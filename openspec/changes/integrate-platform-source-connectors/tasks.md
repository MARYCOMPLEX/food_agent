## 1. Intake, Provenance, And Dependency Boundary

- [x] 1.1 Record the exact upstream snapshots (`dazhongdianping` `ffbc1d413ed1c83602212bc1fec12b57cd2b423d`, `Spider_XHS` `e1888d712519040f5fcc294baeac4b9505b25c98`), source URLs, retrieval date, dependency manifests, and reproducible archive digests.
- [x] 1.2 Produce a provenance and license report for both snapshots; record the missing tracked LICENSE in Spider_XHS, its README non-commercial notice, and an owner/security approval gate that blocks production/commercial activation while status is unknown.
- [x] 1.3 Define the provider import allow-list and namespace isolation.  Allow only Dianping auth/protocol modules and Spider_XHS PC/Creator protocol/auth modules; exclude upstream FastAPI apps, SQLite stores, CLI writers, task workers, and retry queues.
- [x] 1.4 Add dependency/import architecture tests that fail if upstream `apis`, `xhs_utils`, SQLite task tables, `dz-engine serve`, `Data_Spider`, or a second durable runtime is loaded by the application.
- [x] 1.5 Add synthetic provider fixtures and deterministic payload snapshots for Dianping shop/search/detail/review and Spider_XHS note/detail/comment/media/auth outcomes, without committing credentials, cookies, QR payloads, or raw account state.

## 2. Account, Session, Grant, Lease, And Health Authority

- [x] 2.1 Add versioned framework-neutral contracts for `PlatformAccountRef`, channel (`dianping`, `xhs_pc`, `xhs_creator`), account status, session version, health signal, grant, lease, and redacted account invocation.
- [x] 2.2 Implement the PostgreSQL/Alembic additive schema for platform accounts, encrypted session versions, login flows, grants, leases, and health events; include tenant/platform/account uniqueness, expiry, CAS version, and audit indexes.
- [x] 2.3 Implement an envelope codec/key-provider port and local test provider using authenticated encryption (AES-GCM); persist ciphertext, key reference/version, expiry, and digest only, with rotation and decrypt-failure tests.
- [x] 2.4 Implement repository ports/adapters for account lookup, grant authorization, session activate/retire CAS, health transitions, and lease acquire/heartbeat/release; transactions must be owned by the use case and fail closed on missing schema/dependency.
- [x] 2.5 Prove tenant and channel isolation with concurrent tests: same alias across platforms yields independent identities, cross-tenant access is indistinguishable from not-found/denied, and stale session writers/lease contenders cannot overwrite or run concurrently.
- [x] 2.6 Add secret-redaction tests over Temporal inputs/history, exceptions, logs, metrics, SSE, canonical evidence, and object metadata; reject cookies, authorization headers, QR contents, signer inputs, plaintext storage paths, and decrypted envelopes at every boundary.
- [ ] 2.7 Add migration clean/N-1/rollback probes and update the schema-authority manifest; no runtime `CREATE TABLE`, upstream SQLite migration, or second schema owner may remain.

## 3. Login Control Plane And QR Lifecycle

- [x] 3.1 Implement the split-phase login state machine (`created`, `qr_ready`, `waiting_scan`, `waiting_confirmation`, `succeeded`, `expired`, `failed`, `cancelled`) with monotonic terminal transitions, opaque flow IDs, expiry, and account/channel binding.
- [x] 3.2 Extend the Temporal queue configuration with an explicit optional `account-auth` queue and quota (disabled by default); update worker/configuration contracts and document that login is disabled/manual-import-only when the queue is not qualified.
- [x] 3.3 Implement account-auth Temporal activities for QR creation, bounded polling, phone login, and cookie import.  Blocking provider calls must run off the API event loop with timeout, heartbeat, cancellation, and bounded retry policies.
- [x] 3.4 Store QR bytes through the shared ObjectStore with PostgreSQL metadata and short retention; expose only a time-limited presentation reference and clean/undiscover QR objects on expiry or terminal completion. Redis may hold status projection only.
- [x] 3.5 On successful provider identity validation, commit exactly one encrypted session version through CAS and emit a redacted receipt; invalid identity, cancellation, expiry, restart, and duplicate completion must not activate a session.
- [x] 3.6 Add API/use-case adapters for start/status/QR/cancel/re-auth flows with authorization checks and stable error envelopes; do not expose cookies, signer state, storage-state paths, or provider response bodies.
- [x] 3.7 Run login failure-injection tests for Redis restart, Temporal worker restart, provider challenge/risk/timeout, cancellation races, stale flow polling, and orphan QR cleanup; verify the same flow ID resumes without duplicate sessions.

## 4. Dianping Source Connector

