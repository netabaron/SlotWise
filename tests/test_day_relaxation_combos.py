# -*- coding: utf-8 -*-
"""יעד ימים שאף ויתור בודד אינו מגיע אליו — שילוב, או הצעד הקרוב ביותר.

הבאג (2026-11-09): המינימום 5 ויעד 4 — "ויתור על X יאפשר 4 ימים". יעד 3 —
רק "אי אפשר להגיע ל-3 ימים, גם בוויתור על קורס אחד.", גם כשוויתור על שניים
כן מגיע. ‏``day_relaxations`` מדד רק יחידת ויתור אחת, ו-``helpful()`` השאיר
רק מה שמגיע ליעד — ולכן הרשימה התרוקנה. מגבלת הזמן לא הייתה הסיבה: בקטלוג
המשלוח אף בקשה לא הגיעה אליה.

מה שנבדק כאן:
  * אין ויתור בודד שמגיע, ויש זוג — הזוג מוחזר, מהזול לנזק;
  * אין שילוב של עד שלוש יחידות שמגיע — ‏``closest``: מה שמוריד הכי הרבה;
  * שום דבר אינו מוריד — שני השדות ריקים, והממשק אומר שורה אחת;
  * כל מספר הוא פתירה אמיתית, וחיפוש שנקטע אינו מסמן את הבקשה כ-``timed_out``;
  * ‏/api/solve בקטלוג הקפוא — הנדסה אזרחית סמסטר 3, המקרה שדווח.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from src import scheduler as S  # noqa: E402
from src.models import Course, Group, Meeting  # noqa: E402


def _course(code, credits, day, slot):
    """קורס עם הרצאה אחת: יום ומשבצת (08:00, 10:00, …) נשלטים במדויק.

    שני קורסים באותו יום יושבים במשבצות שונות, כך שאינם מתנגשים — וויתור
    על אחד מהם לבדו אינו משחרר את היום.
    """
    start = 480 + slot * 120
    return Course(
        code=code,
        name="קורס " + code,
        credits=credits,
        groups=[
            Group(course_code=code, group_id="1", kind="הרצאה", lecturer="",
                  meetings=[Meeting(day=day, start=start, end=start + 110)])
        ],
    )


def _codes(drops):
    return [o.codes for o in drops]


def _relax(courses, target, **kw):
    return S.day_relaxations(courses, S.Preferences(target_days=target), target, **kw)


#: שלושה ימים, שני קורסים בכל יום. ויתור בודד אינו משחרר אף יום (3 ימים);
#: זוג משחרר יום רק אם שני הקורסים שלו באותו יום. מחירי הימים: 2, 4, 6 נ"ז.
#: ‏{101, 201} עולה 3 — זול יותר מ-{201, 202} — ואינו משחרר דבר.
TWO_PER_DAY = [
    _course("101", 1, 1, 0), _course("102", 1, 1, 1),
    _course("201", 2, 2, 0), _course("202", 2, 2, 1),
    _course("301", 3, 3, 0), _course("302", 3, 3, 1),
]


# ==========================================================================
# 1. אין ויתור בודד — יש זוג
# ==========================================================================
def test_a_pair_is_returned_when_no_single_drop_reaches_the_target():
    rep = _relax(TWO_PER_DAY, 2)
    assert rep.helpful() == [], "ויתור בודד אינו מגיע ל-2 — זה כל הטעם של הבדיקה"
    assert {o.min_days for o in rep.options} == {3}
    assert _codes(rep.combos) == [["101", "102"], ["201", "202"], ["301", "302"]]
    assert [o.credits for o in rep.combos] == [2.0, 4.0, 6.0], "מהזול לנזק"
    assert [o.min_days for o in rep.combos] == [2, 2, 2]
    assert all(len(o.units) == 2 for o in rep.combos)
    assert rep.combos_complete is True
    assert rep.closest == [], "יש שילוב שמגיע — אין צורך ב'הכי קרוב'"
    # ‏{101, 201} זול מ-{201, 202} אבל אינו מגיע — ואינו מוצע.
    assert ["101", "201"] not in _codes(rep.combos)


def test_every_combination_number_is_a_real_solve():
    rep = _relax(TWO_PER_DAY, 2)
    prefs = S.Preferences(target_days=2)
    for drop in rep.combos:
        kept = [c for c in TWO_PER_DAY if c.code not in drop.codes]
        assert S.min_days(kept, prefs) == drop.min_days, drop.codes


def test_combinations_of_different_sizes_are_ranked_by_credits():
    """זוג אחד מגיע (10 נ"ז), ושתי שלישיות זולות ממנו (3 ו-6)."""
    courses = [
        _course("101", 5, 1, 0), _course("102", 5, 1, 1),
        _course("201", 1, 2, 0), _course("202", 1, 2, 1), _course("203", 1, 2, 2),
        _course("301", 2, 3, 0), _course("302", 2, 3, 1), _course("303", 2, 3, 2),
    ]
    rep = _relax(courses, 2)
    assert rep.helpful() == []
    assert _codes(rep.combos) == [["201", "202", "203"], ["301", "302", "303"], ["101", "102"]]
    assert [o.credits for o in rep.combos] == [3.0, 6.0, 10.0]
    # ‏שלישייה שמכילה את הזוג שכבר מגיע — אותו יעד, במחיר גבוה יותר.
    assert not [o for o in rep.combos if {"101", "102"} < set(o.codes)]


def test_out_of_plan_courses_go_first_when_credits_tie():
    courses = [
        _course("101", 1, 1, 0), _course("102", 1, 1, 1),
        _course("201", 1, 2, 0), _course("202", 1, 2, 1),
        _course("301", 5, 3, 0), _course("302", 5, 3, 1),
    ]
    assert _codes(_relax(courses, 2).combos)[:2] == [["101", "102"], ["201", "202"]]
    planned = _relax(courses, 2, plan={"101", "102", "301", "302"})
    assert _codes(planned.combos)[:2] == [["201", "202"], ["101", "102"]]


def test_a_combination_with_unknown_credits_comes_after_priced_ones():
    """נ"ז 0 בידיעון אינו "בחינם" — לא ממציאים לו מחיר, גם לא את הנמוך ביותר."""
    courses = [
        _course("101", 0, 1, 0), _course("102", 0, 1, 1),
        _course("201", 3, 2, 0), _course("202", 3, 2, 1),
        _course("301", 4, 3, 0), _course("302", 4, 3, 1),
    ]
    rep = _relax(courses, 2)
    assert _codes(rep.combos) == [["201", "202"], ["301", "302"], ["101", "102"]]
    assert [o.credits_known for o in rep.combos] == [True, True, False]


def test_a_single_drop_that_reaches_skips_the_combination_search():
    courses = [_course("101", 1, 1, 0), _course("201", 1, 2, 0)]
    rep = _relax(courses, 1)
    assert _codes(rep.helpful()) == [["101"], ["201"]]
    assert rep.combos == [] and rep.closest == []
    assert rep.combos_complete is None, "לא חיפשו — ואין מה לטעון"


# ==========================================================================
# 2. אין שילוב שמגיע — הצעד הקרוב ביותר
# ==========================================================================
def test_the_closest_step_when_no_combination_reaches_the_target():
    """יום 1: קורס אחד. ימים 2 ו-3: ארבעה קורסים כל אחד.

    יום אחד דורש לוותר על שני ימים שלמים — חמש יחידות לפחות. ויתור על ‏101
    משחרר את יום 1 — וזה הצעד שמקרב הכי הרבה.
    """
    courses = [_course("101", 5, 1, 0)] + [
        _course(f"{day}0{i}", day - 1, day, i) for day in (2, 3) for i in range(4)
    ]
    rep = _relax(courses, 1)
    assert rep.helpful() == [] and rep.combos == []
    assert rep.combos_complete is True, "כל שילוב של עד 3 יחידות נמדד"
    assert _codes(rep.closest) == [["101"]]
    assert rep.closest[0].min_days == 2


def test_the_closest_step_falls_back_to_combinations_without_padding():
    """אף ויתור בודד אינו מוריד יום; זוג של יום שלם כן, אבל לא עד יום אחד.

    שלישייה של "זוג שמשחרר יום + עוד קורס" נותנת אותם 2 ימים במחיר גבוה
    יותר — היא אינה צעד, ואינה מוצעת.
    """
    rep = _relax(TWO_PER_DAY, 1)
    assert rep.helpful() == [] and rep.combos == []
    assert {o.min_days for o in rep.options} == {3}
    assert _codes(rep.closest) == [["101", "102"], ["201", "202"], ["301", "302"]]
    assert [o.min_days for o in rep.closest] == [2, 2, 2]


def test_nothing_lowers_it_leaves_both_lists_empty():
    """ארבעה קורסים בכל יום: אף שילוב של עד שלוש יחידות אינו משחרר יום."""
    courses = [_course(f"{day}0{i}", 1, day, i) for day in (1, 2) for i in range(4)]
    rep = _relax(courses, 1)
    assert rep.helpful() == [] and rep.combos == [] and rep.closest == []
    assert rep.combos_complete is True
    assert len(rep.measured_useless()) == 8, "הוויתורים הבודדים נמדדו כמו תמיד"


# ==========================================================================
# 3. הזמן
# ==========================================================================
def test_an_expired_request_does_not_search_combinations(monkeypatch):
    monkeypatch.setattr(S, "_CLOCK_EVERY", 1)
    with S.time_budget(0.0):
        rep = _relax(TWO_PER_DAY, 2, base_min=3)
    assert rep.combos == [] and rep.closest == []
    assert rep.combos_complete is False


def test_a_cut_combination_search_says_so_and_does_not_flag_the_request(monkeypatch):
    """עצה שלא הספיקה אינה "המערכת נעצרה": ``timed_out`` נשאר ``False``."""
    monkeypatch.setattr(S, "_CLOCK_EVERY", 1)
    monkeypatch.setattr(S, "COMBO_SECONDS", 0.0)
    with S.time_budget(60.0):
        rep = _relax(TWO_PER_DAY, 2)
        assert S.time_budget_expired() is False
    assert rep.combos == []
    assert rep.combos_complete is False, "לא נמדד הכול — אסור לטעון 'אי אפשר'"
    assert {o.min_days for o in rep.options} == {3}, "הוויתורים הבודדים נמדדו לפני"


def test_the_advisory_budget_never_extends_the_request_and_reports_its_end(monkeypatch):
    monkeypatch.setattr(S, "_CLOCK_EVERY", 1)
    prefs = S.Preferences(target_days=2)
    with S.time_budget(0.0):
        with S._advisory_budget(3600.0):  # noqa: SLF001
            with pytest.raises(S.SearchTimedOut):
                S.min_days(TWO_PER_DAY, prefs)
        assert S.time_budget_expired() is True, "המועד של הבקשה עבר — זה כן נאמר"


# ==========================================================================
# 4. ‏/api/solve בקטלוג הקפוא — המקרה שדווח
# ==========================================================================
from src.web import api  # noqa: E402
from test_solver_all_programmes import (  # noqa: E402
    courses_request,
    offered_cases,
    page_attendance,
    recommended_codes,
    semester_list,
    solve_body,
)

#: ‏הנדסה אזרחית סמסטר 3, הבחירה שהדף ממליץ עליה: המינימום 5. יעד 4 — ויתור
#: בודד; יעד 3 — אף ויתור בודד. ‏``conftest.py`` מפנה כל בדיקה לקטלוג הקפוא
#: ‏(``tests/fixtures/catalog``); קטלוג המשלוח נתן את אותם מספרים (2026-11-09).
CASE = "civil-s3"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    # ‏מסד ריק — כמו ב-CI: רק הקטלוג (הקפוא, ראו ``conftest.py``).
    empty = tmp_path_factory.mktemp("empty-store")
    app = api.create_app({"allow_network": False}, serve_ui=False, db_root=empty)
    return app.test_client()


@pytest.fixture(scope="module")
def page_default(client):
    boot = client.get("/api/bootstrap").get_json()
    case = next(c for c in offered_cases(boot) if c["id"] == CASE)
    codes = recommended_codes(semester_list(client, case), boot["limits"]["max_codes"])
    year = boot["defaults"].get("academic_year", "")
    attendance = page_attendance(courses_request(client, case, codes, year)["attendance"])

    def solve(target, without=()):
        kept = [c for c in codes if c not in without]
        att = {k: v for k, v in attendance.items() if k in kept}
        res = client.post("/api/solve", json=solve_body(case, kept, att, year, target_days=target))
        assert res.status_code == 200, res.get_data(as_text=True)
        return res.get_json()

    return solve


def _assert_the_case_is_what_was_measured(data):
    assert data["min_days"] == 5, (
        f"{CASE}: המינימום הוא {data['min_days']} ולא 5 — הקטלוג השתנה; יש למדוד מחדש"
    )
    assert data["timed_out"] is False


def test_api_offers_pairs_when_no_single_drop_reaches(page_default):
    data = page_default(3)
    _assert_the_case_is_what_was_measured(data)
    rel = data["day_relaxations"]
    assert rel["items"] == [], f"{CASE}: ויתור בודד מגיע ל-3 — הבדיקה אינה בודקת את הבאג"
    assert rel["checked"], "הוויתורים הבודדים נמדדו ונשלחים כמו קודם"
    assert rel["combos"], "אין שילוב — זה הבאג שדווח"
    assert len(rel["combos"]) <= 3
    for combo in rel["combos"]:
        assert len(combo["units"]) >= 2 and combo["min_days"] <= 3, combo
        # ‏המספר הוא פתירה אמיתית: אותה בקשה, בלי הקורסים — אותו מינימום.
        assert page_default(6, without=combo["codes"])["min_days"] == combo["min_days"], combo


def test_api_offers_the_closest_step_when_no_combination_reaches(page_default):
    data = page_default(1)
    _assert_the_case_is_what_was_measured(data)
    rel = data["day_relaxations"]
    assert rel["items"] == [] and rel["combos"] == []
    assert rel["combos_complete"] is True and rel["combo_max_units"] == 3
    assert rel["closest"], "יש ויתור שמוריד יום — הוא חייב להיות מוצע"
    best = {c["min_days"] for c in rel["closest"]}
    assert len(best) == 1 and best.pop() < 5, rel["closest"]
    singles = [c["min_days"] for c in rel["checked"]]
    assert rel["closest"][0]["min_days"] == min(singles), "הבודדים שמורידים הכי הרבה"
    for step in rel["closest"]:
        assert page_default(6, without=step["codes"])["min_days"] == step["min_days"], step


def test_api_passes_the_students_plan(client, page_default, monkeypatch):
    seen = []
    real = api.scheduler_mod.day_relaxations

    def spy(*args, **kwargs):
        seen.append(kwargs.get("plan"))
        return real(*args, **kwargs)

    monkeypatch.setattr(api.scheduler_mod, "day_relaxations", spy)
    data = page_default(3)
    assert seen and seen[-1], "‏/api/solve עם מסלול חייב למסור את קודי התוכנית"
    assert set(data["codes"]) <= seen[-1], "בחירת ברירת המחדל כולה בתוכנית"
