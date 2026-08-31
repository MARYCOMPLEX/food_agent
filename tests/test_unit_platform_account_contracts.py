"""Focused invariants for the platform account/session contract boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from xhs_food.contracts import (
    AccountHealthSignal,
    EncryptedSessionEnvelope,
    LoginFlowState,
    PlatformAccount,
    PlatformAccountHealth,
    PlatformAccountRef,
    PlatformAccountStatus,
    PlatformChannel,
    PlatformLoginFlow,
    SessionActivationRequest,
    can_transition_login_flow,
    transition_login_flow,
    validate_login_flow_update,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


def _account_ref() -> PlatformAccountRef:
    return PlatformAccountRef(
        tenant_id="tenant-cn-1",
        platform=PlatformChannel.DIANPING,
        account_id="acct-dp-1",
    )


def _envelope() -> EncryptedSessionEnvelope:
    return EncryptedSessionEnvelope(
        encrypted_payload="ciphertext-fixture",
        nonce="nonce-fixture",
        tag="auth-tag-fixture",
        key_ref="local-kms",
        key_version="v1",
        digest="0" * 64,
    )


def test_account_reference_is_opaque_and_platform_scoped() -> None:
    ref = _account_ref()
    assert ref.account_ref == "acct-dp-1"
    assert ref.account_id == ref.account_ref
    assert ref.natural_key == ("tenant-cn-1", PlatformChannel.DIANPING, "acct-dp-1")

    with pytest.raises(ValidationError):
        PlatformAccountRef(
            tenant_id="tenant-cn-1",
            platform="dianping",
            account_ref="sessions/state.json",
        )


def test_session_envelope_contains_ciphertext_metadata_only() -> None:
    envelope = _envelope()
    assert envelope.encrypted_payload == envelope.ciphertext
    assert envelope.key_id == "local-kms"
    assert envelope.session_digest == "0" * 64

    with pytest.raises(ValidationError):
        EncryptedSessionEnvelope(
            ciphertext="ciphertext-fixture",
            nonce="nonce-fixture",
            auth_tag="auth-tag-fixture",
            key_ref="local-kms",
            key_version="v1",
            digest="0" * 64,
            storage_state_path=".state/cookies.json",
        )


def test_active_account_requires_an_active_session_version() -> None:
    with pytest.raises(ValidationError, match="session version"):
        PlatformAccount(
            tenant_id="tenant-cn-1",
            platform="dianping",
            account_ref="acct-dp-1",
            alias="primary",
            status=PlatformAccountStatus.ACTIVE,
            health=PlatformAccountHealth.HEALTHY,
            created_at=NOW,
            updated_at=NOW,
        )


def test_session_activation_is_compare_and_set_input() -> None:
    request = SessionActivationRequest(
        account=_account_ref(),
        expected_session_version=2,
        envelope=_envelope(),
        expires_at=NOW + timedelta(hours=1),
        requested_at=NOW,
    )
    assert request.expected_version == 2
    with pytest.raises(ValidationError, match="expiry"):
        request.model_copy(update={"expires_at": NOW})


def test_login_flow_transitions_are_monotonic_and_terminal() -> None:
    assert can_transition_login_flow(LoginFlowState.CREATED, LoginFlowState.QR_READY)
    assert not can_transition_login_flow(
        LoginFlowState.WAITING_CONFIRMATION,
        LoginFlowState.WAITING_SCAN,
    )
    assert not can_transition_login_flow(LoginFlowState.FAILED, LoginFlowState.QR_READY)


def _flow(
    state: LoginFlowState,
    *,
    updated_at: datetime = NOW,
    provider_subject_id: str | None = None,
    error_code: str | None = None,
) -> PlatformLoginFlow:
    return PlatformLoginFlow(
        flow_id="flow-contract-1",
        account=_account_ref(),
        state=state,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        updated_at=updated_at,
        provider_subject_id=provider_subject_id,
        error_code=error_code,
    )


def test_login_flow_snapshot_cas_rejects_regression_and_allows_equal_time_forward() -> None:
    current = _flow(LoginFlowState.WAITING_CONFIRMATION, updated_at=NOW)
    # A delayed poll can have a newer wall-clock value but an older provider
    # state; timestamp ordering alone must not allow this overwrite.
    with pytest.raises(ValueError, match="state transition is stale"):
        validate_login_flow_update(
            current,
            _flow(
                LoginFlowState.WAITING_SCAN,
                updated_at=NOW + timedelta(seconds=1),
            ),
        )

    # Equal timestamps are valid when the state moves forward in the state
    # machine; provider callbacks may share one clock tick.
    validate_login_flow_update(
        _flow(LoginFlowState.WAITING_SCAN),
        _flow(LoginFlowState.WAITING_CONFIRMATION),
    )


def test_terminal_login_flow_is_immutable_but_idempotent() -> None:
    current = _flow(LoginFlowState.SUCCEEDED, provider_subject_id="subject-1")
    validate_login_flow_update(
        current,
        _flow(
            LoginFlowState.SUCCEEDED,
            updated_at=NOW + timedelta(seconds=1),
            provider_subject_id="subject-1",
        ),
    )
    with pytest.raises(ValueError, match="terminal login flow"):
        validate_login_flow_update(
            current,
            _flow(
                LoginFlowState.WAITING_SCAN,
                updated_at=NOW + timedelta(seconds=1),
                provider_subject_id="subject-1",
            ),
        )
    with pytest.raises(ValueError, match="payload is immutable"):
        validate_login_flow_update(
            current,
            _flow(
                LoginFlowState.SUCCEEDED,
                updated_at=NOW + timedelta(seconds=1),
                provider_subject_id="subject-2",
            ),
        )


def test_transition_login_flow_revalidates_timestamp_and_terminal_payload() -> None:
    current = _flow(LoginFlowState.WAITING_SCAN)
    with pytest.raises(ValueError, match="precede current snapshot"):
        transition_login_flow(
            current,
            LoginFlowState.WAITING_CONFIRMATION,
            updated_at=NOW - timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="requires provider_subject_id"):
        transition_login_flow(
            current,
            LoginFlowState.SUCCEEDED,
            updated_at=NOW,
        )


def test_health_event_rejects_secret_bearing_metadata() -> None:
    from xhs_food.contracts import PlatformAccountHealthEvent

    with pytest.raises(ValidationError, match="secret field"):
        PlatformAccountHealthEvent(
            event_id="health-1",
            account=_account_ref(),
            signal=AccountHealthSignal.AUTHENTICATION,
            health=PlatformAccountHealth.SESSION_INVALID,
            observed_at=NOW,
            metadata={"cookie": "secret"},
        )
