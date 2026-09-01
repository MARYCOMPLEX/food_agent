from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from xhs_food.contracts import PlatformChannel
from xhs_food.contracts.account_service import (
    ACCOUNT_SERVICE_CONTRACT_VERSION,
    AccountServiceConfig,
    AccountServiceDescriptor,
    RemotePayloadRejected,
    RemoteSourceInvocation,
    sanitize_remote_payload,
    validate_remote_payload,
)


def _config(**overrides: object) -> AccountServiceConfig:
    values: dict[str, object] = {
        "service_id": "xhs-account",
        "base_url": "http://account.test",
        "channels": [PlatformChannel.XHS_PC],
        "capabilities": ["account.register", "account.login", "notes.search"],
    }
    values.update(overrides)
    return AccountServiceConfig.model_validate(values)


def test_remote_payload_validation_rejects_secret_shaped_fields() -> None:
    with pytest.raises(RemotePayloadRejected):
        validate_remote_payload({"account_ref": "primary", "cookie": "sid=secret"})
    with pytest.raises(RemotePayloadRejected):
        validate_remote_payload({"query": "authorization: Bearer secret"})


def test_remote_payload_sanitization_is_recursive_and_json_safe() -> None:
    value = sanitize_remote_payload(
        {"safe": {"id": "x"}, "cookie": "sid=secret", "items": [b"qr-bytes"]}
    )
    assert value == {"safe": {"id": "x"}, "items": ["[REDACTED]"]}


def test_remote_source_invocation_rejects_secret_query_keys() -> None:
    with pytest.raises(ValidationError):
        RemoteSourceInvocation(
            service_id="xhs-account",
            tenant_ref="tenant-a",
            platform=PlatformChannel.XHS_PC,
            account_ref="primary",
            correlation_id="corr-1",
            capability="notes.search",
            query={"storage_state": "forbidden"},
        )


def test_descriptor_and_config_pin_the_contract_and_channels() -> None:
    config = _config()
    descriptor = AccountServiceDescriptor(
        service_id="xhs-account",
        service_version="2026.09.01",
        contract_version=ACCOUNT_SERVICE_CONTRACT_VERSION,
        protocol="http+mcp",
        platform_channels=(PlatformChannel.XHS_PC,),
        capabilities=("account.login",),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert config.descriptor_version == descriptor.contract_version
    assert descriptor.platform_channels == (PlatformChannel.XHS_PC,)
