# -*- coding: utf-8 -*-
"""Search event payload types."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class SearchEventType(str, Enum):
    """SSE event types pushed to the client."""

    # 步骤状态
    STEP_START = "step_start"
    STEP_DONE = "step_done"
    STEP_ERROR = "step_error"

    # 进度 / 心跳
    PROGRESS = "progress"

    # 中间结果
    INTENT_PARSED = "intent_parsed"
    NOTES_FOUND = "notes_found"
    ANALYSIS_DONE = "analysis_done"

    # 店铺结果（流式）
    RESTAURANT = "restaurant"

    # 最终状态
    RESULT = "result"
    ERROR = "error"
    DONE = "done"


TERMINAL_EVENTS = frozenset({SearchEventType.DONE, SearchEventType.ERROR})


@dataclass
class SearchEvent:
    """Individual SSE event."""

    type: SearchEventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @property
    def is_terminal(self) -> bool:
        return self.type in TERMINAL_EVENTS

    def to_sse(self) -> Dict[str, str]:
        return {
            "event": self.type.value,
            "data": json.dumps(self.data, ensure_ascii=False),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, payload: str) -> "SearchEvent":
        raw = json.loads(payload)
        return cls(
            type=SearchEventType(raw["type"]),
            data=raw.get("data", {}),
            timestamp=raw.get("timestamp", time.time()),
        )
