"""Phoenix evaluation gateway and reproducible evaluation runners.

Only this Foundation module knows the Phoenix HTTP shape. Repository-owned
evaluation records remain the source of truth; Phoenix receives a redacted
projection and never receives business database credentials or write authority.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import inspect
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from time import monotonic
from typing import Any, cast
from urllib.parse import urlparse

from xhs_food.contracts import (
    ContractPayload,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationDataset,
    EvaluationGate,
    EvaluationOutcome,
    EvaluationPort,
    EvaluationRun,
    NoopEvaluationPort,
    configuration_digest,
)

_PRIVATE_KEYS = frozenset(
    {
        "user",
        "user_id",
        "session",
        "session_id",
        "preference",
        "preferences",
        "memory",
        "prompt",
        "query",
        "output",
        "token",
        "cookie",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "secrets",
        "url",
        "source_url",
        "signed_url",
        "body",
        "header",
        "headers",
        "qr",
        "qr_data",
        "account",
        "account_state",
        "note",
        "private",
        "private_value",
        "private_data",
        "raw",
        "raw_text",
        "note_text",
    }
)
_MISSING = object()


class PhoenixGatewayError(RuntimeError):
    """Stable, bounded error returned by the Phoenix gateway."""

    def __init__(
        self,
        classification: str,
        message: str = "",
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        self.classification = classification
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(message or classification)


class PhoenixEvaluationGateway(EvaluationPort):
    """Bounded HTTP adapter for Phoenix dataset and evaluation projections."""

    def __init__(
        self,
        endpoint: str,
        *,
        api_version: str = "v1",
        token: str | None = None,
        timeout_ms: int = 10_000,
        retry_limit: int = 2,
        verify_tls: bool = True,
        client: Any | None = None,
        dataset_path: str = "/v1/datasets",
        run_path: str = "/v1/experiments",
    ) -> None:
        _validate_endpoint(endpoint, verify_tls=verify_tls)
        if not api_version or any(character.isspace() for character in api_version):
            raise ValueError("Phoenix API version must be a non-empty token")
        if timeout_ms < 1 or timeout_ms > 300_000:
            raise ValueError("Phoenix timeout must be between 1 and 300000 milliseconds")
        if retry_limit < 0 or retry_limit > 10:
            raise ValueError("Phoenix retry limit must be between 0 and 10")
        if not dataset_path.startswith("/") or not run_path.startswith("/"):
            raise ValueError("Phoenix API paths must be absolute")
        if token is not None and (
            len(token) > 4096 or any(ord(character) < 32 for character in token)
        ):
            raise ValueError("Phoenix token must be bounded and free of control characters")
        self.endpoint = endpoint.rstrip("/")
        self.api_version = api_version
        self._token = token
        self._timeout_seconds = timeout_ms / 1000.0
        self._retry_limit = retry_limit
        self._verify_tls = verify_tls
        self._client = client
        self._owned_client = False
        self._dataset_path = dataset_path
        self._run_path = run_path
        self._closed = False
        self._last_error: str | None = None
        self._last_status: int | None = None
        self._submitted_datasets = 0
        self._submitted_runs = 0
        self._failed_requests = 0

    async def submit_dataset(self, dataset: EvaluationDataset) -> bool:
        try:
            validated = EvaluationDataset.model_validate(dataset)
        except Exception:
            self._record_failure("schema_error", None)
            return False
        payload = project_evaluation_dataset(validated)
        success = await self._post(self._dataset_path, payload)
        if success:
            self._submitted_datasets += 1
        return success

    async def submit_run(self, run: EvaluationRun) -> bool:
        try:
            validated = EvaluationRun.model_validate(run)
        except Exception:
            self._record_failure("schema_error", None)
            return False
        payload = project_evaluation_run(validated)
        success = await self._post(self._run_path, payload)
        if success:
            self._submitted_runs += 1
        return success

    async def _post(self, path: str, payload: Mapping[str, object]) -> bool:
        if self._closed:
            self._record_failure("closed", None)
            return False
        client = self._client
        if client is None:
            try:
                httpx = importlib.import_module("httpx")
                client = httpx.AsyncClient(
                    timeout=self._timeout_seconds,
                    verify=self._verify_tls,
                )
            except Exception:
                self._record_failure("dependency_unavailable", None)
                return False
            self._client = client
            self._owned_client = True

        deadline = monotonic() + self._timeout_seconds
        for attempt in range(self._retry_limit + 1):
            remaining = deadline - monotonic()
            if remaining <= 0:
                self._record_failure("timeout", None)
                return False
            try:
                response = await asyncio.wait_for(
                    client.post(
                        self._url_for(path),
                        json=dict(payload),
                        headers=self._headers(),
                    ),
                    timeout=remaining,
                )
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                self._record_failure("timeout", None)
                if attempt < self._retry_limit:
                    continue
                return False
            except Exception:
                self._record_failure("dependency_unavailable", None)
                if attempt < self._retry_limit:
                    continue
                return False

            status = int(getattr(response, "status_code", 0))
            self._last_status = status
            classification = _status_classification(status)
            if classification is not None:
                self._record_failure(classification, status)
                if (status in {429} or status >= 500) and attempt < self._retry_limit:
                    continue
                return False
            if not _response_version_matches(response, self.api_version):
                self._record_failure("version_mismatch", status)
                return False
            if not _response_schema_is_valid(response):
                self._record_failure("schema_error", status)
                return False
            self._last_error = None
            return True
        return False

    def _url_for(self, path: str) -> str:
        # Accept either a Phoenix root or an API root ending in /v1.
        if self.endpoint.endswith(path.rsplit("/", 1)[0]):
            return self.endpoint + "/" + path.rsplit("/", 1)[-1]
        return self.endpoint + path

    def _headers(self) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-phoenix-api-version": self.api_version,
        }
        if self._token:
            headers["authorization"] = f"Bearer {self._token}"
        return headers

    def _record_failure(self, classification: str, status: int | None) -> None:
        self._last_error = classification
        self._last_status = status
        self._failed_requests += 1

    async def flush(self, deadline_seconds: float | None = None) -> str:
        del deadline_seconds
        return "closed" if self._closed else "skipped"

    async def close(self) -> str:
        if self._closed:
            return "closed"
        self._closed = True
        if self._owned_client and self._client is not None:
            try:
                await asyncio.wait_for(self._client.aclose(), timeout=self._timeout_seconds)
            except Exception:
                self._record_failure("dependency_unavailable", None)
            self._client = None
        return "closed"

    def health(self) -> ContractPayload:
        payload: ContractPayload = {
            "status": "closed" if self._closed else ("unhealthy" if self._last_error else "ready"),
            "api_version": self.api_version,
            "submitted_datasets": self._submitted_datasets,
            "submitted_runs": self._submitted_runs,
            "failed_requests": self._failed_requests,
        }
        if self._last_status is not None:
            payload["last_status"] = self._last_status
        if self._last_error is not None:
            payload["last_error"] = self._last_error
        return payload


# Compatibility aliases keep the gateway name independent of the deployment.
PhoenixEvaluationAdapter = PhoenixEvaluationGateway
PhoenixEvalGateway = PhoenixEvaluationGateway


def build_evaluation_port(
    *,
    endpoint: str | None,
    enabled: bool,
    api_version: str = "v1",
    token: str | None = None,
    timeout_ms: int = 10_000,
    retry_limit: int = 2,
    verify_tls: bool = True,
    client: Any | None = None,
) -> EvaluationPort:
    if not enabled:
        return NoopEvaluationPort()
    if not endpoint:
        return NoopEvaluationPort(reason="endpoint_missing")
    return PhoenixEvaluationGateway(
        endpoint,
        api_version=api_version,
        token=token,
        timeout_ms=timeout_ms,
        retry_limit=retry_limit,
        verify_tls=verify_tls,
        client=client,
    )


def project_evaluation_dataset(dataset: EvaluationDataset) -> ContractPayload:
    """Build the only dataset shape allowed to leave the repository boundary."""

    return cast(ContractPayload, {
        "schema_version": dataset.schema_version,
        "dataset_id": dataset.dataset_id,
        "dataset_version": dataset.dataset_version,
        "redaction_version": dataset.redaction_version,
        "digest": dataset.digest,
        "cases": [
            {
                "case_id": case.case_id,
                "input": _public_projection(case.input),
                "expected": _public_projection(case.expected),
                "tags": list(case.tags),
            }
            for case in dataset.cases
        ],
    })


def project_evaluation_run(run: EvaluationRun) -> ContractPayload:
    """Project a run without timestamps, approvals, or private output values."""

    return cast(ContractPayload, {
        "schema_version": run.schema_version,
        "run_id": run.run_id,
        "dataset_id": run.dataset_id,
        "dataset_digest": run.dataset_digest,
        "evaluator_version": run.evaluator_version,
        "configuration_digest": run.configuration_digest,
        "result_digest": run.result_digest,
        "outcome": run.outcome.value,
        "provider": run.provider,
        "model_version": run.model_version,
        "rubric_version": run.rubric_version,
        "template_version": run.template_version,
        "results": [
            {
                "case_id": result.case_id,
                "outcome": result.outcome,
                "evaluator_version": result.evaluator_version,
                "score": result.score,
                "details": _public_projection(result.details),
            }
            for result in run.results
        ],
    })


class DeterministicEvaluator:
    """Exact JSON evaluator that stores only bounded digests in results."""

    version = "deterministic-exact/v1"

    def __init__(self, *, evaluator_version: str = version) -> None:
        if not evaluator_version or any(character.isspace() for character in evaluator_version):
            raise ValueError("evaluator version must be a non-empty token")
        self.evaluator_version = evaluator_version

    def evaluate_case(self, case: EvaluationCase, actual: object = _MISSING) -> EvaluationCaseResult:
        if actual is _MISSING or case.expected is None:
            return EvaluationCaseResult(
                case_id=case.case_id,
                outcome="blocked",
                evaluator_version=self.evaluator_version,
                details={"reason": "missing_expected_or_actual"},
            )
        _reject_private_values(actual, "actual")
        expected_digest = _digest_public(case.expected)
        actual_digest = _digest_public(actual)
        matches = _canonical_json(case.expected) == _canonical_json(actual)
        return EvaluationCaseResult(
            case_id=case.case_id,
            outcome="pass" if matches else "fail",
            evaluator_version=self.evaluator_version,
            score=1.0 if matches else 0.0,
            details={
                "comparison": "exact_json",
                "expected_digest": expected_digest,
                "actual_digest": actual_digest,
            },
        )

    def evaluate(
        self,
        dataset: EvaluationDataset,
        actuals: Mapping[str, object] | Callable[[EvaluationCase], object],
        *,
        configuration: object = None,
        run_id: str | None = None,
        created_at: datetime | None = None,
    ) -> EvaluationRun:
        results: list[EvaluationCaseResult] = []
        for case in dataset.cases:
            try:
                actual = actuals(case) if callable(actuals) else actuals.get(case.case_id, _MISSING)
                result = self.evaluate_case(case, actual)
            except Exception:
                result = EvaluationCaseResult(
                    case_id=case.case_id,
                    outcome="blocked",
                    evaluator_version=self.evaluator_version,
                    details={"reason": "privacy_or_schema_error"},
                )
            results.append(result)
        outcome = _run_outcome(results)
        config_digest = configuration_digest(configuration)
        stable_id = run_id or _stable_run_id(dataset, self.evaluator_version, config_digest, results)
        return EvaluationRun(
            run_id=stable_id,
            dataset_id=dataset.dataset_id,
            dataset_digest=cast(str, dataset.digest),
            evaluator_version=self.evaluator_version,
            configuration_digest=config_digest,
            results=tuple(results),
            outcome=outcome,
            created_at=created_at or datetime.now(UTC),
        )

    run = evaluate


class LLMJudgeRunner:
    """Optional offline judge runner with complete version metadata."""

    def __init__(
        self,
        judge: Callable[[EvaluationCase], object | Awaitable[object]],
        *,
        provider: str,
        model_version: str,
        rubric_version: str,
        template_version: str,
        evaluator_version: str = "llm-judge/v1",
    ) -> None:
        fields = (provider, model_version, rubric_version, template_version, evaluator_version)
        if any(not value or any(character.isspace() for character in value) for value in fields):
            raise ValueError("LLM judge metadata must be non-empty tokens")
        self.judge = judge
        self.provider = provider
        self.model_version = model_version
        self.rubric_version = rubric_version
        self.template_version = template_version
        self.evaluator_version = evaluator_version

    async def evaluate(
        self,
        dataset: EvaluationDataset,
        *,
        configuration: object = None,
        run_id: str | None = None,
        created_at: datetime | None = None,
    ) -> EvaluationRun:
        results: list[EvaluationCaseResult] = []
        for case in dataset.cases:
            try:
                value = self.judge(case)
                if inspect.isawaitable(value):
                    value = await value
                result = _judge_result(case, value, self.evaluator_version)
            except Exception:
                result = EvaluationCaseResult(
                    case_id=case.case_id,
                    outcome="blocked",
                    evaluator_version=self.evaluator_version,
                    details={"reason": "judge_unavailable"},
                )
            results.append(result)
        config_digest = configuration_digest(configuration)
        stable_id = run_id or _stable_run_id(dataset, self.evaluator_version, config_digest, results)
        return EvaluationRun(
            run_id=stable_id,
            dataset_id=dataset.dataset_id,
            dataset_digest=cast(str, dataset.digest),
            evaluator_version=self.evaluator_version,
            configuration_digest=config_digest,
            results=tuple(results),
            outcome=_run_outcome(results),
            created_at=created_at or datetime.now(UTC),
            provider=self.provider,
            model_version=self.model_version,
            rubric_version=self.rubric_version,
            template_version=self.template_version,
        )

    run = evaluate


def evaluate_gate(
    *,
    milestone: str,
    dataset: EvaluationDataset | None,
    run: EvaluationRun | None,
    thresholds: Mapping[str, object] | None,
    code_revision: str,
    evaluator_version: str,
    approval_id: str | None = None,
    expires_at: datetime | None = None,
    phoenix_evidence_required: bool = False,
    phoenix_evidence_digest: str | None = None,
    configuration_digest_value: str | None = None,
    provider: str | None = None,
    model_version: str | None = None,
    core_version: str | None = None,
    pack_version: str | None = None,
) -> EvaluationGate:
    """Produce an explicit pass/fail/blocked gate with fail-closed defaults."""

    threshold_values = dict(thresholds or {})
    report = EvaluationOutcome.PASS
    if dataset is None or run is None or not threshold_values or run.outcome is EvaluationOutcome.BLOCKED:
        report = EvaluationOutcome.BLOCKED
    elif run.outcome is EvaluationOutcome.FAIL:
        report = EvaluationOutcome.FAIL
    else:
        pass_rate = sum(result.outcome == "pass" for result in run.results) / len(run.results)
        minimum = threshold_values.get("minimum_pass_rate")
        if isinstance(minimum, (int, float)) and pass_rate < float(minimum):
            report = EvaluationOutcome.FAIL
        if any(
            str(result.details.get("privacy_status", "")).casefold() in {"fail", "blocked"}
            for result in run.results
        ):
            report = EvaluationOutcome.FAIL
    if report is EvaluationOutcome.PASS and (
        (phoenix_evidence_required and not phoenix_evidence_digest)
        or approval_id is None
        or expires_at is None
        or (expires_at is not None and expires_at <= datetime.now(UTC))
    ):
        report = EvaluationOutcome.BLOCKED
    gate_expiry = expires_at if report is EvaluationOutcome.PASS else None
    return EvaluationGate(
        milestone=cast(Any, milestone),
        report=report,
        dataset_digest=cast(str, dataset.digest if dataset else "0" * 64),
        code_revision=code_revision,
        evaluator_version=evaluator_version,
        thresholds=cast(ContractPayload, threshold_values),
        configuration_digest=configuration_digest_value,
        provider=provider,
        model_version=model_version,
        core_version=core_version,
        pack_version=pack_version,
        failure_injection_passed=True if report is EvaluationOutcome.PASS else None,
        approval_id=approval_id if report is EvaluationOutcome.PASS else None,
        expires_at=gate_expiry,
        phoenix_evidence_digest=phoenix_evidence_digest if report is EvaluationOutcome.PASS else None,
        phoenix_evidence_required=phoenix_evidence_required,
    )


QualificationGateEvaluator = evaluate_gate


def _validate_endpoint(endpoint: str, *, verify_tls: bool) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Phoenix endpoint must include an HTTP(S) host")
    if verify_tls and parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("TLS verification requires an HTTPS Phoenix endpoint")


def _status_classification(status: int) -> str | None:
    if status in {401, 403}:
        return "authorization"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "server_error"
    if status < 200 or status >= 300:
        return "http_error"
    return None


def _response_version_matches(response: Any, expected: str) -> bool:
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("x-phoenix-api-version") or headers.get("x-api-version")
    if value is None:
        return True
    return str(value) == expected


def _response_schema_is_valid(response: Any) -> bool:
    status = int(getattr(response, "status_code", 0))
    if status == 204 or not hasattr(response, "json"):
        return True
    try:
        body = response.json()
    except Exception:
        return False
    return body is None or isinstance(body, (dict, list))


def _public_projection(value: object) -> object:
    _reject_private_values(value, "projection")
    if isinstance(value, Mapping):
        return {
            str(key): _public_projection(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_public_projection(child) for child in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _reject_private_values(value: object, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = _normalize_key(key)
            if normalized in _PRIVATE_KEYS or any(
                normalized.startswith(prefix + "_")
                for prefix in (
                    "user",
                    "session",
                    "preference",
                    "memory",
                    "prompt",
                    "token",
                    "credential",
                    "password",
                    "secret",
                    "private",
                    "account",
                    "qr",
                    "header",
                    "body",
                    "output",
                    "query",
                    "url",
                    "note",
                )
            ):
                raise ValueError(f"private evaluation value at {path}.{key}")
            _reject_private_values(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_private_values(child, f"{path}[{index}]")
    elif isinstance(value, str) and any(
        marker in value.casefold()
        for marker in ("bearer ", "authorization:", "cookie:", "http://", "https://")
    ):
        raise ValueError(f"private evaluation value at {path}")


def _normalize_key(key: object) -> str:
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", str(key))
    return value.casefold().replace("-", "_")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest_public(value: object) -> str:
    return hashlib.sha256(_canonical_json(_public_projection(value)).encode("utf-8")).hexdigest()


def _run_outcome(results: Sequence[EvaluationCaseResult]) -> EvaluationOutcome:
    if any(result.outcome == "blocked" for result in results):
        return EvaluationOutcome.BLOCKED
    if any(result.outcome == "fail" for result in results):
        return EvaluationOutcome.FAIL
    return EvaluationOutcome.PASS


def _stable_run_id(
    dataset: EvaluationDataset,
    evaluator_version: str,
    config_digest: str,
    results: Sequence[EvaluationCaseResult],
) -> str:
    value = {
        "dataset": dataset.digest,
        "evaluator": evaluator_version,
        "configuration": config_digest,
        "results": [result.model_dump(mode="json") for result in results],
    }
    return "run-" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:24]


def _judge_result(case: EvaluationCase, value: object, evaluator_version: str) -> EvaluationCaseResult:
    if isinstance(value, EvaluationCaseResult):
        if value.case_id != case.case_id:
            raise ValueError("judge returned a result for another case")
        return value.model_copy(update={"evaluator_version": evaluator_version})
    if isinstance(value, Mapping):
        outcome = str(value.get("outcome", "blocked"))
        if outcome not in {"pass", "fail", "blocked"}:
            outcome = "blocked"
        score = value.get("score")
        score_value = float(score) if isinstance(score, (int, float)) else None
        details = value.get("details", {})
        if not isinstance(details, Mapping):
            details = {}
        _reject_private_values(details, "judge.details")
        return EvaluationCaseResult(
            case_id=case.case_id,
            outcome=cast(Any, outcome),
            evaluator_version=evaluator_version,
            score=score_value,
            details=cast(ContractPayload, _public_projection(details)),
        )
    raise ValueError("judge result must be a result record or mapping")


__all__ = [
    "DeterministicEvaluator",
    "LLMJudgeRunner",
    "PhoenixEvalGateway",
    "PhoenixEvaluationAdapter",
    "PhoenixEvaluationGateway",
    "PhoenixGatewayError",
    "QualificationGateEvaluator",
    "build_evaluation_port",
    "evaluate_gate",
    "project_evaluation_dataset",
    "project_evaluation_run",
]
