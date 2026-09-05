## Purpose

Provide a replaceable Agent observability and evaluation capability using
OpenTelemetry contracts and Phoenix OSS as the first backend, with bounded,
redacted telemetry, resilient export, reproducible evaluations, and no effect
on business authority or request outcomes.

## ADDED Requirements

### Requirement: Observability boundaries are consistent

The system MUST emit correlated observations for an Agent run, model call,
MCP/tool call, source Connector call, Evidence transformation, Query Family
read or refresh, Memory/context assembly, ranking decision, and Temporal task
boundary when those operations execute. Correlation MUST use bounded opaque
identifiers and MUST preserve parent-child context across asynchronous work.
Workflow code MUST remain deterministic and MUST NOT perform exporter network
calls; propagation across a workflow/activity boundary MUST be handled by the
worker-side integration.

#### Scenario: End-to-end research run
- **WHEN** a research task invokes a model, an MCP tool, and a source Connector
- **THEN** the resulting observations MUST share the task/workflow correlation context and MUST identify each boundary without embedding raw payloads

#### Scenario: Temporal activity retry
- **WHEN** an Activity retries
- **THEN** each attempt MUST be distinguishable by bounded attempt metadata while the workflow correlation remains stable

#### Scenario: Workflow replay
- **WHEN** a Temporal Workflow replays its history
- **THEN** replay MUST produce the same workflow decisions without making an OTel or Phoenix network call

### Requirement: Production telemetry is redacted by default

Production traces, logs, metrics, and evaluation exports MUST exclude prompts,
queries, model outputs, raw MCP arguments/results, cookies, tokens, QR data,
account state, private preference values, session messages, and note text by
default. Identifiers MUST be allow-listed, bounded, and opaque; metric labels
MUST use a finite vocabulary and MUST NOT contain user or request IDs. The
sanitizer MUST run both before span creation and immediately before
export/upload, and MUST recursively inspect automatic instrumentation fields
including headers, URL paths, resource attributes, exception events, and body
fields. Unknown or unclassifiable values MUST be dropped rather than passed
through.

#### Scenario: Sensitive attribute supplied
- **WHEN** instrumentation receives an attribute whose key or value may contain a secret or private content
- **THEN** the exporter boundary MUST drop or hash it before export and MUST retain only an allowed bounded classification

#### Scenario: Unbounded metric label
- **WHEN** code attempts to attach free text or an identifier as a metric label
- **THEN** the metric adapter MUST reject the label and MUST leave the business operation unaffected

#### Scenario: Automatic HTTP span contains a header
- **WHEN** an automatic HTTP instrumentation span contains an authorization, cookie, signed URL, or request-body field
- **THEN** the sink sanitizer MUST remove it before any exporter or evaluation upload can observe it

### Requirement: Phoenix is an optional backend behind project-owned ports

Phoenix OSS MUST be deployable as an optional observability/evaluation backend
through the project-owned observation and evaluation ports. Phoenix-specific
types, URLs, and storage models MUST NOT cross domain, application, API, or
public contract boundaries. PostgreSQL business tables and Temporal history
remain authoritative, and Phoenix storage MUST be isolated from business data.
The application MUST reach Phoenix only through OTLP or its documented HTTP
API; it MUST NOT write Phoenix tables directly or receive Phoenix database
credentials. A no-op backend MUST be available for disabled or failed Phoenix
deployments.

#### Scenario: Phoenix profile disabled
- **WHEN** the Phoenix deployment profile or exporter is disabled
- **THEN** the application MUST start and serve business requests using existing Prometheus metrics and local diagnostics without requiring Phoenix

#### Scenario: Phoenix receives an observation
- **WHEN** a valid sampled observation is exported with Phoenix enabled
- **THEN** Phoenix MUST receive an OpenTelemetry-compatible record through the observation port, while no business transaction waits for Phoenix persistence

#### Scenario: Phoenix API version mismatch
- **WHEN** Phoenix reports an unsupported API or protocol version
- **THEN** the adapter MUST report a stable unhealthy or blocked outcome and MUST keep the no-op/business path available without changing domain behavior

### Requirement: Export failure is non-authoritative and bounded

Telemetry export MUST use bounded queues, batching, timeouts, retry limits, and
graceful shutdown flush. Exporter outage, queue saturation, malformed
telemetry, or Phoenix outage MUST never fail, delay beyond the configured
budget, duplicate, or alter a user request, task state, Evidence Bundle,
Memory authority, or ranking result. Such conditions MUST be visible through
bounded health metrics and logs.

