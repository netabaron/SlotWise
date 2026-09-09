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
        before = {s["id"]: s["def"] for s in pg.evaluate(STEPS)}
        pg.click('.day-btn[data-days="3"]')
        pg.wait_for_timeout(2500)
        after = {s["id"]: s["def"] for s in pg.evaluate(STEPS)}
    finally:
        ctx.close()
    changed = [k for k in before if before[k] and not after[k]]
    assert changed == ["step-days"], (
        f"בחירה אחת שינתה {changed}, ציפינו ל-['step-days'] בלבד")


def test_going_back_to_the_default_turns_the_mark_grey_again(browser, server):
    """הסיבה כולה שהמנגנון הוחלף.

    ‏הגרסה הקודמת זכרה נגיעה, ולכן סעיף שנגעת בו נשאר ירוק לתמיד — גם
    אחרי שהחזרת את הערך בדיוק למה שהיה. אחרי יום שימוש כל ארבעת הסעיפים
    היו ירוקים, והסימון חדל לשאת מידע. עכשיו משווים ערכים, ולכן חזרה אל
    ברירת המחדל חוזרת גם לאפור.
    """
    ctx, pg = _fresh(browser, server)
    try:
        _identity(pg)
        base = pg.evaluate(
            "() => document.querySelector('.day-btn[aria-checked=\"true\"]')"
            "        ?.dataset.days || null")
        assert base, "לא נמצא יעד ימים ברירת מחדל"
        other = "3" if base != "3" else "5"

        pg.click(f'.day-btn[data-days="{other}"]')
        pg.wait_for_timeout(2500)
        away = {s["id"]: s["def"] for s in pg.evaluate(STEPS)}

        pg.click(f'.day-btn[data-days="{base}"]')   # בחזרה בדיוק לברירת המחדל
        pg.wait_for_timeout(2500)
        back = {s["id"]: s["def"] for s in pg.evaluate(STEPS)}
    finally:
        ctx.close()
    assert away["step-days"] is False, f"שינוי מ-{base} ל-{other} לא סימן את הסעיף"
    assert back["step-days"] is True, (
        f"חזרה ל-{base}, שהוא ברירת המחדל, השאירה את הסעיף מסומן כנבחר — "
        "הסימון דביק, וזה מה שהיה אמור להשתנות")


