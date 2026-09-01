"""
refresh.py — עבודת הריענון המתוזמנת של מסד הנתונים. (the scheduled refresh job)

מה זה
-----
זו התשובה הישירה לדרישה השנייה של הסטודנט/ית:

    "סקריפט שמקבל את הנתונים ישירות מתחנת המידע הרשמית, מוציא אותם למכל JSON,
     וכך הם יתעדכנו פעם ביום במסד הנתונים של המערכת."

הסקריפט מריץ *מעבר ריענון אחד*: מוודא את שנת הלימודים, מושך את קטלוג הקורסים
המלא (בקשה אחת אחת! GROUND_TRUTH/SPEC_AUTOREFRESH), ואז מרענן את דפי הקבוצות
של הקורסים שבמעקב — רק את אלה שהתיישנו. כל שינוי שמתגלה (מרצה שהוחלף, שעה
שזזה, קבוצה שנוספה או בוטלה) מודפס בקול ונרשם ביומן.

הרצה
----
    python refresh.py                 # ריענון אחד, ישירות ב-HTTP. בלי דפדפן, בלי התחברות.
    python refresh.py --browser       # מסלול הגיבוי הישן דרך Playwright (דורש התחברות)
    python refresh.py --browser --headful   # דפדפן עם חלון גלוי, כדי להתחבר ידנית
    python refresh.py --status        # מצב המסד: טריות, ריצה אחרונה, שינויים. בלי רשת בכלל
    python refresh.py --codes 61753,61756
    python refresh.py --catalog-only  # רק הקטלוג, בלי דפי הקבוצות
    python refresh.py --max-age 12    # לרענן רק מה שישן מ-12 שעות
    python refresh.py --install-task   /  --uninstall-task

שני מסלולי שליפה (two fetch paths)
-----------------------------------
**ברירת המחדל: HTTP ישיר.** ``src/yedion_http.py``, ספריית התקן בלבד
(``urllib.request`` + ``http.cookiejar``). חיפוש הקורסים בידיעון פתוח לקריאה
לכל אחד: ``S_LOOK_FOR_NOSE`` ו-``S_LOOK_FOR_NOSE_AB`` נענים בלי שום הזדהות.
רק ``Enter_Search`` חסום מאחורי שער Citrix — ובו אין לנו צורך.
(GROUND_TRUTH סעיף 9, אומת מול האתר החי: שישה קורסים, התאמה 6/6.)
לכן הריצה היומית אוטומטית באמת: בלי חלון, בלי סיסמה, בלי שאף אחד יתערב.

**גיבוי: ‎--browser.** המסלול הישן דרך Playwright, נשמר כמו שהוא ליום שבו
המכללה תסגור גם את נקודות הקצה האלה. **רק הוא** דורש התחברות ידנית, ורק בו
קיים המצב ``needs_login``. כשהסשן שלו פג (מקרה רגיל, לא באג): לא מנסים
להתחבר, לא שומרים ולא מצלמים את דף ההתחברות, הנתונים הקיימים לא נגעים,
ביומן נרשם ``needs_login`` וקוד היציאה הוא 2.
**לעולם לא מציגים נתונים ישנים כאילו הם עדכניים.**

קודי יציאה (exit codes — המתזמן קורא אותם)
-------------------------------------------
    0  רוענן בהצלחה, או שהכול היה טרי ולא היה מה לעשות
    2  נדרשת התחברות מחדש — **רק במסלול ‎--browser** (NEEDS LOGIN)
    3  ריענון חלקי — חלק מהקורסים נכשלו
    1  תקלה לא צפויה

מה נשאר בדיוק כמו שהיה
-----------------------
  * שנת הלימודים מאומתת בכל דף. שנה שגויה = עצירה, בלי לכתוב כלום.
  * שומרים HTML גולמי לפני כל פענוח.
  * שליפה שנכשלה לא הורסת נתונים קיימים — הישנים נשמרים עם ok=False.
  * נימוס כלפי השרת: השהיה בין בקשות, מרעננים רק מה שהתיישן, והקטלוג
    נשלף בבקשה **אחת** ולא אות-אות. עכשיו זה חשוב יותר, לא פחות: אין
    התחברות שמאטה אותנו, ולכן אנחנו מאטים את עצמנו.

Security note (hard rule): this script never asks for, reads, stores or logs
credentials, and never writes a non-info.braude.ac.il page or screenshot to
disk. The default HTTP path has no credentials to touch at all; the --browser
path stops and says so when its session is gone.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import html as html_lib
import json
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

# ---------------------------------------------------------------------------
# עברית ב-Windows: מכריחים UTF-8 על הפלט. עטוף — יש מסופים/צינורות שאי אפשר
# להגדיר מחדש, וזה בסדר גמור. (guarded, per the project rules)
# ---------------------------------------------------------------------------
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 - best-effort only
        pass

# ---------------------------------------------------------------------------
# נתיבים — נפתרים תמיד מול שורש הפרויקט ולא מול תיקיית ההרצה.
# זה קריטי דווקא כאן: Task Scheduler מריץ משימות עם cwd של C:\Windows\System32,
# ולכן כל נתיב יחסי היה נשבר בריצה היומית.
# (Every path is anchored to the project root — the daily task runs with a
#  completely different working directory.)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

PROFILE_PATH = PROJECT_ROOT / "data" / "profile.json"
CURRICULUM_PATH = PROJECT_ROOT / "data" / "curriculum.json"
DB_ROOT = PROJECT_ROOT / "data" / "db"
BROWSER_PROFILE_DIR = PROJECT_ROOT / "data" / ".browser_profile"
RAW_DIR = PROJECT_ROOT / "data" / "raw"

# ---------------------------------------------------------------------------
# קודי יציאה — החוזה מול המתזמן. (exit codes: the scheduler's contract)
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEEDS_LOGIN = 2
EXIT_PARTIAL = 3

# ---------------------------------------------------------------------------
# סטטוסים שנרשמים ביומן הריענון (refresh_log.jsonl)
# ---------------------------------------------------------------------------
STATUS_OK = "ok"
STATUS_FRESH = "fresh"              # לא היה מה לרענן
STATUS_PARTIAL = "partial"
STATUS_NEEDS_LOGIN = "needs_login"  # הסשן פג — המקרה ה"רגיל" של ריצה יומית
STATUS_YEAR_ERROR = "year_error"    # לא אושרה שנת הלימודים — לא נכתב כלום
STATUS_ERROR = "error"

# ---------------------------------------------------------------------------
# קבועים תפעוליים
# ---------------------------------------------------------------------------
#: השהיה בין שליפת קורס לקורס — נימוס כלפי השרת של המכללה. GROUND_TRUTH/SPEC.
POLITE_DELAY_S = 1.5

#: השהיה בין בקשה לבקשה במסלול ה-HTTP. מועברת גם ל-YedionHTTP וגם נאכפת כאן.
#: אם הפצ'ר כבר מאט את עצמו נקבל פער כפול — וזה בסדר גמור: להיות שנייה
#: איטיים מדי לא עולה כלום, להיות מהירים מדי עולה לשרת של המכללה.
#: (politeness matters MORE now that no login throttles us — GROUND_TRUTH §9)
HTTP_DELAY_S = 1.2

#: פסק זמן לבקשת HTTP בודדת, בשניות.
HTTP_TIMEOUT_S = 45.0

#: סף התיישנות ברירת מחדל, בשעות.
#: למה 20 ולא 24? כי המשימה היומית רצה בשעה קבועה, ואז גיל הנתונים בכל ריצה
#: הוא בדיוק ~24 שעות — ממש על הגבול. סף של 20 שעות מבטיח שהריצה היומית באמת
#: תרענן, במקום להחליט "עדיין טרי" בגלל הפרש של כמה שניות.
#: (store.DEFAULT_MAX_AGE_HOURS הוא 24.0 — זה ברירת המחדל של המסד, לא של הג'וב.)
DEFAULT_MAX_AGE_HOURS = 20.0

#: שם המשימה ב-Task Scheduler. חייב להישאר יציב — --uninstall-task מחפש אותו.
TASK_NAME = "BraudeScheduleRefresh"
DEFAULT_TASK_TIME = "07:00"

#: כמה זמן לחכות להתחברות ידנית במצב --headful (שניות).
LOGIN_TIMEOUT_S = 600

#: כמה ימים אחורה נספרים השינויים ב---status.
CHANGES_WINDOW_DAYS = 7

#: תוצאות הבדיקה השקטה של הסשן.
PROBE_OK = "ok"
PROBE_NEEDS_LOGIN = "needs_login"
PROBE_NETWORK = "network"


# ===========================================================================
# 0. עזרי הדפסה, זמן וגיל
# ===========================================================================
def log(message: str) -> None:
    """הדפסה עם קידומת אחידה, כדי שקל יהיה לסנן את הפלט של הג'וב."""
    print(f"[refresh] {message}", flush=True)


def banner(lines: list[str], ch: str = "=") -> str:
    """מסגרת טקסט פשוטה.

    בכוונה בלי ריפוד לרוחב: יישור של טקסט עברי (RTL) בתוך מסגרת ASCII יוצא
    שבור במסופים שונים, ושורה נקייה עדיפה על יישור "כמעט נכון".
    """
    rule = ch * 74
    body = "\n".join("  " + line if line else "" for line in lines)
    return f"\n{rule}\n{body}\n{rule}"


