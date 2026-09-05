## Purpose

Enable a controlled Query Family read path that reuses versioned public
Evidence when freshness and confidence permit, while preserving deterministic
matching, single-flight refresh behavior, legacy compatibility, and an
independent rollback to the existing research path.

## ADDED Requirements

### Requirement: Query Family identity is public and versioned

The system MUST compute a stable Query Family identity from the approved public
canonical query fields and a rules/schema version. User identity, session
identity, private preferences, behavior history, credentials, and account
state MUST NOT participate in the shared identity. Every match MUST retain its
normalization version, matching stage, confidence, and rationale.

#### Scenario: Personal constraints differ
- **WHEN** two requests have equal public semantics but different personal taste or budget preferences
- **THEN** the requests MUST resolve to the same eligible Query Family and defer the difference to personalization

#### Scenario: Confidence is below threshold
- **WHEN** the best family match is below the configured confidence threshold
- **THEN** the system MUST avoid serving reused Evidence and MUST return a new-family or clarification path with the match reason recorded

### Requirement: Read routing has exactly three freshness outcomes

For each eligible request, the system MUST choose exactly one of direct reuse,
incremental refresh, or new research. Direct reuse requires a fresh Bundle and
minimum coverage. Incremental refresh requires a usable but stale or partially
covered Bundle. New research is required when no eligible Family or usable
Bundle exists. The selected outcome MUST be observable without exposing private
request content.

#### Scenario: Fresh Bundle
- **WHEN** a matching Family has a current Bundle inside its freshness window and above its coverage threshold
- **THEN** the system MUST serve that Bundle and MUST NOT repeat covered source collection

#### Scenario: Partially stale Bundle
- **WHEN** only some source partitions are stale, missing, or below their watermark
- **THEN** the system MUST schedule or join an incremental refresh for those partitions and MUST preserve valid existing coverage

#### Scenario: No usable Family
- **WHEN** no Family or Bundle satisfies the match and freshness rules
- **THEN** the system MUST create a new research task rather than guessing a reuse match

### Requirement: Concurrent refreshes are single-flight and conditionally published

Requests for the same Family, refresh scope, and compatible policy MUST share a
stable durable refresh identity. At most one refresh may be active for that
identity. Bundle publication MUST be immutable and conditional on the current
version, so a late or older writer cannot replace a newer current pointer.

#### Scenario: Concurrent stale reads
- **WHEN** multiple requests concurrently encounter the same stale Family
- **THEN** all compatible requests MUST observe one refresh identity or one published result and MUST NOT start duplicate source collection

#### Scenario: Late writer loses compare-and-set
- **WHEN** a refresh attempts to publish against an older current Bundle version
- **THEN** the publication MUST be rejected as a conflict and the newer current pointer MUST remain unchanged

### Requirement: Reused results preserve public version and explainability

A reused or refreshed response MUST identify the Family, Bundle version,
freshness state, coverage state, and matching rationale through the stable
internal result contract. The public response mapper MUST preserve its existing
wire shape unless a separately approved API change exists.

#### Scenario: Reuse canary serves a candidate
- **WHEN** the read-canary gate selects a candidate Bundle
- **THEN** the system MUST serve only a contract-compatible result and MUST retain the candidate's Family and Bundle metadata for audit

#### Scenario: Legacy and candidate differ
- **WHEN** a sampled candidate digest differs from the legacy result digest
- **THEN** the system MUST record a bounded mismatch and MUST keep serving the legacy result until the canary gate explicitly permits candidate serving

### Requirement: Stale fallback is explicit and bounded

If refresh fails, the system MAY serve an older Bundle only while its age and
coverage satisfy domain limits. Such a response MUST identify its stale and
partial state. A Bundle beyond the maximum stale age or minimum coverage MUST
not be presented as a successful fresh result.

#### Scenario: Refresh failure within limits
- **WHEN** an incremental refresh fails but the current Bundle remains within stale and coverage limits
- **THEN** the system MUST return the older Bundle with an explicit stale indicator and refresh failure category

#### Scenario: Refresh failure beyond limits
- **WHEN** the current Bundle exceeds a stale or coverage limit
- **THEN** the system MUST return a stable unavailable or research-failed outcome and MUST NOT disguise it as a complete success

### Requirement: B2 activation and rollback are independent

Query Family read serving MUST be controlled by an independent default-off mode
that supports off, shadow, and canary behavior. Disabling the mode MUST stop
reuse serving and return to the legacy research reader without deleting Family,
Bundle, index, or refresh history.

#### Scenario: B2 remains shadow-only
- **WHEN** the B2 mode is shadow
- **THEN** the system MUST compute and compare a candidate while serving the legacy result

#### Scenario: B2 rollback
- **WHEN** the B2 mode changes from canary to off
- **THEN** new requests MUST use the legacy reader, and in-flight durable work MUST finish under its recorded version or terminate under a stable error contract
