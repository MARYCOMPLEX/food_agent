#!/usr/bin/env python3
"""Export deterministic OpenAPI artifacts from the FastAPI application."""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path

import yaml

from api.main import app

ROOT = Path(__file__).resolve().parents[1]
YAML_TARGET = ROOT / "contracts" / "openapi.yaml"
JSON_TARGET = ROOT / "tests" / "fixtures" / "http" / "openapi.json"


def render_artifacts() -> dict[Path, str]:
    schema = app.openapi()
    return {
        YAML_TARGET: yaml.safe_dump(schema, sort_keys=False, allow_unicode=True),
        JSON_TARGET: json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    }


def check_artifacts(artifacts: dict[Path, str]) -> int:
    drifted = False
    for path, expected in artifacts.items():
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current == expected:
            continue
        drifted = True
        relative = path.relative_to(ROOT)
        print(f"OpenAPI artifact is stale: {relative}")
        diff = difflib.unified_diff(
            current.splitlines(),
            expected.splitlines(),
            fromfile=str(relative),
            tofile=f"generated:{relative}",
            lineterm="",
        )
        for line in list(diff)[:80]:
            print(line)
    if drifted:
        print("Run: uv run python scripts/export_openapi.py")
        return 1
    print("OpenAPI artifacts match api.main:app")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail without writing when a checked-in artifact is stale",
    )
    args = parser.parse_args()
    artifacts = render_artifacts()
    if args.check:
        return check_artifacts(artifacts)
    for path, content in artifacts.items():
        path.write_text(content, encoding="utf-8")
        print(f"Wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
