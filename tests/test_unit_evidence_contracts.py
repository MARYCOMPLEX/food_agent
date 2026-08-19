"""Focused S1 contracts for ADR-0006 query and evidence authority."""

from __future__ import annotations

import copy
import json
import warnings
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from xhs_food.contracts import (
    AuthorityModel,
    BundleState,
    CanonicalAuthor,
    CanonicalMediaRef,
    CanonicalQuery,
    CanonicalSourceComment,
    CanonicalSourceDocument,
    EvidenceBundle,
    EvidenceBundleManifest,
    EvidenceStatus,
    MediaRef,
    PublicConstraint,
    SourceLocator,
)
from xhs_food.contracts import evidence as evidence_module

AUTHORITY = Path(__file__).parent / "fixtures" / "authority"


def _json(name: str) -> dict:
    return json.loads((AUTHORITY / name).read_text(encoding="utf-8"))


def test_canonical_query_v1_round_trips_authority_and_excludes_audience_from_identity() -> None:
    fixture = _json("canonical_query_v1.json")
    canonical = CanonicalQuery.model_validate(fixture)

    assert canonical.model_dump(mode="json") == fixture
    assert canonical.query.audience == ("visitor",)
    projection = canonical.family_identity_projection()
    assert "audience" not in projection["query"]
    assert projection["isolation"] == fixture["isolation"]

    local = canonical.model_copy(
        update={"query": canonical.query.model_copy(update={"audience": ("local",)})}
    )
    assert local.family_identity_projection() == projection


@pytest.mark.parametrize(
    ("path", "field", "value"),
    [
        ((), "user_id", "user-private"),
        (("query",), "session_id", "session-private"),
        (("query", "geo"), "preferences", {"spicy": False}),
    ],
)
def test_canonical_query_rejects_personal_or_unknown_fields(
    path: tuple[str, ...], field: str, value: object
) -> None:
    fixture = _json("canonical_query_v1.json")
    target = fixture
    for segment in path:
        target = target[segment]
    target[field] = value

    with pytest.raises(ValidationError):
        CanonicalQuery.model_validate(fixture)


@pytest.mark.parametrize("field", ["user-id", "session_id", "device-id", "preference"])
def test_canonical_query_rejects_personal_constraint_key_variants(field: str) -> None:
    fixture = _json("canonical_query_v1.json")
    fixture["query"]["constraints"][0]["key"] = field

    with pytest.raises(ValidationError, match="personal identity"):
        CanonicalQuery.model_validate(fixture)


def test_canonical_query_rejects_noncanonical_content_and_set_order() -> None:
    fixture = _json("canonical_query_v1.json")
    fixture["query"]["audience"] = ["visitor", "local"]
    with pytest.raises(ValidationError, match="canonical order"):
        CanonicalQuery.model_validate(fixture)


@pytest.mark.parametrize(
    "field_path",
    [
        ("query", "time_range", "start"),
        ("query", "time_range", "end"),
    ],
)
def test_authority_timestamps_accept_utc_and_reject_non_utc(field_path: tuple[str, ...]) -> None:
    fixture = _json("canonical_query_v1.json")
    target = fixture
    for segment in field_path[:-1]:
        target = target[segment]
    target[field_path[-1]] = "2026-08-19T10:00:00+08:00"

    with pytest.raises(ValidationError, match="UTC RFC 3339"):
        CanonicalQuery.model_validate(fixture)

    fixture = _json("canonical_query_v1.json")
    target = fixture
    for segment in field_path[:-1]:
        target = target[segment]
    target[field_path[-1]] = "2026-08-19T02:00:00Z"
    parsed = CanonicalQuery.model_validate(fixture)
    selected = getattr(parsed.query.time_range, field_path[-1])
    assert selected is not None

    fixture = _json("canonical_query_v1.json")
    fixture["query"]["constraints"][0]["value"] = "  local_food  "
    with pytest.raises(ValidationError, match="non-canonical string"):
        CanonicalQuery.model_validate(fixture)


