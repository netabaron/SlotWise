# -*- coding: utf-8 -*-
"""אשכולות קורסי בחירה — בקובץ התוכנית של המסלול, לא רק בהנדסת תוכנה.

מה השתנה
---------
עד כאן ``elective_clusters`` היה שדה של ``data/curriculum.json`` בלבד,
וקבוצות הבחירה שהממשק הציג הגיעו כולן מחילוץ השנתון שב-
``data/curricula.json``. החילוץ מזהה כותרת "אשכול X" ו"מסלול X" — ולכן
פרק מתמטיקה שימושית, שמקבץ את הבחירה תחת "תחום X", יצא ממנו ``flat``
ולמסלול לא הוצגו קורסי בחירה כלל.

עכשיו קובץ תוכנית מחלקתי יכול לשאת ``elective_clusters`` משלו, באותה
צורה בדיוק, ונקודת הקצה נופלת אליו.

**סדר ההכרעה הוא מה שנבדק כאן יותר מכל.** פרק השנתון גובר תמיד; קובץ
התוכנית נכנס רק כשהפרק שטוח. זה מה ששומר על הנדסת תוכנה — שלה יש גם
פרק וגם ``elective_clusters`` משלה, והשניים **אינם** זהים — בדיוק כפי
שהייתה.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src.web.api import create_app  # noqa: E402

CURRICULA_DIR = ROOT / "data" / "curricula"
SOFTWARE = "הנדסת תוכנה"
INDUSTRY = "הנדסת תעשייה וניהול"
MATH = "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה"

#: ארבעת התחומים של פרק מתמטיקה שימושית, עמודים 7–9.
MATH_CLUSTERS = {
    "תחום AI": 6,
    "תחום האלגוריתמים": 7,
    "תחום בתורת המערכות, הבקרה ועיבוד אותות": 5,
    "תחום אחר או מתמטיקה": 19,
}


@pytest.fixture()
def client():
    return create_app({"allow_network": False}).test_client()


def electives(client, program, intake=""):
    query = "program=" + urllib.parse.quote(program)
    if intake:
        query += "&intake=" + urllib.parse.quote(intake)
    res = client.get("/api/program/electives?" + query)
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()


def load(name):
    return json.loads((CURRICULA_DIR / f"{name}.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------- הסכמה
@pytest.mark.parametrize("name", ["math-winter", "math-spring", "industry"])
def test_the_file_carries_clusters_in_the_shape_curriculum_json_uses(name):
    """‏{שם אשכול: [רשומת קורס, ...]} — ולא צורה חדשה משלו."""
    clusters = load(name).get("elective_clusters")
    assert isinstance(clusters, dict) and clusters
    for cluster_name, rows in clusters.items():
        assert isinstance(cluster_name, str) and cluster_name.strip()
        assert isinstance(rows, list) and rows
        for row in rows:
            assert isinstance(row, dict)
            assert "code" in row and "name" in row
            assert str(row["name"]).strip()
            if row["code"] is not None:
                assert str(row["code"]).strip().isdigit()


@pytest.mark.parametrize("name", ["math-winter", "math-spring"])
def test_the_maths_chapter_is_transcribed_whole(name):
    """ארבעה תחומים, בגדלים שנספרו מול עמודי ה-PDF."""
    clusters = load(name).get("elective_clusters")
    assert {k: len(v) for k, v in clusters.items()} == MATH_CLUSTERS


def test_both_maths_intakes_share_one_elective_chapter():
    """השנתון מדפיס תוכנית לכל מועד, אבל **פרק בחירה אחד**."""
    assert load("math-winter")["elective_clusters"] == load("math-spring")["elective_clusters"]


def test_a_row_without_a_course_number_says_why():
    """שבע שורות בפרק מודפסות כ"חדש"/"מחליף" ובלי מספר קורס."""
    clusters = load("math-winter")["elective_clusters"]
    codeless = [
        row for rows in clusters.values() for row in rows if row["code"] is None
    ]
    assert len(codeless) == 8
    for row in codeless:
        assert str(row.get("note") or "").strip(), row["name"]


def test_no_code_is_listed_twice_in_the_same_cluster():
    """קוד כפול באשכול אחד הוא שגיאת הקלדה, לא מבנה."""
    for rows in load("math-winter")["elective_clusters"].values():
        codes = [r["code"] for r in rows if r["code"]]
        assert len(codes) == len(set(codes)), codes


def test_industry_clusters_are_the_extraction_verbatim():
    """‏"מהחילוץ הקיים" פירושו זהה לו, בלי העשרה ובלי המצאה."""
    chapter = json.loads((ROOT / "data" / "curricula.json").read_text(encoding="utf-8"))
    assert load("industry")["elective_clusters"] == chapter["programs"][INDUSTRY]["clusters"]


# ------------------------------------------------------- סדר ההכרעה
def test_software_engineering_is_untouched(client):
    """הפרק גובר, ולכן הנדסת תוכנה מקבלת בדיוק את מה שקיבלה קודם."""
    chapter = json.loads((ROOT / "data" / "curricula.json").read_text(encoding="utf-8"))
    expected = chapter["programs"][SOFTWARE]["clusters"]
    data = electives(client, SOFTWARE)
    assert data["available"] is True
    assert data["origin"] == "chapter"
    assert data["clusters"] == expected
    # ולא מה שיושב ב-data/curriculum.json, שאינו זהה לו.
    own = json.loads((ROOT / "data" / "curriculum.json").read_text(encoding="utf-8"))
    assert own["elective_clusters"] != expected  # אחרת הבדיקה אינה בודקת כלום
    assert data["clusters"] != own["elective_clusters"]


def test_industry_still_comes_from_the_chapter(client):
    """גם כשלקובץ שלה יש עכשיו אשכולות — התוכן זהה, והמקור נשאר הפרק."""
    data = electives(client, INDUSTRY)
    assert data["available"] is True
    assert data["origin"] == "chapter"
    assert data["clusters"] == load("industry")["elective_clusters"]


def test_a_flat_chapter_with_no_file_clusters_stays_hidden(client):
    """חשמל אין לה אשכולות בשום מקום — ואז לא ממציאים רשימה."""
    data = electives(client, "הנדסת חשמל ואלקטרוניקה")
    assert data["available"] is False


def test_a_track_chapter_is_still_tracks(client):
    """אזרחית בוחרת מסלול אחד, לא קורס מכל אשכול. ההבחנה נשמרת."""
    data = electives(client, "הנדסה אזרחית")
    assert data["available"] is True
    assert data["structure"] == "tracks"
    assert data["tracks"]


# ------------------------------------------------- מתמטיקה שימושית
@pytest.mark.parametrize("intake", ["winter", "spring"])
def test_applied_maths_now_has_electives(client, intake):
    data = electives(client, MATH, intake)
    assert data["available"] is True
    assert data["origin"] == "curriculum"
    assert data["structure"] == "clusters"
    assert {k: len(v) for k, v in data["clusters"].items()} == MATH_CLUSTERS
    # השנתון של מתמטיקה אינו קובע "קורס מכל תחום", ולכן אין כלל להציג.
    # שורה זו שונתה באישור מפורש, 2026-09-25 (PROGRAM_REVIEW §2, המשך).
    assert data["cluster_rule"] == ""
    # אין שנת מחזור בפרק הזה, ואז נאמר בדיוק את זה ולא מנחשים.
    assert data["year"] in (None, "")
    assert "לא צוינה" in data["year_text"]


def test_applied_maths_without_an_intake_asks_for_one(client):
    """אותו מספר סמסטר מציין דבר אחר בכל מועד — ואין קובץ אחד להחזיר."""
    data = electives(client, MATH)
    assert data["available"] is False
    assert "מועד כניסה" in data["reason"]


def test_the_elective_codes_reach_the_catalog(client):
    """כיסוי, לא שלמות.

    קורס בחירה שאינו נפתח השנה הוא מצב רגיל לגמרי — בהנדסת תוכנה כ-52%
    מקורסי הבחירה אינם בקטלוג הנוכחי. מה שכן חייב להתקיים הוא שהקודים
    **אמיתיים**: לכל אשכול יש לפחות קורס אחד שהקטלוג מכיר. אשכול שאף
    קוד שלו אינו בקטלוג הוא הסימן להקלדה שגויה או לעמודה שנקראה הפוך.
    """
    import shipped_catalog

    known = set(shipped_catalog.courses())
    clusters = load("math-winter")["elective_clusters"]
    for cluster_name, rows in clusters.items():
        coded = [r["code"] for r in rows if r["code"]]
        assert coded, cluster_name
        assert known & set(coded), cluster_name
