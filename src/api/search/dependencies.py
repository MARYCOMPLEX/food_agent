"""FastAPI dependency adapters for the search use-case boundary."""

from __future__ import annotations

from typing import cast

from fastapi import Request

from xhs_food.contracts import ReliableResearchTaskPort, ResearchTaskPort


def get_research_task(request: Request) -> ResearchTaskPort:
    """Resolve the active facade installed by the application Composition Root."""
    try:
        port = request.app.state.research_task
    except AttributeError as exc:
        raise RuntimeError("ResearchTaskPort is not bound") from exc
    return cast(ResearchTaskPort, port)


def get_reliable_research_task(request: Request) -> ReliableResearchTaskPort:
    """Resolve the opt-in reliable admission port without widening legacy APIs."""

    try:
        port = request.app.state.research_task
    except AttributeError as exc:
        raise RuntimeError("ResearchTaskPort is not bound") from exc
    if not callable(getattr(port, "submit", None)):
        raise RuntimeError("ReliableResearchTaskPort is not bound")
    return cast(ReliableResearchTaskPort, port)


__all__ = ["get_reliable_research_task", "get_research_task"]
