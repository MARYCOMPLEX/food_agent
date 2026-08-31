"""Credential-redaction matrix for every project-owned platform boundary."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from xhs_food.contracts import (
    AccountHealthSignal,
    LoginActivityOperation,
    LoginFlowState,
    PlatformAccountHealth,
    PlatformAccountHealthEvent,
    PlatformAccountRef,
    PlatformChannel,
    PlatformLoginActivityRequest,
    PlatformLoginFlow,
)
from xhs_food.experience.platform_login import _redacted_flow
from xhs_food.foundation.platform_login_temporal import (
    _safe_message,
    build_account_auth_workflow_start,
)
from xhs_food.gateways.platform_gateway import _safe_provider_error
from xhs_food.gateways.platform_sources import _safe_mapping

pytestmark = pytest.mark.unit
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
SECRET = "credential-fixture-never-emit"


def _account() -> PlatformAccountRef:
    return PlatformAccountRef(
        tenant_id="tenant-a",
        platform=PlatformChannel.XHS_PC,
        account_ref="acct-a",
    )


@pytest.mark.parametrize(
    "field",
    (
        "cookie",
        "authorization",
        "qr_payload",
        "signer_input",
        "storage_state_path",
        "decrypted_envelope",
    ),
)
def test_temporal_activity_input_rejects_secret_fields(field: str) -> None:
    payload = {
        "flow_id": "flow-a",
        "account": _account().model_dump(mode="json"),
        "operation": LoginActivityOperation.POLL,
        field: SECRET,
    }
    with pytest.raises(ValidationError):
        PlatformLoginActivityRequest.model_validate(payload)


def test_temporal_history_and_sse_projection_are_identifier_only() -> None:
    request = PlatformLoginActivityRequest(
        flow_id="flow-a",
        account=_account(),
        operation=LoginActivityOperation.POLL,
    )
    command = build_account_auth_workflow_start(
        request,
        workflow_id="platform-auth:flow-a",
        idempotency_key="platform-auth:flow-a:poll",
    )
    flow = PlatformLoginFlow(
        flow_id="flow-a",
        account=_account(),
        state=LoginFlowState.WAITING_SCAN,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        updated_at=NOW,
    )
    # The same redacted projection is safe for HTTP polling or an optional SSE
    # status envelope; QR object metadata and provider material are excluded.
    durable = json.dumps(command.input, sort_keys=True)
    event = json.dumps(_redacted_flow(flow), sort_keys=True, default=str)
    for value in (durable, event):
        lowered = value.casefold()
        assert SECRET not in value
        assert "cookie" not in lowered
        assert "authorization" not in lowered
        assert "qr_payload" not in lowered
        assert "signer_input" not in lowered
        assert "storage_state" not in lowered
        assert "decrypted" not in lowered


def test_provider_exceptions_and_canonical_attributes_redact_all_secret_classes() -> None:
    leaky = RuntimeError(
        "authorization=Bearer " + SECRET
        + "; cookie=" + SECRET
        + "; storage_state=C:/tmp/" + SECRET
        + "; signer_input=" + SECRET
    )
    temporal_message = _safe_message(leaky)
    gateway_error = _safe_provider_error(leaky, "xhs")
    assert SECRET not in temporal_message
    assert SECRET not in json.dumps(gateway_error.model_dump(mode="json"))

    public = _safe_mapping(
        {
            "title": "safe",
            "cookie": SECRET,
            "authorization": SECRET,
            "qr_payload": SECRET,
            "signer_input": SECRET,
            "nested": {"storage_state": "C:/tmp/" + SECRET},
            "url": "https://www.xiaohongshu.com/explore/note?xsec_token=" + SECRET,
            "diagnostic": "token=" + SECRET,
        }
    )
    encoded = json.dumps(public, sort_keys=True)
    assert public["title"] == "safe"
    assert SECRET not in encoded
    assert "xsec_token" not in encoded
    assert public["diagnostic"] == "[REDACTED]"


@pytest.mark.parametrize(
    "metadata",
    (
        {"cookie": SECRET},
        {"headers": {"authorization": SECRET}},
        {"qr_payload": SECRET},
        {"signer_input": SECRET},
        {"path": "storage_state=C:/tmp/credential.json"},
    ),
)
def test_telemetry_metadata_rejects_secret_keys_and_values(metadata: object) -> None:
    with pytest.raises(ValidationError):
        PlatformAccountHealthEvent(
            event_id="health-a",
            account=_account(),
            signal=AccountHealthSignal.TRANSIENT,
            health=PlatformAccountHealth.UNKNOWN,
            observed_at=NOW,
            metadata=metadata,
        )
