"""Tenant- and platform-scoped account/session contracts.

The models in this module describe the *authority* owned by the application.
They intentionally contain metadata and encrypted envelopes only; provider
cookies, browser storage paths, QR bytes, and signer state are never represented
as serializable contract fields.  Concrete PostgreSQL, Redis, ObjectStore, and
Temporal adapters implement the ports at the edge of the application.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import AliasChoices, ConfigDict, Field, field_validator, model_validator

from .base import ContractPayload, NonEmptyStr, Timestamp
from .evidence import AuthorityModel, CollectRequest
from .ports import ObjectRef, TemporalExecutionPolicy

PLATFORM_ACCOUNT_VERSION = "platform-account/v1"
PLATFORM_SESSION_VERSION = "platform-session/v1"
PLATFORM_LOGIN_VERSION = "platform-login/v1"
PLATFORM_LEASE_VERSION = "platform-lease/v1"
PLATFORM_SOURCE_INVOCATION_VERSION = "platform-source-invocation/v1"
PLATFORM_LOGIN_ACTIVITY_VERSION = "platform-login-activity/v1"
PLATFORM_LOGIN_WORKFLOW_VERSION = "platform-login-workflow/v1"
# Compatibility spelling retained for adapters using the early design notes.
ACCOUNT_CONTRACT_VERSION = PLATFORM_ACCOUNT_VERSION

# IDs are references, not provider credentials.  Deliberately disallow path
# separators and whitespace so a reference cannot become a filesystem path or
# log-injection vector when passed through an adapter.
AccountId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$",
    ),
]
# Opaque vault handles may include a namespace separator (for example
# ``vault:phone-123``), unlike account identifiers which are also used in
# object-store keys.  Keep the broader grammar confined to this field.
CredentialRef = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
    ),
]
TenantId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
    ),
]
Sha256Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

_SECRET_ASSIGNMENT = re.compile(
    r"(?:cookie|authorization|bearer|password|passwd|secret|token|qruuid|"
    r"qr(?:[_ -]?(?:id|url|payload))?|storage[_ -]?state|"
    r"signer(?:[_ -]?(?:input|state))?|decrypted[_ -]?(?:envelope|session))\s*[:=]",
    re.IGNORECASE,
)
_SECRET_KEY = re.compile(
    r"(?:cookie|authorization|password|passwd|secret|token|qruuid|"
    r"qr(?:[_ -]?(?:id|url|payload))?|storage[_ -]?state|"
    r"signer(?:[_ -]?(?:input|state))?|decrypted[_ -]?(?:envelope|session))",
    re.IGNORECASE,
)


class _AccountContract(AuthorityModel):
    """Strict immutable base for account authority values."""

    # AuthorityModel already sets ``extra='forbid'``; repeating the intent here
    # makes the security boundary obvious to readers and schema consumers.
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=False,
        use_enum_values=False,
    )


def _validate_redacted_text(value: str, field_name: str) -> str:
    """Reject diagnostics that look like an unredacted credential assignment."""

    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    if _SECRET_ASSIGNMENT.search(value):
        raise ValueError(f"{field_name} appears to contain secret material")
    return value


def _validate_safe_metadata(value: object, path: str = "metadata") -> None:
    """Ensure event metadata cannot carry credential-bearing keys or values."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if _SECRET_KEY.search(key_text):
                raise ValueError(f"{path} contains forbidden secret field {key_text!r}")
            _validate_safe_metadata(item, f"{path}.{key_text}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _validate_safe_metadata(item, f"{path}[{index}]")
        return
    if isinstance(value, str):
        _validate_redacted_text(value, path)


class PlatformChannel(StrEnum):
    """Provider channels with independent account/session namespaces."""

    DIANPING = "dianping"
    XHS_PC = "xhs_pc"
    XHS_CREATOR = "xhs_creator"


class PlatformAccountStatus(StrEnum):
    PENDING_LOGIN = "pending_login"
    ACTIVE = "active"
    DEGRADED = "degraded"
    REAUTH_REQUIRED = "reauth_required"
    DISABLED = "disabled"


class PlatformAccountHealth(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    SESSION_INVALID = "session_invalid"
    SESSION_EXPIRED = "session_expired"
    CHALLENGE_REQUIRED = "challenge_required"
    THROTTLED = "throttled"
    RISK_COOLDOWN = "risk_cooldown"
    DISABLED = "disabled"


class PlatformSessionStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    REVOKED = "revoked"


class PlatformLeaseStatus(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    EXPIRED = "expired"


class AccountGrantPermission(StrEnum):
    """Least-privilege operations that may be granted to a principal."""

    VIEW = "view"
    USE = "use"
    LOGIN = "login"
    REFRESH = "refresh"
    ADMIN = "admin"


class AccountHealthSignal(StrEnum):
    SUCCESS = "success"
    AUTHENTICATION = "authentication"
    CHALLENGE = "challenge"
    THROTTLED = "throttled"
    TRANSIENT = "transient"
    PARSE = "parse"
    EXPIRED = "expired"
    REVOKED = "revoked"


class LoginFlowState(StrEnum):
    """Shared split-phase login states; provider states are mapped at the edge."""

    CREATED = "created"
    QR_READY = "qr_ready"
    WAITING_SCAN = "waiting_scan"
    WAITING_CONFIRMATION = "waiting_confirmation"
    SUCCEEDED = "succeeded"
    EXPIRED = "expired"
    FAILED = "failed"
    CANCELLED = "cancelled"


LOGIN_FLOW_TERMINAL_STATES = frozenset(
    {
        LoginFlowState.SUCCEEDED,
        LoginFlowState.EXPIRED,
        LoginFlowState.FAILED,
        LoginFlowState.CANCELLED,
    }
)
_LOGIN_FLOW_RANK = {
    LoginFlowState.CREATED: 0,
    LoginFlowState.QR_READY: 1,
    LoginFlowState.WAITING_SCAN: 2,
    LoginFlowState.WAITING_CONFIRMATION: 3,
    LoginFlowState.SUCCEEDED: 4,
}


class PlatformAccountRef(_AccountContract):
    """The only identity needed to resolve an external platform account."""

    schema_version: Literal["platform-account-ref/v1"] = "platform-account-ref/v1"
    tenant_id: TenantId
    platform: PlatformChannel
    # ``account_id`` is accepted as an input alias for database adapters.  The
    # public contract calls it account_ref to emphasize that it is opaque.
    account_ref: AccountId = Field(
        validation_alias=AliasChoices("account_ref", "account_id")
    )

    @property
    def account_id(self) -> str:
        """Compatibility spelling for repositories whose column is account_id."""

        return self.account_ref

    @property
    def natural_key(self) -> tuple[str, PlatformChannel, str]:
        return (self.tenant_id, self.platform, self.account_ref)

    @field_validator("tenant_id", "account_ref")
    @classmethod
    def validate_reference_text(cls, value: str) -> str:
        if value != value.strip() or any(character.isspace() for character in value):
            raise ValueError("account references must not contain whitespace")
        return value


class PlatformAccount(_AccountContract):
    """Durable account metadata; no cookie or browser-state payload is allowed."""

    schema_version: Literal["platform-account/v1"] = PLATFORM_ACCOUNT_VERSION
    tenant_id: TenantId
    platform: PlatformChannel
    account_ref: AccountId
    alias: NonEmptyStr
    provider_subject_id: NonEmptyStr | None = None
    status: PlatformAccountStatus = PlatformAccountStatus.PENDING_LOGIN
    health: PlatformAccountHealth = PlatformAccountHealth.UNKNOWN
    session_version: int = Field(default=0, ge=0)
    created_at: Timestamp
    updated_at: Timestamp

    @property
    def ref(self) -> PlatformAccountRef:
        return PlatformAccountRef(
            tenant_id=self.tenant_id,
            platform=self.platform,
            account_ref=self.account_ref,
        )

    @property
    def active_session_version(self) -> int:
        """Explicit spelling used by account/session repositories."""

        return self.session_version

    @model_validator(mode="after")
    def validate_status_and_session(self) -> PlatformAccount:
        if self.status is PlatformAccountStatus.PENDING_LOGIN and self.session_version != 0:
            raise ValueError("pending_login account cannot expose an active session version")
        if self.status in {
            PlatformAccountStatus.ACTIVE,
            PlatformAccountStatus.DEGRADED,
        } and self.session_version < 1:
            raise ValueError("active or degraded account requires a session version")
        if self.status is PlatformAccountStatus.REAUTH_REQUIRED and self.health not in {
            PlatformAccountHealth.SESSION_INVALID,
            PlatformAccountHealth.SESSION_EXPIRED,
            PlatformAccountHealth.CHALLENGE_REQUIRED,
            PlatformAccountHealth.UNKNOWN,
        }:
            raise ValueError("reauth_required account must expose an unusable-session health")
        return self


class EncryptedSessionEnvelope(_AccountContract):
    """Authenticated ciphertext metadata; plaintext session material is not a field."""

    schema_version: Literal["platform-session-envelope/v1"] = (
        "platform-session-envelope/v1"
    )
    algorithm: Literal["AES-GCM", "AES-256-GCM"] = "AES-GCM"
    # Aliases preserve compatibility with common KMS vocabulary while keeping
    # one canonical serialized spelling in this contract.
    ciphertext: NonEmptyStr = Field(
        validation_alias=AliasChoices("ciphertext", "encrypted_payload")
    )
    nonce: NonEmptyStr
    auth_tag: NonEmptyStr = Field(validation_alias=AliasChoices("auth_tag", "tag"))
    key_ref: NonEmptyStr
    key_version: NonEmptyStr
    digest: Sha256Digest
    # ``None`` is retained for compatibility with envelopes produced before
    # version binding was introduced.  Envelopes sealed by the project codec
    # always carry the exact session version used as AES-GCM AAD.
    bound_version: int | None = Field(default=None, ge=1)

    @property
    def encrypted_payload(self) -> str:
        return self.ciphertext

    @property
    def key_id(self) -> str:
        return self.key_ref

    @property
    def session_digest(self) -> str:
        return self.digest


class PlatformAccountSession(_AccountContract):
    """One immutable encrypted session version for one platform account."""

    schema_version: Literal["platform-session/v1"] = PLATFORM_SESSION_VERSION
    session_id: AccountId
    account: PlatformAccountRef
    version: int = Field(ge=1)
    envelope: EncryptedSessionEnvelope
    expires_at: Timestamp
    status: PlatformSessionStatus = PlatformSessionStatus.ACTIVE
    created_at: Timestamp
    superseded_at: Timestamp | None = None
    revoked_at: Timestamp | None = None

    @property
    def digest(self) -> str:
        return self.envelope.digest

    @model_validator(mode="after")
    def validate_lifecycle(self) -> PlatformAccountSession:
        if self.status is PlatformSessionStatus.SUPERSEDED and self.superseded_at is None:
            raise ValueError("superseded session must record superseded_at")
        if self.status is PlatformSessionStatus.REVOKED and self.revoked_at is None:
            raise ValueError("revoked session must record revoked_at")
        if self.status is PlatformSessionStatus.ACTIVE and (
            self.superseded_at is not None or self.revoked_at is not None
        ):
            raise ValueError("active session cannot carry terminal timestamps")
        if self.expires_at <= self.created_at:
            raise ValueError("session expiry must be after creation")
        return self


class SessionActivationRequest(_AccountContract):
    """Compare-and-set command used after a provider login succeeds."""

    schema_version: Literal["platform-session-activation/v1"] = (
        "platform-session-activation/v1"
    )
    account: PlatformAccountRef
    expected_session_version: int = Field(default=0, ge=0)
    envelope: EncryptedSessionEnvelope
    expires_at: Timestamp
    requested_at: Timestamp
    provider_subject_id: NonEmptyStr | None = None

    @property
    def expected_version(self) -> int:
        return self.expected_session_version

    @model_validator(mode="after")
    def validate_expiry(self) -> SessionActivationRequest:
        if self.expires_at <= self.requested_at:
            raise ValueError("session expiry must be after activation request time")
        return self


class SessionVersionView(_AccountContract):
    """Redacted session metadata suitable for API/SSE responses."""

    schema_version: Literal["platform-session-view/v1"] = "platform-session-view/v1"
    session_id: AccountId
    account: PlatformAccountRef
    version: int = Field(ge=1)
    digest: Sha256Digest
    status: PlatformSessionStatus
    expires_at: Timestamp


class PlatformAccountLease(_AccountContract):
    """Durable single-client lease; only a digest of the owner token is stored."""

    schema_version: Literal["platform-lease/v1"] = PLATFORM_LEASE_VERSION
    lease_id: AccountId
    account: PlatformAccountRef
    task_id: NonEmptyStr
    owner_id: NonEmptyStr
    owner_token_digest: Sha256Digest = Field(
        validation_alias=AliasChoices("owner_token_digest", "owner_token_hash")
    )
    status: PlatformLeaseStatus = PlatformLeaseStatus.ACTIVE
    acquired_at: Timestamp
    expires_at: Timestamp
    last_heartbeat_at: Timestamp
    released_at: Timestamp | None = None

    @property
    def owner_token_hash(self) -> str:
        return self.owner_token_digest

    @model_validator(mode="after")
    def validate_lifecycle(self) -> PlatformAccountLease:
        if self.expires_at <= self.acquired_at:
            raise ValueError("lease expiry must be after acquisition")
        if self.last_heartbeat_at < self.acquired_at:
            raise ValueError("lease heartbeat cannot precede acquisition")
        if self.status is PlatformLeaseStatus.RELEASED and self.released_at is None:
            raise ValueError("released lease must record released_at")
        if self.status is PlatformLeaseStatus.ACTIVE and self.released_at is not None:
            raise ValueError("active lease cannot carry released_at")
        return self


class AccountLeaseRequest(_AccountContract):
    """Request to acquire one account-scoped provider client lease."""

    schema_version: Literal["platform-lease-request/v1"] = "platform-lease-request/v1"
    account: PlatformAccountRef
    task_id: NonEmptyStr
    owner_id: NonEmptyStr
    ttl_seconds: int = Field(default=180, ge=1, le=86_400)
    expected_session_version: int | None = Field(default=None, ge=1)


class PlatformAccountGrant(_AccountContract):
    """Tenant-scoped authorization for using an external account."""

    schema_version: Literal["platform-account-grant/v1"] = "platform-account-grant/v1"
    grant_id: AccountId
    account: PlatformAccountRef
    principal_id: NonEmptyStr
    permissions: tuple[AccountGrantPermission, ...] = Field(min_length=1)
    issued_at: Timestamp
    expires_at: Timestamp | None = None
    revoked_at: Timestamp | None = None

    @model_validator(mode="after")
    def validate_permissions_and_lifecycle(self) -> PlatformAccountGrant:
        if len(self.permissions) != len(set(self.permissions)):
            raise ValueError("account grant permissions must be unique")
        if self.expires_at is not None and self.expires_at <= self.issued_at:
            raise ValueError("grant expiry must be after issue time")
        if self.revoked_at is not None and self.revoked_at < self.issued_at:
            raise ValueError("grant revocation cannot precede issue time")
        return self

    def permits(self, permission: AccountGrantPermission) -> bool:
        return AccountGrantPermission.ADMIN in self.permissions or permission in self.permissions


class PlatformAccountHealthEvent(_AccountContract):
    """Low-cardinality account health fact with secret-bearing data rejected."""

    schema_version: Literal["platform-account-health/v1"] = "platform-account-health/v1"
    event_id: AccountId
    account: PlatformAccountRef
    signal: AccountHealthSignal
    health: PlatformAccountHealth
    observed_at: Timestamp
    session_version: int | None = Field(default=None, ge=1)
    task_id: NonEmptyStr | None = None
    reason: str | None = None
    metadata: ContractPayload = Field(default_factory=dict)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        return None if value is None else _validate_redacted_text(value, "reason")

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: ContractPayload) -> ContractPayload:
        _validate_safe_metadata(value)
        return value


class PlatformLoginFlow(_AccountContract):
    """Durable split-phase login attempt, independent from account identity."""

    schema_version: Literal["platform-login/v1"] = PLATFORM_LOGIN_VERSION
    flow_id: AccountId
    account: PlatformAccountRef
    state: LoginFlowState = LoginFlowState.CREATED
    created_at: Timestamp
    expires_at: Timestamp
    updated_at: Timestamp
    qr_object_ref: ObjectRef | None = None
    qr_expires_at: Timestamp | None = None
    provider_subject_id: NonEmptyStr | None = None
    error_code: NonEmptyStr | None = None
    error_message: str | None = None

    @field_validator("error_message")
    @classmethod
    def validate_error_message(cls, value: str | None) -> str | None:
        return None if value is None else _validate_redacted_text(value, "error_message")

    @model_validator(mode="after")
    def validate_lifecycle(self) -> PlatformLoginFlow:
        if self.expires_at <= self.created_at:
            raise ValueError("login flow expiry must be after creation")
        if self.updated_at < self.created_at:
            raise ValueError("login flow update cannot precede creation")
        if self.qr_expires_at is not None and self.qr_expires_at > self.expires_at:
            raise ValueError("QR expiry cannot outlive login flow expiry")
        if self.state is LoginFlowState.SUCCEEDED and not self.provider_subject_id:
            raise ValueError("succeeded login flow requires provider_subject_id")
        if self.state is LoginFlowState.FAILED and not self.error_code:
            raise ValueError("failed login flow requires error_code")
        return self


def can_transition_login_flow(
    current: LoginFlowState, requested: LoginFlowState
) -> bool:
    """Return whether a login state transition is monotonic and terminal-safe."""

    if current in LOGIN_FLOW_TERMINAL_STATES or current is requested:
        return False
    if requested in LOGIN_FLOW_TERMINAL_STATES:
        return True
    current_rank = _LOGIN_FLOW_RANK.get(current)
    requested_rank = _LOGIN_FLOW_RANK.get(requested)
    return (
        current_rank is not None
        and requested_rank is not None
        and requested_rank > current_rank
    )


def validate_login_flow_update(
    current: PlatformLoginFlow,
    candidate: PlatformLoginFlow,
) -> None:
    """Validate an optimistic update against the currently stored snapshot.

    ``PlatformLoginFlow`` is immutable at the contract boundary, but the
    repository still receives independent snapshots from concurrent workers.
    This helper is the framework-neutral CAS rule shared by the in-memory and
    PostgreSQL authorities.  A timestamp alone is not sufficient: a delayed
    ``waiting_scan`` result must not overwrite ``waiting_confirmation`` and a
    terminal state must remain terminal even when the delayed writer has a
    newer wall-clock timestamp.

    Equal timestamps are accepted for a forward state transition.  Provider
    callbacks can complete within the same clock tick, and rejecting that
    update would turn a legitimate completion into a false conflict.  Equal
    timestamps for a backwards transition remain rejected by the rank check.
    Re-saving the same terminal snapshot is idempotent, while its terminal
    payload is immutable (apart from the observation timestamp).
    """

    if current.flow_id != candidate.flow_id:
        raise ValueError("login flow identity conflicts")
    if current.account.natural_key != candidate.account.natural_key:
        raise ValueError("login flow is bound to another account")
    if current.created_at != candidate.created_at:
        raise ValueError("login flow creation timestamp is immutable")
    if current.expires_at != candidate.expires_at:
        raise ValueError("login flow expiry deadline is immutable")
    if candidate.updated_at < current.updated_at:
        raise ValueError("login flow update is stale")

    if current.state in LOGIN_FLOW_TERMINAL_STATES:
        if candidate.state is not current.state:
            raise ValueError("terminal login flow cannot transition again")
        if (
            current.qr_object_ref != candidate.qr_object_ref
            or current.qr_expires_at != candidate.qr_expires_at
            or current.provider_subject_id != candidate.provider_subject_id
            or current.error_code != candidate.error_code
            or current.error_message != candidate.error_message
        ):
            raise ValueError("terminal login flow payload is immutable")
        return

    # A provider may race with a later poll.  Only a strictly higher
    # non-terminal rank, or any terminal state, may advance the snapshot.
    if candidate.state not in LOGIN_FLOW_TERMINAL_STATES:
        current_rank = _LOGIN_FLOW_RANK.get(current.state)
        candidate_rank = _LOGIN_FLOW_RANK.get(candidate.state)
        if candidate.state is not current.state and not (
            current_rank is not None
            and candidate_rank is not None
            and candidate_rank > current_rank
        ):
            raise ValueError("login flow state transition is stale")

    # These fields are write-once while a flow is active.  In particular, a
    # retry that carries an older provider result must not erase the redacted
    # subject marker written immediately before session CAS activation.
    for field_name in (
        "qr_object_ref",
        "qr_expires_at",
        "provider_subject_id",
        "error_code",
        "error_message",
    ):
        previous = getattr(current, field_name)
        if previous is not None and getattr(candidate, field_name) != previous:
            raise ValueError(f"login flow {field_name} is immutable once set")


def transition_login_flow(
    flow: PlatformLoginFlow,
    requested: LoginFlowState,
    *,
    updated_at: Timestamp,
    provider_subject_id: str | None = None,
    qr_object_ref: ObjectRef | None = None,
    qr_expires_at: Timestamp | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> PlatformLoginFlow:
    """Create a validated next flow snapshot without mutating the old one."""

    if not can_transition_login_flow(flow.state, requested):
        raise ValueError(f"invalid login flow transition: {flow.state.value} -> {requested.value}")
    if updated_at < flow.updated_at:
        raise ValueError("login flow update cannot precede current snapshot")
    updates: dict[str, object] = {
        "state": requested,
        "updated_at": updated_at,
    }
    if provider_subject_id is not None:
        updates["provider_subject_id"] = provider_subject_id
    if qr_object_ref is not None:
        updates["qr_object_ref"] = qr_object_ref
    if qr_expires_at is not None:
        updates["qr_expires_at"] = qr_expires_at
    if error_code is not None:
        updates["error_code"] = error_code
    if error_message is not None:
        updates["error_message"] = error_message
    # Rebuild the model explicitly at this trust boundary so lifecycle checks
    # (expiry, terminal payload requirements, and timestamp ordering) remain
    # enforced even if a future model implementation changes ``model_copy``.
    snapshot = flow.model_dump()
    snapshot.update(updates)
    return PlatformLoginFlow.model_validate(snapshot)


class PlatformSourceInvocation(_AccountContract):
    """Account-bound source call; account identity stays outside CollectRequest."""

    schema_version: Literal["platform-source-invocation/v1"] = (
        PLATFORM_SOURCE_INVOCATION_VERSION
    )
    request_id: NonEmptyStr
    tenant_id: TenantId
    platform: PlatformChannel
    account_ref: AccountId
    operation: NonEmptyStr
    collect_request: CollectRequest
    expected_session_version: int | None = Field(default=None, ge=1)
    grant_id: AccountId | None = None

    @property
    def account(self) -> PlatformAccountRef:
        return PlatformAccountRef(
            tenant_id=self.tenant_id,
            platform=self.platform,
            account_ref=self.account_ref,
        )

    @property
    def session_version(self) -> int | None:
        return self.expected_session_version


class LoginChallenge(_AccountContract):
    """Redacted QR challenge metadata; bytes remain behind ObjectStore."""

    schema_version: Literal["platform-login-challenge/v1"] = "platform-login-challenge/v1"
    flow_id: AccountId
    object_ref: ObjectRef
    expires_at: Timestamp
    content_type: NonEmptyStr = "image/png"


class LoginActivityOperation(StrEnum):
    """Provider-neutral operations exposed by the account-auth worker."""

    CREATE_QR = "create_qr"
    POLL = "poll"
    PHONE_LOGIN = "phone_login"
    COOKIE_IMPORT = "cookie_import"
    CANCEL = "cancel"


class PlatformLoginActivityRequest(_AccountContract):
    """Redacted account-auth Activity input.

    Only the flow/account identity and operation cross the Temporal boundary;
    provider cookies, QR bytes, and decrypted session material stay inside the
    Activity implementation.
    """

    schema_version: Literal["platform-login-activity/v1"] = (
        PLATFORM_LOGIN_ACTIVITY_VERSION
    )
    flow_id: AccountId
    account: PlatformAccountRef
    operation: LoginActivityOperation
    # Phone/cookie material is resolved from the activity-local vault by this
    # opaque handle.  The handle itself is safe to place in Temporal history;
    # raw phone numbers, verification codes, cookies, and storage-state paths
    # are intentionally not model fields.
    credential_ref: CredentialRef | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "credential_ref",
            "credential_handle",
            "secret_ref",
        ),
    )

    @model_validator(mode="after")
    def validate_credential_ref(self) -> PlatformLoginActivityRequest:
        needs_credential = self.operation in {
            LoginActivityOperation.PHONE_LOGIN,
            LoginActivityOperation.COOKIE_IMPORT,
        }
        if needs_credential and self.credential_ref is None:
            raise ValueError("credential_ref is required for credential login operations")
        if not needs_credential and self.credential_ref is not None:
            raise ValueError("credential_ref is only valid for credential login operations")
        return self

    @property
    def credential_handle(self) -> str | None:
        """Compatibility spelling for vault-backed credential references."""

        return self.credential_ref


class PlatformLoginActivityResult(_AccountContract):
    """Redacted Activity output containing flow metadata and optional QR ref."""

    schema_version: Literal["platform-login-activity-result/v1"] = (
        "platform-login-activity-result/v1"
    )
    flow: PlatformLoginFlow
    challenge: LoginChallenge | None = None


class PlatformLoginWorkflowInput(_AccountContract):
    """Durable account-auth Workflow input with bounded execution policy."""

    schema_version: Literal["platform-login-workflow/v1"] = (
        PLATFORM_LOGIN_WORKFLOW_VERSION
    )
    request: PlatformLoginActivityRequest
    execution_policy: TemporalExecutionPolicy = Field(default_factory=TemporalExecutionPolicy)


class PlatformLoginWorkflowOutput(_AccountContract):
    """Workflow result; all fields are safe to persist in Temporal history."""

    schema_version: Literal["platform-login-workflow-output/v1"] = (
        "platform-login-workflow-output/v1"
    )
    flow: PlatformLoginFlow
    challenge: LoginChallenge | None = None


@runtime_checkable
class PlatformAccountRepositoryPort(Protocol):
    async def get_account(self, ref: PlatformAccountRef) -> PlatformAccount | None: ...

    async def save_account(self, account: PlatformAccount) -> PlatformAccount: ...

    async def activate_session(self, request: SessionActivationRequest) -> PlatformAccountSession: ...


@runtime_checkable
class PlatformAccountSessionReaderPort(Protocol):
    """Read-only session metadata boundary used by account-bound gateways.

    Keeping this separate from :class:`PlatformAccountRepositoryPort` lets
    lightweight account registries implement registration/activation without
    having to expose decrypted material.  Production repositories implement
    both protocols; callers resolve the active version through this port and
    open the envelope only inside the activity that owns the provider client.
    """

    async def get_active_session(
        self, ref: PlatformAccountRef
    ) -> PlatformAccountSession | None: ...


@runtime_checkable
class SessionEnvelopeCodecPort(Protocol):
    """Seal/open provider state inside an activity; plaintext never enters a contract."""

    async def seal(
        self,
        account: PlatformAccountRef,
        plaintext: bytes,
        *,
        expires_at: Timestamp,
        version: int = 1,
    ) -> EncryptedSessionEnvelope: ...

    async def open(self, session: PlatformAccountSession) -> bytes: ...


@runtime_checkable
class PlatformAccountLeasePort(Protocol):
    async def acquire(self, request: AccountLeaseRequest) -> PlatformAccountLease: ...

    async def heartbeat(self, lease_id: str, *, ttl_seconds: int) -> PlatformAccountLease: ...

    async def release(self, lease_id: str) -> bool: ...


@runtime_checkable
class PlatformAccountGrantPort(Protocol):
    async def authorize(
        self,
        account: PlatformAccountRef,
        principal_id: str,
        permission: AccountGrantPermission,
    ) -> PlatformAccountGrant | None: ...


@runtime_checkable
class PlatformLoginFlowPort(Protocol):
    async def get_flow(self, flow_id: str, *, tenant_id: str) -> PlatformLoginFlow | None: ...

    async def save_flow(self, flow: PlatformLoginFlow) -> PlatformLoginFlow: ...


@runtime_checkable
class PlatformAccountHealthPort(Protocol):
    async def record(self, event: PlatformAccountHealthEvent) -> None: ...


# Short aliases make the contract discoverable for adapters that use the table
# names from the architecture document while preserving the explicit platform
# prefix in the canonical classes.
AccountRef = PlatformAccountRef
AccountSession = PlatformAccountSession
AccountLease = PlatformAccountLease
AccountGrant = PlatformAccountGrant
LoginFlow = PlatformLoginFlow
AccountHealthEvent = PlatformAccountHealthEvent
AccountBoundSourceInvocation = PlatformSourceInvocation
AccountRepositoryPort = PlatformAccountRepositoryPort
AccountSessionReaderPort = PlatformAccountSessionReaderPort
AccountLeasePort = PlatformAccountLeasePort
AccountGrantPort = PlatformAccountGrantPort
LoginFlowPort = PlatformLoginFlowPort
LoginActivityRequest = PlatformLoginActivityRequest
LoginActivityResult = PlatformLoginActivityResult
LoginWorkflowInput = PlatformLoginWorkflowInput
LoginWorkflowOutput = PlatformLoginWorkflowOutput


__all__ = [
    "ACCOUNT_CONTRACT_VERSION",
    "PLATFORM_ACCOUNT_VERSION",
    "PLATFORM_SESSION_VERSION",
    "PLATFORM_LOGIN_VERSION",
    "PLATFORM_LOGIN_ACTIVITY_VERSION",
    "PLATFORM_LOGIN_WORKFLOW_VERSION",
    "PLATFORM_LEASE_VERSION",
    "PLATFORM_SOURCE_INVOCATION_VERSION",
    "AccountBoundSourceInvocation",
    "AccountGrantPort",
    "AccountGrant",
    "AccountGrantPermission",
    "AccountHealthEvent",
    "AccountHealthSignal",
    "AccountId",
    "AccountLease",
    "AccountLeasePort",
    "AccountLeaseRequest",
    "AccountRef",
    "AccountRepositoryPort",
    "AccountSessionReaderPort",
    "AccountSession",
    "EncryptedSessionEnvelope",
    "LOGIN_FLOW_TERMINAL_STATES",
    "LoginChallenge",
    "LoginActivityOperation",
    "LoginActivityRequest",
    "LoginActivityResult",
    "LoginFlow",
    "LoginFlowPort",
    "LoginFlowState",
    "LoginWorkflowInput",
    "LoginWorkflowOutput",
    "PlatformAccount",
    "PlatformAccountGrant",
    "PlatformAccountGrantPort",
    "PlatformAccountHealth",
    "PlatformAccountHealthEvent",
    "PlatformAccountHealthPort",
    "PlatformAccountLease",
    "PlatformAccountLeasePort",
    "PlatformAccountRef",
    "PlatformAccountRepositoryPort",
    "PlatformAccountSessionReaderPort",
    "PlatformAccountStatus",
    "PlatformChannel",
    "PlatformLeaseStatus",
    "PlatformLoginFlow",
    "PlatformLoginFlowPort",
    "PlatformLoginActivityRequest",
    "PlatformLoginActivityResult",
    "PlatformLoginWorkflowInput",
    "PlatformLoginWorkflowOutput",
    "PlatformAccountSession",
    "PlatformSessionStatus",
    "PlatformSourceInvocation",
    "SessionActivationRequest",
    "SessionEnvelopeCodecPort",
    "SessionVersionView",
    "Sha256Digest",
    "TenantId",
    "can_transition_login_flow",
    "validate_login_flow_update",
    "transition_login_flow",
]
