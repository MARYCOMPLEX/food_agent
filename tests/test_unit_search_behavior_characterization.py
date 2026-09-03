"""Current search behavior contracts.

The previous four-phase/search-shortcut characterization belonged to the
retired implementation.  These tests pin the single conversation-aware
comment-first workflow instead.
"""

from __future__ import annotations

from typing import Any

import pytest

from xhs_food.contracts import PlatformChannel, SourceCall
from xhs_food.domain_packs.food.intent import FoodSearchIntent
from xhs_food.research.sources import AdaptiveQueryPlanner, XhsCommentLeadCollector


def test_query_planner_is_small_and_controversy_aware() -> None:
    queries = AdaptiveQueryPlanner(max_queries=3).plan(
        FoodSearchIntent(location="成都", food_type="火锅", requirements=["本地人"])
    )
    assert len(queries) == 3
    assert queries[0] == "成都 火锅"
    assert "争议" in queries[-1]
    assert len(set(queries)) == len(queries)


class _Source:
    async def search_notes(self, **_: Any) -> SourceCall:
        return SourceCall(
            source="xhs",
            operation="notes.search",
            success=True,
            data={
                "notes": [
                    {
                        "note_id": "note-1",
                        "search_item": {"note_card": {"display_title": "成都火锅"}},
                        "comments": {
                            "items": [
                                {"id": "comment-1", "content": "锅底很香", "like_count": 3}
                            ],
                            "has_more": False,
                        },
                    }
                ]
            },
        )

    async def note_detail(self, note_id: str, **_: Any) -> SourceCall:
        return SourceCall(
            source="xhs", operation="notes.detail", success=True, data={"note_id": note_id}
        )

    async def search_comments(self, note_id: str, **_: Any) -> SourceCall:
        return SourceCall(
            source="xhs", operation="comments.search", success=True, data={"items": []}
        )


@pytest.mark.asyncio
async def test_collector_always_returns_raw_comment_evidence_without_phase_state() -> None:
    result = await XhsCommentLeadCollector(_Source(), planner=AdaptiveQueryPlanner(1)).collect(
        FoodSearchIntent(location="成都", food_type="火锅")
    )
    assert len(result.notes) == 1
    assert result.notes[0].comments[0].text == "锅底很香"
    assert result.notes[0].comment_completeness == "complete"
    assert result.notes[0].raw_payload is not None
