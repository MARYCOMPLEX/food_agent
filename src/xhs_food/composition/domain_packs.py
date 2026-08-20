"""Composition-owned Domain Pack registration and immutable task pinning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata
from threading import RLock
from types import MappingProxyType
from typing import Any, Protocol, cast

from xhs_food.contracts import (
    DOMAIN_PACK_ENTRY_POINT_GROUP,
    DomainContract,
    DomainContractPin,
    DomainPackManifest,
    DomainSchemaBundle,
    RegistrationValidationResult,
    validate_domain_pack_registration,
)
from xhs_food.contracts.base import ContractPayload, JsonValue


class DomainPackActivationError(RuntimeError):
    def __init__(self, result: RegistrationValidationResult) -> None:
        issue = result.issues[0]
        super().__init__(f"{issue.code.value} at {issue.path}: {issue.detail}")
        self.result = result


class DomainPackEntryPoint(Protocol):
    """Minimal installed-entry-point surface used by startup discovery."""

    name: str
    group: str

    def load(self) -> object: ...


@dataclass(frozen=True, slots=True)
class RegisteredDomainPack:
    manifest: DomainPackManifest
    schema_bundle: DomainSchemaBundle
    implementation: DomainContract
    contract_pin: DomainContractPin

    @property
    def workflow(self) -> Any:
        """Expose an implementation policy without discarding registration metadata."""

        return cast(Any, self.implementation).workflow

    @property
    def decision(self) -> Any:
        """Expose an implementation policy without discarding registration metadata."""

        return cast(Any, self.implementation).decision

    def validate_final_output(self, value: JsonValue) -> None:
        self.manifest.validate_final_output(value)

    def build_final_output(self, value: ContractPayload) -> JsonValue:
        """Build and validate one output before any compatibility projection.

        Domain implementations remain responsible for pure construction.  The
        registry-owned wrapper is the single path a composition adapter should
        use so a malformed implementation value cannot reach a legacy DTO or
        transport mapper.
        """

        output = self.implementation.build_final_output(value)
        self.validate_final_output(output)
        return output


class DomainPackRegistry:
    """Publish complete Pack versions atomically; rejected candidates remain invisible."""

    def __init__(
        self,
        *,
        core_version: str,
        tool_capabilities: Mapping[str, str],
        source_capabilities: Mapping[str, str],
    ) -> None:
        self._core_version = core_version
        self._tool_capabilities = MappingProxyType(dict(tool_capabilities))
        self._source_capabilities = MappingProxyType(dict(source_capabilities))
        self._packs: dict[tuple[str, str], RegisteredDomainPack] = {}
        self._lock = RLock()

    @property
    def tool_capabilities(self) -> Mapping[str, str]:
        return self._tool_capabilities

    @property
    def source_capabilities(self) -> Mapping[str, str]:
        return self._source_capabilities

    def register_candidate(
        self,
        manifest: DomainPackManifest | Mapping[str, object],
        implementation: DomainContract,
        schema_bundle: DomainSchemaBundle | Mapping[str, object],
    ) -> RegistrationValidationResult:
        with self._lock:
            result = validate_domain_pack_registration(
                manifest,
                implementation,
                schema_bundle=schema_bundle,
                core_version=self._core_version,
                registered_tool_capabilities=self._tool_capabilities,
                registered_source_capabilities=self._source_capabilities,
                existing_pack_versions=tuple(self._packs),
            )
            if not result.activation_allowed:
                return result
            assert result.contract_pin is not None
            registered_manifest = (
                manifest
                if isinstance(manifest, DomainPackManifest)
                else DomainPackManifest.model_validate(manifest)
            )
            registered_bundle = (
                schema_bundle
                if isinstance(schema_bundle, DomainSchemaBundle)
                else DomainSchemaBundle.model_validate(schema_bundle)
            )
            registered = RegisteredDomainPack(
                manifest=registered_manifest,
                schema_bundle=registered_bundle,
                implementation=implementation,
                contract_pin=result.contract_pin,
            )
            self._packs[registered_manifest.pack_key] = registered
            return result

    def register_or_raise(
        self,
        manifest: DomainPackManifest | Mapping[str, object],
        implementation: DomainContract,
        schema_bundle: DomainSchemaBundle | Mapping[str, object],
    ) -> RegisteredDomainPack:
        with self._lock:
            result = self.register_candidate(manifest, implementation, schema_bundle)
            if not result.activation_allowed:
                raise DomainPackActivationError(result)
            # Use the validated pin rather than reaching into the caller-provided
            # value.  Callers may intentionally provide plain mappings, and a
            # mapping has no ``domain_id``/``pack_version`` attributes.
            pin = result.contract_pin
            assert pin is not None
            return self.get(pin.domain_id, pin.pack_version)

    def get(self, domain_id: str, pack_version: str) -> RegisteredDomainPack:
        with self._lock:
            try:
                return self._packs[(domain_id, pack_version)]
            except KeyError as exc:
                raise KeyError(f"unknown Domain Pack: {domain_id}@{pack_version}") from exc

    def pin(self, domain_id: str, pack_version: str) -> DomainContractPin:
        return self.get(domain_id, pack_version).contract_pin

    def unregister(self, domain_id: str, pack_version: str) -> RegisteredDomainPack:
        """Remove only future selection; already copied task pins remain immutable."""

        with self._lock:
            try:
                return self._packs.pop((domain_id, pack_version))
            except KeyError as exc:
                raise KeyError(f"unknown Domain Pack: {domain_id}@{pack_version}") from exc

    def restore(self, registered: RegisteredDomainPack) -> None:
        with self._lock:
            key = registered.manifest.pack_key
            if key in self._packs:
                raise ValueError(f"duplicate Domain Pack: {key[0]}@{key[1]}")
            result = validate_domain_pack_registration(
                registered.manifest,
                registered.implementation,
                schema_bundle=registered.schema_bundle,
                core_version=self._core_version,
                registered_tool_capabilities=self._tool_capabilities,
                registered_source_capabilities=self._source_capabilities,
                existing_pack_versions=tuple(self._packs),
            )
            if not result.activation_allowed:
                raise DomainPackActivationError(result)
            if result.contract_pin != registered.contract_pin:
                raise ValueError("registered Domain Pack pin does not match its manifest")
            self._packs[key] = registered

    def publish_snapshot(self) -> Mapping[tuple[str, str], RegisteredDomainPack]:
        with self._lock:
            return MappingProxyType(dict(self._packs))


def capability_snapshots(
    providers: Sequence[object],
) -> tuple[dict[str, str], dict[str, str]]:
    """Derive declarations from concrete registered provider instances."""

    tools: dict[str, str] = {}
    sources: dict[str, str] = {}
    for provider in providers:
        tool_id = getattr(provider, "name", None)
        tool_version = getattr(provider, "tool_version", None)
        source_id = getattr(provider, "source_capability", None)
        source_version = getattr(provider, "source_version", None)
        if not all(isinstance(value, str) and value for value in (tool_id, tool_version)):
            raise ValueError("Food tool providers must declare a concrete id and version")
        if not all(isinstance(value, str) and value for value in (source_id, source_version)):
            raise ValueError("Food source providers must declare a concrete capability and version")
        tool_name = cast(str, tool_id)
        tool_release = cast(str, tool_version)
        source_name = cast(str, source_id)
        source_release = cast(str, source_version)
        if tool_name in tools or source_name in sources:
            raise ValueError("duplicate Food provider capability")
        tools[tool_name] = tool_release
        sources[source_name] = source_release
    return tools, sources


def discover_allowlisted_domain_packs(
    allow_list: Sequence[str],
    *,
    entry_points: Sequence[DomainPackEntryPoint] | None = None,
) -> tuple[object, ...]:
    """Load only startup allow-listed entry points from the sealed group."""

    allowed = frozenset(allow_list)
    if entry_points is None:
        selected = cast(
            Sequence[DomainPackEntryPoint],
            metadata.entry_points(group=DOMAIN_PACK_ENTRY_POINT_GROUP),
        )
    else:
        selected = entry_points
    loaded: list[object] = []
    seen: set[str] = set()
    for entry_point in selected:
        if getattr(entry_point, "group", None) != DOMAIN_PACK_ENTRY_POINT_GROUP:
            continue
        name = getattr(entry_point, "name", None)
        if not isinstance(name, str) or name not in allowed or name in seen:
            continue
        seen.add(name)
        loaded.append(entry_point.load())
    return tuple(loaded)


__all__ = [
    "DomainPackActivationError",
    "DomainPackEntryPoint",
    "DomainPackRegistry",
    "RegisteredDomainPack",
    "capability_snapshots",
    "discover_allowlisted_domain_packs",
]
