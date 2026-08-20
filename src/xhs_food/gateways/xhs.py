"""XHS compatibility connector; platform payloads terminate in this module."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import AnyUrl, TypeAdapter, ValidationError

from xhs_food.contracts import (
    CanonicalMediaRef,
    CanonicalSourceBatch,
    CanonicalSourceComment,
    CanonicalSourceDocument,
    CollectRequest,
    ContractError,
    ContractPayload,
    ErrorCategory,
    IsolationCoordinates,
    MediaType,
    SourceLocator,
)

from .outcomes import (
    error_from_exception,
    error_from_provider_code,
    single_attempt_coverage,
    source_error,
)


class LegacyXHSTool(Protocol):
    @property
    def name(self) -> str: ...

    async def execute(self, **kwargs: Any) -> object: ...


class XHSSourceConnector:
    source_id = "xhs"
    connector_id = "xhs.compat"
    connector_version = "xhs-connector/v1"
    normalizer_version = "xhs-normalizer/v1"
    legacy_tool_names = ("xhs_search", "xhs_note", "xhs_batch")

    def __init__(
        self,
        *,
        search_provider: LegacyXHSTool,
        note_provider: LegacyXHSTool,
        batch_provider: LegacyXHSTool,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        providers = (search_provider, note_provider, batch_provider)
        if tuple(provider.name for provider in providers) != self.legacy_tool_names:
            raise ValueError("XHS compatibility tool names or order changed")
        self._search_provider = search_provider
        self._note_provider = note_provider
        self._batch_provider = batch_provider
        self._clock = clock or (lambda: datetime.now(UTC))

    async def search(self, request: CollectRequest) -> CanonicalSourceBatch:
        keyword = self._keyword(request)
        return await self._collect_documents(
            request,
            self._search_provider,
            keyword=keyword,
            count=10,
            sort_type="most_comments",
            include_details=True,
            include_comments=True,
        )

    async def batch_search(
        self, request: CollectRequest, topics: Sequence[str], *, notes_per_topic: int = 4
    ) -> CanonicalSourceBatch:
        return await self._collect_documents(
            request,
            self._batch_provider,
            topics=list(topics),
            notes_per_topic=notes_per_topic,
        )

    async def fetch_document(self, ref: SourceLocator) -> CanonicalSourceDocument:
        self._validate_ref(ref)
        raw = await self._execute(
            self._note_provider,
            note_id=ref.external_id,
            max_comments=30,
        )
        data, error = _provider_data(raw, boundary_ref=self._note_provider.name)
        if error is not None:
            raise SourceAdapterError(error)
        note = _extract_single_note(data)
        document, item_error = self._normalize_document(note)
        if item_error is not None or document is None:
            raise SourceAdapterError(
                item_error or _malformed("XHS_NOTE_MALFORMED", self._note_provider.name)
            )
        return document

    async def fetch_comments(
        self, document_ref: SourceLocator, cursor: str | None = None
    ) -> CanonicalSourceBatch:
        del cursor
        self._validate_ref(document_ref)
        raw = await self._execute(
            self._note_provider,
            note_id=document_ref.external_id,
            max_comments=30,
        )
        data, error = _provider_data(raw, boundary_ref=self._note_provider.name)
        errors: list[ContractError] = []
        comments: list[CanonicalSourceComment] = []
        if error is not None:
            errors.append(error)
        else:
            values = data.get("comments", []) if data else []
            if not isinstance(values, list):
                errors.append(_malformed("XHS_COMMENTS_MALFORMED", self._note_provider.name))
            else:
                for index, item in enumerate(values):
                    normalized, item_error = self._normalize_comment(
                        item, document_ref.external_id, index
                    )
                    if normalized is not None:
                        comments.append(normalized)
                    if item_error is not None:
                        errors.append(item_error)
        return self._batch(document_ref, comments=tuple(comments), errors=tuple(errors))

    async def list_media_refs(self, owner_ref: SourceLocator) -> tuple[CanonicalMediaRef, ...]:
        document = await self.fetch_document(owner_ref)
        media: list[CanonicalMediaRef] = []
        values = document.attributes.get("images") or document.attributes.get("photos") or []
        if not isinstance(values, (list, tuple)):
            return ()
        for index, item in enumerate(values):
            url = item.get("url") if isinstance(item, Mapping) else item
            if not isinstance(url, str) or not url:
                continue
            try:
                media.append(
                    CanonicalMediaRef(
                        source_id=self.source_id,
                        external_id=f"{owner_ref.external_id}-media-{index}",
                        owner_external_id=owner_ref.external_id,
                        owner_type="document",
                        canonical_url=AnyUrl(url),
                        captured_at=self._now(),
                        media_type=MediaType.IMAGE,
                    )
                )
            except ValidationError:
                continue
        return tuple(media)

    async def _collect_documents(
        self,
        request: CollectRequest,
        provider: LegacyXHSTool,
        **arguments: Any,
    ) -> CanonicalSourceBatch:
        raw = await self._execute(provider, **arguments)
        data, provider_error = _provider_data(raw, boundary_ref=provider.name)
        errors: list[ContractError] = []
        documents: list[CanonicalSourceDocument] = []
        seen_document_ids: set[str] = set()
        if provider_error is not None:
            errors.append(provider_error)
        else:
            notes = _extract_notes(data)
            if notes is None:
                errors.append(_malformed("XHS_NOTES_MALFORMED", provider.name))
            else:
                for item in notes:
                    document, item_error = self._normalize_document(item)
                    if document is not None and document.external_id not in seen_document_ids:
                        seen_document_ids.add(document.external_id)
                        documents.append(document)
                    if item_error is not None:
                        errors.append(item_error)
        batch_errors = tuple(errors)
        watermark = data.get("watermark") if isinstance(data, Mapping) else None
        return CanonicalSourceBatch(
            isolation=request.query.isolation,
            source_id=self.source_id,
            connector_id=self.connector_id,
            connector_version=self.connector_version,
            normalizer_version=self.normalizer_version,
            documents=tuple(documents),
            watermark=watermark,
            next_cursor=data.get("next_cursor") if isinstance(data, Mapping) else None,
            errors=batch_errors,
            coverage=single_attempt_coverage(
                attempt_id=provider.name,
                boundary_ref=provider.name,
                item_count=len(documents),
                watermark=watermark,
                errors=batch_errors,
            ),
        )

    async def _execute(self, provider: LegacyXHSTool, **arguments: Any) -> object:
        try:
            return await provider.execute(**arguments)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return _ProviderFailure(error_from_exception(exc, boundary_ref=provider.name))

    def _normalize_document(
        self, item: object
    ) -> tuple[CanonicalSourceDocument | None, ContractError | None]:
        if not isinstance(item, Mapping):
            return None, _malformed("XHS_ITEM_MALFORMED", self.connector_id)
        external_id = item.get("id") or item.get("note_id")
        if not isinstance(external_id, str) or not external_id.strip():
            return None, _malformed("XHS_ITEM_ID_MISSING", self.connector_id)
        raw_url = item.get("url") or item.get("note_url")
        url = _stable_url(
            raw_url
            if isinstance(raw_url, str) and raw_url
            else f"https://www.xiaohongshu.com/explore/{quote(external_id, safe='')}"
        )
        try:
            attributes = _json_mapping(item)
            document = CanonicalSourceDocument(
                source_id=self.source_id,
                external_id=external_id,
                canonical_url=AnyUrl(url),
                captured_at=self._now(),
                author_external_id=_optional_string(item.get("user_id") or item.get("author_id")),
                title=_optional_string(item.get("title")),
                text=_optional_string(
                    item.get("full_desc") or item.get("desc") or item.get("content")
                ),
                attributes=attributes,
            )
        except (ValidationError, ValueError, TypeError):
            return None, _malformed("XHS_ITEM_MALFORMED", self.connector_id)
        return document, None

    def _normalize_comment(
        self, item: object, document_id: str, index: int
    ) -> tuple[CanonicalSourceComment | None, ContractError | None]:
        if not isinstance(item, Mapping):
            return None, _malformed("XHS_COMMENT_MALFORMED", self.connector_id)
        external_id = item.get("id") or item.get("comment_id")
        if not isinstance(external_id, (str, int)) or not str(external_id):
            return None, _malformed("XHS_COMMENT_ID_MISSING", self.connector_id)
        raw_url = item.get("url")
        url = _stable_url(
            raw_url
            if isinstance(raw_url, str) and raw_url
            else f"https://www.xiaohongshu.com/explore/{quote(document_id, safe='')}"
        )
        try:
            return (
                CanonicalSourceComment(
                    source_id=self.source_id,
                    external_id=str(external_id),
                    document_external_id=document_id,
                    canonical_url=AnyUrl(url),
                    captured_at=self._now(),
                    author_external_id=_optional_string(
                        item.get("user_id") or item.get("author_id")
                    ),
                    text=_optional_string(item.get("content") or item.get("text")),
                    attributes=_json_mapping(item),
                ),
                None,
            )
        except (ValidationError, ValueError, TypeError):
            return None, _malformed("XHS_COMMENT_MALFORMED", self.connector_id)

    def _batch(
        self,
        ref: SourceLocator,
        *,
        comments: tuple[CanonicalSourceComment, ...] = (),
        errors: tuple[ContractError, ...] = (),
    ) -> CanonicalSourceBatch:
        item_count = len(comments)
        return CanonicalSourceBatch(
            isolation=IsolationCoordinates(
                tenant_scope=ref.visibility.tenant_scope,
                language="zh",
                region="CN",
            ),
            source_id=self.source_id,
            connector_id=self.connector_id,
            connector_version=self.connector_version,
            normalizer_version=self.normalizer_version,
            comments=comments,
            watermark=ref.watermark,
            errors=errors,
            coverage=single_attempt_coverage(
                attempt_id="xhs_note.comments",
                boundary_ref=self._note_provider.name,
                item_count=item_count,
                watermark=ref.watermark,
                errors=errors,
            ),
        )

    def _keyword(self, request: CollectRequest) -> str:
        projection = request.source_query_for(self.source_id)
        if projection is not None:
            return projection.text
        query = request.query.query
        return f"{query.geo.locality} {query.intent.subject}"

    def _validate_ref(self, ref: SourceLocator) -> None:
        if ref.source_id != self.source_id:
            raise ValueError("source locator does not belong to the XHS connector")

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("connector clock must return a timezone-aware value")
        return value.astimezone(UTC)


class SourceAdapterError(RuntimeError):
    def __init__(self, error: ContractError) -> None:
        super().__init__(error.code)
        self.error = error


@dataclass(frozen=True, slots=True)
class _ProviderFailure:
    error: ContractError


def _provider_data(
    raw: object, *, boundary_ref: str
) -> tuple[dict[str, Any], ContractError | None]:
    if isinstance(raw, _ProviderFailure):
        return {}, raw.error
    try:
        value = cast(Any, raw)
        success = bool(value.success)
        if not success:
            error_code = value.error_code
            error_message = value.error_message
        else:
            data = value.data
    except (AttributeError, TypeError):
        return {}, _malformed("XHS_RESULT_ENVELOPE_MALFORMED", boundary_ref)
    if not success:
        return {}, error_from_provider_code(
            error_code,
            boundary_ref=boundary_ref,
            message=error_message,
        )
    if not isinstance(data, dict):
        return {}, _malformed("XHS_RESULT_DATA_MALFORMED", boundary_ref)
    return data, None


def _extract_notes(data: Mapping[str, Any] | None) -> list[object] | None:
    if data is None:
        return None
    notes = data.get("notes")
    if notes is None and isinstance(data.get("results"), Mapping):
        notes = []
        for value in data["results"].values():
            nested = value if isinstance(value, list) else None
            if isinstance(value, Mapping):
                nested = value.get("notes")
            if not isinstance(nested, list):
                return None
            notes.extend(nested)
    return notes if isinstance(notes, list) else None


def _extract_single_note(data: Mapping[str, Any] | None) -> object:
    if data is None:
        return {}
    note = data.get("note") or data.get("data")
    return note if isinstance(note, Mapping) else data


def _json_mapping(value: object) -> ContractPayload:
    if not isinstance(value, Mapping):
        raise TypeError("source item must be an object")
    return TypeAdapter(ContractPayload).validate_python(dict(value))


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _stable_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _malformed(code: str, boundary_ref: str) -> ContractError:
    return source_error(
        code=code,
        category=ErrorCategory.MALFORMED_RESPONSE,
        boundary_ref=boundary_ref,
        retryable=False,
    )


__all__ = ["SourceAdapterError", "XHSSourceConnector"]
