"""Orchestrator public exports with lazy legacy/runtime loading.

Temporal's workflow sandbox imports the package containing a workflow class.
Eagerly importing the legacy Food analyzer here would pull wall-clock and
provider modules into that sandbox, so public names resolve only when a caller
asks for them. The names and import paths remain unchanged for consumers.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "LEGACY_TASK_POLICY_VERSION",
    "RESEARCH_FAIL_ACTIVITY",
    "RESEARCH_RECONCILE_ACTIVITY",
    "InMemoryReliableTaskAuthority",
    "InMemoryReliableTaskEventPublisher",
    "RELIABLE_TASK_POLICY_VERSION",
    "ReliableResearchActivities",
    "ReliableTaskAuthority",
    "ReliableTaskConfig",
    "ReliableTaskConflict",
    "ReliableTaskEventPublisher",
    "ReliableTaskOwner",
    "ResearchCoordinator",
    "ResearchWorkflowInput",
    "ResearchWorkflowOutput",
    "REFRESH_CANCEL_SIGNAL",
    "REFRESH_EXECUTE_ACTIVITY",
    "REFRESH_TASK_QUEUE",
    "REFRESH_WORKFLOW_TYPE",
    "MEDIA_CANCEL_SIGNAL",
    "MEDIA_FETCH_ACTIVITY",
    "MEDIA_TASK_QUEUE",
    "MEDIA_WORKFLOW_TYPE",
    "MediaActivities",
    "TemporalMediaWorkflow",
    "RefreshActivities",
    "ResultCommitReceipt",
    "StepScheduler",
    "TemporalReliableResearchPolicy",
    "TemporalResearchWorkflow",
    "TemporalRefreshWorkflow",
    "XHSFoodOrchestrator",
    "build_workflow_start",
    "build_pydantic_ai_research_workflow",
    "build_refresh_workflow_start",
    "pydantic_ai_worker_plugin",
    "refresh_activity_config",
    "media_activity_config",
    "build_media_workflow_start",
    "stable_research_task_id",
    "stable_research_workflow_id",
]

_EXPORT_MODULES = {
    "ResearchCoordinator": "xhs_food.orchestrator.coordinator",
    "StepScheduler": "xhs_food.orchestrator.scheduler",
    "XHSFoodOrchestrator": "xhs_food.orchestrator.core",
    "REFRESH_CANCEL_SIGNAL": "xhs_food.orchestrator.refresh_media",
    "REFRESH_EXECUTE_ACTIVITY": "xhs_food.orchestrator.refresh_media",
    "REFRESH_TASK_QUEUE": "xhs_food.orchestrator.refresh_media",
    "REFRESH_WORKFLOW_TYPE": "xhs_food.orchestrator.refresh_media",
    "RefreshActivities": "xhs_food.orchestrator.refresh_media",
    "TemporalRefreshWorkflow": "xhs_food.orchestrator.refresh_media",
    "build_refresh_workflow_start": "xhs_food.orchestrator.refresh_media",
    "refresh_activity_config": "xhs_food.orchestrator.refresh_media",
    "MEDIA_CANCEL_SIGNAL": "xhs_food.orchestrator.refresh_media",
    "MEDIA_FETCH_ACTIVITY": "xhs_food.orchestrator.refresh_media",
    "MEDIA_TASK_QUEUE": "xhs_food.orchestrator.refresh_media",
    "MEDIA_WORKFLOW_TYPE": "xhs_food.orchestrator.refresh_media",
    "MediaActivities": "xhs_food.orchestrator.refresh_media",
    "TemporalMediaWorkflow": "xhs_food.orchestrator.refresh_media",
    "media_activity_config": "xhs_food.orchestrator.refresh_media",
    "build_media_workflow_start": "xhs_food.orchestrator.refresh_media",
}
_RELIABLE_EXPORTS = {name for name in __all__ if name not in _EXPORT_MODULES}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None and name in _RELIABLE_EXPORTS:
        module_name = "xhs_food.orchestrator.reliable_task"
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
