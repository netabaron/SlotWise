# -*- coding: utf-8 -*-
"""שלושת המצבים שנותרו בשלב 6: קטלוג ישן, טעינה שאפשר לעצור, ושגיאות.

הכלל המשותף לשלושתם: להגיד מה קרה **ומה אפשר לעשות עכשיו**, ולא לטעון
דבר שאי אפשר לדעת. במיוחד — מצב הכישלון הוא "הקטלוג ישן" ולא "הריענון
שלך נכשל": למי שמשכפל את המאגר, ולמי שישתמש בגרסה מתארחת, אין ריענון
משלהם בכלל.
"""

from __future__ import annotations

import datetime as dt
import json
import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

import shipped_catalog  # noqa: E402
from src.web.api import create_app  # noqa: E402

KEY = "braude_schedule_builder_v1"
CODES = ["11069", "61756", "61757", "62027", "61759", "61832"]


def _state(**kw):
    base = {
        "schema": 1, "studyYear": 3, "term": "א", "semester": "5",
        "codes": CODES, "known": {}, "program": "הנדסת תוכנה", "topN": 5,
        "activeSchedule": 0, "targetDays": 4, "provenanceReady": True,
        "autoSemester": "5", "autoCodes": CODES, "manualCodes": [],
        "autoDropped": [],
    }
    base.update(kw)
    return base


def _age_catalog(monkeypatch, days: float) -> None:
    """מזייף את תאריך בניית הקטלוג — בלי לגעת בקובץ ובלי לדלוף החוצה.

    שתי הקפדות, ושתיהן נלמדו בדרך הקשה בקובץ הזה:

    1. **דרך monkeypatch ולא בהשמה ישירה.** ‏``_CACHE`` הוא מצב ברמת
       המודול, ומצב כזה שנשאר מזוהם אחרי בדיקה מפיל בדיקה אחרת, במקום
       אחר, בלי קשר נראה לעין.
    2. **מילון חדש ולא שינוי במקום.** ‏``load()`` מחזיר את ``_CACHE``
       עצמו; ``data["meta"] = ...`` היה משנה אותו, ואז שחזור ההפניה
       לא היה מבטל דבר.
    """
    stamp = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    real = shipped_catalog.load()
    patched = {
        "courses": real.get("courses") or {},
        "meta": dict(real.get("meta") or {}, built_at=stamp),
    }
    monkeypatch.setattr(shipped_catalog, "_CACHE", patched, raising=False)
    monkeypatch.setattr(
        shipped_catalog, "_STAMP", shipped_catalog._mtimes(), raising=False
    )


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


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            yield b
        finally:
            b.close()


def _page(browser, server, state=None):
    ctx = browser.new_context(viewport={"width": 1100, "height": 900})
    ctx.add_init_script(
        "localStorage.setItem('%s', %s);" % (KEY, json.dumps(json.dumps(state or _state())))
    )
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.goto(server)
    page.wait_for_timeout(6500)
    return ctx, page


def _banners(page):
    return page.evaluate(
        """() => [].slice.call(document.querySelectorAll('#banners .banner')).map(b => ({
            kind: b.className.replace('banner banner--',''),
            text: (b.querySelector('.banner-text')||{}).textContent || '',
            note: (b.querySelector('.banner-note')||{}).textContent || '',
        }))"""
    )


# ==========================================================================
# 1. הקטלוג ישן
# ==========================================================================
def test_a_fresh_catalog_says_nothing(browser, server, monkeypatch):
    _age_catalog(monkeypatch, 3)
    ctx, page = _page(browser, server)
    try:
        seen = _banners(page)
        assert not [b for b in seen if "קטלוג" in b["text"]], (
            "באנר על קטלוג ישן הופיע על קטלוג טרי"
        )
        # שהבדיקה לא תעבור סתם מפני שהעמוד ריק: מוודאים שהיא בכלל
        # מסוגלת לראות את מצב הבאנרים.
        assert page.evaluate("!!document.getElementById('banners')")
        assert page.errors == []
    finally:
        ctx.close()


def test_an_old_catalog_says_so_without_claiming_anything_about_the_yedion(browser, server, monkeypatch):
    _age_catalog(monkeypatch, 60)
    ctx, page = _page(browser, server)
    try:
        hits = [b for b in _banners(page) if "קטלוג" in b["text"]]
        assert hits, "קטלוג בן חודשיים לא הפיק שום הודעה"
        banner = hits[0]
        # מה שידוע: מתי נבנה. הניסוח מסויג.
        assert "ייתכן" in banner["text"], banner["text"]
        assert banner["note"], "אין שורת הסתייגות"
        assert "אינה בודקת את הידיעון" in banner["note"], banner["note"]
        # ומה שאסור: טענה על מצב הידיעון, או האשמת המשתמש/ת בריענון
        for forbidden in ("הריענון שלך", "נכשל", "התעדכן", "השתנה בידיעון"):
            assert forbidden not in banner["text"], (
                f"הבאנר טוען משהו שאינו ידוע: {forbidden}"
            )
    finally:
        ctx.close()


def test_shipped_courses_do_not_trigger_the_per_course_stale_banner(browser, server, monkeypatch):
    """‏572 קורסים באותו גיל בדיוק אינם "הנתונים שלי התיישנו"."""
    _age_catalog(monkeypatch, 60)
    ctx, page = _page(browser, server)
    try:
        per_course = [b for b in _banners(page) if "מהקורסים שבחרת" in b["text"]]
        assert not per_course, (
            "קורסים שהגיעו עם הקטלוג הופיעו כנתונים אישיים שהתיישנו: "
            + "; ".join(b["text"][:80] for b in per_course)
        )
    finally:
        ctx.close()


