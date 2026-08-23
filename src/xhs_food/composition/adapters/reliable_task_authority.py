"""PostgreSQL authority adapters for the opt-in reliable task policy.

The adapters use an already-started Composition-Root-owned SQLAlchemy unit of
work.  They never create tables or engines.  The table names and columns are
Alembic-owned deployment contracts; B0 only supplies the transactional port
implementation that B1 migrations will provision.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy import text

from xhs_food.contracts import (
    ContractError,
    ContractPayload,
    ResultCommitReceipt,
    TaskProgressProjection,
    TaskStatus,
)

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")

UnitOfWorkFactory = Callable[[], Any]


class PostgresReliableTaskAuthority:
    """Commit reliable results and cancellation receipts in one SQL transaction.

    ``reliable_task_results`` is expected to have a unique ``idempotency_key``
    and JSON payload column.  The adapter intentionally fails if the Alembic
    revision is absent; runtime DDL and an implicit fallback would violate the
    authority contract.
    """

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        result_table: str = "reliable_task_results",
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._result_table = _identifier(result_table)

    async def commit_result(
        self,
        task_id: str,
        workflow_id: str,
        run_id: str,
        result: ContractPayload,
        *,
        idempotency_key: str,
    ) -> ResultCommitReceipt:
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        async with self._unit_of_work_factory() as unit:
            session = unit.session_for_adapter()
            row, already_committed = await self._insert_or_read(
                session,
                task_id=task_id,
                workflow_id=workflow_id,
                run_id=run_id,
                status="completed",
                payload=payload,
                idempotency_key=idempotency_key,
            )
            _assert_identity(row, task_id, workflow_id, run_id)
            await unit.commit()
        return _receipt(row, task_id, workflow_id, run_id, already_committed=already_committed)

    async def commit_failed(
        self,
        task_id: str,
        workflow_id: str,
        run_id: str,
        error: ContractError,
        *,
        idempotency_key: str,
    ) -> ResultCommitReceipt:
        payload = json.dumps(
            {"status": TaskStatus.FAILED.value, "error": error.model_dump(mode="json")},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        async with self._unit_of_work_factory() as unit:
            row, already_committed = await self._insert_or_read(
                unit.session_for_adapter(),
                task_id=task_id,
                workflow_id=workflow_id,
                run_id=run_id,
                status=TaskStatus.FAILED.value,
                payload=payload,
                idempotency_key=idempotency_key,
            )
            _assert_identity(row, task_id, workflow_id, run_id)
            await unit.commit()
        return _receipt(row, task_id, workflow_id, run_id, already_committed=already_committed)

    async def commit_cancelled(
        self,
        task_id: str,
        workflow_id: str,
        run_id: str,
        *,
        idempotency_key: str,
    ) -> ResultCommitReceipt:
        async with self._unit_of_work_factory() as unit:
            session = unit.session_for_adapter()
            row, already_committed = await self._insert_or_read(
                session,
                task_id=task_id,
                workflow_id=workflow_id,
                run_id=run_id,
                status="cancelled",
                payload=json.dumps({"status": "cancelled"}),
                idempotency_key=idempotency_key,
            )
            _assert_identity(row, task_id, workflow_id, run_id)
            await unit.commit()
        return _receipt(row, task_id, workflow_id, run_id, already_committed=already_committed)

    async def reconcile(
        self,
        task_id: str,
        workflow_id: str,
        run_id: str,
    ) -> ContractPayload | None:
        async with self._unit_of_work_factory() as unit:
            session = unit.session_for_adapter()
            result = await session.execute(
                text(
                    f"SELECT task_id, workflow_id, run_id, status, payload "
                    f"FROM {self._result_table} "
                    "WHERE task_id = :task_id AND workflow_id = :workflow_id "
                    "AND run_id = :run_id ORDER BY committed_at DESC LIMIT 1"
                ),
                {"task_id": task_id, "workflow_id": workflow_id, "run_id": run_id},
            )
            row = result.mappings().first()
            if row is None:
                return None
            _assert_identity(row, task_id, workflow_id, run_id)
            value = row.get("payload")
            if isinstance(value, str):
                parsed = json.loads(value)
            elif isinstance(value, Mapping):
                parsed = dict(value)
            else:
                parsed = {}
            row_status = str(row.get("status"))
            if row_status in {"completed", "failed", "cancelled"}:
                parsed.setdefault("status", row_status)
            return parsed

    async def _insert_or_read(
        self,
        session: Any,
        *,
        task_id: str,
        workflow_id: str,
        run_id: str,
        status: str,
        payload: str,
        idempotency_key: str,
    ) -> tuple[Mapping[str, Any], bool]:
        result = await session.execute(
            text(
                f"INSERT INTO {self._result_table} "
                "(task_id, workflow_id, run_id, status, payload, idempotency_key, committed_at) "
                "VALUES (:task_id, :workflow_id, :run_id, :status, CAST(:payload AS JSONB), "
                ":idempotency_key, CURRENT_TIMESTAMP) "
                "ON CONFLICT DO NOTHING "
                "RETURNING task_id, workflow_id, run_id, status, payload, "
                "idempotency_key, committed_at, result_version"
            ),
            {
                "task_id": task_id,
                "workflow_id": workflow_id,
                "run_id": run_id,
                "status": status,
                "payload": payload,
                "idempotency_key": idempotency_key,
            },
        )
        row = result.mappings().first()
        if row is not None:
            return row, False
        existing = await session.execute(
            text(
                f"SELECT task_id, workflow_id, run_id, status, payload, "
                f"idempotency_key, committed_at, result_version FROM {self._result_table} "
                "WHERE idempotency_key = :idempotency_key OR ("
                "task_id = :task_id AND workflow_id = :workflow_id AND run_id = :run_id) "
                "ORDER BY (idempotency_key = :idempotency_key) DESC LIMIT 1"
            ),
            {
                "idempotency_key": idempotency_key,
                "task_id": task_id,
                "workflow_id": workflow_id,
                "run_id": run_id,
            },
        )
        row = existing.mappings().first()
        if row is None:
            raise RuntimeError("idempotent result insert returned no receipt")
        return row, True


class PostgresTaskProgressProjectionStore:
    """Durable query projection store; it is never used as a workflow checkpoint."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        projection_table: str = "task_progress_projection",
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._projection_table = _identifier(projection_table)

    async def get(self, task_id: str) -> TaskProgressProjection | None:
        async with self._unit_of_work_factory() as unit:
            result = await unit.session_for_adapter().execute(
                text(
                    f"SELECT payload FROM {self._projection_table} "
                    "WHERE task_id = :task_id"
                ),
                {"task_id": task_id},
            )
            row = result.mappings().first()
            if row is None:
                return None
            payload = row.get("payload")
            if isinstance(payload, str):
                payload = json.loads(payload)
            if not isinstance(payload, Mapping):
                raise TypeError("task projection payload must be a JSON object")
            return TaskProgressProjection.model_validate(payload)

    async def put(self, projection: TaskProgressProjection) -> TaskProgressProjection:
        if projection.executable_checkpoint:
            raise ValueError("task progress projections cannot be execution checkpoints")
        async with self._unit_of_work_factory() as unit:
            session = unit.session_for_adapter()
            current_result = await session.execute(
                text(
                    f"SELECT payload FROM {self._projection_table} "
                    "WHERE task_id = :task_id FOR UPDATE"
                ),
                {"task_id": projection.task_id},
            )
            current = current_result.mappings().first()
            if current is not None:
                value = current.get("payload")
                if isinstance(value, str):
                    value = json.loads(value)
                if isinstance(value, Mapping):
                    current_projection = TaskProgressProjection.model_validate(value)
                    if _projection_is_older(current_projection, projection):
                        await unit.commit()
                        return current_projection
            await session.execute(
                text(
                    f"INSERT INTO {self._projection_table} "
                    "(task_id, payload, updated_at) VALUES "
                    "(:task_id, CAST(:payload AS JSONB), :updated_at) "
                    "ON CONFLICT (task_id) DO UPDATE SET payload = EXCLUDED.payload, "
                    "updated_at = EXCLUDED.updated_at"
                ),
                {
                    "task_id": projection.task_id,
                    "payload": projection.model_dump_json(),
                    "updated_at": projection.updated_at,
                },
            )
            await unit.commit()
        return projection


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid PostgreSQL identifier: {value!r}")
    return value


