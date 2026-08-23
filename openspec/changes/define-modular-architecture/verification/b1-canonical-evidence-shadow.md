# B1 Canonical Evidence Shadow Verification

Status: Partial - offline schema/profile/repository gates pass; PostgreSQL and
interruption recovery gates remain pending

Change: `define-modular-architecture`

## Scope

B1 is shadow-only. The Canonical Query normalizer and deterministic Family
identity are not bound to HTTP/SSE, legacy result reads, similarity matching,
Bundle reuse, or response selection. PostgreSQL remains the authority; Redis and
process memory are not used by this path.

## Gate Status

| Task | Status | Evidence | Remaining gate |
|---|---|---|---|
| 9.1 Alembic additive schema | PARTIAL | `alembic/versions/20260824_0001_b1_shadow_schema.py`; offline PostgreSQL SQL emits only B1 tables and `VECTOR(1024)` | Clean/N-1/pre-turn/current PostgreSQL 16 inventory, idempotent upgrade, interruption and rollback rehearsal |
| 9.2 SQLAlchemy Core repository | PASS (offline) | `SQLAlchemyCanonicalQueryShadowRepository`; one owner UoW/session and one PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` contract test | Live PostgreSQL transaction and constraint qualification |
| 9.3 Embedding profile | PASS (offline) | `BGE_M3_PROFILE_V1` fixes `bge-m3/profile_v1/1024/cosine`; separate `canonical_query_embeddings` table uses `VECTOR(1024)` | pgvector index creation/quality gate and activation rehearsal |
| 9.4 Backfill/dual-write tools | PARTIAL | Versioned `EmbeddingBackfillCursor`, sorted-page validation, chained content hash and idempotent page replay | Embedding producer dual-write, resumable interruption against PostgreSQL, row/hash reconciliation and shadow-read compare |
| 9.5 Canonical normalizer | PASS (offline) | Public/personal/unclassified classification, Unicode normalization, versioned schema/classifier, fail-closed omitted/duplicate classification | Domain Pack matrix expansion |
| 9.6 Deterministic Family identity | PASS (offline) | Stable canonical JSON preimage, SHA-256 key, explainable `FamilyMatchBasis`; no similarity/read reuse binding | B2 matching qualification remains disabled |
| 9.7 Canonical source batch | PASS (offline) | `CanonicalSourceBatchNormalizer` fixes source/external IDs, canonical URL/query ordering, captured time, watermark and rejects binary payloads | Connector differential matrix and live source payload sampling |
| 9.8 Provenance validation | PASS (offline) | `validate_evidence_provenance` and quarantine helper reject missing locator, schema, partition, media or artifact links | Candidate Bundle repository must persist quarantine state before publication |

## Commands

```powershell
uv run --frozen pytest -q tests/test_unit_b1_schema_and_embeddings.py tests/test_unit_b1_canonical_shadow.py
# 8 passed

uv run --frozen pytest -q tests/test_unit_b1_source_provenance.py
# 3 passed

uv run --frozen pytest -q -m "not live" -ra --durations=0
# 753 passed, 12 deselected, 2 warnings

uv run --frozen ruff check src/xhs_food/contracts src/xhs_food/evidence src/xhs_food/foundation/evidence_schema.py src/xhs_food/composition/adapters/evidence_shadow_repository.py tests/test_unit_b1_schema_and_embeddings.py alembic
# passed

uv run --frozen pyright src/xhs_food/contracts/embedding.py src/xhs_food/composition/adapters/evidence_shadow_repository.py src/xhs_food/foundation/evidence_schema.py
# 0 errors

uv run alembic upgrade --sql 20260824_0001_b1_shadow
uv run alembic downgrade --sql 20260824_0001_b1_shadow:base
# passed; static PostgreSQL SQL generation
```

The offline migration check intentionally does not claim a live database
upgrade. No runtime `CREATE TABLE IF NOT EXISTS`, second schema definition,
legacy `VECTOR(4096)` alteration, or current-pointer activation is introduced.
