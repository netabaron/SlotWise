# -*- coding: utf-8 -*-
"""
‏``curriculum_absence`` — *למה* אין תוכנית לימודים, ולא רק *ש*אין.

הבעיה
-----
שתי תשובות שונות לגמרי נראו בדיוק אותו דבר בתשובת השרת:

* "המכללה אינה מפרסמת תוכנית למסלול הזה."
* "היא כן מפרסמת, אבל לא בצורה שאפשר להציג כרשימה אחת לכל סמסטר."

שתיהן החזירו ``curriculum_available: false`` ואת אותו נוסח כללי, והסטודנט/ית
נפלו לעיון בקטלוג בלי לדעת למה. ‏נמדד ב-2026-09-16: התשובות של ביוטכנולוגיה
ותעשייה וניהול היו זהות שדה-בשדה.

מה שנוסף
---------
שדה ``curriculum_absence`` עם שני ערכים: ``no_curriculum`` ו-
``not_representable``. הוא מגיע גם ברמה העליונה של ‏/api/bootstrap, גם לכל
מסלול ברשימת ``programs`` שבו (הממשק מחליף מסלול בלי לבקש ‏bootstrap מחדש),
וגם ב-‏/api/semester/<sem>/courses.

המקרה היחיד כרגע
-----------------
מתמטיקה שימושית: השנתון מדפיס שתי תוכניות לפי מועד הכניסה (חורף/אביב),
**בלי ולו סמסטר אחד משותף**, וגם מספר הסמסטר מציין דבר אחר בכל מועד. זו
החלטה מתועדת (‏commit 5aa6f17) ולא פער — מה שהשתנה הוא שעכשיו אומרים אותה.
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

MATH = "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה"
WITH_PLAN = ("הנדסת תוכנה", "הנדסת ביוטכנולוגיה", "הנדסת תעשייה וניהול")

NOT_REPRESENTABLE = "not_representable"
NO_CURRICULUM = "no_curriculum"


@pytest.fixture(scope="module")
def client():
    return create_app(config={"allow_network": False}).test_client()


def semester(client, sem: str, program: str) -> dict:
    res = client.get(f"/api/semester/{sem}/courses?program={quote(program)}")
    assert res.status_code == 200, f"{program} סמסטר {sem} החזיר {res.status_code}"
    return res.get_json()


# ==========================================================================
# 1. מתמטיקה שימושית — עדיין בלי תוכנית, ועכשיו עם סיבה
# ==========================================================================
def test_applied_maths_still_has_no_curriculum(client):
    """ההתנהגות לא השתנתה: אין רשימה, והנפילה לקטלוג נשארת."""
    data = semester(client, "3", MATH)
    assert data["curriculum_available"] is False
    assert data["courses"] == []


def test_applied_maths_says_the_plan_is_not_representable(client):
    """זה הלב: ההבדל בין "אין תוכנית" ל"יש, ואי אפשר להציג אותה כרשימה"."""
    data = semester(client, "3", MATH)
    assert data.get("curriculum_absence") == NOT_REPRESENTABLE, (
        f"curriculum_absence היה {data.get('curriculum_absence')!r}"
    )


def test_the_fallback_note_is_still_there(client):
    """ההסבר אינו מחליף את הנפילה לקטלוג — הוא מתלווה אליה."""
    data = semester(client, "3", MATH)
    assert data["note"], "חייב לומר משהו, ולא להשאיר מסך ריק"
    assert data["fallback"]["endpoint"] == "/api/catalog/browse"


# ==========================================================================
# 2. מי שיש לו תוכנית — אין לו סיבה להיעדרה
# ==========================================================================
@pytest.mark.parametrize("program", WITH_PLAN)
def test_a_program_with_a_curriculum_reports_no_absence(client, program):
    data = semester(client, "3", program)
    assert data.get("curriculum_absence") == "", (
        f"{program}: {data.get('curriculum_absence')!r}"
    )


# ==========================================================================
# 3. ‏/api/bootstrap נושא את הסיבה לכל מסלול
# ==========================================================================
def test_the_program_list_carries_the_reason_for_every_program(client):
    """הממשק מחליף מסלול בלי לבקש ‏bootstrap מחדש, ולכן הסיבה חייבת להגיע בו."""
    data = client.get("/api/bootstrap").get_json()
    by_id = {p["id"]: p for p in data["programs"]}
    assert by_id[MATH]["curriculum_absence"] == NOT_REPRESENTABLE
    for program in WITH_PLAN:
        assert by_id[program]["has_curriculum"] is True
        assert by_id[program]["curriculum_absence"] == "", (
            f"{program} כבר יש לו תוכנית — אסור שתהיה סיבה להיעדרה"
        )


def test_every_program_entry_carries_the_field(client):
    """כולל "תוכנית אחרת / לא ברשימה" — ‏None שם היה מתפרש בממשק כ"לא נאמר"."""
    data = client.get("/api/bootstrap").get_json()
    missing = [p["id"] for p in data["programs"] if p.get("curriculum_absence") is None]
    assert not missing, f"מסלולים בלי השדה: {missing}"


def test_bootstrap_has_the_field_at_the_top_level(client):
    data = client.get("/api/bootstrap").get_json()
    assert "curriculum_absence" in data


# ==========================================================================
# 4. הנוסח שהממשק מציג
# ==========================================================================
def test_the_explanation_string_exists_and_is_hebrew():
    """בלי המחרוזת הזאת הממשק היה נופל בחזרה לנוסח הכללי בשקט."""
    strings = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
    note = strings["app"]["terms"]["fallbackNote"].get("not-representable")
    assert note, "‏app.terms.fallbackNote['not-representable'] חסר"
    assert any("֐" <= ch <= "׿" for ch in note), "הנוסח אינו בעברית"


def test_the_frontend_looks_the_reason_up(client):
    """‏app.js חייב לקרוא את השדה; אחרת הוא נוסף לשרת ואיש אינו מציג אותו."""
    app_js = (ROOT / "src" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert "curriculum_absence" in app_js, "‏app.js אינו קורא את curriculum_absence"
    assert "curriculumAbsenceKey" in app_js, "חסרה הפונקציה שממפה אותו לנוסח"
