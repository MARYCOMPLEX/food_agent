## Why

The Phoenix/evidence-reuse change committed qualification tests and verification records that reference immutable JSON fixtures, but the fixture directory is absent from the repository. This leaves the full suite red with `FileNotFoundError` and makes the recorded qualification baseline non-reproducible.

## What Changes

- Restore the four versioned schema-state fixtures used by the fail-closed PostgreSQL probe tests.
- Restore four deterministic, redaction-safe evaluation datasets and their milestone manifests for B1, B2, B3, and observability.
- Restore the aggregate qualification manifest that points to every milestone artifact.
- Add an explicit Git ignore exception so OpenSpec fixture JSON is tracked in future commits.
- Add a change-local specification and verification record for fixture completeness and deterministic replay.

## Capabilities

### New Capabilities

- `qualification-fixtures`: Repository-owned schema-state and evaluation fixtures are versioned, immutable, redaction-safe, and reproducible by the qualification tests.

### Modified Capabilities

None.

## Impact

- Affected paths: `openspec/changes/enable-evidence-reuse-memory-phoenix/fixtures/`, `.gitignore`, and the change-local OpenSpec artifacts.
- Runtime code and production APIs are unchanged.
- The restored artifacts are synthetic and contain no provider credentials, account state, private URLs, or raw user content.
