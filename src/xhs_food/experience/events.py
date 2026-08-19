"""Pure projection from internal task events to the legacy SSE contract."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from xhs_food.contracts import ContractPayload, TaskEvent


class EventMappingError(ValueError):
    """A task event cannot be represented by the selected stable encoding."""


@dataclass(frozen=True, slots=True)
class StableEvent:
    """An SSE event name and payload without a transport-assigned wire cursor."""

    event: str
    data: ContractPayload


_STEP_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "step1": "step1",
        "intent_parsing": "step1",
        "step2": "step2",
        "evidence_collection": "step2",
        "xhs_search": "step2",
        "step3": "step3",
        "evidence_analysis": "step3",
        "comment_analysis": "step3",
        "step4": "step4",
        "evidence_validation": "step4",
        "cross_validation": "step4",
        "step5": "step5",
        "entity_enrichment": "step5",
        "poi_enrichment": "step5",
        "step6": "step6",
        "result_generation": "step6",
    }
)


def _legacy_step_id(alias: object) -> str:
    if not isinstance(alias, str):
        raise EventMappingError("step alias must be a string")
    try:
        return _STEP_ALIASES[alias]
    except KeyError as exc:
        raise EventMappingError(f"unknown step alias: {alias!r}") from exc


def _normalise_step_snapshot(data: ContractPayload) -> None:
    raw_steps = data.get("steps")
    if raw_steps is None:
        return
    if not isinstance(raw_steps, list):
        raise EventMappingError("steps payload must be a list")

    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise EventMappingError(f"steps[{index}] must be an object")
        if "id" not in raw_step:
            raise EventMappingError(f"steps[{index}] is missing an id")
        raw_step["id"] = _legacy_step_id(raw_step["id"])


def _copy_and_normalise_payload(event: TaskEvent, *, require_step: bool) -> ContractPayload:
    data = deepcopy(event.payload)
    if event.progress is not None and "progress" not in data:
        data["progress"] = int(event.progress * 100)
    if event.error is not None and "error" not in data:
        data["error"] = event.error.message or event.error.code
    if event.event_type == "done" and "message" not in data:
        data["message"] = "搜索完成"
    payload_alias = data.get("step")
    event_alias = event.step_id

    payload_step = _legacy_step_id(payload_alias) if payload_alias is not None else None
    event_step = _legacy_step_id(event_alias) if event_alias is not None else None
    if payload_step is not None and event_step is not None and payload_step != event_step:
        raise EventMappingError(
            f"conflicting step aliases: step_id={event_alias!r}, payload={payload_alias!r}"
        )

    step = event_step or payload_step
    if require_step and step is None:
        raise EventMappingError(f"{event.event_type!r} requires a step alias")
    if step is not None:
        if "step" in data:
            data["step"] = step
        elif require_step:
            data = {"step": step, **data}

    _normalise_step_snapshot(data)
    return data


def _map_step_event(event: TaskEvent) -> ContractPayload:
    return _copy_and_normalise_payload(event, require_step=True)


def _map_regular_event(event: TaskEvent) -> ContractPayload:
    return _copy_and_normalise_payload(event, require_step=False)


_PayloadMapper = Callable[[TaskEvent], ContractPayload]

_EVENT_DISPATCH: Final[Mapping[str, _PayloadMapper]] = MappingProxyType(
    {
        "step_start": _map_step_event,
        "step_done": _map_step_event,
        "step_error": _map_step_event,
        "progress": _map_regular_event,
        "intent_parsed": _map_regular_event,
        "notes_found": _map_regular_event,
        "analysis_done": _map_regular_event,
        "restaurant": _map_regular_event,
        "result": _map_regular_event,
        "error": _map_regular_event,
        "done": _map_regular_event,
    }
)


class StableEventMapper:
    """Map internal events to the unchanged legacy SSE vocabulary and payload."""

    def map(self, event: TaskEvent) -> StableEvent:
        try:
            payload_mapper = _EVENT_DISPATCH[event.event_type]
        except KeyError as exc:
            raise EventMappingError(f"unknown event alias: {event.event_type!r}") from exc

        # TaskEvent.event_id is internal identity. The EventBus assigns the SSE cursor.
        return StableEvent(event=event.event_type, data=payload_mapper(event))


__all__ = ["EventMappingError", "StableEvent", "StableEventMapper"]
