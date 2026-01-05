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
        try:
            response = await llm.ainvoke(messages, **kwargs)
            return response
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise
    
    def get_llm(self) -> ChatOpenAI:
        """获取底层 LLM 实例."""
        return self._get_llm()
