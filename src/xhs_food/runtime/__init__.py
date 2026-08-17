"""Agentic runtime primitives.

The runtime is deliberately independent from FastAPI, LangChain and the XHS
spider.  It owns planning, execution, budgets and lifecycle state while the
application supplies capabilities, memory and an optional model adapter.
"""

from .agent_loop import AgentLoop, AgentLoopConfig
from .executor import ExecutionReport, PlanExecutor
from .models import (
    AgentRunContext,
    AgentRunResult,
    Evidence,
    LoopPhase,
    Plan,
    PlanStep,
    PlanStepStatus,
    StepExecution,
)
from .planner import Planner, RuleBasedPlanner
from .reviewer import ReviewDecision, Reviewer, RuleBasedReviewer

__all__ = [
    "AgentLoop",
    "AgentLoopConfig",
    "AgentRunContext",
    "AgentRunResult",
    "Evidence",
    "ExecutionReport",
    "LoopPhase",
    "Plan",
    "PlanExecutor",
    "PlanStep",
    "PlanStepStatus",
    "Planner",
    "ReviewDecision",
    "Reviewer",
    "RuleBasedPlanner",
    "RuleBasedReviewer",
    "StepExecution",
]
