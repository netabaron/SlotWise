"""
render.py — שכבת התצוגה של SlotWise (section 6 of SPEC.md).

שלוש פונקציות ציבוריות:
    render_terminal(sched, courses)              -> טבלה שבועית כטקסט מיושר למסך
    render_html(scheds, courses, out_path, title)-> קובץ HTML עצמאי אחד (RTL), מחזיר את הנתיב
    render_lecturer_menu(course)                 -> תפריט בחירת מרצים (שלב 4 בזרימה)

מוסכמות מ-models.py: יום 1=ראשון..6=שישי, שעה = דקות מחצות.

הערה חשובה לגבי הטרמינל בחלונות (Windows / RTL caveat)
------------------------------------------------------
אנחנו *לא* מנסים לבצע סידור דו-כיווני (bidi) אמיתי בטרמינל: זו בעיה קשה,
והתוצאה משתנה בין cmd, PowerShell ו-Windows Terminal. לכן הרשת בטרמינל
נבנית משמאל לימין, כשאותיות הימים א..ו הן כותרות העמודות בסדר הזה.
התצוגה ה-RTL "האמיתית" היא קובץ ה-HTML.

כל טקסט עברי הוא ברוחב תו בודד, ולכן ריפוד (padding) נעשה בספירת תווים
פשוטה עם pad() ולא בחישוב רוחב גרפי.
"""

from __future__ import annotations

import html as _htmlmod
import os
import zlib
from datetime import datetime

from models import (
    DAY_LETTERS_HE,
    DAY_NAMES_HE,
    KIND_ORDER,
    Course,
    Group,
    Meeting,
    ScoredSchedule,
    fmt_time,
)

# --------------------------------------------------------------------------
# קבועים
# --------------------------------------------------------------------------

# רזולוציית הרשת בדקות.
# חייבת להיות 15 ולא 30: שעות הלימוד בבראודה נופלות על :00/:15/:30/:45, ושיעור
# 08:30-10:15 שאחריו 10:15-12:00 הוא רצף תקין לחלוטין. ברשת של 30 דקות שניהם
# נופלים לאותו תא 10:00-10:30 והתצוגה מדווחת על "התנגשות" שלא קיימת במציאות.
SLOT_MINUTES = 15

#: ששת ימי הלימוד. בטרמינל הם נפרשים משמאל לימין, ב-HTML מימין לשמאל.
DAYS: tuple[int, ...] = (1, 2, 3, 4, 5, 6)

#: רוחב תא בטבלת הטרמינל (בתווים) ורוחב עמודת השעה.
CELL_WIDTH = 20
TIME_WIDTH = 11  # "08:30-09:00"

#: חלון ברירת מחדל ל-HTML כשאין בכלל מפגשים.
DEFAULT_DAY_START = 8 * 60
DEFAULT_DAY_END = 18 * 60

UNKNOWN_LECTURER_HE = "מרצה לא ידוע"

#: תרגום מפתחות ה-breakdown של scheduler.score לעברית.
BREAKDOWN_LABELS_HE: dict[str, str] = {
    "lecturer": "מרצים מועדפים (lecturer)",
    "days": "מספר ימים בקמפוס (days)",
    "gaps": "חורים בין שיעורים (gaps)",
    "compactness": "אורך יום הלימודים (compactness)",
}

# --------------------------------------------------------------------------
# פלטת הצבעים — 10 גוונים פסטליים, אחד לכל קורס
# --------------------------------------------------------------------------
# לכל גוון: (רקע, מסגרת, טקסט) במצב בהיר, ואותו דבר במצב כהה.
# הזוגות נבחרו כך שיחס הניגודיות של הטקסט מול הרקע גבוה מ-7:1 (AAA)
# בשני המצבים, כי קוראים מזה שעות.
PALETTE: tuple[dict[str, tuple[str, str, str]], ...] = (
    {"light": ("#dbeafe", "#93c5fd", "#152c56"), "dark": ("#1d3557", "#4b7bb5", "#dbeafe")},
    {"light": ("#dcfce7", "#86efac", "#0f3d22"), "dark": ("#17402a", "#3f8a5c", "#dcfce7")},
    {"light": ("#fef3c7", "#fcd34d", "#5c2c06"), "dark": ("#453413", "#8f7124", "#fef3c7")},
    {"light": ("#ffe4e6", "#fda4af", "#6b0f28"), "dark": ("#4a1f2a", "#94505f", "#ffe4e6")},
    {"light": ("#ede9fe", "#c4b5fd", "#3b1a75"), "dark": ("#2e2557", "#6455a6", "#ede9fe")},
    {"light": ("#cffafe", "#67e8f9", "#0d4453"), "dark": ("#123e4a", "#2f8296", "#cffafe")},
    {"light": ("#ecfccb", "#bef264", "#2b4310"), "dark": ("#2b3d16", "#61812c", "#ecfccb")},
    {"light": ("#ffedd5", "#fdba74", "#6a250d"), "dark": ("#472a14", "#8e5a2b", "#ffedd5")},
    {"light": ("#fae8ff", "#e879f9", "#5c1462"), "dark": ("#43164a", "#8f4499", "#fae8ff")},
    {"light": ("#ccfbf1", "#5eead4", "#0d423e"), "dark": ("#123f3b", "#2f7f77", "#ccfbf1")},
)


