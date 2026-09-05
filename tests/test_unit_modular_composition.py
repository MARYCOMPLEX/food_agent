"""Composition Root integration tests for the B1/B2/B3 capability plan."""

from __future__ import annotations

import pytest

from xhs_food.composition import (
    ModularAdapterOverrides,
    build_composition_root,
    build_modular_binding_plan,
)
from xhs_food.composition.adapters import build_owner_config
from xhs_food.config import Settings
from xhs_food.foundation import TargetSettings


class _PortFixture:
    """Structural test port with the methods required by one capability."""

    def __init__(self, *methods: str) -> None:
        for method in methods:
            setattr(self, method, lambda *args, **kwargs: None)


@pytest.mark.unit
async def test_active_modular_modes_bind_stable_logical_names() -> None:
    settings = TargetSettings(
        _env_file=None,
        target_adapters_enabled=True,
        database_url="postgresql+asyncpg://postgres:postgres@db/xhs_food_agent",
        evidence_shadow_enabled=True,
        evidence_shadow_sample_rate=1.0,
        evidence_shadow_write_budget=100,
        query_reuse_read_mode="shadow",
        query_reuse_read_sample_rate=1.0,
        personalization_canary_mode="shadow",
        personalization_canary_sample_rate=1.0,
    )
    overrides = ModularAdapterOverrides(
        evidence_shadow_sink=_PortFixture("write"),
        canonical_query_shadow=_PortFixture("save"),
        query_family_repository=_PortFixture(
            "get_exact",
            "search_trigram",
            "search_vector",
            "get_freshness",
            "save_freshness",
            "claim_refresh",
            "activate_bundle_if_current",
            "update_refresh_status",
        ),
        query_reuse_read=_PortFixture("read"),
        memory_repository=_PortFixture(
            "append_conversation_turn",
            "save_record",
            "commit_authority_write",
            "append_memory_event",
            "list_records",
            "list_conversation_turns",
            "claim_anonymous",
            "save_preference_snapshot",
            "enqueue_outbox",
        ),
        memory_session_window=_PortFixture("append", "recent", "clear"),
    )

    root = build_composition_root(
        target_settings=settings,
        modular_overrides=overrides,
    )
    try:
        assert set(root.logical_bindings) >= {
            "evidence.canonical_query_shadow",
            "evidence.shadow_sink",
            "evidence.query_family_repository",
            "evidence.query_reuse_read",
            "memory.authority_repository",
            "memory.session_projection",
            "memory.outbox_projector",
            "memory.authority_writer",
        }
        assert (
            await root.resolve_logical("evidence.shadow_sink")
            is overrides.evidence_shadow_sink
        )
        assert (
            await root.resolve_logical("evidence.query_family_repository")
            is overrides.query_family_repository
        )
        assert (
            await root.resolve_logical("memory.authority_repository")
            is overrides.memory_repository
        )
    finally:
        await root.close()


@pytest.mark.unit
def test_active_modular_modes_fail_closed_without_required_ports() -> None:
    settings = TargetSettings(
        _env_file=None,
        target_adapters_enabled=True,
        database_url="postgresql+asyncpg://postgres:postgres@db/xhs_food_agent",
        evidence_shadow_enabled=True,
        evidence_shadow_sample_rate=1.0,
        evidence_shadow_write_budget=100,
    )
    with pytest.raises(RuntimeError, match="evidence_shadow_sink"):
        build_composition_root(target_settings=settings)


@pytest.mark.unit
async def test_injected_modular_adapters_do_not_require_target_database() -> None:
    settings = TargetSettings(
        _env_file=None,
        target_adapters_enabled=True,
        evidence_shadow_enabled=True,
        evidence_shadow_sample_rate=1.0,
        evidence_shadow_write_budget=100,
    )
    overrides = ModularAdapterOverrides(
        evidence_shadow_sink=_PortFixture("write"),
        canonical_query_shadow=_PortFixture("save"),
    )
    root = build_composition_root(
        target_settings=settings,
        modular_overrides=overrides,
    )
    try:
        assert await root.resolve_logical("evidence.shadow_sink") is overrides.evidence_shadow_sink
    finally:
        await root.close()


