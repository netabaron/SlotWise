"""
cli.py — הזרימה האינטראקטיבית של SlotWise (סעיף 7 ב-docs/SPEC.md).

השלבים, בדיוק לפי הסדר שסוכם:
    1. טעינת הפרופיל (data/profile.json) ואישור שנה / סמסטר / מספר ימים רצוי.
    2. פתירת קודי הקורסים לסמסטר הזה מתוך הידיעון (data/curriculum.json).
    3. השגת נתוני הקבוצות: קאש (data/sections.json), סקרייפינג, או נתוני דמו.
    4. לכל קורס — הצגת המרצים ובקשת דירוג.
    5. בניית Preferences והרצת scheduler.solve.
    6. הדפסת המערכות הטובות לטרמינל, כתיבת HTML והצעה לפתוח אותו.
    7. אם אין פתרון — הצגת האבחון והצעות הרפיה, עם ניסיון חוזר אינטראקטיבי.

שני הכללים שמונעים מהמערכת להיות שגויה בשקט:
    • סמסטר — דף קורס בידיעון מציג את המפגשים של *שני* הסמסטרים באותו עמוד.
      הסמסטר המבוקש (student.term, למשל "א") מועבר לפרסר, וכל מפגש שאינו
      בסמסטר הזה מסונן החוצה לפני השיבוץ.
    • שנה אקדמית — הידיעון נפתח כברירת מחדל בשנה הקודמת. השנה המבוקשת
      (student.academic_year, למשל תשפ"ז) מתורגמת לשנה לועזית (2027) ומועברת
      לסקרייפר, שמחליף אותה במפורש ומאמת שההחלפה תפסה.

שני כללים נוספים, שנוספו יחד עם מסד הנתונים המתרענן (data/db):
    • תוכנית הלימודים אינה שער. קורסים חוזרים מסמסטרים קודמים, והרישום בפועל
      אינו זהה ל-PDF. אפשר לבחור *כל* קורס שנפתח בידיעון; curriculum.json
      משמש רק לשמות, נ"ז, קדם וצמידות. קורס מסמסטר אחר הוא מקרה רגיל לגמרי
      ומדווח כמידע ניטרלי ("נלקח כהשלמה"), לא כשגיאה.
    • גיל הנתונים גלוי תמיד. refresh.py מרענן את data/db פעם ביום, וכל ריצה
      מדפיסה מתי הנתונים עודכנו לאחרונה. נתונים ישנים שמוצגים כאילו הם
      עדכניים הם התקלה הגרועה ביותר — ולכן היא מקבלת תיבת אזהרה מפורשת.

כללי ברזל במודול הזה:
    • כל פתיחת קובץ עם encoding="utf-8" (Windows + עברית).
    • שום טיפול בסיסמאות. הן מוקלדות בדפדפן האמיתי בלבד.
    • כל הודעה למשתמש: עברית קודם, אנגלית בסוגריים (ובניסוח ניטרלי).

Technical note: this module is imported from `main.py`, which puts `src/` on
sys.path. Running `python src/cli.py` directly also works — the bootstrap
below adds `src/` to sys.path itself.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# sys.path bootstrap — so `from models import ...` works no matter how we ran.
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import curriculum as curriculum_mod  # noqa: E402  (import after sys.path fix)
import parser as parser_mod  # noqa: E402
import render as render_mod  # noqa: E402
import scheduler as scheduler_mod  # noqa: E402
from models import Course, Group  # noqa: E402

# ---------------------------------------------------------------------------
# נתיבים קבועים (absolute — never depend on the current working directory)
# ---------------------------------------------------------------------------
DATA_DIR = ROOT / "data"
PROFILE_PATH = DATA_DIR / "profile.json"
CURRICULUM_PATH = DATA_DIR / "curriculum.json"
SECTIONS_PATH = DATA_DIR / "sections.json"
#: רישום קטן לצד הקאש: לאיזה סמסטר ולאיזו שנה אקדמית הוא נבנה.
SECTIONS_META_PATH = DATA_DIR / "sections.meta.json"
RAW_DIR = DATA_DIR / "raw"
BROWSER_PROFILE_DIR = DATA_DIR / ".browser_profile"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "sample_sections.json"
DEFAULT_HTML_PATH = ROOT / "schedule.html"

#: מסד הנתונים המתרענן — refresh.py כותב לכאן פעם ביום (SPEC_AUTOREFRESH §1).
DB_ROOT = DATA_DIR / "db"
#: סקריפט הרענון, בשורש הפרויקט. מוזכר בכל מקום שבו הנתונים ישנים.
REFRESH_SCRIPT = ROOT / "refresh.py"

#: מעל כמה שעות נחשבים נתוני קורס "ישנים". זהה לברירת המחדל של store.py.
DEFAULT_MAX_AGE_HOURS = 24.0

#: כמה תוצאות חיפוש מציגים בכל פעם ב---pick.
PICK_RESULT_LIMIT = 20

#: מקסימום סבבי "ניסיון חוזר" אחרי חוסר פתרון (step 7).
MAX_RETRY_ROUNDS = 3

#: התווית שבה render.py מסמן קבוצות ללא שם מרצה. חייבת להיות זהה לשלו,
#: אחרת המספרים בתפריט לא יתאימו למה שמוקלד בפועל.
UNKNOWN_LECTURER_HE = getattr(render_mod, "UNKNOWN_LECTURER_HE", "מרצה לא ידוע")


class QuitRequested(Exception):
    """התקבלה בקשת יציאה ('q'), או שאין יותר קלט (EOF)."""


# ===========================================================================
# עזרי פלט וקלט (small I/O helpers)
# ===========================================================================
def ensure_utf8_stdout() -> None:
    """מוודא ש-stdout/stderr יודעים להדפיס עברית ב-Windows.

    Guarded: some streams (pipes in odd hosts, IDE consoles) are not
    reconfigurable, and that must never crash the program.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:
            pass


def print_box(title: str, lines: list[str], ch: str = "#") -> None:
    """מדפיס תיבת הודעה בולטת.

    Design note: we deliberately draw only the LEFT border. Hebrew text is
    right-to-left, so padding lines to a right-hand border makes the box look
    broken in most Windows terminals.
    """
    width = 74
    print()
    print(ch * width)
    print(f"{ch}{ch}  {title}")
    print(f"{ch}{ch}")
    for line in lines:
        print(f"{ch}{ch}  {line}")
    print(ch * width)
    print()


def ask(question: str, default: str = "") -> str:
    """שואל שאלה וקורא שורה. 'q' זורק QuitRequested, EOF גם כן."""
    try:
        raw = input(question).strip()
    except EOFError:
        # EOF כאן פירושו כמעט תמיד שהתוכנית רצה בלי מסוף אמיתי — למשל דרך
        # צינור, דרך משימה מתוזמנת, או דרך הרצת פקודה מתוך כלי אחר. הבחירה
        # האינטראקטיבית של המרצים פשוט לא יכולה לעבוד שם, ולכן עדיף להסביר
        # מה קרה מאשר "יוצאים" סתום.
        print("\nאין יותר קלט (EOF) — הקלט הסטנדרטי אינו מסוף אינטראקטיבי.")
        print("  הבחירה האינטראקטיבית של המרצים דורשת חלון מסוף אמיתי.")
        print("  יש לפתוח PowerShell / Terminal ולהריץ שם:")
        print(f"      cd {ROOT}")
        print("      python main.py --offline")
        print("  (run this in a real terminal window; stdin here is not a TTY)")
        raise QuitRequested from None
    if raw.lower() in {"q", "quit", "exit"} or raw in {"יציאה", "צא"}:
        raise QuitRequested
    return raw or default


def ask_yes_no(question: str, default: bool = False) -> bool:
    """שאלת כן/לא. מקבלת y/yes/כ/כן ו-n/no/ל/לא. Enter = ברירת המחדל."""
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        raw = ask(f"{question} {hint} ").lower()
        if not raw:
            return default
        if raw in {"y", "yes", "כן", "כ", "כן."}:
            return True
        if raw in {"n", "no", "לא", "ל"}:
            return False
        print("לא הבנתי. יש להקליד y או n. (please answer y or n)")


# ===========================================================================
# סמסטר ושנה אקדמית — התשתית שמונעת את שתי התקלות החמורות ביותר
# ===========================================================================
# (1) דף קורס בידיעון מציג את המפגשים של *שני* הסמסטרים באותו עמוד. העמודה
#     הראשונה בכל שורת מפגש היא הסמסטר ("א" / "ב" / "קיץ"). בלי סינון לפי
#     העמודה הזאת, מפגשים של סמסטר ב' יזלגו בשקט למערכת של סמסטר א'.
# (2) השנה האקדמית היא *מצב סשן* בידיעון, לא פרמטר ב-URL. הידיעון נפתח
#     כברירת מחדל בשנה הקודמת, ולכן חובה להחליף שנה במפורש ולאמת את
#     ההחלפה — אחרת מתקבלת בשקט המערכת של השנה שעברה.
#
# Technical note: the yedion's year <select> uses the GREGORIAN year in which
# the academic year ENDS, so תשפ"ז (2026/27) is the option whose value is 2027.

#: תרגום שנה עברית -> ערך ה-<option> בבורר השנה של הידיעון.
HEBREW_YEAR_TO_GREGORIAN: dict[str, str] = {
    'תשפ"ו': "2026",
    'תשפ"ז': "2027",
    'תשפ"ח': "2028",
}
#: הכיוון ההפוך — לתצוגה בלבד.
GREGORIAN_TO_HEBREW_YEAR: dict[str, str] = {
    greg: heb for heb, greg in HEBREW_YEAR_TO_GREGORIAN.items()
}

#: הסמסטרים כפי שהם מופיעים בעמודת "סמסטר" בידיעון.
SEMESTERS: tuple[str, ...] = ("א", "ב", "קיץ")
SEMESTER_LABELS: dict[str, str] = {"א": "א' (חורף)", "ב": "ב' (אביב)", "קיץ": "קיץ"}

#: קישור ישיר לדף קורס בידיעון, לבדיקה ידנית.
#: (docs/GROUND_TRUTH.md §1 — the search endpoint answers a plain GET.)
YEDION_COURSE_URL = (
    "https://info.braude.ac.il/yedion/fireflyweb.aspx"
    "?prgname=S_LOOK_FOR_NOSE&arguments=-N{code}"
)

#: שמות חריגות השנה של הסקרייפר. מזוהות לפי שם ולא ב-import, כי ייבוא של
#: scraper גורר את playwright — ואין סיבה לשלם את זה במצב --offline.
YEAR_ERROR_NAMES = frozenset({"YearSwitchError", "YearMismatchError"})

#: מודפסת פעם אחת בלבד, אם הפרסר המותקן אינו תומך בסינון סמסטר.
_SEMESTER_FILTER_WARNED = False


class TargetTermError(ValueError):
    """היעד (סמסטר / שנה אקדמית) אינו ברור — ומוטב לעצור מאשר לנחש."""


class UnknownAcademicYearError(TargetTermError):
    """שנה אקדמית שאין לנו תרגום שלה לערך של בורר השנה בידיעון."""


def _plain_quotes(text: str) -> str:
    """מאחד גרשיים עבריים וטיפוגרפיים לגרשיים רגילים, כדי שהשוואות יעבדו."""
    out = str(text)
    for fancy, plain in (
        ("\u05f4", '"'), ("\u05f3", "'"),      # גרשיים / גרש עבריים
        ("\u201c", '"'), ("\u201d", '"'),      # typographic double quotes
        ("\u2018", "'"), ("\u2019", "'"),      # typographic single quotes
    ):
        out = out.replace(fancy, plain)
    return out


def _year_key(text: str) -> str:
    """מפתח השוואה לשנה עברית: בלי רווחים ובלי גרשיים. תשפ"ז -> תשפז."""
    return re.sub(r"[\s\"']", "", _plain_quotes(text))


def hebrew_year_to_gregorian(label: str) -> str:
    """תשפ"ז -> "2027". מחרוזת של 4 ספרות מוחזרת כמו שהיא.

    לעולם לא מנחשים: שנה לא מוכרת מפילה UnknownAcademicYearError, כי מערכת
    שעות של השנה הלא נכונה גרועה בהרבה מהודעת שגיאה.
    """
    raw = _plain_quotes(label).strip()
    if re.fullmatch(r"\d{4}", raw):
        return raw
    key = _year_key(raw)
    for heb, greg in HEBREW_YEAR_TO_GREGORIAN.items():
        if _year_key(heb) == key:
            return greg
    known = ", ".join(HEBREW_YEAR_TO_GREGORIAN)
    raise UnknownAcademicYearError(
        f"שנה אקדמית לא מוכרת: {label!r}. "
        f"הכלי יודע לתרגם רק את {known}, או שנה לועזית בת 4 ספרות (2027). "
        "אפשר לציין אותה במפורש בשורת הפקודה: --year 2027. "
        "(unknown academic year — refusing to guess)"
    )


def hebrew_year_label(gregorian: str) -> str:
    """מהשנה הלועזית לתווית העברית: "2027" -> תשפ"ז. "" אם אינה מוכרת."""
    return GREGORIAN_TO_HEBREW_YEAR.get(str(gregorian).strip(), "")


def previous_year_label(gregorian: str) -> str:
    """התווית העברית של השנה שלפני — זו שהידיעון נפתח בה כברירת מחדל."""
    try:
        return hebrew_year_label(str(int(str(gregorian).strip()) - 1))
    except (TypeError, ValueError):
        return ""


def semester_geresh(semester: str) -> str:
    """"א" -> "א'" (עם גרש), "קיץ" -> "קיץ". לשימוש בתוך משפט."""
    return f"{semester}'" if semester in {"א", "ב"} else str(semester)


def semester_label(semester: str) -> str:
    """"א" -> "א' (חורף)" — לתצוגה מלאה."""
    return SEMESTER_LABELS.get(semester, str(semester))


def _normalize_semester_local(text: str) -> str:
    """זיהוי סמסטר מקומי — גיבוי אם parser.normalize_semester אינו קיים."""
    raw = _plain_quotes(text).strip()
    if not raw:
        return ""
    if "קיץ" in raw:
        return "קיץ"
    if "חורף" in raw:
        return "א"
    if "אביב" in raw:
        return "ב"
    # אות עברית בודדת שאינה חלק ממילה: "סמסטר א'" -> "א".
    m = re.search(r"(?<![א-ת])([אבג])(?![א-ת])", raw)
    if m:
        return {"א": "א", "ב": "ב", "ג": "קיץ"}[m.group(1)]
    m = re.search(r"(?<!\d)([123])(?!\d)", raw)
    if m:
        return {"1": "א", "2": "ב", "3": "קיץ"}[m.group(1)]
    return ""


def normalize_semester(text: str) -> str:
    """מנרמל טקסט סמסטר ל-"א" / "ב" / "קיץ", או "" אם לא זוהה.

    ההיגיון הקנוני יושב ב-parser.normalize_semester; כאן רק מעדיפים אותו,
    ונופלים לזיהוי מקומי אם גרסת הפרסר שמותקנת עדיין לא חושפת אותו.
    """
    fn = getattr(parser_mod, "normalize_semester", None)
    if callable(fn):
        try:
            out = str(fn(text) or "").strip()
        except Exception:
            out = ""
        if out in SEMESTERS:
            return out
    return _normalize_semester_local(text)


