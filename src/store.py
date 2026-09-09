# -*- coding: utf-8 -*-
"""
מסד הנתונים של SlotWise — the JSON store behind the auto-refresh.

מה המודול הזה עושה
-------------------
זהו שכבת האחסון של הכלי: כל מה שהסקריפט היומי מוריד מהידיעון נכתב לכאן, וכל
מה שהתפריט והמנוע קוראים מגיע מכאן. הוא לא נוגע ברשת, לא ב-HTML ולא ב-Playwright —
רק בקבצי JSON. אפשר להריץ אותו ולבדוק אותו לגמרי אופליין.

מבנה התיקייה (``data/db/`` כברירת מחדל)::

    data/db/
      catalog.json         כל הקורסים שנפתחו השנה:  code -> {name, status}
      sections.json        פירוט הקבוצות לכל קורס במעקב + מטא-דאטה לכל קורס
      details.json         פרטי הקורסים מהידיעון: נ"ז, שעות, שפת הוראה, תנאי קדם
      tracked.json         קבוצת קודי הקורסים שאנחנו דואגים לרענן
      refresh_log.jsonl    שורת JSON אחת לכל ריצת רענון (append-only)
      changes.jsonl        שורת JSON אחת לכל שינוי שזוהה (append-only)
      snapshots/           YYYY-MM-DD-HHMM.json — עותק של sections.json לפני דריסה

ארבעת העקרונות שהמודול הזה בנוי סביבם
--------------------------------------
1. **זיהוי שינויים הוא כל הסיפור.** ‏:meth:`Store.save_course` לא רק שומר — הוא
   מחזיר רשימת תיאורים בעברית של מה בדיוק השתנה מול הגרסה הקודמת: קבוצה שנוספה,
   קבוצה שבוטלה, מרצה שהתחלף, שעה או יום שזזו, חדר שהשתנה. סטודנט שנרשם לקורס
   וביום שאחרי המרצה התחלף — זה בדיוק המידע שהוא צריך לקבל, ובקול רם.
2. **כישלון לא הורס נתונים טובים.** אם רענון של קורס נכשל, הרשומה הקודמת נשארת
   במקומה במלואה. רק המטא מתעדכן: ``ok=False`` ו-``last_attempt_at`` חדש —
   ואילו ``fetched_at`` (חותמת ההצלחה האחרונה) לעולם לא נדרסת בכישלון, כדי
   שחישוב "מתי הנתונים באמת עודכנו" יישאר כן.
3. **כל כתיבה אטומית.** כותבים לקובץ ``.tmp`` באותה תיקייה ואז ``os.replace``.
   משימה מתוזמנת שנהרגת באמצע כתיבה לא תשאיר מסד נתונים פגום.
4. **קובץ פגום לא מפיל את הכלי.** JSON שנקטע נרשם כאזהרה, נשמר בצד בשם
   ``<name>.corrupt-<timestamp>`` (לא נמחק!), והמסד ממשיך כאילו היה ריק.

Technical notes
---------------
* Every file is opened with ``encoding="utf-8"`` — on Windows the default would
  be cp1255 and every Hebrew name would be mangled.
* All timestamps are ``datetime.now(timezone.utc)``, serialised as ISO-8601 with
  a trailing ``Z``. Never a naive datetime: a schedule built from "yesterday's"
  data because of a timezone slip is a silent, invisible bug.
* This module deliberately depends only on the standard library and on
  ``models.py``. It does **not** import ``parser`` or ``scraper``, so the
  database layer stays importable (and testable) without BeautifulSoup or
  Playwright installed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import re
import sys
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

import strings as strings_mod

# ייבוא המודל. הפרויקט מוסיף את src/ ל-sys.path (ראו main.py), ולכן הצורה
# הרגילה היא "from models import ...". ה-fallback קיים רק כדי ש-
# "from src import store" יעבוד גם הוא.
try:  # pragma: no cover - trivial import shim
    from models import (
        DAY_LETTERS_HE,
        KIND_OTHER,
        Course,
        Group,
        Meeting,
        fmt_time,
    )
except ImportError:  # pragma: no cover
    from src.models import (  # type: ignore[no-redef]
        DAY_LETTERS_HE,
        KIND_OTHER,
        Course,
        Group,
        Meeting,
        fmt_time,
    )

__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_MAX_AGE_HOURS",
    "DEFAULT_DETAILS_MAX_AGE_HOURS",
    "MAX_SNAPSHOTS",
    "CourseMeta",
    "Store",
    "StoreError",
    "utc_now_iso",
    "parse_iso_utc",
    "content_sha1",
    "age_hours_since",
    "format_hebrew_age",
    "diff_courses",
]

LOG = logging.getLogger("store")

# ==========================================================================
# 0. קבועים
# ==========================================================================
#: גרסת הסכימה של קבצי המסד. עולה רק כשמבנה הקובץ משתנה בצורה לא-תואמת.
SCHEMA_VERSION = 1

#: בני כמה שעות הנתונים עדיין נחשבים טריים. הרענון רץ פעם ביום.
DEFAULT_MAX_AGE_HOURS = 24.0

#: בני כמה שעות *פרטי הקורס* (נ"ז, שעות, שפת הוראה, תנאי קדם) עדיין נחשבים
#: טריים. שבוע שלם — ובכוונה, בניגוד ל-24 השעות של מערכת השעות: קבוצה, מרצה
#: או חדר זזים באמצע סמסטר; מספר נקודות הזכות של קורס כמעט אף פעם לא. חלון של
#: 24 שעות כאן היה מכפיל את מספר הפניות של הרענון היומי לידיעון בשביל נתון
#: שלא זז — וזו בדיוק חוסר-הנימוס שהכלי הזה נמנע ממנה.
DEFAULT_DETAILS_MAX_AGE_HOURS = 24.0 * 7

#: כמה גיבויים של sections.json שומרים בתיקיית snapshots/.
#: ‏30 = בערך חודש של ריצה יומית. מעבר לזה הישנים ביותר נמחקים, כדי שהתיקייה
#: לא תתפח בלי גבול על המחשב של הסטודנט.
MAX_SNAPSHOTS = 30

#: שמות הקבצים בתוך תיקיית המסד.
#: הקטלוג שנשלח עם הקוד. ייבוא עצל ורך: מסד שרץ בלעדיו חייב להמשיך
#: לעבוד, כי ``store.py`` נטען גם מ-refresh.py ומ-reparse.py.
try:  # pragma: no cover - נתיב הייבוא נבדק בבדיקות ייעודיות
    import shipped_catalog as _shipped
except Exception:  # noqa: BLE001
    _shipped = None  # type: ignore[assignment]

#: ‏אותה הפרדה שהפרסר עושה בזמן פענוח, מוחלת גם בזמן **קריאה**. מסד שנכתב
#: לפני 2026-09-10 נושא ערכים כמו "מר כהן אסף הקורס מלא", ופענוח מחדש אינו
#: מנקה את כולם: קורס שאין לו מועד קבוע בסמסטר הנבחר אינו נפתח ב-``reparse``
#: בכלל, ולכן השורה הישנה שלו נשארת. ייבוא רך מאותה סיבה כמו הקטלוג —
#: ‏``store`` נטען גם בהקשרים שאין בהם ‏BeautifulSoup.
try:  # pragma: no cover
    from parser import _split_lecturer_status as _split_status  # type: ignore
except Exception:  # noqa: BLE001
    _split_status = None  # type: ignore[assignment]

#: ‏בזמן קריאה אין ‏HTML, ולכן אין ``span`` אדום להסתמך עליו — וזו הרשימה
#: שמחליפה אותו, **לנתונים ישנים בלבד.** הפרסר עצמו נשאר מונחה-DOM; כאן
#: מדובר בערכים שכבר נכתבו לדיסק לפני 2026-09-10, ובראשם ‏134 שורות
#: ב-``data/catalog.jsonl`` שנשלח עם הקוד. בלי זה, שיבוט טרי — שקורא את
#: הקטלוג ולא מסד מקומי — היה ממשיך לראות "מר כהן אסף הקורס מלא".
#: ההסרה היא של **סיומת מדויקת** בלבד, ורק אם נשאר שם אחריה, ולכן היא
#: אינה יכולה לקצר שם אמיתי. שני הניסוחים האלה הם כל מה שנמצא בפועל
#: ב-572 הדפים השמורים.
_LEGACY_STATUS_SUFFIXES: tuple[str, ...] = (
    "בקורס זה קיימת רשימת המתנה",
    "הקורס מלא",
)

CATALOG_FILE = "catalog.json"
SECTIONS_FILE = "sections.json"
DETAILS_FILE = "details.json"
TRACKED_FILE = "tracked.json"
REFRESH_LOG_FILE = "refresh_log.jsonl"
CHANGES_LOG_FILE = "changes.jsonl"
SNAPSHOTS_DIR = "snapshots"

#: מזהי סכימה שנכתבים לתוך הקבצים, כדי שקובץ זר יזוהה מיד.
CATALOG_SCHEMA = "braude-schedule-builder/catalog"
SECTIONS_SCHEMA = "braude-schedule-builder/sections-db"
DETAILS_SCHEMA = "braude-schedule-builder/course-details"
TRACKED_SCHEMA = "braude-schedule-builder/tracked"

#: פורמט חותמת הזמן. ISO-8601 ב-UTC עם Z בסוף — "2026-08-30T14:03:11Z".
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


class StoreError(Exception):
    """תקלה שאי אפשר להתאושש ממנה בשכבת האחסון (למשל: אין הרשאת כתיבה).

    שימו לב: *קריאה* של קובץ פגום **לא** מרימה את החריגה הזאת. קובץ פגום מטופל
    בשקט-אבל-בקול: אזהרה ללוג, הקובץ נשמר בצד, והמסד מתנהג כאילו הוא ריק.
    """


# ==========================================================================
# 1. זמן — תמיד UTC, תמיד מודע לאזור זמן
# ==========================================================================
def utc_now_iso(now: datetime | None = None) -> str:
    """מחזיר חותמת זמן ISO-8601 ב-UTC, למשל ``"2026-08-30T14:03:11Z"``.

    Args:
        now: זמן להמרה. ``None`` = עכשיו.

    Note:
        משתמשים ב-``datetime.now(timezone.utc)`` ולא ב-``utcnow()``: השני מחזיר
        datetime *נאיבי* (בלי אזור זמן), וחיסור בין נאיבי למודע מתפוצץ — או
        גרוע מכך, מצליח עם הפרש שגוי של כמה שעות.
    """
    dt = now if now is not None else datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime(_ISO_FMT)


def parse_iso_utc(text: Any) -> datetime | None:
    """מפרש חותמת זמן ומחזיר datetime מודע ב-UTC, או ``None`` אם אי אפשר.

    סלחני בכוונה: מקבל ``Z`` בסוף, היסט מפורש (``+03:00``), חותמת בלי אזור זמן
    (מפורשת כ-UTC), ותאריך בלבד. כל דבר אחר -> ``None``, ומי שקורא מתייחס לזה
    כאל "לא ידוע" = מיושן. עדיף לרענן מיותר מאשר להציג נתון ישן כטרי.
    """
    if not isinstance(text, str):
        return None
    t = text.strip()
    if not t:
        return None
    # ‏fromisoformat של פייתון 3.11+ מכיר "Z", אבל ההמרה הידנית זולה ומגינה
    # גם על קבצים שנכתבו בגרסאות ישנות יותר.
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    dt: datetime | None = None
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(t, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:  # חותמת בלי אזור זמן — מפרשים כ-UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def age_hours_since(stamp: Any, now: datetime | None = None) -> float | None:
    """גיל בשעות של חותמת זמן. ``None`` כשהחותמת חסרה או לא ניתנת לפירוש."""
    dt = parse_iso_utc(stamp)
    if dt is None:
        return None
    ref = now if now is not None else datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return (ref.astimezone(timezone.utc) - dt).total_seconds() / 3600.0


def format_hebrew_age(hours: float | None) -> str:
    """מנסח גיל בשעות כטקסט עברי ניטרלי: ``"לפני 3 שעות"``.

    משמש את התצוגה ("הנתונים עודכנו לאחרונה: ... (לפני 3 שעות)"). הניסוח
    ניטרלי מגדרית לחלוטין — אין כאן פנייה לאף אחד.
    """
    age = strings_mod.get("server.age", {})
    if hours is None:
        return age.get("unknown", "")
    if hours < 0:  # חותמת עתידית — שעון שהוזז, או קובץ שנערך ביד
        return age.get("future", "")
    minutes = int(round(hours * 60))
    if minutes < 1:
        return age.get("now", "")
    if minutes < 60:
        if minutes == 1:
            return age.get("minute", "")
        if minutes == 2:
            return age.get("twoMinutes", "")
        return strings_mod.fmt("server.age.minutes", n=minutes)
    whole_hours = int(hours)
    if whole_hours < 24:
        if whole_hours == 1:
            return age.get("hour", "")
        if whole_hours == 2:
            return age.get("twoHours", "")
        return strings_mod.fmt("server.age.hours", n=whole_hours)
    days = int(hours // 24)
    if days == 1:
        return age.get("day", "")
    if days == 2:
        return age.get("twoDays", "")
    return strings_mod.fmt("server.age.days", n=days)


def content_sha1(text: str | bytes) -> str:
    """‏sha1 של ה-HTML הגולמי — מפתח זיהוי השינויים.

    למה sha1 ולא משהו חזק יותר: זו לא הגנה קריפטוגרפית אלא "שער זול" שאומר
    "הדף לא זז מאז אתמול, אין טעם להשוות מבנית". התנגשות אקראית כאן היא
    תאורטית, וממילא יש בדיקה מבנית שנייה (ראו :func:`_structure_fingerprint`).
    """
    data = text if isinstance(text, bytes) else str(text).encode("utf-8", "replace")
    return hashlib.sha1(data).hexdigest()


# ==========================================================================
# 2. ניקוי טקסט להשוואה — נבצ"ר, גרשיים עבריים, מרכאות מסולסלות
# ==========================================================================
#: תווים בלתי-נראים שמסתננים לדפי HTML בעברית ומשגעים כל השוואת מחרוזות.
_INVISIBLE = "".join(
    chr(c)
    for c in (0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C,
              0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069, 0xFEFF)
)

#: טבלת המרה אחת לכל הווריאנטים. U+00A0 (‏nbsp) -> רווח רגיל, גרש/גרשיים
#: עבריים (U+05F3/U+05F4) ומרכאות מסולסלות -> ASCII, תווים בלתי-נראים -> נמחקים.
#: בלי זה, "מתמטיקה ב׳" ו-"מתמטיקה ב'" הם שתי מחרוזות שונות והחיפוש נכשל.
_NORM_MAP: dict[int, Any] = {
    0x00A0: " ",   # no-break space
    0x2007: " ",   # figure space
    0x202F: " ",   # narrow no-break space
    0x05F3: "'",   # גרש עברי
    0x05F4: '"',   # גרשיים עבריים
    0x2018: "'", 0x2019: "'", 0x201A: "'", 0x2032: "'",
    0x201C: '"', 0x201D: '"', 0x201E: '"', 0x2033: '"',
}
for _ch in _INVISIBLE:
    _NORM_MAP[ord(_ch)] = None

_WS_RE = re.compile(r"\s+")


def _norm(text: Any) -> str:
    """מנרמל טקסט להשוואה: מרכאות אחידות, בלי תווים נסתרים, רווחים מכווצים.

    זו לא פונקציית תצוגה — התוצאה משמשת רק להשוואה ולחיפוש. את הטקסט המקורי
    תמיד מציגים כמו שהוא.
    """
    if text is None:
        return ""
    t = str(text).translate(_NORM_MAP)
    return _WS_RE.sub(" ", t).strip()


def _norm_search(text: Any) -> str:
    """כמו :func:`_norm`, אבל גם מוריד רישיות — לחיפוש בקוד/שם."""
    return _norm(text).casefold()


def _code_sort_key(code: Any) -> tuple[int, str]:
    """מיון קודי קורס: מספריים לפי ערך (61753 < 621112), השאר בסוף לפי אלפבית."""
    c = str(code)
    return (int(c), c) if c.isdigit() else (10**9, c)


# ==========================================================================
# 3. CourseMeta — המטא-דאטה של קורס אחד במסד
# ==========================================================================
@dataclass
class CourseMeta:
    """מטא-דאטה של רשומת קורס אחת: מתי נשלפה, מאיזו שנה, והאם הצליחה.

    Attributes:
        fetched_at: חותמת ההצלחה האחרונה, ISO-8601 UTC. **לא נדרסת בכישלון.**
        year: שנת הלימודים העברית, למשל ``'תשפ"ז'``.
        year_gregorian: השנה הלועזית כפי שמופיעה ב-``<option value>``, ``"2027"``.
        semester: הסמסטר שלפיו סוננו המפגשים — ``"א"`` / ``"ב"`` / ``"קיץ"`` /
            ``""`` כשלא סוננו כלל.
        source_url: הכתובת שממנה נשלף הדף.
        content_sha1: ‏sha1 של ה-HTML הגולמי — מפתח זיהוי השינויים.
        group_count: כמה קבוצות נמצאו בדף.
        warnings: אזהרות הפרסור של אותה שליפה.
        ok: ‏``False`` כשהשליפה או הפרסור נכשלו. אז הנתונים עלולים להיות ישנים,
            והרשומה נחשבת מיושנת (ראו :meth:`Store.is_stale`).
        last_attempt_at: חותמת הניסיון האחרון — **גם כשהוא נכשל**. זהו השדה
            שמאפשר להבחין בין "ניסינו והצלחנו" ל"ניסינו ונכשלנו", בלי לשקר
            על גיל הנתונים.
        last_error: תיאור קצר של הכישלון האחרון (ריק כשהכול תקין).

    Note:
        סדר השדות הראשונים זהה לחוזה שב-SPEC_AUTOREFRESH.md, כדי שבנייה
        פוזיציונית תמשיך לעבוד. שני השדות האחרונים נוספו עם ערכי ברירת מחדל,
        ולכן הם תוספת תואמת לאחור.
    """

    fetched_at: str = ""
    year: str = ""
    year_gregorian: str = ""
    semester: str = ""
    source_url: str = ""
    content_sha1: str = ""
    group_count: int = 0
    warnings: list[str] = field(default_factory=list)
    ok: bool = True
    # --- תוספות שנדרשות כדי שכישלון לא ישקר על גיל הנתונים ---
    last_attempt_at: str = ""
    last_error: str = ""

    # ------------------------------------------------------------------
    def age_hours(self, now: datetime | None = None) -> float | None:
        """גיל הנתונים בשעות, לפי ``fetched_at``. ``None`` = לא ידוע."""
        return age_hours_since(self.fetched_at, now)

    def is_stale(
        self, max_age_hours: float = DEFAULT_MAX_AGE_HOURS, now: datetime | None = None
    ) -> bool:
        """האם הרשומה מיושנת: כשלון קודם, חותמת לא קריאה, או גיל מעל הסף."""
        if not self.ok:
            return True
        age = self.age_hours(now)
        if age is None:
            return True
        return age > max_age_hours

    def freshness_text(self, now: datetime | None = None) -> str:
        """שורת טריות לתצוגה: ``"2026-08-30 07:00 (לפני 3 שעות)"``."""
        dt = parse_iso_utc(self.fetched_at)
        if dt is None:
            return "לא ידוע מתי"
        local = dt.astimezone()  # לתצוגה בלבד — האחסון תמיד UTC
        return f"{local.strftime('%Y-%m-%d %H:%M')} ({format_hebrew_age(self.age_hours(now))})"

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "CourseMeta":
        """בונה ``CourseMeta`` ממילון, בסלחנות: שדות לא מוכרים נזרקים,
        שדות חסרים מקבלים ברירת מחדל."""
        if not isinstance(data, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        kw = {k: v for k, v in data.items() if k in known}
        return cls(
            fetched_at=str(kw.get("fetched_at", "") or ""),
            year=str(kw.get("year", "") or ""),
            year_gregorian=str(kw.get("year_gregorian", "") or ""),
            semester=str(kw.get("semester", "") or ""),
            source_url=str(kw.get("source_url", "") or ""),
            content_sha1=str(kw.get("content_sha1", "") or ""),
            group_count=_safe_int(kw.get("group_count", 0)),
            warnings=[str(w) for w in (kw.get("warnings") or [])],
            ok=bool(kw.get("ok", True)),
            last_attempt_at=str(kw.get("last_attempt_at", "") or ""),
            last_error=str(kw.get("last_error", "") or ""),
        )


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _jsonable(value: Any) -> Any:
    """מחזיר עותק של הערך שאפשר לכתוב ל-JSON, בלי להתפוצץ על טיפוס לא צפוי.

    למה זה נחוץ: ``save_details`` מקבל מילון שמגיע מהפרסור של דף הידיעון, ואם
    נכנס לתוכו טיפוס שהמודול הזה לא מכיר (למשל ``Decimal``, או קבוצה) —
    ``json.dumps`` היה מרים ``TypeError`` באמצע הרענון היומי ומפיל אותו. כאן
    כל דבר לא מוכר הופך למחרוזת, וגרוע מכך לא קורה.

    ``NaN``/``Infinity`` הופכים ל-``None``: פייתון היה כותב אותם בשקט, אבל הם
    אינם JSON חוקי וכל קורא אחר היה נופל עליהם. "לא ידוע" עדיף על קובץ שבור.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    return str(value)


