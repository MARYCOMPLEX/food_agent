"""Keep architecture references and compatibility records aligned with code."""

from __future__ import annotations

from pathlib import Path

import pytest

from xhs_food.composition.domain_packs import DomainPackRegistry
from xhs_food.domain_packs import (
    create_food_pack,
    create_travel_pack,
    load_food_contract_resources,
    load_travel_contract_resources,
)

ROOT = Path(__file__).resolve().parents[1]
CHANGE = ROOT / "openspec" / "changes" / "define-modular-architecture"
pytestmark = pytest.mark.unit


def _registered_snapshot() -> dict[tuple[str, str], object]:
    food_manifest, food_bundle = load_food_contract_resources()
    travel_manifest, travel_bundle = load_travel_contract_resources()
    registry = DomainPackRegistry(
        core_version="1.0.0",
        tool_capabilities={
            tool.tool_id: tool.tool_version
            for manifest in (food_manifest, travel_manifest)
            for tool in manifest.allowed_tools
        },
        source_capabilities={
            source.capability: "1.0.0"
            for manifest in (food_manifest, travel_manifest)
            for source in manifest.domain_sources
        },
    )
    registry.register_or_raise(food_manifest, create_food_pack(), food_bundle)
    registry.register_or_raise(travel_manifest, create_travel_pack(), travel_bundle)
    return dict(registry.publish_snapshot())


def test_contract_catalog_matches_registered_manifests_and_schema_bundles() -> None:
    snapshot = _registered_snapshot()
    catalog = (CHANGE / "references" / "contract-catalog.md").read_text(encoding="utf-8")

    assert set(snapshot) == {("food", "1.0.0"), ("travel", "1.0.0")}
    for (domain_id, pack_version), registered in snapshot.items():
        manifest = registered.manifest  # type: ignore[attr-defined]
        bundle = registered.schema_bundle  # type: ignore[attr-defined]
        assert f"| `{domain_id}` | `{pack_version}` |" in catalog
        assert f"`{manifest.contract_api}`" in catalog
        assert f"`{bundle.bundle_version}`" in catalog
        output_version = manifest.final_output_example["schemaVersion"]
        assert f"`{output_version}`" in catalog


def test_architecture_references_and_compatibility_ledger_have_required_anchors() -> None:
    html = (CHANGE / "references" / "food-agent-unified-architecture.html").read_text(
        encoding="utf-8"
    )
    drawio = (
        CHANGE / "references" / "food-agent-extensible-evidence-architecture.drawio"
    ).read_text(encoding="utf-8")
    decisions = (CHANGE / "decisions" / "README.md").read_text(encoding="utf-8")
    compatibility = (CHANGE / "decisions" / "ADR-0009-legacy-gap-disposition.md").read_text(
        encoding="utf-8"
    )

    for label in (
        "Research Orchestrator",
        "Evidence Intelligence",
        "Knowledge & Decision",
        "Personalization",
        "Foundation",
        "Food Pack",
        "Travel Pack",
    ):
        assert label in html
    for label in ("Research", "Evidence", "PostgreSQL", "MinIO", "Temporal", "Travel Pack", "Redis 7 Hot State"):
        assert label in drawio
    for adr in ("ADR-0001", "ADR-0002", "ADR-0009", "ADR-0013"):
        assert adr in decisions
    for anchor in (
        "characterize and preserve",
        "Independent change",
        "configuration_deployment_contract.json",
        "rollback",
    ):
        assert anchor.lower() in compatibility.lower()


def test_milestone_verification_and_rollback_assets_are_present() -> None:
    verification = CHANGE / "verification"
    runbooks = CHANGE / "runbooks"
    for milestone in ("s0", "s1", "s2", "s3", "s4", "s5", "b0", "b1", "b2", "b3", "b4", "b5"):
        assert any(path.name.lower().startswith(milestone) for path in verification.iterdir())
    for runbook in (
        "s2-modular-core-rollback.md",
        "s3-adapter-rollback.md",
        "s4-food-pack-rollback.md",
        "s5-research-skeleton-rollback.md",
        "b0-reliable-task-rollback.md",
        "b1-evidence-shadow-rollback.md",
        "b2-query-family-rollback.md",
        "b3-personalization-rollback.md",
        "b4-worker-isolation-rollback.md",
    ):
        assert (runbooks / runbook).is_file()
