"""Explicit refresh use-case with authorization and Temporal single-flight."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from xhs_food.contracts import (
    ExplicitRefreshUseCase,
    QueryFamilyRepository,
    RefreshEventPublisher,
    RefreshSingleFlightKey,
    RefreshTaskBuilder,
    RequestIdentity,
    RequestPolicy,
    ResearchOperation,
    ResearchRequest,
    ResearchTask,
    TaskEvent,
    WorkflowPort,
    WorkflowRun,
    WorkflowStart,
    stable_refresh_claim_key,
    stable_refresh_task_id,
    stable_refresh_workflow_id,
)

RefreshWorkflowCommandFactory = Callable[
    [ResearchRequest, str, str], WorkflowStart
]


class ExplicitRefreshService(ExplicitRefreshUseCase):
    """Submit ordinary/forced refreshes without exposing a legacy route."""

    def __init__(
        self,
        repository: QueryFamilyRepository,
        workflow: WorkflowPort,
        task_builder: RefreshTaskBuilder,
        *,
        publisher: RefreshEventPublisher | None = None,
        command_factory: RefreshWorkflowCommandFactory | None = None,
    ) -> None:
        self._repository = repository
        self._workflow = workflow
        self._task_builder = task_builder
        self._publisher = publisher
        self._command_factory = command_factory or _default_command

    async def submit(self, request: ResearchRequest) -> ResearchTask:
        if request.operation is not ResearchOperation.REFRESH:
            raise ValueError("explicit refresh requires operation=refresh")
        family_id = request.query_family_id
        if not family_id:
            raise ValueError("refresh requires query_family_id")
        scope = _scope(request.public_inputs)
        force = _force(request.public_inputs)
        if force and "refresh:force" not in request.identity.authorization_refs:
            raise PermissionError("forced refresh requires refresh:force authorization")

        key = RefreshSingleFlightKey(
            family_id=family_id,
            scope=scope,
            policy_version=request.policy.policy_version,
        )
        claim = await self._repository.claim_refresh(key)
        workflow_id = stable_refresh_workflow_id(key)
        if claim.workflow_id != workflow_id or claim.claim_key != stable_refresh_claim_key(key):
            raise ValueError("refresh claim is not deterministic for the requested scope")
        task_id = stable_refresh_task_id(workflow_id)
        reused = not claim.acquired
        run: WorkflowRun | None
        if claim.acquired:
            command = self._command_factory(request, task_id, workflow_id)
            run = await self._workflow.start(command)
        else:
            run = await self._workflow.describe(workflow_id)
        task = await self._task_builder.build(
            request,
            task_id,
            workflow_id,
            run,
            reused=reused,
        )
        if self._publisher is not None:
            await self._publisher.publish(
                TaskEvent(
                    event_id=f"{task_id}:refresh:accepted",
                    task_id=task_id,
                    event_type="task.refresh.accepted",
                    occurred_at=task.created_at,
                    turn_id=task.turn_id,
                    status=task.status,
                    progress=0.0,
                    payload={
                        "familyId": family_id,
                        "workflowId": workflow_id,
                        "reused": reused,
                        "force": force,
                    },
                )
            )
        return task


class ExplicitRefreshRequestMapper:
    """Map a future versioned refresh HTTP payload without adding a route."""

    def to_request(
        self, payload: Mapping[str, Any], *, identity: RequestIdentity
    ) -> ResearchRequest:
        public_inputs = payload.get("publicInputs", {})
        if not isinstance(public_inputs, Mapping):
            raise ValueError("publicInputs must be an object")
        scope = payload.get("refreshScope", public_inputs.get("refresh_scope"))
        if not isinstance(scope, (list, tuple)) or not scope:
            raise ValueError("refreshScope must be a non-empty array")
        force = payload.get("force", public_inputs.get("force", False))
        if not isinstance(force, bool):
            raise ValueError("force must be boolean")
        request_id = _required_wire_text(payload, "requestId")
        domain = _required_wire_text(payload, "domain")
        family_id = _required_wire_text(payload, "queryFamilyId")
        policy_version = _required_wire_text(payload, "policyVersion")
        compatibility_version = _required_wire_text(payload, "compatibilityVersion")
        return ResearchRequest(
            request_id=request_id,
            operation=ResearchOperation.REFRESH,
            domain=domain,
            query=None,
            query_family_id=family_id,
            public_inputs={"refresh_scope": list(scope), "force": force},
            identity=identity,
            policy=RequestPolicy(
                policy_version=policy_version,
                compatibility_version=compatibility_version,
            ),
        )


def _scope(payload: Mapping[str, Any]) -> tuple[str, ...]:
    value = payload.get("refresh_scope")
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("refresh public_inputs.refresh_scope must be a non-empty array")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError("refresh scope entries must be non-empty strings")
    return tuple(str(item) for item in value)


def _required_wire_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _force(payload: Mapping[str, Any]) -> bool:
    value = payload.get("force", False)
    if not isinstance(value, bool):
        raise ValueError("refresh public_inputs.force must be boolean")
    return value


def _default_command(request: ResearchRequest, task_id: str, workflow_id: str) -> WorkflowStart:
    del task_id
    return WorkflowStart(
        workflow_id=workflow_id,
        workflow_type="refresh.workflow/v1",
        task_queue="refresh",
        input=request.model_dump(mode="json"),
        idempotency_key=workflow_id,
    )


__all__ = ["ExplicitRefreshRequestMapper", "ExplicitRefreshService"]
