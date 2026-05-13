"""Small cookie / fingerprint helpers for xhs_food.auth."""
from __future__ import annotations

import hashlib
import os
import random
import string
import time


def parse_cookie_str(s: str) -> dict[str, str]:
    """Parse a `Cookie: a=b; c=d` style string into a dict."""
    out: dict[str, str] = {}
    for kv in s.split("; "):
        if not kv or "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def dump_cookie_str(d: dict[str, str]) -> str:
    """Inverse of :func:`parse_cookie_str`."""
    return "; ".join(f"{k}={v}" for k, v in d.items())


def gen_a1() -> str:
    """伪造浏览器指纹 a1。"""
    ts = format(int(time.time() * 1000) & 0xFFFFFFFFFFF, "x").rjust(11, "0")[:11]
    rnd = "".join(random.choices(string.ascii_lowercase + string.digits, k=20))
    suffix = "".join(random.choices(string.digits, k=6))
    return f"{ts}a{rnd}amzagag93000{suffix}"


def gen_web_id(a1: str) -> str:
    """Derive `webId` from a generated `a1`."""
    return hashlib.md5(a1.encode()).hexdigest()


def _is_pid_alive(pid: int) -> bool:
    """Return True if a process with the given PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
