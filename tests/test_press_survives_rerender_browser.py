"""לחיצה על מתג אינה נבלעת כשהשלב נבנה מחדש באמצעה.

‏rebuild() מחליף כל צומת במכולה. שינוי מצב בונה את שלב המרצים מחדש פעמיים —
כשהחישוב ב-/api/solve מתחיל וכשתשובתו חוזרת — ולחיצה שנמשכה על פני אחת מהן
נחתה בשני צמתים שונים: ‏mousedown על המתג, ‏mouseup על מחליפו, והדפדפן לא שלח
‏click. המתג לא השתנה ולא נאמר דבר. ברווח על מתג ממוקד אותו דבר: ה-keyup נוחת
על הצומת החדש, שלא קיבל את ה-keydown. ‏נמדד 2026-10-23: נבלעה 3 מתוך 3.

‏wirePressGuard() ב-app.js דוחה את הבנייה עד השחרור. כאן: מדליקים את מתג
ההרצאה של 61759 (חישוב יוצא), לוחצים על מתג התרגול ומחזיקים עד שתשובת החישוב
צוירה, ומשחררים. המתג חייב להשתנות, והבקשה הבאה חייבת לשאת את הערך החדש.
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

AUTOMATA = "61759"
LECTURE = f'input[data-fk="att-{AUTOMATA}-הרצאה"]'
TUTORIAL = f'input[data-fk="att-{AUTOMATA}-תרגול"]'

#: ‏זמני האירועים, וגוף כל בקשת /api/solve — כדי לוודא שהלחיצה באמת נמשכה
#: ‏על פני תשובה, ומה נשלח אחריה.
WATCH = r"""
(() => {
  const log = window.__press = {down: [], up: [], solves: []};
  document.addEventListener('mousedown', () => log.down.push(performance.now()), true);
  document.addEventListener('mouseup', () => log.up.push(performance.now()), true);
  document.addEventListener('keydown', e => { if (e.key === ' ') log.down.push(performance.now()); }, true);
  document.addEventListener('keyup', e => { if (e.key === ' ') log.up.push(performance.now()); }, true);
  const of = window.fetch;
  window.fetch = function (url, opts) {
    if (!String(url).includes('/api/solve')) return of.apply(this, arguments);
    const rec = {body: opts && opts.body, start: performance.now(), end: null};
    log.solves.push(rec);
    return of.apply(this, arguments).then(r => { rec.end = performance.now(); return r; });
  };
})();
"""


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


def _ready(browser, server):
    """הנדסת תוכנה שנה ג׳ סמסטר א׳ עם המומלצים, בשלב המרצים, 61759 פתוח."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.add_init_script(WATCH)
    pg = ctx.new_page()
    pg.goto(server)
    pg.wait_for_timeout(3500)
    pg.select_option("#select-program", "הנדסת תוכנה")
    pg.select_option("#select-year", "3")
    pg.select_option("#select-term", "א")
    pg.wait_for_timeout(2500)
    pg.click("#step-year-next")
    pg.click("#btn-restore-recommended")
    pg.wait_for_timeout(6000)
    pg.click("#step-courses-next")
    pg.click("#step-days-next")
    pg.wait_for_timeout(500)
    head = pg.locator(f'[data-fk="lect-course-{AUTOMATA}"]')
    if head.get_attribute("aria-expanded") != "true":
        head.click()
    # ‏הגלישה של ראש הקורס נגמרת, וכל חישוב שיצא עד כאן חוזר.
    pg.wait_for_function("() => !document.getElementById('lecturer-courses').style.transform")
    pg.wait_for_timeout(1500)
    return ctx, pg


def _hold_across_a_solve(pg, press, release):
    """מדליק את מתג ההרצאה, לוחץ על התרגול, ומשחרר רק אחרי שהתשובה צוירה."""
    before = pg.evaluate("s => document.querySelector(s).checked", TUTORIAL)
    n = pg.evaluate("() => window.__press.solves.length")
    # ‏מתג אחר: שינוי מצב, ובעוד ‎150ms‎ חישוב.
    pg.evaluate("s => document.querySelector(s).click()", LECTURE)
    pg.evaluate("s => { document.querySelector(s).__pressed = true; }", TUTORIAL)
    press()
    pg.wait_for_function(
        "n => window.__press.solves.length > n && window.__press.solves[n].end !== null", arg=n)
    # ‏התשובה מפוענחת ומצוירת מיד אחרי שהיא מגיעה.
    pg.wait_for_timeout(400)
    release()
    pg.wait_for_timeout(1500)
    got = pg.evaluate(
        """(a) => { const n = document.querySelector(a.sel); const p = window.__press;
             const s = p.solves[a.n];
             return {checked: n.checked, sameNode: n.__pressed === true,
                     down: p.down[p.down.length - 1], up: p.up[p.up.length - 1],
                     solveEnd: s.end,
                     last: JSON.parse(p.solves[p.solves.length - 1].body).attendance || {},
                     solves: p.solves.length - a.n}; }""",
        {"sel": TUTORIAL, "n": n})
    return before, got


def _check_sent(before, attendance):
    """בשרת מפתח חסר = חובה: מתג דלוק נשלח כ-true או לא נשלח, כבוי — false."""
    sent = attendance.get(AUTOMATA, {}).get("תרגול")
    if before:
        assert sent is False, attendance
    else:
        assert sent is not False, attendance


def _check(before, got):
    # ‏התנאי של הבדיקה עצמה: הלחיצה החזיקה על פני תשובה של /api/solve.
    assert got["down"] < got["solveEnd"] < got["up"], got
    assert got["checked"] is (not before), f"הלחיצה נבלעה: {got}"
    _check_sent(before, got["last"])
    assert got["solves"] >= 2, "החישוב שאחרי הלחיצה יצא עם הערך החדש"
    assert not got["sameNode"], "הבנייה שנדחתה צוירה אחרי השחרור"


def test_a_mouse_press_held_across_a_solve_still_toggles(browser, server):
    ctx, pg = _ready(browser, server)
    try:
        def press():
            box = pg.locator(TUTORIAL).bounding_box()
            pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            pg.mouse.down()

        before, got = _hold_across_a_solve(pg, press, pg.mouse.up)
    finally:
        ctx.close()
    _check(before, got)


def test_space_held_across_a_solve_still_toggles(browser, server):
    ctx, pg = _ready(browser, server)
    try:
        pg.focus(TUTORIAL)

        def press():
            pg.keyboard.down(" ")

        before, got = _hold_across_a_solve(pg, press, lambda: pg.keyboard.up(" "))
        focused = pg.evaluate("s => document.activeElement === document.querySelector(s)", TUTORIAL)
    finally:
        ctx.close()
    _check(before, got)
    assert focused, "הפוקוס נשאר על המתג אחרי הציור"


def test_a_short_click_with_nothing_in_flight_still_toggles(browser, server):
    ctx, pg = _ready(browser, server)
    try:
        before = pg.evaluate("s => document.querySelector(s).checked", TUTORIAL)
        box = pg.locator(TUTORIAL).bounding_box()
        pg.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        pg.wait_for_timeout(1500)
        after = pg.evaluate("s => document.querySelector(s).checked", TUTORIAL)
        last = pg.evaluate(
            "() => { const s = window.__press.solves; return JSON.parse(s[s.length - 1].body).attendance || {}; }")
    finally:
        ctx.close()
    assert after is (not before)
    _check_sent(before, last)
