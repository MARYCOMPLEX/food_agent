"""Node.js subprocess support for the signer (install + asset download)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx

from .paths import (
    AS_HOST,
    DEFAULT_UA,
    DS_FILE,
    HOME,
    NODE_DIR,
    NODE_MODULES,
    SIGN_FILE,
)


def fetch_manifest(cookie_str: str) -> dict[str, str]:
    """调用 /api/sec/v1/sbtsource (无需签名) 拿 ds/sign 的 CDN URL."""
    headers = {
        "Cookie": cookie_str,
        "Origin": HOME, "Referer": HOME + "/",
        "User-Agent": DEFAULT_UA,
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json",
    }
    body = {"callFrom": "web", "appId": "xhs-pc-web"}
    with httpx.Client(timeout=15.0, trust_env=False) as c:
        r = c.post(f"{AS_HOST}/api/sec/v1/sbtsource", json=body, headers=headers)
    d = r.json().get("data", {})
    extra: dict = {}
    try:
        extra = json.loads(d.get("extraInfo", "{}"))
    except Exception:
        pass
    return {
        "ds": extra.get("dsUrl") or "",
        "sign": d.get("signUrl") or "",
        "fp": d.get("url") or "",
        "xhsToken": d.get("xhsTokenUrl") or "",
    }


def _download(url: str, dst: Path) -> int:
    with httpx.Client(timeout=30.0, trust_env=False) as c:
        r = c.get(url, headers={"User-Agent": DEFAULT_UA})
    r.raise_for_status()
    dst.write_bytes(r.content)
    return len(r.content)


def ensure_node_modules() -> None:
    """Install jsdom into the bundled `_node` dir if missing."""
    if NODE_MODULES.exists() and (NODE_MODULES / "jsdom").exists():
        return
    print(f"[auth] 安装 jsdom 到 {NODE_DIR} ...")
    npm = subprocess.run(
        ["npm", "install"], cwd=str(NODE_DIR),
        capture_output=True, text=True,
    )
    if npm.returncode != 0:
        sys.exit(f"[auth] npm install 失败:\n{npm.stderr}")
    print("[auth] jsdom 安装完成")


def ensure_signer_assets(cookie_str: str, force: bool = False) -> None:
    """Download `ds.js` / `sign.js` from the manifest if missing or forced."""
    if not force and DS_FILE.exists() and SIGN_FILE.exists():
        return
    print("[auth] 拉取 sbtsource manifest...")
    m = fetch_manifest(cookie_str)
    if not m["ds"] or not m["sign"]:
        sys.exit(f"[auth] manifest 不完整: {m}")
    print(f"[auth] 下载 ds.js  <- {m['ds']}")
    print(f"        {_download(m['ds'], DS_FILE)} bytes")
    print(f"[auth] 下载 sign.js <- {m['sign']}")
    print(f"        {_download(m['sign'], SIGN_FILE)} bytes")
