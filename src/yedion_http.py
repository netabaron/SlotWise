"""
src/yedion_http.py — שליפה מהידיעון **בלי התחברות** (login-free HTTP fetcher).

למה המודול הזה קיים
--------------------
עד עכשיו כל רענון עבר דרך דפדפן: פותחים חלון, מתחברים ידנית לשער ה-Citrix,
ומקווים שהסשן לא פג. זה גם הפריע לסטודנט/ית ("כשאני לוחץ רענון זה דורש
להתחבר ל-Citrix", "יש שורות קוד שמופיעות על המסך").

``GROUND_TRUTH.md`` §9 הפך את ההנחה הזאת: **מסך חיפוש הקורסים אינו מוגן
בכלל.** רק ``prgname=Enter_Search`` מפנה משתמש אנונימי לשער ההתחברות;
``S_LOOK_FOR_NOSE`` (קורס לפי קוד) ו-``S_LOOK_FOR_NOSE_AB`` (כל הקטלוג)
נקראים בפומבי. שישה קורסים נשלפו אנונימית והושוו לגרידה המחוברת — 6/6 זהים.

לכן הרענון היומי יכול להיות **בלתי מאויש לחלוטין**: בלי דפדפן, בלי חלון,
בלי הזדהות, ובלי אף שורת פלט על המסך.

הפרוטוקול המאומת (GROUND_TRUTH §9) — הסדר הוא הכול
---------------------------------------------------
::

    0. GET  ...?prgname=S_LOOK_FOR_NOSE&arguments=-N<קוד כלשהו>   <- חימום, חובה
    1. POST ...  PRGNAME=Enter_Search
                 ARGUMENTS=-A,,-A,ChangeYear
                 ChangeYear=2027
    2. GET  ...?prgname=S_LOOK_FOR_NOSE&arguments=-N<קוד>          <- קורס
       GET  ...?prgname=S_LOOK_FOR_NOSE_AB&arguments=-A            <- כל הקטלוג

**שלב 0 אינו אופציונלי.** בלי בקשת החימום ה-POST מחזיר 200 והכותרת אפילו
מציגה תשפ"ז — אבל כל GET שאחריו חוזר בשקט עם **תשפ"ו**. זה נצפה בפועל:
11069 חזר עם 4 קבוצות (תשפ"ו) במקום 2 (תשפ"ז). שנה שגויה בשקט היא הכשל
הגרוע ביותר שהכלי הזה יכול לייצר — מערכת אמינה-למראה של שנה אחרת.

לכן הסדר כאן מקודד כך שאי אפשר להפוך אותו בטעות: ``_step_1_warm_up`` מרים
דגל, ``_step_2_change_year`` מסרב לרוץ בלעדיו, ו-``_step_3_verify_year``
מסרב לרוץ בלי שניהם — ואז **מאמת את השנה על GET נפרד**, לא על תשובת ה-POST,
כי בדיוק שם ההבדל בין "עבד" ל"נראה שעבד".

מה יש כאן
---------
``YedionHTTP.open_session``  — חימום, החלפת שנה, ואימות שהשנה באמת תפסה
``YedionHTTP.fetch_course``  — דף קורס אחד (שומר גולמי לפני פירסור, מאמת שנה)
``YedionHTTP.fetch_catalog`` — כל הקטלוג ב**בקשה אחת**
``YedionHTTP.scrape``        — כמה קודים, סדרתי ומנומס, ממשיך אחרי כישלון

Technical notes (English):
    * **Standard library only** — ``urllib.request`` + ``http.cookiejar``.
      No third-party HTTP client, no browser driver. Nothing here is imported
      from ``src/scraper.py`` on purpose: that module pulls in the browser
      automation library at import time, and this path must work on a machine
      that has no browser installed at all.
    * **This module never calls print().** Every progress line goes through the
      ``log`` callback given to ``__init__`` (``None`` = completely silent), so
      the web app can capture the output into its own buffer instead of it
      appearing on the student's screen. The only ``print`` calls in the file
      live in ``main()``, the command-line smoke test.
    * **Nothing here signs in, and nothing here can.** The protocol is
      anonymous end to end; the cookie jar lives in memory only — it is never
      written to disk and never loaded from it.
    * **Politeness matters more, not less.** Nothing throttles an anonymous
      client, so this one throttles itself: ``delay_s`` between *every* request,
      a normal ``User-Agent``, and exactly **one** request for the whole
      catalog (see ``CATALOG_ARGUMENTS`` — never loop the alphabet).
    * **Testing without a network:** pass ``opener=`` (or the alias
      ``transport=``) to ``__init__``. Anything with an ``.open(request,
      timeout=...)`` method — or any plain callable — is accepted, and it may
      return a real response object, a ``str`` or ``bytes``. Every request is
      recorded in ``request_log`` as ``(method, url)`` **before** it is sent, so
      a test can assert that the warm-up GET precedes the ChangeYear POST. When
      a transport is injected the politeness sleep is skipped (there is no
      server to be polite to) but the delay that *would* have been taken is
      appended to ``waits``.
"""

from __future__ import annotations

import datetime as _dt
import gzip
import html as _html
import importlib
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

__all__ = [
    "BASE_URL",
    "CATALOG_URL",
    "YEDION_HOST",
    "WARMUP_CODE",
    "DEFAULT_YEAR",
    "current_academic_year",
    "DEFAULT_DELAY_S",
    "DEFAULT_TIMEOUT_S",
    "course_url",
    "details_url",
    "PRGNAME_COURSE_DETAILS",
    "hebrew_year_label",
    "YedionHTTPError",
    "YearSwitchError",
    "YearMismatchError",
    "GatedEndpointError",
    "ThrottledError",
    "YedionHTTP",
    "main",
]


# ==========================================================================
# 0. קבועים — כתובות, ארגומנטים וברירות מחדל
# ==========================================================================

#: שורש הפרויקט — כדי ש-"data/raw" ייפתר מול הפרויקט ולא מול תיקיית ההרצה.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: נקודת הקצה היחידה של הידיעון. *כל* המסכים הם אותו aspx עם prgname אחר.
BASE_URL = "https://info.braude.ac.il/yedion/fireflyweb.aspx"

#: המארח היחיד שמותר לשמור ממנו דפים לדיסק. כל דבר אחר = הופנינו לשער.
YEDION_HOST = "info.braude.ac.il"

#: חיפוש קורס לפי קוד — ציבורי, בלי התחברות (GROUND_TRUTH §9).
PRGNAME_COURSE_SEARCH = "S_LOOK_FOR_NOSE"

#: רשימת כל הקורסים — ציבורי גם הוא.
PRGNAME_CATALOG = "S_LOOK_FOR_NOSE_AB"

#: פרטי קורס בודד — נ"ז, שעות, שפת הוראה, תיאור ותנאי קדם.
#: ציבורי בדיוק כמו האחרים (GROUND_TRUTH §1 ו-§9) — בלי התחברות.
PRGNAME_COURSE_DETAILS = "S_CourseDetails"

# --------------------------------------------------------------------------
#  דף ההשהיה — התשובה היחידה של הידיעון שנראית תקינה לגמרי ואינה
# --------------------------------------------------------------------------
# כשחורגים מקצב השאילתות השרת עונה **סטטוס 200**, מאותו host, עם כ-100 בתים:
#   "השהיית גישה זמנית: כתובת IP: …<br>יותר מידי שאילתות בדקה<br>…"
# ובגרסה השעתית: "יותר מידי שאילתות בשעה<br>ניתן לנסות שוב החל משעה 21:00".
# שום בדיקה אחרת במודול הזה לא תופסת אותו: המארח נכון, הסטטוס נכון, ואין בו
# שנה — ולכן גם ``_assert_page_year`` שותק. בלי הזיהוי כאן הוא היה נשמר
# כ-HTML גולמי, נשלח לפרסר, וחוזר כקורס בלי נ"ז, בלי תנאי קדם ובלי תיאור —
# ואז נשמר במטמון לשבוע (SPEC_MULTIFACULTY §2). זה בדיוק ה-0.0 שנראה אמיתי.
_THROTTLE_MARKERS: tuple[str, ...] = (
    "השהיית גישה זמנית",
    "יותר מידי שאילתות",
    "יותר מדי שאילתות",
)

#: סימנים שיש בכל דף פרטי קורס אמיתי — כולל דף של קורס שאינו נפתח, שהוא
#: דף חלקי **תקין** ובכל זאת 18KB. שניהם נמדדו בשני ה-fixtures האמיתיים.
_DETAILS_PAGE_MARKERS: tuple[str, ...] = (
    "fcontainer",
    "פרטים נוספים על הקורס המבוקש",
)

#: מתחת לזה זה כבר לא דף. הדפים האמיתיים הם 17–26KB.
_DETAILS_MIN_CHARS = 1024

#: המסך היחיד שכן חסום לאנונימיים. משמש **רק** ל-POST של החלפת השנה,
#: שעובד גם בלי הזדהות אחרי בקשת החימום.
PRGNAME_ENTER_SEARCH = "Enter_Search"

#: הארגומנטים של החלפת שנת לימודים (GROUND_TRUTH §8 ו-§9).
ARGS_CHANGE_YEAR = "-A,,-A,ChangeYear"

#: שם השדה שנושא את השנה הלועזית ב-POST.
YEAR_FIELD = "ChangeYear"

