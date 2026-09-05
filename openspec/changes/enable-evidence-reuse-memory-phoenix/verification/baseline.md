# Change Baseline

Captured for `enable-evidence-reuse-memory-phoenix` before enabling any new
serving path. This record is descriptive evidence; it does not alter the
completed `define-modular-architecture` change.

| Item | Value |
| --- | --- |
| Branch | `codex/integrate-platform-source-connectors` |
| Baseline revision | `71bdb66c3b08db940e20451b39539fb20776339b` |
| Python target | `3.12` (`requires-python >=3.12,<3.13`) |
| Schema authority | Alembic only; latest checked-in revision before this change was `20260904_0010_shop_profile_contract` |
| Business authorities | PostgreSQL for facts; Temporal history for executable recovery; Redis for rebuildable hot state |
| New capability defaults | B1 disabled, B2 `off`, B3 `off`, OTel disabled, Phoenix optional |
| Baseline architecture diff | clean (`git diff --quiet -- openspec/changes/define-modular-architecture`) |

The non-secret `TargetSettings(_env_file=None)` configuration snapshot used by
the local qualification fixtures is:

| Setting group | Default values |
| --- | --- |
| B1 Evidence | `enabled=false`, `sample_rate=0.0`, `write_budget=0` |
| B2 Query reuse | `mode=off`, `sample_rate=0.0`, `min_confidence=0.82`, `max_staleness_seconds=86400`, `b1_gate_approved=false` |
| B3 Personalization | `mode=off`, `sample_rate=0.0` |
| OTel/Phoenix | `otel_enabled=false`, `phoenix_enabled=false`, `queue=2048`, `batch=128`, `schedule_delay_ms=5000`, `export_timeout_ms=10000`, `retry_limit=2`, `sampling_rate=1.0`, `shutdown_flush_timeout_ms=5000`, `drop_policy=drop_oldest` |

The schema-state probe uses the following change-local fixtures, all of which
are read-only inputs to qualification and do not apply DDL:

* `fixtures/schema-state-clean-v1.json`
* `fixtures/schema-state-n-minus-1-v1.json`
* `fixtures/schema-state-current-v1.json`
* `fixtures/schema-state-divergent-v1.json`

The clean and N-1/current migration inputs are intentionally distinct: the
pre-change baseline ends at `20260904_0010_shop_profile`, while this change's
additive revisions are `20260905_0011_b2_freshness_watermark` and
`20260905_0012_b1_source_batches`.

The change-local dependency snapshot after adding the pinned OTLP/HTTP
exporter is `6b069630590e63a74f44b80614406374aa999ce85345be48ed8da2573de9145e`.
The completed architecture change retains its original lock snapshot; the
dependency ledger test accepts both reviewed snapshots during this transition.

## Reproduction commands

```powershell
git branch --show-current
git rev-parse HEAD
git diff --quiet -- openspec/changes/define-modular-architecture
uv lock --check
uv run --frozen pytest -q
```

The full baseline qualification recorded in the completed architecture change
was 734 non-live tests passing (11 deselected, 2 warnings) and 7 live Temporal
qualification tests passing. A local environment without PostgreSQL, Redis,
Temporal, or provider credentials must report those probes as unavailable; it
must not promote a milestone gate from that absence.

The change-local deterministic fixture suite is run separately from external
qualification. It validates the four schema states, four milestone datasets,
and aggregate manifest without claiming a production gate:

```powershell
.venv-win\Scripts\pytest.exe -q tests/test_unit_modular_baseline.py tests/test_unit_schema_authority_state.py tests/test_unit_qualification_fixtures.py
```

## Scope guard

No file under `openspec/changes/define-modular-architecture/` is changed by
this implementation. Any release commit must preserve the clean diff check
above and include this file's command output or an updated capture.
