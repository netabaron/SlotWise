# -*- coding: utf-8 -*-
"""
שעון הדפדפן בבדיקות מקובע — ושום בדיקה אינה תלויה בתאריך של היום.

‏ב-2026-10-25 ה-CI נפל על main בלי שום שינוי בקוד: הקטלוג הקפוא עבר את
‏``CATALOG_STALE_DAYS`` (45 יום), באנר "הקטלוג ישן" הופיע בכל עמוד, וחמש
בדיקות גלילה ופריסה נכשלו. ‏הקובץ הזה נכשל **מהיום הראשון** אם השעון אינו
מקובע, ולא רק ביום שבו סף כלשהו נחצה. ראו ``tests/browser_clock.py``.
"""

from __future__ import annotations

import datetime as dt
import re
import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

import browser_clock  # noqa: E402
import strings as strings_mod  # noqa: E402
from src.web.api import create_app  # noqa: E402

APP_JS = ROOT / "src" / "web" / "static" / "app.js"
PIN_MS = browser_clock.PINNED_NOW.timestamp() * 1000
#: זמן ריצה סביר של בדיקה אחת. השעון זורם, ולכן לא שוויון מדויק.
SLACK_MS = 10 * 60 * 1000


# ==========================================================================
# 1. הקיבוע עצמו — בלי דפדפן
# ==========================================================================
def test_the_pin_follows_the_frozen_catalog():
    """נגזר מ-built_at של הקטלוג הקפוא, לא תאריך קשיח שנשכח מאחור."""
    assert browser_clock.PINNED_NOW == (
        browser_clock.fixture_built_at() + browser_clock.PIN_AFTER_BUILD
    )
    assert browser_clock.PIN_AFTER_BUILD > dt.timedelta(0)


def test_the_pin_is_inside_the_catalog_age_threshold():
    """אם ``CATALOG_STALE_DAYS`` יורד אל מתחת לקיבוע, כל בדיקות הדפדפן
    יראו שוב את הבאנר. עדיף שזה ייכשל כאן, בשם, ולא בחמש בדיקות גלילה."""
    match = re.search(r"var CATALOG_STALE_DAYS = (\d+);", APP_JS.read_text(encoding="utf-8"))
    assert match, "CATALOG_STALE_DAYS לא נמצא ב-app.js"
    assert browser_clock.PIN_AFTER_BUILD < dt.timedelta(days=int(match.group(1)))


# ==========================================================================
# 2. מה שהדפדפן רואה
# ==========================================================================
@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            yield b
        finally:
            b.close()


def _now_in(page) -> float:
    page.goto("data:text/html,<p>clock</p>")
    return page.evaluate("Date.now()")


def test_new_page_starts_at_the_pinned_time(browser):
    page = browser.new_page()
    try:
        assert PIN_MS <= _now_in(page) < PIN_MS + SLACK_MS
    finally:
        page.close()


def test_new_context_starts_at_the_pinned_time(browser):
    ctx = browser.new_context(viewport={"width": 800, "height": 600})
    try:
        assert PIN_MS <= _now_in(ctx.new_page()) < PIN_MS + SLACK_MS
    finally:
        ctx.close()


def test_the_pinned_clock_still_runs(browser):
    """‏set_system_time ולא set_fixed_time: הזמן זורם והטיימרים אמיתיים."""
    page = browser.new_page()
    try:
        before = _now_in(page)
        assert page.evaluate("new Promise(r => setTimeout(() => r(true), 50))")
        page.wait_for_timeout(300)
        assert page.evaluate("Date.now()") > before
    finally:
        page.close()


def test_real_frames_context_is_pinned_with_native_raf(browser):
    """‏``new_context_with_real_frames``: אותו קיבוע, ו-rAF של הדפדפן.
    ‏אם סדר סקריפטי האתחול ישתנה ב-Playwright, זה ייכשל כאן ולא כקפיצה
    ‏לסירוגין ב-test_step_continue_no_jump_browser.py."""
    ctx = browser_clock.new_context_with_real_frames(browser, viewport={"width": 800, "height": 600})
    try:
        page = ctx.new_page()
        assert PIN_MS <= _now_in(page) < PIN_MS + SLACK_MS
        assert page.evaluate("String(requestAnimationFrame).includes('[native code]')")
        assert page.evaluate("String(cancelAnimationFrame).includes('[native code]')")
        assert page.evaluate("new Promise(r => requestAnimationFrame(t => r(t > 0)))")
        assert page.evaluate("new Promise(r => setTimeout(() => r(true), 50))")
    finally:
        ctx.close()


