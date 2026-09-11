"""Deterministic, privacy-preserving comparison of shadow and legacy payloads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

DiffDecision = Literal["match", "approved", "review"]


@dataclass(frozen=True, slots=True)
class ShadowDifference:
    path: str
    legacy_digest: str | None
    shadow_digest: str | None


@dataclass(frozen=True, slots=True)
class ShadowDiffApproval:
    fixture_id: str
    allowed_paths: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ShadowDiffApproval:
        if value.get("schemaVersion") != "evidence-shadow-approval/v1":
            raise ValueError("unsupported shadow approval fixture schema")
        fixture_id = value.get("fixtureId")
        allowed = value.get("allowedPaths", [])
        if not isinstance(fixture_id, str) or not fixture_id:
            raise ValueError("shadow approval fixtureId must be non-empty")
        if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
            raise ValueError("shadow approval allowedPaths must be string array")
        return cls(fixture_id=fixture_id, allowed_paths=tuple(allowed))


@dataclass(frozen=True, slots=True)
class ShadowDiffReport:
    schema_version: str
    fixture_id: str
    decision: DiffDecision
    differences: tuple[ShadowDifference, ...]


def compare_shadow_legacy(
    legacy: object,
    shadow: object,
    *,
    approval: ShadowDiffApproval | None = None,
    fixture_id: str = "unapproved",
) -> ShadowDiffReport:
    """Compare payload leaves while retaining only paths and SHA-256 digests."""

    effective_fixture = approval.fixture_id if approval is not None else fixture_id
    legacy_leaves = _flatten(legacy)
    shadow_leaves = _flatten(shadow)
    differences = tuple(
        ShadowDifference(
            path=path,
            legacy_digest=legacy_leaves.get(path),
            shadow_digest=shadow_leaves.get(path),
        )
        for path in sorted(set(legacy_leaves) | set(shadow_leaves))
        if legacy_leaves.get(path) != shadow_leaves.get(path)
    )
    if not differences:
        decision: DiffDecision = "match"
    elif approval is not None and all(
        item.path in approval.allowed_paths for item in differences
    ):
        decision = "approved"
    else:
        decision = "review"
    return ShadowDiffReport(
        schema_version="evidence-shadow-diff/v1",
        fixture_id=effective_fixture,
        decision=decision,
        differences=differences,
    )


def _flatten(value: object, path: str = "root") -> dict[str, str]:
    if isinstance(value, Mapping):
        if not value:
            return {path: _digest(value)}
        leaves: dict[str, str] = {}
        for key in sorted(value, key=str):
            leaves.update(_flatten(value[key], f"{path}.{key}"))
        return leaves
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if not value:
            return {path: _digest(value)}
        leaves: dict[str, str] = {}
        for index, item in enumerate(value):
            leaves.update(_flatten(item, f"{path}[{index}]"))
        return leaves
    return {path: _digest(value)}


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "ShadowDiffApproval",
    "ShadowDiffReport",
    "ShadowDifference",
    "compare_shadow_legacy",
]
