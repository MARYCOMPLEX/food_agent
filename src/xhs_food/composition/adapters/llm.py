"""Legacy LangChain model service behind project-owned provider contracts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from xhs_food.contracts import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    ModelUsage,
)
from xhs_food.foundation.config import ModelConfigView
from xhs_food.services.llm_service import LLMService


class LegacyLLMProviderAdapter:
    """Keep model choice, request options, and exception propagation unchanged."""

    def __init__(self, service: LLMService, config: ModelConfigView) -> None:
        self._service = service
        self._config = config

    @property
    def provider_id(self) -> str:
        host = self._config.base_url.casefold()
        if "siliconflow" in host:
            return "siliconflow"
        if "deepseek" in host:
            return "deepseek"
        if "openai.com" in host:
            return "openai"
        return "openai-compatible"

    async def complete(self, request: ModelRequest) -> ModelResponse:
        messages: list[BaseMessage] = [_legacy_message(message) for message in request.messages]
        call = self._service.call(messages, **request.provider_options)
        response = (
            await asyncio.wait_for(call, request.timeout_ms / 1000)
            if request.timeout_ms is not None
            else await call
        )
        metadata = getattr(response, "response_metadata", {}) or {}
        usage = metadata.get("token_usage", {}) if isinstance(metadata, Mapping) else {}
        tool_calls = tuple(
            ModelToolCall(
                call_id=str(item.get("id") or item.get("call_id") or f"tool-{index}"),
                name=str(item.get("name") or "unknown"),
                arguments=dict(item.get("args") or item.get("arguments") or {}),
            )
            for index, item in enumerate(getattr(response, "tool_calls", ()) or ())
            if isinstance(item, Mapping)
        )
        return ModelResponse(
            request_id=request.request_id,
            content=_content_text(getattr(response, "content", None)),
            tool_calls=tool_calls,
            usage=ModelUsage(
                input_tokens=int(usage.get("prompt_tokens") or 0),
                output_tokens=int(usage.get("completion_tokens") or 0),
            ),
            provider_ref=self.provider_id,
            model_ref=self._config.model,
        )


class ProviderModelGateway:
    def __init__(self, providers: Mapping[str, LegacyLLMProviderAdapter]) -> None:
        if not providers:
            raise ValueError("at least one model-role provider is required")
        self._providers = dict(providers)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        try:
            provider = self._providers[request.model_role]
        except KeyError as exc:
            raise KeyError(f"no provider configured for model role {request.model_role!r}") from exc
        return await provider.complete(request)


def _legacy_message(message: ModelMessage) -> BaseMessage:
    if message.role == "system":
        return SystemMessage(content=message.content)
    if message.role == "assistant":
        return AIMessage(content=message.content)
    if message.role == "tool":
        if not message.tool_call_id:
            raise ValueError("tool messages require tool_call_id")
        return ToolMessage(content=message.content, tool_call_id=message.tool_call_id)
    if message.role == "user":
        return HumanMessage(content=message.content)
    raise ValueError(f"unsupported model message role: {message.role}")


def _content_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


__all__ = ["LegacyLLMProviderAdapter", "ProviderModelGateway"]
