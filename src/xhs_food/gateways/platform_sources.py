"""Injected platform source adapters.

This module is deliberately independent from any concrete scraper project.
The provider protocols describe the small synchronous surface that an adapter
needs, while the normalizers terminate provider payloads at the canonical
source contracts.  A concrete Spider_XHS or Dianping client can be injected by
the composition root (or replaced by a sidecar) without importing it here.

One connector instance is intended for one account/session.  Calls are
serialized per instance and synchronous provider methods run in a worker
thread, so event-loop code never shares mutable signer or cookie state.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast, runtime_checkable
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import AnyUrl, TypeAdapter, ValidationError

from xhs_food.contracts import (
    CanonicalAuthor,
    CanonicalMediaRef,
    CanonicalSourceBatch,
    CanonicalSourceComment,
    CanonicalSourceDocument,
    CollectRequest,
    ContractError,
    ContractPayload,
    ErrorCategory,
    ErrorScope,
    IsolationCoordinates,
    MediaType,
    SourceLocator,
)

from .outcomes import single_attempt_coverage


@dataclass(frozen=True, slots=True)
class ProviderEnvelope:
    """Transport-neutral view of a provider result.

    Spider-style clients commonly return ``(success, message, payload)``;
    HTTP clients often return a mapping with ``success``/``code`` fields.  The
    adapters accept both and keep status details out of canonical evidence.
    """

    success: bool
    payload: object = None
    message: str = ""
    code: str | None = None
    status_code: int | None = None


@runtime_checkable
class XhsProviderPort(Protocol):
    """Small synchronous surface implemented by a Spider_XHS bridge."""

    def search_notes(
        self, *, query: str, limit: int, cursor: str | None = None
    ) -> object: ...

    def fetch_note(self, *, external_id: str, url: str | None = None) -> object: ...

    def fetch_comments(
        self, *, external_id: str, cursor: str | None = None
    ) -> object: ...

    def list_media(self, *, external_id: str, url: str | None = None) -> object: ...


@runtime_checkable
class DianpingProviderPort(Protocol):
    """Small synchronous surface implemented by a Dianping bridge."""

    def search_places(
        self, *, query: str, city: str = "", limit: int = 20, cursor: str | None = None
    ) -> object: ...

    def fetch_place(self, *, external_id: str, url: str | None = None) -> object: ...

    def fetch_reviews(
        self, *, external_id: str, cursor: str | None = None
    ) -> object: ...

    def list_media(self, *, external_id: str, url: str | None = None) -> object: ...


class PlatformSourceAdapterError(RuntimeError):
    """Raised when a fetch operation cannot produce a canonical value."""

    def __init__(self, error: ContractError) -> None:
        super().__init__(error.code)
        self.error = error


class _PlatformConnector:
    """Common execution, error, and canonical batch plumbing."""

    source_id: str
    connector_id: str
    connector_version: str
    normalizer_version: str
    _media_method_name: str

    def __init__(
        self,
        provider: object,
        *,
        account_ref: str | None = None,
        clock: Callable[[], datetime] | None = None,
        default_limit: int = 20,
    ) -> None:
        if provider is None:
            raise ValueError("platform provider is required")
        if account_ref is not None and not str(account_ref).strip():
            raise ValueError("account_ref must be non-empty when supplied")
        if default_limit < 1:
            raise ValueError("default_limit must be positive")
        self._provider = provider
        # This value is intentionally not copied into canonical payloads.  It
        # is an internal account-selection hint owned by the composition root.
        self.account_ref = str(account_ref) if account_ref is not None else None
        self._clock = clock or (lambda: datetime.now(UTC))
        self._default_limit = int(default_limit)
        self._call_lock = asyncio.Lock()

    async def _invoke(
        self,
        operation: Callable[..., object],
        *,
        boundary_ref: str,
        **kwargs: object,
    ) -> tuple[ProviderEnvelope | None, ContractError | None]:
        """Run one injected sync operation and coerce its envelope."""

        async with self._call_lock:
            try:
                raw = await asyncio.to_thread(operation, **kwargs)
                # A fake/bridge may accidentally expose an async method.  It
                # is harmless to support it while retaining the sync protocol.
                if inspect.isawaitable(raw):
                    raw = await raw
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # provider boundary: classify, do not leak
                return None, _exception_error(exc, boundary_ref=boundary_ref)
        envelope, error = _coerce_envelope(raw, boundary_ref=boundary_ref)
        if error is not None or envelope is None:
            return envelope, error
        # Provider methods use a value envelope rather than raising for
        # authentication, challenge, rate-limit, and upstream failures.  Turn
        # those outcomes into the shared taxonomy here so every connector
        # operation (including detail and comments) fails closed instead of
        # accidentally treating a ``payload=None`` failure as malformed data.
        if not envelope.success:
            return envelope, _provider_error(envelope, boundary_ref=boundary_ref)
        return envelope, None

    async def aclose(self) -> None:
        """Close an injected provider when it exposes a synchronous ``close``."""

        close = getattr(self._provider, "close", None)
        if close is None:
            return
        if not callable(close):
            return
        async with self._call_lock:
            result = await asyncio.to_thread(close)
            if inspect.isawaitable(result):
                await result

    def _request_query(self, request: CollectRequest) -> str:
        projection = request.source_query_for(self.source_id)
        if projection is not None:
            return projection.text
        query = request.query.query
        return f"{query.geo.locality} {query.intent.subject}".strip()

    def _request_limit(self, request: CollectRequest) -> int:
        # Depth remains a domain policy value; the connector only applies a
        # bounded transport page size.  A future policy can pass a different
        # default_limit without changing the provider contract.
        del request
        return self._default_limit

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("connector clock must return a timezone-aware value")
        return value.astimezone(UTC)

    def _batch(
        self,
        request: CollectRequest,
        *,
        documents: Sequence[CanonicalSourceDocument] = (),
        comments: Sequence[CanonicalSourceComment] = (),
        authors: Sequence[CanonicalAuthor] = (),
        media_refs: Sequence[CanonicalMediaRef] = (),
        watermark: str | None = None,
        next_cursor: str | None = None,
        errors: Sequence[ContractError] = (),
        attempt_id: str,
    ) -> CanonicalSourceBatch:
        all_items = (*documents, *comments, *authors, *media_refs)
        error_values = tuple(errors)
        return CanonicalSourceBatch(
            isolation=request.query.isolation,
            source_id=self.source_id,
            connector_id=self.connector_id,
            connector_version=self.connector_version,
            normalizer_version=self.normalizer_version,
            documents=tuple(documents),
            comments=tuple(comments),
            authors=tuple(authors),
            media_refs=tuple(media_refs),
            watermark=watermark,
            next_cursor=next_cursor,
            errors=error_values,
            coverage=single_attempt_coverage(
                attempt_id=attempt_id,
                boundary_ref=self.connector_id,
                item_count=len(all_items),
                watermark=watermark,
                errors=error_values,
            ),
        )

    def _ref_is_owned(self, ref: SourceLocator) -> None:
        if ref.source_id != self.source_id:
            raise ValueError("source locator does not belong to this connector")

    def _failure_batch(
        self,
        request: CollectRequest,
        error: ContractError,
        *,
        attempt_id: str,
    ) -> CanonicalSourceBatch:
        return self._batch(request, errors=(error,), attempt_id=attempt_id)

    def _provider_method(
        self,
        name: str,
        *,
        boundary_ref: str,
    ) -> tuple[Callable[..., object] | None, ContractError | None]:
        """Resolve an optional bridge method without leaking ``AttributeError``.

        Provider checkouts are independently versioned.  A pinned checkout may
        be present while one optional capability is absent; that condition is
        a provider dependency outcome, not an application exception.
        """

        method = getattr(self._provider, name, None)
        if callable(method):
            return cast(Callable[..., object], method), None
        return None, _error(
            "PROVIDER_CAPABILITY_UNAVAILABLE",
            ErrorCategory.DEPENDENCY_UNAVAILABLE,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=True,
            message=f"provider method {name} is unavailable",
        )


class XhsPlatformSourceConnector(_PlatformConnector):
    """Canonical read connector over an injected Spider_XHS-style provider."""

    source_id = "xhs"
    connector_id = "xhs.platform"
    connector_version = "xhs-platform/v1"
    normalizer_version = "xhs-normalizer/v1"
    _media_method_name = "list_media"

    def __init__(
        self,
        provider: XhsProviderPort,
        *,
        channel: str = "xhs_pc",
        account_ref: str | None = None,
        clock: Callable[[], datetime] | None = None,
        default_limit: int = 20,
    ) -> None:
        channel_value = str(channel).strip().casefold()
        if channel_value not in {"xhs_pc", "xhs_creator"}:
            raise ValueError("XHS channel must be xhs_pc or xhs_creator")
        self.channel = channel_value
        super().__init__(
            provider,
            account_ref=account_ref,
            clock=clock,
            default_limit=default_limit,
        )

    @property
    def platform_channel(self) -> str:
        """Return the account namespace used for this connector instance."""

        return self.channel

    async def publish(self, *args: object, **_: object) -> None:
        """Keep Creator publishing outside this read-only source boundary."""

        del args
        raise PlatformSourceAdapterError(
            _error(
                "CAPABILITY_UNREGISTERED",
                ErrorCategory.POLICY_DENIED,
                boundary_ref="xhs.publish",
                retryable=False,
            )
        )

    async def search(self, request: CollectRequest) -> CanonicalSourceBatch:
        method, method_error = self._provider_method(
            "search_notes", boundary_ref="xhs.search_notes"
        )
        if method_error is not None or method is None:
            return self._failure_batch(
                request,
                method_error
                or _error(
                    "PROVIDER_CAPABILITY_UNAVAILABLE",
                    ErrorCategory.DEPENDENCY_UNAVAILABLE,
                    boundary_ref="xhs.search_notes",
                    scope=ErrorScope.PROVIDER,
                    retryable=True,
                ),
                attempt_id="xhs.search",
            )
        raw, error = await self._invoke(
            method,
            boundary_ref="xhs.search_notes",
            query=self._request_query(request),
            limit=self._request_limit(request),
            cursor=request.cursor,
        )
        if error is not None:
            return self._failure_batch(request, error, attempt_id="xhs.search")
        assert raw is not None
        payload = raw.payload
        items = _extract_items(payload, ("notes", "items", "results", "list"))
        if items is None:
            malformed = _malformed("XHS_NOTES_MALFORMED", "xhs.search_notes")
            return self._failure_batch(request, malformed, attempt_id="xhs.search")
        documents: list[CanonicalSourceDocument] = []
        authors: list[CanonicalAuthor] = []
        errors: list[ContractError] = []
        seen_documents: set[str] = set()
        seen_authors: set[str] = set()
        for index, item in enumerate(items):
            document, author, item_error = self._normalize_note(item, index=index)
            if document is not None and document.external_id not in seen_documents:
                documents.append(document)
                seen_documents.add(document.external_id)
            if author is not None and author.external_id not in seen_authors:
                authors.append(author)
                seen_authors.add(author.external_id)
            if item_error is not None:
                errors.append(item_error)
        watermark, next_cursor = _cursor_values(payload)
        return self._batch(
            request,
            documents=documents,
            authors=authors,
            watermark=watermark,
            next_cursor=next_cursor,
            errors=errors,
            attempt_id="xhs.search",
        )

    async def fetch_document(self, ref: SourceLocator) -> CanonicalSourceDocument:
        self._ref_is_owned(ref)
        method, method_error = self._provider_method(
            "fetch_note", boundary_ref="xhs.fetch_note"
        )
        if method_error is not None or method is None:
            raise PlatformSourceAdapterError(
                method_error
                or _error(
                    "PROVIDER_CAPABILITY_UNAVAILABLE",
                    ErrorCategory.DEPENDENCY_UNAVAILABLE,
                    boundary_ref="xhs.fetch_note",
                    scope=ErrorScope.PROVIDER,
                    retryable=True,
                )
            )
        raw, error = await self._invoke(
            method,
            boundary_ref="xhs.fetch_note",
            external_id=ref.external_id,
            url=str(ref.canonical_url),
        )
        if error is not None:
            raise PlatformSourceAdapterError(error)
        assert raw is not None
        item = _extract_mapping(raw.payload, ("note", "data", "item"))
        document, _, item_error = self._normalize_note(item, index=0)
        if document is None or item_error is not None:
            raise PlatformSourceAdapterError(
                item_error or _malformed("XHS_NOTE_MALFORMED", "xhs.fetch_note")
            )
        return document

    async def fetch_comments(
        self, document_ref: SourceLocator, cursor: str | None = None
    ) -> CanonicalSourceBatch:
        self._ref_is_owned(document_ref)
        method, method_error = self._provider_method(
            "fetch_comments", boundary_ref="xhs.fetch_comments"
        )
        isolation_request = _request_from_locator(document_ref)
        if method_error is not None or method is None:
            return self._failure_batch(
                isolation_request,
                method_error
                or _error(
                    "PROVIDER_CAPABILITY_UNAVAILABLE",
                    ErrorCategory.DEPENDENCY_UNAVAILABLE,
                    boundary_ref="xhs.fetch_comments",
                    scope=ErrorScope.PROVIDER,
                    retryable=True,
                ),
                attempt_id="xhs.comments",
            )
        raw, error = await self._invoke(
            method,
            boundary_ref="xhs.fetch_comments",
            external_id=document_ref.external_id,
            cursor=cursor,
        )
        if error is not None:
            return self._failure_batch(
                isolation_request, error, attempt_id="xhs.comments"
            )
        assert raw is not None
        items = _extract_items(raw.payload, ("comments", "items", "results", "list"))
        if items is None:
            malformed = _malformed("XHS_COMMENTS_MALFORMED", "xhs.fetch_comments")
            return self._failure_batch(
                isolation_request, malformed, attempt_id="xhs.comments"
            )
        comments: list[CanonicalSourceComment] = []
        media_refs: list[CanonicalMediaRef] = []
        errors: list[ContractError] = []
        seen_comments: set[str] = set()
        seen_media: set[tuple[str, str]] = set()
        for index, item in enumerate(_flatten_nested_comments(items)):
            comment, item_error = self._normalize_comment(
                item, document_id=document_ref.external_id, index=index
            )
            if comment is not None and comment.external_id not in seen_comments:
                comments.append(comment)
                seen_comments.add(comment.external_id)
                mapping = _as_mapping(item)
                if mapping is not None:
                    for media in _normalize_media_items(
                        source_id=self.source_id,
                        owner_id=comment.external_id,
                        owner_type="comment",
                        items=_media_items_from_attributes(mapping),
                        captured_at=self._now(),
                    ):
                        media_key = (media.external_id, str(media.canonical_url))
                        if media_key not in seen_media:
                            media_refs.append(media)
                            seen_media.add(media_key)
            if item_error is not None:
                errors.append(item_error)
        watermark, next_cursor = _cursor_values(raw.payload)
        return self._batch(
            isolation_request,
            comments=comments,
            media_refs=media_refs,
            watermark=watermark or document_ref.watermark,
            next_cursor=next_cursor,
            errors=errors,
            attempt_id="xhs.comments",
        )

    async def list_media_refs(
        self, owner_ref: SourceLocator
    ) -> tuple[CanonicalMediaRef, ...]:
        self._ref_is_owned(owner_ref)
        method = getattr(self._provider, self._media_method_name, None)
        if callable(method):
            raw, error = await self._invoke(
                method,
                boundary_ref="xhs.list_media",
                external_id=owner_ref.external_id,
                url=str(owner_ref.canonical_url),
            )
            # A media lookup is an evidence operation, not an optional
            # decoration.  Returning ``()`` for an upstream error would make
            # an unavailable/challenged provider indistinguishable from a
            # legitimate document with no media and would let the gateway
            # publish a false success-empty outcome.  Preserve the shared
            # provider taxonomy so AccountBoundSourceGateway can quarantine
            # or retry according to policy.
            if error is not None:
                raise PlatformSourceAdapterError(error)
            if raw is None:
                raise PlatformSourceAdapterError(
                    _malformed("XHS_MEDIA_RESPONSE_MALFORMED", "xhs.list_media")
                )
            items = _extract_items(
                raw.payload,
                (
                    "media",
                    "images",
                    "image_list",
                    "imageList",
                    "photos",
                    "pictures",
                    "items",
                    "list",
                ),
            )
            if items is None:
                # Some pinned Spider_XHS snapshots expose images only in the
                # detail response.  Keep that compatibility fallback, but
                # propagate its error rather than silently swallowing it.
                document = await self.fetch_document(owner_ref)
                items = _media_items_from_attributes(document.attributes)
        else:
            document = await self.fetch_document(owner_ref)
            items = _media_items_from_attributes(document.attributes)
        return _normalize_media_items(
            source_id=self.source_id,
            owner_id=owner_ref.external_id,
            items=items or (),
            captured_at=self._now(),
        )

    def _normalize_note(
        self, item: object, *, index: int
    ) -> tuple[CanonicalSourceDocument | None, CanonicalAuthor | None, ContractError | None]:
        mapping = _as_mapping(item)
        if mapping is None:
            return None, None, _malformed("XHS_ITEM_MALFORMED", "xhs.normalizer")
        # Spider_XHS search/feed responses put the public fields below a
        # ``note_card`` object while retaining the stable id/url at the item
        # level.  Overlay the nested card only for field lookup; keep the
        # original (redacted) payload in attributes for provenance.
        note_card = _as_mapping(mapping.get("note_card"))
        view = _overlay_mapping(mapping, note_card)
        external_id = _first_text(view, "id", "note_id", "noteId", "source_note_id")
        if not external_id:
            return None, None, _malformed("XHS_ITEM_ID_MISSING", "xhs.normalizer")
        url = _stable_url_or_fallback(
            _first_text(view, "url", "note_url", "noteUrl"),
            f"https://www.xiaohongshu.com/explore/{quote(external_id, safe='')}",
        )
        author = self._normalize_author(
            _first_value(view, "user", "author", "user_info"), view, external_id
        )
        try:
            document = CanonicalSourceDocument(
                source_id=self.source_id,
                external_id=external_id,
                canonical_url=AnyUrl(url),
                captured_at=self._now(),
                source_updated_at=_parse_timestamp(
                    _first_value(
                        view,
                        "updated_at",
                        "updatedAt",
                        "created_at",
                        "createdAt",
                        "time",
                        "timestamp",
                    )
                ),
                author_external_id=(
                    author.external_id
                    if author
                    else _first_text(view, "user_id", "userId", "author_id", "authorId")
                ),
                title=_first_text(view, "title", "note_title", "noteTitle"),
                text=_first_text(view, "full_desc", "desc", "content", "description"),
                attributes=_safe_mapping(mapping),
            )
        except (ValidationError, ValueError, TypeError):
            return None, author, _malformed("XHS_ITEM_MALFORMED", "xhs.normalizer")
        del index
        return document, author, None

    def _normalize_author(
        self, user_value: object, item: Mapping[str, Any], document_id: str
    ) -> CanonicalAuthor | None:
        user = _as_mapping(user_value)
        if user is None and any(
            key in item for key in ("user_id", "userId", "author_id", "authorId")
        ):
            user = item
        if user is None:
            return None
        # Some PC payloads wrap profile fields in ``basic_info``; flatten that
        # view without mutating the provider object.
        user = _overlay_mapping(user, _as_mapping(user.get("basic_info")))
        external_id = _first_text(user, "user_id", "userId", "id", "author_id")
        if not external_id:
            return None
        url = _stable_url_or_fallback(
            _first_text(user, "home_url", "homeUrl", "url"),
            f"https://www.xiaohongshu.com/user/profile/{quote(external_id, safe='')}",
        )
        try:
            return CanonicalAuthor(
                source_id=self.source_id,
                external_id=external_id,
                canonical_url=AnyUrl(url),
                captured_at=self._now(),
                display_name=_first_text(user, "nickname", "name"),
                attributes=_safe_mapping(user),
            )
        except (ValidationError, ValueError, TypeError):
            del document_id
            return None

    def _normalize_comment(
        self, item: object, *, document_id: str, index: int
    ) -> tuple[CanonicalSourceComment | None, ContractError | None]:
        mapping = _as_mapping(item)
        if mapping is None:
            return None, _malformed("XHS_COMMENT_MALFORMED", "xhs.normalizer")
        view = _overlay_mapping(
            mapping,
            _as_mapping(mapping.get("comment_info")),
        )
        external_id = _first_text(view, "id", "comment_id", "commentId")
        if not external_id:
            return None, _malformed("XHS_COMMENT_ID_MISSING", "xhs.normalizer")
        author = _as_mapping(
            _first_value(view, "user", "user_info", "author", "author_info")
        )
        author = _overlay_mapping(author, _as_mapping(author.get("basic_info"))) if author else None
        author_id = _first_text(view, "user_id", "userId", "author_id", "authorId") or (
            _first_text(author, "user_id", "userId", "id") if author else None
        )
        try:
            return (
                CanonicalSourceComment(
                    source_id=self.source_id,
                    external_id=external_id,
                    document_external_id=document_id,
                    canonical_url=AnyUrl(
                        _stable_url_or_fallback(
                            _first_text(mapping, "url", "comment_url"),
                            f"https://www.xiaohongshu.com/explore/{quote(document_id, safe='')}",
                        )
                    ),
                    captured_at=self._now(),
                    source_updated_at=_parse_timestamp(
                        _first_value(
                            view,
                            "updated_at",
                            "updatedAt",
                            "created_at",
                            "createdAt",
                            "create_time",
                            "time",
                            "timestamp",
                        )
                    ),
                    author_external_id=author_id,
                    text=_first_text(view, "content", "text", "desc"),
                    attributes=_safe_mapping(mapping),
                ),
                None,
            )
        except (ValidationError, ValueError, TypeError):
            del index
            return None, _malformed("XHS_COMMENT_MALFORMED", "xhs.normalizer")


class DianpingPlatformSourceConnector(_PlatformConnector):
    """Canonical read connector over an injected Dianping provider."""

    source_id = "dianping"
    connector_id = "dianping.platform"
    connector_version = "dianping-platform/v1"
    normalizer_version = "dianping-normalizer/v1"
    _media_method_name = "list_media"

    def __init__(
        self,
        provider: DianpingProviderPort,
        *,
        account_ref: str | None = None,
        clock: Callable[[], datetime] | None = None,
        default_limit: int = 20,
    ) -> None:
        super().__init__(
            provider,
            account_ref=account_ref,
            clock=clock,
            default_limit=default_limit,
        )

    @property
    def platform_channel(self) -> str:
        return "dianping"

    async def search(self, request: CollectRequest) -> CanonicalSourceBatch:
        method, method_error = self._provider_method(
            "search_places", boundary_ref="dianping.search_places"
        )
        if method_error is not None or method is None:
            return self._failure_batch(
                request,
                method_error
                or _error(
                    "PROVIDER_CAPABILITY_UNAVAILABLE",
                    ErrorCategory.DEPENDENCY_UNAVAILABLE,
                    boundary_ref="dianping.search_places",
                    scope=ErrorScope.PROVIDER,
                    retryable=True,
                ),
                attempt_id="dianping.search",
            )
        projection = request.source_query_for(self.source_id)
        city = projection.locality if projection is not None else request.query.query.geo.locality
        raw, error = await self._invoke(
            method,
            boundary_ref="dianping.search_places",
            query=self._request_query(request),
            city=city,
            limit=self._request_limit(request),
            cursor=request.cursor,
        )
        if error is not None:
            return self._failure_batch(request, error, attempt_id="dianping.search")
        assert raw is not None
        items = _extract_items(
            raw.payload,
            ("pois", "shops", "places", "items", "results", "list"),
        )
        if items is None:
            malformed = _malformed("DIANPING_ITEMS_MALFORMED", "dianping.search_places")
            return self._failure_batch(request, malformed, attempt_id="dianping.search")
        documents: list[CanonicalSourceDocument] = []
        errors: list[ContractError] = []
        seen: set[str] = set()
        for item in items:
            document, item_error = self._normalize_place(item)
            if document is not None and document.external_id not in seen:
                documents.append(document)
                seen.add(document.external_id)
            if item_error is not None:
                errors.append(item_error)
        watermark, next_cursor = _cursor_values(raw.payload)
        return self._batch(
            request,
            documents=documents,
            watermark=watermark,
            next_cursor=next_cursor,
            errors=errors,
            attempt_id="dianping.search",
        )

    async def fetch_document(self, ref: SourceLocator) -> CanonicalSourceDocument:
        self._ref_is_owned(ref)
        method, method_error = self._provider_method(
            "fetch_place", boundary_ref="dianping.fetch_place"
        )
        if method_error is not None or method is None:
            raise PlatformSourceAdapterError(
                method_error
                or _error(
                    "PROVIDER_CAPABILITY_UNAVAILABLE",
                    ErrorCategory.DEPENDENCY_UNAVAILABLE,
                    boundary_ref="dianping.fetch_place",
                    scope=ErrorScope.PROVIDER,
                    retryable=True,
                )
            )
        raw, error = await self._invoke(
            method,
            boundary_ref="dianping.fetch_place",
            external_id=ref.external_id,
            url=str(ref.canonical_url),
        )
        if error is not None:
            raise PlatformSourceAdapterError(error)
        assert raw is not None
        item = _extract_mapping(raw.payload, ("place", "shop", "poi", "data", "item"))
        document, item_error = self._normalize_place(item)
        if document is None or item_error is not None:
            raise PlatformSourceAdapterError(
                item_error or _malformed("DIANPING_PLACE_MALFORMED", "dianping.fetch_place")
            )
        return document

    async def fetch_comments(
        self, document_ref: SourceLocator, cursor: str | None = None
    ) -> CanonicalSourceBatch:
        self._ref_is_owned(document_ref)
        method, method_error = self._provider_method(
            "fetch_reviews", boundary_ref="dianping.fetch_reviews"
        )
        isolation_request = _request_from_locator(document_ref)
        if method_error is not None or method is None:
            return self._failure_batch(
                isolation_request,
                method_error
                or _error(
                    "PROVIDER_CAPABILITY_UNAVAILABLE",
                    ErrorCategory.DEPENDENCY_UNAVAILABLE,
                    boundary_ref="dianping.fetch_reviews",
                    scope=ErrorScope.PROVIDER,
                    retryable=True,
                ),
                attempt_id="dianping.reviews",
            )
        raw, error = await self._invoke(
            method,
            boundary_ref="dianping.fetch_reviews",
            external_id=document_ref.external_id,
            cursor=cursor,
        )
        if error is not None:
            return self._failure_batch(
                isolation_request, error, attempt_id="dianping.reviews"
            )
        assert raw is not None
        items = _extract_items(
            raw.payload, ("reviews", "comments", "items", "results", "list")
        )
        if items is None:
            malformed = _malformed("DIANPING_REVIEWS_MALFORMED", "dianping.fetch_reviews")
            return self._failure_batch(
                isolation_request, malformed, attempt_id="dianping.reviews"
            )
        comments: list[CanonicalSourceComment] = []
        media_refs: list[CanonicalMediaRef] = []
        errors: list[ContractError] = []
        seen_reviews: set[str] = set()
        seen_media: set[tuple[str, str]] = set()
        for index, item in enumerate(items):
            comment, item_error = self._normalize_review(
                item, document_id=document_ref.external_id, index=index
            )
            if comment is not None and comment.external_id not in seen_reviews:
                comments.append(comment)
                seen_reviews.add(comment.external_id)
                mapping = _as_mapping(item)
                if mapping is not None:
                    for media in _normalize_media_items(
                        source_id=self.source_id,
                        owner_id=comment.external_id,
                        owner_type="comment",
                        items=_media_items_from_attributes(mapping),
                        captured_at=self._now(),
                    ):
                        media_key = (media.external_id, str(media.canonical_url))
                        if media_key not in seen_media:
                            media_refs.append(media)
                            seen_media.add(media_key)
            if item_error is not None:
                errors.append(item_error)
        watermark, next_cursor = _cursor_values(raw.payload)
        return self._batch(
            isolation_request,
            comments=comments,
            media_refs=media_refs,
            watermark=watermark or document_ref.watermark,
            next_cursor=next_cursor,
            errors=errors,
            attempt_id="dianping.reviews",
        )

    async def list_media_refs(
        self, owner_ref: SourceLocator
    ) -> tuple[CanonicalMediaRef, ...]:
        self._ref_is_owned(owner_ref)
        method = getattr(self._provider, self._media_method_name, None)
        if callable(method):
            raw, error = await self._invoke(
                method,
                boundary_ref="dianping.list_media",
                external_id=owner_ref.external_id,
                url=str(owner_ref.canonical_url),
            )
            # Preserve provider failures.  Empty media is a valid successful
            # result only when the provider actually returned a valid empty
            # collection; an auth/challenge/dependency response must reach
            # the account gateway as a typed error.
            if error is not None:
                raise PlatformSourceAdapterError(error)
            if raw is None:
                raise PlatformSourceAdapterError(
                    _malformed("DIANPING_MEDIA_RESPONSE_MALFORMED", "dianping.list_media")
                )
            items = _extract_items(
                raw.payload,
                (
                    "media",
                    "images",
                    "image_list",
                    "imageList",
                    "photos",
                    "pictures",
                    "items",
                    "list",
                ),
            )
            if items is None:
                # Older Dianping protocol snapshots return photos only in the
                # place-detail payload.  Fall back to detail while retaining
                # any typed failure from that call.
                document = await self.fetch_document(owner_ref)
                items = _media_items_from_attributes(document.attributes)
        else:
            document = await self.fetch_document(owner_ref)
            items = _media_items_from_attributes(document.attributes)
        return _normalize_media_items(
            source_id=self.source_id,
            owner_id=owner_ref.external_id,
            items=items or (),
            captured_at=self._now(),
        )

    def _normalize_place(
        self, item: object
    ) -> tuple[CanonicalSourceDocument | None, ContractError | None]:
        mapping = _as_mapping(item)
        if mapping is None:
            return None, _malformed("DIANPING_ITEM_MALFORMED", "dianping.normalizer")
        external_id = _first_text(mapping, "shop_id", "shopId", "poi_id", "poiId", "id", "idStr")
        if not external_id:
            return None, _malformed("DIANPING_ITEM_ID_MISSING", "dianping.normalizer")
        url = _stable_url_or_fallback(
            _first_text(mapping, "url", "shop_url", "shopUrl", "detail_url"),
            f"https://www.dianping.com/shop/{quote(external_id, safe='')}",
        )
        try:
            return (
                CanonicalSourceDocument(
                    source_id=self.source_id,
                    external_id=external_id,
                    canonical_url=AnyUrl(url),
                    captured_at=self._now(),
                    source_updated_at=_parse_timestamp(
                        _first_value(mapping, "updated_at", "updatedAt", "update_time")
                    ),
                    title=_first_text(mapping, "name", "shop_name", "shopName", "title"),
                    text=_first_text(
                        mapping,
                        "address",
                        "address_text",
                        "description",
                        "desc",
                        "business_area",
                    ),
                    attributes=_safe_mapping(mapping),
                ),
                None,
            )
        except (ValidationError, ValueError, TypeError):
            return None, _malformed("DIANPING_ITEM_MALFORMED", "dianping.normalizer")

    def _normalize_review(
        self, item: object, *, document_id: str, index: int
    ) -> tuple[CanonicalSourceComment | None, ContractError | None]:
        mapping = _as_mapping(item)
        if mapping is None:
            return None, _malformed("DIANPING_REVIEW_MALFORMED", "dianping.normalizer")
        view = _overlay_mapping(
            mapping,
            _as_mapping(mapping.get("review")),
            _as_mapping(mapping.get("review_info")),
        )
        external_id = _first_text(
            view, "review_id", "reviewId", "comment_id", "commentId", "id"
        )
        if not external_id:
            return None, _malformed("DIANPING_REVIEW_ID_MISSING", "dianping.normalizer")
        reviewer = _as_mapping(
            _first_value(view, "user", "user_info", "author", "author_info")
        )
        reviewer = (
            _overlay_mapping(reviewer, _as_mapping(reviewer.get("basic_info")))
            if reviewer
            else None
        )
        try:
            return (
                CanonicalSourceComment(
                    source_id=self.source_id,
                    external_id=external_id,
                    document_external_id=document_id,
                    canonical_url=AnyUrl(
                        _stable_url_or_fallback(
                            _first_text(mapping, "url", "review_url"),
                            f"https://www.dianping.com/shop/{quote(document_id, safe='')}",
                        )
                    ),
                    captured_at=self._now(),
                    source_updated_at=_parse_timestamp(
                        _first_value(
                            view,
                            "updated_at",
                            "updatedAt",
                            "created_at",
                            "createdAt",
                            "time",
                            "timestamp",
                        )
                    ),
                    author_external_id=(
                        _first_text(view, "user_id", "userId", "author_id", "authorId")
                        or (
                            _first_text(reviewer, "user_id", "userId", "id", "author_id")
                            if reviewer
                            else None
                        )
                    ),
                    text=_first_text(
                        view, "content", "text", "review_content", "comment"
                    ),
                    attributes=_safe_mapping(mapping),
                ),
                None,
            )
        except (ValidationError, ValueError, TypeError):
            del index
            return None, _malformed("DIANPING_REVIEW_MALFORMED", "dianping.normalizer")


class XhsPcSourceConnector(XhsPlatformSourceConnector):
    """Explicit PC-channel spelling for composition-root registrations."""

    def __init__(
        self,
        provider: XhsProviderPort,
        *,
        account_ref: str | None = None,
        clock: Callable[[], datetime] | None = None,
        default_limit: int = 20,
    ) -> None:
        super().__init__(
            provider,
            channel="xhs_pc",
            account_ref=account_ref,
            clock=clock,
            default_limit=default_limit,
        )


class XhsCreatorSourceConnector(XhsPlatformSourceConnector):
    """Read-only Creator-channel connector; publishing is not registered."""

    def __init__(
        self,
        provider: XhsProviderPort,
        *,
        account_ref: str | None = None,
        clock: Callable[[], datetime] | None = None,
        default_limit: int = 20,
    ) -> None:
        super().__init__(
            provider,
            channel="xhs_creator",
            account_ref=account_ref,
            clock=clock,
            default_limit=default_limit,
        )

    async def fetch_document(self, ref: SourceLocator) -> CanonicalSourceDocument:
        """Creator Studio has no public note-detail endpoint in the pin."""

        self._ref_is_owned(ref)
        raise PlatformSourceAdapterError(
            _error(
                "CAPABILITY_UNREGISTERED",
                ErrorCategory.POLICY_DENIED,
                boundary_ref="xhs_creator.notes.detail",
                retryable=False,
            )
        )

    async def fetch_comments(
        self, document_ref: SourceLocator, cursor: str | None = None
    ) -> CanonicalSourceBatch:
        """Creator Studio does not expose the PC comment API."""

        del cursor
        self._ref_is_owned(document_ref)
        request = _request_from_locator(document_ref)
        return self._failure_batch(
            request,
            _error(
                "CAPABILITY_UNREGISTERED",
                ErrorCategory.POLICY_DENIED,
                boundary_ref="xhs_creator.reviews.search",
                retryable=False,
            ),
            attempt_id="xhs.creator.comments",
        )

    async def list_media_refs(
        self, owner_ref: SourceLocator
    ) -> tuple[CanonicalMediaRef, ...]:
        """Do not turn an unavailable Creator detail API into empty media."""

        self._ref_is_owned(owner_ref)
        raise PlatformSourceAdapterError(
            _error(
                "CAPABILITY_UNREGISTERED",
                ErrorCategory.POLICY_DENIED,
                boundary_ref="xhs_creator.media.refs",
                retryable=False,
            )
        )

    async def health_check(self) -> bool:
        """Use the Creator ``user/info`` read probe for account health."""

        method, method_error = self._provider_method("health_check", boundary_ref="xhs_creator.health")
        if method_error is not None or method is None:
            return False
        raw, error = await self._invoke(
            method,
            boundary_ref="xhs_creator.health",
        )
        return error is None and raw is not None and raw.success


# Names used in the architecture/design documents remain available while the
# explicit ``Platform`` names make the adapter boundary obvious in code.
SpiderXhsSourceConnector = XhsPlatformSourceConnector
DianpingSourceConnector = DianpingPlatformSourceConnector


def _coerce_envelope(
    raw: object, *, boundary_ref: str
) -> tuple[ProviderEnvelope | None, ContractError | None]:
    """Coerce tuple, mapping, dataclass-like, or direct payload results."""

    if isinstance(raw, ProviderEnvelope):
        return raw, None
    if isinstance(raw, (tuple, list)):
        # The audited Spider clients return ``(ok, message, payload)``.  A few
        # wrappers collapse that to ``(ok, payload)``; accepting both keeps the
        # adapter boundary small without importing either wrapper's result
        # class.  Extra code/status slots are optional and remain diagnostics.
        if not raw:
            # A direct empty list is a valid empty collection response.  It is
            # distinct from an empty *tuple envelope* because there is no
            # outcome marker to coerce.
            return ProviderEnvelope(True, payload=[]), None
        success = _coerce_bool_marker(raw[0])
        if success is None:
            # A bare JSON list is a valid direct collection response.  Tuples,
            # however, are the documented Spider-style envelope shape; a
            # non-boolean first tuple slot is therefore malformed rather than
            # silently promoted to an item payload.
            if isinstance(raw, tuple):
                return None, _malformed("PROVIDER_RESULT_ENVELOPE_MALFORMED", boundary_ref)
            return ProviderEnvelope(True, payload=list(raw)), None
        message = ""
        payload: object = None
        code: str | None = None
        status_code: int | None = None
        if len(raw) >= 3:
            message = _text_or_none(raw[1]) or ""
            payload = raw[2]
            code = _text_or_none(raw[3]) if len(raw) > 3 else None
            status_code = _int_or_none(raw[4]) if len(raw) > 4 else None
        elif len(raw) == 2:
            # A string second element conventionally denotes an error message;
            # otherwise it is the successful payload.
            if isinstance(raw[1], str) and not success:
                message = raw[1]
            elif isinstance(raw[1], Mapping) and not success:
                payload_mapping = raw[1]
                payload = payload_mapping.get(
                    "data", payload_mapping.get("payload", payload_mapping.get("result"))
                )
                if payload is None:
                    payload = payload_mapping
                message = _text_or_none(
                    payload_mapping.get("msg")
                    or payload_mapping.get("message")
                    or payload_mapping.get("error")
                ) or ""
                code = _text_or_none(
                    payload_mapping.get("error_code", payload_mapping.get("code"))
                )
                status_code = _int_or_none(
                    payload_mapping.get("status_code", payload_mapping.get("status"))
                )
            else:
                payload = raw[1]
        if not success and isinstance(payload, Mapping):
            # Spider wrappers sometimes put the HTTP/code marker inside the
            # third tuple element instead of allocating a fourth slot.
            code = code or _text_or_none(
                payload.get("error_code", payload.get("code"))
            )
            status_code = status_code or _int_or_none(
                payload.get("status_code", payload.get("status"))
            )
            if not message:
                message = _text_or_none(
                    payload.get("msg")
                    or payload.get("message")
                    or payload.get("error")
                ) or ""
        return ProviderEnvelope(success, payload, message, code, status_code), None
    if isinstance(raw, Mapping):
        # A plain payload without an outcome marker is a successful response.
        # Dianping snapshots use ``status: success|error`` rather than a bool;
        # map that spelling while retaining the whole mapping as payload when
        # it carries top-level ``items``/``shops`` fields.
        has_outcome_marker = "success" in raw or "ok" in raw
        marker = _coerce_bool_marker(raw.get("success", raw.get("ok")))
        status_value = raw.get("status")
        status_code = _int_or_none(raw.get("status_code", status_value))
        raw_code = raw.get("error_code", raw.get("code"))
        code_status = _int_or_none(raw_code)
        if status_code is None and code_status is not None and code_status >= 100:
            status_code = code_status
        if marker is None and "status" in raw:
            status_text = str(status_value or "").casefold()
            if status_text in {"success", "ok", "succeeded", "0"}:
                marker = True
            elif status_text in {
                "error",
                "failed",
                "failure",
                "forbidden",
                "unauthorized",
                "expired",
                "challenge",
                "rate_limited",
                "rate-limit",
            } or (status_code is not None and status_code >= 400):
                marker = False
        if marker is None and status_code is not None and status_code >= 400:
            marker = False
        if marker is None and _is_failure_code(raw_code):
            marker = False
        if marker is None and has_outcome_marker:
            return None, _malformed("PROVIDER_RESULT_ENVELOPE_MALFORMED", boundary_ref)
        if marker is None:
            return ProviderEnvelope(True, payload=raw), None
        success = marker
        payload = raw.get("data", raw.get("payload", raw.get("result")))
        if payload is None and success:
            payload = raw
        return (
            ProviderEnvelope(
                success=success,
                payload=payload,
                message=_text_or_none(
                    raw.get("msg") or raw.get("message") or raw.get("error")
                )
                or "",
                code=_text_or_none(raw.get("error_code", raw.get("code"))),
                status_code=status_code,
            ),
            None,
        )
    # Duck-typed ProviderResult objects are accepted without importing their
    # defining module (important for optional external projects).
    success = _coerce_bool_marker(getattr(raw, "success", getattr(raw, "ok", None)))
    if isinstance(success, bool):
        return (
            ProviderEnvelope(
                success=success,
                payload=getattr(
                    raw,
                    "data",
                    getattr(raw, "payload", getattr(raw, "result", None)),
                ),
                message=_text_or_none(
                    getattr(raw, "error_message", getattr(raw, "message", ""))
                )
                or "",
                code=_text_or_none(
                    getattr(raw, "error_code", getattr(raw, "code", None))
                ),
                status_code=_int_or_none(getattr(raw, "status_code", None)),
            ),
            None,
        )
    return None, _malformed("PROVIDER_RESULT_ENVELOPE_MALFORMED", boundary_ref)


def _exception_error(exc: BaseException, *, boundary_ref: str) -> ContractError:
    diagnostic = str(exc) or None
    exception_code = _text_or_none(getattr(exc, "code", None)) or ""
    lowered = f"{exception_code} {diagnostic or ''}".casefold()
    response = getattr(exc, "response", None)
    # ``requests``/httpx attach status to ``response`` while curl-style
    # provider exceptions often expose it directly.  Accept both shapes at
    # this boundary so 403 challenge/auth and 429 outcomes remain stable.
    status = _int_or_none(getattr(response, "status_code", None))
    if status is None:
        status = _int_or_none(getattr(exc, "status_code", None))
    if status == 403 and _is_challenge_signal(exception_code, diagnostic):
        return _error(
            "SOURCE_CHALLENGE_REQUIRED",
            ErrorCategory.RATE_LIMITED,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=True,
            message=diagnostic,
        )
    if status in {401, 403}:
        return _error(
            "AUTH_EXPIRED",
            ErrorCategory.POLICY_DENIED,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=False,
            message=diagnostic,
        )
    if status == 429:
        return _error(
            "SOURCE_RATE_LIMITED",
            ErrorCategory.RATE_LIMITED,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=True,
            message=diagnostic,
        )
    if status is not None and status >= 500:
        return _error(
            "SOURCE_DEPENDENCY_UNAVAILABLE",
            ErrorCategory.DEPENDENCY_UNAVAILABLE,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=True,
            message=diagnostic,
        )
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or any(
        marker in lowered for marker in ("timed out", "timeout")
    ):
        return _error(
            "SOURCE_TIMEOUT",
            ErrorCategory.TIMEOUT,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=True,
            message=diagnostic,
        )
    if isinstance(exc, (ConnectionError, OSError)) or any(
        marker in lowered
        for marker in (
            "connection reset",
            "connection refused",
            "connection error",
            "failed to establish a new connection",
            "name or service not known",
            "temporarily unavailable",
        )
    ):
        return _error(
            "SOURCE_DEPENDENCY_UNAVAILABLE",
            ErrorCategory.DEPENDENCY_UNAVAILABLE,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=True,
            message=diagnostic,
        )
    # Risk/verification responses often arrive as an HTTP 403 exception.  A
    # challenge signal takes precedence over the generic forbidden marker so
    # callers can apply a bounded retry/quarantine policy instead of forcing
    # an unnecessary re-login.
    if any(
        marker in lowered
        for marker in (
            "429",
            "rate limit",
            "too many requests",
            "risk control",
            "challenge",
            "captcha",
            "verification",
            "geetest",
        )
    ):
        return _error(
            "SOURCE_CHALLENGE_REQUIRED" if any(
                marker in lowered
                for marker in ("challenge", "captcha", "verification", "geetest", "risk")
            ) else "SOURCE_RATE_LIMITED",
            ErrorCategory.RATE_LIMITED,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=True,
            message=diagnostic,
        )
    if any(
        marker in lowered
        for marker in ("401", "403", "unauthorized", "forbidden", "auth expired", "login required")
    ):
        return _error(
            "AUTH_EXPIRED",
            ErrorCategory.POLICY_DENIED,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=False,
            message=diagnostic,
        )
    return _error(
        "PROVIDER_INTERNAL",
        ErrorCategory.INTERNAL,
        boundary_ref=boundary_ref,
        scope=ErrorScope.PROVIDER,
        retryable=False,
        message=diagnostic,
    )


def _provider_error(envelope: ProviderEnvelope, *, boundary_ref: str) -> ContractError:
    code = _safe_error_code(envelope.code)
    message = envelope.message or None
    status = envelope.status_code
    # Some provider channels intentionally do not expose a public operation
    # (for example, Spider_XHS Creator has no note-detail/comment API).  Keep
    # that policy decision distinct from a missing dependency or an upstream
    # outage so callers do not retry an operation that can never succeed.
    if code in {
        "CAPABILITY_UNREGISTERED",
        "CAPABILITY_NOT_REGISTERED",
        "UNSUPPORTED_CAPABILITY",
    }:
        return _error(
            "CAPABILITY_UNREGISTERED",
            ErrorCategory.POLICY_DENIED,
            boundary_ref=boundary_ref,
            scope=ErrorScope.SOURCE,
            retryable=False,
            message=message,
        )
    # A Dianping verification/risk page can be surfaced as HTTP 403.  Treat a
    # 403 with an explicit challenge signal as retryable risk control; a plain
    # forbidden/expired response remains an authentication failure.
    if status == 403 and _is_challenge_signal(code, message):
        return _error(
            "SOURCE_CHALLENGE_REQUIRED",
            ErrorCategory.RATE_LIMITED,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=True,
            message=message,
        )
    if status in {401, 403} or code in {"AUTH_EXPIRED", "UNAUTHORIZED", "FORBIDDEN"}:
        return _error(
            "AUTH_EXPIRED",
            ErrorCategory.POLICY_DENIED,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=False,
            message=message,
        )
    if status in {406, 408, 409, 425, 429} or code in {
        "RATE_LIMIT",
        "RATE_LIMITED",
        "HTTP_406",
        "HTTP_429",
        "GATE_REJECTED",
    }:
        return _error(
            "SOURCE_CHALLENGE_REQUIRED" if status == 406 or "GATE" in code else "SOURCE_RATE_LIMITED",
            ErrorCategory.RATE_LIMITED,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=True,
            message=message,
        )
    if _is_challenge_signal(code, message):
        return _error(
            "SOURCE_CHALLENGE_REQUIRED",
            ErrorCategory.RATE_LIMITED,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=True,
            message=message,
        )
    if status is not None and status >= 500:
        return _error(
            "SOURCE_DEPENDENCY_UNAVAILABLE",
            ErrorCategory.DEPENDENCY_UNAVAILABLE,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=True,
            message=message,
        )
    if code in {"TIMEOUT", "SOURCE_TIMEOUT"}:
        return _error(
            "SOURCE_TIMEOUT",
            ErrorCategory.TIMEOUT,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=True,
            message=message,
        )
    if code in {"MALFORMED_RESPONSE", "INVALID_RESPONSE"}:
        return _malformed(code, boundary_ref, message=message)
    if code in {"NOT_FOUND", "SOURCE_NOT_FOUND"} or status == 404:
        return _error(
            "SOURCE_NOT_FOUND",
            ErrorCategory.NOT_FOUND,
            boundary_ref=boundary_ref,
            scope=ErrorScope.PROVIDER,
            retryable=False,
            message=message,
        )
    return _error(
        code,
        ErrorCategory.DEPENDENCY_UNAVAILABLE,
        boundary_ref=boundary_ref,
        scope=ErrorScope.PROVIDER,
        retryable=True,
        message=message,
    )


def _is_challenge_signal(code: str, message: object = None) -> bool:
    signal = f"{code} {_text_or_none(message) or ''}".casefold()
    return any(
        token in signal
        for token in (
            "risk",
            "challenge",
            "captcha",
            "verify",
            "verification",
            "geetest",
            "robot",
            "security_check",
            "sec_check",
        )
    )


def _malformed(code: str, boundary_ref: str, *, message: str | None = None) -> ContractError:
    return _error(
        code,
        ErrorCategory.MALFORMED_RESPONSE,
        boundary_ref=boundary_ref,
        retryable=False,
        message=message,
    )


def _error(
    code: str,
    category: ErrorCategory,
    *,
    boundary_ref: str,
    scope: ErrorScope = ErrorScope.SOURCE,
    retryable: bool,
    message: str | None = None,
) -> ContractError:
    return ContractError(
        code=_safe_error_code(code),
        category=category,
        scope=scope,
        retryable=retryable,
        terminal=not retryable,
        message=_redact_message(message),
        boundary_ref=boundary_ref,
    )


_SAFE_ERROR_CODE = re.compile(r"[^A-Z0-9_.-]+")


def _safe_error_code(value: object) -> str:
    """Keep provider-controlled codes bounded and free of secret text."""

    text = _text_or_none(value)
    if not text:
        return "DEPENDENCY_UNAVAILABLE"
    if _SENSITIVE_VALUE.search(text):
        return "PROVIDER_ERROR"
    normalized = _SAFE_ERROR_CODE.sub("_", text.upper()).strip("_ .-")
    if not normalized:
        return "DEPENDENCY_UNAVAILABLE"
    return normalized[:96]


_SECRET_VALUE_PATTERNS = (
    re.compile(
        r"(?i)(\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*[:=]\s*)([^;\n\r]+)"
    ),
    re.compile(
        r"(?i)(\b(?:xsec[_-]?token|access[_-]?token|api[_-]?key|token|password|passwd|secret|signature|q[-_]?signature|qruuid|qr[_-]?(?:id|url|payload)|web[_-]?session|id[_-]?token|x[-_]?(?:s|t|s[-_]?common)|a1|b1|dsl|storage[_ -]?state|signer[_ -]?(?:input|state))\s*[=:]\s*)([^&\s,;]+)"
    ),
    re.compile(r"(?i)(\b(?:bearer|basic)\s+)([^\s,;]+)"),
)


def _redact_message(value: object, *, limit: int = 512) -> str | None:
    """Redact credential-looking assignments from provider diagnostics."""

    if value is None:
        return None
    text = str(value)
    for pattern in _SECRET_VALUE_PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    # Keep exceptions bounded; avoid serializing arbitrary provider response
    # bodies or giant stack traces into ContractError/SSE/Temporal history.
    text = text.replace("\x00", "")[:limit].strip()
    return text or None


def _as_mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _overlay_mapping(
    outer: Mapping[str, Any] | None,
    *nested: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    """Build a read-only field view with outer values taking precedence."""

    merged: dict[str, Any] = {}
    for mapping in nested:
        if mapping is not None:
            merged.update(mapping)
    if outer is not None:
        merged.update(outer)
    return merged


def _first_value(mapping: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _first_text(mapping: Mapping[str, Any] | None, *keys: str) -> str | None:
    if mapping is None:
        return None
    value = _first_value(mapping, *keys)
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        text = str(value).strip()
        return text or None
    return None


def _text_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (str, int, float)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool_marker(value: object) -> bool | None:
    """Accept common bool/int/string outcome markers without guessing payloads."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "ok", "success", "succeeded", "1"}:
            return True
        if normalized in {"false", "no", "error", "failed", "failure", "0"}:
            return False
    return None


