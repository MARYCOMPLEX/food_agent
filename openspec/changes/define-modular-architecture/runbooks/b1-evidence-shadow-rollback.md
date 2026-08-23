# B1 Evidence Shadow Rollback

## Purpose

Disable the B1 Canonical Query/Evidence shadow writer and return source
connectors to their legacy-only binding. This is an additive rollback: it does
not delete the B1 tables, alter the legacy `chat_history` embedding, or change
HTTP/SSE reads.

## Preconditions

1. Record the deployed revision, shadow settings, profile version, and the
   latest shadow/differential report.
2. Stop new shadow-enabled connector instances and let in-flight legacy source
   calls finish. Do not stop or rewind PostgreSQL/Redis data as part of this
   binding rollback.
3. Confirm no B2 current-pointer or profile read binding has been enabled. B1
   candidates are never response-authoritative.

## Disable Binding

Set the target-only controls to their closed-world defaults and redeploy:

```text
MODULAR_EVIDENCE_SHADOW_ENABLED=false
MODULAR_EVIDENCE_SHADOW_SAMPLE_RATE=0
MODULAR_EVIDENCE_SHADOW_WRITE_BUDGET=0
```

Remove the `ShadowSourceConnector` decorator from the Composition Root (or
construct it without a sink). Keep the existing XHS/Place compatibility
adapter and its source registration unchanged. No route, event mapper, DTO,
SSE stream, query read, Bundle current pointer, or embedding read pointer may
be modified.

## Verification

Run the offline rollback and compatibility gates:

```powershell
uv run --frozen pytest -q `
  tests/test_unit_b1_rollback.py `
  tests/test_unit_b1_shadow_writer.py `
  tests/test_unit_b1_shadow_diff.py `
  tests/test_integration_search_http_characterization.py `
  tests/test_integration_sse_characterization.py
```

Confirm that the disabled connector returns the exact legacy batch, no sink
write is attempted, public response fixtures are byte-for-byte unchanged, and
the additive Alembic revision is still present. A production rehearsal must
also verify that old candidate rows remain auditable and that no current
pointer was activated.

## Re-enable

Re-enable only after the failed gate is understood and a new approval fixture
or rollback decision is committed. Restore the recorded sample/budget values,
deploy the same adapter binding, and repeat the differential and privacy gates
before enabling any canary. B1 alone never enables similarity, Bundle reuse,
embedding reads, or background refresh.
