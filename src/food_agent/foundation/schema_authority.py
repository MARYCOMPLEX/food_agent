"""Read-only checks for the Alembic-provisioned PostgreSQL schema.

Application adapters may verify that deployment completed, but they never
repair the schema. All writes to PostgreSQL schema objects belong to the
checked-in Alembic chain.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

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
_VERSION_TABLE_PROBE = """
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'alembic_version'
"""
_VERSION_PROBE = """
SELECT version_num
FROM public.alembic_version
ORDER BY version_num
"""

# The current migration is intentionally represented here as a small, stable
# default signature.  Callers that own a larger schema can pass a complete
# ``SchemaSignature`` to the probe without importing Alembic.
CURRENT_SCHEMA_REVISION: Final = "20260905_0012_b1_source_batches"
N_MINUS_1_SCHEMA_REVISION: Final = "20260905_0011_b2_freshness_watermark"
EXPECTED_SCHEMA_REVISION: Final = CURRENT_SCHEMA_REVISION
PREVIOUS_SCHEMA_REVISION: Final = N_MINUS_1_SCHEMA_REVISION
_FRESHNESS_COLUMNS_N_MINUS_1: Final = (
    "active_refresh_workflow_id",
    "bundle_version",
    "coverage",
    "family_id",
    "updated_at",
    "verified_at",
    "watermarks",
)
_FRESHNESS_COLUMNS_CURRENT: Final = _FRESHNESS_COLUMNS_N_MINUS_1 + ("watermark_advanced",)
_SOURCE_BATCH_COLUMNS: Final = (
    "batch_id",
    "canonical_key",
    "connector_id",
    "connector_version",
    "content_hash",
    "created_at",
    "language",
    "normalizer_version",
    "payload",
    "region",
    "source_id",
    "tenant_scope",
    "watermark",
)
_SOURCE_BATCH_ITEM_COLUMNS: Final = ("batch_id", "evidence_id")


class SchemaNotReadyError(RuntimeError):
    """Raised when an adapter starts before Alembic has provisioned its schema."""


class SchemaState(StrEnum):
    """Known states of a migration-managed PostgreSQL installation."""

    CLEAN = "clean"
    N_MINUS_1 = "n_minus_1"
    CURRENT = "current"
    DIVERGENT = "divergent"


class SchemaProbeError(SchemaNotReadyError):
    """Raised when schema-state probing cannot produce a trustworthy answer."""


class SchemaDivergentError(SchemaProbeError):
    """Raised by the asserting probe when an installation is divergent."""


@dataclass(frozen=True, slots=True)
class SchemaSignature:
    """Canonical signature for the schema objects a probe owns.

    ``tables`` contains exact column sets for the named tables.  Extensions
    are also compared exactly within the extension allow-list supplied by the
    two signatures; unrelated PostgreSQL extensions are intentionally outside
    a caller's signature.
    """

    tables: tuple[tuple[str, tuple[str, ...]], ...]
    extensions: tuple[str, ...] = ()

    @classmethod
    def from_requirements(
        cls,
        requirements: Mapping[str, Sequence[str]],
        *,
        extensions: Sequence[str] = (),
    ) -> SchemaSignature:
        return cls(
            tables=_normalize_table_requirements(requirements),
            extensions=_normalize_names(extensions, field="extensions"),
        )

    @property
    def requirements(self) -> dict[str, tuple[str, ...]]:
        """Return a detached mapping suitable for query construction."""

        return dict(self.tables)


@dataclass(frozen=True, slots=True)
class SchemaStateProbeResult:
    """Read-only result returned by :func:`probe_postgres_schema_state`."""

    state: SchemaState
    revision: str | None
    observed_revisions: tuple[str, ...]
    observed_signature: SchemaSignature
    expected_revision: str
    previous_revision: str
    reason: str | None = None

    @property
    def schema_state(self) -> SchemaState:
        """Compatibility name for callers that use ``schema_state``."""

        return self.state

    @property
    def status(self) -> str:
        """Return the stable serialized state value."""

        return self.state.value

    @property
    def is_compatible(self) -> bool:
        return self.state in {
            SchemaState.CLEAN,
            SchemaState.N_MINUS_1,
            SchemaState.CURRENT,
        }

    def require_compatible(self) -> SchemaStateProbeResult:
        """Fail closed for a divergent state and return this result otherwise."""

        if self.state is SchemaState.DIVERGENT:
            detail = self.reason or "schema state is divergent"
            raise SchemaDivergentError(detail)
        return self


# A concise alias is useful to adapters without making the result contract
# dependent on the implementation module name.
SchemaProbeResult = SchemaStateProbeResult


def _normalize_names(values: Sequence[str], *, field: str) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    normalized = tuple(str(value) for value in values)
    if any(not value or value != value.strip() for value in normalized):
        raise ValueError(f"{field} must contain non-empty names")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field} must not contain duplicates")
    return tuple(sorted(normalized))


def _normalize_table_requirements(
    requirements: Mapping[str, Sequence[str]],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not isinstance(requirements, Mapping):
        raise TypeError("schema requirements must be a mapping")
    normalized: list[tuple[str, tuple[str, ...]]] = []
    for table_name, columns in requirements.items():
        table = str(table_name)
        if not table or table != table.strip():
            raise ValueError("schema table names must be non-empty")
        if isinstance(columns, str):
            columns = (columns,)
        column_names = _normalize_names(columns, field=f"columns for {table}")
        normalized.append((table, column_names))
    return tuple(sorted(normalized))


# Construct the default signatures only after their normalization helpers are
# defined.  This keeps module import deterministic for every adapter that
# imports schema authority during test collection or application bootstrap.
DEFAULT_CURRENT_SCHEMA_SIGNATURE: Final = SchemaSignature.from_requirements(
    {
        "evidence_source_batches": _SOURCE_BATCH_COLUMNS,
        "evidence_source_batch_items": _SOURCE_BATCH_ITEM_COLUMNS,
        "query_family_freshness": _FRESHNESS_COLUMNS_CURRENT,
    }
)
DEFAULT_N_MINUS_1_SCHEMA_SIGNATURE: Final = SchemaSignature.from_requirements(
    {
        "evidence_source_batches": (),
        "evidence_source_batch_items": (),
        "query_family_freshness": _FRESHNESS_COLUMNS_CURRENT,
    }
)
CURRENT_SCHEMA_SIGNATURE: Final = DEFAULT_CURRENT_SCHEMA_SIGNATURE
N_MINUS_1_SCHEMA_SIGNATURE: Final = DEFAULT_N_MINUS_1_SCHEMA_SIGNATURE


def _coerce_signature(
    value: SchemaSignature | Mapping[str, Sequence[str]],
    *,
    extensions: Sequence[str] = (),
) -> SchemaSignature:
    if isinstance(value, SchemaSignature):
        if extensions:
            raise ValueError("extensions must be included in a SchemaSignature")
        return value
    return SchemaSignature.from_requirements(value, extensions=extensions)


def _add_signature_extensions(
    signature: SchemaSignature,
    extensions: Sequence[str],
) -> SchemaSignature:
    if not extensions:
        return signature
    return SchemaSignature(
        tables=signature.tables,
        extensions=_normalize_names((*signature.extensions, *extensions), field="extensions"),
    )


def _resolve_revision(
    primary: str | None,
    alias: str | None,
    default: str,
    *,
    label: str,
) -> str:
    if primary is not None and alias is not None and primary != alias:
        raise ValueError(f"{label} values disagree")
    value = primary if primary is not None else alias
    value = default if value is None else str(value)
    if not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty revision")
    return value


def _resolve_signature(
    primary: SchemaSignature | Mapping[str, Sequence[str]] | None,
    alias: SchemaSignature | Mapping[str, Sequence[str]] | None,
    default: SchemaSignature,
    *,
    label: str,
) -> SchemaSignature:
    if primary is None and alias is None:
        return default
    first = default if primary is None else _coerce_signature(primary)
    if alias is None:
        return first
    second = _coerce_signature(alias)
    if primary is not None and first != second:
        raise ValueError(f"{label} values disagree")
    return second


def _row_value(row: Any, key: str, *, source: str) -> object:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        try:
            return getattr(row, key)
        except AttributeError:
            raise SchemaProbeError(f"malformed {source} row: missing {key}") from exc


async def _fetch_probe_rows(connection: Any, query: str, *args: object) -> tuple[Any, ...]:
    try:
        rows = await connection.fetch(query, *args)
        return tuple(rows)
    except Exception as exc:
        raise SchemaProbeError(f"schema probe query failed: {type(exc).__name__}") from exc


def _signature_matches(expected: SchemaSignature, observed: SchemaSignature) -> bool:
    return expected == observed


async def probe_postgres_schema_state(
    connection: Any,
    *,
    expected_revision: str | None = None,
    previous_revision: str | None = None,
    current_revision: str | None = None,
    n_minus_1_revision: str | None = None,
    current_signature: SchemaSignature | Mapping[str, Sequence[str]] | None = None,
    expected_signature: SchemaSignature | Mapping[str, Sequence[str]] | None = None,
    previous_signature: SchemaSignature | Mapping[str, Sequence[str]] | None = None,
    n_minus_1_signature: SchemaSignature | Mapping[str, Sequence[str]] | None = None,
    current_extensions: Sequence[str] = (),
    previous_extensions: Sequence[str] = (),
) -> SchemaStateProbeResult:
    """Classify a PostgreSQL installation without changing it.

    The probe recognizes only a missing migration table with no owned objects,
    exactly one N-1 revision with its exact signature, and exactly one current
    revision with its exact signature.  Unknown or multiple revisions and
    unversioned objects return ``divergent``.  Connection/query failures and
    malformed rows raise :class:`SchemaProbeError` so callers cannot treat an
    incomplete probe as a safe migration state.
    """

    current = _resolve_revision(
        expected_revision,
        current_revision,
        CURRENT_SCHEMA_REVISION,
        label="current revision",
    )
    previous = _resolve_revision(
        previous_revision,
        n_minus_1_revision,
        N_MINUS_1_SCHEMA_REVISION,
        label="N-1 revision",
    )
    if current == previous:
        raise ValueError("current and N-1 revisions must differ")

    current_sig = _resolve_signature(
        current_signature,
        expected_signature,
        DEFAULT_CURRENT_SCHEMA_SIGNATURE,
        label="current signature",
    )
    previous_sig = _resolve_signature(
        previous_signature,
        n_minus_1_signature,
        DEFAULT_N_MINUS_1_SCHEMA_SIGNATURE,
        label="N-1 signature",
    )
    if current_extensions:
        current_sig = _add_signature_extensions(current_sig, current_extensions)
    if previous_extensions:
        previous_sig = _add_signature_extensions(previous_sig, previous_extensions)

    owned_tables = tuple(sorted(set(current_sig.requirements) | set(previous_sig.requirements)))
    owned_extensions = tuple(sorted(set(current_sig.extensions) | set(previous_sig.extensions)))

    table_rows = await _fetch_probe_rows(connection, _VERSION_TABLE_PROBE)
    if len(table_rows) > 1:
        return _divergent_result(
            current,
            previous,
            SchemaSignature.from_requirements({}),
            (),
            "schema probe found multiple alembic_version tables",
        )
    if table_rows:
        version_rows = await _fetch_probe_rows(connection, _VERSION_PROBE)
        observed_revisions = tuple(
            _revision_value(_row_value(row, "version_num", source="revision"))
            for row in version_rows
        )
    else:
        observed_revisions = ()

    column_rows = (
        await _fetch_probe_rows(connection, _COLUMN_PROBE, owned_tables)
        if owned_tables
        else ()
    )
    observed_tables: dict[str, set[str]] = {table: set() for table in owned_tables}
    try:
        for row in column_rows:
            table_name = _text_value(_row_value(row, "table_name", source="column"), "table_name")
            column_name = _text_value(_row_value(row, "column_name", source="column"), "column_name")
            if table_name in observed_tables:
                observed_tables[table_name].add(column_name)
    except SchemaProbeError:
        raise
    except Exception as exc:
        raise SchemaProbeError("malformed column probe row") from exc

    extension_rows = (
        await _fetch_probe_rows(connection, _EXTENSION_PROBE, owned_extensions)
        if owned_extensions
        else ()
    )
    observed_extensions: set[str] = set()
    for row in extension_rows:
        observed_extensions.add(_text_value(_row_value(row, "extname", source="extension"), "extname"))
    observed = SchemaSignature.from_requirements(
        {table: tuple(sorted(columns)) for table, columns in observed_tables.items()},
        extensions=tuple(sorted(observed_extensions)),
    )

    if not observed_revisions:
        if _has_owned_objects(observed):
            return _divergent_result(
                current,
                previous,
                observed,
                observed_revisions,
                "owned schema objects exist without an Alembic revision",
            )
        return SchemaStateProbeResult(
            state=SchemaState.CLEAN,
            revision=None,
            observed_revisions=observed_revisions,
            observed_signature=observed,
            expected_revision=current,
            previous_revision=previous,
        )

    if len(observed_revisions) != 1:
        return _divergent_result(
            current,
            previous,
            observed,
            observed_revisions,
            "schema has unknown or multiple Alembic revisions",
        )

    revision = observed_revisions[0]
    if revision == current and _signature_matches(current_sig, observed):
        state = SchemaState.CURRENT
        reason = None
    elif revision == previous and _signature_matches(previous_sig, observed):
        state = SchemaState.N_MINUS_1
        reason = None
    elif revision not in {current, previous}:
        state = SchemaState.DIVERGENT
        reason = f"unknown Alembic revision: {revision}"
    else:
        state = SchemaState.DIVERGENT
        reason = f"revision {revision} does not match its schema signature"
    return SchemaStateProbeResult(
        state=state,
        revision=revision,
        observed_revisions=observed_revisions,
        observed_signature=observed,
        expected_revision=current,
        previous_revision=previous,
        reason=reason,
    )


def _revision_value(value: object) -> str:
    return _text_value(value, "version_num")


def _text_value(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise SchemaProbeError(f"malformed {field} value")
    return value


def _has_owned_objects(signature: SchemaSignature) -> bool:
    return bool(signature.extensions) or any(columns for _, columns in signature.tables)


def _divergent_result(
    current: str,
    previous: str,
    observed: SchemaSignature,
    revisions: tuple[str, ...],
    reason: str,
) -> SchemaStateProbeResult:
    return SchemaStateProbeResult(
        state=SchemaState.DIVERGENT,
        revision=revisions[0] if len(revisions) == 1 else None,
        observed_revisions=revisions,
        observed_signature=observed,
        expected_revision=current,
        previous_revision=previous,
        reason=reason,
    )


async def probe_schema_state(
    connection: Any,
    **kwargs: Any,
) -> SchemaStateProbeResult:
    """Alias for :func:`probe_postgres_schema_state`."""

    return await probe_postgres_schema_state(connection, **kwargs)


async def assert_postgres_schema_state(
    connection: Any,
    **kwargs: Any,
) -> SchemaStateProbeResult:
    """Probe and raise when the installation is divergent."""

    return (await probe_postgres_schema_state(connection, **kwargs)).require_compatible()


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


__all__ = [
    "CURRENT_SCHEMA_REVISION",
    "CURRENT_SCHEMA_SIGNATURE",
    "DEFAULT_CURRENT_SCHEMA_SIGNATURE",
    "DEFAULT_N_MINUS_1_SCHEMA_SIGNATURE",
    "EXPECTED_SCHEMA_REVISION",
    "N_MINUS_1_SCHEMA_REVISION",
    "N_MINUS_1_SCHEMA_SIGNATURE",
    "PREVIOUS_SCHEMA_REVISION",
    "SchemaDivergentError",
    "SchemaNotReadyError",
    "SchemaProbeError",
    "SchemaProbeResult",
    "SchemaSignature",
    "SchemaState",
    "SchemaStateProbeResult",
    "assert_postgres_schema_ready",
    "assert_postgres_schema_state",
    "probe_postgres_schema_state",
    "probe_schema_state",
]
