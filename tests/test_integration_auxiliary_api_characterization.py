"""Characterize the legacy non-search HTTP surface without external services."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from fastapi.testclient import TestClient

from xhs_food.services.user_storage import Favorite, SearchHistory, User

ANONYMOUS_ID = "00000000-0000-0000-0000-000000000000"
EXPLICIT_USER_ID = "11111111-1111-1111-1111-111111111111"
RESTAURANT_ID = "restaurant-legacy-id"


class MemoryUserStorage:
    """Small storage double that preserves the routes' user and delete semantics."""

    ANONYMOUS_USER_ID = ANONYMOUS_ID

    def __init__(self) -> None:
        self.users = {
            ANONYMOUS_ID: User(id=ANONYMOUS_ID, device_id="anonymous", name="Anonymous"),
            EXPLICIT_USER_ID: User(
                id=EXPLICIT_USER_ID,
                device_id="registered-device",
                name="Registered User",
                location="Chengdu",
            ),
        }
        self.device_users: dict[str, str] = {"registered-device": EXPLICIT_USER_ID}
        self.favorite_ids: dict[str, set[str]] = {}
        self.deleted_favorites: dict[str, set[str]] = {}
        self.histories: dict[str, list[SearchHistory]] = {}
        self.next_history_id = 1
        self.identity_calls: list[tuple[str, str | None]] = []

    async def get_or_create_user(self, device_id: str) -> User:
        self.identity_calls.append(("device", device_id))
        user_id = self.device_users.get(device_id)
        if user_id is None:
            user_id = str(uuid5(NAMESPACE_URL, f"device:{device_id}"))
            self.device_users[device_id] = user_id
            self.users[user_id] = User(id=user_id, device_id=device_id, name="Guest")
        return self.users[user_id]

    async def get_anonymous_user(self) -> User:
        self.identity_calls.append(("anonymous", None))
        return self.users[ANONYMOUS_ID]

    async def get_user(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    async def update_user(self, user_id: str, **changes: Any) -> User | None:
        user = self.users.get(user_id)
        if user is None:
            return None
        for name, value in changes.items():
            if value is not None:
                setattr(user, name, value)
        return user

    async def get_user_stats(self, user_id: str) -> dict[str, int]:
        return {
            "saved": len(self.favorite_ids.get(user_id, set())),
            "reviews": 0,
            "visited": len(self.histories.get(user_id, [])),
        }

    async def get_restaurant(self, restaurant_id: str) -> dict[str, str] | None:
        if restaurant_id != RESTAURANT_ID:
            return None
        return {"id": RESTAURANT_ID, "name": "Characterization Restaurant"}

    async def get_favorites(self, user_id: str) -> list[Favorite]:
        return [
            Favorite(
                id=index,
                user_id=user_id,
                restaurant_id=restaurant_id,
                restaurant={"id": restaurant_id, "name": "Characterization Restaurant"},
                created_at=datetime(2024, 1, index, tzinfo=UTC),
            )
            for index, restaurant_id in enumerate(
                sorted(self.favorite_ids.get(user_id, set())), start=1
            )
        ]

    async def add_favorite(self, user_id: str, restaurant_id: str) -> Favorite:
        self.deleted_favorites.setdefault(user_id, set()).discard(restaurant_id)
        self.favorite_ids.setdefault(user_id, set()).add(restaurant_id)
        return Favorite(id=1, user_id=user_id, restaurant_id=restaurant_id)

    async def remove_favorite(self, user_id: str, restaurant_id: str) -> bool:
        self.favorite_ids.setdefault(user_id, set()).discard(restaurant_id)
        self.deleted_favorites.setdefault(user_id, set()).add(restaurant_id)
        return True

    async def check_favorite(self, user_id: str, restaurant_id: str) -> bool:
        return restaurant_id in self.favorite_ids.get(user_id, set())

    async def add_history(
        self,
        user_id: str,
        query: str,
        results_count: int = 0,
        location: str | None = None,
        **_: Any,
    ) -> SearchHistory:
        item = SearchHistory(
            id=self.next_history_id,
            user_id=user_id,
            query=query,
            status="loading",
            results_count=results_count,
            location=location,
            created_at=datetime(2024, 1, self.next_history_id, tzinfo=UTC),
        )
        self.next_history_id += 1
        self.histories.setdefault(user_id, []).insert(0, item)
        return item

    async def get_history(
        self, user_id: str, limit: int = 20, offset: int = 0
    ) -> list[SearchHistory]:
        return self.histories.get(user_id, [])[offset : offset + limit]

    async def get_history_count(self, user_id: str) -> int:
        return len(self.histories.get(user_id, []))

    async def delete_history(self, user_id: str, history_id: int) -> bool:
        previous = self.histories.get(user_id, [])
        self.histories[user_id] = [item for item in previous if item.id != history_id]
        return len(previous) != len(self.histories[user_id])

    async def clear_history(self, user_id: str) -> int:
        count = len(self.histories.get(user_id, []))
        self.histories[user_id] = []
        return count


@dataclass
class ApiHarness:
    client: TestClient
    storage: MemoryUserStorage


@pytest.fixture
def auxiliary_api() -> Iterator[ApiHarness]:
    """Override only the storage dependency and skip the production lifespan."""
    from api.deps import get_storage
    from api.main import app

    previous_overrides = dict(app.dependency_overrides)
    storage = MemoryUserStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    client = TestClient(app)
    try:
        yield ApiHarness(client=client, storage=storage)
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def test_auxiliary_routes_and_methods_remain_registered() -> None:
    from api.main import app

    schema = app.openapi()
    expected_methods = {
        "/v1/favorites": {"get", "post"},
        "/v1/favorites/{restaurantId}": {"delete"},
        "/v1/favorites/{restaurantId}/check": {"get"},
        "/v1/history": {"get", "post", "delete"},
        "/v1/history/{historyId}": {"delete"},
        "/v1/user/profile": {"get", "put"},
        "/v1/user/stats/{type}": {"get"},
        "/v1/user/settings": {"get", "put"},
        "/v1/user/preferences": {"put"},
        "/v1/user/notifications": {"put"},
        "/v1/help/faqs": {"get"},
        "/v1/help/feedback": {"post"},
        "/health": {"get"},
        "/metrics": {"get"},
    }

    for path, methods in expected_methods.items():
        assert path in schema["paths"]
        assert methods <= set(schema["paths"][path])


def test_favorites_envelope_status_and_content_type(auxiliary_api: ApiHarness) -> None:
    response = auxiliary_api.client.get(
        "/v1/favorites", headers={"X-User-Id": EXPLICIT_USER_ID}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"success": True, "data": {"items": [], "total": 0}}


def test_favorite_soft_delete_hides_check_and_list_then_add_revives_it(
    auxiliary_api: ApiHarness,
) -> None:
    headers = {"X-User-Id": EXPLICIT_USER_ID}

    added = auxiliary_api.client.post(
        "/v1/favorites", headers=headers, json={"restaurantId": RESTAURANT_ID}
    )
    assert added.status_code == 200
    assert added.json() == {
        "success": True,
        "message": "已添加到收藏",
        "isFavorite": True,
    }

    removed = auxiliary_api.client.delete(f"/v1/favorites/{RESTAURANT_ID}", headers=headers)
    assert removed.status_code == 200
    assert removed.json() == {
        "success": True,
        "message": "已从收藏中移除",
        "isFavorite": False,
    }
    assert auxiliary_api.client.get(
        f"/v1/favorites/{RESTAURANT_ID}/check", headers=headers
    ).json() == {"success": True, "data": {"isFavorite": False}}
    assert auxiliary_api.client.get("/v1/favorites", headers=headers).json()["data"] == {
        "items": [],
        "total": 0,
    }
    assert RESTAURANT_ID in auxiliary_api.storage.deleted_favorites[EXPLICIT_USER_ID]

    revived = auxiliary_api.client.post(
        "/v1/favorites", headers=headers, json={"restaurantId": RESTAURANT_ID}
    )
    assert revived.json()["isFavorite"] is True
    assert auxiliary_api.client.get(
        f"/v1/favorites/{RESTAURANT_ID}/check", headers=headers
    ).json()["data"]["isFavorite"] is True


def test_missing_restaurant_is_a_200_business_failure(auxiliary_api: ApiHarness) -> None:
    response = auxiliary_api.client.post(
        "/v1/favorites",
        headers={"X-User-Id": EXPLICIT_USER_ID},
        json={"restaurantId": "missing"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "message": "餐厅不存在",
        "isFavorite": False,
    }


def test_history_uses_limit_offset_and_returns_its_pagination_envelope(
    auxiliary_api: ApiHarness,
) -> None:
    headers = {"X-User-Id": EXPLICIT_USER_ID}
    for number in range(3):
        created = auxiliary_api.client.post(
            "/v1/history",
            headers=headers,
            json={"query": f"query-{number}", "resultsCount": number, "location": "Chengdu"},
        )
        assert created.status_code == 200
        assert created.json()["success"] is True

    response = auxiliary_api.client.get("/v1/history?limit=1&offset=1", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] | {"items": None} == {
        "items": None,
        "total": 3,
        "limit": 1,
        "offset": 1,
    }
    assert [item["query"] for item in body["data"]["items"]] == ["query-1"]


def test_history_frontend_page_parameters_are_ignored_by_the_backend(
    auxiliary_api: ApiHarness,
) -> None:
    response = auxiliary_api.client.get(
        "/v1/history?page=4&pageSize=1", headers={"X-User-Id": EXPLICIT_USER_ID}
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"items": [], "total": 0, "limit": 20, "offset": 0}


@pytest.mark.parametrize(
    ("query", "expected_status"),
    [("limit=0", 422), ("limit=101", 422), ("offset=-1", 422)],
)
def test_history_pagination_bounds_are_validation_errors(
    auxiliary_api: ApiHarness, query: str, expected_status: int
) -> None:
    response = auxiliary_api.client.get(
        f"/v1/history?{query}", headers={"X-User-Id": EXPLICIT_USER_ID}
    )

    assert response.status_code == expected_status


def test_history_delete_and_clear_current_wire_semantics(auxiliary_api: ApiHarness) -> None:
    headers = {"X-User-Id": EXPLICIT_USER_ID}
    first = auxiliary_api.client.post(
        "/v1/history", headers=headers, json={"query": "first"}
    ).json()["data"]
    auxiliary_api.client.post("/v1/history", headers=headers, json={"query": "second"})

    invalid = auxiliary_api.client.delete("/v1/history/not-a-history-id", headers=headers)
    assert invalid.status_code == 200
    assert invalid.json() == {"success": False, "message": "无效的历史记录ID"}

    deleted = auxiliary_api.client.delete(f"/v1/history/{first['id']}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json() == {"success": True, "message": "已删除"}

    cleared = auxiliary_api.client.delete("/v1/history", headers=headers)
    assert cleared.status_code == 200
    assert cleared.json() == {"success": True, "message": "已清空 1 条历史记录"}


def test_user_profile_settings_and_invalid_stats_envelopes(auxiliary_api: ApiHarness) -> None:
    headers = {"X-User-Id": EXPLICIT_USER_ID}

    profile = auxiliary_api.client.get("/v1/user/profile", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["data"] | {"stats": None} == {
        "id": EXPLICIT_USER_ID,
        "deviceId": "registered-device",
        "name": "Registered User",
        "username": None,
        "email": None,
        "avatar": None,
        "location": "Chengdu",
        "settings": {},
        "memberSince": None,
        "stats": None,
    }
    assert profile.json()["data"]["stats"] == {"saved": 0, "reviews": 0, "visited": 0}

    updated = auxiliary_api.client.put(
        "/v1/user/profile", headers=headers, json={"name": "Updated", "email": "u@example.test"}
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "Updated"
    assert updated.json()["data"]["email"] == "u@example.test"

    settings = auxiliary_api.client.get("/v1/user/settings", headers=headers)
    assert settings.status_code == 200
    assert settings.json()["data"]["preferences"] == {
        "theme": "system",
        "language": "zh-CN",
        "accentColor": "default",
    }
    invalid_stats = auxiliary_api.client.get("/v1/user/stats/unknown", headers=headers)
    assert invalid_stats.status_code == 200
    assert invalid_stats.json()["success"] is False
    assert invalid_stats.json()["error"] == "invalid_type"


def test_help_health_and_metrics_wire_formats(auxiliary_api: ApiHarness) -> None:
    faqs = auxiliary_api.client.get("/v1/help/faqs")
    assert faqs.status_code == 200
    assert faqs.json()["success"] is True
    assert isinstance(faqs.json()["data"], list)
    assert len(faqs.json()["data"]) == 4

    feedback = auxiliary_api.client.post(
        "/v1/help/feedback", json={"type": "bug", "content": "characterized"}
    )
    assert feedback.status_code == 200
    assert feedback.json() == {"success": True, "message": "感谢您的反馈！我们会尽快处理。"}
    assert auxiliary_api.client.post("/v1/help/feedback", json={"type": "bug"}).status_code == 422

    health = auxiliary_api.client.get("/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": "xhs-food-agent",
        "version": "1.0.0",
    }

    metrics = auxiliary_api.client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain; version=1.0.0")
    assert "# HELP xhs_http_requests_total HTTP requests" in metrics.text
    assert "# TYPE xhs_http_requests_total counter" in metrics.text


class _Connection:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def execute(self, query: str, *_: Any) -> str:
        self.queries.append(query)
        return "UPDATE 1" if query.lstrip().startswith("UPDATE") else "DELETE 1"

    async def fetch(self, query: str, *_: Any) -> list[Any]:
        self.queries.append(query)
        return []

    async def fetchrow(self, query: str, *_: Any) -> None:
        self.queries.append(query)
        return None

    async def fetchval(self, query: str, *_: Any) -> bool:
        self.queries.append(query)
        return False


class _Acquire:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _Connection:
        return self.connection

    async def __aexit__(self, *_: Any) -> None:
        return None


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


@pytest.mark.asyncio
async def test_repository_favorite_delete_filter_and_revive_are_soft_delete_contract() -> None:
    from xhs_food.services.user_storage import UserStorageService

    storage = UserStorageService()
    connection = _Connection()
    storage._initialized = True  # noqa: SLF001 - characterize the legacy repository directly
    storage._pool = _Pool(connection)  # type: ignore[assignment]  # noqa: SLF001

    await storage.remove_favorite(EXPLICIT_USER_ID, RESTAURANT_ID)
    await storage.get_favorites(EXPLICIT_USER_ID)
    await storage.check_favorite(EXPLICIT_USER_ID, RESTAURANT_ID)
    await storage.add_favorite(EXPLICIT_USER_ID, RESTAURANT_ID)

    normalized = [" ".join(query.split()) for query in connection.queries]
    assert any(
        "UPDATE favorites SET deleted_at = NOW()" in query
        and "deleted_at IS NULL" in query
        for query in normalized
    )
    assert sum("deleted_at IS NULL" in query for query in normalized) >= 3
    assert any("deleted_at = NULL, created_at = NOW()" in query for query in normalized)


@pytest.mark.asyncio
async def test_repository_history_delete_is_currently_physical_not_soft() -> None:
    from xhs_food.services.user_storage import UserStorageService

    storage = UserStorageService()
    connection = _Connection()
    storage._initialized = True  # noqa: SLF001 - characterize the legacy repository directly
    storage._pool = _Pool(connection)  # type: ignore[assignment]  # noqa: SLF001

    await storage.delete_history(EXPLICIT_USER_ID, 7)
    await storage.clear_history(EXPLICIT_USER_ID)

    normalized = [" ".join(query.split()) for query in connection.queries]
    assert normalized == [
        "DELETE FROM search_history WHERE user_id = $1 AND id = $2",
        "DELETE FROM search_history WHERE user_id = $1",
    ]
