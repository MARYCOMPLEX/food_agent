# B3 Personalization Memory Verification

Status: Partial implementation - tasks 11.1-11.5 qualified; 11.6-11.15 remain disabled and pending

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
- `PreferenceResolver` is a contracts-only service. It rejects records outside
  the requested full scope, excludes expired/withdrawn/tombstoned records,
  keeps the four memory buckets separate, and selects the newest record per
  key within each bucket. `effective_constraints` merges inferred -> stable
  explicit -> current session -> explicit hard constraints, so stronger input
  wins deterministically. Strategy feedback is never included in that content
  merge and can only be consumed by later research/presentation policy code.
- `PreferenceSnapshot.source_record_versions` may be empty when no active
  memory exists. This represents “no preference” distinctly from an explicit
  no-preference value and prevents stale caches from being treated as facts.

## Task 11.5 boundary

- `ContextAssembler` is a contracts-only personalization service. It does not
  import FastAPI, Redis, SQLAlchemy, Pydantic AI, or any provider SDK.
- `ContextAssembly` uses the fixed order `request_constraints`,
  `recent_messages`, `versioned_summary`, `related_memory`, and
  `related_evidence`. It returns structured fragments instead of framework
  `ModelMessage` values; a model adapter may translate the temporary result
  later without making framework messages memory authority.
- `ContextBudget` has a total ceiling and an explicit ceiling for every
  section. The default estimator is deterministic (`ceil(characters / 4)`) and
  can be replaced by a provider tokenizer adapter without changing the
  contract. Whole fragments are selected deterministically; priority-zero
  hard constraints can be clipped to their section ceiling, while lower
  priority inferred memory is dropped first and never displaces them.
- Every selected and dropped fragment carries a `ContextSourceRef` with source
  identity plus schema/policy/summary/profile/authority/bundle versions where
  applicable. Section records include selected and dropped refs, token usage,
  version refs, and a truncation flag.
- The assembler validates an optional full memory isolation scope and rejects
  records from another user/session. It accepts public Evidence only and
  excludes tombstoned items; no private Evidence can enter the temporary
  context.
- Strategy Feedback records are intentionally excluded from content memory
  sections; they remain inputs to research-depth, source-selection, and
  presentation policy only.

## Task 11.6 boundary

- `MemorySessionWindowPort` is a distinct user-scoped projection contract. Its
  append/recent/clear methods require the complete `MemoryIsolationKey`, so a
  bare session ID cannot read another user's hot state.
- `RedisUserSessionWindow` uses a namespaced `session:` key containing tenant,
  user or anonymous subject, and session. It enforces the fixed 20-item window
  and 24-hour TTL and exposes no lock, lease, durable task, or process-local
  fallback surface. The existing legacy `RedisSessionWindow` key and methods
  remain unchanged for compatibility.
- `SQLAlchemyMemoryRepository.list_conversation_turns` reads only the supplied
  PostgreSQL scope, orders by the authority timestamp, and caps the query at
  20 turns. `MemorySessionProjection` first reads Redis; an empty/missing
  projection is rebuilt from those PostgreSQL turns and then warmed back into
  Redis. Redis errors propagate to the caller and never switch to in-process
  cross-request memory.

## Qualification commands

```powershell
uv run --frozen pytest -q tests/test_unit_b3_schema.py
# 13 passed

uv run --frozen pytest -q tests/test_unit_domain_memory_contracts.py tests/test_unit_memory_media_hardening.py
# 53 passed

uv run --frozen pytest -q tests/test_unit_b3_resolver.py
# 5 passed

uv run --frozen pytest -q tests/test_unit_b3_context.py
# 4 passed

uv run --frozen pytest -q tests/test_unit_b3_session_projection.py
# 3 passed

uv run --frozen pytest -q tests/test_unit_b3_schema.py tests/test_unit_b3_resolver.py tests/test_unit_b3_context.py tests/test_unit_b3_session_projection.py
# 25 passed

uv run --frozen pytest -q tests/test_unit_b0_schema.py tests/test_unit_b1_schema_and_embeddings.py tests/test_unit_b2_profile_fixture.py
# 8 passed

uv run --frozen ruff check src/xhs_food/foundation/memory_schema.py src/xhs_food/contracts/memory_repositories.py src/xhs_food/composition/adapters/memory_repository.py src/xhs_food/foundation/__init__.py src/xhs_food/contracts/__init__.py src/xhs_food/composition/adapters/__init__.py alembic/versions/20260824_0007_b3_personalization_memory.py alembic/env.py tests/test_unit_b3_schema.py
# All checks passed

git diff --check
# passed

uv run --frozen pytest -q -m "not live" -ra --tb=short
# 894 passed, 24 deselected, 2 warnings

uv lock --check
# passed

openspec validate define-modular-architecture --strict
# Change 'define-modular-architecture' is valid
```

## Deliberate non-claims

This milestone does not implement Redis session projections, cache
invalidation, feedback ingestion, consent flows, personalization canarying, or
reranking. Those behaviors remain behind the later B3 tasks and no
personalization binding is enabled by this change.
