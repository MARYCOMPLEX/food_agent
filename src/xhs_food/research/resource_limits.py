"""Bounded resource and budget primitives for the in-process research runtime.

These helpers intentionally have no provider knowledge.  A resource pool is
the admission boundary for one capability class; callers still own the source
port and the semantic action that is being executed.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeVar

from pydantic import AliasChoices, Field, field_validator

from xhs_food.contracts import ContractModel, ResourceClass
from xhs_food.contracts.errors import ContractError

T = TypeVar("T")


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ResourcePoolConfig(ContractModel):
    """Immutable settings for one external resource class."""

    resource_class: ResourceClass | str
    max_concurrency: int = Field(default=1, ge=1)
    rate_per_second: float | None = Field(
        default=None,
        validation_alias=AliasChoices("rate_per_second", "rate_limit_per_second"),
        ge=0.0,
    )
    rate_burst: int = Field(default=1, ge=1)
    deadline_seconds: float | None = Field(default=None, gt=0.0)
    max_retries: int = Field(default=0, ge=0)
    retry_backoff_seconds: float = Field(default=0.0, ge=0.0)
    circuit_breaker_threshold: int = Field(default=3, ge=1)
    circuit_breaker_reset_seconds: float = Field(default=30.0, gt=0.0)

    @field_validator("resource_class", mode="before")
    @classmethod
    def normalize_resource_class(cls, value: object) -> object:
        if isinstance(value, ResourceClass):
            return value
        return str(value)


ResourcePoolSettings = ResourcePoolConfig


class RuntimeBudget(ContractModel):
    """Hard run ceilings.  Unset dimensions are intentionally unlimited."""

    max_actions: int | None = Field(default=None, ge=0)
    max_calls: int | None = Field(default=None, ge=0)
    max_tokens: int | None = Field(default=None, ge=0)
    max_duration_seconds: float | None = Field(default=None, gt=0.0)
    deadline_at: datetime | None = None

    @field_validator("deadline_at")
    @classmethod
    def require_aware_deadline(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("runtime deadline_at must be timezone-aware")
        return value


RunBudget = RuntimeBudget
ResearchRuntimeBudget = RuntimeBudget


class BudgetUsage(ContractModel):
    """Serializable snapshot of consumed run budget."""

    actions: int = Field(default=0, ge=0)
    calls: int = Field(default=0, ge=0)
    tokens: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0.0, ge=0.0)


class BudgetExceededError(RuntimeError):
    """Raised before an action/call would exceed a hard run ceiling."""

    def __init__(self, message: str, *, dimension: str = "budget") -> None:
        super().__init__(message)
        self.dimension = dimension


class ResourceCircuitOpenError(RuntimeError):
    """Raised when the affected resource class is circuit-open."""

    def __init__(self, resource_class: str) -> None:
        super().__init__(f"resource circuit is open: {resource_class}")
        self.resource_class = resource_class


class RetryableResourceError(RuntimeError):
    """Convenience exception for source adapters and tests."""

    retryable = True


class ResourceCallTimeoutError(TimeoutError):
    """A resource operation exceeded its configured deadline."""

    retryable = True


class CircuitBreaker:
    """Small failure-count circuit breaker scoped to one resource class."""

    def __init__(
        self,
        failure_threshold: int = 3,
        reset_timeout_seconds: float = 30.0,
        *,
        threshold: int | None = None,
        reset_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        effective_threshold = threshold if threshold is not None else failure_threshold
        effective_reset = reset_seconds if reset_seconds is not None else reset_timeout_seconds
        if effective_threshold < 1:
            raise ValueError("failure_threshold must be at least one")
        if effective_reset <= 0:
            raise ValueError("reset_timeout_seconds must be positive")
        self.failure_threshold = effective_threshold
        self.reset_timeout_seconds = effective_reset
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_probe = False

    @property
    def state(self) -> CircuitState:
        self._refresh()
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failures

    @property
    def is_open(self) -> bool:
        return self.state is CircuitState.OPEN

    def _refresh(self) -> None:
        if (
            self._state is CircuitState.OPEN
            and self._opened_at is not None
            and self._clock() - self._opened_at >= self.reset_timeout_seconds
        ):
            self._state = CircuitState.HALF_OPEN
            self._half_open_probe = False

    def allow_request(self) -> bool:
        """Return whether one request may enter this breaker."""

        self._refresh()
        if self._state is CircuitState.CLOSED:
            return True
        if self._state is CircuitState.OPEN:
            return False
        if self._half_open_probe:
            return False
        self._half_open_probe = True
        return True

    can_execute = allow_request
    allow = allow_request

    def record_success(self) -> None:
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = None
        self._half_open_probe = False

    def record_failure(self, *, retryable: bool = True) -> None:
        # Non-retryable validation/policy errors should not poison a provider
        # circuit; they are local action failures.
        if not retryable:
            return
        self._refresh()
        if self._state is CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            self._opened_at = self._clock()
            self._half_open_probe = False
            return
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = self._clock()

    def record_cancelled(self) -> None:
        """Release a half-open probe when its request is cancelled.

        Cancellation is not a provider failure, so it must not increment the
        failure counter.  It also must not leave the single half-open probe
        occupied forever; the next caller should be allowed to retry it.
        """

        self._refresh()
        if self._state is CircuitState.HALF_OPEN:
            self._half_open_probe = False

    def reset(self) -> None:
        self.record_success()


class BudgetController:
    """Concurrency-safe accounting for total run actions, calls, and tokens."""

    def __init__(
        self,
        budget: RuntimeBudget | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        initial_usage: BudgetUsage | Mapping[str, Any] | None = None,
    ) -> None:
        if budget is None:
            self.budget = RuntimeBudget()
        elif isinstance(budget, RuntimeBudget):
            self.budget = budget
        elif isinstance(budget, Mapping):
            self.budget = RuntimeBudget.model_validate(budget)
        else:
            raise TypeError("budget must be RuntimeBudget, a mapping, or None")
        self._clock = clock
        self._wall_clock = wall_clock
        usage = (
            BudgetUsage.model_validate(initial_usage)
            if initial_usage is not None and not isinstance(initial_usage, BudgetUsage)
            else initial_usage
        )
        if usage is not None and not isinstance(usage, BudgetUsage):
            raise TypeError("initial_usage must be BudgetUsage, a mapping, or None")
        self._started_at = clock() - (usage.elapsed_seconds if usage is not None else 0.0)
        self._actions = usage.actions if usage is not None else 0
        self._calls = usage.calls if usage is not None else 0
        self._tokens = usage.tokens if usage is not None else 0
        self._lock = asyncio.Lock()

    def _elapsed(self) -> float:
        return max(0.0, self._clock() - self._started_at)

    def _deadline_exceeded(self) -> bool:
        deadline = self.budget.deadline_at
        if deadline is not None and self._wall_clock() >= deadline:
            return True
        duration = self.budget.max_duration_seconds
        return duration is not None and self._elapsed() >= duration

    def _check(self, *, actions: int, calls: int, tokens: int) -> None:
        if self._deadline_exceeded():
            raise BudgetExceededError("research run deadline exceeded", dimension="deadline")
        if (
            self.budget.max_actions is not None
            and self._actions + actions > self.budget.max_actions
        ):
            raise BudgetExceededError("research action budget exhausted", dimension="actions")
        if self.budget.max_calls is not None and self._calls + calls > self.budget.max_calls:
            raise BudgetExceededError("research call budget exhausted", dimension="calls")
        if self.budget.max_tokens is not None and self._tokens + tokens > self.budget.max_tokens:
            raise BudgetExceededError("research token budget exhausted", dimension="tokens")

    async def reserve(
        self,
        *,
        actions: int = 0,
        calls: int = 0,
        tokens: int = 0,
    ) -> BudgetUsage:
        if min(actions, calls, tokens) < 0:
            raise ValueError("budget reservations cannot be negative")
        async with self._lock:
            self._check(actions=actions, calls=calls, tokens=tokens)
            self._actions += actions
            self._calls += calls
            self._tokens += tokens
            return self.snapshot()

    async def consume(self, *, actions: int = 0, calls: int = 0, tokens: int = 0) -> BudgetUsage:
        return await self.reserve(actions=actions, calls=calls, tokens=tokens)

    async def reconcile_tokens(
        self,
        *,
        reserved_tokens: int,
        actual_tokens: int,
    ) -> BudgetUsage:
        """Account for tokens observed after an action has executed.

        Reservations are deliberately conservative: a caller never receives a
        refund when the estimate was high.  If the provider reports more
        tokens than reserved, the delta is charged atomically before another
        action can claim the remaining budget.
        """

        if reserved_tokens < 0 or actual_tokens < 0:
            raise ValueError("token reservations cannot be negative")
        delta = max(0, actual_tokens - reserved_tokens)
        if not delta:
            return self.snapshot()
        # The provider has already consumed the tokens by the time this
        # reconciliation runs.  Record the observed usage even when it puts
        # the run over its hard ceiling, then surface the breach to the
        # caller so the result can be marked partial and continuation-aware.
        async with self._lock:
            self._tokens += delta
            maximum = self.budget.max_tokens
            if maximum is not None and self._tokens > maximum:
                raise BudgetExceededError(
                    "research token budget exhausted",
                    dimension="tokens",
                )
            return self.snapshot()

    def snapshot(self) -> BudgetUsage:
        return BudgetUsage(
            actions=self._actions,
            calls=self._calls,
            tokens=self._tokens,
            elapsed_seconds=self._elapsed(),
        )

    def remaining_seconds(self) -> float | None:
        """Return the hard run time remaining across all duration limits."""

        limits: list[float] = []
        if self.budget.max_duration_seconds is not None:
            limits.append(self.budget.max_duration_seconds - self._elapsed())
        if self.budget.deadline_at is not None:
            limits.append((self.budget.deadline_at - self._wall_clock()).total_seconds())
        if not limits:
            return None
        return max(0.0, min(limits))

    @property
    def usage(self) -> BudgetUsage:
        return self.snapshot()


class ResourcePool[T]:
    """Semaphore, rate limiter, deadlines, retries, and circuit breaker."""

    def __init__(
        self,
        config: ResourcePoolConfig | ResourceClass | str | None = None,
        *,
        resource_class: ResourceClass | str | None = None,
        max_concurrency: int | None = None,
        concurrency: int | None = None,
        rate_per_second: float | None = None,
        rate_limit_per_second: float | None = None,
        rate_burst: int | None = None,
        deadline_seconds: float | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        retry_backoff_seconds: float | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        circuit_breaker_threshold: int | None = None,
        circuit_breaker_reset_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(config, ResourcePoolConfig):
            base = config
        else:
            selected_resource = resource_class or config or "default"
            effective_max_concurrency = (
                max_concurrency
                if max_concurrency is not None
                else concurrency
                if concurrency is not None
                else 1
            )
            base = ResourcePoolConfig(
                resource_class=selected_resource,
                max_concurrency=effective_max_concurrency,
                rate_per_second=(
                    rate_per_second
                    if rate_per_second is not None
                    else rate_limit_per_second
                ),
                rate_burst=rate_burst if rate_burst is not None else 1,
                deadline_seconds=(
                    deadline_seconds if deadline_seconds is not None else timeout_seconds
                ),
                max_retries=max_retries if max_retries is not None else 0,
                retry_backoff_seconds=(
                    retry_backoff_seconds
                    if retry_backoff_seconds is not None
                    else 0.0
                ),
                circuit_breaker_threshold=(
                    circuit_breaker_threshold
                    if circuit_breaker_threshold is not None
                    else 3
                ),
                circuit_breaker_reset_seconds=(
                    circuit_breaker_reset_seconds
                    if circuit_breaker_reset_seconds is not None
                    else 30.0
                ),
            )
        self.config = base
        self.resource_class = str(base.resource_class)
        self._semaphore = asyncio.Semaphore(base.max_concurrency)
        self._clock = clock
        self._rate_lock = asyncio.Lock()
        self._rate_events: deque[float] = deque()
        self._circuit = circuit_breaker or CircuitBreaker(
            base.circuit_breaker_threshold,
            base.circuit_breaker_reset_seconds,
            clock=clock,
        )
        self._in_flight = 0
        self._max_in_flight = 0
        self._invocations = 0

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._semaphore

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        return self._circuit

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @property
    def max_in_flight(self) -> int:
        return self._max_in_flight

    @property
    def calls(self) -> int:
        return self._invocations

    async def _wait_for_rate(self) -> None:
        rate = self.config.rate_per_second
        if rate is None or rate <= 0:
            return
        burst = self.config.rate_burst
        while True:
            async with self._rate_lock:
                now = self._clock()
                while self._rate_events and now - self._rate_events[0] >= 1.0:
                    self._rate_events.popleft()
                if len(self._rate_events) < burst:
                    self._rate_events.append(now)
                    return
                wait_for = max(0.0, 1.0 - (now - self._rate_events[0]))
            await asyncio.sleep(wait_for)

    @asynccontextmanager
    async def admission(self) -> AsyncIterator[None]:
        """Admit one attempt and expose queue/in-flight accounting."""

        # Reject an already-open circuit before waiting, but perform the
        # authoritative check again after the semaphore. A waiter may have
        # entered while a sibling failed and opened the circuit; a second
        # check prevents that stale waiter from reaching the provider.
        if self._circuit.state is CircuitState.OPEN:
            raise ResourceCircuitOpenError(self.resource_class)
        await self._wait_for_rate()
        await self._semaphore.acquire()
        admitted = False
        try:
            if not self._circuit.allow_request():
                raise ResourceCircuitOpenError(self.resource_class)
            admitted = True
            self._in_flight += 1
            self._max_in_flight = max(self._max_in_flight, self._in_flight)
            yield
        finally:
            if admitted:
                self._in_flight -= 1
            self._semaphore.release()

    async def _invoke(
        self,
        operation: Callable[..., Awaitable[T]] | Awaitable[T],
        args: tuple[Any, ...],
        kwargs: Mapping[str, Any],
        timeout: float | None,
        attempt_callback: Callable[[], Awaitable[Any] | Any] | None = None,
    ) -> T:
        async with self.admission():
            try:
                # The callback is executed after resource admission.  This
                # keeps a run's call budget atomic with the actual provider
                # attempt and lets cancellation release a half-open probe.
                if attempt_callback is not None:
                    callback_result = attempt_callback()
                    if inspect.isawaitable(callback_result):
                        await callback_result
                self._invocations += 1
                if callable(operation):
                    value = operation(*args, **kwargs)
                else:
                    if args or kwargs:
                        raise TypeError("an awaitable operation cannot receive arguments")
                    value = operation
                if not inspect.isawaitable(value):
                    result = value
                elif timeout is None:
                    result = await value
                else:
                    try:
                        async with asyncio.timeout(timeout):
                            result = await value
                    except TimeoutError as exc:
                        raise ResourceCallTimeoutError(
                            f"resource {self.resource_class} exceeded deadline"
                        ) from exc
            except asyncio.CancelledError:
                self._circuit.record_cancelled()
                raise
            except Exception as exc:
                retryable = _exception_retryable(exc)
                self._circuit.record_failure(retryable=retryable)
                raise
            self._circuit.record_success()
            return result  # type: ignore[return-value]

    async def execute(
        self,
        operation: Callable[..., Awaitable[T]] | Awaitable[T],
        *args: Any,
        timeout: float | None = None,
        deadline_seconds: float | None = None,
        max_retries: int | None = None,
        attempt_callback: Callable[[], Awaitable[Any] | Any] | None = None,
        **kwargs: Any,
    ) -> T:
        """Run an operation with bounded attempts and one total deadline."""

        configured_timeout = (
            timeout
            if timeout is not None
            else deadline_seconds
            if deadline_seconds is not None
            else self.config.deadline_seconds
        )
        retries = self.config.max_retries if max_retries is None else max_retries
        if retries < 0:
            raise ValueError("max_retries cannot be negative")
        # A coroutine object can only be awaited once.  Callers that need
        # retries must pass a callable factory so each attempt gets a fresh
        # awaitable; silently retrying the same coroutine masks the provider
        # error with ``cannot reuse already awaited coroutine``.
        if not callable(operation):
            retries = 0
        started = self._clock()
        for attempt in range(retries + 1):
            remaining = None
            if configured_timeout is not None:
                remaining = configured_timeout - (self._clock() - started)
                if remaining <= 0:
                    raise ResourceCallTimeoutError(
                        f"resource {self.resource_class} exceeded deadline"
                    )
            try:
                if remaining is None:
                    return await self._invoke(
                        operation,
                        args,
                        kwargs,
                        None,
                        attempt_callback,
                    )
                try:
                    async with asyncio.timeout(remaining):
                        return await self._invoke(
                            operation,
                            args,
                            kwargs,
                            remaining,
                            attempt_callback,
                        )
                except TimeoutError as exc:
                    raise ResourceCallTimeoutError(
                        f"resource {self.resource_class} exceeded deadline"
                    ) from exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                retryable = _exception_retryable(exc)
                if not retryable or attempt >= retries:
                    raise
                backoff = self.config.retry_backoff_seconds * (2**attempt)
                if configured_timeout is not None:
                    remaining_after = configured_timeout - (self._clock() - started)
                    if remaining_after <= 0:
                        raise ResourceCallTimeoutError(
                            f"resource {self.resource_class} exceeded deadline"
                        ) from exc
                    backoff = min(backoff, remaining_after)
                if backoff:
                    await asyncio.sleep(backoff)
        raise AssertionError("resource execution loop did not return")

    call = execute
    run = execute


class ResourcePoolSet:
    """Named collection of independent pools shared by a runtime run."""

    def __init__(
        self,
        configs: Mapping[ResourceClass | str, ResourcePoolConfig | ResourcePool] | None = None,
        *,
        default_config: ResourcePoolConfig | None = None,
    ) -> None:
        self._pools: dict[str, ResourcePool[Any]] = {}
        for key, value in (configs or {}).items():
            name = str(key)
            if isinstance(value, ResourcePool):
                self._pools[name] = value
            else:
                self._pools[name] = ResourcePool(
                    value.model_copy(update={"resource_class": name})
                )
        self._default_config = default_config

    def get(self, resource_class: ResourceClass | str) -> ResourcePool[Any]:
        name = str(resource_class)
        if name not in self._pools:
            if self._default_config is None:
                config = ResourcePoolConfig(resource_class=name)
            else:
                config = self._default_config.model_copy(update={"resource_class": name})
            self._pools[name] = ResourcePool(config)
        return self._pools[name]

    pool = get

    def __getitem__(self, resource_class: ResourceClass | str) -> ResourcePool[Any]:
        return self.get(resource_class)

    def __iter__(self) -> Iterator[str]:
        return iter(self._pools)

    @property
    def pools(self) -> Mapping[str, ResourcePool[Any]]:
        return self._pools


ResourcePoolManager = ResourcePoolSet
ResourceLimiter = ResourcePoolSet


class BoundedAsyncQueue[T]:
    """A bounded queue that makes backpressure explicit at the API boundary."""

    def __init__(self, maxsize: int = 1) -> None:
        if maxsize < 1:
            raise ValueError("bounded queue maxsize must be at least one")
        self.maxsize = maxsize
        self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize=maxsize)
        self._closed = False
        self._closed_event = asyncio.Event()

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    def full(self) -> bool:
        return self._queue.full()

    async def put(self, item: T) -> None:
        if self._closed:
            raise QueueClosedError("bounded queue is closed")
        put_task = asyncio.create_task(self._queue.put(item))
        close_task = asyncio.create_task(self._closed_event.wait())
        try:
            done, _ = await asyncio.wait(
                (put_task, close_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if put_task in done:
                # A close racing with a successful put keeps the item
                # available for consumers; close never discards accepted data.
                return
            put_task.cancel()
            await asyncio.gather(put_task, return_exceptions=True)
            raise QueueClosedError("bounded queue is closed")
        except asyncio.CancelledError:
            put_task.cancel()
            await asyncio.gather(put_task, return_exceptions=True)
            raise
        finally:
            if not close_task.done():
                close_task.cancel()
            await asyncio.gather(close_task, return_exceptions=True)

    def put_nowait(self, item: T) -> None:
        if self._closed:
            raise QueueClosedError("bounded queue is closed")
        self._queue.put_nowait(item)

    async def get(self) -> T:
        while True:
            if self._closed and self._queue.empty():
                raise QueueClosedError("bounded queue is closed")
            get_task = asyncio.create_task(self._queue.get())
            close_task = asyncio.create_task(self._closed_event.wait())
            try:
                done, _ = await asyncio.wait(
                    (get_task, close_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if get_task in done:
                    # A consumer may drain items that were accepted before
                    # close; task_done remains the consumer's responsibility.
                    return get_task.result()
                get_task.cancel()
                await asyncio.gather(get_task, return_exceptions=True)
                if self._queue.empty():
                    raise QueueClosedError("bounded queue is closed")
            except asyncio.CancelledError:
                get_task.cancel()
                await asyncio.gather(get_task, return_exceptions=True)
                raise
            finally:
                if not close_task.done():
                    close_task.cancel()
                await asyncio.gather(close_task, return_exceptions=True)

    def get_nowait(self) -> T:
        if self._closed and self._queue.empty():
            raise QueueClosedError("bounded queue is closed")
        return self._queue.get_nowait()

    def task_done(self) -> None:
        self._queue.task_done()

    async def join(self) -> None:
        await self._queue.join()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # Do not enqueue a sentinel: a full queue would make close block, and
        # one sentinel cannot wake multiple consumers.  The close event wakes
        # every waiter while already accepted items remain drainable.
        self._closed_event.set()

    def __aiter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __anext__(self) -> T:
        try:
            return await self.get()
        except QueueClosedError as exc:
            raise StopAsyncIteration from exc


class QueueClosedError(RuntimeError):
    pass


BoundedQueue = BoundedAsyncQueue
BoundedAsyncQueueError = QueueClosedError


def _exception_retryable(exc: BaseException) -> bool:
    if isinstance(exc, ContractError):
        return exc.retryable
    return bool(getattr(exc, "retryable", False)) or isinstance(
        exc,
        (TimeoutError, ConnectionError, OSError),
    )


__all__ = [
    "BoundedAsyncQueue",
    "BoundedAsyncQueueError",
    "BoundedQueue",
    "BudgetController",
    "BudgetExceededError",
    "BudgetUsage",
    "CircuitBreaker",
    "CircuitState",
    "QueueClosedError",
    "ResourceCallTimeoutError",
    "ResourceCircuitOpenError",
    "ResourceLimiter",
    "ResourcePool",
    "ResourcePoolConfig",
    "ResourcePoolManager",
    "ResourcePoolSet",
    "ResourcePoolSettings",
    "ResearchRuntimeBudget",
    "RetryableResourceError",
    "RunBudget",
    "RuntimeBudget",
]
