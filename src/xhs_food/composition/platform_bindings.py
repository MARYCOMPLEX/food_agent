"""Feature-gated platform bindings owned by the Composition Root.

The platform source adapters are deliberately inert until an operator turns
on ``TargetSettings.platform_connectors_enabled`` and supplies the authority
dependencies required by :class:`AccountBoundSourceGateway`.  This module is
kept separate from the legacy builder so importing the application with the
default flags does not import either upstream checkout or create a second
source runtime.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

from xhs_food.gateways.capabilities import (
    CapabilityRegistration,
    PlatformCapabilityRegistry,
)
from xhs_food.gateways.platform_gateway import AccountBoundSourceGateway


@dataclass(frozen=True, slots=True)
class PlatformBindingStatus:
    """Redacted readiness state for one account channel.

    Status objects intentionally contain references and versions only.  They
    never carry cookies, QR bytes, signer state, or a decrypted session.
    ``available`` describes dependency readiness while ``enabled`` additionally
    requires the operator feature flag and a qualified dependency set.
    """

    platform: str
    source_id: str
    requested: bool
    enabled: bool
    available: bool
    mode: str
    connector_version: str
    checkout: str | None = None
    provenance_ref: str | None = None
    license_approval_ref: str | None = None
    dependency_digest: str | None = None
    reason: str | None = None

    @property
    def ready(self) -> bool:
        return self.enabled and self.available

    @property
    def disabled(self) -> bool:
        return not self.enabled

    @property
    def state(self) -> str:
        """Stable operator-facing state label used by health projections."""

        if self.enabled and self.available:
            return "enabled"
        if self.requested:
            return "dependency-unavailable"
        return "disabled"

    @property
    def dependency_unavailable(self) -> bool:
        return self.requested and not self.available

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-safe, secret-free projection for health endpoints."""

        return {
            "platform": self.platform,
            "source_id": self.source_id,
            "requested": self.requested,
            "enabled": self.enabled,
            "available": self.available,
            "ready": self.ready,
            "state": self.state,
            "mode": self.mode,
            "connector_version": self.connector_version,
            "checkout": self.checkout,
            "provenance_ref": self.provenance_ref,
            "license_approval_ref": self.license_approval_ref,
            "dependency_digest": self.dependency_digest,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class PlatformReadiness:
    """Aggregate feature/readiness projection exposed by the root."""

    statuses: tuple[PlatformBindingStatus, ...]
    gateway_enabled: bool
    gateway_reason: str | None = None
    login_requested: bool = False
    login_enabled: bool = False
    login_queue: str | None = None
    login_reason: str | None = None

    @property
    def ready(self) -> bool:
        requested = tuple(item for item in self.statuses if item.requested)
        source_ready = all(item.ready for item in requested) if requested else True
        login_ready = not self.login_requested or self.login_enabled
        return source_ready and login_ready and (
            not requested or self.gateway_enabled
        )

    @property
    def state(self) -> str:
        if self.ready:
            return "ready"
        if any(item.requested for item in self.statuses) or self.login_requested:
            return "dependency-unavailable"
        return "disabled"

    @property
    def by_platform(self) -> Mapping[str, PlatformBindingStatus]:
        return MappingProxyType({item.platform: item for item in self.statuses})

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "state": self.state,
            "gateway": {
                "enabled": self.gateway_enabled,
                "reason": self.gateway_reason,
            },
            "login": {
                "requested": self.login_requested,
                "enabled": self.login_enabled,
                "queue": self.login_queue,
                "reason": self.login_reason,
            },
            "platforms": [item.as_dict() for item in self.statuses],
        }


@dataclass(frozen=True, slots=True)
class PlatformBindingAssembly:
    """Objects the Composition Root installs in its platform registry."""

    connector_factories: Mapping[str, Callable[..., object]]
    provider_factories: Mapping[str, Callable[..., object]]
    capabilities: PlatformCapabilityRegistry
    readiness: PlatformReadiness
    gateway: AccountBoundSourceGateway | None
    account_authority: object | None = None
    session_codec: object | None = None
    login_service: object | None = None
    object_store: object | None = None


