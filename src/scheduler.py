"""
מנוע בניית המערכת — SlotWise scheduling engine.

זהו הלב של המערכת. התפקיד שלו:
    1. לעבור על כל הצירופים האפשריים של קבוצות (backtracking עם גיזום מוקדם).
    2. לתת ניקוד לכל מערכת אפשרית לפי ההעדפות של הסטודנטית.
    3. להחזיר את ה-top_n הטובות ביותר, או — אם אין אף פתרון — להסביר *למה* בעברית.

מוסכמות (מ-models.py):
    יום  : 1=ראשון ... 6=שישי
    שעה  : דקות מחצות (08:30 -> 510)
    חפיפה: חצי-פתוח [start, end) — שיעור שנגמר ב-10:00 ואחד שמתחיל ב-10:00 *אינם* מתנגשים.

הערה חשובה על "קורסים צמודים" (tied courses):
    בסמסטר 5 של הנדסת תוכנה בבראודה, הקורסים 61756 + 61757 + 62027 הם חבילה אחת.
    אי אפשר לקחת אחד בלי השניים האחרים. solve() אוכף את זה לפני שהוא בכלל מתחיל לחפש.

הערה חשובה על חובת נוכחות (attendance) — SPEC_V2 §2:
    בבראודה יש רכיבים — בעיקר הרצאות, ובמיוחד בקורס חוזר — שאין בהם חובת נוכחות.
    סטודנט יכול לבחור *ביודעין* להירשם לשני רכיבים שחופפים בזמן וללכת רק לאחד,
    אם בזכות זה השבוע שלו נגמר מוקדם יותר. לכן חפיפה בזמן אינה עוד וטו מוחלט:

        חפיפה **קשיחה** (hard) — שני הצדדים דורשים נוכחות → נפסלת, כמו תמיד.
        חפיפה **רכה**   (soft) — לפחות צד אחד אינו דורש נוכחות → מותרת, אך
                                 נספרת, מקבלת קנס ניקוד, ו*מדווחת בקול*.

    ברירת המחדל לא השתנתה בכהוא זה: ``Preferences()`` בלי ``attendance`` ובלי
    ``allow_soft_conflicts`` מתנהגת בדיוק כמו קודם — כל חפיפה נפסלת. הסטודנט
    מוותר על נוכחות במפורש, לעולם לא בטעות.
"""

from __future__ import annotations

import json
import re
import sys
import warnings
from collections.abc import Iterator
import dataclasses
from dataclasses import dataclass, field, replace
from pathlib import Path

from models import (
    DAY_LETTERS_HE,
    DAY_NAMES_HE,
    KIND_COMBINED,
    KIND_LAB,
    KIND_LECTURE,
    KIND_ORDER,
    KIND_OTHER,
    KIND_PROJECT,
    KIND_TUTORIAL,
    Course,
    Group,
    Meeting,
    ScoredSchedule,
    Selection,
    fmt_time,
)

# ==========================================================================
# קבועים
# ==========================================================================

#: דקות ביממה — ברירת המחדל של prefs.latest.
MINUTES_IN_DAY: int = 24 * 60

#: יום שישי. forbid_friday חוסם את היום הזה לגמרי.
FRIDAY: int = 6

#: מפתח המשקל של חפיפה מכוונת (soft conflict).
WEIGHT_SOFT_CONFLICT: str = "soft_conflict"

#: "לסיים מוקדם" — הבקשה המפורשת של הסטודנט/ית.
WEIGHT_LATE_FINISH: str = "late_finish"

#: כמה משקל יש להעדפת המרצה **לפי סוג הרכיב**.
#: הרצאה שווה מלוא המשקל; תרגול/מעבדה שווים פחות — כי אפשר להתפשר על
#: המתרגל/ת אם זה מקצר את היום, אבל לא על מי שמעביר/ה את ההרצאה.
#: סוג שאינו ברשימה מקבל 1.0 (לא מנחשים כלפי מטה).
LECTURER_KIND_WEIGHT: dict[str, float] = {
    KIND_LECTURE: 1.0,
    KIND_COMBINED: 1.0,
    KIND_TUTORIAL: 0.4,
    KIND_LAB: 0.4,
    KIND_PROJECT: 0.4,
    KIND_OTHER: 0.6,
}

#: השעה שממנה ואילך יום נחשב "נגמר מאוחר". 14:00 — כל שעה אחריה היא שעה
#: שביקשו במפורש להימנע ממנה. שימו לב שזה **לא** span: יום 08:00-12:00 ויום
#: 16:00-20:00 זהים באורכם, ורק השני מחזיר הביתה בערב.
LATE_BASELINE_MIN: int = 14 * 60

#: משקולות ברירת המחדל — "מאוזן" (balanced), בדיוק כמו ב-data/profile.json.
#:
#: ``soft_conflict`` הוא קנס: 6.0 נקודות לכל חפיפה מכוונת. הוא לא נועד לחסום
#: אלא לתמחר — ויתור על הרצאה הוא מחיר אמיתי, ולכן המנוע ייקח חפיפה כזו רק
#: כשהיא באמת קונה שבוע קצר יותר (יום שלם שווה 8.0, שעת חור שווה 4.0).
#: הוא נכנס ל-breakdown *רק* כשיש חפיפה בפועל — ראי score().
#: חלון הצהריים של בראודה, בדקות מחצות: ‏12:20–12:50.
#:
#: לא הנחה — נמדד מתוך ``data/db/sections.json``: בכל טווח 12:00–13:00 יש
#: בדיוק שעת התחלה אחת (12:50) ובדיוק שעת סיום אחת (12:20). אף מפגש אינו
#: מתחיל או מסתיים בתוך החלון, באף אחד מששת הימים. זו גם אי-הרציפות
#: **היחידה** בלוח: כל שאר הגבולות רצופים — שיעור מסתיים ב-10:30 והבא
#: מתחיל ב-10:30.
#:
#: שני סייגים, במפורש:
#:   * ‏92 מפגשים מתוך 1143 (8%) עוברים דרך החלון כבלוק אחד ארוך
#:     ‏(11:30–13:50 וכדומה). החלון אינו חסום — פשוט אי אפשר להתחיל או
#:     לסיים בתוכו. לכן הזיכוי ניתן על חור בפועל ולא על השעה שבלוח.
#:   * במסד יש רק סמסטר א'. ‏44 קבוצות מסומנות ב', ולאף אחת אין מפגשים
#:     עם שעות. החלון **לא** אומת מול סמסטר ב' או הקיץ, ולכן יש בדיקה
#:     שמוודאת שהקבוע עדיין תואם לנתונים — כדי שההנחה תיפול ברעש ולא
#:     בשקט ביום שבו יגיעו נתונים אחרים.
#:
#: תופעת לוואי מכוונת, ששווה לדעת עליה מראש: החלון מקטין את הכדאיות של
#: חפיפה מכוונת. קודם, מערכת שקנתה חפיפה ‏(-6.0) חסכה גם 30 דקות חור סביב
#: הצהריים ויצאה מרוויחה; עכשיו החור הזה ממילא אינו נספר, החיסכון קטן,
#: והמערכת שאינה מוותרת על נוכחות מנצחת. נמדד על בחירת סמסטר 5: לפני —
#: המובילה הייתה עם חפיפה ‏(-73.50 מול -75.33); אחרי — בלי ‏(-71.33 מול
#: -71.50). זה מה שהחלון נועד לעשות: ויתור על נוכחות בהרצאה אינו מחיר
#: סביר עבור הימנעות מהפסקה שאי אפשר להימנע ממנה ממילא.
LUNCH_WINDOW: tuple[int, int] = (12 * 60 + 20, 12 * 60 + 50)

DEFAULT_WEIGHTS: dict[str, float] = {
    "lecturer": 10.0,
    "days": 8.0,
    "gaps": 4.0,
    "compactness": 1.0,
            # "לסיים מוקדם" — הבקשה המפורשת של הסטודנט/ית.
            WEIGHT_LATE_FINISH: 4.0,
    WEIGHT_SOFT_CONFLICT: 6.0,
}

#: ארבעת רכיבי הניקוד הקבועים, שתמיד מופיעים ב-``ScoredSchedule.breakdown``.
#: ‏``soft_conflict`` הוא רכיב חמישי **מותנה** — הוא מצטרף רק כשיש חפיפה
#: מכוונת בפועל. מי שמציג את הפירוק (render / web) חייב לסבול מפתח נוסף.
CORE_BREAKDOWN_KEYS: tuple[str, ...] = ("lecturer", "days", "gaps", "compactness")

# --------------------------------------------------------------------------
# חובת נוכחות (attendance)
# --------------------------------------------------------------------------
#: מקור ברירת המחדל של חובת הנוכחות ברכיב.
ATTENDANCE_SOURCE_YEDION = "yedion"  # הידיעון אמר את זה במפורש בהערת הקבוצה
ATTENDANCE_SOURCE_DEFAULT = "default"  # לא נאמר דבר — ברירת המחדל היא "חובה"

#: ניסוחים בידיעון שמשמעותם "יש חובת נוכחות".
#: 11069 (אנגלית טכנית) נושא בדיוק הערה כזו: "חובת הנוכחות בקורס היא מרגע
#: הרישום לקורס" — שימי לב ל-ה' הידיעה ב"הנוכחות", ולכן היא אופציונלית בתבנית.
ATTENDANCE_NOTE_PATTERNS: tuple[str, ...] = (
    r"חוב[הת]\s+ה?נוכחות",  # "חובת נוכחות" / "חובת הנוכחות" / "חובה נוכחות"
    r"נוכחות\s+ה?חובה",  # "נוכחות חובה" — אותו משפט, סדר הפוך
    r"חובה\s+להשתתף",  # "חובה להשתתף בכל המפגשים"
)

_ATTENDANCE_NOTE_RE = re.compile("|".join(ATTENDANCE_NOTE_PATTERNS))

#: מכסת הצמתים המינימלית של enumerate_selections (ברירת המחדל של הפרמטר limit).
DEFAULT_NODE_LIMIT: int = 200_000

#: תקרת המכסה ש-solve() מוכן להקצות לעצמו כשמרחב החיפוש גדול.
#: מעליה החיפוש עלול לקחת דקות, ולכן עדיף להיעצר ולהזהיר מאשר להיתקע.
MAX_SOLVE_NODES: int = 5_000_000

#: שמות האילוצים היחידניים (unary) — אילוץ שפוסל קבוצה בפני עצמה, בלי קשר לשאר.
CONSTRAINT_EARLIEST = "earliest"
CONSTRAINT_LATEST = "latest"
CONSTRAINT_BLOCKED = "blocked"
CONSTRAINT_FRIDAY = "friday"


# ==========================================================================
# חריגות (exceptions)
# ==========================================================================
class SearchExhausted(Exception):
    """
    נזרקת כאשר החיפוש עבר את מכסת הצמתים שהוקצתה לו (`limit`).

    זו לא שגיאה "אמיתית" — זו בלימת בטיחות שמונעת מהתוכנית להיתקע לנצח
    על מרחב חיפוש ענק. השדה .visited מחזיק את מספר הצמתים שנבדקו.
    """

    def __init__(self, visited: int) -> None:
        self.visited = int(visited)
        super().__init__(
            f"החיפוש עבר את מכסת הצמתים ({self.visited:,} צמתים חלקיים) "
            f"(search node limit exceeded)"
        )


class Infeasible(Exception):
    """
    נזרקת מ-solve() כשאין אף מערכת אפשרית.

    השדה .reasons הוא רשימת מחרוזות בעברית שמסבירות בדיוק מה חוסם.
    לעולם לא מחזירים [] במקום — עדיף הסבר מאשר שקט.
    """

    def __init__(self, reasons: list[str]) -> None:
        self.reasons: list[str] = list(reasons)
        body = "\n".join(f"  • {r}" for r in self.reasons) or "  • (לא נמצא הסבר ספציפי)"
        super().__init__("לא נמצאה מערכת אפשרית (no feasible schedule found):\n" + body)


class TiedCoursesError(ValueError):
    """
    נזרקת כשחבילת קורסים צמודים (קורסים תְּמוּדִים / korsim tzmudim) נשברה:
    קורס אחד מהחבילה נמצא ברשימה אבל שותפיו חסרים.
    """

    def __init__(self, course_code: str, missing: list[str], partners: list[str]) -> None:
        self.course_code = course_code
        self.missing = list(missing)
        self.partners = list(partners)
        super().__init__(
            f"קורסים צמודים: הקורס {course_code} חייב להילקח יחד עם "
            f"{', '.join(self.partners)}, אך הקורס/ים {', '.join(self.missing)} "
            f"אינם ברשימת הקורסים שהועברה. או שכולם נכנסים — או שאף אחד. "
            f"(tied courses must all be present or none)"
        )


