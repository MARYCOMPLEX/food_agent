"""Food semantics for the shared, observation-driven research loop.

This module is deliberately an adapter, rather than another workflow.  It
describes the Food ontology and turns provider-neutral observations into the
standard claim/entity/gap projection consumed by a shared investigation
runtime.  Follow-up work is emitted from the current projection; there is no
fixed phase graph here.

The current runtime calls its provider envelope ``SourceEnvelope``.  The
adapter owns the small ``ObservationEnvelope`` compatibility model so it can
also be used by a newer generic loop without making that loop import Food or
provider classes.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, cast, runtime_checkable

from xhs_food.contracts import (
    ContractPayload,
    InsightClaim,
    ResearchGap,
    SourceEnvelope,
)
from xhs_food.contracts.adaptive_investigation import (
    AliasChoices,
    ConfigDict,
    Field,
    ObservationCompleteness,
    ObservationOutcome,
    PlanAction,
    PlanActionKind,
    model_validator,
)
from xhs_food.contracts.adaptive_investigation import (
    ObservationEnvelope as AdaptiveObservationEnvelope,
)
from xhs_food.contracts.base import JsonValue

OBSERVATION_ENVELOPE_SCHEMA_VERSION = "adaptive-observation/v1"
FOOD_ADAPTATION_SCHEMA_VERSION = "food-adaptation/v1"
CAPABILITY_ACTION_SCHEMA_VERSION = "capability-action/v1"

# These are the public fields exposed by the current account-service MCP
# descriptors.  Domain context belongs on ``CapabilityAction.metadata``;
# putting it in ``arguments`` makes a valid semantic action fail strict MCP
# input validation before it reaches the provider.
_XHS_SEARCH_ARGUMENTS = frozenset(
    {"query", "count", "sort_type", "include_details", "include_comments", "max_comments"}
)
_XHS_COMMENTS_ARGUMENTS = frozenset(
    {"note_id", "max_comments", "include_replies"}
)
_DIANPING_SEARCH_ARGUMENTS = frozenset(
    {
        "keyword",
        "city_id",
        "channel_id",
        "category_id",
        "region_id",
        "sort",
        "min_price",
        "max_price",
        "page",
    }
)
_DIANPING_DETAIL_ARGUMENTS = frozenset({"shop_id", "detail_url", "timeout_seconds"})
_DIANPING_REVIEWS_ARGUMENTS = frozenset(
    {"shop_id", "offset", "sort", "review_filter", "tag_name", "timeout_seconds"}
)


_MCP_WRAPPER_KEYS = ("structuredContent", "structured_content", "content")
_PROVIDER_CONTAINER_KEYS = (
    "data",
    "detail",
    "comments",
    "reviews",
    "notes",
    "search_items",
    "items",
    "records",
    "results",
    "shop",
    "pagination",
    "page_info",
    "pageInfo",
    "paging",
    "completeness",
    "continuation",
    "protocol",
    "meta",
    "response",
    "result",
    "payload",
    "body",
)


def _unwrap_mcp_payload(value: Any, *, _depth: int = 0) -> Any:
    """Return the provider JSON from common MCP result wrappers.

    Account services expose ``content`` as a list of typed MCP blocks.  Some
    callers hand this adapter the JSON-RPC ``result``/``structuredContent``
    wrapper instead, so the unwrap is intentionally recursive and bounded.
    The caller retains the original value as ``raw_payload``.
    """

    if _depth > 8:
        return value
    if isinstance(value, str):
        candidate = value.strip()
        if candidate.startswith(("{", "[")):
            try:
                return _unwrap_mcp_payload(json.loads(candidate), _depth=_depth + 1)
            except json.JSONDecodeError:
                return value
        return value
    if isinstance(value, Mapping):
        # A raw MCP content block may be passed without its surrounding list.
        if value.get("type") == "json" and "json" in value:
            return _unwrap_mcp_payload(value["json"], _depth=_depth + 1)
        if value.get("type") == "text" and "text" in value:
            return _unwrap_mcp_payload(value["text"], _depth=_depth + 1)

        for key in ("structuredContent", "structured_content"):
            if key in value and value[key] is not None:
                return _unwrap_mcp_payload(value[key], _depth=_depth + 1)

        result = value.get("result")
        if isinstance(result, Mapping) and any(
            key in result for key in _MCP_WRAPPER_KEYS
        ):
            return _unwrap_mcp_payload(result, _depth=_depth + 1)

        content = value.get("content")
        if isinstance(content, (list, tuple)):
            for block in content:
                if isinstance(block, Mapping) and block.get("type") == "json" and "json" in block:
                    return _unwrap_mcp_payload(block["json"], _depth=_depth + 1)
            for block in content:
                if isinstance(block, Mapping) and block.get("type") == "text" and "text" in block:
                    parsed = _unwrap_mcp_payload(block["text"], _depth=_depth + 1)
                    if parsed is not block["text"]:
                        return parsed
            if len(content) == 1 and isinstance(content[0], Mapping):
                return _unwrap_mcp_payload(content[0], _depth=_depth + 1)
    if isinstance(value, (list, tuple)) and len(value) == 1 and isinstance(value[0], Mapping):
        block = value[0]
        if block.get("type") in {"json", "text"}:
            return _unwrap_mcp_payload(block, _depth=_depth + 1)
    return value


def _values_at_path(value: Any, path: Sequence[str]) -> tuple[Any, ...]:
    """Read a path through mappings while treating lists as implicit wildcards."""

    if not path:
        return (value,)
    if isinstance(value, (list, tuple)):
        values: list[Any] = []
        for item in value:
            values.extend(_values_at_path(item, path))
        return tuple(values)
    if not isinstance(value, Mapping) or path[0] not in value:
        return ()
    return _values_at_path(value[path[0]], path[1:])


def _rows_at_paths(
    value: Any,
    paths: Sequence[Sequence[str]],
    *,
    allow_mapping: bool = False,
) -> tuple[bool, tuple[Any, ...]]:
    """Return the first explicitly present provider collection.

    The boolean distinguishes an explicit empty page from an unknown shape;
    this matters for completeness and prevents a failed empty comments page
    from falling through to an unrelated detail item.
    """

    for path in paths:
        empty_collection = False
        rows: list[Any] = []
        for candidate in _values_at_path(value, tuple(path)):
            if isinstance(candidate, (list, tuple)):
                if candidate:
                    rows.extend(candidate)
                else:
                    empty_collection = True
            elif allow_mapping and isinstance(candidate, Mapping):
                rows.append(candidate)
        if rows:
            return True, tuple(rows)
        if empty_collection:
            return True, ()
    return False, ()


def _comment_row_shape(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    has_text = any(key in value for key in ("content", "text", "comment", "body"))
    has_identity = any(
        value.get(key) not in (None, "")
        for key in ("id", "comment_id", "commentId", "review_id", "reviewId")
    )
    return has_text and has_identity


def _looks_like_provider_payload(value: Any, *, operation: str | None = None) -> bool:
    if not isinstance(value, Mapping):
        return False
    # Keep this iterative so a partially imported/reloaded module cannot hit a
    # recursive global lookup while an MCP payload is being normalized.
    pending: list[Mapping[str, Any]] = [value]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        if any(key in current for key in ("content", "structuredContent", "structured_content")):
            return True
        if any(
            key in current
            for key in (
                "search_items",
                "detail",
                "comments",
                "reviews",
                "shop",
                "pagination",
                "completeness",
                "raw_response",
                "raw_responses",
            )
        ):
            return True
        if "items" in current and str(operation or "").casefold() in {
            "notes.search",
            "notes.detail",
            "comments.search",
            "places.search",
            "places.detail",
            "reviews.search",
        }:
            return True
        for key in ("data", "detail", "result", "payload", "body", "response"):
            nested = current.get(key)
            if isinstance(nested, Mapping):
                pending.append(nested)
    return False


def _json_compatible(value: Any) -> Any:
    """Convert tuple/set containers used by compatibility callers to JSON lists."""

    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_compatible(item) for item in value]
    return value


def _provider_item_paths(operation: str | None) -> tuple[tuple[str, ...], ...]:
    op = str(operation or "").casefold()
    if op.startswith("comments."):
        return (
            ("comments", "items"),
            ("comments", "comments"),
            ("comments",),
            ("detail", "comments", "items"),
            ("detail", "data", "comments", "items"),
            ("notes", "comments", "items"),
            ("notes", "comments"),
            ("items",),
            ("data", "items"),
        )
    if op == "notes.detail":
        return (
            ("detail", "data", "items"),
            ("detail", "items"),
            ("items",),
            ("notes",),
            ("search_items",),
            ("data", "items"),
        )
    if op == "notes.search":
        return (
            ("search_items",),
            ("notes",),
            ("items",),
            ("data", "items"),
            ("detail", "data", "items"),
        )
    if op == "places.detail":
        return (
            ("shop",),
            ("data", "shop"),
            ("detail", "shop"),
            ("items",),
            ("data", "items"),
        )
    if op == "places.search":
        return (
            ("items",),
            ("results",),
            ("shops",),
            ("pois",),
            ("data", "items"),
        )
    if op == "reviews.search":
        return (
            ("reviews", "items"),
            ("reviews",),
            ("items",),
            ("data", "reviews", "items"),
            ("data", "items"),
        )
    return (
        ("items",),
        ("search_items",),
        ("comments", "items"),
        ("reviews", "items"),
        ("comments",),
        ("reviews",),
        ("shop",),
        ("notes",),
        ("records",),
        ("results",),
        ("data", "items"),
        ("data",),
    )


def provider_items(value: Any, *, operation: str | None = None) -> tuple[Any, ...]:
    """Project provider rows from MCP/XHS/Dianping response shapes.

    This is deliberately a small shape adapter.  It does not mutate rows or
    strip provider fields; ``raw_payload`` remains the complete response.
    """

    payload = _unwrap_mcp_payload(value)
    if isinstance(payload, (list, tuple)):
        return tuple(payload)
    if not isinstance(payload, Mapping):
        return ()

    op = str(operation or "").casefold()
    paths = _provider_item_paths(op)
    allow_mapping = op in {"places.detail", ""}

    found, rows = _rows_at_paths(payload, paths, allow_mapping=allow_mapping)
    if found:
        return rows
    if _comment_row_shape(payload):
        return (payload,)
    return ()


def provider_comment_items(value: Any, *, operation: str | None = None) -> tuple[Mapping[str, Any], ...]:
    """Collect comments nested inside XHS note search/detail responses."""

    if not str(operation or "").casefold().startswith("notes."):
        return ()
    payload = _unwrap_mcp_payload(value)
    paths = (
        ("comments", "items"),
        ("comments", "comments"),
        ("comments",),
        ("notes", "comments", "items"),
        ("notes", "comments", "comments"),
        ("notes", "comments"),
        ("notes", "detail", "comments", "items"),
        ("notes", "detail", "comments"),
        ("notes", "detail", "data", "comments", "items"),
        ("search_items", "comments", "items"),
        ("search_items", "comments", "comments"),
        ("search_items", "comments"),
        ("search_items", "detail", "comments", "items"),
        ("search_items", "detail", "comments"),
        ("detail", "comments", "items"),
        ("detail", "comments", "comments"),
        ("detail", "comments"),
        ("detail", "data", "items", "comments", "items"),
        ("detail", "data", "items", "comments"),
    )
    rows: list[Mapping[str, Any]] = []
    for path in paths:
        found, candidates = _rows_at_paths(payload, (path,))
        if found:
            rows.extend(
                candidate
                for candidate in candidates
                if isinstance(candidate, Mapping)
            )

    unique: list[Mapping[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        comment_id = next(
            (
                _scalar_text(row.get(key))
                for key in ("comment_id", "commentId", "id", "external_id")
                if _scalar_text(row.get(key)) is not None
            ),
            None,
        )
        note_id = next(
            (
                _scalar_text(row.get(key))
                for key in ("note_id", "noteId", "document_id", "documentId")
                if _scalar_text(row.get(key)) is not None
            ),
            None,
        )
        if comment_id is not None:
            identity = ("id", note_id or "", comment_id)
        else:
            identity = (
                "payload",
                json.dumps(_json_compatible(row), ensure_ascii=True, sort_keys=True, default=str),
            )
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(row)
    return tuple(unique)


def _provider_shop_items(value: Any) -> tuple[Mapping[str, Any], ...]:
    """Read a Dianping shop object without confusing review rows for a shop."""

    payload = _unwrap_mcp_payload(value)
    found, rows = _rows_at_paths(
        payload,
        (("shop",), ("data", "shop"), ("detail", "shop")),
        allow_mapping=True,
    )
    if not found:
        return ()
    return tuple(row for row in rows if isinstance(row, Mapping))


def _provider_mapping_nodes(value: Any, *, _depth: int = 0) -> tuple[Mapping[str, Any], ...]:
    """Walk only known response containers for pagination metadata."""

    if _depth > 8:
        return ()
    payload = _unwrap_mcp_payload(value)
    if not isinstance(payload, Mapping):
        return ()
    nodes: list[Mapping[str, Any]] = []
    pending: list[tuple[Mapping[str, Any], int]] = [(payload, _depth)]
    seen: set[int] = set()
    while pending:
        node, depth = pending.pop(0)
        marker = id(node)
        if marker in seen or depth > 8:
            continue
        seen.add(marker)
        nodes.append(node)
        for key in _PROVIDER_CONTAINER_KEYS:
            child = node.get(key)
            if isinstance(child, Mapping):
                pending.append((child, depth + 1))
            elif isinstance(child, (list, tuple)):
                pending.extend(
                    (item, depth + 1)
                    for item in child
                    if isinstance(item, Mapping)
                )
    return tuple(nodes)


def _scalar_text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return text or None
    return None


def _first_scalar(nodes: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> str | None:
    for node in nodes:
        for key in keys:
            value = _scalar_text(node.get(key))
            if value is not None:
                return value
    return None


def _first_bool(nodes: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> bool | None:
    for node in nodes:
        for key in keys:
            value = node.get(key)
            if isinstance(value, bool):
                return value
    return None


def _first_mapping(nodes: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> Mapping[str, Any] | None:
    for node in nodes:
        for key in keys:
            value = node.get(key)
            if isinstance(value, Mapping):
                return value
    return None


def provider_metadata(value: Any, *, operation: str | None = None) -> dict[str, Any]:
    """Derive cursor/continuation/completeness without dropping provider maps."""

    del operation  # reserved for future provider-specific metadata precedence
    nodes = _provider_mapping_nodes(value)
    if not nodes:
        return {}

    pagination = _first_mapping(nodes, ("pagination", "page_info", "pageInfo", "paging"))
    continuation = _first_mapping(nodes, ("continuation",))
    completeness_raw: Any = next(
        (
            node.get("completeness")
            for node in nodes
            if node.get("completeness") not in (None, "")
        ),
        None,
    )
    completeness_map = completeness_raw if isinstance(completeness_raw, Mapping) else None
    nested_continuation = (
        completeness_map.get("continuation")
        if completeness_map is not None and isinstance(completeness_map.get("continuation"), Mapping)
        else None
    )
    if continuation is None:
        continuation = nested_continuation

    next_cursor = _first_scalar(
        nodes,
        ("next_cursor", "nextCursor", "next_offset", "nextOffset", "next_start_index", "nextStartIndex", "next_page", "nextPage"),
    )
    if next_cursor is None and continuation is not None:
        next_cursor = _first_scalar(
            (continuation,),
            ("next_cursor", "nextCursor", "next_offset", "nextOffset", "next_start_index", "nextStartIndex", "next_page", "nextPage"),
        )
    if next_cursor is None and pagination is not None:
        next_cursor = _first_scalar(
            (pagination,),
            ("next_cursor", "nextCursor", "next_offset", "nextOffset", "next_start_index", "nextStartIndex", "next_page", "nextPage"),
        )

    has_more = _first_bool(nodes, ("has_more", "hasMore", "has_next", "hasNext"))
    if has_more is None and pagination is not None:
        has_more = _first_bool((pagination,), ("has_more", "hasMore", "has_next", "hasNext"))
    if has_more is None:
        ended = _first_bool(nodes, ("is_end", "isEnd"))
        if ended is not None:
            has_more = not ended
    complete_flag = _first_bool(nodes, ("complete", "is_complete", "isComplete"))
    if complete_flag is None and completeness_map is not None:
        complete_flag = _first_bool((completeness_map,), ("complete", "is_complete", "isComplete"))
    if has_more is None and complete_flag is not None:
        has_more = not complete_flag
    has_more = bool(has_more)

    cursor = _first_scalar(nodes, ("cursor", "current_cursor", "currentCursor", "start_index", "startIndex", "offset"))
    if cursor is None and pagination is not None:
        cursor = _first_scalar((pagination,), ("cursor", "current_cursor", "currentCursor", "start_index", "startIndex", "offset"))

    # Offset/page providers often expose only ``has_next``.  Derive a stable
    # continuation token from their explicit page state so the strict contract
    # can retain the fact that more evidence exists.
    if has_more and next_cursor is None and pagination is not None:
        current_page = _first_scalar((pagination,), ("current_page", "currentPage", "page"))
        if current_page is not None:
            with suppress(ValueError):
                next_cursor = str(int(current_page) + 1)
        if next_cursor is None:
            start = _first_scalar((pagination,), ("start_index", "startIndex", "offset"))
            size = _first_scalar((pagination,), ("page_size", "pageSize", "limit"))
            try:
                if start is not None and size is not None:
                    next_cursor = str(int(start) + int(size))
            except ValueError:
                pass
    expected_count = _first_scalar(
        nodes,
        ("expected_count", "expectedCount", "total", "record_count", "recordCount", "comment_count", "commentCount", "result_count", "resultCount", "count"),
    )
    metadata: dict[str, Any] = {}
    if pagination is not None:
        metadata["pagination"] = dict(pagination)
    if completeness_raw is not None:
        metadata["completeness_manifest"] = completeness_raw
    if continuation is not None:
        metadata["continuation"] = dict(continuation)
    if cursor is not None:
        metadata["cursor"] = cursor
    if next_cursor is not None:
        metadata["next_cursor"] = next_cursor
    if has_more:
        metadata["has_more"] = True
    if expected_count is not None:
        metadata["expected_count"] = expected_count

    if isinstance(completeness_raw, str):
        normalized = completeness_raw.casefold()
        completeness = normalized if normalized in {"complete", "partial", "unknown"} else None
    elif completeness_map is not None:
        status = _scalar_text(completeness_map.get("status"))
        normalized = status.casefold() if status else ""
        completeness = (
            "complete" if complete_flag is True or normalized in {"complete", "completed", "done", "end", "ended"}
            else "partial" if complete_flag is False or normalized in {"partial", "incomplete", "pending", "more"}
            else None
        )
    else:
        completeness = None
    if completeness is None:
        completeness = "partial" if has_more else "complete"
    metadata["derived_completeness"] = completeness
    return {
        "cursor": cursor,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "completeness": completeness,
        "expected_count": int(expected_count) if expected_count and expected_count.isdigit() else None,
        **metadata,
    }


class FoodEntityType(StrEnum):
    """Entity kinds that the Food pack can identify from public evidence."""

    SHOP = "shop"
    DISH = "dish"
    CUISINE = "cuisine"
    LOCATION = "location"


class FoodEvidenceType(StrEnum):
    """Food evidence types, ordered from direct observation to enrichment."""

    XHS_COMMENT = "xhs_comment"
    RESTAURANT_IDENTITY = "restaurant_identity"
    MENU = "menu"
    PRICE = "price"
    LOCALITY = "locality"
    REVIEW_TRUST = "review_trust"
    ADVERTISING_RISK = "advertising_risk"
    DIANPING_PROFILE = "dianping_profile"


class FoodClaimType(StrEnum):
    """Claim families emitted by the deterministic Food adapter."""

    EXPERIENCE = "experience"
    RECOMMENDATION = "recommendation"
    COMPLAINT = "complaint"
    LOCALITY = "locality"
    PRICE = "price"
    MENU = "menu"
    IDENTITY = "identity"
    ADVERTISING_RISK = "advertising_risk"


class FoodControversyKind(StrEnum):
    """Known disagreement shapes used to request more evidence."""

    MIXED_SENTIMENT = "mixed_sentiment"
    CORRECTION = "correction"
    EXPLICIT = "explicit"


@dataclass(frozen=True, slots=True)
class FoodInvestigationGoal:
    """The public objective and success criteria for a Food investigation."""

    goal_id: str = "food.restaurant-recommendation"
    objective: str = (
        "Identify restaurants and dishes supported by trustworthy local food "
        "experience evidence, then fill public shop facts when useful."
    )
    primary_evidence: tuple[str, ...] = (FoodEvidenceType.XHS_COMMENT.value,)
    secondary_evidence: tuple[str, ...] = (FoodEvidenceType.DIANPING_PROFILE.value,)
    success_criteria: tuple[str, ...] = (
        "candidate shops have comment-backed claims",
        "unresolved high-signal controversies are surfaced",
        "structured profile fields remain source-attributed",
    )

    @property
    def id(self) -> str:
        """Short alias used by generic goal registries."""

        return self.goal_id


@dataclass(frozen=True, slots=True)
class FoodSourcePriority:
    """Priority and role for one provider-neutral source capability."""

    source: str
    capability: str
    priority: int
    role: str
    evidence_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CommentDeepFetchStrategy:
    """Bounded, cursor-friendly comment collection policy."""

    capability: str = "comments.search"
    page_size: int = 50
    max_pages: int = 8
    max_comments_per_note: int = 400
    include_replies: bool = True
    preserve_raw_comments: bool = True
    stop_on_repeated_cursor: bool = True
    completeness_field: str = "comment_completeness"

    def __post_init__(self) -> None:
        if self.page_size <= 0 or self.max_pages <= 0 or self.max_comments_per_note <= 0:
            raise ValueError("comment deep-fetch bounds must be positive")


@dataclass(frozen=True, slots=True)
class ShopStructuredFields:
    """Fields the secondary shop profile source may contribute."""

    fields: tuple[str, ...] = (
        "provider_refs",
        "name",
        "alias",
        "url",
        "image_url",
        "images",
        "address",
        "city",
        "district",
        "region",
        "business_area",
        "location",
        "latitude",
        "longitude",
        "coordinate_system",
        "geo",
        "phone",
        "rating",
        "review_count",
        "average_price",
        "category",
        "opening_hours",
        "source_url",
        "recommended_dishes",
        "promotions",
        "tags",
        "attributes",
        "review_completeness",
        "source_payload",
        "source_updated_at",
        "fetched_at",
    )


@dataclass(frozen=True, slots=True)
class FoodCoverageRules:
    """Dimension thresholds used by the stopping decision."""

    minimum_comment_coverage: float = 0.80
    minimum_entity_coverage: float = 0.80
    minimum_claim_coverage: float = 0.60
    minimum_profile_coverage: float = 0.50
    maximum_unresolved_controversies: int = 0
    minimum_candidate_entities: int = 1

    def __post_init__(self) -> None:
        numeric = (
            self.minimum_comment_coverage,
            self.minimum_entity_coverage,
            self.minimum_claim_coverage,
            self.minimum_profile_coverage,
        )
        if any(not 0.0 <= value <= 1.0 for value in numeric):
            raise ValueError("coverage thresholds must be between 0 and 1")
        if self.maximum_unresolved_controversies < 0 or self.minimum_candidate_entities < 0:
            raise ValueError("coverage counts cannot be negative")


@dataclass(frozen=True, slots=True)
class FoodStoppingRules:
    """Stopping behavior independent of how the shared runtime schedules work."""

    coverage: FoodCoverageRules = field(default_factory=FoodCoverageRules)
    stop_when_no_actionable_gap: bool = True
    stop_when_no_candidate: bool = False
    allow_partial_profile: bool = True


@dataclass(frozen=True, slots=True)
class FoodPackDeclaration:
    """Complete semantic declaration exposed to a generic investigation loop."""

    domain_id: str = "food"
    version: str = "food-adaptive/v1"
    investigation_goal: FoodInvestigationGoal = field(default_factory=FoodInvestigationGoal)
    entity_types: tuple[str, ...] = tuple(item.value for item in FoodEntityType)
    evidence_types: tuple[str, ...] = tuple(item.value for item in FoodEvidenceType)
    claim_types: tuple[str, ...] = tuple(item.value for item in FoodClaimType)
    controversy_kinds: tuple[str, ...] = tuple(item.value for item in FoodControversyKind)
    source_priority: tuple[FoodSourcePriority, ...] = (
        FoodSourcePriority(
            source="xhs",
            capability="comments.search",
            priority=100,
            role="primary",
            evidence_types=(FoodEvidenceType.XHS_COMMENT.value,),
        ),
        FoodSourcePriority(
            source="dianping",
            capability="places.detail",
            priority=50,
            role="secondary",
            evidence_types=(FoodEvidenceType.DIANPING_PROFILE.value,),
        ),
    )
    comment_deep_fetch: CommentDeepFetchStrategy = field(default_factory=CommentDeepFetchStrategy)
    shop_fields: ShopStructuredFields = field(default_factory=ShopStructuredFields)
    stopping: FoodStoppingRules = field(default_factory=FoodStoppingRules)

    @property
    def source_priorities(self) -> Mapping[str, int]:
        return {item.capability: item.priority for item in self.source_priority}

    @property
    def structured_shop_fields(self) -> tuple[str, ...]:
        return self.shop_fields.fields

    def to_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-friendly declaration for registry/introspection APIs."""

        return cast(
            dict[str, JsonValue],
            {
                "domain_id": self.domain_id,
                "version": self.version,
                "investigation_goal": {
                    "goal_id": self.investigation_goal.goal_id,
                    "objective": self.investigation_goal.objective,
                    "primary_evidence": list(self.investigation_goal.primary_evidence),
                    "secondary_evidence": list(self.investigation_goal.secondary_evidence),
                    "success_criteria": list(self.investigation_goal.success_criteria),
                },
                "entity_types": list(self.entity_types),
                "evidence_types": list(self.evidence_types),
                "claim_types": list(self.claim_types),
                "controversy_kinds": list(self.controversy_kinds),
                "source_priority": [
                    {
                        "source": item.source,
                        "capability": item.capability,
                        "priority": item.priority,
                        "role": item.role,
                        "evidence_types": list(item.evidence_types),
                    }
                    for item in self.source_priority
                ],
                "comment_deep_fetch": {
                    "capability": self.comment_deep_fetch.capability,
                    "page_size": self.comment_deep_fetch.page_size,
                    "max_pages": self.comment_deep_fetch.max_pages,
                    "max_comments_per_note": self.comment_deep_fetch.max_comments_per_note,
                    "include_replies": self.comment_deep_fetch.include_replies,
                },
                "shop_fields": list(self.shop_fields.fields),
                "stopping": {
                    "minimum_comment_coverage": self.stopping.coverage.minimum_comment_coverage,
                    "minimum_entity_coverage": self.stopping.coverage.minimum_entity_coverage,
                    "minimum_claim_coverage": self.stopping.coverage.minimum_claim_coverage,
                    "minimum_profile_coverage": self.stopping.coverage.minimum_profile_coverage,
                    "maximum_unresolved_controversies": self.stopping.coverage.maximum_unresolved_controversies,
                    "minimum_candidate_entities": self.stopping.coverage.minimum_candidate_entities,
                },
            },
        )


