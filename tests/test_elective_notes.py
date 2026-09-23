# -*- coding: utf-8 -*-
"""הערת השנתון על רשימת הבחירה — ומה שאסור להציג לידה.

הרקע
-----
פרק מתמטיקה שימושית מסיים את רשימת הבחירה במשפט משלו: הנ"ז ותנאי הקדם של
הקורסים שם עשויים להשתנות לפי החלטת המחלקה שהקורס שייך אליה. זו אמירה של
המסמך לסטודנט/ית, והיא נשמרה עד כה ב-``warnings`` — יחד עם יומן החילוץ.

‏``warnings`` אינו לעיניים. יש בו שורות כמו "prereq ריק בכל שורות
הסמסטרים", "‏cohort_year הוא null" ו-"שמונה קורסים נשמרים עם code: null":
תיעוד למי שקורא את הקובץ, רעש — ובחלקו מטעה — על המסך. לכן נוסף שדה
‏``notes``, והוא היחיד שמגיע לממשק.

הבדיקות כאן נועלות את שלוש התכונות: ההערה נמצאת ב-``notes`` ולא
ב-``warnings``; היא מגיעה מנקודת הקצה; ו-``warnings`` **אינו** מוצג.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import create_app  # noqa: E402

CURRICULA_DIR = ROOT / "data" / "curricula"
MATH = "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה"
SOFTWARE = "הנדסת תוכנה"
INDUSTRY = "הנדסת תעשייה וניהול"
CIVIL = "הנדסה אזרחית"

#: חלק מהמשפט, לא כולו — כדי שתיקון ניסוח לא יפיל את הבדיקה.
FOOTNOTE = "עשויים להשתנות בהתאם להחלטות המחלקה"

#: שורות שמעידות שמה שמוצג הוא יומן החילוץ ולא הערה לסטודנט/ית.
INTERNAL = ("code: null", "prereq", "cohort_year", "warnings")


@pytest.fixture()
def client():
    return create_app({"allow_network": False}).test_client()


def electives(client, program, intake=""):
    query = "program=" + urllib.parse.quote(program)
    if intake:
        query += "&intake=" + urllib.parse.quote(intake)
    res = client.get("/api/program/electives?" + query)
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()


def load(name):
    return json.loads((CURRICULA_DIR / f"{name}.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------- הקובץ
@pytest.mark.parametrize("name", ["math-winter", "math-spring"])
def test_the_footnote_lives_in_notes(name):
    notes = load(name).get("notes")
    assert isinstance(notes, list) and notes
    assert all(isinstance(note, str) and note.strip() for note in notes)
    assert any(FOOTNOTE in note for note in notes)


@pytest.mark.parametrize("name", ["math-winter", "math-spring"])
def test_the_footnote_no_longer_lives_in_warnings(name):
    """שדה אחד, לא שניים — אחרת אחד מהם ישתנה והשני יישאר מאחור."""
    assert not any(FOOTNOTE in w for w in load(name)["warnings"])


@pytest.mark.parametrize("name", ["math-winter", "math-spring"])
def test_notes_carries_nothing_internal(name):
    """‏``notes`` מוצג כמות שהוא, ולכן אסור שייכנס אליו תיעוד חילוץ."""
    for note in load(name)["notes"]:
        for marker in INTERNAL:
            assert marker not in note, note


def test_warnings_is_still_where_the_extraction_log_lives():
    """‏השדה הפנימי לא התרוקן — ההפרדה היא בין שני שדות, לא מחיקה."""
    warnings = load("math-winter")["warnings"]
    assert len(warnings) >= 8
    assert any("code: null" in w for w in warnings)


@pytest.mark.parametrize(
    "name", ["biotech", "civil", "electronic", "industry", "infosystems", "mechines"]
)
def test_every_other_program_has_no_notes(name):
    """‏"שאר המסלולים נראים בדיוק כמו קודם" מתחיל מכך שאין להם מה להציג."""
    assert not load(name).get("notes")


# ------------------------------------------------------------ השרת
@pytest.mark.parametrize("intake", ["winter", "spring"])
def test_the_endpoint_serves_the_note(client, intake):
    data = electives(client, MATH, intake)
    assert data["available"] is True
    assert any(FOOTNOTE in note for note in data["notes"])


@pytest.mark.parametrize("program", [SOFTWARE, INDUSTRY, CIVIL])
def test_the_endpoint_serves_no_note_for_anyone_else(client, program):
    data = electives(client, program)
    assert data["available"] is True
    assert data["notes"] == []


def test_the_endpoint_never_puts_the_extraction_log_in_notes(client):
    for program, intake in ((MATH, "winter"), (SOFTWARE, ""), (INDUSTRY, "")):
        for note in electives(client, program, intake)["notes"]:
            for marker in INTERNAL:
                assert marker not in note, (program, note)


# ------------------------------------------------------------ הממשק
@pytest.fixture(scope="module")
def server():
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
    sync_playwright = pytest.importorskip(
        "playwright.sync_api", reason="אין Playwright מותקן"
    ).sync_playwright
    with sync_playwright() as pw:
        try:
            instance = pw.chromium.launch()
        except Exception as exc:  # אין דפדפן מותקן — לא כישלון של הקוד
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture()
def page(browser, server):
    ctx = browser.new_context()
    p = ctx.new_page()
    errors: list[str] = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(server)
    p.wait_for_timeout(1500)
    p.errors = errors  # type: ignore[attr-defined]
    try:
        yield p
    finally:
        ctx.close()


def _expand(page, step_id: str) -> None:
    page.evaluate(
        """(id) => {
      const s = document.getElementById(id);
      if (s && s.classList.contains('is-collapsed')) {
        const b = document.getElementById(id + '-toggle');
        if (b) b.click();
      }
    }""",
        step_id,
    )
    page.wait_for_timeout(200)


def choose(page, program: str, intake: str = "") -> None:
    _expand(page, "step-year")
    page.select_option("#select-program", program)
    page.wait_for_timeout(700)
    _expand(page, "step-year")
    if intake:
        page.select_option("#select-intake", intake)
        page.wait_for_timeout(700)
        _expand(page, "step-year")
        page.select_option("#select-plan-semester", "1")
    else:
        page.select_option("#select-year", "1")
        _expand(page, "step-year")
        page.select_option("#select-term", "א")
    page.wait_for_timeout(2000)


def note_on_screen(page) -> dict:
    return page.evaluate(
        """() => {
      const el = document.getElementById('electives-notes');
      return {
        exists: !!el,
        hidden: el ? el.hidden : null,
        text: el ? (el.textContent || '').trim() : '',
        visible: el ? el.offsetParent !== null : false,
      };
    }"""
    )


def test_applied_maths_shows_the_note(page):
    choose(page, MATH, "winter")
    seen = note_on_screen(page)
    assert seen["exists"] and seen["hidden"] is False and seen["visible"]
    assert FOOTNOTE in seen["text"]
    assert page.errors == []


@pytest.mark.parametrize("program", [SOFTWARE, INDUSTRY])
def test_no_note_appears_for_a_program_that_has_none(page, program):
    """שאר המסלולים נראים בדיוק כמו קודם: אין שורה, לא שורה ריקה."""
    choose(page, program)
    seen = note_on_screen(page)
    assert seen["hidden"] is True
    assert seen["visible"] is False
    assert seen["text"] == ""


def test_the_extraction_log_never_reaches_the_screen(page):
    """‏``warnings`` אינו מוצג — לא כאן ולא בשום מקום אחר בעמוד."""
    choose(page, MATH, "winter")
    body = page.evaluate("() => document.body.innerText")
    for marker in ("code: null", "cohort_year", "prereq"):
        assert marker not in body, marker
