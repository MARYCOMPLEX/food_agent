"""B4 media fetch, processor, and extractor registry contracts."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from test_unit_refresh_media_contracts import _artifact, _limits, _media_asset, _source_locator

from xhs_food.contracts import (
    DerivedArtifact,
    MediaFetchRequest,
    MediaProcessingRequest,
    ObjectRef,
)
from xhs_food.contracts.refresh_media import EvidenceExtractionRequest
from xhs_food.evidence import EvidenceExtractorRegistry, MediaAssetFetcher, MediaProcessorRegistry


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


class _ObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def put(self, key: str, chunks: Any, content_type: str, metadata: Any = None) -> ObjectRef:
        del metadata
        payload = b"".join([chunk async for chunk in chunks])
        self.objects[key] = payload
        digest = hashlib.sha256(payload).hexdigest()
        return ObjectRef(
            object_id=digest,
            key=key,
            content_hash=digest,
            size_bytes=len(payload),
            content_type=content_type,
        )

    def get(self, ref: ObjectRef) -> Any:
        raise NotImplementedError

    async def stat(self, ref: ObjectRef) -> Any:
        return None

    async def delete(self, ref: ObjectRef) -> bool:
        self.deleted.append(ref.key)
        self.objects.pop(ref.key, None)
        return True


def _fetch_request(*, declared_sha256: str | None = None, media_ref_id: str = "media.fixture.image") -> MediaFetchRequest:
    asset = _media_asset()
    media_ref = asset.media_ref.model_copy(
        update={"media_ref_id": media_ref_id, "declared_sha256": declared_sha256}
    )
    return MediaFetchRequest(
        request_id="fetch-1",
        asset_id="asset.fixture.image",
        media_ref=media_ref,
        source_locator=_source_locator(),
        max_bytes=1024,
        allowed_content_types=("image/jpeg",),
    )


@pytest.mark.unit
async def test_media_fetch_streams_hashes_and_reuses_content_addressed_object() -> None:
    store = _ObjectStore()
    fetcher = MediaAssetFetcher(store)
    request = _fetch_request()
    first = await fetcher.fetch(
        request,
        _chunks(b"ab", b"cd"),
        content_type="image/jpeg",
        fetched_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    second = await fetcher.fetch(request, _chunks(b"different"), content_type="image/jpeg")

    assert first.asset.sha256 == hashlib.sha256(b"abcd").hexdigest()
    assert first.deduplicated is False
    assert second.asset == first.asset
    assert second.deduplicated is True
    assert list(store.objects) == ["raw/sha256/media.fixture.image"]


@pytest.mark.unit
async def test_media_fetch_rejects_declared_hash_and_removes_orphan_object() -> None:
    store = _ObjectStore()
    fetcher = MediaAssetFetcher(store)
    with pytest.raises(ValueError, match="SHA-256"):
        await fetcher.fetch(
            _fetch_request(declared_sha256="a" * 64),
            _chunks(b"payload"),
            content_type="image/jpeg",
        )
    assert store.deleted == ["raw/sha256/" + "a" * 64]
    assert store.objects == {}


@pytest.mark.unit
async def test_processor_and_extractor_registries_pin_versions_and_limits() -> None:
    artifact = _artifact().model_copy(update={"input_refs": ("asset.fixture.image",)})

    class Processor:
        processor_id = "ocr"
        processor_version = "ocr/v1"

        def supports(self, *_: Any) -> bool:
            return True

        async def process(self, _: MediaProcessingRequest) -> tuple[DerivedArtifact, ...]:
            return (artifact,)

    processor_registry = MediaProcessorRegistry((Processor(),))
    processed = await processor_registry.process(
        MediaProcessingRequest(
            request_id="process-1",
            processor_id="ocr",
            processor_version="ocr/v1",
            asset=_media_asset(),
            limits=_limits(),
        )
    )
    assert processed == (artifact,)

    class Extractor:
        extractor_id = "food.ocr"
        extractor_version = "food_ocr/v1"

        def supports(self, _: EvidenceExtractionRequest) -> bool:
            return True

        async def extract(self, _: EvidenceExtractionRequest) -> tuple:
            return ()

    extractor_registry = EvidenceExtractorRegistry((Extractor(),))
    text = "fixture"
    extraction = EvidenceExtractionRequest(
        request_id="extract-1",
        extractor_id="food.ocr",
        extractor_version="food_ocr/v1",
        evidence_schema_version="food_evidence/v1",
        source_locator=_source_locator(),
        source_text=text,
        source_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        limits=_limits(),
    )
    assert await extractor_registry.extract(extraction) == ()