# --------------------------------------------------------------------------
#  !!! חשוב מאוד — לא "לתקן" את זה ללולאה על אותיות הא"ב !!!
# --------------------------------------------------------------------------
# הארגומנט של מסך הקטלוג *נראה* כמו אות עברית ("-Aא"), אבל נבדק מול מופע חי:
# השרת מתעלם מהאות ומחזיר את כל הקטלוג בכל מקרה — "-Aא", "-Aמ" ו-"-A" החזירו
# תשובות זהות בייט-בייט. לולאה על 22 אותיות = פי 22 עומס על השרת של המכללה
# עבור בדיוק אותם נתונים. אסור. (ראו גם discovery.CATALOG_ARGUMENTS.)
CATALOG_ARGUMENTS = "-A"

#: הבקשה היחידה שמביאה את כל הקטלוג. אותו ערך כמו ``discovery.CATALOG_URL``,
#: משוכפל כאן בכוונה כדי שלמודול הזה לא תהיה תלות ייבוא ב-bs4.
CATALOG_URL = f"{BASE_URL}?prgname={PRGNAME_CATALOG}&arguments={CATALOG_ARGUMENTS}"

#: הקוד שמשמש לבקשת החימום. GROUND_TRUTH §9 כותב במפורש
#: ``arguments=-N<any code>`` — לחימום לא משנה *מה* התשובה, רק שהיא תיפתח
#: סשן. לכן נבחר כאן קוד **שאינו קורס אמיתי**, משתי סיבות:
#:   1. קוד שאינו קיים מחזיר דף 200 תקין ובלי קבוצות (GROUND_TRUTH §6) —
#:      בדיוק מה שצריך, ובלי לבזבז דף אמיתי.
#:   2. אילו היה זה קוד אמיתי, סטודנט/ית שמבקש/ת דווקא אותו היה גורם לשתי
#:      בקשות לאותו דף באותה ריצה — בזבוז וחוסר נימוס כלפי שרת המכללה.
#: אפשר להחליף דרך הפרמטר ``warmup_code`` אם אי פעם יתברר שהאתר דורש קוד קיים.
WARMUP_CODE = "99999"

def current_academic_year(today: "_dt.date | None" = None) -> str:
    """השנה האקדמית הלועזית הנוכחית — ``"2027"`` פירושו תשפ"ז.

    שנת הלימודים בישראל נפתחת באוקטובר, ולכן מאוגוסט והלאה כבר מתייחסים
    לשנה הבאה. **לא לקבע כאן מספר**: ערך קבוע היה נכון השנה ושקט-ושגוי
    בשנה הבאה, וזה בדיוק סוג הכשל שהפרויקט הזה נכווה ממנו שוב ושוב.
    """
    day = today or _dt.date.today()
    return str(day.year + 1) if day.month >= 8 else str(day.year)


#: ברירת מחדל לשנה, מחושבת בזמן הייבוא. הידיעון נפתח על השנה הקודמת,
#: ולכן ברירת מחדל שקטה הייתה מסוכנת.
DEFAULT_YEAR = current_academic_year()

#: השהיה בין בקשות. אין מי שיחסום אותנו — לכן אנחנו חוסמים את עצמנו.
# ‏3.0 ולא 1.2. ב-2026-09-01 ריצה של 571 קורסים ב-1.2 שניות (כ-50 בקשות
# לדקה) הפעילה את מגבלת הקצב של הידיעון: הוא החזיר 200 עם דף
# "השהיית גישה זמנית … יותר מידי שאילתות בשעה … ניתן לנסות שוב החל משעה 21:00",
# והדף הזה נשמר על גבי שישה דמפים תקינים. הקטלוג כולו עדיין נגמר בפחות מחצי
# שעה בקצב הזה, וזה בהחלט מספיק למשימה יומית.
DEFAULT_DELAY_S = 3.0

#: פסק זמן לבקשה בודדת.
DEFAULT_TIMEOUT_S = 45.0

#: User-Agent רגיל. שרתי WebForms ותיקים לפעמים מתנהגים אחרת מול מחרוזת
#: חריגה, ואנחנו רוצים בדיוק את מה שהדפדפן היה מקבל.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

#: כותרות קבועות לכל בקשה. עברית לפני אנגלית — הידיעון מגיש עברית ממילא.
BASE_HEADERS: dict[str, str] = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def course_url(code: str) -> str:
    """
    בונה את כתובת ה-GET של דף התוצאות לקוד קורס.

    ``-N`` = ארגומנט מספרי; קודי קורס תמיד מספריים (GROUND_TRUTH §1).

    >>> course_url("61753")
    'https://info.braude.ac.il/yedion/fireflyweb.aspx?prgname=S_LOOK_FOR_NOSE&arguments=-N61753'
    """
    clean = str(code).strip()
    return (
        f"{BASE_URL}?prgname={PRGNAME_COURSE_SEARCH}"
        f"&arguments=-N{quote(clean, safe='')}"
    )


def _details_argument(value: object, default: str) -> str:
    """ארגומנט אחד של ‎S_CourseDetails‎ — ריק חוזר לברירת המחדל, ותמיד מקודד."""
    text = str(value if value is not None else "").strip()
    return quote(text or default, safe="")


def details_url(
    code: str,
    semester_code: str = "1",
    kind_code: str = "1",
    group_id: str = "0",
) -> str:
    """
    בונה את כתובת ה-GET של דף **פרטי הקורס** (``S_CourseDetails``).

    זה המסך שנושא את מה שחסר לכל שאר הקטלוג: נקודות זכות, פירוק שעות,
    שעות סמסטריאליות, שפת הוראה, תיאור ותנאי קדם. הוא ציבורי בדיוק כמו
    ``S_LOOK_FOR_NOSE`` — אין כאן התחברות ואין סיסמה (GROUND_TRUTH §9).

    צורת הארגומנטים מתועדת ב-GROUND_TRUTH §1 ונלקחה מכפתורי "פרטים נוספים"
    שבדף התוצאות::

        arguments=-N<course>,-N<sem>,-N<kind>,-N<group>,-N

    ברירות המחדל (``sem=1``, ``kind=1``, ``group=0``) הן מה שמחזיר את דף
    ה"כללי" של הקורס — בדיוק הדף ששני ה-fixtures האמיתיים נשמרו ממנו. הן
    לא תלויות במחלקה ולא בתוכנית לימודים כלשהי, וזו הנקודה: פרטי קורס הם
    נתון של הקורס, לא של הסטודנט/ית.

    Args:
        code: קוד הקורס, למשל ``"61753"``.
        semester_code: קוד הסמסטר בידיעון (``"1"`` / ``"2"``).
        kind_code: קוד סוג המקצוע (1 = הרצאה, 9 = תרגיל וכו').
        group_id: מזהה הקבוצה. ``"0"`` = הקורס כולו, בלי קבוצה מסוימת.

    Returns:
        כתובת GET מלאה.

    >>> details_url("61753")
    'https://info.braude.ac.il/yedion/fireflyweb.aspx?prgname=S_CourseDetails&arguments=-N61753,-N1,-N1,-N0,-N'
    """
    arguments = ",".join(
        (
            f"-N{_details_argument(code, '')}",
            f"-N{_details_argument(semester_code, '1')}",
            f"-N{_details_argument(kind_code, '1')}",
            f"-N{_details_argument(group_id, '0')}",
            "-N",
        )
    )
    return f"{BASE_URL}?prgname={PRGNAME_COURSE_DETAILS}&arguments={arguments}"


# ==========================================================================
# 1. חריגות
# ==========================================================================
class YedionHTTPError(Exception):
    """בסיס לכל תקלות השליפה ב-HTTP — נוח לתפוס את כולן במכה אחת."""


class YearMismatchError(YedionHTTPError):
    """
    דף שהתקבל מצהיר על שנת לימודים אחרת מזו שביקשנו.

    זו השמירה שתופסת בדיוק את הכשל של GROUND_TRUTH §9. ההודעה תמיד מציינת
    את שתי השנים — המבוקשת ומה שכתוב בדף.
    """


class YearSwitchError(YearMismatchError):
    """
    החלפת שנת הלימודים של הסשן לא אושרה.

    **מקרה פרטי של אי-התאמת שנה**, ולכן יורש מ-``YearMismatchError``: הסשן
    עומד על שנה שאינה זו שביקשנו, בדיוק כמו דף שמצהיר על שנה אחרת. מי שרוצה
    לתפוס "כל בעיית שנה" יתפוס את ``YearMismatchError`` ויקבל גם את זה.

    זה כמעט תמיד אומר דבר אחד: בקשת החימום לא בוצעה, או שנכשלה בשקט.
    """


class GatedEndpointError(YedionHTTPError):
    """
    הבקשה הופנתה אל מחוץ לידיעון — כלומר אל שער ההתחברות.

    נכון להיום זה לא אמור לקרות ב-``S_LOOK_FOR_NOSE``; אם זה קורה, המכללה
    כנראה סגרה את נקודות הקצה הציבוריות, וזה היום שבשבילו נשמר מסלול
    הדפדפן (``refresh.py --browser``).
    """


class ThrottledError(YedionHTTPError):
    """הידיעון החזיר דף "השהיית גישה זמנית" במקום את התוכן.

    **תקלה זמנית, לא תשובה.** השרת מגביל שאילתות לדקה ולשעה, ועונה 200 עם
    כמאה בתים של "יותר מידי שאילתות". מי שתופס אותה צריך להמתין (ולהאט את
    ``delay_s``) ולנסות שוב — ובשום אופן לא לשמור את התוצאה: רשומה ריקה
    שנשמרת עכשיו נראית כמו קורס בלי נ"ז ובלי תנאי קדם, ונתקעת ככזאת לשבוע.

    יורשת מ-``YedionHTTPError`` כדי שקוד קיים שתופס "כל תקלת שליפה" ימשיך
    לעבוד — אבל מי שרוצה להאט ולנסות שוב יכול לתפוס דווקא אותה.
    """


