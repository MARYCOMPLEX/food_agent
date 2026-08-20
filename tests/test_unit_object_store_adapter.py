"""Offline contract tests for the target boto3 ObjectStore adapter."""

from __future__ import annotations

import asyncio
import hashlib
import io
import threading
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

from xhs_food.contracts import ObjectRef
from xhs_food.foundation import FoundationAdapterError
from xhs_food.foundation import object_store as object_store_module
from xhs_food.foundation.object_store import Boto3ObjectStore, minio_s3_client_factory


async def byte_chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


def missing_object_error() -> ClientError:
    return ClientError(
        {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
        "GetObject",
    )


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self._stream = io.BytesIO(data)
        self.closed = False

    def read(self, size: int) -> bytes:
        return self._stream.read(size)

    def close(self) -> None:
        self.closed = True
        self._stream.close()


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, dict[str, Any]]] = {}
        self.uploads: list[dict[str, Any]] = []
        self.closed = False
        self.active_uploads = 0
        self.max_active_uploads = 0
        self.upload_gate: threading.Event | None = None

    def upload_fileobj(
        self,
        file_object: io.BufferedReader,
        bucket: str,
        key: str,
        *,
        ExtraArgs: dict[str, Any],
        Config: Any,
    ) -> None:
        self.active_uploads += 1
        self.max_active_uploads = max(self.max_active_uploads, self.active_uploads)
        try:
            if self.upload_gate is not None:
                self.upload_gate.wait(timeout=2)
            payload = file_object.read()
            self.objects[key] = (payload, ExtraArgs)
            self.uploads.append({"bucket": bucket, "key": key, "config": Config})
        finally:
            self.active_uploads -= 1

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        del Bucket
        if Key not in self.objects:
            raise missing_object_error()
        payload, _ = self.objects[Key]
        return {"Body": FakeBody(payload)}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        del Bucket
        if Key not in self.objects:
            raise missing_object_error()
        payload, extra_args = self.objects[Key]
        return {
            "ContentType": extra_args["ContentType"],
            "ContentLength": len(payload),
            "Metadata": extra_args["Metadata"],
            "ETag": '"fake-etag"',
            "LastModified": datetime(2026, 8, 20, tzinfo=UTC),
        }

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        del Bucket
        if Key not in self.objects:
            raise missing_object_error()
        del self.objects[Key]

    def close(self) -> None:
        self.closed = True


@pytest.mark.unit
async def test_put_configures_multipart_and_returns_content_addressed_ref() -> None:
    client = FakeS3Client()
    store = Boto3ObjectStore(
        bucket="media",
        client=client,
        multipart_threshold=3,
        multipart_chunksize=2,
    )

    ref = await store.put(
        "tenant-a/assets/item.bin",
        byte_chunks(b"ab", b"cde"),
        "application/octet-stream",
        {"source": "fixture", "attempt": 2},
    )

    expected_hash = hashlib.sha256(b"abcde").hexdigest()
    assert ref.object_id == expected_hash
    assert ref.content_hash == expected_hash
    assert ref.size_bytes == 5
    assert ref.key == "tenant-a/assets/item.bin"
    assert client.objects[ref.key][0] == b"abcde"
    assert client.objects[ref.key][1]["Metadata"] == {
        "xhs-food-content-hash": expected_hash,
        "xhs-food-object-id": expected_hash,
        "source": "fixture",
        "attempt": "2",
    }
    config = client.uploads[0]["config"]
    assert config.multipart_threshold == 3
    assert config.multipart_chunksize == 2
    assert config.max_concurrency == 1


