# Project Index

## What This Project Is

XHS Food Agent is a Python/FastAPI backend plus React/Vite frontend for local-food recommendations. It searches Xiaohongshu notes, analyzes comments with an OpenAI-compatible LLM, filters suspected influencer shops, enriches POIs through Amap, and streams progress through SSE.

## Project Type

- Type: full-stack AI application.
- Confidence: high. Evidence: `src/api/main.py`, `src/xhs_food/orchestrator/`, `frontend/`, `pyproject.toml`, and `frontend/package.json`.

## Important Files

| Path | Purpose |
|---|---|
| `src/api/main.py` | FastAPI app, lifespan, middleware, routes |
| `src/api/search/routes.py` | Unified search, SSE, status, results |
| `src/api/search/tasks.py` | Background search and persistence |
| `src/xhs_food/orchestrator/core.py` | Search orchestration and streaming |
| `src/xhs_food/orchestrator/search_executor.py` | Four-stage search and merge/filter |
| `src/xhs_food/agents/intent_parser.py` | LLM intent parsing |
| `src/xhs_food/agents/analyzer.py` | Comment analysis and recommendation conversion |
| `src/xhs_food/spider/services/xhs_service.py` | Xiaohongshu API facade |
| `src/xhs_food/agents/poi_enricher.py` | Amap POI enrichment |
| `src/xhs_food/events/` | SSE event bus and emitter |
| `src/xhs_food/services/user_storage/` | PostgreSQL users/history/favorites/results |
| `frontend/src/stores/searchStore.ts` | Frontend search/SSE state |

## Confirmed Current Risks

- Backend tests pass, but frontend build fails because `frontend/tsconfig.json` is absent.
- Backend persistence expects migrated `search_results` columns (`turn_id`, `query`) that the default schema does not create.
- Search route calls nonexistent `create_search_history`, so automatic search history creation is skipped.
- Frontend and backend response/event field names are inconsistent.
- Ruff and Pyright are currently non-clean; CI gates Ruff and frontend lint/build.

## Best Next Step

Align the API contract and database migration first, then add one real end-to-end test from POST search through SSE, persistence, and frontend DTO mapping.
