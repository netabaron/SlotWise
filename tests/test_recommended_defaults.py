"""הבחירה בשלב 1 היא שקובעת מה מסומן בשלב 2.

הרקע
----
עד התיקון הזה רשימת הקורסים המסומנים נבנתה **פעם אחת**, מ-``defaults.codes``
של ``/api/bootstrap`` — כלומר מ-``data/profile.json``, הבחירה האישית של
סטודנט/ית אחד/ת. היא כללה גם את 61753, קורס של סמסטר 4. התוצאה: כל מי שפתח/ה
את העמוד קיבל/ה את אותם שישה קורסים מסומנים, ובחירת שנה וסמסטר אחרים החליפה
את *הרשימה המוצגת* אבל לא את *מה שמסומן* — כך שסטודנט/ית בשנה ב' ראו את
קורסי סמסטר 3 ריקים, ומתחתם שישה קורסים מסומנים מסמסטר 5.

התיקון: מה שמסומן הוא רשימת ההמלצה של הסמסטר שנבחר, וקורס שצריך להשלים
מסמסטר קודם מתווסף ידנית דרך תיבת החיפוש.

הקובץ הזה מכסה את צד השרת ואת **הכלל** עצמו. צד הלקוח — הפרדת "אוטומטי"
מ"ידני", האימוץ החד-פעמי של מצב שמור, וההתנהגות בהחלפת סמסטר — נבדק
ב-``test_recommended_defaults_browser.py``.

מה **לא** נעשה כאן, בכוונה
--------------------------
1. השרת אינו מסנן שורות. חלופה שאין לסמן אוטומטית מקבלת **דגל**, ונשארת
   ברשימה: הסטודנט/ית חייבים לראות את שלוש רמות האנגלית כדי לבחור אחת.
   סינון בשרת היה גם שובר את ``test_multifaculty`` וגם מסתיר מידע אמיתי.
2. אין הסקה של חלופיות מ-``group`` או מ-``cond``. ‏11069 (אנגלית טכנית) הוא
   ``group: "english"`` ויש לו ``cond``, והוא קורס חובה גמור — כלל כזה היה
   מבטל בטעות את קורס האנגלית היחיד של סמסטר 5.
3. אין ניחוש מה כבר נלמד. המערכת לא יודעת מה עבר, מה נכשל ומה נדחה, ולכן
   היא לא מציעה השלמות — היא רק אומרת מה כתוב בתוכנית לסמסטר הזה.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src.web.api import create_app  # noqa: E402

PROGRAM = "הנדסת תוכנה"


@pytest.fixture()
def client():
    return create_app().test_client()


def semester(client, sem: str) -> dict:
    res = client.get(f"/api/semester/{sem}/courses?program={PROGRAM}")
    assert res.status_code == 200, f"סמסטר {sem} החזיר {res.status_code}"
    return res.get_json()


def by_code(data: dict) -> dict:
    return {c["code"]: c for c in data["courses"] if c.get("code")}


# ==========================================================================
# 1. השדות שמסמנים חלופה הדדית
# ==========================================================================
def test_every_row_carries_both_alternative_flags(client):
    """גם שורה בלי קוד. שדה חסר בחלק מהשורות הוא בדיוק מה ששולח את הממשק
    לנחש, ואת זה אין לו במה לעשות."""
    for sem in "12345678":
        for course in semester(client, sem)["courses"]:
            assert isinstance(course.get("placement"), bool), f"סמסטר {sem}: placement חסר"
            assert isinstance(course.get("physics_track"), str), f"סמסטר {sem}: physics_track חסר"


def test_the_english_and_hebrew_placement_courses_are_flagged(client):
    """קורסי השמה: הרמה נקבעת לפי ציון פסיכומטרי או יע\"ל, ורק אחת שייכת."""
    sem1 = by_code(semester(client, "1"))
    for code in ("11063", "11064", "11360"):
        assert sem1[code]["placement"] is True, f"{code} הוא קורס השמה"

    sem2 = by_code(semester(client, "2"))
    for code in ("11060", "11361"):
        assert sem2[code]["placement"] is True, f"{code} הוא קורס השמה"


def test_technical_english_is_not_a_placement_course(client):
    """‏11069 הוא ``group: english`` ויש לו ``cond`` — ובכל זאת קורס חובה.

    זו בדיוק המלכודת: כלל שנשען על ``group`` או על ``cond`` היה מבטל את קורס
    האנגלית היחיד של סמסטר 5, שהוא גם קדם לפרויקט הגמר ולתריסר קורסי בחירה.
    """
    course = by_code(semester(client, "5"))["11069"]
    assert course["placement"] is False, "11069 הוא קורס חובה, לא חלופת השמה"
    assert course["group"] == "english", "השדה שמטעה עדיין שם — ולכן הבדיקה הזאת קיימת"


def test_the_physics_track_split_is_flagged(client):
    """‏61179+61180 למי שאין פטור, 61181 למי שיש. אחד מהשניים, לא שניהם."""
    sem4 = by_code(semester(client, "4"))
    assert sem4["61179"]["physics_track"] == "no_exemption"
    assert sem4["61180"]["physics_track"] == "no_exemption"
    assert sem4["61181"]["physics_track"] == "exemption"
    assert set(sem4["61179"]["tied_with"]) == {"61180"}, "61179 ו-61180 נלקחים יחד"


