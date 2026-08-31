# Platform Connector Qualification Record

**Repository fixture:** `C:\Users\14158\Documents\ChatGPT\fagent\food_agent`
**Branch at record time:** `codex/integrate-platform-source-connectors`
**Change:** `integrate-platform-source-connectors`
**Record type:** reproducible qualification evidence (not a production approval)
**Recorded:** 2026-08-31 (Asia/Shanghai)
**Current decision:** local contract qualification is available; production and
commercial activation remain gated on owner/legal approval, reviewed dependency
digests, and an owner-approved canary.

This record is deliberately split into **implemented local evidence** and
**release evidence still required**. A green unit result never changes the
license/provenance gate. No credentials, cookies, QR bytes, signer inputs, or
raw provider account state belong in this file.

## 1. Pinned input set

| Provider | Snapshot | Adapter surface | Intake record |
|---|---|---|---|
| Dianping | `MARYCOMPLEX/dazhongdianping` @ `ffbc1d413ed1c83602212bc1fec12b57cd2b423d` | auth, QR, search, detail, reviews protocol modules | [`references/provider-import-allowlist.yaml`](../references/provider-import-allowlist.yaml) |
| Spider_XHS | `cv-cat/Spider_XHS` @ `e1888d712519040f5fcc294baeac4b9505b25c98` | PC/Creator auth and read protocol modules | [`references/provider-import-allowlist.yaml`](../references/provider-import-allowlist.yaml) |

Archive and dependency-manifest digests are recorded in
[`upstream-provenance.md`](upstream-provenance.md). A changed SHA, archive
format, dependency manifest, or signer asset starts a new intake revision and
connector version.

## 2. Gate summary

The OpenSpec task checklist is the closure authority. At this record point
(`openspec/changes/integrate-platform-source-connectors/tasks.md` on branch
`codex/integrate-platform-source-connectors`) the following tasks have local
implementation/contract evidence: **1.1–1.5, 2.1–2.4, 3.1–3.7, 4.2–4.4,
2.5–2.6, 4.1, 4.5, 5.1, 5.3–5.6, 6.1–6.6, 7.1, and 7.5–7.7**. A checked task here means that its project-owned
boundary and synthetic/unit behavior are implemented; it does **not** mean
that a provider account, target stack, signer sandbox, legal approval, or
production canary has passed. Tasks whose wording requires those external or
broader failure-injection observations remain unchecked until their evidence
is attached.

| Gate | Evidence | Status | Activation meaning |
|---|---|---:|---|
| I0 provenance/import boundary | pinned commits, allow-list, license report, secret-free fixtures, AST import scan | **PASS (local)** | adapters may be tested against synthetic inputs |
| I1 account authority | Pydantic contracts, AES-GCM test provider, repository compile/CAS tests, additive Alembic revision, schema-authority scan, concurrent channel/tenant/CAS/lease tests, and full boundary-redaction matrix | **PASS (2.1–2.6 local)** / **PENDING (database probe)** | clean/N-1/rollback PostgreSQL probes (2.7) remain open |
| I2 login control plane | split-phase flow state machine, ObjectStore QR cleanup, Temporal activity redaction and atomic signal-with-start cancellation tests, `/v1/platform/*` redacted API, deterministic flow replay, Redis-projection loss, worker replacement, provider challenge/risk/timeout, cancellation-race, stale-poll, and orphan-cleanup injection tests | **PASS (3.1–3.7 local)** / **PENDING (stack)** | target auth-queue service qualification and provider-account observations remain open |
| I3 Dianping adapter | injected activity-local provider factory, temporary storage-state cleanup, concurrent context isolation, canonical search/detail/review/media mapping, URL safety, and failure taxonomy | **PASS (4.1–4.5 local)** / **PENDING (provider probe)** | owner-approved disposable-account probe (4.6) remains open |
| I4 XHS PC/Creator adapter | injected channel-separated factory, QR/risk/cancel/restart matrix, tuple normalization, URL redaction, Creator read-only boundary, stable error mapping, and concurrent PC/Creator account tests | **PASS (5.1, 5.3–5.6 local)** / **PENDING (signer)** | signer sandbox/hash/resource evidence (5.2) remains open |
| I5 gateway/composition | grant-before-provider, PG lease/CAS boundary, capability collision, feature-gated readiness, ObjectStore gate, legacy/new differential equivalence, cursor/cancel/timeout budgets, and query-identity preservation | **PASS (6.1–6.6 local)** | target-stack execution remains separately gated |
| I6 target stack | full non-live suite plus PostgreSQL/Alembic + Redis + Temporal + S3/MinIO restart/replay matrix | **PASS (7.1 local)** / **PENDING (7.2–7.3 stack/security)** | Docker Desktop daemon was unavailable during this record; target-stack and signer evidence are required before canary |
| Owner canary | selected tenant/account differential comparison and aggregate metrics | **BLOCKED — approval required** | required before production/commercial traffic |

