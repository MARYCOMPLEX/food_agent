"""B2 disable and pointer rollback rehearsal gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from xhs_food.contracts import (
    BGE_M3_PROFILE_V1,
    QueryReuseReadMode,
    QueryReuseReadSettings,
    QueryReuseRequest,
)
from xhs_food.evidence import QueryFamilyReuseService, QueryReuseReadService

RUNBOOK = (
    Path(__file__).parents[1]
    / "openspec"
    / "changes"
    / "define-modular-architecture"
    / "runbooks"
    / "b2-query-family-rollback.md"
)


class _Repository:
    async def get_exact(self, canonical_key: str):
        raise AssertionError(f"reuse must be disabled: {canonical_key}")

    async def search_trigram(self, alias_text: str, *, limit: int = 5):
        raise AssertionError((alias_text, limit))

    async def search_vector(self, vector, profile, *, limit: int = 5):
        raise AssertionError((vector, profile, limit))


def _request() -> QueryReuseRequest:
    return QueryReuseRequest(
        canonical_key="query.zigong.restaurant",
        alias_text="自贡本地美食",
        vector=(0.0,) * BGE_M3_PROFILE_V1.dimensions,
    )


@pytest.mark.unit
async def test_rollback_mode_serves_legacy_and_never_calls_reuse() -> None:
    calls = 0

    async def legacy():
        nonlocal calls
        calls += 1
        return {"source": "legacy", "items": []}

    outcome = await QueryReuseReadService(
        QueryFamilyReuseService(_Repository()),
        settings=QueryReuseReadSettings(mode=QueryReuseReadMode.OFF, sample_rate=0.0),
    ).read(_request(), legacy, request_key="rollback-task")

    assert calls == 1
    assert outcome.served_candidate is False
    assert outcome.served_result == {"source": "legacy", "items": []}
    assert outcome.shadow.status is not None and outcome.shadow.status.value == "skipped"


@pytest.mark.unit
def test_rollback_runbook_keeps_immutable_data_and_requires_conditional_restore() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    assert "retaining every immutable Bundle" in text
    assert "expected_bundle_version=CURRENT_BUNDLE_VERSION" in text
    assert "unconditional update" in text
    assert "B2CanaryApproval" in text
    assert "Redis" in text
    assert "no explicit refresh route" in text
