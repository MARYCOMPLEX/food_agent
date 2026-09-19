"""HTTP task facade assembled only by the Composition Root."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Coroutine, Mapping, Sequence
from copy import deepcopy
from typing import Any, cast

from loguru import logger

from api.search import state as search_state
from api.search import tasks as search_tasks
from food_agent.contracts import (
    AgentToolExecutionContext,
    ContextMessage,
    ContractPayload,
    RecommendationSnapshot,
    ResearchContextSnapshot,
    ResearchOperation,
    ResearchTaskAdmission,
    ResearchTaskNotFoundError,
    StableResultMapperPort,
)
from food_agent.events import get_emitter
from food_agent.experience.results import StableResultMapper
from food_agent.services import get_session_manager, get_user_storage_service

TaskRunner = Callable[
    [str, str, AgentToolExecutionContext | None],
    Coroutine[Any, Any, None],
]
TaskSpawner = Callable[[Coroutine[Any, Any, None]], object]


class ResearchTaskFacade:
    """Expose task lifecycle while delegating execution to the active Agent."""

    def __init__(
        self,
        *,
        result_mapper: StableResultMapperPort | None = None,
        task_runner: TaskRunner | None = None,
        task_spawner: TaskSpawner = asyncio.create_task,
        session_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._result_mapper = result_mapper or StableResultMapper()
        self._task_runner = task_runner
        self._task_spawner = task_spawner
        self._session_id_factory = session_id_factory or (lambda: str(uuid.uuid4()))

    async def start_new(
        self,
        query: str,
        *,
        tool_context: AgentToolExecutionContext | None = None,
    ) -> ResearchTaskAdmission:
        session_id = self._session_id_factory()
        await search_state.update_state(
            session_id,
            status="loading",
            query=query,
            turn_id=1,
        )

        emitter = await get_emitter(session_id)
        if hasattr(emitter, "areset"):
            await emitter.areset()
        else:
            emitter.reset()

        try:
            manager = await get_session_manager()
            await manager.add_user_message(session_id, query)
        except Exception as exc:  # noqa: BLE001 - frozen best-effort policy
            logger.warning(f"add_user_message failed: {exc}")

        try:
            storage = await get_user_storage_service()
            create_search_history = getattr(  # noqa: B009 - frozen missing-method defect
                storage, "create_search_history"
            )
            await create_search_history(
                session_id=session_id,
                query=query,
                status="loading",
            )
        except Exception as exc:  # noqa: BLE001 - known legacy API mismatch
            logger.warning(f"create_search_history failed: {exc}")

        self._spawn_run(session_id, query, tool_context)
        return self._admission(session_id, ResearchOperation.QUERY, turn_id=1)

    async def refine(
        self,
        session_id: str,
        query: str,
        *,
        tool_context: AgentToolExecutionContext | None = None,
        history: Sequence[Mapping[str, Any]] | None = None,
    ) -> ResearchTaskAdmission:
        state = await search_state.load_state(session_id)
        if state is None:
            try:
                state = await self._restore_state_from_storage(session_id)
            except Exception:
                state = None

        turn_id = (state.get("turn_id") or 1) + 1 if state else ((len(history) // 2 + 1) if history else 2)
        await search_state.update_state(
            session_id,
            status="loading",
            query=query,
            turn_id=turn_id,
        )

        try:
            manager = await get_session_manager()
            if history:
                for msg in history:
                    r = str(msg.get("role", "user"))
                    c = str(msg.get("content", ""))
                    if r == "user":
                        await manager.add_user_message(session_id, c)
                    elif r == "assistant":
                        await manager.add_assistant_message(session_id, c)
            await manager.add_user_message(session_id, query)
        except Exception as exc:  # noqa: BLE001 - frozen best-effort policy
            logger.warning(f"add_user_message failed: {exc}")

        # Also restore orchestrator context directly if history is provided
        orchestrator = search_state.get_orchestrator(session_id)
        if history:
            messages = tuple(
                ContextMessage(role=str(msg["role"]), content=str(msg["content"]))
                for msg in history
                if msg.get("role") in {"user", "assistant"}
            )
            hist_city = orchestrator._context.target_city
            if not hist_city:
                for msg in history:
                    c = str(msg.get("content", ""))
                    for city_candidate in ("连云港", "北京", "上海", "广州", "深圳", "成都", "杭州", "南京", "武汉", "重庆", "西安", "苏州", "天津", "长沙", "郑州"):
                        if city_candidate in c:
                            hist_city = city_candidate
                            break
                    if hist_city:
                        break
            orchestrator.restore_context(
                ResearchContextSnapshot(
                    messages=messages,
                    target_city=hist_city,
                ),
                merge=False,
            )

        emitter = await get_emitter(session_id)
        if hasattr(emitter, "areset"):
            await emitter.areset()
        else:
            emitter.reset()

        self._spawn_run(session_id, query, tool_context)
        return self._admission(session_id, ResearchOperation.REFINE, turn_id=turn_id)

    async def recover(self, session_id: str) -> ContractPayload:
        return await search_tasks.build_recovery_payload(
            session_id, result_mapper=self._result_mapper
        )

    async def status(self, session_id: str) -> ContractPayload | None:
        state = await search_state.load_state(session_id)
        if state is None:
            return None
        emitter = await get_emitter(session_id)
        return cast(
            ContractPayload,
            {
                "sessionId": session_id,
                "status": state["status"],
                "loadingSteps": deepcopy(emitter.steps),
            },
        )

    async def results(self, session_id: str) -> ContractPayload | None:
        state = await search_state.load_state(session_id)
        if state is None:
            return None
        return self._result_mapper.to_http_results(session_id, state)

    def _spawn_run(
        self,
        session_id: str,
        query: str,
        tool_context: AgentToolExecutionContext | None,
    ) -> None:
        if self._task_runner is not None:
            run = self._task_runner(session_id, query, tool_context)
        else:
            run = search_tasks.run_stream_search(
                session_id,
                query,
                result_mapper=self._result_mapper,
                tool_context=tool_context,
            )
        self._task_spawner(run)

    def _admission(
        self, session_id: str, operation: ResearchOperation, *, turn_id: int
    ) -> ResearchTaskAdmission:
        return ResearchTaskAdmission(
            task_id=session_id,
            session_id=session_id,
            operation=operation,
            stream_ref=f"/v1/search/stream/{session_id}",
            turn_id=turn_id,
        )

    async def _restore_state_from_storage(self, session_id: str) -> dict[str, Any]:
        storage = await get_user_storage_service()
        first_result = await storage.get_first_search_result(session_id)
        if not first_result:
            raise ResearchTaskNotFoundError("Session not found")

        all_results = await storage.get_all_search_results(session_id)
        state = await search_state.update_state(
            session_id,
            status="completed",
            query=first_result.get("query", ""),
            turn_id=len(all_results) if all_results else 1,
            restaurants=first_result.get("restaurants", []),
        )

        manager = await get_session_manager()
        history = await manager.get_context(session_id)
        messages = tuple(
            ContextMessage(role=message["role"], content=message["content"])
            for message in (history or [])
            if message["role"] in {"user", "assistant"}
        )
        recommendations = tuple(
            RecommendationSnapshot(key=restaurant["name"], payload=deepcopy(restaurant))
            for restaurant in first_result.get("restaurants", [])
            if restaurant.get("name")
        )
        orchestrator = search_state.get_orchestrator(session_id)
        orchestrator.restore_context(
            ResearchContextSnapshot(
                messages=messages,
                recommendations=recommendations,
            ),
            merge=True,
        )

        logger.info(
            f"session restored: {len(first_result.get('restaurants', []))} restaurants, "
            f"turn_id={state['turn_id']}"
        )
        return state


__all__ = ["ResearchTaskFacade"]
