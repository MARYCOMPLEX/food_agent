"""Search event emitter — facade kept stable for orchestrator code.

Replaces the previous in-process emitter with an :class:`EventBus`-backed
publisher. The step tracking state lives on the emitter (per session); the
underlying event log lives on the bus.
"""
from __future__ import annotations

import asyncio
from typing import Any

from .bus import EventBus, get_event_bus
from .step_projection import LegacySixStepProjection
from .types import SearchEvent, SearchEventType


class SearchEventEmitter:
    """Per-session emitter used by the orchestrator.

    The emitter does not buffer events itself — replay is the bus's job.
    It still tracks the pipeline ``steps`` for ``/v1/search/status``.
    """

    def __init__(
        self,
        session_id: str,
        bus: EventBus,
        *,
        step_projection: LegacySixStepProjection | None = None,
    ) -> None:
        self._session_id = session_id
        self._bus = bus
        self._step_projection = step_projection or LegacySixStepProjection()
        self._completed: bool = False

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def steps(self) -> list[dict[str, str]]:
        return self._step_projection.steps

    @property
    def is_completed(self) -> bool:
        return self._completed

    # Backwards-compat shims --------------------------------------------------

    @property
    def _steps_legacy(self) -> list[dict[str, str]]:
        return self._step_projection.steps

    def reset(self) -> None:
        self._step_projection.reset()
        self._completed = False

    def init_steps(self, query: str) -> None:
        _ = query  # reserved for future per-query labels
        self._step_projection.initialize()

    # Core emit ---------------------------------------------------------------

    async def emit(self, event: SearchEvent) -> str:
        entry_id = await self._bus.publish(self._session_id, event)
        if event.is_terminal:
            self._completed = True
        return entry_id

    async def emit_progress(self, kind: str, data: dict[str, Any] | None = None) -> str:
        """Publish a workflow progress payload without exposing event types.

        The orchestrator only knows about this transport-facing method.  The
        mapping from internal workflow milestones to the concrete SSE event
        enum stays in the event layer, which keeps the architecture dependency
        direction explicit.
        """

        event_type = {
            "intent_parsed": SearchEventType.INTENT_PARSED,
            "note_collected": SearchEventType.NOTES_FOUND,
            "note_analyzed": SearchEventType.ANALYSIS_DONE,
        }.get(kind, SearchEventType.PROGRESS)
        payload = dict(data or {})
        payload.setdefault("kind", kind)
        return await self.emit(SearchEvent(type=event_type, data=payload))

    # Step helpers ------------------------------------------------------------

    def _update_step(self, step_id: str, status: str, message: str = "") -> None:
        self._step_projection.update(step_id, status, message)

    def _progress(self) -> int:
        return self._step_projection.progress()

    async def step_start(self, step_id: str, message: str = "") -> None:
        self._update_step(step_id, "loading", message)
        await self.emit(
            SearchEvent(
                type=SearchEventType.STEP_START,
                data={
                    "step": step_id,
                    "message": message,
                    "steps": self.steps,
                    "progress": self._progress(),
                },
            )
        )

    async def step_done(
        self,
        step_id: str,
        message: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._update_step(step_id, "done", message)
        self._step_projection.advance()
        data: dict[str, Any] = {
            "step": step_id,
            "message": message,
            "steps": self.steps,
            "progress": self._progress(),
        }
        if extra:
            data.update(extra)
        await self.emit(SearchEvent(type=SearchEventType.STEP_DONE, data=data))

    async def step_error(self, step_id: str, error: str) -> None:
        self._update_step(step_id, "error")
        await self.emit(
            SearchEvent(
                type=SearchEventType.STEP_ERROR,
                data={"step": step_id, "error": error, "steps": self.steps},
            )
        )

    async def emit_restaurant(self, restaurant: dict[str, Any]) -> None:
        await self.emit(
            SearchEvent(type=SearchEventType.RESTAURANT, data={"restaurant": restaurant})
        )

    async def emit_result(self, summary: str, total: int, filtered: int = 0) -> None:
        await self.emit(
            SearchEvent(
                type=SearchEventType.RESULT,
                data={
                    "summary": summary,
                    "total": total,
                    "filtered": filtered,
                    "steps": self.steps,
                },
            )
        )

    async def emit_error(self, error: str) -> None:
        await self.emit(SearchEvent(type=SearchEventType.ERROR, data={"error": error}))

    async def emit_done(self) -> None:
        await self.emit(SearchEvent(type=SearchEventType.DONE, data={"message": "搜索完成"}))


# ---------------------------------------------------------------------------
# Per-session emitter accessor (thin cache; underlying state is on the bus)
# ---------------------------------------------------------------------------


_emitters: dict[str, SearchEventEmitter] = {}
_emitters_lock = asyncio.Lock()


async def get_emitter(session_id: str) -> SearchEventEmitter:
    """Return an emitter for ``session_id`` (creates one if missing)."""
    if session_id in _emitters:
        return _emitters[session_id]
    async with _emitters_lock:
        if session_id in _emitters:
            return _emitters[session_id]
        bus = await get_event_bus()
        _emitters[session_id] = SearchEventEmitter(session_id, bus)
        return _emitters[session_id]


def remove_emitter(session_id: str) -> None:
    """Drop the cached emitter (event log on the bus is unaffected)."""
    _emitters.pop(session_id, None)