def test_evidence_bundle_v1_manifest_round_trips_complete_authority_graph() -> None:
    fixture = _json("evidence_bundle_v1.json")
    manifest = EvidenceBundleManifest.model_validate(fixture)

    assert manifest.model_dump(mode="json") == fixture
    assert manifest.isolation.tenant_scope == "public"
    assert manifest.derived_artifacts[0].object_ref.startswith("s3://")
    assert manifest.bundles[0].state is BundleState.PUBLISHED
    assert all(item.status is EvidenceStatus.ACCEPTED for item in manifest.evidence_items)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nested_authority_json_rejects_non_finite_numbers(value: float) -> None:
    fixture = _json("evidence_bundle_v1.json")
    fixture["evidence_items"][0]["claim_value"] = {"nested": {"score": value}}

    with pytest.raises(ValidationError, match="NaN or Infinity"):
        EvidenceBundleManifest.model_validate(fixture)


@pytest.mark.parametrize(
    ("collection", "index", "field", "value"),
    [
        ("media_refs", 0, "locator_id", "source.missing"),
        ("derived_artifacts", 0, "input_refs", ["media.missing"]),
        ("evidence_items", 0, "source_locator_id", "source.missing"),
        ("evidence_items", 1, "derived_artifact_ids", ["artifact.missing"]),
        ("bundles", 0, "evidence_ids", ["evidence.missing"]),
    ],
)
def test_evidence_manifest_rejects_broken_provenance_graph(
    collection: str, index: int, field: str, value: object
) -> None:
    fixture = _json("evidence_bundle_v1.json")
    fixture[collection][index][field] = value

    with pytest.raises(ValidationError):
        EvidenceBundleManifest.model_validate(fixture)


@pytest.mark.parametrize("status", ["candidate", "quarantined", "tombstoned"])
def test_published_bundle_rejects_nonaccepted_evidence(status: str) -> None:
    fixture = _json("evidence_bundle_v1.json")
    fixture["evidence_items"][0]["status"] = status

    with pytest.raises(ValidationError, match="only accepted Evidence"):
        EvidenceBundleManifest.model_validate(fixture)


@pytest.mark.parametrize("status", ["unknown", "expired", "revoked"])
@pytest.mark.parametrize(
    "collection",
    ["source_locators", "derived_artifacts", "evidence_items"],
)
def test_published_bundle_rejects_unpublishable_license_chain(
    collection: str, status: str
) -> None:
    fixture = _json("evidence_bundle_v1.json")
    fixture[collection][0]["license"]["status"] = status

    with pytest.raises(ValidationError, match="governance|known, unexpired licenses"):
        EvidenceBundleManifest.model_validate(fixture)


def test_derived_artifact_cannot_broaden_source_rights_or_visibility() -> None:
    fixture = _json("evidence_bundle_v1.json")
    fixture["source_locators"][0]["license"]["allowed_use"] = "extract_only"
    with pytest.raises(ValidationError, match="broaden input governance"):
        EvidenceBundleManifest.model_validate(fixture)

    fixture = _json("evidence_bundle_v1.json")
    locator = fixture["source_locators"][0]
    locator["visibility"] = {
        "scope": "tenant",
        "tenant_scope": "tenant:fixture",
        "entitlement_ids": [],
    }
    fixture["isolation"]["tenant_scope"] = "tenant:fixture"
    with pytest.raises(ValidationError, match="broaden input governance"):
        EvidenceBundleManifest.model_validate(fixture)


def test_public_evidence_rejects_personal_claims_and_cross_partition_bundle() -> None:
    fixture = _json("evidence_bundle_v1.json")
    fixture["evidence_items"][0]["claim_value"] = {"user_id": "private-user"}
    with pytest.raises(ValidationError, match="forbidden personal field"):
        EvidenceBundleManifest.model_validate(fixture)

    fixture = _json("evidence_bundle_v1.json")
    fixture["bundles"][0]["visibility"] = {
        "scope": "tenant",
        "tenant_scope": "tenant:other",
        "entitlement_ids": [],
    }
    with pytest.raises(ValidationError, match="isolation tenant_scope"):
        EvidenceBundleManifest.model_validate(fixture)