def _is_failure_code(value: object) -> bool:
    text = _safe_error_code(value)
    if text in {
        "AUTH_EXPIRED",
        "UNAUTHORIZED",
        "FORBIDDEN",
        "RATE_LIMIT",
        "RATE_LIMITED",
        "RISK_CONTROL",
        "CHALLENGE",
        "VERIFICATION_REQUIRED",
        "MALFORMED_RESPONSE",
        "INVALID_RESPONSE",
        "TIMEOUT",
        "SOURCE_TIMEOUT",
    }:
        return True
    return any(token in text for token in ("RISK", "CHALLENGE", "VERIFY", "CAPTCHA"))


def _extract_mapping(
    payload: object,
    keys: Sequence[str],
    *,
    _depth: int = 0,
) -> Mapping[str, Any] | None:
    """Find one object in provider wrappers without importing their models.

    Detail endpoints in the audited clients alternate between ``data`` being
    the object itself and ``data.items`` containing a one-element list.  Keep
    this helper bounded and deterministic so a malformed recursive payload
    cannot consume the worker.
    """

    if not isinstance(payload, Mapping) or _depth > 5:
        return None

    # Explicit result keys have the strongest signal.  ``data``/``payload``
    # wrappers are traversed; a named object (``note``/``shop``) is returned
    # directly because it is already the provider's detail record.
    wrapper_keys = {"data", "payload", "result", "response", "body", "detail"}
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            if key in wrapper_keys:
                nested = _extract_mapping(value, keys, _depth=_depth + 1)
                if nested is not None:
                    return nested
            return value
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, Mapping):
                    return item

    # Common collection wrappers (actual Spider_XHS detail responses use
    # ``data.items``) are accepted even when the caller's key set is narrow.
    for key in ("items", "notes", "comments", "reviews", "shops", "pois", "places", "list"):
        value = payload.get(key)
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, Mapping):
                    return item
        elif isinstance(value, Mapping):
            nested = _extract_mapping(value, keys, _depth=_depth + 1)
            if nested is not None and nested is not value:
                return nested

    # Finally descend through generic wrappers and the XHS ``note_card``
    # object.  Returning the outer mapping remains the correct behavior when
    # it is itself a detail item (for example, ``{"id": ..., "note_card": ...}``).
    for key in ("data", "payload", "result", "response", "body"):
        value = payload.get(key)
        if isinstance(value, Mapping) and value is not payload:
            nested = _extract_mapping(value, keys, _depth=_depth + 1)
            if nested is not None:
                return nested
    return payload


