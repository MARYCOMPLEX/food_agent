"""Comment-first Food Research Agent components.

The package is intentionally split by responsibility so the Agent can be
reviewed as a small object graph: MCP session -> source collectors -> insight
analysis -> evidence ledger/profile repository -> response projection.
"""

from .aggregation import AggregationResult, EntityControversyAggregator
from .evidence import CanonicalCommentEvidenceAdapter, EvidenceLedger
from .mcp import ManagedMcpToolSession, UnavailableMcpToolSession
from .planner import PlannerDecision, ResearchPlanner
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
from .resource_limits import (
    BoundedAsyncQueue,
    BoundedAsyncQueueError,
    BoundedQueue,
    BudgetController,
    BudgetExceededError,
    BudgetUsage,
    CircuitBreaker,
    CircuitState,
    QueueClosedError,
    ResearchRuntimeBudget,
    ResourceCallTimeoutError,
    ResourceCircuitOpenError,
    ResourceLimiter,
    ResourcePool,
    ResourcePoolConfig,
    ResourcePoolManager,
    ResourcePoolSet,
    ResourcePoolSettings,
    RetryableResourceError,
    RunBudget,
    RuntimeBudget,
)
from .runtime import (
    ActionExecution,
    ActionHandler,
    ResearchRuntime,
    ResearchRuntimeConfig,
    RuntimeConfig,
    RuntimeEventSink,
    RuntimePolicyError,
)
from .sources import (
    AdaptiveQueryPlanner,
    DianpingMcpSource,
    DianpingShopEnricher,
    XhsCommentLeadCollector,
    XhsMcpSource,
)
from .workflow import CommentFirstResearchWorkflow, WorkflowExecution

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
    "CircuitBreaker",
    "CircuitState",
    "CommentFirstResearchWorkflow",
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
