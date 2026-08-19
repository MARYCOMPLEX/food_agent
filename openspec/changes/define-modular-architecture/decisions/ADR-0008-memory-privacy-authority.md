# ADR-0008: Memory And Privacy Authority

- Status: Accepted
- Date: 2026-08-19
- Owners: Product, Privacy, Security, Data Platform, QA
- Resolves: OQ-13, OQ-14, OQ-15
- Normative contract: [`memory_privacy_v1.json`](../../../../tests/fixtures/authority/memory_privacy_v1.json)

## Decision

`memory-record/v1` is the authority schema for the four product memory layers. Every
record is private, tenant-scoped, subject-scoped, provenance-linked, consent-aware,
versioned, and lifecycle controlled. PostgreSQL 16 owns committed conversation turns,
memory records/events, preference snapshots, consent events, claim events, and outbox
events in one transactional boundary.

Redis contains only the rebuildable 20-message/24-hour session window and invalidation
or recall projections. Embeddings, summaries, framework messages, and retrieval indexes
are rebuildable derived artifacts. Pydantic AI, Temporal, an LLM provider, Redis, Mem0,
Zep, or any other framework cannot become memory authority.

### Four Layer Schemas

All layers share the authority fields defined by the JSON fixture: record/schema/policy
versions, tenant and subject, optional session, stable key, typed value, source event
IDs, consent reference, validity interval, status, timestamps, and supersession link.

| Layer | Typed value and confidence | Scope and active-use expiry |
|---|---|---|
| `session` | Current query, geo, time, or temporary constraint; confidence is absent. | Requires `session_id`; active for 24 hours after last session activity. |
| `explicit` | User-stated preference or hard constraint with operator and typed value; confidence is absent. | Stable user scope, or isolated anonymous session before claim; active until correction, deletion, consent withdrawal, or an explicit user expiry. |
| `inferred` | Preference plus confidence in `[0,1]` and supporting user-action event IDs. | Stable user scope only; expires 180 days after the most recent supporting event. Anonymous behavior is not promoted to inferred long-term memory before an explicit claim. |
| `strategy_feedback` | Research depth, source trust, or result-style choice; confidence is absent. | Stable user scope, or current anonymous session; expires 90 days after capture. |

Expiry means the record is immediately excluded from context assembly, policy resolution,
and reranking. It cannot be revived by a stale cache or index. Expired authority rows are
removed by the retention job under the recorded policy version; legal holds are explicit
metadata and never implicit Redis retention.

### Identity And Isolation

Every access key begins with `tenant_id`. An authenticated private record is partitioned
by `(tenant_id, user_id)`; session memory adds `session_id`. An anonymous record is
partitioned by `(tenant_id, anonymous_subject_id, session_id)`. The literal word
`anonymous`, IP address, user agent, or a shared device fallback is never a subject ID.

`cohort` and `locale` are optional policy attributes, not authorization principals and
not permission to share memory. Visibility is fixed to `private_subject` (or
`private_session` for anonymous/session-only records). Public Evidence and public refresh
signals are not memory records. Repository predicates, cache keys, outbox consumers,
exports, and deletes all repeat the full tenant/subject scope; a caller-supplied ID alone
is insufficient.

Public Query Family isolation remains governed by ADR-0006: `tenant_scope`, `language`,
and `region` are mandatory partition coordinates, while user, session, device, cohort,
preference, and memory fields are forbidden from Family identity. A private memory scope
cannot broaden an Evidence visibility partition or authorize cross-partition reuse.

### Anonymous Claim

Anonymous memory never attaches to an authenticated user automatically. Migration
requires an authenticated, explicit `claim` command containing a one-time claim token
bound to the same tenant, anonymous subject, and session; the target user; a unique
idempotency key; and the accepted consent-policy version.

One PostgreSQL transaction verifies that the anonymous scope is still unclaimed, records
the claim event, copies eligible active records with provenance to new user-scoped
records, marks the originals claimed, and writes outbox invalidations. Session and
explicit/strategy records may migrate. Inferred memory must be recomputed from eligible
claimed source events; an anonymous inferred record is never copied. Cross-tenant,
expired, withdrawn, replayed-to-another-user, or conflicting claims fail atomically.
Failed cache invalidation cannot undo or replace the committed claim.

### Consent And Lifecycle Operations

The consent policy is layer-specific and versioned:

- session processing uses `service_required` only for the active request/session;
- explicit memory uses the user's `user_directed` write;
- inferred memory requires active `personalization_opt_in` before write and every use;
- strategy feedback requires active `feedback_personalization_opt_in` before cross-turn
  use; session-only feedback can remain service scoped.

Withdrawal prevents new writes and use immediately, supersedes affected active records,
and emits deletion/invalidation work. A stale derived projection cannot supply withdrawn
data.

Correction is append-only: a new record references `supersedes_record_id`, and the old
record becomes `superseded` in the same transaction. Export is an authenticated,
tenant/subject-scoped UTF-8 JSON document containing active, superseded, expired, consent,
claim, source, and policy metadata; it excludes credentials and raw embedding vectors.
Delete may target a record, layer, session, or whole subject. It blocks online reads in
the authority transaction, emits cache/index purge work, and removes non-held online
records within 24 hours and backup copies within 30 days. Replayed source or outbox
events cannot recreate a tombstoned record.

### Derived Data And Framework Independence

Every summary, embedding, recall index, preference projection, and Redis value records
the source authority version plus its model/rule profile. Only active, consent-valid,
unexpired authority records may be indexed. Derived data can always be dropped and
rebuilt from those records, must not overwrite a newer authority version, and is purged
after correction, withdrawal, expiry, or deletion. Framework-specific message objects
exist only in a per-call adapter and are never persisted as product memory.

### Feedback Privacy Gate

The accepted v1 threshold is deny-all: `public_refresh_influence.enabled = false`.
Neither an individual signal, a small cohort, nor any current aggregate may affect public
refresh priority, Query Family identity, Evidence, public features, or public scoring.
There is therefore no numerical k-threshold to accidentally treat as permission.

Enabling public influence requires a separate ADR and policy version defining a reviewed
aggregation population, minimum cohort size, contribution caps, time window, tenant and
visibility boundaries, deletion propagation, abuse resistance, privacy analysis, audit,
and rollback. Until that ADR is accepted, the only valid aggregation output for public
refresh is no signal.

## Consequences

- Personalization can survive runtime/framework replacement without moving product facts.
- Anonymous sessions remain isolated unless the user performs an explicit, auditable
  claim.
- Expiry, correction, export, and deletion apply to authority and derived data through a
  replayable outbox rather than best-effort cache mutation.
- Public research assets cannot be influenced by private feedback under v1.

## Rejected Alternatives

- Redis or an Agent framework as long-term memory: rejected because neither is the
  committed, user-lifecycle-aware business-fact authority.
- Automatic device-to-user merge: rejected because device identity is not proof of an
  authenticated user's intent to claim private data.
- In-place correction: rejected because it destroys provenance and past-decision audit.
- A placeholder cohort threshold: rejected because an unevaluated number would silently
  authorize a privacy-sensitive public feedback path.
