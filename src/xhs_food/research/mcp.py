"""One pinned, capability-aware MCP session for a research run."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from xhs_food.contracts import (
    AgentToolCatalogPort,
    AgentToolExecutionContext,
    ContextualToolExecutorPort,
    PlatformChannel,
    SourceCall,
    ToolCall,
)


class ManagedMcpToolSession:
    """Pin the managed catalog once and route all calls through that snapshot.

    A workflow never discovers or calls a remote tool directly.  It asks this
    session for a semantic capability (for example ``notes.search``); the
    session resolves the current policy-approved public tool and translates
    the provider-neutral arguments to the discovered schema.
    """

    def __init__(
        self,
        catalog: AgentToolCatalogPort | None,
        executor: ContextualToolExecutorPort | None,
    ) -> None:
        self._catalog = catalog
        self._executor = executor
        self._context: AgentToolExecutionContext | None = None
        self._snapshot: Any = None
        self._closed = True

    @property
    def snapshot_ref(self) -> str | None:
        return getattr(self._snapshot, "snapshot_ref", None)

    @property
    def snapshot(self) -> Any:
        return self._snapshot

    async def open(self, context: AgentToolExecutionContext) -> None:
        if self._snapshot is not None and not self._closed:
            if self._context == context:
                return
            await self.close()
        self._context = context
        self._closed = False
        if self._catalog is None or self._executor is None:
            return
        self._snapshot = await self._catalog.snapshot(context)

    async def call(
        self,
        platform: PlatformChannel,
        capability: str,
        arguments: Mapping[str, Any],
    ) -> SourceCall:
        if self._closed or self._context is None:
            return _failure(platform.value, capability, "MCP_SESSION_NOT_OPEN")
        if platform not in self._context.platforms:
            return _failure(platform.value, capability, "MCP_PLATFORM_DENIED")
        if self._catalog is None or self._executor is None or self._snapshot is None:
            return _failure(platform.value, capability, "MCP_NOT_CONFIGURED")

        matches = tuple(
            item
            for item in self._snapshot.projection
            if item.platform == platform and item.capability == capability
        )
        if len(matches) == 0:
            return _failure(platform.value, capability, "MCP_CAPABILITY_UNAVAILABLE")
        if len(matches) > 1:
            return _failure(platform.value, capability, "MCP_CAPABILITY_AMBIGUOUS")
        projection = matches[0]
        try:
            definition = next(
                item for item in self._snapshot.tools if item.name == projection.public_name
            )
            translated, argument_metadata = _translate_arguments(
                definition.input_schema, arguments
            )
        except (StopIteration, TypeError, ValueError) as exc:
            return _failure(
                platform.value,
                capability,
                "MCP_ARGUMENT_SCHEMA_UNSUPPORTED",
                message=type(exc).__name__,
            )

        call = ToolCall(
            call_id=f"research:{uuid4().hex}",
            tool_name=definition.name,
            arguments=translated,
            timeout_ms=definition.timeout_ms,
        )
        try:
            result = await self._executor.execute(
                snapshot_ref=self._snapshot.snapshot_ref,
                call=call,
                context=self._context,
            )
        except Exception as exc:  # the session is the source failure boundary
            return _failure(
                platform.value,
                capability,
                "MCP_EXECUTION_FAILED",
                message=type(exc).__name__,
                retryable=True,
            )
        if not result.success:
            error = result.error
            metadata = dict(result.metadata)
            metadata.update(argument_metadata)
            return SourceCall(
                source=platform.value,
                operation=capability,
                success=False,
                error_code=error.code if error else "MCP_TOOL_FAILED",
                error_message=error.message if error else None,
                retryable=bool(error.retryable) if error else False,
                metadata=metadata,
                raw_payload=result.model_dump(mode="json"),
            )
        metadata = dict(result.metadata)
        metadata.update(argument_metadata)
        return SourceCall(
            source=platform.value,
            operation=capability,
            success=True,
            data=result.output,
            metadata=metadata,
            raw_payload=result.model_dump(mode="json"),
        )

    async def close(self) -> None:
        snapshot_ref = self.snapshot_ref
        self._snapshot = None
        self._closed = True
        if snapshot_ref is not None and self._catalog is not None:
            await self._catalog.release(snapshot_ref)

    async def __aenter__(self) -> ManagedMcpToolSession:
        if self._context is None:
            raise RuntimeError("ManagedMcpToolSession.open(context) must be called first")
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


class UnavailableMcpToolSession(ManagedMcpToolSession):
    """Fail-closed session used when no account-service policy is configured."""

    def __init__(self) -> None:
        super().__init__(None, None)

    async def open(self, context: AgentToolExecutionContext) -> None:
        self._context = context
        self._closed = False


def _translate_arguments(
    schema: Mapping[str, Any], arguments: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Map provider-neutral arguments to one discovered schema.

    MCP descriptors are authoritative.  The adapter therefore never sends
    unknown keys, and records every dropped or bounded value in the call
    metadata so an operator can distinguish a provider limit from missing
    evidence.  Numeric bounds are applied only at the transport boundary;
    collectors continue pagination when the provider exposes a cursor.
    """

    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise ValueError("tool schema properties must be an object")
    translated: dict[str, Any] = {}
    used: set[str] = set()
    adjustments: list[dict[str, Any]] = []
    for name, property_schema in properties.items():
        value, source_name = _argument_value(str(name), arguments)
        if value is not _MISSING:
            used.add(source_name)
            # Optional continuation/context arguments are represented as
            # ``None`` by the source port when there is no cursor yet.  Do
            # not send JSON null to a provider schema that declares a string
            # or integer; omission is the contractually correct value.
            if value is None:
                continue
            effective = _apply_numeric_bounds(value, property_schema)
            translated[str(name)] = effective
            if effective != value:
                adjustments.append(
                    {
                        "field": str(name),
                        "requested": value,
                        "effective": effective,
                    }
                )
    required = schema.get("required", ())
    if isinstance(required, (list, tuple)):
        missing = [str(name) for name in required if str(name) not in translated]
        if missing:
            raise ValueError("missing required arguments: " + ",".join(missing))
    dropped = sorted(str(name) for name in arguments if name not in used)
    metadata: dict[str, Any] = {}
    if adjustments:
        metadata["argument_adjustments"] = adjustments
    if dropped:
        metadata["dropped_arguments"] = dropped
    return translated, metadata


