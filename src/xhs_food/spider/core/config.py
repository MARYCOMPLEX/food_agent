"""Spider configuration — paths and rate-limit knobs."""
from __future__ import annotations

import os
from pathlib import Path

# Default data directory: ``$XHS_LOG_DB_PATH`` (file) or
# ``$XHS_DATA_DIR`` (directory) override the in-repo location.
_BASE_DIR = Path(__file__).parent.parent
_DEFAULT_DATA_DIR = _BASE_DIR / "datas"


def _resolve_log_db_path() -> Path:
    env_file = os.getenv("XHS_LOG_DB_PATH")
    if env_file:
        path = Path(env_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    data_dir = Path(os.getenv("XHS_DATA_DIR", str(_DEFAULT_DATA_DIR))).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "request_log.db"


DATA_DIR = _DEFAULT_DATA_DIR
LOG_DB_PATH = _resolve_log_db_path()


class Config:
    """Spider behavior knobs."""

    REQUEST_DELAY_MIN: float = 1.0
    REQUEST_DELAY_MAX: float = 3.0

    DEFAULT_PAGE_SIZE: int = 20
    MAX_ITEMS_PER_BATCH: int = 100

    LOG_RETENTION_DAYS: int = 7

    DEFAULT_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )


config = Config()
