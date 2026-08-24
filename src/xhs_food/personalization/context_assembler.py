"""Deterministic assembly of private, temporary model context."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from math import ceil
from typing import Any

from xhs_food.contracts import (
    ContextAssembly,
    ContextAssemblyRequest,
    ContextBudget,
    ContextFragment,
    ContextSection,
    ContextSectionName,
    ContextSourceRef,
    EvidenceBundle,
    EvidenceItem,
    EvidenceStatus,
    MemoryConversationTurn,
    MemoryIsolationKey,
    MemoryLayer,
    MemoryRecord,
    VersionedMemorySummary,
    VisibilityScope,
    isolation_key_for,
)

TokenEstimator = Callable[[str], int]


class ContextAssembler:
    """Build a bounded context without importing an Agent or model framework.

    The assembler returns source-attributed sections.  A provider adapter may
    later translate those sections into ``ModelMessage`` values, but those
    framework objects never become memory or context authority records.
    """

    def __init__(self, token_estimator: TokenEstimator | None = None) -> None:
        self._token_estimator = token_estimator or _estimate_tokens

    def assemble(
        self,
        request: ContextAssemblyRequest | None = None,
        *,
        assembly_id: str | None = None,
        policy_version: str | None = None,
        request_constraints: Mapping[str, Any] | None = None,
        recent_messages: Iterable[MemoryConversationTurn | str] | None = None,
        summaries: Iterable[VersionedMemorySummary] | None = None,
        memories: Iterable[MemoryRecord] | None = None,
        evidence: Iterable[EvidenceItem] | None = None,
        evidence_bundle: EvidenceBundle | None = None,
        scope: MemoryIsolationKey | None = None,
        budget: ContextBudget | None = None,
    ) -> ContextAssembly:
        """Assemble sections in the contract's fixed order.

        ``request`` is a convenience envelope; keyword arguments are accepted
        so composition code can pass repositories' typed values directly.
        When both are supplied, explicit keyword values take precedence.
        """

        if request is not None:
            assembly_id = assembly_id or request.assembly_id
            policy_version = policy_version or request.policy_version
            if request_constraints is None:
                request_constraints = request.request_constraints
            recent_messages = recent_messages if recent_messages is not None else request.recent_messages
            summaries = summaries if summaries is not None else request.summaries
            memories = memories if memories is not None else request.memories
            evidence = evidence if evidence is not None else request.evidence
            evidence_bundle = evidence_bundle or request.evidence_bundle
            scope = scope or request.scope
            budget = budget or request.budget
        assembly_id = assembly_id or "context-assembly"
        policy_version = policy_version or "context-policy/v1"
        request_constraints = request_constraints or {}
        budget = budget or ContextBudget()

        memory_values = tuple(memories or ())
        message_values = tuple(recent_messages or ())
        summary_values = tuple(summaries or ())
        if scope is not None:
            expected_scope = _scope_key(scope)
            if any(_scope_key(isolation_key_for(item)) != expected_scope for item in memory_values):
                raise ValueError("context assembler received memory outside the requested scope")
            for message in message_values:
                if isinstance(message, MemoryConversationTurn) and _scope_key(message.scope) != expected_scope:
                    raise ValueError("context assembler received a message outside the requested scope")
            for summary in summary_values:
                if summary.scope is not None and _scope_key(summary.scope) != expected_scope:
                    raise ValueError("context assembler received a summary outside the requested scope")

        evidence_values = tuple(evidence or ())
        if evidence_bundle is not None:
            allowed = set(evidence_bundle.evidence_ids)
            evidence_values = tuple(item for item in evidence_values if item.evidence_id in allowed)
            bundle_version = f"{evidence_bundle.bundle_id}:v{evidence_bundle.bundle_version}"
        else:
            bundle_version = None

        sections = (
            self._assemble_request_constraints(
                request_constraints,
                policy_version=policy_version,
                budget=budget.request_constraints_tokens,
                assembly_id=assembly_id,
            ),
            self._assemble_messages(
                message_values,
                budget=budget.recent_messages_tokens,
            ),
            self._assemble_summaries(
                summary_values,
                budget=budget.versioned_summary_tokens,
            ),
            self._assemble_memories(
                memory_values,
                policy_version=policy_version,
                budget=budget.related_memory_tokens,
            ),
            self._assemble_evidence(
                evidence_values,
                bundle_version=bundle_version,
                budget=budget.related_evidence_tokens,
            ),
        )
        return ContextAssembly(
            assembly_id=assembly_id,
            policy_version=policy_version,
            budget=budget,
            estimated_tokens=sum(section.used_tokens for section in sections),
            sections=sections,
        )

    def _assemble_request_constraints(
        self,
        constraints: Mapping[str, Any],
        *,
        policy_version: str,
        budget: int,
        assembly_id: str,
    ) -> ContextSection:
        fragments = []
        for key in sorted(constraints):
            value = constraints[key]
            hard = isinstance(value, Mapping) and (
                value.get("hardConstraint") is True or value.get("kind") == "hard_constraint"
            )
            fragments.append(
                self._fragment(
                    fragment_id=f"{assembly_id}:constraint:{key}",
                    text=f"{key}={_json_text(value)}",
                    source=ContextSourceRef(
                        source_type="request-constraint",
                        source_id=f"{assembly_id}:constraint:{key}",
                        versions={"schema": "request-constraints/v1", "policy": policy_version},
                        citation=f"request:{assembly_id}:{key}",
                    ),
                    priority=0 if hard else 10,
                )
            )
        return self._select_section(
            ContextSectionName.REQUEST_CONSTRAINTS,
            fragments,
            budget,
            version_refs={"schema": "request-constraints/v1", "policy": policy_version},
        )

    def _assemble_messages(
        self,
        messages: Iterable[MemoryConversationTurn | str],
        *,
        budget: int,
    ) -> ContextSection:
        fragments: list[ContextFragment] = []
        values = tuple(messages)
        if all(not isinstance(message, str) for message in values):
            values = tuple(
                sorted(
                    values,
                    key=lambda message: (message.occurred_at, message.turn_id),  # type: ignore[union-attr]
                )
            )
        for index, message in enumerate(values):
            if isinstance(message, str):
                turn_id = f"message-{index:06d}"
                role = "user"
                content = message
            else:
                turn_id = message.turn_id
                role = message.role
                content = message.content
            fragments.append(
                self._fragment(
                    fragment_id=f"turn:{turn_id}",
                    text=f"{role}: {content}",
                    source=ContextSourceRef(
                        source_type="conversation-turn",
                        source_id=turn_id,
                        versions={"schema": "memory-conversation-turn/v1"},
                        citation=turn_id,
                    ),
                    priority=0,
                )
            )
        return self._select_section(
            ContextSectionName.RECENT_MESSAGES,
            fragments,
            budget,
            prefer_latest=True,
            version_refs={"schema": "memory-conversation-turn/v1"},
        )

    def _assemble_summaries(
        self,
        summaries: Iterable[VersionedMemorySummary],
        *,
        budget: int,
    ) -> ContextSection:
        fragments = [
            self._fragment(
                fragment_id=f"summary:{summary.summary_id}:v{summary.summary_version}",
                text=summary.content,
                source=ContextSourceRef(
                    source_type="memory-summary",
                    source_id=summary.summary_id,
                    versions={
                        "schema": summary.schema_version,
                        "summary": f"v{summary.summary_version}",
                        "authority": summary.source_authority_version,
                        "profile": summary.profile_version,
                        "policy": summary.policy_version,
                    },
                    citation=summary.source_authority_version,
                ),
                priority=0,
            )
            for summary in sorted(summaries, key=lambda item: (-item.summary_version, item.summary_id))
        ]
        return self._select_section(
            ContextSectionName.VERSIONED_SUMMARY,
            fragments,
            budget,
            version_refs={"schema": "memory-summary/v1"},
        )

    def _assemble_memories(
        self,
        memories: Sequence[MemoryRecord],
        *,
        policy_version: str,
        budget: int,
    ) -> ContextSection:
        fragments = []
        for record in sorted(
            memories,
            key=lambda item: (
                _memory_priority(item),
                -(item.confidence or 1.0),
                item.updated_at,
                item.record_id,
            ),
        ):
            if record.layer is MemoryLayer.STRATEGY_FEEDBACK:
                # Strategy feedback belongs to research/presentation policy,
                # never to content context as a user preference claim.
                continue
            layer_priority = _memory_priority(record)
            fragments.append(
                self._fragment(
                    fragment_id=f"memory:{record.record_id}",
                    text=f"{record.key}={_json_text(record.value)}",
                    source=ContextSourceRef(
                        source_type="memory-record",
                        source_id=record.record_id,
                        versions={
                            "schema": record.schema_version,
                            "policy": record.policy_version,
                        },
                        citation=record.source_event_ids[0],
                    ),
                    priority=layer_priority,
                    confidence=record.confidence,
                )
            )
        return self._select_section(
            ContextSectionName.RELATED_MEMORY,
            fragments,
            budget,
            version_refs={"schema": "memory-record/v1", "policy": policy_version},
        )

    def _assemble_evidence(
        self,
        evidence: Sequence[EvidenceItem],
        *,
        bundle_version: str | None,
        budget: int,
    ) -> ContextSection:
        fragments = []
        for item in sorted(evidence, key=lambda value: (-value.confidence, value.evidence_id)):
            if item.visibility.scope is not VisibilityScope.PUBLIC:
                raise ValueError("ContextAssembler accepts public Evidence only")
            if item.status is EvidenceStatus.TOMBSTONED:
                continue
            versions = {"schema": item.schema_version, "extractor": item.extractor_version}
            if bundle_version is not None:
                versions["bundle"] = bundle_version
            fragments.append(
                self._fragment(
                    fragment_id=f"evidence:{item.evidence_id}",
                    text=f"{item.claim_type}={_json_text(item.claim_value)}",
                    source=ContextSourceRef(
                        source_type="public-evidence",
                        source_id=item.evidence_id,
                        versions=versions,
                        citation=item.source_locator_id,
                    ),
                    priority=int(round((1.0 - item.confidence) * 100)),
                    confidence=item.confidence,
                )
            )
        version_refs = {"schema": "evidence-item/v1"}
        if bundle_version is not None:
            version_refs["bundle"] = bundle_version
        return self._select_section(
            ContextSectionName.RELATED_EVIDENCE,
            fragments,
            budget,
            version_refs=version_refs,
        )

    def _fragment(
        self,
        *,
        fragment_id: str,
        text: str,
        source: ContextSourceRef,
        priority: int,
        confidence: float | None = None,
    ) -> ContextFragment:
        return ContextFragment(
            fragment_id=fragment_id,
            text=text,
            source=source,
            priority=priority,
            confidence=confidence,
            estimated_tokens=max(1, self._token_estimator(text)),
        )

    def _select_section(
        self,
        name: ContextSectionName,
        fragments: Sequence[ContextFragment],
        budget: int,
        *,
        prefer_latest: bool = False,
        version_refs: Mapping[str, str],
    ) -> ContextSection:
        # The caller's construction order is deterministic; selection is
        # priority-first, while recent messages additionally prefer newest.
        indexed = list(enumerate(fragments))
        if prefer_latest:
            ordered = list(reversed(indexed))
        else:
            ordered = sorted(indexed, key=lambda item: (item[1].priority, item[0]))
        selected: list[tuple[int, ContextFragment]] = []
        dropped: list[ContextSourceRef] = []
        remaining = budget
        for index, fragment in ordered:
            if fragment.estimated_tokens <= remaining:
                selected.append((index, fragment))
                remaining -= fragment.estimated_tokens
                continue
            if fragment.priority == 0 and remaining > 0:
                clipped = self._clip(fragment, remaining)
                if clipped is not None:
                    selected.append((index, clipped))
                    remaining -= clipped.estimated_tokens
                    continue
            dropped.append(fragment.source)
        selected.sort(key=lambda item: item[0])
        selected_fragments = tuple(item[1] for item in selected)
        return ContextSection(
            section=name,
            budget_tokens=budget,
            used_tokens=sum(item.estimated_tokens for item in selected_fragments),
            fragments=selected_fragments,
            source_refs=tuple(item.source for item in selected_fragments),
            dropped_source_refs=tuple(dropped),
            version_refs=dict(version_refs),
            truncated=bool(dropped),
        )

    def _clip(self, fragment: ContextFragment, budget: int) -> ContextFragment | None:
        if budget <= 0:
            return None
        text = fragment.text
        if self._token_estimator(text) <= budget:
            return fragment
        low, high = 1, len(text)
        best = ""
        while low <= high:
            middle = (low + high) // 2
            candidate = text[:middle].rstrip()
            if middle < len(text):
                candidate = f"{candidate}..."
            if self._token_estimator(candidate) <= budget:
                best = candidate
                low = middle + 1
            else:
                high = middle - 1
        if not best:
            return None
        return fragment.model_copy(
            update={"text": best, "estimated_tokens": self._token_estimator(best)}
        )


def _estimate_tokens(text: str) -> int:
    """Stable dependency-free estimate used until a provider tokenizer adapter exists."""

    return max(1, ceil(len(text) / 4))


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _memory_priority(record: MemoryRecord) -> int:
    if record.layer is MemoryLayer.EXPLICIT and (
        record.value.get("kind") == "hard_constraint" or record.value.get("hardConstraint") is True
    ):
        return 0
    if record.layer is MemoryLayer.SESSION:
        return 1
    if record.layer is MemoryLayer.EXPLICIT:
        return 2
    if record.layer is MemoryLayer.INFERRED:
        # Lower-confidence inferred facts are deliberately selected later.
        return 3 if (record.confidence or 0.0) >= 0.75 else 4
    return 5


def _scope_key(scope: MemoryIsolationKey) -> tuple[str, str, str, str | None]:
    subject_id = scope.user_id if scope.kind == "user" else scope.anonymous_subject_id
    return (scope.tenant_id, str(scope.kind), subject_id, scope.session_id)


__all__ = ["ContextAssembler"]
