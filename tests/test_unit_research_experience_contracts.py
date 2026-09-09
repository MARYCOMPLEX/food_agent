"""Contract and reducer tests for the public ResearchEvent v1 boundary."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from xhs_food.contracts.research_experience import (
    ResearchEventV1,
    ResearchRunStatus,
    UserResearchProjectionV1,
)
from xhs_food.experience.research_projection import (
    ProjectionIdentityError,
    ProjectionResyncRequired,
    ProjectionTerminalError,
    ResearchProjectionReducer,
)

NOW = datetime(2026, 9, 9, 3, 30, tzinfo=UTC)
FIXTURES = (
    Path(__file__).parents[1]
    / "openspec"
    / "changes"
    / "freeze-research-experience-contracts"
    / "fixtures"
)


def _event(
    sequence: int,
    kind: str,
    payload: dict[str, object] | None = None,
    *,
    event_id: str | None = None,
    status: ResearchRunStatus | str | None = None,
    mutation: str = "append",
) -> ResearchEventV1:
    return ResearchEventV1(
        event_id=event_id or f"event-{sequence}",
        session_id="session-1",
        task_id="task-1",
        turn_id=1,
        run_id="run-1",
        sequence=sequence,
        occurred_at=NOW + timedelta(seconds=sequence),
        kind=kind,
        status=status,
        mutation=mutation,
        payload=payload or {},
    )


def test_event_wire_round_trip_is_versioned_and_camel_case() -> None:
    event = _event(
        1,
        "evidence_added",
        {
            "items": [
                {
                    "evidenceId": "evidence-1",
                    "source": "xhs",
                    "noteRef": "note-1",
                    "commentRef": "comment-1",
                    "excerpt": "汤底鲜，但高峰期排队。",
                    "stance": "mixed",
                }
            ]
        },
    )

    wire = event.to_wire()
    assert wire["schemaVersion"] == "research-event/v1"
    assert wire["eventId"] == "event-1"
    assert wire["payload"]["items"][0]["commentRef"] == "comment-1"
    assert ResearchEventV1.model_validate(wire) == event


@pytest.mark.parametrize(
    "payload",
    [
        {"rawProviderResponse": {"body": "private"}},
        {"plannerPrompt": "private"},
        {"headers": {"Authorization": "Bearer private"}},
        {"mcpArguments": {"query": "private"}},
        {"accessToken": "private"},
        {"excerpt": "x" * 4_097},
    ],
)
def test_public_event_rejects_private_or_unbounded_payload(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _event(1, "run_progress", payload)


def test_terminal_event_status_combinations_are_contract_checked() -> None:
    with pytest.raises(ValidationError, match="run_failed status"):
        _event(1, "run_failed", status="partial")


def test_reducer_preserves_comment_evidence_when_profile_enrichment_is_partial() -> None:
    reducer = ResearchProjectionReducer()
    projection = reducer.initial("session-1", "task-1", 1, run_id="run-1")
    projection = reducer.reduce(
        projection,
        (
            _event(1, "run_started", {"intent": {"objective": "找真正好吃的店"}}),
            _event(
                2,
                "evidence_added",
                {
                    "items": [
                        {
                            "evidenceId": "evidence-1",
                            "source": "xhs",
                            "noteRef": "note-1",
                            "commentRef": "comment-1",
                            "excerpt": "本地人说鱼香味很足。",
                            "stance": "positive",
                        }
                    ]
                },
            ),
            _event(
                3,
                "controversy_upserted",
                {
                    "controversyId": "controversy-1",
                    "topic": "高峰期排队",
                    "summary": "评论对等待时间评价不一致",
                    "status": "unresolved",
                    "sides": [],
                    "evidenceRefs": ["evidence-1"],
                },
            ),
            _event(
                4,
                "profile_upserted",
                {
                    "profileId": "profile-1",
                    "name": "老店",
                    "status": "partial",
                    "address": "人民路 1 号",
                },
            ),
            _event(
                5,
                "gap_upserted",
                {
                    "gapId": "gap-1",
                    "source": "dianping",
                    "operation": "places.detail",
                    "code": "verification_required",
                    "message": "需要人工验证，店铺补充信息暂不可用",
                    "retryable": True,
                    "severity": "warning",
                    "affectedRefs": [
                        {"entityType": "profile", "entityId": "profile-1"}
                    ],
                },
            ),
            _event(6, "run_completed", {"status": "partial", "message": "评论证据已完成"}),
        ),
    )

    assert projection.status is ResearchRunStatus.PARTIAL
    assert projection.termination is not None
    assert projection.termination.status is ResearchRunStatus.PARTIAL
    assert projection.evidence[0].comment_ref == "comment-1"
    assert projection.controversies[0].status.value == "unresolved"
    assert projection.profiles[0].address == "人民路 1 号"
    assert projection.gaps[0].code == "verification_required"
    assert projection.metrics.comment_evidence_items == 1
    assert projection.metrics.gaps == 1


def test_sparse_profile_upsert_does_not_erase_existing_fields() -> None:
    reducer = ResearchProjectionReducer()
    projection = reducer.initial("session-1", "task-1", 1, run_id="run-1")
    projection = reducer.apply(
        projection,
        _event(
            1,
            "profile_upserted",
            {
                "profileId": "profile-1",
                "name": "店铺",
                "address": "旧街 8 号",
                "status": "partial",
            },
        ),
    )
    projection = reducer.apply(
        projection,
        _event(
            2,
            "profile_upserted",
            {
                "profileId": "profile-1",
                "images": ["https://example.test/shop.jpg"],
                "recommendedDishes": ["招牌鱼"],
            },
            mutation="patch",
        ),
    )

    profile = projection.profiles[0]
    assert profile.address == "旧街 8 号"
    assert profile.images == ("https://example.test/shop.jpg",)
    assert profile.recommended_dishes == ("招牌鱼",)


def test_evidence_is_append_only_even_when_the_same_identity_is_replayed() -> None:
    reducer = ResearchProjectionReducer()
    projection = reducer.initial("session-1", "task-1", 1, run_id="run-1")
    projection = reducer.apply(
        projection,
        _event(
            1,
            "evidence_added",
            {"items": [{"evidenceId": "ev-1", "source": "xhs", "excerpt": "first"}]},
        ),
    )
    projection = reducer.apply(
        projection,
        _event(
            2,
            "evidence_added",
            {"items": [{"evidenceId": "ev-1", "source": "xhs", "excerpt": "late duplicate"}]},
        ),
    )
    assert len(projection.evidence) == 1
    assert projection.evidence[0].excerpt == "first"


def test_gap_marks_an_affected_pending_profile_partial_without_touching_evidence() -> None:
    reducer = ResearchProjectionReducer()
    projection = reducer.initial("session-1", "task-1", 1, run_id="run-1")
    projection = reducer.apply(
        projection,
        _event(1, "profile_upserted", {"profileId": "p-1", "name": "Shop"}),
    )
    projection = reducer.apply(
        projection,
        _event(
            2,
            "gap_upserted",
            {
                "gapId": "gap-1",
                "source": "dianping",
                "operation": "places.detail",
                "code": "verification_required",
                "message": "Interactive verification is required.",
                "affectedRefs": [{"entityType": "profile", "entityId": "p-1"}],
            },
        ),
    )

    assert projection.profiles[0].status.value == "partial"
    assert projection.profiles[0].gap_refs == ("gap-1",)


def test_duplicate_is_noop_and_missing_sequence_requires_snapshot() -> None:
    reducer = ResearchProjectionReducer()
    projection = reducer.initial("session-1", "task-1", 1, run_id="run-1")
    first = _event(1, "run_started", event_id="stable-event")
    projection = reducer.apply(projection, first)
    assert reducer.apply(projection, first) == projection

    with pytest.raises(ProjectionResyncRequired, match="sequence_gap"):
        reducer.apply(projection, _event(3, "run_progress"))


def test_identity_and_terminal_guards_are_explicit() -> None:
    reducer = ResearchProjectionReducer()
    projection = reducer.initial("session-1", "task-1", 1, run_id="run-1")
    with pytest.raises(ProjectionIdentityError):
        reducer.apply(
            projection,
            ResearchEventV1(
                event_id="foreign",
                session_id="other-session",
                task_id="task-1",
                turn_id=1,
                run_id="run-1",
                sequence=1,
                occurred_at=NOW,
                kind="run_started",
                payload={},
            ),
        )

    projection = reducer.apply(projection, _event(1, "run_started"))
    projection = reducer.apply(
        projection,
        _event(2, "run_completed", {"message": "完成"}),
    )
    with pytest.raises(ProjectionTerminalError):
        reducer.apply(projection, _event(3, "evidence_added", {"items": []}))


def test_namespaced_extension_advances_cursor_and_snapshot_replacement_keeps_identity() -> None:
    reducer = ResearchProjectionReducer()
    projection = reducer.initial("session-1", "task-1", 1, run_id="run-1")
    projection = reducer.apply(
        projection,
        _event(1, "x.food.controversy_classifier_updated", {"label": "queue"}),
    )
    assert projection.last_sequence == 1
    assert projection.revision == 1

    snapshot = UserResearchProjectionV1.model_validate(projection.to_wire())
    assert reducer.replace_snapshot(projection, snapshot) == snapshot


def test_authority_fixtures_replay_to_the_published_partial_snapshot() -> None:
    events = tuple(
        ResearchEventV1.model_validate(item)
        for item in json.loads((FIXTURES / "partial-research-events-v1.json").read_text())
    )
    expected = UserResearchProjectionV1.model_validate_json(
        (FIXTURES / "partial-research-projection-v1.json").read_text()
    )
    reducer = ResearchProjectionReducer()
    actual = reducer.reduce(
        reducer.initial("session-1", "task-1", 1, run_id="run-1"),
        events,
    )

    assert actual.status is expected.status
    assert actual.last_sequence == expected.last_sequence
    assert actual.evidence == expected.evidence
    assert actual.controversies == expected.controversies
    assert actual.profiles == expected.profiles
    assert actual.gaps == expected.gaps
