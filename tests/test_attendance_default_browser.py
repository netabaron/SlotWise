"""מתג חובת הנוכחות מתחיל כבוי, אלא אם הידיעון מחייב נוכחות (2026-10-10).

docs/DESIGN.md, Lecturers, "The switch starts off":
* המתג דלוק בהתחלה רק ברכיב שהשרת מסמן ``from_yedion`` (‏``api.attendance_info``).
  בקטלוג הקפוא, הנדסת תוכנה שנה ג׳ סמסטר א׳ עם המומלצים: 1 מתוך 12 רכיבים,
  ‏11069 שו"ת.
* השרת לא השתנה — מפתח חסר עדיין פירושו חובה — ולכן הדף שולח ``false`` מפורש
  לכל רכיב כבוי.
* בחירה שמורה נשמרת; רק רכיב שלא נגעו בו מקבל את ברירת המחדל החדשה.
* ליד המתגים: "אם יש בשיעור חובת נוכחות, הדליקו." — בלי אזכור של הידיעון.
* בפרטי השיעור של חפיפה, מתחת לכל שיעור כבוי: "השיעור הזה מסומן בלי חובת
  נוכחות. אם יש בו חובה, הדליקו את המתג בשלב המרצים."
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import create_app  # noqa: E402

STORAGE_KEY = "braude_schedule_builder_v1"  # אין לשנותו — ראו CLAUDE.md
STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
ATT = STRINGS["app"]["lecturers"]["attendance"]
DETAIL = STRINGS["app"]["detail"]

ENGLISH, QA = "11069", 'שו"ת'
#: ‏12 הרכיבים של ששת המומלצים בקטלוג הקפוא, וכולם חוץ מ-11069 שו"ת כבויים.
KINDS = {
    "11069": [QA],
    "61756": ["הרצאה", "תרגול", "פרויקט"],
    "61757": ["הרצאה", "מעבדה"],
    "62027": ["הרצאה", "תרגול"],
    "61759": ["הרצאה", "תרגול"],
    "61832": ["הרצאה", "תרגול"],
}
OFF = {code: kinds for code, kinds in KINDS.items() if code != ENGLISH}

#: ‏ביעד 4 עם שני הדירוגים האלה, המובילה מכבדת את שניהם בחפיפה אחת — הרצאת
#: ‏61759 מול תרגול 61756 (נמדד 2026-10-10).
RANKED_OVERLAP = {
    "61759": {"הרצאה": ['ד"ר יהלום אורלי']},
    "61756": {"תרגול": ["מר חסאוי טירן"]},
}


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
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Exception as exc:
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            yield b
        finally:
            b.close()


def _open(browser, server, seed=None):
    """הנדסת תוכנה שנה ג׳ סמסטר א׳ עם המומלצים, עד שיש מערכת.

    ‏``seed`` נכתב למצב השמור ואז הדף נטען מחדש — כמו סטודנט/ית שחוזר/ת.
    כל בקשה ל-/api/solve נאספת ב-``page.solves``.
    """
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = ctx.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.solves = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]

    def grab(request):
        if request.method == "POST" and request.url.endswith("/api/solve"):
            try:
                page.solves.append(request.post_data_json)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

    page.on("request", grab)
    page.goto(server)
    page.wait_for_timeout(2500)
    page.select_option("#select-program", "הנדסת תוכנה")
    page.select_option("#select-year", "3")
    page.select_option("#select-term", "א")
    page.wait_for_timeout(2500)
    page.click("#step-year-next")
    page.click("#btn-restore-recommended")
    page.wait_for_selector("#alt-cards .alt-card", timeout=20000)
    if seed:
        page.evaluate(
            """(a) => { const s = JSON.parse(localStorage.getItem(a.key) || '{}');
                        Object.assign(s, a.fields); localStorage.setItem(a.key, JSON.stringify(s)); }""",
            {"key": STORAGE_KEY, "fields": seed},
        )
        page.solves.clear()  # type: ignore[attr-defined]
        page.reload()
        page.wait_for_selector("#alt-cards .alt-card", timeout=20000)
    page.wait_for_timeout(1500)
    return ctx, page


SWITCHES = """() => Object.fromEntries(
  [...document.querySelectorAll('input[role="switch"]')].map(i => [i.dataset.fk, i.checked]))"""


def _fk(code, kind):
    return f"att-{code}-{kind}"


def test_only_the_kind_the_yedion_requires_starts_on(browser, server):
    ctx, page = _open(browser, server)
    try:
        switches = page.evaluate(SWITCHES)
        stored = page.evaluate("() => window.slotwise.getState().attendance")
        hints = page.evaluate(
            "() => [...document.querySelectorAll('.lect-attendance .att-hint')].map(p => p.textContent)"
        )
        box = page.evaluate(
            "() => [...document.querySelectorAll('.lect-attendance')].map(b => b.textContent).join('\\n')"
        )
        pill = page.evaluate("() => document.querySelector('#attendance-off summary').textContent")
        assert page.errors == [], page.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()

    want = {_fk(code, kind): code == ENGLISH for code, kinds in KINDS.items() for kind in kinds}
    assert switches == want, switches
    # ‏ברירת מחדל אינה בחירה: שום דבר לא נשמר.
    assert stored == {}, stored
    assert hints == [ATT["hint"]] * len(KINDS), hints
    assert ATT["hint"] == "אם יש בשיעור חובת נוכחות, הדליקו."
    assert "ידיעון" not in box, box
    assert pill == ATT["offPill"].replace("{n}", "11"), pill


def test_every_kind_that_starts_off_is_sent_as_false(browser, server):
    ctx, page = _open(browser, server)
    try:
        sent = page.solves[-1]  # type: ignore[attr-defined]
    finally:
        ctx.close()

    want = {code: {kind: False for kind in kinds} for code, kinds in OFF.items()}
    assert sent.get("attendance") == want, sent.get("attendance")


def test_saved_choices_are_kept(browser, server):
    """‏true שמור על רכיב שכבוי כברירת מחדל, ו-false שמור על 11069."""
    saved = {"61759": {"תרגול": True}, ENGLISH: {QA: False}}
    ctx, page = _open(browser, server, seed={"attendance": saved})
    try:
        switches = page.evaluate(SWITCHES)
        sent = page.solves[-1]  # type: ignore[attr-defined]
        stored = page.evaluate("() => window.slotwise.getState().attendance")
    finally:
        ctx.close()

    assert switches[_fk("61759", "תרגול")] is True
    assert switches[_fk(ENGLISH, QA)] is False
    assert switches[_fk("61759", "הרצאה")] is False, "רכיב שלא נגעו בו — ברירת המחדל החדשה"
    assert stored == saved, stored
    att = sent["attendance"]
    assert att["61759"] == {"הרצאה": False, "תרגול": True}, att
    assert att[ENGLISH] == {QA: False}, att


def test_a_choice_equal_to_the_default_is_not_stored(browser, server):
    ctx, page = _open(browser, server)
    try:
        page.evaluate(
            "(fk) => document.querySelector('[data-fk=\"' + fk + '\"]').click()", _fk("61832", "הרצאה")
        )
        page.wait_for_timeout(300)
        on = page.evaluate("() => window.slotwise.getState().attendance")
        page.evaluate(
            "(fk) => document.querySelector('[data-fk=\"' + fk + '\"]').click()", _fk("61832", "הרצאה")
        )
        page.wait_for_timeout(300)
        off = page.evaluate("() => window.slotwise.getState().attendance")
    finally:
        ctx.close()

    assert on == {"61832": {"הרצאה": True}}, on
    assert off == {}, off


def test_an_overlap_says_which_lesson_is_marked_off(browser, server):
    ctx, page = _open(browser, server, seed={"targetDays": 4, "ranked": RANKED_OVERLAP})
    try:
        page.click('#alt-cards .alt-card[data-rank="1"]')
        page.wait_for_timeout(500)
        soft = page.locator("#schedule-grid .ev.is-soft")
        assert soft.count() >= 2, "המובילה אמורה להכיל חפיפה מכוונת"
        rows = page.evaluate(
            "() => [...document.querySelectorAll('#soft-conflicts-list li')].map(li => li.textContent)"
        )
        soft.first.click()
        page.wait_for_timeout(600)
        panel = page.evaluate(
            """() => { const body = document.getElementById('meeting-detail-body');
                 return {head: body.querySelector('.detail-overlap').textContent,
                         items: [...body.querySelectorAll('.detail-item')].map(s => {
                           const p = s.querySelector('.detail-att-off');
                           return {text: s.textContent, off: p ? p.textContent : null}; })}; }"""
        )
        assert page.errors == [], page.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()

    assert DETAIL["overlapOff"] == (
        "השיעור הזה מסומן בלי חובת נוכחות. אם יש בו חובה, הדליקו את המתג בשלב המרצים."
    )
    assert panel["head"].strip() == DETAIL["overlapTitle"] + " " + DETAIL["overlapNote"], panel
    # ‏המשפט מתחת לכל שיעור כבוי, ורק שם: 11069 שו"ת הוא היחיד שדלוק.
    assert len(panel["items"]) >= 2, panel
    for item in panel["items"]:
        want = None if ENGLISH in item["text"] else DETAIL["overlapOff"]
        assert item["off"] == want, item
    assert any(item["off"] for item in panel["items"]), panel
    assert rows and all("בלי חובת נוכחות" in row for row in rows), rows
    assert not any("סימנת" in row for row in rows), rows


def test_the_page_has_no_copy_of_the_yedion_rule():
    """הכלל אחד, בשרת: ‏``from_yedion`` של ``api.attendance_info``."""
    js = (ROOT / "src" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "ATTENDANCE_NOTE_RE" not in js
    assert "from_yedion" in js
    for text in list(ATT.values()) + [DETAIL["overlapNote"], DETAIL["overlapOff"]]:
        assert "ידיעון" not in text, text
