"""Reviewable contract gates for the accepted HTTP/SSE authority decision."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "tests" / "fixtures" / "authority"
DECISIONS = (
    ROOT
    / "openspec"
    / "changes"
    / "define-modular-architecture"
    / "decisions"
)


def _json(name: str) -> dict[str, Any]:
    return json.loads((AUTHORITY / name).read_text(encoding="utf-8"))


def _parse_sse(name: str) -> list[dict[str, Any]]:
    raw = (AUTHORITY / name).read_bytes()
    assert b"\r" not in raw, "fixtures are reviewed with LF and normalized to CRLF on wire"
    blocks = raw.decode("utf-8").strip().split("\n\n")
    events: list[dict[str, Any]] = []
    for block in blocks:
        event: dict[str, Any] = {}
        for line in block.splitlines():
            field, value = line.split(":", maxsplit=1)
            value = value.removeprefix(" ")
            event[field] = json.loads(value) if field == "data" else value
        events.append(event)
    return events


def test_adr_and_index_accept_http_sse_authority() -> None:
    adr = (DECISIONS / "ADR-0004-http-sse-authority.md").read_text(encoding="utf-8")
    index = (DECISIONS / "README.md").read_text(encoding="utf-8")

    assert "Status: Accepted" in adr
    assert "`POST /v1/search/` is the sole canonical v1" in adr
    assert "| 16 |" in index and "| S2 | Accepted | [ADR-0004]" in index
    assert "| 17 |" in index and index.count("| S2 | Accepted | [ADR-0004]") == 2


def test_http_authority_selects_server_envelopes_and_pagination() -> None:
    fixture = _json("http_v1_authority.schema.json")
    authority = fixture["x-authority"]

    assert fixture["$schema"].endswith("draft/2020-12/schema")
    assert authority["search"] == {
        "canonicalCommand": {"method": "POST", "path": "/v1/search/"},
        "dispatch": {
            "new": ["query"],
            "refine": ["sessionId", "query"],
            "recover": ["sessionId"],
        },
        "deprecatedDocumentationOnlyPaths": [
            "POST /v1/search/start",
            "POST /v1/search/refine",
            "GET /v1/search/recover/{sessionId}",
        ],
        "sessionIdLocation": "data.sessionId",
    }
    assert authority["history"] == {
        "queryParameters": ["limit", "offset"],
        "itemsLocation": "data.items",
        "paginationLocations": ["data.total", "data.limit", "data.offset"],
    }
    assert authority["favorites"]["itemsLocation"] == "data.items"
    assert authority["faq"]["itemsLocation"] == "data"
    assert authority["errors"]["transportField"] == "detail"


def test_every_http_ruling_has_schema_and_reviewable_example() -> None:
    fixture = _json("http_v1_authority.schema.json")
    schemas = fixture["$defs"]
    examples = fixture["x-fixture-examples"]
    expected = {
        "searchCommandResponse",
        "historyListResponse",
        "favoritesListResponse",
        "faqListResponse",
        "fastApiErrorResponse",
    }

    assert set(schemas) == expected
    assert set(examples) == expected
    for name in expected:
        schema = schemas[name]
        example = examples[name]
        assert set(schema["required"]) <= set(example)
        assert set(example) <= set(schema["properties"])

    search = examples["searchCommandResponse"]
    assert "sessionId" not in search
    assert search["data"]["sessionId"] == "session-authority-1"

    history = examples["historyListResponse"]["data"]
    assert set(history) == {"items", "total", "limit", "offset"}
    assert not ({"history", "page", "pageSize"} & set(history))

    favorites = examples["favoritesListResponse"]["data"]
    assert set(favorites) == {"items", "total"}
    assert "favorites" not in favorites
    assert isinstance(examples["faqListResponse"]["data"], list)


def test_sse_v1_negotiation_semantic_steps_and_field_authority() -> None:
    contract = _json("sse_v1_contract.json")

    assert contract["contractVersion"] == "v1"
    assert contract["negotiation"] == {
        "queryParameter": "sseVersion",
        "explicitValue": "v1",
        "legacyValue": "legacy",
        "omittedDuringCompatibilityWindow": "legacy",
        "responseHeader": {"X-SSE-Version": "v1"},
        "unsupportedStatus": 406,
        "unsupportedCode": "unsupported_sse_version",
        "cursorHeader": "Last-Event-ID",
        "rejectedCursorAlias": "lastEventIndex",
    }
    assert contract["semanticSteps"] == [
        "intent_parsing",
        "evidence_collection",
        "evidence_analysis",
        "evidence_validation",
        "entity_enrichment",
        "result_generation",
    ]
    assert list(contract["legacyMappings"]["server"]) == [
        "step1",
        "step2",
        "step3",
        "step4",
        "step5",
        "step6",
    ]
    assert set(contract["legacyMappings"]["server"].values()) == set(
        contract["semanticSteps"]
    )
    assert contract["fieldAuthority"]["detail"].startswith("optional")
    assert contract["fieldAuthority"]["message"].endswith("on done")
    assert contract["fieldAuthority"]["error"]["required"] == [
        "code",
        "message",
        "retryable",
    ]
    assert contract["terminal"] == {
        "events": ["done", "error"],
        "exactlyOnePer": ["taskId", "turnId"],
        "resultIsTerminal": False,
        "stepErrorIsTerminal": False,
        "publishAfter": "authoritative_postgresql_projection_commit",
    }


def test_retained_window_wire_is_exclusive_and_preserves_terminal_identity() -> None:
    contract = _json("sse_v1_contract.json")
    events = _parse_sse(contract["wireFixtures"]["retainedWindow"])
    cursor = contract["replay"]["retainedFixtureCursor"]

    assert contract["replay"]["retainedCursor"] == "exclusive"
    assert cursor not in {event.get("id") for event in events}
    assert [event["id"] for event in events] == [
        "1734567890000-1",
        "1734567890000-2",
        "1734567890000-3",
    ]
    assert [event["event"] for event in events] == ["step_done", "result", "done"]
    assert events[0]["data"]["step"] == "evidence_validation"
    identities = {
        (event["data"]["sessionId"], event["data"]["taskId"], event["data"]["turnId"])
        for event in events
    }
    assert identities == {("session-authority-1", "task-authority-1", 2)}
    assert events[-1]["data"]["message"] == "搜索完成"
    assert "error" not in events[-1]["data"]


def test_expired_window_wire_forces_snapshot_resync_without_fabricated_cursor() -> None:
    contract = _json("sse_v1_contract.json")
    replay = contract["replay"]
    events = _parse_sse(contract["wireFixtures"]["expiredWindow"])

    assert replay["expiredEvent"] == "replay_expired"
    assert replay["expiredEventHasId"] is False
    assert replay["connectionAfterExpiredEvent"] == "close"
    assert replay["createsNewTask"] is False
    assert len(events) == 1
    event = events[0]
    assert set(event) == {"event", "data"}
    assert event["event"] == "replay_expired"
    assert event["data"]["reason"] == "cursor_not_retained"
    assert event["data"]["action"] == "resync"
    assert event["data"]["snapshot"] == {
        "snapshotVersion": 7,
        "status": "completed",
        "terminal": {"event": "done", "message": "搜索完成"},
    }
    assert (event["data"]["taskId"], event["data"]["turnId"]) == (
        "task-authority-1",
        2,
    )
