"""Connector-neutral source normalization and provenance quarantine checks."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from xhs_food.contracts import (
    CanonicalAuthor,
    CanonicalMediaRef,
    CanonicalSourceBatch,
    CanonicalSourceComment,
    CanonicalSourceDocument,
    ContractError,
    ContractPayload,
    EvidenceItem,
    EvidenceStatus,
    IsolationCoordinates,
    SourceLocator,
)
from xhs_food.contracts.evidence import DerivedArtifact, MediaRef

_TRACKING_QUERY = re.compile(r"^(?:utm_[a-z0-9_]+|spm|from|share_token)$", re.IGNORECASE)


class SourceNormalizationError(ValueError):
    """Raw connector payload cannot be converted into a canonical source batch."""


class EvidenceQuarantineError(ValueError):
    """Evidence cannot be published until its provenance issue is resolved."""

    def __init__(self, evidence_id: str, reasons: tuple[str, ...]) -> None:
        self.evidence_id = evidence_id
        self.reasons = reasons
        super().__init__(f"evidence {evidence_id!r} is quarantined: {', '.join(reasons)}")


class CanonicalSourceBatchNormalizer:
    """Normalize one connector result without carrying connector-specific types."""

    def __init__(self, *, normalizer_version: str = "source-normalizer/v1") -> None:
        self._normalizer_version = normalizer_version

    def normalize(self, value: Mapping[str, object]) -> CanonicalSourceBatch:
        isolation = IsolationCoordinates.model_validate(value.get("isolation"))
        source_id = self._required_text(value, "source_id")
        payload = {
            "isolation": isolation.model_dump(mode="json"),
            "source_id": source_id,
            "connector_id": self._required_text(value, "connector_id"),
            "connector_version": self._required_text(value, "connector_version"),
            "normalizer_version": self._normalizer_version,
            "documents": tuple(
                self._document(item, source_id) for item in self._items(value, "documents")
            ),
            "comments": tuple(
                self._comment(item, source_id) for item in self._items(value, "comments")
            ),
            "authors": tuple(
                self._author(item, source_id) for item in self._items(value, "authors")
            ),
            "media_refs": tuple(
                self._media(item, source_id) for item in self._items(value, "media_refs")
            ),
            "watermark": self._optional_text(value.get("watermark"), "watermark"),
            "next_cursor": self._optional_text(value.get("next_cursor"), "next_cursor"),
            "errors": tuple(self._error(item) for item in self._items(value, "errors")),
        }
        if "coverage" in value and value["coverage"] is not None:
            payload["coverage"] = value["coverage"]
        return CanonicalSourceBatch.model_validate(payload)

    @staticmethod
    def _items(value: Mapping[str, object], key: str) -> tuple[Mapping[str, object], ...]:
        raw = value.get(key, ())
        if not isinstance(raw, (list, tuple)):
            raise SourceNormalizationError(f"{key} must be an array")
        rows: list[Mapping[str, object]] = []
        for index, item in enumerate(raw):
            if not isinstance(item, Mapping):
                raise SourceNormalizationError(f"{key}[{index}] must be an object")
            _reject_binary(item, f"{key}[{index}]")
            rows.append(item)
        return tuple(rows)

    @staticmethod
    def _required_text(value: Mapping[str, object], key: str) -> str:
        result = value.get(key)
        if not isinstance(result, str) or not result.strip():
            raise SourceNormalizationError(f"{key} must be a non-empty string")
        return result.strip()

    @staticmethod
    def _optional_text(value: object, key: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise SourceNormalizationError(f"{key} must be a string or null")
        return value.strip() or None

    @classmethod
    def _base(cls, item: Mapping[str, object], source_id: str) -> dict[str, object]:
        raw_external = item.get("external_id", item.get("id"))
        if not isinstance(raw_external, str) or not raw_external.strip():
            raise SourceNormalizationError("source item requires external_id or id")
        raw_url = item.get("canonical_url", item.get("url"))
        if not isinstance(raw_url, str) or not raw_url.strip():
            raise SourceNormalizationError(f"source item {raw_external!r} requires canonical_url")
        captured_at = item.get("captured_at")
        if captured_at is None:
            raise SourceNormalizationError(f"source item {raw_external!r} requires captured_at")
        result: dict[str, object] = {
            "source_id": source_id,
            "external_id": raw_external.strip(),
            "canonical_url": _canonical_url(raw_url),
            "captured_at": captured_at,
        }
        if "source_updated_at" in item:
            result["source_updated_at"] = item["source_updated_at"]
        attributes = item.get("attributes", {})
        if not isinstance(attributes, Mapping):
            raise SourceNormalizationError("source item attributes must be an object")
        result["attributes"] = cast(ContractPayload, dict(attributes))
        return result

    @classmethod
    def _document(cls, item: Mapping[str, object], source_id: str) -> CanonicalSourceDocument:
        payload = cls._base(item, source_id)
        for field in ("author_external_id", "title", "text"):
            if field in item:
                payload[field] = item[field]
        return CanonicalSourceDocument.model_validate(payload)

    @classmethod
    def _comment(cls, item: Mapping[str, object], source_id: str) -> CanonicalSourceComment:
        payload = cls._base(item, source_id)
        document_id = item.get("document_external_id", item.get("document_id"))
        if not isinstance(document_id, str) or not document_id.strip():
            raise SourceNormalizationError("comment requires document_external_id")
        payload["document_external_id"] = document_id.strip()
        for field in ("author_external_id", "text"):
            if field in item:
                payload[field] = item[field]
        return CanonicalSourceComment.model_validate(payload)

    @classmethod
    def _author(cls, item: Mapping[str, object], source_id: str) -> CanonicalAuthor:
        payload = cls._base(item, source_id)
        if "display_name" in item:
            payload["display_name"] = item["display_name"]
        return CanonicalAuthor.model_validate(payload)

    @classmethod
    def _media(cls, item: Mapping[str, object], source_id: str) -> CanonicalMediaRef:
        payload = cls._base(item, source_id)
        owner_id = item.get("owner_external_id", item.get("owner_id"))
        owner_type = item.get("owner_type")
        media_type = item.get("media_type", "image")
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise SourceNormalizationError("media reference requires owner_external_id")
        payload["owner_external_id"] = owner_id.strip()
        payload["owner_type"] = owner_type
        payload["media_type"] = media_type
        return CanonicalMediaRef.model_validate(payload)

    @staticmethod
    def _error(value: Mapping[str, object]) -> ContractError:
        try:
            return ContractError.model_validate(value)
        except Exception as exc:
            raise SourceNormalizationError("source error is not a valid ContractError") from exc


def validate_evidence_provenance(
    item: EvidenceItem,
    *,
    locator: SourceLocator | None,
    isolation: IsolationCoordinates | None = None,
    media_refs: Mapping[str, MediaRef] | None = None,
    derived_artifacts: Mapping[str, DerivedArtifact] | None = None,
    expected_schema_version: str = "food-evidence/v1",
) -> EvidenceItem:
    """Validate the graph needed for publication, failing closed on any gap."""

    reasons: list[str] = []
    if locator is None:
        reasons.append("source_locator_missing")
    elif locator.locator_id != item.source_locator_id:
        reasons.append("source_locator_id_mismatch")
    elif isolation is not None and (
        locator.visibility.tenant_scope != isolation.tenant_scope
        or (
            locator.visibility.scope.value == "public"
            and isolation.tenant_scope != "public"
        )
    ):
        reasons.append("source_locator_partition_mismatch")
    if item.schema_version != expected_schema_version:
        reasons.append("evidence_schema_version_mismatch")
    media_refs = media_refs or {}
    derived_artifacts = derived_artifacts or {}
    reasons.extend(
        f"media_ref_missing:{ref_id}" for ref_id in item.media_ref_ids if ref_id not in media_refs
    )
    reasons.extend(
        f"derived_artifact_missing:{ref_id}"
        for ref_id in item.derived_artifact_ids
        if ref_id not in derived_artifacts
    )
    if reasons:
        raise EvidenceQuarantineError(item.evidence_id, tuple(reasons))
    return item


def quarantine_evidence(item: EvidenceItem, error: EvidenceQuarantineError) -> EvidenceItem:
    if error.evidence_id != item.evidence_id:
        raise ValueError("quarantine error does not belong to evidence item")
    return item.model_copy(update={"status": EvidenceStatus.QUARANTINED})


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if not parsed.scheme or not parsed.netloc or parsed.username or parsed.password:
        raise SourceNormalizationError("canonical_url must be an absolute URL without credentials")
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not _TRACKING_QUERY.match(key)
        )
    )
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", query, ""))


def _reject_binary(value: object, path: str) -> None:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise SourceNormalizationError(f"{path} contains binary data")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_binary(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_binary(item, f"{path}[{index}]")


__all__ = [
    "CanonicalSourceBatchNormalizer",
    "EvidenceQuarantineError",
    "SourceNormalizationError",
    "quarantine_evidence",
    "validate_evidence_provenance",
]
