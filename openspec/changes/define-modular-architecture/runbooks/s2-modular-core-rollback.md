# S2 Modular Core Binding Rollback

## Purpose

Restore the S2 Experience boundary to the frozen legacy task policy without
changing HTTP/SSE contracts, database schema, stored data, or frontend code.

The stable logical capability is `modular_core`. In S2 its only active target
is:

```text
modular_core
  -> use_cases.research_task
  -> LegacyResearchTaskFacade
  -> contract_version legacy/v1
```

S2 does not add a runtime environment toggle because no second implementation
is active yet. A later milestone that introduces another implementation MUST
keep `modular_core` as the selection key and retain this legacy target as the
rollback binding.

## Preconditions

1. Record the deployed Git revision and confirm no later schema/data migration
   is being rolled back with this procedure.
2. Stop routing new research requests to the candidate deployment. Existing
   in-process legacy tasks may finish under the same legacy policy.
3. Preserve PostgreSQL, Redis, and event data. S2 has no schema migration,
   backfill, dual write, or new durable state to delete.

## Binding Rollback

Restore the Composition Root selection to:

```python
root.bind_logical(
    "modular_core",
    registry_name="use_cases",
    binding_name="research_task",
)
```

The selected registry entry MUST remain `legacy=True` with
`contract_version="legacy/v1"` and factory `LegacyResearchTaskFacade`. Deploy
the resulting artifact and restart the FastAPI process so lifespan resolves
the binding again. Do not change routes, SSE cursors, DTOs, or stored rows as
part of the rollback.

## Verification

Run the binding and compatibility gates:

```powershell
uv run --frozen pytest -q `
  tests/test_unit_composition_root.py `
  tests/test_unit_legacy_research_task_facade.py `
  tests/test_integration_search_http_characterization.py `
  tests/test_integration_sse_characterization.py `
  tests/test_unit_sse_state_characterization.py
```

Confirm:

- `resolve_logical("modular_core")` returns `LegacyResearchTaskFacade`.
- New/refine each spawn the legacy runner once.
- HTTP and SSE golden fixtures are unchanged.
- The known error-after-completed, persist-after-completed, swallowed
  persistence failure, and old-terminal replay behavior remain selected.
- No Alembic revision, table, column, profile, object, or durable workflow is
  created or removed.

If any check fails, keep the candidate out of service and deploy the last known
S1/S2-compatible artifact. Data restore is neither required nor permitted for
this structural rollback.