@pytest.fixture()
def server(tmp_path):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    app = create_app(config={"allow_network": False, "db_root": str(tmp_path / "db")})
    srv = make_server("127.0.0.1", port, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield "http://127.0.0.1:%d/" % port
    finally:
        srv.shutdown()


def _catalog_old_banner(browser, server, *, at: dt.datetime | None = None) -> bool:
    """טוען את האפליקציה ומחזיר אם באנר "הקטלוג ישן" מוצג. ‏``at`` מזיז
    את השעון מהקיבוע — רק כאן, כדי לבדוק שהבדיקה בכלל רואה את הבאנר."""
    note = strings_mod.get("app.banners.catalogOldNote", "")
    assert note
    ctx = browser.new_context(viewport={"width": 1100, "height": 900})
    try:
        if at is not None:
            ctx.clock.set_system_time(at)
        page = ctx.new_page()
        page.goto(server)
        page.wait_for_function(
            "() => { const t = document.getElementById('freshness-text');"
            " return t && t.hasAttribute('data-state'); }",
            timeout=15000,
        )
        page.wait_for_timeout(500)
        notes = page.evaluate(
            "() => [].map.call(document.querySelectorAll('#banners .banner-note'),"
            " n => n.textContent.trim())"
        )
        return note in notes
    finally:
        ctx.close()


def test_the_app_shows_browser_tests_no_catalog_age_banner(browser, server):
    """מה שכל בדיקת דפדפן רואה: אותו עמוד בכל תאריך, בלי באנר גיל."""
    assert not _catalog_old_banner(browser, server)


def test_far_in_the_future_the_same_page_would_show_it(browser, server):
    """בקרה חיובית: עשר שנים אחרי — הבאנר מופיע. בלי זה, הבדיקה שמעל
    הייתה עוברת גם אילו לא הייתה מסוגלת לראות את הבאנר בכלל."""
    later = browser_clock.PINNED_NOW + dt.timedelta(days=3653)
    assert _catalog_old_banner(browser, server, at=later)


# ==========================================================================
# 3. אף בדיקת דפדפן אינה עוקפת את הקיבוע
# ==========================================================================
#: פותחים דפדפן — ולכן חייבים לעבור דרך Browser.new_context/new_page.
_OPENS_A_PAGE = re.compile(r"\.new_(?:page|context)\(")
#: שעון הקיר. חותמת שנגזרת ממנו אינה באותו זמן כמו הדפדפן.
_WALL_CLOCK = re.compile(r"datetime\.now\(|date\.today\(|time\.time\(\)|utcnow\(")
#: דרכים לפתוח דפדפן ש-install() אינו עוטף.
_UNCOVERED = re.compile(r"launch_persistent_context|async_playwright|connect_over_cdp")


def _browser_test_files():
    """‏בלי הקובץ הזה: הביטויים שלמעלה מופיעים בו כטקסט, והוא מזיז את
    השעון בכוונה בבקרה החיובית."""
    return sorted(
        p for p in TESTS.glob("test_*.py")
        if p.name != Path(__file__).name
        and _OPENS_A_PAGE.search(p.read_text(encoding="utf-8"))
    )


def test_the_scan_finds_the_browser_tests():
    assert len(_browser_test_files()) >= 40


@pytest.mark.parametrize("path", _browser_test_files(), ids=lambda p: p.name)
def test_browser_tests_do_not_read_the_wall_clock(path):
    """חותמת "לפני N ימים" מחושבת מ-``browser_clock.PINNED_NOW``."""
    text = path.read_text(encoding="utf-8")
    hits = [m.group(0) for m in _WALL_CLOCK.finditer(text)]
    assert not hits, f"{path.name} קורא את שעון הקיר: {hits}"


@pytest.mark.parametrize("path", _browser_test_files(), ids=lambda p: p.name)
def test_browser_tests_open_pages_the_pinned_way(path):
    text = path.read_text(encoding="utf-8")
    hits = [m.group(0) for m in _UNCOVERED.finditer(text)]
    assert not hits, f"{path.name} פותח דפדפן בלי קיבוע השעון: {hits}"