_CHANNELS = ("dianping", "xhs_pc", "xhs_creator")
_CONNECTOR_VERSIONS = {
    "dianping": "dianping-platform/v1",
    "xhs_pc": "xhs-platform/v1",
    "xhs_creator": "xhs-platform/v1",
}
_SOURCE_IDS = {"dianping": "dianping", "xhs_pc": "xhs", "xhs_creator": "xhs"}
_CAPABILITIES = {
    "dianping": ("place.lookup", "reviews.search", "media.refs"),
    "xhs": ("notes.search", "reviews.search", "media.refs"),
}
# Creator Studio intentionally exposes only the account's own note listing;
# detail/comments/media remain unregistered rather than being advertised and
# failing later at invocation time.
_CHANNEL_CAPABILITIES = {
    "dianping": frozenset(_CAPABILITIES["dianping"]),
    "xhs_pc": frozenset(_CAPABILITIES["xhs"]),
    "xhs_creator": frozenset({"notes.search"}),
}


def build_platform_bindings(
    target_settings: Any,
    *,
    account_authority: object | None = None,
    session_codec: object | None = None,
    connector_factories: Mapping[str, Callable[..., object]] | None = None,
    provider_factories: Mapping[str, Callable[..., object]] | None = None,
    source_control: object | None = None,
    health: object | None = None,
    capability_registry: Any | None = None,
    login_service: object | None = None,
    object_store: object | None = None,
    provenance_ref: str | None = None,
    license_approval_ref: str | None = None,
    dependency_digests: Mapping[str, str] | None = None,
    legacy_capabilities: Mapping[str, tuple[str, str]] | None = None,
) -> PlatformBindingAssembly:
    """Resolve feature-gated provider factories and account gateway.

    ``connector_factories`` are already canonical connector factories (the
    three-argument account/session/material shape).  ``provider_factories``
    are lower-level provider factories and are wrapped with the project-owned
    canonical connector classes.  Both maps accept enum-like keys and the
    aggregate ``xhs`` key; XHS PC and Creator are kept separate internally.
    """

    from xhs_food.composition.adapters.platforms import (
        ProviderDependencyStatus,
        build_dianping_provider_factory,
        build_xhs_provider_factory,
    )
    from xhs_food.gateways.platform_sources import (
        DianpingPlatformSourceConnector,
        XhsCreatorSourceConnector,
        XhsPcSourceConnector,
    )

    direct = _normalize_factory_map(connector_factories)
    providers = _normalize_factory_map(provider_factories)
    digests = _normalize_string_map(dependency_digests)
    configured_provenance = _first_text(
        provenance_ref,
        getattr(target_settings, "platform_provenance_ref", None),
    )
    configured_license = _first_text(
        license_approval_ref,
        getattr(target_settings, "platform_license_approval_ref", None),
    )
    mode = str(getattr(target_settings, "platform_provider_mode", "in_process"))
    connectors_enabled = bool(getattr(target_settings, "platform_connectors_enabled", False))
    requested = {
        "dianping": connectors_enabled
        and bool(getattr(target_settings, "platform_dianping_enabled", False)),
        "xhs_pc": connectors_enabled and bool(getattr(target_settings, "platform_xhs_enabled", False)),
        "xhs_creator": connectors_enabled and bool(getattr(target_settings, "platform_xhs_enabled", False)),
    }

    checkouts = {
        "dianping": _optional_text(getattr(target_settings, "platform_dianping_checkout", None)),
        "xhs_pc": _optional_text(getattr(target_settings, "platform_xhs_checkout", None)),
        "xhs_creator": _optional_text(getattr(target_settings, "platform_xhs_checkout", None)),
    }
    connector_classes: dict[str, type[Any]] = {
        "dianping": DianpingPlatformSourceConnector,
        "xhs_pc": XhsPcSourceConnector,
        "xhs_creator": XhsCreatorSourceConnector,
    }

    resolved_connectors: dict[str, Callable[..., object]] = {}
    resolved_providers: dict[str, Callable[..., object]] = {}
    statuses: list[PlatformBindingStatus] = []

    for channel in _CHANNELS:
        source_id = _SOURCE_IDS[channel]
        factory = direct.get(channel)
        if factory is None and channel.startswith("xhs_"):
            # A single injected XHS factory may intentionally represent both
            # account channels; the gateway still keys the resulting clients
            # by the concrete ``xhs_pc``/``xhs_creator`` channel.
            factory = direct.get("xhs")
        if factory is None and source_id == "dianping":
            factory = direct.get(source_id)
        provider = providers.get(channel) or (providers.get("xhs") if channel.startswith("xhs_") else None)
        checkout = checkouts[channel]
        dependency_status: ProviderDependencyStatus | None = None

        # An explicit canonical connector factory is the preferred seam for
        # tests and for a future sidecar transport.  Provider factories are
        # wrapped only when no canonical factory was supplied.
        if (
            factory is None
            and provider is None
            and requested[channel]
            and mode != "sidecar"
            and checkout
        ):
            if channel == "dianping":
                provider = build_dianping_provider_factory(
                    checkout,
                    provenance_ref=configured_provenance,
                )
            else:
                provider = build_xhs_provider_factory(
                    checkout,
                    channel=channel,
                    provenance_ref=configured_provenance,
                )
        if provider is not None and factory is None:
            factory = _wrap_provider_factory(provider, connector_classes[channel], channel)
            resolved_providers[channel] = provider
        elif provider is not None:
            resolved_providers[channel] = provider

        if provider is not None:
            dependency_status = _provider_status(provider)

        available, reason = _dependency_gate(
            channel=channel,
            requested=requested[channel],
            mode=mode,
            checkout=checkout,
            factory=factory,
            provider_status=dependency_status,
            provenance_ref=configured_provenance,
            license_approval_ref=configured_license,
            authority_configured=account_authority is not None,
            codec_configured=session_codec is not None,
        )
        enabled = bool(requested[channel] and available)
        if factory is not None and enabled:
            resolved_connectors[channel] = factory
        dependency_digest = (
            digests.get(channel)
            or digests.get(source_id)
            or _optional_text(getattr(factory, "dependency_digest", None))
            or _optional_text(getattr(provider, "dependency_digest", None))
        )
        statuses.append(
            PlatformBindingStatus(
                platform=channel,
                source_id=source_id,
                requested=requested[channel],
                enabled=enabled,
                available=available,
                mode=(dependency_status.mode if dependency_status is not None else mode),
                connector_version=_CONNECTOR_VERSIONS[channel],
                checkout=checkout,
                provenance_ref=configured_provenance,
                license_approval_ref=configured_license,
                dependency_digest=dependency_digest,
                reason=reason,
            )
        )

    # Keep the pre-existing Amap/legacy-XHS snapshots visible to the
    # multiplexer. New platform registrations therefore create an explicit
    # collision that callers must resolve by source/version instead of
    # silently replacing a legacy provider.
    registry = capability_registry or PlatformCapabilityRegistry()
    default_legacy_capabilities = {
        "place.lookup": ("place_compat", "1.0.0"),
        "reviews.search": ("xhs_compat", "1.0.0"),
    }
    for capability, (legacy_source, legacy_version) in (
        default_legacy_capabilities if legacy_capabilities is None else legacy_capabilities
    ).items():
        _register_capability(
            registry,
            CapabilityRegistration(
                capability=str(capability),
                version=str(legacy_version),
                source_id=str(legacy_source),
                connector_version=str(legacy_version),
                enabled=True,
                provenance_ref=f"legacy/{legacy_source}",
            ),
        )

    # Register one source-level capability snapshot for XHS.  PC/Creator are
    # account channels, not competing public source IDs; the gateway chooses
    # the channel-specific connector from the invocation.
    for source_id, capabilities in _CAPABILITIES.items():
        channel_statuses = [item for item in statuses if item.source_id == source_id]
        source_enabled = any(item.enabled for item in channel_statuses)
        status = next((item for item in channel_statuses if item.enabled), channel_statuses[0])
        for capability in capabilities:
            capability_enabled = source_enabled and any(
                item.enabled
                and capability in _CHANNEL_CAPABILITIES.get(item.platform, frozenset())
                for item in channel_statuses
            )
            _register_capability(
                registry,
                CapabilityRegistration(
                    capability=capability,
                    version="platform-capability/v1",
                    source_id=source_id,
                    connector_version=status.connector_version,
                    enabled=capability_enabled,
                    provenance_ref=(status.provenance_ref or "") if capability_enabled else "",
                    dependency_digest=status.dependency_digest or "",
                ),
            )

    gateway_reason: str | None = None
    gateway: AccountBoundSourceGateway | None = None
    requested_any = any(requested.values())
    if not requested_any:
        gateway_reason = "platform connector feature flag is disabled"
    elif account_authority is None:
        gateway_reason = "platform account authority is not configured"
    elif session_codec is None:
        gateway_reason = "platform session codec is not configured"
    elif not resolved_connectors:
        gateway_reason = "no platform provider binding is ready"
    else:
        gateway = AccountBoundSourceGateway(
            accounts=cast(Any, account_authority),
            codec=cast(Any, session_codec),
            connector_factories=cast(Any, resolved_connectors),
            source_control=cast(Any, source_control),
            health=health,
            lease_ttl_seconds=int(getattr(target_settings, "platform_lease_ttl_seconds", 180)),
        )

    login_requested = bool(
        connectors_enabled and getattr(target_settings, "platform_login_enabled", False)
    )
    login_queue = _optional_text(getattr(target_settings, "temporal_account_auth_queue", None))
    login_enabled = False
    login_reason: str | None = None
    if login_requested:
        if not bool(getattr(target_settings, "temporal_account_auth_enabled", False)):
            login_reason = "account-auth Temporal worker is disabled"
        elif not login_queue:
            login_reason = "account-auth Temporal queue is not configured"
        elif account_authority is None:
            login_reason = "platform account authority is not configured"
        elif session_codec is None:
            login_reason = "platform session codec is not configured"
        elif login_service is None:
            login_reason = "platform login service is not configured"
        elif not _object_store_ready(object_store):
            login_reason = "platform ObjectStore is not configured"
        else:
            login_enabled = True

    readiness = PlatformReadiness(
        statuses=tuple(statuses),
        gateway_enabled=gateway is not None,
        gateway_reason=gateway_reason,
        login_requested=login_requested,
        login_enabled=login_enabled,
        login_queue=login_queue,
        login_reason=login_reason,
    )
    return PlatformBindingAssembly(
        connector_factories=MappingProxyType(dict(resolved_connectors)),
        provider_factories=MappingProxyType(dict(resolved_providers)),
        capabilities=registry,
        readiness=readiness,
        gateway=gateway,
        account_authority=account_authority,
        session_codec=session_codec,
        login_service=login_service,
        object_store=object_store,
    )


