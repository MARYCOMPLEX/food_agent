"""
AnalyzerAgent - 内容分析代理 (重构版).

采用三阶段流水线架构：
1. Python 预处理: 提取点赞、计算 interaction_score
2. LLM 语义分析: 仅判断 identity/sentiment/is_correction/mentioned_shops
3. Python 后处理: 精确计算最终权重得分

此架构解决 LLM 算术错误问题，并大幅降低 Prompt 成本。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from xhs_food.common import extract_json
from xhs_food.contracts import (
    CommentIdentity,
    CommentInsight,
    CommentSentiment,
    InsightClaim,
    ResearchGap,
    ResourceClass,
)
from xhs_food.domain_packs.food.decision import FoodDecisionPolicy
from xhs_food.domain_packs.food.preprocessing import (
    ProcessedComment,
    format_comments_for_llm,
    preprocess_comments,
)
from xhs_food.domain_packs.food.scoring import (
    ShopScore,
    calculate_scores,
    get_top_shops,
)
from xhs_food.prompts import (
    COMMENT_ANALYSIS_SYSTEM_PROMPT,
    COMMENT_ANALYSIS_USER_PROMPT,
)
from xhs_food.schemas import (
    RestaurantRecommendation,
    WanghongAnalysis,
    WanghongScore,
)

logger = logging.getLogger(__name__)
_FOOD_DECISION = FoodDecisionPolicy()

ResourceExecutor = Callable[..., Awaitable[Any]]


class _TokenLease:
    """One reservation held by :class:`TokenAwareLimiter`."""

    def __init__(self, limiter: TokenAwareLimiter, tokens: int) -> None:
        self._limiter = limiter
        self._tokens = tokens
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        # Use the limiter's public release boundary.  Besides keeping the
        # lease decoupled from implementation details, this lets architecture
        # checks distinguish injected resource ports from private state.
        await self._limiter.release_tokens(self._tokens)


class TokenAwareLimiter:
    """Bound concurrent LLM calls by both request count and token estimates.

    The limiter intentionally accepts an estimated token count rather than
    provider-specific usage metadata.  A reservation is released as soon as
    the corresponding provider call completes, so one AnalyzerAgent instance
    can safely share the budget across notes and calls.
    """

    def __init__(self, max_concurrency: int = 3, max_tokens: int | None = 8192) -> None:
        self.max_concurrency = max(1, int(max_concurrency))
        self.max_tokens = None if max_tokens is None else max(1, int(max_tokens))
        self._condition = asyncio.Condition()
        self._in_flight = 0
        self._in_flight_tokens = 0

    @property
    def in_flight(self) -> int:
        """Number of currently reserved requests (useful for observability/tests)."""
        return self._in_flight

    @property
    def in_flight_tokens(self) -> int:
        """Estimated tokens currently reserved by active requests."""
        return self._in_flight_tokens

    async def acquire(self, tokens: int = 1) -> _TokenLease:
        """Wait until a request can reserve its estimated token cost."""
        requested = max(1, int(tokens))
        reservation = (
            requested
            if self.max_tokens is None
            else min(requested, self.max_tokens)
        )
        async with self._condition:
            while self._in_flight >= self.max_concurrency or (
                self.max_tokens is not None
                and self._in_flight_tokens + reservation > self.max_tokens
            ):
                await self._condition.wait()
            self._in_flight += 1
            self._in_flight_tokens += reservation
        return _TokenLease(self, reservation)

    async def _release(self, tokens: int) -> None:
        async with self._condition:
            self._in_flight = max(0, self._in_flight - 1)
            self._in_flight_tokens = max(0, self._in_flight_tokens - tokens)
            self._condition.notify_all()

    async def release_tokens(self, tokens: int) -> None:
        """Release a reservation acquired through :meth:`acquire`."""

        await self._release(tokens)


@dataclass(slots=True)
class _BatchAnalysis:
    """Outcome of one independent comment batch."""

    batch_index: int
    comments: tuple[ProcessedComment, ...]
    estimated_tokens: int
    raw_output: str = ""
    results: list[dict[str, Any]] | None = None
    error: str | None = None
    retryable: bool = False
    failure_kind: str = ""
    missing_comment_ids: tuple[str, ...] = ()
    invalid_comment_ids: tuple[str, ...] = ()


class _NoopLease:
    async def release(self) -> None:
        return


class _ReleaseLease:
    """Adapt semaphore-style limiters to the analyzer's async lease API."""

    def __init__(self, release: Callable[[], Any] | None) -> None:
        self._release_callback = release
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self._release_callback is not None:
            value = self._release_callback()
            if inspect.isawaitable(value):
                await value