@pytest.mark.parametrize(
    "private_field",
    ["userId", "UserId", "session-id", "SessionID", "Device_ID", "preference"],
)
def test_public_evidence_rejects_personal_field_naming_variants(private_field: str) -> None:
    fixture = _json("evidence_bundle_v1.json")
    fixture["evidence_items"][0]["claim_value"] = {private_field: "private"}

    with pytest.raises(ValidationError, match="forbidden personal field"):
        EvidenceBundleManifest.model_validate(fixture)


def test_public_constraint_rejects_kebab_case_personal_key() -> None:
    with pytest.raises(ValidationError, match="personal identity"):
        PublicConstraint(
            key="session-id",
            operator="eq",
            value="private",
            classification_rule="fixture",
        )


_CANONICAL_URL_CASES = [
    (
        CanonicalAuthor,
        "canonical_url",
        {
            "source_id": "fixture",
            "external_id": "author-1",
            "canonical_url": "https://source.invalid/authors/1",
            "captured_at": "2026-08-19T02:00:00Z",
        },
    ),
    (
        CanonicalSourceDocument,
        "canonical_url",
        {
            "source_id": "fixture",
            "external_id": "document-1",
            "canonical_url": "https://source.invalid/documents/1",
            "captured_at": "2026-08-19T02:00:00Z",
        },
    ),
    (
        CanonicalSourceComment,
        "canonical_url",
        {
            "source_id": "fixture",
            "external_id": "comment-1",
            "document_external_id": "document-1",
            "canonical_url": "https://source.invalid/comments/1",
            "captured_at": "2026-08-19T02:00:00Z",
        },
    ),
    (
        SourceLocator,
        "canonical_url",
        {
            "locator_id": "source.fixture",
            "source_id": "fixture",
            "connector_id": "fixture.connector",
            "connector_version": "fixture_connector/v1",
            "external_id": "document-1",
            "canonical_url": "https://source.invalid/documents/1",
            "captured_at": "2026-08-19T02:00:00Z",
            "source_updated_at": None,
            "watermark": None,
            "visibility": {
                "scope": "public",
                "tenant_scope": "public",
                "entitlement_ids": [],
            },
            "license": {
                "license_id": "fixture",
                "status": "known",
                "allowed_use": "internal_reuse",
                "attribution_required": False,
                "expires_at": None,
                "policy_version": "license/v1",
            },
            "retention": {
                "retention_class": "fixture",
                "duration_seconds": None,
                "legal_hold": False,
            },
        },
    ),
]

_MEDIA_URL_CASES = [
    (
        CanonicalMediaRef,
        "canonical_url",
        {
            "source_id": "fixture",
            "external_id": "media-1",
            "owner_external_id": "document-1",
            "owner_type": "document",
            "canonical_url": "https://source.invalid/media/1",
            "captured_at": "2026-08-19T02:00:00Z",
            "media_type": "image",
        },
    ),
    (
        MediaRef,
        "source_url",
        {
            "media_ref_id": "media.fixture",
            "locator_id": "source.fixture",
            "media_type": "image",
            "source_url": "https://source.invalid/media/1",
            "declared_content_type": None,
            "declared_sha256": None,
        },
    ),
]


@pytest.mark.parametrize(("model", "field", "payload"), _CANONICAL_URL_CASES)
@pytest.mark.parametrize(
    "unsafe_url",
    [
        "https://source.invalid/resource?X-Amz-Signature=secret",
        "https://source.invalid/resource?ACCESS_TOKEN=secret",
        "https://source.invalid/resource#access_token=secret",
        "https://user:secret@source.invalid/resource",
    ],
)
def test_canonical_urls_reject_credentials_but_not_ordinary_url_components(
    model: type[AuthorityModel],
    field: str,
    payload: dict[str, object],
    unsafe_url: str,
) -> None:
    candidate = copy.deepcopy(payload)
    candidate[field] = unsafe_url

    with pytest.raises(ValidationError, match="credentials|signed URL"):
        model.model_validate(candidate)


