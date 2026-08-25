# Legacy Schema Baseline Evidence

Status: **PASS for clean/N-1/pre-turn migration behavior; runtime DDL contraction remains pending**

Recorded: `2026-08-25` on the local release Compose stack (`PostgreSQL 16 +
pgvector/pg_trgm`, Alembic `1.19.1`).

## Revision And Ownership

`20260825_0008_legacy_schema` is chained after
`20260824_0007_b3_personalization_memory`. The checked-in Core metadata in
`src/xhs_food/foundation/legacy_schema.py` is imported by `alembic/env.py` and
is shared by the revision. Importing metadata never creates or alters a table.

The revision adopts six legacy application tables:

```text
users, favorites, search_history, search_results, restaurants, chat_history
```

Clean installs create the complete shape. Existing recognized tables are
catalog-inspected; a pre-turn `search_results` table receives `turn_id` and
`query`, loses the single-column `session_id` unique constraint, and receives
the composite `(session_id, turn_id)` unique index. Missing required columns
raise an explicit `unrecognized legacy schema` error rather than being
silently repaired.

## Observed Commands

```powershell
docker compose -f docker-compose.release.yml -p food-agent-release-gate run --rm --no-deps `
  -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/xhs_food_agent migrate
```

Observed release head:

```text
20260825_0008_legacy_schema
```

The app then initialized both legacy asyncpg adapters successfully after
normalizing the release SQLAlchemy DSN scheme:

```text
UserStorageService initialized successfully
pgvector enabled, embedding search available
PostgresStorage initialized successfully
```

## N-1 And Pre-Turn

A disposable database was upgraded through `20260824_0007_b3_personalization_memory`,
loaded from `tests/fixtures/database/search_results_pre_turn_id.sql`, and then
upgraded to head. The resulting `search_results` columns were:

```text
id, session_id, restaurants, summary, filtered_count, created_at, turn_id, query
```

The resulting indexes included:

```text
idx_results_session
idx_results_session_turn UNIQUE (session_id, turn_id)
idx_results_turn (session_id, turn_id DESC)
```

The same disposable database completed downgrade to `0007` and re-upgrade to
`0008` while empty. After inserting one `users` row, downgrade failed closed
with `legacy schema downgrade requires restore because populated tables would
be deleted: users`; the Alembic version and row remained unchanged.

## Boundary

This closes the missing-table deployment gap and establishes the migration
authority. It does not remove the legacy runtime initializers or historical
one-shot scripts. The schema-authority probe therefore remains intentionally
`pending_legacy_contraction` until one complete release cycle, consumer owner
approval, and restore evidence authorize each removal.
