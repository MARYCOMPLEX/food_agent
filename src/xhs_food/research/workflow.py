"""The single comment-first Food Research Agent workflow."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from xhs_food.agents.analyzer import AnalyzerAgent
from xhs_food.agents.intent_parser import IntentParserAgent
from xhs_food.contracts import (
    AgentToolExecutionContext,
    PlatformChannel,
    ResearchGap,
    ResearchOutcome,
    ResearchRunResult,
    ShopProfile,
    ShopProfileRepositoryPort,
)
from xhs_food.domain_packs.food.decision import FoodDecisionPolicy
from xhs_food.domain_packs.food.intent import FoodSearchIntent
from xhs_food.schemas import (
    ConversationContext,
    MustTryItem,
    RestaurantRecommendation,
    XHSFoodResponse,
)

from .evidence import EvidenceLedger, evidence_ref
from .mcp import ManagedMcpToolSession, UnavailableMcpToolSession
from .profile_service import (
    ShopProfileRefreshPolicy,
    ShopProfileService,
)
from .repository import InMemoryShopProfileRepository
from .sources import (
    DianpingMcpSource,
    DianpingShopEnricher,
    EnrichmentResult,
    XhsCommentLeadCollector,
    XhsMcpSource,
)

SessionFactory = Callable[[], ManagedMcpToolSession]


@dataclass(frozen=True, slots=True)
class WorkflowExecution:
    response: XHSFoodResponse
    run: ResearchRunResult
    intent: FoodSearchIntent | None = None


class CommentFirstResearchWorkflow:
    """Coordinate one research turn through explicit injected collaborators.

    Every user turn enters this same method with the full conversation context.
    There is no follow-up classifier and no alternate shortcut for an existing
    result set.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        intent_parser: IntentParserAgent | None = None,
        analyzer: AnalyzerAgent | None = None,
        evidence: EvidenceLedger | None = None,
        profiles: ShopProfileRepositoryPort | None = None,
        profile_service: ShopProfileService | None = None,
        max_notes: int = 30,
        max_restaurants: int = 10,
        analysis_concurrency: int = 3,
        profile_concurrency: int = 3,
        profile_refresh_after: timedelta = timedelta(days=7),
        partial_profile_retry_after: timedelta = timedelta(hours=12),
    ) -> None:
        if profiles is not None and profile_service is not None:
            raise ValueError("inject profiles or profile_service, not both")
        self._session_factory = session_factory or UnavailableMcpToolSession
        self._intent_parser = intent_parser or IntentParserAgent()
        self._analyzer = analyzer or AnalyzerAgent()
        self._evidence = evidence or EvidenceLedger()
        profile_repository = profiles or InMemoryShopProfileRepository()
        self._profile_service = profile_service or ShopProfileService(
            profile_repository,
            policy=ShopProfileRefreshPolicy(
                refresh_after=profile_refresh_after,
                partial_retry_after=partial_profile_retry_after,
            ),
        )
        self._max_notes = max(1, max_notes)
        self._max_restaurants = max(1, max_restaurants)
        self._analysis_semaphore = asyncio.Semaphore(max(1, analysis_concurrency))
        self._profile_concurrency = max(1, profile_concurrency)
        self._decision = FoodDecisionPolicy()

    @property
    def evidence(self) -> EvidenceLedger:
        return self._evidence

    @property
    def profiles(self) -> ShopProfileRepositoryPort:
        return self._profile_service.repository

    async def execute(
        self,
        user_input: str,
        context: ConversationContext,
        *,
        tool_context: AgentToolExecutionContext | None = None,
    ) -> WorkflowExecution:
        context.add_user_message(user_input)
        parse_result = await self._intent_parser.parse(user_input, context)
        if not parse_result.success:
            response = XHSFoodResponse(
                status="clarify" if parse_result.need_clarify else "error",
                clarify_questions=parse_result.questions,
                error_message=None if parse_result.need_clarify else parse_result.error,
                summary="需要更多信息以继续研究" if parse_result.need_clarify else "意图解析失败",
            )
            return WorkflowExecution(response=response, run=ResearchRunResult(outcome=ResearchOutcome.FAILED))
        intent = parse_result.intent
        if intent is None:
            response = XHSFoodResponse(status="error", error_message="意图解析缺少结构化结果")
            return WorkflowExecution(response=response, run=ResearchRunResult(outcome=ResearchOutcome.FAILED))

        context.last_intent = intent.to_dict()
        context.target_city = intent.location
        context.turn_count += 1
        authority = tool_context or AgentToolExecutionContext(
            tenant_ref="local-anonymous",
            platforms=(PlatformChannel.XHS_PC, PlatformChannel.DIANPING),
        )
        session = self._session_factory()
        await session.open(authority)
        try:
            xhs_platform = (
                PlatformChannel.XHS_PC
                if PlatformChannel.XHS_PC in authority.platforms
                else PlatformChannel.XHS_CREATOR
            )
            collector = XhsCommentLeadCollector(
                XhsMcpSource(session, platform=xhs_platform),
                max_notes=self._max_notes,
            )
            collected = await collector.collect(intent)
            notes = collected.notes
            evidence_refs = await self._evidence.record_many(notes)
            recommendations, analysis_gaps = await self._analyze(notes, intent)
            recommendations, filtered_count = self._decision.rank_and_filter(
                self._decision.merge_and_validate(recommendations),
                context.excluded_shops,
            )
            recommendations = recommendations[: self._max_restaurants]
            _attach_evidence(recommendations, notes, evidence_refs)

            profile_plan = await self._profile_service.plan(
                [item.name for item in recommendations]
            )
            enrichment = await self._enrich(
                session,
                profile_plan.refresh_candidates,
                intent,
                enabled=PlatformChannel.DIANPING in authority.platforms,
            )
            profile_sync = await self._profile_service.commit(
                profile_plan, enrichment.profiles
            )
            shop_profiles = profile_sync.profiles
            _attach_profiles(recommendations, shop_profiles)

            gaps = _dedupe_gaps(
                (
                    *collected.gaps,
                    *(gap for note in notes for gap in note.gaps),
                    *tuple(
                        ResearchGap(
                            source="evidence",
                            operation="canonical.write",
                            code=str(item.get("code") or "evidence_lifecycle_write_failed"),
                            message=str(item.get("message") or "evidence lifecycle write failed"),
                            retryable=True,
                            details={"note_id": item.get("note_id")},
                        )
                        for item in self._evidence.lifecycle_errors
                    ),
                    *analysis_gaps,
                    *profile_plan.gaps,
                    *enrichment.gaps,
                    *profile_sync.gaps,
                )
            )
            outcome = _outcome(notes, recommendations, gaps)
            run = ResearchRunResult(
                notes=notes,
                profiles=shop_profiles,
                evidence_refs=evidence_refs,
                gaps=gaps,
                outcome=outcome,
                raw_payload={
                    "xhs": collected.raw_payload,
                    "dianping": enrichment.raw_payload,
                    "shop_profile_cache": {
                        "hits": list(profile_plan.fresh_cache_hits),
                        "refresh_candidates": list(profile_plan.refresh_candidates),
                    },
                },
            )
            context.last_notes = [note.model_dump(mode="json") for note in notes]
            context.last_recommendations = {
                recommendation.name: recommendation.to_dict()
                for recommendation in recommendations
            }
            summary = _summary(intent, notes, recommendations, outcome)
            response = XHSFoodResponse(
                status="ok" if outcome is not ResearchOutcome.FAILED else "error",
                recommendations=recommendations,
                filtered_count=filtered_count,
                error_message="小红书评论证据采集失败" if outcome is ResearchOutcome.FAILED else None,
                summary=summary,
                research_metadata={
                    "strategy": "comment_first/v1",
                    "outcome": outcome.value,
                    "noteCount": len(notes),
                    "commentEvidenceCount": len(evidence_refs),
                    "shopProfileCount": len(shop_profiles),
                    "shopProfileCacheHits": len(profile_plan.fresh_cache_hits),
                    "shopProfileRefreshCount": len(profile_plan.refresh_candidates),
                },
                gaps=[gap.model_dump(mode="json") for gap in gaps],
            )
            return WorkflowExecution(response=response, run=run, intent=intent)
        finally:
            await session.close()

    async def _analyze(
        self,
        notes: Sequence[Any],
        intent: FoodSearchIntent,
    ) -> tuple[list[RestaurantRecommendation], tuple[ResearchGap, ...]]:
        results = await asyncio.gather(
            *(self._analyze_note(note, intent) for note in notes), return_exceptions=True
        )
        recommendations: list[RestaurantRecommendation] = []
        gaps: list[ResearchGap] = []
        for note, result in zip(notes, results, strict=False):
            if isinstance(result, BaseException):
                gaps.append(
                    ResearchGap(
                        source="agent",
                        operation="comments.analyze",
                        code="analysis_exception",
                        message=type(result).__name__,
                        retryable=True,
                        details={"note_id": note.note_id},
                    )
                )
            elif not result.success:
                gaps.append(
                    ResearchGap(
                        source="agent",
                        operation="comments.analyze",
                        code="analysis_failed",
                        message=result.error or "comment analysis failed",
                        retryable=True,
                        details={"note_id": note.note_id},
                    )
                )
            else:
                recommendations.extend(result.restaurants)
        return recommendations, tuple(gaps)

    async def _analyze_note(self, note: Any, intent: FoodSearchIntent) -> Any:
        comments = [
            {
                "id": item.comment_id,
                "comment_id": item.comment_id,
                "text": item.text,
                "likes": item.likes,
                "sub_comment_count": item.replies,
                "user": _author_name(item.author),
                "raw_payload": item.raw_payload,
            }
            for item in note.comments
        ]
        async with self._analysis_semaphore:
            return await self._analyzer.analyze(
                note.title,
                note.summary,
                comments,
                intent.exclude_keywords,
                note.note_id,
            )

    async def _enrich(
        self,
        session: ManagedMcpToolSession,
        candidates: Sequence[str],
        intent: FoodSearchIntent,
        *,
        enabled: bool,
    ) -> EnrichmentResult:
        if not candidates or not enabled:
            return EnrichmentResult(profiles=())
        return await DianpingShopEnricher(
            DianpingMcpSource(session),
            max_profiles=self._max_restaurants,
            concurrency=self._profile_concurrency,
        ).enrich(candidates, intent)

