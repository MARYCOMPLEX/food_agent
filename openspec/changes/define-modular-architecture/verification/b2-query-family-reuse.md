# B2 Query Family Reuse Qualification

Status: Partial implementation - tasks 10.1-10.11 and 10.13 qualified; 10.12 target-stack gate pending

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
- `QueryReuseReadService` is closed-world by default. Shadow mode compares
  deterministic public digests while serving legacy output; canary mode uses a
  deterministic request hash and returns an explicit `served_result`. Its
  settings reject personalization and background-refresh bindings.
- The qualification matrix freezes the two Zigong public questions, separates
  taste constraints from shared identity, covers deterministic/trigram/vector
  hits and low-confidence no-merge, and links the Temporal replay/worker restart
  qualification cases with explicit refresh and pointer rollback gates.
- The fixed `bge_m3_profile_v1.json` fixture pins the 1024-dimensional cosine
  profile and vector hash. Alembic 0005 emits the profile-aware HNSW
  `vector_cosine_ops` index; model/profile mismatches fail before candidate
  writes, while vector-disabled reads retain deterministic/trigram behavior.
- Failure injection covers candidate Evidence write, feature/index derivation,
  derivation receipt write, and final activation CAS. Each failure leaves the
  prior Bundle pointer unchanged and keeps failed candidates off the read path.
- Explicit refresh tests prove unauthorized force mode stops before the claim
  or any connector boundary, while compatible requests reuse one stable
  Temporal workflow, task ID, and accepted event ID.
- `qualify_b2_observations` evaluates a privacy-preserving fixed sample for
  exact result equivalence, per-layer recall, P95 latency, source-request
  reduction, and error classification. An owner approval is bound to the
  exact observation/threshold digest; missing, rejected, or mismatched approval
  is blocked rather than inferred.
- `BundleLifecycleService.restore_pointer` performs a conditional dual-pointer
  restore to an older Bundle/profile and rejects non-older targets before any
  repository call. The B2 rollback runbook keeps immutable data and Temporal
  history and turns the read path back to legacy.

## Qualification commands

Offline contract and service tests:

```powershell
uv run --frozen pytest -q tests/test_unit_b2_query_reuse.py tests/test_unit_b1_schema_and_embeddings.py tests/test_unit_b1_embedding_shadow.py
uv run --frozen pytest -q tests/test_unit_b2_bundle_refresh.py
uv run --frozen pytest -q tests/test_unit_b2_query_reuse_read.py
uv run --frozen pytest -q tests/test_unit_b2_qualification_matrix.py
uv run --frozen pytest -q tests/test_unit_b2_profile_fixture.py
uv run --frozen pytest -q tests/test_unit_b2_qualification_gate.py
uv run --frozen pytest -q tests/test_unit_b2_rollback.py tests/test_unit_b2_bundle_lifecycle.py
```

Live PostgreSQL/pgvector/pg_trgm test:

```powershell
$env:B2_POSTGRES_URL = "postgresql+asyncpg://POSTGRES_TEST_URL"
uv run --frozen pytest -q -m live tests/test_live_b2_query_reuse.py -vv -s --tb=short
```

Observed on 2026-08-24 with PostgreSQL 16.14 and pgvector:

- offline B2/B1 subset: `51 passed` (including Bundle lifecycle, refresh,
  delta derivation/pointer failure, read shadow/canary, qualification matrix,
  profile/index, and failure-injection gates)
- live B2 repository qualification: `1 passed in 6.40s`
- Alembic head resolves through `20260824_0005_b2_derivations`; additive 0005
  upgrade was rerun against the local PostgreSQL 16 + pgvector fixture and the
  live B2 repository qualification passed again: `1 passed in 6.02s` on
  2026-08-24. The migration was applied with `DATABASE_URL` set only in the
  local process and no credential was committed.
- `uv lock --check`: passed
- targeted Ruff check: passed

Target-stack local qualification on 2026-08-25:

- the release Compose stack was healthy with PostgreSQL `16.14`, `pg_trgm 1.6`,
  `vector 0.8.2`, Redis `7.4.9`, Temporal `1.28.2`, and MinIO;
- an isolated CPython `3.12.12` runner joined the Compose network and ran
  `tests/test_live_b2_query_reuse.py` against the PostgreSQL service:
  `1 passed in 15.34s`;
- the same target runner was repeated on 2026-08-26 after rebuilding the
  current working-tree image and re-installing the frozen lockfile; the live
  PostgreSQL/pgvector/pg_trgm CAS qualification passed:
  `1 passed in 88.60s` (cold dependency installation included);
- the same runner, with `DATABASE_URL`, Redis, Temporal, and deterministic
  provider fakes exercised by the suite, ran the CI backend command:
  `961 passed, 24 deselected, 2 warnings in 242.58s`.

This is target-stack local evidence for repository connectivity and the backend
contract suite. It does not measure a production traffic sample, exercise a
deployed model provider, or constitute the owner-approved B2 canary.

Offline B2 qualification fixture (2026-08-24): `pass`; result equivalence,
deterministic/trigram/vector recall, P95 latency, source-request reduction,
and error-classification gates all passed with approval
`b2-fixture-canary-20260824`. This approval is explicitly scoped to the fixed
fixture and does not approve a production canary.

The fail-closed evaluator is available for reviewable observation digests:

```powershell
uv run --frozen python scripts/qualification_b2_canary.py `
  tests/fixtures/authority/b2_qualification_v1.json `
  --output b2-canary-report.json
```

It returns exit `0` for a passing approved sample, `1` for failed thresholds,
and `2` for blocked input (including missing/rejected approval). Passing a
fixture approval through `--require-production-scope` remains blocked because
its scope is not `production/`; a production canary must provide a separate
owner approval bound to the exact observation and threshold digest. The CLI
accepts digests and aggregate measurements only; it does not collect traffic
or expose user-level observations.

The target-stack 10.12 gate remains `BLOCKED`: the local repository smoke and
backend contract suite now pass, but PostgreSQL 16 + pg_trgm + pgvector
recall/latency measurements across the approved sample, source-request
reduction from sampled legacy traffic, and owner-approved threshold values for
OQ-6/OQ-7 have not been captured. The evaluator fails closed when this approval
is absent or its input digest changes.

Task 10.13 rollback qualification: `PASS (offline)`. Read reuse defaults to
`off`, the explicit refresh service remains unbound from the current HTTP
surface, and the runbook's conditional Bundle/profile restore is covered by
unit tests. No Bundle, profile row, or Temporal history is deleted.

## Deliberate non-claims

Task 10.12 remains pending until the target-stack gate and canary approval are
complete. This milestone does not activate query reuse reads, background
refresh scheduling, personalization, or an external refresh API. Temporal
worker crash replay and production canary gates remain part of the later B2
tasks. Task 10.13's rollback path is qualified but leaves all B2 bindings
disabled.
