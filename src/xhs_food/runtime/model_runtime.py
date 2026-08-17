"""Local adapter around OpenAI Agents SDK.

No API route imports Agents SDK classes directly.  This module is the only
place that knows the tested ResponsesModel construction for the configured
OpenAI-compatible provider.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol


class AgentRuntime(Protocol):
    async def run_structured(
        self,
        *,
        name: str,
        instructions: str,
        input_text: str,
        output_type: type[Any],
        tools: Sequence[Any] = (),
    ) -> Any:
        ...

    async def stream(
        self,
        *,
        name: str,
        instructions: str,
        input_text: str,
        tools: Sequence[Any] = (),
    ) -> AsyncIterator[Any]:
        ...


class OpenAIAgentsRuntime:
    """Agents SDK adapter for Responses + Pydantic structured output."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._base_url = base_url or os.getenv(
            "OPENAI_API_BASE", "https://tokenrhythm.studio/v1"
        )
        self._model_name = model or os.getenv(
            "DEFAULT_LLM_MODEL", "deepseek-v4-flash-0731"
        )
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAIAgentsRuntime")
        try:
            from agents.models.openai_responses import OpenAIResponsesModel
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError(
                "openai-agents and openai are required for OpenAIAgentsRuntime"
            ) from exc

        client = AsyncOpenAI(base_url=self._base_url, api_key=self._api_key)
        self._model = OpenAIResponsesModel(
            model=self._model_name,
            openai_client=client,
        )
        return self._model

    async def run_structured(
        self,
        *,
        name: str,
        instructions: str,
        input_text: str,
        output_type: type[Any],
        tools: Sequence[Any] = (),
    ) -> Any:
        try:
            from agents import Agent, RunConfig, Runner
        except ImportError as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError("openai-agents is not installed") from exc

        agent = Agent(
            name=name,
            instructions=instructions,
            model=self._get_model(),
            output_type=output_type,
            tools=list(tools),
        )
        result = await Runner.run(
            agent,
            input=input_text,
            run_config=RunConfig(tracing_disabled=True),
        )
        return result.final_output

    async def stream(
        self,
        *,
        name: str,
        instructions: str,
        input_text: str,
        tools: Sequence[Any] = (),
    ) -> AsyncIterator[Any]:
        try:
            from agents import Agent, RunConfig, Runner
        except ImportError as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError("openai-agents is not installed") from exc

        agent = Agent(
            name=name,
            instructions=instructions,
            model=self._get_model(),
            tools=list(tools),
        )
        result = Runner.run_streamed(
            agent,
            input=input_text,
            run_config=RunConfig(tracing_disabled=True),
        )
        async for event in result.stream_events():
            yield event
