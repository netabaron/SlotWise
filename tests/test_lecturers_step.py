"""שלב 4 של העיצוב מחדש: מרצים (docs/DESIGN.md, "Lecturers").

כל מה שהוצג עד עכשיו עדיין נגיש — רק במקום אחר:
* המקרא הוסר; הפקדים מסבירים את עצמם.
* הסברי חובת הנוכחות עברו מאחורי ⓘ, ורשימת "ללא חובת נוכחות" לגלולה.
* משפט הנוכחות שחזר בכל שורה מופיע פעם אחת לקורס.
* "עודכן לפני…" לכל קורס הוסר (נאמר פעם אחת, בכותרת העמוד).
* מספר הקבוצה אינו עמודה — הוא ב-title של השורה ובשם של כפתור הנעיצה.
ושורה שלא משאירה מערכת אפשרית מעומעמת בצבע, לא ב-opacity (החלטה
‏2026-09-24, ‏tests/test_no_opacity_on_text.py).

בקטלוג הקפוא, הנדסת תוכנה שנה ג׳ סמסטר א׳ עם כל המומלצים: נעיצת הרצאה 1
של 61759 משאירה קבוצת שו"ת אחת של 11069 בלי מערכת אפשרית.
"""

from __future__ import annotations

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

ENGLISH = "11069"
AUTOMATA = "61759"
PIN_LECTURE = f"pin-{AUTOMATA}-הרצאה-271060310/1"
MUT = {"light": "rgb(163, 163, 168)", "dark": "rgb(93, 94, 100)"}


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


def _ready(browser, server, scheme="light"):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme=scheme)
    pg = ctx.new_page()
    pg.goto(server)
    pg.wait_for_timeout(3500)
    pg.select_option("#select-program", "הנדסת תוכנה")
    pg.select_option("#select-year", "3")
    pg.select_option("#select-term", "א")
    pg.wait_for_timeout(2500)
    pg.click("#step-year-next")  # "המשך" אל שלב הקורסים (Phase 8, באישור 2026-10-06)
    pg.click("#btn-restore-recommended")
    pg.wait_for_timeout(6000)
    pg.click("#step-courses-next")  # "המשך" אל ימי הלימוד (Phase 8, באישור 2026-10-06)
    pg.click("#step-days-next")  # "המשך" אל המרצים (Phase 8, באישור 2026-10-06)
    pg.wait_for_timeout(500)
    return ctx, pg


def _fk(pg, fk):
    pg.evaluate("fk => document.querySelector('[data-fk=\"' + fk + '\"]').click()", fk)


def _open(pg, code):
    head = pg.locator(f'[data-fk="lect-course-{code}"]')
    if head.get_attribute("aria-expanded") != "true":
        head.click()
        pg.wait_for_timeout(300)


def _card(code):
    return f"document.querySelector('[data-fk=\"lect-course-{code}\"]').closest('.lect-course')"


# --------------------------------------------------------------------------
# 1. בלי מקרא; "איפוס" בכותרת; שורת עזר אחת
# --------------------------------------------------------------------------
def test_no_legend_and_reset_is_a_link_in_the_header(browser, server):
    ctx, pg = _ready(browser, server)
    try:
        got = pg.evaluate(
            """() => {
              const step = document.getElementById('step-lecturers');
              const reset = document.getElementById('btn-clear-ranking');
              return {legend: step.querySelectorAll('.legend-inline, .legend-swatch, .lect-toolbar').length,
                      oldNotes: ['attendance-note', 'attendance-what'].filter(id => document.getElementById(id)),
                      resetInHead: !!reset.closest('.step-head'),
                      resetText: reset.textContent.trim(),
                      resetName: reset.getAttribute('aria-label'),
                      resetIsBtn: reset.classList.contains('btn'),
                      helper: step.querySelector('.step-hint').textContent.trim()};
            }""")
    finally:
        ctx.close()
    assert got["legend"] == 0 and got["oldNotes"] == [], got
    assert got["resetInHead"] and got["resetText"] == "איפוס" and not got["resetIsBtn"], got
    assert got["resetName"] == "איפוס הדירוג והנעיצות", got
    assert got["helper"] == "לחצו על מרצים לפי סדר העדפה. הנעץ קובע קבוצה.", got


