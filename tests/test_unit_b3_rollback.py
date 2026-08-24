"""B3 personalization disable and Redis warm-up rollback gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from xhs_food.composition.adapters import MemoryOutboxProjector
from xhs_food.contracts import (
    MemoryOutboxEvent,
    PersonalizationCanaryMode,
    PersonalizationCanarySettings,
    PersonalizationPolicy,
    PublicCandidate,
    UserIsolationKey,
)
from xhs_food.personalization import PersonalizationCanary, PersonalizedReranker

RUNBOOK = (
    Path(__file__).parents[1]
    / "openspec"
    / "changes"
    / "define-modular-architecture"
    / "runbooks"
    / "b3-personalization-rollback.md"
)


def _policy() -> PersonalizationPolicy:
    return PersonalizationPolicy(
        policy_id="rollback-policy",
        policy_version="personalization-policy/v1",
        isolation_key=UserIsolationKey(
            tenant_id="tenant-cn-1", user_id="user-rollback-2b4aa1b95c884d64"
        ),
        preference_snapshot_id="snapshot-rollback",
        preference_snapshot_version=1,
        ranking_weights={"locality": 0.3},
    )


def _candidates() -> tuple[PublicCandidate, ...]:
    return (
        PublicCandidate(
            candidate_id="restaurant-popular",
            public_score=0.9,
            public_features={"locality": 0.0},
        ),
        PublicCandidate(
            candidate_id="restaurant-local",
            public_score=0.8,
            public_features={"locality": 1.0},
        ),
    )


@pytest.mark.unit
def test_rollback_disables_canary_and_preserves_authority_contract() -> None:
    service = PersonalizationCanary(
        PersonalizedReranker(),
        settings=PersonalizationCanarySettings(
            mode=PersonalizationCanaryMode.CANARY,
            sample_rate=1.0,
        ),
    )
    before = service.evaluate(_candidates(), _policy(), request_key="rollback-request")
    assert before.observation.served_personalized is True

    receipt = service.rollback()
    assert receipt.personalization_enabled is False
    assert receipt.postgres_authority_retained is True
    assert receipt.redis_projection_warmup_enabled is False
    assert receipt.public_refresh_priority_changed is False
    assert service.settings.mode is PersonalizationCanaryMode.OFF
    assert service.settings.projection_warmup_enabled is False

    after = service.evaluate(_candidates(), _policy(), request_key="rollback-request")
    assert after.personalized_ranking is None
    assert after.observation.served_personalized is False
    assert after.observation.served_candidate_ids == (
        "restaurant-popular",
        "restaurant-local",
    )


@pytest.mark.unit
async def test_disabled_projection_warmup_acknowledges_outbox_without_touching_redis() -> None:
    class Window:
        def __init__(self) -> None:
            self.appended = 0
            self.cleared = 0

        async def append(self, session_id: str, message: dict[str, object], ttl: int) -> None:
            del session_id, message, ttl
            self.appended += 1

        async def clear(self, session_id: str) -> bool:
            del session_id
            self.cleared += 1
            return True

    window = Window()
    projector = MemoryOutboxProjector(window, warmup_enabled=False)  # type: ignore[arg-type]
    event = MemoryOutboxEvent(
        outbox_id="outbox-rollback",
        scope=UserIsolationKey(
            tenant_id="tenant-cn-1",
            user_id="user-rollback-2b4aa1b95c884d64",
            session_id="session-rollback",
        ),
        event_type="memory.session.warm",
        aggregate_id="turn-rollback",
        payload={"message": {"role": "user", "content": "private"}},
        idempotency_key="outbox-rollback",
        available_at="2026-08-24T00:00:00Z",
    )
    assert await projector.project(event) is True
    assert window.appended == 0
    assert projector.warmup_enabled is False


@pytest.mark.unit
def test_rollback_runbook_preserves_postgres_and_stops_projection_warmup() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "MODULAR_PERSONALIZATION_CANARY_MODE=off" in text
    assert "PostgreSQL" in text
    assert "projection warm-up" in text
    assert "public/legacy" in text
