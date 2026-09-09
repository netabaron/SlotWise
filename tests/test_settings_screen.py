"""מסך ההגדרות: מה ששלב 5 הבטיח, נבדק בדפדפן על הציור הראשון.

למה הקובץ הזה קיים
-------------------
שני דיווחים ב-2026-09-08, ורק אחד מהם היה באג:

1. **התוויות והתיבות לא היו מיושרות.** ``.input`` מצהיר על
   ``min-inline-size: 9rem`` (144px) כדי ששדה בודד לא ייצא זעיר, ואילו
   ``.field--sm`` שהגיע בשלב 5 הוא ``8rem`` (128px). הרצפה גדולה מהמכל,
   ולכן ה-``select`` גלש 16px החוצה — וב-RTL הגלישה היא שמאלה, אל תוך
   השדה השכן. התווית "סמסטר", שמיושרת לימין השדה שלה, כיסתה בפועל את
   ``#select-year``. **זה נבדק כאן כחפיפה גאומטרית בין תווית לתיבה שאינה
   שלה** ולא כרוחב של מחלקה, כי המספר שנשבר הוא היחס ביניהם.

2. **הסימונים בסעיפים** דווחו כירוקים על טעינה נקייה. על הקשר דפדפן נקי
   הם לא היו — אבל הדיווח הצביע על פגם אמיתי במנגנון. הגרסה הראשונה זכרה
   *נגיעה* (``state.touched``), וזיכרון כזה דביק: סעיף שנגעת בו נשאר ירוק
   לתמיד, גם אחרי שהחזרת את הערך בדיוק לברירת המחדל. אחרי יום שימוש כל
   ארבעת הסעיפים ירוקים, והסימון חדל לשאת מידע — כלומר בדיוק מה ששלב 5
   בא לתקן.

   ‏המנגנון הוחלף בהשוואת **ערכים** מול ברירת המחדל שהשרת נותן לסטודנט/ית
   הזה/ו. ``test_going_back_to_the_default_turns_the_mark_grey_again`` היא
   הבדיקה שמבדילה בין השניים: הישנה עוברת אותה רק אם המנגנון אינו דביק.

הבדיקות רצות ב**הקשר דפדפן חדש בכל פעם** — בלי ``localStorage`` ובלי מצב
מוזרע. זה בדיוק הפער שהחמיץ בעבר את באג התוויות הריקות: מצב מוזרע בודק
מסך שכבר נגעו בו, ולא את הציור הראשון.
"""

from __future__ import annotations

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

STEP_KEYS = ("year", "courses", "days", "lecturers")


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


def _fresh(browser, server, width: int = 1280):
    """הקשר חדש לגמרי: אין ‏localStorage, אין מצב, ציור ראשון."""
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    pg = ctx.new_page()
    pg.goto(server)
    pg.wait_for_timeout(4500)
    return ctx, pg


def _identity(pg):
    """בוחר מסלול, שנה וסמסטר.

    ‏מאז 2026-09-09 שלב 1 הוא זהות ואין לו ברירת מחדל, ולכן שלבים 2..5
    נעולים עד שנבחרו שלושתם. כל בדיקה שנוגעת בכפתורי הימים חייבת לעבור
    כאן קודם — אחרת היא נכשלת על פקד נעול, ולא על מה שהיא בודקת.
    """
    pg.select_option("#select-program", "הנדסת תוכנה")
    pg.select_option("#select-year", "3")
    pg.select_option("#select-term", "א")
    pg.wait_for_timeout(3000)


def _pick_courses(pg):
    """מסמנת את כל המומלצים בלחיצה אחת.

    ‏מאז 2026-09-09 שום קורס אינו מסומן מראש, ולכן שלב 3 נעול עד שיש
    קורסים. בדיקה שנוגעת בכפתורי הימים חייבת לעבור כאן קודם.
    """
    pg.click("#btn-restore-recommended")
    pg.wait_for_timeout(6000)


