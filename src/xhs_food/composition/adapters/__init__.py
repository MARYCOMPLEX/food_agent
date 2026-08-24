"""Concrete and legacy framework adapters owned by Composition."""

from .bundle_derivation_repository import SQLAlchemyBundleDerivationRepository
from .config import OwnerConfigFacade, build_owner_config
from .embedding_shadow_repository import SQLAlchemyEmbeddingShadowRepository
from .evidence_bundle_repository import SQLAlchemyCandidateBundleRepository
from .evidence_shadow_repository import SQLAlchemyCanonicalQueryShadowRepository
from .llm import LegacyLLMProviderAdapter, ProviderModelGateway
from .memory_repository import SQLAlchemyMemoryRepository
from .query_family_repository import SQLAlchemyQueryFamilyRepository
from .reliable_events import ReliableTaskEventBusPublisher
from .reliable_task_authority import (
    PostgresReliableTaskAuthority,
    PostgresReliableTaskStore,
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
    "SQLAlchemyBundleDerivationRepository",
    "SQLAlchemyCandidateBundleRepository",
    "SQLAlchemyEmbeddingShadowRepository",
    "SQLAlchemyMemoryRepository",
    "SQLAlchemyCanonicalQueryShadowRepository",
    "SQLAlchemyQueryFamilyRepository",
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
    "PostgresReliableTaskStore",
    "PostgresTaskProgressProjectionStore",
    "ReliableTaskEventBusPublisher",
    "build_owner_config",
    "build_place_source_connector",
    "build_place_tool",
    "build_xhs_source_connector",
]
