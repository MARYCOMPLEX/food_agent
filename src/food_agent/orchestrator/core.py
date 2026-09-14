"""Single entry point for the adaptive Food Research Agent."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from food_agent.contracts import (
    AgentToolExecutionContext,
    ContextMessage,
    RecommendationSnapshot,
    ResearchContextSnapshot,
)
from food_agent.observability.metrics import (
    search_duration_seconds,
    search_finished_total,
    search_started_total,
)
from food_agent.research.adaptive.food_workflow import AdaptiveFoodResearchWorkflow
from food_agent.schemas import ConversationContext, XHSFoodResponse

if TYPE_CHECKING:
    from food_agent.events.emitter import SearchEventEmitter

import json
import re

logger = logging.getLogger(__name__)

GREETING_PATTERNS = frozenset({
    "hi", "hello", "hey", "halo", "yo", "hihi",
    "你好", "您好", "哈喽", "嗨", "在吗", "在不在",
    "你是谁", "你能做什么", "你有什么功能", "介绍一下自己", "介绍自己",
    "帮助", "help", "说明", "早上好", "中午好", "下午好", "晚上好",
    "早", "晚安", "谢谢", "多谢", "感谢", "thx", "thanks", "thank you",
    "哈哈", "好的", "收到", "知道了", "拜拜", "再见", "bye", "ok",
})

GREETING_REGEX = re.compile(
    r"^(hi|hello|hey|halo|yo|hihi|你好|您好|哈喽|嗨|在吗|在不在|你是谁|你能做什么|你有什么功能|介绍一下自己|介绍自己|帮助|help|说明|早上好|中午好|下午好|晚上好|早|晚安|谢谢|多谢|感谢|thx|thanks|thank you|哈哈|好的|收到|知道了|拜拜|再见|bye|ok)[~！!？?，,。\s呀啊吧啦呢第几版]*$",
    re.IGNORECASE,
)

INTENT_CLASSIFY_SYSTEM_PROMPT = """你是一个智能美食助手的意图分流器。
请根据用户的最新输入和之前的对话历史，判断该输入应该进入哪个处理分支：
1. "chat":
   - 用户在打招呼、闲聊、表达情绪、感谢、询问助手的身份或功能。
   - 用户提出的美食需求极度模糊、没有明确指向任何城市或具体菜系/品类（例如只说“今天吃什么”、“推荐点好吃的”、“有什么好吃的”、“好饿”），此时应先与用户进行自然语言交流并引导用户提供更多信息。
2. "research":
   - 用户提出了具体的探店/美食检索需求，包含了明确的城市（如成都、广州、北京、上海）、商圈地标（如玉林、建设路、静安寺）、具体菜系品类（如火锅、早茶、钵钵鸡、烤肉）、具体店铺名或聚餐场景（如商务宴请、朋友聚会）。
   - 或者用户在之前的对话基础上，补充了城市、菜系或筛选条件。

严格按以下 JSON 格式输出，不要输出任何额外文字或解释：
{"intent": "chat" | "research", "reason": "判断原因"}
"""

CHAT_SYSTEM_PROMPT = """你是一位热情、贴心、懂吃的小红书美食探店智能向导 🍜。
你的核心目标是帮用户发现本地宝藏小店、挖掘真实口碑，避开网红营销与水军陷阱。

