# -*- coding: utf-8 -*-
"""Session validation + interactive QR re-login.

Public API:
- :func:`validate_session` — non-destructive check (one HTTP call to /user/me)
- :func:`ensure_logged_in` — validate, and if invalid run an interactive QR
  flow until the session is good (or the user aborts).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from xhs_food.exceptions import XHSAuthError

from .client import XhsClient
from .profile import Profile
from .paths import _profile_dir  # type: ignore  # used for QR png path


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_session(profile_name: str = "default") -> bool:
    """Return True iff the profile has a valid logged-in session.

    Validation calls ``/api/sns/web/v2/user/me``. A response with ``code == 0``
    and ``data.guest`` falsy is considered valid; everything else is invalid.
    Any HTTP / signer error is treated as invalid.
    """
    profile = Profile.load_or_create(profile_name)
    if not profile.cookies.get("web_session"):
        logger.debug(f"profile '{profile_name}' has no web_session cookie")
        return False

    try:
        with XhsClient(profile, prefer_socket=False) as cli:
            response = cli.get("/api/sns/web/v2/user/me")
    except Exception as exc:
        logger.warning(f"session validate request failed: {exc}")
        return False

    try:
        payload = response.json()
    except json.JSONDecodeError:
        logger.warning(f"/user/me returned non-JSON: {response.text[:200]}")
        return False

    if payload.get("code") != 0:
        logger.info(
            f"session invalid for '{profile_name}': "
            f"code={payload.get('code')} msg={payload.get('msg')}"
        )
        return False

    data = payload.get("data") or {}
    if data.get("guest"):
        logger.info(f"session invalid for '{profile_name}': server marks guest")
        return False

    user_id = data.get("user_id") or data.get("red_id")
    logger.info(f"session valid for '{profile_name}' (user_id={user_id})")
    return True


# ---------------------------------------------------------------------------
# Interactive QR flow
# ---------------------------------------------------------------------------


def _render_qr(url: str, png_path: Path) -> None:
    """Print the QR code to the terminal and save a PNG side copy."""
    try:
        import qrcode
    except ImportError:
        print("[!] 缺少 qrcode 库：uv pip install 'qrcode[pil]'")
        print(f"    手工渲染 URL: {url}")
        return
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr.make_image(fill_color="black", back_color="white").save(png_path)
    print(f"[+] PNG 已保存: {png_path}")
    print("[+] 终端二维码（直接扫）:\n")
    qr.print_ascii(invert=True)
    print()


# Cookies that must be wiped before issuing a fresh QR — otherwise XHS sees
# a logged-in / mid-login session and may return a stale QR or skip the real
# session-issuance step entirely.
_STALE_AUTH_COOKIES = (
    "web_session",
    "customer-sso-sid",
    "customerClientId",
    "x-user-id-creator.xiaohongshu.com",
    "x-user-id-edith.xiaohongshu.com",
    "unread",
    "sec_poison_id",
)


def _reset_for_new_qr(profile: Profile) -> None:
    """Drop session-bearing cookies in-memory before requesting a new QR.

    Device identity (``a1``, ``webId``) is preserved so we don't look like a
    brand-new browser, but everything that says "logged in" is cleared.
    """
    for key in _STALE_AUTH_COOKIES:
        profile.cookies.pop(key, None)
    profile.session = None


def run_qr_flow(
    profile_name: str = "default",
    poll_timeout: int = 120,
    fresh_device: bool = False,
) -> Profile:
    """Run the QR login flow and return the updated profile.

    Args:
        profile_name: profile slot.
        poll_timeout: seconds to wait for the user to scan.
        fresh_device: regenerate a1 / webId from scratch (forces XHS to treat
            this as a brand-new browser session).

    Raises :class:`XHSAuthError` on timeout or fatal API error. The caller
    is responsible for re-validating via :func:`validate_session` because
    XHS may return ``codeStatus=2`` (扫码成功) without immediately issuing a
    fully authenticated session.
    """
    if fresh_device:
        Profile.file_path(profile_name).unlink(missing_ok=True)

    profile = Profile.load_or_create(profile_name)
    _reset_for_new_qr(profile)
    deadline = time.time() + poll_timeout

    with XhsClient(profile, prefer_socket=False) as cli:
        r = cli.post("/api/sns/web/v1/login/qrcode/create", {"qr_type": 1})
        body = r.json()
        if not body.get("success"):
            raise XHSAuthError(f"qrcode/create 失败: {body}")
        data = body["data"]
        qr_id, qr_code, url = data["qr_id"], data["code"], data["url"]

        png_path = _profile_dir() / f"qr-{profile_name}.png"
        print(f"\n二维码 URL: {url}")
        _render_qr(url, png_path)
        print("等待扫描... (Ctrl+C 退出)")

        last_status = None
        while True:
            if time.time() > deadline:
                raise XHSAuthError(f"QR 等待超时 ({poll_timeout}s)")

            rr = cli.post("/api/qrcode/userinfo", {"qrId": qr_id, "code": qr_code})
            poll = rr.json()
            cs = (poll.get("data") or {}).get("codeStatus")
            if cs != last_status:
                print(f"  codeStatus={cs}")
                last_status = cs
            if cs == 2:
                _complete_login_after_scan(cli, profile, qr_id, qr_code)
                profile.save()
                print("\n[OK] 扫码完成，profile 已写回")
                return profile
            if cs == 3:
                raise XHSAuthError("二维码已过期")
            time.sleep(2)


_VERIFY_BIZ = 471  # XHS sets this to the HTTP status that triggered the SMS flow

# XHS error codes that mean "your account is risk-flagged — stop trying"
_RISK_CODES = frozenset({40000, 40001, -103, -10403})


class XHSRiskControlError(XHSAuthError):
    """Raised when XHS refuses login due to risk-control (40000 etc).

    Retrying makes risk-control *worse*; surface this to the caller so the
    retry loop in :func:`ensure_logged_in` stops immediately.
    """


def _header_ci(headers, *names: str) -> str | None:
    """Case-insensitive header lookup."""
    for name in names:
        for k, v in headers.items():
            if k.lower() == name.lower():
                return v
    return None


def _complete_login_after_scan(
    cli: XhsClient,
    profile: Profile,
    qr_id: str,
    qr_code: str,
) -> None:
    """Finalize the QR login: status → optional SMS verify → activate session.

    Reverse-engineered from the official xiaohongshu.com flow:

    1. ``GET /api/sns/web/v1/login/qrcode/status?qr_id=&code=`` —
       confirms server-side that the scan is acknowledged.

       - HTTP 200 + ``data.login_info`` → success, web_session set via
         ``Set-Cookie`` and ``login_info`` carries ``{user_id, session}``.
       - HTTP 471 with response headers ``VerifyType`` + ``VerifyUuid`` →
         风控 SMS path; see :func:`_run_sms_verification` and retry.
    2. (Older / non-风控 path) ``POST /api/sns/web/v1/login/activate`` with
       empty body — also valid if status returns 200 but without
       ``login_info`` (older XHS deployments).
    """
    status_path = f"/api/sns/web/v1/login/qrcode/status?qr_id={qr_id}&code={qr_code}"
    status_resp = cli.get(status_path)

    if status_resp.status_code == 471:
        verify_type = _header_ci(status_resp.headers, "verifytype")
        verify_uuid = _header_ci(status_resp.headers, "verifyuuid")
        if not verify_uuid:
            raise XHSAuthError(
                f"qrcode/status 471 但缺 VerifyUuid 头: {dict(status_resp.headers)}"
            )
        print(f"\n[风控] 需短信验证 (VerifyType={verify_type})")
        _run_sms_verification(cli, verify_uuid, verify_type or "120")
        # retry the status call — should now succeed
        status_resp = cli.get(status_path)

    if status_resp.status_code != 200:
        raise XHSAuthError(
            f"qrcode/status 异常: HTTP {status_resp.status_code} "
            f"body={status_resp.text[:200]}"
        )

    payload = status_resp.json()
    login_info = (payload.get("data") or {}).get("login_info") or {}

    if login_info.get("user_id") and login_info.get("session"):
        # New protocol: qrcode/status already produced the session
        profile.update_session(
            user_id=login_info["user_id"],
            web_session=login_info["session"],
        )
        return

    # Legacy fallback: still need to explicitly activate
    activate_resp = cli.post("/api/sns/web/v1/login/activate", {})
    activate_payload = activate_resp.json()
    if not activate_payload.get("success") or activate_payload.get("code") != 0:
        raise XHSAuthError(f"login/activate 失败: {activate_payload}")
    data = activate_payload.get("data") or {}
    user_id = data.get("user_id")
    session_token = data.get("session")
    if not user_id or not session_token:
        raise XHSAuthError(f"login/activate 响应缺字段: {activate_payload}")
    profile.update_session(user_id=user_id, web_session=session_token)


def _run_sms_verification(
    cli: XhsClient,
    verify_uuid: str,
    verify_type: str,
) -> None:
    """Drive the SMS challenge flow: init → send → prompt user → check.

    Endpoints reverse-engineered from xiaohongshu.com:
    - POST /api/redcaptcha/v2/vc/init  → {receiver}  (masked phone number)
    - POST /api/redcaptcha/v2/vc/send  → {rid, expireSec}
    - POST /api/redcaptcha/v2/vc/check → {code: 0} on success
    """
    body = {
        "verifyUuid": verify_uuid,
        "verifyType": str(verify_type),
        "verifyBiz": _VERIFY_BIZ,
        "sourceSite": "",
    }

    init_resp = cli.post("/api/redcaptcha/v2/vc/init", body)
    _raise_for_payload(init_resp.json(), "redcaptcha/vc/init")
    receiver = (init_resp.json().get("data") or {}).get("receiver", "")
    print(f"[+] 短信将发送至 {receiver or '(空)'}")

    send_payload = cli.post("/api/redcaptcha/v2/vc/send", body).json()
    _raise_for_payload(send_payload, "redcaptcha/vc/send")
    rid = (send_payload.get("data") or {}).get("rid")
    expire_sec = (send_payload.get("data") or {}).get("expireSec", 60)
    if not rid:
        raise XHSAuthError(f"vc/send 响应缺 rid: {send_payload}")
    print(f"[+] 短信已发送 (有效 {expire_sec}s)，rid={rid[:8]}…")

    try:
        code = input(f"请输入短信验证码 (6 位数字): ").strip()
    except EOFError as exc:
        raise XHSAuthError("无法读取标准输入；非交互环境请改用浏览器登录") from exc
    if not code or not code.isdigit() or len(code) not in (4, 6):
        raise XHSAuthError(f"验证码格式异常: {code!r}")

    check_payload = cli.post(
        "/api/redcaptcha/v2/vc/check",
        {**body, "rid": rid, "code": code, "checkCount": 0},
    ).json()
    _raise_for_payload(check_payload, "redcaptcha/vc/check")
    print("[OK] 短信验证通过")


def _raise_for_payload(payload: dict, endpoint: str) -> None:
    """Treat XHS ``code != 0`` as failure even when ``success`` is true.

    Distinguishes risk-control responses (40000 family) from generic errors
    so the outer retry loop can short-circuit.
    """
    code = payload.get("code")
    msg = payload.get("msg") or payload.get("message") or ""
    if code == 0 and payload.get("success"):
        return
    if code in _RISK_CODES:
        raise XHSRiskControlError(
            f"{endpoint} 触发风控 (code={code}): {msg}. "
            "请等待数小时或改用浏览器导出 cookie。"
        )
    raise XHSAuthError(f"{endpoint} 失败 (code={code}): {msg}")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


# Per-account / per-IP risk control on XHS roughly clears in 1-3 hours.
_RISK_BACKOFF_SECONDS = 15  # between retries, *not* a real cooldown


def ensure_logged_in(
    profile_name: str = "default",
    force_scan: bool = False,
    fresh_device: bool = False,
    max_attempts: int = 2,
) -> Profile:
    """Guarantee a valid logged-in profile, prompting the user as needed.

    Args:
        profile_name: which profile slot to validate / refresh.
        force_scan: skip the initial validation and always require a fresh
            scan. Use this for "every-execution-scans" workflows.
        fresh_device: regenerate device identity (a1/webId) on each scan so
            XHS sees a brand-new browser. Use when scans keep producing
            stale-looking QR codes.
        max_attempts: how many scan retries before giving up.

    Raises:
        XHSAuthError: if all attempts fail.
    """
    if not force_scan and validate_session(profile_name):
        return Profile.load_or_create(profile_name)

    print(f"\n=== XHS 登录态无效，需要扫码 (profile={profile_name}) ===")
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            print(f"\n第 {attempt}/{max_attempts} 次尝试 ({_RISK_BACKOFF_SECONDS}s 后开始)…")
            time.sleep(_RISK_BACKOFF_SECONDS)
        try:
            # Only first attempt honors fresh_device; subsequent retries reuse
            # the same a1/webId so we don't look like a 攻击者 to XHS.
            run_qr_flow(profile_name, fresh_device=fresh_device and attempt == 1)
        except XHSRiskControlError as exc:
            raise XHSAuthError(
                f"账号已被风控，无法继续扫码登录: {exc}\n"
                "解决方案（任选其一）：\n"
                "  1) 等 1-3 小时让风控解除再跑 --force-scan (不要带 --fresh-device)\n"
                "  2) 浏览器登录 xiaohongshu.com → DevTools 复制完整 cookie，\n"
                "     然后运行: uv run python -m xhs_food.auth import-cookie '<cookie 串>'"
            ) from exc
        except XHSAuthError as exc:
            logger.warning(f"QR flow attempt {attempt} failed: {exc}")
            continue
        except KeyboardInterrupt:
            sys.exit("\n[!] 用户取消")

        if validate_session(profile_name):
            return Profile.load_or_create(profile_name)

        print(
            "[!] 扫码完成但服务端仍判 guest — XHS 可能还在补 cookie，"
            "稍候几秒再次校验…"
        )
        time.sleep(3)
        if validate_session(profile_name):
            return Profile.load_or_create(profile_name)

    raise XHSAuthError(
        f"扫码 {max_attempts} 次后仍无法激活 session；"
        "请用浏览器登录 xiaohongshu.com，从 DevTools 复制完整 cookie 到 .env 的 XHS_COOKIES"
    )