def _extract_items(
    payload: object,
    keys: Sequence[str],
    *,
    _depth: int = 0,
) -> list[object] | None:
    if _depth > 5:
        return None
    if isinstance(payload, (list, tuple)):
        return list(payload)
    if not isinstance(payload, Mapping):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (list, tuple)):
            return list(value)
        if isinstance(value, Mapping):
            nested = _extract_items(value, keys, _depth=_depth + 1)
            if nested is not None:
                return nested
            # Some JSON APIs use an object keyed by provider ID instead of an
            # array.  Preserve mapping values as candidate items when the
            # field itself is an item collection.
            if key in {
                "notes",
                "items",
                "results",
                "comments",
                "reviews",
                "shops",
                "pois",
                "places",
                "list",
            }:
                values = [entry for entry in value.values() if isinstance(entry, Mapping)]
                if values:
                    return values
                # A few lightweight wrappers collapse a one-item collection
                # into an object rather than an array.  Recognize it only
                # when an explicit provider ID is present; generic wrapper
                # mappings must continue to recurse as malformed/empty.
                if any(
                    identifier in value
                    for identifier in (
                        "id",
                        "note_id",
                        "noteId",
                        "comment_id",
                        "commentId",
                        "shop_id",
                        "shopId",
                        "poi_id",
                        "poiId",
                        "review_id",
                        "reviewId",
                    )
                ):
                    return [value]
    data = payload.get("data")
    if isinstance(data, (list, tuple)):
        return list(data)
    if isinstance(data, Mapping) and data is not payload:
        nested = _extract_items(data, keys, _depth=_depth + 1)
        if nested is not None:
            return nested
    # Detail-shaped XHS payloads can place the media/comment collection below
    # ``note_card`` or a named result object.  Traverse only known wrappers and
    # keep the recursion bounded by the existing provider response depth.
    for wrapper in ("payload", "result", "response", "body", "note", "note_card", "review", "comment", "detail"):
        nested_value = payload.get(wrapper)
        if isinstance(nested_value, Mapping) and nested_value is not payload:
            nested = _extract_items(nested_value, keys, _depth=_depth + 1)
            if nested is not None:
                return nested
    # Some clients use a keyed ``results`` map.  Preserve each map value as an
    # item rather than dropping an otherwise valid response.
    results = payload.get("results")
    if isinstance(results, Mapping):
        values: list[object] = []
        for value in results.values():
            if isinstance(value, Mapping):
                values.append(value)
            elif isinstance(value, (list, tuple)):
                values.extend(value)
        return values
    return None


