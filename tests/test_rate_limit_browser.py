# -*- coding: utf-8 -*-
"""מה הדף עושה עם 429 (‏DEPLOY.md, "Rate limiting" → "What the student sees").

  * ‏429 של מגן הקצב (JSON עם ``reason: "rate_limited"``) ⇐ באנר אזהרה אחד,
    ‏``app.banners.solveRateLimited``, לא באנר תקלה אדום; ניסיון חוזר לבד
    אחרי ``Retry-After``; ואחרי שלושה ניסיונות ברצף — ``rateLimitedManual``,
    ושקט.
  * ‏429 של ‏Cloud Run עצמו (בלי JSON) ⇐ ``serverBusy``, ולא "הבקשה נדחתה —
    כדאי לשנות את הבחירה".

התשובות של השרת מיורטות; השרת עצמו הוא האמיתי, מקומי ובלי מגן.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

KEY = "braude_schedule_builder_v1"  # אין לשנותו — ראו CLAUDE.md
CODES = ["11069", "61756", "61757", "62027", "61759", "61832"]
STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
ERRORS = STRINGS["app"]["errors"]
BANNER = STRINGS["app"]["banners"]["solveRateLimited"]

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import create_app  # noqa: E402

#: ‏Retry-After בתשובות המיורטות. הדף מצמיד אותו ל-2 שניות לפחות.
RETRY_AFTER = 2


def _state():
    return {
        "schema": 1, "studyYear": 3, "term": "א", "semester": "5",
        "codes": CODES, "known": {}, "program": "הנדסת תוכנה", "topN": 5,
        "activeSchedule": 0, "targetDays": 4, "provenanceReady": True,
        "autoSemester": "5", "autoCodes": CODES, "manualCodes": [],
        "autoDropped": [],
    }


@pytest.fixture(scope="module")
def server():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = make_server("127.0.0.1", port, create_app(config={"allow_network": False}),
                      threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d/" % port
    finally:
        srv.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            yield b
        finally:
            b.close()


class Throttle:
    """‏/api/solve עונה 429 ל-``times`` הבקשות הראשונות, ואחר כך עובר לשרת."""

    def __init__(self, times: int) -> None:
        self.times = times
        self.calls = 0

    def __call__(self, route):
        self.calls += 1
        if self.calls > self.times:
            route.continue_()
            return
        body = {"ok": False, "error": "x", "detail": "rate limited",
                "reason": "rate_limited", "retry_after": RETRY_AFTER}
        route.fulfill(status=429,
                      headers={"content-type": "application/json",
                               "retry-after": str(RETRY_AFTER)},
                      body=json.dumps(body))


def _cloud_run_429(route):
    """מה ש-Cloud Run מחזיר כשאין מופע פנוי: טקסט, בלי JSON."""
    route.fulfill(status=429, headers={"content-type": "text/html"},
                  body="Rate exceeded.")


def _open(browser, server, routes, wait_ms=6500):
    ctx = browser.new_context(viewport={"width": 1100, "height": 900})
    ctx.add_init_script(
        "localStorage.setItem('%s', %s);" % (KEY, json.dumps(json.dumps(_state())))
    )
    page = ctx.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    for pattern, handler in routes:
        page.route(pattern, handler)
    page.goto(server)
    page.wait_for_timeout(wait_ms)
    return ctx, page


def _banners(page):
    return page.evaluate(
        """() => [].slice.call(document.querySelectorAll('#banners .banner')).map(b => ({
            kind: b.className.replace('banner banner--',''),
            text: (b.querySelector('.banner-text')||{}).textContent || '',
        }))"""
    )


def test_rate_limited_is_a_warning_and_the_page_retries_by_itself(browser, server):
    throttle = Throttle(times=10**6)
    ctx, page = _open(browser, server, [("**/api/solve", throttle)], wait_ms=3000)
    try:
        want = BANNER.replace("{error}", ERRORS["rateLimited"])
        banners = _banners(page)
        assert any(b["kind"] == "warn" and b["text"] == want for b in banners), banners
        assert not any(b["kind"] == "error" for b in banners), banners
        before = throttle.calls
        page.wait_for_timeout((RETRY_AFTER + 1) * 1000)
        assert throttle.calls > before, "לא היה ניסיון חוזר אחרי Retry-After"
        assert page.errors == []
    finally:
        ctx.close()


def test_the_retry_succeeds_and_the_warning_goes_away(browser, server):
    throttle = Throttle(times=1)
    ctx, page = _open(browser, server, [("**/api/solve", throttle)],
                      wait_ms=6500 + RETRY_AFTER * 1000)
    try:
        banners = _banners(page)
        assert not any(b["kind"] == "warn" and ERRORS["rateLimited"] in b["text"]
                       for b in banners), banners
        assert page.locator("#schedule-grid .ev").count() > 0, "המערכת לא הגיעה אחרי הניסיון החוזר"
        assert page.errors == []
    finally:
        ctx.close()


def test_after_three_retries_it_stops_and_says_so(browser, server):
    throttle = Throttle(times=10**6)
    # טעינה + שלושה ניסיונות של 2 שניות, ועוד מרווח.
    ctx, page = _open(browser, server, [("**/api/solve", throttle)],
                      wait_ms=6500 + 3 * RETRY_AFTER * 1000 + 2000)
    try:
        want = BANNER.replace("{error}", ERRORS["rateLimitedManual"])
        banners = _banners(page)
        assert any(b["kind"] == "warn" and b["text"] == want for b in banners), banners
        settled = throttle.calls
        page.wait_for_timeout((RETRY_AFTER + 2) * 1000)
        assert throttle.calls == settled, "הדף ממשיך לנסות אחרי שלושה ניסיונות"
        assert page.errors == []
    finally:
        ctx.close()


def test_cloud_runs_own_429_says_busy_not_change_your_selection(browser, server):
    ctx, page = _open(browser, server, [("**/api/solve", _cloud_run_429)])
    try:
        texts = [b["text"] for b in _banners(page)]
        assert any(ERRORS["serverBusy"] in t for t in texts), texts
        rejected = ERRORS["badRequest"].split("{error}")[0]
        assert not any(rejected in t for t in texts), texts
        assert page.errors == []
    finally:
        ctx.close()
