"""
src/discovery.py — מה *באמת* נפתח השנה בידיעון (course discovery).

למה המודול הזה קיים
--------------------
תוכנית הלימודים (``data/curriculum.json``) היא **המלצה, לא גזרת גורל**.
קורסים חוזרים מסמסטרים קודמים, ולפעמים הסמסטר בפועל שונה מהתוכנית. לכן
מקור האמת לשאלה "מה מוצע השנה" הוא **הידיעון**, ולא קובץ התוכנית.
התוכנית נשארת שימושית לשמות, נ"ז, קורסי קדם וקורסים צמודים — אבל היא
**אינה** מגבילה את הבחירה.

מכאן נובע הכלל החשוב ביותר בקובץ הזה:
    ``filter_catalog(..., only_curriculum=None)`` — וזו ברירת המחדל —
    פירושה **בלי שום הגבלה לפי התוכנית**. כל קוד קורס שנמצא בידיעון ניתן
    לבחירה, גם אם הוא לא מופיע בתוכנית בכלל.

מה יש כאן
---------
``parse_catalog``              — HTML של דף "רשימת קורסים" -> {code: {name, status}} + אזהרות
``filter_catalog``             — סינון לפי קידומת קוד / טקסט בשם / (אופציונלי) התוכנית
``annotate_with_curriculum``   — העשרה בנתוני התוכנית, בלי לפסול אף קוד
``offered_codes``              — קבוצת הקודים המוצעים
``compare_catalogs``           — מה נוסף / נסגר / שינה שם מאתמול

השנה האקדמית *אינה* נקבעת כאן: היא מצב-סשן בדפדפן (``GROUND_TRUTH.md`` §8).
מי שרוצה לחלץ את השנה מתוך דף שנשמר יכול להשתמש ב-``parser.extract_page_year``;
החתמת הקטלוג בשנה שעבורה נשלף היא באחריות ``src/store.py``.

Technical notes (English):
    * Pure functions. No network, no browser, no disk I/O — the caller supplies
      the HTML. That keeps every test in this area fully offline.
    * Shape-agnostic parsing, exactly like ``src/parser.py``: the yedion is an
      old ASP.NET WebForms app, so nothing here depends on a fixed column index
      or on an auto-generated element id.
    * Anything that cannot be parsed becomes a warning string. Nothing is ever
      dropped silently.
"""

from __future__ import annotations

import copy as _copy
import html as _html
import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

# --------------------------------------------------------------------------
# ייבוא מודולים אחיים.
# הפרויקט מוסיף את src/ ל-sys.path (ראו main.py), ולכן הצורה הרגילה היא
# "from curriculum import ...". ה-fallback קיים כדי ש-"from src import discovery"
# יעבוד גם הוא.
# --------------------------------------------------------------------------
try:  # pragma: no cover - trivial import shim
    from curriculum import iter_all_courses, tied_group
except ImportError:  # pragma: no cover
    from src.curriculum import iter_all_courses, tied_group  # type: ignore[no-redef]

#: כתובת הבסיס של הידיעון. מיובאת מ-scraper כדי שתהיה מוגדרת במקום אחד בלבד.
#: ה-import עטוף כי scraper מייבא playwright, ואנחנו רוצים ש-discovery יישאר
#: ניתן לייבוא גם בסביבה שבה playwright לא מותקן (בדיקות אופליין).
#: Broad except on purpose: a missing playwright raises ImportError, but a
#: half-installed one can raise other errors at import time.
try:  # pragma: no cover - import shim
    from scraper import BASE_URL
except Exception:  # pragma: no cover
    try:
        from src.scraper import BASE_URL  # type: ignore[no-redef]
    except Exception:
        BASE_URL = "https://info.braude.ac.il/yedion/fireflyweb.aspx"


__all__ = [
    "CATALOG_URL",
    "CATALOG_PRGNAME",
    "CATALOG_ARGUMENTS",
    "COURSE_BUTTON_PRGNAME",
    "STATUS_TAUGHT",
    "KNOWN_STATUSES",
    "EXPECTED_FIXTURE_COURSES",
    "parse_catalog",
    "filter_catalog",
    "annotate_with_curriculum",
    "offered_codes",
    "compare_catalogs",
    "self_check",
]


# ==========================================================================
# 0. קבועים — כתובת הקטלוג והמחרוזות שמופיעות בדף
# ==========================================================================

#: ה-prgname של מסך "רשימת קורסים לפי התחום המבוקש" (GROUND_TRUTH §1).
CATALOG_PRGNAME = "S_LOOK_FOR_NOSE_AB"

