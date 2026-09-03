"""Conversation-aware intent resolution for the Food Research Agent.

Intent is resolved from the current input plus the conversation transcript on
every turn. There is deliberately no result-set/follow-up classifier here;
the model decides whether a turn changes, narrows, or continues a request.
"""

from __future__ import annotations

from typing import Any

from xhs_food.common import extract_json
from xhs_food.domain_packs.food.intent import FoodSearchIntent
from xhs_food.prompts import INTENT_PARSER_INSTRUCTION_ZH, INTENT_PARSER_SYSTEM_PROMPT_ZH
from xhs_food.schemas import ConversationContext


class IntentParseResult:
    """Transport-neutral result returned by the intent resolver."""

    def __init__(
        self,
        success: bool,
        intent: FoodSearchIntent | None = None,
        *,
        need_clarify: bool = False,
        questions: list[str] | None = None,
        raw_output: str = "",
        error: str | None = None,
    ) -> None:
        self.success = success
        self.intent = intent
        self.need_clarify = need_clarify
        self.questions = questions or []
        self.raw_output = raw_output
        self.error = error


class IntentParserAgent:
    """Resolve a complete intent using the full bounded conversation context."""

    def __init__(self, llm_service: Any | None = None, *, history_turns: int = 10) -> None:
        self._llm_service = llm_service
        self._history_turns = max(1, history_turns)

    async def _get_llm_service(self) -> Any:
        if self._llm_service is None:
            from xhs_food.services.llm_service import LLMService

            self._llm_service = LLMService()
        return self._llm_service

    async def parse(
        self,
        user_input: str,
        context: ConversationContext | None = None,
    ) -> IntentParseResult:
        try:
            llm = await self._get_llm_service()
            from langchain_core.messages import HumanMessage, SystemMessage

            history = (
                context.get_history_for_llm(self._history_turns)
                if context is not None
                else ""
            )
            instruction = INTENT_PARSER_INSTRUCTION_ZH.format(user_input=user_input)
            if history:
                instruction += (
                    "\n\n已有对话（请结合其语义重新推理，不要套用固定追问类别）:\n"
                    + history
                )
            response = await llm.call(
                [
                    SystemMessage(content=INTENT_PARSER_SYSTEM_PROMPT_ZH),
                    HumanMessage(content=instruction),
                ]
            )
            raw_output = response.content if hasattr(response, "content") else str(response)
            parsed = extract_json(raw_output)
            if not isinstance(parsed, dict):
                return IntentParseResult(
                    False,
                    raw_output=raw_output,
                    error="Failed to parse JSON from LLM output",
                )
            if parsed.get("need_clarify", False):
                return IntentParseResult(
                    False,
                    need_clarify=True,
                    questions=[str(item) for item in parsed.get("questions", []) if item],
                    raw_output=raw_output,
                )
            intent = FoodSearchIntent.from_dict(parsed)
            if not intent.location or intent.location.strip() in {"未指定", "不明确", "未知"}:
                return IntentParseResult(
                    False,
                    need_clarify=True,
                    questions=["请问您想在哪个城市或区域搜索美食？"],
                    raw_output=raw_output,
                )
            return IntentParseResult(True, intent, raw_output=raw_output)
        except Exception as exc:  # caller maps this to a stable Agent error
            return IntentParseResult(False, error=str(exc))


__all__ = ["IntentParseResult", "IntentParserAgent"]
