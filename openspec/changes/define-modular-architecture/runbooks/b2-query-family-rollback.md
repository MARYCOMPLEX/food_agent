# B2 Query Family Rollback Runbook

This runbook disables the B2 read canary and explicit refresh binding while
retaining every immutable Bundle, derivation, profile row, and Temporal history.
It is a pointer/configuration rollback, not a data deletion procedure.

## Preconditions

Record the deployed revision, the B2 qualification report/approval IDs, the
active `query_reuse_read` mode, active refresh Workflow IDs, the current Bundle
pointer for every affected Family, and the active embedding profile pointer.
Keep the previous legacy binding and the previous Bundle/profile pair available
until post-rollback checks complete.

## Stop New B2 Work

1. Set `QueryReuseReadSettings(mode="off", sample_rate=0.0)` in the
   Composition Root. The default constructor already produces this closed-world
   setting.
2. Remove or disable the binding that constructs `ExplicitRefreshService`; the
   current change deliberately does not expose a refresh HTTP route.
3. Stop admitting new canary requests and new explicit-refresh commands. Do not
   cancel an in-flight refresh by deleting its claim or by writing a Redis lock.
4. Let an in-flight Workflow reach a deterministic boundary, then cancel or
   terminate it through Temporal's Workflow API according to the operator policy.
   Record the terminal Workflow result and any candidate Bundle ID.

## Restore A Previous Pointer

For each Family that must return to an older version, use the repository's
conditional dual-pointer operation with the values captured before activation:

```python
await repository.activate_bundle_and_profile_if_current(
    family_id=FAMILY_ID,
    expected_bundle_version=CURRENT_BUNDLE_VERSION,
    bundle_id=PREVIOUS_BUNDLE_ID,
    bundle_version=PREVIOUS_BUNDLE_VERSION,
    expected_profile_id=CURRENT_PROFILE_ID,
    profile=PREVIOUS_PROFILE,
)
```

The operation must return `True`. A `False` result means another writer moved
the pointer; stop and re-read the authoritative PostgreSQL pointer before
retrying. Never force a rollback with an unconditional update. The B2 service
also exposes `BundleLifecycleService.restore_pointer`, which rejects a target
that is not older and delegates this same CAS.

## Verify Legacy Service

Run the offline gate and the targeted application checks:

```powershell
uv run --frozen pytest -q tests/test_unit_b2_rollback.py tests/test_unit_b2_query_reuse_read.py
uv run --frozen pytest -q tests/test_unit_b2_bundle_lifecycle.py tests/test_integration_search_http_characterization.py
```

Confirm that legacy search remains the served result, the canary candidate is
not returned, no explicit refresh route is present in the OpenAPI snapshot,
the restored Bundle/profile pair is readable, and no new refresh Workflow is
admitted after the gate timestamp. Redis streams and caches may be allowed to
expire; they are not authority and must not be used to prove rollback.

## Re-enable Criteria

Re-enable only after a new B2 qualification report has an owner-approved
`B2CanaryApproval`, the target PostgreSQL/pgvector recall and latency gate has
passed, and this rollback procedure has been rehearsed against the same
deployment revision. Keep the read mode off if any gate is missing.