# ==========================================================================
# Preferences — ההעדפות של הסטודנטית
# ==========================================================================
@dataclass
class Preferences:
    """
    כל מה שהסטודנטית "רוצה". שים לב להבחנה החשובה:

    אילוצים קשיחים (hard constraints) — פוסלים קבוצה לגמרי:
        earliest, latest, blocked_windows, forbid_friday
    העדפות רכות (soft preferences) — רק משפיעות על הניקוד:
        target_days, preferred_lecturers, weights
    ויתור מודע (deliberate trade-off) — הופך אילוץ קשיח לרך:
        attendance, allow_soft_conflicts
    """

    target_days: int = 4
    #: {קוד קורס: [שם מרצה מועדף ביותר, שני, שלישי, ...]}
    preferred_lecturers: dict[str, list[str]] = field(default_factory=dict)
    #: (יום, התחלה בדקות, סוף בדקות) — חלונות שבהם הסטודנטית לא זמינה
    blocked_windows: list[tuple[int, int, int]] = field(default_factory=list)
    #: אף שיעור לא יתחיל לפני השעה הזו (בדקות מחצות)
    earliest: int = 0
    #: אף שיעור לא יסתיים אחרי השעה הזו (בדקות מחצות)
    latest: int = MINUTES_IN_DAY
    #: ‏``soft_conflict`` נמצא כאן כדי שהמשקל יהיה *גלוי וניתן לכוונון* גם
    #: כשלא נגעו בו — אבל הוא מוכפל ב-0 בכל מערכת בלי חפיפה מכוונת, ולכן
    #: אינו משנה אף ניקוד קיים.
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "lecturer": 10.0,
            "days": 8.0,
            "gaps": 4.0,
            "compactness": 1.0,
            WEIGHT_SOFT_CONFLICT: 6.0,
        }
    )
    forbid_friday: bool = False

    #: ‏{קוד קורס: {סוג רכיב: האם נדרשת נוכחות}}. **מפתח חסר פירושו True.**
    #:
    #: ‏``{"61753": {"הרצאה": False}}`` = "בהרצאה של 61753 אין חובת נוכחות,
    #: ולכן מותר לי לשבץ אותה על גבי משהו אחר". כל רכיב שלא הוזכר כאן נשאר
    #: חובה — הסטודנט מוותר על נוכחות במפורש, לעולם לא בהיסח הדעת.
    #: אפשר לאתחל את המילון מ-``seed_attendance_from_notes(courses)`` (ראי בהמשך).
    attendance: dict[str, dict[str, bool]] = field(default_factory=dict)

    #: ‏False = ההתנהגות של היום, בדיוק: כל חפיפה בזמן נפסלת.
    #: ‏True  = חפיפה מותרת כשלפחות צד אחד אינו דורש נוכחות. היא עדיין נספרת,
    #: מקבלת קנס ניקוד, ומדווחת ב-``describe_soft_conflicts``.
    #: המתג הזה לבדו לא מספיק: בלי ``attendance`` שמסמן משהו כלא-חובה,
    #: כל הרכיבים עדיין חובה ולכן כל חפיפה עדיין קשיחה.
    #: ברירת המחדל היא **True** בכוונה, והיא בטוחה: ``attendance`` ריק פירושו
    #: "בכל הקורסים יש חובת נוכחות", ואז ``conflict_is_hard`` מחזיר True לכל
    #: חפיפה — בדיוק ההתנהגות המקורית. מה שקובע בפועל הוא סימון הנוכחות בלבד.
    #:
    #: קודם זה היה False, וזה יצר מלכודת: הסטודנט/ית סימנ/ה "אין חובת נוכחות
    #: בהרצאה של 61753", והמערכת המשיכה לחסום — כי מתג נפרד וכבוי ביטל את
    #: הסימון בשקט. שני פקדים לאותה החלטה אחת; נשאר רק אחד.
    allow_soft_conflicts: bool = True
    #: דריסה של ``LECTURER_KIND_WEIGHT``. ריק = ברירת המחדל.
    lecturer_kind_weight: dict[str, float] = field(default_factory=dict)



def day_end_times(sel: "models.Selection") -> dict[int, int]:
    """{יום: דקת הסיום של המפגש האחרון בו}."""
    out: dict[int, int] = {}
    for meeting in sel.all_meetings():
        if meeting.end > out.get(meeting.day, -1):
            out[meeting.day] = meeting.end
    return out


def late_finish_minutes(sel: "models.Selection") -> int:
    """סך הדקות שבהן ימי הלימוד נמשכים אחרי ``LATE_BASELINE_MIN``.

    זה **לא** אותו דבר כמו ``span_minutes``: יום 08:00-12:00 ויום 16:00-20:00
    זהים באורכם, אבל רק השני גורם לחזור הביתה בערב. הסטודנט/ית ביקש/ה
    במפורש ש"היום ייגמר מוקדם ככל האפשר", וזה המדד שמודד בדיוק את זה.
    """
    return sum(max(0, end - LATE_BASELINE_MIN) for end in day_end_times(sel).values())


def attendance_free_days(sel: "models.Selection", prefs: "Preferences") -> set[int]:
    """ימים שבהם **כל** המפגשים פטורים מחובת נוכחות.

    יום כזה אינו באמת יום לימודים: אפשר פשוט לא להגיע. ספירתו כיום קמפוס
    היא בדיוק מה שגרם למערכת לפתוח יום שלם עבור תרגול יחיד שממילא לא חובה.
    """
    by_day: dict[int, list] = {}
    for group in sel.groups:
        for meeting in group.meetings:
            by_day.setdefault(meeting.day, []).append(group)
    return {
        day
        for day, groups in by_day.items()
        if groups and not any(attendance_required(prefs, g) for g in groups)
    }


def _weight(prefs: Preferences, key: str) -> float:
    """משקל בודד, עם נפילה לברירת המחדל אם המפתח חסר במילון של המשתמשת."""
    try:
        return float(prefs.weights.get(key, DEFAULT_WEIGHTS[key]))
    except (AttributeError, TypeError, ValueError):
        # weights פגום או None — לא מפילים את המנוע בגלל זה.
        return DEFAULT_WEIGHTS[key]


# ==========================================================================
# חובת נוכחות — מי חייב להיות בכיתה, ומי לא (SPEC_V2 §2)
# ==========================================================================
def note_requires_attendance(note: str) -> bool:
    """האם הערת הידיעון אומרת במפורש שיש חובת נוכחות ברכיב הזה?

    זו קריאה ב*ניסוח של הידיעון עצמו*, לא ניחוש. הידיעון לא תמיד אומר,
    ולכן ``False`` כאן פירושו "הידיעון שתק" — ולא "אין חובת נוכחות".
    ברירת המחדל כשהידיעון שותק היא עדיין **חובה**.

    Examples:
        >>> note_requires_attendance("חובת הנוכחות בקורס היא מרגע הרישום לקורס")
        True
        >>> note_requires_attendance("קורס זה הינו קורס צמוד לקורסים: 61756")
        False
    """
    text = " ".join((note or "").split())
    if not text:
        return False
    return bool(_ATTENDANCE_NOTE_RE.search(text))


def attendance_required(prefs: Preferences, group: Group) -> bool:
    """האם הרכיב שהקבוצה הזו שייכת אליו דורש נוכחות?

    **מפתח חסר פירושו True.** זה הכלל היחיד כאן, והוא הכלל שמגן על הסטודנט:
    ‏``attendance`` ריק (ברירת המחדל) → הכול חובה → כל חפיפה קשיחה → בדיוק
    ההתנהגות שהייתה לפני SPEC_V2.

    ההחלטה נקראת מ-``prefs`` בלבד ולא מהערת הידיעון, כי ההערה כבר עשתה את
    שלה: היא זרעה את ברירת המחדל דרך ``seed_attendance_from_notes``. אחרי שהסטודנט
    בחר במפורש — הבחירה שלו היא הקובעת.
    """
    table = getattr(prefs, "attendance", None)
    if not isinstance(table, dict):
        return True
    per_course = table.get(group.course_code)
    if not isinstance(per_course, dict):
        return True
    value = per_course.get(group.kind)
    if value is None:
        return True  # לא נאמר דבר על הרכיב הזה — חובה.
    return bool(value)


@dataclass(frozen=True)
class AttendanceDefault:
    """ברירת המחדל של חובת נוכחות לרכיב אחד, ומאיפה היא הגיעה.

    ``source`` מאפשר לממשק לומר "כך כתוב בידיעון" במקום "כך הנחנו" —
    ההבדל הזה חשוב לסטודנט שמחליט אם לוותר על נוכחות.
    """

    course_code: str
    kind: str
    required: bool
    source: str  # ATTENDANCE_SOURCE_YEDION / ATTENDANCE_SOURCE_DEFAULT
    evidence: str = ""  # הערת הידיעון שממנה זה נקרא, אם הייתה

    @property
    def from_yedion(self) -> bool:
        return self.source == ATTENDANCE_SOURCE_YEDION

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.course_code,
            "kind": self.kind,
            "required": self.required,
            "source": self.source,
            "from_yedion": self.from_yedion,
            "evidence": self.evidence,
        }


def seed_attendance_defaults(
    courses: "list[Course] | tuple[Course, ...]",
) -> dict[str, dict[str, AttendanceDefault]]:
    """זורעת ברירות מחדל של חובת נוכחות מהניסוח של הידיעון עצמו.

    לכל (קורס, סוג רכיב) מוחזר ``AttendanceDefault``:
      * ‏``required=True`` תמיד — הסטודנט מוותר על נוכחות במפורש, לא בטעות;
      * ‏``source="yedion"`` כשהערת אחת הקבוצות ברכיב אומרת זאת במפורש
        (למשל 11069 שו"ת, שהערתו "חובת הנוכחות בקורס היא מרגע הרישום לקורס");
      * ‏``source="default"`` כשהידיעון שתק.

    Returns:
        ‏{קוד קורס: {סוג רכיב: AttendanceDefault}}.
    """
    seeded: dict[str, dict[str, AttendanceDefault]] = {}
    for course in courses or []:
        for group in course.groups:
            slot = seeded.setdefault(course.code, {})
            existing = slot.get(group.kind)
            if existing is not None and existing.from_yedion:
                continue  # כבר מצאנו ראיה מפורשת לרכיב הזה
            if note_requires_attendance(group.note):
                slot[group.kind] = AttendanceDefault(
                    course_code=course.code,
                    kind=group.kind,
                    required=True,
                    source=ATTENDANCE_SOURCE_YEDION,
                    evidence=" ".join((group.note or "").split()),
                )
            elif existing is None:
                slot[group.kind] = AttendanceDefault(
                    course_code=course.code,
                    kind=group.kind,
                    required=True,
                    source=ATTENDANCE_SOURCE_DEFAULT,
                )
    return seeded


def seed_attendance_from_notes(
    courses: "list[Course] | tuple[Course, ...]",
    overrides: dict[str, dict[str, bool]] | None = None,
) -> dict[str, dict[str, bool]]:
    """מילון מוכן להצבה ב-``Preferences.attendance``.

    מתחילה מברירות המחדל של הידיעון (הכול חובה) ומחילה מעליהן את הוויתורים
    המפורשים של הסטודנט. רכיב שאינו קיים בנתונים *כן* נכנס אם הסטודנט ביקש —
    כדי שוויתור לא ייעלם בשקט רק בגלל שהקורס טרם נשאב.

    Args:
        courses:   הקורסים שמהם נזרעות ברירות המחדל.
        overrides: ‏{קוד: {סוג: bool}} — הבחירות המפורשות של הסטודנט.
    """
    table: dict[str, dict[str, bool]] = {
        code: {kind: default.required for kind, default in kinds.items()}
        for code, kinds in seed_attendance_defaults(courses).items()
    }
    for code, kinds in (overrides or {}).items():
        if not isinstance(kinds, dict):
            continue
        slot = table.setdefault(str(code), {})
        for kind, required in kinds.items():
            slot[str(kind)] = bool(required)
    return table


#: שם קצר לאותה פונקציה, לקוראים שרוצים "תני לי את הטבלה" ולא "זרעי".
attendance_table = seed_attendance_from_notes


