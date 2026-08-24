"""Framework-neutral contracts for temporary model-context assembly."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from .base import ContractModel, ContractPayload, NonEmptyStr
from .evidence import EvidenceBundle, EvidenceItem
from .memory import MemoryConversationTurn, MemoryIsolationKey, MemoryRecord

CONTEXT_ASSEMBLY_VERSION = "context-assembly/v1"
MEMORY_SUMMARY_VERSION = "memory-summary/v1"


class ContextSectionName(StrEnum):
    """Stable order of sections supplied to a model adapter."""

    REQUEST_CONSTRAINTS = "request_constraints"
    RECENT_MESSAGES = "recent_messages"
    VERSIONED_SUMMARY = "versioned_summary"
    RELATED_MEMORY = "related_memory"
    RELATED_EVIDENCE = "related_evidence"


class ContextBudget(ContractModel):
    """Per-section ceilings for one temporary context assembly."""

    total_tokens: int = Field(default=2048, ge=1)
    request_constraints_tokens: int = Field(default=256, ge=0)
    recent_messages_tokens: int = Field(default=768, ge=0)
    versioned_summary_tokens: int = Field(default=256, ge=0)
    related_memory_tokens: int = Field(default=384, ge=0)
    related_evidence_tokens: int = Field(default=384, ge=0)

    @property
    def section_budgets(self) -> dict[ContextSectionName, int]:
        return {
            ContextSectionName.REQUEST_CONSTRAINTS: self.request_constraints_tokens,
            ContextSectionName.RECENT_MESSAGES: self.recent_messages_tokens,
            ContextSectionName.VERSIONED_SUMMARY: self.versioned_summary_tokens,
            ContextSectionName.RELATED_MEMORY: self.related_memory_tokens,
            ContextSectionName.RELATED_EVIDENCE: self.related_evidence_tokens,
        }

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if sum(self.section_budgets.values()) > self.total_tokens:
            raise ValueError("section token budgets must not exceed total_tokens")
        return self


class ContextSourceRef(ContractModel):
    """Traceable source identity for a temporary context fragment."""

    source_type: NonEmptyStr
    source_id: NonEmptyStr
    versions: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    citation: NonEmptyStr | None = None


class ContextFragment(ContractModel):
    """One independently selectable, attributable context fragment."""

    fragment_id: NonEmptyStr
    text: NonEmptyStr
    source: ContextSourceRef
    priority: int = Field(ge=0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    estimated_tokens: int = Field(ge=1)


class ContextSection(ContractModel):
    """One ordered section and its selected/dropped source references."""

    section: ContextSectionName
    budget_tokens: int = Field(ge=0)
    used_tokens: int = Field(ge=0)
    fragments: tuple[ContextFragment, ...] = ()
    source_refs: tuple[ContextSourceRef, ...] = ()
    dropped_source_refs: tuple[ContextSourceRef, ...] = ()
    version_refs: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    truncated: bool = False

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        estimated = sum(fragment.estimated_tokens for fragment in self.fragments)
        if estimated != self.used_tokens:
            raise ValueError("used_tokens must equal selected fragment estimates")
        if self.used_tokens > self.budget_tokens:
            raise ValueError("selected context exceeds section budget")
        selected_sources = tuple(fragment.source for fragment in self.fragments)
        if self.source_refs != selected_sources:
            raise ValueError("source_refs must follow selected fragments")
        return self


class VersionedMemorySummary(ContractModel):
    """A rebuildable summary pinned to the authority watermark that produced it."""

    schema_version: Literal["memory-summary/v1"] = MEMORY_SUMMARY_VERSION
    summary_id: NonEmptyStr
    summary_version: int = Field(ge=1)
    content: NonEmptyStr
    source_authority_version: NonEmptyStr
    profile_version: NonEmptyStr
    policy_version: NonEmptyStr
    scope: MemoryIsolationKey | None = Field(default=None, discriminator="kind")


class ContextAssembly(ContractModel):
    """Versioned, temporary context; it is never a memory authority record."""

    schema_version: Literal["context-assembly/v1"] = CONTEXT_ASSEMBLY_VERSION
    assembly_id: NonEmptyStr
    policy_version: NonEmptyStr
    budget: ContextBudget
    estimated_tokens: int = Field(ge=0)
    sections: tuple[ContextSection, ...]

    @model_validator(mode="after")
    def validate_order_and_budget(self) -> Self:
        expected = tuple(ContextSectionName)
        actual = tuple(section.section for section in self.sections)
        if actual != expected:
            raise ValueError("context sections must use the declared fixed order")
        estimated = sum(section.used_tokens for section in self.sections)
        if estimated != self.estimated_tokens:
            raise ValueError("estimated_tokens must equal selected section tokens")
        if estimated > self.budget.total_tokens:
            raise ValueError("context assembly exceeds total token budget")
        return self

    @property
    def fragments(self) -> tuple[ContextFragment, ...]:
        """Return fragments in model-facing order without choosing a framework format."""

        return tuple(fragment for section in self.sections for fragment in section.fragments)

    @property
    def text(self) -> str:
        """Render a deterministic plain-text view for a temporary adapter."""

        return "\n\n".join(
            f"[{section.section.value}]\n" + "\n".join(fragment.text for fragment in section.fragments)
            for section in self.sections
            if section.fragments
        )


class ContextAssemblyRequest(ContractModel):
    """Typed input to :class:`ContextAssembler`; all fields are private/temporary."""

    assembly_id: NonEmptyStr
    policy_version: NonEmptyStr
    request_constraints: ContractPayload = Field(default_factory=dict)
    budget: ContextBudget = Field(default_factory=ContextBudget)
    recent_messages: tuple[MemoryConversationTurn, ...] = ()
    summaries: tuple[VersionedMemorySummary, ...] = ()
    memories: tuple[MemoryRecord, ...] = ()
    evidence: tuple[EvidenceItem, ...] = ()
    evidence_bundle: EvidenceBundle | None = None
    scope: MemoryIsolationKey | None = Field(default=None, discriminator="kind")


__all__ = [
    "CONTEXT_ASSEMBLY_VERSION",
    "MEMORY_SUMMARY_VERSION",
    "ContextAssembly",
    "ContextAssemblyRequest",
    "ContextBudget",
    "ContextFragment",
    "ContextSection",
    "ContextSectionName",
    "ContextSourceRef",
    "VersionedMemorySummary",
]
