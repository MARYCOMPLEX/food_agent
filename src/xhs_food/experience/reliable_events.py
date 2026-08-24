"""Versioned SSE projection for the opt-in reliable task policy."""

from __future__ import annotations

from collections.abc import Mapping

from xhs_food.contracts import ContractPayload, TaskEvent, TaskProgressProjection, TaskStatus

from .events import EventMappingError, StableEvent


def _turn_id(event: TaskEvent) -> int:
    return _parse_turn_id(event.turn_id)


def _parse_turn_id(value: str | None) -> int:
    try:
        turn_id = int(value or "0")
    except ValueError as exc:
        raise EventMappingError("reliable event turn_id must be a positive integer") from exc
    if turn_id < 1:
        raise EventMappingError("reliable event turn_id must be a positive integer")
    return turn_id


def _common(event: TaskEvent, session_id: str) -> ContractPayload:
    if not session_id:
        raise EventMappingError("reliable event session_id must be non-empty")
    return {
        "schemaVersion": "v1",
        "sessionId": session_id,
        "taskId": event.task_id,
        "turnId": _turn_id(event),
    }


def _error_payload(event: TaskEvent, *, cancelled: bool) -> ContractPayload:
    raw_error: object = event.error.model_dump(mode="json") if event.error else None
    if raw_error is None:
        raw_error = event.payload.get("error")
    if raw_error is None:
        result = event.payload.get("result")
        if isinstance(result, Mapping):
            raw_error = result.get("error")
    if isinstance(raw_error, Mapping):
        code = raw_error.get("code")
        message = raw_error.get("message")
        retryable = raw_error.get("retryable")
        if (
            isinstance(code, str)
            and code
            and isinstance(message, str)
            and message
            and isinstance(retryable, bool)
        ):
            return {"code": code, "message": message, "retryable": retryable}
    if cancelled:
        return {"code": "TASK_CANCELLED", "message": "任务已取消", "retryable": False}
    return {"code": "TASK_FAILED", "message": "研究任务失败", "retryable": False}


class ReliableEventMapper:
    """Map reliable internal events to canonical SSE v1 names.

    The mapper is a pure boundary adapter. It is intentionally not bound to
    the current HTTP route; B0 integration supplies the stream/session port.
    """

    def map(self, event: TaskEvent, *, session_id: str) -> StableEvent:
        data = _common(event, session_id)
        if event.event_type == "task.accepted":
            if event.status is not None and event.status is not TaskStatus.RUNNING:
                raise EventMappingError("task.accepted must have running status")
            data["progress"] = int((event.progress or 0.0) * 100)
            return StableEvent(event="progress", data=data)

        expected = {
            "task.completed": TaskStatus.COMPLETED,
            "task.failed": TaskStatus.FAILED,
            "task.cancelled": TaskStatus.CANCELLED,
        }.get(event.event_type)
        if expected is None:
            raise EventMappingError(f"unknown reliable event alias: {event.event_type!r}")
        if event.status is not expected:
            raise EventMappingError(
                f"{event.event_type!r} status must be {expected.value!r}"
            )

        if expected is TaskStatus.COMPLETED:
            payload = dict(data)
            payload["message"] = str(event.payload.get("message") or "搜索完成")
            return StableEvent(event="done", data=payload)

        payload = dict(data)
        payload["error"] = _error_payload(
            event,
            cancelled=expected is TaskStatus.CANCELLED,
        )
        return StableEvent(event="error", data=payload)

    def replay_expired(
        self,
        projection: TaskProgressProjection,
        *,
        session_id: str,
        snapshot: ContractPayload,
    ) -> StableEvent:
        """Build the single resync control event for an expired Redis cursor."""

        if not session_id:
            raise EventMappingError("reliable event session_id must be non-empty")
        turn_id = _parse_turn_id(projection.turn_id)
        return StableEvent(
            event="replay_expired",
            data={
                "schemaVersion": "v1",
                "sessionId": session_id,
                "taskId": projection.task_id,
                "turnId": turn_id,
                "reason": "cursor_not_retained",
                "action": "resync",
                "snapshot": dict(snapshot),
            },
        )


__all__ = ["ReliableEventMapper"]
