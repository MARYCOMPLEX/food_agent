## Context

See `proposal.md` for the motivation and audited upstream snapshots.  The
current repository already owns the `SourceConnector` and `SourceGateway`
contracts, canonical evidence models, PostgreSQL/Alembic authority, Redis hot
state, S3-compatible ObjectStore, and Temporal Research/Refresh/Media queues.
The existing XHS path is a legacy singleton/tool facade; it is intentionally
left intact while the new bindings are qualified.

The Dianping snapshot contains useful Playwright protocol modules but its
backend/worker persists plaintext storage-state paths in SQLite.  The
Spider_XHS snapshot contains PC and Creator QR/phone/cookie protocol clients,
but its public entry point is a single `.env` cookie and its synchronous
clients carry mutable signer state.  Neither upstream repository supplies the
account authority required by this system.

## Goals / Non-Goals

**Goals:**

- Make account selection and session material an explicit, tenant-isolated
  control-plane concern while preserving public query/evidence identity.
- Reuse the upstream protocol implementations without importing their API
  servers, SQLite schedulers, CLI writers, or unbounded retry behavior.
- Deliver read-only Dianping and XHS PC/Creator collection through canonical
  source contracts, with bounded pagination, failure taxonomy, provenance, and
  reversible Composition Root bindings.
- Provide a split-phase QR flow that works for both platforms and leaves a
  clear path to phone and cookie import.
- Keep all provider-specific dependencies replaceable, auditable, and isolated
  from the core process where their runtime (notably Node remote-script
  execution) requires it.

**Non-Goals:**

- No deletion or replacement of the current `xhs.compat` connector, legacy
  HTTP/SSE routes, Query Family schema, or existing memory implementation.
- No Creator publishing, uploads, scheduling, PGY/Qianfan capabilities, or
  automatic proxy rotation.
- No provider-specific credential or raw-response fields in canonical evidence;
  raw bytes are handled only by the existing ObjectStore/Media contracts.
- No assumption that a README license badge is a legal grant.  Activation in a
  commercial deployment remains blocked until provenance/license approval is
  recorded for both snapshots.

## Decisions

### 1. Project-owned account authority

Add versioned account contracts and an Alembic-owned PostgreSQL schema with
`platform_accounts`, `platform_account_sessions`, `platform_login_flows`,
`platform_account_leases`, `platform_account_grants`, and
`platform_account_health_events`.  The natural key is
`(tenant_id, platform, account_id)`; `xhs_pc` and `xhs_creator` are different
platform channels even when they belong to one person.  Session rows contain
an AES-GCM envelope, key reference/version, expiry, and digest—not plaintext
cookies or file paths.  The codec is a port so a KMS/Vault implementation can
replace the local key provider without changing the repository contract.

Alternatives considered: reusing the Dianping SQLite database or `.xhs_profiles`
files (rejected because they create a second authority and leak plaintext),
and putting credentials in Redis (rejected because Redis is rebuildable hot
state only).

### 2. Account-bound invocation without query pollution

Keep `CollectRequest`, `SourceLocator`, and Family identity unchanged.  A
Temporal Activity receives an opaque `account_ref` and expected `session_version`
in a separate invocation envelope, checks an `AccountGrant`, acquires the
PostgreSQL lease, decrypts material in process-local memory, and constructs a
short-lived connector/client.  Only the redacted account reference and version
may appear in workflow metadata; `SessionMaterial` never crosses the Activity
boundary.

Alternatives considered: adding `account_id` to `CollectRequest` (rejected—it
would fragment public Family identity), and a global connector with mutable
profiles (rejected—it cannot guarantee isolation under concurrency).

### 3. One durable runtime, with a bounded auth queue

Use the same Temporal service for login and collection.  Add an optional,
explicit `account-auth` Task Queue and quota for long-running QR/browser work;
it is disabled by default until its qualification gate, so the existing three
queue defaults and tests remain valid.  Auth activities use bounded heartbeat,
timeout, cancellation, and provider retry budgets.  No upstream worker, Redis
queue, SQLite task table, or broker dead-letter queue is started.

Alternatives considered: placing QR polling on the Research queue (rejected
because it competes with foreground capacity), and adding a second worker
runtime (rejected because Temporal must remain the sole durable checkpoint).

### 4. Provider runtime placement