# --------------------------------------------------------------------------
# 1. תווית מעל התיבה שלה — ולא מעל השכנה
# --------------------------------------------------------------------------
OVERLAP = """() => {
  const fields = [...document.querySelectorAll('#step-year-body .field')]
    .map(f => ({label: f.querySelector('label'), sel: f.querySelector('select'), f}))
    .filter(x => x.label && x.sel);
  const bad = [], spill = [];
  for (const a of fields) {
    spill.push({id: a.sel.id, px: Math.round(
      a.sel.getBoundingClientRect().width - a.f.getBoundingClientRect().width)});
    const lr = a.label.getBoundingClientRect();
    for (const b of fields) {
      if (a === b) continue;
      const sr = b.sel.getBoundingClientRect();
      if (Math.abs(lr.top - sr.top) > 60) continue;   // שורות שונות
      const ov = Math.min(lr.right, sr.right) - Math.max(lr.left, sr.left);
      if (ov > 1) bad.push(`${a.label.textContent.trim()} מכסה #${b.sel.id} ב-${Math.round(ov)}px`);
    }
  }
  return {bad, spill};
}"""


@pytest.mark.parametrize("width", [1440, 1280, 1100, 980, 900])
def test_no_label_sits_over_a_foreign_select(browser, server, width):
    ctx, pg = _fresh(browser, server, width)
    try:
        got = pg.evaluate(OVERLAP)
    finally:
        ctx.close()
    assert not got["bad"], f"ב-{width}px: " + "; ".join(got["bad"])


@pytest.mark.parametrize("width", [1440, 1280, 980])
def test_no_input_spills_out_of_its_field(browser, server, width):
    """הסיבה עצמה, ולא רק התסמין.

    ‏מחלקת הרוחב היא שקובעת. תיבה רחבה מהמכל שלה תמיד תדחוף משהו.
    """
    ctx, pg = _fresh(browser, server, width)
    try:
        got = pg.evaluate(OVERLAP)
    finally:
        ctx.close()
    over = [s for s in got["spill"] if s["px"] > 1]
    assert not over, f"ב-{width}px תיבות גולשות מהשדה שלהן: {over}"


# --------------------------------------------------------------------------
# 2. הסימון נושא מידע
# --------------------------------------------------------------------------
STEPS = """() => [...document.querySelectorAll('.step')]
  .filter(s => s.id !== 'step-schedule')
  .map(s => ({id: s.id,
              def: s.classList.contains('is-default'),
              conflict: s.classList.contains('is-conflict'),
              locked: s.classList.contains('is-locked')}))"""


def test_every_section_is_grey_on_a_first_visit(browser, server):
    """‏✓ שמופיע על הכל מהרגע הראשון אינו סימן אלא קישוט — שלב 5, סעיף 1."""
    ctx, pg = _fresh(browser, server)
    try:
        steps = pg.evaluate(STEPS)
    finally:
        ctx.close()
    assert len(steps) == 4, steps
    # ‏שלב נעול אינו נושא סימן כלל — renderStepMarks מתנה את is-default
    # ב-‎!step.locked‎ — ולכן "ירוק" הוא: לא אפור, לא ענבר, ולא נעול.
    green = [s["id"] for s in steps
             if not s["def"] and not s["conflict"] and not s["locked"]]
    assert not green, f"סעיפים מסומנים כנבחרים והערכים בהם עדיין ברירת המחדל: {green}"
    assert [s["id"] for s in steps if s["locked"]] == [
        "step-courses", "step-days", "step-lecturers"
    ], "לפני בחירת זהות שלבים 2..4 נעולים"


def test_one_real_choice_turns_exactly_one_section(browser, server):
    """ולא כולם, ולא אף אחד."""
    ctx, pg = _fresh(browser, server)
    try:
        _identity(pg)
        _pick_courses(pg)
        before = {s["id"]: s["def"] for s in pg.evaluate(STEPS)}
        pg.click('.day-btn[data-days="3"]')
        pg.wait_for_timeout(2500)
        after = {s["id"]: s["def"] for s in pg.evaluate(STEPS)}
    finally:
        ctx.close()
    changed = [k for k in before if before[k] and not after[k]]
    assert changed == ["step-days"], (
        f"בחירה אחת שינתה {changed}, ציפינו ל-['step-days'] בלבד")


