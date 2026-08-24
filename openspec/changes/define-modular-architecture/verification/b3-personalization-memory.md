# B3 Personalization Memory Verification

Status: Partial implementation - tasks 11.1-11.3 qualified; 11.4-11.15 remain disabled and pending

## Task 11.1 boundary

- Alembic revision `20260824_0007_b3_personalization_memory` is additive and follows
  B0 `20260824_0006_b0_reliable_task`.
- The revision owns `conversation_turns`, `session_state`, `memory_records`,
  `memory_events`, `preference_snapshots`, `memory_summaries`, `consent_events`,
  `claim_events`, and `outbox`. It creates no legacy tables and does not use
  runtime `CREATE TABLE IF NOT EXISTS` or a side migration path.
- `MEMORY_METADATA` is registered alongside `SHADOW_METADATA` in
  `alembic/env.py`; Alembic remains the only schema authority.
- `SQLAlchemyMemoryRepository` uses the project `SQLAlchemyUnitOfWork` and
  PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` for idempotent turn, record,
  source-event, preference snapshot, and outbox writes.
- Every read and write carries the complete tenant/subject/session scope. User
  and anonymous isolation keys map to distinct subject kinds and do not use
  process-local memory or Redis as an authority.
- `MemoryRecord` is the single `memory-record/v1` contract for Session,
  Explicit, Inferred, and Strategy Feedback layers. Its validation fixes the
  layer-specific value kind, confidence rule, consent basis, source event IDs,
  validity interval, expiry policy, status, and policy version.
- `MemoryEvent` is the private `memory-event/v1` source-event contract. Its
  payload stores schema/policy metadata and the repository persists the event
  identity, full scope, event type, occurred/created timestamps, and unique
  idempotency key in `memory_events`.
- `MemoryAuthorityWrite` is the only batch shape for the multi-fact write path.
  Its validator requires one tenant/subject/session scope for every fact. The
  SQLAlchemy adapter writes conversation, source event, memory record, and
  outbox in that order through one `SQLAlchemyUnitOfWork` and calls `commit`
  exactly once.
- `MemoryOutboxProjector` is invoked only after that commit. It supports
  user/session-scoped Redis invalidate and warm instructions with the fixed
  24-hour session TTL. Redis exceptions return `False` for retry and never
  enter or roll back the PostgreSQL transaction.
- `MemoryAuthorityWriter` makes this ordering executable at the application
  boundary: a repository commit failure prevents projection, while a
  projector failure returns `MemoryWriteReceipt(committed=True,
  projected=False)` and leaves the outbox ID available for retry.
- No embedding, summary, framework message, or recall-index column is part of
  the authority schema. Such artifacts remain rebuildable derived data.
- Individual repository convenience methods remain one-UoW operations; callers
  requiring atomic conversation/memory/outbox persistence use
  `commit_authority_write`.

## Qualification commands

```powershell
uv run --frozen pytest -q tests/test_unit_b3_schema.py
# 13 passed

uv run --frozen pytest -q tests/test_unit_domain_memory_contracts.py tests/test_unit_memory_media_hardening.py
# 53 passed

uv run --frozen pytest -q tests/test_unit_b0_schema.py tests/test_unit_b1_schema_and_embeddings.py tests/test_unit_b2_profile_fixture.py
# 8 passed

uv run --frozen ruff check src/xhs_food/foundation/memory_schema.py src/xhs_food/contracts/memory_repositories.py src/xhs_food/composition/adapters/memory_repository.py src/xhs_food/foundation/__init__.py src/xhs_food/contracts/__init__.py src/xhs_food/composition/adapters/__init__.py alembic/versions/20260824_0007_b3_personalization_memory.py alembic/env.py tests/test_unit_b3_schema.py
# All checks passed

git diff --check
# passed
```

## Deliberate non-claims

This milestone does not implement preference resolution, context assembly,
Redis session projections, cache invalidation, feedback ingestion, consent
flows, personalization canarying, or reranking. Those behaviors remain behind
the later B3 tasks and no personalization binding is enabled by this change.
