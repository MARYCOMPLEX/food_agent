# Platform Connector Rollout Runbook

**Repository fixture:** `C:\Users\14158\Documents\ChatGPT\fagent\food_agent`
**Change branch at record time:** `codex/integrate-platform-source-connectors`
**Change:** `integrate-platform-source-connectors`
**Scope:** Dianping read connector and Spider_XHS PC/Creator read connectors;
Creator publishing is not part of this rollout.

This runbook describes a reversible, account-scoped rollout. It assumes the
OpenSpec change has passed local contract tests. It does not grant permission
to use either upstream project. Production/commercial activation requires the
owner/legal and security references in
[`upstream-provenance.md`](upstream-provenance.md).

## 0. Roles and invariants

| Role | Responsibility |
|---|---|
| Engineering owner | pinned checkout, adapter version, migration and test evidence |
| Security owner | KMS/Vault, AES-GCM envelope, signer sandbox, secret scan |
| Platform/account owner | disposable account cohort, re-auth and quarantine policy |
| Release owner | canary thresholds, traffic percentage, go/no-go and rollback |
| On-call | health checks, queue drain, lease recovery, incident timeline |

The following invariants apply in every environment:

1. Account identity is `(tenant_id, platform_channel, account_ref)`.
   `dianping`, `xhs_pc`, and `xhs_creator` are separate channels even when the
   human owner is the same.
2. Query Family, `CollectRequest`, and public Evidence do not contain an
   account ID or credential. The invocation envelope carries only an opaque
   reference and expected session version.
3. PostgreSQL/Alembic is the business/schema authority; Temporal is the only
   durable execution runtime; Redis is rebuildable hot state; S3-compatible
   ObjectStore owns binary QR/media objects.
4. Cookies, QR bytes, Authorization headers, storage-state paths, signer
   inputs, and decrypted envelopes never enter Temporal history, SSE, logs,
   metrics, Evidence, or object metadata.
5. A missing dependency is reported as `disabled` or
   `dependency-unavailable`; it is never hidden by silently selecting a new
   provider or an unqualified fallback.

## 1. Preflight and approval gate

Run from the absolute repository path shown above (PowerShell):

```powershell
Set-Location 'C:\Users\14158\Documents\ChatGPT\fagent\food_agent'
git status --short --branch
git rev-parse HEAD
openspec validate integrate-platform-source-connectors --strict
uv lock --check
.\.venv-win\Scripts\python.exe scripts\qualification_schema_authority.py --root .
```

Confirm all of the following before touching a production flag:

- `references/provider-import-allowlist.yaml` contains the exact provider
  commits and excluded upstream runtimes.
- `verification/upstream-provenance.md` has a reviewed dependency digest and
  a non-empty `OWNER_LEGAL_REF`/`OWNER_SECURITY_REF` for the deployment.
- The checkout paths contain only the allow-listed protocol/auth modules. Do
  not add the upstream repository root to the application package path.
- A KMS/Vault-backed `SessionEnvelopeCodecPort` and a project-owned
  `SQLAlchemyPlatformAccountRepository` are injected into the Composition
  Root. A local/test codec is not a production secret store.
- `MODULAR_PLATFORM_PROVIDER_MODE=sidecar` has an approved transport and the
  Spider_XHS Node signer asset is hash-pinned. If running in process, the
  locked image still contains the reviewed dependency set.
- The target Postgres schema has been applied by the release `migrate` job;
  the app's readiness probe is read-only.
- The schema probe output has no `unexpectedFindings`; its source scan skips
  `.venv`, `.venv-win`, `.venv-auth`, bytecode, tests, and Alembic, while the
  known SQLite request-log telemetry finding is classified separately.

If an approval or dependency is missing, leave the platform flags off and
continue only with synthetic qualification.

### Runtime injection and control-plane routes

