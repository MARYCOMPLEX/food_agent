# Legacy Compatibility Ledger

Status: inventory-only; no legacy path or field is removed by this record.

Inventory commit: `60b2194` (`codex/define-modular-architecture-s0`)
Inventory date: `2026-08-25`

This ledger is the review input for `legacy-contraction`. It records the
compatibility surface that still has supported or unknown consumers. A row may
move to removal only after all three gates are attached to that row:

1. `RELEASE_CYCLE_PROVEN`: one complete release cycle with no supported caller.
2. `CONSUMER_APPROVED`: an owner, evidence link, and rollback command are
   recorded.
3. `RESTORE_PROVEN`: clean/N-1 database restore and retained Temporal/history
   replay pass.

Until then every row remains available. `PENDING_*` is an explicit state, not
an inference that a consumer is absent.

## Removal Gate And Rollback Rules

| Rule | Meaning |
|---|---|
| `NO_REMOVAL_IN_INITIAL_PHASE` | This inventory commit changes no runtime behavior and deletes no data. |
| `PENDING_RELEASE_CYCLE` | No complete production release-cycle observation is attached. |
| `PENDING_CONSUMER_APPROVAL` | A supported-consumer inventory, owner, or exact rollback command is missing. |
| `PENDING_RESTORE` | The clean/N-1 Alembic and retained Temporal/Evidence restore evidence is missing from this change. |
| `ROLLBACK_BINDING` | Disable the target binding and restart the owning process; preserve PostgreSQL facts, Temporal history, immutable Evidence/Bundle versions, and rebuildable Redis state. |

## HTTP Routes And Wire Contracts