def conflict_is_hard(a: Group, b: Group, prefs: Preferences) -> bool:
    """האם החפיפה בין שתי הקבוצות היא חפיפה **קשיחה** — כזו שפוסלת?

    שלושת המקרים, בסדר הזה בדיוק (SPEC_V2 §2):
        1. אין חפיפה בכלל                       → False (אין מה לפסול).
        2. ‏``allow_soft_conflicts=False``       → True  (ההתנהגות של היום).
        3. אחרת                                  → קשיחה רק אם *שני* הצדדים
           דורשים נוכחות. די בצד אחד שאינו דורש כדי שהחפיפה תהיה רכה.
    """
    if not a.conflicts_with(b):
        return False
    if not getattr(prefs, "allow_soft_conflicts", False):
        return True
    return attendance_required(prefs, a) and attendance_required(prefs, b)


# ==========================================================================
# עזרי פנים — בדיקת אילוצים יחידניים
# ==========================================================================
def _kind_rank(kind: str) -> int:
    """מיקום סוג הרכיב בסדר התצוגה הקבוע — לצורך מיון דטרמיניסטי."""
    try:
        return KIND_ORDER.index(kind)
    except ValueError:
        return len(KIND_ORDER)


def _group_sort_key(group: Group) -> tuple[int, int, str]:
    """
    מיון קבוצות בתוך אותו סלוט. מספרי קבוצה ("11", "21") ממוינים כמספרים,
    ושאר המזהים לקסיקוגרפית — כדי שהתוצאה תהיה זהה בכל הרצה.
    """
    gid = (group.group_id or "").strip()
    if gid.isdigit():
        return (0, int(gid), gid)
    return (1, 0, gid)


def _window_overlaps(meeting: Meeting, day: int, start: int, end: int) -> bool:
    """האם המפגש חופף לחלון (יום, התחלה, סוף) — שוב, חפיפה חצי-פתוחה."""
    if meeting.day != day:
        return False
    return meeting.start < end and start < meeting.end


def _unary_violations(group: Group, prefs: Preferences) -> list[tuple[str, str]]:
    """
    בודקת קבוצה אחת מול האילוצים ה*יחידניים* — אלה שלא תלויים בשום קבוצה אחרת.

    מחזירה רשימת זוגות (סוג_האילוץ, הסבר_בעברית). רשימה ריקה = הקבוצה עוברת.

    Technical note: this is what lets us pre-filter candidates before the search
    even starts, which is exactly equivalent to rejecting them inside the loop —
    only much faster, because a rejected group is never re-tested at every depth.
    """
    problems: list[tuple[str, str]] = []
    for m in group.meetings:
        if prefs.forbid_friday and m.day == FRIDAY:
            problems.append(
                (CONSTRAINT_FRIDAY, f"מתקיים ביום שישי {fmt_time(m.start)}-{fmt_time(m.end)}, ולימודי שישי נאסרו")
            )
        if m.start < prefs.earliest:
            problems.append(
                (
                    CONSTRAINT_EARLIEST,
                    f"מתחיל ב-{fmt_time(m.start)}, לפני השעה המוקדמת ביותר שאושרה {fmt_time(prefs.earliest)}",
                )
            )
        if m.end > prefs.latest:
            problems.append(
                (
                    CONSTRAINT_LATEST,
                    f"מסתיים ב-{fmt_time(m.end)}, אחרי השעה המאוחרת ביותר שאושרה {fmt_time(prefs.latest)}",
                )
            )
        for day, w_start, w_end in prefs.blocked_windows:
            if _window_overlaps(m, day, w_start, w_end):
                problems.append(
                    (
                        CONSTRAINT_BLOCKED,
                        f"חופף לחלון חסום ביום {DAY_NAMES_HE.get(day, day)} "
                        f"{fmt_time(w_start)}-{fmt_time(w_end)}",
                    )
                )
    return problems


def _group_allowed(group: Group, prefs: Preferences) -> bool:
    """True אם הקבוצה שורדת את כל האילוצים היחידניים."""
    return not _unary_violations(group, prefs)


def _filter_groups(
    groups: list[Group], prefs: Preferences
) -> tuple[list[Group], list[tuple[Group, list[tuple[str, str]]]]]:
    """
    מחלקת רשימת קבוצות ל: (ששרדו, [(שנפסלה, סיבות), ...]).
    משמשת גם את החיפוש (לוקח רק את מי ששרד) וגם את האבחון (מסביר את מי שנפסל).
    """
    survivors: list[Group] = []
    eliminated: list[tuple[Group, list[tuple[str, str]]]] = []
    for g in sorted(groups, key=_group_sort_key):
        problems = _unary_violations(g, prefs)
        if problems:
            eliminated.append((g, problems))
        else:
            survivors.append(g)
    return survivors, eliminated


#: מיפוי (קוד קורס, מזהה קבוצה) -> סוג הרכיב. משמש את כלל ה-linked_to.
_KindIndex = dict[tuple[str, str], str]


def _kind_index(courses: "list[Course] | tuple[Course, ...]") -> _KindIndex:
    """בונה מיפוי (course_code, group_id) -> kind עבור כל הקבוצות שהתקבלו."""
    index: _KindIndex = {}
    for course in courses:
        for g in course.groups:
            index[(g.course_code, g.group_id)] = g.kind
    return index


def _link_allows(owner: Group, other: Group, kind_of: _KindIndex | None) -> bool:
    """
    האם ה-linked_to של `owner` מרשה לצרף דווקא את `other` (מאותו קורס)?

    המשמעות של linked_to לפי ה-SPEC היא *דרישה*: "חייבים לקחת גם את הקבוצות
    האלה" — ולא רשימת-היתר גורפת. לכן היא מגבילה רק את הרכיבים (kinds)
    שהיא באמת מזכירה:
        הרצאה 31 עם linked_to=["33"] כשהקבוצה 33 היא תרגול —
        מחייבת שהתרגול הנבחר יהיה 33, אך אינה אומרת דבר על הפרויקט.
    מכיוון שכל kind בקורס הוא סלוט נפרד שממולא בדיוק פעם אחת, הכלל הזוגי
    הזה מבטיח שכל מזהה שברשימה אכן ייכנס לבחירה הסופית.

    אם סוג הקבוצה המבוקשת אינו ידוע (מזהה שלא קיים בנתונים) — לא פוסלים,
    כדי שקישור שבור מהפרסר לא ימחק בשקט מערכות תקינות.
    """
    if not owner.linked_to:
        return True
    if other.group_id in owner.linked_to:
        return True  # זו בדיוק אחת הקבוצות הנדרשות
    if not kind_of:
        return True  # אין לנו מפת סוגים — לא מגבילים באופן שרירותי
    for gid in owner.linked_to:
        if kind_of.get((owner.course_code, gid)) == other.kind:
            # הרשימה דורשת קבוצה *אחרת* מאותו סוג בדיוק — זו כן פסילה.
            return False
    return True


def _linked_ok(a: Group, b: Group, kind_of: _KindIndex | None = None) -> bool:
    """
    כלל ה-linked_to, סימטרי ובשני הכיוונים.

    הכלל חל רק בתוך אותו קורס, ורק על סוגי הרכיבים שהרשימה מזכירה במפורש
    (ראי _link_allows). הבדיקה נעשית לשני הכיוונים — גם אם רק אחת מהן הצהירה.
    """
    if a.course_code != b.course_code:
        return True  # הכלל חל רק בתוך אותו קורס
    if not _link_allows(a, b, kind_of):
        return False
    if not _link_allows(b, a, kind_of):
        return False
    return True


def _pair_ok(
    a: Group, b: Group, kind_of: _KindIndex | None = None, prefs: Preferences | None = None
) -> bool:
    """שתי קבוצות יכולות לחיות יחד: לא מתנגשות בזמן ולא שוברות linked_to.

    ‏``prefs=None`` (ברירת המחדל) = הכלל המחמיר הישן: כל חפיפה פוסלת.
    עם ``prefs`` הפסילה עוברת דרך ``conflict_is_hard``, כלומר חפיפה רכה
    (רכיב בלי חובת נוכחות) *אינה* פוסלת. שימי לב: כש-
    ‏``allow_soft_conflicts=False`` שני המסלולים זהים בתוצאה, כי אז
    ‏``conflict_is_hard`` מחזיר בדיוק ``a.conflicts_with(b)``.
    """
    if not _linked_ok(a, b, kind_of):
        return False
    if prefs is None:
        return not a.conflicts_with(b)
    return not conflict_is_hard(a, b, prefs)


def _first_overlap(a: Group, b: Group) -> tuple[int, int, int] | None:
    """
    מחזירה (יום, תחילת החפיפה, סוף החפיפה) של זוג המפגשים החופפים הראשון,
    או None אם אין חפיפה. משמש להסבר קונקרטי באבחון.
    """
    for ma in a.meetings:
        for mb in b.meetings:
            if ma.overlaps(mb):
                return (ma.day, max(ma.start, mb.start), min(ma.end, mb.end))
    return None


def _overlap_windows(a: Group, b: Group) -> list[tuple[int, int, int, Meeting, Meeting]]:
    """כל חלונות החפיפה בין שתי קבוצות, ממוינים לפי יום ושעה.

    לכל חלון: ``(יום, תחילת החפיפה, סוף החפיפה, המפגש של a, המפגש של b)``.
    ‏``_first_overlap`` מספיק לאבחון; כאן צריך את *הכול*, כי דיווח על חפיפה
    מכוונת חייב להראות לסטודנט כל דקה שהוא מוותר עליה.
    """
    windows: list[tuple[int, int, int, Meeting, Meeting]] = []
    for ma in a.meetings:
        for mb in b.meetings:
            if ma.overlaps(mb):
                windows.append(
                    (ma.day, max(ma.start, mb.start), min(ma.end, mb.end), ma, mb)
                )
    windows.sort(key=lambda w: (w[0], w[1], w[2]))
    return windows


def _fmt_overlap(day: int, start: int, end: int) -> str:
    """'יום שלישי 10:00-12:00'."""
    return f"יום {DAY_NAMES_HE.get(day, day)} {fmt_time(start)}-{fmt_time(end)}"


def _norm_name(name: str) -> str:
    """נרמול שם מרצה להשוואה: רווחים מיותרים החוצה, אותיות אחידות."""
    return " ".join((name or "").split()).casefold()


# ==========================================================================
# הסלוטים — (קורס, סוג רכיב) ומועמדיו
# ==========================================================================
@dataclass
class _Slot:
    """סלוט אחד בחיפוש: 'בקורס 61756 צריך לבחור בדיוק הרצאה אחת'."""

    course: Course
    kind: str
    candidates: list[Group]


def _build_slots(courses: list[Course], prefs: Preferences) -> list[_Slot]:
    """
    בונה את רשימת הסלוטים ומסדרת אותה MOST-CONSTRAINED-FIRST.

    למה הסדר הזה? כי אם לסלוט יש רק שתי אפשרויות ולאחר יש עשרים, כדאי לבחור
    קודם את הצר — כך ענפים כושלים נחתכים כמעט מיד במקום אחרי עשרים ניסיונות.
    זהו היוריסטיקת MRV (Minimum Remaining Values) הקלאסית.
    """
    slots: list[_Slot] = []
    for course in courses:
        kinds = course.kinds()
        if not kinds:
            # קורס בלי אף קבוצה במאגר. חייב להיות סלוט *מת* (בלי מועמדים)
            # ולא "בלי סלוט בכלל" — אחרת החיפוש היה מדלג עליו בשקט ומחזיר
            # מערכת שחסר בה קורס שלם. עכשיו החיפוש נכשל, ו-solve() מפנה
            # ל-diagnose_infeasibility שמסביר "אין אף קבוצה במאגר".
            slots.append(_Slot(course=course, kind="", candidates=[]))
            continue
        for kind in kinds:
            survivors, _ = _filter_groups(course.groups_of(kind), prefs)
            slots.append(_Slot(course=course, kind=kind, candidates=survivors))

    # מיון: הכי מעט מועמדים קודם. שני שדות נוספים רק כדי שהסדר יהיה יציב.
    slots.sort(key=lambda s: (len(s.candidates), s.course.code, _kind_rank(s.kind)))
    return slots


def _search_space(slots: list[_Slot], cap: int = MAX_SOLVE_NODES) -> int:
    """מכפלת מספרי המועמדים — גודל מרחב החיפוש הגולמי, חסום ב-cap."""
    space = 1
    for s in slots:
        space *= max(1, len(s.candidates))
        if space >= cap:
            return cap
    return space


