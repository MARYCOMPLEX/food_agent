"""Unit tests for :mod:`api.search.state` — the in-memory task state store.

These tests exercise the ``_MemoryStateStore`` backend directly so we never
hit Redis, then verify the public helper functions (``get_or_init_state``,
``update_state``, ``clear_state``) behave correctly when wired to it.
"""

from __future__ import annotations

import asyncio

import pytest

from api.search import state as state_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch: pytest.MonkeyPatch):
    """Force a fresh in-memory store for every test.

    Resets the module-level ``_state_store`` and swaps in a new
    :class:`_MemoryStateStore` so tests are fully isolated.
    """
    store = state_mod._MemoryStateStore()  # noqa: SLF001 - test-only access
    monkeypatch.setattr(state_mod, "_state_store", store)
    yield store


# ---------------------------------------------------------------------------
# Memory store primitive operations
# ---------------------------------------------------------------------------


async def test_memory_store_get_returns_none_when_absent() -> None:
    # Arrange
    store = state_mod._MemoryStateStore()  # noqa: SLF001

    # Act / Assert
    assert await store.get("missing") is None


async def test_memory_store_set_then_get_roundtrips() -> None:
    # Arrange
    store = state_mod._MemoryStateStore()  # noqa: SLF001
    payload = {"id": "s1", "status": "loading"}

    # Act
    await store.set("s1", payload)

    # Assert
    assert await store.get("s1") == payload


async def test_memory_store_delete_removes_entry() -> None:
    # Arrange
    store = state_mod._MemoryStateStore()  # noqa: SLF001
    await store.set("s1", {"id": "s1"})

    # Act
    await store.delete("s1")

    # Assert
    assert await store.get("s1") is None


# ---------------------------------------------------------------------------
# get_or_init_state
# ---------------------------------------------------------------------------


async def test_get_or_init_state_creates_default_when_missing() -> None:
    # Arrange
    sid = "new-session"

    # Act
    state = await state_mod.get_or_init_state(sid)

    # Assert
    assert state["id"] == sid
    assert state["status"] == "idle"
    assert state["query"] == ""
    assert state["turn_id"] == 0
    assert "created_at" in state
    assert "updated_at" in state


async def test_get_or_init_state_is_idempotent_for_same_session() -> None:
    # Arrange / Act
    first = await state_mod.get_or_init_state("s1")
    second = await state_mod.get_or_init_state("s1")

    # Assert — same dict, same created_at
    assert first["created_at"] == second["created_at"]


async def test_get_or_init_state_honors_status_argument() -> None:
    # Arrange / Act
    state = await state_mod.get_or_init_state("s-loading", status="loading")

    # Assert
    assert state["status"] == "loading"


# ---------------------------------------------------------------------------
# update_state
# ---------------------------------------------------------------------------


async def test_update_state_merges_changes_and_bumps_updated_at() -> None:
    # Arrange — create the state, capture its original updated_at
    sid = "s1"
    original = await state_mod.get_or_init_state(sid)
    original_updated = original["updated_at"]
    # Give the clock a chance to advance to make the comparison reliable.
    await asyncio.sleep(0.01)

    # Act
    new_state = await state_mod.update_state(
        sid, status="loading", query="火锅", turn_id=1
    )

    # Assert
    assert new_state["status"] == "loading"
    assert new_state["query"] == "火锅"
    assert new_state["turn_id"] == 1
    assert new_state["updated_at"] >= original_updated


async def test_update_state_creates_state_if_missing() -> None:
    # Arrange / Act
    state = await state_mod.update_state("brand-new", status="completed")

    # Assert
    assert state["status"] == "completed"
    assert state["id"] == "brand-new"


# ---------------------------------------------------------------------------
# clear_state
# ---------------------------------------------------------------------------


async def test_clear_state_removes_entry() -> None:
    # Arrange
    await state_mod.get_or_init_state("s1")

    # Act
    await state_mod.clear_state("s1")

    # Assert
    assert await state_mod.load_state("s1") is None