# ==========================================================================
# 2. שנת לימודים — המרה, נורמליזציה וזיהוי בתוך הדף
# ==========================================================================
#: גימטריה: ערך -> אות, מהגדול לקטן (המרה חמדנית).
_GEMATRIA: tuple[tuple[int, str], ...] = (
    (400, "ת"), (300, "ש"), (200, "ר"), (100, "ק"),
    (90, "צ"), (80, "פ"), (70, "ע"), (60, "ס"), (50, "נ"),
    (40, "מ"), (30, "ל"), (20, "כ"), (10, "י"),
    (9, "ט"), (8, "ח"), (7, "ז"), (6, "ו"), (5, "ה"),
    (4, "ד"), (3, "ג"), (2, "ב"), (1, "א"),
)

#: אותיות סופיות -> רגילות. הידיעון כותב תש"ף בפ' סופית ואנחנו מחשבים תש"פ.
_FINAL_LETTERS = str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"})

#: תשפ"ז = 5787, ו-5787 - 3760 = 2027.
_HEBREW_YEAR_OFFSET = 3760


def hebrew_year_label(gregorian: str | int) -> str:
    """
    ``2027`` -> ``'תשפ"ז'``. מחזיר "" אם הקלט אינו שנה סבירה.

    הידיעון מקבל שנה לועזית ב-``<option value>`` אבל *מציג* עברית בכותרת,
    ולכן צריך את שתי הצורות כדי לאמת שההחלפה תפסה.
    """
    try:
        n = int(str(gregorian).strip())
    except (TypeError, ValueError):
        return ""
    if not (1900 <= n <= 2200):
        return ""

    remainder = (n + _HEBREW_YEAR_OFFSET) % 1000  # את ה"ה' אלפים" לא כותבים
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


def _normalize_year(value: str | int | None) -> str | None:
    """
    מנרמל את הפרמטר ``year`` של הלקוח.

    * ``None``  -> ``DEFAULT_YEAR``. **בכוונה**: הידיעון נפתח על השנה
      הקודמת, ולכן "לא ציינו שנה" חייב להיות "השנה שהכלי נבנה עבורה"
      ולא "מה שהאתר יחליט". שנה שגויה בשקט היא הכשל הגרוע ביותר כאן.
    * ``""`` / ``"none"`` / ``"off"`` / ``"-"`` -> ``None`` = במפורש לא
      נוגעים בשנה (קיים כדי לבדוק מה האתר מחזיר בברירת המחדל שלו).
    * כל דבר אחר -> המחרוזת המנוקה.
    """
    if value is None:
        # מחושב מחדש ולא הקבוע הקפוא, כדי שתהליך שרץ לאורך זמן
        # ויחצה שנה אקדמית לא יישאר תקוע על השנה שבה הופעל.
        return current_academic_year()
    text = str(value).strip()
    if text.casefold() in ("", "none", "off", "-"):
        return None
    return text


def _normalize_hebrew_year(text: str) -> str:
    """``'תשפ"ז'`` ו-``'תשפ&quot;ז'`` -> ``'תשפז'`` — צורת השוואה בלבד."""
    if not text:
        return ""
    t = _html.unescape(str(text)).translate(_FINAL_LETTERS)
    return "".join(ch for ch in t if "א" <= ch <= "ת")


#: כותרת דף קורס: ``קורס מתמטיקה ב' שנה"ל תשפ"ז``.
_COURSE_YEAR_RE = re.compile(r"שנה\s*[\"'׳״]?\s*ל\s*(תש[א-ת\"'׳״]{1,10})")

#: התווית ``שנה"ל`` לבדה — סימן לכך שהדף בכלל *מנסה* להצהיר על שנה.
_COURSE_YEAR_LABEL_RE = re.compile(r"שנה\s*[\"'׳״]?\s*ל(?![א-ת])")

#: כותרת דף החיפוש/הקטלוג: ``חיפוש קורסים במערכת תשפ"ז``.
_HEADER_YEAR_RE = re.compile(r"במערכת\s*(תש[א-ת\"'׳״]{1,10})")

#: ``<option selected value="2027">`` — סימן משני שהחלפת השנה תפסה.
_SELECTED_YEAR_RE = re.compile(
    r"<option[^>]*\bselected\b[^>]*\bvalue\s*=\s*[\"']?((?:19|20)\d{2})",
    re.IGNORECASE,
)
_SELECTED_YEAR_ALT_RE = re.compile(
    r"<option[^>]*\bvalue\s*=\s*[\"']?((?:19|20)\d{2})[\"']?[^>]*\bselected\b",
    re.IGNORECASE,
)


def _course_year_label(page_html: str) -> str:
    """תווית השנה מכותרת דף קורס (``שנה"ל תשפ"X``), או ""."""
    if not page_html:
        return ""
    m = _COURSE_YEAR_RE.search(_html.unescape(str(page_html)))
    return m.group(1).strip() if m else ""


def _header_year_label(page_html: str) -> str:
    """תווית השנה מכותרת דף החיפוש (``במערכת תשפ"ז``), או ""."""
    if not page_html:
        return ""
    m = _HEADER_YEAR_RE.search(_html.unescape(str(page_html)))
    return m.group(1).strip() if m else ""


def _selected_year_value(page_html: str) -> str:
    """השנה הלועזית שמסומנת כרגע בבורר השנה, או ""."""
    if not page_html:
        return ""
    text = str(page_html)
    for pattern in (_SELECTED_YEAR_RE, _SELECTED_YEAR_ALT_RE):
        m = pattern.search(text)
        if m:
            return m.group(1)
    return ""


# --- גשר עצל אל parser.extract_page_year -----------------------------------
#: None = עוד לא ניסינו, False = ניסינו ואין (לא מנסים שוב בכל דף).
_EXTRACT_PAGE_YEAR: object = None


def _load_extract_page_year():
    """
    ייבוא **עצל** של ``parser.extract_page_year``.

    עצל בכוונה: הפרסר מושך את bs4/lxml, וקריאת השנה חייבת לעבוד גם בלעדיהם
    (יש כאן רגקסים שעושים את אותה עבודה על דף רגיל). אם הייבוא נכשל —
    מחזירים None והקורא נופל לרגקס.
    """
    global _EXTRACT_PAGE_YEAR
    if _EXTRACT_PAGE_YEAR is not None:
        return _EXTRACT_PAGE_YEAR or None

    for module_name in ("parser", "src.parser"):
        try:
            module = importlib.import_module(module_name)
        except Exception:  # noqa: BLE001 - כל תקלת ייבוא => נופלים לרגקס
            continue
        func = getattr(module, "extract_page_year", None)
        if callable(func):
            _EXTRACT_PAGE_YEAR = func
            return func

    _EXTRACT_PAGE_YEAR = False
    return None


