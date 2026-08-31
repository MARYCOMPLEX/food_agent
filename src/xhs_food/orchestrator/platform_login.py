"""Compatibility exports for the account-auth Temporal boundary.

The executable workflow and Activity implementation live in the foundation
runtime module so infrastructure ownership stays explicit.  This legacy
module intentionally performs only a lazy compatibility lookup and imports no
Temporal SDK symbols itself.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_TARGET_MODULE = "xhs_food.foundation.platform_login_temporal"

# Annotations keep static export checks aware of the lazy compatibility
# surface without binding SDK-backed objects in the orchestrator package.
ACCOUNT_AUTH_CANCEL_ACTIVITY: Any
ACCOUNT_AUTH_CANCEL_SIGNAL: Any
ACCOUNT_AUTH_COOKIE_IMPORT_ACTIVITY: Any
ACCOUNT_AUTH_CREATE_QR_ACTIVITY: Any
ACCOUNT_AUTH_POLL_ACTIVITY: Any
ACCOUNT_AUTH_PHONE_LOGIN_ACTIVITY: Any
ACCOUNT_AUTH_TASK_QUEUE: Any
ACCOUNT_AUTH_WORKFLOW_TYPE: Any
PlatformLoginTemporalActivities: Any
TemporalAccountAuthWorkflow: Any
account_auth_activity_config: Any
build_account_auth_workflow_start: Any

__all__ = [
    "ACCOUNT_AUTH_CANCEL_ACTIVITY",
    "ACCOUNT_AUTH_CANCEL_SIGNAL",
    "ACCOUNT_AUTH_COOKIE_IMPORT_ACTIVITY",
    "ACCOUNT_AUTH_CREATE_QR_ACTIVITY",
    "ACCOUNT_AUTH_POLL_ACTIVITY",
    "ACCOUNT_AUTH_PHONE_LOGIN_ACTIVITY",
    "ACCOUNT_AUTH_TASK_QUEUE",
    "ACCOUNT_AUTH_WORKFLOW_TYPE",
    "PlatformLoginTemporalActivities",
    "TemporalAccountAuthWorkflow",
    "account_auth_activity_config",
    "build_account_auth_workflow_start",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(_TARGET_MODULE), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
