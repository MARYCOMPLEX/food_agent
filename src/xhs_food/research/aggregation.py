"""Deterministic entity and controversy aggregation for comment insights.

LLM output is treated as an interpretation, never as the evidence authority.
This reducer keeps every insight's evidence references and produces compact
JSON projections for ranking/synthesis while the raw comments stay in the
evidence ledger.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from xhs_food.contracts import CommentInsight, InsightClaim


@dataclass(frozen=True, slots=True)
class AggregationResult:
    """Stable projections derived from typed comment insights."""

    insights: tuple[CommentInsight, ...] = ()
    claims: tuple[InsightClaim, ...] = ()
    entities: tuple[dict[str, Any], ...] = ()
    controversies: tuple[dict[str, Any], ...] = ()


class EntityControversyAggregator:
    """Merge duplicate insights and expose disagreement as explicit edges."""

    def aggregate(self, insights: Iterable[CommentInsight]) -> AggregationResult:
        by_evidence: dict[str, CommentInsight] = {}
        for insight in insights:
            key = insight.evidence_key
            previous = by_evidence.get(key)
            if previous is None or self._rank(insight) > self._rank(previous):
                by_evidence[key] = insight

        ordered_insights = tuple(by_evidence[key] for key in sorted(by_evidence))
        claims_by_id: dict[str, InsightClaim] = {}
        for insight in ordered_insights:
            for claim in insight.claims:
                previous = claims_by_id.get(claim.claim_id)
                if previous is None or self._rank(claim) > self._rank(previous):
                    claims_by_id[claim.claim_id] = claim

        entities = self._entities(ordered_insights)
        controversies = self._controversies(ordered_insights)
        return AggregationResult(
            insights=ordered_insights,
            claims=tuple(claims_by_id[key] for key in sorted(claims_by_id)),
            entities=entities,
            controversies=controversies,
        )

    # Alias used by reducers and callers that think in terms of reduction.
    reduce = aggregate

    @staticmethod
    def _rank(value: Any) -> tuple[int, str]:
        payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return len(encoded), encoded

    @staticmethod
    def _key(value: str) -> str:
        return "".join(value.casefold().split())

    def _entities(self, insights: tuple[CommentInsight, ...]) -> tuple[dict[str, Any], ...]:
        buckets: dict[str, dict[str, Any]] = {}
        for insight in insights:
            for name in insight.mentioned_shops:
                key = self._key(name)
                if not key:
                    continue
                item = buckets.setdefault(
                    key,
                    {
                        "entity_type": "shop",
                        "name": name,
                        "normalized_name": key,
                        "mention_count": 0,
                        "positive_count": 0,
                        "negative_count": 0,
                        "correction_count": 0,
                        "evidence_refs": set(),
                        "note_ids": set(),
                        "dishes": set(),
                    },
                )
                item["mention_count"] += 1
                item["positive_count"] += insight.sentiment.value == "positive"
                item["negative_count"] += insight.sentiment.value == "negative"
                item["correction_count"] += int(insight.is_correction)
                item["evidence_refs"].update(insight.evidence_refs or (insight.evidence_key,))
                item["note_ids"].add(insight.note_id)
                item["dishes"].update(insight.mentioned_dishes)
        return tuple(self._freeze_entity(buckets[key]) for key in sorted(buckets))

    def _controversies(self, insights: tuple[CommentInsight, ...]) -> tuple[dict[str, Any], ...]:
        # A controversy is a shop with both positive and negative evidence, or
        # an explicit correction.  Keep the source refs so synthesis can cite it.
        grouped: dict[str, dict[str, Any]] = {}
        for insight in insights:
            for name in insight.mentioned_shops:
                key = self._key(name)
                if not key:
                    continue
                item = grouped.setdefault(
                    key,
                    {
                        "entity": name,
                        "positive_refs": set(),
                        "negative_refs": set(),
                        "correction_refs": set(),
                    },
                )
                refs = set(insight.evidence_refs or (insight.evidence_key,))
                if insight.sentiment.value == "positive":
                    item["positive_refs"].update(refs)
                elif insight.sentiment.value == "negative":
                    item["negative_refs"].update(refs)
                if insight.is_correction:
                    item["correction_refs"].update(refs)
        output: list[dict[str, Any]] = []
        for key in sorted(grouped):
            item = grouped[key]
            if not (item["correction_refs"] or (item["positive_refs"] and item["negative_refs"])):
                continue
            output.append(
                {
                    "entity": item["entity"],
                    "normalized_name": key,
                    "kind": "correction" if item["correction_refs"] else "mixed_sentiment",
                    "positive_evidence_refs": sorted(item["positive_refs"]),
                    "negative_evidence_refs": sorted(item["negative_refs"]),
                    "correction_evidence_refs": sorted(item["correction_refs"]),
                }
            )
        return tuple(output)

    @staticmethod
    def _freeze_entity(item: dict[str, Any]) -> dict[str, Any]:
        frozen = dict(item)
        for key in ("evidence_refs", "note_ids", "dishes"):
            frozen[key] = sorted(frozen[key])
        return frozen


__all__ = ["AggregationResult", "EntityControversyAggregator"]
