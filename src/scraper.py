"""
גירוד הידיעון של בראודה — Braude yedion scraper (Playwright, התחברות ידנית).

מה המודול הזה עושה
-------------------
פותח חלון דפדפן *אמיתי* וגלוי, מחכה שהמשתמש/ת יתחבר/תתחבר בעצמו/ה, ואז שולף
את דף התוצאות של כל קוד קורס מתוך הידיעון ומחזיר את ה-HTML הגולמי.

הפרוטוקול (מאומת מקצה לקצה — docs/GROUND_TRUTH.md סעיפים 1 ו-8)
-----------------------------------------------------------
1. **החיפוש הוא GET פשוט.** אין צורך למלא טופס ואין צורך ללחוץ על כלום::

       https://info.braude.ac.il/yedion/fireflyweb.aspx?prgname=S_LOOK_FOR_NOSE&arguments=-N61753

   זה המסלול הראשי. מילוי הטופס נשאר כאן רק כגיבוי, ובדרגה נמוכה יותר.

2. **שנת הלימודים היא מצב-סשן (session state), לא פרמטר ב-URL.** הידיעון של
   בראודה נפתח כברירת מחדל על תשפ"ו, בעוד שהמערכת שאנחנו בונים היא לתשפ"ז
   (2027). לכן *חייבים* להחליף שנה פעם אחת בתחילת הריצה, ואז כל GET שאחריו
   יורש את השנה מהעוגייה. בלי ההחלפה הזאת הכלי היה מחזיר בשקט את המערכת של
   השנה שעברה — וזו התקלה הגרועה ביותר שאפשר להעלות על הדעת כאן.
   לכן: אחרי ההחלפה *מוודאים* שהכותרת בדף באמת השתנתה, ואם לא — נזרקת
   ``YearSwitchError``. וכן: כל דף קורס נבדק שוב מול השנה המבוקשת
   (``YearMismatchError``). עדיף להיכשל ברעש מאשר להצליח בשקט עם נתון שגוי.

כללי ברזל (אין לעקוף אותם)
--------------------------
1. **אפס סיסמאות.** המודול הזה לא מבקש, לא קורא, לא שומר, לא מדפיס ולא שולח
   שם משתמש או סיסמה. פרטי ההתחברות מוקלדים בחלון הדפדפן האמיתי. הסקריפט רק
   מסתכל על ה-URL ומחכה. אין כאן שום קוד שנוגע בשדות התחברות.
2. **הקשר קבוע (persistent context).** הפרופיל של הדפדפן נשמר בתיקייה, כך
   שהעוגיות של Citrix שורדות בין הרצות וההתחברות נעשית פעם אחת בלבד.
3. **קודם שומרים, אחר כך מפרשים.** כל דף שנטען נשמר כקובץ HTML גולמי תחת
   data/raw/ *לפני* שמישהו מנסה לפרסר אותו — אבל **אך ורק** אם הוא הגיע
   מ-info.braude.ac.il. דף של שער ההתחברות לעולם לא נכתב לדיסק.
4. **בעדינות.** בקשות סדרתיות בלבד, השהיה של 1.5 שניות בין קורס לקורס.

למה הקוד כאן "חשדן" כל כך
-------------------------
הידיעון הוא עמוד ASP.NET WebForms ישן (fireflyweb.aspx). מזהי הפקדים בו
נוצרים אוטומטית ומשתנים בין גרסאות, ולכן אסור להסתמך על סלקטור יחיד.
לכל פעולה יש כאן *שרשרת אסטרטגיות*, והקוד מדפיס איזו אסטרטגיה הצליחה —
כך שכשה-HTML ישתנה, יהיה ברור מיד מה נשבר.

Technical note: this module only ever *reads* the page. The only things it
types are course codes; the only things it clicks are search / year-switch
buttons.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import importlib
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

# --------------------------------------------------------------------------
# קבועים — כתובות ומחרוזות עברית שמופיעות בדף
# --------------------------------------------------------------------------

#: הסימנים של דף ההשהיה של הידיעון, והרצפה שמתחתיה שום דף אינו דף.
#: זהים ל-yedion_http — שני המסלולים כותבים לאותה תיקייה, ולכן שניהם
#: חייבים לסרב לאותם גופים. ‏158 תווים של "יותר מידי שאילתות" שנשמרו
#: מעל דמפ תקין מוחקים אותו בשקט.
BLOCKED_MARKERS: tuple[str, ...] = (
    "השהיית גישה זמנית",
    "יותר מידי שאילתות",
    "יותר מדי שאילתות",
)
MIN_REAL_PAGE_CHARS = 500


def looks_like_a_page(html: str) -> tuple[bool, str]:
    """האם מה שחזר הוא בכלל דף. מחזיר (כן/לא, הסיבה אם לא)."""
    text = str(html or "")
    for marker in BLOCKED_MARKERS:
        if marker in text:
            return False, f"דף השהיה ({marker!r})"
    if len(text.strip()) < MIN_REAL_PAGE_CHARS:
        return False, f"{len(text.strip()):,} תווים בלבד"
    return True, ""


#: שורש הפרויקט — משמש כדי לפתור נתיבים יחסיים כמו "data/raw" בלי תלות ב-cwd.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: שער ההתחברות (Citrix NetScaler AAA) — הכתובת מה-SPEC.
LOGIN_URL = "https://login.braude.ac.il/logon/LogonPoint/tmindex.html"

#: כתובת חלופית שנצפתה בפועל בהפניה (302) של משתמש אנונימי.
#: אם LOGIN_URL לא נטענת, מנסים את זו, ואם גם היא נכשלת — פשוט ניגשים
#: ל-SEARCH_URL ונותנים לשרת להפנות אותנו לשער הנכון בעצמו.
LOGIN_URL_ALT = "https://loginedu.braude.ac.il/logon/LogonPoint/tmindex.html"

#: נקודת הקצה היחידה של הידיעון. *כל* המסכים הם אותו aspx עם prgname אחר.
BASE_URL = "https://info.braude.ac.il/yedion/fireflyweb.aspx"

#: דף החיפוש בידיעון. משתמש אנונימי מקבל ממנו 302 לשער ההתחברות.
SEARCH_URL = BASE_URL + "?prgname=Enter_Search"

#: ההוכחה שההתחברות הצליחה: הדפדפן חזר לנחות על הדומיין הזה.
SUCCESS_HOST = "info.braude.ac.il"

#: ה-prgname של חיפוש קורס לפי קוד (GROUND_TRUTH סעיף 1, טבלת ה-API).
PRGNAME_COURSE_SEARCH = "S_LOOK_FOR_NOSE"

#: ה-prgname וה-arguments של החלפת שנת לימודים (GROUND_TRUTH סעיף 8).
PRGNAME_ENTER_SEARCH = "Enter_Search"
ARGS_CHANGE_YEAR = "-A,,-A,ChangeYear"

#: שם/מזהה בורר השנה בדף החיפוש (אומת פעמיים — ראה GROUND_TRUTH סעיף 1).
YEAR_SELECT_ID = "ChangeYear"


def course_url(code: str) -> str:
    """
    בונה את כתובת ה-GET הישירה לדף התוצאות של קוד קורס.

    זהו המסלול המאומת (GROUND_TRUTH סעיף 1): אותה נקודת קצה שהטופס שולח
    אליה POST עונה יפה גם ל-GET, ולכן אין שום צורך למלא טופס או ללחוץ.
    קידומת ``-N`` = ארגומנט מספרי; קודי קורס תמיד מספריים.

    >>> course_url("61753")
    'https://info.braude.ac.il/yedion/fireflyweb.aspx?prgname=S_LOOK_FOR_NOSE&arguments=-N61753'
    """
    # Defensive: the code goes straight into a URL, so strip whitespace and
    # percent-encode anything that is not a bare alphanumeric.
    clean = str(code).strip()
    return (
        f"{BASE_URL}?prgname={PRGNAME_COURSE_SEARCH}"
        f"&arguments=-N{quote(clean, safe='')}"
    )


#: חלקי URL שמסגירים שאנחנו עדיין בשער ההתחברות ולא בידיעון.
#: הקבוצה הראשונה היא שער ה-Citrix עצמו; השנייה היא שלבי אימות נוספים
#: (nFactor, SAML, Microsoft) שה-URL שלהם לא מכיל "logon" בכלל — בלעדיהם
#: הבדיקה השקטה הייתה יכולה לרוץ בדיוק באמצע הזדהות.
#: הרשימה משמשת רק כדי *להימנע* מבדיקה; זיהוי ההצלחה עצמו נעשה לפי המארח.
LOGIN_URL_MARKERS = (
    "logon",
    "tmindex",
    "logonpoint",
    "/vpn/",
    "nsbrand",
    "/nf/auth",
    "doauthentication",
    "/cgi/",
    "microsoftonline",
    "saml",
    "adfs",
    "okta",
)

#: טקסטים בעברית שמופיעים בדף החיפוש (ראה צילום המסך של הדף).
LABEL_COURSE_CODE = "קוד קורס"      # "נא להקליד קוד קורס:"
BUTTON_YEAR_CHANGE = "מעבר שנה"     # הכפתור ליד בורר השנה
BUTTON_SEMESTER = "סינון סמסטר"     # הכפתור ליד בורר הסמסטר (לא בשימוש — ראה למטה)

#: **לא משתמשים בסינון הסמסטר של האתר (R1C19).** לכל שורת מפגש יש עמודת
#: "סמסטר" משלה (א' / ב' / קיץ), ולכן מסננים אצלנו אחרי הפירסור — זה גם פשוט
#: יותר וגם ניתן לאימות. GROUND_TRUTH סעיף 8, "Semester filtering".

#: מילים שמסגירות כפתור "חפש" בעברית — לשימוש כשנופלים לחיפוש כפתור בכל הדף.
SEARCH_WORDS_HE = ("חיפוש", "חפש", "הצג", "הצגה", "בצע", "אישור")

#: השהיה מנומסת בין קורס לקורס (שניות). לא לשנות כלפי מטה.
POLITE_DELAY_S = 1.5

#: כל כמה זמן בודקים אם ההתחברות הסתיימה (שניות).
POLL_INTERVAL_S = 2.0

#: זמן המתנה מקסימלי לניווט (מילישניות). שער Citrix איטי, נהיה סבלניים.
NAV_TIMEOUT_MS = 45_000

#: זמן המתנה מקסימלי לפעולה בודדת על אלמנט (מילישניות).
ACTION_TIMEOUT_MS = 15_000

#: כמה לחכות אחרי Enter לפני שנופלים לכפתור (שניות).
#: קצר בכוונה — בגרסה שנצפתה בפועל של הידיעון יש סקריפט שחוסם את Enter
#: בתוך הטופס (preventDefault), ולכן ברוב המקרים Enter פשוט לא יעשה כלום
#: ואין טעם לבזבז עליו זמן. הכפתור הוא המסלול האמיתי.
ENTER_PROBE_S = 3.0

#: כמה לחכות לתגובת השרת אחרי לחיצה על כפתור החיפוש (שניות).
SUBMIT_WAIT_S = 15.0

#: תקציב זמן כולל לכל שלב השליחה, כולל כל הניסיונות והנפילות (שניות).
#: בלי התקרה הזו, קורס אחד שנכשל היה יכול לתקוע את הריצה לדקות ארוכות —
#: יש כאן הרבה ניסיונות גיבוי, וכל אחד מהם מחכה בנפרד.
SUBMIT_BUDGET_S = 45.0

#: כמה לחכות לתגובה אחרי לחיצה על "מעבר שנה" (שניות).
YEAR_SWITCH_WAIT_S = 15.0


# --------------------------------------------------------------------------
# חריגות
# --------------------------------------------------------------------------
class ScraperError(Exception):
    """בסיס לכל תקלות הגורד — נוח לתפוס את כולן במכה אחת."""


class ScraperSelectorError(ScraperError):
    """
    נזרקת כשלא הצלחנו למצוא פקד בדף — למשל את שדה 'קוד קורס'.

    ההודעה תמיד כוללת את הנתיב לקובץ ה-HTML שנשמר, כי זה מה שמאפשר לתקן
    את הסלקטורים אחר כך.
    """


class YearSwitchError(ScraperError):
    """
    נזרקת כשלא הצלחנו להחליף את שנת הלימודים של הסשן, או כשלא הצלחנו
    *לוודא* שההחלפה תפסה.

    זו לא אזהרה ולא "נחמד שיהיה": בלי השנה הנכונה הידיעון יחזיר בשקט את
    המערכת של שנה אחרת. עדיף שהריצה תיעצר ברעש מאשר שתחזור מערכת שגויה.
    """


class YearMismatchError(ScraperError):
    """
    נזרקת כשדף קורס שנשלף מצהיר על שנת לימודים אחרת מזו שביקשנו.

    ההודעה תמיד מציינת את שתי השנים — המבוקשת ומה שנמצא בדף.
    """


# --------------------------------------------------------------------------
# עזרי תשתית
# --------------------------------------------------------------------------
def enable_utf8_stdout() -> None:
    """
    מוודא שאפשר להדפיס עברית לקונסולה של Windows.

    עטוף ב-try/except כי לא כל זרם פלט ניתן לקנפוג מחדש (למשל כשמפנים
    את הפלט לקובץ או כשמריצים מתוך IDE).
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass


