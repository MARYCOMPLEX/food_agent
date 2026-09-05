## 1. Baseline, contracts, and migration guardrails

- [x] 1.1 Record the current branch, configuration, schema revision, test baseline, and the clean diff of `define-modular-architecture`; do not edit that change.
- [x] 1.2 Add immutable configuration views and validation for B2 read mode, bounded OTel/Phoenix queue, batch, timeout, retry, sampling, and shutdown settings while preserving all existing defaults.
- [x] 1.3 Define project-owned observation and evaluation ports plus versioned redacted observation/evaluation payloads in `src/xhs_food/contracts`; keep vendor SDK imports out of contracts and domain modules.
- [x] 1.4 Add a composition binding plan for B1, B2, B3, and observability adapters with explicit off/shadow/canary modes and fail-closed invalid configuration handling.
- [x] 1.5 Add schema-state probing and additive migration fixtures for clean, N-1, current, and divergent PostgreSQL installations; stop safely on divergent state.
- [x] 1.6 Create versioned qualification manifests and deterministic fixture datasets for B1, B2, B3, and observability, including public/private redaction cases.
- [x] 1.7 Record a change-local ADR that pins the Phoenix image digest, OTLP protocol/path, evaluation API version, health endpoint, TLS/auth mode, retention, and isolated storage topology before adding dependencies.

## 2. B1 Evidence shadow implementation

- [x] 2.1 Wire the public canonical-query classifier and constraint partition into the shadow path with stable schema, classifier, and normalization versions.
- [x] 2.2 Integrate the shadow connector decorator at the Source Gateway boundary so it returns the legacy batch before attempting any shadow persistence.
- [x] 2.3 Enforce public-only input validation, source locator completeness, visibility/license/retention checks, content hashes, and derived-chain provenance for candidate Evidence.
- [x] 2.4 Implement deterministic sampling and bounded write-budget accounting with all disabled/zero-budget behavior covered by tests.
- [x] 2.5 Complete idempotent PostgreSQL persistence for canonical queries, source batches, locators, Evidence items, and candidate Bundles; never advance the current Bundle pointer in B1.
- [x] 2.6 Add bounded B1 telemetry for sampled, skipped, privacy-rejected, provenance-rejected, persisted, and failed outcomes with no raw payload attributes.
- [x] 2.7 Add unit and contract tests for duplicate deliveries, corrected content hashes, missing provenance, private nested fields, malformed batches, and sink exceptions.
- [x] 2.8 Add migration tests proving clean and N-1 convergence, additive rollback safety, and no impact on legacy reads or API event bytes.
- [x] 2.9 Add failure-injection tests for PostgreSQL abort, sink timeout, telemetry exporter failure, and process exit after candidate commit.
- [ ] 2.10 Run the B1 shadow qualification window, record parity/privacy/provenance thresholds and rollback evidence, and leave the mode non-serving until the gate is approved.

## 3. B2 Query Family read reuse implementation

- [x] 3.1 Implement or complete the versioned Query Family repository adapters for deterministic, lexical/trigram, and profile-pinned vector matching with isolated profile metadata.
- [x] 3.2 Implement the three-state freshness decision and Domain Pack policy adapter, including explicit coverage, watermark, active-refresh, and maximum-staleness reasons.
- [x] 3.3 Implement stable refresh claim/workflow identity and PostgreSQL single-flight conflict handling for concurrent stale requests.
- [x] 3.4 Implement immutable Bundle candidate publication with compare-and-set against the expected current version and a visible conflict outcome for late writers.
- [x] 3.5 Wrap the legacy reader with off/shadow/canary read modes; compute candidate and legacy digests without including user/session/private fields.
- [x] 3.6 Implement bounded stale fallback and explicit unavailable/partial outcomes when age or coverage limits are exceeded.
- [x] 3.7 Add profile backfill, quality validation, atomic read-pointer activation, and rollback tests for incompatible model/dimension configurations.
- [x] 3.8 Add contract and integration tests for exact/near/low-confidence matches, fresh/incremental/new routing, single-flight refresh, CAS races, and legacy wire compatibility.
- [x] 3.9 Add failure-injection tests for index loss, refresh worker crash, source timeout, PostgreSQL conflict, and stale fallback boundaries.
- [ ] 3.10 Run B2 shadow comparisons and then the separately approved canary gate; verify B1 remains enabled only as shadow and document the legacy-reader rollback command.

## 4. B3 Memory and Personalization implementation