def _assert_identity(row: Mapping[str, Any], task_id: str, workflow_id: str, run_id: str) -> None:
    if (
        str(row.get("task_id")) != task_id
        or str(row.get("workflow_id")) != workflow_id
        or str(row.get("run_id")) != run_id
    ):
        raise RuntimeError(
            f"idempotency receipt belongs to a different task/run: {row.get('idempotency_key')}"
        )


def _receipt(
    row: Mapping[str, Any],
    task_id: str,
    workflow_id: str,
    run_id: str,
    *,
    already_committed: bool,
) -> ResultCommitReceipt:
    return ResultCommitReceipt(
        task_id=task_id,
        workflow_id=workflow_id,
        run_id=run_id,
        committed=True,
        already_committed=already_committed,
        result_version=(str(row["result_version"]) if row.get("result_version") else None),
        terminal_status=_terminal_status(row.get("status")),
    )


def _terminal_status(value: object) -> TaskStatus | None:
    try:
        status = TaskStatus(str(value))
    except ValueError:
        return None
    return status if status.is_terminal else None


def _projection_is_older(
    current: TaskProgressProjection, candidate: TaskProgressProjection
) -> bool:
    if current.turn_id != candidate.turn_id:
        try:
            current_turn = int(current.turn_id or "0")
            candidate_turn = int(candidate.turn_id or "0")
            return candidate_turn < current_turn
        except ValueError:
            # Turn IDs are normally decimal strings.  Keep a deterministic
            # fallback for legacy/non-numeric values without treating every
            # cross-turn candidate as stale.
            return (candidate.turn_id or "") < (current.turn_id or "")
    if current.status.is_terminal:
        return True
    if candidate.status is current.status and candidate.progress < current.progress:
        return True
    return candidate.updated_at < current.updated_at


__all__ = ["PostgresReliableTaskAuthority", "PostgresTaskProgressProjectionStore"]
