"""Typed memory records and queries."""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MemoryScope(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    namespace: str
    scope: MemoryScope
    content: Any
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float | None = None
    created_at: float = Field(default_factory=time.time)
    expires_at: float | None = None

    def is_expired(self, now: float | None = None) -> bool:
        return self.expires_at is not None and self.expires_at <= (now or time.time())


class MemoryQuery(BaseModel):
    query: str
    namespace: str | None = None
    scope: MemoryScope | None = None
    limit: int = Field(default=10, ge=1, le=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
