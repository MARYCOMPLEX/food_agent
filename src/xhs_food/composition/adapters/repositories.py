"""Legacy persistence facades returning only project-owned JSON payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from xhs_food.contracts import ContractPayload, EvidenceBundle, EvidenceItem
from xhs_food.foundation.base import TargetAdapterDisabled


class LegacySessionRepositoryAdapter:
    def __init__(self, manager: Any) -> None:
        self._manager = manager

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        user_id: str | None = None,
        metadata: ContractPayload | None = None,
    ) -> None:
        if role == "user":
            await self._manager.add_user_message(session_id, content, user_id, metadata)
        elif role == "assistant":
            await self._manager.add_assistant_message(session_id, content, user_id, metadata)
        else:
            raise ValueError("legacy session repository supports user/assistant roles only")

    async def list_messages(
        self, session_id: str, *, limit: int = 20
    ) -> tuple[ContractPayload, ...]:
        return tuple(await self._manager.get_context(session_id, count=limit))

    async def delete_session(self, session_id: str) -> bool:
        await self._manager.clear_session(session_id)
        return True


class LegacyUserRepositoryAdapter:
    _UPDATABLE = frozenset({"name", "username", "email", "location", "settings"})

    def __init__(self, storage: Any) -> None:
        self._storage = storage

    async def get_user(self, user_id: str) -> ContractPayload | None:
        return _payload_or_none(await self._storage.get_user(user_id))

    async def get_or_create_user(self, device_id: str) -> ContractPayload:
        value = _payload_or_none(await self._storage.get_or_create_user(device_id))
        if value is None:
            raise RuntimeError("legacy user storage returned no user")
        return value

    async def update_user(self, user_id: str, changes: ContractPayload) -> ContractPayload | None:
        unexpected = set(changes) - self._UPDATABLE
        if unexpected:
            raise ValueError(f"unsupported user fields: {sorted(unexpected)}")
        return _payload_or_none(await self._storage.update_user(user_id, **changes))


class LegacyHistoryRepositoryAdapter:
    def __init__(self, storage: Any) -> None:
        self._storage = storage

    async def list_history(
        self, user_id: str, *, limit: int = 20, offset: int = 0
    ) -> tuple[ContractPayload, ...]:
        return tuple(
            _payload(item)
            for item in await self._storage.get_history(user_id, limit=limit, offset=offset)
        )

    async def count_history(self, user_id: str) -> int:
        return int(await self._storage.get_history_count(user_id))

    async def add_history(self, user_id: str, item: ContractPayload) -> ContractPayload | None:
        return _payload_or_none(await self._storage.add_history(user_id, **item))

    async def delete_history(self, user_id: str, history_id: int) -> bool:
        return bool(await self._storage.delete_history(user_id, history_id))

    async def clear_history(self, user_id: str) -> int:
        return int(await self._storage.clear_history(user_id))

    async def get_history_by_session(self, session_id: str) -> ContractPayload | None:
        return _payload_or_none(await self._storage.get_history_by_session(session_id))


class LegacyFavoritesRepositoryAdapter:
    def __init__(self, storage: Any) -> None:
        self._storage = storage

    async def list_favorites(self, user_id: str) -> tuple[ContractPayload, ...]:
        return tuple(_payload(item) for item in await self._storage.get_favorites(user_id))

    async def add_favorite(self, user_id: str, restaurant_id: str) -> ContractPayload | None:
        return _payload_or_none(await self._storage.add_favorite(user_id, restaurant_id))

    async def remove_favorite(self, user_id: str, restaurant_id: str) -> bool:
        return bool(await self._storage.remove_favorite(user_id, restaurant_id))

    async def contains_favorite(self, user_id: str, restaurant_id: str) -> bool:
        return bool(await self._storage.check_favorite(user_id, restaurant_id))


class LegacySearchResultRepositoryAdapter:
    def __init__(self, storage: Any) -> None:
        self._storage = storage

    async def save_result(
        self,
        session_id: str,
        result: ContractPayload,
        *,
        turn_id: int | None = None,
    ) -> bool:
        restaurants = result.get("restaurants", [])
        if not isinstance(restaurants, list):
            raise TypeError("search result restaurants must be a JSON array")
        filtered_count = result.get("filtered_count", 0)
        if not isinstance(filtered_count, int) or isinstance(filtered_count, bool):
            raise TypeError("search result filtered_count must be an integer")
        return bool(
            await self._storage.save_search_result(
                session_id,
                restaurants,
                summary=str(result.get("summary", "")),
                filtered_count=filtered_count,
                query=str(result.get("query", "")),
                turn_id=turn_id,
            )
        )

    async def get_result(
        self, session_id: str, *, turn_id: int | None = None
    ) -> ContractPayload | None:
        return _payload_or_none(await self._storage.get_search_result(session_id, turn_id))

    async def list_results(self, session_id: str) -> tuple[ContractPayload, ...]:
        return tuple(
            _payload(item) for item in await self._storage.get_all_search_results(session_id)
        )


class DisabledPublicEvidenceRepository:
    async def get_bundle(self, bundle_id: str) -> EvidenceBundle | None:
        del bundle_id
        raise TargetAdapterDisabled("public-evidence-repository")

    async def get_items(self, evidence_ids: tuple[str, ...]) -> tuple[EvidenceItem, ...]:
        del evidence_ids
        raise TargetAdapterDisabled("public-evidence-repository")

    async def save_candidate(
        self, bundle: EvidenceBundle, items: tuple[EvidenceItem, ...]
    ) -> EvidenceBundle:
        del bundle, items
        raise TargetAdapterDisabled("public-evidence-repository")


def _payload(value: object) -> ContractPayload:
    if hasattr(value, "to_dict"):
        value = value.to_dict()  # type: ignore[union-attr]
    if not isinstance(value, Mapping):
        raise TypeError("legacy repository value is not a JSON object")
    return dict(value)  # type: ignore[return-value]


def _payload_or_none(value: object | None) -> ContractPayload | None:
    return None if value is None else _payload(value)


__all__ = [
    "DisabledPublicEvidenceRepository",
    "LegacyFavoritesRepositoryAdapter",
    "LegacyHistoryRepositoryAdapter",
    "LegacySearchResultRepositoryAdapter",
    "LegacySessionRepositoryAdapter",
    "LegacyUserRepositoryAdapter",
]