`PARTIAL (... local)` means the named project-owned seams have focused
code/tests, while the listed independent or external observations remain open.
`PASS (local)` and `PASS (unit)` mean the behavior is covered without an
external provider account; neither asserts provider availability,
terms-of-use permission, or production capacity.

## 3. Reproduce local qualification

Run from the repository root with the locked environment. On Windows, the
local qualification environment used for this record was `.venv-win`.

```powershell
$env:PYTHONPATH = "src"
uv lock --check
.\.venv-win\Scripts\python.exe -m ruff check src tests
.\.venv-win\Scripts\python.exe -m pytest -q `
  tests/test_platform_connector_intake.py `
  tests/test_unit_platform_account_authority.py `
  tests/test_unit_platform_account_contracts.py `
  tests/test_unit_platform_account_repository.py `
  tests/test_unit_platform_account_schema.py `
  tests/test_unit_platform_adapters.py `
  tests/test_unit_platform_gateway.py `
  tests/test_unit_platform_gateway_matrix.py `
  tests/test_unit_platform_secret_boundaries.py `
  tests/test_unit_platform_login.py `
  tests/test_unit_platform_login_service_workflow.py `
  tests/test_unit_platform_login_temporal.py `
  tests/test_unit_platform_login_api.py `
  tests/test_unit_platform_lifespan_wiring.py `
  tests/test_unit_platform_sources.py `
  tests/test_unit_composition_platform_bindings.py `
  tests/test_unit_temporal_account_auth_queue.py `
  tests/test_unit_temporal_platform_cancel.py `
  tests/test_unit_xhs_login_provider_bridge.py
openspec validate integrate-platform-source-connectors --strict
git diff --check
```

The schema-authority probe is also part of the release evidence:

```powershell
.\.venv-win\Scripts\python.exe scripts\qualification_schema_authority.py `
  --root . `
  --output .state\schema-authority-RUN_ID.json
