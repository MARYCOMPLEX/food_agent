"""Signer client implementations (stdio + UNIX socket) and daemon control."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from .helpers import _is_pid_alive
from .node_runtime import ensure_node_modules
from .paths import (
    SIGNER_JS,
    _log_path,
    _pid_path,
    _socket_path,
)
from .profile import Profile


class SignerClient:
    """Abstract signer client. Implementations sign one API path at a time."""

    def sign(self, path: str, body: object | None = None) -> dict:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class StdioSignerClient(SignerClient):
    """Talks to a fresh `node signer.js` child over stdin/stdout."""

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

    def sign(self, path: str, body: object | None = None) -> dict:
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
    """Talks to a long-lived signer daemon over a UNIX socket."""

    def __init__(self, sock_path: str) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(15.0)
        self.sock.connect(sock_path)
        self.f = self.sock.makefile("rwb", buffering=0)

    def sign(self, path: str, body: object | None = None) -> dict:
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
    """Fork the signer node process as a background daemon. Returns its PID."""
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
    """Return the best-available signer client for the profile.

    Tries the socket daemon first; falls back to a fresh stdio child.
    """
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
    """Kill every running xhs-signer daemon. Returns the count killed."""
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
