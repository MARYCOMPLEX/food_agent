"""Shared pytest fixtures and configuration for the test suite.

This conftest provides:
- Auto-marking based on filename prefix (test_unit_, test_integration_, test_e2e_)
- ``mock_llm`` async fixture for a configurable LLMService stub
- ``mock_xhs_search`` fixture for a stubbed XHS search tool
- ``event_bus`` fixture returning a fresh :class:`InMemoryEventBus`
- ``frozen_time`` fixture patching ``time.time``
- ``settings_override`` fixture yielding a mutable settings object
- Session-scoped autouse fixture that sets a dummy ``OPENAI_API_KEY``
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# Ensure ``src/`` is importable even when tests run outside an editable install.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# ---------------------------------------------------------------------------
# Test category assignment
# ---------------------------------------------------------------------------

_FILENAME_MARKERS = (
    ("test_unit_", "unit"),
    ("test_integration_", "integration"),
    ("test_e2e_", "e2e"),
)

_LEGACY_FILE_MARKERS = {
    "test_basic.py": "unit",
    "test_calculation_standalone.py": "unit",
    "test_comment_processing.py": "unit",
    "test_config.py": "live",
    "test_session.py": "integration",
}

_CATEGORY_MARKERS = ("unit", "integration", "e2e", "live")


def pytest_collection_modifyitems(config: pytest.Config, items: List[pytest.Item]) -> None:
    """Assign every test exactly one execution category."""
    uncategorized: List[str] = []
    for item in items:
        filename = Path(item.fspath).name
        marker = next(
            (name for prefix, name in _FILENAME_MARKERS if filename.startswith(prefix)),
            _LEGACY_FILE_MARKERS.get(filename),
        )

        existing = [name for name in _CATEGORY_MARKERS if item.get_closest_marker(name)]
        if marker and not existing:
            item.add_marker(getattr(pytest.mark, marker))
            existing = [marker]

        if len(existing) != 1:
            uncategorized.append(item.nodeid)

    if uncategorized:
        joined = "\n".join(f"- {nodeid}" for nodeid in uncategorized)
        raise pytest.UsageError(
            "Each test must have exactly one unit/integration/e2e/live marker:\n" + joined
        )


# ---------------------------------------------------------------------------
# Environment bootstrap
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _set_test_env() -> None:
    """Provide a dummy OPENAI_API_KEY so Settings doesn't blow up on import."""
    os.environ.setdefault("OPENAI_API_KEY", "test-key")
    os.environ.setdefault("DEFAULT_LLM_MODEL", "test-model")


# ---------------------------------------------------------------------------
# Settings fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def settings_override():
    """Yield a fresh, mutable Settings instance and reset the cached singleton."""
    from xhs_food.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    try:
        yield settings
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# LLM fixture
# ---------------------------------------------------------------------------


class _FakeMessage:
    """Stand-in for a LangChain ``AIMessage``."""

    def __init__(self, content: str) -> None:
        self.content = content


class FakeLLMService:
    """Configurable async LLM stub used in tests."""

    def __init__(self, response_content: str = "{}") -> None:
        self._response_content = response_content
        self.calls: List[List[Any]] = []

    def set_response(self, content: str) -> None:
        """Override the canned response content."""
        self._response_content = content

    async def call(self, messages: List[Any], **kwargs: Any) -> _FakeMessage:
        _ = kwargs
        self.calls.append(list(messages))
        return _FakeMessage(self._response_content)


@pytest.fixture
async def mock_llm() -> FakeLLMService:
    """Return a fresh :class:`FakeLLMService` for the current test."""
    return FakeLLMService()


# ---------------------------------------------------------------------------
# XHS search fixture
# ---------------------------------------------------------------------------


class FakeXHSSearch:
    """Stub for the XHS search tool. ``execute`` returns ``notes``."""

    def __init__(self, notes: Optional[List[Dict[str, Any]]] = None) -> None:
        self.notes: List[Dict[str, Any]] = notes or []
        self.calls: List[Dict[str, Any]] = []

    def set_notes(self, notes: List[Dict[str, Any]]) -> None:
        self.notes = notes

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        return {"notes": list(self.notes)}


@pytest.fixture
def mock_xhs_search() -> FakeXHSSearch:
    """Return a stub XHS search tool, pre-loaded with no notes."""
    return FakeXHSSearch()


# ---------------------------------------------------------------------------
# Event bus fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def event_bus():
    """Return a fresh in-memory event bus per-test."""
    from xhs_food.events.bus import InMemoryEventBus

    return InMemoryEventBus()


# ---------------------------------------------------------------------------
# Time fixture
# ---------------------------------------------------------------------------


_FROZEN_TIMESTAMP = 1_700_000_000.0


@pytest.fixture
def frozen_time(monkeypatch: pytest.MonkeyPatch) -> float:
    """Patch ``time.time`` to a fixed value across modules that imported it."""
    import time

    monkeypatch.setattr(time, "time", lambda: _FROZEN_TIMESTAMP)
    return _FROZEN_TIMESTAMP