The adapter interface accepts an injected provider factory and normalizes its
result envelope.  Dianping may run in-process in the dedicated activity because
Playwright is already a project dependency; Spider_XHS defaults to an isolated
provider worker/sidecar image (Python 3.10+/Node 20+) when its `curl_cffi` and
Node signer dependencies are not part of the locked core image.  The cross-
process contract is the same typed adapter boundary and carries no credentials
in logs or transport.  A pinned in-process checkout is allowed for local
qualification, but top-level `apis`/`xhs_utils` are never added to the main
module path.

Remote signer programs are run with a sanitized environment, bounded CPU,
memory, output, and wall time, and an allow-listed/hash-recorded source.  The
existing global DSL/signature caches are not shared between account clients.

### 5. Canonical source mapping and media

`DianpingSourceConnector` maps shop search/detail to documents and reviews to
comments; `SpiderXhsSourceConnector` maps PC notes to documents and comments.
Provider-specific IDs remain opaque attributes, while canonical URLs are
normalized to remove access-bearing query parameters.  Empty-success,
authentication/challenge, rate-limit, timeout, malformed, and dependency
outcomes use the existing `ContractError` categories.  Media is returned as
stable references only; signed provider URLs are fetched later by the Media
queue into ObjectStore when policy permits.  Public Evidence is never inferred
from account-authenticated data without an explicit visibility/license policy.

### 6. Capability and rollout binding

Register `dianping` and the versioned `xhs` Spider connector in a dedicated
platform registry rather than replacing the existing Food tool capability
entries.  The SourceGateway chooses one implementation per source invocation;
legacy XHS remains the default until the new flag and differential suite pass.
Creator publishing is deliberately not registered.  Every binding carries the
upstream commit, connector version, dependency digest, and license status in
the provenance manifest.

## Risks / Trade-offs

- **[Upstream license/ToS is ambiguous]** → keep `license_status=unknown`, block
  production/commercial activation, and require owner approval plus a pinned
  provenance record before canary.
- **[Provider protocol or signer drift]** → run synthetic fixtures and a manual
  live probe, version connector/algorithm profiles, classify drift as a health
  failure, and roll back the binding without touching public pointers.
- **[Sidecar adds latency and operations]** → use a typed local adapter and
  bounded connection pool; keep in-process mode for development and preserve
  the same contract for later migration.
- **[Credential leakage through exceptions or traces]** → central redaction,
  encrypted envelopes, opaque IDs, allow-listed telemetry labels, and secret
  scanning in CI.
- **[Mutable signer state races]** → one client per account/activity, a durable
  account lease, CAS session updates, and explicit cleanup on every exit path.
- **[QR objects outlive a login flow]** → short TTL metadata, terminal cleanup,
  and Media/ObjectStore orphan reconciliation; Redis status is disposable.

## Migration Plan

1. **I0 Intake:** record the two commit SHAs, dependency manifests, license
   status, namespace collision findings, and synthetic fixtures.  Keep the new
   bindings disabled.
2. **I1 Authority:** apply the additive Alembic revision, deploy the encrypted
   account/session repository, grant checks, lease/CAS logic, redaction, and
   health projection.  Run clean/N-1 migration and rollback probes.
3. **I2 Login:** enable the optional `account-auth` queue in a qualification
   environment; expose split-phase QR/phone/cookie control routes; exercise
   expiry, cancellation, worker restart, and re-authentication for both
   platforms.
4. **I3 Dianping:** bind search/detail/review/media adapters behind SourceGateway
   with synthetic and manual live fixtures.  Do not start `dz-engine serve` or
   its SQLite worker.
5. **I4 XHS:** bind PC read operations and separate Creator health/read adapter;
   verify per-channel signer state, QR flow, and sidecar isolation.  Do not
   enable publishing.
6. **I5 Canary:** compare legacy/new canonical outputs and failure categories,
   then opt in selected tenants/accounts.  Record aggregate metrics only.
7. **Rollback:** turn off the platform flag and auth queue, stop new provider
   activities, let pinned in-flight Temporal runs finish or fail, revoke active
   leases, and route new requests to the prior connector.  Keep encrypted
   account rows, immutable evidence, and Temporal history; no destructive
   migration or pointer rewrite is required.

## Open Questions

None that change the selected scope or task breakdown.  Deployment-specific
KMS/Vault wiring, exact lease durations, and production canary thresholds are
operational inputs to be supplied by the owning release/security teams during
I1/I6; the contracts already fail closed when they are absent.