def _coerce_year_value(value: object) -> str:
    """הופך את מה ש-``extract_page_year`` החזיר למחרוזת אחת, בסובלנות."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("gregorian", "year", "label", "hebrew", "year_label"):
            got = value.get(key)
            if isinstance(got, str) and got.strip():
                return got.strip()
        return ""
    if isinstance(value, (list, tuple)):
        for item in value:
            got = _coerce_year_value(item)
            if got:
                return got
        return ""
    return str(value).strip()


def _year_matches(found: str, want_gregorian: str) -> bool | None:
    """
    האם השנה שנמצאה בדף היא זו שביקשנו?

    Returns:
        ``True`` / ``False``, או **``None``** אם אי אפשר להכריע — ואז לא
        זורקים כלום: עדיף לא לחסום ריצה תקינה בגלל ניסוח שלא הכרנו.
    """
    if not found or not want_gregorian:
        return None

    m = re.search(r"(?:19|20)\d{2}", str(found))
    if m:  # שנה לועזית בטקסט — ההשוואה החדה ביותר.
        return m.group(0) == str(want_gregorian).strip()

    want_label = _normalize_hebrew_year(hebrew_year_label(want_gregorian))
    got_label = _normalize_hebrew_year(found)
    if want_label and got_label:
        return want_label == got_label
    return None


# ==========================================================================
# 3. עזרי דף ורשת
# ==========================================================================
#: כל בלוק קבוצה בדף תוצאות מביא כפתור "פרטים נוספים" ותווית ``קבוצה :``.
_GROUP_MARKERS = ("S_CourseDetails", "קבוצה :", "קבוצה:")

#: הכפתור שמופיע בכל שורת קורס בדף הקטלוג. ה-lookahead מונע ספירה של
#: ``S_LOOK_FOR_NOSE_AB`` (כפתור הקטלוג עצמו) כאילו היה שורת קורס.
_CATALOG_ROW_RE = re.compile(PRGNAME_COURSE_SEARCH + r"(?!_)")


def count_group_blocks(page_html: str) -> int:
    """
    ספירה גסה של **בלוקי קבוצה בדף** — "יש כאן משהו או שהדף ריק?".

    שימו לב: זה **לא** מספר הקבוצות שיישמרו במסד. הידיעון מציג את שני
    הסמסטרים באותו עמוד ומפצל קבוצה לכמה בלוקים, ולכן המספר כאן גדול
    מהאמת — 11069 מראה 4 בלוקים והם 2 קבוצות. הספירה האמיתית היא של
    ``parser.parse_course_page``. המספר כאן משמש רק כאינדיקציה "הדף לא ריק",
    ולכן כל הודעה שמשתמשת בו אומרת במפורש "בלוקים" ולא "קבוצות" — אחרת
    היה אפשר לבלבל בינו לבין הסימן של השנה השגויה מ-GROUND_TRUTH §9.
    """
    if not page_html:
        return 0
    text = _html.unescape(str(page_html))
    return max(text.count(marker) for marker in _GROUP_MARKERS)


def count_catalog_rows(page_html: str) -> int:
    """ספירה גסה של שורות קורס בדף הקטלוג (571 בקטלוג של תשפ"ז)."""
    if not page_html:
        return 0
    return len(_CATALOG_ROW_RE.findall(_html.unescape(str(page_html))))


def _host_of(url: str) -> str:
    """שם המארח מתוך URL, באותיות קטנות, בלי משתמש ובלי פורט."""
    try:
        netloc = urlparse(str(url)).netloc.lower()
    except ValueError:
        return ""
    host = netloc.rsplit("@", 1)[-1]
    if ":" in host:
        head, _, tail = host.rpartition(":")
        if tail.isdigit():
            host = head
    return host.strip("[]")


def _is_yedion_url(url: str) -> bool:
    """
    האם ה-URL הזה הוא של הידיעון עצמו?

    זו גם הבדיקה שמחליטה אם מותר לכתוב את הדף ל-``data/raw``: דף שאינו של
    הידיעון הוא, בהגדרה, שער ההתחברות — ואותו לא כותבים לדיסק לעולם.
    ההשוואה היא על רכיבי הדומיין, כדי ש-"notinfo.braude.ac.il" לא ייחשב
    בטעות כתקין.
    """
    host = _host_of(url)
    return host == YEDION_HOST or host.endswith("." + YEDION_HOST)


#: ``<meta charset="utf-8">`` או ``content="text/html; charset=windows-1255"``.
_META_CHARSET_RE = re.compile(rb"""charset\s*=\s*["']?\s*([A-Za-z0-9_\-]+)""", re.I)


def _decode_body(raw: bytes, header_charset: str = "") -> str:
    """
    ממיר את גוף התשובה למחרוזת — **בלי לזרוק לעולם**.

    סדר הניסיונות: הקידוד מכותרת ה-HTTP, ``<meta charset>`` שבתחילת הדף,
    utf-8 (מה שהידיעון מגיש בפועל), windows-1255 (עברית ישנה), ולבסוף
    utf-8 עם ``errors="replace"``. דף עברי פגום עדיף על חריגה באמצע רענון.
    """
    if not raw:
        return ""

    # יש שרתים שמכווצים גם בלי שביקשנו. זול לבדוק, יקר לפספס.
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError, ValueError):
            pass

    candidates: list[str] = []
    if header_charset:
        candidates.append(header_charset)
    meta = _META_CHARSET_RE.search(raw[:4096])
    if meta:
        try:
            candidates.append(meta.group(1).decode("ascii", "ignore"))
        except Exception:  # noqa: BLE001 - קידוד לא קריא הוא רק רמז
            pass
    candidates += ["utf-8", "windows-1255"]

    seen: set[str] = set()
    for enc in candidates:
        name = (enc or "").strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            return raw.decode(name)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _charset_of(response: object) -> str:
    """הקידוד מכותרת ה-HTTP, אם יש. סובלני לתשובות מזויפות של בדיקות."""
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    getter = getattr(headers, "get_content_charset", None)
    if callable(getter):
        try:
            return str(getter() or "")
        except Exception:  # noqa: BLE001
            return ""
    try:
        content_type = str(headers.get("Content-Type", ""))
    except Exception:  # noqa: BLE001
        return ""
    m = re.search(r"charset\s*=\s*([A-Za-z0-9_\-]+)", content_type, re.I)
    return m.group(1) if m else ""


def _final_url(response: object, fallback: str) -> str:
    """ה-URL שממנו הגיעה התשובה בפועל (אחרי הפניות), או ``fallback``."""
    getter = getattr(response, "geturl", None)
    if callable(getter):
        try:
            url = getter()
            if url:
                return str(url)
        except Exception:  # noqa: BLE001
            pass
    url = getattr(response, "url", "")
    return str(url) if url else str(fallback)


def _status_of(response: object) -> int:
    """קוד הסטטוס, עם ברירת מחדל 200 לתשובות מזויפות שאין להן כזה."""
    for attr in ("status", "code"):
        value = getattr(response, attr, None)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 200