def test_the_demo_semester_has_no_alternatives_at_all(client):
    """סמסטר 5 כולו חובה — ולכן כולו אמור להיות מסומן מראש."""
    for course in semester(client, "5")["courses"]:
        assert course["placement"] is False
        assert course["physics_track"] == ""


# ==========================================================================
# 2. השורות עצמן לא נעלמות
# ==========================================================================
def test_alternatives_stay_in_the_list(client):
    """אי-סימון הוא דגל, לא הסרה. מי שלא רואה את שלוש רמות האנגלית לא יכול
    לבחור ביניהן, וגם ``test_multifaculty`` קורא את השורות האלה."""
    sem1 = semester(client, "1")
    codes = {c.get("code") for c in sem1["courses"]}
    assert {"11063", "11064", "11360"} <= codes
    assert any(c.get("code") is None for c in sem1["courses"]), "קורס כללי/ספורט נשארים"
    assert {"61179", "61180", "61181"} <= {c.get("code") for c in semester(client, "4")["courses"]}


def test_the_catalog_population_signal_reaches_the_client(client):
    """בלי המספר הזה אי אפשר להבחין בין "לא נפתח" לבין "אין נתונים".

    קטלוג ריק מחזיר ``offered: false`` לכל שורה. להסיק מזה שאף קורס אינו
    נפתח היה משאיר התקנה טרייה עם רשימה ריקה ובלי שום הסבר.
    """
    count = semester(client, "5")["fallback"]["catalog_count"]
    assert isinstance(count, int) and count >= 0


# ==========================================================================
# 3. הכלל עצמו
# ==========================================================================
def recommended_codes(data: dict) -> list[str]:
    """הכלל שהממשק מיישם, בפייתון — כדי שיהיה לו מנוע בדיקות.

    התאום שלו הוא ``recommendedCodes()`` ב-``src/web/static/app.js``.
    """
    courses = data["courses"]
    known_offered = data["fallback"]["catalog_count"] > 0
    index = by_code(data)

    def selectable(course: dict) -> bool:
        if not course or not course.get("code"):
            return False  # "קורס כללי", "ספורט" — אין קוד לסמן
        if course.get("placement") is True:
            return False
        if course.get("physics_track"):
            return False
        # קורס של מסלול התמחות. אותו היגיון בדיוק: הכלי אינו יודע באיזה
        # מסלול הסטודנט/ית, ובהנדסה אזרחית המסלול נקבע לפי ציונים.
        if course.get("track"):
            return False
        if known_offered and course.get("offered") is False:
            return False
        return True

    decided: dict[str, bool] = {}
    for course in courses:
        code = course.get("code")
        if not code or code in decided:
            continue
        # חבילת קורסים צמודים נבחנת כיחידה: חבר אחד שנפסל מפיל את כולה,
        # כי חצי חבילה היא בדיוק מה שהידיעון דוחה.
        family = [c for c in {code, *(course.get("tied_with") or [])} if c in index]
        good = all(selectable(index[c]) for c in family)
        for member in family:
            decided[member] = good
    return [c["code"] for c in courses if c.get("code") and decided.get(c["code"])]


def test_the_rule_marks_the_whole_of_semester_five(client):
    assert set(recommended_codes(semester(client, "5"))) == {
        "11069", "61756", "61757", "62027", "61759", "61832",
    }


def test_the_rule_skips_placement_courses_and_codeless_rows(client):
    assert set(recommended_codes(semester(client, "1"))) == {
        "251961", "11004", "11102", "61740", "61741",
    }


def test_the_rule_skips_both_physics_tracks(client):
    """אף אחד משלושת קורסי הפיזיקה לא נבחר אוטומטית — הבחירה תלויה בפטור."""
    picked = set(recommended_codes(semester(client, "4")))
    assert picked == {"61751", "61752", "61753", "61755"}
    assert not picked & {"61179", "61180", "61181"}


def test_the_rule_keeps_tied_courses_together(client):
    """‏61756+61757+62027 — או שלושתם, או אף אחד."""
    picked = set(recommended_codes(semester(client, "5")))
    tied = {"61756", "61757", "62027"}
    assert tied <= picked or not (tied & picked)


def test_a_cancelled_course_is_not_marked_when_the_catalog_knows(client):
    """‏61912 בוטל מתשפ\"ז והוחלף ב-62018. סימון שלו היה בונה מערכת שאין לה
    פתרון, ולכן הוא יוצא — אבל **רק** כשיש קטלוג להישען עליו."""
    data = semester(client, "3")
    if data["fallback"]["catalog_count"] == 0:
        pytest.skip("אין קטלוג משוך — ל-offered אין משמעות, ואין מה לבדוק")
    if by_code(data)["61912"]["offered"] is not False:
        pytest.skip("הקטלוג הנוכחי כן מכיר את 61912")
    assert "61912" not in recommended_codes(data)


def test_an_empty_catalog_does_not_empty_the_recommendation(client):
    """ההגנה מפני התקנה טרייה: בלי קטלוג לא מסיקים כלום מ-``offered``."""
    data = semester(client, "5")
    blind = dict(data, fallback={"catalog_count": 0})
    blind["courses"] = [dict(c, offered=False) for c in data["courses"]]
    assert len(recommended_codes(blind)) == 6, "קטלוג ריק אינו 'שום קורס לא נפתח'"
