"""Food-search adapter over the policy-controlled Agent MCP catalog."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from xhs_food.contracts import (
    AgentToolCatalogPort,
    AgentToolExecutionContext,
    ContextualToolExecutorPort,
    PlatformChannel,
    ToolCall,
)

_SEARCH_CONTEXT: ContextVar[AgentToolExecutionContext | None] = ContextVar(
    "managed_search_context",
    default=None,
)


@dataclass(frozen=True, slots=True)
class ManagedSearchResult:
    success: bool
    data: Mapping[str, Any] | None = None
    error_message: str | None = None


@contextmanager
def bind_managed_search_context(
    context: AgentToolExecutionContext,
) -> Iterator[None]:
    """Bind opaque search authority to the current async request task."""

    token = _SEARCH_CONTEXT.set(context)
    try:
        yield
    finally:
        _SEARCH_CONTEXT.reset(token)


class ManagedMcpSearchTool:
    """Select and call one approved notes.search tool from a pinned snapshot."""

    def __init__(
        self,
        catalog: AgentToolCatalogPort,
        executor: ContextualToolExecutorPort,
        *,
        platform: PlatformChannel = PlatformChannel.XHS_PC,
        capability: str = "notes.search",
    ) -> None:
        self._catalog = catalog
        self._executor = executor
        self._platform = platform
        self._capability = capability

    async def execute(
        self,
        *,
        keyword: str,
        count: int,
        sort_type: str,
        include_details: bool,
        include_comments: bool,
    ) -> ManagedSearchResult:
        context = _SEARCH_CONTEXT.get()
        if context is None:
            return _failure("MANAGED_SEARCH_CONTEXT_MISSING")
        if self._platform not in context.platforms:
            return _failure("MANAGED_SEARCH_PLATFORM_DENIED")

        snapshot_ref: str | None = None
        try:
            snapshot = await self._catalog.snapshot(context)
            snapshot_ref = snapshot.snapshot_ref
            matches = tuple(
                item
                for item in snapshot.projection
                if item.platform is self._platform and item.capability == self._capability
            )
            if len(matches) != 1:
                return _failure(
                    "MANAGED_SEARCH_TOOL_UNAVAILABLE"
                    if not matches
                    else "MANAGED_SEARCH_TOOL_AMBIGUOUS"
                )
            projection = matches[0]
            definition = next(
                item for item in snapshot.tools if item.name == projection.public_name
            )
            arguments = _search_arguments(
                definition.input_schema,
                keyword=keyword,
                count=count,
                sort_type=sort_type,
                include_details=include_details,
                include_comments=include_comments,
            )
            result = await self._executor.execute(
                snapshot_ref=snapshot.snapshot_ref,
                call=ToolCall(
                    call_id=f"managed-search:{uuid4().hex}",
                    tool_name=definition.name,
                    arguments=arguments,
                ),
                context=context,
            )
            if not result.success:
                code = result.error.code if result.error is not None else "MANAGED_SEARCH_FAILED"
                return _failure(code)
            if not isinstance(result.output, Mapping):
                return _failure("MANAGED_SEARCH_OUTPUT_INVALID")
            notes = result.output.get("notes")
            if not isinstance(notes, list):
                return _failure("MANAGED_SEARCH_OUTPUT_INVALID")
            return ManagedSearchResult(success=True, data=dict(result.output))
        except (StopIteration, TypeError, ValueError):
            return _failure("MANAGED_SEARCH_SCHEMA_UNSUPPORTED")
        except Exception:
            return _failure("MANAGED_SEARCH_DEPENDENCY_UNAVAILABLE")
        finally:
            if snapshot_ref is not None:
                await self._catalog.release(snapshot_ref)

    async def health(self) -> bool:
        context = _SEARCH_CONTEXT.get()
        if context is None or self._platform not in context.platforms:
            return False
        snapshot_ref: str | None = None
        try:
            snapshot = await self._catalog.snapshot(context)
            snapshot_ref = snapshot.snapshot_ref
            matches = tuple(
                item
                for item in snapshot.projection
                if item.platform is self._platform and item.capability == self._capability
            )
            return len(matches) == 1 and await self._executor.health(
                snapshot_ref=snapshot.snapshot_ref,
                tool_name=matches[0].public_name,
            )
        except Exception:
            return False
        finally:
            if snapshot_ref is not None:
                await self._catalog.release(snapshot_ref)


class UnavailableManagedSearchTool:
    """Fail-closed binding used when managed MCP configuration is absent."""

    async def execute(self, **arguments: Any) -> ManagedSearchResult:
        del arguments
        return _failure("MANAGED_SEARCH_NOT_CONFIGURED")

    async def health(self) -> bool:
        return False


def _search_arguments(
    schema: Mapping[str, Any],
    *,
    keyword: str,
    count: int,
    sort_type: str,
    include_details: bool,
    include_comments: bool,
) -> dict[str, Any]:
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise ValueError("managed search input properties must be an object")
    values: dict[str, Any] = {
        "keyword": keyword,
        "query": keyword,
        "count": count,
        "limit": count,
        "sort_type": sort_type,
        "sort": sort_type,
        "include_details": include_details,
        "include_comments": include_comments,
    }
    arguments = {name: values[name] for name in properties if name in values}
    required = schema.get("required", ())
    if isinstance(required, list) and any(name not in arguments for name in required):
        raise ValueError("managed search schema contains unsupported required fields")
    if "keyword" not in arguments and "query" not in arguments:
        raise ValueError("managed search schema must accept keyword or query")
    return arguments


def _failure(code: str) -> ManagedSearchResult:
    return ManagedSearchResult(success=False, error_message=code)


__all__ = [
    "ManagedMcpSearchTool",
    "ManagedSearchResult",
    "UnavailableManagedSearchTool",
    "bind_managed_search_context",
]
