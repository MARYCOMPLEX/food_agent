"""Feature-gated Composition Root platform binding checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from xhs_food.composition.platform_bindings import build_platform_bindings
from xhs_food.contracts import PlatformAccountRef, PlatformChannel, SessionActivationRequest
from xhs_food.foundation.config import TargetSettings
from xhs_food.foundation.platform_accounts import (
    AesGcmSessionCodec,
    InMemoryKeyProvider,
    InMemoryPlatformAccountAuthority,
)


class _Factory:
    def __call__(self, *_args: object) -> object:
        return object()


def test_platform_bindings_are_inert_when_feature_flag_is_off() -> None:
    assembly = build_platform_bindings(TargetSettings())

    assert assembly.connector_factories == {}
    assert assembly.gateway is None
    assert assembly.readiness.ready is True
    assert all(item.enabled is False for item in assembly.readiness.statuses)
    assert all(item.reason == "platform feature flag is disabled" for item in assembly.readiness.statuses)


def test_platform_binding_uses_injected_factory_and_account_authority() -> None:
    target = TargetSettings(
        platform_connectors_enabled=True,
        platform_dianping_enabled=True,
        platform_provenance_ref="fixture/provenance",
        platform_license_approval_ref="fixture/license",
    )
    authority = object()
    codec = object()
    assembly = build_platform_bindings(
        target,
        account_authority=authority,
        session_codec=codec,
        connector_factories={"dianping": _Factory()},
    )

    status = assembly.readiness.by_platform["dianping"]
    assert status.enabled is True
    assert status.ready is True
    assert assembly.gateway is not None
    assert assembly.gateway.connector_channels == ("dianping",)
    assert assembly.capabilities.resolve("place.lookup", source_id="dianping").enabled is True


def test_platform_capabilities_keep_legacy_snapshots_for_explicit_selection() -> None:
    target = TargetSettings(
        platform_connectors_enabled=True,
        platform_dianping_enabled=True,
        platform_provenance_ref="fixture/provenance",
        platform_license_approval_ref="fixture/license",
    )
    assembly = build_platform_bindings(
        target,
        account_authority=object(),
        session_codec=object(),
        connector_factories={"dianping": _Factory()},
        legacy_capabilities={"place.lookup": ("place_compat", "1.0.0")},
    )

    with pytest.raises(ValueError, match="multiple enabled registrations"):
        assembly.capabilities.resolve("place.lookup")
    assert assembly.capabilities.resolve("place.lookup", source_id="place_compat").source_id == "place_compat"


def test_missing_platform_authority_or_approval_fails_closed_without_legacy_fallback() -> None:
    target = TargetSettings(
        platform_connectors_enabled=True,
        platform_xhs_enabled=True,
        platform_provenance_ref="fixture/provenance",
        # Deliberately omit the owner/legal approval reference.
    )
    assembly = build_platform_bindings(
        target,
        account_authority=object(),
        session_codec=object(),
        connector_factories={"xhs_pc": _Factory(), "xhs_creator": _Factory()},
    )

    assert assembly.gateway is None
    assert assembly.readiness.gateway_reason == "no platform provider binding is ready"
    assert all(item.enabled is False for item in assembly.readiness.statuses if item.requested)
    assert all("license approval" in (item.reason or "") for item in assembly.readiness.statuses if item.requested)


@pytest.mark.parametrize("channel", ["xhs_pc", "xhs_creator"])
def test_xhs_channels_remain_separate_in_readiness(channel: str) -> None:
    target = TargetSettings(
        platform_connectors_enabled=True,
        platform_xhs_enabled=True,
        platform_provenance_ref="fixture/provenance",
        platform_license_approval_ref="fixture/license",
    )
    assembly = build_platform_bindings(
        target,
        account_authority=object(),
        session_codec=object(),
        connector_factories={"xhs_pc": _Factory(), "xhs_creator": _Factory()},
    )

    assert assembly.readiness.by_platform[channel].platform == channel
    assert set(assembly.gateway.connector_channels if assembly.gateway else ()) == {
        "xhs_pc",
        "xhs_creator",
    }


def test_creator_capability_registry_filters_pc_only_operations() -> None:
    target = TargetSettings(
        platform_connectors_enabled=True,
        platform_xhs_enabled=True,
        platform_provenance_ref="fixture/provenance",
        platform_license_approval_ref="fixture/license",
    )
    assembly = build_platform_bindings(
        target,
        account_authority=object(),
        session_codec=object(),
        connector_factories={"xhs_creator": _Factory()},
    )

    assert assembly.capabilities.resolve("notes.search", source_id="xhs").enabled is True
    with pytest.raises(LookupError):
        assembly.capabilities.resolve("reviews.search", source_id="xhs")


def test_login_flag_requires_the_isolated_account_auth_queue() -> None:
    target = TargetSettings(
        platform_connectors_enabled=True,
        platform_login_enabled=True,
        platform_provenance_ref="fixture/provenance",
        platform_license_approval_ref="fixture/license",
    )
    assembly = build_platform_bindings(
        target,
        account_authority=object(),
        session_codec=object(),
        login_service=object(),
    )

    assert assembly.readiness.login_requested is True
    assert assembly.readiness.login_enabled is False
    assert assembly.readiness.login_reason == "account-auth Temporal worker is disabled"


def test_login_readiness_requires_object_store_for_qr_lifecycle() -> None:
    target = TargetSettings(
        platform_connectors_enabled=True,
        platform_login_enabled=True,
        temporal_account_auth_enabled=True,
        temporal_account_auth_queue="account-auth",
        platform_provenance_ref="fixture/provenance",
        platform_license_approval_ref="fixture/license",
    )

    without_store = build_platform_bindings(
        target,
        account_authority=object(),
        session_codec=object(),
        login_service=object(),
    )
    assert without_store.readiness.login_enabled is False
    assert without_store.readiness.login_reason == "platform ObjectStore is not configured"

    class _ObjectStore:
        async def put(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def delete(self, *_args: object, **_kwargs: object) -> None:
            return None

    with_store = build_platform_bindings(
        target,
        account_authority=object(),
        session_codec=object(),
        login_service=object(),
        object_store=_ObjectStore(),
    )
    assert with_store.readiness.login_enabled is True
    assert with_store.readiness.login_reason is None


@pytest.mark.asyncio
async def test_flag_rollback_keeps_encrypted_authority_and_pinned_inflight_binding() -> None:
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    ref = PlatformAccountRef(
        tenant_id="tenant-a",
        platform=PlatformChannel.DIANPING,
        account_ref="rollback-account",
    )
    authority = InMemoryPlatformAccountAuthority(clock=lambda: now)
    await authority.register_account(
        tenant_id=ref.tenant_id,
        platform=ref.platform,
        account_ref=ref.account_ref,
        alias="rollback",
        now=now,
    )
    codec = AesGcmSessionCodec(
        InMemoryKeyProvider({("test", "v1"): b"r" * 32}),
        key_ref="test",
        key_version="v1",
    )
    expiry = now + timedelta(hours=1)
    envelope = await codec.seal(
        ref,
        b'{"cookie":"encrypted-authority-fixture"}',
        expires_at=expiry,
        version=1,
    )
    await authority.activate_session(
        SessionActivationRequest(
            account=ref,
            expected_session_version=0,
            envelope=envelope,
            expires_at=expiry,
            requested_at=now,
        )
    )
    provider_factory = _Factory()
    enabled = build_platform_bindings(
        TargetSettings(
            platform_connectors_enabled=True,
            platform_dianping_enabled=True,
            platform_provenance_ref="fixture/provenance",
            platform_license_approval_ref="fixture/license",
        ),
        account_authority=authority,
        session_codec=codec,
        connector_factories={"dianping": provider_factory},
    )
    pinned_factory = enabled.connector_factories["dianping"]
    pinned_capability = enabled.capabilities.resolve("place.lookup", source_id="dianping")

    disabled = build_platform_bindings(
        TargetSettings(),
        account_authority=authority,
        session_codec=codec,
    )
    assert disabled.gateway is None
    assert disabled.connector_factories == {}
    assert disabled.capabilities.resolve("place.lookup", source_id="place_compat").enabled is True
    # Already-started work retains its immutable connector snapshot, while new
    # composition has no platform route. No account/session row is deleted.
    assert pinned_factory is provider_factory
    assert pinned_capability.connector_version == "dianping-platform/v1"
    assert enabled.gateway is not None
    active = await authority.get_active_session(ref)
    assert active is not None and active.version == 1
    assert "encrypted-authority-fixture" not in active.model_dump_json()
