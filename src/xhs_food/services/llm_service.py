"""
LLMService - 简化版LLM服务.

使用 LangChain ChatOpenAI (OpenAI Compatible) 调用，默认配置为硅基流动 (SiliconFlow) API。
"""

from __future__ import annotations

import os
from typing import List, Optional

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from loguru import logger

from xhs_food.observability.metrics import (
    llm_calls_total,
    llm_duration_seconds,
    llm_tokens_total,
)


# 默认配置：硅基流动 Qwen3-8B
DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1/"
DEFAULT_MODEL = "Qwen/Qwen3-8B"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 1024


class LLMService:
    """简化版 LLM 服务.
    
    使用 LangChain ChatOpenAI (OpenAI Compatible) 进行调用。
    默认配置为硅基流动 (SiliconFlow) API。
    
    环境变量:
        OPENAI_API_KEY: API密钥 (硅基流动或其他OpenAI兼容服务)
        OPENAI_API_BASE: API基地址 (默认 https://api.siliconflow.cn/v1/)
        DEFAULT_LLM_MODEL: 模型名称 (默认 Qwen/Qwen3-8B)
    """
    
    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        self._model_name = model_name or os.getenv("DEFAULT_LLM_MODEL", DEFAULT_MODEL)
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._llm: Optional[ChatOpenAI] = None
        
    def _get_llm(self) -> ChatOpenAI:
        """懒加载 LLM 实例."""
        if self._llm is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable is required")
            
            base_url = os.getenv("OPENAI_API_BASE", DEFAULT_BASE_URL)
            
            self._llm = ChatOpenAI(
                model=self._model_name,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                api_key=api_key,
                base_url=base_url,
            )
            logger.info(f"LLM initialized: {self._model_name} @ {base_url}")
        
        return self._llm
    
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
        with llm_duration_seconds.labels(model=model).time():
            try:
                response = await llm.ainvoke(messages, **kwargs)
            except Exception as e:
                llm_calls_total.labels(model=model, outcome="error").inc()
                logger.error(f"LLM call failed: {e}")
                raise
            llm_calls_total.labels(model=model, outcome="ok").inc()
            self._record_token_usage(model, messages, response)
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
