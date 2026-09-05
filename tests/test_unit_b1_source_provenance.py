"""Offline source-batch normalization and provenance quarantine contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from xhs_food.contracts import (
    EvidenceItem,
    IsolationCoordinates,
    SourceLocator,
)
from xhs_food.evidence import (
    CanonicalSourceBatchNormalizer,
    EvidenceQuarantineError,
    SourceNormalizationError,
    quarantine_evidence,
    validate_evidence_provenance,
)
from xhs_food.evidence.source import evidence_content_hash

FIXTURE = Path(__file__).parent / "fixtures" / "authority" / "evidence_bundle_v1.json"
NOW = datetime(2026, 8, 24, tzinfo=UTC)


@pytest.mark.unit
def test_source_batch_normalizer_canonicalizes_ids_urls_and_excludes_binary() -> None:
    batch = CanonicalSourceBatchNormalizer().normalize(
        {
            "isolation": {"tenant_scope": "public", "language": "en", "region": "US"},
            "source_id": "fixture-source",
            "connector_id": "fixture.connector",
            "connector_version": "fixture-connector/v1",
            "watermark": "opaque:42",
            "documents": [
                {
                    "id": "note-1",
                    "url": "HTTPS://SOURCE.INVALID/note/1?utm_source=x&b=2&a=1#comments",
                    "captured_at": NOW,
                    "title": "Fixture",
                }
            ],
        }
    )

    assert batch.documents[0].external_id == "note-1"
    assert str(batch.documents[0].canonical_url) == "https://source.invalid/note/1?a=1&b=2"
    assert batch.watermark == "opaque:42"
    assert batch.documents[0].captured_at == NOW

    with pytest.raises(SourceNormalizationError, match="binary"):
        CanonicalSourceBatchNormalizer().normalize(
            {
                "isolation": {"tenant_scope": "public", "language": "en", "region": "US"},
                "source_id": "fixture-source",
                "connector_id": "fixture.connector",
                "connector_version": "fixture-connector/v1",
                "documents": [
                    {
                        "id": "note-1",
                        "url": "https://source.invalid/1",
                        "captured_at": NOW,
                        "raw": b"bytes",
                    }
                ],
            }
        )


@pytest.mark.unit
def test_provenance_validator_quarantines_missing_locator_or_schema() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    item = EvidenceItem.model_validate(fixture["evidence_items"][0])
    locator = SourceLocator.model_validate(fixture["source_locators"][0])
    isolation = IsolationCoordinates.model_validate(fixture["isolation"])

    assert validate_evidence_provenance(item, locator=locator, isolation=isolation) == item

    with pytest.raises(EvidenceQuarantineError) as missing:
        validate_evidence_provenance(item, locator=None)
    quarantined = quarantine_evidence(item, missing.value)
    assert quarantined.status.value == "quarantined"

    invalid = item.model_copy(update={"schema_version": "other-evidence/v1"})
    with pytest.raises(EvidenceQuarantineError, match="schema_version"):
        validate_evidence_provenance(invalid, locator=locator)


@pytest.mark.unit
def test_provenance_validator_rejects_locator_id_or_partition_mismatch() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    item = EvidenceItem.model_validate(fixture["evidence_items"][0])
    locator = SourceLocator.model_validate(fixture["source_locators"][0])
    other_locator = locator.model_copy(update={"locator_id": "source.other.123"})
    with pytest.raises(EvidenceQuarantineError, match="locator_id"):
        validate_evidence_provenance(item, locator=other_locator)

    other_partition = locator.model_copy(
        update={
            "visibility": {
                "scope": "tenant",
                "tenant_scope": "tenant:other",
                "entitlement_ids": [],
            }
        }
    )
    with pytest.raises(EvidenceQuarantineError, match="partition"):
        validate_evidence_provenance(
            item,
            locator=other_partition,
            isolation=IsolationCoordinates(
                tenant_scope="tenant:fixture", language="en", region="US"
            ),
        )


@pytest.mark.unit
def test_provenance_validator_rejects_content_hash_and_broadened_license() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    item = EvidenceItem.model_validate(fixture["evidence_items"][0])
    locator = SourceLocator.model_validate(fixture["source_locators"][0])
    valid_hash_item = item.model_copy(update={"content_hash": evidence_content_hash(item)})
    assert (
        validate_evidence_provenance(
            valid_hash_item,
            locator=locator,
            validate_content_hash=True,
        )
        == valid_hash_item
    )

    invalid_hash_item = valid_hash_item.model_copy(update={"content_hash": "0" * 64})
    with pytest.raises(EvidenceQuarantineError, match="content_hash"):
        validate_evidence_provenance(
            invalid_hash_item,
            locator=locator,
            validate_content_hash=True,
        )

    broadened = valid_hash_item.model_copy(
        update={
            "license": {
                **valid_hash_item.license.model_dump(mode="json"),
                "allowed_use": "redistributable",
            }
        }
    )
    with pytest.raises(EvidenceQuarantineError, match="broadens_locator"):
        validate_evidence_provenance(broadened, locator=locator)


@pytest.mark.unit
def test_source_batch_normalizer_wraps_malformed_top_level_and_contract_values() -> None:
    normalizer = CanonicalSourceBatchNormalizer()
    with pytest.raises(SourceNormalizationError, match="source batch must be an object"):
        normalizer.normalize(None)  # type: ignore[arg-type]
    with pytest.raises(SourceNormalizationError, match="invalid source batch"):
        normalizer.normalize({"isolation": {}, "source_id": "fixture"})
