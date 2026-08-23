"""Concrete and legacy framework adapters owned by Composition."""

from .config import OwnerConfigFacade, build_owner_config
from .evidence_bundle_repository import SQLAlchemyCandidateBundleRepository
from .evidence_shadow_repository import SQLAlchemyCanonicalQueryShadowRepository
from .llm import LegacyLLMProviderAdapter, ProviderModelGateway
from .reliable_task_authority import (
    PostgresReliableTaskAuthority,
    PostgresTaskProgressProjectionStore,
)
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
    "SQLAlchemyCandidateBundleRepository",
    "SQLAlchemyCanonicalQueryShadowRepository",
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
    "PostgresReliableTaskAuthority",
    "PostgresTaskProgressProjectionStore",
    "build_owner_config",
    "build_place_source_connector",
    "build_place_tool",
    "build_xhs_source_connector",
]
