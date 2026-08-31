"""Differential, isolation, cancellation, and lifecycle matrix for platform sources."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from xhs_food.contracts import (
    AccountGrantPermission,
    AccountLeaseRequest,
    CanonicalQuery,
    CanonicalSourceBatch,
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
from xhs_food.gateways.platform_gateway import AccountBoundSourceGateway
from xhs_food.gateways.platform_sources import (
    XhsCreatorSourceConnector,
    XhsPcSourceConnector,
)
from xhs_food.gateways.xhs import XHSSourceConnector

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def _request(source: str = "xhs", *, cursor: str | None = None) -> CollectRequest:
    query = CanonicalQuery.model_validate(
        json.loads(
            (ROOT / "tests" / "fixtures" / "authority" / "canonical_query_v1.json").read_text(
                encoding="utf-8"
            )
        )
    )
    return CollectRequest(
        query=query,
        source_scope=(source,),
        depth="standard",
        cursor=cursor,
    )


async def _authority(
    refs: tuple[PlatformAccountRef, ...],
    *,
    principal: str = "operator",
) -> tuple[InMemoryPlatformAccountAuthority, AesGcmSessionCodec]:
    authority = InMemoryPlatformAccountAuthority(clock=lambda: NOW)
    codec = AesGcmSessionCodec(
        InMemoryKeyProvider({("test", "v1"): b"m" * 32}),
        key_ref="test",
        key_version="v1",
    )
    expiry = NOW + timedelta(hours=1)
    for index, ref in enumerate(refs):
        await authority.register_account(
            tenant_id=ref.tenant_id,
            platform=ref.platform,
            account_ref=ref.account_ref,
            alias="shared-alias",
            now=NOW,
        )
        await authority.add_grant(
            PlatformAccountGrant(
                grant_id=f"grant-{index}",
                account=ref,
                principal_id=principal,
                permissions=(AccountGrantPermission.USE,),
                issued_at=NOW,
            )
        )
        material = json.dumps(
            {"cookie": f"{ref.platform.value}-credential-fixture"},
            separators=(",", ":"),
        ).encode()
        envelope = await codec.seal(ref, material, expires_at=expiry, version=1)
        await authority.activate_session(
            SessionActivationRequest(
                account=ref,
                expected_session_version=0,
                envelope=envelope,
                expires_at=expiry,
                requested_at=NOW,
            )
        )
    return authority, codec


def _invocation(
    ref: PlatformAccountRef,
    *,
    request_id: str,
    request: CollectRequest | None = None,
) -> PlatformSourceInvocation:
    source_id = "dianping" if ref.platform is PlatformChannel.DIANPING else "xhs"
    return PlatformSourceInvocation(
        request_id=request_id,
        tenant_id=ref.tenant_id,
        platform=ref.platform,
        account_ref=ref.account_ref,
        operation="search",
        collect_request=request or _request(source_id),
        expected_session_version=1,
    )


class _EmptyXhsProvider:
    def search_notes(self, **_: object) -> object:
        return True, "ok", {"data": {"items": [], "has_more": False}}

    def fetch_note(self, **_: object) -> object:
        return True, "ok", {"data": {}}

    def fetch_comments(self, **_: object) -> object:
        return True, "ok", {"data": {"comments": []}}

    def list_media(self, **_: object) -> object:
        return True, "ok", {"data": {"media": []}}


@pytest.mark.asyncio
async def test_concurrent_pc_creator_accounts_receive_only_their_session_material() -> None:
    refs = (
        PlatformAccountRef(
            tenant_id="tenant-a",
            platform=PlatformChannel.XHS_PC,
            account_ref="same-alias",
        ),
        PlatformAccountRef(
            tenant_id="tenant-a",
            platform=PlatformChannel.XHS_CREATOR,
            account_ref="same-alias",
        ),
    )
    authority, codec = await _authority(refs)
    observed: dict[str, bytes] = {}

    def factory(channel: PlatformChannel) -> Any:
        connector_type = (
            XhsPcSourceConnector
            if channel is PlatformChannel.XHS_PC
            else XhsCreatorSourceConnector
        )

        def build(account: object, _session: object, material: bytes) -> object:
            observed[channel.value] = bytes(material)
            assert getattr(account, "platform") is channel
            return connector_type(_EmptyXhsProvider(), account_ref="same-alias")

        return build

    gateway = AccountBoundSourceGateway(
        accounts=authority,
        codec=codec,
        connector_factories={channel: factory(channel) for channel in (PlatformChannel.XHS_PC, PlatformChannel.XHS_CREATOR)},
        clock=lambda: NOW,
    )
    outcomes = await asyncio.gather(
        *(
            gateway.collect(
                _invocation(ref, request_id=f"request-{ref.platform.value}"),
                principal_id="operator",
            )
            for ref in refs
        )
    )
    assert [item.outcome for item in outcomes] == ["success_empty", "success_empty"]
    assert json.loads(observed["xhs_pc"])["cookie"].startswith("xhs_pc-")
    assert json.loads(observed["xhs_creator"])["cookie"].startswith("xhs_creator-")
    assert observed["xhs_pc"] != observed["xhs_creator"]
    public = "".join(item.model_dump_json() for item in outcomes)
    assert "credential-fixture" not in public


@pytest.mark.asyncio
async def test_cross_tenant_and_unknown_principal_are_indistinguishable_and_short_circuit() -> None:
    owner_ref = PlatformAccountRef(
        tenant_id="tenant-a",
        platform=PlatformChannel.DIANPING,
        account_ref="private",
    )
    authority, codec = await _authority((owner_ref,))
    calls = 0

    def forbidden_factory(*_: object) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("authorization must precede provider construction")

    gateway = AccountBoundSourceGateway(
        accounts=authority,
        codec=codec,
        connector_factories={PlatformChannel.DIANPING: forbidden_factory},
    )
    wrong_tenant = owner_ref.model_copy(update={"tenant_id": "tenant-b"})
    cross_tenant, wrong_principal = await asyncio.gather(
        gateway.collect(
            _invocation(wrong_tenant, request_id="cross-tenant"),
            principal_id="operator",
        ),
        gateway.collect(
            _invocation(owner_ref, request_id="wrong-principal"),
            principal_id="other",
        ),
    )
    assert cross_tenant.error is not None
    assert wrong_principal.error is not None
    assert cross_tenant.error.model_dump(mode="json") == wrong_principal.error.model_dump(mode="json")
    assert cross_tenant.error.code == "PLATFORM_ACCOUNT_DENIED"
    assert calls == 0


@pytest.mark.asyncio
async def test_missing_dianping_session_stops_before_browser_factory() -> None:
    ref = PlatformAccountRef(
        tenant_id="tenant-a",
        platform=PlatformChannel.DIANPING,
        account_ref="missing-session",
    )
    authority = InMemoryPlatformAccountAuthority(clock=lambda: NOW)
    await authority.register_account(
        tenant_id=ref.tenant_id,
        platform=ref.platform,
        account_ref=ref.account_ref,
        alias="missing",
        now=NOW,
    )
    await authority.add_grant(
        PlatformAccountGrant(
            grant_id="grant-missing",
            account=ref,
            principal_id="operator",
            permissions=(AccountGrantPermission.USE,),
            issued_at=NOW,
        )
    )
    calls = 0

    def forbidden_factory(*_: object) -> object:
        nonlocal calls
        calls += 1
        raise AssertionError("Playwright must not launch without a session")

    gateway = AccountBoundSourceGateway(
        accounts=authority,
        codec=AesGcmSessionCodec(
            InMemoryKeyProvider({("test", "v1"): b"m" * 32}),
            key_ref="test",
            key_version="v1",
        ),
        connector_factories={PlatformChannel.DIANPING: forbidden_factory},
    )
    result = await gateway.collect(
        _invocation(ref, request_id="missing-session"),
        principal_id="operator",
    )
    assert result.error is not None
    assert result.error.code in {"PLATFORM_ACCOUNT_UNAVAILABLE", "PLATFORM_SESSION_REQUIRED"}
    assert calls == 0


class _LifecycleConnector:
    source_id = "dianping"
    platform_channel = "dianping"
    connector_version = "dianping-platform/v1"

    def __init__(self, behavior: str, entered: asyncio.Event | None = None) -> None:
        self.behavior = behavior
        self.entered = entered
        self.calls = 0
        self.closed = False
        self.seen_cursors: list[str | None] = []

    async def search(self, request: CollectRequest) -> CanonicalSourceBatch:
        self.calls += 1
        self.seen_cursors.append(request.cursor)
        if self.entered is not None:
            self.entered.set()
        if self.behavior == "wait":
            await asyncio.Event().wait()
        if self.behavior == "timeout":
            raise TimeoutError("authorization=Bearer credential-fixture-never-emit")
        return CanonicalSourceBatch(
            isolation=request.query.isolation,
            source_id="dianping",
            connector_id="fixture",
            connector_version=self.connector_version,
            normalizer_version="fixture/v1",
            next_cursor="cursor-2",
        )

    async def aclose(self) -> None:
        self.closed = True

    async def fetch_document(self, _ref: object) -> object:
        raise AssertionError("detail was not requested")

    async def fetch_comments(self, _ref: object, cursor: str | None = None) -> object:
        del cursor
        raise AssertionError("comments were not requested")

    async def list_media_refs(self, _ref: object) -> tuple[object, ...]:
        raise AssertionError("media was not requested")


@pytest.mark.asyncio
async def test_gateway_cancellation_closes_connector_and_releases_postgres_lease_contract() -> None:
    ref = PlatformAccountRef(
        tenant_id="tenant-a",
        platform=PlatformChannel.DIANPING,
        account_ref="cancel",
    )
    authority, codec = await _authority((ref,))
    entered = asyncio.Event()
    connector = _LifecycleConnector("wait", entered)
    gateway = AccountBoundSourceGateway(
        accounts=authority,
        codec=codec,
        connector_factories={PlatformChannel.DIANPING: lambda *_: connector},
        clock=lambda: NOW,
    )
    running = asyncio.create_task(
        gateway.collect(_invocation(ref, request_id="cancel"), principal_id="operator")
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert connector.closed is True
    lease = await authority.acquire(
        AccountLeaseRequest(
            account=ref,
            task_id="after-cancel",
            owner_id="operator",
            expected_session_version=1,
        )
    )
    assert lease.account == ref


@pytest.mark.asyncio
async def test_timeout_is_single_attempt_and_does_not_pollute_query_identity() -> None:
    ref = PlatformAccountRef(
        tenant_id="tenant-a",
        platform=PlatformChannel.DIANPING,
        account_ref="timeout",
    )
    authority, codec = await _authority((ref,))
    connector = _LifecycleConnector("timeout")
    request = _request("dianping", cursor="cursor-1")
    before = request.model_dump(mode="json")
    gateway = AccountBoundSourceGateway(
        accounts=authority,
        codec=codec,
        connector_factories={PlatformChannel.DIANPING: lambda *_: connector},
        clock=lambda: NOW,
    )
    result = await gateway.collect(
        _invocation(ref, request_id="timeout", request=request),
        principal_id="operator",
    )
    assert result.error is not None and result.error.code == "PLATFORM_SOURCE_TIMEOUT"
    assert "credential-fixture" not in result.model_dump_json()
    assert connector.calls == 1
    assert connector.seen_cursors == ["cursor-1"]
    assert connector.closed is True
    assert request.model_dump(mode="json") == before


class _LegacyTool:
    def __init__(self, name: str, data: dict[str, object]) -> None:
        self.name = name
        self._data = data

    async def execute(self, **_: object) -> object:
        return type("Result", (), {"success": True, "data": self._data})()


class _FixtureXhsProvider(_EmptyXhsProvider):
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def search_notes(self, **_: object) -> object:
        return True, "ok", self.payload


@pytest.mark.asyncio
async def test_legacy_and_new_xhs_emit_equivalent_public_document_identity() -> None:
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "platform_connectors" / "xhs_search.json").read_text(
            encoding="utf-8"
        )
    )
    items = fixture["data"]["items"]
    legacy = XHSSourceConnector(
        search_provider=_LegacyTool("xhs_search", {"notes": items}),
        note_provider=_LegacyTool("xhs_note", {"note": items[0]}),
        batch_provider=_LegacyTool("xhs_batch", {"notes": items}),
        clock=lambda: NOW,
    )
    modern = XhsPcSourceConnector(
        _FixtureXhsProvider({"data": fixture["data"]}),
        clock=lambda: NOW,
    )
    request = _request("xhs")
    legacy_batch, modern_batch = await asyncio.gather(
        legacy.search(request),
        modern.search(request),
    )
    legacy_doc = legacy_batch.documents[0]
    modern_doc = modern_batch.documents[0]
    assert (
        legacy_doc.source_id,
        legacy_doc.external_id,
        str(legacy_doc.canonical_url),
        legacy_doc.title,
        legacy_doc.text,
    ) == (
        modern_doc.source_id,
        modern_doc.external_id,
        str(modern_doc.canonical_url),
        modern_doc.title,
        modern_doc.text,
    )
    assert request.model_dump(mode="json") == _request("xhs").model_dump(mode="json")
