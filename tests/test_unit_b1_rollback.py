"""B1 independent disable/rollback rehearsal gates."""

from __future__ import annotations

from pathlib import Path

import pytest

from xhs_food.contracts import CanonicalQuery, CanonicalSourceBatch, CollectRequest, SourceLocator
from xhs_food.evidence import (
    EvidenceShadowGate,
    EvidenceShadowPolicy,
    EvidenceShadowSettings,
    ShadowSourceConnector,
)
from xhs_food.foundation import EvidenceShadowConfigView, TargetSettings

RUNBOOK = (
    Path(__file__).parents[1]
    / "openspec"
    / "changes"
    / "define-modular-architecture"
    / "runbooks"
    / "b1-evidence-shadow-rollback.md"
)


def _policy() -> EvidenceShadowPolicy:
    return EvidenceShadowPolicy(
        evidence_type="restaurant",
        claim_type="restaurant_name",
        confidence=0.9,
        extractor_version="source-extractor/v1",
        schema_version="food-evidence/v1",
        license={
            "license_id": "source-internal-reuse",
            "status": "known",
            "allowed_use": "internal_reuse",
            "attribution_required": True,
            "expires_at": None,
            "policy_version": "evidence-license/v1",
        },
        retention={
            "retention_class": "evidence_default",
            "duration_seconds": None,
            "legal_hold": False,
        },
        visibility={"scope": "public", "tenant_scope": "public", "entitlement_ids": []},
    )


def _batch() -> CanonicalSourceBatch:
    return CanonicalSourceBatch(
        isolation={"tenant_scope": "public", "language": "en", "region": "US"},
        source_id="fixture",
        connector_id="fixture.connector",
        connector_version="fixture/v1",
        normalizer_version="fixture/v1",
        documents=(
            {
                "source_id": "fixture",
                "external_id": "note-1",
                "canonical_url": "https://source.invalid/note/1",
                "captured_at": "2026-08-24T00:00:00Z",
                "title": "Fixture",
            },
        ),
        watermark=None,
    )


def _request() -> CollectRequest:
    return CollectRequest(
        query=CanonicalQuery.model_validate(
            {
                "schema_version": "canonical-query/v1",
                "normalizer_version": "canonical-normalizer/v1",
                "classifier_version": "food-constraint-classifier/v1",
                "isolation": {"tenant_scope": "public", "language": "en", "region": "US"},
                "query": {
                    "domain": "food",
                    "geo": {"country_code": "US", "admin_path": [], "locality": "us.ca.sf"},
                    "intent": {"kind": "recommend", "subject": "restaurant"},
                    "audience": [],
                    "constraints": [],
                    "time_range": {
                        "kind": "current",
                        "start": None,
                        "end": None,
                        "timezone": "Etc/UTC",
                    },
                    "freshness_policy": {
                        "policy_id": "food.default",
                        "policy_version": "food-freshness/v1",
                    },
                },
            }
        ),
        source_scope=("fixture",),
        depth="standard",
    )


@pytest.mark.unit
def test_rollback_runbook_keeps_additive_schema_and_legacy_binding() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "MODULAR_EVIDENCE_SHADOW_ENABLED=false" in text
    assert "not delete the B1 tables" in text
    assert "HTTP/SSE" in text
    assert "current pointer" in text


@pytest.mark.unit
def test_shadow_settings_are_closed_world_defaults_after_disable() -> None:
    settings = TargetSettings(_env_file=None)
    assert settings.evidence_shadow_enabled is False
    assert settings.evidence_shadow_sample_rate == 0.0
    assert settings.evidence_shadow_write_budget == 0
    view = EvidenceShadowConfigView(
        enabled=settings.evidence_shadow_enabled,
        sample_rate=settings.evidence_shadow_sample_rate,
        write_budget=settings.evidence_shadow_write_budget,
    )
    assert view.enabled is False


@pytest.mark.unit
async def test_disabled_decorator_returns_legacy_batch_without_sink_activity() -> None:
    class Connector:
        source_id = "fixture"

        async def search(self, request: CollectRequest) -> CanonicalSourceBatch:
            del request
            return _batch()

        async def fetch_document(self, ref: SourceLocator) -> object:
            del ref
            raise AssertionError

        async def fetch_comments(self, document_ref: SourceLocator, cursor: str | None = None) -> object:
            del document_ref, cursor
            raise AssertionError

        async def list_media_refs(self, owner_ref: SourceLocator) -> tuple[object, ...]:
            del owner_ref
            return ()

    class Sink:
        def __init__(self) -> None:
            self.calls = 0

        async def write(self, record: object) -> None:
            del record
            self.calls += 1

    sink = Sink()
    connector = ShadowSourceConnector(
        Connector(),
        policy=_policy(),
        sink=sink,
        gate=EvidenceShadowGate(EvidenceShadowSettings()),
    )
    assert await connector.search(_request()) == _batch()
    assert sink.calls == 0
