"""שלב 7 של העיצוב מחדש, חלק א׳: הפריסה הרחבה (docs/DESIGN.md, "Layout", 2026-10-03).

מה נבדק כאן
-----------
* **מ-1200px ומעלה, זה לצד זה:** השלבים בצד ההתחלה (ימין), המערכת בשאר הרוחב.
  ב-1199 — עמודה אחת, כמו קודם.
* **עמודת המערכת דביקה ובגובה המסך בדיוק,** גם אחרי שגוללים את השלבים.
* **מה שאינו מוצג במסך רחב:** כפתור הבנייה, הסרגל המצוף ושורת ההגדרות. ב-1000
  שלושתם עדיין שם.
* **צעד 1 של סדר ההתאמה:** ליום ו׳ ריק אין עמודה, וכותרת הימים היא שורה אחת.
* **צעד 4:** ב-1440x650 הרשת נגללת בתוך התיבה שלה, שורת הימים נשארת נעוצה,
  והיא נפתחת על השיעור הראשון.
* **פרטי השיעור במקום המקרא:** פתיחה אינה משנה את ‎--slot-h‎ ואינה מזיזה בלוק.
* **השכבה "הצג מערכת" נסגרת כשהחלון מתרחב,** והפוקוס אינו נופל ל-body.
* **"מעדכן…"** ליד "5 מערכות מובילות" בזמן חישוב.
* **לפני שנבחר קורס:** שבוע ריק ושורה אחת.
* **הדפסה מחלון של 1440x650:** כל בלוק בשלוש שורות, ושום דבר אינו חתוך —
  הפריסה הרחבה אינה מגיעה לנייר.

הבחירה: הנדסת תוכנה, שנה ג', סמסטר א', ששת הקורסים המומלצים — כמו
‏test_results_page_browser.py. הציפיות אינן תלויות בנתונים: כל מספר נגזר ממה
שהדף מציג בפועל.
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

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import create_app  # noqa: E402

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))

WIDE = 1440
NARROW = 1000


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
            instance = pw.chromium.launch()
        except Exception as exc:  # אין דפדפן מותקן — לא כישלון של הקוד
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            yield instance
        finally:
            instance.close()


def _new_page(browser, width, height):
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme="light")
    page = ctx.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    return ctx, page


def _open_semester_5(browser, server, width=WIDE, height=900):
    ctx, page = _new_page(browser, width, height)
    page.goto(server)
    page.wait_for_timeout(2500)
    page.select_option("#select-program", "הנדסת תוכנה")
    page.select_option("#select-year", "3")
    page.select_option("#select-term", "א")
    page.wait_for_timeout(2500)
    page.click("#step-year-next")  # "המשך" אל שלב הקורסים (Phase 8, באישור 2026-10-06)
    # ‏מחכים ששלב הקורסים יסיים להיפתח לפני הלחיצה הבאה: באמצע הפתיחה
    # ‏Playwright גולל בעצמו אל הכפתור החשוף-למחצה, והעמוד נשאר גלול
    # ‏(באישור 2026-10-07).
    page.wait_for_function(
        """() => { const s = document.getElementById('step-courses');
                   const fold = s.querySelector('.step-fold');
                   return s.classList.contains('is-active') && !s.classList.contains('is-locked')
                     && fold.getAnimations().length === 0
                     && getComputedStyle(fold.firstElementChild).visibility === 'visible'
                     && fold.getBoundingClientRect().height > 0; }""",
        timeout=5000,
    )
    page.click("#btn-restore-recommended")
    page.wait_for_selector("#schedule-grid .ev", timeout=20000)
    _settle(page)
    return ctx, page


def _settle(page):
    page.wait_for_function(
        "() => !!document.getElementById('schedule-grid').style.getPropertyValue('--slot-h')",
        timeout=15000,
    )
    page.wait_for_timeout(700)


@pytest.fixture(scope="module")
def wide(browser, server):
    """דף אחד ב-1440x900, לבדיקות שרק קוראות."""
    ctx, pg = _open_semester_5(browser, server)
    try:
        yield pg
    finally:
        ctx.close()


RECT = """(sel) => { const e = document.querySelector(sel); if (!e) return null;
  const r = e.getBoundingClientRect();
  return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height,
          display: getComputedStyle(e).display, visibility: getComputedStyle(e).visibility}; }"""


def _rect(page, sel):
    return page.evaluate(RECT, sel)


def _shown(page, sel):
    """מוצג באמת: לא display:none, לא visibility:hidden, ובעל שטח."""
    r = _rect(page, sel)
    return bool(r) and r["display"] != "none" and r["visibility"] != "hidden" and r["width"] > 0 and r["height"] > 0


# ==========================================================================
# 1. זה לצד זה, ועמודה אחת מתחת ל-1200
# ==========================================================================
def test_side_by_side_at_1440(wide):
    steps = _rect(wide, "#step-year")
    sched = _rect(wide, "#step-schedule")
    # ‏RTL: השלבים בצד ההתחלה — מימין — והמערכת משמאלם.
    assert sched["right"] <= steps["left"], (steps, sched)
    assert abs(steps["top"] - sched["top"]) < 2, (steps, sched)
    assert 380 <= steps["width"] <= 420, steps
    assert sched["width"] > steps["width"], (steps, sched)
    for sel in ("#step-courses", "#step-days", "#step-lecturers"):
        r = _rect(wide, sel)
        assert abs(r["left"] - steps["left"]) < 1 and abs(r["width"] - steps["width"]) < 1, (sel, r)
    assert wide.errors == []  # type: ignore[attr-defined]


def test_one_column_at_1199(browser, server):
    ctx, pg = _open_semester_5(browser, server, width=1199)
    try:
        lect = _rect(pg, "#step-lecturers")
        sched = _rect(pg, "#step-schedule")
        year = _rect(pg, "#step-year")
        assert sched["top"] >= lect["bottom"], (lect, sched)
        assert abs(sched["width"] - year["width"]) < 1, (year, sched)
        assert pg.evaluate("getComputedStyle(document.getElementById('step-schedule')).position") == "static"
        # כותרת השלב עדיין מוצגת בעמודה אחת.
        assert _shown(pg, "#step-schedule-title")
    finally:
        ctx.close()


def test_the_timetable_column_is_one_viewport_tall_and_stays_in_view(browser, server):
    ctx, pg = _open_semester_5(browser, server, width=WIDE, height=900)
    try:
        assert _rect(pg, "#step-schedule")["height"] == pytest.approx(900, abs=1)
        # ‏Phase 8 (באישור 2026-10-07): שלב אחד פתוח, ולכן העמוד קצר יותר
        # ‏מכשכל השלבים היו פרוסים. גוללים עד הסוף, ודורשים 600px לפחות.
        doc = pg.evaluate("document.documentElement.scrollHeight")
        far = pg.evaluate("document.documentElement.scrollHeight - window.innerHeight")
        assert far >= 600, f"העמוד קצר מכדי לגלול את השלבים: {doc}"
        pg.evaluate("(y) => window.scrollTo(0, y)", far)
        pg.wait_for_timeout(300)
        assert pg.evaluate("window.scrollY") == pytest.approx(far, abs=1)
        sched = _rect(pg, "#step-schedule")
        assert sched["top"] == pytest.approx(0, abs=1), sched
        assert sched["bottom"] == pytest.approx(900, abs=1), sched
        # הרשת עצמה בתוך המסך, והשלבים נגללו.
        grid = _rect(pg, "#grid-scroll")
        assert 0 <= grid["top"] and grid["bottom"] <= 900, grid
        assert _rect(pg, "#step-year")["bottom"] < 0
        # הכותרת אינה דביקה במסך רחב: היא נגללה מהמסך.
        assert _rect(pg, "#app-header")["bottom"] <= 0
    finally:
        ctx.close()


def test_the_step_heading_is_not_shown_but_stays_for_screen_readers(wide):
    head = _rect(wide, "#step-schedule > .step-head")
    assert head["width"] <= 1 and head["height"] <= 1, head
    assert wide.evaluate("document.getElementById('step-schedule-title').textContent.trim()") == (
        STRINGS["ui"]["steps"]["scheduleTitle"]
    )


# ==========================================================================
# 2. מה שאינו מוצג במסך רחב
# ==========================================================================
def test_build_button_bottom_bar_and_settings_pills_are_hidden_at_1440(wide):
    wide.evaluate("window.scrollTo(0, 1500)")
    wide.wait_for_timeout(400)
    try:
        # ‏Phase 8: ‏#sticky-bar הוסר; הסרגל התחתון במקומו (באישור 2026-10-08).
        for sel in ("#build-row", "#bottom-bar", "#settings-pills"):
            assert _rect(wide, sel)["display"] == "none", sel
    finally:
        wide.evaluate("window.scrollTo(0, 0)")
        wide.wait_for_timeout(200)


def test_build_button_bottom_bar_and_settings_pills_are_visible_at_1000(browser, server):
    ctx, pg = _open_semester_5(browser, server, width=NARROW, height=900)
    try:
        assert _shown(pg, "#build-row")
        assert _shown(pg, "#btn-build")
        assert _shown(pg, "#settings-pills")
        # ‏הסרגל התחתון מופיע אחרי הגלילה, כשהכפתור שבעמוד והתוצאה מחוץ
        # ‏למסך (Phase 8: במקום הסרגל המצוף, באישור 2026-10-08).
        below = pg.evaluate("document.getElementById('step-year').getBoundingClientRect().bottom + window.scrollY + 20")
        pg.evaluate(f"window.scrollTo(0, {below})")
        pg.wait_for_function(
            "() => document.getElementById('bottom-bar').classList.contains('is-visible')", timeout=5000
        )
        pg.wait_for_timeout(400)
        assert _shown(pg, "#bottom-bar")
        assert _shown(pg, "#btn-bottom-build")
    finally:
        ctx.close()


# ==========================================================================
# 3. סדר ההתאמה: צעד 1 וצעד 4
# ==========================================================================
def test_an_empty_friday_has_no_column_and_the_day_row_is_one_line(wide):
    got = wide.evaluate(
        """() => {
          const heads = [...document.querySelectorAll('#schedule-grid .hd')];
          const fri = heads[6];
          const shown = heads.filter(h => getComputedStyle(h).display !== 'none');
          const lh = parseFloat(getComputedStyle(shown[1]).lineHeight) || 20;
          return {friEmpty: fri.classList.contains('is-empty'),
                  friShown: getComputedStyle(fri).display !== 'none',
                  friCells: [...document.querySelectorAll('#schedule-grid .slot.is-fri')]
                              .filter(s => getComputedStyle(s).display !== 'none').length,
                  heights: shown.map(h => {
                    const cs = getComputedStyle(h);
                    return h.getBoundingClientRect().height - parseFloat(cs.paddingTop)
                           - parseFloat(cs.paddingBottom) - parseFloat(cs.borderBottomWidth); }),
                  lh: lh,
                  gridRight: document.getElementById('schedule-grid').getBoundingClientRect().left,
                  thursdayLeft: heads[5].getBoundingClientRect().left};
        }"""
    )
    if not got["friEmpty"]:
        pytest.skip("במערכת הזו יש שיעורים ביום ו׳")
    assert not got["friShown"] and got["friCells"] == 0, got
    # יום ה׳ הוא העמודה האחרונה: אין רצועה ריקה אחריו.
    assert got["thursdayLeft"] - got["gridRight"] < 2, got
    assert all(h <= got["lh"] * 1.5 for h in got["heights"]), got


def test_an_empty_friday_keeps_its_narrow_column_at_1000(browser, server):
    ctx, pg = _open_semester_5(browser, server, width=NARROW)
    try:
        got = pg.evaluate(
            """() => { const fri = document.querySelectorAll('#schedule-grid .hd')[6];
                       return {empty: fri.classList.contains('is-empty'),
                               width: fri.getBoundingClientRect().width,
                               label: getComputedStyle(fri.querySelector('.hd-empty') || fri).display}; }"""
        )
        if not got["empty"]:
            pytest.skip("במערכת הזו יש שיעורים ביום ו׳")
        assert got["width"] > 20 and got["label"] != "none", got
    finally:
        ctx.close()


def test_a_short_window_scrolls_the_grid_inside_with_the_day_row_pinned(browser, server):
    ctx, pg = _open_semester_5(browser, server, width=WIDE, height=650)
    try:
        assert _rect(pg, "#step-schedule")["height"] == pytest.approx(650, abs=1)
        got = pg.evaluate(
            """() => { const b = document.getElementById('grid-scroll');
                       return {sh: b.scrollHeight, ch: b.clientHeight, top: b.scrollTop,
                               oy: getComputedStyle(b).overflowY}; }"""
        )
        assert got["oy"] == "auto" and got["sh"] > got["ch"] + 50, got
        # נפתחת על השיעור הראשון: הבלוק המוקדם ביותר גלוי מתחת לשורת הימים.
        first = pg.evaluate(
            """() => { const box = document.getElementById('grid-scroll').getBoundingClientRect();
                       const hd = document.querySelector('#schedule-grid .hd').getBoundingClientRect();
                       const evs = [...document.querySelectorAll('#schedule-grid .ev')]
                         .map(e => e.getBoundingClientRect()).sort((a, b) => a.top - b.top);
                       return {top: evs[0].top, hdBottom: hd.bottom, boxBottom: box.bottom}; }"""
        )
        assert first["hdBottom"] - 1 <= first["top"] < first["boxBottom"], first
        # שלוש שורות בכל בלוק — גובה השעה נשאר מהתוכן.
        over = pg.evaluate(
            "[...document.querySelectorAll('#schedule-grid .ev')].filter(e => e.scrollHeight > e.clientHeight).length"
        )
        assert over == 0
        # גלילה בתוך התיבה: שורת הימים נשארת בראשה, והעמוד עצמו לא זז.
        before = pg.evaluate("window.scrollY")
        pg.evaluate("document.getElementById('grid-scroll').scrollTop = 300")
        pg.wait_for_timeout(200)
        pinned = pg.evaluate(
            """() => { const box = document.getElementById('grid-scroll');
                       const hd = document.querySelector('#schedule-grid .hd');
                       return {scrolled: box.scrollTop,
                               boxTop: box.getBoundingClientRect().top + box.clientTop,
                               hdTop: hd.getBoundingClientRect().top}; }"""
        )
        assert pinned["scrolled"] > 0, pinned
        assert abs(pinned["hdTop"] - pinned["boxTop"]) < 1.5, pinned
        assert pg.evaluate("window.scrollY") == before
    finally:
        ctx.close()


# ==========================================================================
# 4. פרטי השיעור במקום המקרא
# ==========================================================================
LAYOUT = """() => ({
  slot: document.getElementById('schedule-grid').style.getPropertyValue('--slot-h'),
  grid: (r => [r.top, r.height])(document.getElementById('grid-scroll').getBoundingClientRect()),
  blocks: [...document.querySelectorAll('#schedule-grid .ev')].map(e => {
    const r = e.getBoundingClientRect();
    return [Math.round(r.left * 10) / 10, Math.round(r.top * 10) / 10,
            Math.round(r.width * 10) / 10, Math.round(r.height * 10) / 10]; })
})"""


def test_opening_the_details_moves_nothing(browser, server):
    ctx, pg = _open_semester_5(browser, server, width=WIDE, height=900)
    try:
        pg.evaluate("window.scrollTo(0, 2000)")
        pg.wait_for_timeout(400)
        before = pg.evaluate(LAYOUT)
        tools = _rect(pg, ".grid-tools")
        pg.evaluate("document.querySelector('#schedule-grid .ev').click()")
        pg.wait_for_timeout(600)
        assert pg.evaluate("!document.getElementById('meeting-detail').hidden")
        after = pg.evaluate(LAYOUT)
        assert after == before, (before, after)
        detail = _rect(pg, "#meeting-detail")
        # במקום המקרא ובגובה שלו.
        assert detail["top"] == pytest.approx(tools["top"], abs=1), (detail, tools)
        assert detail["height"] == pytest.approx(tools["height"], abs=1), (detail, tools)
        assert _rect(pg, ".grid-tools")["height"] == pytest.approx(tools["height"], abs=0.5)
        assert _rect(pg, ".grid-tools-main")["visibility"] == "hidden"
        # השדות זה לצד זה: כל התוויות באותה שורה.
        tops = pg.evaluate(
            "[...document.querySelectorAll('#meeting-detail .detail-list dt')].map(d => Math.round(d.getBoundingClientRect().top))"
        )
        assert len(tops) >= 4 and len(set(tops)) == 1, tops
        # התוכן כולו בתוך הפאנל, בלי גלילה.
        fits = pg.evaluate(
            "(e => e.scrollHeight <= e.clientHeight + 1)(document.getElementById('meeting-detail'))"
        )
        assert fits
        # סגירה מחזירה את המקרא, ושוב שום דבר לא זז.
        pg.click("#btn-detail-close")
        pg.wait_for_timeout(400)
        assert pg.evaluate("document.getElementById('meeting-detail').hidden")
        assert _rect(pg, ".grid-tools-main")["visibility"] == "visible"
        assert pg.evaluate(LAYOUT) == before
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


# ==========================================================================
# 5. הסרגל התחתון נעלם כשהחלון מתרחב
# ==========================================================================
# ‏Phase 8: השכבה "הצג מערכת" הוסרה; אותה התנהגות — נעלם ברחב, והפוקוס
# ‏אינו נופל ל-body — נבדקת על הסרגל התחתון (באישור 2026-10-08).
def test_the_bottom_bar_goes_away_when_the_window_widens(browser, server):
    ctx, pg = _open_semester_5(browser, server, width=NARROW, height=900)
    try:
        below = pg.evaluate("document.getElementById('step-year').getBoundingClientRect().bottom + window.scrollY + 20")
        pg.evaluate(f"window.scrollTo(0, {below})")
        pg.wait_for_function(
            "() => document.getElementById('bottom-bar').classList.contains('is-visible')", timeout=5000
        )
        pg.wait_for_timeout(300)
        pg.focus("#btn-bottom-build")
        pg.wait_for_timeout(100)
        assert pg.evaluate("document.activeElement.id") == "btn-bottom-build"
        pg.set_viewport_size({"width": WIDE, "height": 900})
        pg.wait_for_timeout(600)
        got = pg.evaluate(
            """() => ({hidden: !document.getElementById('bottom-bar').classList.contains('is-visible'),
                       padded: document.body.classList.contains('has-bottom-bar'),
                       focus: document.activeElement ? (document.activeElement.id || document.activeElement.tagName) : null})"""
        )
        assert got["hidden"] and not got["padded"], got
        assert got["focus"] not in (None, "BODY", "HTML"), got
        assert _shown(pg, "#" + got["focus"]), got
    finally:
        ctx.close()


# ==========================================================================
# 6. "מעדכן…" בזמן חישוב
# ==========================================================================
def test_updating_shows_next_to_the_title_while_a_solve_runs(browser, server):
    ctx, pg = _open_semester_5(browser, server, width=WIDE)
    try:
        running = pg.evaluate(
            """() => { window.slotwise.solveNow();
                       const u = document.getElementById('alt-updating');
                       return {hidden: u.hidden, display: getComputedStyle(u).display, text: u.textContent.trim(),
                               color: getComputedStyle(u).color,
                               mut: (() => { const p = document.createElement('span');
                                             p.style.color = 'var(--mut)'; document.body.appendChild(p);
                                             const c = getComputedStyle(p).color; p.remove(); return c; })(),
                               sameRow: Math.abs(u.getBoundingClientRect().top
                                        - document.getElementById('alt-title').getBoundingClientRect().top) < 12}; }"""
        )
        assert running["text"] == STRINGS["app"]["alts"]["updating"], running
        assert not running["hidden"] and running["display"] != "none", running
        assert running["color"] == running["mut"], running
        assert running["sameRow"], running
        pg.wait_for_function("() => !window.slotwise.getRuntime().solveBusy", timeout=20000)
        pg.wait_for_timeout(200)
        assert pg.evaluate("document.getElementById('alt-updating').hidden")
    finally:
        ctx.close()


# ==========================================================================
# 7. לפני שנבחר קורס: שבוע ריק ושורה אחת
# ==========================================================================
def test_before_any_course_the_column_shows_an_empty_week_and_one_line(browser, server):
    ctx, pg = _new_page(browser, WIDE, 900)
    try:
        pg.goto(server)
        pg.wait_for_timeout(2500)
        assert pg.evaluate("window.slotwise.getState().codes.length") == 0
        got = pg.evaluate(
            """() => ({line: document.querySelector('#schedule-placeholder .week-empty-line').textContent.trim(),
                       days: [...document.querySelectorAll('#schedule-placeholder .week-empty-hd')].map(d => d.textContent.trim()),
                       note: getComputedStyle(document.getElementById('schedule-note')).display})"""
        )
        assert _shown(pg, "#schedule-placeholder")
        assert got["line"] == STRINGS["app"]["schedule"]["emptyWeek"], got
        letters = STRINGS["app"]["terms"]["dayLetters"]
        want = [STRINGS["app"]["grid"]["dayHeader"].replace("{day}", letters[str(d)]) for d in range(1, 6)]
        assert got["days"] == want, got
        assert got["note"] == "none", got
        # במסך צר: בלי שינוי.
        pg.set_viewport_size({"width": NARROW, "height": 900})
        pg.wait_for_timeout(300)
        assert not _shown(pg, "#schedule-placeholder")
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_the_empty_week_goes_away_once_there_is_a_schedule(wide):
    assert wide.evaluate("document.getElementById('schedule-placeholder').hidden")


# ==========================================================================
# 8. הדפסה מחלון רחב ונמוך
# ==========================================================================
BLOCK_LINES = """() => {
  const box = document.getElementById('grid-scroll').getBoundingClientRect();
  return [...document.querySelectorAll('#schedule-grid .ev')].map(e => {
    const cs = getComputedStyle(e);
    const r = e.getBoundingClientRect();
    const top = r.top + parseFloat(cs.borderTopWidth) + parseFloat(cs.paddingTop);
    const bottom = r.bottom - parseFloat(cs.borderBottomWidth) - parseFloat(cs.paddingBottom);
    const lines = [...e.querySelectorAll(':scope > .ev-line')].map(l => {
      const lr = l.getBoundingClientRect();
      return {shown: getComputedStyle(l).display !== 'none' && lr.height > 0 && !!l.textContent.trim(),
              inside: lr.top >= top - 0.5 && lr.bottom <= bottom + 0.5,
              wide: l.scrollWidth > l.clientWidth + 1};
    });
    return {name: (e.querySelector('b') || {}).textContent || '',
            overflow: e.scrollHeight - e.clientHeight,
            inBox: r.top >= box.top - 0.5 && r.bottom <= box.bottom + 0.5
                   && r.left >= box.left - 0.5 && r.right <= box.right + 0.5,
            lines: lines};
  });
}"""


def test_print_from_a_short_wide_window_keeps_every_block_whole(browser, server):
    ctx, pg = _open_semester_5(browser, server, width=WIDE, height=650)
    try:
        # על המסך הרשת נגללת — זה החלון שבו המסך מקצר.
        assert pg.evaluate(
            "(b => b.scrollHeight > b.clientHeight)(document.getElementById('grid-scroll'))"
        )
        pg.evaluate("document.getElementById('grid-scroll').scrollTop = 200")
        pg.emulate_media(media="print")
        pg.wait_for_timeout(1000)
        box = pg.evaluate(
            """() => { const b = document.getElementById('grid-scroll'); const cs = getComputedStyle(b);
                       const s = document.getElementById('step-schedule');
                       return {sh: b.scrollHeight, ch: b.clientHeight, oy: cs.overflowY,
                               position: getComputedStyle(s).position,
                               height: getComputedStyle(s).height,
                               steps: getComputedStyle(document.getElementById('steps')).display}; }"""
        )
        assert box["oy"] == "visible" and box["sh"] <= box["ch"] + 1, box
        assert box["position"] == "static" and box["steps"] == "flex", box
        blocks = pg.evaluate(BLOCK_LINES)
        assert blocks
        bad = []
        for b in blocks:
            if b["overflow"] > 0:
                bad.append(f"{b['name']}: גולש ב-{b['overflow']}px")
            if not b["inBox"]:
                bad.append(f"{b['name']}: מחוץ לרשת")
            if len(b["lines"]) != 3:
                bad.append(f"{b['name']}: {len(b['lines'])} שורות")
            for line in b["lines"]:
                if not (line["shown"] and line["inside"] and not line["wide"]):
                    bad.append(f"{b['name']}: {line}")
        assert not bad, " | ".join(bad)
        # יום ו׳ על הנייר כמו קודם: אין כאן כלל רחב שמסתיר אותו.
        fri = pg.evaluate(
            "(h => h ? getComputedStyle(h).display : null)(document.querySelector('#schedule-grid .hd.is-fri'))"
        )
        assert fri in (None, "block"), fri
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()
