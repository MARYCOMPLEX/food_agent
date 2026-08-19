"""FastAPI dependency adapters for the search use-case boundary."""

from __future__ import annotations

from typing import cast

from fastapi import Request

from xhs_food.contracts import ResearchTaskPort


def get_research_task(request: Request) -> ResearchTaskPort:
    """Resolve the active facade installed by the application Composition Root."""
    try:
        port = request.app.state.research_task
    except AttributeError as exc:
        raise RuntimeError("ResearchTaskPort is not bound") from exc
    return cast(ResearchTaskPort, port)


__all__ = ["get_research_task"]
