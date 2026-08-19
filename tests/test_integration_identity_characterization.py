"""Characterize legacy HTTP identity precedence and browser device identity."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from fastapi.testclient import TestClient

from xhs_food.services.user_storage import User

ROOT = Path(__file__).resolve().parents[1]
ANONYMOUS_ID = "00000000-0000-0000-0000-000000000000"
EXPLICIT_USER_ID = "11111111-1111-1111-1111-111111111111"
RESTAURANT_ID = "restaurant-legacy-id"


class IdentityStorage:
    ANONYMOUS_USER_ID = ANONYMOUS_ID

    def __init__(self) -> None:
        self.users = {
            ANONYMOUS_ID: User(id=ANONYMOUS_ID, device_id="anonymous", name="Anonymous"),
            EXPLICIT_USER_ID: User(
                id=EXPLICIT_USER_ID, device_id="explicit-device", name="Explicit"
            ),
        }
        self.device_users: dict[str, str] = {}
        self.favorites: dict[str, set[str]] = {}
        self.device_lookups: list[str] = []
        self.favorite_reads: list[str] = []

    async def get_or_create_user(self, device_id: str) -> User:
        self.device_lookups.append(device_id)
        user_id = self.device_users.setdefault(
            device_id, str(uuid5(NAMESPACE_URL, f"characterization:{device_id}"))
        )
        self.users.setdefault(user_id, User(id=user_id, device_id=device_id, name="Guest"))
        return self.users[user_id]

    async def get_user(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    async def get_anonymous_user(self) -> User:
        return self.users[ANONYMOUS_ID]

    async def get_restaurant(self, restaurant_id: str) -> dict[str, str] | None:
        if restaurant_id == RESTAURANT_ID:
            return {"id": RESTAURANT_ID}
        return None

    async def get_favorites(self, user_id: str) -> list[Any]:
        self.favorite_reads.append(user_id)
        return []

    async def check_favorite(self, user_id: str, restaurant_id: str) -> bool:
        return restaurant_id in self.favorites.get(user_id, set())

    async def add_favorite(self, user_id: str, restaurant_id: str) -> None:
        self.favorites.setdefault(user_id, set()).add(restaurant_id)

    async def remove_favorite(self, user_id: str, restaurant_id: str) -> bool:
        self.favorites.setdefault(user_id, set()).discard(restaurant_id)
        return True


@dataclass
class IdentityHarness:
    client: TestClient
    storage: IdentityStorage


@pytest.fixture
def identity_api() -> Iterator[IdentityHarness]:
    from api.deps import get_storage
    from api.main import app

    previous_overrides = dict(app.dependency_overrides)
    storage = IdentityStorage()
    app.dependency_overrides[get_storage] = lambda: storage
    client = TestClient(app)
    try:
        yield IdentityHarness(client=client, storage=storage)
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def test_explicit_user_header_has_priority_over_device_header(
    identity_api: IdentityHarness,
) -> None:
    response = identity_api.client.get(
        "/v1/favorites",
        headers={"X-User-Id": EXPLICIT_USER_ID, "X-Device-Id": "ignored-device"},
    )

    assert response.status_code == 200
    assert identity_api.storage.favorite_reads == [EXPLICIT_USER_ID]
    assert identity_api.storage.device_lookups == []


def test_device_header_resolves_a_stable_device_scoped_user(
    identity_api: IdentityHarness,
) -> None:
    headers = {"X-Device-Id": "browser-device-a"}

    identity_api.client.get("/v1/favorites", headers=headers)
    identity_api.client.get("/v1/favorites", headers=headers)

    resolved_id = str(uuid5(NAMESPACE_URL, "characterization:browser-device-a"))
    assert identity_api.storage.favorite_reads == [resolved_id, resolved_id]
    assert identity_api.storage.device_lookups == ["browser-device-a", "browser-device-a"]


def test_missing_identity_headers_use_the_legacy_anonymous_user(
    identity_api: IdentityHarness,
) -> None:
    response = identity_api.client.get("/v1/favorites")

    assert response.status_code == 200
    assert identity_api.storage.favorite_reads == [ANONYMOUS_ID]
    assert identity_api.storage.device_lookups == []


def test_device_and_anonymous_favorites_are_isolated_by_resolved_user_id(
    identity_api: IdentityHarness,
) -> None:
    device_a = {"X-Device-Id": "device-a"}
    device_b = {"X-Device-Id": "device-b"}

    assert identity_api.client.post(
        "/v1/favorites", headers=device_a, json={"restaurantId": RESTAURANT_ID}
    ).json()["isFavorite"] is True

    assert identity_api.client.get(
        f"/v1/favorites/{RESTAURANT_ID}/check", headers=device_a
    ).json()["data"]["isFavorite"] is True
    assert identity_api.client.get(
        f"/v1/favorites/{RESTAURANT_ID}/check", headers=device_b
    ).json()["data"]["isFavorite"] is False
    assert identity_api.client.get(
        f"/v1/favorites/{RESTAURANT_ID}/check"
    ).json()["data"]["isFavorite"] is False

    identity_api.client.post("/v1/favorites", json={"restaurantId": RESTAURANT_ID})
    assert identity_api.client.get(
        f"/v1/favorites/{RESTAURANT_ID}/check"
    ).json()["data"]["isFavorite"] is True
    assert identity_api.client.get(
        f"/v1/favorites/{RESTAURANT_ID}/check", headers=device_b
    ).json()["data"]["isFavorite"] is False


def test_headerless_clients_currently_share_one_legacy_anonymous_identity(
    identity_api: IdentityHarness,
) -> None:
    first_client = identity_api.client
    second_client = TestClient(first_client.app)
    try:
        first_client.post("/v1/favorites", json={"restaurantId": RESTAURANT_ID})
        observed = second_client.get(f"/v1/favorites/{RESTAURANT_ID}/check")
    finally:
        second_client.close()

    assert observed.status_code == 200
    assert observed.json()["data"]["isFavorite"] is True


def test_browser_device_id_consumer_matches_the_frozen_fixture() -> None:
    fixture = json.loads(
        (ROOT / "tests/fixtures/frontend_device_identity_contract.json").read_text(
            encoding="utf-8"
        )
    )
    source = (ROOT / fixture["source"]).read_text(encoding="utf-8")
    function_body = re.search(
        r"const getDeviceId = \(\): string => \{(?P<body>.*?)\n\}", source, re.DOTALL
    )

    assert function_body is not None
    body = function_body.group("body")
    assert f"{fixture['storage']}.getItem('{fixture['storageKey']}')" in body
    assert f"id = {fixture['generator']}()" in body
    assert (
        f"{fixture['storage']}.setItem('{fixture['storageKey']}', id)" in body
    )
    assert re.search(
        rf"'{re.escape(fixture['requestHeader'])}'\s*:\s*{fixture['exportedFunction']}\(\)",
        source,
    )
    assert f"export {{ {fixture['exportedFunction']} }}" in source
