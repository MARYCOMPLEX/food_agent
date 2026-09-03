"""Contract tests for the pure legacy Stable Event Mapper."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from xhs_food.contracts import (
    ContractError,
    ErrorCategory,
    ErrorScope,
    TaskEvent,
)
from xhs_food.experience import EventMappingError, StableEventMapper

NOW = datetime(2026, 8, 20, tzinfo=UTC)


def _event(
    event_type: str,
    *,
    step_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> TaskEvent:
    return TaskEvent(
        event_id="internal-event-42",
        task_id="task-1",
        event_type=event_type,
        occurred_at=NOW,
        step_id=step_id,
        payload=payload or {},
    )


@pytest.mark.parametrize(
    "event_type",
    [
        "progress",
        "intent_parsed",
        "notes_found",
        "analysis_done",
        "restaurant",
        "result",
        "error",
        "done",
    ],
)
def test_legacy_non_step_events_preserve_name_and_payload(event_type: str) -> None:
    payload = {"message": "原样保留", "nested": {"count": 2}}

    mapped = StableEventMapper().map(_event(event_type, payload=payload))

    assert mapped.event == event_type
    assert mapped.data == payload


@pytest.mark.parametrize("event_type", ["step_start", "step_done", "step_error"])
@pytest.mark.parametrize(
    ("alias", "legacy_step"),
    [
        ("step1", "step1"),
        ("intent_parsing", "step1"),
        ("step2", "step2"),
        ("evidence_collection", "step2"),
        ("step3", "step3"),
        ("evidence_analysis", "step3"),
        ("comment_analysis", "step3"),
        ("step4", "step4"),
        ("evidence_validation", "step4"),
        ("cross_validation", "step4"),
        ("step5", "step5"),
        ("entity_enrichment", "step5"),
        ("poi_enrichment", "step5"),
        ("step6", "step6"),
        ("result_generation", "step6"),
    ],
)
def test_approved_step_aliases_map_to_legacy_numeric_steps(
    event_type: str,
    alias: str,
    legacy_step: str,
) -> None:
    mapped = StableEventMapper().map(
        _event(event_type, step_id=alias, payload={"message": "detail"})
    )

    assert mapped.data == {"step": legacy_step, "message": "detail"}


def test_step_snapshot_aliases_are_normalised_without_changing_other_fields() -> None:
    payload = {
        "step": "evidence_validation",
        "message": "交叉验证完成",
        "steps": [
            {"id": "intent_parsing", "label": "解析用户意图", "status": "done"},
            {"id": "evidence_collection", "label": "搜索小红书笔记", "status": "done"},
            {"id": "comment_analysis", "label": "分析评论内容", "status": "done"},
            {"id": "cross_validation", "label": "交叉验证完成", "status": "done"},
            {"id": "poi_enrichment", "label": "补充 POI 信息", "status": "pending"},
            {"id": "result_generation", "label": "生成推荐结果", "status": "pending"},
        ],
        "progress": 66,
    }

    mapped = StableEventMapper().map(_event("step_done", payload=payload))

    assert mapped.data == {
        "step": "step4",
        "message": "交叉验证完成",
        "steps": [
            {"id": "step1", "label": "解析用户意图", "status": "done"},
            {"id": "step2", "label": "搜索小红书笔记", "status": "done"},
            {"id": "step3", "label": "分析评论内容", "status": "done"},
            {"id": "step4", "label": "交叉验证完成", "status": "done"},
            {"id": "step5", "label": "补充 POI 信息", "status": "pending"},
            {"id": "step6", "label": "生成推荐结果", "status": "pending"},
        ],
        "progress": 66,
    }
    assert payload["step"] == "evidence_validation"
    assert payload["steps"][0]["id"] == "intent_parsing"


def test_legacy_characterization_payload_is_byte_shape_equivalent() -> None:
    payload = {
        "step": "step1",
        "message": "解析: 成都火锅",
        "steps": [{"id": "step1", "label": "解析: 成都火锅", "status": "loading"}],
        "progress": 0,
    }

    mapped = StableEventMapper().map(_event("step_start", step_id="step1", payload=payload))

    assert mapped.event == "step_start"
    assert list(mapped.data) == ["step", "message", "steps", "progress"]
    assert mapped.data == payload
    assert json.dumps(mapped.data, ensure_ascii=False) == (
        '{"step": "step1", "message": "解析: 成都火锅", "steps": '
        '[{"id": "step1", "label": "解析: 成都火锅", "status": "loading"}], '
        '"progress": 0}'
    )


def test_internal_event_id_never_becomes_a_wire_cursor_or_payload_field() -> None:
    mapped = StableEventMapper().map(_event("done", payload={"message": "搜索完成"}))

    assert not hasattr(mapped, "id")
    assert not hasattr(mapped, "event_id")
    assert set(mapped.data) == {"message"}


def test_typed_progress_and_error_fields_fill_missing_legacy_payload_fields() -> None:
    progress = TaskEvent(
        event_id="progress-event",
        task_id="task-1",
        event_type="progress",
        occurred_at=NOW,
        progress=0.66,
    )
    error = TaskEvent(
        event_id="error-event",
        task_id="task-1",
        event_type="error",
        occurred_at=NOW,
        error=ContractError(
            code="source_failed",
            category=ErrorCategory.INTERNAL,
            scope=ErrorScope.TASK,
            message="来源失败",
        ),
    )

    assert StableEventMapper().map(progress).data == {"progress": 66}
    assert StableEventMapper().map(error).data == {"error": "来源失败"}


@pytest.mark.parametrize("event_type", ["task_completed", "replay_expired", "STEP_DONE"])
def test_unknown_event_aliases_are_rejected(event_type: str) -> None:
    with pytest.raises(EventMappingError, match="unknown event alias"):
        StableEventMapper().map(_event(event_type))


@pytest.mark.parametrize("unknown_alias", ["step7", "search_platform", ""])
def test_unknown_step_aliases_are_rejected(unknown_alias: str) -> None:
    with pytest.raises(EventMappingError, match="unknown step alias"):
        StableEventMapper().map(_event("step_start", step_id=unknown_alias))


def test_unknown_step_alias_in_snapshot_is_rejected() -> None:
    with pytest.raises(EventMappingError, match="unknown step alias"):
        StableEventMapper().map(
            _event(
                "result",
                payload={"steps": [{"id": "source_specific_step", "status": "pending"}]},
            )
        )


def test_conflicting_step_aliases_are_rejected() -> None:
    with pytest.raises(EventMappingError, match="conflicting step aliases"):
        StableEventMapper().map(
            _event("step_done", step_id="intent_parsing", payload={"step": "step2"})
        )
