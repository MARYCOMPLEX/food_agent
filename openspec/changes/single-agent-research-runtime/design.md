## Decision

Implement one `FoodResearchAgent` backed by a deterministic, in-process
`ResearchRuntime`. The runtime uses `asyncio.TaskGroup` (or an equivalent
structured-concurrency implementation), bounded queues, and typed reducers.
It is a pipeline executor, not a collection of cooperating Agents.

```text
FoodResearchAgent
  -> IntentParser
  -> ResearchPlanner (semantic actions, bounded replans)
  -> ResearchRuntime
       -> pinned ManagedMcpToolSession
       -> XHS evidence producer
       -> comment insight producer
       -> deterministic entity/controversy reducer
       -> Dianping profile producer
       -> evidence/profile committers
  -> answer composer + evidence validator
```

The runtime owns one immutable run configuration and one mutable
`ResearchState`. Every state transition is represented by a typed event and
reduced in a deterministic order. Workers are ordinary async functions with no
independent prompt, memory, or tool catalog.

## Action model and planning

The Planner can emit only `SearchNotes`, `FetchNoteEvidence`,
`AnalyzeCommentBatch`, `ExpandResearch`, `EnrichShopProfile`, `Synthesize`, or
`StopResearch`. Each action contains an id, dependencies, idempotency key,
resource class, input contract, and reason. An action is validated against the
run's MCP capability snapshot, budget, and state before dispatch. The executor
maps semantic actions to source ports; the Agent never receives provider tool
JSON.

The initial plan starts with up to the configured high-information XHS query
variants. Replanning occurs only after a collection wave or a typed gap, and
is bounded by `max_replans`. The Planner cannot schedule Dianping enrichment
until a candidate has an XHS evidence threshold, except for an explicit
profile-only operation (which is outside this food research route).

## Pipeline and concurrency

1. Search variants run concurrently under `xhs.search` limits.
2. Each accepted note is put on an evidence queue. Its detail request and
   first comments page may run concurrently; subsequent cursor pages remain
   ordered and are deduplicated by stable comment id.
3. Completed notes are put on an analysis queue. Comment batches run with a
   global, token-aware LLM limiter and merge by batch index.
4. Insight records are merged by deterministic code into entities, claims, and
   a controversy graph. Raw comments remain in the evidence store.
5. Candidates crossing the configured evidence threshold enter a profile
   queue. Candidate searches are concurrent; detail/review calls are
   independently bounded and protected by capability-level circuit breakers.
6. Profile cache reads and evidence writes use batch ports. Writes are
   idempotent and serialized where the backing store requires ordering.
7. Synthesis starts only after the minimum evidence barrier and a best-effort
   profile wave; it receives claims plus selected evidence references and must
   pass evidence validation before success is published.

The runtime has separate resource pools for XHS search/detail/comments, LLM,
Dianping search/detail/reviews, and persistence. A single MCP snapshot is
shared by all actions in a run; discovery is never repeated by a worker.

## Contracts and losslessness

Introduce versioned contracts for `ResearchState`, `ResearchEvent`, semantic
actions, `SourceEnvelope`, and `CommentInsight`. `SourceEnvelope` carries the
provider response, normalized items, cursor, completeness, warnings, and raw
payload. Unknown provider fields stay in the opaque payload/extra map.

Evidence identity is `platform + note_id + comment_id`; profile identity uses
provider and shop id, with a deterministic name fallback. A reducer must be
commutative for independent events and apply stable sorting before output. A
failed or cancelled action appends a `ResearchGap`; it never overwrites a
successful item with an empty value. Reaching a configured budget produces a
partial result with continuation metadata.

## Failure, backpressure, and cancellation

Queues are bounded. When a downstream queue is full, producers wait rather
than loading the entire corpus into memory. A single item failure is isolated;
the run cancels only dependent actions. Run cancellation propagates through
all child tasks and closes the pinned MCP session exactly once. Retries are
limited to typed retryable errors and consume the same budget as the original
call.

Dianping verification trips only the affected capability breaker. Successful
search fields and all XHS evidence remain usable. A profile can be `partial`
with gaps; it cannot be represented as a successful empty profile.

## Observability and rollout

Emit action lifecycle events containing run id, action id, resource class,
queue wait, duration, attempt, outcome, item counts, completeness, and budget
usage. Add metrics for in-flight concurrency, cache hit rate, deduplication,
LLM tokens, gaps, replans, and provider challenges.

The runtime is the only active route. Configuration controls pool sizes,
queue limits, batch size, token budget, deadlines, and replan count. Tests use
fake MCP/source ports with deterministic delays to prove overlap, bounds,
ordering, cancellation, idempotence, and no data loss.
