# Legacy Contraction Restore Rehearsal

Status: **PASS for restore prerequisite; removal remains blocked**

Recorded: `2026-08-25` on the local release Compose stack
(`PostgreSQL 16 + pgvector/pg_trgm`, Temporal `1.28.2`). The rehearsal used
disposable databases only and did not modify `xhs_food_agent`.

## Clean, Downgrade, And Re-Upgrade

Disposable database: `legacy_contraction_rehearsal_20260825`

```powershell
docker compose -f docker-compose.release.yml -p food-agent-release-gate exec -T postgres createdb -U postgres legacy_contraction_rehearsal_20260825
docker compose -f docker-compose.release.yml -p food-agent-release-gate run --rm --no-deps -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/legacy_contraction_rehearsal_20260825 migrate
docker compose -f docker-compose.release.yml -p food-agent-release-gate run --rm --no-deps -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/legacy_contraction_rehearsal_20260825 app alembic downgrade base
docker compose -f docker-compose.release.yml -p food-agent-release-gate run --rm --no-deps -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/legacy_contraction_rehearsal_20260825 app alembic upgrade head
```

Observed result:

- clean `upgrade head`: revisions `0001` through `0007` completed;
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
20260824_0007_b3_personalization_memory
26
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
20260824_0007_b3_personalization_memory
pg_trgm
vector
26
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
status: pending_legacy_contraction
unexpectedFindings: []
legacyFindings: 8 registered runtime DDL sources
```

Exit code `2` is intentional while the compatibility ledger still retains
legacy runtime DDL. The probe covers literal SQL, string concatenation, and
f-string SQL fragments. An unregistered runtime DDL source returns exit `1`;
once the approved contraction removes all allowlisted paths, the same probe
returns exit `0`. The probe excludes Alembic, tests, and virtual environments
and does not modify source code or database state. Hosted CI run
[`32849665982`](https://github.com/MARYCOMPLEX/food_agent/actions/runs/32849665982)
at commit `803bbaa` executed the same preflight and uploaded the JSON report.

## Gate Interpretation And Cleanup

- The restore prerequisite is `PASS` and is safe to repeat with new disposable
  database names.
- Runtime DDL paths listed in
  [`compatibility-ledger.md`](../references/compatibility-ledger.md) remain
  present and are intentionally not deleted.
- Complete release-cycle consumer evidence and owner approval are still
  required before any contraction row can move to removal.
- The disposable databases and in-container dump are cleaned after evidence
  capture; PostgreSQL facts, Temporal history, and immutable Evidence/Bundle
  versions are never removed by this rehearsal.
