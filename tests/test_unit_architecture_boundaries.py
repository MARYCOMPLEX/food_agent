"""Static S1 architecture gates with shrink-only legacy violation baselines."""

from __future__ import annotations

import ast
import json
import sys
import warnings
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"
POLICY_PATH = ROOT / "tests/fixtures/architecture/dependency_policy_v1.json"


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


def _import_targets(
    current_module: str, path: Path, node: ast.AST
) -> tuple[ImportTarget, ...]:
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
                target_rule = _layer_for(target.identity, rules) or _layer_for(
                    target.module, rules
                )
                if target_rule is not None:
                    allowed = allowed_edges[source_rule.layer]
                    if "*" not in allowed and target_rule.layer not in allowed:
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
                    violations.add(
                        f"{module}|{source_rule.layer}->third_party|{target.identity}"
                    )
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
            is_super = isinstance(node.value, ast.Call) and isinstance(
                node.value.func, ast.Name
            ) and node.value.func.id == "super"
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
        "import redis\n"
        "from xhs_food.services import LLMService\n",
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
        "from xhs_food.contracts import LLMProvider\n"
        "from xhs_food.services import LLMService\n",
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
        "xhs_food.contracts.private_fixture|Fixture.read|storage._pool"
    }
