"""
הקורסים של תוכנית הלימודים מוצגים **רק למי שלומד/ת אותה**.

הרקע
----
``data/curriculum.json`` נגזר מ-``rec.pdf``, שהוא פרק **הנדסת תוכנה** בשנתון
בלבד — 87 מתוך 571 קורסים בקטלוג, כ-15%. עד התיקון הזה שלב 2 בממשק בנה את
רשימת הקורסים מהתוכנית עבור **כל** מי שנכנס, ולכן סטודנט/ית מהנדסת מכונות
שבחר/ה "שנה ג', סמסטר א'" קיבל/ה רשימה של קורסי תוכנה כאילו זהו המסלול שלו/ה.

התיקון הוא לשאול מראש מהו המסלול, ולהציג את התוכנית רק כשהיא באמת מתאימה.
לכל השאר — הקטלוג המלא, שממילא מכסה את כל המחלקות.

מה **לא** נעשה כאן, בכוונה: לא הומצאה טקסונומיה של מחלקות לפי קידומת קוד.
בדיקה על הקטלוג האמיתי הראתה שהמיפוי הזה פשוט לא נכון — ‏81xxx הם קורסי
חינוך ("מבוא להוראת המקצועות", "סוציולוגיה בחינוך") ולא הנדסת חשמל, ו-42xxx
הם אדריכלות. ניחוש כזה היה מחליף הטעיה אחת באחרת.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src.web.api import (  # noqa: E402
    OTHER_PROGRAM,
    _program_matches_curriculum,
    create_app,
    curriculum_program,
)


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return app.test_client()


# ==========================================================================
# 1. ההתאמה עצמה
# ==========================================================================
def test_the_loaded_curriculum_knows_which_program_it_describes(app):
    with app.app_context():
        assert curriculum_program() == "הנדסת תוכנה"


def test_the_matching_program_matches(app):
    with app.app_context():
        assert _program_matches_curriculum("הנדסת תוכנה") is True


def test_punctuation_and_spacing_do_not_break_the_match(app):
    """שם מסלול שהגיע עם מקף או רווח כפול הוא עדיין אותו מסלול."""
    with app.app_context():
        assert _program_matches_curriculum("הנדסת-תוכנה") is True
        assert _program_matches_curriculum("  הנדסת תוכנה  ") is True


def test_another_program_does_not_match(app):
    with app.app_context():
        assert _program_matches_curriculum("הנדסת מכונות") is False
        assert _program_matches_curriculum("הנדסה אזרחית") is False
        assert _program_matches_curriculum(OTHER_PROGRAM) is False


def test_an_unspecified_program_still_matches(app):
    """ריק = לא נשאל. אסור שהתיקון ישבור קריאות שאינן מציינות מסלול."""
    with app.app_context():
        assert _program_matches_curriculum("") is True
        assert _program_matches_curriculum(None) is True


# ==========================================================================
# 2. דרך ה-API
# ==========================================================================
def test_bootstrap_advertises_the_program_and_the_choices(client):
    data = client.get("/api/bootstrap").get_json()
    assert data["curriculum_program"] == "הנדסת תוכנה"
    programs = data["programs"]
    assert any(p["id"] == "הנדסת תוכנה" and p["has_curriculum"] for p in programs)
    assert any(p["id"] == OTHER_PROGRAM and not p["has_curriculum"] for p in programs)


def test_a_software_student_still_gets_the_curriculum(client):
    data = client.get("/api/semester/5/courses?program=הנדסת תוכנה").get_json()
    assert data["curriculum_available"] is True
    codes = {c["code"] for c in data["courses"]}
    assert {"61756", "61757", "62027"} <= codes


def test_a_student_of_another_program_is_not_shown_software_courses(client):
    """**התקלה שהקובץ הזה שומר עליה.**

    ‏העיקרון לא השתנה: רואים תוכנית לימודים רק אם היא באמת שלך. מה שהשתנה
    הוא מה שיש להציע במקום — מאז שלכל מחלקה שיש לה פרק שנתון יש קובץ תוכנית
    משלה, סטודנט/ית להנדסת מכונות מקבל/ת את **קורסי המכונות**, ולא רשימה
    ריקה. הבדיקה נעשתה חזקה יותר, לא רופפת: קודם היא בדקה "לא קיבל כלום",
    ועכשיו היא בודקת "לא קיבל קורסי תוכנה" — וזה מה שהיה כתוב בשמה מלכתחילה.
    ‏מסלול שאין לו פרק כלל נבדק בנפרד, מיד אחרי.
    """
    software = client.get("/api/semester/5/courses?program=הנדסת תוכנה").get_json()
    software_codes = {c["code"] for c in software["courses"] if c["code"]}

    data = client.get("/api/semester/5/courses?program=הנדסת מכונות").get_json()
    codes = {c["code"] for c in data["courses"] if c["code"]}
    assert codes, "למכונות יש פרק שנתון משלה, ולכן יש לה רשימת קורסים"
    assert not (codes & software_codes), "ואף אחד מהם אינו קורס של הנדסת תוכנה"
    assert data["program"] == "הנדסת מכונות"


def test_a_program_with_no_chapter_at_all_is_shown_nothing(client):
    """להנדסת ביוטכנולוגיה אין קובץ ‏PDF ואין תוכנית — והיא עוברת לקטלוג."""
    data = client.get("/api/semester/5/courses?program=הנדסת ביוטכנולוגיה").get_json()
    assert data["curriculum_available"] is False
    assert data["courses"] == []


def test_choosing_other_behaves_the_same(client):
    data = client.get(f"/api/semester/5/courses?program={OTHER_PROGRAM}").get_json()
    assert data["curriculum_available"] is False
    assert data["courses"] == []


def test_not_naming_a_program_keeps_the_old_behaviour(client):
    """בלי הפרמטר — כמו קודם. תאימות לאחור לכל מי שכבר קורא ל-API."""
    data = client.get("/api/semester/5/courses").get_json()
    assert data["curriculum_available"] is True
    assert data["courses"]


def test_no_program_is_ever_an_error(client):
    """אין תוכנית = מצב תקין, לא תקלה. ‏200 תמיד, אחרת הממשק נשבר."""
    for program in ("הנדסת מכונות", OTHER_PROGRAM, "משהו שלא קיים"):
        resp = client.get(f"/api/semester/5/courses?program={program}")
        assert resp.status_code == 200, program


def test_the_page_offers_the_program_selector(client):
    html = client.get("/").get_data(as_text=True)
    assert 'id="select-program"' in html


# ==========================================================================
# 3. מה שנשאר עובד לכולם
# ==========================================================================
def test_the_catalog_is_still_open_to_everyone(client):
    """הקטלוג הוא הנתיב של כל מי שאינו הנדסת תוכנה — הוא חייב לעבוד."""
    resp = client.get("/api/catalog/browse?limit=5")
    assert resp.status_code == 200
    data = resp.get_json()
    items = data.get("items") or data.get("courses") or data.get("results") or []
    assert items, "עיון בקטלוג חייב להחזיר קורסים גם בלי תוכנית לימודים"
