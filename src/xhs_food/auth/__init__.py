"""
xhs_food.auth — 小红书 Web 设备 / 登陆态管理模块

工作原理：
  - Profile 持久化 a1/webId/cookies/session（profiles/<name>.json）
  - Node 子进程 signer.js + jsdom 加载 ds.js / sign.js 提供 _webmsxyw 签名
  - Python httpx 调小红书 API，登陆成功后写回 profile

集成点：
  - get_cookies(profile="default") -> str | None  供 spider 取登陆态 cookie
  - get_active_profile()          -> Profile | None
  - python -m xhs_food.auth qr   等子命令 (CLI)

This module's public surface is preserved across the package split:
    from xhs_food.auth import Profile, XhsClient, get_active_profile, get_cookies
all still work.
"""
from __future__ import annotations

from .client import XhsClient
from .helpers import (
    _is_pid_alive,
    dump_cookie_str,
    gen_a1,
    gen_web_id,
    parse_cookie_str,
)
from .node_runtime import ensure_node_modules, ensure_signer_assets, fetch_manifest
from .paths import (
    AS_HOST,
    DEFAULT_UA,
    DS_FILE,
    EDITH,
    HOME,
    NODE_DIR,
    NODE_MODULES,
    NODE_PACKAGE_JSON,
    SIGNER_JS,
    SIGN_FILE,
    _log_path,
    _pid_path,
    _profile_dir,
    _socket_path,
)
from .browser_login import run_browser_login
from .profile import Profile
from .session import ensure_logged_in, run_qr_flow, validate_session
from .signer import (
    SignerClient,
    SocketSignerClient,
    StdioSignerClient,
    get_signer,
    kill_all_daemons,
    spawn_signer_daemon,
)


# ---------- public integration helpers ----------


def get_active_profile(name: str = "default") -> Profile | None:
    """Return profile if it exists, else None. Does NOT bootstrap."""
    return Profile.load_if_exists(name)


def get_cookies(profile_name: str = "default") -> str | None:
    """Return cookie string for spider/business use, or None if not logged in.

    优先级（在 spider 的 load_env 里使用）：
        1. XHS_COOKIES env (老兼容)
        2. 这个函数返回的 profile cookie
    """
    p = Profile.load_if_exists(profile_name)
    return p.cookie_str if (p and p.is_logged_in) else None


__all__ = [
    "Profile", "XhsClient",
    "get_active_profile", "get_cookies",
    "ensure_signer_assets", "fetch_manifest",
    "kill_all_daemons", "spawn_signer_daemon",
    "DEFAULT_UA",
    # session lifecycle
    "ensure_logged_in", "validate_session", "run_qr_flow",
    "run_browser_login",
]
