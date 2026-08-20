"""Static S1 architecture gates with shrink-only legacy violation baselines."""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
import warnings
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"
POLICY_PATH = ROOT / "tests/fixtures/architecture/dependency_policy_v1.json"
PYPROJECT_PATH = ROOT / "pyproject.toml"
UV_LOCK_PATH = ROOT / "uv.lock"

_DISTRIBUTION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
_RUNTIME_DDL = re.compile(
    r"^\s*(CREATE|ALTER|DROP|TRUNCATE)\s+"
    r"(TABLE|INDEX|SCHEMA|EXTENSION|TYPE|FUNCTION)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LayerRule:
    prefix: str
    layer: str
    mode: str
    match: str = "prefix"


@dataclass(frozen=True)
class ImportEdge:
    source_module: str
    source_layer: str
    target: str
    target_layer: str

    @property
    def identity(self) -> str:
        return f"{self.source_module}|{self.source_layer}->{self.target_layer}|{self.target}"


@dataclass(frozen=True)
class ImportTarget:
    identity: str
    module: str


@dataclass(frozen=True)
class PrivateAccess:
    module: str
    scope: str
    receiver: str
    attribute: str

    @property
    def identity(self) -> str:
        return f"{self.module}|{self.scope}|{self.receiver}.{self.attribute}"


def _load_policy() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _rules(policy: dict[str, Any]) -> tuple[LayerRule, ...]:
    rules = (LayerRule(**item) for item in policy["module_layers"])
    return tuple(sorted(rules, key=lambda item: len(item.prefix), reverse=True))


def _module_name(path: Path, source_root: Path) -> str:
    relative = path.relative_to(source_root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _layer_for(module: str, rules: tuple[LayerRule, ...]) -> LayerRule | None:
    return next(
        (
            rule
            for rule in rules
            if module == rule.prefix
            or (rule.match == "prefix" and module.startswith(f"{rule.prefix}."))
        ),
        None,
    )


def _resolve_import(current_module: str, path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = current_module if path.name == "__init__.py" else current_module.rpartition(".")[0]
    relative = f"{'.' * node.level}{node.module or ''}"
    return resolve_name(relative, package)


def _parse_module(path: Path) -> ast.Module:
    source = path.read_text(encoding="utf-8-sig")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(source, filename=str(path))


def _target_modules(
    source_root: Path, policy: dict[str, Any]
) -> tuple[tuple[str, Path, ast.Module], ...]:
    rules = _rules(policy)
    modules: list[tuple[str, Path, ast.Module]] = []
    for path in sorted(source_root.rglob("*.py")):
        module = _module_name(path, source_root)
        rule = _layer_for(module, rules)
        if rule is not None and rule.mode == "target":
            modules.append((module, path, _parse_module(path)))
    return tuple(modules)


def _import_targets(current_module: str, path: Path, node: ast.AST) -> tuple[ImportTarget, ...]:
    if isinstance(node, ast.Import):
        return tuple(ImportTarget(alias.name, alias.name) for alias in node.names)
    if not isinstance(node, ast.ImportFrom):
        return ()
    base = _resolve_import(current_module, path, node)
    return tuple(
        ImportTarget(
            identity=f"{base}.{alias.name}" if base else alias.name,
            module=base,
        )
        for alias in node.names
    )


def _scan_import_violations(source_root: Path, policy: dict[str, Any]) -> set[str]:
    rules = _rules(policy)
    allowed_edges = policy["allowed_internal_edges"]
    allowed_compatibility_imports = set(policy["allowed_compatibility_imports"])
    third_party = policy["target_third_party_allowlist"]
    violations: set[str] = set()

    for path in sorted(source_root.rglob("*.py")):
        module = _module_name(path, source_root)
        source_rule = _layer_for(module, rules)
        if source_rule is None:
            violations.add(f"{module}|unclassified-source-module")
            continue
        tree = _parse_module(path)
        for node in ast.walk(tree):
            for target in _import_targets(module, path, node):
                target_rule = _layer_for(target.identity, rules) or _layer_for(target.module, rules)
                if target_rule is not None:
                    allowed = allowed_edges[source_rule.layer]
                    if "*" not in allowed and target_rule.layer not in allowed:
                        compatibility_identity = f"{module}|{target.identity}"
                        if compatibility_identity in allowed_compatibility_imports:
                            continue
                        violations.add(
                            ImportEdge(
                                source_module=module,
                                source_layer=source_rule.layer,
                                target=target.identity,
                                target_layer=target_rule.layer,
                            ).identity
                        )
                    continue

                root = target.module.partition(".")[0]
                if root in sys.stdlib_module_names:
                    continue
                if source_rule.mode != "target":
                    continue
                allowed_external = third_party.get(source_rule.layer, [])
                if "*" not in allowed_external and root not in allowed_external:
                    violations.add(f"{module}|{source_rule.layer}->third_party|{target.identity}")
    return violations


class _PrivateAccessVisitor(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.scope: list[str] = []
        self.violations: set[str] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in {"getattr", "setattr", "delattr"}
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and node.args[1].value.startswith("_")
            and not node.args[1].value.startswith("__")
        ):
            receiver = ast.unparse(node.args[0])
            if receiver not in {"self", "cls"}:
                access = PrivateAccess(
                    module=self.module,
                    scope=".".join(self.scope) or "<module>",
                    receiver=receiver,
                    attribute=node.args[1].value,
                )
                self.violations.add(access.identity)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if node.attr.startswith("_") and not node.attr.startswith("__"):
            receiver = ast.unparse(node.value)
            is_own_state = isinstance(node.value, ast.Name) and node.value.id in {
                "self",
                "cls",
            }
            is_super = (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "super"
            )
            if not is_own_state and not is_super:
                access = PrivateAccess(
                    module=self.module,
                    scope=".".join(self.scope) or "<module>",
                    receiver=receiver,
                    attribute=node.attr,
                )
                self.violations.add(access.identity)
        self.generic_visit(node)


def _scan_private_access_violations(source_root: Path) -> set[str]:
    violations: set[str] = set()
    for path in sorted(source_root.rglob("*.py")):
        module = _module_name(path, source_root)
        tree = _parse_module(path)
        visitor = _PrivateAccessVisitor(module)
        visitor.visit(tree)
        violations.update(visitor.violations)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            imported_from = _resolve_import(module, path, node)
            for alias in node.names:
                if alias.name.startswith("_") and not alias.name.startswith("__"):
                    violations.add(
                        PrivateAccess(
                            module=module,
                            scope="<module>",
                            receiver=imported_from,
                            attribute=alias.name,
                        ).identity
                    )
    return violations


def _normalize_distribution(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _requirement_name(requirement: str) -> str:
    match = _DISTRIBUTION_NAME.match(requirement.strip())
    if match is None:
        raise ValueError(f"invalid dependency requirement: {requirement!r}")
    return _normalize_distribution(match.group())


def _declared_dependency_names(path: Path) -> set[str]:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    requirements = list(document.get("project", {}).get("dependencies", ()))
    for group in document.get("project", {}).get("optional-dependencies", {}).values():
        requirements.extend(group)
    for group in document.get("dependency-groups", {}).values():
        requirements.extend(group)
    requirements.extend(document.get("build-system", {}).get("requires", ()))
    return {_requirement_name(requirement) for requirement in requirements}


def _locked_dependency_names(path: Path) -> set[str]:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    return {_normalize_distribution(package["name"]) for package in document.get("package", ())}


def _scan_forbidden_imports(source_root: Path, forbidden_roots: set[str]) -> set[str]:
    violations: set[str] = set()
    for path in sorted(source_root.rglob("*.py")):
        module = _module_name(path, source_root)
        tree = _parse_module(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.partition(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported_from = _resolve_import(module, path, node)
                roots = {imported_from.partition(".")[0]}
            else:
                continue
            for root in roots & forbidden_roots:
                violations.add(f"{module}|forbidden-import|{root}")
    return violations


def _matches_module_prefix(value: str, prefix: str) -> bool:
    return value == prefix or value.startswith(f"{prefix}.")


def _scan_owner_port_boundary_violations(source_root: Path, policy: dict[str, Any]) -> set[str]:
    consumer_prefixes = set(policy["owner_port_consumer_module_prefixes"])
    forbidden_imports = set(policy["owner_port_forbidden_import_prefixes"])
    forbidden_symbols = set(policy["owner_port_forbidden_import_symbols"])
    foundation_prefixes = set(policy["foundation_module_prefixes"])
    food_imports = set(policy["foundation_forbidden_food_import_prefixes"])
    violations: set[str] = set()

    for path in sorted(source_root.rglob("*.py")):
        module = _module_name(path, source_root)
        is_consumer = any(_matches_module_prefix(module, prefix) for prefix in consumer_prefixes)
        is_foundation = any(
            _matches_module_prefix(module, prefix) for prefix in foundation_prefixes
        )
        if not is_consumer and not is_foundation:
            continue
        tree = _parse_module(path)
        for node in ast.walk(tree):
            for target in _import_targets(module, path, node):
                identities = (target.module, target.identity)
                if is_consumer and (
                    target.identity.rpartition(".")[2] in forbidden_symbols
                    or any(
                        _matches_module_prefix(identity, prefix)
                        for identity in identities
                        for prefix in forbidden_imports
                    )
                ):
                    violations.add(f"{module}|owner-port-bypass|{target.identity}")
                if is_foundation and any(
                    _matches_module_prefix(identity, prefix)
                    for identity in identities
                    for prefix in food_imports
                ):
                    violations.add(f"{module}|foundation-food-dependency|{target.identity}")
    return violations


def _import_aliases(module: str, path: Path, tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.partition(".")[0]
                aliases[local] = alias.name if alias.asname else local
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_import(module, path, node)
            for alias in node.names:
                local = alias.asname or alias.name
                aliases[local] = f"{base}.{alias.name}" if base else alias.name
    return aliases


def _qualified_name(node: ast.AST, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value, aliases)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _scan_target_authority_violations(source_root: Path, policy: dict[str, Any]) -> set[str]:
    pool_owners = policy["database_pool_factories"]
    forbidden_pools = set(policy["forbidden_target_database_pool_factories"])
    forbidden_import_roots = set(policy["forbidden_target_runtime_import_roots"])
    schema_calls = set(policy["forbidden_runtime_schema_calls"])
    violations: set[str] = set()

    for module, path, tree in _target_modules(source_root, policy):
        aliases = _import_aliases(module, path, tree)
        for imported in aliases.values():
            root = imported.partition(".")[0]
            if root in forbidden_import_roots:
                violations.add(f"{module}|runtime-schema-import|{root}")
            owner = pool_owners.get(imported)
            if owner is not None and module != owner:
                violations.add(f"{module}|database-pool-owner|{imported}->{owner}")
            if imported in forbidden_pools:
                violations.add(f"{module}|forbidden-database-pool|{imported}")

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = _qualified_name(node.func, aliases)
            if called is None:
                continue
            owner = pool_owners.get(called)
            if owner is not None and module != owner:
                violations.add(f"{module}|database-pool-owner|{called}->{owner}")
            if called in forbidden_pools:
                violations.add(f"{module}|forbidden-database-pool|{called}")
            if called.rpartition(".")[2] in schema_calls:
                violations.add(f"{module}|runtime-schema-call|{called}")
            if called.rpartition(".")[2] not in {"execute", "exec_driver_sql"}:
                continue
            for argument in node.args:
                if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
                    continue
                match = _RUNTIME_DDL.match(argument.value)
                if match is not None:
                    operation = f"{match.group(1).upper()} {match.group(2).upper()}"
                    violations.add(f"{module}|runtime-ddl|{operation}")
    return violations


def _identifier_tokens(value: str) -> set[str]:
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value).lower()
    return {token for token in re.split(r"[^a-z0-9]+", snake) if token}


def _class_definition(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"missing class {name}")


def _class_methods(node: ast.ClassDef) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        item.name: item
        for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not item.name.startswith("__")
    }


def _redis_key_prefixes(tree: ast.Module) -> set[str]:
    prefixes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        if any(isinstance(target, ast.Name) and target.id == "KEY_PREFIX" for target in targets):
            prefixes.add(value.value)
    return prefixes


def _assert_shrink_only(actual: set[str], baseline: list[str], kind: str) -> None:
    frozen = set(baseline)
    additions = sorted(actual - frozen)
    assert not additions, (
        f"new {kind} violations are forbidden; remove the dependency/access or explicitly "
        f"reclassify the architecture before changing the baseline:\n"
        f"{json.dumps(additions, indent=2, ensure_ascii=False)}"
    )


def test_current_import_graph_has_no_new_cross_layer_concrete_dependencies() -> None:
    policy = _load_policy()
    actual = _scan_import_violations(SRC, policy)
    baseline = policy["legacy_import_violations"]

    assert baseline, "the reviewed legacy import baseline must remain explicit and non-empty"
    _assert_shrink_only(actual, baseline, "cross-layer import")


def test_current_source_has_no_new_cross_object_private_attribute_access() -> None:
    policy = _load_policy()
    actual = _scan_private_access_violations(SRC)
    baseline = policy["legacy_private_access_violations"]

    assert baseline, "the reviewed legacy private-access baseline must remain explicit"
    _assert_shrink_only(actual, baseline, "private attribute access")


def test_default_deny_and_composition_root_exception_are_exercised(tmp_path: Path) -> None:
    policy = _load_policy()
    bad = tmp_path / "xhs_food/contracts/bad.py"
    bad.parent.mkdir(parents=True)
    bad.write_text(
        "import redis\nfrom xhs_food.services import LLMService\n",
        encoding="utf-8",
    )
    assert _scan_import_violations(tmp_path, policy) == {
        "xhs_food.contracts.bad|contracts->foundation|xhs_food.services.LLMService",
        "xhs_food.contracts.bad|contracts->third_party|redis",
    }

    bad.unlink()
    wiring = tmp_path / "xhs_food/composition/wiring.py"
    wiring.parent.mkdir(parents=True, exist_ok=True)
    wiring.write_text(
        "from xhs_food.contracts import LLMProvider\nfrom xhs_food.services import LLMService\n",
        encoding="utf-8",
    )
    assert _scan_import_violations(tmp_path, policy) == set()

    wiring.unlink()
    unowned = tmp_path / "xhs_food/new_core.py"
    unowned.write_text("VALUE = 1\n", encoding="utf-8")
    assert _scan_import_violations(tmp_path, policy) == {
        "xhs_food.new_core|unclassified-source-module"
    }


def test_parent_package_import_is_classified_by_imported_submodule(tmp_path: Path) -> None:
    policy = _load_policy()
    module = tmp_path / "xhs_food/state.py"
    module.parent.mkdir(parents=True)
    module.write_text("from xhs_food import services\n", encoding="utf-8")

    assert _scan_import_violations(tmp_path, policy) == {
        "xhs_food.state|legacy_shell->foundation|xhs_food.services"
    }


def test_private_gate_distinguishes_own_state_from_cross_object_access(
    tmp_path: Path,
) -> None:
    module = tmp_path / "xhs_food/contracts/private_fixture.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        "from xhs_food.services import _private_factory\n"
        "class Fixture:\n"
        "    def read(self, storage):\n"
        "        own = self._cache\n"
        "        hidden = getattr(storage, '_client')\n"
        "        return own, hidden, storage._pool\n",
        encoding="utf-8",
    )

    violations = _scan_private_access_violations(tmp_path)
    assert violations == {
        "xhs_food.contracts.private_fixture|<module>|xhs_food.services._private_factory",
        "xhs_food.contracts.private_fixture|Fixture.read|storage._client",
        "xhs_food.contracts.private_fixture|Fixture.read|storage._pool",
    }


def test_s3_target_layers_and_third_party_allowlists_are_explicit() -> None:
    policy = _load_policy()
    rules_by_prefix = {item["prefix"]: item for item in policy["module_layers"]}

    assert rules_by_prefix["xhs_food.gateways"] == {
        "prefix": "xhs_food.gateways",
        "layer": "gateway",
        "mode": "target",
    }
    assert rules_by_prefix["xhs_food.foundation"] == {
        "prefix": "xhs_food.foundation",
        "layer": "target_foundation",
        "mode": "target",
    }
    assert rules_by_prefix["xhs_food.composition.adapters"] == {
        "prefix": "xhs_food.composition.adapters",
        "layer": "compatibility_adapter",
        "mode": "target",
    }

    target_layers = {item["layer"] for item in policy["module_layers"] if item["mode"] == "target"}
    for layer in target_layers:
        assert "*" not in policy["allowed_internal_edges"][layer]
        assert "*" not in policy["target_third_party_allowlist"].get(layer, [])


def test_forbidden_frameworks_are_not_declared_locked_or_imported(
    tmp_path: Path,
) -> None:
    policy = _load_policy()
    required_forbidden_packages = {
        "arq",
        "celery",
        "langgraph",
        "litellm",
        "mem0",
        "mem0ai",
        "openai-agents",
        "zep",
        "zep-cloud",
        "zep-python",
    }
    required_forbidden_imports = {
        "agents",
        "arq",
        "celery",
        "langgraph",
        "litellm",
        "mem0",
        "zep",
        "zep_cloud",
        "zep_python",
    }
    forbidden_packages = {
        _normalize_distribution(name) for name in policy["forbidden_dependency_packages"]
    }
    forbidden_imports = set(policy["forbidden_import_roots"])
    assert required_forbidden_packages <= forbidden_packages
    assert required_forbidden_imports <= forbidden_imports
    declared = _declared_dependency_names(PYPROJECT_PATH)
    locked = _locked_dependency_names(UV_LOCK_PATH)

    assert not forbidden_packages & declared
    assert not forbidden_packages & locked
    assert not _scan_forbidden_imports(SRC, forbidden_imports)

    bad = tmp_path / "xhs_food/gateways/bad_runtime.py"
    bad.parent.mkdir(parents=True)
    bad.write_text("import agents\nfrom celery import Celery\n", encoding="utf-8")
    assert _scan_forbidden_imports(tmp_path, set(policy["forbidden_import_roots"])) == {
        "xhs_food.gateways.bad_runtime|forbidden-import|agents",
        "xhs_food.gateways.bad_runtime|forbidden-import|celery",
    }


def test_owner_port_and_foundation_food_boundaries_are_absolute(
    tmp_path: Path,
) -> None:
    policy = _load_policy()
    assert {
        "xhs_food.agents",
        "xhs_food.domain_packs",
        "xhs_food.orchestrator",
        "xhs_food.repositories",
    } <= set(policy["owner_port_consumer_module_prefixes"])
    assert {
        "asyncpg",
        "boto3",
        "redis",
        "sqlalchemy",
        "temporalio",
        "xhs_food.gateways",
        "xhs_food.services.postgres_storage",
        "xhs_food.services.redis_memory",
        "xhs_food.services.user_storage",
        "xhs_food.spider",
    } <= set(policy["owner_port_forbidden_import_prefixes"])
    assert {"AmapAPI", "get_amap_api", "get_user_storage_service"} <= set(
        policy["owner_port_forbidden_import_symbols"]
    )
    assert not _scan_owner_port_boundary_violations(SRC, policy)

    agent = tmp_path / "xhs_food/agents/bad_place.py"
    agent.parent.mkdir(parents=True)
    agent.write_text(
        "import redis\n"
        "from xhs_food.gateways.place import PlaceLookupToolAdapter\n"
        "from xhs_food.services import get_user_storage_service\n"
        "from xhs_food.spider.apis.amap_api import AmapAPI\n",
        encoding="utf-8",
    )
    domain_pack = tmp_path / "xhs_food/domain_packs/bad_food.py"
    domain_pack.parent.mkdir(parents=True)
    domain_pack.write_text("import boto3\n", encoding="utf-8")
    repository = tmp_path / "xhs_food/repositories/bad_cache.py"
    repository.parent.mkdir(parents=True)
    repository.write_text("import temporalio\n", encoding="utf-8")
    foundation = tmp_path / "xhs_food/foundation/bad_food.py"
    foundation.parent.mkdir(parents=True)
    foundation.write_text(
        "from xhs_food.schemas import RestaurantRecommendation\n",
        encoding="utf-8",
    )

    assert _scan_owner_port_boundary_violations(tmp_path, policy) == {
        "xhs_food.agents.bad_place|owner-port-bypass|redis",
        "xhs_food.agents.bad_place|owner-port-bypass|"
        "xhs_food.gateways.place.PlaceLookupToolAdapter",
        "xhs_food.agents.bad_place|owner-port-bypass|xhs_food.services.get_user_storage_service",
        "xhs_food.agents.bad_place|owner-port-bypass|xhs_food.spider.apis.amap_api.AmapAPI",
        "xhs_food.domain_packs.bad_food|owner-port-bypass|boto3",
        "xhs_food.repositories.bad_cache|owner-port-bypass|temporalio",
        "xhs_food.foundation.bad_food|foundation-food-dependency|"
        "xhs_food.schemas.RestaurantRecommendation",
    }


def test_target_has_one_database_pool_owner_and_no_runtime_schema_authority(
    tmp_path: Path,
) -> None:
    policy = _load_policy()
    assert policy["database_pool_factories"] == {
        "sqlalchemy.ext.asyncio.create_async_engine": "xhs_food.foundation.database"
    }
    assert {
        "asyncpg.create_pool",
        "psycopg_pool.AsyncConnectionPool",
        "psycopg_pool.ConnectionPool",
        "sqlalchemy.create_engine",
    } <= set(policy["forbidden_target_database_pool_factories"])
    assert set(policy["forbidden_target_runtime_import_roots"]) == {"alembic"}
    assert {"create_all", "drop_all"} <= set(policy["forbidden_runtime_schema_calls"])
    assert not _scan_target_authority_violations(SRC, policy)

    bad = tmp_path / "xhs_food/gateways/bad_database.py"
    bad.parent.mkdir(parents=True)
    bad.write_text(
        "import alembic\n"
        "import asyncpg\n"
        "from sqlalchemy.ext.asyncio import create_async_engine\n"
        "async def open_second_pool(connection):\n"
        "    create_async_engine('postgresql+asyncpg://fixture')\n"
        "    await asyncpg.create_pool('postgresql://fixture')\n"
        "    await connection.execute('CREATE TABLE duplicate_authority (id int)')\n",
        encoding="utf-8",
    )
    assert _scan_target_authority_violations(tmp_path, policy) == {
        "xhs_food.gateways.bad_database|database-pool-owner|"
        "sqlalchemy.ext.asyncio.create_async_engine->xhs_food.foundation.database",
        "xhs_food.gateways.bad_database|forbidden-database-pool|asyncpg.create_pool",
        "xhs_food.gateways.bad_database|runtime-ddl|CREATE TABLE",
        "xhs_food.gateways.bad_database|runtime-schema-import|alembic",
    }


def test_redis_target_surface_is_hot_state_only() -> None:
    policy = _load_policy()
    redis_module = policy["redis_hot_state_module"]
    redis_path = SRC.joinpath(*redis_module.split(".")).with_suffix(".py")
    tree = _parse_module(redis_path)

    client_methods = _class_methods(_class_definition(tree, "AsyncRedisClient"))
    assert set(client_methods) == set(policy["redis_allowed_client_methods"])
    assert _redis_key_prefixes(tree) == set(policy["redis_allowed_key_prefixes"])

    redis_set = client_methods["set"]
    assert {argument.arg for argument in redis_set.args.kwonlyargs} == {"ex", "nx"}
    state_set = _class_methods(_class_definition(tree, "RedisStateStore"))["set"]
    assert "ttl_seconds" in {argument.arg for argument in state_set.args.args}

    forbidden_tokens = set(policy["redis_forbidden_surface_tokens"])
    assert {
        "checkpoint",
        "durable",
        "lease",
        "lock",
        "redlock",
        "task",
        "workflow",
    } <= forbidden_tokens
    surface_violations: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            tokens = _identifier_tokens(node.name)
            if tokens & forbidden_tokens and not node.name.startswith("_"):
                surface_violations.add(node.name)
    assert not surface_violations

    allowed_keyword_sites = {
        keyword: set(sites)
        for keyword, sites in policy["redis_allowed_command_keyword_sites"].items()
    }
    actual_keyword_sites: dict[str, set[str]] = {
        keyword: set() for keyword in allowed_keyword_sites
    }
    for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        for method_name, method_node in _class_methods(class_node).items():
            for call in (node for node in ast.walk(method_node) if isinstance(node, ast.Call)):
                for keyword in call.keywords:
                    if keyword.arg in actual_keyword_sites:
                        actual_keyword_sites[keyword.arg].add(f"{class_node.name}.{method_name}")
    assert actual_keyword_sites == allowed_keyword_sites

    claim = _class_methods(_class_definition(tree, "RedisIdempotencyWindow"))["claim"]
    nx_values = [
        keyword.value
        for call in ast.walk(claim)
        if isinstance(call, ast.Call)
        for keyword in call.keywords
        if keyword.arg == "nx"
    ]
    assert len(nx_values) == 1
    assert isinstance(nx_values[0], ast.Constant) and nx_values[0].value is True

    redis_bound_durable_surfaces: set[str] = set()
    for module, _, target_tree in _target_modules(SRC, policy):
        for node in ast.walk(target_tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                tokens = _identifier_tokens(node.name)
                if "redis" in tokens and tokens & forbidden_tokens:
                    redis_bound_durable_surfaces.add(f"{module}|{node.name}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                tokens = _identifier_tokens(node.value)
                if "redis" in tokens and tokens & forbidden_tokens:
                    redis_bound_durable_surfaces.add(f"{module}|{node.value}")
    assert not redis_bound_durable_surfaces


def test_resolved_poi_boundary_violations_are_not_baselined() -> None:
    policy = _load_policy()
    resolved = {
        "xhs_food.agents.poi_enricher|POIEnricherAgent._get_cached_poi|storage._initialized",
        "xhs_food.agents.poi_enricher|POIEnricherAgent._get_cached_poi|storage._pool",
    }
    assert resolved.isdisjoint(policy["legacy_private_access_violations"])
    assert resolved.isdisjoint(_scan_private_access_violations(SRC))
    resolved_import = (
        "xhs_food.agents.poi_enricher|orchestrator->foundation|"
        "xhs_food.services.user_storage.generate_restaurant_hash"
    )
    assert resolved_import not in policy["legacy_import_violations"]
    assert resolved_import not in _scan_import_violations(SRC, policy)
    resolved_amap_imports = {
        "xhs_food.agents.poi_enricher|orchestrator->connector|"
        "xhs_food.spider.apis.amap_api.AmapAPI",
        "xhs_food.agents.poi_enricher|orchestrator->connector|"
        "xhs_food.spider.apis.amap_api.get_amap_api",
    }
    assert resolved_amap_imports.isdisjoint(policy["legacy_import_violations"])
    assert resolved_amap_imports.isdisjoint(_scan_import_violations(SRC, policy))
    resolved_storage_import = (
        "xhs_food.agents.poi_enricher|orchestrator->foundation|"
        "xhs_food.services.get_user_storage_service"
    )
    assert resolved_storage_import not in policy["legacy_import_violations"]
    assert resolved_storage_import not in _scan_import_violations(SRC, policy)

    poi_search = _parse_module(SRC / "xhs_food" / "agents" / "poi_search.py")
    calls = {ast.unparse(node.func) for node in ast.walk(poi_search) if isinstance(node, ast.Call)}
    assert "self._place_lookup.lookup" in calls
    assert not {call for call in calls if call.endswith(".search_poi")}

    assert policy["allowed_compatibility_imports"] == [
        "xhs_food.agents.poi_enricher|xhs_food.composition.legacy_poi.build_legacy_poi_ports"
    ]
