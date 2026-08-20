# Architecture Decision Index

Status: Active

Change: `define-modular-architecture`

Last reviewed: 2026-08-21

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
| ADR-0009 | Disposition of legacy schema, task-state, persistence, deployment, and documentation gaps | Architecture + API + Data Platform + Platform + Frontend | [ADR-0009](./ADR-0009-legacy-gap-disposition.md) |
| ADR-0010 | Source outcome taxonomy, source-ready query projection, and legacy client projection | Evidence + API + Architecture + QA | [ADR-0010](./ADR-0010-source-outcome-legacy-projection.md) |

## Dependency Qualification Ledger

Upstream and distribution metadata were rechecked on 2026-08-21 against the
linked official documentation/repositories and the Python Package Index JSON
metadata. `uv.lock` was resolved for CPython 3.12 and currently contains 117
packages with SHA-256
`8301f2b046290c4e65a8ffdacafce7844d1f8da6e414df003809e161931cccff`.
`uv lock --check` and a frozen Python 3.12 environment both resolve the exact
versions below.

"Active, compatibility-pinned" means upstream has a newer compatible or major
release, but this change deliberately retains the version exercised by the S3
contract suite. Moving that pin requires an explicit dependency review,
lockfile diff, release/security review, and the same owner-approved contract
and rollback evidence; it is not folded into a structural milestone.

