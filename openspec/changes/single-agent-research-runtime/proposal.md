## Why

The comment-first Food Agent already uses limited fan-out, but the active
workflow still has phase barriers and several unbounded or serial sections:
one note's LLM batches run serially, note analysis waits for collection to
finish, and profile enrichment is not scheduled as a shared resource. This
increases wall-clock latency for the large comment corpus that is the product's
primary signal and makes partial failures difficult to explain.

## What Changes

- Keep exactly one logical Food Research Agent and one conversation-aware
  workflow.
- Add a typed `ResearchState` and semantic action model used by a bounded
  in-process runtime; the model may choose the next action, but never raw MCP
  names or unvalidated arguments.
- Replace phase barriers with a producer/consumer pipeline: XHS note evidence
  collection, comment analysis, deterministic entity/controversy aggregation,
  and Dianping profile enrichment run as soon as their dependencies are ready.
- Add independent concurrency, rate, timeout, retry, and circuit-breaker
  budgets for each external resource class.
- Preserve every raw provider envelope, comment, cursor, completeness marker,
  and gap. Parallel execution MUST be lossless, idempotent, and reproducible.
- Batch evidence writes and profile reads/updates through explicit ports while
  keeping evidence and durable shop profiles as separate authorities.
- Emit actual internal progress events as work completes rather than only
  reporting completed top-level phases.
- Remove no new compatibility route and do not add multi-Agent orchestration.

## Goals

- Reduce research wall-clock time without reducing comment coverage or source
  fidelity.
- Make every concurrent action reviewable through typed inputs, outputs,
  dependencies, and budget accounting.
- Allow the single Agent to replan a bounded number of times from observed
  gaps and candidate coverage.
- Keep the existing public food response and evidence/profile ownership
  semantics stable unless an additive metadata field is required.

## Non-Goals

- No second Agent, Agent handoff, autonomous worker conversation, or per-tool
  LLM Agent.
- No lossy summary in place of raw comments or provider payloads.
- No arbitrary distributed queue, new orchestration framework, or browser
  automation in this change.
- No change to the authority of Xiaohongshu comments as primary evidence or
  Dianping as secondary structured profile source.

## Impact

The change affects research contracts, the active workflow, source adapters,
the analyzer, scheduler/runtime primitives, evidence/profile ports, event
projection, configuration, and focused tests. Existing MCP catalog snapshots,
conversation semantics, and profile/evidence persistence boundaries remain the
composition-root responsibilities.
