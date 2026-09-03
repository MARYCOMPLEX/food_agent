"""Source-consumer contracts for the two managed MCP connectors."""

from __future__ import annotations

from typing import Any

import pytest

from xhs_food.contracts import PlatformChannel, SourceCall
from xhs_food.research.sources import DianpingMcpSource, XhsMcpSource


class _Session:
    def __init__(self) -> None:
        self.calls: list[tuple[PlatformChannel, str, dict[str, Any]]] = []

    async def call(
        self, platform: PlatformChannel, capability: str, arguments: dict[str, Any]
    ) -> SourceCall:
        self.calls.append((platform, capability, arguments))
        return SourceCall(source=platform.value, operation=capability, success=True, data={})


@pytest.mark.asyncio
async def test_platform_adapters_translate_semantic_operations_to_mcp_calls() -> None:
    session = _Session()
    xhs = XhsMcpSource(session)  # type: ignore[arg-type]
    dianping = DianpingMcpSource(session)  # type: ignore[arg-type]

    await xhs.search_notes(query="成都火锅")
    await xhs.note_detail("note-1", include_comments=True)
    await xhs.search_comments("note-1", cursor="next")
    await dianping.search_places(keyword="老店")
    await dianping.place_detail("shop-1")
    await dianping.search_reviews("shop-1", offset=0)

    assert [item[1] for item in session.calls] == [
        "notes.search",
        "notes.detail",
        "comments.search",
        "places.search",
        "places.detail",
        "reviews.search",
    ]
    assert session.calls[1][2]["note_id"] == "note-1"
    assert session.calls[4][2]["shop_id"] == "shop-1"