- [x] 4.1 Complete the authoritative PostgreSQL transaction for conversation turns, four memory layers, source events, versioned snapshots, and outbox entries.
- [x] 4.2 Enforce user, anonymous-session, consent, lifecycle, and export/delete scope authorization at every memory repository and use-case boundary.
- [x] 4.3 Implement bounded Context Assembler ordering, model-budget trimming, version references, and a non-memory framework-neutral assembly record.
- [x] 4.4 Connect the resolver and reranker to public candidate facts only; expose strategy/version and bounded digest metadata without private values.
- [x] 4.5 Complete Redis window invalidation/warm-up and derived summary/index projection from the post-commit outbox, with version checks preventing stale projection writes.
- [x] 4.6 Add idempotent feedback/inference updates, correction, expiry, deletion, anonymous isolation, and cross-user denial tests.
- [x] 4.7 Add failure-injection tests for authority transaction abort, process exit after commit, Redis outage/restart, cache collision, outbox replay, and lost derived indexes.
- [x] 4.8 Add off/shadow/canary exposure tests proving public facts and public scores remain unchanged and B3 cannot expand the authorized tool/source set.
- [ ] 4.9 Run the B3 shadow qualification and then the separately approved canary gate only after B2 rollback rehearsal; record the public-ranking rollback evidence.

## 5. Phoenix OSS observation backend and evaluation plane

- [x] 5.1 Implement the observation-port adapter in `xhs_food.foundation` over the existing OpenTelemetry API/SDK and add the pinned OTLP/HTTP exporter dependency without leaking exporter types.
- [x] 5.2 Implement versioned redaction before span creation and a recursive sink scrubber for automatic spans immediately before export, covering headers, URLs, exception events, resources, bodies, and bounded correlation fields.
- [x] 5.3 Add bounded batch processing, queue saturation/drop policy, timeout/retry limits, malformed-record isolation, and one-deadline graceful shutdown flush.
- [x] 5.4 Add Prometheus health/volume/drop metrics and redacted diagnostics for exporter state; keep existing `/metrics` behavior and business health independent of Phoenix.
- [x] 5.5 Add no-op and deterministic in-memory observation/evaluation adapters, including captured-sink tests proving forbidden values never reach a backend.
- [x] 5.6 Add an optional Phoenix OSS Compose profile with a separate observability PostgreSQL service/database, role, credentials, named volume, retention settings, network identity, and health check; do not alter the legacy Compose manifest.
- [x] 5.7 Implement the Phoenix evaluation HTTP gateway against the documented API with version checks, bounded auth/TLS configuration, idempotent close/flush, and stable mapping for 401/403/404/429/5xx/timeout/schema errors.
- [x] 5.8 Implement immutable repository-owned dataset/case/result records, deterministic evaluators, and an optional versioned LLM-judge runner; Phoenix receives a projection and has no production write authority.
- [x] 5.9 Add Phoenix OTLP/API smoke tests, exporter-disabled startup tests, backend/database-unavailable tests, queue-saturation tests, malformed-telemetry tests, and shutdown-flush tests.
- [x] 5.10 Add end-to-end trace-context tests across API, Agent/model, MCP, Connector, Evidence, Query Family, Memory, ranking, and Temporal retry boundaries, proving workflow replay performs no exporter I/O.
- [x] 5.11 Add evaluation gate tests for B1/B2/B3 thresholds, privacy failures, deterministic reruns, judge metadata, digest-bound approvals, expiry, and explicit `pass`/`fail`/`blocked` outcomes.
- [x] 5.12 Use the no-op/in-memory backends to prove Phoenix replacement does not change domain, API, Temporal, Evidence, Memory, or business storage behavior.

## 6. Integration, qualification, and release controls

- [x] 6.1 Integrate the adapters through the Composition Root and verify architecture dependency rules, public imports, and legacy bindings remain valid with every mode off.
- [x] 6.2 Add locked-install and lint/type checks for the new dependencies, contracts, migrations, adapters, tests, and Compose manifests.
- [x] 6.3 Add a Compose smoke matrix for application, PostgreSQL, Redis, Temporal, optional Phoenix, and observability-database restart/order scenarios.
- [x] 6.4 Run the complete non-live suite plus focused B1/B2/B3/Phoenix contract and failure-injection suites; record commands and results in the change verification record.
- [x] 6.5 Run the live qualification probes available in the environment and explicitly record any external owner/release evidence or infrastructure gaps; do not mark the baseline task 10.12 complete.
- [x] 6.6 Validate `enable-evidence-reuse-memory-phoenix` with `openspec validate enable-evidence-reuse-memory-phoenix --strict` and revalidate `define-modular-architecture` unchanged.
- [x] 6.7 Produce per-milestone rollout and rollback runbooks, configuration snapshots, schema revision notes, and independent commit boundaries before enabling serving traffic.
- [ ] 6.8 Review the final diff for scope, secrets, telemetry redaction, dependency direction, and accidental edits outside this change; obtain explicit release approval for each activation gate.