def now_utc() -> datetime:
    """הזמן הנוכחי — תמיד מודע לאזור זמן, לעולם לא naive. (rule 8)"""
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime | None = None) -> str:
    """ISO-8601 עם Z בסוף: '2026-08-30T14:03:11Z'."""
    dt = dt or now_utc()
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: object) -> datetime | None:
    """קורא חותמת זמן ISO-8601 (עם Z או עם היסט) ומחזיר datetime ב-UTC.

    סלחני בכוונה: חותמות שנכתבו על ידי גרסאות שונות של הכלי, או ביד, לא
    צריכות להפיל דוח מצב.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        # חותמת בלי אזור זמן — מניחים UTC, כי ככה הכלי הזה כותב.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def age_hours(value: object) -> float | None:
    """גיל בשעות של חותמת זמן, או None אם היא לא קריאה."""
    dt = parse_iso(value)
    if dt is None:
        return None
    return max(0.0, (now_utc() - dt).total_seconds() / 3600.0)


def human_age(hours: float | None) -> str:
    """גיל קריא בעברית: 'לפני 3 שעות', 'לפני יומיים', 'ממש עכשיו'.

    שימו לב לצורות הזוגי בעברית: "שעתיים" (נקבה), "יומיים" (זכר),
    "שתי דקות". ניסוח נייטרלי — אין כאן שום פנייה למישהו/מישהי.
    """
    if hours is None:
        return "לא ידוע"
    hours = max(0.0, float(hours))
    minutes = int(round(hours * 60))
    if minutes < 1:
        return "ממש עכשיו"
    if minutes < 60:
        if minutes == 1:
            return "לפני דקה"
        if minutes == 2:
            return "לפני שתי דקות"
        return f"לפני {minutes} דקות"
    whole_hours = int(hours)
    if whole_hours < 24:
        if whole_hours == 1:
            return "לפני שעה"
        if whole_hours == 2:
            return "לפני שעתיים"
        return f"לפני {whole_hours} שעות"
    days = whole_hours // 24
    if days == 1:
        return "לפני יום"
    if days == 2:
        return "לפני יומיים"
    return f"לפני {days} ימים"


def local_stamp(value: object) -> str:
    """חותמת UTC -> תצוגה בשעון מקומי: '2026-08-30 07:00'.

    הסטודנט/ית קורא/ת שעון מקומי, לא UTC. הנתונים *נשמרים* ב-UTC (כלל 8)
    ורק התצוגה מומרת.
    """
    dt = parse_iso(value)
    if dt is None:
        return "לא ידוע"
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


_FINAL_LETTERS = str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"})


def normalize_year_label(text: object) -> str:
    """מנרמל תווית שנה עברית להשוואה: 'תשפ"ז' / 'תשפ&quot;ז' -> 'תשפז'."""
    raw = html_lib.unescape(str(text or ""))
    letters = "".join(ch for ch in raw if ch.isalpha())
    return letters.translate(_FINAL_LETTERS)


def sha1_of(text: str) -> str:
    """טביעת אצבע של ה-HTML הגולמי — מפתח זיהוי השינויים של המסד."""
    return hashlib.sha1(str(text).encode("utf-8", errors="replace")).hexdigest()


def truncate(text: str, width: int) -> str:
    """קיצור לתצוגה בטבלה, עם … בסוף."""
    text = str(text or "")
    return text if len(text) <= width else text[: width - 1] + "…"


#: גימטריה לחישוב תווית שנה עברית. מראה של ``scraper.hebrew_year_label``,
#: מועתק לכאן בכוונה: המסלול הרגיל לא נוגע ב-scraper (ולכן גם לא ב-playwright),
#: ובכל זאת צריך לדעת שביקשנו תשפ"ז כדי לאמת את הדף שחזר.
_GEMATRIA: tuple[tuple[int, str], ...] = (
    (400, "ת"), (300, "ש"), (200, "ר"), (100, "ק"),
    (90, "צ"), (80, "פ"), (70, "ע"), (60, "ס"), (50, "נ"),
    (40, "מ"), (30, "ל"), (20, "כ"), (10, "י"),
    (9, "ט"), (8, "ח"), (7, "ז"), (6, "ו"), (5, "ה"),
    (4, "ד"), (3, "ג"), (2, "ב"), (1, "א"),
)

#: הפרש השנים בין הלוח העברי ללועזי, לשנה שמסתיימת באותה שנה לועזית:
#: תשפ"ז = 5787, ו-5787 - 3760 = 2027.
_HEBREW_YEAR_OFFSET = 3760


def hebrew_year_label(gregorian: str | int) -> str:
    """‏2027 -> 'תשפ"ז'. מחזיר "" אם הקלט אינו שנה סבירה."""
    try:
        number = int(str(gregorian).strip())
    except (TypeError, ValueError):
        return ""
    if not (1900 <= number <= 2200):
        return ""

    remainder = (number + _HEBREW_YEAR_OFFSET) % 1000  # את ה"ה' אלפים" לא כותבים
    letters = ""
    for value, ch in _GEMATRIA:
        while remainder >= value:
            letters += ch
            remainder -= value
    # 15 ו-16 נכתבים טו/טז ולא יה/יו.
    letters = letters.replace("יה", "טו").replace("יו", "טז")
    if len(letters) >= 2:
        return letters[:-1] + '"' + letters[-1]
    return letters + "'" if letters else ""


def is_year_problem(exc: BaseException) -> bool:
    """האם התקלה הזאת היא 'הדף חזר עם שנה אחרת'?

    שנה שגויה היא כשל **גלובלי**, לא כשל של קורס בודד: אם הסשן יושב על
    השנה הלא נכונה, גם כל שאר הדפים יחזרו שגויים. לכן מזהים אותה ועוצרים,
    במקום לסמן שישה קורסים ככושלים. במסלול ה-HTTP זה כמעט תמיד סימן שבקשת
    החימום לא תפסה (GROUND_TRUTH סעיף 9).
    """
    if type(exc).__name__ in ("YearMismatchError", "YearSwitchError"):
        return True
    text = str(exc)
    return "wrong academic year" in text or "מצהיר על שנת" in text


def looks_like_network(exc: BaseException) -> bool:
    """האם התקלה היא 'לא הצלחנו להגיע לשרת' ולא באג אצלנו?

    ההבחנה חשובה: 'אין אינטרנט' ו'משהו שבור בקוד' דורשים פעולות שונות
    לגמרי מהסטודנט/ית.
    """
    if isinstance(exc, OSError):  # URLError, HTTPError, TimeoutError — כולם יורדים מכאן
        return True
    name = type(exc).__name__.lower()
    return any(marker in name for marker in ("url", "http", "network", "timeout", "socket", "fetch"))


# ===========================================================================
# 1. ייבוא מודולי המסד — עם הודעה ידידותית אם הם עדיין לא קיימים
# ===========================================================================
class MissingModule(RuntimeError):
    """מודול פנימי חסר — נזרק עם הסבר, לא עם traceback."""


def import_store():
    """מייבא את src/store.py (מסד ה-JSON)."""
    try:
        import store  # type: ignore
    except ImportError as exc:
        raise MissingModule(
            "המודול src/store.py לא נמצא או לא נטען, ובלעדיו אין מסד נתונים לרענן.\n"
            f"    ({type(exc).__name__}: {exc})\n"
            "    (src/store.py is missing — the JSON database layer)"
        ) from exc
    return store


def import_discovery():
    """מייבא את src/discovery.py (קטלוג הקורסים)."""
    try:
        import discovery  # type: ignore
    except ImportError as exc:
        raise MissingModule(
            "המודול src/discovery.py לא נמצא או לא נטען, ובלעדיו אי אפשר לקרוא את קטלוג הקורסים.\n"
            f"    ({type(exc).__name__}: {exc})\n"
            "    (src/discovery.py is missing — the catalog reader)"
        ) from exc
    return discovery


def import_scraper():
    """מייבא את src/scraper.py — **רק למסלול ‎--browser**. מיובא בעצלתיים
    בכוונה: הוא מושך את playwright, והמסלול הרגיל (וגם --status) חייבים
    לעבוד גם במחשב שאין בו דפדפן מותקן בכלל."""
    try:
        import scraper  # type: ignore
    except ImportError as exc:
        raise MissingModule(
            "לא הצלחתי לטעון את src/scraper.py. אולי playwright לא מותקן?\n"
            "    יש להריץ:  python -m pip install playwright  ואחר כך  python -m playwright install chromium\n"
            "    (או פשוט להריץ בלי --browser — המסלול הרגיל לא צריך דפדפן בכלל.)\n"
            f"    ({type(exc).__name__}: {exc})"
        ) from exc
    return scraper


def import_yedion_http():
    """מייבא את src/yedion_http.py — השולף הרגיל, ספריית תקן בלבד.

    זה המודול שמאפשר ריענון בלי התחברות ובלי דפדפן (GROUND_TRUTH סעיף 9).
    """
    try:
        import yedion_http  # type: ignore
    except ImportError as exc:
        raise MissingModule(
            "המודול src/yedion_http.py לא נמצא או לא נטען, והוא השולף הרגיל של הכלי.\n"
            f"    ({type(exc).__name__}: {exc})\n"
            "    כגיבוי אפשר להריץ דרך הדפדפן:  python refresh.py --browser --headful\n"
            "    (src/yedion_http.py is missing — the login-free HTTP fetcher)"
        ) from exc
    return yedion_http


# ===========================================================================
# 2. הפרופיל — שנה, סמסטר וקודי הקורסים של הסטודנט/ית
# ===========================================================================
def load_profile(path: Path = PROFILE_PATH) -> dict:
    """קורא את data/profile.json. מחזיר מילון ריק אם אין קובץ — לא מפיל ריצה."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        log(f"אזהרה: לא נמצא קובץ פרופיל ב-{path} — ממשיכים עם ברירות מחדל.")
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        log(f"אזהרה: קובץ הפרופיל לא נקרא ({type(exc).__name__}: {exc}) — ברירות מחדל.")
        return {}


def profile_year(profile: dict) -> str:
    """'2026/27' -> '2027' — השנה הלועזית שהידיעון מכיר ב-<option value>.

    ברירת מחדל 2027 (תשפ"ז), השנה שהכלי הזה נבנה עבורה. אף פעם לא משאירים
    את הידיעון על ברירת המחדל שלו — היא שנה אחורה. GROUND_TRUTH סעיף 8.
    """
    raw = str((profile.get("student") or {}).get("academic_year_gregorian", "")).strip()
    numbers = re.findall(r"\d{2,4}", raw)
    if numbers:
        last = numbers[-1]
        if len(last) == 4:
            return last
        if len(last) == 2 and len(numbers[0]) == 4:
            # '2026/27' -> מחברים את שתי הספרות לקידומת המאה של החלק הראשון.
            return numbers[0][:2] + last
    return "2027"


def profile_semester(profile: dict) -> str:
    """הסמסטר המבוקש: 'א' / 'ב' / 'קיץ'. ריק = בלי סינון."""
    term = str((profile.get("student") or {}).get("term", "")).strip()
    try:
        import parser as parser_mod  # type: ignore

        return parser_mod.normalize_semester(term)
    except Exception:  # noqa: BLE001 - הפרסר הוא נוחות, לא תלות קשיחה
        return term


def profile_codes(profile: dict) -> list[str]:
    """קודי הקורסים מהפרופיל — קודם scrape_codes, אחרת selected_courses."""
    codes: list[str] = []
    for code in profile.get("scrape_codes") or []:
        code = str(code).strip()
        if code and code not in codes:
            codes.append(code)
    if codes:
        return codes
    for item in profile.get("selected_courses") or []:
        code = str((item or {}).get("code", "")).strip()
        if code and code not in codes:
            codes.append(code)
    return codes


def split_codes(raw: str | None) -> list[str]:
    """'61753, 61756  62027' -> ['61753','61756','62027'] (ללא כפילויות, לפי הסדר)."""
    if not raw:
        return []
    parts = re.split(r"[,\s;]+", str(raw))
    out: list[str] = []
    for part in parts:
        code = part.strip()
        if code and code not in out:
            out.append(code)
    return out


# ===========================================================================
# 3. עזרי מסד — בנייה סלחנית של CourseMeta וקריאת יומן השינויים
# ===========================================================================
def build_course_meta(store_mod, **values):
    """בונה ``store.CourseMeta`` ומעביר רק שדות שקיימים בו בפועל.

    למה הסינון: ``store.py`` הוא קובץ של סוכן אחר. אם יתווסף לו שדה
    (למשל ``attempted_at``) או יוסר אחד — הג'וב הזה לא צריך להישבר. מעבירים
    את מה שהדאטהקלאס באמת מכריז עליו, ולא יותר.
    """
    try:
        names = {f.name for f in dataclasses.fields(store_mod.CourseMeta)}
    except TypeError:  # לא dataclass? נעביר הכול ונקווה לטוב.
        names = set(values)
    kwargs = {key: val for key, val in values.items() if key in names}
    return store_mod.CourseMeta(**kwargs)


def meta_field(meta: object, name: str, default=None):
    """קריאת שדה מ-CourseMeta בלי להניח שהוא קיים."""
    if meta is None:
        return default
    return getattr(meta, name, default)


