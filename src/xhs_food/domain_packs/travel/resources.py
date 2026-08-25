"""Generated-in-code Travel manifest and schema bundle.

The declarations are immutable and digested exactly like the bundled Food
resources. Keeping the small proof pack in Python makes the fixture easy to
inspect while preserving the same Domain Contract validation path.
"""

from __future__ import annotations

from functools import cache
from typing import Any, cast

from xhs_food.contracts import (
    AllowedToolContract,
    BundledSchemaDocument,
    DomainContractMethod,
    DomainPackManifest,
    DomainPolicyProfiles,
    DomainSchemaBundle,
    DomainSchemaDeclarations,
    DomainSourceCapability,
    MethodSchemaContract,
    PublicScoringPolicy,
    canonical_manifest_digest,
    canonical_schema_digest,
)

TRAVEL_DOMAIN_ID = "travel"
TRAVEL_PACK_VERSION = "1.0.0"
_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _schema(schema_id: str, *, properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "$schema": _DIALECT,
        "$id": schema_id,
        "type": "object",
        "additionalProperties": False,
        "required": required or [],
        "properties": properties or {},
    }


def _document(document: dict[str, Any], example: dict[str, Any]) -> BundledSchemaDocument:
    return BundledSchemaDocument(
        schema_id=cast(str, document["$id"]),
        schema_digest=canonical_schema_digest(document),
        schema=document,
        examples=(cast(Any, example),),
    )


