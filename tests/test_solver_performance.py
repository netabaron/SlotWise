# -*- coding: utf-8 -*-
"""שנה א' נפתרת בכמות עבודה קבועה, ולא רק "מהר על המכונה הזו".

‏עד 2026-10-20 הבחירות שלמטה — מה שהדף מסמן לסמסטר 1, עם ברירת המחדל של
הדף לנוכחות (כל רכיב בלי הערת ידיעון אינו חובה) — לא הסתיימו בתוך 60
שניות מול הקטלוג הקפוא, ומעל 30 שניות gunicorn הורג את ה-worker ומחזיר
‏500. מכונות היה 18 שניות. (docs/SOLVER_PERFORMANCE.md.)

‏**מה נמדד — ולמה לא שעון בלבד.** סף של 3 שניות נפל ב-CI (‏-n 4) על 4.00
שניות, ועל המכונה המקומית אותה בקשה נמדדה 0.7, ‏2.3 ו-8.4 שניות בהרצות
שונות של אותו קוד. זמן מודד את המכונה; מספר הצמתים מודד את האלגוריתם.
לכן הבדיקה העיקרית היא **מספר צמתי החיפוש** של הבקשה כולה — כל קריאה
ל-``_Budget.tick()``, אותו מונה שמכסת הצמתים נשענת עליו — והוא דטרמיניסטי:
אותו קוד ואותו קטלוג נותנים אותו מספר בכל הרצה ובכל מכונה.

‏התקציבים הם המספרים שנמדדו ב-2026-10-21 ועוד כ-10%, מעוגלים כלפי מעלה
לאלף. המנייה המלאה שלפני 2026-10-20 עברה על מאות אלפים עד מיליונים
(אזרחית, מעבר הספירה לבדו: 960,944 צמתים בקטלוג האמיתי), ולכן כל חזרה אליה
נתפסת מיד. שינוי מכוון באלגוריתם או בקטלוג הקפוא מעדכן את התקציבים כאן,
באותו commit, עם המספרים החדשים.

‏**השעון נשאר רק כרשת ביטחון**, נדיבה: ‏10 שניות — יותר מפי 5 מהמקרה האיטי
ביותר שנמדד (1.8 ש'), וחצי ממגבלת הזמן של השרת (``SOLVE_DEADLINE_S`` = 20).
בקשה שמגיעה למגבלה נתפסת ממילא ב-``timed_out``.
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

sch = api.scheduler_mod
TERM = "א"

#: רשת הביטחון של השעון, בשניות. ראו למעלה.
WALL_GUARD_S = 10.0

#: ‏הקודים שהדף מסמן לשנה א' סמסטר א', מהקטלוג הקפוא (recommendedCodes ב-app.js),
#: ‏ומשך ‏/api/solve לפני 2026-10-20.
FIRST_YEAR = {
    "civil": (["11003", "11001", "41079", "421208", "421110", "22400"], "timeout >60 s"),
    "biotech": (["11179", "11001", "11003", "41014", "41113", "41201", "251961"], "timeout >60 s"),
    "electrical": (["11002", "11004", "31230", "31511", "251961"], "timeout >60 s"),
    "mechanical": (["11001", "11003", "22112", "251961"], "18.1 s"),
    "industrial": (["11001", "11003", "11179", "51104", "61903", "251961"], "timeout >60 s"),
}

#: ‏תקציב הצמתים לבקשה אחת: ‏(נמדד ב-2026-10-21, תקציב). התקציב ≈ נמדד × 1.1,
#: מעוגל כלפי מעלה לאלף.
PAGE_NODES = {
    "civil": (23_292, 26_000),
    "biotech": (17_599, 20_000),
    "electrical": (23_131, 26_000),
    "mechanical": (19_415, 22_000),
    "industrial": (43_159, 48_000),
}
REQUIRED_NODES = {
    "industrial": (101_981, 113_000),
    "mechanical": (23_312, 26_000),
}
RANKED_NODES = (16_524, 19_000)


@pytest.fixture(scope="module")
def app():
    return api.create_app({"allow_network": False}, serve_ui=False)


@pytest.fixture(scope="module")
def client(app):
    c = app.test_client()
    # חימום: טעינת הקטלוג והמטמונים אינה חלק ממה שנמדד כאן.
    assert c.post("/api/solve", json={"codes": ["11061"], "semester": TERM}).status_code == 200
    return c


@pytest.fixture()
def nodes(monkeypatch):
    """סופר כל צומת חיפוש — כל ``_Budget.tick()`` — בכל השלבים של הבקשה."""
    counter = {"n": 0}
    tick = sch._Budget.tick  # noqa: SLF001

    def counting(self):
        counter["n"] += 1
        return tick(self)

    monkeypatch.setattr(sch._Budget, "tick", counting)  # noqa: SLF001
    return counter


def _page_attendance(app, codes):
    """מה ש-``attendanceBody()`` שולח: ‏False לכל רכיב שהידיעון אינו מחייב בו."""
    with app.app_context():
        built, _p, _m = api._build_courses(codes, semester=TERM)  # noqa: SLF001
    info = api.attendance_info(built)
    return {
        code: {kind: False for kind, rec in kinds.items() if not rec["from_yedion"]}
        for code, kinds in info.items()
    }


def _solve(client, nodes, body):
    """‏(התשובה, צמתי החיפוש, שניות) לבקשה אחת."""
    nodes["n"] = 0
    started = time.perf_counter()
    res = client.post("/api/solve", json=body)
    return res, nodes["n"], time.perf_counter() - started


def _check_work(label, visited, measured, budget, elapsed):
    assert visited <= budget, (
        f"{label}: {visited:,} צמתים, מעל התקציב {budget:,} (נמדד {measured:,} ב-2026-10-21)"
    )
    assert elapsed < WALL_GUARD_S, f"{label}: {elapsed:.2f} s — מעל רשת הביטחון"


@pytest.mark.parametrize("name", list(FIRST_YEAR))
def test_first_year_page_defaults_stay_within_their_node_budget(app, client, nodes, name):
    codes, before = FIRST_YEAR[name]
    body = {"codes": codes, "semester": TERM, "target_days": 6, "top_n": 5,
            "allow_soft_conflicts": True, "attendance": _page_attendance(app, codes)}
    res, visited, elapsed = _solve(client, nodes, body)
    assert res.status_code == 200, res.get_data(as_text=True)
    data = res.get_json()
    assert data["timed_out"] is False, "הגיע למגבלת הזמן — כלומר לא נפתר"
    assert len(data["schedules"]) == 5
    assert not any(s["truncated"] for s in data["schedules"])
    assert data["viability_skipped"] is False and data["viability_truncated"] is False
    # עשרות-מאות אלפי צירופים: הספירה נעצרת במכסה ואומרת זאת.
    assert data["feasible_count"] == api.FEASIBLE_COUNT_CAP
    assert data["feasible_count_capped"] is True
    measured, budget = PAGE_NODES[name]
    _check_work(f"{name} (לפני 2026-10-20: {before})", visited, measured, budget, elapsed)


@pytest.mark.parametrize("name", list(REQUIRED_NODES))
def test_first_year_with_every_component_required_stays_within_budget(client, nodes, name):
    """בלי ויתור על נוכחות כלל — הנתיב השני; תעשייה וניהול היה 12 שניות."""
    codes, _before = FIRST_YEAR[name]
    res, visited, elapsed = _solve(client, nodes,
                                   {"codes": codes, "semester": TERM, "target_days": 6})
    assert res.status_code == 200
    assert res.get_json()["timed_out"] is False
    measured, budget = REQUIRED_NODES[name]
    _check_work(name, visited, measured, budget, elapsed)


def test_a_ranked_first_year_with_a_day_target_stays_within_budget(app, client, nodes):
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
    res, visited, elapsed = _solve(client, nodes, body)
    assert res.status_code == 200
    data = res.get_json()
    assert data["timed_out"] is False and data["schedules"]
    assert data["schedules"][0]["lecturer_total"] > 0
    measured, budget = RANKED_NODES
    _check_work("ranked civil", visited, measured, budget, elapsed)


def test_the_node_count_is_deterministic(app, client, nodes):
    """שתי הרצות של אותה בקשה: אותו מספר צמתים בדיוק — זה מה שמצדיק לבדוק אותו."""
    codes, _before = FIRST_YEAR["industrial"]
    body = {"codes": codes, "semester": TERM, "target_days": 6,
            "attendance": _page_attendance(app, codes)}
    _res, first, _t = _solve(client, nodes, body)
    _res, second, _t = _solve(client, nodes, body)
    assert first == second > 0
