# B2 Query Family Reuse Qualification

Status: Partial implementation - tasks 10.1-10.6 qualified; 10.7-10.13 remain pending

## Implemented boundary

- `QueryFamilyReuseService` tries deterministic canonical key, then PostgreSQL
  `pg_trgm`, then cosine pgvector using the pinned `bge-m3/profile_v1` profile.
- `QueryFamilyMatch` records the layer, confidence, rule/profile version,
  matched alias, and audit basis. Personal/session fields are not accepted by
  the reuse request.
- `FreshnessInput` and `FreshnessPolicy` produce `fresh`, `incremental`, or
  `new` with verified time, coverage, connector-owned watermark advancement,
  and active refresh workflow input.
- `RefreshSingleFlightKey` derives a stable Temporal Workflow ID and a
  PostgreSQL idempotency claim key. Bundle activation uses a PostgreSQL
  current-pointer compare-and-swap; Redis is not consulted.
- Candidate Bundles are validated before the profile read pointer and Bundle
  current pointer move in one row-lock/CAS transaction. A profile mismatch or
  late Bundle writer leaves both pointers unchanged.
- `BundleRefreshService` collects only the public `RefreshJob.delta_scope`, merges
  the delta into an immutable child Bundle, validates every accepted Evidence
  through the Domain Pack, recomputes public features/scores, and requires a
  profile-pinned index receipt before persisting candidate derivations.
- Candidate evidence, derivation receipt, and profile-aware index metadata are
  persisted before PostgreSQL conditional dual-pointer activation. Index,
  derivation, or CAS failure leaves the previous Bundle/profile readable; the
  additive `evidence_bundle_derivations` table is owned by Alembic revision
  `20260824_0005_b2_derivations`.
- Reads map a valid old Bundle to explicit `stale` or `partial` status when
  the Freshness Gate reports time staleness or coverage deficit; a new Family
  returns `unavailable` without fabricating a Bundle.
- `ExplicitRefreshService` validates ordinary/forced refresh envelopes,
  requires `refresh:force` authorization for force mode, reuses the stable
  Family/scope claim, starts only the first Temporal refresh workflow, and
  emits an idempotent accepted `TaskEvent` for both new and reused requests.

## Qualification commands

Offline contract and service tests:

```powershell
uv run --frozen pytest -q tests/test_unit_b2_query_reuse.py tests/test_unit_b1_schema_and_embeddings.py tests/test_unit_b1_embedding_shadow.py
uv run --frozen pytest -q tests/test_unit_b2_bundle_refresh.py
```

Live PostgreSQL/pgvector/pg_trgm test:

```powershell
$env:B2_POSTGRES_URL = "postgresql+asyncpg://POSTGRES_TEST_URL"
uv run --frozen pytest -q -m live tests/test_live_b2_query_reuse.py -vv -s --tb=short
```

Observed on 2026-08-24 with PostgreSQL 16.14 and pgvector:

- offline B2/B1 subset: `33 passed` (including Bundle lifecycle, refresh, and
  delta derivation/pointer failure gates)
- live B2 repository qualification: `1 passed in 6.40s`
- Alembic head resolves through `20260824_0005_b2_derivations`; additive 0005
  upgrade/downgrade SQL smoke passed (live PostgreSQL migration rerun remains
  part of the target-stack gate)
- `uv lock --check`: passed
- targeted Ruff check: passed

## Deliberate non-claims

Tasks 10.7-10.13 remain pending. This milestone does not activate query reuse
reads, background refresh scheduling, personalization, or an external refresh
API. Temporal worker crash replay and production canary gates remain part of
the later B2 tasks.
