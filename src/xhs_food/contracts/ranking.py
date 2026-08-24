"""Contracts for read-only personalized ranking of public candidates."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .base import ContractModel, ContractPayload, NonEmptyStr

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PublicCandidate(ContractModel):
    """Public candidate and score produced before personalization."""

    candidate_id: NonEmptyStr
    public_score: float = Field(ge=0.0, le=1.0)
    public_features: dict[NonEmptyStr, float] = Field(default_factory=dict)
    public_attributes: ContractPayload = Field(default_factory=dict)
    evidence_refs: tuple[NonEmptyStr, ...] = ()


class PersonalizedCandidate(ContractModel):
    """Ranking view; ``public_score`` remains the immutable public input."""

    candidate_id: NonEmptyStr
    public_score: float = Field(ge=0.0, le=1.0)
    personalized_score: float
    rank: int = Field(ge=1)
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    explanation_refs: tuple[NonEmptyStr, ...] = ()


class PersonalizedRanking(ContractModel):
    """Versioned reranker output with a digest of the unchanged public input."""

    schema_version: Literal["personalized-ranking/v1"] = "personalized-ranking/v1"
    policy_id: NonEmptyStr
    policy_version: NonEmptyStr
    preference_snapshot_id: NonEmptyStr
    preference_snapshot_version: int = Field(ge=1)
    public_input_digest: Digest
    candidates: tuple[PersonalizedCandidate, ...] = ()
    mutates_public_evidence: Literal[False] = False
    mutates_public_features: Literal[False] = False
    mutates_public_scores: Literal[False] = False


__all__ = [
    "Digest",
    "PersonalizedCandidate",
    "PersonalizedRanking",
    "PublicCandidate",
]
