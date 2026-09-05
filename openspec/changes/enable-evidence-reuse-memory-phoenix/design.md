## Context

The architecture baseline is already represented by the existing composition
root, contract packages, PostgreSQL authority, Redis rebuildable projections,
Temporal execution history, and stable API/event mappers. It is a completed
baseline and is out of scope for this change. The repository currently contains
target-side foundations for canonical queries, Evidence shadow records, Query
Family matching, memory authority/outbox handling, personalization canaries,
OpenTelemetry instrumentation, and Prometheus metrics, but the serving paths are
mostly disabled by configuration. Existing Alembic revisions are additive and
must remain compatible with clean and pre-change databases.

The new change therefore has two layers: qualification data paths (B1, B2,
B3) and an observation/evaluation plane. The observation plane is not a source
of business truth. PostgreSQL remains authoritative for business facts,
Temporal history remains the executable recovery authority, Redis remains
rebuildable hot state, and Phoenix is an optional consumer of telemetry and
evaluation artifacts.

## Goals / Non-Goals

**Goals:**

- Activate B1, then B2, then B3 with independent flags, contracts, tests,
  metrics, and rollback procedures.
- Reuse the existing project-owned ports and adapters rather than exposing
  concrete vendor types to domain or API code.
- Add Phoenix OSS as the first OpenTelemetry trace and evaluation backend with
  an isolated storage boundary and a direct OTLP path that can later sit behind
  an OTel Collector.
- Preserve legacy response wire contracts and business authority during shadow
  and canary operation.
- Make telemetry and evaluation deterministic enough to compare releases while
  bounding cost, cardinality, queue growth, and sensitive data exposure.

**Non-Goals:**

- No edits to `define-modular-architecture`, its tasks, verification records,
  ADRs, or release evidence.
- No simultaneous production activation of B2 and B3 before their preceding
  gates pass; no broad rewrite of the existing Agent runtime.
- No Phoenix SDK objects in application/domain contracts, no Phoenix dependence
  for request success, and no migration of business data into Phoenix.
- No automatic promotion of an LLM judge result, automatic public refresh
  reprioritization from private feedback, or replacement of the existing
  Prometheus `/metrics` surface.

## Decisions

### 1. Milestone state machine and configuration ownership

The Composition Root owns the feature bindings. Each capability exposes an
`off`, `shadow`, or `canary` mode where serving behavior is relevant; B1 has a
shadow-only serving contract. Settings are immutable after bootstrap and are
validated before binding activation. Recommended names are:

| Capability | Modes/flags | Default | Owner |
|---|---|---:|---|
| B1 Evidence | `MODULAR_EVIDENCE_SHADOW_ENABLED`, sample rate, write budget | disabled/0 | Evidence Intelligence + Foundation config |
| B2 Query reuse | `MODULAR_QUERY_REUSE_READ_MODE`, sample rate | `off` | Evidence Intelligence |
| B3 Personalization | existing `MODULAR_PERSONALIZATION_CANARY_MODE`, sample rate, warm-up | `off` | Personalization |
| OTel/Phoenix | existing `MODULAR_OTEL_ENABLED`, service name, exporter endpoint, plus bounded queue/batch settings | disabled | Foundation/Composition |

The implementation may use a compatible internal naming adapter, but the
logical bindings and defaults must remain stable. A later milestone cannot
implicitly enable an earlier one. Startup rejects an invalid mode/rate pair,
missing Phoenix endpoint when Phoenix export is explicitly selected, or a
configuration that would make B2 serve while its B1 gate is not recorded as
passed. The final production check still requires explicit operator action;
configuration alone does not mark a qualification gate complete.

### 2. Ownership and dependency direction

The dependency direction is:

```text
API/experience -> application use cases -> domain capabilities/contracts
                 -> project-owned ports -> composition adapters
                 -> Foundation (PG, Redis, Temporal, OTel)
```

- `xhs_food.evidence` owns canonicalization, shadow projection, Query Family
  matching, freshness decisions, and Bundle lifecycle decisions.
- `xhs_food.personalization` owns memory resolution, context assembly, and
  private reranking; it can read public Evidence but cannot write it.
- `xhs_food.contracts` owns versioned payloads and ports, with no vendor SDK
  imports.
- `composition.adapters` implements business-facing SQL and compatibility
  ports. OTel mechanics live in `foundation` (where the dependency policy
  permits OTel), while Phoenix evaluation HTTP calls live in the gateway layer
  (where the dependency policy permits `httpx`). `composition.root` selects
  both bindings and owns their lifecycle. No Phoenix SDK import is permitted in
  `composition.adapters`, domain, or contracts.
- `foundation` owns transport/infrastructure mechanics, low-cardinality metrics,
  redaction, and tracing bootstrap; it does not decide domain outcomes.