# ==========================================================================
# עזרי טקסט
# ==========================================================================
def pad(s: str, width: int, align: str = "left") -> str:
    """
    מרפד מחרוזת לרוחב קבוע *בספירת תווים* (עברית = תו ברוחב אחד).

    אם המחרוזת ארוכה מהתא — חותכים ומוסיפים '…' כדי שהעמודות לא יזוזו.
    align: "left" (ברירת מחדל) / "right" / "center".
    """
    text = "" if s is None else str(s)
    # תווי בקרה הורסים יישור בטבלה — מנטרלים אותם מראש.
    text = text.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    if width <= 0:
        return ""
    if len(text) > width:
        text = text[: width - 1] + "…" if width > 1 else text[:width]
    fill = " " * (width - len(text))
    if align == "right":
        return fill + text
    if align == "center":
        half = len(fill) // 2
        return fill[:half] + text + fill[half:]
    return text + fill


def _floor_to_slot(minutes: int) -> int:
    """מעגל כלפי מטה למשבצת רבע שעה. 8:20 -> 8:15."""
    return (minutes // SLOT_MINUTES) * SLOT_MINUTES


def _ceil_to_slot(minutes: int) -> int:
    """מעגל כלפי מעלה למשבצת רבע שעה. 9:50 -> 10:00."""
    return -((-minutes) // SLOT_MINUTES) * SLOT_MINUTES


def _time_range(m: Meeting) -> str:
    """'08:30-10:00'."""
    return f"{fmt_time(m.start)}-{fmt_time(m.end)}"


def _where(m: Meeting) -> str:
    """'בניין 8 חדר 205' — ריק אם אין נתוני מיקום."""
    return f"{m.building} {m.room}".strip()


def _pairs(sched: ScoredSchedule) -> list[tuple[Group, Meeting]]:
    """כל המפגשים במערכת יחד עם הקבוצה שאליה הם שייכים, ממוינים לפי יום ואז שעה."""
    out = [(g, m) for g in sched.selection.groups for m in g.meetings]
    out.sort(key=lambda gm: (gm[1].day, gm[1].start, gm[1].end, gm[0].course_code))
    return out


def _course_name(courses: dict[str, Course], code: str) -> str:
    """שם הקורס מהמילון, ואם אינו מוכר — הקוד עצמו (לא נופלים על KeyError)."""
    course = courses.get(code)
    return course.name if course is not None else code


def _course_credits(courses: dict[str, Course], code: str) -> float:
    course = courses.get(code)
    return float(course.credits) if course is not None else 0.0


def _grid_bounds(meetings: list[Meeting]) -> tuple[int, int]:
    """
    גבולות הרשת: מהמפגש המוקדם ביותר ועד המאוחר ביותר, מעוגל למשבצות של רבע שעה.
    אם אין מפגשים בכלל — חלון ברירת מחדל 08:00-18:00.
    """
    if not meetings:
        return DEFAULT_DAY_START, DEFAULT_DAY_END
    start = _floor_to_slot(min(m.start for m in meetings))
    end = _ceil_to_slot(max(m.end for m in meetings))
    if end <= start:  # הגנה מפני נתונים משובשים
        end = start + SLOT_MINUTES
    return start, end


def _sorted_groups(groups: list[Group]) -> list[Group]:
    """מיון קבוצות לתצוגה: לפי סדר הרכיבים (הרצאה, תרגול, מעבדה...) ואז לפי מספר קבוצה."""
    order = {k: i for i, k in enumerate(KIND_ORDER)}
    return sorted(groups, key=lambda g: (order.get(g.kind, 99), g.kind, g.group_id))


# ==========================================================================
# צבע קבוע לכל קורס
# ==========================================================================
def course_color(code: str) -> int:
    """
    ממפה קוד קורס לאינדקס בפלטה (0..9) בצורה יציבה.

    משתמשים ב-crc32 ולא ב-hash() המובנה, כי hash() של מחרוזות ב-Python
    מקבל seed אקראי בכל הרצה — הצבעים היו מתחלפים בכל פעם.
    """
    return zlib.crc32(str(code).strip().encode("utf-8")) % len(PALETTE)


def build_color_map(codes) -> dict[str, int]:
    """
    {course_code: palette_index} לכל הקורסים.

    בסיס הבחירה הוא course_color(), אבל אם שני קורסים מתנגשים על אותו גוון
    אנחנו "מדלגים" לגוון הפנוי הבא (linear probing) בסדר קודים קבוע —
    כך אותו קורס מקבל תמיד אותו צבע בכל המערכות שבקובץ.
    """
    mapping: dict[str, int] = {}
    used: set[int] = set()
    for code in sorted({str(c) for c in codes}):
        idx = course_color(code)
        if len(used) < len(PALETTE):  # יש עדיין גוון פנוי — מחפשים אותו
            for step in range(len(PALETTE)):
                candidate = (idx + step) % len(PALETTE)
                if candidate not in used:
                    idx = candidate
                    break
        mapping[code] = idx
        used.add(idx)
    return mapping


# ==========================================================================
# 1. תצוגת טרמינל
# ==========================================================================
def _cell_lines(group: Group, meeting: Meeting, courses: dict[str, Course]) -> list[str]:
    """
    השורות שייכתבו בתוך בלוק המפגש בטרמינל, לפי סדר חשיבות.
    בלוק בן חצי שעה יראה רק את השורה הראשונה, בלוק בן שעתיים יראה את כולן.
    """
    lines = [
        _course_name(courses, group.course_code),
        f"{group.course_code} {group.kind} קב'{group.group_id}",
    ]
    if group.lecturer.strip():
        lines.append(group.lecturer.strip())
    where = _where(meeting)
    if where:
        lines.append(where)
    # שורת הסיום מסמנת עד מתי המפגש נמשך. בלי זה, משבצות ריקות בסוף הבלוק
    # נראות כאילו השיעור נגמר מוקדם — במיוחד ברשת של רבע שעה.
    lines.append(f"└ עד {fmt_time(meeting.end)}")
    return lines


def _fill_lines(lines: list[str], span: int) -> list[str]:
    """
    פורש את שורות הבלוק על פני ``span`` משבצות.

    השורה האחרונה ("└ עד HH:MM") מוצמדת תמיד לתחתית הבלוק, וכל מה שביניהן
    מרופד בקו המשך '│' כדי שאורך השיעור ייראה בבירור ברשת.
    """
    if span <= 0:
        return []
    if span == 1:
        return lines[:1]
    body, tail = lines[:-1], lines[-1]
    body = body[: span - 1]
    filler = ["│"] * (span - 1 - len(body))
    return body + filler + [tail]


def render_terminal(sched: ScoredSchedule, courses: dict[str, Course]) -> str:
    """
    מציירת מערכת שבועית אחת כטקסט מיושר (monospace) להדפסה למסך.

    העמודות הן ששת הימים כאותיות א..ו, פרושות **משמאל לימין** (ראו הערת ה-RTL
    בראש הקובץ), והשורות הן משבצות של 30 דקות מהמפגש המוקדם ועד המאוחר.
    ימים שאין בהם שיעורים כלל מושמטים כדי לא לבזבז רוחב מסך.
    מחזירה מחרוזת אחת (ללא הדפסה) — מי שמדפיס אותה חייב stdout ב-UTF-8.
    """
    pairs = _pairs(sched)
    out: list[str] = [sched.summary()]

    if not pairs:
        out.append("אין מפגשים להצגה (no meetings to display).")
        return "\n".join(out)

    days = sorted({m.day for _, m in pairs})
    grid_start, grid_end = _grid_bounds([m for _, m in pairs])
    n_slots = (grid_end - grid_start) // SLOT_MINUTES

    # ---- מילוי התאים ----------------------------------------------------
    # cells[(row, day)] = טקסט התא. תא ריק = מחרוזת ריקה.
    cells: dict[tuple[int, int], str] = {}
    clashes: list[str] = []
    # מי כבר תופס כל תא — כדי להבדיל בין התנגשות אמיתית לבין ארטיפקט של עיגול לרשת.
    occupants: dict[tuple[int, int], list[Meeting]] = {}
    for group, meeting in pairs:
        r0 = (_floor_to_slot(meeting.start) - grid_start) // SLOT_MINUTES
        r1 = max(r0 + 1, (_ceil_to_slot(meeting.end) - grid_start) // SLOT_MINUTES)
        r0 = max(0, min(r0, n_slots - 1))
        r1 = max(r0 + 1, min(r1, n_slots))
        lines = _fill_lines(_cell_lines(group, meeting, courses), r1 - r0)
        reported = False
        for i in range(r1 - r0):
            key = (r0 + i, meeting.day)
            text = lines[i] if i < len(lines) else ""
            here = occupants.setdefault(key, [])
            # התנגשות אמיתית = חפיפה בפועל בין טווחי הזמן, לא רק נפילה לאותו תא.
            # מפגש 08:30-10:15 ומפגש 10:15-12:00 חולקים גבול ואינם מתנגשים.
            real_clash = any(meeting.overlaps(other) for other in here)
            if key in cells and cells[key].strip():
                if real_clash:
                    if not reported:
                        clashes.append(f"התנגשות: {group.label()} ב{str(meeting)}")
                        reported = True
                    # רוחב שמור: רווח מוביל אחד מתווסף בשלב הציור, ועוד ' !' בסוף.
                    cells[key] = pad(cells[key], CELL_WIDTH - 3) + " !"
                # אחרת: שכנות בלבד — התא כבר צויר, משאירים אותו כמו שהוא.
            else:
                cells[key] = text
            here.append(meeting)

    # ---- כותרת וקווים ---------------------------------------------------
    header = pad("שעה", TIME_WIDTH, align="center") + "│"
    header += "│".join(
        pad(f" {DAY_LETTERS_HE[d]} {DAY_NAMES_HE[d]}", CELL_WIDTH) for d in days
    )
    header += "│"
    rule = "─" * TIME_WIDTH + "┼" + "┼".join("─" * CELL_WIDTH for _ in days) + "┼"

    out.append("")
    out.append(header)
    out.append(rule)

    for row in range(n_slots):
        t0 = grid_start + row * SLOT_MINUTES
        label = f"{fmt_time(t0)}-{fmt_time(t0 + SLOT_MINUTES)}"
        line = pad(label, TIME_WIDTH) + "│"
        line += "│".join(pad(" " + cells.get((row, d), ""), CELL_WIDTH) for d in days)
        out.append(line + "│")

    out.append(rule.replace("┼", "┴"))

    if clashes:
        out.append("")
        out.append("שימו לב — נמצאו חפיפות בתצוגה (overlaps found):")
        out.extend("  " + c for c in clashes)

    # ---- מקרא הקורסים ---------------------------------------------------
    out.append("")
    out.append("מקרא (legend):")
    by_course: dict[str, list[Group]] = {}
    for group in sched.selection.groups:
        by_course.setdefault(group.course_code, []).append(group)
    total_credits = 0.0
    for code in sorted(by_course):
        credits = _course_credits(courses, code)
        total_credits += credits
        out.append(f"  {code} · {_course_name(courses, code)} · {credits:g} נ\"ז")
        for group in _sorted_groups(by_course[code]):
            who = group.lecturer.strip() or UNKNOWN_LECTURER_HE
            times = " | ".join(str(m) for m in group.meetings) or "ללא מפגשים"
            out.append(f"      {pad(group.kind, 6)} קב' {pad(group.group_id, 4)} · {who} · {times}")
    out.append(f"  סה\"כ {len(by_course)} קורסים, {total_credits:g} נ\"ז.")

    # ---- הערת RTL -------------------------------------------------------
    out.append("")
    out.append(
        "הערה: הטרמינל בחלונות לא מיישר עברית מימין לשמאל, ולכן העמודות כאן "
        "פרושות משמאל לימין (א..ו)."
    )
    out.append(
        "התצוגה הנכונה ב-RTL היא קובץ ה-HTML — כדאי לפתוח אותו בדפדפן. "
        "(The HTML view is the properly right-to-left one.)"
    )
    return "\n".join(out)


# ==========================================================================
# 2. תפריט בחירת מרצים (שלב 4)
# ==========================================================================
def render_lecturer_menu(course: Course) -> str:
    """
    בונה את התפריט הממוספר שהסטודנטית רואה בשלב בחירת המרצים.

    לכל מרצה בקורס: שורה ממוספרת (החל מ-1), ומתחתיה כל הקבוצות שהוא/היא
    מלמד/ת — סוג הרכיב, מספר הקבוצה, וכל המפגשים (יום ושעות).
    המספרים כאן הם בדיוק מה שהסטודנטית תקליד בהמשך ("1,3").
    מחזירה מחרוזת רגילה, בלי הדפסה ובלי קלט.
    """
    lines: list[str] = []
    credits = f"{float(course.credits):g}"
    lines.append(f"קורס {course.code} — {course.name} ({credits} נ\"ז)")

    # קיבוץ הקבוצות לפי מרצה. מרצה ללא שם מקבל מקום אחרון ברשימה.
    by_lecturer: dict[str, list[Group]] = {}
    for group in course.groups:
        by_lecturer.setdefault(group.lecturer.strip() or UNKNOWN_LECTURER_HE, []).append(group)

    named = [name for name in sorted(by_lecturer) if name != UNKNOWN_LECTURER_HE]
    ordered = named + ([UNKNOWN_LECTURER_HE] if UNKNOWN_LECTURER_HE in by_lecturer else [])

    if not ordered:
        lines.append("  אין בקורס הזה אף קבוצה פתוחה (no groups found).")
        lines.append("")
        lines.append("Enter = להמשיך בלי העדפה  (press Enter to continue)")
        return "\n".join(lines)

    lines.append(f"מרצים זמינים: {len(ordered)}")
    for i, name in enumerate(ordered, start=1):
        # הרכיבים שהמרצה מלמד/ת, לדוגמה "הרצאה + תרגול"
        kinds = " + ".join(dict.fromkeys(g.kind for g in _sorted_groups(by_lecturer[name])))
        lines.append(f"  {i}. {name}  [{kinds}]")
        for group in _sorted_groups(by_lecturer[name]):
            times = " | ".join(str(m) for m in group.meetings) or "ללא מפגשים"
            lines.append(f"       {pad(group.kind, 6)} קב' {pad(group.group_id, 4)} — {times}")
            if group.note.strip():
                lines.append(f"       הערה: {group.note.strip()}")

    lines.append("")
    lines.append(
        'יש לדרג לפי סדר העדפה, למשל "1,3" (הראשון = הכי מועדף) · '
        "Enter ריק או \"any\" = אין העדפה · q = יציאה"
    )
    lines.append('(type "1,3" to rank, Enter for no preference, q to quit)')
    return "\n".join(lines)


# ==========================================================================
# 3. תצוגת HTML — קובץ עצמאי אחד, RTL
# ==========================================================================
def _e(value) -> str:
    """בריחת HTML לכל טקסט דינמי (שמות מרצים, הערות מהידיעון וכו')."""
    return _htmlmod.escape("" if value is None else str(value), quote=True)


def _palette_vars(mode: str, indent: str) -> str:
    """מייצר את שורות ה-CSS custom properties של הפלטה עבור 'light' או 'dark'."""
    rows = []
    for i, entry in enumerate(PALETTE):
        bg, border, fg = entry[mode]
        rows.append(f"{indent}--c{i}-bg:{bg}; --c{i}-bd:{border}; --c{i}-fg:{fg};")
    return "\n".join(rows)


def _css() -> str:
    """
    כל ה-CSS של הדף, כמחרוזת אחת.

    שלושה עקרונות:
    1. אין שום בקשה חיצונית — אין CDN, אין @import, אין גופן שנטען מהרשת.
       רק גופני מערכת: "Segoe UI" (חלונות), "Arial Hebrew" (מק), Arial, sans-serif.
    2. כל הצבעים מוגדרים קודם כמשתנים על :root (מצב בהיר), ורק אחר כך נדרסים
       ב-prefers-color-scheme: dark — כך אין צבע ש"קיים רק במצב אחד".
    3. גיליון הדפסה נפרד: מערכת אחת לכל עמוד A4 לרוחב.
    """
    return f"""
:root {{
  color-scheme: light dark;
  --bg:#f4f6f9;
  --panel:#ffffff;
  --ink:#1b232e;
  --muted:#5b6674;
  --line:#dde2e9;
  --line-strong:#b8c0cc;
  --accent:#245ea8;
  --chip:#eef1f5;
  --slot-h:22px;
  --time-col:4.8rem;
{_palette_vars("light", "  ")}
}}

@media (prefers-color-scheme: dark) {{
  :root {{
    --bg:#11151b;
    --panel:#1a2028;
    --ink:#e6eaf1;
    --muted:#98a3b2;
    --line:#2a323d;
    --line-strong:#3d4855;
    --accent:#7fb2f2;
    --chip:#222a34;
{_palette_vars("dark", "    ")}
  }}
}}

* {{ box-sizing:border-box; }}

body {{
  margin:0;
  background:var(--bg);
  color:var(--ink);
  font-family:"Segoe UI","Arial Hebrew",Arial,sans-serif;
  font-size:14px;
  line-height:1.45;
}}

.wrap {{ max-width:1180px; margin:0 auto; padding:20px 18px 40px; }}

h1 {{ font-size:22px; margin:0 0 4px; }}
h2 {{ font-size:17px; margin:0 0 2px; }}
h3 {{ font-size:14px; margin:18px 0 6px; color:var(--muted); font-weight:600; }}

.meta {{ color:var(--muted); font-size:12px; margin:0 0 18px; }}

.sched {{
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:12px;
  padding:16px 18px 20px;
  margin-bottom:26px;
}}

.summary {{ color:var(--muted); font-size:13px; margin:0 0 12px; }}

/* ---- שבבי המקרא (צבע לכל קורס) ---- */
.chips {{ display:flex; flex-wrap:wrap; gap:6px; margin:0 0 12px; }}
.chip {{
  font-size:11.5px; padding:2px 8px; border-radius:999px;
  border:1px solid; line-height:1.6;
}}

/* ---- הרשת השבועית ---- */
/* dir="rtl" על ה-html גורם לעמודה 1 (השעות) לשבת מימין,
   ואחריה הימים א..ו נפרשים שמאלה — בדיוק כמו מערכת שעות ישראלית. */
.grid {{
  display:grid;
  grid-template-columns:var(--time-col) repeat(6,1fr);
  border:1px solid var(--line-strong);
  border-radius:10px;
  overflow:hidden;
  background:var(--panel);
}}
.hd {{
  padding:6px 4px; text-align:center; font-weight:700; font-size:12.5px;
  background:var(--chip); border-bottom:1px solid var(--line-strong);
}}
.hd .dayname {{ display:block; font-weight:400; font-size:10.5px; color:var(--muted); }}
.tl {{
  font-size:10.5px; color:var(--muted); text-align:center;
  border-top:1px dotted var(--line); padding-top:1px;
}}
.tl.hour {{ border-top:1px solid var(--line-strong); color:var(--ink); }}
.slot {{ border-top:1px dotted var(--line); border-inline-start:1px solid var(--line); }}
.slot.hour {{ border-top:1px solid var(--line-strong); }}

.ev {{
  margin:1.5px; padding:3px 5px; border-radius:7px;
  border:1px solid; overflow:hidden; z-index:1;
  display:flex; flex-direction:column; gap:1px;
  font-size:11px;
}}
.ev b {{ font-size:11.5px; font-weight:700; }}
.ev span {{ opacity:.92; }}
.ltr {{ direction:ltr; unicode-bidi:isolate; }}

/* ---- טבלאות ---- */
table {{ border-collapse:collapse; width:100%; font-size:12.5px; }}
th, td {{ border:1px solid var(--line); padding:4px 7px; text-align:right; }}
th {{ background:var(--chip); font-weight:600; }}
tfoot td {{ font-weight:700; background:var(--chip); }}
.num {{ text-align:center; }}
.swatch {{
  display:inline-block; width:10px; height:10px; border-radius:3px;
  border:1px solid; margin-inline-start:6px; vertical-align:middle;
}}
footer {{ color:var(--muted); font-size:11.5px; margin-top:8px; }}

/* ---- הדפסה: מערכת אחת לכל עמוד ---- */
@page {{ size:A4 landscape; margin:10mm; }}

@media print {{
  :root {{
    --bg:#ffffff; --panel:#ffffff; --ink:#000000; --muted:#444444;
    --line:#c9ced6; --line-strong:#8b939e; --accent:#14406f; --chip:#f1f3f6;
    --slot-h:17px;
{_palette_vars("light", "    ")}
  }}
  body {{ background:#fff; font-size:11.5px; }}
  .wrap {{ max-width:none; padding:0; }}
  .sched {{
    border:none; border-radius:0; padding:0; margin:0;
    break-after:page; page-break-after:always; break-inside:avoid;
  }}
  .sched:last-of-type {{ break-after:auto; page-break-after:auto; }}
  .ev, .chip, .hd, th, tfoot td {{
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  .noprint {{ display:none !important; }}
}}
""".strip()


def _grid_html(
    sched: ScoredSchedule,
    courses: dict[str, Course],
    colors: dict[str, int],
    grid_start: int,
    n_slots: int,
) -> str:
    """הרשת השבועית עצמה כ-CSS grid: כותרות ימים, תוויות שעה, משבצות רקע, ובלוקי מפגש."""
    parts: list[str] = []
    parts.append(
        f'<div class="grid" style="grid-template-rows:auto repeat({n_slots},var(--slot-h))">'
    )
    # שורה 1: פינת "שעה" + כותרות הימים.
    parts.append('<div class="hd" style="grid-column:1;grid-row:1">שעה</div>')
    for day in DAYS:
        parts.append(
            f'<div class="hd" style="grid-column:{day + 1};grid-row:1">'
            f"{_e(DAY_LETTERS_HE[day])}<span class=\"dayname\">{_e(DAY_NAMES_HE[day])}</span></div>"
        )

    # תוויות השעה (עמודה 1) + משבצות רקע לכל יום.
    for row in range(n_slots):
        t0 = grid_start + row * SLOT_MINUTES
        hour_cls = " hour" if t0 % 60 == 0 else ""
        parts.append(
            f'<div class="tl{hour_cls}" style="grid-column:1;grid-row:{row + 2}">'
            f'<span class="ltr">{fmt_time(t0)}</span></div>'
        )
        for day in DAYS:
            parts.append(
                f'<div class="slot{hour_cls}" style="grid-column:{day + 1};grid-row:{row + 2}"></div>'
            )

    # בלוקי המפגשים — מונחים מעל משבצות הרקע לפי יום ושעה.
    for group, meeting in _pairs(sched):
        r0 = (_floor_to_slot(meeting.start) - grid_start) // SLOT_MINUTES
        r1 = max(r0 + 1, (_ceil_to_slot(meeting.end) - grid_start) // SLOT_MINUTES)
        r0 = max(0, min(r0, n_slots - 1))
        r1 = max(r0 + 1, min(r1, n_slots))
        cls = f"c{colors.get(group.course_code, course_color(group.course_code))}"
        who = group.lecturer.strip() or UNKNOWN_LECTURER_HE
        where = _where(meeting)
        body = [
            f"<b>{_e(_course_name(courses, group.course_code))}</b>",
            f"<span>{_e(group.kind)} · קב' {_e(group.group_id)}</span>",
            f'<span class="ltr">{_e(_time_range(meeting))}</span>',
            f"<span>{_e(who)}</span>",
        ]
        if where:
            body.append(f"<span>{_e(where)}</span>")
        parts.append(
            f'<div class="ev {cls}" style="grid-column:{meeting.day + 1};'
            f'grid-row:{r0 + 2}/{r1 + 2};'
            f"background:var(--{cls}-bg);border-color:var(--{cls}-bd);color:var(--{cls}-fg)\">"
            + "".join(body)
            + "</div>"
        )

    parts.append("</div>")
    return "\n".join(parts)


def _chips_html(sched: ScoredSchedule, courses: dict[str, Course], colors: dict[str, int]) -> str:
    """שורת שבבים צבעוניים — איזה צבע שייך לאיזה קורס."""
    codes = sorted(sched.selection.course_codes())
    if not codes:
        return ""
    chips = []
    for code in codes:
        cls = f"c{colors.get(code, course_color(code))}"
        chips.append(
            f'<span class="chip" style="background:var(--{cls}-bg);'
            f'border-color:var(--{cls}-bd);color:var(--{cls}-fg)">'
            f"{_e(code)} {_e(_course_name(courses, code))}</span>"
        )
    return '<div class="chips">' + "".join(chips) + "</div>"


def _courses_table_html(
    sched: ScoredSchedule, courses: dict[str, Course], colors: dict[str, int]
) -> str:
    """טבלת הקורסים: איזו קבוצה נבחרה לכל רכיב, אצל מי, ובכמה נקודות זכות."""
    by_course: dict[str, list[Group]] = {}
    for group in sched.selection.groups:
        by_course.setdefault(group.course_code, []).append(group)

    rows: list[str] = []
    total_credits = 0.0
    total_minutes = 0
    for code in sorted(by_course):
        credits = _course_credits(courses, code)
        total_credits += credits
        groups = _sorted_groups(by_course[code])
        cls = f"c{colors.get(code, course_color(code))}"
        for i, group in enumerate(groups):
            total_minutes += group.total_minutes()
            times = (
                " · ".join(
                    f"{DAY_LETTERS_HE.get(m.day, '?')} "
                    f'<span class="ltr">{_e(_time_range(m))}</span>'
                    + (f" ({_e(_where(m))})" if _where(m) else "")
                    for m in sorted(group.meetings, key=lambda m: (m.day, m.start))
                )
                or "—"
            )
            # שם הקורס ונ"ז מופיעים רק בשורה הראשונה של כל קורס.
            if i == 0:
                swatch = (
                    f'<span class="swatch" style="background:var(--{cls}-bg);'
                    f'border-color:var(--{cls}-bd)"></span>'
                )
                first = f"{_e(code)} {_e(_course_name(courses, code))}{swatch}"
                cred = f"{credits:g}"
            else:
                first = ""
                cred = ""
            rows.append(
                "<tr>"
                f"<td>{first}</td>"
                f"<td>{_e(group.kind)}</td>"
                f'<td class="num">{_e(group.group_id)}</td>'
                f"<td>{_e(group.lecturer.strip() or UNKNOWN_LECTURER_HE)}</td>"
                f"<td>{times}</td>"
                f'<td class="num">{cred}</td>'
                "</tr>"
            )

    hours = total_minutes / 60.0
    return (
        "<h3>הקורסים והקבוצות שנבחרו</h3>"
        "<table><thead><tr>"
        "<th>קורס</th><th>רכיב</th><th>קבוצה</th><th>מרצה</th><th>מפגשים</th><th>נ\"ז</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody><tfoot><tr>"
        f'<td colspan="4">סה"כ {len(by_course)} קורסים</td>'
        f"<td>{hours:g} שעות שבועיות</td>"
        f'<td class="num">{total_credits:g}</td>'
        "</tr></tfoot></table>"
    )


def _score_table_html(sched: ScoredSchedule) -> str:
    """פירוק הניקוד: כל רכיב, הערך שלו, והמספרים הגולמיים שמאחוריו."""
    rows: list[str] = []
    for key, value in sched.breakdown.items():
        label = BREAKDOWN_LABELS_HE.get(key, key)
        rows.append(
            f"<tr><td>{_e(label)}</td>"
            f'<td class="num"><span class="ltr">{value:.2f}</span></td></tr>'
        )
    days_letters = "".join(
        DAY_LETTERS_HE[d] for d in sorted(sched.selection.days_used()) if d in DAY_LETTERS_HE
    )
    extras = [
        ("ימים בקמפוס", f"{sched.days_count} ({days_letters})"),
        ("סה\"כ חורים", f"{sched.gap_minutes // 60}:{sched.gap_minutes % 60:02d} שעות"),
        ("מרצים מועדפים שהתקבלו", f"{sched.lecturer_hits}/{sched.lecturer_total}"),
    ]
    for label, value in extras:
        rows.append(f"<tr><td>{_e(label)}</td><td class=\"num\">{_e(value)}</td></tr>")
    return (
        "<h3>פירוק הניקוד</h3>"
        "<table><thead><tr><th>רכיב</th><th>ערך</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody><tfoot><tr><td>ניקוד סופי</td>"
        f'<td class="num"><span class="ltr">{sched.score:.2f}</span></td>'
        "</tr></tfoot></table>"
    )


def render_html(
    scheds: list[ScoredSchedule],
    courses: dict[str, Course],
    out_path: str,
    title: str = "מערכת שעות",
) -> str:
    """
    כותבת קובץ HTML **עצמאי אחד** עם כל המערכות המוצעות, ומחזירה את out_path.

    מאפיינים:
      * dir="rtl" lang="he", charset=utf-8, ומחסנית גופני מערכת בלבד —
        אין שום בקשה לרשת (אין CDN, אין Google Fonts). הקובץ עובד גם אופליין.
      * לכל מערכת: שורת סיכום ניקוד, רשת שבועית (CSS grid) שבה ששת הימים
        פרושים מימין לשמאל והשורות הן משבצות של 30 דקות,
        טבלת קורסים/קבוצות/מרצים/נ"ז, וטבלת פירוק ניקוד.
      * צבע פסטלי קבוע לכל קוד קורס — אותו קורס = אותו צבע בכל המערכות.
      * מצב בהיר וכהה לפי prefers-color-scheme, וגיליון הדפסה של מערכת לעמוד.

    כל המערכות משתמשות באותו חלון שעות (המוקדם והמאוחר ביותר מכולן),
    כדי שאפשר יהיה להשוות ביניהן במבט אחד.
    """
    scheds = list(scheds or [])

    # חלון שעות משותף לכל המערכות.
    all_meetings = [m for s in scheds for _, m in _pairs(s)]
    grid_start, grid_end = _grid_bounds(all_meetings)
    n_slots = max(1, (grid_end - grid_start) // SLOT_MINUTES)

    # מפת צבעים יציבה: כל הקודים שאנחנו מכירים, לא רק אלה שנבחרו.
    codes = {g.course_code for s in scheds for g in s.selection.groups} | set(courses)
    colors = build_color_map(codes)

    stamp = datetime.now().strftime("%d/%m/%Y %H:%M")
    body: list[str] = [
        f"<h1>{_e(title)}</h1>",
        f'<p class="meta">נוצר ב-{_e(stamp)} · {len(scheds)} הצעות · '
        "הרשת מסודרת מימין לשמאל: העמודה הימנית היא השעה, ואחריה ימים א׳–ו׳.</p>",
    ]

    if not scheds:
        body.append(
            '<div class="sched"><h2>לא נמצאו מערכות</h2>'
            "<p>לא הועברו מערכות לתצוגה (no schedules to render).</p></div>"
        )
    for i, sched in enumerate(scheds, start=1):
        body.append('<section class="sched">')
        body.append(f"<h2>הצעה {i}</h2>")
        body.append(f'<p class="summary">{_e(sched.summary())}</p>')
        body.append(_chips_html(sched, courses, colors))
        body.append(_grid_html(sched, courses, colors, grid_start, n_slots))
        body.append(_courses_table_html(sched, courses, colors))
        body.append(_score_table_html(sched))
        body.append("</section>")

    body.append(
        '<footer class="noprint">נוצר על ידי SlotWise · '
        "קובץ עצמאי, ללא תלות באינטרנט · להדפסה: Ctrl+P (מערכת אחת בכל עמוד).</footer>"
    )

    doc = (
        "<!doctype html>\n"
        '<html lang="he" dir="rtl">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_e(title)}</title>\n"
        "<style>\n" + _css() + "\n</style>\n"
        "</head>\n"
        "<body>\n"
        '<main class="wrap">\n' + "\n".join(body) + "\n</main>\n"
        "</body>\n</html>\n"
    )

    # יצירת התיקייה אם צריך, וכתיבה ב-UTF-8 (חובה — התוכן עברי).
    folder = os.path.dirname(os.path.abspath(out_path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(doc)
    return out_path


# ==========================================================================
# הרצה ישירה — הדגמה קטנה על נתונים מומצאים (python src/render.py)
# ==========================================================================
if __name__ == "__main__":  # pragma: no cover
    import sys
    import tempfile

    from models import Selection

    # חלונות: בלי זה עברית ותווי מסגרת יתפוצצו בקונסולה.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError, OSError):
        pass

    demo_groups = [
        Group("61832", "11", "הרצאה", 'ד"ר כהן', [Meeting(1, 510, 600, "205", "בניין 8")]),
        Group("61832", "12", "תרגול", "מר לוי", [Meeting(3, 600, 660, "104", "בניין 3")]),
        Group("11069", "21", "תרגול", "גב' אברהם", [Meeting(1, 630, 720)]),
    ]
    demo_courses = {
        "61832": Course("61832", "מבוא להסתברות וסטטיסטיקה", 4.0, demo_groups[:2]),
        "11069": Course("11069", "אנגלית טכנית יישומית – תוכנה", 1.0, demo_groups[2:]),
    }
    demo_sel = Selection(demo_groups)
    demo = ScoredSchedule(
        selection=demo_sel,
        score=31.5,
        breakdown={"lecturer": 10.0, "days": 0.0, "gaps": -2.0, "compactness": -1.5},
        days_count=len(demo_sel.days_used()),
        gap_minutes=demo_sel.gap_minutes(),
        lecturer_hits=1,
        lecturer_total=2,
    )

    print(render_terminal(demo, demo_courses))
    print()
    print(render_lecturer_menu(demo_courses["61832"]))
    demo_path = os.path.join(tempfile.gettempdir(), "render_demo.html")
    print()
    print("HTML demo ->", render_html([demo], demo_courses, demo_path, "הדגמה"))