# ==========================================================================
#  !!! חשוב מאוד — לא לתקן את זה ל"לולאה על כל האותיות" !!!
# ==========================================================================
# הארגומנט של המסך הזה *נראה* כאילו הוא אות עברית ("-Aא", "-Aמ", "-Aש"),
# ובאמת ככה הכפתורים בדף בנויים. אבל נבדק מול מופע חי: השרת **מתעלם**
# מהאות לחלוטין ומחזיר את כל הקטלוג בכל מקרה. "-Aא", "-Aמ", "-Aש" ו-"-A"
# החזירו תשובות **זהות בייט-בייט** (566,762 בתים, 1172 קורסים, 25 אותיות
# פתיחה שונות).
#
# מסקנה מעשית: כל הקטלוג עולה **בקשה אחת**. מעבר על 22 אותיות היה מייצר
# פי 22 עומס על השרת של המכללה — עבור בדיוק אותם נתונים. אסור.
# Do NOT "fix" this into an alphabet loop: it is 22x the load on the college's
# server for byte-identical data.
CATALOG_ARGUMENTS = "-A"

#: הבקשה היחידה שמביאה את כל הקטלוג של השנה שנבחרה בסשן.
CATALOG_URL = f"{BASE_URL}?prgname={CATALOG_PRGNAME}&arguments={CATALOG_ARGUMENTS}"

#: ה-prgname שמופיע על הכפתור "חיפוש קורס במערכת השעות" בכל שורת קורס.
#: נוכחותו היא הסימן הבטוח שהשורה היא באמת שורת קורס ולא כותרת/כותרת-תחתונה.
COURSE_BUTTON_PRGNAME = "S_LOOK_FOR_NOSE"

#: ערך הסטטוס היחיד שנצפה בפועל בעמודה "האם נלמד".
STATUS_TAUGHT = "נלמד"

#: סטטוסים מוכרים. ערך שאינו ברשימה **נשמר** ומיוצר עליו warning —
#: לעולם לא מוחקים קורס רק כי לא הכרנו את הסטטוס שלו.
KNOWN_STATUSES: frozenset[str] = frozenset({STATUS_TAUGHT})

#: מספר הקורסים בפיקסצ'ר הייחוס tests/fixtures/real_yedion/catalog_all_courses.html.
#: משמש כבדיקת שפיות ב-self_check ובבדיקות.
EXPECTED_FIXTURE_COURSES = 1172

#: קוד קורס בידיעון: 4 עד 7 ספרות (נצפו 5 ו-6 ספרות בפועל).
_CODE_RE = re.compile(r"\d{4,7}")

#: הקוד שנושא הכפתור, למשל data-arguments="-N93567".
_BUTTON_CODE_RE = re.compile(r"-N\s*(\d{4,7})")

#: תווי בקרה דו-כיווניים (bidi) שמסתתרים ב-HTML עברי ומשגעים כל השוואה.
#: נכתבים כקודים ולא כתווים ממש — תו בלתי-נראה בקוד מקור הוא מלכודת.
_BIDI_CODEPOINTS: tuple[int, ...] = (
    0x200B, 0x200C, 0x200D, 0x200E, 0x200F,   # ZWSP, ZWNJ, ZWJ, LRM, RLM
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,   # LRE, RLE, PDF, LRO, RLO
    0x2066, 0x2067, 0x2068, 0x2069,           # LRI, RLI, FSI, PDI
    0xFEFF,                                   # BOM
)
_BIDI_RE = re.compile("[" + "".join(chr(c) for c in _BIDI_CODEPOINTS) + "]")

#: ישות HTML *תקינה* בלבד (עם נקודה-פסיק). מכוון: לא נוגעים ב-"&nbsp" בלי
#: נקודה-פסיק, כדי לא לשנות טקסט שכבר פוענח פעם אחת על ידי BeautifulSoup.
_ENTITY_RE = re.compile(r"&(?:#\d{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")


