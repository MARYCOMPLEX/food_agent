"""Background search task + recovery payload builder."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from loguru import logger

from xhs_food.contracts import (
    AgentToolExecutionContext,
    ContextMessage,
    ResearchContextSnapshot,
    StableResultMapperPort,
)
from xhs_food.events import get_emitter
from xhs_food.experience.results import StableResultMapper
from xhs_food.services import get_session_manager, get_user_storage_service
from xhs_food.services.user_storage import generate_restaurant_hash

from .state import bind_search_tool_context, get_orchestrator, load_state, update_state


async def run_stream_search(
    session_id: str,
    query: str,
    *,
    result_mapper: StableResultMapperPort | None = None,
    tool_context: AgentToolExecutionContext | None = None,
) -> None:
    """Background task driving the orchestrator + persisting results."""
    orchestrator = get_orchestrator(session_id)
    emitter = await get_emitter(session_id)

    try:
        manager = await get_session_manager()
        history = await manager.get_context(session_id)
        if history and len(history) > 1:
            orchestrator.restore_context(
                ResearchContextSnapshot(
                    messages=tuple(
                        ContextMessage(role=msg["role"], content=msg["content"])
                        for msg in history[:-1]
                        if msg["role"] in {"user", "assistant"}
                    )
                ),
                merge=True,
            )

        if tool_context is None:
            raise RuntimeError("managed MCP search context is required")
        with bind_search_tool_context(tool_context):
            await orchestrator.search_stream(query, emitter)

        await update_state(session_id, status="completed")
        if result_mapper is None:
            await _persist_results(session_id, query, orchestrator, manager)
        else:
            await _persist_results(
                session_id,
                query,
                orchestrator,
                manager,
                result_mapper=result_mapper,
            )

    except Exception as exc:
        logger.exception(f"stream search failed: {session_id}")
        await update_state(session_id, status="error", error=str(exc))
        await emitter.emit_error(str(exc))
        try:
            storage = await get_user_storage_service()
            await storage.update_history_status(session_id, "error")
        except Exception:
            pass


async def _persist_results(
    session_id: str,
    query: str,
    orchestrator,
    manager,
    *,
    result_mapper: StableResultMapperPort | None = None,
) -> None:
    state = await load_state(session_id) or {}
    summary = state.get("summary", "")
    if summary:
        try:
            await manager.add_assistant_message(session_id, summary)
        except Exception as exc:
            logger.warning(f"add_assistant_message failed: {exc}")

    storage = await get_user_storage_service()

    mapper = result_mapper or StableResultMapper()
    restaurants: list[dict[str, Any]] = []
    result_summary = ""
    # We previously read events from the emitter buffer; with the bus we
    # rely on the orchestrator having stored recommendations on its
    # context. Fall back to context for both restaurants and summary.
    context_snapshot = orchestrator.snapshot_context()
    for recommendation in context_snapshot.recommendations:
        rec_name = recommendation.key
        rec_dict = deepcopy(recommendation.payload)
        if not rec_dict:
            continue
        if "id" not in rec_dict:
            rec_dict = mapper.to_persisted_restaurant(
                rec_dict,
                generate_restaurant_hash(rec_name, rec_dict.get("tel")),
            )
        # The legacy writer mutates context before the restaurant upsert await.
        orchestrator.update_context_recommendation(rec_name, rec_dict)
        try:
            saved = await storage.upsert_restaurant(rec_dict)
            if saved:
                rec_dict = mapper.to_persisted_restaurant(rec_dict, saved.id)
                orchestrator.update_context_recommendation(rec_name, rec_dict)
        except Exception as exc:
            logger.warning(f"upsert_restaurant failed: {exc}")
        restaurants.append(rec_dict)

    result_summary = context_snapshot.last_summary or summary

    try:
        await storage.save_search_result(
            session_id=session_id,
            restaurants=restaurants,
            summary=result_summary or summary,
            filtered_count=state.get("filtered_count", 0),
            query=query,
        )
        await storage.update_history_status(
            session_id=session_id,
            status="completed",
            results_count=len(restaurants),
        )
    except Exception as exc:
        logger.warning(f"save_search_result failed: {exc}")

    await update_state(
        session_id,
        restaurants=restaurants,
        summary=result_summary or summary,
    )


# ---------------------------------------------------------------------------
# Recovery payload (used by POST /v1/search when only sessionId provided)
# ---------------------------------------------------------------------------


async def build_recovery_payload(
    session_id: str,
    result_mapper: StableResultMapperPort | None = None,
) -> dict[str, Any]:
    """Return the unified-search response for the recover branch.

    Source-of-truth order: PostgreSQL (search_results) → search_history →
    in-memory state. The bus replay handles in-flight reconnects; this
    endpoint reports the higher-level session state.
    """
    try:
        storage = await get_user_storage_service()
        all_results = await storage.get_all_search_results(session_id)
        if all_results:
            mapper = result_mapper or StableResultMapper()
            return mapper.to_completed_recovery(session_id, tuple(all_results))

        history = await storage.get_history_by_session(session_id)
        if history:
            if history.status == "loading":
                state = await load_state(session_id)
                if state and state.get("status") == "loading":
                    return {
                        "success": True,
                        "data": {
                            "sessionId": session_id,
                            "status": "loading",
                            "streamUrl": f"/v1/search/stream/{session_id}",
                            "message": "搜索进行中，请连接 SSE 流继续接收",
                        },
                    }
                return {
                    "success": False,
                    "data": {
                        "sessionId": session_id,
                        "status": "interrupted",
                        "query": history.query,
                        "message": "搜索已中断，请重新搜索",
                    },
                }
            if history.status == "error":
                return {
                    "success": False,
                    "data": {
                        "sessionId": session_id,
                        "status": "error",
                        "query": history.query,
                        "message": "搜索失败，请重试",
                    },
                }
    except Exception as exc:
        logger.warning(f"recover from storage failed: {exc}")

    return {
        "success": False,
        "data": {
            "sessionId": session_id,
            "status": "not_found",
            "message": "会话不存在或已过期",
        },
    }


# Re-export for symmetry — old code expected a router on this module.
# The router is now empty; routes live in ``routes.py``. Importers that
# referenced this module's router will receive an empty include.
from fastapi import APIRouter  # noqa: E402

router = APIRouter()
