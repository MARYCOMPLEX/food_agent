# Account Service Rollout Evidence

This document is a release-evidence template. Local fixture results prove the
HTTP/MCP contract only; they are not owner, legal, security, dependency, or
production approval.

## Local contract gate

Run from the repository root:

```powershell
.\.venv-win\Scripts\pytest.exe -q tests/test_unit_account_service_contracts.py tests/test_unit_account_service_http.py tests/test_unit_account_service_mcp.py tests/test_unit_account_service_registry.py tests/test_unit_account_service_fixture.py
.\.venv-win\Scripts\ruff.exe check src/xhs_food/account_services src/xhs_food/contracts/account_service.py src/xhs_food/gateways/account_service.py src/xhs_food/composition/account_services.py src/api/platform.py src/api/main.py
openspec validate platform-account-service-mcp --strict
```

Recorded local result on 2026-09-02: `1159 passed, 25 deselected, 2 warnings`
in 84.32s for the complete non-live suite; the targeted account-service
contract suite passed; targeted Ruff and Pyright checks for the account-service
implementation reported no errors;
`uv lock --check` resolved 117 packages successfully; and OpenSpec strict
validation succeeded. The lockfile SHA-256 was
`8301F2B046290C4E65A8FFDACAFCE7844D1F8DA6E414DF003809E161931CCCFF`.

No real provider account, cookie, QR payload,
browser profile, signer state, or service token is used by these tests.

## Target-stack smoke gate

The following must be run against disposable accounts and deployment-managed
service authentication references after both upstream services are built:

```text
GET  http://HOST:PORT_XHS/v1/capabilities
GET  http://HOST:PORT_DIANPING/v1/capabilities
POST http://HOST:PORT_XHS/v1/accounts
POST http://HOST:PORT_DIANPING/v1/accounts
POST http://HOST:PORT_XHS/v1/accounts/xhs_pc/ACCOUNT_REF/login/qr
POST http://HOST:PORT_DIANPING/v1/accounts/dianping/ACCOUNT_REF/login/qr
POST http://HOST:PORT_XHS/mcp       (initialize, tools/list)
POST http://HOST:PORT_DIANPING/mcp (initialize, tools/list)
```

Record the exact image digest, service version, contract version, capability
catalog, database migration revision, object-store policy, and redacted
readiness response. Verify that XHS and Dianping accounts cannot read one
another's flow, session, object, or health records. Verify that an MCP outage
degrades discovery only while healthy HTTP operations continue.

## Owner-approved canary gate

Before routing production traffic, attach evidence for:

```text
OWNER_APPROVAL_REF
SECURITY_REVIEW_REF
LEGAL_LICENSE_REF
DEPENDENCY_DIGESTS_REF
DISPOSABLE_ACCOUNT_CANARY_REF
ROLLBACK_CHANGE_REF
```

The canary must cover QR login, status/poll/cancel monotonicity, source
invocation, rate-limit/provider-risk mapping, service restart, descriptor
expiry, and rollback to the in-process connector. The main application must
continue to persist opaque references only. Missing evidence keeps the remote
service opt-in and disabled for production.