def _node_budget(courses: list[Course], prefs: Preferences) -> int:
    """
    מכסת צמתים שמתאימה למרחב החיפוש *האמיתי* של הקלט הזה.

    למה בכלל: ברירת המחדל הקבועה של 200,000 צמתים נגמרת כבר בקלט ריאלי
    (6 קורסים, 11 סלוטים, 4 קבוצות לרכיב). כשהיא נגמרת, ה-DFS מחזיר את
    מה שהספיק לראות — וזה עלול להיות גרוע מהפתרון האמיתי, בלי שאיש ידע.
    לכן המכסה גדלה עם המרחב: מכפלת המועמדים כפול מספר הסלוטים (חסם עליון
    גס למספר הצמתים בעץ), בין DEFAULT_NODE_LIMIT ל-MAX_SOLVE_NODES.
    """
    slots = _build_slots(courses, prefs)
    space = _search_space(slots)
    tree_bound = space * max(1, len(slots))
    return max(DEFAULT_NODE_LIMIT, min(MAX_SOLVE_NODES, tree_bound))


# ==========================================================================
# 1. enumerate_selections — החיפוש עצמו
# ==========================================================================
def enumerate_selections(
    courses: list[Course], prefs: Preferences, limit: int = DEFAULT_NODE_LIMIT
) -> Iterator[Selection]:
    """
    מייצרת (yield) כל בחירה שלמה ותקינה: קבוצה אחת לכל (קורס, סוג רכיב).

    האלגוריתם: backtracking על רשימת הסלוטים, כשהסלוטים ממוינים
    most-constrained-first. לכל סלוט מנסים כל קבוצה מועמדת, ופוסלים מיד אם:
      - החפיפה שלה עם קבוצה שכבר נבחרה היא חפיפה *קשיחה* (conflict_is_hard)
      - היא שוברת linked_to מול קבוצה שכבר נבחרה מאותו קורס (בשני הכיוונים)
    האילוצים היחידניים (earliest / latest / blocked_windows / forbid_friday)
    כבר סוננו ב-_build_slots — קבוצה שנפסלת מהם לא מגיעה בכלל לרשימת המועמדים.

    חפיפה קשיחה מול רכה (SPEC_V2 §2): כברירת מחדל
    ‏``prefs.allow_soft_conflicts=False``, ואז ``conflict_is_hard`` שקול מילה
    במילה ל-``Group.conflicts_with`` — כל חפיפה פוסלת, בדיוק כמו קודם.
    רק כשהסטודנט מדליק את המתג *וגם* מסמן רכיב כלא-מחייב-נוכחות,
    בחירות עם חפיפה מכוונת מתחילות לצאת מכאן. הן חוקיות, אך אינן
    ‏``Selection.is_feasible()`` — זו בדיוק הנקודה, ולכן הניקוד מקנס אותן
    ו-``describe_soft_conflicts`` מדווח עליהן.

    Args:
        courses: הקורסים לשיבוץ. כל אחד תורם סלוט אחד לכל סוג רכיב שיש בו.
        prefs:   ההעדפות; רק האילוצים הקשיחים (וכללי הנוכחות) משפיעים כאן.
        limit:   מכסת צמתים חלקיים. חריגה ממנה זורקת SearchExhausted.

    Yields:
        Selection — אובייקט חדש בכל פעם (העותק מנותק מהמצב הפנימי של החיפוש).

    Raises:
        SearchExhausted: אם נבדקו יותר מ-`limit` צמתים חלקיים.
    """
    slots = _build_slots(courses, prefs)
    n_slots = len(slots)
    kind_of = _kind_index(courses)  # (קורס, קבוצה) -> סוג, עבור כלל linked_to

    chosen: list[Group] = []  # המצב החלקי הנוכחי
    visited = 0  # מונה צמתים — כל ניסיון השמה הוא צומת

    def backtrack(depth: int) -> Iterator[Selection]:
        nonlocal visited

        if depth == n_slots:
            # הגענו לעלה: כל הסלוטים מולאו. זו מערכת שלמה ותקינה.
            yield Selection(list(chosen))
            return

        slot = slots[depth]
        for candidate in slot.candidates:
            visited += 1
            if visited > limit:
                raise SearchExhausted(visited)

            # גיזום: האם המועמד סובל את כל מי שכבר בפנים?
            if any(not _pair_ok(already, candidate, kind_of, prefs) for already in chosen):
                continue

            chosen.append(candidate)
            yield from backtrack(depth + 1)
            chosen.pop()

    yield from backtrack(0)


# ==========================================================================
# 1ב. חפיפות מכוונות — מה נבחר ביודעין, ואיך אומרים את זה בקול
# ==========================================================================
#: התחילית של דיווח חפיפה מכוונת. שורות ההמשך מיושרות מתחתיה.
_SOFT_PREFIX = "חפיפה מכוונת: "
_SOFT_INDENT = " " * len(_SOFT_PREFIX)


def _component_label(group: Group) -> str:
    """'61753 הרצאה' — הרכיב, בלי מספר הקבוצה."""
    return f"{group.course_code} {group.kind}"


def _day_time(day: int, start: int, end: int) -> str:
    """'יום ד 08:30-10:30'."""
    return f"יום {DAY_LETTERS_HE.get(day, day)} {fmt_time(start)}-{fmt_time(end)}"


def _side_label(group: Group, meeting: Meeting) -> str:
    """'61753 הרצאה קב' 271060330 (יום ד 08:30-10:30)' — צד אחד של החפיפה."""
    when = _day_time(meeting.day, meeting.start, meeting.end)
    return f"{_component_label(group)} קב' {group.group_id} ({when})"


@dataclass(frozen=True)
class SoftConflict:
    """חפיפה אחת שאושרה ביודעין, על כל פרטיה.

    זהו הפירוט המובנה שמאחורי המשפט העברי — כדי שה-API והממשק לא יצטרכו
    לנתח מחרוזות כדי לדעת מה חופף למה.
    """

    a: Group
    b: Group
    #: כל חלונות החפיפה: ‏(יום, התחלה, סוף) בדקות מחצות.
    windows: tuple[tuple[int, int, int], ...]
    #: סך דקות החפיפה — כמה זמן לימוד בפועל נזנח.
    minutes: int
    #: הרכיבים שהונח לגביהם שאין חובת נוכחות ('61753 הרצאה'), אחד או שניים.
    optional_components: tuple[str, ...]
    #: המשפט בעברית, מוכן להצגה. ראי describe_soft_conflicts.
    text: str

    @property
    def day(self) -> int:
        """היום של חלון החפיפה הראשון."""
        return self.windows[0][0] if self.windows else 0

    def as_dict(self) -> dict[str, object]:
        return {
            "a": {
                "code": self.a.course_code,
                "kind": self.a.kind,
                "group_id": self.a.group_id,
            },
            "b": {
                "code": self.b.course_code,
                "kind": self.b.kind,
                "group_id": self.b.group_id,
            },
            "windows": [
                {"day": d, "start": s, "end": e} for d, s, e in self.windows
            ],
            "minutes": self.minutes,
            "optional_components": list(self.optional_components),
            "text": self.text,
        }


def soft_conflicts_in(sel: Selection, prefs: Preferences) -> list[SoftConflict]:
    """כל החפיפות ה*רכות* בבחירה — מפורטות, לא רק נספרות.

    חפיפה רכה קיימת רק כשהסטודנט הדליק את ``allow_soft_conflicts`` *וגם*
    סימן לפחות אחד הצדדים כרכיב בלי חובת נוכחות. כש-``allow_soft_conflicts``
    כבוי, כל חפיפה היא לפי הגדרה קשיחה, ולכן הרשימה ריקה תמיד — וזו הסיבה
    שהניקוד של ברירת המחדל לא זז אף לא בנקודה אחת.

    חפיפה *קשיחה* שנמצאה בבחירה (מצב שהמנוע לעולם לא מייצר, אבל בחירה
    שנבנתה ביד כן יכולה) אינה מוחזרת כאן — היא אינה "מכוונת", היא פשוט
    פסולה. ``Selection.overlapping_pairs()`` מראה את הכול.

    Returns:
        רשימה, אחת לכל *זוג קבוצות* חופף (לא לכל מפגש), בסדר יציב.
    """
    if not getattr(prefs, "allow_soft_conflicts", False):
        return []

    found: list[SoftConflict] = []
    for a, b in sel.overlapping_pairs():
        if conflict_is_hard(a, b, prefs):
            continue

        raw = _overlap_windows(a, b)
        if not raw:
            continue  # לא אמור לקרות — overlapping_pairs כבר ווידא חפיפה
        windows = tuple((day, start, end) for day, start, end, _ma, _mb in raw)
        minutes = sum(max(0, end - start) for _day, start, end in windows)

        optional = tuple(
            _component_label(g) for g in (a, b) if not attendance_required(prefs, g)
        )
        if len(optional) == 2:
            assumption = (
                f"נבחר בהנחה שאין חובת נוכחות ב-{optional[0]} ואף לא ב-{optional[1]}"
            )
        elif optional:
            assumption = f"נבחר בהנחה שאין חובת נוכחות ב-{optional[0]}"
        else:
            # בלתי אפשרי לפי conflict_is_hard (חפיפה רכה מחייבת צד אחד פטור),
            # אבל דוח שחייב לא לשתוק לעולם — לא ייפול על IndexError.
            assumption = "החפיפה אושרה, אך לא ברור איזה רכיב פטור מנוכחות"

        overlap_text = ", ".join(_day_time(d, s, e) for d, s, e in windows)
        meeting_a, meeting_b = raw[0][3], raw[0][4]
        text = (
            f"{_SOFT_PREFIX}{_side_label(a, meeting_a)}\n"
            f"{_SOFT_INDENT}מול {_side_label(b, meeting_b)}\n"
            f"{_SOFT_INDENT}— חופפים ב{overlap_text} ({minutes} דקות); {assumption}."
        )
        found.append(
            SoftConflict(
                a=a,
                b=b,
                windows=windows,
                minutes=minutes,
                optional_components=optional,
                text=text,
            )
        )

    found.sort(key=lambda c: (c.windows[0], c.a.course_code, c.a.kind, c.b.course_code, c.b.kind))
    return found


def describe_soft_conflicts(sel: Selection, prefs: Preferences) -> list[str]:
    """דוח עברי על כל חפיפה מכוונת בבחירה. רשימה ריקה = אין חפיפות.

    כל פריט הוא בלוק של שלוש שורות שמזהה את שני הצדדים, את היום ואת שעות
    החפיפה, ואת הרכיב שלגביו הונח שאין בו חובת נוכחות::

        חפיפה מכוונת: 61753 הרצאה קב' 271060330 (יום ד 08:30-10:30)
                      מול 61756 תרגול קב' 271060310/3 (יום ד 08:30-11:30)
                      — חופפים ביום ד 08:30-10:30 (120 דקות); נבחר בהנחה
                        שאין חובת נוכחות ב-61753 הרצאה.

    זה לא קישוט. הסטודנט מחליף נוכחות בזמן, והוא חייב לראות בדיוק במה הוא
    מחליף — חפיפה מכוונת לעולם לא עוברת בשקט.
    """
    return [conflict.text for conflict in soft_conflicts_in(sel, prefs)]


def soft_conflicts_of(sched: ScoredSchedule) -> int:
    """מספר החפיפות המכוונות במערכת מנוקדת, גם אם הופקה בגרסה ישנה."""
    try:
        return int(getattr(sched, "soft_conflicts", 0) or 0)
    except (TypeError, ValueError):
        return 0


def soft_conflict_minutes_of(sched: ScoredSchedule) -> int:
    """סך דקות החפיפה המכוונת במערכת מנוקדת, גם אם הופקה בגרסה ישנה."""
    try:
        return int(getattr(sched, "soft_conflict_minutes", 0) or 0)
    except (TypeError, ValueError):
        return 0


# ==========================================================================
# 2. score — ניקוד מערכת בודדת
# ==========================================================================
def _kind_weight(prefs: "Preferences", kind: str) -> float:
    """משקל העדפת המרצה לסוג רכיב. הרצאה = מלא, תרגול = חלקי."""
    override = getattr(prefs, "lecturer_kind_weight", None) or {}
    if kind in override:
        try:
            return float(override[kind])
        except (TypeError, ValueError):
            pass
    return LECTURER_KIND_WEIGHT.get(kind, 1.0)


