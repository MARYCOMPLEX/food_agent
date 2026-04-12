"""
Shared session state for search routes.

In-memory session storage for transient state; SessionManager handles
persistent context (Redis + PostgreSQL).
"""

import time
from typing import Dict, Any

from xhs_food import XHSFoodOrchestrator
from xhs_food.di import get_xhs_tool_registry


_sessions: Dict[str, Dict[str, Any]] = {}
_orchestrators: Dict[str, XHSFoodOrchestrator] = {}


def _get_session(session_id: str) -> Dict[str, Any]:
    """Get or create session state."""
    if session_id not in _sessions:
        _sessions[session_id] = {
            "id": session_id,
            "status": "idle",
            "restaurants": [],
            "summary": "",
            "error": None,
            "created_at": time.time(),
        }
    return _sessions[session_id]


def _get_orchestrator(session_id: str) -> XHSFoodOrchestrator:
    """Get or create orchestrator for a session."""
    if session_id not in _orchestrators:
        _orchestrators[session_id] = XHSFoodOrchestrator(
            xhs_registry=get_xhs_tool_registry()
        )
    return _orchestrators[session_id]
