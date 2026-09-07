# -*- coding: utf-8 -*-
"""יעד ימים שאינו בר-השגה — איזה ויתור על קורס יפתח אותו.

אותם כללים כמו הוויתור על אילוץ, ועוד שניים שהם ייחודיים לוויתור על
קורס — כי לוותר על קורס זו בקשה גדולה יותר מלהרפות אילוץ:

* יחידת הוויתור היא **חבילה צמודה** ולא קורס בודד, כי הידיעון אוסר
  לפרק אותה.
* הסדר הוא לפי **נזק**: פחות נקודות זכות קודם. שני קורסים שפותחים את
  אותו יעד אינם שקולים.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src import scheduler as S  # noqa: E402
from src.models import Course, Group, Meeting  # noqa: E402


def _course(code, credits, day, tied=()):
    """קורס עם הרצאה אחת ביום נתון — כך 'ימים' נשלט במדויק.

    השעה נגזרת מהקוד ותחומה לשש משבצות. שתי דרישות מתנגשות כאן: שני
    קורסים באותו יום ובאותה שעה מתנגשים ואז אין פתרון כלל, אבל מונה
    גלובלי שרק עולה מייצר בסוף שעות אחרי 24:00 — שנפסלות על ידי אילוץ
    ``latest`` ומרוקנות את החיפוש. גזירה מהקוד פותרת את שתיהן, ובלי
    מצב משותף שדולף בין בדיקות.
    """
    start = 480 + (sum(ord(ch) for ch in code) % 6) * 120
    return Course(
        code=code,
        name="קורס " + code,
        credits=credits,
        groups=[
            Group(course_code=code, group_id="1", kind="הרצאה", lecturer="",
                  meetings=[Meeting(day=day, start=start, end=start + 110)])
        ],
        tied_with=list(tied),
    )


# ==========================================================================
# 1. יחידת הוויתור
# ==========================================================================
def test_a_lone_course_is_its_own_unit():
    units = S._tied_units([_course("A", 3, 1), _course("B", 3, 2)])
    assert sorted(units) == [["A"], ["B"]]


def test_a_tied_package_is_one_unit_not_three():
    """‏solve זורק TiedCoursesError על פירוק חבילה — אז לא מציעים לפרק."""
    courses = [
        _course("A", 3, 1, tied=("B", "C")),
        _course("B", 2, 2, tied=("A", "C")),
        _course("C", 2, 3, tied=("A", "B")),
    ]
    units = S._tied_units(courses)
    assert units == [["A", "B", "C"]], units


# ==========================================================================
# 2. נמדד, ולא מוערך
# ==========================================================================
def test_it_says_nothing_when_the_target_is_already_reachable():
    courses = [_course("A", 3, 1), _course("B", 3, 1)]  # שניהם ביום 1
    rep = S.day_relaxations(courses, S.Preferences(target_days=1), 1)
    assert rep.reachable_without_dropping
    assert rep.options == [], "הוצע ויתור כשלא היה צורך"


def test_a_helpful_drop_reports_the_measured_day_count():
    courses = [_course("A", 3, 1), _course("B", 3, 2), _course("C", 3, 3)]
    rep = S.day_relaxations(courses, S.Preferences(target_days=2), 2)
    assert not rep.reachable_without_dropping
    helpful = rep.helpful()
    assert helpful, "אף ויתור לא זוהה כמועיל"
    for opt in helpful:
        assert opt.min_days == 2, "מספר הימים אינו מדוד"
        # ובאמת: פתירה בלי הקורס הזה נותנת בדיוק את זה
        kept = [c for c in courses if c.code not in opt.codes]
        got, _ = S._min_days_of(kept, S.Preferences(target_days=2), None)
        assert got == opt.min_days


def test_a_truncated_measurement_is_not_reported_as_a_number():
    courses = [_course(c, 3, i + 1) for i, c in enumerate("ABCD")]
    rep = S.day_relaxations(courses, S.Preferences(target_days=1), 1, limit=1)
    assert all(o.min_days is None for o in rep.options), (
        "חיפוש שנקטע הציג מספר ימים — זה ניחוש"
    )
    assert rep.helpful() == [], "ויתור לא מדוד הוצג כמועיל"


def test_options_that_do_not_help_are_kept_as_measured_not_dropped():
    """‏"בדקנו ולא הספיק" הוא מידע, ולכן הוא נשמר בנפרד מ"לא נמדד"."""
    courses = [_course(c, 3, i + 1) for i, c in enumerate("ABCD")]
    rep = S.day_relaxations(courses, S.Preferences(target_days=1), 1)
    assert rep.measured_useless(), "המדידות השליליות אבדו"
    for opt in rep.measured_useless():
        assert opt.min_days is not None and opt.min_days > 1


# ==========================================================================
# 3. סדר לפי נזק
# ==========================================================================
def test_cheaper_in_credits_comes_first_when_both_unlock():
    """שני קורסים שפותחים את אותו יעד — הזול קודם.

    כל אחד מהם הוא הדייר היחיד של יום משלו, ולכן ויתור על כל אחד מהם
    לחוד מוריד את השבוע משלושה ימים לשניים.
    """
    courses = [
        _course("CORE", 3, 1),
        _course("CHEAP", 2, 2),
        _course("EXPENSIVE", 6, 3),
    ]
    rep = S.day_relaxations(courses, S.Preferences(target_days=2), 2)
    helpful = rep.helpful()
    unlock_codes = [o.codes[0] for o in helpful]
    assert "CHEAP" in unlock_codes and "EXPENSIVE" in unlock_codes
    assert unlock_codes.index("CHEAP") < unlock_codes.index("EXPENSIVE"), (
        "הקורס היקר הוצע לפני הזול — הסדר אינו לפי נזק"
    )


def test_the_credit_cost_of_a_package_is_the_sum_of_its_members():
    courses = [
        _course("A", 3, 2, tied=("B",)),
        _course("B", 4, 3, tied=("A",)),
        _course("C", 2, 1),
    ]
    rep = S.day_relaxations(courses, S.Preferences(target_days=1), 1)
    package = [o for o in rep.options if len(o.codes) > 1]
    assert package, "החבילה לא הוצעה כיחידה"
    assert package[0].credits == 7.0, package[0].credits


def test_dropping_everything_is_never_offered():
    courses = [_course("A", 3, 1)]
    rep = S.day_relaxations(courses, S.Preferences(target_days=0), 0)
    assert all(o.codes != ["A"] for o in rep.options), "הוצע לוותר על כל הקורסים"
