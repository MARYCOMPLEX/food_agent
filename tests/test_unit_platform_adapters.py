"""Unit tests for the lazy upstream provider bridges.

The tests use API-shaped fakes and never import either external checkout.  In
particular, Creator Studio's intentionally smaller read surface must not fall
through to PC-only methods or invoke publishing/upload code.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from xhs_food.composition.adapters import platforms as platform_adapters
from xhs_food.composition.adapters.platforms import (
    DianpingProviderFactory,
    ProviderUnavailableError,
    XhsProviderFactory,
    _XhsBridge,
)
from xhs_food.contracts import (
    CanonicalQuery,
    CollectRequest,
    ErrorCategory,
    PlatformChannel,
)
from xhs_food.gateways.platform_sources import (
    ProviderEnvelope,
    XhsCreatorSourceConnector,
    _media_items_from_attributes,
    _normalize_media_items,
)

ROOT = Path(__file__).resolve().parents[1]


def _request() -> CollectRequest:
    query = CanonicalQuery.model_validate(
        json.loads(
            (ROOT / "tests" / "fixtures" / "authority" / "canonical_query_v1.json").read_text(
                encoding="utf-8"
            )
        )
    )
    return CollectRequest(query=query, source_scope=("xhs",), depth="standard")

pytestmark = pytest.mark.unit


class _CreatorApi:
    def __init__(self) -> None:
        self.posted_calls: list[dict[str, object]] = []
        self.health_calls = 0
        self.upload_called = False

    def get_posted_notes_page(self, *, page: int = 0, tab: int = 0) -> object:
        self.posted_calls.append({"page": page, "tab": tab})
        return True, "ok", {"data": {"notes": [], "page": -1}}

    def get_user_info(self) -> object:
        self.health_calls += 1
        return True, "ok", {"success": True}

    def post_note(self, *_: object, **__: object) -> object:
        self.upload_called = True
        raise AssertionError("Creator publishing must not be invoked")


def _bridge(api: object, *, channel: str = "xhs_creator") -> _XhsBridge:
    return _XhsBridge(
        checkout=Path("."),
        channel=channel,
        account_ref="acct-1",
        api=api,
    )


def test_creator_bridge_maps_posted_notes_and_health_without_pc_calls() -> None:
    api = _CreatorApi()
    bridge = _bridge(api)

    result = bridge.search_notes(query="ignored", limit=5, cursor="3")
    assert result == (True, "ok", {"data": {"notes": [], "page": -1}})
    assert api.posted_calls == [{"page": 3, "tab": 0}]

    health = bridge.health_check()
    assert health == (True, "ok", {"success": True})
    assert api.health_calls == 1
    assert api.upload_called is False


@pytest.mark.parametrize(
    "operation",
    ("fetch_note", "fetch_comments", "list_media"),
)
def test_creator_bridge_returns_stable_unregistered_capability(operation: str) -> None:
    bridge = _bridge(_CreatorApi())
    result = getattr(bridge, operation)(
        external_id="note-1",
        **({"url": None} if operation in {"fetch_note", "list_media"} else {"cursor": None}),
    )
    assert isinstance(result, ProviderEnvelope)
    assert result.success is False
    assert result.code == "CAPABILITY_UNREGISTERED"


def test_creator_bridge_without_posted_endpoint_is_explicitly_unregistered() -> None:
    bridge = _bridge(object())
    result = bridge.search_notes(query="ignored", limit=1)
    assert isinstance(result, ProviderEnvelope)
    assert result.success is False
    assert result.code == "CAPABILITY_UNREGISTERED"
    assert bridge.health_check().code == "CAPABILITY_UNREGISTERED"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_creator_search_envelope_preserves_unregistered_policy_error() -> None:
    class MissingCreatorApi:
        pass

    connector = XhsCreatorSourceConnector(_bridge(MissingCreatorApi()))
    batch = await connector.search(_request())
    assert batch.errors[0].code == "CAPABILITY_UNREGISTERED"
    assert batch.errors[0].category is ErrorCategory.POLICY_DENIED
    assert batch.errors[0].retryable is False


def test_pc_bridge_propagates_detail_failure_when_listing_media() -> None:
    class FailingPcApi:
        def get_note_info(self, _url: str) -> object:
            return ProviderEnvelope(False, code="AUTH_EXPIRED", message="expired")

    result = _bridge(FailingPcApi(), channel="xhs_pc").list_media(
        external_id="note-1",
        url=None,
    )
    assert isinstance(result, ProviderEnvelope)
    assert result.success is False
    assert result.code == "AUTH_EXPIRED"


def test_pc_bridge_prefers_paginated_search_over_unbounded_convenience_method() -> None:
    class SearchApi:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def search_note(self, query: str, *, page: int = 1) -> object:
            self.calls.append(("search_note", (query, page)))
            return True, "ok", {"data": {"items": []}}

        def search_some_note(self, query: str, require_num: int) -> object:
            self.calls.append(("search_some_note", (query, require_num)))
            return True, "ok", {"data": {"items": []}}

    api = SearchApi()
    result = _bridge(api, channel="xhs_pc").search_notes(
        query="火锅", limit=7, cursor="4"
    )
    assert result == (True, "ok", {"data": {"items": []}})
    assert api.calls == [("search_note", ("火锅", 4))]


def test_xhs_video_stream_without_media_wrapper_is_normalized() -> None:
    attributes = {
        "note_card": {
            "video": {
                "stream": {
                    "h264": [
                        {
                            "master_url": "https://cdn.example.test/note.mp4?xsec_token=drop"
                        }
                    ]
                }
            }
        }
    }
    items = _media_items_from_attributes(attributes)
    refs = _normalize_media_items(
        source_id="xhs",
        owner_id="note-1",
        items=items,
        captured_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    assert len(refs) == 1
    assert refs[0].media_type.value == "video"
    assert str(refs[0].canonical_url) == "https://cdn.example.test/note.mp4"


def test_xhs_video_origin_key_is_resolved_to_stable_cdn_reference() -> None:
    items = _media_items_from_attributes(
        {"note_card": {"video": {"consumer": {"origin_video_key": "foo/bar.mp4"}}}}
    )
    refs = _normalize_media_items(
        source_id="xhs",
        owner_id="note-2",
        items=items,
        captured_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    assert len(refs) == 1
    assert str(refs[0].canonical_url) == "https://sns-video-bd.xhscdn.com/foo/bar.mp4"


def test_provider_module_namespace_is_pinned_to_one_checkout(tmp_path: Path) -> None:
    """A second checkout cannot silently reuse cached top-level modules."""

    package_name = f"food_agent_namespace_probe_{tmp_path.name.replace('-', '_')}"
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    for root, value in ((first_root, "first"), (second_root, "second")):
        package = root / package_name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "marker.py").write_text(
            f"VALUE = {value!r}\n",
            encoding="utf-8",
        )

    try:
        first = platform_adapters._import_from_checkout(
            first_root, f"{package_name}.marker"
        )
        assert first.VALUE == "first"
        # Reusing the pinned checkout is safe and returns the normal import
        # cache object.
        assert (
            platform_adapters._import_from_checkout(first_root, f"{package_name}.marker")
            is first
        )
        with pytest.raises(platform_adapters.ProviderUnavailableError, match="another checkout"):
            platform_adapters._import_from_checkout(second_root, f"{package_name}.marker")
    finally:
        prefix = package_name + "."
        for name in list(sys.modules):
            if name == package_name or name.startswith(prefix):
                sys.modules.pop(name, None)
        platform_adapters._CHECKOUT_IMPORT_ROOTS.pop(package_name, None)


@dataclass
class _DianpingSearchRequest:
    keyword: str
    city_id: int
    page: int


@dataclass
class _DianpingDetailRequest:
    shop_id: str
    detail_url: str | None = None


@dataclass
class _DianpingReviewRequest:
    shop_id: str
    page: int


def _dianping_modules(created: list[object]) -> dict[str, object]:
    class Protocol:
        def __init__(self, *, storage_state_path: Path, headless: bool) -> None:
            self.storage_state_path = Path(storage_state_path)
            self.headless = headless
            self.closed = False
            created.append(self)

        async def search(self, request: _DianpingSearchRequest) -> object:
            return {"shops": [{"shop_id": "shop-1", "name": request.keyword}]}

        async def fetch(self, request: object) -> object:
            return {"shop_id": getattr(request, "shop_id", "shop-1")}

        def close(self) -> None:
            self.closed = True

    return {
        "dz_engine.providers.dianping.search": SimpleNamespace(
            DianpingSearchProtocol=Protocol,
            DianpingSearchRequest=_DianpingSearchRequest,
        ),
        "dz_engine.providers.dianping.details": SimpleNamespace(
            DianpingPlaceDetailProtocol=Protocol,
            DianpingPlaceDetailRequest=_DianpingDetailRequest,
        ),
        "dz_engine.providers.dianping.reviews": SimpleNamespace(
            DianpingReviewProtocol=Protocol,
            DianpingReviewRequest=_DianpingReviewRequest,
        ),
    }


def test_dianping_injected_factory_scopes_state_and_closes_resources(tmp_path: Path) -> None:
    created: list[object] = []
    modules = _dianping_modules(created)
    factory = DianpingProviderFactory(
        tmp_path / "sidecar-owned-checkout",
        module_loader=modules.__getitem__,
    )
    account = SimpleNamespace(
        account_ref="same-alias",
        platform=PlatformChannel.DIANPING,
    )

    first = factory(
        account,
        object(),
        b'{"storage_state":{"cookies":[{"name":"sid","value":"one"}]}}',
    )
    first_paths = {Path(getattr(item, "storage_state_path")) for item in created}
    first_protocols = tuple(created)
    assert len(first_paths) == 1
    first_path = next(iter(first_paths))
    assert first_path.is_file()
    created.clear()
    second = factory(
        account,
        object(),
        b'{"storage_state":{"cookies":[{"name":"sid","value":"two"}]}}',
    )
    second_path = Path(getattr(created[0], "storage_state_path"))
    second_protocols = tuple(created)
    assert second_path != first_path
    assert second_path.read_text(encoding="utf-8") != first_path.read_text(encoding="utf-8")

    async def collect_concurrently() -> tuple[object, object]:
        first_result, second_result = await asyncio.gather(
            asyncio.to_thread(first.search_places, query="hotpot-one", city="1", cursor="2"),
            asyncio.to_thread(second.search_places, query="hotpot-two", city="1", cursor="2"),
        )
        return first_result, second_result

    first_result, second_result = asyncio.run(collect_concurrently())
    assert first_result == ProviderEnvelope(
        True,
        payload={"shops": [{"shop_id": "shop-1", "name": "hotpot-one"}]},
    )
    assert second_result == ProviderEnvelope(
        True,
        payload={"shops": [{"shop_id": "shop-1", "name": "hotpot-two"}]},
    )

    first.close()
    second.close()
    assert not first_path.exists()
    assert not second_path.exists()
    assert all(bool(getattr(item, "closed")) for item in first_protocols + second_protocols)


def test_dianping_factory_cleans_session_file_when_construction_fails(tmp_path: Path) -> None:
    captured: list[Path] = []

    class SearchProtocol:
        def __init__(self, *, storage_state_path: Path, headless: bool) -> None:
            del headless
            captured.append(Path(storage_state_path))

    class BrokenProtocol:
        def __init__(self, **_: Any) -> None:
            raise RuntimeError("cookie=provider-secret")

    modules = {
        "dz_engine.providers.dianping.search": SimpleNamespace(
            DianpingSearchProtocol=SearchProtocol,
            DianpingSearchRequest=_DianpingSearchRequest,
        ),
        "dz_engine.providers.dianping.details": SimpleNamespace(
            DianpingPlaceDetailProtocol=BrokenProtocol,
            DianpingPlaceDetailRequest=_DianpingDetailRequest,
        ),
        "dz_engine.providers.dianping.reviews": SimpleNamespace(
            DianpingReviewProtocol=BrokenProtocol,
            DianpingReviewRequest=_DianpingReviewRequest,
        ),
    }
    factory = DianpingProviderFactory(tmp_path, module_loader=modules.__getitem__)
    account = SimpleNamespace(
        account_ref="acct",
        platform=PlatformChannel.DIANPING,
    )
    with pytest.raises(ProviderUnavailableError) as captured_error:
        factory(account, object(), b'{"cookies":[]}')
    assert "provider-secret" not in str(captured_error.value)
    assert captured and not captured[0].exists()
    assert not captured[0].parent.exists()


def test_source_factories_reject_channel_mismatch_before_provider_import(tmp_path: Path) -> None:
    def unexpected_loader(_: str) -> object:
        raise AssertionError("provider import must not run for a mismatched channel")

    account = SimpleNamespace(
        account_ref="same-alias",
        platform=PlatformChannel.XHS_CREATOR,
    )
    with pytest.raises(ProviderUnavailableError, match="channel"):
        XhsProviderFactory(
            tmp_path,
            channel="xhs_pc",
            module_loader=unexpected_loader,
        )(account, object(), b'{"cookie":"opaque"}')
