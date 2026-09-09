"""
מודל הנתונים של SlotWise — SlotWise data model.

זהו החוזה המשותף לכל שאר המודולים. אין לשנות שמות שדות או חתימות.
This is the shared contract for every other module. Do not rename fields or methods.

מוסכמות (conventions):
    יום  (day)   : 1=ראשון ... 6=שישי
    שעה  (time)  : דקות מחצות. 08:30 -> 510 ,  20:00 -> 1200
    חפיפה (overlap): חצי-פתוח [start, end) — שיעור שנגמר ב-10:00 ואחד שמתחיל ב-10:00 *אינם* מתנגשים.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# ימים
# --------------------------------------------------------------------------
DAY_NAMES_HE: dict[int, str] = {
    1: "ראשון",
    2: "שני",
    3: "שלישי",
    4: "רביעי",
    5: "חמישי",
    6: "שישי",
}

DAY_LETTERS_HE: dict[int, str] = {1: "א", 2: "ב", 3: "ג", 4: "ד", 5: "ה", 6: "ו"}

# --------------------------------------------------------------------------
# סוגי מפגש (component kinds)
# --------------------------------------------------------------------------
KIND_LECTURE = "הרצאה"
KIND_TUTORIAL = "תרגול"
KIND_LAB = "מעבדה"
KIND_PROJECT = "פרויקט"
#: "שו\"ת" = שיעור ותרגיל באותו מפגש. סוג רכיב אמיתי בבראודה
#: (למשל 11069 אנגלית טכנית). נרשמים לקבוצה אחת שלו, בדיוק כמו לכל רכיב אחר.
KIND_COMBINED = "שו\"ת"
KIND_OTHER = "אחר"

#: סדר תצוגה קבוע — משמש למיון קבוצות לפי סוג.
KIND_ORDER: tuple[str, ...] = (
    KIND_LECTURE,
    KIND_TUTORIAL,
    KIND_LAB,
    KIND_PROJECT,
    KIND_COMBINED,
    KIND_OTHER,
)


def fmt_time(minutes: int) -> str:
    """510 -> '08:30'."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# --------------------------------------------------------------------------
# Meeting — מפגש בודד בשבוע
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Meeting:
    """מפגש בודד: יום אחד, טווח שעות אחד.

    ``semester`` הוא עמודת "סמסטר" מהידיעון ("א" / "ב" / "קיץ"). קורס יכול
    להיפתח בשני הסמסטרים, והידיעון מציג את שניהם באותו עמוד — לכן חובה לסנן
    לפי הסמסטר המבוקש, אחרת מפגשים מסמסטר ב' יזלגו למערכת של סמסטר א'.
    """

    day: int
    start: int
    end: int
    room: str = ""
    building: str = ""
    semester: str = ""

    def overlaps(self, other: "Meeting") -> bool:
        """חפיפה חצי-פתוחה [start, end): 08:30-10:00 ו-10:00-12:00 אינם מתנגשים."""
        if self.day != other.day:
            return False
        return self.start < other.end and other.start < self.end

    def duration(self) -> int:
        """אורך המפגש בדקות."""
        return max(0, self.end - self.start)

    def __str__(self) -> str:
        where = f" {self.building} {self.room}".rstrip()
        return f"יום {DAY_LETTERS_HE.get(self.day, '?')} {fmt_time(self.start)}-{fmt_time(self.end)}{where}"