def resolve_semester(profile: dict, override: str | None = None) -> str:
    """הסמסטר שלפיו מסננים מפגשים: --semester אם ניתן, אחרת student.term."""
    if override:
        sem = normalize_semester(override)
        if sem:
            return sem
        raise TargetTermError(
            f"סמסטר לא מוכר: {override!r}. ערכים חוקיים: {', '.join(SEMESTERS)}. "
            "(unknown semester)"
        )
    student = profile.get("student", {}) or {}
    for key in ("term", "term_label", "semester"):
        sem = normalize_semester(student.get(key, ""))
        if sem:
            return sem
    raise TargetTermError(
        'לא נמצא סמסטר בפרופיל (student.term, למשל "א"). '
        "אפשר לציין אותו בשורת הפקודה: --semester א. "
        "(no semester in the profile)"
    )


def resolve_year(profile: dict, override: str | None = None) -> str:
    """השנה הלועזית לבורר השנה בידיעון: --year, אחרת student.academic_year."""
    if override:
        return hebrew_year_to_gregorian(override)
    student = profile.get("student", {}) or {}
    label = str(student.get("academic_year", "") or "").strip()
    if label:
        # תרגום מפורש — שנה עברית לא מוכרת מפילה כאן, בכוונה.
        return hebrew_year_to_gregorian(label)
    fallback = yedion_year(profile)  # מוגדרת בהמשך הקובץ (שלב 3)
    if fallback:
        return fallback
    raise UnknownAcademicYearError(
        'לא נמצאה שנה אקדמית בפרופיל (student.academic_year, למשל תשפ"ז). '
        "אפשר לציין אותה בשורת הפקודה: --year 2027. "
        "(no academic year in the profile)"
    )


def print_target_banner(semester: str, year: str) -> None:
    """מדפיס בגדול את הסמסטר והשנה שאליהם מכוונים, ואת מלכודת ברירת המחדל."""
    year_he = hebrew_year_label(year)
    prev_he = previous_year_label(year)
    prev_txt = f" ({prev_he})" if prev_he else ""
    title = (
        f"היעד: סמסטר {semester_geresh(semester)}   •   "
        f'שנה"ל {year_he or year}  ({year})'
    )
    print_box(
        title,
        [
            f"כל מפגש שאינו בסמסטר {semester_geresh(semester)} יסונן החוצה.",
            f"(only semester {semester!r} meetings are kept)",
            "",
            f"הידיעון נפתח כברירת מחדל בשנה הקודמת{prev_txt} — הכלי מחליף את",
            f"השנה במפורש ומאמת בכל דף שהיא באמת {year_he or year}.",
            "(the yedion defaults to the PREVIOUS year; the tool switches it",
            " explicitly and verifies the switch on every page)",
        ],
        ch="*",
    )


def _accepts_kwarg(func, name: str) -> bool:
    """האם אפשר להעביר לפונקציה ארגומנט מילת-מפתח בשם הזה?

    Used to stay compatible while the parser and the scraper grow their new
    `semester=` / `year=` parameters. Checking the signature is safer than
    catching TypeError, which would also swallow a genuine TypeError raised
    from *inside* the callee. If the signature cannot be inspected we answer
    True and let the call itself decide.
    """
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return True
    for param in sig.parameters.values():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            return True
        if param.name == name and param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            return True
    return False


def course_url(code: str) -> str:
    """קישור לדף הקורס בידיעון — מהסקרייפר אם הוא כבר טעון, אחרת מקומי."""
    module = sys.modules.get("scraper")
    builder = getattr(module, "course_url", None)
    if callable(builder):
        try:
            return str(builder(code))
        except Exception:
            pass
    return YEDION_COURSE_URL.format(code=code)


def is_year_error(exc: BaseException) -> bool:
    """האם החריגה היא YearSwitchError / YearMismatchError של הסקרייפר?"""
    return any(cls.__name__ in YEAR_ERROR_NAMES for cls in type(exc).__mro__)


def report_year_error(exc: BaseException, year: str = "") -> None:
    """מסביר בעברית מה השתבש בהחלפת השנה, ולמה עצרנו במקום להמשיך."""
    year_he = hebrew_year_label(year)
    target = f"{year_he} ({year})" if year_he else (year or "השנה המבוקשת")
    prev_he = previous_year_label(year)
    prev_txt = f" ({prev_he})" if prev_he else ""
    kind = type(exc).__name__
    if kind == "YearMismatchError":
        what = [
            "דף שהתקבל מהידיעון נשא שנה אקדמית אחרת מזו שביקשנו.",
            "(a page came back stamped with a different academic year)",
        ]
    else:
        what = [
            "לא הצלחנו להחליף את השנה האקדמית בידיעון.",
            "(the academic-year switch did not take effect)",
        ]
    print_box(
        "שגיאת שנה אקדמית  (academic-year error)",
        what
        + [
            "",
            f"היעד היה: {target}.",
            f"הידיעון נפתח כברירת מחדל בשנה הקודמת{prev_txt}, ולכן הנתונים",
            "שהיו מתקבלים הם של השנה הלא נכונה — מערכת שנראית תקינה לגמרי",
            "אבל שייכת לשנה שעברה. עצרנו בכוונה במקום לבנות מערכת שגויה.",
            "(stopped on purpose — the data would have been from the wrong year)",
            "",
            f"פרטי השגיאה (details): {kind}: {exc}",
            "",
            "מה אפשר לעשות (what to try):",
            "  • להריץ שוב — ייתכן שההתחברות פגה באמצע.",
            "  • לבדוק ידנית בידיעון שבורר השנה אכן מציע את השנה המבוקשת.",
            "  • להריץ עם --year YYYY אם השנה בפרופיל אינה מעודכנת.",
        ],
        ch="!",
    )


# ===========================================================================
# מסד הנתונים המתרענן (data/db) — טריות הנתונים והקטלוג החי
# ===========================================================================
# refresh.py סורק את הידיעון פעם ביום וכותב ל-data/db: את קטלוג הקורסים
# שנפתחים, את נתוני הקבוצות של הקורסים המנוטרים, ואת הזמן שבו כל דבר נשלף.
# ה-CLI קורא משם *קודם*, אחר כך מהקאש הישן (data/sections.json), ורק בלית
# ברירה מנתוני הדמו.
#
# שני עקרונות:
#   1. הידיעון הוא מקור האמת לשאלה "מה בכלל נפתח הסמסטר". תוכנית הלימודים
#      (curriculum.json) נשארת מקור לשמות, לנ"ז, לקדם ולצמידות בלבד — היא
#      אינה מגבילה את הבחירה. קורס שחוזר מסמסטר קודם הוא מקרה רגיל.
#   2. גיל הנתונים הוא חלק מהתשובה. מערכת שנבנתה מנתונים של לפני שבוע היא
#      מערכת שאולי כבר אינה נכונה — ולכן הגיל מודפס בכל ריצה, ומקבל תיבת
#      אזהרה כשהוא ישן.
#
# Technical note: src/store.py, src/discovery.py and refresh.py belong to other
# parts of this project. Everything below imports them lazily and tolerates
# their absence, so this CLI keeps working from data/sections.json even before
# they exist.

#: מודפסת פעם אחת בלבד — אין טעם להציק בכל קריאה שהמודול עדיין לא קיים.
_STORE_WARNED = False


def open_store(root: Path | str = DB_ROOT):
    """מחזיר אובייקט Store, או None אם המודול/התיקייה אינם זמינים.

    Never raises: a missing store is a normal state (nobody has run
    refresh.py yet), and the CLI must simply fall back to the older cache.
    """
    global _STORE_WARNED
    try:
        import store as store_mod  # ייבוא עצל — לא נדרש בזרימות שאינן צריכות אותו
    except Exception as exc:  # המודול עדיין לא קיים / שגיאת ייבוא
        if not _STORE_WARNED:
            _STORE_WARNED = True
            print(f"  (מסד הנתונים המתרענן אינו זמין: {exc})")
            print("  (auto-refreshing database not available — using the local cache)")
        return None
    try:
        return store_mod.Store(root=str(root))
    except Exception as exc:
        if not _STORE_WARNED:
            _STORE_WARNED = True
            print(f"  (לא הצלחנו לפתוח את מסד הנתונים ב-{root}: {exc})")
        return None


def _meta_get(meta, name: str, default=None):
    """קורא שדה מ-CourseMeta (dataclass) או ממילון — לפי מה שהתקבל בפועל."""
    if meta is None:
        return default
    value = getattr(meta, name, None)
    if value is None and isinstance(meta, dict):
        value = meta.get(name)
    return default if value is None else value


def parse_utc(stamp) -> datetime | None:
    """'2026-08-30T07:00:00Z' -> datetime מודע לאזור זמן (UTC). None אם לא ניתן."""
    if isinstance(stamp, datetime):
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    text = str(stamp or "").strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # חותמת בלי אזור זמן נחשבת UTC — כך נכתבות כל החותמות בפרויקט הזה.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def age_hours(stamp: datetime | None) -> float | None:
    """כמה שעות עברו מאז החותמת. None אם אין חותמת."""
    if stamp is None:
        return None
    delta = datetime.now(timezone.utc) - stamp
    return delta.total_seconds() / 3600.0


