## Context

The existing qualification tests load JSON directly from the
`enable-evidence-reuse-memory-phoenix` change directory. The test contracts
already define the required fields, digest algorithm, redaction restrictions,
and four schema classifications. The repository-wide `*.json` ignore rule
currently does not exempt OpenSpec fixture paths, which allowed these
repository-owned artifacts to be omitted from the commit.

## Goals / Non-Goals

**Goals:**

- Make every fixture referenced by the existing tests present and tracked.
- Use the existing `EvaluationDataset` model and digest implementation as the
  only authority for dataset serialization.
- Keep schema fixtures aligned with the default schema probe signatures and
  make the divergent case fail closed.
- Make the repair independently reviewable and reversible.

**Non-Goals:**

- No production behavior, migration, database schema, or Phoenix integration
  changes.
- No claim that these synthetic fixtures constitute live owner approval or a
  serving gate.
- No weakening of privacy validation or test assertions.

## Decisions

### Versioned fixture location

Keep all artifacts under the path already used by the tests:
`openspec/changes/enable-evidence-reuse-memory-phoenix/fixtures/`. Changing
the tests to another location would hide the missing-artifact defect and break
the verification records.

### Dataset authority and digest

Construct each dataset as `evaluation/v1` with four synthetic cases covering
contract shape, privacy/redaction, failure recovery, and the milestone-specific
qualification path. Compute and pin `digest` through the repository's
`EvaluationDataset` validator. This avoids hand-implementing a second digest
algorithm and preserves deterministic reruns.

### Schema-state authority

Use the exact default revision and signature values exported by
`xhs_food.foundation.schema_authority`. The clean fixture has no version table,
the N-1 and current fixtures contain their respective exact revisions and
columns, and the divergent fixture uses an unknown revision. The fixtures are
read-only inputs; Alembic remains the only schema writer.

### Tracking rule

Add a narrow `.gitignore` exception for the OpenSpec fixture subtree instead
of unignoring every JSON file in the repository. This preserves the existing
protection for runtime exports and credentials while making the intended
qualification artifacts trackable.

## Risks / Trade-offs

- [Risk] Synthetic fixtures could be mistaken for production qualification.
  -> Keep the files redaction-safe and document that they are offline,
  repository-owned evidence only.
- [Risk] Future schema or evaluator changes can make old fixtures invalid.
  -> Keep explicit `v1` names and digests; update them only in a reviewed
  OpenSpec change.
- [Risk] A broad ignore exception could expose sensitive JSON.
  -> Scope the exception to this exact fixture directory.

## Migration Plan

1. Add the fixture artifacts and ignore exception.
2. Run the focused schema/qualification tests and strict OpenSpec validation.
3. Run the non-live regression suite and record the result.
4. Rollback is a Git revert of this change; no runtime or database rollback is
   required.

## Open Questions

None.
