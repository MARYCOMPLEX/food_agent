# Implementation Verification

This record covers the code and local qualification evidence for
`enable-evidence-reuse-memory-phoenix`. It does not grant an external serving
approval. B1/B2/B3 remain non-serving until their owner gates are recorded.

## Revision and scope

| Item | Value |
| --- | --- |
| Working branch | `codex/integrate-platform-source-connectors` |
| Pre-change base | `71bdb66c3b08db940e20451b39539fb20776339b` |
| Schema head in this change | `20260905_0012_b1_source_batches` |
| Qualification image | `xhs-food-agent:qualification` (`sha256:9cd4eb3b06ec0374f6cc97106171780aa9bcc283fcb46e9446ad58e94bafd349`) |
| Architecture baseline | `define-modular-architecture` unchanged and strict-valid |
| Business authority | PostgreSQL facts; Temporal recovery history; Redis rebuildable projection |
| Observation authority | Repository-owned records; Phoenix receives a projection only |

## Local commands

The following commands were run against the current working tree:

| Command | Result |
| --- | --- |
| `.venv-win\\Scripts\\pytest.exe -q -m "not live" --tb=short -ra` | `1127 passed, 25 deselected, 2 warnings` |
| Complete focused B1/B2/B3/Phoenix/schema/qualification unit files (40 files) | `253 passed` |
| `uv lock --check` | pass |
| Clean locked dev install (`uv sync --frozen --extra dev`, isolated `.qa-venv`) | pass; 116 locked packages installed |
| Targeted Ruff over changed runtime and test paths | pass (`All checks passed!`) |
| Targeted Pyright for new contracts, telemetry, evaluation, Phoenix, and binding modules using the clean locked environment | `0 errors, 0 warnings` |
| `openspec validate enable-evidence-reuse-memory-phoenix --strict` | pass |
| `openspec validate define-modular-architecture --strict` | pass |
| `git diff --check` | pass (only Git line-ending notices) |
| `docker compose -f docker-compose.release.yml config --quiet` | pass |
| `docker compose -f docker-compose.release.yml --profile phoenix config --quiet` | pass |
| `docker compose -p food-agent-qualification -f docker-compose.release.yml -f docker-compose.qualification.yml config --quiet` | pass; overlay ports replace release ports |
| `docker compose -p food-agent-qualification -f docker-compose.release.yml -f docker-compose.qualification.yml --profile phoenix config --quiet` | pass |
| `docker compose -p food-agent-qualification ... exec app alembic current` | `20260905_0012_b1_source_batches (head)` |

The repository-wide Ruff/Pyright reports remain non-gating legacy baselines;
they include pre-existing service typing/import issues. The change-specific
checks above use the locked Windows environment and are the release evidence
for the new modules.

## Compose qualification matrix

The current worktree image was built with `Dockerfile.release` and
`uv sync --no-dev --frozen`. The isolated project name was
`food-agent-qualification`; the existing `food-agent-release-gate` project was
left running and was not used as evidence for this change.

| Scenario | Result |
| --- | --- |
| Current image build | pass; image digest recorded above |
| Default profile startup with `up -d --wait` | pass |
| PostgreSQL, Redis, Temporal, and MinIO health checks | pass |
| Alembic migration and current head | pass; migration container exit `0` |
| App `/health` and `/metrics` | HTTP `200` / HTTP `200` |
| Research, refresh, and media queue smoke containers | all exit `0` |
| App restart, PostgreSQL restart, Redis restart | pass; app health HTTP `200` after each |
| Temporal restart followed by research queue smoke | pass; app health HTTP `200` |
| Phoenix profile image/service startup | blocked: the pinned Phoenix image pull hit a Docker Hub TLS handshake timeout; no ingestion claim is made |

The qualification overlay uses Compose `!override` port lists so it cannot
retain the release project's host ports. Phoenix's fixed observability network
is intentionally separate from the business default network; the business
health check does not depend on Phoenix.

