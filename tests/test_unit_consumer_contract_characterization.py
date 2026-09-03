"""Server and browser contracts after the comment-first cutover."""

from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent


def _source(relative_path: str) -> str:
    return (_ROOT / relative_path).read_text(encoding="utf-8")


def test_server_search_route_is_the_single_entry_point() -> None:
    from api.main import app

    paths = app.openapi()["paths"]
    assert "post" in paths["/v1/search/"]
    assert "/v1/search/start" not in paths
    assert "/v1/search/refine" not in paths
    assert "/v1/search/recover/{sessionId}" not in paths


def test_frontend_uses_unified_turns_and_current_pipeline_ids() -> None:
    search_api = _source("frontend/src/api/searchApi.ts")
    search_store = _source("frontend/src/stores/searchStore.ts")

    assert "apiPost('/v1/search/'" in search_api
    assert "const sid = res.sessionId" in search_store
    assert "shop_profile_enrichment" in search_store
    assert "poi_enrichment" not in search_store
    assert "apiPost('/v1/search/refine'" not in search_api
    assert "apiGet(`/v1/search/recover/${sessionId}`)" not in search_api


def test_frontend_auxiliary_envelopes_and_default_dev_origin_are_current() -> None:
    history_api = _source("frontend/src/api/historyApi.ts")
    favorites_api = _source("frontend/src/api/favoritesApi.ts")
    user_api = _source("frontend/src/api/userApi.ts")
    vite_config = _source("frontend/vite.config.ts")

    assert "page=${page}&pageSize=${pageSize}" in history_api
    assert "data: { history: unknown[]; total: number }" in history_api
    assert "data: { favorites: unknown[] }" in favorites_api
    assert "data: { faqs: unknown[] }" in user_api
    assert "port: 3000" not in vite_config


def test_readme_documents_the_unified_search_endpoint_and_new_agent_flow() -> None:
    readme = _source("README.md")
    assert "/v1/search/" in readme
    assert "小红书评论证据" in readme
    assert "大众点评店铺档案" in readme
    assert "/v1/search/start" not in readme
    assert "四阶段" not in readme
