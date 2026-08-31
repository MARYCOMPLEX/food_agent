# Compatibility Ledger — Platform Source Connectors

**Repository fixture:** `C:\Users\14158\Documents\ChatGPT\fagent\food_agent`
**Recorded branch:** `codex/integrate-platform-source-connectors`
**Recorded date:** 2026-08-31
**Compatibility rule:** additive first; legacy behavior remains the default
until a separately approved flag/canary changes traffic.

This ledger is the contract-level map between the existing application and the
new Dianping/Spider_XHS integration. “Target” identifies the project-owned
boundary, not an assertion that production traffic is already enabled.

## 1. Runtime and entry-point ledger

| Concern | Existing / legacy path | Target path | Default and switch | Rollback guarantee |
|---|---|---|---|---|
| HTTP edge | `src/api/main.py`, `api/search`, history/favorites/user routers | same FastAPI process; platform readiness is exposed through Composition Root | unchanged unless platform flags are supplied | existing REST/SSE routes and response contracts stay intact |
| Composition | `build_legacy_composition_root()` and legacy registries | dedicated `platform` registry via `composition/platform_bindings.py` | `MODULAR_PLATFORM_CONNECTORS_ENABLED=false` | disable flag; no public pointer rewrite |
| Search use case | legacy task facade / current research coordinator wiring | account-bound gateway can be called by a later use-case adapter | no implicit route switch | legacy connector remains resolvable |
| Durable execution | Temporal target adapters are opt-in; legacy in-process task path remains | same Temporal service, with optional `account-auth` queue | queue must be explicitly configured and enabled | drain queue; retain Temporal history |
| Agent runtime | legacy agents and LangChain-compatible LLM adapter remain | Pydantic AI V2 runtime behind project ports | target milestone/flag, not a provider requirement | revert composition binding |
| Provider process | existing `xhs.compat` facade and project auth helpers | typed Dianping/XHS bridges, optionally a sidecar | per-platform flags + dependency gate | route new requests to `xhs_compat` |

## 2. Source and capability ledger

| Capability | Legacy source | Target source/version | Collision rule | Data compatibility |
|---|---|---|---|---|
| `place.lookup` | `place_compat` / Amap (`amap-connector/v1`) | `dianping` / `dianping-platform/v1` | `PlatformCapabilityRegistry.resolve()` requires explicit source/version when both are enabled | canonical place/document fields; provider IDs remain opaque |
| `reviews.search` | `xhs_compat` (`xhs-connector/v1`) | `dianping` and `xhs` (`platform-capability/v1`) | duplicate enabled snapshots are rejected; no silent replacement | canonical comments and stable error categories |
| `notes.search` | legacy XHS tool facade | `xhs` through `xhs_pc` channel | explicit source ID plus account channel | canonical documents, bounded cursor |
| `media.refs` | legacy provider-specific photo fields | `dianping` or `xhs` platform adapter | source/version selection required | stable media refs only; bytes go to ObjectStore/Media workflow |
| Creator publish/upload | none registered as a canonical capability | deliberately unregistered | invocation rejected before provider call | no compatibility promise; scope remains read/health |

`xhs_pc` and `xhs_creator` share public source ID `xhs` for evidence/source
identity, but their account namespaces, session versions, leases, signer state,
and health records remain independent.

## 3. Identity, account, and secret ledger

| Boundary | Existing behavior | Target contract | Compatibility / migration note |
|---|---|---|---|
| Public query identity | `CollectRequest`, `SourceLocator`, Query Family | unchanged | account selection is never appended to family identity |
| Account key | environment cookie/profile or singleton legacy auth | `(tenant_id, platform_channel, account_ref)` | aliases may repeat across channels/tenants without collision |
| Session storage | legacy profile/flat cookie paths may exist for compatibility | PostgreSQL session row with AES-GCM envelope, key ref/version, expiry, digest | target path never imports legacy SQLite authority; migration is explicit |
| Session update | no shared CAS contract | expected-version CAS retires old active row atomically | stale writers receive conflict; legacy state is untouched |
| Concurrency | process-local clients | PostgreSQL account lease; one mutable client/activity | Redis is not a lock; lease failure is retryable |
| Authorization | route/service-level checks | grant check before account lookup/provider call | cross-tenant result is denied/not-found shaped |
| Secret telemetry | legacy logs may contain provider errors | redacted `ContractError`, bounded labels, no raw material | secret scan is a release gate; no retrofit of old logs required |

## 4. State and storage ledger

