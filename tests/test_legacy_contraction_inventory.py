"""Non-destructive inventory gate for the legacy-contraction follow-up."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEDGER = (
    ROOT
    / "openspec"
    / "changes"
    / "legacy-contraction"
    / "references"
    / "compatibility-ledger.md"
)

pytestmark = pytest.mark.unit


def test_compatibility_ledger_is_explicitly_evidence_gated() -> None:
    text = LEDGER.read_text(encoding="utf-8")

    assert "Status: inventory-only" in text
    assert "NO_REMOVAL_IN_INITIAL_PHASE" in text
    for marker in (
        "PENDING_RELEASE_CYCLE",
        "PENDING_CONSUMER_APPROVAL",
        "PENDING_RESTORE",
        "route.search.unified",
        "dto.food.public",
        "export.xhs_food",
        "adapter.repositories",
        "config.legacy.settings",
        "ddl.user-storage",
        "ddl.turn-id-script",
    ):
        assert marker in text


@pytest.mark.parametrize(
    "source_path",
    (
        "src/api/search/routes.py",
        "src/api/README.md",
        "src/xhs_food/__init__.py",
        "src/xhs_food/schemas/__init__.py",
        "src/xhs_food/services/__init__.py",
        "src/xhs_food/agents/__init__.py",
        "src/xhs_food/composition/legacy_research_task.py",
        "src/xhs_food/composition/adapters/repositories.py",
        "src/xhs_food/services/user_storage/schema.py",
        "src/xhs_food/services/postgres_storage.py",
        "src/xhs_food/services/postgres_vector.py",
        "scripts/migrate_turn_id.py",
        "scripts/migrate_sse_recovery.py",
        "src/scripts/migrate_favorites.py",
    ),
)
def test_every_inventoried_source_path_exists(source_path: str) -> None:
    assert (ROOT / source_path).is_file(), source_path


def test_inventory_does_not_claim_release_cycle_or_consumer_approval() -> None:
    text = LEDGER.read_text(encoding="utf-8")

    assert "No complete production release-cycle observation is attached" in text
    assert "external fleet callers unknown" in text
    assert "No row is eligible for removal" in text


def test_restore_rehearsal_records_the_non_destructive_prerequisite() -> None:
    verification = (
        ROOT
        / "openspec"
        / "changes"
        / "legacy-contraction"
        / "verification"
        / "restore-rehearsal.md"
    ).read_text(encoding="utf-8")

    for marker in (
        "Status: **PASS for restore prerequisite; removal remains blocked**",
        "legacy_contraction_rehearsal_20260825",
        "legacy_contraction_n1_20260825",
        "legacy_contraction_restore_20260825",
        "20260824_0007_b3_personalization_memory",
        "worker_rollout=PASS retry_exhaustion=PASS operator_retry=PASS",
        "Runtime DDL paths",
        "Complete release-cycle consumer evidence",
    ):
        assert marker in verification
