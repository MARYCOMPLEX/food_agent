"""B4 operational policy, failure isolation, and telemetry contracts."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError
from test_unit_b4_media_pipeline import _fetch_request
from test_unit_object_store_adapter import byte_chunks

from xhs_food.contracts import ObjectStorePolicy, OrphanCleanupRequest
from xhs_food.foundation import Boto3ObjectStore, RefreshMediaTelemetry, TargetSettings
from xhs_food.orchestrator import (
    MEDIA_FETCH_ACTIVITY,
    MEDIA_TASK_QUEUE,
    MEDIA_WORKFLOW_TYPE,
    MediaActivities,
    TemporalMediaWorkflow,
    build_media_workflow_start,
)


class _Client:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, dict[str, Any]]] = {}
        self.presign_calls: list[dict[str, Any]] = []

    def upload_fileobj(
        self,
        file_object: io.BufferedReader,
        bucket: str,
        key: str,
        *,
        ExtraArgs: dict[str, Any],
        Config: Any,
    ) -> None:
        del bucket, Config
        self.objects[key] = (file_object.read(), ExtraArgs)

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        del Bucket
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "HeadObject",
            )
        payload, extra = self.objects[Key]
        return {
            "ContentType": extra["ContentType"],
            "ContentLength": len(payload),
            "Metadata": extra["Metadata"],
        }

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        del Bucket
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
                "DeleteObject",
            )
        del self.objects[Key]

    def generate_presigned_url(self, operation: str, *, Params: dict[str, str], ExpiresIn: int) -> str:
        self.presign_calls.append({"operation": operation, "params": Params, "expires": ExpiresIn})
        return "https://signed.fixture/object"


@pytest.mark.unit
def test_background_workers_are_closed_by_default_and_can_be_enabled_explicitly() -> None:
    defaults = TargetSettings()
    assert defaults.refresh_enabled is False
    assert defaults.media_enabled is False
    enabled = TargetSettings(
        refresh_enabled=True,
        media_enabled=True,
        object_store_environment="local",
    )
    assert enabled.refresh_enabled is True
    assert enabled.media_enabled is True


@pytest.mark.unit
def test_production_object_policy_requires_encryption_and_kms_key() -> None:
    with pytest.raises(ValueError, match="server-side encryption"):
        ObjectStorePolicy(environment="production")
    with pytest.raises(ValueError, match="encryption key"):
        ObjectStorePolicy(environment="production", server_side_encryption="aws:kms")
    assert ObjectStorePolicy(
        environment="production",
        server_side_encryption="aws:kms",
        encryption_key_ref="kms/food-agent",
    ).server_side_encryption == "aws:kms"


@pytest.mark.unit
async def test_object_store_enforces_allow_list_size_encryption_and_signed_ttl() -> None:
    client = _Client()
    store = Boto3ObjectStore(
        bucket="media",
        client=client,
        allowed_content_types=("image/jpeg",),
        max_object_bytes=4,
        multipart_chunksize=2,
        server_side_encryption="AES256",
        signed_url_ttl_seconds=60,
    )
    with pytest.raises(ValueError, match="allow-list"):
        await store.put("raw/bad", byte_chunks(b"x"), "text/plain")
    with pytest.raises(ValueError, match="size"):
        await store.put("raw/large", byte_chunks(b"12345"), "image/jpeg")
    ref = await store.put("raw/ok", byte_chunks(b"1234"), "image/jpeg")
    assert client.objects[ref.key][1]["ServerSideEncryption"] == "AES256"
    assert await store.signed_url(ref) == "https://signed.fixture/object"
    assert client.presign_calls[0]["expires"] == 60
    with pytest.raises(ValueError, match="seven days"):
        await store.signed_url(ref, ttl_seconds=7 * 24 * 60 * 60 + 1)


@pytest.mark.unit
async def test_orphan_cleanup_rechecks_commit_reference_and_grace() -> None:
    client = _Client()
    store = Boto3ObjectStore(bucket="media", client=client, orphan_grace_seconds=0)
    ref = await store.put("raw/orphan", byte_chunks(b"orphan"), "application/octet-stream")
    request = OrphanCleanupRequest(
        object_ref=ref,
        uploaded_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    result = await store.cleanup_orphan(request)
    assert result.action == "deleted"
    assert await store.stat(ref) is None

    retained = await store.cleanup_orphan(request.model_copy(update={"metadata_committed": True}))
    assert retained.action == "retained"


@pytest.mark.unit
def test_b4_telemetry_uses_only_registered_low_cardinality_values() -> None:
    telemetry = RefreshMediaTelemetry(enabled=True)
    telemetry.record_worker_health(task_queue="media", status="ready")
    telemetry.record_queue_lag(task_queue="refresh", lag_seconds=1.25)
    telemetry.record_throughput(task_queue="research", outcome="success")
    telemetry.record_retry_exhaustion(task_queue="refresh")
    telemetry.record_object_io(operation="upload", outcome="success")
    telemetry.record_extractor_error()
    with pytest.raises(ValueError, match="unregistered Prometheus label"):
        telemetry.record_worker_health(task_queue="tenant-123", status="ready")


@pytest.mark.unit
def test_media_workflow_isolated_queue_and_deterministic_start_contract() -> None:
    request = _fetch_request()
    command = build_media_workflow_start(
        request,
        workflow_id="media:fixture:asset",
        idempotency_key="media-idempotency-1",
    )
    assert command.workflow_type == MEDIA_WORKFLOW_TYPE
    assert command.task_queue == MEDIA_TASK_QUEUE
    assert command.input["request"]["request_id"] == request.request_id
    assert getattr(TemporalMediaWorkflow, "__temporal_workflow_definition", None) is not None
    activities = MediaActivities(lambda _: None)  # type: ignore[arg-type]
    assert getattr(activities.activities()[0], "__temporal_activity_definition").name == MEDIA_FETCH_ACTIVITY
