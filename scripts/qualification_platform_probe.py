"""Record a non-blocking host/runtime compatibility probe.

Probe success is compatibility evidence only. The script deliberately reports
the production support matrix as unchanged, including when the host does not
match the requested macOS arm64 target.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any


def probe(*, expected_os: str, expected_arch: str) -> dict[str, Any]:
    actual_os = platform.system()
    actual_arch = platform.machine().lower()
    expected_arch_normalized = expected_arch.lower()
    runtime_supported = sys.version_info[:2] == (3, 12)
    host_matches = actual_os == expected_os and actual_arch == expected_arch_normalized
    status = "pass" if runtime_supported and host_matches else "probe_mismatch"
    return {
        "schemaVersion": "platform-probe/v1",
        "status": status,
        "host": {
            "os": actual_os,
            "architecture": actual_arch,
            "python": platform.python_version(),
        },
        "expected": {
            "os": expected_os,
            "architecture": expected_arch_normalized,
            "python": "3.12.x",
        },
        "checks": {
            "python312": runtime_supported,
            "hostMatch": host_matches,
        },
        "productionSupportMatrixChanged": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-os", default="Darwin")
    parser.add_argument("--expected-arch", default="arm64")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = probe(expected_os=args.expected_os, expected_arch=args.expected_arch)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output is not None:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())

