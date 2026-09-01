"""
src/parser.py — פענוח דף הידיעון (HTML) והפיכתו לאובייקטי המודל.

המודול הזה הוא ה"מתרגם" של המערכת: הוא מקבל HTML גולמי של דף קורס מהידיעון
של בראודה, ומחזיר אובייקט ``Course`` מלא בקבוצות ובמפגשים.

עקרון התכנון החשוב ביותר
------------------------
**המבנה המדויק של הטבלה בידיעון אינו ידוע לנו.**
הידיעון הוא עמוד ASP.NET WebForms ישן; המחלקות, סדר העמודות ומספרן עשויים
להשתנות. לכן כל הקוד כאן כתוב בגישה "shape-agnostic" (אגנוסטי לצורה):

1. לא מסתמכים על מזהי CSS ולא על אינדקס עמודה קבוע.
2. מוצאים את *כל* הטבלאות בדף, נותנים לכל אחת ניקוד לפי כמה כותרות עבריות
   מוכרות היא מכילה, ובוחרים את הטובה ביותר.
3. ממפים עמודות **לפי טקסט הכותרת** בלבד.
4. כל שורה שלא הצלחנו לפענח נרשמת ב-``ParseResult.warnings`` — אף פעם לא
   נזרקת בשקט.

English note: every public function keeps the exact signature from SPEC.md
section 4. Helpers are prefixed with ``_`` and are free to change.
"""

from __future__ import annotations

import copy as _copy
import html as _html
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, fields
from typing import Any, NamedTuple

from bs4 import BeautifulSoup, Comment

# ייבוא המודל. הפרויקט מוסיף את src/ ל-sys.path (ראו main.py), ולכן הצורה
# הרגילה היא "from models import ...". ה-fallback קיים רק כדי שגם
# "from src import parser" יעבוד בלי להתפוצץ.
try:  # pragma: no cover - trivial import shim
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
        fmt_time,
    )
except ImportError:  # pragma: no cover
    from src.models import (  # type: ignore[no-redef]
        DAY_LETTERS_HE,
        DAY_NAMES_HE,
        KIND_LAB,
        KIND_LECTURE,
        KIND_ORDER,
        KIND_OTHER,
        KIND_PROJECT,
        KIND_TUTORIAL,
        Course,
        Group,
        Meeting,
        fmt_time,
    )


__all__ = [
    "ParseResult",
    "CourseDetails",
    "parse_course_page",
    "parse_course_details",
    "parse_time_range",
    "parse_day",
    "classify_kind",
    "normalize_semester",
    "extract_page_year",
    "load_sections",
    "save_sections",
    "self_check",
    "details_self_check",
    "DETAILS_HOUR_KEYS",
    "DETAILS_PREREQ_KEYS",
    "SEMESTER_A",
    "SEMESTER_B",
    "SEMESTER_SUMMER",
    "KNOWN_SEMESTERS",
]


# ==========================================================================
# ParseResult — מה שחוזר מפענוח דף אחד
# ==========================================================================
class ParseResult(NamedTuple):
    """תוצאת פענוח של דף קורס אחד.

    Attributes:
        course:   אובייקט ``Course`` מלא, או ``None`` אם לא הצלחנו לפענח כלום.
        warnings: רשימת אזהרות בעברית (+אנגלית בסוגריים). אף פעם לא ``None``.
                  שורה שדולגה תמיד מייצרת אזהרה — כדי שאפשר יהיה לתקן אחר כך
                  מול ה-HTML הגולמי שנשמר ב-data/raw/.
    """

    course: "Course | None"
    warnings: list[str]


# ==========================================================================
# 0. ניקוי טקסט — תווי RTL, רווחים קשיחים, גרשיים עבריים
# ==========================================================================
#: תווי בקרה דו-כיווניים (bidi) שמסתתרים בדפי HTML בעברית ומשגעים כל regex.
#: נכתבים כקודים ולא כתווים ממש — תו בלתי-נראה בתוך קוד מקור הוא מלכודת.
_BIDI_CODEPOINTS: tuple[int, ...] = (
    0x200B, 0x200C, 0x200D, 0x200E, 0x200F,   # ZWSP, ZWNJ, ZWJ, LRM, RLM
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,   # LRE, RLE, PDF, LRO, RLO
    0x2066, 0x2067, 0x2068, 0x2069,           # LRI, RLI, FSI, PDI
    0xFEFF,                                   # BOM
)
_BIDI_RE = re.compile("[" + "".join(chr(c) for c in _BIDI_CODEPOINTS) + "]")

#: כל סוגי המקפים/המינוסים שראינו בטבלאות שעות, כולל מקף עברי (maqaf).
_DASH_CODEPOINTS: tuple[int, ...] = (
    0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015,  # hyphen .. horizontal bar
    0x2212,                                          # minus sign
    0x05BE,                                          # מקף עברי (maqaf)
    0xFE58, 0xFE63, 0xFF0D,                          # small / fullwidth variants
    0x007E,                                          # tilde
)
_DASH_RE = re.compile("[" + "".join(chr(c) for c in _DASH_CODEPOINTS) + "]")

#: ישות HTML *תקינה* בלבד (עם נקודה-פסיק בסוף). מכוון: לא נוגעים ב-"&nbsp"
#: בלי נקודה-פסיק, כדי לא לשנות טקסט שכבר פוענח פעם אחת ע"י BeautifulSoup.
_ENTITY_RE = re.compile(r"&(?:#\d{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")


def _clean(text: Any) -> str:
    """מנקה טקסט גולמי: מפענח ישויות HTML, מוריד תווי bidi, ומכווץ רווחים.

    למה ``html.unescape``: בידיעון שמות מרצים מכילים ``&quot;`` (``ד&quot;ר``),
    ותאים מתחילים ב-``&nbsp;``. BeautifulSoup כבר מפענח את רובם, אבל טקסט
    שמגיע מתוך אטריביוט (למשל ``data-arguments``) או מ-HTML שנחתך ביד — לא.

    Args:
        text: כל דבר; ``None`` הופך למחרוזת ריקה.

    Returns:
        מחרוזת נקייה בשורה אחת.
    """
    if text is None:
        return ""
    t = str(text)
    if "&" in t and _ENTITY_RE.search(t):
        t = _html.unescape(t)
    t = t.replace("\xa0", " ")
    t = _BIDI_RE.sub("", t)
    # גרש/גרשיים עבריים -> ASCII, כדי שנוכל להשוות בקלות ("קב'", 'ש"ש')
    t = t.replace("׳", "'").replace("״", '"')
    t = t.replace("‘", "'").replace("’", "'")
    t = t.replace("“", '"').replace("”", '"')
    t = re.sub(r"\s+", " ", t)
    return t.strip()


#: הערה שמסמנת קבוצה שנפתחת אבל אין לה מועד קבוע (פרויקט, סמינר בתיאום,
#: ספורט, קורס כללי). הטקסט הזה הוא גם מה שהממשק מציג לסטודנט/ית, וגם הסימן
#: שמבדיל בין "אין מועד" ל"לא מתקיים בסמסטר הזה" — שני מצבים שנראים זהים
#: אחרי סינון הסמסטר, אבל אחד מהם צריך להישאר בר-בחירה והשני לא.
NO_FIXED_TIME_NOTE = "אין מועד קבוע"

#: הארגומנטים של כפתור "פרטים נוספים":
#:   -N<קורס>,-N<סמסטר>,-N<סוג>,-N<קבוצה>,-N...
#: הארגומנט השני הוא **קוד הסמסטר של הקבוצה**, והוא המקור היחיד לכך כשאין
#: לקבוצה אף שורת מפגש. בלעדיו קבוצה של סמסטר ב' שטרם נקבע לה מועד נראית
#: זהה לפרויקט גמר של סמסטר א' — שניהם "קבוצה בלי מפגשים".
_DETAILS_ARGS_RE = re.compile(r"data-arguments\s*=\s*[\"']\s*-N\d+\s*,\s*-N(\d+)")

#: קוד סמסטר בידיעון -> האות שאנחנו עובדים איתה.
SEMESTER_CODE_TO_LETTER: dict[str, str] = {"1": "א", "2": "ב", "3": "קיץ"}


def semester_from_details_args(html_fragment: str) -> str:
    """הסמסטר של הקבוצה מתוך כפתור "פרטים נוספים". ``""`` אם אין."""
    if not html_fragment:
        return ""
    m = _DETAILS_ARGS_RE.search(str(html_fragment))
    return SEMESTER_CODE_TO_LETTER.get(m.group(1), "") if m else ""


#: תוויות נגישות שהידיעון של בראודה מזריק לתוך *כל* תא:
#: ``<div class="col InRange"><span class="LabelIn">סמסטר:&nbsp;</span>&nbsp;א</div>``
#: בלי להסיר אותן, הטקסט של התא הוא "סמסטר: א" במקום "א" — וזה מרעיל את
#: כל השדות: סמסטר, יום, שעות, חדר ומרצה. גרסת הידיעון של תל-אביב-יפו
#: (שממנה נלקחו ה-fixtures) לא כללה את הספאנים האלה, ולכן זה לא נתפס קודם.
_LABEL_SPAN_SELECTOR = "span.LabelIn, .sr-only"


def _strip_label_spans(cell: Any) -> Any:
    """מחזיר עותק של התא בלי תוויות הנגישות. לא נוגע במקור.

    עובד על *עותק* כי ``decompose()`` הורס את העץ, ואותו עץ נסרק שוב
    בהמשך (למשל לזיהוי כפתורים ומזהי קבוצה).
    """
    if cell is None or isinstance(cell, str):
        return cell
    try:
        if cell.select_one(_LABEL_SPAN_SELECTOR) is None:
            return cell  # מסלול מהיר — אין מה להסיר
        clone = _copy.copy(cell)
        for label in clone.select(_LABEL_SPAN_SELECTOR):
            label.decompose()
        return clone
    except Exception:  # noqa: BLE001 — טקסט גולמי עדיף על קריסה
        return cell


def _cell_text(cell: Any) -> str:
    """טקסט של תא טבלה, מכווץ לשורה אחת, בלי תוויות נגישות."""
    if cell is None:
        return ""
    if isinstance(cell, str):
        return _clean(cell)
    return _clean(_strip_label_spans(cell).get_text(" ", strip=True))


def _cell_lines(cell: Any) -> list[str]:
    """שורות הטקסט של תא — פיצול לפי ``<br>`` וירידות שורה.

    למה זה חשוב: בידיעון קורה שתא אחד מכיל שני מפגשים, למשל
    ``יום א'<br>יום ג'`` מול ``08:30-10:00<br>12:00-14:00``.
    """
    if cell is None:
        return []
    raw = cell if isinstance(cell, str) else _strip_label_spans(cell).get_text("\n", strip=True)
    lines = [_clean(x) for x in str(raw).split("\n")]
    return [x for x in lines if x]


# ==========================================================================
# 1. parse_time_range — טווח שעות
# ==========================================================================
#
# טוקן זמן בודד. סדר האלטרנטיבות חשוב — הצורה עם נקודתיים/נקודה נבדקת ראשונה:
#   קבוצה 1+2) 08:30 / 8:30 / 08.30
#   קבוצה 3)   0830   (ארבע ספרות)
#   קבוצה 4)   830    (שלוש ספרות)
#   קבוצה 5)   8      (שעה עגולה בלבד)
_TIME_TOKEN_RE = re.compile(
    r"(?<!\d)(?:(\d{1,2})\s*[:.]\s*(\d{2})|(\d{4})|(\d{3})|(\d{1,2}))(?!\d)"
)

#: מפרידים שמעידים על "טווח": מקף מכל סוג, המילה "עד", to/until.
_RANGE_SEP_RE = re.compile(r"-|(?<![א-ת])עד(?![א-ת])|\bto\b|\buntil\b", re.IGNORECASE)


def _normalize_time_text(text: str) -> str:
    """מאחד מפרידים בטקסט שעות: כל מקף / en-dash / 'עד' / 'to' הופך ל-'-'."""
    t = _clean(text)
    t = _DASH_RE.sub("-", t)
    t = re.sub(r"(?<![א-ת])עד(?![א-ת])", "-", t)
    t = re.sub(r"\b(?:to|until|till)\b", "-", t, flags=re.IGNORECASE)
    return t


def _token_to_minutes(m: re.Match[str]) -> int | None:
    """ממיר התאמה בודדת של ``_TIME_TOKEN_RE`` לדקות מחצות, או None אם לא חוקי."""
    h_colon, m_colon, four, three, hour_only = (
        m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    )
    if h_colon is not None and m_colon is not None:      # 08:30
        hh, mm = int(h_colon), int(m_colon)
    elif four is not None:                                # 0830
        hh, mm = int(four[:2]), int(four[2:])
    elif three is not None:                               # 830
        hh, mm = int(three[0]), int(three[1:])
    elif hour_only is not None:                           # 8
        hh, mm = int(hour_only), 0
    else:                                                 # pragma: no cover
        return None
    if not (0 <= hh <= 24 and 0 <= mm <= 59):
        return None
    total = hh * 60 + mm
    return total if total <= 24 * 60 else None


def _parse_time_range_ex(
    text: str, require_separator: bool = False
) -> tuple[int, int, list[str]] | None:
    """גרסה פנימית של :func:`parse_time_range` שמחזירה גם אזהרות.

    Args:
        text: הטקסט של תא השעות.
        require_separator: אם True — נדרוש סימן טווח מפורש (מקף / "עד") או שני
            טוקנים עם נקודתיים. משמש כשסורקים תאים *לא ידועים* בשורה, כדי
            שמספר חדר ("301") לא ייקרא בטעות כשעה.

    Returns:
        ``(start, end, warnings)`` בדקות מחצות, או ``None`` אם לא ניתן לפענח.
    """
    warnings: list[str] = []
    raw = _clean(text)
    if not raw:
        return None
    norm = _normalize_time_text(raw)

    values: list[int] = []
    kinds: list[str] = []
    for m in _TIME_TOKEN_RE.finditer(norm):
        v = _token_to_minutes(m)
        if v is None:
            continue
        if m.group(1) is not None and m.group(2) is not None:
            kinds.append("colon")       # 08:30 / 08.30
        elif m.group(3) is not None:
            kinds.append("block4")      # 0830
        elif m.group(4) is not None:
            kinds.append("block3")      # 830
        else:
            kinds.append("hour")        # 8
        values.append(v)
        if len(values) == 2:
            break

    if len(values) < 2:
        return None

    # בלי מפריד מפורש דורשים ראיה חזקה שמדובר בטווח שעות, אחרת תא כמו
    # "בניין 2 חדר 310" היה נקרא בטעות כ-02:00 עד 03:10.
    has_sep = bool(_RANGE_SEP_RE.search(norm))
    both_colon = kinds == ["colon", "colon"]
    both_block4 = kinds == ["block4", "block4"]
    both_block = all(k.startswith("block") for k in kinds)
    if require_separator:
        # סורקים תא *לא ידוע*: מקף לבדו אינו ראיה! "301-305" (טווח חדרים) ו-"1-2"
        # (בניין) עברו כאן פעם כשעות והמציאו מפגש 03:01-03:05. לכן דורשים
        # שעות עם נקודתיים, או שני בלוקים של ארבע ספרות עם מפריד.
        if not (both_colon or (both_block4 and has_sep)):
            return None
    elif not has_sep and not both_colon and not both_block:
        return None

    start, end = values[0], values[1]
    if start == end:
        warnings.append(f"טווח שעות באורך אפס ולכן נפסל: '{raw}' (zero-length range).")
        return None
    if start > end:
        # RTL mangling: בטקסט עברי הטווח מגיע לפעמים הפוך ("10:00-08:30").
        # לפי ההנחיה — מחליפים ומדווחים, לא זורקים את השורה.
        start, end = end, start
        warnings.append(
            f"טווח שעות הגיע הפוך (RTL) ותוקן: '{raw}' -> "
            f"{fmt_time(start)}-{fmt_time(end)} (reversed range auto-swapped)."
        )
    return start, end, warnings


def parse_time_range(text: str) -> tuple[int, int] | None:
    """'08:30-10:00', '8:30 - 10:00', '0830-1000' -> (510, 600). None אם לא ניתן לפענח.

    תומך גם ב: '08.30-10.00', מקף en-dash/em-dash, 'עד' / 'to' / 'until',
    ובטווח הפוך ('10:00-08:30') שמוחלף אוטומטית ל-(510, 600).

    Args:
        text: הטקסט הגולמי של תא השעות.

    Returns:
        זוג ``(start, end)`` בדקות מחצות, או ``None``.
    """
    res = _parse_time_range_ex(text)
    if res is None:
        return None
    start, end, _warnings = res
    return start, end


# ==========================================================================
# 2. parse_day — יום בשבוע
# ==========================================================================
#: שמות ימים מלאים -> מספר.
_DAY_FULL_NAMES: dict[str, int] = {name: num for num, name in DAY_NAMES_HE.items()}
_DAY_FULL_NAMES.update({"ראשון": 1, "שני": 2, "שלישי": 3, "רביעי": 4, "חמישי": 5, "שישי": 6})

#: התאמת שמות מלאים — הארוך ביותר קודם, כדי ש"רביעי" ינצח את האות 'ב' שבתוכו.
_DAY_NAME_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"(?<![א-ת])" + re.escape(name) + r"(?![א-ת])"), num)
    for name, num in sorted(_DAY_FULL_NAMES.items(), key=lambda kv: -len(kv[0]))
]

#: אות יום -> מספר ("א" -> 1 ... "ו" -> 6).
_DAY_LETTERS: dict[str, int] = {letter: num for num, letter in DAY_LETTERS_HE.items()}

#: מילים שמקדימות את היום ואינן חלק מהמידע עצמו.
_DAY_WORDS = {"יום", "ביום", "ליום", "מיום", "ימים", "day", "days"}

#: טוקן שהוא מספר או שעה — לא רלוונטי לזיהוי אות היום.
_NUMERIC_TOKEN_RE = re.compile(r"\d{1,4}(?:[:.]\d{2})?")

#: "יום א'", "ביום ג", "ליום ה" — המילה 'יום' ואחריה אות.
_DAY_WORD_LETTER_RE = re.compile(r"(?:^|[^א-ת])[בלמ]?יו?ם\s*['\"]?\s*([אבגדהו])(?![א-ת])")

#: גיבוי אחרון — שמות ימים באנגלית, אם הדף אי פעם ייצא באנגלית.
#: גבולות מילה מלאים, אחרת שם כמו "Sunila" היה נקרא כיום ראשון.
_DAY_EN_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"\b(?:sun|sunday)\b", re.IGNORECASE), 1),
    (re.compile(r"\b(?:mon|monday)\b", re.IGNORECASE), 2),
    (re.compile(r"\b(?:tue|tues|tuesday)\b", re.IGNORECASE), 3),
    (re.compile(r"\b(?:wed|weds|wednesday)\b", re.IGNORECASE), 4),
    (re.compile(r"\b(?:thu|thur|thurs|thursday)\b", re.IGNORECASE), 5),
    (re.compile(r"\b(?:fri|friday)\b", re.IGNORECASE), 6),
]


def _parse_day_ex(text: str, allow_bare_digit: bool = True) -> int | None:
    """גרסה פנימית של :func:`parse_day` עם שליטה על ספרה בודדת.

    ``allow_bare_digit=False`` משמש כשסורקים תאים לא ידועים בשורה — אחרת תא
    של "מס' שעות" עם הערך 4 היה נקרא בטעות כ"יום רביעי".
    """
    t = _clean(text)
    if not t:
        return None

    # (1) שם יום מלא — הארוך ביותר קודם (longest-first).
    for pattern, num in _DAY_NAME_PATTERNS:
        if pattern.search(t):
            return num

    # (2) "יום א'" / "ביום ג"
    m = _DAY_WORD_LETTER_RE.search(" " + t)
    if m:
        return _DAY_LETTERS[m.group(1)]

    # (3) אות יום כטוקן עצמאי: "א", "א'", "ד׳", וגם "א,ג".
    #     קריטי: לא מספיק ש*אחד* הטוקנים הוא אות יום — אחרת 'ד"ר כהן' היה
    #     נקרא כיום רביעי בגלל ה-'ד'. דורשים שכל הטוקנים המשמעותיים
    #     (אחרי סינון "יום" ומספרים) יהיו אותיות יום.
    stripped = t.replace("'", " ").replace('"', " ")
    tokens = [tok for tok in re.split(r"[\s,./\\|()\[\]-]+", stripped) if tok]
    meaningful = [
        tok
        for tok in tokens
        if tok not in _DAY_WORDS and not _NUMERIC_TOKEN_RE.fullmatch(tok)
    ]
    if meaningful and all(tok in _DAY_LETTERS for tok in meaningful):
        return _DAY_LETTERS[meaningful[0]]

    # (4) אנגלית
    for pattern, num in _DAY_EN_PATTERNS:
        if pattern.search(t):
            return num

    # (5) ספרה בודדת 1..6
    if allow_bare_digit:
        for tok in tokens:
            if tok.isdigit() and 1 <= int(tok) <= 6:
                return int(tok)
    return None


def parse_day(text: str) -> int | None:
    """'א' / "יום א'" / 'ראשון' / '1' -> 1 ... 'ו' / 'שישי' -> 6.

    ההתאמה היא longest-first: שם יום מלא נבדק לפני אות בודדת, אחרת "רביעי"
    היה נקרא בטעות כ-'ב' (=יום שני).

    Args:
        text: הטקסט הגולמי של תא היום.

    Returns:
        1..6, או ``None`` אם אין יום מזוהה (למשל 'שבת').
    """
    return _parse_day_ex(text, allow_bare_digit=True)