The current API lifespan does not construct a provider, key store, or account
authority from environment variables alone. A deployment or test harness must
set `app.state.platform_runtime_factory` before entering the lifespan. The
factory may be synchronous or asynchronous and returns the explicitly composed
authority, session codec, connector/provider factories, optional Temporal
workflow/coordinator, ObjectStore, and cleanup hook. With no factory, the
legacy composition call receives empty platform kwargs and the platform router
reports a redacted `503 PLATFORM_DISABLED` response.

Once a bundle is injected, the control-plane routes are:

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/v1/platform/readiness` | redacted source/gateway/login readiness |
| `POST` | `/v1/platform/accounts` | register a tenant/channel/account alias |
| `GET` | `/v1/platform/accounts/{platform}/{account_ref}` | account projection (no session material) |
| `POST` | `/v1/platform/accounts/{platform}/{account_ref}/login/qr` | start QR login |
| `POST` | `/v1/platform/accounts/{platform}/{account_ref}/login` | start QR/phone/cookie mode using an opaque handle |
| `POST` | `/v1/platform/accounts/{platform}/{account_ref}/login/re-auth` | re-authenticate an existing account |
| `GET` | `/v1/platform/login/{flow_id}/status` | inspect a flow projection |
| `GET` | `/v1/platform/login/{flow_id}/qr` | obtain a time-limited QR presentation reference |
| `POST` | `/v1/platform/login/{flow_id}/poll` | advance/poll provider login state |
| `POST` | `/v1/platform/login/{flow_id}/cancel` | cancel a non-terminal flow |

The router's strict models reject raw `cookie`, `authorization`, QR, and signer
fields and its validation handler never echoes the offending request body.
Principal/tenant identity is supplied by the configured authentication
dependency; use the deployment's normal auth mechanism rather than putting a
tenant value in a public query parameter.

## 2. Deploy the target stack

The release fixture separates migration, app, queue smoke workers, Redis,
PostgreSQL/pgvector, Temporal, and MinIO. Use a unique Compose project name
for a qualification run.

```powershell
$env:COMPOSE_PROJECT_NAME = 'food-agent-PLATFORM_RUN_ID'
docker compose -f docker-compose.release.yml build app
docker compose -f docker-compose.release.yml up -d postgres redis temporal minio
docker compose -f docker-compose.release.yml run --rm migrate
docker compose -f docker-compose.release.yml up -d app
docker compose -f docker-compose.release.yml ps
```

Expected baseline:

- `migrate` exits `0` and `alembic current` reports the head revision.
- Postgres reports `pgvector`/`pg_trgm` and all platform account tables.
- Redis, Temporal, and MinIO health checks are green.
- `GET http://HOST:18000/health` returns HTTP 200 with a redacted readiness
  projection.
- The app process starts without importing upstream `apis`, `xhs_utils`,
  `dz_engine`, or an independent broker/worker.

Collect logs without secrets:

```powershell
docker compose -f docker-compose.release.yml logs --no-color app > logs\platform-app-RUN_ID.txt
docker compose -f docker-compose.release.yml exec app python -m pytest -q tests/test_platform_connector_intake.py
```

Run a secret scanner over the captured artifact and remove the artifact if it
contains a credential-bearing value. Keep only its digest and findings in the
qualification record.

## 3. Register accounts and sessions

Account registration is a control-plane operation, not a provider CLI action.
Use the project account use case/API adapter with an opaque alias:

```text
tenant_id       = TENANT
platform        = dianping | xhs_pc | xhs_creator
account_ref     = ACCOUNT_REF
alias           = ACCOUNT_ALIAS
provider_subject_id = optional reviewed subject reference
```

The repository must create the composite identity and an initial
`pending_login` account. Never import a provider SQLite account table or copy a
`.env` cookie/profile into the application. Grant the release principal only
the required `use`/`login` permissions and record the grant ID, not secret
material.

### Manual cookie import (temporary qualification path)