@pytest.mark.parametrize(("model", "field", "payload"), _CANONICAL_URL_CASES)
def test_canonical_urls_preserve_benign_query_and_fragment(
    model: type[AuthorityModel], field: str, payload: dict[str, object]
) -> None:
    candidate = copy.deepcopy(payload)
    candidate[field] = "https://source.invalid/resource?view=thread&page=2#comment-4"

    parsed = model.model_validate(candidate)
    parsed_url = getattr(parsed, field)

    assert parsed_url.query == "view=thread&page=2"
    assert parsed_url.fragment == "comment-4"


@pytest.mark.parametrize(("model", "field", "payload"), _MEDIA_URL_CASES)
@pytest.mark.parametrize(
    "unsafe_url",
    [
        "https://source.invalid/resource?size=large",
        "https://source.invalid/resource#preview",
        "https://user:secret@source.invalid/resource",
    ],
)
def test_media_urls_reject_query_fragment_and_credentials(
    model: type[AuthorityModel],
    field: str,
    payload: dict[str, object],
    unsafe_url: str,
) -> None:
    candidate = copy.deepcopy(payload)
    candidate[field] = unsafe_url

    with pytest.raises(ValidationError, match="credentials|query parameters|fragments"):
        model.model_validate(candidate)


@pytest.mark.parametrize(
    ("collection", "field", "value"),
    [
        (
            "media_refs",
            "source_url",
            "https://source.invalid/image.jpg?X-Amz-Signature=secret",
        ),
        ("media_refs", "source_url", "https://user:secret@source.invalid/image.jpg"),
        (
            "derived_artifacts",
            "object_ref",
            "s3://food-agent/derived/object?X-Amz-Signature=secret",
        ),
        ("derived_artifacts", "object_ref", "s3://food-agent/derived/object#fragment"),
        (
            "derived_artifacts",
            "object_ref",
            "s3://user:secret@food-agent/derived/object",
        ),
    ],
)
def test_evidence_references_reject_embedded_access_credentials(
    collection: str, field: str, value: str
) -> None:
    fixture = _json("evidence_bundle_v1.json")
    fixture[collection][0][field] = value

    with pytest.raises(ValidationError):
        EvidenceBundleManifest.model_validate(fixture)


@pytest.mark.parametrize(
    ("collection", "field", "value", "accepted"),
    [
        (
            "source_locators",
            "canonical_url",
            "https://source.invalid/note/1?view=thread&page=2#comment-4",
            True,
        ),
        (
            "source_locators",
            "canonical_url",
            "https://source.invalid/note/1?X-Amz-Signature=secret",
            False,
        ),
        (
            "source_locators",
            "canonical_url",
            "https://source.invalid/note/1?access_token=secret",
            False,
        ),
        (
            "source_locators",
            "canonical_url",
            "https://source.invalid/note/1#access_token=secret",
            False,
        ),
        (
            "source_locators",
            "canonical_url",
            "https://source.invalid/note/1#/route?token=secret",
            False,
        ),
        (
            "source_locators",
            "canonical_url",
            "https://user:secret@source.invalid/note/1",
            False,
        ),
        ("media_refs", "source_url", "https://source.invalid/image?width=1280", False),
        ("media_refs", "source_url", "https://source.invalid/image#preview", False),
        (
            "media_refs",
            "source_url",
            "https://user:secret@source.invalid/image",
            False,
        ),
        ("derived_artifacts", "object_ref", "s3://food-agent/object?token=x", False),
        ("derived_artifacts", "object_ref", "s3://food-agent/object#preview", False),
        (
            "derived_artifacts",
            "object_ref",
            "s3://user:secret@food-agent/object",
            False,
        ),
    ],
)
def test_authority_schema_matches_runtime_reference_policy(
    collection: str, field: str, value: str, accepted: bool
) -> None:
    schema = _json("evidence_bundle_v1.schema.json")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    fixture = _json("evidence_bundle_v1.json")
    fixture[collection][0][field] = value

    if accepted:
        EvidenceBundleManifest.model_validate(fixture)
        validator.validate(fixture)
    else:
        with pytest.raises(ValidationError):
            EvidenceBundleManifest.model_validate(fixture)
        assert not validator.is_valid(fixture)


