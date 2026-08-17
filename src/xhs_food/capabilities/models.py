"""Capability metadata and trust policy models."""

from __future__ import annotations

from enum import Enum, IntEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CapabilityKind(str, Enum):
    LOCAL = "local"
    SKILL = "skill"
    MCP = "mcp"


class SideEffectLevel(IntEnum):
    READ_ONLY = 0
    WRITE = 1
    EXTERNAL = 2
    DESTRUCTIVE = 3


class CapabilityManifest(BaseModel):
    """Description exposed to planners and enforced by the gateway."""

    model_config = ConfigDict(extra="allow")

    name: str
    version: str = "1.0.0"
    description: str = ""
    kind: CapabilityKind = CapabilityKind.LOCAL
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=60.0, gt=0, le=3600)
    max_concurrency: int = Field(default=4, ge=1, le=1000)
    estimated_cost: float = Field(default=0.0, ge=0)
    side_effect: SideEffectLevel = SideEffectLevel.READ_ONLY
    auth_scopes: list[str] = Field(default_factory=list)
    trust: str = "builtin"
    idempotent: bool = True
    tags: list[str] = Field(default_factory=list)
