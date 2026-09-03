"""Project-owned Source and Tool Gateway implementations."""

from .account_service import (
    AccountServiceClientPort,
    AuthHeaderProvider,
    HttpAccountServiceClient,
    McpAccountServiceClient,
    RemoteAccountServiceError,
)
from .outcomes import (
    LegacySourceProjection,
    SourceOutcome,
    SourceOutcomeKind,
    classify_batch,
    error_from_exception,
    error_from_provider_code,
    project_legacy_place,
    single_attempt_coverage,
)
from .source_gateway import InMemorySourceControl, SourceGateway
from .tools import ProviderResult, SchemaToolGateway, ToolRegistration

__all__ = [
    "AccountServiceClientPort",
    "AuthHeaderProvider",
    "InMemorySourceControl",
    "LegacySourceProjection",
    "ProviderResult",
    "SchemaToolGateway",
    "SourceGateway",
    "SourceOutcome",
    "SourceOutcomeKind",
    "ToolRegistration",
    "HttpAccountServiceClient",
    "McpAccountServiceClient",
    "RemoteAccountServiceError",
    "classify_batch",
    "error_from_exception",
    "error_from_provider_code",
    "project_legacy_place",
    "single_attempt_coverage",
]
