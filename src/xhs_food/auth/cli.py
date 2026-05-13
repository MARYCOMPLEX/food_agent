"""xhs_food.auth CLI — qr / login / whoami / profiles / serve / stop / update / reset."""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import (
    Profile, XhsClient,
    ensure_signer_assets, kill_all_daemons, spawn_signer_daemon,
    _is_pid_alive, _socket_path, _pid_path, _log_path,
)


def cmd_whoami(profile: Profile, prefer_socket: bool) -> None:
    with XhsClient(profile, prefer_socket) as cli:
        r = cli.get("/api/sns/web/v2/user/me")
        print(f"HTTP {r.status_code}")
        try: print(json.dumps(r.json(), ensure_ascii=False, indent=2))
        except Exception: print(r.text[:1000])
        profile.save()


def cmd_login(profile: Profile, phone: str, prefer_socket: bool) -> None:
    zone = "86"
    with XhsClient(profile, prefer_socket) as cli:
        path1 = f"/api/sns/web/v2/login/send_code?phone={phone}&zone={zone}&type=login"
        r1 = cli.get(path1)
        print(f"[1/3] send_code -> {r1.status_code}: {r1.text[:200]}")
        if not r1.json().get("success"):
            sys.exit("[!] 发送验证码失败")

        code = input("收到的 6 位验证码: ").strip()
        path2 = f"/api/sns/web/v1/login/check_code?phone={phone}&zone={zone}&code={code}"
        r2 = cli.get(path2)
        print(f"[2/3] check_code -> {r2.status_code}: {r2.text[:300]}")
        d2 = r2.json()
        if not d2.get("success"):
            sys.exit("[!] 校验码失败")
        mobile_token = d2["data"]["mobile_token"]

        body3 = {"mobile_token": mobile_token, "zone": zone, "phone": phone}
        r3 = cli.post("/api/sns/web/v2/login/code", body3)
        print(f"[3/3] login/code -> {r3.status_code}: {r3.text[:400]}")
        d3 = r3.json()
        if not d3.get("success"):
            sys.exit("[!] 登陆失败")

        profile.update_session(d3["data"]["user_id"], d3["data"]["session"])
        profile.save()
        print(f"\n[OK] user_id={profile.session['user_id']}  web_session={profile.session['web_session']}")
        print(f"[+] profile '{profile.name}' 已写回")

        r4 = cli.get("/api/sns/web/v2/user/me")
        print(f"\n[verify] /user/me -> {r4.status_code}: {r4.text[:400]}")


def render_qr(url: str, png_path: Path) -> None:
    try:
        import qrcode
    except ImportError:
        print("[!] 缺少 qrcode 库，运行: pip install 'qrcode[pil]'")
        print(f"    或手工渲染此 URL: {url}")
        return
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(url); qr.make(fit=True)
    qr.make_image(fill_color="black", back_color="white").save(png_path)
    print(f"[+] PNG 已保存: {png_path}")
    print("[+] 终端二维码（直接扫）:\n")
    qr.print_ascii(invert=True)
    print()


def cmd_qr(profile: Profile, prefer_socket: bool) -> None:
    with XhsClient(profile, prefer_socket) as cli:
        r = cli.post("/api/sns/web/v1/login/qrcode/create", {"qr_type": 1})
        d = r.json()
        if not d.get("success"):
            sys.exit(f"[!] qrcode/create 失败: {r.text}")
        qr_id = d["data"]["qr_id"]
        qr_code = d["data"]["code"]
        url = d["data"]["url"]
        print(f"\n二维码 URL: {url}")
        png = profile.file_path(profile.name).parent / f"qr-{profile.name}.png"
        render_qr(url, png)
        print("等待扫描... (Ctrl+C 退出)")
        last = None
        while True:
            rr = cli.post("/api/qrcode/userinfo", {"qrId": qr_id, "code": qr_code})
            dd = rr.json()
            cs = (dd.get("data") or {}).get("codeStatus")
            if cs != last:
                print(f"  状态变化: codeStatus={cs}")
                last = cs
            if cs == 2:
                print(f"\n[OK] 扫码登陆成功！")
                print(json.dumps(dd, ensure_ascii=False, indent=2))
                profile.save()
                break
            if cs == 3:
                sys.exit("[!] 二维码已过期")
            time.sleep(2)


def cmd_reset(profile: Profile) -> None:
    profile.remove()
    print(f"[-] 删除 {profile.file_path(profile.name)}")
    pid_file = Path(_pid_path(profile.name))
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            if _is_pid_alive(pid):
                os.kill(pid, 15)
                print(f"[-] killed daemon pid {pid}")
        except Exception:
            pass
        try: pid_file.unlink()
        except FileNotFoundError: pass
    sock = Path(_socket_path(profile.name))
    if sock.exists():
        try: sock.unlink()
        except FileNotFoundError: pass


def cmd_update(profile: Profile) -> None:
    ensure_signer_assets(profile.cookie_str, force=True)
    print("[OK] 签名脚本已更新；如有 daemon 请先 stop")


