"""Project-owned Source and Tool Gateway implementations."""

from .account_service import (
    AccountServiceClientPort,
    AuthHeaderProvider,
    HttpAccountServiceClient,
    McpAccountServiceClient,
    RemoteAccountServiceError,
)
from .capabilities import (
    CapabilityCollisionError,
    CapabilityMultiplexer,
    CapabilityNotRegisteredError,
    CapabilityRegistration,
    PlatformCapabilityRegistry,
)
from .outcomes import (
    LegacySourceProjection,
    SourceOutcome,
    SourceOutcomeKind,
    classify_batch,
    error_from_exception,
    error_from_provider_code,
    project_legacy_place,
    project_legacy_xhs,
    single_attempt_coverage,
)
from .place import AmapPlaceSourceConnector, PlaceLookupToolAdapter
from .platform_gateway import (
    AccountBoundGateway,
    AccountBoundSourceGateway,
    PlatformConnectorFactory,
    PlatformGatewayCode,
    PlatformGatewayError,
    PlatformSourceGateway,
)
from .platform_sources import (
    DianpingPlatformSourceConnector,
    DianpingProviderPort,
    DianpingSourceConnector,
    PlatformSourceAdapterError,
    ProviderEnvelope,
    SpiderXhsSourceConnector,
    XhsCreatorSourceConnector,
    XhsPcSourceConnector,
    XhsPlatformSourceConnector,
    XhsProviderPort,
)
from .source_gateway import InMemorySourceControl, SourceGateway
from .tools import ProviderResult, SchemaToolGateway, ToolRegistration
from .xhs import SourceAdapterError, XHSSourceConnector

__all__ = [
    "AccountServiceClientPort",
    "AuthHeaderProvider",
    "AmapPlaceSourceConnector",
    "DianpingPlatformSourceConnector",
    "DianpingProviderPort",
    "DianpingSourceConnector",
    "InMemorySourceControl",
    "LegacySourceProjection",
    "PlaceLookupToolAdapter",
    "PlatformSourceAdapterError",
    "ProviderResult",
    "ProviderEnvelope",
    "SchemaToolGateway",
    "SourceAdapterError",
    "SourceGateway",
    "SpiderXhsSourceConnector",
    "SourceOutcome",
    "SourceOutcomeKind",
    "ToolRegistration",
    "XHSSourceConnector",
    "XhsCreatorSourceConnector",
    "XhsPcSourceConnector",
    "XhsPlatformSourceConnector",
    "XhsProviderPort",
    "AccountBoundGateway",
    "AccountBoundSourceGateway",
    "PlatformConnectorFactory",
    "PlatformGatewayCode",
    "PlatformGatewayError",
    "PlatformSourceGateway",
    "HttpAccountServiceClient",
    "McpAccountServiceClient",
    "RemoteAccountServiceError",
    "CapabilityCollisionError",
    "CapabilityMultiplexer",
    "CapabilityNotRegisteredError",
    "CapabilityRegistration",
    "PlatformCapabilityRegistry",
    "classify_batch",
    "error_from_exception",
    "error_from_provider_code",
    "project_legacy_place",
    "project_legacy_xhs",
    "single_attempt_coverage",
]
