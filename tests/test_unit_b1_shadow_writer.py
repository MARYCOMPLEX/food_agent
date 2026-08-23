"""Offline shadow decorator tests for source adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from xhs_food.contracts import (
    CanonicalQuery,
    CanonicalSourceBatch,
    CollectRequest,
    EvidenceStatus,
    SourceLocator,
)
from xhs_food.evidence import (
    EvidenceShadowGate,
    EvidenceShadowPolicy,
    EvidenceShadowSettings,
    ShadowSourceConnector,
    ShadowWriteRecord,
    build_shadow_record,
)
from xhs_food.foundation import (
    EvidenceShadowTelemetry,
    correlation_attributes,
    prometheus_labels,
    redact_log_context,
)

NOW = datetime(2026, 8, 24, tzinfo=UTC)


def _request() -> CollectRequest:
    query = CanonicalQuery.model_validate(
        {
            "schema_version": "canonical-query/v1",
            "normalizer_version": "canonical-normalizer/v1",
            "classifier_version": "food-constraint-classifier/v1",
            "isolation": {"tenant_scope": "public", "language": "en", "region": "US"},
            "query": {
                "domain": "food",
                "geo": {"country_code": "US", "admin_path": ["us.ca"], "locality": "us.ca.sf"},
                "intent": {"kind": "recommend", "subject": "restaurant"},
                "audience": ["visitor"],
                "constraints": [],
                "time_range": {"kind": "current", "start": None, "end": None, "timezone": "Etc/UTC"},
                "freshness_policy": {"policy_id": "food.default", "policy_version": "food-freshness/v1"},
            },
        }
    )
    return CollectRequest(query=query, source_scope=("fixture",), depth="standard")


def _batch() -> CanonicalSourceBatch:
    return CanonicalSourceBatch(
        isolation={"tenant_scope": "public", "language": "en", "region": "US"},
        source_id="fixture",
        connector_id="fixture.connector",
        connector_version="fixture-connector/v1",
        normalizer_version="fixture-normalizer/v1",
        documents=(
            {
                "source_id": "fixture",
                "external_id": "note-1",
                "canonical_url": "https://source.invalid/note/1",
                "captured_at": NOW,
                "title": "Fixture restaurant",
                "text": "A public source claim",
            },
        ),
        watermark="opaque:42",
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
        retention={"retention_class": "evidence_default", "duration_seconds": None, "legal_hold": False},
        visibility={"scope": "public", "tenant_scope": "public", "entitlement_ids": []},
    )


@pytest.mark.unit
async def test_shadow_source_connector_preserves_batch_and_writes_only_when_sink_bound() -> None:
    class Connector:
        source_id = "fixture"

        async def search(self, request: CollectRequest) -> CanonicalSourceBatch:
            del request
            return _batch()

        async def fetch_document(self, ref: SourceLocator) -> Any:
            del ref
            raise AssertionError

        async def fetch_comments(self, document_ref: SourceLocator, cursor: str | None = None) -> Any:
            del document_ref, cursor
            raise AssertionError

        async def list_media_refs(self, owner_ref: SourceLocator) -> tuple[Any, ...]:
            del owner_ref
            return ()

    class Sink:
        def __init__(self) -> None:
            self.records: list[ShadowWriteRecord] = []

        async def write(self, record: ShadowWriteRecord) -> None:
            self.records.append(record)

    batch = _batch()
    disabled = ShadowSourceConnector(Connector(), policy=_policy())
    assert await disabled.search(_request()) == batch

    sink = Sink()
    enabled = ShadowSourceConnector(Connector(), policy=_policy(), sink=sink)
    assert await enabled.search(_request()) == batch
    assert len(sink.records) == 1
    record = sink.records[0]
    assert record.batch == batch
    assert record.locators[0].watermark == "opaque:42"
    assert record.evidence_items[0].status is EvidenceStatus.CANDIDATE
    assert record.evidence_items[0].source_locator_id == record.locators[0].locator_id


@pytest.mark.unit
def test_shadow_gate_is_disabled_by_default_and_budgeted_deterministically() -> None:
    assert EvidenceShadowGate().allow("family", 1) is False
    gate = EvidenceShadowGate(EvidenceShadowSettings(enabled=True, sample_rate=1.0, write_budget=1))
    assert gate.allow("family", 1) is True
    assert gate.allow("family", 1) is False
    with pytest.raises(ValueError, match="sample_rate"):
        EvidenceShadowSettings(enabled=True, sample_rate=2.0)


@pytest.mark.unit
def test_shadow_telemetry_redacts_ids_and_keeps_profile_version() -> None:
    attributes = correlation_attributes(
        {
            "task_id": "task-private",
            "family_id": "family-private",
            "bundle_version": 2,
            "profile_version": "profile_v1",
        }
    )
    assert attributes["task_id"].startswith("sha256:")
    assert attributes["family_id"].startswith("sha256:")
    assert attributes["bundle_version"] == 2
    assert attributes["profile_version"] == "profile_v1"
    telemetry = EvidenceShadowTelemetry(enabled=False)
    with telemetry.span(
        task_id="task-private",
        family_id="family-private",
        bundle_version=2,
        profile_version="profile_v1",
    ) as span:
        assert span is None
    telemetry.record(connector="xhs", outcome="success")


@pytest.mark.unit
def test_public_shadow_rejects_private_information_before_sink_write() -> None:
    document = _batch().documents[0].model_copy(
        update={"attributes": {"user_id": "user-private", "favorite": True}}
    )
    batch = _batch().model_copy(update={"documents": (document,)})

    with pytest.raises(ValueError, match="private fields"):
        build_shadow_record(batch, _policy())


@pytest.mark.unit
def test_observability_redacts_log_context_and_rejects_unbounded_metric_values() -> None:
    context = redact_log_context(
        {
            "task_id": "task-private",
            "family_id": "family-private",
            "query": "do not log this",
            "session_id": "session-private",
            "preference": "do not log this",
            "operation": "write",
            "outcome": "success",
            "connector": "xhs",
            "bundle_version": 2,
            "profile_version": "profile_v1",
            "exception": "private traceback",
        }
    )
    assert context["task_id"].startswith("sha256:")
    assert context["family_id"].startswith("sha256:")
    assert "session_id" not in context
    assert "query" not in context
    assert "preference" not in context
    assert "exception" not in context
    assert context["bundle_version"] == 2
    assert prometheus_labels(
        {"operation": "write", "outcome": "success", "connector": "xhs"}
    ) == {"operation": "write", "outcome": "success", "connector": "xhs"}
    with pytest.raises(ValueError, match="unregistered"):
        prometheus_labels({"connector": "user-controlled"})


@pytest.mark.unit
async def test_shadow_sink_failure_isolated_from_legacy_connector_result() -> None:
    class Connector:
        source_id = "fixture"

        async def search(self, request: CollectRequest) -> CanonicalSourceBatch:
            del request
            return _batch()

        async def fetch_document(self, ref: SourceLocator) -> Any:
            del ref
            raise AssertionError

        async def fetch_comments(self, document_ref: SourceLocator, cursor: str | None = None) -> Any:
            del document_ref, cursor
            raise AssertionError

        async def list_media_refs(self, owner_ref: SourceLocator) -> tuple[Any, ...]:
            del owner_ref
            return ()

    class FailingSink:
        async def write(self, record: ShadowWriteRecord) -> None:
            del record
            raise TimeoutError("shadow store timeout")

    connector = ShadowSourceConnector(Connector(), policy=_policy(), sink=FailingSink())
    assert await connector.search(_request()) == _batch()