def test_derived_artifact_lineage_must_be_acyclic() -> None:
    fixture = _json("evidence_bundle_v1.json")
    first = fixture["derived_artifacts"][0]
    second = copy.deepcopy(first)
    second["artifact_id"] = "artifact.ocr.note.124"
    first["input_refs"] = [second["artifact_id"]]
    second["input_refs"] = [first["artifact_id"]]
    fixture["derived_artifacts"].append(second)

    with pytest.raises(ValidationError, match="lineage must be acyclic"):
        EvidenceBundleManifest.model_validate(fixture)


def test_bundle_version_is_frozen_and_requires_append_only_parent_lineage() -> None:
    payload = _json("evidence_bundle_v1.json")["bundles"][0]
    bundle = EvidenceBundle.model_validate(payload)

    with pytest.raises(ValidationError, match="frozen"):
        bundle.bundle_version = 2

    child = copy.deepcopy(payload)
    child.update(
        {
            "bundle_id": "bundle.food.zigong.v2",
            "bundle_version": 2,
            "parent_bundle_version": 1,
            "state": "candidate",
        }
    )
    assert EvidenceBundle.model_validate(child).parent_bundle_version == 1

    child["parent_bundle_version"] = 2
    with pytest.raises(ValidationError, match="must precede"):
        EvidenceBundle.model_validate(child)


def test_nested_json_is_deeply_immutable_and_model_copy_revalidates() -> None:
    fixture = _json("evidence_bundle_v1.json")
    nested_claim = {
        "menu": [
            {
                "dish": "鲜椒牛肉",
                "tags": ["beef", "spicy"],
            }
        ]
    }
    fixture["evidence_items"][1]["claim_value"] = nested_claim
    manifest = EvidenceBundleManifest.model_validate(fixture)
    claim = manifest.evidence_items[1].claim_value
    assert isinstance(claim, dict)
    menu = claim["menu"]
    assert isinstance(menu, list)
    menu_item = menu[0]
    assert isinstance(menu_item, dict)
    tags = menu_item["tags"]
    assert isinstance(tags, list)

    with pytest.raises(TypeError, match="immutable"):
        claim["dish"] = "changed"  # type: ignore[index]

    with pytest.raises(TypeError, match="immutable"):
        menu.append({"dish": "changed"})

    with pytest.raises(TypeError, match="immutable"):
        menu_item["dish"] = "changed"

    with pytest.raises(TypeError, match="immutable"):
        tags[0] = "changed"

    with pytest.raises(TypeError, match="immutable"):
        manifest.bundles[0].coverage["entity_identity"] = 0.1

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        python_payload = manifest.model_dump(mode="python", round_trip=True)
        json_payload = manifest.model_dump(mode="json")
        encoded_payload = manifest.model_dump_json()

    for payload in (python_payload, json_payload, json.loads(encoded_payload)):
        serialized_claim = payload["evidence_items"][1]["claim_value"]
        assert isinstance(serialized_claim, dict)
        assert isinstance(serialized_claim["menu"], list)
        assert isinstance(serialized_claim["menu"][0]["tags"], list)
        assert serialized_claim == nested_claim

    with pytest.raises(ValidationError, match="forbidden personal field"):
        manifest.evidence_items[0].model_copy(
            update={"claim_value": {"nested": {"user_id": "private"}}}
        )


def test_evidence_module_and_top_level_exports_are_identical() -> None:
    from xhs_food import contracts

    assert set(evidence_module.__all__).issubset(set(contracts.__all__))
    assert all(hasattr(contracts, name) for name in evidence_module.__all__)
    assert issubclass(AuthorityModel, object)


def test_contracts_do_not_choose_deferred_matching_or_freshness_values() -> None:
    schemas = {
        "canonical": CanonicalQuery.model_json_schema(),
        "evidence": EvidenceBundleManifest.model_json_schema(),
    }
    serialized = json.dumps(schemas, sort_keys=True)

    assert "trigram_threshold" not in serialized
    assert "vector_threshold" not in serialized
    assert "fresh_for_seconds" not in serialized
    assert "scheduler_weight" not in serialized