#### Scenario: Phoenix is unavailable
- **WHEN** the Phoenix endpoint is unavailable during a request
- **THEN** the request MUST complete according to its business dependencies, the observation MAY be dropped after bounded retry, and an exporter-health signal MUST be recorded

#### Scenario: Queue is saturated
- **WHEN** the telemetry queue reaches its configured bound
- **THEN** the exporter MUST apply the declared drop policy, increment a bounded saturation metric, and MUST not apply backpressure to the business authority

#### Scenario: Phoenix authorization or server error
- **WHEN** the Phoenix endpoint returns 401, 403, 404, 429, or a 5xx response
- **THEN** the adapter MUST map it to a stable observability health outcome, apply bounded retry policy, and MUST NOT raise it into the request path

### Requirement: Sampling and shutdown are deterministic enough to operate

Sampling, batch limits, timeout, retry, and shutdown flush settings MUST be
explicitly configurable with safe defaults and exposed in redacted health
metadata. Shutdown MUST make a bounded flush attempt and MUST report whether
the attempt completed, timed out, or was skipped; it MUST not hold process
shutdown indefinitely.

#### Scenario: Graceful shutdown
- **WHEN** the application receives a normal shutdown signal with queued observations
- **THEN** it MUST attempt one bounded flush and report the result without blocking past the configured deadline

#### Scenario: Malformed telemetry
- **WHEN** a span or evaluation record fails schema validation
- **THEN** the adapter MUST drop that record, classify the validation error, and continue exporting other records

### Requirement: Evaluation is reproducible and separated from serving

The system MUST support versioned offline evaluation datasets, immutable input
digests, deterministic evaluators for contract/quality properties, and an
optional LLM judge whose model and prompt-template versions are recorded. A
judge result MUST NOT directly mutate production Evidence, Memory, scores, or
serving configuration; promotion requires an explicit gate decision. The
repository-owned fixture and digest MUST be the reproducible gate authority;
Phoenix receives a projection and MUST NOT be the only copy. Dataset cases MUST
be synthetic or explicitly redacted, and production traces MUST NOT become a
dataset without a separate authorized privacy/export step.

#### Scenario: Deterministic evaluator rerun
- **WHEN** the same dataset, evaluator version, and configuration are evaluated twice
- **THEN** the evaluator MUST produce the same result digest and per-case outcome

#### Scenario: LLM judge evaluates a sample
- **WHEN** an authorized offline run invokes the LLM judge
- **THEN** the result MUST include dataset, model, rubric, and template versions and MUST remain an evaluation artifact until explicitly approved

#### Scenario: Phoenix dataset projection is lost
- **WHEN** a Phoenix dataset or experiment projection is unavailable or deleted
- **THEN** the system MUST retain the immutable repository fixture and digest required to reproduce the qualification run

### Requirement: Evaluation gates cover all activation milestones

The qualification suite MUST include B1 shadow parity/privacy/provenance,
B2 match/freshness/CAS/stale fallback, B3 precedence/isolation/authority/cache
recovery, and observability redaction/export-failure cases. Each milestone
MUST have an independently recorded pass threshold, failure-injection result,
and rollback decision before its serving mode is enabled. A qualification
report MUST be `pass`, `fail`, or `blocked`; missing dataset, evaluator,
threshold, explicit approval, or required Phoenix ingestion evidence MUST be
`blocked`, never `pass`. Approval MUST be bound to the dataset digest, code
revision, model/provider, pack/core versions, evaluator versions, thresholds,
and expiry.

#### Scenario: B2 gate has a privacy failure
- **WHEN** a qualification run detects private data in a candidate trace or Family key
- **THEN** the B2 gate MUST fail and MUST keep B2 in legacy or shadow mode until the issue is corrected and rerun

#### Scenario: All gates pass
- **WHEN** the declared test, evaluation, migration, and failure-injection gates pass for a milestone
- **THEN** an operator MAY enable only that milestone's serving mode while later milestones remain independently disabled

#### Scenario: Required Phoenix evidence is missing
- **WHEN** a release manifest requires Phoenix ingestion evidence but the backend is unavailable or the evidence digest is missing
- **THEN** the milestone report MUST be `blocked` even though the application may continue serving its business path

### Requirement: Backend replacement preserves the observation contract

Any future observation or evaluation backend MUST implement the same project-owned
ports, redaction policy, correlation fields, bounded delivery semantics, and
evaluation artifact schema. Replacing Phoenix MUST NOT require changes to
domain modules, Agent workflow contracts, API payloads, or business storage.

#### Scenario: Replace Phoenix exporter
- **WHEN** a second backend is configured behind the observation port
- **THEN** the same redacted observations and evaluation artifacts MUST remain valid and business behavior MUST remain unchanged
