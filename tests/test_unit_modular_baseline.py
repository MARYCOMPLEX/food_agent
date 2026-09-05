"""Baseline contracts for target configuration and capability activation."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from xhs_food.composition import build_modular_binding_plan
from xhs_food.composition.adapters import build_owner_config
from xhs_food.config import Settings
from xhs_food.foundation import (
    ObservabilityConfigView,
    QueryReuseReadConfigView,
    TargetSettings,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.unit
def test_new_target_defaults_are_off_and_owner_views_are_bounded() -> None:
    target = TargetSettings(_env_file=None)
    owner = build_owner_config(Settings(_env_file=None), target)

    assert target.evidence_shadow_enabled is False
    assert target.evidence_shadow_sample_rate == 0.0
    assert target.evidence_shadow_write_budget == 0
    assert target.query_reuse_read_mode == "off"
    assert target.query_reuse_read_sample_rate == 0.0
    assert target.personalization_canary_mode == "off"
    assert target.personalization_canary_sample_rate == 0.0
    assert target.otel_enabled is False
    assert target.phoenix_enabled is False
    assert owner.query_reuse_read.mode == "off"
    assert owner.query_reuse_read.sample_rate == 0.0
    assert owner.observability.max_queue_size == 2_048
    assert owner.observability.max_batch_size == 128
    assert owner.observability.export_timeout_ms == 10_000
    assert owner.observability.retry_limit == 2
    assert owner.observability.sampling_rate == 1.0
    assert owner.observability.shutdown_flush_timeout_ms == 5_000


@pytest.mark.parametrize(
    "kwargs",
    (
        {
            "query_reuse_read_mode": "off",
            "query_reuse_read_sample_rate": 0.1,
        },
        {
            "query_reuse_read_mode": "shadow",
            "query_reuse_read_sample_rate": 0.0,
        },
        {
            "query_reuse_read_mode": "canary",
            "query_reuse_read_sample_rate": 1.0,
        },
    ),
)
@pytest.mark.unit
def test_target_b2_read_validation_is_fail_closed(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="query reuse"):
        TargetSettings(_env_file=None, **kwargs)


@pytest.mark.unit
def test_target_b2_canary_requires_gate_and_valid_configuration() -> None:
    valid = TargetSettings(
        _env_file=None,
        target_adapters_enabled=True,
        query_reuse_read_mode="canary",
        query_reuse_read_sample_rate=0.25,
        query_reuse_b1_gate_approved=True,
    )
    assert valid.query_reuse_read_mode == "canary"


@pytest.mark.parametrize(
    "kwargs",
    (
        {"otel_max_queue_size": 4, "otel_max_batch_size": 5},
        {"otel_queue_size": 4, "otel_batch_size": 5},
        {"otel_export_timeout_ms": 0},
        {"otel_retry_limit": 11},
        {"otel_sampling_rate": 1.1},
        {"otel_shutdown_flush_timeout_ms": -1},
    ),
)
@pytest.mark.unit
def test_target_otel_limits_are_bounded(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TargetSettings(_env_file=None, **kwargs)


@pytest.mark.unit
def test_owner_views_are_frozen_and_nested_coverage_is_immutable() -> None:
    query = QueryReuseReadConfigView(
        mode="off",
        sample_rate=0.0,
        minimum_coverage={"food": 0.8},
    )
    with pytest.raises((TypeError, ValidationError), match="immutable|frozen"):
        query.mode = "shadow"  # type: ignore[misc]
    with pytest.raises(TypeError, match="immutable"):
        query.minimum_coverage["food"] = 0.9

    observation = ObservabilityConfigView(
        enabled=False,
        service_name="fixture",
        exporter_endpoint=None,
    )
    with pytest.raises((TypeError, ValidationError), match="immutable|frozen"):
        observation.max_queue_size = 4  # type: ignore[misc]


@pytest.mark.unit
def test_binding_plan_rejects_active_target_without_target_adapters() -> None:
    target = TargetSettings(
        _env_file=None,
        evidence_shadow_enabled=True,
        evidence_shadow_sample_rate=1.0,
        evidence_shadow_write_budget=1,
    )
    owner = build_owner_config(Settings(_env_file=None), target)
    with pytest.raises(ValueError, match="target_adapters_enabled"):
        build_modular_binding_plan(target, owner)


@pytest.mark.unit
def test_binding_plan_rejects_phoenix_without_otel_or_evaluation_endpoint() -> None:
    target = TargetSettings(
        _env_file=None,
        phoenix_enabled=True,
        otel_exporter_endpoint="http://telemetry.invalid/v1/traces",
    )
    owner = build_owner_config(Settings(_env_file=None), target)
    with pytest.raises(ValueError, match="OTel"):
        build_modular_binding_plan(target, owner)

    target = TargetSettings(
        _env_file=None,
        otel_enabled=True,
        phoenix_enabled=True,
        otel_exporter_endpoint="http://telemetry.invalid/v1/traces",
    )
    owner = build_owner_config(Settings(_env_file=None), target)
    with pytest.raises(ValueError, match="HTTP endpoint"):
        build_modular_binding_plan(target, owner)


@pytest.mark.unit
def test_contract_and_domain_modules_do_not_import_vendor_observability_clients() -> None:
    forbidden_roots = {"httpx", "opentelemetry", "phoenix"}
    violations: list[str] = []
    for package in ("contracts", "evidence", "personalization", "domain_packs"):
        package_root = ROOT / "src" / "xhs_food" / package
        if not package_root.exists():
            continue
        for path in sorted(package_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                else:
                    continue
                for module in modules:
                    if module.split(".", 1)[0] in forbidden_roots:
                        violations.append(f"{path.relative_to(ROOT)}: {module}")
    assert violations == []


@pytest.mark.unit
def test_phoenix_adr_pins_transport_health_auth_retention_and_storage_isolation() -> None:
    adr = (
        ROOT
        / "openspec"
        / "changes"
        / "enable-evidence-reuse-memory-phoenix"
        / "decisions"
        / "ADR-0001-phoenix-pins.md"
    ).read_text(encoding="utf-8")
    required_fragments = (
        "arizephoenix/phoenix@sha256:41489a3f4f04310545393d0000cd950f35fad71060bd676d937f0afad379e8f9",
        "POST /v1/traces",
        "/v1/datasets",
        "/v1/experiments",
        "GET /healthz",
        "TLS",
        "bearer `TOKEN`",
        "30 days",
        "phoenix-observability",
        "separate PostgreSQL service/database",
    )
    for fragment in required_fragments:
        assert fragment in adr