@cache
def load_travel_schema_bundle() -> DomainSchemaBundle:
    method_ids = {
        "describe-input": "urn:food-agent:domain-method:describe-input:v1",
        "describe-output": "urn:food-agent:domain-pack-manifest:v1",
        "classify-input": "urn:food-agent:domain-method:classify-constraints-input:v1",
        "classify-output": "urn:food-agent:domain-method:classify-constraints-output:v1",
        "validate-input": "urn:food-agent:domain-method:validate-evidence-input:v1",
        "validate-output": "urn:food-agent:domain-method:validate-evidence-output:v1",
        "features-input": "urn:food-agent:domain-method:compute-features-input:v1",
        "features-output": "urn:food-agent:domain-method:compute-features-output:v1",
        "score-input": "urn:food-agent:domain-method:score-public-input:v1",
        "score-output": "urn:food-agent:domain-method:score-public-output:v1",
        "final-input": "urn:food-agent:domain-method:build-final-output-input:v1",
        "final-output": "urn:food-agent:domain-method:build-final-output-output:v1",
        "error-input": "urn:food-agent:domain-method:map-error-input:v1",
        "error-output": "urn:food-agent:stable-error:v1",
    }
    documents: list[BundledSchemaDocument] = []
    generic = {
        key: _schema(value)
        for key, value in method_ids.items()
        if key not in {"final-output", "describe-output"}
    }
    for _key, document in generic.items():
        documents.append(_document(document, {}))
    describe_schema = _schema(method_ids["describe-output"])
    describe_schema["additionalProperties"] = True
    documents.append(_document(describe_schema, {}))

    method_output_schema = _schema(
        method_ids["final-output"],
        properties={
            "schemaVersion": {"const": "travel-agent-final-output/v1"},
            "summary": {"type": "string"},
            "itineraries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["entityId", "publicScore", "stops", "season", "ticket", "crowding", "durationMinutes", "suitableFor", "explanationRefs"],
                    "properties": {
                        "entityId": {"type": "string", "minLength": 1},
                        "publicScore": {"type": "number", "minimum": 0, "maximum": 1},
                        "stops": {"type": "array", "items": {"type": "string"}},
                        "season": {"type": "string"},
                        "ticket": {"type": "string"},
                        "crowding": {"type": "string"},
                        "durationMinutes": {"type": "integer", "minimum": 0},
                        "suitableFor": {"type": "array", "items": {"type": "string"}},
                        "explanationRefs": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
        required=["schemaVersion", "summary", "itineraries"],
    )
    documents.append(
        _document(
            method_output_schema,
            {"schemaVersion": "travel-agent-final-output/v1", "summary": "", "itineraries": []},
        )
    )
    output_schema = dict(method_output_schema)
    output_schema["$id"] = "urn:food-agent:travel:final-output:v1"
    domain_schema_ids = {
        "entities": "urn:food-agent:travel:entities:v1",
        "relations": "urn:food-agent:travel:relations:v1",
        "evidence": "urn:food-agent:travel:evidence-types:v1",
        "features": "urn:food-agent:travel:feature-set:v1",
        "personalization": "urn:food-agent:travel:personalization-slots:v1",
    }
    for value in domain_schema_ids.values():
        documents.append(_document(_schema(value), {}))
    return DomainSchemaBundle(bundle_version="domain-contract-schema-bundle/v1", schemas=tuple(documents))


@cache
def load_travel_manifest() -> DomainPackManifest:
    bundle = load_travel_schema_bundle()
    by_id = {item.schema_id: item for item in bundle.schemas}
    domain_schema_ids = {
        "entities": "urn:food-agent:travel:entities:v1",
        "relations": "urn:food-agent:travel:relations:v1",
        "evidence": "urn:food-agent:travel:evidence-types:v1",
        "features": "urn:food-agent:travel:feature-set:v1",
        "personalization": "urn:food-agent:travel:personalization-slots:v1",
    }
    methods = tuple(DomainContractMethod)
    method_schemas = tuple(
        MethodSchemaContract(
            method=method,
            input_schema_id={
                DomainContractMethod.DESCRIBE: "urn:food-agent:domain-method:describe-input:v1",
                DomainContractMethod.CLASSIFY_CONSTRAINTS: "urn:food-agent:domain-method:classify-constraints-input:v1",
                DomainContractMethod.VALIDATE_EVIDENCE: "urn:food-agent:domain-method:validate-evidence-input:v1",
                DomainContractMethod.COMPUTE_FEATURES: "urn:food-agent:domain-method:compute-features-input:v1",
                DomainContractMethod.SCORE_PUBLIC: "urn:food-agent:domain-method:score-public-input:v1",
                DomainContractMethod.BUILD_FINAL_OUTPUT: "urn:food-agent:domain-method:build-final-output-input:v1",
                DomainContractMethod.MAP_ERROR: "urn:food-agent:domain-method:map-error-input:v1",
            }[method],
            input_schema_digest=by_id[{
                DomainContractMethod.DESCRIBE: "urn:food-agent:domain-method:describe-input:v1",
                DomainContractMethod.CLASSIFY_CONSTRAINTS: "urn:food-agent:domain-method:classify-constraints-input:v1",
                DomainContractMethod.VALIDATE_EVIDENCE: "urn:food-agent:domain-method:validate-evidence-input:v1",
                DomainContractMethod.COMPUTE_FEATURES: "urn:food-agent:domain-method:compute-features-input:v1",
                DomainContractMethod.SCORE_PUBLIC: "urn:food-agent:domain-method:score-public-input:v1",
                DomainContractMethod.BUILD_FINAL_OUTPUT: "urn:food-agent:domain-method:build-final-output-input:v1",
                DomainContractMethod.MAP_ERROR: "urn:food-agent:domain-method:map-error-input:v1",
            }[method]].schema_digest,
            output_schema_id={
                DomainContractMethod.DESCRIBE: "urn:food-agent:domain-pack-manifest:v1",
                DomainContractMethod.CLASSIFY_CONSTRAINTS: "urn:food-agent:domain-method:classify-constraints-output:v1",
                DomainContractMethod.VALIDATE_EVIDENCE: "urn:food-agent:domain-method:validate-evidence-output:v1",
                DomainContractMethod.COMPUTE_FEATURES: "urn:food-agent:domain-method:compute-features-output:v1",
                DomainContractMethod.SCORE_PUBLIC: "urn:food-agent:domain-method:score-public-output:v1",
                DomainContractMethod.BUILD_FINAL_OUTPUT: "urn:food-agent:domain-method:build-final-output-output:v1",
                DomainContractMethod.MAP_ERROR: "urn:food-agent:stable-error:v1",
            }[method],
            output_schema_digest=by_id[{
                DomainContractMethod.DESCRIBE: "urn:food-agent:domain-pack-manifest:v1",
                DomainContractMethod.CLASSIFY_CONSTRAINTS: "urn:food-agent:domain-method:classify-constraints-output:v1",
                DomainContractMethod.VALIDATE_EVIDENCE: "urn:food-agent:domain-method:validate-evidence-output:v1",
                DomainContractMethod.COMPUTE_FEATURES: "urn:food-agent:domain-method:compute-features-output:v1",
                DomainContractMethod.SCORE_PUBLIC: "urn:food-agent:domain-method:score-public-output:v1",
                DomainContractMethod.BUILD_FINAL_OUTPUT: "urn:food-agent:domain-method:build-final-output-output:v1",
                DomainContractMethod.MAP_ERROR: "urn:food-agent:stable-error:v1",
            }[method]].schema_digest,
        )
        for method in methods
    )
    input_schema = _schema(
        "urn:food-agent:travel:tool:poi.lookup:input:v1",
        properties={"schemaVersion": {"const": "travel.poi.lookup/input/v1"}, "query": {"type": "string"}, "geo": {"type": "string"}},
        required=["schemaVersion", "query", "geo"],
    )
    output_tool_schema = _schema(
        "urn:food-agent:travel:tool:poi.lookup:output:v1",
        properties={"schemaVersion": {"const": "travel.poi.lookup/output/v1"}, "places": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["sourceId", "name"], "properties": {"sourceId": {"type": "string"}, "name": {"type": "string"}, "address": {"type": "string"}}}}},
        required=["schemaVersion", "places"],
    )
    output_schema = dict(
        by_id["urn:food-agent:domain-method:build-final-output-output:v1"].schema_document
    )
    output_schema["$id"] = "urn:food-agent:travel:final-output:v1"
    tool = AllowedToolContract(
        tool_id="travel.poi.lookup",
        tool_version="1.0.0",
        permission="source.place.read",
        timeout_ms=3000,
        error_codes=("dependency_unavailable", "rate_limited", "invalid_tool_result"),
        input_schema_digest=canonical_schema_digest(input_schema),
        output_schema_digest=canonical_schema_digest(output_tool_schema),
        input_schema=input_schema,
        input_example={"schemaVersion": "travel.poi.lookup/input/v1", "query": "景点", "geo": "CN-SC"},
        output_schema=output_tool_schema,
        output_example={"schemaVersion": "travel.poi.lookup/output/v1", "places": []},
    )
    manifest = DomainPackManifest(
        manifest_version="domain-pack-manifest/v1",
        domain_id=TRAVEL_DOMAIN_ID,
        pack_version=TRAVEL_PACK_VERSION,
        contract_api="domain-contract/v1",
        core_version_range=">=1.0.0,<2.0.0",
        manifest_digest="0" * 64,
        methods=methods,
        domain_schemas=DomainSchemaDeclarations(
            entities=domain_schema_ids["entities"], relations=domain_schema_ids["relations"], evidence_types=domain_schema_ids["evidence"], feature_set=domain_schema_ids["features"], personalization_slots=domain_schema_ids["personalization"]
        ),
        method_schemas=method_schemas,
        allowed_tools=(tool,),
        final_output_schema_digest=canonical_schema_digest(output_schema),
        final_output_schema=output_schema,
        final_output_example={"schemaVersion": "travel-agent-final-output/v1", "summary": "", "itineraries": []},
        scoring_policy=PublicScoringPolicy(
            policy_id="travel-public-score",
            policy_version="1.0.0",
            mode="pure_deterministic",
            inputs=("season", "ticket", "crowding", "duration", "audience", "declared_public_feature_set", "explicit_versioned_config"),
            forbidden_inputs=("user_memory", "session_memory", "wall_clock", "randomness", "environment", "framework_state"),
            forbidden_effects=("network", "filesystem", "database", "cache", "workflow", "connector"),
        ),
        domain_sources=(DomainSourceCapability(capability="place.lookup", version_range=">=1.0.0,<2.0.0", required=True),),
        policy_profiles=DomainPolicyProfiles(workflow="travel-workflow/v1", freshness="travel-freshness/v1", coverage="travel-coverage/v1", stopping="travel-stopping/v1", refresh_job="travel-refresh/v1"),
    )
    return manifest.model_copy(update={"manifest_digest": canonical_manifest_digest(manifest, bundle)})


def load_travel_contract_resources() -> tuple[DomainPackManifest, DomainSchemaBundle]:
    return load_travel_manifest(), load_travel_schema_bundle()


__all__ = [
    "TRAVEL_DOMAIN_ID",
    "TRAVEL_PACK_VERSION",
    "load_travel_contract_resources",
    "load_travel_manifest",
    "load_travel_schema_bundle",
]
