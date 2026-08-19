"""Reviewable authority tests for ADR-0006 (no production implementation imports)."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
AUTHORITY = ROOT / "tests" / "fixtures" / "authority"


def _json(name: str) -> dict:
    return json.loads((AUTHORITY / name).read_text(encoding="utf-8"))


def _canonical_identity(value: dict) -> str:
    """Mirror only the ADR's projection; this is not a production normalizer."""
    projection = {
        "isolation": value["isolation"],
        "query": {
            key: value["query"][key]
            for key in (
                "domain",
                "geo",
                "intent",
                "constraints",
                "time_range",
                "freshness_policy",
            )
        },
    }
    encoded = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def test_canonical_query_fixture_freezes_field_set_isolation_and_public_projection() -> None:
    schema = _json("canonical_query_v1.schema.json")
    fixture = _json("canonical_query_v1.json")

    assert schema["$id"] == "urn:food-agent:canonical-query:v1"
    assert schema["required"] == [
        "schema_version",
        "normalizer_version",
        "classifier_version",
        "isolation",
        "query",
    ]
    assert set(schema["$defs"]["query"]["required"]) == {
        "domain",
        "geo",
        "intent",
        "audience",
        "constraints",
        "time_range",
        "freshness_policy",
    }
    assert fixture["schema_version"] == "canonical-query/v1"
    assert set(fixture["query"]) == {
        "domain",
        "geo",
        "intent",
        "audience",
        "constraints",
        "time_range",
        "freshness_policy",
    }
    assert fixture["isolation"] == {
        "tenant_scope": "public",
        "language": "zh-Hans",
        "region": "CN",
    }
    assert fixture["query"]["constraints"][0]["classification_rule"] == (
        "food.public.entity_category"
    )

    authority = schema["x-authority"]
    assert authority["familyIdentity"]["excludedQueryFields"] == ["audience"]
    assert authority["familyIdentity"]["forbiddenFields"]
    assert authority["matching"]["orderedLevels"] == [
        "deterministic",
        "pg_trgm",
        "bge_m3_profile_v1",
    ]
    assert authority["matching"]["vectorProfile"] == {
        "id": "profile_v1",
        "dimensions": 1024,
        "metric": "cosine",
        "normalized": True,
    }


def test_audience_is_explainable_but_does_not_split_public_family_identity() -> None:
    visitor = _json("canonical_query_v1.json")
    local = copy.deepcopy(visitor)
    local["query"]["audience"] = ["local"]

    assert _canonical_identity(visitor) == _canonical_identity(local)
    assert visitor["query"]["audience"] != local["query"]["audience"]
    forbidden = _json("canonical_query_v1.schema.json")["x-authority"]["familyIdentity"][
        "forbiddenFields"
    ]
    serialized = json.dumps(visitor, ensure_ascii=False).lower()
    assert all(field.lower() not in serialized for field in forbidden)


def test_canonical_constraint_and_matching_rules_keep_thresholds_deferred() -> None:
    schema = _json("canonical_query_v1.schema.json")
    classification = schema["x-authority"]["constraintClassification"]
    assert "dietary_restriction" in classification["personalCategories"]
    assert classification["unknownAction"] == ["clarify", "non_shared_research"]
    assert schema["x-authority"]["matching"]["thresholds"] == (
        "deferred_to_b2_versioned_matching_policy"
    )
    assert schema["x-authority"]["mergeSplitAuditRequired"] == [
        "operation_id",
        "operation",
        "before_family_ids",
        "after_family_ids",
        "isolation",
        "actor_type",
        "rule_version",
        "profile_version",
        "threshold_version",
        "scores",
        "reason_codes",
        "evidence_refs",
        "recorded_at",
    ]


