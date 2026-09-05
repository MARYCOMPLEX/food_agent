"""B1 Source Gateway decoration and lifecycle contracts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from xhs_food.composition import ModularAdapterOverrides, build_composition_root
from xhs_food.contracts import CanonicalQuery, CanonicalSourceBatch, CollectRequest, SourceLocator
from xhs_food.evidence import (
    EvidenceShadowGate,
    EvidenceShadowPolicy,
    EvidenceShadowSettings,
    ShadowWriteRecord,
    build_shadow_connector_factory,
)
from xhs_food.foundation import TargetSettings
from xhs_food.gateways import SourceGateway

NOW = datetime(2026, 8, 24, tzinfo=UTC)


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


def _batch() -> CanonicalSourceBatch:
    return CanonicalSourceBatch(
        isolation={"tenant_scope": "public", "language": "en", "region": "US"},
        source_id="fixture",
        connector_id="fixture.connector",
        connector_version="fixture/v1",
        normalizer_version="fixture-normalizer/v1",
        documents=(
            {
                "source_id": "fixture",
                "external_id": "doc-1",
                "canonical_url": "https://source.invalid/doc-1",
                "captured_at": NOW,
                "title": "Fixture",
                "text": "Public claim",
            },
        ),
        watermark="opaque:1",
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


class _Connector:
    source_id = "fixture"

    def __init__(self, batch: Any | None = None) -> None:
        self.batch = _batch() if batch is None else batch
        self.requests: list[CollectRequest] = []
        self.closed = False

    async def search(self, request: CollectRequest) -> Any:
        self.requests.append(request)
        return self.batch

    async def fetch_document(self, ref: SourceLocator) -> Any:
        del ref
        raise AssertionError("not part of the Source Gateway contract")

    async def fetch_comments(
        self, document_ref: SourceLocator, cursor: str | None = None
    ) -> Any:
        del document_ref, cursor
        raise AssertionError("not part of the Source Gateway contract")

    async def list_media_refs(self, owner_ref: SourceLocator) -> tuple[Any, ...]:
        del owner_ref
        return ()

    async def aclose(self) -> None:
        self.closed = True


class _Sink:
    supports_atomic_canonical_query = True

    def __init__(self) -> None:
        self.records: list[ShadowWriteRecord] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.legacy_returned = False

    async def write(self, record: ShadowWriteRecord) -> None:
        assert self.legacy_returned
        self.started.set()
        await self.release.wait()
        self.records.append(record)


@pytest.mark.unit
async def test_source_gateway_decorates_at_registration_and_serves_legacy_first() -> None:
    connector = _Connector()
    sink = _Sink()
    decorated: list[object] = []
    factory = build_shadow_connector_factory(
        policy=_policy(),
        sink=sink,
        gate=EvidenceShadowGate(
            EvidenceShadowSettings(enabled=True, sample_rate=1.0, write_budget=10)
        ),
    )

    def decorate(value: object) -> object:
        decorated.append(value)
        return factory(value)  # type: ignore[arg-type]

    gateway = SourceGateway({"fixture": connector}, connector_decorator=decorate)  # type: ignore[arg-type]
    outcome = (await gateway.collect(_request()))[0]
    sink.legacy_returned = True

    assert decorated == [connector]
    assert outcome.outcome == "success_nonempty"
    assert outcome.batch == _batch()
    await asyncio.wait_for(sink.started.wait(), timeout=1)

    sink.release.set()
    await gateway.aclose()
    assert len(sink.records) == 1
    assert connector.closed is True


@pytest.mark.unit
async def test_source_gateway_without_decorator_preserves_off_connector_identity() -> None:
    connector = _Connector()

    # The gateway itself is default-off: callers select decoration explicitly
    # rather than having a sink or ambient setting alter registration.
    gateway = SourceGateway({"fixture": connector})  # type: ignore[arg-type]
    outcome = (await gateway.collect(_request()))[0]

    assert outcome.batch == _batch()
    await gateway.aclose()
    assert connector.closed is True


@pytest.mark.unit
async def test_composition_root_applies_b1_decorator_and_drains_gateway() -> None:
    connector = _Connector()
    sink = _Sink()
    factory = build_shadow_connector_factory(
        policy=_policy(),
        sink=sink,
        gate=EvidenceShadowGate(
            EvidenceShadowSettings(enabled=True, sample_rate=1.0, write_budget=10)
        ),
    )
    settings = TargetSettings(
        _env_file=None,
        target_adapters_enabled=True,
        evidence_shadow_enabled=True,
        evidence_shadow_sample_rate=1.0,
        evidence_shadow_write_budget=10,
    )
    root = build_composition_root(
        target_settings=settings,
        modular_overrides=ModularAdapterOverrides(
            evidence_shadow_sink=sink,
            source_connectors={"fixture": connector},
            source_connector_decorator=factory,
        ),
    )
    try:
        gateway = await root.resolve_logical("source.gateway")
        assert isinstance(gateway, SourceGateway)
        outcome = (await gateway.collect(_request()))[0]
        sink.legacy_returned = True
        assert outcome.batch == _batch()
        await asyncio.wait_for(sink.started.wait(), timeout=1)
        sink.release.set()
    finally:
        await root.close()

    assert len(sink.records) == 1
    assert connector.closed is True


@pytest.mark.unit
async def test_composition_root_off_mode_ignores_injected_decorator() -> None:
    connector = _Connector()
    calls = 0

    def unexpected_decorator(value: object) -> object:
        del value
        nonlocal calls
        calls += 1
        raise AssertionError("off mode must keep the legacy connector")

    root = build_composition_root(
        target_settings=TargetSettings(_env_file=None),
        modular_overrides=ModularAdapterOverrides(
            source_connectors={"fixture": connector},
            source_connector_decorator=unexpected_decorator,
        ),
    )
    assert calls == 0
    try:
        gateway = await root.resolve_logical("source.gateway")
        assert isinstance(gateway, SourceGateway)
        outcome = (await gateway.collect(_request()))[0]
        assert outcome.batch == _batch()
    finally:
        await root.close()
    assert calls == 0
    assert connector.closed is True


@pytest.mark.unit
def test_composition_root_validates_b1_sink_before_invoking_connector_decorator() -> None:
    calls = 0

    def unexpected_decorator(value: object) -> object:
        del value
        nonlocal calls
        calls += 1
        raise AssertionError("invalid B1 configuration must fail before decoration")

    settings = TargetSettings(
        _env_file=None,
        target_adapters_enabled=True,
        evidence_shadow_enabled=True,
        evidence_shadow_sample_rate=1.0,
        evidence_shadow_write_budget=1,
    )
    with pytest.raises(RuntimeError, match="evidence_shadow_sink"):
        build_composition_root(
            target_settings=settings,
            modular_overrides=ModularAdapterOverrides(
                source_connectors={"fixture": _Connector()},
                source_connector_decorator=unexpected_decorator,
            ),
        )
    assert calls == 0
