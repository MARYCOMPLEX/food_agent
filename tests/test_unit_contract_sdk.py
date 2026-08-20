"""Focused tests for the framework-neutral S1 contract SDK."""

from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from xhs_food.contracts import (
    ActivityPort,
    CachePort,
    CanonicalQuery,
    CanonicalSourceBatch,
    CanonicalSourceDocument,
    CollectRequest,
    ContractError,
    ErrorCategory,
    ErrorScope,
    EventBusPort,
    LLMProvider,
    ModelGateway,
    ObjectStore,
    Repository,
    RequestIdentity,
    RequestPolicy,
    ResearchOperation,
    ResearchRequest,
    SchemaVersion,
    SourceAttemptMetadata,
    SourceAttemptOutcome,
    SourceConnector,
    SourceCoverageMetadata,
    TaskProgressProjection,
    TaskStatus,
    ToolGateway,
    WorkflowPort,
)

NOW = datetime(2026, 8, 19, tzinfo=UTC)
AUTHORITY = Path(__file__).parent / "fixtures" / "authority"


def test_schema_version_is_explicit_and_rejects_ambiguous_values() -> None:
    assert str(SchemaVersion("1.0")) == "1.0"
    with pytest.raises(ValidationError):
        SchemaVersion("v1")
    with pytest.raises(ValidationError):
        SchemaVersion("1")


def test_research_request_operations_are_versioned_and_json_round_trip() -> None:
    for operation in ResearchOperation:
        request = ResearchRequest(
            request_id=f"request-{operation.value}",
            operation=operation,
            domain="fixture-domain",
            query="fixture query",
            identity=RequestIdentity(session_ref="session-1"),
            policy=RequestPolicy(policy_version="policy-1", compatibility_version="api-1"),
        )
        payload = request.model_dump_json()
        assert json.loads(payload)["schema_version"] == "1.0"
        assert ResearchRequest.model_validate_json(payload) == request


def test_task_progress_projection_cannot_be_an_execution_checkpoint() -> None:
    projection = TaskProgressProjection(
        task_id="task-1",
        status=TaskStatus.RUNNING,
        progress=0.5,
        workflow_id="workflow-1",
        run_id="run-1",
        updated_at=NOW,
    )
    assert projection.executable_checkpoint is False
    assert projection.projection_kind == "business_query_only"
    with pytest.raises(ValidationError):
        TaskProgressProjection.model_validate(
            {**projection.model_dump(), "executable_checkpoint": True}
        )


def test_stable_error_classification_is_serializable() -> None:
    error = ContractError(
        code="SOURCE_TIMEOUT",
        category=ErrorCategory.TIMEOUT,
        scope=ErrorScope.SOURCE,
        retryable=True,
        boundary_ref="source-fixture",
    )
    dumped = error.model_dump(mode="json")
    assert dumped["category"] == "timeout"
    assert dumped["scope"] == "source"
    assert ContractError.model_validate(dumped) == error


def test_canonical_query_signature_has_no_identity_or_personal_fields() -> None:
    fixture = json.loads((AUTHORITY / "canonical_query_v1.json").read_text(encoding="utf-8"))
    query = CanonicalQuery.model_validate(fixture)
    payload = query.model_dump(mode="json")
    assert {"user_id", "session_id", "preferences"}.isdisjoint(payload)
    assert set(CanonicalQuery.model_fields) == {
        "schema_version",
        "normalizer_version",
        "classifier_version",
        "isolation",
        "query",
    }

    private = copy.deepcopy(fixture)
    private["user_id"] = "must-be-rejected"
    with pytest.raises(ValidationError):
        CanonicalQuery.model_validate(private)


def test_canonical_source_batch_contains_metadata_but_rejects_binary() -> None:
    batch = CanonicalSourceBatch(
        isolation={"tenant_scope": "public", "language": "en", "region": "US"},
        source_id="fixture-source",
        connector_id="fixture.connector",
        connector_version="fixture-connector/v1",
        normalizer_version="fixture-normalizer/v1",
        documents=(
            CanonicalSourceDocument(
                source_id="fixture-source",
                external_id="document-1",
                canonical_url="https://fixture.invalid/document-1",
                captured_at=NOW,
                text="fixture text",
            ),
        ),
        watermark=None,
    )
    assert CanonicalSourceBatch.model_validate_json(batch.model_dump_json()) == batch
    with pytest.raises(ValidationError):
        CanonicalSourceDocument(
            source_id="fixture-source",
            external_id="document-2",
            canonical_url="https://fixture.invalid/document-2",
            captured_at=NOW,
            attributes={"binary": b"not-allowed"},
        )