class ObservationEnvelope(AdaptiveObservationEnvelope):
    """Food-friendly view over the generic adaptive observation contract.

    The generic contract uses ``data`` and ``capability``.  Existing Food
    source adapters use ``items`` and ``operation``.  This additive subclass
    accepts both spellings and converts legacy values into the generic shape,
    while retaining the generic observation identity and raw payload.
    """

    model_config = ConfigDict(
        extra="allow",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )

    observation_id: str = Field(
        default="food-observation",
        validation_alias=AliasChoices("observation_id", "id"),
    )
    investigation_id: str = Field(
        default="food-investigation",
        validation_alias=AliasChoices("investigation_id", "run_id"),
    )
    source: str | None = Field(
        default=None,
        validation_alias=AliasChoices("source", "source_id", "provider"),
    )
    provider: str | None = None
    items: tuple[JsonValue, ...] = Field(
        default=(),
        validation_alias=AliasChoices(
            "items", "normalized_items", "records", "comments", "profiles"
        ),
    )
    provider_response: JsonValue = None
    provider_payload_ref: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "provider_payload_ref",
            "provider_payload_id",
            "payload_ref",
            "provider_response_ref",
        ),
    )
    provider_payload_refs: tuple[str, ...] = ()
    expected_count: int | None = Field(default=None, ge=0)
    warnings: tuple[str, ...] = ()
    error_code: str | None = None
    error_message: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_shape(cls, value: Any) -> Any:
        if isinstance(value, AdaptiveObservationEnvelope):
            value = value.model_dump(mode="python", by_alias=False)
        if not isinstance(value, Mapping):
            return value
        original = dict(value)
        payload = dict(value)
        operation = payload.get("operation", payload.get("op"))
        capability = payload.get("capability")
        if operation is not None and capability is None:
            payload["capability"] = operation
        # ``operation`` and ``success`` are compatibility spellings for the
        # generic contract's ``capability`` and ``outcome`` fields.  The
        # generic model exposes the former two as read-only projections, so
        # remove the aliases before validation instead of shadowing them.
        payload.pop("operation", None)
        payload.pop("op", None)
        effective_operation = str(payload.get("operation") or payload.get("capability") or "observation")
        if payload.get("source") is None and payload.get("source_id") is None:
            provider = payload.get("provider")
            if isinstance(provider, str) and provider:
                payload["source"] = provider
        if payload.get("source") is None and payload.get("source_id") is None:
            lowered_operation = effective_operation.casefold()
            if lowered_operation.startswith(("notes.", "comments.")):
                payload["source"] = "xhs"
            elif lowered_operation.startswith(("places.", "reviews.")):
                payload["source"] = "dianping"
        if payload.get("observation_id") is None and payload.get("id") is None:
            payload["observation_id"] = "food-observation"
        if payload.get("investigation_id") is None and payload.get("run_id") is None:
            payload["investigation_id"] = "food-investigation"

        # ``data`` may itself be an MCP JSON-RPC result.  Keep the original
        # envelope as the audit payload, while exposing the provider JSON to
        # reducers and planners through the normalized data field.
        data_was_present = "data" in payload and payload.get("data") is not None
        provider_data = _unwrap_mcp_payload(payload.get("data") if data_was_present else original)
        external_provider_shape = data_was_present or _looks_like_provider_payload(
            original, operation=effective_operation
        )
        if data_was_present or external_provider_shape and not any(
            key in original for key in ("items", "normalized_items", "records", "comments", "profiles")
        ):
            payload["data"] = _json_compatible(provider_data)
        explicit_raw = any(
            key in original for key in ("raw_payload", "raw", "provider_payload")
        )
        if not explicit_raw and external_provider_shape:
            raw_source = original.get("data") if data_was_present else original
            payload["raw_payload"] = _json_compatible(raw_source)
        if payload.get("provider_response") is None and external_provider_shape:
            payload["provider_response"] = _json_compatible(provider_data)

        item_value = next(
            (
                payload[key]
                for key in ("items", "normalized_items", "records", "comments", "profiles")
                if key in payload
                and isinstance(payload[key], (list, tuple))
            ),
            None,
        )
        data = payload.get("data")
        if item_value is None:
            item_found, provider_rows = _rows_at_paths(
                data,
                _provider_item_paths(effective_operation),
                allow_mapping=effective_operation.casefold() in {"places.detail", ""},
            )
            if item_found:
                item_value = provider_rows
            else:
                provider_rows = provider_items(data, operation=effective_operation)
                if provider_rows:
                    item_value = provider_rows
        if item_value is not None:
            payload["items"] = item_value
            if payload.get("data") is None:
                payload["data"] = {
                    "items": list(item_value)
                    if isinstance(item_value, (tuple, set, frozenset))
                    else item_value
                }
        elif payload.get("data") is not None and isinstance(payload["data"], (list, tuple)):
            payload["items"] = payload["data"]
        outcome = payload.get("outcome")
        success = payload.pop("success", None)
        if success is False and outcome is None:
            payload["outcome"] = ObservationOutcome.FAILURE
        elif success is True and outcome is None:
            payload["outcome"] = ObservationOutcome.SUCCESS
        completeness = payload.get("completeness")
        if isinstance(completeness, ObservationCompleteness):
            payload["completeness"] = completeness.value

        derived = provider_metadata(payload.get("data", provider_data), operation=effective_operation)
        for field_name in ("cursor", "next_cursor", "has_more", "expected_count"):
            if payload.get(field_name) is None and derived.get(field_name) is not None:
                payload[field_name] = derived[field_name]
        if "has_more" not in payload and derived.get("has_more") is not None:
            payload["has_more"] = derived["has_more"]
        # The strict generic envelope cannot represent ``has_more`` without
        # a real continuation token. Preserve the provider signal in a typed
        # continuation marker instead of inventing a cursor that would cause
        # a page-one retry.
        if bool(payload.get("has_more")) and not payload.get("next_cursor"):
            continuation = payload.get("continuation")
            continuation = dict(continuation) if isinstance(continuation, Mapping) else {}
            continuation["has_more_without_cursor"] = True
            payload["continuation"] = continuation
            payload["has_more"] = False
        explicit_completeness = payload.get("completeness")
        if success is False and explicit_completeness is None:
            # The generic contract rejects a failed observation marked
            # complete.  A failed call has unknown coverage unless the
            # provider explicitly supplied a partial/unknown marker.
            payload["completeness"] = "unknown"
            explicit_completeness = "unknown"
        if explicit_completeness is None or isinstance(explicit_completeness, Mapping):
            payload["completeness"] = derived.get("completeness", "unknown")
        elif isinstance(explicit_completeness, str):
            normalized = explicit_completeness.casefold()
            if normalized not in {"complete", "partial", "unknown"}:
                payload["completeness"] = derived.get("completeness", "unknown")
        derived_metadata = {
            key: value
            for key, value in derived.items()
            if key not in {"cursor", "next_cursor", "has_more", "completeness", "expected_count"}
            and value is not None
        }
        continuation = payload.get("continuation")
        if isinstance(continuation, Mapping) and continuation.get("has_more_without_cursor"):
            derived_metadata["has_more_without_cursor"] = True
        existing_metadata = payload.get("metadata")
        if isinstance(existing_metadata, Mapping):
            merged_metadata = dict(derived_metadata)
            merged_metadata.update(existing_metadata)
            payload["metadata"] = merged_metadata
        elif derived_metadata:
            payload["metadata"] = derived_metadata
        return payload

    @property
    def normalized_items(self) -> tuple[JsonValue, ...]:
        return self.items

    @property
    def payload_refs(self) -> tuple[str, ...]:
        refs = list(self.provider_payload_refs)
        if self.provider_payload_ref:
            refs.append(self.provider_payload_ref)
        for key in ("provider_payload_ref", "payload_ref", "provider_response_ref", "raw_payload_ref"):
            for container in (self.provenance, self.metadata):
                value = container.get(key)
                if isinstance(value, str) and value:
                    refs.append(value)
        return tuple(dict.fromkeys(refs))

    @classmethod
    def from_source_envelope(cls, envelope: SourceEnvelope) -> ObservationEnvelope:
        """Adapt the existing runtime envelope without losing any fields."""

        payload = envelope.model_dump(mode="python", by_alias=False)
        payload["schema_version"] = OBSERVATION_ENVELOPE_SCHEMA_VERSION
        payload["items"] = payload.pop("normalized_items", ())
        payload["operation"] = envelope.operation
        payload["capability"] = envelope.operation
        payload["provider_payload_refs"] = tuple(
            value
            for value in (
                envelope.provenance.get("provider_payload_ref"),
                envelope.provenance.get("payload_ref"),
            )
            if isinstance(value, str) and value
        )
        return cls.model_validate(payload)

    @classmethod
    def coerce(
        cls,
        value: ObservationEnvelope | AdaptiveObservationEnvelope | SourceEnvelope | Mapping[str, Any],
    ) -> ObservationEnvelope:
        if isinstance(value, cls):
            return value
        if isinstance(value, SourceEnvelope):
            return cls.from_source_envelope(value)
        return cls.model_validate(value)


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Measured dimensions and missing work for one adapter projection."""

    dimensions: Mapping[str, float]
    unresolved_controversies: int = 0
    candidate_entity_count: int = 0
    missing: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.missing and self.unresolved_controversies == 0

    def meets(self, rules: FoodCoverageRules) -> bool:
        return (
            all(
                self.dimensions.get(name, 0.0) >= minimum
                for name, minimum in (
                    ("comments", rules.minimum_comment_coverage),
                    ("entities", rules.minimum_entity_coverage),
                    ("claims", rules.minimum_claim_coverage),
                    ("profiles", rules.minimum_profile_coverage),
                )
            )
            and self.unresolved_controversies <= rules.maximum_unresolved_controversies
            and self.candidate_entity_count >= rules.minimum_candidate_entities
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "dimensions": dict(self.dimensions),
            "unresolved_controversies": self.unresolved_controversies,
            "candidate_entity_count": self.candidate_entity_count,
            "missing": list(self.missing),
            "complete": self.complete,
        }


@dataclass(frozen=True, slots=True)
class FoodAdaptationResult:
    """Standard claims/entities/gaps plus lossless source material."""

    claims: tuple[InsightClaim, ...] = ()
    entities: tuple[dict[str, JsonValue], ...] = ()
    controversies: tuple[dict[str, JsonValue], ...] = ()
    gaps: tuple[ResearchGap, ...] = ()
    comments: tuple[JsonValue, ...] = ()
    profiles: tuple[dict[str, JsonValue], ...] = ()
    raw_comments: tuple[Any, ...] = ()
    provider_payload_refs: tuple[str, ...] = ()
    raw_provider_payloads: tuple[Any, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    coverage: CoverageReport = field(
        default_factory=lambda: CoverageReport(dimensions={})
    )
    observations: tuple[ObservationEnvelope, ...] = ()

    @property
    def standard_claims(self) -> tuple[InsightClaim, ...]:
        return self.claims

    @property
    def standard_entities(self) -> tuple[dict[str, JsonValue], ...]:
        return self.entities

    @property
    def standard_gaps(self) -> tuple[ResearchGap, ...]:
        return self.gaps

    @property
    def unresolved_controversies(self) -> tuple[dict[str, JsonValue], ...]:
        return tuple(
            controversy
            for controversy in self.controversies
            if controversy.get("status", "unresolved") == "unresolved"
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": FOOD_ADAPTATION_SCHEMA_VERSION,
            "claims": [claim.model_dump(mode="json") for claim in self.claims],
            "entities": list(self.entities),
            "controversies": list(self.controversies),
            "gaps": [gap.model_dump(mode="json") for gap in self.gaps],
            "comments": list(self.comments),
            "profiles": list(self.profiles),
            "raw_comments": cast(list[JsonValue], list(self.raw_comments)),
            "provider_payload_refs": list(self.provider_payload_refs),
            "raw_provider_payloads": cast(list[JsonValue], list(self.raw_provider_payloads)),
            "evidence_refs": list(self.evidence_refs),
            "coverage": self.coverage.to_dict(),
            # Observations are the audit boundary consumed by the adaptive
            # planner.  Keep the complete envelope here, including cursors,
            # provenance, metadata, and the untouched provider payload.
            "observations": [
                observation.model_dump(mode="json")
                for observation in self.observations
            ],
        }

    def to_model_context(self, *, include_comments: bool = True) -> dict[str, JsonValue]:
        """Return the normalized Food view used by model roles.

        The immutable run audit remains lossless in :meth:`to_dict`.  Model
        context is a separate read projection: raw provider envelopes and the
        complete observation list are already available on the canonical
        state, so copying them into ``food_projection`` needlessly doubles
        prompt size.  Comment rows are retained by default because they are
        the primary Food evidence; callers may omit them when the same rows
        are already present in the current state observation view.
        """

        payload = self.to_dict()
        payload.pop("raw_comments", None)
        payload.pop("raw_provider_payloads", None)
        payload.pop("observations", None)
        if not include_comments:
            payload.pop("comments", None)
        # Unknown provider profile fields remain authoritative in the run
        # audit.  Known structured fields are retained here for planning,
        # while the opaque source payload is not serialized a second time.
        profiles = payload.get("profiles")
        if isinstance(profiles, list):
            for profile in profiles:
                if isinstance(profile, dict):
                    profile.pop("source_payload", None)
        return payload


class CapabilityAction(PlanAction):
    """Food follow-up action extending the shared typed PlanAction contract."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )

    reason: str = Field(default="", validation_alias=AliasChoices("reason", "rationale"))
    entity_id: str | None = None
    source: str | None = None
    metadata: ContractPayload = Field(default_factory=dict)

    @property
    def rationale_text(self) -> str:
        return self.reason or self.rationale

    def to_dict(self) -> dict[str, JsonValue]:
        return cast(dict[str, JsonValue], self.model_dump(mode="json"))


