"""Streaming media fetch, processor, and extractor registries."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterable
from datetime import UTC, datetime
from typing import Any

from xhs_food.contracts import (
    DerivedArtifact,
    EvidenceExtractionRequest,
    EvidenceExtractor,
    EvidenceItem,
    MediaAsset,
    MediaFetchRequest,
    MediaFetchResult,
    MediaProcessingRequest,
    MediaProcessor,
    ObjectRef,
    ObjectStore,
)


class MediaAssetFetcher:
    """Validate and persist one MediaRef without buffering the full payload."""

    def __init__(self, object_store: ObjectStore, *, telemetry: Any | None = None) -> None:
        self._object_store = object_store
        self._telemetry = telemetry
        self._assets: dict[str, MediaAsset] = {}
        self._objects_by_hash: dict[str, ObjectRef] = {}

    async def fetch(
        self,
        request: MediaFetchRequest,
        chunks: AsyncIterable[bytes],
        *,
        content_type: str,
        fetched_at: datetime | None = None,
    ) -> MediaFetchResult:
        cached = self._assets.get(request.media_ref.media_ref_id)
        if cached is not None:
            return MediaFetchResult(asset=cached, deduplicated=True)
        if content_type not in request.allowed_content_types:
            raise ValueError("media content type is outside the declared allow-list")
        if request.media_ref.declared_content_type not in (None, content_type):
            raise ValueError("media content type does not match the declared MediaRef")
        digest = hashlib.sha256()
        size_bytes = 0

        async def checked_chunks() -> AsyncIterable[bytes]:
            nonlocal size_bytes
            async for chunk in chunks:
                if not isinstance(chunk, bytes):
                    raise TypeError("media source must yield bytes")
                size_bytes += len(chunk)
                if size_bytes > request.max_bytes:
                    raise ValueError("media payload exceeds the configured byte limit")
                digest.update(chunk)
                yield chunk

        expected_key = request.media_ref.declared_sha256 or request.media_ref.media_ref_id
        key = f"raw/sha256/{expected_key}"
        try:
            object_ref = await self._object_store.put(key, checked_chunks(), content_type)
        except BaseException:
            _record_object_io(self._telemetry, operation="upload", outcome="failure")
            raise
        _record_object_io(self._telemetry, operation="upload", outcome="success")
        actual_hash = digest.hexdigest()
        if request.media_ref.declared_sha256 not in (None, actual_hash):
            await self._object_store.delete(object_ref)
            raise ValueError("media payload does not match the declared SHA-256")
        existing_ref = self._objects_by_hash.get(actual_hash)
        deduplicated = existing_ref is not None
        if existing_ref is not None and existing_ref.key != object_ref.key:
            await self._object_store.delete(object_ref)
            object_ref = existing_ref
        else:
            self._objects_by_hash[actual_hash] = object_ref
        timestamp = fetched_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("fetched_at must be timezone-aware")
        try:
            asset = MediaAsset(
                asset_id=request.asset_id,
                media_ref=request.media_ref,
                source_locator=request.source_locator,
                object_ref=object_ref,
                sha256=actual_hash,
                size_bytes=size_bytes,
                content_type=content_type,
                media_type=request.media_ref.media_type,
                fetched_at=timestamp.astimezone(UTC),
                visibility=request.source_locator.visibility,
                license=request.source_locator.license,
                retention=request.source_locator.retention,
            )
        except BaseException:
            # The object is not discoverable until metadata commits.  A
            # failed authority construction therefore becomes an idempotent
            # orphan candidate and never leaks into the business read path.
            if not deduplicated:
                await self._object_store.delete(object_ref)
            raise
        self._assets[request.media_ref.media_ref_id] = asset
        return MediaFetchResult(asset=asset, deduplicated=deduplicated)


class MediaProcessorRegistry:
    """Version-pinned Processor registry with time/output quotas."""

    def __init__(self, processors: tuple[MediaProcessor, ...] = (), *, telemetry: Any | None = None) -> None:
        self._processors: dict[tuple[str, str], MediaProcessor] = {}
        self._telemetry = telemetry
        for processor in processors:
            self.register(processor)

    def register(self, processor: MediaProcessor) -> None:
        key = (processor.processor_id, processor.processor_version)
        if key in self._processors:
            raise ValueError(f"duplicate media processor: {key}")
        self._processors[key] = processor

    def resolve(self, request: MediaProcessingRequest) -> MediaProcessor:
        processor = self._processors.get((request.processor_id, request.processor_version))
        if processor is None or not processor.supports(request.asset.media_type, request.asset.content_type):
            raise ValueError("no registered media processor supports the pinned request")
        return processor

    async def process(self, request: MediaProcessingRequest) -> tuple[DerivedArtifact, ...]:
        if request.asset.size_bytes > request.limits.max_input_bytes:
            raise ValueError("media processor input exceeds the input byte quota")
        processor = self.resolve(request)
        try:
            artifacts = await asyncio.wait_for(
                processor.process(request), request.limits.timeout_ms / 1000
            )
        except TimeoutError as exc:
            _record_extractor_error(self._telemetry, outcome="timeout")
            raise TimeoutError("media processor exceeded its time quota") from exc
        except BaseException:
            _record_extractor_error(self._telemetry, outcome="error")
            raise
        if len(artifacts) > request.limits.max_outputs:
            raise ValueError("media processor exceeded its output-count quota")
        for artifact in artifacts:
            if not isinstance(artifact, DerivedArtifact):
                raise ValueError("media processor returned an invalid DerivedArtifact")
            if artifact.processor_id != request.processor_id:
                raise ValueError("DerivedArtifact processor identity does not match request")
            if artifact.processor_version != request.processor_version:
                raise ValueError("DerivedArtifact processor version does not match request")
            if artifact.size_bytes > request.limits.max_output_bytes:
                raise ValueError("DerivedArtifact exceeded the output byte quota")
            if request.asset.asset_id not in artifact.input_refs:
                raise ValueError("DerivedArtifact must reference its input MediaAsset")
        return tuple(artifacts)


class EvidenceExtractorRegistry:
    """Version-pinned extractor registry with schema/provenance validation."""

    def __init__(self, extractors: tuple[EvidenceExtractor, ...] = (), *, telemetry: Any | None = None) -> None:
        self._extractors: dict[tuple[str, str], EvidenceExtractor] = {}
        self._telemetry = telemetry
        for extractor in extractors:
            self.register(extractor)

    def register(self, extractor: EvidenceExtractor) -> None:
        key = (extractor.extractor_id, extractor.extractor_version)
        if key in self._extractors:
            raise ValueError(f"duplicate evidence extractor: {key}")
        self._extractors[key] = extractor

    def resolve(self, request: EvidenceExtractionRequest) -> EvidenceExtractor:
        extractor = self._extractors.get((request.extractor_id, request.extractor_version))
        if extractor is None or not extractor.supports(request):
            raise ValueError("no registered evidence extractor supports the pinned request")
        return extractor

    async def extract(self, request: EvidenceExtractionRequest) -> tuple[EvidenceItem, ...]:
        extractor = self.resolve(request)
        try:
            items = await asyncio.wait_for(
                extractor.extract(request), request.limits.timeout_ms / 1000
            )
        except TimeoutError as exc:
            _record_extractor_error(self._telemetry, outcome="timeout")
            raise TimeoutError("evidence extractor exceeded its time quota") from exc
        except BaseException:
            _record_extractor_error(self._telemetry, outcome="error")
            raise
        if len(items) > request.limits.max_outputs:
            raise ValueError("evidence extractor exceeded its output-count quota")
        for item in items:
            if not isinstance(item, EvidenceItem):
                raise ValueError("evidence extractor returned an invalid EvidenceItem")
            if item.source_locator_id != request.source_locator.locator_id:
                raise ValueError("EvidenceItem provenance does not match the extraction request")
            if item.extractor_version != request.extractor_version:
                raise ValueError("EvidenceItem extractor version does not match request")
            if item.schema_version != request.evidence_schema_version:
                raise ValueError("EvidenceItem schema version does not match request")
        return tuple(items)


def _record_object_io(telemetry: Any | None, *, operation: str, outcome: str) -> None:
    record = getattr(telemetry, "record_object_io", None)
    if callable(record):
        record(operation=operation, outcome=outcome)


def _record_extractor_error(telemetry: Any | None, *, outcome: str) -> None:
    record = getattr(telemetry, "record_extractor_error", None)
    if callable(record):
        record(outcome=outcome)


__all__ = ["EvidenceExtractorRegistry", "MediaAssetFetcher", "MediaProcessorRegistry"]
