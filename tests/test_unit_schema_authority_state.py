"""Schema-state probe and additive migration qualification fixtures."""

from __future__ import annotations

import importlib.util
import json
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from xhs_food.foundation import (
    CURRENT_SCHEMA_REVISION,
    DEFAULT_CURRENT_SCHEMA_SIGNATURE,
    DEFAULT_N_MINUS_1_SCHEMA_SIGNATURE,
    N_MINUS_1_SCHEMA_REVISION,
    SchemaDivergentError,
    SchemaProbeError,
    SchemaSignature,
    SchemaState,
    assert_postgres_schema_state,
    probe_postgres_schema_state,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FIXTURE_ROOT = (
    ROOT
    / "openspec"
    / "changes"
    / "enable-evidence-reuse-memory-phoenix"
    / "fixtures"
)
CURRENT_REVISION = "fixture/current"
PREVIOUS_REVISION = "fixture/previous"
CURRENT_REQUIREMENTS = {"fixture_table": ("id", "watermark_advanced")}
PREVIOUS_REQUIREMENTS = {"fixture_table": ("id",)}


class FakeAsyncPostgresConnection:
    """Deterministic asyncpg-like read fixture for schema probes."""

    def __init__(
        self,
        *,
        revisions: tuple[str, ...] = (),
        version_table: bool = True,
        columns: dict[str, tuple[str, ...]] | None = None,
        extensions: tuple[str, ...] = (),
        fail_query: str | None = None,
    ) -> None:
        self.revisions = revisions
        self.version_table = version_table
        self.columns = columns or {}
        self.extensions = extensions
        self.fail_query = fail_query
        self.calls: list[str] = []

    async def fetch(self, query: str, *args: object) -> list[dict[str, str]]:
        self.calls.append(query)
        if self.fail_query and self.fail_query in query:
            raise TimeoutError("fixture schema probe timeout")
        if "information_schema.tables" in query:
            return ([{"table_name": "alembic_version"}] if self.version_table else [])
        if "public.alembic_version" in query:
            return [{"version_num": revision} for revision in self.revisions]
        if "information_schema.columns" in query:
            requested = set(args[0]) if args else set(self.columns)
            return [
                {"table_name": table_name, "column_name": column_name}
                for table_name in sorted(requested)
                for column_name in self.columns.get(table_name, ())
            ]
        if "FROM pg_extension" in query:
            requested = set(args[0]) if args else set(self.extensions)
            return [{"extname": name} for name in sorted(requested & set(self.extensions))]
        raise AssertionError(f"unexpected probe query: {query}")


def _probe_kwargs() -> dict[str, object]:
    return {
        "expected_revision": CURRENT_REVISION,
        "previous_revision": PREVIOUS_REVISION,
        "current_signature": CURRENT_REQUIREMENTS,
        "previous_signature": PREVIOUS_REQUIREMENTS,
    }


def _columns(requirements: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    return dict(requirements)


def _load_schema_state_fixture(filename: str) -> dict[str, Any]:
    payload = json.loads((SCHEMA_FIXTURE_ROOT / filename).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


@pytest.mark.parametrize(
    ("filename", "expected_state"),
    (
        ("schema-state-clean-v1.json", SchemaState.CLEAN),
        ("schema-state-n-minus-1-v1.json", SchemaState.N_MINUS_1),
        ("schema-state-current-v1.json", SchemaState.CURRENT),
        ("schema-state-divergent-v1.json", SchemaState.DIVERGENT),
    ),
)
@pytest.mark.unit
async def test_versioned_schema_state_fixtures_drive_the_fail_closed_probe(
    filename: str,
    expected_state: SchemaState,
) -> None:
    fixture = _load_schema_state_fixture(filename)
    assert fixture["schemaVersion"] == "schema-state-fixture/v1"
    connection = FakeAsyncPostgresConnection(
        revisions=tuple(fixture["revisions"]),
        version_table=bool(fixture["versionTable"]),
        columns={
            str(table): tuple(columns)
            for table, columns in dict(fixture["tables"]).items()
        },
        extensions=tuple(fixture["extensions"]),
    )

    result = await probe_postgres_schema_state(connection)

    assert result.state is expected_state
    assert result.status == str(fixture["state"])
    assert result.observed_revisions == connection.revisions
    if expected_state is SchemaState.DIVERGENT:
        with pytest.raises(SchemaDivergentError):
            result.require_compatible()
    else:
        assert result.is_compatible


@pytest.mark.unit
async def test_default_b1_revision_probe_distinguishes_clean_n_minus_1_and_current() -> None:
    clean = FakeAsyncPostgresConnection(version_table=False)
    n_minus_1 = FakeAsyncPostgresConnection(
        revisions=(N_MINUS_1_SCHEMA_REVISION,),
        columns=DEFAULT_N_MINUS_1_SCHEMA_SIGNATURE.requirements,
    )
    current = FakeAsyncPostgresConnection(
        revisions=(CURRENT_SCHEMA_REVISION,),
        columns=DEFAULT_CURRENT_SCHEMA_SIGNATURE.requirements,
    )

    clean_result = await probe_postgres_schema_state(clean)
    n_minus_1_result = await probe_postgres_schema_state(n_minus_1)
    current_result = await probe_postgres_schema_state(current)

    assert clean_result.state is SchemaState.CLEAN
    assert n_minus_1_result.state is SchemaState.N_MINUS_1
    assert current_result.state is SchemaState.CURRENT


@pytest.mark.parametrize(
    ("connection_kwargs", "expected_state"),
    (
        (
            {"version_table": False},
            SchemaState.CLEAN,
        ),
        (
            {
                "revisions": (PREVIOUS_REVISION,),
                "columns": _columns(PREVIOUS_REQUIREMENTS),
            },
            SchemaState.N_MINUS_1,
        ),
        (
            {
                "revisions": (CURRENT_REVISION,),
                "columns": _columns(CURRENT_REQUIREMENTS),
            },
            SchemaState.CURRENT,
        ),
    ),
)
@pytest.mark.unit
async def test_schema_probe_classifies_clean_n_minus_1_and_current(
    connection_kwargs: dict[str, object], expected_state: SchemaState
) -> None:
    connection = FakeAsyncPostgresConnection(**connection_kwargs)

    result = await probe_postgres_schema_state(connection, **_probe_kwargs())

    assert result.state is expected_state
    assert result.is_compatible
    assert result.observed_revisions == connection.revisions
    assert all(query.lstrip().startswith("SELECT") for query in connection.calls)


@pytest.mark.parametrize(
    "connection_kwargs",
    (
        {
            "revisions": ("fixture/unknown",),
            "columns": _columns(CURRENT_REQUIREMENTS),
        },
        {
            "revisions": (CURRENT_REVISION, PREVIOUS_REVISION),
            "columns": _columns(CURRENT_REQUIREMENTS),
        },
        {
            "revisions": (CURRENT_REVISION,),
            "columns": _columns(PREVIOUS_REQUIREMENTS),
        },
        {
            "version_table": False,
            "columns": _columns(CURRENT_REQUIREMENTS),
        },
    ),
)
@pytest.mark.unit
async def test_schema_probe_rejects_unknown_multiple_and_inconsistent_states(
    connection_kwargs: dict[str, object],
) -> None:
    connection = FakeAsyncPostgresConnection(**connection_kwargs)

    result = await probe_postgres_schema_state(connection, **_probe_kwargs())

    assert result.state is SchemaState.DIVERGENT
    assert not result.is_compatible
    with pytest.raises(SchemaDivergentError):
        result.require_compatible()


@pytest.mark.unit
async def test_asserting_schema_probe_stops_on_divergence() -> None:
    connection = FakeAsyncPostgresConnection(
        revisions=(CURRENT_REVISION,),
        columns=_columns(PREVIOUS_REQUIREMENTS),
    )

    with pytest.raises(SchemaDivergentError, match="signature"):
        await assert_postgres_schema_state(connection, **_probe_kwargs())


@pytest.mark.unit
async def test_schema_probe_wraps_database_errors_fail_closed() -> None:
    connection = FakeAsyncPostgresConnection(fail_query="information_schema.tables")

    with pytest.raises(SchemaProbeError, match="schema probe query failed"):
        await probe_postgres_schema_state(connection, **_probe_kwargs())


@pytest.mark.unit
def test_schema_signature_is_order_independent_and_extensions_are_pinned() -> None:
    first = SchemaSignature.from_requirements(
        {"fixture_table": ("watermark_advanced", "id")},
        extensions=("vector",),
    )
    second = SchemaSignature.from_requirements(
        {"fixture_table": ("id", "watermark_advanced")},
        extensions=("vector",),
    )

    assert first == second
    assert first.requirements == {"fixture_table": ("id", "watermark_advanced")}


def _load_migration(filename: str) -> Any:
    path = ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location("schema_state_migration_fixture", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_freshness_watermark_migration_is_linear_and_additive() -> None:
    migration = _load_migration("20260905_0011_b2_freshness_watermark.py")

    assert migration.revision == "20260905_0011_b2_freshness_watermark"
    assert migration.down_revision == "20260904_0010_shop_profile"

    sql_buffer = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": sql_buffer},
    )
    with Operations.context(context):
        migration.upgrade()
    sql = sql_buffer.getvalue().lower()

    assert "alter table query_family_freshness add column watermark_advanced" in sql
    assert "alter table users" not in sql
    assert "alter table restaurants" not in sql
    assert "evidence_bundle_current" not in sql
    assert "drop table" not in sql


@pytest.mark.unit
def test_migration_chain_fixture_keeps_clean_and_n_minus_1_inputs_distinct() -> None:
    migration = _load_migration("20260905_0011_b2_freshness_watermark.py")
    clean = FakeAsyncPostgresConnection(version_table=False)
    n_minus_1 = FakeAsyncPostgresConnection(
        revisions=(PREVIOUS_REVISION,),
        columns=_columns(PREVIOUS_REQUIREMENTS),
    )

    # This fixture proves the probe's two pre-upgrade inputs are both
    # recognized; Alembic remains the only component that applies DDL.
    import asyncio

    clean_result = asyncio.run(probe_postgres_schema_state(clean, **_probe_kwargs()))
    n_minus_1_result = asyncio.run(
        probe_postgres_schema_state(n_minus_1, **_probe_kwargs())
    )

    assert migration.down_revision == PREVIOUS_REVISION or migration.down_revision == "20260904_0010_shop_profile"
    assert clean_result.state is SchemaState.CLEAN
    assert n_minus_1_result.state is SchemaState.N_MINUS_1