def _cursor_values(payload: object) -> tuple[str | None, str | None]:
    if not isinstance(payload, Mapping):
        return None, None
    candidates: list[Mapping[str, Any]] = []

    def collect(mapping: Mapping[str, Any], *, depth: int = 0) -> None:
        if depth > 3 or mapping in candidates:
            return
        candidates.append(mapping)
        for key in ("data", "pagination", "page_info", "pageInfo", "meta"):
            nested = mapping.get(key)
            if isinstance(nested, Mapping):
                collect(nested, depth=depth + 1)

    collect(payload)
    watermark: str | None = None
    next_cursor: str | None = None
    terminal_page = False
    for mapping in candidates:
        if watermark is None:
            watermark = _first_text(
                mapping,
                "watermark",
                "cursor_score",
                "high_watermark",
                "last_updated_at",
            )
        if next_cursor is None:
            next_cursor = _first_text(
                mapping,
                "next_cursor",
                "nextCursor",
                "next_page",
                "nextPage",
                "next_start_index",
                "nextStartIndex",
                "cursor",
                "offset",
            )
        has_more = mapping.get("has_more", mapping.get("hasMore"))
        has_next = mapping.get("has_next", mapping.get("hasNext"))
        if has_more is False or has_next is False:
            terminal_page = True
    if terminal_page:
        next_cursor = None
    return watermark, next_cursor


