"""
טבלת תיקוני השמות — ``data/name_corrections.json`` (2026-09-26).

שמות שאושרו במפורש, לקודים שהידיעון קוטע (40 תווים) או שהשנתון מדפיס
בשגיאה. הטבלה גוברת על כל מקור אחר, והיא מוחלת בשתי נקודות בלבד:
בטעינת כל קובץ תוכנית (``curriculum.normalize_names``) ובכל שם ידיעון
שהשרת מגיש (``api._restored_name``). הקבצים עצמם נשארים כפי שחולצו.
docs/PROGRAM_FINDINGS.md סעיף 10.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import curriculum as curriculum_mod  # noqa: E402
from web.api import create_app  # noqa: E402

CONFIRMED = {
    "421223": "מבוא לאלגוריתמיקה ותכנות",
    "31032": "בחינת סווג-יסודות הפיזיקה-חשמל ואלקטרוניקה",
    "41526": "קינטיקה ותכנון ריאקטורים כימיים וביולוגיים",
    "43101": "תקינה ופיתוח מוצרים ביוטכנולוגיים ורפואיים",
    "81561": "נושאים מתמטיים נבחרים למורים למתמטיקה",
    "51742": "הסתברות ויסודות הסטטיסטיקה להנדסת אלקטרוניקה",
    "11375": "פרשיות סוערות במשפט ישראלי",
    "81403": "התנסות מעשית בהוראת מתמטיקה והנדסה משלב 1",
    "81404": "התנסות מעשית בהוראת מתמטיקה והנדסה משלב 2",
    "51170": "נושא אישי 1",
    "51156": "מבוא להנדסת מערכות שירות",
}

#: מתי הוחלט כל שם. ‏51170 ו-51156 נוספו מ-industry.pdf (עמ' 13, 14).
DECIDED = {code: "2026-09-26" for code in CONFIRMED}
DECIDED.update({"51170": "2026-09-27", "51156": "2026-09-27"})

#: אינם בקטלוג, ולכן חיפוש בקטלוג אינו מחזיר אותם. שמם נבדק על השבבים
#: והכרטיסים של "רשימת בחירה מחייבת": tests/test_courses_step_notes.py.
NOT_IN_CATALOG = {"51170", "51156"}

#: שאר הרשימה מ-PROGRAM_FINDINGS §10 — הוחלט להשאיר כפי שהידיעון כותב.
UNCHANGED = {
    "11578": "חינוך וטכנולוגיה בעידן המהפכה התעשייתית",
    "11871": "שילוב טכנולוגיות מתקדמות בהוראה ובהדרכה",
    "31033": "יסודות הפיזיקה - הנדסת חשמל ואלקטרוניקה",
    "51963": "פיתוח מערכות ארגוניות בעזרת Vibe Coding",
    "81280": "מבוא להוראת המקצועות העיוניים ההתנסותיים",
    "81578": "חינוך וטכנולוגיה בעידן המהפכה התעשייתית",
    "81671": "שילוב טכנולוגיות מתקדמות בהוראה ובהדרכה",
    "85405": "פרויקט אינדוודואלי בהוראת הנדסה ומתמטיקה",
    "51023": "פרוייקט גמר בהתמחות מדעי הנתונים שלב א'",
    "51024": "פרוייקט גמר בהתמחות מדעי הנתונים שלב ב'",
    "51230": "פרויקט גמר בהתמחות תכן ותפעול שלב א'",
    "51231": "פרויקט גמר בהתמחות תכן ותפעול שלב ב'",
}


@pytest.fixture(scope="module")
def client():
    return create_app(config={"allow_network": False}).test_client()


def searched(client, code: str) -> str:
    rows = client.get(f"/api/catalog/search?q={code}").get_json()["results"]
    return {r["code"]: r["name"] for r in rows}[code]


def served(client, codes, program: str, semester: str = "ב") -> dict[str, str]:
    body = {"codes": codes, "semester": semester, "program": program, "fetch_missing": False}
    data = client.post("/api/courses", json=body).get_json()
    return {r["code"]: r["name"] for r in data["courses"] + data["not_offered"]}


# --- הטבלה עצמה ----------------------------------------------------------
def test_the_table_holds_exactly_the_confirmed_names():
    assert curriculum_mod.load_name_corrections() == CONFIRMED


def test_every_row_records_what_it_replaced_and_when():
    raw = json.loads((ROOT / "data" / "name_corrections.json").read_text(encoding="utf-8"))
    for code, row in raw["corrections"].items():
        assert row["was"].strip(), code
        assert row["decided"] == DECIDED[code], code


def test_a_missing_table_corrects_nothing(tmp_path):
    assert curriculum_mod.load_name_corrections(tmp_path / "missing.json") == {}


# --- השם המאושר בכל מקום ---------------------------------------------------
@pytest.mark.parametrize(
    "code, name", sorted((c, n) for c, n in CONFIRMED.items() if c not in NOT_IN_CATALOG)
)
def test_catalog_search_shows_the_confirmed_name(client, code, name):
    assert searched(client, code) == name


@pytest.mark.parametrize("code, name", sorted(UNCHANGED.items()))
def test_the_rest_of_the_list_is_left_as_the_yedion_writes_it(client, code, name):
    assert searched(client, code) == name


def test_the_correction_beats_the_curriculum_name(client):
    """‏biotech.pdf מדפיס "קינטיקה ותכנון ריאקטורים"; electronic.json — שם קצר."""
    assert served(client, ["41526"], "הנדסת ביוטכנולוגיה")["41526"] == CONFIRMED["41526"]
    assert served(client, ["51742"], "הנדסת חשמל ואלקטרוניקה")["51742"] == CONFIRMED["51742"]


def test_civil_students_see_the_corrected_spelling(client):
    names = served(client, ["421223"], "הנדסה אזרחית")
    assert names["421223"] == CONFIRMED["421223"]
    data = client.get(f"/api/semester/2/courses?program={quote('הנדסה אזרחית')}").get_json()
    assert {c["code"]: c["name"] for c in data["courses"]}["421223"] == CONFIRMED["421223"]


def test_the_extracted_file_keeps_what_the_pdf_prints():
    """התיקון חי בטבלה, לא בקובץ שחולץ — כך נשאר תיעוד של מה שהמקור מדפיס."""
    raw = json.loads((ROOT / "data" / "curricula" / "civil.json").read_text(encoding="utf-8"))
    names = {c["name"] for s in raw["semesters"].values() for c in s["courses"]
             if c.get("code") == "421223"}
    assert names == {"מבוא לאלגרומיתקה ותכנות"}


def test_biotech_physics_follows_the_yedion(client):
    names = served(client, ["11023", "11026", "11027"], "הנדסת ביוטכנולוגיה")
    assert names == {"11023": "פיזיקה 1ב", "11026": "פיזיקה 2ב", "11027": "פיזיקה 3ב"}