class _ContextLease:
    """Adapt an injected async context manager returned by a limiter."""

    def __init__(self, context_manager: Any) -> None:
        self._context_manager = context_manager
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        value = self._context_manager.__aexit__(None, None, None)
        if inspect.isawaitable(value):
            await value


class AnalyzeResult:
    """分析结果."""

    def __init__(
        self,
        success: bool,
        restaurants: list[RestaurantRecommendation] | None = None,
        shop_scores: dict[str, ShopScore] | None = None,
        raw_output: str = "",
        error: str | None = None,
        gaps: list[ResearchGap] | None = None,
        partial: bool = False,
        raw_comments: list[dict[str, Any]] | None = None,
        insights: list[CommentInsight] | None = None,
    ):
        self.success = success
        self.restaurants = restaurants or []
        self.shop_scores = shop_scores or {}
        self.raw_output = raw_output
        self.error = error
        self.gaps = list(gaps or [])
        self.partial = partial
        # Keep the normalized source objects available even when one batch
        # cannot be analyzed.  The list is never mutated by this pipeline.
        self.raw_comments = list(raw_comments or [])
        # Typed interpretations are additive to the historical restaurant
        # projection.  Raw comments and raw model output remain authoritative.
        self.insights = list(insights or [])


class AnalyzerAgent:
    """
    内容分析代理 - 三阶段流水线.

    Pipeline:
    1. preprocess_comments() -> ProcessedComment[] (含 interaction_score)
    2. LLM analyze          -> CommentAnalysis[] (语义标签)
    3. calculate_scores()   -> ShopScore[] (精确计算)
    """

    def __init__(
        self,
        llm_service: Any | None = None,
        *,
        analysis_batch_size: int = 30,
        max_comments: int | None = None,
        analysis_concurrency: int = 3,
        analysis_token_budget: int | None = 8192,
        limiter: Any | None = None,
        analysis_limiter: Any | None = None,
        token_estimator: Callable[[str], int] | None = None,
        token_budget: int | None = None,
        resource_executor: ResourceExecutor | Any | None = None,
    ) -> None:
        if limiter is not None and analysis_limiter is not None:
            raise ValueError("inject limiter or analysis_limiter, not both")
        if token_budget is not None:
            if analysis_token_budget != 8192 and analysis_token_budget != token_budget:
                raise ValueError("configure analysis_token_budget or token_budget, not both")
            analysis_token_budget = token_budget
        self._llm_service = llm_service
        self._resource_executor = resource_executor
        self._analysis_batch_size = max(1, analysis_batch_size)
        self._max_comments = max_comments
        self._analysis_concurrency = max(1, int(analysis_concurrency))
        self._token_estimator = token_estimator or self._default_token_estimator
        self._analysis_limiter = (
            limiter
            if limiter is not None
            else analysis_limiter
            if analysis_limiter is not None
            else TokenAwareLimiter(self._analysis_concurrency, analysis_token_budget)
        )
        # Keep a short alias for callers that used the resource name while
        # this capability was being introduced.
        self._limiter = self._analysis_limiter

    @property
    def resource_executor(self) -> ResourceExecutor | Any | None:
        """Physical-call boundary optionally injected by the runtime."""

        return self._resource_executor

    def set_resource_executor(self, executor: ResourceExecutor | Any | None) -> None:
        """Bind this analyzer to one run-scoped resource policy."""

        self._resource_executor = executor

    async def _get_llm_service(self) -> Any:
        """懒加载 LLM 服务."""
        if self._llm_service is None:
            from xhs_food.services.llm_service import LLMService

            self._llm_service = LLMService()
        return self._llm_service

    async def analyze(
        self,
        title: str,
        content: str,
        comments: list[Any],
        exclude_keywords: list[str],
        note_id: str = "",
        *,
        resource_executor: ResourceExecutor | Any | None = None,
    ) -> AnalyzeResult:
        """分析笔记内容和评论 (入口方法)."""
        return await self._analyze_pipeline(
            title,
            content,
            comments,
            exclude_keywords,
            note_id,
            resource_executor=resource_executor,
        )

    async def _analyze_pipeline(
        self,
        title: str,
        content: str,
        comments: list[Any],
        exclude_keywords: list[str],
        note_id: str = "",
        *,
        resource_executor: ResourceExecutor | Any | None = None,
    ) -> AnalyzeResult:
        """
        三阶段流水线分析.

        Stage 1: Python 预处理
        Stage 2: LLM 语义分析 (简化 Prompt)
        Stage 3: Python 后处理计分
        """
        try:
            # ============================================================
            # Stage 1: 预处理 - Python 端计算 interaction_score
            # ============================================================
            normalized_comments = self._normalize_comments(comments)
            analysis_comments, input_gaps = self._deduplicate_analysis_comments(
                normalized_comments
            )
            processed = preprocess_comments(
                analysis_comments,
                max_comments=self._max_comments,
            )

            if not processed:
                return AnalyzeResult(
                    success=True,
                    restaurants=[],
                    shop_scores={},
                    raw_comments=normalized_comments,
                    insights=[],
                    gaps=input_gaps,
                    partial=bool(input_gaps),
                )

            logger.debug(f"Stage 1: 预处理完成, {len(processed)} 条评论")

            # ============================================================
            # Stage 2: LLM 语义分析 - 仅判断语义标签
            # ============================================================
            llm = await self._get_llm_service()
            from langchain_core.messages import HumanMessage, SystemMessage  # noqa: I001  # pyright: ignore[reportMissingImports]

            # Analyze every comment exactly once, in bounded batches.  The
            # source payload remains untouched; batching only controls prompt
            # size and latency.
            batches = [
                processed[start : start + self._analysis_batch_size]
                for start in range(0, len(processed), self._analysis_batch_size)
            ]
            batch_outcomes = await asyncio.gather(
                *(
                    self._analyze_batch(
                        batch_index=batch_index,
                        batch=batch,
                        llm=llm,
                        message_types=(SystemMessage, HumanMessage),
                        resource_executor=(
                            resource_executor
                            if resource_executor is not None
                            else self._resource_executor
                        ),
                    )
                    for batch_index, batch in enumerate(batches)
                )
            )

            # ``gather`` returns values in task creation order, independently
            # of completion order.  Flattening this list is therefore the
            # deterministic batch-index merge required by the runtime.
            llm_results: list[dict[str, Any]] = []
            result_batch_indices: list[int] = []
            raw_outputs: list[str] = []
            gaps: list[ResearchGap] = list(input_gaps)
            failures: list[_BatchAnalysis] = []
            for outcome in batch_outcomes:
                if outcome.raw_output:
                    raw_outputs.append(outcome.raw_output)
                # Keep valid claims from a structurally incomplete response;
                # the missing portion is represented by the typed gap below.
                batch_results = outcome.results or []
                llm_results.extend(batch_results)
                result_batch_indices.extend(
                    outcome.batch_index for _ in batch_results
                )
                if outcome.error is not None:
                    failures.append(outcome)
                    gaps.append(self._batch_gap(outcome, note_id))
                    continue

            raw_output = "\n".join(raw_outputs)
            if not llm_results and raw_outputs:
                # Preserve the historical all-invalid response contract while
                # exposing the new per-batch typed gaps to callers.
                return AnalyzeResult(
                    success=False,
                    raw_output=raw_output,
                    error="Failed to parse JSON from LLM output",
                    gaps=gaps,
                    raw_comments=normalized_comments,
                    insights=[],
                )

            if not llm_results and failures:
                first_failure = failures[0]
                return AnalyzeResult(
                    success=False,
                    raw_output=raw_output,
                    error=first_failure.error,
                    gaps=gaps,
                    raw_comments=normalized_comments,
                    insights=[],
                )

            logger.debug(f"Stage 2: LLM 分析完成, {len(llm_results)} 条结果")

            # ============================================================
            # Stage 3: 后处理计分 - Python 端精确计算
            # ============================================================
            shop_scores = calculate_scores(llm_results, processed)

            # 不限制数量，返回所有满足条件的店铺
            top_shops = get_top_shops(shop_scores, min_mentions=1, top_n=999)

            logger.info(
                f"Stage 3: 计分完成, 识别 {len(shop_scores)} 家店铺, 返回 {len(top_shops)} 家"
            )

            # 转换为 RestaurantRecommendation 格式
            restaurants = self._convert_to_recommendations(top_shops, note_id, exclude_keywords)

            insights = self._build_insights(
                llm_results,
                processed,
                normalized_comments,
                note_id=note_id,
                batch_indices=result_batch_indices,
                gaps=gaps,
            )

            return AnalyzeResult(
                success=True,
                restaurants=restaurants,
                shop_scores=shop_scores,
                raw_output=raw_output,
                error=failures[0].error if failures else None,
                gaps=gaps,
                partial=bool(gaps),
                raw_comments=normalized_comments,
                insights=insights,
            )

        except Exception as e:
            logger.exception("Pipeline 分析失败")
            # Normalization may already have found duplicate/malformed source
            # rows before a later provider/parser error. Keep those typed gaps
            # and the complete normalized input available for retry/audit.
            try:
                fallback_comments = self._normalize_comments(comments)
                _, fallback_gaps = self._deduplicate_analysis_comments(
                    fallback_comments
                )
            except Exception:  # noqa: BLE001 - defensive error boundary
                fallback_comments = []
                fallback_gaps = []
            return AnalyzeResult(
                success=False,
                error=str(e),
                gaps=fallback_gaps,
                partial=bool(fallback_gaps),
                raw_comments=fallback_comments,
                insights=[],
            )

    def _build_insights(
        self,
        llm_results: list[dict[str, Any]],
        processed: list[ProcessedComment],
        normalized_comments: list[dict[str, Any]],
        *,
        note_id: str,
        batch_indices: list[int],
        gaps: list[ResearchGap],
    ) -> list[CommentInsight]:
        """Convert model labels into typed, evidence-addressable insights.

        The conversion is deliberately a best-effort projection.  A malformed
        model item creates a typed gap while the corresponding source comment
        and raw model response remain available to retry/audit.
        """

        if not note_id:
            # Some unit-level callers analyze an isolated comment without a
            # source note.  Do not invent a citation that could be published.
            return []
        processed_by_id = {item.id: item for item in processed}
        raw_by_id: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(normalized_comments):
            raw_id = item.get("id") or item.get("comment_id") or item.get("commentId")
            if raw_id is not None:
                raw_by_id.setdefault(str(raw_id), item)
            elif index < len(processed):
                raw_by_id.setdefault(processed[index].id, item)

        insights: list[CommentInsight] = []
        for index, raw_result in enumerate(llm_results):
            if not isinstance(raw_result, dict):
                continue
            comment_id_value = raw_result.get("id") or raw_result.get("comment_id")
            if comment_id_value is None:
                gaps.append(
                    self._insight_gap(
                        note_id,
                        "comment_id_missing",
                        {"result_index": index},
                    )
                )
                continue
            comment_id = str(comment_id_value)
            if comment_id not in processed_by_id:
                # The batch validator normally catches this.  Keep this guard
                # at the contract boundary for custom analyzer subclasses.
                gaps.append(
                    self._insight_gap(
                        note_id,
                        "comment_not_in_batch",
                        {"comment_id": comment_id, "result_index": index},
                    )
                )
                continue
            evidence = f"xhs:note:{note_id}:comment:{comment_id}"
            identity = _enum_or_default(
                CommentIdentity,
                raw_result.get("identity"),
                CommentIdentity.NONE,
            )
            sentiment = _enum_or_default(
                CommentSentiment,
                raw_result.get("sentiment"),
                CommentSentiment.NEUTRAL,
            )
            # ``mentioned_shops`` is the canonical contract field; accept the
            # documented ``shop_mentions`` alias at this boundary too because
            # custom model adapters may return the wire alias directly.
            shops = _string_tuple(
                raw_result.get("mentioned_shops")
                if "mentioned_shops" in raw_result
                else raw_result.get("shop_mentions")
            )
            dishes = _string_tuple(
                raw_result.get("mentioned_dishes")
                or raw_result.get("dish_mentions")
            )
            claims = _claims_from_result(raw_result, evidence)
            # A model may attach a more specific source locator to a claim.
            # Keep that locator on the insight contract instead of rejecting
            # the whole comment projection; the canonical comment reference
            # remains present as the minimum citation.
            insight_evidence_refs = tuple(
                dict.fromkeys(
                    (
                        evidence,
                        *(ref for claim in claims for ref in claim.evidence_refs),
                    )
                )
            )
            confidence = _optional_confidence(raw_result.get("confidence"))
            metadata: dict[str, Any] = {}
            for key in ("correction_text", "reason", "signals", "controversy"):
                if raw_result.get(key) not in (None, "", [], {}):
                    metadata[key] = raw_result[key]
            metadata["processed_interaction_score"] = processed_by_id[
                comment_id
            ].interaction_score
            try:
                insight = CommentInsight(
                    note_id=note_id,
                    comment_id=comment_id,
                    batch_index=(
                        batch_indices[index]
                        if index < len(batch_indices)
                        else 0
                    ),
                    identity=identity,
                    sentiment=sentiment,
                    is_correction=bool(
                        raw_result.get("is_correction", raw_result.get("correction", False))
                    ),
                    mentioned_shops=shops,
                    mentioned_dishes=dishes,
                    claims=claims,
                    evidence_refs=insight_evidence_refs,
                    confidence=confidence,
                    raw_payload={
                        "analysis": dict(raw_result),
                        "comment": raw_by_id.get(comment_id),
                    },
                    metadata=metadata,
                )
            except Exception as exc:  # noqa: BLE001 - isolate one bad item
                gaps.append(
                    self._insight_gap(
                        note_id,
                        "insight_contract_invalid",
                        {
                            "comment_id": comment_id,
                            "error": type(exc).__name__,
                        },
                    )
                )
                continue
            insights.append(insight)
        return insights

    @staticmethod
    def _insight_gap(
        note_id: str,
        code: str,
        details: dict[str, Any],
    ) -> ResearchGap:
        return ResearchGap(
            source="agent",
            operation="comments.insight",
            code=code,
            message="comment insight could not be represented by the typed contract",
            retryable=False,
            details={"note_id": note_id, **details},
        )

    async def _analyze_batch(
        self,
        *,
        batch_index: int,
        batch: list[ProcessedComment],
        llm: Any,
        message_types: tuple[Any, Any],
        resource_executor: ResourceExecutor | Any | None = None,
    ) -> _BatchAnalysis:
        """Analyze one batch and isolate provider/response failures."""

        comments_text = format_comments_for_llm(batch)
        system_message, human_message = message_types
        messages = [
            system_message(content=COMMENT_ANALYSIS_SYSTEM_PROMPT),
            human_message(content=COMMENT_ANALYSIS_USER_PROMPT.format(comments=comments_text)),
        ]
        estimated_tokens = self._estimate_batch_tokens(comments_text)
        lease: Any = _NoopLease()
        try:
            lease = await self._acquire_limiter(estimated_tokens)
            executor = resource_executor
            if executor is None:
                response = await llm.call(messages)
            elif hasattr(executor, "execute"):
                value = executor.execute(ResourceClass.LLM, llm.call, messages)
                response = await value if inspect.isawaitable(value) else value
            else:
                value = executor(ResourceClass.LLM, llm.call, messages)
                response = await value if inspect.isawaitable(value) else value
            raw_output = response.content if hasattr(response, "content") else str(response)
            if not isinstance(raw_output, str):
                raw_output = str(raw_output)
            parsed = extract_json(raw_output)
            if parsed is None:
                logger.warning("LLM 输出 JSON 解析失败 for batch index %s", batch_index)
                return _BatchAnalysis(
                    batch_index=batch_index,
                    comments=tuple(batch),
                    estimated_tokens=estimated_tokens,
                    raw_output=raw_output,
                    error="Failed to parse JSON from LLM output",
                    failure_kind="invalid_json",
                )
            if not isinstance(parsed, dict) or not isinstance(parsed.get("results"), list):
                logger.warning("LLM 输出 results 字段无效 for batch index %s", batch_index)
                return _BatchAnalysis(
                    batch_index=batch_index,
                    comments=tuple(batch),
                    estimated_tokens=estimated_tokens,
                    raw_output=raw_output,
                    error="LLM output results must be a list",
                    failure_kind="invalid_output",
                )
            batch_results = parsed["results"]
            expected_ids = tuple(comment.id for comment in batch)
            expected_id_set = set(expected_ids)
            results_by_id: dict[str, dict[str, Any]] = {}
            invalid_ids: list[str] = []
            duplicate_ids: list[str] = []
            for item in batch_results:
                if not isinstance(item, dict):
                    invalid_ids.append("")
                    continue
                item_id = item.get("id") or item.get("comment_id")
                normalized_id = str(item_id) if item_id is not None else ""
                if normalized_id not in expected_id_set:
                    invalid_ids.append(normalized_id)
                    continue
                if normalized_id in results_by_id:
                    duplicate_ids.append(normalized_id)
                    continue
                normalized_item = dict(item)
                # The scoring layer uses ``id`` as its stable join key.  Accept
                # the contract's comment_id alias, but always reduce to one
                # canonical representation before scoring.
                normalized_item["id"] = normalized_id
                results_by_id[normalized_id] = normalized_item

            valid_results = [
                results_by_id[comment_id]
                for comment_id in expected_ids
                if comment_id in results_by_id
            ]
            missing_comment_ids = tuple(
                comment_id for comment_id in expected_ids if comment_id not in results_by_id
            )
            invalid_comment_ids = tuple(
                item_id
                for item_id in (*invalid_ids, *duplicate_ids)
                if item_id
            )
            invalid_result_count = len(invalid_ids) + len(duplicate_ids)
            if missing_comment_ids or invalid_result_count:
                if invalid_result_count:
                    reason = "LLM output contains invalid or duplicate comment results"
                else:
                    reason = "LLM output omitted one or more comment results"
                return _BatchAnalysis(
                    batch_index=batch_index,
                    comments=tuple(batch),
                    estimated_tokens=estimated_tokens,
                    raw_output=raw_output,
                    results=valid_results,
                    error=reason,
                    failure_kind=("invalid_item" if invalid_result_count else "incomplete_output"),
                    missing_comment_ids=missing_comment_ids,
                    invalid_comment_ids=invalid_comment_ids,
                )
            return _BatchAnalysis(
                batch_index=batch_index,
                comments=tuple(batch),
                estimated_tokens=estimated_tokens,
                raw_output=raw_output,
                results=valid_results,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - isolate one batch failure
            logger.warning("LLM 评论批次 %s 分析失败: %s", batch_index, exc)
            failure_kind, retryable = self._classify_batch_exception(exc)
            return _BatchAnalysis(
                batch_index=batch_index,
                comments=tuple(batch),
                estimated_tokens=estimated_tokens,
                error=str(exc) or type(exc).__name__,
                retryable=retryable,
                failure_kind=failure_kind,
            )
        finally:
            try:
                await lease.release()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a release must not hide analysis output
                logger.exception("释放评论分析 limiter 失败 for batch index %s", batch_index)

    def _estimate_batch_tokens(self, comments_text: str) -> int:
        """Estimate the request cost used by the token-aware limiter."""
        try:
            estimated = self._token_estimator(comments_text)
        except Exception:  # noqa: BLE001 - fallback keeps limiting fail-safe
            logger.warning("评论分析 token 估算失败，使用字符长度回退值", exc_info=True)
            estimated = self._default_token_estimator(comments_text)
        try:
            return max(1, int(estimated))
        except (TypeError, ValueError):
            return self._default_token_estimator(comments_text)

    @staticmethod
    def _default_token_estimator(text: str) -> int:
        """Conservative provider-independent approximation for prompt tokens."""
        return max(1, math.ceil(len(text) / 4))

    async def _acquire_limiter(self, estimated_tokens: int) -> Any:
        """Acquire either the built-in limiter or a test/application adapter.

        Semaphore-style ``acquire()/release()`` objects and limiters exposing
        ``limit(tokens)`` are both accepted so callers can inject their own
        resource pool without coupling it to this legacy Agent API.
        """
        limiter: Any = self._analysis_limiter
        acquire = getattr(limiter, "acquire", None)
        if acquire is not None:
            try:
                acquired = acquire(estimated_tokens)
            except TypeError:
                acquired = acquire()
            if inspect.isawaitable(acquired):
                acquired = await acquired
            if hasattr(acquired, "__aenter__") and hasattr(acquired, "__aexit__"):
                entered = acquired.__aenter__()
                if inspect.isawaitable(entered):
                    await entered
                return _ContextLease(acquired)
            if hasattr(acquired, "release"):
                return _ReleaseLease(acquired.release)
            return _ReleaseLease(getattr(limiter, "release", None))

        limit = getattr(limiter, "limit", None)
        if limit is not None:
            context_manager = limit(estimated_tokens)
            if inspect.isawaitable(context_manager):
                context_manager = await context_manager
            entered = context_manager.__aenter__()
            if inspect.isawaitable(entered):
                await entered
            return _ContextLease(context_manager)

        if hasattr(limiter, "__aenter__") and hasattr(limiter, "__aexit__"):
            entered = limiter.__aenter__()
            if inspect.isawaitable(entered):
                await entered
            return _ContextLease(limiter)

        return _NoopLease()

    @staticmethod
    def _batch_gap(batch: _BatchAnalysis, note_id: str) -> ResearchGap:
        """Create a typed, loss-aware gap for one failed comment batch."""
        failure_kind = batch.failure_kind or "unknown"
        # Keep the historical generic code for ordinary provider failures,
        # while making runtime policy failures actionable to the planner.
        code = (
            failure_kind
            if failure_kind.startswith("budget_")
            or failure_kind in {"resource_timeout", "circuit_open"}
            else "analysis_batch_failed"
        )
        return ResearchGap(
            source="agent",
            operation="comments.analyze",
            code=code,
            message=batch.error or "comment analysis batch failed",
            retryable=batch.retryable,
            details={
                "note_id": note_id,
                "batch_index": batch.batch_index,
                "comment_ids": [comment.id for comment in batch.comments],
                "comment_count": len(batch.comments),
                "missing_comment_ids": list(batch.missing_comment_ids),
                "invalid_comment_ids": list(batch.invalid_comment_ids),
                "estimated_tokens": batch.estimated_tokens,
                "failure_kind": batch.failure_kind or "unknown",
            },
        )

    @staticmethod
    def _classify_batch_exception(exc: BaseException) -> tuple[str, bool]:
        """Map runtime resource errors without importing the runtime layer.

        The analyzer is intentionally usable on its own, so this boundary
        relies on the small exception protocol (class name, ``dimension`` and
        ``retryable`` attributes) rather than coupling the Agent to a concrete
        resource-pool implementation.
        """

        name = type(exc).__name__
        if name == "BudgetExceededError" or hasattr(exc, "dimension"):
            dimension = str(getattr(exc, "dimension", "budget") or "budget")
            dimension = "".join(
                character if character.isalnum() or character == "_" else "_"
                for character in dimension
            ).strip("_") or "budget"
            return f"budget_{dimension}_exhausted", False
        if name in {"ResourceCallTimeoutError", "TimeoutError", "asyncio.TimeoutError"} or isinstance(
            exc, TimeoutError
        ):
            return "resource_timeout", bool(getattr(exc, "retryable", True))
        if name == "ResourceCircuitOpenError" or hasattr(exc, "resource_class"):
            return "circuit_open", bool(getattr(exc, "retryable", True))
        return "provider_exception", bool(getattr(exc, "retryable", True))

    def _normalize_comments(self, comments: list[Any]) -> list[dict[str, Any]]:
        """将评论统一转换为字典格式."""
        normalized = []
        for c in comments:
            if isinstance(c, str):
                normalized.append({"text": c})
            elif isinstance(c, dict):
                normalized.append(c)
            else:
                normalized.append({"text": str(c)})
        return normalized

    def _deduplicate_analysis_comments(
        self,
        comments: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[ResearchGap]]:
        """Deduplicate only the model view while retaining the raw input.

        Providers can repeat a comment across overlapping cursor pages.  The
        evidence ledger must retain every raw occurrence, but scoring the same
        stable id twice would silently inflate a shop.  Pick the richest row
        deterministically and expose the discarded occurrence as a typed gap.
        """

        selected: dict[str, tuple[int, dict[str, Any]]] = {}
        order: list[str] = []
        gaps: list[ResearchGap] = []
        occurrences: dict[str, int] = {}
        for index, comment in enumerate(comments):
            raw_id = comment.get("id") or comment.get("comment_id") or comment.get("commentId")
            # ``preprocess_comments`` supplies a deterministic positional id
            # for id-less records; those rows cannot collide here.
            key = (
                f"__index__:{index}"
                if raw_id is None or not str(raw_id).strip()
                else str(raw_id)
            )
            occurrences[key] = occurrences.get(key, 0) + 1
            if key not in selected:
                selected[key] = (index, comment)
                order.append(key)
                continue
            previous_index, previous = selected[key]
            if self._comment_row_rank(comment) > self._comment_row_rank(previous):
                selected[key] = (index, comment)
            # Keep the original source order for unique ids; the richer row
            # replaces only the analysis payload, never the raw list.
            _ = previous_index

        for key, count in occurrences.items():
            if count > 1 and not key.startswith("__index__:"):
                gaps.append(
                    ResearchGap(
                        source="agent",
                        operation="comments.analyze",
                        code="duplicate_comment_id",
                        message="duplicate comment id was reduced for analysis",
                        retryable=False,
                        details={"comment_id": key, "occurrences": count},
                    )
                )
        return [selected[key][1] for key in order], gaps

    @staticmethod
    def _comment_row_rank(comment: dict[str, Any]) -> tuple[int, str]:
        """Prefer a row with more source detail, then resolve ties stably."""

        encoded = json.dumps(
            comment,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return len(encoded), encoded

    def _convert_to_recommendations(
        self,
        shops: list[ShopScore],
        note_id: str,
        exclude_keywords: list[str],
    ) -> list[RestaurantRecommendation]:
        """将 ShopScore 转换为 RestaurantRecommendation."""
        recommendations = []

        for shop in shops:
            decision = _FOOD_DECISION.assess_shop(shop, exclude_keywords)
            wh_score = WanghongScore(decision.score)

            wanghong = WanghongAnalysis(
                score=wh_score,
                confidence=decision.confidence,
                reasons=list(decision.reasons),
                has_local_mentions=decision.has_local_mentions,
                has_years_mentioned=False,  # 暂不支持
            )

            rec = RestaurantRecommendation(
                name=shop.name,
                location=None,
                features=[f"评论权重得分: {shop.total_score:.1f}"] + shop.reasons,
                source_notes=[note_id] if note_id else [],
                confidence=decision.confidence,
                wanghong_analysis=wanghong,
                is_recommended=decision.is_recommended,
                filter_reason=decision.filter_reason,
            )
            recommendations.append(rec)

        return recommendations


def _enum_or_default(enum_type: Any, value: Any, default: Any) -> Any:
    """Parse an LLM label without allowing one bad label to drop a batch."""

    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip().casefold())
    except (TypeError, ValueError):
        return default


def _string_tuple(value: Any) -> tuple[str, ...]:
    """Normalize model lists while preserving order and removing empties."""

    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, (list, tuple)):
        values = tuple(value)
    elif isinstance(value, (set, frozenset)):
        # Provider/model sets are unordered; sorting their string form makes
        # the normalized contract reproducible across processes.
        values = tuple(sorted(value, key=lambda item: str(item)))
    else:
        values = ()
    output: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return tuple(output)


