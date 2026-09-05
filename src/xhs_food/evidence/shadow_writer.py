"""Shadow source-to-evidence projection used by XHS/Place connector wrappers."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Protocol, cast

from xhs_food.contracts import (
    BundleState,
    CanonicalAuthor,
    CanonicalMediaRef,
    CanonicalSourceBatch,
    CanonicalSourceComment,
    CanonicalSourceDocument,
    CollectRequest,
    ContractPayload,
    EvidenceBundle,
    EvidenceItem,
    EvidenceLicense,
    EvidenceStatus,
    EvidenceVisibility,
    RetentionPolicy,
    SourceConnector,
    SourceLocator,
)
from xhs_food.contracts.evidence_shadow import CanonicalQueryResult

from .canonical import CanonicalQueryNormalizer, UnclassifiedConstraintError
from .source import EvidenceQuarantineError, validate_evidence_provenance

_PRIVATE_PUBLIC_FIELDS = frozenset(
    {
        "account",
        "auth",
        "cookie",
        "credential",
        "credentials",
        "device",
        "device_id",
        "identity",
        "password",
        "private",
        "qr",
        "secret",
        "signed_url",
        "user",
        "user_id",
        "session",
        "session_id",
        "preference",
        "preferences",
        "click",
        "clicks",
        "favorite",
        "favorites",
        "token",
    }
)


@dataclass(frozen=True, slots=True)
class EvidenceShadowPolicy:
    """Governance and typed claim policy supplied by the Domain Pack."""

    evidence_type: str
    claim_type: str
    confidence: float
    extractor_version: str
    schema_version: str
    license: EvidenceLicense
    retention: RetentionPolicy
    visibility: EvidenceVisibility

    def __post_init__(self) -> None:
        # Domain packs commonly load governance from JSON.  Normalize those
        # mappings at the boundary so the immutable policy is always typed.
        if not isinstance(self.license, EvidenceLicense):
            object.__setattr__(self, "license", EvidenceLicense.model_validate(self.license))
        if not isinstance(self.retention, RetentionPolicy):
            object.__setattr__(self, "retention", RetentionPolicy.model_validate(self.retention))
        if not isinstance(self.visibility, EvidenceVisibility):
            object.__setattr__(self, "visibility", EvidenceVisibility.model_validate(self.visibility))


@dataclass(frozen=True, slots=True)
class EvidenceShadowSettings:
    """Closed-world shadow controls; disabled and zero-budget by default."""

    enabled: bool = False
    sample_rate: float = 0.0
    write_budget: int = 0

    def __post_init__(self) -> None:
        if not isfinite(self.sample_rate) or not 0.0 <= self.sample_rate <= 1.0:
            raise ValueError("evidence shadow sample_rate must be between 0 and 1")
        if self.write_budget < 0:
            raise ValueError("evidence shadow write_budget must be non-negative")


class EvidenceShadowGate:
    """Deterministic sampling and per-process write budget for shadow output."""

    def __init__(self, settings: EvidenceShadowSettings | None = None) -> None:
        self._settings = settings or EvidenceShadowSettings()
        self._writes = 0

    def allow(self, family_key: str, evidence_count: int) -> bool:
        # A zero budget is an explicit closed-world setting, not an unlimited
        # budget.  This makes the default and an operator rollback equivalent.
        if (
            not self._settings.enabled
            or self._settings.sample_rate <= 0
            or self._settings.write_budget <= 0
            or evidence_count <= 0
        ):
            return False
        if self._writes + evidence_count > self._settings.write_budget:
            return False
        sample = int(hashlib.sha256(family_key.encode("utf-8")).hexdigest()[:12], 16) / 16**12
        if sample >= self._settings.sample_rate:
            return False
        self._writes += evidence_count
        return True

    @property
    def writes(self) -> int:
        return self._writes

    @property
    def remaining_budget(self) -> int:
        return max(0, self._settings.write_budget - self._writes)


@dataclass(frozen=True, slots=True)
class ShadowWriteRecord:
    batch: CanonicalSourceBatch
    locators: tuple[SourceLocator, ...]
    evidence_items: tuple[EvidenceItem, ...]
    canonical_query: CanonicalQueryResult | None = None
    candidate_bundle: EvidenceBundle | None = None
    source_batch_id: str | None = None

    @property
    def canonical_result(self) -> CanonicalQueryResult | None:
        """Compatibility alias for callers that use the result terminology."""

        return self.canonical_query


class EvidenceShadowSink(Protocol):
    async def write(self, record: ShadowWriteRecord) -> None: ...


class CanonicalQueryShadowSink(Protocol):
    async def save(self, result: CanonicalQueryResult) -> str: ...


ShadowConnectorFactory = Callable[[SourceConnector], SourceConnector]


async def write_shadow_record(
    sink: EvidenceShadowSink,
    record: ShadowWriteRecord,
) -> None:
    await sink.write(record)


class ShadowSourceConnector:
    """Decorator preserving connector results while optionally writing Evidence."""

    def __init__(
        self,
        connector: SourceConnector,
        *,
        policy: EvidenceShadowPolicy,
        sink: EvidenceShadowSink | None = None,
        gate: EvidenceShadowGate | None = None,
        normalizer: CanonicalQueryNormalizer | None = None,
        canonical_query_sink: CanonicalQueryShadowSink | None = None,
        telemetry: Any | None = None,
        # The connector contract is legacy-first: return the source batch as
        # soon as the underlying connector succeeds, then perform shadow work
        # in a detached task.  Qualification and deterministic tests may opt
        # into synchronous writes explicitly.
        defer_shadow: bool = True,
    ) -> None:
        self._connector = connector
        self._policy = policy
        self._sink = sink
        self._gate = gate
        self._normalizer = normalizer
        self._canonical_query_sink = canonical_query_sink
        self._telemetry = telemetry
        self._defer_shadow = defer_shadow
        self._pending_tasks: set[asyncio.Task[None]] = set()

    @property
    def source_id(self) -> str:
        return self._connector.source_id

    async def search(self, request: CollectRequest) -> CanonicalSourceBatch:
        batch = await self._connector.search(request)
        # Do not let malformed connector output enter the shadow projection.
        # SourceGateway still owns the legacy response classification, so the
        # original value is returned unchanged to its caller.
        if not isinstance(batch, CanonicalSourceBatch):
            self._record_telemetry_value("failed")
            return batch
        if batch.source_id != self.source_id:
            self._record_telemetry_value("provenance_rejected")
            return batch
        if self._defer_shadow:
            task = asyncio.create_task(self._shadow(batch, request))
            self._pending_tasks.add(task)
            task.add_done_callback(self._complete_shadow_task)
        else:
            await self._shadow(batch, request)
        return batch

    @property
    def pending_shadow_tasks(self) -> int:
        return len(self._pending_tasks)

    async def aclose(self) -> None:
        """Drain deferred writes when the owning Source Gateway shuts down."""

        pending = tuple(self._pending_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            # The done callback normally removes these tasks as the gather
            # resumes.  Clear explicitly as well so a repeated close is
            # idempotent even when callback delivery is delayed by the loop.
            self._pending_tasks.difference_update(pending)
        close = getattr(self._connector, "aclose", None) or getattr(
            self._connector, "close", None
        )
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result

    async def fetch_document(self, ref: SourceLocator) -> CanonicalSourceDocument:
        return await self._connector.fetch_document(ref)

    async def fetch_comments(
        self, document_ref: SourceLocator, cursor: str | None = None
    ) -> CanonicalSourceBatch:
        return await self._connector.fetch_comments(document_ref, cursor)

    async def list_media_refs(self, owner_ref: SourceLocator) -> tuple[CanonicalMediaRef, ...]:
        return await self._connector.list_media_refs(owner_ref)

    async def _shadow(self, batch: CanonicalSourceBatch, request: CollectRequest) -> None:
        if self._sink is None and self._canonical_query_sink is None:
            return
        try:
            canonical_result = self._canonical_result(request)
            record = build_shadow_record(
                batch,
                self._policy,
                canonical_result=canonical_result,
            )
            if self._gate is not None and not self._gate.allow(
                canonical_result.canonical_key
                if canonical_result is not None
                else _batch_family_key(batch),
                len(record.evidence_items),
            ):
                self._record_telemetry("skipped", batch, len(record.evidence_items))
                return
            self._record_telemetry("sampled", batch, len(record.evidence_items))
            # An atomic SQLAlchemy shadow sink persists canonical identity in
            # the same transaction as the source projection.  Keep the
            # standalone sink path for legacy/test adapters, but never commit
            # canonical identity separately when the selected sink advertises
            # atomic ownership.
            atomic_canonical = bool(
                getattr(self._sink, "supports_atomic_canonical_query", False)
            )
            if (
                self._canonical_query_sink is not None
                and canonical_result is not None
                and not atomic_canonical
            ):
                await self._canonical_query_sink.save(canonical_result)
            if self._sink is not None:
                await self._sink.write(record)
            self._record_telemetry("persisted", batch, len(record.evidence_items))
        except EvidenceQuarantineError:
            self._record_telemetry("provenance_rejected", batch, 0)
        except UnclassifiedConstraintError:
            self._record_telemetry("privacy_rejected", batch, 0)
        except ValueError as exc:
            message = str(exc).casefold()
            outcome = (
                "privacy_rejected"
                if any(
                    marker in message
                    for marker in ("private", "public evidence", "visibility")
                )
                else "provenance_rejected"
                if any(
                    marker in message
                    for marker in ("provenance", "locator", "schema_version", "license")
                )
                else "failed"
            )
            self._record_telemetry(outcome, batch, 0)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Shadow-only failures must not alter the connector's legacy result.
            self._record_telemetry("failed", batch, 0)

    def _canonical_result(self, request: CollectRequest) -> CanonicalQueryResult | None:
        if self._normalizer is None:
            return None
        payload = cast(Mapping[str, object], request.model_dump(mode="json"))
        # CollectRequest nests CanonicalQuery under ``query``; the normalizer
        # accepts the CanonicalQuery-shaped mapping with isolation at its root.
        canonical = payload.get("query")
        if isinstance(canonical, Mapping):
            result = self._normalizer.normalize(canonical)
        else:
            result = self._normalizer.normalize(payload)
        # Personal constraints are useful to the request-time classifier but
        # must never cross the public shadow persistence boundary.  The public
        # Canonical Query already excludes them from its identity projection.
        if result.classification.personal_constraints:
            result = result.model_copy(
                update={
                    "classification": result.classification.model_copy(
                        update={"personal_constraints": ()}
                    )
                }
            )
        return result

    def _record_telemetry_value(self, outcome: str) -> None:
        """Record malformed connector output without requiring a batch."""

        if self._telemetry is None:
            return
        try:
            record = getattr(self._telemetry, "record", None)
            if callable(record):
                record(outcome=outcome, item_count=0)
        except Exception:
            return

    def _record_telemetry(
        self,
        outcome: str,
        batch: CanonicalSourceBatch,
        item_count: int,
    ) -> None:
        if self._telemetry is None:
            return
        try:
            record = getattr(self._telemetry, "record", None)
            if not callable(record):
                return
            record(
                outcome=outcome,
                connector=batch.source_id,
                item_count=max(0, item_count),
            )
        except Exception:
            # Telemetry is non-authoritative and must never become a sink error.
            return

    def _complete_shadow_task(self, task: asyncio.Task[None]) -> None:
        self._pending_tasks.discard(task)
        # Consume a detached task exception so it cannot become an event-loop
        # warning if a future implementation changes the error boundary.
        if not task.cancelled():
            task.exception()


def build_shadow_connector_factory(
    *,
    policy: EvidenceShadowPolicy,
    sink: EvidenceShadowSink | None = None,
    gate: EvidenceShadowGate | None = None,
    normalizer: CanonicalQueryNormalizer | None = None,
    canonical_query_sink: CanonicalQueryShadowSink | None = None,
    telemetry: Any | None = None,
    defer_shadow: bool = True,
) -> ShadowConnectorFactory:
    """Create the connector decorator selected by the Composition Root.

    The returned one-argument factory is intentionally small so a Source
    Gateway can apply it while registering connectors without importing the
    Evidence implementation.  All policy, sink, and lifecycle dependencies
    are captured once for the gateway instance; each connector gets its own
    pending-task set and therefore can be drained independently on shutdown.
    """

    def decorate(connector: SourceConnector) -> SourceConnector:
        return ShadowSourceConnector(
            connector,
            policy=policy,
            sink=sink,
            gate=gate,
            normalizer=normalizer,
            canonical_query_sink=canonical_query_sink,
            telemetry=telemetry,
            defer_shadow=defer_shadow,
        )

    return decorate


def build_shadow_record(
    batch: CanonicalSourceBatch,
    policy: EvidenceShadowPolicy,
    *,
    canonical_result: CanonicalQueryResult | None = None,
) -> ShadowWriteRecord:
    _assert_public_batch(batch)
    _validate_shadow_policy(policy)
    if batch.isolation.tenant_scope != "public":
        raise ValueError("public Evidence requires a public batch partition")
    if (
        canonical_result is not None
        and canonical_result.canonical_query.isolation != batch.isolation
    ):
        raise ValueError("canonical query and source batch partitions must match")
    locators: list[SourceLocator] = []
    evidence_items: list[EvidenceItem] = []
    for kind, item in _source_items(batch):
        locator = _locator(batch, kind, item, policy)
        evidence = _evidence(kind, item, locator, policy)
        validate_evidence_provenance(
            evidence,
            locator=locator,
            isolation=batch.isolation,
            expected_schema_version=policy.schema_version,
            require_public=True,
            validate_content_hash=True,
        )
        locators.append(locator)
        evidence_items.append(evidence)
    source_batch_id = source_batch_identity(batch)
    candidate_bundle = (
        _build_candidate_bundle(
            canonical_result,
            batch,
            tuple(locators),
            tuple(evidence_items),
            policy,
        )
        if evidence_items
        else None
    )
    return ShadowWriteRecord(
        batch=batch,
        locators=tuple(locators),
        evidence_items=tuple(evidence_items),
        canonical_query=canonical_result,
        candidate_bundle=candidate_bundle,
        source_batch_id=source_batch_id,
    )


def _assert_public_batch(batch: CanonicalSourceBatch) -> None:
    violations = sorted(_private_field_paths(batch.model_dump(mode="json")))
    if violations:
        raise ValueError(
            "public Evidence cannot contain private fields: " + ", ".join(violations)
        )


def _private_field_paths(value: object, path: str = "batch") -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = "".join(character for character in str(key).casefold() if character.isalnum())
            child_path = f"{path}.{key}"
            private_names = {
                "".join(character for character in field.casefold() if character.isalnum())
                for field in _PRIVATE_PUBLIC_FIELDS
            }
            prefixes = (
                "account",
                "credential",
                "device",
                "identity",
                "password",
                "private",
                "qr",
                "secret",
                "signed_url",
                "user",
                "session",
                "preference",
                "click",
                "favorite",
                "token",
            )
            # ``author_external_id`` is a public source identity, while
            # ``auth*`` denotes credentials.  Keep the latter exact to avoid
            # treating the former as an authentication field.
            private_prefix = any(
                name.startswith(
                    "".join(character for character in prefix.casefold() if character.isalnum())
                )
                for prefix in prefixes
            )
            auth_field = name == "auth" or (name.startswith("auth") and not name.startswith("author"))
            if name in private_names or private_prefix or auth_field:
                found.append(child_path)
            found.extend(_private_field_paths(item, child_path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_private_field_paths(item, f"{path}[{index}]"))
    return tuple(found)


def _source_items(
    batch: CanonicalSourceBatch,
) -> tuple[
    tuple[str, CanonicalSourceDocument | CanonicalSourceComment | CanonicalAuthor], ...
]:
    return tuple(
        (kind, item)
        for kind, values in (
            ("document", batch.documents),
            ("comment", batch.comments),
            ("author", batch.authors),
        )
        for item in values
    )


def _batch_family_key(batch: CanonicalSourceBatch) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "isolation": batch.isolation.model_dump(mode="json"),
                "source_id": batch.source_id,
                "connector_id": batch.connector_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def source_batch_identity(batch: CanonicalSourceBatch) -> str:
    """Return a stable opaque identity for one canonical source batch."""

    encoded = json.dumps(
        batch.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"batch.{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _locator(
    batch: CanonicalSourceBatch,
    kind: str,
    item: CanonicalSourceDocument | CanonicalSourceComment | CanonicalAuthor,
    policy: EvidenceShadowPolicy,
) -> SourceLocator:
    external_id = item.external_id
    digest = hashlib.sha256(f"{batch.source_id}:{kind}:{external_id}".encode()).hexdigest()[:32]
    return SourceLocator(
        locator_id=f"locator.{batch.source_id}.{digest}",
        source_id=batch.source_id,
        connector_id=batch.connector_id,
        connector_version=batch.connector_version,
        external_id=external_id,
        canonical_url=item.canonical_url,
        captured_at=item.captured_at,
        source_updated_at=item.source_updated_at,
        watermark=batch.watermark,
        visibility=policy.visibility,
        license=policy.license,
        retention=policy.retention,
    )


def _evidence(
    kind: str,
    item: CanonicalSourceDocument | CanonicalSourceComment | CanonicalAuthor,
    locator: SourceLocator,
    policy: EvidenceShadowPolicy,
) -> EvidenceItem:
    claim_value: ContractPayload = {
        "source_id": item.source_id,
        "external_id": item.external_id,
        "kind": kind,
    }
    for key in ("title", "text", "display_name", "document_external_id"):
        value = getattr(item, key, None)
        if isinstance(value, str) and value:
            claim_value[key] = value
    encoded = json.dumps(
        {
            "claim_type": policy.claim_type,
            "claim_value": claim_value,
            "evidence_type": policy.evidence_type,
            "source_locator_id": locator.locator_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    content_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return EvidenceItem(
        # Content identity is immutable.  A corrected delivery therefore gets
        # a new candidate row rather than being swallowed as a replay.
        evidence_id=(
            f"evidence.{locator.locator_id.removeprefix('locator.')}"
            f".{content_hash[:16]}"
        ),
        evidence_type=cast(str, policy.evidence_type),
        claim_type=cast(str, policy.claim_type),
        claim_value=claim_value,
        confidence=policy.confidence,
        source_locator_id=locator.locator_id,
        media_ref_ids=(),
        derived_artifact_ids=(),
        extractor_version=policy.extractor_version,
        schema_version=policy.schema_version,
        content_hash=content_hash,
        status=EvidenceStatus.CANDIDATE,
        visibility=policy.visibility,
        license=policy.license,
        retention=policy.retention,
    )


def _validate_shadow_policy(policy: EvidenceShadowPolicy) -> None:
    if policy.visibility.scope.value != "public" or policy.visibility.tenant_scope != "public":
        raise ValueError("public Evidence shadow policy requires public visibility")
    if policy.visibility.entitlement_ids:
        raise ValueError("public Evidence shadow policy cannot carry entitlements")
    if policy.license.status.value != "known":
        raise ValueError("public Evidence shadow policy requires a known license")
    if policy.license.allowed_use.value not in {"internal_reuse", "redistributable"}:
        raise ValueError("public Evidence shadow policy requires reusable license rights")
    if policy.license.expires_at is not None and policy.license.expires_at <= datetime.now(UTC):
        raise ValueError("public Evidence shadow policy license is expired")


def _build_candidate_bundle(
    canonical_result: CanonicalQueryResult | None,
    batch: CanonicalSourceBatch,
    locators: tuple[SourceLocator, ...],
    items: tuple[EvidenceItem, ...],
    policy: EvidenceShadowPolicy,
) -> EvidenceBundle:
    if canonical_result is None:
        family_digest = _batch_family_key(batch)
        family_id = f"family.{batch.source_id}.{family_digest[:32]}"
        freshness_policy_id = "shadow.default"
        freshness_policy_version = "shadow-freshness/v1"
    else:
        family_id = canonical_result.family_id
        freshness_policy_id = canonical_result.canonical_query.query.freshness_policy.policy_id
        freshness_policy_version = (
            canonical_result.canonical_query.query.freshness_policy.policy_version
        )
    item_projection = [
        {
            "evidence_id": item.evidence_id,
            "content_hash": item.content_hash,
            "source_locator_id": item.source_locator_id,
        }
        for item in items
    ]
    content_hash = _sha256(
        {
            "family_id": family_id,
            "items": item_projection,
        }
    )
    provenance_hash = _sha256(
        {
            "locators": [locator.model_dump(mode="json") for locator in locators],
            "items": [item.model_dump(mode="json") for item in items],
        }
    )
    captured = (*batch.documents, *batch.comments, *batch.authors)
    verified_at = max(
        (item.captured_at for item in captured),
        default=datetime.now(UTC),
    )
    bundle_id = f"bundle.{family_id.removeprefix('family.')}.candidate.{content_hash[:16]}"
    if len(bundle_id) > 128:
        bundle_id = f"bundle.{hashlib.sha256(bundle_id.encode('utf-8')).hexdigest()[:56]}"
    return EvidenceBundle(
        bundle_id=bundle_id,
        family_id=family_id,
        bundle_version=1,
        parent_bundle_version=None,
        state=BundleState.CANDIDATE,
        evidence_ids=tuple(item.evidence_id for item in items),
        coverage={"source_provenance": 1.0, "public_attributes": 1.0},
        watermarks={batch.source_id: batch.watermark} if batch.watermark else {},
        verified_at=verified_at,
        freshness_policy_id=freshness_policy_id,
        freshness_policy_version=freshness_policy_version,
        provenance_hash=provenance_hash,
        content_hash=content_hash,
        visibility=policy.visibility,
        retention=policy.retention,
    )


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "EvidenceShadowPolicy",
    "EvidenceShadowGate",
    "EvidenceShadowSettings",
    "EvidenceShadowSink",
    "CanonicalQueryShadowSink",
    "ShadowConnectorFactory",
    "ShadowSourceConnector",
    "ShadowWriteRecord",
    "build_shadow_connector_factory",
    "build_shadow_record",
    "source_batch_identity",
    "write_shadow_record",
]
