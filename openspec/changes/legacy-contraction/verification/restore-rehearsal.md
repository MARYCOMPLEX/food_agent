# Legacy Contraction Restore Rehearsal

Status: **PASS for restore prerequisite; removal remains blocked**

Recorded: `2026-08-25` on the local release Compose stack
(`PostgreSQL 16 + pgvector/pg_trgm`, Temporal `1.28.2`). The rehearsal used
disposable databases only and did not modify `xhs_food_agent`.

## Clean, Downgrade, And Re-Upgrade

The pre-baseline head used by the rehearsal was
`20260824_0007_b3_personalization_memory`; the current head after the legacy
schema adoption is `20260825_0008_legacy_schema`.

Disposable database: `legacy_contraction_rehearsal_20260825`

```powershell
docker compose -f docker-compose.release.yml -p food-agent-release-gate exec -T postgres createdb -U postgres legacy_contraction_rehearsal_20260825
docker compose -f docker-compose.release.yml -p food-agent-release-gate run --rm --no-deps -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/legacy_contraction_rehearsal_20260825 migrate
docker compose -f docker-compose.release.yml -p food-agent-release-gate run --rm --no-deps -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/legacy_contraction_rehearsal_20260825 app alembic downgrade base
docker compose -f docker-compose.release.yml -p food-agent-release-gate run --rm --no-deps -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/legacy_contraction_rehearsal_20260825 app alembic upgrade head
```

Observed result:

- clean `upgrade head`: revisions `0001` through `0008` completed;
- `downgrade base`: all seven revisions downgraded transactionally;
- second `upgrade head`: all seven revisions completed again.

## N-1 Upgrade

Disposable database: `legacy_contraction_n1_20260825`

```powershell
docker compose -f docker-compose.release.yml -p food-agent-release-gate exec -T postgres createdb -U postgres legacy_contraction_n1_20260825
docker compose -f docker-compose.release.yml -p food-agent-release-gate run --rm --no-deps -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/legacy_contraction_n1_20260825 app alembic upgrade 20260824_0001_b1_shadow
docker compose -f docker-compose.release.yml -p food-agent-release-gate run --rm --no-deps -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/legacy_contraction_n1_20260825 app alembic upgrade head
docker compose -f docker-compose.release.yml -p food-agent-release-gate exec -T postgres psql -U postgres -d legacy_contraction_n1_20260825 -Atc "SELECT version_num FROM alembic_version; SELECT count(*) FROM pg_tables WHERE schemaname='public';"
```

Observed output:

```text
20260825_0008_legacy_schema
32
```

## Dump And Restore

The clean rehearsal database was dumped in custom format and restored into a
second disposable database:

```powershell
docker compose -f docker-compose.release.yml -p food-agent-release-gate exec -T postgres createdb -U postgres legacy_contraction_restore_20260825
docker compose -f docker-compose.release.yml -p food-agent-release-gate exec -T postgres sh -lc "pg_dump -U postgres -Fc --no-owner --no-privileges -d legacy_contraction_rehearsal_20260825 -f /tmp/legacy_contraction_20260825.dump && pg_restore -U postgres --no-owner --no-privileges -d legacy_contraction_restore_20260825 /tmp/legacy_contraction_20260825.dump"
docker compose -f docker-compose.release.yml -p food-agent-release-gate exec -T postgres psql -U postgres -d legacy_contraction_restore_20260825 -Atc "SELECT version_num FROM alembic_version; SELECT extname FROM pg_extension WHERE extname IN ('vector','pg_trgm') ORDER BY extname; SELECT count(*) FROM pg_tables WHERE schemaname='public';"
```

Observed output:

```text
20260825_0008_legacy_schema
pg_trgm
vector
32
```

## Temporal History Replay And Operator Recovery

The same release stack ran the disposable Temporal qualification probe:

```powershell
$env:TEMPORAL_ADDRESS = "127.0.0.1:17233"
uv run --frozen python scripts/qualification_temporal_release_matrix.py
```

Observed result:

```text
temporal release matrix: PASS address=127.0.0.1:17233 queues=research,refresh,media worker_rollout=PASS retry_exhaustion=PASS operator_retry=PASS
```

This proves the retained Temporal history can be handed to a replacement
worker and that a failed execution can be located and retried. It does not
prove that an external production deployment has no old consumers.

## Schema Authority Preflight

The repository-local AST probe is the repeatable 14.7 source scan:

```powershell
uv run --frozen python scripts/qualification_schema_authority.py
```

Observed on 2026-08-25:

```text
schemaVersion: schema-authority-probe/v1
status: pass
unexpectedFindings: []
legacyFindings: 0
telemetryFindings: 1 explicitly classified SQLite request-log source
```

Exit code `0` is expected because no PostgreSQL runtime DDL remains. The probe
covers literal SQL, string concatenation, and f-string SQL fragments. An
unregistered runtime DDL source returns exit `1`; the SQLite request-log table
is reported separately as local telemetry. The probe excludes Alembic, tests,
and virtual environments and does not modify source code or database state.
Hosted CI run
[`32849665982`](https://github.com/MARYCOMPLEX/food_agent/actions/runs/32849665982)
at commit `803bbaa` executed the same preflight and uploaded the JSON report.

## Gate Interpretation And Cleanup

Runtime DDL paths are retained only as compatibility inventory entries; the
PostgreSQL implementations are now read-only or Alembic delegates.

- The restore prerequisite is `PASS` and is safe to repeat with new disposable
  database names.
- Compatibility entrypoint paths listed in
  [`compatibility-ledger.md`](../references/compatibility-ledger.md) remain
  present and are intentionally not deleted; the PostgreSQL paths now
  delegate to Alembic rather than issuing DDL.
- Complete release-cycle consumer evidence and owner approval are still
  required before any contraction row can move to removal.
- The disposable databases and in-container dump are cleaned after evidence
  capture; PostgreSQL facts, Temporal history, and immutable Evidence/Bundle
  versions are never removed by this rehearsal.
