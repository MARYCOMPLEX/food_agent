"""Contract checks for the generated and human-readable backend API docs."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from api.main import app

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "backend-api.md"
DOCUMENTS_WITH_LOCAL_LINKS = (
    ROOT / "README.md",
    GUIDE,
    ROOT / "docs" / "account-services.md",
    ROOT / "src" / "api" / "README.md",
    ROOT / "src" / "food_agent" / "services" / "README.md",
)
HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch"})
INVENTORY_ROW = re.compile(r"^\| `([A-Z]+)` \| `([^`]+)` \|", re.MULTILINE)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _render_artifacts() -> dict[Path, str]:
    schema = app.openapi()
    return {
        ROOT / "contracts" / "openapi.yaml": yaml.safe_dump(
            schema, sort_keys=False, allow_unicode=True
        ),
        ROOT / "tests" / "fixtures" / "http" / "openapi.json": json.dumps(
            schema, ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n",
    }


def _runtime_operations() -> set[tuple[str, str]]:
    schema = app.openapi()
    return {
        (method.upper(), path)
        for path, path_item in schema["paths"].items()
        for method in path_item
        if method in HTTP_METHODS
    }


def test_checked_in_openapi_artifacts_equal_runtime_schema() -> None:
    expected = app.openapi()
    yaml_schema = yaml.safe_load(
        (ROOT / "contracts" / "openapi.yaml").read_text(encoding="utf-8")
    )
    json_schema = json.loads(
        (ROOT / "tests" / "fixtures" / "http" / "openapi.json").read_text(
            encoding="utf-8"
        )
    )

    assert yaml_schema == expected
    assert json_schema == expected


def test_checked_in_openapi_artifacts_are_deterministically_rendered() -> None:
    for path, expected in _render_artifacts().items():
        assert path.read_text(encoding="utf-8") == expected, (
            f"{path.relative_to(ROOT)} is stale; run "
            "`uv run python scripts/export_openapi.py`"
        )


def test_backend_guide_inventory_matches_every_runtime_operation() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    inventory = text.split("<!-- BEGIN API ENDPOINT INVENTORY -->", 1)[1].split(
        "<!-- END API ENDPOINT INVENTORY -->", 1
    )[0]
    documented = set(INVENTORY_ROW.findall(inventory))

    assert documented == _runtime_operations()
    assert len(documented) == 38


def test_backend_guide_states_current_protocol_boundaries() -> None:
    text = GUIDE.read_text(encoding="utf-8")

    assert "不存在 `lastEventIndex` 查询参数" in text
    assert "身份解析，不是认证" in text
    assert "值转换**并不相同**" in text
    assert "`sessionId` 没有 ownership 校验" in text
    assert "`ResearchEvent v1` | **否**" in text
    assert "`UserResearchProjection v1` | **否**" in text
    assert "当前路由实际映射的事件只有" in text
    assert "`SSE_TIMEOUT_SECONDS`" in text
    assert "`SSE_TIMEOUT` 实际不生效" not in text  # avoid claiming a runtime alias
    assert "/v1/search/start" not in text
    assert "/v1/search/refine" not in text
    assert "/v1/search/recover" not in text


def test_backend_documentation_local_markdown_links_exist() -> None:
    missing: list[str] = []
    for document in DOCUMENTS_WITH_LOCAL_LINKS:
        text = document.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            if not target.endswith(".md"):
                continue
            resolved = (document.parent / target).resolve()
            if not resolved.exists():
                missing.append(
                    f"{document.relative_to(ROOT)} -> {raw_target}"
                )

    assert missing == []


def test_sse_openapi_declares_stream_content_and_versions() -> None:
    operation = app.openapi()["paths"]["/v1/search/stream/{sessionId}"]["get"]
    response = operation["responses"]["200"]

    assert "text/event-stream" in response["content"]
    parameters = {item["name"]: item for item in operation["parameters"]}
    assert parameters["sseVersion"]["in"] == "query"
    assert parameters["Last-Event-ID"]["in"] == "header"
    examples = response["content"]["text/event-stream"]["examples"]
    assert set(examples) == {"legacy", "reliableV1"}


def test_metrics_openapi_declares_prometheus_text() -> None:
    response = app.openapi()["paths"]["/metrics"]["get"]["responses"]["200"]

    assert "application/json" not in response["content"]
    assert any(content_type.startswith("text/plain") for content_type in response["content"])


def test_search_openapi_exposes_consumed_identity_headers() -> None:
    operation = app.openapi()["paths"]["/v1/search/"]["post"]
    parameters = {(item["name"], item["in"]) for item in operation["parameters"]}

    assert ("X-User-Id", "header") in parameters
    assert ("X-Device-Id", "header") in parameters
