"""B1 profile-aware embedding dual-write and resumable backfill gates."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect

from xhs_food.composition.adapters import SQLAlchemyEmbeddingShadowRepository
from xhs_food.contracts import BGE_M3_PROFILE_V1, EmbeddingProfile
from xhs_food.evidence import (
    EmbeddingBackfillInput,
    EmbeddingCompareStatus,
    EmbeddingShadowRow,
    EmbeddingShadowService,
)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Repository:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], EmbeddingShadowRow] = {}
        self.cursor = None
        self.writes = 0

    async def put_embedding(
        self, canonical_key, profile, vector, content_hash, generated_at
    ) -> None:
        self.writes += 1
        key = (canonical_key, profile.profile_id)
        existing = self.rows.get(key)
        if existing is not None and existing.content_hash != content_hash:
            raise ValueError("embedding content hash conflicts with existing profile row")
        self.rows[key] = EmbeddingShadowRow(
            canonical_key=canonical_key,
            profile_id=profile.profile_id,
            vector=vector,
            content_hash=content_hash,
            generated_at=generated_at,
        )

    async def get_embedding(self, canonical_key, profile):
        return self.rows.get((canonical_key, profile.profile_id))

    async def load_backfill_cursor(self, profile):
        del profile
        return self.cursor

    async def save_backfill_cursor(self, cursor) -> None:
        self.cursor = cursor


class Producer:
    def __init__(self, *, fail_on: str | None = None) -> None:
        self.fail_on = fail_on
        self.calls: list[str] = []

    async def embed(self, content: str, profile: EmbeddingProfile) -> tuple[float, ...]:
        self.calls.append(content)
        if content == self.fail_on:
            raise TimeoutError("fixture embedding interruption")
        return (0.0,) * profile.dimensions


@pytest.mark.unit
async def test_dual_write_and_shadow_read_are_profile_pinned_and_hash_checked() -> None:
    repository = Repository()
    service = EmbeddingShadowService(repository)
    producer = Producer()
    row = await service.dual_write("query-1", "public query", producer)
    assert row.profile_id == "profile_v1"
    assert len(row.vector) == 1024
    assert (await service.shadow_read_compare("query-1", "public query")).status is EmbeddingCompareStatus.MATCH
    assert (await service.shadow_read_compare("query-1", "changed query")).status is EmbeddingCompareStatus.MISMATCH
    assert (await service.shadow_read_compare("missing", "public query")).status is EmbeddingCompareStatus.MISSING
    with pytest.raises(ValueError, match="conflicts"):
        await service.dual_write("query-1", "changed query", producer)


@pytest.mark.unit
async def test_backfill_interruption_leaves_cursor_uncommitted_and_resume_is_idempotent() -> None:
    rows = (
        EmbeddingBackfillInput("q-001", "first", _hash("first")),
        EmbeddingBackfillInput("q-002", "second", _hash("second")),
    )
    repository = Repository()
    service = EmbeddingShadowService(repository)
    with pytest.raises(TimeoutError, match="interruption"):
        await service.backfill(rows, Producer(fail_on="second"))
    assert repository.cursor is None
    resumed = await service.backfill(rows, Producer())
    assert resumed.processed_rows == 2
    writes = repository.writes
    assert await service.backfill(rows, Producer()) == resumed
    assert repository.writes == writes


@pytest.mark.unit
async def test_sqlalchemy_embedding_repository_uses_profile_key_and_idempotent_insert() -> None:
    class Result:
        def mappings(self) -> Result:
            return self

        def first(self) -> dict[str, str]:
            return {"content_hash": _hash("public query")}

    class Session:
        def __init__(self) -> None:
            self.statements: list[object] = []

        async def execute(self, statement: object, *_args: object) -> Result:
            self.statements.append(statement)
            return Result()

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
    repository = SQLAlchemyEmbeddingShadowRepository(lambda: unit)  # type: ignore[arg-type]
    await repository.put_embedding(
        "query-1",
        BGE_M3_PROFILE_V1,
        (0.0,) * 1024,
        _hash("public query"),
        datetime(2026, 8, 24, tzinfo=UTC),
    )
    assert unit.commits == 1
    assert len(session.statements) == 2
    compiled = str(session.statements[0].compile(dialect=postgresql_dialect()))
    assert "canonical_query_embeddings" in compiled
    assert "DO NOTHING" in compiled


@pytest.mark.unit
def test_embedding_service_rejects_incompatible_profile_before_any_write() -> None:
    other = EmbeddingProfile(
        profile_id="other_profile",
        model_id="other-model",
        model_version="other-model/v1",
        dimensions=1024,
    )
    with pytest.raises(ValueError, match="pinned"):
        EmbeddingShadowService(Repository(), profile=other)
