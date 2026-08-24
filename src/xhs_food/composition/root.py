"""Central lifecycle for contract-to-adapter bindings.

S1 creates the root without routing production callers through it. The explicit
legacy builder is the only place in this package that imports concrete adapters.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, cast

AdapterFactory = Callable[[], object | Awaitable[object]]


class RegistryState(StrEnum):
    CONFIGURING = "configuring"
    ACTIVE = "active"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class AdapterBinding:
    """A versioned factory selected only by the Composition Root."""

    name: str
    contract_version: str
    factory: AdapterFactory
    legacy: bool
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.name or not self.contract_version:
            raise ValueError("binding name and contract_version must be non-empty")


@dataclass(frozen=True, slots=True)
class LogicalBinding:
    """A stable capability name resolved to one concrete registry binding."""

    name: str
    registry_name: str
    binding_name: str

    def __post_init__(self) -> None:
        if not self.name or not self.registry_name or not self.binding_name:
            raise ValueError("logical binding names must be non-empty")


class BindingRegistry:
    """Configure once, activate atomically, and close owned instances."""

    def __init__(self, name: str) -> None:
        if not name:
            raise ValueError("registry name must be non-empty")
        self.name = name
        self._state = RegistryState.CONFIGURING
        self._bindings: dict[str, AdapterBinding] = {}
        self._instances: dict[str, object] = {}
        self._creation_order: list[str] = []
        self._lifecycle_lock = asyncio.Lock()

    @property
    def state(self) -> RegistryState:
        return self._state

    @property
    def bindings(self) -> Mapping[str, AdapterBinding]:
        return MappingProxyType(self._bindings)

    def register(self, binding: AdapterBinding) -> None:
        if self._state is not RegistryState.CONFIGURING:
            raise RuntimeError(f"registry {self.name!r} is not configurable")
        if binding.name in self._bindings:
            raise ValueError(f"duplicate binding: {self.name}.{binding.name}")
        self._bindings[binding.name] = binding

    def activate(self) -> None:
        if self._state is not RegistryState.CONFIGURING:
            raise RuntimeError(f"registry {self.name!r} cannot be activated from {self._state}")
        self._state = RegistryState.ACTIVE

    async def resolve(self, name: str) -> object:
        async with self._lifecycle_lock:
            if self._state is not RegistryState.ACTIVE:
                raise RuntimeError(f"registry {self.name!r} is not active")
            if name in self._instances:
                return self._instances[name]
            try:
                binding = self._bindings[name]
            except KeyError as exc:
                raise KeyError(f"unknown binding: {self.name}.{name}") from exc
            if not binding.enabled:
                raise DisabledBindingError(self.name, name)

            instance = binding.factory()
            if inspect.isawaitable(instance):
                instance = await instance
            self._instances[name] = instance
            self._creation_order.append(name)
            return instance

    async def close(self) -> None:
        async with self._lifecycle_lock:
            if self._state is RegistryState.CLOSED and not self._instances:
                return
            self._state = RegistryState.CLOSED
            errors: list[Exception] = []
            failed_names: list[str] = []
            for name in reversed(tuple(self._creation_order)):
                instance = self._instances[name]
                close = getattr(instance, "aclose", None) or getattr(instance, "close", None)
                try:
                    if close is not None:
                        result = close()
                        if inspect.isawaitable(result):
                            await result
                except Exception as exc:
                    errors.append(exc)
                    failed_names.append(name)
                    continue
                self._instances.pop(name, None)
                self._creation_order.remove(name)

            if errors:
                failed = ", ".join(f"{self.name}.{name}" for name in failed_names)
                raise ExceptionGroup(f"failed to close registry bindings: {failed}", errors)


class CompositionRoot:
    """Own all registries without owning domain behavior."""

    def __init__(self) -> None:
        self._state = RegistryState.CONFIGURING
        self._registries: dict[str, BindingRegistry] = {}
        self._logical_bindings: dict[str, LogicalBinding] = {}
        self._lifecycle_lock = asyncio.Lock()
        self._close_complete = False

    @property
    def state(self) -> RegistryState:
        return self._state

    @property
    def registries(self) -> Mapping[str, BindingRegistry]:
        return MappingProxyType(self._registries)

    @property
    def logical_bindings(self) -> Mapping[str, LogicalBinding]:
        return MappingProxyType(self._logical_bindings)

    def registry(self, name: str) -> BindingRegistry:
        if self._state is not RegistryState.CONFIGURING:
            raise RuntimeError("composition root is no longer configurable")
        registry = self._registries.get(name)
        if registry is None:
            registry = BindingRegistry(name)
            self._registries[name] = registry
        return registry

    def bind_logical(self, name: str, *, registry_name: str, binding_name: str) -> None:
        if self._state is not RegistryState.CONFIGURING:
            raise RuntimeError("composition root is no longer configurable")
        if name in self._logical_bindings:
            raise ValueError(f"duplicate logical binding: {name}")
        try:
            registry = self._registries[registry_name]
        except KeyError as exc:
            raise KeyError(f"unknown registry: {registry_name}") from exc
        if binding_name not in registry.bindings:
            raise KeyError(f"unknown binding: {registry_name}.{binding_name}")
        self._logical_bindings[name] = LogicalBinding(
            name=name,
            registry_name=registry_name,
            binding_name=binding_name,
        )

    def activate(self) -> None:
        if self._state is not RegistryState.CONFIGURING:
            raise RuntimeError(f"composition root cannot activate from {self._state}")
        for registry in self._registries.values():
            registry.activate()
        self._state = RegistryState.ACTIVE

    async def resolve(self, registry_name: str, binding_name: str) -> object:
        if self._state is not RegistryState.ACTIVE:
            raise RuntimeError("composition root is not active")
        try:
            registry = self._registries[registry_name]
        except KeyError as exc:
            raise KeyError(f"unknown registry: {registry_name}") from exc
        return await registry.resolve(binding_name)

    async def resolve_logical(self, name: str) -> object:
        if self._state is not RegistryState.ACTIVE:
            raise RuntimeError("composition root is not active")
        try:
            binding = self._logical_bindings[name]
        except KeyError as exc:
            raise KeyError(f"unknown logical binding: {name}") from exc
        return await self.resolve(binding.registry_name, binding.binding_name)

    def assert_legacy_only(self, allowed_non_legacy: frozenset[str] = frozenset()) -> None:
        non_legacy = [
            f"{registry.name}.{binding.name}"
            for registry in self._registries.values()
            for binding in registry.bindings.values()
            if binding.enabled
            and not binding.legacy
            and f"{registry.name}.{binding.name}" not in allowed_non_legacy
        ]
        if non_legacy:
            raise RuntimeError(f"enabled non-legacy bindings are forbidden in S3: {non_legacy}")

    async def close(self) -> None:
        async with self._lifecycle_lock:
            if self._close_complete:
                return
            self._state = RegistryState.CLOSED
            errors: list[Exception] = []
            failed_names: list[str] = []
            for registry in reversed(tuple(self._registries.values())):
                try:
                    await registry.close()
                except Exception as exc:
                    errors.append(exc)
                    failed_names.append(registry.name)

            self._close_complete = not errors
            if errors:
                failed = ", ".join(failed_names)
                raise ExceptionGroup(f"failed to close composition registries: {failed}", errors)


class DisabledBindingError(RuntimeError):
    def __init__(self, registry_name: str, binding_name: str) -> None:
        super().__init__(f"binding {registry_name}.{binding_name} is disabled")
        self.registry_name = registry_name
        self.binding_name = binding_name


@dataclass(slots=True)
class ReliableRuntimeBindings:
    """Explicit production resources shared by the API and reliable policy.

    The API process owns these connections for its lifetime.  Temporal worker
    processes create their own Activity-side bindings, while PostgreSQL and
    Redis remain shared service dependencies rather than process-local state.
    """

    database: Any
    workflow: Any
    task_store: Any
    projection_store: Any
    event_bus: Any
    policy: Any
    redis_client: Any

    async def aclose(self) -> None:
        errors: list[BaseException] = []
        for resource in (self.workflow, self.redis_client, self.database):
            close = getattr(resource, "aclose", None) or getattr(resource, "close", None)
            if not callable(close):
                continue
            try:
                result = close()
                if inspect.isawaitable(result):
                    await result
            except BaseException as exc:  # pragma: no cover - exercised by lifecycle failure tests
                errors.append(exc)
        if errors:
            raise ExceptionGroup("failed to close reliable runtime bindings", errors)


async def build_reliable_runtime_bindings(
    *,
    target_settings: Any | None = None,
    legacy_settings: Any | None = None,
    database_factory: Callable[..., Any] | None = None,
    redis_factory: Callable[..., Any] | None = None,
    temporal_connect: Callable[..., Awaitable[Any]] | None = None,
) -> ReliableRuntimeBindings:
    """Create the explicit PG/Redis/Temporal bindings for API lifespan use.

    This helper is intentionally opt-in and injectable for contract tests. It
    never creates an in-memory execution store or EventBus when a target
    binding is requested; missing service configuration is a startup error.
    """

    from xhs_food.composition.adapters import (
        PostgresReliableTaskStore,
        PostgresTaskProgressProjectionStore,
    )
    from xhs_food.config import get_settings
    from xhs_food.foundation import (
        RedisEventBusAdapter,
        RedisHotStateContract,
        SQLAlchemyDatabase,
        TargetSettings,
        TemporalTaskQueues,
        TemporalWorkflowAdapter,
        create_redis_client,
    )
    from xhs_food.orchestrator import TemporalReliableResearchPolicy

    target = target_settings if target_settings is not None else TargetSettings()
    if not bool(getattr(target, "reliable_task_lifecycle", False)):
        raise RuntimeError("reliable_task_lifecycle must be enabled for target bindings")
    if not bool(getattr(target, "target_adapters_enabled", False)):
        raise RuntimeError("target_adapters_enabled must be enabled for reliable bindings")

    legacy = legacy_settings if legacy_settings is not None else get_settings()
    database_url = getattr(target, "database_url", None)
    if not isinstance(database_url, str) or not database_url:
        raise RuntimeError("reliable_task_lifecycle requires MODULAR_DATABASE_URL")
    redis_url = legacy.resolved_redis_url()
    if not isinstance(redis_url, str) or not redis_url:
        raise RuntimeError("reliable runtime requires REDIS_URL or REDIS_HOST")

    database_builder = database_factory or SQLAlchemyDatabase
    database = database_builder(database_url, enabled=True)
    database.start()
    redis_builder = redis_factory or create_redis_client
    redis_client = redis_builder(redis_url, decode_responses=True)
    workflow: Any | None = None
    try:
        await redis_client.ping()
        queues = TemporalTaskQueues(
            research=target.temporal_research_queue,
            refresh=target.temporal_refresh_queue,
            media=target.temporal_media_queue,
        )
        connect = temporal_connect or TemporalWorkflowAdapter.connect
        workflow = await connect(
            address=target.temporal_address,
            namespace=target.temporal_namespace,
            task_queues=queues,
            enabled=True,
        )
        contract = RedisHotStateContract(
            event_stream_ttl_seconds=legacy.event_stream_ttl_seconds,
            event_stream_maxlen=legacy.event_stream_maxlen,
        )
        event_bus = RedisEventBusAdapter(redis_client, contract)
        task_store = PostgresReliableTaskStore(database.unit_of_work)
        projection_store = PostgresTaskProgressProjectionStore(database.unit_of_work)
        policy = TemporalReliableResearchPolicy(workflow)
        return ReliableRuntimeBindings(
            database=database,
            workflow=workflow,
            task_store=task_store,
            projection_store=projection_store,
            event_bus=event_bus,
            policy=policy,
            redis_client=redis_client,
        )
    except BaseException:
        if workflow is not None:
            close = getattr(workflow, "aclose", None) or getattr(workflow, "close", None)
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result
        close_redis = getattr(redis_client, "aclose", None) or getattr(redis_client, "close", None)
        if callable(close_redis):
            result = close_redis()
            if inspect.isawaitable(result):
                await result
        await database.aclose()
        raise


def build_reliable_research_worker(
    client: object,
    activities: object,
    *,
    config: object | None = None,
    task_queues: object | None = None,
    workflows: Sequence[type[object]] | None = None,
    plugins: Sequence[object] = (),
) -> object:
    """Build the opt-in Research worker at the Composition Root boundary."""

    from xhs_food.foundation import TemporalTaskQueues, build_temporal_worker
    from xhs_food.orchestrator import (
        ReliableTaskConfig,
        TemporalResearchWorkflow,
        pydantic_ai_worker_plugin,
    )

    reliable_config = config if isinstance(config, ReliableTaskConfig) else ReliableTaskConfig()
    queues = task_queues if isinstance(task_queues, TemporalTaskQueues) else TemporalTaskQueues(
        research=reliable_config.task_queue,
        refresh="refresh",
        media="media",
    )
    if queues.research != reliable_config.task_queue:
        raise ValueError("Research worker queue must match ReliableTaskConfig.task_queue")
    activity_list = getattr(activities, "activities", None)
    if not callable(activity_list):
        raise TypeError("reliable Research activities must expose activities()")
    registered_plugins = tuple(plugins)
    if not any(type(plugin).__name__ == "PydanticAIPlugin" for plugin in registered_plugins):
        registered_plugins = (pydantic_ai_worker_plugin(), *registered_plugins)
    return build_temporal_worker(
        client,
        task_queues=queues,
        queue=reliable_config.task_queue,
        workflows=tuple(workflows or (TemporalResearchWorkflow,)),
        activities=tuple(activity_list()),
        plugins=registered_plugins,
    )


def build_legacy_composition_root(
    *,
    reliable_policy: object | None = None,
    reliable_task_store: object | None = None,
    reliable_projection_store: object | None = None,
    reliable_event_bus: object | None = None,
    reliable_task_lifecycle: bool | None = None,
) -> CompositionRoot:
    """Create the compatibility root with an atomically validated Food Pack.

    ``reliable_task_lifecycle`` is deliberately explicit.  When enabled, a
    caller must provide a ``TemporalReliableResearchPolicy`` plus durable task
    and PostgreSQL projection stores; the root never silently falls back to
    process-local task execution or projection state.
    """

    from xhs_food.agents.poi_enricher import (
        configure_poi_place_cache_factory,
        configure_poi_place_lookup_factory,
    )
    from xhs_food.composition.adapters import (
        DisabledPublicEvidenceRepository,
        LegacyEventBusAdapter,
        LegacyFavoritesRepositoryAdapter,
        LegacyHistoryRepositoryAdapter,
        LegacyLLMProviderAdapter,
        LegacyPlaceCacheRepositoryAdapter,
        LegacySearchResultRepositoryAdapter,
        LegacySessionRepositoryAdapter,
        LegacySessionWindowAdapter,
        LegacyStateStoreAdapter,
        LegacyUserRepositoryAdapter,
        build_owner_config,
        build_place_source_connector,
        build_place_tool,
        build_xhs_source_connector,
    )
    from xhs_food.composition.adapters.food_tools import build_food_tool_gateway
    from xhs_food.composition.adapters.legacy_food import LegacyFoodPackAdapter
    from xhs_food.composition.domain_packs import (
        DomainPackRegistry,
        capability_snapshots,
        discover_allowlisted_domain_packs,
    )
    from xhs_food.composition.legacy_research_task import LegacyResearchTaskFacade
    from xhs_food.config import get_settings
    from xhs_food.contracts import (
        DomainContract,
        EventBusPort,
        ReliableTaskStorePort,
        TaskProgressProjectionPort,
    )
    from xhs_food.di import factories as legacy
    from xhs_food.domain_packs.food import load_food_contract_resources
    from xhs_food.domain_packs.food.pack import FoodBehavior
    from xhs_food.foundation import (
        Boto3ObjectStore,
        ObservabilityBootstrap,
        RedisHotStateContract,
        SQLAlchemyDatabase,
        TargetSettings,
        TemporalActivityAdapter,
        TemporalTaskQueues,
        TemporalWorkflowAdapter,
    )
    from xhs_food.gateways import SchemaToolGateway
    from xhs_food.orchestrator.agent_runtime import PydanticAIAgentRuntime
    from xhs_food.orchestrator.coordinator import ResearchCoordinator
    from xhs_food.orchestrator.scheduler import StepScheduler
    from xhs_food.services import LLMService, get_session_manager, get_user_storage_service

    discovered_food_factories = discover_allowlisted_domain_packs(("food",))
    if len(discovered_food_factories) != 1:
        raise RuntimeError(
            "Food Domain Pack discovery must return exactly one allow-listed factory; "
            f"found {len(discovered_food_factories)}"
        )
    food_pack_factory = discovered_food_factories[0]
    if not callable(food_pack_factory):
        raise RuntimeError("Food Domain Pack entry point must load a callable factory")
    food_pack_candidate = food_pack_factory()

    place_cache_repository = LegacyPlaceCacheRepositoryAdapter(get_user_storage_service)
    configure_poi_place_lookup_factory(build_place_tool)
    configure_poi_place_cache_factory(lambda: place_cache_repository)
    target_settings = TargetSettings()
    reliable_enabled = (
        target_settings.reliable_task_lifecycle
        if reliable_task_lifecycle is None
        else reliable_task_lifecycle
    )
    if reliable_enabled and reliable_policy is None:
        raise RuntimeError(
            "reliable_task_lifecycle requires an explicit Temporal/PostgreSQL policy adapter"
        )
    if reliable_enabled and not isinstance(reliable_task_store, ReliableTaskStorePort):
        raise RuntimeError(
            "reliable_task_lifecycle requires an explicit durable reliable task store"
        )
    if reliable_enabled and not isinstance(
        reliable_projection_store, TaskProgressProjectionPort
    ):
        raise RuntimeError(
            "reliable_task_lifecycle requires an explicit PostgreSQL task projection store"
        )
    if reliable_enabled and reliable_event_bus is not None and not isinstance(
        reliable_event_bus, EventBusPort
    ):
        raise RuntimeError("reliable_event_bus must implement EventBusPort")
    owner_config = build_owner_config(get_settings(), target_settings)

    food_gateway, food_providers = build_food_tool_gateway(
        build_place_tool(),
        legacy.get_xhs_tool_registry().get_required("xhs_search"),
    )
    tool_capabilities, source_capabilities = capability_snapshots(food_providers)
    domain_pack_registry = DomainPackRegistry(
        core_version="1.0.0",
        tool_capabilities=tool_capabilities,
        source_capabilities=source_capabilities,
    )
    food_manifest, food_schema_bundle = load_food_contract_resources()
    registered_food = domain_pack_registry.register_or_raise(
        food_manifest,
        cast(DomainContract, food_pack_candidate),
        food_schema_bundle,
    )
    food_implementation = registered_food.implementation
    if not isinstance(food_implementation, FoodBehavior):
        raise RuntimeError("registered Food Pack does not expose Food behavior policies")
    legacy_food_behavior = LegacyFoodPackAdapter()
    selected_food_behavior: FoodBehavior = (
        cast(FoodBehavior, registered_food)
        if target_settings.food_pack_version == food_manifest.pack_version
        else legacy_food_behavior
    )

    def legacy_llm_provider() -> LegacyLLMProviderAdapter:
        view = owner_config.model
        service = LLMService(
            model_name=view.model,
            temperature=view.temperature,
            max_tokens=view.max_tokens,
        )
        return LegacyLLMProviderAdapter(service, view)

    async def session_repository() -> LegacySessionRepositoryAdapter:
        return LegacySessionRepositoryAdapter(await get_session_manager())

    async def user_repository() -> LegacyUserRepositoryAdapter:
        return LegacyUserRepositoryAdapter(await get_user_storage_service())

    async def history_repository() -> LegacyHistoryRepositoryAdapter:
        return LegacyHistoryRepositoryAdapter(await get_user_storage_service())

    async def favorites_repository() -> LegacyFavoritesRepositoryAdapter:
        return LegacyFavoritesRepositoryAdapter(await get_user_storage_service())

    async def search_result_repository() -> LegacySearchResultRepositoryAdapter:
        return LegacySearchResultRepositoryAdapter(await get_user_storage_service())

    async def legacy_state_store() -> LegacyStateStoreAdapter:
        from api.search.state import get_state_store

        return LegacyStateStoreAdapter(await get_state_store())

    async def legacy_event_bus() -> LegacyEventBusAdapter:
        from xhs_food.events.bus import get_event_bus

        return LegacyEventBusAdapter(await get_event_bus())

    async def legacy_session_window() -> LegacySessionWindowAdapter:
        manager = await get_session_manager()
        return LegacySessionWindowAdapter(manager.session_window_backend)

    def target_database() -> SQLAlchemyDatabase:
        database_url = owner_config.repositories.target_database_url
        if not database_url:
            raise RuntimeError("target database URL is not configured")
        return SQLAlchemyDatabase(database_url, enabled=False)

    def target_temporal() -> TemporalWorkflowAdapter:
        temporal = owner_config.temporal
        return TemporalWorkflowAdapter(
            None,
            task_queues=TemporalTaskQueues(
                research=temporal.research_queue,
                refresh=temporal.refresh_queue,
                media=temporal.media_queue,
            ),
            enabled=False,
        )

    def target_temporal_activities() -> TemporalActivityAdapter:
        temporal = owner_config.temporal
        return TemporalActivityAdapter(
            {},
            task_queues=TemporalTaskQueues(
                research=temporal.research_queue,
                refresh=temporal.refresh_queue,
                media=temporal.media_queue,
            ),
            enabled=False,
        )

    def target_object_store() -> Boto3ObjectStore:
        object_store = owner_config.object_store
        if object_store.endpoint_url:
            access_key = object_store.access_key
            secret_key = object_store.secret_key
            if access_key is None or secret_key is None:
                raise RuntimeError("S3-compatible endpoint credentials are not configured")
            return Boto3ObjectStore.for_minio(
                bucket=object_store.bucket,
                endpoint_url=object_store.endpoint_url,
                access_key_id=access_key.get_secret_value(),
                secret_access_key=secret_key.get_secret_value(),
                region_name=object_store.region,
                max_concurrency=object_store.max_concurrency,
                multipart_threshold=object_store.multipart_threshold,
            )
        return Boto3ObjectStore(
            bucket=object_store.bucket,
            max_concurrency=object_store.max_concurrency,
            multipart_threshold=object_store.multipart_threshold,
        )

    def shared_research_coordinator() -> ResearchCoordinator:
        runtime = PydanticAIAgentRuntime(
            tool_gateway=food_gateway,
            enabled=False,
        )
        coordinator = ResearchCoordinator(
            LegacyResearchTaskFacade(),
            agent_runtime=runtime,
            scheduler=StepScheduler(food_gateway),
            projection_store=reliable_projection_store,  # type: ignore[arg-type]
            reliable_task_store=reliable_task_store,  # type: ignore[arg-type]
            reliable_policy=reliable_policy,  # type: ignore[arg-type]
            agent_runtime_enabled=False,
            scheduler_enabled=False,
            reliable_policy_enabled=reliable_enabled,
        )
        bind_owner = getattr(reliable_policy, "bind_owner", None)
        if reliable_enabled and callable(bind_owner):
            bind_owner(coordinator)
        return coordinator

    root = CompositionRoot()
    root.registry("foundation").register(
        AdapterBinding(
            name="xhs_service",
            contract_version="legacy/v1",
            factory=legacy.get_xhs_service,
            legacy=True,
        )
    )
    root.registry("tools").register(
        AdapterBinding(
            name="xhs_tool_registry",
            contract_version="legacy/v1",
            factory=legacy.get_xhs_tool_registry,
            legacy=True,
        )
    )
    root.registry("tools").register(
        AdapterBinding(
            name="food_tool_gateway",
            contract_version="food-tools/v1",
            factory=lambda: food_gateway,
            legacy=False,
        )
    )
    root.registry("tools").register(
        AdapterBinding(
            name="schema_tool_gateway",
            contract_version="tool-gateway/v1",
            factory=lambda: SchemaToolGateway(()),
            legacy=False,
            enabled=False,
        )
    )
    sources = root.registry("sources")
    sources.register(
        AdapterBinding(
            name="xhs_compat",
            contract_version="xhs-connector/v1",
            factory=build_xhs_source_connector,
            legacy=True,
        )
    )
    sources.register(
        AdapterBinding(
            name="food_place_capability",
            contract_version="1.0.0",
            factory=lambda: food_providers[0],
            legacy=False,
        )
    )
    sources.register(
        AdapterBinding(
            name="food_reviews_capability",
            contract_version="1.0.0",
            factory=lambda: food_providers[1],
            legacy=False,
        )
    )
    sources.register(
        AdapterBinding(
            name="place_compat",
            contract_version="amap-connector/v1",
            factory=build_place_source_connector,
            legacy=True,
        )
    )
    sources.register(
        AdapterBinding(
            name="place_tool_compat",
            contract_version="place-tool/v1",
            factory=build_place_tool,
            legacy=True,
        )
    )
    root.registry("models").register(
        AdapterBinding(
            name="legacy_llm_provider",
            contract_version="model-provider/v1",
            factory=legacy_llm_provider,
            legacy=True,
        )
    )
    repositories = root.registry("repositories")
    for name, factory in (
        ("session_legacy", session_repository),
        ("user_legacy", user_repository),
        ("history_legacy", history_repository),
        ("favorites_legacy", favorites_repository),
        ("search_result_legacy", search_result_repository),
        ("place_cache_legacy", lambda: place_cache_repository),
        ("public_evidence_disabled", DisabledPublicEvidenceRepository),
    ):
        repositories.register(
            AdapterBinding(
                name=name,
                contract_version="repository/v1",
                factory=factory,
                legacy=True,
            )
        )
    if reliable_enabled:
        repositories.register(
            AdapterBinding(
                name="reliable_task_store",
                contract_version="reliable-task-store/v1",
                factory=lambda: reliable_task_store,
                legacy=False,
            )
        )
        repositories.register(
            AdapterBinding(
                name="reliable_projection_store",
                contract_version="task-projection/v1",
                factory=lambda: reliable_projection_store,
                legacy=False,
            )
        )
    state = root.registry("state")
    for name, factory in (
        ("task_state_legacy", legacy_state_store),
        ("event_bus_legacy", legacy_event_bus),
        ("session_window_legacy", legacy_session_window),
    ):
        state.register(
            AdapterBinding(
                name=name,
                contract_version="legacy-hot-state/v1",
                factory=factory,
                legacy=True,
            )
        )
    if reliable_enabled and reliable_event_bus is not None:
        state.register(
            AdapterBinding(
                name="reliable_event_bus",
                contract_version="redis-event-bus/v1",
                factory=lambda: reliable_event_bus,
                legacy=False,
            )
        )
    target = root.registry("target_foundation")
    for name, version, factory in (
        ("sqlalchemy", "sqlalchemy-async/v1", target_database),
        ("temporal", "temporal-workflow/v1", target_temporal),
        (
            "temporal_activities",
            "temporal-activity/v1",
            target_temporal_activities,
        ),
        ("object_store", "object-store/v1", target_object_store),
        (
            "redis_contract",
            "redis-hot-state/v1",
            RedisHotStateContract,
        ),
        (
            "observability",
            "observability/v1",
            lambda: ObservabilityBootstrap(enabled=False),
        ),
    ):
        target.register(
            AdapterBinding(
                name=name,
                contract_version=version,
                factory=factory,
                legacy=False,
                enabled=False,
            )
        )
    root.registry("orchestrators").register(
        AdapterBinding(
            name="xhs_food_orchestrator",
            contract_version="legacy/v1",
            factory=lambda: legacy.get_xhs_food_orchestrator(food_pack=selected_food_behavior),
            legacy=True,
        )
    )
    packs = root.registry("domain_packs")
    packs.register(
        AdapterBinding(
            name="registry",
            contract_version="domain-pack-registry/v1",
            factory=lambda: domain_pack_registry,
            legacy=False,
        )
    )
    packs.register(
        AdapterBinding(
            name="food_1_0_0",
            contract_version="1.0.0",
            factory=lambda: registered_food,
            legacy=False,
        )
    )
    packs.register(
        AdapterBinding(
            name="food_legacy",
            contract_version="legacy/v1",
            factory=lambda: legacy_food_behavior,
            legacy=True,
        )
    )
    root.registry("use_cases").register(
        AdapterBinding(
            name="research_task",
            contract_version=(
                "research-coordinator/v1"
                if target_settings.research_core_version == "shared/v1"
                else "legacy/v1"
            ),
            factory=(
                shared_research_coordinator
                if target_settings.research_core_version == "shared/v1"
                else LegacyResearchTaskFacade
            ),
            legacy=True,
        )
    )
    root.bind_logical(
        "modular_core",
        registry_name="use_cases",
        binding_name="research_task",
    )
    if reliable_enabled:
        root.bind_logical(
            "reliable_task_lifecycle",
            registry_name="use_cases",
            binding_name="research_task",
        )
        root.bind_logical(
            "reliable_task_store",
            registry_name="repositories",
            binding_name="reliable_task_store",
        )
        root.bind_logical(
            "reliable_projection_store",
            registry_name="repositories",
            binding_name="reliable_projection_store",
        )
        if reliable_event_bus is not None:
            root.bind_logical(
                "reliable_event_bus",
                registry_name="state",
                binding_name="reliable_event_bus",
            )
    root.bind_logical(
        "food_pack",
        registry_name="domain_packs",
        binding_name=(
            "food_1_0_0"
            if target_settings.food_pack_version == food_manifest.pack_version
            else "food_legacy"
        ),
    )
    allowed_non_legacy = {
        "domain_packs.food_1_0_0",
        "domain_packs.registry",
        "sources.food_place_capability",
        "sources.food_reviews_capability",
        "tools.food_tool_gateway",
    }
    if reliable_enabled:
        allowed_non_legacy.update(
            {
                "repositories.reliable_task_store",
                "repositories.reliable_projection_store",
            }
        )
        if reliable_event_bus is not None:
            allowed_non_legacy.add("state.reliable_event_bus")
    root.assert_legacy_only(frozenset(allowed_non_legacy))
    root.activate()
    return root


__all__ = [
    "AdapterBinding",
    "BindingRegistry",
    "CompositionRoot",
    "DisabledBindingError",
    "LogicalBinding",
    "RegistryState",
    "build_legacy_composition_root",
    "build_reliable_research_worker",
]
