## Purpose

Activate isolated, traceable user memory and personalization only after public
Evidence reuse is qualified, so context assembly and ranking can adapt to a
user without changing shared facts, crossing user boundaries, or making Redis
the authority.

## ADDED Requirements

### Requirement: Memory layers and authority are explicit

The system MUST distinguish session memory, explicit preference, inferred
preference, and strategy feedback. Each persisted memory fact MUST include its
scope, source event, status, update version, and consent/lifecycle metadata when
applicable. PostgreSQL (or the declared authoritative store) MUST be the
authority; hot windows, summaries, vectors, and caches MUST be rebuildable
derivatives.

#### Scenario: Explicit constraint
- **WHEN** a user states an explicit constraint such as a dietary exclusion
- **THEN** the system MUST persist it as explicit memory with its source event and MUST not downgrade it to an inference

#### Scenario: Inferred behavior
- **WHEN** repeated behavior produces a long-term preference inference
- **THEN** the system MUST store its confidence and inferred layer separately from explicit memory

### Requirement: Memory resolution has deterministic precedence

For a request, explicit hard constraints MUST take precedence over current
session requirements, stable explicit preferences, and inferred preferences in
that order. Strategy feedback MAY change research depth, source priorities, or
presentation, but MUST NOT bypass a higher-priority content constraint.

#### Scenario: Explicit constraint conflicts with inference
- **WHEN** inferred behavior favors a food that an explicit request excludes
- **THEN** the system MUST filter the excluded candidate rather than merely lower its rank

#### Scenario: Session request conflicts with stable preference
- **WHEN** the current session gives a different budget or audience requirement than a stable preference
- **THEN** the current session requirement MUST apply to the current request while the stable preference remains unchanged

### Requirement: User and anonymous scopes are isolated

All memory reads, writes, exports, corrections, and deletions MUST be bound to
the authorized user or anonymous session scope. Cache keys, events, logs,
traces, and responses MUST NOT reveal another scope. Anonymous memory MUST NOT
be merged across sessions; any identity claim or upgrade MUST be explicit and
auditable.

#### Scenario: Cross-user access
- **WHEN** a request asks for memory outside its authorized scope
- **THEN** the system MUST reject the operation without revealing whether the other scope exists or exposing its values

#### Scenario: Anonymous session
- **WHEN** no durable user subject is available
- **THEN** the system MUST keep memory within the current session and MUST not persist it as another user's memory

### Requirement: Context assembly is bounded and traceable

Before each model invocation, the system MUST assemble temporary context under
the active model budget. It MUST retain system/task constraints and current
hard constraints before recent messages, then choose versioned summaries,
authorized memory, and public Evidence. Trimming or summarization MUST be
deterministic enough to explain what was retained, and the assembly record MUST
reference versions without storing framework-specific messages as memory facts.

#### Scenario: Context exceeds budget
- **WHEN** recent messages, summaries, memory, and Evidence exceed the model budget
- **THEN** the system MUST trim or summarize lower-priority material while retaining hard constraints and an assembly explanation

#### Scenario: Runtime adapter changes
- **WHEN** an equivalent Agent or model adapter is selected
- **THEN** authoritative conversation and memory facts MUST remain usable while only the temporary message representation changes

### Requirement: Personalization changes only private strategy and ranking

Personalization MUST operate on the shared public candidate facts and public
scores after Evidence selection. It MAY filter, reweight, or reorder candidates
within the authorized Domain Contract capability set, but MUST NOT write public
Evidence, Query Family identity, or public scores. A personalized result MUST
identify the memory categories and strategy version used without exposing
sensitive values unless the client is authorized.

#### Scenario: Same public candidates, different users
- **WHEN** two users with different preferences read the same public Bundle
- **THEN** the system MUST preserve identical public candidate facts and MAY return different private rankings

#### Scenario: Unauthorized capability in memory
- **WHEN** a preference requests a source or tool outside the Domain Contract and subject authorization
- **THEN** the system MUST omit that capability and MUST NOT invoke it

### Requirement: Authority commit precedes derived projection

The system MUST confirm a memory write only after the authoritative transaction
commits. A post-commit outbox MUST drive cache invalidation, warm-up, summary,
and index projection. A projection carrying an older authority version MUST
not overwrite a newer one, and loss of Redis or a derived index MUST trigger a
rebuild or an explicit non-personalized path rather than a cross-user fallback.

#### Scenario: Process exits after commit
- **WHEN** the process exits after confirming an authoritative memory commit but before cache warm-up
- **THEN** a restart MUST recover the fact from authority and replay the outbox without losing or duplicating it

#### Scenario: Redis is unavailable
- **WHEN** the hot projection cannot be read or written
- **THEN** the system MUST use an authoritative read or a clearly marked non-personalized path and MUST never treat Redis as the new authority

### Requirement: Memory updates are idempotent and reversible

Repeated delivery of one user action or feedback event MUST produce one logical
memory update. Corrections, expiry, deletion, and export MUST retain a link to
the source event and affected version so a ranking or context decision can be
investigated without restoring deleted private values.

#### Scenario: Duplicate feedback
- **WHEN** the same feedback event is delivered more than once
- **THEN** the system MUST apply it once and MUST NOT inflate inferred confidence

#### Scenario: User correction
- **WHEN** a user corrects or deletes a preference
- **THEN** future assemblies MUST exclude the superseded value while the audit record preserves only the authorized lifecycle metadata

### Requirement: B3 exposure is independently controllable

Personalization MUST support off, shadow, and canary exposure independent of
B1 and B2. In shadow mode it MUST compute bounded comparison observations while
serving the public ranking. In canary mode it MAY serve sampled personalized
rankings only after isolation, authority, and fallback gates pass. Turning B3
off MUST stop personalized serving and retain authoritative memory for future
rebuild.

#### Scenario: Shadow evaluation
- **WHEN** B3 is in shadow mode and a request is sampled
- **THEN** the system MUST compare public and personalized ordering without exposing private values or changing the served ranking

#### Scenario: B3 rollback
- **WHEN** B3 is disabled during a canary
- **THEN** new requests MUST use the public ranking, while authoritative memory and already committed outbox events remain intact
