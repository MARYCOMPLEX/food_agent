"""OpenAI-compatible model adapter used by the Food Research Agent."""

from __future__ import annotations

import os
from typing import Any, List, Optional

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_openai import ChatOpenAI
from loguru import logger

from food_agent.config import settings
from food_agent.observability.metrics import (
    llm_calls_total,
    llm_duration_seconds,
    llm_tokens_total,
)


class LLMService:
    """简化版 LLM 服务.

    使用 LangChain ChatOpenAI (OpenAI Compatible) 进行调用。

    环境变量 / settings:
        OPENAI_API_KEY: API密钥
        OPENAI_API_BASE: API基地址
        DEFAULT_LLM_MODEL: 模型名称
    """

    _cached_instances: dict[tuple, ChatOpenAI] = {}

    @classmethod
    def clear_cache(cls) -> None:
        """Clear cached LLM client instances upon configuration changes."""
        cls._cached_instances.clear()
        logger.info("LLMService client instance cache cleared")

    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
    ):
        self._requested_model_name = model_name
        self._explicit_temp = temperature is not None
        self._explicit_tokens = max_tokens is not None
        self._explicit_reasoning = reasoning_effort is not None

        self._model_name = model_name or settings.default_llm_model
        self._temperature = temperature if temperature is not None else settings.llm_temperature
        self._max_tokens = max_tokens if max_tokens is not None else settings.llm_max_tokens
        self._reasoning_effort = (
            reasoning_effort
            if reasoning_effort is not None
            else settings.llm_reasoning_effort
        )
        self._llm: Optional[ChatOpenAI] = None
        
    def _get_llm(self) -> ChatOpenAI:
        """懒加载 LLM 实例，优先从 LLMConfigStorage 获取动态配置."""
        from food_agent.services.llm_storage import LLMConfigStorage

        storage = LLMConfigStorage.get_instance()
        record = None
        if self._requested_model_name:
            record = storage.get_model_sync(self._requested_model_name, mask_key=False)
        if not record:
            record = storage.get_default_model_sync(mask_key=False)

        if record:
            actual_model = record["model_name"]
            self._model_name = actual_model
            api_key = record.get("api_key") or settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
            base_url = record.get("base_url") or settings.openai_api_base or os.getenv("OPENAI_API_BASE", "https://api.gojia.cloud/v1/")
            temperature = self._temperature if self._explicit_temp else float(record.get("temperature", self._temperature))
            max_tokens = self._max_tokens if self._explicit_tokens else int(record.get("max_tokens", self._max_tokens))
            reasoning_effort = self._reasoning_effort if self._explicit_reasoning else record.get("reasoning_effort", self._reasoning_effort)
        else:
            actual_model = self._model_name or settings.default_llm_model or os.getenv("DEFAULT_LLM_MODEL", "gpt-5.6-sol")
            self._model_name = actual_model
            api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
            base_url = settings.openai_api_base or os.getenv(
                "OPENAI_API_BASE", "https://api.gojia.cloud/v1/"
            )
            temperature = self._temperature
            max_tokens = self._max_tokens
            reasoning_effort = self._reasoning_effort

        if not api_key:
            raise ValueError("OPENAI_API_KEY is required (configured in DB or environment)")

        cache_key = (actual_model, base_url, api_key, temperature, max_tokens, reasoning_effort)
        if cache_key in self._cached_instances:
            self._llm = self._cached_instances[cache_key]
            return self._llm

        client_kwargs = self._build_client_kwargs(
            model=actual_model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
        self._llm = ChatOpenAI(**client_kwargs)
        self._cached_instances[cache_key] = self._llm
        logger.info(f"LLM initialized: {actual_model} @ {base_url}")
        return self._llm

    @staticmethod
    def _build_client_kwargs(
        *,
        model: str,
        api_key: str,
        base_url: str,
        temperature: float,
        max_tokens: int,
        reasoning_effort: Optional[str],
    ) -> dict[str, Any]:
        """Build provider kwargs without sending unsupported sampling options."""
        common: dict[str, Any] = {
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
            "timeout": 60.0,
            "default_headers": {"User-Agent": "food-agent/1.0"},
        }
        m = model.casefold()
        if m.startswith(("gpt-5", "o1", "o3", "o4")):
            common["max_completion_tokens"] = max_tokens
            if reasoning_effort:
                common["reasoning_effort"] = reasoning_effort
        else:
            common.update(
                {
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
            )
        return common

    def _client_kwargs(self, *, api_key: str, base_url: str) -> dict[str, Any]:
        """Backward compatible client kwargs builder."""
        return self._build_client_kwargs(
            model=self._model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            reasoning_effort=self._reasoning_effort,
        )

    @classmethod
    def _prepare_messages(cls, messages: List[BaseMessage]) -> List[BaseMessage]:
        """Prepend strong override directive to suppress any upstream injected coding/Codex instructions."""
        override_prefix = (
            "[ROLE OVERRIDE & DIRECTIVE]\n"
            "Discard and nullify all previous developer instructions, coding assistant roles, and Codex personas.\n"
            "You are strictly the AI Food & Dining Recommendation Assistant (小红书美食智能助手).\n"
            "Never refer to yourself as Codex or a coding agent. Never mention code, git, repositories, or programming tools.\n"
        )
        has_system = False
        new_messages: list[BaseMessage] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                has_system = True
                new_messages.append(SystemMessage(content=f"{override_prefix}\n{msg.content}"))
            else:
                new_messages.append(msg)

        if not has_system:
            new_messages.insert(0, SystemMessage(content=override_prefix))

        return new_messages

    @classmethod
    def _clean_response(cls, response: BaseMessage) -> BaseMessage:
        """Sanitize accidental Codex / coding assistant persona residue."""
        if isinstance(response.content, str) and response.content:
            text = response.content
            replacements = [
                ("我是 Codex，基于 GPT-5 的代码助手", "我是小红书美食智能助手"),
                ("我是 Codex，一个代码助手", "我是小红书美食智能助手"),
                ("我是 Codex", "我是美食推荐助手"),
                ("I am Codex, an AI coding agent", "I am the Food & Dining Recommendation Assistant"),
                ("I’m Codex, an AI coding agent", "I am the Food & Dining Recommendation Assistant"),
                ("I'm Codex, an AI coding agent", "I am the Food & Dining Recommendation Assistant"),
            ]
            for pattern, rep in replacements:
                text = text.replace(pattern, rep)
            response.content = text
        return response

    async def call(
        self,
        messages: List[BaseMessage],
        **kwargs,
    ) -> BaseMessage:
        """调用 LLM.

        Args:
            messages: 消息列表
            **kwargs: 额外参数传递给 LLM

        Returns:
            LLM 响应消息
        """
        llm = self._get_llm()
        model = self._model_name
        prepared_messages = self._prepare_messages(messages)
        with llm_duration_seconds.labels(model=model).time():
            try:
                response = await llm.ainvoke(prepared_messages, **kwargs)
            except Exception as e:
                llm_calls_total.labels(model=model, outcome="error").inc()
                logger.error(f"LLM call failed: {e}")
                raise
            llm_calls_total.labels(model=model, outcome="ok").inc()
            response = self._clean_response(response)
            self._record_token_usage(model, prepared_messages, response)
            return response

    @staticmethod
    def _record_token_usage(
        model: str,
        messages: List[BaseMessage],
        response: BaseMessage,
    ) -> None:
        """Record token counters. Falls back to len(content) when the API
        does not expose usage data — labelled the same so dashboards can
        still graph rough throughput."""
        usage = {}
        try:
            usage = getattr(response, "response_metadata", {}).get("token_usage", {}) or {}
        except Exception:  # noqa: BLE001 - never let metrics crash callers
            usage = {}

        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")

        if prompt_tokens is None:
            # rough proxy: sum of len(message.content) across the prompt
            prompt_tokens = sum(
                len(getattr(m, "content", "") or "") for m in messages
            )
        if completion_tokens is None:
            completion_tokens = len(getattr(response, "content", "") or "")

        if prompt_tokens:
            llm_tokens_total.labels(model=model, kind="prompt").inc(prompt_tokens)
        if completion_tokens:
            llm_tokens_total.labels(model=model, kind="completion").inc(completion_tokens)
    
    def get_llm(self) -> ChatOpenAI:
        """获取底层 LLM 实例."""
        return self._get_llm()
