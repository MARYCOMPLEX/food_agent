"""High-level signed HTTP client for the xhs Edith API."""
from __future__ import annotations

import httpx

from .node_runtime import ensure_signer_assets
from .paths import EDITH, HOME
from .profile import Profile
from .signer import get_signer


class XhsClient:
    """Signed httpx client. Use as a context manager."""

    def __init__(self, profile: Profile, prefer_socket: bool = True) -> None:
        self.profile = profile
        ensure_signer_assets(profile.cookie_str)
        self.signer = get_signer(profile, prefer_socket=prefer_socket)
        self.client = httpx.Client(timeout=15.0, follow_redirects=False, trust_env=False)

    def __enter__(self) -> "XhsClient":
        return self

    def __exit__(self, *a) -> None:
        self.close()

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
