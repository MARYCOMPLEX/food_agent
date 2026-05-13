"""Profile dataclass + on-disk persistence for xhs_food.auth."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from .helpers import dump_cookie_str, gen_a1, gen_web_id
from .paths import DEFAULT_UA, HOME, _profile_dir


@dataclass
class Profile:
    """Persistent device + session state for one xhs identity."""

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