def test_the_mark_survives_a_reload(browser, server):
    """ערך שנבחר נשמר, ולכן משתמש/ת חוזר/ת רואה אותו מסומן — לא איפוס."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    try:
        pg.goto(server)
        pg.wait_for_timeout(4500)
        _identity(pg)
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


# --------------------------------------------------------------------------
# 4. אישור סעיף — "ההצעה מתאימה לי" הוא גם החלטה
# --------------------------------------------------------------------------
CONFIRM_SNAP = """() => {
  const mark = id => {
    const s = document.getElementById(id);
    return s.classList.contains('is-conflict') ? 'amber'
         : s.classList.contains('is-locked') ? 'locked'
         : s.classList.contains('is-default') ? 'grey' : 'green';
  };
  const b = document.getElementById('btn-confirm-courses');
  const stale = document.getElementById('confirm-courses-stale');
  let saved = null;
  try { saved = JSON.parse(
    localStorage.getItem('braude_schedule_builder_v1')).confirmed; } catch (e) {}
  return {
    courses: mark('step-courses'), days: mark('step-days'),
    pressed: b && b.getAttribute('aria-pressed'),
    tick: b && getComputedStyle(b.querySelector('.confirm-tick')).visibility,
    stale: stale && !stale.hidden ? (stale.textContent || '').trim() : null,
    confirmed: saved,
  };
}"""


def test_agreeing_with_the_suggestion_turns_the_section_green(browser, server):
    """הבעיה שהמתג נועד לה: מי שההצעה מתאימה לה בדיוק לא שינתה דבר,
    ולכן נראתה כמי שלא נגעה בסעיף — נענשת על כך שהניחוש היה טוב."""
    ctx, pg = _fresh(browser, server)
    try:
        _identity(pg)
        before = pg.evaluate(CONFIRM_SNAP)
        assert before["courses"] == "grey", before
        assert before["tick"] == "hidden", "אין ✓ לפני שאישרו"

        pg.click("#btn-confirm-courses")
        pg.wait_for_timeout(1200)
        after = pg.evaluate(CONFIRM_SNAP)
    finally:
        ctx.close()
    assert after["courses"] == "green", "הסכמה היא החלטה, והסעיף אמור לומר זאת"
    assert after["pressed"] == "true"
    assert after["tick"] == "visible", "הסימן חייב להיות צורה, לא רק צבע"
    assert after["confirmed"] and after["confirmed"].get("courses"), (
        "נשמר דגל במקום ערך — זה ‏touched בשם אחר")


def test_the_confirm_is_a_toggle(browser, server):
    """אישור חד-כיווני הופך הקלקה בטעות לקבועה, ואת האפור לבלתי נגיש."""
    ctx, pg = _fresh(browser, server)
    try:
        _identity(pg)
        pg.click("#btn-confirm-courses"); pg.wait_for_timeout(1000)
        assert pg.evaluate(CONFIRM_SNAP)["courses"] == "green"
        pg.click("#btn-confirm-courses"); pg.wait_for_timeout(1000)
        back = pg.evaluate(CONFIRM_SNAP)
    finally:
        ctx.close()
    assert back["courses"] == "grey", "לחיצה שנייה לא ביטלה"
    assert back["pressed"] == "false"
    assert not (back["confirmed"] or {}).get("courses"), "הערך לא נמחק"


def test_a_recomputed_default_undoes_the_confirm_and_says_so(browser, server):
    """הדרישה המרכזית: סימן שנעלם בשקט הוא בדיוק מה שאסור.

    ‏אישרה שישה קורסים, החליפה שנה, וההמלצה חושבה מחדש. הסעיף חוזר לאפור
    — נכון, כי היא לא אישרה את **זו** — אבל היא חייבת לדעת שמשהו זז.
    """
    ctx, pg = _fresh(browser, server)
    try:
        _identity(pg)
        pg.click("#btn-confirm-courses"); pg.wait_for_timeout(1200)
        assert pg.evaluate(CONFIRM_SNAP)["courses"] == "green"

        pg.select_option("#select-year", "2")   # ההמלצה מחושבת מחדש
        pg.wait_for_timeout(6000)
        after = pg.evaluate(CONFIRM_SNAP)
    finally:
        ctx.close()
    assert after["courses"] == "grey", "אישור לרשימה אחרת אינו אישור לזו"
    assert after["stale"], "הסימן נעלם בלי לומר דבר — זה מה שנאסר במפורש"
    assert "השתנתה" in after["stale"], after["stale"]


def test_the_confirmed_value_is_compared_as_a_set_not_a_string(browser, server):
    """‏עמידות לשינוי צורה, לא רק לשינוי ערך.

    ‏הערך השמור מוזרע כאן **בסדר הפוך**. השוואה שנכתבה כמחרוזת או כמערך
    מסודר הייתה קוראת לזה "השתנה" ומחזירה את הסעיף לאפור בלי סיבה, ביום
    שבו משהו במעלה הזרם יחליף סדר. השוואה כרב-קבוצה אינה מבחינה בכך.
    """
    ctx, pg = _fresh(browser, server)
    try:
        _identity(pg)
        pg.click("#btn-confirm-courses"); pg.wait_for_timeout(1200)
        assert pg.evaluate(CONFIRM_SNAP)["courses"] == "green"

        pg.evaluate(
            """() => {
              const k = 'braude_schedule_builder_v1';
              const s = JSON.parse(localStorage.getItem(k));
              s.confirmed.courses = s.confirmed.courses.slice().reverse();
              localStorage.setItem(k, JSON.stringify(s));
            }"""
        )
        pg.reload()
        pg.wait_for_timeout(5000)
        after = pg.evaluate(CONFIRM_SNAP)
    finally:
        ctx.close()
    assert after["courses"] == "green", (
        "סדר הפוך נקרא כשינוי — ההשוואה תלויה בסדר ותייצר אפור מדומה")
    assert after["stale"] is None, "ואין להתריע על שינוי שלא קרה"


def test_the_lecturers_section_has_no_confirm(browser, server):
    """ברירת המחדל שלו היא היעדר העדפות — אין הצעה, ואין למה להסכים."""
    ctx, pg = _fresh(browser, server)
    try:
        _identity(pg)
        found = pg.evaluate(
            "() => [...document.querySelectorAll('#step-lecturers .confirm-btn')].length"
        )
    finally:
        ctx.close()
    assert found == 0, "נוסף אישור למרצים — אין לו ברירת מחדל דעתנית לאשר"