def read_recent_changes(store_obj, days: int = CHANGES_WINDOW_DAYS) -> tuple[int, list[str]]:
    """סופר את השינויים שנרשמו ב-N הימים האחרונים ומחזיר גם דוגמאות.

    מעדיף עוזר מובנה של ה-Store אם קיים; אחרת קורא את ``changes.jsonl`` ישירות.
    הקריאה סלחנית בכוונה — שורה פגומה ביומן לא תפיל דוח מצב.

    Returns:
        (count, samples) — הדוגמאות מהחדשות לישנות.
    """
    helper = getattr(store_obj, "recent_changes", None)
    if callable(helper):
        try:
            rows = list(helper(days))  # type: ignore[misc]
            texts = [str(r) for r in rows]
            return len(texts), texts[:8]
        except Exception:  # noqa: BLE001 - נופלים לקריאה הידנית
            pass

    path = DB_ROOT / "changes.jsonl"
    if not path.exists():
        return 0, []

    cutoff = now_utc() - timedelta(days=days)
    count = 0
    samples: list[str] = []
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return 0, []

    # מהסוף להתחלה: השורות האחרונות הן החדשות ביותר.
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue

        # חותמת הזמן — שמות אפשריים שונים, כי היומן נכתב על ידי מודול אחר.
        stamp = None
        for key in ("ts", "timestamp", "at", "time", "detected_at", "when", "fetched_at"):
            if record.get(key):
                stamp = parse_iso(record[key])
                if stamp is not None:
                    break
        if stamp is not None and stamp < cutoff:
            continue

        code = str(record.get("code") or record.get("course") or "").strip()
        texts: list[str] = []
        raw_changes = record.get("changes")
        if isinstance(raw_changes, list):
            texts = [str(c) for c in raw_changes if str(c).strip()]
        else:
            for key in ("change", "text", "description", "message", "detail"):
                if record.get(key):
                    texts = [str(record[key])]
                    break
        if not texts:
            continue

        count += len(texts)
        for text in texts:
            if len(samples) < 8:
                samples.append(format_change(code, text))
    return count, samples


def format_change(code: str, text: str) -> str:
    """'61753: קבוצה 21 — המרצה השתנה…' — בלי לכפול את הקוד אם הוא כבר שם."""
    body = str(text).strip()
    code = str(code or "").strip()
    if not code or body.startswith(f"{code}:") or body.startswith(f"{code} "):
        return body
    return f"{code}: {body}"


# ===========================================================================
# 4. --status : דוח מצב, בלי שום פנייה לרשת
# ===========================================================================
def cmd_status(args: argparse.Namespace) -> int:
    """מדפיס את מצב מסד הנתונים. **אפס רשת** — רק קריאה מהדיסק."""
    store_mod = import_store()
    store_obj = store_mod.Store(str(DB_ROOT))
    profile = load_profile()
    max_age = float(args.max_age)

    schema = getattr(store_mod, "SCHEMA_VERSION", "?")
    print(
        banner(
            [
                "מצב מסד הנתונים — DATABASE STATUS",
                "",
                f"תיקייה (folder): {DB_ROOT}",
                f"גרסת סכימה (schema version): {schema}",
                f"סף התיישנות בדוח הזה (staleness threshold): {max_age:g} שעות",
                "לא בוצעה שום פנייה לרשת. (no network was used)",
            ]
        )
    )

    # ------------------------------------------------------------------ קטלוג
    print("\nקטלוג הקורסים (catalog)")
    try:
        catalog, catalog_meta = store_obj.load_catalog()
    except Exception as exc:  # noqa: BLE001 - דוח מצב לא נופל בגלל קובץ פגום
        catalog, catalog_meta = {}, {}
        print(f"  שגיאה בקריאת הקטלוג: {type(exc).__name__}: {exc}")

    if catalog:
        cat_age = None
        try:
            cat_age = store_obj.catalog_age_hours()
        except Exception:  # noqa: BLE001
            cat_age = None
        meta = catalog_meta if isinstance(catalog_meta, dict) else {}
        fetched = meta.get("fetched_at") or meta.get("updated_at") or ""
        if cat_age is None:
            cat_age = age_hours(fetched)
        year = meta.get("year") or "?"
        year_greg = meta.get("year_gregorian") or "?"
        print(f"  {len(catalog)} קורסים | שנה: {year} ({year_greg})")
        print(f"  עודכן: {local_stamp(fetched)} ({human_age(cat_age)})")
        if cat_age is not None and cat_age > max_age:
            print("  ** הקטלוג ישן. יש להריץ ריענון. (the catalog is stale) **")
    else:
        print("  אין קטלוג שמור. יש להריץ:  python refresh.py")

    # ------------------------------------------------- קורסים במעקב + טריות
    tracked = list(store_obj.tracked())
    if not tracked:
        tracked = profile_codes(profile)
        if tracked:
            print("\n(אין עדיין רשימת מעקב שמורה — מוצגים הקורסים מהפרופיל.)")

    print(f"\nקורסים במעקב (tracked courses): {len(tracked)}")
    if not tracked:
        print("  הרשימה ריקה. ריצה רגילה של refresh.py תאכלס אותה מהפרופיל.")
    else:
        header = f"  {'קוד':<8}{'מצב':<22}{'גיל':<18}{'קב׳':<6}שם"
        print(header)
        print("  " + "-" * 70)
        for code in tracked:
            meta = None
            try:
                meta = store_obj.course_meta(code)
            except Exception:  # noqa: BLE001
                meta = None

            name = ""
            entry = catalog.get(code) if isinstance(catalog, dict) else None
            if isinstance(entry, dict):
                name = str(entry.get("name") or "")
            if not name:
                try:
                    course, _ = store_obj.load_course(code)
                    name = getattr(course, "name", "") or ""
                except Exception:  # noqa: BLE001
                    name = ""

            if meta is None:
                state, age_text = "לא נשלף מעולם", "—"
                groups = "—"
            else:
                fetched = meta_field(meta, "fetched_at", "")
                age_text = human_age(age_hours(fetched))
                groups = str(meta_field(meta, "group_count", "?"))
                if not meta_field(meta, "ok", True):
                    state = "השליפה נכשלה"
                else:
                    try:
                        stale = store_obj.is_stale(code, max_age)
                    except Exception:  # noqa: BLE001
                        stale = False
                    state = "ישן — כדאי לרענן" if stale else "עדכני"
            print(f"  {code:<8}{state:<22}{age_text:<18}{groups:<6}{truncate(name, 34)}")
        print("  " + "-" * 70)
        print("  מקרא: עדכני = נשלף לאחרונה | ישן = עבר הסף | השליפה נכשלה = הנתונים הקודמים נשמרו")

    # ------------------------------------------------------------ ריצה אחרונה
    print("\nריצה אחרונה (last refresh)")
    last = None
    try:
        last = store_obj.last_refresh()
    except Exception as exc:  # noqa: BLE001
        print(f"  לא הצלחתי לקרוא את היומן: {type(exc).__name__}: {exc}")
    if not last:
        print("  אין עדיין רישום ריצה. (never run)")
    else:
        started = last.get("started_at") or last.get("finished_at") or ""
        status = str(last.get("status") or "?")
        print(f"  {local_stamp(started)} ({human_age(age_hours(started))}) | סטטוס: {status}")
        refreshed = last.get("refreshed") or []
        failed = last.get("failed") or []
        print(
            f"  עודכנו: {len(refreshed)} | נכשלו: {len(failed)} | "
            f"שינויים: {last.get('changes_count', 0)} | קוד יציאה: {last.get('exit_code', '?')}"
        )
        if last.get("reason"):
            print(f"  סיבה: {last['reason']}")
        if status == STATUS_NEEDS_LOGIN:
            print(
                banner(
                    [
                        "הריצה האחרונה הייתה במסלול --browser, והיא נעצרה כי הסשן פג.",
                        "The last run used the --browser path; its session expired.",
                        "",
                        "המסלול הרגיל לא דורש התחברות בכלל — אפשר פשוט להריץ:",
                        "    python refresh.py",
                        "",
                        "ואם בכל זאת צריך דווקא את מסלול הדפדפן:",
                        "    python refresh.py --browser --headful",
                        "ולהתחבר בחלון הדפדפן שנפתח. אין להקליד סיסמאות בשום מקום אחר.",
                    ],
                    ch="!",
                )
            )

    # -------------------------------------------------------- שינויים אחרונים
    count, samples = read_recent_changes(store_obj, CHANGES_WINDOW_DAYS)
    print(f"\nשינויים ב-{CHANGES_WINDOW_DAYS} הימים האחרונים (changes in the last {CHANGES_WINDOW_DAYS} days): {count}")
    for text in samples:
        print(f"  • {text}")
    if count > len(samples):
        print(f"  … ועוד {count - len(samples)} (ראו data/db/changes.jsonl)")

    # ----------------------------------------------------- המגבלה, בגלוי
    print(
        banner(
            [
                "איך הנתונים מתעדכנים — HOW THE DATA IS REFRESHED",
                "",
                "ברירת המחדל שולפת מהידיעון ישירות ב-HTTP: חיפוש הקורסים שם פתוח",
                "לקריאה לכל אחד, בלי הזדהות. לכן הריענון היומי רץ לבד — בלי חלון,",
                "בלי דפדפן ובלי שאף אחד יתחבר. (unattended: no login, no browser)",
                "",
                "המסלול החלופי  --browser  עדיין עובר דרך שער ההתחברות (Citrix),",
                "והסשן שלו פג מדי כמה ימים. הוא שמור כגיבוי בלבד, ורק הוא דורש",
                "התחברות ידנית. (only --browser has that limitation)",
                "",
                "ובכל מקרה: התאריך שליד כל שורה כאן הוא התאריך האמיתי של הנתונים.",
                "אין להתייחס אליהם כאל מה שמופיע בידיעון *כרגע*.",
                "The stored data is only as current as the timestamps above.",
                "Nothing here is ever presented as live data.",
            ],
            ch="-",
        )
    )
    return EXIT_OK


# ===========================================================================
# 5. ריענון — הזרימה המלאה
# ===========================================================================
class SessionExpired(RuntimeError):
    """הסשן פג. מקרה רגיל לגמרי בריצה יומית, לא באג."""


class NetworkTrouble(RuntimeError):
    """הדפדפן לא הצליח להגיע לשרת — תקלת רשת, לא בעיית הרשאה."""


def probe_session(scraper_obj, scraper_mod) -> tuple[str, str]:
    """בדיקה שקטה: האם הסשן השמור עדיין תקף?

    נפתחת **לשונית זמנית** ולא משתמשים בלשונית העבודה — כדי לא לנווט בטעות
    דף שבו מוקלדים כרגע פרטי התחברות (זו בדיוק הסיבה ש-scraper עושה את זה
    ככה). אם הסשן תקף, הלשונית הזאת מאומצת כלשונית העבודה — היא כבר עומדת
    על דף החיפוש.

    ההבחנה החשובה כאן: **תקלת רשת אינה פקיעת סשן**. לומר לסטודנט/ית
    "צריך להתחבר" כשפשוט אין אינטרנט זו הודעה שגויה, ולכן מפרידים ביניהן.

    Returns:
        (PROBE_OK | PROBE_NEEDS_LOGIN | PROBE_NETWORK, פרטים לתצוגה)
    """
    from playwright.sync_api import Error as PlaywrightError  # ייבוא עצל

    context = getattr(scraper_obj, "context", None)
    if context is None:
        return PROBE_NETWORK, "הדפדפן לא נפתח"

    probe = None
    try:
        probe = context.new_page()
        probe.goto(
            scraper_mod.SEARCH_URL,
            wait_until="domcontentloaded",
            timeout=getattr(scraper_mod, "NAV_TIMEOUT_MS", 45_000),
        )
    except PlaywrightError as exc:
        if probe is not None:
            try:
                probe.close()
            except PlaywrightError:
                pass
        return PROBE_NETWORK, f"{type(exc).__name__}: {exc}"

    landed_ok = scraper_mod.is_success_url(probe.url)
    if landed_ok:
        scraper_obj.page = probe  # מאמצים את הלשונית שכבר על דף החיפוש
        settle = getattr(scraper_obj, "_wait_for_settle", None)
        if callable(settle):
            try:
                settle()
            except Exception:  # noqa: BLE001 - התייצבות היא נוחות בלבד
                pass
        return PROBE_OK, ""

    # הופנינו לשער ההתחברות. **לא שומרים ולא מצלמים את הדף הזה, לעולם.**
    # מדווחים שם מארח בלבד — בלי URL מלא, שעלול להכיל טוקנים.
    host = ""
    try:
        host = scraper_mod._host_of(probe.url)  # noqa: SLF001 - עזר קריאה בלבד
    except Exception:  # noqa: BLE001
        host = "שער ההתחברות"
    try:
        probe.close()
    except PlaywrightError:
        pass
    return PROBE_NEEDS_LOGIN, host