@dataclass(frozen=True, slots=True)
class FoodStopDecision:
    """Explainable stopping result suitable for an investigation reducer."""

    stop: bool
    reason: str
    coverage: CoverageReport
    actions: tuple[CapabilityAction, ...] = ()

    @property
    def should_stop(self) -> bool:
        return self.stop


@runtime_checkable
class DomainPack(Protocol):
    """Minimal injectable protocol implemented by adaptive domain packs."""

    declaration: FoodPackDeclaration

    def adapt_observation(
        self,
        observation: ObservationEnvelope | SourceEnvelope | Mapping[str, Any],
    ) -> FoodAdaptationResult: ...

    def next_actions(
        self,
        observation: FoodAdaptationResult | ObservationEnvelope | SourceEnvelope | Mapping[str, Any],
        *,
        run_id: str = "run",
    ) -> tuple[CapabilityAction, ...]: ...


# Alias names make the protocol discoverable for callers that use the explicit
# adaptive terminology while retaining the generic DomainPack name.
AdaptiveDomainPack = DomainPack
FoodDomainPackProtocol = DomainPack


class FoodAdaptivePack:
    """Food implementation of the observation-to-action adapter protocol."""

    def __init__(
        self,
        *,
        declaration: FoodPackDeclaration | None = None,
        coverage_rules: FoodCoverageRules | None = None,
    ) -> None:
        base = declaration or FoodPackDeclaration()
        if coverage_rules is not None:
            base = FoodPackDeclaration(
                domain_id=base.domain_id,
                version=base.version,
                investigation_goal=base.investigation_goal,
                entity_types=base.entity_types,
                evidence_types=base.evidence_types,
                claim_types=base.claim_types,
                controversy_kinds=base.controversy_kinds,
                source_priority=base.source_priority,
                comment_deep_fetch=base.comment_deep_fetch,
                shop_fields=base.shop_fields,
                stopping=FoodStoppingRules(
                    coverage=coverage_rules,
                    stop_when_no_actionable_gap=base.stopping.stop_when_no_actionable_gap,
                    stop_when_no_candidate=base.stopping.stop_when_no_candidate,
                    allow_partial_profile=base.stopping.allow_partial_profile,
                ),
            )
        self.declaration = base

    @property
    def goal(self) -> FoodInvestigationGoal:
        return self.declaration.investigation_goal

    @property
    def entity_types(self) -> tuple[str, ...]:
        return self.declaration.entity_types

    @property
    def evidence_types(self) -> tuple[str, ...]:
        return self.declaration.evidence_types

    @property
    def claim_types(self) -> tuple[str, ...]:
        return self.declaration.claim_types

    @property
    def source_priority(self) -> tuple[FoodSourcePriority, ...]:
        return self.declaration.source_priority

    @property
    def source_priorities(self) -> Mapping[str, int]:
        return self.declaration.source_priorities

    @property
    def comment_deep_fetch(self) -> CommentDeepFetchStrategy:
        return self.declaration.comment_deep_fetch

    @property
    def shop_fields(self) -> tuple[str, ...]:
        return self.declaration.structured_shop_fields

    @property
    def stopping_rules(self) -> FoodStoppingRules:
        return self.declaration.stopping

    def describe(self) -> FoodPackDeclaration:
        return self.declaration

    def adapt_observation(
        self,
        observation: ObservationEnvelope | SourceEnvelope | Mapping[str, Any],
    ) -> FoodAdaptationResult:
        """Convert one or many observations into standard Food projections."""

        envelopes = self._coerce_observations(observation)
        claims: dict[str, InsightClaim] = {}
        entities: dict[str, dict[str, Any]] = {}
        controversies: dict[str, dict[str, Any]] = {}
        profiles: dict[str, dict[str, JsonValue]] = {}
        comments: list[JsonValue] = []
        raw_comments: list[Any] = []
        provider_payload_refs: list[str] = []
        raw_provider_payloads: list[Any] = []
        gaps: dict[tuple[str, str, str], ResearchGap] = {}
        sentiment_by_entity: dict[str, dict[str, set[str]]] = defaultdict(
            lambda: {"positive": set(), "negative": set(), "correction": set()}
        )
        expected_comments = 0
        observed_comments = 0
        comment_envelopes = 0

        for envelope in envelopes:
            provider_payload_refs.extend(envelope.payload_refs)
            if envelope.raw_payload is not None:
                raw_provider_payloads.append(envelope.raw_payload)
            self._append_envelope_gaps(envelope, gaps)
            direct_comment_observation = self._is_comment_observation(envelope)
            nested_comment_items = self._nested_comment_items(envelope)
            if direct_comment_observation or nested_comment_items:
                comment_envelopes += 1
                comment_items = envelope.items if direct_comment_observation else nested_comment_items
                expected_comments += (
                    self._expected_count(envelope)
                    if direct_comment_observation
                    else len(comment_items)
                )
                for item in comment_items:
                    if not isinstance(item, Mapping):
                        self._add_gap(
                            gaps,
                            ResearchGap(
                                source=envelope.source,
                                operation=envelope.operation,
                                code="invalid_comment_item",
                                message="comment item is not an object",
                                details={"provider_payload_refs": list(envelope.payload_refs)},
                            ),
                        )
                        continue
                    observed_comments += 1
                    comments.append(cast(JsonValue, dict(item)))
                    raw_item = item.get("raw_payload", item.get("raw", item))
                    if self.declaration.comment_deep_fetch.preserve_raw_comments:
                        raw_comments.append(raw_item)
                    comment_claims, comment_entities = self._extract_comment(
                        envelope, item, claims, entities, sentiment_by_entity
                    )
                    for claim in comment_claims:
                        claims[claim.claim_id] = claim
                    for entity in comment_entities:
                        self._merge_entity(entities, entity)
                    self._extract_explicit_controversies(
                        envelope, item, controversies, provider_payload_refs
                    )
            elif self._is_place_search_observation(envelope):
                for item in envelope.items:
                    if not isinstance(item, Mapping):
                        self._add_gap(
                            gaps,
                            ResearchGap(
                                source=envelope.source,
                                operation=envelope.operation,
                                code="invalid_place_search_item",
                                message="place search item is not an object",
                                details={"provider_payload_refs": list(envelope.payload_refs)},
                            ),
                        )
                        continue
                    self._merge_entity(
                        entities,
                        self._extract_place_search_entity(envelope, item),
                    )
            elif self._is_profile_observation(envelope):
                for item in self._profile_items(envelope):
                    if not isinstance(item, Mapping):
                        self._add_gap(
                            gaps,
                            ResearchGap(
                                source=envelope.source,
                                operation=envelope.operation,
                                code="invalid_profile_item",
                                message="shop profile item is not an object",
                            ),
                        )
                        continue
                    profile = self._extract_profile(envelope, item, entities)
                    profile_id = str(profile["entity_id"])
                    profiles[profile_id] = self.merge_mapping(profiles.get(profile_id, {}), profile)
                    self._merge_entity(
                        entities,
                        {
                            "entity_id": profile_id,
                            "entity_type": FoodEntityType.SHOP.value,
                            "name": str(profile.get("name") or profile_id),
                            "status": "enriched",
                            "candidate": False,
                            "evidence_refs": list(profile.get("evidence_refs", [])),
                            "provider_payload_refs": list(envelope.payload_refs),
                            "structured_fields": profile,
                        },
                    )

        self._derive_controversies(sentiment_by_entity, entities, controversies)
        self._add_profile_gaps(profiles, entities, gaps, envelopes)
        all_refs = set(provider_payload_refs)
        all_evidence_refs = {
            ref for claim in claims.values() for ref in claim.evidence_refs
        }
        all_evidence_refs.update(
            str(ref)
            for entity in entities.values()
            for ref in entity.get("evidence_refs", ())
            if isinstance(ref, str)
        )
        all_refs.update(all_evidence_refs)
        coverage = self._coverage(
            expected_comments=expected_comments,
            observed_comments=observed_comments,
            comment_envelopes=comment_envelopes,
            claims=claims,
            entities=entities,
            profiles=profiles,
            controversies=controversies,
            gaps=gaps,
        )
        return FoodAdaptationResult(
            claims=tuple(claims[key] for key in sorted(claims)),
            entities=tuple(
                cast(dict[str, JsonValue], entities[key]) for key in sorted(entities)
            ),
            controversies=tuple(
                cast(dict[str, JsonValue], controversies[key]) for key in sorted(controversies)
            ),
            gaps=tuple(gaps[key] for key in sorted(gaps)),
            comments=tuple(comments),
            profiles=tuple(profiles[key] for key in sorted(profiles)),
            raw_comments=tuple(raw_comments),
            provider_payload_refs=tuple(dict.fromkeys(provider_payload_refs)),
            raw_provider_payloads=tuple(raw_provider_payloads),
            evidence_refs=tuple(sorted(all_refs)),
            coverage=coverage,
            observations=envelopes,
        )

    def merge_model_findings(
        self,
        adaptation: FoodAdaptationResult,
        findings: Iterable[Any] = (),
        controversies: Iterable[Any] = (),
    ) -> FoodAdaptationResult:
        """Reduce critic discoveries into the Food projection.

        Provider comments deliberately remain untouched.  The critic may
        identify a shop, dish, claim, or disagreement from those comments;
        this method turns only *cited* discoveries into candidates and keeps
        uncited output as an explicit gap.  That gives the model a useful
        semantic extraction boundary without making regexes or provider
        fields the source of truth.
        """

        finding_rows = tuple(self._iter_model_rows(findings))
        controversy_rows = tuple(self._iter_model_rows(controversies))
        if not finding_rows and not controversy_rows:
            return adaptation

        claims: dict[str, InsightClaim] = {item.claim_id: item for item in adaptation.claims}
        entities: dict[str, dict[str, Any]] = {
            str(item.get("entity_id")): dict(item)
            for item in adaptation.entities
            if isinstance(item, Mapping) and item.get("entity_id")
        }
        merged_controversies: dict[str, dict[str, Any]] = {
            str(item.get("controversy_id")): dict(item)
            for item in adaptation.controversies
            if isinstance(item, Mapping) and item.get("controversy_id")
        }
        gaps: dict[tuple[str, str, str], ResearchGap] = {
            (gap.source, gap.operation, gap.code): gap for gap in adaptation.gaps
        }
        evidence_refs = set(adaptation.evidence_refs)

        for index, row in enumerate(finding_rows):
            self._merge_model_finding(
                row,
                index=index,
                claims=claims,
                entities=entities,
                evidence_refs=evidence_refs,
                gaps=gaps,
            )

        for index, row in enumerate(controversy_rows):
            self._merge_model_controversy(
                row,
                index=index,
                controversies=merged_controversies,
                evidence_refs=evidence_refs,
                gaps=gaps,
            )

        # Keep the original measured comment coverage while refreshing the
        # dimensions affected by model discoveries.
        candidate_count = sum(
            1
            for entity in entities.values()
            if entity.get("entity_type") == FoodEntityType.SHOP.value
            and entity.get("candidate")
        )
        dimensions = dict(adaptation.coverage.dimensions)
        dimensions["entities"] = 1.0 if candidate_count else 0.0
        dimensions["claims"] = min(
            len(claims) / max(len(adaptation.comments), 1), 1.0
        )
        dimensions["profiles"] = min(
            len(adaptation.profiles) / max(candidate_count, 1), 1.0
        )
        coverage = CoverageReport(
            dimensions=dimensions,
            unresolved_controversies=sum(
                1
                for item in merged_controversies.values()
                if item.get("status", "unresolved") == "unresolved"
            ),
            candidate_entity_count=candidate_count,
            missing=tuple(sorted({*adaptation.coverage.missing, *(gap.code for gap in gaps.values() if gap.retryable)})),
        )
        return FoodAdaptationResult(
            claims=tuple(claims[key] for key in sorted(claims)),
            entities=tuple(
                cast(dict[str, JsonValue], entities[key]) for key in sorted(entities)
            ),
            controversies=tuple(
                cast(dict[str, JsonValue], merged_controversies[key])
                for key in sorted(merged_controversies)
            ),
            gaps=tuple(gaps[key] for key in sorted(gaps)),
            comments=adaptation.comments,
            profiles=adaptation.profiles,
            raw_comments=adaptation.raw_comments,
            provider_payload_refs=adaptation.provider_payload_refs,
            raw_provider_payloads=adaptation.raw_provider_payloads,
            evidence_refs=tuple(sorted(evidence_refs)),
            coverage=coverage,
            observations=adaptation.observations,
        )

    # ``reduce_findings`` is the domain-pack protocol spelling used by the
    # workflow composition boundary.  Keep the implementation in one method
    # so callers cannot accidentally diverge in evidence handling.
    reduce_findings = merge_model_findings

    @classmethod
    def _iter_model_rows(cls, values: Iterable[Any]) -> Iterable[Mapping[str, Any]]:
        """Flatten common model wrappers while retaining only object rows."""

        for value in values or ():
            if isinstance(value, Mapping):
                nested = next(
                    (
                        value[key]
                        for key in ("findings", "entities", "candidates", "items")
                        if isinstance(value.get(key), (list, tuple))
                    ),
                    None,
                )
                if nested is not None:
                    yield from cls._iter_model_rows(nested)
                else:
                    yield value

    def _merge_model_finding(
        self,
        row: Mapping[str, Any],
        *,
        index: int,
        claims: dict[str, InsightClaim],
        entities: dict[str, dict[str, Any]],
        evidence_refs: set[str],
        gaps: dict[tuple[str, str, str], ResearchGap],
    ) -> None:
        nested_entity = row.get("entity") if isinstance(row.get("entity"), Mapping) else {}
        nested_shop = row.get("shop") if isinstance(row.get("shop"), Mapping) else {}
        name = self._first_string(
            row,
            "entity_name",
            "shop_name",
            "shop",
            "restaurant",
            "restaurant_name",
            "entity",
            "name",
        ) or self._first_string(
            nested_entity,
            "name",
            "shop_name",
            "entity_name",
        ) or self._first_string(nested_shop, "name", "shop_name", "entity_name")
        raw_entity_id = self._first_string(row, "entity_id")
        if not name and raw_entity_id:
            name = raw_entity_id.split(":", 1)[1] if ":" in raw_entity_id else raw_entity_id
        provider_id = self._provider_id(row)
        if not provider_id:
            provider_id = self._provider_id(nested_entity) or self._provider_id(nested_shop)
        refs = self.string_values(
            row.get("evidence_refs", row.get("evidence_ref", row.get("refs")))
        )
        claim_text = self._first_string(
            row,
            "claim",
            "claim_text",
            "text",
            "finding",
            "summary",
            "description",
        )
        if not refs:
            self._add_model_gap(gaps, index, "finding")
            return
        evidence_refs.update(refs)
        dishes = self.string_values(
            row.get("dish_names", row.get("dishes", row.get("mentioned_dishes")))
        )
        entity_id = (
            raw_entity_id
            if raw_entity_id and raw_entity_id.startswith(f"{FoodEntityType.SHOP.value}:")
            else self._entity_id(FoodEntityType.SHOP.value, name)
            if name
            else None
        )
        if entity_id is not None:
            self._merge_entity(
                entities,
                {
                    "entity_id": entity_id,
                    "entity_type": FoodEntityType.SHOP.value,
                    "name": name,
                    "normalized_name": self._normalize_name(name),
                    "status": "candidate",
                    "candidate": True,
                    "evidence_refs": list(refs),
                    "raw_comment_refs": list(refs),
                    "dishes": list(dishes),
                    "source": "model_critic",
                    **({"provider_id": provider_id} if provider_id else {}),
                },
            )
        if not claim_text:
            return
        sentiment = self._normalize_sentiment(row)
        claim_type = self._model_claim_type(row, sentiment)
        claim_id = self._stable_id("claim", "model", *refs, claim_type, claim_text)
        attributes = {
            "claim_type": claim_type,
            "source": "model_critic",
            "operation": "adaptive.critic",
            "mentioned_shops": [name] if name else [],
            "mentioned_dishes": list(dishes),
            "sentiment": sentiment,
            "confidence": row.get("confidence"),
            "model_finding": True,
        }
        claims[claim_id] = InsightClaim(
            claim_id=claim_id,
            text=claim_text,
            evidence_refs=refs,
            attributes=cast(ContractPayload, attributes),
        )

    def _merge_model_controversy(
        self,
        row: Mapping[str, Any],
        *,
        index: int,
        controversies: dict[str, dict[str, Any]],
        evidence_refs: set[str],
        gaps: dict[tuple[str, str, str], ResearchGap],
    ) -> None:
        refs = self.string_values(
            row.get("evidence_refs", row.get("evidence_ref", row.get("refs")))
        )
        if not refs:
            self._add_model_gap(gaps, index, "controversy")
            return
        name = self._first_string(
            row,
            "entity_name",
            "shop_name",
            "entity",
            "name",
        ) or "unknown"
        kind = self._first_string(row, "kind", "controversy_kind", "type") or FoodControversyKind.EXPLICIT.value
        description = self._first_string(row, "description", "claim", "text", "summary") or "model identified an unresolved disagreement"
        entity_id = self._entity_id(FoodEntityType.SHOP.value, name) if name != "unknown" else ""
        controversy_id = self._stable_id("controversy", "model", entity_id, kind, description, *refs)
        controversies[controversy_id] = {
            "controversy_id": controversy_id,
            "entity_id": entity_id,
            "entity": name,
            "kind": kind,
            "status": self._first_string(row, "status") or "unresolved",
            "description": description,
            "evidence_refs": list(refs),
            "source": "model_critic",
        }
        evidence_refs.update(refs)

    @staticmethod
    def _add_model_gap(
        gaps: dict[tuple[str, str, str], ResearchGap], index: int, kind: str
    ) -> None:
        gap = ResearchGap(
            source="adaptive",
            operation="critic",
            code="uncited_model_finding",
            message=f"critic {kind} did not cite an evidence reference",
            retryable=False,
            details={"finding_index": index, "finding_kind": kind},
        )
        gaps.setdefault((gap.source, gap.operation, gap.code), gap)

    @staticmethod
    def _model_claim_type(row: Mapping[str, Any], sentiment: str) -> str:
        explicit = row.get("claim_type", row.get("kind", row.get("type")))
        if isinstance(explicit, str) and explicit in {item.value for item in FoodClaimType}:
            return explicit
        if sentiment == "negative":
            return FoodClaimType.COMPLAINT.value
        if sentiment == "positive":
            return FoodClaimType.RECOMMENDATION.value
        return FoodClaimType.EXPERIENCE.value

    # Descriptive aliases make the adapter easy to inject into differing
    # shared-loop naming conventions without duplicating semantics.
    adapt = adapt_observation
    to_standard = adapt_observation
    normalize_observation = adapt_observation

    def next_actions(
        self,
        observation: FoodAdaptationResult
        | ObservationEnvelope
        | SourceEnvelope
        | Mapping[str, Any],
        *,
        run_id: str = "run",
        existing_action_ids: Sequence[str] = (),
        max_actions: int | None = None,
    ) -> tuple[CapabilityAction, ...]:
        """Emit only work justified by current gaps, controversies, or candidates."""

        result = (
            observation
            if isinstance(observation, FoodAdaptationResult)
            else self.adapt_observation(observation)
        )
        existing = set(existing_action_ids)
        actions: list[CapabilityAction] = []
        unresolved = sorted(
            result.unresolved_controversies,
            key=lambda item: (
                str(item.get("entity_id") or item.get("entity") or ""),
                str(item.get("controversy_id") or ""),
            ),
        )
        for controversy in unresolved:
            entity_id = str(controversy.get("entity_id") or "")
            entity_name = str(controversy.get("entity") or controversy.get("name") or entity_id)
            refs = self._string_tuple(controversy.get("evidence_refs"))
            query = f"{entity_name} 真实评价 争议 避雷".strip()
            note_ids = self._note_ids_from_refs(refs)
            direct_note_id = self._first_string(controversy, "note_id", "noteId")
            if direct_note_id and direct_note_id not in note_ids:
                note_ids = (*note_ids, direct_note_id)
            contexts = {
                "controversy_id": str(controversy.get("controversy_id") or ""),
                "entity_id": entity_id,
                "entity": entity_name,
                "query": query,
                "evidence_refs": list(refs),
                "depth": "targeted",
            }
            if note_ids:
                action_specs = tuple(
                    (
                        "comments.search",
                        self._schema_arguments(
                            "comments.search",
                            {
                                "note_id": note_id,
                                "max_comments": min(
                                    100,
                                    max(1, self.comment_deep_fetch.max_comments_per_note),
                                ),
                                "include_replies": self.comment_deep_fetch.include_replies,
                            },
                        ),
                        {**contexts, "note_id": note_id},
                        "resolve an unresolved Food controversy with primary XHS comments",
                    )
                    for note_id in note_ids
                )
            else:
                action_specs = (
                    (
                        "notes.search",
                        self._schema_arguments(
                            "notes.search",
                            {
                                "query": query,
                                "count": 3,
                                "sort_type": "most_comments",
                                "include_details": True,
                                "include_comments": True,
                                "max_comments": min(
                                    60,
                                    max(0, self.comment_deep_fetch.max_comments_per_note),
                                ),
                            },
                        ),
                        contexts,
                        "find XHS notes that can resolve an unresolved Food controversy",
                    ),
                )
            for capability, arguments, metadata_context, reason in action_specs:
                action = self._action(
                    run_id=run_id,
                    capability=capability,
                    kind=PlanActionKind.SEARCH,
                    arguments=arguments,
                    reason=reason,
                    priority=100,
                    evidence_refs=refs,
                    entity_id=entity_id or None,
                    source="xhs",
                    metadata={
                        "trigger": "unresolved_controversy",
                        "context": metadata_context,
                    },
                )
                if action.action_id not in existing:
                    actions.append(action)

        profiles_by_entity = {
            str(entity.get("entity_id")): entity
            for entity in result.entities
            if entity.get("entity_type") == FoodEntityType.SHOP.value
        }
        for entity_id in sorted(profiles_by_entity):
            entity = profiles_by_entity[entity_id]
            if not bool(entity.get("candidate", False)):
                continue
            if entity.get("status") == "enriched" or entity_id in {
                str(profile.get("entity_id")) for profile in result.profiles
            }:
                continue
            name = str(entity.get("name") or entity_id)
            refs = self._string_tuple(entity.get("evidence_refs"))
            provider_id = self._provider_id(entity)
            if provider_id:
                capability = "places.detail"
                kind = PlanActionKind.VERIFY
                arguments: dict[str, JsonValue] = self._schema_arguments(
                    capability,
                    {"shop_id": provider_id},
                )
                reason = (
                    "fill a candidate shop's structured public profile from "
                    "secondary Dianping data"
                )
                trigger = "candidate_entity"
            else:
                # A comment name is not a Dianping identity.  Resolve it with
                # search first; detail requires a provider id in most MCP
                # schemas and must never receive a guessed id.
                capability = "places.search"
                kind = PlanActionKind.SEARCH
                arguments = self._schema_arguments(capability, {"keyword": name})
                reason = "resolve a candidate shop's Dianping identity before profile detail"
                trigger = "candidate_entity_lookup"
            action = self._action(
                run_id=run_id,
                capability=capability,
                kind=kind,
                arguments=arguments,
                reason=reason,
                priority=50,
                evidence_refs=refs,
                entity_id=entity_id,
                source="dianping",
                metadata={
                    "trigger": trigger,
                    "context": {
                        "entity_id": entity_id,
                        "entity": name,
                        "provider_id": provider_id,
                        "stage": "detail" if provider_id else "search",
                        "source_priority": "secondary",
                    },
                },
            )
            if action.action_id not in existing:
                actions.append(action)

        if any(gap.retryable for gap in result.gaps):
            # A missing profile is already represented by the targeted
            # ``places.detail`` action above.  It must not also fan out an
            # unrelated generic comment retry.
            retryable_gaps = tuple(
                gap for gap in result.gaps if gap.code != "candidate_profile_missing"
            )
            for gap in retryable_gaps:
                details = gap.details
                capability, source = self._retry_target(gap)
                entity_id = self._first_string(details, "entity_id")
                retry_spec = self._retry_arguments(capability, details)
                if retry_spec is None:
                    # A required provider identity is absent.  Keep the gap
                    # actionable for a later reducer turn, but never create
                    # an action that the MCP schema cannot accept.
                    continue
                capability, arguments = retry_spec
                if capability.startswith("places.") or capability == "reviews.search":
                    source = "dianping"
                else:
                    source = "xhs"
                refs = tuple(
                    ref
                    for ref in self._string_tuple(details.get("evidence_refs"))
                )
                action = self._action(
                    run_id=run_id,
                    capability=capability,
                    kind=PlanActionKind.SEARCH,
                    arguments=arguments,
                    reason="recover retryable Food observation coverage gap",
                    priority=90,
                    evidence_refs=refs,
                    entity_id=entity_id,
                    source=source,
                    metadata={
                        "trigger": "retryable_gap",
                        "gap_code": gap.code,
                        "continuation": True,
                        "context": dict(details),
                    },
                )
                if action.action_id not in existing:
                    actions.append(action)

        actions.sort(key=lambda item: (-item.priority, item.action_id))
        if max_actions is not None:
            return tuple(actions[: max(0, max_actions)])
        return tuple(actions)

    plan_follow_up = next_actions
    follow_up_actions = next_actions
    actions_for = next_actions

    def evaluate_stop(
        self,
        observation: FoodAdaptationResult | ObservationEnvelope | SourceEnvelope | Mapping[str, Any],
        *,
        run_id: str = "run",
        existing_action_ids: Sequence[str] = (),
    ) -> FoodStopDecision:
        result = (
            observation
            if isinstance(observation, FoodAdaptationResult)
            else self.adapt_observation(observation)
        )
        actions = self.next_actions(
            result,
            run_id=run_id,
            existing_action_ids=existing_action_ids,
        )
        rules = self.stopping_rules
        if rules.stop_when_no_candidate and result.coverage.candidate_entity_count == 0:
            return FoodStopDecision(True, "no candidate entity was observed", result.coverage, actions)
        if result.coverage.meets(rules.coverage) and not actions:
            return FoodStopDecision(True, "Food coverage thresholds met", result.coverage, actions)
        if rules.stop_when_no_actionable_gap and not actions and not result.gaps:
            return FoodStopDecision(
                True,
                "no unresolved controversy, candidate, or coverage gap remains",
                result.coverage,
                actions,
            )
        return FoodStopDecision(False, "additional evidence is actionable", result.coverage, actions)

    should_stop = evaluate_stop
    stopping_decision = evaluate_stop

    def _coerce_observations(
        self,
        value: ObservationEnvelope | SourceEnvelope | Mapping[str, Any] | Iterable[Any],
    ) -> tuple[ObservationEnvelope, ...]:
        if isinstance(value, (ObservationEnvelope, AdaptiveObservationEnvelope, SourceEnvelope, Mapping)):
            return (ObservationEnvelope.coerce(value),)
        return tuple(ObservationEnvelope.coerce(item) for item in value)

    @staticmethod
    def _is_comment_observation(envelope: ObservationEnvelope) -> bool:
        operation = envelope.operation.casefold()
        return (envelope.source or "").casefold() in {"xhs", "xiaohongshu", "xhs_pc"} and (
            "comment" in operation or "review" in operation
        )

    @staticmethod
    def _is_profile_observation(envelope: ObservationEnvelope) -> bool:
        operation = envelope.operation.casefold()
        source = (envelope.source or "").casefold()
        if source not in {"dianping", "dp"}:
            return False
        # A place search is an identity-discovery phase.  Treating its rows as
        # complete profiles suppresses the required detail fetch and loses the
        # distinction between a search hit and a hydrated shop record.
        return operation in {
            "places.detail",
            "reviews.search",
            "place.detail",
            "shop.profile",
            "places.profile",
        }

    @staticmethod
    def _is_place_search_observation(envelope: ObservationEnvelope) -> bool:
        return (
            (envelope.source or "").casefold() in {"dianping", "dp"}
            and envelope.operation.casefold() == "places.search"
        )

    @staticmethod
    def _nested_comment_items(envelope: ObservationEnvelope) -> tuple[Mapping[str, Any], ...]:
        """Expose comments embedded in XHS note search/detail result rows."""

        operation = envelope.operation.casefold()
        if (envelope.source or "").casefold() not in {"xhs", "xiaohongshu", "xhs_pc"}:
            return ()
        if not operation.startswith("notes."):
            return ()
        # Read each compatibility view independently.  Passing a list of
        # views to the provider shape adapter treats it as an opaque payload
        # and loses comments when raw_payload is absent.
        values: list[Any] = [envelope.data, envelope.items]
        if envelope.raw_payload is not None:
            values.append(envelope.raw_payload)
        rows: list[Mapping[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for value in values:
            for row in provider_comment_items(value, operation=operation):
                comment_id = next(
                    (
                        _scalar_text(row.get(key))
                        for key in ("comment_id", "commentId", "id", "external_id")
                        if _scalar_text(row.get(key)) is not None
                    ),
                    None,
                )
                note_id = next(
                    (
                        _scalar_text(row.get(key))
                        for key in ("note_id", "noteId", "document_id", "documentId")
                        if _scalar_text(row.get(key)) is not None
                    ),
                    "",
                )
                identity = (note_id, comment_id or json.dumps(_json_compatible(row), sort_keys=True, default=str))
                if identity in seen:
                    continue
                seen.add(identity)
                rows.append(row)
        return tuple(rows)

    @staticmethod
    def _profile_items(envelope: ObservationEnvelope) -> tuple[Mapping[str, Any], ...] | tuple[JsonValue, ...]:
        """Use ``shop`` for Dianping review profiles and retain review rows."""

        if envelope.operation.casefold() != "reviews.search":
            return envelope.items
        payload = _unwrap_mcp_payload(envelope.data)
        if not isinstance(payload, Mapping):
            payload = _unwrap_mcp_payload(envelope.raw_payload)
        shops = _provider_shop_items(payload)
        if not shops:
            # A review response may carry only review rows; the requested shop
            # identity is then available on the action metadata rather than in
            # the provider body.  Keep that identity so review-stage evidence
            # can still be attached to the correct profile.
            shop_id = next(
                (
                    _scalar_text(envelope.metadata.get(key))
                    for key in ("provider_id", "shop_id", "place_id")
                    if _scalar_text(envelope.metadata.get(key)) is not None
                ),
                None,
            )
            if shop_id:
                shops = ({
                    "shop_id": shop_id,
                    "name": next(
                        (
                            _scalar_text(envelope.metadata.get(key))
                            for key in ("entity_name", "shop_name", "name")
                            if _scalar_text(envelope.metadata.get(key)) is not None
                        ),
                        shop_id,
                    ),
                },)
        if not shops:
            return ()
        review_items = provider_items(payload, operation="reviews.search")
        profiles: list[Mapping[str, Any]] = []
        for shop in shops:
            profile = dict(shop)
            if review_items:
                profile["review_items"] = list(review_items)
            if isinstance(payload, Mapping):
                if payload.get("completeness") is not None:
                    profile["review_completeness"] = payload["completeness"]
                for key in (
                    "pagination",
                    "available_filters",
                    "record_count",
                    "result_count",
                    "split_tips",
                    "protocol",
                ):
                    if payload.get(key) is not None:
                        profile[f"review_{key}"] = payload[key]
            profiles.append(profile)
        return tuple(profiles)

    @staticmethod
    def _expected_count(envelope: ObservationEnvelope) -> int:
        if envelope.expected_count is not None:
            return envelope.expected_count
        for container in (envelope.metadata, envelope.provenance):
            for key in ("expected_count", "comment_expected_count", "total", "count"):
                value = container.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    return value
        return len(envelope.items) if envelope.completeness == "complete" else max(len(envelope.items), 1)

    @staticmethod
    def _comment_ref(source: str, note_id: str, comment_id: str) -> str:
        if source.casefold() in {"xhs", "xiaohongshu", "xhs_pc"}:
            return f"xhs:note:{note_id}:comment:{comment_id}"
        return f"{source}:comment:{comment_id}"

    def _extract_comment(
        self,
        envelope: ObservationEnvelope,
        item: Mapping[str, Any],
        claims: Mapping[str, InsightClaim],
        entities: Mapping[str, dict[str, Any]],
        sentiment_by_entity: dict[str, dict[str, set[str]]],
    ) -> tuple[tuple[InsightClaim, ...], tuple[dict[str, JsonValue], ...]]:
        del claims, entities
        comment_id = self._first_string(item, "comment_id", "commentId", "id", "external_id")
        note_id = self._first_string(
            item,
            "note_id",
            "noteId",
            "document_id",
            "documentId",
        ) or self._first_string(envelope.metadata, "note_id", "noteId")
        if not comment_id:
            comment_id = self._digest_id(item)
        if not note_id:
            note_id = "unknown"
        explicit_ref = self._first_string(item, "evidence_ref", "comment_ref", "ref")
        evidence_ref = explicit_ref or self._comment_ref(envelope.source, note_id, comment_id)
        text = self._first_string(item, "text", "content", "comment", "body") or ""
        sentiment = self._normalize_sentiment(item)
        correction = bool(item.get("is_correction", item.get("correction", False)))
        shops = self.string_values(
            item.get("mentioned_shops", item.get("shop_mentions", item.get("shops")))
        )
        direct_shop = self._first_string(item, "shop_name", "restaurant", "entity_name")
        if direct_shop:
            shops = tuple(dict.fromkeys((*shops, direct_shop)))
        dishes = self.string_values(
            item.get("mentioned_dishes", item.get("dish_mentions", item.get("dishes")))
        )
        payload_ref = self._item_payload_ref(item, envelope)
        claim_rows = item.get("claims")
        claim_inputs = claim_rows if isinstance(claim_rows, (list, tuple)) else ()
        extracted_claims: list[InsightClaim] = []
        for raw_claim in claim_inputs:
            if isinstance(raw_claim, Mapping):
                claim_text = self._first_string(raw_claim, "text", "claim", "content") or text
                claim_type = self._first_string(raw_claim, "claim_type", "type") or self._claim_type(
                    item, sentiment
                )
                claim_id = self._first_string(raw_claim, "claim_id", "id")
                attributes = dict(raw_claim.get("attributes")) if isinstance(raw_claim.get("attributes"), Mapping) else {}
            else:
                claim_text = str(raw_claim).strip()
                claim_type = self._claim_type(item, sentiment)
                claim_id = None
                attributes = {}
            if not claim_text:
                continue
            stable_id = claim_id or self._stable_id("claim", evidence_ref, claim_type, claim_text)
            attributes.update(
                {
                    "claim_type": claim_type,
                    "source": envelope.source,
                    "operation": envelope.operation,
                    "note_id": note_id,
                    "comment_id": comment_id,
                    "raw_comment_ref": evidence_ref,
                    "provider_payload_ref": payload_ref,
                    "mentioned_shops": list(shops),
                    "mentioned_dishes": list(dishes),
                    "sentiment": sentiment,
                }
            )
            extracted_claims.append(
                InsightClaim(
                    claim_id=stable_id,
                    text=claim_text,
                    evidence_refs=(evidence_ref,),
                    attributes=cast(ContractPayload, attributes),
                )
            )
        if text and not extracted_claims:
            claim_type = self._claim_type(item, sentiment)
            extracted_claims.append(
                InsightClaim(
                    claim_id=self._stable_id("claim", evidence_ref, claim_type, text),
                    text=text,
                    evidence_refs=(evidence_ref,),
                    attributes=cast(
                        ContractPayload,
                        {
                            "claim_type": claim_type,
                            "source": envelope.source,
                            "operation": envelope.operation,
                            "note_id": note_id,
                            "comment_id": comment_id,
                            "raw_comment_ref": evidence_ref,
                            "provider_payload_ref": payload_ref,
                            "mentioned_shops": list(shops),
                            "mentioned_dishes": list(dishes),
                            "sentiment": sentiment,
                        },
                    ),
                )
            )
        for shop in shops:
            entity_id = self._entity_id(FoodEntityType.SHOP.value, shop)
            bucket = sentiment_by_entity[entity_id]
            if sentiment in {"positive", "negative"}:
                bucket[sentiment].add(evidence_ref)
            if correction:
                bucket["correction"].add(evidence_ref)
        output_entities: list[dict[str, JsonValue]] = []
        for shop in shops:
            output_entities.append(
                {
                    "entity_id": self._entity_id(FoodEntityType.SHOP.value, shop),
                    "entity_type": FoodEntityType.SHOP.value,
                    "name": shop,
                    "normalized_name": self._normalize_name(shop),
                    "status": "candidate",
                    "candidate": True,
                    "evidence_refs": [evidence_ref],
                    "raw_comment_refs": [evidence_ref],
                    "provider_payload_refs": [payload_ref] if payload_ref else [],
                    "dishes": list(dishes),
                }
            )
        for dish in dishes:
            output_entities.append(
                {
                    "entity_id": self._entity_id(FoodEntityType.DISH.value, dish),
                    "entity_type": FoodEntityType.DISH.value,
                    "name": dish,
                    "normalized_name": self._normalize_name(dish),
                    "status": "candidate",
                    "candidate": True,
                    "evidence_refs": [evidence_ref],
                    "raw_comment_refs": [evidence_ref],
                    "provider_payload_refs": [payload_ref] if payload_ref else [],
                }
            )
        return tuple(extracted_claims), tuple(output_entities)

    def _extract_explicit_controversies(
        self,
        envelope: ObservationEnvelope,
        item: Mapping[str, Any],
        controversies: dict[str, dict[str, Any]],
        provider_payload_refs: Sequence[str],
    ) -> None:
        raw = item.get(
            "unresolved_controversies",
            item.get("controversies", item.get("controversy")),
        )
        values = raw if isinstance(raw, (list, tuple)) else (raw,) if raw is not None else ()
        comment_id = self._first_string(item, "comment_id", "commentId", "id") or self._digest_id(item)
        note_id = self._first_string(item, "note_id", "noteId") or "unknown"
        evidence_ref = self._first_string(item, "evidence_ref", "comment_ref", "ref") or self._comment_ref(
            envelope.source, note_id, comment_id
        )
        for value in values:
            if isinstance(value, Mapping):
                entity = self._first_string(value, "entity", "entity_name", "shop_name", "name") or "unknown"
                kind = self._first_string(value, "kind", "type") or FoodControversyKind.EXPLICIT.value
                status = self._first_string(value, "status") or "unresolved"
                refs = self.string_values(value.get("evidence_refs", value.get("refs")))
                description = self._first_string(value, "description", "text", "claim") or ""
            else:
                entity = "unknown"
                kind = FoodControversyKind.EXPLICIT.value
                status = "unresolved"
                refs = ()
                description = str(value).strip()
            refs = tuple(dict.fromkeys((*refs, evidence_ref)))
            entity_id = self._entity_id(FoodEntityType.SHOP.value, entity) if entity != "unknown" else ""
            controversy_id = self._stable_id("controversy", entity_id, kind, description, *refs)
            controversies[controversy_id] = {
                "controversy_id": controversy_id,
                "entity_id": entity_id,
                "entity": entity,
                "kind": kind,
                "status": status,
                "description": description,
                "evidence_refs": list(refs),
                "raw_comment_refs": [evidence_ref],
                "provider_payload_refs": list(provider_payload_refs),
            }

    def _derive_controversies(
        self,
        sentiment_by_entity: Mapping[str, Mapping[str, set[str]]],
        entities: Mapping[str, dict[str, Any]],
        controversies: dict[str, dict[str, Any]],
    ) -> None:
        for entity_id, signals in sentiment_by_entity.items():
            if not (
                (signals.get("positive") and signals.get("negative"))
                or signals.get("correction")
            ):
                continue
            entity = entities.get(entity_id, {})
            kind = (
                FoodControversyKind.CORRECTION.value
                if signals.get("correction")
                else FoodControversyKind.MIXED_SENTIMENT.value
            )
            refs = tuple(
                sorted(
                    set(signals.get("positive", set()))
                    | set(signals.get("negative", set()))
                    | set(signals.get("correction", set()))
                )
            )
            controversy_id = self._stable_id("controversy", entity_id, kind, *refs)
            controversies.setdefault(
                controversy_id,
                {
                    "controversy_id": controversy_id,
                    "entity_id": entity_id,
                    "entity": str(entity.get("name") or entity_id),
                    "kind": kind,
                    "status": "unresolved",
                    "evidence_refs": list(refs),
                    "positive_evidence_refs": sorted(signals.get("positive", set())),
                    "negative_evidence_refs": sorted(signals.get("negative", set())),
                    "correction_evidence_refs": sorted(signals.get("correction", set())),
                },
            )

    def _extract_place_search_entity(
        self,
        envelope: ObservationEnvelope,
        item: Mapping[str, Any],
    ) -> dict[str, JsonValue]:
        """Project one Dianping search hit as identity evidence only.

        Search cards may contain useful provider fields, but they are not a
        substitute for a detail page.  Keep the hit attached to the
        name-based Food entity and expose its provider identity so the next
        planning turn can issue ``places.detail`` with a real ``shop_id``.
        """

        provider_id = self._provider_id(item)
        name = self._first_string(
            item,
            "name",
            "shop_name",
            "restaurant_name",
            "title",
        )
        if not name:
            name = self._first_string(envelope.metadata, "entity_name", "shop_name", "name")
        if not name:
            name = provider_id or "unknown"
        entity_id = self._entity_id(FoodEntityType.SHOP.value, name)
        search_ref = f"{envelope.source}:search:{provider_id or self._normalize_name(name)}"
        result: dict[str, JsonValue] = {
            "entity_id": entity_id,
            "entity_type": FoodEntityType.SHOP.value,
            "name": name,
            "normalized_name": self._normalize_name(name),
            "status": "identified" if provider_id else "discovered",
            "candidate": False,
            "evidence_refs": [search_ref],
            "provider_payload_refs": list(envelope.payload_refs),
            "source": envelope.source,
            "operation": envelope.operation,
            "stage": "search",
            "structured_fields": cast(JsonValue, dict(item)),
        }
        if provider_id:
            result["provider_id"] = provider_id
            result["provider_refs"] = {"dianping": provider_id}
        return result

    def _extract_profile(
        self,
        envelope: ObservationEnvelope,
        item: Mapping[str, Any],
        entities: Mapping[str, dict[str, Any]],
    ) -> dict[str, JsonValue]:
        provider_id = self._first_string(
            item,
            "provider_id",
            "shop_id",
            "place_id",
            "id",
            "external_id",
        ) or self._first_string(envelope.metadata, "provider_id", "shop_id", "place_id")
        name = self._first_string(item, "name", "shop_name", "restaurant_name")
        if not name:
            name = self._first_string(envelope.metadata, "entity_name", "shop_name", "name")
        if not name and provider_id:
            # Detail/review payloads often omit the shop name because it was
            # already present on the preceding search card.  Match by the
            # retained provider identity so the hydrated profile enriches the
            # original name-based Food entity.
            for entity in entities.values():
                if str(entity.get("provider_id") or "") == provider_id:
                    name = self._first_string(entity, "name")
                    if name:
                        break
                provider_refs = entity.get("provider_refs")
                if isinstance(provider_refs, Mapping) and str(
                    provider_refs.get("dianping") or provider_refs.get("dp") or ""
                ) == provider_id:
                    name = self._first_string(entity, "name")
                    if name:
                        break
        name = name or "unknown"
        # Entity identity is canonicalized by the public shop name so a
        # profile returned later with a provider-specific id enriches the same
        # candidate entity.  Keep that provider id as provenance instead of
        # allowing connector identity to replace domain identity.
        entity_id = self._entity_id(FoodEntityType.SHOP.value, name)
        fields = {
            key: cast(JsonValue, item[key])
            for key in self.shop_fields
            if key in item
        }
        fields["name"] = name
        fields["entity_id"] = entity_id
        if provider_id:
            fields["provider_id"] = provider_id
            fields["provider_refs"] = {"dianping": provider_id}
        fields["source"] = envelope.source
        fields["operation"] = envelope.operation
        profile_stage = {
            "places.detail": "detail",
            "place.detail": "detail",
            "reviews.search": "reviews",
        }.get(envelope.operation.casefold(), "profile")
        fields["stage"] = profile_stage
        fields["profile_stage"] = profile_stage
        fields["stages"] = [profile_stage]
        fields["evidence_refs"] = [
            f"{envelope.source}:profile:{provider_id or self._normalize_name(name)}"
        ]
        fields["provider_payload_refs"] = list(envelope.payload_refs)
        fields["source_payload"] = cast(JsonValue, item.get("source_payload", item.get("raw_payload", item)))
        return cast(dict[str, JsonValue], fields)

    def _add_profile_gaps(
        self,
        profiles: Mapping[str, dict[str, JsonValue]],
        entities: Mapping[str, dict[str, Any]],
        gaps: dict[tuple[str, str, str], ResearchGap],
        envelopes: Sequence[ObservationEnvelope],
    ) -> None:
        profile_ids = set(profiles)
        for entity in entities.values():
            if entity.get("entity_type") != FoodEntityType.SHOP.value or not entity.get("candidate"):
                continue
            if str(entity.get("entity_id")) in profile_ids:
                continue
            envelope = next(
                (item for item in envelopes if self._is_comment_observation(item)),
                None,
            )
            if envelope is None:
                continue
            self._add_gap(
                gaps,
                ResearchGap(
                    source="dianping",
                    operation="places.detail",
                    code="candidate_profile_missing",
                    message="candidate shop has no secondary structured profile yet",
                    retryable=True,
                    details={
                        "entity_id": str(entity.get("entity_id")),
                        "shop_name": str(entity.get("name") or ""),
                        "evidence_refs": list(self._string_tuple(entity.get("evidence_refs"))),
                    },
                ),
            )

    def _append_envelope_gaps(
        self,
        envelope: ObservationEnvelope,
        gaps: dict[tuple[str, str, str], ResearchGap],
    ) -> None:
        if not envelope.success:
            self._add_gap(
                gaps,
                ResearchGap(
                    source=envelope.source,
                    operation=envelope.operation,
                    code=envelope.error_code or "provider_failure",
                    message=envelope.error_message or "provider observation failed",
                    retryable=True,
                    details={"provider_payload_refs": list(envelope.payload_refs)},
                ),
            )
        missing_cursor = bool(
            envelope.continuation.get("has_more_without_cursor")
            or envelope.metadata.get("has_more_without_cursor")
        )
        if envelope.completeness != "complete" or envelope.has_more or missing_cursor:
            self._add_gap(
                gaps,
                ResearchGap(
                    source=envelope.source,
                    operation=envelope.operation,
                    code=(
                        "continuation_missing_cursor"
                        if missing_cursor
                        else "partial_observation"
                        if envelope.completeness != "complete"
                        else "pagination_incomplete"
                    ),
                    message=(
                        "provider indicated more results but did not return a continuation cursor"
                        if missing_cursor
                        else "observation does not yet cover the source boundary"
                    ),
                    retryable=not missing_cursor,
                    details=self._continuation_details(envelope),
                ),
            )
        for warning in envelope.warnings:
            self._add_gap(
                gaps,
                ResearchGap(
                    source=envelope.source,
                    operation=envelope.operation,
                    code="provider_warning",
                    message=warning,
                    details={"provider_payload_refs": list(envelope.payload_refs)},
                ),
            )

    @staticmethod
    def _continuation_details(envelope: ObservationEnvelope) -> ContractPayload:
        """Copy provider continuation identity into a retryable gap.

        The next action must be able to continue the exact source stream.  A
        gap that only says ``partial`` is insufficient because it causes a
        cursor-capable connector to repeat page one and makes the resulting
        evidence look newer than it is.
        """

        details: dict[str, JsonValue] = {
            "source": envelope.source,
            "operation": envelope.operation,
            "cursor": envelope.cursor,
            "next_cursor": envelope.next_cursor,
            "has_more": envelope.has_more,
            "provider_payload_refs": list(envelope.payload_refs),
        }
        if envelope.continuation.get("has_more_without_cursor") or envelope.metadata.get(
            "has_more_without_cursor"
        ):
            details["has_more_without_cursor"] = True
        for container in (envelope.metadata, envelope.provenance):
            for key in (
                "entity_id",
                "entity",
                "note_id",
                "shop_id",
                "place_id",
                "provider_id",
                "keyword",
                "query",
                "page",
                "offset",
                "page_size",
                "expected_count",
            ):
                if key not in details:
                    value = _continuation_value(container.get(key))
                    if value is not None:
                        details[key] = value
        # The provider may not echo the original query/identity on a partial
        # page.  The scheduler keeps the semantic action in metadata; copy
        # only the public continuation fields needed to issue the next call.
        action = envelope.metadata.get("action")
        action_arguments = (
            action.get("arguments")
            if isinstance(action, Mapping)
            else None
        )
        if isinstance(action_arguments, Mapping):
            for key in (
                "entity_id",
                "entity",
                "note_id",
                "noteId",
                "shop_id",
                "shopId",
                "place_id",
                "placeId",
                "provider_id",
                "keyword",
                "query",
                "page",
                "offset",
                "sort",
                "review_filter",
                "tag_name",
                "max_comments",
            ):
                value = _continuation_value(action_arguments.get(key))
                if value is not None:
                    normalized_key = {
                        "noteId": "note_id",
                        "shopId": "shop_id",
                        "placeId": "place_id",
                        "provider_id": "shop_id",
                    }.get(key, key)
                    details.setdefault(normalized_key, value)
        for item in envelope.items:
            if not isinstance(item, Mapping):
                continue
            for key in (
                "entity_id",
                "entity",
                "note_id",
                "noteId",
                "shop_id",
                "shopId",
                "place_id",
                "placeId",
            ):
                value = _continuation_value(item.get(key))
                if value is not None:
                    normalized_key = {
                        "noteId": "note_id",
                        "shopId": "shop_id",
                        "placeId": "place_id",
                    }.get(key, key)
                    details.setdefault(normalized_key, value)
            if any(key in details for key in ("entity_id", "note_id", "shop_id", "place_id")):
                break
        # Dianping review pages carry the shop identity in a sibling ``shop``
        # object rather than on each review row.  Preserve it in continuation
        # metadata so the next page can use the provider's required key.
        for shop in _provider_shop_items(envelope.data or envelope.raw_payload):
            for key in ("shop_id", "shopId", "place_id", "placeId", "provider_id"):
                value = _continuation_value(shop.get(key))
                if value is not None:
                    details.setdefault(
                        {"shopId": "shop_id", "placeId": "place_id", "provider_id": "shop_id"}.get(
                            key, key
                        ),
                        value,
                    )
            if "shop_id" in details or "place_id" in details:
                break
        return cast(ContractPayload, details)

    @staticmethod
    def _note_ids_from_refs(refs: Sequence[str]) -> tuple[str, ...]:
        """Extract XHS note identities without treating arbitrary refs as ids."""

        pattern = re.compile(
            r"(?:^|[:/?&#])(?:note|note_id|noteid|document|document_id)"
            r"(?:[:=/?]|%3a)([^:/?&#]+)",
            re.IGNORECASE,
        )
        note_ids: list[str] = []
        for ref in refs:
            if not isinstance(ref, str):
                continue
            for match in pattern.finditer(ref.strip()):
                note_id = match.group(1).strip()
                if note_id.casefold() in {"unknown", "none", "null", "nil"}:
                    continue
                if note_id and note_id not in note_ids:
                    note_ids.append(note_id)
        return tuple(note_ids)

    @staticmethod
    def _schema_arguments(
        capability: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, JsonValue]:
        allowed_by_capability = {
            "notes.search": _XHS_SEARCH_ARGUMENTS,
            "comments.search": _XHS_COMMENTS_ARGUMENTS,
            "places.search": _DIANPING_SEARCH_ARGUMENTS,
            "places.detail": _DIANPING_DETAIL_ARGUMENTS,
            "reviews.search": _DIANPING_REVIEWS_ARGUMENTS,
            "notes.detail": frozenset({"note_id", "max_comments", "include_comments"}),
        }
        allowed = allowed_by_capability.get(capability, frozenset())
        return {
            str(key): cast(JsonValue, value)
            for key, value in arguments.items()
            if str(key) in allowed and value is not None
        }

    @classmethod
    def _retry_arguments(
        cls,
        capability: str,
        details: Mapping[str, Any],
    ) -> tuple[str, dict[str, JsonValue]] | None:
        """Build a retry payload from the actual public MCP fields only."""

        def text(*keys: str) -> str | None:
            return cls._first_string(details, *keys)

        def keyword(*keys: str) -> str | None:
            value = text(*keys)
            if value and value.startswith("shop:"):
                return value[5:] or None
            return value

        def bounded(
            value: Any,
            *,
            default: int,
            minimum: int,
            maximum: int,
        ) -> int:
            if isinstance(value, bool):
                return default
            try:
                return min(maximum, max(minimum, int(value)))
            except (TypeError, ValueError):
                return default

        if capability == "comments.search":
            note_id = text("note_id", "noteId")
            if note_id:
                return capability, cls._schema_arguments(
                    capability,
                    {
                        "note_id": note_id,
                        "max_comments": bounded(
                            details.get("max_comments"),
                            default=30,
                            minimum=1,
                            maximum=100,
                        ),
                        "include_replies": True,
                    },
                )
            # A comment retry without a note identity cannot satisfy the
            # comments.search required field.  Re-discover notes by query.
            capability = "notes.search"

        if capability == "notes.search":
            query = keyword("query", "keyword", "shop_name", "name", "entity")
            if not query:
                return None
            return capability, cls._schema_arguments(
                capability,
                {
                    "query": query,
                    "count": 3,
                    "sort_type": "most_comments",
                    "include_details": True,
                    "include_comments": True,
                    "max_comments": bounded(
                        details.get("max_comments"),
                        default=30,
                        minimum=0,
                        maximum=60,
                    ),
                },
            )

        if capability == "notes.detail":
            note_id = text("note_id", "noteId")
            if not note_id:
                return None
            return capability, cls._schema_arguments(
                capability,
                {
                    "note_id": note_id,
                    "max_comments": bounded(
                        details.get("max_comments"),
                        default=30,
                        minimum=0,
                        maximum=100,
                    ),
                    "include_comments": True,
                },
            )

        if capability == "places.search":
            query = keyword("keyword", "query", "shop_name", "name", "entity")
            if not query:
                return None
            page = cls._bounded_integer(
                details.get("page", details.get("next_page", details.get("next_cursor"))),
                default=1,
                minimum=1,
                maximum=10,
            )
            return capability, cls._schema_arguments(
                capability,
                {"keyword": query, "page": page},
            )

        if capability in {"places.detail", "reviews.search"}:
            shop_id = text("shop_id", "place_id", "provider_id")
            if not shop_id:
                return None
            if capability == "places.detail":
                return capability, cls._schema_arguments(capability, {"shop_id": shop_id})
            offset = cls._bounded_integer(
                details.get(
                    "offset",
                    details.get(
                        "next_offset",
                        details.get("next_cursor", details.get("cursor")),
                    ),
                ),
                default=0,
                minimum=0,
                maximum=1_000_000,
            )
            tag_name = text("tag_name", "tag")
            review_arguments: dict[str, Any] = {
                "shop_id": shop_id,
                "offset": offset,
                "timeout_seconds": 30,
            }
            # The provider contract forbids combining a semantic tag with
            # sort/filter, so choose one valid branch when continuing a page.
            if tag_name:
                review_arguments["tag_name"] = tag_name
            else:
                review_arguments["sort"] = text("sort") or "default"
                review_arguments["review_filter"] = text("review_filter") or "all"
            return capability, cls._schema_arguments(capability, review_arguments)

        return None

    @staticmethod
    def _bounded_integer(
        value: Any,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        if isinstance(value, bool):
            return default
        try:
            return min(maximum, max(minimum, int(value)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _retry_target(gap: ResearchGap) -> tuple[str, str]:
        """Resolve a retry capability without changing the source boundary."""

        source = gap.source.casefold()
        operation = gap.operation
        if source in {"dianping", "dp"}:
            allowed = {"places.search", "places.detail", "reviews.search"}
            return (operation if operation in allowed else "places.detail", "dianping")
        allowed = {"notes.search", "notes.detail", "comments.search"}
        return (operation if operation in allowed else "comments.search", "xhs")

    @staticmethod
    def _add_gap(gaps: dict[tuple[str, str, str], ResearchGap], gap: ResearchGap) -> None:
        gaps.setdefault((gap.source, gap.operation, gap.code), gap)

    def _coverage(
        self,
        *,
        expected_comments: int,
        observed_comments: int,
        comment_envelopes: int,
        claims: Mapping[str, InsightClaim],
        entities: Mapping[str, dict[str, Any]],
        profiles: Mapping[str, dict[str, JsonValue]],
        controversies: Mapping[str, dict[str, Any]],
        gaps: Mapping[tuple[str, str, str], ResearchGap],
    ) -> CoverageReport:
        candidate_count = sum(
            1
            for entity in entities.values()
            if entity.get("entity_type") == FoodEntityType.SHOP.value and entity.get("candidate")
        )
        unresolved = sum(
            1 for controversy in controversies.values() if controversy.get("status", "unresolved") == "unresolved"
        )
        comment_coverage = (
            1.0 if comment_envelopes and expected_comments == 0 else min(observed_comments / expected_comments, 1.0)
            if expected_comments
            else 0.0
        )
        entity_coverage = 1.0 if candidate_count else 0.0
        claim_coverage = min(len(claims) / max(observed_comments, 1), 1.0)
        profile_coverage = min(len(profiles) / max(candidate_count, 1), 1.0)
        missing = tuple(
            sorted(
                {
                    gap.code
                    for gap in gaps.values()
                    if gap.retryable
                }
            )
        )
        return CoverageReport(
            dimensions={
                "comments": round(comment_coverage, 6),
                "entities": round(entity_coverage, 6),
                "claims": round(claim_coverage, 6),
                "profiles": round(profile_coverage, 6),
            },
            unresolved_controversies=unresolved,
            candidate_entity_count=candidate_count,
            missing=missing,
        )

    @staticmethod
    def _merge_entity(entities: dict[str, dict[str, Any]], entity: Mapping[str, Any]) -> None:
        entity_id = str(entity.get("entity_id") or "")
        if not entity_id:
            return
        previous = entities.get(entity_id)
        if previous is None:
            entities[entity_id] = dict(entity)
            return
        for key, value in entity.items():
            if isinstance(value, (list, tuple)):
                existing = previous.get(key)
                values = list(existing) if isinstance(existing, (list, tuple)) else []
                values.extend(item for item in value if item not in values)
                previous[key] = values
            elif key == "status":
                # Search results identify a candidate, while detail/review
                # observations hydrate it.  A lower-fidelity observation must
                # never demote an already enriched entity.
                ranks = {
                    "discovered": 0,
                    "identified": 1,
                    "candidate": 2,
                    "enriched": 3,
                }
                current = str(previous.get(key) or "")
                incoming = str(value or "")
                if ranks.get(incoming, -1) >= ranks.get(current, -1):
                    previous[key] = value
            elif key == "candidate":
                # A secondary profile enriches a comment-backed candidate; it
                # must never demote that primary-evidence candidate to a
                # non-candidate merely because the profile projection carries
                # ``candidate=False``.
                previous[key] = bool(previous.get(key)) or bool(value)
            elif value not in (None, "", {}, []):
                previous[key] = value

    @classmethod
    def merge_mapping(
        cls,
        left: Mapping[str, JsonValue],
        right: Mapping[str, JsonValue],
    ) -> dict[str, JsonValue]:
        merged = dict(left)
        for key, value in right.items():
            if _is_empty_value(value):
                continue
            previous = merged.get(key)
            if isinstance(previous, Mapping) and isinstance(value, Mapping):
                merged[key] = cls.merge_mapping(previous, value)
            elif isinstance(previous, (list, tuple)) and isinstance(value, (list, tuple)):
                merged[key] = _merge_sequence(previous, value)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _first_string(value: Mapping[str, Any], *keys: str) -> str | None:
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None

    @classmethod
    def _provider_id(cls, entity: Mapping[str, Any]) -> str | None:
        """Return an explicit Dianping identity, never a display name."""

        direct = cls._first_string(
            entity,
            "provider_id",
            "shop_id",
            "place_id",
            "dianping_id",
            "id",
            "external_id",
        )
        if direct:
            return direct
        refs = entity.get("provider_refs")
        if isinstance(refs, Mapping):
            return cls._first_string(refs, "dianping", "dp")
        return None

    @staticmethod
    def string_values(value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value.strip(),) if value.strip() else ()
        if isinstance(value, (list, tuple, set, frozenset)):
            return tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
        return ()

    @classmethod
    def _string_tuple(cls, value: Any) -> tuple[str, ...]:
        return cls.string_values(value)

    @staticmethod
    def _normalize_name(value: str) -> str:
        return "".join(value.casefold().split())

    @classmethod
    def _entity_id(cls, entity_type: str, name: str) -> str:
        return f"{entity_type}:{cls._normalize_name(name)}"

    @staticmethod
    def _normalize_sentiment(item: Mapping[str, Any]) -> str:
        value = item.get("sentiment", item.get("polarity", "neutral"))
        normalized = str(getattr(value, "value", value)).casefold()
        if normalized in {"positive", "pos", "好评", "推荐", "正面"}:
            return "positive"
        if normalized in {"negative", "neg", "差评", "避雷", "负面"}:
            return "negative"
        return "neutral"

    @staticmethod
    def _claim_type(item: Mapping[str, Any], sentiment: str) -> str:
        explicit = item.get("claim_type", item.get("type"))
        if isinstance(explicit, str) and explicit:
            return explicit
        if bool(item.get("is_correction", item.get("correction", False))):
            return FoodClaimType.COMPLAINT.value
        if sentiment == "negative":
            return FoodClaimType.COMPLAINT.value
        if item.get("price") is not None or item.get("cost") is not None:
            return FoodClaimType.PRICE.value
        return FoodClaimType.EXPERIENCE.value

    @staticmethod
    def _item_payload_ref(item: Mapping[str, Any], envelope: ObservationEnvelope) -> str | None:
        for key in ("provider_payload_ref", "payload_ref", "provider_response_ref", "raw_payload_ref"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
        return envelope.payload_refs[0] if envelope.payload_refs else None

    @staticmethod
    def _digest_id(value: Any) -> str:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def _stable_id(cls, prefix: str, *parts: str) -> str:
        joined = "\x1f".join(str(part) for part in parts)
        return f"{prefix}:{hashlib.sha256(joined.encode('utf-8')).hexdigest()[:20]}"

    @classmethod
    def _action(
        cls,
        *,
        run_id: str,
        capability: str,
        kind: PlanActionKind,
        arguments: Mapping[str, JsonValue],
        reason: str,
        priority: int,
        evidence_refs: tuple[str, ...],
        entity_id: str | None = None,
        source: str | None = None,
        depends_on: tuple[str, ...] = (),
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> CapabilityAction:
        payload = json.dumps(
            {"capability": capability, "arguments": arguments, "entity_id": entity_id},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        suffix = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return CapabilityAction(
            action_id=f"{run_id}:food:{capability}:{suffix}",
            kind=kind,
            capability=capability,
            arguments=dict(arguments),
            reason=reason,
            priority=priority,
            evidence_refs=tuple(dict.fromkeys(evidence_refs)),
            entity_id=entity_id,
            source=source,
            depends_on=depends_on,
            metadata=dict(metadata or {}),
        )


# Friendly aliases used by integrations that name the concrete pack first.
AdaptiveFoodPack = FoodAdaptivePack
FoodDomainPack = FoodAdaptivePack
FoodAdaptiveDomainPack = FoodAdaptivePack


def create_food_adaptive_pack(
    *,
    declaration: FoodPackDeclaration | None = None,
    coverage_rules: FoodCoverageRules | None = None,
) -> FoodAdaptivePack:
    """Factory for composition-root dependency injection."""

    return FoodAdaptivePack(declaration=declaration, coverage_rules=coverage_rules)


def _is_empty_value(value: Any) -> bool:
    """Return whether a provider value carries no profile information."""

    return value is None or value == "" or value == [] or value == {} or value == ()


def _merge_sequence(left: Sequence[JsonValue], right: Sequence[JsonValue]) -> list[JsonValue]:
    """Union JSON sequences without requiring nested objects to be hashable."""

    merged: list[JsonValue] = []
    for value in (*left, *right):
        if not any(value == existing for existing in merged):
            merged.append(value)
    return merged


def _continuation_value(value: Any) -> JsonValue | None:
    """Keep only JSON-safe scalar/list values in a retry contract."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)) and all(
        isinstance(item, (str, int, float, bool)) or item is None for item in value
    ):
        return list(value)
    return None


__all__ = [
    "AdaptiveDomainPack",
    "AdaptiveFoodPack",
    "CapabilityAction",
    "CommentDeepFetchStrategy",
    "CoverageReport",
    "DomainPack",
    "FOOD_ADAPTATION_SCHEMA_VERSION",
    "FoodAdaptiveDomainPack",
    "FoodAdaptivePack",
    "FoodClaimType",
    "FoodControversyKind",
    "FoodCoverageRules",
    "FoodDomainPack",
    "FoodDomainPackProtocol",
    "FoodEntityType",
    "FoodEvidenceType",
    "FoodInvestigationGoal",
    "FoodPackDeclaration",
    "FoodSourcePriority",
    "FoodStopDecision",
    "FoodStoppingRules",
    "FoodAdaptationResult",
    "ObservationEnvelope",
    "OBSERVATION_ENVELOPE_SCHEMA_VERSION",
    "ShopStructuredFields",
    "create_food_adaptive_pack",
    "provider_comment_items",
    "provider_items",
    "provider_metadata",
]
