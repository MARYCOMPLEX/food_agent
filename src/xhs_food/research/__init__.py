"""Research boundaries for the production Food Agent.

The adaptive package is the only production planning/runtime route.  The
pre-adaptive modules are kept as an explicit import-only quarantine for
already persisted jobs and migration tooling; importing this package never
loads them.  This is important because the legacy modules depend on provider
specific collectors and the old fixed workflow.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .workflow import CommentFirstResearchWorkflow, WorkflowExecution

from .adaptive import (
    AdaptiveCritic,
    AdaptivePlanner,
    InvestigationLoop,
)
from .adaptive.food_workflow import (
    AdaptiveFoodResearchWorkflow,
    AdaptiveWorkflowExecution,
    ManagedMcpToolPort,
)
from .aggregation import AggregationResult, EntityControversyAggregator
from .evidence import (
    CanonicalCommentEvidenceAdapter,
    EvidenceLedger,
    build_query_reuse_read_service,
)
from .mcp import ManagedMcpToolSession, UnavailableMcpToolSession
from .profile_service import (
    ShopProfileRefreshPlan,
    ShopProfileRefreshPolicy,
    ShopProfileService,
    ShopProfileSyncResult,
)
from .repository import (
    InMemoryShopProfileRepository,
    UserStorageShopProfileRepository,
    profile_from_storage,
)

_LEGACY_EXPORT_MODULES = {
    "CommentFirstResearchWorkflow": ".workflow",
    "WorkflowExecution": ".workflow",
    # Fixed planner and source collectors are intentionally lazy.  They are
    # not imported by the adaptive route and cannot accidentally become a
    # second planning authority through package-level re-exports.
    "PlannerDecision": ".planner",
    "ResearchPlanner": ".planner",
    "AdaptiveQueryPlanner": ".sources",
    "DianpingMcpSource": ".sources",
    "DianpingShopEnricher": ".sources",
    "XhsCommentLeadCollector": ".sources",
    "XhsMcpSource": ".sources",
    # Resource/runtime names below are historical consumers.  New code must
    # use research.adaptive.{ActionScheduler,InvestigationLoop,...}.
    "BoundedAsyncQueue": ".resource_limits",
    "BoundedAsyncQueueError": ".resource_limits",
    "BoundedQueue": ".resource_limits",
    "BudgetController": ".resource_limits",
    "BudgetExceededError": ".resource_limits",
    "BudgetUsage": ".resource_limits",
    "CircuitBreaker": ".resource_limits",
    "CircuitState": ".resource_limits",
    "QueueClosedError": ".resource_limits",
    "ResearchRuntimeBudget": ".resource_limits",
    "ResourceCallTimeoutError": ".resource_limits",
    "ResourceCircuitOpenError": ".resource_limits",
    "ResourceLimiter": ".resource_limits",
    "ResourcePool": ".resource_limits",
    "ResourcePoolConfig": ".resource_limits",
    "ResourcePoolManager": ".resource_limits",
    "ResourcePoolSet": ".resource_limits",
    "ResourcePoolSettings": ".resource_limits",
    "RetryableResourceError": ".resource_limits",
    "RunBudget": ".resource_limits",
    "RuntimeBudget": ".resource_limits",
    "ActionExecution": ".runtime",
    "ActionHandler": ".runtime",
    "ResearchRuntime": ".runtime",
    "ResearchRuntimeConfig": ".runtime",
    "RuntimeConfig": ".runtime",
    "RuntimeEventSink": ".runtime",
    "RuntimePolicyError": ".runtime",
}


def __getattr__(name: str) -> Any:
    """Load deterministic compatibility exports only when explicitly used."""

    module_name = _LEGACY_EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

__all__ = [
    "AggregationResult",
    "ActionExecution",
    "ActionHandler",
    "AdaptiveQueryPlanner",
    "BoundedAsyncQueue",
    "BoundedAsyncQueueError",
    "BoundedQueue",
    "BudgetController",
    "BudgetExceededError",
    "BudgetUsage",
    "CanonicalCommentEvidenceAdapter",
    "build_query_reuse_read_service",
    "CircuitBreaker",
    "CircuitState",
    "CommentFirstResearchWorkflow",
    "AdaptiveCritic",
    "AdaptivePlanner",
    "AdaptiveFoodResearchWorkflow",
    "AdaptiveWorkflowExecution",
    "InvestigationLoop",
    "ManagedMcpToolPort",
    "EntityControversyAggregator",
    "DianpingMcpSource",
    "DianpingShopEnricher",
    "EvidenceLedger",
    "InMemoryShopProfileRepository",
    "ManagedMcpToolSession",
    "QueueClosedError",
    "ResourceCallTimeoutError",
    "ResourceCircuitOpenError",
    "ResourceLimiter",
    "ResourcePool",
    "ResourcePoolConfig",
    "ResourcePoolManager",
    "ResourcePoolSet",
    "ResourcePoolSettings",
    "ResearchRuntime",
    "ResearchRuntimeConfig",
    "ResearchRuntimeBudget",
    "RetryableResourceError",
    "RunBudget",
    "RuntimeBudget",
    "RuntimeConfig",
    "RuntimeEventSink",
    "RuntimePolicyError",
    "PlannerDecision",
    "ResearchPlanner",
    "ShopProfileRefreshPlan",
    "ShopProfileRefreshPolicy",
    "ShopProfileService",
    "ShopProfileSyncResult",
    "UnavailableMcpToolSession",
    "UserStorageShopProfileRepository",
    "WorkflowExecution",
    "XhsCommentLeadCollector",
    "XhsMcpSource",
    "profile_from_storage",
]