```

It scans application source files only and skips local virtual environments
(`.venv`, `.venv-win`, `.venv-auth`), bytecode, tests, and the Alembic directory.
The explicitly allow-listed legacy SQLite request-log telemetry finding is
classified separately; an unexpected PostgreSQL DDL finding is a release stop.

The recorded focused run covered the intake, account, adapter, gateway,
login, source, architecture, queue, XHS auth bridge, and composition paths:

```
151 passed in 11.76s
```

The same run used CPython 3.12.0 from `.venv-win`, `uv.lock` SHA-256
`8301F2B046290C4E65A8FFDACAFCE7844D1F8DA6E414DF003809E161931CCCFF`, and the
exact test selection shown above. Targeted Ruff, `uv lock --check`, OpenSpec
strict validation, and `git diff --check` were green after the import cleanup
in `tests/test_unit_platform_gateway.py`. The complete non-live repository
suite was also executed with the exact command below:

```powershell
.\.venv-win\Scripts\python.exe -m pytest -q
```

It recorded `1158 passed, 10 skipped, 5 warnings in 172.52s`; the enclosing
PowerShell stopwatch recorded `177.55s`. The five warnings are the existing
`PytestReturnNotNoneWarning` observations in `tests/test_config.py` and
`tests/test_session.py`, not platform-connector failures. This is a local working-tree
observation, not an independent release commit. Re-run output must still be
attached to release evidence with the exact interpreter, lockfile digest,
commit, and test selection; a copied summary is not evidence.

### Required local assertions

1. `test_application_source_has_no_upstream_runtime_imports` remains empty.
2. All fixture JSON files are `/v1` JSON-safe and secret-free.
3. An unauthorized grant returns before a provider factory is called.
4. Two accounts with the same alias but different tenant/channel have
   independent lease and session keys.
5. A stale session writer loses CAS and leaves the active version unchanged.
6. PC and Creator connectors serialize their own mutable clients and never
   share a signer/profile.
7. Missing checkout, authority, codec, provenance, license approval, auth
   queue, or ObjectStore produces a redacted `dependency-unavailable`/`disabled`
   readiness state; it never silently selects a new provider. The ObjectStore
   assertion is structural in this local run (`put`/`delete` capability); a
   live backend health/retention probe is still required.
8. Capability collisions require explicit source/version selection; legacy
   `xhs_compat` and Amap compatibility registrations remain intact.

### Local task evidence map

The checked implementation tasks are backed by the following focused tests.
The map is intentionally explicit so a future reviewer can distinguish a
synthetic contract result from a target-stack or owner-approved observation.

| Task group | Local implementation evidence |
|---|---|
| 2.1–2.6 | `test_unit_platform_account_contracts.py`, `test_unit_platform_account_authority.py`, `test_unit_platform_account_repository.py`, `test_unit_platform_account_schema.py`, `test_unit_platform_secret_boundaries.py`, `test_unit_platform_gateway_matrix.py` |
| 3.1–3.7 | `test_unit_platform_login.py`, `test_unit_platform_login_service_workflow.py`, `test_unit_platform_login_temporal.py`, `test_unit_temporal_platform_cancel.py`, `test_unit_temporal_account_auth_queue.py`, `test_unit_platform_login_api.py`, `test_unit_platform_lifespan_wiring.py`, `test_unit_composition_platform_bindings.py` |
| 4.1–4.5 | `test_unit_platform_adapters.py`, `test_unit_platform_sources.py`, `test_unit_platform_gateway_matrix.py` (injected factory lifecycle, concurrent storage-state isolation, missing-session short circuit, mapping, pagination, media, URL safety, and failure taxonomy) |
| 5.1 | `test_unit_platform_adapters.py`, `test_unit_platform_sources.py`, `test_unit_xhs_login_provider_bridge.py` (channel-separated factories, mutable-client serialization, and namespace/state isolation) |
| 5.3–5.6 | `test_unit_platform_sources.py`, `test_unit_platform_adapters.py`, `test_unit_xhs_login_provider_bridge.py`, `test_unit_platform_gateway_matrix.py` |
| 6.1–6.6 | `test_unit_platform_gateway.py`, `test_unit_platform_gateway_matrix.py`, `test_unit_composition_platform_bindings.py`, `test_unit_platform_lifespan_wiring.py` |
| 7.1 | complete non-live `pytest -q` result above; focused 151-test platform matrix; `uv.lock` digest recorded above |
| 7.5 | `platform-rollout-runbook.md` (registration, re-auth, QR expiry, quarantine, lease/queue/sidecar recovery, retry/terminate, and rollback procedure) |
| 7.6 | `test_unit_composition_platform_bindings.py::test_flag_rollback_keeps_encrypted_authority_and_pinned_inflight_binding` plus cancellation/lease cleanup in `test_unit_platform_gateway_matrix.py` |
| 7.7 | `platform-integration-architecture.svg` and `.html`, `architecture-module-catalog.md`, `upstream-provenance.md`, `compatibility-ledger.md`, this qualification record, strict OpenSpec validation, and the independent commit/push recorded in repository history |

The following are deliberately **not** represented as passed by this table:
PostgreSQL live contention/migration probes, Redis/Temporal/ObjectStore
restart tests, signer sandbox and dependency/license review, disposable-account
probes, production traffic comparison, and canary approval. They remain the open
tasks listed in `tasks.md`.

## 4. Target-stack qualification matrix

The following matrix is the release run to perform in an isolated Compose
project. Replace `TARGET`, `HOST`, `PORT`, `TOKEN`, and account references with
deployment-owned values; do not paste them into this document.

| Component | Probe | Required observation | Evidence artifact |
|---|---|---|---|
| PostgreSQL 16 + pgvector/pg_trgm | `docker compose -f docker-compose.release.yml up -d postgres migrate` then `alembic current` | migration exits 0; all account tables/columns/extensions present; no runtime DDL | `postgres-schema-<RUN_ID>.json` |
| Redis 7 | `redis-cli -h HOST -p PORT ping` and restart projection consumer | hot status/SSE replay resumes or reports bounded replay expiry; no lease rows in Redis | `redis-hot-state-<RUN_ID>.json` |
| Temporal | start research/refresh/media workers and optional `account-auth` worker | queue names are distinct; bounded retry/heartbeat; worker restart/replay is deterministic | `temporal-queues-<RUN_ID>.json` |
| S3/MinIO | health probe, put/get/delete a synthetic QR/media object | content policy, short QR retention, orphan cleanup, signed reference redaction | `object-store-<RUN_ID>.json` |
| FastAPI | `GET /health`, `GET /metrics`, synthetic `/v1/search` | app reports dependency state; no provider secret in response/log/metric | `api-health-<RUN_ID>.json` |
| Provider adapters | injected synthetic checkout or owner-approved disposable account | bounded pagination, canonical IDs/URLs, stable error category, clean shutdown | `connector-probe-<RUN_ID>.json` |

The release Compose manifest starts the `migrate` job before the app. The
application performs read-only schema readiness checks; it does not create or
repair tables. The default `docker-compose.yml` remains a legacy/dev fixture
and must not be interpreted as production approval.

The local host probe `docker version --format '{{json .Server.Version}}'`
returned exit code `1` with `failed to connect to the docker API at
npipe:////./pipe/dockerDesktopLinuxEngine`; therefore tasks 2.7 and 7.2 were
left unchecked rather than converting structural/unit evidence into a live
PostgreSQL or target-stack claim.