请根据用户的输入以及会话历史，进行自然、贴心的对话：
1. 语气亲切活泼、懂吃会吃，如同本地资深老饕朋友在跟用户聊天。
2. 如果用户在打招呼（如 "hi"）或询问功能，热情问好并简要介绍你可以帮他做的事情（如“深挖真实食客评价、排查负面差评、全网严选地道餐厅”），并主动询问用户目前在哪个城市、想吃什么风味。
3. 如果用户说“吃什么好”但没提供城市和偏好，主动给出一两个诱人的美食启发，并自然询问他所在的城市和预算。
4. 回复语言生动自然，适度使用 emoji，不要像生硬冷漠的问卷机器人。
5. 严禁提及代码、编程、测试或系统内部流程。
"""


class XHSFoodOrchestrator:
    """Thin transport-facing facade over one injected research workflow."""

    def __init__(
        self,
        *,
        workflow: AdaptiveFoodResearchWorkflow | Any | None = None,
        llm_service: Any = None,
        **_: Any,
    ) -> None:
        self._context = ConversationContext()
        self._workflow = workflow or _default_adaptive_workflow(llm_service)
        self._llm_service = llm_service

    @property
    def context(self) -> ConversationContext:
        return self._context

    @property
    def workflow(self) -> AdaptiveFoodResearchWorkflow | Any:
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

    async def _classify_intent(self, user_input: str) -> str:
        clean_text = user_input.strip()
        lower_text = clean_text.lower()
        normalized = re.sub(r"[^\w\s\u4e00-\u9fa5]", "", lower_text).strip()

        # Fast path for short common greetings / chitchat
        if (
            lower_text in GREETING_PATTERNS
            or normalized in GREETING_PATTERNS
            or GREETING_REGEX.match(clean_text)
            or GREETING_REGEX.match(lower_text)
        ):
            return "chat"

        if len(clean_text) <= 2:
            return "chat"

        # Model-based classification for longer / ambiguous queries
        try:
            from food_agent.services.llm_service import LLMService
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = self._llm_service or LLMService()
            history_text = self._context.get_history_for_llm(max_turns=3)
            prompt = (
                f"会话历史:\n{history_text}\n\n当前用户输入: {user_input}"
                if history_text
                else f"当前用户输入: {user_input}"
            )

            response = await asyncio.wait_for(
                llm.call(
                    [
                        SystemMessage(content=INTENT_CLASSIFY_SYSTEM_PROMPT),
                        HumanMessage(content=prompt),
                    ],
                    temperature=0.0,
                ),
                timeout=8.0,
            )
            content = response.content if hasattr(response, "content") else str(response)
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                intent = str(data.get("intent", "research")).lower().strip()
                if intent in {"chat", "research"}:
                    return intent
        except Exception as exc:
            logger.warning("Intent classification failed: %s, fallback to research", exc)

        return "research"

    async def _handle_conversational(self, user_input: str) -> XHSFoodResponse:
        from food_agent.services.llm_service import LLMService
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        self._context.add_user_message(user_input)
        self._context.turn_count += 1

        llm = self._llm_service or LLMService()
        messages = [SystemMessage(content=CHAT_SYSTEM_PROMPT)]

        # Include recent conversation turns for context continuity
        for msg in self._context.conversation_history[-7:-1]:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))

        messages.append(HumanMessage(content=user_input))

        try:
            response = await asyncio.wait_for(llm.call(messages), timeout=15.0)
            reply_text = str(response.content) if hasattr(response, "content") else str(response)
        except Exception as exc:
            logger.warning("Conversational LLM call failed or timed out: %s", exc)
            reply_text = (
                "您好！我是您的小红书美食智能助手 🍜。\n"
                "想找什么美食？告诉我在哪个城市、什么预算或口味偏好，我来为您深度探寻地道口碑好店！"
            )

        food_response = XHSFoodResponse(
            status="ok",
            summary=reply_text,
            recommendations=[],
            filtered_count=0,
        )
        self._record_response(food_response)
        return food_response

    async def _handle_conversational_stream(
        self,
        user_input: str,
        emitter: SearchEventEmitter,
    ) -> XHSFoodResponse:
        emitter.reset()
        await emitter.emit_progress("thinking", {"message": "正在为您组织回答..."})
        food_response = await self._handle_conversational(user_input)
        await emitter.emit_result(summary=food_response.summary, total=0, filtered=0)
        await emitter.emit_done()
        return food_response

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
        intent = await self._classify_intent(user_input)
        if intent == "chat":
            return await self._handle_conversational(user_input)
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
        emitter: SearchEventEmitter,
        *,
        tool_context: AgentToolExecutionContext | None = None,
    ) -> None:
        search_started_total.inc()
        started = time.perf_counter()
        outcome = "error"
        try:
            intent = await self._classify_intent(user_input)
            if intent == "chat":
                logger.info("Input classified as chat/clarify mode: %s", user_input)
                await self._handle_conversational_stream(user_input, emitter)
                outcome = "ok"
                return

            emitter.init_steps(user_input)
            async def progress_sink(payload: Mapping[str, Any]) -> None:
                kind = str(payload.get("kind", "progress"))
                await emitter.emit_progress(kind, dict(payload))

            await emitter.step_start("step1", "结合完整会话解析研究意图...")
            execution = await self._workflow.execute(
                user_input,
                self._context,
                tool_context=tool_context,
                progress_sink=progress_sink,
            )
            response = execution.response
            if execution.intent is not None:
                await emitter.step_done("step1", "意图解析完成", {"intent": execution.intent.to_dict()})
            else:
                await emitter.step_done("step1", "意图解析完成")
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
            logger.exception("adaptive stream failed")
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


def _default_adaptive_workflow(model: Any = None) -> AdaptiveFoodResearchWorkflow:
    """Build the standalone fail-closed adaptive workflow.

    The Composition Root normally injects the fully managed MCP session and
    repositories.  This fallback keeps direct library construction useful
    while ensuring an unconfigured process cannot call arbitrary tools.
    """

    from food_agent.research import UnavailableMcpToolSession
    from food_agent.research.adaptive import (
        AdaptiveCritic,
        AdaptivePlanner,
        ScriptedModelPort,
    )

    # The transport facade is usable as a library without bootstrapping the
    # application Composition Root.  In that mode the default is deliberately
    # fail-closed: no credentials, provider client, or implicit settings file
    # are read, and the model immediately records why no MCP work can run.
    # A fully configured Composition Root injects the real role-aware gateway.
    model_port = model or ScriptedModelPort(
        [{"stop": True, "reason": "managed MCP session is not configured"}]
    )
    return AdaptiveFoodResearchWorkflow(
        session_factory=UnavailableMcpToolSession,
        planner=AdaptivePlanner(model_port),
        critic=AdaptiveCritic(model_port),
    )
