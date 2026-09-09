## Verification Record

This change restores repository-owned synthetic fixtures only. It does not
enable B1, B2, B3, or Phoenix serving gates.

The focused schema and qualification tests must pass, each dataset digest must
be recomputed by `EvaluationDataset`, and strict OpenSpec validation must pass.
The full non-live suite is also run to distinguish this repair from unrelated
legacy failures.

## Recorded Results

| Check | Result |
| --- | --- |
| `uv run --frozen pytest -q tests/test_unit_schema_authority_state.py tests/test_unit_qualification_fixtures.py --tb=short -ra` | `26 passed` |
| `uv run --frozen pytest -q -m "not live" --tb=short -ra` | `1209 passed, 25 deselected, 2 warnings` |
| `openspec validate restore-phoenix-qualification-fixtures --strict` | pass |
| `openspec validate enable-evidence-reuse-memory-phoenix --strict` | pass |
| `openspec validate freeze-research-experience-contracts --strict` | pass |
| Targeted Ruff | pass |
| Targeted Pyright | `0 errors, 0 warnings, 0 informations` |
| Frontend `npm run typecheck` | pass |
| Fixture JSON parsing | pass |

The two warnings are pre-existing pytest warnings from `tests/test_session.py`
returning boolean values. No fixture or contract test remains failing.
