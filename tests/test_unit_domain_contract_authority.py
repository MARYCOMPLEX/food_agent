"""Machine-checkable authority fixture for Domain Contract v1."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "authority" / "domain_contract_v1.json"
DECISIONS = ROOT / "openspec" / "changes" / "define-modular-architecture" / "decisions"


def _load() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _schema_digest(schema: dict[str, Any]) -> str:
    canonical = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _check_example(schema: dict[str, Any], value: Any, path: str = "$") -> None:
    """Check the fixture subset that the registry must enforce without a runtime dependency."""
    if "const" in schema:
        assert value == schema["const"], path
    if "enum" in schema:
        assert value in schema["enum"], path
    if "oneOf" in schema:
        assert any(_matches(candidate, value) for candidate in schema["oneOf"]), path

    schema_type = schema.get("type")
    if schema_type == "object":
        assert isinstance(value, dict), path
        required = set(schema.get("required", []))
        assert required <= set(value), path
        if schema.get("additionalProperties") is False:
            assert set(value) <= set(schema.get("properties", {})), path
        for name, child in schema.get("properties", {}).items():
            if name in value:
                _check_example(child, value[name], f"{path}.{name}")
    elif schema_type == "array":
        assert isinstance(value, list), path
        if "minItems" in schema:
            assert len(value) >= schema["minItems"], path
        if "items" in schema:
            for index, item in enumerate(value):
                _check_example(schema["items"], item, f"{path}[{index}]")
    elif schema_type == "string":
        assert isinstance(value, str), path
        if "minLength" in schema:
            assert len(value) >= schema["minLength"], path
    elif schema_type == "integer":
        assert type(value) is int, path
        if "minimum" in schema:
            assert value >= schema["minimum"], path
        if "maximum" in schema:
            assert value <= schema["maximum"], path
    elif schema_type == "number":
        assert isinstance(value, (int, float)) and not isinstance(value, bool), path
        if "minimum" in schema:
            assert value >= schema["minimum"], path
        if "maximum" in schema:
            assert value <= schema["maximum"], path


def _matches(schema: dict[str, Any], value: Any) -> bool:
    try:
        _check_example(schema, value)
    except AssertionError:
        return False
    return True


def test_domain_contract_adr_and_index_accept_oq9_and_oq10() -> None:
    adr = (DECISIONS / "ADR-0007-domain-contract-authority.md").read_text(encoding="utf-8")
    index = (DECISIONS / "README.md").read_text(encoding="utf-8")
    oq9 = next(line for line in index.splitlines() if line.startswith("| 9 |"))
    oq10 = next(line for line in index.splitlines() if line.startswith("| 10 |"))

    assert "- Status: Accepted" in adr
    assert "- Resolves: OQ-9, OQ-10" in adr
    assert "| Accepted | [ADR-0007]" in oq9
    assert "| Accepted | [ADR-0007]" in oq10


def test_discovery_is_startup_allowlisted_and_not_request_selected() -> None:
    discovery = _load()["discovery"]
    assert discovery == {
        "entryPointGroup": "food_agent.domain_packs",
        "loadedBy": "composition_root",
        "loadTime": "worker_startup",
        "deploymentAllowListRequired": True,
        "requestSelectedImports": False,
        "networkDiscovery": False,
        "directoryScanning": False,
    }


def test_required_methods_and_task_pins_are_explicit() -> None:
    authority = _load()
    names = [method["name"] for method in authority["requiredMethods"]]
    assert names == [
        "describe",
        "classify_constraints",
        "validate_evidence",
        "compute_features",
        "score_public",
        "build_final_output",
        "map_error",
    ]
    manifest = authority["manifestFixture"]
    assert manifest["methods"] == names
    assert authority["versioning"]["selectionTime"] == "task_admission_only"
    assert authority["versioning"]["inFlightRenegotiation"] is False
    assert set(authority["versioning"]["pinnedFields"]) >= {
        "domainId",
        "packVersion",
        "manifestDigest",
        "contractApi",
        "finalOutputSchemaIdAndDigest",
        "scoringPolicyVersion",
    }


def test_each_allowed_tool_has_strict_distinct_io_schemas_and_valid_examples() -> None:
    tools = _load()["manifestFixture"]["allowedTools"]
    ids = {tool["toolId"] for tool in tools}
    assert len(ids) == len(tools)
    for tool in tools:
        input_schema = tool["inputSchema"]
        output_schema = tool["outputSchema"]
        assert input_schema["$id"] != output_schema["$id"]
        assert re.fullmatch(r"[0-9a-f]{64}", tool["inputSchemaDigest"])
        assert re.fullmatch(r"[0-9a-f]{64}", tool["outputSchemaDigest"])
        assert tool["inputSchemaDigest"] == _schema_digest(input_schema)
        assert tool["outputSchemaDigest"] == _schema_digest(output_schema)
        assert input_schema["additionalProperties"] is False
        assert output_schema["additionalProperties"] is False
        _check_example(input_schema, tool["inputExample"], f"{tool['toolId']}.input")
        _check_example(output_schema, tool["outputExample"], f"{tool['toolId']}.output")
        assert tool["permission"]
        assert tool["timeoutMs"] > 0
        assert tool["errorCodes"]


def test_final_output_is_schema_validated_before_legacy_mapping() -> None:
    manifest = _load()["manifestFixture"]
    schema = manifest["finalOutputSchema"]
    assert schema["$id"] == "urn:food-agent:food:agent-final-output:v1"
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["finalOutputSchemaDigest"])
    assert manifest["finalOutputSchemaDigest"] == _schema_digest(schema)
    assert schema["additionalProperties"] is False
    _check_example(schema, manifest["finalOutputExample"], "finalOutput")
    assert manifest["finalOutputExample"]["schemaVersion"] == "food-agent-final-output/v1"


def test_source_declarations_do_not_embed_connectors_and_scoring_is_pure() -> None:
    manifest = _load()["manifestFixture"]
    for source in manifest["domainSources"]:
        assert set(source) == {"capability", "versionRange", "required"}
        assert "connector" not in source
        assert "class" not in source

    scoring = manifest["scoringPolicy"]
    assert scoring["mode"] == "pure_deterministic"
    assert "user_memory" in scoring["forbiddenInputs"]
    assert {"network", "database", "workflow", "connector"} <= set(scoring["forbiddenEffects"])


def test_extension_point_rulings_keep_one_workflow_and_refresh_owner() -> None:
    extensions = _load()["extensionPoints"]
    assert extensions["fixedWorkflow"] == "not_public_select_approved_profile_only"
    assert extensions["refreshCoordinator"] == "not_public_single_shared_owner"
    assert extensions["scoringPolicy"] == "controlled_pure_deterministic_extension"
    assert extensions["domainSources"] == "capability_declarations_only"


def test_registration_is_atomic_and_rejects_incomplete_or_impure_packs() -> None:
    authority = _load()
    registration = authority["registration"]
    assert registration["atomic"] is True
    assert registration["partialActivation"] is False
    assert authority["manifestFixture"]["manifestDigest"]
    assert {item["method"] for item in authority["manifestFixture"]["methodSchemas"]} == {
        method["name"] for method in authority["requiredMethods"]
    }

    cases = {case["case"]: case for case in authority["registrationCases"]}
    assert cases["complete_pack"]["accepted"] is True
    assert cases["missing_tool_output_schema"]["failureCode"] == "invalid_tool_contract"
    assert cases["invalid_final_output"]["failureCode"] == "invalid_final_output_schema"
    assert cases["connector_embedded_in_pack"]["failureCode"] == "invalid_manifest"
    assert cases["impure_score"]["failureCode"] == "impure_scoring_policy"
    assert cases["required_source_missing"]["failureCode"] == "unresolved_source_capability"