def cmd_import_cookie(profile_name: str, cookie_str: str) -> None:
    """Import a raw cookie string from a browser into the profile.

    Use this when XHS risk-control blocks SMS-based QR login: log in via a
    real browser, copy cookies from DevTools, run::

        python -m xhs_food.auth import-cookie '<cookie 串>'

    The command parses the cookie, derives ``a1`` / ``webId`` / ``web_session``,
    writes a fresh profile, then validates the session via ``/user/me``.
    """
    import json as _json
    import time as _time

    from xhs_food.auth.helpers import DEFAULT_UA, parse_cookie_str
    from xhs_food.auth.paths import _profile_dir
    from xhs_food.auth.session import validate_session

    cookie_str = cookie_str.strip().strip('"').strip("'").rstrip(";").strip()
    if not cookie_str:
        sys.exit("[!] cookie 串为空")
    cookies = parse_cookie_str(cookie_str)

    required = ("a1", "webId", "web_session")
    missing = [k for k in required if not cookies.get(k)]
    if missing:
        sys.exit(f"[!] cookie 串缺少关键字段: {missing}；请确认从已登录的浏览器复制")

    profile_dict = {
        "name": profile_name,
        "device": {
            "a1": cookies["a1"],
            "webId": cookies["webId"],
            "user_agent": DEFAULT_UA,
        },
        "cookies": cookies,
        "session": {
            "user_id": "",  # filled in on first /user/me call (optional)
            "web_session": cookies["web_session"],
            "logged_in_at": int(_time.time()),
        },
        "created_at": int(_time.time()),
    }

    dest = _profile_dir() / f"{profile_name}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_json.dumps(profile_dict, ensure_ascii=False, indent=2))
    print(f"[+] 已写入 {dest}（{len(cookies)} 个 cookie）")

    print("[*] 验证 session…")
    if validate_session(profile_name):
        print(f"[OK] session 可用，profile '{profile_name}' 已就绪")
    else:
        sys.exit(f"[!] session 校验失败；请重新从浏览器复制最新 cookie")


def cmd_profiles() -> None:
    names = Profile.list_all()
    if not names:
        print("(no profiles)")
        return
    for name in names:
        p = Profile.load_or_create(name)
        sock_alive = "✓" if Path(_socket_path(name)).exists() else "·"
        if p.is_logged_in:
            uid = p.session.get("user_id", "?")
            ago = int(time.time()) - p.session.get("logged_in_at", 0)
            sess = f"已登陆 user_id={uid} ({ago}s ago)"
        else:
            sess = "未登陆"
        print(f"  [{sock_alive}] {name:20} a1={p.device.get('a1','?')[:30]}…  {sess}")


def cmd_stop() -> None:
    n = kill_all_daemons()
    print(f"[OK] 终止了 {n} 个守护进程")


def cmd_serve(profile: Profile) -> None:
    sock_path = _socket_path(profile.name)
    if Path(sock_path).exists():
        print(f"[!] {sock_path} 已存在；先 stop")
        return
    pid = spawn_signer_daemon(profile)
    print(f"[OK] daemon pid={pid} listening at {sock_path}")
    print(f"     log: {_log_path(profile.name)}")


def main():
    parser = argparse.ArgumentParser(
        prog="python -m xhs_food.auth",
        description="小红书设备身份与登陆态管理",
    )
    parser.add_argument("--profile", default="default", help="设备 profile 名（默认 default）")
    parser.add_argument("--no-socket", action="store_true", help="不用守护进程")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("whoami")
    sp = sub.add_parser("login"); sp.add_argument("phone")
    sub.add_parser("qr")
    sub.add_parser("update")
    sub.add_parser("reset")
    sub.add_parser("serve")
    sub.add_parser("stop")
    sub.add_parser("profiles")
    ic = sub.add_parser("import-cookie", help="把浏览器复制的 cookie 串写入 profile")
    ic.add_argument("cookie", help="cookie 字符串（来自 DevTools 或 document.cookie）")
    bl = sub.add_parser("browser-login", help="开 headed Chromium 扫码登录（绕过 CLI 风控）")
    bl.add_argument("--headless", action="store_true", help="（调试用）无头模式，无法扫码")
    bl.add_argument("--timeout", type=int, default=240, help="登录超时秒数（默认 240）")

    args = parser.parse_args()

    if args.cmd == "stop":
        cmd_stop(); return
    if args.cmd == "profiles":
        cmd_profiles(); return
    if args.cmd == "import-cookie":
        cmd_import_cookie(args.profile, args.cookie); return
    if args.cmd == "browser-login":
        import asyncio as _asyncio
        from xhs_food.auth.browser_login import run_browser_login
        try:
            _asyncio.run(run_browser_login(
                profile_name=args.profile,
                timeout=args.timeout,
                headless=args.headless,
            ))
        except Exception as exc:
            sys.exit(f"[!] 浏览器登录失败: {exc}")
        return

    profile = Profile.load_or_create(args.profile)
    prefer_socket = not args.no_socket

    if args.cmd == "whoami": cmd_whoami(profile, prefer_socket)
    elif args.cmd == "login": cmd_login(profile, args.phone, prefer_socket)
    elif args.cmd == "qr": cmd_qr(profile, prefer_socket)
    elif args.cmd == "update": cmd_update(profile)
    elif args.cmd == "reset": cmd_reset(profile)
    elif args.cmd == "serve": cmd_serve(profile)
