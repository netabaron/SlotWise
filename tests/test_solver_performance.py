# -*- coding: utf-8 -*-
"""שנה א' נפתרת בפחות משלוש שניות.

‏עד 2026-10-20 הבחירות שלמטה — מה שהדף מסמן לסמסטר 1, עם ברירת המחדל של
הדף לנוכחות (כל רכיב בלי הערת ידיעון אינו חובה) — לא הסתיימו בתוך 60
שניות מול הקטלוג הקפוא, ומעל 30 שניות gunicorn הורג את ה-worker ומחזיר
‏500. מכונות היה 18 שניות. (docs/SOLVER_PERFORMANCE.md.) אחרי החיפוש הגוזם
כל אחת מהן נמדדה מתחת לשנייה אחת על המכונה המקומית; הסף כאן — שלוש — משאיר
מקום למחשב איטי יותר.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src.web import api  # noqa: E402

TERM = "א"
LIMIT_S = 3.0

#: ‏הקודים שהדף מסמן לשנה א' סמסטר א', מהקטלוג הקפוא (recommendedCodes ב-app.js),
#: ‏ומשך ‏/api/solve לפני 2026-10-20.
FIRST_YEAR = {
    "civil": (["11003", "11001", "41079", "421208", "421110", "22400"], "timeout >60 s"),
    "biotech": (["11179", "11001", "11003", "41014", "41113", "41201", "251961"], "timeout >60 s"),
    "electrical": (["11002", "11004", "31230", "31511", "251961"], "timeout >60 s"),
    "mechanical": (["11001", "11003", "22112", "251961"], "18.1 s"),
    "industrial": (["11001", "11003", "11179", "51104", "61903", "251961"], "timeout >60 s"),
}


@pytest.fixture(scope="module")
def app():
    return api.create_app({"allow_network": False}, serve_ui=False)


@pytest.fixture(scope="module")
def client(app):
    c = app.test_client()
    # חימום: טעינת הקטלוג והמטמונים אינה חלק ממה שנמדד כאן.
    assert c.post("/api/solve", json={"codes": ["11061"], "semester": TERM}).status_code == 200
    return c


def _page_attendance(app, codes):
    """מה ש-``attendanceBody()`` שולח: ‏False לכל רכיב שהידיעון אינו מחייב בו."""
    with app.app_context():
        built, _p, _m = api._build_courses(codes, semester=TERM)  # noqa: SLF001
    info = api.attendance_info(built)
    return {
        code: {kind: False for kind, rec in kinds.items() if not rec["from_yedion"]}
        for code, kinds in info.items()
    }


def _solve(client, body, attempts=3):
    """התשובה, והזמן הקצר מבין עד ``attempts`` ניסיונות.

    ‏הטוב מבין שלושה ולא ניסיון יחיד: על המכונה המקומית אותה בקשה נמדדה
    ‏0.7, ‏2.3 ו-8.4 שניות בשלוש הרצות שונות של אותו קוד (2026-10-20, אחרי
    ריצת דפדפנים ארוכה). רגרסיה אמיתית — חזרה למנייה מלאה — איטית בכל
    הניסיונות, ולכן היא עדיין נכשלת.
    """
    best, res = None, None
    for _ in range(attempts):
        started = time.perf_counter()
        res = client.post("/api/solve", json=body)
        elapsed = time.perf_counter() - started
        best = elapsed if best is None else min(best, elapsed)
        if res.status_code != 200 or best < LIMIT_S:
            break
    return res, best


@pytest.mark.parametrize("name", list(FIRST_YEAR))
def test_first_year_page_defaults_solve_under_three_seconds(app, client, name):
    codes, before = FIRST_YEAR[name]
    body = {"codes": codes, "semester": TERM, "target_days": 6, "top_n": 5,
            "allow_soft_conflicts": True, "attendance": _page_attendance(app, codes)}
    res, elapsed = _solve(client, body)
    assert res.status_code == 200, res.get_data(as_text=True)
    data = res.get_json()
    assert data["timed_out"] is False, "הגיע למגבלת הזמן — כלומר לא נפתר"
    assert len(data["schedules"]) == 5
    assert not any(s["truncated"] for s in data["schedules"])
    assert data["viability_skipped"] is False and data["viability_truncated"] is False
    # עשרות-מאות אלפי צירופים: הספירה נעצרת במכסה ואומרת זאת.
    assert data["feasible_count"] == api.FEASIBLE_COUNT_CAP
    assert data["feasible_count_capped"] is True
    assert elapsed < LIMIT_S, f"{name}: {elapsed:.2f} s (לפני 2026-10-20: {before})"


@pytest.mark.parametrize("name", ["industrial", "mechanical"])
def test_first_year_with_every_component_required_is_fast_too(client, name):
    """בלי ויתור על נוכחות כלל — הנתיב השני; תעשייה וניהול היה 12 שניות."""
    codes, _before = FIRST_YEAR[name]
    res, elapsed = _solve(client, {"codes": codes, "semester": TERM, "target_days": 6})
    assert res.status_code == 200
    assert res.get_json()["timed_out"] is False
    assert elapsed < LIMIT_S, f"{name}: {elapsed:.2f} s"


def test_a_ranked_first_year_with_a_day_target_is_fast_too(app, client):
    """דירוג מרצים ויעד ימים מפעילים את שתי הרמות הראשונות של החסם."""
    codes, _before = FIRST_YEAR["civil"]
    with app.app_context():
        built, _p, _m = api._build_courses(codes, semester=TERM)  # noqa: SLF001
    ranked = {}
    for course in built[:3]:
        for kind in course.kinds():
            names = [g.lecturer for g in course.groups_of(kind) if g.lecturer]
            if names:
                ranked.setdefault(course.code, {})[kind] = [names[-1]]
    body = {"codes": codes, "semester": TERM, "target_days": 3, "ranked": ranked,
            "attendance": _page_attendance(app, codes)}
    res, elapsed = _solve(client, body)
    assert res.status_code == 200
    data = res.get_json()
    assert data["timed_out"] is False and data["schedules"]
    assert data["schedules"][0]["lecturer_total"] > 0
    assert elapsed < LIMIT_S, f"{elapsed:.2f} s"