def test_unticking_everything_returns_the_section_to_grey(browser, server):
    """הכלל אחיד: אפור עד שבחרה, ירוק אחרי — ובחזרה, אם ביטלה.

    ‏עד 2026-09-09 הבדיקה הזאת נכתבה על יעד הימים, כי לו הייתה ברירת מחדל
    לחזור אליה. אין לו עוד — אין יעד מוצע, ואי אפשר "לבטל בחירה" של יעד.
    הטענה עצמה לא השתנתה, ומקומה עכשיו בקורסים: לסמן ואז לבטל מחזיר את
    הסעיף לאפור, כי הסימן מודד בחירה ולא נגיעה.
    """
    ctx, pg = _fresh(browser, server)
    try:
        _identity(pg)
        grey = {s["id"]: s["def"] for s in pg.evaluate(STEPS)}
        assert grey["step-courses"] is True, "לפני סימון — אפור"

        _pick_courses(pg)
        green = {s["id"]: s["def"] for s in pg.evaluate(STEPS)}
        assert green["step-courses"] is False, "אחרי סימון — ירוק"

        # ‏קורסים צמודים יורדים כחבילה, ולכן לולאה שלוחצת על כל תיבה
        # מסומנת בבת אחת מסמנת חלק מהן בחזרה. מבטלים אחת-אחת, ובכל פעם
        # שואלים מחדש מה עדיין מסומן.
        for _ in range(12):
            left = pg.evaluate(
                "() => document.querySelectorAll("
                "  '#course-list .course-item input:checked').length")
            if not left:
                break
            pg.evaluate(
                "() => document.querySelector("
                "  '#course-list .course-item input:checked').click()")
            pg.wait_for_timeout(1200)
        pg.wait_for_timeout(5000)
        back = {s["id"]: s["def"] for s in pg.evaluate(STEPS)}
    finally:
        ctx.close()
    assert back["step-courses"] is True, (
        "ביטול כל הסימונים השאיר את הסעיף ירוק — הסימן דביק")


def test_the_mark_survives_a_reload(browser, server):
    """ערך שנבחר נשמר, ולכן משתמש/ת חוזר/ת רואה אותו מסומן — לא איפוס."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    try:
        pg.goto(server)
        pg.wait_for_timeout(4500)
        _identity(pg)
        _pick_courses(pg)
        pg.click('.day-btn[data-days="3"]')
        pg.wait_for_timeout(2500)
        pg.reload()
        pg.wait_for_timeout(4500)
        after = {s["id"]: s["def"] for s in pg.evaluate(STEPS)}
    finally:
        ctx.close()
    assert after["step-days"] is False, "הבחירה לא שרדה טעינה מחדש"
    # ‏שלב 1 ירוק בצדק: הזהות נבחרה ונשמרה. הסעיף שלא נגעו בו הוא מרצים.
    assert after["step-year"] is False, "הזהות שנבחרה לא שרדה טעינה מחדש"
    assert after["step-lecturers"] is True, "סעיף שלא נגעו בו הפך לנבחר אחרי טעינה"


# --------------------------------------------------------------------------
# 3. שאר מה ששלב 5 הבטיח
# --------------------------------------------------------------------------
def test_the_progress_line_reports_each_section(browser, server):
    ctx, pg = _fresh(browser, server)
    try:
        chips = pg.evaluate(
            """() => [...document.querySelectorAll('.progress-chip')].map(c => ({
                 text: (c.textContent || '').trim(),
                 stateful: c.classList.contains('is-default') ||
                           c.classList.contains('is-conflict') ||
                           c.classList.contains('is-chosen')}))"""
        )
    finally:
        ctx.close()
    assert len(chips) == 4, chips
    for c in chips:
        assert c["text"], "שבב התקדמות בלי טקסט"
        assert c["stateful"], f"שבב בלי מצב: {c['text']!r}"


@pytest.mark.parametrize("key", STEP_KEYS)
def test_a_collapsed_section_shows_its_own_summary(browser, server, key):
    """שלב 5, סעיף 3: סעיף מקופל חייב לומר מה יש בו."""
    ctx, pg = _fresh(browser, server)
    try:
        pg.evaluate(
            "(k) => { const s = document.getElementById('step-' + k);"
            " if (s) s.classList.add('is-collapsed'); }", key)
        pg.wait_for_timeout(300)
        summary = pg.evaluate(
            "(k) => { const e = document.getElementById('step-' + k + '-summary');"
            " return e ? (e.textContent || '').trim() : null; }", key)
    finally:
        ctx.close()
    assert summary, f"סעיף {key} מקופל בלי שורת סיכום"
