"""Comment evidence boundary for the comment-first research workflow.

The workflow keeps a small idempotent index for response references, but the
authoritative evidence shape is still the existing canonical source/evidence
pipeline. ``CanonicalCommentEvidenceAdapter`` converts the new source DTOs to
that pipeline and can hand its shadow record to the existing Bundle sink.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import AnyUrl, TypeAdapter

from xhs_food.contracts import (
    CanonicalSourceBatch,
    CanonicalSourceComment,
    CanonicalSourceDocument,
    CommentEvidence,
    CommentEvidenceLifecyclePort,
    EvidenceLicense,
    EvidenceVisibility,
    IsolationCoordinates,
    LicenseStatus,
    LicenseUse,
    RetentionPolicy,
    VisibilityScope,
    XhsNoteLead,
)
from xhs_food.evidence.shadow_writer import (
    EvidenceShadowPolicy,
    EvidenceShadowSink,
    ShadowWriteRecord,
    build_shadow_record,
)

EvidenceSink = Callable[[CommentEvidence], Awaitable[object] | object]
_URL_ADAPTER = TypeAdapter(AnyUrl)


class EvidenceLifecycleError(RuntimeError):
    """A canonical evidence projection could not be handed to its sink."""


class CanonicalCommentEvidenceAdapter:
    """Adapt XHS comments to the existing canonical Evidence/Bundle boundary.

    User identity is intentionally absent from the public canonical
    projection. The original provider payload remains on ``CommentEvidence``
    for the private evidence store, while the existing public-evidence
    validator receives only non-identifying observations.
    """

    def __init__(
        self,
        sink: EvidenceShadowSink | None = None,
        *,
        isolation: IsolationCoordinates | None = None,
        policy: EvidenceShadowPolicy | None = None,
        connector_id: str = "xhs-mcp",
        connector_version: str = "xhs-mcp/v1",
    ) -> None:
        self._sink = sink
        self._isolation = isolation or IsolationCoordinates(
            tenant_scope="public",
            language="zh",
            region="CN",
        )
        self._policy = policy or _default_shadow_policy()
        self._connector_id = connector_id
        self._connector_version = connector_version
        self._batches: list[CanonicalSourceBatch] = []
        self._records: list[ShadowWriteRecord] = []

    @property
    def batches(self) -> tuple[CanonicalSourceBatch, ...]:
        return tuple(self._batches)

    @property
    def records(self) -> tuple[ShadowWriteRecord, ...]:
        return tuple(self._records)

    async def write(self, note: XhsNoteLead) -> None:
        batch = self.to_batch(note)
        self._batches.append(batch)
        if self._sink is None:
            return
        record = build_shadow_record(batch, self._policy)
        self._records.append(record)
        await self._sink.write(record)

    def to_batch(self, note: XhsNoteLead) -> CanonicalSourceBatch:
        captured_at = datetime.now(UTC)
        canonical_url = _canonical_url(
            note.url or f"https://www.xiaohongshu.com/explore/{note.note_id}",
            note.note_id,
        )
        document = CanonicalSourceDocument(
            source_id="xhs",
            external_id=note.note_id,
            canonical_url=canonical_url,
            captured_at=captured_at,
            source_updated_at=captured_at,
            title=note.title or None,
            text=note.summary or None,
            attributes={
                "comment_count": note.comment_count,
                "comment_expected_count": note.comment_expected_count,
                "comment_collected_count": note.comment_collected_count,
                "comment_completeness": note.comment_completeness,
                "comment_pages": note.comment_pages,
            },
        )
        comments = tuple(
            CanonicalSourceComment(
                source_id="xhs",
                external_id=item.comment_id,
                document_external_id=note.note_id,
                canonical_url=canonical_url,
                captured_at=item.created_at or captured_at,
                source_updated_at=item.created_at,
                text=item.text or None,
                attributes=_public_comment_attributes(item),
            )
            for item in note.comments
        )
        return CanonicalSourceBatch(
            isolation=self._isolation,
            source_id="xhs",
            connector_id=self._connector_id,
            connector_version=self._connector_version,
            normalizer_version="research-source-normalizer/v1",
            documents=(document,),
            comments=comments,
            authors=(),
            media_refs=(),
            watermark=None,
            next_cursor=note.comment_cursor,
            errors=(),
        )


class EvidenceRecord:
    """Stable response reference paired with every observed comment version.

    The current ``evidence`` value is the latest provider observation.  The
    additive ``occurrences`` and ``versions`` collections make an update to a
    provider row observable without allowing duplicate rows to inflate the
    analysis score.  ``occurrences`` intentionally includes byte-for-byte
    repeats; a replay is still useful when auditing the provider response.
    """

    __slots__ = ("ref", "evidence", "occurrences", "versions")

    def __init__(
        self,
        ref: str,
        evidence: CommentEvidence,
        *,
        occurrences: Sequence[CommentEvidence] | None = None,
        versions: Sequence[CommentEvidence] | None = None,
    ) -> None:
        self.ref = ref
        self.evidence = evidence
        self.occurrences = list(occurrences or (evidence,))
        self.versions = list(versions or (evidence,))

    @property
    def history(self) -> tuple[CommentEvidence, ...]:
        """All distinct versions before the current one, in observation order."""

        return tuple(self.versions[:-1])


class EvidenceLedger:
    """Idempotent response index plus the existing evidence lifecycle bridge."""

    def __init__(
        self,
        sink: EvidenceSink | None = None,
        *,
        lifecycle: CommentEvidenceLifecyclePort | None = None,
    ) -> None:
        self._sink = sink
        self._lifecycle = lifecycle or CanonicalCommentEvidenceAdapter()
        self._records: dict[str, EvidenceRecord] = {}
        self._written_note_signatures: set[str] = set()
        # A failed sink write must be retryable, while a successful replay of
        # the same version must remain idempotent.
        self._delivered_signatures: set[tuple[str, str]] = set()
        self._lifecycle_errors: list[Mapping[str, Any]] = []

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        return tuple(self._records.values())

    @property
    def lifecycle(self) -> CommentEvidenceLifecyclePort | None:
        return self._lifecycle

    @property
    def lifecycle_errors(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._lifecycle_errors)

    async def record(self, note: XhsNoteLead) -> tuple[str, ...]:
        signature = _note_signature(note)
        if signature not in self._written_note_signatures and self._lifecycle is not None:
            try:
                await self._lifecycle.write(note)
                self._written_note_signatures.add(signature)
            except Exception as exc:  # evidence index remains available for retry
                self._lifecycle_errors.append(
                    {
                        "note_id": note.note_id,
                        "code": "evidence_lifecycle_write_failed",
                        "message": type(exc).__name__,
                    }
                )
        refs: list[str] = []
        for evidence in note.comments:
            ref = evidence_ref(evidence)
            signature = _evidence_signature(evidence)
            record = self._records.get(ref)
            if record is None:
                record = EvidenceRecord(ref=ref, evidence=evidence)
                self._records[ref] = record
            else:
                # Keep every raw occurrence, but only add a new semantic
                # version when the provider payload actually changed.
                record.occurrences.append(evidence)
                if _evidence_signature(record.evidence) != signature:
                    record.evidence = evidence
                    record.versions.append(evidence)

            delivery_key = (ref, signature)
            if self._sink is not None and delivery_key not in self._delivered_signatures:
                result = self._sink(evidence)
                if inspect.isawaitable(result):
                    await result
                self._delivered_signatures.add(delivery_key)
            refs.append(ref)
        return tuple(dict.fromkeys(refs))

    async def record_many(self, notes: Sequence[XhsNoteLead]) -> tuple[str, ...]:
        refs: list[str] = []
        for note in notes:
            refs.extend(await self.record(note))
        return tuple(dict.fromkeys(refs))

    def get(self, ref: str) -> CommentEvidence | None:
        record = self._records.get(ref)
        return record.evidence if record else None

    def export(self) -> tuple[Mapping[str, Any], ...]:
        """Return a lossless JSON-ready projection for audits/tests."""

        return tuple(
            {
                **_export_evidence(item.evidence),
                "ref": item.ref,
                # ``versions`` is the semantic update history; ``occurrences``
                # is the complete lossless replay stream, including repeats.
                "versions": [_export_evidence(value) for value in item.versions],
                "occurrences": [
                    _export_evidence(value) for value in item.occurrences
                ],
            }
            for item in self._records.values()
        )


def evidence_ref(evidence: CommentEvidence) -> str:
    return f"{evidence.source}:note:{evidence.note_id}:comment:{evidence.comment_id}"


def _evidence_signature(evidence: CommentEvidence) -> str:
    """Fingerprint the complete typed/raw observation for update detection."""

    encoded = json.dumps(
        evidence.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _export_evidence(evidence: CommentEvidence) -> dict[str, Any]:
    """Serialize one version without dropping opaque provider fields."""

    return {
        "source": evidence.source,
        "note_id": evidence.note_id,
        "comment_id": evidence.comment_id,
        "text": evidence.text,
        "author": dict(evidence.author),
        "likes": evidence.likes,
        "replies": evidence.replies,
        "created_at": evidence.created_at.isoformat()
        if evidence.created_at
        else None,
        "raw_payload": evidence.raw_payload,
        "provenance": dict(evidence.provenance),
        "metadata": dict(evidence.metadata),
    }


def _default_shadow_policy() -> EvidenceShadowPolicy:
    return EvidenceShadowPolicy(
        evidence_type="review_trust",
        claim_type="comment_observation",
        confidence=1.0,
        extractor_version="comment-first/v1",
        schema_version="food-evidence/v1",
        license=EvidenceLicense(
            license_id="provider-extract",
            status=LicenseStatus.UNKNOWN,
            allowed_use=LicenseUse.EXTRACT_ONLY,
            attribution_required=True,
            expires_at=None,
            policy_version="evidence-policy/v1",
        ),
        retention=RetentionPolicy(
            retention_class="provider-comment",
            duration_seconds=None,
            legal_hold=False,
        ),
        visibility=EvidenceVisibility(
            scope=VisibilityScope.PUBLIC,
            tenant_scope="public",
            entitlement_ids=(),
        ),
    )


def _public_comment_attributes(item: CommentEvidence) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "likes": item.likes,
        "replies": item.replies,
    }
    for key in ("is_reply", "page_cursor"):
        value = item.metadata.get(key)
        if value not in (None, "", [], {}, ()):
            attributes[key] = value
    return attributes


def _note_signature(note: XhsNoteLead) -> str:
    payload = {
        "note_id": note.note_id,
        "cursor": note.comment_cursor,
        "comments": [
            {
                "id": item.comment_id,
                "text": item.text,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "raw": item.raw_payload,
            }
            for item in note.comments
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _canonical_url(value: str, note_id: str) -> AnyUrl:
    """Validate provider URLs while retaining a deterministic safe fallback."""

    try:
        return _URL_ADAPTER.validate_python(value)
    except Exception:
        return _URL_ADAPTER.validate_python(
            f"https://www.xiaohongshu.com/explore/{note_id}"
        )


__all__ = [
    "CanonicalCommentEvidenceAdapter",
    "EvidenceLedger",
    "EvidenceLifecycleError",
    "EvidenceRecord",
    "evidence_ref",
]