# --------------------------------------------------------------------------
# Group — קבוצה אחת שניתן להירשם אליה
# --------------------------------------------------------------------------
@dataclass
class Group:
    """קבוצה אחת (סקשן) של רכיב אחד בקורס — למשל 'הרצאה קבוצה 11'."""

    course_code: str
    group_id: str
    kind: str
    lecturer: str
    meetings: list[Meeting]
    linked_to: list[str] = field(default_factory=list)
    note: str = ""
    #: הודעת מצב של הידיעון על הקבוצה — "הקורס מלא", "בקורס זה קיימת רשימת
    #: המתנה", "מיועד לחוזרים". שדה נפרד מ-``note`` בכוונה: ``note`` נושא
    #: הערות שיוך וחובת נוכחות, ו-``api.attendance_info`` סורק אותו בביטוי
    #: רגולרי — הודעת מצב שנכנסת לשם משנה את מה שהממשק אומר על נוכחות.
    #: עד 2026-09-09 הטקסט הזה נדבק **לתוך שם המרצה** ("מר כהן אסף הקורס
    #: מלא"), כי הוא יושב ב-span אדום משלו בין השם לבין "שפת הוראה", ו-
    #: ``_visible_text`` משטח את שניהם למחרוזת אחת.
    status_note: str = ""
    #: הסמסטר שהקבוצה שייכת אליו לפי הידיעון עצמו — הארגומנט השני של כפתור
    #: "פרטים נוספים" (``-N1`` = א, ``-N2`` = ב, ``-N3`` = קיץ). זהו המקור
    #: **היחיד** שאומר לאיזה סמסטר שייכת קבוצה שאין לה מועד קבוע: בלעדיו
    #: קבוצה של סמסטר ב' שטרם נקבע לה מועד נראית זהה לפרויקט גמר של סמסטר א'.
    semester: str = ""

    def days(self) -> set[int]:
        """קבוצת הימים שבהם הקבוצה נפגשת."""
        return {m.day for m in self.meetings}

    def total_minutes(self) -> int:
        return sum(m.duration() for m in self.meetings)

    def conflicts_with(self, other: "Group") -> bool:
        """האם קיים זוג מפגשים חופפים בין שתי הקבוצות."""
        for a in self.meetings:
            for b in other.meetings:
                if a.overlaps(b):
                    return True
        return False

    def label(self) -> str:
        return f"{self.course_code} קב' {self.group_id} ({self.kind})"

    def __str__(self) -> str:
        times = " | ".join(str(m) for m in self.meetings) or "ללא מפגשים"
        who = self.lecturer or "מרצה לא ידוע"
        return f"{self.label()} — {who} — {times}"


# --------------------------------------------------------------------------
# Course — קורס עם כל הקבוצות שלו
# --------------------------------------------------------------------------
@dataclass
class Course:
    """קורס יחיד וכל הקבוצות הפתוחות בו בסמסטר הנוכחי."""

    code: str
    name: str
    credits: float
    groups: list[Group]
    tied_with: list[str] = field(default_factory=list)

    def kinds(self) -> list[str]:
        """סוגי הרכיבים הקיימים בקורס, בסדר תצוגה קבוע."""
        present = {g.kind for g in self.groups}
        ordered = [k for k in KIND_ORDER if k in present]
        # כל סוג לא מוכר נוסף בסוף, לפי סדר אלפביתי, כדי לא לאבד נתונים.
        ordered += sorted(k for k in present if k not in KIND_ORDER)
        return ordered

    def groups_of(self, kind: str) -> list[Group]:
        return [g for g in self.groups if g.kind == kind]

    def lecturers(self) -> list[str]:
        """שמות המרצים הייחודיים בקורס, ממוינים, ללא ריקים."""
        return sorted({g.lecturer.strip() for g in self.groups if g.lecturer.strip()})

    def lecturers_by_kind(self, kind: str) -> list[str]:
        return sorted({g.lecturer.strip() for g in self.groups_of(kind) if g.lecturer.strip()})

    def __str__(self) -> str:
        return f"{self.code} {self.name} ({self.credits} נ\"ז, {len(self.groups)} קבוצות)"


