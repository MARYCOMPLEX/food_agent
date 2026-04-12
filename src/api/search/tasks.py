"""
Background tasks and recovery endpoint.

- _run_stream_search  (background task)
- GET /v1/search/recover/{sessionId}
"""

from fastapi import APIRouter, Path
from loguru import logger

from xhs_food.events import get_emitter, SearchEventType
from xhs_food.services import get_session_manager, get_user_storage_service

from .state import _sessions, _get_session, _get_orchestrator

router = APIRouter()


async def _run_stream_search(session_id: str, query: str):
    """后台流式搜索任务."""
    session = _get_session(session_id)
    orchestrator = _get_orchestrator(session_id)
    emitter = get_emitter(session_id)

    try:
        # 获取对话历史上下文
        manager = await get_session_manager()
        context = await manager.get_context(session_id)

        # 将历史上下文传递给 orchestrator（使用正确的方法）
        if context and len(context) > 1:
            # 有历史记录，设置到 orchestrator 的上下文中
            for msg in context[:-1]:  # 最后一条是当前 query，已经传入
                if msg["role"] == "user":
                    orchestrator._context.add_user_message(msg["content"])
                elif msg["role"] == "assistant":
                    orchestrator._context.add_assistant_message(msg["content"])

        await orchestrator.search_stream(query, emitter)
        session["status"] = "completed"

        # 保存 AI 响应摘要到 SessionManager
        summary = session.get("summary", "")
        if summary:
            await manager.add_assistant_message(session_id, summary)
            logger.debug(f"Saved assistant response to context: {session_id}")

        # 保存搜索结果到数据库（支持断线恢复）
        try:
            storage = await get_user_storage_service()
            from xhs_food.services.user_storage import generate_restaurant_hash

            # 从 emitter 获取已发送的 restaurant 事件并保存到 restaurants 表
            restaurants = []
            for event in emitter.get_sent_events():
                if event.type == SearchEventType.RESTAURANT:
                    restaurant_data = event.data.get("restaurant", {})
                    if restaurant_data.get("name"):
                        # Upsert to restaurants table and get hash ID
                        saved = await storage.upsert_restaurant(restaurant_data)
                        if saved:
                            # Add the hash ID to restaurant data
                            restaurant_data["id"] = saved.id
                        else:
                            # Generate hash ID even if save fails
                            restaurant_data["id"] = generate_restaurant_hash(
                                restaurant_data["name"],
                                restaurant_data.get("tel")
                            )
                        restaurants.append(restaurant_data)

            # 获取 summary
            result_summary = ""
            for event in emitter.get_sent_events():
                if event.type == SearchEventType.RESULT:
                    result_summary = event.data.get("summary", "")
                    break

            # 保存结果（自动计算 turn_id）
            await storage.save_search_result(
                session_id=session_id,
                restaurants=restaurants,
                summary=result_summary,
                filtered_count=session.get("filtered_count", 0),
                query=query,  # 传递本轮的查询
            )

            # 更新历史状态
            await storage.update_history_status(
                session_id=session_id,
                status="completed",
                results_count=len(restaurants),
            )
            logger.debug(f"Saved search results: {session_id}, {len(restaurants)} restaurants")

        except Exception as e:
            logger.warning(f"Failed to save search results: {e}")

    except Exception as e:
        logger.exception(f"Stream search failed for {session_id}")
        session["status"] = "error"
        session["error"] = str(e)
        await emitter.emit_error(str(e))

        # 更新历史状态为 error
        try:
            storage = await get_user_storage_service()
            await storage.update_history_status(session_id, "error")
        except Exception:
            pass


# =============================================================================
# GET /v1/search/recover/{sessionId} [LEGACY - 建议使用 POST /v1/search]
# =============================================================================