def _ranking_for(ranking: Any, kind: str | None = None) -> list:
    """מקבל רשימה שטוחה **או** מילון לפי סוג רכיב.

    ``{"61832": ["ד\"ר X"]}``                       — כמו קודם, לכל הרכיבים
    ``{"61832": {"הרצאה": ["X"], "תרגול": ["Y"]}}``  — העדפה נפרדת לכל רכיב
    """
    if isinstance(ranking, dict):
        if kind is None:
            merged: list = []
            for value in ranking.values():
                for name in value or []:
                    if name not in merged:
                        merged.append(name)
            return merged
        return list(ranking.get(kind) or [])
    return list(ranking or [])


def _lecturer_component(
    sel: Selection, prefs: Preferences
) -> tuple[float, int, int]:
    """
    רכיב המרצים. מחזירה (L, פגיעות_במקום_ראשון, מספר_הקורסים_המדורגים).

    כלל הניקוד: לכל קורס שיש לו דירוג מרצים, מסתכלים על הקבוצות שנבחרו בו
    ולוקחים את הדירוג ה*טוב ביותר* שהושג. דירוג 0 (המרצה המועדף) שווה 1.0,
    דירוג i שווה 1/(i+1): 1.0, 0.5, 0.333... מרצה שלא ברשימה — 0.0.
    """
    present_codes = sel.course_codes()

    total = 0.0
    hits = 0
    ranked_courses = 0

    for code, ranking in (prefs.preferred_lecturers or {}).items():
        if not _ranking_for(ranking):
            continue  # רשימה ריקה = "אין לי העדפה" — לא נספר כקורס מדורג
        if code not in present_codes:
            continue  # דירוג לקורס שלא במערכת הזו — לא רלוונטי ולא מעוות את היחס

        ranked_courses += 1

        # מיפוי שם מרצה מנורמל -> הדירוג הטוב ביותר שלו ברשימה
        rank_of: dict[str, int] = {}
        for i, name in enumerate(_ranking_for(ranking)):
            key = _norm_name(name)
            if key and key not in rank_of:
                rank_of[key] = i

        # הדירוג הטוב ביותר **לכל סוג רכיב בנפרד**, כדי שאפשר יהיה לשקלל
        # הרצאה ותרגול אחרת. קודם נלקח המקסימום על כל הקורס, וכך העדפה
        # למרצה ההרצאה והעדפה למתרגל/ת נשקלו זהה — בדיוק מה שביקשו להפריד.
        best_by_kind: dict[str, int] = {}
        for g in sel.groups:
            if g.course_code != code:
                continue
            r = rank_of.get(_norm_name(g.lecturer))
            if r is None:
                continue
            cur = best_by_kind.get(g.kind)
            if cur is None or r < cur:
                best_by_kind[g.kind] = r

        if best_by_kind:
            best_rank = min(best_by_kind.values())
            # הציון הוא הטוב ביותר מבין הרכיבים, אחרי שקלול לפי סוג:
            # הרצאה עם המרצה המועדף/ת שווה יותר מתרגול איתו/ה.
            total += max(
                (1.0 / (rank + 1)) * _kind_weight(prefs, kind)
                for kind, rank in best_by_kind.items()
            )
            if best_rank == 0:
                hits += 1
        # אחרת: 0.0 — אף אחת מהקבוצות שנבחרו אינה של מרצה מהרשימה.

    return total, hits, ranked_courses


def score(sel: Selection, prefs: Preferences) -> ScoredSchedule:
    """
    נותנת ניקוד למערכת אחת. ניקוד גבוה = מערכת טובה יותר.

    הנוסחה (בדיוק כמו ב-SPEC.md, בתוספת הרכיב החמישי של SPEC_V2 §2):
        score = w_lecturer * L  -  w_days * D  -  w_gaps * (G/60)
                                -  w_compactness * (S/60)  -  w_soft_conflict * C

    כאשר:
        L = סכום ציוני המרצים (1.0 למרצה המועדף, 1/(i+1) לדירוג i, 0 ללא-מדורג)
        D = max(0, מספר ימי הלימוד - target_days)      ← קנס על יום עודף
        G = דקות ה"חורים" שנספרות לחובה — בלי חלון הצהריים הקבוע
            ‏(LUNCH_WINDOW)                             ← billable_gap_minutes()
            ‏ScoredSchedule.gap_minutes נשאר המספר המלא, לתצוגה ול-API.
        S = סך "אורך היום" (מהשיעור הראשון לאחרון)     ← models.Selection.span_minutes()
        C = מספר החפיפות המכוונות (זוגות קבוצות)       ← soft_conflicts_in()

    G ו-S מחולקים ב-60 כדי שהמשקולות ידברו בשעות, לא בדקות.

    על הרכיב החמישי:
        C הוא 0 בכל מצב שאינו ``allow_soft_conflicts=True`` — כלומר בכל
        השימושים הקיימים. לכן ``breakdown`` ממשיך להכיל **בדיוק** את ארבעת
        המפתחות הוותיקים, וה-``soft_conflict`` מצטרף אליהם רק כשהוא באמת
        פועל. זה לא קישוט: ``breakdown`` הוא חוזה שמוצג לסטודנט, ואסור
        שיצוץ בו רכיב "0.00" על ויתור שמעולם לא נעשה.
    """
    w_lect = _weight(prefs, "lecturer")
    w_days = _weight(prefs, "days")
    w_gaps = _weight(prefs, "gaps")
    w_comp = _weight(prefs, "compactness")

    lecturer_sum, lecturer_hits, lecturer_total = _lecturer_component(sel, prefs)

    days_used = sel.days_used()
    # יום שכולו רכיבים בלי חובת נוכחות אינו יום קמפוס — פשוט לא מגיעים.
    # בלי ההבחנה הזאת המערכת "פותחת" יום שלם עבור תרגול יחיד שממילא אפשר
    # לוותר עליו, ואז סופרת אותו כאילו הוא מחייב הגעה.
    skippable = attendance_free_days(sel, prefs)
    effective_days = days_used - skippable
    days_penalty = max(0, len(effective_days) - prefs.target_days)

    gap_min = sel.gap_minutes()  # מ-models — לא ממציאים מחדש
    # מה שנספר לחובה: אותה המתנה, בלי הפסקת הצהריים הקבועה. המספר המוצג
    # נשאר ``gap_min`` — הסטודנט/ית רואים את זמן ההמתנה האמיתי, והניקוד
    # פשוט אינו גובה על חצי השעה שאיש לא בחר בה.
    billable_gap_min = sel.billable_gap_minutes(LUNCH_WINDOW)
    span_min = sel.span_minutes()  # מ-models — לא ממציאים מחדש
    late_min = late_finish_minutes(sel)

    conflicts = soft_conflicts_in(sel, prefs)  # ריק כברירת מחדל — ראי למעלה
    soft_count = len(conflicts)
    soft_minutes = sum(c.minutes for c in conflicts)

    # כל רכיב כבר מוכפל במשקל וחתום (+ לטובה, - לרעה).
    breakdown = {
        "lecturer": w_lect * lecturer_sum,
        "days": -w_days * days_penalty,
        "gaps": -w_gaps * (billable_gap_min / 60.0),
        "compactness": -w_comp * (span_min / 60.0),
        # ככל שהיום נגמר מאוחר יותר — קנס גדול יותר. זה המדד שמבטא
        # "שהיום ייגמר מוקדם ככל האפשר", ו-span לבדו לא מבטא אותו.
        WEIGHT_LATE_FINISH: -_weight(prefs, WEIGHT_LATE_FINISH) * (late_min / 60.0),
    }
    if soft_count:
        breakdown[WEIGHT_SOFT_CONFLICT] = -_weight(prefs, WEIGHT_SOFT_CONFLICT) * soft_count
    total = sum(breakdown.values())

    sched = ScoredSchedule(
        selection=sel,
        score=total,
        breakdown=breakdown,
        days_count=len(days_used),
        gap_minutes=gap_min,
        lecturer_hits=lecturer_hits,
        lecturer_total=lecturer_total,
    )
    # שני השדות האלה נצמדים למופע ולא לחוזה של models.ScoredSchedule, בדיוק
    # כמו ``.truncated`` ש-solve() מצמיד — כדי שמודל הנתונים המשותף יישאר
    # כפי שהוא. הקוראים שאינם בטוחים ישתמשו ב-soft_conflicts_of() /
    # soft_conflict_minutes_of(), שאף פעם לא נופלים.
    sched.late_finish_minutes = late_min  # type: ignore[attr-defined]
    sched.skippable_days = sorted(skippable)  # type: ignore[attr-defined]
    sched.effective_days = len(effective_days)  # type: ignore[attr-defined]
    sched.soft_conflicts = soft_count  # type: ignore[attr-defined]
    sched.soft_conflict_minutes = soft_minutes  # type: ignore[attr-defined]
    return sched


# ==========================================================================
# 3. מיון דטרמיניסטי
# ==========================================================================
#: דיוק ההשוואה של הניקוד. שני ניקודים שנבדלים בפחות מזה נחשבים שווים,
#: ואז שוברים את השוויון לפי הקריטריונים הבאים. אף פעם לא משווים floats ב-==.
_SCORE_PRECISION = 6


def _stable_key(sel: Selection) -> str:
    """מפתח טקסטואלי יציב למערכת — הקלף האחרון בשבירת שוויון."""
    return "|".join(
        sorted(f"{g.course_code}~{g.kind}~{g.group_id}" for g in sel.groups)
    )


def _sort_key(sched: ScoredSchedule) -> tuple[float, int, int, int, int, str]:
    """
    סדר העדיפויות: ניקוד גבוה, ואז פחות חפיפות מכוונות, ואז פחות ימים,
    ואז פחות חורים, ואז יום קצר יותר, ואז מפתח טקסטואלי יציב.
    (הכל 'קטן יותר = טוב יותר').

    החפיפות המכוונות נכנסות מיד אחרי הניקוד: הקנס כבר תומחר בניקוד עצמו,
    אבל אם שתי מערכות יצאו שוות בדיוק — עדיף להציע לסטודנט את זו שלא דורשת
    ממנו לוותר על שיעור. בברירת המחדל הערך הזה הוא 0 בכל המערכות, ולכן
    הסדר זהה לחלוטין לסדר שהיה לפני SPEC_V2.
    """
    return (
        -round(sched.score, _SCORE_PRECISION),
        soft_conflicts_of(sched),
        sched.days_count,
        sched.gap_minutes,
        sched.selection.span_minutes(),
        _stable_key(sched.selection),
    )


# ==========================================================================
# 4. solve — הפונקציה הראשית
# ==========================================================================
def _validate_tied(courses: list[Course]) -> None:
    """
    אוכפת את חוק הקורסים הצמודים: אם קורס מצהיר tied_with, כל שותפיו
    חייבים להיות ברשימה. הכל או כלום.

    Raises:
        TiedCoursesError: עם שם הקורס והקודים החסרים, בעברית.
    """
    present = {c.code for c in courses}
    for course in courses:
        if not course.tied_with:
            continue
        missing = [code for code in course.tied_with if code not in present]
        if missing:
            raise TiedCoursesError(course.code, missing, list(course.tied_with))