def test_source_coverage_is_typed_without_claiming_a_business_threshold() -> None:
    coverage = SourceCoverageMetadata(
        eligible_item_count=0,
        attempts=(
            SourceAttemptMetadata(
                attempt_id="fixture-empty",
                boundary_ref="fixture.connector",
                outcome=SourceAttemptOutcome.SUCCESS_EMPTY,
                item_count=0,
                watermark="source-watermark",
            ),
        ),
    )
    batch = CanonicalSourceBatch.model_validate(
        {
            "isolation": {
                "tenant_scope": "public",
                "language": "en",
                "region": "US",
            },
            "source_id": "fixture-source",
            "connector_id": "fixture.connector",
            "connector_version": "fixture-connector/v1",
            "normalizer_version": "fixture-normalizer/v1",
            "watermark": "source-watermark",
            "coverage": coverage,
        }
    )

    payload = batch.model_dump(mode="json")
    assert payload["coverage"] == {
        "eligible_item_count": 0,
        "attempts": [
            {
                "attempt_id": "fixture-empty",
                "boundary_ref": "fixture.connector",
                "outcome": "success_empty",
                "item_count": 0,
                "watermark": "source-watermark",
                "error_indexes": [],
            }
        ],
    }
    assert {"minimum", "threshold", "satisfied", "ratio"}.isdisjoint(payload["coverage"])
    assert CanonicalSourceBatch.model_validate(payload) == batch

    with pytest.raises(ValidationError, match="eligible_item_count"):
        CanonicalSourceBatch.model_validate(
            {
                **payload,
                "coverage": {**payload["coverage"], "eligible_item_count": 1},
            }
        )

    with pytest.raises(ValidationError, match="outcome"):
        SourceAttemptMetadata(
            attempt_id="invalid-empty",
            boundary_ref="fixture.connector",
            outcome=SourceAttemptOutcome.FAILURE,
            item_count=0,
        )


def test_collect_request_accepts_only_in_scope_source_query_projections() -> None:
    query = CanonicalQuery.model_validate(
        json.loads((AUTHORITY / "canonical_query_v1.json").read_text(encoding="utf-8"))
    )
    request = CollectRequest.model_validate(
        {
            "query": query,
            "source_scope": ["xhs"],
            "source_queries": {
                "xhs": {
                    "source_id": "xhs",
                    "text": "自贡 美食",
                    "language": "zh-Hans",
                    "renderer_id": "food.xhs",
                    "renderer_version": "source-query/v1",
                    "locality": "自贡",
                }
            },
            "depth": "standard",
        }
    )

    assert request.source_queries["xhs"].text == "自贡 美食"
    assert request.source_queries["xhs"].language == "zh-Hans"
    assert CollectRequest.model_validate_json(request.model_dump_json()) == request
    with pytest.raises(ValidationError, match="outside source_scope"):
        CollectRequest.model_validate(
            {
                **request.model_dump(),
                "source_queries": {
                    "amap": {
                        "source_id": "amap",
                        "text": "自贡 餐厅",
                        "language": "zh-Hans",
                        "renderer_id": "food.amap",
                        "renderer_version": "source-query/v1",
                    }
                },
            }
        )
    with pytest.raises(ValidationError, match="language must match"):
        CollectRequest.model_validate(
            {
                **request.model_dump(),
                "source_queries": {
                    "xhs": {
                        "source_id": "xhs",
                        "text": "Zigong food",
                        "language": "en",
                        "renderer_id": "food.xhs",
                        "renderer_version": "source-query/v1",
                    }
                },
            }
        )
    with pytest.raises(ValidationError, match="source_id must match"):
        CollectRequest.model_validate(
            {
                **request.model_dump(),
                "source_queries": {
                    "xhs": {
                        "source_id": "amap",
                        "text": "自贡 美食",
                        "language": "zh-Hans",
                        "renderer_id": "food.xhs",
                        "renderer_version": "source-query/v1",
                    }
                },
            }
        )


def test_contract_ports_are_structural_protocols() -> None:
    for port in (
        ActivityPort,
        SourceConnector,
        ToolGateway,
        Repository,
        WorkflowPort,
        CachePort,
        EventBusPort,
        ObjectStore,
        LLMProvider,
        ModelGateway,
    ):
        assert getattr(port, "_is_protocol", False) is True
        assert getattr(port, "_is_runtime_protocol", False) is True

    assert "lock" not in CachePort.__dict__
    assert "lease" not in CachePort.__dict__


def test_contract_import_does_not_load_legacy_or_infrastructure_modules() -> None:
    source_root = Path(__file__).parents[1] / "src"
    script = """
import json
import sys
import xhs_food.contracts

forbidden = {
    'fastapi',
    'asyncpg',
    'redis',
    'xhs_food.orchestrator',
    'xhs_food.schemas',
    'xhs_food.services',
    'xhs_food.spider',
}
print(json.dumps(sorted(forbidden.intersection(sys.modules))))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root)
    output = subprocess.check_output(
        [sys.executable, "-c", script],
        cwd=source_root.parent,
        env=env,
        text=True,
    )
    assert json.loads(output) == []


def test_legacy_root_exports_remain_the_original_objects() -> None:
    import xhs_food
    from xhs_food.orchestrator import XHSFoodOrchestrator
    from xhs_food.schemas import FoodSearchIntent

    assert xhs_food.XHSFoodOrchestrator is XHSFoodOrchestrator
    assert xhs_food.FoodSearchIntent is FoodSearchIntent


def test_contract_package_has_no_framework_sdk_database_or_domain_imports() -> None:
    contracts_dir = Path(__file__).parents[1] / "src/xhs_food/contracts"
    forbidden_roots = {
        "api",
        "asyncpg",
        "boto3",
        "fastapi",
        "langchain",
        "mcp",
        "redis",
        "sqlalchemy",
        "temporalio",
    }
    forbidden_xhs_modules = {
        "xhs_food.agents",
        "xhs_food.orchestrator",
        "xhs_food.providers",
        "xhs_food.schemas",
        "xhs_food.services",
        "xhs_food.spider",
    }

    violations: list[str] = []
    for path in sorted(contracts_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if name.split(".", 1)[0] in forbidden_roots or any(
                    name == module or name.startswith(f"{module}.")
                    for module in forbidden_xhs_modules
                ):
                    violations.append(f"{path.name}: {name}")

    assert violations == []