def _normalize_factory_map(
    values: Mapping[str, Callable[..., object]] | None,
) -> dict[str, Callable[..., object]]:
    result: dict[str, Callable[..., object]] = {}
    for key, value in (values or {}).items():
        normalized = getattr(key, "value", key)
        text = str(normalized).strip().casefold()
        if text and callable(value):
            result[text] = value
    return result


def _normalize_string_map(values: Mapping[str, str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in (values or {}).items():
        text = str(getattr(key, "value", key)).strip().casefold()
        if text and value is not None and str(value).strip():
            result[text] = str(value).strip()
    return result


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_text(*values: object) -> str | None:
    for value in values:
        text = _optional_text(value)
        if text and text.casefold() not in {"unknown", "pending", "none", "null", "todo"}:
            return text
    return None


def _provider_status(provider: object) -> Any | None:
    status = getattr(provider, "status", None)
    if not callable(status):
        return None
    try:
        value = status()
    except Exception:
        # A readiness probe that cannot complete is itself a dependency
        # failure; never promote a provider to active on a swallowed probe
        # exception.
        return type(
            "_UnavailableProviderStatus",
            (),
            {
                "available": False,
                "mode": "unknown",
                "reason": "provider dependency status probe failed",
            },
        )()
    if inspect.isawaitable(value):
        close = getattr(value, "close", None)
        if callable(close):
            close()
        return type(
            "_UnavailableProviderStatus",
            (),
            {
                "available": False,
                "mode": "unknown",
                "reason": "provider dependency status probe is asynchronous",
            },
        )()
    return value


def _dependency_gate(
    *,
    channel: str,
    requested: bool,
    mode: str,
    checkout: str | None,
    factory: Callable[..., object] | None,
    provider_status: Any | None,
    provenance_ref: str | None,
    license_approval_ref: str | None,
    authority_configured: bool,
    codec_configured: bool,
) -> tuple[bool, str | None]:
    if not requested:
        return False, "platform feature flag is disabled"
    if not authority_configured:
        return False, "platform account authority is not configured"
    if not codec_configured:
        return False, "platform session codec is not configured"
    if mode == "sidecar" and factory is None:
        return False, "sidecar provider transport is not configured"
    if factory is None:
        return False, (
            f"{channel} provider checkout is not configured"
            if not checkout
            else f"{channel} provider factory is unavailable"
        )
    if provider_status is not None and not bool(getattr(provider_status, "available", False)):
        return False, str(getattr(provider_status, "reason", None) or "provider dependency is unavailable")
    if not provenance_ref:
        return False, "provider provenance reference is not configured"
    if not license_approval_ref:
        return False, "provider license approval reference is not configured"
    return True, None


def _object_store_ready(value: object | None) -> bool:
    """Check the minimal QR lifecycle surface without forcing a backend call.

    ``ObjectStore`` is a protocol rather than a concrete class.  Requiring
    put/delete here prevents a login service from advertising readiness while
    QR bytes would have nowhere to go; signed URL support remains optional
    because the API can return an opaque in-app presentation reference.
    """

    if value is None:
        return False
    return all(callable(getattr(value, name, None)) for name in ("put", "delete"))


def _wrap_provider_factory(
    provider_factory: Callable[..., object],
    connector_class: type[Any],
    channel: str,
) -> Callable[..., object]:
    def build(account: object, session: object, material: bytes) -> object:
        provider = _call_factory(provider_factory, account, session, material)
        if inspect.isawaitable(provider):
            async def finish() -> object:
                resolved = await provider
                return connector_class(
                    resolved,
                    account_ref=getattr(account, "account_ref", None),
                )

            return finish()
        return connector_class(
            provider,
            account_ref=getattr(account, "account_ref", None),
        )

    build.__name__ = f"build_{channel}_source_connector"
    return build


def _call_factory(
    factory: Callable[..., object],
    account: object,
    session: object,
    material: bytes,
) -> object:
    """Accept the canonical 3-argument seam and small test-friendly forms."""

    try:
        signature = inspect.signature(factory)
        positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        has_varargs = any(
            parameter.kind is inspect.Parameter.VAR_POSITIONAL
            for parameter in signature.parameters.values()
        )
    except (TypeError, ValueError):
        positional, has_varargs = (), True
    if has_varargs or len(positional) >= 3:
        return factory(account, session, material)
    if len(positional) == 2:
        return factory(account, session)
    return factory(account)


def _register_capability(
    registry: PlatformCapabilityRegistry,
    registration: CapabilityRegistration,
) -> None:
    """Register idempotently when the caller supplied a pre-populated map."""

    existing = registry.snapshot.get(registration.key)
    if existing is None:
        registry.register(registration)
        return
    # A caller-owned registry may already contain the exact immutable snapshot
    # (for example when two roots share a qualification fixture).  Preserve it
    # only when all metadata agrees; otherwise surface the collision.
    if existing != registration:
        raise ValueError(f"platform capability snapshot conflicts: {registration.key}")


__all__ = [
    "PlatformBindingAssembly",
    "PlatformBindingStatus",
    "PlatformReadiness",
    "build_platform_bindings",
]
