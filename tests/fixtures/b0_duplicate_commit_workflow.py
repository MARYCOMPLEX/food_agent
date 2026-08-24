"""Sandbox-isolated workflow used by the B0 duplicate Activity qualification."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow


@workflow.defn(name="B0DuplicateCommitQualificationWorkflow")
class DuplicateCommitQualificationWorkflow:
    """Run one authority commit twice with the same idempotency key."""

    @workflow.run
    async def run(self, raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        commit_input = {**raw, "run_id": workflow.info().run_id}
        first = await workflow.execute_activity(
            "research.commit/v1",
            args=[commit_input],
            start_to_close_timeout=timedelta(seconds=5),
            activity_id=f"{raw['task_id']}:commit:first",
        )
        second = await workflow.execute_activity(
            "research.commit/v1",
            args=[commit_input],
            start_to_close_timeout=timedelta(seconds=5),
            activity_id=f"{raw['task_id']}:commit:duplicate",
        )
        return dict(first), dict(second)