def _as_details_dict(details: Any) -> dict[str, Any] | None:
    """מנרמל את הקלט של :meth:`Store.save_details` למילון, או ``None``.

    סלחני בכוונה, בדיוק כמו שאר המודול: מקבל מילון, ‏NamedTuple (למשל
    ``CourseDetails`` של הפרסר, שיש לו ``_asdict``) או dataclass. כל דבר אחר —
    ובכלל זה ``None`` ומילון ריק — מוחזר כ-``None``, כלומר "לא התקבלו פרטים",
    וזה מה שמפעיל את מסלול הכישלון ששומר על הרשומה הקודמת.
    """
    if details is None:
        return None
    if is_dataclass(details) and not isinstance(details, type):
        details = asdict(details)
    elif hasattr(details, "_asdict"):
        try:
            details = details._asdict()
        except Exception:  # pragma: no cover - NamedTuple חריג
            return None
    if not isinstance(details, dict) or not details:
        return None
    clean = _jsonable(details)
    return clean if isinstance(clean, dict) and clean else None


# ==========================================================================
# 4. סריאליזציה של Course/Group/Meeting
# ==========================================================================
# השמות נשלפים מהדאטהקלאסים עצמם — בדיוק כמו ב-parser.save_sections — כדי
# שהעיגול הלוך-ושוב יישאר מדויק גם אם models.py יקבל שדה נוסף בעתיד.
_MEETING_FIELDS = {f.name for f in fields(Meeting)}
_GROUP_FIELDS = {f.name for f in fields(Group)}
_COURSE_FIELDS = {f.name for f in fields(Course)}


def _meeting_from_dict(data: Any) -> Meeting:
    if not isinstance(data, dict):
        return Meeting(day=0, start=0, end=0)
    kw = {k: v for k, v in data.items() if k in _MEETING_FIELDS}
    return Meeting(
        day=_safe_int(kw.get("day", 0)),
        start=_safe_int(kw.get("start", 0)),
        end=_safe_int(kw.get("end", 0)),
        room=str(kw.get("room", "") or ""),
        building=str(kw.get("building", "") or ""),
        semester=str(kw.get("semester", "") or ""),
    )


def _group_from_dict(data: Any, course_code: str) -> Group:
    if not isinstance(data, dict):
        return Group(course_code=course_code, group_id="", kind=KIND_OTHER, lecturer="", meetings=[])
    kw = {k: v for k, v in data.items() if k in _GROUP_FIELDS}
    _lecturer = str(kw.get("lecturer", "") or "")
    _status = str(kw.get("status_note", "") or "")
    if _split_status is not None:
        # ‏אותה הפרדה, עם רשימת ניסוחים במקום ה-``span``-ים — ראו
        # ``_LEGACY_STATUS_SUFFIXES``. זה מה שמנקה גם את הקטלוג שנשלח
        # עם הקוד, בלי לבנות אותו מחדש.
        _lecturer, _found = _split_status(_lecturer, list(_LEGACY_STATUS_SUFFIXES))
        _status = _status or _found
    return Group(
        course_code=str(kw.get("course_code") or course_code),
        group_id=str(kw.get("group_id", "") or ""),
        kind=str(kw.get("kind") or KIND_OTHER),
        lecturer=_lecturer,
        meetings=[_meeting_from_dict(m) for m in (kw.get("meetings") or [])],
        linked_to=[str(x) for x in (kw.get("linked_to") or [])],
        note=str(kw.get("note", "") or ""),
        status_note=_status,
        # ‏semester **חייב** לעבור. כל עוד sections.json נכתב מסונן לסמסטר
        # אחד, אפשר היה לוותר עליו בלי שאיש ירגיש; מרגע שהקטלוג נושא את
        # כל הסמסטרים, קבוצה בלי תג סמסטר אינה ניתנת לסינון בזמן קריאה —
        # וקבוצות סמסטר ב', שאין להן מפגשים כלל, נכנסו למרחב החיפוש.
        semester=str(kw.get("semester", "") or ""),
    )