# --------------------------------------------------------------------------
# 2. אקורדיון: קורס אחד פתוח; כותרת עם פס צבע, קוד ונ"ז, וסיכום חי
# --------------------------------------------------------------------------
def test_one_course_open_at_a_time(browser, server):
    ctx, pg = _ready(browser, server)
    try:
        opened = lambda: pg.evaluate(
            "() => [...document.querySelectorAll('.lect-course')].filter(c => "
            "!c.querySelector('.lect-course-body').hidden).length")
        first = opened()
        _open(pg, AUTOMATA)
        after = pg.evaluate(
            """() => [...document.querySelectorAll('.lect-course-head')].map(h => ({
                 fk: h.dataset.fk, expanded: h.getAttribute('aria-expanded'),
                 hidden: document.getElementById(h.getAttribute('aria-controls')).hidden}))""")
    finally:
        ctx.close()
    assert first == 1, "בכניסה קורס אחד פתוח"
    open_ = [h for h in after if h["expanded"] == "true"]
    assert [h["fk"] for h in open_] == [f"lect-course-{AUTOMATA}"], after
    assert all(h["hidden"] == (h["expanded"] != "true") for h in after), after


def test_course_header_carries_stripe_code_credits_and_no_age(browser, server):
    ctx, pg = _ready(browser, server)
    try:
        got = pg.evaluate(
            """(code) => { const c = document.querySelector('[data-fk="lect-course-' + code + '"]').closest('.lect-course');
                 const cs = getComputedStyle(c);
                 const probe = document.createElement('span');
                 probe.style.color = 'var(--ev-bd)'; c.appendChild(probe);
                 const bd = getComputedStyle(probe).color; probe.remove();
                 return {w: cs.borderInlineStartWidth, color: cs.borderInlineStartColor, bd: bd,
                         titleWeight: getComputedStyle(c.querySelector('.lect-course-title')).fontWeight,
                         meta: c.querySelector('.lect-course-meta').textContent,
                         metaColor: getComputedStyle(c.querySelector('.lect-course-meta')).color,
                         choice: c.querySelector('.lect-course-choice').textContent,
                         all: document.getElementById('lecturer-courses').innerText}; }""",
            AUTOMATA)
    finally:
        ctx.close()
    assert got["w"] == "4px" and got["color"] == got["bd"], got
    assert got["titleWeight"] == "600", got
    assert AUTOMATA in got["meta"] and 'נ"ז' in got["meta"], got
    assert got["metaColor"] == MUT["light"], got
    assert got["choice"] == "לא דורג", got
    assert "עודכן" not in got["all"], "גיל הנתונים נאמר פעם אחת, בכותרת העמוד"


# --------------------------------------------------------------------------
# 3. שורות: בלי עמודת קבוצה; דירוג בלחיצה, מספור מחדש, וקפיצה
# --------------------------------------------------------------------------
def test_group_number_is_not_a_column_but_is_still_there(browser, server):
    ctx, pg = _ready(browser, server)
    try:
        _open(pg, AUTOMATA)
        got = pg.evaluate(
            """(code) => { const c = document.querySelector('[data-fk="lect-course-' + code + '"]').closest('.lect-course');
                 const tr = c.querySelector('tbody tr');
                 return {heads: [...c.querySelectorAll('thead th')].map(th => th.textContent.trim()),
                         cells: tr.children.length, title: tr.title,
                         pinName: tr.querySelector('.pin-btn').getAttribute('aria-label'),
                         rowText: tr.innerText}; }""",
            AUTOMATA)
    finally:
        ctx.close()
    assert got["heads"] == ["דירוג", "מרצה", "סוג", "יום ושעה", "חדר", "נעיצה"], got
    assert got["cells"] == 6, got
    assert "קבוצה 271060310/1" in got["title"], got["title"]
    assert "271060310/1" in got["pinName"], got
    assert "271060310" not in got["rowText"], "מספר הקבוצה אינו טקסט גלוי בשורה"