@pytest.mark.unit
async def test_explicit_plan_drives_all_active_bindings_and_builds_missing_services() -> None:
    settings = TargetSettings(
        _env_file=None,
        target_adapters_enabled=True,
        evidence_shadow_enabled=True,
        evidence_shadow_sample_rate=1.0,
        evidence_shadow_write_budget=100,
        query_reuse_read_mode="shadow",
        query_reuse_read_sample_rate=1.0,
        personalization_canary_mode="shadow",
        personalization_canary_sample_rate=1.0,
        otel_enabled=True,
    )
    owner = build_owner_config(Settings(_env_file=None), settings)
    plan = build_modular_binding_plan(settings, owner)
    query_repository = _PortFixture(
        "get_exact",
        "search_trigram",
        "search_vector",
        "get_freshness",
        "save_freshness",
        "claim_refresh",
        "activate_bundle_if_current",
        "update_refresh_status",
    )
    memory_repository = _PortFixture(
        "append_conversation_turn",
        "save_record",
        "commit_authority_write",
        "append_memory_event",
        "list_records",
        "list_conversation_turns",
        "claim_anonymous",
        "save_preference_snapshot",
        "enqueue_outbox",
    )
    memory_session = _PortFixture("append", "recent", "clear")
    observation = _PortFixture("observe", "flush", "health")
    evaluation = _PortFixture("submit_dataset", "submit_run", "close", "health")
    overrides = ModularAdapterOverrides(
        evidence_shadow_sink=_PortFixture("write"),
        canonical_query_shadow=_PortFixture("save"),
        query_family_repository=query_repository,
        memory_repository=memory_repository,
        memory_session_window=memory_session,
        observation_port=observation,
        evaluation_port=evaluation,
    )

    root = build_composition_root(
        target_settings=TargetSettings(_env_file=None),
        modular_binding_plan=plan,
        modular_overrides=overrides,
    )
    try:
        assert root.modular_plan is plan
        assert await root.resolve_logical("evidence.query_family_repository") is query_repository
        assert await root.resolve_logical("evidence.query_reuse_read") is not None
        assert await root.resolve_logical("memory.authority_repository") is memory_repository
        assert await root.resolve_logical("memory.session_projection") is memory_session
        assert await root.resolve_logical("observability.observation_port") is observation
        assert await root.resolve_logical("observability.evaluation_port") is evaluation
        assert "personalization_canary" in root.logical_bindings
    finally:
        await root.close()


@pytest.mark.unit
def test_otel_activation_without_endpoint_or_observation_port_fails_closed() -> None:
    settings = TargetSettings(_env_file=None, otel_enabled=True)
    with pytest.raises(RuntimeError, match="OTLP exporter endpoint"):
        build_composition_root(target_settings=settings)


@pytest.mark.unit
def test_memory_projection_and_writer_overrides_are_method_validated() -> None:
    settings = TargetSettings(
        _env_file=None,
        target_adapters_enabled=True,
        personalization_canary_mode="shadow",
        personalization_canary_sample_rate=1.0,
    )
    repository = _PortFixture(
        "append_conversation_turn",
        "save_record",
        "commit_authority_write",
        "append_memory_event",
        "list_records",
        "list_conversation_turns",
        "claim_anonymous",
        "save_preference_snapshot",
        "enqueue_outbox",
    )
    session = _PortFixture("append", "recent", "clear")
    with pytest.raises(TypeError, match="memory_outbox_projector"):
        build_composition_root(
            target_settings=settings,
            modular_overrides=ModularAdapterOverrides(
                memory_repository=repository,
                memory_session_window=session,
                memory_outbox_projector=object(),
            ),
        )
    with pytest.raises(TypeError, match="memory_authority_writer"):
        build_composition_root(
            target_settings=settings,
            modular_overrides=ModularAdapterOverrides(
                memory_repository=repository,
                memory_session_window=session,
                memory_authority_writer=object(),
            ),
        )
