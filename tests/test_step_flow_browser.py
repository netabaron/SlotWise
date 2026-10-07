"""שלב 8 של העיצוב, חלק א': זרימת השלבים (docs/DESIGN.md, "General step
behaviour" — ‏Flow ו-"Completion is remembered", ו-"Scroll behaviour", 2).

מה נבדק כאן: שלב אחד פתוח, הבאים נעולים, ושלב מושלם רק אחרי "המשך" —
לעולם לא מערכים תקינים לבדם. "שינוי" פותח שלב שהושלם. ה"המשך" האחרון
גולל אל התוצאה בצר ואינו מזיז דבר ברחב. ההשלמה נשמרת תחת אותו מפתח
‏localStorage, ושלב שנשמר והערכים בו כבר אינם תקינים נפתח שוב. והמערכת
ממשיכה להיבנות מחדש בכל שינוי, בלי קשר למצב השלבים.

רץ על מסד ה-fixture (‏``scripts/seed_dev_data.py --fixture``), כמו ב-CI.
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

STEPS = ("year", "courses", "days", "lecturers")
#: ‏app.js:133. המפתח אינו משתנה עם השם SlotWise — ראו CLAUDE.md.
STORAGE_KEY = "braude_schedule_builder_v1"


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


def _page(browser, server, *, width=1280, height=900, reduced=True):
    # ‏בלי תנועה כברירת מחדל: הבדיקות כאן על מצב ועל מיקום, לא על אנימציה,
    # ‏וגלילה חלקה הייתה הופכת כל מדידת מיקום למרוץ מול השעון.
    ctx = browser.new_context(
        viewport={"width": width, "height": height},
        color_scheme="light",
        reduced_motion="reduce" if reduced else "no-preference",
    )
    pg = ctx.new_page()
    pg.goto(server)
    pg.wait_for_timeout(3500)
    return ctx, pg


def _identity(pg):
    pg.select_option("#select-program", "הנדסת תוכנה")
    pg.select_option("#select-year", "3")
    pg.select_option("#select-term", "א")
    pg.wait_for_timeout(2500)


def _next(pg, key, wait=1200):
    pg.click(f"#step-{key}-next")
    pg.wait_for_timeout(wait)


def _through_courses(pg):
    _identity(pg)
    _next(pg, "year")
    pg.click("#btn-restore-recommended")
    pg.wait_for_timeout(4000)
    _next(pg, "courses")


STATUS = """() => ['year', 'courses', 'days', 'lecturers'].map(k => {
  const s = document.getElementById('step-' + k);
  const t = document.getElementById('step-' + k + '-toggle');
  const body = document.getElementById('step-' + k + '-body');
  return {
    key: k,
    open: s.classList.contains('is-active') && !s.classList.contains('is-collapsed')
          && !s.classList.contains('is-locked'),
    complete: s.classList.contains('is-complete') && s.classList.contains('is-collapsed'),
    locked: s.classList.contains('is-locked'),
    visible: getComputedStyle(body).visibility === 'visible',
    expanded: t.getAttribute('aria-expanded'),
    ariaDisabled: t.getAttribute('aria-disabled'),
    tabindex: t.getAttribute('tabindex'),
  };
})"""


def _status(pg):
    return {s["key"]: s for s in pg.evaluate(STATUS)}


def _shape(pg):
    """‏"open" / "complete" / "locked" לכל שלב, לפי הסדר."""
    out = []
    for key, s in _status(pg).items():
        kinds = [k for k in ("open", "complete", "locked") if s[k]]
        assert len(kinds) == 1, f"{key}: מצב לא חד-משמעי {s}"
        out.append(kinds[0])
    return out


#: ‏תחתית מה שמכסה את ראש המסך: הכותרת כשהיא דביקה, והסרגל המצוף כשהוא
#: ‏מוצג. שלב שנגלל "אל מתחת לכותרת" מתחיל שם.
COVER = """() => {
  let bottom = 0;
  const h = document.getElementById('app-header');
  const hp = getComputedStyle(h).position;
  if (hp === 'sticky' || hp === 'fixed') bottom = Math.max(bottom, h.getBoundingClientRect().bottom);
  const bar = document.getElementById('sticky-bar');
  if (bar && bar.classList.contains('is-visible') && getComputedStyle(bar).display !== 'none') {
    bottom = Math.max(bottom, bar.getBoundingClientRect().bottom);
  }
  return bottom;
}"""


def _saved(pg):
    raw = pg.evaluate(f"() => localStorage.getItem({json.dumps(STORAGE_KEY)})")
    return json.loads(raw) if raw else {}


# --------------------------------------------------------------------------
# 1. ביקור ראשון
# --------------------------------------------------------------------------
def test_fresh_visit_opens_only_step_one_and_locks_the_rest(browser, server):
    ctx, pg = _page(browser, server)
    try:
        status = _status(pg)
        shape = _shape(pg)
        # ‏Tab מתחילת העמוד לעולם לא נוחת על כותרת של שלב נעול.
        landed = []
        pg.evaluate("() => document.activeElement && document.activeElement.blur()")
        for _ in range(60):
            pg.keyboard.press("Tab")
            landed.append(pg.evaluate("() => document.activeElement && document.activeElement.id"))
        pg.click("#step-days-toggle", force=True)
        pg.wait_for_timeout(300)
        after_click = _shape(pg)
    finally:
        ctx.close()
    assert shape == ["open", "locked", "locked", "locked"], shape
    assert status["year"]["visible"] and status["year"]["expanded"] == "true"
    for key in ("courses", "days", "lecturers"):
        s = status[key]
        assert not s["visible"], f"{key}: גוף של שלב נעול נראה"
        assert s["ariaDisabled"] == "true" and s["tabindex"] == "-1", (key, s)
        assert s["expanded"] == "false", (key, s)
        assert f"step-{key}-toggle" not in landed, f"Tab נחת על כותרת השלב הנעול {key}"
    assert after_click == shape, "לחיצה על שלב נעול פתחה אותו"


def test_the_next_button_is_the_strings_json_copy(browser, server):
    strings = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
    ctx, pg = _page(browser, server)
    try:
        texts = [pg.text_content(f"#step-{k}-next").strip() for k in STEPS]
    finally:
        ctx.close()
    assert texts == [strings["ui"]["steps"]["next"]] * 4 == ["המשך"] * 4, texts


# --------------------------------------------------------------------------
# 2. ערכים תקינים לבדם אינם משלימים שלב
# --------------------------------------------------------------------------
def test_valid_values_alone_never_complete_a_step(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _identity(pg)
        after_identity = _shape(pg)
        enabled = pg.evaluate("() => !document.getElementById('step-year-next').disabled")
        # ‏מצב מלא ותקין — זהות, קורסים, יעד ימים — בלי ``completed``, ואחרי
        # טעינה מחדש: עדיין רק שלב 1 פתוח.
        pg.evaluate(
            """(key) => { const s = JSON.parse(localStorage.getItem(key));
                          s.codes = s.codes.length ? s.codes : ['11069'];
                          s.manualCodes = s.codes.slice(); s.targetDays = 4;
                          delete s.completed;
                          localStorage.setItem(key, JSON.stringify(s)); }""",
            STORAGE_KEY,
        )
        pg.reload()
        pg.wait_for_timeout(4000)
        after_reload = _shape(pg)
        saved = _saved(pg)
    finally:
        ctx.close()
    assert enabled, "‏\"המשך\" של שלב 1 כבוי למרות שהזהות נבחרה"
    assert after_identity == ["open", "locked", "locked", "locked"], after_identity
    assert saved["codes"], "ההכנה לא שמרה קורסים"
    assert after_reload == ["open", "locked", "locked", "locked"], after_reload


def test_next_is_disabled_until_the_step_values_are_valid(browser, server):
    ctx, pg = _page(browser, server)
    try:
        before = pg.evaluate("() => document.getElementById('step-year-next').disabled")
        _identity(pg)
        _next(pg, "year")
        # ‏שלב הקורסים פתוח ועוד לא סומן בו קורס.
        courses_empty = pg.evaluate("() => document.getElementById('step-courses-next').disabled")
    finally:
        ctx.close()
    assert before is True, "אפשר היה להשלים את שלב 1 בלי מסלול, שנה וסמסטר"
    assert courses_empty is True, "אפשר היה להשלים את שלב הקורסים בלי קורס"


# --------------------------------------------------------------------------
# 3. "המשך" ו"שינוי"
# --------------------------------------------------------------------------
def test_next_completes_collapses_and_opens_the_next_step(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _identity(pg)
        _next(pg, "year")
        one = _shape(pg)
        pg.click("#btn-restore-recommended")
        pg.wait_for_timeout(4000)
        _next(pg, "courses")
        two = _shape(pg)
        _next(pg, "days")
        three = _shape(pg)
        status = _status(pg)
        focused = pg.evaluate("() => document.activeElement && document.activeElement.id")
        saved = _saved(pg)
    finally:
        ctx.close()
    assert one == ["complete", "open", "locked", "locked"], one
    assert two == ["complete", "complete", "open", "locked"], two
    assert three == ["complete", "complete", "complete", "open"], three
    assert not status["days"]["visible"] and status["lecturers"]["visible"], status
    assert focused == "step-lecturers-toggle", f"המיקוד אחרי \"המשך\": {focused}"
    assert saved.get("completed") == {"year": True, "courses": True, "days": True}, saved


#: ‏סופר קריאות גלילה של הדף — "לא זז" נמדד כאן, ולא ב-scrollY, כי שלב
#: ‏שמתקפל מקצר את העמוד והדפדפן מצמיד את הגלילה בעצמו.
COUNT_SCROLLS = """() => { window.__scrolls = 0;
  const count = () => { window.__scrolls++; };
  const st = window.scrollTo.bind(window);
  window.scrollTo = function () { count(); return st.apply(null, arguments); };
  const sb = window.scrollBy.bind(window);
  window.scrollBy = function () { count(); return sb.apply(null, arguments); };
  const si = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = function () { count(); return si.apply(this, arguments); }; }"""

#: ‏DESIGN.md, Scroll behaviour 2: שלב שראשו כבר בחלק הזה של המסך, מתחת
#: ‏לכותרת, אינו נגלל (‎STEP_IN_VIEW_FRACTION‎ ב-app.js).
IN_VIEW = 0.4


def test_next_scrolls_an_off_screen_step_below_the_header(browser, server):
    """השלב הבא מחוץ למסך: "המשך" נלחץ בתחתית שלב הקורסים הארוך, ואחרי
    ‏שהוא מתקפל, ראש שלב הימים נמצא מעל המסך. הוא נגלל אל מתחת לכותרת."""
    ctx, pg = _page(browser, server, width=390, height=844)
    try:
        _identity(pg)
        _next(pg, "year")
        pg.click("#btn-restore-recommended")
        pg.wait_for_timeout(4000)
        pg.evaluate(
            "() => document.getElementById('step-courses-next').scrollIntoView({block: 'end'})")
        pg.wait_for_timeout(300)
        pg.evaluate(COUNT_SCROLLS)
        _next(pg, "courses")
        pg.wait_for_timeout(500)
        scrolls = pg.evaluate("() => window.__scrolls")
        top = pg.evaluate("() => document.getElementById('step-days').getBoundingClientRect().top")
        header = pg.evaluate(COVER)
    finally:
        ctx.close()
    assert scrolls >= 1, "השלב הבא היה מחוץ למסך, והעמוד לא נגלל"
    # ‏‎+ 0.4 מסך‎ ולא צמוד לכותרת: הסרגל המצוף (בצר, עד חלק ב') מופיע רק
    # ‏כששלב 1 כולו מעל המסך, והגלילה משאירה לו מקום כשהוא עשוי להופיע.
    assert header - 1 <= top <= header + 844 * IN_VIEW, (
        f"שלב הימים לא נגלל אל מתחת לכותרת: top={top}, header={header}")


@pytest.mark.parametrize("width,height", [(390, 844), (1440, 900)])
def test_next_does_not_move_a_step_that_is_already_in_view(browser, server, width, height):
    """השלב הבא כבר על המסך, מתחת לכותרת: העמוד אינו זז."""
    ctx, pg = _page(browser, server, width=width, height=height)
    try:
        _through_courses(pg)
        pg.evaluate("() => window.scrollTo(0, 0)")
        pg.wait_for_timeout(200)
        pg.evaluate(COUNT_SCROLLS)
        _next(pg, "days")
        pg.wait_for_timeout(500)
        scrolls = pg.evaluate("() => window.__scrolls")
        top = pg.evaluate("() => document.getElementById('step-lecturers').getBoundingClientRect().top")
        header = pg.evaluate(COVER)
    finally:
        ctx.close()
    assert header - 1 <= top <= header + height * IN_VIEW, (
        f"ההכנה לא השאירה את שלב המרצים על המסך: top={top}, header={header}")
    assert scrolls == 0, f"שלב שכבר נראה הזיז את העמוד ({scrolls} קריאות גלילה)"


def test_change_reopens_a_completed_step_in_view_and_outlines_it(browser, server):
    ctx, pg = _page(browser, server, width=390, height=844)
    try:
        _through_courses(pg)
        _next(pg, "days", wait=300)
        pg.click("#step-year-toggle")
        pg.wait_for_timeout(200)
        shape = _shape(pg)
        flashed = pg.evaluate("() => document.getElementById('step-year').classList.contains('is-flash')")
        outline = pg.evaluate("() => getComputedStyle(document.getElementById('step-year')).outlineStyle")
        top = pg.evaluate("() => document.getElementById('step-year').getBoundingClientRect().top")
        header = pg.evaluate(COVER)
        pg.wait_for_timeout(1500)
        later = pg.evaluate("() => document.getElementById('step-year').classList.contains('is-flash')")
        # ‏"המשך" על השלב שנפתח מחדש מחזיר אל השלב הראשון שעוד לא הושלם.
        _next(pg, "year")
        back = _shape(pg)
    finally:
        ctx.close()
    assert shape == ["open", "complete", "complete", "locked"], shape
    assert flashed and outline == "solid", "השלב שנפתח ב\"שינוי\" לא סומן במסגרת"
    assert not later, "המסגרת נשארה"
    assert header - 1 <= top <= header + 844 * IN_VIEW, (
        f"השלב שנפתח אינו על המסך מתחת לכותרת: top={top}, header={header}")
    assert back == ["complete", "complete", "complete", "open"], back


def test_a_reopened_step_can_be_closed_again_from_its_title(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _through_courses(pg)
        pg.click("#step-courses-toggle")
        pg.wait_for_timeout(300)
        reopened = _shape(pg)
        pg.click("#step-courses-toggle")
        pg.wait_for_timeout(300)
        closed = _shape(pg)
    finally:
        ctx.close()
    assert reopened == ["complete", "open", "locked", "locked"], reopened
    assert closed == ["complete", "complete", "open", "locked"], closed


def test_the_lecturers_next_works_with_no_rankings_or_pins(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _through_courses(pg)
        _next(pg, "days")
        empty = pg.evaluate(
            """() => { const s = window.slotwise.getState();
                       return Object.keys(s.ranked).every(k => !s.ranked[k].length)
                           && Object.keys(s.pinned).every(k => !Object.keys(s.pinned[k]).length); }""")
        disabled = pg.evaluate("() => document.getElementById('step-lecturers-next').disabled")
        _next(pg, "lecturers")
        shape = _shape(pg)
        schedule_active = pg.evaluate(
            "() => document.getElementById('step-schedule').classList.contains('is-active')")
    finally:
        ctx.close()
    assert empty, "ההכנה השאירה דירוג או נעיצה"
    assert disabled is False
    assert shape == ["complete"] * 4, shape
    assert schedule_active


# --------------------------------------------------------------------------
# 4. ה"המשך" האחרון: צר גולל אל התוצאה, רחב לא זז
# --------------------------------------------------------------------------
def _last_next(browser, server, width, height):
    ctx, pg = _page(browser, server, width=width, height=height)
    try:
        _through_courses(pg)
        _next(pg, "days")
        # ‏"לא זז" נמדד כקריאות גלילה, לא כ-scrollY: שלב שמתקפל מקצר את
        # ‏העמוד, והדפדפן עצמו מצמיד את הגלילה לגובה החדש.
        pg.evaluate(COUNT_SCROLLS)
        _next(pg, "lecturers")
        pg.wait_for_timeout(500)
        scrolls = pg.evaluate("() => window.__scrolls")
        res_top = pg.evaluate(
            "() => document.getElementById('step-schedule').getBoundingClientRect().top")
        header = pg.evaluate(COVER)
        shape = _shape(pg)
    finally:
        ctx.close()
    return scrolls, res_top, header, shape


def test_on_a_narrow_window_the_last_next_scrolls_to_the_results(browser, server):
    scrolls, res_top, header, shape = _last_next(browser, server, 390, 844)
    assert shape == ["complete"] * 4, shape
    assert scrolls >= 1, "לא נגלל"
    assert header - 1 <= res_top <= header + 40, (
        f"התוצאה לא בראש המסך: top={res_top}, header={header}")


def test_on_a_wide_window_the_last_next_does_not_scroll(browser, server):
    scrolls, _res_top, _header, shape = _last_next(browser, server, 1440, 900)
    assert shape == ["complete"] * 4, shape
    assert scrolls == 0, f"העמוד נגלל ברחב ({scrolls} קריאות גלילה)"


# --------------------------------------------------------------------------
# 5. ההשלמה נשמרת
# --------------------------------------------------------------------------
def test_reload_keeps_the_completed_steps(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _through_courses(pg)
        _next(pg, "days")
        _next(pg, "lecturers")
        pg.reload()
        pg.wait_for_timeout(5000)
        shape = _shape(pg)
        blocks = pg.evaluate("() => document.querySelectorAll('#schedule-grid .ev').length")
        keys = pg.evaluate("() => Object.keys(localStorage)")
    finally:
        ctx.close()
    assert shape == ["complete"] * 4, shape
    assert blocks > 0, "המערכת לא מוכנה אחרי טעינה מחדש"
    assert STORAGE_KEY in keys, keys


def test_a_saved_step_that_became_invalid_reopens(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _through_courses(pg)
        _next(pg, "days")
        _next(pg, "lecturers")
        # ‏הסמסטר שנשמר כבר אינו תקין: שלב 1 נפתח, והקורסים — שעדיין
        # ‏מסומנים כמושלמים — נעולים עד שמגיעים אליהם שוב ב"המשך".
        pg.evaluate(
            """(key) => { const s = JSON.parse(localStorage.getItem(key));
                          s.term = ''; localStorage.setItem(key, JSON.stringify(s)); }""",
            STORAGE_KEY,
        )
        pg.reload()
        pg.wait_for_timeout(4000)
        shape = _shape(pg)
        completed = _saved(pg).get("completed")
        pg.select_option("#select-term", "א")
        pg.wait_for_timeout(2500)
        _next(pg, "year")
        resumed = _shape(pg)
    finally:
        ctx.close()
    assert shape == ["open", "locked", "locked", "locked"], shape
    assert completed and completed.get("courses") is True, completed
    assert resumed == ["complete"] * 4, (
        f"אחרי תיקון שלב 1, השלבים שעדיין תקינים חוזרים מושלמים: {resumed}")


def test_a_saved_courses_step_with_no_courses_reopens_as_the_active_step(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _through_courses(pg)
        _next(pg, "days")
        pg.evaluate(
            """(key) => { const s = JSON.parse(localStorage.getItem(key));
                          s.codes = []; s.manualCodes = []; s.autoCodes = [];
                          localStorage.setItem(key, JSON.stringify(s)); }""",
            STORAGE_KEY,
        )
        pg.reload()
        pg.wait_for_timeout(4000)
        shape = _shape(pg)
    finally:
        ctx.close()
    assert shape == ["complete", "open", "locked", "locked"], shape


# --------------------------------------------------------------------------
# 6. בנייה חיה, בלי קשר למצב השלבים
# --------------------------------------------------------------------------
def test_the_schedule_still_rebuilds_live_while_a_step_is_open(browser, server):
    ctx, pg = _page(browser, server)
    solves = []
    pg.on("request", lambda r: solves.append(r.url) if "/api/solve" in r.url else None)
    try:
        _identity(pg)
        _next(pg, "year")
        # ‏שלב הקורסים פתוח, ואף שלב אחריו לא הושלם.
        n0 = len(solves)
        pg.click("#btn-restore-recommended")
        pg.wait_for_timeout(4000)
        n1 = len(solves)
        blocks = pg.evaluate("() => document.querySelectorAll('#schedule-grid .ev').length")
        shape = _shape(pg)
        _next(pg, "courses")
        n2 = len(solves)
        pg.click('.day-btn[data-days="3"]')
        pg.wait_for_timeout(2500)
        n3 = len(solves)
    finally:
        ctx.close()
    assert shape == ["complete", "open", "locked", "locked"], shape
    assert n1 > n0, "סימון קורסים בשלב פתוח לא הפעיל חישוב"
    assert blocks > 0, "המערכת לא נבנתה בזמן ששלב הקורסים פתוח"
    assert n3 > n2, "שינוי יעד הימים בשלב פתוח לא הפעיל חישוב"
