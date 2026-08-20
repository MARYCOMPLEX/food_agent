"""Load the sealed Food Domain Pack contract resources from this package."""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Any, cast

from xhs_food.contracts import (
    DomainPackManifest,
    DomainSchemaBundle,
    canonical_manifest_digest,
)

FOOD_DOMAIN_ID = "food"
FOOD_PACK_VERSION = "1.0.0"

_MANIFEST_RESOURCE = "manifest_v1.json.resource"
_SCHEMA_BUNDLE_RESOURCE = "schema_bundle_v1.json.resource"


def _load_json_object(resource_name: str) -> dict[str, Any]:
    resource = files(__package__).joinpath(resource_name)
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Food Pack resource {resource_name!r} must contain a JSON object")
    return cast(dict[str, Any], value)


@cache
def load_food_schema_bundle() -> DomainSchemaBundle:
    """Return the immutable, locally sealed Food Pack schema bundle."""

    return DomainSchemaBundle.model_validate(_load_json_object(_SCHEMA_BUNDLE_RESOURCE))


@cache
def load_food_manifest() -> DomainPackManifest:
    """Return the immutable Food Pack manifest after verifying its bundle digest."""

    manifest = DomainPackManifest.model_validate(_load_json_object(_MANIFEST_RESOURCE))
    if canonical_manifest_digest(manifest, load_food_schema_bundle()) != manifest.manifest_digest:
        raise ValueError("Food Pack manifest digest does not match its sealed schema bundle")
    return manifest


def load_food_contract_resources() -> tuple[DomainPackManifest, DomainSchemaBundle]:
    """Load the complete Food Pack declaration without registering or activating it."""

    return load_food_manifest(), load_food_schema_bundle()


__all__ = [
    "FOOD_DOMAIN_ID",
    "FOOD_PACK_VERSION",
    "load_food_contract_resources",
    "load_food_manifest",
    "load_food_schema_bundle",
]