The credential source supplies an opaque `CREDENTIAL_REF` to the account-auth
Activity. The Activity resolves it from the vault, validates provider identity,
then commits exactly one encrypted session version using CAS. The API and
Temporal input contain the reference only. A successful result exposes:

```json
{
  "account_ref": "ACCOUNT_REF",
  "platform": "xhs_pc",
  "session_version": 1,
  "status": "active",
  "digest": "SHA256"
}
```

No cookie string, storage-state path, or signer state is returned. Revoke the
credential handle after the Activity completes.

## 4. QR login flow

QR login is split phase and account/channel scoped:

`created → qr_ready → waiting_scan → waiting_confirmation → succeeded`

Terminal alternatives are `expired`, `failed`, and `cancelled`; transitions
are monotonic. The QR image is written to ObjectStore with a short TTL and the
flow exposes only `FLOW_ID`, `OBJECT_REF`, and `expires_at`.

1. Start a flow with `ACCOUNT_REF`, `platform`, an idempotency key, and an
   approved principal.
2. Route the workflow to the distinct `account-auth` queue. Verify that the
   queue quota is enabled and does not share a collection queue.
3. Poll status using `FLOW_ID`. The status projection may be in Redis, while
   PostgreSQL remains the flow/session authority.
4. Present the short-lived ObjectStore reference to the operator. Do not proxy
   QR bytes through Temporal history, logs, or an unbounded SSE event.
5. On scan/confirmation, validate the provider subject against the requested
   account. Commit one new AES-GCM session version with expected-version CAS.
6. Delete the QR object on success, expiry, cancellation, or terminal failure.
   Run orphan cleanup after a worker restart.

Example queue settings (replace values with approved deployment settings):

```dotenv
MODULAR_PLATFORM_CONNECTORS_ENABLED=true
MODULAR_PLATFORM_LOGIN_ENABLED=true
MODULAR_TEMPORAL_ACCOUNT_AUTH_QUEUE=account-auth
MODULAR_TEMPORAL_ACCOUNT_AUTH_ENABLED=true
MODULAR_TEMPORAL_ACCOUNT_AUTH_MAX_CONCURRENT_ACTIVITIES=2
MODULAR_TEMPORAL_ACCOUNT_AUTH_MAX_CONCURRENT_WORKFLOWS=2
```

When any required auth setting or login service is absent, readiness must show
`login.enabled=false`; the supported operation is manual import through the
same opaque-reference contract.

## 5. Enable a platform in stages

Enable one platform and one small account cohort at a time. Keep the release
owner's previous flag values in the change ticket.

### Dianping

```dotenv
MODULAR_PLATFORM_CONNECTORS_ENABLED=true
MODULAR_PLATFORM_DIANPING_ENABLED=true
MODULAR_PLATFORM_DIANPING_CHECKOUT=CHECKOUT_PATH
MODULAR_PLATFORM_PROVENANCE_REF=PROVENANCE_REF
MODULAR_PLATFORM_LICENSE_APPROVAL_REF=OWNER_LEGAL_REF
```

Verify source ID `dianping`, connector version `dianping-platform/v1`, and
capabilities `place.lookup`, `reviews.search`, `media.refs`. Search, detail,
review, and media operations must use bounded pagination and canonical URL
normalization. The upstream FastAPI app, SQLite state, risk manager, CLI, and
worker remain stopped.

### Spider_XHS PC

```dotenv
MODULAR_PLATFORM_CONNECTORS_ENABLED=true
MODULAR_PLATFORM_XHS_ENABLED=true
MODULAR_PLATFORM_XHS_CHECKOUT=CHECKOUT_PATH
MODULAR_PLATFORM_PROVIDER_MODE=sidecar
MODULAR_PLATFORM_PROVENANCE_REF=PROVENANCE_REF
MODULAR_PLATFORM_LICENSE_APPROVAL_REF=OWNER_LEGAL_REF
```