def _flatten_nested_comments(items: Sequence[object]) -> list[object]:
    flattened: list[object] = []
    for item in items:
        flattened.append(item)
        mapping = _as_mapping(item)
        if mapping is None:
            continue
        nested = mapping.get("sub_comments", mapping.get("subComments"))
        if isinstance(nested, (list, tuple)):
            flattened.extend(_flatten_nested_comments(nested))
    return flattened


_SENSITIVE_KEY = re.compile(
    r"(?:token|cookie|authorization|password|passwd|secret|signature|access[-_]?key|"
    r"xsec[-_]?token|session[-_]?id|account[-_]?(?:ref|id)|tenant[-_]?id|"
    r"grant[-_]?id|lease[-_]?id|device[-_]?id|qr(?:[-_]?id|[-_]?url|[-_]?payload)?|"
    r"web[-_]?session|id[-_]?token|q[-_]?signature|x[-_]?(?:s|t|s[-_]?common)|"
    r"storage[-_ ]?state|signer[-_ ]?(?:input|state)|decrypted[-_ ]?(?:envelope|session)|"
    r"(?:^|[-_])(?:a1|b1|dsl)(?:$|[-_]))",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?i)(?:^|[?&\s=])(?:token|xsec[_-]?token|access[_-]?token|api[_-]?key|authorization|"
    r"cookie|password|passwd|secret|signature|q[-_]?signature|qruuid|qr[_-]?(?:id|url|payload)|"
    r"web[_-]?session|id[_-]?token|x[-_]?(?:s|t|s[-_]?common)|a1|b1|dsl|storage[_ -]?state|"
    r"signer[_ -]?(?:input|state)|account[_-]?(?:ref|id)|tenant[_-]?id|"
    r"grant[_-]?id|lease[_-]?id|device[_-]?id)\s*[:=]"
)


