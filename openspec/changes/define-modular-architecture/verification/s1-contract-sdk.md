# S1 Contract SDK Verification

Date: 2026-08-20

## Scope

S1 adds domain-neutral contracts, a legacy-only Composition Root lifecycle,
schema validation, compatibility checks, and shrink-only architecture gates.
It does not route production traffic through the new contracts, activate a
Domain Pack, or enable Query Family, memory, refresh, or media behavior.

The S0 base revision is `90930af40c92faaa1a9de33ea090b129dec1a134`.
The implementation tip and detached-worktree revert evidence are recorded in
the follow-up `Revert Drill` section after the implementation commit exists.

## Runtime And Lock

- Windows x86_64 blocking workspace.
- Python `3.12.0`.
- Node.js `22.13.1`; npm `11.7.0`.
- uv `0.11.14`.
- `jsonschema==4.26.0`; transitive implementation dependency
  `referencing==0.37.0`.
- `uv lock --check --offline` resolved 89 locked packages successfully.

## Contract SDK Gate

The focused S1 suite ran with every warning promoted to an error:

```text
226 passed in 24.06s
```

It covers:

- Research request, plan, task, event, projection, error, port, and registry
  contracts.
- Canonical Query, source batch, provenance, Evidence, immutable Bundle, memory,
  refresh, media, processor, and extractor contracts.
- Deeply immutable nested JSON values with JSON-compatible serialization and no
  Pydantic serialization warnings.
- A sealed 19-document local Domain schema bundle, format checking, tool and
  final-output schemas, stable registration failures, and rejection of external
  or unbundled references.
- Optional-field compatibility, destructive field/enum change detection, and
  contract round trips.

The Domain manifest digest preimage is
`domain-manifest-digest-preimage/v1`. The validated manifest digest is:

```text
e4165d6bf54a56bc7ea6df6a4b9aef74f6064276d50fbd6ece383c7cd2a992c7
```

Representative examples are validation fixtures and do not affect this
identity digest.

## Legacy Compatibility

The complete non-live S0+S1 backend suite produced:

```text
422 passed, 5 deselected, 2 warnings in 25.32s
```

The two warnings are the S0-recorded `PytestReturnNotNoneWarning` cases in
`tests/test_session.py`; no S1-focused test emits a warning.

A separate legacy import, HTTP, SSE, Food DTO/result, search behavior, and state
golden run produced:

```text
66 passed in 4.14s
```

The S0 characterization, HTTP, SSE, database, and frontend identity fixture
paths have an empty Git diff against `90930af`. S1 changes no FastAPI route,
SSE mapper, Food workflow, production composition binding, database schema, or
frontend runtime source.

## Architecture Graph Archive

The default-deny dependency policy contains 21 ordered module-layer rules. Its
SHA-256 is:

```text
6afe84483385ecdddd56cbcd35204468d6df3749f0eda09204c4d940a11e9593
```

The final scan found `101/101` reviewed legacy import violations and `24/24`
reviewed legacy private-access violations, with zero additions. Tests also
inject forbidden target-layer imports, forbidden third-party imports,
unclassified modules, and cross-object private access to prove that the gate is
default-deny while preserving the Composition Root exception.

The version-controlled architecture references remain the S0 authority archive:

| Reference | SHA-256 |
|---|---|
| `food-agent-unified-architecture.html` | `0e122cf6d7f45344faaf45aec084e384463c94ebbac36328dae0d866a1e8c198` |
| `food-agent-extensible-evidence-architecture.drawio` | `70ba87d7ea63e55ec0af22c47e4bc647751cf5dece7cebd22b81a63b3091cbc6` |

S1 archives and checks the reference result; synchronizing diagram labels from
the implemented registries remains the explicit release task `14.16`.

## Tooling Gates

- Ruff on every Python file added or modified by S1: passed.
- Pyright on `src/xhs_food/contracts` and `src/xhs_food/composition`:
  `0 errors, 0 warnings, 0 informations`.
- Frontend ESLint: passed.
- Frontend TypeScript and Vite production build: passed; 2,264 modules
  transformed.
- `openspec validate define-modular-architecture --strict --json`: one change
  passed, zero issues.
- `git diff --check`: passed.

The normal Pyright, ESLint, TypeScript, and Vite entry points ran directly.
Vite emitted only its non-blocking forward-compatibility notice for
`__dirname`; the production build completed successfully.

## Failure Injection

S1 tests reject incomplete or malformed Pack manifests, duplicate or missing
schema IDs, external and unbundled references, invalid formats, digest mismatch,
unregistered or version-mismatched tools, malformed optional source ranges,
illegal SemVer numeric prerelease identifiers, malformed tool/final outputs,
divergent build-method/final-output schemas, invalid registry bindings,
destructive nested union/schema changes, new
architecture violations, and nested mutation. They also prove union branch
reordering and nested optional-field addition remain compatible, and recursive
local references terminate deterministically. Registration failures remain
isolated values and do not partially activate a Pack or alter the legacy-only
default bindings.

## Revert Drill

Pending the S1 implementation commit. The drill will revert every implementation
commit after the S0 base in newest-first order inside a detached worktree, compare
the resulting tree with the S0 base, and rerun the S0 non-live suite.

## Deferred Release Gates

Ubuntu and extended platform probes, the full PostgreSQL/Redis/Temporal/S3
target stack, generated architecture documentation synchronization, and release
matrix evidence remain tasks `14.1` through `14.16`. They are not claimed by the
Windows S1 structural checkpoint.