# ==========================================================================
# 1. ניקוי טקסט
# ==========================================================================
def _clean(text: Any) -> str:
    """מנקה תא: מפענח ישויות HTML, מוריד &nbsp; ותווי bidi, מכווץ רווחים.

    שלושת הכללים מ-GROUND_TRUTH §4 שאסור לוותר עליהם:
      1. כל ``div.col`` מתחיל ב-``&nbsp;`` — צריך להוריד גם U+00A0 וגם רווח רגיל.
      2. טקסט עברי מכיל ``&quot;`` (``ד&quot;ר`` -> ``ד"ר``) — חובה ``html.unescape``.
      3. תווי bidi בלתי-נראים מופיעים באמצע שמות ושוברים כל השוואה.

    שימו לב: הגרשיים העבריים (״ ׳) **נשמרים כמו שהם**. הפונקציה הזאת מנקה
    "לכלוך" טכני בלבד ולא מעצבת מחדש שמות קורסים — שם קורס חייב לחזור
    מהקטלוג בדיוק כפי שהופיע בידיעון.

    Args:
        text: מחרוזת, אלמנט BeautifulSoup, או None.

    Returns:
        מחרוזת נקייה בשורה אחת (ייתכן ריקה).
    """
    if text is None:
        return ""
    if isinstance(text, str):
        raw = text
    else:
        # הידיעון של בראודה מזריק תווית נגישות לתוך כל תא:
        #   <div class="col InRange"><span class="LabelIn">קוד קורס:&nbsp;</span>421315</div>
        # בלי להסיר אותה, טקסט התא הוא "קוד קורס: 421315" ולא "421315", והבדיקה
        # ש"התא הראשון הוא 4-7 ספרות" נכשלת על *כל* השורות — הקטלוג חזר ריק
        # למרות 572 קורסים בדף. גרסת תל-אביב-יפו לא כללה את הספאנים האלה.
        node = text
        try:
            if text.select_one("span.LabelIn, .sr-only") is not None:
                node = _copy.copy(text)
                for label in node.select("span.LabelIn, .sr-only"):
                    label.decompose()
        except Exception:  # noqa: BLE001 — עדיף טקסט גולמי מאשר קריסה
            node = text
        raw = node.get_text(" ", strip=True)
    out = str(raw)
    # Guarded unescape: only touch text that actually contains a valid entity,
    # so a literal "&" in a course name is never mangled by a second pass.
    if "&" in out and _ENTITY_RE.search(out):
        out = _html.unescape(out)
    out = out.replace(" ", " ")  # U+00A0 written as an escape: never an invisible char in source
    out = _BIDI_RE.sub("", out)
    out = re.sub(r"\s+", " ", out)
    return out.strip()


def _norm_name(text: Any) -> str:
    """גרסת-השוואה של שם קורס: אותיות קטנות, גרשיים אחידים, בלי רווח כפול.

    משמשת רק להשוואות ולחיפוש טקסט — **לא** לשמירה. מה שנשמר הוא תמיד
    השם המקורי מהידיעון.
    """
    out = _clean(text).lower()
    out = out.replace("״", '"').replace("”", '"').replace("“", '"')
    out = out.replace("׳", "'").replace("’", "'").replace("‘", "'")
    return out


def _norm_code(code: Any) -> str:
    """מנרמל קוד קורס למחרוזת נקייה. None / ריק -> ""."""
    if code is None:
        return ""
    return _clean(str(code))


