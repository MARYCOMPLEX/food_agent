"""Offline S3 contract tests for Composition target bindings and owner config."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from xhs_food.composition import DisabledBindingError, build_composition_root
from xhs_food.composition.adapters import build_owner_config
from xhs_food.config import Settings
from xhs_food.foundation import Boto3ObjectStore, TargetSettings


@pytest.mark.unit
def test_target_settings_validate_task_queues_and_owner_views_are_read_only() -> None:
    target = TargetSettings(
        target_adapters_enabled=False,
        database_url="postgresql://target/database",
        temporal_research_queue="research",
        temporal_refresh_queue="refresh",
        temporal_media_queue="media",
    )
    legacy = Settings(
        database_url="postgresql://legacy/database",
        redis_url="redis://localhost:6379/0",
        openai_api_key="legacy-secret",
    )
    owner = build_owner_config(legacy, target)

    assert owner.repositories.target_database_url == "postgresql://target/database"
    assert owner.repositories.legacy_database_url == "postgresql://legacy/database"
    assert owner.temporal.enabled is False
    assert owner.redis.session_window_size == 20
    assert owner.redis.event_stream_ttl_seconds == 3_600
    assert owner.redis.event_stream_maxlen == 1_000
    with pytest.raises(ValidationError, match="frozen"):
        owner.temporal.address = "other:7233"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        owner.temporal = owner.temporal  # type: ignore[misc]
    with pytest.raises(ValidationError, match="distinct"):
        TargetSettings(
            temporal_research_queue="same",
            temporal_refresh_queue="same",
            temporal_media_queue="media",
        )


@pytest.mark.unit
async def test_composition_keeps_optional_target_bindings_disabled() -> None:
    root = build_composition_root()
    try:
        target = root.registries["target_foundation"].bindings
        assert set(target) == {
            "sqlalchemy",
            "temporal",
            "temporal_activities",
            "object_store",
            "redis_contract",
            "observability",
        }
        assert all(not binding.enabled and not binding.legacy for binding in target.values())
        with pytest.raises(DisabledBindingError, match="target_foundation.temporal"):
            await root.resolve("target_foundation", "temporal")
    finally:
        await root.close()


@pytest.mark.unit
async def test_object_store_target_factory_passes_minio_settings_without_creating_a_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def capture_minio_factory(cls: type[Boto3ObjectStore], **kwargs: object) -> object:
        captured["class"] = cls
        captured.update(kwargs)
        return object()

    monkeypatch.setenv("MODULAR_OBJECT_STORE_ENDPOINT_URL", "http://minio.test:9000")
    monkeypatch.setenv("MODULAR_OBJECT_STORE_ACCESS_KEY", "minio-access")
    monkeypatch.setenv("MODULAR_OBJECT_STORE_SECRET_KEY", "minio-secret")
    monkeypatch.setenv("MODULAR_OBJECT_STORE_REGION", "minio-region")
    monkeypatch.setenv("MODULAR_OBJECT_STORE_BUCKET", "media")
    monkeypatch.setenv("MODULAR_OBJECT_STORE_MAX_CONCURRENCY", "3")
    monkeypatch.setenv("MODULAR_OBJECT_STORE_MULTIPART_THRESHOLD", str(5 * 1024 * 1024))
    monkeypatch.setattr(
        Boto3ObjectStore,
        "for_minio",
        classmethod(capture_minio_factory),
    )

    root = build_composition_root()
    try:
        binding = root.registries["target_foundation"].bindings["object_store"]
        assert binding.enabled is False
        assert captured == {}
        binding.factory()
        assert captured == {
            "class": Boto3ObjectStore,
            "bucket": "media",
            "endpoint_url": "http://minio.test:9000",
            "access_key_id": "minio-access",
            "secret_access_key": "minio-secret",
            "region_name": "minio-region",
            "max_concurrency": 3,
            "multipart_threshold": 5 * 1024 * 1024,
        }
    finally:
        await root.close()
