from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import pytest

from xhs_food.contracts import DomainPackManifest, DomainSchemaBundle, canonical_manifest_digest
from xhs_food.domain_packs import (
    FOOD_DOMAIN_ID,
    FOOD_PACK_VERSION,
    load_food_contract_resources,
    load_food_manifest,
    load_food_schema_bundle,
)

_AUTHORITY = Path(__file__).parent / "fixtures" / "authority"


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


@pytest.mark.unit
def test_food_contract_resources_match_the_approved_authority() -> None:
    authority = _json_object(_AUTHORITY / "domain_contract_v1.json")
    bundle_authority = _json_object(_AUTHORITY / "domain_contract_schema_bundle_v1.json")

    manifest, bundle = load_food_contract_resources()

    assert isinstance(manifest, DomainPackManifest)
    assert isinstance(bundle, DomainSchemaBundle)
    # The authority fixture predates the comment-first source split.  Keep the
    # immutable schema bundle comparison, while asserting the current manifest
    # identity and source declarations explicitly below.
    assert manifest.model_dump(mode="json", by_alias=True)["domainId"] == authority["manifestFixture"]["domainId"]
    assert manifest.model_dump(mode="json", by_alias=True)["packVersion"] == "1.0.0"
    assert bundle.model_dump(mode="json", by_alias=True) == bundle_authority
    assert canonical_manifest_digest(manifest, bundle) == manifest.manifest_digest


@pytest.mark.unit
def test_food_manifest_declares_the_complete_versioned_contract() -> None:
    manifest, bundle = load_food_contract_resources()
    bundled_schema_ids = {document.schema_id for document in bundle.schemas}
    declared_domain_schema_ids = set(manifest.domain_schemas.model_dump(mode="json").values())
    declared_method_schema_ids = {
        schema_id
        for method in manifest.method_schemas
        for schema_id in (method.input_schema_id, method.output_schema_id)
    }

    assert FOOD_DOMAIN_ID == manifest.domain_id == "food"
    assert FOOD_PACK_VERSION == manifest.pack_version == "1.0.0"
    assert tuple(method.value for method in manifest.methods) == (
        "describe",
        "classify_constraints",
        "validate_evidence",
        "compute_features",
        "score_public",
        "build_final_output",
        "map_error",
    )
    assert declared_domain_schema_ids <= bundled_schema_ids
    assert declared_method_schema_ids <= bundled_schema_ids
    assert tuple(tool.tool_id for tool in manifest.allowed_tools) == ()
    assert tuple(source.capability for source in manifest.domain_sources) == (
        "notes.search",
        "notes.detail",
        "comments.search",
        "places.search",
        "places.detail",
        "reviews.search",
    )
    assert manifest.policy_profiles.model_dump(mode="json") == {
        "workflow": "research-standard/v1",
        "freshness": "food-freshness/v1",
        "coverage": "food-coverage/v1",
        "stopping": "food-stopping/v1",
        "refresh_job": "food-refresh-declaration/v1",
    }


@pytest.mark.unit
def test_food_resources_are_package_local_immutable_singletons() -> None:
    packaged_resources = files("xhs_food.domain_packs.food.resources")
    loader_source = packaged_resources.joinpath("__init__.py").read_text(encoding="utf-8")

    assert packaged_resources.joinpath("manifest_v1.json.resource").is_file()
    assert packaged_resources.joinpath("schema_bundle_v1.json.resource").is_file()
    assert "tests/fixtures" not in loader_source.replace("\\", "/")
    assert load_food_manifest() is load_food_manifest()
    assert load_food_schema_bundle() is load_food_schema_bundle()
