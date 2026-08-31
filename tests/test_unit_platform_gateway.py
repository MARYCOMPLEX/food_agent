"""Account-bound gateway and capability collision contract tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from xhs_food.contracts import (
    AccountGrantPermission,
    AccountLeaseRequest,
    CanonicalQuery,
    CollectRequest,
    PlatformAccountGrant,
    PlatformAccountRef,
    PlatformChannel,
    PlatformSourceInvocation,
    SessionActivationRequest,
)
from xhs_food.foundation.platform_accounts import (
    AesGcmSessionCodec,
    InMemoryKeyProvider,
    InMemoryPlatformAccountAuthority,
)
from xhs_food.gateways.capabilities import (
    CapabilityCollisionError,
    CapabilityRegistration,
    PlatformCapabilityRegistry,
)
from xhs_food.gateways.platform_gateway import AccountBoundSourceGateway, _connector_matches
from xhs_food.gateways.platform_sources import DianpingPlatformSourceConnector

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def _request() -> CollectRequest:
    query = CanonicalQuery.model_validate(
        json.loads(
            (ROOT / "tests" / "fixtures" / "authority" / "canonical_query_v1.json").read_text(
                encoding="utf-8"
            )
        )
    )
    return CollectRequest(query=query, source_scope=("dianping",), depth="standard")


class _Provider:
    calls = 0

    def search_places(self, **_: object) -> object:
        self.calls += 1
        return {"status": "success", "items": []}

    def fetch_place(self, **_: object) -> object:
        return {"status": "success", "item": {"shop_id": "shop-1", "name": "fixture"}}

    def fetch_reviews(self, **_: object) -> object:
        return {"status": "success", "items": []}

    def list_media(self, **_: object) -> object:
        return {"status": "success", "items": []}


async def _setup() -> tuple[InMemoryPlatformAccountAuthority, PlatformAccountRef, AesGcmSessionCodec]:
    ref = PlatformAccountRef(
        tenant_id="tenant-a", platform=PlatformChannel.DIANPING, account_ref="acct-1"
    )
    authority = InMemoryPlatformAccountAuthority(clock=lambda: NOW)
    await authority.register_account(
        tenant_id=ref.tenant_id,
        platform=ref.platform,
        account_ref=ref.account_ref,
        alias="primary",
        now=NOW,
    )
    await authority.add_grant(
        PlatformAccountGrant(
            grant_id="grant-1",
            account=ref,
            principal_id="operator",
            permissions=(AccountGrantPermission.USE,),
            issued_at=NOW,
        )
    )
    keys = InMemoryKeyProvider({("test", "v1"): b"x" * 32})
    codec = AesGcmSessionCodec(keys, key_ref="test", key_version="v1")
    envelope = await codec.seal(
        ref, b'{"cookies": [{"name": "sid", "value": "fixture"}]}',
        expires_at=NOW + timedelta(hours=1),
        version=1,
    )
    await authority.activate_session(
        SessionActivationRequest(
            account=ref,
            expected_session_version=0,
            envelope=envelope,
            expires_at=NOW + timedelta(hours=1),
            requested_at=NOW,
        )
    )
    return authority, ref, codec


@pytest.mark.asyncio
async def test_denied_grant_short_circuits_provider() -> None:
    authority, ref, codec = await _setup()
    provider = _Provider()
    gateway = AccountBoundSourceGateway(
        accounts=authority,
        codec=codec,
        connector_factories={PlatformChannel.DIANPING: lambda *_: DianpingPlatformSourceConnector(provider)},
    )
    invocation = PlatformSourceInvocation(
        request_id="req-denied",
        tenant_id=ref.tenant_id,
        platform=ref.platform,
        account_ref=ref.account_ref,
        operation="search",
        collect_request=_request(),
    )
    result = await gateway.collect(invocation, principal_id="other")
    assert result.error is not None and result.error.code == "PLATFORM_ACCOUNT_DENIED"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_authorized_same_query_uses_account_lease_and_releases() -> None:
    authority, ref, codec = await _setup()
    provider = _Provider()
    gateway = AccountBoundSourceGateway(
        accounts=authority,
        codec=codec,
        connector_factories={PlatformChannel.DIANPING: lambda *_: DianpingPlatformSourceConnector(provider)},
        clock=lambda: NOW,
    )
    invocation = PlatformSourceInvocation(
        request_id="req-ok",
        tenant_id=ref.tenant_id,
        platform=ref.platform,
        account_ref=ref.account_ref,
        operation="search",
        collect_request=_request(),
        expected_session_version=1,
    )
    result = await gateway.collect(invocation, principal_id="operator")
    assert result.outcome == "success_empty"
    assert provider.calls == 1
    # Release is observable by acquiring the same account again.
    lease = await authority.acquire(AccountLeaseRequest(account=ref, task_id="after", owner_id="operator"))
    assert lease.account == ref


def test_capability_registry_requires_explicit_collision_resolution() -> None:
    registry = PlatformCapabilityRegistry()
    registry.register(
        CapabilityRegistration(
            capability="place.lookup",
            version="dianping/v1",
            source_id="dianping",
            connector_version="dianping-platform/v1",
            provenance_ref="fixture/dianping",
        )
    )
    registry.register(
        CapabilityRegistration(
            capability="place.lookup",
            version="amap/v1",
            source_id="place_compat",
            connector_version="amap/v1",
            provenance_ref="legacy/amap",
        )
    )
    with pytest.raises(CapabilityCollisionError):
        registry.resolve("place.lookup")
    assert registry.resolve("place.lookup", source_id="dianping").source_id == "dianping"
    with pytest.raises(CapabilityCollisionError):
        registry.register(
            CapabilityRegistration(
                capability="place.lookup",
                version="dianping/v2",
                source_id="dianping",
                connector_version="dianping-platform/v2",
                provenance_ref="fixture/dianping-v2",
            )
        )


def test_connector_channel_is_required_for_shared_xhs_source_id() -> None:
    """A source-id-only connector must never cross PC/Creator namespaces."""

    class SourceOnlyConnector:
        source_id = "xhs"

    class WrongChannelConnector:
        source_id = "xhs"
        platform_channel = "xhs_creator"

    class DianpingLegacyConnector:
        source_id = "dianping"

    assert not _connector_matches(SourceOnlyConnector(), PlatformChannel.XHS_PC)  # type: ignore[arg-type]
    assert not _connector_matches(SourceOnlyConnector(), PlatformChannel.XHS_CREATOR)  # type: ignore[arg-type]
    assert not _connector_matches(WrongChannelConnector(), PlatformChannel.XHS_PC)  # type: ignore[arg-type]
    # The narrow fallback is retained only for pre-channel Dianping adapters.
    assert _connector_matches(DianpingLegacyConnector(), PlatformChannel.DIANPING)  # type: ignore[arg-type]