def _course_from_dict(data: Any, code_hint: str = "") -> Course | None:
    if not isinstance(data, dict):
        return None
    kw = {k: v for k, v in data.items() if k in _COURSE_FIELDS}
    code = str(kw.get("code") or code_hint)
    if not code:
        return None
    return Course(
        code=code,
        name=str(kw.get("name", "") or ""),
        credits=_safe_float(kw.get("credits", 0.0)),
        groups=[_group_from_dict(g, code) for g in (kw.get("groups") or [])],
        tied_with=[str(x) for x in (kw.get("tied_with") or [])],
    )


# ==========================================================================
# 5. זיהוי שינויים — הלב של המודול
# ==========================================================================
def _fmt_meeting_time(m: Meeting) -> str:
    """מפגש כטקסט זמן בלבד: ``"יום ב 10:15-12:00"`` (בלי חדר)."""
    return f"יום {DAY_LETTERS_HE.get(m.day, '?')} {fmt_time(m.start)}-{fmt_time(m.end)}"


def _fmt_place(m: Meeting) -> str:
    """מיקום המפגש לתצוגה: ``"בניין 3 חדר 210"``, או ``"לא צוין"`` כשריק."""
    where = " ".join(p for p in (str(m.building).strip(), str(m.room).strip()) if p)
    return where or "לא צוין"


def _fmt_lecturer(name: str) -> str:
    return str(name).strip() or "לא צוין"


def _meeting_time_key(m: Meeting) -> tuple[int, int, int]:
    """מפתח הזהות של מפגש לצורך השוואה: יום + שעת התחלה + שעת סיום."""
    return (int(m.day), int(m.start), int(m.end))


def _group_key(g: Group) -> tuple[str, str]:
    """מפתח הזהות של קבוצה: (מזהה קבוצה, סוג רכיב).

    למה גם הסוג: בידיעון אותו מספר קבוצה יכול להופיע פעם כהרצאה ופעם כתרגול,
    ואלה שתי יחידות רישום נפרדות לחלוטין.
    """
    return (str(g.group_id), str(g.kind))


def _structure_fingerprint(course: Course | None) -> str:
    """טביעת אצבע קומפקטית של *תוכן* הקורס (לא של ה-HTML).

    משמשת כבדיקה שנייה מאחורי שער ה-sha1: אם מישהו קרא ל-save_course עם מטא
    ממוחזר (אותו content_sha1) אבל עם קורס אחר, השער הזול לבדו היה מחמיץ את
    השינוי בשקט. כאן זה נתפס.
    """
    if course is None:
        return ""
    parts: list[str] = [_norm(course.name)]
    for g in sorted(course.groups, key=lambda x: (_group_key(x))):
        meetings = "|".join(
            f"{m.day},{m.start},{m.end},{_norm(m.room)},{_norm(m.building)},{_norm(m.semester)}"
            for m in sorted(g.meetings, key=_meeting_time_key)
        )
        parts.append(
            f"{g.group_id}~{g.kind}~{_norm(g.lecturer)}~"
            f"{','.join(sorted(str(x) for x in g.linked_to))}~{meetings}"
        )
    return content_sha1("\n".join(parts))


def _diff_meetings(code: str, gid: str, old: list[Meeting], new: list[Meeting]) -> list[str]:
    """משווה את מפגשי קבוצה אחת ומחזיר תיאורי שינוי בעברית.

    האלגוריתם, בשלושה שלבים:
      1. מפגשים עם *אותו* (יום, התחלה, סיום) מזוהים זה עם זה — ומה שנשווה בהם
         זה החדר, הבניין והסמסטר.
      2. מה שנשאר מכל צד מזווג לפי הסדר: זוג כזה הוא "השעה השתנתה"
         (וזה מכסה גם מעבר יום, כי היום והשעה נעים יחד).
      3. שארית לא מזווגת = מפגש שנוסף או מפגש שבוטל.
    """
    changes: list[str] = []

    old_by_key: dict[tuple[int, int, int], list[Meeting]] = {}
    new_by_key: dict[tuple[int, int, int], list[Meeting]] = {}
    for m in old:
        old_by_key.setdefault(_meeting_time_key(m), []).append(m)
    for m in new:
        new_by_key.setdefault(_meeting_time_key(m), []).append(m)

    # --- שלב 1: אותו זמן בדיוק -> בודקים חדר וסמסטר ---
    for key in sorted(set(old_by_key) & set(new_by_key)):
        pairs = zip(old_by_key[key], new_by_key[key])
        for om, nm in pairs:
            when = _fmt_meeting_time(nm)
            if _norm(om.room) != _norm(nm.room) or _norm(om.building) != _norm(nm.building):
                changes.append(
                    f"{code}: קבוצה {gid} — החדר השתנה ({when}): "
                    f"{_fmt_place(om)} -> {_fmt_place(nm)}"
                )
            if _norm(om.semester) != _norm(nm.semester):
                changes.append(
                    f"{code}: קבוצה {gid} — הסמסטר של המפגש השתנה ({when}): "
                    f"{om.semester or 'לא צוין'} -> {nm.semester or 'לא צוין'}"
                )

    # --- שלב 2+3: מה שלא הזדווג לפי זמן ---
    leftover_old: list[Meeting] = []
    leftover_new: list[Meeting] = []
    for key in sorted(set(old_by_key) | set(new_by_key)):
        o = old_by_key.get(key, [])
        n = new_by_key.get(key, [])
        matched = min(len(o), len(n))
        leftover_old.extend(o[matched:])
        leftover_new.extend(n[matched:])

    paired = min(len(leftover_old), len(leftover_new))
    for om, nm in zip(leftover_old[:paired], leftover_new[:paired]):
        changes.append(
            f"{code}: קבוצה {gid} — השעה השתנתה: "
            f"{_fmt_meeting_time(om)} -> {_fmt_meeting_time(nm)}"
        )
    for nm in leftover_new[paired:]:
        changes.append(f"{code}: קבוצה {gid} — נוסף מפגש: {_fmt_meeting_time(nm)}")
    for om in leftover_old[paired:]:
        changes.append(f"{code}: קבוצה {gid} — בוטל מפגש: {_fmt_meeting_time(om)}")

    return changes


def diff_courses(previous: Course | None, current: Course | None, code: str = "") -> list[str]:
    """משווה שתי גרסאות של אותו קורס ומחזיר תיאורי שינוי בעברית.

    הפורמט זהה לדוגמאות שב-SPEC_AUTOREFRESH.md::

        61753: נוספה קבוצה 22 (הרצאה, ד"ר רווה אלנה)
        61753: קבוצה 21 — המרצה השתנה: פרופ' וולקוביץ' זאב -> ד"ר גולני מתתיהו
        61753: קבוצה 24 — השעה השתנתה: יום ב 10:15-12:00 -> יום ג 12:00-13:45
        61753: בוטלה קבוצה 27 (תרגול)

    הסדר קבוע ודטרמיניסטי: קודם מה שנוסף, אחר כך מה שהשתנה, ולבסוף מה שבוטל.

    Args:
        previous: הגרסה השמורה. ``None`` = כתיבה ראשונה.
        current: הגרסה החדשה.
        code: קוד הקורס לקידומת ההודעה. ריק = נלקח מהקורס עצמו.

    Returns:
        רשימת מחרוזות. ריקה כשאין שינוי, כשזו כתיבה ראשונה, או כששליפה נכשלה.
    """
    if previous is None or current is None:
        # כתיבה ראשונה, או כישלון שבו אין גרסה חדשה להשוות אליה.
        return []
    code = str(code or current.code or previous.code)
    changes: list[str] = []

    # שם הקורס — נדיר שמשתנה, אבל כשזה קורה זה בדרך כלל אומר שקוד הקורס
    # מוחזר בידיעון עם שם אחר, וכדאי לדעת.
    if _norm(previous.name) and _norm(current.name) and _norm(previous.name) != _norm(current.name):
        changes.append(f"{code}: שם הקורס השתנה: {previous.name} -> {current.name}")

    old_map: dict[tuple[str, str], Group] = {}
    for g in previous.groups:
        old_map.setdefault(_group_key(g), g)   # כפילויות (לא אמורות לקרות) — הראשונה קובעת
    new_map: dict[tuple[str, str], Group] = {}
    for g in current.groups:
        new_map.setdefault(_group_key(g), g)

    added = sorted(set(new_map) - set(old_map), key=lambda k: (_code_sort_key(k[0]), k[1]))
    removed = sorted(set(old_map) - set(new_map), key=lambda k: (_code_sort_key(k[0]), k[1]))
    common = sorted(set(old_map) & set(new_map), key=lambda k: (_code_sort_key(k[0]), k[1]))

    # --- (1) קבוצות שנוספו ---
    for key in added:
        g = new_map[key]
        gid, kind = key
        who = _norm(g.lecturer)
        detail = f"{kind}, {g.lecturer.strip()}" if who else kind
        changes.append(f"{code}: נוספה קבוצה {gid} ({detail})")

    # --- (2) קבוצות שהשתנו ---
    for key in common:
        og, ng = old_map[key], new_map[key]
        gid = key[0]
        if _norm(og.lecturer) != _norm(ng.lecturer):
            changes.append(
                f"{code}: קבוצה {gid} — המרצה השתנה: "
                f"{_fmt_lecturer(og.lecturer)} -> {_fmt_lecturer(ng.lecturer)}"
            )
        changes.extend(_diff_meetings(code, gid, list(og.meetings), list(ng.meetings)))
        # קבוצות צמודות (הרצאה שקושרה לתרגול אחר) — משנה איזה שילובים חוקיים.
        old_linked = sorted(_norm(x) for x in og.linked_to)
        new_linked = sorted(_norm(x) for x in ng.linked_to)
        if old_linked != new_linked:
            changes.append(
                f"{code}: קבוצה {gid} — הקבוצות הצמודות השתנו: "
                f"{', '.join(og.linked_to) or 'אין'} -> {', '.join(ng.linked_to) or 'אין'}"
            )

    # --- (3) קבוצות שבוטלו ---
    for key in removed:
        gid, kind = key
        changes.append(f"{code}: בוטלה קבוצה {gid} ({kind})")

    return changes