RANKS = """(code) => { const c = document.querySelector('[data-fk="lect-course-' + code + '"]').closest('.lect-course');
  return {choice: c.querySelector('.lect-course-choice').textContent,
          rows: [...c.querySelectorAll('tbody tr')].map(tr => {
            const r = tr.querySelector('.rank-circle');
            return {lect: tr.querySelector('.cell-lect > span').textContent, rank: r.textContent,
                    filled: r.classList.contains('is-ranked'), pop: r.classList.contains('is-pop'),
                    border: getComputedStyle(r).borderTopStyle,
                    anim: getComputedStyle(r).animationName + ' ' + getComputedStyle(r).animationDuration};
          })}; }"""


def test_click_ranks_the_next_and_click_again_renumbers(browser, server):
    ctx, pg = _ready(browser, server)
    try:
        _open(pg, AUTOMATA)
        before = pg.evaluate(RANKS, AUTOMATA)
        rows = pg.locator(".lect-course.is-open tbody tr")
        rows.nth(0).click()
        popped = pg.evaluate(RANKS, AUTOMATA)
        pg.wait_for_timeout(1500)
        rows.nth(1).click()
        pg.wait_for_timeout(1500)
        two = pg.evaluate(RANKS, AUTOMATA)
        rows.nth(0).click()
        pg.wait_for_timeout(1500)
        renumbered = pg.evaluate(RANKS, AUTOMATA)
    finally:
        ctx.close()

    first, second = before["rows"][0]["lect"], before["rows"][1]["lect"]
    assert all(not r["filled"] and r["border"] == "dashed" and r["rank"] == "" for r in before["rows"]), before
    assert before["choice"] == "לא דורג"

    top = popped["rows"][0]
    assert top["filled"] and top["rank"] == "1" and top["pop"], top
    assert top["anim"] == "rank-pop 0.25s", top

    assert two["choice"] == f"עדיפות: {first} ← {second}", two["choice"]
    by = {r["lect"]: r["rank"] for r in two["rows"]}
    assert by[first] == "1" and by[second] == "2", two

    by = {r["lect"]: r["rank"] for r in renumbered["rows"]}
    assert by[first] == "" and by[second] == "1", renumbered
    assert renumbered["choice"] == f"עדיפות: {second}", renumbered["choice"]


# --------------------------------------------------------------------------
# 4. נעיצה, ושורה שלא משאירה מערכת אפשרית
# --------------------------------------------------------------------------
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_pinned_row_is_course_tinted_and_dead_row_is_dimmed_without_opacity(browser, server, scheme):
    ctx, pg = _ready(browser, server, scheme)
    try:
        _open(pg, AUTOMATA)
        _fk(pg, PIN_LECTURE)
        pg.wait_for_timeout(4000)
        pinned = pg.evaluate(
            """(fk) => { const btn = document.querySelector('[data-fk="' + fk + '"]');
                 const tr = btn.closest('tr'); const card = tr.closest('.lect-course');
                 const probe = document.createElement('span');
                 probe.style.color = 'var(--ev-bd)'; probe.style.backgroundColor = 'var(--ev-bg)';
                 card.appendChild(probe); const p = getComputedStyle(probe);
                 const out = {cls: tr.className, bg: getComputedStyle(tr.cells[1]).backgroundColor,
                              tint: p.backgroundColor, bd: p.color,
                              fill: getComputedStyle(btn.querySelector('path')).fill,
                              pressed: btn.getAttribute('aria-pressed'),
                              choice: card.querySelector('.lect-course-choice').textContent};
                 probe.remove(); return out; }""",
            PIN_LECTURE)
        _open(pg, ENGLISH)
        dead = pg.evaluate(
            """(code) => { const c = document.querySelector('[data-fk="lect-course-' + code + '"]').closest('.lect-course');
                 const tr = c.querySelector('tbody tr.is-dead');
                 if (!tr) return null;
                 return {disabled: tr.getAttribute('aria-disabled'), text: tr.innerText,
                         color: getComputedStyle(tr.cells[1]).color,
                         opacities: [tr, ...tr.cells].map(e => getComputedStyle(e).opacity),
                         pinDisabled: tr.querySelector('.pin-btn').disabled,
                         title: tr.title}; }""",
            ENGLISH)
        pg.locator(".lect-course.is-open tbody tr.is-dead").click(force=True)
        pg.wait_for_timeout(1500)
        still = pg.evaluate(
            "(code) => document.querySelector('[data-fk=\"lect-course-' + code + '\"]')"
            ".closest('.lect-course').querySelector('.lect-course-choice').textContent",
            ENGLISH)
    finally:
        ctx.close()

    assert "is-pinned" in pinned["cls"] and pinned["pressed"] == "true", pinned
    assert pinned["bg"] == pinned["tint"], "שורה נעוצה ברקע גוון הקורס"
    assert pinned["fill"] == pinned["bd"], "נעץ מלא בצבע הקורס"
    assert pinned["choice"].startswith("נעוץ: "), pinned["choice"]

    assert dead, "נעיצת הרצאה 1 של 61759 אמורה להשאיר שורה בלי מערכת ב-11069"
    assert dead["disabled"] == "true" and dead["pinDisabled"], dead
    assert "לא משאיר מערכת אפשרית" in dead["text"], dead["text"]
    assert "קבוצה" in dead["title"], dead["title"]
    assert set(dead["opacities"]) == {"1"}, f"בלי opacity: {dead['opacities']}"
    assert dead["color"] == MUT[scheme], dead
    assert still == "לא דורג", "לחיצה על שורה כזו אינה מדרגת"