- Evaluation code reads immutable fixtures/results and calls evaluator ports; it
  cannot call business repositories with write authority.

Forbidden edges include domain imports of SQLAlchemy/Redis/Temporal/Phoenix,
Personalization writes to public Evidence or Query Family identity, telemetry
adapters writing business tables, and API routes constructing vendor clients.
The architecture dependency test and an import scan enforce these edges.

### 3. B1 shadow path

The existing connector is wrapped by a shadow decorator. The wrapper returns
the exact source batch first, then performs a bounded, sampled projection:

```text
public request
  -> canonical query/classification
  -> source connector (legacy result authority)
  -> public/provenance validation
  -> candidate Evidence + locator + candidate Bundle
  -> idempotent PG transaction
```

Canonical identity uses the approved public fields and a classifier/schema
version. A private-field detector fails closed. Candidate rows use stable
content hashes and conflict-safe inserts. The current Bundle pointer is never
changed in B1. A sink or telemetry exception is caught at the decorator
boundary and classified; it cannot change connector status or API output.

The B1 migration is expand-only. It creates or verifies canonical query,
source/provenance, evidence item, candidate bundle, and dedupe structures. The
migration probe classifies clean, pre-turn, current, and divergent schemas
before upgrade; it never assumes a historical migration ran. B1 qualification
uses clean install, N-1 upgrade, source contract, provenance, privacy,
idempotency, and legacy digest comparisons.

### 4. B2 read reuse path

B2 wraps the existing reader behind a read-use-case port. It evaluates the
legacy result as the compatibility reference and only then computes a candidate
reuse decision. Matching order is deterministic key, approved lexical/trigram
stage, and an isolated vector profile. Profile metadata (model, dimensions,
distance, normalization, and version) is stored with derived rows. A profile
change creates a separate index and is activated atomically after backfill and
quality checks.

Freshness is a pure decision over authoritative facts and Domain Pack policy:

```text
fresh -> serve current Bundle
incremental -> join one refresh identity and preserve usable coverage
new -> create new research task
```

Refresh identity is derived from Family, scope, and policy version, never from
user/session data. Bundle publication uses compare-and-set against the expected
current version. B2 shadow mode records candidate/legacy digests but serves the
legacy response. Canary mode serves only sampled, contract-compatible candidates
after the B2 gate. A rollback changes one binding to the legacy reader; it does
not delete Family, Bundle, index, or refresh history.

### 5. B3 memory and personalization path

The authority writer commits conversation turns, structured memories, source
events, and outbox entries in one PostgreSQL transaction. The outbox drives
Redis window invalidation/warm-up and any summary or vector projection. Redis
keys include the full isolation scope and are never used to confirm a write.

The Context Assembler consumes only an authorized scope and enforces the
priority order (hard constraints, current session, recent messages, versioned
summaries, relevant memory, public Evidence) within the active model budget.
The Resolver and reranker operate on public candidates after Evidence selection;
they return strategy/version metadata and bounded digests, not private values.

B3 shadow mode computes a sampled personalized result and records whether order
changed while serving the public ranking. Canary mode is independently sampled.
If authority is unavailable, the system does not pretend a write succeeded; if
Redis or a derived index is unavailable, it rebuilds from authority or uses a
clearly marked non-personalized path. B3 rollback disables exposure and warm-up
but retains authority facts.

### 6. Phoenix observation and evaluation plane

Use OpenTelemetry API/SDK as the internal tracing contract and the OTLP/HTTP
exporter as the initial transport. A small project-owned `ObservationPort`
accepts normalized span/event records; a separate `EvaluationPort` accepts
versioned dataset cases and evaluator results. The implementation is split at
the dependency-policy boundary: a Foundation exporter emits standard OTLP,
and a gateway adapter uses the documented Phoenix HTTP API for datasets and
evaluation records. No Phoenix SDK import occurs in domain, contracts,
`composition.adapters`, or workflow code; if a future SDK is needed, it is
confined to that gateway and pinned in the lockfile.

Initial topology:

```text
API / workers
  -> OTel SDK + bounded batch processor
  -> ObservationPort
  -> OTLP/HTTP Phoenix adapter
  -> Phoenix OSS (optional Compose profile)
  -> isolated observability PostgreSQL database/schema
```

Direct OTLP keeps the first deployment small. An OTel Collector is a future
transport substitution, not a prerequisite. Phoenix health is sampled through
the gateway/exporter adapters and exposed in Prometheus; business health
endpoints do not depend on a Phoenix round trip. Phoenix storage uses a
separate database, role, credentials, retention policy, named volume, and
network identity from business PostgreSQL. The application receives only the
OTLP/Phoenix endpoint and an opaque `TOKEN` reference, never Phoenix database
credentials.