def humanize_age(hours: float | None) -> str:
    """0.5 -> 'לפני 30 דקות'. ניסוח ניטרלי, בלי צורות מגדריות."""
    if hours is None:
        return "לא ידוע (unknown)"
    if hours < 0:
        # חותמת עתידית — בדרך כלל שעון מערכת שאינו מסונכרן. לא מסתירים.
        return "חותמת עתידית (clock skew?)"
    minutes = int(round(hours * 60))
    if minutes < 1:
        return "ממש עכשיו"
    if minutes < 60:
        return "לפני דקה" if minutes == 1 else f"לפני {minutes} דקות"
    if hours < 24:
        whole = int(round(hours))
        return "לפני שעה" if whole == 1 else f"לפני {whole} שעות"
    days = int(hours // 24)
    if days == 1:
        return "לפני יום"
    if days == 2:
        return "לפני יומיים"
    return f"לפני {days} ימים"


def format_local(stamp: datetime) -> str:
    """חותמת UTC -> '2026-08-30 07:00' בשעון המקומי של המחשב."""
    return stamp.astimezone().strftime("%Y-%m-%d %H:%M")


def _last_refresh_stamp(store) -> datetime | None:
    """מתי הסתיימה ריצת הרענון האחרונה, לפי refresh_log."""
    if store is None:
        return None
    try:
        record = store.last_refresh()
    except Exception:
        return None
    if not isinstance(record, dict):
        return None
    # שמות השדות ברשומת הלוג אינם מקובעים בחוזה — מנסים כמה, לפי סדר עדיפות.
    for key in ("finished", "finished_at", "ended", "started", "started_at", "at", "timestamp"):
        stamp = parse_utc(record.get(key))
        if stamp is not None:
            return stamp
    return None


def store_updated_at(store, codes: list[str] | None = None) -> datetime | None:
    """החותמת האחרונה שידועה לנו: ריצת הרענון, או השליפה של הקורסים המבוקשים."""
    stamps = [s for s in (_last_refresh_stamp(store),) if s is not None]
    if store is not None:
        for code in codes or []:
            try:
                meta = store.course_meta(code)
            except Exception:
                continue
            stamp = parse_utc(_meta_get(meta, "fetched_at", ""))
            if stamp is not None:
                stamps.append(stamp)
    return max(stamps) if stamps else None


def print_freshness(store, codes: list[str], source: str = "") -> None:
    """מדפיס בבירור מתי הנתונים עודכנו לאחרונה. (data freshness — always shown)

    source: 'store' / 'cache' / 'scrape' / 'fixture' — מאיפה הגיעו הנתונים
    בריצה הזו. משפיע רק על הניסוח, לא על החישוב.
    """
    print()
    print("-" * 74)
    if source == "fixture":
        print("הנתונים עודכנו לאחרונה: לא רלוונטי — אלה נתוני דמו סינתטיים.")
        print("(demo data — there is no freshness stamp, and none is implied)")
        print("-" * 74)
        return

    stamp = store_updated_at(store, codes)
    origin = "מסד הנתונים המתרענן (data/db)"
    if stamp is None and SECTIONS_PATH.exists():
        try:
            stamp = datetime.fromtimestamp(SECTIONS_PATH.stat().st_mtime, tz=timezone.utc)
            origin = f"הקאש המקומי ({SECTIONS_PATH.name})"
        except OSError:
            stamp = None
    if source == "scrape":
        # נשלף עכשיו מהידיעון — זו העדות הטרייה ביותר שיכולה להיות.
        print(f"הנתונים עודכנו לאחרונה: {format_local(datetime.now(timezone.utc))} (ממש עכשיו)")
        print("  מקור (source): סריקה חיה של הידיעון בריצה הזו")
        print("-" * 74)
        return
    if stamp is None:
        print("הנתונים עודכנו לאחרונה: לא ידוע  (last update: unknown)")
        print(f"  כדאי להריץ רענון: python {REFRESH_SCRIPT.name}")
        print("-" * 74)
        return

    hours = age_hours(stamp)
    print(f"הנתונים עודכנו לאחרונה: {format_local(stamp)} ({humanize_age(hours)})")
    print(f"  מקור (source): {origin}")
    print(
        f"  לפי שעון המחשב המקומי; ב-UTC: {stamp.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )
    print("-" * 74)


def stale_report(
    store, codes: list[str], max_age_hours: float = DEFAULT_MAX_AGE_HOURS
) -> tuple[list[str], list[str]]:
    """(ישנים, כושלים) — קודים שהנתונים שלהם ישנים, וקודים ששליפתם נכשלה.

    "כושל" הוא ok=False ב-CourseMeta: הרענון האחרון לא הצליח, ולכן מה שיש
    בידינו הוא הנתונים הקודמים — טובים, אבל לא בהכרח עדכניים.
    """
    if store is None:
        return [], []
    stale: list[str] = []
    try:
        stale = [str(c) for c in (store.stale_codes(codes, max_age_hours) or [])]
    except Exception:
        for code in codes:
            try:
                if store.is_stale(code, max_age_hours):
                    stale.append(code)
            except Exception:
                continue
    failed: list[str] = []
    for code in codes:
        try:
            meta = store.course_meta(code)
        except Exception:
            continue
        if meta is not None and not bool(_meta_get(meta, "ok", True)):
            failed.append(code)
    return sorted(set(stale)), sorted(set(failed))


def refresh_hint_lines() -> list[str]:
    """השורות שמסבירות איך לרענן את הנתונים — מופיעות בכל מקום שצריך אותן."""
    return [
        f"לרענון עכשיו (refresh now):          python {REFRESH_SCRIPT.name}",
        f"למצב הנתונים בלי רשת (status):        python {REFRESH_SCRIPT.name} --status",
        f"להתקנת רענון יומי (daily task):       python {REFRESH_SCRIPT.name} --install-task",
    ]


def print_refresh_hint() -> None:
    """תזכורת קצרה בסוף הריצה: איך לשמור על הנתונים טריים."""
    print()
    print("שמירה על נתונים עדכניים  (keeping the data fresh):")
    for line in refresh_hint_lines():
        print(f"  {line}")
    print(
        "  הרענון היומי מושך את הידיעון פעם ביום. אם ההתחברות פגה, הוא עוצר,"
    )
    print("  משאיר את הנתונים הישנים ומבקש התחברות מחדש — ולא מציג ישן כחדש.")


def warn_if_stale(
    store,
    codes: list[str],
    courses: dict[str, Course] | None = None,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> None:
    """תיבת אזהרה על נתונים ישנים/כושלים, ושאלה אם להמשיך.

    ברירת המחדל היא כן להמשיך — נתונים ישנים עדיין שימושיים לתכנון — אבל
    לעולם לא בשקט. יציאה מפורשת מפילה QuitRequested.
    """
    stale, failed = stale_report(store, codes, max_age_hours)
    if not stale and not failed:
        return

    def describe(code: str) -> str:
        name = ""
        if courses and code in courses:
            name = getattr(courses[code], "name", "") or ""
        try:
            meta = store.course_meta(code)
        except Exception:
            meta = None
        stamp = parse_utc(_meta_get(meta, "fetched_at", ""))
        when = humanize_age(age_hours(stamp)) if stamp else "לא ידוע מתי"
        tail = "השליפה האחרונה נכשלה" if code in failed else f"עודכן {when}"
        return f"{code}  {name}".rstrip() + f"  —  {tail}"

    lines = [
        f"הנתונים של הקורסים הבאים ישנים מ-{max_age_hours:.0f} שעות, "
        "או שהשליפה האחרונה שלהם נכשלה:",
        "",
    ]
    lines += [f"  • {describe(code)}" for code in sorted(set(stale) | set(failed))]
    lines += [
        "",
        "המשמעות: ייתכן שהידיעון השתנה מאז — קבוצה נוספה, מרצה הוחלף,",
        "או ששעה זזה. המערכת שתיבנה עדיין שימושית לתכנון, אבל לפני רישום",
        "אמיתי חובה לרענן ולבדוק.",
        "",
        "(the data below is older than the threshold, or its last fetch failed)",
        "",
    ] + refresh_hint_lines()
    print_box("נתונים לא טריים  (stale data)", lines, ch="!")
    if not ask_yes_no(
        "להמשיך בכל זאת עם הנתונים האלה? (continue anyway?)", default=True
    ):
        print("עצרנו. כדאי להריץ רענון ואז שוב את SlotWise. (stopped)")
        raise QuitRequested


# ---------------------------------------------------------------------------
# טעינת קורסים מהמסד — כולל סינון סמסטר ואימות שנה
# ---------------------------------------------------------------------------
def restrict_to_semester(course: Course, semester: str) -> tuple[Course, int, int]:
    """מחזיר עותק של הקורס עם מפגשי הסמסטר המבוקש בלבד.

    Returns:
        (course, dropped, unverified) — הקורס המסונן, כמה מפגשים הוסרו
        כי הם שייכים לסמסטר אחר, וכמה מפגשים אין עליהם סימון סמסטר בכלל.

    מפגש בלי סימון סמסטר *נשמר* — אבל נספר ומדווח. מחיקה שלו הייתה מוחקת
    בשקט חצי מערכת; השארה בלי דיווח הייתה מערבבת סמסטרים בשקט. הדרך
    היחידה שאינה שקטה היא לשמור ולספר.
    """
    kept_groups: list[Group] = []
    dropped = 0
    unverified = 0
    for group in course.groups:
        meetings = []
        for meeting in group.meetings:
            mark = normalize_semester(getattr(meeting, "semester", "") or "")
            if not mark:
                unverified += 1
                meetings.append(meeting)
            elif mark == semester:
                meetings.append(meeting)
            else:
                dropped += 1
        if meetings:
            kept_groups.append(
                Group(
                    course_code=group.course_code,
                    group_id=group.group_id,
                    kind=group.kind,
                    lecturer=group.lecturer,
                    meetings=meetings,
                    linked_to=list(group.linked_to or []),
                    note=group.note,
                )
            )
    filtered = Course(
        code=course.code,
        name=course.name,
        credits=course.credits,
        groups=kept_groups,
        tied_with=list(course.tied_with or []),
    )
    return filtered, dropped, unverified


def _store_course(store, code: str) -> tuple[Course | None, object | None]:
    """(Course, CourseMeta) מהמסד לקוד אחד. (None, None) אם אינו שם."""
    course = None
    meta = None
    loader = getattr(store, "load_course", None)
    if callable(loader):
        try:
            got = loader(code)
        except Exception:
            got = None
        if isinstance(got, tuple):
            course = got[0] if len(got) > 0 else None
            meta = got[1] if len(got) > 1 else None
        elif got is not None:
            course = got
    if course is None:
        # גיבוי לגרסת Store שאין בה load_course.
        try:
            course = (store.load_all() or {}).get(code)
        except Exception:
            course = None
    if meta is None:
        try:
            meta = store.course_meta(code)
        except Exception:
            meta = None
    return course, meta


def store_sections(
    store, codes: list[str], semester: str, year: str
) -> dict[str, Course]:
    """טוען מהמסד את הקורסים המבוקשים, מסונן לסמסטר ומאומת מול השנה.

    כללי הבטיחות זהים לאלה של הקאש הישן:
        • שנה שאינה תואמת -> הקורס אינו נכנס לריצה. לעולם לא מערבבים שנים.
        • מפגשים מסמסטר אחר -> מסוננים החוצה לפני השיבוץ.
        • קורס שנשאר בלי אף קבוצה -> אינו נפתח בסמסטר הזה, ולא נכנס.
    """
    if store is None or not codes:
        return {}
    found: dict[str, Course] = {}
    wrong_year: list[tuple[str, str]] = []
    empty: list[str] = []
    unverified: list[str] = []
    for code in codes:
        course, meta = _store_course(store, code)
        if course is None:
            continue
        got_year = str(_meta_get(meta, "year_gregorian", "") or "").strip()
        if got_year and str(year) and got_year != str(year):
            wrong_year.append((code, got_year))
            continue
        meta_sem = normalize_semester(str(_meta_get(meta, "semester", "") or ""))
        if meta_sem and meta_sem == semester:
            kept = course  # כבר סונן בזמן הרענון
        else:
            kept, _dropped, unknown = restrict_to_semester(course, semester)
            if unknown:
                unverified.append(code)
        if not kept.groups:
            empty.append(code)
            continue
        found[code] = kept

    if found:
        print(f"  נטענו ממסד הנתונים (from the database): {', '.join(sorted(found))}")
    if empty:
        print(
            f"  אין קבוצות בסמסטר {semester_geresh(semester)} עבור: "
            f"{', '.join(sorted(empty))}  (not offered this term in the database)"
        )
    if unverified:
        print(
            "  שימו לב — מפגשים בלי סימון סמסטר נשמרו כמו שהם, ולכן לא ניתן "
            f"לאמת אותם: {', '.join(sorted(set(unverified)))}"
        )
        print("  (meetings with no semester tag were kept but could not be verified)")
    if wrong_year:
        print_box(
            "נתונים משנה אקדמית אחרת — לא נכנסו לריצה  (wrong year, skipped)",
            [
                f"היעד (target): {hebrew_year_label(str(year)) or year}  ({year})",
                "",
                *[
                    f"  • {code}  —  נשמר במסד לשנה {hebrew_year_label(got) or got} ({got})"
                    for code, got in sorted(wrong_year)
                ],
                "",
                "מערכת משנה שגויה גרועה מכלום, ולכן הקורסים האלה מדולגים.",
                f"לרענון: python {REFRESH_SCRIPT.name}",
            ],
            ch="!",
        )
    return found


# ---------------------------------------------------------------------------
# מיקום הקורס בתוכנית הלימודים — מידע בלבד, אף פעם לא שער
# ---------------------------------------------------------------------------
def curriculum_placement(curr: dict, code: str) -> dict:
    """היכן הקורס יושב בתוכנית: סמסטר, אשכול בחירה, שם ונ"ז.

    Returns:
        {"in_curriculum": bool, "semester": "4"/"", "cluster": "", "name": "",
         "credits": 0.0}

    התשובה הזאת היא *מידע* להצגה. היא לעולם אינה מונעת בחירה של קורס:
    קורסים חוזרים מסמסטרים קודמים, והרישום בפועל אינו זהה לתוכנית.
    """
    place = {
        "in_curriculum": False,
        "semester": "",
        "cluster": "",
        "name": "",
        "credits": 0.0,
    }
    try:
        source = curriculum_mod.find_course_source(curr, code)
    except Exception:
        source = None
    try:
        info = curriculum_mod.find_course(curr, code)
    except Exception:
        info = None
    if info:
        place["in_curriculum"] = True
        place["name"] = str(info.get("name", "") or "")
        try:
            place["credits"] = float(info.get("credits") or 0.0)
        except (TypeError, ValueError):
            place["credits"] = 0.0
    if source:
        place["in_curriculum"] = True
        text = str(source)
        if text.startswith("semester:"):
            place["semester"] = text.split(":", 1)[1]
        elif text.startswith("cluster:"):
            place["cluster"] = text.split(":", 1)[1]
    return place


def placement_marker(place: dict) -> str:
    """הסימון שמופיע ליד הקורס ברשימת הבחירה. שלושתם ניתנים לבחירה."""
    if not place.get("in_curriculum"):
        return "[מחוץ לתוכנית]"
    if place.get("semester"):
        return f"[בתוכנית-סמסטר {place['semester']}]"
    if place.get("cluster"):
        return f"[בתוכנית-בחירה: {place['cluster']}]"
    return "[בתוכנית]"


def placement_note(place: dict, student_semester: str, code: str, name: str = "") -> str:
    """שורת *מידע* על קורס שאינו מסמסטר התוכנית הנוכחי. "" אם אין מה לומר.

    זו הודעה ניטרלית בכוונה: קורס מסמסטר קודם הוא מקרה רגיל ותקין לגמרי,
    ולא תקלה. אין כאן שום ניסיון להניא מבחירה.
    """
    label = f"{code} {name}".strip()
    if not place.get("in_curriculum"):
        return (
            f"{label}: אינו מופיע בתוכנית הלימודים — נלקח כקורס מחוץ לתוכנית. "
            "(outside the curriculum — taken as an extra)"
        )
    sem = str(place.get("semester") or "")
    if sem and student_semester and sem != str(student_semester):
        return (
            f"{label}: קורס זה משויך לסמסטר {sem} בתוכנית — נלקח כהשלמה. "
            "(from another curriculum semester — taken as catch-up)"
        )
    if place.get("cluster"):
        return (
            f"{label}: קורס בחירה מאשכול {place['cluster']}. "
            "(an elective from this cluster)"
        )
    return ""


# ---------------------------------------------------------------------------
# הקטלוג החי — כל מה שנפתח בפועל, לא רק מה שכתוב בתוכנית
# ---------------------------------------------------------------------------
def annotate_catalog(catalog: dict, curr: dict) -> dict:
    """מעשיר את הקטלוג בפרטי התוכנית, אם discovery.py זמין. אחרת מחזיר כמו שהוא."""
    if not catalog:
        return {}
    try:
        import discovery as discovery_mod

        fn = getattr(discovery_mod, "annotate_with_curriculum", None)
        if callable(fn):
            annotated = fn(catalog, curr)
            if isinstance(annotated, dict) and annotated:
                return annotated
    except Exception:
        # ההעשרה היא בונוס בלבד — בלעדיה פשוט מציגים קוד ושם.
        pass
    return catalog


def build_catalog_view(store, curr: dict) -> dict[str, dict]:
    """{קוד: {"name":..., ...}} — קטלוג הקורסים שנפתחים, מועשר בפרטי התוכנית."""
    catalog: dict = {}
    if store is not None:
        try:
            loaded = store.load_catalog()
        except Exception as exc:
            print(f"  (לא הצלחנו לקרוא את הקטלוג: {exc})")
            loaded = None
        if isinstance(loaded, tuple):
            catalog = loaded[0] if loaded and isinstance(loaded[0], dict) else {}
        elif isinstance(loaded, dict):
            catalog = loaded
    return annotate_catalog(dict(catalog or {}), curr)


def _clean_catalog_text(text) -> str:
    """מנקה טקסט מהקטלוג: nbsp, גרשיים עבריים ורווחים כפולים."""
    out = str(text or "").replace(" ", " ")
    return re.sub(r"\s+", " ", _plain_quotes(out)).strip()


def _local_catalog_search(
    catalog: dict[str, dict], query: str, limit: int
) -> list[tuple[str, str]]:
    """חיפוש מקומי בקטלוג — גיבוי ל-Store.search_catalog.

    הדירוג זהה לזה שבחוזה: קוד מדויק, אחר כך תחילת קוד, ואז חלק מהשם.
    """
    needle = _clean_catalog_text(query)
    if not needle:
        return []
    exact: list[tuple[str, str]] = []
    prefix: list[tuple[str, str]] = []
    by_name: list[tuple[str, str]] = []
    for code, entry in catalog.items():
        name = ""
        if isinstance(entry, dict):
            name = str(entry.get("name", "") or "")
        else:
            name = str(entry or "")
        pair = (str(code), _clean_catalog_text(name))
        if str(code) == needle:
            exact.append(pair)
        elif str(code).startswith(needle):
            prefix.append(pair)
        elif needle in pair[1]:
            by_name.append(pair)
    ordered = exact + sorted(prefix) + sorted(by_name, key=lambda p: p[1])
    return ordered[:limit]


def catalog_search(
    store, catalog: dict[str, dict], query: str, limit: int = PICK_RESULT_LIMIT
) -> list[tuple[str, str]]:
    """חיפוש בקטלוג: קוד מלא, תחילת קוד, או חלק משם הקורס בעברית."""
    results: list[tuple[str, str]] = []
    if store is not None:
        try:
            raw = store.search_catalog(query, limit) or []
        except Exception as exc:
            print(f"  (חיפוש בקטלוג נכשל: {exc})")
            raw = []
        for item in raw:
            if isinstance(item, (tuple, list)) and item:
                code = str(item[0])
                name = str(item[1]) if len(item) > 1 else ""
            else:
                code, name = str(item), ""
            results.append((code, _clean_catalog_text(name)))
    if not results:
        results = _local_catalog_search(catalog, query, limit)
    return results[:limit]


def _catalog_name(catalog: dict, curr: dict, code: str) -> str:
    """שם הקורס: מהקטלוג החי אם יש, אחרת מתוכנית הלימודים, אחרת ריק."""
    entry = catalog.get(code) if isinstance(catalog, dict) else None
    if isinstance(entry, dict) and entry.get("name"):
        return _clean_catalog_text(entry["name"])
    return curriculum_placement(curr, code).get("name", "")


def _pick_line(index: int, code: str, name: str, place: dict) -> str:
    """שורת תוצאה אחת. המספרים והקוד בהתחלה — עברית היא RTL, ולכן השם אחרון."""
    credits = float(place.get("credits") or 0.0)
    credits_txt = f'{credits:>4.1f} נ"ז' if credits else "   ?  נ\"ז"
    return f"  {index:>2}. {code}   {credits_txt}   {placement_marker(place):<22} {name}"


def _print_chosen(chosen: list[str], catalog: dict, curr: dict) -> float:
    """מדפיס את הרשימה המצטברת ומחזיר את סכום הנ"ז הידוע."""
    print()
    total = 0.0
    unknown = 0
    print(f"הרשימה עד כה ({len(chosen)} קורסים):")
    for i, code in enumerate(chosen, start=1):
        place = curriculum_placement(curr, code)
        name = _catalog_name(catalog, curr, code) or place.get("name", "")
        credits = float(place.get("credits") or 0.0)
        if credits:
            total += credits
        else:
            unknown += 1
        print(_pick_line(i, code, name, place))
    tail = "  (+ קורסים שאין לנו נ\"ז עבורם)" if unknown else ""
    print(f'  סה"כ נקודות זכות ידועות: {total:.1f}{tail}')
    return total


def pick_courses(
    store, curr: dict, profile: dict, preselected: list[str] | None = None
) -> list[str]:
    """--pick: בחירת קורסים מתוך הקטלוג החי של הידיעון.

    אפשר להקליד קוד מלא, תחילת קוד, או חלק משם הקורס בעברית. כל תוצאה
    מסומנת ב-[בתוכנית-סמסטר N] או ב-[מחוץ לתוכנית] — *כל* התוצאות ניתנות
    לבחירה. תוכנית הלימודים היא הצעה, לא גדר: קורס חוזר מסמסטר קודם הוא
    מקרה רגיל, ולא כל מה שנרשמים אליו בפועל מופיע ב-PDF.

    Returns:
        רשימת קודים לפי סדר הבחירה. רשימה ריקה = לא נבחר כלום (ואז
        הזרימה ממשיכה עם מה שכתוב בפרופיל).
    """
    student_sem = str((profile.get("student") or {}).get("curriculum_semester", "") or "")
    chosen: list[str] = []
    for code in preselected or []:
        if code not in chosen:
            chosen.append(code)

    catalog = build_catalog_view(store, curr)
    print()
    print("=" * 74)
    print("  בחירת קורסים מהקטלוג החי  (pick courses from the live catalog)")
    print("=" * 74)
    if catalog:
        print(f"  בקטלוג {len(catalog)} קורסים שנפתחים בשנה הזאת.")
    else:
        print("  אין קטלוג שמור עדיין — אפשר עדיין להקליד קודי קורס במלואם.")
        print(f"  (no catalog yet — run  python {REFRESH_SCRIPT.name}  to build one)")
    print("  אפשר להקליד: קוד (61753), תחילת קוד (617), או חלק משם בעברית.")
    print("  פקודות: Enter = סיום   |   -קוד = הסרה   |   ? = עזרה   |   q = יציאה")
    print("  הערה: כל קורס שנפתח ניתן לבחירה — גם אם אינו בסמסטר של התוכנית,")
    print("  וגם אם אינו מופיע בתוכנית בכלל. (every offered course is selectable)")
    if chosen:
        _print_chosen(chosen, catalog, curr)

    while True:
        raw = ask("\nחיפוש או קוד (Enter = סיום): ").strip()

        if not raw:
            if not chosen:
                print("לא נבחר אף קורס. (nothing picked)")
                return []
            _print_chosen(chosen, catalog, curr)
            if ask_yes_no("לאשר את הרשימה הזאת? (confirm this list?)", default=True):
                break
            continue

        if raw in {"?", "עזרה", "help"}:
            print("  קוד מלא (61753) / תחילת קוד (617) / חלק משם (אלגורית)")
            print("  -61753 = להסיר קורס מהרשימה   |   Enter = סיום")
            continue

        if raw.startswith("-") and len(raw) > 1:
            victim = raw[1:].strip()
            if victim in chosen:
                chosen.remove(victim)
                print(f"  הוסר: {victim}  (removed)")
                _print_chosen(chosen, catalog, curr)
            else:
                print(f"  {victim} אינו ברשימה. (not in the list)")
            continue

        matches = catalog_search(store, catalog, raw)
        if not matches:
            print("  לא נמצאו התאמות בקטלוג. (no matches)")
            if re.fullmatch(r"\d{4,7}", raw):
                # קוד תקין שאינו בקטלוג: ייתכן שהקטלוג ישן, או שהקורס מוצע
                # ואינו מופיע ברשימה. לא חוסמים — רק מסבירים.
                print("  זהו קוד תקין שאינו מופיע בקטלוג השמור.")
                if ask_yes_no("להוסיף אותו בכל זאת? (add it anyway?)", default=True):
                    if raw not in chosen:
                        chosen.append(raw)
                    note = placement_note(
                        curriculum_placement(curr, raw), student_sem, raw
                    )
                    if note:
                        print(f"  {note}")
                    _print_chosen(chosen, catalog, curr)
            continue

        print()
        print(f"נמצאו {len(matches)} תוצאות (showing up to {PICK_RESULT_LIMIT}):")
        places = []
        for i, (code, name) in enumerate(matches, start=1):
            place = curriculum_placement(curr, code)
            places.append(place)
            print(_pick_line(i, code, name or place.get("name", ""), place))

        answer = ask("מספרים להוספה, או Enter לחיפוש חדש: ").strip()
        if not answer:
            continue
        picked = _parse_ranking(answer, len(matches))
        if picked is None:
            print(f"יש לנסות שוב: מספרים בין 1 ל-{len(matches)}. (try again)")
            continue
        for index in picked:
            code, name = matches[index - 1]
            if code in chosen:
                print(f"  {code} כבר ברשימה. (already picked)")
                continue
            chosen.append(code)
            note = placement_note(places[index - 1], student_sem, code, name)
            if note:
                print(f"  {note}")
            # צמידות: מודיעים מראש שהחבילה תיסגר לבד בשלב הבא.
            try:
                block = [c for c in (curriculum_mod.tied_group(curr, code) or []) if c != code]
            except Exception:
                block = []
            if block:
                print(
                    f"  {code} צמוד ל-{', '.join(block)} — הם יתווספו אוטומטית. "
                    "(tied courses are added automatically)"
                )
        _print_chosen(chosen, catalog, curr)

    # הצעה לנטר את הקורסים שנבחרו — כדי שהרענון היומי יעדכן בדיוק אותם.
    if store is not None and chosen:
        try:
            if ask_yes_no(
                "להוסיף את הקורסים האלה לרשימת הרענון היומי? (track them?)",
                default=True,
            ):
                store.track(chosen)
                print(f"  נוספו לרשימת הרענון: {', '.join(chosen)}  (tracked)")
        except QuitRequested:
            raise
        except Exception as exc:
            print(f"  (לא הצלחנו לעדכן את רשימת הרענון: {exc})")
    return chosen


# ---------------------------------------------------------------------------
# --track / --untrack — ניהול הקורסים שהרענון היומי מעדכן
# ---------------------------------------------------------------------------
def split_codes(raw: str | None) -> list[str]:
    """'61753, 61756' -> ['61753', '61756']. מחרוזת ריקה -> []."""
    if not raw:
        return []
    return [part.strip() for part in re.split(r"[,\s]+", str(raw)) if part.strip()]


def manage_tracking(store, add: list[str], remove: list[str]) -> int:
    """מוסיף/מסיר קודים מרשימת הרענון היומי ומדפיס את התוצאה. קוד יציאה."""
    if store is None:
        print_box(
            "מסד הנתונים המתרענן אינו זמין  (database not available)",
            [
                f"לא נמצא מסד נתונים ב-{DB_ROOT}.",
                "רשימת הרענון נשמרת שם, ולכן אין מה לעדכן עדיין.",
                "",
                *refresh_hint_lines(),
            ],
            ch="!",
        )
        return 1
    try:
        before = sorted(str(c) for c in (store.tracked() or []))
    except Exception as exc:
        print(f"לא הצלחנו לקרוא את רשימת הרענון: {exc}  (cannot read tracked set)")
        return 1
    try:
        if add:
            store.track(add)
        if remove:
            store.untrack(remove)
        after = sorted(str(c) for c in (store.tracked() or []))
    except Exception as exc:
        print(f"עדכון רשימת הרענון נכשל: {exc}  (update failed)")
        return 1

    added = [c for c in after if c not in before]
    removed = [c for c in before if c not in after]
    print()
    print("=" * 74)
    print("  רשימת הרענון היומי  (the auto-refreshed set)")
    print("=" * 74)
    if added:
        print(f"  נוספו (added)  : {', '.join(added)}")
    if removed:
        print(f"  הוסרו (removed): {', '.join(removed)}")
    if not added and not removed:
        print("  לא השתנה כלום. (no change)")
    ignored = [c for c in add if c in before and c not in added]
    if ignored:
        print(f"  כבר היו ברשימה (already tracked): {', '.join(sorted(set(ignored)))}")
    missing = [c for c in remove if c not in before]
    if missing:
        print(f"  לא היו ברשימה (were not tracked): {', '.join(sorted(set(missing)))}")
    print()
    print(f"  הרשימה עכשיו ({len(after)} קורסים):")
    print("   " + (", ".join(after) if after else "— ריקה —"))
    print_refresh_hint()
    return 0


# ===========================================================================
# שלב 0 — שורת הפקודה
# ===========================================================================
def build_arg_parser() -> argparse.ArgumentParser:
    """בונה את מנתח הדגלים של שורת הפקודה. (command-line flags)"""
    ap = argparse.ArgumentParser(
        prog="slotwise",
        description="בונה מערכת שעות למכללת בראודה (SlotWise)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "דוגמאות (examples):\n"
            "  python main.py                 # ריצה רגילה\n"
            "  python main.py --offline       # בלי דפדפן, מהקאש/דמו\n"
            "  python main.py --refresh       # לסרוק מחדש את הידיעון\n"
            "  python main.py --top 3 --days 3\n"
            "  python main.py --codes 61756,61757,62027\n"
            "  python main.py --semester א --year 2027\n"
        ),
    )
    ap.add_argument(
        "--refresh",
        action="store_true",
        help="לסרוק מחדש את הידיעון גם אם יש קאש (re-scrape the yedion)",
    )
    ap.add_argument(
        "--offline",
        action="store_true",
        help="לא לפתוח דפדפן בכלל — קאש או נתוני דמו בלבד (no browser)",
    )
    ap.add_argument(
        "--top",
        type=int,
        default=5,
        metavar="N",
        help="כמה מערכות להציג (how many schedules to show). ברירת מחדל: 5",
    )
    ap.add_argument(
        "--days",
        type=int,
        default=None,
        metavar="N",
        help="כמה ימים בקמפוס לכוון אליהם (target days). ברירת מחדל: מהפרופיל",
    )
    ap.add_argument(
        "--html",
        type=str,
        default=None,
        metavar="PATH",
        help=f"נתיב קובץ ה-HTML לפלט. ברירת מחדל: {DEFAULT_HTML_PATH}",
    )
    ap.add_argument(
        "--codes",
        type=str,
        default=None,
        metavar="61753,61756",
        help="רשימת קודי קורסים מופרדת בפסיקים, במקום אלה שבפרופיל",
    )
    # --- היעד: סמסטר ושנה. שניהם גוברים על data/profile.json. ---
    ap.add_argument(
        "--semester",
        type=str,
        default=None,
        choices=list(SEMESTERS),
        help=(
            "הסמסטר שלפיו מסננים את המפגשים, במקום student.term שבפרופיל "
            "(which semester's meetings to keep)"
        ),
    )
    ap.add_argument(
        "--year",
        type=str,
        default=None,
        metavar="YYYY",
        help=(
            'השנה האקדמית כשנה לועזית, למשל 2027 = תשפ"ז (גם תווית עברית '
            "מתקבלת). ברירת מחדל: student.academic_year שבפרופיל"
        ),
    )
    # --- בחירת קורסים מהקטלוג החי ורשימת המעקב לריענון היומי ---
    # תוכנית הלימודים היא *המלצה*, לא גדר: קורסים חוזרים מסמסטרים קודמים,
    # ומה שנפתח בפועל נקבע בידיעון בלבד. לכן --pick מציג את הקטלוג האמיתי
    # ומאפשר לבחור כל קורס, גם כזה שאינו בסמסטר של הסטודנט/ית ואף לא בתוכנית.
    ap.add_argument(
        "--pick",
        action="store_true",
        help=(
            "בחירת קורסים מהקטלוג החי של הידיעון (חיפוש לפי קוד, תחילית קוד או "
            "חלק משם) — כולל קורסים חוזרים מסמסטרים קודמים "
            "(pick courses from the live catalog)"
        ),
    )
    ap.add_argument(
        "--track",
        type=str,
        default=None,
        metavar="61753,61756",
        help="להוסיף קודים לרשימת המעקב שמתרעננת אוטומטית (add to the auto-refresh set)",
    )
    ap.add_argument(
        "--untrack",
        type=str,
        default=None,
        metavar="61753",
        help="להסיר קודים מרשימת המעקב (remove from the auto-refresh set)",
    )
    return ap


# ===========================================================================
# שלב 1 — טעינת הפרופיל ואישורו
# ===========================================================================
def load_profile(path: Path | str = PROFILE_PATH) -> dict:
    """טוען את data/profile.json — תשובות האינטייק שנאספו בשיחת ההיכרות."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def confirm_profile(
    profile: dict,
    plan: list[dict],
    target_days: int,
    semester: str | None = None,
    year: str | None = None,
) -> bool:
    """מדפיס את בלוק האישור של שלב 1 ומחזיר האם להמשיך.

    מציג: שנה, סמסטר, מספר ימים רצוי, ואת הקורסים עם נ"ז וסכום מצטבר,
    כולל ההבהרה ש-61756/61757/62027 הם קורסים צמודים.

    semester/year הם היעד שנקבע בפועל (אחרי --semester / --year). אם לא
    הועברו, נופלים למה שכתוב בפרופיל — כדי שהפונקציה תישאר שמישה לבדה.
    """
    st = profile.get("student", {})
    print()
    print("=" * 74)
    print("  שלב 1: אישור הנתונים  (step 1: confirm your details)")
    print("=" * 74)
    print(f"  תוכנית (program)        : {st.get('program', '—')}")
    print(f"  שנה (year of study)     : {st.get('year_of_study', '—')}  {st.get('year_label', '')}")
    # היעד בפועל — לא רק מה שכתוב בפרופיל.
    profile_sem = normalize_semester(st.get("term", ""))
    sem = semester or profile_sem or str(st.get("term", "—"))
    year_greg = str(year or "")
    year_he = hebrew_year_label(year_greg) or str(st.get("academic_year", "—"))
    # אם --semester עקף את הפרופיל, לא מציגים את התווית של הפרופיל —
    # היא הייתה מכריזה על סמסטר אחר מזה שבאמת ייסרק.
    if sem == profile_sem:
        term_text = st.get("term_label", "")
    else:
        term_text = f"{semester_label(sem)}  ← מהדגל --semester"
    print(
        f"  סמסטר (term)            : {semester_geresh(sem)}  {term_text}"
        f"  — סמסטר {st.get('curriculum_semester', '—')} בתוכנית הלימודים"
    )
    print(
        f"  שנה אקדמית (acad. year) : {year_he}"
        f"  ({year_greg or st.get('academic_year_gregorian', '—')})"
    )
    print(f"  ימים בקמפוס (target days): {target_days}")
    print()
    print(f"  הקורסים לשיבוץ ({len(plan)} קורסים):")
    # Numbers first, Hebrew name last — Hebrew is RTL, so anything padded
    # *after* the name renders crookedly in a Windows terminal.
    running = 0.0
    for i, course in enumerate(plan, start=1):
        running += float(course.get("credits") or 0.0)
        credits = f"{float(course.get('credits') or 0.0):.1f}"
        print(
            f"   {i}. {course['code']}   {credits:>4} נ\"ז   "
            f"(מצטבר {running:>4.1f})   {course.get('name', '')}"
        )
    print()
    print(f'  סה"כ נקודות זכות (total credits): {running:.1f}')
    hours = profile.get("total_weekly_hours")
    if hours:
        print(f"  שעות שבועיות (weekly hours)     : {hours}")

    # קורסים צמודים — הכלל הכי חשוב בסמסטר הזה.
    tied_codes = [c["code"] for c in plan if c.get("tied_with")]
    if tied_codes:
        print()
        print("  שימו לב — קורסים צמודים (tied courses):")
        print(
            "   " + ", ".join(sorted(set(tied_codes)))
            + " נלקחים יחד או בכלל לא — הכל או כלום."
        )
        print("   (they are an all-or-nothing block: all of them, or none)")

    # 61753 אלגוריתמים מגיע מסמסטר 4 (קורס אביב) — ייתכן שלא ייפתח בסמסטר א'.
    for course in plan:
        if course.get("from_semester") and course["from_semester"] != str(
            st.get("curriculum_semester", "")
        ):
            print()
            print(
                f"  הערה: {course['code']} {course.get('name', '')} נלקח מסמסטר "
                f"{course['from_semester']} — יש לוודא בידיעון שהוא נפתח הסמסטר."
            )
            print("  (borrowed from another semester — may not be offered)")
    print("=" * 74)

    # היעד — בלוק בולט בכוונה. סמסטר שגוי או שנה שגויה הם שתי התקלות
    # היחידות שמייצרות מערכת שנראית מושלמת ופשוט אינה נכונה.
    if year_greg:
        print_target_banner(sem, year_greg)

    return ask_yes_no("להמשיך עם הנתונים האלה? (continue with these?)", default=True)


# ===========================================================================
# שלב 2 — פתירת קודי הקורסים מול הידיעון
# ===========================================================================
def resolve_plan(profile: dict, curr: dict, codes_override: list[str] | None = None) -> list[dict]:
    """בונה את רשימת הקורסים לשיבוץ: קוד, שם, נ"ז, וצמידויות.

    מקור הקודים: --codes אם ניתן, אחרת selected_courses שבפרופיל.
    כל קוד מועשר בפרטים מהידיעון (curriculum.find_course), ומורחב
    לקבוצת הקורסים הצמודים שלו (curriculum.tied_group).
    """
    if codes_override:
        codes = list(codes_override)
        by_code: dict[str, dict] = {}
    else:
        selected = profile.get("selected_courses", []) or []
        codes = [c["code"] for c in selected]
        by_code = {c["code"]: dict(c) for c in selected}

    # הרחבה לפי צמידות: אם נבחר 61756 — חייבים גם 61757 ו-62027.
    expanded: list[str] = []
    for code in codes:
        try:
            group = curriculum_mod.tied_group(curr, code)
        except Exception:
            group = [code]
        for member in group or [code]:
            if member not in expanded:
                expanded.append(member)

    plan: list[dict] = []
    for code in expanded:
        entry = dict(by_code.get(code, {"code": code}))
        entry["code"] = code
        info = None
        try:
            info = curriculum_mod.find_course(curr, code)
        except Exception:
            info = None
        if info:
            entry.setdefault("name", info.get("name", ""))
            if not entry.get("credits"):
                entry["credits"] = info.get("credits", 0.0)
            if info.get("tied_with") and not entry.get("tied_with"):
                entry["tied_with"] = list(info["tied_with"])
        else:
            entry.setdefault("name", "")
            entry.setdefault("credits", 0.0)
            print(
                f"אזהרה: הקוד {code} לא נמצא בידיעון. ממשיכים איתו בכל זאת. "
                f"(code not found in curriculum — continuing anyway)"
            )
        if not entry.get("tied_with"):
            try:
                group = curriculum_mod.tied_group(curr, code)
            except Exception:
                group = [code]
            entry["tied_with"] = [c for c in (group or []) if c != code]
        plan.append(entry)
    return plan


# ===========================================================================
# שלב 3 — השגת נתוני הקבוצות (sections)
# ===========================================================================
def load_sections_file(path: Path) -> dict[str, Course]:
    """עוטף את parser.load_sections עם נתיב מוחלט."""
    return parser_mod.load_sections(str(path))


def warn_demo_data() -> None:
    """אזהרה רועשת: הנתונים הם דמו סינתטי ולא הידיעון האמיתי."""
    print_box(
        "אזהרה חמורה — נתוני דמו סינתטיים!   (SYNTHETIC DEMO DATA)",
        [
            f"מקור הנתונים: {FIXTURE_PATH}",
            "",
            "אלה נתוני בדיקה שהומצאו לצורך פיתוח התוכנה.",
            "הם *אינם* הידיעון האמיתי של בראודה, והמערכת שתתקבל",
            "אינה מתאימה לרישום אמיתי לקורסים!",
            "",
            "This is fake data used for development only. Do NOT register",
            "for courses based on it.",
            "",
            "כדי לקבל נתונים אמיתיים: יש להריץ בלי --offline (או עם --refresh)",
            "ולהתחבר לידיעון בחלון הדפדפן שייפתח.",
        ],
        ch="!",
    )


def yedion_year(profile: dict) -> str | None:
    """מחלץ את שנת הידיעון מ-academic_year_gregorian: '2026/27' -> '2027'.

    זהו *גיבוי* בלבד ל-resolve_year, שמתרגם את student.academic_year
    (תווית עברית) דרך HEBREW_YEAR_TO_GREGORIAN.

    הידיעון עובד בשנים לועזיות של סוף שנת הלימודים (תשפ"ז = 2027).
    מחזיר None אם אי אפשר להסיק — ואז הסקרייפר פשוט לא נוגע בבורר.
    """
    raw = str((profile.get("student") or {}).get("academic_year_gregorian", "")).strip()
    m = re.fullmatch(r"(\d{4})\s*/\s*(\d{2,4})", raw)
    if m:
        head, tail = m.group(1), m.group(2)
        return tail if len(tail) == 4 else head[:2] + tail
    if re.fullmatch(r"\d{4}", raw):
        return raw
    return None


def check_page_year(html: str, code: str, year: str) -> bool:
    """אימות נוסף בצד שלנו: האם דף הקורס הזה באמת של השנה שביקשנו?

    הסקרייפר כבר מאמת את החלפת השנה, אבל שכבת אימות שנייה כאן עולה כמעט
    כלום — וזו בדיוק התקלה שאסור שתעבור בשקט. מחזיר True גם כשאי אפשר
    לדעת: חוסמים רק על סתירה מפורשת, לא על חוסר מידע.
    """
    extractor = getattr(parser_mod, "extract_page_year", None)
    if not callable(extractor):
        return True
    try:
        found = extractor(html)
    except Exception:
        return True
    if not found:
        return True
    try:
        found_greg = hebrew_year_to_gregorian(str(found))
    except TargetTermError:
        return True  # תווית שאיננו מכירים — לא נחסום בגללה
    if found_greg == str(year):
        return True
    print_box(
        f"שנה שגויה בדף הקורס {code}!  (wrong year on the course page)",
        [
            f"ביקשנו (asked for): {hebrew_year_label(year) or year}  ({year})",
            f"התקבל  (got)      : {found}  ({found_greg})",
            "",
            "הקורס הזה לא ייכנס למערכת — נתונים משנה אחרת גרועים מכלום.",
            "(this course is skipped: wrong-year data is worse than none)",
            f"לבדיקה ידנית: {course_url(code)}",
        ],
        ch="!",
    )
    return False


def parse_page(
    html: str,
    code: str,
    fallback_name: str = "",
    semester: str | None = None,
):
    """עוטף את parser.parse_course_page ומעביר לו את הסמסטר לסינון.

    semester=None פירושו במפורש "בלי סינון" — משתמשים בזה רק לעיון
    (הצגת כל הסמסטרים), אף פעם לא לבניית המערכת עצמה.

    Tolerant on purpose: the `semester=` parameter is new, so an older parser
    build is detected by inspecting the signature rather than by catching
    TypeError — which would also swallow a genuine TypeError from inside it.
    """
    global _SEMESTER_FILTER_WARNED
    if semester and _accepts_kwarg(parser_mod.parse_course_page, "semester"):
        return parser_mod.parse_course_page(
            html, code, fallback_name=fallback_name, semester=semester
        )
    if semester and not _SEMESTER_FILTER_WARNED:
        _SEMESTER_FILTER_WARNED = True
        print_box(
            "הפרסר אינו תומך בסינון סמסטר!  (parser has no semester filter)",
            [
                "גרסת הפרסר שמותקנת אינה מקבלת semester=, ולכן ייתכן מאוד",
                "שמפגשים מסמסטר אחר ייכנסו למערכת.",
                "אין להסתמך על המערכת שתתקבל עד שהפרסר יעודכן.",
                "(meetings from another semester may leak in — do not trust it)",
            ],
            ch="!",
        )
    return parser_mod.parse_course_page(html, code, fallback_name=fallback_name)


def not_offered_headline(entries: list[dict], semester: str, year: str) -> str:
    """שורת הכותרת של הדיווח על קורסים שאינם נפתחים בסמסטר המבוקש."""
    year_he = hebrew_year_label(year) or year
    listed = ", ".join(
        f"{e['code']} {e.get('name', '')}".strip() for e in entries
    )
    return (
        f"הקורסים הבאים אינם נפתחים בסמסטר {semester_geresh(semester)} "
        f"{year_he}: {listed}"
    )


def _pick_entry(entries: list[dict]) -> dict | None:
    """בוחר קורס מתוך הרשימה (אם יש יותר מאחד) לצורך עיון."""
    if len(entries) == 1:
        return entries[0]
    for i, entry in enumerate(entries, start=1):
        print(f"  {i}. {entry['code']}  {entry.get('name', '')}")
    raw = ask("מספר הקורס לעיון (number to inspect): ")
    if not raw.isdigit() or not 1 <= int(raw) <= len(entries):
        print("בחירה לא חוקית. (invalid choice)")
        return None
    return entries[int(raw) - 1]


def inspect_other_semester(entry: dict, semester: str) -> None:
    """מציג את כל המפגשים שבדף הקורס, בכל הסמסטרים — לעיון בלבד.

    זו האפשרות השלישית בדיווח: לראות מה כן קיים בסמסטר האחר, כדי להחליט
    בידיעון מה עושים. הנתונים האלה לעולם אינם נכנסים למערכת — ערבוב
    סמסטרים הוא בדיוק התקלה שהכלי הזה נועד למנוע.
    """
    code = entry["code"]
    result = parse_page(
        entry.get("html", ""),
        code,
        fallback_name=entry.get("name", ""),
        semester=None,  # בכוונה בלי סינון — רוצים לראות הכול
    )
    course = getattr(result, "course", None)
    print()
    print("-" * 74)
    print(f"עיון: {code} {entry.get('name', '')} — כל המפגשים שבדף, בכל הסמסטרים")
    print("(inspection: every meeting on the page, in every semester)")
    print("-" * 74)
    if course is None or not course.groups:
        print("גם בלי סינון סמסטר לא נמצאה אף קבוצה בדף הזה —")
        print("כנראה שהקורס אינו נפתח השנה בכלל. (no groups at all)")
        print(f"לבדיקה ידנית: {course_url(code)}")
        return
    for group in course.groups:
        print(f"  {group.kind}   קבוצה {group.group_id}   {group.lecturer or '—'}")
        if not group.meetings:
            print("      (אין מפגשים בקבוצה הזאת)")
        for meeting in group.meetings:
            mark = getattr(meeting, "semester", "") or "?"
            flag = "   ← הסמסטר המבוקש" if mark == semester else ""
            print(f"      סמסטר {mark}   {meeting}{flag}")
    print()
    print("לעיון בלבד — הנתונים האלה אינם נכנסים למערכת.")
    print("(inspection only — never mixed into the timetable)")
    print(f"לבדיקה ידנית בידיעון: {course_url(code)}")


def report_not_offered(entries: list[dict], semester: str, year: str) -> str:
    """מדווח על קורסים שאינם נפתחים בסמסטר המבוקש, ושואל מה לעשות.

    docs/GROUND_TRUTH.md §6: דף שחוזר תקין ובלי אף קבוצה אינו קריסה — זה בדיוק
    הסימן ש"הקורס לא נפתח בסמסטר הזה". זה רלוונטי מאוד ל-61753 אלגוריתמים,
    שהוא קורס של סמסטר 4 (אביב) ונלקח מוקדם.

    מחזיר "continue" אם ממשיכים בלעדיהם; בחירה בעצירה מפילה QuitRequested.
    """
    lines = [not_offered_headline(entries, semester, year), ""]
    for entry in entries:
        lines.append(f"{entry['code']}  {entry.get('name', '')}".rstrip())
        lines.append(f"    {course_url(entry['code'])}")
    lines += [
        "",
        f"The courses above are not offered in semester {semester} ({year}).",
        "",
        "זו אינה בהכרח תקלה: דף הקורס חזר תקין, פשוט אין בו אף קבוצה",
        f"בסמסטר {semester_geresh(semester)}.",
        "כדאי מאוד לוודא את זה ידנית בידיעון לפני שמוותרים על הקורס.",
    ]
    print_box(
        "קורסים שאינם נפתחים בסמסטר המבוקש  (not offered this term)",
        lines,
        ch="!",
    )

    while True:
        print("מה לעשות? (what now?)")
        print("  1 = להמשיך בלי הקורסים האלה              (continue without them)")
        print("  2 = לעצור כאן                            (abort)")
        print("  3 = להציג את נתוני הסמסטר האחר, לעיון    (inspect other semester)")
        choice = ask("בחירה (your choice): ", default="1")
        if choice == "1":
            print("ממשיכים בלי: " + ", ".join(e["code"] for e in entries))
            return "continue"
        if choice == "2":
            print()
            print("עצרנו. אפשר לבדוק בידיעון ולהריץ שוב. (aborted)")
            raise QuitRequested
        if choice == "3":
            entry = _pick_entry(entries)
            if entry is not None:
                inspect_other_semester(entry, semester)
            continue
        print("לא הבנתי. אפשר 1, 2 או 3. (please answer 1, 2 or 3)")


def target_of(semester: str, year: str) -> dict:
    """רישום יעד יחיד: לאיזה סמסטר ולאיזו שנה נסרקה רשומה אחת."""
    return {
        "semester": str(semester),
        "year": str(year),
        "year_he": hebrew_year_label(year),
    }


def same_target(entry: dict | None, semester: str, year: str) -> bool:
    """האם הרישום של קורס בודד מתאר בדיוק את היעד המבוקש."""
    if not isinstance(entry, dict):
        return False
    return (
        str(entry.get("semester", "")) == str(semester)
        and str(entry.get("year", "")) == str(year)
    )


def describe_target(entry: dict | None) -> str:
    """'סמסטר ב'  תשפ"ז' — לתצוגה בהודעות."""
    if not isinstance(entry, dict):
        return "לא ידוע (unknown)"
    sem = semester_geresh(str(entry.get("semester", ""))) or "?"
    year = str(entry.get("year", ""))
    year_txt = str(entry.get("year_he") or "") or hebrew_year_label(year) or year or "?"
    return f"סמסטר {sem}  {year_txt}"


def save_sections_meta(semester: str, year: str, targets: dict[str, dict]) -> None:
    """שומר לצד הקאש לאיזה סמסטר ולאיזו שנה אקדמית נסרק *כל קורס*.

    בלי הרישום הזה אי אפשר לדעת שקאש שנבנה לסמסטר א' נטען בטעות בריצה
    שמכוונת לסמסטר ב' — וזו שוב מערכת שנראית תקינה ואינה נכונה.

    הרישום הוא לכל קורס בנפרד (``targets``) ולא חותמת גלובלית אחת: קאש
    מעורב נבנה בדיוק מזה שריצה אחת מעדכנת חלק מהקורסים ומשאירה את השאר.
    חותמת אחת לכל הקובץ הייתה מכריזה גם על הקורסים הישנים שהם ביעד הנוכחי.
    ``semester``/``year`` ברמת הקובץ מתארים את *הריצה האחרונה* בלבד.
    """
    payload = {
        "last_run": target_of(semester, year),
        # תאימות לאחור לקוראים ישנים — היעד של הריצה האחרונה, לא של הקאש כולו.
        "semester": str(semester),
        "year": str(year),
        "year_he": hebrew_year_label(year),
        "codes": sorted(targets),
        "targets": {code: dict(targets[code]) for code in sorted(targets)},
    }
    try:
        SECTIONS_META_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SECTIONS_META_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"  לא הצלחנו לשמור את רישום הקאש: {exc}  (meta not saved)")


def load_sections_meta() -> dict:
    """קורא את רישום הקאש. {} אם אינו קיים או שאינו קריא."""
    try:
        with open(SECTIONS_META_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def meta_targets(meta: dict) -> dict[str, dict]:
    """{קוד קורס: היעד שנרשם עבורו} מתוך רישום הקאש.

    רישום ישן (חותמת גלובלית אחת) אינו מתורגם לרישום פר-קורס: הוא אינו
    מעיד על אף קורס בנפרד, ולכן הקורסים שבו נחשבים "בלי רישום".
    """
    raw = meta.get("targets")
    targets: dict[str, dict] = {}
    if isinstance(raw, dict):
        for code, entry in raw.items():
            if isinstance(entry, dict):
                targets[str(code)] = {
                    "semester": str(entry.get("semester", "")),
                    "year": str(entry.get("year", "")),
                    "year_he": str(entry.get("year_he", "")),
                }
    return targets


def check_cache_term(semester: str, year: str, codes: list[str] | None = None) -> None:
    """מזהיר אם קורסים בקאש נבנו לסמסטר או לשנה אחרים מהיעד הנוכחי.

    codes — הקודים שבאמת נטענו מהקאש לריצה הזו. כל קוד נבדק מול היעד
    שנרשם *עבורו*, כדי שקאש מעורב לא יקבל אישור גורף.
    """
    meta = load_sections_meta()
    if not meta:
        print("  (אין רישום סמסטר/שנה לקאש הזה — אם הוא ישן, כדאי --refresh)")
        return
    targets = meta_targets(meta)
    to_check = list(codes) if codes is not None else sorted(targets)
    if not to_check:
        print("  (אין קורסים לבדוק מול רישום הקאש)")
        return

    matched: list[str] = []
    mismatched: list[str] = []
    unrecorded: list[str] = []
    for code in to_check:
        entry = targets.get(code)
        if entry is None:
            unrecorded.append(code)
        elif same_target(entry, semester, year):
            matched.append(code)
        else:
            mismatched.append(code)

    if not mismatched and not unrecorded:
        print(
            f"  כל הקורסים בקאש נסרקו לסמסטר {semester_geresh(semester)} "
            f"{hebrew_year_label(year) or year} — תואם ליעד. (cache matches)"
        )
        return

    lines = [
        f"היעד (target): סמסטר {semester_geresh(semester)}  "
        f"{hebrew_year_label(year) or year}",
        "",
    ]
    if mismatched:
        lines.append("קורסים שנסרקו ליעד אחר (built for a different term/year):")
        lines += [
            f"  • {code}  —  {describe_target(targets.get(code))}"
            for code in sorted(mismatched)
        ]
    if unrecorded:
        if mismatched:
            lines.append("")
        lines.append("קורסים בלי רישום יעד (no per-course record — cannot verify):")
        lines += [f"  • {code}" for code in sorted(unrecorded)]
    lines += [
        "",
        "מפגשים של הקורסים האלה עלולים להיות מסמסטר או משנה אחרים.",
        "מומלץ מאוד להריץ עם --refresh ולסרוק אותם מחדש.",
        "(strongly recommended: re-run with --refresh)",
    ]
    if matched:
        lines += ["", f"תואמים ליעד (verified): {', '.join(sorted(matched))}"]
    print_box("הקאש אינו מאומת מול היעד!  (cache not verified for this target)", lines, ch="!")
    if not ask_yes_no("להמשיך בכל זאת עם הקאש הזה? (use it anyway?)", default=False):
        raise QuitRequested


def scrape_and_parse(
    plan: list[dict],
    profile: dict,
    semester: str | None = None,
    year: str | None = None,
) -> dict[str, Course]:
    """מריץ את הסקרייפר (ההתחברות נעשית ידנית בדפדפן) ומפרסר את התוצאות.

    אין כאן שום טיפול בפרטי התחברות: הסקריפט רק פותח חלון דפדפן אמיתי
    ומחכה. הסיסמה נשארת בין הדפדפן לאתר בלבד.

    semester — הסמסטר שלפיו מסננים את המפגשים ("א").
    year     — השנה הלועזית שהסקרייפר יבחר בבורר השנה ("2027").
    שניהם נלקחים מהפרופיל אם לא הועברו במפורש.

    הקאש (data/sections.json) ממוזג ולא נדרס: קורסים שלא סרקנו עכשיו
    (למשל בריצה עם --codes), קורסים שנכשלו בשליפה וקורסים שחזרו עם שנה
    שגויה — נשמרים כמו שהם. מוחרקים רק קורסים שהדף שלהם נשלף בהצלחה,
    בשנה הנכונה, ולא הכיל אף קבוצה בסמסטר המבוקש.
    (the cache is merged, never replaced — see the comment below)

    Returns:
        רק הנתונים של הריצה הזו: הקורסים שנסרקו עכשיו, ובנוסף רשומות קאש
        ישנות *רק* אם רשום עליהן במפורש שנבנו לאותו סמסטר ולאותה שנה.
        {} אם לא נסרק אף קורס בהצלחה. הקאש בדיסק רחב מזה במכוון — מה
        שנשמר לדיסק ומה שמוחזר לריצה הם שני דברים שונים.
        (the on-disk cache is a superset; only target-verified data is returned)
    """
    # ייבוא עצל — playwright נטען רק כשבאמת סורקים.
    import scraper as scraper_mod

    semester = semester or resolve_semester(profile)
    year = str(year or resolve_year(profile))
    year_he = hebrew_year_label(year) or year

    codes = [c["code"] for c in plan]
    names = {c["code"]: c.get("name", "") for c in plan}

    print()
    print("שלב 3: פתיחת דפדפן והתחברות ידנית לידיעון")
    print("(step 3: opening a browser — the login is typed by you, in it)")
    print("התוכנה לעולם לא מבקשת, לא רואה ולא שומרת שם משתמש או סיסמה.")
    print("(this program never asks for, sees or stores your credentials)")
    print()
    print(f'  היעד: סמסטר {semester_geresh(semester)}   שנה"ל {year_he} ({year})')
    print("  הידיעון נפתח כברירת מחדל בשנה הקודמת — מחליפים שנה במפורש ומאמתים.")
    print("  (the yedion defaults to the previous year; we switch it and verify)")

    kwargs = dict(
        profile_dir=str(BROWSER_PROFILE_DIR),
        raw_dir=str(RAW_DIR),
        headless=False,
    )
    # אם הסקרייפר אינו יודע לקבל year — אסור להמשיך: הוא היה סורק את שנת
    # ברירת המחדל של הידיעון, וזו בדיוק התקלה השקטה שאנחנו מונעים.
    if not _accepts_kwarg(scraper_mod.BraudeScraper.__init__, "year"):
        raise RuntimeError(
            "הסקרייפר המותקן אינו תומך בבחירת שנה אקדמית (year=), ולכן היה "
            "סורק את שנת ברירת המחדל של הידיעון. עצרנו. "
            "(the scraper cannot switch years — refusing to scrape the wrong one)"
        )
    scraper = scraper_mod.BraudeScraper(year=year, **kwargs)

    error_codes: set[str] = set()
    with scraper as sc:
        if not sc.open_and_wait_for_login():
            print("ההתחברות לא הושלמה. (login was not completed)")
            return {}
        html_by_code = sc.scrape(codes)
        for err in getattr(sc, "errors", []) or []:
            print(f"  שגיאת סריקה (scrape error): {err}")
            # השגיאות מגיעות כזוגות (code, message) — שומרים את הקוד
            # כדי לדעת מאוחר יותר שאסור למחוק את הרשומה הישנה שלו.
            if isinstance(err, (tuple, list)) and err:
                error_codes.add(str(err[0]).strip())

    courses: dict[str, Course] = {}
    not_offered: list[dict] = []
    wrong_year: set[str] = set()
    for code, html in (html_by_code or {}).items():
        # אימות שני לשנה, בצד שלנו, לפני שנוגעים בתוכן הדף.
        if not check_page_year(html, code, year):
            wrong_year.add(code)
            continue
        result = parse_page(
            html, code, fallback_name=names.get(code, ""), semester=semester
        )
        for warning in getattr(result, "warnings", []) or []:
            print(f"  אזהרת פירסור {code} (parse warning): {warning}")
        if result.course is not None and result.course.groups:
            courses[code] = result.course
        else:
            # docs/GROUND_TRUTH.md §6: דף תקין בלי אף קבוצה בסמסטר המבוקש אינו
            # קריסה — זה הסימן ש"הקורס לא נפתח בסמסטר הזה".
            print(
                f"  אין קבוצות ל-{code} בסמסטר {semester_geresh(semester)}. "
                f"(no groups in the requested semester)"
            )
            not_offered.append(
                {"code": code, "name": names.get(code, ""), "html": html}
            )

    if not_offered:
        # מדווחים ושואלים — עלול להפיל QuitRequested אם ביקשו לעצור.
        report_not_offered(not_offered, semester, year)

    if not courses:
        # לא שומרים כלום: קאש ישן טוב מקאש ריק. המתקשר ייפול חזרה לקאש.
        return {}

    # ----------------------------------------------------------------------
    # מיזוג לתוך הקאש — לעולם לא דריסה שלו.
    # ריצה עם --codes (או ריצה שבה חלק מהדפים נכשלו) אינה רשאית
    # להשמיד נתונים טובים של קורסים אחרים שנשמרו בעבר.
    # (merge, never replace: a partial run must not destroy other courses)
    # ----------------------------------------------------------------------
    existing: dict[str, Course] = {}
    if SECTIONS_PATH.exists():
        try:
            existing = load_sections_file(SECTIONS_PATH)
        except Exception as exc:  # קאש פגום לא יפיל סריקה מוצלחת
            print(f"  לא הצלחנו לקרוא את הקאש הקיים: {exc}  (cache unreadable)")
    # הרישום הישן נקרא *לפני* שדורסים אותו — הוא מספר לאיזה יעד נבנתה כל
    # רשומה שאינה מהריצה הזו.
    old_targets = meta_targets(load_sections_meta())

    requested = set(codes)
    fetched = set(html_by_code or {})
    # קוד שלא נשלף בכלל, שנרשמה עליו תקלת סריקה, או שהדף שלו חזר משנה
    # אחרת — אין לנו עליו מידע חדש ותקף, ולכן הרשומה הישנה נשמרת כמו שהיא.
    failed = (
        (requested - fetched)
        | (error_codes & requested)
        | (wrong_year & requested)
    )
    # קוד שהדף שלו נשלף בהצלחה, בשנה הנכונה, אך לא הניב אף קבוצה בסמסטר
    # המבוקש — אינו נפתח הסמסטר, ולכן הרשומה הישנה שלו כן מוסרת.
    stale = (fetched - set(courses)) - failed

    merged: dict[str, Course] = {**existing, **courses}
    for code in stale:
        merged.pop(code, None)

    # רישום היעד הוא לכל קורס בנפרד: רק מה שנסרק עכשיו מקבל את היעד של
    # הריצה הזו; לכל השאר נגרר הרישום הישן (ואם אין — אין רישום, ולא
    # מומצא אחד). חותמת גלובלית אחת הייתה מכריזה על כל הקאש כתואם ליעד.
    targets: dict[str, dict] = {}
    for code in merged:
        if code in courses:
            targets[code] = target_of(semester, year)
        elif code in old_targets:
            targets[code] = old_targets[code]

    kept_on_disk = sorted(set(merged) - set(courses))
    SECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    parser_mod.save_sections(merged, str(SECTIONS_PATH))
    save_sections_meta(semester, year, targets)

    # ----------------------------------------------------------------------
    # מה מוחזר לריצה הזו — לא הקאש כולו.
    # רשומה שלא נסרקה עכשיו נכנסת למערכת רק אם רשום עליה במפורש שהיא
    # נבנתה לאותו סמסטר ולאותה שנה. אחרת היא נשארת בדיסק אבל אינה משתתפת
    # בריצה — כך מפגשים מסמסטר אחר אינם זולגים לתוך המערכת בלי שאיש ידע.
    # (return only data verified against this run's target)
    # ----------------------------------------------------------------------
    result: dict[str, Course] = dict(courses)
    reused: list[str] = []
    unverified: list[str] = []
    for code in sorted(failed & set(existing)):
        if same_target(old_targets.get(code), semester, year):
            result[code] = existing[code]
            reused.append(code)
        else:
            unverified.append(code)

    print(f"הנתונים נשמרו בקאש: {SECTIONS_PATH}  (cache saved)")
    print(
        f"  היעד שנרשם (target): סמסטר {semester_geresh(semester)} "
        f"{year_he} ({year})"
    )
    print(f"  עודכנו עכשיו (updated now): {', '.join(sorted(courses))}")
    if reused:
        print_box(
            "נתונים שלא נסרקו בריצה הזו  (data not fetched in this run)",
            [
                f"היעד (target): סמסטר {semester_geresh(semester)}  {year_he}",
                "",
                "הקורסים האלה לא נשלפו עכשיו. הם נלקחו מהקאש רק משום",
                "שרשום עליהם שנסרקו בדיוק ליעד הזה — אבל הם אינם טריים:",
                *[f"  • {code}" for code in reused],
                "",
                "אם הידיעון התעדכן מאז, כדאי להריץ שוב עם --refresh.",
                "(reused from cache: same recorded target, but not fresh)",
            ],
            ch="!",
        )
    if unverified:
        print(
            "  לא נכנסו לריצה — אין רישום שהם נבנו ליעד הזה "
            f"(excluded, target not verified): {', '.join(unverified)}"
        )
    if kept_on_disk:
        print(
            "  נשארו בקאש בדיסק (left in the on-disk cache): "
            f"{', '.join(kept_on_disk)}"
        )
    if stale:
        print(
            "  הוסרו מהקאש — לא נמצאו קבוצות בסמסטר המבוקש "
            f"(removed, not offered): {', '.join(sorted(stale))}"
        )
    if wrong_year:
        print(
            "  דולגו בגלל שנה שגויה בדף (skipped, wrong year): "
            f"{', '.join(sorted(wrong_year))}"
        )
    return result


def obtain_sections(plan: list[dict], profile: dict, args: argparse.Namespace) -> dict[str, Course]:
    """שלב 3 המלא: מחזיר {קוד קורס: Course} מהמקור המתאים.

    סדר ההחלטה:
        --offline  -> קאש, ואם אין — נתוני דמו עם אזהרה רועשת.
        --refresh  -> סריקה מחדש.
        אחרת       -> קאש אם קיים, ואם לא — סריקה.

    הסמסטר והשנה נלקחים מ-args (שם כבר נפתרו מול הפרופיל והדגלים), וכל
    טעינה מהקאש נבדקת מולם — קאש של סמסטר אחר הוא מלכודת שקטה.
    """
    semester = getattr(args, "semester", None) or resolve_semester(profile)
    year = str(getattr(args, "year", None) or resolve_year(profile))
    planned = [c["code"] for c in plan]

    def load_cache_verified() -> dict[str, Course]:
        """טוען את הקאש ובודק כל קורס מבוקש מול היעד שנרשם *עבורו*."""
        cached = load_sections_file(SECTIONS_PATH)
        check_cache_term(semester, year, [c for c in planned if c in cached])
        return cached

    print()
    print("=" * 74)
    print("  שלב 3: נתוני הקבוצות מהידיעון  (step 3: section data)")
    print("=" * 74)
    print(
        f"  היעד: סמסטר {semester_geresh(semester)}   "
        f'שנה"ל {hebrew_year_label(year) or year} ({year})'
    )

    # --- מקור ראשון בעדיפות: מסד הנתונים המתרענן (data/db) -------------------
    # זה המקור *האמיתי* מאז שהוספנו את refresh.py. בלי הבדיקה הזאת הזרימה
    # הייתה נופלת ישר לנתוני הדמו הסינתטיים, ומציגה מערכת שנראית אמיתית
    # לחלוטין אבל מבוססת על מרצים ושעות מומצאים — התקלה המסוכנת ביותר כאן.
    from_store = store_sections(open_store(), planned, semester, year)
    if from_store:
        missing = [c for c in planned if c not in from_store]
        print(f"נטענו {len(from_store)} קורסים ממסד הנתונים (from the database): {DB_ROOT}")
        print_freshness(open_store(), list(from_store), source=str(DB_ROOT))
        if not missing:
            return from_store
        print(
            f"חסרים במסד: {', '.join(missing)} — ממשיכים למקור הבא עבורם. "
            f"(missing from the database)"
        )

    if args.offline:
        # מצב לא-מקוון: אסור לפתוח דפדפן בכלל.
        if SECTIONS_PATH.exists():
            print(f"טוענים מהקאש (loading cache): {SECTIONS_PATH}")
            merged = dict(load_cache_verified())
            merged.update(from_store)  # מה שבמסד גובר על הקאש הישן
            return merged
        if from_store:
            return from_store
        if FIXTURE_PATH.exists():
            warn_demo_data()
            return load_sections_file(FIXTURE_PATH)
        print(
            f"אין קאש ואין קובץ דמו. (no cache at {SECTIONS_PATH} and no fixture "
            f"at {FIXTURE_PATH})"
        )
        return {}

    if args.refresh or not SECTIONS_PATH.exists():
        if not SECTIONS_PATH.exists() and not args.refresh:
            print("אין קאש — צריך לסרוק את הידיעון. (no cache — scraping)")
        try:
            courses = scrape_and_parse(plan, profile, semester=semester, year=year)
        except QuitRequested:
            raise  # בקשת יציאה מפורשת — לא בולעים אותה כ"סריקה שנכשלה"
        except Exception as exc:  # playwright חסר, דפדפן נכשל, אתר השתנה...
            if is_year_error(exc):
                # שגיאת שנה מטופלת בראש הזרימה, עם הסבר מלא בעברית.
                raise
            print()
            print(f"הסריקה נכשלה: {exc}  (scraping failed)")
            courses = {}
        if courses:
            return courses
        # נפילה חיננית: קאש ישן, ואם אין — דמו, רק באישור מפורש.
        if SECTIONS_PATH.exists():
            print(f"נופלים חזרה לקאש הקיים (falling back to cache): {SECTIONS_PATH}")
            return load_cache_verified()
        if FIXTURE_PATH.exists() and ask_yes_no(
            "להמשיך עם נתוני דמו סינתטיים רק כדי לראות איך זה עובד? "
            "(continue with synthetic demo data?)",
            default=False,
        ):
            warn_demo_data()
            return load_sections_file(FIXTURE_PATH)
        return {}

    print(f"טוענים מהקאש (loading cache): {SECTIONS_PATH}")
    cached = load_cache_verified()
    print("(אם הידיעון התעדכן — יש להריץ שוב עם --refresh)")
    return cached


def apply_plan_metadata(courses: dict[str, Course], plan: list[dict]) -> None:
    """משלים ל-Course שם, נ"ז וצמידויות מתוך הידיעון/הפרופיל.

    חשוב במיוחד ל-tied_with: הסקרייפר לא יודע על קורסים צמודים,
    זה מידע שמגיע מתוכנית הלימודים.
    """
    by_code = {c["code"]: c for c in plan}
    for code, course in courses.items():
        meta = by_code.get(code)
        if not meta:
            continue
        if not course.name and meta.get("name"):
            course.name = meta["name"]
        if not course.credits and meta.get("credits"):
            course.credits = float(meta["credits"])
        if not course.tied_with and meta.get("tied_with"):
            # הרשימה המלאה, בלי סינון: scheduler._validate_tied חייב לראות
            # שותף חסר ולא לחשוב שהחבילה שלמה.
            course.tied_with = list(meta["tied_with"])


def report_missing(
    plan: list[dict],
    courses: dict[str, Course],
    semester: str | None = None,
    year: str | None = None,
) -> list[str]:
    """מדווח אילו קורסים לא נמצאו בכלל, ומחזיר את הקודים החסרים."""
    missing = [c["code"] for c in plan if c["code"] not in courses]
    if missing:
        print()
        print("קורסים שלא נמצאו בנתונים (courses with no section data):")
        for code in missing:
            meta = next((c for c in plan if c["code"] == code), {})
            print(f"  • {code}  {meta.get('name', '')}")
            print(f"      {course_url(code)}")
        if semester:
            year_txt = hebrew_year_label(str(year or "")) or str(year or "")
            print(
                f"ייתכן שהקורס אינו נפתח בסמסטר {semester_geresh(semester)} "
                f"{year_txt}, או שהפירסור נכשל."
            )
        else:
            print("ייתכן שהקורס לא נפתח הסמסטר, או שהפירסור נכשל.")
        print("(the course may not be offered this term, or parsing failed)")
    return missing


def enforce_tied_blocks(courses: dict[str, Course]) -> None:
    """מוריד חבילות קורסים צמודים שנשברו — הכל או כלום.

    אם 61756 קיים בנתונים אבל 61757 לא נמצא בידיעון, אי אפשר לשבץ אף אחד
    מהם: הם קורסים צמודים. עדיף לומר זאת בקול רם מאשר שהפותר יזרוק
    TiedCoursesError באמצע.
    """
    while True:
        broken: tuple[str, list[str]] | None = None
        for code, course in courses.items():
            missing = [c for c in (course.tied_with or []) if c not in courses]
            if missing:
                broken = (code, missing)
                break
        if broken is None:
            return
        code, missing = broken
        block = sorted(_tied_block(courses, code))
        print_box(
            "חבילת קורסים צמודים שבורה  (broken tied-course block)",
            [
                f"הקורס {code} חייב להילקח יחד עם: {', '.join(missing)}",
                "אבל אין לקורסים האלה נתוני קבוצות — הם כנראה לא נפתחו,",
                "או שהפירסור נכשל.",
                "",
                f"לכן מורידים מהשיבוץ את כל החבילה: {', '.join(block)}",
                "(the whole tied block is dropped — all or nothing)",
                "",
                "כדאי לבדוק את זה ידנית בידיעון לפני הרישום!",
            ],
            ch="!",
        )
        for member in block:
            courses.pop(member, None)


# ===========================================================================
# שלב 4 — תפריט המרצים לכל קורס
# ===========================================================================
def menu_lecturer_order(course: Course, menu_text: str) -> list[str]:
    """מחזירה את שמות המרצים לפי המספור שמופיע בתפריט שהודפס.

    We print `render.render_lecturer_menu(course)` for the human, but we have
    to map the numbers she types back to lecturer *names*. To stay in sync
    with whatever order the renderer used, we read the numbering straight out
    of the printed text; if that fails we fall back to the same order the
    renderer builds: named lecturers sorted, then the "unknown" bucket last.
    """
    names = course.lecturers()
    # קבוצות בלי שם מרצה מקבלות ב-render שורה אחרונה בשם "מרצה לא ידוע",
    # ולכן היא תופסת מספר בתפריט וחייבת להיות ברשימה שלנו גם כן.
    if any(not g.lecturer.strip() for g in course.groups):
        names = names + [UNKNOWN_LECTURER_HE]
    if not names:
        return []

    found: dict[int, str] = {}
    for line in (menu_text or "").splitlines():
        m = re.match(r"\s*\[?\(?(\d{1,2})[\].):\-]\s+?(.*)", line)
        if not m:
            continue
        index, rest = int(m.group(1)), m.group(2)
        # השם הארוך ביותר שמופיע בשורה — כדי לא להתבלבל בין שמות שהם
        # תת-מחרוזת אחד של השני.
        candidates = [n for n in names if n and n in rest]
        if not candidates:
            continue
        found.setdefault(index, max(candidates, key=len))

    ordered = [found[i] for i in sorted(found)]
    looks_valid = (
        sorted(found) == list(range(1, len(names) + 1))
        and len(set(ordered)) == len(names)
        and sorted(ordered) == sorted(names)
    )
    return ordered if looks_valid else names


def _parse_ranking(raw: str, count: int) -> list[int] | None:
    """'1,3' -> [1,3]. מחזיר None אם הקלט לא חוקי (ואז שואלים שוב)."""
    parts = [p for p in re.split(r"[,\s]+", raw) if p]
    picked: list[int] = []
    for part in parts:
        if not part.isdigit():
            print(f"'{part}' אינו מספר. (not a number)")
            return None
        value = int(part)
        if not 1 <= value <= count:
            print(f"המספר {value} מחוץ לטווח 1-{count}. (out of range)")
            return None
        if value in picked:
            print(f"המספר {value} הופיע פעמיים — מתעלמים מהכפילות. (duplicate ignored)")
            continue
        picked.append(value)
    return picked or None


def ask_lecturer_preferences(
    courses: dict[str, Course], order: list[str]
) -> tuple[dict[str, list[str]], set[str]]:
    """שלב 4: לכל קורס — הצגת המרצים ובקשת דירוג.

    מחזיר (העדפות, קורסים לוותר עליהם):
        העדפות = {קוד קורס: [שמות מרצים לפי סדר עדיפות]}
        ויתורים = קודים שהתבקשה עבורם הורדה ('s')

    קלט מקובל: "1,3" (דירוג), Enter או "any" (ללא העדפה),
    "s" (לוותר על הקורס), "q" (יציאה).
    """
    print()
    print("=" * 74)
    print("  שלב 4: בחירת מרצים  (step 4: choose your lecturers)")
    print("=" * 74)
    print("לכל קורס יוצגו המרצים והשעות שלהם. אפשר:")
    print("  • מספרים לפי סדר העדפה, למשל  1,3   (ranked, best first)")
    print("  • Enter או any  = אין העדפה     (no preference)")
    print("  • s             = לוותר על הקורס (skip / drop this course)")
    print("  • q             = יציאה          (quit)")

    preferred: dict[str, list[str]] = {}
    dropped: set[str] = set()

    for code in order:
        course = courses.get(code)
        if course is None or code in dropped:
            continue

        print()
        print("-" * 74)
        try:
            menu = render_mod.render_lecturer_menu(course)
        except Exception as exc:  # renderer problem must not kill the flow
            menu = ""
            print(f"(לא הצלחנו להציג את תפריט המרצים: {exc})")
        if menu:
            print(menu)

        names = menu_lecturer_order(course, menu)
        if not names:
            print(f"בקורס {code} אין שמות מרצים בנתונים — מדלגים על הדירוג.")
            print("(no lecturer names for this course — nothing to rank)")
            continue

        while True:
            raw = ask(f"דירוג המרצים ל-{code} (your ranking): ").strip()
            low = raw.lower()

            if low in {"", "any", "כל", "לא משנה", "אין"}:
                print("  ← אין העדפה. (no preference)")
                break

            if low in {"s", "skip", "דלג", "ויתור"}:
                block = _tied_block(courses, code)
                if len(block) > 1:
                    print(
                        f"  שימו לב: {code} צמוד ל-{', '.join(c for c in block if c != code)} "
                        f"— ויתור מוריד את כל הבלוק. (tied block: all or nothing)"
                    )
                    if not ask_yes_no(
                        "להוריד את כל הקורסים הצמודים? (drop the whole tied block?)",
                        default=False,
                    ):
                        continue
                dropped.update(block)
                print(f"  ← מוותרים על: {', '.join(sorted(block))}  (dropped)")
                break

            picked = _parse_ranking(raw, len(names))
            if picked is None:
                print(f"יש לנסות שוב: מספרים בין 1 ל-{len(names)}, מופרדים בפסיק. (try again)")
                continue

            ranked = [names[i - 1] for i in picked]
            print(f"  ← סדר העדפה: {' > '.join(ranked)}")
            # "מרצה לא ידוע" אינו שם אמיתי — אי אפשר להעדיף אותו בניקוד.
            real = [n for n in ranked if n != UNKNOWN_LECTURER_HE]
            if real:
                preferred[code] = real
            else:
                print("  (זו קבוצה ללא שם מרצה — נרשם כאין העדפה. no real name to prefer)")
            break

    return preferred, dropped


def _tied_block(courses: dict[str, Course], code: str) -> set[str]:
    """כל הקורסים הצמודים לקוד נתון, כולל הוא עצמו (רק כאלה שקיימים בנתונים)."""
    block = {code}
    course = courses.get(code)
    if course is not None:
        block.update(c for c in (course.tied_with or []) if c in courses)
    # צמידות היא דו-כיוונית: גם מי שמצביע עלינו נכנס לבלוק.
    for other_code, other in courses.items():
        if code in (other.tied_with or []):
            block.add(other_code)
    return block


# ===========================================================================
# שלב 5 — בניית ההעדפות
# ===========================================================================
def build_preferences(
    profile: dict, args: argparse.Namespace, preferred: dict[str, list[str]]
) -> "scheduler_mod.Preferences":
    """בונה אובייקט Preferences מהפרופיל + הדגלים + בחירות המרצים."""
    prefs_json = profile.get("preferences", {}) or {}
    target_days = args.days if args.days else int(prefs_json.get("target_days", 4) or 4)

    weights = dict(prefs_json.get("weights") or {})
    # ימים ומרצים אינם משקולות מאז 2026-10-09 — הם רמות עדיפות (scheduler._sort_key).
    weights.pop("lecturer", None)
    weights.pop("days", None)
    weights.setdefault("gaps", 4.0)
    weights.setdefault("compactness", 1.0)

    earliest = prefs_json.get("earliest")
    latest = prefs_json.get("latest")

    return scheduler_mod.Preferences(
        target_days=target_days,
        preferred_lecturers=preferred,
        blocked_windows=[],
        earliest=int(earliest) if earliest else 0,
        latest=int(latest) if latest else 24 * 60,
        weights={k: float(v) for k, v in weights.items()},
        forbid_friday=bool(prefs_json.get("forbid_friday", False)),
    )


def describe_preferences(prefs: "scheduler_mod.Preferences", codes: list[str]) -> None:
    """מדפיס סיכום קצר של ההעדפות לפני ההרצה."""
    print()
    print("=" * 74)
    print("  שלב 5: מחפשים מערכת  (step 5: searching)")
    print("=" * 74)
    print(f"  קורסים (courses)          : {', '.join(codes)}")
    print(f"  ימים רצויים (target days) : {prefs.target_days}")
    print(f"  משקלים (weights)          : {prefs.weights}")
    if prefs.preferred_lecturers:
        print("  העדפות מרצים (lecturer prefs):")
        for code, names in prefs.preferred_lecturers.items():
            print(f"    {code}: {' > '.join(names)}")
    else:
        print("  העדפות מרצים (lecturer prefs): אין (none)")
    print("...מחשבים, זה יכול לקחת כמה שניות (this can take a few seconds)")


# ===========================================================================
# שלבים 6-7 — פתרון, הצגה, וטיפול בחוסר פתרון
# ===========================================================================
def _reasons_of(exc: Exception, courses: list[Course], prefs) -> list[str]:
    """שולף את סיבות חוסר הפתרון מתוך החריגה, או מריץ אבחון בעצמו."""
    reasons = getattr(exc, "reasons", None)  # Infeasible.reasons
    if isinstance(reasons, str):
        reasons = [reasons]
    if not reasons and isinstance(exc, scheduler_mod.Infeasible):
        # אין סיבות מוכנות — מריצים אבחון בעצמנו.
        try:
            reasons = scheduler_mod.diagnose_infeasibility(courses, prefs)
        except Exception as diag_exc:
            reasons = [f"אבחון נכשל (diagnosis failed): {diag_exc}"]
    if not reasons:
        reasons = [str(exc) or "לא נמצאה אף מערכת אפשרית. (no feasible schedule)"]
    return list(reasons)


def _relax_suggestions(exc: Exception, courses: list[Course], prefs) -> list[str]:
    """הצעות הרפיה — מהחריגה/מהמודול אם קיימות, אחרת הצעות ברירת מחדל."""
    for getter in (
        lambda: exc.relax_suggestions(),  # type: ignore[attr-defined]
        lambda: scheduler_mod.relax_suggestions(courses, prefs),  # type: ignore[attr-defined]
        lambda: scheduler_mod.relax_suggestions(exc),  # type: ignore[attr-defined]
    ):
        try:
            out = getter()
        except Exception:
            continue
        if out:
            return [out] if isinstance(out, str) else list(out)

    # גיבוי מקומי — תמיד יש מה להציע לסטודנטית.
    return [
        f"להעלות את מספר הימים בקמפוס מ-{prefs.target_days} ל-{prefs.target_days + 1} "
        f"(raise target days)",
        "לוותר על קורס אחד — למשל 61753 אלגוריתמים, שנלקח מסמסטר ב' "
        "(drop one course)",
        "לוותר על העדפת מרצה בקורס עמוס (relax a lecturer preference)",
        "לבדוק בידיעון אם נפתחה קבוצה נוספת (check the yedion for another group)",
    ]


def present_results(
    scheds: list,
    courses: dict[str, Course],
    args: argparse.Namespace,
    title: str,
) -> None:
    """שלב 6: הדפסת המערכות, כתיבת ה-HTML, והצעה לפתוח אותו."""
    print()
    print("=" * 74)
    print(f"  שלב 6: נמצאו {len(scheds)} מערכות  (step 6: results)")
    print("=" * 74)

    for i, sched in enumerate(scheds, start=1):
        print()
        print(f"### מערכת מס' {i}  (schedule #{i})")
        # render_terminal כבר כולל את שורת הסיכום, ולכן לא מדפיסים אותה פעמיים.
        try:
            print(render_mod.render_terminal(sched, courses))
        except Exception as exc:
            print(f"(שגיאה בציור המערכת: {exc})  (render error)")
            try:
                print(sched.summary())
            except Exception:
                pass

    # --- קובץ ה-HTML ---
    out_path = Path(args.html).expanduser() if args.html else DEFAULT_HTML_PATH
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        render_mod.render_html(scheds, courses, str(out_path), title=title)
    except TypeError:
        # תאימות אם title אינו keyword במימוש.
        render_mod.render_html(scheds, courses, str(out_path))
    print()
    print("קובץ ה-HTML נכתב אל (HTML written to):")
    print(f"  {out_path}")

    # פתיחה בדפדפן — רק אחרי שאלה, לעולם לא אוטומטית.
    opener = getattr(os, "startfile", None)
    if os.name == "nt" and opener is not None and out_path.exists():
        try:
            if ask_yes_no("לפתוח את הקובץ עכשיו? (open it now?)", default=False):
                opener(str(out_path))  # noqa: S606 — local file, user-approved
        except QuitRequested:
            pass
        except OSError as exc:
            print(f"לא הצלחנו לפתוח את הקובץ: {exc}  (could not open the file)")


def solve_with_retries(
    courses: dict[str, Course], prefs, top_n: int
) -> tuple[list, dict[str, Course]] | None:
    """מריץ את הפותר, ובמקרה של Infeasible מציע הרפיה ומנסה שוב.

    מחזיר (רשימת מערכות, מילון הקורסים שנשארו) או None אם ויתרנו.
    לכל היותר MAX_RETRY_ROUNDS סבבים.
    """
    # SearchExhausted/TiedCoursesError מוגדרים ב-scheduler; getattr כדי לא
    # ליפול אם שם השתנה.
    catchable: tuple = (scheduler_mod.Infeasible,)
    for name in ("SearchExhausted", "TiedCoursesError"):
        cls = getattr(scheduler_mod, name, None)
        if isinstance(cls, type) and issubclass(cls, BaseException):
            catchable = catchable + (cls,)

    for attempt in range(1, MAX_RETRY_ROUNDS + 1):
        course_list = list(courses.values())
        describe_preferences(prefs, sorted(courses))
        try:
            scheds = scheduler_mod.solve(course_list, prefs, top_n=top_n)
            if scheds:
                return scheds, courses
            print("הפותר לא החזיר אף מערכת. (solver returned nothing)")
        except catchable as exc:  # type: ignore[misc]
            print()
            print("=" * 74)
            if isinstance(exc, scheduler_mod.Infeasible):
                print("  שלב 7: אין מערכת אפשרית  (step 7: no feasible schedule)")
            else:
                print("  שלב 7: החיפוש נעצר  (step 7: the search stopped)")
            print("=" * 74)
            for reason in _reasons_of(exc, course_list, prefs):
                print(f"  ✗ {reason}")
            print()
            print("הצעות להרפיה (ways to relax):")
            for suggestion in _relax_suggestions(exc, course_list, prefs):
                print(f"  • {suggestion}")

        if attempt == MAX_RETRY_ROUNDS:
            print()
            print("ניסינו מספיק פעמים. אפשר לערוך את data/profile.json ולהריץ שוב.")
            print("(out of retries — edit the profile and run again)")
            return None

        print()
        print(f"ניסיון {attempt}/{MAX_RETRY_ROUNDS}. מה לעשות? (what now?)")
        print(f"  1 = להעלות ל-{prefs.target_days + 1} ימים בקמפוס (one more day)")
        print("  2 = לוותר על קורס (drop a course)")
        print("  3 = לעצור כאן (stop)")
        choice = ask("בחירתך (your choice): ", default="3")

        if choice == "1":
            prefs.target_days += 1
            print(f"מכוונים עכשיו ל-{prefs.target_days} ימים. (target days raised)")
        elif choice == "2":
            codes = sorted(courses)
            for i, code in enumerate(codes, start=1):
                print(f"  {i}. {code}  {courses[code].name}")
            raw = ask("מספר הקורס לוויתור (number to drop): ")
            if not raw.isdigit() or not 1 <= int(raw) <= len(codes):
                print("בחירה לא חוקית — לא הורדנו כלום. (invalid choice)")
                continue
            victim = codes[int(raw) - 1]
            block = _tied_block(courses, victim)
            if len(block) > 1:
                print(f"הקורס צמוד ל-{', '.join(sorted(block - {victim}))} — יורד כל הבלוק.")
            for code in block:
                courses.pop(code, None)
                prefs.preferred_lecturers.pop(code, None)
            print(f"הורדנו: {', '.join(sorted(block))}  (dropped)")
            if not courses:
                print("לא נשארו קורסים. (no courses left)")
                return None
        else:
            return None

    return None


# ===========================================================================
# main
# ===========================================================================
def run(args: argparse.Namespace) -> int:
    """הזרימה המלאה, שלבים 1-7. מחזיר קוד יציאה."""
    # ---- שלב 1: פרופיל ----------------------------------------------------
    if not PROFILE_PATH.exists():
        print(f"לא נמצא קובץ הפרופיל: {PROFILE_PATH}  (profile not found)")
        return 1
    profile = load_profile(PROFILE_PATH)

    if not CURRICULUM_PATH.exists():
        print(f"לא נמצא קובץ הידיעון: {CURRICULUM_PATH}  (curriculum not found)")
        return 1
    curr = curriculum_mod.load_curriculum(str(CURRICULUM_PATH))

    # ---- היעד: סמסטר ושנה אקדמית ------------------------------------------
    # מקור אמת יחיד לכל שאר הזרימה. --semester / --year גוברים על הפרופיל,
    # ומה שנקבע כאן נכתב בחזרה ל-args כדי שאף שלב לא ינחש מחדש.
    semester = resolve_semester(profile, getattr(args, "semester", None))
    year = resolve_year(profile, getattr(args, "year", None))
    args.semester, args.year = semester, year

    # ---- ניהול רשימת המעקב (--track / --untrack): פעולה עצמאית ויציאה ------
    add_codes = [c.strip() for c in (getattr(args, "track", None) or "").split(",") if c.strip()]
    del_codes = [c.strip() for c in (getattr(args, "untrack", None) or "").split(",") if c.strip()]
    if add_codes or del_codes:
        return manage_tracking(open_store(), add_codes, del_codes)

    # ---- שלב 2: קודי הקורסים ---------------------------------------------
    codes_override = None
    if args.codes:
        codes_override = [c.strip() for c in args.codes.split(",") if c.strip()]

    # --pick: בוחרים מהקטלוג האמיתי של הידיעון ולא מתוכנית הלימודים.
    # זה בדיוק המקרה של קורס חוזר מסמסטר קודם — הוא לא יופיע ברשימת הסמסטר
    # שבתוכנית, אבל הוא כן נפתח בפועל, ולכן הוא חייב להיות בר-בחירה.
    if getattr(args, "pick", False):
        picked = pick_courses(open_store(), curr, profile, preselected=codes_override)
        if picked:
            codes_override = picked
        else:
            print("לא נבחרו קורסים — ממשיכים עם מה שבפרופיל. (nothing picked)")

    plan = resolve_plan(profile, curr, codes_override)
    if not plan:
        print("אין קורסים לשיבוץ. (no courses to schedule)")
        return 1

    target_days = args.days if args.days else int(
        (profile.get("preferences") or {}).get("target_days", 4) or 4
    )
    if not confirm_profile(profile, plan, target_days, semester=semester, year=year):
        print("בסדר. אפשר לערוך את data/profile.json ולהריץ שוב.")
        print("(fine — edit the profile and run again)")
        return 0

    # ---- שלב 3: נתוני הקבוצות --------------------------------------------
    courses = obtain_sections(plan, profile, args)
    if not courses:
        print()
        print("אין נתוני קבוצות — אי אפשר לבנות מערכת. (no section data)")
        print("אפשר לנסות: python main.py --refresh   או   python main.py --offline")
        return 1

    # שומרים רק את הקורסים שביקשנו, בסדר של התוכנית.
    planned_codes = [c["code"] for c in plan]
    courses = {code: courses[code] for code in planned_codes if code in courses}
    apply_plan_metadata(courses, plan)
    report_missing(plan, courses, semester=semester, year=year)
    enforce_tied_blocks(courses)  # קורסים צמודים: הכל או כלום
    if not courses:
        print("אף אחד מהקורסים המבוקשים לא נמצא בנתונים. (none of the requested courses)")
        return 1

    # ---- שלב 4: מרצים -----------------------------------------------------
    preferred, dropped = ask_lecturer_preferences(courses, list(courses))
    for code in dropped:
        courses.pop(code, None)
        preferred.pop(code, None)
    if not courses:
        print("כל הקורסים הורדו — אין מה לשבץ. (all courses dropped)")
        return 0

    # ---- שלב 5-7 ----------------------------------------------------------
    prefs = build_preferences(profile, args, preferred)
    result = solve_with_retries(courses, prefs, top_n=max(1, int(args.top)))
    if result is None:
        return 2
    scheds, courses = result

    # הכותרת משקפת את היעד בפועל (כולל --semester / --year), לא רק את הפרופיל.
    title = (
        f"מערכת שעות — סמסטר {semester_geresh(semester)} "
        f"{hebrew_year_label(year) or year}"
    ).strip()
    present_results(scheds, courses, args, title or "מערכת שעות")

    print()
    print("בהצלחה בסמסטר! (good luck this semester)")
    return 0


def main(argv: list[str] | None = None) -> int:
    """נקודת הכניסה. מחזירה קוד יציאה: 0 תקין, 1 שגיאה, 2 אין פתרון, 130 עצירה."""
    ensure_utf8_stdout()
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    # בדיקות שפיות קטנות על הדגלים.
    if args.top < 1:
        ap.error("--top חייב להיות לפחות 1  (--top must be at least 1)")
    if args.days is not None and not 1 <= args.days <= 6:
        ap.error("--days חייב להיות בין 1 ל-6  (--days must be between 1 and 6)")
    if args.year is not None:
        # מתרגמים כאן כדי שתקלה בשנה תתגלה מיד, לפני שנפתח דפדפן.
        try:
            args.year = hebrew_year_to_gregorian(args.year)
        except TargetTermError as exc:
            ap.error(str(exc))

    try:
        return run(args)
    except QuitRequested:
        print()
        print("יצאנו. להתראות! (bye)")
        return 0
    except KeyboardInterrupt:
        print()
        print("עצרת את התוכנית. להתראות! (interrupted — bye)")
        return 130
    except TargetTermError as exc:
        # סמסטר או שנה שאי אפשר לפענח — עוצרים במקום לנחש.
        print_box(
            "היעד אינו ברור  (unclear target term / year)",
            [
                str(exc),
                "",
                "אפשר לתקן ב-data/profile.json, או לציין --semester / --year.",
            ],
            ch="!",
        )
        return 1
    except Exception as exc:
        # YearSwitchError / YearMismatchError מהסקרייפר: הנתונים היו מגיעים
        # מהשנה הלא נכונה, ולכן עוצרים עם הסבר מלא. כל חריגה אחרת ממשיכה
        # כרגיל (traceback), כדי לא להסתיר באגים אמיתיים.
        if not is_year_error(exc):
            raise
        report_year_error(exc, str(getattr(args, "year", "") or ""))
        return 1


if __name__ == "__main__":
    sys.exit(main())
