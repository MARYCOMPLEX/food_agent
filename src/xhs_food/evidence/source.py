"""Connector-neutral source normalization and provenance quarantine checks."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import ValidationError

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
    EvidenceVisibility,
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
        if not isinstance(value, Mapping):
            raise SourceNormalizationError("source batch must be an object")
        try:
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
        except SourceNormalizationError:
            raise
        except (TypeError, ValueError, ValidationError) as exc:
            raise SourceNormalizationError(f"invalid source batch: {exc}") from exc

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
    require_public: bool = False,
    validate_content_hash: bool = False,
    now: datetime | None = None,
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
    if locator is not None:
        if locator.source_id == "":
            reasons.append("source_locator_source_missing")
        if require_public and not _is_public_visibility(locator.visibility):
            reasons.append("source_locator_not_public")
    if item.schema_version != expected_schema_version:
        reasons.append("evidence_schema_version_mismatch")
    if require_public and not _is_public_visibility(item.visibility):
        reasons.append("evidence_not_public")
    if locator is not None:
        if not _governance_at_least_as_restrictive(item.visibility, locator.visibility):
            reasons.append("evidence_visibility_broadens_locator")
        if not _license_at_least_as_restrictive(item.license, locator.license):
            reasons.append("evidence_license_broadens_locator")
        if not _license_reusable(locator.license, now=now):
            reasons.append("source_license_not_reusable")
        if not _license_reusable(item.license, now=now):
            reasons.append("evidence_license_not_reusable")
        if not _retention_at_least_as_restrictive(item.retention, locator.retention):
            reasons.append("evidence_retention_broadened")
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
    for ref_id in item.media_ref_ids:
        media = media_refs.get(ref_id)
        if media is not None:
            if locator is not None and media.locator_id != locator.locator_id:
                reasons.append(f"media_ref_locator_mismatch:{ref_id}")
            if not _is_public_url(str(media.source_url)):
                reasons.append(f"media_ref_not_public:{ref_id}")
    for ref_id in item.derived_artifact_ids:
        artifact = derived_artifacts.get(ref_id)
        if artifact is not None and not _derived_chain_is_valid(
            ref_id,
            artifact,
            media_refs=media_refs,
            derived_artifacts=derived_artifacts,
            item_visibility=item.visibility,
            item_license=item.license,
            item_retention=item.retention,
        ):
            reasons.append(f"derived_artifact_provenance_invalid:{ref_id}")
    if validate_content_hash and item.content_hash != evidence_content_hash(item):
        reasons.append("evidence_content_hash_mismatch")
    if reasons:
        raise EvidenceQuarantineError(item.evidence_id, tuple(reasons))
    return item


def quarantine_evidence(item: EvidenceItem, error: EvidenceQuarantineError) -> EvidenceItem:
    if error.evidence_id != item.evidence_id:
        raise ValueError("quarantine error does not belong to evidence item")
    return item.model_copy(update={"status": EvidenceStatus.QUARANTINED})


def evidence_content_hash(item: EvidenceItem) -> str:
    """Compute the stable hash used by the shadow extractor for one claim."""

    encoded = json.dumps(
        {
            "claim_type": item.claim_type,
            "claim_value": item.claim_value,
            "evidence_type": item.evidence_type,
            "source_locator_id": item.source_locator_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_public_visibility(visibility: EvidenceVisibility) -> bool:
    return (
        visibility.scope.value == "public"
        and visibility.tenant_scope == "public"
        and not visibility.entitlement_ids
    )


def _is_public_url(value: str) -> bool:
    return not any(marker in value.casefold() for marker in ("token=", "signature=", "sig="))


def _license_reusable(license: object, *, now: datetime | None) -> bool:
    status = getattr(license, "status", None)
    allowed_use = getattr(license, "allowed_use", None)
    expires_at = getattr(license, "expires_at", None)
    if getattr(status, "value", status) != "known":
        return False
    if getattr(allowed_use, "value", allowed_use) not in {"internal_reuse", "redistributable"}:
        return False
    current = now or datetime.now(UTC)
    return expires_at is None or expires_at > current


def _governance_at_least_as_restrictive(
    candidate: EvidenceVisibility,
    source: EvidenceVisibility,
) -> bool:
    rank = {"public": 0, "tenant": 1, "entitlement": 2}
    if rank[candidate.scope.value] < rank[source.scope.value]:
        return False
    if source.scope.value != "public" and candidate.tenant_scope != source.tenant_scope:
        return False
    if source.scope.value == "entitlement":
        return set(candidate.entitlement_ids).issubset(source.entitlement_ids)
    return True


def _retention_at_least_as_restrictive(candidate: object, source: object) -> bool:
    if getattr(source, "legal_hold", False) and not getattr(candidate, "legal_hold", False):
        return False
    source_duration = getattr(source, "duration_seconds", None)
    candidate_duration = getattr(candidate, "duration_seconds", None)
    if source_duration is None:
        return candidate_duration is None
    return candidate_duration is None or candidate_duration >= source_duration


def _license_at_least_as_restrictive(candidate: object, source: object) -> bool:
    """Ensure a derived Evidence license never broadens its source license."""

    candidate_status = getattr(getattr(candidate, "status", None), "value", None)
    source_status = getattr(getattr(source, "status", None), "value", None)
    if candidate_status != source_status:
        return False
    rank = {"extract_only": 0, "internal_reuse": 1, "redistributable": 2}
    candidate_use = getattr(getattr(candidate, "allowed_use", None), "value", None)
    source_use = getattr(getattr(source, "allowed_use", None), "value", None)
    if candidate_use not in rank or source_use not in rank:
        return False
    if rank[candidate_use] > rank[source_use]:
        return False
    if getattr(source, "attribution_required", False) and not getattr(
        candidate, "attribution_required", False
    ):
        return False
    source_expires = getattr(source, "expires_at", None)
    candidate_expires = getattr(candidate, "expires_at", None)
    return not source_expires or (
        candidate_expires is not None and candidate_expires <= source_expires
    )


def _derived_chain_is_valid(
    root_id: str,
    root: DerivedArtifact,
    *,
    media_refs: Mapping[str, MediaRef],
    derived_artifacts: Mapping[str, DerivedArtifact],
    item_visibility: EvidenceVisibility,
    item_license: object,
    item_retention: object,
) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(artifact_id: str, artifact: DerivedArtifact) -> bool:
        if artifact_id in visiting:
            return False
        if artifact_id in visited:
            return True
        visiting.add(artifact_id)
        if not _governance_at_least_as_restrictive(item_visibility, artifact.visibility):
            return False
        if not _license_at_least_as_restrictive(item_license, artifact.license):
            return False
        if not _license_reusable(artifact.license, now=None):
            return False
        if not _retention_at_least_as_restrictive(item_retention, artifact.retention):
            return False
        for input_ref in artifact.input_refs:
            if input_ref in media_refs:
                media = media_refs[input_ref]
                if not _is_public_url(str(media.source_url)):
                    return False
                continue
            child = derived_artifacts.get(input_ref)
            if child is None or not visit(input_ref, child):
                return False
        visiting.remove(artifact_id)
        visited.add(artifact_id)
        return True

    return visit(root_id, root)


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
    "evidence_content_hash",
    "quarantine_evidence",
    "validate_evidence_provenance",
]
