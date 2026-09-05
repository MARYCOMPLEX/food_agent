"""Machine-checkable dependency and lockfile evidence for the foundation ADR."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (
    ROOT
    / "openspec"
    / "changes"
    / "define-modular-architecture"
    / "decisions"
    / "README.md"
)
LOCK = ROOT / "uv.lock"


def test_dependency_ledger_has_current_sources_versions_and_spikes() -> None:
    text = INDEX.read_text(encoding="utf-8")

    assert "rechecked on 2026-08-24" in text
    assert "`uv lock --check`" in text
    for required in (
        "Pydantic AI Slim | `2.5.1`",
        "Temporal Python SDK | `1.31.0`",
        "SQLAlchemy | `2.0.52`",
        "asyncpg | `0.31.0`",
        "Alembic | `1.19.1`",
        "redis-py | `7.4.0`",
        "boto3 | `1.43.75`",
        "OpenTelemetry API/SDK | `1.44.0`",
        "Prometheus client | `0.25.0`",
        "Pydantic Settings | `2.13.1`",
        "https://pydantic.dev/docs/ai/overview/",
        "https://docs.temporal.io/develop/python",
        "https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html",
        "https://alembic.sqlalchemy.org/en/latest/",
        "https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html",
        "https://boto3.amazonaws.com/v1/documentation/api/latest/guide/s3.html",
        "https://opentelemetry.io/docs/languages/python/instrumentation/",
        "Import/provider and disabled-binding contracts",
        "Three queue declarations",
        "Single-engine/UoW ownership",
    ):
        assert required in text


def test_lockfile_hash_and_runtime_versions_match_ledger() -> None:
    digest = hashlib.sha256(LOCK.read_bytes()).hexdigest()
    # The completed architecture baseline remains an accepted snapshot.  This
    # change adds the pinned OTLP/HTTP exporter and records its new snapshot in
    # the change-local baseline rather than mutating the completed change.
    assert digest in {
        "98e8c2b67e4d2d07a9d797cbc356b79686094fee238526b7745f049da1079e45",
        "6b069630590e63a74f44b80614406374aa999ce85345be48ed8da2573de9145e",
    }
    lock_text = LOCK.read_text(encoding="utf-8")
    assert "requires-python = \"==3.12.*\"" in lock_text

    expected = {
        "alembic": "1.19.1",
        "asyncpg": "0.31.0",
        "boto3": "1.43.75",
        "opentelemetry-api": "1.44.0",
        "prometheus-client": "0.25.0",
        "pydantic-ai-slim": "2.5.1",
        "pydantic-settings": "2.13.1",
        "redis": "7.4.0",
        "sqlalchemy": "2.0.52",
        "temporalio": "1.31.0",
    }
    for name, version in expected.items():
        assert re.search(
            rf"name = \"{re.escape(name)}\"\nversion = \"{re.escape(version)}\"",
            lock_text,
        )