# ==========================================================================
# 3. classify_kind — סוג המפגש
# ==========================================================================
#: מילות מפתח בעברית -> KIND_*. ממוין בהמשך לפי אורך יורד (הארוך מנצח).
_KIND_SUBSTRINGS_RAW: list[tuple[str, str]] = [
    # שו"ת = שיעור ותרגיל באותו מפגש (נצפה ב-11069 אנגלית טכנית בבראודה).
    # חייב להופיע לפני "שיעור", אחרת הוא היה מסווג כהרצאה ומאבד את המידע
    # שמדובר במפגש משולב. שני סוגי הגרשיים נתמכים (U+0022 ו-U+05F4).
    ("שיעור ותרגיל", KIND_COMBINED), ("שיעור ותרגול", KIND_COMBINED),
    ("שו\"ת", KIND_COMBINED), ("שו״ת", KIND_COMBINED),
    # הרצאה
    ("הרצאות", KIND_LECTURE), ("הרצאה", KIND_LECTURE), ("הרצאת", KIND_LECTURE),
    ("הרצ", KIND_LECTURE), ("שיעור", KIND_LECTURE), ("שעור", KIND_LECTURE),
    # תרגול
    ("תרגילים", KIND_TUTORIAL), ("תירגול", KIND_TUTORIAL), ("תרגול", KIND_TUTORIAL),
    ("תרגיל", KIND_TUTORIAL), ("תירג", KIND_TUTORIAL), ("תרג", KIND_TUTORIAL),
    # מעבדה
    ("מעבדות", KIND_LAB), ("מעבדה", KIND_LAB), ("מעבדת", KIND_LAB), ("מעב", KIND_LAB),
    # פרויקט — כולל הכתיב החלופי "פרוייקט"
    ("פרוייקט", KIND_PROJECT), ("פרויקט", KIND_PROJECT), ("פרוקט", KIND_PROJECT),
    # שימו לב: אין כאן "פרו" — הוא תחילית של "פרופ'", תואר של מרצה!
    ("פרויק", KIND_PROJECT), ("פרוי", KIND_PROJECT),
]
#: המילה הארוכה ביותר נבדקת ראשונה; בתיקו נשמר סדר הרשימה שלמעלה.
_KIND_SUBSTRINGS: list[tuple[str, str]] = sorted(
    _KIND_SUBSTRINGS_RAW, key=lambda kv: -len(kv[0])
)

#: קיצורים לטיניים (he/te/ma/pr הם ה-legend של הידיעון). התאמה למחרוזת *שלמה*
#: בלבד, כדי ש-"he" בתוך מילה אנגלית לא ייקרא כ"הרצאה".
_KIND_LATIN_EXACT: dict[str, str] = {
    "he": KIND_LECTURE, "lec": KIND_LECTURE, "lect": KIND_LECTURE,
    "lecture": KIND_LECTURE, "l": KIND_LECTURE,
    "te": KIND_TUTORIAL, "tut": KIND_TUTORIAL, "tutorial": KIND_TUTORIAL,
    "ex": KIND_TUTORIAL, "exercise": KIND_TUTORIAL, "t": KIND_TUTORIAL,
    "ma": KIND_LAB, "lab": KIND_LAB, "laboratory": KIND_LAB,
    "pr": KIND_PROJECT, "proj": KIND_PROJECT, "project": KIND_PROJECT,
}


#: מילות הסוג כמחרוזות שלמות. משמש לבדיקת שפיות של עמודת המרצה: תא שכתוב בו
#: בדיוק "הרצאה" אינו שם של מרצה. השוואה מדויקת בלבד — שם משפחה כמו "הרצל"
#: מכיל "הרצ" אך אינו שווה לו, ולכן לא ייפסל.
_KIND_EXACT_WORDS: set[str] = {w for w, _kind in _KIND_SUBSTRINGS_RAW} | set(_KIND_LATIN_EXACT)


def _is_kind_word(text: str) -> bool:
    """האם הטקסט הוא בדיוק מילת סוג מפגש (ולכן בוודאי לא שם מרצה)?"""
    t = _clean(text).strip("'\".,: ")
    return bool(t) and (t in _KIND_EXACT_WORDS or t.lower() in _KIND_LATIN_EXACT)


def classify_kind(text: str) -> str:
    """ממפה מילים בעברית ל-KIND_*.

    הרצאה/שיעור -> ``הרצאה`` , תרגיל/תרגול -> ``תרגול`` , מעבדה/מעב' -> ``מעבדה`` ,
    פרויקט/פרוייקט -> ``פרויקט`` , אחרת -> ``אחר``.

    ההתאמה היא longest-first, ולכן "מעבדה" מנצח את הקיצור "מעב".
    הערה: תא שמכיל גם "הרצאה" וגם "תרגול" יסווג כהרצאה (סדר הרשימה).

    Args:
        text: טקסט תא הסוג (או כל טקסט שעשוי להכיל את מילת הסוג).

    Returns:
        אחד מקבועי ``KIND_*``.
    """
    t = _clean(text)
    if not t:
        return KIND_OTHER

    # (1) מילות מפתח בעברית — הארוכה ביותר קודם.
    for word, kind in _KIND_SUBSTRINGS:
        if word in t:
            return kind

    # (2) קיצור לטיני, כמחרוזת שלמה בלבד.
    bare = re.sub(r"[^a-zA-Z]", "", t).lower()
    if bare and bare in _KIND_LATIN_EXACT:
        return _KIND_LATIN_EXACT[bare]

    return KIND_OTHER


# ==========================================================================
# 3b. סמסטר — נירמול עמודת "סמסטר" (העמודה החשובה ביותר בדף)
# ==========================================================================
# ‏‏GROUND_TRUTH.md סעיף 3 + סעיף "Semester filtering": דף קורס בידיעון מציג את
# המפגשים של **שני הסמסטרים יחד**, והעמודה הראשונה בכל שורת מפגש היא הסמסטר
# ("א" / "ב" / "קיץ"). בלי סינון לפי העמודה הזאת מפגש של סמסטר ב' היה נכנס
# בשקט למערכת של סמסטר א' — התקלה החמורה ביותר שהכלי הזה יכול לייצר.
#
# ההחלטה (GROUND_TRUTH): לא סומכים על פקד הסינון R1C19 של האתר. מסננים אצלנו,
# אחרי הפענוח, לפי מה שכתוב בשורה עצמה. זה גם פשוט יותר וגם ניתן לאימות.

SEMESTER_A = "א"
SEMESTER_B = "ב"
SEMESTER_SUMMER = "קיץ"

#: הערכים היחידים שנחשבים "סמסטר ידוע". כל ערך אחר (כולל מחרוזת ריקה) הוא
#: *לא ידוע* — ואת מה שלא ידוע לעולם לא זורקים, רק מסמנים באזהרה.
KNOWN_SEMESTERS: tuple[str, ...] = (SEMESTER_A, SEMESTER_B, SEMESTER_SUMMER)

#: הקידוד המספרי שמופיע בארגומנטים של הכפתור S_CourseDetails (``-N<sem>``).
_SEMESTER_BY_DIGIT: dict[str, str] = {
    "1": SEMESTER_A,
    "2": SEMESTER_B,
    "3": SEMESTER_SUMMER,
}

#: מילים נרדפות. בישראל סמסטר החורף הוא א' וסמסטר האביב הוא ב'.
#: נבדקות *לפני* הסרת המילה "סמסטר", כדי ש"סמסטר קיץ" ייתן "קיץ".
_SEMESTER_WORDS: tuple[tuple[str, str], ...] = (
    ("קיץ", SEMESTER_SUMMER),
    ("חורף", SEMESTER_A),
    ("אביב", SEMESTER_B),
    ("summer", SEMESTER_SUMMER),
    ("winter", SEMESTER_A),
    ("spring", SEMESTER_B),
)

#: המילה "סמסטר" על צורותיה — מוסרת לפני שמסתכלים על האות עצמה.
_SEMESTER_LABEL_RE = re.compile(r"סמסטר|סמ'|semester|term", re.IGNORECASE)

#: תווים שמעטרים את ערך הסמסטר: גרש/גרשיים, סוגריים, נקודתיים, מקפים.
_SEMESTER_TRIM = " \t'\"`.,:;-\u2013\u2014()[]{}"


def normalize_semester(text: str) -> str:
    """מנרמל את הטקסט של עמודת הסמסטר לערך אחיד.

    דוגמאות (בדיוק כפי שנדרש):
        ``"&nbsp;ב"`` -> ``"ב"`` , ``"סמסטר א'"`` -> ``"א"`` ,
        ``"קיץ"`` -> ``"קיץ"`` , ``""`` -> ``""``.

    הפונקציה סלחנית בכוונה: היא מפענחת ישויות HTML, מורידה את ה-U+00A0
    שמקדים כל תא בידיעון, מסירה את המילה "סמסטר" וגרש/גרשיים נגררים.

    Args:
        text: תוכן תא הסמסטר, גולמי או מנוקה.

    Returns:
        ``"א"`` / ``"ב"`` / ``"קיץ"`` כשהערך זוהה; מחרוזת ריקה כשהתא ריק;
        ואחרת — הטקסט הנקי כמות שהוא (ערך "לא ידוע" שאסור לסנן לפיו).

    Note:
        הפונקציה אידמפוטנטית: ``normalize_semester(normalize_semester(x))``
        שווה תמיד ל-``normalize_semester(x)``. זה מה שמאפשר round-trip
        מדויק של data/sections.json.
    """
    t = _clean(text)          # unescape entities, U+00A0 -> space, geresh -> '
    if not t:
        return ""

    # (1) מילים מפורשות — לפני כל ניקוי, כדי ש"סמסטר קיץ" יזוהה.
    low = t.lower()
    for word, sem in _SEMESTER_WORDS:
        if word in low:
            return sem

    # (2) מסירים את התווית "סמסטר" ואת העיטורים שסביב האות.
    t = _clean(_SEMESTER_LABEL_RE.sub(" ", t))
    t = t.strip(_SEMESTER_TRIM)
    if not t:
        return ""

    # (3) קידוד מספרי (‏-N1 / -N2 / -N3 מכפתור S_CourseDetails).
    if t in _SEMESTER_BY_DIGIT:
        return _SEMESTER_BY_DIGIT[t]

    # (4) האות עצמה, או ערך לא מוכר שמוחזר כמות שהוא ומסומן אחר כך כ"לא ידוע".
    return t


# ==========================================================================
# 4. זיהוי הטבלה הנכונה — ניקוד לפי כותרות
# ==========================================================================
#: (שדה, ביטויי כותרת). הסדר קובע! ביטוי ספציפי חייב להופיע לפני הכללי,
#: אחרת "עד שעה" היה נתפס בטעות כעמודת "שעה".
_HEADER_FIELDS: list[tuple[str, tuple[str, ...]]] = [
    ("hour_start", ("שעת התחלה", "משעה", "מ שעה", "שעה מ", "start time", "from hour")),
    ("hour_end", ("שעת סיום", "עד שעה", "שעה עד", "end time", "to hour", "until")),
    ("hours_count", ('ש"ש', "שעות שבועיות", "מס' שעות", "מספר שעות", "היקף")),
    ("hour", ("שעות", "שעה", "שעון", "hour", "time")),
    ("day", ("ימים", "יום", "day")),
    ("group", ("קבוצה", "קבוצת", "קב'", "group", "section")),
    ("lecturer", ("שם המרצה", "מרצים", "מרצה", "מורה", "מלמד", "lecturer", "teacher")),
    ("kind", ("סוג מפגש", "סוג שיעור", "סוג", "מרכיב", "רכיב", "type", "kind")),
    ("building", ("בניין", "בנין", "מבנה", "building")),
    ("room", ("חדר", "כיתה", "אולם", "room")),
    ("session", ("מפגש", "מועד", "session")),
    ("note", ("הערות", "הערה", "note", "remark")),
    ("semester", ("סמסטר", "semester", "term")),
    ("code", ("קוד קורס", "מספר קורס", "קוד", "course code")),
    ("name", ("שם הקורס", "שם קורס", "course name")),
]

#: השדות שמזכים בניקוד — בדיוק אלה שמנויים במפרט.
_SCORE_CATEGORIES: tuple[str, ...] = (
    "group", "lecturer", "day", "hour", "hours_count", "kind", "building", "room", "session",
)

#: ביטויים שמעידים שהדף פשוט לא החזיר תוצאות.
_EMPTY_RESULT_PHRASES = (
    "לא נמצאו נתונים", "אין נתונים", "לא נמצאו רשומות", "לא נמצא קורס",
    "לא נמצאו קורסים", "no records", "no data",
)


#: "יום" / "ימים" / "day" כמילה שלמה. לא ``"יום" in t`` — אחרת "יומן" היה
#: נחשב לעמודת יום.
_DAY_HEADER_RE = re.compile(r"(?<![א-ת])(?:ימים|יום)(?![א-ת])|\bdays?\b", re.IGNORECASE)


def _fields_for_header(text: str) -> list[str]:
    """מחזיר את שמות השדות שכותרת מסוימת מייצגת.

    בדרך כלל שדה אחד (ההתאמה הראשונה ברשימה המסודרת). חריג מכוון: כותרת
    משולבת כמו "יום ושעה" מקבלת גם ``day`` וגם ``hour``.

    שימו לב לסדר: ``hour`` מופיע ב-``_HEADER_FIELDS`` *לפני* ``day``, ולכן
    "יום ושעה" מתאים קודם כול ל-``hour``. לכן ההשלמה של ``day`` נעשית *אחרי*
    הלולאה ולא מותנית בשדה שנמצא — אחרת עמודת "יום ושעה" לא הייתה ממופה כיום
    בכלל, והיום היה נקרא בטעות מתא אחר בשורה.
    """
    t = _clean(text)
    if not t:
        return []
    found: list[str] = []
    for field_name, phrases in _HEADER_FIELDS:
        if any(p in t for p in phrases):
            found.append(field_name)
            break
    if found and "day" not in found and _DAY_HEADER_RE.search(t):
        found.append("day")
    if found == ["day"] and any(p in t for p in ("שעה", "שעות", "hour", "time")):
        found.append("hour")
    return found


def _span(cell: Any, attr: str, limit: int) -> int:
    """קורא colspan/rowspan בבטחה, עם חסם עליון נגד ערכים מטורפים."""
    try:
        val = int(str(cell.get(attr, 1)).strip() or 1)
    except (TypeError, ValueError, AttributeError):
        return 1
    return max(1, min(val, limit))


def _own_rows(table: Any) -> list[Any]:
    """שורות ששייכות *לטבלה הזאת* ולא לטבלה מקוננת בתוכה."""
    return [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]


def _own_cells(tr: Any) -> list[Any]:
    """תאים ששייכים ישירות לשורה הזאת."""
    return [c for c in tr.find_all(["td", "th"]) if c.find_parent("tr") is tr]


def _table_grid(table: Any) -> list[list[Any]]:
    """פורש טבלה לרשת מלבנית של תאים, תוך פתיחת rowspan ו-colspan.

    זה הפתרון שלנו לבעיית "מספר תאים לא תואם": אחרי הפרישה יש לכל שורה בדיוק
    אותו מספר עמודות, ותא שנמתח על שתי שורות מופיע בשתיהן. כך מיפוי לפי
    כותרת נשאר נכון גם בטבלאות עם מיזוגים, ובלי לנחש אינדקסים.

    Returns:
        רשימת שורות; כל שורה היא רשימת תאים (``Tag``) או ``None`` לתא ריק.
    """
    rows = _own_rows(table)
    if not rows:
        return []
    max_rows = len(rows) + 4
    grid: list[list[Any]] = []

    def _ensure_row(idx: int) -> list[Any]:
        while len(grid) <= idx:
            grid.append([])
        return grid[idx]

    for r, tr in enumerate(rows):
        row = _ensure_row(r)
        c = 0
        for cell in _own_cells(tr):
            # מדלגים על עמודות שכבר תפוסות ע"י rowspan משורה קודמת.
            while c < len(row) and row[c] is not None:
                c += 1
            colspan = _span(cell, "colspan", 40)
            rowspan = min(_span(cell, "rowspan", max_rows), max_rows - r)
            for dr in range(rowspan):
                target = _ensure_row(r + dr)
                while len(target) < c + colspan:
                    target.append(None)
                for dc in range(colspan):
                    if target[c + dc] is None:
                        target[c + dc] = cell
            c += colspan

    width = max((len(row) for row in grid), default=0)
    for row in grid:
        while len(row) < width:
            row.append(None)
    return grid


def _row_has_time(row: list[Any]) -> bool:
    """האם יש בשורה תא שנקרא כטווח שעות? (מבדיל שורת נתונים משורת כותרת)."""
    for cell in row:
        for line in _cell_lines(cell):
            if _parse_time_range_ex(line) is not None:
                return True
    return False


def _map_columns(
    header_row: list[Any], second_row: list[Any] | None = None
) -> tuple[dict[str, int], int]:
    """ממפה אינדקס עמודה -> שדה, לפי טקסט הכותרת בלבד.

    Args:
        header_row: שורת הכותרת (מתוך הרשת הפרושה).
        second_row: שורת כותרת שנייה, אם הכותרת נמתחת על שתי שורות.

    Returns:
        ``(col_map, score)`` — מילון ``{"day": 3, "hour": 4, ...}`` והניקוד.
    """
    texts: list[str] = []
    for i, cell in enumerate(header_row):
        a = _cell_text(cell)
        if second_row is not None and i < len(second_row):
            b = _cell_text(second_row[i])
            if b and b != a:
                a = f"{a} {b}".strip()
        texts.append(a)

    col_map: dict[str, int] = {}
    for i, t in enumerate(texts):
        for field_name in _fields_for_header(t):
            col_map.setdefault(field_name, i)

    categories: set[str] = set()
    for cat in _SCORE_CATEGORIES:
        if cat == "hour":
            if any(k in col_map for k in ("hour", "hour_start", "hour_end")):
                categories.add(cat)
        elif cat in col_map:
            categories.add(cat)
    return col_map, len(categories)


def _score_grid(grid: list[list[Any]]) -> tuple[int, int, dict[str, int]]:
    """מוצא את שורת הכותרת הטובה ביותר ומחזיר ``(score, header_idx, col_map)``.

    לא מסתמכים על ``<th>`` (הידיעון לא תמיד משתמש בו): מנסים כמה שורות
    ראשונות כמועמדות לכותרת ובוחרים את זו שמניבה את הניקוד הגבוה ביותר.
    גם כותרת דו-שורתית נבדקת — אך רק אם השורה השנייה אינה שורת נתונים.
    """
    best_score, best_idx, best_map = 0, 0, {}
    for idx in range(min(3, len(grid))):
        col_map, score = _map_columns(grid[idx])
        if score > best_score:
            best_score, best_idx, best_map = score, idx, col_map
        if idx + 1 < len(grid) and not _row_has_time(grid[idx + 1]):
            col_map2, score2 = _map_columns(grid[idx], grid[idx + 1])
            if score2 > best_score:
                best_score, best_idx, best_map = score2, idx + 1, col_map2
    return best_score, best_idx, best_map


def _pick_group_table(
    soup: Any,
) -> tuple[list[list[Any]], int, dict[str, int], int, bool] | None:
    """בוחר מכל הטבלאות בדף את טבלת הקבוצות.

    Returns:
        ``(grid, header_idx, col_map, score, few_rows)``, או ``None`` אם אף
        טבלה לא קיבלה ניקוד חיובי. ``few_rows=True`` אומר שנאלצנו להסתפק
        בטבלה עם פחות משתי שורות נתונים.
    """
    candidates: list[tuple[int, int, int, dict[str, int], list[list[Any]]]] = []
    for table in soup.find_all("table"):
        grid = _table_grid(table)
        if not grid:
            continue
        score, header_idx, col_map = _score_grid(grid)
        if score <= 0:
            continue
        n_data = max(0, len(grid) - (header_idx + 1))
        if n_data <= 0:
            continue
        candidates.append((score, n_data, header_idx, col_map, grid))

    if not candidates:
        return None

    # לפי המפרט: הטבלה בעלת הניקוד הגבוה ביותר שיש בה לפחות 2 שורות נתונים.
    # אם אין כזאת (קורס עם קבוצה יחידה) — לוקחים את הטובה ביותר ומזהירים.
    rich = [c for c in candidates if c[1] >= 2]
    pool = rich if rich else candidates
    pool.sort(key=lambda c: (c[0], c[1]), reverse=True)
    score, _n_data, header_idx, col_map, grid = pool[0]
    return grid, header_idx, col_map, score, not rich


# ==========================================================================
# 5. קריאת שורות -> מפגשים וקבוצות
# ==========================================================================
def _at(items: list[str], i: int) -> str:
    """איבר i ברשימה; אם חורג — האיבר האחרון (או מחרוזת ריקה)."""
    if not items:
        return ""
    return items[i] if i < len(items) else items[-1]


def _lines_at(row: list[Any], idx: int | None) -> list[str]:
    """שורות הטקסט של תא בעמודה idx (רשימה ריקה אם אין עמודה כזאת)."""
    if idx is None or idx < 0 or idx >= len(row):
        return []
    return _cell_lines(row[idx])


def _text_at(row: list[Any], col_map: dict[str, int], field_name: str) -> str:
    """טקסט של עמודה לפי שם שדה, או '' אם השדה לא מופה."""
    idx = col_map.get(field_name)
    if idx is None or idx >= len(row):
        return ""
    return _cell_text(row[idx])


#: עמודות שאסור לסרוק בחיפוש יום/שעה — הערכים שבהן נראים כמו זמן אבל אינם.
#: "301-305" בעמודת חדר, "1-2" בעמודת בניין, "11-12" בעמודת קבוצה, "א" בעמודת
#: סמסטר — כולם ייצרו מפגש מומצא שלא מתנגש בכלום, וזה הכשל המסוכן ביותר כאן.
_SCAN_SKIP_FIELDS: tuple[str, ...] = (
    "group", "room", "building", "note", "hours_count", "code", "semester", "name",
)


