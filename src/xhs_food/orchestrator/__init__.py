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
    "ReliableTaskEventPublisher",
    "ReliableTaskOwner",
    "ResearchCoordinator",
    "ResearchWorkflowInput",
    "ResearchWorkflowOutput",
    "ResultCommitReceipt",
    "StepScheduler",
    "TemporalReliableResearchPolicy",
    "TemporalResearchWorkflow",
    "XHSFoodOrchestrator",
    "build_workflow_start",
    "build_pydantic_ai_research_workflow",
    "build_reliable_research_worker",
    "pydantic_ai_worker_plugin",
    "stable_research_task_id",
    "stable_research_workflow_id",
]

_EXPORT_MODULES = {
    "ResearchCoordinator": "xhs_food.orchestrator.coordinator",
    "StepScheduler": "xhs_food.orchestrator.scheduler",
    "XHSFoodOrchestrator": "xhs_food.orchestrator.core",
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
