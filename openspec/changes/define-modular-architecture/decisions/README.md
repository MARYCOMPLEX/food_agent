# Architecture Decision Index

Status: Active

Change: `define-modular-architecture`

Last reviewed: 2026-08-19

This index is the authority gate for the change. An unresolved question blocks only the milestones listed in its row. Owners are accountable roles; a named assignee can be added when implementation work is scheduled.

## Decision Rules

- Observable behavior is governed by the capability specs.
- Implementation choices are governed by accepted ADRs and `design.md`.
- Current code and tests are evidence of legacy behavior, not automatic target behavior.
- A question moves to `Accepted` only when its ADR includes fixtures or other reproducible evidence.
- A milestone cannot close while a question listed as its blocker remains `Open` or `Investigating`.

## Accepted Decisions

| ID | Decision | Owner | Evidence |
|---|---|---|---|
| ADR-0001 | Specification authority and versioned architecture references | Architecture | [ADR-0001](./ADR-0001-specification-authority.md) |
| ADR-0002 | Approved infrastructure and framework baseline | Architecture + Platform | [ADR-0002](./ADR-0002-infrastructure-baseline.md) |
| ADR-0003 | Runtime and platform support matrix | Build + Release + QA | [ADR-0003](./ADR-0003-runtime-support-matrix.md) |
| ADR-0004 | HTTP route/envelope authority and canonical SSE v1 | API + Frontend | [ADR-0004](./ADR-0004-http-sse-authority.md) |
| ADR-0005 | Food DTO, restaurant identity, Python exports, and result equivalence | API + Domain + Data + SDK + QA | [ADR-0005](./ADR-0005-food-dto-identity-authority.md) |
| ADR-0006 | Canonical Query, Family matching contract, freshness policy schema, and Evidence governance | Domain + Evidence + Data Governance | [ADR-0006](./ADR-0006-query-evidence-authority.md) |
| ADR-0007 | Domain Contract method, discovery, version pinning, tools, output, and extension boundaries | Architecture + Domain + Integrations + QA | [ADR-0007](./ADR-0007-domain-contract-authority.md) |
| ADR-0008 | Four-layer memory, identity isolation, consent, lifecycle, and feedback privacy | Product + Privacy + Security + Data Platform + QA | [ADR-0008](./ADR-0008-memory-privacy-authority.md) |

## Open Question Register

