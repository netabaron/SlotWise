"""מועדים שעוד לא פורסמו: חלון בבחירת הסמסטר, ומצב ריק במקום מערכות ריקות.

הידיעון פותח סמסטר לפני שהוא מפרסם ימים ושעות. בקטלוג הקפוא סמסטר ב׳
נושא 988 קבוצות ואף מפגש — בדיוק המצב שבו הדף הציג חמש מערכות של "0 ימים"
בלי הסבר. ההכרעה היא מהנתונים (``timed_by_term`` ב-/api/bootstrap), לא
מאות הסמסטר, ולכן הבדיקות כאן לא מזכירות "ב" כקבוע אלא כמה שהשרת אמר.

* סמסטר שיש בו קבוצות ואף אחת מהן בלי מועד → חלון, פעם אחת לסמסטר בסשן,
  ‏Esc וכפתור סוגרים, והפוקוס חוזר.
* באותו סמסטר — והוא הדין כשלאף קורס שנבחר אין מועד — אזור התוצאות מציג
  הודעה אחת במקום כרטיסים ורשת.
* רק חלק מהקורסים בלי מועד → אין חלון ואין מצב ריק; שורת "ללא מועד קבוע"
  נשארת כמו שהיא.

השרת מצביע על מסד ריק — רק הקטלוג הקפוא נקרא, לא data/db המקומי, שהמסד
הזרוע שלו (סמסטר א׳ בלבד) מסתיר את קבוצות סמסטר ב׳ של הקטלוג.
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

from src.web.api import create_app  # noqa: E402

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
NO_TIMES = STRINGS["app"]["noTimes"]
GRID = STRINGS["app"]["grid"]
STORAGE_KEY = "braude_schedule_builder_v1"  # אין לשנותו — ראו CLAUDE.md
PROGRAM = "הנדסת תוכנה"
#: ‏"פרויקט מסכם שלב א׳": בקטלוג הקפוא, לקבוצה היחידה שלו בסמסטר א׳ אין מועד.
UNTIMED_CODE = "61998"

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

PHONE = (390, 844)
DESKTOP = (1440, 1000)


def fill(template: str, **values) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    db = tmp_path_factory.mktemp("empty-db")
    return create_app(config={"allow_network": False, "db_root": str(db)})


@pytest.fixture(scope="module")
def timing(app):
    """‏``timed_by_term`` כפי שהשרת שולח אותו — המקור של כל ההחלטות כאן."""
    data = app.test_client().get("/api/bootstrap").get_json()
    return data["timed_by_term"]


@pytest.fixture(scope="module")
def untimed_term(timing):
    terms = [t for t, rec in timing.items() if rec["groups"] > 0 and rec["timed"] == 0]
    if not terms:
        pytest.skip("בקטלוג הקפוא אין סמסטר בלי מועדים")
    return terms[0]


@pytest.fixture(scope="module")
def timed_term(timing):
    terms = [t for t, rec in timing.items() if rec["timed"] > 0]
    assert terms, timing
    return terms[0]


@pytest.fixture(scope="module")
def server(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = make_server("127.0.0.1", port, app, threaded=True)
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
        except Exception as exc:  # אין דפדפן מותקן — לא כישלון של הקוד
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            yield b
        finally:
            b.close()


def _open(browser, server, term, size=DESKTOP):
    """מסלול, שנה ג׳ והסמסטר המבוקש — בלי לסגור חלון שנפתח."""
    ctx = browser.new_context(viewport={"width": size[0], "height": size[1]}, color_scheme="dark")
    pg = ctx.new_page()
    pg.errors = []  # type: ignore[attr-defined]
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))  # type: ignore[attr-defined]
    pg.goto(server)
    pg.wait_for_timeout(2500)
    pg.select_option("#select-program", PROGRAM)
    pg.select_option("#select-year", "3")
    # ‏כמו ביד: הפוקוס על התיבה, ואז הבחירה. לשם הוא חוזר כשהחלון נסגר.
    pg.focus("#select-term")
    pg.select_option("#select-term", term)
    pg.wait_for_timeout(1500)
    return ctx, pg


DIALOG = """() => {
  const d = document.getElementById('no-times-dialog');
  return {
    open: d.open,
    modal: d.open && d.matches(':modal'),
    title: document.getElementById('no-times-title').textContent.trim(),
    body: document.getElementById('no-times-body').textContent.trim(),
    focused: document.activeElement && document.activeElement.id,
    dir: getComputedStyle(d).direction,
    bg: getComputedStyle(d).backgroundColor,
  };
}"""

#: ‏החלון כמודאל: מיקום, רקע מעומעם, נעילת גלילה, ומה מקבל לחיצה מאחוריו.
MODAL = """() => {
  const d = document.getElementById('no-times-dialog');
  const r = d.getBoundingClientRect();
  const root = getComputedStyle(document.documentElement);
  const behind = id => {
    const e = document.getElementById(id);
    const b = e.getBoundingClientRect();
    const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
    return hit === e || e.contains(hit);
  };
  const align = sel => getComputedStyle(d.querySelector(sel)).textAlign;
  const btn = document.getElementById('no-times-ok').getBoundingClientRect();
  return {
    dx: Math.abs((r.left + r.right) / 2 - innerWidth / 2),
    dy: Math.abs((r.top + r.bottom) / 2 - innerHeight / 2),
    inView: r.top >= 0 && r.left >= 0 && r.bottom <= innerHeight && r.right <= innerWidth,
    backdrop: getComputedStyle(d, '::backdrop').backgroundColor,
    scrim: root.getPropertyValue('--scrim').trim(),
    overflow: getComputedStyle(document.documentElement).overflow,
    termReachable: behind('select-term'),
    nextReachable: behind('step-year-next'),
    titleAlign: align('#no-times-title'),
    bodyAlign: align('#no-times-body'),
    btnOffset: Math.abs((btn.left + btn.right) / 2 - (r.left + r.right) / 2),
  };
}"""


def _rgba_alpha(css: str) -> float:
    """האלפא של ‎rgb()/rgba()‎ כפי ש-getComputedStyle מחזיר."""
    nums = css[css.index("(") + 1 : css.rindex(")")].replace("/", ",").split(",")
    return float(nums[3]) if len(nums) == 4 else 1.0

RESULTS = """() => {
  const shown = id => { const e = document.getElementById(id); return !!e && !e.hidden && e.getClientRects().length > 0; };
  const sub = document.getElementById('schedule-no-times-sub');
  const u = document.getElementById('schedule-unscheduled');
  return {
    noTimes: shown('schedule-no-times'),
    sub: sub ? sub.textContent.trim() : '',
    infeasible: shown('schedule-empty'),
    cards: document.querySelectorAll('#alt-cards .alt-card, #alt-cards > *').length,
    altCardsShown: shown('alt-cards'),
    gridShown: shown('grid-scroll'),
    placeholder: shown('schedule-placeholder'),
    unscheduled: u && !u.hidden ? u.textContent.trim() : '',
    solved: !!window.slotwise.getRuntime().solve,
    blocks: document.querySelectorAll('#schedule-grid .ev').length,
  };
}"""


def _term_label(pg, term) -> str:
    return pg.evaluate(
        "(t) => [...document.querySelectorAll('#select-term option')]"
        ".find(o => o.value === t).textContent.trim()",
        term,
    )


def _choose_codes(pg, codes):
    """שלב הקורסים, ואז בדיוק ``codes`` — דרך המצב השמור, כמו בבדיקות האחרות."""
    pg.evaluate(
        """(a) => { const s = JSON.parse(localStorage.getItem(a.key) || '{}');
                    s.codes = a.codes;
                    localStorage.setItem(a.key, JSON.stringify(s)); }""",
        {"key": STORAGE_KEY, "codes": list(codes)},
    )
    pg.reload()
    pg.wait_for_timeout(1500)


def _wait_solved(pg):
    pg.wait_for_function(
        "() => { const r = window.slotwise.getRuntime();"
        " return !!r.solve && !r.solveBusy && !r.coursesBusy; }",
        timeout=30000,
    )
    pg.wait_for_timeout(600)


# ==========================================================================
# 0. הנתונים: ההכרעה היא מהקטלוג
# ==========================================================================
def test_bootstrap_reports_timed_counts_per_term(timing, untimed_term, timed_term):
    assert set(timing) >= {"א", "ב"}, timing
    for rec in timing.values():
        assert 0 <= rec["timed"] <= rec["groups"], timing
    assert timing[untimed_term]["groups"] > 0
    assert timing[untimed_term]["timed"] == 0
    assert timing[timed_term]["timed"] > 0


# ==========================================================================
# 1. החלון
# ==========================================================================
@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_the_popup_opens_when_a_term_without_times_is_picked(browser, server, untimed_term, size):
    ctx, pg = _open(browser, server, untimed_term, size)
    try:
        d = pg.evaluate(DIALOG)
        assert d["open"] and d["modal"], d
        assert d["title"] == NO_TIMES["title"]
        assert d["body"] == fill(NO_TIMES["bodyTerm"], term=_term_label(pg, untimed_term))
        assert d["focused"] == "no-times-ok", "הפוקוס עובר לכפתור שבחלון"
        assert d["dir"] == "rtl"
        # ‏ערכה כהה: המשטח של החלון הוא המשטח הכהה, לא לבן.
        assert d["bg"] != "rgb(255, 255, 255)", d
        assert pg.evaluate("document.getElementById('no-times-ok').textContent.trim()") == NO_TIMES["ok"]

        m = pg.evaluate(MODAL)
        # ‏במרכז החלון, כולו בתוך המסך.
        assert m["dx"] < 2 and m["dy"] < 2 and m["inView"], m
        # ‏רקע מעומעם שקוף-למחצה, מהטוקן ‎--scrim‎.
        assert m["scrim"], "‏‎--scrim‎ מוגדר ב-:root"
        alpha = _rgba_alpha(m["backdrop"])
        assert 0 < alpha < 1, m
        # ‏הדף שמאחור אינו נגלל ואינו לחיץ.
        assert m["overflow"] == "hidden", m
        assert not m["termReachable"] and not m["nextReachable"], m
        with pytest.raises(Exception):
            pg.click("#step-year-next", timeout=800)
        assert pg.evaluate(DIALOG)["open"], "לחיצה על הדף שמאחור אינה עוברת"
        # ‏בתוך החלון בלבד: כותרת, גוף וכפתור ממורכזים.
        assert m["titleAlign"] == "center" and m["bodyAlign"] == "center", m
        assert m["btnOffset"] < 2, m
        # ‏והמצב הריק שבתוצאות נשאר מיושר לימין, כמו שאר הדף.
        assert pg.evaluate(
            "getComputedStyle(document.getElementById('schedule-no-times')).textAlign"
        ) in ("start", "right")
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_clicking_the_backdrop_closes_it_and_unlocks_the_page(browser, server, untimed_term):
    ctx, pg = _open(browser, server, untimed_term)
    try:
        assert pg.evaluate(DIALOG)["open"]
        pg.mouse.click(8, 8)  # ‏פינת המסך — הרקע המעומעם, לא החלון
        pg.wait_for_timeout(300)
        d = pg.evaluate(DIALOG)
        assert not d["open"], d
        assert d["focused"] == "select-term", d
        assert pg.evaluate("getComputedStyle(document.documentElement).overflow") != "hidden"
        # ‏לחיצה בתוך החלון — גם על הריפוד שלו — אינה סוגרת. סשן "חדש" באותה
        # ‏לשונית: בלי הרישום, ורענון מחזיר את הסמסטר השמור ואת החלון.
        pg.evaluate("sessionStorage.clear()")
        pg.reload()
        pg.wait_for_timeout(2500)
        assert pg.evaluate(DIALOG)["open"]
        box = pg.locator("#no-times-dialog").bounding_box()
        pg.mouse.click(box["x"] + 6, box["y"] + 6)
        pg.wait_for_timeout(300)
        assert pg.evaluate(DIALOG)["open"], "לחיצה בתוך החלון אינה סוגרת אותו"
    finally:
        ctx.close()


def test_tab_keeps_focus_inside_the_popup(browser, server, untimed_term):
    ctx, pg = _open(browser, server, untimed_term)
    try:
        for key in ("Tab", "Tab", "Shift+Tab"):
            pg.keyboard.press(key)
            assert pg.evaluate(DIALOG)["focused"] == "no-times-ok", key
        assert pg.evaluate(DIALOG)["open"]
    finally:
        ctx.close()


def test_escape_closes_it_and_focus_returns_to_the_term_box(browser, server, untimed_term):
    ctx, pg = _open(browser, server, untimed_term)
    try:
        assert pg.evaluate(DIALOG)["open"]
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        d = pg.evaluate(DIALOG)
        assert not d["open"], d
        assert d["focused"] == "select-term", d
    finally:
        ctx.close()


def test_the_button_closes_it_and_it_is_not_shown_again_in_the_session(
    browser, server, untimed_term, timed_term
):
    ctx, pg = _open(browser, server, untimed_term)
    try:
        pg.click("#no-times-ok")
        pg.wait_for_timeout(300)
        assert not pg.evaluate(DIALOG)["open"]
        # ‏הלוך ושוב בין הסמסטרים: אותו סמסטר אינו פותח את החלון פעם שנייה.
        pg.select_option("#select-term", timed_term)
        pg.wait_for_timeout(1200)
        pg.select_option("#select-term", untimed_term)
        pg.wait_for_timeout(1200)
        assert not pg.evaluate(DIALOG)["open"], "פעם אחת לסמסטר בסשן"
        # ‏וגם לא אחרי רענון באותה לשונית — זה עדיין אותו סשן.
        pg.reload()
        pg.wait_for_timeout(2500)
        assert pg.evaluate("window.slotwise.getState().term") == untimed_term
        assert not pg.evaluate(DIALOG)["open"], "רענון אינו סשן חדש"
    finally:
        ctx.close()


def test_a_new_session_shows_it_again(browser, server, untimed_term):
    for _ in range(2):
        ctx, pg = _open(browser, server, untimed_term)
        try:
            assert pg.evaluate(DIALOG)["open"], "כל סשן חדש רואה את החלון פעם אחת"
        finally:
            ctx.close()


def test_no_popup_for_a_term_that_has_times(browser, server, timed_term):
    ctx, pg = _open(browser, server, timed_term)
    try:
        assert not pg.evaluate(DIALOG)["open"]
        assert pg.evaluate(RESULTS)["noTimes"] is False
    finally:
        ctx.close()


# ==========================================================================
# 2. המצב הריק
# ==========================================================================
@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_a_term_without_times_shows_the_message_instead_of_empty_schedules(
    browser, server, untimed_term, size
):
    ctx, pg = _open(browser, server, untimed_term, size)
    try:
        pg.keyboard.press("Escape")
        pg.click("#step-year-next")
        pg.wait_for_timeout(1200)
        pg.click("#btn-restore-recommended")
        _wait_solved(pg)
        assert pg.evaluate("window.slotwise.getState().codes.length") > 0
        r = pg.evaluate(RESULTS)
        assert r["solved"], "החישוב עצמו לא השתנה — רק מה שמוצג ממנו"
        assert r["noTimes"], r
        assert r["sub"] == fill(NO_TIMES["bodyTerm"], term=_term_label(pg, untimed_term))
        assert not r["infeasible"], "זה לא \"אין מערכת אפשרית\""
        assert not r["altCardsShown"] and not r["gridShown"], r
        assert r["blocks"] == 0
        assert not pg.evaluate(DIALOG)["open"], "החלון אינו חוזר עם התוצאה"
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_the_message_shows_before_any_course_is_chosen(browser, server, untimed_term):
    """בלי קורסים: ההודעה במקום "בחרו קורסים, והמערכת תופיע כאן"."""
    ctx, pg = _open(browser, server, untimed_term)
    try:
        pg.keyboard.press("Escape")
        _choose_codes(pg, [])
        r = pg.evaluate(RESULTS)
        assert r["noTimes"] and not r["placeholder"], r
    finally:
        ctx.close()


def test_selected_courses_without_times_show_the_courses_message(browser, server, timed_term):
    ctx, pg = _open(browser, server, timed_term)
    try:
        _choose_codes(pg, [UNTIMED_CODE])
        _wait_solved(pg)
        r = pg.evaluate(RESULTS)
        assert r["noTimes"], r
        assert r["sub"] == NO_TIMES["bodyCourses"]
        assert not r["infeasible"] and not r["gridShown"], r
        assert not pg.evaluate(DIALOG)["open"], "הסמסטר עצמו מתוזמן — אין חלון"
    finally:
        ctx.close()


def test_some_untimed_courses_keep_the_existing_line(browser, server, timed_term):
    """קורס בלי מועד לצד קורסים עם מועד: אין חלון, אין מצב ריק, השורה הקיימת."""
    ctx, pg = _open(browser, server, timed_term)
    try:
        pg.click("#step-year-next")
        pg.click("#btn-restore-recommended")
        pg.wait_for_selector("#schedule-grid .ev", timeout=20000)
        codes = pg.evaluate("window.slotwise.getState().codes")
        _choose_codes(pg, list(codes) + [UNTIMED_CODE])
        _wait_solved(pg)
        pg.wait_for_selector("#schedule-grid .ev", timeout=20000)
        r = pg.evaluate(RESULTS)
        assert not r["noTimes"], r
        assert r["gridShown"] and r["blocks"] > 0, r
        assert r["unscheduled"].startswith(fill(GRID["unscheduled"], list="")), r
        assert not pg.evaluate(DIALOG)["open"]
    finally:
        ctx.close()
