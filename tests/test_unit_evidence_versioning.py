"""Regression coverage for lossless comment updates in the evidence ledger."""

from __future__ import annotations

from typing import Any

import pytest

from xhs_food.contracts import CommentEvidence, XhsNoteLead
from xhs_food.research.evidence import EvidenceLedger


class _Lifecycle:
    def __init__(self) -> None:
        self.notes: list[XhsNoteLead] = []

    async def write(self, note: XhsNoteLead) -> None:
        self.notes.append(note)


def _note(*, text: str, likes: int, payload: dict[str, Any]) -> XhsNoteLead:
    return XhsNoteLead(
        note_id="note-1",
        title="火锅",
        comments=(
            CommentEvidence(
                note_id="note-1",
                comment_id="comment-1",
                text=text,
                likes=likes,
                raw_payload=payload,
            ),
        ),
        comment_count=1,
        comment_collected_count=1,
    )


@pytest.mark.asyncio
async def test_ledger_preserves_replays_and_delivers_changed_comment_versions() -> None:
    lifecycle = _Lifecycle()
    delivered: list[str] = []

    async def sink(evidence: CommentEvidence) -> None:
        delivered.append(evidence.text)

    ledger = EvidenceLedger(sink=sink, lifecycle=lifecycle)
    first = _note(text="先说一般", likes=1, payload={"rank": 1})
    changed = _note(text="回访后很惊艳", likes=9, payload={"rank": 2})

    await ledger.record(first)
    await ledger.record(first)  # exact replay: retain it, but do not redeliver
    await ledger.record(changed)  # same ref, changed provider observation

    record = ledger.records[0]
    assert record.evidence.text == "回访后很惊艳"
    assert record.history[0].text == "先说一般"
    assert len(record.versions) == 2
    assert len(record.occurrences) == 3
    assert delivered == ["先说一般", "回访后很惊艳"]
    # The note lifecycle sees the initial and changed comment snapshots, but
    # not an identical replay.
    assert len(lifecycle.notes) == 2

    exported = ledger.export()[0]
    assert exported["text"] == "回访后很惊艳"
    assert [item["text"] for item in exported["versions"]] == [
        "先说一般",
        "回访后很惊艳",
    ]
    assert [item["raw_payload"] for item in exported["occurrences"]] == [
        {"rank": 1},
        {"rank": 1},
        {"rank": 2},
    ]