@router.get("/recover/{sessionId}")
async def search_recover(sessionId: str = Path(..., description="会话ID")):
    """
    [LEGACY] 断线恢复端点.

    ⚠️ 建议使用 POST /v1/search { sessionId } 代替此接口。

    用于用户断线后恢复搜索：
    - 已完成: 返回所有轮次的完整结果
    - 进行中: 返回 SSE 流信息，支持继续接收
    - 不存在: 从数据库查询历史结果

    Returns:
        status: loading | completed | error | not_found
        如果 completed:
            - restaurants/summary/total: 最新轮次的结果（向后兼容）
            - turns: 所有轮次的完整历史数组
            - turnCount: 总轮次数
        如果 loading: 包含 streamUrl 和 lastEventIndex
    """
    logger.info(f"=== [RECOVER DEBUG] 开始处理 sessionId: {sessionId} ===")

    # 1. 检查内存中的 session
    session = _sessions.get(sessionId)
    emitter = get_emitter(sessionId) if sessionId in _sessions else None

    logger.info(f"[RECOVER DEBUG] 第1层-内存查找: session存在={session is not None}, emitter存在={emitter is not None}")
    if session:
        logger.info(f"[RECOVER DEBUG] 第1层-session内容: status={session.get('status')}, keys={list(session.keys())}")

    if session:
        if session.get("status") == "completed":
            # 任务已完成，返回结果
            logger.info(f"[RECOVER DEBUG] 第1层-状态completed, emitter存在={emitter is not None}")
            if emitter:
                restaurants = []
                summary = ""
                sent_events = emitter.get_sent_events()
                logger.info(f"[RECOVER DEBUG] 第1层-事件数量: {len(sent_events)}")
                for event in sent_events:
                    if event.type == SearchEventType.RESTAURANT:
                        restaurants.append(event.data.get("restaurant", {}))
                    elif event.type == SearchEventType.RESULT:
                        summary = event.data.get("summary", "")

                logger.info(f"[RECOVER DEBUG] 第1层-提取结果: restaurants={len(restaurants)}, summary长度={len(summary)}")

                # BUG FIX: 如果 emitter 没有餐厅数据，fallback 到数据库查询
                if restaurants:
                    return {
                        "success": True,
                        "data": {
                            "sessionId": sessionId,
                            "status": "completed",
                            "restaurants": restaurants,
                            "summary": summary,
                            "total": len(restaurants),
                        }
                    }
                else:
                    logger.warning(f"[RECOVER DEBUG] 第1层-emitter无数据，fallback到数据库查询")

        elif session.get("status") == "loading":
            # 任务进行中，返回流信息
            last_index = emitter.get_sent_count() if emitter else 0
            return {
                "success": True,
                "data": {
                    "sessionId": sessionId,
                    "status": "loading",
                    "streamUrl": f"/v1/search/stream/{sessionId}?lastEventIndex={last_index}",
                    "lastEventIndex": last_index,
                    "message": "搜索进行中，请连接 SSE 流继续接收",
                }
            }

        elif session.get("status") == "error":
            return {
                "success": False,
                "data": {
                    "sessionId": sessionId,
                    "status": "error",
                    "error": session.get("error", "Unknown error"),
                }
            }

    # 2. 内存中没有，从数据库查询
    logger.info(f"[RECOVER DEBUG] 第2层-开始查询数据库...")
    try:
        storage = await get_user_storage_service()
        logger.info(f"[RECOVER DEBUG] 第2层-storage初始化成功: initialized={storage._initialized}")

        # 查询所有轮次的搜索结果
        all_results = await storage.get_all_search_results(sessionId)
        logger.info(f"[RECOVER DEBUG] 第2层-search_results查询结果: 共 {len(all_results)} 轮")
        if all_results:
            # 构建所有轮次数据
            turns = []
            for result in all_results:
                turns.append({
                    "turnId": result.get("turn_id", 1),
                    "query": result.get("query", ""),
                    "restaurants": result.get("restaurants", []),
                    "summary": result.get("summary", ""),
                    "total": len(result.get("restaurants", [])),
                    "createdAt": result.get("created_at"),
                })

            # 最新一轮作为主要结果
            latest = all_results[-1]
            logger.info(f"[RECOVER DEBUG] 第2层-返回 {len(turns)} 轮数据, 最新轮: turn_id={latest.get('turn_id')}")

            return {
                "success": True,
                "data": {
                    "sessionId": sessionId,
                    "status": "completed",
                    # 最新轮次的结果（向后兼容）
                    "turnId": latest.get("turn_id", 1),
                    "query": latest.get("query", ""),
                    "restaurants": latest.get("restaurants", []),
                    "summary": latest.get("summary", ""),
                    "total": len(latest.get("restaurants", [])),
                    # 所有轮次的完整历史
                    "turns": turns,
                    "turnCount": len(turns),
                    "fromDatabase": True,
                }
            }

        # 查询历史状态
        history = await storage.get_history_by_session(sessionId)
        logger.info(f"[RECOVER DEBUG] 第3层-search_history查询结果: {history is not None}")
        if history:
            logger.info(f"[RECOVER DEBUG] 第3层-search_history内容: status={history.status}, query={history.query[:50] if history.query else None}")
            if history.status == "loading":
                # 搜索中断了（可能服务重启）
                return {
                    "success": False,
                    "data": {
                        "sessionId": sessionId,
                        "status": "interrupted",
                        "query": history.query,
                        "message": "搜索已中断，请重新搜索",
                    }
                }
            elif history.status == "error":
                return {
                    "success": False,
                    "data": {
                        "sessionId": sessionId,
                        "status": "error",
                        "query": history.query,
                        "message": "搜索失败，请重试",
                    }
                }
    except Exception as e:
        logger.warning(f"[RECOVER DEBUG] 数据库查询异常: {e}")

    # 3. 完全找不到
    logger.info(f"[RECOVER DEBUG] 最终结果: not_found")
    return {
        "success": False,
        "data": {
            "sessionId": sessionId,
            "status": "not_found",
            "message": "会话不存在或已过期",
        }
    }
