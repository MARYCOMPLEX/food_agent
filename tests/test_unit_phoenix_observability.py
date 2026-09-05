"""Contract tests for the optional Phoenix observation and evaluation plane."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from xhs_food.contracts import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationOutcome,
    ObservationKind,
    ObservationRecord,
)
from xhs_food.foundation import (
    BoundedObservationExporter,
    CapturingObservationBackend,
    DeterministicEvaluator,
    LLMJudgeRunner,
    NoopObservationPort,
    ObservationExportError,
    PhoenixEvaluationGateway,
    QueryReuseReadConfigView,
    TraceContext,
    evaluate_gate,
    extract_trace_context,
    inject_trace_context,
    observation_context,
    observed_operation,
    redact_telemetry,
    scrub_otel_record,
)

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.unit


def _record(identifier: str, *, attempt: int = 0) -> ObservationRecord:
    return ObservationRecord(
        observation_id=identifier,
        kind=ObservationKind.AGENT_RUN,
        name="agent.run",
        correlation={"task": "task-fixture", "attempt": attempt},
        attributes={"operation": "read", "classification": "public"},
    )


class _Backend:
    def __init__(self, *, fail_batches: int = 0, schema_isolating: bool = False) -> None:
        self.fail_batches = fail_batches
        self.schema_isolating = schema_isolating
        self.calls: list[tuple[ObservationRecord, ...]] = []
        self.closed = False

    async def export(self, records: tuple[ObservationRecord, ...]) -> None:
        self.calls.append(records)
        if self.fail_batches:
            self.fail_batches -= 1
            raise ObservationExportError("dependency_unavailable")
        if self.schema_isolating and len(records) > 1:
            raise ObservationExportError("schema_error")
        if self.schema_isolating and records[0].observation_id == "bad":
            raise ObservationExportError("schema_error")

    async def close(self) -> None:
        self.closed = True


class _Response:
    def __init__(
        self,
        status_code: int,
        *,
        body: object = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}

    def json(self) -> object:
        return self._body


class _Client:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)

    async def aclose(self) -> None:
        self.closed = True


def _dataset() -> EvaluationDataset:
    return EvaluationDataset(
        dataset_id="fixture",
        dataset_version="v1",
        cases=(
            EvaluationCase(
                case_id="case-1",
                input={"domain": "food"},
                expected={"route": "reuse"},
            ),
        ),
    )


def test_observation_contract_rejects_forbidden_fields_and_scrubs_automatic_values() -> None:
    with pytest.raises(ValidationError, match="unapproved observation attributes"):
        ObservationRecord(
            observation_id="bad",
            kind=ObservationKind.MODEL_CALL,
            name="model.call",
            attributes={"query": "private query"},
        )

    payload = scrub_otel_record(
        {
            "name": "GET /restaurants/123",
            "attributes": {
                "http.url": "https://example.test/a?token=TOKEN",
                "http.request.header.authorization": "Bearer TOKEN",
                "traceId": "trace-fixture",
                "status_code": 200,
            },
            "resource": {"service.name": "food-agent", "userId": "private-user"},
            "events": [
                {
                    "name": "exception",
                    "attributes": {
                        "exception.message": "private message",
                        "classification": "dependency_unavailable",
                    },
                }
            ],
        }
    )

    encoded = json.dumps(payload, ensure_ascii=True)
    assert "TOKEN" not in encoded
    assert "private-user" not in encoded
    assert "private message" not in encoded
    assert payload["attributes"]["status_code"] == 200  # type: ignore[index]
    assert payload["attributes"]["traceId"].startswith("sha256:")  # type: ignore[index]
    assert redact_telemetry({"userId": "private-user"}) == {}


def test_bounded_exporter_applies_sampling_drop_policy_batching_and_metrics() -> None:
    backend = CapturingObservationBackend()
    exporter = BoundedObservationExporter(
        backend,
        max_queue_size=2,
        max_batch_size=2,
        sampling_rate=1.0,
        drop_policy="drop_oldest",
    )
    assert exporter.observe(_record("one"))
    assert exporter.observe(_record("two"))
    assert exporter.observe(_record("three"))
    assert exporter.queue_size == 2

    assert asyncio.run(exporter.flush(1.0)) == "flushed"
    assert [record.observation_id for record in backend.records] == ["two", "three"]
    assert exporter.health()["saturated"] == 1
    assert exporter.health()["dropped"] == 1

    sampled = BoundedObservationExporter(backend, sampling_rate=0.0)
    assert sampled.observe(_record("never")) is False
    assert sampled.health()["dropped"] == 1


def test_exporter_retries_and_isolates_malformed_batch_records() -> None:
    retry_backend = _Backend(fail_batches=1)
    retry_exporter = BoundedObservationExporter(retry_backend, retry_limit=1)
    retry_exporter.observe(_record("retry"))
    assert asyncio.run(retry_exporter.flush(1.0)) == "flushed"
    assert len(retry_backend.calls) == 2
    assert retry_exporter.health()["exported"] == 1

    schema_backend = _Backend(schema_isolating=True)
    schema_exporter = BoundedObservationExporter(
        schema_backend,
        max_batch_size=2,
        retry_limit=0,
    )
    schema_exporter.observe(_record("bad"))
    schema_exporter.observe(_record("good"))
    assert asyncio.run(schema_exporter.flush(1.0)) == "failed"
    assert schema_exporter.health()["exported"] == 1
    assert schema_exporter.health()["failed"] == 1

    malformed = BoundedObservationExporter(schema_backend)
    assert malformed.observe({"malformed": True}) is False  # type: ignore[arg-type]
    assert malformed.health()["malformed"] == 1


def test_shutdown_flush_is_bounded_and_noop_backend_is_replaceable() -> None:
    class SlowBackend(_Backend):
        async def export(self, records: tuple[ObservationRecord, ...]) -> None:
            del records
            await asyncio.sleep(0.2)

    slow = BoundedObservationExporter(
        SlowBackend(),
        export_timeout_ms=10,
        shutdown_flush_timeout_ms=20,
        retry_limit=0,
    )
    slow.observe(_record("slow"))
    result = asyncio.run(slow.aclose())
    assert result in {"failed", "timed_out"}
    assert slow.health()["status"] == "closed"

    noop = NoopObservationPort()
    assert noop.observe(_record("ignored")) is False
    assert asyncio.run(noop.flush()) == "skipped"
    assert noop.health()["dropped"] == 1


def test_trace_context_is_w3c_valid_and_attempts_are_bounded() -> None:
    with observation_context(seed="research", attempt=2) as parent:
        carrier: dict[str, str] = {}
        inject_trace_context(carrier)
        extracted = extract_trace_context(carrier)
        assert extracted is not None
        assert extracted.trace_id == parent.trace_id
        assert extracted.span_id == parent.span_id
        assert extracted.attempt == 2

        with observation_context(seed="activity") as child:
            assert child.trace_id == parent.trace_id
            assert child.parent_span_id == parent.span_id
            assert child.attempt == 2

    assert extract_trace_context({"traceparent": "00-" + "0" * 32 + "-" + "1" * 16 + "-01"}) is None
    assert extract_trace_context({"traceparent": "01-" + "1" * 32 + "-" + "2" * 16 + "-01"}) is None
    assert TraceContext("1" * 32, "2" * 16).child("attempt", attempt=-1).attempt == 0


@pytest.mark.asyncio
async def test_observed_operation_preserves_context_and_records_errors() -> None:
    backend = CapturingObservationBackend()
    port = BoundedObservationExporter(backend)
    async with observed_operation(
        port,
        observation_id="ok-operation",
        kind=ObservationKind.CONNECTOR_CALL,
        name="connector.call",
        correlation={"connector": "fixture"},
    ):
        pass
    with pytest.raises(RuntimeError):
        async with observed_operation(
            port,
            observation_id="failed-operation",
            kind=ObservationKind.CONNECTOR_CALL,
            name="connector.call",
        ):
            raise RuntimeError("fixture")
    await port.flush(1.0)
    assert [record.outcome.value for record in backend.records] == ["ok", "error"]


def test_evaluation_artifacts_are_deterministic_immutable_and_private_safe() -> None:
    dataset = _dataset()
    evaluator = DeterministicEvaluator()
    first = evaluator.evaluate(dataset, {"case-1": {"route": "reuse"}}, configuration={"mode": "test"})
    second = evaluator.evaluate(dataset, {"case-1": {"route": "reuse"}}, configuration={"mode": "test"})
    assert first.result_digest == second.result_digest
    assert first.results[0].outcome == "pass"
    with pytest.raises(TypeError, match="immutable"):
        first.results[0].details["new"] = "value"  # type: ignore[index]
    with pytest.raises(ValidationError, match="private field"):
        EvaluationCase(case_id="private", input={"userId": "secret"})
    with pytest.raises(ValidationError, match="private field"):
        EvaluationCase(case_id="secret", input={"accountState": "private"})


@pytest.mark.asyncio
async def test_llm_judge_metadata_and_gate_statuses_are_explicit() -> None:
    async def judge(case: EvaluationCase) -> dict[str, object]:
        return {"outcome": "pass", "score": 1.0, "details": {"case": case.case_id}}

    dataset = _dataset()
    run = await LLMJudgeRunner(
        judge,
        provider="fixture-provider",
        model_version="fixture-model-v1",
        rubric_version="rubric-v1",
        template_version="template-v1",
    ).evaluate(dataset, configuration={"mode": "test"})
    assert run.outcome is EvaluationOutcome.PASS
    assert run.provider == "fixture-provider"
    assert run.template_version == "template-v1"

    expiry = datetime.now(UTC) + timedelta(hours=1)
    passed = evaluate_gate(
        milestone="b2",
        dataset=dataset,
        run=run,
        thresholds={"minimum_pass_rate": 1.0},
        code_revision="fixture-revision",
        evaluator_version=run.evaluator_version,
        approval_id="approval-1",
        expires_at=expiry,
    )
    assert passed.report is EvaluationOutcome.PASS

    blocked = evaluate_gate(
        milestone="b2",
        dataset=dataset,
        run=run,
        thresholds={},
        code_revision="fixture-revision",
        evaluator_version=run.evaluator_version,
    )
    assert blocked.report is EvaluationOutcome.BLOCKED

    missing_evidence = evaluate_gate(
        milestone="observability",
        dataset=dataset,
        run=run,
        thresholds={"minimum_pass_rate": 1.0},
        code_revision="fixture-revision",
        evaluator_version=run.evaluator_version,
        approval_id="approval-1",
        expires_at=expiry,
        phoenix_evidence_required=True,
    )
    assert missing_evidence.report is EvaluationOutcome.BLOCKED


@pytest.mark.asyncio
async def test_phoenix_gateway_maps_status_schema_version_and_lifecycle() -> None:
    version = {"x-phoenix-api-version": "v1"}
    client = _Client([_Response(429, body={}, headers=version), _Response(200, body={}, headers=version)])
    gateway = PhoenixEvaluationGateway(
        "http://localhost:6006",
        client=client,
        retry_limit=1,
    )
    assert await gateway.submit_dataset(_dataset()) is True
    assert len(client.calls) == 2
    assert client.calls[0]["url"] == "http://localhost:6006/v1/datasets"
    assert client.calls[0]["headers"]["x-phoenix-api-version"] == "v1"

    bad_version = _Client([_Response(200, body={}, headers={"x-phoenix-api-version": "v2"})])
    mismatch = PhoenixEvaluationGateway("http://localhost:6006", client=bad_version)
    assert await mismatch.submit_dataset(_dataset()) is False
    assert mismatch.health()["last_error"] == "version_mismatch"

    bad_schema = _Client([_Response(200, body="not-json", headers=version)])
    schema = PhoenixEvaluationGateway("http://localhost:6006", client=bad_schema)
    assert await schema.submit_dataset(_dataset()) is False
    assert schema.health()["last_error"] == "schema_error"

    run = DeterministicEvaluator().evaluate(_dataset(), {"case-1": {"route": "reuse"}})
    run_client = _Client([_Response(401, body={}, headers=version)])
    auth = PhoenixEvaluationGateway("http://localhost:6006", client=run_client, retry_limit=0)
    assert await auth.submit_run(run) is False
    assert auth.health()["last_error"] == "authorization"
    assert "authorization" not in json.dumps(run_client.calls[0]["json"])
    assert run_client.calls[0]["url"] == "http://localhost:6006/v1/experiments"

    assert await auth.close() == "closed"
    assert await auth.close() == "closed"


def test_compose_phoenix_profile_is_optional_and_storage_isolated() -> None:
    release = yaml.safe_load((ROOT / "docker-compose.release.yml").read_text(encoding="utf-8"))
    legacy = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = release["services"]
    assert "phoenix" not in legacy.get("services", {})
    assert services["phoenix"]["profiles"] == ["phoenix"]
    assert services["phoenix-postgres"]["profiles"] == ["phoenix"]
    assert "sha256:41489a3f4f04310545393d0000cd950f35fad71060bd676d937f0afad379e8f9" in services[
        "phoenix"
    ]["image"]
    assert "release_phoenix_postgres_data:/var/lib/postgresql/data" in services[
        "phoenix-postgres"
    ]["volumes"]
    assert services["phoenix"]["depends_on"]["phoenix-postgres"]["condition"] == "service_healthy"
    assert services["phoenix"]["networks"] == ["phoenix-observability"]
    assert services["phoenix-postgres"]["networks"] == ["phoenix-observability"]
    assert release["networks"]["phoenix-observability"]["name"] == (
        "food-agent-release-phoenix-observability"
    )


def test_configuration_views_are_immutable_and_fail_closed() -> None:
    view = QueryReuseReadConfigView(mode="off", sample_rate=0.0, minimum_coverage={"food": 0.8})
    with pytest.raises(TypeError, match="immutable"):
        view.minimum_coverage["food"] = 0.9
