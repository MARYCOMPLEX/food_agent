"""B3 architecture gates for private memory authority boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from xhs_food.contracts import PersonalizedRanking
from xhs_food.foundation.memory_schema import B3_MEMORY_TABLES

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src" / "xhs_food"


@pytest.mark.unit
def test_personalization_has_no_second_memory_or_durable_runtime_import() -> None:
    forbidden = {
        "arq",
        "celery",
        "langgraph",
        "litellm",
        "mem0",
        "mem0ai",
        "zep",
        "zep_cloud",
        "zep_python",
        "pydantic_ai",
        "redis",
    }
    imported: set[str] = set()
    for path in (SRC / "personalization").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
    assert imported.isdisjoint(forbidden)


@pytest.mark.unit
def test_memory_authority_schema_contains_no_framework_message_or_public_score_columns() -> None:
    columns = {
        column.name.lower()
        for table in B3_MEMORY_TABLES
        for column in table.columns
    }
    assert "modelmessage" not in columns
    assert "public_score" not in columns
    assert not any("embedding" in column for column in columns)


@pytest.mark.unit
def test_personalized_ranking_contract_cannot_enable_public_mutation_flags() -> None:
    for field_name in (
        "mutates_public_evidence",
        "mutates_public_features",
        "mutates_public_scores",
    ):
        assert PersonalizedRanking.model_fields[field_name].default is False

    with pytest.raises(ValidationError):
        PersonalizedRanking(
            policy_id="policy",
            policy_version="v1",
            preference_snapshot_id="snapshot",
            preference_snapshot_version=1,
            public_input_digest="0" * 64,
            mutates_public_scores=True,
        )
