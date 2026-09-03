"""Concrete and legacy framework adapters owned by Composition."""

from .bundle_derivation_repository import SQLAlchemyBundleDerivationRepository
from .config import OwnerConfigFacade, build_owner_config
from .embedding_shadow_repository import SQLAlchemyEmbeddingShadowRepository
from .evidence_bundle_repository import SQLAlchemyCandidateBundleRepository
from .evidence_shadow_repository import SQLAlchemyCanonicalQueryShadowRepository
from .llm import LegacyLLMProviderAdapter, ProviderModelGateway
from .memory_authority import MemoryAuthorityWriter
from .memory_outbox import MemoryOutboxProjector
from .memory_repository import SQLAlchemyMemoryRepository
from .memory_session_projection import (
    SESSION_WINDOW_SIZE,
    SESSION_WINDOW_TTL_SECONDS,
    MemorySessionProjection,
)
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
    LegacySearchResultRepositoryAdapter,
    LegacySessionRepositoryAdapter,
    LegacyUserRepositoryAdapter,
)
from .state import (
    LegacyEventBusAdapter,
    LegacySessionWindowAdapter,
    LegacyStateStoreAdapter,
)
from .travel_output import TravelOutputAdapter
from .travel_tools import TravelPlaceLookupProvider, build_travel_tool_gateway

__all__ = [
    "DisabledPublicEvidenceRepository",
    "SQLAlchemyBundleDerivationRepository",
    "SQLAlchemyCandidateBundleRepository",
    "SQLAlchemyEmbeddingShadowRepository",
    "SQLAlchemyMemoryRepository",
    "MemoryOutboxProjector",
    "MemorySessionProjection",
    "SESSION_WINDOW_SIZE",
    "SESSION_WINDOW_TTL_SECONDS",
    "MemoryAuthorityWriter",
    "SQLAlchemyCanonicalQueryShadowRepository",
    "SQLAlchemyQueryFamilyRepository",
    "LegacyFavoritesRepositoryAdapter",
    "LegacyHistoryRepositoryAdapter",
    "LegacyLLMProviderAdapter",
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
    "TravelOutputAdapter",
    "TravelPlaceLookupProvider",
    "build_travel_tool_gateway",
]