Span boundaries are stable names for Agent run, model call, MCP/tool call,
Connector call, Evidence transform, Query Family read/refresh, Memory assembly,
ranking, and Temporal activity. Correlation fields are opaque hashes for task,
workflow, Family, Bundle, profile, pack, connector, provider, and model role.
The redaction layer runs before span creation and again immediately before
both exporter/evaluation upload and structured logging. It recursively scrubs
automatic instrumentation fields such as URL paths, headers, exception
events, resource attributes, and HTTP bodies. It allows only bounded
classifications and finite metric labels; it drops raw prompts, queries,
outputs, MCP payloads, cookies, tokens, QR data, account state, private
memory, source URLs, signed URLs, and note text. Temporal Workflow code never
executes network or exporter calls, preserving replay determinism; context is
propagated through workflow/activity boundaries by the worker interceptor.

Exporter settings include maximum queue size, batch size, schedule delay,
export timeout, retry limit, sampling rate, and shutdown flush deadline. Queue
saturation uses a documented drop-oldest/newest policy and never blocks a
business transaction. Shutdown attempts one bounded flush and reports the
outcome. Malformed records are dropped individually so other records proceed.

### 7. Evaluation and release gates

Evaluation artifacts are immutable repository-owned JSON records containing
dataset digest, case ID, evaluator version, configuration digest, outcome, and
(for an LLM judge) provider/model/rubric/template versions. Phoenix receives a
projection and is never the sole dataset authority. Deterministic evaluators cover
contract shape, public/private separation, Family match, freshness state,
ordering, authority commit, and failure behavior. A judge is optional and
offline; its output is evidence for a human/operator gate, never a write path.

Each milestone has a manifest with required tests, thresholds, failure-injection
cases, observed telemetry health, and rollback decision. Reports are explicitly
`pass`, `fail`, or `blocked`; missing datasets, evaluator versions, approvals,
or required Phoenix ingestion evidence produce `blocked`, never `pass`. The
manifest records Phoenix availability separately from business pass/fail so an
observability outage cannot mask a business regression or vice versa.

### 8. Migration, deployment, and rollback

Deployment order is:

1. Record an ADR/dependency spike pinning the Phoenix image digest, documented
   OTLP protocol/path, evaluation API version, health endpoint, auth/TLS mode,
   retention, and isolated storage topology.
2. Apply additive business migrations and verify clean/N-1 convergence.
3. Deploy code with all new modes off and Phoenix profile optional.
4. Run B1 shadow qualification and record the gate.
5. Enable B1 shadow only; after its window and gate, run B2 shadow, then B2
   canary; after B2 rollback rehearsal, run B3 shadow, then B3 canary.
6. Enable Phoenix export independently at any stage; its outage does not force
   a business rollback.

Every step has a separate commit and a reversible configuration change. B1
rollback stops shadow writes. B2 rollback routes reads to legacy. B3 rollback
routes ranking to public. Phoenix rollback disables exporter/profile or points
the adapter to another backend. No rollback deletes immutable Evidence,
Bundle, Family, Memory, or evaluation rows. In-flight Temporal work uses the
version recorded at start and completes or terminates under its stable contract.

## Risks / Trade-offs

- [Risk] Shadow writes increase database load and storage before serving value.
  -> Deterministic sampling, per-process budgets, bounded payloads, retention,
  and explicit write metrics keep B1 measurable and stoppable.
- [Risk] A Family false positive can serve stale or semantically wrong facts.
  -> Public-only keys, versioned rationale, confidence thresholds, three-state
  freshness, legacy digest comparison, and canary rollback prevent silent use.
- [Risk] Personalization can leak private data through logs or cache keys.
  -> Scope authorization, opaque IDs, redaction before export, finite labels,
  and privacy failure gates fail closed.
- [Risk] Phoenix or OTLP outage can consume worker resources.
  -> Bounded queues/timeouts/retries, non-blocking drop policy, separate health,
  and shutdown deadlines isolate the exporter.
- [Risk] Direct OTLP couples deployment to one collector endpoint.
  -> The ObservationPort, Foundation exporter, and Phoenix evaluation gateway
  are replaceable; an OTel Collector or another backend can be inserted without
  domain changes.
- [Risk] Existing migration history may differ across installations.
  -> Probe schema state, use additive idempotent steps, test clean and N-1
  upgrades, and stop on divergent state instead of guessing.
- [Risk] Evaluation drift makes thresholds hard to compare.
  -> Pin dataset/evaluator/model/template digests and require an explicit gate
  decision for every activation.

## Open Questions

None remain that change the selected contracts, activation order, or rollback
model. Operational values such as exact Phoenix retention, queue sizes, and
per-domain freshness thresholds are configuration fixtures to be finalized in
the corresponding implementation tasks and must remain within the bounds in
the contracts.
