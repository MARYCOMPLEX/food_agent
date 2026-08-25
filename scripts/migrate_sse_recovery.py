"""Deprecated SSE migration entrypoint delegated to Alembic.

Run ``alembic upgrade head`` directly for new deployments. This file remains
so older operators receive the same migration command without a second schema
authority.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts._alembic_compat import upgrade_head  # noqa: E402


async def migrate() -> None:
    await asyncio.to_thread(upgrade_head)


if __name__ == "__main__":
    asyncio.run(migrate())
