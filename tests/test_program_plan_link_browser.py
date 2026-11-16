# -*- coding: utf-8 -*-
"""
הקישור לתוכנית הלימודים של המסלול באתר המכללה, בדפדפן אמיתי
(‏docs/SPEC_LINKS.md, פיצ'ר 1).

השרת שהדפדפן מדבר איתו רץ **בתוך התהליך הזה** (‏werkzeug בחוט) עם
``programs.load_programs`` עטוף, שמוחק את ``plan_url`` האמיתי ומציב כתובות
מזויפות לשני מסלולים בלבד. כך הנתונים המזויפים מגיעים בדיוק לשרת שהעמוד טוען
ממנו, בלי לגעת בקובץ, והבדיקה אינה תלויה בערכים שב-``data/programs.json``.

נבדק:
* לפני בחירת מסלול — אין קישור נראה.
* מסלול עם ``plan_url`` — הקישור נראה, עם ה-href שלו, ‏target="_blank"
  ו-rel עם noopener ו-noreferrer, ושם נגיש שאומר שהוא נפתח בלשונית חדשה.
* מסלול בלי ``plan_url`` — אין קישור נראה, וגם אין href (לא קישור מת).
* שני מועדי הכניסה של מתמטיקה — אותו href.
* בהיר וכהה — נראה; טבעת פוקוס; לא מודפס.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _path in (str(ROOT / "src"), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

import programs as programs_mod  # noqa: E402
from web.api import create_app  # noqa: E402

SOFTWARE = "הנדסת תוכנה"
CIVIL = "הנדסה אזרחית"
MATH = "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה"

FAKE_PLAN_URLS = {
    SOFTWARE: "https://plans.example.invalid/software",
    MATH: "https://plans.example.invalid/math",
}

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
PLAN_LINK_TEXT = STRINGS["ui"]["program"]["planLink"]
NEW_TAB_TEXT = STRINGS["ui"]["program"]["opensInNewTab"]

LINK = "#program-plan-link"

#: מה שהעמוד מראה על הקישור — ‏visible הוא "יש לו קופסה על המסך".
STATE = """() => {
  const a = document.getElementById('program-plan-link');
  if (!a) return null;
  const box = a.getBoundingClientRect();
  return {
    hidden: a.hidden,
    visible: !!(a.offsetParent) && box.width > 0 && box.height > 0,
    href: a.getAttribute('href'),
    target: a.getAttribute('target'),
    rel: (a.getAttribute('rel') || '').split(/\\s+/).filter(Boolean),
    text: a.textContent.replace(/\\s+/g, ' ').trim(),
    iconHidden: (a.querySelector('svg') || {getAttribute: () => null}).getAttribute('aria-hidden'),
    color: getComputedStyle(a).color,
    bg: getComputedStyle(document.body).backgroundColor,
  };
}"""


def _load_with_plan_urls(original):
    def load(*args, **kwargs):
        out = []
        for entry in original(*args, **kwargs):
            entry = dict(entry)
            entry.pop("plan_url", None)
            if entry.get("name") in FAKE_PLAN_URLS:
                entry["plan_url"] = FAKE_PLAN_URLS[entry["name"]]
            out.append(entry)
        return out

    return load


@pytest.fixture(scope="module")
def server():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            programs_mod, "load_programs", _load_with_plan_urls(programs_mod.load_programs)
        )
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        srv = make_server(
            "127.0.0.1", port, create_app(config={"allow_network": False}), threaded=True
        )
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{port}/"
        finally:
            srv.shutdown()
            thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        try:
            instance = pw.chromium.launch()
        except Exception as exc:  # אין דפדפן מותקן — לא כישלון של הקוד
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture(scope="module")
def page(browser, server):
    """עמוד אחד לכל המודול, מתחיל נקי (בלי מצב שמור), בערכה כהה."""
    ctx = browser.new_context(viewport={"width": 1100, "height": 900}, color_scheme="dark")
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.goto(server)
    pg.wait_for_function(
        "() => document.querySelectorAll('#select-program option').length > 2",
        timeout=15000,
    )
    yield pg
    ctx.close()


def choose(pg, program: str) -> dict:
    pg.select_option("#select-program", program)
    pg.wait_for_timeout(400)
    return pg.evaluate(STATE)


def test_the_fake_data_reached_the_server_the_browser_uses(page):
    """בלי זה, כל בדיקת "אין קישור" כאן הייתה עוברת גם כשהזרקה נכשלה."""
    programs = page.evaluate(
        "() => fetch('/api/bootstrap').then(r => r.json()).then(d => d.programs)"
    )
    by_id = {p["id"]: p for p in programs}
    assert by_id[SOFTWARE].get("plan_url") == FAKE_PLAN_URLS[SOFTWARE]
    assert "plan_url" not in by_id[CIVIL]


def test_no_visible_link_before_a_program_is_chosen(page):
    assert page.eval_on_selector("#select-program", "s => s.value") == ""
    state = page.evaluate(STATE)
    assert state is not None, "‏#program-plan-link חסר בעמוד"
    assert state["visible"] is False, state
    assert state["hidden"] is True, state
    assert state["href"] is None, f"קישור מוסתר עדיין נושא href: {state}"


def test_choosing_a_program_shows_its_plan_link(page):
    state = choose(page, SOFTWARE)
    assert state["visible"] is True, state
    assert state["href"] == FAKE_PLAN_URLS[SOFTWARE], state
    assert state["target"] == "_blank", state
    assert "noopener" in state["rel"] and "noreferrer" in state["rel"], state
    assert PLAN_LINK_TEXT in state["text"], state
    assert state["iconHidden"] == "true", state


def test_the_accessible_name_says_it_opens_in_a_new_tab(page):
    choose(page, SOFTWARE)
    name = page.get_by_role("link", name=PLAN_LINK_TEXT)
    assert name.count() == 1
    accessible = name.evaluate(
        "a => a.textContent.replace(/\\s+/g, ' ').trim()"
    )
    assert NEW_TAB_TEXT in accessible, accessible


def test_a_program_without_plan_url_shows_no_link(page):
    choose(page, SOFTWARE)
    state = choose(page, CIVIL)
    assert state["visible"] is False, state
    assert state["hidden"] is True, state
    assert state["href"] is None, f"מסלול בלי plan_url נשאר עם href: {state}"


def test_both_math_intakes_get_the_same_link(page):
    state = choose(page, MATH)
    assert state["visible"] is True, state
    assert state["href"] == FAKE_PLAN_URLS[MATH], state
    hrefs = {}
    for intake in ("winter", "spring"):
        page.select_option("#select-intake", intake)
        page.wait_for_timeout(400)
        got = page.evaluate(STATE)
        assert got["visible"] is True, (intake, got)
        hrefs[intake] = got["href"]
    assert hrefs["winter"] == hrefs["spring"] == FAKE_PLAN_URLS[MATH], hrefs


def test_the_link_has_a_visible_focus_ring(page):
    choose(page, SOFTWARE)
    page.focus("#select-program")
    page.keyboard.press("Tab")
    focused = page.evaluate("() => document.activeElement && document.activeElement.id")
    assert focused == "program-plan-link", focused
    ring = page.eval_on_selector(
        LINK,
        "a => { const s = getComputedStyle(a); return [s.outlineStyle, s.outlineWidth]; }",
    )
    assert ring[0] == "solid" and ring[1] != "0px", ring


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_visible_and_readable_in_both_themes(browser, server, scheme):
    ctx = browser.new_context(viewport={"width": 1100, "height": 900}, color_scheme=scheme)
    pg = ctx.new_page()
    try:
        pg.goto(server)
        pg.wait_for_function(
            "() => document.querySelectorAll('#select-program option').length > 2",
            timeout=15000,
        )
        state = choose(pg, SOFTWARE)
        assert state["visible"] is True, state
        assert state["color"] != state["bg"], state
    finally:
        ctx.close()


def test_not_printed(page):
    choose(page, SOFTWARE)
    page.emulate_media(media="print")
    try:
        display = page.eval_on_selector(LINK, "a => getComputedStyle(a).display")
    finally:
        page.emulate_media(media="screen")
    assert display == "none", display


def test_no_page_errors_and_no_missing_strings(page):
    assert page.errors == []
    missing = page.evaluate("window.slotwise.missingStrings()")
    assert missing == [], missing
