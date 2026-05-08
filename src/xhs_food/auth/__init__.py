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
"""

from __future__ import annotations
import hashlib
import json
import os
import random
import socket
import string
import subprocess
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

import httpx

# ---------- paths / config ----------

NODE_DIR = Path(__file__).resolve().parent / "_node"
SIGNER_JS = NODE_DIR / "signer.js"
DS_FILE = NODE_DIR / "ds.js"
SIGN_FILE = NODE_DIR / "sign.js"
NODE_PACKAGE_JSON = NODE_DIR / "package.json"
NODE_MODULES = NODE_DIR / "node_modules"


def _profile_dir() -> Path:
    """profile 文件存储目录。可通过 XHS_PROFILE_DIR 覆盖；默认项目根/.xhs_profiles."""
    env = os.environ.get("XHS_PROFILE_DIR")
    if env:
        return Path(env)
    # food_agent project root: 4 levels up from this file (src/xhs_food/auth/__init__.py)
    return Path(__file__).resolve().parents[3] / ".xhs_profiles"


EDITH = "https://edith.xiaohongshu.com"
HOME = "https://www.xiaohongshu.com"
AS_HOST = "https://as.xiaohongshu.com"
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)


# ---------- helpers ----------

def parse_cookie_str(s: str) -> dict[str, str]:
    out = {}
    for kv in s.split("; "):
        if not kv or "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def dump_cookie_str(d: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in d.items())


def gen_a1() -> str:
    """伪造浏览器指纹 a1。"""
    ts = format(int(time.time() * 1000) & 0xFFFFFFFFFFF, "x").rjust(11, "0")[:11]
    rnd = "".join(random.choices(string.ascii_lowercase + string.digits, k=20))
    suffix = "".join(random.choices(string.digits, k=6))
    return f"{ts}a{rnd}amzagag93000{suffix}"


def gen_web_id(a1: str) -> str:
    return hashlib.md5(a1.encode()).hexdigest()


# ---------- manifest / signer assets ----------

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
    extra = {}
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


# ---------- profile ----------

@dataclass
class Profile:
    name: str
    device: dict = field(default_factory=dict)
    cookies: dict = field(default_factory=dict)
    session: dict | None = None
    created_at: int = 0

    @classmethod
    def file_path(cls, name: str) -> Path:
        return _profile_dir() / f"{name}.json"

    @classmethod
    def list_all(cls) -> list[str]:
        d = _profile_dir()
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.json"))

    @classmethod
    def load_or_create(cls, name: str = "default") -> "Profile":
        path = cls.file_path(name)
        if path.exists():
            d = json.loads(path.read_text())
            return cls(
                name=d.get("name", name),
                device=d.get("device", {}),
                cookies=d.get("cookies", {}),
                session=d.get("session"),
                created_at=d.get("created_at", 0),
            )
        return cls.bootstrap(name)

    @classmethod
    def load_if_exists(cls, name: str = "default") -> "Profile | None":
        path = cls.file_path(name)
        if not path.exists():
            return None
        d = json.loads(path.read_text())
        return cls(
            name=d.get("name", name),
            device=d.get("device", {}),
            cookies=d.get("cookies", {}),
            session=d.get("session"),
            created_at=d.get("created_at", 0),
        )

    @classmethod
    def bootstrap(cls, name: str) -> "Profile":
        print(f"[auth] 创建新设备 profile '{name}' ...")
        with httpx.Client(timeout=15.0, trust_env=False) as c:
            r = c.get(HOME + "/explore", headers={"User-Agent": DEFAULT_UA, "Accept": "text/html"})
        server = {ck.name: ck.value for ck in r.cookies.jar}
        a1 = gen_a1()
        web_id = gen_web_id(a1)
        ck = {
            "xsecappid": "xhs-pc-web",
            "a1": a1, "webId": web_id,
            "webBuild": "6.8.2",
            "loadts": str(int(time.time() * 1000)),
        }
        for k in ("abRequestId", "acw_tc"):
            if server.get(k):
                ck[k] = server[k]
        p = cls(
            name=name,
            device={"a1": a1, "webId": web_id, "user_agent": DEFAULT_UA},
            cookies=ck, session=None,
            created_at=int(time.time()),
        )
        p.save()
        print(f"[auth] device a1={a1}, webId={web_id}")
        return p

    def save(self) -> None:
        d = _profile_dir()
        d.mkdir(parents=True, exist_ok=True)
        self.file_path(self.name).write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2)
        )

    def remove(self) -> None:
        path = self.file_path(self.name)
        if path.exists():
            path.unlink()

    @property
    def cookie_str(self) -> str:
        return dump_cookie_str(self.cookies)

    @property
    def user_agent(self) -> str:
        return self.device.get("user_agent", DEFAULT_UA)

    @property
    def is_logged_in(self) -> bool:
        return bool(self.session and self.session.get("web_session"))

    def merge_set_cookie(self, jar) -> None:
        for c in jar:
            self.cookies[c.name] = c.value

    def update_session(self, user_id: str, web_session: str) -> None:
        self.session = {
            "user_id": user_id,
            "web_session": web_session,
            "logged_in_at": int(time.time()),
        }


# ---------- signer client ----------

def _socket_path(profile_name: str) -> str:
    return f"/tmp/xhs-signer-{profile_name}.sock"


def _pid_path(profile_name: str) -> str:
    return f"/tmp/xhs-signer-{profile_name}.pid"


def _log_path(profile_name: str) -> str:
    return f"/tmp/xhs-signer-{profile_name}.log"


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


class SignerClient:
    def sign(self, path: str, body: object | None = None) -> dict: raise NotImplementedError
    def close(self) -> None: raise NotImplementedError


class StdioSignerClient(SignerClient):
    def __init__(self, profile: Profile) -> None:
        ensure_node_modules()
        env = os.environ.copy()
        env["XHS_COOKIE"] = profile.cookie_str
        env["XHS_UA"] = profile.user_agent
        self.proc = subprocess.Popen(
            ["node", str(SIGNER_JS)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=True, bufsize=1,
        )
        line = self.proc.stderr.readline()
        if "ready" not in line:
            err = line + (self.proc.stderr.read() or "")
            self.close()
            sys.exit(f"[auth] signer 启动失败: {err}")

    def sign(self, path: str, body=None) -> dict:
        msg = json.dumps({"id": 1, "path": path, "body": body}, ensure_ascii=False) + "\n"
        self.proc.stdin.write(msg); self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            sys.exit(f"[auth] signer 已退出: {self.proc.stderr.read() or ''}")
        resp = json.loads(line)
        if "error" in resp:
            sys.exit(f"[auth] sign error: {resp['error']}")
        return resp

    def close(self) -> None:
        try: self.proc.stdin.close()
        except Exception: pass
        try:
            self.proc.terminate(); self.proc.wait(timeout=3)
        except Exception:
            try: self.proc.kill()
            except Exception: pass


class SocketSignerClient(SignerClient):
    def __init__(self, sock_path: str) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(15.0)
        self.sock.connect(sock_path)
        self.f = self.sock.makefile("rwb", buffering=0)

    def sign(self, path: str, body=None) -> dict:
        msg = (json.dumps({"id": 1, "path": path, "body": body}, ensure_ascii=False) + "\n").encode()
        self.f.write(msg)
        line = self.f.readline()
        if not line:
            raise RuntimeError("socket signer 关闭了连接")
        resp = json.loads(line)
        if "error" in resp:
            sys.exit(f"[auth] sign error: {resp['error']}")
        return resp

    def close(self) -> None:
        try: self.f.close()
        except Exception: pass
        try: self.sock.close()
        except Exception: pass


def spawn_signer_daemon(profile: Profile) -> int:
    ensure_node_modules()
    sock_path = _socket_path(profile.name)
    pid_path = _pid_path(profile.name)
    log_path = _log_path(profile.name)
    try: Path(sock_path).unlink()
    except FileNotFoundError: pass

    env = os.environ.copy()
    env["XHS_COOKIE"] = profile.cookie_str
    env["XHS_UA"] = profile.user_agent

    log_fh = open(log_path, "ab")
    proc = subprocess.Popen(
        ["node", str(SIGNER_JS), f"--socket={sock_path}"],
        stdin=subprocess.DEVNULL, stdout=log_fh, stderr=log_fh,
        env=env, start_new_session=True, close_fds=True,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        if Path(sock_path).exists():
            Path(pid_path).write_text(str(proc.pid))
            return proc.pid
        if proc.poll() is not None:
            sys.exit(f"[auth] signer daemon 启动失败，查看 {log_path}")
        time.sleep(0.1)
    proc.kill()
    sys.exit("[auth] signer daemon 启动超时 (10s)")


def get_signer(profile: Profile, prefer_socket: bool = True) -> SignerClient:
    if prefer_socket:
        sock_path = _socket_path(profile.name)
        pid_path = _pid_path(profile.name)
        existing = None
        if Path(pid_path).exists():
            try: existing = int(Path(pid_path).read_text().strip())
            except Exception: pass
        if existing and _is_pid_alive(existing) and Path(sock_path).exists():
            try:
                return SocketSignerClient(sock_path)
            except OSError:
                pass
        spawn_signer_daemon(profile)
        try:
            return SocketSignerClient(sock_path)
        except OSError as e:
            print(f"[auth] socket 模式失败，降级 stdio: {e}")
    return StdioSignerClient(profile)


def kill_all_daemons() -> int:
    killed = 0
    for pid_file in Path("/tmp").glob("xhs-signer-*.pid"):
        try:
            pid = int(pid_file.read_text().strip())
            if _is_pid_alive(pid):
                os.kill(pid, 15); killed += 1
                print(f"  [-] killed pid {pid} ({pid_file.stem})")
        except Exception as e:
            print(f"  [!] {pid_file}: {e}")
        try: pid_file.unlink()
        except FileNotFoundError: pass
    for sock in Path("/tmp").glob("xhs-signer-*.sock"):
        try: sock.unlink()
        except FileNotFoundError: pass
    return killed


# ---------- HTTP client ----------

class XhsClient:
    def __init__(self, profile: Profile, prefer_socket: bool = True) -> None:
        self.profile = profile
        ensure_signer_assets(profile.cookie_str)
        self.signer = get_signer(profile, prefer_socket=prefer_socket)
        self.client = httpx.Client(timeout=15.0, follow_redirects=False, trust_env=False)

    def __enter__(self): return self
    def __exit__(self, *a): self.close()

    def close(self) -> None:
        self.signer.close()
        self.client.close()

    def _headers(self, sig: dict) -> dict[str, str]:
        return {
            "Cookie": self.profile.cookie_str,
            "Origin": HOME, "Referer": HOME + "/",
            "User-Agent": self.profile.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "x-s": sig["X-s"], "x-t": str(sig["X-t"]),
        }

    def get(self, path: str) -> httpx.Response:
        sig = self.signer.sign(path, None)
        r = self.client.get(EDITH + path, headers=self._headers(sig))
        self.profile.merge_set_cookie(r.cookies.jar)
        return r

    def post(self, path: str, body: dict) -> httpx.Response:
        sig = self.signer.sign(path, body)
        h = self._headers(sig); h["Content-Type"] = "application/json;charset=UTF-8"
        r = self.client.post(EDITH + path, json=body, headers=h)
        self.profile.merge_set_cookie(r.cookies.jar)
        return r


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
]
