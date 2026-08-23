"""Shadow source-to-evidence projection used by XHS/Place connector wrappers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Protocol, cast

from xhs_food.contracts import (
    CanonicalAuthor,
    CanonicalMediaRef,
    CanonicalSourceBatch,
    CanonicalSourceComment,
    CanonicalSourceDocument,
    CollectRequest,
    ContractPayload,
    EvidenceItem,
    EvidenceLicense,
    EvidenceStatus,
    EvidenceVisibility,
    RetentionPolicy,
    SourceConnector,
    SourceLocator,
)

from .source import validate_evidence_provenance

_PRIVATE_PUBLIC_FIELDS = frozenset(
    {
        "user",
        "user_id",
        "session",
        "session_id",
        "preference",
        "preferences",
        "click",
        "clicks",
        "favorite",
        "favorites",
    }
)


@dataclass(frozen=True, slots=True)
class EvidenceShadowPolicy:
    """Governance and typed claim policy supplied by the Domain Pack."""

    evidence_type: str
    claim_type: str
    confidence: float
    extractor_version: str
    schema_version: str
    license: EvidenceLicense
    retention: RetentionPolicy
    visibility: EvidenceVisibility


@dataclass(frozen=True, slots=True)
class EvidenceShadowSettings:
    """Closed-world shadow controls; disabled and zero-budget by default."""

    enabled: bool = False
    sample_rate: float = 0.0
    write_budget: int = 0

    def __post_init__(self) -> None:
        if not isfinite(self.sample_rate) or not 0.0 <= self.sample_rate <= 1.0:
            raise ValueError("evidence shadow sample_rate must be between 0 and 1")
        if self.write_budget < 0:
            raise ValueError("evidence shadow write_budget must be non-negative")


class EvidenceShadowGate:
    """Deterministic sampling and per-process write budget for shadow output."""

    def __init__(self, settings: EvidenceShadowSettings | None = None) -> None:
        self._settings = settings or EvidenceShadowSettings()
        self._writes = 0

    def allow(self, family_key: str, evidence_count: int) -> bool:
        if not self._settings.enabled or evidence_count <= 0:
            return False
        if self._settings.write_budget and self._writes + evidence_count > self._settings.write_budget:
            return False
        sample = int(hashlib.sha256(family_key.encode("utf-8")).hexdigest()[:12], 16) / 16**12
        if sample >= self._settings.sample_rate:
            return False
        self._writes += evidence_count
        return True


@dataclass(frozen=True, slots=True)
class ShadowWriteRecord:
    batch: CanonicalSourceBatch
    locators: tuple[SourceLocator, ...]
    evidence_items: tuple[EvidenceItem, ...]


class EvidenceShadowSink(Protocol):
    async def write(self, record: ShadowWriteRecord) -> None: ...


async def write_shadow_record(
    sink: EvidenceShadowSink,
    record: ShadowWriteRecord,
) -> None:
    await sink.write(record)


class ShadowSourceConnector:
    """Decorator preserving connector results while optionally writing Evidence."""

    def __init__(
        self,
        connector: SourceConnector,
        *,
        policy: EvidenceShadowPolicy,
        sink: EvidenceShadowSink | None = None,
        gate: EvidenceShadowGate | None = None,
    ) -> None:
        self._connector = connector
        self._policy = policy
        self._sink = sink
        self._gate = gate

    @property
    def source_id(self) -> str:
        return self._connector.source_id

    async def search(self, request: CollectRequest) -> CanonicalSourceBatch:
        batch = await self._connector.search(request)
        await self._shadow(batch)
        return batch

    async def fetch_document(self, ref: SourceLocator) -> CanonicalSourceDocument:
        return await self._connector.fetch_document(ref)

    async def fetch_comments(
        self, document_ref: SourceLocator, cursor: str | None = None
    ) -> CanonicalSourceBatch:
        return await self._connector.fetch_comments(document_ref, cursor)

    async def list_media_refs(self, owner_ref: SourceLocator) -> tuple[CanonicalMediaRef, ...]:
        return await self._connector.list_media_refs(owner_ref)

    async def _shadow(self, batch: CanonicalSourceBatch) -> None:
        if self._sink is None:
            return
        try:
            record = build_shadow_record(batch, self._policy)
            if self._gate is not None and not self._gate.allow(
                _batch_family_key(batch), len(record.evidence_items)
            ):
                return
            await self._sink.write(record)
        except Exception:
            # Shadow-only failures must not alter the connector's legacy result.
            return


def build_shadow_record(
    batch: CanonicalSourceBatch,
    policy: EvidenceShadowPolicy,
) -> ShadowWriteRecord:
    _assert_public_batch(batch)
    locators: list[SourceLocator] = []
    evidence_items: list[EvidenceItem] = []
    for kind, item in _source_items(batch):
        locator = _locator(batch, kind, item, policy)
        evidence = _evidence(kind, item, locator, policy)
        validate_evidence_provenance(
            evidence,
            locator=locator,
            isolation=batch.isolation,
            expected_schema_version=policy.schema_version,
        )
        locators.append(locator)
        evidence_items.append(evidence)
    return ShadowWriteRecord(
        batch=batch,
        locators=tuple(locators),
        evidence_items=tuple(evidence_items),
    )


def _assert_public_batch(batch: CanonicalSourceBatch) -> None:
    violations = sorted(_private_field_paths(batch.model_dump(mode="json")))
    if violations:
        raise ValueError(
            "public Evidence cannot contain private fields: " + ", ".join(violations)
        )


def _private_field_paths(value: object, path: str = "batch") -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key).lower().replace("-", "_")
            child_path = f"{path}.{key}"
            if name in _PRIVATE_PUBLIC_FIELDS or any(
                name.startswith(f"{prefix}_")
                for prefix in ("user", "session", "preference", "click", "favorite")
            ):
                found.append(child_path)
            found.extend(_private_field_paths(item, child_path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_private_field_paths(item, f"{path}[{index}]"))
    return tuple(found)


def _source_items(
    batch: CanonicalSourceBatch,
) -> tuple[
    tuple[str, CanonicalSourceDocument | CanonicalSourceComment | CanonicalAuthor], ...
]:
    return tuple(
        (kind, item)
        for kind, values in (
            ("document", batch.documents),
            ("comment", batch.comments),
            ("author", batch.authors),
        )
        for item in values
    )


def _batch_family_key(batch: CanonicalSourceBatch) -> str:
    return hashlib.sha256(
        json.dumps(
            batch.isolation.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _locator(
    batch: CanonicalSourceBatch,
    kind: str,
    item: CanonicalSourceDocument | CanonicalSourceComment | CanonicalAuthor,
    policy: EvidenceShadowPolicy,
) -> SourceLocator:
    external_id = item.external_id
    digest = hashlib.sha256(f"{batch.source_id}:{kind}:{external_id}".encode()).hexdigest()[:32]
    return SourceLocator(
        locator_id=f"locator.{batch.source_id}.{digest}",
        source_id=batch.source_id,
        connector_id=batch.connector_id,
        connector_version=batch.connector_version,
        external_id=external_id,
        canonical_url=item.canonical_url,
        captured_at=item.captured_at,
        source_updated_at=item.source_updated_at,
        watermark=batch.watermark,
        visibility=policy.visibility,
        license=policy.license,
        retention=policy.retention,
    )


def _evidence(
    kind: str,
    item: CanonicalSourceDocument | CanonicalSourceComment | CanonicalAuthor,
    locator: SourceLocator,
    policy: EvidenceShadowPolicy,
) -> EvidenceItem:
    claim_value: ContractPayload = {
        "source_id": item.source_id,
        "external_id": item.external_id,
        "kind": kind,
    }
    for key in ("title", "text", "display_name", "document_external_id"):
        value = getattr(item, key, None)
        if isinstance(value, str) and value:
            claim_value[key] = value
    encoded = json.dumps(claim_value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return EvidenceItem(
        evidence_id=f"evidence.{locator.locator_id.removeprefix('locator.')}",
        evidence_type=cast(str, policy.evidence_type),
        claim_type=cast(str, policy.claim_type),
        claim_value=claim_value,
        confidence=policy.confidence,
        source_locator_id=locator.locator_id,
        media_ref_ids=(),
        derived_artifact_ids=(),
        extractor_version=policy.extractor_version,
        schema_version=policy.schema_version,
        content_hash=content_hash,
        status=EvidenceStatus.CANDIDATE,
        visibility=policy.visibility,
        license=policy.license,
        retention=policy.retention,
    )


__all__ = [
    "EvidenceShadowPolicy",
    "EvidenceShadowGate",
    "EvidenceShadowSettings",
    "EvidenceShadowSink",
    "ShadowSourceConnector",
    "ShadowWriteRecord",
    "build_shadow_record",
    "write_shadow_record",
]
