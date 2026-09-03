"""Single entry point for the comment-first Food Research Agent."""

from __future__ import annotations

import logging
import time
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from xhs_food.contracts import (
    AgentToolExecutionContext,
    ContextMessage,
    RecommendationSnapshot,
    ResearchContextSnapshot,
)
from xhs_food.observability.metrics import (
    search_duration_seconds,
    search_finished_total,
    search_started_total,
)
from xhs_food.research import CommentFirstResearchWorkflow
from xhs_food.schemas import ConversationContext, XHSFoodResponse

if TYPE_CHECKING:
    from xhs_food.events.emitter import SearchEventEmitter

logger = logging.getLogger(__name__)


class XHSFoodOrchestrator:
    """Thin transport-facing facade over one injected research workflow."""

    def __init__(
        self,
        *,
        workflow: CommentFirstResearchWorkflow | None = None,
        llm_service: Any = None,
        **_: Any,
    ) -> None:
        self._context = ConversationContext()
        self._workflow = workflow or CommentFirstResearchWorkflow()
        self._llm_service = llm_service

    @property
    def context(self) -> ConversationContext:
        return self._context

    @property
    def workflow(self) -> CommentFirstResearchWorkflow:
        return self._workflow

    def reset_context(self) -> None:
        self._context.reset()

    def snapshot_context(self) -> ResearchContextSnapshot:
        return ResearchContextSnapshot(
            messages=tuple(
                ContextMessage(role=item["role"], content=item["content"])
                for item in deepcopy(self._context.conversation_history)
            ),
            recommendations=tuple(
                RecommendationSnapshot(key=name, payload=deepcopy(payload))
                for name, payload in self._context.last_recommendations.items()
            ),
            last_summary=getattr(self._context, "last_summary", "") or "",
            last_intent=deepcopy(self._context.last_intent),
            excluded_shops=tuple(self._context.excluded_shops),
            accumulated_preferences=tuple(self._context.accumulated_preferences),
            turn_count=self._context.turn_count,
            last_notes=tuple(deepcopy(self._context.last_notes)),
            target_city=self._context.target_city,
        )

    def restore_context(self, snapshot: ResearchContextSnapshot, *, merge: bool = False) -> None:
        messages = [
            {"role": item.role, "content": item.content} for item in snapshot.messages
        ]
        recommendations = {item.key: deepcopy(item.payload) for item in snapshot.recommendations}
        if merge:
            self._context.conversation_history.extend(messages)
            self._context.last_recommendations.update(recommendations)
            if snapshot.last_summary:
                self._context.last_summary = snapshot.last_summary  # type: ignore[attr-defined]
            return
        self._context.conversation_history = messages
        self._context.last_recommendations = recommendations
        self._context.last_intent = deepcopy(snapshot.last_intent)
        self._context.excluded_shops = list(snapshot.excluded_shops)
        self._context.accumulated_preferences = list(snapshot.accumulated_preferences)
        self._context.turn_count = snapshot.turn_count
        self._context.last_notes = [deepcopy(item) for item in snapshot.last_notes]
        self._context.target_city = snapshot.target_city
        self._context.last_summary = snapshot.last_summary  # type: ignore[attr-defined]

    def update_context_recommendation(self, key: str, recommendation: dict[str, Any]) -> None:
        self._context.last_recommendations[key] = recommendation

    async def process(
        self,
        user_input: str,
        *,
        conversation_history: list[dict[str, Any]] | None = None,
        tool_context: AgentToolExecutionContext | None = None,
    ) -> XHSFoodResponse:
        if conversation_history and not self._context.conversation_history:
            self._context.conversation_history = [
                {"role": str(item["role"]), "content": str(item["content"])}
                for item in conversation_history
                if item.get("role") in {"user", "assistant"}
            ]
        execution = await self._workflow.execute(
            user_input,
            self._context,
            tool_context=tool_context,
        )
        return execution.response

    async def search(self, user_input: str) -> XHSFoodResponse:
        response = await self.process(user_input)
        return self._record_response(response)

    async def search_stream(
        self,
        user_input: str,
        emitter: "SearchEventEmitter",
        *,
        tool_context: AgentToolExecutionContext | None = None,
    ) -> None:
        emitter.init_steps(user_input)
        search_started_total.inc()
        started = time.perf_counter()
        outcome = "error"
        try:
            await emitter.step_start("step1", "结合完整会话解析研究意图...")
            execution = await self._workflow.execute(
                user_input,
                self._context,
                tool_context=tool_context,
            )
            response = execution.response
            if execution.intent is not None:
                await emitter.step_done("step1", "意图解析完成", {"intent": execution.intent.to_dict()})
            else:
                await emitter.step_error("step1", response.error_message or response.summary)
            run = execution.run
            await emitter.step_start("step2", "采集小红书笔记及完整评论...")
            if run.notes:
                comment_count = sum(len(note.comments) for note in run.notes)
                await emitter.step_done("step2", f"获得 {len(run.notes)} 篇笔记、{comment_count} 条评论")
            else:
                await emitter.step_error("step2", "未获得可分析的评论证据")
            await emitter.step_start("step3", "从评论争议与共识中提取店铺线索...")
            await emitter.step_done("step3", f"识别到 {len(response.recommendations)} 家候选店铺")
            await emitter.step_start("step4", "登记评论证据并合并候选...")
            await emitter.step_done("step4", f"保留 {len(run.evidence_refs)} 条证据引用")
            await emitter.step_start("step5", "用大众点评补充店铺结构化资料...")
            await emitter.step_done("step5", f"写入 {len(run.profiles)} 份店铺档案")
            await emitter.step_start("step6", "生成研究结果...")
            for recommendation in response.recommendations:
                await emitter.emit_restaurant(recommendation.to_dict())
            await emitter.step_done("step6", response.summary)
            await emitter.emit_result(
                response.summary,
                len(response.recommendations),
                response.filtered_count,
            )
            if response.status == "error":
                await emitter.emit_error(response.error_message or response.summary)
            else:
                await emitter.emit_done()
                outcome = "ok"
            self._record_response(response)
        except Exception as exc:  # system boundary: turn into SSE error
            logger.exception("comment-first stream failed")
            await emitter.emit_error(str(exc))
        finally:
            search_finished_total.labels(status=outcome).inc()
            search_duration_seconds.observe(time.perf_counter() - started)

    def _record_response(self, response: XHSFoodResponse) -> XHSFoodResponse:
        if response.status == "ok":
            names = ", ".join(item.name for item in response.recommendations[:5])
            summary = response.summary + (f"\n推荐店铺: {names}" if names else "")
        else:
            summary = response.summary or response.error_message or "处理完成"
        self._context.last_summary = summary  # type: ignore[attr-defined]
        self._context.add_assistant_message(summary)
        return response


__all__ = ["XHSFoodOrchestrator"]