def _safe_mapping(value: Mapping[str, Any]) -> ContractPayload:
    """Return JSON-only attributes with access-bearing keys removed."""

    def scrub(item: object) -> object:
        if isinstance(item, AnyUrl):
            return _stable_url(str(item))
        if isinstance(item, datetime):
            normalized = item.astimezone(UTC) if item.tzinfo else item.replace(tzinfo=UTC)
            return normalized.isoformat().replace("+00:00", "Z")
        if isinstance(item, Mapping):
            return {
                str(key): scrub(child)
                for key, child in item.items()
                if not _SENSITIVE_KEY.search(str(key))
            }
        if isinstance(item, (list, tuple)):
            return [scrub(child) for child in item]
        if isinstance(item, str):
            # URLs are normalized before they can become public attributes;
            # non-URL diagnostics that contain an assignment are redacted as a
            # whole value so a cookie/token cannot survive under an innocuous
            # provider key.  A stable public URL is retained (rather than
            # blanket-redacted) because downstream media/evidence consumers
            # use it as a provenance hint.
            if urlsplit(item.strip()).scheme.casefold() in {"http", "https"}:
                normalized = _stable_url(item)
                parsed = urlsplit(normalized)
                return normalized if parsed.netloc else "[REDACTED]"
            if _SENSITIVE_VALUE.search(item):
                return "[REDACTED]"
        return item

    cleaned = scrub(value)
    try:
        return TypeAdapter(ContractPayload).validate_python(cleaned)
    except (ValidationError, ValueError, TypeError) as exc:
        raise ValueError("provider attributes contain non-JSON values") from exc


