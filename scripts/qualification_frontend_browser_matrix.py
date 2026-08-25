"""Playwright browser qualification for the frontend compatibility surface.

The API is mocked at the browser boundary so this matrix measures frontend
HTTP/SSE behavior and responsive routing without depending on live providers.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Browser, Page, Route, sync_playwright

BASE_URL = "http://127.0.0.1:4173"
SCREENSHOT_DIR = Path(tempfile.gettempdir()) / "food-agent-browser-matrix"

RESTAURANT = {
    "name": "锦里小馆",
    "location": "成都",
    "confidence": 0.91,
    "tags": ["本地人常去"],
    "features": ["小巷里的家常川味"],
    "pros": ["口味稳定"],
    "cons": [],
    "mustTry": [{"name": "红油抄手", "reason": "鲜香"}],
    "blackList": [],
    "stats": {"locality": 0.9, "authenticity": 0.88},
    "source_notes": ["note-1"],
    "poi_details": {"address": "锦江区样例街 1 号"},
}


def _json(route: Route, value: object, *, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(value, ensure_ascii=False),
    )


def install_mock_api(page: Page) -> dict[str, object]:
    state: dict[str, object] = {"sse_attempts": 0, "sse_urls": []}

    def handle(route: Route) -> None:
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path

        if request.method == "POST" and path == "/v1/search/":
            _json(
                route,
                {
                    "success": True,
                    "sessionId": "browser-session",
                    "streamUrl": "/v1/search/stream/browser-session",
                },
            )
            return

        if path == "/v1/search/stream/browser-session":
            attempt = int(state["sse_attempts"]) + 1
            state["sse_attempts"] = attempt
            urls = state["sse_urls"]
            assert isinstance(urls, list)
            urls.append(request.url)
            if attempt == 1:
                route.fulfill(status=503, content_type="text/plain", body="temporary outage")
                return
            body = (
                    "event: intent_parsed\n"
                    'data: {"intent":{"location":"成都","food_type":"川菜","requirements":[],"exclude_keywords":[]}}\n\n'
                    "event: restaurant\n"
                    f"data: {json.dumps({'restaurant': RESTAURANT}, ensure_ascii=False)}\n\n"
                    "event: result\n"
                    'data: {"summary":"已完成本地餐厅推荐"}\n\n'
                    "event: done\n"
                    "data: {}\n\n"
                )
            route.fulfill(
                status=200,
                headers={"Cache-Control": "no-cache"},
                content_type="text/event-stream",
                body=body,
            )
            return

        if request.method == "GET" and path == "/v1/favorites":
            _json(route, {"success": True, "data": {"favorites": [{"restaurantId": "r-1", "restaurant": RESTAURANT}]}})
            return

        if request.method == "GET" and path == "/v1/history":
            _json(
                route,
                {
                    "success": True,
                    "data": {"history": [{"id": "h-1", "query": "成都本地川菜", "createdAt": "2026-08-25T00:00:00Z", "resultsCount": 1}], "total": 1},
                },
            )
            return

        if path.endswith("/check"):
            _json(route, {"success": True, "data": {"isFavorite": True}})
            return

        if request.method in {"POST", "DELETE", "PUT"}:
            _json(route, {"success": True, "data": {}})
            return

        _json(route, {"success": True, "data": {}})

    page.route("**/v1/**", handle)
    return state


def assert_search_and_reconnect(page: Page, state: dict[str, object]) -> None:
    page.goto(f"{BASE_URL}/")
    page.wait_for_load_state("networkidle")
    search = page.locator("textarea[placeholder]")
    search.fill("成都本地川菜")
    search.press("Enter")
    page.get_by_role("heading", name="锦里小馆").wait_for(timeout=10_000)
    page.get_by_text("已完成本地餐厅推荐", exact=True).wait_for(timeout=10_000)

    deadline = time.monotonic() + 8
    while int(state["sse_attempts"]) < 2 and time.monotonic() < deadline:
        page.wait_for_timeout(250)
    assert int(state["sse_attempts"]) == 2, state
    urls = state["sse_urls"]
    assert isinstance(urls, list) and len(urls) == 2
    assert parse_qs(urlparse(urls[1]).query).get("lastEventIndex", []) == []


def assert_auxiliary_routes(page: Page) -> None:
    page.goto(f"{BASE_URL}/favorites")
    page.wait_for_load_state("networkidle")
    page.get_by_role("heading", name="锦里小馆").wait_for(timeout=10_000)

    page.goto(f"{BASE_URL}/history")
    page.wait_for_load_state("networkidle")
    page.get_by_text("成都本地川菜", exact=True).wait_for(timeout=10_000)

    page.goto(f"{BASE_URL}/profile")
    page.wait_for_load_state("networkidle")
    faq = page.get_by_role("button", name="数据来自哪里？")
    faq.click()
    page.get_by_text("所有推荐基于真实小红书笔记分析", exact=False).wait_for(timeout=10_000)


def run_browser(browser_name: str, browser: Browser, width: int, height: int) -> None:
    page = browser.new_page(viewport={"width": width, "height": height}, locale="zh-CN")
    state = install_mock_api(page)
    assert_search_and_reconnect(page, state)
    assert_auxiliary_routes(page)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SCREENSHOT_DIR / f"{browser_name}-{width}x{height}.png"), full_page=True)
    page.close()


def main() -> None:
    requested = {
        value.strip().lower()
        for value in os.getenv("FOOD_AGENT_BROWSER_MATRIX_BROWSERS", "").split(",")
        if value.strip()
    }
    with sync_playwright() as playwright:
        for browser_name, launcher in (
            ("chromium", playwright.chromium),
            ("firefox", playwright.firefox),
            ("webkit", playwright.webkit),
        ):
            if requested and browser_name not in requested:
                continue
            browser = launcher.launch(headless=True)
            try:
                for width, height in ((1280, 900), (390, 844)):
                    run_browser(browser_name, browser, width, height)
                    print(f"{browser_name} {width}x{height}: PASS")
            finally:
                browser.close()


if __name__ == "__main__":
    main()