Verify channel `xhs_pc`, public source ID `xhs`, and note/detail/comments/media
operations. Confirm signer process resource limits, URL query stripping, and
that an account's mutable client is not reused by another activity.

### Spider_XHS Creator

The same XHS feature flag exposes a separate `xhs_creator` account channel.
Only read/health capabilities are registered. Publishing, upload, scheduling,
Qianfan/Pugongying, and `Data_Spider` calls must return a stable unregistered
capability result before provider invocation.

## 6. Health checks and observability

Inspect the redacted Composition Root projection:

```text
platform_readiness.statuses[].platform
platform_readiness.statuses[].state
platform_readiness.statuses[].reason
platform_readiness.gateway.enabled
platform_readiness.login.enabled
```

Useful bounded labels are `platform`, `source_id`, `connector_version`,
`operation`, `outcome`, `error_category`, and queue name. Do not add
`account_ref`, cookie hashes, provider URLs, QR IDs, or raw exception text as
high-cardinality labels. A provider auth/challenge/expiry signal should move
the account to a quarantined/expired health state and require re-auth before
blind retries.

## 7. Incident procedures

### Provider risk, 406/429, or auth expiry

1. Confirm the source-level admission/circuit state and affected channel.
2. Stop new calls for the affected source or account by disabling its flag or
   grant; retain existing evidence and history.
3. Mark health/quarantine in PostgreSQL. Do not repeatedly retry a challenged
   account.
4. Re-authenticate through the same flow ID or create a new flow after expiry;
   commit only one CAS session version.
5. Record aggregate error category and provider response class, never raw
   response/cookie data.

### Lease conflict or stale session writer

1. Inspect the PostgreSQL lease row by opaque lease ID and task ID.
2. Let the active owner heartbeat or expire according to the configured TTL;
   do not use Redis locks or manual row deletion during an active task.
3. A stale CAS writer must be rejected. Retry the use case with the latest
   session version and a new idempotency key only after policy approval.

### Worker or sidecar restart

1. Stop accepting new work on the affected queue.
2. Restart the worker/sidecar with the same pinned connector version and
   resource policy.
3. Verify Temporal replay, lease release, connector close, material zeroization,
   and QR orphan cleanup.
4. Resume the queue only after health and secret-scan probes pass.

## 8. Rollback / disable

Rollback is safe and configuration-first:

```dotenv
MODULAR_PLATFORM_DIANPING_ENABLED=false
MODULAR_PLATFORM_XHS_ENABLED=false
MODULAR_PLATFORM_LOGIN_ENABLED=false
MODULAR_TEMPORAL_ACCOUNT_AUTH_ENABLED=false
```

1. Stop new platform requests at the Composition Root and, if needed, revoke
   grants for the canary cohort.
2. Drain or allow in-flight Temporal Activities to finish under their pinned
   connector version; terminate only under the normal Temporal policy.
3. Release/recover leases and remove temporary QR objects.
4. Route new requests to the prior `xhs_compat`/legacy source binding. Legacy
   HTTP/SSE, Query Family identity, public pointers, account rows, Evidence,
   and Temporal history remain unchanged.
5. Preserve the incident aggregate and exact input digest. Do not delete the
   Alembic revision or rewrite stored evidence as part of rollback.

## 9. Post-rollout evidence

Attach the following to `platform-connector-qualification.md` or a linked
immutable release record:

- branch, commit, image digests, lockfile digest, and exact commands;
- Postgres migration/readiness, Redis replay, Temporal queue/restart, and
  ObjectStore QR/media cleanup observations;
- aggregate canary metrics and threshold approval;
- secret-scan output (zero findings) and signer hash/resource policy;
- owner, security, legal, and release sign-offs;
- final flag values and rollback test result.

After evidence is reviewed, update the OpenSpec task state in a separate
change/commit. This runbook itself does not mark production approval.