def _stable_url(value: str) -> str:
    text = str(value).strip()
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return text
    try:
        hostname = parsed.hostname
        port = parsed.port
        username = parsed.username
        password = parsed.password
    except ValueError:
        # Invalid ports/user-info are rejected by the canonical URL contract;
        # returning an empty value prevents the original credential-bearing
        # authority from being copied into public attributes.
        return ""
    # URL user-info is credential-bearing and must never cross the canonical
    # source boundary, even if the host itself is otherwise valid.
    if not hostname or username is not None or password is not None:
        return ""
    hostname = hostname.casefold()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    default_port = (parsed.scheme.casefold() == "http" and port == 80) or (
        parsed.scheme.casefold() == "https" and port == 443
    )
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            netloc,
            parsed.path or "/",
            "",
            "",
        )
    )


def _stable_url_or_fallback(value: str | None, fallback: str) -> str:
    """Normalize a provider URL, falling back when it is malformed/unsafe."""

    if value:
        normalized = _stable_url(value)
        if normalized:
            return normalized
    return _stable_url(fallback)


def _parse_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            seconds = float(value) / 1000 if abs(float(value)) > 10_000_000_000 else float(value)
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _media_items_from_attributes(attributes: Mapping[str, Any]) -> list[object]:
    """Extract media candidates from flat and nested provider records.

    Spider_XHS stores note images under ``note_card.image_list`` and each
    image's URL under ``info_list``.  Dianping review snapshots commonly use
    ``pictures``/``photos``.  Preserve the original candidate mappings for the
    URL/type normalizer while avoiding arbitrary recursive traversal.
    """

    media_keys = (
        "media",
        "images",
        "image_list",
        "imageList",
        "photos",
        "pictures",
        "attachments",
        "list",
    )
    results: list[object] = []
    seen_containers: set[int] = set()

    def collect(mapping: Mapping[str, Any], *, depth: int = 0) -> None:
        if depth > 5 or id(mapping) in seen_containers:
            return
        seen_containers.add(id(mapping))
        for key in media_keys:
            value = mapping.get(key)
            if isinstance(value, (list, tuple)):
                results.extend(value)
            elif isinstance(value, Mapping):
                # A keyed media map is also a valid provider collection.
                if _media_url(value) is not None:
                    results.append(value)
                else:
                    collect(value, depth=depth + 1)
        for key in (
            "note_card",
            "data",
            "payload",
            "result",
            "detail",
            "review",
            "review_info",
            "comment",
            "comment_info",
            "video",
            # Spider_XHS video-only notes may omit the intermediate
            # ``video.media`` object and expose ``stream.h264`` directly.
            # Traverse the bounded media wrappers so those references are not
            # silently dropped.
            "stream",
            "h264",
            "source",
            "resource",
            "origin",
            "consumer",
        ):
            nested = mapping.get(key)
            if isinstance(nested, Mapping):
                # A media wrapper can itself resolve to a URL (for example a
                # direct ``stream.h264[].master_url`` object).  Keep it as a
                # candidate before descending so video-only notes are not
                # lost when no ``media``/``images`` collection key exists.
                if key in {
                    "video",
                    "stream",
                    "h264",
                    "source",
                    "resource",
                    "origin",
                    "consumer",
                } and _media_url(nested) is not None:
                    results.append(nested)
                else:
                    collect(nested, depth=depth + 1)
            elif isinstance(nested, (list, tuple)):
                for candidate in nested:
                    if isinstance(candidate, Mapping):
                        if key in {
                            "video",
                            "stream",
                            "h264",
                            "source",
                            "resource",
                            "origin",
                            "consumer",
                        } and _media_url(candidate) is not None:
                            results.append(candidate)
                        else:
                            collect(candidate, depth=depth + 1)

    collect(attributes)
    return results


