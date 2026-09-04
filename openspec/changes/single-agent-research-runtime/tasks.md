## OpenSpec

- [x] Create proposal, design, and executable requirements for the single
      bounded-concurrency Agent runtime.
- [x] Validate this change with `openspec validate
      single-agent-research-runtime --strict --no-interactive`.

## Contracts and runtime

- [x] Add versioned `ResearchState`, `ResearchEvent`, semantic Action, insight,
      and source-envelope contracts with exports and validation.
- [x] Add resource-pool, budget, retry, circuit-breaker, and bounded queue
      primitives with deterministic event reduction.
- [x] Extend the typed DAG scheduler to execute independent ready actions
      concurrently while preserving dependency and budget invariants.

## Research pipeline

- [x] Refactor XHS collection to expose note-level streaming, concurrent detail
      and first-comment requests, ordered cursor pagination, and explicit gaps.
- [x] Refactor comment analysis to use bounded token-aware batch concurrency and
      stable batch-index merging without changing raw evidence.
- [x] Add deterministic entity/claim/controversy aggregation and candidate
      thresholding.
- [x] Refactor Dianping enrichment into bounded candidate pipelines with
      capability-level circuit breakers and partial profile preservation.
- [x] Add batch profile reads and idempotent evidence/profile commits.
- [x] Integrate the single runtime into `CommentFirstResearchWorkflow`; remove
      its phase barrier while preserving the public response contract.
- [x] Emit real action lifecycle progress through the existing event/SSE path.

## Verification

- [x] Add deterministic fake-source tests for overlap, maximum in-flight calls,
      cursor ordering, backpressure, cancellation, retry, and circuit breaking.
- [x] Add tests for lossless raw payloads, deterministic aggregation, duplicate
      delivery, profile/evidence isolation, and partial outcomes.
- [x] Add integration tests proving one Agent/runtime composition and one MCP
      snapshot per run.
- [x] Run strict OpenSpec validation, ruff, pyright, and the non-live test suite.
- [x] Review the final diff for prohibited multi-Agent, Gaode, and legacy
      workflow references before commit.
