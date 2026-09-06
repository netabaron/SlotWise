# -*- coding: utf-8 -*-
"""הפסקת הצהריים הקבועה אינה זמן המתנה.

‏12:20–12:50 הוא חלון שאי אפשר לקבוע בו שיעור. קנס על המתנה בתוכו מעניש
כל מי שיש לו שיעור משני צדדיו — כלומר כמעט כל מערכת — על חצי שעה שאיש לא
בחר בה. הקובץ הזה מחזיק את שני הצדדים של ההבחנה: מי שיש לו הפסקה בפועל
מזוכה, ומי ששיעורו רץ דרך החלון אינו מזוכה בדבר.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src import scheduler  # noqa: E402
from src.models import Group, Meeting, Selection  # noqa: E402

LUNCH = scheduler.LUNCH_WINDOW
T1130, T1220, T1250, T1350, T1440 = 690, 740, 770, 830, 880
T0830, T1030 = 510, 630


def _sel(*spans: tuple[int, int, int]) -> Selection:
    """מערכת מפגשים חשופה: (יום, התחלה, סוף)."""
    groups = []
    for i, (day, start, end) in enumerate(spans):
        groups.append(
            Group(
                course_code="9000%d" % i,
                group_id="%d" % i,
                kind="הרצאה",
                lecturer="ד\"ר בדיקה",
                meetings=[Meeting(day=day, start=start, end=end, room="", building="")],
            )
        )
    return Selection(groups)


# ==========================================================================
# 1. מה מזוכה ומה לא
# ==========================================================================
def test_a_real_break_in_the_window_is_credited():
    """‏11:30–12:20 ואז 12:50–13:50: החור הוא בדיוק הצהריים, ולכן אינו נספר."""
    sel = _sel((1, T1130, T1220), (1, T1250, T1350))
    assert sel.gap_minutes() == 30, "המדידה עצמה אינה משתנה"
    assert sel.billable_gap_minutes(LUNCH) == 0, "הצהריים אינם זמן המתנה"


def test_a_meeting_running_through_the_window_gets_nothing():
    """שיעור 11:30–13:50 עובר דרך החלון — אין לו הפסקה, ואין לו זיכוי.

    זה הסייג החשוב: הזיכוי ניתן על חור בפועל, לא על השעה שבלוח. ‏92
    מפגשים במסד עוברים כך דרך החלון.
    """
    sel = _sel((1, T1130, T1350), (1, T1440, T1440 + 60))
    assert sel.gap_minutes() == T1440 - T1350 == 50
    # ‏50 דקות המתנה אחרי 13:50 — כולן נספרות, כי אף לא אחת מהן בצהריים.
    assert sel.billable_gap_minutes(LUNCH) == 50


def test_a_day_with_no_break_at_all_is_unaffected():
    sel = _sel((1, T1130, T1350))
    assert sel.gap_minutes() == 0
    assert sel.billable_gap_minutes(LUNCH) == 0


def test_only_the_overlap_is_credited_not_the_whole_gap():
    """חור 12:00–14:00 מזוכה ב-30 דקות בלבד — לא ב-120."""
    sel = _sel((1, T0830, 720), (1, 840, 900))
    assert sel.gap_minutes() == 120
    assert sel.billable_gap_minutes(LUNCH) == 90


def test_a_gap_far_from_noon_is_untouched():
    """חור 14:00–17:00 — רחוק מהצהריים, ולכן נספר במלואו."""
    sel = _sel((1, 840, 900), (1, 1020, 1080))
    assert sel.gap_minutes() == 120
    assert sel.billable_gap_minutes(LUNCH) == 120


def test_no_window_means_no_credit():
    sel = _sel((1, T1130, T1220), (1, T1250, T1350))
    assert sel.billable_gap_minutes(None) == sel.gap_minutes() == 30


# ==========================================================================
# 2. הניקוד משתמש במספר שנספר לחובה — והתצוגה במספר המלא
# ==========================================================================
def test_score_charges_the_billable_gap_but_reports_the_real_one():
    sel = _sel((1, T1130, T1220), (1, T1250, T1350))
    sched = scheduler.score(sel, scheduler.Preferences(target_days=5))
    assert sched.gap_minutes == 30, "המספר המוצג הוא זמן ההמתנה האמיתי"
    assert sched.breakdown["gaps"] == 0.0, "ואין קנס על הצהריים"


def test_score_still_charges_waiting_that_is_not_lunch():
    sel = _sel((1, T0830, T1030), (1, 750, 810))
    sched = scheduler.score(sel, scheduler.Preferences(target_days=5))
    # חור 10:30–12:30: מתוכו רק 10 דקות (12:20–12:30) בצהריים.
    assert sched.gap_minutes == 120
    assert sched.breakdown["gaps"] < 0, "המתנה אמיתית עדיין עולה ניקוד"


# ==========================================================================
# 3. שמירה על ההנחה עצמה
# ==========================================================================
def test_the_window_still_matches_the_yedion_data():
    """הקבוע נגזר מהנתונים, ולכן הוא נבדק מולם.

    במסד יש רק סמסטר א'. ביום שבו ייכנסו נתוני סמסטר ב' עם לוח אחר,
    עדיף שהבדיקה תיפול כאן ולא שההנחה תמשיך לעבוד בשקט.
    """
    path = ROOT / "data" / "db" / "sections.json"
    if not path.is_file():
        return  # אין מסד מקומי — אין מה לאמת
    db = json.loads(path.read_text(encoding="utf-8"))
    low, high = LUNCH
    starts_inside, ends_inside = [], []
    for rec in db.get("courses", {}).values():
        for group in rec.get("course", {}).get("groups", []):
            for m in group.get("meetings") or []:
                start, end = m.get("start"), m.get("end")
                if start is None or end is None:
                    continue
                if low < start < high:
                    starts_inside.append(start)
                if low < end < high:
                    ends_inside.append(end)
    assert not starts_inside, f"מפגש מתחיל בתוך חלון הצהריים: {starts_inside[:5]}"
    assert not ends_inside, f"מפגש מסתיים בתוך חלון הצהריים: {ends_inside[:5]}"