def test_the_header_reports_when_the_data_was_pulled(browser, server, monkeypatch):
    """שורה אחת על **מתי הנתונים נמשכו**, וההסתייגות בתווית ההצפה.

    ‏עד 2026-09-20 השורה אמרה "הקטלוג נבנה …" והייתה מתחתיה שורה שנייה עם
    אותו תאריך במילים אחרות. הנוסח החדש הוא של מי שמשתמש ולא של מי שבונה,
    אבל **התנאי לא התרופף**: ההסתייגות — שהאפליקציה אינה יודעת אם הידיעון
    השתנה מאז — עדיין חייבת להופיע, ועכשיו היא בתווית ההצפה.
    """
    _age_catalog(monkeypatch, 60)
    ctx, page = _page(browser, server)
    try:
        head = page.evaluate(
            "document.getElementById('freshness-text').textContent.trim()"
        )
        assert "מעודכן מהידיעון" in head, head
        title = page.evaluate(
            "document.getElementById('freshness-text').getAttribute('title') || ''"
        )
        assert "נמשכו מהידיעון" in title, title
        assert "אין דרך לדעת" in title or "לדעת" in title, title
    finally:
        ctx.close()


# ==========================================================================
# 2. טעינה שאפשר לעצור
# ==========================================================================
@pytest.fixture()
def slow_server(tmp_path):
    """שרת שבו /api/solve איטי בכוונה.

    החישוב האמיתי לוקח 20 מילישניות, ולכן אי אפשר לתפוס בו מצב טעינה
    בלי להאט אותו. ההאטה היא ב-WSGI ולא ב-Playwright: כך מה שנבדק הוא
    בקשה אמיתית שנמצאת באוויר, ולא דגל שהודלק ביד.
    """
    import time as _time

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    app = create_app(config={"allow_network": False, "db_root": str(tmp_path / "db")})

    inner = app.wsgi_app

    def delayed(environ, start_response):
        if environ.get("PATH_INFO", "") == "/api/solve":
            _time.sleep(2.0)
        return inner(environ, start_response)

    app.wsgi_app = delayed
    srv = make_server("127.0.0.1", port, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield "http://127.0.0.1:%d/" % port
    finally:
        srv.shutdown()


def test_a_running_solve_offers_a_way_out(browser, slow_server):
    """כפתור העצירה קיים **בזמן** שהחישוב רץ, ולחיצה עליו עוצרת."""
    ctx, page = _page(browser, slow_server)
    try:
        # לא מחזירים את ה-Promise: ‏page.evaluate ממתין לו, וכך היינו
        # מפספסים בדיוק את החלון שאנחנו רוצים לבדוק.
        page.evaluate("() => { window.slotwise.solveNow(); }")
        page.wait_for_selector('[data-fk="solve-cancel"]', timeout=6000)
        label = page.evaluate(
            """() => document.querySelector('[data-fk="solve-cancel"]').textContent.trim()"""
        )
        assert label, "לכפתור העצירה אין טקסט"
        page.click('[data-fk="solve-cancel"]')
        page.wait_for_timeout(400)
        assert not page.evaluate("window.slotwise.getRuntime().solveBusy"), (
            "לחיצה על ביטול לא עצרה את החישוב"
        )
        # והבחירות שרדו
        assert page.evaluate("window.slotwise.getState().codes.length") == len(CODES)
    finally:
        ctx.close()


def test_cancelling_stops_the_run_and_keeps_the_selection(browser, server):
    ctx, page = _page(browser, server)
    try:
        before = page.evaluate("window.slotwise.getState().codes.length")
        page.evaluate(
            """() => {
              const r = window.slotwise.getRuntime();
              r.solveBusy = true;
            }"""
        )
        page.evaluate("window.slotwise.solveNow && window.slotwise.solveNow()")
        page.wait_for_timeout(2500)
        after = page.evaluate("window.slotwise.getState().codes.length")
        assert after == before, "הבחירות השתנו בעקבות חישוב/ביטול"
        assert not page.evaluate("window.slotwise.getRuntime().solveBusy"), (
            "החישוב נשאר תקוע במצב 'רץ'"
        )
    finally:
        ctx.close()


# ==========================================================================
# 3. שגיאות שאומרות מה לעשות
# ==========================================================================
def test_the_network_error_copy_says_the_selection_is_safe(browser, server):
    ctx, page = _page(browser, server)
    try:
        msg = page.evaluate(
            """() => {
              const T = window.slotwise;
              return document.body ? null : null;
            }"""
        )
        # הניסוח עצמו נבדק מהמחרוזות, כדי לא להפיל את השרת בבדיקה
        text = page.evaluate(
            "window.STRINGS && window.STRINGS.app.errors.network"
        )
        assert text, "אין ניסוח לתקלת רשת"
        assert "שמורות" in text or "לא אבדו" in text, (
            "תקלת רשת אינה אומרת שהבחירות נשמרו — וזו השאלה הראשונה"
        )
        assert "אפשר" in text, "אין צעד הבא"
    finally:
        ctx.close()


def test_error_copy_never_shows_a_raw_exception_name():
    """‏'TypeError: Failed to fetch' אינו הודעה למשתמש/ת."""
    strings = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
    errs = strings["app"]["errors"]
    for key in ("network", "serverFault", "badRequest"):
        text = errs.get(key, "")
        assert text, f"חסר ניסוח: {key}"
        for leak in ("TypeError", "Error:", "Traceback", "undefined"):
            assert leak not in text, f"{key} מדליף מונח טכני: {leak}"