def _attach_evidence(
    recommendations: Sequence[RestaurantRecommendation],
    notes: Sequence[Any],
    evidence_refs: Sequence[str],
) -> None:
    # Build the relation from the typed notes instead of parsing a transport
    # reference string.  Provider IDs may legally contain ``:`` and should
    # never be mis-associated by a delimiter heuristic.
    allowed_refs = set(evidence_refs)
    refs_by_note: dict[str, list[str]] = {
        note.note_id: [
            ref
            for item in note.comments
            if (ref := evidence_ref(item)) in allowed_refs
        ]
        for note in notes
    }
    notes_by_id = {note.note_id: note for note in notes}
    for recommendation in recommendations:
        refs: list[str] = []
        source_gaps: list[dict[str, Any]] = []
        comment_count = 0
        for note_id in recommendation.source_notes:
            refs.extend(refs_by_note.get(note_id, ()))
            note = notes_by_id.get(note_id)
            if note is not None:
                comment_count += len(note.comments)
                source_gaps.extend(gap.model_dump(mode="json") for gap in note.gaps)
        recommendation.evidence_refs = list(dict.fromkeys(refs))
        recommendation.evidence_summary = {
            "commentCount": comment_count,
            "noteCount": len(set(recommendation.source_notes)),
        }
        recommendation.source_gaps = source_gaps


