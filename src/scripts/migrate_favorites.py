"""Deprecated favorites migration entrypoint delegated to Alembic."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts._alembic_compat import upgrade_head  # noqa: E402


async def main() -> None:
    await asyncio.to_thread(upgrade_head)


if __name__ == "__main__":
    asyncio.run(main())
