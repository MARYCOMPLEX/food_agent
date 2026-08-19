"""Freeze server, browser consumer, and README claims as distinct contracts."""

from __future__ import annotations

import json
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE = json.loads(
    (_ROOT / "tests/fixtures/characterization/consumer_contracts.json").read_text(
        encoding="utf-8"
    )
)


def _source(relative_path: str) -> str:
    return (_ROOT / relative_path).read_text(encoding="utf-8")


def test_server_search_routes_and_cors_match_current_contract() -> None:
    from api.main import app
    from starlette.middleware.cors import CORSMiddleware

    paths = app.openapi()["paths"]
    assert "post" in paths["/v1/search/"]
    assert "/v1/search/refine" not in paths
    assert "/v1/search/recover/{sessionId}" not in paths

    cors = next(item for item in app.user_middleware if item.cls is CORSMiddleware)
    assert cors.kwargs["allow_origins"] == [_FIXTURE["server_current"]["cors_origin"]]
    assert cors.kwargs["allow_methods"] == _FIXTURE["server_current"]["cors_methods"]


def test_frontend_search_and_sse_assumptions_match_current_source() -> None:
    search_api = _source("frontend/src/api/searchApi.ts")
    search_store = _source("frontend/src/stores/searchStore.ts")

    assert "sessionId: string" in search_api
    assert "const sid = res.sessionId" in search_store
    assert "apiPost('/v1/search/refine'" in search_api
    assert "apiGet(`/v1/search/recover/${sessionId}`)" in search_api
    assert "?lastEventIndex=${lastEventIndex}" in search_api
    assert "detail: data.detail" in search_store
    for step in _FIXTURE["frontend_assumed"]["sse_steps"]:
        assert f"id: '{step}'" in search_store


def test_frontend_collection_envelopes_and_dev_origin_match_current_source() -> None:
    history_api = _source("frontend/src/api/historyApi.ts")
    favorites_api = _source("frontend/src/api/favoritesApi.ts")
    user_api = _source("frontend/src/api/userApi.ts")
    vite_config = _source("frontend/vite.config.ts")

    assert "page=${page}&pageSize=${pageSize}" in history_api
    assert "data: { history: unknown[]; total: number }" in history_api
    assert "data: { favorites: unknown[] }" in favorites_api
    assert "data: { faqs: unknown[] }" in user_api
    assert "port: 3000" in vite_config


def test_readme_legacy_route_claims_match_current_documentation() -> None:
    readme = _source("README.md")
    assert "/v1/search/start" in readme
    assert "/v1/search/refine" in readme
    assert "/v1/search/recover/{id}" in readme


def test_fixture_keeps_known_contract_conflicts_explicit() -> None:
    server = _FIXTURE["server_current"]
    frontend = _FIXTURE["frontend_assumed"]
    docs = _FIXTURE["docs_declared"]

    assert server["search_response_session"] != frontend["search_response_session"]
    assert server["refine_and_recover"] != frontend["refine"]
    assert frontend["refine"] == docs["refine"]
    assert server["refine_and_recover"] != frontend["recover"]
    assert server["history_query"] != frontend["history_query"]
    assert server["history_items"] != frontend["history_items"]
    assert server["favorites_items"] != frontend["favorites_items"]
    assert server["faqs_items"] != frontend["faqs_items"]
    assert server["sse_replay"] != frontend["sse_replay"]
    assert server["sse_steps"] != frontend["sse_steps"]
    assert server["cors_origin"] != frontend["dev_origin"]
