# -*- coding: utf-8 -*-
"""Browser-driven login (Playwright).

Launches a real (or near-real) Chromium, lets the user scan the QR + enter
SMS in the browser, extracts the resulting cookies, writes them to the
profile, and validates the session. Bypasses the CLI 风控 by inheriting
the browser's established trust score.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict

from loguru import logger

from xhs_food.exceptions import XHSAuthError

from .paths import DEFAULT_UA, _profile_dir

# We only care about cookies on the main xhs domains
_XHS_DOMAINS = (".xiaohongshu.com", "xiaohongshu.com", ".xhs.cn", "xhs.cn")
_USER_ME_PATH = "/api/sns/web/v2/user/me"
# Cookies that we forward into the profile (best-effort superset of what the
# spider needs). Playwright returns more domain cookies than we need.
_PROFILE_COOKIE_DOMAINS = (".xiaohongshu.com", "xiaohongshu.com")


async def run_browser_login(
    profile_name: str = "default",
    timeout: int = 240,
    headless: bool = False,
) -> Dict[str, Any]:
    """Drive a Chromium login and return the resulting profile dict.

    Args:
        profile_name: profile slot to write.
        timeout: max seconds to wait for the user to finish login.
        headless: run headless (only useful for tests; humans can't scan
            QR in headless mode).

    Raises:
        XHSAuthError: on timeout, missing cookies, or failed validation.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise XHSAuthError(
            "playwright 未安装：uv add playwright && uv run playwright install chromium"
        ) from exc

    async with async_playwright() as pw:
        browser = await _launch_browser(pw, headless=headless)
        try:
            context = await browser.new_context(
                user_agent=DEFAULT_UA,
                viewport={"width": 1280, "height": 800},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            await context.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['zh-CN', 'zh', 'en']
                });
                """
            )

            page = await context.new_page()
            login_event = asyncio.Event()
            user_info: Dict[str, Any] = {}

            async def _on_response(response) -> None:
                if _USER_ME_PATH not in response.url:
                    return
                try:
                    body = await response.json()
                except Exception:
                    return
                if body.get("code") != 0:
                    return
                data = body.get("data") or {}
                if data.get("guest"):
                    return
                user_info.update(data)
                login_event.set()

            page.on("response", lambda r: asyncio.create_task(_on_response(r)))

            await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")

            print()
            print("=" * 60)
            print("  请在打开的 Chromium 窗口里扫码登录")
            print(f"  如需短信验证码，请在浏览器里输入（无需切回终端）")
            print(f"  等待登录完成 (超时 {timeout}s)…")
            print("=" * 60)
            print()

            try:
                await asyncio.wait_for(login_event.wait(), timeout=timeout)
            except asyncio.TimeoutError as exc:
                raise XHSAuthError(f"浏览器登录超时 ({timeout}s)") from exc

            cookies_raw = await context.cookies()
        finally:
            await browser.close()

    profile_dict = _build_profile_from_cookies(profile_name, cookies_raw, user_info)
    _persist_profile(profile_dict)

    # Lazy import to avoid circular: validate_session lives in session.py
    from .session import validate_session

    if not validate_session(profile_name):
        raise XHSAuthError("浏览器登录后 validate_session 仍失败；请检查 cookie 完整性")

    print(f"[OK] profile '{profile_name}' 已就绪 (user_id={user_info.get('user_id')})")
    return profile_dict


async def _launch_browser(pw, *, headless: bool):
    """Try system Chrome first (best fingerprint), fall back to bundled chromium."""
    launch_args = {
        "headless": headless,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=AutomationControlled",
        ],
    }
    try:
        return await pw.chromium.launch(channel="chrome", **launch_args)
    except Exception as exc:
        logger.debug(f"system Chrome unavailable ({exc}); falling back to bundled chromium")
        return await pw.chromium.launch(**launch_args)


def _build_profile_from_cookies(
    profile_name: str,
    cookies_raw: list[dict],
    user_info: Dict[str, Any],
) -> Dict[str, Any]:
    """Convert Playwright's cookie list to the on-disk profile format."""
    cookie_dict: Dict[str, str] = {}
    for c in cookies_raw:
        domain = c.get("domain", "")
        if not any(domain.endswith(d) or domain == d for d in _PROFILE_COOKIE_DOMAINS):
            continue
        cookie_dict[c["name"]] = c["value"]

    if not cookie_dict.get("web_session"):
        raise XHSAuthError(
            "登录完成但浏览器 cookie 里没有 web_session；可能 XHS 改了 cookie 结构"
        )
    if not cookie_dict.get("a1") or not cookie_dict.get("webId"):
        raise XHSAuthError(
            f"缺少设备指纹 cookie (a1={cookie_dict.get('a1')!r}, "
            f"webId={cookie_dict.get('webId')!r})"
        )

    now = int(time.time())
    return {
        "name": profile_name,
        "device": {
            "a1": cookie_dict["a1"],
            "webId": cookie_dict["webId"],
            "user_agent": DEFAULT_UA,
        },
        "cookies": cookie_dict,
        "session": {
            "user_id": user_info.get("user_id", ""),
            "web_session": cookie_dict["web_session"],
            "logged_in_at": now,
        },
        "created_at": now,
    }


def _persist_profile(profile_dict: Dict[str, Any]) -> None:
    dest = _profile_dir() / f"{profile_dict['name']}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(profile_dict, ensure_ascii=False, indent=2))
    print(
        f"[+] 写入 {dest} "
        f"({len(profile_dict['cookies'])} cookies, "
        f"user_id={profile_dict['session']['user_id']})"
    )
