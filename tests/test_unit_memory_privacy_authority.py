"""Machine-checkable authority fixture for memory scope and privacy lifecycle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "authority" / "memory_privacy_v1.json"
DECISIONS = ROOT / "openspec" / "changes" / "define-modular-architecture" / "decisions"


def _load() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _assert_record_shape(record: dict[str, Any], schema: dict[str, Any]) -> None:
    assert set(schema["required"]) <= set(record)
    assert set(record) <= set(schema["properties"])
    assert record["schemaVersion"] == "memory-record/v1"
    assert record["layer"] in {"session", "explicit", "inferred", "strategy_feedback"}
    assert record["subject"]["kind"] in {"user", "anonymous"}
    assert record["tenantId"]
    assert record["subject"]["id"]
    assert record["sourceEventIds"]
    assert record["consent"]["status"] == "active"


def test_memory_adr_and_index_accept_oq13_oq14_and_oq15() -> None:
    adr = (DECISIONS / "ADR-0008-memory-privacy-authority.md").read_text(encoding="utf-8")
    index = (DECISIONS / "README.md").read_text(encoding="utf-8")
    rows = {
        oq: next(line for line in index.splitlines() if line.startswith(f"| {oq} |"))
        for oq in (13, 14, 15)
    }

    assert "- Status: Accepted" in adr
    assert "- Resolves: OQ-13, OQ-14, OQ-15" in adr
    assert all("| Accepted | [ADR-0008]" in row for row in rows.values())


def test_four_layers_have_distinct_value_confidence_scope_consent_and_expiry_rules() -> None:
    layers = _load()["layers"]
    assert set(layers) == {"session", "explicit", "inferred", "strategy_feedback"}
    assert layers["session"]["confidence"] == "absent"
    assert layers["session"]["requiresSessionId"] is True
    assert layers["explicit"]["consentBasis"] == "user_directed"
    assert layers["inferred"]["confidence"] == "required_0_to_1"
    assert layers["inferred"]["requiresAuthenticatedUser"] is True
    assert layers["inferred"]["activeUseExpiry"] == "P180D_AFTER_LATEST_SUPPORT_EVENT"
    assert layers["strategy_feedback"]["activeUseExpiry"] == "P90D_AFTER_CAPTURE"
    assert layers["strategy_feedback"]["consentBasis"] == "feedback_personalization_opt_in"


def test_examples_validate_against_common_record_schema_and_layer_invariants() -> None:
    authority = _load()
    schema = authority["recordSchemaDefinition"]
    examples = authority["exampleRecords"]
    assert len(examples) == 4
    assert {record["layer"] for record in examples} == set(authority["layers"])
    by_layer = {record["layer"]: record for record in examples}
    for record in examples:
        _assert_record_shape(record, schema)
        invariant = next(item for item in authority["layerInvariants"] if item["layer"] == record["layer"])
        assert invariant["confidence"] is None or record["confidence"] is not None
        for key in invariant["requiredValueKeys"]:
            assert key in record["value"]

    assert by_layer["session"]["subject"]["kind"] == "anonymous"
    assert by_layer["session"]["sessionId"]
    assert by_layer["inferred"]["subject"]["kind"] == "user"
    assert 0 <= by_layer["inferred"]["confidence"] <= 1


def test_tenant_subject_session_scope_is_never_a_shared_anonymous_bucket() -> None:
    authority = _load()
    identity = authority["identity"]
    assert identity["requiredPartitionPrefix"] == "tenant_id"
    assert identity["anonymous"] == ["tenant_id", "anonymous_subject_id", "session_id"]
    assert identity["forbiddenSubjectValues"]
    assert identity["cohortIsAuthorization"] is False
    assert identity["localeIsAuthorization"] is False
    assert identity["publicEvidenceIsMemory"] is False
    family = authority["publicQueryFamilyIsolation"]
    assert family["authority"] == "ADR-0006"
    assert family["requiredCoordinates"] == ["tenant_scope", "language", "region"]
    assert {"user_id", "session_id", "cohort", "memory"} <= set(family["forbiddenIdentityInputs"])
    assert family["memoryMayBroadenVisibility"] is False

    scopes = {
        (
            record["tenantId"],
            record["subject"]["kind"],
            record["subject"]["id"],
            record["sessionId"],
        )
        for record in authority["exampleRecords"]
    }
    assert len(scopes) == 2
    anonymous_scopes = [scope for scope in scopes if scope[1] == "anonymous"]
    assert len(anonymous_scopes) == 1 and anonymous_scopes[0][3]


def test_anonymous_claim_is_explicit_idempotent_and_recomputes_inferred_memory() -> None:
    claim = _load()["claim"]
    assert claim["explicitCommand"] == "claim_anonymous_memory"
    assert set(claim["requiredFields"]) >= {
        "tenantId",
        "anonymousSubjectId",
        "sessionId",
        "oneTimeToken",
        "targetUserId",
        "idempotencyKey",
    }
    assert claim["automaticDeviceMerge"] is False
    assert claim["crossTenantClaim"] is False
    assert "inferred" in claim["recomputedLayers"]
    assert claim["failureAtomic"] is True


def test_consent_expiry_correction_export_delete_and_derived_rebuild_are_normative() -> None:
    authority = _load()
    lifecycle = authority["lifecycle"]
    assert lifecycle["correction"] == {
        "style": "append_only_supersession",
        "oldStatus": "superseded",
        "requiresSameTransaction": True,
    }
    assert lifecycle["export"]["format"] == "utf8-json"
    assert "raw_embedding_vectors" in lifecycle["export"]["excludes"]
    assert lifecycle["delete"]["onlinePurgeSla"] == "PT24H"
    assert lifecycle["delete"]["backupPurgeSla"] == "P30D"
    assert lifecycle["withdrawal"]["blocksNewWritesAndUse"] is True

    derived = authority["derivedData"]
    assert derived["rebuildable"] is True
    assert derived["mayOverwriteNewerAuthority"] is False
    assert derived["frameworkMessagesPersistedAsMemory"] is False
    assert derived["redisMissAction"] == "rebuild_from_postgresql_or_use_non_personalized_path"


def test_public_feedback_influence_is_deny_all_until_a_separate_adr() -> None:
    policy = _load()["publicRefreshInfluence"]
    assert policy == {
        "enabled": False,
        "threshold": None,
        "individualSignalAllowed": False,
        "smallCohortSignalAllowed": False,
        "aggregateSignalAllowed": False,
        "futureEnablement": "separate_adr_and_policy_version",
        "untilThen": "no_signal",
    }