| ID | Legacy surface and source | Replacement/owner | Known consumer evidence | Removal state | Rollback binding |
|---|---|---|---|---|---|
| `route.search.unified` | `POST /v1/search/` in `src/api/search/routes.py`; legacy task facade is selected when reliable lifecycle is off | `ResearchTaskPort` and `ResearchCoordinator` | `tests/test_integration_search_http_characterization.py`, `tests/test_unit_legacy_research_task_facade.py` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` | `MODULAR_RESEARCH_CORE_VERSION=legacy/v1` |
| `route.search.sse` | `GET /v1/search/stream/{sessionId}` without `sseVersion=v1` | Stable v1 Event Mapper plus legacy EventBus adapter | `tests/test_integration_sse_characterization.py`, `tests/test_unit_stable_event_mapper.py` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` | `MODULAR_RELIABLE_TASK_LIFECYCLE=false` and `EVENT_BUS_BACKEND=memory` |
| `route.search.sse-v1` | `GET /v1/search/stream/{sessionId}?sseVersion=v1` | Reliable task projection/event ports | `tests/test_integration_reliable_search_http.py` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` | `MODULAR_RELIABLE_TASK_LIFECYCLE=false` |
| `route.search.status-results` | `GET /v1/search/status/{sessionId}` and `GET /v1/search/results/{sessionId}` | `ResearchTaskPort.status/results` | `tests/test_integration_search_http_characterization.py` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` | `MODULAR_RESEARCH_CORE_VERSION=legacy/v1` |
| `route.search.documented-old` | README-only `/v1/search/start`, `/v1/search/refine`, `/v1/search/recover` references in `src/api/README.md`; no independent router is currently registered | Unified `POST /v1/search/` request envelope | `tests/test_unit_consumer_contract_characterization.py`; README is a documented consumer, not runtime proof | `PENDING_CONSUMER_APPROVAL`; `NO_REMOVAL_IN_INITIAL_PHASE` | Keep README and unified route unchanged until a documentation change approves replacement |
| `route.auxiliary` | `/v1/favorites`, `/v1/history`, `/v1/user`, `/v1/help`, `/health`, `/metrics` in `src/api/*.py` and `src/api/main.py` | Dedicated repository and observability ports | `tests/test_integration_auxiliary_api_characterization.py` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` | `MODULAR_TARGET_ADAPTERS_ENABLED=false` |

## DTOs, Schemas, And Public Python Exports

| ID | Legacy surface and source | Replacement/owner | Evidence | Removal state |
|---|---|---|---|---|
| `dto.food.public` | `FoodSearchIntent`, `RestaurantRecommendation`, `XHSFoodResponse`, `ConversationContext` and related enums in `src/xhs_food/schemas/__init__.py` and lazy exports in `src/xhs_food/__init__.py` | Food Pack contracts and `LegacyFoodOutputAdapter` | `tests/test_unit_s4_food_pack_compatibility.py`, `tests/test_unit_search_results_schema_characterization.py` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `dto.food.enriched` | `EnrichedRestaurant`, `RestaurantInfo`, `WanghongAnalysis`, `MustTryItem`, `BlackListItem`, `ShopStats` in `src/xhs_food/schemas/restaurant.py` | Food Pack final output schema | `tests/test_unit_s4_food_pack_compatibility.py` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `export.xhs_food` | Top-level lazy exports in `src/xhs_food/__init__.py`: `XHSFoodOrchestrator`, `XHSFoodState`, `FoodSearchIntent`, `XHSFoodResponse`, `RestaurantRecommendation`, `SearchPhase`, `CommentWeight`, `CrossValidationResult`, `RecommendationLevel`, `WanghongScore`, `FollowUpType`, `ConversationContext` | Domain-neutral contracts and Food Pack adapters | `tests/test_unit_contract_sdk.py`, `tests/test_unit_s4_food_pack_compatibility.py` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `export.services` | `LLMService`, `RedisMemory`, `PostgresStorage`, `SessionManager`, `UserStorageService`, preprocessing and scoring exports in `src/xhs_food/services/__init__.py` | Provider, repository, StateStore, and Domain ports | `tests/test_unit_s3_composition_adapters.py`, `tests/test_unit_contract_sdk.py` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `export.agents` | `IntentParserAgent`, `AnalyzerAgent`, `POIEnricherAgent`, `EnrichedRestaurant` and `get_poi_enricher` in `src/xhs_food/agents/__init__.py` | Pydantic AI V2 Agent runtime and Tool Gateway | `tests/test_unit_s5_research_skeleton.py`, `tests/test_unit_s3_gateway_adapters.py` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `export.composition` | `build_legacy_composition_root` in `src/xhs_food/composition/__init__.py` | Composition Root target bindings | `tests/test_unit_composition_root.py`, `tests/test_unit_b0_rollback.py` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `export.adapters` | `Legacy*` adapter names exported from `src/xhs_food/composition/adapters/__init__.py` | Owner ports and target adapters | `tests/test_unit_s3_composition_adapters.py`, `tests/test_unit_architecture_boundaries.py` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |

## Legacy Adapters And Fallback Bindings

| ID | Source symbols | Replacement/owner | Rollback binding | Removal state |
|---|---|---|---|---|
| `adapter.research` | `LegacyResearchTaskFacade` in `src/xhs_food/composition/legacy_research_task.py` | `ResearchCoordinator` / `ResearchTaskPort` | `MODULAR_RESEARCH_CORE_VERSION=legacy/v1` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `adapter.food` | `LegacyFoodPackAdapter`, `LegacyFoodOutputAdapter` | Installed Food Pack registry | `MODULAR_FOOD_PACK_VERSION=legacy/v1` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `adapter.repositories` | `LegacySessionRepositoryAdapter`, `LegacyUserRepositoryAdapter`, `LegacyHistoryRepositoryAdapter`, `LegacyFavoritesRepositoryAdapter`, `LegacySearchResultRepositoryAdapter`, `LegacyPlaceCacheRepositoryAdapter` in `src/xhs_food/composition/adapters/repositories.py` | SQLAlchemy 2 Async repository ports | `MODULAR_TARGET_ADAPTERS_ENABLED=false` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `adapter.state` | `LegacyStateStoreAdapter`, `LegacyEventBusAdapter`, `LegacySessionWindowAdapter` in `src/xhs_food/composition/adapters/state.py` | Redis target StateStore/EventBus/session projection | `EVENT_BUS_BACKEND=memory`; `MODULAR_TARGET_ADAPTERS_ENABLED=false` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `adapter.llm` | `LegacyLLMProviderAdapter` in `src/xhs_food/composition/adapters/llm.py` and `LLMService` in `src/xhs_food/services/llm_service.py` | Pydantic AI V2 provider port | `MODULAR_TARGET_ADAPTERS_ENABLED=false` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `adapter.poi` | `build_legacy_poi_ports`, `LegacyPlaceCacheRepositoryAdapter`, and `_LegacyAmapInjectionAdapter` | `PlaceLookupPort` and Source/Tool Gateway | `MODULAR_TARGET_ADAPTERS_ENABLED=false` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `adapter.spider` | `XHS_Apis`, `XHS_ApisBase`, `AmapAPI`, and `XHSService` under `src/xhs_food/spider/` | SourceConnector adapters | `MODULAR_TARGET_ADAPTERS_ENABLED=false` | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `fallback.memory` | `RedisMemory`, in-process EventBus/state, and `get_event_bus()` legacy fallback | Redis rebuildable hot-state contracts | `EVENT_BUS_BACKEND=memory` only for legacy/dev characterization; never a target production binding | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |

## Configuration And Environment Bindings

| ID | Legacy names/source | Replacement/owner | Removal state |
|---|---|---|---|
| `config.legacy.settings` | `OPENAI_API_KEY`, `OPENAI_API_BASE`, `DEFAULT_LLM_MODEL`, `SEARCH_DEEP_MODE`, `SEARCH_NOTE_LIMIT`, `SEARCH_NOTES_PER_KEYWORD`, `SEARCH_MAX_RESTAURANTS`, `SSE_TIMEOUT`, `SSE_TIMEOUT_SECONDS`, `CORS_ORIGINS`, `REDIS_*`, `DATABASE_URL`/`POSTGRES_*`, `XHS_*`, `LOG_LEVEL`, `API_HOST`, `API_PORT` in `src/xhs_food/config.py`, `src/api`, `.env.example` | `OwnerConfigFacade` and target `MODULAR_*` settings; aliases are retained until a separate config change | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `config.modular.bindings` | `MODULAR_TARGET_ADAPTERS_ENABLED`, `MODULAR_RELIABLE_TASK_LIFECYCLE`, `MODULAR_EVIDENCE_SHADOW_*`, `MODULAR_PERSONALIZATION_CANARY_*`, `MODULAR_FOOD_PACK_VERSION`, `MODULAR_RESEARCH_CORE_VERSION`, `MODULAR_*_DATABASE_URL`, `MODULAR_TEMPORAL_*`, `MODULAR_REFRESH_ENABLED`, `MODULAR_MEDIA_ENABLED`, `MODULAR_OBJECT_STORE_*`, `MODULAR_OTEL_*` in `src/xhs_food/foundation/config.py` | Target Composition Root feature bindings | Keep as explicit rollback controls; no removal before a replacement release contract | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `config.auth.compat` | `XHS_COOKIES`, `XHS_PROFILE`, `XHS_PROFILE_DIR`, Node signer/profile paths in `src/xhs_food/auth/` and `src/xhs_food/spider/xhs_utils/` | Auth/Profile and signer ports | `XHS_COOKIES` remains available as a legacy fallback | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |

## Runtime DDL And Migration Bypass Paths

These paths are explicitly inventoried as legacy. They are not removed in the
initial phase because existing deployments and unknown consumers must be
discovered first. Alembic remains the only target schema authority.

| ID | Runtime DDL path | Affected authority | Replacement/owner | Removal state |
|---|---|---|---|---|
| `ddl.chat-history` | `src/xhs_food/services/postgres_storage.py` (`chat_history`, indexes) | PostgreSQL business facts | Alembic chat/history revisions | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `ddl.chat-vector` | `src/xhs_food/services/postgres_vector.py` (`ALTER TABLE`, extension) | PostgreSQL embedding facts | Alembic profile/embedding revisions | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `ddl.user-storage` | `src/xhs_food/services/user_storage/schema.py` and `service.py` (`users`, `favorites`, `search_history`, `search_results`, `restaurants`) | PostgreSQL user/history facts | Alembic legacy baseline plus additive revisions | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `ddl.favorites-script` | `src/scripts/migrate_favorites.py` | PostgreSQL user/favorite facts | Alembic user/favorite revisions | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `ddl.sse-recovery-script` | `scripts/migrate_sse_recovery.py` | PostgreSQL history/result facts | Alembic history/result revisions | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `ddl.turn-id-script` | `scripts/migrate_turn_id.py` | `search_results.turn_id` and index | Alembic expand/baseline migration | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |
| `ddl.request-log` | `src/xhs_food/spider/core/logger.py` (`request_logs`) | Operational logging | Observability exporter/storage contract | `PENDING_RELEASE_CYCLE`; `PENDING_CONSUMER_APPROVAL`; `PENDING_RESTORE` |

## Evidence And Approval Record

Current evidence is repository-local characterization and target-stack
rehearsal only. It does not prove the absence of external consumers or a
complete production release cycle.

| Required artifact | Current state | Authoritative reference |
|---|---|---|
| Consumer inventory | Repository callers and public exports listed above; external fleet callers unknown | `ADR-0009-legacy-gap-disposition.md`, this ledger |
| Release-cycle evidence | Missing; no owner approval attached | `legacy-contraction/tasks.md` task 1.2 remains open |
| Clean/N-1 Alembic restore | Local rehearsal recorded; source runtime DDL still present | `define-modular-architecture/verification/release-gates.md` task 14.7 |
| Temporal history replay | Local SDK/target-stack qualification recorded | `define-modular-architecture/verification/b0-temporal-qualification.md` and `release-gates.md` |
| Rollback | Existing S2-S5/B0-B4 runbooks and explicit `MODULAR_*` bindings | `define-modular-architecture/runbooks/` |

No row is eligible for removal until the missing evidence is attached to that
row and approved by the owning release/data/platform owners.
