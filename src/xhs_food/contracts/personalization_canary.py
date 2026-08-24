"""Closed-world canary and rollback contracts for personalization."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import ContractModel, NonEmptyStr
from .ranking import PersonalizedRanking

PERSONALIZATION_CANARY_VERSION = "personalization-canary/v1"
CanaryDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PersonalizationCanaryMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    CANARY = "canary"


class PersonalizationCanarySettings(ContractModel):
    """Independent controls; public refresh influence is permanently denied."""

    schema_version: Literal["personalization-canary/v1"] = PERSONALIZATION_CANARY_VERSION
    mode: PersonalizationCanaryMode = PersonalizationCanaryMode.OFF
    sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    default_strategy_version: NonEmptyStr = "public/v1"
    projection_warmup_enabled: bool = True
    public_refresh_priority_enabled: Literal[False] = False

    @model_validator(mode="after")
    def validate_sampling(self) -> PersonalizationCanarySettings:
        if self.mode is PersonalizationCanaryMode.OFF and self.sample_rate != 0:
            raise ValueError("off personalization canary cannot carry a sample rate")
        if self.mode is not PersonalizationCanaryMode.OFF and self.sample_rate <= 0:
            raise ValueError("active personalization canary requires a positive sample rate")
        return self


class PersonalizationCanaryObservation(ContractModel):
    """Low-cardinality observation containing digests, never private values."""

    schema_version: Literal["personalization-canary/v1"] = PERSONALIZATION_CANARY_VERSION
    request_key_hash: CanaryDigest
    mode: PersonalizationCanaryMode
    sampled: bool
    served_personalized: bool
    default_strategy_version: NonEmptyStr
    personalized_strategy_version: NonEmptyStr | None = None
    public_input_digest: CanaryDigest
    default_result_digest: CanaryDigest
    personalized_result_digest: CanaryDigest | None = None
    default_candidate_ids: tuple[NonEmptyStr, ...] = ()
    personalized_candidate_ids: tuple[NonEmptyStr, ...] = ()
    served_candidate_ids: tuple[NonEmptyStr, ...] = ()
    ranking_changed: bool = False
    cache_hit: bool = False
    outbox_lag_ms: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    private_records_used: int = Field(default=0, ge=0)
    private_values_exposed: Literal[False] = False
    public_refresh_priority_changed: Literal[False] = False

    @model_validator(mode="after")
    def validate_exposure(self) -> PersonalizationCanaryObservation:
        if self.served_personalized and not self.sampled:
            raise ValueError("served personalization must be sampled")
        if self.served_personalized and self.mode is not PersonalizationCanaryMode.CANARY:
            raise ValueError("shadow personalization cannot be served")
        if self.personalized_result_digest is None and self.personalized_candidate_ids:
            raise ValueError("personalized candidates require a personalized digest")
        expected_changed = self.sampled and (
            self.default_candidate_ids != self.personalized_candidate_ids
        )
        if self.ranking_changed != expected_changed:
            raise ValueError("ranking_changed must match candidate ordering")
        return self


class PersonalizationCanaryResult(ContractModel):
    """Served IDs plus an optional internal personalized ranking."""

    schema_version: Literal["personalization-canary/v1"] = PERSONALIZATION_CANARY_VERSION
    observation: PersonalizationCanaryObservation
    personalized_ranking: PersonalizedRanking | None = None


class PersonalizationRollbackReceipt(ContractModel):
    """Auditable B3 rollback result; authority facts are retained."""

    schema_version: Literal["personalization-canary/v1"] = PERSONALIZATION_CANARY_VERSION
    canary_mode: Literal[PersonalizationCanaryMode.OFF] = PersonalizationCanaryMode.OFF
    ranking_source: Literal["public/legacy"] = "public/legacy"
    personalization_enabled: Literal[False] = False
    postgres_authority_retained: Literal[True] = True
    redis_projection_warmup_enabled: Literal[False] = False
    public_refresh_priority_changed: Literal[False] = False


__all__ = [
    "CanaryDigest",
    "PERSONALIZATION_CANARY_VERSION",
    "PersonalizationCanaryMode",
    "PersonalizationCanaryObservation",
    "PersonalizationCanaryResult",
    "PersonalizationCanarySettings",
    "PersonalizationRollbackReceipt",
]