_MISSING = object()


def _argument_value(name: str, arguments: Mapping[str, Any]) -> tuple[Any, str]:
    if name in arguments:
        return arguments[name], name
    snake = _snake(name)
    aliases: dict[str, tuple[str, ...]] = {
        "query": ("keyword", "text", "q"),
        "keyword": ("query", "text", "q"),
        "limit": ("count", "max_comments", "page_size", "pageSize"),
        "count": ("limit", "max_comments", "page_size", "pageSize"),
        "maxcomments": ("max_comments", "limit", "count", "page_size", "pageSize"),
        "noteid": ("note_id", "noteId", "id"),
        "shopid": ("shop_id", "shopId", "id", "poi_id"),
        "cityid": ("city_id", "cityId"),
        "city": ("city_name", "cityName", "location", "geo"),
        "page": ("page_no", "pageNo"),
        "cursor": ("next_cursor", "nextCursor"),
        "offset": ("start", "start_index", "page_offset"),
        "timeoutseconds": ("timeout", "timeoutSeconds"),
        "detailurl": ("url", "shop_url", "shopUrl"),
        "reviewfilter": ("filter", "review_type", "reviewType"),
        "sorttype": ("sort", "order"),
    }
    candidates = (snake, name, *aliases.get(snake.replace("_", ""), ()))
    for candidate in candidates:
        if candidate in arguments:
            return arguments[candidate], candidate
    return _MISSING, ""


def _apply_numeric_bounds(value: Any, property_schema: Any) -> Any:
    if not isinstance(property_schema, Mapping):
        return value
    schema_type = property_schema.get("type")
    if schema_type not in {"integer", "number"} or not isinstance(value, (int, float)):
        return value
    effective: int | float = value
    minimum = property_schema.get("minimum")
    maximum = property_schema.get("maximum")
    if isinstance(minimum, (int, float)):
        effective = max(effective, minimum)
    if isinstance(maximum, (int, float)):
        effective = min(effective, maximum)
    if schema_type == "integer":
        return int(effective)
    return effective


def _snake(value: str) -> str:
    output: list[str] = []
    for char in value:
        if char.isupper():
            output.extend(("_", char.lower()))
        else:
            output.append(char)
    return "".join(output).lstrip("_")


def _failure(
    source: str,
    operation: str,
    code: str,
    *,
    message: str | None = None,
    retryable: bool = False,
) -> SourceCall:
    return SourceCall(
        source=source,
        operation=operation,
        success=False,
        error_code=code,
        error_message=message,
        retryable=retryable,
        metadata={"failed_at": datetime.now(UTC).isoformat()},
    )


__all__ = ["ManagedMcpToolSession", "UnavailableMcpToolSession"]
