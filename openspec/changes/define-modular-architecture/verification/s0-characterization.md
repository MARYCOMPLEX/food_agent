# S0 Characterization Verification

Date: 2026-08-19

## Scope

S0 freezes the observable legacy behavior before structural migration. It adds
tests, deterministic fixtures, and test tooling only; it does not change files
under `src/`, frontend runtime source, database migrations, or deployment
manifests.

The baseline covers:

- FastAPI OpenAPI and search/auxiliary/identity HTTP behavior.
- SSE bytes, ordering, replay, terminal events, and legacy state behavior.
- Food search phases, stopping, deduplication, ranking, follow-up, DTOs, and hashes.
- Python exports, constructor injection, MCP registrations, and result envelopes.
- Memory, Redis, EventBus, PostgreSQL/pgvector, and startup fallback behavior.
- Clean/pre-`turn_id`/post-`turn_id` schema and repository combinations.
- Settings, LLM adapters, Node signer, Docker, Compose, and README deployment facts.
- Separate server, frontend, and documentation consumer assumptions.

## Offline CI Baseline

Non-live tests use frozen source, model, time, HTTP, SSE, and database fixtures.
The autouse guard in `tests/conftest.py` rejects non-loopback DNS resolution and
socket connections for every test not marked `live`; localhost Redis/PostgreSQL
service containers remain available to integration jobs.

Command:

```powershell
uv run --frozen pytest -q -m "unit or integration"
```

Result on the Python 3.12 blocking runtime:

```text
196 passed, 5 deselected, 2 warnings in 5.01s
```

The five deselected cases are explicitly marked `live`. The two warnings are
pre-existing `PytestReturnNotNoneWarning` results in `tests/test_session.py` and
do not hide failed assertions.

## Intentionally Uncovered

- Live XHS, POI, browser login, and LLM provider calls requiring credentials.
- Real-browser frontend workflows and SSE reconnection behavior.
- Real PostgreSQL migration execution and Redis multi-process timing; S0 uses
  replayable contract fakes for these legacy states.
- Linux container build/runtime and non-Windows platform probes.
- Target Temporal, S3/MinIO, Query Family, Evidence, and Personalization behavior,
  which belongs to later structural or behavioral milestones.
- Resolution of the route/envelope/SSE/DTO authority conflicts tracked by tasks
  1.3-1.6. S0 preserves each conflicting producer/consumer claim independently.

## Fixture Update Rules

1. Never auto-regenerate or accept snapshots solely to make a failing test pass.
2. Link every fixture change to an approved compatibility/authority decision or
   an intentional production behavior change in OpenSpec.
3. Regenerate OpenAPI with the locked Python 3.12 environment, inspect the
   semantic diff, and update its HTTP golden expectations in the same commit.
4. Update SSE byte fixtures and replay/state assertions together; retain exact
   event IDs, field names, separators, ordering, heartbeat, and terminal bytes.
5. Keep server facts, frontend assumptions, and README claims as separate fixture
   sections until the relevant authority decision is accepted.
6. Keep clocks, provider responses, identities, Unicode, database rows, and
   hashes deterministic. Characterization suites must not gain live I/O.
7. Require reviewer approval for any fixture diff and record whether it is a
   compatibility change, an intentional defect fix, or fixture-only correction.

## Revert Drill

Commit `4686b6c` was checked out in a temporary detached worktree and reverted
as commit `f4f4847`. The revert removed all 30 S0 test, fixture, and verification
assets. The tree comparison from the S0 parent to the reverted worktree was
empty for `src/`, `frontend/`, `pyproject.toml`, `uv.lock`, `Dockerfile`, and
`docker-compose.yml`; no production behavior or deployment asset was changed.
