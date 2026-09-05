## Why

The modular architecture baseline already defines Evidence, Query Family reuse, Personalization, and observable task boundaries, but those capabilities are not yet activated in the running product. This change turns them on in controlled, independently reversible milestones and adds Phoenix OSS as the first Agent observability and evaluation backend without changing the completed architecture baseline.

## What Changes

- Add a B1 shadow path that canonicalizes research inputs, records source/provenance and candidate Evidence Bundles, and measures divergence while leaving response reads on the existing path.
- Add a B2 read canary that reuses versioned Query Families and Evidence Bundles through deterministic matching, freshness gates, and conditional publication, with an explicit rollback switch.
- Add a B3 memory and personalization path with authoritative PostgreSQL records, bounded context assembly, user isolation, and post-read ranking, while keeping public Evidence immutable and shared.
- Add project-owned observability and evaluation ports with OpenTelemetry as the internal standard and Phoenix OSS as the first backend; instrumentation and exporter failure must be non-authoritative.
- Add offline datasets, deterministic evaluators, optional LLM-judge evaluation, shadow/canary gates, redaction controls, health metrics, and failure-injection coverage for the new paths.
- Add additive migrations, feature flags, deployment configuration, runbooks, and independent commit/rollback gates for B1, B2, B3, and Phoenix.
- Keep `define-modular-architecture` unchanged; its outstanding external owner/release evidence remains an external prerequisite and is referenced only by the new change.

## Capabilities

### New Capabilities

- `evidence-shadow-activation`: Shadow canonicalization, source/provenance capture, candidate Evidence Bundle construction, diff metrics, and B1 activation/rollback gates.
- `query-family-read-reuse`: Versioned Query Family matching, freshness routing, read reuse canary, atomic Bundle pointer handling, and B2 rollback behavior.
- `memory-personalization-activation`: Authoritative memory, bounded context assembly, user isolation, strategy snapshots, and B3 personalized filtering/ranking.
- `agent-observability-evaluation`: OpenTelemetry-based Agent/MCP/Connector/Evidence/Memory tracing, Phoenix export, redaction, evaluation datasets, evaluators, and backend replacement ports.

### Modified Capabilities

No existing main-spec capability requirements are modified. The completed `define-modular-architecture` change is intentionally left untouched.

## Impact

- Affected composition and application modules: research orchestration, Evidence/Query Family repositories and services, Personalization/context assembly, and the existing foundation observability module.
- Affected infrastructure: additive PostgreSQL/Alembic schema, Redis-derived caches only, optional Phoenix OSS service and isolated observability database/schema, and deployment/health configuration.
- Affected dependencies: an OTLP exporter and Phoenix-compatible OpenTelemetry integration selected behind project-owned ports; no Phoenix SDK types may leak into domain or API contracts.
- Affected tests and operations: contract, characterization, failure-injection, evaluation, migration, Compose smoke, redaction, and rollback tests/runbooks.
- Runtime compatibility: all new behavior is default-off until its milestone gate passes; legacy request/result contracts, Temporal execution authority, PostgreSQL business authority, and existing Prometheus `/metrics` remain intact.
