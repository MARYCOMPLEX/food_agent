"""Contract tests for the account/login HTTP control plane."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.deps import get_current_user_id
from api.platform import router
from xhs_food.contracts import (
    LoginFlowState,
    PlatformAccount,
    PlatformChannel,
    PlatformLoginFlow,
)
from xhs_food.experience.platform_login import LoginSubmission, QrPresentation

NOW = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)


def _account() -> PlatformAccount:
    return PlatformAccount(
        tenant_id="tenant-1",
        platform=PlatformChannel.XHS_PC,
        account_ref="primary",
        alias="primary account",
        created_at=NOW,
        updated_at=NOW,
    )


def _flow(state: LoginFlowState = LoginFlowState.WAITING_SCAN) -> PlatformLoginFlow:
    return PlatformLoginFlow(
        flow_id="flow-test",
        account=_account().ref,
        state=state,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        updated_at=NOW,
        qr_expires_at=NOW + timedelta(minutes=2)
        if state in {LoginFlowState.QR_READY, LoginFlowState.WAITING_SCAN}
        else None,
    )


class FakeLoginService:
    async def register_account(self, **_: Any) -> PlatformAccount:
        return _account()

    async def get_account(self, **_: Any) -> PlatformAccount:
        return _account()

    async def start_login(self, **_: Any) -> LoginSubmission:
        return LoginSubmission(flow=_flow())

    async def poll(self, **_: Any) -> LoginSubmission:
        return LoginSubmission(flow=_flow())

    async def status(self, **_: Any) -> PlatformLoginFlow:
        return _flow()

    async def cancel(self, **_: Any) -> LoginSubmission:
        return LoginSubmission(flow=_flow(LoginFlowState.CANCELLED))

    async def get_qr(self, **_: Any) -> QrPresentation:
        return QrPresentation(
            flow_id="flow-test",
            presentation_ref="qr-present:opaque",
            expires_at=NOW + timedelta(minutes=2),
            content_type="image/png",
        )

    async def readiness(self) -> dict[str, Any]:
        return {"enabled": True, "execution": "temporal", "queue": "account-auth"}


@pytest.fixture
def platform_api() -> TestClient:
    application = FastAPI()
    application.state.platform_login_service = FakeLoginService()
    application.include_router(router)
    application.dependency_overrides[get_current_user_id] = lambda: "tenant-1"
    client = TestClient(application)
    try:
        yield client
    finally:
        client.close()


def test_platform_status_and_qr_are_redacted(platform_api: TestClient) -> None:
    status = platform_api.get("/v1/platform/login/flow-test/status")
    assert status.status_code == 200
    body = status.json()
    assert body["success"] is True
    assert body["data"]["state"] == "waiting_scan"
    assert "qr_object_ref" not in body["data"]

    started = platform_api.post(
        "/v1/platform/accounts/xhs_pc/primary/login/qr",
        json={"idempotency_key": "redaction-check"},
    )
    assert started.status_code == 200
    assert "qr_object_ref" not in started.text

    qr = platform_api.get("/v1/platform/login/flow-test/qr")
    assert qr.status_code == 200
    assert qr.json()["data"] == {
        "flow_id": "flow-test",
        "presentation_ref": "qr-present:opaque",
        "expires_at": "2026-08-31T00:02:00Z",
        "content_type": "image/png",
    }


def test_platform_login_rejects_raw_cookie_fields(platform_api: TestClient) -> None:
    response = platform_api.post(
        "/v1/platform/accounts/xhs_pc/primary/login",
        json={"mode": "cookie", "cookie": "sid=SECRET"},
    )
    assert response.status_code == 422
    assert "SECRET" not in response.text


def test_platform_routes_fail_closed_without_runtime() -> None:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_current_user_id] = lambda: "tenant-1"
    with TestClient(application) as client:
        response = client.post(
            "/v1/platform/accounts/xhs_pc/primary/login/qr",
            json={},
        )
    assert response.status_code == 503
    assert response.json() == {
        "success": False,
        "error": "PLATFORM_DISABLED",
        "message": "platform account control plane is disabled",
    }
