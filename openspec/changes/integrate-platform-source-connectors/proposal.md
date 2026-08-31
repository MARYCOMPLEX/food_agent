## Why

The research core currently has an XHS compatibility connector, but it has no
project-owned account control plane and it cannot consume the audited
Dianping implementation.  The two upstream repositories expose useful
protocol clients, yet their SQLite/filesystem/global-cookie state must not
become a second task runtime or a source of business truth.  This change adds
replaceable platform adapters and a durable, tenant- and platform-isolated
account/session boundary so both providers can be enabled without changing
Query Family or Evidence contracts.

## What Changes

- Pin and record the audited upstream snapshots:
  - `MARYCOMPLEX/dazhongdianping` at `ffbc1d413ed1c83602212bc1fec12b57cd2b423d`.
  - `cv-cat/Spider_XHS` at `e1888d712519040f5fcc294baeac4b9505b25c98`.
- Add project-owned account, session, lease, health, and split-phase login
  contracts.  Account identity is `(tenant, platform, account)` and never
  enters public Query Family identity or canonical evidence.
- Persist account metadata and encrypted session envelopes through the
  PostgreSQL/Alembic authority; use Redis only for short-lived login status and
  rate-limit projections, and ObjectStore only for expiring QR bytes.
- Add per-account Temporal login/collection execution boundaries.  Each
  activity materializes one provider client, serializes mutable signer state,
  commits a new session version with compare-and-set, and destroys temporary
  credential material on completion.
- Add a Dianping SourceConnector for place search, place detail, reviews, and
  media references, translating provider failures and payloads into the
  canonical source contracts.
- Add a Spider_XHS SourceConnector for PC read operations and an explicit
  Creator read/publish capability boundary; publishing is not enabled by this
  change.  PC and Creator sessions are separate account namespaces.
- Add feature-gated Composition Root bindings, synthetic provider fixtures,
  contract/failure tests, runbooks, provenance and license evidence, and
  rollback procedures.  Existing `xhs.compat` behavior remains unchanged when
  the new binding is off.

## Capabilities

### New Capabilities

- `platform-account-session-management`: durable account identity, encrypted
  session versions, leases, health, tenant isolation, and secret redaction.
- `platform-login`: split-phase QR/phone/cookie login state machine and
  account-scoped Temporal execution.
- `dianping-source-connector`: canonical read-only Dianping source operations.
- `xhs-spider-source-connector`: canonical read-only Spider_XHS PC/Creator
  operations with per-account signer state.
- `platform-source-operation`: account-bound source invocation, queue
  selection, capability registration, and failure/rollback behavior.

### Modified Capabilities

None.  Existing `SourceConnector`, legacy HTTP/SSE, Query Family, and Evidence
requirements remain compatible; new behavior is additive and feature-gated.

## Impact

The change affects `src/xhs_food/contracts`, `foundation`, `gateways`,
`composition/adapters`, `composition/root.py`, optional API control-plane
routes, Alembic metadata/revisions, deployment configuration, and test/verification
fixtures.  Provider code is consumed through lazy, pinned integration
boundaries; upstream FastAPI apps, SQLite stores, CLI data writers, and task
workers are not embedded.  The Spider_XHS repository has no tracked LICENSE
file despite its README badge and contains a non-commercial notice; production
activation therefore requires recorded owner/license approval and dependency
evidence.  No credentials, cookies, QR payloads, or provider raw responses are
committed.