## Live qualification probes

The available live probe suite was run against the SDK's ephemeral
time-skipping Temporal test server (no external provider credentials or
production services):

```powershell
.venv-win\\Scripts\\pytest.exe -q -m live tests/test_temporal_qualification.py -ra --durations=0 --tb=short
```

Result: `9 passed in 119.12s`. This proves the local replay/retry/cancel,
worker restart, model/tool Activity, duplicate commit, and authoritative
cancellation paths. It is not external owner/release approval and does not
qualify B1/B2/B3 serving gates.

## Schema and rollback notes

The migration chain is additive and linear:

```text
20260904_0010_shop_profile
  -> 20260905_0011_b2_freshness_watermark
  -> 20260905_0012_b1_source_batches
```

`0011` adds only `query_family_freshness.watermark_advanced`. `0012` adds
source-batch provenance tables and indexes. Clean, N-1, current, and divergent
fixtures are probed before deployment; divergent state stops without applying
DDL. Downgrade is an explicit rollback drill: it removes only the corresponding
additive revision and never deletes legacy tables or published business data.

Recommended deployment evidence commands:

```powershell
uv lock --check
uv sync --frozen --extra dev --python 3.12
uv run --frozen alembic current
uv run --frozen alembic upgrade head
uv run --frozen pytest -q tests/test_unit_schema_authority_state.py
```

## Configuration snapshot

The safe baseline is:

```text
MODULAR_EVIDENCE_SHADOW_ENABLED=false
MODULAR_EVIDENCE_SHADOW_SAMPLE_RATE=0
MODULAR_EVIDENCE_SHADOW_WRITE_BUDGET=0
MODULAR_QUERY_REUSE_READ_MODE=off
MODULAR_QUERY_REUSE_READ_SAMPLE_RATE=0
MODULAR_QUERY_REUSE_B1_GATE_APPROVED=false
MODULAR_PERSONALIZATION_CANARY_MODE=off
MODULAR_PERSONALIZATION_CANARY_SAMPLE_RATE=0
MODULAR_OTEL_ENABLED=false
MODULAR_PHOENIX_ENABLED=false
```

Phoenix can be enabled independently only with a bounded OTLP endpoint and a
separate observability database. It never changes business health or request
success semantics.

## Gate status

| Gate | Local evidence | Release status |
| --- | --- | --- |
| B1 shadow qualification window | deterministic/unit/failure tests pass; no production window or owner report | blocked |
| B2 shadow and canary | repository/read/CAS/fallback tests pass; no approved canary observation window | blocked |
| B3 shadow and canary | authority/scope/Redis/canary tests pass; no post-B2 owner gate | blocked |
| Phoenix backend | redaction/queue/API/evaluation tests pass; pinned image pull blocked in this environment | blocked for serving, optional for diagnostics |
| Local integration/restart matrix | current image, migration, dependency health, queue smoke, and restart checks pass | local pass; not a serving approval |
| External owner/release approval | not present in repository | blocked |

## Rollback commands

Use one configuration switch per capability; do not delete immutable rows:

```powershell
$env:MODULAR_PERSONALIZATION_CANARY_MODE = "off"
$env:MODULAR_QUERY_REUSE_READ_MODE = "off"
$env:MODULAR_EVIDENCE_SHADOW_ENABLED = "false"
$env:MODULAR_OTEL_ENABLED = "false"
docker compose -f docker-compose.release.yml --profile phoenix down
```

The independent rollback switches route reads back to the legacy reader,
public ranking, and legacy connector behavior while retaining candidate
Evidence, Query Family, Bundle, Memory, and evaluation history for audit.

## Secrets and scope review

No credential, cookie, QR payload, provider token, or API key is present in the
tracked change. `.env` remains local-only and is not included in the release
commit. Compose qualification uses local fixture credentials only; deployment
must inject `TOKEN`/secret references through the environment or secret store.
