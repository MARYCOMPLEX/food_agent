"""Optional platform runtime injection stays explicit and reversible."""

from __future__ import annotations

import pytest
from fastapi import FastAPI


@pytest.mark.unit
async def test_platform_runtime_factory_builds_injected_login_service_and_cleanup() -> None:
    from api.main import _close_platform_runtime, _load_platform_runtime

    application = FastAPI()
    calls: list[str] = []

    class Authority:
        pass

    class Workflow:
        pass

    def build_start(request: object, **kwargs: object) -> dict[str, object]:
        return {"request": request, **kwargs}

    async def factory(target: object) -> dict[str, object]:
        assert target is not None

        async def cleanup() -> None:
            calls.append("cleanup")

        return {
            "authority": Authority(),
            "workflow": Workflow(),
            "workflow_start_builder": build_start,
            "queue": "account-auth-fixture",
            "cleanup": cleanup,
        }

    application.state.platform_runtime_factory = factory
    target = type(
        "Target",
        (),
        {
            "platform_connectors_enabled": True,
            "platform_login_enabled": True,
            "temporal_account_auth_queue": "account-auth-fixture",
        },
    )()

    runtime, cleanup, kwargs = await _load_platform_runtime(application, target)

    assert runtime["queue"] == "account-auth-fixture"
    assert callable(cleanup)
    assert kwargs["target_settings"] is target
    assert kwargs["platform_account_authority"].__class__.__name__ == "Authority"
    service = kwargs["platform_login_service"]
    assert service.__class__.__name__ == "PlatformLoginService"
    await _close_platform_runtime(cleanup)
    assert calls == ["cleanup"]


@pytest.mark.unit
async def test_platform_runtime_hook_absent_preserves_empty_legacy_kwargs() -> None:
    from api.main import _load_platform_runtime

    application = FastAPI()
    target = object()
    runtime, cleanup, kwargs = await _load_platform_runtime(application, target)
    assert runtime is None
    assert cleanup is None
    assert kwargs == {}
