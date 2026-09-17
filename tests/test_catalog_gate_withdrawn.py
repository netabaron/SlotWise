# -*- coding: utf-8 -*-
"""
שער 4: קורס שנעלם — האם זו נסיגה שלנו, או גריעה של המכללה?

מה קרה
------
הריצה הראשונה של הצינור הלילי (‏2026-09-17, ‏run 35262996905) רצה שעה
ו-39 דקות, שלפה ‏571 מתוך 571 קורסים עם **אפס** כישלונות, עברה חמישה
שערים — ונפלה על השישי:

    [נכשל] 4. אין נסיגה מול הקטלוג הקודם: קורסים שנעלמו: 1 (51961);
            מפגשים מתוזמנים 1184 מול 1187 = 99.7% (נדרש 95%)

הקורס ‏51961 ("יישומי בינה מלאכותית בתעשייה") לא נעלם בגללנו: **הידיעון
עצמו הפסיק לפרסם אותו.** אינדקס הקורסים שנשלף בתחילת אותה ריצה החזיר
‏571 שורות במקום 572, והקוד הזה מעולם לא נתבקש.

מה היה שבור בשער
-----------------
שער 4 הוא צירוף של שתי בדיקות שנכתבו בשני סגנונות שונים לגמרי:

    שימור מפגשים   ‏>= 95%   — טווח סבילות. עבר ב-99.7%.
    קורסים שנעלמו  ‏== 0      — מספר מוחלט. נפל על אחד מתוך 572.

כלומר: מכללה שגורעת קורס אחד — אירוע שגרתי לגמרי — מפילה את הבנייה, וכל
עדכון לגיטימי אחר (קורס חדש, שעה שזזה) נחסם מאחוריו עד שאדם יתערב.

התיקון
-------
‏``catalog`` שמגיע ל-``validate`` הוא האינדקס **הטרי** שנשלף בתחילת הריצה,
ולכן הוא בדיוק מה שמבדיל בין שתי הסיבות:

    נסיגה  = קוד שהידיעון עדיין מפרסם ואנחנו לא הפקנו  -> פוסל
    גריעה  = קוד שהידיעון כבר אינו מפרסם               -> מדווח, לא פוסל

הקובץ הזה נועל את ההבחנה. ‏``tests/test_catalog_gate.py`` נשאר כפי שהוא
ובודק את השערים מול השחתה אמיתית.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _path in (str(ROOT / "src"), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import build_catalog as B  # noqa: E402


def catalog(codes) -> dict:
    """אינדקס הקורסים כפי שהידיעון מחזיר אותו."""
    return {c: {"name": f"קורס {c}"} for c in codes}


def records(codes, meetings_per_course: int = 2) -> dict:
    """רשומות מפוענחות, עם מספר מפגשים ידוע לכל קורס."""
    return {
        c: {"groups": [{"semester": "א", "meetings": [
            {"start": 510, "end": 630} for _ in range(meetings_per_course)]}]}
        for c in codes
    }


def previous(codes, timed: int) -> dict:
    return {"counts": {"courses": len(codes), "groups": len(codes),
                       "timed_meetings": timed},
            "codes": sorted(codes)}


def gate4(recs, index, prev):
    census = B.RawCensus(intact=sorted(recs))
    result = B.validate(recs, census, index, prev, expected_year='תשפ"ז')
    name, ok, detail = next(c for c in result.checks if c[0].startswith("4."))
    return ok, detail


ALL = [f"9{i:04d}" for i in range(100)]


# ==========================================================================
# 1. ההבחנה עצמה
# ==========================================================================
def test_a_course_the_yedion_no_longer_lists_does_not_fail_the_gate():
    """גריעה אצל המכללה אינה נסיגה אצלנו."""
    kept = ALL[:-1]
    ok, detail = gate4(records(kept), catalog(kept), previous(ALL, 200))
    assert ok, f"גריעה הפילה את השער: {detail}"
    assert ALL[-1] in detail, "הגריעה חייבת להיאמר ביומן ולא להיעלם בשקט"


def test_a_course_still_listed_but_missing_does_fail_the_gate():
    """זו הנסיגה שהשער נועד לתפוס: הידיעון מפרסם, ואנחנו לא הפקנו."""
    kept = ALL[:-1]
    # האינדקס עדיין מכיל את כל 100 — כלומר הקוד החסר הוא כישלון שלנו.
    ok, detail = gate4(records(kept), catalog(ALL), previous(ALL, 200))
    assert not ok, "קורס שהידיעון עדיין מפרסם ונעלם — חייב לפסול"
    assert ALL[-1] in detail


def test_the_two_reasons_are_counted_separately():
    """קורס אחד מכל סוג: אחד פוסל, השני מדווח."""
    withdrawn, lost = ALL[-1], ALL[-2]
    kept = ALL[:-2]
    index = catalog([c for c in ALL if c != withdrawn])   # הידיעון גרע רק אחד
    ok, detail = gate4(records(kept), index, previous(ALL, 200))
    assert not ok, "הקוד שעדיין מפורסם חייב להפיל"
    assert lost in detail, "הקוד שנעלם למרות שהוא מפורסם חייב להופיע"
    assert withdrawn in detail, "גם הגריעה מדווחת"


def test_a_parser_regression_still_fails_loudly():
    """‏40 קורסים שהידיעון עדיין מפרסם ונעלמו — בדיוק מה שהשער קיים בשבילו."""
    kept = ALL[:-40]
    ok, detail = gate4(records(kept), catalog(ALL), previous(ALL, 200))
    assert not ok, f"נסיגה של 40 קורסים עברה: {detail}"


def test_a_wholesale_withdrawal_still_fails_on_meeting_retention():
    """גריעה המונית אינה חומקת: שימור המפגשים הוא הרשת השנייה.

    ‏אם הידיעון "גרע" 40 קורסים, הבדיקה הראשונה אמנם מרשה זאת — אבל
    המפגשים שנעלמו איתם מפילים את השער בכל זאת. שתי הבדיקות משלימות זו
    את זו, וזו הסיבה שהתיקון נגע רק באחת מהן.
    """
    kept = ALL[:-40]
    ok, detail = gate4(records(kept), catalog(kept), previous(ALL, 200))
    assert not ok, f"אובדן 40% מהמפגשים עבר: {detail}"
    assert "95%" in detail


# ==========================================================================
# 2. הריצה האמיתית, במספרים שלה
# ==========================================================================
def test_the_first_pipeline_run_would_now_pass():
    """‏572 -> 571 קורסים, שימור מפגשים 99.7%. ‏run 35262996905."""
    prev_codes = [f"9{i:04d}" for i in range(572)]
    gone = prev_codes[-1]
    kept = prev_codes[:-1]
    # ‏1187 -> 1184 מפגשים = 99.7%, הרבה מעל הרף של 95%.
    recs = records(kept, meetings_per_course=2)
    prev = previous(prev_codes, int(len(kept) * 2 / 0.997))
    ok, detail = gate4(recs, catalog(kept), prev)
    assert ok, f"התרחיש של הריצה הראשונה עדיין נופל: {detail}"
    assert gone in detail


def test_the_gate_still_reports_when_nothing_was_withdrawn():
    """ריצה שקטה: אין נסיגה, אין גריעה, והדיווח אינו ממציא אף אחת מהן."""
    ok, detail = gate4(records(ALL), catalog(ALL), previous(ALL, 200))
    assert ok
    assert "נגרעו" not in detail, f"דווחה גריעה שלא הייתה: {detail}"
