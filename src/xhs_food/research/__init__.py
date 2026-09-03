"""Comment-first Food Research Agent components.

The package is intentionally split by responsibility so the Agent can be
reviewed as a small object graph: MCP session -> source collectors -> insight
analysis -> evidence ledger/profile repository -> response projection.
"""

from .evidence import CanonicalCommentEvidenceAdapter, EvidenceLedger
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
from .sources import (
    AdaptiveQueryPlanner,
    DianpingMcpSource,
    DianpingShopEnricher,
    DianpingSourceAdapterFactory,
    XhsCommentLeadCollector,
    XhsMcpSource,
    XhsSourceAdapterFactory,
)
from .workflow import CommentFirstResearchWorkflow, WorkflowExecution

__all__ = [
    "AdaptiveQueryPlanner",
    "CanonicalCommentEvidenceAdapter",
    "CommentFirstResearchWorkflow",
    "DianpingSourceAdapterFactory",
    "DianpingMcpSource",
    "DianpingShopEnricher",
    "EvidenceLedger",
    "InMemoryShopProfileRepository",
    "ManagedMcpToolSession",
    "ShopProfileRefreshPlan",
    "ShopProfileRefreshPolicy",
    "ShopProfileService",
    "ShopProfileSyncResult",
    "UnavailableMcpToolSession",
    "UserStorageShopProfileRepository",
    "WorkflowExecution",
    "XhsCommentLeadCollector",
    "XhsSourceAdapterFactory",
    "XhsMcpSource",
    "profile_from_storage",
]