| OQ | Decision needed | Accountable owner | Due before | Blocks | Status | Evidence |
|---|---|---|---|---|---|---|
| 1 | Domain-neutral naming versus Food-specific diagram labels | Architecture | S1 | S1, S4 | Accepted | [ADR-0001](./ADR-0001-specification-authority.md) |
| 2 | Repository location and versioning of the HTML and Draw.io sources | Architecture | S0 | S0 documentation gate | Accepted | [ADR-0001](./ADR-0001-specification-authority.md) |
| 3 | Authority for the missing Experience internal subgraph | Architecture + API | S1 | S1, S2 | Accepted | [ADR-0001](./ADR-0001-specification-authority.md) |
| 4 | Whether `audience` participates in exact identity, similarity, or reranking | Domain + Evidence | S1 | S1, B2 | Accepted | [ADR-0006](./ADR-0006-query-evidence-authority.md) |
| 5 | Canonical Query enums, normalization, defaults, locale, and constraint classification | Domain + Evidence | S1 | S1, B1 | Accepted | [ADR-0006](./ADR-0006-query-evidence-authority.md) |
| 6 | Qualify trigram/vector thresholds and ambiguity margins; matching order, low-confidence behavior, merge/split, aliases, and correction contract are accepted | Evidence | B2 | B2 | Open (values only) | [ADR-0006](./ADR-0006-query-evidence-authority.md) |
| 7 | Approve Food/Travel freshness/coverage values and B4 scheduler weights; policy schema, watermark, popularity, and priority inputs are accepted | Domain + Evidence | B2 | B2, B4 | Open (values only) | [ADR-0006](./ADR-0006-query-evidence-authority.md) |
| 8 | Evidence, Bundle, locator, media, derived artifact, license, visibility, retention, and deletion schemas | Evidence + Data Governance | S1 | S1, B1, B4 | Accepted | [ADR-0006](./ADR-0006-query-evidence-authority.md) |
| 9 | Domain Contract method set, discovery, negotiation, compatibility, tools, and output | Architecture + Domain | S1 | S1, S4, B5 | Accepted | [ADR-0007](./ADR-0007-domain-contract-authority.md) |
| 10 | Whether fixed workflows, scoring policies, domain sources, and refresh coordination are public extension points | Architecture + Domain | S1 | S1, S3, S4, B4, B5 | Accepted | [ADR-0007](./ADR-0007-domain-contract-authority.md) |
| 11 | Refresh retry budget, backoff, priority, timeout, cancellation, and exhausted-run handling | Platform + Evidence | B4 | B4 | Open | [core spec](../specs/modular-research-core/spec.md) |
| 12 | Object encryption, retention, orphan cleanup, and signed URL policy | Platform + Security | B4 | B4 | Open | [query reuse spec](../specs/query-family-evidence-reuse/spec.md) |
| 13 | Memory scope, consent, expiry, correction, export, and deletion semantics | Product + Privacy | S1 | S1, B3 | Accepted | [ADR-0008](./ADR-0008-memory-privacy-authority.md) |
| 14 | Privacy threshold for feedback that may influence public refresh priority | Privacy + Evidence | B3 | B3, B4 | Accepted | [ADR-0008](./ADR-0008-memory-privacy-authority.md) |
| 15 | Tenant, cohort, locale, visibility isolation, and anonymous-to-user migration | Security + Data | S1 | S1, B1, B2, B3 | Accepted | [ADR-0008](./ADR-0008-memory-privacy-authority.md) + [ADR-0006](./ADR-0006-query-evidence-authority.md) |
| 16 | Authority and deprecation for unified search versus documented legacy routes | API | S0 | S2 | Accepted | [ADR-0004](./ADR-0004-http-sse-authority.md) |
| 17 | Authority for envelopes, pagination, SSE replay, step IDs, and error fields | API + Frontend | S0 | S2 | Accepted | [ADR-0004](./ADR-0004-http-sse-authority.md) |
| 18 | Versioning policy for mixed camelCase/snake_case DTOs | API + Domain | S0 | S2, S4 | Accepted | [ADR-0005](./ADR-0005-food-dto-identity-authority.md) |
| 19 | Historical `turn_id` migration state and Alembic baseline/stamp | Data Platform | B1 | B1 | Investigating | [`migrate_turn_id.py`](../../../../scripts/migrate_turn_id.py) |
| 20 | Restaurant entity/view/result ownership and stable identity | Domain + Data | S0 | S4, B1 | Accepted | [ADR-0005](./ADR-0005-food-dto-identity-authority.md) |
| 21 | Disposition of known search history, terminal-state, and refine replay defects | API | S0 | S2, B0 | Investigating | [design compatibility ledger](../design.md#known-incompatible-current-expectations) |
| 22 | Legacy client mapping for source failure: error, partial, or empty success | API + Evidence | S3 | S3, B1 | Investigating | [core spec](../specs/modular-research-core/spec.md) |
| 23 | Long-term support boundary for Python exports, injection points, and examples | Architecture + SDK | S0 | S1 | Accepted | [ADR-0005](./ADR-0005-food-dto-identity-authority.md) |
| 24 | Target topology for CORS, frontend, SSE configuration, and container delivery | Platform + Frontend | B0 | B0, B4, Release gate | Investigating | [design compatibility ledger](../design.md#known-incompatible-current-expectations) |
| 25 | Supported macOS/arm64 and browser probe matrix | Build + QA | S0 | Release gate | Accepted | [ADR-0003](./ADR-0003-runtime-support-matrix.md) |
| 26 | Food equivalence rule and approval of nondeterministic fixture updates | Domain + QA | S4 | S4, B2 | Accepted | [ADR-0005](./ADR-0005-food-dto-identity-authority.md) |
| 27 | Recovery or replacement of missing `internal-docs/*` references | Architecture | S0 | S0 documentation gate | Investigating | [design Open Questions](../design.md#open-questions) |
| 28 | Explicit refresh API, authorization, in-flight merge, and SSE mapping | API + Evidence | B2 | B2 | Open | [core spec](../specs/modular-research-core/spec.md) |

## Accepted Infrastructure Is Not Open

Agent runtime, durable workflow, database authority, cache boundaries, embedding profile, object-store API, observability, MCP boundary, and Python toolchain are accepted in [ADR-0002](./ADR-0002-infrastructure-baseline.md). Operational parameters represented by OQ-11 and OQ-12 do not reopen those product selections.
