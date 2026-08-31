"""Unit contracts for the injected Dianping and Spider_XHS adapters.

The tests use tiny provider fakes rather than importing either upstream
checkout.  They exercise the boundary that a composition root/sidecar must
implement: result-envelope coercion, canonical mapping, account-local
serialization, and secret-safe diagnostics.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from xhs_food.contracts import (
    CanonicalQuery,
    CollectRequest,
    ErrorCategory,
    ErrorScope,
    SourceLocator,
)
from xhs_food.gateways.platform_sources import (
    DianpingPlatformSourceConnector,
    PlatformSourceAdapterError,
    ProviderEnvelope,
    XhsCreatorSourceConnector,
    XhsPlatformSourceConnector,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def _request(source_id: str, *, cursor: str | None = None) -> CollectRequest:
    query = CanonicalQuery.model_validate(
        json.loads(
            (ROOT / "tests" / "fixtures" / "authority" / "canonical_query_v1.json").read_text(
                encoding="utf-8"
            )
        )
    )
    return CollectRequest(
        query=query,
        source_scope=(source_id,),
        depth="standard",
        cursor=cursor,
    )


def _locator(source_id: str, external_id: str = "item-1") -> SourceLocator:
    return SourceLocator.model_validate(
        {
            "locator_id": f"{source_id}.item",
            "source_id": source_id,
            "connector_id": f"{source_id}.platform",
            "connector_version": f"{source_id}-platform/v1",
            "external_id": external_id,
            "canonical_url": (
                "https://www.xiaohongshu.com/explore/item-1"
                if source_id == "xhs"
                else "https://www.dianping.com/shop/item-1"
            ),
            "captured_at": NOW,
            "source_updated_at": None,
            "watermark": None,
            "visibility": {
                "scope": "public",
                "tenant_scope": "public",
                "entitlement_ids": [],
            },
            "license": {
                "license_id": "fixture-license",
                "status": "known",
                "allowed_use": "internal_reuse",
                "attribution_required": False,
                "expires_at": None,
                "policy_version": "fixture-license/v1",
            },
            "retention": {
                "retention_class": "fixture",
                "duration_seconds": None,
                "legal_hold": False,
            },
        }
    )


class _XhsProvider:
    def __init__(self, search_result: object | None = None) -> None:
        self.search_result = search_result
        self.calls: list[tuple[str, dict[str, object]]] = []

    def search_notes(self, **kwargs: object) -> object:
        self.calls.append(("search_notes", kwargs))
        if self.search_result is not None:
            return self.search_result
        return {
            "success": True,
            "data": {
                "items": [
                    {
                        "note_id": "note-1",
                        "title": "火锅探店",
                        "desc": "一份公开笔记",
                        "url": "https://WWW.XIAOHONGSHU.COM/explore/note-1?xsec_token=secret",
                        "user": {
                            "user_id": "user-1",
                            "nickname": "示例作者",
                            "home_url": "https://www.xiaohongshu.com/user/profile/user-1",
                        },
                        "xsec_token": "secret-token",
                        "account_ref": "tenant-a-xhs",
                    },
                    {"note_id": "note-1", "title": "duplicate"},
                    {"title": "missing id"},
                ],
                "next_cursor": "opaque-page-2",
            },
        }

    def fetch_note(self, **kwargs: object) -> object:
        self.calls.append(("fetch_note", kwargs))
        return (
            True,
            "ok",
            {
                "note_id": kwargs.get("external_id", "note-1"),
                "title": "火锅详情",
                "url": "https://www.xiaohongshu.com/explore/note-1?xsec_token=secret",
                "user_id": "user-1",
            },
        )

    def fetch_comments(self, **kwargs: object) -> object:
        self.calls.append(("fetch_comments", kwargs))
        return {
            "ok": True,
            "data": {
                "items": [
                    {"comment_id": "comment-1", "user_id": "user-2", "text": "好吃"},
                    {"comment_id": "comment-1", "text": "duplicate"},
                    {"text": "missing id"},
                ],
                "has_more": True,
                "next_cursor": "comment-page-2",
            },
        }

    def list_media(self, **kwargs: object) -> object:
        self.calls.append(("list_media", kwargs))
        return {
            "success": True,
            "data": {
                "items": [
                    {
                        "media_id": "media-1",
                        "url": "https://img.example.test/a.jpg?xsec_token=secret",
                    },
                    {"id": "media-2", "url": "https://img.example.test/a.jpg"},
                    {"id": "media-3", "url": "file:///tmp/private.jpg"},
                ]
            },
        }


class _DianpingProvider:
    def search_places(self, **kwargs: object) -> object:
        return {
            "status": "success",
            "items": [
                {
                    "shop_id": "shop-1",
                    "name": "示例餐厅",
                    "address": "示例路 1 号",
                    "url": "https://www.dianping.com/shop/shop-1?token=secret",
                }
            ],
            "pagination": {"has_next": True, "next_page": 2},
        }

    def fetch_place(self, **kwargs: object) -> object:
        return {
            "status": "success",
            "shop": {
                "shop_id": kwargs.get("external_id", "shop-1"),
                "name": "示例餐厅",
                "url": "https://www.dianping.com/shop/shop-1",
            },
        }

    def fetch_reviews(self, **kwargs: object) -> object:
        return {
            "status": "success",
            "items": [
                {"review_id": "review-1", "text": "味道很好"},
                {"review_id": "review-1", "text": "duplicate"},
            ],
            "pagination": {"has_next": False, "next_start_index": 10},
        }

    def list_media(self, **kwargs: object) -> object:
        return (True, "ok", [{"media_id": "photo-1", "url": "https://img.example.test/p.jpg"}])


async def test_xhs_search_normalizes_tuple_like_payload_and_isolates_bad_items() -> None:
    provider = _XhsProvider()
    connector = XhsPlatformSourceConnector(provider, account_ref="tenant-a-xhs", clock=lambda: NOW)

    batch = await connector.search(_request("xhs"))

    assert [document.external_id for document in batch.documents] == ["note-1"]
    assert [author.external_id for author in batch.authors] == ["user-1"]
    assert batch.next_cursor == "opaque-page-2"
    assert batch.watermark is None
    assert len(batch.errors) == 1
    assert batch.errors[0].code == "XHS_ITEM_ID_MISSING"
    assert batch.errors[0].scope is ErrorScope.SOURCE
    assert batch.coverage is not None
    assert batch.coverage.attempts[0].outcome.value == "partial"
    public_dump = batch.model_dump_json()
    assert "xsec_token" not in public_dump
    assert "secret-token" not in public_dump
    assert "account_ref" not in public_dump
    assert batch.documents[0].attributes["url"] == (
        "https://www.xiaohongshu.com/explore/note-1"
    )
    assert connector.account_ref == "tenant-a-xhs"


async def test_xhs_comments_and_media_use_stable_ids_and_urls() -> None:
    connector = XhsPlatformSourceConnector(_XhsProvider(), clock=lambda: NOW)
    ref = _locator("xhs", "note-1")

    comments = await connector.fetch_comments(ref)
    media = await connector.list_media_refs(ref)

    assert [comment.external_id for comment in comments.comments] == ["comment-1"]
    assert comments.next_cursor == "comment-page-2"
    assert comments.errors[0].code == "XHS_COMMENT_ID_MISSING"
    assert [item.external_id for item in media] == ["media-1"]
    assert str(media[0].canonical_url) == "https://img.example.test/a.jpg"


async def test_dianping_maps_status_payload_and_pagination() -> None:
    connector = DianpingPlatformSourceConnector(_DianpingProvider(), clock=lambda: NOW)

    batch = await connector.search(_request("dianping"))
    detail = await connector.fetch_document(_locator("dianping", "shop-1"))
    reviews = await connector.fetch_comments(_locator("dianping", "shop-1"))

    assert [item.external_id for item in batch.documents] == ["shop-1"]
    assert batch.next_cursor == "2"
    assert str(batch.documents[0].canonical_url) == "https://www.dianping.com/shop/shop-1"
    assert detail.external_id == "shop-1"
    assert [item.external_id for item in reviews.comments] == ["review-1"]
    assert reviews.next_cursor is None


async def test_dianping_accepts_list_payload_and_classifies_403_challenge() -> None:
    class ListProvider(_DianpingProvider):
        def search_places(self, **_: object) -> object:
            return {
                "success": True,
                "data": {
                    "list": [
                        {
                            "shop_id": "shop-list-1",
                            "name": "列表餐厅",
                            "url": "https://user:password@www.dianping.com/shop/shop-list-1?foo=bar",
                        }
                    ]
                },
            }

    connector = DianpingPlatformSourceConnector(ListProvider(), clock=lambda: NOW)
    batch = await connector.search(_request("dianping"))
    assert [item.external_id for item in batch.documents] == ["shop-list-1"]
    assert str(batch.documents[0].canonical_url) == (
        "https://www.dianping.com/shop/shop-list-1"
    )
    assert "password" not in batch.model_dump_json()

    class ChallengeProvider(_DianpingProvider):
        def search_places(self, **_: object) -> object:
            return {
                "success": False,
                "status_code": 403,
                "code": "VERIFICATION_REQUIRED",
                "message": "human verification required",
            }

    challenge = await DianpingPlatformSourceConnector(
        ChallengeProvider(), clock=lambda: NOW
    ).search(_request("dianping"))
    assert challenge.errors[0].code == "SOURCE_CHALLENGE_REQUIRED"
    assert challenge.errors[0].category is ErrorCategory.RATE_LIMITED
    assert challenge.errors[0].retryable is True

    class StatusOnlyProvider(_DianpingProvider):
        def search_places(self, **_: object) -> object:
            return {"status_code": 403, "message": "verification required"}

    status_only = await DianpingPlatformSourceConnector(
        StatusOnlyProvider(), clock=lambda: NOW
    ).search(_request("dianping"))
    assert status_only.errors[0].code == "SOURCE_CHALLENGE_REQUIRED"


@pytest.mark.parametrize(
    ("envelope", "category", "code"),
    [
        (ProviderEnvelope(False, message="cookie=secret", code="AUTH_EXPIRED", status_code=401), ErrorCategory.POLICY_DENIED, "AUTH_EXPIRED"),
        (ProviderEnvelope(False, message="risk control", code="RISK_CONTROL", status_code=406), ErrorCategory.RATE_LIMITED, "SOURCE_CHALLENGE_REQUIRED"),
        (ProviderEnvelope(False, message="upstream", code="HTTP_503", status_code=503), ErrorCategory.DEPENDENCY_UNAVAILABLE, "SOURCE_DEPENDENCY_UNAVAILABLE"),
    ],
)
async def test_provider_failures_are_classified_before_payload_normalization(
    envelope: ProviderEnvelope, category: ErrorCategory, code: str
) -> None:
    provider = _XhsProvider(search_result=envelope)
    connector = XhsPlatformSourceConnector(provider, clock=lambda: NOW)

    batch = await connector.search(_request("xhs"))

    assert not batch.documents
    assert batch.errors[0].category is category
    assert batch.errors[0].code == code
    assert batch.errors[0].scope is ErrorScope.PROVIDER
    assert "secret" not in batch.errors[0].model_dump_json()


@pytest.mark.parametrize("payload", [[], (), [{"note_id": "direct-note"}]])
async def test_direct_collection_payloads_are_not_treated_as_malformed_envelopes(
    payload: object,
) -> None:
    class DirectProvider(_XhsProvider):
        def search_notes(self, **_: object) -> object:
            return payload

    batch = await XhsPlatformSourceConnector(
        DirectProvider(), clock=lambda: NOW
    ).search(_request("xhs"))
    if payload and isinstance(payload, (list, tuple)):
        assert [item.external_id for item in batch.documents] == ["direct-note"]
    else:
        assert batch.documents == ()
        assert batch.errors == ()


async def test_single_mapping_collection_payload_is_normalized() -> None:
    class SingleMappingProvider(_XhsProvider):
        def search_notes(self, **_: object) -> object:
            return {"success": True, "data": {"items": {"note_id": "single-note"}}}

    batch = await XhsPlatformSourceConnector(
        SingleMappingProvider(), clock=lambda: NOW
    ).search(_request("xhs"))
    assert [item.external_id for item in batch.documents] == ["single-note"]


async def test_non_boolean_tuple_envelope_is_classified_as_malformed() -> None:
    class MalformedProvider(_XhsProvider):
        def search_notes(self, **_: object) -> object:
            return ("not-a-bool", "message", {"items": []})

    batch = await XhsPlatformSourceConnector(
        MalformedProvider(), clock=lambda: NOW
    ).search(_request("xhs"))
    assert batch.errors[0].code == "PROVIDER_RESULT_ENVELOPE_MALFORMED"
    assert batch.errors[0].category is ErrorCategory.MALFORMED_RESPONSE


async def test_missing_provider_capability_is_a_scoped_dependency_error() -> None:
    class SearchOnlyProvider:
        def search_notes(self, **_: object) -> object:
            return {"success": True, "data": {"items": []}}

    connector = XhsPlatformSourceConnector(SearchOnlyProvider(), clock=lambda: NOW)
    batch = await connector.fetch_comments(_locator("xhs", "note-1"))
    assert batch.errors[0].code == "PROVIDER_CAPABILITY_UNAVAILABLE"
    assert batch.errors[0].scope is ErrorScope.PROVIDER
    assert batch.errors[0].retryable is True


@pytest.mark.parametrize(
    ("message", "expected_code", "expected_category"),
    [
        ("HTTP 403 forbidden", "AUTH_EXPIRED", ErrorCategory.POLICY_DENIED),
        ("HTTP 403 verification challenge", "SOURCE_CHALLENGE_REQUIRED", ErrorCategory.RATE_LIMITED),
        ("HTTP 429 too many requests", "SOURCE_RATE_LIMITED", ErrorCategory.RATE_LIMITED),
    ],
)
async def test_provider_exception_http_markers_map_to_stable_errors(
    message: str, expected_code: str, expected_category: ErrorCategory
) -> None:
    class FailingProvider(_XhsProvider):
        def search_notes(self, **_: object) -> object:
            raise RuntimeError(message)

    batch = await XhsPlatformSourceConnector(
        FailingProvider(), clock=lambda: NOW
    ).search(_request("xhs"))
    assert batch.errors[0].code == expected_code
    assert batch.errors[0].category is expected_category


async def test_fetch_failure_raises_redacted_adapter_error_and_wrong_source_is_rejected() -> None:
    class Provider(_XhsProvider):
        def fetch_note(self, **_: object) -> object:
            raise RuntimeError("authorization: Bearer very-secret-token")

    connector = XhsPlatformSourceConnector(Provider(), clock=lambda: NOW)
    with pytest.raises(PlatformSourceAdapterError) as caught:
        await connector.fetch_document(_locator("xhs", "note-1"))
    assert caught.value.error.code == "PROVIDER_INTERNAL"
    assert "very-secret-token" not in caught.value.error.model_dump_json()
    assert caught.value.error.scope is ErrorScope.PROVIDER

    with pytest.raises(ValueError, match="does not belong"):
        await connector.fetch_document(_locator("dianping", "shop-1"))


@pytest.mark.parametrize(
    ("connector_type", "source_id", "error_code", "status_code"),
    [
        (XhsPlatformSourceConnector, "xhs", "AUTH_EXPIRED", 401),
        (DianpingPlatformSourceConnector, "dianping", "SOURCE_CHALLENGE_REQUIRED", 406),
    ],
)
async def test_media_provider_failures_are_not_collapsed_to_empty_success(
    connector_type: type[object],
    source_id: str,
    error_code: str,
    status_code: int,
) -> None:
    """Media failures must reach the account gateway as typed errors."""

    class FailingMediaProvider:
        def list_media(self, **_: object) -> object:
            return ProviderEnvelope(
                False,
                message="cookie=secret; verification required",
                code=error_code,
                status_code=status_code,
            )

    connector = connector_type(FailingMediaProvider(), clock=lambda: NOW)  # type: ignore[call-arg]
    with pytest.raises(PlatformSourceAdapterError) as caught:
        await connector.list_media_refs(_locator(source_id, "owner-1"))  # type: ignore[attr-defined]
    assert caught.value.error.code == error_code
    assert caught.value.error.scope is ErrorScope.PROVIDER
    assert "secret" not in caught.value.error.model_dump_json()


async def test_malformed_media_response_propagates_detail_fallback_failure() -> None:
    class MalformedMediaProvider(_XhsProvider):
        def list_media(self, **_: object) -> object:
            return {"success": True, "data": {"unexpected": "shape"}}

        def fetch_note(self, **_: object) -> object:
            return ProviderEnvelope(
                False,
                message="upstream media detail unavailable",
                code="HTTP_503",
                status_code=503,
            )

    connector = XhsPlatformSourceConnector(MalformedMediaProvider(), clock=lambda: NOW)
    with pytest.raises(PlatformSourceAdapterError) as caught:
        await connector.list_media_refs(_locator("xhs", "owner-1"))
    assert caught.value.error.code == "SOURCE_DEPENDENCY_UNAVAILABLE"
    assert caught.value.error.category is ErrorCategory.DEPENDENCY_UNAVAILABLE
    assert caught.value.error.scope is ErrorScope.PROVIDER


async def test_each_connector_serializes_mutable_provider_calls() -> None:
    class SlowProvider(_XhsProvider):
        active = 0
        maximum = 0

        def search_notes(self, **kwargs: object) -> object:
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            time.sleep(0.02)
            self.active -= 1
            return {"success": True, "data": {"items": []}}

    provider = SlowProvider()
    connector = XhsPlatformSourceConnector(provider, account_ref="one", clock=lambda: NOW)
    await asyncio.gather(connector.search(_request("xhs")), connector.search(_request("xhs")))
    assert provider.maximum == 1

    # Separate instances represent separate account/channel namespaces and do
    # not share the lock or mutable provider object.
    pc = XhsPlatformSourceConnector(SlowProvider(), account_ref="same-alias", clock=lambda: NOW)
    creator = XhsCreatorSourceConnector(SlowProvider(), account_ref="same-alias", clock=lambda: NOW)
    assert pc.platform_channel == "xhs_pc"
    assert creator.platform_channel == "xhs_creator"
    assert pc.account_ref == creator.account_ref
    assert pc._provider is not creator._provider  # noqa: SLF001 - isolation assertion


async def test_publish_is_explicitly_unregistered() -> None:
    connector = XhsCreatorSourceConnector(_XhsProvider(), clock=lambda: NOW)
    with pytest.raises(PlatformSourceAdapterError) as caught:
        await connector.publish(note={"title": "not invoked"})
    assert caught.value.error.code == "CAPABILITY_UNREGISTERED"
    assert caught.value.error.category is ErrorCategory.POLICY_DENIED


async def test_xhs_nested_spider_payload_and_comment_media_are_canonicalized() -> None:
    class NestedProvider(_XhsProvider):
        def search_notes(self, **_: object) -> object:
            return (
                True,
                "ok",
                {
                    "data": {
                        "items": [
                            {
                                "id": "nested-note-1",
                                "url": "https://www.xiaohongshu.com/explore/nested-note-1?xsec_token=drop",
                                "note_card": {
                                    "title": "嵌套标题",
                                    "desc": "嵌套正文",
                                    "time": 1_756_600_000_000,
                                    "user": {
                                        "user_id": "nested-user-1",
                                        "nickname": "嵌套作者",
                                    },
                                    "image_list": [
                                        {
                                            "info_list": [
                                                {"url": "https://img.example.test/low.jpg"},
                                                {"url": "https://img.example.test/high.jpg?xsec_token=drop"},
                                            ]
                                        }
                                    ],
                                },
                            }
                        ],
                        "has_more": False,
                    }
                },
            )

        def fetch_note(self, **_: object) -> object:
            return {
                "success": True,
                "data": {
                    "items": [
                        {
                            "id": "nested-note-1",
                            "note_card": {
                                "title": "嵌套详情",
                                "desc": "详情正文",
                                "user": {"user_id": "nested-user-1"},
                            },
                        }
                    ]
                },
            }

        def fetch_comments(self, **_: object) -> object:
            return {
                "success": True,
                "data": {
                    "comments": [
                        {
                            "id": "nested-comment-1",
                            "content": "嵌套评论",
                            "create_time": 1_756_600_000_000,
                            "user_info": {
                                "user_id": "nested-user-2",
                                "nickname": "评论作者",
                            },
                            "pictures": [
                                {
                                    "media_id": "nested-comment-media-1",
                                    "info_list": [
                                        {"url": "https://img.example.test/comment.jpg?token=drop"}
                                    ],
                                }
                            ],
                        }
                    ],
                    "has_more": False,
                },
            }

        def list_media(self, **_: object) -> object:
            return {
                "success": True,
                "data": {
                    "note_card": {
                        "image_list": [
                            {
                                "media_id": "nested-note-media-1",
                                "info_list": [
                                    {"url": "https://img.example.test/low.jpg"},
                                    {"url": "https://img.example.test/high.jpg?xsec_token=drop"},
                                ],
                            }
                        ]
                    }
                },
            }

    connector = XhsPlatformSourceConnector(NestedProvider(), clock=lambda: NOW)
    search = await connector.search(_request("xhs"))
    assert [doc.external_id for doc in search.documents] == ["nested-note-1"]
    assert search.documents[0].title == "嵌套标题"
    assert search.documents[0].author_external_id == "nested-user-1"
    assert [author.external_id for author in search.authors] == ["nested-user-1"]
    assert search.next_cursor is None

    detail = await connector.fetch_document(_locator("xhs", "nested-note-1"))
    assert detail.title == "嵌套详情"
    note_media = await connector.list_media_refs(_locator("xhs", "nested-note-1"))
    assert [media.external_id for media in note_media] == ["nested-note-media-1"]
    assert str(note_media[0].canonical_url) == "https://img.example.test/high.jpg"

    comments = await connector.fetch_comments(_locator("xhs", "nested-note-1"))
    assert [comment.external_id for comment in comments.comments] == ["nested-comment-1"]
    assert comments.comments[0].author_external_id == "nested-user-2"
    assert [media.external_id for media in comments.media_refs] == [
        "nested-comment-media-1"
    ]
    assert comments.media_refs[0].owner_type == "comment"
    assert str(comments.media_refs[0].canonical_url) == "https://img.example.test/comment.jpg"
    serialized = comments.model_dump_json()
    assert "token=drop" not in serialized


async def test_dianping_review_media_are_returned_as_separate_refs() -> None:
    class ReviewMediaProvider(_DianpingProvider):
        def fetch_reviews(self, **_: object) -> object:
            return {
                "status": "success",
                "items": [
                    {
                        "review_id": "review-with-media",
                        "user_name": "用户",
                        "text": "有图评价",
                        "images": [
                            {
                                "media_id": "review-photo-1",
                                "url": "https://img.example.test/review.jpg?sig=secret",
                            }
                        ],
                    }
                ],
            }

    connector = DianpingPlatformSourceConnector(ReviewMediaProvider(), clock=lambda: NOW)
    batch = await connector.fetch_comments(_locator("dianping", "shop-1"))
    assert [comment.external_id for comment in batch.comments] == ["review-with-media"]
    assert [media.external_id for media in batch.media_refs] == ["review-photo-1"]
    assert batch.media_refs[0].owner_external_id == "review-with-media"
    assert batch.media_refs[0].owner_type == "comment"
    assert str(batch.media_refs[0].canonical_url) == "https://img.example.test/review.jpg"
    assert "sig=secret" not in batch.model_dump_json()