def _claims_from_result(
    result: dict[str, Any], evidence_ref: str
) -> tuple[InsightClaim, ...]:
    """Create stable claims from optional provider/model claim projections."""

    raw_claims = result.get("claims")
    if isinstance(raw_claims, (str, dict)):
        raw_claims = [raw_claims]
    if not isinstance(raw_claims, (list, tuple)):
        return ()
    claims: list[InsightClaim] = []
    for index, raw_claim in enumerate(raw_claims):
        if isinstance(raw_claim, dict):
            text = str(
                raw_claim.get("text")
                or raw_claim.get("claim")
                or raw_claim.get("content")
                or ""
            ).strip()
            attributes = {
                str(key): value
                for key, value in raw_claim.items()
                if key not in {"text", "claim", "content", "claim_id", "id", "evidence_ref", "evidence_refs"}
            }
            claim_id = str(raw_claim.get("claim_id") or raw_claim.get("id") or "").strip()
            refs = _string_tuple(raw_claim.get("evidence_refs"))
            explicit_ref = raw_claim.get("evidence_ref")
            if explicit_ref:
                refs = tuple(dict.fromkeys((*refs, str(explicit_ref))))
        else:
            text = str(raw_claim).strip()
            attributes = {}
            claim_id = ""
            refs = ()
        if not text:
            continue
        stable_id = claim_id or f"{evidence_ref}:claim:{index}"
        claims.append(
            InsightClaim(
                claim_id=stable_id,
                text=text,
                evidence_refs=tuple(dict.fromkeys((evidence_ref, *refs))),
                attributes=attributes,
            )
        )
    return tuple(claims)


def _optional_confidence(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None