def test_freshness_policy_fixture_freezes_gate_shape_but_marks_values_review_only() -> None:
    schema = _json("freshness_policy_v1.schema.json")
    policy = _json("freshness_policy_v1.json")

    assert schema["$id"] == "urn:food-agent:freshness-policy:v1"
    assert policy["schema_version"] == "freshness-policy/v1"
    assert policy["gate"]["outcomes"] == ["fresh", "incremental", "new"]
    assert schema["x-authority"]["reviewExampleValues"] == "non_normative_until_b2_b4"
    assert schema["x-authority"]["publicFeedbackInfluence"] == (
        "disabled_by_memory-privacy/v1"
    )
    assert abs(sum(item["weight"] for item in policy["coverage"]["dimensions"]) - 1.0) < 1e-12
    assert abs(sum(item["weight"] for item in policy["priority"]["factors"]) - 1.0) < 1e-12
    assert all(
        partition["max_stale_for_seconds"] >= partition["fresh_for_seconds"]
        for partition in policy["partitions"]
    )
    assert policy["watermarks"]["missing_action"] in {"incremental", "new", "fail_closed"}
    assert all("user" not in json.dumps(item).lower() for item in policy["priority"]["factors"])
    assert "public_change_rate" not in policy["popularity"]["aggregate_signals"]


def test_evidence_fixture_has_complete_provenance_and_no_embedded_binary() -> None:
    schema = _json("evidence_bundle_v1.schema.json")
    fixture = _json("evidence_bundle_v1.json")
    assert schema["$id"] == "urn:food-agent:evidence-bundle:v1"
    assert fixture["schema_version"] == "evidence-bundle/v1"
    assert fixture["governance"]["deletion"] == {
        "request_is_idempotent": True,
        "uses_tombstone": True,
        "replacement_candidate_required": True,
        "cleanup_is_async_and_idempotent": True,
        "legal_hold_blocks_bytes_delete": True,
        "metadata_authority": "postgresql",
    }

    locators = {item["locator_id"]: item for item in fixture["source_locators"]}
    media = {item["media_ref_id"]: item for item in fixture["media_refs"]}
    artifacts = {item["artifact_id"]: item for item in fixture["derived_artifacts"]}
    evidence = {item["evidence_id"]: item for item in fixture["evidence_items"]}
    assert locators and media and artifacts and evidence

    for ref in media.values():
        assert ref["locator_id"] in locators
        assert "bytes" not in ref and "data" not in ref
    for artifact in artifacts.values():
        assert artifact["object_ref"].startswith("s3://")
        assert re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
        assert "bytes" not in artifact and "data" not in artifact
        assert all(ref in media for ref in artifact["input_refs"])
        assert artifact["license"]["status"] == "known"
    for item in evidence.values():
        assert item["source_locator_id"] in locators
        assert all(ref in media for ref in item["media_ref_ids"])
        assert all(ref in artifacts for ref in item["derived_artifact_ids"])
        assert item["status"] == "accepted"
        assert item["license"]["status"] == "known"
        assert 0 <= item["confidence"] <= 1
        assert re.fullmatch(r"[0-9a-f]{64}", item["content_hash"])
        assert "bytes" not in item and "data" not in item

    published = [bundle for bundle in fixture["bundles"] if bundle["state"] == "published"]
    assert len(published) == 1
    bundle = published[0]
    assert set(bundle["evidence_ids"]) <= set(evidence)
    assert all(evidence[item_id]["status"] == "accepted" for item_id in bundle["evidence_ids"])
    assert bundle["visibility"]["scope"] == "public"
    assert bundle["retention"]["duration_seconds"] is None
    assert schema["x-authority"]["retentionDurations"] == "deferred_to_oq12_b4"


def test_evidence_governance_requires_tombstone_replacement_and_cas_lifecycle() -> None:
    authority = _json("evidence_bundle_v1.schema.json")["x-authority"]
    assert authority["metadataAuthority"] == "postgresql"
    assert authority["binaryBoundary"] == "object_store_only"
    assert authority["deletion"] == {
        "publishedBundle": "never_mutate_in_place",
        "oldMetadata": "retain_auditable_tombstone",
        "oldBytes": "delete_after_reference_retention_and_legal_hold_checks",
    }
    assert "candidate_bundle_cas_activation" in authority["publicationRequirements"]
