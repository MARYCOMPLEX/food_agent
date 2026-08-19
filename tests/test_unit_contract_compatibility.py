"""Compatibility gates for versioned, domain-neutral internal contracts."""

from __future__ import annotations

import copy
from enum import StrEnum

import pytest
from pydantic import Field

from xhs_food.contracts import (
    CompatibilityIssueCode,
    ModelMessage,
    ToolCall,
    compare_contract_models,
    compare_contract_schemas,
    round_trip_contract,
)
from xhs_food.contracts.base import SchemaVersion, VersionedContract


class StatusV1(StrEnum):
    CREATED = "created"
    RUNNING = "running"


class StatusWithoutRunning(StrEnum):
    CREATED = "created"


class StatusWithCompleted(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"


class FixtureContractV1(VersionedContract):
    contract_id: str
    count: int
    status: StatusV1


class FixtureContractAdditive(VersionedContract):
    schema_version: SchemaVersion = Field(default_factory=lambda: SchemaVersion("1.1"))
    contract_id: str
    count: int
    status: StatusV1
    note: str | None = None


class FixtureContractRequiredRemoved(VersionedContract):
    schema_version: SchemaVersion = Field(default_factory=lambda: SchemaVersion("2.0"))
    contract_id: str
    count: int | None = None
    status: StatusV1


class FixtureContractFieldRemoved(VersionedContract):
    schema_version: SchemaVersion = Field(default_factory=lambda: SchemaVersion("2.0"))
    contract_id: str
    status: StatusV1


class FixtureContractTypeChanged(VersionedContract):
    schema_version: SchemaVersion = Field(default_factory=lambda: SchemaVersion("2.0"))
    contract_id: str
    count: str
    status: StatusV1


class FixtureContractEnumRemoved(VersionedContract):
    schema_version: SchemaVersion = Field(default_factory=lambda: SchemaVersion("2.0"))
    contract_id: str
    count: int
    status: StatusWithoutRunning


class FixtureContractEnumAdded(VersionedContract):
    schema_version: SchemaVersion = Field(default_factory=lambda: SchemaVersion("2.0"))
    contract_id: str
    count: int
    status: StatusWithCompleted


@pytest.mark.unit
def test_contract_round_trip_uses_wire_json_and_preserves_typed_values() -> None:
    value = FixtureContractV1(
        contract_id="合同-fixture",
        count=3,
        status=StatusV1.RUNNING,
    )

    restored = round_trip_contract(value)

    assert restored == value
    assert restored is not value
    assert restored.status is StatusV1.RUNNING


@pytest.mark.unit
def test_optional_additive_field_is_mixed_version_compatible() -> None:
    report = compare_contract_models(FixtureContractV1, FixtureContractAdditive)
    old_value = FixtureContractV1(
        contract_id="fixture",
        count=1,
        status=StatusV1.CREATED,
    )
    new_value = FixtureContractAdditive(
        contract_id="fixture",
        count=1,
        status=StatusV1.CREATED,
        note="optional",
    )

    assert report.compatible is True
    assert report.issues == ()
    assert FixtureContractAdditive.model_validate_json(old_value.model_dump_json()).note is None
    assert (
        FixtureContractV1.model_validate_json(new_value.model_dump_json()).contract_id
        == "fixture"
    )


@pytest.mark.unit
def test_port_consumer_ignores_a_future_optional_field() -> None:
    call = ToolCall.model_validate(
        {
            "call_id": "call-1",
            "tool_name": "source.collect",
            "arguments": {},
            "future_optional_hint": "new-producer-value",
        }
    )

    assert call.call_id == "call-1"
    assert "future_optional_hint" not in call.model_dump()

    message = ModelMessage.model_validate(
        {
            "role": "user",
            "content": "fixture",
            "future_optional_metadata": {"trace": "new-producer-value"},
        }
    )

    assert message.content == "fixture"
    assert "future_optional_metadata" not in message.model_dump()


@pytest.mark.unit
@pytest.mark.parametrize(
    "candidate",
    [FixtureContractRequiredRemoved, FixtureContractFieldRemoved],
)
def test_required_field_removal_is_a_breaking_change(
    candidate: type[VersionedContract],
) -> None:
    report = compare_contract_models(FixtureContractV1, candidate)

    assert report.compatible is False
    assert any(
        issue.code is CompatibilityIssueCode.REQUIRED_FIELD_REMOVED
        and issue.path == "$.count"
        for issue in report.issues
    )


@pytest.mark.unit
def test_field_type_change_is_a_breaking_change() -> None:
    report = compare_contract_models(FixtureContractV1, FixtureContractTypeChanged)

    assert report.compatible is False
    issue = next(
        item
        for item in report.issues
        if item.code is CompatibilityIssueCode.FIELD_TYPE_CHANGED
        and item.path == "$.count"
    )
    assert issue.previous == ["integer"]
    assert issue.candidate == ["string"]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("candidate", "code", "changed_value"),
    [
        (
            FixtureContractEnumRemoved,
            CompatibilityIssueCode.ENUM_VALUES_REMOVED,
            "running",
        ),
        (
            FixtureContractEnumAdded,
            CompatibilityIssueCode.ENUM_VALUES_ADDED,
            "completed",
        ),
    ],
)
def test_enum_value_changes_are_breaking_for_mixed_versions(
    candidate: type[VersionedContract],
    code: CompatibilityIssueCode,
    changed_value: str,
) -> None:
    report = compare_contract_models(FixtureContractV1, candidate)

    assert report.compatible is False
    issue = next(item for item in report.issues if item.code is code)
    assert issue.path == "$.status"
    assert changed_value in (issue.previous or issue.candidate)


