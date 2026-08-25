"""Read-only checks for the Alembic-provisioned PostgreSQL schema.

Application adapters may verify that deployment completed, but they never
repair the schema. All writes to PostgreSQL schema objects belong to the
checked-in Alembic chain.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_COLUMN_PROBE = """
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = ANY($1::text[])
"""
_EXTENSION_PROBE = """
SELECT extname
FROM pg_extension
WHERE extname = ANY($1::text[])
"""


class SchemaNotReadyError(RuntimeError):
    """Raised when an adapter starts before Alembic has provisioned its schema."""


async def assert_postgres_schema_ready(
    connection: Any,
    requirements: Mapping[str, Sequence[str]],
    *,
    extensions: Sequence[str] = (),
) -> None:
    """Fail closed when required tables, columns, or extensions are absent."""

    table_names = tuple(requirements)
    rows = await connection.fetch(_COLUMN_PROBE, table_names)
    observed: dict[str, set[str]] = {table: set() for table in table_names}
    for row in rows:
        table_name = str(row["table_name"])
        if table_name in observed:
            observed[table_name].add(str(row["column_name"]))

    missing_columns = {
        table: sorted(set(columns) - observed[table])
        for table, columns in requirements.items()
        if set(columns) - observed[table]
    }
    missing_tables = sorted(table for table in missing_columns if not observed[table])
    missing_details = {
        table: columns for table, columns in missing_columns.items() if table not in missing_tables
    }
    if missing_tables or missing_details:
        details = {"tables": missing_tables, "columns": missing_details}
        raise SchemaNotReadyError(f"Alembic schema is not ready: {details}")

    required_extensions = tuple(extensions)
    if not required_extensions:
        return
    extension_rows = await connection.fetch(_EXTENSION_PROBE, required_extensions)
    observed_extensions = {str(row["extname"]) for row in extension_rows}
    missing_extensions = sorted(set(required_extensions) - observed_extensions)
    if missing_extensions:
        raise SchemaNotReadyError(
            "Alembic schema extensions are not ready: " + ", ".join(missing_extensions)
        )


__all__ = ["SchemaNotReadyError", "assert_postgres_schema_ready"]
