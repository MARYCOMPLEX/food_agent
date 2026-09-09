"""Deterministic reducer for the public ResearchEvent v1 experience stream.

The reducer is intentionally transport-neutral.  SSE, WebSocket, polling, and
server-rendered clients can all apply the same event list and obtain the same
``UserResearchProjectionV1`` snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from xhs_food.contracts.research_experience import (
    CORE_RESEARCH_EVENT_KINDS,
    PUBLIC_EXPERIENCE_MAX_IDEMPOTENCY_LEDGER,
    ControversyViewV1,
    CoverageViewV1,
    EntityRef,
    EvidenceItemV1,
    GapViewV1,
    IntentViewV1,
    PlanStepViewV1,
    ProfileStatus,
    ProfileViewV1,
    RecommendationStatus,
    RecommendationViewV1,
    ResearchEventKind,
    ResearchEventV1,
    ResearchMetricsV1,
    ResearchMutation,
    ResearchRunStatus,
    StepStatus,
    TerminationViewV1,
    UserResearchProjectionV1,
)


class ProjectionError(ValueError):
    """Base error raised when a public event cannot update a projection."""


class ProjectionIdentityError(ProjectionError):
    """An event belongs to another session, task, turn, or run."""


class ProjectionResyncRequired(ProjectionError):
    """The retained event sequence is no longer contiguous."""

    def __init__(self, *, expected_sequence: int, received_sequence: int, reason: str) -> None:
        self.expected_sequence = expected_sequence
        self.received_sequence = received_sequence
        self.reason = reason
        super().__init__(
            f"projection resync required ({reason}); expected sequence "
            f"{expected_sequence}, received {received_sequence}"
        )


class ProjectionTerminalError(ProjectionError):
    """A non-duplicate event attempted to mutate a terminal projection."""


_EMPTY_VALUES = (None, "", [], (), {})
_TERMINAL_STATUSES = frozenset(
    {
        ResearchRunStatus.SUCCEEDED,
        ResearchRunStatus.PARTIAL,
        ResearchRunStatus.FAILED,
        ResearchRunStatus.CANCELLED,
        ResearchRunStatus.BLOCKED,
    }
)


def initial_research_projection(
    session_id: str,
    task_id: str,
    turn_id: int,
    *,
    run_id: str | None = None,
) -> UserResearchProjectionV1:
    """Create an empty, queued projection for a newly admitted turn."""

    return UserResearchProjectionV1(
        sessionId=session_id,
        taskId=task_id,
        turnId=turn_id,
        runId=run_id,
    )


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectionError(f"{label} must be an object")
    return dict(value)


def _payload_objects(payload: object, *, singular: str, plural: str) -> list[dict[str, Any]]:
    """Accept the stable wrapper form and a direct single-object form."""

    if isinstance(payload, Mapping):
        if plural in payload:
            raw = payload[plural]
            if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
                raise ProjectionError(f"payload.{plural} must be an array")
            return [_mapping(item, label=f"payload.{plural}[{index}]") for index, item in enumerate(raw)]
        for key in (singular, "item", "value"):
            if key in payload:
                return [_mapping(payload[key], label=f"payload.{key}")]
        return [dict(payload)]
    raise ProjectionError(f"payload for {singular} must be an object")


def _merge_non_empty(
    existing: object,
    incoming: object,
    *,
    allow_empty: bool = False,
) -> object:
    """Merge a patch without deleting known facts through sparse responses."""

    if isinstance(existing, Mapping) and isinstance(incoming, Mapping):
        result = dict(existing)
        for key, value in incoming.items():
            if key in result:
                result[key] = _merge_non_empty(result[key], value, allow_empty=allow_empty)
            elif allow_empty or value not in _EMPTY_VALUES:
                result[key] = value
        return result
    if not allow_empty and incoming in _EMPTY_VALUES:
        return existing
    return incoming


def _validated_projection(
    projection: UserResearchProjectionV1,
    **updates: object,
) -> UserResearchProjectionV1:
    """Apply updates and run all model validators again."""

    data = projection.model_dump(mode="python", by_alias=False)
    data.update(updates)
    return UserResearchProjectionV1.model_validate(data)


def _event_status(event: ResearchEventV1, default: ResearchRunStatus) -> ResearchRunStatus:
    return event.status or default


def _payload_text(payload: Mapping[str, Any], key: str, fallback: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) and value else fallback


def _terminal(projection: UserResearchProjectionV1) -> bool:
    return projection.status in _TERMINAL_STATUSES or projection.termination is not None


def _check_identity(projection: UserResearchProjectionV1, event: ResearchEventV1) -> None:
    if event.session_id != projection.session_id:
        raise ProjectionIdentityError("event session_id does not match projection")
    if event.task_id != projection.task_id:
        raise ProjectionIdentityError("event task_id does not match projection")
    if event.turn_id != projection.turn_id:
        raise ProjectionIdentityError("event turn_id does not match projection")
    if (
        projection.run_id is not None
        and event.run_id is not None
        and projection.run_id != event.run_id
    ):
        raise ProjectionIdentityError("event run_id does not match projection")


def _check_sequence(projection: UserResearchProjectionV1, event: ResearchEventV1) -> bool:
    """Return true for a duplicate; otherwise require the next contiguous event."""

    if event.event_id in projection.applied_event_ids:
        return True
    expected = projection.last_sequence + 1
    if event.sequence != expected:
        reason = "sequence_gap" if event.sequence > expected else "unknown_replay"
        raise ProjectionResyncRequired(
            expected_sequence=expected,
            received_sequence=event.sequence,
            reason=reason,
        )
    return False


def _with_event_cursor(
    projection: UserResearchProjectionV1,
    event: ResearchEventV1,
    *,
    updates: Mapping[str, object] | None = None,
) -> UserResearchProjectionV1:
    event_ids = (*projection.applied_event_ids, event.event_id)
    max_ids = PUBLIC_EXPERIENCE_MAX_IDEMPOTENCY_LEDGER
    if len(event_ids) > max_ids:
        event_ids = event_ids[-max_ids:]
    values: dict[str, object] = {
        "last_sequence": event.sequence,
        "revision": projection.revision + 1,
        "updated_at": event.occurred_at,
        "applied_event_ids": event_ids,
    }
    # Counts are projection-local (not fabricated provider totals).  Preserve
    # an explicitly supplied aggregate when it is larger than the retained
    # client window, while still making incremental UIs immediately useful.
    values["metrics"] = projection.metrics.model_copy(
        update={
            "evidence_items": max(projection.metrics.evidence_items, len(projection.evidence)),
            "comment_evidence_items": max(
                projection.metrics.comment_evidence_items,
                sum(1 for item in projection.evidence if item.comment_ref is not None),
            ),
            "profiles": max(projection.metrics.profiles, len(projection.profiles)),
            "controversies": max(projection.metrics.controversies, len(projection.controversies)),
            "gaps": max(projection.metrics.gaps, len(projection.gaps)),
            "actions": max(projection.metrics.actions, len(projection.plan)),
        }
    )
    if updates:
        values.update(updates)
    return _validated_projection(projection, **values)


def _entity_id(data: Mapping[str, Any], key: str, entity: EntityRef | None) -> str | None:
    value = data.get(key)
    if value is None and entity is not None:
        value = entity.entity_id
    return value if isinstance(value, str) and value else None


def _python_field_name(alias: str) -> str:
    """Convert the public camelCase identity key to a model attribute name."""

    return alias[0].lower() + "".join(
        f"_{character.lower()}" if character.isupper() else character
        for character in alias[1:]
    )


def _upsert_collection[ModelT](
    values: tuple[ModelT, ...],
    incoming: Mapping[str, Any],
    *,
    id_key: str,
    model_type: Any,
    mutation: ResearchMutation,
    entity: EntityRef | None,
) -> tuple[ModelT, ...]:
    item_id = _entity_id(incoming, id_key, entity)
    if item_id is None:
        raise ProjectionError(f"{id_key} is required for {model_type.__name__}")
    index = next(
        (
            index
            for index, item in enumerate(values)
            if getattr(item, _python_field_name(id_key)) == item_id
        ),
        None,
    )
    if mutation is ResearchMutation.REMOVE:
        if index is None:
            return values
        return values[:index] + values[index + 1 :]
    if index is not None and mutation is ResearchMutation.APPEND:
        return values

    if index is None or mutation is ResearchMutation.REPLACE:
        candidate = dict(incoming)
    else:
        existing_model: Any = values[index]
        existing = existing_model.model_dump(mode="json", by_alias=True)
        candidate = _merge_non_empty(
            existing,
            incoming,
            allow_empty=False,
        )
        if not isinstance(candidate, dict):
            raise ProjectionError("merged public entity must remain an object")
    if id_key not in candidate:
        candidate[id_key] = item_id
    try:
        parsed = model_type.model_validate(candidate)
    except ValueError as exc:
        raise ProjectionError(f"invalid {model_type.__name__} payload: {exc}") from exc
    if index is None:
        return (*values, parsed)
    return values[:index] + (parsed,) + values[index + 1 :]


def _apply_entity_event[ModelT](
    projection: UserResearchProjectionV1,
    event: ResearchEventV1,
    *,
    singular: str,
    plural: str,
    id_key: str,
    model_type: Any,
    collection_name: str,
) -> UserResearchProjectionV1:
    objects = _payload_objects(event.payload, singular=singular, plural=plural)
    if collection_name == "evidence":
        if event.mutation is not ResearchMutation.APPEND:
            raise ProjectionError("evidence is append-only in ResearchEvent v1")
        effective_mutation = ResearchMutation.APPEND
    else:
        # The envelope defaults to append for lifecycle events.  Entity events
        # without an explicit mutation are still safe keyed upserts.
        effective_mutation = (
            ResearchMutation.UPSERT
            if event.mutation is ResearchMutation.APPEND
            else event.mutation
        )
    current = getattr(projection, collection_name)
    for item in objects:
        current = _upsert_collection(
            current,
            item,
            id_key=id_key,
            model_type=model_type,
            mutation=effective_mutation,
            entity=event.entity,
        )
    updated = _validated_projection(projection, **{collection_name: current})
    if collection_name == "gaps":
        updated = _attach_gap_state(updated, current)
    return updated


def _attach_gap_state(
    projection: UserResearchProjectionV1,
    gaps: tuple[GapViewV1, ...],
) -> UserResearchProjectionV1:
    """Reflect affected optional entities as partial without erasing evidence."""

    profile_updates = list(projection.profiles)
    recommendation_updates = list(projection.recommendations)
    for gap in gaps:
        for reference in gap.affected_refs:
            if reference.entity_type in {"profile", "shop"}:
                for index, profile in enumerate(profile_updates):
                    matches = reference.entity_id in {
                        profile.profile_id,
                        profile.entity_ref.entity_id if profile.entity_ref else "",
                    }
                    if not matches:
                        continue
                    gap_refs = tuple(dict.fromkeys((*profile.gap_refs, gap.gap_id)))
                    status = profile.status
                    if status is ProfileStatus.PENDING:
                        status = ProfileStatus.PARTIAL
                    profile_updates[index] = profile.model_copy(
                        update={"status": status, "gap_refs": gap_refs}
                    )
            if reference.entity_type in {"recommendation", "shop"}:
                for index, recommendation in enumerate(recommendation_updates):
                    matches = reference.entity_id in {
                        recommendation.recommendation_id,
                        (
                            recommendation.entity_ref.entity_id
                            if recommendation.entity_ref
                            else ""
                        ),
                    }
                    if not matches:
                        continue
                    status = recommendation.status
                    if status is RecommendationStatus.CANDIDATE:
                        status = RecommendationStatus.PARTIAL
                    recommendation_updates[index] = recommendation.model_copy(
                        update={"status": status}
                    )
    if profile_updates == list(projection.profiles) and recommendation_updates == list(
        projection.recommendations
    ):
        return projection
    return _validated_projection(
        projection,
        profiles=tuple(profile_updates),
        recommendations=tuple(recommendation_updates),
    )


def _apply_plan_update(
    projection: UserResearchProjectionV1,
    event: ResearchEventV1,
) -> UserResearchProjectionV1:
    payload = _mapping(event.payload, label="plan payload")
    raw_steps = payload.get("steps")
    if raw_steps is None:
        raw_steps = payload.get("plan")
    if raw_steps is None:
        return projection
    if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, (str, bytes, bytearray)):
        raise ProjectionError("plan.steps must be an array")
    steps = tuple(
        PlanStepViewV1.model_validate(_mapping(item, label=f"plan.steps[{index}]"))
        for index, item in enumerate(raw_steps)
    )
    if event.mutation is ResearchMutation.REPLACE:
        return _validated_projection(projection, plan=steps)
    merged = projection.plan
    for step in steps:
        merged = _upsert_collection(
            merged,
            step.model_dump(mode="json", by_alias=True),
            id_key="stepId",
            model_type=PlanStepViewV1,
            mutation=ResearchMutation.UPSERT,
            entity=None,
        )
    return _validated_projection(projection, plan=merged)


def _step_status_for_event(kind: str) -> StepStatus:
    return {
        ResearchEventKind.ACTION_STARTED.value: StepStatus.RUNNING,
        ResearchEventKind.ACTION_PROGRESS.value: StepStatus.RUNNING,
        ResearchEventKind.ACTION_COMPLETED.value: StepStatus.SUCCEEDED,
    }.get(kind, StepStatus.RUNNING)


def _apply_action_event(
    projection: UserResearchProjectionV1,
    event: ResearchEventV1,
) -> UserResearchProjectionV1:
    payload = _mapping(event.payload, label="action payload")
    raw_step = payload.get("step")
    step_data = dict(raw_step) if isinstance(raw_step, Mapping) else {}
    step_id = step_data.get("stepId") or payload.get("stepId") or payload.get("actionId")
    if step_id is None and event.entity is not None:
        step_id = event.entity.entity_id
    if not isinstance(step_id, str) or not step_id:
        # An action can still update the run phase and metrics before a UI
        # step has been materialised.  Do not invent an array position.
        return _validated_projection(
            projection,
            phase=event.phase or projection.phase,
            status=_event_status(event, ResearchRunStatus.RUNNING),
        )
    step_data.setdefault("stepId", step_id)
    step_data.setdefault("label", str(payload.get("label") or payload.get("actionName") or step_id))
    step_data.setdefault("status", payload.get("stepStatus") or _step_status_for_event(event.kind).value)
    if event.phase is not None:
        step_data.setdefault("phase", event.phase)
    if "detail" not in step_data and isinstance(payload.get("detail"), str):
        step_data["detail"] = payload["detail"]
    current = _upsert_collection(
        projection.plan,
        step_data,
        id_key="stepId",
        model_type=PlanStepViewV1,
        mutation=ResearchMutation.UPSERT,
        entity=None,
    )
    return _validated_projection(
        projection,
        plan=current,
        phase=event.phase or projection.phase,
        status=_event_status(event, ResearchRunStatus.RUNNING),
    )


def _metrics_from_payload(
    projection: UserResearchProjectionV1,
    payload: Mapping[str, Any],
) -> ResearchMetricsV1:
    raw = payload.get("metrics")
    if raw is None:
        return projection.metrics
    if not isinstance(raw, Mapping):
        raise ProjectionError("payload.metrics must be an object")
    merged = _merge_non_empty(
        projection.metrics.model_dump(mode="json", by_alias=True),
        dict(raw),
        allow_empty=False,
    )
    return ResearchMetricsV1.model_validate(merged)


def _coverage_from_payload(
    projection: UserResearchProjectionV1,
    payload: Mapping[str, Any],
) -> object:
    if "coverage" not in payload:
        return projection.coverage
    raw = payload["coverage"]
    if raw is None:
        return projection.coverage
    return CoverageViewV1.model_validate(raw)


def _apply_run_started(
    projection: UserResearchProjectionV1,
    event: ResearchEventV1,
) -> UserResearchProjectionV1:
    payload = _mapping(event.payload, label="run_started payload")
    updates: dict[str, object] = {
        "status": _event_status(event, ResearchRunStatus.RUNNING),
        "phase": event.phase or _payload_text(payload, "phase", projection.phase),
        "summary": _payload_text(payload, "summary", projection.summary),
    }
    if isinstance(payload.get("intent"), Mapping):
        updates["intent"] = IntentViewV1.model_validate(payload["intent"])
    if "plan" in payload or "steps" in payload:
        updates["plan"] = _apply_plan_update(projection, event).plan
    return _validated_projection(projection, **updates)


def _apply_progress(
    projection: UserResearchProjectionV1,
    event: ResearchEventV1,
) -> UserResearchProjectionV1:
    payload = _mapping(event.payload, label="run_progress payload")
    updates: dict[str, object] = {
        "status": _event_status(event, ResearchRunStatus.RUNNING),
        "phase": event.phase or _payload_text(payload, "phase", projection.phase),
        "summary": _payload_text(payload, "summary", projection.summary),
        "metrics": _metrics_from_payload(projection, payload),
        "coverage": _coverage_from_payload(projection, payload),
    }
    return _validated_projection(projection, **updates)


def _apply_terminal(
    projection: UserResearchProjectionV1,
    event: ResearchEventV1,
    status: ResearchRunStatus,
) -> UserResearchProjectionV1:
    payload = _mapping(event.payload, label=f"{event.kind} payload")
    resolved_status = _event_status(event, status)
    payload_status = payload.get("status")
    if (
        event.kind == ResearchEventKind.RUN_COMPLETED.value
        and event.status is None
        and payload_status == ResearchRunStatus.PARTIAL.value
    ):
        resolved_status = ResearchRunStatus.PARTIAL
    reason = payload.get("reason") or payload.get("code") or event.kind
    if not isinstance(reason, str) or not reason:
        reason = event.kind
    message = payload.get("message") or payload.get("summary") or ""
    if not isinstance(message, str):
        message = str(message)
    resumable = payload.get("resumable")
    resumable_value = resumable if isinstance(resumable, bool) else False
    termination = TerminationViewV1(
        status=resolved_status,
        reason=reason,
        message=message,
        resumable=resumable_value,
        continuationRef=(
            payload.get("continuationRef")
            if isinstance(payload.get("continuationRef"), str)
            else None
        ),
        completedAt=event.occurred_at,
    )
    return _validated_projection(
        projection,
        status=resolved_status,
        phase=event.phase or projection.phase,
        summary=message or projection.summary,
        metrics=_metrics_from_payload(projection, payload),
        coverage=_coverage_from_payload(projection, payload),
        termination=termination,
    )


def _apply_event_body(
    projection: UserResearchProjectionV1,
    event: ResearchEventV1,
) -> UserResearchProjectionV1:
    kind = event.kind
    if kind == ResearchEventKind.RUN_STARTED.value:
        return _apply_run_started(projection, event)
    if kind == ResearchEventKind.PLAN_UPDATED.value:
        return _apply_plan_update(projection, event)
    if kind in {
        ResearchEventKind.ACTION_STARTED.value,
        ResearchEventKind.ACTION_PROGRESS.value,
        ResearchEventKind.ACTION_COMPLETED.value,
    }:
        return _apply_action_event(projection, event)
    if kind == ResearchEventKind.EVIDENCE_ADDED.value:
        return _apply_entity_event(
            projection,
            event,
            singular="evidence",
            plural="items",
            id_key="evidenceId",
            model_type=EvidenceItemV1,
            collection_name="evidence",
        )
    if kind == ResearchEventKind.CONTROVERSY_UPSERTED.value:
        return _apply_entity_event(
            projection,
            event,
            singular="controversy",
            plural="controversies",
            id_key="controversyId",
            model_type=ControversyViewV1,
            collection_name="controversies",
        )
    if kind == ResearchEventKind.PROFILE_UPSERTED.value:
        return _apply_entity_event(
            projection,
            event,
            singular="profile",
            plural="profiles",
            id_key="profileId",
            model_type=ProfileViewV1,
            collection_name="profiles",
        )
    if kind == ResearchEventKind.RECOMMENDATION_UPSERTED.value:
        return _apply_entity_event(
            projection,
            event,
            singular="recommendation",
            plural="recommendations",
            id_key="recommendationId",
            model_type=RecommendationViewV1,
            collection_name="recommendations",
        )
    if kind == ResearchEventKind.GAP_UPSERTED.value:
        return _apply_entity_event(
            projection,
            event,
            singular="gap",
            plural="gaps",
            id_key="gapId",
            model_type=GapViewV1,
            collection_name="gaps",
        )
    if kind == ResearchEventKind.RUN_PROGRESS.value:
        return _apply_progress(projection, event)
    if kind == ResearchEventKind.RUN_COMPLETED.value:
        status = ResearchRunStatus.PARTIAL if event.status is ResearchRunStatus.PARTIAL else ResearchRunStatus.SUCCEEDED
        return _apply_terminal(projection, event, status)
    if kind == ResearchEventKind.RUN_FAILED.value:
        return _apply_terminal(projection, event, ResearchRunStatus.FAILED)
    if kind == ResearchEventKind.RUN_CANCELLED.value:
        return _apply_terminal(projection, event, ResearchRunStatus.CANCELLED)
    # A namespaced extension is valid v1.  It advances the public cursor but
    # has no generic meaning; domain-aware reducers can layer on top later.
    if kind not in CORE_RESEARCH_EVENT_KINDS:
        return projection
    raise ProjectionError(f"unsupported core event kind: {kind}")


class ResearchProjectionReducer:
    """Apply public events with strict identity, ordering, and idempotency."""

    def initial(
        self,
        session_id: str,
        task_id: str,
        turn_id: int,
        *,
        run_id: str | None = None,
    ) -> UserResearchProjectionV1:
        return initial_research_projection(session_id, task_id, turn_id, run_id=run_id)

    def apply(
        self,
        projection: UserResearchProjectionV1,
        event: ResearchEventV1,
    ) -> UserResearchProjectionV1:
        _check_identity(projection, event)
        duplicate = _check_sequence(projection, event)
        if duplicate:
            return projection
        if _terminal(projection):
            raise ProjectionTerminalError(
                f"terminal projection cannot apply event {event.event_id!r}"
            )
        reduced = _apply_event_body(projection, event)
        return _with_event_cursor(reduced, event)

    def reduce(
        self,
        projection: UserResearchProjectionV1,
        events: Sequence[ResearchEventV1],
    ) -> UserResearchProjectionV1:
        current = projection
        for event in events:
            current = self.apply(current, event)
        return current

    def replace_snapshot(
        self,
        current: UserResearchProjectionV1,
        snapshot: UserResearchProjectionV1,
    ) -> UserResearchProjectionV1:
        """Replace local state after replay expiry or an explicit resync."""

        if (
            current.session_id != snapshot.session_id
            or current.task_id != snapshot.task_id
            or current.turn_id != snapshot.turn_id
        ):
            raise ProjectionIdentityError("snapshot identity does not match projection")
        if current.run_id is not None and snapshot.run_id is not None and current.run_id != snapshot.run_id:
            raise ProjectionIdentityError("snapshot run_id does not match projection")
        return snapshot

    __call__ = apply


def reduce_research_projection(
    projection: UserResearchProjectionV1,
    event: ResearchEventV1,
) -> UserResearchProjectionV1:
    """Functional convenience wrapper for one public event."""

    return ResearchProjectionReducer().apply(projection, event)


def reduce_research_projections(
    projection: UserResearchProjectionV1,
    events: Sequence[ResearchEventV1],
) -> UserResearchProjectionV1:
    """Functional convenience wrapper for an ordered public event list."""

    return ResearchProjectionReducer().reduce(projection, events)


__all__ = [
    "ProjectionError",
    "ProjectionIdentityError",
    "ProjectionResyncRequired",
    "ProjectionTerminalError",
    "ResearchProjectionReducer",
    "initial_research_projection",
    "reduce_research_projection",
    "reduce_research_projections",
]
