"""שלב 2 בדפדפן אמיתי: מה מסומן, ומה קורה כשמחליפים שנה וסמסטר.

למה בדפדפן
-----------
הכלל שקובע מה מסומן חי ב-``src/web/static/app.js``, ולפרויקט אין מריץ בדיקות
ל-JavaScript. עד הקובץ הזה כל צד הלקוח — הפרדת "סומן אוטומטית" מ"נוסף ידנית",
זכירת ביטול ידני, והאימוץ החד-פעמי של מצב שמור — לא היה מכוסה בכלל, וכל
רגרסיה בו הייתה מתגלה רק בשימוש. ‏Playwright כבר תלוי בפרויקט (הוא מה שמושך
מהידיעון), ולכן זו בדיקה בלי תלות חדשה.

הבדיקה מדלגת על עצמה בשקט כשאין ‏Playwright או כשאין דפדפן מותקן, כדי
שהסוויטה תמשיך לרוץ במכונה שלא הריצה ``playwright install``.

מה **לא** נעשה כאן, בכוונה: אין רשת אמיתית ואין ידיעון. השרת עולה על פורט
מקומי מול הנתונים שכבר במאגר, ואף בדיקה כאן לא תלויה בגודל הקטלוג — רק
בהתנהגות הממשק מול מה שהשרת מחזיר.
"""

from __future__ import annotations

import json
import re
import socket
import sys
import threading
import time
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

STORAGE_KEY = "braude_schedule_builder_v1"
PROGRAM = "הנדסת תוכנה"

#: קריאת מצב אחת. מחזירה גם מה שמצויר וגם מה שנשמר — הבדיקות כאן נשענות
#: על שניהם יחד, כי בדיוק אי-ההתאמה ביניהם היא התקלה שהקובץ הזה שומר מפניה.
SNAPSHOT = """() => {
  const rows = [...document.querySelectorAll('#course-list .course-item')].map(el => ({
    code: (el.querySelector('.course-code') || {}).textContent || '',
    checked: !!el.querySelector('input[type=checkbox]:checked'),
    tags: [...el.querySelectorAll('.tag')].map(t => t.textContent.trim()),
  }));
  const saved = JSON.parse(localStorage.getItem('%s') || '{}');
  return {
    rows: rows,
    checked: rows.filter(r => r.checked).map(r => r.code),
    note: (document.getElementById('recommended-note') || {}).textContent || '',
    restoreHidden: (document.getElementById('btn-restore-recommended') || {}).hidden,
    codes: saved.codes || [],
    autoSemester: saved.autoSemester || '',
    autoCodes: saved.autoCodes || [],
    manualCodes: saved.manualCodes || [],
    autoDropped: saved.autoDropped || [],
  };
}""" % STORAGE_KEY


