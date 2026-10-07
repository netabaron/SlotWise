"""שלב 2 של העיצוב מחדש: הסטפר (docs/DESIGN.md, "Steps" ו-"Implementation phases").

מה נשמר כאן: שלושת המראות — שלב פרוס, שורת "הושלם", שורת "הבא" — נגזרים
מאותם מצבים שהיו (‏is-collapsed / is-locked / is-active), הפתיחה והסגירה
מונפשות רק בתגובה לפעולה, וגוף סגור באמת סגור: לא נראה, לא לחיץ, לא
בסדר ה-Tab. והחור שהעטיפה החדשה פתחה פעם אחת — עמוד רחב מהמסך בטלפון.
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

STEPPER = ("year", "courses", "days", "lecturers")
INK = {"light": "rgb(13, 29, 61)", "dark": "rgb(242, 242, 240)"}
SEC = {"light": "rgb(110, 110, 115)", "dark": "rgb(154, 154, 161)"}


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


def _page(browser, server, *, width=1280, scheme="light", reduced=False):
    ctx = browser.new_context(
        viewport={"width": width, "height": 900},
        color_scheme=scheme,
        reduced_motion="reduce" if reduced else "no-preference",
    )
    pg = ctx.new_page()
    pg.goto(server)
    pg.wait_for_timeout(3500)
    return ctx, pg


def _identity_and_courses(pg):
    pg.select_option("#select-program", "הנדסת תוכנה")
    pg.select_option("#select-year", "3")
    pg.select_option("#select-term", "א")
    pg.wait_for_timeout(2500)
    pg.click("#step-year-next")  # "המשך" אל שלב הקורסים (Phase 8, באישור 2026-10-06)
    pg.click("#btn-restore-recommended")
    pg.wait_for_timeout(5000)


LOOK = """(key) => {
  const s = document.getElementById('step-' + key);
  const cs = (sel) => { const e = s.querySelector(sel); return e ? getComputedStyle(e) : null; };
  const body = document.getElementById('step-' + key + '-body');
  const fold = s.querySelector('.step-fold');
  const state = document.getElementById('step-' + key + '-state');
  return {
    cls: s.className,
    height: s.getBoundingClientRect().height,
    border: getComputedStyle(s).borderTopColor,
    foldHeight: fold.getBoundingClientRect().height,
    bodyVisibility: getComputedStyle(body).visibility,
    summaryDisplay: cs('.step-summary').display,
    summaryText: s.querySelector('.step-summary').textContent.trim(),
    changeDisplay: cs('.step-change').display,
    changeText: s.querySelector('.step-change').textContent.trim(),
    hintDisplay: cs('.step-hint').display,
    nameColor: cs('.step-name').color,
    dotBg: getComputedStyle(s.querySelector('.step-title'), '::before').backgroundColor,
    stateWidth: state.getBoundingClientRect().width,
    stateText: state.textContent.trim(),
  };
}"""


# --------------------------------------------------------------------------
# 1. ביקור ראשון: שלב אחד פרוס, והשאר שורות "הבא"
# --------------------------------------------------------------------------
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_first_visit_is_one_open_step_and_three_upcoming_lines(browser, server, scheme):
    ctx, pg = _page(browser, server, scheme=scheme)
    try:
        looks = {k: pg.evaluate(LOOK, k) for k in STEPPER}
    finally:
        ctx.close()

    year = looks["year"]
    assert "is-active" in year["cls"] and "is-collapsed" not in year["cls"], year
    assert year["border"] == INK[scheme], "השלב הפעיל ממוסגר בדיו"
    assert year["bodyVisibility"] == "visible" and year["foldHeight"] > 50, year
    assert year["summaryDisplay"] == "none", "שורת הסיכום אינה מוצגת כשהשלב פתוח"

    for key in ("courses", "days", "lecturers"):
        up = looks[key]
        assert "is-locked" in up["cls"], (key, up["cls"])
        assert up["height"] < 60, f"{key}: שורת 'הבא' אחת, לא פאנל ({up['height']:.0f}px)"
        assert up["foldHeight"] < 1 and up["bodyVisibility"] == "hidden", (key, up)
        # ‏הסיבה נשארת כתובה — היא מה שאומר מה חסר כדי להתקדם.
        assert up["summaryDisplay"] != "none" and up["summaryText"], (key, up)
        assert up["changeDisplay"] == "none", f"{key}: אין 'שינוי' על שלב נעול"
        assert up["border"] != INK[scheme], f"{key}: רק השלב הפעיל ממוסגר בדיו"


def test_the_state_line_is_hidden_but_still_announced(browser, server):
    """‏docs/DESIGN.md: שורת הסיכום מתחת לכותרת מוסרת כשהשלב פתוח.

    ‏היא נשארת ב-DOM עם הטקסט שלה: היא ‎aria-live‎, ובדיקות קיימות קוראות אותה.
    """
    ctx, pg = _page(browser, server)
    try:
        looks = {k: pg.evaluate(LOOK, k) for k in STEPPER}
    finally:
        ctx.close()
    for key, look in looks.items():
        assert look["stateWidth"] <= 1, f"{key}: שורת המצב עדיין נראית"
        assert look["stateText"], f"{key}: שורת המצב התרוקנה"


# --------------------------------------------------------------------------
# 2. שורת "הושלם", ו"שינוי" שפותח אותה חזרה
# --------------------------------------------------------------------------
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_a_collapsed_step_is_one_completed_line_and_reopens(browser, server, scheme):
    ctx, pg = _page(browser, server, scheme=scheme)
    try:
        _identity_and_courses(pg)
        if "is-collapsed" not in pg.evaluate(LOOK, "year")["cls"]:
            pg.click("#step-year-toggle")
        pg.wait_for_timeout(700)
        closed = pg.evaluate(LOOK, "year")
        pg.click("#step-year-toggle")
        pg.wait_for_timeout(700)
        opened = pg.evaluate(LOOK, "year")
        expanded = pg.get_attribute("#step-year-toggle", "aria-expanded")
    finally:
        ctx.close()

    assert "is-complete" in closed["cls"], closed["cls"]
    assert closed["height"] < 60, f"שורה אחת, לא פאנל ({closed['height']:.0f}px)"
    assert closed["bodyVisibility"] == "hidden" and closed["foldHeight"] < 1, closed
    assert closed["summaryDisplay"] != "none" and closed["summaryText"], closed
    assert closed["changeDisplay"] != "none" and closed["changeText"] == "שינוי", closed
    assert closed["hintDisplay"] == "none", "שורה אחת — בלי שורת עזר"
    assert closed["nameColor"] == SEC[scheme], "שם השלב ב-‎--sec‎"
    assert closed["dotBg"] == INK[scheme], "‏✓ על רקע דיו"

    assert opened["bodyVisibility"] == "visible" and opened["foldHeight"] > 50, opened
    assert opened["summaryDisplay"] == "none" and opened["changeDisplay"] == "none", opened
    assert expanded == "true"


def test_a_closed_body_is_out_of_the_tab_order(browser, server):
    """‏‎display: none‎ הוציא אותו מסדר ה-Tab. גובה אפס לבדו לא היה מוציא."""
    ctx, pg = _page(browser, server)
    try:
        _identity_and_courses(pg)
        if "is-collapsed" not in pg.evaluate(LOOK, "year")["cls"]:
            pg.click("#step-year-toggle")
        pg.wait_for_timeout(700)
        got = pg.evaluate(
            """() => { const e = document.getElementById('select-program');
                       e.focus(); return document.activeElement === e; }""")
    finally:
        ctx.close()
    assert got is False, "פקד בתוך שלב סגור עדיין מקבל מיקוד"


# --------------------------------------------------------------------------
# 3. תנועה: רק אחרי פעולה, 350ms, ובלי תנועה כשביקשו פחות
# --------------------------------------------------------------------------
FOLD = """() => { const f = document.querySelector('#step-year .step-fold');
                  const cs = getComputedStyle(f);
                  return {prop: cs.transitionProperty, dur: cs.transitionDuration,
                          ease: cs.transitionTimingFunction,
                          h: f.getBoundingClientRect().height}; }"""


def test_nothing_animates_before_the_user_acts(browser, server):
    """עיקרון 3: תנועה מסבירה פעולה. קיפול בטעינה אינו פעולה של אף אחד."""
    ctx, pg = _page(browser, server)
    try:
        before = pg.evaluate(FOLD)
    finally:
        ctx.close()
    assert before["dur"] in ("0s", ""), before


def test_opening_and_closing_animate_the_height(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _identity_and_courses(pg)
        if "is-collapsed" in pg.evaluate(LOOK, "year")["cls"]:
            pg.click("#step-year-toggle")
            pg.wait_for_timeout(700)
        full = pg.evaluate(FOLD)
        # ‏עד 2026-09-24 כאן היה ‎wait_for_timeout(120)‎ ואז מדידה — מרוץ מול
        # השעון, שתחת עומס דגם אחרי סוף האנימציה וקרא 0. ‏setState מצייר
        # סינכרונית, ולכן המעבר קיים ברגע שהלחיצה חוזרת: עוצרים אותו,
        # מזיזים ל-120ms בדיוק, מודדים, וממשיכים. (תוקן באישור.)
        mid = pg.evaluate(
            """() => {
              const fold = document.querySelector('#step-year .step-fold');
              document.getElementById('step-year-toggle').click();
              getComputedStyle(fold).gridTemplateRows;  // מוודא שהמעבר נוצר
              const t = fold.getAnimations().find(
                a => a.transitionProperty === 'grid-template-rows');
              if (!t) return {h: null};
              t.pause();
              t.currentTime = 120;
              const h = fold.getBoundingClientRect().height;
              t.play();
              return {h};
            }""")
        pg.wait_for_timeout(700)
        end = pg.evaluate(FOLD)
    finally:
        ctx.close()
    assert "grid-template-rows" in full["prop"], full
    assert "0.35s" in full["dur"], full
    assert "cubic-bezier(0.2, 0.8, 0.2, 1)" in full["ease"], full
    assert 0 < mid["h"] < full["h"], f"באמצע הסגירה הגובה אמור להיות בין 0 ל-{full['h']}: {mid}"
    assert end["h"] < 1, end


def test_reduced_motion_makes_it_instant(browser, server):
    ctx, pg = _page(browser, server, reduced=True)
    try:
        _identity_and_courses(pg)
        if "is-collapsed" in pg.evaluate(LOOK, "year")["cls"]:
            pg.click("#step-year-toggle")
            pg.wait_for_timeout(300)
        pg.click("#step-year-toggle")
        pg.wait_for_timeout(50)
        got = pg.evaluate(FOLD)
        hidden = pg.evaluate(LOOK, "year")["bodyVisibility"]
    finally:
        ctx.close()
    assert got["h"] < 1, f"עם prefers-reduced-motion הסגירה אמורה להיות מיידית: {got}"
    assert hidden == "hidden"


# --------------------------------------------------------------------------
# 4. טלפון: העטיפה החדשה לא מרחיבה את העמוד
# --------------------------------------------------------------------------
def test_phone_page_is_not_wider_than_the_screen(browser, server):
    """‏עמודת grid גדלה לפי התוכן כברירת מחדל. בלי ‎minmax(0, 1fr)‎ טבלת המרצים
    דחפה את העמוד ל-821px במסך של 390px — והמסך נראה ריק."""
    ctx, pg = _page(browser, server, width=390)
    try:
        _identity_and_courses(pg)
        width = pg.evaluate("() => document.documentElement.scrollWidth")
    finally:
        ctx.close()
    assert width <= 390, f"העמוד ברוחב {width}px במסך של 390px"