| Store | Role in baseline | Platform integration role | Authority rule |
|---|---|---|---|
| PostgreSQL 16 | user/history/evidence and target repositories | accounts, sessions, grants, leases, login flows, health events | business facts and schema; Alembic is sole DDL authority |
| `pgvector` / `pg_trgm` | target retrieval capability | optional canonical evidence/retrieval support | extension readiness is checked read-only by adapters |
| Redis 7 | legacy session windows/event bus when configured | SSE stream, short-lived login/status projection, rate/circuit state | rebuildable hot state; no durable task/account truth or lock |
| S3-compatible ObjectStore | target binary contract (Boto3; MinIO local) | QR bytes and media objects with TTL/policy | object refs only cross API/Temporal boundaries |
| SQLite in upstream Dianping | not a project authority | excluded | never mounted or migrated into app runtime |
| `.xhs_profiles` / `.env` cookie | legacy local auth compatibility | excluded from target account authority | target sessions are vault/codec supplied and encrypted |

## 5. Queue and execution ledger

| Workload | Queue | Runtime | Isolation | Status |
|---|---|---|---|---|
| Foreground research | `research` | Temporal worker or legacy facade | request/task scoped | existing baseline |
| Refresh | `refresh` | Temporal worker | evidence refresh scoped | opt-in target workload |
| Media | `media` | Temporal worker | ObjectStore upload/fetch scoped | opt-in target workload |
| Account login | `account-auth` (configurable) | Temporal account-auth workflow/activities | account/channel scoped, bounded quota | disabled unless queue + gate are qualified |
| Upstream worker/queue | upstream names | not started | n/a | prohibited by intake boundary |

Queue names must be distinct. A queue may be registered only through
`TemporalTaskQueues` and its enabled quota; no ARQ, Celery, Redis lock, or
SQLite scheduler is introduced.

## 6. Provider dependency ledger

| Provider | Pinned snapshot | Reused modules | Explicitly excluded | Runtime mode |
|---|---|---|---|---|
| Dianping | `ffbc1d413ed1c83602212bc1fec12b57cd2b423d` | auth/QR/search/detail/reviews protocol modules | FastAPI app, SQLite, risk manager, CLI, worker, retry queue | Playwright in Activity; sidecar seam available |
| Spider_XHS | `e1888d712519040f5fcc294baeac4b9505b25c98` | PC/Creator auth + read protocol modules | `Data_Spider`, writers, publish/upload, global `.env` cookie, standalone queue | in-process qualification or sandboxed Python/Node sidecar |

Both snapshots have an unresolved license record in the intake. A README
badge is not treated as a grant; production/commercial activation requires a
new provenance revision with legal/owner approval and dependency digests.

## 7. Contract and error compatibility

| Provider outcome | Target mapping | Public effect |
|---|---|---|
| valid item/page | canonical `CanonicalSourceBatch` | same source/evidence shape, bounded cursor |
| valid empty | `outcome=empty` with source scope | distinguish from malformed/failure |
| auth expiry/challenge/risk | source `ContractError`, account health quarantine | retry/re-auth policy, no blind retry |
| 406/429/rate limit | `RATE_LIMITED` / dependency category as classified | admission/circuit can shed source |
| timeout/cancellation | stable timeout/cancel code | Temporal retry policy decides bounded retry |
| malformed tuple/item | malformed error or partial item isolation | eligible items preserved, no provider payload leakage |
| missing capability | scoped dependency/unregistered error | rejected before provider invocation |

The target adapters normalize URLs by removing access-bearing query parameters
(`xsec_token`, signature, authorization and equivalent keys), preserve opaque
external IDs, and return media references rather than binary/provider secrets.

## 8. Version and migration policy

1. A provider commit, dependency manifest, signer asset, canonical mapping, or
   capability change increments the connector version and creates a new
   provenance record.
2. Existing `xhs_compat`, legacy routes, Query Family records, and stored
   Evidence are not rewritten by enabling the platform registry.
3. A canary is selected by tenant/account cohort and compares aggregate
   equivalence, latency, coverage, request volume, and error classification.
4. Rollback is a flag/queue change. In-flight Temporal work keeps its pinned
   version; new work resolves the prior binding.
5. Legacy deletion, export contraction, and removal of compatibility fields are
   outside this change and require the separate `legacy-contraction` evidence
   gates.

## 9. Open compatibility items

| Item | Current state | Owner/action |
|---|---|---|
| Legal/license approval | pending; both intake statuses are `unknown` | `OWNER_LEGAL_REF` + revised provenance |
| Production dependency digest | pending reviewed lock/signer assets | security/engineering owner |
| Account-auth queue stack probe | unit contracts pass; external stack evidence pending | release owner |
| Disposable-account live probe | not represented by synthetic fixtures | platform owner, approved cohort |
| Legacy-to-target traffic cutover | not automatic | release owner after canary thresholds |

## 10. Qualification tooling compatibility

`scripts/qualification_schema_authority.py` now ignores local dependency trees
(`.venv`, `.venv-win`, `.venv-auth`), bytecode, tests, and the Alembic source
directory while scanning application Python. This prevents third-party SQL
strings from being mistaken for runtime schema ownership. The one explicitly
allow-listed SQLite request-log telemetry path remains reported as a separate
finding until the `legacy-contraction` evidence is complete. The generated
HTTP OpenAPI fixture includes the additive `/v1/platform/*` routes; existing
route schemas remain unchanged.