@pytest.mark.unit
async def test_get_stat_delete_and_missing_object_behavior() -> None:
    client = FakeS3Client()
    store = Boto3ObjectStore(bucket="media", client=client, read_chunk_size=2)
    ref = await store.put("media/one.bin", byte_chunks(b"hello"), "application/octet-stream")

    assert [chunk async for chunk in store.get(ref)] == [b"he", b"ll", b"o"]
    stat = await store.stat(ref)
    assert stat is not None
    assert stat.ref == ref
    assert stat.metadata == {
        "content_type": "application/octet-stream",
        "size_bytes": 5,
        "user_metadata": {
            "xhs-food-content-hash": ref.content_hash,
            "xhs-food-object-id": ref.object_id,
        },
        "e_tag": '"fake-etag"',
        "last_modified": "2026-08-20T00:00:00+00:00",
    }
    assert await store.delete(ref) is True
    assert await store.stat(ref) is None
    assert await store.delete(ref) is False
    with pytest.raises(FileNotFoundError):
        _ = [chunk async for chunk in store.get(ref)]


@pytest.mark.unit
async def test_client_factory_is_lazy_and_lifecycle_is_explicit() -> None:
    client = FakeS3Client()
    calls = 0

    def factory() -> FakeS3Client:
        nonlocal calls
        calls += 1
        return client

    store = Boto3ObjectStore(bucket="media", client_factory=factory)
    assert calls == 0
    ref = await store.put("media/lazy.bin", byte_chunks(b"a"), "text/plain")
    assert ref.size_bytes == 1
    assert calls == 1
    await store.aclose()
    assert client.closed is True
    with pytest.raises(RuntimeError, match="closed"):
        await store.stat(ref)


@pytest.mark.unit
@pytest.mark.parametrize("failure", ["metadata", "client"])
async def test_put_removes_temporary_file_before_upload_starts(
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original = object_store_module.tempfile.NamedTemporaryFile

    def temporary_file(**kwargs: Any) -> Any:
        return original(dir=tmp_path, **kwargs)

    monkeypatch.setattr(object_store_module.tempfile, "NamedTemporaryFile", temporary_file)
    if failure == "metadata":
        store = Boto3ObjectStore(bucket="media", client=FakeS3Client())
        with pytest.raises(ValueError, match="reserved"):
            await store.put(
                "media/metadata.bin",
                byte_chunks(b"payload"),
                "application/octet-stream",
                {"xhs-food-content-hash": "caller-controlled"},
            )
    else:

        def broken_factory() -> object:
            raise ConnectionError("fixture client unavailable")

        store = Boto3ObjectStore(bucket="media", client_factory=broken_factory)
        with pytest.raises(FoundationAdapterError):
            await store.put(
                "media/client.bin",
                byte_chunks(b"payload"),
                "application/octet-stream",
            )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.unit
async def test_put_bounds_synchronous_upload_concurrency() -> None:
    client = FakeS3Client()
    client.upload_gate = threading.Event()
    store = Boto3ObjectStore(bucket="media", client=client, max_concurrency=1)

    first = asyncio.create_task(store.put("media/first.bin", byte_chunks(b"1"), "text/plain"))
    second = asyncio.create_task(store.put("media/second.bin", byte_chunks(b"2"), "text/plain"))
    await asyncio.sleep(0.05)
    assert client.max_active_uploads == 1
    client.upload_gate.set()
    await asyncio.gather(first, second)
    assert client.max_active_uploads == 1


@pytest.mark.unit
def test_minio_factory_is_endpoint_compatible_without_creating_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_client(service_name: str, **kwargs: Any) -> object:
        captured["service_name"] = service_name
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("xhs_food.foundation.object_store.boto3.client", fake_client)
    factory = minio_s3_client_factory(
        endpoint_url="http://minio:9000",
        access_key_id="minio",
        secret_access_key="minio-secret",
    )
    assert captured == {}
    factory()
    assert captured["service_name"] == "s3"
    assert captured["endpoint_url"] == "http://minio:9000"
    assert captured["config"].s3["addressing_style"] == "path"


@pytest.mark.unit
def test_object_ref_remains_an_opaque_key() -> None:
    with pytest.raises(ValueError, match="not a URL"):
        ObjectRef(
            object_id="id",
            key="s3://media/secret",
            content_hash="hash",
            size_bytes=1,
            content_type="text/plain",
        )
