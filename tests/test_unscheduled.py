"""
בדיקות לקורסים שנפתחים אבל **אין להם מועד קבוע**.

למה הקובץ הזה קיים
------------------
פרויקט גמר, התנסות בתעשייה, סמינר בתיאום אישי — קורסים אמיתיים, עם קבוצה
ועם מרצה, ובלי אף שורה בטבלת "מערכת שעות". הפרסר נהג לזרוק כל קבוצה בלי
מפגשים, ואז הקורס נעלם לגמרי **ודווח כ"כשל פענוח"** — כלומר גם לא היה, וגם
הוסתר מאחורי רעש של שגיאה. בבראודה תשפ"ז אלה 30 קורסים בסמסטר א'.

זו החלטה שגויה עבור בונה מערכת: אי אפשר *לשבץ* קבוצה כזאת, אבל בהחלט אפשר
ורוצים *להירשם* אליה ולספור את הנ"ז שלה. בלי מפגשים היא ממילא לא מתנגשת עם
כלום ולא תופסת שום משבצת ברשת.

המלכודת שחייבים להימנע ממנה
---------------------------
אחרי סינון הסמסטר, שני מצבים **נראים זהים** — רשימת מפגשים ריקה:
    (א) קבוצה שמעולם לא היה לה מועד      -> חייבת להישאר בת-בחירה
    (ב) קבוצה של סמסטר ב' שטרם נקבע מועדה -> אסור שתופיע במערכת של סמסטר א'
ההבחנה נעשית לפי הארגומנט השני של כפתור "פרטים נוספים" (``-N1``=א, ``-N2``=ב),
שהוא המקור היחיד בדף שאומר לאיזה סמסטר הקבוצה שייכת.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import parser as parser_mod  # noqa: E402
import scheduler as scheduler_mod  # noqa: E402
from models import Course, Group, Meeting  # noqa: E402

RAW = ROOT / "data" / "raw"


def _raw(code: str) -> str | None:
    """הדמפ העדכני של הקוד, או None. ``data/raw`` הוא git-ignored."""
    hits = sorted(p for p in RAW.glob(f"{code}_*.html") if "details" not in p.name)
    if not hits:
        return None
    html = hits[-1].read_text(encoding="utf-8", errors="replace")
    return html if "קורס מסוג" in html else None


# ==========================================================================
# 1. הכלל עצמו — בלי רשת, על נתונים בנויים ביד
# ==========================================================================
def test_a_group_with_no_meetings_never_conflicts():
    """בלי מפגשים אין חפיפה. זו הסיבה שאפשר לשבץ קורס כזה בבטחה."""
    unscheduled = Group("61998", "271060410", "פרויקט", "ד\"ר פלונית", [])
    busy = Group("61753", "271060330", "הרצאה", "ד\"ר אלמונית",
                 [Meeting(2, 510, 630, semester="א")])
    assert unscheduled.conflicts_with(busy) is False
    assert busy.conflicts_with(unscheduled) is False


def test_a_group_with_no_meetings_uses_no_days_and_no_slots():
    from models import Selection

    unscheduled = Group("61998", "271060410", "פרויקט", "מרצה", [])
    sel = Selection([unscheduled])
    assert sel.days_used() == set()
    assert sel.all_meetings() == []
    assert sel.gap_minutes() == 0
    assert sel.span_minutes() == 0
    assert sel.is_feasible() is True


def test_the_semester_code_is_read_from_the_details_button():
    """‏-N1 = א, ‏-N2 = ב. זה מה שמבדיל בין שני המצבים הזהים-למראה."""
    assert parser_mod.semester_from_details_args(
        'data-arguments="-N61753,-N1,-N1,-N271060330,-N"'
    ) == "א"
    assert parser_mod.semester_from_details_args(
        'data-arguments="-N61753,-N2,-N9,-N271060210,-N1"'
    ) == "ב"
    assert parser_mod.semester_from_details_args("no button here") == ""
    assert parser_mod.semester_from_details_args("") == ""


# ==========================================================================
# 2. על דפים אמיתיים של בראודה
# ==========================================================================
@pytest.mark.skipif(_raw("61998") is None, reason="אין דמפ של 61998")
def test_a_final_project_survives_and_is_marked_unscheduled():
    """‏61998 פרויקט מסכם: קבוצה אמיתית, מרצים אמיתיים, בלי שעות."""
    result = parser_mod.parse_course_page(_raw("61998"), "61998", semester="א")
    assert result.course is not None, "פרויקט מסכם נעלם — זו התקלה שהקובץ הזה שומר עליה"
    assert len(result.course.groups) == 1
    group = result.course.groups[0]
    assert group.meetings == []
    assert group.lecturer, "לקבוצה יש מרצה אמיתי גם בלי מועד"
    assert parser_mod.NO_FIXED_TIME_NOTE in group.note


@pytest.mark.skipif(_raw("61753") is None, reason="אין דמפ של 61753")
def test_unscheduled_groups_of_another_term_do_not_leak_in():
    """‏61753: 4 קבוצות בסמסטר א', ו-4 קבוצות ב' שטרם נקבע להן מועד.

    בלי קוד הסמסטר מהכפתור, ארבע קבוצות ה-ב' היו נראות כמו "אין מועד"
    ומחליקות פנימה — והסטודנט/ית היה/תה בוחר/ת קבוצה שאינה קיימת בסמסטר.
    """
    html = _raw("61753")
    first = parser_mod.parse_course_page(html, "61753", semester="א")
    second = parser_mod.parse_course_page(html, "61753", semester="ב")

    assert len(first.course.groups) == 4
    assert all(g.meetings for g in first.course.groups), "בסמסטר א' לכולן יש מועד"

    assert len(second.course.groups) == 4
    assert all(not g.meetings for g in second.course.groups), "בסמסטר ב' טרם נקבע מועד"

    ids_a = {g.group_id for g in first.course.groups}
    ids_b = {g.group_id for g in second.course.groups}
    assert not (ids_a & ids_b), "אותה קבוצה לא יכולה להופיע בשני הסמסטרים"


@pytest.mark.skipif(
    _raw("61753") is None or _raw("61998") is None, reason="אין דמפים"
)
def test_a_schedule_can_contain_a_course_with_no_fixed_time():
    """הבדיקה שסוגרת את המעגל: קורס בלי מועד נכנס למערכת ולא שובר אותה."""
    project = parser_mod.parse_course_page(_raw("61998"), "61998", semester="א").course
    algo = parser_mod.parse_course_page(_raw("61753"), "61753", semester="א").course
    project.credits, algo.credits = 4.0, 5.0

    best = scheduler_mod.solve([algo, project], scheduler_mod.Preferences(target_days=5), top_n=1)
    assert best, "חייב להימצא פתרון"
    chosen = best[0].selection
    codes = {g.course_code for g in chosen.groups}
    assert "61998" in codes, "הקורס בלי המועד חייב להיבחר, לא להיעלם"
    picked = [g for g in chosen.groups if g.course_code == "61998"][0]
    assert picked.meetings == []
    # והוא לא תרם ימים או חורים
    assert 6 not in chosen.days_used()
    assert chosen.is_feasible() is True
