"""Unit gates for explicit refresh authorization and task/event mapping."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from xhs_food.contracts import (
    RefreshClaim,
    RequestIdentity,
    RequestPolicy,
    ResearchOperation,
    ResearchRequest,
    ResearchTask,
    TaskStatus,
    WorkflowRun,
    stable_refresh_claim_key,
    stable_refresh_workflow_id,
)
from xhs_food.evidence import ExplicitRefreshRequestMapper, ExplicitRefreshService


def _request(*, force: bool = False, authorization: tuple[str, ...] = ()) -> ResearchRequest:
    return ResearchRequest(
        request_id="request-refresh-1",
        operation=ResearchOperation.REFRESH,
        domain="food",
        query=None,
        query_family_id="family.zigong",
        public_inputs={"refresh_scope": ["restaurants", "reviews"], "force": force},
        identity=RequestIdentity(authorization_refs=authorization),
        policy=RequestPolicy(policy_version="refresh-policy/v1", compatibility_version="v1"),
    )


class _Repository:
    def __init__(self, claim: RefreshClaim) -> None:
        self.claim = claim
        self.calls = 0

    async def claim_refresh(self, key: object) -> RefreshClaim:
        del key
        self.calls += 1
        return self.claim


class _Workflow:
    def __init__(self) -> None:
        self.started: list[object] = []
        self.described: list[str] = []

    async def start(self, command: object) -> WorkflowRun:
        self.started.append(command)
        return WorkflowRun(workflow_id=command.workflow_id, run_id="run-1", status="running")  # type: ignore[attr-defined]

    async def signal(self, workflow_id: str, signal: str, payload: dict[str, object]) -> None:
        del workflow_id, signal, payload

    async def cancel(self, workflow_id: str, reason: str | None = None) -> None:
        del workflow_id, reason

    async def describe(self, workflow_id: str) -> WorkflowRun | None:
        self.described.append(workflow_id)
        return WorkflowRun(workflow_id=workflow_id, run_id="run-existing", status="running")


class _Builder:
    async def build(
        self,
        request: ResearchRequest,
        task_id: str,
        workflow_id: str,
        run: WorkflowRun | None,
        *,
        reused: bool,
    ) -> ResearchTask:
        del request, reused
        now = datetime.now(UTC)
        return ResearchTask(
            task_id=task_id,
            request_id="request-refresh-1",
            operation=ResearchOperation.REFRESH,
            domain="food",
            status=TaskStatus.PLANNING,
            query_family_id="family.zigong",
            workflow_id=workflow_id,
            run_id=run.run_id if run else None,
            created_at=now,
            updated_at=now,
        )


class _Publisher:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, event: object) -> None:
        self.events.append(event)


def _claim(request: ResearchRequest, *, acquired: bool) -> RefreshClaim:
    from xhs_food.contracts import RefreshSingleFlightKey

    key = RefreshSingleFlightKey(
        family_id=request.query_family_id or "",
        scope=("restaurants", "reviews"),
        policy_version=request.policy.policy_version,
    )
    return RefreshClaim(
        claim_key=stable_refresh_claim_key(key),
        workflow_id=stable_refresh_workflow_id(key),
        acquired=acquired,
    )


@pytest.mark.unit
async def test_ordinary_refresh_starts_refresh_queue_and_publishes_event() -> None:
    request = _request()
    repository = _Repository(_claim(request, acquired=True))
    workflow = _Workflow()
    publisher = _Publisher()

    task = await ExplicitRefreshService(
        repository,
        workflow,
        _Builder(),
        publisher=publisher,
    ).submit(request)

    assert task.operation is ResearchOperation.REFRESH
    assert len(workflow.started) == 1
    assert workflow.started[0].task_queue == "refresh"  # type: ignore[attr-defined]
    assert publisher.events[0].event_type == "task.refresh.accepted"
    assert publisher.events[0].payload["reused"] is False


@pytest.mark.unit
async def test_duplicate_refresh_reuses_workflow_without_starting_another() -> None:
    request = _request()
    repository = _Repository(_claim(request, acquired=False))
    workflow = _Workflow()
    publisher = _Publisher()

    await ExplicitRefreshService(repository, workflow, _Builder(), publisher=publisher).submit(request)

    assert workflow.started == []
    assert len(workflow.described) == 1
    assert publisher.events[0].payload["reused"] is True


@pytest.mark.unit
async def test_forced_refresh_requires_authorization_before_claim() -> None:
    request = _request(force=True)
    repository = _Repository(_claim(request, acquired=True))

    with pytest.raises(PermissionError, match="refresh:force"):
        await ExplicitRefreshService(repository, _Workflow(), _Builder()).submit(request)

    assert repository.calls == 0


@pytest.mark.unit
async def test_authorized_forced_refresh_is_accepted() -> None:
    request = _request(force=True, authorization=("refresh:force",))
    repository = _Repository(_claim(request, acquired=True))
    publisher = _Publisher()

    await ExplicitRefreshService(repository, _Workflow(), _Builder(), publisher=publisher).submit(request)

    assert publisher.events[0].payload["force"] is True


@pytest.mark.unit
async def test_refresh_rejects_missing_scope_without_claim() -> None:
    request = _request().model_copy(update={"public_inputs": {}})
    repository = _Repository(_claim(_request(), acquired=True))

    with pytest.raises(ValueError, match="refresh_scope"):
        await ExplicitRefreshService(repository, _Workflow(), _Builder()).submit(request)
    assert repository.calls == 0


@pytest.mark.unit
async def test_refresh_rejects_nondeterministic_claim() -> None:
    request = _request()
    claim = _claim(request, acquired=True).model_copy(update={"workflow_id": "wrong"})

    with pytest.raises(ValueError, match="deterministic"):
        await ExplicitRefreshService(
            _Repository(claim), _Workflow(), _Builder()
        ).submit(request)


@pytest.mark.unit
def test_refresh_request_mapper_requires_versioned_wire_fields() -> None:
    request = ExplicitRefreshRequestMapper().to_request(
        {
            "requestId": "wire-refresh-1",
            "domain": "food",
            "queryFamilyId": "family.zigong",
            "refreshScope": ["restaurants"],
            "force": False,
            "policyVersion": "refresh-policy/v1",
            "compatibilityVersion": "v1",
        },
        identity=RequestIdentity(),
    )

    assert request.operation is ResearchOperation.REFRESH
    assert request.public_inputs["refresh_scope"] == ["restaurants"]


@pytest.mark.unit
def test_refresh_request_mapper_rejects_missing_policy_version() -> None:
    payload = {
        "requestId": "wire-refresh-1",
        "domain": "food",
        "queryFamilyId": "family.zigong",
        "refreshScope": ["restaurants"],
        "compatibilityVersion": "v1",
    }

    with pytest.raises(ValueError, match="policyVersion"):
        ExplicitRefreshRequestMapper().to_request(payload, identity=RequestIdentity())
