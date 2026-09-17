"""לכל מחלקה שיש לה פרק שנתון — תוכנית לימודים משלה.

הרקע
----
עד השינוי הזה היה בפרויקט קובץ תוכנית **אחד**, ``data/curriculum.json``,
שנגזר מפרק הנדסת תוכנה. שלב 2 ידע להמליץ על קורסי סמסטר רק למי שלומד/ת
הנדסת תוכנה; כל השאר קיבלו חיפוש בקטלוג, גם כשלמחלקה שלהם יש פרק שנתון
מלא עם טבלת קורסים לכל סמסטר.

עכשיו יש קובץ תוכנית לכל מחלקה תחת ``data/curricula/``, והשרת בוחר את
התוכנית לפי המסלול שנשלח ב-``?program=``.

מה **לא** נעשה כאן, בכוונה
--------------------------
1. **לא הומצאה תוכנית למי שאין לו.** ‏**עודכן 2026-09-17:** ביוטכנולוגיה
   ותעשייה וניהול קיבלו קובץ תוכנית משלהן — לביוטכנולוגיה הגיע מסמך קורסי
   חובה, ותעשייה וניהול מיוצגת דרך מנגנון ה-``track`` הקיים (ליבה משותפת
   בסמסטרים 1–2, ומסמסטר 3 קורס שמופיע רק באחת ההתמחויות מסומן בשמה).
   מתמטיקה שימושית **נשארת** מול הקטלוג: התוכנית מודפסת פעמיים לפי מועד
   הקבלה ואין ולו סמסטר אחד משותף, ורשימה שטוחה אחת הייתה שגויה לחצי
   מהסטודנטים.
2. **לא הומצא מסלול התמחות.** מחלקות אחדות מפצלות חלק מהסמסטרים לפי מסלול,
   ובהנדסה אזרחית המסלול נקבע לפי ציונים — הסטודנט/ית אולי אינם יודעים
   את התשובה בעצמם. קורס של מסלול מסומן ב-``track`` ו**לעולם אינו נבחר
   אוטומטית**, בדיוק כמו קורס השמה או מסלול פיזיקה.
3. **לא הומצאה שנה וסמסטר.** אף פרק שנתון אינו כותב אותם ליד הטבלאות. הם
   נגזרים ממספר הסמסטר, וכל סמסטר נושא ``year_term_inferred: true``.
4. **לא הומצאה שנת מחזור.** רק שני פרקים מציינים אותה. בשאר ``cohort_year``
   הוא ``null`` — ה-``תשפ"X`` שמופיע בהם מדבר על דברים אחרים לגמרי.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src.web.api import create_app  # noqa: E402

CURRICULA_DIR = ROOT / "data" / "curricula"

#: המחלקות שיש להן קובץ תוכנית, ומספר הסמסטר שנבדק לכל אחת.
WITH_PLAN = {
    "הנדסת תוכנה": "5",
    "הנדסת מערכות מידע": "5",
    "הנדסת חשמל ואלקטרוניקה": "3",
    "הנדסה אזרחית": "5",
    "הנדסת מכונות": "5",
    # נוספו ב-2026-09-17. הפרטים שלהן ב-tests/test_biotech_curriculum.py
    # וב-tests/test_industry_curriculum.py.
    "הנדסת ביוטכנולוגיה": "3",
    "הנדסת תעשייה וניהול": "3",
}

#: מחלקות שנשארות מול הקטלוג, ולמה.
WITHOUT_PLAN = {
    "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה": "התוכנית מודפסת פעמיים, לפי מועד הקבלה",
}


@pytest.fixture()
def client():
    return create_app(config={"allow_network": False}).test_client()


def semester(client, sem: str, program: str) -> dict:
    res = client.get(f"/api/semester/{sem}/courses?program={program}")
    assert res.status_code == 200, f"{program} סמסטר {sem} החזיר {res.status_code}"
    return res.get_json()


# ==========================================================================
# 1. הקבצים עצמם
# ==========================================================================
def test_every_curriculum_file_is_valid_and_names_its_program():
    assert CURRICULA_DIR.is_dir(), "תיקיית תוכניות הלימודים חייבת להתקיים"
    files = sorted(CURRICULA_DIR.glob("*.json"))
    assert files, "אין אף קובץ תוכנית"
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("program"), f"{path.name}: חסר שם מסלול"
        assert data.get("semesters"), f"{path.name}: אין סמסטרים"
        for key, sem in data["semesters"].items():
            assert sem.get("year_term_inferred") is True, (
                f"{path.name} סמסטר {key}: שנה וסמסטר נגזרים ואינם כתובים בשנתון, "
                "ולכן חייב לשאת את הדגל"
            )
            for course in sem.get("courses") or []:
                assert course.get("prereq") == [], (
                    f"{path.name} סמסטר {key}: קורסי קדם לא חולצו במכוון"
                )


def test_a_cohort_year_is_only_claimed_where_the_document_states_one():
    """‏חמישה מתוך שבעת הפרקים אינם מציינים שנת מחזור, וה-``תשפ"X`` שמופיע
    בהם מדבר על מועד בחינה או על היסטוריה של המחלקה."""
    stated = {"הנדסת תוכנה", "הנדסת מערכות מידע"}
    for path in sorted(CURRICULA_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        year = data.get("cohort_year")
        if data["program"] in stated:
            continue
        assert not year, f"{path.name}: אין לנחש שנת מחזור ({year!r})"


# ==========================================================================
# 2. השרת בוחר תוכנית לפי מסלול
# ==========================================================================
@pytest.mark.parametrize("program,sem", sorted(WITH_PLAN.items()))
def test_a_program_with_a_chapter_gets_its_own_courses(client, program, sem):
    data = semester(client, sem, program)
    assert data["curriculum_available"] is True, f"{program}: אמורה להיות תוכנית"
    assert data["count"] > 0
    assert data["program"] == program, "התוכנית שהוחזרה חייבת להיות של המסלול שנשאל"


def test_each_program_gets_different_courses(client):
    """הבדיקה שהייתה נכשלת קודם: כולם קיבלו את קורסי הנדסת תוכנה."""
    sets = {}
    for program, sem in WITH_PLAN.items():
        codes = {c["code"] for c in semester(client, sem, program)["courses"] if c["code"]}
        sets[program] = codes
    software = sets["הנדסת תוכנה"]
    for program in ("הנדסה אזרחית", "הנדסת מכונות", "הנדסת חשמל ואלקטרוניקה"):
        assert not (sets[program] & software), (
            f"{program} קיבל/ה קורסי הנדסת תוכנה — זו בדיוק התקלה"
        )


@pytest.mark.parametrize("program,why", sorted(WITHOUT_PLAN.items()))
def test_a_program_without_a_usable_plan_falls_back_to_the_catalog(client, program, why):
    data = semester(client, "5", program)
    assert data["curriculum_available"] is False, f"{program}: {why}"
    assert data["courses"] == []
    assert data["note"], "חייב לומר למה, ולא להשאיר מסך ריק בלי הסבר"


# ==========================================================================
# 3. מסלולי התמחות — מוצגים, לא נבחרים
# ==========================================================================
def test_track_courses_are_marked_and_named(client):
    data = semester(client, "5", "הנדסה אזרחית")
    tracked = [c for c in data["courses"] if c["track"]]
    shared = [c for c in data["courses"] if not c["track"]]
    assert tracked, "לסמסטר 5 באזרחית יש קורסי מסלול"
    assert shared, "ויש גם ליבה משותפת"
    assert {c["track"] for c in tracked} == {"מבנים", "ניהול הבנייה"}


def test_the_recommendation_rule_never_picks_a_track_course(client):
    """אותו כלל של קורסי השמה ומסלול פיזיקה, מיושם על מסלולי התמחות."""
    from tests.test_recommended_defaults import recommended_codes  # noqa: PLC0415

    for program in ("הנדסה אזרחית", "הנדסת מכונות"):
        data = semester(client, "5", program)
        picked = set(recommended_codes(data))
        by_code = {c["code"]: c for c in data["courses"] if c["code"]}
        for code in picked:
            assert not by_code[code]["track"], (
                f"{program}: {code} שייך למסלול {by_code[code]['track']} ואין לסמן אותו"
            )
        assert picked, f"{program}: הליבה המשותפת כן נבחרת"


def test_a_semester_that_does_not_reconcile_says_so(client):
    """‏מכונות הוא הפרק היחיד שהחשבון שלו אינו נסגר בכמה סמסטרים. עדיף
    להציג את הרשימה עם הסתייגות מאשר להעמיד פנים שהיא מדויקת."""
    data = semester(client, "5", "הנדסת מכונות")
    assert data["info"]["reconciles"] is False
    assert data["info"]["semester_note"], "אי-התאמה חייבת לבוא עם הסבר"


# ==========================================================================
# 4. לוח הסמסטרים לכל מסלול
# ==========================================================================
def test_bootstrap_carries_a_semester_table_per_program(client):
    """הדפדפן ממפה שנה+סמסטר למספר סמסטר לפני כל משיכה, ולכן הוא חייב את
    הלוח של כל מסלול כבר בטעינה."""
    data = client.get("/api/bootstrap").get_json()
    by_program = data["semesters_by_program"]
    for program in WITH_PLAN:
        assert program in by_program, f"{program} חסר מהלוח"
        assert by_program[program], f"{program}: לוח ריק"
    for program in WITHOUT_PLAN:
        assert program not in by_program, (
            f"{program} אינו אמור לקבל לוח — אחרת יוצג לו סמסטר של מחלקה אחרת"
        )


def test_the_program_list_marks_who_has_a_curriculum(client):
    data = client.get("/api/bootstrap").get_json()
    flags = {p["id"]: p.get("has_curriculum") for p in data["programs"]}
    for program in WITH_PLAN:
        assert flags.get(program) is True, f"{program} אמור להיות מסומן כבעל תוכנית"
    for program in WITHOUT_PLAN:
        assert flags.get(program) is False, f"{program} אינו בעל תוכנית"
