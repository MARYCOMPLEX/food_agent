"""Offline candidate Bundle repository and dedupe gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect

from xhs_food.composition.adapters import SQLAlchemyCandidateBundleRepository
from xhs_food.contracts import BundleState, EvidenceBundle, EvidenceItem
from xhs_food.foundation.evidence_schema import evidence_bundles

FIXTURE = Path(__file__).parent / "fixtures" / "authority" / "evidence_bundle_v1.json"


def _candidate() -> tuple[EvidenceBundle, tuple[EvidenceItem, ...]]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    bundle = EvidenceBundle.model_validate(value["bundles"][0]).model_copy(
        update={"state": BundleState.CANDIDATE}
    )
    items = tuple(EvidenceItem.model_validate(item) for item in value["evidence_items"])
    return bundle, items


@pytest.mark.unit
async def test_candidate_repository_writes_items_and_bundle_in_one_transaction() -> None:
    class Session:
        def __init__(self) -> None:
            self.statements: list[Any] = []

        async def execute(self, statement: Any) -> None:
            self.statements.append(statement)

    class Unit:
        def __init__(self, session: Session) -> None:
            self.session = session
            self.commits = 0

        async def __aenter__(self) -> Unit:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def session_for_adapter(self) -> Session:
            return self.session

        async def commit(self) -> None:
            self.commits += 1

    session = Session()
    unit = Unit(session)
    repository = SQLAlchemyCandidateBundleRepository(lambda: unit)  # type: ignore[arg-type]
    bundle, items = _candidate()
    assert await repository.save_candidate(bundle, items) == bundle
    assert unit.commits == 1
    assert len(session.statements) == len(items) + 1
    assert all("DO NOTHING" in str(statement.compile(dialect=postgresql_dialect())) for statement in session.statements)
    assert "evidence_bundle_current" not in str(session.statements[-1])
    params = session.statements[-1].compile(dialect=postgresql_dialect()).params
    assert params["parent_bundle_id"] is None
    assert any(index.name == "uq_evidence_bundles_family_content" for index in evidence_bundles.indexes)


@pytest.mark.unit
async def test_candidate_repository_rejects_published_or_mismatched_candidates() -> None:
    class Unit:
        async def __aenter__(self) -> Unit:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    repository = SQLAlchemyCandidateBundleRepository(lambda: Unit())  # type: ignore[arg-type]
    bundle, items = _candidate()
    with pytest.raises(ValueError, match="candidate Bundles"):
        await repository.save_candidate(bundle.model_copy(update={"state": BundleState.PUBLISHED}), items)
    with pytest.raises(ValueError, match="evidence_ids"):
        await repository.save_candidate(bundle, items[:-1])