def solve(
    courses: list[Course],
    prefs: Preferences,
    top_n: int = 5,
    *,
    limit: int | None = None,
) -> list[ScoredSchedule]:
    """
    מוצאת את המערכות הטובות ביותר.

    השלבים:
        1. בדיקת קורסים צמודים (61756/61757/62027 — הכל או כלום).
        2. מנייה של כל הצירופים התקינים (enumerate_selections).
        3. ניקוד לכל אחד (score) ושמירת ה-top_n.
        4. אם אין אף פתרון — אבחון והרמת Infeasible. לעולם לא מחזירים [].

    Args:
        courses: הקורסים לשיבוץ.
        prefs:   העדפות הסטודנטית.
        top_n:   כמה מערכות להחזיר (לפחות 1).
        limit:   מכסת צמתים לחיפוש. None (ברירת המחדל) = מכסה שמחושבת לפי
                 גודל מרחב החיפוש בפועל (_node_budget), כדי שקלט ריאלי
                 ייסרק *במלואו* ולא ייקטע באמצע.

    Returns:
        רשימה ממוינת מהטובה לפחות טובה, באורך top_n לכל היותר.
        לכל מערכת מוצמדת התכונה .truncated — True רק אם החיפוש נקטע במכסת
        הצמתים, כלומר ייתכן שקיימת מערכת טובה יותר שלא נבדקה.

    Raises:
        TiedCoursesError: חבילת קורסים צמודים שבורה.
        Infeasible:       אין אף מערכת אפשרית; .reasons מכיל את ההסבר.
    """
    _validate_tied(courses)

    keep = max(1, int(top_n))
    # מגזמים את הרשימה מדי פעם כדי לא לאגור עשרות אלפי אובייקטים בזיכרון.
    prune_at = max(200, keep * 20)

    budget = _node_budget(courses, prefs) if limit is None else max(1, int(limit))

    kept: list[ScoredSchedule] = []
    feasible_count = 0
    hit_limit = False

    try:
        for sel in enumerate_selections(courses, prefs, limit=budget):
            feasible_count += 1
            kept.append(score(sel, prefs))
            if len(kept) >= prune_at:
                kept.sort(key=_sort_key)
                del kept[keep:]
    except SearchExhausted as exc:
        # לא מוותרים על מה שכבר נמצא — פשוט מסמנים שהחיפוש נקטע.
        hit_limit = True
        warnings.warn(
            f"החיפוש נקטע אחרי {exc.visited:,} צמתים (מתוך מכסה של {budget:,}); "
            f"המערכות שיוחזרו הן הטובות ביותר *מבין אלה שנבדקו* בלבד, וייתכן "
            f"שקיימת מערכת טובה יותר. אפשר להעלות את הפרמטר limit של solve() "
            f"(search truncated at the node limit; the result is best-so-far, "
            f"not proven best — raise solve(..., limit=...) to search further)",
            RuntimeWarning,
            stacklevel=2,
        )

    if not kept:
        reasons = diagnose_infeasibility(courses, prefs)
        if hit_limit:
            reasons.append(
                "החיפוש נעצר במכסת הצמתים לפני שנמצא פתרון — כדאי להעלות את "
                "פרמטר limit או להקטין את מרחב החיפוש (search node limit reached)."
            )
        problem = Infeasible(reasons)
        # ‏"לא נמצא פתרון" ו"לא סיימנו לחפש" הם שתי תשובות שונות לגמרי.
        # בלי ההבחנה הזאת מי שסופר וריאנטים היה רושם 0 ("בדקתי, לא עוזר")
        # על חיפוש שפשוט נגמרה לו המכסה — כלומר ניחוש שנראה כמו מדידה.
        problem.truncated = hit_limit  # type: ignore[attr-defined]
        raise problem

    kept.sort(key=_sort_key)
    best = kept[:keep]
    # מסמנים במפורש אם התוצאה חלקית — אזהרת RuntimeWarning לבדה נבלעת בקלות,
    # והקוראת חייבת דרך לדעת שהמערכת הזו היא "הטובה שנמצאה" ולא "הטובה ביותר".
    for sched in best:
        sched.truncated = hit_limit  # type: ignore[attr-defined]
    return best


# ==========================================================================
# 4ב. ויתורים — מה באמת ייפתח אם נרפה אילוץ אחד
# ==========================================================================
#: כמה צירופים של שני ויתורים לבדוק כשאף ויתור בודד אינו עוזר.
MAX_RELAXATION_PAIRS: int = 15


@dataclass
class Relaxation:
    """ויתור אחד אפשרי, ומה **נמדד** כשמוותרים עליו.

    ``schedules`` הוא תמיד תוצאה של פתירה אמיתית, ולעולם לא הערכה. כשאי
    אפשר למדוד — חיפוש שנקטע במכסה, או חריגה — הוא ``None``, והממשק מציג
    את הוויתור **בלי מספר**. מספר משוער כאן גרוע ממספר חסר: הוא נראה כמו
    הבטחה.

    ``cost`` הוא מה שהוויתור **גובה**, גם הוא מדוד. "12 מערכות" בלי
    "וכולן עם יום שישי" מוכר את הוויתור בלי המחיר שלו.
    """

    kind: str
    detail: dict
    apply: dict
    schedules: "int | None" = None
    cost: dict = field(default_factory=dict)
    combines_with: "dict | None" = None

    def helps(self) -> bool:
        return bool(self.schedules)


@dataclass
class RelaxationReport:
    """כל מה שנמדד על הוויתורים, בלי לאבד מדידה בדרך.

    ``singles`` נשמר גם כשרק זוגות עוזרים: "בדקנו כל אחד לחוד, אף אחד לא
    פותר" הוא בדיוק מה שהופך את "שילוב של שניים כן" למשפט מובן.
    """

    singles: list = field(default_factory=list)
    pairs: list = field(default_factory=list)
    pairs_only: bool = False

    def best(self) -> list:
        """מה להציג: הזוגות כשרק הם עוזרים, אחרת הבודדים שעוזרים."""
        if self.pairs_only:
            return list(self.pairs)
        return [r for r in self.singles if r.helps()]

    def measured_useless(self) -> list:
        """ויתורים שנמדדו במפורש כלא-עוזרים (0), להבדיל מלא-נמדדו."""
        return [r for r in self.singles if r.schedules == 0]


def _relax_candidates(prefs: Preferences) -> list:
    """אילו ויתורים רלוונטיים — רק אילוצים שהוגדרו בפועל.

    אין טעם להציע "לבטל את חסימת שישי" למי שלא חסם אותו.
    """
    out = []
    if prefs.forbid_friday:
        out.append((CONSTRAINT_FRIDAY, {}, {"forbid_friday": False}))
    if prefs.earliest > 0:
        out.append((CONSTRAINT_EARLIEST, {"was": prefs.earliest}, {"earliest": 0}))
    if prefs.latest < MINUTES_IN_DAY:
        out.append(
            (CONSTRAINT_LATEST, {"was": prefs.latest}, {"latest": MINUTES_IN_DAY})
        )
    for day, start, end in list(prefs.blocked_windows or []):
        out.append(
            (
                CONSTRAINT_BLOCKED,
                {"day": day, "start": start, "end": end},
                {"drop_blocked_window": [day, start, end]},
            )
        )
    return out


def _apply_delta(prefs: Preferences, delta: dict) -> Preferences:
    """מעתיק העדפות עם שינוי. לעולם לא נוגע במקור."""
    changes = {}
    for key, value in delta.items():
        if key == "drop_blocked_window":
            target = tuple(value)
            base = changes.get("blocked_windows", prefs.blocked_windows or [])
            changes["blocked_windows"] = [w for w in base if tuple(w) != target]
        else:
            changes[key] = value
    return dataclasses.replace(prefs, **changes)


def _measure(courses, prefs, top_n, limit):
    """פותר, ומחזיר (כמה, המערכות). ``None`` = לא ניתן היה למדוד.

    חיפוש שנקטע במכסה מחזיר "לפחות N" ולא N, ולכן הוא נחשב **לא נמדד** —
    זה בדיוק ההבדל בין מספר לניחוש.
    """
    try:
        found = solve(courses, prefs, top_n=top_n, limit=limit)
    except Infeasible as exc:
        # אפס = נבדק ואינו עוזר. ‏None = לא הספקנו לבדוק.
        return (None if getattr(exc, "truncated", False) else 0), []
    except Exception:  # noqa: BLE001 - וריאנט שנכשל אינו מפיל את השאר
        return None, []
    if any(getattr(x, "truncated", False) for x in found):
        return None, found
    return len(found), found


def _cost_of(kind: str, detail: dict, found: list) -> dict:
    """מה הוויתור גובה — נמדד מתוך המערכות שהוא באמת פתח."""
    if not found:
        return {}
    total = len(found)
    if kind == CONSTRAINT_FRIDAY:
        n = sum(1 for x in found if FRIDAY in x.selection.days_used())
        return {"metric": "friday", "n": n, "of": total}
    if kind == CONSTRAINT_EARLIEST:
        value = min(m.start for x in found for m in x.selection.all_meetings())
        return {"metric": "starts_at", "minutes": value, "of": total}
    if kind == CONSTRAINT_LATEST:
        value = max(m.end for x in found for m in x.selection.all_meetings())
        return {"metric": "ends_at", "minutes": value, "of": total}
    if kind == CONSTRAINT_BLOCKED:
        day = detail.get("day")
        start = detail.get("start")
        end = detail.get("end")
        n = sum(
            1
            for x in found
            if any(
                _window_overlaps(m, day, start, end)
                for m in x.selection.all_meetings()
            )
        )
        return {"metric": "uses_window", "n": n, "of": total}
    return {}


def relaxations(
    courses: list,
    prefs: Preferences,
    *,
    top_n: int = 5,
    limit: "int | None" = None,
    max_pairs: int = MAX_RELAXATION_PAIRS,
):
    """
    מה ייפתח אם נרפה אילוץ אחד — **נמדד**, אילוץ-אילוץ.

    כל מספר כאן מגיע מפתירה אמיתית. הפותר רץ במילישניות על קלט ריאלי
    (2,400 צירופים, 0.02 שניות), ולכן מדידה של חמישה וריאנטים זולה מכדי
    שתהיה סיבה כלשהי לנחש.

    Returns:
        ``RelaxationReport``. ``singles`` תמיד מכיל את **כל** הוויתורים
        הבודדים שנמדדו, כולל אלה שיצאו 0 — "בדקתי, לא עוזר" הוא מידע.
        ``pairs_only=True`` אומר שאף בודד אינו פותח דבר אבל צירוף של
        שניים כן, ואז ``pairs`` מחזיק אותם. רשימה ריקה אינה תשובה.
    """
    singles = []
    for kind, detail, delta in _relax_candidates(prefs):
        count, found = _measure(courses, _apply_delta(prefs, delta), top_n, limit)
        singles.append(
            Relaxation(
                kind=kind,
                detail=detail,
                apply=delta,
                schedules=count,
                cost=_cost_of(kind, detail, found),
            )
        )

    if any(r.helps() for r in singles):
        singles.sort(key=lambda r: (-(r.schedules or 0), r.kind))
        return RelaxationReport(singles=singles, pairs=[], pairs_only=False)

    # אף ויתור בודד לא עזר. האם שניים יחד כן? "שילוב של שניים כן" הוא
    # תשובה; רשימה ריקה היא הימנעות מתשובה.
    pairs = []
    cands = _relax_candidates(prefs)
    for i, (kind_a, detail_a, delta_a) in enumerate(cands):
        for kind_b, detail_b, delta_b in cands[i + 1 :]:
            if len(pairs) >= max_pairs:
                break
            stepped = _apply_delta(_apply_delta(prefs, delta_a), delta_b)
            count, found = _measure(courses, stepped, top_n, limit)
            if count:
                pairs.append(
                    Relaxation(
                        kind=kind_a,
                        detail=detail_a,
                        apply=delta_a,
                        schedules=count,
                        cost=_cost_of(kind_a, detail_a, found),
                        combines_with={
                            "kind": kind_b,
                            "detail": detail_b,
                            "apply": delta_b,
                        },
                    )
                )
    singles.sort(key=lambda r: (-(r.schedules or 0), r.kind))
    if pairs:
        pairs.sort(key=lambda r: -(r.schedules or 0))
        return RelaxationReport(singles=singles, pairs=pairs, pairs_only=True)
    return RelaxationReport(singles=singles, pairs=[], pairs_only=False)


# ==========================================================================
# 4ג. יעד ימים שאינו בר-השגה — איזה ויתור על קורס יפתח אותו
# ==========================================================================
@dataclass
class CourseDrop:
    """ויתור על קורס אחד (או על חבילה צמודה שלמה), ומה שנמדד בעקבותיו.

    ``codes`` הוא רשימה ולא קוד יחיד בכוונה: הידיעון מסמן קורסים מסוימים
    כחבילה (``tied_with``), וּויתור על אחד מהם לבדו אינו חוקי — ``solve``
    זורק ``TiedCoursesError``. לכן היחידה היא החבילה, והמחיר הוא סכום
    נקודות הזכות שלה. זה גם מה שמסדר אותה נכון: חבילה של שלושה קורסים
    יקרה יותר מקורס בודד, ולכן היא תוצע אחריו.

    ``min_days`` ו-``schedules`` נמדדים בפתירה אמיתית. ``None`` = לא ניתן
    היה למדוד, ואז לא מוצג מספר — בדיוק כמו בוויתור על אילוץ.
    """

    codes: list
    names: list
    credits: float
    min_days: "int | None" = None
    schedules: "int | None" = None

    def unlocks(self, target: int) -> bool:
        return self.min_days is not None and self.min_days <= target


