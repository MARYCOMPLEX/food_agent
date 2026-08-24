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
    ResearchRequest,
    ResearchTask,
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
                "(task_id, workflow_id, run_id, status, payload, idempotency_key, "
                "result_version, committed_at) "
                "VALUES (:task_id, :workflow_id, :run_id, :status, CAST(:payload AS JSONB), "
                ":idempotency_key, :result_version, CURRENT_TIMESTAMP) "
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
                "result_version": _result_version(task_id, workflow_id, run_id),
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

    async def get_by_session_id(self, session_id: str) -> TaskProgressProjection | None:
        async with self._unit_of_work_factory() as unit:
            result = await unit.session_for_adapter().execute(
                text(
                    f"SELECT payload FROM {self._projection_table} "
                    "WHERE payload ->> 'session_id' = :session_id "
                    "ORDER BY updated_at DESC LIMIT 1"
                ),
                {"session_id": session_id},
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

    async def delete(self, task_id: str) -> bool:
        async with self._unit_of_work_factory() as unit:
            result = await unit.session_for_adapter().execute(
                text(
                    f"DELETE FROM {self._projection_table} "
                    "WHERE task_id = :task_id RETURNING task_id"
                ),
                {"task_id": task_id},
            )
            deleted = result.mappings().first() is not None
            await unit.commit()
        return deleted


class PostgresReliableTaskStore:
    """Durable reliable-task owner snapshots with PostgreSQL admission/CAS.

    The ``reliable_tasks`` table is an externally provisioned deployment
    contract.  This adapter never creates or alters schema; it only uses the
    caller-owned SQLAlchemy unit of work for one transaction per operation.
    """

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        task_table: str = "reliable_tasks",
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._task_table = _identifier(task_table)

    async def get(self, task_id: str) -> tuple[ResearchTask, ResearchRequest] | None:
        async with self._unit_of_work_factory() as unit:
            result = await unit.session_for_adapter().execute(
                text(
                    f"SELECT task_payload, request_payload FROM {self._task_table} "
                    "WHERE task_id = :task_id"
                ),
                {"task_id": task_id},
            )
            row = result.mappings().first()
            if row is None:
                return None
            return _task_record(row)

    async def admit(
        self, task: ResearchTask, request: ResearchRequest
    ) -> tuple[ResearchTask, bool]:
        task_payload, request_payload = _serialized_task_record(task, request)
        async with self._unit_of_work_factory() as unit:
            session = unit.session_for_adapter()
            result = await session.execute(
                text(
                    f"INSERT INTO {self._task_table} "
                    "(task_id, workflow_id, status, turn_id, run_id, task_payload, "
                    "request_payload, updated_at) VALUES "
                    "(:task_id, :workflow_id, :status, :turn_id, :run_id, "
                    "CAST(:task_payload AS JSONB), CAST(:request_payload AS JSONB), "
                    ":updated_at) ON CONFLICT (task_id) DO NOTHING "
                    "RETURNING task_payload, request_payload"
                ),
                {
                    "task_id": task.task_id,
                    "workflow_id": task.workflow_id,
                    "status": task.status.value,
                    "turn_id": task.turn_id,
                    "run_id": task.run_id,
                    "task_payload": task_payload,
                    "request_payload": request_payload,
                    "updated_at": task.updated_at,
                },
            )
            row = result.mappings().first()
            created = row is not None
            if row is None:
                row = await _select_task_row(session, self._task_table, task.task_id, lock=True)
            if row is None:
                raise RuntimeError("reliable task admission returned no durable row")
            admitted_task, _ = _task_record(row)
            if admitted_task.workflow_id != task.workflow_id:
                raise RuntimeError("task admission resolved to a different workflow identity")
            await unit.commit()
        return admitted_task, created

    async def save(self, task: ResearchTask, request: ResearchRequest) -> ResearchTask:
        task_payload, request_payload = _serialized_task_record(task, request)
        async with self._unit_of_work_factory() as unit:
            session = unit.session_for_adapter()
            current_row = await _select_task_row(session, self._task_table, task.task_id, lock=True)
            if current_row is None:
                raise RuntimeError("reliable task CAS found no durable task")
            current_task, current_request = _task_record(current_row)
            if current_task.workflow_id != task.workflow_id:
                raise RuntimeError("reliable task CAS rejected task/workflow identity")
            if current_request != request:
                raise RuntimeError("reliable task request identity changed during CAS")
            if _task_is_older(current_task, task):
                await unit.commit()
                return current_task
            result = await session.execute(
                text(
                    f"UPDATE {self._task_table} SET status = :status, turn_id = :turn_id, "
                    "run_id = :run_id, task_payload = CAST(:task_payload AS JSONB), "
                    "request_payload = CAST(:request_payload AS JSONB), "
                    "updated_at = :updated_at "
                    "WHERE task_id = :task_id AND workflow_id = :workflow_id "
                    "RETURNING task_payload, request_payload"
                ),
                {
                    "task_id": task.task_id,
                    "workflow_id": task.workflow_id,
                    "status": task.status.value,
                    "turn_id": task.turn_id,
                    "run_id": task.run_id,
                    "task_payload": task_payload,
                    "request_payload": request_payload,
                    "updated_at": task.updated_at,
                },
            )
            row = result.mappings().first()
            if row is None:
                raise RuntimeError("reliable task CAS rejected task/workflow identity")
            saved_task, saved_request = _task_record(row)
            if saved_request != request:
                raise RuntimeError("reliable task request identity changed during CAS")
            await unit.commit()
        return saved_task


async def _select_task_row(
    session: Any, table: str, task_id: str, *, lock: bool
) -> Mapping[str, Any] | None:
    suffix = " FOR UPDATE" if lock else ""
    result = await session.execute(
        text(
            f"SELECT task_payload, request_payload FROM {table} "
            f"WHERE task_id = :task_id{suffix}"
        ),
        {"task_id": task_id},
    )
    return result.mappings().first()


def _serialized_task_record(
    task: ResearchTask, request: ResearchRequest
) -> tuple[str, str]:
    return (
        json.dumps(task.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        json.dumps(
            request.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    )


def _task_record(row: Mapping[str, Any]) -> tuple[ResearchTask, ResearchRequest]:
    task_payload = row.get("task_payload")
    request_payload = row.get("request_payload")
    if isinstance(task_payload, str):
        task_payload = json.loads(task_payload)
    if isinstance(request_payload, str):
        request_payload = json.loads(request_payload)
    if not isinstance(task_payload, Mapping) or not isinstance(request_payload, Mapping):
        raise TypeError("reliable task row payloads must be JSON objects")
    return ResearchTask.model_validate(task_payload), ResearchRequest.model_validate(request_payload)


def _task_is_older(current: ResearchTask, candidate: ResearchTask) -> bool:
    """Return whether a candidate cannot replace the locked task snapshot."""

    if current.turn_id != candidate.turn_id:
        try:
            return int(candidate.turn_id or "0") < int(current.turn_id or "0")
        except ValueError:
            return (candidate.turn_id or "") < (current.turn_id or "")
    if current.status.is_terminal:
        return True
    if current.run_id and current.run_id != candidate.run_id:
        return True
    return candidate.updated_at < current.updated_at


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


def _result_version(task_id: str, workflow_id: str, run_id: str) -> str:
    """Return a stable receipt version for one task/workflow/run identity."""

    return f"{task_id}:{workflow_id}:{run_id}"


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


__all__ = [
    "PostgresReliableTaskAuthority",
    "PostgresReliableTaskStore",
    "PostgresTaskProgressProjectionStore",
]