def newest_data_stamp(store_obj, codes: list[str]) -> str:
    """החותמת החדשה ביותר מבין הקטלוג והקורסים — 'הנתונים שלנו הם מ…'."""
    stamps: list[datetime] = []
    try:
        _, catalog_meta = store_obj.load_catalog()
        if isinstance(catalog_meta, dict):
            dt = parse_iso(catalog_meta.get("fetched_at") or catalog_meta.get("updated_at"))
            if dt:
                stamps.append(dt)
    except Exception:  # noqa: BLE001
        pass
    for code in codes:
        try:
            meta = store_obj.course_meta(code)
        except Exception:  # noqa: BLE001
            continue
        dt = parse_iso(meta_field(meta, "fetched_at", ""))
        if dt:
            stamps.append(dt)
    if not stamps:
        return ""
    return iso_utc(max(stamps))


def print_needs_login(store_obj, codes: list[str]) -> None:
    """ההודעה שהסטודנט/ית רואה כשהסשן של ‎--browser פג. דו-לשונית, ובלי לטשטש כלום.

    שייכת **אך ורק** למסלול הדפדפן. במסלול הרגיל אין סשן, אין התחברות, ולכן
    אין מצב כזה בכלל. (SPEC_V2 §3 — exit code 2 is a --browser-only path)
    """
    stamp = newest_data_stamp(store_obj, codes)
    if stamp:
        when = f"{local_stamp(stamp)} ({human_age(age_hours(stamp))})"
        data_line_he = f"הנתונים השמורים הם מ-{when} — הם אינם בהכרח מה שמופיע בידיעון כרגע."
        data_line_en = f"The stored data is from {when}. It is NOT current."
    else:
        data_line_he = "אין עדיין נתונים שמורים בכלל."
        data_line_en = "There is no stored data yet."

    print(
        banner(
            [
                "נדרשת התחברות לידיעון במסלול הדפדפן — SIGN-IN NEEDED (--browser)",
                "",
                "ההודעה הזאת שייכת אך ורק למסלול --browser: הסשן השמור שלו פג,",
                "וההזדהות מחדש היא ידנית מעצם טבעה. זה מצב רגיל, לא באג.",
                "This applies only to the --browser path; its saved session expired.",
                "",
                "**המסלול הרגיל אינו דורש התחברות בכלל.** אפשר פשוט להריץ:",
                "    python refresh.py",
                "",
                "לא בוצע שום עדכון, והנתונים הקיימים לא נגעו בהם.",
                "Nothing was updated; the existing data was left untouched.",
                "",
                data_line_he,
                data_line_en,
                "",
                "כדי להמשיך דווקא במסלול הדפדפן יש להריץ במסוף:",
                "    python refresh.py --browser --headful",
                "(או  python main.py  — גם הוא פותח חלון התחברות)",
                "",
                "ואז להקליד את פרטי ההתחברות **בחלון הדפדפן בלבד**.",
                "הסקריפט הזה לא מבקש, לא רואה ולא שומר סיסמאות — לעולם.",
                "This script never asks for, sees or stores credentials.",
            ],
            ch="!",
        )
    )


def browser_fetch_catalog_html(scraper_obj, scraper_mod, discovery_mod) -> str:
    """מביא את דף הקטלוג המלא דרך הדפדפן — **בקשה אחת** לכל הקורסים.

    ``S_LOOK_FOR_NOSE_AB&arguments=-A`` מחזיר את כל הקורסים של השנה שנבחרה
    בסשן; אות החיפוש מתעלמים ממנה (SPEC_AUTOREFRESH, מאומת). לכן גילוי
    הקטלוג עולה קריאה אחת בלבד ולא אחת לכל אות.
    """
    from playwright.sync_api import Error as PlaywrightError

    page = scraper_obj.page
    url = getattr(discovery_mod, "CATALOG_URL", None)
    if not url:
        raise MissingModule("ל-src/discovery.py אין CATALOG_URL. (discovery.CATALOG_URL missing)")

    log("מביא את קטלוג הקורסים המלא (בקשה אחת)… (fetching the whole catalog)")
    try:
        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=getattr(scraper_mod, "NAV_TIMEOUT_MS", 45_000),
        )
    except PlaywrightError as exc:
        raise NetworkTrouble(f"טעינת הקטלוג נכשלה: {type(exc).__name__}: {exc}") from exc

    if not scraper_mod.is_success_url(page.url):
        # הופנינו להתחברות באמצע. הדף הזה לא נשמר לדיסק בשום מצב.
        raise SessionExpired("הופנינו לשער ההתחברות בזמן שליפת הקטלוג.")

    settle = getattr(scraper_obj, "_wait_for_settle", None)
    if callable(settle):
        try:
            settle()
        except Exception:  # noqa: BLE001
            pass

    html = page.content()
    # חוק ברזל: קודם שומרים גולמי, אחר כך מפרסרים. dump_page עצמו מסרב לכתוב
    # דף שאינו מ-info.braude.ac.il, אז זו הגנה כפולה.
    try:
        scraper_obj.dump_page("catalog")
    except Exception as exc:  # noqa: BLE001 - דמפ הוא נוחות, לא תנאי להצלחה
        log(f"אזהרה: שמירת הדמפ של הקטלוג נכשלה ({type(exc).__name__}: {exc}).")
    return html


def assert_year_on_html(html: str, want_label: str, what: str) -> None:
    """מוודא שדף שנשלף באמת מצהיר על שנת הלימודים המבוקשת.

    שנה שגויה בשקט היא הכשל הגרוע ביותר של הכלי הזה: היא מחזירה מערכת
    אמינה-למראה של שנה אחרת. לכן נכשלים ברעש. GROUND_TRUTH סעיף 8.
    """
    try:
        import parser as parser_mod  # type: ignore

        found = parser_mod.extract_page_year(html)
    except Exception:  # noqa: BLE001 - אם הפרסר לא זמין, אין מה לאמת
        return
    if not found or not want_label:
        return  # אין תווית בדף — אין סתירה, רק היעדר ראיה
    if normalize_year_label(found) != normalize_year_label(want_label):
        raise RuntimeError(
            f"{what}: הדף מצהיר על שנת {found} במקום {want_label}. "
            "הריצה נעצרת כדי שלא ייכתבו נתונים של שנה שגויה. "
            f"(wrong academic year on the {what} page)"
        )


def refresh_one_course(
    backend,
    store_mod,
    store_obj,
    code: str,
    *,
    year_label: str,
    year_greg: str,
    semester: str,
    fallback_name: str,
    fallback_credits: float,
) -> dict:
    """מרענן קורס אחד. מחזיר מילון תוצאה, ולא זורק על כשל "רגיל".

    ``backend`` הוא ``HttpBackend`` (ברירת מחדל) או ``BrowserBackend`` — שניהם
    מציגים את אותן שתי שיטות שצריך כאן: ``fetch_course_html`` ו-``course_url``.

    Returns dict with: ok, changes, warnings, group_count, not_offered, error.
    """
    import parser as parser_mod  # type: ignore

    result = {
        "code": code,
        "ok": False,
        "changes": [],
        "warnings": [],
        "group_count": 0,
        "not_offered": False,
        "error": "",
    }

    html = backend.fetch_course_html(code)  # השולף מאמת בעצמו את שנת הדף
    parsed = parser_mod.parse_course_page(
        html,
        code,
        fallback_name=fallback_name,
        semester=semester or None,
    )
    course = parsed.course
    warnings = list(parsed.warnings or [])

    if course is None:
        # פענוח נכשל לגמרי — לא נוגעים בנתונים הקיימים.
        result["error"] = "הפענוח לא החזיר קורס (parse returned no course)"
        result["warnings"] = warnings
        return result

    # השלמת נ"ז מתוכנית הלימודים, אם הידיעון לא נתן אותם.
    # התוכנית טובה לשמות/נ"ז/קדם — אבל **לא** לשאלה מה נפתח בפועל.
    if not getattr(course, "credits", 0) and fallback_credits:
        course.credits = float(fallback_credits)

    group_count = len(getattr(course, "groups", []) or [])
    result["group_count"] = group_count
    result["not_offered"] = group_count == 0
    if group_count == 0:
        # GROUND_TRUTH סעיף 6: דף תקין בלי קבוצות = "לא נפתח" — לא שגיאה.
        warnings.append("הידיעון לא מציג אף קבוצה בשנה/סמסטר האלה (course not offered)")

    meta = build_course_meta(
        store_mod,
        fetched_at=iso_utc(),
        attempted_at=iso_utc(),
        year=year_label,
        year_gregorian=year_greg,
        semester=semester,
        source_url=backend.course_url(code),
        content_sha1=sha1_of(html),
        group_count=group_count,
        warnings=warnings,
        ok=True,
    )
    changes = store_obj.save_course(course, meta) or []
    result["ok"] = True
    result["changes"] = [str(c) for c in changes]
    result["warnings"] = warnings
    return result


def mark_course_failed(store_mod, store_obj, code: str, message: str) -> bool:
    """מסמן כישלון שליפה **בלי להרוס נתונים טובים**.

    אם יש רשומה קודמת: שומרים אותה כמו שהיא, ורק מעדכנים את המטא ל-ok=False
    עם חותמת ניסיון טרייה. ``fetched_at`` נשאר של השליפה המוצלחת האחרונה —
    ככה הגיל שמוצג נשאר אמיתי ולא "מתרענן" בזכות ניסיון שנכשל.
    אם אין רשומה קודמת: אין מה לשמר, והכישלון נרשם ביומן בלבד.
    """
    try:
        course, meta = store_obj.load_course(code)
    except Exception:  # noqa: BLE001
        course, meta = None, None
    if course is None:
        return False

    warnings = list(meta_field(meta, "warnings", []) or [])
    warnings.append(f"[{iso_utc()}] ניסיון ריענון נכשל: {message}")
    new_meta = build_course_meta(
        store_mod,
        fetched_at=meta_field(meta, "fetched_at", "") or "",
        attempted_at=iso_utc(),
        year=meta_field(meta, "year", "") or "",
        year_gregorian=meta_field(meta, "year_gregorian", "") or "",
        semester=meta_field(meta, "semester", "") or "",
        source_url=meta_field(meta, "source_url", "") or "",
        content_sha1=meta_field(meta, "content_sha1", "") or "",
        group_count=meta_field(meta, "group_count", 0) or 0,
        warnings=warnings,
        ok=False,
    )
    try:
        store_obj.save_course(course, new_meta)
        return True
    except Exception as exc:  # noqa: BLE001
        log(f"אזהרה: לא הצלחתי לסמן את {code} ככשל ({type(exc).__name__}: {exc}).")
        return False


# ===========================================================================
# 5א. שני מסלולי השליפה — HTTP ישיר (ברירת מחדל) ודפדפן (גיבוי)
# ===========================================================================
#: תוצאת מעבר שליפה אחד. היא קובעת איזו הודעה מודפסת ומה קוד היציאה.
PASS_OK = "ok"
PASS_NEEDS_LOGIN = "needs_login"     # אפשרי אך ורק במסלול --browser
PASS_YEAR_ERROR = "year_error"
PASS_NETWORK = "network"
PASS_CATALOG_ONLY = "catalog_only"
PASS_ERROR = "error"