def _scan_skip(col_map: dict[str, int] | None) -> set[int]:
    """אינדקסי העמודות שהסריקה הפוזיציונית מדלגת עליהן."""
    if not col_map:
        return set()
    return {col_map[k] for k in _SCAN_SKIP_FIELDS if k in col_map}


def _scan_days(row: list[Any], col_map: dict[str, int] | None = None) -> list[int]:
    """סריקה פוזיציונית: מחפשת יום בתאי השורה, בלי לקבל ספרה בודדת.

    שני כללי זהירות:
      * מדלגים על עמודות שממופות לשדה שאינו זמן (חדר/בניין/קבוצה/סמסטר).
      * תא שיש בו *גם* יום וגם טווח שעות מנצח תא שיש בו יום בלבד — כך עמודה
        משולבת "יום ושעה" גוברת על תא הסמסטר 'א' שנראה כמו יום ראשון.
    """
    skip = _scan_skip(col_map)
    first: list[int] = []
    for i, cell in enumerate(row):
        if i in skip:
            continue
        lines = _cell_lines(cell)
        found = [
            d for d in (_parse_day_ex(line, allow_bare_digit=False) for line in lines)
            if d is not None
        ]
        if not found:
            continue
        if any(_parse_time_range_ex(line, require_separator=True) for line in lines):
            return found
        if not first:
            first = found
    return first


def _scan_ranges(
    row: list[Any], col_map: dict[str, int] | None = None
) -> list[tuple[int, int, list[str]]]:
    """סריקה פוזיציונית: מחפשת טווח שעות בתאי השורה, בדרישה מחמירה."""
    skip = _scan_skip(col_map)
    for i, cell in enumerate(row):
        if i in skip:
            continue
        found = [
            t
            for t in (
                _parse_time_range_ex(line, require_separator=True)
                for line in _cell_lines(cell)
            )
            if t is not None
        ]
        if found:
            return found
    return []


def _row_meetings(
    row: list[Any],
    col_map: dict[str, int],
    warnings: list[str],
    ctx: str,
    force_scan: bool = False,
) -> list[Meeting]:
    """מחלץ את כל המפגשים שבשורה אחת של הטבלה.

    שתי דרכי קריאה:
      * **לפי הכותרות** — הדרך הנכונה, וברירת המחדל.
      * **סריקה פוזיציונית** של כל תאי השורה — נפילה-לאחור כשהקריאה לפי
        הכותרות לא הניבה כלום, וגם כש-``force_scan=True``, כלומר כשזוהתה
        אי-התאמה בין מספר התאים בשורה למספר עמודות הכותרת (rowspan/colspan
        או כותרת חסרה). הסריקה מחמירה בכוונה — דורשת סימן טווח מפורש ולא
        מקבלת ספרה בודדת כיום — כדי לא להמציא מפגשים ממספרי חדרים.
    """
    # --- קריאה לפי הכותרות ---
    day_lines = _lines_at(row, col_map.get("day"))
    if "hour_start" in col_map and "hour_end" in col_map:
        # זוג עמודות "משעה" / "עד שעה" מחוברות לטווח אחד.
        starts = _lines_at(row, col_map["hour_start"])
        ends = _lines_at(row, col_map["hour_end"])
        n = max(len(starts), len(ends))
        time_lines = [f"{_at(starts, i)} - {_at(ends, i)}" for i in range(n)]
    elif "hour" in col_map:
        time_lines = _lines_at(row, col_map["hour"])
    else:
        time_lines = []

    mapped_days = [d for d in (_parse_day_ex(x, True) for x in day_lines) if d is not None]
    mapped_ranges = [t for t in (_parse_time_range_ex(x) for x in time_lines) if t is not None]

    # הקריאה לפי הכותרת מנצחת תמיד — גם בשורה "עקומה". סריקה פוזיציונית היא
    # ניחוש לפי מיקום, ואסור לה לדרוס ערך שנקרא מהעמודה הנכונה: שורה שחסר בה
    # תא הערות סופית קיבלה פעם את מזהה הקבוצה "11-12" כשעה 11:00-12:00.
    scanned_days = _scan_days(row, col_map) if (force_scan or not mapped_days) else []
    scanned_ranges = _scan_ranges(row, col_map) if (force_scan or not mapped_ranges) else []
    days = mapped_days or scanned_days
    ranges = mapped_ranges or scanned_ranges

    if force_scan:
        if mapped_days and scanned_days and scanned_days != mapped_days:
            warnings.append(
                f"{ctx}: הסריקה הפוזיציונית מצאה יום אחר מזה שבעמודה הממופה — "
                f"נשמר הערך מהעמודה (positional day scan disagrees with the mapped column)."
            )
        if mapped_ranges and scanned_ranges and (
            [(s, e) for s, e, _w in scanned_ranges] != [(s, e) for s, e, _w in mapped_ranges]
        ):
            warnings.append(
                f"{ctx}: הסריקה הפוזיציונית מצאה שעות אחרות מאלה שבעמודה הממופה — "
                f"נשמר הערך מהעמודה (positional time scan disagrees with the mapped column)."
            )

    if not days or not ranges:
        return []

    # --- התאמת ימים לטווחים ---
    if len(days) == len(ranges):
        pairs = list(zip(days, ranges))
    elif len(days) == 1:
        pairs = [(days[0], t) for t in ranges]          # יום אחד, כמה טווחים
    elif len(ranges) == 1:
        pairs = [(d, ranges[0]) for d in days]          # כמה ימים, אותו טווח
    else:
        warnings.append(
            f"{ctx}: מספר הימים ({len(days)}) אינו תואם למספר טווחי השעות "
            f"({len(ranges)}) — נלקח המינימום (day/time count mismatch)."
        )
        pairs = list(zip(days, ranges))

    rooms = _lines_at(row, col_map.get("room"))
    buildings = _lines_at(row, col_map.get("building"))
    # עמודת הסמסטר. אם אין עמודה כזאת בטבלה — כל המפגשים יקבלו "" (לא ידוע),
    # וזה בסדר: "לא ידוע" נשמר תמיד, ורק אזהרה נרשמת בשלב הסינון.
    semesters = _lines_at(row, col_map.get("semester"))

    meetings: list[Meeting] = []
    for i, (day, (start, end, time_warnings)) in enumerate(pairs):
        for w in time_warnings:
            warnings.append(f"{ctx}: {w}")
        meetings.append(
            Meeting(
                day=day,
                start=start,
                end=end,
                room=_at(rooms, i),
                building=_at(buildings, i),
                semester=normalize_semester(_at(semesters, i)),
            )
        )
    return meetings


#: מפרידים במזהה קבוצה משולב ("11/12", "11-12", "11,12").
_GID_SPLIT_RE = re.compile(r"\s*[/\\,+&|]\s*|\s*-\s*")


def _split_group_id(raw: str) -> tuple[str, list[str], str | None]:
    """מפרק מזהה קבוצה שעשוי לרמז על קבוצה צמודה.

    ``"11/12"`` -> ``("11", ["12"], אזהרה)``. הפרשנות: החלק הראשון הוא הקבוצה
    עצמה, והשאר הן קבוצות שחייבות להילקח איתה. זו הערכה best-effort ולכן
    תמיד מוחזרת גם אזהרה, כדי שאפשר יהיה לוודא מול הידיעון.

    Returns:
        ``(group_id, linked_to, warning_or_None)``
    """
    t = _clean(raw)
    if not t:
        return "", [], None
    parts = [p for p in _GID_SPLIT_RE.split(t) if p]
    if len(parts) <= 1:
        return t, [], None
    numeric = [p for p in parts if re.fullmatch(r"\d{1,4}", p)]
    if len(numeric) >= 2:
        head, rest = numeric[0], numeric[1:]
        return (
            head,
            rest,
            f"מזהה קבוצה מורכב '{t}' פורש כקבוצה {head} הצמודה ל-{', '.join(rest)} "
            f"— יש לוודא מול הידיעון (ambiguous linked group id).",
        )
    return parts[0], [], f"מזהה קבוצה לא שגרתי '{t}' (unusual group id)."


#: מילים בהערה שמעידות על קבוצה צמודה.
_TIE_WORDS = (
    "צמוד", "צמודה", "צמודים", "צמודות", "יחד עם", "ביחד עם", "משולב", "משולבת",
    "חובה עם", "בשילוב", "עם קבוצה", "שייך לקבוצה", "מחייב קבוצה", "linked", "tied",
)
_TIE_NUM_RE = re.compile(r"קבוצ\w*\s*'?\s*(\d{1,4})")


def _linked_from_note(note: str) -> tuple[list[str], str | None]:
    """מחלץ קבוצות צמודות מתוך עמודת ההערות. best-effort + אזהרה כשעמום."""
    t = _clean(note)
    if not t or not any(w in t for w in _TIE_WORDS):
        return [], None
    nums = _TIE_NUM_RE.findall(t)
    if nums:
        return list(dict.fromkeys(nums)), None
    loose = re.findall(r"(?<!\d)(\d{1,3})(?!\d)", t)
    if loose:
        return list(dict.fromkeys(loose)), (
            f"ההערה '{t}' מרמזת על קבוצה צמודה אך מספר הקבוצה אינו ודאי "
            f"(ambiguous tie note)."
        )
    return [], f"ההערה '{t}' מרמזת על קבוצה צמודה אך לא נמצא מספר קבוצה (ambiguous tie note)."


def _is_header_label(text: str) -> bool:
    """האם הטקסט הוא *תווית כותרת* ולא ערך?

    "קבוצה" כן, "קבוצה 12" לא. הבחנה זו קריטית: בלעדיה שורת נתונים אמיתית
    שכתוב בה "קבוצה 12 | הרצאה | ד"ר לוי | יום ג | שעה טרם נקבעה" זוהתה
    ככותרת חוזרת ונזרקה בשקט, וקבוצה שלמה נעלמה מהמערכת.
    """
    t = _clean(text)
    if not t or len(t) > 24:
        return False
    if any(ch.isdigit() for ch in t):
        return False                       # תווית כותרת אינה מכילה מספרים
    if not _fields_for_header(t):
        return False
    if _parse_day_ex(t, allow_bare_digit=False) is not None:
        return False                       # "יום ג" הוא ערך, לא כותרת
    return _parse_time_range_ex(t) is None


def _looks_like_header(row: list[Any]) -> bool:
    """האם השורה היא בעצם כותרת שחוזרת באמצע הטבלה?

    דורשים ש*כל* התאים המלאים יהיו תוויות כותרת (ולפחות שלושה כאלה). שורה
    שמכילה ולו ערך אחד — מספר קבוצה, שם מרצה — אינה כותרת, ולכן תדולג עם
    אזהרה ולא בשקט.
    """
    _col_map, score = _map_columns(row)
    if score < 3 or _row_has_time(row):
        return False
    non_empty = [t for t in (_cell_text(c) for c in row) if t]
    labels = [t for t in non_empty if _is_header_label(t)]
    return len(labels) >= 3 and len(labels) == len(non_empty)


def _detect_kind(row: list[Any], col_map: dict[str, int], trust_columns: bool = True) -> str:
    """מזהה את סוג המפגש של שורה — מעמודת הסוג, ואם אין, מסריקת השורה.

    Args:
        row: שורת הרשת.
        col_map: מיפוי העמודות של הטבלה.
        trust_columns: כשהוא ``False`` (זוהתה אי-התאמה במספר התאים) המיפוי אינו
            אמין, ולכן סורקים את כל התאים בלי לדלג על אף עמודה.
    """
    if "kind" in col_map:
        kind = classify_kind(_text_at(row, col_map, "kind"))
        if kind != KIND_OTHER:
            return kind
    # אין עמודת סוג (או שהיא לא אמרה כלום) — סורקים את השורה, אבל מדלגים על
    # עמודות טקסט חופשי: "פרופ' כהן" או הערה "מעבר לקבוצה" היו מטעים אותנו.
    skip = (
        {col_map[k] for k in ("lecturer", "note", "room", "building") if k in col_map}
        if trust_columns
        else set()
    )
    for i, cell in enumerate(row):
        if i in skip:
            continue
        kind = classify_kind(_cell_text(cell))
        if kind != KIND_OTHER:
            return kind
    return KIND_OTHER


def _gid_sort_key(group: Group) -> tuple[int, int, str]:
    """מיון קבוצות: קודם לפי סוג הרכיב, אחר כך לפי מספר הקבוצה."""
    kind_idx = KIND_ORDER.index(group.kind) if group.kind in KIND_ORDER else len(KIND_ORDER)
    digits = re.sub(r"\D", "", group.group_id)
    return kind_idx, int(digits) if digits else 10**6, group.group_id


def _rows_to_groups(
    grid: list[list[Any]],
    header_idx: int,
    col_map: dict[str, int],
    code: str,
    warnings: list[str],
) -> list[Group]:
    """הופך את שורות הנתונים לרשימת ``Group``.

    כלל המיזוג המרכזי: קבוצה אחת יכולה להיפגש כמה פעמים בשבוע, ואז מופיעות לה
    כמה שורות עם אותו מספר קבוצה ואותו סוג. אנחנו ממזגים אותן לקבוצה אחת עם
    כמה ``Meeting``, לפי המפתח ``(group_id, kind)``.

    שורה שבה תא הקבוצה ריק נחשבת "שורת המשך" ויורשת את הקבוצה / הסוג / המרצה
    מהשורה שמעליה — זה הכתיב הנפוץ בידיעון כשמפגש שני נרשם מתחת לראשון.
    """
    synth_ids = "group" not in col_map
    if synth_ids:
        warnings.append(
            f"קורס {code}: לא נמצאה עמודת 'קבוצה' — מזהי הקבוצות סונתזו לפי סוג "
            f"ומרצה (group column missing, ids synthesized)."
        )

    by_key: dict[tuple[str, str], Group] = {}
    order: list[tuple[str, str]] = []
    seen_meetings: dict[tuple[str, str], set[tuple[int, int, int, str, str, str]]] = {}
    synth_counter: dict[str, int] = {}
    synth_seen: dict[tuple[str, str], str] = {}

    # רוחב הכותרת בעמודות מלאות. שורה שרוחבה שונה מעידה על אי-התאמה במספר
    # התאים (rowspan/colspan או כותרת חלקית) ולכן תיקרא פוזיציונית.
    header_width = (
        sum(1 for c in grid[header_idx] if c is not None) if header_idx < len(grid) else 0
    )
    mismatch_reported = False

    prev_gid, prev_kind, prev_lecturer = "", "", ""

    for r in range(header_idx + 1, len(grid)):
        row = grid[r]
        texts = [_cell_text(c) for c in row]
        if not any(texts):
            continue

        rownum = r + 1
        ctx = f"קורס {code} שורה {rownum}"

        # קודם כול מנסים לחלץ מפגשים — זה מה שמבדיל שורת נתונים מכל השאר.
        row_width = sum(1 for c in row if c is not None)
        mismatched = header_width > 0 and row_width != header_width
        if mismatched and not mismatch_reported:
            mismatch_reported = True
            warnings.append(
                f"קורס {code}: מספר התאים בשורה ({row_width}) שונה ממספר עמודות "
                f"הכותרת ({header_width}) — הקריאה לפי הכותרת נשמרת, ובנוסף נעשית "
                f"סריקה פוזיציונית להצלבה (cell-count mismatch, positional cross-check)."
            )
        meetings = _row_meetings(row, col_map, warnings, ctx, force_scan=mismatched)
        if not meetings:
            snippet = " | ".join(t for t in texts if t)[:160]
            if _looks_like_header(row):
                # כותרת שחוזרת באמצע הטבלה — לא שגיאה, אבל גם לא "בשקט":
                # המפרט דורש שכל שורה שדולגה תשאיר עקבות באזהרות.
                warnings.append(
                    f"{ctx}: השורה זוהתה ככותרת חוזרת ודולגה. תוכן: '{snippet}' "
                    f"(row skipped: looks like a repeated header)."
                )
                continue
            warnings.append(
                f"{ctx}: השורה דולגה — לא נמצאו יום ושעה תקינים. תוכן: '{snippet}' "
                f"(row skipped: no day+time)."
            )
            continue

        raw_gid = _text_at(row, col_map, "group")
        gid, linked, gid_warning = _split_group_id(raw_gid)
        if gid_warning:
            warnings.append(f"{ctx}: {gid_warning}")

        inherited = False
        if not gid and not synth_ids:
            gid = prev_gid
            inherited = True

        kind = _detect_kind(row, col_map, trust_columns=not mismatched)
        if kind == KIND_OTHER and inherited and prev_kind:
            kind = prev_kind

        lecturer = _text_at(row, col_map, "lecturer")
        if _is_kind_word(lecturer):
            # עמודת המרצה מכילה מילת סוג — סימן שהמיפוי החליק. עדיף מרצה ריק
            # מאשר "הרצאה" שיופיע אחר כך בתפריט בחירת המרצים.
            warnings.append(
                f"{ctx}: בעמודת המרצה נמצא '{lecturer}' שהוא סוג מפגש ולא שם — "
                f"השדה רוקן (lecturer column holds a component kind)."
            )
            lecturer = ""
        if not lecturer and inherited:
            lecturer = prev_lecturer

        note = _text_at(row, col_map, "note")
        note_linked, note_warning = _linked_from_note(note)
        if note_warning:
            warnings.append(f"{ctx}: {note_warning}")

        if synth_ids:
            # אין עמודת קבוצה: מזהה מסונתז לכל צירוף (סוג, מרצה).
            signature = (kind, lecturer)
            if signature not in synth_seen:
                synth_counter[kind] = synth_counter.get(kind, 0) + 1
                synth_seen[signature] = str(synth_counter[kind])
            gid = synth_seen[signature]

        key = (gid, kind)
        if key not in by_key:
            by_key[key] = Group(
                course_code=code,
                group_id=gid,
                kind=kind,
                lecturer=lecturer,
                meetings=[],
                linked_to=[],
                note=note,
            )
            seen_meetings[key] = set()
            order.append(key)

        group = by_key[key]
        if not group.lecturer and lecturer:
            group.lecturer = lecturer
        if note and note not in group.note:
            group.note = (group.note + " | " + note) if group.note else note

        for linked_id in list(linked) + list(note_linked):
            if linked_id and linked_id != gid and linked_id not in group.linked_to:
                group.linked_to.append(linked_id)

        for m in meetings:
            # הסמסטר הוא חלק מהזהות! קורס שנפתח גם בא' וגם בב' באותו יום
            # ובאותה שעה מייצר שתי שורות שנבדלות רק בעמודה הזאת.
            fingerprint = (m.day, m.start, m.end, m.room, m.building, m.semester)
            if fingerprint in seen_meetings[key]:
                continue
            seen_meetings[key].add(fingerprint)
            group.meetings.append(m)

        prev_gid, prev_kind, prev_lecturer = gid, kind, lecturer

    groups = [by_key[k] for k in order]
    for g in groups:
        g.meetings.sort(key=lambda m: (m.day, m.start, m.end, m.semester))
    groups.sort(key=_gid_sort_key)
    return groups


# ==========================================================================
# 5b. המבנה האמיתי של הידיעון: רשת DIV של Bootstrap — לא ``<table>``
# ==========================================================================
# ‏GROUND_TRUTH.md סעיף 2 (שגובר על SPEC.md סעיף 4): בדפי הידיעון האמיתיים
# אין ולו ``<table>`` אחד. התוצאות בנויות מ-``div.row`` / ``div.col``, וכל
# קבוצה היא "בלוק" שמתחיל ב-``div.TextAlignRight`` ואחריו טבלת מערכת שעות.
# פרסר שמחפש ``<table>`` בלבד מחזיר אפס קבוצות בכל אחד מחמשת ה-fixtures.
#
# הנתיב הזה נוסף *לצד* נתיב הטבלאות ולא במקומו: הידיעון של בראודה עדיין לא
# נראה בעיניים, ותבנית טבלאות עלולה לחזור בעמוד אחר.

#: "קורס מסוג <סוג>" — עד "קבוצה :" או "מרצה הקורס".
_GROUP_KIND_RE = re.compile(r"קורס\s*מסוג\s*(.{0,60}?)\s*(?:קבוצה\s*:|מרצה\s*ה?קורס|$)")
#: "קבוצה : 27103001" — המזהה נשמר כמות שהוא (GROUND_TRUTH סעיף 4.4).
_GROUP_ID_RE = re.compile(r"קבוצה\s*:\s*(\d[\w.-]{0,19}(?:\s*/\s*\d{1,3})?)")
#: "מרצה הקורס : ד"ר שפיגל הדר" (טקסט הכפתור כבר הוסר).
_GROUP_LECTURER_RE = re.compile(
    r"מרצה\s*ה?קורס\s*:\s*(.+?)\s*(?:שפת\s*הוראה|פרטים\s*נוספים|$)"
)
#: "( קבוצות הקשורות לקורס זה : 27103005 , 27103006 )"
_LINKED_IDS_RE = re.compile(r"קבוצ\w*\s*הקשור\w*\s*לקורס\s*זה\s*:?\s*([^)\]]*)")

#: מזהה קבוצה בודד בתוך רשימת הקבוצות הצמודות.
#: בבראודה הרשימה נראית כך: "271060330 /  1 , 271070330 /  1" — כלומר המזהה
#: עצמו מכיל "/" ואי אפשר לפצל עליו. פיצול נאיבי על "/" הפך כל מזהה לשניים
#: ("271060330" ו-"1"), הקישור לא התאים לאף קבוצה אמיתית, ואילוץ הקבוצות
#: הצמודות פשוט לא נאכף — כלומר הכלי היה מציע שילובים שאי אפשר להירשם אליהם.
_LINKED_ID_ITEM_RE = re.compile(r"\d{3,}(?:\s*/\s*\d{1,3})?")


def _norm_group_id(text: str) -> str:
    """מנרמל מזהה קבוצה לצורה אחידה: ``"271060330/ 1"`` -> ``"271060330/1"``.

    חייב לחול גם על ``Group.group_id`` וגם על ``linked_to``, אחרת השניים
    לא ישתוו זה לזה והקישור בין הרצאה לתרגול יאבד.
    """
    return re.sub(r"\s*/\s*", "/", _clean(text))
