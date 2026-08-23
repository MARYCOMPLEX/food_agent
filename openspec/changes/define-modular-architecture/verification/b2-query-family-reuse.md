# B2 Query Family Reuse Qualification

Status: Partial implementation - tasks 10.1-10.3, 10.5, and 10.6 qualified; 10.4 remains partial

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
  late Bundle writer leaves both pointers unchanged. Delta collection and
  feature/score recomputation remain part of task 10.4.
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
```

Live PostgreSQL/pgvector/pg_trgm test:

```powershell
$env:B2_POSTGRES_URL = "postgresql+asyncpg://POSTGRES_TEST_URL"
uv run --frozen pytest -q -m live tests/test_live_b2_query_reuse.py -vv -s --tb=short
```

Observed on 2026-08-24 with PostgreSQL 16.14 and pgvector:

- offline B2/B1 subset: `30 passed` (including Bundle lifecycle and refresh)
- live B2 repository qualification: `1 passed in 6.40s`
- migration clean upgrade and B2 downgrade/upgrade through `20260824_0004_b2_activate`: passed
- `uv lock --check`: passed
- targeted Ruff check: passed

## Deliberate non-claims

Tasks 10.4 and 10.7-10.13 remain pending. This milestone does not activate query reuse
reads, background refresh scheduling, personalization, or an external refresh
API. Temporal worker crash replay and production canary gates remain part of
the later B2 tasks.
