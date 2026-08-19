"""Focused contract tests for OpenSpec S1 tasks 3.5 and 3.6."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from xhs_food.contracts import (
    DOMAIN_PACK_ENTRY_POINT_GROUP,
    AnonymousIsolationKey,
    DomainContractPin,
    DomainPackDiscoveryPolicy,
    DomainPackManifest,
    DomainRegistrationFailureCode,
    DomainSchemaBundle,
    MemoryLayer,
    MemoryRecord,
    PersonalizationPolicy,
    PreferenceSnapshot,
    UserIsolationKey,
    canonical_manifest_digest,
    canonical_schema_digest,
    intersect_personalized_capabilities,
    isolation_key_for,
    validate_domain_pack_registration,
    validate_json_schema_value,
)

ROOT = Path(__file__).resolve().parents[1]
DOMAIN_AUTHORITY = ROOT / "tests/fixtures/authority/domain_contract_v1.json"
DOMAIN_SCHEMA_BUNDLE = ROOT / "tests/fixtures/authority/domain_contract_schema_bundle_v1.json"
MEMORY_AUTHORITY = ROOT / "tests/fixtures/authority/memory_privacy_v1.json"
NOW = datetime(2026, 8, 19, tzinfo=UTC)


def _domain_authority() -> dict[str, Any]:
    return json.loads(DOMAIN_AUTHORITY.read_text(encoding="utf-8"))


def _memory_authority() -> dict[str, Any]:
    return json.loads(MEMORY_AUTHORITY.read_text(encoding="utf-8"))


def _domain_schema_bundle() -> DomainSchemaBundle:
    return DomainSchemaBundle.model_validate(
        json.loads(DOMAIN_SCHEMA_BUNDLE.read_text(encoding="utf-8"))
    )


def _domain_schema_bundle_value() -> dict[str, Any]:
    return json.loads(DOMAIN_SCHEMA_BUNDLE.read_text(encoding="utf-8"))


def _refresh_manifest_digest(manifest_value: dict[str, Any]) -> None:
    """Re-sign a structurally valid negative fixture so its target stage is reachable."""

    manifest_value["manifestDigest"] = "0" * 64
    try:
        manifest = DomainPackManifest.model_validate(manifest_value)
    except ValidationError:
        return
    manifest_value["manifestDigest"] = canonical_manifest_digest(
        manifest,
        _domain_schema_bundle(),
    )


class FixtureDomainPack:
    def __init__(self, manifest: DomainPackManifest) -> None:
        self.manifest = manifest

    def describe(self) -> DomainPackManifest:
        return self.manifest

    def classify_constraints(self, value: dict[str, Any]) -> dict[str, Any]:
        return value

    def validate_evidence(self, evidence: object) -> dict[str, Any]:
        return {"valid": evidence is not None}

    def compute_features(
        self,
        bundle: object,
        evidence_items: tuple[object, ...],
    ) -> dict[str, Any]:
        return {"bundle": str(bundle), "evidence_items": str(evidence_items)}

    def score_public(self, features: dict[str, Any]) -> dict[str, Any]:
        return features

    def build_final_output(self, value: dict[str, Any]) -> dict[str, Any]:
        return value

    def map_error(self, error: object) -> object:
        return error


def _registration(
    manifest_value: dict[str, Any],
    *,
    tools: dict[str, str] | None = None,
    sources: dict[str, str] | None = None,
):
    try:
        pack_manifest = DomainPackManifest.model_validate(manifest_value)
    except ValidationError:
        pack_manifest = DomainPackManifest.model_validate(
            _domain_authority()["manifestFixture"]
        )
    return validate_domain_pack_registration(
        manifest_value,
        FixtureDomainPack(pack_manifest),
        schema_bundle=_domain_schema_bundle(),
        core_version="1.0.0",
        registered_tool_capabilities=(
            tools
            if tools is not None
            else {"place.lookup": "1.0.0", "evidence.search_reviews": "1.0.0"}
        ),
        registered_source_capabilities=(
            sources
            if sources is not None
            else {"place.lookup": "1.0.0", "reviews.search": "1.0.0"}
        ),
    )


@pytest.mark.unit
def test_domain_manifest_discovery_and_task_pin_match_authority_fixture() -> None:
    authority = _domain_authority()
    manifest = DomainPackManifest.model_validate(authority["manifestFixture"])
    discovery = DomainPackDiscoveryPolicy.model_validate(authority["discovery"])

    assert discovery.entry_point_group == DOMAIN_PACK_ENTRY_POINT_GROUP
    assert discovery.request_selected_imports is False
    assert discovery.network_discovery is False
    assert manifest.model_dump(mode="json", by_alias=True) == authority["manifestFixture"]

    pin = DomainContractPin.from_manifest(manifest)
    assert pin.domain_id == manifest.domain_id
    assert pin.manifest_digest == manifest.manifest_digest
    assert {item.method for item in pin.method_schemas} == set(manifest.methods)
    assert {item.tool_id for item in pin.tool_schemas} == {
        tool.tool_id for tool in manifest.allowed_tools
    }
    assert pin.final_output_schema_id == manifest.final_output_schema["$id"]


@pytest.mark.unit
def test_complete_domain_pack_validates_once_and_can_activate_atomically() -> None:
    raw = _domain_authority()["manifestFixture"]
    result = _registration(raw)

    assert result.accepted is True
    assert result.activation_allowed is True
    assert result.failure_code is None
    assert result.contract_pin is not None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing_tool_output", DomainRegistrationFailureCode.INVALID_TOOL_CONTRACT),
        ("invalid_tool_schema", DomainRegistrationFailureCode.INVALID_TOOL_CONTRACT),
        ("tool_digest_mismatch", DomainRegistrationFailureCode.INVALID_TOOL_CONTRACT),
        ("invalid_tool_example", DomainRegistrationFailureCode.INVALID_TOOL_CONTRACT),
        ("external_tool_ref", DomainRegistrationFailureCode.INVALID_TOOL_CONTRACT),
        ("cross_bundle_tool_ref", DomainRegistrationFailureCode.INVALID_TOOL_CONTRACT),
        ("unresolved_local_fragment", DomainRegistrationFailureCode.INVALID_TOOL_CONTRACT),
        ("unresolved_tool_fragment", DomainRegistrationFailureCode.INVALID_TOOL_CONTRACT),
        ("invalid_final_output", DomainRegistrationFailureCode.INVALID_FINAL_OUTPUT_SCHEMA),
        ("external_final_ref", DomainRegistrationFailureCode.INVALID_FINAL_OUTPUT_SCHEMA),
        ("cross_bundle_final_ref", DomainRegistrationFailureCode.INVALID_FINAL_OUTPUT_SCHEMA),
        ("connector_in_manifest", DomainRegistrationFailureCode.INVALID_MANIFEST),
        ("impure_scoring", DomainRegistrationFailureCode.IMPURE_SCORING_POLICY),
    ],
)
def test_invalid_or_incomplete_pack_never_partially_activates(
    mutation: str, expected: DomainRegistrationFailureCode
) -> None:
    raw = copy.deepcopy(_domain_authority()["manifestFixture"])
    if mutation == "missing_tool_output":
        del raw["allowedTools"][0]["outputSchema"]
    elif mutation == "invalid_tool_schema":
        raw["allowedTools"][0]["inputSchema"]["type"] = "not-a-json-schema-type"
    elif mutation == "tool_digest_mismatch":
        raw["allowedTools"][0]["inputSchemaDigest"] = "0" * 64
    elif mutation == "invalid_tool_example":
        del raw["allowedTools"][0]["inputExample"]["query"]
    elif mutation == "external_tool_ref":
        schema = raw["allowedTools"][0]["inputSchema"]
        schema["$ref"] = "urn:food-agent:not-bundled:v1"
        raw["allowedTools"][0]["inputSchemaDigest"] = canonical_schema_digest(schema)
    elif mutation == "cross_bundle_tool_ref":
        schema = raw["allowedTools"][0]["inputSchema"]
        schema["properties"]["optionalError"] = {"$ref": "urn:food-agent:stable-error:v1"}
        raw["allowedTools"][0]["inputSchemaDigest"] = canonical_schema_digest(schema)
    elif mutation == "unresolved_local_fragment":
        schema = raw["allowedTools"][0]["inputSchema"]
        schema["properties"]["optionalError"] = {"$ref": "#/$defs/missing"}
        raw["allowedTools"][0]["inputSchemaDigest"] = canonical_schema_digest(schema)
    elif mutation == "unresolved_tool_fragment":
        schema = raw["allowedTools"][0]["inputSchema"]
        schema["properties"]["optionalError"] = {
            "$ref": "urn:food-agent:stable-error:v1#/$defs/missing"
        }
        raw["allowedTools"][0]["inputSchemaDigest"] = canonical_schema_digest(schema)
    elif mutation == "invalid_final_output":
        raw["finalOutputExample"]["recommendations"][0]["publicScore"] = 2
    elif mutation == "external_final_ref":
        schema = raw["finalOutputSchema"]
        schema["$ref"] = "https://schemas.example.invalid/final.json"
        raw["finalOutputSchemaDigest"] = canonical_schema_digest(schema)
    elif mutation == "cross_bundle_final_ref":
        schema = raw["finalOutputSchema"]
        schema["properties"]["optionalError"] = {"$ref": "urn:food-agent:stable-error:v1"}
        raw["finalOutputSchemaDigest"] = canonical_schema_digest(schema)
    elif mutation == "connector_in_manifest":
        raw["domainSources"][0]["connectorClass"] = "ConcretePoiConnector"
    else:
        raw["scoringPolicy"]["forbiddenEffects"].remove("network")

    _refresh_manifest_digest(raw)
    result = _registration(raw)

    assert result.accepted is False
    assert result.activation_allowed is False
    assert result.failure_code is expected
    assert result.contract_pin is None
    assert result.issues


@pytest.mark.unit
def test_missing_contract_method_and_source_capability_block_activation() -> None:
    raw = _domain_authority()["manifestFixture"]
    manifest = DomainPackManifest.model_validate(raw)

    class MissingMapError:
        def describe(self) -> DomainPackManifest:
            return manifest

    method_result = validate_domain_pack_registration(
        manifest,
        MissingMapError(),  # type: ignore[arg-type]
        schema_bundle=_domain_schema_bundle(),
        core_version="1.0.0",
        registered_tool_capabilities={
            "place.lookup": "1.0.0",
            "evidence.search_reviews": "1.0.0",
        },
        registered_source_capabilities={
            "place.lookup": "1.0.0",
            "reviews.search": "1.0.0",
        },
    )
    source_result = _registration(raw, sources={"reviews.search": "1.0.0"})

    assert method_result.failure_code is DomainRegistrationFailureCode.MISSING_CONTRACT_METHOD
    assert source_result.failure_code is DomainRegistrationFailureCode.UNRESOLVED_SOURCE_CAPABILITY


@pytest.mark.unit
def test_prerelease_source_version_does_not_satisfy_release_floor() -> None:
    result = _registration(
        _domain_authority()["manifestFixture"],
        sources={"place.lookup": "1.0.0-alpha", "reviews.search": "1.0.0"},
    )

    assert result.failure_code is DomainRegistrationFailureCode.UNRESOLVED_SOURCE_CAPABILITY


@pytest.mark.unit
@pytest.mark.parametrize(
    ("tools", "expected_path"),
    [
        ({}, "$.allowedTools[0].toolId"),
        ({"evidence.search_reviews": "1.0.0"}, "$.allowedTools[0].toolId"),
        (
            {"place.lookup": "1.1.0", "evidence.search_reviews": "1.0.0"},
            "$.allowedTools[0].toolVersion",
        ),
    ],
)
def test_unregistered_or_version_mismatched_tool_blocks_activation(
    tools: dict[str, str],
    expected_path: str,
) -> None:
    result = _registration(_domain_authority()["manifestFixture"], tools=tools)

    assert result.failure_code is DomainRegistrationFailureCode.INVALID_TOOL_CONTRACT
    assert result.activation_allowed is False
    assert result.issues[0].path == expected_path


@pytest.mark.unit
def test_numeric_prerelease_identifier_rejects_leading_zero() -> None:
    raw = _domain_authority()["manifestFixture"]
    raw["packVersion"] = "1.0.0-01"

    with pytest.raises(ValidationError, match="String should match pattern"):
        DomainPackManifest.model_validate(raw)

    manifest_schema = next(
        document.schema_document
        for document in _domain_schema_bundle().schemas
        if document.schema_id == "urn:food-agent:domain-pack-manifest:v1"
    )
    with pytest.raises(ValueError, match="does not match"):
        validate_json_schema_value(manifest_schema, raw)


@pytest.mark.unit
def test_optional_source_still_requires_a_valid_semver_range() -> None:
    raw = _domain_authority()["manifestFixture"]
    raw["domainSources"][1]["required"] = False
    raw["domainSources"][1]["versionRange"] = "not-a-version-range"

    result = _registration(raw)

    assert result.failure_code is DomainRegistrationFailureCode.INVALID_MANIFEST
    assert result.activation_allowed is False

    manifest_schema = next(
        document.schema_document
        for document in _domain_schema_bundle().schemas
        if document.schema_id == "urn:food-agent:domain-pack-manifest:v1"
    )
    with pytest.raises(ValueError, match="does not match"):
        validate_json_schema_value(manifest_schema, raw)


@pytest.mark.unit
def test_build_method_output_must_match_agent_final_output_schema() -> None:
    raw = _domain_authority()["manifestFixture"]
    final_schema = raw["finalOutputSchema"]
    final_schema["properties"]["detail"] = {"type": "string"}
    raw["finalOutputSchemaDigest"] = canonical_schema_digest(final_schema)
    raw["manifestDigest"] = "0" * 64
    manifest = DomainPackManifest.model_validate(raw)
    raw["manifestDigest"] = canonical_manifest_digest(manifest, _domain_schema_bundle())

    result = _registration(raw)

    assert result.failure_code is DomainRegistrationFailureCode.INVALID_FINAL_OUTPUT_SCHEMA
    assert result.activation_allowed is False
    assert result.issues[0].path == "$.finalOutputSchema"


@pytest.mark.unit
def test_tool_io_and_agent_final_values_are_schema_validated() -> None:
    manifest = DomainPackManifest.model_validate(_domain_authority()["manifestFixture"])
    tool = manifest.allowed_tools[0]

    tool.validate_input(tool.input_example)
    tool.validate_output(tool.output_example)
    manifest.validate_final_output(manifest.final_output_example)

    with pytest.raises(ValueError, match="required"):
        tool.validate_input({"schemaVersion": "place.lookup/input/v1"})
    with pytest.raises(ValueError, match="greater than the maximum"):
        invalid = manifest.model_dump(mode="json", by_alias=True)["finalOutputExample"]
        invalid["recommendations"][0]["publicScore"] = 2
        manifest.validate_final_output(invalid)


@pytest.mark.unit
def test_manifest_digest_preimage_is_stable_order_independent_and_example_free() -> None:
    authority = _domain_authority()
    manifest = DomainPackManifest.model_validate(authority["manifestFixture"])
    bundle_value = _domain_schema_bundle_value()
    bundle = DomainSchemaBundle.model_validate(bundle_value)

    assert canonical_manifest_digest(manifest, bundle) == manifest.manifest_digest
    assert authority["versioning"]["manifestDigestPreimage"] == {
        "version": "domain-manifest-digest-preimage/v1",
        "algorithm": "sha256",
        "canonicalization": "utf8-json-sort-object-keys-no-whitespace",
        "schemaProjection": "bundle-version-and-sorted-schema-id-digest-pins",
        "representativeExamplesIncluded": False,
    }

    reordered = copy.deepcopy(bundle_value)
    reordered["schemas"].reverse()
    example_only_change = copy.deepcopy(bundle_value)
    stable_error = next(
        item
        for item in example_only_change["schemas"]
        if item["schemaId"] == "urn:food-agent:stable-error:v1"
    )
    stable_error["examples"][0]["message"] = "non-semantic fixture note"
    manifest_example_change = manifest.model_dump(mode="json", by_alias=True)
    manifest_example_change["finalOutputExample"]["summary"] = "non-semantic example"
    manifest_example_change["allowedTools"][0]["inputExample"]["query"] = (
        "non-semantic example"
    )

    assert canonical_manifest_digest(
        manifest, DomainSchemaBundle.model_validate(reordered)
    ) == manifest.manifest_digest
    assert canonical_manifest_digest(
        manifest, DomainSchemaBundle.model_validate(example_only_change)
    ) == manifest.manifest_digest
    assert canonical_manifest_digest(
        DomainPackManifest.model_validate(manifest_example_change), bundle
    ) == manifest.manifest_digest


@pytest.mark.unit
def test_manifest_and_bundle_json_are_deeply_immutable() -> None:
    manifest = DomainPackManifest.model_validate(_domain_authority()["manifestFixture"])
    bundle = _domain_schema_bundle()

    with pytest.raises(TypeError, match="immutable"):
        manifest.final_output_schema["properties"]["summary"]["type"] = "integer"
    with pytest.raises(TypeError, match="immutable"):
        manifest.allowed_tools[0].input_example["query"] = "changed"
    with pytest.raises(TypeError, match="immutable"):
        manifest.final_output_example["recommendations"].append({})
    with pytest.raises(TypeError, match="immutable"):
        bundle.schemas[0].schema_document["type"] = "array"


@pytest.mark.unit
@pytest.mark.parametrize(
    "reference",
    ["https://schemas.example.invalid/remote.json", "urn:food-agent:not-bundled:v1"],
)
def test_external_or_unbundled_schema_refs_are_rejected(reference: str) -> None:
    bundle_value = _domain_schema_bundle_value()
    document = bundle_value["schemas"][0]
    document["schema"]["$ref"] = reference
    document["schemaDigest"] = canonical_schema_digest(document["schema"])

    with pytest.raises(ValidationError, match="sealed local schema bundle"):
        DomainSchemaBundle.model_validate(bundle_value)


@pytest.mark.unit
def test_runtime_schema_validation_rejects_nonlocal_refs() -> None:
    external_id = "urn:food-agent:not-bundled:v1"
    local_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:food-agent:test-local:v1",
        "$ref": external_id,
    }

    with pytest.raises(ValueError, match="sealed local schema bundle"):
        validate_json_schema_value(local_schema, {})


@pytest.mark.unit
def test_registration_failure_codes_are_owned_by_validation_stage() -> None:
    manifest_value = _domain_authority()["manifestFixture"]
    manifest = DomainPackManifest.model_validate(manifest_value)
    invalid_bundle = _domain_schema_bundle_value()
    stable_error = next(
        item
        for item in invalid_bundle["schemas"]
        if item["schemaId"] == "urn:food-agent:stable-error:v1"
    )
    stable_error["examples"][0]["category"] = "not-a-stable-category"

    result = validate_domain_pack_registration(
        manifest_value,
        FixtureDomainPack(manifest),
        schema_bundle=invalid_bundle,
        core_version="1.0.0",
        registered_tool_capabilities={
            "place.lookup": "1.0.0",
            "evidence.search_reviews": "1.0.0",
        },
        registered_source_capabilities={
            "place.lookup": "1.0.0",
            "reviews.search": "1.0.0",
        },
    )

    assert result.failure_code is DomainRegistrationFailureCode.INVALID_SCHEMA_BUNDLE
    assert result.issues[0].path == "$.schemaBundle"


@pytest.mark.unit
def test_stale_manifest_digest_precedes_later_semantic_failures() -> None:
    raw = copy.deepcopy(_domain_authority()["manifestFixture"])
    raw["scoringPolicy"]["forbiddenEffects"].remove("network")

    result = _registration(raw)

    assert result.failure_code is DomainRegistrationFailureCode.INVALID_MANIFEST
    assert result.issues[0].path == "$.manifestDigest"


@pytest.mark.unit
def test_memory_authority_examples_round_trip_and_keep_full_isolation_scope() -> None:
    authority = _memory_authority()
    records = [MemoryRecord.model_validate(item) for item in authority["exampleRecords"]]

    assert {record.layer for record in records} == set(MemoryLayer)
    assert [record.model_dump(mode="json", by_alias=True) for record in records] == authority[
        "exampleRecords"
    ]

    anonymous_key = isolation_key_for(records[0])
    user_key = isolation_key_for(records[1])
    assert isinstance(anonymous_key, AnonymousIsolationKey)
    assert anonymous_key.partition == (
        records[0].tenant_id,
        records[0].subject.id,
        records[0].session_id,
    )
    assert isinstance(user_key, UserIsolationKey)
    assert user_key.partition == (records[1].tenant_id, records[1].subject.id)
    assert anonymous_key.namespaced_key("session-window").startswith("tenant_id:")
    assert user_key.namespaced_key("preference").startswith("tenant_id:")


@pytest.mark.unit
def test_memory_layer_invariants_reject_cross_scope_or_misclassified_records() -> None:
    records = _memory_authority()["exampleRecords"]

    inferred_anonymous = copy.deepcopy(records[2])
    inferred_anonymous["subject"] = records[0]["subject"]
    inferred_anonymous["sessionId"] = records[0]["sessionId"]
    with pytest.raises(ValidationError, match="authenticated user"):
        MemoryRecord.model_validate(inferred_anonymous)

    session_without_scope = copy.deepcopy(records[0])
    session_without_scope["sessionId"] = None
    with pytest.raises(ValidationError, match="session_id"):
        MemoryRecord.model_validate(session_without_scope)

    explicit_with_confidence = copy.deepcopy(records[1])
    explicit_with_confidence["confidence"] = 0.5
    with pytest.raises(ValidationError, match="confidence is forbidden"):
        MemoryRecord.model_validate(explicit_with_confidence)


@pytest.mark.unit
def test_preference_snapshot_and_policy_are_private_versioned_and_user_scoped() -> None:
    user_key = UserIsolationKey(
        tenant_id="tenant-cn-1",
        user_id="user-2b4aa1b95c884d64",
    )
    snapshot = PreferenceSnapshot(
        snapshot_id="snapshot-1",
        snapshot_version=3,
        isolation_key=user_key,
        policy_version="memory-policy/v1",
        source_record_versions={"mem-explicit-001": "2026-08-18T10:00:00Z"},
        explicit_hard_constraints={"diet.spice": "mild"},
        generated_at=NOW,
    )
    policy = PersonalizationPolicy(
        policy_id="personalization-food",
        policy_version="personalization-policy/v1",
        isolation_key=user_key,
        preference_snapshot_id=snapshot.snapshot_id,
        preference_snapshot_version=snapshot.snapshot_version,
        hard_filters={"diet.spice": "mild"},
        selected_source_subset=("place.lookup",),
        selected_tool_subset=("place.lookup",),
        ranking_weights={"locality": 1.2},
        explanation_refs=("mem-explicit-001",),
    )

    assert PreferenceSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot
    assert PersonalizationPolicy.model_validate_json(policy.model_dump_json()) == policy
    assert policy.mutates_query_family_identity is False
    assert policy.mutates_public_evidence is False
    assert policy.mutates_public_scores is False
    assert policy.public_refresh_influence is False


@pytest.mark.unit
def test_personalization_can_only_narrow_authorized_pack_capabilities() -> None:
    effective = intersect_personalized_capabilities(
        pack_sources={"place.lookup", "reviews.search"},
        authorized_sources={"place.lookup", "reviews.search", "private.source"},
        selected_sources={"place.lookup", "private.source"},
        pack_tools={"place.lookup", "evidence.search_reviews"},
        authorized_tools={"place.lookup", "admin.tool"},
        selected_tools={"place.lookup", "admin.tool"},
    )

    assert effective.sources == ("place.lookup",)
    assert effective.tools == ("place.lookup",)