_LINKED_CLAUSE_RE = re.compile(r"[(\[]\s*קבוצ\w*\s*הקשור\w*[^)\]]*[)\]]")


def _is_ancestor(node: Any, target: Any) -> bool:
    """האם ``node`` הוא אב-קדמון של ``target``?"""
    for parent in getattr(target, "parents", []):
        if parent is node:
            return True
    return False


def _classes(node: Any) -> list[str]:
    """רשימת ה-class של אלמנט (bs4 מחזיר לפעמים מחרוזת ולפעמים רשימה)."""
    raw = node.get("class") if hasattr(node, "get") else None
    if not raw:
        return []
    return raw.split() if isinstance(raw, str) else [str(c) for c in raw]


def _is_div_row(node: Any) -> bool:
    return getattr(node, "name", None) == "div" and "row" in _classes(node)


def _is_div_col(node: Any) -> bool:
    if getattr(node, "name", None) != "div":
        return False
    return any(c == "col" or c.startswith("col-") for c in _classes(node))


def _visible_text(node: Any) -> str:
    """טקסט של אלמנט בלי כפתורים/סקריפטים — הכפתור "פרטים נוספים" אינו תוכן."""
    if node is None:
        return ""
    if getattr(node, "name", None) is None:
        return _clean(node)
    parts: list[str] = []
    for child in node.descendants:
        if getattr(child, "name", None) is not None or isinstance(child, Comment):
            continue
        if child.find_parent(["button", "script", "style", "noscript"]) is not None:
            continue
        parts.append(str(child))
    return _clean(" ".join(parts))


def _is_group_block(node: Any) -> bool:
    """האם האלמנט הוא הכותרת של בלוק קבוצה ("קורס מסוג ... קבוצה : ...")?"""
    text = _visible_text(node)
    if not text or len(text) > 600 or not _GROUP_ID_RE.search(text):
        return False
    return "קורס מסוג" in text or "מרצה הקורס" in text or "מרצה קורס" in text


def _find_group_blocks(soup: Any) -> list[Any]:
    """כל בלוקי הקבוצות בדף, בסדר הופעתם."""
    # שער מהיר: בלי הביטויים האלה אין בדף בלוקי קבוצה, ואין טעם לסרוק כל אלמנט.
    page = _clean(soup.get_text(" ", strip=True))
    if "קבוצה" not in page or not any(
        p in page for p in ("קורס מסוג", "מרצה הקורס", "מרצה קורס")
    ):
        return []
    blocks = [d for d in soup.find_all("div", class_="TextAlignRight") if _is_group_block(d)]
    if blocks:
        return blocks
    # סובלנות לשינוי שמות מחלקות: מחפשים בכל אלמנט, ושומרים רק את הפנימיים.
    cands = [t for t in soup.find_all(["div", "p", "td", "li", "section"]) if _is_group_block(t)]
    return [t for t in cands if not any(c is not t and _is_ancestor(t, c) for c in cands)]


def _block_scope(block: Any, next_block: Any) -> list[Any]:
    """האלמנטים ששייכים לבלוק: הבלוק עצמו וכל האחים שאחריו עד הבלוק הבא."""
    scope = [block]
    for sib in block.next_siblings:
        if getattr(sib, "name", None) is None:
            continue
        if next_block is not None and (sib is next_block or _is_ancestor(sib, next_block)):
            break
        if _is_group_block(sib) or any(_is_group_block(d) for d in sib.find_all("div")):
            break
        scope.append(sib)
    return scope


def _scope_elements(scope: list[Any], names: list[str] | None = None) -> list[Any]:
    """כל האלמנטים שבתוך ה-scope (כולל אברי ה-scope עצמם), בסדר המסמך."""
    out: list[Any] = []
    seen: set[int] = set()
    for node in scope:
        if getattr(node, "name", None) is None:
            continue
        for el in [node] + list(node.find_all(names if names else True)):
            if names and el.name not in names:
                continue
            if id(el) in seen:
                continue
            seen.add(id(el))
            out.append(el)
    return out


def _find_group_label(scope: list[Any], block: Any = None) -> str:
    """התווית הירוקה של הקבוצה ("שיעור א' - מסלול בוקר ( קבוצות הקשורות ... )").

    התווית הזאת ריקה בחלק מהקורסים; אם קיים אלמנט ירוק אך הוא ריק — זו התשובה
    ("אין תווית"), ואסור לרדת לגיבוי ולתפוס במקומה את ה-span הכחול של מספר
    הקבוצה.
    """
    tags = _scope_elements(scope, ["span", "strong", "b", "font"])
    green_seen = False
    for el in tags:
        style = _clean(el.get("style", "")).lower()
        if "green" not in style and "green" not in " ".join(_classes(el)).lower():
            continue
        green_seen = True
        text = _visible_text(el)
        if text:
            return text
    if green_seen:
        return ""
    # גיבוי: הדגשה שאינה חלק מכותרת הבלוק ואינה כותרת הכרטיס.
    for el in tags:
        if el.name not in ("strong", "b"):
            continue
        if block is not None and (el is block or _is_ancestor(block, el)):
            continue
        text = _visible_text(el)
        if not text or len(text) > 200:
            continue
        if "מערכת שעות" in text or "מרצה" in text or _GROUP_ID_RE.search(text):
            continue
        return text
    return ""


def _scope_rows(scope: list[Any]) -> list[Any]:
    """שורות ה-``div.row`` הפנימיות ביותר שבתוך ה-scope."""
    rows: list[Any] = []
    for el in _scope_elements(scope, ["div"]):
        if not _is_div_row(el):
            continue
        if any(_is_div_row(d) for d in el.find_all("div")):
            continue                      # שורה שעוטפת שורות אחרות אינה שורת נתונים
        rows.append(el)
    return rows


def _row_cols(row: Any) -> list[Any]:
    """תאי ``div.col`` ששייכים ישירות לשורה (בלי תאים מקוננים בתוך תא)."""
    cols: list[Any] = []
    for cell in row.find_all("div"):
        if not _is_div_col(cell):
            continue
        parent = cell.parent
        nested = False
        while parent is not None and parent is not row:
            if _is_div_col(parent):
                nested = True
                break
            parent = parent.parent
        if not nested:
            cols.append(cell)
    return cols


def _div_grid(rows: list[Any]) -> list[list[Any]]:
    """רשת מלבנית מתוך שורות ה-div, באותה צורה שבה ``_table_grid`` מחזיר טבלה."""
    grid = [cols for cols in (_row_cols(r) for r in rows) if cols]
    width = max((len(g) for g in grid), default=0)
    for g in grid:
        while len(g) < width:
            g.append(None)
    return grid


#: הכותרות האפשריות של העמודה הראשונה בטבלת מערכת השעות.
_DIV_HEADER_FIRST_CELL = ("סמסטר", "semester", "term")


def _is_div_header_row(row: list[Any]) -> bool:
    """שורת כותרת של רשת ה-div.

    ‏GROUND_TRUTH.md סעיף 5, מילה במילה: שורה היא **כותרת** אם טקסט התא הראשון
    שלה (אחרי ניקוי) שווה ל-"סמסטר"; אחרת היא שורת מפגש. במפורש: *לא* לפי
    מיקום — יש קורסים שבהם קודמת לכותרת שורה ריקה.

    הבדיקה הזאת היא הראשית. הניקוד הכללי נשאר כגיבוי, למקרה שבבראודה מילת
    הכותרת תיכתב אחרת.
    """
    first = _cell_text(row[0]) if row else ""
    if first and first.lower() in _DIV_HEADER_FIRST_CELL:
        return True

    # גיבוי סובלני: שורה שכולה תוויות כותרת מוכרות, בלי שעות ובלי ימים.
    _col_map, score = _map_columns(row)
    if score < 2 or _row_has_time(row):
        return False
    return not any(
        _parse_day_ex(_cell_text(c), allow_bare_digit=False) is not None for c in row
    )


def _div_header_index(grid: list[list[Any]]) -> tuple[int, dict[str, int], int]:
    """אינדקס שורת הכותרת ברשת ה-div, ומיפוי העמודות שלה."""
    for idx, row in enumerate(grid):
        if _is_div_header_row(row):
            col_map, score = _map_columns(row)
            return idx, col_map, score
    return -1, {}, 0


def _blocks_to_groups(blocks: list[Any], code: str, warnings: list[str]) -> list[Group]:
    """הופך את בלוקי ה-div לרשימת ``Group`` (נתיב הידיעון האמיתי)."""
    by_key: dict[tuple[str, str], Group] = {}
    order: list[tuple[str, str]] = []
    seen_meetings: dict[tuple[str, str], set[tuple[int, int, int, str, str, str]]] = {}

    for i, block in enumerate(blocks):
        next_block = blocks[i + 1] if i + 1 < len(blocks) else None
        scope = _block_scope(block, next_block)
        head = _visible_text(block)

        # --- מזהה הקבוצה: קודם מה-span הכחול, אחר כך מכל טקסט הבלוק ---
        gid = ""
        for span in block.find_all("span"):
            style = _clean(span.get("style", "")).lower()
            if "blue" not in style and "blue" not in " ".join(_classes(span)).lower():
                continue
            m = _GROUP_ID_RE.search(_visible_text(span))
            if m:
                gid = _norm_group_id(m.group(1))
                break
        if not gid:
            m = _GROUP_ID_RE.search(head)
            gid = _norm_group_id(m.group(1)) if m else ""
        if not gid:
            gid = f"?{i + 1}"
            warnings.append(
                f"קורס {code}: בבלוק קבוצה מס' {i + 1} לא נמצא מספר קבוצה — נוצר מזהה "
                f"זמני '{gid}' (group id missing in block)."
            )
        ctx = f"קורס {code} קבוצה {gid}"

        # הסמסטר של הקבוצה לפי הידיעון עצמו. קריטי לקבוצות בלי מועד: הוא
        # מה שמבדיל בין "פרויקט גמר של סמסטר א' בלי שעות" לבין "קבוצה של
        # סמסטר ב' שטרם נקבע לה מועד" — שתיהן קבוצות בלי מפגשים.
        block_semester = semester_from_details_args(str(block))

        label = _find_group_label(scope, block)

        # --- סוג המפגש: "קורס מסוג ..." ואם אין — התווית הירוקה ---
        m = _GROUP_KIND_RE.search(head)
        kind_text = _clean(m.group(1)) if m else ""
        kind = classify_kind(kind_text) if kind_text else classify_kind(label)

        # --- מרצה ---
        m = _GROUP_LECTURER_RE.search(head)
        lecturer = _clean(m.group(1)).strip(" ,;:-") if m else ""
        if _is_kind_word(lecturer):
            lecturer = ""

        # --- קבוצות קשורות + הערה ---
        linked: list[str] = []
        note = ""
        if label:
            m = _LINKED_IDS_RE.search(label)
            if m:
                linked = [
                    _norm_group_id(x) for x in _LINKED_ID_ITEM_RE.findall(_clean(m.group(1)))
                ]
            note = _clean(_LINKED_CLAUSE_RE.sub(" ", label))

        # --- מפגשים: רשת ה-div של "מערכת שעות" ---
        grid = _div_grid(_scope_rows(scope))
        header_idx, col_map, _score = _div_header_index(grid)
        meetings: list[Meeting] = []
        if header_idx < 0:
            warnings.append(
                f"{ctx}: לא נמצאה שורת כותרת בטבלת מערכת השעות של הקבוצה — "
                f"יש לבדוק את ה-HTML הגולמי (group schedule header row not found)."
            )
        for r in range(header_idx + 1, len(grid)):
            row = grid[r]
            texts = [_cell_text(c) for c in row]
            if not any(texts):
                continue
            rctx = f"{ctx} שורה {r + 1}"
            if _is_div_header_row(row):
                warnings.append(
                    f"{rctx}: השורה זוהתה ככותרת חוזרת ודולגה "
                    f"(row skipped: looks like a repeated header)."
                )
                continue
            got = _row_meetings(row, col_map, warnings, rctx)
            if not got:
                snippet = " | ".join(t for t in texts if t)[:160]
                warnings.append(
                    f"{rctx}: השורה דולגה — לא נמצאו יום ושעה תקינים. תוכן: '{snippet}' "
                    f"(row skipped: no day+time)."
                )
                continue
            meetings.extend(got)
            if not lecturer:
                row_lecturer = _text_at(row, col_map, "lecturer")
                if row_lecturer and not _is_kind_word(row_lecturer):
                    lecturer = row_lecturer

        if not meetings:
            # קבוצה בלי אף שורת מפגש = קורס שנפתח אבל **אין לו מועד קבוע**:
            # פרויקט גמר, סמינר בתיאום אישי, ספורט, קורסים כלליים. בבראודה
            # תשפ"ז אלה 163 קורסים מתוך 571 — 29% מהקטלוג, וביניהם קורסי
            # החובה "ספורט" ושלושת "הקורסים הכלליים".
            #
            # קודם הן נזרקו, ואז הקורס נעלם לגמרי ודווח כ"כשל פענוח". זו
            # החלטה שגויה עבור בונה מערכת: אי אפשר *לשבץ* קבוצה כזאת, אבל
            # בהחלט אפשר ורוצים *להירשם* אליה ולספור את הנ"ז שלה. בלי מפגשים
            # היא ממילא לא מתנגשת עם כלום ולא תופסת שום משבצת ברשת.
            note = " | ".join(x for x in (note, NO_FIXED_TIME_NOTE) if x)
            warnings.append(
                f"{ctx}: אין מועד קבוע בדף — הקבוצה נשמרת ככזאת ולא תופיע ברשת "
                f"השעות (no fixed time; kept as unscheduled)."
            )

        key = (gid, kind)
        if key not in by_key:
            by_key[key] = Group(
                course_code=code,
                group_id=gid,
                kind=kind,
                lecturer=lecturer,
                meetings=[],
                linked_to=[],
                note=note,
                semester=block_semester,
            )
            seen_meetings[key] = set()
            order.append(key)

        group = by_key[key]
        if not group.semester and block_semester:
            group.semester = block_semester
        if not group.lecturer and lecturer:
            group.lecturer = lecturer
        if note and note not in group.note:
            group.note = (group.note + " | " + note) if group.note else note
        for linked_id in linked:
            if linked_id and linked_id != gid and linked_id not in group.linked_to:
                group.linked_to.append(linked_id)
        for meeting in meetings:
            # הסמסטר הוא חלק מהזהות (ראו ההערה בנתיב הטבלאות).
            fingerprint = (
                meeting.day, meeting.start, meeting.end,
                meeting.room, meeting.building, meeting.semester,
            )
            if fingerprint in seen_meetings[key]:
                continue
            seen_meetings[key].add(fingerprint)
            group.meetings.append(meeting)

    groups = [by_key[k] for k in order]
    for g in groups:
        g.meetings.sort(key=lambda m: (m.day, m.start, m.end, m.semester))
    groups.sort(key=_gid_sort_key)
    return groups


# ==========================================================================
# 6. פרטי הקורס עצמו (שם, נ"ז)
# ==========================================================================
_CREDIT_PATTERNS = [
    re.compile(r"(\d{1,2}(?:\.\d)?)\s*נ\s*[\"']?\s*ז(?![א-ת])"),
    re.compile(r"נקודות\s*זכות[^0-9]{0,12}(\d{1,2}(?:\.\d)?)"),
    re.compile(r"נ\s*[\"']?\s*ז(?![א-ת])[^0-9]{0,12}(\d{1,2}(?:\.\d)?)"),
]

#: תגיות שבהן סביר למצוא את שם הקורס.
_NAME_TAGS = ("h1", "h2", "h3", "title", "b", "strong", "span", "td", "th", "div", "p")


def _make_soup(html: str, warnings: list[str]) -> Any:
    """בונה ``BeautifulSoup`` עם lxml, ונופל בחזרה ל-html.parser אם צריך."""
    try:
        return BeautifulSoup(html, "lxml")
    except Exception as exc:  # pragma: no cover - lxml is installed
        warnings.append(f"lxml נכשל ({exc}); נעשה שימוש ב-html.parser (parser fallback).")
        return BeautifulSoup(html, "html.parser")


#: כותרות שהן "רהיטים" של האתר ולא שם קורס. ה-``<h1>`` של הידיעון הוא תמיד
#: "חיפוש קורסים במערכת - לפי נושא", ובלעדי הרשימה הזאת *כל* קורס היה מוצג
#: תחת השם הזה.
_PAGE_CHROME_PATTERNS: tuple[str, ...] = (
    "חיפוש קורסים", "חיפוש קורס", "מידע-נט", "מידע נט", "ידיעון", "דף הבית",
    "מערכת שעות", "תפריט", "התחברות", "כניסה למערכת", "מכללת בראודה",
)

#: 'קורס מתמטיקה ב\' שנה"ל תשפ"ז' -> "מתמטיקה ב'" (GROUND_TRUTH סעיף 3).
_COURSE_TITLE_YEAR_RE = re.compile(r"\s*שנה\s*[\"']?\s*ל\b.*$")
_COURSE_TITLE_PREFIX_RE = re.compile(r"^\s*קורס\s+")


def _is_page_chrome(text: str) -> bool:
    """האם הטקסט הוא כותרת של האתר ולא שם של קורס?"""
    t = _clean(text)
    return any(p in t for p in _PAGE_CHROME_PATTERNS)


def _course_name_from_title_h2(soup: Any) -> str:
    """שם הקורס מתוך ``h2.TextAlignCenter`` — הכותרת האמיתית בדף הידיעון."""
    for tag in soup.find_all(["h1", "h2", "h3"]):
        if "TextAlignCenter" not in _classes(tag):
            continue
        text = _cell_text(tag)
        if not text or len(text) > 160:
            continue
        text = _clean(_COURSE_TITLE_YEAR_RE.sub("", text))
        text = _clean(_COURSE_TITLE_PREFIX_RE.sub("", text))
        if 2 <= len(text) <= 120 and not _is_page_chrome(text):
            return text
    return ""


def _extract_course_name(soup: Any, code: str, fallback_name: str, warnings: list[str]) -> str:
    """מנסה לחלץ את שם הקורס מהדף; אם לא הצליח — משתמש ב-``fallback_name``.

    סדר הניסיונות (חשוב!):
        1. כותרת שמופיעה יחד עם קוד הקורס ("61756 - שיטות הנדסיות...").
        2. ``h2.TextAlignCenter`` — הכותרת של דף התוצאות בידיעון.
        3. תווית "שם הקורס" ואחריה ערך (ולא כותרת עמודה!).
        4. ``fallback_name`` מתוך curriculum.json.
        5. רק בלית ברירה — כותרת כללית של הדף, ובתנאי שאינה כותרת של האתר.

    שלב 5 היה קודם לפני ה-fallback, ולכן כל קורס קיבל את ה-``<h1>`` של האתר
    ("חיפוש קורסים במערכת - לפי נושא") והשם הנכון נזרק בלי אזהרה.

    מחפשים רק בתוך אלמנטים קצרים (עד 120 תווים), כדי לא "לבלוע" חצי דף.
    """
    if code:
        after = re.compile(r"^\s*(?:קורס\s*)?" + re.escape(code) + r"\s*[-–—:]\s*(.{3,80})$")
        before = re.compile(r"^\s*(.{3,80}?)\s*[-–—:]\s*(?:קורס\s*)?" + re.escape(code) + r"\s*$")
        for tag in soup.find_all(_NAME_TAGS, limit=4000):
            text = _cell_text(tag)
            if not text or len(text) > 120:
                continue
            m = after.match(text) or before.match(text)
            if m:
                name = _clean(m.group(1))
                if name and name != code and not _is_page_chrome(name):
                    return name

    # הכותרת הייעודית של דף הידיעון.
    title_name = _course_name_from_title_h2(soup)
    if title_name:
        return title_name

    # תווית "שם קורס" ואחריה הערך (טבלת פרטי קורס).
    for label in ("שם הקורס", "שם קורס"):
        node = soup.find(string=re.compile(re.escape(label)))
        if node is None:
            continue
        parent = getattr(node, "parent", None)
        sibling = parent.find_next(["td", "th", "span", "div"]) if parent is not None else None
        value = _cell_text(sibling)
        # ‏"שם הקורס" עשוי להיות *כותרת עמודה*; אז השכן הוא הכותרת הבאה
        # ("קבוצה") ולא שם הקורס. תא ``<th>`` או טקסט שמזוהה ככותרת — נפסלים.
        if getattr(sibling, "name", "") == "th" or _fields_for_header(value):
            continue
        if value and label not in value and 3 <= len(value) <= 120:
            return value

    if fallback_name:
        return _clean(fallback_name)

    # רק עכשיו — כותרת כללית של הדף, ובלבד שאינה כותרת של האתר עצמו.
    for tag_name in ("h1", "h2", "h3", "title"):
        for tag in soup.find_all(tag_name, limit=8):
            text = _cell_text(tag)
            text = re.sub(r"\s*[-|–]\s*(מכללת בראודה|בראודה|ידיעון).*$", "", text).strip()
            if 3 <= len(text) <= 120 and text != code and not _is_page_chrome(text):
                return text

    warnings.append(f"קורס {code}: שם הקורס לא נמצא בדף (course name not found).")
    return f"קורס {code}"


def _extract_credits(page_text: str, code: str, warnings: list[str]) -> float:
    """מחלץ נקודות זכות מהדף; 0.0 אם לא נמצא (הקורא ישלים מ-curriculum.json)."""
    for pattern in _CREDIT_PATTERNS:
        m = pattern.search(page_text)
        if m:
            try:
                return float(m.group(1))
            except ValueError:  # pragma: no cover
                continue
    warnings.append(
        f"קורס {code}: מספר נקודות הזכות לא נמצא בדף — נקבע 0.0, יש להשלים מתוך "
        f"curriculum.json (credits not found)."
    )
    return 0.0


