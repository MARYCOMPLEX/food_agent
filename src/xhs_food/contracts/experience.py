"""Experience-boundary commands, snapshots, and use-case ports."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import ConfigDict, Field

from .base import ContractModel, ContractPayload, NonEmptyStr, VersionedContract
from .tasks import ResearchOperation, ResearchRequest, ResearchTask


class ResearchTaskNotFoundError(LookupError):
    """The requested legacy research session has no recoverable task state."""


class ContextMessage(ContractModel):
    """A transport-neutral conversation entry used by context restoration."""

    model_config = ConfigDict(str_strip_whitespace=False)

    role: NonEmptyStr
    content: str


class RecommendationSnapshot(ContractModel):
    """A named result item preserving legacy insertion order and key identity."""

    model_config = ConfigDict(str_strip_whitespace=False)

    key: NonEmptyStr
    payload: ContractPayload = Field(default_factory=dict)


class ResearchContextSnapshot(VersionedContract):
    """Detached context projection needed by compatibility adapters."""

    model_config = ConfigDict(str_strip_whitespace=False)

    messages: tuple[ContextMessage, ...] = ()
    recommendations: tuple[RecommendationSnapshot, ...] = ()
    last_summary: str = ""
    last_intent: ContractPayload | None = None
    excluded_shops: tuple[str, ...] = ()
    accumulated_preferences: tuple[str, ...] = ()
    turn_count: int = 0
    last_notes: tuple[ContractPayload, ...] = ()
    target_city: str = ""


class ResearchResultSnapshot(VersionedContract):
    """Internal result projection kept distinct from each legacy output view."""

    model_config = ConfigDict(str_strip_whitespace=False)

    recommendations: tuple[RecommendationSnapshot, ...] = ()
    presentation_items: tuple[ContractPayload, ...] = ()
    summary: str = ""
    filtered_count: int = 0
    total_count: int | None = Field(default=None, ge=0)


class ResearchTaskAdmission(VersionedContract):
    """Accepted task identity returned before a legacy background run starts."""

    task_id: NonEmptyStr
    session_id: NonEmptyStr
    operation: ResearchOperation
    stream_ref: NonEmptyStr
    turn_id: int = Field(ge=1)


@runtime_checkable
class ResearchTaskPort(Protocol):
    """Single use-case boundary consumed by the current search routes."""

    async def start_new(self, query: str) -> ResearchTaskAdmission: ...

    async def refine(self, session_id: str, query: str) -> ResearchTaskAdmission: ...

    async def recover(self, session_id: str) -> ContractPayload: ...

    async def status(self, session_id: str) -> ContractPayload | None: ...

    async def results(self, session_id: str) -> ContractPayload | None: ...


@runtime_checkable
class ExplicitRefreshUseCase(Protocol):
    """Unbound S2 extension point; B2 supplies authorization and execution."""

    async def submit(self, request: ResearchRequest) -> ResearchTask: ...


@runtime_checkable
class StableResultMapperPort(Protocol):
    """Field-aware mapper for legacy HTTP, SSE, and persistence views."""

    def to_http_results(self, session_id: str, state: ContractPayload) -> ContractPayload: ...

    def to_completed_recovery(
        self, session_id: str, records: tuple[ContractPayload, ...]
    ) -> ContractPayload: ...

    def to_sse_restaurant(self, item: ContractPayload) -> ContractPayload: ...

    def to_sse_result(
        self,
        snapshot: ResearchResultSnapshot,
        steps: tuple[ContractPayload, ...],
    ) -> ContractPayload: ...

    def to_persisted_restaurant(
        self, item: ContractPayload, restaurant_id: str
    ) -> ContractPayload: ...


__all__ = [
    "ContextMessage",
    "ExplicitRefreshUseCase",
    "RecommendationSnapshot",
    "ResearchContextSnapshot",
    "ResearchResultSnapshot",
    "ResearchTaskAdmission",
    "ResearchTaskNotFoundError",
    "ResearchTaskPort",
    "StableResultMapperPort",
]
