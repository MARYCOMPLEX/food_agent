"""B1 failure-injection gates for shadow-only writes and migration boundaries."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.schema import CreateTable

from xhs_food.composition.adapters import SQLAlchemyCandidateBundleRepository
from xhs_food.contracts import (
    BGE_M3_PROFILE_V1,
    BundleState,
    CanonicalQuery,
    CanonicalSourceBatch,
    CollectRequest,
    EmbeddingProfile,
    EvidenceBundle,
    EvidenceItem,
    SourceLocator,
    validate_embedding_vector,
)
from xhs_food.domain_packs.food.pack import FoodPack
from xhs_food.evidence import (
    CanonicalQueryNormalizer,
    CanonicalSourceBatchNormalizer,
    EvidenceShadowPolicy,
    ShadowSourceConnector,
    ShadowWriteRecord,
    UnclassifiedConstraintError,
)
from xhs_food.foundation import SQLAlchemyUnitOfWork

ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "20260824_0001_b1_shadow_schema.py"
FIXTURE = ROOT / "tests" / "fixtures" / "authority" / "canonical_query_v1.json"
EVIDENCE_FIXTURE = ROOT / "tests" / "fixtures" / "authority" / "evidence_bundle_v1.json"


def _request() -> CollectRequest:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return CollectRequest(
        query=CanonicalQuery.model_validate(payload),
        source_scope=("fixture",),
        depth="standard",
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
        connector_version="fixture-connector/v1",
        normalizer_version="fixture-normalizer/v1",
        documents=(
            {
                "source_id": "fixture",
                "external_id": "note-1",
                "canonical_url": "https://source.invalid/note/1",
                "captured_at": "2026-08-24T00:00:00Z",
                "title": "Fixture",
            },
        ),
    )


@pytest.mark.unit
async def test_transaction_abort_rolls_back_and_closes_the_owned_session() -> None:
    calls: list[str] = []

    class Session:
        async def begin(self) -> None:
            calls.append("begin")

        async def rollback(self) -> None:
            calls.append("rollback")

        async def close(self) -> None:
            calls.append("close")

        async def execute(self, statement: object) -> None:
            del statement
            calls.append("execute")
            raise TimeoutError("fixture transaction abort")

    unit = SQLAlchemyUnitOfWork(Session)
    with pytest.raises(TimeoutError, match="transaction abort"):
        async with unit:
            await unit.session_for_adapter().execute("shadow write")
    assert calls == ["begin", "execute", "rollback", "close"]


@pytest.mark.unit
def test_alembic_interruption_stops_before_current_pointer_activation(monkeypatch: pytest.MonkeyPatch) -> None:
    spec = importlib.util.spec_from_file_location("b1_interrupted_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    class InterruptingOperations:
        def __init__(self) -> None:
            self.calls: list[object] = []

        def execute(self, statement: object) -> None:
            self.calls.append(statement)
            if len(self.calls) == 3:
                raise RuntimeError("fixture migration interruption")

        def drop_table(self, name: str) -> None:
            self.calls.append(f"drop:{name}")

    operations = InterruptingOperations()
    monkeypatch.setattr(migration, "op", operations)
    with pytest.raises(RuntimeError, match="migration interruption"):
        migration.upgrade()
    rendered = "\n".join(
        str(item.element if isinstance(item, CreateTable) else item) for item in operations.calls
    )
    assert "evidence_bundle_current" not in rendered


@pytest.mark.unit
def test_profile_dimension_mismatch_and_unclassified_constraint_fail_closed() -> None:
    with pytest.raises(ValueError, match="dimension mismatch"):
        validate_embedding_vector(BGE_M3_PROFILE_V1, (0.0,))
    with pytest.raises(ValueError, match="pinned"):
        from xhs_food.contracts import initial_backfill_cursor

        initial_backfill_cursor(
            EmbeddingProfile(
                profile_id="other_profile",
                model_id="other-model",
                model_version="other-model/v1",
                dimensions=1024,
            )
        )
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["query"]["constraints"] = [
        {"constraint_id": "unknown", "key": "private_identity", "operator": "eq", "value": "x"}
    ]
    with pytest.raises(UnclassifiedConstraintError):
        CanonicalQueryNormalizer(FoodPack()).normalize(payload)


@pytest.mark.unit
def test_malformed_source_item_is_rejected_before_shadow_write() -> None:
    with pytest.raises(ValueError, match="canonical_url"):
        CanonicalSourceBatchNormalizer().normalize(
            {
                "isolation": {"tenant_scope": "public", "language": "en", "region": "US"},
                "source_id": "fixture",
                "connector_id": "fixture.connector",
                "connector_version": "fixture/v1",
                "documents": [{"id": "note-1", "captured_at": "2026-08-24T00:00:00Z"}],
            }
        )


@pytest.mark.unit
async def test_connector_timeout_is_legacy_visible_but_shadow_sink_is_not_called() -> None:
    class TimeoutConnector:
        source_id = "fixture"

        async def search(self, request: CollectRequest) -> CanonicalSourceBatch:
            del request
            raise TimeoutError("fixture connector timeout")

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

    sink = Sink()
    connector = ShadowSourceConnector(TimeoutConnector(), policy=_policy(), sink=sink)
    with pytest.raises(TimeoutError, match="connector timeout"):
        await connector.search(_request())
    assert sink.records == []


@pytest.mark.unit
async def test_duplicate_shadow_insert_is_idempotent_and_has_no_current_pointer_statement() -> None:
    value = json.loads(EVIDENCE_FIXTURE.read_text(encoding="utf-8"))
    bundle = EvidenceBundle.model_validate(value["bundles"][0]).model_copy(
        update={"state": BundleState.CANDIDATE}
    )
    items = tuple(EvidenceItem.model_validate(item) for item in value["evidence_items"])

    class Session:
        def __init__(self) -> None:
            self.statements: list[object] = []

        async def execute(self, statement: object) -> None:
            self.statements.append(statement)

    class Unit:
        def __init__(self, session: Session) -> None:
            self.session = session
            self.commits = 0

        async def __aenter__(self) -> Unit:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def session_for_adapter(self) -> Session:
            return self.session

        async def commit(self) -> None:
            self.commits += 1

    session = Session()
    unit = Unit(session)
    repository = SQLAlchemyCandidateBundleRepository(lambda: unit)  # type: ignore[arg-type]
    await repository.save_candidate(bundle, items)
    await repository.save_candidate(bundle, items)

    assert unit.commits == 2
    compiled = [str(statement.compile(dialect=postgresql_dialect())) for statement in session.statements]
    assert len(compiled) == 2 * (len(items) + 1)
    assert all("DO NOTHING" in statement for statement in compiled)
    assert all("evidence_bundle_current" not in statement for statement in compiled)
