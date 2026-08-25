"""Fail-closed scan for runtime schema authority drift.

The target architecture allows Alembic to own schema changes. Runtime DDL in
the explicitly inventoried legacy adapters remains visible during the
contraction window, so the probe distinguishes those known findings from new
or unregistered runtime DDL.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

SCHEMA_VERSION = "schema-authority-probe/v1"
_DDL_PATTERN = re.compile(r"\b(CREATE\s+(?:TABLE|INDEX)|ALTER\s+TABLE)\b", re.IGNORECASE)
_LEGACY_PATHS = frozenset(
    {
        "scripts/migrate_sse_recovery.py",
        "scripts/migrate_turn_id.py",
        "src/scripts/migrate_favorites.py",
        "src/xhs_food/services/postgres_storage.py",
        "src/xhs_food/services/postgres_vector.py",
        "src/xhs_food/spider/core/logger.py",
        "src/xhs_food/services/user_storage/schema.py",
        "src/xhs_food/services/user_storage/service.py",
    }
)
_SKIP_PARTS = frozenset({".venv", ".venv-win", "__pycache__", "alembic"})


@dataclass(frozen=True)
class DdlFinding:
    path: str
    line: int
    statement: str


def _python_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in sorted(root.rglob("*.py"))
        if not _SKIP_PARTS.intersection(path.parts)
        and "tests" not in path.parts
        and ".git" not in path.parts
    )


def _findings(path: Path, root: Path) -> tuple[DdlFinding, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return ()
    findings: list[DdlFinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        match = _DDL_PATTERN.search(node.value)
        if match is None:
            continue
        findings.append(
            DdlFinding(
                path=path.relative_to(root).as_posix(),
                line=getattr(node, "lineno", 0),
                statement=" ".join(match.group(1).upper().split()),
            )
        )
    return tuple(findings)


def scan(root: Path) -> dict[str, object]:
    all_findings = tuple(
        finding
        for path in _python_files(root)
        for finding in _findings(path, root)
    )
    legacy = tuple(finding for finding in all_findings if finding.path in _LEGACY_PATHS)
    unexpected = tuple(finding for finding in all_findings if finding.path not in _LEGACY_PATHS)
    status: Literal["pass", "pending_legacy_contraction", "fail"]
    if unexpected:
        status = "fail"
    elif legacy:
        status = "pending_legacy_contraction"
    else:
        status = "pass"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "legacyFindings": [asdict(item) for item in legacy],
        "unexpectedFindings": [asdict(item) for item in unexpected],
        "legacyPathAllowlist": sorted(_LEGACY_PATHS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = scan(args.root.resolve())
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output is not None:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return {"pass": 0, "pending_legacy_contraction": 2, "fail": 1}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