@pytest.mark.unit
def test_nested_schema_changes_are_reported_at_stable_paths() -> None:
    previous = {
        "type": "object",
        "properties": {
            "payload": {
                "type": "object",
                "properties": {"label": {"type": "string"}},
                "required": ["label"],
            }
        },
        "required": ["payload"],
    }
    candidate = {
        "type": "object",
        "properties": {
            "payload": {
                "type": "object",
                "properties": {"label": {"type": "integer"}},
                "required": ["label"],
            }
        },
        "required": ["payload"],
    }

    report = compare_contract_schemas(previous, candidate)

    assert [(issue.code, issue.path) for issue in report.issues] == [
        (CompatibilityIssueCode.FIELD_TYPE_CHANGED, "$.payload.label")
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("previous", "candidate", "path"),
    [
        (
            {"type": "number", "maximum": 1},
            {"type": "number", "maximum": 0.5},
            "$.maximum",
        ),
        (
            {"type": "string", "pattern": "^[a-z]+$"},
            {"type": "string", "pattern": "^[a-z0-9]+$"},
            "$.pattern",
        ),
        (
            {"type": "object", "additionalProperties": False},
            {"type": "object", "additionalProperties": True},
            "$.additionalProperties",
        ),
    ],
)
def test_validation_constraint_changes_are_breaking(
    previous: dict[str, object],
    candidate: dict[str, object],
    path: str,
) -> None:
    report = compare_contract_schemas(previous, candidate)

    assert report.compatible is False
    assert any(
        issue.code is CompatibilityIssueCode.VALIDATION_CONSTRAINT_CHANGED
        and issue.path == path
        for issue in report.issues
    )


@pytest.mark.unit
def test_array_item_constraint_changes_are_compared_recursively() -> None:
    report = compare_contract_schemas(
        {"type": "array", "items": {"type": "string"}},
        {"type": "array", "items": {"type": "integer"}},
    )

    assert report.compatible is False
    assert any(
        issue.code is CompatibilityIssueCode.FIELD_TYPE_CHANGED and issue.path == "$[]"
        for issue in report.issues
    )


