"""Schema-validating Tool Gateway with legacy result compatibility."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from pydantic import JsonValue, TypeAdapter, ValidationError

from xhs_food.contracts import (
    AllowedToolContract,
    ContractError,
    ErrorCategory,
    ErrorScope,
    ToolCall,
    ToolResult,
)


class ToolProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def execute(self, **kwargs: Any) -> object: ...

    async def health_check(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class ProviderResult:
    success: bool
    data: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolRegistration:
    contract: AllowedToolContract
    provider: ToolProvider
    max_calls_per_task: int = 32

    def __post_init__(self) -> None:
        if self.provider.name != self.contract.tool_id:
            raise ValueError("provider name must match the tool contract id")
        if self.max_calls_per_task < 1:
            raise ValueError("max_calls_per_task must be positive")


class SchemaToolGateway:
    """The only dispatch path exposed to target Agent adapters."""

    def __init__(
        self,
        registrations: tuple[ToolRegistration, ...],
        *,
        allowed_tools: frozenset[str] | None = None,
    ) -> None:
        self._registrations = {item.contract.tool_id: item for item in registrations}
        if len(self._registrations) != len(registrations):
            raise ValueError("duplicate tool registration")
        self._allowed_tools = (
            frozenset(self._registrations) if allowed_tools is None else allowed_tools
        )
        if not self._allowed_tools.issubset(self._registrations):
            raise ValueError("allow-list contains an unregistered tool")
        self._calls: dict[tuple[str, str], int] = {}
        self._budget_lock = asyncio.Lock()

    async def execute(self, call: ToolCall) -> ToolResult:
        registration = self._registrations.get(call.tool_name)
        if registration is None:
            return _failure(
                call,
                code="TOOL_NOT_FOUND",
                category=ErrorCategory.NOT_FOUND,
            )
        if call.tool_name not in self._allowed_tools:
            return _failure(
                call,
                code="TOOL_POLICY_DENIED",
                category=ErrorCategory.POLICY_DENIED,
            )
        try:
            registration.contract.validate_input(call.arguments)
        except (ValueError, ValidationError) as exc:
            return _failure(
                call,
                code="TOOL_INPUT_INVALID",
                category=ErrorCategory.VALIDATION,
                message=str(exc),
            )
        if not await self._consume_budget(call, registration):
            return _failure(
                call,
                code="TOOL_BUDGET_EXHAUSTED",
                category=ErrorCategory.BUDGET_EXHAUSTED,
            )

        timeout = (call.timeout_ms or registration.contract.timeout_ms) / 1000
        try:
            raw = await asyncio.wait_for(
                registration.provider.execute(**call.arguments), timeout=timeout
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = _tool_error_from_exception(exc, boundary_ref=call.tool_name)
            return ToolResult(call_id=call.call_id, success=False, error=error)

        try:
            result = _coerce_provider_result(raw, call)
        except ValueError as exc:
            return _failure(
                call,
                code="TOOL_RESULT_ENVELOPE_INVALID",
                category=ErrorCategory.MALFORMED_RESPONSE,
                message=str(exc),
            )
        if not result.success:
            try:
                metadata = _json_mapping(result.metadata)
            except (TypeError, ValueError, ValidationError) as exc:
                return _failure(
                    call,
                    code="TOOL_METADATA_INVALID",
                    category=ErrorCategory.MALFORMED_RESPONSE,
                    message=str(exc),
                )
            return ToolResult(
                call_id=call.call_id,
                success=False,
                error=_tool_error_from_provider_code(
                    result.error_code,
                    boundary_ref=call.tool_name,
                    message=result.error_message,
                ),
                metadata=metadata,
            )
        try:
            output = _json_value(result.data)
            registration.contract.validate_output(output)
        except (TypeError, ValueError, ValidationError) as exc:
            return _failure(
                call,
                code="TOOL_OUTPUT_INVALID",
                category=ErrorCategory.MALFORMED_RESPONSE,
                message=str(exc),
            )
        try:
            metadata = _json_mapping(result.metadata)
        except (TypeError, ValueError, ValidationError) as exc:
            return _failure(
                call,
                code="TOOL_METADATA_INVALID",
                category=ErrorCategory.MALFORMED_RESPONSE,
                message=str(exc),
            )
        return ToolResult(
            call_id=call.call_id,
            success=True,
            output=output,
            metadata=metadata,
        )

    async def health(self, tool_name: str) -> bool:
        registration = self._registrations.get(tool_name)
        if registration is None or tool_name not in self._allowed_tools:
            return False
        try:
            return bool(await registration.provider.health_check())
        except Exception:
            return False

    async def _consume_budget(self, call: ToolCall, registration: ToolRegistration) -> bool:
        identity = (call.task_id or call.call_id, call.tool_name)
        async with self._budget_lock:
            used = self._calls.get(identity, 0)
            if used >= registration.max_calls_per_task:
                return False
            self._calls[identity] = used + 1
            return True


def _coerce_provider_result(raw: object, call: ToolCall) -> ProviderResult:
    if isinstance(raw, ProviderResult):
        return raw
    try:
        value = cast(Any, raw)
        return ProviderResult(
            success=bool(value.success),
            data=value.data,
            error_code=value.error_code,
            error_message=value.error_message,
            metadata=dict(value.metadata or {}),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"tool {call.tool_name!r} returned an invalid result envelope") from exc


def _json_value(value: object) -> JsonValue:
    return TypeAdapter(JsonValue).validate_python(value)


def _json_mapping(value: object) -> dict[str, JsonValue]:
    result = _json_value(value)
    if not isinstance(result, dict):
        raise ValueError("tool metadata must be a JSON object")
    return result


def _tool_error_from_exception(exc: BaseException, *, boundary_ref: str) -> ContractError:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ContractError(
            code="TOOL_TIMEOUT",
            category=ErrorCategory.TIMEOUT,
            scope=ErrorScope.TOOL,
            boundary_ref=boundary_ref,
            retryable=True,
        )
    return ContractError(
        code="PROVIDER_INTERNAL",
        category=ErrorCategory.INTERNAL,
        scope=ErrorScope.PROVIDER,
        boundary_ref=boundary_ref,
        retryable=False,
        message=str(exc) or None,
    )


def _tool_error_from_provider_code(
    code: str | None,
    *,
    boundary_ref: str,
    message: str | None = None,
) -> ContractError:
    normalized = (code or "DEPENDENCY_UNAVAILABLE").upper()
    if normalized in {"TOOL_TIMEOUT", "SOURCE_TIMEOUT", "TIMEOUT"}:
        category, retryable = ErrorCategory.TIMEOUT, True
    elif normalized in {"RATE_LIMITED", "RATE_LIMIT", "HTTP_429"}:
        category, retryable = ErrorCategory.RATE_LIMITED, True
    elif normalized in {"MALFORMED_RESPONSE", "INVALID_RESPONSE"}:
        category, retryable = ErrorCategory.MALFORMED_RESPONSE, False
    elif normalized in {
        "SEARCH_FAILED",
        "NOTE_FETCH_FAILED",
        "BATCH_FAILED",
        "DEPENDENCY_UNAVAILABLE",
    }:
        category, retryable = ErrorCategory.DEPENDENCY_UNAVAILABLE, True
    else:
        category, retryable = ErrorCategory.INTERNAL, False
    return ContractError(
        code=normalized,
        category=category,
        scope=ErrorScope.PROVIDER,
        boundary_ref=boundary_ref,
        retryable=retryable,
        message=message,
    )


def _failure(
    call: ToolCall,
    *,
    code: str,
    category: ErrorCategory,
    message: str | None = None,
) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        success=False,
        error=ContractError(
            code=code,
            category=category,
            scope=ErrorScope.TOOL,
            retryable=False,
            message=message,
            boundary_ref=call.tool_name,
        ),
    )


__all__ = [
    "ProviderResult",
    "SchemaToolGateway",
    "ToolProvider",
    "ToolRegistration",
]
