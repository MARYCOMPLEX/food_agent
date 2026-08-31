"""Lazy bridges for the audited Dianping and Spider_XHS checkouts.

The upstream projects are intentionally *not* installed as application
packages.  This adapter loads only the protocol/auth modules from a pinned
checkout when a feature flag and an account invocation select them.  The
checkout path is added to ``sys.path`` for the import scope only; no upstream
FastAPI app, SQLite store, CLI writer, or worker is started.

Factories are synchronous at the provider edge and are called from an
activity/worker thread by :class:`AccountBoundSourceGateway`.  Session
material is consumed from a transient mapping and any Dianping storage-state
file is activity-local, mode ``0600``, and removed when the provider closes.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
import sys
import tempfile
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from xhs_food.gateways.platform_sources import (
    DianpingProviderPort,
    ProviderEnvelope,
    XhsProviderPort,
)

# ``apis`` and ``xhs_utils`` are top-level packages in Spider_XHS.  Python's
# process-wide import cache would otherwise silently reuse the first checkout
# when a second account/factory points at another path.  In-process mode is
# therefore pinned to one resolved checkout per top-level package.  Deployments
# that need multiple provider revisions should use the sidecar mode; this
# guard turns a subtle cross-checkout data/signature mix-up into a typed
# dependency error instead.
_CHECKOUT_IMPORT_LOCK = threading.RLock()
_CHECKOUT_IMPORT_ROOTS: dict[str, Path] = {}


class ProviderUnavailableError(RuntimeError):
    """Raised when a pinned provider checkout/dependency is not usable."""

    code = "PLATFORM_PROVIDER_UNAVAILABLE"

    def __init__(self, message: str, *, platform: str, checkout: str | None = None) -> None:
        # Do not include session values or arbitrary import tracebacks in the
        # public exception.  The caller maps this to a stable ContractError.
        super().__init__(message[:256])
        self.platform = platform
        self.checkout = checkout


def _capability_unregistered(capability: str) -> ProviderEnvelope:
    """Return a stable provider result for an intentionally unregistered API.

    The canonical source adapter maps this envelope to a non-retryable policy
    error.  Keeping the result transport-neutral lets the same bridge run in
    process or behind the sidecar boundary without exposing ``AttributeError``
    from an upstream API that is not part of this integration.
    """

    return ProviderEnvelope(
        False,
        message=f"provider capability {capability} is not registered",
        code="CAPABILITY_UNREGISTERED",
    )


@dataclass(frozen=True, slots=True)
class ProviderDependencyStatus:
    platform: str
    available: bool
    mode: str
    checkout: str | None
    reason: str | None = None
    provenance_ref: str | None = None


class _BridgeBase:
    def __init__(self, *, platform: str, account_ref: str, checkout: Path) -> None:
        self.platform = platform
        self.account_ref = account_ref
        self.checkout = checkout
        self._closed = False

    @property
    def platform_channel(self) -> str:
        return self.platform

    def close(self) -> None:
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise ProviderUnavailableError(
                "provider client is closed", platform=self.platform, checkout=str(self.checkout)
            )


class DianpingProviderFactory:
    """Create an account-local provider over ``dazhongdianping`` protocols."""

    platform = "dianping"

    def __init__(
        self,
        checkout: str | os.PathLike[str],
        *,
        headless: bool = True,
        provenance_ref: str | None = None,
        module_loader: Any | None = None,
    ) -> None:
        self.checkout = Path(checkout).expanduser().resolve()
        self.headless = headless
        self.provenance_ref = provenance_ref
        self._module_loader = module_loader

    def status(self) -> ProviderDependencyStatus:
        required = (
            "dz_engine/providers/dianping/search.py",
            "dz_engine/providers/dianping/details.py",
            "dz_engine/providers/dianping/reviews.py",
        )
        # An injected loader is the sidecar/qualification seam. It owns its
        # dependency probe and therefore does not require a host checkout.
        missing = [] if self._module_loader is not None else _checkout_missing(
            self.checkout, required
        )
        return ProviderDependencyStatus(
            platform=self.platform,
            available=not missing,
            mode="in_process_protocol",
            checkout=str(self.checkout),
            reason=(f"missing protocol modules: {', '.join(missing)}" if missing else None),
            provenance_ref=self.provenance_ref,
        )

    def __call__(self, account: Any, session: Any, session_material: bytes) -> DianpingProviderPort:
        del session
        account_ref = str(getattr(account, "account_ref", ""))
        if not account_ref:
            raise ProviderUnavailableError("account reference is missing", platform=self.platform)
        account_channel = getattr(getattr(account, "platform", None), "value", None)
        if account_channel is not None and str(account_channel).casefold() != self.platform:
            raise ProviderUnavailableError(
                "provider channel does not match account channel",
                platform=self.platform,
                checkout=str(self.checkout),
            )
        if self._module_loader is None:
            _require_checkout(
                self.checkout,
                (
                    "dz_engine/providers/dianping/search.py",
                    "dz_engine/providers/dianping/details.py",
                    "dz_engine/providers/dianping/reviews.py",
                ),
                platform=self.platform,
            )
        state = _session_state(session_material)
        state_path = _materialize_storage_state(state)
        try:
            search_module = self._load("dz_engine.providers.dianping.search")
            detail_module = self._load("dz_engine.providers.dianping.details")
            review_module = self._load("dz_engine.providers.dianping.reviews")
            search = search_module.DianpingSearchProtocol(
                storage_state_path=state_path, headless=self.headless
            )
            detail = detail_module.DianpingPlaceDetailProtocol(
                storage_state_path=state_path, headless=self.headless
            )
            review = review_module.DianpingReviewProtocol(
                storage_state_path=state_path, headless=self.headless
            )
            return _DianpingBridge(
                checkout=self.checkout,
                account_ref=account_ref,
                state_path=state_path,
                search=search,
                detail=detail,
                review=review,
                search_request_type=search_module.DianpingSearchRequest,
                detail_request_type=detail_module.DianpingPlaceDetailRequest,
                review_request_type=review_module.DianpingReviewRequest,
            )
        except ProviderUnavailableError:
            _remove_file(state_path)
            raise
        except Exception as exc:
            _remove_file(state_path)
            raise ProviderUnavailableError(
                "Dianping protocol dependencies are unavailable",
                platform=self.platform,
                checkout=str(self.checkout),
            ) from exc

    def _load(self, module_name: str) -> Any:
        if self._module_loader is not None:
            return self._module_loader(module_name)
        return _import_from_checkout(self.checkout, module_name)


class _DianpingBridge(_BridgeBase, DianpingProviderPort):
    def __init__(
        self,
        *,
        checkout: Path,
        account_ref: str,
        state_path: Path,
        search: Any,
        detail: Any,
        review: Any,
        search_request_type: Any,
        detail_request_type: Any,
        review_request_type: Any,
    ) -> None:
        super().__init__(platform="dianping", account_ref=account_ref, checkout=checkout)
        self._state_path = state_path
        self._search = search
        self._detail = detail
        self._review = review
        self._search_request_type = search_request_type
        self._detail_request_type = detail_request_type
        self._review_request_type = review_request_type

    def search_places(
        self, *, query: str, city: str = "", limit: int = 20, cursor: str | None = None
    ) -> object:
        self._ensure_open()
        page = _page_from_cursor(cursor)
        # The upstream protocol accepts a numeric city ID.  City names remain
        # in the public query projection; deployments may inject a resolver
        # later without changing this bridge contract.
        request = self._search_request_type(keyword=query, city_id=_city_id(city), page=page)
        payload = _run_async(self._search.search(request))
        return ProviderEnvelope(True, payload=payload)

    def fetch_place(self, *, external_id: str, url: str | None = None) -> object:
        self._ensure_open()
        request = self._detail_request_type(shop_id=external_id, detail_url=url)
        return ProviderEnvelope(True, payload=_run_async(self._detail.fetch(request)))

    def fetch_reviews(self, *, external_id: str, cursor: str | None = None) -> object:
        self._ensure_open()
        request = self._review_request_type(
            shop_id=external_id, page=_page_from_cursor(cursor)
        )
        return ProviderEnvelope(True, payload=_run_async(self._review.fetch(request)))

    def list_media(self, *, external_id: str, url: str | None = None) -> object:
        self._ensure_open()
        # Detail responses contain media references under ``photos``/``images``;
        # keep the bridge response JSON-only and let the canonical adapter
        # normalize URLs and remove access-bearing parameters.
        detail = self.fetch_place(external_id=external_id, url=url)
        payload = detail.payload if isinstance(detail, ProviderEnvelope) else detail
        return ProviderEnvelope(True, payload={"media": _media_from_payload(payload)})

    def close(self) -> None:
        if self._closed:
            return
        try:
            # The pinned protocols close their Playwright browser/context in
            # operation-local ``finally`` blocks. The injected seam may own
            # an additional client, so close every distinct protocol object
            # as well. Gateway ``finally`` invokes this on every exit path.
            seen: set[int] = set()
            for protocol in (self._search, self._detail, self._review):
                if id(protocol) in seen:
                    continue
                seen.add(id(protocol))
                close = getattr(protocol, "close", None)
                if callable(close):
                    with suppress(Exception):
                        close()
        finally:
            super().close()
            _remove_file(self._state_path)


class XhsProviderFactory:
    """Create one PC or Creator Spider_XHS client per account invocation."""

    def __init__(
        self,
        checkout: str | os.PathLike[str],
        *,
        channel: str = "xhs_pc",
        provenance_ref: str | None = None,
        module_loader: Any | None = None,
    ) -> None:
        normalized = str(channel).strip().casefold()
        if normalized not in {"xhs_pc", "xhs_creator"}:
            raise ValueError("XHS channel must be xhs_pc or xhs_creator")
        self.channel = normalized
        self.checkout = Path(checkout).expanduser().resolve()
        self.provenance_ref = provenance_ref
        self._module_loader = module_loader

    def status(self) -> ProviderDependencyStatus:
        required = (
            ("apis/xhs_pc_apis.py", "xhs_utils/xhs_pc/auth.py")
            if self.channel == "xhs_pc"
            else ("apis/xhs_creator_apis.py", "xhs_utils/xhs_creator/auth.py")
        )
        missing = [] if self._module_loader is not None else _checkout_missing(
            self.checkout, required
        )
        return ProviderDependencyStatus(
            platform=self.channel,
            available=not missing,
            mode="in_process_protocol",
            checkout=str(self.checkout),
            reason=(f"missing protocol modules: {', '.join(missing)}" if missing else None),
            provenance_ref=self.provenance_ref,
        )

    def __call__(self, account: Any, session: Any, session_material: bytes) -> XhsProviderPort:
        del session
        account_ref = str(getattr(account, "account_ref", ""))
        if not account_ref:
            raise ProviderUnavailableError(
                "account reference is missing",
                platform=self.channel,
                checkout=str(self.checkout),
            )
        account_channel = getattr(getattr(account, "platform", None), "value", None)
        if account_channel is not None and str(account_channel).casefold() != self.channel:
            raise ProviderUnavailableError(
                "provider channel does not match account channel",
                platform=self.channel,
                checkout=str(self.checkout),
            )
        required = (
            ("apis/xhs_pc_apis.py", "xhs_utils/xhs_pc/auth.py")
            if self.channel == "xhs_pc"
            else ("apis/xhs_creator_apis.py", "xhs_utils/xhs_creator/auth.py")
        )
        if self._module_loader is None:
            _require_checkout(self.checkout, required, platform=self.channel)
        state = _session_state(session_material)
        try:
            if self.channel == "xhs_pc":
                auth_module = self._load("xhs_utils.xhs_pc.auth")
                api_module = self._load("apis.xhs_pc_apis")
                auth_cls = auth_module.XHSPcAuth
                api_cls = api_module.XHS_Apis
            else:
                auth_module = self._load("xhs_utils.xhs_creator.auth")
                api_module = self._load("apis.xhs_creator_apis")
                auth_cls = auth_module.XHSCreatorAuth
                api_cls = api_module.XHS_Creator_Apis
            cookie_value = _cookie_value(state)
            if not cookie_value:
                raise ProviderUnavailableError(
                    "XHS session does not contain an authenticated cookie",
                    platform=self.channel,
                    checkout=str(self.checkout),
                )
            auth = auth_cls.from_cookie(
                cookie_value,
                b1=state.get("b1", ""),
                dsl=state.get("dsl", ""),
                host_cookies=state.get("host_cookies"),
                host_cookie_state=state.get("host_cookie_state"),
            )
            api = api_cls(auth)
            return _XhsBridge(
                checkout=self.checkout,
                channel=self.channel,
                account_ref=account_ref,
                api=api,
            )
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise ProviderUnavailableError(
                "Spider_XHS protocol dependencies are unavailable",
                platform=self.channel,
                checkout=str(self.checkout),
            ) from exc

    def _load(self, module_name: str) -> Any:
        if self._module_loader is not None:
            return self._module_loader(module_name)
        return _import_from_checkout(self.checkout, module_name)


class _XhsBridge(_BridgeBase, XhsProviderPort):
    def __init__(self, *, checkout: Path, channel: str, account_ref: str, api: Any) -> None:
        super().__init__(platform=channel, account_ref=account_ref, checkout=checkout)
        self.channel = channel
        self._api = api

    def search_notes(self, *, query: str, limit: int, cursor: str | None = None) -> object:
        self._ensure_open()
        page = _page_from_cursor(cursor)
        if self.channel == "xhs_creator":
            # ``XHS_Creator_Apis`` is the Creator Studio client.  It does not
            # expose the public PC search/detail/comment endpoints; its
            # bounded read surface is the account's own posted-note page.
            # Keep that distinction explicit instead of falling through to a
            # missing ``search_note`` attribute and leaking AttributeError.
            posted = getattr(self._api, "get_posted_notes_page", None)
            if callable(posted):
                return posted(page=page, tab=0)
            # Older pinned snapshots expose the same endpoint under this
            # compatibility spelling.  It accepts ``page`` but not ``tab``.
            posted_compat = getattr(self._api, "get_publish_note_info", None)
            if callable(posted_compat):
                return posted_compat(page=page)
            return _capability_unregistered("notes.search")
        search = getattr(self._api, "search_note", None)
        if callable(search):
            # ``search_note`` carries the provider page cursor.  Prefer it
            # whenever available; ``search_some_note`` is a convenience API
            # that intentionally discards pagination and is only a fallback
            # for older/minimal checkouts.
            return search(query, page=page)
        search_some = getattr(self._api, "search_some_note", None)
        if callable(search_some):
            return search_some(query, max(1, min(limit, 100)))
        return _capability_unregistered("notes.search")

    def fetch_note(self, *, external_id: str, url: str | None = None) -> object:
        self._ensure_open()
        if self.channel == "xhs_creator":
            return _capability_unregistered("notes.detail")
        target = url or f"https://www.xiaohongshu.com/explore/{external_id}"
        detail = getattr(self._api, "get_note_info", None)
        if callable(detail):
            return detail(target)
        return _capability_unregistered("notes.detail")

    def fetch_comments(self, *, external_id: str, cursor: str | None = None) -> object:
        self._ensure_open()
        if self.channel == "xhs_creator":
            return _capability_unregistered("reviews.search")
        del cursor
        target = f"https://www.xiaohongshu.com/explore/{external_id}"
        comments = getattr(self._api, "get_note_all_comment", None)
        if callable(comments):
            return comments(target)
        comments_out = getattr(self._api, "get_note_all_out_comment", None)
        if callable(comments_out):
            return comments_out(external_id, "")
        return _capability_unregistered("reviews.search")

    def list_media(self, *, external_id: str, url: str | None = None) -> object:
        if self.channel == "xhs_creator":
            return _capability_unregistered("media.refs")
        detail = self.fetch_note(external_id=external_id, url=url)
        if isinstance(detail, ProviderEnvelope) and not detail.success:
            # Do not turn a failed detail call into a misleading empty-success
            # media response.  The canonical adapter must preserve the
            # provider error taxonomy.
            return detail
        payload = detail.payload if isinstance(detail, ProviderEnvelope) else detail
        return ProviderEnvelope(True, payload={"media": _media_from_payload(payload)})

    def health_check(self) -> object:
        """Run the channel's provider health/read probe when available.

        Creator exposes ``get_user_info`` as its authenticated read probe;
        this method intentionally does not invoke publishing/upload APIs.
        The optional method is consumed by account-health adapters and is not
        part of the canonical SourceConnector surface.
        """

        self._ensure_open()
        probe_name = "get_user_info" if self.channel == "xhs_creator" else "get_user_me"
        probe = getattr(self._api, probe_name, None)
        if not callable(probe):
            return _capability_unregistered("account.health")
        return probe()

    def close(self) -> None:
        if self._closed:
            return
        close = getattr(self._api, "close", None)
        # Spider_XHS API facades do not all expose ``close`` themselves; the
        # underlying Auth owns the HTTP client and signer state.  Fall back to
        # that public lifecycle method so each account-local client releases
        # sockets/state at activity end.
        if not callable(close):
            close = getattr(getattr(self._api, "auth", None), "close", None)
        if callable(close):
            with suppress(Exception):
                close()
        super().close()


def build_dianping_provider_factory(
    checkout: str | os.PathLike[str], *, headless: bool = True, provenance_ref: str | None = None
) -> DianpingProviderFactory:
    return DianpingProviderFactory(checkout, headless=headless, provenance_ref=provenance_ref)


def build_xhs_provider_factory(
    checkout: str | os.PathLike[str],
    *,
    channel: str = "xhs_pc",
    provenance_ref: str | None = None,
) -> XhsProviderFactory:
    return XhsProviderFactory(checkout, channel=channel, provenance_ref=provenance_ref)


def _checkout_missing(checkout: Path, required: Sequence[str]) -> list[str]:
    return [item for item in required if not (checkout / item).is_file()]


def checkout_missing(checkout: Path, required: Sequence[str]) -> list[str]:
    """Public readiness helper for sibling composition adapters."""

    return _checkout_missing(checkout, required)


def _require_checkout(checkout: Path, required: Sequence[str], *, platform: str) -> None:
    if not checkout.is_dir():
        raise ProviderUnavailableError(
            "pinned provider checkout is unavailable", platform=platform, checkout=str(checkout)
        )
    missing = _checkout_missing(checkout, required)
    if missing:
        raise ProviderUnavailableError(
            "pinned provider protocol modules are unavailable",
            platform=platform,
            checkout=str(checkout),
        )


@contextmanager
def _checkout_import_path(checkout: Path) -> Iterator[None]:
    path = str(checkout)
    previous = list(sys.path)
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        yield
    finally:
        # Restore the exact caller path, even if an upstream module mutated it.
        sys.path[:] = previous


def _import_from_checkout(checkout: Path, module_name: str) -> Any:
    """Import one provider module without allowing checkout cache mixing.

    Both audited upstream projects expose short top-level package names
    (notably ``apis`` and ``xhs_utils``).  Removing a path from ``sys.path``
    after import does *not* remove those modules from ``sys.modules``.  A
    later factory could consequently execute code from the first checkout
    while believing it selected another one.  Serialize imports and pin each
    top-level package to its first resolved checkout.  Reusing that same
    checkout remains cheap and fully supported; a different checkout gets a
    stable ``ProviderUnavailableError`` and should be run behind the sidecar
    seam instead.
    """

    resolved_checkout = checkout.expanduser().resolve()
    module_root = module_name.partition(".")[0]
    if not module_root:
        raise ProviderUnavailableError(
            "provider module name is empty", platform="platform", checkout=str(resolved_checkout)
        )

    with _CHECKOUT_IMPORT_LOCK:
        _assert_checkout_namespace(resolved_checkout, module_root)
        try:
            with _checkout_import_path(resolved_checkout):
                module = importlib.import_module(module_name)
        except ProviderUnavailableError:
            raise
        except Exception as exc:
            raise ProviderUnavailableError(
                "provider protocol import failed",
                platform="platform",
                checkout=str(resolved_checkout),
            ) from exc

        # Verify the complete package subtree after import.  Importing a
        # submodule can eagerly load siblings, and one of those imports must
        # not come from a different checkout or an unrelated installed
        # package with the same top-level name.
        try:
            _assert_checkout_namespace(resolved_checkout, module_root)
        except ProviderUnavailableError:
            raise
        _CHECKOUT_IMPORT_ROOTS[module_root] = resolved_checkout
        return module


def import_from_checkout(checkout: Path, module_name: str) -> Any:
    """Public lazy-import seam for sibling adapters and sidecar tests."""

    return _import_from_checkout(checkout, module_name)


def _assert_checkout_namespace(checkout: Path, module_root: str) -> None:
    """Validate the cached modules for ``module_root`` belong to ``checkout``.

    A registry entry is discarded only when no corresponding module remains
    in ``sys.modules``.  This makes test/process teardown explicit while
    preserving the safety invariant during normal provider lifetime.
    """

    expected = checkout.resolve()
    registered = _CHECKOUT_IMPORT_ROOTS.get(module_root)
    loaded = _loaded_module_origins(module_root)
    if registered is not None and not _same_path(registered, expected):
        if loaded:
            raise ProviderUnavailableError(
                "provider module namespace is pinned to another checkout",
                platform="platform",
                checkout=str(expected),
            )
        # The caller deliberately removed the package from sys.modules (for
        # example during a worker restart/test teardown), so the old pin is no
        # longer authoritative.
        _CHECKOUT_IMPORT_ROOTS.pop(module_root, None)
        registered = None

    for origin in loaded:
        if not _path_is_under(origin, expected):
            raise ProviderUnavailableError(
                "provider module namespace is loaded from another checkout",
                platform="platform",
                checkout=str(expected),
            )

    if registered is not None and loaded:
        # Keep the canonical spelling in the registry in case a caller passed
        # a relative/case-variant path on a case-insensitive filesystem.
        _CHECKOUT_IMPORT_ROOTS[module_root] = expected


def _loaded_module_origins(module_root: str) -> tuple[Path, ...]:
    """Return filesystem origins for a cached package subtree."""

    origins: list[Path] = []
    prefix = module_root + "."
    for name, module in tuple(sys.modules.items()):
        if name != module_root and not name.startswith(prefix):
            continue
        if module is None:
            continue
        candidates: list[object] = []
        file_value = getattr(module, "__file__", None)
        if file_value:
            candidates.append(file_value)
        spec = getattr(module, "__spec__", None)
        spec_origin = getattr(spec, "origin", None)
        if spec_origin and spec_origin not in {"built-in", "frozen"}:
            candidates.append(spec_origin)
        search_locations = getattr(spec, "submodule_search_locations", None)
        if search_locations:
            candidates.extend(search_locations)
        package_path = getattr(module, "__path__", None)
        if package_path:
            candidates.extend(package_path)
        for candidate in candidates:
            if not isinstance(candidate, (str, os.PathLike)):
                continue
            try:
                path = Path(candidate).expanduser().resolve()
            except (OSError, RuntimeError, TypeError, ValueError):
                continue
            if path not in origins:
                origins.append(path)
    return tuple(origins)


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def _path_is_under(path: Path, root: Path) -> bool:
    """Return whether ``path`` is ``root`` or a descendant of it."""

    path_text = os.path.normcase(str(path.resolve()))
    root_text = os.path.normcase(str(root.resolve())).rstrip("\\/")
    return path_text == root_text or path_text.startswith(root_text + os.sep)


def _session_state(value: bytes | bytearray | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        decoded = json.loads(bytes(value).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise ProviderUnavailableError("session envelope is not valid JSON", platform="platform") from exc
    if not isinstance(decoded, Mapping):
        raise ProviderUnavailableError("session envelope must contain an object", platform="platform")
    return dict(decoded)


def _materialize_storage_state(state: Mapping[str, Any]) -> Path:
    raw: Any = state.get("storage_state", state.get("storage_state_json"))
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailableError("Dianping storage state is malformed", platform="dianping") from exc
    if raw is None:
        cookies = state.get("cookies")
        raw = {"cookies": cookies if isinstance(cookies, list) else []}
    if not isinstance(raw, Mapping):
        raise ProviderUnavailableError("Dianping storage state is malformed", platform="dianping")
    directory = Path(tempfile.mkdtemp(prefix="food-agent-dp-session-"))
    path = directory / "storage-state.json"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(dict(raw), output, ensure_ascii=False, separators=(",", ":"))
        os.chmod(path, 0o600)
        return path
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def _cookie_value(state: Mapping[str, Any]) -> str:
    value = state.get("cookie", state.get("cookies", state.get("xhr_cookie", "")))
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return "; ".join(f"{key}={item}" for key, item in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        pairs: list[str] = []
        for item in value:
            if isinstance(item, Mapping) and item.get("name") is not None:
                pairs.append(f"{item['name']}={item.get('value', '')}")
        return "; ".join(pairs)
    return ""


def _page_from_cursor(cursor: str | None) -> int:
    if cursor is None or not str(cursor).strip():
        return 1
    try:
        value = int(str(cursor))
    except ValueError:
        return 1
    return max(1, min(value, 50))


def _city_id(city: str) -> int:
    try:
        value = int(str(city).strip())
    except (TypeError, ValueError):
        return 1
    return max(1, value)


def _run_async(value: Any) -> Any:
    if not asyncio.iscoroutine(value) and not hasattr(value, "__await__"):
        return value
    return asyncio.run(value)


def _media_from_payload(payload: object) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []

    def visit(value: object) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                key_text = str(key).casefold()
                if key_text in {"image_url", "imageurl", "url", "origin_image", "origin_image_url"} and isinstance(item, str):
                    normalized = _strip_access_query(item)
                    if normalized:
                        values.append({"url": normalized})
                elif key_text in {"image_list", "images", "photos", "media"} or isinstance(item, (Mapping, list, tuple)):
                    visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(payload)
    seen: set[str] = set()
    return [item for item in values if not (item["url"] in seen or seen.add(item["url"]))]


def _strip_access_query(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    pairs = [
        part
        for part in parsed.query.split("&")
        if part and part.split("=", 1)[0].casefold() not in {
            "xsec_token",
            "xsec_source",
            "token",
            "signature",
            "authorization",
        }
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "&".join(pairs), ""))


def _remove_file(path: Path | None) -> None:
    if path is None:
        return
    try:
        directory = path.parent
        path.unlink(missing_ok=True)
        shutil.rmtree(directory, ignore_errors=True)
    except Exception:
        pass


__all__ = [
    "checkout_missing",
    "DianpingProviderFactory",
    "import_from_checkout",
    "ProviderDependencyStatus",
    "ProviderUnavailableError",
    "XhsProviderFactory",
    "build_dianping_provider_factory",
    "build_xhs_provider_factory",
]
