# ADR-0007: Domain Contract Authority

- Status: Accepted
- Date: 2026-08-19
- Owners: Architecture, Domain, Integrations, QA
- Resolves: OQ-9, OQ-10
- Normative contract: [`domain_contract_v1.json`](../../../../tests/fixtures/authority/domain_contract_v1.json)

## Decision

`domain-contract/v1` is the project-owned boundary between the shared research core and
every Domain Pack. It is independent of Pydantic AI, Temporal, MCP, FastAPI, persistence
drivers, and source SDKs. A Pack is inert until its complete manifest and implementation
pass registry validation; validation and activation are atomic.

### Required Contract Methods

Every Pack implements the following pure, typed operations. Their exact input and output
schema IDs are recorded in the authority fixture.

| Method | Responsibility | Side-effect rule |
|---|---|---|
| `describe` | Return the immutable manifest for the implementation. | No I/O. |
| `classify_constraints` | Classify every request constraint as public, personal, or unresolved. | Deterministic; an unresolved constraint cannot enter shared identity. |
| `validate_evidence` | Apply domain validity rules to standard Evidence. | No Connector or repository access. |
| `compute_features` | Derive the declared public FeatureSet from a fixed Evidence Bundle. | Pure and deterministic. |
| `score_public` | Apply the pinned public Scoring Policy to a fixed FeatureSet. | Pure, deterministic, and user-neutral. |
| `build_final_output` | Build a value that validates against the pinned Agent final output schema. | No transport rendering or persistence. |
| `map_error` | Map declared domain failures to the stable project error taxonomy. | Deterministic and exhaustive for declared errors. |

Freshness, coverage, stopping conditions, entity/relation/evidence schemas,
personalization slots, and source capabilities are immutable manifest declarations, not
hidden callback methods. The shared services evaluate those declarations. This keeps
workflow and refresh ownership in the core.

### Manifest, Discovery, And Activation

An installed Pack exposes one factory through the Python entry-point group
`food_agent.domain_packs`. The Composition Root reads a deployment allow-list and loads
entry points once at worker startup. Request data, a database row, network discovery,
directory scanning, and arbitrary module names cannot cause a Pack import.

The returned manifest must contain the domain and Pack versions, supported Contract API
range, required method schemas, domain schemas, allowed tools, final output schema,
source capability declarations, the Scoring Policy, policy profiles, and a content
digest. The registry validates, in order:

1. manifest syntax, immutable schema IDs, digest, and unique `(domain_id, pack_version)`;
2. Contract API/core compatibility and the exact required method set;
3. locally bundled JSON Schema Draft 2020-12 documents and representative examples;
4. every allowed tool's separate input and output schemas, permission, timeout, stable
   error mapping, and exact capability/version presence in the Tool Gateway registry
   snapshot; tool schemas are self-contained and may reference only their own local
   fragments, while method/domain schemas may reference documents in the sealed schema
   bundle;
5. the Agent final output schema and output example;
6. Scoring Policy purity metadata and public-only feature inputs;
7. resolution of each required source capability by an independently registered
   SourceConnector; and
8. an atomic registry snapshot publication.

Any error rejects the complete Pack version with a stable registration error. Partial
method, tool, schema, or domain activation is forbidden. A broken Pack version is
isolated from all other registered versions and domains.

### Version Selection And Task Pinning

Pack versions use SemVer. Contract compatibility is negotiated only at task admission:
the registry selects the deployment-approved active version satisfying the requested
Contract API range. A major Contract API or schema change is breaking. Additive optional
fields require a new schema version even when they remain compatible.

Before execution starts, the task input pins the exact domain ID, Pack version, manifest
digest, Contract API, every method/tool/final-output schema ID and digest, Scoring Policy
version, and referenced policy profiles. Temporal persists that immutable task input.
Worker restart, replay, retry, or registry reload must use the pins and cannot renegotiate
to the current active Pack. If pinned artifacts are unavailable or fail digest checks,
the task fails with `pinned_contract_unavailable`; it never runs with nearby semantics.
Rollback changes only admission for new tasks. In-flight tasks finish with their pins or
follow their declared failure policy.

### Allowed Tools And Agent Output

An allowed-tool declaration names a project capability and version, permission, timeout,
and a distinct strict input and output schema. The Tool Gateway computes:

```text
Pack allow-list ∩ request-subject authorization ∩ Personalization-selected subset
```

It validates input before dispatch and output before returning to the Agent. Undeclared,
unauthorized, malformed, or version-mismatched calls are stable failures and do not reach
a Connector. Framework tool objects and MCP transports terminate at adapters.

The Agent final value must validate against the pinned final output schema before result
commit or success publication. A legacy Food mapper may transform that validated value
to `food-dto/v1`; the legacy DTO is not the Domain Contract itself.

The `build_final_output` method output schema and the Agent final-output schema MUST
describe the same document shape; only their root `$id` values may differ. Registration
rejects a Pack whose two declarations diverge, so a method-valid value cannot bypass the
final publication schema.

Tool input/output and Agent final-output schemas are self-contained documents. They may
reuse local `$defs`, but they cannot depend on another bundle document. This keeps the
manifest's public validation methods identical to registration-time validation without
accepting a caller-supplied registry that could expand the trusted schema set.

### Public Extension-Point Rulings

| Candidate | Ruling |
|---|---|
| Domain Pack | Public, registered extension point governed by this Contract. |
| Agent Tool | Public only through Tool Gateway with per-tool input/output schemas. |
| SourceConnector | Public adapter extension point owned by Source Gateway, never by a Pack. |
| Media Processor / Evidence Extractor | Public registered extensions under their separate shared contracts. |
| Refresh Job declaration | Public policy/job declaration consumed by the shared coordinator; not an executable scheduler. |
| Fixed Workflow | **Not public.** Packs may select an approved workflow profile, but cannot register executable workflows or own task state. |
| Refresh Coordinator | **Not public.** There is exactly one shared coordinator and one Temporal durable runtime. |
| Scoring Policy | Controlled extension: a versioned pure deterministic function over declared public features and explicit config. It has no I/O, time, randomness, framework objects, user memory, or hidden state. Personal reranking is separate. |
| Domain Sources | Capability declarations only. A Pack may state `poi.lookup` or `review.search`; it cannot contain, construct, select by concrete class, authenticate, or retain a Connector. Source Gateway resolves capabilities independently. |

## Consequences

- Travel and later domains can add semantics without adding another Agent, workflow
  runtime, refresh coordinator, evidence library, memory system, or infrastructure stack.
- Registry snapshots and task pins make deploy, replay, canary, and rollback semantics
  reviewable.
- Scoring stays extensible without allowing arbitrary plugin I/O or user-specific changes
  to public facts.
- Missing tool/output schemas and unresolved required source capabilities fail at
  registration instead of during a production task.

## Rejected Alternatives

- Runtime package scanning or request-selected imports: rejected because discovery would
  be non-deterministic and an unsafe execution boundary.
- A Pack-owned Connector collection: rejected because it couples domain meaning to
  platform access and credentials.
- Pack-defined Fixed Workflows or Refresh Coordinators: rejected because they create a
  second task-state owner and durable runtime.
- Arbitrary scoring plugins: rejected because I/O, clock, randomness, or private memory
  would make public scores non-reproducible.