def _host_of(url: str) -> str:
    """מחזיר את שם המארח (host) מתוך URL, באותיות קטנות וללא פורט."""
    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    # מורידים פרטי משתמש (user@host) ופורט (host:443) אם יש.
    host = netloc.rsplit("@", 1)[-1]
    if ":" in host:
        head, _, tail = host.rpartition(":")
        if tail.isdigit():          # זה פורט, לא חלק משם המארח
            host = head
    return host.strip("[]")         # סוגריים של כתובת IPv6, ליתר ביטחון


def is_success_url(url: str) -> bool:
    """
    האם ה-URL הזה אומר 'התחברנו בהצלחה'?

    כלומר: האם נחתנו בחזרה על info.braude.ac.il (או תת-דומיין שלו).
    הבדיקה נעשית על רכיבי הדומיין ולא ב-endswith גולמי, כדי ש-
    "notinfo.braude.ac.il" לא ייחשב בטעות כהצלחה.

    **זו גם הבדיקה שמחליטה אם מותר לכתוב את הדף לדיסק.**
    """
    host = _host_of(url)
    return host == SUCCESS_HOST or host.endswith("." + SUCCESS_HOST)


def _looks_like_login_page(url: str) -> bool:
    """האם ה-URL נראה כמו דף של שער ההתחברות (ולא כמו הידיעון)?"""
    low = (url or "").lower()
    return any(marker in low for marker in LOGIN_URL_MARKERS)


def _sha1(text: str) -> str:
    """טביעת אצבע קצרה של תוכן הדף — משמשת לזהות 'הדף השתנה'."""
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


def _banner(lines: list[str], ch: str = "-") -> str:
    """בונה מסגרת טקסט בולטת סביב הודעה — כדי שההודעה לא תפוספס."""
    width = max((len(line) for line in lines), default=0)
    top = "+" + ch * (width + 2) + "+"
    body = "\n".join(f"| {line.ljust(width)} |" for line in lines)
    return f"{top}\n{body}\n{top}"


# --------------------------------------------------------------------------
# שנת לימודים — המרה, נורמליזציה וזיהוי בתוך הדף
# --------------------------------------------------------------------------
#: גימטריה: ערך -> אות. מסודר מהגדול לקטן כדי שהמרה חמדנית תעבוד.
_GEMATRIA: tuple[tuple[int, str], ...] = (
    (400, "ת"), (300, "ש"), (200, "ר"), (100, "ק"),
    (90, "צ"), (80, "פ"), (70, "ע"), (60, "ס"), (50, "נ"),
    (40, "מ"), (30, "ל"), (20, "כ"), (10, "י"),
    (9, "ט"), (8, "ח"), (7, "ז"), (6, "ו"), (5, "ה"),
    (4, "ד"), (3, "ג"), (2, "ב"), (1, "א"),
)

#: אותיות סופיות -> רגילות. הידיעון כותב תש"ף עם פ' סופית, ואנחנו מחשבים
#: תש"פ עם פ' רגילה — בלי המיפוי הזה ההשוואה הייתה נכשלת סתם.
_FINAL_LETTERS = str.maketrans({"ך": "כ", "ם": "מ", "ן": "נ", "ף": "פ", "ץ": "צ"})

#: פער השנים בין הלוח העברי ללועזי, לשנה שמסתיימת באותה שנה לועזית:
#: תשפ"ז = 5787, ו-5787 - 3760 = 2027.
_HEBREW_YEAR_OFFSET = 3760


def hebrew_year_label(gregorian: str | int) -> str:
    """
    ממיר שנה לועזית (סוף שנת הלימודים) לתווית עברית: ``2027`` -> ``'תשפ"ז'``.

    הידיעון מזהה שנים במספרים לועזיים ב-``<option value>``, אבל *מציג* אותן
    בעברית בכותרת ("חיפוש קורסים במערכת תשפ״ז"). כדי לאמת שההחלפה תפסה
    צריך את שתי הצורות, ולכן מחשבים כאן את הצורה העברית.

    מחזיר "" אם הקלט אינו שנה סבירה.
    """
    try:
        n = int(str(gregorian).strip())
    except (TypeError, ValueError):
        return ""
    if not (1900 <= n <= 2200):
        return ""

    hebrew = n + _HEBREW_YEAR_OFFSET
    remainder = hebrew % 1000       # את ה"ה' אלפים" לא כותבים בכתיב המקובל

    letters = ""
    for value, ch in _GEMATRIA:
        while remainder >= value:
            letters += ch
            remainder -= value

    # 15 ו-16 נכתבים טו/טז ולא יה/יו (מנהג שלא לכתוב צירוף של שם השם).
    letters = letters.replace("יה", "טו").replace("יו", "טז")

    if len(letters) >= 2:
        return letters[:-1] + '"' + letters[-1]     # גרשיים לפני האות האחרונה
    return letters + "'" if letters else ""


def _normalize_hebrew_year(text: str) -> str:
    """
    מנרמל תווית שנה עברית להשוואה: מוריד גרשיים/רווחים/ישויות HTML
    וממפה אותיות סופיות. ``'תשפ"ז'`` ו-``'תשפ&quot;ז'`` -> ``'תשפז'``.
    """
    if not text:
        return ""
    t = html_lib.unescape(str(text)).translate(_FINAL_LETTERS)
    # משאירים אך ורק אותיות עבריות — כל השאר הוא עיטור.
    return "".join(ch for ch in t if "א" <= ch <= "ת")


#: כותרת דף החיפוש: ``<h2> חיפוש קורסים במערכת תשפ"ז </h2>``.
#: דורשים שהתווית תתחיל ב"תש" כדי לא לתפוס את ה-<h1> חסר-השנה שבראש הדף.
_HEADER_YEAR_RE = re.compile(
    r"חיפוש\s+קורסים\s+במערכת\s*(תש[א-ת\"'׳״]{1,10})"
)

#: כותרת דף קורס: ``<h2 class="TextAlignCenter"> קורס מתמטיקה ב' שנה"ל תשפ"ז</h2>``.
_COURSE_YEAR_RE = re.compile(
    r"שנה\s*[\"'׳״]?\s*ל\s*(תש[א-ת\"'׳״]{1,10})"
)

#: התווית ``שנה"ל`` לבדה, בלי השנה שאחריה. סימן לכך שהדף הוא דף קורס: דף
#: החיפוש כותב ``חיפוש קורסים במערכת תשפ"ז`` — שנה בלי התווית הזאת.
_COURSE_YEAR_LABEL_RE = re.compile(r"שנה\s*[\"'׳״]?\s*ל(?![א-ת])")

#: ``<option selected value="2027">2027 - תשפ"ז</option>`` — סימן משני לכך
#: שהחלפת השנה תפסה (GROUND_TRUTH סעיף 8: "both selects came back with 2026").
_SELECTED_YEAR_RE = re.compile(
    r"<option[^>]*\bselected\b[^>]*\bvalue\s*=\s*[\"']?((?:19|20)\d{2})",
    re.IGNORECASE,
)


def _header_year_label(page_html: str) -> str:
    """מחזיר את תווית השנה מכותרת דף החיפוש, או "" אם לא נמצאה."""
    if not page_html:
        return ""
    text = html_lib.unescape(page_html)
    m = _HEADER_YEAR_RE.search(text)
    return m.group(1).strip() if m else ""


def _course_year_label(page_html: str) -> str:
    """מחזיר את תווית השנה מכותרת דף קורס (``שנה"ל תשפ"X``), או ""."""
    if not page_html:
        return ""
    text = html_lib.unescape(page_html)
    m = _COURSE_YEAR_RE.search(text)
    return m.group(1).strip() if m else ""


def _selected_year_value(page_html: str) -> str:
    """מחזיר את השנה הלועזית שמסומנת כרגע באחד מבוררי השנה, או ""."""
    if not page_html:
        return ""
    m = _SELECTED_YEAR_RE.search(page_html)
    return m.group(1) if m else ""


#: כמה קבוצות יש בדף? כל קבוצה מביאה איתה כפתור "פרטים נוספים" עם
#: data-progname="S_CourseDetails" ותווית ``קבוצה :`` בתוך span כחול.
_GROUP_MARKERS = ("S_CourseDetails", "קבוצה :", "קבוצה:")

#: ניסוחים אפשריים של "אין תוצאות". הידיעון של MTA לא מציג אף אחד מהם
#: (הוא פשוט מחזיר דף עם כותרת ובלי קבוצות), אבל מוסדות שונים מנסחים אחרת —
#: ולכן נשארים סובלניים.
_NO_RESULT_MARKERS = (
    "לא נמצאו",
    "לא נמצא קורס",
    "לא נמצאה",
    "אין קורסים",
    "אין נתונים",
    "לא קיימים נתונים",
    "לא קיים קורס",
)