# ==========================================================================
# 4. YedionHTTP — הלקוח עצמו
# ==========================================================================
class YedionHTTP:
    """
    לקוח HTTP לידיעון של בראודה, **בלי התחברות ובלי דפדפן**.

    שימוש טיפוסי::

        client = YedionHTTP(year="2027", log=logger.append)
        client.open_session()               # חימום -> החלפת שנה -> אימות
        pages = client.scrape(["61753", "61756"])
        for code, message in client.errors:
            ...

    שדות ציבוריים שימושיים:
        ``errors``      — ``[(code, message), ...]`` — קורס שנכשל לא עוצר את השאר.
        ``year_label``  — תווית השנה שאומתה בפועל, למשל ``'תשפ"ז'``.
        ``request_log`` — ``[(method, url), ...]`` לפי סדר, כולל בקשות שנכשלו.
        ``waits``       — ההשהיות שנלקחו (או שהיו נלקחות) לפי סדר.
        ``dumps``       — הנתיבים של קבצי ה-HTML הגולמיים שנשמרו.
    """

    def __init__(
        self,
        year: str | None = None,
        delay_s: float = DEFAULT_DELAY_S,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        raw_dir: str | None = "data/raw",
        log: Callable[[str], None] | None = None,
        *,
        opener: object | None = None,
        transport: object | None = None,
        warmup_code: str = WARMUP_CODE,
        user_agent: str = USER_AGENT,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        """
        Args:
            year: שנת הלימודים ה**לועזית**, למשל ``"2027"`` עבור תשפ"ז.
                ``None`` = ברירת המחדל ``DEFAULT_YEAR`` (2027 = תשפ"ז), ולא
                "בלי לגעת בשנה": הידיעון נפתח על השנה הקודמת, ושתיקה כאן
                הייתה מחזירה בשקט את המערכת של אשתקד. מי שבכל זאת רוצה את
                ברירת המחדל של האתר — ``year=""`` (או ``"none"``).
            delay_s: השהיה בין בקשות. נימוס כלפי השרת של המכללה. 0 = בלי.
            timeout_s: פסק זמן לבקשה בודדת.
            raw_dir: לאן נשמרים דפי ה-HTML הגולמיים. ``None`` = לא לשמור.
                נתיב יחסי נפתר מול שורש הפרויקט.
            log: פונקציית יומן. ``None`` = **שקט מוחלט**. המודול הזה לעולם
                לא מדפיס בעצמו — כך הפלט מגיע ליומן של האפליקציה ולא למסך.
            opener / transport: הזרקה לבדיקות (שני השמות שקולים). כל אובייקט
                עם ``.open(request, timeout=...)`` או כל callable. אפשר גם
                להציב אחרי היצירה: ``client.opener = fake``.
            warmup_code: הקוד לבקשת החימום.
            user_agent: מחרוזת ה-User-Agent.
            sleep: פונקציית ההשהיה (ניתנת להחלפה בבדיקות).
        """
        self.year = _normalize_year(year)
        self.delay_s = float(delay_s)
        self.timeout_s = float(timeout_s)
        self.raw_dir: Path | None = self._resolve(raw_dir) if raw_dir else None
        self.log = log
        self.warmup_code = str(warmup_code).strip() or WARMUP_CODE
        self.user_agent = str(user_agent or USER_AGENT)

        #: צנצנת עוגיות **בזיכרון בלבד** — לא נכתבת לדיסק ולא נטענת ממנו.
        #: הסשן של הידיעון הוא Yedion.MySession + TS0188c6f2, ותו לא. אין בו
        #: שום פרט אישי, כי אין כאן שום הזדהות.
        self.cookies = CookieJar()

        self.errors: list[tuple[str, str]] = []
        self.year_label: str = ""
        #: נדלק כשהידיעון החזיר דף השהיית-גישה. הריצה נעצרת, ומה שנשאר
        #: נרשם ב-``skipped`` — "לא נוסה", שזה מידע אחר לגמרי מ"נכשל".
        self.throttled: bool = False
        self.skipped: list[str] = []
        #: האם השנה אומתה כבר על דף אמיתי. False = האימות נדחה לדף הקורס
        #: הראשון, שם _assert_page_year אוכף אותו ממילא.
        self._year_verified: bool = False
        self.request_log: list[tuple[str, str]] = []
        self.waits: list[float] = []
        self.dumps: list[Path] = []
        self.session_ready: bool = False

        #: ה-opener בפועל. ``None`` = ייבנה בבקשה הראשונה. זו התכונה שאפשר
        #: להציב עליה opener מזויף בבדיקות.
        self.opener = opener if opener is not None else transport
        self._injected = self.opener is not None
        self._sleep = sleep if callable(sleep) else None
        self._requests_made = 0
        self._last_request_at = 0.0
        self._dump_counters: dict[str, int] = {}

        # דגלי הסדר. אלה מה שהופך את הפרוטוקול של §9 לבלתי-הפיך בטעות.
        self._warmed_up = False
        self._year_posted = False

    # ------------------------------------------------------------ תשתית
    @staticmethod
    def _resolve(path_like: str | Path) -> Path:
        """נתיב יחסי נפתר מול שורש הפרויקט, לא מול תיקיית ההרצה."""
        p = Path(path_like)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    def _emit(self, message: str) -> None:
        """
        שורת יומן אחת. **זו הדרך היחידה שבה המודול הזה מוציא טקסט.**

        ``log=None`` (ברירת המחדל) = שקט מוחלט. אין כאן print בשום מקום:
        זה בדיוק מה שגרם ל"שורות קוד שמופיעות על המסך" ברענון הישן.
        יומן שנשבר לא יפיל רענון — לכן ה-try.
        """
        callback = self.log
        if callback is None:
            return
        try:
            callback(str(message))
        except Exception:  # noqa: BLE001 - יומן הוא נוחות, לא תנאי להצלחה
            pass

    # ------------------------------------------------------------- נימוס
    def _polite_wait(self) -> None:
        """
        ממתין ``delay_s`` שניות לפני כל בקשה — חוץ מהראשונה.

        אין יותר login שמאט אותנו, ולכן ההאטה היא באחריותנו. ההשהיה היא
        בדיוק ``delay_s`` (ולא "ההפרש שנותר"), כדי שההתנהגות תהיה צפויה
        וניתנת לבדיקה. ``delay_s=0`` = בלי המתנה בכלל.

        ``time.sleep`` נקראת דרך המודול ולא נשמרת מראש, כדי שהחלפה שלה
        בבדיקות תעבוד גם אם היא בוצעה אחרי יצירת האובייקט. כשהוזרק
        transport ישירות ל-``__init__`` לא ישנים באמת — אין שרת לנמס אליו —
        אבל ההשהיה נרשמת ב-``waits`` כך שאפשר לבדוק אותה.
        """
        delay = max(0.0, float(self.delay_s))
        if delay <= 0 or self._requests_made == 0:
            return  # לפני הבקשה הראשונה אין למה לחכות
        self.waits.append(delay)
        if self._injected:
            return
        sleeper = self._sleep if self._sleep is not None else time.sleep
        sleeper(delay)

    # -------------------------------------------------------------- רשת
    def _build_opener(self):
        """
        בונה opener עם צנצנת עוגיות. נבנה **בעצלתיים** — יצירת המחלקה עצמה
        לא נוגעת ברשת ולא בקבצים.
        """
        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies)
        )

    def _ensure_opener(self):
        """
        מחזיר את ה-opener, ובונה אותו בפעם הראשונה.

        השם הזה **אינו** ``_opener`` בכוונה: ``self.opener`` היא התכונה
        שמחזיקה את האובייקט, ובדיקה שמזריקה opener עושה זאת בדיוק על השם
        הזה. מתודה בשם ``_opener`` הייתה מתנגשת עם ההזרקה.
        """
        if self.opener is None:
            self.opener = self._build_opener()
        return self.opener

    def _perform(self, request: urllib.request.Request):
        """שולח את הבקשה דרך ה-opener (אמיתי או מוזרק)."""
        opener = self._ensure_opener()
        open_fn = getattr(opener, "open", None)
        if open_fn is None:
            if not callable(opener):
                raise YedionHTTPError(
                    "ה-opener שהוזרק אינו ניתן לשימוש: אין לו .open והוא אינו "
                    "callable. (injected opener is unusable)"
                )
            open_fn = opener
        try:
            return open_fn(request, timeout=self.timeout_s)
        except TypeError:
            if not self._injected:
                raise
            # transport פשוט של בדיקות שלא מקבל timeout — מנסים בלעדיו.
            return open_fn(request)

    def _request(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        what: str = "",
    ) -> str:
        """
        בקשה אחת, מנומסת, עם כל בדיקות השפיות — ומחזירה טקסט.

        Raises:
            GatedEndpointError: אם נחתנו מחוץ ל-info.braude.ac.il.
            YedionHTTPError: כל תקלת רשת/HTTP אחרת.
        """
        label = what or url
        self._polite_wait()

        all_headers = dict(BASE_HEADERS)
        all_headers["User-Agent"] = self.user_agent
        if headers:
            all_headers.update(headers)

        request = urllib.request.Request(
            url, data=data, headers=all_headers, method=method
        )

        # נרשם **לפני** השליחה: כך הסדר נשמר גם כשבקשה נכשלת, וזו הרשימה
        # שבודקים בה שהחימום קדם ל-POST של החלפת השנה.
        self.request_log.append((method, url))

        try:
            response = self._perform(request)
        except urllib.error.HTTPError as exc:
            # HTTPError הוא גם תשובה — קודם בודקים לאן הוא מפנה.
            if not _is_yedion_url(_final_url(exc, url)):
                raise GatedEndpointError(self._gated_message(label)) from exc
            raise YedionHTTPError(
                f"{label}: השרת החזיר שגיאת HTTP {exc.code}. "
                f"(HTTP {exc.code} from the yedion)"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise YedionHTTPError(
                f"{label}: הבקשה נכשלה ברמת הרשת ({type(exc).__name__}: {exc}). "
                "ייתכן שאין חיבור לאינטרנט או שהאתר של המכללה למטה. "
                "(network-level failure)"
            ) from exc
        finally:
            self._requests_made += 1
            self._last_request_at = time.monotonic()

        try:
            text, final, status = self._read(response, url)
        finally:
            closer = getattr(response, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:  # noqa: BLE001
                    pass

        if not _is_yedion_url(final):
            raise GatedEndpointError(self._gated_message(label))
        if status >= 400:
            raise YedionHTTPError(
                f"{label}: השרת החזיר סטטוס {status}. (unexpected status)"
            )
        return text

    def _read(self, response: object, url: str) -> tuple[str, str, int]:
        """
        קורא תשובה ומחזיר ``(טקסט, url סופי, סטטוס)``.

        סובלני בכוונה: תשובה מזויפת בבדיקות יכולה להיות אובייקט עם ``read``,
        או פשוט ``str``/``bytes``.
        """
        raw: object = response
        reader = getattr(response, "read", None)
        if callable(reader):
            raw = reader()

        if isinstance(raw, str):
            text = raw
        elif isinstance(raw, (bytes, bytearray, memoryview)):
            text = _decode_body(bytes(raw), _charset_of(response))
        else:
            text = str(raw)

        return text, _final_url(response, url), _status_of(response)

    @staticmethod
    def _gated_message(label: str) -> str:
        return (
            f"{label}: הבקשה הופנתה אל מחוץ לידיעון — כנראה אל שער ההתחברות. "
            "ייתכן שהמכללה סגרה את נקודות הקצה הציבוריות. אפשר לנסות את "
            "המסלול עם הדפדפן: refresh.py --browser. "
            "(redirected off the yedion; the public endpoints may now be gated)"
        )

    # ------------------------------------------------------------- שמירה
    def _highest_existing(self, name: str) -> int:
        """המספר הרץ הגבוה ביותר שכבר קיים לשם הזה ב-raw_dir."""
        if self.raw_dir is None:
            return 0
        best = 0
        try:
            for path in self.raw_dir.glob(f"{name}_*.html"):
                m = re.search(r"_(\d+)\.html$", path.name)
                if m:
                    best = max(best, int(m.group(1)))
        except OSError:
            return 0
        return best

    def _next_index(self, name: str) -> int:
        """
        מספר רץ לקובץ הדמפ.

        ``reparse.py`` בוחר תמיד את המספר **הגבוה ביותר** לכל קוד, ולכן
        הכתיבה הראשונה בריצה דורסת את הקובץ הגבוה הקיים ולא נכתבת מתחתיו —
        אחרת פענוח מחדש היה קורא דף ישן ומחזיר נתונים של אתמול.
        """
        if name in self._dump_counters:
            self._dump_counters[name] += 1
        else:
            self._dump_counters[name] = max(1, self._highest_existing(name))
        return self._dump_counters[name]

    def dump_html(self, name: str, html: str) -> Path | None:
        """
        שומר HTML גולמי ל-``raw_dir/<name>_<n>.html``.

        **חוק ברזל: קוראים לזה לפני שמישהו מפרסר.** זה מה שמאפשר ל-
        ``reparse.py`` לרוץ בלי רשת, וזה מה שמאפשר לתקן פרסר בלי לגרד שוב.
        כישלון בשמירה לא מפיל שליפה — רק נרשם ביומן.
        """
        if self.raw_dir is None:
            return None
        path = self.raw_dir / f"{name}_{self._next_index(name)}.html"
        try:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            # encoding="utf-8" חובה — הידיעון כולו בעברית.
            path.write_text(str(html), encoding="utf-8", errors="replace")
        except OSError as exc:
            self._emit(f"אזהרה: שמירת ה-HTML הגולמי נכשלה ({type(exc).__name__}: {exc}).")
            return None
        self.dumps.append(path)
        self._emit(f"נשמר HTML גולמי: {path}")
        return path

    def _assert_details_payload(self, what: str, html: str) -> None:
        """
        מוודא שמה שחזר הוא **דף פרטים**, לפני שהוא נשמר או מפוענח.

        ``_request`` בודק host וסטטוס בלבד, ו-``_assert_page_year`` שותק
        כשאין בדף שנה — ולכן דף ההשהיה עובר את שניהם. הוא נראה אז זהה
        לחלוטין לקורס שבאמת אינו מפרסם פרטים, וזה ההבדל שכל הפרק הזה נועד
        לשמור עליו: "לא ידוע" חייב להיות שונה מ"אין".

        הבדיקה רצה **לפני** ``dump_html`` בכוונה — גוף השהיה שנשמר לתיקיית
        ה-raw מזהם אותה: ``reparse.py`` יפענח אותו כדף ריק, והבדיקות
        שקוראות משם דפים אמיתיים יקבלו מאה בתים של הודעת שגיאה.

        Raises:
            ThrottledError: דף השהיה — להמתין ולנסות שוב, לא לשמור.
            YedionHTTPError: מה שחזר אינו דף פרטי קורס בכלל.
        """
        text = str(html or "")
        plain = _html.unescape(text)

        for marker in _THROTTLE_MARKERS:
            if marker in plain:
                raise ThrottledError(
                    f"{what}: הידיעון החזיר דף השהיית גישה ולא את דף הפרטים — "
                    "חרגנו מקצב השאילתות. הדף לא נשמר ולא פוענח, כי רשומה "
                    'ריקה שנשמרת עכשיו תיראה כמו קורס בלי נ"ז ובלי תנאי קדם '
                    "ותישאר כזאת שבוע שלם. כדאי להמתין ולהגדיל את delay_s. "
                    "(throttled by the yedion; response withheld)"
                )

        if len(text.strip()) < _DETAILS_MIN_CHARS or not any(
            marker in plain for marker in _DETAILS_PAGE_MARKERS
        ):
            raise YedionHTTPError(
                f"{what}: מה שחזר אינו דף פרטי קורס ({len(text):,} תווים, בלי "
                "הסימנים הקבועים של הדף). דף חלקי של קורס שאינו נפתח הוא "
                "תשובה תקינה — זה לא דף חלקי, זה בכלל לא הדף. "
                "(not a course-details page)"
            )

    # ------------------------------------------------------- אימות שנה
    def _page_year(self, html: str) -> str:
        """
        השנה שהדף מצהיר עליה, כמחרוזת ("" אם לא נמצאה).

        המקור הראשי הוא ``parser.extract_page_year`` — הוא עובד על ה-DOM
        ולכן עומד גם בכותרת שמפוצלת בין תגיות. אם הפרסר לא זמין (או לא מצא),
        נופלים לרגקסים המקומיים ולבסוף לערך שמסומן בבורר השנה.
        """
        if not html:
            return ""
        extractor = _load_extract_page_year()
        if extractor is not None:
            try:
                found = _coerce_year_value(extractor(html))
            except Exception as exc:  # noqa: BLE001 - הפרסר לא יפיל שליפה
                self._emit(
                    f"אזהרה: extract_page_year נכשל ({type(exc).__name__}: {exc}); "
                    "ממשיכים עם זיהוי מקומי."
                )
                found = ""
            if found:
                return found
        return (
            _course_year_label(html)
            or _header_year_label(html)
            or _selected_year_value(html)
        )

    def _assert_page_year(self, what: str, html: str) -> None:
        """
        מוודא שדף שנשלף באמת שייך לשנה שביקשנו.

        הסימן הראשי הוא הרגקס המקומי על ``שנה"ל תשפ"X`` — בדיוק הכותרת של דף
        קורס. ``parser.extract_page_year`` רחב יותר (הוא מסתפק גם בכותרת של
        דף החיפוש), ולכן הוא נקרא רק כגיבוי, ורק כשהתווית ``שנה"ל`` כן קיימת
        בדף אבל הרגקס לא הצליח לקרוא ממנה שנה.

        שנה שלא זוהתה כלל **אינה** שגיאה: קורס שלא נפתח מחזיר דף תקין
        (GROUND_TRUTH §6). רק אי-התאמה מפורשת זורקת.

        Raises:
            YearMismatchError: אם הדף מצהיר על שנה אחרת מזו שביקשנו.
        """
        if not self.year or not html:
            return

        found = _course_year_label(html)
        if not found and _COURSE_YEAR_LABEL_RE.search(_html.unescape(str(html))):
            found = self._page_year(html)

        verdict = _year_matches(found, self.year)
        if verdict is False:
            want = hebrew_year_label(self.year)
            raise YearMismatchError(
                f"{what}: הדף שנשלף מצהיר על שנת לימודים {found}, אבל ביקשנו "
                f"{want} ({self.year}). לא מפרסרים דף של שנה אחרת — זו בדיוק "
                "התקלה שהבדיקה הזאת נועדה למנוע (ראו GROUND_TRUTH §9: בלי "
                "בקשת החימום השנה חוזרת בשקט לשנה הקודמת). "
                f"(Year mismatch: page says {found!r}, expected {self.year!r}.)"
            )
        if verdict is True:
            self._emit(f"{what}: אומת — הדף הוא של שנת {found}.")
        else:
            self._emit(f"{what}: לא זוהתה שנה בדף (ממשיכים; no year on the page).")

    # =====================================================================
    #  הפרוטוקול של GROUND_TRUTH §9 — שלושה שלבים, בסדר הזה בלבד
    # =====================================================================
    def open_session(self) -> None:
        """
        פותח סשן: **חימום -> החלפת שנה -> אימות**. בדיוק בסדר הזה.

        למה הסדר קדוש (GROUND_TRUTH §9): ה-POST של החלפת השנה "תופס" רק אם
        כבר קיים סשן. בלי בקשת החימום ה-POST מחזיר 200 והכותרת שלו אפילו
        מציגה את השנה הנכונה — אבל כל GET שאחריו חוזר עם השנה **הקודמת**,
        בלי שום שגיאה. כך 11069 חזר עם 4 קבוצות (תשפ"ו) במקום 2 (תשפ"ז).

        לכן:
          * ``_step_2_change_year`` מסרב לרוץ אם ``_warmed_up`` לא הורם,
          * ``_step_3_verify_year`` מסרב לרוץ אם ה-POST לא נשלח,
          * והאימות נעשה על **GET נפרד**, לא על תשובת ה-POST — כי ההבדל בין
            "עבד" ל"נראה שעבד" מתגלה רק בבקשה הבאה.

        Raises:
            YearSwitchError: אם לא הצלחנו לוודא שהשנה המבוקשת אכן נתפסה.
            GatedEndpointError / YedionHTTPError: תקלות רשת.
        """
        if self.session_ready:
            self._emit("הסשן כבר פתוח — מדלגים על פתיחה נוספת.")
            return

        # אין להחליף את סדר שלוש השורות האלה. ראו הסבר למעלה.
        self._step_1_warm_up()
        self._step_2_change_year()
        self._step_3_verify_year()

        self.session_ready = True

    def _step_1_warm_up(self) -> str:
        """
        שלב 0 בפרוטוקול: GET אחד ל-``S_LOOK_FOR_NOSE``, רק כדי שייווצר סשן.

        זה מה שמייצר את העוגיות (``Yedion.MySession``, ``TS0188c6f2``)
        שבלעדיהן החלפת השנה לא נדבקת. **בקשה זו אינה אופציונלית.**
        """
        self._emit(
            f"שלב 1/3 — בקשת חימום ({self.warmup_code}) כדי לפתוח סשן. "
            "בלעדיה החלפת השנה לא נתפסת (GROUND_TRUTH §9)."
        )
        html = self._request(
            "GET", course_url(self.warmup_code), what=f"חימום {self.warmup_code}"
        )
        # שם קבוע (ולא מספר רץ) כדי שכל ריצה תדרוס את הקודמת ולא תצבור קבצים.
        self.dump_html("session_warmup", html)
        self._warmed_up = True

        before = self._page_year(html)
        if before:
            self._emit(f"שלב 1/3 — הסשן נפתח. השנה כרגע: {before}.")
        else:
            self._emit("שלב 1/3 — הסשן נפתח.")
        return html

    def _step_2_change_year(self) -> str:
        """
        שלב 1 בפרוטוקול: POST של ``Enter_Search`` עם ``ChangeYear``.

        ``Enter_Search`` הוא המסך היחיד שחסום לאנונימיים ב-GET, אבל ה-POST
        הזה עובד בלי הזדהות — כל עוד קדמה לו בקשת החימום.
        """
        if not self._warmed_up:
            # שגיאת תכנות, לא שגיאת רשת: מישהו הפך את הסדר.
            raise YedionHTTPError(
                "סדר שגוי: אסור לשלוח את POST החלפת השנה לפני בקשת החימום. "
                "בלי החימום ה-POST מחזיר 200 אבל כל GET שאחריו יחזור בשקט עם "
                "השנה הקודמת (GROUND_TRUTH §9). "
                "(the warm-up GET must precede the ChangeYear POST)"
            )

        if not self.year:
            self._emit(
                "שלב 2/3 — לא הוגדרה שנה, לא נוגעים בשנת הסשן. "
                "האתר יחזיר את ברירת המחדל שלו (כרגע תשפ\"ו) — כמעט אף פעם "
                "לא מה שרוצים."
            )
            return ""

        want = hebrew_year_label(self.year)
        self._emit(f"שלב 2/3 — מחליף את שנת הלימודים ל-{want} ({self.year}).")

        body = urlencode(
            {
                "PRGNAME": PRGNAME_ENTER_SEARCH,
                "ARGUMENTS": ARGS_CHANGE_YEAR,
                YEAR_FIELD: str(self.year),
            }
        ).encode("utf-8")

        html = self._request(
            "POST",
            BASE_URL,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": f"https://{YEDION_HOST}",
                "Referer": course_url(self.warmup_code),
            },
            what="החלפת שנה",
        )
        self.dump_html("session_changeyear", html)
        self._year_posted = True
        return html

    def _step_3_verify_year(self) -> None:
        """
        שלב 2 בפרוטוקול: **אימות** — GET נוסף, ובדיקה שהשנה שחזרה היא זו
        שביקשנו.

        האימות חייב להיות על GET חדש ולא על תשובת ה-POST: התקלה של §9 היא
        בדיוק "ה-POST נראה מצוין וה-GET הבא חוזר עם שנה אחרת".

        Raises:
            YearSwitchError: אם השנה לא תואמת, או שלא הצלחנו לקרוא שנה בכלל.
        """
        if not self.year:
            self.year_label = ""
            self._emit("שלב 3/3 — אין שנה לאמת (לא בוצעה החלפה).")
            return

        if not (self._warmed_up and self._year_posted):
            raise YedionHTTPError(
                "סדר שגוי: אימות השנה חייב לבוא אחרי החימום ואחרי ה-POST. "
                "(verification must follow the warm-up and the ChangeYear POST)"
            )

        want = hebrew_year_label(self.year)
        self._emit(f"שלב 3/3 — מאמת שהשנה שחזרה היא {want} ({self.year}).")

        html = self._request(
            "GET",
            course_url(self.warmup_code),
            what=f"אימות שנה ({self.warmup_code})",
        )
        self.dump_html("session_verify", html)

        found = self._page_year(html)
        verdict = _year_matches(found, self.year)

        if not found:
            # דף החימום הוא קוד לא-קיים (WARMUP_CODE), ולכן אין בו כותרת קורס
            # ואין בו מחרוזת שנה שאפשר לאמת מולה — זה מצב תקין ולא כישלון.
            # האימות פשוט נדחה: _assert_page_year רץ על *כל* דף קורס אמיתי,
            # כולל הראשון, ויעצור שם אם השנה שגויה. כלומר התכונה הבטיחותית
            # נשמרת במלואה — שום דף לא מפורסר עם שנה שגויה — רק מקום הבדיקה זז.
            self.year_label = ""
            self._year_verified = False
            self._emit(
                f"שלב 3/3 — דף החימום ({self.warmup_code}) אינו קורס אמיתי ולכן "
                "אין בו שנה לאמת. האימות נדחה לדף הקורס הראשון, שבו הוא נאכף "
                "בכל מקרה. (deferred to the first real course page)"
            )
            return

        if verdict is not True:
            got = found or "לא נמצאה שנה בדף"
            raise YearSwitchError(
                f"החלפת שנת הלימודים לא אושרה: ביקשנו {want} ({self.year}) "
                f"והדף שחזר מצהיר על {got}. "
                "כך נראית בדיוק התקלה של GROUND_TRUTH §9 — בקשת חימום שלא "
                "התבצעה או שנכשלה, ואז כל דף חוזר עם השנה הקודמת בלי שום "
                "שגיאה. לא נשלף אף קורס: מערכת של שנה שגויה גרועה בהרבה "
                "ממערכת שלא התעדכנה. "
                f"(year switch not confirmed: wanted {self.year!r}, page says {found!r})"
            )

        self.year_label = found
        self._year_verified = True
        self._emit(f"שלב 3/3 — אושר: הסשן עומד על {found}.")

    def _warn_if_no_session(self, what: str) -> None:
        """
        אזהרה (לא חריגה) כשמושכים דף בלי לפתוח סשן.

        אנחנו לא פותחים סשן מאחורי הגב של מי שקרא: שליפה בודדת היא שימוש
        לגיטימי (וכך גם הבדיקות עובדות). השמירה האמיתית מפני שנה שגויה היא
        ``_assert_page_year``, שרצה על כל דף בכל מקרה.
        """
        if self.session_ready or not self.year:
            return
        self._emit(
            f"אזהרה: {what} נשלף בלי שנפתח סשן (open_session). השנה שתתקבל "
            "היא ברירת המחדל של האתר; אימות השנה על הדף עצמו עדיין פעיל."
        )

    # ------------------------------------------------------------ שליפות
    def fetch_course(self, code: str) -> str:
        """
        מביא את דף התוצאות של קוד קורס אחד ומחזיר את ה-HTML הגולמי.

        הסדר קבוע: שליפה -> **שמירה גולמית** -> אימות שנה -> החזרה. השמירה
        קודמת לכל פירסור, בדיוק כמו במסלול הדפדפן; זה מה שמאפשר ל-
        ``reparse.py`` לפענח מחדש בלי לגעת ברשת.

        Returns:
            ה-HTML של הדף. דף בלי אף קבוצה הוא תשובה **תקינה** — כך נראה
            קורס שלא נפתח בשנה הזאת (GROUND_TRUTH §6).

        Raises:
            YearMismatchError: אם הדף מצהיר על שנת לימודים אחרת.
            GatedEndpointError / YedionHTTPError: תקלות רשת.
        """
        clean = str(code).strip()
        if not clean:
            raise YedionHTTPError("קוד קורס ריק. (empty course code)")
        if not clean.isdigit():
            self._emit(f"אזהרה: הקוד {clean!r} אינו מספרי — הידיעון מצפה לקוד מספרי.")

        self._warn_if_no_session(f"קורס {clean}")
        self._emit(f"קורס {clean}: מביא מהידיעון…")

        html = self._request("GET", course_url(clean), what=f"קורס {clean}")

        # חוק ברזל: קודם לדיסק, אחר כך פירסור (כולל אימות השנה, שמפרסר גם הוא).
        self.dump_html(clean, html)
        self._assert_page_year(f"קורס {clean}", html)

        blocks = count_group_blocks(html)
        if blocks:
            # "בלוקים" ולא "קבוצות" בכוונה — ראו count_group_blocks.
            self._emit(
                f"קורס {clean}: התקבלו {len(html):,} תווים, ~{blocks} בלוקי קבוצה "
                "(הספירה הסופית נעשית בפירסור)."
            )
        else:
            self._emit(
                f"קורס {clean}: הדף התקבל אבל אין בו אף קבוצה — כנראה הקורס "
                "אינו נפתח בשנה/סמסטר האלה. (no groups; may not be offered)"
            )
        return html

    def fetch_details(
        self,
        code: str,
        group_id: str = "0",
        kind_code: str = "1",
        *,
        semester_code: str = "1",
    ) -> str:
        """
        מביא את דף **פרטי הקורס** (``S_CourseDetails``) ומחזיר HTML גולמי.

        אותו סדר ברזל כמו ``fetch_course``: שליפה -> **שמירה גולמית** ->
        אימות שנה -> החזרה. השמירה קודמת לכל פירסור, כדי שאפשר יהיה לתקן
        את הפרסר בלי לגרד שוב את השרת של המכללה.

        נימוס: הדף הזה נשלף **הרבה פחות** מדף המערכת. נקודות זכות ותנאי קדם
        כמעט לא משתנים במהלך השנה, ולכן חלון הרעננות שלהם הוא שבוע ולא יממה
        (SPEC_MULTIFACULTY §2). הרענון היומי לא אמור להכפיל את מספר הבקשות
        שלו עבור נתונים שכמעט אינם זזים — ההשהיה ``delay_s`` חלה כאן בדיוק
        כמו בכל בקשה אחרת.

        Args:
            code: קוד הקורס.
            group_id: מזהה קבוצה; ``"0"`` = הקורס כולו (ברירת המחדל).
            kind_code: קוד סוג המקצוע (1 = הרצאה).
            semester_code: קוד הסמסטר בידיעון. פרטי הקורס אינם תלויים בו,
                והוא קיים רק כדי שאפשר יהיה לשחזר קישור מדויק מדף התוצאות.

        Returns:
            ה-HTML של דף הפרטים. דף חלקי — למשל של קורס שאינו נפתח, שבו
            "נקודות זכות :" ריק — הוא תשובה **תקינה**; ``parse_course_details``
            יחזיר ``credits=None`` ואזהרה, ולא יזרוק.

        Raises:
            ThrottledError: הידיעון החזיר דף "השהיית גישה זמנית" — חרגנו
                מקצב השאילתות. הדף **לא** נשמר ולא הוחזר, כדי שרשומה ריקה
                לא תיכנס למטמון לשבוע במקום פרטי הקורס.
            YearMismatchError: אם הדף מצהיר על שנת לימודים אחרת.
            GatedEndpointError / YedionHTTPError: תקלות רשת, או תשובה
                שאינה דף פרטי קורס בכלל.
        """
        clean = str(code).strip()
        if not clean:
            raise YedionHTTPError("קוד קורס ריק. (empty course code)")
        if not clean.isdigit():
            self._emit(f"אזהרה: הקוד {clean!r} אינו מספרי — הידיעון מצפה לקוד מספרי.")

        self._warn_if_no_session(f"פרטי קורס {clean}")
        self._emit(f"פרטי קורס {clean}: מביא מהידיעון…")

        url = details_url(
            clean,
            semester_code=semester_code,
            kind_code=kind_code,
            group_id=group_id,
        )
        html = self._request("GET", url, what=f"פרטי קורס {clean}")

        # לפני חוק הברזל: לוודא שזה בכלל דף. גוף השהיה אינו "דף חלקי" —
        # הוא לא תשובה, ואסור שיישמר לדיסק או ייכנס למטמון כרשומה ריקה.
        self._assert_details_payload(f"פרטי קורס {clean}", html)

        # חוק ברזל: קודם לדיסק, אחר כך פירסור (גם אימות השנה מפרסר).
        # שם הקובץ מתחיל ב-"details_" ולא בקוד, כדי ש-reparse.py — שסורק
        # "<code>_*.html" — לא יבלבל דף פרטים עם דף מערכת שעות.
        self.dump_html(f"details_{clean}", html)
        self._assert_page_year(f"פרטי קורס {clean}", html)

        self._emit(f"פרטי קורס {clean}: התקבלו {len(html):,} תווים.")
        return html

    def fetch_catalog(self) -> str:
        """
        מביא את **כל** קטלוג הקורסים של השנה שבסשן — בבקשה אחת.

        לא לולאה על אותיות: השרת מתעלם מהאות ומחזיר את הקטלוג המלא בכל מקרה
        (ראו ``CATALOG_ARGUMENTS``). מעבר על הא"ב היה פי 22 עומס על השרת של
        המכללה עבור אותם נתונים בדיוק.
        """
        self._warn_if_no_session("הקטלוג")
        self._emit("קטלוג: מביא את כל הקורסים בבקשה אחת…")

        html = self._request("GET", CATALOG_URL, what="קטלוג")

        self.dump_html("catalog", html)
        self._assert_page_year("קטלוג", html)

        rows = count_catalog_rows(html)
        self._emit(f"קטלוג: התקבלו {len(html):,} תווים, ~{rows} שורות קורס.")
        return html

    def scrape(self, codes: Iterable[str]) -> dict[str, str]:
        """
        מביא את הדפים של כל הקודים — סדרתי, מנומס, וממשיך אחרי כישלון.

        לפני הקורס הראשון נפתח הסשן (חימום, שנה, אימות). אם האימות נכשל
        **לא נשלף אף קורס**: מוטב לחזור בלי נתונים מאשר עם שנה שגויה.
        קורס שנכשל נרשם ב-``errors`` כזוג ``(code, message)`` והריצה נמשכת.

        Returns:
            ``{קוד: HTML}``. קודים שנכשלו פשוט לא יופיעו במילון.
        """
        wanted: list[str] = []
        for code in codes or []:
            clean = str(code).strip()
            if clean and clean not in wanted:
                wanted.append(clean)

        if not wanted:
            self._emit("אין קודים לשליפה.")
            return {}

        if not self.session_ready:
            try:
                self.open_session()
            except YedionHTTPError as exc:
                self._emit(f"עצירה: {exc}")
                for code in wanted:
                    self.errors.append((code, f"{type(exc).__name__}: {exc}"))
                return {}

        results: dict[str, str] = {}
        total = len(wanted)
        self._emit(f"מרענן {total} קורסים…")

        for i, code in enumerate(wanted, start=1):
            self._emit(f"({i}/{total}) קורס {code}")
            try:
                results[code] = self.fetch_course(code)
            except ThrottledError as exc:
                # השרת אמר במפורש "האטו". להמשיך ולנסות את כל השאר זה גם חסר
                # תועלת (כולם יחזרו כדף השהיה) וגם לא מנומס. עוצרים כאן,
                # ומסמנים את מה שנשאר כ"לא נוסה" ולא כ"נכשל".
                self.throttled = True
                remaining = wanted[i - 1 :]
                self._emit(
                    f"עצירה: הידיעון הגביל את קצב הבקשות. {len(remaining)} קורסים "
                    f"לא נוסו בכלל. {exc}"
                )
                self.skipped.extend(remaining)
                break
            except YedionHTTPError as exc:
                self.errors.append((code, str(exc)))
                self._emit(f"שגיאה בקורס {code}: {exc}")
            except Exception as exc:  # noqa: BLE001 - קורס אחד לא מפיל את הכול
                self.errors.append((code, f"{type(exc).__name__}: {exc}"))
                self._emit(f"שגיאה לא צפויה בקורס {code}: {exc}")

        self._emit(
            f"סיום: {len(results)}/{total} קורסים נשלפו, {len(self.errors)} תקלות."
        )
        return results


# ==========================================================================
# 5. בדיקת עשן מהשורה — היחיד במודול שמותר לו להדפיס
# ==========================================================================
#   python src/yedion_http.py                    (11069, תשפ"ז)
#   python src/yedion_http.py 61753 61756
#   python src/yedion_http.py --year 2026 11069  (אמור להראות 4 קבוצות)
#   python src/yedion_http.py --catalog
#   python src/yedion_http.py --quiet 61753
# --------------------------------------------------------------------------
def enable_utf8_stdout() -> None:
    """מאפשר הדפסת עברית בקונסולה של Windows. עטוף — לא כל זרם ניתן לקנפוג."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass


def _parse_args(argv: list[str]) -> dict:
    """מפרק ארגומנטים: קודים + ``--year`` + ``--semester`` + ``--catalog`` + ``--quiet``."""
    codes: list[str] = []
    year: str | None = DEFAULT_YEAR
    semester = "א"
    catalog = False
    quiet = False

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--year", "-y") and i + 1 < len(argv):
            year = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--year="):
            year = arg.split("=", 1)[1]
            i += 1
            continue
        if arg in ("--semester", "-s") and i + 1 < len(argv):
            semester = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--semester="):
            semester = arg.split("=", 1)[1]
            i += 1
            continue
        if arg == "--catalog":
            catalog = True
        elif arg in ("--quiet", "-q"):
            quiet = True
        else:
            codes.append(arg)
        i += 1

    if year is not None and year.strip().lower() in ("", "none", "off", "-"):
        year = None
    if semester.strip().lower() in ("", "none", "off", "-", "all"):
        semester = ""
    return {
        "codes": codes or [WARMUP_CODE],
        "year": year,
        "semester": semester,
        "catalog": catalog,
        "quiet": quiet,
    }


def _parsed_group_count(html: str, code: str, semester: str) -> int | None:
    """
    כמה קבוצות באמת יש בדף, לפי הפרסר — או ``None`` אם הפרסר לא זמין.

    זה המספר שסופר: 11069 בתשפ"ז = **2** קבוצות, בעוד שספירת הבלוקים הגסה
    בדף מראה 4 (הידיעון מציג את שני הסמסטרים באותו עמוד). המספר הזה הוא גם
    מה שמאפשר לבדיקת העשן לשחזר את הכשל של GROUND_TRUTH §9: תשפ"ז -> 2,
    תשפ"ו -> 4.
    """
    for module_name in ("parser", "src.parser"):
        try:
            module = importlib.import_module(module_name)
        except Exception:  # noqa: BLE001 - בדיקת עשן לא נופלת בגלל ייבוא
            continue
        parse = getattr(module, "parse_course_page", None)
        if not callable(parse):
            continue
        try:
            result = parse(html, code, semester=semester or None)
        except Exception:  # noqa: BLE001
            return None
        course = getattr(result, "course", None)
        return len(getattr(course, "groups", []) or []) if course else 0
    return None


def main(argv: list[str] | None = None) -> int:
    """
    בדיקת עשן: פותח סשן בלי התחברות, מביא קורס אחד ומדפיס כמה קבוצות בו.

    זו הפונקציה **היחידה** בקובץ שמדפיסה. המחלקה עצמה שקטה לחלוטין אלא אם
    העבירו לה ``log``, וכאן אנחנו מעבירים לה את ההדפסה של הכלי.

    Exit codes:
        0 — הצליח.  1 — נכשל.  2 — נקודות הקצה נחסמו (צריך את מסלול הדפדפן).
    """
    enable_utf8_stdout()
    args = list(argv if argv is not None else sys.argv[1:])

    if any(a in ("-h", "--help") for a in args):
        print("שליפה מהידיעון בלי התחברות (login-free yedion fetcher)")
        print()
        print("שימוש: python src/yedion_http.py [--year YYYY] [--semester א] "
              "[--catalog] [--quiet] [קוד ...]")
        print(f"  --year YYYY   שנה לועזית. ברירת מחדל {DEFAULT_YEAR} "
              f"(= {hebrew_year_label(DEFAULT_YEAR)}).")
        print("  --year none   בלי להחליף שנה (האתר יחזיר את ברירת המחדל שלו).")
        print("  --semester X  סמסטר לספירת הקבוצות. ברירת מחדל א. 'all' = בלי סינון.")
        print("  --catalog     להביא גם את כל הקטלוג (בקשה אחת).")
        print("  --quiet       בלי שורות התקדמות, רק הסיכום.")
        print(f"  ברירת מחדל לקוד: {WARMUP_CODE}")
        return 0

    opts = _parse_args(args)
    codes: list[str] = opts["codes"]
    year: str | None = opts["year"]
    semester: str = opts["semester"]

    year_note = f"{year} ({hebrew_year_label(year)})" if year else "ברירת המחדל של האתר (!)"
    print("בדיקת עשן — שליפה מהידיעון בלי התחברות")
    print(f"קורסים: {', '.join(codes)} | שנה: {year_note} | סמסטר: {semester or 'הכול'}")
    print()

    client = YedionHTTP(
        year=year,
        log=None if opts["quiet"] else (lambda line: print(f"[yedion] {line}", flush=True)),
    )

    try:
        client.open_session()
    except GatedEndpointError as exc:
        print(f"נחסם: {exc}")
        return 2
    except YedionHTTPError as exc:
        print(f"פתיחת הסשן נכשלה: {exc}")
        return 1

    pages = client.scrape(codes)

    catalog_html = ""
    if opts["catalog"]:
        try:
            catalog_html = client.fetch_catalog()
        except YedionHTTPError as exc:
            print(f"הקטלוג נכשל: {exc}")

    print()
    print("=== סיכום (summary) ===")
    if client.year_label:
        print(f"שנת הלימודים שאושרה: {client.year_label}")
    for code in codes:
        html = pages.get(code)
        if html is None:
            print(f"  {code}: נכשל (failed)")
            continue
        groups = _parsed_group_count(html, code, semester)
        where = f"סמסטר {semester}" if semester else "כל הסמסטרים"
        if groups is None:
            print(f"  {code}: ~{count_group_blocks(html)} בלוקי קבוצה בדף "
                  f"(הפרסר לא זמין), {len(html):,} תווים")
        else:
            print(f"  {code}: {groups} קבוצות ב{where}, "
                  f"~{count_group_blocks(html)} בלוקים בדף, {len(html):,} תווים")
    if catalog_html:
        print(f"  קטלוג: ~{count_catalog_rows(catalog_html)} שורות קורס, "
              f"{len(catalog_html):,} תווים")
    if client.errors:
        print("תקלות (errors):")
        for code, message in client.errors:
            print(f"  {code}: {message}")
    if client.raw_dir is not None:
        print(f"קבצי HTML גולמיים: {client.raw_dir}")
    print(f"בקשות שבוצעו: {len(client.request_log)}")

    return 0 if pages else 1


if __name__ == "__main__":
    raise SystemExit(main())
