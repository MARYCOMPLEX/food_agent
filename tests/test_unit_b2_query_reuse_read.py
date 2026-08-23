"""B2 shadow/canary gates for the public Query Family read path."""

from __future__ import annotations

import pytest

from xhs_food.contracts import (
    BGE_M3_PROFILE_V1,
    QueryFamilyMatch,
    QueryMatchLayer,
    QueryReuseReadMode,
    QueryReuseReadSettings,
    QueryReuseRequest,
    RefreshClaim,
    RefreshSingleFlightKey,
    stable_refresh_claim_key,
    stable_refresh_workflow_id,
)
from xhs_food.evidence import QueryFamilyReuseService, QueryReuseReadService


class _Repository:
    async def get_exact(self, canonical_key: str):
        return QueryFamilyMatch(
            family_id="family.zigong",
            canonical_key=canonical_key,
            layer=QueryMatchLayer.DETERMINISTIC,
            confidence=1.0,
            rule_version="canonical-normalizer/v1",
        )

    async def search_trigram(self, alias_text: str, *, limit: int = 5):
        del alias_text, limit
        return ()

    async def search_vector(self, vector, profile, *, limit: int = 5):
        del vector, profile, limit
        return ()

    async def get_freshness(self, family_id: str):
        del family_id
        return None

    async def save_freshness(self, state):
        del state

    async def claim_refresh(self, key: RefreshSingleFlightKey):
        return RefreshClaim(
            claim_key=stable_refresh_claim_key(key),
            workflow_id=stable_refresh_workflow_id(key),
            acquired=True,
        )

    async def activate_bundle_if_current(self, family_id, expected_bundle_version, bundle_id, bundle_version):
        del family_id, expected_bundle_version, bundle_id, bundle_version
        return True


def _request() -> QueryReuseRequest:
    return QueryReuseRequest(
        canonical_key="query.zigong.restaurant",
        alias_text="自贡本地美食",
        vector=(0.0,) * BGE_M3_PROFILE_V1.dimensions,
    )


@pytest.mark.unit
async def test_off_mode_does_not_call_query_reuse_and_keeps_legacy_value() -> None:
    calls = 0

    async def legacy():
        return {"source": "legacy", "items": []}

    service = QueryReuseReadService(
        QueryFamilyReuseService(_Repository()),
        settings=QueryReuseReadSettings(),
    )
    outcome = await service.read(_request(), legacy, request_key="task-1")

    assert outcome.shadow.status.value == "skipped"
    assert outcome.served_candidate is False
    assert outcome.legacy_result == {"source": "legacy", "items": []}
    assert outcome.served_result == outcome.legacy_result
    assert calls == 0


@pytest.mark.unit
async def test_shadow_mode_compares_candidate_but_serves_legacy() -> None:
    async def legacy():
        return {"source": "legacy", "items": []}

    service = QueryReuseReadService(
        QueryFamilyReuseService(_Repository()),
        settings=QueryReuseReadSettings(mode=QueryReuseReadMode.SHADOW, sample_rate=1.0),
    )
    outcome = await service.read(_request(), legacy, request_key="task-shadow")

    assert outcome.candidate is not None
    assert outcome.shadow.status.value == "mismatch"
    assert outcome.served_candidate is False
    assert outcome.shadow.served_candidate is False
    assert outcome.served_result == outcome.legacy_result


@pytest.mark.unit
async def test_canary_mode_is_deterministic_and_only_changes_sampled_reads() -> None:
    async def legacy():
        return {"source": "legacy", "items": []}

    service = QueryReuseReadService(
        QueryFamilyReuseService(_Repository()),
        settings=QueryReuseReadSettings(mode=QueryReuseReadMode.CANARY, sample_rate=1.0),
    )
    first = await service.read(_request(), legacy, request_key="task-canary")
    second = await service.read(_request(), legacy, request_key="task-canary")

    assert first.served_candidate is True
    assert first.served_result == first.candidate.model_dump(mode="json")  # type: ignore[union-attr]
    assert first.shadow.request_key_hash == second.shadow.request_key_hash
    assert first.candidate == second.candidate


@pytest.mark.unit
def test_query_reuse_read_settings_reject_personalization_and_scheduler_binding() -> None:
    with pytest.raises(ValueError):
        QueryReuseReadSettings(personalization_enabled=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        QueryReuseReadSettings(background_refresh_enabled=True)  # type: ignore[arg-type]