def _attach_profiles(
    recommendations: Sequence[RestaurantRecommendation],
    profiles: Sequence[ShopProfile],
) -> None:
    for recommendation in recommendations:
        profile = _profile_for_name(recommendation.name, profiles)
        if profile is None:
            continue
        recommendation.location = profile.address or profile.region or recommendation.location
        recommendation.tags = list(dict.fromkeys((*recommendation.tags, *profile.tags)))
        if not recommendation.must_try:
            recommendation.must_try = [MustTryItem(name=item) for item in profile.recommended_dishes]
        projection = {
            "providerRefs": dict(profile.provider_refs),
            "name": profile.name,
            "alias": profile.alias,
            "url": profile.url,
            "sourceUrl": profile.source_url,
            "imageUrl": profile.image_url,
            "images": list(profile.images),
            "address": profile.address,
            "city": profile.city,
            "district": profile.district,
            "region": profile.region,
            "businessArea": profile.business_area,
            "location": profile.location,
            "latitude": profile.latitude,
            "longitude": profile.longitude,
            "coordinateSystem": profile.coordinate_system,
            "geo": dict(profile.geo),
            "phone": profile.phone,
            "rating": profile.rating,
            "reviewCount": profile.review_count,
            "averagePrice": profile.average_price,
            "category": profile.category,
            "openingHours": profile.opening_hours,
            "recommendedDishes": list(profile.recommended_dishes),
            "promotions": list(profile.promotions),
            "tags": list(profile.tags),
            "attributes": dict(profile.attributes),
            "reviewCompleteness": dict(profile.review_completeness),
            "profileOutcome": profile.outcome.value,
            "profileGaps": [gap.model_dump(mode="json") for gap in profile.gaps],
        }
        recommendation.shop_profile = projection