@pytest.fixture(scope="module")
def server():
    """שרת מקומי על פורט פנוי, בלי רשת החוצה."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    srv = make_server("127.0.0.1", port, create_app(config={"allow_network": False}),
                      threaded=True)
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


def snap(page) -> dict:
    return page.evaluate(SNAPSHOT)


#: המסלול שיש לו תוכנית לימודים, ולכן זה שכל הבדיקות כאן מדברות עליו.
CURRICULUM_PROGRAM = "הנדסת תוכנה"


def choose(page, year: int, term: str, program: str = CURRICULUM_PROGRAM) -> dict:
    """בוחר זהות מלאה: מסלול, שנה וסמסטר.

    ‏המסלול נוסף כאן ב-2026-09-09. עד אז הוא נבחר אוטומטית — התוכנית של
    ``curriculum_program`` — ולכן הספיק לבחור שנה וסמסטר. מרגע ששלוש
    התיבות מתחילות ריקות, בחירה חלקית משאירה את שלב 2 נעול ואת הרשימה
    ריקה, וכל בדיקה שנשענת על ``choose`` הייתה נכשלת על תיבת חיפוש שאי
    אפשר להקליד בה — ולא על מה שהיא באמת בודקת.
    """
    page.select_option("#select-program", program)
    page.select_option("#select-year", str(year))
    page.select_option("#select-term", term)
    page.wait_for_timeout(1200)
    return snap(page)


def with_identity(page) -> dict:
    """בוחר את הזהות שהבדיקות כאן יצאו ממנה עד 2026-09-09.

    ‏עד אז שנה ג׳ + סמסטר א׳ + הנדסת תוכנה נקבעו אוטומטית מ-``profile.json``,
    ולכן בדיקה יכלה להתחיל לפעול על עמוד שכבר יש בו תוכנית. מרגע ששלוש
    התיבות מתחילות ריקות צריך לבחור אותן במפורש — וזה כל מה שהשורה הזאת
    עושה. שום טענה בבדיקות שמשתמשות בה לא השתנתה.
    """
    return choose(page, 3, "א")


# ==========================================================================
# 1. הבחירה בשלב 1 היא שמסמנת
# ==========================================================================
def test_choosing_an_identity_marks_that_semesters_plan(page):
    """הרשימה נגזרת מהבחירה — אחריה, לא לפניה.

    ‏עד 2026-09-09 הבדיקה הזאת נקראה
    ``test_a_fresh_visitor_gets_the_plan_for_the_chosen_semester`` והריצה
    את אותן שלוש הטענות על ``snap(page)`` **בלי לבחור דבר**: על הציור
    הראשון, ששת קורסי סמסטר 5 כבר היו מסומנים. זה היה נכון כל עוד שנה,
    סמסטר ומסלול נקבעו אוטומטית מ-``profile.json`` — כלומר כל עוד
    האפליקציה ניחשה מי הסטודנט/ית.

    ‏הניחוש הוסר בכוונה: שלב 1 הוא זהות, והאפליקציה אינה יודעת אותה.
    ‏"מבקר/ת חדש/ה מקבל/ת תוכנית" הוא בדיוק מה שהשינוי ביטל, ולכן הטענה
    הזאת אינה יכולה להישאר כפי שהייתה.

    ‏מה שכן נשאר נכון, ונבדק כאן ללא שינוי: **בהינתן** מסלול, שנה וסמסטר,
    הרשימה המסומנת היא בדיוק תוכנית הסמסטר ההוא, ואף קורס אינו נחשב
    "נוסף ידנית". שלוש הטענות זהות למה שהיו — רק הרגע שבו הן נבדקות זז.

    ‏הצד השני, שמבקר/ת חדש/ה **אינו/ה** מקבל/ת דבר, נבדק בנפרד ב-
    ``test_a_fresh_visitor_has_nothing_chosen_and_step_two_locked``.
    """
    state = with_identity(page)
    assert set(state["checked"]) == {"11069", "61756", "61757", "62027", "61759", "61832"}
    assert state["autoSemester"] == "5"
    assert state["manualCodes"] == []


def test_a_fresh_visitor_has_nothing_chosen_and_step_two_locked(page):
    """הצד השני של הבחירה: לפניה אין תוכנית, ואין ממה לבחור.

    ‏זו הטענה החיובית של השינוי מ-2026-09-09, ולא רק היעדר הטענה הישנה.
    שלוש התיבות פתוחות על ה-placeholder, שום קורס אינו מסומן, ושלב 2 נעול
    עם שורה שאומרת מה חסר — ולא ריק בלי הסבר, שנראה כמו תקלה.

    ‏ואז, ברגע שנבחרו שלושתם, השלב נפתח וההמלצה מופיעה. שני החצאים באותה
    בדיקה בכוונה: "נעול" בלי "ונפתח" היה עובר גם אם הנעילה לא נפתחת לעולם.
    """
    placeholders = page.evaluate(
        """() => ['select-program', 'select-year', 'select-term'].map(id => {
             const s = document.getElementById(id);
             return {id: id, value: s.value,
                     shown: s.selectedIndex >= 0
                       ? s.options[s.selectedIndex].textContent.trim() : null};
           })"""
    )
    for p in placeholders:
        assert p["value"] == "", f"{p['id']} מגיע מלא מראש: {p['value']!r}"
        assert p["shown"] and "בחר" in p["shown"], (
            f"{p['id']} מצויר ריק במקום להזמין לבחור: {p['shown']!r}")

    before = snap(page)
    assert before["checked"] == [], "אין תוכנית לפני שיודעים למי"
    assert before["codes"] == []
    assert before["autoSemester"] == ""

    locked = page.evaluate(
        "() => ({locked: document.getElementById('step-courses')"
        "                  .classList.contains('is-locked'),"
        "         why: (document.getElementById('step-courses-state')||{})"
        "                  .textContent || ''})"
    )
    assert locked["locked"], "שלב 2 חייב להיות נעול כל עוד אין זהות"
    assert locked["why"].strip(), "ונעילה בלי שורה שמסבירה אותה היא מסך שבור"

    # ואז הבחירה — ורק אחריה מופיעה הרשימה.
    after = with_identity(page)
    assert set(after["checked"]) == {
        "11069", "61756", "61757", "62027", "61759", "61832"
    }, "ההמלצה מופיעה ברגע שיש מסלול, שנה וסמסטר"
    assert after["autoSemester"] == "5"
    assert not page.evaluate(
        "() => document.getElementById('step-courses').classList.contains('is-locked')"
    ), "והשלב נפתח"


def test_a_fresh_visitor_does_not_inherit_the_profile_selection(page):
    """‏61753 הוא קורס של סמסטר 4 מ-``data/profile.json``. זו הייתה התקלה:
    הוא הופיע מסומן לכל מי שפתח/ה את העמוד, בלי קשר לסמסטר שנבחר."""
    assert "61753" not in snap(page)["codes"]


def test_changing_the_year_changes_what_is_marked(page):
    state = choose(page, 2, "א")
    assert state["autoSemester"] == "3"
    assert set(state["checked"]) == {"11129", "61739", "61774", "61778", "61911"}
    assert "61756" not in state["codes"], "קורסי הסמסטר הקודם יורדים"


# ==========================================================================
# 2. חלופות — נראות, לא מסומנות
# ==========================================================================
def test_placement_courses_are_shown_unchecked_with_a_reason(page):
    state = choose(page, 1, "א")
    shown = {row["code"]: row for row in state["rows"]}
    for code in ("11063", "11064", "11360"):
        assert code in shown, f"{code} חייב להופיע — אחרת אי אפשר לבחור ביניהם"
        assert not shown[code]["checked"], f"{code} הוא חלופה ולא מסומן מראש"
        assert any("חלופה" in tag for tag in shown[code]["tags"]), "בלי הסבר זה נראה כמו תקלה"
    assert set(state["checked"]) == {"251961", "11004", "11102", "61740", "61741"}


def test_neither_physics_track_is_marked(page):
    state = choose(page, 2, "ב")
    shown = {row["code"]: row for row in state["rows"]}
    for code in ("61179", "61180", "61181"):
        assert not shown[code]["checked"], f"{code} תלוי בפטור — הבחירה אינה של המערכת"
    assert set(state["checked"]) == {"61751", "61752", "61753", "61755"}


# ==========================================================================
# 3. קורס מסמסטר קודם — ידני, ושורד
# ==========================================================================
def add_by_search(page, code: str) -> None:
    page.fill("#course-search", code)
    page.wait_for_timeout(1400)
    page.click("#course-search-results li >> nth=0")
    page.wait_for_timeout(1000)


def test_a_manually_added_course_survives_a_semester_change(page):
    """המקרה שהתכונה נועדה לו: השלמת קורס מסמסטר קודם."""
    with_identity(page)
    add_by_search(page, "61739")  # קורס של סמסטר 3, בזמן שיושבים על סמסטר 5
    state = snap(page)
    assert state["manualCodes"] == ["61739"]
    assert "61739" in state["checked"]

    state = choose(page, 1, "א")
    assert "61739" in state["checked"], "מה שנוסף ביד לא יורד עם החלפת סמסטר"
    assert state["manualCodes"] == ["61739"]
    assert "61756" not in state["codes"], "וההמלצה הישנה כן יורדת"


def test_summer_drops_the_plan_and_keeps_the_manual_pick(page):
    """אין סמסטר קיץ בתוכנית. מסירים את מה שהמערכת סימנה — ורק אותו."""
    with_identity(page)
    add_by_search(page, "61739")
    page.select_option("#select-term", "קיץ")
    page.wait_for_timeout(1200)
    state = snap(page)
    assert state["codes"] == ["61739"]
    assert state["autoSemester"] == ""


#: מסלול שאין לו תוכנית לימודים כלל — אין לו פרק שנתון. הבדיקות שמתארות
#: "מסלול בלי תוכנית" חייבות להצביע עליו במפורש: מאז שכל מחלקה שיש לה פרק
#: קיבלה תוכנית משלה, "המסלול הראשון שאינו הנדסת תוכנה" הוא כבר מסלול
#: שכן יש לו תוכנית, והבדיקות היו בודקות את ההפך ממה שכתוב בשמן.
NO_CURRICULUM_PROGRAM = "הנדסת ביוטכנולוגיה"


def other_program(page) -> str:
    options = page.eval_on_selector_all("#select-program option", "els => els.map(e => e.value)")
    assert NO_CURRICULUM_PROGRAM in options, "המסלול חייב להופיע ברשימה"
    return NO_CURRICULUM_PROGRAM


def test_switching_program_drops_the_previous_program_plan(page):
    """מסלול אחר, תוכנית אחרת.

    שישה קורסי תוכנה מסומנים לסטודנט/ית להנדסה אזרחית הם בדיוק אותה תקלה
    שהתכונה הזאת נועדה לתקן — ומספר הסמסטר לבדו אינו מבחין ביניהם, כי הוא
    לא משתנה בהחלפת מסלול.
    """
    with_identity(page)
    assert "61756" in snap(page)["checked"], "מתחילים עם תוכנית הנדסת תוכנה"

    page.select_option("#select-program", other_program(page))
    page.wait_for_timeout(2000)
    state = snap(page)
    assert state["codes"] == [], "תוכנית של מסלול אחר יורדת מיד"
    assert state["autoSemester"] == ""


def test_a_program_without_a_curriculum_keeps_a_hand_built_list(page):
    """‏SPEC_MULTIFACULTY: בלי תוכנית לימודים הכול נבחר מהקטלוג, והמערכת
    לא נוגעת בבחירה שנבנתה ביד — היא מסירה רק מה שהיא עצמה סימנה."""
    with_identity(page)
    page.select_option("#select-program", other_program(page))
    page.wait_for_timeout(2000)
    # במצב קטלוג אותה תיבת חיפוש מזינה את רשימת הקטלוג שמתחתיה, ולא רשימה
    # נפתחת — ולכן הבחירה היא בתיבת הסימון שם.
    page.fill("#course-search", "11004")
    page.wait_for_timeout(1600)
    page.click("#catalog-results .course-item input >> nth=0")
    page.wait_for_timeout(1200)
    before = snap(page)
    assert before["manualCodes"] == ["11004"]

    for year, term in ((1, "א"), (4, "ב"), (3, "א")):
        page.select_option("#select-year", str(year))
        page.select_option("#select-term", term)
        page.wait_for_timeout(1100)
    assert snap(page)["codes"] == before["codes"], "החלפת שנה/סמסטר לא מוחקת בחירה ידנית"


# ==========================================================================
# 4. ביטול ידני נזכר
# ==========================================================================
def uncheck(page, code: str) -> dict:
    page.click(f"#course-list .course-item:has(.course-code:text-is('{code}')) input")
    page.wait_for_timeout(1000)
    return snap(page)


def test_unchecking_a_recommended_course_sticks_across_a_reload(page):
    """משיכה חוזרת של אותה רשימה אסור שתסמן מחדש מה שבוטל במפורש."""
    with_identity(page)
    state = uncheck(page, "61759")
    assert state["autoDropped"] == ["61759"]
    assert "61759" not in state["checked"]

    page.reload()
    page.wait_for_timeout(2000)
    state = snap(page)
    assert "61759" not in state["checked"], "הביטול נשמר גם אחרי רענון"
    assert state["autoDropped"] == ["61759"]
    assert state["restoreHidden"] is False, "יש מה להחזיר — הכפתור מוצג"


def test_restoring_the_recommended_list_brings_it_back(page):
    with_identity(page)
    uncheck(page, "61759")
    page.click("#btn-restore-recommended")
    page.wait_for_timeout(1000)
    state = snap(page)
    assert "61759" in state["checked"]
    assert state["autoDropped"] == []
    assert state["restoreHidden"] is True


def test_unchecking_one_tied_course_unchecks_the_whole_package(page):
    """‏61756+61757+62027 — הידיעון רושם אותם כחבילה אחת."""
    with_identity(page)
    state = uncheck(page, "61757")
    assert not ({"61756", "61757", "62027"} & set(state["checked"]))


# ==========================================================================
# 5. מצב שנשמר לפני התכונה — לא נמחק ולא מוחלף
# ==========================================================================
OLD_STATE = {
    "schema": 1,
    "studyYear": 3,
    "term": "א",
    "semester": "5",
    # בדיוק הבחירה מ-data/profile.json: כוללת קורס מסמסטר 4, וחסר בה 61759.
    "codes": ["61756", "61757", "62027", "61832", "11069", "61753"],
    "known": {},
    "targetDays": 4,
    "program": PROGRAM,
    "topN": 5,
    "activeSchedule": 0,
}


def test_an_existing_selection_is_adopted_and_not_overwritten(browser, server):
    ctx = browser.new_context()
    # הזרעה **לפני** שסקריפט כלשהו בדף רץ. כתיבה אחרי ``goto`` מתחרה בשמירה
    # הראשונה של האפליקציה עצמה, והמרוץ הזה נופל לשני הכיוונים.
    # התנאי על המפתח דואג שההזרעה תקרה פעם אחת, ולא שוב בכל ניווט.
    ctx.add_init_script(
        "if (!localStorage.getItem('%s')) localStorage.setItem('%s', %s);"
        % (STORAGE_KEY, STORAGE_KEY, json.dumps(json.dumps(OLD_STATE)))
    )
    p = ctx.new_page()
    try:
        p.goto(server)
        p.wait_for_timeout(2200)

        state = snap(p)
        assert sorted(state["codes"]) == sorted(OLD_STATE["codes"]), (
            "בחירה קיימת לא נמחקת ולא מוחלפת — רק מקבלת שיוך"
        )
        # ‏61753 אינו ברשימת ההמלצה של סמסטר 5 ⇒ הוא ידני, ולכן ישרוד החלפה.
        assert state["manualCodes"] == ["61753"]
        # ‏61759 כן ברשימה אבל לא היה מסומן ⇒ נחשב "בוטל", ולא יחזור מעצמו.
        assert state["autoDropped"] == ["61759"]

        p.select_option("#select-year", "2")
        p.select_option("#select-term", "א")
        p.wait_for_timeout(1300)
        state = snap(p)
        assert "61753" in state["checked"], "ההשלמה הידנית שורדת"
        assert "61756" not in state["codes"], "ההמלצה של סמסטר 5 יורדת"
    finally:
        ctx.close()


# ==========================================================================
# 6. שלוש תקלות שנמצאו בסקירה — כל אחת נשמרת כאן
# ==========================================================================
def test_a_late_answer_for_an_abandoned_semester_is_ignored(page):
    """מעבר לקיץ בזמן שתשובת הסמסטר הקודם עדיין באוויר.

    השומר ``seq.semester`` מגן רק אם **כל** מסלול שמשנה את הסמסטר המבוקש
    מקדם אותו. הענף של "אין סמסטר" לא קידם, ולכן התשובה המאוחרת עברה את
    השומר, החילה את ההמלצה של סמסטר 3 ושמרה אותה — בזמן שעל המסך קיץ.
    """
    def slow(route):
        """מרחיב את החלון שהמרוץ קורה בו. הוא קיים גם בלי ההשהיה — הוא פשוט
        נמדד במאיות שנייה, ובדיקה שנשענת על תזמון כזה אינה בדיקה."""
        time.sleep(2.0)
        route.continue_()

    page.route("**/api/semester/3/courses*", slow)

    page.select_option("#select-year", "2")  # סמסטר 3 — הבקשה יוצאת ומתעכבת
    page.wait_for_timeout(250)
    page.select_option("#select-term", "קיץ")  # ואז נוטשים אותה
    page.wait_for_timeout(3500)  # מספיק זמן לתשובה המאוחרת לנחות

    state = snap(page)
    assert state["autoSemester"] == "", "תשובה של סמסטר נטוש לא מחילה את ההמלצה שלו"
    assert state["codes"] == [], "ובוודאי לא שומרת אותה"


def test_a_semester_change_keeps_lecturer_ranking_and_attendance(page, browser, server):
    """הצצה בסמסטר אחר וחזרה אינה מוחקת עבודה עדינה.

    ‏``prunePicks`` נהג למחוק דירוג מרצים, נעיצות וחובות נוכחות לכל קוד שאינו
    מסומן. מרגע שהחלפת שנה/סמסטר מחליפה את רשימת הקורסים, זו הפכה למחיקה
    שקטה של בחירות שנעשו ביד — ובחזרה לסמסטר הן לא שבו.
    """
    seeded = dict(
        OLD_STATE,
        provenanceReady=True,
        autoSemester="5",
        autoCodes=["11069", "61756", "61757", "62027", "61759", "61832"],
        manualCodes=[],
        autoDropped=[],
        codes=["11069", "61756", "61757", "62027", "61759", "61832"],
        ranked={"61759": ["ד\"ר פלוני"]},
        attendance={"61759": {"תרגיל": False}},
    )
    ctx = browser.new_context()
    ctx.add_init_script(
        "if (!localStorage.getItem('%s')) localStorage.setItem('%s', %s);"
        % (STORAGE_KEY, STORAGE_KEY, json.dumps(json.dumps(seeded)))
    )
    p = ctx.new_page()
    try:
        p.goto(server)
        p.wait_for_timeout(2200)

        p.select_option("#select-year", "2")  # סמסטר 3 — 61759 יורד מהרשימה
        p.wait_for_timeout(1500)
        p.select_option("#select-year", "3")  # וחזרה
        p.wait_for_timeout(1800)

        kept = p.evaluate(
            "() => JSON.parse(localStorage.getItem('%s') || '{}')" % STORAGE_KEY
        )
        assert "61759" in kept.get("ranked", {}), "דירוג המרצים של 61759 שרד"
        assert "61759" in kept.get("attendance", {}), "חובת הנוכחות של 61759 שרדה"
        assert "61759" in (kept.get("codes") or []), "והקורס עצמו חזר לרשימה"
    finally:
        ctx.close()


SUMMER_STATE = {
    "schema": 1,
    "studyYear": 3,
    "term": "קיץ",
    "semester": "",
    "codes": ["11004", "61753"],
    "known": {},
    "program": PROGRAM,
    "topN": 5,
    "activeSchedule": 0,
}


def test_adoption_does_not_swallow_the_students_next_choice(browser, server):
    """מצב שמור מלפני התכונה, שנשמר בקיץ.

    האימוץ החד-פעמי שייך לסמסטר שהבחירה נשמרה בו. בלי הקישור הזה, הבחירה
    הראשונה שהסטודנט/ית עושים אחרי השדרוג — "שנה ג', סמסטר א'" — הייתה
    נבלעת: כל המלצת סמסטר 5 הייתה נרשמת כ"בוטלה", והרשימה נשארת ריקה.
    """
    ctx = browser.new_context()
    ctx.add_init_script(
        "if (!localStorage.getItem('%s')) localStorage.setItem('%s', %s);"
        % (STORAGE_KEY, STORAGE_KEY, json.dumps(json.dumps(SUMMER_STATE)))
    )
    p = ctx.new_page()
    try:
        p.goto(server)
        p.wait_for_timeout(2000)
        assert snap(p)["autoSemester"] == "", "בקיץ אין סמסטר בתוכנית"

        p.select_option("#select-year", "3")
        p.select_option("#select-term", "א")
        p.wait_for_timeout(1800)

        state = snap(p)
        assert state["autoSemester"] == "5"
        assert {"61756", "61757", "62027", "61832"} <= set(state["checked"]), (
            "ההמלצה של הסמסטר שנבחר מסומנת"
        )
        assert state["autoDropped"] == [], "ואיש לא ביטל אותה"
        # הבחירה הישנה שייכת לסטודנט/ית, ולכן היא ידנית ושורדת.
        assert set(SUMMER_STATE["codes"]) <= set(state["codes"])
    finally:
        ctx.close()


# ==========================================================================
# 7. תוכנית לימודים לכל מחלקה
# ==========================================================================
def test_another_department_gets_its_own_plan_not_software_engineering(page):
    """‏מספר הסמסטר אינו משתנה בהחלפת מסלול, ולכן "אותו סמסטר, אל תיגע"
    השאיר את רשימת הנדסת תוכנה מסומנת מתחת לקורסי האזרחית. הבעלות היא על
    צמד מסלול+סמסטר."""
    with_identity(page)
    assert "61756" in snap(page)["checked"], "מתחילים בהנדסת תוכנה"

    page.select_option("#select-program", "הנדסה אזרחית")
    page.wait_for_timeout(2200)
    state = snap(page)
    checked = set(state["checked"])
    assert not (checked & {"61756", "61757", "62027", "61832", "11069"}), (
        "אף קורס מתוכנית הנדסת תוכנה לא נשאר מסומן"
    )
    assert checked, "ויש רשימה משלה"
    assert all(c.startswith("42") for c in checked), (
        f"קורסי אזרחית מתחילים ב-42: {sorted(checked)}"
    )


def test_track_courses_are_shown_but_never_auto_checked(page):
    with_identity(page)
    page.select_option("#select-program", "הנדסה אזרחית")
    page.wait_for_timeout(2200)
    rows = {r["code"]: r for r in snap(page)["rows"]}
    tracked = {c: r for c, r in rows.items() if "מבנים" in r["tags"] or "ניהול הבנייה" in r["tags"]}
    assert tracked, "קורסי המסלולים מוצגים"
    for code, row in tracked.items():
        assert not row["checked"], f"{code} שייך למסלול ואין לסמן אותו אוטומטית"
    note = snap(page)["note"]
    assert "מסלול" in note, "וההסבר אומר למה הם ריקים"


def test_a_department_with_no_chapter_stays_on_the_catalog(page):
    """להנדסת ביוטכנולוגיה אין פרק שנתון כלל. אסור שתקבל לוח סמסטרים של
    מחלקה אחרת, ואסור שתראה "סמסטר 5 בתוכנית הלימודים"."""
    with_identity(page)
    page.select_option("#select-program", "הנדסת ביוטכנולוגיה")
    page.wait_for_timeout(2200)
    state = snap(page)
    assert state["autoSemester"] == ""
    assert state["codes"] == []
    summary = page.evaluate(
        "() => (document.getElementById('semester-summary')||{}).textContent || ''"
    )
    # ‏"אין סמסטר תואם בתוכנית הלימודים" הוא המשפט הנכון, והוא מכיל את אותן
    # מילים — ולכן הבדיקה היא על ההצהרה עצמה: "סמסטר <מספר> בתוכנית".
    assert not re.search(r"סמסטר\s*\d+\s*בתוכנית", summary), (
        f"אין להצהיר על סמסטר בתוכנית למסלול שאין לו תוכנית: {summary!r}"
    )
    assert "אין סמסטר תואם" in summary, f"וצריך לומר זאת במפורש: {summary!r}"


def test_the_page_raises_no_javascript_errors(page):
    choose(page, 1, "א")
    choose(page, 4, "ב")
    add_by_search(page, "61739")
    assert page.errors == [], f"שגיאות JavaScript בדף: {page.errors}"