## 5. Differential canary record

The canary compares the legacy connector and the new versioned binding for the
same **public** request while keeping account/session references separate from
the Query Family identity. Capture aggregate data only:

```json
{
  "run_id": "RUN_ID",
  "connector_version": "dianping-platform/v1|xhs-platform/v1",
  "provider_commit": "PINNED_SHA",
  "dependency_digest": "SHA256",
  "tenant_bucket": "TENANT_BUCKET",
  "account_bucket": "ACCOUNT_BUCKET",
  "sample_count": 0,
  "result_equivalence": 0.0,
  "p95_latency_ms": 0.0,
  "coverage_rate": 0.0,
  "request_volume_reduction": 0.0,
  "error_classification_accuracy": 0.0,
  "auth_or_risk_rate": 0.0,
  "partial_item_rate": 0.0,
  "secret_scan_findings": 0,
  "approval_ref": "OWNER_APPROVAL_REF",
  "input_digest": "SHA256_OF_REDACTED_INPUT",
  "observed_at": "2026-08-31T00:00:00Z"
}
```

The redacted aggregate must be generated from an immutable input and include
the exact command, environment image digest, and reviewer. A fixture run may
exercise the schema but must be labeled `scope=local-fixture`; it cannot be
promoted to `scope=production-canary` by editing a field.

### Canary exit criteria (owner-configured)

- `result_equivalence >= RESULT_EQUIVALENCE_MIN`
- `coverage_rate >= COVERAGE_MIN`
- `p95_latency_ms <= P95_MAX_MS`
- `request_volume_reduction >= REQUEST_REDUCTION_MIN` (if applicable)
- `error_classification_accuracy >= ERROR_CLASSIFICATION_MIN`
- `secret_scan_findings == 0`
- auth/risk and rate-limit rates stay within the approved budget
- no cross-tenant/channel isolation, lease, CAS, or replay violation

Thresholds are release inputs, not hard-coded provider assumptions. The owner
must sign the values and the sampled tenant/account cohort before enabling a
canary flag.

## 6. Stop conditions and recovery

Immediately stop the canary and set the affected platform flag to `false` on:

- any secret-bearing log, trace, Temporal payload, SSE event, evidence field,
  object metadata, or provider exception;
- a cross-tenant or cross-channel account/session lookup;
- a stale session CAS overwrite or simultaneous mutable client for one lease;
- an unbounded retry, queue crossover, provider process leak, or signer drift;
- a schema readiness failure, unknown/unreviewed dependency, or license gate
  mismatch;
- canonical URL output containing access-bearing query parameters.

Rollback is configuration-only: stop new provider Activities, let pinned
in-flight Temporal runs finish or fail, revoke/release leases, and route new
requests to the previous connector. Retain encrypted account rows, Evidence,
and Temporal history; do not rewrite public pointers or perform destructive
migrations. The detailed sequence is in
[`platform-rollout-runbook.md`](platform-rollout-runbook.md).

## 7. Sign-off block

| Role | Name / reference | Date | Decision |
|---|---|---|---|
| Engineering owner | `OWNER_ENGINEERING_REF` | `YYYY-MM-DD` | unit/stack evidence accepted |
| Security owner | `OWNER_SECURITY_REF` | `YYYY-MM-DD` | secret/redaction/signer evidence accepted |
| Legal/licensing owner | `OWNER_LEGAL_REF` | `YYYY-MM-DD` | permitted use and notices accepted |
| Release owner | `OWNER_RELEASE_REF` | `YYYY-MM-DD` | canary cohort and thresholds approved |

Until all required sign-offs and target-stack artifacts are attached, the
provenance manifest remains `license_status: unknown` and production bindings
remain disabled.