# ==========================================================================
# 6c. סינון קבוצות לפי סמסטר
# ==========================================================================
def _filter_groups_by_semester(
    groups: list[Group], wanted: str, code: str, warnings: list[str]
) -> list[Group]:
    """משאיר בכל קבוצה רק את המפגשים של הסמסטר המבוקש.

    שלושת הכללים, לפי סדר החומרה:

    1. מפגש שהסמסטר שלו **מוכר ושונה** מהמבוקש — מוסר. זה כל תכלית הפונקציה.
    2. מפגש שהסמסטר שלו **ריק או לא מוכר** — **נשמר**, עם אזהרה. "לא ידוע"
       אינו "שגוי", ומחיקה שקטה של מפגש היא בדיוק מה שאסור לנו לעשות.
    3. קבוצה שלא נשאר בה אף מפגש — מוסרת, ונרשמת אזהרה שמזכירה את מספרה
       ואת העובדה שאינה מוצעת בסמסטר המבוקש.

    כלל 2 נשקל תמיד **בהקשר הקבוצה כולה**: אם שורות אחרות באותה קבוצה
    מצהירות סמסטר מוכר — והסמסטר המבוקש איננו ביניהן — אזי הדף עצמו
    אומר שהקבוצה אינה מתקיימת בסמסטר המבוקש, והשורות הריקות שבה
    שייכות לסמסטר שהיא כן מצהירה. במקרה הזה הקבוצה כולה מוסרת (עם
    אזהרה), אחרת קורס שהדף אומר עליו "סמסטר ב'" היה משריד שורה ריקה
    וזולג למערכת של סמסטר א'. רק כשהקבוצה לא מצהירה שום סמסטר מוכר
    — אין על מה להסתמך, והמפגשים נשמרים עם אזהרה כמקודם.

    Args:
        groups: הקבוצות שחולצו מהדף (משתנות במקום — ``meetings`` מוחלף).
        wanted: הסמסטר המבוקש, מנורמל ("א" / "ב" / "קיץ").
        code: קוד הקורס, לטובת נוסח האזהרות.
        warnings: רשימת האזהרות שאליה מוסיפים.

    Returns:
        רשימת הקבוצות ששרדו, באותו סדר.
    """
    survivors: list[Group] = []
    known_set = set(KNOWN_SEMESTERS)
    for group in groups:
        # קבוצה שמלכתחילה לא היו לה מפגשים אינה "נשרה בגלל הסמסטר" — פשוט
        # אין לה מועד. אסור להחיל עליה את כלל 3, אחרת פרויקט מסכם, ספורט
        # וקורסים כלליים ייעלמו שוב. ההבחנה נעשית *לפני* הסינון, כי אחריו
        # שני המצבים נראים זהים: רשימת מפגשים ריקה.
        if not group.meetings:
            declared_by_page = normalize_semester(getattr(group, "semester", ""))
            if declared_by_page and declared_by_page != wanted:
                warnings.append(
                    f"קורס {code} קב' {group.group_id}: אין לה מועד קבוע, והידיעון "
                    f"משייך אותה לסמסטר {declared_by_page} — לכן היא אינה נכללת "
                    f"בסמסטר {wanted}. (unscheduled, but belongs to another term)"
                )
                continue
            survivors.append(group)
            continue

        # מה הקבוצה עצמה מצהירה? שורה ריקה אינה עדות עצמאית — האחיות
        # שלה באותה טבלת מערכת שעות כבר אומרות באילו סמסטר הקבוצה מתקיימת.
        declared = {normalize_semester(m.semester) for m in group.meetings} & known_set
        if declared and wanted not in declared:
            warnings.append(
                f"קורס {code} קב' {group.group_id}: אינה מוצעת בסמסטר {wanted} — "
                f"הקבוצה מצהירה סמסטר {', '.join(sorted(declared))} בלבד, ולכן גם "
                f"שורות שבהן עמודת הסמסטר ריקה מיוחסות לסמסטר הזה. כל הקבוצה "
                f"הוסרה (group declares only semester "
                f"{', '.join(sorted(declared))}; blank rows attributed to it)."
            )
            continue

        kept: list[Meeting] = []
        dropped = 0
        for meeting in group.meetings:
            sem = normalize_semester(meeting.semester)
            if sem == wanted:
                kept.append(meeting)
            elif sem not in KNOWN_SEMESTERS:
                # כלל 2: לא ידוע -> נשמר + אזהרה.
                kept.append(meeting)
                warnings.append(
                    f"קורס {code} קב' {group.group_id}: לא ניתן לקבוע את הסמסטר של "
                    f"המפגש {meeting} — הוא נשמר למרות הסינון לסמסטר {wanted} "
                    f"(meeting semester could not be determined; kept)."
                )
            else:
                dropped += 1

        if kept:
            group.meetings = kept
            survivors.append(group)
            if dropped:
                warnings.append(
                    f"קורס {code} קב' {group.group_id}: {dropped} מפגשים הוסרו "
                    f"כי אינם בסמסטר {wanted} "
                    f"({dropped} meetings dropped: other semester)."
                )
        else:
            warnings.append(
                f"קורס {code} קב' {group.group_id}: אינה מוצעת בסמסטר {wanted} — "
                f"כל {dropped} מפגשיה שייכים לסמסטר אחר, והקבוצה הוסרה "
                f"(group {group.group_id} is not offered in semester {wanted})."
            )
    return survivors


# ==========================================================================
# 6b. extract_page_year — אימות שנת הלימודים של הדף
# ==========================================================================
# ‏GROUND_TRUTH.md סעיף 8: שנת הלימודים היא **מצב סשן**, לא פרמטר ב-URL.
# הידיעון של בראודה נפתח כברירת מחדל על תשפ"ו, בעוד שהמערכת הנדרשת היא
# תשפ"ז. אם לא מחליפים שנה — הכלי יחזיר בשקט את המערכת של השנה שעברה.
# לכן כל דף חייב להיבדק: הכותרת ‏h2.TextAlignCenter כתובה
# ``קורס <שם> שנה"ל תשפ"ז``, ומכאן אנחנו קוראים את השנה בפועל.

#: שנה עברית בכתיב הרגיל, עם גרשיים: תשפ"ז , תשע"ט , תש"ף.
_YEAR_QUOTED_RE = re.compile(r"(?<![א-ת])(תש[א-ת]?[\"'][א-ת])(?![א-ת])")
#: כתיב נדיר בלי גרשיים (תשפז). מותר רק אחרי התווית שנה"ל, אחרת מילים
#: תמימות כמו "תשלם" היו נקראות בטעות כשנה.
_YEAR_LOOSE_RE = re.compile(r"(?<![א-ת])(תש[א-ת]{1,2})(?![א-ת])")
#: התווית עצמה: שנה"ל / שנה'ל / שנה ל.
_YEAR_LABEL_RE = re.compile(r"שנה\s*[\"']?\s*ל(?![א-ת])")


def _year_from_text(text: str, require_label: bool = False) -> str | None:
    """מחלץ שנה עברית ממחרוזת אחת. ``None`` אם אין."""
    t = _clean(text)
    if not t:
        return None
    label = _YEAR_LABEL_RE.search(t)
    if label:
        for pattern in (_YEAR_QUOTED_RE, _YEAR_LOOSE_RE):
            m = pattern.search(t, label.end())
            if m:
                return m.group(1)
    if require_label:
        return None
    m = _YEAR_QUOTED_RE.search(t)
    return m.group(1) if m else None


def extract_page_year(html: str) -> str | None:
    """מחזיר את שנת הלימודים שמודפסת בדף, למשל ``'תשפ"ז'``.

    המקור העיקרי הוא ``h2.TextAlignCenter`` של דף הקורס, שכתוב בו
    ``קורס <שם הקורס> שנה"ל תשפ"ז``. אם אין כותרת כזאת — מנסים כל כותרת
    אחרת בדף, כך שגם כותרת דף החיפוש ("חיפוש קורסים במערכת תשפ"ז") נקראת;
    בדיוק מה שצריך כדי לוודא שהחלפת השנה הצליחה לפני שמתחילים לגרד.

    Args:
        html: ה-HTML הגולמי של הדף.

    Returns:
        השנה כמחרוזת עברית עם גרשיים (``'תשפ"ז'``), או ``None`` אם לא נמצאה.

    Warning:
        שנה שגויה היא הכשל הגרוע ביותר של הכלי הזה — היא מחזירה מערכת
        אמינה-למראה של השנה הלא נכונה. מי שקורא לפונקציה הזאת חייב להשוות
        לשנה המבוקשת ולעצור בקול רם אם אין התאמה.
    """
    if not html or not str(html).strip():
        return None
    soup = _make_soup(str(html), [])

    headings = list(soup.find_all(["h1", "h2", "h3"]))
    centered = [t for t in headings if "TextAlignCenter" in _classes(t)]

    # (1) הכותרת הייעודית, עם התווית שנה"ל — המקור המוסמך.
    for pool in (centered, headings):
        for tag in pool:
            year = _year_from_text(_cell_text(tag), require_label=True)
            if year:
                return year

    # (2) אותן כותרות, בלי התווית (כותרת דף החיפוש).
    for pool in (centered, headings):
        for tag in pool:
            year = _year_from_text(_cell_text(tag))
            if year:
                return year

    # (3) גיבוי אחרון: כל טקסט בדף שמכיל שנה"ל, ובלבד שאינו בתוך רשימת בחירה
    # (ל-<select> של החלפת השנה יש אופציה לכל שנה, וזה היה מטעה).
    for node in soup.find_all(string=_YEAR_LABEL_RE):
        parent = getattr(node, "parent", None)
        if parent is not None and parent.find_parent(["select", "option"]) is not None:
            continue
        year = _year_from_text(str(node), require_label=True)
        if year:
            return year
    return None


# ==========================================================================
# 7. parse_course_page — הפונקציה הראשית
# ==========================================================================
def parse_course_page(
    html: str,
    code: str,
    fallback_name: str = "",
    semester: str | None = None,
) -> ParseResult:
    """מפענח דף קורס מהידיעון ומחזיר ``ParseResult``.

    האלגוריתם:
        1. בונים soup ומחפשים הודעת "אין נתונים".
        2. מחלצים שם ונ"ז (best-effort).
        3. **נתיב א' — רשת DIV (המבנה האמיתי של הידיעון).** מחפשים בלוקי קבוצה
           ``div.TextAlignRight`` שכתוב בהם "קורס מסוג ... קבוצה : ...", וקוראים
           לכל בלוק את טבלת ``div.row``/``div.col`` של מערכת השעות.
        4. **נתיב ב' — טבלאות.** אם אין בלוקים (או שלא יצאה מהם אף קבוצה),
           עוברים על *כל* ה-``<table>``, מנקדים כל אחת לפי כותרות עבריות מוכרות
           (קבוצה / מרצה / יום / שעה / ש"ש / סוג / בניין / חדר / מפגש)
           ובוחרים את הטובה ביותר שיש בה לפחות 2 שורות נתונים.
        5. ממפים עמודות לפי טקסט הכותרת — אף פעם לא לפי אינדקס קבוע.
        6. קוראים שורות; שורות ללא יום+שעה מדולגות **עם אזהרה**.
        7. שורות עם אותו (מספר קבוצה, סוג) ממוזגות לקבוצה אחת עם כמה מפגשים.
        8. **סינון סמסטר** (אם התבקש) — ראו למטה.

    Args:
        html: ה-HTML הגולמי של דף הקורס.
        code: קוד הקורס, למשל ``"61756"``.
        fallback_name: שם קורס מתוך curriculum.json, אם הדף לא מגלה אותו.
        semester: ``"א"`` / ``"ב"`` / ``"קיץ"`` — או ``None``.

            * ``None`` (ברירת המחדל) — שומרים כל מפגש, בלי סינון.
            * ערך — שומרים **רק** מפגשים שעמודת הסמסטר שלהם תואמת. אחר כך:
              קבוצה שלא נשאר בה אף מפגש נזרקת ונרשמת אזהרה עם מספרה; ואם
              *כל* קבוצות הקורס נזרקו, מוחזר ``ParseResult(None, warnings)``
              עם אזהרה ברורה שהקורס אינו נפתח בסמסטר הזה.

            שימו לב: מפגש שעמודת הסמסטר שלו ריקה או לא מוכרת **לעולם לא
            מסונן החוצה** — הוא "לא ידוע", לא "שגוי". הוא נשמר, ונרשמת אזהרה.

    Returns:
        ``ParseResult(course, warnings)``. ``course`` יהיה ``None`` אם לא נמצאה
        טבלת קבוצות, שלא חולצה ממנה אף קבוצה תקינה, או שהקורס כולו אינו נפתח
        בסמסטר המבוקש — והמקרה האחרון הוא תוצאה **תקינה**, לא שגיאה: בדיוק כך
        נגלה אם 61753 אלגוריתמים נפתח בסמסטר א'.
    """
    warnings: list[str] = []
    code = _clean(code)

    if not html or not str(html).strip():
        warnings.append(f"קורס {code}: התקבל HTML ריק (empty HTML input).")
        return ParseResult(None, warnings)

    soup = _make_soup(str(html), warnings)
    page_text = _clean(soup.get_text(" ", strip=True))

    for phrase in _EMPTY_RESULT_PHRASES:
        if phrase in page_text:
            warnings.append(
                f"קורס {code}: הדף מכיל הודעת '{phrase}' — ייתכן שהקורס אינו נפתח "
                f"בסמסטר זה (page reports no results)."
            )
            break

    name = _extract_course_name(soup, code, fallback_name, warnings)
    credits = _extract_credits(page_text, code, warnings)

    # --- נתיב א': רשת ה-DIV, המבנה שאומת מול הידיעון החי ---
    groups: list[Group] = []
    blocks = _find_group_blocks(soup)
    if blocks:
        groups = _blocks_to_groups(blocks, code, warnings)

    # --- נתיב ב': טבלאות (עמוד ישן יותר, או נפילה-לאחור) ---
    if not groups:
        picked = _pick_group_table(soup)
        if picked is None:
            if not blocks:
                warnings.append(
                    f"קורס {code}: לא נמצאו קבוצות בדף — לא בלוקי ``div`` ולא טבלה. "
                    f"אם הדף כן הכיל קבוצות, יש לבדוק את ה-HTML הגולמי בתיקייה "
                    f"data/raw/ מול tests/fixtures/real_yedion/ (no group blocks or "
                    f"table found)."
                )
            else:
                warnings.append(
                    f"קורס {code}: נמצאו בלוקי קבוצות אך לא חולצה מהם אף קבוצה תקינה "
                    f"(group blocks found but none parsed)."
                )
            return ParseResult(None, warnings)

        grid, header_idx, col_map, score, few_rows = picked
        if few_rows:
            warnings.append(
                f"קורס {code}: הטבלה שנבחרה מכילה פחות משתי שורות נתונים "
                f"(only one data row in the best-scoring table)."
            )
        if score < 3:
            warnings.append(
                f"קורס {code}: הטבלה שנבחרה קיבלה ניקוד נמוך ({score}) — הפענוח עלול "
                f"להיות חלקי (low-confidence table match)."
            )

        groups = _rows_to_groups(grid, header_idx, col_map, code, warnings)

    if not groups:
        warnings.append(
            f"קורס {code}: נמצאה טבלה אך לא חולצה ממנה אף קבוצה תקינה — ייתכן "
            f"שהקורס אינו נפתח בסמסטר זה (no valid group rows)."
        )
        return ParseResult(None, warnings)

    # --- סינון לפי סמסטר (GROUND_TRUTH: מסננים אצלנו, לא בפקד של האתר) ---
    if semester is not None:
        wanted = normalize_semester(semester)
        if not wanted:
            warnings.append(
                f"קורס {code}: לא זוהה סמסטר מתוך '{semester}' — לא בוצע סינון "
                f"סמסטר וכל המפגשים נשמרו (unrecognized semester filter, no filtering)."
            )
        else:
            groups = _filter_groups_by_semester(groups, wanted, code, warnings)
            if not groups:
                warnings.append(
                    f"קורס {code} אינו נפתח בסמסטר {wanted} — אף אחת מקבוצות הקורס "
                    f"אינה מתקיימת בסמסטר הזה. זו תשובה תקינה ולא שגיאה "
                    f"(course not offered in semester {wanted})."
                )
                return ParseResult(None, warnings)

    # מדווחים על linked_to שמצביע על קבוצה שלא קיימת בדף — לא מוחקים נתון בשקט.
    known_ids = {g.group_id for g in groups}
    for g in groups:
        unknown = [x for x in g.linked_to if x not in known_ids]
        if unknown:
            warnings.append(
                f"קורס {code} קב' {g.group_id}: הפניה לקבוצות צמודות שלא נמצאו בדף: "
                f"{', '.join(unknown)} (linked group ids not found on page)."
            )

    course = Course(code=code, name=name, credits=credits, groups=groups, tied_with=[])
    return ParseResult(course, warnings)


# ==========================================================================
# 8. שמירה וטעינה של המטמון (data/sections.json)
# ==========================================================================
#: שמות השדות נשלפים מהדאטהקלאסים עצמם, כדי שהעיגול הלוך-ושוב יישאר מדויק
#: גם אם models.py יקבל שדה נוסף בעתיד.
_MEETING_FIELDS = {f.name for f in fields(Meeting)}
_GROUP_FIELDS = {f.name for f in fields(Group)}
_COURSE_FIELDS = {f.name for f in fields(Course)}

SECTIONS_SCHEMA = "braude-schedule-builder/sections"
SECTIONS_VERSION = 1


def _code_sort_key(code: str) -> tuple[int, str]:
    """מיון קודי קורס: מספריים לפי ערך, השאר לפי אלפבית."""
    c = str(code)
    return (int(c), c) if c.isdigit() else (10**9, c)


def save_sections(courses: dict[str, Course], path: str = "data/sections.json") -> None:
    """שומר את מטמון הקורסים ל-JSON בעברית קריאה.

    הקובץ נשמר תמיד ב-utf-8 עם ``ensure_ascii=False`` ו-``indent=2``, וממוין
    לפי קוד קורס — כך ששמירה חוזרת של אותם נתונים מייצרת קובץ זהה בייט-בייט
    (round-trip מדויק; יש בדיקה לזה ב-:func:`self_check`).

    Args:
        courses: מילון ``{course_code: Course}``.
        path: נתיב היעד. תיקיות חסרות נוצרות אוטומטית.
    """
    payload = {
        "schema": SECTIONS_SCHEMA,
        "version": SECTIONS_VERSION,
        "courses": {
            code: asdict(courses[code]) for code in sorted(courses, key=_code_sort_key)
        },
    }
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _meeting_from_dict(data: dict[str, Any]) -> Meeting:
    """בונה ``Meeting`` ממילון, תוך התעלמות משדות לא מוכרים."""
    kw = {k: v for k, v in data.items() if k in _MEETING_FIELDS}
    return Meeting(
        day=int(kw.get("day", 0)),
        start=int(kw.get("start", 0)),
        end=int(kw.get("end", 0)),
        room=_clean(kw.get("room", "")),
        building=_clean(kw.get("building", "")),
        # קובץ ישן שנכתב לפני שדה הסמסטר נטען כרגיל, עם "" (לא ידוע).
        # ‏normalize_semester אידמפוטנטית, ולכן ה-round-trip נשאר מדויק.
        semester=normalize_semester(kw.get("semester", "")),
    )


def _group_from_dict(data: dict[str, Any], course_code: str) -> Group:
    """בונה ``Group`` ממילון."""
    kw = {k: v for k, v in data.items() if k in _GROUP_FIELDS}
    return Group(
        course_code=str(kw.get("course_code") or course_code),
        group_id=str(kw.get("group_id", "")),
        kind=str(kw.get("kind") or KIND_OTHER),
        lecturer=str(kw.get("lecturer", "")),
        meetings=[_meeting_from_dict(m) for m in (kw.get("meetings") or [])],
        linked_to=[str(x) for x in (kw.get("linked_to") or [])],
        note=str(kw.get("note", "")),
    )


def _course_from_dict(data: dict[str, Any], code_hint: str = "") -> Course:
    """בונה ``Course`` ממילון."""
    kw = {k: v for k, v in data.items() if k in _COURSE_FIELDS}
    code = str(kw.get("code") or code_hint)
    return Course(
        code=code,
        name=str(kw.get("name", "")),
        credits=float(kw.get("credits", 0.0) or 0.0),
        groups=[_group_from_dict(g, code) for g in (kw.get("groups") or [])],
        tied_with=[str(x) for x in (kw.get("tied_with") or [])],
    )


