"""Framework-neutral primitives shared by internal contracts."""

from __future__ import annotations

from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, RootModel

NonEmptyStr = Annotated[str, Field(min_length=1)]
ContractPayload = dict[str, JsonValue]
Timestamp = AwareDatetime


class SchemaVersion(RootModel[str]):
    """A serialization version independent of any transport or framework."""

    model_config = ConfigDict(frozen=True)
    root: Annotated[str, Field(pattern=r"^[1-9][0-9]*\.[0-9]+$")]

    def __str__(self) -> str:
        return self.root


def schema_version_v1() -> SchemaVersion:
    """Return the initial additive contract schema version."""

    return SchemaVersion("1.0")


class ContractModel(BaseModel):
    """Immutable JSON-compatible value model with additive-read semantics."""

    model_config = ConfigDict(
        extra="ignore",
        frozen=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )


class VersionedContract(ContractModel):
    """Base for every command, event, and cross-module data envelope."""

    schema_version: SchemaVersion = Field(default_factory=schema_version_v1)


class TimeRange(ContractModel):
    """Optional public time bounds without domain-specific interpretation."""

    starts_at: Timestamp | None = None
    ends_at: Timestamp | None = None


__all__ = [
    "ContractModel",
    "ContractPayload",
    "JsonValue",
    "NonEmptyStr",
    "SchemaVersion",
    "TimeRange",
    "Timestamp",
    "VersionedContract",
    "schema_version_v1",
]