# --------------------------------------------------------------------------
# Selection — בחירה שלמה אחת
# --------------------------------------------------------------------------
@dataclass
class Selection:
    """בחירה שלמה: קבוצה אחת לכל (קורס, סוג רכיב)."""

    groups: list[Group]

    def all_meetings(self) -> list[Meeting]:
        return [m for g in self.groups for m in g.meetings]

    def days_used(self) -> set[int]:
        return {m.day for m in self.all_meetings()}

    def meetings_by_day(self) -> dict[int, list[Meeting]]:
        """מפגשים מקובצים לפי יום וממוינים לפי שעת התחלה."""
        by_day: dict[int, list[Meeting]] = {}
        for m in self.all_meetings():
            by_day.setdefault(m.day, []).append(m)
        for day in by_day:
            by_day[day].sort(key=lambda m: (m.start, m.end))
        return by_day

    def group_for(self, course_code: str, kind: str) -> Group | None:
        for g in self.groups:
            if g.course_code == course_code and g.kind == kind:
                return g
        return None

    def course_codes(self) -> set[str]:
        return {g.course_code for g in self.groups}

    def is_feasible(self) -> bool:
        """אין שתי קבוצות שמתנגשות בזמן.

        המשמעות כאן היא **מחמירה ובלתי משתנה**: כל חפיפה, מכל סוג, פוסלת.
        הבחירה אם חפיפה מסוימת *מותרת* (למשל כשאין חובת נוכחות בהרצאה) אינה
        שייכת למודל הנתונים אלא למנוע — ראי ``scheduler.conflict_is_hard``.
        """
        for i, a in enumerate(self.groups):
            for b in self.groups[i + 1 :]:
                if a.conflicts_with(b):
                    return False
        return True

    def overlapping_pairs(self) -> list[tuple[Group, Group]]:
        """כל זוגות הקבוצות שחופפות בזמן, בסדר יציב.

        ``is_feasible`` עונה "כן/לא"; הפונקציה הזו עונה "מה בדיוק חופף" — כדי
        שהממשק יוכל *להראות* לסטודנט מה הוא מוותר עליו כשהוא בוחר מערכת עם
        חפיפה מכוונת (חפיפה שאושרה כי באחד הרכיבים אין חובת נוכחות).

        Returns:
            רשימת זוגות ``(a, b)`` שבהם ``a`` מופיע לפני ``b`` ב-``groups``.
            רשימה ריקה פירושה בדיוק ``is_feasible() is True``.
        """
        pairs: list[tuple[Group, Group]] = []
        for i, a in enumerate(self.groups):
            for b in self.groups[i + 1 :]:
                if a.conflicts_with(b):
                    pairs.append((a, b))
        return pairs

    def gap_intervals(self) -> list[tuple[int, int]]:
        """כל 'חור' במערכת, כטווח (התחלה, סוף), באותו יום בלבד.

        ההגדרה היחידה של "חור". שתי הספירות שמתחתיה נגזרות ממנה, כדי שלא
        ייווצר מצב שבו "כמה זמן המתנה יש" ו"על כמה ממנו נקנס" עונים על
        שאלות שנספרו בשתי לולאות שונות.
        """
        out: list[tuple[int, int]] = []
        for meetings in self.meetings_by_day().values():
            cursor = meetings[0].end
            for m in meetings[1:]:
                if m.start > cursor:
                    out.append((cursor, m.start))
                cursor = max(cursor, m.end)
        return out

    def gap_minutes(self) -> int:
        """סך 'החורים' — דקות פנויות בין מפגשים רצופים באותו יום בלבד.

        זו **מדידה**, והיא נשארת כפי שהיא: זה המספר שמוצג כ"זמן המתנה",
        נשלח ב-API ומודפס בסיכום. מה שנספר לחובה בניקוד הוא עניין נפרד —
        ראי ``billable_gap_minutes``.
        """
        return sum(end - start for start, end in self.gap_intervals())

    def billable_gap_minutes(self, window: tuple[int, int] | None = None) -> int:
        """דקות ההמתנה שנספרות לחובה, בלי הפסקה קבועה שנופלת בתוכן.

        ‏``window`` הוא חלון הצהריים של המוסד — חצי שעה שאי אפשר לקבוע בה
        שיעור. המתנה בתוכה אינה בחירה של אף אחד ואינה מבדילה בין מערכת
        למערכת, ולכן קנס עליה מעניש כל מי שיש לו שיעור משני צדדיה.

        הזיכוי ניתן על **החפיפה של החור עצמו** עם החלון, ולא על עצם קיומו
        של החלון. שיעור שרץ דרכו — 11:30–13:50 — אינו יוצר חור, ולכן אינו
        מזוכה בדבר: אין לו הפסקת צהריים, ואסור שהניקוד יתנהג כאילו יש.
        """
        if not window:
            return self.gap_minutes()
        low, high = window
        total = 0
        for start, end in self.gap_intervals():
            lunch = max(0, min(end, high) - max(start, low))
            total += (end - start) - lunch
        return total

    def span_minutes(self) -> int:
        """סך 'אורך היום' — מהמפגש הראשון ועד האחרון, לכל יום, מחובר."""
        total = 0
        for meetings in self.meetings_by_day().values():
            total += max(m.end for m in meetings) - min(m.start for m in meetings)
        return total


# --------------------------------------------------------------------------
# ScoredSchedule — מערכת מנוקדת
# --------------------------------------------------------------------------
@dataclass
class ScoredSchedule:
    """מערכת שעות אחת אחרי ניקוד."""

    selection: Selection
    score: float
    breakdown: dict[str, float]
    days_count: int
    gap_minutes: int
    lecturer_hits: int
    lecturer_total: int

    def summary(self) -> str:
        days = "".join(
            DAY_LETTERS_HE[d] for d in sorted(self.selection.days_used()) if d in DAY_LETTERS_HE
        )
        return (
            f"ניקוד {self.score:.1f} | {self.days_count} ימים ({days}) | "
            f"חורים {self.gap_minutes // 60}:{self.gap_minutes % 60:02d} | "
            f"מרצים מועדפים {self.lecturer_hits}/{self.lecturer_total}"
        )
