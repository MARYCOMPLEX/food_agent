"""Qualification gates for the accepted foundation binding decision."""

from __future__ import annotations

from pathlib import Path

import pytest

from xhs_food.foundation import Boto3ObjectStore, TemporalTaskQueues

ADR = (
    Path(__file__).parents[1]
    / "openspec"
    / "changes"
    / "define-modular-architecture"
    / "decisions"
    / "ADR-0012-task-queues-object-store-operations.md"
)


@pytest.mark.unit
def test_adr_0012_records_authority_and_fail_closed_operations() -> None:
    text = ADR.read_text(encoding="utf-8")

    for required in (
        "Temporal `research` Task Queue",
        "Temporal `refresh` Task Queue",
        "Temporal `media` Task Queue",
        "ObjectStore` backed by boto3",
        "local and CI MinIO",
        "server-side encryption",
        "versioned retention class",
        "orphan",
        "queryable failed execution",
        "same Workflow ID/idempotency key",
        "unconditional pointer update",
    ):
        assert required in text


@pytest.mark.unit
def test_temporal_queues_and_minio_adapter_have_one_replaceable_binding() -> None:
    queues = TemporalTaskQueues(research="research", refresh="refresh", media="media")
    assert queues.allowed == frozenset({"research", "refresh", "media"})
    with pytest.raises(ValueError, match="distinct"):
        TemporalTaskQueues(research="research", refresh="research", media="media")

    store = Boto3ObjectStore.for_minio(
        bucket="fixture",
        endpoint_url="http://minio.fixture",
        access_key_id="ACCESS_KEY",
        secret_access_key="SECRET_KEY",
    )
    assert isinstance(store, Boto3ObjectStore)
    assert "minio" not in type(store).__module__.casefold()
