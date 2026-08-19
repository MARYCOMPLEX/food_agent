"""Domain Pack manifests, task pins, and framework-neutral registration validation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal, Protocol, Self, cast, runtime_checkable
from urllib.parse import urldefrag

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ConfigDict, Field, JsonValue, ValidationError, model_validator
from pydantic_core import PydanticCustomError
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable

from .base import ContractPayload, NonEmptyStr
from .errors import ContractError
from .evidence import AuthorityModel, EvidenceBundle, EvidenceItem

DOMAIN_CONTRACT_API = "domain-contract/v1"
DOMAIN_PACK_ENTRY_POINT_GROUP = "food_agent.domain_packs"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
MANIFEST_DIGEST_PREIMAGE_VERSION = "domain-manifest-digest-preimage/v1"

_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_SEMVER_PRERELEASE_IDENTIFIER = (
    r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
)
_SEMVER_PATTERN = (
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    rf"(?:-{_SEMVER_PRERELEASE_IDENTIFIER}"
    rf"(?:\.{_SEMVER_PRERELEASE_IDENTIFIER})*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_SEMVER_VALUE_PATTERN = _SEMVER_PATTERN.removeprefix("^").removesuffix("$")
_SEMVER_RANGE_CLAUSE_PATTERN = rf"(?:>=|<=|>|<|==)?\s*{_SEMVER_VALUE_PATTERN}"
_SEMVER_RANGE_PATTERN = (
    rf"^\s*{_SEMVER_RANGE_CLAUSE_PATTERN}\s*"
    rf"(?:,\s*{_SEMVER_RANGE_CLAUSE_PATTERN}\s*)*$"
)

Digest = Annotated[str, Field(pattern=_DIGEST_PATTERN)]
SemanticVersion = Annotated[str, Field(pattern=_SEMVER_PATTERN)]
VersionRange = Annotated[str, Field(pattern=_SEMVER_RANGE_PATTERN)]
JsonSchema = dict[str, JsonValue]


def _to_camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class _AuthorityModel(AuthorityModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )


class DomainContractMethod(StrEnum):
    DESCRIBE = "describe"
    CLASSIFY_CONSTRAINTS = "classify_constraints"
    VALIDATE_EVIDENCE = "validate_evidence"
    COMPUTE_FEATURES = "compute_features"
    SCORE_PUBLIC = "score_public"
    BUILD_FINAL_OUTPUT = "build_final_output"
    MAP_ERROR = "map_error"


REQUIRED_DOMAIN_METHODS = tuple(DomainContractMethod)
REQUIRED_METHOD_SCHEMA_IDS: dict[DomainContractMethod, tuple[str, str]] = {
    DomainContractMethod.DESCRIBE: (
        "urn:food-agent:domain-method:describe-input:v1",
        "urn:food-agent:domain-pack-manifest:v1",
    ),
    DomainContractMethod.CLASSIFY_CONSTRAINTS: (
        "urn:food-agent:domain-method:classify-constraints-input:v1",
        "urn:food-agent:domain-method:classify-constraints-output:v1",
    ),
    DomainContractMethod.VALIDATE_EVIDENCE: (
        "urn:food-agent:domain-method:validate-evidence-input:v1",
        "urn:food-agent:domain-method:validate-evidence-output:v1",
    ),
    DomainContractMethod.COMPUTE_FEATURES: (
        "urn:food-agent:domain-method:compute-features-input:v1",
        "urn:food-agent:domain-method:compute-features-output:v1",
    ),
    DomainContractMethod.SCORE_PUBLIC: (
        "urn:food-agent:domain-method:score-public-input:v1",
        "urn:food-agent:domain-method:score-public-output:v1",
    ),
    DomainContractMethod.BUILD_FINAL_OUTPUT: (
        "urn:food-agent:domain-method:build-final-output-input:v1",
        "urn:food-agent:domain-method:build-final-output-output:v1",
    ),
    DomainContractMethod.MAP_ERROR: (
        "urn:food-agent:domain-method:map-error-input:v1",
        "urn:food-agent:stable-error:v1",
    ),
}


class DomainRegistrationFailureCode(StrEnum):
    INVALID_MANIFEST = "invalid_manifest"
    DUPLICATE_PACK_VERSION = "duplicate_pack_version"
    INCOMPATIBLE_CONTRACT_API = "incompatible_contract_api"
    MISSING_CONTRACT_METHOD = "missing_contract_method"
    INVALID_SCHEMA_BUNDLE = "invalid_schema_bundle"
    INVALID_TOOL_CONTRACT = "invalid_tool_contract"
    INVALID_FINAL_OUTPUT_SCHEMA = "invalid_final_output_schema"
    IMPURE_SCORING_POLICY = "impure_scoring_policy"
    UNRESOLVED_SOURCE_CAPABILITY = "unresolved_source_capability"


class DomainPackDiscoveryPolicy(_AuthorityModel):
    """The only supported discovery policy; actual loading belongs to Composition Root."""

    entry_point_group: Literal["food_agent.domain_packs"] = DOMAIN_PACK_ENTRY_POINT_GROUP
    loaded_by: Literal["composition_root"] = "composition_root"
    load_time: Literal["worker_startup"] = "worker_startup"
    deployment_allow_list_required: Literal[True] = True
    request_selected_imports: Literal[False] = False
    network_discovery: Literal[False] = False
    directory_scanning: Literal[False] = False


class DomainSchemaDeclarations(_AuthorityModel):
    entities: NonEmptyStr
    relations: NonEmptyStr
    evidence_types: NonEmptyStr
    feature_set: NonEmptyStr
    personalization_slots: NonEmptyStr


class BundledSchemaDocument(_AuthorityModel):
    """One local schema artifact pinned by its canonical content digest."""

    schema_id: NonEmptyStr
    schema_digest: Digest
    schema_document: JsonSchema = Field(alias="schema")
    examples: tuple[JsonValue, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_identity_and_digest(self) -> Self:
        _validate_schema_syntax(self.schema_document)
        if self.schema_document.get("$id") != self.schema_id:
            raise ValueError("bundled schema_id must equal the schema $id")
        if canonical_schema_digest(self.schema_document) != self.schema_digest:
            raise ValueError("bundled schema digest does not match its document")
        return self


class DomainSchemaBundle(_AuthorityModel):
    bundle_version: Literal["domain-contract-schema-bundle/v1"]
    schemas: tuple[BundledSchemaDocument, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_schema_ids(self) -> Self:
        schema_ids = tuple(item.schema_id for item in self.schemas)
        if len(schema_ids) != len(set(schema_ids)):
            raise ValueError("bundled schema $id values must be globally unique")
        allowed_schema_ids = set(schema_ids)
        for index, item in enumerate(self.schemas):
            validate_schema_document(
                item.schema_document,
                path=f"$.schemas[{index}].schema",
                allowed_schema_ids=allowed_schema_ids,
            )
        return self


class MethodSchemaContract(_AuthorityModel):
    method: DomainContractMethod
    input_schema_id: NonEmptyStr
    input_schema_digest: Digest
    output_schema_id: NonEmptyStr
    output_schema_digest: Digest


class AllowedToolContract(_AuthorityModel):
    tool_id: NonEmptyStr
    tool_version: SemanticVersion
    permission: NonEmptyStr
    timeout_ms: int = Field(gt=0)
    error_codes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    input_schema_digest: Digest
    output_schema_digest: Digest
    input_schema: JsonSchema
    input_example: JsonValue
    output_schema: JsonSchema
    output_example: JsonValue

    @model_validator(mode="after")
    def validate_schema_contract(self) -> Self:
        _validate_schema_syntax(self.input_schema)
        _validate_schema_syntax(self.output_schema)
        input_id = self.input_schema.get("$id")
        output_id = self.output_schema.get("$id")
        if input_id == output_id:
            raise ValueError("tool input and output schemas must have distinct $id values")
        if self.input_schema.get("additionalProperties") is not False:
            raise ValueError("tool input schema must reject additional properties")
        if self.output_schema.get("additionalProperties") is not False:
            raise ValueError("tool output schema must reject additional properties")
        if canonical_schema_digest(self.input_schema) != self.input_schema_digest:
            raise ValueError("tool input schema digest does not match its document")
        if canonical_schema_digest(self.output_schema) != self.output_schema_digest:
            raise ValueError("tool output schema digest does not match its document")
        return self

    def validate_input(self, value: JsonValue) -> None:
        if canonical_schema_digest(self.input_schema) != self.input_schema_digest:
            raise ValueError("tool input schema changed after validation")
        validate_json_schema_value(self.input_schema, value)

    def validate_output(self, value: JsonValue) -> None:
        if canonical_schema_digest(self.output_schema) != self.output_schema_digest:
            raise ValueError("tool output schema changed after validation")
        validate_json_schema_value(self.output_schema, value)


class PublicScoringPolicy(_AuthorityModel):
    policy_id: NonEmptyStr
    policy_version: SemanticVersion
    mode: Literal["pure_deterministic"]
    inputs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    forbidden_inputs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    forbidden_effects: tuple[NonEmptyStr, ...] = Field(min_length=1)


class DomainSourceCapability(_AuthorityModel):
    capability: NonEmptyStr
    version_range: VersionRange
    required: bool

    @model_validator(mode="after")
    def validate_version_range(self) -> Self:
        if _parse_version_range(self.version_range) is None:
            raise ValueError("source capability version_range must be a valid SemVer range")
        return self


class DomainPolicyProfiles(_AuthorityModel):
    workflow: NonEmptyStr
    freshness: NonEmptyStr
    coverage: NonEmptyStr
    stopping: NonEmptyStr
    refresh_job: NonEmptyStr


class DomainPackManifest(_AuthorityModel):
    manifest_version: Literal["domain-pack-manifest/v1"]
    domain_id: NonEmptyStr
    pack_version: SemanticVersion
    contract_api: Literal["domain-contract/v1"]
    core_version_range: VersionRange
    manifest_digest: Digest
    methods: tuple[DomainContractMethod, ...]
    domain_schemas: DomainSchemaDeclarations
    method_schemas: tuple[MethodSchemaContract, ...]
    allowed_tools: tuple[AllowedToolContract, ...]
    final_output_schema_digest: Digest
    final_output_schema: JsonSchema
    final_output_example: JsonValue
    scoring_policy: PublicScoringPolicy
    domain_sources: tuple[DomainSourceCapability, ...]
    policy_profiles: DomainPolicyProfiles

    @model_validator(mode="after")
    def validate_final_output_contract(self) -> Self:
        try:
            _validate_schema_syntax(self.final_output_schema)
            if self.final_output_schema.get("additionalProperties") is not False:
                raise ValueError("schema must reject additional properties")
            if canonical_schema_digest(self.final_output_schema) != self.final_output_schema_digest:
                raise ValueError("schema digest does not match its document")
        except ValueError as exc:
            raise PydanticCustomError(
                "invalid_final_output_schema",
                "Agent final output schema is invalid: {reason}",
                {"reason": str(exc)},
            ) from exc
        return self

    @property
    def pack_key(self) -> tuple[str, str]:
        return (self.domain_id, self.pack_version)

    def validate_final_output(self, value: JsonValue) -> None:
        if canonical_schema_digest(self.final_output_schema) != self.final_output_schema_digest:
            raise ValueError("Agent final output schema changed after validation")
        validate_json_schema_value(self.final_output_schema, value)


class ToolSchemaPin(_AuthorityModel):
    tool_id: NonEmptyStr
    tool_version: SemanticVersion
    input_schema_id: NonEmptyStr
    input_schema_digest: Digest
    output_schema_id: NonEmptyStr
    output_schema_digest: Digest


class DomainContractPin(_AuthorityModel):
    """Immutable semantic pins copied into task input before execution starts."""

    domain_id: NonEmptyStr
    pack_version: SemanticVersion
    manifest_digest: Digest
    contract_api: Literal["domain-contract/v1"]
    method_schemas: tuple[MethodSchemaContract, ...]
    tool_schemas: tuple[ToolSchemaPin, ...]
    final_output_schema_id: NonEmptyStr
    final_output_schema_digest: Digest
    scoring_policy_version: SemanticVersion
    policy_profiles: DomainPolicyProfiles

    @classmethod
    def from_manifest(cls, manifest: DomainPackManifest) -> DomainContractPin:
        return cls(
            domain_id=manifest.domain_id,
            pack_version=manifest.pack_version,
            manifest_digest=manifest.manifest_digest,
            contract_api=manifest.contract_api,
            method_schemas=manifest.method_schemas,
            tool_schemas=tuple(
                ToolSchemaPin(
                    tool_id=tool.tool_id,
                    tool_version=tool.tool_version,
                    input_schema_id=str(tool.input_schema["$id"]),
                    input_schema_digest=tool.input_schema_digest,
                    output_schema_id=str(tool.output_schema["$id"]),
                    output_schema_digest=tool.output_schema_digest,
                )
                for tool in manifest.allowed_tools
            ),
            final_output_schema_id=str(manifest.final_output_schema["$id"]),
            final_output_schema_digest=manifest.final_output_schema_digest,
            scoring_policy_version=manifest.scoring_policy.policy_version,
            policy_profiles=manifest.policy_profiles,
        )


class RegistrationIssue(_AuthorityModel):
    code: DomainRegistrationFailureCode
    path: NonEmptyStr
    detail: NonEmptyStr


class RegistrationValidationResult(_AuthorityModel):
    accepted: bool
    activation_allowed: bool
    failure_code: DomainRegistrationFailureCode | None = None
    issues: tuple[RegistrationIssue, ...] = ()
    contract_pin: DomainContractPin | None = None

    @model_validator(mode="after")
    def enforce_atomic_activation(self) -> RegistrationValidationResult:
        if self.accepted != self.activation_allowed:
            raise ValueError("validation and activation decisions must be atomic")
        if self.accepted and (self.failure_code is not None or self.issues):
            raise ValueError("accepted registrations cannot contain failures")
        if self.accepted and self.contract_pin is None:
            raise ValueError("accepted registrations must publish complete task pins")
        if not self.accepted and (self.failure_code is None or not self.issues):
            raise ValueError("rejected registrations require a stable failure and issue")
        return self


@runtime_checkable
class DomainContract(Protocol):
    """Pure Domain Pack behavior; infrastructure access is intentionally absent."""

    def describe(self) -> DomainPackManifest: ...

    def classify_constraints(self, value: ContractPayload) -> ContractPayload: ...

    def validate_evidence(self, evidence: EvidenceItem) -> ContractPayload: ...

    def compute_features(
        self,
        bundle: EvidenceBundle,
        evidence_items: tuple[EvidenceItem, ...],
    ) -> ContractPayload: ...

    def score_public(self, features: ContractPayload) -> ContractPayload: ...

    def build_final_output(self, value: ContractPayload) -> JsonValue: ...

    def map_error(self, error: ContractError) -> ContractError: ...


def canonical_schema_digest(schema: Mapping[str, JsonValue]) -> str:
    encoded = json.dumps(
        schema,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _schema_without_identity(schema: Mapping[str, JsonValue]) -> JsonSchema:
    detached = cast(
        JsonSchema,
        json.loads(json.dumps(schema, ensure_ascii=False, allow_nan=False)),
    )
    detached.pop("$id", None)
    return detached


def canonical_manifest_digest(
    manifest: DomainPackManifest, schema_bundle: DomainSchemaBundle
) -> str:
    """Digest executable declarations and sorted schema pins, excluding test examples."""

    manifest_value = manifest.model_dump(mode="json", by_alias=True)
    manifest_value.pop("manifestDigest")
    manifest_value.pop("finalOutputExample")
    for tool in manifest_value["allowedTools"]:
        tool.pop("inputExample")
        tool.pop("outputExample")
    preimage = {
        "preimageVersion": MANIFEST_DIGEST_PREIMAGE_VERSION,
        "manifest": manifest_value,
        "schemaBundle": {
            "bundleVersion": schema_bundle.bundle_version,
            "schemas": sorted(
                (
                    {
                        "schemaId": item.schema_id,
                        "schemaDigest": item.schema_digest,
                    }
                    for item in schema_bundle.schemas
                ),
                key=lambda item: item["schemaId"],
            ),
        },
    }
    encoded = json.dumps(
        preimage,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_schema_syntax(schema: Mapping[str, JsonValue], *, path: str = "$") -> None:
    if schema.get("$schema") != JSON_SCHEMA_DIALECT:
        raise ValueError(f"{path}: unsupported or missing JSON Schema dialect")
    schema_id = schema.get("$id")
    if not isinstance(schema_id, str) or not schema_id.startswith("urn:food-agent:"):
        raise ValueError(f"{path}: schema $id must use the project urn:food-agent namespace")
    try:
        detached = json.loads(json.dumps(schema, ensure_ascii=False, allow_nan=False))
        Draft202012Validator.check_schema(detached)
    except SchemaError as exc:
        raise ValueError(f"{path}: invalid Draft 2020-12 schema: {exc.message}") from exc
    for nested_path, _nested_id in _iter_schema_ids(schema):
        if nested_path != "$.$id":
            raise ValueError(f"{path}: nested schema $id values are forbidden")


def validate_schema_document(
    schema: Mapping[str, JsonValue],
    *,
    path: str = "$",
    allowed_schema_ids: set[str] | None = None,
) -> None:
    """Validate a locally bundled JSON Schema Draft 2020-12 document."""

    _validate_schema_syntax(schema, path=path)
    schema_id = cast(str, schema["$id"])
    permitted = {schema_id} if allowed_schema_ids is None else allowed_schema_ids
    for ref_path, reference in _iter_schema_refs(schema):
        base, _fragment = urldefrag(reference)
        if not base:
            continue
        if base not in permitted:
            raise ValueError(f"{path}: {ref_path} is not in the sealed local schema bundle")


@dataclass(frozen=True)
class _SchemaRegistryContext:
    registry: Registry
    schema_ids: frozenset[str]


def validate_json_schema_value(
    schema: Mapping[str, Any],
    value: JsonValue,
    *,
    path: str = "$",
) -> None:
    """Validate one standalone schema with local-fragment references only."""

    schema_copy = cast(JsonSchema, dict(schema))
    schema_id = schema_copy.get("$id")
    allowed_schema_ids = {schema_id} if isinstance(schema_id, str) else set()
    validate_schema_document(
        schema_copy,
        path=path,
        allowed_schema_ids=allowed_schema_ids,
    )
    context = _schema_registry((schema_copy,))
    _validate_json_schema_value_in_context(schema_copy, value, path=path, context=context)


def _validate_json_schema_value_in_context(
    schema: Mapping[str, Any],
    value: JsonValue,
    *,
    path: str,
    context: _SchemaRegistryContext,
) -> None:
    """Validate against the registry snapshot sealed by Pack registration."""

    validate_schema_document(
        cast(Mapping[str, JsonValue], schema),
        path=path,
        allowed_schema_ids=set(context.schema_ids),
    )
    _validate_schema_references(schema, path=path, context=context)
    try:
        detached = json.loads(json.dumps(schema, ensure_ascii=False, allow_nan=False))
        Draft202012Validator(
            cast(dict[str, Any], detached),
            registry=context.registry,
            format_checker=FormatChecker(),
        ).validate(value)
    except JsonSchemaValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path)
        resolved_path = f"{path}.{location}" if location else path
        raise ValueError(f"{resolved_path}: {exc.message}") from exc
    except Exception as exc:
        raise ValueError(f"{path}: schema reference resolution failed: {exc}") from exc


def _validate_schema_references(
    schema: Mapping[str, Any],
    *,
    path: str,
    context: _SchemaRegistryContext,
) -> None:
    schema_id = cast(str, schema["$id"])
    resolver = context.registry.resolver(base_uri=schema_id)
    for ref_path, reference in _iter_schema_refs(schema):
        try:
            resolver.lookup(reference)
        except Unresolvable as exc:
            raise ValueError(f"{path}: {ref_path} does not resolve in the sealed bundle") from exc


def _iter_schema_refs(value: Any, path: str = "$") -> Sequence[tuple[str, str]]:
    references: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if key in {"$ref", "$dynamicRef"} and isinstance(item, str):
                references.append((child_path, item))
            else:
                references.extend(_iter_schema_refs(item, child_path))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            references.extend(_iter_schema_refs(item, f"{path}[{index}]"))
    return references


def _iter_schema_ids(value: Any, path: str = "$") -> Sequence[tuple[str, str]]:
    schema_ids: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if key == "$id" and isinstance(item, str):
                schema_ids.append((child_path, item))
            elif isinstance(item, (Mapping, list, tuple)):
                schema_ids.extend(_iter_schema_ids(item, child_path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            schema_ids.extend(_iter_schema_ids(item, f"{path}[{index}]"))
    return schema_ids


def _schema_registry(schemas: Sequence[JsonSchema]) -> _SchemaRegistryContext:
    resources = []
    schema_ids: set[str] = set()
    for schema in schemas:
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or not schema_id:
            raise ValueError("every registry schema requires a non-empty $id")
        if schema_id in schema_ids:
            raise ValueError(f"duplicate schema $id {schema_id!r}")
        schema_ids.add(schema_id)
        detached = json.loads(json.dumps(schema, ensure_ascii=False, allow_nan=False))
        resources.append((schema_id, Resource.from_contents(detached)))
    registry = Registry(retrieve=_reject_external_schema_retrieval).with_resources(resources)
    return _SchemaRegistryContext(registry=registry, schema_ids=frozenset(schema_ids))


def _reject_external_schema_retrieval(uri: str) -> Resource:
    raise ValueError(f"schema {uri!r} is not present in the local bundle")


def validate_domain_pack_registration(
    manifest_value: DomainPackManifest | Mapping[str, Any],
    implementation: DomainContract,
    *,
    schema_bundle: DomainSchemaBundle | Mapping[str, Any],
    core_version: str,
    registered_tool_capabilities: Mapping[str, str],
    registered_source_capabilities: Mapping[str, str],
    existing_pack_versions: Sequence[tuple[str, str]] = (),
) -> RegistrationValidationResult:
    """Return one atomic activation decision without mutating a registry."""

    try:
        bundle = (
            schema_bundle
            if isinstance(schema_bundle, DomainSchemaBundle)
            else DomainSchemaBundle.model_validate(schema_bundle)
        )
    except (ValidationError, ValueError) as exc:
        return _rejected(
            DomainRegistrationFailureCode.INVALID_SCHEMA_BUNDLE,
            f"invalid local schema bundle: {exc}",
            path="$.schemaBundle",
        )

    try:
        manifest = (
            manifest_value
            if isinstance(manifest_value, DomainPackManifest)
            else DomainPackManifest.model_validate(manifest_value)
        )
    except (ValidationError, ValueError) as exc:
        if not isinstance(exc, ValidationError):
            return _rejected(DomainRegistrationFailureCode.INVALID_MANIFEST, str(exc))
        code = _code_for_manifest_error(exc)
        return _rejected(code, exc.errors(include_url=False)[0].get("msg", "invalid manifest"))

    if canonical_manifest_digest(manifest, bundle) != manifest.manifest_digest:
        return _rejected(
            DomainRegistrationFailureCode.INVALID_MANIFEST,
            "manifest digest does not match its versioned declaration preimage",
            path="$.manifestDigest",
        )
    if manifest.pack_key in set(existing_pack_versions):
        return _rejected(
            DomainRegistrationFailureCode.DUPLICATE_PACK_VERSION,
            f"duplicate Pack version {manifest.domain_id}@{manifest.pack_version}",
            path="$.packVersion",
        )
    if manifest.contract_api != DOMAIN_CONTRACT_API or not _version_in_range(
        core_version, manifest.core_version_range
    ):
        return _rejected(
            DomainRegistrationFailureCode.INCOMPATIBLE_CONTRACT_API,
            "Pack Contract API or core version range is incompatible",
            path="$.contractApi",
        )

    declared_methods = tuple(manifest.methods)
    if declared_methods != REQUIRED_DOMAIN_METHODS:
        return _rejected(
            DomainRegistrationFailureCode.MISSING_CONTRACT_METHOD,
            "manifest must declare the exact ordered Domain Contract method set",
            path="$.methods",
        )
    for method in REQUIRED_DOMAIN_METHODS:
        if not callable(getattr(implementation, method.value, None)):
            return _rejected(
                DomainRegistrationFailureCode.MISSING_CONTRACT_METHOD,
                f"implementation is missing {method.value}",
                path=f"$.implementation.{method.value}",
            )

    method_schema_names = tuple(item.method for item in manifest.method_schemas)
    if len(set(method_schema_names)) != len(method_schema_names) or set(
        method_schema_names
    ) != set(REQUIRED_DOMAIN_METHODS):
        return _rejected(
            DomainRegistrationFailureCode.INVALID_SCHEMA_BUNDLE,
            "every required method needs exactly one input/output schema pin",
            path="$.methodSchemas",
        )
    bundled_by_id = {item.schema_id: item for item in bundle.schemas}
    for method_schema in manifest.method_schemas:
        expected_input, expected_output = REQUIRED_METHOD_SCHEMA_IDS[method_schema.method]
        if (
            method_schema.input_schema_id != expected_input
            or method_schema.output_schema_id != expected_output
        ):
            return _rejected(
                DomainRegistrationFailureCode.INVALID_SCHEMA_BUNDLE,
                f"{method_schema.method.value} does not use the authority schema IDs",
                path="$.methodSchemas",
            )
        input_document = bundled_by_id.get(expected_input)
        output_document = bundled_by_id.get(expected_output)
        if (
            input_document is None
            or output_document is None
            or input_document.schema_digest != method_schema.input_schema_digest
            or output_document.schema_digest != method_schema.output_schema_digest
        ):
            return _rejected(
                DomainRegistrationFailureCode.INVALID_SCHEMA_BUNDLE,
                f"{method_schema.method.value} schema pins do not resolve to the local bundle",
                path="$.methodSchemas",
            )
    domain_schema_ids = set(manifest.domain_schemas.model_dump(mode="json", by_alias=True).values())
    if not domain_schema_ids <= set(bundled_by_id):
        return _rejected(
            DomainRegistrationFailureCode.INVALID_SCHEMA_BUNDLE,
            "every domain schema declaration must resolve to the local bundle",
            path="$.domainSchemas",
        )

    build_output_id = REQUIRED_METHOD_SCHEMA_IDS[
        DomainContractMethod.BUILD_FINAL_OUTPUT
    ][1]
    build_output_schema = bundled_by_id[build_output_id].schema_document
    if _schema_without_identity(build_output_schema) != _schema_without_identity(
        manifest.final_output_schema
    ):
        return _rejected(
            DomainRegistrationFailureCode.INVALID_FINAL_OUTPUT_SCHEMA,
            "build_final_output method output must match the Agent final output schema",
            path="$.finalOutputSchema",
        )

    bundle_schema_documents = [item.schema_document for item in bundle.schemas]
    artifact_schema_documents = list(bundle_schema_documents)
    artifact_schema_documents.extend(
        schema
        for tool in manifest.allowed_tools
        for schema in (tool.input_schema, tool.output_schema)
    )
    artifact_schema_documents.append(manifest.final_output_schema)
    schema_ids = [str(schema["$id"]) for schema in artifact_schema_documents]
    if len(schema_ids) != len(set(schema_ids)):
        return _rejected(
            DomainRegistrationFailureCode.INVALID_SCHEMA_BUNDLE,
            "schema $id values must be globally unique across Pack artifacts",
            path="$.schemaBundle",
        )
    bundle_schema_ids = {str(schema["$id"]) for schema in bundle_schema_documents}
    try:
        for index, document in enumerate(bundle.schemas):
            validate_schema_document(
                document.schema_document,
                path=f"$.schemaBundle.schemas[{index}].schema",
                allowed_schema_ids=bundle_schema_ids,
            )
        bundle_registry_context = _schema_registry(bundle_schema_documents)
        for document_index, document in enumerate(bundle.schemas):
            if canonical_schema_digest(document.schema_document) != document.schema_digest:
                raise ValueError(f"bundled schema {document.schema_id} digest changed")
            for example_index, example in enumerate(document.examples):
                _validate_json_schema_value_in_context(
                    document.schema_document,
                    example,
                    path=(
                        f"$.schemaBundle.schemas[{document_index}]"
                        f".examples[{example_index}]"
                    ),
                    context=bundle_registry_context,
                )
    except ValueError as exc:
        return _rejected(
            DomainRegistrationFailureCode.INVALID_SCHEMA_BUNDLE,
            str(exc),
            path="$.schemaBundle",
        )

    if len({tool.tool_id for tool in manifest.allowed_tools}) != len(manifest.allowed_tools):
        return _rejected(
            DomainRegistrationFailureCode.INVALID_TOOL_CONTRACT,
            "allowed tool IDs must be unique",
            path="$.allowedTools",
        )
    for tool_index, tool in enumerate(manifest.allowed_tools):
        try:
            validate_schema_document(
                tool.input_schema,
                path=f"$.allowedTools[{tool_index}].inputSchema",
                allowed_schema_ids={cast(str, tool.input_schema["$id"])},
            )
            validate_schema_document(
                tool.output_schema,
                path=f"$.allowedTools[{tool_index}].outputSchema",
                allowed_schema_ids={cast(str, tool.output_schema["$id"])},
            )
            _validate_json_schema_value_in_context(
                tool.input_schema,
                tool.input_example,
                path=f"$.allowedTools[{tool_index}].inputExample",
                context=_schema_registry((tool.input_schema,)),
            )
            _validate_json_schema_value_in_context(
                tool.output_schema,
                tool.output_example,
                path=f"$.allowedTools[{tool_index}].outputExample",
                context=_schema_registry((tool.output_schema,)),
            )
        except ValueError as exc:
            return _rejected(
                DomainRegistrationFailureCode.INVALID_TOOL_CONTRACT,
                str(exc),
                path=f"$.allowedTools[{tool_index}]",
            )

        available_version = registered_tool_capabilities.get(tool.tool_id)
        if available_version is None:
            return _rejected(
                DomainRegistrationFailureCode.INVALID_TOOL_CONTRACT,
                f"allowed tool {tool.tool_id}@{tool.tool_version} is not registered",
                path=f"$.allowedTools[{tool_index}].toolId",
            )
        if available_version != tool.tool_version:
            return _rejected(
                DomainRegistrationFailureCode.INVALID_TOOL_CONTRACT,
                (
                    f"allowed tool {tool.tool_id} requires {tool.tool_version}, "
                    f"but registry provides {available_version}"
                ),
                path=f"$.allowedTools[{tool_index}].toolVersion",
            )

    try:
        validate_schema_document(
            manifest.final_output_schema,
            path="$.finalOutputSchema",
            allowed_schema_ids={cast(str, manifest.final_output_schema["$id"])},
        )
        _validate_json_schema_value_in_context(
            manifest.final_output_schema,
            manifest.final_output_example,
            path="$.finalOutputExample",
            context=_schema_registry((manifest.final_output_schema,)),
        )
    except ValueError as exc:
        return _rejected(
            DomainRegistrationFailureCode.INVALID_FINAL_OUTPUT_SCHEMA,
            str(exc),
            path="$.finalOutputSchema",
        )

    required_scoring_inputs = {"declared_public_feature_set", "explicit_versioned_config"}
    required_forbidden_inputs = {
        "user_memory",
        "session_memory",
        "wall_clock",
        "randomness",
        "environment",
        "framework_state",
    }
    required_forbidden_effects = {
        "network",
        "filesystem",
        "database",
        "cache",
        "workflow",
        "connector",
    }
    scoring = manifest.scoring_policy
    if (
        not required_scoring_inputs <= set(scoring.inputs)
        or not required_forbidden_inputs <= set(scoring.forbidden_inputs)
        or not required_forbidden_effects <= set(scoring.forbidden_effects)
    ):
        return _rejected(
            DomainRegistrationFailureCode.IMPURE_SCORING_POLICY,
            "public scoring policy does not declare all purity boundaries",
            path="$.scoringPolicy",
        )

    for source in manifest.domain_sources:
        available_version = registered_source_capabilities.get(source.capability)
        if source.required and (
            available_version is None
            or not _version_in_range(available_version, source.version_range)
        ):
            return _rejected(
                DomainRegistrationFailureCode.UNRESOLVED_SOURCE_CAPABILITY,
                f"required source capability {source.capability} is unresolved",
                path="$.domainSources",
            )

    try:
        described = implementation.describe()
    except Exception as exc:  # Pure validation turns Pack initialization errors into isolation.
        return _rejected(
            DomainRegistrationFailureCode.INVALID_MANIFEST,
            f"Pack describe failed: {type(exc).__name__}",
            path="$.implementation.describe",
        )
    if described != manifest:
        return _rejected(
            DomainRegistrationFailureCode.INVALID_MANIFEST,
            "Pack describe result differs from the validated manifest",
            path="$.implementation.describe",
        )
    try:
        describe_schema = bundled_by_id[REQUIRED_METHOD_SCHEMA_IDS[DomainContractMethod.DESCRIBE][1]]
        _validate_json_schema_value_in_context(
            describe_schema.schema_document,
            described.model_dump(mode="json", by_alias=True),
            path="$.implementation.describe",
            context=bundle_registry_context,
        )
    except ValueError as exc:
        return _rejected(
            DomainRegistrationFailureCode.INVALID_MANIFEST,
            str(exc),
            path="$.implementation.describe",
        )

    return RegistrationValidationResult(
        accepted=True,
        activation_allowed=True,
        contract_pin=DomainContractPin.from_manifest(manifest),
    )


def _rejected(
    code: DomainRegistrationFailureCode, detail: str, *, path: str = "$"
) -> RegistrationValidationResult:
    return RegistrationValidationResult(
        accepted=False,
        activation_allowed=False,
        failure_code=code,
        issues=(RegistrationIssue(code=code, path=path, detail=detail),),
    )


def _code_for_manifest_error(exc: ValidationError) -> DomainRegistrationFailureCode:
    errors = exc.errors(include_url=False)
    locations = [str(error["loc"][0]) for error in errors if error["loc"]]
    error_types = {str(error["type"]) for error in errors}
    if any(location in {"allowedTools", "allowed_tools"} for location in locations):
        return DomainRegistrationFailureCode.INVALID_TOOL_CONTRACT
    if "invalid_final_output_schema" in error_types or any(
        location
        in {
            "finalOutputSchema",
            "finalOutputExample",
            "final_output_schema",
            "final_output_example",
        }
        for location in locations
    ):
        return DomainRegistrationFailureCode.INVALID_FINAL_OUTPUT_SCHEMA
    if any(
        location in {"methodSchemas", "domainSchemas", "method_schemas", "domain_schemas"}
        for location in locations
    ):
        return DomainRegistrationFailureCode.INVALID_SCHEMA_BUNDLE
    if any(location in {"methods"} for location in locations):
        return DomainRegistrationFailureCode.MISSING_CONTRACT_METHOD
    if any(location in {"contractApi", "contract_api"} for location in locations):
        return DomainRegistrationFailureCode.INCOMPATIBLE_CONTRACT_API
    if any(location in {"scoringPolicy", "scoring_policy"} for location in locations):
        return DomainRegistrationFailureCode.IMPURE_SCORING_POLICY
    return DomainRegistrationFailureCode.INVALID_MANIFEST


def _parse_version_range(
    version_range: str,
) -> tuple[tuple[str, SemVer], ...] | None:
    clause_pattern = re.compile(
        rf"\s*(?P<operator>>=|<=|>|<|==)?\s*"
        rf"(?P<version>{_SEMVER_VALUE_PATTERN})\s*"
    )
    clauses: list[tuple[str, SemVer]] = []
    for clause in version_range.split(","):
        match = clause_pattern.fullmatch(clause)
        if match is None:
            return None
        parsed = _parse_semver(match.group("version"))
        if parsed is None:
            return None
        clauses.append((match.group("operator") or "==", parsed))
    return tuple(clauses) or None


def _version_in_range(version: str, version_range: str) -> bool:
    parsed = _parse_semver(version)
    clauses = _parse_version_range(version_range)
    if parsed is None or clauses is None:
        return False
    for operator, other in clauses:
        comparison = _compare_semver(parsed, other)
        if not {
            ">=": comparison >= 0,
            "<=": comparison <= 0,
            ">": comparison > 0,
            "<": comparison < 0,
            "==": comparison == 0,
        }[operator]:
            return False
    return True


SemVer = tuple[int, int, int, tuple[str, ...] | None]


def _parse_semver(value: str) -> SemVer | None:
    match = re.fullmatch(_SEMVER_PATTERN, value)
    if match is None:
        return None
    without_build = value.split("+", maxsplit=1)[0]
    _core, separator, prerelease = without_build.partition("-")
    identifiers = tuple(prerelease.split(".")) if separator else None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)), identifiers)


def _compare_semver(left: SemVer, right: SemVer) -> int:
    left_core = left[:3]
    right_core = right[:3]
    if left_core != right_core:
        return 1 if left_core > right_core else -1

    left_prerelease = left[3]
    right_prerelease = right[3]
    if left_prerelease is None or right_prerelease is None:
        if left_prerelease is right_prerelease:
            return 0
        return 1 if left_prerelease is None else -1

    for left_identifier, right_identifier in zip(left_prerelease, right_prerelease, strict=False):
        if left_identifier == right_identifier:
            continue
        left_numeric = left_identifier.isdigit()
        right_numeric = right_identifier.isdigit()
        if left_numeric and right_numeric:
            return 1 if int(left_identifier) > int(right_identifier) else -1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return 1 if left_identifier > right_identifier else -1

    if len(left_prerelease) == len(right_prerelease):
        return 0
    return 1 if len(left_prerelease) > len(right_prerelease) else -1


__all__ = [
    "DOMAIN_CONTRACT_API",
    "DOMAIN_PACK_ENTRY_POINT_GROUP",
    "JSON_SCHEMA_DIALECT",
    "MANIFEST_DIGEST_PREIMAGE_VERSION",
    "AllowedToolContract",
    "BundledSchemaDocument",
    "DomainContract",
    "DomainContractMethod",
    "DomainContractPin",
    "DomainPackDiscoveryPolicy",
    "DomainPackManifest",
    "DomainPolicyProfiles",
    "DomainRegistrationFailureCode",
    "DomainSchemaBundle",
    "DomainSchemaDeclarations",
    "DomainSourceCapability",
    "JsonSchema",
    "MethodSchemaContract",
    "PublicScoringPolicy",
    "REQUIRED_DOMAIN_METHODS",
    "REQUIRED_METHOD_SCHEMA_IDS",
    "RegistrationIssue",
    "RegistrationValidationResult",
    "ToolSchemaPin",
    "canonical_manifest_digest",
    "canonical_schema_digest",
    "validate_domain_pack_registration",
    "validate_json_schema_value",
    "validate_schema_document",
]