- [x] 4.1 Implement an injected Dianping provider factory that materializes one Playwright context from the resolved session in activity-local memory, uses no upstream SQLite/API/worker, and closes all browser resources on success, failure, timeout, and cancellation.
- [x] 4.2 Implement bounded place search mapping to canonical documents with stable shop IDs, normalized URLs, captured timestamps, cursors/watermarks, provenance, and JSON-safe public attributes.
- [x] 4.3 Implement place-detail, review/comment, and media-reference mapping.  Keep review media as stable references for the Media workflow; never place binary content or credentials in canonical attributes.
- [x] 4.4 Map authentication, challenge/risk, rate-limit, timeout, malformed, dependency, and valid-empty outcomes to the existing `ContractError` taxonomy and source/provider scope; quarantine degraded accounts and preserve partial coverage.
- [x] 4.5 Add Dianping connector contract tests for true-empty, pagination, malformed item isolation, missing session short-circuit, concurrent account contexts, provider exception redaction, and canonical URL safety.
- [ ] 4.6 Add a manual/qualification probe against a disposable account (when owner-approved) and record aggregate latency, coverage, and failure classifications without storing account data.

## 5. Spider_XHS PC/Creator Source Connector

- [x] 5.1 Implement an injected Spider_XHS provider factory with separate `xhs_pc` and `xhs_creator` account namespaces, one mutable client/signer per activity, and no process-global `.env` cookie, profile, or signer cache.
- [ ] 5.2 Execute synchronous QR/phone/cookie factories and note APIs in the account-auth/collection worker or approved sidecar, never in the FastAPI event loop; sanitize and hash-pin any Node remote signer assets and bound process resources.
- [x] 5.3 Implement bounded PC note search/detail/comments/media mapping, including tuple/envelope normalization, opaque pagination cursor, note ID/url validation, deduplication, and removal of access-bearing query parameters such as `xsec_token`.
- [x] 5.4 Implement Creator read/health capability only.  Keep publishing, upload, scheduling, business APIs, and `Data_Spider` unregistered and reject them before provider invocation.
- [x] 5.5 Map XHS 406/429/risk, authentication expiry, malformed tuples/items, timeout, dependency failure, and valid-empty responses to stable source errors; quarantine/rate-limit the affected channel and preserve eligible partial items.
- [x] 5.6 Add XHS connector/login tests for channel mismatch, QR lifecycle, risk challenge, worker cancellation/restart, tuple variants, malformed note isolation, URL redaction, media references, and concurrent PC/Creator accounts.

## 6. SourceGateway, Capability Registry, And Composition Binding

- [x] 6.1 Add an account-bound `SourceInvocation`/execution context port carrying opaque account reference, expected session version, correlation ID, and capability; keep `CollectRequest`, `SourceLocator`, Query Family identity, and public Evidence unchanged.
- [x] 6.2 Resolve grant, health, session version, and PostgreSQL lease before any provider call; release/heartbeat the lease and destroy decrypted material on every exit path.
- [x] 6.3 Register versioned `dianping` and Spider_XHS source IDs through the Composition Root with pinned provenance/dependency metadata; preserve the existing `xhs.compat` connector as the default while the feature flag is off.
- [x] 6.4 Resolve capability collisions (`place.lookup`, `reviews.search`) through an explicit source multiplexer/versioned capability registry; reject duplicate capability snapshots and never silently replace Amap or legacy XHS.
- [x] 6.5 Add feature flags, configuration validation, health/readiness reporting, and rollback bindings.  Missing provider checkout, vault, license approval, or auth queue must produce dependency-unavailable/disabled status rather than fallback that masks configuration.
- [x] 6.6 Add SourceGateway differential tests for legacy/new equivalence, account authorization denial before provider call, true-empty vs failure/partial, cursor resume, cancellation, timeout/retry budgets, and no query-identity pollution.

## 7. Qualification, Security, And Rollout

- [x] 7.1 Run the complete non-live contract, architecture, migration, and dependency suites with the new bindings disabled and enabled against synthetic fixtures; record exact commands, lockfile digest, and results.
- [ ] 7.2 Run the target-stack smoke matrix (PostgreSQL/Alembic, Redis hot status, Temporal research/refresh/media plus optional auth queue, and S3/MinIO ObjectStore) and verify queue isolation, health checks, and restart/replay behavior.
- [ ] 7.3 Run secret scanning, dependency/license review, signer sandbox checks, and telemetry cardinality/redaction gates; fail activation on unknown license, unpinned remote script, plaintext session path, or credential-bearing output.
- [ ] 7.4 Execute owner-approved canary for selected tenants/accounts, comparing legacy/new canonical outputs and error categories with aggregate-only metrics (result equivalence, latency, coverage, request volume, and auth/risk rates).
- [x] 7.5 Document operational runbooks for account registration/re-authentication, QR expiry, session revocation, provider quarantine, lease recovery, queue drain, sidecar restart, and manual Temporal retry/terminate using the same idempotency key.
- [x] 7.6 Verify rollback by disabling each platform flag and optional auth queue, draining or failing in-flight activities under their pinned connector version, retaining encrypted account rows/evidence/Temporal history, and routing new requests to the prior connector.
- [x] 7.7 Update architecture diagrams, dependency/provenance manifest, compatibility ledger, and release evidence; run `openspec validate integrate-platform-source-connectors --strict` and archive an independent commit/push with no credentials or generated state artifacts.
