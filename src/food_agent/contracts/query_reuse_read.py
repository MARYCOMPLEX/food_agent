"""Contracts for shadow comparison and bounded Query Family read canaries."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from .base import ContractModel, JsonValue
from .query_reuse import QueryReuseDecision

QUERY_REUSE_READ_VERSION = "query-reuse-read/v1"


class QueryReuseReadMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    CANARY = "canary"


class QueryReuseReadSettings(ContractModel):
    """Closed-world controls; personalization and scheduling stay elsewhere."""

    schema_version: Literal["query-reuse-read/v1"] = QUERY_REUSE_READ_VERSION
    mode: QueryReuseReadMode = QueryReuseReadMode.OFF
    sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    personalization_enabled: Literal[False] = False
    background_refresh_enabled: Literal[False] = False
    # A release record must explicitly opt in before a sampled candidate can
    # replace the legacy result. Composition bindings may set this true only
    # after the owner gate is recorded.
    canary_gate_approved: bool = False

    @model_validator(mode="after")
    def validate_canary_rate(self) -> QueryReuseReadSettings:
        if self.mode is QueryReuseReadMode.CANARY and self.sample_rate <= 0:
            raise ValueError("canary mode requires a positive sample_rate")
        if self.mode is QueryReuseReadMode.OFF and self.sample_rate != 0:
            raise ValueError("off mode cannot carry a sample_rate")
        return self


class QueryReuseShadowStatus(StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    SKIPPED = "skipped"
    FAILED = "failed"


class QueryReuseShadowReport(ContractModel):
    schema_version: Literal["query-reuse-read/v1"] = QUERY_REUSE_READ_VERSION
    request_key_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: QueryReuseShadowStatus
    legacy_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    candidate_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    served_candidate: bool = False
    failure_code: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_.-]{0,63}$"
    )


class QueryReuseReadOutcome(ContractModel):
    """Legacy value remains the caller's authority; candidate output is diagnostic."""

    schema_version: Literal["query-reuse-read/v1"] = QUERY_REUSE_READ_VERSION
    legacy_result: JsonValue
    candidate: QueryReuseDecision | None = None
    served_result: JsonValue
    served_candidate: bool = False
    shadow: QueryReuseShadowReport


def stable_request_key_hash(request_key: str) -> str:
    if not request_key:
        raise ValueError("query reuse request key must be non-empty")
    return hashlib.sha256(request_key.encode("utf-8")).hexdigest()


def stable_sample(request_key: str, sample_rate: float) -> bool:
    """Select a request deterministically so retries do not change exposure."""

    if not 0.0 <= sample_rate <= 1.0:
        raise ValueError("sample_rate must be between 0 and 1")
    if sample_rate == 0:
        return False
    bucket = int(stable_request_key_hash(request_key)[:16], 16) / 16**16
    return bucket < sample_rate


def digest_public_result(value: object) -> str:
    """Hash only a JSON-compatible public result, never identity or memory state."""

    value = _public_digest_value(value)
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


_PRIVATE_KEY_MARKERS = frozenset(
    {
        "user",
        "users",
        "userid",
        "session",
        "sessions",
        "sessionid",
        "subject",
        "subjects",
        "identity",
        "identities",
        "deviceid",
        "private",
        "preference",
        "preferences",
        "memory",
        "favorite",
        "favorites",
        "click",
        "clicks",
        "cookie",
        "token",
        "credential",
        "credentials",
        "password",
        "secret",
        "account",
    }
)


def _public_digest_value(value: object) -> Any:
    """Drop identity-bearing keys before computing comparison digests."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")  # type: ignore[union-attr]
    if isinstance(value, Mapping):
        public: dict[str, Any] = {}
        for key, item in value.items():
            normalized = "".join(character for character in str(key).casefold() if character.isalnum())
            if normalized in _PRIVATE_KEY_MARKERS or any(
                marker in normalized for marker in _PRIVATE_KEY_MARKERS
            ):
                continue
            public[str(key)] = _public_digest_value(item)
        return public
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_public_digest_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


__all__ = [
    "QUERY_REUSE_READ_VERSION",
    "QueryReuseReadMode",
    "QueryReuseReadOutcome",
    "QueryReuseReadSettings",
    "QueryReuseShadowReport",
    "QueryReuseShadowStatus",
    "digest_public_result",
    "stable_request_key_hash",
    "stable_sample",
]
