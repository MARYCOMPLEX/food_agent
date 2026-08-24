"""Project-owned Source and Tool Gateway implementations."""

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
from .source_gateway import InMemorySourceControl, SourceGateway
from .tools import ProviderResult, SchemaToolGateway, ToolRegistration
from .xhs import SourceAdapterError, XHSSourceConnector

__all__ = [
    "AmapPlaceSourceConnector",
    "InMemorySourceControl",
    "LegacySourceProjection",
    "PlaceLookupToolAdapter",
    "ProviderResult",
    "SchemaToolGateway",
    "SourceAdapterError",
    "SourceGateway",
    "SourceOutcome",
    "SourceOutcomeKind",
    "ToolRegistration",
    "XHSSourceConnector",
    "classify_batch",
    "error_from_exception",
    "error_from_provider_code",
    "project_legacy_place",
    "project_legacy_xhs",
    "single_attempt_coverage",
]