| Component | Exact locked version | Official source | Upstream status at check | License | Upgrade/security owner | Reproducible spike result |
|---|---:|---|---|---|---|---|
| Pydantic AI Slim | `2.5.1` | [docs](https://pydantic.dev/docs/ai/overview/) / [releases](https://github.com/pydantic/pydantic-ai/releases) | Active, compatibility-pinned (`2.32.1` available) | MIT | AI Platform | Import/provider and disabled-binding contracts; [S3 record](../verification/s3-gateways-foundation.md) |
| Temporal Python SDK | `1.31.0` | [docs](https://docs.temporal.io/develop/python) / [source](https://github.com/temporalio/sdk-python) | Active; locked release was current | MIT | Platform Runtime | Three queue declarations, deterministic payload, disabled connect/start; full replay qualification remains `1.20`/B0 |
| SQLAlchemy | `2.0.52` | [asyncio docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) | Active; locked release was current | MIT | Data Platform | Single-engine/UoW ownership and rollback/close contract |
| asyncpg | `0.31.0` | [source](https://github.com/MagicStack/asyncpg) | Active; locked release was current | Apache-2.0 | Data Platform | SQLAlchemy asyncpg URL normalization with no second target pool |
| Alembic | `1.19.1` | [docs and changelog](https://alembic.sqlalchemy.org/en/latest/) | Active; locked release was current | MIT | Data Platform | Sole-authority import/DDL gate; S3 creates no revision or runtime DDL |
| redis-py | `7.4.0` | [asyncio docs](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html) / [releases](https://github.com/redis/redis-py/releases) | Active, compatibility-pinned (`8.1.0` available) | MIT | Platform Runtime | 20-message/24-hour and 1000-event/1-hour target contracts; no lock/lease/durable-state API |
| boto3 | `1.43.75` | [S3 guide](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3.html) / [source](https://github.com/boto/boto3) | Active; locked release was current | Apache-2.0 | Platform Storage | Lazy client, bounded async boundary, multipart/content-hash, lifecycle and missing-object contracts |
| OpenTelemetry API/SDK | `1.44.0` | [Python docs](https://opentelemetry.io/docs/languages/python/instrumentation/) / [source](https://github.com/open-telemetry/opentelemetry-python) | Active; locked release was current | Apache-2.0 | SRE | Correlation allow-list/hash and disabled composition bootstrap |
| OTel FastAPI/httpx/Redis/SQLAlchemy instrumentation | `0.65b0` each | [contrib source](https://github.com/open-telemetry/opentelemetry-python-contrib) | Active; locked releases were current | Apache-2.0 | SRE | Idempotent instrumentation registration; existing `/metrics` semantics unchanged |
| pgvector Python | `0.4.2` | [source](https://github.com/pgvector/pgvector-python) | Active, compatibility-pinned (`0.5.0` available) | MIT | AI Platform + Data Platform | Dependency/ownership gate only; no S3 vector read, write, profile, or schema activation |
| Prometheus client | `0.25.0` | [docs](https://prometheus.github.io/client_python/) / [source](https://github.com/prometheus/client_python) | Active, compatibility-pinned (`0.26.0` available) | Apache-2.0 AND BSD-2-Clause | SRE | Metric label allow-list/cardinality contract; no metric rename |
| Pydantic Settings | `2.13.1` | [docs](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) / [source](https://github.com/pydantic/pydantic-settings) | Active, compatibility-pinned (`2.15.0` available) | MIT | Platform Runtime | Frozen owner views, `MODULAR_` parsing, and import-time no-client contract |

PostgreSQL 16, Redis Server 7.4, Temporal Service, and S3-compatible/MinIO
services are accepted runtime baselines rather than Python lock entries. Their
exact deployment image digests and full-stack qualification are release and
B0-B4 gates. MCP SDK and BGE-M3 runtime packages are likewise added only when
their owning behavioral milestone activates them. This staged packaging does
not reopen ADR-0002 or permit a second implementation for the same role.

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
| 18 | Versioning policy for mixed camelCase/snake_case DTOs | API + Domain | S0 | S2, S4 | Accepted | [ADR-0005](./ADR-0005-food-dto-identity-authority.md) + [ADR-0009 writer-path correction](./ADR-0009-legacy-gap-disposition.md) |
| 19 | Historical `turn_id` migration state and Alembic baseline/stamp disposition | Data Platform | B1 | B1 | Accepted (disposition) | [ADR-0009](./ADR-0009-legacy-gap-disposition.md) + [schema fixtures](../../../../tests/fixtures/database/search_results_schema_contract.json) |
| 20 | Restaurant entity/view/result ownership and stable identity | Domain + Data | S0 | S4, B1 | Accepted | [ADR-0005](./ADR-0005-food-dto-identity-authority.md) |
| 21 | Disposition of known search history, terminal-state, refine replay, and live persistence defects | API | S0 | S2, B0 | Accepted | [ADR-0009](./ADR-0009-legacy-gap-disposition.md) |
| 22 | Legacy client mapping for source failure: error, partial, or empty success | API + Evidence | S3 | S3, B1 | Accepted | [ADR-0010](./ADR-0010-source-outcome-legacy-projection.md) + [core spec](../specs/modular-research-core/spec.md) |
| 23 | Long-term support boundary for Python exports, injection points, and examples | Architecture + SDK | S0 | S1 | Accepted | [ADR-0005](./ADR-0005-food-dto-identity-authority.md) |
| 24 | Disposition of CORS, frontend, SSE configuration, and container delivery differences | Platform + Frontend | B0 | Release gate | Accepted (independent change) | [ADR-0009](./ADR-0009-legacy-gap-disposition.md) + [deployment fixture](../../../../tests/fixtures/characterization/configuration_deployment_contract.json) |
| 25 | Supported macOS/arm64 and browser probe matrix | Build + QA | S0 | Release gate | Accepted | [ADR-0003](./ADR-0003-runtime-support-matrix.md) |
| 26 | Food equivalence rule and approval of nondeterministic fixture updates | Domain + QA | S4 | S4, B2 | Accepted | [ADR-0005](./ADR-0005-food-dto-identity-authority.md) |
| 27 | Recovery or replacement of missing `internal-docs/*` references | Architecture | S0 | Documentation cleanup | Accepted (independent change) | [ADR-0009](./ADR-0009-legacy-gap-disposition.md) |
| 28 | Explicit refresh API, authorization, in-flight merge, and SSE mapping | API + Evidence | B2 | B2 | Open | [core spec](../specs/modular-research-core/spec.md) |

## Accepted Infrastructure Is Not Open

Agent runtime, durable workflow, database authority, cache boundaries, embedding profile, object-store API, observability, MCP boundary, and Python toolchain are accepted in [ADR-0002](./ADR-0002-infrastructure-baseline.md). Operational parameters represented by OQ-11 and OQ-12 do not reopen those product selections.
