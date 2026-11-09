"""חיפוש ועיון בקטלוג: "בתוכנית" מול המסלול של הסטודנט/ית, ולמי שייך כל קורס.

הבעיה (2026-11-09): חיפוש "פיזיקה 2" החזיר חמישה קורסים כמעט זהים —
‏11026 ‏פיזיקה 2ב, ‏11210 ‏פיזיקה 2 IE, ‏11212 ‏פיזיקה 2 מכ', ‏11232 ‏פיזיקה 2 מ',
‏421209 ‏פיזיקה 2 אז' — וכולם סומנו "[מחוץ לתוכנית]", גם לסטודנט/ית
מתעשייה וניהול שהפיזיקה שלהם היא ‏11210. שתי סיבות:

1. ‏``/api/catalog/search`` סימן מול ``_curriculum()`` בלי ארגומנטים — תוכנית
   ברירת המחדל, הנדסת תוכנה — והממשק לא שלח מסלול. ‏``/api/catalog/browse``
   סבל מאותו דבר.
2. שום דבר לא אמר של מי כל אחד מהם. עכשיו כל שורה נושאת ``programs``.

‏**המזהה של מסלול הוא השם שלו ב-``data/programs.json``** — "הנדסת תעשייה
וניהול" — ולא ה-slug ("industry"): זה מה שהממשק שולח לכל נקודת קצה.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src.web.api import create_app  # noqa: E402

INDUSTRY = "הנדסת תעשייה וניהול"
MATH = "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה"

#: כל גרסה של פיזיקה 2 נמצאת בקובץ תוכנית אחד בדיוק תחת data/curricula/.
PHYSICS_2_OWNERS = {
    "11026": ["הנדסת ביוטכנולוגיה"],
    "11210": ["הנדסת תעשייה וניהול"],
    "11212": ["הנדסת מכונות"],
    "11232": ["הנדסת חשמל ואלקטרוניקה"],
    "421209": ["הנדסה אזרחית"],
}


@pytest.fixture(scope="module")
def client():
    return create_app(config={"allow_network": False}).test_client()


def search(client, q: str, **params) -> list[dict]:
    resp = client.get("/api/catalog/search", query_string={"q": q, "limit": 25, **params})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["results"]


def browse(client, **params) -> list[dict]:
    resp = client.get("/api/catalog/browse", query_string={"limit": 50, **params})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["results"]


# ---------------------------------------------------------------- the report
def test_industry_physics_2_is_in_plan_and_every_result_has_its_programs(client):
    rows = search(client, "פיזיקה 2", program=INDUSTRY)
    by_code = {r["code"]: r for r in rows}
    assert set(PHYSICS_2_OWNERS) <= set(by_code), sorted(by_code)

    mine = by_code["11210"]
    assert mine["in_curriculum"] is True, mine
    assert mine["curriculum_semester"] == "3", mine
    assert mine["tag"] == "[בתוכנית-סמסטר 3]", mine

    for code in PHYSICS_2_OWNERS.keys() - {"11210"}:
        assert by_code[code]["in_curriculum"] is False, by_code[code]

    for row in rows:
        assert isinstance(row.get("programs"), list), row
    for code, owners in PHYSICS_2_OWNERS.items():
        assert by_code[code]["programs"] == owners, (code, by_code[code]["programs"])


def test_the_students_own_course_comes_first(client):
    rows = search(client, "פיזיקה 2", program=INDUSTRY)
    assert rows[0]["code"] == "11210", [r["code"] for r in rows]


def test_in_plan_courses_are_ranked_before_the_limit_cuts(client):
    """"פיזיקה" מחזיר 18 קורסים. עם limit=2 שני הראשונים חייבים להיות של תעשייה וניהול."""
    rows = search(client, "פיזיקה", program=INDUSTRY, limit=2)
    assert [r["in_curriculum"] for r in rows] == [True, True], rows
    assert {r["code"] for r in rows} <= {"11209", "11210", "11179"}, rows


def test_an_exact_code_still_comes_first(client):
    rows = search(client, "11026", program=INDUSTRY)
    assert rows[0]["code"] == "11026", [r["code"] for r in rows]
    assert rows[0]["in_curriculum"] is False


# ------------------------------------------------- what must not change
def test_without_a_program_nothing_changes(client):
    """בלי ``program``: תוכנית ברירת המחדל, ובסדר של search_catalog."""
    rows = search(client, "פיזיקה 2")
    assert [r["code"] for r in rows] == ["11026", "11210", "11212", "11232", "421209"]
    assert all(r["in_curriculum"] is False for r in rows), rows
    assert all(isinstance(r["programs"], list) for r in rows)


def test_a_default_plan_semester_does_not_leak_into_another_program(client):
    """‏61753 הוא סמסטר 4 בהנדסת תוכנה ואינו בתוכנית של תעשייה וניהול."""
    software = search(client, "61753")[0]
    assert software["in_curriculum"] is True and software["curriculum_semester"] == "4"

    industry = search(client, "61753", program=INDUSTRY)[0]
    assert industry["code"] == "61753"
    assert industry["in_curriculum"] is False, industry
    assert industry["curriculum_semester"] is None, industry
    assert industry["tag"] == "[מחוץ לתוכנית]", industry


def test_other_program_has_nothing_in_plan(client):
    rows = search(client, "פיזיקה 2", program="other")
    assert all(r["in_curriculum"] is False for r in rows), rows
    assert {r["code"]: r["programs"] for r in rows if r["code"] in PHYSICS_2_OWNERS} == PHYSICS_2_OWNERS


# ------------------------------------------------- programs with intakes
def test_an_intake_program_is_annotated_against_that_intake(client):
    rows = {r["code"]: r for r in search(client, "חדו", program=MATH, intake="winter")}
    assert rows["11004"]["in_curriculum"] is True, rows["11004"]
    assert rows["11003"]["in_curriculum"] is False, rows["11003"]


def test_an_intake_program_without_an_intake_has_nothing_in_plan(client):
    rows = search(client, "חדו", program=MATH)
    assert all(r["in_curriculum"] is False for r in rows), rows


def test_an_intake_program_is_listed_once_by_its_label(client):
    """שני קובצי מתמטיקה שימושית (חורף, אביב) — שם אחד, פעם אחת."""
    row = {r["code"]: r for r in search(client, "חדו")}["11004"]
    assert row["programs"].count("מתמטיקה שימושית") == 1, row["programs"]
    assert MATH not in row["programs"], "השם שמוצג הוא program_label, לא המזהה"
    assert row["programs"] == sorted(row["programs"])


# ---------------------------------------------------------------- browse
def test_browse_annotates_against_the_students_program(client):
    without = {r["code"]: r for r in browse(client, prefix="1121")}
    assert without["11210"]["in_curriculum"] is False

    rows = {r["code"]: r for r in browse(client, prefix="1121", program=INDUSTRY)}
    assert rows["11210"]["in_curriculum"] is True, rows["11210"]
    assert rows["11210"]["programs"] == ["הנדסת תעשייה וניהול"]
    assert rows["11212"]["in_curriculum"] is False
    assert rows["11212"]["programs"] == ["הנדסת מכונות"]


def test_browse_keeps_code_order_with_a_program(client):
    rows = browse(client, prefix="112", program=INDUSTRY)
    codes = [int(r["code"]) for r in rows]
    assert codes == sorted(codes), codes


def test_a_course_no_curriculum_lists_has_an_empty_programs_list(client):
    rows = browse(client, prefix="112", program=INDUSTRY)
    assert any(r["programs"] == [] for r in rows), "ציפיתי לקורס שאף תוכנית אינה כוללת"
