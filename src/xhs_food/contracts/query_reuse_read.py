"""Contracts for shadow comparison and bounded Query Family read canaries."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

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


class QueryReuseShadowReport(ContractModel):
    schema_version: Literal["query-reuse-read/v1"] = QUERY_REUSE_READ_VERSION
    request_key_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: QueryReuseShadowStatus
    legacy_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    candidate_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    served_candidate: bool = False


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

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")  # type: ignore[union-attr]
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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
