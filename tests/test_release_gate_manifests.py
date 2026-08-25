"""Static checks for the blocking release image and full-stack manifest."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.unit


def test_release_dockerfile_is_python312_and_non_root() -> None:
    text = (ROOT / "Dockerfile.release").read_text(encoding="utf-8")
    assert "FROM python:3.12-slim AS builder" in text
    assert "FROM python:3.12-slim AS runtime" in text
    assert "USER app" in text
    assert "uv sync --no-dev --frozen" in text
    assert "COPY src/ /app/src/" in text
    assert "CREATE TABLE" not in text
    assert "CMD [\"uvicorn\", \"api.main:app\"" in text


def test_release_compose_declares_all_authority_services_and_healthchecks() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.release.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert {
        "app",
        "migrate",
        "postgres",
        "redis",
        "temporal",
        "minio",
        "research-queue-smoke",
        "refresh-queue-smoke",
        "media-queue-smoke",
    } <= set(services)
    for service in ("app", "postgres", "redis", "temporal", "minio"):
        assert "healthcheck" in services[service]
    assert services["app"]["environment"]["EVENT_BUS_BACKEND"] == "redis"
    assert services["app"]["environment"]["MODULAR_TEMPORAL_ADDRESS"] == "temporal:7233"
    assert services["app"]["environment"]["MODULAR_OBJECT_STORE_ENDPOINT_URL"] == "http://minio:9000"
    assert services["migrate"]["command"] == ["alembic", "upgrade", "head"]
    assert services["app"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert {
        services[name]["environment"]["QUEUE"]
        for name in ("research-queue-smoke", "refresh-queue-smoke", "media-queue-smoke")
    } == {"research", "refresh", "media"}
    assert services["refresh-queue-smoke"]["depends_on"]["research-queue-smoke"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["media-queue-smoke"]["depends_on"]["refresh-queue-smoke"]["condition"] == (
        "service_completed_successfully"
    )


def test_release_database_init_keeps_application_schema_with_alembic() -> None:
    text = (ROOT / "scripts" / "init_release_db.sql").read_text(encoding="utf-8")
    assert "CREATE DATABASE temporal;" in text
    assert "CREATE DATABASE temporal_visibility;" in text
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in text
    assert "CREATE TABLE" not in text