def fetcher_log(message: str) -> None:
    """הקולבק היחיד שדרכו ``YedionHTTP`` מדבר.

    למה זה קיים בכלל: כשהריענון מופעל מהאתר, הפלט של הסקריפט נקלט אל יומן
    הריצה ומוצג בפאנל המתקפל — ולכן שום מודול אסור לו להדפיס בעצמו. הפצ'ר
    מקבל ``log=fetcher_log`` ולא נוגע ב-``print``; refresh.py הוא הבעלים
    היחיד של הפלט. (SPEC_V2 סעיף 4)
    """
    log(str(message))


class HttpBackend:
    """המסלול הרגיל: ``urllib`` בלבד. בלי דפדפן, בלי חלון, בלי התחברות.

    GROUND_TRUTH סעיף 9: חיפוש הקורסים בידיעון פתוח לקריאה אנונימית —
    ``S_LOOK_FOR_NOSE`` ו-``S_LOOK_FOR_NOSE_AB``. רק ``Enter_Search`` חסום
    מאחורי Citrix, ובו אין לנו צורך. אומת מול האתר החי: שישה קורסים,
    התאמה 6/6 מול הגרידה המחוברת.
    """

    kind = "http"
    #: האם המסלול הזה יכול להגיע למצב "נדרשת התחברות"? לא. אף פעם.
    can_need_login = False

    def __init__(self, year_greg: str) -> None:
        self.module = import_yedion_http()
        self.year_gregorian = str(year_greg)
        self.year_label = hebrew_year_label(year_greg)
        self.fetcher = self.module.YedionHTTP(
            year=self.year_gregorian,
            delay_s=HTTP_DELAY_S,
            timeout_s=HTTP_TIMEOUT_S,
            raw_dir=str(RAW_DIR),
            log=fetcher_log,          # <- כל שורה שלו עוברת דרך היומן, לא דרך המסך
        )

    def open(self) -> str:
        """חימום, קביעת שנה, ואימות שהשנה באמת חזרה. זורק אם לא.

        בקשת החימום אינה קישוט: בלעדיה ה-POST של השנה "מצליח" אבל כל דף
        שיישלף אחריו יחזור בשקט עם השנה הקודמת. האימות הוא מה שתופס את זה.
        """
        self.fetcher.open_session()
        confirmed = str(getattr(self.fetcher, "year_label", "") or "")
        self.year_label = confirmed or self.year_label
        return self.year_label

    def close(self) -> None:
        closer = getattr(self.fetcher, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # noqa: BLE001 - סגירה היא נוחות בלבד
                pass

    def fetch_course_html(self, code: str) -> str:
        return self.fetcher.fetch_course(code)

    def fetch_catalog_html(self) -> str:
        log("מביא את קטלוג הקורסים המלא (בקשה אחת)… (fetching the whole catalog)")
        return self.fetcher.fetch_catalog()

    def course_url(self, code: str) -> str:
        """הכתובת שנשמרת ב-meta.source_url. סלחני: אם המודול חושף בונה
        כתובות משלו נשתמש בו, אחרת נבנה אותה כאן לפי GROUND_TRUTH סעיף 1."""
        maker = getattr(self.module, "course_url", None)
        if callable(maker):
            try:
                return str(maker(code))
            except Exception:  # noqa: BLE001 - נופלים לבנייה המקומית
                pass
        base = str(
            getattr(self.module, "BASE_URL", "")
            or "https://info.braude.ac.il/yedion/fireflyweb.aspx"
        )
        return (
            f"{base}?prgname=S_LOOK_FOR_NOSE"
            f"&arguments=-N{quote(str(code).strip(), safe='')}"
        )

    def session_lost(self) -> bool:
        """אין סשן שאפשר לאבד — אין התחברות מלכתחילה."""
        return False


class BrowserBackend:
    """מסלול הגיבוי: Playwright, בדיוק כפי שהיה.

    נשמר שלם ליום שבו המכללה תסגור גם את הקריאה החופשית. **רק כאן** קיים
    המצב "נדרשת התחברות", ולכן רק כאן אפשר לקבל קוד יציאה 2.
    """

    kind = "browser"
    can_need_login = True

    def __init__(self, scraper_obj, scraper_mod, discovery_mod, year_label: str) -> None:
        self.sc = scraper_obj
        self.scraper_mod = scraper_mod
        self.discovery_mod = discovery_mod
        self.year_label = year_label

    def fetch_course_html(self, code: str) -> str:
        return self.sc.fetch_course_html(code)

    def fetch_catalog_html(self) -> str:
        return browser_fetch_catalog_html(self.sc, self.scraper_mod, self.discovery_mod)

    def course_url(self, code: str) -> str:
        return self.scraper_mod.course_url(code)

    def close(self) -> None:
        return None

    def session_lost(self) -> bool:
        """האם הופנינו באמצע הריצה אל שער ההתחברות?"""
        current = getattr(getattr(self.sc, "page", None), "url", "") or ""
        return bool(current) and not self.scraper_mod.is_success_url(current)


def refresh_courses(
    backend,
    store_mod,
    store_obj,
    record: dict,
    targets: list[str],
    catalog: dict,
    *,
    year_label: str,
    year_greg: str,
    semester: str,
    delay_s: float,
) -> tuple[str, str]:
    """מרענן את הקורסים ברשימה, אחד-אחד ובנימוס. מחזיר (תוצאה, סיבה)."""
    names, credits = curriculum_hints(catalog)
    total = len(targets)

    for index, code in enumerate(targets, start=1):
        if index > 1 and delay_s > 0:
            time.sleep(delay_s)  # נימוס כלפי השרת של המכללה
        record["attempted"].append(code)
        log(f"({index}/{total}) מרענן קורס {code}…")
        try:
            outcome = refresh_one_course(
                backend,
                store_mod,
                store_obj,
                code,
                year_label=year_label,
                year_greg=year_greg,
                semester=semester,
                fallback_name=names.get(code, ""),
                fallback_credits=credits.get(code, 0.0),
            )
        except Exception as exc:  # noqa: BLE001 - קורס אחד לא מפיל את הכול
            message = f"{type(exc).__name__}: {exc}"

            # שנה שגויה היא כשל גלובלי: עוצרים מיד ולא כותבים כלום. הקורס הזה
            # לא נכתב, וגם לא מסומן ככשל — הבעיה אינה בו.
            if is_year_problem(exc):
                record["skipped"].extend(targets[index - 1:])
                return PASS_YEAR_ERROR, message

            session_gone = backend.session_lost()
            mark_course_failed(store_mod, store_obj, code, message)
            record["failed"].append({"code": code, "error": message})
            log(f"תקלה בקורס {code}: {message}")
            if session_gone:
                record["skipped"].extend(targets[index:])
                return PASS_NEEDS_LOGIN, "session expired mid-run"
            continue

        if not outcome["ok"]:
            mark_course_failed(store_mod, store_obj, code, outcome["error"])
            record["failed"].append({"code": code, "error": outcome["error"]})
            log(f"תקלה בקורס {code}: {outcome['error']}")
            continue

        record["refreshed"].append(code)
        if outcome["not_offered"]:
            record["not_offered"].append(code)
        if outcome["changes"]:
            record["changes"][code] = outcome["changes"]
            try:
                store_obj.log_changes(code, outcome["changes"])
            except Exception as exc:  # noqa: BLE001
                log(f"אזהרה: כתיבת השינויים של {code} ליומן נכשלה ({exc}).")
        log(
            f"קורס {code}: {outcome['group_count']} קבוצות, "
            f"{len(outcome['changes'])} שינויים."
        )

    return PASS_OK, ""


def run_pass(
    backend,
    args: argparse.Namespace,
    record: dict,
    store_mod,
    store_obj,
    discovery_mod,
    *,
    targets: list[str],
    need_catalog: bool,
    catalog_age: float | None,
    year_label: str,
    year_greg: str,
    semester: str,
    delay_s: float,
) -> tuple[str, str, dict]:
    """הגוף המשותף לשני המסלולים: קטלוג, תצלום מצב, ואז הקורסים.

    זהה לחלוטין בשניהם — ההבדל היחיד הוא מי מביא את ה-HTML.
    """
    catalog: dict[str, dict] = {}

    # ------------------------------------------------------------- הקטלוג
    if need_catalog:
        try:
            html = backend.fetch_catalog_html()
            assert_year_on_html(html, year_label, "catalog")
            catalog, cat_warnings = discovery_mod.parse_catalog(html)
            record["catalog"]["warnings"] = [str(w) for w in (cat_warnings or [])][:20]
            if catalog:
                store_obj.save_catalog(catalog, year_label, year_greg)
                record["catalog"]["refreshed"] = True
                record["catalog"]["courses"] = len(catalog)
                log(f"הקטלוג נשמר: {len(catalog)} קורסים.")
            else:
                # דף ריק לא דורס קטלוג טוב שכבר קיים.
                log("אזהרה: הקטלוג חזר ריק — הקטלוג הקודם נשמר כמו שהוא.")
                record["catalog"]["warnings"].append("empty catalog page; kept previous")
        except SessionExpired as exc:
            return PASS_NEEDS_LOGIN, f"session expired during catalog fetch: {exc}", catalog
        except Exception as exc:  # noqa: BLE001 - קטלוג שנכשל לא עוצר קורסים
            if is_year_problem(exc) or (
                isinstance(exc, RuntimeError)
                and ("שנת" in str(exc) or "year" in str(exc).lower())
            ):
                # שנה שגויה בדף הקטלוג = עצירה מלאה. לא כותבים כלום.
                return PASS_YEAR_ERROR, str(exc), catalog
            log(f"אזהרה: הקטלוג נכשל ({type(exc).__name__}: {exc}) — ממשיכים לקורסים.")
            record["catalog"]["warnings"].append(f"{type(exc).__name__}: {exc}")
    else:
        log(f"הקטלוג עדיין טרי ({human_age(catalog_age)}) — מדלגים עליו.")

    if not catalog:
        try:
            catalog, _ = store_obj.load_catalog()
        except Exception:  # noqa: BLE001
            catalog = {}

    if args.catalog_only:
        return PASS_CATALOG_ONLY, "catalog only", catalog

    # ------------------------------------------------ תצלום מצב לפני הכתיבה
    # תצלום אחד לפני שמתחילים לדרוס — ככה תמיד יש למה לחזור.
    try:
        snap = store_obj.snapshot()
        if snap:
            log(f"תצלום מצב נשמר: {snap}")
    except Exception as exc:  # noqa: BLE001
        log(f"אזהרה: שמירת תצלום המצב נכשלה ({type(exc).__name__}: {exc}).")

    outcome, reason = refresh_courses(
        backend,
        store_mod,
        store_obj,
        record,
        targets,
        catalog,
        year_label=year_label,
        year_greg=year_greg,
        semester=semester,
        delay_s=delay_s,
    )
    return outcome, reason, catalog


def run_http_pass(
    args: argparse.Namespace,
    record: dict,
    store_mod,
    store_obj,
    discovery_mod,
    *,
    targets: list[str],
    need_catalog: bool,
    catalog_age: float | None,
    year_label: str,
    year_greg: str,
    semester: str,
) -> tuple[str, str, dict]:
    """המסלול הרגיל: שליפה ישירה ב-HTTP. אין כאן התחברות, ולכן אין needs_login."""
    backend = HttpBackend(year_greg)          # MissingModule עולה החוצה במכוון
    log("שולף ישירות מהידיעון ב-HTTP — בלי דפדפן ובלי התחברות. (anonymous fetch)")
    log("פותח סשן: בקשת חימום, ואז קביעת שנת הלימודים ואימות שלה…")
    try:
        confirmed = backend.open()
    except Exception as exc:  # noqa: BLE001
        backend.close()
        if is_year_problem(exc):
            return PASS_YEAR_ERROR, f"{type(exc).__name__}: {exc}", {}
        if looks_like_network(exc):
            return PASS_NETWORK, f"{type(exc).__name__}: {exc}", {}
        return PASS_ERROR, f"{type(exc).__name__}: {exc}", {}

    year_label = confirmed or year_label
    record["year"] = year_label
    log(f"שנת הלימודים אושרה: {year_label} ({year_greg}).")

    try:
        return run_pass(
            backend,
            args,
            record,
            store_mod,
            store_obj,
            discovery_mod,
            targets=targets,
            need_catalog=need_catalog,
            catalog_age=catalog_age,
            year_label=year_label,
            year_greg=year_greg,
            semester=semester,
            # ההשהיה נאכפת גם כאן וגם בתוך הפצ'ר. פער כפול עדיף על פער חסר.
            delay_s=HTTP_DELAY_S,
        )
    finally:
        backend.close()


def run_browser_pass(
    args: argparse.Namespace,
    record: dict,
    store_mod,
    store_obj,
    discovery_mod,
    *,
    targets: list[str],
    need_catalog: bool,
    catalog_age: float | None,
    year_label: str,
    year_greg: str,
    semester: str,
) -> tuple[str, str, dict]:
    """מסלול הגיבוי דרך Playwright — הזרימה הישנה, ללא שינוי.

    זה המסלול היחיד שבו יש סשן שיכול לפוג, ולכן היחיד שמחזיר needs_login.
    """
    scraper_mod = import_scraper()
    try:
        scraper_ctx = scraper_mod.BraudeScraper(
            profile_dir=str(BROWSER_PROFILE_DIR),
            raw_dir=str(RAW_DIR),
            headless=not args.headful,
            year=year_greg,
        )
    except Exception as exc:  # noqa: BLE001
        return PASS_ERROR, f"scraper init failed: {exc}", {}

    with scraper_ctx as sc:
        # ------------------------------------- הסשן — קיים או פג?
        state, detail = probe_session(sc, scraper_mod)

        if state == PROBE_NETWORK:
            log(f"תקלת רשת/דפדפן: {detail}")
            return PASS_NETWORK, f"network: {detail}", {}

        if state == PROBE_NEEDS_LOGIN:
            if args.headful:
                # רק כאן מותר לפתוח התחברות — כי יש בן אדם מול המסך.
                log("הסשן פג. פותח חלון התחברות ומחכה שההתחברות תתבצע ידנית…")
                if not sc.open_and_wait_for_login(timeout_s=LOGIN_TIMEOUT_S):
                    return PASS_NEEDS_LOGIN, "manual login not completed", {}
            else:
                # ריצה ללא פיקוח: **לא מנסים להתחבר**, לא שומרים את דף
                # ההזדהות (הוא עלול להכיל טופס שמולא אוטומטית), ולא נוגעים
                # בנתונים.
                log(f"הסשן פג (הופנינו ל-{detail}). לא מנסים להתחבר, לא שומרים את הדף.")
                return PASS_NEEDS_LOGIN, "session expired", {}

        # ------------------------------------- שנת לימודים — לקבוע ולאמת
        try:
            year_label = sc.set_year(year_greg) or year_label
            log(f"שנת הלימודים אושרה: {year_label} ({year_greg}).")
            record["year"] = year_label
        except Exception as exc:  # noqa: BLE001 - כולל YearSwitchError
            # אולי הסשן פג בדיוק עכשיו? אז זו הודעה אחרת לגמרי.
            current = getattr(getattr(sc, "page", None), "url", "") or ""
            if current and not scraper_mod.is_success_url(current):
                return PASS_NEEDS_LOGIN, "session expired during year switch", {}
            return PASS_YEAR_ERROR, f"year not verified: {type(exc).__name__}: {exc}", {}

        backend = BrowserBackend(sc, scraper_mod, discovery_mod, year_label)
        return run_pass(
            backend,
            args,
            record,
            store_mod,
            store_obj,
            discovery_mod,
            targets=targets,
            need_catalog=need_catalog,
            catalog_age=catalog_age,
            year_label=year_label,
            year_greg=year_greg,
            semester=semester,
            delay_s=POLITE_DELAY_S,
        )


def cmd_refresh(args: argparse.Namespace) -> int:
    """מעבר ריענון אחד. זו הפונקציה שהמשימה היומית מריצה.

    ברירת המחדל היא המסלול הישיר ב-HTTP: בלי דפדפן, בלי חלון ובלי התחברות.
    ``--browser`` מחזיר את המסלול הישן דרך Playwright, ורק בו קיים needs_login.
    """
    store_mod = import_store()
    discovery_mod = import_discovery()

    use_browser = bool(getattr(args, "browser", False))
    started = now_utc()
    profile = load_profile()
    year_greg = args.year or profile_year(profile)
    year_label = hebrew_year_label(year_greg)
    semester = args.semester if args.semester is not None else profile_semester(profile)
    max_age = float(args.max_age)
    store_obj = store_mod.Store(str(DB_ROOT))

    if use_browser:
        mode = "browser-headful" if args.headful else "browser-headless"
        mode_he = "דפדפן, חלון גלוי" if args.headful else "דפדפן ברקע (headless)"
    else:
        mode = "http"
        mode_he = "HTTP ישיר — בלי דפדפן ובלי התחברות"

    record: dict = {
        "started_at": iso_utc(started),
        "finished_at": "",
        "duration_s": 0.0,
        "status": STATUS_ERROR,
        "exit_code": EXIT_ERROR,
        "reason": "",
        "mode": mode,
        "year": year_label,
        "year_gregorian": year_greg,
        "semester": semester,
        "max_age_hours": max_age,
        "catalog": {"refreshed": False, "courses": 0, "warnings": []},
        "tracked": 0,
        "attempted": [],
        "refreshed": [],
        "failed": [],
        "not_offered": [],
        "skipped": [],
        "changes": {},
        "changes_count": 0,
    }

    def finish(status: str, exit_code: int, reason: str = "") -> int:
        """סוגר את הרשומה, כותב אותה ליומן, ומחזיר את קוד היציאה."""
        record["status"] = status
        record["exit_code"] = exit_code
        record["reason"] = reason
        record["finished_at"] = iso_utc()
        record["duration_s"] = round((now_utc() - started).total_seconds(), 1)
        record["changes_count"] = sum(len(v) for v in record["changes"].values())
        try:
            store_obj.log_refresh(record)
        except Exception as exc:  # noqa: BLE001 - כשל ביומן לא מסתיר את התוצאה
            log(f"אזהרה: כתיבת יומן הריענון נכשלה ({type(exc).__name__}: {exc}).")
        return exit_code

    print(
        banner(
            [
                "ריענון מסד הנתונים מהידיעון — REFRESH RUN",
                "",
                f"שנה: {year_label} ({year_greg}) | סמסטר: {semester or 'ללא סינון'}",
                f"מצב: {mode_he} | סף התיישנות: {max_age:g} שעות",
                f"מסד: {DB_ROOT}",
            ]
        )
    )

    if args.headful and not use_browser:
        log(
            "שימו לב: --headful שייך למסלול הדפדפן בלבד. המסלול הרגיל לא פותח "
            "דפדפן כלל, ולכן הדגל לא משנה כלום."
        )
        log("למסלול הישן:  python refresh.py --browser --headful")

    # ------------------------------------------------- 1. מי במעקב, ומה ישן
    explicit = split_codes(args.codes)
    for code in explicit:
        if not re.fullmatch(r"\d{4,7}", code):
            log(f"אזהרה: '{code}' לא נראה כמו קוד קורס (4-7 ספרות) — מנסים בכל זאת.")
    if explicit:
        try:
            store_obj.track(explicit)
        except Exception as exc:  # noqa: BLE001
            log(f"אזהרה: הוספה לרשימת המעקב נכשלה ({type(exc).__name__}: {exc}).")

    if getattr(args, "all", False):
        # --all: כל קוד שמופיע בקטלוג נכנס למעקב. הקטלוג הוא בקשה אחת שכבר
        # מחזירה את כל הקורסים שנפתחים השנה, ולכן זה לא עולה שום בקשה נוספת.
        # אם עדיין אין קטלוג שמור — הריצה הזאת תשלוף אותו, והבאה כבר תכסה הכול.
        try:
            catalog, _meta = store_obj.load_catalog()
        except Exception as exc:  # noqa: BLE001
            catalog = {}
            log(f"אזהרה: לא ניתן לקרוא את הקטלוג ({type(exc).__name__}).")
        if catalog:
            log(f"--all: מוסיף למעקב את כל {len(catalog)} הקורסים שבקטלוג.")
            try:
                store_obj.track(sorted(catalog))
            except Exception as exc:  # noqa: BLE001
                log(f"אזהרה: הרחבת רשימת המעקב נכשלה ({exc}).")
        else:
            log("--all: אין עדיין קטלוג שמור — הריצה הזאת תשלוף אותו, והבאה תכסה את כל הקורסים.")

    tracked = list(store_obj.tracked())
    if not tracked:
        seed = profile_codes(profile)
        if seed:
            log(f"רשימת המעקב ריקה — מאכלס אותה מהפרופיל: {', '.join(seed)}")
            try:
                store_obj.track(seed)
                tracked = list(store_obj.tracked())
            except Exception as exc:  # noqa: BLE001
                log(f"אזהרה: לא הצלחתי לשמור את רשימת המעקב ({exc}).")
                tracked = seed
    record["tracked"] = len(tracked)

    if explicit:
        # בקשה מפורשת = מרעננים בלי קשר לגיל.
        targets = explicit
    else:
        try:
            targets = list(store_obj.stale_codes(tracked, max_age))
        except Exception as exc:  # noqa: BLE001
            log(f"אזהרה: חישוב הטריות נכשל ({exc}) — מרעננים הכול.")
            targets = list(tracked)
        record["skipped"] = [c for c in tracked if c not in targets]

    # האם צריך לגעת בקטלוג בכלל?
    catalog_age = None
    try:
        catalog_age = store_obj.catalog_age_hours()
    except Exception:  # noqa: BLE001
        catalog_age = None
    need_catalog = args.catalog_only or catalog_age is None or catalog_age >= max_age

    if args.catalog_only and explicit:
        log("שימו לב: --catalog-only ו---codes ביחד — הקודים נוספו למעקב, אבל בריצה הזאת נשלף רק הקטלוג.")
    if args.catalog_only:
        targets = []

    if not need_catalog and not targets:
        # הכול טרי. לא נוגעים ברשת בכלל — זה גם מנומס וגם מהיר.
        print(
            banner(
                [
                    "הכול טרי — אין מה לרענן. (everything is fresh)",
                    "",
                    f"הקטלוג עודכן {human_age(catalog_age)}, וכל {len(tracked)} הקורסים במעקב עדכניים.",
                    f"סף ההתיישנות הוא {max_age:g} שעות. לרענון בכוח:  python refresh.py --max-age 0",
                ]
            )
        )
        return finish(STATUS_FRESH, EXIT_OK, "nothing was stale")

    log(f"קורסים במעקב: {len(tracked)} | לרענון עכשיו: {len(targets)} | קטלוג: {'כן' if need_catalog else 'לא'}")

    # -------------------------------------------------- 2. המעבר עצמו
    kwargs = dict(
        targets=targets,
        need_catalog=need_catalog,
        catalog_age=catalog_age,
        year_label=year_label,
        year_greg=year_greg,
        semester=semester,
    )
    try:
        if use_browser:
            outcome, reason, catalog = run_browser_pass(
                args, record, store_mod, store_obj, discovery_mod, **kwargs
            )
        else:
            outcome, reason, catalog = run_http_pass(
                args, record, store_mod, store_obj, discovery_mod, **kwargs
            )
    except MissingModule:
        raise
    except KeyboardInterrupt:
        return finish(STATUS_ERROR, EXIT_ERROR, "interrupted by the user")
    except Exception as exc:  # noqa: BLE001
        log(f"תקלה לא צפויה: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return finish(STATUS_ERROR, EXIT_ERROR, f"{type(exc).__name__}: {exc}")

    year_label = record["year"] or year_label

    # -------------------------------------------------- 3. מה יצא מהמעבר
    if outcome == PASS_NEEDS_LOGIN:
        if not use_browser:
            # לא אמור לקרות: במסלול הישיר אין התחברות ואין סשן. אם בכל זאת
            # הגענו לכאן — זו תקלה רגילה, ולא נשלח את הסטודנט/ית להתחבר לחינם.
            log("מצב לא צפוי: המסלול הישיר דיווח על צורך בהתחברות. מדווחים כתקלה.")
            return finish(STATUS_ERROR, EXIT_ERROR, reason or "unexpected needs_login on the http path")
        print_needs_login(store_obj, tracked)
        return finish(STATUS_NEEDS_LOGIN, EXIT_NEEDS_LOGIN, reason)

    if outcome == PASS_YEAR_ERROR:
        wrote_something = bool(record["refreshed"]) or record["catalog"]["refreshed"]
        lines = [
            "עצירה: לא אושרה שנת הלימודים — STOPPED: academic year not verified",
            "",
            f"ביקשנו {year_label or '?'} ({year_greg}) והידיעון לא אישר.",
            f"פרטים: {reason}",
            "",
        ]
        if wrote_something:
            lines += [
                "הריצה נעצרה באמצע. מה שנכתב עד כה נכתב אחרי אימות שנה תקין;",
                "הדף שהחזיר שנה שגויה **לא** נכתב, ושאר הרשימה לא נשלפה.",
            ]
        else:
            lines.append("**לא נכתב שום נתון למסד.**")
        lines += [
            "נתונים של שנה שגויה גרועים בהרבה מהיעדר נתונים — הם נראים אמינים לגמרי.",
            "Wrong-year data is worse than no data: it looks perfectly trustworthy.",
        ]
        if not use_browser:
            lines += [
                "",
                "במסלול הישיר זה כמעט תמיד אומר שבקשת החימום לא תפסה, ולכן",
                "קביעת השנה לא נדבקה לסשן. (GROUND_TRUTH סעיף 9)",
            ]
        print(banner(lines, ch="!"))
        return finish(STATUS_YEAR_ERROR, EXIT_ERROR, reason)

    if outcome == PASS_NETWORK:
        print(
            banner(
                [
                    "לא הצלחתי להגיע לשרת של המכללה. (could not reach the server)",
                    "",
                    "זו תקלת רשת ולא בעיית הרשאה — הנתונים הקיימים נשארו כמו שהם.",
                    "כדאי לבדוק חיבור לאינטרנט ולנסות שוב מאוחר יותר.",
                    "",
                    f"פרטים: {reason}",
                ],
                ch="!",
            )
        )
        return finish(STATUS_ERROR, EXIT_ERROR, reason)

    if outcome == PASS_ERROR:
        print(banner(["תקלה בהתחלת השליפה — FETCH DID NOT START", "", str(reason)], ch="!"))
        return finish(STATUS_ERROR, EXIT_ERROR, reason)

    if outcome == PASS_CATALOG_ONLY:
        print(
            banner(
                [
                    "רוענן הקטלוג בלבד. (catalog only)",
                    f"{record['catalog']['courses'] or len(catalog)} קורסים מוצעים בשנה {year_label}.",
                ]
            )
        )
        return finish(STATUS_OK, EXIT_OK, "catalog only")

    # -------------------------------------------------- 4. סיכום אנושי
    print_summary(record, catalog_age)

    failed = record["failed"]
    if failed and not record["refreshed"]:
        return finish(STATUS_PARTIAL, EXIT_PARTIAL, "all course fetches failed")
    if failed:
        return finish(STATUS_PARTIAL, EXIT_PARTIAL, f"{len(failed)} course(s) failed")
    return finish(STATUS_OK, EXIT_OK, "refreshed")


def curriculum_hints(catalog: dict) -> tuple[dict[str, str], dict[str, float]]:
    """שמות ונ"ז להשלמה: קודם מהקטלוג (מקור האמת למה שנפתח), אחר כך מהתוכנית.

    תוכנית הלימודים היא **הנחיה, לא הגבלה**: היא טובה לשמות, נ"ז וקדם, אבל
    לא קובעת מה מוצע בפועל. קורס שחוזר מסמסטר קודם הוא מקרה רגיל לחלוטין.
    """
    names: dict[str, str] = {}
    credits: dict[str, float] = {}

    if isinstance(catalog, dict):
        for code, entry in catalog.items():
            if isinstance(entry, dict) and entry.get("name"):
                names[str(code)] = str(entry["name"])

    try:
        import curriculum as curriculum_mod  # type: ignore

        curr = curriculum_mod.load_curriculum(str(CURRICULUM_PATH))
    except Exception:  # noqa: BLE001 - התוכנית היא נוחות בלבד
        return names, credits

    def visit(node) -> None:
        if isinstance(node, dict):
            code = str(node.get("code", "")).strip()
            if code:
                if node.get("name") and code not in names:
                    names[code] = str(node["name"])
                try:
                    credits[code] = float(node.get("credits") or 0.0)
                except (TypeError, ValueError):
                    pass
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(curr)
    return names, credits


def print_summary(record: dict, catalog_age: float | None) -> None:
    """הסיכום שהסטודנט/ית רואה. השינויים מודפסים בקול — זה כל הרעיון."""
    lines = [
        "סיכום ריצה — REFRESH SUMMARY",
        "",
        f"התחיל: {local_stamp(record['started_at'])} | משך: {record['duration_s'] or 0} שניות",
        f"שנה: {record['year']} ({record['year_gregorian']}) | "
        f"סמסטר: {record['semester'] or 'ללא סינון'} | מצב: {record['mode']}",
    ]
    cat = record["catalog"]
    if cat["refreshed"]:
        lines.append(f"קטלוג: {cat['courses']} קורסים מוצעים (רוענן עכשיו)")
    else:
        lines.append(f"קטלוג: לא רוענן בריצה הזאת ({human_age(catalog_age)})")
    lines.append(
        f"קורסים: {len(record['attempted'])} נבדקו | {len(record['refreshed'])} עודכנו | "
        f"{len(record['failed'])} נכשלו | {len(record['skipped'])} דולגו (עדיין טריים)"
    )
    changes_total = sum(len(v) for v in record["changes"].values())
    lines.append(f"שינויים שזוהו: {changes_total}")
    print(banner(lines))

    # --- השינויים: בקול, לא רק ביומן ---
    if record["changes"]:
        change_lines = [
            "שינויים מאז העדכון הקודם — CHANGES DETECTED",
            "",
            "שינוי מרצה או שעה אחרי ההרשמה הוא בדיוק הדבר שחשוב לדעת עליו.",
            "A lecturer or time change after registration is what this job is for.",
            "",
        ]
        for code in sorted(record["changes"]):
            for text in record["changes"][code]:
                change_lines.append("• " + format_change(code, text))
        change_lines += ["", "יש לוודא בידיעון לפני הרשמה. (please verify in the yedion)"]
        print(banner(change_lines, ch="*"))

    # --- קורסים שלא נפתחו ---
    if record["not_offered"]:
        print(
            banner(
                [
                    "קורסים בלי אף קבוצה בשנה/סמסטר האלה:",
                    "  " + ", ".join(record["not_offered"]),
                    "",
                    "דף תקין בלי קבוצות פירושו 'לא נפתח' — זו תשובה לגיטימית של",
                    "הידיעון ולא תקלה. כדאי לבדוק ידנית לפני שמוותרים על הקורס.",
                    "(An empty result page means 'not offered', not an error.)",
                ],
                ch="-",
            )
        )

    # --- כשלים ---
    if record["failed"]:
        fail_lines = ["קורסים שנכשלו — הנתונים הקודמים שלהם נשמרו:", ""]
        for item in record["failed"]:
            fail_lines.append(f"• {item['code']}: {truncate(item['error'], 100)}")
        fail_lines += ["", "אפשר לנסות שוב:  python refresh.py --codes " + ",".join(i["code"] for i in record["failed"])]
        print(banner(fail_lines, ch="-"))


# ===========================================================================
# 6. Windows Task Scheduler — התקנה והסרה של המשימה היומית
# ===========================================================================
def decode_console(raw: bytes) -> str:
    """מפענח פלט של כלי מסוף ב-Windows. schtasks כותב בקוד-עמוד של הקונסולה,
    שהוא לא UTF-8 — לכן מנסים כמה קידודים לפי הסדר, בלי להפיל כלום."""
    if not raw:
        return ""
    for encoding in ("oem", "utf-8", "cp1255", "latin-1"):
        try:
            return raw.decode(encoding, errors="replace").strip()
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace").strip()


def run_schtasks(argv: list[str]) -> tuple[int, str]:
    """מריץ schtasks ומחזיר (קוד יציאה, פלט). לא זורק על כישלון.

    שימו לב: מריצים ברשימת ארגומנטים ובלי shell=True — ככה אין שום פרשנות
    של תווים מיוחדים בנתיבים.
    """
    try:
        proc = subprocess.run(argv, capture_output=True, shell=False, check=False)
    except FileNotFoundError:
        return 127, "לא נמצאה הפקודה schtasks — היא קיימת רק ב-Windows. (schtasks not found)"
    except OSError as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    output = "\n".join(part for part in (decode_console(proc.stdout), decode_console(proc.stderr)) if part)
    return proc.returncode, output


def python_for_task() -> Path:
    """בוחר את המפרש שיריץ את המשימה היומית.

    מעדיפים ``pythonw.exe`` אם הוא קיים ליד ``sys.executable``: הוא רץ בלי
    חלון קונסולה, ולכן המשימה היומית לא תקפיץ חלון שחור מדי בוקר.
    """
    exe = Path(sys.executable).resolve()
    candidate = exe.with_name("pythonw.exe")
    return candidate if candidate.exists() else exe


def cmd_install_task(args: argparse.Namespace) -> int:
    """רושם משימה יומית ב-Task Scheduler של Windows."""
    task_time = str(args.task_time or DEFAULT_TASK_TIME).strip()
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", task_time):
        print(f"שעה לא תקינה: '{task_time}'. הפורמט הוא HH:MM בפורמט 24 שעות, למשל 07:00.")
        return EXIT_ERROR

    python_exe = python_for_task()
    script = (PROJECT_ROOT / "refresh.py").resolve()

    # כל נתיב בין מרכאות. היום אין רווחים בנתיב הפרויקט — מחר תיקיית הבית
    # של המשתמש עשויה להכיל רווח, וזה בדיוק המקום שבו זה היה נשבר בשקט.
    # ‏--all: המשימה היומית מרעננת את *כל* הקורסים שנפתחים, ולא רק את אלה
    # שנבחרו. זו הדרישה של הסטודנט/ית — שלא יהיה מצב שקורס נבחר בממשק ואין
    # לו נתונים, ושאף אחד לא יצטרך לדעת מתי המידע נמשך.
    tr_value = f'"{python_exe}" "{script}" --all'
    argv = [
        "schtasks", "/Create",
        "/TN", TASK_NAME,
        "/SC", "DAILY",
        "/ST", task_time,
        "/F",                       # /F = לדרוס משימה קיימת באותו שם
        "/TR", tr_value,
    ]

    print(
        banner(
            [
                "התקנת משימה יומית — INSTALL DAILY TASK",
                "",
                f"שם המשימה: {TASK_NAME}",
                f"שעה: {task_time} כל יום",
                f"מפרש: {python_exe}"
                + ("   (pythonw = בלי חלון קונסולה)" if python_exe.name.lower() == "pythonw.exe" else ""),
                f"סקריפט: {script}",
                "",
                "המשימה תרוץ במסלול ברירת המחדל: שליפה ישירה ב-HTTP, בלי דפדפן",
                "ובלי התחברות — כלומר ריצה יומית ללא שום התערבות. (unattended)",
            ]
        )
    )
    print("\nהפקודה שתרוץ עכשיו (this exact command will run now):")
    print("    " + subprocess.list2cmdline(argv))
    print()

    code, output = run_schtasks(argv)
    if output:
        print(output)

    if code != 0:
        print(
            banner(
                [
                    "יצירת המשימה נכשלה. (task creation failed)",
                    "",
                    f"קוד שגיאה: {code}",
                    "סיבות נפוצות: אין הרשאות מתאימות, או מדיניות ארגונית שחוסמת schtasks.",
                    "",
                    "אפשר להתקין ידנית דרך הממשק הגרפי:",
                    "  1. לפתוח את 'Task Scheduler' (מתזמן המשימות) מתפריט התחלה.",
                    "  2. Create Basic Task… → שם: " + TASK_NAME,
                    "  3. Trigger: Daily, בשעה " + task_time,
                    "  4. Action: Start a program",
                    f"       Program/script:  {python_exe}",
                    f"       Add arguments:   \"{script}\"",
                    f"       Start in:        {PROJECT_ROOT}",
                    "  5. לסיים, ואז Run פעם אחת כדי לוודא שזה עובד.",
                    "",
                    "לחלופין, אפשר פשוט להריץ  python refresh.py  ידנית מדי פעם.",
                ],
                ch="!",
            )
        )
        return EXIT_ERROR

    # אימות: לא מסתפקים ב"הפקודה החזירה 0".
    print("\nבודק שהמשימה באמת נרשמה… (verifying)")
    verify_argv = ["schtasks", "/Query", "/TN", TASK_NAME]
    print("    " + subprocess.list2cmdline(verify_argv))
    vcode, voutput = run_schtasks(verify_argv)
    if voutput:
        print(voutput)
    if vcode != 0:
        print("\nהמשימה נוצרה לכאורה, אבל השאילתה עליה נכשלה. כדאי לבדוק ידנית ב-Task Scheduler.")
        return EXIT_ERROR

    print(
        banner(
            [
                "המשימה נרשמה בהצלחה. (task installed)",
                "",
                f"תרוץ כל יום ב-{task_time}, כל עוד המחשב דולק ומחובר למשתמש.",
                "",
                "הריצה אוטומטית לגמרי: אין חלון, אין דפדפן ואין התחברות.",
                "השליפה נעשית ישירות ב-HTTP מול הידיעון, שפתוח לקריאה בלי הזדהות,",
                "ולכן אין סשן שיפוג ואין שום דבר לחדש מדי כמה ימים.",
                "The daily run is genuinely unattended: no window, no browser, no sign-in.",
                "",
                "לבדיקה מפורטת:",
                f'    schtasks /Query /TN "{TASK_NAME}" /V /FO LIST',
                "להרצה מיידית לבדיקה:",
                f'    schtasks /Run /TN "{TASK_NAME}"',
                "להסרה:",
                "    python refresh.py --uninstall-task",
                f'    (או ידנית:  schtasks /Delete /TN "{TASK_NAME}" /F)',
                "",
                "pythonw רץ בלי חלון, ולכן לא רואים את הפלט של הריצה היומית.",
                "כדי לראות מה קרה בה:",
                "    python refresh.py --status",
                "",
                "ואם יום אחד המכללה תסגור את הקריאה החופשית — יש מסלול גיבוי דרך",
                "דפדפן:  python refresh.py --browser --headful  — ורק הוא דורש התחברות.",
            ]
        )
    )
    return EXIT_OK


def cmd_uninstall_task(args: argparse.Namespace) -> int:
    """מסיר את המשימה היומית."""
    print(
        banner(
            [
                "הסרת המשימה היומית — UNINSTALL DAILY TASK",
                f"שם המשימה: {TASK_NAME}",
            ]
        )
    )

    query_argv = ["schtasks", "/Query", "/TN", TASK_NAME]
    qcode, _ = run_schtasks(query_argv)
    if qcode == 127:
        print("הפקודה schtasks לא נמצאה — הפעולה הזאת רלוונטית ל-Windows בלבד.")
        return EXIT_ERROR
    if qcode != 0:
        print(f"לא קיימת משימה בשם {TASK_NAME} — אין מה להסיר. (nothing to remove)")
        return EXIT_OK

    argv = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
    print("הפקודה שתרוץ עכשיו (this exact command will run now):")
    print("    " + subprocess.list2cmdline(argv))
    print()
    code, output = run_schtasks(argv)
    if output:
        print(output)
    if code != 0:
        print(
            banner(
                [
                    "מחיקת המשימה נכשלה. (delete failed)",
                    f"קוד שגיאה: {code}",
                    "",
                    "אפשר למחוק ידנית: לפתוח 'Task Scheduler', לאתר את",
                    f"  {TASK_NAME}",
                    "וללחוץ Delete.",
                ],
                ch="!",
            )
        )
        return EXIT_ERROR

    print(f"\nהמשימה {TASK_NAME} הוסרה. הנתונים במסד לא נגעו בהם. (task removed; data untouched)")
    return EXIT_OK


# ===========================================================================
# 7. CLI
# ===========================================================================
class FriendlyParser(argparse.ArgumentParser):
    """argparse שיוצא עם קוד 1 ולא עם 2 על שגיאת שימוש.

    למה זה חשוב כאן: **2 שמור אצלנו ל"נדרשת התחברות"**. אם argparse היה
    יוצא עם 2 בגלל דגל שגוי, המתזמן היה חושב שהסשן פג.
    """

    def error(self, message: str):  # noqa: D102 - מוגדר ב-argparse
        self.print_usage(sys.stderr)
        print(f"\nשגיאה בשורת הפקודה: {message}", file=sys.stderr)
        print("(command-line error — see --help)", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)


def build_arg_parser() -> argparse.ArgumentParser:
    """בונה את מפענח הארגומנטים."""
    parser = FriendlyParser(
        prog="refresh.py",
        description=(
            "ריענון מתוזמן של מסד הנתונים מהידיעון של בראודה. "
            "(scheduled refresh of the local JSON database from the Braude yedion)"
        ),
        epilog=(
            "ברירת המחדל: שליפה ישירה ב-HTTP — בלי דפדפן, בלי חלון ובלי התחברות. "
            "--browser מפעיל את מסלול הגיבוי דרך Playwright, והוא היחיד שדורש התחברות ידנית. "
            "קודי יציאה: 0 = רוענן/טרי, 2 = נדרשת התחברות (במסלול --browser בלבד), "
            "3 = ריענון חלקי, 1 = תקלה. "
            "(default = login-free HTTP fetch; --browser = the old Playwright path; "
            "exit codes: 0 ok, 2 needs login [--browser only], 3 partial, 1 error)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # פעולות שאינן ריענון — אי אפשר לשלב ביניהן.
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--status", action="store_true",
        help="הצגת מצב המסד: טריות, ריצה אחרונה ושינויים. בלי שום פנייה לרשת.",
    )
    actions.add_argument(
        "--install-task", action="store_true",
        help=f'רישום משימה יומית ב-Windows בשם "{TASK_NAME}".',
    )
    actions.add_argument(
        "--uninstall-task", action="store_true",
        help="הסרת המשימה היומית.",
    )

    parser.add_argument(
        "--browser", action="store_true",
        help=(
            "מסלול גיבוי: שליפה דרך דפדפן Playwright במקום HTTP ישיר. "
            "רק הוא דורש התחברות ידנית לידיעון (Citrix) ורק בו קיים קוד יציאה 2. "
            "ברירת המחדל, בלי הדגל הזה, היא שליפה ישירה בלי דפדפן ובלי התחברות."
        ),
    )
    parser.add_argument(
        "--headful", action="store_true",
        help=(
            "רלוונטי רק יחד עם --browser: פתיחת חלון דפדפן גלוי כדי להתחבר ידנית. "
            "בלי --browser אין דפדפן בכלל, והדגל לא עושה כלום."
        ),
    )
    parser.add_argument(
        "--all", action="store_true",
        help=(
            "לרענן את *כל* הקורסים שנפתחים השנה, לא רק את אלה שבמעקב. "
            "זה מה שהמשימה היומית מריצה, כדי שלעולם לא יהיה קורס בלי נתונים "
            "(refresh every offered course, not just the tracked ones)"
        ),
    )
    parser.add_argument(
        "--codes", default="",
        help="קודי קורסים לרענון מיידי, מופרדים בפסיקים. הם גם נוספים לרשימת המעקב.",
    )
    parser.add_argument(
        "--catalog-only", action="store_true",
        help="רק קטלוג הקורסים, בלי דפי הקבוצות.",
    )
    parser.add_argument(
        "--max-age", type=float, default=DEFAULT_MAX_AGE_HOURS, metavar="HOURS",
        help=f"סף התיישנות בשעות (ברירת מחדל {DEFAULT_MAX_AGE_HOURS:g}). 0 = לרענן הכול.",
    )
    parser.add_argument(
        "--task-time", default=DEFAULT_TASK_TIME, metavar="HH:MM",
        help=f"שעת הריצה של המשימה היומית (ברירת מחדל {DEFAULT_TASK_TIME}).",
    )
    parser.add_argument(
        "--year", default="", metavar="YYYY",
        help="שנה אקדמית לועזית (2027 = תשפ\"ז). ברירת מחדל: מהפרופיל.",
    )
    parser.add_argument(
        "--semester", default=None, metavar="א|ב|קיץ",
        help="סמסטר לסינון המפגשים. ברירת מחדל: מהפרופיל. ריק = בלי סינון.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """נקודת הכניסה. מחזירה קוד יציאה — אף פעם לא זורקת traceback לסטודנט/ית."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.max_age < 0:
        print("--max-age לא יכול להיות שלילי.")
        return EXIT_ERROR

    try:
        if args.install_task:
            return cmd_install_task(args)
        if args.uninstall_task:
            return cmd_uninstall_task(args)
        if args.status:
            return cmd_status(args)
        return cmd_refresh(args)
    except MissingModule as exc:
        print(banner(["חסר מודול פנימי — MISSING MODULE", "", str(exc)], ch="!"))
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\nעצרת את הריענון. שום דבר לא נשבר. (interrupted — nothing was broken)")
        return 130
    except Exception as exc:  # noqa: BLE001 - רשת ביטחון אחרונה
        print(banner([
            "תקלה לא צפויה — UNEXPECTED ERROR",
            "",
            f"{type(exc).__name__}: {exc}",
            "",
            "הנתונים הקיימים לא נמחקו. אפשר לבדוק מצב עם:",
            "    python refresh.py --status",
        ], ch="!"))
        traceback.print_exc()
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