@dataclass
class DayRelaxationReport:
    """כל האפשרויות שנמדדו ליעד ימים אחד."""

    target: int = 0
    options: list = field(default_factory=list)
    reachable_without_dropping: bool = False

    def helpful(self) -> list:
        return [o for o in self.options if o.unlocks(self.target)]

    def measured_useless(self) -> list:
        """נמדדו במפורש ואינם פותחים את היעד — להבדיל מלא-נמדדו."""
        return [
            o for o in self.options
            if o.min_days is not None and not o.unlocks(self.target)
        ]


def _tied_units(courses: list) -> list:
    """מחלק את הקורסים ליחידות ויתור: קורס בודד, או חבילה צמודה שלמה."""
    by_code = {c.code: c for c in courses}
    seen: set = set()
    units: list = []
    for course in courses:
        if course.code in seen:
            continue
        package = [course.code]
        for other in list(getattr(course, "tied_with", []) or []):
            if other in by_code and other not in package:
                package.append(other)
        for code in package:
            seen.add(code)
        units.append(sorted(package))
    return units


def _min_days_of(courses: list, prefs: Preferences, limit: "int | None"):
    """‏(מינימום ימים, כמה מערכות). ``None`` = לא ניתן היה למדוד.

    חיפוש שנקטע מחזיר "לפחות" ולא ערך — ולכן אינו נחשב מדידה.
    """
    budget = limit if limit is not None else _node_budget(courses, prefs)
    best = None
    count = 0
    try:
        for selection in enumerate_selections(courses, prefs, limit=budget):
            count += 1
            days = len(selection.days_used())
            if best is None or days < best:
                best = days
    except SearchExhausted:
        return None, None
    except Exception:  # noqa: BLE001
        return None, None
    if best is None:
        return None, 0
    return best, count


def day_relaxations(
    courses: list,
    prefs: Preferences,
    target_days: int,
    *,
    limit: "int | None" = None,
) -> DayRelaxationReport:
    """
    אילו ויתורים על קורסים יאפשרו את יעד הימים — **נמדד**.

    לכל יחידת ויתור (קורס, או חבילה צמודה) פותרים מחדש בלעדיה ובודקים
    למה יורד מינימום הימים. שום מספר כאן אינו הערכה.

    הסדר הוא **לפי נזק**: קודם מה שעולה פחות נקודות זכות. שני קורסים
    שפותחים את אותו יעד אינם שקולים, והמחיר הוא מה שמבדיל ביניהם.

    אין כאן מושג של "קורס שסומן כחובה" — הוא אינו קיים במערכת. הדבר
    הקרוב ביותר הוא ``tied_with``, וזו קביעה של הידיעון ולא בחירה של
    הסטודנט/ית.
    """
    report = DayRelaxationReport(target=int(target_days))

    base_min, _ = _min_days_of(courses, prefs, limit)
    if base_min is not None and base_min <= target_days:
        report.reachable_without_dropping = True
        return report

    by_code = {c.code: c for c in courses}
    for unit in _tied_units(courses):
        kept = [c for c in courses if c.code not in unit]
        if not kept:
            continue  # ויתור על הכול אינו הצעה
        min_days, count = _min_days_of(kept, prefs, limit)
        report.options.append(
            CourseDrop(
                codes=list(unit),
                names=[str(getattr(by_code.get(c), "name", "") or c) for c in unit],
                credits=round(
                    sum(float(getattr(by_code.get(c), "credits", 0) or 0) for c in unit),
                    1,
                ),
                min_days=min_days,
                schedules=count,
            )
        )

    # פחות נזק קודם: מי שעולה פחות נקודות זכות. ואז לפי כמה ימים נחסכו,
    # ואז לפי הקוד — כדי שהסדר יהיה יציב בין ריצות.
    report.options.sort(
        key=lambda o: (
            not o.unlocks(target_days),
            o.credits,
            o.min_days if o.min_days is not None else 99,
            o.codes,
        )
    )
    return report


# ==========================================================================
# 5. diagnose_infeasibility — למה אין פתרון
# ==========================================================================
def diagnose_infeasibility(courses: list[Course], prefs: Preferences) -> list[str]:
    """
    מסבירה בעברית *קונקרטית* למה אי אפשר לבנות מערכת. לא זורקת חריגות.

    שלוש שכבות בדיקה, לפי הסדר:
        1. אילוץ יחידני שמוחק סוג רכיב שלם — למשל: כל הרצאות 61753 מתחילות
           לפני 10:00, ולכן הכלל "לא לפני 10:00" חוסם את הקורס כולו.
        2. זוג סלוטים שכל צירוף ביניהם מתנגש — עם דוגמה קונקרטית
           (שני מספרי קבוצה, היום, ושעות החפיפה).
        3. אם אף אחד מהשניים לא תפס — החיפוש נכשל קומבינטורית (שילוב של
           כמה אילוצים חלשים שביחד לא משאירים כלום).

    Returns:
        רשימת מחרוזות. אף פעם לא זורקת.
    """
    reasons: list[str] = []

    # --- שלב 0: קורס בלי שום קבוצה --------------------------------------
    for course in courses:
        if not course.groups:
            reasons.append(
                f"לקורס {course.code} ({course.name}) אין אף קבוצה במאגר — "
                f"ייתכן שהקורס לא נפתח בסמסטר הזה "
                f"(no groups found; the course may not be offered)."
            )

    # --- שלב 1: אילוץ יחידני שמוחק סוג רכיב שלם -------------------------
    live_slots: list[_Slot] = []
    for course in courses:
        for kind in course.kinds():
            all_groups = course.groups_of(kind)
            survivors, eliminated = _filter_groups(all_groups, prefs)
            if survivors:
                live_slots.append(_Slot(course=course, kind=kind, candidates=survivors))
                continue

            # כל הקבוצות מהסוג הזה נפסלו. מי האשם?
            kinds_hit = {ctype for _g, probs in eliminated for ctype, _txt in probs}
            head = (
                f"כל קבוצות ה{kind} בקורס {course.code} ({course.name}) נפסלו "
                f"({len(eliminated)} קבוצות)"
            )

            if len(kinds_hit) == 1:
                # כל הקבוצות נפלו מאותו אילוץ — אפשר לנסח משפט אחד וברור.
                only = next(iter(kinds_hit))
                reasons.append(f"{head} — {_constraint_sentence(only, prefs)}.")
            else:
                # תערובת אילוצים — מפרטים לכל היותר שלוש דוגמאות.
                sample = "; ".join(
                    f"קב' {g.group_id} {probs[0][1]}" for g, probs in eliminated[:3]
                )
                more = "" if len(eliminated) <= 3 else f"; ועוד {len(eliminated) - 3}"
                reasons.append(f"{head}: {sample}{more}.")

    # --- שלב 2: זוג סלוטים שכל הצירופים ביניהם נפסלים -------------------
    # prefs עובר פנימה כדי שהאבחון ידבר על אותם כללים שהחיפוש עבד לפיהם:
    # אם חפיפות מכוונות מותרות, זוג שחופף אינו "חסום" ואסור להאשים אותו.
    for i, slot_a in enumerate(live_slots):
        for slot_b in live_slots[i + 1 :]:
            example = _all_pairs_blocked_example(slot_a, slot_b, prefs)
            if example is not None:
                reasons.append(example)

    # --- שלב 3: לא נמצאה סיבה נקודתית -----------------------------------
    if not reasons:
        total_space = 1
        for s in live_slots:
            total_space *= max(1, len(s.candidates))
        reasons.append(
            f"אף אילוץ בודד ואף זוג קורסים אינם חוסמים לבדם, אבל שום צירוף מלא "
            f"מתוך {total_space:,} האפשרויות אינו עומד בכל האילוצים יחד. "
            f"אפשר לוותר על קורס אחד, להרחיב את חלון השעות, או לבטל חלון חסום "
            f"(combinatorial exhaustion — no single pair is at fault)."
        )

    return reasons


def _constraint_sentence(constraint: str, prefs: Preferences) -> str:
    """משפט הסבר לאילוץ יחידני שמחק סוג רכיב שלם."""
    if constraint == CONSTRAINT_EARLIEST:
        return (
            f"כולן מתחילות לפני {fmt_time(prefs.earliest)}, והכלל "
            f"'אין שיעור לפני {fmt_time(prefs.earliest)}' חוסם את כולן"
        )
    if constraint == CONSTRAINT_LATEST:
        return (
            f"כולן מסתיימות אחרי {fmt_time(prefs.latest)}, והכלל "
            f"'אין שיעור אחרי {fmt_time(prefs.latest)}' חוסם את כולן"
        )
    if constraint == CONSTRAINT_FRIDAY:
        return "כולן מתקיימות ביום שישי, ולימודי שישי נאסרו"
    if constraint == CONSTRAINT_BLOCKED:
        windows = ", ".join(
            f"יום {DAY_NAMES_HE.get(d, d)} {fmt_time(s)}-{fmt_time(e)}"
            for d, s, e in prefs.blocked_windows
        )
        return f"כולן חופפות לחלונות החסומים ({windows})"
    return "אילוץ אישי חוסם את כולן"


def _all_pairs_blocked_example(
    slot_a: _Slot, slot_b: _Slot, prefs: Preferences | None = None
) -> str | None:
    """
    בודקת אם *כל* צירוף קבוצות בין שני סלוטים נפסל. אם כן — מחזירה משפט
    הסבר עם דוגמה קונקרטית; אחרת None.

    ‏``prefs=None`` = הכלל המחמיר (כל חפיפה פוסלת). כשמעבירים ``prefs``,
    הבדיקה משתמשת באותם כללי נוכחות שהחיפוש עצמו עבד לפיהם.
    """
    if not slot_a.candidates or not slot_b.candidates:
        return None

    kind_of = _kind_index([slot_a.course, slot_b.course])

    example: str | None = None
    for a in slot_a.candidates:
        for b in slot_b.candidates:
            if _pair_ok(a, b, kind_of, prefs):
                return None  # נמצא צירוף חוקי אחד — הזוג הזה לא אשם

            if example is None:
                overlap = _first_overlap(a, b)
                if overlap is not None:
                    day, ov_s, ov_e = overlap
                    example = (
                        f"קורס {a.course_code} קבוצה {a.group_id} ({a.kind}) מתנגש עם "
                        f"{b.course_code} קבוצה {b.group_id} ({b.kind}) — "
                        f"{_fmt_overlap(day, ov_s, ov_e)}"
                    )
                else:
                    # לא התנגשות זמנים אלא הפרת linked_to.
                    example = (
                        f"קורס {a.course_code} קבוצה {a.group_id} ({a.kind}) אינה מותרת "
                        f"יחד עם קבוצה {b.group_id} ({b.kind}) לפי כלל הקבוצות הצמודות "
                        f"(linked_to)"
                    )

    same = slot_a.course.code == slot_b.course.code
    scope = (
        f"בתוך קורס {slot_a.course.code}: כל שילוב של {slot_a.kind} עם {slot_b.kind} נפסל"
        if same
        else (
            f"בין {slot_a.course.code} ({slot_a.kind}) לבין "
            f"{slot_b.course.code} ({slot_b.kind}): כל צירוף אפשרי של קבוצות נפסל"
        )
    )
    return f"{scope}. לדוגמה: {example} (every group pair is blocked)."


