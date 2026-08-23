"""B2 profile/index quality gates that do not require a live database."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from xhs_food.contracts import BGE_M3_PROFILE_V1, QueryReuseRequest, validate_embedding_vector
from xhs_food.evidence import QueryFamilyReuseService

FIXTURE = Path(__file__).parent / "fixtures" / "authority" / "bge_m3_profile_v1.json"
MIGRATION = Path(__file__).parents[1] / "alembic" / "versions" / "20260824_0005_b2_derivations.py"


@pytest.mark.unit
def test_fixed_bge_m3_fixture_pins_dimension_cosine_and_vector_hash() -> None:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert {key: value[key] for key in ("profile_id", "model_id", "model_version", "dimensions", "distance", "normalized")} == {
        "profile_id": "profile_v1",
        "model_id": "bge-m3",
        "model_version": "bge-m3/v1",
        "dimensions": 1024,
        "distance": "cosine",
        "normalized": True,
    }
    vector = (float(value["vector_first"]),) + (float(value["vector_rest"]),) * (value["dimensions"] - 1)
    validate_embedding_vector(BGE_M3_PROFILE_V1, vector)
    encoded = json.dumps(vector, separators=(",", ":"))
    assert hashlib.sha256(encoded.encode("utf-8")).hexdigest() == value["vector_sha256"]


@pytest.mark.unit
def test_b2_migration_builds_profile_aware_cosine_hnsw_index() -> None:
    spec = importlib.util.spec_from_file_location("b2_derivations", MIGRATION)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
    sql = output.getvalue()
    assert "ix_canonical_query_embeddings_vector_cosine" in sql
    assert "USING hnsw" in sql
    assert "vector_cosine_ops" in sql


class _DisabledEmbeddingRepository:
    async def get_exact(self, canonical_key: str):
        del canonical_key
        return None

    async def search_trigram(self, alias_text: str, *, limit: int = 5):
        del alias_text, limit
        return ()

    async def search_vector(self, vector, profile, *, limit: int = 5):
        raise AssertionError("vector tier must not run when embedding is disabled")


@pytest.mark.unit
async def test_embedding_disabled_keeps_deterministic_and_trigram_ports_available() -> None:
    service = QueryFamilyReuseService(_DisabledEmbeddingRepository())
    decision = await service.resolve(
        QueryReuseRequest(
            canonical_key="query.missing",
            alias_text="自贡本地美食",
            vector=None,
        )
    )
    assert decision.match is None