# --------------------------------------------------------------------------
# 5. חובת נוכחות: מתגים, ⓘ אחד, הערת הידיעון פעם אחת, והגלולה
# --------------------------------------------------------------------------
def test_attendance_switches_one_info_and_the_note_once(browser, server):
    ctx, pg = _ready(browser, server)
    try:
        got = pg.evaluate(
            """(code) => { const c = document.querySelector('[data-fk="lect-course-' + code + '"]').closest('.lect-course');
                 const note = c.querySelector('.lect-course-note');
                 const body = c.querySelector('.lect-course-body');
                 const info = c.querySelector('.att-info');
                 return {switches: c.querySelectorAll('input[role="switch"]').length,
                         infoBtns: c.querySelectorAll('.info-btn').length,
                         infoHidden: info.hidden,
                         note: note ? note.textContent : null,
                         rowsText: [...c.querySelectorAll('tbody tr')].map(tr => tr.innerText).join('\\n'),
                         visible: body.innerText}; }""",
            ENGLISH)
        _fk(pg, f"att-info-{ENGLISH}")
        pg.wait_for_timeout(300)
        opened = pg.evaluate(
            "(code) => { const i = document.getElementById('att-info-' + code);"
            " return {hidden: i.hidden, text: i.innerText}; }", ENGLISH)
    finally:
        ctx.close()
    assert got["switches"] >= 1 and got["infoBtns"] == 1, got
    assert got["infoHidden"], "ההסבר סגור עד שלוחצים על ⓘ"
    assert got["note"], "משפט הנוכחות של הידיעון מופיע בקורס"
    assert got["note"] not in got["rowsText"], "ולא בשורות"
    assert got["visible"].count(got["note"]) == 1, "פעם אחת לקורס"
    assert not opened["hidden"] and "המנוע לא ישבץ שני שיעורים" in opened["text"], opened


def test_sessions_without_attendance_collapse_into_one_pill(browser, server):
    ctx, pg = _ready(browser, server)
    try:
        before = pg.evaluate("() => document.getElementById('attendance-off').hidden")
        _open(pg, AUTOMATA)
        pg.uncheck(f'input[data-fk="att-{AUTOMATA}-תרגול"]', force=True)
        pg.wait_for_timeout(3000)
        closed = pg.evaluate(
            """() => { const box = document.getElementById('attendance-off');
                 const d = box.querySelector('details');
                 return {hidden: box.hidden, open: d.open,
                         pill: d.querySelector('summary').textContent,
                         line: box.querySelector('.att-off-line').textContent,
                         items: d.querySelectorAll('li').length}; }""")
        pg.click("#attendance-off summary")
        pg.wait_for_timeout(200)
        opened = pg.evaluate("() => document.querySelector('#attendance-off details').open")
    finally:
        ctx.close()
    assert before is True, "כשהכול בחובת נוכחות — אין גלולה"
    assert not closed["hidden"] and not closed["open"], closed
    assert closed["pill"] == "שיעור אחד ללא חובת נוכחות", closed
    assert closed["items"] == 1 and closed["line"], closed
    assert opened is True
