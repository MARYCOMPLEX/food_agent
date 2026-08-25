from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from xhs_food.services.user_storage.search_results import SearchResultsMixin

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "database"
SESSION_ID = "10000000-0000-0000-0000-000000000001"


class SchemaContractError(RuntimeError):
    """Raised when a repository statement is incompatible with the replayed schema."""


@dataclass
class IndexContract:
    columns: list[str]
    unique: bool


@dataclass
class SearchResultsSchema:
    exists: bool = False
    columns: list[str] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    unique_constraints: list[list[str]] = field(default_factory=list)
    indexes: dict[str, IndexContract] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return {
            "exists": self.exists,
            "columns": self.columns,
            "primary_key": self.primary_key,
            "unique_constraints": self.unique_constraints,
            "indexes": {
                name: {"columns": index.columns, "unique": index.unique}
                for name, index in self.indexes.items()
            },
        }


class SchemaReplayConnection:
    """Small asyncpg contract fake for replaying only the legacy table lifecycle."""

    def __init__(self) -> None:
        self.schema = SearchResultsSchema()
        self.rows: list[dict[str, Any]] = []
        self.closed = False
        self.database_url: str | None = None

    async def replay(self, sql: str) -> None:
        await self.execute(sql)

    async def execute(self, sql: str, *args: Any) -> str:
        normalized = " ".join(sql.split())
        upper = normalized.upper()

        if args and upper.startswith("INSERT INTO SEARCH_RESULTS"):
            self._require_columns("turn_id", "query")
            self._require_composite_conflict_target()
            session_id, turn_id, restaurants, summary, filtered_count, query = args
            row = next(
                (
                    item
                    for item in self.rows
                    if item["session_id"] == session_id and item["turn_id"] == turn_id
                ),
                None,
            )
            values = {
                "session_id": session_id,
                "turn_id": turn_id,
                "restaurants": restaurants,
                "summary": summary,
                "filtered_count": filtered_count,
                "query": query,
            }
            if row is None:
                values["created_at"] = datetime(2024, 1, 2, 3, 4, tzinfo=UTC)
                self.rows.append(values)
                return "INSERT 0 1"
            created_at = row["created_at"]
            row.update(values)
            row["created_at"] = created_at
            return "INSERT 0 1"

        if "DROP TABLE IF EXISTS SEARCH_RESULTS" in upper:
            self.schema = SearchResultsSchema()
            self.rows.clear()

        table_match = re.search(
            r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+search_results\s*\((.*?)\)\s*;",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if table_match and not self.schema.exists:
            self._create_table(table_match.group(1))

        for column_name in re.findall(
            r"ALTER\s+TABLE\s+search_results\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+(\w+)",
            sql,
            flags=re.IGNORECASE,
        ):
            self._require_table()
            if column_name not in self.schema.columns:
                self.schema.columns.append(column_name)
                if column_name == "turn_id":
                    for row in self.rows:
                        row[column_name] = 1
                elif column_name == "query":
                    for row in self.rows:
                        row[column_name] = None

        if re.search(
            r"DROP\s+CONSTRAINT\s+IF\s+EXISTS\s+search_results_session_id_key",
            sql,
            flags=re.IGNORECASE,
        ):
            self.schema.unique_constraints = [
                columns for columns in self.schema.unique_constraints if columns != ["session_id"]
            ]

        for match in re.finditer(
            r"CREATE\s+(UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+(\w+)\s+"
            r"ON\s+search_results\s*\((.*?)\)",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            self._require_table()
            name = match.group(2)
            if name not in self.schema.indexes:
                self.schema.indexes[name] = IndexContract(
                    columns=[part.strip() for part in match.group(3).split(",")],
                    unique=bool(match.group(1)),
                )

        return "OK"

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        normalized = " ".join(sql.split()).upper()
        self._require_table()
        if "MAX(TURN_ID)" in normalized:
            self._require_columns("turn_id")
            matching = [row["turn_id"] for row in self.rows if row["session_id"] == args[0]]
            return {"next_turn": max(matching, default=0) + 1}
        if "AND TURN_ID = $2" in normalized:
            self._require_columns("turn_id")
            return next(
                (
                    row.copy()
                    for row in self.rows
                    if row["session_id"] == args[0] and row["turn_id"] == args[1]
                ),
                None,
            )
        if "ORDER BY TURN_ID DESC LIMIT 1" in normalized:
            self._require_columns("turn_id")
            matching = [row for row in self.rows if row["session_id"] == args[0]]
            return max(matching, key=lambda row: row["turn_id"]).copy() if matching else None
        raise AssertionError(f"Unexpected fetchrow statement: {sql}")

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        normalized = " ".join(sql.split()).upper()
        self._require_table()
        if "ORDER BY TURN_ID ASC" in normalized:
            self._require_columns("turn_id")
            return [
                row.copy()
                for row in sorted(self.rows, key=lambda item: item["turn_id"])
                if row["session_id"] == args[0]
            ]
        if "FROM INFORMATION_SCHEMA.COLUMNS" in normalized:
            return [
                {"column_name": column, "data_type": "fixture", "column_default": None}
                for column in self.schema.columns
            ]
        raise AssertionError(f"Unexpected fetch statement: {sql}")

    async def close(self) -> None:
        self.closed = True

    def _create_table(self, body: str) -> None:
        self.schema.exists = True
        for definition in body.split(","):
            tokens = definition.strip().split()
            if not tokens:
                continue
            column_name = tokens[0]
            self.schema.columns.append(column_name)
            upper = definition.upper()
            if "PRIMARY KEY" in upper:
                self.schema.primary_key = [column_name]
            if "UNIQUE" in upper:
                self.schema.unique_constraints.append([column_name])

    def _require_table(self) -> None:
        if not self.schema.exists:
            raise SchemaContractError('relation "search_results" does not exist')

    def _require_columns(self, *columns: str) -> None:
        self._require_table()
        missing = [column for column in columns if column not in self.schema.columns]
        if missing:
            raise SchemaContractError(f"missing search_results columns: {', '.join(missing)}")

    def _require_composite_conflict_target(self) -> None:
        target = self.schema.indexes.get("idx_results_session_turn")
        if target is None or not target.unique:
            raise SchemaContractError("no unique constraint matching (session_id, turn_id)")


class _AcquireContext:
    def __init__(self, connection: SchemaReplayConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> SchemaReplayConnection:
        return self.connection

    async def __aexit__(self, *_args: Any) -> None:
        return None


class ReplayPool:
    def __init__(self, connection: SchemaReplayConnection) -> None:
        self.connection = connection

    def acquire(self) -> _AcquireContext:
        return _AcquireContext(self.connection)


class SearchResultsRepository(SearchResultsMixin):
    def __init__(self, connection: SchemaReplayConnection) -> None:
        self._initialized = True
        self._pool = ReplayPool(connection)


def _fixture_sql(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _expected_contracts() -> dict[str, Any]:
    return json.loads(
        (FIXTURE_DIR / "search_results_schema_contract.json").read_text(encoding="utf-8")
    )


async def _replay(name: str) -> SchemaReplayConnection:
    connection = SchemaReplayConnection()
    await connection.replay(_fixture_sql(name))
    return connection


def _load_turn_id_migration() -> ModuleType:
    script_path = Path(__file__).parent.parent / "scripts" / "migrate_turn_id.py"
    spec = importlib.util.spec_from_file_location("turn_id_migration_fixture", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("fixture_name", "contract_name"),
    [
        ("clean_db.sql", "clean_db"),
        ("search_results_pre_turn_id.sql", "pre_turn_id"),
        ("search_results_post_turn_id.sql", "post_turn_id"),
    ],
)
async def test_schema_fixtures_replay_to_declared_contract(
    fixture_name: str, contract_name: str
) -> None:
    connection = await _replay(fixture_name)

    assert connection.schema.snapshot() == _expected_contracts()[contract_name]

    await connection.replay(_fixture_sql(fixture_name))
    assert connection.schema.snapshot() == _expected_contracts()[contract_name]


@pytest.mark.parametrize(
    ("fixture_name", "expected_contract"),
    [
        ("clean_db.sql", "clean_db"),
        ("search_results_pre_turn_id.sql", "pre_turn_id"),
        ("search_results_post_turn_id.sql", "post_turn_id"),
    ],
)
async def test_runtime_initializer_does_not_mutate_the_current_schema_split(
    fixture_name: str, expected_contract: str
) -> None:
    connection = await _replay(fixture_name)
    assert connection.schema.snapshot() == _expected_contracts()[expected_contract]


async def test_turn_id_script_delegates_to_alembic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_turn_id_migration()
    calls: list[bool] = []

    monkeypatch.setattr(migration, "upgrade_head", lambda: calls.append(True))

    await migration.migrate()
    assert calls == [True]


@pytest.mark.parametrize(
    "fixture_name",
    ["clean_db.sql", "search_results_pre_turn_id.sql"],
)
async def test_repository_failure_contract_before_turn_id_migration(fixture_name: str) -> None:
    connection = await _replay(fixture_name)
    repository = SearchResultsRepository(connection)

    assert await repository.save_search_result(SESSION_ID, [{"name": "legacy"}]) is False
    assert await repository.get_search_result(SESSION_ID) is None
    assert await repository.get_all_search_results(SESSION_ID) == []


async def test_repository_multi_turn_contract_after_turn_id_migration() -> None:
    connection = await _replay("search_results_post_turn_id.sql")
    repository = SearchResultsRepository(connection)

    assert await repository.save_search_result(
        SESSION_ID,
        [{"name": "first"}],
        summary="first summary",
        filtered_count=1,
        query="first query",
        turn_id=1,
    )
    assert await repository.save_search_result(
        SESSION_ID,
        [{"name": "second"}],
        summary="second summary",
        filtered_count=2,
        query="second query",
    )
    assert await repository.save_search_result(
        SESSION_ID,
        [{"name": "second updated"}],
        summary="updated summary",
        filtered_count=3,
        query="updated query",
        turn_id=2,
    )

    first = await repository.get_first_search_result(SESSION_ID)
    latest = await repository.get_search_result(SESSION_ID)
    all_results = await repository.get_all_search_results(SESSION_ID)

    assert first is not None
    assert first["turn_id"] == 1
    assert first["restaurants"] == [{"name": "first"}]
    assert latest is not None
    assert latest["turn_id"] == 2
    assert latest["query"] == "updated query"
    assert latest["filtered_count"] == 3
    assert [result["turn_id"] for result in all_results] == [1, 2]