# ==========================================================================
# 6. relax_suggestions — מה לעשות עכשיו
# ==========================================================================
def relax_suggestions(courses: list[Course], prefs: Preferences) -> list[str]:
    """
    צעדים מעשיים בעברית להרפיית האילוצים, כשאין פתרון (או שהפתרון גרוע).

    מציעה, לפי סדר "כמה זה כואב":
        1. להעלות את יעד הימים (הכי זול — זו העדפה רכה בלבד).
        2. להרחיב את חלון השעות בדיוק עד מה שהנתונים דורשים.
        3. לבטל חלון חסום שמוחק הרבה קבוצות.
        4. לאפשר יום שישי.
        5. לאפשר חפיפה מכוונת ברכיב שאין בו חובת נוכחות (SPEC_V2 §2) —
           מוצע רק כשזה באמת פותח זוג קורסים שחסום כרגע.
        6. לוותר על קורס — כולל אזהרה שקורס צמוד גורר את כל החבילה.
    """
    tips: list[str] = []

    # --- 1. יעד ימים -----------------------------------------------------
    if prefs.target_days < 6:
        tips.append(
            f"העלי את target_days מ-{prefs.target_days} ל-{prefs.target_days + 1} "
            f"(ואם צריך עד 5): יעד הימים הוא העדפה רכה — הוא רק מוריד ניקוד ואינו "
            f"פוסל מערכות, אבל הוא עלול לדחוק מערכות טובות למטה ברשימה "
            f"(raise target_days to {prefs.target_days + 1})."
        )

    # --- 2. חלון השעות ---------------------------------------------------
    all_meetings = [m for c in courses for g in c.groups for m in g.meetings]
    if all_meetings:
        min_start = min(m.start for m in all_meetings)
        max_end = max(m.end for m in all_meetings)
        if prefs.earliest > min_start:
            tips.append(
                f"הקדימי את earliest מ-{fmt_time(prefs.earliest)} ל-{fmt_time(min_start)} — "
                f"יש שיעורים שמתחילים בשעה הזו ואין דרך לעקוף אותם "
                f"(widen the window: earliest -> {fmt_time(min_start)})."
            )
        if prefs.latest < max_end:
            tips.append(
                f"אחרי את latest מ-{fmt_time(prefs.latest)} ל-{fmt_time(max_end)} "
                f"(widen the window: latest -> {fmt_time(max_end)})."
            )

    # --- 3. חלונות חסומים ------------------------------------------------
    for day, w_start, w_end in prefs.blocked_windows:
        blocked_count = sum(
            1
            for c in courses
            for g in c.groups
            if any(_window_overlaps(m, day, w_start, w_end) for m in g.meetings)
        )
        if blocked_count:
            tips.append(
                f"בטלי או כווצי את החלון החסום ביום {DAY_NAMES_HE.get(day, day)} "
                f"{fmt_time(w_start)}-{fmt_time(w_end)} — הוא מוחק {blocked_count} קבוצות "
                f"(drop this blocked window)."
            )

    # --- 4. יום שישי -----------------------------------------------------
    if prefs.forbid_friday:
        friday_groups = sum(
            1 for c in courses for g in c.groups if FRIDAY in g.days()
        )
        if friday_groups:
            tips.append(
                f"אפשרי לימודים ביום שישי (forbid_friday=False) — {friday_groups} קבוצות "
                f"נחסמות כרגע בגללו (allow Friday)."
            )

    # --- 5. חפיפה מכוונת ברכיב בלי חובת נוכחות ---------------------------
    for slot_a, slot_b in _soft_conflict_opportunities(courses, prefs)[:2]:
        tips.append(
            f"‏{slot_a.course.code} ({slot_a.kind}) ו-{slot_b.course.code} "
            f"({slot_b.kind}) חוסמים זה את זה רק בגלל חפיפה בשעות. אם באחד מהם "
            f"אין חובת נוכחות — אפשר לסמן אותו ככזה ולאפשר חפיפות מכוונות "
            f"(allow_soft_conflicts), ואז המערכת תיבנה עם החפיפה הזו, תדווח "
            f"עליה במפורש, ותקבל קנס ניקוד "
            f"(mark a component attendance-optional and allow soft conflicts)."
        )

    # --- 6. ויתור על קורס ------------------------------------------------
    for course in _most_problematic_courses(courses, prefs)[:2]:
        if course.tied_with:
            block = ", ".join([course.code, *course.tied_with])
            tips.append(
                f"ויתור על {course.code} ({course.name}) מחייב ויתור על כל החבילה "
                f"הצמודה [{block}] — זו החלטה כבדה, שקלי אותה אחרונה "
                f"(dropping a tied course drops the whole block)."
            )
        else:
            tips.append(
                f"שקלי לוותר על {course.code} ({course.name}) ולדחות אותו לסמסטר הבא — "
                f"זה הקורס הכי בעייתי לשיבוץ כרגע (drop course {course.code})."
            )

    if not tips:
        tips.append(
            "כל האילוצים כבר רפויים; הבעיה היא שילוב הקורסים עצמו. "
            "הדרך היחידה היא לוותר על קורס (only dropping a course will help)."
        )
    return tips


def _soft_conflict_opportunities(
    courses: list[Course], prefs: Preferences
) -> list[tuple[_Slot, _Slot]]:
    """זוגות סלוטים שחסומים היום, ושחפיפה מכוונת הייתה פותחת.

    התשובה חייבת להיות מדויקת: אין טעם להציע לסטודנט לוותר על נוכחות אם
    החסימה בכלל נובעת מ-``linked_to`` ולא משעות. לכן הבדיקה היא השוואה בין
    שני עולמות — העולם הנוכחי, ועולם היפותטי שבו *כל* הרכיבים פטורים
    מנוכחות. זוג שחסום בראשון ופתוח בשני נחסם בזמנים בלבד.

    מחזירה [] כשהמתג כבר דלוק — אין מה להציע.
    """
    if getattr(prefs, "allow_soft_conflicts", False):
        return []

    all_optional = {
        course.code: {kind: False for kind in course.kinds()} for course in courses
    }
    relaxed = replace(prefs, allow_soft_conflicts=True, attendance=all_optional)

    live_slots: list[_Slot] = []
    for course in courses:
        for kind in course.kinds():
            survivors, _ = _filter_groups(course.groups_of(kind), prefs)
            if survivors:
                live_slots.append(_Slot(course, kind, survivors))

    opportunities: list[tuple[_Slot, _Slot]] = []
    for i, slot_a in enumerate(live_slots):
        for slot_b in live_slots[i + 1 :]:
            if _all_pairs_blocked_example(slot_a, slot_b, prefs) is None:
                continue  # לא חסום היום — אין מה לפתוח
            if _all_pairs_blocked_example(slot_a, slot_b, relaxed) is None:
                opportunities.append((slot_a, slot_b))
    return opportunities


def _most_problematic_courses(courses: list[Course], prefs: Preferences) -> list[Course]:
    """
    מדרגת קורסים לפי "כמה הם מפריעים": סלוטים שנמחקו לגמרי + מספר הזוגות
    שבהם כל הצירופים חסומים. משמש רק להצעות — לא משפיע על החיפוש.
    """
    trouble: dict[str, int] = {c.code: 0 for c in courses}

    live_slots: list[_Slot] = []
    for course in courses:
        if not course.groups:
            trouble[course.code] += 10
        for kind in course.kinds():
            survivors, _ = _filter_groups(course.groups_of(kind), prefs)
            if survivors:
                live_slots.append(_Slot(course, kind, survivors))
            else:
                trouble[course.code] += 5

    for i, a in enumerate(live_slots):
        for b in live_slots[i + 1 :]:
            if _all_pairs_blocked_example(a, b, prefs) is not None:
                trouble[a.course.code] += 1
                trouble[b.course.code] += 1

    ranked = sorted(
        courses,
        key=lambda c: (-trouble[c.code], len(c.tied_with), c.code),
    )
    # מחזירים רק קורסים שבאמת בעייתיים; אם אף אחד לא — הראשון ברשימה עדיין שימושי.
    problematic = [c for c in ranked if trouble[c.code] > 0]
    if problematic:
        return problematic
    return ranked[:1]


# ==========================================================================
# 7. בדיקת עשן (smoke test) — רק כשמריצים את הקובץ ישירות
# ==========================================================================
def _to_minutes(value: object) -> int:
    """מקבלת 510 או '08:30' ומחזירה דקות מחצות."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a time")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if ":" in text:
        hh, mm = text.split(":", 1)
        return int(hh) * 60 + int(mm)
    return int(text)


def _courses_from_json(raw: object) -> list[Course]:
    """
    קורא מבנה JSON סלחני והופך אותו ל-Course objects.

    Technical note: the canonical loader is parser.load_sections(); this local
    reader exists only so the smoke test can run before parser.py is finished.
    It accepts {"courses": {...}}, {code: {...}} and a bare list of dicts.
    """
    data: object = raw
    if isinstance(data, dict) and "courses" in data:
        data = data["courses"]

    if isinstance(data, dict):
        items = list(data.values())
    elif isinstance(data, list):
        items = list(data)
    else:
        return []

    courses: list[Course] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip()
        groups: list[Group] = []
        for gd in item.get("groups", []) or []:
            meetings = [
                Meeting(
                    day=int(md.get("day", 0)),
                    start=_to_minutes(md.get("start", 0)),
                    end=_to_minutes(md.get("end", 0)),
                    room=str(md.get("room", "")),
                    building=str(md.get("building", "")),
                )
                for md in (gd.get("meetings", []) or [])
            ]
            groups.append(
                Group(
                    course_code=str(gd.get("course_code", code)),
                    group_id=str(gd.get("group_id", gd.get("group", gd.get("id", "")))),
                    kind=str(gd.get("kind", gd.get("type", ""))),
                    lecturer=str(gd.get("lecturer", "")),
                    meetings=meetings,
                    linked_to=[str(x) for x in (gd.get("linked_to") or [])],
                    note=str(gd.get("note", "")),
                )
            )
        courses.append(
            Course(
                code=code,
                name=str(item.get("name", "")),
                credits=float(item.get("credits", 0) or 0),
                groups=groups,
                tied_with=[str(x) for x in (item.get("tied_with") or [])],
            )
        )
    return courses


def _load_fixture(path: Path) -> list[Course]:
    """טוען את קובץ הדוגמה. מנסה קודם את parser.load_sections אם הוא כבר קיים."""
    try:
        from parser import load_sections  # type: ignore[attr-defined]

        loaded = load_sections(str(path))
        if isinstance(loaded, dict) and loaded:
            return list(loaded.values())
    except Exception:
        # parser.py עדיין לא נכתב / לא תואם — נופלים לקורא המקומי.
        pass

    with open(path, encoding="utf-8") as fh:
        return _courses_from_json(json.load(fh))


def _demo_courses() -> list[Course]:
    """מערך זעיר מובנה, לשימוש כשקובץ ה-fixture עדיין לא קיים."""
    return [
        Course(
            code="11069",
            name="אנגלית טכנית יישומית",
            credits=1.0,
            groups=[
                Group("11069", "11", "הרצאה", "כהן", [Meeting(1, 480, 600)]),
                Group("11069", "12", "הרצאה", "לוי", [Meeting(3, 600, 720)]),
            ],
        ),
        Course(
            code="61832",
            name="מבוא להסתברות וסטטיסטיקה",
            credits=4.0,
            groups=[
                Group("61832", "11", "הרצאה", "לוי", [Meeting(1, 600, 720)]),
                Group("61832", "21", "תרגול", "כהן", [Meeting(1, 720, 840)]),
                Group("61832", "22", "תרגול", "כהן", [Meeting(3, 480, 600)]),
            ],
        ),
    ]


def _smoke_test() -> int:
    """הרצה ידנית: python src/scheduler.py"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass  # זרם שלא ניתן לשינוי (pipe/pytest capture) — ממשיכים בלי

    root = Path(__file__).resolve().parents[1]
    fixture = root / "tests" / "fixtures" / "sample_sections.json"

    if fixture.exists():
        print(f"טוען fixture: {fixture}")
        courses = _load_fixture(fixture)
    else:
        print(f"אין fixture ב-{fixture} — מריץ דוגמה מובנית קטנה במקום.")
        courses = _demo_courses()

    print(f"נטענו {len(courses)} קורסים: {', '.join(c.code for c in courses)}")

    prefs = Preferences(
        target_days=4,
        weights=dict(DEFAULT_WEIGHTS),
    )

    try:
        best = solve(courses, prefs, top_n=3)
    except TiedCoursesError as exc:
        print(f"שגיאת קורסים צמודים: {exc}")
        return 2
    except Infeasible as exc:
        print("אין מערכת אפשרית. סיבות:")
        for reason in exc.reasons:
            print(f"  • {reason}")
        print("הצעות להרפיה:")
        for tip in relax_suggestions(courses, prefs):
            print(f"  → {tip}")
        return 1

    print(f"\nנמצאו {len(best)} מערכות מובילות:\n")
    for i, sched in enumerate(best, start=1):
        print(f"[{i}] {sched.summary()}")
        for key, value in sched.breakdown.items():
            print(f"      {key:<14} {value:+8.2f}")
        for g in sorted(sched.selection.groups, key=lambda g: (g.course_code, g.kind)):
            print(f"      {g}")
        # חפיפה מכוונת לעולם לא עוברת בשקט — גם לא בבדיקת העשן.
        for line in describe_soft_conflicts(sched.selection, prefs):
            print(f"      {line}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(_smoke_test())