def _count_group_blocks(page_html: str) -> int:
    """
    ספירה גסה של בלוקי קבוצה בדף תוצאות.

    לא פירסור — רק "יש כאן משהו או שהדף ריק?". הפירסור האמיתי נעשה ב-parser.
    """
    if not page_html:
        return 0
    text = html_lib.unescape(page_html)
    return max(text.count(marker) for marker in _GROUP_MARKERS)


def _looks_like_course_page(page_html: str) -> bool:
    """
    האם זה בכלל דף תוצאות של קורס (ולא טופס החיפוש / דף שגיאה)?

    הסימן: כותרת ``קורס ... שנה"ל תש...`` שמופיעה גם כשאין אף קבוצה.
    """
    return bool(_course_year_label(page_html))


def _has_no_results_marker(page_html: str) -> bool:
    """
    האם הדף אומר במפורש (או במבנה) "הקורס לא נפתח / לא נמצא"?

    לפי GROUND_TRUTH סעיף 6, קוד שלא נפתח בשנה הנבחרת מחזיר **200 עם הכותרת
    הנכונה ובלי אף בלוק קבוצה**. זה לא כישלון של הגורד — זה תשובה לגיטימית,
    ולכן אסור לנו "לתקן" אותה בגיבוי של מילוי טופס. זה בדיוק המקרה של
    61753 אלגוריתמים, שאולי בכלל לא נפתח בסמסטר א'.
    """
    if not page_html:
        return False
    if _looks_like_course_page(page_html):
        return True
    text = html_lib.unescape(page_html)
    return any(marker in text for marker in _NO_RESULT_MARKERS)


# --- גשר עצל אל הפרסר ------------------------------------------------------
#: תוצאת הייבוא העצל של parser.extract_page_year: פונקציה, או False = ניסינו
#: ולא הצלחנו (לא מנסים שוב בכל קורס).
_EXTRACT_PAGE_YEAR: object = None


def _load_extract_page_year():
    """
    ייבוא **עצל** של ``parser.extract_page_year``.

    עצל בכוונה: scraper ו-parser נמצאים באותה חבילה, וייבוא ישיר בראש הקובץ
    היה יוצר תלות מעגלית קשיחה. אם הייבוא נכשל (או שהפונקציה עדיין לא קיימת
    בגרסה הזאת של הפרסר) — מחזירים None והבודק נופל לרגקס מקומי.
    """
    global _EXTRACT_PAGE_YEAR
    if _EXTRACT_PAGE_YEAR is not None:
        return _EXTRACT_PAGE_YEAR or None

    for module_name in ("parser", "src.parser"):
        try:
            module = importlib.import_module(module_name)
        except Exception:  # noqa: BLE001 - any import problem => use the regex
            continue
        func = getattr(module, "extract_page_year", None)
        if callable(func):
            _EXTRACT_PAGE_YEAR = func
            return func

    _EXTRACT_PAGE_YEAR = False      # ניסינו, אין — לא מנסים שוב
    return None


