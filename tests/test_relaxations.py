# -*- coding: utf-8 -*-
"""ויתורים נמדדים — לא מוערכים.

שלוש התחייבויות נבדקות כאן:

1. כל מספר מגיע מפתירה אמיתית. חיפוש שנקטע במכסה מחזיר "לפחות N", ולכן
   הוא נחשב **לא נמדד** ולא מוצג כמספר. מספר משוער נראה כמו הבטחה.
2. הוויתור אומר מה הוא **גובה**, לא רק מה הוא פותח.
3. כשאף ויתור בודד אינו עוזר אבל צירוף של שניים כן — אומרים את זה, ולא
   מציגים רשימה ריקה.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src import scheduler as S  # noqa: E402
from src.models import Group, Meeting, Selection  # noqa: E402
from src.store import _course_from_dict  # noqa: E402

CODES = ["11069", "61756", "61757", "62027", "61759", "61832"]


@pytest.fixture(scope="module")
def courses():
    path = ROOT / "data" / "db" / "sections.json"
    if not path.is_file():
        pytest.skip("אין מסד מקומי")
    raw = json.loads(path.read_text(encoding="utf-8"))["courses"]
    out = [_course_from_dict(raw[c]["course"], c) for c in CODES if c in raw]
    if len(out) < len(CODES):
        pytest.skip("חסרים קורסים במסד")
    return out


# ==========================================================================
# 1. רק אילוצים שהוגדרו בפועל מוצעים
# ==========================================================================
def test_nothing_is_offered_when_no_constraint_is_set():
    prefs = S.Preferences(target_days=4)
    assert S._relax_candidates(prefs) == []


def test_only_the_constraints_actually_set_are_offered():
    prefs = S.Preferences(target_days=4, forbid_friday=True, earliest=9 * 60)
    kinds = {k for k, _d, _a in S._relax_candidates(prefs)}
    assert kinds == {S.CONSTRAINT_FRIDAY, S.CONSTRAINT_EARLIEST}
    assert S.CONSTRAINT_LATEST not in kinds, "הוצע ויתור על אילוץ שלא הוגדר"


def test_each_blocked_window_is_offered_separately():
    prefs = S.Preferences(
        target_days=4,
        blocked_windows=[(1, 480, 600), (3, 720, 840)],
    )
    blocked = [d for k, d, _a in S._relax_candidates(prefs)
               if k == S.CONSTRAINT_BLOCKED]
    assert len(blocked) == 2, "חלונות חסומים לא הוצעו בנפרד"


# ==========================================================================
# 2. המקור אינו משתנה
# ==========================================================================
def test_applying_a_delta_never_mutates_the_original():
    prefs = S.Preferences(target_days=4, forbid_friday=True,
                          blocked_windows=[(1, 480, 600)])
    S._apply_delta(prefs, {"forbid_friday": False})
    S._apply_delta(prefs, {"drop_blocked_window": [1, 480, 600]})
    assert prefs.forbid_friday is True
    assert prefs.blocked_windows == [(1, 480, 600)]


# ==========================================================================
# 3. נמדד, ולא מוערך
# ==========================================================================
def test_a_relaxation_that_helps_reports_a_real_count(courses):
    prefs = S.Preferences(target_days=4, latest=13 * 60)
    with pytest.raises(S.Infeasible):
        S.solve(courses, prefs)
    rep = S.relaxations(courses, prefs)
    assert not rep.pairs_only
    helpful = rep.best()
    assert helpful, "ויתור שפותר לא זוהה"
    top = helpful[0]
    assert top.kind == S.CONSTRAINT_LATEST
    assert isinstance(top.schedules, int) and top.schedules > 0
    # והמספר אמיתי: פתירה עם הוויתור מחזירה בדיוק אותו מספר
    actual = S.solve(courses, S._apply_delta(prefs, top.apply), top_n=5)
    assert len(actual) == top.schedules


@pytest.mark.filterwarnings("ignore::RuntimeWarning")
def test_a_truncated_search_is_reported_as_unmeasured_not_as_a_number(courses):
    """מכסה זעירה => "לפחות N" => לא מציגים מספר בכלל.

    האזהרה של ``solve`` על חיפוש שנקטע צפויה כאן — היא בדיוק מה שהבדיקה
    מייצרת בכוונה, ולכן היא מושתקת ולא נשארת כרעש בפלט.
    """
    prefs = S.Preferences(target_days=4, latest=13 * 60)
    rep = S.relaxations(courses, prefs, limit=1)
    assert rep.singles, "לא הוצע דבר"
    assert all(r.schedules is None for r in rep.singles), (
        "חיפוש שנקטע הציג מספר — זה ניחוש, לא מדידה"
    )


def test_an_impossible_relaxation_reports_zero_not_none(courses):
    """אפס הוא מדידה ("בדקתי, לא עוזר"); ‏None הוא היעדר מדידה."""
    prefs = S.Preferences(target_days=4, earliest=12 * 60, latest=15 * 60)
    rep = S.relaxations(courses, prefs)
    assert rep.measured_useless(), "אף ויתור לא נמדד כ'לא עוזר'"


# ==========================================================================
# 4. המחיר, לא רק הרווח
# ==========================================================================
def test_a_helpful_relaxation_states_what_it_costs(courses):
    prefs = S.Preferences(target_days=4, latest=13 * 60)
    top = S.relaxations(courses, prefs).best()[0]
    assert top.cost, "ויתור בלי מחיר — מוכר את הרווח ומשמיט את המחיר"
    assert top.cost["metric"] == "ends_at"
    # והמחיר מדוד: זו באמת השעה שבה נגמר היום הכי מאוחר
    assert top.cost["minutes"] > 13 * 60, "המחיר אינו משקף את הוויתור"


def test_the_friday_cost_counts_how_many_schedules_actually_use_friday():
    """המחיר של "לוותר על חסימת שישי" נספר מהמערכות עצמן.

    נבדק ישירות על ``_cost_of`` ולא דרך המסד: קודם היה כאן ``pytest.skip``
    למקרה שביטול שישי לבדו אינו פותר בנתונים שבמסד — כלומר הבדיקה הייתה
    מדלגת על עצמה בשקט ולא בודקת דבר. בדיקה שמדלגת על עצמה אינה בדיקה,
    וזה בדיוק מה שהסתיר 171 דמפים מורעלים במשך יום שלם.
    """
    def sched(days):
        groups = [
            Group(course_code="900", group_id=str(i), kind="הרצאה", lecturer="",
                  meetings=[Meeting(day=d, start=510, end=630)])
            for i, d in enumerate(days)
        ]
        return S.score(Selection(groups), S.Preferences(target_days=6))

    with_friday = sched([S.FRIDAY])
    without = sched([1])

    cost = S._cost_of(S.CONSTRAINT_FRIDAY, {}, [with_friday, without])
    assert cost == {"metric": "friday", "n": 1, "of": 2}

    all_friday = S._cost_of(S.CONSTRAINT_FRIDAY, {}, [with_friday, with_friday])
    assert all_friday["n"] == all_friday["of"] == 2, "כולן עם שישי — וזה מה שנאמר"

    none = S._cost_of(S.CONSTRAINT_FRIDAY, {}, [without])
    assert none["n"] == 0, "אף אחת עם שישי — וגם זה נאמר"


# ==========================================================================
# 5. כשרק צירוף עוזר — אומרים את זה
# ==========================================================================
def test_when_only_a_pair_helps_it_is_said_plainly(courses):
    prefs = S.Preferences(target_days=4, forbid_friday=True,
                          earliest=9 * 60, latest=16 * 60)
    with pytest.raises(S.Infeasible):
        S.solve(courses, prefs)
    rep = S.relaxations(courses, prefs)
    assert rep.pairs_only, "אף ויתור בודד לא עוזר — וזה לא נאמר"
    assert rep.pairs, "רשימה ריקה במקום 'שילוב של שניים כן'"
    assert rep.singles, "המדידות של הבודדים אבדו"
    top = rep.pairs[0]
    assert top.combines_with, "לא נאמר עם מה הוויתור מצטרף"
    assert top.combines_with["kind"] != top.kind
    # והצירוף באמת עובד
    stepped = S._apply_delta(S._apply_delta(prefs, top.apply),
                             top.combines_with["apply"])
    assert len(S.solve(courses, stepped, top_n=5)) == top.schedules
