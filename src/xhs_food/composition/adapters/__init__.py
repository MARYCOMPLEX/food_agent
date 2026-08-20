"""Concrete and legacy framework adapters owned by Composition."""

from .config import OwnerConfigFacade, build_owner_config
from .llm import LegacyLLMProviderAdapter, ProviderModelGateway
from .repositories import (
    DisabledPublicEvidenceRepository,
    LegacyFavoritesRepositoryAdapter,
    LegacyHistoryRepositoryAdapter,
    LegacyPlaceCacheRepositoryAdapter,
    LegacySearchResultRepositoryAdapter,
    LegacySessionRepositoryAdapter,
    LegacyUserRepositoryAdapter,
)
from .sources import (
    build_place_source_connector,
    build_place_tool,
    build_xhs_source_connector,
)
from .state import (
    LegacyEventBusAdapter,
    LegacySessionWindowAdapter,
    LegacyStateStoreAdapter,
)

__all__ = [
    "DisabledPublicEvidenceRepository",
    "LegacyFavoritesRepositoryAdapter",
    "LegacyHistoryRepositoryAdapter",
    "LegacyLLMProviderAdapter",
    "LegacyPlaceCacheRepositoryAdapter",
    "LegacyEventBusAdapter",
    "LegacySearchResultRepositoryAdapter",
    "LegacySessionRepositoryAdapter",
    "LegacySessionWindowAdapter",
    "LegacyStateStoreAdapter",
    "LegacyUserRepositoryAdapter",
    "OwnerConfigFacade",
    "ProviderModelGateway",
    "build_owner_config",
    "build_place_source_connector",
    "build_place_tool",
    "build_xhs_source_connector",
]
