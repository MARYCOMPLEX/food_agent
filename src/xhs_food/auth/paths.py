"""Path constants and host configuration for the xhs_food.auth package."""
from __future__ import annotations

import os
from pathlib import Path

# ---------- node runtime assets ----------

NODE_DIR: Path = Path(__file__).resolve().parent / "_node"
SIGNER_JS: Path = NODE_DIR / "signer.js"
DS_FILE: Path = NODE_DIR / "ds.js"
SIGN_FILE: Path = NODE_DIR / "sign.js"
NODE_PACKAGE_JSON: Path = NODE_DIR / "package.json"
NODE_MODULES: Path = NODE_DIR / "node_modules"


def _profile_dir() -> Path:
    """profile 文件存储目录。可通过 XHS_PROFILE_DIR 覆盖；默认项目根/.xhs_profiles."""
    env = os.environ.get("XHS_PROFILE_DIR")
    if env:
        return Path(env)
    # food_agent project root: 4 levels up from this file (src/xhs_food/auth/paths.py)
    return Path(__file__).resolve().parents[3] / ".xhs_profiles"


# ---------- API hosts / UA ----------

EDITH: str = "https://edith.xiaohongshu.com"
HOME: str = "https://www.xiaohongshu.com"
AS_HOST: str = "https://as.xiaohongshu.com"
DEFAULT_UA: str = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)


# ---------- signer daemon path helpers ----------

def _socket_path(profile_name: str) -> str:
    return f"/tmp/xhs-signer-{profile_name}.sock"


def _pid_path(profile_name: str) -> str:
    return f"/tmp/xhs-signer-{profile_name}.pid"


def _log_path(profile_name: str) -> str:
    return f"/tmp/xhs-signer-{profile_name}.log"
