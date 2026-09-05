"""Composition root for the Food Research Agent and shared infrastructure."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, cast

from .modular_bindings import (
    ModularAdapterOverrides,
    ModularBindingPlan,
    build_modular_binding_plan,
)

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

    def __init__(self, *, modular_plan: ModularBindingPlan | None = None) -> None:
        self._state = RegistryState.CONFIGURING
        self._registries: dict[str, BindingRegistry] = {}
        self._logical_bindings: dict[str, LogicalBinding] = {}
        self._lifecycle_lock = asyncio.Lock()
        self._close_complete = False
        self._modular_plan = modular_plan

    @property
    def state(self) -> RegistryState:
        return self._state

    @property
    def registries(self) -> Mapping[str, BindingRegistry]:
        return MappingProxyType(self._registries)

    @property
    def logical_bindings(self) -> Mapping[str, LogicalBinding]:
        return MappingProxyType(self._logical_bindings)

    @property
    def modular_plan(self) -> ModularBindingPlan | None:
        """Return the immutable activation plan selected at bootstrap."""

        return self._modular_plan

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
            raise BaseExceptionGroup("failed to close reliable runtime bindings", errors)


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
    from xhs_food.orchestrator.reliable_task import (
        ReliableTaskConfig,
        TemporalResearchWorkflow,
        pydantic_ai_worker_plugin,
    )

    reliable_config = config if isinstance(config, ReliableTaskConfig) else ReliableTaskConfig()
    queues: TemporalTaskQueues = (
        task_queues
        if isinstance(task_queues, TemporalTaskQueues)
        else TemporalTaskQueues(
            research=reliable_config.task_queue,
            refresh="refresh",
            media="media",
        )
    )
    if queues.research != reliable_config.task_queue:
        raise ValueError("Research worker queue must match ReliableTaskConfig.task_queue")
    activity_list = cast(Callable[[], Sequence[object]] | None, getattr(activities, "activities", None))
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


def build_refresh_worker(
    client: object,
    activities: object,
    *,
    task_queues: object | None = None,
    workflows: Sequence[type[object]] = (),
    plugins: Sequence[object] = (),
) -> object:
    """Build the opt-in Refresh worker on its isolated Temporal queue."""

    from xhs_food.foundation import TemporalTaskQueues, build_temporal_refresh_worker

    queues = task_queues if isinstance(task_queues, TemporalTaskQueues) else TemporalTaskQueues()
    if not workflows:
        from xhs_food.orchestrator import TemporalRefreshWorkflow

        workflows = (TemporalRefreshWorkflow,)
    return build_temporal_refresh_worker(
        client,
        activities,
        task_queues=queues,
        workflows=workflows,
        plugins=plugins,
    )


def build_media_worker(
    client: object,
    activities: object,
    *,
    task_queues: object | None = None,
    workflows: Sequence[type[object]] = (),
    plugins: Sequence[object] = (),
) -> object:
    """Build the opt-in Media worker on its isolated Temporal queue."""

    from xhs_food.foundation import TemporalTaskQueues, build_temporal_media_worker

    queues = task_queues if isinstance(task_queues, TemporalTaskQueues) else TemporalTaskQueues()
    if not workflows:
        from xhs_food.orchestrator import TemporalMediaWorkflow

        workflows = (TemporalMediaWorkflow,)
    return build_temporal_media_worker(
        client,
        activities,
        task_queues=queues,
        workflows=workflows,
        plugins=plugins,
    )


def build_composition_root(
    *,
    reliable_policy: object | None = None,
    reliable_task_store: object | None = None,
    reliable_projection_store: object | None = None,
    reliable_event_bus: object | None = None,
    reliable_task_lifecycle: bool | None = None,
    target_settings: Any = None,
    account_service_registry: object | None = None,
    modular_overrides: ModularAdapterOverrides | None = None,
    modular_plan: ModularBindingPlan | None = None,
    modular_binding_plan: ModularBindingPlan | None = None,
) -> CompositionRoot:
    """Create the active composition root with an atomically validated Food Pack.

    ``reliable_task_lifecycle`` is deliberately explicit.  When enabled, a
    caller must provide a ``TemporalReliableResearchPolicy`` plus durable task
    and PostgreSQL projection stores; the root never silently falls back to
    process-local task execution or projection state.
    """

    from xhs_food.agents import AnalyzerAgent, IntentParserAgent
    from xhs_food.composition.adapters import (
        DisabledPublicEvidenceRepository,
        LegacyEventBusAdapter,
        LegacyFavoritesRepositoryAdapter,
        LegacyHistoryRepositoryAdapter,
        LegacyLLMProviderAdapter,
        LegacySearchResultRepositoryAdapter,
        LegacySessionRepositoryAdapter,
        LegacySessionWindowAdapter,
        LegacyStateStoreAdapter,
        LegacyUserRepositoryAdapter,
        build_owner_config,
    )
    from xhs_food.composition.domain_packs import (
        DomainPackRegistry,
        discover_allowlisted_domain_packs,
    )
    from xhs_food.composition.modular_bindings import CapabilityMode
    from xhs_food.composition.research_task import ResearchTaskFacade
    from xhs_food.config import get_settings
    from xhs_food.contracts import (
        DomainContract,
        EventBusPort,
        PersonalizationCanaryMode,
        PersonalizationCanarySettings,
        ReliableTaskStorePort,
        TaskProgressProjectionPort,
    )
    from xhs_food.domain_packs.food import load_food_contract_resources
    from xhs_food.domain_packs.food.pack import FoodBehavior
    from xhs_food.foundation import (
        Boto3ObjectStore,
        ObservabilityBootstrap,
        PersonalizationCanaryTelemetry,
        RedisHotStateContract,
        SQLAlchemyDatabase,
        TargetSettings,
        TemporalActivityAdapter,
        TemporalTaskQueues,
        TemporalWorkerQuota,
        TemporalWorkflowAdapter,
    )
    from xhs_food.orchestrator.coordinator import ResearchCoordinator
    from xhs_food.orchestrator.core import XHSFoodOrchestrator
    from xhs_food.personalization import PersonalizationCanary, PersonalizedReranker
    from xhs_food.research import (
        CommentFirstResearchWorkflow,
        ManagedMcpToolSession,
        UserStorageShopProfileRepository,
        build_query_reuse_read_service,
    )
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

    # ``target_settings`` is injectable for qualification and sidecar tests.
    # Public/unit callers that omit settings must remain deterministic and
    # legacy-only: ambient dotenv files are deployment input, not an implicit
    # change to the composition graph.  The API lifespan passes an explicit
    # TargetSettings instance after loading its configured env file.
    target_settings_was_implicit = target_settings is None
    target_settings = cast(
        Any,
        target_settings
        if target_settings is not None
        else TargetSettings(_env_file=None),
    )
    # A qualification/unit caller may deliberately construct
    # ``TargetSettings(_env_file=None)`` while another imported application
    # module has already loaded the repository ``.env`` into ``os.environ``.
    # Only fields explicitly supplied to that settings object may change the
    # default composition graph.  The API lifespan passes ``TargetSettings()``
    # (whose environment fields are part of deployment configuration), so its
    # configured account services continue to bind normally.
    explicit_fields = getattr(
        target_settings,
        "explicit_input_fields",
        getattr(target_settings, "model_fields_set", frozenset()),
    )
    ambient_environment_enabled = bool(
        getattr(target_settings, "ambient_environment_enabled", True)
    )
    account_config_explicit = bool(
        {"account_services_json", "account_services_file"} & set(explicit_fields)
    )
    policy_explicit = "agent_mcp_tool_policy_json" in set(explicit_fields)
    ambient_target_bindings_enabled = bool(
        ambient_environment_enabled and getattr(target_settings, "target_adapters_enabled", False)
    )
    if account_service_registry is None and (account_config_explicit or ambient_target_bindings_enabled):
        from xhs_food.composition.account_services import build_account_service_registry

        account_service_registry = build_account_service_registry(target_settings)
    from xhs_food.composition.account_services import AccountServiceRegistry
    from xhs_food.composition.agent_tools import (
        AccountServiceAgentToolCatalog,
        build_agent_tool_policy,
    )

    if policy_explicit or ambient_target_bindings_enabled:
        agent_tool_policy = build_agent_tool_policy(target_settings)
    else:
        # See the account-service note above: ambient dotenv values must not
        # alter a caller's intentionally empty/unit composition graph.
        from xhs_food.contracts import AgentToolPolicy

        agent_tool_policy = AgentToolPolicy()
    managed_agent_tools: AccountServiceAgentToolCatalog | None = None
    if agent_tool_policy.enabled:
        if not isinstance(account_service_registry, AccountServiceRegistry):
            raise RuntimeError("enabled Agent MCP tool policy requires an account-service registry")
        managed_agent_tools = AccountServiceAgentToolCatalog(
            account_service_registry,
            agent_tool_policy,
        )
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
    if reliable_enabled and not isinstance(reliable_projection_store, TaskProgressProjectionPort):
        raise RuntimeError(
            "reliable_task_lifecycle requires an explicit PostgreSQL task projection store"
        )
    if (
        reliable_enabled
        and reliable_event_bus is not None
        and not isinstance(reliable_event_bus, EventBusPort)
    ):
        raise RuntimeError("reliable_event_bus must implement EventBusPort")
    owner_config = build_owner_config(get_settings(), cast(TargetSettings, target_settings))
    if modular_overrides is None:
        modular_overrides = ModularAdapterOverrides()
    elif not isinstance(modular_overrides, ModularAdapterOverrides):
        raise TypeError("modular_overrides must be a ModularAdapterOverrides instance")

    # A caller may supply a prevalidated plan from a deployment coordinator or
    # qualification fixture.  Keep both spellings for compatibility with the
    # public design terminology, but reject two conflicting plan objects so the
    # graph can never be assembled from mixed configuration snapshots.
    if (
        modular_plan is not None
        and modular_binding_plan is not None
        and modular_plan != modular_binding_plan
    ):
        raise ValueError("modular_plan and modular_binding_plan must identify one plan")
    explicit_plan_supplied = modular_plan is not None or modular_binding_plan is not None
    selected_plan = (
        modular_plan if modular_plan is not None else modular_binding_plan
    )
    if selected_plan is None:
        selected_plan = build_modular_binding_plan(
            cast(TargetSettings, target_settings), owner_config
        )
    elif not isinstance(selected_plan, ModularBindingPlan):
        raise TypeError("modular_plan must be a ModularBindingPlan instance")
    # ``validate`` is intentionally called even for injected plans: the plan
    # is the immutable activation boundary, not an unchecked dependency bag.
    modular_plan = selected_plan.validate()
    modular_overrides = cast(ModularAdapterOverrides, modular_overrides)
    canary_enabled = modular_plan.personalization_mode is not CapabilityMode.OFF
    memory_bindings_enabled = modular_plan.has_memory_bindings and (
        not target_settings_was_implicit
        or explicit_plan_supplied
        or any(
            value is not None
            for value in (
                modular_overrides.memory_repository,
                modular_overrides.memory_session_window,
                modular_overrides.memory_outbox_projector,
                modular_overrides.memory_authority_writer,
            )
        )
    )

    def require_override(value: object | None, name: str) -> object:
        if value is None:
            raise RuntimeError(f"active modular capability requires {name} adapter override")
        return value

    def require_methods(value: object, name: str, methods: tuple[str, ...]) -> object:
        missing = tuple(method for method in methods if not callable(getattr(value, method, None)))
        if missing:
            joined = ", ".join(missing)
            raise TypeError(f"{name} adapter is missing required methods: {joined}")
        return value

    if modular_plan.evidence_mode is CapabilityMode.SHADOW:
        evidence_shadow_sink = require_override(
            modular_overrides.evidence_shadow_sink,
            "evidence_shadow_sink",
        )
        require_methods(
            evidence_shadow_sink,
            "evidence_shadow_sink",
            ("write",),
        )
        canonical_query_shadow = modular_overrides.canonical_query_shadow
        if canonical_query_shadow is None and not getattr(
            evidence_shadow_sink, "supports_atomic_canonical_query", False
        ):
            raise RuntimeError(
                "active modular capability requires canonical_query_shadow adapter override "
                "unless evidence_shadow_sink owns canonical identity atomically"
            )
        if canonical_query_shadow is not None:
            require_methods(canonical_query_shadow, "canonical_query_shadow", ("save",))

    # Source connectors are supplied by the runtime that owns platform
    # credentials.  When that runtime injects the connector map, the
    # Composition Root still owns the Source Gateway boundary and applies the
    # explicitly supplied B1 decorator before registration.  A pre-built
    # gateway remains injectable for deployments that own connector creation
    # outside this process.
    source_gateway: object | None = modular_overrides.source_gateway
    if source_gateway is not None and modular_overrides.source_connectors is not None:
        raise ValueError("source_gateway and source_connectors are mutually exclusive")
    if source_gateway is not None:
        require_methods(source_gateway, "source_gateway", ("collect", "collect_one"))
    elif modular_overrides.source_connectors is not None:
        source_connectors = modular_overrides.source_connectors
        if not isinstance(source_connectors, Mapping):
            raise TypeError("source_connectors must be a mapping")
        for source_id, connector in source_connectors.items():
            if not isinstance(source_id, str) or not source_id:
                raise TypeError("source_connectors keys must be non-empty strings")
            require_methods(connector, f"source_connectors[{source_id!r}]", ("search",))
        connector_decorator = None
        if modular_plan.evidence_mode is CapabilityMode.SHADOW:
            connector_decorator = require_override(
                modular_overrides.source_connector_decorator,
                "source_connector_decorator",
            )
            if not callable(connector_decorator):
                raise TypeError("source_connector_decorator must be callable")
        # Ignore an accidentally supplied decorator while B1 is off.  This
        # preserves the exact legacy connector instances and makes the
        # closed-world setting authoritative at the composition boundary.
        from xhs_food.gateways import SourceGateway

        source_gateway = SourceGateway(
            cast(Mapping[str, Any], source_connectors),
            connector_decorator=cast(Any, connector_decorator),
        )

    query_family_repository: object | None = None
    query_reuse_read: object | None = None
    if modular_plan.query_mode is not CapabilityMode.OFF:
        query_family_repository = require_override(
            modular_overrides.query_family_repository,
            "query_family_repository",
        )
        require_methods(
            query_family_repository,
            "query_family_repository",
            (
                "get_exact",
                "search_trigram",
                "search_vector",
                "get_freshness",
                "save_freshness",
                "claim_refresh",
                "activate_bundle_if_current",
                "update_refresh_status",
            ),
        )
        query_reuse_read = modular_overrides.query_reuse_read
        if query_reuse_read is None:
            query_reuse_read = build_query_reuse_read_service(
                query_family_repository,
                mode=modular_plan.query_reuse_read.mode,
                sample_rate=modular_plan.query_reuse_read.sample_rate,
                min_confidence=modular_plan.query_reuse_read.min_confidence,
                canary_gate_approved=modular_plan.query_reuse_read.b1_gate_approved,
            )
        require_methods(query_reuse_read, "query_reuse_read", ("read",))
    if memory_bindings_enabled:
        require_methods(
            require_override(modular_overrides.memory_repository, "memory_repository"),
            "memory_repository",
            (
                "append_conversation_turn",
                "save_record",
                "commit_authority_write",
                "append_memory_event",
                "list_records",
                "list_conversation_turns",
                "claim_anonymous",
                "save_preference_snapshot",
                "enqueue_outbox",
            ),
        )
        memory_session_window = require_override(
            modular_overrides.memory_session_window,
            "memory_session_window",
        )
        require_methods(
            memory_session_window,
            "memory_session_window",
            ("append", "recent", "clear"),
        )
        if modular_overrides.memory_outbox_projector is not None:
            require_methods(
                modular_overrides.memory_outbox_projector,
                "memory_outbox_projector",
                ("project",),
            )
        if modular_overrides.memory_authority_writer is not None:
            require_methods(
                modular_overrides.memory_authority_writer,
                "memory_authority_writer",
                ("write",),
            )
    observation_port: object | None = None
    evaluation_port: object | None = None
    if modular_plan.observability_enabled:
        if modular_overrides.observation_port is None:
            if not modular_plan.observability.exporter_endpoint:
                raise RuntimeError(
                    "OTel enabled without an injected observation_port requires an OTLP exporter endpoint"
                )
            from xhs_food.composition.adapters import build_observation_exporter

            observation_port = build_observation_exporter(
                endpoint=modular_plan.observability.exporter_endpoint,
                enabled=True,
                service_name=modular_plan.observability.service_name,
                api_version=modular_plan.observability.phoenix_api_version,
                max_queue_size=modular_plan.observability.max_queue_size,
                max_batch_size=modular_plan.observability.max_batch_size,
                schedule_delay_ms=modular_plan.observability.schedule_delay_ms,
                export_timeout_ms=modular_plan.observability.export_timeout_ms,
                retry_limit=modular_plan.observability.retry_limit,
                sampling_rate=modular_plan.observability.sampling_rate,
                shutdown_flush_timeout_ms=modular_plan.observability.shutdown_flush_timeout_ms,
                drop_policy=modular_plan.observability.drop_policy,
            )
        else:
            observation_port = modular_overrides.observation_port
        require_methods(
            observation_port,
            "observation_port",
            ("observe", "flush", "health"),
        )
        if modular_overrides.evaluation_port is None:
            from xhs_food.composition.adapters import build_evaluation_port

            evaluation_port = build_evaluation_port(
                endpoint=modular_plan.observability.phoenix_evaluation_endpoint,
                enabled=modular_plan.phoenix_enabled,
                api_version=modular_plan.observability.phoenix_api_version,
                timeout_ms=modular_plan.observability.export_timeout_ms,
                retry_limit=modular_plan.observability.retry_limit,
            )
        else:
            evaluation_port = modular_overrides.evaluation_port
        require_methods(
            evaluation_port,
            "evaluation_port",
            ("submit_dataset", "submit_run", "close", "health"),
        )

    domain_pack_registry = DomainPackRegistry(
        core_version="1.0.0",
        tool_capabilities={},
        source_capabilities={},
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
    model_view = owner_config.model
    configured_llm = LLMService(
        model_name=model_view.model,
        temperature=model_view.temperature,
        max_tokens=model_view.max_tokens,
        reasoning_effort=model_view.reasoning_effort,
    )

    def research_session() -> ManagedMcpToolSession:
        """Create one MCP session; a workflow closes it after each turn."""

        return ManagedMcpToolSession(managed_agent_tools, managed_agent_tools)

    def research_workflow() -> CommentFirstResearchWorkflow:
        profile_repository = UserStorageShopProfileRepository(get_user_storage_service)

        return CommentFirstResearchWorkflow(
            session_factory=research_session,
            intent_parser=IntentParserAgent(configured_llm),
            analyzer=AnalyzerAgent(configured_llm),
            profiles=profile_repository,
            max_notes=getattr(get_settings(), "search_note_limit", 30),
            max_restaurants=getattr(get_settings(), "search_max_restaurants", 10),
            analysis_concurrency=getattr(get_settings(), "analyze_concurrency", 3),
            profile_concurrency=getattr(get_settings(), "profile_concurrency", 3),
            profile_refresh_after=timedelta(
                hours=getattr(get_settings(), "shop_profile_refresh_hours", 168)
            ),
            partial_profile_retry_after=timedelta(
                hours=getattr(get_settings(), "shop_profile_partial_retry_hours", 12)
            ),
        )

    # One immutable dependency graph is shared by session-scoped orchestrator
    # facades; conversation state itself remains on each orchestrator.
    active_research_workflow = research_workflow()

    def legacy_llm_provider() -> LegacyLLMProviderAdapter:
        view = owner_config.model
        service = LLMService(
            model_name=view.model,
            temperature=view.temperature,
            max_tokens=view.max_tokens,
            reasoning_effort=view.reasoning_effort,
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
                refresh_quota=TemporalWorkerQuota(
                    temporal.refresh_queue, 2, 2, 50, enabled=temporal.refresh_enabled
                ),
                media_quota=TemporalWorkerQuota(
                    temporal.media_queue, 2, 2, 25, enabled=temporal.media_enabled
                ),
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
                refresh_quota=TemporalWorkerQuota(
                    temporal.refresh_queue, 2, 2, 50, enabled=temporal.refresh_enabled
                ),
                media_quota=TemporalWorkerQuota(
                    temporal.media_queue, 2, 2, 25, enabled=temporal.media_enabled
                ),
            ),
            enabled=False,
        )

    def target_object_store() -> Boto3ObjectStore:
        object_store = owner_config.object_store
        extra: dict[str, Any] = {}
        optional_config_allowed = bool(
            getattr(target_settings, "ambient_environment_enabled", True)
            or {
                "object_store_environment",
                "object_store_server_side_encryption",
                "object_store_encryption_key_ref",
                "object_store_signed_url_ttl_seconds",
                "object_store_orphan_grace_seconds",
            }
            & set(
                getattr(
                    target_settings,
                    "explicit_input_fields",
                    getattr(target_settings, "model_fields_set", frozenset()),
                )
            )
        )
        if optional_config_allowed and object_store.multipart_chunk_size != 8 * 1024 * 1024:
            extra["multipart_chunksize"] = object_store.multipart_chunk_size
        if optional_config_allowed and object_store.max_bytes != 50 * 1024 * 1024:
            extra["max_object_bytes"] = object_store.max_bytes
        default_content_types = (
            "application/json",
            "audio/mpeg",
            "image/jpeg",
            "image/png",
            "image/webp",
            "text/plain",
            "video/mp4",
        )
        if object_store.allowed_content_types != default_content_types:
            extra["allowed_content_types"] = object_store.allowed_content_types
        if optional_config_allowed and object_store.environment != "test":
            extra["environment"] = object_store.environment
        if optional_config_allowed and object_store.server_side_encryption is not None:
            extra["server_side_encryption"] = object_store.server_side_encryption
        if optional_config_allowed and object_store.encryption_key_ref is not None:
            extra["encryption_key_ref"] = object_store.encryption_key_ref
        if optional_config_allowed and object_store.signed_url_ttl_seconds is not None:
            extra["signed_url_ttl_seconds"] = object_store.signed_url_ttl_seconds
        if optional_config_allowed and object_store.orphan_grace_seconds is not None:
            extra["orphan_grace_seconds"] = object_store.orphan_grace_seconds
        if object_store.environment == "production":
            extra["require_encryption"] = True
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
                **extra,
            )
        return Boto3ObjectStore(
            bucket=object_store.bucket,
            max_concurrency=object_store.max_concurrency,
            multipart_threshold=object_store.multipart_threshold,
            **extra,
        )

    def shared_research_coordinator() -> ResearchCoordinator:
        # The HTTP task lifecycle is a transport concern.  Its coordinator is
        # deliberately not given a second tool gateway; the Agent workflow
        # above is the sole owner of MCP source execution.
        coordinator = ResearchCoordinator(
            ResearchTaskFacade(),
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

    def personalization_canary() -> PersonalizationCanary:
        personalization = modular_plan.personalization
        settings = PersonalizationCanarySettings(
            mode=PersonalizationCanaryMode(personalization.mode),
            sample_rate=personalization.sample_rate,
            projection_warmup_enabled=personalization.projection_warmup_enabled,
        )
        telemetry = PersonalizationCanaryTelemetry()
        return PersonalizationCanary(
            PersonalizedReranker(),
            settings=settings,
            recorder=telemetry.record,
        )

    root = CompositionRoot(modular_plan=modular_plan)

    def bind_modular_value(
        *,
        registry_name: str,
        binding_name: str,
        logical_name: str,
        contract_version: str,
        value: object,
    ) -> None:
        registry = root.registry(registry_name)
        registry.register(
            AdapterBinding(
                name=binding_name,
                contract_version=contract_version,
                factory=lambda value=value: value,
                legacy=False,
            )
        )
        root.bind_logical(
            logical_name,
            registry_name=registry_name,
            binding_name=binding_name,
        )

    if source_gateway is not None:
        bind_modular_value(
            registry_name="gateways",
            binding_name="source",
            logical_name="source.gateway",
            contract_version="source-gateway/v1",
            value=source_gateway,
        )
    if modular_plan.evidence_mode is CapabilityMode.SHADOW:
        if modular_overrides.canonical_query_shadow is not None:
            bind_modular_value(
                registry_name="evidence",
                binding_name="canonical_query_shadow",
                logical_name="evidence.canonical_query_shadow",
                contract_version="canonical-query-shadow/v1",
                value=modular_overrides.canonical_query_shadow,
            )
        bind_modular_value(
            registry_name="evidence",
            binding_name="shadow_sink",
            logical_name="evidence.shadow_sink",
            contract_version="evidence-shadow-sink/v1",
            value=evidence_shadow_sink,
        )
    if modular_plan.query_mode is not CapabilityMode.OFF:
        bind_modular_value(
            registry_name="evidence",
            binding_name="query_family_repository",
            logical_name="evidence.query_family_repository",
            contract_version="query-family-repository/v1",
            value=query_family_repository,
        )
        bind_modular_value(
            registry_name="evidence",
            binding_name="query_reuse_read",
            logical_name="evidence.query_reuse_read",
            contract_version="query-reuse-read/v1",
            value=query_reuse_read,
        )
    if memory_bindings_enabled:
        from xhs_food.composition.adapters import MemoryAuthorityWriter, MemoryOutboxProjector

        memory_repository = require_override(
            modular_overrides.memory_repository,
            "memory_repository",
        )
        memory_session_window = require_override(
            modular_overrides.memory_session_window,
            "memory_session_window",
        )
        outbox_projector = modular_overrides.memory_outbox_projector
        if outbox_projector is None:
            outbox_projector = MemoryOutboxProjector(cast(Any, memory_session_window))
        require_methods(outbox_projector, "memory_outbox_projector", ("project",))
        authority_writer = modular_overrides.memory_authority_writer
        if authority_writer is None:
            authority_writer = MemoryAuthorityWriter(
                cast(Any, memory_repository), cast(Any, outbox_projector)
            )
        require_methods(authority_writer, "memory_authority_writer", ("write",))
        bind_modular_value(
            registry_name="memory",
            binding_name="authority_repository",
            logical_name="memory.authority_repository",
            contract_version="memory-authority-repository/v1",
            value=memory_repository,
        )
        bind_modular_value(
            registry_name="memory",
            binding_name="session_projection",
            logical_name="memory.session_projection",
            contract_version="memory-session-projection/v1",
            value=memory_session_window,
        )
        bind_modular_value(
            registry_name="memory",
            binding_name="outbox_projector",
            logical_name="memory.outbox_projector",
            contract_version="memory-outbox-projector/v1",
            value=outbox_projector,
        )
        bind_modular_value(
            registry_name="memory",
            binding_name="authority_writer",
            logical_name="memory.authority_writer",
            contract_version="memory-authority-writer/v1",
            value=authority_writer,
        )
    if modular_plan.observability_enabled:
        assert observation_port is not None
        assert evaluation_port is not None
        bind_modular_value(
            registry_name="observability",
            binding_name="observation_port",
            logical_name="observability.observation_port",
            contract_version="observation-port/v1",
            value=observation_port,
        )
        bind_modular_value(
            registry_name="observability",
            binding_name="evaluation_port",
            logical_name="observability.evaluation_port",
            contract_version="evaluation-port/v1",
            value=evaluation_port,
        )
    if account_service_registry is not None:
        service_registry = root.registry("account_services")
        service_registry.register(
            AdapterBinding(
                name="remote",
                contract_version="account-service-registry/v1",
                factory=lambda: account_service_registry,
                legacy=False,
            )
        )
        root.bind_logical(
            "account_services",
            registry_name="account_services",
            binding_name="remote",
        )
    if managed_agent_tools is not None:
        agent_tools_registry = root.registry("agent_tools")
        agent_tools_registry.register(
            AdapterBinding(
                name="account_service_mcp",
                contract_version="agent-tool-catalog/v1",
                factory=lambda: managed_agent_tools,
                legacy=False,
            )
        )
        root.bind_logical(
            "agent_tool_catalog",
            registry_name="agent_tools",
            binding_name="account_service_mcp",
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
            contract_version="comment-first-agent/v1",
            factory=lambda: XHSFoodOrchestrator(
                workflow=active_research_workflow,
            ),
            legacy=False,
        )
    )
    root.registry("research").register(
        AdapterBinding(
            name="comment_first_workflow",
            contract_version="comment-first-workflow/v1",
            factory=lambda: active_research_workflow,
            legacy=False,
        )
    )
    root.bind_logical(
        "research_agent",
        registry_name="research",
        binding_name="comment_first_workflow",
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
    root.registry("use_cases").register(
        AdapterBinding(
            name="research_task",
            contract_version="research-task/v2",
            factory=shared_research_coordinator,
            legacy=False,
        )
    )
    if canary_enabled:
        root.registry("personalization").register(
            AdapterBinding(
                name="canary",
                contract_version="personalization-canary/v1",
                factory=personalization_canary,
                legacy=False,
            )
        )
    # The task facade is a transport-facing entry point.  Keep its logical
    # name explicit so callers do not depend on the retired modular-core
    # compatibility alias.
    root.bind_logical(
        "research_task",
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
    if canary_enabled:
        root.bind_logical(
            "personalization_canary",
            registry_name="personalization",
            binding_name="canary",
        )
    root.bind_logical(
        "food_pack",
        registry_name="domain_packs",
        binding_name="food_1_0_0",
    )
    allowed_non_legacy = {
        "domain_packs.food_1_0_0",
        "domain_packs.registry",
        "orchestrators.xhs_food_orchestrator",
        "research.comment_first_workflow",
        "use_cases.research_task",
    }
    if modular_plan.evidence_mode is CapabilityMode.SHADOW:
        allowed_non_legacy.update(
            {
                "evidence.canonical_query_shadow",
                "evidence.shadow_sink",
            }
        )
    if source_gateway is not None:
        allowed_non_legacy.add("gateways.source")
    if modular_plan.query_mode is not CapabilityMode.OFF:
        allowed_non_legacy.update(
            {
                "evidence.query_family_repository",
                "evidence.query_reuse_read",
            }
        )
    if memory_bindings_enabled:
        allowed_non_legacy.update(
            {
                "memory.authority_repository",
                "memory.session_projection",
                "memory.outbox_projector",
                "memory.authority_writer",
            }
        )
    if modular_plan.observability_enabled:
        allowed_non_legacy.update(
            {
                "observability.observation_port",
                "observability.evaluation_port",
            }
        )
    if reliable_enabled:
        allowed_non_legacy.update(
            {
                "repositories.reliable_task_store",
                "repositories.reliable_projection_store",
            }
        )
        if reliable_event_bus is not None:
            allowed_non_legacy.add("state.reliable_event_bus")
    if canary_enabled:
        allowed_non_legacy.add("personalization.canary")
    if account_service_registry is not None:
        allowed_non_legacy.add("account_services.remote")
    if managed_agent_tools is not None:
        allowed_non_legacy.add("agent_tools.account_service_mcp")
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
    "build_media_worker",
    "build_composition_root",
    "build_refresh_worker",
    "build_reliable_research_worker",
]