def _as_tuple(value: str | Iterable[str] | None) -> tuple[str, ...]:
    """מקבל מחרוזת בודדת *או* איטרבל של מחרוזות ומחזיר tuple.

    נוחות למי שקורא: ``code_prefixes="61"`` ו-``code_prefixes=("61","62")``
    שניהם עובדים. מחרוזת בודדת אינה מפורקת לתווים — זו טעות קלאסית.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    return tuple(_clean(v) for v in value if _clean(v))


# ==========================================================================
# 2. parse_catalog — פענוח דף הקטלוג
# ==========================================================================
def _soup(page_html: str, warnings: list[str]) -> BeautifulSoup:
    """בונה BeautifulSoup עם lxml, ונופל בחזרה ל-html.parser אם צריך."""
    try:
        return BeautifulSoup(page_html, "lxml")
    except Exception as exc:  # pragma: no cover - lxml is installed
        warnings.append(
            f"lxml נכשל ({exc}); נעשה שימוש ב-html.parser (parser fallback)."
        )
        return BeautifulSoup(page_html, "html.parser")


def _is_col(tag: Any) -> bool:
    """האם האלמנט הוא "תא" בגריד של Bootstrap — class ``col`` או ``col-*``."""
    classes = tag.get("class") or []
    return any(c == "col" or c.startswith("col-") for c in classes)


def _row_cells(row: Any) -> list[Any]:
    """תאי השורה. מעדיף ילדים ישירים, ורק אם אין — יורד לצאצאים.

    למה: אם מתישהו יעטפו כל תא ב-div נוסף, החיפוש הישיר יחזיר 0 והנפילה
    לצאצאים תציל את הפענוח. בפיקסצ'ר האמיתי התאים הם ילדים ישירים.
    """
    direct = [c for c in row.find_all("div", recursive=False) if _is_col(c)]
    if direct:
        return direct
    return [c for c in row.find_all("div") if _is_col(c)]


def _course_button_code(row: Any) -> str | None:
    """הקוד שעל כפתור "חיפוש קורס במערכת השעות", או None אם אין כפתור כזה.

    נוכחות הכפתור (``data-progname="S_LOOK_FOR_NOSE"``) היא התנאי השני
    לזיהוי שורת קורס. מחזירים גם את הקוד שעליו כדי להצליב מול עמודה 0.
    """
    for tag in row.find_all(attrs={"data-progname": True}):
        if _clean(tag.get("data-progname")).upper() != COURSE_BUTTON_PRGNAME:
            continue
        match = _BUTTON_CODE_RE.search(_clean(tag.get("data-arguments") or ""))
        return match.group(1) if match else ""
    return None


def _iter_rows(soup: BeautifulSoup) -> Iterator[Any]:
    """כל ``div.row`` בדף, בלי שורות-מכולה שמכילות שורות אחרות בתוכן."""
    for row in soup.select("div.row"):
        # שורה שמכילה שורה אחרת היא מכולה, לא שורת נתונים — נדלג עליה
        # ונפגוש את הפנימית בסיבוב הבא. (בפיקסצ'ר אין כאלה, זו רשת ביטחון.)
        if row.select_one("div.row") is not None:
            continue
        yield row


def parse_catalog(html: str) -> tuple[dict[str, dict], list[str]]:
    """מפענח דף "רשימת קורסים" של הידיעון.

    מבנה הדף (GROUND_TRUTH §2): הכול ``div.row`` / ``div.col``, **אין**
    ולו ``<table>`` אחד בעמוד. פרסר שמחפש טבלאות ימצא אפס שורות.

    שורה נחשבת שורת קורס אך ורק אם מתקיימים **שני** התנאים:
      1. התא הראשון הוא 4-7 ספרות (קוד קורס), וגם
      2. יש בשורה כפתור עם ``data-progname="S_LOOK_FOR_NOSE"``.
    כך שורת הכותרת ("קוד קורס / שם קורס / האם נלמד") והכותרת התחתונה
    נופלות מעצמן, בלי להסתמך על מיקום.

    מיפוי העמודות: 0 = קוד, 1 = שם, 2 = סטטוס.

    Args:
        html: ה-HTML הגולמי של הדף (מחרוזת utf-8 כבר מפוענחת).

    Returns:
        (courses, warnings) כאשר courses הוא
        ``{code: {"name": str, "status": str}}`` ממוין לפי קוד,
        ו-warnings היא רשימת מחרוזות בעברית. אף פעם לא None.

    Notes:
        * סטטוס לא מוכר **נשמר**, עם אזהרה שמציינת את הערך במפורש.
        * קוד כפול -> נשמרת המופע הראשון, ונרשמת אזהרה על ההתנגשות.
        * דף ריק / דף התחברות -> dict ריק + אזהרה ברורה, לא חריגה.
    """
    warnings: list[str] = []
    courses: dict[str, dict] = {}

    if not html or not html.strip():
        warnings.append("דף הקטלוג ריק — לא הוחזר HTML כלל (empty catalog page).")
        return {}, warnings

    soup = _soup(html, warnings)

    rows_seen = 0
    unknown_status: dict[str, int] = {}

    for row in _iter_rows(soup):
        rows_seen += 1
        cells = _row_cells(row)
        if not cells:
            continue

        code = _clean(cells[0])
        if not _CODE_RE.fullmatch(code):
            continue  # כותרת, כותרת תחתונה, או שורת עיצוב — לא שורת קורס

        button_code = _course_button_code(row)
        if button_code is None:
            # קוד בתא הראשון אבל בלי כפתור חיפוש: לא שורת קורס לפי ההגדרה.
            # נרשם כאזהרה כי זה בדיוק סוג הדבר שישתנה אם התבנית תשתנה.
            warnings.append(
                f"שורה עם קוד {code} דולגה — אין בה כפתור {COURSE_BUTTON_PRGNAME} "
                f"(row skipped: no course button)."
            )
            continue

        if button_code and button_code != code:
            warnings.append(
                f"אי-התאמה בשורת הקטלוג: בעמודה הראשונה {code} ועל הכפתור "
                f"{button_code} — נלקח {code} (code mismatch)."
            )

        name = _clean(cells[1]) if len(cells) > 1 else ""

        # עמודה 2 = סטטוס. אם בתא הזה יושב דווקא כפתור החיפוש, סימן שהשורה
        # קצרה מהצפוי (חסרה עמודה) — עדיף סטטוס ריק מאשר תווית של כפתור.
        status_cell = cells[2] if len(cells) > 2 else None
        if status_cell is not None and _course_button_code(status_cell) is not None:
            warnings.append(
                f"שורת הקורס {code} קצרה מהצפוי — אין עמודת סטטוס (short catalog row)."
            )
            status_cell = None
        status = _clean(status_cell) if status_cell is not None else ""

        if not name:
            warnings.append(f"לקורס {code} אין שם בקטלוג (missing course name).")

        if status not in KNOWN_STATUSES:
            # לא מוחקים! רק סופרים ומדווחים בסוף, כדי לא להציף באלף אזהרות זהות.
            label = status or "(ריק)"
            unknown_status[label] = unknown_status.get(label, 0) + 1

        if code in courses:
            previous = courses[code]
            warnings.append(
                f"קוד {code} מופיע יותר מפעם אחת בקטלוג — נשמרה המופע הראשון "
                f"('{previous['name']}'), הושמט '{name}' (duplicate code)."
            )
            continue

        courses[code] = {"name": name, "status": status}

    for label, count in sorted(unknown_status.items()):
        warnings.append(
            f"סטטוס לא מוכר בקטלוג: '{label}' ב-{count} קורסים — הקורסים נשמרו, "
            f"כדאי לבדוק אותם בידיעון (unknown status kept)."
        )

    if not courses:
        warnings.append(
            f"לא נמצא אף קורס בדף הקטלוג ({rows_seen} שורות נסרקו). ייתכן שהסשן "
            f"פג ושהתקבל דף התחברות, או שמבנה הדף השתנה (no courses parsed)."
        )

    # מיון לפי קוד — כדי שקובץ ה-JSON שנשמר יהיה יציב ושה-diff היומי יהיה קריא.
    return {code: courses[code] for code in sorted(courses)}, warnings


# ==========================================================================
# 3. filter_catalog — סינון
# ==========================================================================
def _curriculum_code_set(curr: dict | None) -> set[str]:
    """כל קודי הקורסים שמופיעים בתוכנית — גם בסמסטרים וגם באשכולות הבחירה.

    רשומות עם ``"code": null`` (קורס כללי, ספורט, "קורס בחירה מאשכול")
    פשוט מדולגות — אין להן קוד להשוות אליו.
    """
    if not curr:
        return set()
    return {
        _norm_code(entry.get("code"))
        for _source, entry in iter_all_courses(curr)
        if _norm_code(entry.get("code"))
    }


def filter_catalog(
    catalog: dict[str, dict],
    *,
    code_prefixes: str | Iterable[str] | None = None,
    name_contains: str | Iterable[str] | None = None,
    only_curriculum: dict | None = None,
) -> dict[str, dict]:
    """מסנן את הקטלוג. **ברירת המחדל היא בלי שום סינון.**

    Args:
        catalog: התוצאה של ``parse_catalog`` (או כל dict בצורה ``{code: {...}}``).
        code_prefixes: קידומת אחת או כמה, למשל ``("61", "62", "65")`` לקורסי
            הנדסת תוכנה. קוד נשמר אם הוא מתחיל ב*אחת* מהן.
        name_contains: מחרוזת אחת או כמה. שם נשמר אם הוא מכיל *אחת* מהן
            (השוואה חסינה לגרשיים עבריים, ל-nbsp ולרווחים כפולים).
        only_curriculum: dict של תוכנית הלימודים. אם הועבר — יישמרו רק קודים
            שמופיעים בתוכנית (בסמסטר כלשהו או באשכול בחירה כלשהו).

            **``None`` (ברירת המחדל) = בלי הגבלה לפי התוכנית.** זו לא סתם
            ברירת מחדל נוחה — זו הדרישה עצמה: הסטודנט/ית רשאי/ת לקחת קורס
            שחוזר מסמסטר קודם או קורס שלא מופיע בתוכנית כלל, והכלי לא אמור
            לחסום את זה. אין להפוך את הברירה הזאת.

    Returns:
        dict חדש (הערכים מועתקים העתקה רדודה) הכולל רק את מה שעבר את כל
        התנאים שהופעלו. התנאים מצטרפים ב-AND ביניהם.
    """
    prefixes = _as_tuple(code_prefixes)
    needles = tuple(_norm_name(n) for n in _as_tuple(name_contains))
    allowed = _curriculum_code_set(only_curriculum) if only_curriculum else None

    out: dict[str, dict] = {}
    for code, info in (catalog or {}).items():
        code = _norm_code(code)
        if not code:
            continue

        if prefixes and not any(code.startswith(p) for p in prefixes):
            continue

        if needles:
            name = _norm_name((info or {}).get("name", ""))
            if not any(needle in name for needle in needles):
                continue

        # only_curriculum=None -> allowed is None -> שום סינון לפי התוכנית.
        if allowed is not None and code not in allowed:
            continue

        out[code] = dict(info or {})

    return out


# ==========================================================================
# 4. annotate_with_curriculum — העשרה, לא סינון
# ==========================================================================
def _curriculum_index(curr: dict | None) -> dict[str, tuple[str, dict]]:
    """אינדקס ``{code: (source, entry)}``, מופע ראשון מנצח.

    "מופע ראשון" חשוב: הקוד 251100 מופיע בשני אשכולות בחירה, ו-``find_course``
    מחזיר תמיד את הראשון לפי הסדר הקבוע של ``iter_all_courses``. האינדקס כאן
    מתנהג בדיוק אותו דבר, כדי שלא יהיו שתי תשובות שונות לאותה שאלה.

    Built once instead of calling find_course() per code — 1172 catalog codes
    times a linear scan of the curriculum is wasteful for no reason.
    """
    index: dict[str, tuple[str, dict]] = {}
    if not curr:
        return index
    for source, entry in iter_all_courses(curr):
        code = _norm_code(entry.get("code"))
        if code:
            index.setdefault(code, (source, entry))
    return index


def _semester_and_cluster(source: str) -> tuple[str | None, str | None]:
    """מפרק תווית מקור: "semester:5" -> ("5", None), "cluster:מדעים" -> (None, "מדעים")."""
    if source.startswith("semester:"):
        return source.split(":", 1)[1], None
    if source.startswith("cluster:"):
        return None, source.split(":", 1)[1]
    return None, None


def annotate_with_curriculum(catalog: dict[str, dict], curr: dict) -> dict[str, dict]:
    """מוסיף לכל קורס בקטלוג את מה שידוע עליו מתוכנית הלימודים.

    השדות שנוספים לקורס שנמצא בתוכנית:
        ``in_curriculum``       True
        ``curriculum_semester`` "1".."8", או None אם הקורס יושב באשכול בחירה
        ``credits``             נ"ז לפי התוכנית, או None אם לא רשום
        ``cluster``             שם אשכול הבחירה, או None
        ``tied_with``           קורסים צמודים (סגור טרנזיטיבית, בלי הקורס עצמו)
        ``prereq``              רשימת קודי קדם לפי התוכנית

    קוד שאינו בתוכנית מקבל ``{"in_curriculum": False}`` בלבד (בנוסף לשם
    ולסטטוס שהגיעו מהקטלוג).

    **קוד שאינו בתוכנית נשאר בר-בחירה לכל דבר.** הפונקציה הזאת *מעשירה*
    ואינה *מסננת*: היא מחזירה בדיוק את אותם קודים שקיבלה, אף אחד לא נופל.
    זה בדיוק המצב של קורס שחוזר מסמסטר קודם, של קורס מתוכנית ישנה, ושל
    קורס מחוץ למחלקה — כולם מקרים לגיטימיים לחלוטין ולא שגיאות.
    This function annotates; it never filters. Out-of-curriculum codes stay
    selectable.

    Args:
        catalog: ``{code: {...}}`` — למשל הפלט של ``parse_catalog``.
        curr: תוכנית הלימודים (``curriculum.load_curriculum``). גם ``None``
            או dict ריק מותרים — אז הכול יסומן ``in_curriculum: False``.

    Returns:
        dict חדש באותו סדר ובאותם מפתחות כמו הקלט, עם ערכים מועשרים.
    """
    index = _curriculum_index(curr)
    out: dict[str, dict] = {}

    for raw_code, info in (catalog or {}).items():
        code = _norm_code(raw_code)
        enriched = dict(info or {})

        found = index.get(code)
        if found is None:
            # לא בתוכנית — וזה בסדר גמור. הקורס נשאר ברשימה ובר-בחירה.
            enriched["in_curriculum"] = False
            out[raw_code] = enriched
            continue

        source, entry = found
        semester, cluster = _semester_and_cluster(source)

        # tied_group סוגר את הקשר טרנזיטיבית ודו-כיוונית ומחזיר גם את הקוד
        # עצמו — מסירים אותו כדי ש-tied_with יהיה "מי עוד", כמו בתוכנית.
        tied = [other for other in tied_group(curr, code) if other != code]

        enriched.update(
            {
                "in_curriculum": True,
                "curriculum_semester": semester,
                "credits": entry.get("credits"),
                "cluster": cluster,
                "tied_with": tied,
                "prereq": [
                    _norm_code(p) for p in (entry.get("prereq") or []) if _norm_code(p)
                ],
            }
        )
        out[raw_code] = enriched

    return out


# ==========================================================================
# 5. עזרים לעבודת הרענון היומית
# ==========================================================================
def offered_codes(catalog: dict[str, dict]) -> set[str]:
    """קבוצת קודי הקורסים שמופיעים בקטלוג.

    זו התשובה לשאלה "האם 61753 בכלל נפתח השנה?" — ``"61753" in offered_codes(cat)``.
    """
    return {c for c in (_norm_code(code) for code in (catalog or {})) if c}


def _name_of(value: Any) -> str:
    """שם הקורס מתוך ערך הקטלוג. סובלני: גם dict וגם מחרוזת שם עירומה."""
    if isinstance(value, dict):
        return _clean(value.get("name", ""))
    return _clean(value)


def compare_catalogs(
    old: dict[str, Any], new: dict[str, Any]
) -> dict[str, list]:
    """משווה שני קטלוגים — אתמול מול היום.

    זה מה שמאפשר לעבודת הרענון לומר "נפתח קורס חדש" או "קורס נסגר", במקום
    להחליף קובץ בשקט. שינוי סטטוס בתוך הקטלוג נשאר גלוי בערכים עצמם.

    Args:
        old: הקטלוג הקודם (``{code: {...}}``, או ``{code: "שם"}``).
        new: הקטלוג החדש.

    Returns:
        ``{"added": [code, ...], "removed": [code, ...],
           "renamed": [(code, old_name, new_name), ...]}``
        כל הרשימות ממוינות לפי קוד. השוואת השמות מתעלמת מהבדלי רווחים,
        nbsp וגרשיים — כדי שלא נדווח על "שינוי שם" שהוא רק רעש טיפוגרפי —
        אבל מדווחת את השמות המקוריים כפי שהם.
    """
    old = old or {}
    new = new or {}

    old_codes = offered_codes(old)
    new_codes = offered_codes(new)

    added = sorted(new_codes - old_codes)
    removed = sorted(old_codes - new_codes)

    renamed: list[tuple[str, str, str]] = []
    for code in sorted(old_codes & new_codes):
        before = _name_of(old.get(code))
        after = _name_of(new.get(code))
        if _norm_name(before) != _norm_name(after):
            renamed.append((code, before, after))

    return {"added": added, "removed": removed, "renamed": renamed}


# ==========================================================================
# 6. בדיקה עצמית — רצה מול הפיקסצ'ר האמיתי
# ==========================================================================
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
FIXTURE_CATALOG: Path = (
    PROJECT_ROOT / "tests" / "fixtures" / "real_yedion" / "catalog_all_courses.html"
)


def self_check() -> int:
    """מריצה את המודול מול דף הקטלוג האמיתי ומאמתת את מה שנמדד בפועל.

    Returns:
        0 אם הכול תקין, 1 אם הפיקסצ'ר חסר.

    Raises:
        AssertionError: אם משהו במבנה הדף השתנה בלי שנשים לב.
    """
    if not FIXTURE_CATALOG.is_file():
        print(f"פיקסצ'ר הקטלוג לא נמצא: {FIXTURE_CATALOG} (fixture missing)")
        return 1

    # encoding="utf-8" חובה — ב-Windows ברירת המחדל היא cp1255 והדף עברי.
    with open(FIXTURE_CATALOG, encoding="utf-8") as fh:
        page = fh.read()

    catalog, warnings = parse_catalog(page)

    print(f"קטלוג: {len(catalog)} קורסים, {len(warnings)} אזהרות")
    for warning in warnings[:10]:
        print(f"  ! {warning}")

    assert len(catalog) == EXPECTED_FIXTURE_COURSES, (
        f"ציפינו ל-{EXPECTED_FIXTURE_COURSES} קורסים בפיקסצ'ר וקיבלנו {len(catalog)} — "
        f"מבנה דף הקטלוג כנראה השתנה (catalog course count changed)"
    )
    assert all(_CODE_RE.fullmatch(code) for code in catalog), "קוד קורס לא תקין בקטלוג"
    assert all(
        set(info) == {"name", "status"} for info in catalog.values()
    ), "מבנה הערך בקטלוג השתנה"

    # שמות עם גרשיים ועם סוגריים חייבים לשרוד את הפענוח כמו שהם.
    quoted = [c for c, i in catalog.items() if '"' in i["name"]]
    parens = [c for c, i in catalog.items() if "(" in i["name"]]
    assert quoted and parens, "לא נמצאו שמות עם גרשיים/סוגריים — הניקוי אגרסיבי מדי?"
    print(f"  שמות עם גרשיים: {len(quoted)} | עם סוגריים: {len(parens)}")
    print(f"  לדוגמה: {quoted[0]} = {catalog[quoted[0]]['name']}")

    # סינון: ברירת המחדל לא מסננת כלום.
    assert filter_catalog(catalog) == catalog, "ברירת המחדל של filter_catalog סיננה משהו"

    by_prefix = filter_catalog(catalog, code_prefixes=("61", "62", "65"))
    assert all(c[:2] in {"61", "62", "65"} for c in by_prefix)
    print(f"  סינון לפי קידומת 61/62/65: {len(by_prefix)} קורסים")

    single = filter_catalog(catalog, code_prefixes="93")  # מחרוזת בודדת, לא רשימה
    assert all(c.startswith("93") for c in single) and single

    # העשרה מול התוכנית — בלי לאבד אף קוד.
    try:  # pragma: no cover - the curriculum ships with the project
        from curriculum import load_curriculum
    except ImportError:  # pragma: no cover
        from src.curriculum import load_curriculum  # type: ignore[no-redef]

    curr = load_curriculum()
    annotated = annotate_with_curriculum(catalog, curr)
    assert set(annotated) == set(catalog), "annotate_with_curriculum איבד או הוסיף קודים"

    inside = [c for c, i in annotated.items() if i["in_curriculum"]]
    outside = [c for c, i in annotated.items() if not i["in_curriculum"]]
    print(f"  בתוכנית: {len(inside)} | מחוץ לתוכנית: {len(outside)} (וכולם ניתנים לבחירה)")
    assert outside, "ציפינו לקורסים מחוץ לתוכנית — הקטלוג הוא של כל המכללה"
    assert all(set(annotated[c]) == {"name", "status", "in_curriculum"} for c in outside)

    # סינון לפי התוכנית — קיים, אבל הוא לעולם לא ברירת המחדל.
    restricted = filter_catalog(catalog, only_curriculum=curr)
    assert len(restricted) <= len(catalog)
    print(f"  only_curriculum (לא ברירת מחדל!): {len(restricted)} קורסים")

    # הפיקסצ'ר הוא של מכללה אחרת (MTA), ולכן אף קוד בו אינו בתוכנית של בראודה.
    # כדי לבדוק בכל זאת את *ענף ההעשרה*, בונים קטלוג קטן עם קודים אמיתיים
    # של בראודה: אחד צמוד, אחד מסמסטר מוקדם יותר, ואחד שלא קיים בתוכנית.
    # The MTA fixture shares no codes with the Braude curriculum, so the
    # in_curriculum branch needs its own tiny catalog to be exercised at all.
    mini = {
        "61756": {"name": "שיטות הנדסיות לפיתוח מערכות תוכנה", "status": STATUS_TAUGHT},
        "61753": {"name": "אלגוריתמים", "status": STATUS_TAUGHT},
        "999999": {"name": "קורס שלא בתוכנית", "status": STATUS_TAUGHT},
    }
    mini_annotated = annotate_with_curriculum(mini, curr)
    tied = mini_annotated["61756"]
    assert tied["in_curriculum"] is True
    assert tied["curriculum_semester"] == "5", tied
    assert tied["credits"] == 5.0, tied
    assert sorted(tied["tied_with"]) == ["61757", "62027"], tied
    assert "61751" in tied["prereq"], tied
    assert tied["cluster"] is None
    # קורס שחוזר מסמסטר מוקדם יותר — מידע, לא שגיאה.
    assert mini_annotated["61753"]["curriculum_semester"] == "4"
    assert mini_annotated["999999"] == dict(mini["999999"], in_curriculum=False)
    print(
        "  העשרה: 61756 -> סמסטר "
        f"{tied['curriculum_semester']}, צמודים {tied['tied_with']} | "
        f"61753 -> סמסטר {mini_annotated['61753']['curriculum_semester']} "
        "(חזרה מסמסטר מוקדם — תקין) | 999999 -> מחוץ לתוכנית ועדיין נבחר"
    )

    # השוואת קטלוגים.
    older = {c: dict(i) for c, i in list(catalog.items())[:20]}
    newer = {c: dict(i) for c, i in list(catalog.items())[10:30]}
    first_new = sorted(newer)[0]
    newer[first_new] = dict(newer[first_new], name=newer[first_new]["name"] + " (חדש)")
    newer["999999"] = {"name": "קורס דמה", "status": STATUS_TAUGHT}
    diff = compare_catalogs(older, newer)
    assert "999999" in diff["added"]
    assert diff["removed"], "ציפינו לקורסים שנעלמו בין שני החתכים"
    assert any(row[0] == first_new for row in diff["renamed"])
    print(
        f"  compare_catalogs: +{len(diff['added'])} / -{len(diff['removed'])} / "
        f"שינויי שם {len(diff['renamed'])}"
    )

    # offered_codes.
    assert offered_codes(catalog) == set(catalog)
    assert offered_codes({}) == set()

    # קלט פגום לא מפיל — הוא מייצר אזהרה.
    empty, empty_warnings = parse_catalog("")
    assert empty == {} and empty_warnings
    junk, junk_warnings = parse_catalog("<html><body><p>שלום</p></body></html>")
    assert junk == {} and junk_warnings

    print("discovery.py — כל הבדיקות עברו (self-check OK)")
    return 0


if __name__ == "__main__":
    # עברית ב-Windows: מכריחים UTF-8 על הפלט. עטוף — יש קונסולות וצינורות
    # שלא ניתן להגדיר מחדש, וזה לא אמור להפיל כלום.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:
            pass

    if str(PROJECT_ROOT / "src") not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT / "src"))

    raise SystemExit(self_check())
