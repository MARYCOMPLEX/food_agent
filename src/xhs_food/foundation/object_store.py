"""S3-compatible binary storage adapter behind the project-owned ObjectStore port."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from collections.abc import AsyncIterable, AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError

from xhs_food.contracts import (
    ContractPayload,
    ErrorScope,
    ObjectRef,
    ObjectStat,
    ObjectStorePolicy,
    OrphanCleanupRequest,
    OrphanCleanupResult,
)

from .failures import (
    FoundationAdapterError,
    foundation_error_from_exception,
    foundation_failure_boundary,
)

_CONTENT_HASH_METADATA_KEY = "xhs-food-content-hash"
_OBJECT_ID_METADATA_KEY = "xhs-food-object-id"
_RESERVED_METADATA_KEYS = frozenset({_CONTENT_HASH_METADATA_KEY, _OBJECT_ID_METADATA_KEY})


def boto3_s3_client_factory() -> Any:
    """Build the default S3 client only when the adapter first needs it."""

    return boto3.client("s3")


def minio_s3_client_factory(
    *,
    endpoint_url: str,
    access_key_id: str,
    secret_access_key: str,
    region_name: str = "us-east-1",
) -> Callable[[], Any]:
    """Return an endpoint-compatible MinIO factory without importing a MinIO SDK."""

    def create_client() -> Any:
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region_name,
            config=Config(s3={"addressing_style": "path"}),
        )

    return create_client


class Boto3ObjectStore:
    """Bounded async facade for a boto3 S3-compatible client.

    boto3 is synchronous. Every call into it is scheduled through one semaphore
    and ``asyncio.to_thread``; the adapter never exposes provider values through
    the ``ObjectStore`` contract.
    """

    def __init__(
        self,
        *,
        bucket: str,
        client: Any | None = None,
        client_factory: Callable[[], Any] | None = None,
        max_concurrency: int = 4,
        multipart_threshold: int = 8 * 1024 * 1024,
        multipart_chunksize: int = 8 * 1024 * 1024,
        read_chunk_size: int = 64 * 1024,
        max_object_bytes: int | None = None,
        allowed_content_types: tuple[str, ...] | None = None,
        environment: str = "test",
        server_side_encryption: str | None = None,
        encryption_key_ref: str | None = None,
        signed_url_ttl_seconds: int | None = None,
        orphan_grace_seconds: int | None = None,
        require_encryption: bool = False,
        policy: ObjectStorePolicy | None = None,
        telemetry: Any | None = None,
    ) -> None:
        if policy is not None:
            if any(
                value is not None
                for value in (
                    max_object_bytes,
                    allowed_content_types,
                    server_side_encryption,
                    encryption_key_ref,
                    signed_url_ttl_seconds,
                    orphan_grace_seconds,
                )
            ):
                raise ValueError("provide either policy or individual ObjectStore policy values")
            environment = policy.environment
            max_object_bytes = policy.max_object_bytes
            allowed_content_types = policy.allowed_content_types
            multipart_threshold = policy.multipart_threshold_bytes
            multipart_chunksize = policy.multipart_chunk_bytes
            server_side_encryption = policy.server_side_encryption
            encryption_key_ref = policy.encryption_key_ref
            signed_url_ttl_seconds = policy.signed_url_ttl_seconds
            orphan_grace_seconds = policy.orphan_grace_seconds
            require_encryption = environment == "production"
        if not bucket:
            raise ValueError("bucket must not be empty")
        if client is not None and client_factory is not None:
            raise ValueError("provide either client or client_factory, not both")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least one")
        if multipart_threshold < 1 or multipart_chunksize < 1 or read_chunk_size < 1:
            raise ValueError("object store sizes must be positive")
        if max_object_bytes is not None and max_object_bytes < 1:
            raise ValueError("max_object_bytes must be positive")
        if max_object_bytes is not None and multipart_chunksize > max_object_bytes:
            raise ValueError("multipart_chunksize cannot exceed max_object_bytes")
        if allowed_content_types is not None and (
            not allowed_content_types or len(allowed_content_types) != len(set(allowed_content_types))
        ):
            raise ValueError("allowed_content_types must be non-empty and unique")
        if environment not in {"production", "local", "test"}:
            raise ValueError("ObjectStore environment must be production, local, or test")
        if require_encryption and not server_side_encryption:
            raise ValueError("production ObjectStore requires server-side encryption")
        if server_side_encryption not in {None, "AES256", "aws:kms", "test"}:
            raise ValueError("unsupported server-side encryption mode")
        if server_side_encryption == "aws:kms" and not encryption_key_ref:
            raise ValueError("aws:kms ObjectStore encryption requires an encryption key reference")
        if server_side_encryption != "aws:kms" and encryption_key_ref is not None:
            raise ValueError("encryption_key_ref is only valid with aws:kms")
        if signed_url_ttl_seconds is not None and signed_url_ttl_seconds < 1:
            raise ValueError("signed_url_ttl_seconds must be positive")
        if orphan_grace_seconds is not None and orphan_grace_seconds < 0:
            raise ValueError("orphan_grace_seconds cannot be negative")

        self._bucket = bucket
        self._client = client
        self._client_factory = client_factory or boto3_s3_client_factory
        self._client_lock = asyncio.Lock()
        self._operations = asyncio.Semaphore(max_concurrency)
        # One boto3 transfer is one bounded adapter operation. boto3 itself must
        # not fan out extra concurrent requests behind this limit.
        self._transfer_config = TransferConfig(
            multipart_threshold=multipart_threshold,
            multipart_chunksize=multipart_chunksize,
            max_concurrency=1,
        )
        self._read_chunk_size = read_chunk_size
        self._max_object_bytes = max_object_bytes
        self._allowed_content_types = frozenset(allowed_content_types or ())
        self._environment = environment
        self._server_side_encryption = server_side_encryption
        self._encryption_key_ref = encryption_key_ref
        self._signed_url_ttl_seconds = signed_url_ttl_seconds
        self._orphan_grace_seconds = orphan_grace_seconds
        self._telemetry = telemetry
        self._closed = False

    @classmethod
    def for_minio(
        cls,
        *,
        bucket: str,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        region_name: str = "us-east-1",
        **kwargs: Any,
    ) -> Boto3ObjectStore:
        """Construct an adapter configured for a local S3-compatible MinIO endpoint."""

        return cls(
            bucket=bucket,
            client_factory=minio_s3_client_factory(
                endpoint_url=endpoint_url,
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
                region_name=region_name,
            ),
            **kwargs,
        )

    async def put(
        self,
        key: str,
        chunks: AsyncIterable[bytes],
        content_type: str,
        metadata: ContractPayload | None = None,
    ) -> ObjectRef:
        """Upload byte chunks with a content hash calculated before dispatch."""

        if not content_type:
            raise ValueError("content_type must not be empty")
        if self._allowed_content_types and content_type not in self._allowed_content_types:
            raise ValueError("content_type is outside the configured ObjectStore allow-list")
        # Validate the externally supplied key before any byte reaches storage.
        ObjectRef(
            object_id="pending",
            key=key,
            content_hash="pending",
            size_bytes=0,
            content_type=content_type,
        )

        path, content_hash, size_bytes = await self._write_chunks(chunks)
        object_id = content_hash
        try:
            extra_args = {
                "ContentType": content_type,
                "Metadata": self._upload_metadata(metadata, content_hash, object_id),
            }
            if self._server_side_encryption in {"AES256", "aws:kms"}:
                extra_args["ServerSideEncryption"] = self._server_side_encryption
                if self._server_side_encryption == "aws:kms":
                    assert self._encryption_key_ref is not None
                    extra_args["SSEKMSKeyId"] = self._encryption_key_ref
            client = await self._get_client()
        except BaseException:
            self._remove_file(path)
            raise
        upload = asyncio.create_task(
            self._call_sync(
                self._upload_file,
                client,
                path,
                key,
                extra_args,
            )
        )
        try:
            await asyncio.shield(upload)
        except asyncio.CancelledError:
            upload.add_done_callback(lambda _: self._remove_file(path))
            raise
        except Exception as exc:
            self._remove_file(path)
            self._record_io("upload", "failure")
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    exc,
                    scope=ErrorScope.OBJECT_STORE,
                    operation="object_store.put",
                )
            ) from exc
        except BaseException:
            self._remove_file(path)
            raise
        else:
            self._remove_file(path)
            self._record_io("upload", "success")

        return ObjectRef(
            object_id=object_id,
            key=key,
            content_hash=content_hash,
            size_bytes=size_bytes,
            content_type=content_type,
        )

    async def _write_chunks(self, chunks: AsyncIterable[bytes]) -> tuple[Path, str, int]:
        digest = hashlib.sha256()
        size_bytes = 0
        path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix="xhs-food-object-", delete=False) as handle:
                path = Path(handle.name)
                async for chunk in chunks:
                    if not isinstance(chunk, bytes):
                        raise TypeError("ObjectStore chunks must be bytes")
                    digest.update(chunk)
                    size_bytes += len(chunk)
                    if self._max_object_bytes is not None and size_bytes > self._max_object_bytes:
                        raise ValueError("object exceeds the configured size allow-list")
                    handle.write(chunk)
                handle.flush()
        except BaseException:
            if path is not None:
                self._remove_file(path)
            raise
        if path is None:
            raise RuntimeError("temporary upload path was not created")
        return path, digest.hexdigest(), size_bytes

    def get(self, ref: ObjectRef) -> AsyncIterator[bytes]:
        return self._stream(ref)

    async def _stream(self, ref: ObjectRef) -> AsyncIterator[bytes]:
        client = await self._get_client()
        try:
            response = await self._call_sync(
                client.get_object,
                Bucket=self._bucket,
                Key=ref.key,
            )
        except ClientError as error:
            if self._is_not_found(error):
                raise FileNotFoundError(ref.key) from error
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    error,
                    scope=ErrorScope.OBJECT_STORE,
                    operation="object_store.get",
                )
            ) from error
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    exc,
                    scope=ErrorScope.OBJECT_STORE,
                    operation="object_store.get",
                )
            ) from exc

        with foundation_failure_boundary(
            scope=ErrorScope.OBJECT_STORE,
            operation="object_store.get.response",
        ):
            body = response["Body"]
        try:
            while True:
                with foundation_failure_boundary(
                    scope=ErrorScope.OBJECT_STORE,
                    operation="object_store.get.stream",
                ):
                    chunk = await self._call_sync(body.read, self._read_chunk_size)
                if not chunk:
                    return
                if not isinstance(chunk, bytes):
                    with foundation_failure_boundary(
                        scope=ErrorScope.OBJECT_STORE,
                        operation="object_store.get.response",
                    ):
                        raise TypeError("S3 streaming body returned a non-bytes chunk")
                yield chunk
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                with foundation_failure_boundary(
                    scope=ErrorScope.OBJECT_STORE,
                    operation="object_store.get.close",
                ):
                    await self._call_sync(close)

    async def stat(self, ref: ObjectRef) -> ObjectStat | None:
        client = await self._get_client()
        try:
            response = await self._call_sync(
                client.head_object,
                Bucket=self._bucket,
                Key=ref.key,
            )
        except ClientError as error:
            if self._is_not_found(error):
                return None
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    error,
                    scope=ErrorScope.OBJECT_STORE,
                    operation="object_store.stat",
                )
            ) from error
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    exc,
                    scope=ErrorScope.OBJECT_STORE,
                    operation="object_store.stat",
                )
            ) from exc
        with foundation_failure_boundary(
            scope=ErrorScope.OBJECT_STORE,
            operation="object_store.stat.response",
        ):
            return ObjectStat(ref=ref, metadata=self._stat_metadata(response))

    async def delete(self, ref: ObjectRef) -> bool:
        client = await self._get_client()
        try:
            await self._call_sync(
                client.delete_object,
                Bucket=self._bucket,
                Key=ref.key,
            )
        except ClientError as error:
            if self._is_not_found(error):
                return False
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    error,
                    scope=ErrorScope.OBJECT_STORE,
                    operation="object_store.delete",
                )
            ) from error
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    exc,
                    scope=ErrorScope.OBJECT_STORE,
                    operation="object_store.delete",
                )
            ) from exc
        self._record_io("delete", "success")
        return True

    async def signed_url(self, ref: ObjectRef, *, ttl_seconds: int | None = None) -> str:
        """Return a bounded presigned URL only when an explicit TTL is configured."""

        ttl = ttl_seconds if ttl_seconds is not None else self._signed_url_ttl_seconds
        if ttl is None:
            raise RuntimeError("signed URL policy is not configured")
        if ttl < 1 or ttl > 7 * 24 * 60 * 60:
            raise ValueError("signed URL TTL must be between one second and seven days")
        client = await self._get_client()
        try:
            value = await self._call_sync(
                client.generate_presigned_url,
                "get_object",
                Params={"Bucket": self._bucket, "Key": ref.key},
                ExpiresIn=ttl,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    exc,
                    scope=ErrorScope.OBJECT_STORE,
                    operation="object_store.signed_url",
                )
            ) from exc
        if not isinstance(value, str) or not value:
            raise FoundationAdapterError(
                foundation_error_from_exception(
                    TypeError("S3 presign returned a non-string URL"),
                    scope=ErrorScope.OBJECT_STORE,
                    operation="object_store.signed_url",
                )
            )
        return value

    def _record_io(self, operation: str, outcome: str) -> None:
        record = getattr(self._telemetry, "record_object_io", None)
        if callable(record):
            record(operation=operation, outcome=outcome)

    async def cleanup_orphan(self, request: OrphanCleanupRequest) -> OrphanCleanupResult:
        """Re-check authority before idempotently deleting an orphan candidate."""

        if request.metadata_committed or request.referenced:
            return OrphanCleanupResult(
                object_id=request.object_ref.object_id,
                action="retained",
                reason="metadata_committed_or_referenced",
            )
        if request.legal_hold:
            return OrphanCleanupResult(
                object_id=request.object_ref.object_id,
                action="retained",
                reason="legal_hold",
            )
        if self._orphan_grace_seconds is None:
            return OrphanCleanupResult(
                object_id=request.object_ref.object_id,
                action="deferred",
                reason="orphan_grace_policy_missing",
            )
        uploaded_at = request.uploaded_at
        if uploaded_at.tzinfo is None or uploaded_at.utcoffset() is None:
            raise ValueError("orphan uploaded_at must be timezone-aware")
        age_seconds = (datetime.now(UTC) - uploaded_at.astimezone(UTC)).total_seconds()
        if age_seconds < self._orphan_grace_seconds:
            return OrphanCleanupResult(
                object_id=request.object_ref.object_id,
                action="deferred",
                reason="orphan_grace_not_elapsed",
            )
        if await self.stat(request.object_ref) is None:
            return OrphanCleanupResult(
                object_id=request.object_ref.object_id,
                action="missing",
                reason="object_already_absent",
            )
        deleted = await self.delete(request.object_ref)
        return OrphanCleanupResult(
            object_id=request.object_ref.object_id,
            action="deleted" if deleted else "missing",
            reason="orphan_cleanup" if deleted else "object_already_absent",
        )

    async def aclose(self) -> None:
        """Close a lazily-created boto3 client when the composition root stops."""

        self._closed = True
        client = self._client
        close = getattr(client, "close", None)
        if callable(close):
            with foundation_failure_boundary(
                scope=ErrorScope.OBJECT_STORE,
                operation="object_store.close",
            ):
                await self._call_sync(close)

    async def _get_client(self) -> Any:
        if self._closed:
            raise RuntimeError("ObjectStore is closed")
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._closed:
                raise RuntimeError("ObjectStore is closed")
            if self._client is None:
                with foundation_failure_boundary(
                    scope=ErrorScope.OBJECT_STORE,
                    operation="object_store.client.create",
                ):
                    self._client = await self._call_sync(self._client_factory)
            return self._client

    async def _call_sync(self, operation: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        async with self._operations:
            return await asyncio.to_thread(operation, *args, **kwargs)

    def _upload_file(
        self,
        client: Any,
        path: Path,
        key: str,
        extra_args: Mapping[str, Any],
    ) -> None:
        # The worker owns this descriptor, so cancellation of the async waiter
        # cannot close a file still read by boto3.
        with path.open("rb") as file_object:
            client.upload_fileobj(
                file_object,
                self._bucket,
                key,
                ExtraArgs=dict(extra_args),
                Config=self._transfer_config,
            )

    @staticmethod
    def _remove_file(path: Path) -> None:
        path.unlink(missing_ok=True)

    @staticmethod
    def _is_not_found(error: ClientError) -> bool:
        response = error.response
        code = str(response.get("Error", {}).get("Code", ""))
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return status == 404 or code in {"404", "NoSuchKey", "NoSuchObject", "NotFound"}

    @staticmethod
    def _metadata_value(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def _upload_metadata(
        self,
        metadata: ContractPayload | None,
        content_hash: str,
        object_id: str,
    ) -> dict[str, str]:
        encoded = {
            _CONTENT_HASH_METADATA_KEY: content_hash,
            _OBJECT_ID_METADATA_KEY: object_id,
        }
        for key, value in (metadata or {}).items():
            normalized_key = key.lower()
            if normalized_key in _RESERVED_METADATA_KEYS:
                raise ValueError(f"metadata key {key!r} is reserved")
            encoded[key] = self._metadata_value(value)
        return encoded

    @staticmethod
    def _stat_metadata(response: Mapping[str, Any]) -> ContractPayload:
        metadata: ContractPayload = {
            "content_type": str(response.get("ContentType", "")),
            "size_bytes": int(response.get("ContentLength", 0)),
            "user_metadata": {
                str(key): str(value) for key, value in dict(response.get("Metadata", {})).items()
            },
        }
        e_tag = response.get("ETag")
        if isinstance(e_tag, str):
            metadata["e_tag"] = e_tag
        last_modified = response.get("LastModified")
        if isinstance(last_modified, datetime):
            metadata["last_modified"] = last_modified.isoformat()
        return metadata


__all__ = ["Boto3ObjectStore", "boto3_s3_client_factory", "minio_s3_client_factory"]