def _profile_for_name(name: str, profiles: Sequence[ShopProfile]) -> ShopProfile | None:
    target = _normalise_name(name)
    for profile in profiles:
        candidate = _normalise_name(profile.name)
        if candidate == target or candidate in target or target in candidate:
            return profile
    return None


def _normalise_name(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _author_name(author: Mapping[str, Any]) -> str:
    for key in ("nickname", "name", "user_name", "userName"):
        value = author.get(key)
        if value:
            return str(value)
    return ""


def _dedupe_gaps(values: Sequence[ResearchGap]) -> tuple[ResearchGap, ...]:
    output: list[ResearchGap] = []
    seen: set[str] = set()
    for gap in values:
        marker = gap.model_dump_json()
        if marker not in seen:
            seen.add(marker)
            output.append(gap)
    return tuple(output)


def _outcome(
    notes: Sequence[Any],
    recommendations: Sequence[RestaurantRecommendation],
    gaps: Sequence[ResearchGap],
) -> ResearchOutcome:
    if not notes and gaps:
        return ResearchOutcome.FAILED
    if not notes:
        return ResearchOutcome.EMPTY
    if gaps:
        return ResearchOutcome.PARTIAL
    return ResearchOutcome.COMPLETE


def _summary(
    intent: FoodSearchIntent,
    notes: Sequence[Any],
    recommendations: Sequence[RestaurantRecommendation],
    outcome: ResearchOutcome,
) -> str:
    if outcome is ResearchOutcome.FAILED:
        return "小红书评论证据采集失败，未生成不可靠的空推荐"
    if not notes:
        return f"未在{intent.location}找到可分析的小红书评论证据"
    suffix = "，部分来源存在可审计缺口" if outcome is ResearchOutcome.PARTIAL else ""
    return (
        f"基于 {len(notes)} 篇小红书笔记的评论证据，"
        f"在{intent.location}识别到 {len(recommendations)} 家候选店铺{suffix}"
    )


__all__ = ["CommentFirstResearchWorkflow", "WorkflowExecution"]