@pytest.mark.unit
def test_union_wrapped_nested_constraint_changes_are_breaking() -> None:
    previous = {
        "type": "object",
        "properties": {
            "payload": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {"label": {"type": "string"}},
                        "required": ["label"],
                    },
                    {"type": "null"},
                ]
            }
        },
    }
    candidate = {
        "type": "object",
        "properties": {
            "payload": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {"label": {"type": "integer"}},
                        "required": ["label"],
                    },
                    {"type": "null"},
                ]
            }
        },
    }

    report = compare_contract_schemas(previous, candidate)

    assert report.compatible is False
    assert any(
        issue.code is CompatibilityIssueCode.VALIDATION_CONSTRAINT_CHANGED
        and issue.path == "$.payload.anyOf"
        for issue in report.issues
    )


@pytest.mark.unit
@pytest.mark.parametrize("union_keyword", ["anyOf", "oneOf"])
def test_union_changes_behind_local_refs_are_breaking(union_keyword: str) -> None:
    previous = {
        "$defs": {
            "Payload": {
                "type": "object",
                "properties": {"label": {"type": "string"}},
                "required": ["label"],
            }
        },
        union_keyword: [
            {"$ref": "#/$defs/Payload"},
            {"type": "null"},
        ],
    }
    candidate = copy.deepcopy(previous)
    candidate["$defs"]["Payload"]["properties"]["label"]["type"] = "integer"

    report = compare_contract_schemas(previous, candidate)

    assert report.compatible is False
    assert any(
        issue.code is CompatibilityIssueCode.VALIDATION_CONSTRAINT_CHANGED
        and issue.path == f"$.{union_keyword}"
        for issue in report.issues
    )


@pytest.mark.unit
def test_recursive_local_refs_terminate_and_compare_equal() -> None:
    schema = {
        "$defs": {
            "Node": {
                "type": "object",
                "properties": {
                    "children": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/Node"},
                    }
                },
            }
        },
        "$ref": "#/$defs/Node",
    }

    report = compare_contract_schemas(schema, schema)

    assert report.compatible is True
    assert report.issues == ()


@pytest.mark.unit
@pytest.mark.parametrize("union_keyword", ["anyOf", "oneOf"])
def test_recursive_union_refs_terminate_and_compare_equal(union_keyword: str) -> None:
    schema = {
        "$defs": {
            "Node": {
                union_keyword: [
                    {"type": "string"},
                    {"$ref": "#/$defs/Node"},
                ]
            }
        },
        "$ref": "#/$defs/Node",
    }

    report = compare_contract_schemas(schema, copy.deepcopy(schema))

    assert report.compatible is True
    assert report.issues == ()


@pytest.mark.unit
def test_union_branch_order_and_annotations_are_non_structural() -> None:
    previous = {
        "anyOf": [
            {"type": "string", "title": "Old label"},
            {"type": "null"},
        ]
    }
    candidate = {
        "anyOf": [
            {"type": "null", "description": "No value"},
            {"type": "string", "title": "New label"},
        ]
    }

    report = compare_contract_schemas(previous, candidate)

    assert report.compatible is True
    assert report.issues == ()


@pytest.mark.unit
def test_optional_field_added_inside_reordered_union_is_compatible() -> None:
    previous = {
        "anyOf": [
            {
                "type": "object",
                "properties": {"label": {"type": "string"}},
                "required": ["label"],
            },
            {"type": "null"},
        ]
    }
    candidate = {
        "anyOf": [
            {"type": "null"},
            {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["label"],
            },
        ]
    }

    report = compare_contract_schemas(previous, candidate)

    assert report.compatible is True
    assert report.issues == ()


@pytest.mark.unit
def test_compatibility_report_is_deterministic_and_json_serializable() -> None:
    first = compare_contract_models(FixtureContractV1, FixtureContractEnumAdded)
    second = compare_contract_models(FixtureContractV1, FixtureContractEnumAdded)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert "enum_values_added" in first.model_dump_json()
