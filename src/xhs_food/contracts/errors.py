"""Stable failure classification shared by contract boundaries."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .base import ContractPayload, NonEmptyStr, VersionedContract


class ErrorCategory(StrEnum):
    """Transport-independent categories suitable for policy and mapping."""

    VALIDATION = "validation"
    POLICY_DENIED = "policy_denied"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    MALFORMED_RESPONSE = "malformed_response"
    BUDGET_EXHAUSTED = "budget_exhausted"
    REPLAY_EXPIRED = "replay_expired"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


class ErrorScope(StrEnum):
    """The isolation boundary that owns a failure."""

    REQUEST = "request"
    TASK = "task"
    PLAN = "plan"
    TOOL = "tool"
    SOURCE = "source"
    PROVIDER = "provider"
    REPOSITORY = "repository"
    WORKFLOW = "workflow"
    CACHE = "cache"
    EVENT_BUS = "event_bus"
    OBJECT_STORE = "object_store"
    DOMAIN_PACK = "domain_pack"


class ContractError(VersionedContract):
    """Serializable error; consumers branch on ``code`` and ``category``."""

    code: NonEmptyStr
    category: ErrorCategory
    scope: ErrorScope
    retryable: bool = False
    terminal: bool = False
    message: str | None = None
    boundary_ref: str | None = None
    details: ContractPayload = Field(default_factory=dict)


__all__ = ["ContractError", "ErrorCategory", "ErrorScope"]