def load_sections(path: str = "data/sections.json") -> dict[str, Course]:
    """טוען את מטמון הקורסים מ-JSON ומחזיר ``{course_code: Course}``.

    הפונקציה סלחנית לגבי צורת הקובץ, כדי שגם fixture שנכתב ביד יעבוד:
        * ``{"courses": {code: {...}}}``  — הפורמט שאנחנו כותבים
        * ``{"courses": [{...}, ...]}``   — רשימה תחת מפתח
        * ``{code: {...}}``               — מילון שטוח
        * ``[{...}, {...}]``              — רשימת קורסים

    Args:
        path: נתיב הקובץ.

    Returns:
        מילון ``{course_code: Course}``.

    Raises:
        FileNotFoundError: אם הקובץ לא קיים.
        ValueError: אם תוכן הקובץ אינו בצורה מוכרת.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"קובץ המטמון לא נמצא: {path} (sections cache not found — run with --refresh)."
        )
    # ‏utf-8-sig ולא utf-8: קובץ שנכתב ב-Notepad או ב-PowerShell 5.1
    # (‏Out-File / Set-Content -Encoding utf8) מקבל BOM, ו-json.load היה נופל עליו
    # עם "Unexpected UTF-8 BOM". הקידוד הזה קורא קובץ בלי BOM בדיוק אותו דבר,
    # ולכן ה-round-trip מול save_sections (שכותב utf-8 נקי) לא משתנה.
    with open(path, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)

    if isinstance(data, dict) and isinstance(data.get("courses"), dict):
        raw_courses = data["courses"]
    elif isinstance(data, dict) and isinstance(data.get("courses"), list):
        raw_courses = {
            str(c.get("code", i)): c for i, c in enumerate(data["courses"]) if isinstance(c, dict)
        }
    elif isinstance(data, list):
        raw_courses = {str(c.get("code", i)): c for i, c in enumerate(data) if isinstance(c, dict)}
    elif isinstance(data, dict):
        raw_courses = {k: v for k, v in data.items() if isinstance(v, dict)}
    else:
        raise ValueError(f"מבנה לא מוכר בקובץ {path} (unrecognized sections file shape).")

    courses: dict[str, Course] = {}
    for code_key, raw in raw_courses.items():
        if not isinstance(raw, dict):
            continue
        course = _course_from_dict(raw, str(code_key))
        courses[course.code or str(code_key)] = course
    return courses


# ==========================================================================
# ‏8.5 פרטי קורס — פענוח דף ‎S_CourseDetails‎ ("פרטים נוספים על הקורס המבוקש")
# ==========================================================================
# למה החלק הזה קיים: ‏493 מתוך 571 קורסי הקטלוג (86%) אינם מופיעים ב-
# ``data/curriculum.json``, ולכן דיווחו "0.0 נקודות זכות" — מספר שנראה אמיתי
# ואינו. דף הפרטים של הידיעון קריא לחלוטין בלי התחברות (GROUND_TRUTH §9)
# ונושא לכל קורס, מכל מחלקה, את הנתון האמיתי: נ"ז, פירוק שעות, שעות
# סמסטריאליות, שפת הוראה, תיאור ותנאי קדם.
#
# **הכלל החשוב ביותר כאן: לעולם לא 0.0 כשלא ידוע.** ``credits=None`` פירושו
# "לא יודעים", והממשק יציג מקף. סכום נ"ז ששותק על 86% מהקורסים גרוע מסכום
# שמודה בקול שאינו יודע.
#
# העמוד עצמו (נבדק מול שני דפים אמיתיים ב-tests/fixtures/real_yedion/):
#
#   <div class="row"><div class="col"><strong>61753 אלגוריתמים</strong></div></div>
#   <div class="row"><div class="col">נקודות זכות : 5.00</div></div>
#   <div class="row"><div class="col">שעות סמסטריאליות : 4.00</div></div>
#   <div class="row"><div class="col">שפת הוראה של הקורס : עברית</div></div>
#   <details><summary><h3>פרשיית לימוד</h3></summary>
#     <div>61753  אלגוריתמים <br>4 2 - -  5.0 נ"ז <br>מטרת הקורס היא …</div>
#   </details><p style="text-align:left"> … אותו בלוק בדיוק, שוב … </p>
#   <div class="card …"><h2 class="card-header-H2"> תנאי קדם לנושא </h2> …
#
# שתי מלכודות אמיתיות שנצפו בקבצים:
#   1. בלוק "פרשיית לימוד" מודפס **פעמיים** (פעם ב-<details> ופעם ב-<p>).
#      תיאור כפול הוא באג — ראו ``_details_dedupe_block``.
#   2. קורס שאינו נפתח (11001) מחזיר דף עם התוויות אבל **בלי ערכים**:
#      "נקודות זכות : " ריק, ובמקום שורות טבלה יושבים תגי-תבנית
#      ‎<!$MG_…>‎ שנעלמים בפירסור. זה דף חלקי תקין, לא שגיאה.


class CourseDetails(NamedTuple):
    """פרטי קורס מדף ‎S_CourseDetails‎ — הכול אופציונלי, שום דבר לא זורק.

    Attributes:
        code:          קוד הקורס (כפי שהתבקש; הדף רק מאמת אותו).
        name:          שם הקורס, או ``""`` אם לא נמצא.
        credits:       נקודות זכות, או ``None`` כשלא ידוע. **לעולם לא 0.0**
                       כמשמעות "לא ידוע" — זו כל מטרת המחלקה הזאת.
        hours:         פירוק שעות שבועיות ``{"he","te","ma","pr"}`` —
                       הרצאה / תרגיל / מעבדה / פרויקט. רכיב חסר בשורה מסומן
                       ``-`` בידיעון והופך כאן ל-``0.0`` (אפס אמיתי: אין
                       תרגיל). מילון **ריק** = השורה כולה לא נמצאה, כלומר
                       לא ידוע — וזה שונה מארבעה אפסים.
        weekly_hours:  "שעות סמסטריאליות", או ``None``.
        language:      "שפת הוראה של הקורס" (למשל ``"עברית"``), או ``""``.
        description:   תיאור הקורס בשורה אחת, או ``""``.
        prerequisites: שורות טבלת "תנאי קדם לנושא". כל שורה היא מילון עם
                       המפתחות ``code`` / ``name`` / ``relation`` /
                       ``alternative`` (ומעבר להם גם ``kind``,
                       ``alternative_name`` ו-``population``; ראו
                       ``_details_prereq_row``).
                       **הרשימה אינה רשימת תנאי קדם בלבד.** אותה טבלה
                       נושאת גם קורסים צמודים וגם תנאים אקסקלוסיביים
                       (שאומרים את ההפך: אסור להירשם אם כבר למדת), ולכן
                       כל צרכן חייב לסנן על ``kind == "prereq"`` לפני
                       שהוא מתייחס לשורה כאל דרישה.
        warnings:      אזהרות בעברית. שדה חסר תמיד מייצר אזהרה — חוץ
                       מטבלת תנאי קדם ריקה, שהיא תשובה לגיטימית: יש קורסים
                       בלי תנאי קדם.
    """

    code: str
    name: str
    credits: "float | None"
    hours: dict[str, float]
    weekly_hours: "float | None"
    language: str
    description: str
    prerequisites: list[dict]
    warnings: list[str]


#: מפתחות פירוק השעות, **לפי הסדר שבו הידיעון מדפיס אותם** בשורת
#: "פרשיית לימוד": הרצאה, תרגיל, מעבדה, פרויקט.
DETAILS_HOUR_KEYS: tuple[str, ...] = ("he", "te", "ma", "pr")

#: המפתחות שמובטח שיופיעו בכל שורת תנאי-קדם.
DETAILS_PREREQ_KEYS: tuple[str, ...] = ("code", "name", "relation", "alternative")

#: תוויות "שדה : ערך" בדף. לכל שדה כמה ניסוחים — הידיעון של בראודה ושל
#: ת"א-יפו לא תמיד מנסחים אותו דבר (ראו GROUND_TRUTH, האזהרה בראש המסמך).
_DETAILS_CREDIT_LABELS: tuple[str, ...] = ("נקודות זכות", "נקודות הזכות")
_DETAILS_WEEKLY_LABELS: tuple[str, ...] = (
    "שעות סמסטריאליות", "שעות סמסטריאליות בשבוע", "שעות שבועיות",
)
_DETAILS_LANGUAGE_LABELS: tuple[str, ...] = (
    "שפת הוראה של הקורס", "שפת ההוראה של הקורס", "שפת הוראה", "שפת הקורס",
)

#: כותרת בלוק "פרשיית לימוד" (הבלוק שנושא קוד+שם, שורת שעות ותיאור).
_DETAILS_SYLLABUS_LABEL = "פרשיית לימוד"

#: כותרת הכרטיס של טבלת תנאי הקדם. שימו לב שהיא **אינה** "תנאי קשר לתרגיל",
#: שהוא כרטיס אחר לגמרי (קבוצות צמודות) שיושב באותו דף.
_DETAILS_PREREQ_LABEL = "תנאי קדם"

#: שורת "61753  אלגוריתמים" -> ("61753", "אלגוריתמים").
_DETAILS_CODE_LINE_RE = re.compile(r"^\s*(\d{4,7})\s+(\S.*)$")

#: הסימן נ"ז בשורת השעות — **בכל מקום בשורה**, לא רק בסופה. יש דפים
#: שמדפיסים אותו לפני השעות (``'2 נ"ז , 1-0-2'``), והוא עדיין הסימן היחיד
#: שאומר איזה מספר הוא נקודות זכות ואיזה הוא שעות.
_DETAILS_CREDIT_MARK_RE = re.compile("נ\\s*[\"']?\\s*ז")

#: פיסוק שהידיעון משרבב לשורת השעות ואינו נושא מידע (``'2 נ"ז , 1-0-2'``).
_DETAILS_HOURS_JUNK_RE = re.compile(r"[,;]+")

#: אסימון מספרי "טהור" בשורת השעות: 4 , 2 , 5.0 , 5.00.
_DETAILS_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

#: כותרות טבלת תנאי הקדם -> שם השדה. הסדר משמעותי: הביטוי הראשון שמוכל
#: בכותרת מנצח, ולכן "נושא נקשר" חייב להיבדק לפני "נושא".
_DETAILS_PREREQ_HEADERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("relation", ("סוג הקשר", "סוג קשר", "סוג הקישור")),
    ("population", ("אוכלוסייה", "אוכלוסיה")),
    ("code", ("קוד קורס", "קוד נושא", "קוד מקצוע")),
    ("name", ("נושא נקשר", "שם קורס", "שם הקורס", "שם נושא", "נושא")),
    ("alternative", ("חליפי", "חלופי")),
)

#: כותרת שמציינת את **הנושא שהתנאי שייך לו** — כלומר הקורס המבוקש עצמו,
#: לעולם לא הקורס הקשור. חייבת להיפסל במפורש: היא מכילה "נושא", ובלעדי
#: הפסילה היא הייתה נחטפת כעמודת ``name`` והקורס היה הופך לתנאי קדם של
#: עצמו — תנאי שאי אפשר לעמוד בו לעולם.
_DETAILS_PREREQ_SUBJECT_LABELS: tuple[str, ...] = ("תנאי קדם לנושא", "תנאי קדם")

#: "סוג הקשר" -> ערך מנורמל. **לא כל שורה בטבלה היא תנאי קדם**: אותה טבלה
#: נושאת גם קורס צמוד (חייבים להירשם לשניהם) וגם תנאי אקסקלוסיבי, שהוא
#: ההפך הגמור — מי שלמד/ה את הקורס שמשמאל **אינו/ה** רשאי/ת להירשם.
#: הסדר משמעותי: "תנאי קדם" הוא תחילית של "תנאי קדם לנושא", ולכן אחרון.
_DETAILS_PREREQ_KINDS: tuple[tuple[str, str], ...] = (
    ("תנאי אקסקלוסיבי", "exclusive"),
    ("תנאי צמוד", "corequisite"),
    ("תנאי מקביל", "corequisite"),
    ("תנאי קדם", "prereq"),
)

#: סדר העמודות כשאין שורת כותרת בכלל — בדיוק כפי שהוא בדפים האמיתיים.
_DETAILS_PREREQ_FALLBACK_ORDER: tuple[str, ...] = (
    "relation", "population", "name", "alternative",
)


def _details_number(text: Any) -> "float | None":
    """המספר שבו **מתחיל** הטקסט, או ``None``. ``"5.00"`` -> ``5.0``.

    למה בתחילת הטקסט ולא בכל מקום בו: הערכים היחידים שמגיעים לכאן הם ערכי
    "תווית : ערך", ו"המספר הראשון שנמצא" הוא בדיוק הדרך שבה ערך של תווית
    שכנה באותה שורה מתחזה לערך שלנו. ערך ריק חייב להישאר "לא ידוע".
    """
    m = _DETAILS_NUMBER_RE.match(_clean(text))
    if m is None:
        return None
    try:
        return float(m.group(0))
    except ValueError:  # pragma: no cover - הרגקס כבר מבטיח מספר
        return None


def _details_hour_pieces(token: str) -> "list[str] | None":
    """אסימון אחד של שורת השעות -> רכיביו, או ``None`` אם אינו של שורת שעות.

    הידיעון אינו עקבי בצורת ההדפסה, וזה נמדד על דפים אמיתיים:
    ``'1-1-1'`` (רכיבים מחוברים במקפים), ``'1-'`` (מקף שנדבק למספר),
    ``'2.0'`` ו-``'-'`` — כולם חוקיים, וכולם מתפרקים כאן לרכיבים בודדים.
    """
    if not token:
        return None
    if set(token) == {"-"}:
        return ["-"]
    pieces: list[str] = []
    for part in token.split("-"):
        if part == "":
            pieces.append("-")          # '1-' -> ['1','-'] ; '-1' -> ['-','1']
        elif _DETAILS_NUMBER_RE.fullmatch(part):
            pieces.append(part)
        else:
            return None                 # יש כאן טקסט — זו לא שורת שעות
    return pieces


def _details_hour_groups(text: str) -> "list[list[str]] | None":
    """מפרק קטע לקבוצות רכיבים — קבוצה לכל אסימון שמופרד ברווח."""
    groups: list[list[str]] = []
    for token in text.split():
        pieces = _details_hour_pieces(token)
        if pieces is None:
            return None
        groups.append(pieces)
    return groups


def _details_looks_like_name(line: str) -> bool:
    """האם השורה יכולה בכלל להיות שם קורס — כלומר יש בה מילה ולא רק מספרים.

    שורה כמו ``'2 נ"ז , 1-0-2'`` היא שורת שעות בכתיב שלא זוהה, לא שם קורס.
    שם שנלקח ממנה **נראה** תקין ואינו, ולכן עדיף להשאיר את השם ריק ולתת
    לכותרת המודגשת שבראש הדף לספק אותו.
    """
    text = _DETAILS_HOURS_JUNK_RE.sub(" ", _DASH_RE.sub("-", _clean(line)))
    text = _DETAILS_CREDIT_MARK_RE.sub(" ", text)
    if not text.strip():
        return False
    return any(_details_hour_pieces(tok) is None for tok in text.split())


def _details_scope(soup: Any) -> Any:
    """האזור בדף שבו יושבים הפרטים — בלי הכותרת, התפריט והפוטר של האתר."""
    for selector in ("div.fcontainer", "main", "form", "body"):
        try:
            node = soup.select_one(selector)
        except Exception:  # noqa: BLE001 - סלקטור לא נתמך אינו סיבה ליפול
            node = None
        if node is not None:
            return node
    return soup


def _details_plain_lines(node: Any) -> list[str]:
    """שורות הטקסט של אלמנט, בלי סקריפטים וכפתורים. גיבוי לדפים לא צפויים."""
    if node is None or isinstance(node, str):
        return _cell_lines(node)
    clone = node
    try:
        clone = _copy.copy(node)
        for junk in clone.find_all(["script", "style", "noscript", "button"]):
            junk.decompose()
    except Exception:  # noqa: BLE001 - טקסט עם רעש עדיף על קריסה
        clone = node
    return _cell_lines(clone)


def _details_blobs(scope: Any) -> list[str]:
    """כל קטעי הטקסט של הדף, מהקצר-והממוקד אל הרחב — לחיפוש "תווית : ערך".

    התאים (``div.col``) קודמים, כי שם יושבות התוויות; שורות הטקסט הגולמיות
    הן גיבוי לדף שנבנה אחרת לגמרי (או ל-HTML מזערי בבדיקות).
    """
    blobs: list[str] = []
    seen: set[str] = set()

    def add(text: Any) -> None:
        t = _clean(text)
        if t and t not in seen:
            seen.add(t)
            blobs.append(t)

    cells: list[Any] = []
    if hasattr(scope, "find_all"):
        cells = [d for d in scope.find_all("div") if _is_div_col(d)]

    # תא "עלה" = תא שאין בתוכו שורות נוספות. אלה התאים של "תווית : ערך".
    for cell in cells:
        if not any(_is_div_row(d) for d in cell.find_all("div")):
            add(_cell_text(cell))
    for cell in cells:
        add(_cell_text(cell))
    for line in _details_plain_lines(scope):
        add(line)
    return blobs


#: כל התוויות המוכרות בדף. הן אינן משמשות לחיפוש אלא כדי לדעת **איפה
#: נגמר** הערך של התווית שכן חיפשנו: הידיעון מדפיס שלוש תוויות באותה שורה
#: ("נקודות זכות : 5.00  שעות סמסטריאליות : 4.00  סוג קורס : הרצאה"), וכשהערך
#: הראשון ריק — וזה המצב בכל דף שנמדד — ערך השכנה נראה בדיוק כמו ערך שלו.
_DETAILS_BOUNDARY_LABELS: tuple[str, ...] = (
    _DETAILS_CREDIT_LABELS + _DETAILS_WEEKLY_LABELS + _DETAILS_LANGUAGE_LABELS + (
        "סוג קורס", "סוג הקורס", "מרצה הקורס", "מרצה", "קבוצה", "סמסטר",
        "מחלקה", "שעות תרגיל", "שעות מעבדה", "אשכול",
    )
)


def _details_cut_at_next_label(value: str, label: str) -> str:
    """חותך ערך של תווית ברגע שמתחילה בו תווית אחרת.

    בלי זה ``נקודות זכות :`` ריקה בולעת את השורה כולה, ו-4.00 של "שעות
    סמסטריאליות" חוזר כנ"ז — מספר שנראה אמיתי ואינו. ערך ריק שנשאר ריק
    נופל בהמשך לשורת פרשיית הלימוד, וזו התשובה הנכונה.
    """
    cut = len(value)
    for other in _DETAILS_BOUNDARY_LABELS:
        if other == label:
            continue
        m = re.search(re.escape(other) + r"\s*:", value)
        if m is not None:
            cut = min(cut, m.start())
    return value[:cut]


def _details_label_value(blobs: list[str], labels: "tuple[str, ...]") -> "str | None":
    """הערך שאחרי ``תווית :``. ``None`` = התווית לא קיימת בדף; ``""`` = ריקה.

    ההבחנה הזאת חשובה: בדף של קורס שאינו נפתח התווית **כן** מופיעה
    ("נקודות זכות : ") והערך ריק — וזה עדיין "לא ידוע", לא אפס.
    """
    patterns = [
        (label, re.compile(re.escape(label) + r"\s*:\s*(.*)$")) for label in labels
    ]
    # מעבר ראשון על קטעים קצרים בלבד: התיאור של הקורס הוא פסקה ארוכה, ואנחנו
    # לא רוצים שמילה מתוכו תתחזה לערך של שדה.
    for limit in (160, None):
        for blob in blobs:
            if limit is not None and len(blob) > limit:
                continue
            for label, pattern in patterns:
                m = pattern.search(blob)
                if m is not None:
                    return _clean(_details_cut_at_next_label(m.group(1), label))
    return None


def _details_parse_hours(line: str) -> "tuple[dict[str, float], float | None] | None":
    """מפענח שורת שעות: ``'4 2 - -  5.0 נ"ז'`` -> ``({he:4,te:2,ma:0,pr:0}, 5.0)``.

    ``-`` ברכיב שעות פירושו "אין" — כלומר **0.0**, לא "לא ידוע": הידיעון
    מדפיס מקף כשלקורס אין מעבדה, ואפס הוא התשובה הנכונה. ``-`` במקום הנ"ז
    לעומת זאת כן מחזיר ``None``, כי אז באמת לא ידוע.

    הכתיבים שנמדדו על דפים אמיתיים — כולם חייבים להתפענח, אחרת נ"ז
    שמודפסת בדף בבירור מדווחת כ"לא ידועה" או, גרוע מכך, נספרת כשעות::

        '4 2 - -  5.0 נ"ז'  -> he4 te2 ma0 pr0, 5.0   (הכתיב המלא)
        '2 2 - 3 נ"ז'       -> he2 te2 ma0 pr0, 3.0   (שלושה רכיבים בלבד)
        '1 1 1-  2.0'       -> he1 te1 ma1 pr0, 2.0   (מקף שנדבק למספר)
        '1-1-1 2.0'         -> he1 te1 ma1 pr0, 2.0   (רכיבים מחוברים)
        '2 2 3.0'           -> he2 te2 ma0 pr0, 3.0   (שני רכיבים בלבד)
        '2 נ"ז , 1-0-2'     -> he1 te0 ma2 pr0, 2.0   (הנ"ז נדפסה ראשונה)

    Returns:
        ``(hours, credits)`` או ``None`` אם השורה אינה שורת שעות.
    """
    text = _DETAILS_HOURS_JUNK_RE.sub(" ", _DASH_RE.sub("-", _clean(line)))
    if not text.strip():
        return None

    # הסימן נ"ז הוא **המידע**, לא רעש: המספר שלידו הוא נ"ז ולא שעת פרויקט.
    # לכן מסמנים איפה הוא ישב, במקום לזרוק אותו לפני הפיצול לאסימונים.
    mark = _DETAILS_CREDIT_MARK_RE.search(text)
    head_text, tail_text = (
        (text, "") if mark is None else (text[:mark.start()], text[mark.end():])
    )

    head = _details_hour_groups(head_text)
    tail = _details_hour_groups(tail_text)
    if head is None or tail is None:
        return None
    before = [p for group in head for p in group]
    after = [p for group in tail for p in group]

    credit_token: "str | None" = None
    if mark is not None:
        # ``'2 2 - 3 נ"ז'`` -> הנ"ז לפני הסימן; ``'2 נ"ז , 1-0-2'`` -> אחריו.
        if before:
            credit_token, pieces = before[-1], before[:-1] + after
        elif after:
            credit_token, pieces = after[0], after[1:]
        else:
            return None
    else:
        pieces = before
        if not (2 <= len(pieces) <= len(DETAILS_HOUR_KEYS) + 1):
            return None
        glued = any(len(group) > 1 for group in head[:-1])
        if len(pieces) > len(DETAILS_HOUR_KEYS):
            credit_token, pieces = pieces[-1], pieces[:-1]
        elif (glued and len(head[-1]) == 1) or "." in pieces[-1]:
            # ``'1-1-1 2.0'`` / ``'2 1- 2.5'`` / ``'2 2 3.0'`` — הרכיבים נדבקו
            # זה לזה או שנדפסו פחות מארבעה, והמספר האחרון הוא נ"ז.
            credit_token, pieces = pieces[-1], pieces[:-1]

    if len(pieces) > len(DETAILS_HOUR_KEYS):
        return None  # יותר רכיבים ממה שהידיעון מדפיס — זו לא שורת שעות

    # רכיב שלא נדפס כלל הוא 0.0 בדיוק כמו מקף: הידיעון מפסיק לכתוב אחרי
    # הרכיב האחרון שיש בו שעות. שורה בלי אף רכיב שעות מחזירה {} — לא ידוע.
    hours = {
        key: (0.0 if i >= len(pieces) or pieces[i] == "-" else float(pieces[i]))
        for i, key in enumerate(DETAILS_HOUR_KEYS)
    } if pieces else {}
    credits = (
        None if credit_token is None or credit_token == "-" else float(credit_token)
    )
    return hours, credits


def _details_hours_index(lines: list[str]) -> "int | None":
    """מיקום שורת השעות בתוך בלוק פרשיית הלימוד, או ``None``."""
    for i, line in enumerate(lines):
        if _details_parse_hours(line) is not None:
            return i
    return None


def _details_dedupe_block(lines: list[str]) -> list[str]:
    """מנקה את בלוק פרשיית הלימוד — ובעיקר: **לא פולט את התיאור פעמיים**.

    הדף מדפיס את הבלוק כולו פעמיים (פעם ב-``<details>`` ופעם ב-``<p>``).
    כשמגיעים אליו דרך התא העוטף מקבלים רצף כפול מדויק; חוצים אותו.
    """
    out = [
        line for line in (_clean(x) for x in lines)
        if line and line != _DETAILS_SYLLABUS_LABEL
    ]
    half = len(out) // 2
    if half and len(out) % 2 == 0 and out[:half] == out[half:]:
        out = out[:half]
    deduped: list[str] = []
    for line in out:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return deduped


def _details_syllabus_lines(scope: Any) -> list[str]:
    """שורות בלוק "פרשיית לימוד": ``[קוד ושם, שורת שעות, תיאור…]``.

    סדר החיפוש: ה-``<details>`` הייעודי (המקור הנקי), אחר כך ``<p>``, ואחר
    כך כל תא שמכיל את הכותרת. מועמד "לא-מהימן" מתקבל רק אם שורתו הראשונה
    נראית כמו ``<קוד> <שם>`` — אחרת כל פסקה בדף הייתה יכולה להתחזות לבלוק.
    """
    if not hasattr(scope, "find_all"):
        return []

    candidates: list[tuple[Any, bool]] = []
    for det in scope.find_all("details"):
        summary = det.find("summary")
        label = _cell_text(summary) if summary is not None else ""
        if label and _DETAILS_SYLLABUS_LABEL not in label:
            continue
        body = next(
            (c for c in det.find_all(recursive=False)
             if getattr(c, "name", None) != "summary"),
            None,
        )
        candidates.append((body if body is not None else det, True))
    candidates.extend((p, False) for p in scope.find_all("p"))
    candidates.extend(
        (cell, False)
        for cell in scope.find_all("div")
        if _is_div_col(cell) and _DETAILS_SYLLABUS_LABEL in _cell_text(cell)
    )

    for want_hours in (True, False):
        for node, trusted in candidates:
            lines = _details_dedupe_block(_cell_lines(node))
            if not lines:
                continue
            if want_hours and _details_hours_index(lines) is None:
                continue
            if not trusted and not _DETAILS_CODE_LINE_RE.match(lines[0]):
                continue
            return lines
    return []


def _details_prereq_container(scope: Any) -> Any:
    """הטבלה שמתחת לכותרת "תנאי קדם לנושא", או ``None``.

    לא לבלבל עם הכרטיס "תנאי קשר לתרגיל(...)" שיושב באותו דף ומתאר קבוצות
    צמודות — הוא נראה כמו טבלה לכל דבר ואינו תנאי קדם.
    """
    if not hasattr(scope, "find_all"):
        return None

    for card in scope.find_all("div"):
        if "card" not in _classes(card):
            continue
        head = card.find(["h1", "h2", "h3", "h4", "h5"])
        if head is None or _DETAILS_PREREQ_LABEL not in _cell_text(head):
            continue
        inner = next(
            (d for d in card.find_all("div")
             if any(c in ("ncontainer", "Table") for c in _classes(d))),
            None,
        )
        return inner if inner is not None else card

    # גיבוי: מיכל שיש בו שורת כותרת עם "סוג הקשר" ו-"נושא נקשר".
    for row in scope.find_all("div"):
        if not _is_div_row(row):
            continue
        texts = [_cell_text(c) for c in _row_cols(row)]
        if any("סוג הקשר" in t for t in texts) and any("נושא נקשר" in t for t in texts):
            return row.parent
    return None


def _details_prereq_kind(relation: str) -> str:
    """"סוג הקשר" -> ``prereq`` / ``corequisite`` / ``exclusive`` / ``other``.

    הטקסט עצמו נשמר כמו שהוא ב-``relation``; זה רק המפתח שאפשר לסנן לפיו.
    """
    text = _clean(relation)
    if not text:
        return "other"
    for marker, kind in _DETAILS_PREREQ_KINDS:
        if text.startswith(marker):
            return kind
    for marker, kind in _DETAILS_PREREQ_KINDS:
        if marker in text:
            return kind
    return "other"


def _details_prereq_columns(texts: list[str]) -> dict[str, int]:
    """ממפה כותרות טבלת תנאי הקדם לשמות שדות. ``{}`` = זו אינה שורת כותרת.

    ההתאמה נעשית **לפי שדה ולא לפי תא**, מהניסוח הספציפי לכללי. ההבדל אינו
    תיאורטי: בכותרת המלאה ‏"תנאי קדם לנושא | סוג הקשר | אוכלוסייה | נושא נקשר |
    חליפי" מעבר תא-אחר-תא נותן ל-``name`` את התא הראשון (הוא מכיל "נושא"),
    ועמודת "נושא נקשר" — הקורס שהוא באמת התנאי — נזרקת. סריקה לפי שדה
    מבטיחה ש"נושא נקשר" גובר על "נושא" באיזה תא שלא יישבו.
    """
    # (דירוג הניסוח, סדר השדה, שדה, עמודה) — ככל שהניסוח ספציפי יותר,
    # כך הוא נמצא מוקדם יותר ב-_DETAILS_PREREQ_HEADERS ומנצח.
    candidates: list[tuple[int, int, str, int]] = []
    for order, (field, labels) in enumerate(_DETAILS_PREREQ_HEADERS):
        for i, text in enumerate(texts):
            if not text or any(s in text for s in _DETAILS_PREREQ_SUBJECT_LABELS):
                continue
            for rank, label in enumerate(labels):
                if label in text:
                    candidates.append((rank, order, field, i))
                    break

    mapping: dict[str, int] = {}
    taken: set[int] = set()
    for _rank, _order, field, column in sorted(candidates):
        if field in mapping or column in taken:
            continue
        mapping[field] = column
        taken.add(column)
    return mapping


def _details_prereq_row(cells: list[Any], col_map: dict[str, int]) -> "dict | None":
    """שורת טבלה אחת -> מילון תנאי קדם, או ``None`` אם השורה ריקה.

    שורה ריקה היא מצב **תקין**: בדף של קורס שאינו נפתח שורות הטבלה מכילות
    תגי-תבנית ‎<!$MG_…>‎ שנעלמים בפירסור. אין תנאי קדם, ואין אזהרה.

    המילון תמיד מכיל את ארבעת המפתחות של המפרט. שלושה מפתחות נוספים
    נשמרים כי בלעדיהם אי אפשר לאכוף תנאי קדם נכון בין-מחלקתי:
      * ``kind``             — ``relation`` מנורמל: ``prereq`` (תנאי קדם),
        ``corequisite`` (תנאי צמוד — נרשמים לשניהם יחד), ``exclusive``
        (תנאי אקסקלוסיבי — מי שלמד/ה את הקורס שמשמאל **אינו/ה** רשאי/ת
        להירשם) או ``other``. **חובה לסנן לפיו**: הטבלה מחזירה את שלושת
        הסוגים באותו מבנה, ומי שיתייחס לכולם כתנאי קדם ידרוש קורס שהדף
        אומר עליו את ההפך הגמור.
      * ``alternative_name`` — שם הקורס החליפי (``alternative`` הוא רק "יש/אין").
      * ``population``       — "מגמה : הנדסת תוכנה". תנאי קדם בידיעון מוגדר
        **לפי מגמה**, וסטודנט/ית ממחלקה אחרת אינו/ה כפוף/ה לו.
    """

    def cell(field: str) -> str:
        idx = col_map.get(field)
        if idx is None or idx >= len(cells) or cells[idx] is None:
            return ""
        return _cell_text(cells[idx])

    code = cell("code")
    name = cell("name")
    relation = cell("relation")
    alternative = cell("alternative")
    population = cell("population")

    if not any((code, name, relation, alternative, population)):
        return None

    if not code:
        m = _DETAILS_CODE_LINE_RE.match(name)
        if m is not None:
            code, name = m.group(1), _clean(m.group(2))

    if not (code or name):
        return None

    return {
        "code": code,
        "name": name,
        "relation": relation,
        "kind": _details_prereq_kind(relation),
        "alternative": bool(alternative),
        "alternative_name": alternative,
        "population": population,
    }


def _details_prerequisites(scope: Any, warnings: list[str]) -> list[dict]:
    """טבלת "תנאי קדם לנושא" -> רשימת מילונים. אין תנאי קדם = ``[]`` בלי אזהרה."""
    container = _details_prereq_container(scope)
    if container is None:
        return []

    rows = [
        r for r in container.find_all("div")
        if _is_div_row(r) and not any(_is_div_row(d) for d in r.find_all("div"))
    ]
    if _is_div_row(container) and not rows:
        rows = [container]

    # שורה ריקה לגמרי אינה נתון ואינה כותרת — הידיעון מדפיס שורת-מקום כזאת
    # בראש הטבלה. אסור לה לקבוע את מפת העמודות, אחרת הכותרת האמיתית שאחריה
    # תפוענח כשורת נתונים ותיפלט כתנאי קדם מדומה בשם "נושא נקשר".
    body: list[tuple[list, list[str]]] = []
    for row in rows:
        cells = _row_cols(row)
        if not cells:
            continue
        texts = [_cell_text(c) for c in cells]
        if not any(texts):
            continue
        body.append((cells, texts))
    if not body:
        return []

    # שורת הכותרת היא הראשונה **בכל הטבלה** שמזוהות בה שתי עמודות ומעלה,
    # ולא בהכרח השורה הראשונה.
    header_at: "int | None" = None
    col_map: dict[str, int] = {}
    for i, (_cells, texts) in enumerate(body):
        header = _details_prereq_columns(texts)
        if len(header) >= 2:
            header_at, col_map = i, header
            break

    if not col_map:
        widest = max(len(cells) for cells, _texts in body)
        col_map = {
            field: i
            for i, field in enumerate(_DETAILS_PREREQ_FALLBACK_ORDER)
            if i < widest
        }
        warnings.append(
            "בטבלת תנאי הקדם לא נמצאה שורת כותרת — העמודות מופו לפי הסדר "
            "המקובל בידיעון. (prerequisite table without a header row)"
        )

    out: list[dict] = []
    for i, (cells, _texts) in enumerate(body):
        if i == header_at:
            continue
        parsed = _details_prereq_row(cells, col_map)
        if parsed is not None:
            out.append(parsed)
    return out


def parse_course_details(html: str, code: str) -> CourseDetails:
    """מפענח דף ‎S_CourseDetails‎ אחד ומחזיר ``CourseDetails``.

    **הפונקציה הזאת לא זורקת.** דף חלקי, דף של קורס שאינו נפתח, ואפילו
    מחרוזת ריקה — כולם מחזירים ``CourseDetails`` עם ``None``/רשימות ריקות
    ואזהרה מתאימה. הסיבה פשוטה: הרענון היומי עובר על מאות קורסים, ודף אחד
    מוזר לא יכול להפיל את כולם.

    Args:
        html: ה-HTML הגולמי של הדף, כפי שנשמר ב-``data/raw/``.
        code: קוד הקורס שביקשנו. משמש גם לאימות מול הקוד שמודפס בדף.

    Returns:
        ``CourseDetails``. ``credits`` הוא ``None`` — ולא ``0.0`` — כשלא ידוע.
    """
    warnings: list[str] = []
    wanted = _clean(code)

    empty = CourseDetails(
        code=wanted, name="", credits=None, hours={}, weekly_hours=None,
        language="", description="", prerequisites=[], warnings=warnings,
    )

    if not str(html or "").strip():
        warnings.append("דף פרטי הקורס ריק — אין ממה לפענח. (empty details page)")
        return empty

    try:
        soup = _make_soup(str(html), warnings)
        scope = _details_scope(soup)
        blobs = _details_blobs(scope)
        lines = _details_syllabus_lines(scope)
    except Exception as exc:  # noqa: BLE001 - דף חריג אינו סיבה להפיל רענון
        warnings.append(
            f"פענוח דף הפרטים נכשל ({type(exc).__name__}: {exc}); "
            "לא נשלפו פרטים. (details page could not be parsed)"
        )
        return empty

    # ----- קוד, שם, שעות ותיאור מתוך בלוק "פרשיית לימוד" -----
    page_code = ""
    name = ""
    hours: dict[str, float] = {}
    line_credits: "float | None" = None
    description = ""

    hours_index = _details_hours_index(lines) if lines else None
    if hours_index is not None:
        parsed = _details_parse_hours(lines[hours_index])
        if parsed is not None:
            hours, line_credits = parsed
    else:
        warnings.append(
            "לא נמצאה שורת פירוק השעות (הרצאה/תרגיל/מעבדה/פרויקט) בדף. "
            "(no hours breakdown line)"
        )

    head_name = ""   # שם ודאי: השורה הראשונה באמת הייתה "<קוד> <שם>"
    if lines:
        head = lines[0]
        if hours_index != 0:
            m = _DETAILS_CODE_LINE_RE.match(head)
            if m is not None:
                page_code, head_name = m.group(1), _clean(m.group(2))
                name = head_name
            elif _details_looks_like_name(head):
                # מועמד **חלש**: זה יכול להיות גם המשפט הראשון של התיאור.
                # הכותרת המודגשת שבראש הדף גוברת עליו אם היא קיימת, והשורה
                # נשארת בתיאור (start=0) כדי שלא תיעלם ממנו.
                name = head
            # שורה שכולה מספרים ומקפים אינה שם בשום מצב — היא שורת שעות
            # בכתיב שלא זוהה. משאירים את השם ריק, ונותנים לכותרת לספק אותו.
        start = (hours_index + 1) if hours_index is not None else (1 if head_name else 0)
        description = _clean(" ".join(lines[start:]))

    # ----- שם: הכותרת המודגשת בראש הדף גוברת על מועמד חלש -----
    if not head_name:
        for blob in blobs:
            if len(blob) > 120:
                continue
            m = _DETAILS_CODE_LINE_RE.match(blob)
            if m is not None and (not wanted or m.group(1) == wanted):
                page_code, name = m.group(1), _clean(m.group(2))
                break
    if not name:
        warnings.append("לא נמצא שם קורס בדף. (course name not found)")

    if page_code and wanted and page_code != wanted:
        warnings.append(
            f"הדף מדבר על קורס {page_code} ולא על {wanted} — הפרטים עלולים "
            "להיות של קורס אחר. (course code mismatch)"
        )
    if not wanted and page_code:
        wanted = page_code

    if not description:
        warnings.append("לא נמצא תיאור קורס בדף. (course description not found)")

    # ----- נקודות זכות: "נקודות זכות" קודם, שורת השעות אחריו, ואז None -----
    raw_credits = _details_label_value(blobs, _DETAILS_CREDIT_LABELS)
    credits = _details_number(raw_credits) if raw_credits else None
    if credits is None:
        if line_credits is not None:
            credits = line_credits
            warnings.append(
                "שורת 'נקודות זכות' חסרה או ריקה — הנ\"ז נלקחו משורת פרשיית "
                "הלימוד. (credits taken from the study-line)"
            )
        else:
            warnings.append(
                "לא נמצאו נקודות זכות בדף — credits הוא None ולא 0.0, כדי "
                "שהסכום לא ישקר. (credits unknown)"
            )
    elif line_credits is not None and abs(credits - line_credits) > 0.01:
        warnings.append(
            f"אי-התאמה בנ\"ז: 'נקודות זכות' אומר {credits}, שורת פרשיית "
            f"הלימוד אומרת {line_credits}. נלקח הראשון. (credits disagree)"
        )

    # ----- שעות סמסטריאליות -----
    raw_weekly = _details_label_value(blobs, _DETAILS_WEEKLY_LABELS)
    weekly_hours = _details_number(raw_weekly) if raw_weekly else None
    if weekly_hours is None:
        warnings.append("לא נמצאו שעות סמסטריאליות בדף. (weekly hours not found)")

    # ----- שפת הוראה -----
    raw_language = _details_label_value(blobs, _DETAILS_LANGUAGE_LABELS)
    language = _clean(raw_language) if raw_language else ""
    if not language:
        warnings.append("לא נמצאה שפת הוראה בדף. (teaching language not found)")

    # ----- תנאי קדם -----
    try:
        prerequisites = _details_prerequisites(scope, warnings)
    except Exception as exc:  # noqa: BLE001
        prerequisites = []
        warnings.append(
            f"פענוח טבלת תנאי הקדם נכשל ({type(exc).__name__}: {exc}). "
            "(prerequisite table could not be parsed)"
        )

    return CourseDetails(
        code=wanted,
        name=name,
        credits=credits,
        hours=hours,
        weekly_hours=weekly_hours,
        language=language,
        description=description,
        prerequisites=prerequisites,
        warnings=warnings,
    )


# ==========================================================================
# 9. בדיקה עצמית — רצה כש-parser.py מופעל ישירות (python src/parser.py)
# ==========================================================================
#: דוגמת HTML קטנה שמכילה בכוונה את כל המלכודות: טבלת עיצוב מיותרת, rowspan,
#: טווח שעות הפוך, קבוצה עם שני מפגשים, מזהה קבוצה "11/12", הערת "צמודה",
#: ושורה פגומה שחייבת לייצר אזהרה.
_SAMPLE_HTML = """
<html><body>
<table><tr><td>טבלת עיצוב בלבד</td></tr></table>
<h1>61756 - שיטות הנדסיות לפיתוח מערכות תוכנה</h1>
<p>נקודות זכות: 5.0</p>
<table border="1">
  <tr><th>קבוצה</th><th>סוג</th><th>מרצה</th><th>יום</th><th>שעה</th>
      <th>בניין</th><th>חדר</th><th>הערות</th></tr>
  <tr><td rowspan="2">11/12</td><td rowspan="2">הרצאה</td><td rowspan="2">ד"ר כהן</td>
      <td>יום א'</td><td>08:30-10:00</td><td>1</td><td>201</td><td></td></tr>
  <tr><td>ג</td><td>10:00-12:00</td><td>1</td><td>201</td><td></td></tr>
  <tr><td>21</td><td>תרג'</td><td>מר לוי</td><td>רביעי</td><td>1400-1530</td>
      <td>2</td><td>310</td><td>צמודה לקבוצה 11</td></tr>
  <tr><td>22</td><td>מעב'</td><td>גב' מזרחי</td><td>5</td><td>16:00-14:00</td>
      <td>2</td><td>311</td><td></td></tr>
  <tr><td>23</td><td>פרוייקט</td><td></td><td>שבת</td><td>???</td>
      <td></td><td></td><td></td></tr>
</table>
</body></html>
"""


#: דוגמה שנייה — נתיב הטבלאות *עם* עמודת סמסטר. כאן נבדקות שלוש נקודות:
#:   1. אותה קבוצה נפגשת באותו יום ובאותה שעה בשני הסמסטרים — שני מפגשים
#:      נפרדים, ולא מפגש אחד שנבלע בדה-דופליקציה.
#:   2. "&nbsp;א" ו-"סמסטר ב'" מנורמלים שניהם נכון.
#:   3. תא סמסטר ריק = "לא ידוע" — המפגש נשמר גם כשמסננים.
_SAMPLE_SEMESTER_HTML = """
<html><body>
<h1>99999 - קורס בדיקה דו-סמסטריאלי</h1>
<table border="1">
  <tr><th>סמסטר</th><th>קבוצה</th><th>סוג</th><th>מרצה</th><th>יום</th>
      <th>שעה</th><th>חדר</th></tr>
  <tr><td>&nbsp;א</td><td>11</td><td>הרצאה</td><td>ד"ר כהן</td><td>יום א'</td>
      <td>08:30-10:00</td><td>201</td></tr>
  <tr><td>&nbsp;ב</td><td>11</td><td>הרצאה</td><td>ד"ר כהן</td><td>יום א'</td>
      <td>08:30-10:00</td><td>201</td></tr>
  <tr><td>סמסטר ב'</td><td>21</td><td>תרגול</td><td>מר לוי</td><td>ג</td>
      <td>12:00-14:00</td><td>310</td></tr>
  <tr><td></td><td>31</td><td>מעבדה</td><td>גב' מזרחי</td><td>ד</td>
      <td>16:00-18:00</td><td>311</td></tr>
</table>
</body></html>
"""

#: חמשת דפי הידיעון האמיתיים (GROUND_TRUTH סעיף 7). הם מגיעים מהמכללה
#: האקדמית ת"א-יפו ולא מבראודה — אותו מוצר בדיוק, אך ייתכנו הבדלי ניסוח.
_FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests", "fixtures", "real_yedion",
)

#: השנה שמודפסת בכל חמשת ה-fixtures.
_FIXTURE_YEAR = 'תשפ"ז'


def _read_fixture(name: str) -> str | None:
    """קורא fixture בקידוד utf-8; ``None`` אם הקובץ לא קיים."""
    path = os.path.join(_FIXTURE_DIR, name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def details_self_check(verbose: bool = True) -> list[str]:
    """בדיקה עצמית של ``parse_course_details`` מול שני דפי הידיעון האמיתיים.

    מדפיסה מה נמצא בכל דף — כי הדרך היחידה לדעת שפרסר עובד היא לראות את
    מה שהוא הוציא, לא להאמין שהוא רץ בלי לזרוק.

    Args:
        verbose: להדפיס את הממצאים.

    Returns:
        רשימת בעיות (ריקה = הכול תקין).
    """
    problems: list[str] = []

    def check(label: str, got: Any, want: Any) -> None:
        if got != want:
            problems.append(f"{label}: קיבלנו {got!r}, ציפינו ל-{want!r}")
        elif verbose:
            print(f"  ok  {label} -> {got!r}")

    def show(details: CourseDetails) -> None:
        if not verbose:
            return
        credits = "—" if details.credits is None else f"{details.credits:g}"
        weekly = "—" if details.weekly_hours is None else f"{details.weekly_hours:g}"
        hours = (
            ", ".join(f"{k}={v:g}" for k, v in details.hours.items())
            if details.hours else "— (לא נמצאה שורת שעות)"
        )
        print(f"  קורס {details.code} — {details.name or '(ללא שם)'}")
        print(f"    נ\"ז: {credits}   שעות סמסטריאליות: {weekly}")
        print(f"    פירוק שעות: {hours}")
        print(f"    שפת הוראה: {details.language or '—'}")
        print(f"    תיאור: {len(details.description)} תווים — {details.description[:70]}…")
        print(f"    תנאי קדם: {len(details.prerequisites)} שורות")
        for row in details.prerequisites[:3]:
            alt = f" (חליפי: {row['alternative_name']})" if row["alternative"] else ""
            print(f"      · {row['code'] or '—'} {row['name']}{alt} [{row['population']}]")
        if details.prerequisites[3:]:
            print(f"      · … ועוד {len(details.prerequisites) - 3}")
        for warning in details.warnings:
            print(f"    אזהרה: {warning}")

    # ----- דף אמיתי מלא: 61753 אלגוריתמים -----
    if verbose:
        print("== parse_course_details: course_details_61753.html ==")
    html = _read_fixture("course_details_61753.html")
    if html is None:
        if verbose:
            print("  דילוג: course_details_61753.html לא נמצא")
    else:
        got = parse_course_details(html, "61753")
        show(got)
        check("61753 code", got.code, "61753")
        check("61753 name", got.name, "אלגוריתמים")
        check("61753 credits", got.credits, 5.0)
        check("61753 hours he", got.hours.get("he"), 4.0)
        check("61753 hours te", got.hours.get("te"), 2.0)
        check("61753 hours ma (מקף -> 0.0)", got.hours.get("ma"), 0.0)
        check("61753 hours pr (מקף -> 0.0)", got.hours.get("pr"), 0.0)
        check("61753 weekly_hours", got.weekly_hours, 4.0)
        check("61753 language", got.language, "עברית")
        check("61753 יש תיאור", bool(got.description), True)
        check("61753 התיאור לא מוכפל", got.description.count("מטרת הקורס היא"), 1)
        check("61753 יש תנאי קדם", len(got.prerequisites) > 0, True)
        check("61753 בלי אזהרות", got.warnings, [])
        if got.prerequisites:
            first = got.prerequisites[0]
            for key in DETAILS_PREREQ_KEYS:
                if key not in first:
                    problems.append(f"61753 תנאי קדם: חסר המפתח {key!r}")
            check("61753 תנאי קדם ראשון — שם", bool(first["name"]), True)
            check("61753 תנאי קדם ראשון — סוג קשר", bool(first["relation"]), True)
        if any(row["alternative"] for row in got.prerequisites):
            if verbose:
                print("  ok  זוהתה לפחות שורת תנאי-קדם אחת עם קורס חליפי")
        else:
            problems.append("61753: לא זוהתה אף שורת תנאי קדם עם חליפי")

    # ----- דף חלקי אמיתי: 11001, קורס שאינו נפתח (תוויות בלי ערכים) -----
    if verbose:
        print("== parse_course_details: course_details_11001.html (דף חלקי) ==")
    html = _read_fixture("course_details_11001.html")
    if html is None:
        if verbose:
            print("  דילוג: course_details_11001.html לא נמצא")
    else:
        got = parse_course_details(html, "11001")
        show(got)
        check("11001 code", got.code, "11001")
        check("11001 name", got.name, "אלגברה")
        # "נקודות זכות :" ריק בדף הזה — הערך נלקח משורת פרשיית הלימוד.
        check("11001 credits (משורת פרשיית הלימוד)", got.credits, 4.0)
        check("11001 hours he", got.hours.get("he"), 3.0)
        check("11001 hours te", got.hours.get("te"), 2.0)
        check("11001 weekly_hours לא ידוע -> None", got.weekly_hours, None)
        check("11001 שפת הוראה חסרה -> ''", got.language, "")
        check("11001 שדה חסר מייצר אזהרה", len(got.warnings) > 0, True)
        check("11001 בלי תנאי קדם -> רשימה ריקה", got.prerequisites, [])

    # ----- דף ריק / פגום: אסור לזרוק, ואסור להחזיר 0.0 -----
    if verbose:
        print("== parse_course_details: דפים פגומים ==")
    for label, bad in (
        ("ריק", ""),
        ("None", None),
        ("לא HTML", "שלום עולם"),
        ("HTML בלי פרטים", "<html><body><p>אין כאן כלום</p></body></html>"),
    ):
        try:
            got = parse_course_details(bad, "99999")  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            problems.append(f"דף {label}: parse_course_details זרק {type(exc).__name__}: {exc}")
            continue
        check(f"דף {label}: credits הוא None ולא 0.0", got.credits, None)
        check(f"דף {label}: hours ריק", got.hours, {})
        check(f"דף {label}: prerequisites ריק", got.prerequisites, [])
        check(f"דף {label}: יש אזהרה", len(got.warnings) > 0, True)

    return problems


def self_check(verbose: bool = True) -> list[str]:
    """בדיקה עצמית של המודול. מחזירה רשימת בעיות (רשימה ריקה = הכול תקין).

    כוללת את בדיקת ה-round-trip המדויק שנדרשה במפרט: שמירה -> טעינה -> שמירה
    חוזרת חייבת לייצר קובץ זהה בייט-בייט.

    Args:
        verbose: להדפיס פירוט לקונסולה.

    Returns:
        רשימת מחרוזות המתארות כשלים.
    """
    problems: list[str] = []

    def check(label: str, got: Any, want: Any) -> None:
        if got != want:
            problems.append(f"{label}: קיבלנו {got!r}, ציפינו ל-{want!r}")
        elif verbose:
            print(f"  ok  {label} -> {got!r}")

    if verbose:
        print("== parse_time_range ==")
    check("'08:30-10:00'", parse_time_range("08:30-10:00"), (510, 600))
    check("'8:30 - 10:00'", parse_time_range("8:30 - 10:00"), (510, 600))
    check("en dash", parse_time_range("08:30 – 10:00"), (510, 600))
    check("'08:30 to 10:00'", parse_time_range("08:30 to 10:00"), (510, 600))
    check("'08:30 עד 10:00'", parse_time_range("08:30 עד 10:00"), (510, 600))
    check("'0830-1000'", parse_time_range("0830-1000"), (510, 600))
    check("'08.30-10.00'", parse_time_range("08.30-10.00"), (510, 600))
    check("reversed RTL", parse_time_range("10:00-08:30"), (510, 600))
    check("garbage", parse_time_range("???"), None)
    check("single time", parse_time_range("08:30"), None)

    if verbose:
        print("== parse_day ==")
    check("'א'", parse_day("א"), 1)
    check("\"א'\"", parse_day("א'"), 1)
    check("'יום ב'", parse_day("יום ב"), 2)
    check("'ראשון'", parse_day("ראשון"), 1)
    check("'רביעי' (longest-first)", parse_day("רביעי"), 4)
    check("'שישי'", parse_day("שישי"), 6)
    check("'5'", parse_day("5"), 5)
    check("'שבת'", parse_day("שבת"), None)

    if verbose:
        print("== classify_kind ==")
    check("'הרצאה'", classify_kind("הרצאה"), KIND_LECTURE)
    check("'שיעור'", classify_kind("שיעור"), KIND_LECTURE)
    check("\"תרג'\"", classify_kind("תרג'"), KIND_TUTORIAL)
    check("\"מעב'\"", classify_kind("מעב'"), KIND_LAB)
    check("'פרוייקט'", classify_kind("פרוייקט"), KIND_PROJECT)
    check("'סיור'", classify_kind("סיור"), KIND_OTHER)

    if verbose:
        print("== parse_course_page ==")
    result = parse_course_page(_SAMPLE_HTML, "61756", fallback_name="גיבוי")
    if result.course is None:
        problems.append("parse_course_page: לא הוחזר קורס מה-HTML לדוגמה")
    else:
        course = result.course
        check("שם הקורס", course.name, "שיטות הנדסיות לפיתוח מערכות תוכנה")
        check("נקודות זכות", course.credits, 5.0)
        check("מספר קבוצות", len(course.groups), 3)
        lecture = course.groups_of(KIND_LECTURE)
        if not lecture:
            problems.append("parse_course_page: לא נמצאה קבוצת הרצאה")
        else:
            check("מיזוג שני מפגשים לקבוצה אחת", len(lecture[0].meetings), 2)
            check("מזהה קבוצה מתוך '11/12'", lecture[0].group_id, "11")
            check("linked_to מתוך '11/12'", lecture[0].linked_to, ["12"])
        lab = course.groups_of(KIND_LAB)
        if not lab:
            problems.append("parse_course_page: לא נמצאה קבוצת מעבדה")
        else:
            check(
                "טווח הפוך תוקן",
                (lab[0].meetings[0].start, lab[0].meetings[0].end),
                (840, 960),
            )
        tut = course.groups_of(KIND_TUTORIAL)
        if not tut:
            problems.append("parse_course_page: לא נמצאה קבוצת תרגול")
        else:
            check("linked_to מתוך ההערה", tut[0].linked_to, ["11"])
        if not any("דולגה" in w for w in result.warnings):
            problems.append("parse_course_page: השורה הפגומה לא ייצרה אזהרה")
        elif verbose:
            print(f"  ok  {len(result.warnings)} אזהרות נרשמו (כולל שורה שדולגה)")

    if verbose:
        print("== normalize_semester ==")
    check("'&nbsp;ב'", normalize_semester("&nbsp;ב"), "ב")
    check("U+00A0 + ב", normalize_semester("\u00a0ב"), "ב")
    check("\"סמסטר א'\"", normalize_semester("סמסטר א'"), "א")
    check("'קיץ'", normalize_semester("קיץ"), "קיץ")
    check("'סמסטר קיץ'", normalize_semester("סמסטר קיץ"), "קיץ")
    check("''", normalize_semester(""), "")
    check("רווחים בלבד", normalize_semester("   "), "")
    check("קוד מספרי '2'", normalize_semester("2"), "ב")
    check("אידמפוטנטיות", normalize_semester(normalize_semester("סמסטר ב'")), "ב")
    check("ערך לא מוכר נשמר", normalize_semester("שנתי"), "שנתי")

    if verbose:
        print("== סמסטר בנתיב הטבלאות (legacy table path) ==")
    dual = parse_course_page(_SAMPLE_SEMESTER_HTML, "99999")
    if dual.course is None:
        problems.append("נתיב הטבלאות: לא הוחזר קורס מה-HTML הדו-סמסטריאלי")
    else:
        lec = dual.course.groups_of(KIND_LECTURE)
        if not lec:
            problems.append("נתיב הטבלאות: לא נמצאה קבוצת הרצאה")
        else:
            check("שני סמסטרים באותה שעה = שני מפגשים", len(lec[0].meetings), 2)
            check(
                "הסמסטרים שנקראו מהעמודה",
                sorted(m.semester for m in lec[0].meetings),
                ["א", "ב"],
            )
        empty_cell = [
            m for g in dual.course.groups for m in g.meetings if g.group_id == "31"
        ]
        check("תא סמסטר ריק -> ''", [m.semester for m in empty_cell], [""])

    filtered = parse_course_page(_SAMPLE_SEMESTER_HTML, "99999", semester="א")
    if filtered.course is None:
        problems.append("סינון סמסטר א' בנתיב הטבלאות: הקורס נעלם לגמרי")
    else:
        ids = sorted(g.group_id for g in filtered.course.groups)
        # ‏11 שורדת עם מפגש אחד, 21 (סמסטר ב') נזרקת, 31 ("לא ידוע") נשמרת.
        check("סינון א': הקבוצות ששרדו", ids, ["11", "31"])
        lec = filtered.course.groups_of(KIND_LECTURE)
        if lec:
            check("סינון א': נשאר מפגש אחד", [m.semester for m in lec[0].meetings], ["א"])
    if not any("לא ניתן לקבוע את הסמסטר" in w for w in filtered.warnings):
        problems.append("סינון סמסטר: מפגש עם סמסטר לא ידוע נשמר בלי אזהרה")
    if not any("אינה מוצעת בסמסטר" in w and "21" in w for w in filtered.warnings):
        problems.append("סינון סמסטר: קבוצה 21 הוסרה בלי אזהרה שמזכירה את מספרה")

    if verbose:
        print("== extract_page_year ==")
    check("שנה מכותרת קורס", extract_page_year(
        '<h2 class="TextAlignCenter"> קורס מתמטיקה ב\' שנה"ל תשפ"ז</h2>'), 'תשפ"ז')
    check("שנה מכותרת דף החיפוש", extract_page_year(
        '<h2> חיפוש קורסים במערכת תשפ"ו </h2>'), 'תשפ"ו')
    check("אין שנה בדף", extract_page_year("<html><body>שלום</body></html>"), None)
    check("HTML ריק", extract_page_year(""), None)

    if verbose:
        print("== חמשת דפי הידיעון האמיתיים ==")
    if not os.path.isdir(_FIXTURE_DIR):
        if verbose:
            print(f"  דילוג: תיקיית ה-fixtures לא נמצאה ({_FIXTURE_DIR})")
    else:
        # (filename, course_code, expected_group_count)
        fixture_specs = [
            ("single_group.html", "93263", 1),
            ("three_groups.html", "651112", 3),
            ("four_groups.html", "211164", 4),
            ("multi_group_lecture_tutorial.html", "271030", 5),
        ]
        for filename, fcode, want_groups in fixture_specs:
            raw = _read_fixture(filename)
            if raw is None:
                problems.append(f"fixture חסר: {filename}")
                continue
            check(f"{filename}: שנת הדף", extract_page_year(raw), _FIXTURE_YEAR)
            res = parse_course_page(raw, fcode)
            if res.course is None:
                problems.append(f"{filename}: לא הוחזר קורס")
                continue
            check(f"{filename}: מספר קבוצות", len(res.course.groups), want_groups)
            sems = sorted({m.semester for g in res.course.groups for m in g.meetings})
            # כל חמשת ה-fixtures הם קורסים של סמסטר ב'.
            check(f"{filename}: הסמסטרים בעמודה", sems, ["ב"])
            bad = [w for w in res.warnings if "credits not found" not in w]
            if bad:
                problems.append(f"{filename}: אזהרות בלתי צפויות: {bad}")

        # ----- הדף החשוב ביותר: 271030 מתמטיקה ב' -----
        raw = _read_fixture("multi_group_lecture_tutorial.html")
        if raw is not None:
            res = parse_course_page(raw, "271030")
            course = res.course
            if course is None:
                problems.append("multi_group_lecture_tutorial: לא הוחזר קורס")
            else:
                check("271030: שם הקורס", course.name, "מתמטיקה ב'")
                check("271030: הרצאות", len(course.groups_of(KIND_LECTURE)), 2)
                check("271030: תרגולים", len(course.groups_of(KIND_TUTORIAL)), 3)
                linked = {g.group_id: g.linked_to for g in course.groups if g.linked_to}
                check(
                    "271030: קבוצות קשורות",
                    linked,
                    {"27103001": ["27103002"], "27103004": ["27103005", "27103006"]},
                )

            # סמסטר א' -> הקורס אינו נפתח. זו תשובה תקינה, לא שגיאה.
            res_a = parse_course_page(raw, "271030", semester="א")
            check("271030 סמסטר א': אין קורס", res_a.course, None)
            if not any("אינו נפתח בסמסטר" in w for w in res_a.warnings):
                problems.append("271030 סמסטר א': חסרה אזהרת 'אינו נפתח בסמסטר'")
            elif verbose:
                print("  ok  271030 סמסטר א' -> אזהרת 'אינו נפתח בסמסטר' נרשמה")

            # סמסטר ב' -> כל חמש הקבוצות שורדות, עם המפגשים שלהן.
            res_b = parse_course_page(raw, "271030", semester="ב")
            if res_b.course is None:
                problems.append("271030 סמסטר ב': הקורס נעלם")
            else:
                check("271030 סמסטר ב': מספר קבוצות", len(res_b.course.groups), 5)
                check(
                    "271030 סמסטר ב': מספר מפגשים",
                    sum(len(g.meetings) for g in res_b.course.groups),
                    5,
                )
                check(
                    "271030 סמסטר ב': קבוצות קשורות נשמרו",
                    res_b.course.groups[0].linked_to,
                    ["27103002"],
                )

        # דף החיפוש עצמו: אין בו קבוצות, אבל כן שנה — וזה בדיוק מה שהסורק
        # צריך כדי לוודא שהחלפת השנה הצליחה לפני שמתחילים.
        raw = _read_fixture("enter_search_page.html")
        if raw is None:
            problems.append("fixture חסר: enter_search_page.html")
        else:
            check("enter_search_page: שנת הדף", extract_page_year(raw), _FIXTURE_YEAR)
            check(
                "enter_search_page: אין קבוצות",
                parse_course_page(raw, "00000").course,
                None,
            )

    if verbose:
        print("== round-trip של sections.json ==")
    demo = {
        "61756": Course(
            code="61756",
            name="שיטות הנדסיות לפיתוח מערכות תוכנה",
            credits=5.0,
            groups=[
                Group(
                    course_code="61756",
                    group_id="11",
                    kind=KIND_LECTURE,
                    lecturer='ד"ר כהן',
                    meetings=[
                        Meeting(1, 510, 600, "201", "1", "א"),
                        Meeting(3, 600, 720, "201", "1", "א"),
                    ],
                    linked_to=["12"],
                    note="קבוצה צמודה",
                )
            ],
            tied_with=["61757", "62027"],
        )
    }
    tmpdir = tempfile.mkdtemp(prefix="sections_roundtrip_")
    first = os.path.join(tmpdir, "a.json")
    second = os.path.join(tmpdir, "b.json")
    try:
        save_sections(demo, first)
        loaded = load_sections(first)
        save_sections(loaded, second)
        with open(first, "rb") as fh:
            blob_a = fh.read()
        with open(second, "rb") as fh:
            blob_b = fh.read()
        if blob_a != blob_b:
            problems.append("round-trip: הקובץ אחרי טעינה ושמירה חוזרת אינו זהה")
        elif verbose:
            print("  ok  שמירה -> טעינה -> שמירה מייצרת קובץ זהה בייט-בייט")
        if loaded != demo:
            problems.append("round-trip: האובייקטים שנטענו אינם שווים למקוריים")
        elif verbose:
            print("  ok  האובייקטים שנטענו זהים למקוריים")
    finally:
        for p in (first, second):
            if os.path.exists(p):
                os.remove(p)
        if os.path.isdir(tmpdir):
            os.rmdir(tmpdir)

    # ----- round-trip של ה-fixture הישן, שנכתב לפני שדה הסמסטר -----
    # דרישה מפורשת: קובץ JSON ישן שאין בו המפתח "semester" חייב להיטען,
    # וכל מפגש בו יקבל "" (לא ידוע) — בלי להתפוצץ ובלי לאבד מפגשים.
    legacy = os.path.join(os.path.dirname(_FIXTURE_DIR), "sample_sections.json")
    if not os.path.exists(legacy):
        if verbose:
            print(f"  דילוג: {legacy} לא נמצא")
    else:
        loaded = load_sections(legacy)
        sems = {m.semester for c in loaded.values() for g in c.groups for m in g.meetings}
        check("sample_sections.json: קובץ ישן -> סמסטר ריק", sems, {""})
        tmpdir2 = tempfile.mkdtemp(prefix="sections_legacy_")
        out = os.path.join(tmpdir2, "c.json")
        try:
            save_sections(loaded, out)
            again = load_sections(out)
            if again != loaded:
                problems.append(
                    "round-trip: tests/fixtures/sample_sections.json לא שרד "
                    "שמירה+טעינה חוזרת"
                )
            elif verbose:
                print("  ok  sample_sections.json שרד round-trip מלא")
        finally:
            if os.path.exists(out):
                os.remove(out)
            if os.path.isdir(tmpdir2):
                os.rmdir(tmpdir2)

    # ----- פרטי קורס מדף S_CourseDetails (שני ה-fixtures האמיתיים) -----
    problems.extend(details_self_check(verbose=verbose))

    return problems


if __name__ == "__main__":
    # הדפסת עברית ב-Windows דורשת utf-8 מפורש; עטוף ב-try כי לא כל זרם פלט
    # ניתן להגדרה מחדש.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    issues = self_check(verbose=True)
    print()
    if issues:
        print(f"נמצאו {len(issues)} בעיות (self-check FAILED):")
        for issue in issues:
            print("  - " + issue)
        raise SystemExit(1)
    print("כל הבדיקות עברו (self-check OK).")
    raise SystemExit(0)
