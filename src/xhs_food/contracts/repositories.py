"""Repository contracts for business facts owned outside infrastructure adapters."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self, runtime_checkable

from .base import ContractPayload
from .evidence import EvidenceBundle, EvidenceItem


@runtime_checkable
class SessionRepositoryPort(Protocol):
    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        user_id: str | None = None,
        metadata: ContractPayload | None = None,
    ) -> None: ...

    async def list_messages(
        self, session_id: str, *, limit: int = 20
    ) -> tuple[ContractPayload, ...]: ...

    async def delete_session(self, session_id: str) -> bool: ...


@runtime_checkable
class UserRepositoryPort(Protocol):
    async def get_user(self, user_id: str) -> ContractPayload | None: ...

    async def get_or_create_user(self, device_id: str) -> ContractPayload: ...

    async def update_user(
        self, user_id: str, changes: ContractPayload
    ) -> ContractPayload | None: ...


@runtime_checkable
class HistoryRepositoryPort(Protocol):
    async def list_history(
        self, user_id: str, *, limit: int = 20, offset: int = 0
    ) -> tuple[ContractPayload, ...]: ...

    async def count_history(self, user_id: str) -> int: ...

    async def add_history(self, user_id: str, item: ContractPayload) -> ContractPayload | None: ...

    async def delete_history(self, user_id: str, history_id: int) -> bool: ...

    async def clear_history(self, user_id: str) -> int: ...

    async def get_history_by_session(self, session_id: str) -> ContractPayload | None: ...


@runtime_checkable
class FavoritesRepositoryPort(Protocol):
    async def list_favorites(self, user_id: str) -> tuple[ContractPayload, ...]: ...

    async def add_favorite(self, user_id: str, restaurant_id: str) -> ContractPayload | None: ...

    async def remove_favorite(self, user_id: str, restaurant_id: str) -> bool: ...

    async def contains_favorite(self, user_id: str, restaurant_id: str) -> bool: ...


@runtime_checkable
class SearchResultRepositoryPort(Protocol):
    async def save_result(
        self,
        session_id: str,
        result: ContractPayload,
        *,
        turn_id: int | None = None,
    ) -> bool: ...

    async def get_result(
        self, session_id: str, *, turn_id: int | None = None
    ) -> ContractPayload | None: ...

    async def list_results(self, session_id: str) -> tuple[ContractPayload, ...]: ...


@runtime_checkable
class PlaceCacheRepositoryPort(Protocol):
    """Read the optional legacy place cache without exposing its storage driver."""

    async def get_cached_place_by_name(self, name: str) -> ContractPayload | None: ...


@runtime_checkable
class PublicEvidenceRepositoryPort(Protocol):
    async def get_bundle(self, bundle_id: str) -> EvidenceBundle | None: ...

    async def get_items(self, evidence_ids: tuple[str, ...]) -> tuple[EvidenceItem, ...]: ...

    async def save_candidate(
        self, bundle: EvidenceBundle, items: tuple[EvidenceItem, ...]
    ) -> EvidenceBundle: ...


@runtime_checkable
class RepositoryUnitOfWork(Protocol):
    """One use-case transaction; adapters keep driver sessions private."""

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


__all__ = [
    "FavoritesRepositoryPort",
    "HistoryRepositoryPort",
    "PlaceCacheRepositoryPort",
    "PublicEvidenceRepositoryPort",
    "RepositoryUnitOfWork",
    "SearchResultRepositoryPort",
    "SessionRepositoryPort",
    "UserRepositoryPort",
]
