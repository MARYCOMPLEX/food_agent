"""Amap place source and tool compatibility adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote

from pydantic import AnyUrl, TypeAdapter, ValidationError

from xhs_food.contracts import (
    CanonicalMediaRef,
    CanonicalSourceBatch,
    CanonicalSourceDocument,
    CollectRequest,
    ContractPayload,
    ErrorCategory,
    SourceLocator,
)

from .outcomes import error_from_exception, single_attempt_coverage, source_error
from .tools import ProviderResult


class AmapClient(Protocol):
    def search_poi(self, keywords: str, city: str = "", types: str = "050000") -> dict: ...


class AmapPlaceSourceConnector:
    source_id = "amap"
    connector_id = "amap.compat"
    connector_version = "amap-connector/v1"
    normalizer_version = "amap-normalizer/v1"

    def __init__(
        self,
        client: AmapClient,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))

    async def search(self, request: CollectRequest) -> CanonicalSourceBatch:
        query = request.query.query
        projection = request.source_query_for(self.source_id)
        keyword = (
            projection.text
            if projection is not None
            else f"{query.geo.locality} {query.intent.subject}"
        )
        locality = projection.locality if projection is not None else query.geo.locality
        return await self.search_places(
            request,
            keywords=keyword,
            city=locality,
        )

    async def search_places(
        self, request: CollectRequest, *, keywords: str, city: str = ""
    ) -> CanonicalSourceBatch:
        errors = []
        documents = []
        try:
            raw = await asyncio.to_thread(
                self._client.search_poi,
                keywords=keywords,
                city=city,
                types="050000",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raw = None
            errors.append(error_from_exception(exc, boundary_ref=self.connector_id))
        if raw is not None:
            if not isinstance(raw, Mapping):
                errors.append(self._malformed("AMAP_RESPONSE_MALFORMED"))
            elif "error" in raw:
                errors.append(self._provider_error(raw["error"]))
            elif not isinstance(raw.get("pois", []), list):
                errors.append(self._malformed("AMAP_POIS_MALFORMED"))
            else:
                for item in raw.get("pois", []):
                    document = self._normalize(item)
                    if document is None:
                        errors.append(self._malformed("AMAP_ITEM_MALFORMED"))
                    else:
                        documents.append(document)
        batch_errors = tuple(errors)
        return CanonicalSourceBatch(
            isolation=request.query.isolation,
            source_id=self.source_id,
            connector_id=self.connector_id,
            connector_version=self.connector_version,
            normalizer_version=self.normalizer_version,
            documents=tuple(documents),
            watermark=None,
            errors=batch_errors,
            coverage=single_attempt_coverage(
                attempt_id="amap.search",
                boundary_ref=self.connector_id,
                item_count=len(documents),
                watermark=None,
                errors=batch_errors,
            ),
        )

    async def fetch_document(self, ref: SourceLocator) -> CanonicalSourceDocument:
        raise NotImplementedError("Amap compatibility API has no stable fetch-by-id operation")

    async def fetch_comments(
        self, document_ref: SourceLocator, cursor: str | None = None
    ) -> CanonicalSourceBatch:
        raise NotImplementedError("Amap does not expose the XHS comment capability")

    async def list_media_refs(self, owner_ref: SourceLocator) -> tuple[CanonicalMediaRef, ...]:
        del owner_ref
        return ()

    def _normalize(self, item: object) -> CanonicalSourceDocument | None:
        if not isinstance(item, Mapping):
            return None
        external_id = item.get("poi_id") or item.get("id")
        if not isinstance(external_id, str) or not external_id:
            return None
        try:
            return CanonicalSourceDocument(
                source_id=self.source_id,
                external_id=external_id,
                canonical_url=AnyUrl(f"https://www.amap.com/place/{quote(external_id, safe='')}"),
                captured_at=self._now(),
                title=item.get("name") if isinstance(item.get("name"), str) else None,
                text=item.get("address") if isinstance(item.get("address"), str) else None,
                attributes=TypeAdapter(ContractPayload).validate_python(dict(item)),
            )
        except (ValidationError, ValueError, TypeError):
            return None

    def _malformed(self, code: str):
        return source_error(
            code=code,
            category=ErrorCategory.MALFORMED_RESPONSE,
            boundary_ref=self.connector_id,
            retryable=False,
        )

    def _provider_error(self, value: object):
        if _is_rate_limited(value):
            return source_error(
                code="AMAP_RATE_LIMITED",
                category=ErrorCategory.RATE_LIMITED,
                boundary_ref=self.connector_id,
                retryable=True,
            )
        return source_error(
            code="AMAP_DEPENDENCY_UNAVAILABLE",
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
            boundary_ref=self.connector_id,
            retryable=True,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("connector clock must return a timezone-aware value")
        return value.astimezone(UTC)


class PlaceLookupToolAdapter:
    name = "place_lookup"

    def __init__(self, client: AmapClient) -> None:
        self._client = client

    async def execute(
        self, *, keywords: str, city: str = "", types: str = "050000", **_: Any
    ) -> ProviderResult:
        try:
            raw = await asyncio.to_thread(
                self._client.search_poi,
                keywords=keywords,
                city=city,
                types=types,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return ProviderResult(False, error_code="SOURCE_TIMEOUT")
        except Exception as exc:
            return ProviderResult(False, error_code="PROVIDER_INTERNAL", error_message=str(exc))
        if not isinstance(raw, dict):
            return ProviderResult(False, error_code="MALFORMED_RESPONSE")
        if "error" in raw:
            code = "HTTP_429" if _is_rate_limited(raw["error"]) else "DEPENDENCY_UNAVAILABLE"
            return ProviderResult(False, error_code=code, error_message=str(raw["error"]))
        return ProviderResult(True, data=raw)

    async def lookup(
        self, *, keywords: str, city: str = "", types: str = "050000"
    ) -> dict[str, Any] | None:
        """Project the provider envelope onto the optional lookup port."""
        result = await self.execute(keywords=keywords, city=city, types=types)
        return result.data if result.success else None

    async def health_check(self) -> bool:
        return self._client is not None


def _is_rate_limited(value: object) -> bool:
    text = str(value).casefold()
    return "429" in text or "too many requests" in text or ("rate" in text and "limit" in text)


__all__ = ["AmapClient", "AmapPlaceSourceConnector", "PlaceLookupToolAdapter"]