# ==========================================================================
# 6. Store — מסד הנתונים עצמו
# ==========================================================================
class Store:
    """מסד נתוני ה-JSON שמאחורי הרענון היומי.

    כל המתודות בטוחות לקריאה גם כשהתיקייה עדיין לא קיימת: קריאה ממסד ריק
    מחזירה ערכים ריקים, לא חריגה. תיקיות נוצרות רק כשבאמת כותבים.

    Example:
        >>> store = Store("data/db")            # doctest: +SKIP
        >>> store.track(["61753"])              # doctest: +SKIP
        >>> changes = store.save_course(course, meta)   # doctest: +SKIP
        >>> for line in changes:                # doctest: +SKIP
        ...     print(line)
    """

    def __init__(
        self,
        root: str = "data/db",
        *,
        use_shipped: bool = False,
        semester: str = "",
    ) -> None:
        """
        Args:
            root: תיקיית המסד.
            use_shipped: האם לצרף מתחת למסד את הקטלוג שנשלח עם הקוד.
                **כבוי כברירת מחדל, ובכוונה.** ``Store(path)`` מתאר את מה
                שיש ב-``path`` ותו לא; מסד ריק חייב להיות ריק. הצירוף הוא
                החלטה של שכבת התצוגה — האפליקציה מדליקה אותו כדי שמשתמש/ת
                יראו קטלוג מלא, ואילו ``refresh.py`` ו-``reparse.py``
                משאירים אותו כבוי, אחרת זיהוי השינויים היה מוצא 572
                "קורסים קיימים" שמעולם לא נכתבו למסד הזה.
            semester: לאיזה סמסטר לסנן את הקטלוג שנשלח. ריק = בלי סינון.
                הקטלוג נושא את כל הסמסטרים, ולכן הבחירה היא של הקורא.
        """
        self.use_shipped = bool(use_shipped)
        self.shipped_semester = str(semester or "")
        self.root = os.path.abspath(str(root))
        self.catalog_path = os.path.join(self.root, CATALOG_FILE)
        self.sections_path = os.path.join(self.root, SECTIONS_FILE)
        self.details_path = os.path.join(self.root, DETAILS_FILE)
        self.tracked_path = os.path.join(self.root, TRACKED_FILE)
        self.refresh_log_path = os.path.join(self.root, REFRESH_LOG_FILE)
        self.changes_log_path = os.path.join(self.root, CHANGES_LOG_FILE)
        self.snapshots_dir = os.path.join(self.root, SNAPSHOTS_DIR)
        #: אזהרות שהצטברו בטעינה (קובץ פגום וכו'). התצוגה יכולה להראות אותן.
        self.warnings: list[str] = []
        # מטמון קטן לפי (mtime_ns, size) — כדי שחיפוש חוזר בקטלוג של 1172
        # קורסים לא יפרסר מחדש חצי מגה-בייט של JSON בכל הקשה.
        self._cache: dict[str, tuple[tuple[int, int], Any]] = {}

    def __repr__(self) -> str:  # pragma: no cover - נוחות דיבוג
        return f"Store({self.root!r})"

    # ------------------------------------------------------------------
    # 6.1 יסודות: כתיבה אטומית, קריאה סלחנית
    # ------------------------------------------------------------------
    def _ensure_root(self) -> None:
        """יוצר את תיקיית המסד. נקרא רק לפני כתיבה — קריאה לא יוצרת כלום."""
        try:
            os.makedirs(self.root, exist_ok=True)
        except OSError as exc:  # pragma: no cover - תלוי מערכת קבצים
            raise StoreError(f"לא ניתן ליצור את תיקיית המסד {self.root}: {exc}") from exc

    @staticmethod
    def _atomic_write_text(path: str, text: str) -> None:
        """כתיבה אטומית: קובץ ``.tmp`` באותה תיקייה ואז ``os.replace``.

        למה זה קריטי דווקא כאן: הרענון רץ כמשימה מתוזמנת ברקע. אם המחשב נכבה
        או שהמשימה נהרגת באמצע ``json.dump``, כתיבה רגילה הייתה משאירה קובץ
        חתוך — כלומר מסד נתונים הרוס. ``os.replace`` הוא אטומי גם ב-Windows
        (‏MoveFileEx עם REPLACE_EXISTING), ולכן הקורא רואה או את הגרסה הישנה
        במלואה, או את החדשה במלואה. אף פעם לא חצי.

        ה-pid בשם הקובץ הזמני מונע התנגשות בין שתי ריצות במקביל.
        """
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())   # לוודא שהתוכן באמת על הדיסק לפני ההחלפה
            os.replace(tmp, path)
        except OSError as exc:
            # ניקוי הזמני, כדי לא להשאיר לכלוך אחרי כישלון.
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:  # pragma: no cover
                pass
            raise StoreError(f"כתיבה ל-{path} נכשלה: {exc}") from exc

    def _write_json(self, path: str, payload: Any) -> None:
        """כותב JSON בעברית קריאה, ממוין, עם שורה חדשה בסוף — אטומית."""
        self._ensure_root()
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
        self._atomic_write_text(path, text)
        self._cache.pop(path, None)   # המטמון התיישן

    def _quarantine(self, path: str, reason: str) -> None:
        """שומר קובץ פגום בצד בשם ``<name>.corrupt-<timestamp>``.

        לא מוחקים כלום: אולי אפשר לשחזר ממנו ביד, ובכל מקרה נתון של הסטודנט
        לא נמחק בגלל באג שלנו.
        """
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = f"{path}.corrupt-{stamp}"
        msg = f"קובץ פגום: {os.path.basename(path)} ({reason}). נשמר בצד: {os.path.basename(dest)}"
        LOG.warning(msg)
        self.warnings.append(msg)
        try:
            os.replace(path, dest)
        except OSError as exc:  # pragma: no cover - קובץ נעול וכו'
            LOG.warning("לא ניתן היה להעביר את הקובץ הפגום %s: %s", path, exc)

    def _read_json(self, path: str, default: Any) -> Any:
        """קורא JSON בסלחנות. קובץ חסר -> ``default``. קובץ פגום -> אזהרה,
        הקובץ נשמר בצד, ומוחזר ``default``.

        המטרה המפורשת: קובץ אחד שנפגם לא יפיל את כל הכלי. הסטודנט צריך לראות
        מערכת שעות, לא stack trace.
        """
        if not os.path.exists(path):
            return default
        try:
            stat = os.stat(path)
            key = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            key = (0, 0)
        cached = self._cache.get(path)
        if cached is not None and cached[0] == key:
            return cached[1]
        try:
            # utf-8-sig ולא utf-8: קובץ שנערך ב-Notepad או נכתב ב-PowerShell 5.1
            # מקבל BOM, ו-json.load היה נופל עליו עם "Unexpected UTF-8 BOM".
            with open(path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._quarantine(path, f"JSON לא תקין — {exc}")
            return default
        except OSError as exc:
            msg = f"לא ניתן לקרוא את {os.path.basename(path)}: {exc}"
            LOG.warning(msg)
            self.warnings.append(msg)
            return default
        self._cache[path] = (key, data)
        return data

    def _append_jsonl(self, path: str, obj: dict) -> None:
        """מוסיף שורת JSON אחת לקובץ append-only.

        כתיבה אחת ב-mode="a" של שורה קצרה היא בפועל אטומית ברמת מערכת הקבצים,
        ולכן אין כאן tmp+replace: זה גם היה הורס את התכונה החשובה של הקובץ —
        שהוא רק גדל ולעולם לא נכתב מחדש.
        """
        self._ensure_root()
        line = json.dumps(obj, ensure_ascii=False, sort_keys=True)
        try:
            with open(path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
        except OSError as exc:
            msg = f"כתיבה ליומן {os.path.basename(path)} נכשלה: {exc}"
            LOG.warning(msg)
            self.warnings.append(msg)

    @staticmethod
    def _now(now: datetime | None = None) -> datetime:
        dt = now if now is not None else datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _as_code_list(codes: Any) -> list[str]:
        """מקבל מחרוזת בודדת או אוסף, ומחזיר רשימת קודים נקייה."""
        if codes is None:
            return []
        if isinstance(codes, str):
            codes = [codes]
        out: list[str] = []
        for c in codes:
            c = str(c).strip()
            if c:
                out.append(c)
        return out

    # ------------------------------------------------------------------
    # 6.2 קטלוג — כל מה שנפתח השנה
    # ------------------------------------------------------------------
    def save_catalog(self, courses: dict[str, dict], year: str, year_gregorian: str) -> None:
        """שומר את קטלוג כל הקורסים שנפתחו בשנה הנתונה.

        הקטלוג הוא מקור האמת ל*מה מוצע*. הוא בכוונה **לא** מסונן לפי
        curriculum.json: קורס שנלקח מסמסטר קודם, או קורס מחוץ לתוכנית, חייב
        להופיע כאן ולהיות בר-בחירה. זו דרישה מפורשת של הסטודנט.

        Args:
            courses: ``{code: {"name": ..., "status": ...}}``.
            year: שנת הלימודים העברית, ``'תשפ"ז'``.
            year_gregorian: השנה הלועזית, ``"2027"``.
        """
        clean: dict[str, dict] = {}
        for code, info in (courses or {}).items():
            key = str(code).strip()
            if not key:
                continue
            if isinstance(info, dict):
                entry = {str(k): v for k, v in info.items()}
                entry.setdefault("name", "")
                entry["name"] = str(entry.get("name") or "")
            else:
                # סלחנות: מי שמעביר {code: "שם"} מקבל את אותה תוצאה.
                entry = {"name": str(info or "")}
            clean[key] = entry

        payload = {
            "schema": CATALOG_SCHEMA,
            "version": SCHEMA_VERSION,
            "meta": {
                "fetched_at": utc_now_iso(),
                "year": str(year or ""),
                "year_gregorian": str(year_gregorian or ""),
                "count": len(clean),
            },
            # ממוין לפי קוד — כך ש-diff בין שתי גרסאות של הקובץ קריא לאדם.
            "courses": {c: clean[c] for c in sorted(clean, key=_code_sort_key)},
        }
        self._write_json(self.catalog_path, payload)

    def load_catalog(self) -> tuple[dict[str, dict], dict]:
        """טוען את הקטלוג. מחזיר ``(courses, meta)``; מסד ריק -> ``({}, {})``."""
        data = self._read_json(self.catalog_path, None)
        if not isinstance(data, dict):
            # אין קטלוג פרטי — נופלים לקטלוג שנשלח עם הקוד. זה מה שהופך
            # שכפול נקי מ"אפס קורסים" ל-572.
            if self.use_shipped and _shipped is not None and _shipped.available():
                info = _shipped.meta()
                return _shipped.index(), {
                    "fetched_at": info.get("built_at") or "",
                    "year": info.get("year") or "",
                    "year_gregorian": info.get("year_gregorian") or "",
                    "source": _shipped.SHIPPED_SOURCE,
                }
            return {}, {}
        raw = data.get("courses")
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        courses: dict[str, dict] = {}
        if isinstance(raw, dict):
            for code, info in raw.items():
                key = str(code).strip()
                if not key:
                    continue
                courses[key] = dict(info) if isinstance(info, dict) else {"name": str(info or "")}
        elif isinstance(raw, list):
            # סלחנות לצורה חלופית: [{"code": ..., "name": ...}, ...]
            for item in raw:
                if isinstance(item, dict) and item.get("code"):
                    key = str(item["code"]).strip()
                    courses[key] = {k: v for k, v in item.items() if k != "code"}
        return courses, dict(meta)

    def catalog_age_hours(self, now: datetime | None = None) -> float | None:
        """גיל הקטלוג בשעות. ``None`` כשאין קטלוג או שחותמת הזמן לא קריאה."""
        _, meta = self.load_catalog()
        if not meta:
            return None
        return age_hours_since(meta.get("fetched_at"), now)

    def search_catalog(self, query: str, limit: int = 40) -> list[tuple[str, str]]:
        """חיפוש בקטלוג לפי קוד או שם.

        דירוג התוצאות, בסדר הזה בדיוק:
          1. התאמה מדויקת לקוד הקורס;
          2. קוד שמתחיל במחרוזת החיפוש (למשל ``"617"`` -> 61753, 61756, ...);
          3. שם שמכיל את מחרוזת החיפוש.

        ההשוואה מנרמלת U+00A0, גרש/גרשיים עבריים ומרכאות מסולסלות — אחרת
        חיפוש ``מתמטיקה ב'`` לא היה מוצא קורס ששמו נכתב בידיעון עם ``ב׳``.

        Args:
            query: קוד, קידומת קוד, או חלק משם הקורס.
            limit: מספר תוצאות מרבי. ``0`` או פחות = בלי הגבלה.

        Returns:
            רשימת ``(code, name)``. מחרוזת חיפוש ריקה מחזירה רשימה ריקה —
            תפריט הבחירה לא אמור לשפוך 1172 קורסים לפני שהוקלד משהו.
        """
        q = _norm_search(query)
        if not q:
            return []
        courses, _ = self.load_catalog()
        if not courses:
            return []

        q_nospace = q.replace(" ", "")
        ranked: list[tuple[int, int, tuple[int, str], str, str]] = []
        for code, info in courses.items():
            name = str(info.get("name", "")) if isinstance(info, dict) else str(info or "")
            code_n = _norm_search(code)
            name_n = _norm_search(name)

            rank: int | None = None
            position = 0
            if code_n == q or code_n == q_nospace:
                rank = 0                                  # (1) קוד מדויק
            elif q_nospace and code_n.startswith(q_nospace):
                rank = 1                                  # (2) קידומת קוד
            elif q and q in name_n:
                rank = 2                                  # (3) תת-מחרוזת בשם
                position = name_n.index(q)
            if rank is None:
                continue
            ranked.append((rank, position, _code_sort_key(code), code, name))

        ranked.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
        results = [(code, name) for _, _, _, code, name in ranked]
        return results if limit is None or limit <= 0 else results[:limit]

    # ------------------------------------------------------------------
    # 6.3 סקשנים — הקבוצות המפורטות של קורס
    # ------------------------------------------------------------------
    def _load_sections_db(self) -> dict[str, Any]:
        """הקובץ הגולמי של sections.json, מעל הקטלוג שנשלח עם הקוד.

        **נקודת החיבור היחידה.** ``load_course``, ``load_all`` ו-``codes``
        כולם עוברים כאן, ולכן די בשכבה אחת: הקטלוג שנשלח הוא הבסיס, ומה
        שהמשתמש/ת שלפו בעצמם דורס אותו קוד-אחר-קוד. שכפול נקי מקבל את כל
        הקטלוג; מי ששלף קורס בעצמו מקבל את הגרסה שלו.
        """
        data = self._read_json(self.sections_path, None)
        if not isinstance(data, dict):
            data = {}
        courses = data.get("courses")
        if not isinstance(courses, dict):
            courses = {}

        merged: dict[str, Any] = {}
        if self.use_shipped and _shipped is not None:
            try:
                merged.update(
                    _shipped.as_sections_entries(self.shipped_semester)
                )
            except Exception:  # noqa: BLE001 - קטלוג פגום לא מפיל את המסד
                pass
        merged.update(courses)  # הנתונים של המשתמש/ת מנצחים

        return {
            "schema": data.get("schema", SECTIONS_SCHEMA),
            "version": _safe_int(data.get("version", SCHEMA_VERSION), SCHEMA_VERSION),
            "updated_at": data.get("updated_at", ""),
            "courses": merged,
        }

    @staticmethod
    def _split_entry(entry: Any, code: str) -> tuple[Course | None, CourseMeta | None]:
        """מפרק רשומת קורס אחת ל-(Course, CourseMeta).

        סלחני לשתי צורות: הצורה שאנחנו כותבים ``{"course": {...}, "meta": {...}}``,
        וגם קובץ שנכתב ביד שבו הרשומה עצמה היא הקורס.
        """
        if not isinstance(entry, dict):
            return None, None
        if "course" in entry or "meta" in entry:
            course = _course_from_dict(entry.get("course"), code)
            meta = CourseMeta.from_dict(entry.get("meta")) if entry.get("meta") is not None else None
        else:
            course = _course_from_dict(entry, code)
            meta = None
        return course, meta

    def save_course(self, course: Course | None, meta: CourseMeta) -> list[str]:
        """שומר קורס אחד ומחזיר את רשימת השינויים מול הגרסה שהייתה שמורה.

        זו המתודה שכל המודול קיים בשבילה. שני מסלולים:

        **שליפה שהצליחה** (``meta.ok is True``) — הקורס נכתב, והשינויים מול
        הגרסה הקודמת מוחזרים בעברית. שער זול קודם: אם ``content_sha1`` זהה
        לזה ששמור *וגם* טביעת האצבע המבנית זהה, הדף לא זז ואין מה להשוות.

        **שליפה שנכשלה** (``meta.ok is False``, או ``course is None``) — הנתונים
        הקודמים **נשארים במלואם**. מתעדכנים רק ``ok=False``,
        ``last_attempt_at`` ו-``last_error``; ``fetched_at`` שומר על חותמת
        ההצלחה האחרונה. כך "הנתונים עודכנו לאחרונה ב-..." נשאר נכון, והקורס
        מסומן כמיושן — במקום להציג נתון ישן כאילו הוא טרי.

        Args:
            course: הקורס החדש. ``None`` מסמן שליפה שנכשלה.
            meta: המטא של השליפה הנוכחית.

        Returns:
            רשימת תיאורי שינוי בעברית. ריקה בכתיבה ראשונה, כשאין שינוי,
            או כששליפה נכשלה (כישלון הוא לא "שינוי בקורס").

        Note:
            המתודה **לא** יוצרת snapshot ו**לא** כותבת ל-changes.jsonl:
            מי שמנהל את ריצת הרענון קורא ל-:meth:`snapshot` פעם אחת בתחילת
            הריצה, ול-:meth:`log_changes` על מה שחזר מכאן. אחרת היינו מקבלים
            גיבוי לכל קורס ומוחקים את היסטוריית הגיבויים בריצה אחת.
        """
        if meta is None:
            meta = CourseMeta()
        code = str((course.code if course is not None else "") or "").strip()
        db = self._load_sections_db()
        entries: dict[str, Any] = dict(db.get("courses") or {})

        if not code:
            # אין קוד לזהות לפיו — נסיון אחרון: אולי המטא מספיק ידידותי.
            raise StoreError("save_course נקרא בלי קוד קורס (course.code ריק).")

        prev_entry = entries.get(code)
        prev_course, prev_meta = self._split_entry(prev_entry, code)
        now_iso = utc_now_iso()
        changes: list[str] = []

        failed = (not meta.ok) or (course is None)
        if failed:
            # ---------- מסלול הכישלון: לא נוגעים בנתונים הטובים ----------
            kept_meta = prev_meta if prev_meta is not None else CourseMeta()
            new_meta = CourseMeta(
                # חותמת ההצלחה נשמרת כמו שהיא. זו הנקודה כולה.
                fetched_at=kept_meta.fetched_at,
                year=kept_meta.year or meta.year,
                year_gregorian=kept_meta.year_gregorian or meta.year_gregorian,
                semester=kept_meta.semester or meta.semester,
                source_url=meta.source_url or kept_meta.source_url,
                content_sha1=kept_meta.content_sha1,
                group_count=kept_meta.group_count,
                warnings=list(meta.warnings or kept_meta.warnings),
                ok=False,
                last_attempt_at=meta.last_attempt_at or now_iso,
                last_error=meta.last_error or "השליפה או הפרסור נכשלו",
            )
            kept_course_dict = None
            if isinstance(prev_entry, dict) and isinstance(prev_entry.get("course"), dict):
                kept_course_dict = prev_entry["course"]
            elif prev_course is not None:
                kept_course_dict = asdict(prev_course)
            entry: dict[str, Any] = {"meta": new_meta.to_dict()}
            if kept_course_dict is not None:
                entry["course"] = kept_course_dict
            entries[code] = entry
            self._store_sections(db, entries)
            return []

        # ---------- מסלול ההצלחה ----------
        assert course is not None  # מובטח ע"י הבדיקה למעלה
        new_fingerprint = _structure_fingerprint(course)
        prev_fingerprint = _structure_fingerprint(prev_course)

        # שער זול: אותו sha1 של HTML *וגם* אותה טביעת אצבע מבנית -> אין שינוי.
        # הבדיקה הכפולה מגינה מפני מטא ממוחזר עם sha1 ישן, שהיה מחביא שינוי אמיתי.
        cheap_gate_hit = bool(
            prev_meta is not None
            and prev_meta.content_sha1
            and meta.content_sha1
            and prev_meta.content_sha1 == meta.content_sha1
            and prev_fingerprint == new_fingerprint
        )
        if prev_course is not None and not cheap_gate_hit:
            changes = diff_courses(prev_course, course, code)

        stored_meta = CourseMeta(
            # חותמת השליפה נשמרת *בדיוק* כפי שהתקבלה, גם כשהיא ריקה או משובשת.
            # אין להשלים אותה ל-"עכשיו": רשומה שמקורה בזמן לא ידוע תיחשב מיושנת
            # ותרוענן בהרצה הבאה — וזה בדיוק הכיוון הבטוח. השלמה אוטומטית הייתה
            # מציגה נתונים שמקורם לא ידוע כאילו נשלפו הרגע, וזו בדיוק השקר
            # שהמנגנון הזה אמור למנוע. הקורא האמיתי (refresh.py) תמיד מציב
            # fetched_at=iso_utc() בעצמו, ולכן אין כאן רענון מיותר בפועל.
            fetched_at=meta.fetched_at,
            year=meta.year,
            year_gregorian=meta.year_gregorian,
            semester=meta.semester,
            source_url=meta.source_url,
            content_sha1=meta.content_sha1 or new_fingerprint,
            group_count=meta.group_count if meta.group_count else len(course.groups),
            warnings=list(meta.warnings or []),
            ok=True,
            last_attempt_at=meta.last_attempt_at or meta.fetched_at or now_iso,
            last_error="",
        )
        entries[code] = {"course": asdict(course), "meta": stored_meta.to_dict()}
        self._store_sections(db, entries)
        return changes

    def mark_failed(self, code: str, error: str = "", meta: CourseMeta | None = None) -> None:
        """מסמן שרענון של קורס נכשל, בלי לגעת בנתונים ששמורים.

        קיצור דרך נוח ל-``save_course(None, CourseMeta(ok=False, ...))``, לשימוש
        כשאין בכלל קורס חדש ביד (למשל: הדף לא נטען).
        """
        code = str(code).strip()
        if not code:
            return
        base = meta if meta is not None else CourseMeta()
        base.ok = False
        base.last_error = error or base.last_error or "השליפה נכשלה"
        base.last_attempt_at = base.last_attempt_at or utc_now_iso()
        # עוקפים את save_course כי אין Course עם code — בונים את הרשומה כאן.
        db = self._load_sections_db()
        entries: dict[str, Any] = dict(db.get("courses") or {})
        prev_entry = entries.get(code)
        prev_course, prev_meta = self._split_entry(prev_entry, code)
        kept = prev_meta if prev_meta is not None else CourseMeta()
        new_meta = CourseMeta(
            fetched_at=kept.fetched_at,                 # חותמת ההצלחה לא נדרסת
            year=kept.year or base.year,
            year_gregorian=kept.year_gregorian or base.year_gregorian,
            semester=kept.semester or base.semester,
            source_url=base.source_url or kept.source_url,
            content_sha1=kept.content_sha1,
            group_count=kept.group_count,
            warnings=list(base.warnings or kept.warnings),
            ok=False,
            last_attempt_at=base.last_attempt_at,
            last_error=base.last_error,
        )
        entry: dict[str, Any] = {"meta": new_meta.to_dict()}
        if isinstance(prev_entry, dict) and isinstance(prev_entry.get("course"), dict):
            entry["course"] = prev_entry["course"]
        elif prev_course is not None:
            entry["course"] = asdict(prev_course)
        entries[code] = entry
        self._store_sections(db, entries)

    def _store_sections(self, db: dict[str, Any], entries: dict[str, Any]) -> None:
        """כותב את sections.json מחדש, ממוין לפי קוד קורס."""
        payload = {
            "schema": SECTIONS_SCHEMA,
            "version": SCHEMA_VERSION,
            "updated_at": utc_now_iso(),
            "courses": {c: entries[c] for c in sorted(entries, key=_code_sort_key)},
        }
        self._write_json(self.sections_path, payload)

    def load_course(self, code: str) -> tuple[Course | None, CourseMeta | None]:
        """טוען קורס אחד ואת המטא שלו. ``(None, None)`` כשהקוד לא במסד."""
        code = str(code).strip()
        db = self._load_sections_db()
        entry = (db.get("courses") or {}).get(code)
        if entry is None:
            return None, None
        return self._split_entry(entry, code)

    def load_all(self) -> dict[str, Course]:
        """כל הקורסים ששמורים במסד, ``{code: Course}``.

        רשומות שהן מטא בלבד (שליפה ראשונה שנכשלה, בלי נתונים קודמים) לא
        מופיעות כאן — אין להן תוכן להציג.
        """
        db = self._load_sections_db()
        out: dict[str, Course] = {}
        for code, entry in (db.get("courses") or {}).items():
            course, _ = self._split_entry(entry, str(code))
            if course is not None:
                out[course.code or str(code)] = course
        return out

    def course_meta(self, code: str) -> CourseMeta | None:
        """המטא של קורס אחד, או ``None`` כשהקוד לא במסד."""
        _, meta = self.load_course(code)
        return meta

    def all_meta(self) -> dict[str, CourseMeta]:
        """המטא של כל הקורסים במסד — נוח לדוח מצב (``refresh.py --status``)."""
        db = self._load_sections_db()
        out: dict[str, CourseMeta] = {}
        for code, entry in (db.get("courses") or {}).items():
            _, meta = self._split_entry(entry, str(code))
            if meta is not None:
                out[str(code)] = meta
        return out

    def codes(self) -> list[str]:
        """כל קודי הקורסים ששמורים במסד, ממוינים."""
        db = self._load_sections_db()
        return sorted((db.get("courses") or {}).keys(), key=_code_sort_key)

    def is_stale(
        self,
        code: str,
        max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
        now: datetime | None = None,
    ) -> bool:
        """האם הרשומה של הקורס דורשת רענון.

        מיושן = אחד משלושה:
          * הקוד לא נמצא במסד בכלל;
          * ``meta.ok is False`` — הניסיון האחרון נכשל, אז הנתונים חשודים;
          * הגיל (``now - fetched_at``, בהשוואה ב-UTC) גדול מ-``max_age_hours``.

        חותמת זמן שלא ניתן לפרש נחשבת מיושנת. הגבול עצמו סלחני: גיל *ששווה
        בדיוק* ל-max_age_hours עדיין טרי; רק מעליו זה מיושן.
        """
        meta = self.course_meta(code)
        if meta is None:
            return True
        return meta.is_stale(max_age_hours, now)

    def stale_codes(
        self,
        codes: Iterable[str] | None = None,
        max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
        now: datetime | None = None,
    ) -> list[str]:
        """אילו מהקודים דורשים רענון. סדר הקלט נשמר; כפילויות מנוכות.

        ``codes=None`` בודק את כל הסט שבמעקב (:meth:`tracked`).
        """
        wanted = self._as_code_list(codes) if codes is not None else self.tracked()
        seen: set[str] = set()
        out: list[str] = []
        for c in wanted:
            if c in seen:
                continue
            seen.add(c)
            if self.is_stale(c, max_age_hours, now):
                out.append(c)
        return out

    # ------------------------------------------------------------------
    # 6.4 פרטי קורס — נ"ז, שעות, שפת הוראה ותנאי קדם (S_CourseDetails)
    # ------------------------------------------------------------------
    # למה החלק הזה קיים: עד עכשיו נקודות הזכות ותנאי הקדם הגיעו מ-
    # curriculum.json, שמתאר תוכנית לימודים של מחלקה אחת. 493 מתוך 571 קורסי
    # הקטלוג — 86% — פשוט לא נמצאים שם, ולכן דווחו כ-0.0 נ"ז. הידיעון מפרסם
    # את המידע הזה לכל קורס, בלי התחברות, בדף S_CourseDetails; כאן הוא נשמר,
    # וכך תוכנית הלימודים הופכת מדרישה להעשרה אופציונלית.
    #
    # שלושה כללים שולטים בכל מה שלמטה:
    #   1. **חלון טריות משלו — שבוע.** ראו DEFAULT_DETAILS_MAX_AGE_HOURS.
    #   2. **לא ממציאים 0.0.** אין רשומה -> None. סכום נ"ז ששותק על 86%
    #      מהקורסים גרוע מסכום שאומר בפירוש "לא ידוע".
    #   3. **כישלון לא הורס נתון טוב** — בדיוק כמו ב-save_course.
    #
    # מבנה הרשומה בקובץ details.json::
    #
    #     {"details": {...}, "fetched_at": "...", "ok": true,
    #      "last_attempt_at": "...", "last_error": ""}

    def _load_details_db(self) -> dict[str, Any]:
        """הקובץ הגולמי של details.json, תמיד בצורה תקינה (גם כשאינו קיים)."""
        data = self._read_json(self.details_path, None)
        if not isinstance(data, dict):
            return {"schema": DETAILS_SCHEMA, "version": SCHEMA_VERSION, "courses": {}}
        courses = data.get("courses")
        if not isinstance(courses, dict):
            courses = {}
        return {
            "schema": data.get("schema", DETAILS_SCHEMA),
            "version": _safe_int(data.get("version", SCHEMA_VERSION), SCHEMA_VERSION),
            "updated_at": data.get("updated_at", ""),
            "courses": courses,
        }

    def _store_details_db(self, entries: dict[str, Any]) -> None:
        """כותב את details.json מחדש, ממוין לפי קוד קורס — כתיבה אטומית."""
        payload = {
            "schema": DETAILS_SCHEMA,
            "version": SCHEMA_VERSION,
            "updated_at": utc_now_iso(),
            "courses": {c: entries[c] for c in sorted(entries, key=_code_sort_key)},
        }
        self._write_json(self.details_path, payload)

    @staticmethod
    def _split_details_entry(entry: Any) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """מפרק רשומת פרטים אחת ל-``(details, meta)``.

        סלחני לשתי צורות, בדיוק כמו :meth:`_split_entry`: הצורה שאנחנו כותבים
        (``{"details": {...}, "fetched_at": ...}``), וגם קובץ שנכתב ביד שבו
        הרשומה *עצמה* היא הפרטים. רשומה שאינה מילון, או שהפרטים שבתוכה אינם
        מילון או ריקים, מחזירה ``(None, ...)`` — כלומר "פגומה", וזה מספיק כדי
        שתיחשב מיושנת ותרוענן.
        """
        if not isinstance(entry, dict):
            return None, {}
        if "details" in entry or "fetched_at" in entry or "ok" in entry:
            payload = entry.get("details")
            meta = {k: v for k, v in entry.items() if k != "details"}
            return (payload if isinstance(payload, dict) and payload else None), meta
        return (dict(entry) if entry else None), {}

    @staticmethod
    def _details_entry_is_stale(
        payload: dict[str, Any] | None,
        meta: dict[str, Any],
        max_age_hours: float,
        now: datetime | None,
    ) -> bool:
        """הכלל היחיד למיושנוּת של פרטים — ראו :meth:`details_stale`."""
        if payload is None:
            return True
        if not bool(meta.get("ok", True)):
            return True
        age = age_hours_since(meta.get("fetched_at"), now)
        if age is None:      # חסרה חותמת, או שאי אפשר לפרש אותה -> מיושן
            return True
        return age > _safe_float(max_age_hours, DEFAULT_DETAILS_MAX_AGE_HOURS)

    def _details_failure_entry(
        self,
        prev_payload: dict[str, Any] | None,
        prev_meta: dict[str, Any],
        error: str,
        attempt_at: str,
    ) -> dict[str, Any]:
        """בונה רשומת כישלון ששומרת על הנתון הטוב הקודם במלואו.

        בדיוק כמו במסלול הכישלון של :meth:`save_course`: ``fetched_at`` (חותמת
        ההצלחה האחרונה) **לא** נדרסת, הפרטים הישנים נשארים במקומם, ורק ``ok``,
        ``last_attempt_at`` ו-``last_error`` מתעדכנים. התוצאה: התצוגה עדיין
        יודעת כמה נ"ז יש לקורס, והרענון הבא ינסה שוב.
        """
        entry: dict[str, Any] = {}
        if prev_payload is not None:
            entry["details"] = prev_payload
        entry["fetched_at"] = str(prev_meta.get("fetched_at", "") or "")
        entry["ok"] = False
        entry["last_attempt_at"] = attempt_at
        entry["last_error"] = error
        return entry

    def save_details(self, code: str, details: dict, fetched_at: str) -> None:
        """שומר את פרטי הקורס (נ"ז, שעות, שפה, תיאור, תנאי קדם) מדף הידיעון.

        שני מסלולים, בדיוק כמו ב-:meth:`save_course`:

        **שליפה שהצליחה** — ``details`` הוא מילון עם תוכן. הוא נשמר *כפי שהוא*,
        ו-``fetched_at`` נשמר גם הוא בדיוק כפי שהתקבל: חותמת ריקה או משובשת
        תגרום לרשומה להיחשב מיושנת ולהתרענן בהרצה הבאה, וזה הכיוון הבטוח. אין
        כאן השלמה שקטה ל"עכשיו", שהייתה מציגה נתון ממקור-זמן לא ידוע כטרי.

        **שליפה שנכשלה** — ``details`` ריק, ``None``, או לא מילון. הרשומה
        הקודמת **נשארת במלואה**, כולל ``fetched_at``; מתעדכנים רק ``ok=False``,
        ``last_attempt_at`` ו-``last_error``, והרשומה נחשבת מיושנת.

        Args:
            code: קוד הקורס. חובה.
            details: מילון הפרטים. מתקבל גם ``NamedTuple``/dataclass (למשל
                ``CourseDetails`` של הפרסר) — ראו :func:`_as_details_dict`.
            fetched_at: חותמת ISO-8601 ב-UTC, למשל מ-:func:`utc_now_iso`.

        Raises:
            StoreError: כשקוד הקורס ריק, או כשהכתיבה לדיסק נכשלה.
        """
        code = str(code or "").strip()
        if not code:
            raise StoreError("save_details נקרא בלי קוד קורס.")

        payload = _as_details_dict(details)
        db = self._load_details_db()
        entries: dict[str, Any] = dict(db.get("courses") or {})
        prev_payload, prev_meta = self._split_details_entry(entries.get(code))
        stamp = str(fetched_at or "")

        if payload is None:
            entries[code] = self._details_failure_entry(
                prev_payload,
                prev_meta,
                "לא התקבלו פרטי קורס מהידיעון",
                stamp or utc_now_iso(),
            )
        else:
            entries[code] = {
                "details": payload,
                "fetched_at": stamp,
                "ok": True,
                "last_attempt_at": stamp or utc_now_iso(),
                "last_error": "",
            }
        self._store_details_db(entries)

    def mark_details_failed(self, code: str, error: str = "") -> None:
        """מסמן ששליפת הפרטים של קורס נכשלה, בלי לגעת במה ששמור.

        קיצור דרך ל-``save_details(code, None, utc_now_iso())`` עם תיאור שגיאה
        משלכם, לשימוש כשאין בכלל דף ביד (הדף לא נטען, הקורס לא קיים בידיעון).
        """
        code = str(code or "").strip()
        if not code:
            return
        db = self._load_details_db()
        entries: dict[str, Any] = dict(db.get("courses") or {})
        prev_payload, prev_meta = self._split_details_entry(entries.get(code))
        entries[code] = self._details_failure_entry(
            prev_payload,
            prev_meta,
            error or "שליפת פרטי הקורס נכשלה",
            utc_now_iso(),
        )
        self._store_details_db(entries)

    def load_details(self, code: str) -> dict | None:
        """מחזיר את פרטי הקורס ששמורים, או ``None`` כשאין רשומה תקינה.

        מה שנשמר הוא מה שחוזר — עיגול הלוך-ושוב מדויק, בלי שדות מטא שמוזרקים
        פנימה (את חותמת הזמן שולפים ב-:meth:`details_meta` או
        ב-:meth:`details_fetched_at`). מוחזר עותק עמוק, כדי ששינוי אצל הקורא לא
        ידלוף למטמון הקריאה של המודול.

        ``None`` פירושו "לא ידוע" — **לא** אפס. מי שמציג נ"ז חייב להראות מקף
        במקרה הזה ולא ``0.0``: סכום שמעלים 86% מהקורסים גרוע מסכום שמודה שאינו
        יודע.
        """
        code = str(code or "").strip()
        if not code:
            return None
        db = self._load_details_db()
        payload, _meta = self._split_details_entry((db.get("courses") or {}).get(code))
        if payload is None:
            return None
        return copy.deepcopy(payload)

    def details_meta(self, code: str) -> dict | None:
        """המטא של רשומת הפרטים, או ``None`` כשאין רשומה בכלל.

        Returns:
            ``{"fetched_at", "ok", "last_attempt_at", "last_error", "has_details"}``.
        """
        code = str(code or "").strip()
        db = self._load_details_db()
        entry = (db.get("courses") or {}).get(code)
        if entry is None:
            return None
        payload, meta = self._split_details_entry(entry)
        return {
            "fetched_at": str(meta.get("fetched_at", "") or ""),
            "ok": bool(meta.get("ok", True)),
            "last_attempt_at": str(meta.get("last_attempt_at", "") or ""),
            "last_error": str(meta.get("last_error", "") or ""),
            "has_details": payload is not None,
        }

    def details_fetched_at(self, code: str) -> str:
        """חותמת ההצלחה האחרונה של הפרטים, או מחרוזת ריקה."""
        meta = self.details_meta(code)
        return str((meta or {}).get("fetched_at", "") or "")

    def details_age_hours(self, code: str, now: datetime | None = None) -> float | None:
        """גיל הפרטים בשעות. ``None`` כשאין רשומה או שהחותמת לא קריאה."""
        return age_hours_since(self.details_fetched_at(code), now)

    def details_stale(
        self,
        code: str,
        max_age_hours: float = DEFAULT_DETAILS_MAX_AGE_HOURS,
        now: datetime | None = None,
    ) -> bool:
        """האם צריך לשלוף מחדש את פרטי הקורס.

        מיושן = אחד מארבעה:
          * הקוד לא נמצא בקובץ הפרטים בכלל;
          * הרשומה פגומה (אינה מילון, או שאין בה פרטים);
          * ``ok is False`` — הניסיון האחרון נכשל, אז הנתונים חשודים;
          * הגיל (``now - fetched_at``, בהשוואה ב-UTC) גדול מ-``max_age_hours``.

        חותמת זמן חסרה או שאי אפשר לפרש אותה נחשבת מיושנת — אותו כלל בטיחות
        כמו ב-:meth:`is_stale`. הגבול עצמו סלחני: גיל *ששווה בדיוק* לסף עדיין
        טרי; רק מעליו זה מיושן.

        ברירת המחדל היא שבוע (``DEFAULT_DETAILS_MAX_AGE_HOURS``) ולא 24 שעות,
        כי נ"ז ותנאי קדם כמעט לא משתנים — הרענון היומי לא צריך להכפיל את מספר
        הפניות שלו לידיעון בשביל נתון שלא זז.
        """
        code = str(code or "").strip()
        db = self._load_details_db()
        entry = (db.get("courses") or {}).get(code)
        if entry is None:
            return True
        payload, meta = self._split_details_entry(entry)
        return self._details_entry_is_stale(payload, meta, max_age_hours, now)

    def all_details(self) -> dict[str, dict]:
        """כל רשומות הפרטים התקינות שבמסד, ``{code: details}``.

        רשומות שהן מטא בלבד (שליפה ראשונה שנכשלה) לא מופיעות כאן — אין להן
        תוכן להציג.
        """
        db = self._load_details_db()
        out: dict[str, dict] = {}
        for code, entry in (db.get("courses") or {}).items():
            payload, _meta = self._split_details_entry(entry)
            if payload is not None:
                out[str(code)] = copy.deepcopy(payload)
        return out

    def details_codes(self) -> list[str]:
        """כל הקודים שיש להם רשומת פרטים (כולל רשומת כישלון), ממוינים."""
        db = self._load_details_db()
        return sorted((db.get("courses") or {}).keys(), key=_code_sort_key)

    def stale_details_codes(
        self,
        codes: Iterable[str] | None = None,
        max_age_hours: float = DEFAULT_DETAILS_MAX_AGE_HOURS,
        now: datetime | None = None,
    ) -> list[str]:
        """אילו מהקודים דורשים שליפת פרטים. סדר הקלט נשמר; כפילויות מנוכות.

        ``codes=None`` בודק את כל הסט שבמעקב (:meth:`tracked`). הקובץ נקרא פעם
        אחת לכל הקריאה, ולא פעם לכל קוד.
        """
        wanted = self._as_code_list(codes) if codes is not None else self.tracked()
        db = self._load_details_db()
        entries = db.get("courses") or {}
        seen: set[str] = set()
        out: list[str] = []
        for c in wanted:
            if c in seen:
                continue
            seen.add(c)
            entry = entries.get(c)
            if entry is None:
                out.append(c)
                continue
            payload, meta = self._split_details_entry(entry)
            if self._details_entry_is_stale(payload, meta, max_age_hours, now):
                out.append(c)
        return out

    # ------------------------------------------------------------------
    # 6.5 סט המעקב
    # ------------------------------------------------------------------
    def tracked(self) -> list[str]:
        """קודי הקורסים שהרענון היומי דואג להם, ממוינים."""
        data = self._read_json(self.tracked_path, None)
        raw: Any = []
        if isinstance(data, dict):
            raw = data.get("codes") or []
        elif isinstance(data, list):
            raw = data           # סלחנות לקובץ שנכתב ביד כרשימה שטוחה
        codes = {c for c in self._as_code_list(raw)}
        return sorted(codes, key=_code_sort_key)

    def _store_tracked(self, codes: Sequence[str]) -> None:
        payload = {
            "schema": TRACKED_SCHEMA,
            "version": SCHEMA_VERSION,
            "updated_at": utc_now_iso(),
            "codes": sorted(set(codes), key=_code_sort_key),
        }
        self._write_json(self.tracked_path, payload)

    def track(self, codes: Iterable[str] | str) -> None:
        """מוסיף קודים לסט המעקב. איחוד, בלי כפילויות, ממוין."""
        new = self._as_code_list(codes)
        if not new:
            return
        merged = set(self.tracked()) | set(new)
        self._store_tracked(sorted(merged, key=_code_sort_key))

    def untrack(self, codes: Iterable[str] | str) -> None:
        """מוציא קודים מסט המעקב. הנתונים ששמורים לקורס **לא** נמחקים —
        הם פשוט מפסיקים להתרענן."""
        drop = set(self._as_code_list(codes))
        if not drop:
            return
        remaining = [c for c in self.tracked() if c not in drop]
        self._store_tracked(remaining)

    # ------------------------------------------------------------------
    # 6.6 יומנים וגיבויים
    # ------------------------------------------------------------------
    def log_refresh(self, record: dict) -> None:
        """מוסיף רשומה ליומן הרענונים (``refresh_log.jsonl``), שורה אחת לריצה."""
        entry = dict(record or {})
        entry.setdefault("logged_at", utc_now_iso())
        entry.setdefault("schema_version", SCHEMA_VERSION)
        self._append_jsonl(self.refresh_log_path, entry)

    def log_changes(self, code: str, changes: list[str]) -> None:
        """מוסיף ל-``changes.jsonl`` שורה אחת **לכל שינוי** שזוהה.

        שורה-לשינוי (ולא שורה-לקורס) כדי שאפשר יהיה לשאול "מה השתנה בקורס
        61753 מאז תחילת הסמסטר" בעזרת grep פשוט.
        """
        if not changes:
            return
        stamp = utc_now_iso()
        for line in changes:
            self._append_jsonl(
                self.changes_log_path,
                {"at": stamp, "code": str(code), "change": str(line)},
            )

    def last_refresh(self) -> dict | None:
        """הרשומה האחרונה ביומן הרענונים, או ``None`` כשאין יומן.

        קורא מהסוף אחורה ומדלג על שורות פגומות — יומן שנקטע באמצע שורה
        (מחשב שנכבה) עדיין ייתן את הריצה המוצלחת שלפניה.
        """
        if not os.path.exists(self.refresh_log_path):
            return None
        try:
            with open(self.refresh_log_path, "r", encoding="utf-8-sig") as fh:
                lines = fh.read().splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            LOG.warning("לא ניתן לקרוא את יומן הרענונים: %s", exc)
            return None
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue     # שורה חתוכה — ממשיכים אחורה
            if isinstance(obj, dict):
                return obj
        return None

    def read_changes(self, limit: int = 50) -> list[dict]:
        """‏``limit`` השינויים האחרונים מ-``changes.jsonl``, מהחדש לישן."""
        if not os.path.exists(self.changes_log_path):
            return []
        try:
            with open(self.changes_log_path, "r", encoding="utf-8-sig") as fh:
                lines = fh.read().splitlines()
        except (OSError, UnicodeDecodeError):
            return []
        out: list[dict] = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
            if 0 < limit <= len(out):
                break
        return out

    def snapshot(self, now: datetime | None = None) -> str | None:
        """מעתיק את ``sections.json`` הנוכחי ל-``snapshots/YYYY-MM-DD-HHMM.json``.

        נקרא **פעם אחת בתחילת ריצת רענון**, לפני הדריסה, כדי שאפשר יהיה לחזור
        אחורה אם רענון החזיר נתונים שגויים (למשל: הידיעון החזיר את השנה הלא
        נכונה). מחזיר את נתיב הגיבוי, או ``None`` כשעדיין אין מה לגבות.

        התיקייה מוגבלת ל-``MAX_SNAPSHOTS`` (=30) הגיבויים העדכניים ביותר;
        בריצה יומית זה חודש אחורה. כל מה שמעבר לזה — הישנים ביותר — נמחק,
        כדי שהתיקייה לא תגדל בלי גבול על המחשב של הסטודנט.
        """
        if not os.path.exists(self.sections_path):
            return None
        try:
            with open(self.sections_path, "r", encoding="utf-8-sig") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            LOG.warning("לא ניתן לקרוא את sections.json לגיבוי: %s", exc)
            return None

        try:
            os.makedirs(self.snapshots_dir, exist_ok=True)
        except OSError as exc:  # pragma: no cover
            raise StoreError(f"לא ניתן ליצור את תיקיית הגיבויים: {exc}") from exc

        stamp = self._now(now).strftime("%Y-%m-%d-%H%M")
        dest = os.path.join(self.snapshots_dir, f"{stamp}.json")
        # שתי ריצות באותה דקה — לא דורסים, מוסיפים סיומת מונה.
        counter = 2
        while os.path.exists(dest) and counter < 100:
            dest = os.path.join(self.snapshots_dir, f"{stamp}-{counter}.json")
            counter += 1
        self._atomic_write_text(dest, text)
        self._prune_snapshots()
        return dest

    def list_snapshots(self) -> list[str]:
        """נתיבי הגיבויים, מהחדש לישן."""
        if not os.path.isdir(self.snapshots_dir):
            return []
        try:
            names = [n for n in os.listdir(self.snapshots_dir) if n.endswith(".json")]
        except OSError:  # pragma: no cover
            return []
        paths = [os.path.join(self.snapshots_dir, n) for n in names]
        # שם הקובץ הוא YYYY-MM-DD-HHMM ולכן מיון לקסיקוגרפי הוא כרונולוגי.
        # ה-mtime הוא רק שובר-שוויון, למקרה של קובץ ששמו נערך ביד.
        def key(p: str) -> tuple[str, float]:
            try:
                return (os.path.basename(p), os.path.getmtime(p))
            except OSError:  # pragma: no cover
                return (os.path.basename(p), 0.0)

        return sorted(paths, key=key, reverse=True)

    def _prune_snapshots(self, keep: int = MAX_SNAPSHOTS) -> list[str]:
        """מוחק את הגיבויים הישנים מעבר ל-``keep`` (ברירת מחדל 30).

        מחזיר את רשימת הקבצים שנמחקו — נוח לבדיקה ולדיווח.
        """
        paths = self.list_snapshots()
        deleted: list[str] = []
        for path in paths[keep:]:
            try:
                os.remove(path)
                deleted.append(path)
            except OSError as exc:  # pragma: no cover
                LOG.warning("לא ניתן למחוק גיבוי ישן %s: %s", path, exc)
        return deleted

    # ------------------------------------------------------------------
    # 6.7 סיכום מצב לתצוגה
    # ------------------------------------------------------------------
    def freshness(
        self,
        codes: Iterable[str] | None = None,
        max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """דוח טריות קצר לתצוגה ב-CLI ולפלט ``refresh.py --status``.

        Returns:
            מילון עם: ``newest``/``oldest`` (חותמות), ``age_hours``,
            ``stale`` (רשימת קודים מיושנים), ``failed`` (קודים עם ok=False),
            ``text`` (שורה עברית מוכנה להדפסה).
        """
        wanted = self._as_code_list(codes) if codes is not None else self.codes()
        metas = self.all_meta()
        stamps: list[str] = []
        stale: list[str] = []
        failed: list[str] = []
        for c in wanted:
            meta = metas.get(c)
            if meta is None:
                stale.append(c)
                continue
            if not meta.ok:
                failed.append(c)
            if meta.is_stale(max_age_hours, now):
                stale.append(c)
            if meta.fetched_at:
                stamps.append(meta.fetched_at)
        newest = max(stamps) if stamps else ""      # ISO-8601 UTC ממוין לקסיקוגרפית = כרונולוגית
        oldest = min(stamps) if stamps else ""
        age = age_hours_since(oldest, now)
        if oldest:
            dt = parse_iso_utc(oldest)
            local = dt.astimezone().strftime("%Y-%m-%d %H:%M") if dt else "?"
            text = strings_mod.fmt(
                "server.freshness.lastUpdated",
                when=local,
                age=format_hebrew_age(age),
            )
        else:
            text = strings_mod.get("server.freshness.empty", "")
        return {
            "newest": newest,
            "oldest": oldest,
            "age_hours": age,
            "stale": stale,
            "failed": failed,
            "text": text,
        }


# ==========================================================================
# 7. בדיקה עצמית — רצה כש-store.py מופעל ישירות (python src/store.py)
# ==========================================================================
def _demo_course(
    code: str = "61753",
    lecturer: str = 'פרופ\' וולקוביץ\' זאב',
    day: int = 2,
    start: int = 615,
    end: int = 720,
    room: str = "305",
) -> Course:
    """קורס דמו קטן לבדיקה העצמית — מבנה אמיתי, נתונים מומצאים."""
    return Course(
        code=code,
        name="אלגוריתמים",
        credits=5.0,
        groups=[
            Group(
                course_code=code,
                group_id="21",
                kind="הרצאה",
                lecturer=lecturer,
                meetings=[Meeting(day=day, start=start, end=end, room=room, semester="א")],
                linked_to=["24"],
                note="מסלול בוקר",
            ),
            Group(
                course_code=code,
                group_id="24",
                kind="תרגול",
                lecturer='ד"ר גולני מתתיהו',
                meetings=[Meeting(day=3, start=720, end=825, room="411", semester="א")],
            ),
        ],
    )


def _demo_meta(sha: str, when: datetime | None = None, ok: bool = True) -> CourseMeta:
    return CourseMeta(
        fetched_at=utc_now_iso(when),
        year='תשפ"ז',
        year_gregorian="2027",
        semester="א",
        source_url="https://info.braude.ac.il/yedion/fireflyweb.aspx?prgname=S_LOOK_FOR_NOSE&arguments=-N61753",
        content_sha1=sha,
        group_count=2,
        warnings=[],
        ok=ok,
    )


def self_check(verbose: bool = True) -> list[str]:
    """בודק שמירה, טעינה, מיושנוּת וזיהוי שינויים על תיקייה זמנית.

    כל הבדיקות אופליין ולא נוגעות ב-``data/db`` האמיתי.
    """
    import shutil
    import tempfile

    problems: list[str] = []

    def check(label: str, got: Any, want: Any) -> None:
        if got == want:
            if verbose:
                print(f"  ok  {label}")
        else:
            problems.append(f"{label}: קיבלנו {got!r}, ציפינו ל-{want!r}")
            if verbose:
                print(f"  FAIL {label}: {got!r} != {want!r}")

    def check_true(label: str, got: Any) -> None:
        check(label, bool(got), True)

    tmpdir = tempfile.mkdtemp(prefix="store_selfcheck_")
    try:
        root = os.path.join(tmpdir, "db")
        store = Store(root)

        # ----- מסד ריק לא מתפוצץ ולא יוצר קבצים -----
        check("מסד ריק: load_all", store.load_all(), {})
        check("מסד ריק: tracked", store.tracked(), [])
        check("מסד ריק: catalog", store.load_catalog(), ({}, {}))
        check("מסד ריק: last_refresh", store.last_refresh(), None)
        check("מסד ריק: is_stale על קוד לא קיים", store.is_stale("99999"), True)
        check("מסד ריק: snapshot", store.snapshot(), None)

        # ----- סט המעקב -----
        store.track(["61753", "61756", "61753"])      # כפילות בכוונה
        store.track("11069")                          # מחרוזת בודדת
        check("tracked: איחוד + ניכוי כפילויות + מיון",
              store.tracked(), ["11069", "61753", "61756"])
        store.untrack(["61756"])
        check("untrack", store.tracked(), ["11069", "61753"])

        # ----- קטלוג + חיפוש מדורג -----
        store.save_catalog(
            {
                "61753": {"name": "אלגוריתמים", "status": "נלמד"},
                "61756": {"name": "שיטות הנדסיות לפיתוח מערכות תוכנה", "status": "נלמד"},
                "271030": {"name": "מתמטיקה ב׳", "status": "נלמד"},   # גרש עברי בכוונה
                "11069": {"name": "אנגלית טכנית יישומית", "status": "נלמד"},
            },
            'תשפ"ז',
            "2027",
        )
        courses, cmeta = store.load_catalog()
        check("catalog: מספר קורסים", len(courses), 4)
        check("catalog: שנה", cmeta.get("year"), 'תשפ"ז')
        check_true("catalog: גיל מחושב", store.catalog_age_hours() is not None)
        # דירוג: קוד מדויק מנצח קידומת, קידומת מנצחת שם
        ranked = [c for c, _ in store.search_catalog("61753")]
        check("search: קוד מדויק ראשון", ranked[0] if ranked else None, "61753")
        prefix = [c for c, _ in store.search_catalog("617")]
        check("search: קידומת קוד", prefix, ["61753", "61756"])
        by_name = store.search_catalog("מתמטיקה ב'")   # גרש ASCII מול גרש עברי בקטלוג
        check("search: נרמול גרש עברי מול ASCII",
              [c for c, _ in by_name], ["271030"])
        check("search: מחרוזת ריקה", store.search_catalog("  "), [])
        check("search: limit", len(store.search_catalog("א", limit=1)), 1)

        # ----- שמירה ראשונה: אין שינויים -----
        course_v1 = _demo_course()
        changes = store.save_course(course_v1, _demo_meta("sha-v1"))
        check("save_course: כתיבה ראשונה מחזירה רשימה ריקה", changes, [])
        loaded, meta = store.load_course("61753")
        check("round-trip: הקורס שנטען זהה למקורי", loaded, course_v1)
        check("round-trip: שנה במטא", meta.year if meta else None, 'תשפ"ז')
        check("load_all", list(store.load_all()), ["61753"])
        check("codes", store.codes(), ["61753"])

        # ----- שמירה חוזרת של אותו דבר: אין שינויים -----
        again = store.save_course(_demo_course(), _demo_meta("sha-v1"))
        check("save_course: ללא שינוי -> רשימה ריקה", again, [])

        # ----- מרצה השתנה -----
        v2 = _demo_course(lecturer='ד"ר גולני מתתיהו')
        changes = store.save_course(v2, _demo_meta("sha-v2"))
        check("change: מרצה", changes,
              ['61753: קבוצה 21 — המרצה השתנה: פרופ\' וולקוביץ\' זאב -> ד"ר גולני מתתיהו'])

        # ----- שעה ויום השתנו -----
        v3 = _demo_course(lecturer='ד"ר גולני מתתיהו', day=3, start=720, end=825)
        changes = store.save_course(v3, _demo_meta("sha-v3"))
        check("change: שעה ויום", changes,
              ["61753: קבוצה 21 — השעה השתנתה: יום ב 10:15-12:00 -> יום ג 12:00-13:45"])

        # ----- חדר השתנה -----
        v4 = _demo_course(lecturer='ד"ר גולני מתתיהו', day=3, start=720, end=825, room="411")
        changes = store.save_course(v4, _demo_meta("sha-v4"))
        check("change: חדר", changes,
              ["61753: קבוצה 21 — החדר השתנה (יום ג 12:00-13:45): 305 -> 411"])

        # ----- קבוצה נוספה + קבוצה בוטלה -----
        v5 = _demo_course(lecturer='ד"ר גולני מתתיהו', day=3, start=720, end=825, room="411")
        v5.groups = [
            v5.groups[0],
            Group(
                course_code="61753",
                group_id="22",
                kind="הרצאה",
                lecturer='ד"ר רווה אלנה',
                meetings=[Meeting(day=4, start=510, end=615, semester="א")],
            ),
        ]
        changes = store.save_course(v5, _demo_meta("sha-v5"))
        check("change: קבוצה נוספה + קבוצה בוטלה", changes,
              ['61753: נוספה קבוצה 22 (הרצאה, ד"ר רווה אלנה)',
               "61753: בוטלה קבוצה 24 (תרגול)"])

        # ----- טריות ומיושנוּת -----
        check("is_stale: נתון טרי", store.is_stale("61753"), False)
        now = datetime.now(timezone.utc)
        # בדיוק על הגבול -> עדיין טרי; מעל הגבול -> מיושן; מתחת -> טרי
        store.save_course(_demo_course(), _demo_meta("sha-old", now - timedelta(hours=24)))
        check("is_stale: בדיוק 24 שעות -> טרי",
              store.is_stale("61753", 24.0, now - timedelta(seconds=1)), False)
        check("is_stale: 24 שעות ודקה -> מיושן",
              store.is_stale("61753", 24.0, now + timedelta(minutes=1)), True)
        check("is_stale: מתחת לגבול -> טרי", store.is_stale("61753", 48.0, now), False)
        check("stale_codes", store.stale_codes(["61753", "99999"], 48.0, now), ["99999"])

        # ----- כישלון לא הורס נתונים טובים -----
        before_course, before_meta = store.load_course("61753")
        failed_meta = _demo_meta("sha-should-be-ignored", ok=False)
        failed_meta.last_error = "הדף לא נטען"
        store.save_course(None if False else before_course, failed_meta)
        after_course, after_meta = store.load_course("61753")
        check("כישלון: הקורס נשמר במלואו", after_course, before_course)
        check("כישלון: ok=False", after_meta.ok if after_meta else None, False)
        check("כישלון: fetched_at לא נדרס",
              after_meta.fetched_at if after_meta else None,
              before_meta.fetched_at if before_meta else None)
        check_true("כישלון: last_attempt_at נרשם", (after_meta.last_attempt_at if after_meta else ""))
        check("כישלון: ok=False נחשב מיושן", store.is_stale("61753", 10_000.0), True)

        # mark_failed על קוד שאין לו נתונים בכלל
        store.mark_failed("99999", "הקורס לא נמצא בידיעון")
        c99, m99 = store.load_course("99999")
        check("mark_failed: אין קורס", c99, None)
        check("mark_failed: המטא נרשם", m99.last_error if m99 else None, "הקורס לא נמצא בידיעון")

        # ----- פרטי קורס: עיגול הלוך-ושוב, חלון של שבוע, כישלון שלא הורס -----
        details = {
            "code": "61753",
            "name": "אלגוריתמים",
            "credits": 5.0,
            "hours": {"he": 4.0, "te": 2.0, "ma": 0.0, "pr": 0.0},
            "weekly_hours": 4.0,
            "language": "עברית",
            "description": "מטרת הקורס היא להקנות כלים לתכנון וניתוח אלגוריתמים.",
            "prerequisites": [
                {"code": "61140", "name": "מבני נתונים", "relation": "תנאי קדם", "alternative": ""}
            ],
            "warnings": [],
        }
        check("details: אין רשומה -> None", store.load_details("61753"), None)
        check("details: אין רשומה -> מיושן", store.details_stale("61753"), True)

        store.save_details("61753", details, utc_now_iso(now - timedelta(days=3)))
        check("details: עיגול הלוך-ושוב מדויק", store.load_details("61753"), details)
        check("details: בן 3 ימים טרי בחלון של שבוע",
              store.details_stale("61753", now=now), False)
        check("details: אותה רשומה מיושנת בחלון של 24 שעות",
              store.details_stale("61753", 24.0, now=now), True)
        check("details: ברירת המחדל היא שבוע", DEFAULT_DETAILS_MAX_AGE_HOURS, 168.0)
        check("details: all_details", list(store.all_details()), ["61753"])
        check("details: stale_details_codes",
              store.stale_details_codes(["61753", "99999"], now=now), ["99999"])

        store.save_details("61753", details, utc_now_iso(now - timedelta(days=8)))
        check("details: בן 8 ימים -> מיושן", store.details_stale("61753", now=now), True)

        # כישלון: הרשומה הטובה נשארת, רק המטא מתעדכן
        good_stamp = utc_now_iso(now - timedelta(days=1))
        store.save_details("61753", details, good_stamp)
        store.save_details("61753", None, utc_now_iso(now))
        check("details: כישלון לא מוחק את הפרטים", store.load_details("61753"), details)
        check("details: כישלון לא דורס את fetched_at", store.details_fetched_at("61753"), good_stamp)
        check("details: כישלון -> מיושן", store.details_stale("61753", 100_000.0, now=now), True)
        store.save_details("61753", details, good_stamp)   # חזרה למצב תקין
        check("details: רענון מוצלח מחזיר לטרי", store.details_stale("61753", now=now), False)

        # חותמת לא קריאה = מיושן (אותו כלל בטיחות כמו בקורסים)
        store.save_details("11001", {"code": "11001", "credits": None}, "לא תאריך")
        check("details: חותמת משובשת -> מיושן", store.details_stale("11001", now=now), True)
        check("details: הפרטים עצמם עדיין נטענים",
              (store.load_details("11001") or {}).get("code"), "11001")
        check("details: credits לא ידוע נשאר None ולא 0.0",
              (store.load_details("11001") or {}).get("credits"), None)

        # קוד שלא נשלף מעולם, ורשומת כישלון בלי נתון קודם
        store.mark_details_failed("99999", "הקורס לא נמצא בידיעון")
        check("mark_details_failed: אין פרטים", store.load_details("99999"), None)
        check("mark_details_failed: המטא נרשם",
              (store.details_meta("99999") or {}).get("last_error"), "הקורס לא נמצא בידיעון")
        try:
            store.save_details("", details, utc_now_iso(now))
            empty_code_raised = False
        except StoreError:
            empty_code_raised = True
        check("details: קוד ריק -> StoreError", empty_code_raised, True)

        # ----- יומנים -----
        store.log_refresh({"started_at": utc_now_iso(), "ok": True, "refreshed": 1})
        store.log_refresh({"started_at": utc_now_iso(), "ok": False, "reason": "needs_login"})
        last = store.last_refresh()
        check("last_refresh: הרשומה האחרונה", (last or {}).get("reason"), "needs_login")
        store.log_changes("61753", ["61753: בוטלה קבוצה 27 (תרגול)"])
        check("read_changes", len(store.read_changes()), 1)

        # ----- גיבויים + תקרת 30 -----
        first_snap = store.snapshot()
        check_true("snapshot: נוצר קובץ", first_snap and os.path.exists(first_snap))
        for i in range(35):
            store.snapshot(now=now + timedelta(minutes=i + 1))
        check("snapshot: לא יותר מ-30 גיבויים", len(store.list_snapshots()), MAX_SNAPSHOTS)

        # ----- קובץ פגום לא מפיל את הכלי -----
        with open(store.sections_path, "w", encoding="utf-8") as fh:
            fh.write('{"courses": {"61753": {"course": ')      # JSON קטוע בכוונה
        broken = Store(root)
        check("קובץ פגום: load_all מחזיר ריק", broken.load_all(), {})
        check_true("קובץ פגום: נרשמה אזהרה", broken.warnings)
        quarantined = [n for n in os.listdir(root) if ".corrupt-" in n]
        check("קובץ פגום: הקובץ נשמר בצד", len(quarantined), 1)
        check_true("קובץ פגום: המסד ממשיך לעבוד", broken.save_course(_demo_course(), _demo_meta("s")) == [])

        # ----- ניסוח גיל בעברית -----
        check("format_hebrew_age: 3 שעות", format_hebrew_age(3.0), "לפני 3 שעות")
        check("format_hebrew_age: שעתיים", format_hebrew_age(2.0), "לפני שעתיים")
        check("format_hebrew_age: יומיים", format_hebrew_age(48.0), "לפני יומיים")
        check("format_hebrew_age: לא ידוע", format_hebrew_age(None), "לא ידוע מתי")

        # ----- זמנים תמיד מודעים ל-UTC -----
        check_true("parse_iso_utc: מודע לאזור זמן",
                   parse_iso_utc("2026-08-30T14:03:11Z").tzinfo is not None)
        check("parse_iso_utc: זבל -> None", parse_iso_utc("לא תאריך"), None)
        check("utc_now_iso: מסתיים ב-Z", utc_now_iso().endswith("Z"), True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return problems


if __name__ == "__main__":
    # הדפסת עברית ב-Windows דורשת utf-8 מפורש; עטוף ב-try כי לא כל זרם פלט
    # ניתן להגדרה מחדש.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")
    print("בדיקה עצמית של src/store.py (self-check)")
    issues = self_check(verbose=True)
    print()
    if issues:
        print(f"נמצאו {len(issues)} בעיות (self-check FAILED):")
        for issue in issues:
            print("  - " + issue)
        raise SystemExit(1)
    print("כל הבדיקות עברו (self-check OK).")
    raise SystemExit(0)
