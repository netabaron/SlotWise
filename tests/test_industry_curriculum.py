# -*- coding: utf-8 -*-
"""
הנדסת תעשייה וניהול — שתי התמחויות, דרך מנגנון ה-``track`` הקיים.

הרקע
----
המסמך (``industry.pdf``) מדפיס את התוכנית **פעמיים**: מסלול מלא 1–8 לכל
התמחות. זו הסיבה שהמחלקה נשארה בלי תוכנית עד 2026-09-17 — רשימה שטוחה
אחת הייתה נכונה לחצי מהמחלקה ושגויה לחצי השני, וניחוש איזה חצי הוא בדיוק
מה שהפרויקט הזה אינו עושה.

מה שאיפשר לפתור את זה בלי מנגנון חדש
-------------------------------------
‏``track`` כבר קיים, ומשמש באזרחית (2 מסלולים) ובמכונות (4). קורס עם
‏``track`` לא ריק מוצג, מסומן בשם המסלול, ו**לעולם אינו נבחר אוטומטית** —
בדיוק כמו קורס השמה. אותו טיפול בדיוק עובד כאן:

* **סמסטרים 1–2** זהים בשתי ההתמחויות (אומת: 8 ו-7 קורסים משותפים, אפס
  הבדלים), ולכן אינם נושאים מסלול כלל.
* **מסמסטר 3** — קורס שמופיע בשתי ההתמחויות נשאר ליבה משותפת, וקורס
  שמופיע רק באחת מסומן בשמה.

אומת באריתמטיקה, לא בעין
-------------------------
לכל סמסטר: ליבה משותפת + קורסי התמחות א' חייבים להסתכם בסה"כ המודפס של
התמחות א', ואותו דבר להתמחות ב'. כל שמונת הסמסטרים עוברים את הבדיקה הזאת.
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

INDUSTRY = "הנדסת תעשייה וניהול"
CURRICULUM = ROOT / "data" / "curricula" / "industry.json"

#: שתי ההתמחויות שהמסמך מדפיס.
TRACKS = {"מדעי הנתונים", "תכן ותפעול של מערכות ייצור ושירות"}


@pytest.fixture(scope="module")
def client():
    return create_app(config={"allow_network": False}).test_client()


@pytest.fixture(scope="module")
def curriculum() -> dict:
    return json.loads(CURRICULUM.read_text(encoding="utf-8"))


def semester(client, sem: str) -> dict:
    res = client.get(f"/api/semester/{sem}/courses?program={quote(INDUSTRY)}")
    assert res.status_code == 200, f"סמסטר {sem} החזיר {res.status_code}"
    return res.get_json()


# ==========================================================================
# 1. הקובץ עצמו
# ==========================================================================
def test_the_file_exists_and_declares_both_tracks(curriculum):
    assert curriculum["program"] == INDUSTRY
    assert curriculum["source"] == "industry.pdf"
    assert set(curriculum["tracks"]) == TRACKS
    assert len(curriculum["semesters"]) == 8


def test_every_semester_reconciles(curriculum):
    """ליבה + קורסי כל התמחות = הסה"כ המודפס של אותה התמחות."""
    bad = [sem for sem, body in curriculum["semesters"].items()
           if body.get("reconciles") is not True]
    assert not bad, f"סמסטרים שאינם מסתדרים: {bad}"


def test_the_split_is_explained_in_every_divided_semester(curriculum):
    """סמסטר שיש בו מסלולים חייב לומר בקול מה הליבה ומה ההתמחות מוסיפה."""
    for sem, body in curriculum["semesters"].items():
        if any(c["track"] for c in body["courses"]):
            assert body.get("note"), f"סמסטר {sem} מפוצל למסלולים בלי הסבר"


def test_no_course_code_appears_twice_in_one_semester(curriculum):
    """קורס משותף נשמר פעם אחת כליבה, ולא פעמיים — אחת לכל התמחות.

    שורה כפולה הייתה מצטיירת בממשק כשני קורסים שונים באותו סמסטר.
    """
    for sem, body in curriculum["semesters"].items():
        codes = [c["code"] for c in body["courses"]]
        dupes = {c for c in codes if codes.count(c) > 1}
        assert not dupes, f"סמסטר {sem}: קודים כפולים {dupes}"


# ==========================================================================
# 2. דרך השרת
# ==========================================================================
def test_it_yields_suggestions_for_semester_three(client):
    data = semester(client, "3")
    assert data["curriculum_available"] is True
    assert data["count"] > 0
    assert data["program"] == INDUSTRY


def test_semester_three_badges_both_specialisations(client):
    """סמסטר 3 הוא הראשון שבו ההתמחויות נפרדות — ושתיהן חייבות להופיע."""
    data = semester(client, "3")
    tracks = {c["track"] for c in data["courses"] if c["track"]}
    assert tracks == TRACKS, f"מסלולים שהוחזרו: {tracks}"
    assert [c for c in data["courses"] if not c["track"]], "חייבת להיות ליבה משותפת"


def test_the_first_two_semesters_carry_no_track(client):
    """סמסטרים 1–2 זהים בשתי ההתמחויות, ולכן אסור שיישאו שם מסלול."""
    for sem in ("1", "2"):
        tracked = [c["code"] for c in semester(client, sem)["courses"] if c["track"]]
        assert not tracked, f"סמסטר {sem}: שורות מסלול {tracked} — אמור להיות ליבה בלבד"


def test_track_names_are_always_one_of_the_two(client):
    for sem in map(str, range(1, 9)):
        for course in semester(client, sem)["courses"]:
            if course["track"]:
                assert course["track"] in TRACKS, (
                    f"סמסטר {sem}: מסלול לא מוכר {course['track']!r}"
                )


def test_a_track_course_is_shown_and_selectable_but_explained(client):
    """מציגים ומסבירים, לא מסמנים. הכלי אינו יודע באיזו התמחות הסטודנט/ית."""
    tracked = [c for c in semester(client, "3")["courses"] if c["track"]]
    assert tracked, "סמסטר 3 אמור לכלול קורסי התמחות"
    for course in tracked:
        assert course["selectable"] is True, "קורס מסלול חייב להישאר ניתן לבחירה ידנית"
        assert course["in_curriculum"] is True


def test_every_code_is_in_the_catalog(client):
    """‏100% כיסוי — נמדד בזמן הבנייה, ונשמר כאן."""
    missing = [c["code"] for sem in map(str, range(1, 9))
               for c in semester(client, sem)["courses"] if not c["offered"]]
    assert not missing, f"קודים שאינם בקטלוג: {sorted(set(missing))}"
