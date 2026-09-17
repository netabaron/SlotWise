# -*- coding: utf-8 -*-
"""
הנדסת ביוטכנולוגיה — תוכנית לימודים שטוחה, מ-biotech.pdf.

הרקע
----
עד 2026-09-17 זו הייתה המחלקה היחידה שלא היה לה **שום** מסמך: לא פרק שנתון
ולא קובץ PDF. היא עבדה מול הקטלוג לא מתוך החלטה אלא מחוסר מקור. מאז הגיע
מסמך "תוכנית לימודים של קורסי חובה", והוא נגזר לקובץ תוכנית רגיל.

מה המסמך הזה כן ולא נותן
-------------------------
* **קורסי חובה בלבד.** אין בו קורסי בחירה, וזה בסדר — התוכנית מתארת את מה
  שחייבים, והשאר נבחר מהקטלוג.
* **נ"ז בלבד, בלי פירוט שעות.** לכן ``he/te/ma/pr`` הם 0 בכל השורות.
* **שורות שאינן קורסים.** "סליק" היא קבוצת דמה לסטודנט שחוזר על קורס, ושורה
  אחת מסומנת "מבוטל" עם 0 נ"ז. מי שמעתיק את הטבלה כלשונה מקבל קורסים שאיש
  אינו נרשם אליהם, ולכן שתי הקטגוריות מושמטות — והבדיקות כאן שומרות על כך.
* **קורס שהוחלף.** שורה אחת אומרת "קורס חדש במקום 41524"; הקוד שנלמד הוא
  ‏41526, והוא זה שנשמר.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from web.api import create_app  # noqa: E402

BIOTECH = "הנדסת ביוטכנולוגיה"
CURRICULUM = ROOT / "data" / "curricula" / "biotech.json"


@pytest.fixture(scope="module")
def client():
    return create_app(config={"allow_network": False}).test_client()


@pytest.fixture(scope="module")
def curriculum() -> dict:
    return json.loads(CURRICULUM.read_text(encoding="utf-8"))


def semester(client, sem: str) -> dict:
    res = client.get(f"/api/semester/{sem}/courses?program={quote(BIOTECH)}")
    assert res.status_code == 200, f"סמסטר {sem} החזיר {res.status_code}"
    return res.get_json()


# ==========================================================================
# 1. הקובץ עצמו
# ==========================================================================
def test_the_file_exists_and_names_its_program(curriculum):
    assert curriculum["program"] == BIOTECH
    assert curriculum["source"] == "biotech.pdf"
    assert len(curriculum["semesters"]) == 8


def test_the_repeater_rows_are_not_courses(curriculum):
    """‏"סליק" היא קבוצת דמה לחוזרים על הקורס, לא קורס."""
    codes = {c["code"] for s in curriculum["semesters"].values() for c in s["courses"]}
    for slik in ("41063", "41233", "41361"):
        assert slik not in codes, f"קוד סליק {slik} נכנס לתוכנית"


def test_the_cancelled_row_is_not_a_course(curriculum):
    """השורה שמסומנת "מבוטל" היא 0 נ"ז ואינה נלמדת."""
    names = [c["name"] for s in curriculum["semesters"].values() for c in s["courses"]]
    assert not [n for n in names if "מבוטל" in n], "שורה מבוטלת נכנסה לתוכנית"


def test_the_replacement_code_is_used_not_the_replaced_one(curriculum):
    """‏"קורס חדש במקום 41524" — הקוד שנלמד הוא 41526."""
    codes = {c["code"] for s in curriculum["semesters"].values() for c in s["courses"]}
    assert "41526" in codes, "הקוד החדש חסר"
    assert "41524" not in codes, "הקוד שהוחלף נכנס בטעות"


def test_the_document_publishes_no_hours_and_the_file_says_so(curriculum):
    """‏he/te/ma/pr הם 0 — ויש אזהרה שמסבירה שזה המסמך ולא באג בחילוץ."""
    hours = [c["he"] + c["te"] + c["ma"] + c["pr"]
             for s in curriculum["semesters"].values() for c in s["courses"]]
    assert hours and not any(hours), "המסמך אינו מפרסם שעות; הן אמורות להיות 0"
    assert any("שעות" in w for w in curriculum["warnings"]), "חסרה אזהרה על היעדר השעות"


# ==========================================================================
# 2. דרך השרת
# ==========================================================================
def test_it_yields_suggestions_for_semester_three(client):
    data = semester(client, "3")
    assert data["curriculum_available"] is True, "ביוטכנולוגיה אמורה לקבל תוכנית עכשיו"
    assert data["count"] > 0
    assert data["program"] == BIOTECH


def test_every_semester_yields_something(client):
    empty = [s for s in map(str, range(1, 9)) if semester(client, s)["count"] == 0]
    assert not empty, f"סמסטרים ריקים: {empty}"


def test_the_plan_is_flat_with_no_specialisation_tracks(client):
    """אין התמחויות במסמך, ולכן אסור שתופיע שורת מסלול באף סמסטר."""
    for sem in map(str, range(1, 9)):
        tracked = [c["code"] for c in semester(client, sem)["courses"] if c["track"]]
        assert not tracked, f"סמסטר {sem}: נמצאו שורות מסלול {tracked}"


def test_the_english_ladder_is_never_auto_selected(client):
    """רמת האנגלית נקבעת לפי ציון השמה — אף רמה אינה נבחרת אוטומטית."""
    english = [c for c in semester(client, "1")["courses"]
               if c["code"] in {"11062", "11063", "11064", "11058"}]
    assert english, "שורות האנגלית נעלמו מסמסטר 1"
    for course in english:
        assert course["placement"] is True, f"{course['code']} אינו מסומן כקורס השמה"


def test_almost_every_code_is_in_the_catalog(client):
    """‏הקורסים אמיתיים. ‏11062 (אנגלית טרום בסיסי) אינו נפתח השנה, וזה ידוע."""
    missing = [c["code"] for sem in map(str, range(1, 9))
               for c in semester(client, sem)["courses"] if not c["offered"]]
    assert set(missing) <= {"11062"}, f"קודים שאינם בקטלוג: {sorted(set(missing))}"
