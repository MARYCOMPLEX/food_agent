"""Optional account-auth Temporal queue contracts and worker binding."""

from __future__ import annotations

from typing import Any

import pytest

from xhs_food.composition import build_account_auth_worker
from xhs_food.composition.adapters import build_owner_config
from xhs_food.config import Settings
from xhs_food.foundation import (
    TargetSettings,
    TemporalConfigView,
    TemporalTaskQueues,
    TemporalWorkerQuota,
    build_temporal_auth_worker,
)


class _Worker:
    def __init__(self, client: Any, **kwargs: Any) -> None:
        self.client = client
        self.kwargs = kwargs


class _Activities:
    def activities(self) -> tuple[str, ...]:
        return ("login_activity",)


@pytest.mark.unit
def test_account_auth_queue_is_optional_and_disabled_by_default() -> None:
    baseline = TemporalTaskQueues()
    assert baseline.allowed == frozenset({"research", "refresh", "media"})
    assert baseline.active == frozenset({"research"})
    with pytest.raises(ValueError, match="unregistered"):
        baseline.queue_for("account_auth")

    configured = TemporalTaskQueues(account_auth="account-auth")
    assert configured.allowed == frozenset({"research", "refresh", "media", "account-auth"})
    assert "account-auth" not in configured.active
    assert configured.quota_for_workload("account_auth").enabled is False
    with pytest.raises(ValueError, match="disabled"):
        configured.assert_enabled("account-auth")


@pytest.mark.unit
def test_enabled_account_auth_worker_uses_explicit_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("temporalio.worker.Worker", _Worker)
    queues = TemporalTaskQueues(
        account_auth="account-auth",
        account_auth_quota=TemporalWorkerQuota(
            "account-auth", 3, 2, 75, enabled=True
        ),
    )
    worker = build_temporal_auth_worker(object(), _Activities(), task_queues=queues)
    assert worker.kwargs["task_queue"] == "account-auth"
    assert worker.kwargs["max_concurrent_activities"] == 3
    assert worker.kwargs["max_concurrent_workflow_tasks"] == 2
    assert worker.kwargs["activities"] == ("login_activity",)

    # The Composition Root wrapper preserves the same queue gate and adapter
    # registration path.
    wrapped = build_account_auth_worker(object(), _Activities(), task_queues=queues)
    assert wrapped.kwargs["task_queue"] == "account-auth"


@pytest.mark.unit
def test_auth_queue_configuration_is_owner_scoped_and_fail_closed() -> None:
    with pytest.raises(ValueError, match="requires"):
        TargetSettings(temporal_account_auth_enabled=True)
    with pytest.raises(ValueError, match="distinct"):
        TargetSettings(
            temporal_account_auth_queue="research",
        )

    target = TargetSettings(
        temporal_account_auth_queue="account-auth",
        temporal_account_auth_enabled=True,
        temporal_account_auth_max_concurrent_activities=4,
        temporal_account_auth_max_concurrent_workflows=1,
        temporal_account_auth_priority=80,
    )
    owner = build_owner_config(Settings(), target)
    assert isinstance(owner.temporal, TemporalConfigView)
    assert owner.temporal.account_auth_queue == "account-auth"
    assert owner.temporal.account_auth_enabled is True
    assert owner.temporal.account_auth_max_concurrent_activities == 4
    assert owner.temporal.account_auth_max_concurrent_workflows == 1
    assert owner.temporal.account_auth_priority == 80


@pytest.mark.unit
def test_auth_worker_without_explicit_queue_fails_closed() -> None:
    with pytest.raises(ValueError, match="not configured"):
        build_temporal_auth_worker(object(), _Activities())
