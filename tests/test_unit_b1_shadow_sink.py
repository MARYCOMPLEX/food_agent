"""B1 atomic source-batch shadow sink and migration gates."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect

from xhs_food.composition.adapters import SQLAlchemyEvidenceShadowRepository
from xhs_food.contracts import CanonicalSourceBatch
from xhs_food.domain_packs.food.pack import FoodPack
from xhs_food.evidence import (
    CanonicalQueryNormalizer,
    EvidenceShadowPolicy,
    build_shadow_record,
)
from xhs_food.foundation import SQLAlchemyUnitOfWork

ROOT = Path(__file__).parents[1]
CANONICAL_FIXTURE = ROOT / "tests" / "fixtures" / "authority" / "canonical_query_v1.json"
NOW = datetime(2026, 8, 24, tzinfo=UTC)


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
        retention={
            "retention_class": "evidence_default",
            "duration_seconds": None,
            "legal_hold": False,
        },
        visibility={"scope": "public", "tenant_scope": "public", "entitlement_ids": []},
    )


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> None:
        self.statements.append(statement)


class _RecordingUnit:
    def __init__(self, session: _RecordingSession) -> None:
        self.session = session
        self.commits = 0

    async def __aenter__(self) -> _RecordingUnit:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def session_for_adapter(self) -> _RecordingSession:
        return self.session

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.unit
async def test_b1_sink_persists_complete_projection_in_one_transaction() -> None:
    session = _RecordingSession()
    unit = _RecordingUnit(session)
    repository = SQLAlchemyEvidenceShadowRepository(lambda: unit)  # type: ignore[arg-type]
    record = build_shadow_record(_batch(), _policy())

    await repository.write(record)

    assert unit.commits == 1
    compiled = [
        statement.compile(dialect=postgresql_dialect()) for statement in session.statements
    ]
    sql = "\n".join(str(statement) for statement in compiled)
    assert "INSERT INTO evidence_source_batches" in sql
    assert "INSERT INTO evidence_source_locators" in sql
    assert "INSERT INTO evidence_items" in sql
    assert "INSERT INTO evidence_source_batch_items" in sql
    assert "INSERT INTO evidence_bundles" in sql
    assert "evidence_bundle_current" not in sql
    assert len(compiled) == (
        int(record.canonical_query is not None)
        + 2
        + len(record.locators)
        + 2 * len(record.evidence_items)
    )
    assert all("DO NOTHING" in str(statement) for statement in compiled)
    source_batch_params = compiled[0].params
    assert source_batch_params["batch_id"] == record.source_batch_id
    link_params = compiled[-2].params
    assert link_params["batch_id"] == record.source_batch_id
    assert link_params["evidence_id"] == record.evidence_items[0].evidence_id


@pytest.mark.unit
async def test_b1_sink_keeps_canonical_query_in_the_candidate_transaction() -> None:
    session = _RecordingSession()
    unit = _RecordingUnit(session)
    repository = SQLAlchemyEvidenceShadowRepository(lambda: unit)  # type: ignore[arg-type]
    canonical_payload = json.loads(CANONICAL_FIXTURE.read_text(encoding="utf-8"))
    canonical_payload["query"]["constraints"] = [
        {"constraint_id": "food-type", "key": "food_type", "operator": "eq", "value": "local_food"}
    ]
    canonical = CanonicalQueryNormalizer(FoodPack()).normalize(canonical_payload)
    canonical_batch = _batch().model_copy(update={"isolation": canonical.canonical_query.isolation})
    record = build_shadow_record(canonical_batch, _policy(), canonical_result=canonical)

    await repository.write(record)

    assert unit.commits == 1
    compiled = [
        statement.compile(dialect=postgresql_dialect()) for statement in session.statements
    ]
    assert "INSERT INTO canonical_queries" in str(compiled[0])
    assert "INSERT INTO evidence_source_batches" in str(compiled[1])
    assert "evidence_bundle_current" not in "\n".join(map(str, compiled))


@pytest.mark.unit
async def test_b1_sink_duplicate_delivery_is_idempotent_and_keeps_pointer_unwritten() -> None:
    session = _RecordingSession()
    unit = _RecordingUnit(session)
    repository = SQLAlchemyEvidenceShadowRepository(lambda: unit)  # type: ignore[arg-type]
    record = build_shadow_record(_batch(), _policy())

    await repository.write(record)
    await repository.write(record)

    assert unit.commits == 2
    sql = [str(statement.compile(dialect=postgresql_dialect())) for statement in session.statements]
    assert all("DO NOTHING" in statement for statement in sql)
    assert all("evidence_bundle_current" not in statement for statement in sql)


@pytest.mark.unit
async def test_b1_sink_allocates_a_new_bundle_version_for_corrected_content() -> None:
    """A family/version collision must become an immutable child candidate."""

    class _Result:
        def __init__(self, rowcount: int, row: dict[str, object] | None = None) -> None:
            self.rowcount = rowcount
            self._row = row

        def mappings(self) -> _Result:
            return self

        def first(self) -> dict[str, object] | None:
            return self._row

    class _ConflictSession(_RecordingSession):
        def __init__(self) -> None:
            super().__init__()
            self.bundle_inserts = 0

        async def execute(self, statement: Any) -> _Result:
            self.statements.append(statement)
            sql = str(statement.compile(dialect=postgresql_dialect()))
            if "INSERT INTO evidence_bundles" in sql:
                self.bundle_inserts += 1
                # The builder emits v1. Simulate an existing v1 row, then let
                # the repository insert the allocated v2 child.
                return _Result(1 if self.bundle_inserts == 1 else 0 if self.bundle_inserts == 2 else 1)
            if "FROM evidence_bundles" in sql and "SELECT" in sql:
                return _Result(
                    1,
                    {
                        "bundle_id": "bundle.existing.v1",
                        "bundle_version": 1,
                        "content_hash": "old-content-hash",
                    },
                )
            return _Result(1)

    session = _ConflictSession()
    unit = _RecordingUnit(session)  # type: ignore[arg-type]
    repository = SQLAlchemyEvidenceShadowRepository(lambda: unit)  # type: ignore[arg-type]
    first = build_shadow_record(_batch(), _policy())
    corrected_document = _batch().documents[0].model_copy(update={"text": "corrected"})
    corrected = build_shadow_record(
        _batch().model_copy(update={"documents": (corrected_document,)}),
        _policy(),
    )

    await repository.write(first)
    await repository.write(corrected)

    bundle_sql = [
        statement.compile(dialect=postgresql_dialect())
        for statement in session.statements
        if "INSERT INTO evidence_bundles"
        in str(statement.compile(dialect=postgresql_dialect()))
    ]
    assert len(bundle_sql) == 3
    assert bundle_sql[-1].params["bundle_version"] == 2
    assert bundle_sql[-1].params["parent_bundle_id"] == "bundle.existing.v1"
    payload = bundle_sql[-1].params["payload"]
    assert payload["bundle_version"] == 2
    assert payload["parent_bundle_version"] == 1


@pytest.mark.unit
async def test_b1_sink_aborts_owned_transaction_before_commit() -> None:
    record = build_shadow_record(_batch(), _policy())
    calls: list[str] = []

    class FailingSession:
        async def begin(self) -> None:
            calls.append("begin")

        async def execute(self, statement: object) -> None:
            del statement
            calls.append("execute")
            if calls.count("execute") == 3:
                raise TimeoutError("source batch transaction timeout")

        async def rollback(self) -> None:
            calls.append("rollback")

        async def close(self) -> None:
            calls.append("close")

        async def commit(self) -> None:
            calls.append("commit")

    unit = SQLAlchemyUnitOfWork(FailingSession)
    repository = SQLAlchemyEvidenceShadowRepository(lambda: unit)  # type: ignore[arg-type]
    with pytest.raises(TimeoutError, match="source batch transaction timeout"):
        await repository.write(record)

    assert calls == ["begin", "execute", "execute", "execute", "rollback", "close"]
    assert "commit" not in calls


@pytest.mark.unit
async def test_b1_sink_rejects_missing_provenance_before_opening_transaction() -> None:
    session = _RecordingSession()
    unit = _RecordingUnit(session)
    repository = SQLAlchemyEvidenceShadowRepository(lambda: unit)  # type: ignore[arg-type]
    record = build_shadow_record(_batch(), _policy())
    malformed = replace(record, locators=())

    with pytest.raises(ValueError, match="source locator"):
        await repository.write(malformed)

    assert unit.commits == 0
    assert session.statements == []


@pytest.mark.unit
async def test_b1_sink_revalidates_hash_schema_and_license_before_opening_transaction() -> None:
    session = _RecordingSession()
    unit = _RecordingUnit(session)
    repository = SQLAlchemyEvidenceShadowRepository(lambda: unit)  # type: ignore[arg-type]
    record = build_shadow_record(_batch(), _policy())

    bad_hash = record.evidence_items[0].model_copy(update={"content_hash": "0" * 64})
    with pytest.raises(ValueError, match="content_hash"):
        await repository.write(replace(record, evidence_items=(bad_hash,)))
    assert unit.commits == 0
    assert session.statements == []

    bad_schema = record.evidence_items[0].model_copy(update={"schema_version": "other/v1"})
    with pytest.raises(ValueError, match="schema_version"):
        await repository.write(replace(record, evidence_items=(bad_schema,)))
    assert unit.commits == 0
    assert session.statements == []

    bad_license = record.evidence_items[0].model_copy(
        update={
            "license": {
                **record.evidence_items[0].license.model_dump(mode="json"),
                "status": "unknown",
            }
        }
    )
    with pytest.raises(ValueError, match="license"):
        await repository.write(replace(record, evidence_items=(bad_license,)))
    assert unit.commits == 0
    assert session.statements == []


@pytest.mark.unit
def test_source_batch_migration_is_additive_and_reversible() -> None:
    path = ROOT / "alembic" / "versions" / "20260905_0012_b1_source_batches.py"
    spec = importlib.util.spec_from_file_location("b1_source_batch_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.down_revision == "20260905_0011_b2_freshness_watermark"
    upgrade_buffer = StringIO()
    upgrade_context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": upgrade_buffer},
    )
    with Operations.context(upgrade_context):
        migration.upgrade()
    upgrade_sql = upgrade_buffer.getvalue().lower()
    assert "create table evidence_source_batches" in upgrade_sql
    assert "create table evidence_source_batch_items" in upgrade_sql
    assert "create table chat_history" not in upgrade_sql

    downgrade_buffer = StringIO()
    downgrade_context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": downgrade_buffer},
    )
    with Operations.context(downgrade_context):
        migration.downgrade()
    downgrade_sql = downgrade_buffer.getvalue().lower()
    assert "drop table evidence_source_batch_items" in downgrade_sql
    assert "drop table evidence_source_batches" in downgrade_sql
    assert "drop table chat_history" not in downgrade_sql


@pytest.mark.unit
def test_b1_shadow_record_source_batch_id_is_stable_and_changes_with_content() -> None:
    first = build_shadow_record(_batch(), _policy())
    corrected = build_shadow_record(
        _batch().model_copy(update={"documents": (_batch().documents[0].model_copy(update={"text": "corrected"}),)}),
        _policy(),
    )

    assert first.source_batch_id is not None
    assert first.source_batch_id == build_shadow_record(_batch(), _policy()).source_batch_id
    assert corrected.source_batch_id != first.source_batch_id
    assert corrected.evidence_items[0].evidence_id != first.evidence_items[0].evidence_id
