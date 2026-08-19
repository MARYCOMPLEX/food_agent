"""Pure, field-aware projections for the frozen Food compatibility views."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

from xhs_food.contracts import ContractPayload, ResearchResultSnapshot


class StableResultMapper:
    """Map internal snapshots without normalizing the mixed legacy key casing."""

    def to_http_results(self, session_id: str, state: ContractPayload) -> ContractPayload:
        return cast(
            ContractPayload,
            {
                "sessionId": session_id,
                "restaurants": deepcopy(state.get("restaurants", [])),
                "summary": state.get("summary", ""),
            },
        )

    def to_completed_recovery(
        self, session_id: str, records: tuple[ContractPayload, ...]
    ) -> ContractPayload:
        turns: list[ContractPayload] = []
        for record in records:
            restaurants = cast(list[ContractPayload], deepcopy(record.get("restaurants", [])))
            turns.append(
                cast(
                    ContractPayload,
                    {
                        "turnId": record.get("turn_id", 1),
                        "query": record.get("query", ""),
                        "restaurants": restaurants,
                        "summary": record.get("summary", ""),
                        "total": len(restaurants),
                        "createdAt": record.get("created_at"),
                    },
                )
            )

        latest = records[-1]
        latest_restaurants = cast(list[ContractPayload], deepcopy(latest.get("restaurants", [])))
        return cast(
            ContractPayload,
            {
                "success": True,
                "data": {
                    "sessionId": session_id,
                    "status": "completed",
                    "turnId": latest.get("turn_id", 1),
                    "query": latest.get("query", ""),
                    "restaurants": latest_restaurants,
                    "summary": latest.get("summary", ""),
                    "total": len(latest_restaurants),
                    "turns": turns,
                    "turnCount": len(turns),
                    "fromDatabase": True,
                },
            },
        )

    def to_sse_restaurant(self, item: ContractPayload) -> ContractPayload:
        return cast(ContractPayload, {"restaurant": deepcopy(item)})

    def to_sse_result(
        self,
        snapshot: ResearchResultSnapshot,
        steps: tuple[ContractPayload, ...],
    ) -> ContractPayload:
        return cast(
            ContractPayload,
            {
                "summary": snapshot.summary,
                "total": (
                    snapshot.total_count
                    if snapshot.total_count is not None
                    else len(snapshot.recommendations)
                ),
                "filtered": snapshot.filtered_count,
                "steps": deepcopy(list(steps)),
            },
        )

    def to_persisted_restaurant(self, item: ContractPayload, restaurant_id: str) -> ContractPayload:
        persisted = deepcopy(item)
        persisted["id"] = restaurant_id
        return persisted


__all__ = ["StableResultMapper"]