def _coerce_year_value(value: object) -> str:
    """
    הופך את מה ש-``extract_page_year`` החזיר למחרוזת אחת.

    הפרסר בבעלות סוכן אחר, ולכן אנחנו סובלניים לגבי צורת ההחזרה: מחרוזת
    ("2027" או 'תשפ"ז'), טאפל, או מילון עם מפתח סביר.
    """
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
    האם השנה שנמצאה בדף היא השנה שביקשנו?

    Returns:
        True / False, או **None** אם אי אפשר להכריע (ואז לא זורקים כלום —
        עדיף לא לחסום ריצה תקינה בגלל ניסוח שלא הכרנו).
    """
    if not found or not want_gregorian:
        return None

    # 1. אם יש בטקסט שנה לועזית — זו ההשוואה הכי חדה שיש.
    m = re.search(r"(?:19|20)\d{2}", found)
    if m:
        return m.group(0) == str(want_gregorian).strip()

    # 2. אחרת משווים תוויות עבריות מנורמלות ('תשפ"ז' מול תשפ"ז שחישבנו).
    want_label = _normalize_hebrew_year(hebrew_year_label(want_gregorian))
    got_label = _normalize_hebrew_year(found)
    if want_label and got_label:
        return want_label == got_label
    return None


# --------------------------------------------------------------------------
# הגורד עצמו
# --------------------------------------------------------------------------
class BraudeScraper:
    """
    מנהל חלון דפדפן קבוע מול הידיעון של בראודה.

    שימוש טיפוסי::

        with BraudeScraper(year="2027") as scraper:
            if scraper.open_and_wait_for_login():
                pages = scraper.scrape(["61753", "61756"])
            print(scraper.errors)

    השדה ``errors`` צובר תקלות כזוגות ``(code, message)`` — הגירוד לא נעצר
    בגלל קורס אחד שנכשל.
    """

    def __init__(
        self,
        profile_dir: str = "data/.browser_profile",
        raw_dir: str = "data/raw",
        headless: bool = False,
        year: str | None = None,
    ) -> None:
        """
        Args:
            profile_dir: תיקיית פרופיל הדפדפן הקבוע. שם נשמרות העוגיות של
                Citrix, ולכן ההתחברות שורדת בין הרצות.
            raw_dir: לאן נשמרים דמפים של HTML וצילומי מסך.
            headless: כמעט תמיד False — צריך חלון אמיתי כדי להתחבר ידנית.
            year: שנת הלימודים ה**לועזית** להחלפה, למשל "2027" עבור תשפ"ז.
                None = לא נוגעים בשנה (ואז מקבלים את ברירת המחדל של האתר,
                שהיא כרגע תשפ"ו — כמעט אף פעם לא מה שרוצים).
        """
        self.profile_dir = self._resolve(profile_dir)
        self.raw_dir = self._resolve(raw_dir)
        self.headless = headless
        self.year = str(year).strip() if year else None

        #: תקלות שנצברו: [(code, message), ...]
        self.errors: list[tuple[str, str]] = []
        #: איזו אסטרטגיה הצליחה לכל קוד — שימושי לדיבוג עתידי.
        self.strategy_log: list[tuple[str, str]] = []
        #: תווית השנה שהדף הציג אחרי ההחלפה (למשל 'תשפ"ז'), אם הוחלפה.
        self.year_label: str = ""

        self._playwright = None
        self.context = None
        self.page: Page | None = None
        self._logged_in = False
        self._dump_counters: dict[str, int] = {}
        self._year_applied = False

    # ---------------------------------------------------------------- paths
    @staticmethod
    def _resolve(path_like: str | Path) -> Path:
        """נתיב יחסי נפתר מול שורש הפרויקט, לא מול תיקיית ההרצה."""
        p = Path(path_like)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    def _log(self, message: str) -> None:
        """הדפסה אחידה עם קידומת, כדי שקל יהיה לסנן את הפלט של הגורד."""
        print(f"[scraper] {message}", flush=True)

    # ------------------------------------------------------- context manager
    def __enter__(self) -> "BraudeScraper":
        """פותח את Playwright ואת חלון הדפדפן הקבוע."""
        enable_utf8_stdout()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = sync_playwright().start()

        # launch_persistent_context = דפדפן עם פרופיל על הדיסק.
        # זה בדיוק מה שגורם לכך שההתחברות ל-Citrix שורדת בין הרצות.
        launch_kwargs: dict = {
            "user_data_dir": str(self.profile_dir),
            "headless": self.headless,
            "locale": "he-IL",
            "timezone_id": "Asia/Jerusalem",
            "accept_downloads": False,
            "args": ["--start-maximized"],
        }
        if not self.headless:
            # no_viewport => החלון מקבל את גודל המסך האמיתי (נוח לקריאה בעברית).
            launch_kwargs["no_viewport"] = True

        try:
            self.context = self._playwright.chromium.launch_persistent_context(**launch_kwargs)
        except PlaywrightError as exc:
            # התקלה הנפוצה: חלון דפדפן קודם עדיין פתוח ונועל את הפרופיל.
            self._safe_stop_playwright()
            raise RuntimeError(
                "לא הצלחתי לפתוח את הדפדפן. אולי נשאר חלון פתוח מהרצה קודמת "
                f"שנועל את {self.profile_dir}? יש לסגור אותו ולנסות שוב.\n"
                f"(Could not launch the persistent browser context: {exc})"
            ) from exc

        self.context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        self.context.set_default_timeout(ACTION_TIMEOUT_MS)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        """סוגר את הדפדפן ואת Playwright. לא בולע חריגות של המשתמש."""
        try:
            if self.context is not None:
                self.context.close()
        except Exception:  # noqa: BLE001 - סגירה היא best-effort בלבד
            pass
        finally:
            self.context = None
            self.page = None
            self._safe_stop_playwright()
        return False  # False = אל תבלע חריגה שקרתה בתוך ה-with

    def _safe_stop_playwright(self) -> None:
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._playwright = None

    def _require_page(self) -> Page:
        """מחזיר את הדף הפעיל, או זורק שגיאה ברורה אם לא נכנסנו ל-with."""
        if self.page is None:
            raise RuntimeError(
                "הדפדפן לא פתוח. יש להשתמש ב-`with BraudeScraper() as scraper:` "
                "(the scraper must be used as a context manager)."
            )
        return self.page

    def _page_html(self) -> str:
        """``page.content()`` שלא זורק — מחזיר "" אם הדף באמצע ניווט."""
        try:
            return self._require_page().content()
        except (PlaywrightError, RuntimeError):
            return ""

    # ------------------------------------------------------------- dumping
    def _next_index(self, code: str) -> int:
        """מספר רץ לכל קוד קורס, כדי שקבצי הדמפ לא ידרסו זה את זה."""
        self._dump_counters[code] = self._dump_counters.get(code, 0) + 1
        return self._dump_counters[code]

    def dump_page(self, code: str, screenshot: bool = False) -> Path | None:
        """
        שומר את ה-HTML הנוכחי ל-data/raw/<code>_<n>.html ומחזיר את הנתיב.

        זו הפעולה הכי חשובה במודול: **תמיד** קוראים לה לפני שמחזירים HTML
        למישהו. גם אם הכול נשבר, לפחות יש לנו את הדף על הדיסק.

        **מחסום אבטחה:** אם הדף הנוכחי אינו מ-info.braude.ac.il — לא נכתב
        כלום, לא HTML ולא צילום מסך, ומוחזר ``None``. הדף היחיד שיכול להיות
        שם הוא שער ההתחברות, ובפרופיל קבוע הדפדפן כבר מילא בו את שם המשתמש;
        כתיבה שלו ל-data/raw/ (התיקייה שנשלחת לתמיכה) הייתה מפרה את כלל
        ברזל מס' 1. הבדיקה כאן היא בנוסף לבדיקות שבמסלולי הקריאה — הגנה
        לעומק, כי זו בדיוק הטעות שאסור לעשות אפילו פעם אחת.

        Args:
            code: קוד הקורס (משמש כשם הקובץ).
            screenshot: אם True, נשמר גם צילום מסך <code>_<n>.png באותו מספר.

        Returns:
            הנתיב לקובץ שנשמר, או None אם הכתיבה נחסמה.
        """
        page = self._require_page()

        current_url = ""
        try:
            current_url = page.url
        except PlaywrightError:
            current_url = ""

        if not is_success_url(current_url):
            # מדווחים שם מארח בלבד — לא URL מלא, שעלול להכיל טוקנים.
            self._log(
                f"דמפ נחסם: הדף הנוכחי אינו של הידיעון ({_host_of(current_url) or 'unknown'}). "
                "(refusing to write a non-yedion page to data/raw/)"
            )
            return None

        n = self._next_index(code)
        html_path = self.raw_dir / f"{code}_{n}.html"

        try:
            html = page.content()
        except PlaywrightError as exc:
            html = f"<!-- failed to read page content: {exc} -->"

        # הגנה לעומק, בדיוק כמו מחסום ה-host שמעליה: דמפ תקין לעולם אינו
        # נדרס בגוף שאינו דף. ‏dump_page רץ לפני האימות בכוונה ("קודם
        # לדיסק"), ולכן הבדיקה חייבת לשבת כאן ולא רק אצל הקוראים.
        ok, why = looks_like_a_page(html)
        if not ok:
            try:
                shed = self.raw_dir / "blocked"
                shed.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
                (shed / f"{code}_{stamp}.html").write_text(
                    html, encoding="utf-8", errors="replace"
                )
            except OSError:
                pass
            self._log(
                f"לא נשמר: מה שחזר עבור {code} אינו דף ({why}). הדמפ הקודם "
                "נשמר כמו שהוא. (refused to overwrite a good dump)"
            )
            return None

        # encoding="utf-8" חובה — הידיעון כולו בעברית.
        html_path.write_text(html, encoding="utf-8", errors="replace")
        self._log(f"נשמר HTML: {html_path}")

        if screenshot:
            png_path = self.raw_dir / f"{code}_{n}.png"
            try:
                page.screenshot(path=str(png_path), full_page=True)
                self._log(f"נשמר צילום מסך: {png_path}")
            except PlaywrightError as exc:
                self._log(f"אזהרה: לא הצלחתי לצלם מסך ({exc}).")

        return html_path

    @staticmethod
    def _dump_note(path: Path | None) -> str:
        """טקסט קצר להודעות שגיאה: 'דמפ: ...' או הסבר למה אין דמפ."""
        if path is None:
            return "(לא נשמר דמפ — הדף אינו של הידיעון / no dump saved)"
        return f"דמפ: {path}"

    # ---------------------------------------------------------------- login
    def open_and_wait_for_login(self, timeout_s: int = 600) -> bool:
        """
        פותח את דף ההתחברות ומחכה שההתחברות תתבצע ידנית בחלון הדפדפן.

        השלבים:
          1. בדיקה שקטה — אולי הסשן מההרצה הקודמת עדיין חי. אם כן, מסיימים מיד.
          2. אחרת: ניווט ל-LOGIN_URL והדפסת הוראות ברורות בעברית ובאנגלית.
          3. סקירה כל 2 שניות של כל הלשוניות הפתוחות, עד שאחת מהן נוחתת על
             info.braude.ac.il — זו ההוכחה שההתחברות עברה.

        **המודול לא נוגע בשדות שם המשתמש/סיסמה, לא קורא אותם ולא מדפיס אותם.**

        Returns:
            True אם ההתחברות אושרה בזמן, אחרת False.
        """
        self._require_page()

        # --- שלב 1: אולי כבר מחוברים מהרצה קודמת (זה כל היופי בפרופיל קבוע) ---
        self._log("בודק אם הסשן מההרצה הקודמת עדיין תקף…")
        if self._probe_search_page():
            self._log("מצוין — כבר מחוברים, אין צורך להתחבר שוב. (Already logged in.)")
            self._logged_in = True
            self._apply_year_if_needed()
            return True

        # --- שלב 2: ניווט לשער ההתחברות והדפסת הוראות ---
        self._goto_login_page()
        print()
        print(
            _banner(
                [
                    "התחברות ידנית לידיעון — MANUAL LOGIN",
                    "",
                    "נפתח חלון דפדפן. יש להתחבר בו עם שם המשתמש והסיסמה.",
                    "A browser window is open. Please log in there yourself.",
                    "",
                    "אין לסגור את החלון! הסקריפט מחכה ויזהה לבד שההתחברות בוצעה.",
                    "Do NOT close the window. The script detects login by itself.",
                    "",
                    "הסקריפט לא מבקש, לא רואה ולא שומר סיסמאות — לעולם.",
                    "This script never asks for, sees, or stores credentials.",
                    "",
                    f"ממתין עד {timeout_s} שניות… (waiting)",
                ]
            )
        )
        print(flush=True)

        # --- שלב 3: לולאת ההמתנה ---
        deadline = time.monotonic() + timeout_s
        last_report = 0.0
        # בדיקה יזומה כל כמה שניות. *לא* מותנית בצורת ה-URL — ראה הנימוק למטה.
        PROBE_EVERY_S = 12.0
        last_probe = time.monotonic()

        while time.monotonic() < deadline:
            landed = self._find_logged_in_page()
            if landed is not None:
                self.page = landed
                self._logged_in = True
                print()
                self._log(f"התחברות זוהתה! הדפדפן נחת על {landed.url}")
                self._log("Login detected. Continuing.")
                self._apply_year_if_needed()
                return True

            # דיווח התקדמות כל 30 שניות, כדי שלא ייראה תקוע.
            remaining = int(deadline - time.monotonic())
            if remaining and (last_report - remaining >= 30 or last_report == 0):
                last_report = remaining
                self._log(f"ממתין להתחברות… נותרו כ-{remaining} שניות. (waiting for login)")

            # בדיקה יזומה: מנסים לפתוח את דף החיפוש ורואים אם הוא נתפס.
            #
            # למה בלי שום תנאי על צורת ה-URL: אחרי התחברות מוצלחת שער ה-Citrix
            # משאיר את הדפדפן על פורטל שכתובתו מכילה "/vpn/" — שהוא בעצמו אחד
            # מ-LOGIN_URL_MARKERS. כלומר "עדיין בהתחברות" ו"התחברנו ועומדים
            # בפורטל" נראים *זהים* מבחינת ה-URL, ואי אפשר להבדיל ביניהם כך.
            # זה בדיוק הכשל שנצפה בשטח: המשתמש/ת התחבר/ה, הדפדפן עמד על
            # /vpn/index.html, והתנאי הישן חסם את הבדיקה עד שפג הזמן.
            # הסימן היחיד שאפשר לסמוך עליו הוא לנסות בפועל.
            # זה בטוח: _probe_search_page פותח לשונית זמנית ונמנע לגמרי כל עוד
            # יש שדה סיסמה על המסך, כך שאי אפשר להפריע להקלדה.
            if time.monotonic() - last_probe >= PROBE_EVERY_S:
                last_probe = time.monotonic()
                if self._probe_search_page():
                    self._logged_in = True
                    print()
                    self._log("התחברות זוהתה! (Login detected.)")
                    self._apply_year_if_needed()
                    return True

            time.sleep(POLL_INTERVAL_S)

        self._log(
            f"פג הזמן ({timeout_s} שניות) ולא זוהתה התחברות. "
            "(Timed out waiting for manual login.)"
        )
        return False

    def _goto_login_page(self) -> None:
        """
        מנווט לשער ההתחברות.

        מנסה קודם את LOGIN_URL מה-SPEC, אחר כך את הכתובת החלופית שנצפתה
        בהפניה בפועל, ולבסוף פשוט ניגש ל-SEARCH_URL — משתמש אנונימי מקבל
        ממנו 302 לשער הנכון, ואז השרת בוחר את הכתובת במקומנו.
        """
        page = self._require_page()
        for url in (LOGIN_URL, LOGIN_URL_ALT, SEARCH_URL):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                self._log(f"נפתח דף התחברות: {page.url}")
                return
            except PlaywrightError as exc:
                self._log(f"אזהרה: לא הצלחתי לטעון {url} ({type(exc).__name__}). מנסה חלופה…")
        self._log("אזהרה: אף כתובת התחברות לא נטענה. אפשר לנווט ידנית בחלון הדפדפן.")

    def _current_url(self) -> str:
        try:
            return self._require_page().url
        except (PlaywrightError, RuntimeError):
            return ""

    def _find_logged_in_page(self) -> Page | None:
        """
        סורק את כל הלשוניות הפתוחות ומחזיר את הראשונה שנחתה על info.braude.ac.il.

        סורקים את כולן ולא רק את הדף הראשי, כי שער Citrix לפעמים פותח
        לשונית חדשה אחרי ההתחברות.
        """
        if self.context is None:
            return None
        for p in list(self.context.pages):
            try:
                if p.is_closed():
                    continue
                if is_success_url(p.url):
                    return p
            except PlaywrightError:
                continue
        return None

    def _credentials_on_screen(self) -> bool:
        """
        האם באחת הלשוניות הפתוחות מוצג כרגע שדה סיסמה?

        זו בדיקת *נימוס*, לא בדיקת אבטחה: אם מסך התחברות פתוח כרגע, אסור לנו
        לפתוח מעליו לשונית או לנווט מתחת לידיים. הפונקציה רק סופרת אלמנטים —
        היא לא קוראת שום ערך משדה ולא מדפיסה כלום.
        """
        if self.context is None:
            return False
        for p in list(self.context.pages):
            try:
                if p.is_closed():
                    continue
                if p.locator("input[type='password']").count() > 0:
                    return True
            except PlaywrightError:
                continue        # דף באמצע ניווט — לא יודעים, ממשיכים הלאה
        return False

    def _probe_search_page(self) -> bool:
        """
        ניסיון שקט לפתוח את דף החיפוש. True אם נחתנו על info.braude.ac.il.

        אם אין סשן תקף, השרת יחזיר 302 לשער ההתחברות — נזהה זאת לפי ה-URL
        ונחזיר False בלי להרעיש.

        **הבדיקה נעשית בלשונית זמנית ולא בלשונית שבה מקלידים.** קודם היא
        ניווטה את הלשונית הפעילה, וזה היה הרסני: ה-URL של שער ההתחברות לא
        תמיד מכיל את אחת המילים ב-LOGIN_URL_MARKERS (למשל שלב nFactor או
        הפניה ל-Microsoft), ואז הבדיקה הייתה מנווטת בדיוק את הלשונית שבה
        מוקלדת סיסמה או קוד חד-פעמי ומוחקת את הטופס באמצע.
        עכשיו: לשונית חדשה, ואם הסשן תקף — מאמצים אותה כלשונית העבודה
        (היא כבר עומדת על דף החיפוש); אחרת סוגרים אותה ולא נשאר ממנה זכר.
        """
        if self.context is None:
            return False
        if self._credentials_on_screen():
            # התחברות בעיצומה — לא מפריעים בכלל.
            return False

        probe = None
        ok = False
        try:
            probe = self.context.new_page()
            probe.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            ok = is_success_url(probe.url)
        except PlaywrightError:
            ok = False

        if probe is None:
            return False
        if ok:
            self.page = probe        # מאמצים את הלשונית שכבר עומדת על דף החיפוש
            return True
        try:
            probe.close()
        except PlaywrightError:
            pass
        return False

    # ------------------------------------------------------ academic year
    def _apply_year_if_needed(self) -> None:
        """
        מנסה להחליף שנה מיד אחרי ההתחברות — אבל בלי להפיל את ההתחברות.

        למה כאן זה "רך" ובתוך ``scrape`` זה "קשה"? כי כישלון כאן עדיין לא
        מסוכן: לא נשלף שום נתון. ``scrape`` ינסה שוב, והפעם ברעש — הוא לא
        יתחיל להביא קורסים בלי שהשנה אושרה.
        """
        if not self.year or self._year_applied:
            return
        try:
            self.set_year(self.year)
        except (YearSwitchError, PlaywrightError, RuntimeError) as exc:
            self._log(f"אזהרה: החלפת השנה בשלב ההתחברות לא הצליחה ({exc}). ננסה שוב לפני הסריקה.")

    def _year_select(self, year: str):
        """
        מאתר את בורר השנה בדף.

        סדר הניסיונות:
          1. ``#ChangeYear`` — המזהה המאומת (GROUND_TRUTH סעיף 1).
          2. בורר ששמו/מזהו מרמז על שנה.
          3. כל בורר שהערכים שלו נראים כמו שנים (4 ספרות) ושמכיל את השנה
             המבוקשת — שימו לב שבדף יש גם בורר שנה *של הבחינות* (R1C39),
             ולכן ``#ChangeYear`` תמיד קודם.

        Returns:
            (locator, description) או (None, "").
        """
        page = self._require_page()
        attempts = [
            ("id-ChangeYear", f"select#{YEAR_SELECT_ID}"),
            ("name-ChangeYear", f"select[name='{YEAR_SELECT_ID}']"),
            ("attr-year", "select[name*='year' i], select[id*='year' i], "
                          "select[name*='shana' i], select[id*='shana' i]"),
            ("any-select", "select"),
        ]
        for label, css in attempts:
            try:
                loc = page.locator(css)
                count = min(loc.count(), 25)
            except PlaywrightError:
                continue
            for i in range(count):
                sel = loc.nth(i)
                try:
                    if not sel.is_visible():
                        continue
                    options: list[dict] = sel.evaluate(
                        "el => Array.from(el.options).map("
                        "o => ({value: (o.value || ''), label: (o.textContent || '').trim(), "
                        "selected: !!o.selected}))"
                    )
                except PlaywrightError:
                    continue
                # בורר שנה = יש בו לפחות שתי אפשרויות שנראות כמו שנה,
                # והשנה שאנחנו רוצים היא אחת מהן.
                year_values = [
                    str(o.get("value", "")).strip()
                    for o in options
                    if re.fullmatch(r"(?:19|20)\d{2}", str(o.get("value", "")).strip())
                ]
                if len(year_values) >= 2 and str(year) in year_values:
                    return sel, f"{label}[{i}]"
        return None, ""

    def _click_year_button(self) -> bool:
        """
        לוחץ על כפתור "מעבר שנה".

        הכפתור המדויק הוא זה שה-data-arguments שלו מכיל ``ChangeYear``
        (GROUND_TRUTH סעיף 1). חשוב להתחיל דווקא ממנו: בדף יש **שני** כפתורי
        "מעבר שנה" — השני שייך לחיפוש הבחינות (``-A,,-A,R1C39``) ולא משנה את
        שנת הקורסים. אחריו נופלים לזיהוי לפי טקסט.
        """
        return self._click_first_visible(
            [
                f"button[data-progname='{PRGNAME_ENTER_SEARCH}']"
                f"[data-arguments*='{YEAR_SELECT_ID}']",
                f"[data-arguments*='{YEAR_SELECT_ID}']",
                f"button:has-text('{BUTTON_YEAR_CHANGE}')",
                f"input[type='submit'][value*='{BUTTON_YEAR_CHANGE}']",
                f"input[type='button'][value*='{BUTTON_YEAR_CHANGE}']",
                f"a:has-text('{BUTTON_YEAR_CHANGE}')",
            ]
        )

    def _post_change_year(self, year: str) -> bool:
        """
        גיבוי: שולח את בקשת החלפת השנה ישירות, דרך ההקשר המאומת.

        זו בדיוק הבקשה שאומתה מול מופע חי (GROUND_TRUTH סעיף 8)::

            POST /yedion/fireflyweb.aspx
                PRGNAME   = Enter_Search
                ARGUMENTS = -A,,-A,ChangeYear
                ChangeYear = 2027

        ``page.request`` חולק עוגיות עם הדפדפן, ולכן הבקשה יוצאת מאומתת בלי
        שנגענו בשום פרט התחברות. התשובה **לא** נכתבת לדיסק.
        """
        page = self._require_page()
        try:
            response = page.request.post(
                BASE_URL,
                form={
                    "PRGNAME": PRGNAME_ENTER_SEARCH,
                    "ARGUMENTS": ARGS_CHANGE_YEAR,
                    YEAR_SELECT_ID: str(year),
                },
                timeout=NAV_TIMEOUT_MS,
            )
        except Exception as exc:  # noqa: BLE001 - גם AttributeError: בגרסאות
            # ישנות של playwright אין page.request בכלל. כישלון כאן הוא לא סוף
            # העולם — האימות שאחריו הוא שיחליט אם נכשלנו באמת.
            self._log(f"אזהרה: POST להחלפת שנה נכשל ({type(exc).__name__}: {exc}).")
            return False

        ok = bool(getattr(response, "ok", False))
        self._log(f"POST להחלפת שנה נשלח (status={getattr(response, 'status', '?')}).")
        return ok

    def _goto_search_page(self) -> bool:
        """מנווט לדף החיפוש ומוודא שנחתנו על הידיעון עצמו."""
        page = self._require_page()
        try:
            page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except PlaywrightError as exc:
            self._log(f"אזהרה: טעינת דף החיפוש נכשלה ({type(exc).__name__}: {exc}).")
            return False
        self._wait_for_settle()
        if is_success_url(page.url):
            return True
        # הופנינו לשער ההתחברות — הסשן פג. הדף הזה לא נשמר לדיסק לעולם.
        return False

    def set_year(self, year: str) -> str:
        """
        מחליף את שנת הלימודים של הסשן ומחזיר את תווית השנה שהדף מציג עכשיו.

        למה זה קריטי: שנת הלימודים בידיעון היא **מצב-סשן**, לא פרמטר ב-URL.
        הידיעון של בראודה נפתח על תשפ"ו, וכל שליפה בלי החלפה מפורשת הייתה
        מחזירה בשקט את המערכת של שנה שעברה. GROUND_TRUTH סעיף 8.

        סדר הפעולות:
          1. **דרך ה-UI האמיתי** — בוחרים ב-``#ChangeYear`` ולוחצים "מעבר שנה".
          2. **גיבוי** — POST ישיר דרך ההקשר המאומת (PRGNAME=Enter_Search,
             ARGUMENTS=-A,,-A,ChangeYear, ChangeYear=<year>).
          3. **קוראים את הדף מחדש ומאמתים** שהכותרת
             "חיפוש קורסים במערכת <שנה>" באמת מציגה את השנה המבוקשת.

        Args:
            year: השנה הלועזית, למשל "2027" (= תשפ"ז).

        Returns:
            תווית השנה שמוצגת עכשיו בדף, למשל ``'תשפ"ז'``.

        Raises:
            YearSwitchError: אם לא הצלחנו לאמת שהשנה התחלפה. **בכוונה** —
                שנה שגויה בשקט היא הכישלון הגרוע ביותר של הכלי הזה.
        """
        year = str(year).strip()
        want_label = hebrew_year_label(year)
        self._require_page()

        # --- ודאו שאנחנו בכלל על דף החיפוש ---
        if not is_success_url(self._current_url()) and not self._probe_search_page():
            raise YearSwitchError(
                f"לא הצלחתי להגיע לדף החיפוש כדי להחליף לשנת {year} "
                f"({want_label or '?'}). ייתכן שהסשן פג — יש להריץ שוב ולהתחבר. "
                "(Could not reach the search page to switch the academic year.)"
            )
        if not self._goto_search_page():
            raise YearSwitchError(
                f"דף החיפוש לא נטען (או שהופנינו חזרה להתחברות) בזמן המעבר לשנת {year}. "
                "(Search page did not load while switching the year.)"
            )

        current = _header_year_label(self._page_html())

        # --- כבר על השנה הנכונה? אין מה לעשות ---
        if current and want_label and _normalize_hebrew_year(current) == _normalize_hebrew_year(want_label):
            self._log(f"הידיעון כבר מציג את שנת {current} ({year}) — אין צורך להחליף.")
            self._year_applied = True
            self.year_label = current
            return current

        if current:
            self._log(f"הידיעון מציג כרגע {current}; מחליף ל-{want_label or year}…")
        else:
            self._log(f"לא זיהיתי את תווית השנה בכותרת; מנסה בכל זאת לעבור ל-{want_label or year}…")

        # --- אסטרטגיה 1: ה-UI האמיתי ---
        used = ""
        sel, where = self._year_select(year)
        if sel is not None:
            before = _sha1(self._page_html())
            try:
                sel.select_option(value=year)
                self._log(f"נבחרה השנה {year} בבורר ({where}).")
                if self._click_year_button():
                    self._wait_for_change(before, timeout_s=YEAR_SWITCH_WAIT_S)
                    self._wait_for_settle()
                    used = f"ui:{where}"
                else:
                    self._log("אזהרה: לא נמצא כפתור 'מעבר שנה' — עובר לגיבוי.")
            except PlaywrightError as exc:
                self._log(f"אזהרה: בחירת השנה ב-UI נכשלה ({type(exc).__name__}: {exc}).")
        else:
            self._log("אזהרה: לא נמצא בורר שנה בדף — עובר לגיבוי.")

        # --- קריאה חוזרת של הדף ואימות ---
        label = self._verify_year_on_page(year, want_label)
        if label:
            self._year_applied = True
            self.year_label = label
            self.strategy_log.append(("year", used or "ui"))
            self._log(f"מעבר שנה אושר: הדף מציג {label} ({year}). (year switch verified)")
            return label

        # --- אסטרטגיה 2: POST ישיר דרך ההקשר המאומת ---
        self._log("המעבר דרך ה-UI לא אושר — מנסה POST ישיר (הפרוטוקול המאומת).")
        self._post_change_year(year)
        label = self._verify_year_on_page(year, want_label)
        if label:
            self._year_applied = True
            self.year_label = label
            self.strategy_log.append(("year", "post"))
            self._log(f"מעבר שנה אושר אחרי POST: הדף מציג {label} ({year}).")
            return label

        # --- נכשלנו. נופלים ברעש. ---
        seen = _header_year_label(self._page_html()) or _selected_year_value(self._page_html()) or "לא ידוע"
        raise YearSwitchError(
            f"לא הצלחתי לעבור לשנת הלימודים {year} ({want_label or '?'}). "
            f"הדף עדיין מציג: {seen}. "
            "בלי השנה הנכונה הידיעון היה מחזיר את המערכת של שנה אחרת, ולכן "
            "הריצה נעצרת כאן במכוון. "
            "(Failed to switch the academic year; refusing to continue with the wrong year.)"
        )

    def _verify_year_on_page(self, year: str, want_label: str) -> str:
        """
        טוען מחדש את דף החיפוש ובודק שהכותרת מציגה את השנה המבוקשת.

        Returns:
            תווית השנה שנמצאה אם היא תואמת, אחרת "".
        """
        if not self._goto_search_page():
            return ""
        page_html = self._page_html()

        label = _header_year_label(page_html)
        if label and want_label:
            if _normalize_hebrew_year(label) == _normalize_hebrew_year(want_label):
                return label
            return ""

        # אין כותרת מזוהה (ניסוח אחר במוסד אחר?) — נופלים לסימן המשני:
        # ה-<option> שמסומן selected בבורר השנה.
        selected = _selected_year_value(page_html)
        if selected and selected == str(year):
            return label or want_label or selected
        return ""

    # ------------------------------------------------- year assertion (pages)
    def _assert_page_year(self, code: str, page_html: str) -> None:
        """
        מוודא שדף הקורס שנשלף באמת שייך לשנה שהוגדרה לגורד.

        GROUND_TRUTH סעיף 8, שלב 6: הכותרת ``h2.TextAlignCenter`` מכילה
        ``שנה"ל תשפ"X``. אם היא מצהירה על שנה אחרת — לא מפרסרים, זורקים.

        **הסימן הראשי הוא הרגקס המקומי** על ``שנה"ל תשפ"X`` — בדיוק הכותרת
        שה-GROUND_TRUTH מתאר. ``parser.extract_page_year`` (ייבוא **עצל**, כדי
        לא ליצור תלות מעגלית) רחב יותר: כשאין כותרת עם התווית הוא מסתפק ב*כל*
        כותרת בדף, כולל ``חיפוש קורסים במערכת תשפ"ז`` של טופס החיפוש עצמו —
        ואז דף שאינו דף קורס בכלל היה יוצא "מאומת". לכן הוא נקרא רק כגיבוי,
        ורק כשהתווית ``שנה"ל`` כן קיימת בדף אבל הרגקס לא הצליח לקרוא ממנה שנה
        (למשל כשהיא מפוצלת בין תגיות, שם הפירסור מבוסס ה-DOM מנצח רגקס).

        Raises:
            YearMismatchError: אם נמצאה שנה והיא שונה מהמבוקשת.
        """
        if not self.year or not page_html:
            return

        # רגקס מקומי על 'שנה"ל תשפ"X' — בדיוק מה שה-GROUND_TRUTH מתאר.
        found = _course_year_label(page_html)

        if not found and _COURSE_YEAR_LABEL_RE.search(html_lib.unescape(page_html)):
            extractor = _load_extract_page_year()
            if extractor is not None:
                try:
                    found = _coerce_year_value(extractor(page_html))
                except Exception as exc:  # noqa: BLE001 - הפרסר לא אמור להפיל שליפה
                    self._log(
                        f"אזהרה: extract_page_year נכשל ({type(exc).__name__}: {exc}); "
                        "ממשיכים בלי אימות שנה."
                    )
                    found = ""

        verdict = _year_matches(found, self.year)
        if verdict is False:
            want_label = hebrew_year_label(self.year)
            raise YearMismatchError(
                f"קוד {code}: הדף שנשלף מצהיר על שנת לימודים {found}, "
                f"אבל ביקשנו {want_label or ''} ({self.year}). "
                "לא מפרסרים דף של שנה אחרת — זו בדיוק התקלה שהבדיקה הזאת נועדה למנוע. "
                f"(Year mismatch: page says {found!r}, expected {self.year!r}.)"
            )
        if verdict is True:
            self._log(f"קוד {code}: אומת — הדף הוא של שנת {found}.")
        else:
            self._log(f"קוד {code}: לא זוהתה שנה בדף (ממשיך; no year found on the page).")

    # ------------------------------------------------------- element helpers
    def _first_usable(self, selector: str, limit: int = 15):
        """
        מחזיר את ההתאמה הראשונה לסלקטור שהיא גם גלויה וגם ניתנת לעריכה/לחיצה.

        ASP.NET מפזר בדף שדות נסתרים (__VIEWSTATE וכו') — צריך לדלג עליהם.
        """
        page = self._require_page()
        try:
            loc = page.locator(selector)
            n = min(loc.count(), limit)
        except PlaywrightError:
            return None
        for i in range(n):
            cand = loc.nth(i)
            try:
                if cand.is_visible() and cand.is_enabled():
                    return cand
            except PlaywrightError:
                continue
        return None

    def _click_first_visible(self, selectors: list[str]) -> bool:
        """מנסה סלקטורים לפי הסדר ולוחץ על הראשון שנמצא וגלוי."""
        for sel in selectors:
            cand = self._first_usable(sel)
            if cand is None:
                continue
            try:
                cand.click(timeout=ACTION_TIMEOUT_MS)
                return True
            except PlaywrightError:
                continue
        return False

    def _wait_for_settle(self, timeout_ms: int = 12_000) -> None:
        """המתנה ל-networkidle, ואם אין — לפחות ל-domcontentloaded. לא זורק."""
        page = self._require_page()
        for state in ("networkidle", "domcontentloaded"):
            try:
                page.wait_for_load_state(state, timeout=timeout_ms)
                return
            except (PlaywrightTimeoutError, PlaywrightError):
                continue

    def _wait_for_change(self, before_hash: str, timeout_s: float = 12.0) -> bool:
        """
        מחכה עד ש-networkidle מגיע *או* שתוכן ה-DOM השתנה.

        למה שתי הבדיקות? כי WebForms לפעמים עושה postback מלא (ניווט), ולפעמים
        רק מעדכן חלק מהדף. טביעת אצבע של התוכן תופסת את שני המקרים.
        """
        page = self._require_page()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                page.wait_for_load_state("networkidle", timeout=1_500)
            except (PlaywrightTimeoutError, PlaywrightError):
                pass
            try:
                if _sha1(page.content()) != before_hash:
                    return True
            except PlaywrightError:
                # הדף באמצע ניווט — זה בעצמו סימן שמשהו קורה.
                pass
            time.sleep(0.4)
        return False

    # ------------------------------------------------- the course-code input
    #: שרשרת אסטרטגיות לאיתור שדה 'קוד קורס', לפי הסדר שב-SPEC סעיף 3.
    #: משמש **רק במסלול הגיבוי** — המסלול הראשי הוא GET ישיר ולא נוגע בטופס.
    #: כל אחת מודפסת ללוג כשהיא מצליחה — זה מה שיציל אותנו כשה-HTML ישתנה.
    CODE_INPUT_STRATEGIES: list[tuple[str, str]] = [
        # 1א. הכי מדויק: <label for="..."> שהטקסט שלו הוא "נא להקליד קוד קורס:".
        #     בגרסת הידיעון שנצפתה בפועל התווית אכן קשורה לשדה דרך for/id, וזו
        #     הדרך הכי עמידה לשינויים — שם השדה יכול להשתנות, הקשר לא.
        (
            "label-for",
            "xpath=//input[@id = //label[contains(text(),'" + LABEL_COURSE_CODE + "')]/@for]",
        ),
        # 1ב. השדה שאחרי הטקסט "קוד קורס".
        #    contains(text(), …) ולא normalize-space(.) — כדי לתפוס רק את
        #    התווית עצמה ולא כל <div> עוטף שמכיל אותה איפשהו בפנים.
        (
            "label-following",
            "xpath=//*[contains(text(),'" + LABEL_COURSE_CODE + "')]"
            "/following::input[not(@type) or @type='text'][1]",
        ),
        # 2. השדה שבתוך המכל הפנימי ביותר שמכיל את הטקסט "קוד קורס".
        (
            "label-container",
            "xpath=//*[self::td or self::div or self::fieldset or self::form]"
            "[contains(normalize-space(.),'" + LABEL_COURSE_CODE + "')]"
            "[not(.//*[contains(normalize-space(.),'" + LABEL_COURSE_CODE + "')])]"
            "//input[not(@type) or @type='text']",
        ),
        # 3. היוריסטיקות של שם/מזהה מה-SPEC.
        ("name-param", "input[name*='param']"),
        ("id-course", "input[id*='course']"),
        ("id-Course", "input[id*='Course']"),
        # 3ב. הרחבות ליוריסטיקה. השם SubjectCode אומת פעמיים על ידיעון אמיתי
        #     של אותה מערכת (fireflyweb) — ולכן 'subject' ו-'code' חשובים כאן
        #     לא פחות מהשמות שב-SPEC.
        ("attr-subject-code", "input[name*='subject' i], input[id*='subject' i]"),
        ("attr-code", "input[name*='code' i], input[id*='code' i]"),
        ("attr-course-any", "input[name*='course' i], input[id*='param' i]"),
        ("attr-kod", "input[name*='kod' i], input[id*='kod' i], input[name*='kurs' i], input[id*='kurs' i]"),
        # 4. מוצא אחרון: תיבת הטקסט הגלויה הראשונה בדף.
        ("first-visible-text", "input[type='text'], input:not([type])"),
    ]

    def _find_code_input(self):
        """
        מאתר את תיבת 'קוד קורס' לפי שרשרת האסטרטגיות.

        Returns:
            (locator, strategy_name) או (None, "") אם שום אסטרטגיה לא הצליחה.
        """
        for name, selector in self.CODE_INPUT_STRATEGIES:
            cand = self._first_usable(selector)
            if cand is not None:
                return cand, name
        return None, ""

    def _submit_search(self, inp, before_hash: str) -> str:
        """
        שולח את הטופס: קודם Enter, ואם לא קרה כלום — לוחץ על כפתור החיפוש.

        Returns:
            תיאור קצר של מה שעבד ("enter" / "button:…" / "no-change"), ללוג.
        """
        try:
            inp.press("Enter")
        except PlaywrightError as exc:
            self._log(f"אזהרה: Enter נכשל ({type(exc).__name__}). עובר לכפתור.")
        else:
            # המתנה קצרה בלבד: בגרסה שנצפתה בפועל יש סקריפט שחוסם Enter בתוך
            # הטופס, ולכן ברוב המקרים לא יקרה כאן כלום וזה תקין לחלוטין.
            if self._wait_for_change(before_hash, timeout_s=ENTER_PROBE_S):
                return "enter"

        # המסלול האמיתי: לחיצה על כפתור החיפוש. מחפשים כפתור *ליד* השדה
        # (באותו פאנל/תא/טופס), כדי לא ללחוץ בטעות על "מעבר שנה" או על
        # כפתור של פאנל חיפוש אחר.
        near = [
            # הניב של fireflyweb: <button class="go" data-progname="..." data-arguments="...">
            # שסקריפט חיצוני קושר אליו את שליחת הטופס. זה מה שנצפה בפועל.
            (
                "firefly-go",
                "xpath=ancestor::*[self::div or self::td or self::form][1]"
                "//button[@data-progname or contains(@class,'go')]",
            ),
            (
                "submit-near",
                "xpath=ancestor::*[self::form or self::td or self::fieldset or self::div][1]"
                "//input[@type='submit' or @type='button' or @type='image']",
            ),
            (
                "button-near",
                "xpath=ancestor::*[self::form or self::td or self::fieldset or self::div][1]//button",
            ),
            ("submit-following", "xpath=following::input[@type='submit' or @type='button' or @type='image'][1]"),
            ("button-following", "xpath=following::button[1]"),
        ]
        # תקציב זמן כולל — אחרת שרשרת הגיבויים הארוכה יכולה לתקוע קורס לדקות.
        deadline = time.monotonic() + SUBMIT_BUDGET_S

        def _budget_left() -> float:
            return deadline - time.monotonic()

        for label, rel in near:
            if _budget_left() <= 1.0:
                break
            try:
                cand = inp.locator(rel).first
                if cand.is_visible() and cand.is_enabled():
                    cand.click(timeout=ACTION_TIMEOUT_MS)
                    wait = max(2.0, min(SUBMIT_WAIT_S, _budget_left()))
                    if self._wait_for_change(before_hash, timeout_s=wait):
                        return label
            except PlaywrightError:
                continue

        # מוצא אחרון: כפתור בכל הדף שהכיתוב שלו נשמע כמו "חפש".
        # "קוד" ראשון בכוונה — הכפתור הנכון בפאנל הראשון נקרא "חיפוש קורס לפי קוד",
        # וכך לא נלחץ בטעות על כפתור החיפוש של פאנל אחר (מגמה / ימים ושעות).
        for word in ("קוד",) + SEARCH_WORDS_HE:
            if _budget_left() <= 1.0:
                break
            if self._click_first_visible(
                [
                    f"input[type='submit'][value*='{word}']",
                    f"input[type='button'][value*='{word}']",
                    f"button:has-text('{word}')",
                ]
            ):
                wait = max(2.0, min(SUBMIT_WAIT_S, _budget_left()))
                if self._wait_for_change(before_hash, timeout_s=wait):
                    return f"button-text:{word}"

        return "no-change"

    # -------------------------------------------------------------- fetching
    def fetch_course_html(self, code: str) -> str:
        """
        מביא את דף התוצאות של קוד קורס אחד ומחזיר את ה-HTML הגולמי.

        **מסלול ראשי (מאומת):** ניווט ישיר ל-``course_url(code)``. אין טופס,
        אין לחיצות, אין סלקטורים שיכולים להישבר. GROUND_TRUTH סעיף 1.

        **מסלול גיבוי (מודח):** מילוי טופס החיפוש — רק אם המסלול הראשי החזיר
        דף בלי אף קבוצה **וגם** בלי סימן ל"אין תוצאות". שימו לב: דף עם כותרת
        קורס ובלי קבוצות הוא תשובה לגיטימית ("הקורס לא נפתח השנה", סעיף 6)
        ולכן הוא **לא** מפעיל את הגיבוי.

        בכל מסלול: ה-HTML נשמר ל-raw_dir *לפני* שהוא מוחזר, ורק אם הדף באמת
        הגיע מ-info.braude.ac.il. אחרי השליפה נבדקת שנת הדף.

        Raises:
            ScraperSelectorError: הפניה חזרה להתחברות, כשל טעינה, או — במסלול
                הגיבוי — שליחה שלא בוצעה בכלל.
            YearMismatchError: אם הדף מצהיר על שנת לימודים אחרת מזו שביקשנו.
        """
        page = self._require_page()

        # ---------- מסלול ראשי: GET ישיר ----------
        url = course_url(code)
        self._log(f"קוד {code}: ניגש ישירות ל-{PRGNAME_COURSE_SEARCH} (GET).")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        except PlaywrightError as exc:
            raise ScraperSelectorError(
                f"קוד {code}: לא הצלחתי לטעון את דף הקורס. "
                f"(Could not load the course page: {exc})"
            ) from exc

        if not is_success_url(page.url):
            # הופנינו חזרה לשער ההתחברות — הסשן פג באמצע הריצה.
            # **כאן לא שומרים דמפ ולא צילום מסך.** הדף שלפנינו הוא, בהגדרה,
            # טופס ההתחברות ולא הידיעון: אין בו שום דבר שהפרסר צריך, ובפרופיל
            # הקבוע הדפדפן כבר מילא בו את שם המשתמש. שמירה שלו ל-data/raw/
            # (התיקייה שנשלחת לתמיכה) הייתה מפרה את כלל ברזל מס' 1.
            # מדווחים את שם המארח בלבד, בלי ה-URL המלא ובלי טוקנים שבתוכו.
            raise ScraperSelectorError(
                f"קוד {code}: הופנינו חזרה להתחברות ({_host_of(page.url)}). ייתכן שהסשן "
                "פג — יש להריץ שוב ולהתחבר מחדש. (Redirected back to login; no dump saved, "
                "the login page is never written to disk.)"
            )

        self._wait_for_settle()
        html = self._page_html()

        # חוק ברזל: שומרים לדיסק *לפני* שמישהו מפרסר או מחזיר.
        direct_dump = self.dump_page(code)

        groups = _count_group_blocks(html)
        if groups > 0 or _has_no_results_marker(html):
            if groups:
                self._log(f"קוד {code}: המסלול הישיר הצליח ({groups} בלוקי קבוצה). {self._dump_note(direct_dump)}")
            else:
                self._log(
                    f"קוד {code}: הדף נטען אבל אין בו אף קבוצה — כנראה הקורס לא נפתח "
                    f"בשנה/סמסטר האלה. (no groups; the course may not be offered) "
                    f"{self._dump_note(direct_dump)}"
                )
            self.strategy_log.append((code, "direct-get"))
            self._assert_page_year(code, html)
            return html

        # ---------- מסלול גיבוי: מילוי הטופס ----------
        self._log(
            f"קוד {code}: המסלול הישיר החזיר דף שלא נראה כמו דף תוצאות — "
            "נופל למילוי טופס החיפוש (fallback)."
        )
        html = self._fetch_via_search_form(code)
        self._assert_page_year(code, html)
        return html

    def _fetch_via_search_form(self, code: str) -> str:
        """
        מסלול הגיבוי הישן: ממלא את טופס החיפוש ולוחץ על כפתור.

        שמור כאן בכוונה, אבל **מודח**: הוא תלוי בסלקטורים של WebForms שנוצרים
        אוטומטית ומשתנים בין גרסאות. הוא ירוץ רק אם ה-GET הישיר לא החזיר
        משהו שנראה כמו דף תוצאות.

        Raises:
            ScraperSelectorError: אם לא נמצאה תיבת הקוד, אם לא הצלחנו להקליד
                לתוכה, אם **השליחה לא בוצעה בכלל** (הדף לא השתנה), או אם הדף
                אמנם השתנה אבל מה שחזר אינו דף תוצאות (מודאל שגיאה וכדומה).
        """
        page = self._require_page()

        # --- 1. דף החיפוש ---
        if not self._goto_search_page():
            raise ScraperSelectorError(
                f"קוד {code}: לא הצלחתי לטעון את דף החיפוש (או שהופנינו חזרה להתחברות). "
                "(Could not load the search page; no dump saved.)"
            )

        # ניווט חדש עלול להחזיר אותנו לברירת המחדל של האתר — מוודאים את השנה
        # שוב, וברעש. שנה שגויה במסלול הגיבוי מסוכנת בדיוק כמו במסלול הראשי.
        if self.year:
            header = _header_year_label(self._page_html())
            want = hebrew_year_label(self.year)
            if header and want and _normalize_hebrew_year(header) != _normalize_hebrew_year(want):
                self._log(f"קוד {code}: דף החיפוש חזר לשנת {header} — מחליף שוב ל-{want}.")
                self.set_year(self.year)     # יזרוק YearSwitchError אם לא יצליח

        # --- 2. דמפ לפני כל ניסיון פרסור (חוק ברזל) ---
        search_dump = self.dump_page(code)

        # --- 3. איתור התיבה ---
        inp, strategy = self._find_code_input()
        if inp is None:
            self.dump_page(code, screenshot=True)
            raise ScraperSelectorError(
                f"קוד {code}: לא מצאתי את תיבת '{LABEL_COURSE_CODE}' בדף. "
                f"המבנה של הידיעון כנראה השתנה — יש לפתוח את קובץ ה-HTML השמור "
                f"ולעדכן את CODE_INPUT_STRATEGIES.\n"
                f"(Could not locate the course-code input.) {self._dump_note(search_dump)}"
            )
        self._log(f"קוד {code}: תיבת הקוד אותרה באסטרטגיה '{strategy}'.")
        self.strategy_log.append((code, f"form:{strategy}"))

        # --- 4. מילוי ושליחה ---
        try:
            inp.click(timeout=ACTION_TIMEOUT_MS)
            inp.fill("")
            inp.fill(code)
        except PlaywrightError as exc:
            self.dump_page(code, screenshot=True)
            raise ScraperSelectorError(
                f"קוד {code}: לא הצלחתי להקליד לתוך תיבת הקוד ({exc}). "
                f"{self._dump_note(search_dump)}"
            ) from exc

        # טביעת האצבע של הדף *לפני* השליחה, כדי שנוכל לדעת אם הוא באמת זז.
        # שדה WebForms עם AutoPostBack (או onchange שמפעיל form.submit) יכול
        # להתחיל ניווט כבר ברגע ההקלדה, ואז page.content() זורק
        # "Execution context was destroyed". מחכים שהדף יתייצב ומנסים שוב.
        # אסור ליפול חזרה ל-"" — כל דף לא-ריק היה נראה אז כאילו "השתנה",
        # והשליחה הייתה נחשבת מוצלחת בטעות.
        try:
            before = _sha1(page.content())
        except PlaywrightError:
            self._wait_for_settle()
            try:
                before = _sha1(page.content())
            except PlaywrightError as exc:
                crash_dump = self.dump_page(code, screenshot=True)
                raise ScraperSelectorError(
                    f"קוד {code}: לא הצלחתי לקרוא את הדף לפני השליחה "
                    f"({type(exc).__name__}: {exc}) — כנראה הדף ניווט באמצע ההקלדה. "
                    f"(Could not snapshot the search page before submitting.) "
                    f"{self._dump_note(crash_dump)}"
                ) from exc

        how = self._submit_search(inp, before)

        # --- 5. דמפ של דף התוצאות (תמיד, גם כשנכשלנו) ---
        self._wait_for_settle()
        result_dump = self.dump_page(code, screenshot=(how == "no-change"))

        if how == "no-change":
            # הדף לא זז בכלל. ב-WebForms כל postback אמיתי משנה את __VIEWSTATE,
            # ולכן "הדף לא השתנה" לעולם לא אומר "אין תוצאות" — הוא אומר שלא
            # נלחץ כלום. אם נחזיר כאן את ה-HTML נחזיר את *טופס החיפוש* עצמו,
            # הקורס ייחשב "הצליח", הפרסר לא ימצא קבוצות, sections.json ייכתב
            # ריק והמערכת תצא ריקה בלי שום הודעת שגיאה. לכן: כישלון.
            raise ScraperSelectorError(
                f"קוד {code}: השליחה לא בוצעה — לא נמצא כפתור חיפוש שעובד (או שנגמר "
                f"תקציב הזמן של {SUBMIT_BUDGET_S:.0f} שניות). מה שנשמר הוא טופס החיפוש "
                f"ולא דף תוצאות. יש לפתוח את הדמפ ולעדכן את שרשרת הכפתורים ב-_submit_search.\n"
                f"(The search was never submitted — no working submit control.) "
                f"{self._dump_note(result_dump)}"
            )

        self._log(f"קוד {code}: השליחה בוצעה ({how}). {self._dump_note(result_dump)}")

        try:
            html = page.content()
        except PlaywrightError as exc:
            raise ScraperSelectorError(
                f"קוד {code}: לא הצלחתי לקרוא את תוכן דף התוצאות ({exc}). "
                f"{self._dump_note(result_dump)}"
            ) from exc

        # --- 6. בדיקת צורה: האם זה בכלל דף תוצאות? ---
        # "ה-DOM זז" הוא **לא** הוכחה שהחיפוש רץ. הידיעון מקפיץ מודאל שגיאה
        # (showAlertModal) במקום לשלוח את הטופס, ו-AJAX שממלא את שם הקורס ליד
        # התיבה משנה את הדף גם הוא — כל אלה היו נספרים כ"נשלח". ההוכחה היחידה
        # היא שהדף *נראה* כמו דף תוצאות, בדיוק אותה בדיקה שהמסלול הישיר מפעיל.
        # בלי זה היינו מחזירים כאן את טופס החיפוש עצמו, הקורס היה נחשב "נשלף",
        # והסטודנטית הייתה מקבלת "הקורס לא נפתח" על קורס שכן נפתח.
        if not (
            _count_group_blocks(html) > 0
            or _looks_like_course_page(html)
            or _has_no_results_marker(html)
        ):
            raise ScraperSelectorError(
                f"קוד {code}: הדף השתנה אחרי השליחה ({how}) אבל מה שחזר אינו דף תוצאות — "
                f"אין בו אף בלוק קבוצה, אין כותרת קורס עם שנה\"ל, ואין הודעת 'לא נמצא'. "
                f"כנראה נפתחה הודעת שגיאה במקום שהחיפוש יישלח. יש לפתוח את הדמפ ולבדוק.\n"
                f"(The page changed but it is not a results page — nothing was submitted.) "
                f"{self._dump_note(result_dump)}"
            )

        return html

    def scrape(self, codes: list[str]) -> dict[str, str]:
        """
        מביא את דפי התוצאות של כל הקודים, אחד אחרי השני.

        לפני הקורס הראשון — ורק פעם אחת — מוחלפת שנת הלימודים של הסשן.
        אם ההחלפה לא מאושרת, **לא נשלף אף קורס**: מוטב לחזור בלי נתונים מאשר
        עם המערכת של שנה אחרת.

        סדרתי בכוונה, עם השהיה של 1.5 שניות בין קורס לקורס — לא מציפים את
        השרת של המכללה. קורס שנכשל לא עוצר את השאר: התקלה נרשמת ב-``errors``
        והריצה ממשיכה.

        Returns:
            מילון {קוד קורס: HTML}. קודים שנכשלו פשוט לא יופיעו בו.
        """
        if not self._logged_in:
            # נוחות: אם לא קראו ל-open_and_wait_for_login מראש, עושים זאת כאן.
            # כשהסשן כבר קיים זה מסתיים תוך שנייה ובלי להטריד אף אחד.
            self._log("עוד לא אושרה התחברות — פותח את תהליך ההתחברות.")
            if not self.open_and_wait_for_login():
                for code in codes:
                    self.errors.append((code, "לא בוצעה התחברות (login was not completed)"))
                return {}

        # ---------- החלפת שנה, פעם אחת, לפני הכול ----------
        if self.year and not self._year_applied:
            try:
                label = self.set_year(self.year)
                self._log(f"שנת הלימודים לסריקה: {label} ({self.year}).")
            except (YearSwitchError, PlaywrightError, RuntimeError) as exc:
                print(
                    _banner(
                        [
                            "עצירה: לא הצלחתי לוודא את שנת הלימודים בידיעון",
                            "STOPPED: could not verify the academic year",
                            "",
                            f"ביקשנו {hebrew_year_label(self.year)} ({self.year}).",
                            "בלי אישור השנה לא נשלף אף קורס — אחרת הייתה מתקבלת",
                            "המערכת של שנה אחרת, בלי שום סימן לכך.",
                            "",
                            "No course was fetched; a wrong-year timetable is worse",
                            "than no timetable at all.",
                        ],
                        ch="!",
                    ),
                    flush=True,
                )
                for code in codes:
                    self.errors.append((code, f"{type(exc).__name__}: {exc}"))
                return {}

        results: dict[str, str] = {}
        total = len(codes)
        for i, code in enumerate(codes, start=1):
            if i > 1:
                time.sleep(POLITE_DELAY_S)  # נימוס כלפי השרת
            self._log(f"({i}/{total}) מביא קורס {code}…")
            try:
                results[code] = self.fetch_course_html(code)
            except ScraperError as exc:
                # כולל ScraperSelectorError / YearMismatchError / YearSwitchError
                self.errors.append((code, str(exc)))
                self._log(f"שגיאה בקורס {code}: {exc}")
            except PlaywrightError as exc:
                self.errors.append((code, f"{type(exc).__name__}: {exc}"))
                self._log(f"שגיאת דפדפן בקורס {code}: {exc}")
            except Exception as exc:  # noqa: BLE001 - קורס אחד לא מפיל את הכול
                self.errors.append((code, f"{type(exc).__name__}: {exc}"))
                self._log(f"שגיאה לא צפויה בקורס {code}: {exc}")

        self._log(f"סיום: {len(results)}/{total} קורסים נשלפו, {len(self.errors)} תקלות.")
        return results


# --------------------------------------------------------------------------
# הרצה עצמאית — בדיקת עשן להתחברות, למעבר שנה ולשמירת דמפים
#   python src/scraper.py                 (ברירת מחדל: 2027 = תשפ"ז)
#   python src/scraper.py 61753 61756
#   python src/scraper.py --year 2026 11069 61832
#   python src/scraper.py --year none 61753      (בלי לגעת בשנה — לא מומלץ)
# --------------------------------------------------------------------------
#: ברירת המחדל: ששת הקורסים של הסמסטר הנוכחי (מתוך data/profile.json).
DEFAULT_CODES = ["11069", "61753", "61756", "61757", "61832", "62027"]

#: ברירת מחדל לשנה: 2027 = תשפ"ז — השנה שהמערכת הזאת נבנית עבורה.
#: הידיעון עצמו נפתח על תשפ"ו, ולכן ברירת מחדל שקטה הייתה מסוכנת.
DEFAULT_YEAR = "2027"


def _parse_args(argv: list[str]) -> tuple[list[str], str | None]:
    """
    מפרק ארגומנטים: קודי קורסים חופשיים + ``--year YYYY`` אופציונלי.

    ``--year none`` (או ``--year ""``) = אל תיגע בשנה בכלל. קיים כדי שאפשר
    יהיה לבדוק מה הידיעון מחזיר בברירת המחדל שלו, אבל זה לא מה שרוצים בריצה
    אמיתית.
    """
    codes: list[str] = []
    year: str | None = DEFAULT_YEAR
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
        codes.append(arg)
        i += 1

    if year is not None and year.strip().lower() in ("", "none", "off", "-"):
        year = None
    return (codes or DEFAULT_CODES), year


def main(argv: list[str] | None = None) -> int:
    """בדיקת עשן: פותח דפדפן, מחכה להתחברות ידנית, ושומר דמפים ל-data/raw/."""
    enable_utf8_stdout()
    args = list(argv if argv is not None else sys.argv[1:])

    if any(a in ("-h", "--help") for a in args):
        print(__doc__.strip().splitlines()[0])
        print()
        print("שימוש (usage): python src/scraper.py [--year YYYY] [קוד קורס ...]")
        print(f"  --year YYYY   שנת לימודים לועזית. ברירת מחדל: {DEFAULT_YEAR} "
              f"(= {hebrew_year_label(DEFAULT_YEAR)}).")
        print("  --year none   אל תיגע בשנה כלל (לא מומלץ — האתר יפתח בשנה שלו).")
        print(f"  ברירת מחדל לקודים: {', '.join(DEFAULT_CODES)}")
        return 0

    codes, year = _parse_args(args)

    print("בדיקת עשן לגורד הידיעון — Braude yedion scraper smoke test")
    year_note = f"{year} ({hebrew_year_label(year)})" if year else "ברירת המחדל של האתר (!)"
    print(f"קורסים: {', '.join(codes)} | שנה: {year_note}")
    print()

    with BraudeScraper(year=year) as scraper:
        if not scraper.open_and_wait_for_login():
            print("ההתחברות לא הושלמה. (Login was not completed.) — יוצא.")
            return 1

        pages = scraper.scrape(codes)

        print()
        print("=== סיכום (summary) ===")
        if scraper.year_label:
            print(f"שנת הלימודים שאושרה בדף: {scraper.year_label}")
        for code in codes:
            html = pages.get(code)
            if html is None:
                print(f"  {code}: נכשל (failed)")
            else:
                groups = _count_group_blocks(html)
                print(f"  {code}: הצליח, {len(html):,} תווים, ~{groups} קבוצות (chars, groups)")
        if scraper.strategy_log:
            print("אסטרטגיות שעבדו (strategies that matched):")
            for code, strategy in scraper.strategy_log:
                print(f"  {code}: {strategy}")
        if scraper.errors:
            print("תקלות (errors):")
            for code, message in scraper.errors:
                print(f"  {code}: {message}")
        print(f"קבצי HTML גולמיים נשמרו תחת: {scraper.raw_dir}")

        return 0 if pages else 2


if __name__ == "__main__":
    raise SystemExit(main())