def _normalize_media_items(
    *,
    source_id: str,
    owner_id: str,
    owner_type: str = "document",
    items: Sequence[object],
    captured_at: datetime,
) -> tuple[CanonicalMediaRef, ...]:
    result: list[CanonicalMediaRef] = []
    seen: set[str] = set()
    seen_urls: set[str] = set()
    for index, item in enumerate(items):
        mapping = _as_mapping(item)
        raw_url = _media_url(item)
        if not raw_url:
            continue
        stable = _stable_url(raw_url)
        parsed = urlsplit(stable)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        media_type = _media_type(mapping, raw_url)
        provider_id = (
            _first_text(mapping, "media_id", "mediaId", "id", "resource_id")
            if mapping is not None
            else None
        )
        external_id = provider_id or f"{owner_id}-media-{index}"
        if external_id in seen or stable in seen_urls:
            continue
        try:
            result.append(
                CanonicalMediaRef(
                    source_id=source_id,
                    external_id=external_id,
                    owner_external_id=owner_id,
                    owner_type=owner_type,
                    canonical_url=AnyUrl(stable),
                    captured_at=captured_at,
                    media_type=media_type,
                )
            )
            seen.add(external_id)
            seen_urls.add(stable)
        except (ValidationError, ValueError, TypeError):
            continue
    return tuple(result)


def _media_url(item: object, *, _depth: int = 0) -> str | None:
    """Return the first stable-looking URL from a provider media candidate."""

    if _depth > 5:
        return None
    if isinstance(item, str):
        return item.strip() or None
    mapping = _as_mapping(item)
    if mapping is None:
        return None
    direct = _first_text(
        mapping,
        "url",
        "src",
        "image_url",
        "imageUrl",
        "video_url",
        "videoUrl",
        "master_url",
        "masterUrl",
        "download_url",
        "downloadUrl",
    )
    if direct:
        return direct
    # Video-only XHS records may provide an opaque ``origin_video_key``
    # instead of a fully-qualified URL.  The upstream helper resolves this to
    # the public CDN host; reproduce only that stable reference (never the
    # provider's signed query material).
    origin_key = _first_text(mapping, "origin_video_key", "originVideoKey")
    if origin_key:
        return "https://sns-video-bd.xhscdn.com/" + quote(origin_key, safe="/._-~")
    # XHS image entries carry several resolutions in ``info_list``; prefer the
    # highest entry (the upstream helper uses index 1) and fall back safely.
    info = mapping.get("info_list", mapping.get("infoList"))
    if isinstance(info, (list, tuple)):
        for candidate in reversed(info):
            value = _media_url(candidate, _depth=_depth + 1)
            if value:
                return value
    for key in ("media", "stream", "h264", "source", "resource", "origin", "consumer"):
        nested = mapping.get(key)
        if isinstance(nested, (list, tuple)):
            for candidate in nested:
                value = _media_url(candidate, _depth=_depth + 1)
                if value:
                    return value
        elif isinstance(nested, Mapping):
            value = _media_url(nested, _depth=_depth + 1)
            if value:
                return value
    return None


def _media_type(mapping: Mapping[str, Any] | None, raw_url: str) -> MediaType:
    declared = _first_text(mapping, "type", "media_type", "mediaType") if mapping else None
    if declared:
        lowered = declared.casefold()
        if "video" in lowered:
            return MediaType.VIDEO
        if "audio" in lowered:
            return MediaType.AUDIO
        if "document" in lowered:
            return MediaType.DOCUMENT
    suffix = urlsplit(raw_url).path.casefold()
    if suffix.endswith((".mp4", ".mov", ".webm")):
        return MediaType.VIDEO
    if suffix.endswith((".mp3", ".wav", ".m4a")):
        return MediaType.AUDIO
    return MediaType.IMAGE


def _request_from_locator(ref: SourceLocator) -> CollectRequest:
    """Build the smallest valid request needed for a comment batch."""

    # SourceLocator intentionally carries visibility, not language/region.
    # Comment fetches therefore use the platform's documented default partition
    # while preserving the tenant boundary from the locator.
    from xhs_food.contracts import (
        CanonicalGeo,
        CanonicalIntent,
        CanonicalQuery,
        CanonicalQueryValue,
        CanonicalTimeRange,
        CanonicalTimeRangeKind,
        FreshnessPolicyRef,
        IntentKind,
    )

    isolation = IsolationCoordinates(
        tenant_scope=ref.visibility.tenant_scope,
        language="zh",
        region="CN",
    )
    query = CanonicalQuery(
        isolation=isolation,
        normalizer_version="source-normalizer/v1",
        classifier_version="source-classifier/v1",
        query=CanonicalQueryValue(
            domain="food",
            geo=CanonicalGeo(country_code="CN", admin_path=(), locality="unknown"),
            intent=CanonicalIntent(kind=IntentKind.DISCOVER, subject="comments"),
            audience=(),
            constraints=(),
            time_range=CanonicalTimeRange(
                kind=CanonicalTimeRangeKind.ANY,
                start=None,
                end=None,
                timezone="Etc/UTC",
            ),
            freshness_policy=FreshnessPolicyRef(
                policy_id="default",
                policy_version="freshness/v1",
            ),
        ),
    )
    return CollectRequest(
        query=query,
        source_scope=(ref.source_id,),
        depth="standard",
    )


__all__ = [
    "DianpingSourceConnector",
    "DianpingPlatformSourceConnector",
    "DianpingProviderPort",
    "PlatformSourceAdapterError",
    "ProviderEnvelope",
    "SpiderXhsSourceConnector",
    "XhsCreatorSourceConnector",
    "XhsPcSourceConnector",
    "XhsPlatformSourceConnector",
    "XhsProviderPort",
]
