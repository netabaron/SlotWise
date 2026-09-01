# -*- coding: utf-8 -*-
"""
בדיקות רב-מחלקתיות — the tool must work for a student from *any* faculty.

הרקע (SPEC_MULTIFACULTY.md), במספרים שנמדדו ולא נוחשו:
    ‏493 מתוך 571 קורסי הקטלוג (86%) אינם מופיעים ב-``data/curriculum.json``.
    לכן הם מדווחים ‏``credits: 0.0``, לא מקבלים בדיקת קדם ולא נאכפת עליהם צמידות,
    ורשימת הקורסים בשלב 2 — שנבנית מהתוכנית — יוצאת **ריקה** לסטודנט/ית מחוץ
    להנדסת תוכנה.

התיקון: ``S_CourseDetails`` בידיעון קריא לכולם בלי התחברות, ומחזיק נ"ז, פילוח
שעות (he/te/ma/pr), שעות סמסטריאליות, שפת הוראה, תיאור ותנאי קדם. התוכנית
הופכת מדרישה ל**העשרה אופציונלית**.

הקובץ הזה בודק את שלוש השכבות של התיקון:
    1. ``parser.parse_course_details``   — פענוח דף הפרטים
    2. ``store.Store.save/load_details`` + חלון התיישנות של **7 ימים**
    3. שכבת ה-HTTP — ‏``/api/catalog/browse``, ‏``/api/semester/<n>/courses``
       בלי תוכנית לימודים, ו-``/api/solve`` על ארבעה קורסים שאינם בתוכנית.
    4. ‏``refresh.py --all`` — הריצה היומית שמחזיקה את הפרטים האלה מעודכנים
       (‏§6 במפרט). בלי המעבר הזה חלון שבעת הימים הוא קוד שאיש אינו מריץ.

שני כללי ברזל של הקובץ הזה
--------------------------
**‏(א) אין רשת. בכלל.** שני דפים אמיתיים שמורים ב-
``tests/fixtures/real_yedion/course_details_*.html`` ומוזרקים כתשובות מוכנות.
‏fixture אוטומטי חוסם את ``YedionHTTP`` ואת ``urlopen``, בדיוק כמו ב-
``tests/test_web.py``.

**‏(ב) אף פעם לא לקבע את גודל המסד.** רענון קטלוג מלא רץ ברקע והמאגר גדל
כל הזמן. כל טענה כאן היא על **תת-קבוצה** או על קוד ספציפי — אף פעם לא על מספר.

הכלל שהכי חשוב לא להפר: **‏0.0 לעולם אינו "לא ידוע"**. סך נ"ז ששותק על 86%
מהקורסים גרוע מסך שמודה שאינו יודע. ‏``credits`` של קורס שאין עליו מידע חייב
להיות ``None`` — ו-``credits_source`` חייב לומר מאיפה המספר הגיע כשהוא כן קיים.

איך מריצים:
    python -m pytest tests/test_multifaculty.py -q

הערה על שערים (gates): שכבות התיקון נכתבות במקביל על ידי סוכנים אחרים. כל אזור
בקובץ נשמר מאחורי בדיקת נוכחות אחת (``parse_course_details`` קיימת? ‏
``Store.save_details`` קיימת? המסלול ``/api/catalog/browse`` רשום?). כל עוד
השכבה לא נחתה — האזור מדולג בקול רם ובנימוק מפורש. ברגע שהיא נוחתת — הבדיקות
נאכפות בקפדנות, בלי הנחות.
"""

from __future__ import annotations

import inspect
import json
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# --------------------------------------------------------------------------
# הכנת הסביבה: src/ ושורש הפרויקט נכנסים ל-sys.path, בדיוק כמו ש-main.py עושה.
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for _path in (str(SRC), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass  # זרם שאי אפשר להגדיר מחדש (pytest capture / pipe) — ממשיכים

import parser as parser_mod  # noqa: E402  (ייבוא אחרי ניתוח ה-sys.path — בכוונה)
import store as store_mod  # noqa: E402
import yedion_http as yedion_mod  # noqa: E402
from models import Group, Selection  # noqa: E402

#: המתודה האמיתית, נשמרת **לפני** שה-fixture האוטומטי חוסם אותה. בדיקה אחת
#: (השליפה דרך fetcher מוזרק) צריכה אותה בחזרה, ורק אותה.
_REAL_FETCH_DETAILS = getattr(yedion_mod.YedionHTTP, "fetch_details", None)

DB_ROOT = ROOT / "data" / "db"
CURRICULUM_PATH = ROOT / "data" / "curriculum.json"
PROFILE_PATH = ROOT / "data" / "profile.json"
FIXTURES = ROOT / "tests" / "fixtures" / "real_yedion"

DETAILS_61753 = FIXTURES / "course_details_61753.html"
DETAILS_11001 = FIXTURES / "course_details_11001.html"
SEARCH_PAGE = FIXTURES / "enter_search_page.html"
SINGLE_GROUP = FIXTURES / "single_group.html"

# --------------------------------------------------------------------------
# עובדות שנקראו מהדפים השמורים עצמם. אלה **לא** מספרים שהומצאו.
# --------------------------------------------------------------------------
SE_CODE = "61753"  # אלגוריתמים — קורס הנדסת תוכנה, נמצא גם ב-curriculum.json
SE_NAME = "אלגוריתמים"
SE_CREDITS = 5.0
SE_HOURS = {"he": 4.0, "te": 2.0, "ma": 0.0, "pr": 0.0}
SE_WEEKLY = 4.0
SE_LANGUAGE = "עברית"
SE_PREREQ_NAME = 'חדו"א 2מ'
SE_DESC_MARKER = "מטרת הקורס היא הכרת פרדיגמות"

NON_SE_CODE = "11001"  # אלגברה — לא קיים ב-curriculum.json כלל
NON_SE_NAME = "אלגברה"
NON_SE_CREDITS = 4.0  # מגיע משורת "פרשיית לימוד" בלבד; שורת נקודות הזכות ריקה
NON_SE_HOURS = {"he": 3.0, "te": 2.0, "ma": 0.0, "pr": 0.0}
NON_SE_DESC_MARKER = "מספרים מרוכבים"

#: ארבעת הקורסים שהאודיט פתר עליהם — כולם מחוץ להנדסת תוכנה, אף אחד מהם
#: לא נמצא ב-curriculum.json. זו ההוכחה שהליבה אינה תלויה בתוכנית.
NON_SE_CODES = ["11001", "11002", "11003", "11005"]
NO_DETAILS_CODE = "11002"  # אלגברה מ' — לא בתוכנית, ולא נשמור לו פרטים

#: המצב **השני** של "לא ידוע", וזה שקורה בפועל: רשומת פרטים קיימת ו-``credits``
#: שבה הוא ``null``. כל הרשומות שב-``data/db/details.json`` החי נמצאות בדיוק
#: במצב הזה. "אין רשומה בכלל" עוצר לפני הנפילה-לאחור לידיעון; "רשומה בלי נ\"ז"
#: עובר **דרכה** — ולכן דווקא הוא זה שיחזור כ-0.0 אם מישהו יכתוב ``or 0.0``.
NULL_CREDITS_CODE = "11003"  # חדו"א 1 — לא בתוכנית; יש רשומה, אין בה נ"ז

#: קורס שאינו בתוכנית ותנאי הקדם שלו מגיעים מהידיעון בלבד (חדו"א 2 → חדו"א 1).
YEDION_PREREQ_CODE = "11005"

#: קוד שאינו קיים באמת, ונשתל בכוונה בפרטים של קורס שכן נמצא בתוכנית. אם הוא
#: צץ בתשובה — סדר ההכרעה של תנאי הקדם התהפך.
WRONG_PREREQ_CODE = "99999"

CURRICULUM_ZERO_CODE = "11063"  # אנגלית בסיסי — 0.0 נ"ז **באמת**, לפי התוכנית
CURRICULUM_SEMESTER = "5"
TERM = "א"
YEAR = 'תשפ"ז'

HOURS_KEYS = ("he", "te", "ma", "pr")

DAY = 24.0
WEEK_HOURS = 7 * DAY  # 168 — חלון ההתיישנות של הפרטים

#: מקורות נ"ז מוכרים. הערך המדויק נתון לסוכן שכותב את השכבה; המשמעות אינה.
_CURRICULUM_SOURCE_WORDS = ("curriculum", "תוכנית", "rec.pdf", "rec")
_YEDION_SOURCE_WORDS = ("yedion", "details", "ידיעון", "פרטי")
_UNKNOWN_SOURCE_VALUES = {"", "none", "null", "unknown", "-", "—", "לא ידוע", "אין"}


def _hebrew(text: object) -> bool:
    """האם יש בטקסט אות עברית אחת לפחות."""
    return any("֐" <= ch <= "׿" for ch in str(text or ""))


def _read(path: Path) -> str:
    """כל קריאת קובץ ב-utf-8 — ב-Windows ברירת המחדל היא cp1255."""
    return path.read_text(encoding="utf-8")


# ==========================================================================
# 0. רשת ביטחון — אף בדיקה בקובץ הזה לא פונה לרשת, אף פעם.
#    מראה את ה-fixture המקביל ב-tests/test_web.py, ומרחיב אותו ל-urlopen
#    ולנקודות הפרטים החדשות.
# ==========================================================================
@pytest.fixture(autouse=True)
def _never_touch_the_network(monkeypatch):
    def _refuse(*_args, **_kwargs):  # pragma: no cover - נקרא רק אם משהו השתבש
        raise RuntimeError(
            "no network in tests — הבדיקות האלה עובדות רק מול הדפים השמורים"
        )

    for name in (
        "open_session",
        "fetch_course",
        "fetch_catalog",
        "fetch_details",
        "scrape",
    ):
        monkeypatch.setattr(yedion_mod.YedionHTTP, name, _refuse, raising=False)

    # שכבה שנייה: גם אם מישהו יעקוף את המחלקה, urllib עצמו חסום.
    monkeypatch.setattr(urllib.request, "urlopen", _refuse, raising=False)
    monkeypatch.setattr(
        urllib.request.OpenerDirector, "open", _refuse, raising=False
    )
    yield


@pytest.fixture(autouse=True)
def _never_open_a_browser(monkeypatch):
    """שום חלון דפדפן לא נפתח — לא Playwright ולא webbrowser."""

    def _refuse(*_args, **_kwargs):  # pragma: no cover
        raise RuntimeError("no browser in tests")

    try:
        import playwright.sync_api as pw_api

        monkeypatch.setattr(pw_api, "sync_playwright", _refuse, raising=False)
    except Exception:  # pragma: no cover - playwright לא מותקן, וזה בסדר גמור
        pass
    try:
        import scraper as scraper_mod

        monkeypatch.setattr(scraper_mod, "sync_playwright", _refuse, raising=False)
    except Exception:  # pragma: no cover
        pass
    try:
        import webbrowser

        monkeypatch.setattr(webbrowser, "open", lambda *a, **k: False)
        monkeypatch.setattr(webbrowser, "open_new", lambda *a, **k: False, raising=False)
    except Exception:  # pragma: no cover
        pass
    yield


# ==========================================================================
# 1. הזרקת "ידיעון" מזויף — הדפים השמורים כתשובות מוכנות
# ==========================================================================
class CannedResponse:
    """תשובת HTTP מזויפת. מספיק ממשק כדי להיראות כמו ``HTTPResponse``."""

    def __init__(self, html: str, url: str, status: int = 200) -> None:
        self._body = html.encode("utf-8")
        self._pos = 0
        self.url = url
        self.status = status
        self.code = status

    def read(self, amt: int | None = None) -> bytes:
        chunk = self._body[self._pos:] if amt is None else self._body[self._pos:self._pos + amt]
        self._pos += len(chunk)
        return chunk

    def geturl(self) -> str:
        return self.url

    def getcode(self) -> int:
        return self.status

    def getheader(self, _name: str, default=None):
        return "text/html; charset=utf-8" if _name.lower() == "content-type" else default

    def info(self):
        return {"Content-Type": "text/html; charset=utf-8"}

    def close(self) -> None:
        pass

    def __enter__(self) -> "CannedResponse":
        return self

    def __exit__(self, *_exc) -> bool:
        return False


class FakeFetcher:
    """‏opener מוזרק: מחזיר את הדפים השמורים ומקליט כל כתובת שנתבקשה.

    זהו ממשק ההזרקה המתועד של ``YedionHTTP`` (``opener=`` / ``transport=``),
    ולכן הבדיקה עוברת דרך *כל* קוד הבניית הכתובת האמיתי — ורק הרשת מוחלפת.
    """

    def __init__(self, pages: dict[str, str], default: str = "") -> None:
        self.pages = dict(pages)
        self.default = default
        self.urls: list[str] = []

    def open(self, request, timeout=None, **_kwargs) -> CannedResponse:
        url = request.full_url if hasattr(request, "full_url") else str(request)
        self.urls.append(url)
        for needle, html in self.pages.items():
            if needle in url:
                return CannedResponse(html, url)
        return CannedResponse(self.default, url)


@pytest.fixture(scope="module")
def html_61753() -> str:
    return _read(DETAILS_61753)


@pytest.fixture(scope="module")
def html_11001() -> str:
    return _read(DETAILS_11001)


@pytest.fixture(scope="module")
def html_no_credits() -> str:
    """הדף האמיתי של 61753 אחרי שהוסרו ממנו **שני** מקורות הנ"ז.

    נגזר מהדף האמיתי ולא מומצא מאפס — כך שכל שאר המבנה נשאר בדיוק כפי
    שהידיעון מגיש אותו, והבדיקה בודקת שדה חסר ולא דף מדומה.
    """
    html = _read(DETAILS_61753)
    stripped = html.replace("נקודות זכות : 5.00", "נקודות זכות :")
    stripped = stripped.replace('<br>4 2 - -  5.0 נ"ז <br>', "<br>")
    assert stripped != html, "התבנית לא השתנתה — הדף השמור זז ויש לעדכן את הבדיקה"
    assert "5.00" not in stripped, "נשאר מקור נקודות זכות בדף שאמור להיות בלעדיו"
    assert '5.0 נ"ז' not in stripped, "נשארה שורת שעות עם נ\"ז בדף שאמור להיות בלעדיה"
    return stripped


# ==========================================================================
# 2. השערים — כל אזור נבדק רק כשהשכבה שלו נחתה
# ==========================================================================
_PARSER_READY = hasattr(parser_mod, "parse_course_details")
_STORE_READY = all(
    hasattr(store_mod.Store, name)
    for name in ("save_details", "load_details", "details_stale")
)
_HTTP_READY = hasattr(yedion_mod, "details_url")

_API_ERROR = ""
_API_READY = False
_CREATE_APP = None
try:  # pragma: no cover - תלוי בסדר הנחיתה של הסוכנים
    import flask  # noqa: F401  (Flask נדרש לשכבת האינטרנט)

    from web.api import create_app as _CREATE_APP  # type: ignore

    _probe = _CREATE_APP(
        config={
            "db_root": str(DB_ROOT),
            "curriculum_path": str(CURRICULUM_PATH),
            "allow_network": False,
        },
        serve_ui=False,
    )
    _API_READY = any(
        str(rule.rule) == "/api/catalog/browse" for rule in _probe.url_map.iter_rules()
    )
    if not _API_READY:
        _API_ERROR = "המסלול /api/catalog/browse עדיין אינו רשום"
    del _probe
except Exception as exc:  # noqa: BLE001 - הסיבה נכנסת לנימוק הדילוג
    _API_ERROR = f"{type(exc).__name__}: {exc}"

needs_parser = pytest.mark.skipif(
    not _PARSER_READY,
    reason="parser.parse_course_details עדיין לא נכתבה — האזור הזה ירוץ ברגע שהיא תיחת",
)
needs_store = pytest.mark.skipif(
    not _STORE_READY,
    reason="Store.save_details/load_details/details_stale עדיין לא נכתבו",
)
needs_http = pytest.mark.skipif(
    not _HTTP_READY,
    reason="yedion_http.details_url עדיין לא נכתבה",
)
needs_api = pytest.mark.skipif(
    not _API_READY,
    reason=f"שכבת ה-API הרב-מחלקתית עדיין לא נחתה ({_API_ERROR})",
)

_REFRESH_ERROR = ""
_REFRESH_DETAILS_READY = False
try:  # pragma: no cover - תלוי בסדר הנחיתה של הסוכנים
    import refresh as refresh_mod  # type: ignore  # noqa: E402
except Exception as exc:  # noqa: BLE001 - הסיבה נכנסת לנימוק הדילוג
    refresh_mod = None  # type: ignore[assignment]
    _REFRESH_ERROR = f"refresh.py אינו ניתן לייבוא ({type(exc).__name__}: {exc})"
else:
    # השכבה מזוהה לפי מה שהיא **חייבת** לקרוא לו כדי להתקיים, ולא לפי שם
    # פונקציה שנבחר: בלי אף אחד משלושת אלה, ‏refresh.py אינו נוגע בפרטים כלל.
    _REFRESH_DETAILS_READY = any(
        marker in _read(ROOT / "refresh.py")
        for marker in ("details_stale", "save_details", "fetch_details")
    )
    if not _REFRESH_DETAILS_READY:
        _REFRESH_ERROR = (
            "refresh.py עדיין אינו מרענן פרטים — אין בו אף קריאה ל-details_stale / "
            "save_details / fetch_details, כלומר §6 במפרט טרם מומש"
        )

needs_refresh_details = pytest.mark.skipif(
    not _REFRESH_DETAILS_READY,
    reason=f"מעבר הפרטים של הריצה היומית עדיין לא נחת ({_REFRESH_ERROR})",
)


def _details(html: str, code: str):
    """קיצור: ``parse_course_details(html, code)``."""
    return parser_mod.parse_course_details(html, code)


def _hours_of(details) -> dict[str, float]:
    hours = details.hours
    assert isinstance(hours, dict), f"hours חייב להיות dict, קיבלתי {type(hours).__name__}"
    return hours


# ==========================================================================
# 3. ‏parse_course_details — הדף האמיתי של 61753 (קורס הנדסת תוכנה)
# ==========================================================================
@needs_parser
def test_course_details_exposes_every_field_the_spec_promises(html_61753):
    """‏CourseDetails הוא החוזה; שדה חסר בו הוא שקט שאסור לו לקרות."""
    details = _details(html_61753, SE_CODE)
    for field in (
        "code",
        "name",
        "credits",
        "hours",
        "weekly_hours",
        "language",
        "description",
        "prerequisites",
        "warnings",
    ):
        assert hasattr(details, field), f"שדה {field} חסר ב-CourseDetails: {details!r}"


@needs_parser
def test_61753_credits_are_five(html_61753):
    """‏'נקודות זכות : 5.00' — והתשובה היא 5.0, לא 5, לא '5.00', ולא 0.0."""
    details = _details(html_61753, SE_CODE)
    assert details.credits == SE_CREDITS, f"ציפיתי ל-5.0 נ\"ז, קיבלתי {details.credits!r}"
    assert isinstance(details.credits, float)


@needs_parser
def test_61753_hours_are_four_lecture_two_tutorial(html_61753):
    """שורת 'פרשיית לימוד': ‏``4 2 - -  5.0 נ"ז`` → he=4, te=2."""
    hours = _hours_of(_details(html_61753, SE_CODE))
    assert float(hours["he"]) == 4.0, f"he שגוי: {hours}"
    assert float(hours["te"]) == 2.0, f"te שגוי: {hours}"


@needs_parser
def test_61753_hours_have_all_four_components(html_61753):
    hours = _hours_of(_details(html_61753, SE_CODE))
    assert set(HOURS_KEYS) <= set(hours), f"חסרים רכיבי שעות: {sorted(hours)}"
    for key in HOURS_KEYS:
        assert isinstance(hours[key], (int, float)), f"{key} אינו מספר: {hours[key]!r}"


@needs_parser
def test_a_dash_in_the_hours_line_is_zero_and_never_none(html_61753):
    """‏'-' בשורת השעות פירושו **אפס שעות**, וזה ידוע — לא 'לא ידוע'.

    זו ההבחנה ההפוכה מזו של הנ"ז: שם ‏0.0 היה שקר, כאן ‏None היה שקר.
    """
    hours = _hours_of(_details(html_61753, SE_CODE))
    for key in ("ma", "pr"):
        assert hours[key] is not None, f"{key} הוא '-' בדף — צריך 0.0, לא None"
        assert float(hours[key]) == 0.0, f"{key} צריך להיות 0.0: {hours[key]!r}"


@needs_parser
def test_61753_weekly_hours_come_from_the_semester_hours_line(html_61753):
    details = _details(html_61753, SE_CODE)
    assert details.weekly_hours == SE_WEEKLY, (
        f"'שעות סמסטריאליות : 4.00' → 4.0, קיבלתי {details.weekly_hours!r}"
    )


@needs_parser
def test_61753_language_is_hebrew(html_61753):
    details = _details(html_61753, SE_CODE)
    assert details.language.strip() == SE_LANGUAGE, (
        f"שפת הוראה שגויה: {details.language!r}"
    )


@needs_parser
def test_61753_code_and_name(html_61753):
    details = _details(html_61753, SE_CODE)
    assert details.code == SE_CODE
    assert SE_NAME in details.name, f"שם הקורס שגוי: {details.name!r}"


@needs_parser
def test_61753_description_is_present_and_hebrew(html_61753):
    details = _details(html_61753, SE_CODE)
    assert details.description.strip(), "התיאור ריק"
    assert _hebrew(details.description)
    assert SE_DESC_MARKER in details.description


@needs_parser
def test_61753_description_is_not_duplicated(html_61753):
    """הידיעון מגיש את גוש 'פרשיית לימוד' **פעמיים** באותו דף.

    פענוח תמים משרשר את שניהם ומכפיל את התיאור. זה לא באג קוסמטי: תיאור
    כפול הוא הסימן שהפרסר סופר את אותו גוש פעמיים — ואם הוא עושה זאת לתיאור,
    הוא עלול לעשות זאת גם לשעות ולנ"ז.
    """
    raw = html_61753
    assert raw.count(SE_DESC_MARKER) >= 2, "הדף השמור כבר לא מכיל תיאור כפול"

    description = _details(raw, SE_CODE).description
    assert description.count(SE_DESC_MARKER) == 1, (
        f"התיאור שוכפל ({description.count(SE_DESC_MARKER)} מופעים): {description[:160]!r}"
    )


@needs_parser
def test_61753_description_is_prose_not_the_hours_line(html_61753):
    """התיאור הוא הטקסט, לא הכותרת שמעליו."""
    description = _details(html_61753, SE_CODE).description
    assert "פרשיית לימוד" not in description, f"כותרת דלפה לתיאור: {description[:120]!r}"
    assert description.strip().startswith("מטרת"), (
        f"התיאור צריך להתחיל בפרוזה: {description[:120]!r}"
    )


@needs_parser
def test_61753_has_prerequisite_rows(html_61753):
    details = _details(html_61753, SE_CODE)
    assert isinstance(details.prerequisites, list), "prerequisites חייב להיות list"
    assert details.prerequisites, "לדף של 61753 יש טבלת תנאי קדם מלאה — היא לא נקראה"
    for row in details.prerequisites:
        assert isinstance(row, dict), f"שורת תנאי קדם חייבת להיות dict: {row!r}"


@needs_parser
def test_61753_prerequisite_rows_carry_the_spec_keys(html_61753):
    """‏[{"code","name","relation","alternative"}] — הכותרת של הטבלה בידיעון."""
    rows = _details(html_61753, SE_CODE).prerequisites
    for row in rows:
        for key in ("code", "name", "relation", "alternative"):
            assert key in row, f"מפתח {key} חסר בשורת תנאי קדם: {row!r}"


@needs_parser
def test_61753_prerequisites_name_a_real_course(html_61753):
    """הידיעון נותן **שם** ולא קוד בעמודת 'נושא נקשר' — ולכן השם חייב להישמר."""
    rows = _details(html_61753, SE_CODE).prerequisites
    names = [str(row.get("name") or "") for row in rows]
    assert any(SE_PREREQ_NAME in name for name in names), (
        f'ציפיתי לתנאי קדם "{SE_PREREQ_NAME}" ברשימה: {names[:6]}'
    )
    assert all(_hebrew(name) or not name for name in names)


def _alternative_text(row: dict) -> str:
    """הקורס החליפי של שורת תנאי-קדם, בלי להניח אם הוא דגל או שם."""
    for key in ("alternative_name", "alternative", "alt", "alternative_code"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


@needs_parser
def test_61753_prerequisites_keep_the_alternative_column(html_61753):
    """עמודת 'חליפי' היא מה שהופך תנאי קדם לניתן לעמידה — היא לא קישוט.

    בדף הזה יש שורות שבהן 'חדו"א 2' הוא חלופה ל'חדו"א 2מ'. אם העמודה
    נבלעת, סטודנט/ית שעבר/ה את החלופה יסומן/תסומן בטעות כמי שאינו עומד בתנאי.
    """
    rows = _details(html_61753, SE_CODE).prerequisites
    alternatives = [_alternative_text(row) for row in rows]
    assert any(alternatives), f"אף שורה לא שמרה קורס חליפי: {rows[:3]}"
    assert any('חדו"א 2' == text for text in alternatives), (
        f'ציפיתי לחלופה "חדו"א 2": {[a for a in alternatives if a][:5]}'
    )
    assert any(row.get("alternative") for row in rows), (
        "לפחות שורה אחת חייבת לסמן שיש לה חלופה"
    )


@needs_parser
def test_61753_prerequisite_relation_is_explained_in_hebrew(html_61753):
    rows = _details(html_61753, SE_CODE).prerequisites
    relations = [str(row.get("relation") or "") for row in rows]
    assert any("תנאי קדם" in text for text in relations), (
        f"סוג הקשר לא נקרא: {relations[:3]}"
    )


@needs_parser
def test_61753_parses_without_complaining_about_the_fields_that_exist(html_61753):
    """אזהרה היא סימן לשדה חסר. בדף הזה אין שדה חסר, אז אין על מה להתלונן."""
    details = _details(html_61753, SE_CODE)
    assert isinstance(details.warnings, list)
    blob = " ".join(str(w) for w in details.warnings)
    for word in ("נקודות זכות", "credits", "שפת הוראה", "language"):
        assert word not in blob, f"אזהרה על שדה שקיים בדף: {details.warnings}"


# ==========================================================================
# 4. ‏parse_course_details — הדף האמיתי של 11001 (קורס שאינו הנדסת תוכנה)
#    זהו המקרה שכל הפרויקט הזה נועד בשבילו.
# ==========================================================================
@needs_parser
def test_11001_a_non_se_course_returns_usable_data(html_11001):
    details = _details(html_11001, NON_SE_CODE)
    assert details.code == NON_SE_CODE
    assert NON_SE_NAME in details.name, f"שם שגוי: {details.name!r}"
    assert details.credits == NON_SE_CREDITS, (
        f"‏11001 הוא קורס 4 נ\"ז לפי הדף; קיבלתי {details.credits!r}"
    )
    assert details.description.strip(), "תיאור ריק לקורס שיש לו תיאור מלא בדף"


@needs_parser
def test_11001_credits_fall_back_to_the_study_line(html_11001):
    """בדף הזה 'נקודות זכות :' **ריקה** — הנ"ז קיימת רק בשורת פרשיית הלימוד.

    זה בדיוק ההבדל בין קורס הנדסת תוכנה לקורס כללי, וזה מה שהופך את
    ‏``curriculum.json`` למיותר כדרישה: המידע קיים, הוא פשוט במקום אחר בדף.
    """
    assert "נקודות זכות :" in _read(DETAILS_11001)
    details = _details(html_11001, NON_SE_CODE)
    assert details.credits == NON_SE_CREDITS
    assert details.credits != 0.0


@needs_parser
def test_11001_hours_are_three_lecture_two_tutorial(html_11001):
    hours = _hours_of(_details(html_11001, NON_SE_CODE))
    assert float(hours["he"]) == NON_SE_HOURS["he"], f"he שגוי: {hours}"
    assert float(hours["te"]) == NON_SE_HOURS["te"], f"te שגוי: {hours}"
    assert float(hours["ma"]) == 0.0 and float(hours["pr"]) == 0.0


@needs_parser
def test_11001_description_is_not_duplicated(html_11001):
    raw = _read(DETAILS_11001)
    assert raw.count(NON_SE_DESC_MARKER) >= 2, "הדף השמור כבר לא מכיל תיאור כפול"
    description = _details(html_11001, NON_SE_CODE).description
    assert description.count(NON_SE_DESC_MARKER) == 1, (
        f"התיאור שוכפל: {description[:160]!r}"
    )


@needs_parser
def test_11001_missing_optional_fields_are_empty_never_an_exception(html_11001):
    """בדף הזה אין 'שעות סמסטריאליות' ואין 'שפת הוראה'. זו לא שגיאה."""
    details = _details(html_11001, NON_SE_CODE)
    assert details.weekly_hours is None, (
        f"שעות סמסטריאליות ריקות → None, קיבלתי {details.weekly_hours!r}"
    )
    assert details.language == "", f"אין שורת שפת הוראה בדף: {details.language!r}"
    assert isinstance(details.prerequisites, list) and details.prerequisites == [], (
        f"לדף אין שורות תנאי קדם — צריך [] ולא {details.prerequisites!r}"
    )


@needs_parser
def test_11001_reports_what_it_could_not_find(html_11001):
    """שדה חסר מדווח כאזהרה. שקט הוא הכשל שהפרויקט הזה נבנה נגדו."""
    details = _details(html_11001, NON_SE_CODE)
    assert isinstance(details.warnings, list)
    assert details.warnings, "שני שדות חסרים בדף ואף אזהרה לא נרשמה"
    assert all(isinstance(w, str) and w.strip() for w in details.warnings)


# ==========================================================================
# 5. ‏0.0 לעולם אינו "לא ידוע" — שומר הרגרסיה של הסך המטעה
# ==========================================================================
@needs_parser
def test_a_page_without_credits_yields_none_and_a_warning(html_no_credits):
    details = _details(html_no_credits, SE_CODE)
    assert details.credits is None, (
        f"בלי שורת נ\"ז התשובה חייבת להיות None, קיבלתי {details.credits!r}"
    )
    assert details.warnings, "נ\"ז חסרה חייבת להיווצר כאזהרה, לא להיעלם בשקט"


@needs_parser
def test_a_page_without_credits_does_not_raise(html_no_credits):
    """הכול אופציונלי: שדה חסר הוא ``None`` ואזהרה — אף פעם לא חריגה."""
    details = _details(html_no_credits, SE_CODE)  # לא אמור לזרוק
    assert details.code == SE_CODE
    assert details.name, "השם עדיין קיים בדף גם בלי נ\"ז"


@needs_parser
@pytest.mark.parametrize(
    "label",
    ["no_credits", "empty", "not_html", "wrong_page", "search_page"],
)
def test_credits_is_never_zero_point_zero_for_unknown(label, html_no_credits):
    """שומר הרגרסיה המרכזי של המפרט.

    סך נ"ז ששותק על 86% מהקורסים גרוע מסך שמודה שאינו יודע. לכן: כשהמידע
    אינו קיים התשובה היא ``None`` — ואם היא מספר, הוא חייב להיות אמיתי וחיובי.
    """
    pages = {
        "no_credits": html_no_credits,
        "empty": "",
        "not_html": "לא HTML בכלל, סתם טקסט עברי",
        "wrong_page": _read(SINGLE_GROUP),
        "search_page": _read(SEARCH_PAGE),
    }
    details = _details(pages[label], "99999")
    credits = details.credits
    assert credits is None or credits > 0.0, (
        f"‏0.0 אינו 'לא ידוע' ({label}): credits={credits!r}"
    )


@needs_parser
@pytest.mark.parametrize("junk", ["", "   ", "<html></html>", "<div class='row'></div>"])
def test_parsing_junk_returns_a_result_with_warnings_not_an_exception(junk):
    details = _details(junk, "99999")
    assert details.code == "99999", "הקוד המבוקש נשמר גם כשהדף חסר תועלת"
    assert details.credits is None
    assert details.warnings, "דף שלא נקרא חייב להשאיר עקבות"
    assert isinstance(details.prerequisites, list)
    assert isinstance(details.hours, dict)


# ==========================================================================
# 6. ‏yedion_http — בניית הכתובת ושליפה דרך fetcher מוזרק (בלי רשת)
# ==========================================================================
@needs_http
def test_details_url_points_at_the_public_details_endpoint():
    url = yedion_mod.details_url(SE_CODE)
    assert "S_CourseDetails" in url, f"prgname שגוי: {url}"
    assert "info.braude.ac.il" in url, f"הכתובת חייבת להיות של הידיעון: {url}"
    assert SE_CODE in url


@needs_http
def test_details_url_keeps_the_documented_argument_order():
    """‏-N<course>,-N<sem>,-N<kind>,-N<group>,-N — לפי GROUND_TRUTH §1."""
    url = yedion_mod.details_url(SE_CODE, "2", "7", "271060330")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    raw = (query.get("arguments") or query.get("ARGUMENTS") or [""])[0]
    parts = raw.split(",")
    assert len(parts) == 5, f"חמישה ארגומנטים, קיבלתי {parts}"
    assert parts[0] == f"-N{SE_CODE}"
    assert parts[1] == "-N2", f"סמסטר במקום השני: {parts}"
    assert parts[2] == "-N7", f"סוג במקום השלישי: {parts}"
    assert parts[3] == "-N271060330", f"קבוצה במקום הרביעי: {parts}"
    assert parts[4] == "-N", f"הארגומנט החמישי הוא -N ריק: {parts}"


@needs_http
def test_details_url_defaults_are_the_neutral_group_zero():
    """ברירת המחדל שולפת את הקורס עצמו (קבוצה 0), לא קבוצה מסוימת."""
    url = yedion_mod.details_url(NON_SE_CODE)
    raw = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["arguments"][0]
    parts = raw.split(",")
    assert parts[0] == f"-N{NON_SE_CODE}"
    assert parts[3] == "-N0", f"ברירת המחדל לקבוצה היא 0: {parts}"


@needs_http
def test_details_url_is_a_pure_function_and_touches_nothing():
    """בניית כתובת אינה בקשה. אם היא נוגעת ברשת — הבדיקה הזו תתפוצץ."""
    assert yedion_mod.details_url(SE_CODE) == yedion_mod.details_url(SE_CODE)


@needs_http
@pytest.mark.skipif(
    not hasattr(yedion_mod.YedionHTTP, "fetch_details"),
    reason="YedionHTTP.fetch_details עדיין לא נכתבה",
)
def test_fetch_details_signature_matches_the_spec():
    # המתודה שנשמרה בייבוא — ה-fixture האוטומטי החליף את זו שעל המחלקה.
    params = list(inspect.signature(_REAL_FETCH_DETAILS).parameters)
    assert params[0] == "self", f"חתימה לא צפויה: {params}"
    assert "code" in params, f"חתימה לא צפויה: {params}"


@needs_http
@pytest.mark.skipif(
    not hasattr(yedion_mod.YedionHTTP, "fetch_details"),
    reason="YedionHTTP.fetch_details עדיין לא נכתבה",
)
def test_fetch_details_asks_for_the_details_page_and_returns_the_saved_html(
    monkeypatch, tmp_path, html_61753
):
    """‏fetcher מוזרק: הדף השמור חוזר, והכתובת שנתבקשה היא דף הפרטים.

    ‏``fetch_details`` המקורית מוחזרת נקודתית — שאר רשת הביטחון (‏urlopen,
    ‏fetch_course, הדפדפן) נשארת חסומה. הרשת מוחלפת ב-``opener`` מוזרק, שהוא
    ממשק ההזרקה המתועד של המודול, ולכן כל בניית הכתובת האמיתית עדיין רצה.
    """
    monkeypatch.setattr(yedion_mod.YedionHTTP, "fetch_details", _REAL_FETCH_DETAILS)
    fake = FakeFetcher({"S_CourseDetails": html_61753}, default=html_61753)
    client = yedion_mod.YedionHTTP(
        year="2027", delay_s=0.0, raw_dir=str(tmp_path / "raw"), opener=fake
    )
    html = client.fetch_details(SE_CODE)

    assert SE_DESC_MARKER in html, "לא חזר הדף השמור"
    assert fake.urls, "לא נשלחה אף בקשה"
    assert all("S_CourseDetails" in url for url in fake.urls), fake.urls
    assert all(SE_CODE in url for url in fake.urls), fake.urls


# ==========================================================================
# 7. ‏Store — שמירת פרטים, טעינה, וחלון ההתיישנות של שבעה ימים
# ==========================================================================
def _sample_details(
    code: str = SE_CODE,
    credits: float | None = SE_CREDITS,
    prereq_codes: list[str] | None = None,
) -> dict:
    """רשומת פרטים אופיינית — אותם שדות בדיוק שהמפרט מבטיח.

    ל-``prereq_codes`` שלושה מצבים שאינם זהים:

    * ``None`` (ברירת המחדל) — שורת תנאי קדם אחת בדיוק כפי שהידיעון מגיש
      אותה: **בלי עמודת קוד**, רק שם. זה המצב הנפוץ בדפים האמיתיים.
    * רשימת קודים — שורה לכל קוד, כשצריך לבדוק *לאן* תנאי הקדם מגיעים.
    * ``[]`` — טבלה ריקה במפורש: "נשלפה, ואין בה כלום".
    """
    if prereq_codes is None:
        prerequisites = [
            {
                "code": "",
                "name": SE_PREREQ_NAME,
                "relation": "תנאי קדם",
                "alternative": 'חדו"א 2',
            }
        ]
    else:
        prerequisites = [
            {"code": str(one), "name": "", "relation": "תנאי קדם", "alternative": None}
            for one in prereq_codes
        ]
    return {
        "code": code,
        "name": SE_NAME,
        "credits": credits,
        "hours": dict(SE_HOURS),
        "weekly_hours": SE_WEEKLY,
        "language": SE_LANGUAGE,
        "description": "מטרת הקורס היא הכרת פרדיגמות לתכנון וניתוח אלגוריתמים.",
        "prerequisites": prerequisites,
        "warnings": [],
    }


def _stamp(hours_ago: float) -> str:
    return store_mod.utc_now_iso(
        datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    )


@pytest.fixture
def fresh_store(tmp_path) -> "store_mod.Store":
    """מסד ריק וזמני. שום בדיקה כאן לא כותבת למסד האמיתי."""
    return store_mod.Store(str(tmp_path / "db"))


@needs_store
def test_details_round_trip_through_the_store(fresh_store):
    payload = _sample_details()
    fresh_store.save_details(SE_CODE, payload, _stamp(0))
    loaded = fresh_store.load_details(SE_CODE)

    assert isinstance(loaded, dict), f"load_details החזירה {type(loaded).__name__}"
    assert float(loaded["credits"]) == SE_CREDITS
    assert dict(loaded["hours"]) == SE_HOURS
    assert loaded["language"] == SE_LANGUAGE
    assert loaded["prerequisites"][0]["name"] == SE_PREREQ_NAME


@needs_store
def test_details_round_trip_keeps_hebrew_intact(fresh_store):
    """‏utf-8 בכל קריאה וכתיבה — ב-Windows ברירת המחדל הייתה הורסת את העברית."""
    fresh_store.save_details(SE_CODE, _sample_details(), _stamp(0))
    loaded = fresh_store.load_details(SE_CODE)
    assert loaded["description"].startswith("מטרת הקורס")
    assert _hebrew(loaded["name"])


@needs_store
def test_details_survive_a_new_store_object(tmp_path):
    """הפרטים יושבים על הדיסק, לא רק בזיכרון של התהליך."""
    root = str(tmp_path / "db")
    store_mod.Store(root).save_details(NON_SE_CODE, _sample_details(NON_SE_CODE, 4.0), _stamp(0))
    reopened = store_mod.Store(root).load_details(NON_SE_CODE)
    assert reopened is not None and float(reopened["credits"]) == 4.0


@needs_store
def test_details_live_in_their_own_file(tmp_path):
    """‏data/db/details.json — קובץ נפרד, כדי שלא ידרוס ולא ידרסו אותו."""
    root = tmp_path / "db"
    store = store_mod.Store(str(root))
    store.save_details(SE_CODE, _sample_details(), _stamp(0))

    path = root / "details.json"
    assert path.exists(), f"ציפיתי ל-details.json תחת {root}; יש שם {list(root.iterdir())}"
    blob = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(blob, dict) and blob, "הקובץ חייב להיות אובייקט JSON לא ריק"


@needs_store
def test_unknown_code_has_no_details(fresh_store):
    assert fresh_store.load_details("99999") is None


@needs_store
def test_details_of_two_courses_do_not_overwrite_each_other(fresh_store):
    fresh_store.save_details(SE_CODE, _sample_details(SE_CODE, 5.0), _stamp(0))
    fresh_store.save_details(NON_SE_CODE, _sample_details(NON_SE_CODE, 4.0), _stamp(0))
    assert float(fresh_store.load_details(SE_CODE)["credits"]) == 5.0
    assert float(fresh_store.load_details(NON_SE_CODE)["credits"]) == 4.0


@needs_store
def test_details_never_fetched_are_stale(fresh_store):
    assert fresh_store.details_stale("99999") is True


@needs_store
def test_details_fetched_now_are_fresh(fresh_store):
    fresh_store.save_details(SE_CODE, _sample_details(), _stamp(0))
    assert fresh_store.details_stale(SE_CODE) is False


@needs_store
def test_a_day_old_detail_is_still_fresh(fresh_store):
    """**הבדיקה של הנימוס.** פרטים משתנים לעיתים נדירות.

    אילו חלון ההתיישנות היה 24 שעות כמו של המערכת, הריצה היומית הייתה מכפילה
    את מספר הבקשות לשרת המכללה עבור נתונים שכמעט לא זזים. החלון הוא 7 ימים.
    """
    fresh_store.save_details(SE_CODE, _sample_details(), _stamp(25))
    assert fresh_store.details_stale(SE_CODE) is False, (
        "פרטים בני יממה עדיין טריים — אחרת הרענון היומי מכפיל את עומס הבקשות"
    )


@needs_store
@pytest.mark.parametrize(
    "hours_ago, expected_stale",
    [
        (1.0, False),
        (6 * DAY, False),
        (WEEK_HOURS - 1.0, False),  # רגע לפני הגבול
        (WEEK_HOURS + 1.0, True),  # רגע אחרי הגבול
        (8 * DAY, True),
        (30 * DAY, True),
    ],
)
def test_the_seven_day_window_at_its_boundary(fresh_store, hours_ago, expected_stale):
    fresh_store.save_details(SE_CODE, _sample_details(), _stamp(hours_ago))
    assert fresh_store.details_stale(SE_CODE) is expected_stale, (
        f"אחרי {hours_ago:.0f} שעות ציפיתי stale={expected_stale}"
    )


@needs_store
def test_the_staleness_window_is_overridable(fresh_store):
    """מי שרוצה חלון אחר מקבל אותו — ברירת המחדל היא זו שנשמרת."""
    fresh_store.save_details(SE_CODE, _sample_details(), _stamp(2))
    assert fresh_store.details_stale(SE_CODE, max_age_hours=1.0) is True
    assert fresh_store.details_stale(SE_CODE, max_age_hours=48.0) is False


@needs_store
def test_the_default_window_is_seven_days_not_one():
    default = inspect.signature(store_mod.Store.details_stale).parameters["max_age_hours"].default
    assert float(default) == pytest.approx(WEEK_HOURS), (
        f"ברירת המחדל חייבת להיות 7 ימים (168 שעות), קיבלתי {default!r}"
    )


@needs_store
def test_saving_details_does_not_disturb_the_sections_database(tmp_path):
    """הפרטים נשמרים **לצד** המערכת, לא במקומה."""
    root = tmp_path / "db"
    store = store_mod.Store(str(root))
    course = store_mod._demo_course() if hasattr(store_mod, "_demo_course") else None
    if course is None:  # pragma: no cover - שינוי פנימי במודול
        pytest.skip("אין קורס הדגמה במודול המסד")
    meta = store_mod._demo_meta(store_mod.content_sha1("x"))
    store.save_course(course, meta)
    store.save_details(course.code, _sample_details(course.code), _stamp(0))

    loaded, loaded_meta = store.load_course(course.code)
    assert loaded is not None and loaded_meta is not None
    assert loaded.code == course.code
    assert store.load_details(course.code) is not None


@needs_store
@needs_parser
def test_a_parsed_page_can_be_stored_and_read_back(fresh_store, html_11001):
    """המסלול המלא בלי רשת: דף שמור → פענוח → מסד → חזרה."""
    details = _details(html_11001, NON_SE_CODE)
    payload = details._asdict() if hasattr(details, "_asdict") else dict(details.__dict__)
    fresh_store.save_details(NON_SE_CODE, payload, _stamp(0))

    loaded = fresh_store.load_details(NON_SE_CODE)
    assert float(loaded["credits"]) == NON_SE_CREDITS
    assert float(loaded["hours"]["he"]) == NON_SE_HOURS["he"]
    assert fresh_store.details_stale(NON_SE_CODE) is False


# ==========================================================================
# 8. שכבת ה-HTTP — הזרימה של סטודנט/ית שהתוכנית שלו/ה אינה ב-rec.pdf
# ==========================================================================
def _copy_db(tmp_path: Path) -> Path:
    """עותק זמני של המסד האמיתי. הרענון היומי כותב לאמיתי בזמן שאנחנו רצים."""
    target = tmp_path / "db"
    last: Exception | None = None
    for _ in range(4):
        try:
            shutil.copytree(DB_ROOT, target)
            return target
        except (FileNotFoundError, PermissionError, OSError) as exc:  # pragma: no cover
            last = exc
            shutil.rmtree(target, ignore_errors=True)
            time.sleep(0.2)
    raise AssertionError(f"לא ניתן להעתיק את המסד: {last!r}")  # pragma: no cover


def _forget_details(db_root: Path, code: str) -> None:
    """מוחקת פרטים שמורים לקוד אחד מהעותק הזמני.

    הרענון היומי כבר מושך פרטים, ולכן ``details.json`` שבמסד האמיתי עשוי
    להכיל *כל* קורס. בדיקת "אין מידע → ``None``" חייבת להתחיל ממצב ידוע,
    ובלי לקבע איזה קוד במקרה עוד לא נשלף.
    """
    path = db_root / "details.json"
    if not path.exists():
        return
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # pragma: no cover - קובץ פגום, אין מה למחוק
        return

    def scrub(node: object) -> None:
        if isinstance(node, dict):
            node.pop(code, None)
            for value in list(node.values()):
                scrub(value)
        elif isinstance(node, list):
            for value in node:
                scrub(value)

    scrub(blob)
    path.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")


def _build_app(db_root: Path, curriculum_path: Path):
    assert _CREATE_APP is not None
    return _CREATE_APP(
        config={
            "db_root": str(db_root),
            "curriculum_path": str(curriculum_path),
            "allow_network": False,
        },
        serve_ui=False,
    )


@pytest.fixture
def tmp_db(tmp_path) -> Path:
    db_root = _copy_db(tmp_path)
    _forget_details(db_root, NO_DETAILS_CODE)
    return db_root


@pytest.fixture
def no_curriculum_path(tmp_path) -> Path:
    """נתיב לקובץ תוכנית שאינו קיים — סטודנט/ית שהמסלול שלו/ה לא ב-rec.pdf."""
    return tmp_path / "there-is-no-curriculum-here.json"


@pytest.fixture
def empty_curriculum_path(tmp_path) -> Path:
    """קובץ תוכנית תקין אבל ריק — התקלה השקטה השנייה."""
    path = tmp_path / "empty_curriculum.json"
    path.write_text(json.dumps({"semesters": {}}), encoding="utf-8")
    return path


@pytest.fixture
def client_with_curriculum(tmp_db):
    app = _build_app(tmp_db, CURRICULUM_PATH)
    with app.test_client() as client:
        yield client


@pytest.fixture
def client_without_curriculum(tmp_db, no_curriculum_path):
    app = _build_app(tmp_db, no_curriculum_path)
    with app.test_client() as client:
        yield client


@pytest.fixture
def client_with_empty_curriculum(tmp_db, empty_curriculum_path):
    app = _build_app(tmp_db, empty_curriculum_path)
    with app.test_client() as client:
        yield client


def _ok(resp) -> dict:
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200, f"ציפיתי ל-200, קיבלתי {resp.status_code}: {body[:300]!r}"
    data = resp.get_json(silent=True)
    assert isinstance(data, dict), f"התשובה אינה אובייקט JSON: {body[:300]!r}"
    assert data.get("ok") is True, f"ok אינו True: {json.dumps(data, ensure_ascii=False)[:300]}"
    assert "Traceback (most recent call last)" not in body, "traceback דלף לתשובה"
    return data


def _entries(data: dict) -> list[dict]:
    for key in ("results", "courses", "items", "matches", "catalog"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [item for item in value.values() if isinstance(item, dict)]
    raise AssertionError(
        f"לא נמצאה רשימת קורסים בתשובה: {json.dumps(data, ensure_ascii=False)[:300]}"
    )


_MISSING = object()


def _credits_pair(entry: dict):
    """‏(credits, credits_source) — סובלני לקינון, קפדני למשמעות."""
    credits = entry.get("credits", _MISSING)
    source = entry.get("credits_source")
    for key in ("credits_info", "credits_meta", "credits_detail"):
        block = entry.get(key)
        if isinstance(block, dict):
            source = source if source is not None else block.get("source")
            if credits is _MISSING and "credits" in block:
                credits = block["credits"]
    return credits, source


def _source_words(source) -> str:
    return str(source if source is not None else "").strip().casefold()


def _is_curriculum_source(source) -> bool:
    text = _source_words(source)
    return any(word in text for word in _CURRICULUM_SOURCE_WORDS)


def _is_yedion_source(source) -> bool:
    text = _source_words(source)
    return any(word in text for word in _YEDION_SOURCE_WORDS)


def _is_unknown_source(source) -> bool:
    return _source_words(source) in _UNKNOWN_SOURCE_VALUES


def _course_entry(data: dict, code: str) -> dict:
    for entry in _entries(data):
        if str(entry.get("code")) == code:
            return entry
    raise AssertionError(f"קורס {code} לא נמצא בתשובה: {[e.get('code') for e in _entries(data)][:20]}")


# ---------------------------------------------------- /api/catalog/browse
@needs_api
def test_browse_works_with_no_curriculum_loaded(client_without_curriculum):
    """שלב 2 חייב לעבוד גם למי שאין לו תוכנית — זה כל העניין."""
    data = _ok(client_without_curriculum.get("/api/catalog/browse?limit=25"))
    entries = _entries(data)
    assert entries, "עיון בקטלוג בלי תוכנית לימודים חייב להחזיר קורסים"
    for entry in entries:
        assert str(entry.get("code") or "").strip(), f"רשומה בלי קוד: {entry}"


@needs_api
def test_browse_matches_by_code_prefix(client_without_curriculum):
    data = _ok(client_without_curriculum.get("/api/catalog/browse?prefix=110&limit=50"))
    codes = [str(entry.get("code")) for entry in _entries(data)]
    assert codes, "קידומת 110 קיימת בקטלוג האמיתי"
    assert all(code.startswith("110") for code in codes), f"קידומת לא נאכפה: {codes[:10]}"
    # תת-קבוצה, לא שוויון: הקטלוג גדל בזמן שהבדיקה רצה.
    assert NON_SE_CODE in codes, f"‏{NON_SE_CODE} חייב להיות תחת קידומת 110: {codes[:10]}"


@needs_api
def test_browse_matches_a_hebrew_name_substring(client_without_curriculum):
    query = urllib.parse.quote(NON_SE_NAME)
    data = _ok(client_without_curriculum.get(f"/api/catalog/browse?q={query}&limit=50"))
    entries = _entries(data)
    assert entries, f"חיפוש '{NON_SE_NAME}' חייב להחזיר תוצאות"
    codes = [str(entry.get("code")) for entry in entries]
    assert NON_SE_CODE in codes, f"‏11001 אלגברה חייב להימצא: {codes[:10]}"
    assert any(_hebrew(entry.get("name")) for entry in entries)


@needs_api
def test_browse_honours_the_limit(client_without_curriculum):
    data = _ok(client_without_curriculum.get("/api/catalog/browse?limit=3"))
    assert len(_entries(data)) <= 3, "limit אינו נאכף"


@needs_api
def test_browse_combines_prefix_and_query(client_without_curriculum):
    query = urllib.parse.quote(NON_SE_NAME)
    data = _ok(
        client_without_curriculum.get(f"/api/catalog/browse?prefix=110&q={query}&limit=50")
    )
    codes = [str(entry.get("code")) for entry in _entries(data)]
    assert all(code.startswith("110") for code in codes), codes[:10]
    assert NON_SE_CODE in codes


@needs_api
def test_browse_never_reports_zero_credits_for_a_course_it_knows_nothing_about(
    client_without_curriculum,
):
    """אין תוכנית ואין פרטים שמורים → ‏None. אף פעם לא 0.0."""
    data = _ok(client_without_curriculum.get(f"/api/catalog/browse?prefix={NO_DETAILS_CODE}"))
    entry = _course_entry(data, NO_DETAILS_CODE)
    credits, source = _credits_pair(entry)
    assert credits is _MISSING or credits is None, (
        f"נ\"ז לא ידועה חייבת להיות None (או להיעדר), קיבלתי {credits!r}"
    )
    assert _is_unknown_source(source), f"credits_source שגוי ללא-ידוע: {source!r}"


@needs_api
def test_browse_still_works_when_the_curriculum_is_present(client_with_curriculum):
    """התוכנית היא העשרה — נוכחותה לא מפילה ולא משנה את חוזה העיון."""
    data = _ok(client_with_curriculum.get("/api/catalog/browse?prefix=110&limit=50"))
    codes = [str(entry.get("code")) for entry in _entries(data)]
    assert NON_SE_CODE in codes


# ------------------------------------------ /api/semester/<n>/courses
@needs_api
def test_semester_courses_without_a_curriculum_is_ok_not_an_error(
    client_without_curriculum,
):
    """‏200 עם ``curriculum_available: false`` — לא 404 ולא 500.

    לסטודנט/ית שהמסלול שלו/ה לא ב-rec.pdf, היעדר התוכנית הוא **מצב רגיל**,
    לא תקלה. מסך שגיאה כאן היה סוגר את האפליקציה בפניו/ה כבר בשלב 2.
    """
    resp = client_without_curriculum.get(f"/api/semester/{CURRICULUM_SEMESTER}/courses")
    assert resp.status_code == 200, (
        f"היעדר תוכנית אינו שגיאה; קיבלתי {resp.status_code}: "
        f"{resp.get_data(as_text=True)[:300]!r}"
    )
    data = _ok(resp)
    assert data.get("curriculum_available") is False, (
        f"חייב להיאמר במפורש שאין תוכנית: {json.dumps(data, ensure_ascii=False)[:300]}"
    )


@needs_api
def test_semester_courses_without_a_curriculum_returns_an_empty_list_not_junk(
    client_without_curriculum,
):
    data = _ok(client_without_curriculum.get(f"/api/semester/{CURRICULUM_SEMESTER}/courses"))
    assert _entries(data) == [], "אין תוכנית — אין קורסי תוכנית. לא המצאות."


@needs_api
def test_semester_courses_without_a_curriculum_says_so_in_hebrew(
    client_without_curriculum,
):
    """נאמר פעם אחת, בפשטות — ולא כשגיאה."""
    data = _ok(client_without_curriculum.get(f"/api/semester/{CURRICULUM_SEMESTER}/courses"))
    blob = json.dumps(data, ensure_ascii=False)
    assert "תוכנית" in blob, f"אין הסבר בעברית על היעדר התוכנית: {blob[:400]}"


@needs_api
def test_semester_courses_with_an_empty_curriculum_is_also_ok(
    client_with_empty_curriculum,
):
    resp = client_with_empty_curriculum.get(f"/api/semester/{CURRICULUM_SEMESTER}/courses")
    assert resp.status_code == 200, (
        f"תוכנית ריקה אינה שגיאה; קיבלתי {resp.status_code}: "
        f"{resp.get_data(as_text=True)[:300]!r}"
    )
    data = _ok(resp)
    assert data.get("curriculum_available") is False


@needs_api
def test_semester_courses_with_a_real_curriculum_still_reports_it_available(
    client_with_curriculum,
):
    """בקרת נגד: כשהתוכנית כן נטענה, הדגל אומר את זה — והקורסים חוזרים."""
    data = _ok(client_with_curriculum.get(f"/api/semester/{CURRICULUM_SEMESTER}/courses"))
    assert data.get("curriculum_available") is True
    assert _entries(data), "סמסטר 5 בתוכנית האמיתית אינו ריק"


@needs_api
def test_a_known_zero_is_told_apart_from_an_unknown(client_with_curriculum):
    """ההבחנה שכל המפרט נשען עליה: "אפס ידוע" אינו "לא ידוע".

    ‏11063 אנגלית בסיסי הוא **באמת** 0 נ"ז לפי התוכנית — אותו מותר להציג
    כאפס. ‏11002, שאינו בתוכנית ואין לו פרטים שמורים, אינו יודע — ואותו
    אסור להציג כאפס. אילו שניהם היו יוצאים ‏0.0, הסך היה משקר בשקט.
    """
    known = _credits_pair(
        _course_entry(_ok(client_with_curriculum.get("/api/semester/1/courses")),
                      CURRICULUM_ZERO_CODE)
    )
    assert known[0] == 0.0, f"אפס אמיתי מהתוכנית חייב להישאר 0.0: {known[0]!r}"
    assert _is_curriculum_source(known[1]), f"המקור הוא התוכנית: {known[1]!r}"

    unknown_entry = _course_entry(
        _ok(client_with_curriculum.get(f"/api/catalog/browse?prefix={NO_DETAILS_CODE}")),
        NO_DETAILS_CODE,
    )
    unknown = _credits_pair(unknown_entry)
    assert unknown[0] is None or unknown[0] is _MISSING, (
        f"קורס בלי מידע חייב לצאת None ולא 0.0: {unknown[0]!r}"
    )
    assert _is_unknown_source(unknown[1]), f"המקור חייב לומר 'לא ידוע': {unknown[1]!r}"

    text = unknown_entry.get("credits_text")
    if isinstance(text, str) and text:
        assert text.strip() not in {"0", "0.0", "0.00"}, (
            f"'לא ידוע' לא מוצג כאפס: {text!r}"
        )


@needs_api
@pytest.mark.parametrize(
    "path",
    [
        "/api/catalog/browse?prefix=110&limit=40",
        "/api/catalog/browse?prefix=617&limit=40",
        "/api/semester/1/courses",
        f"/api/semester/{CURRICULUM_SEMESTER}/courses",
    ],
)
def test_credits_and_their_source_never_contradict_each_other(
    client_with_curriculum, path
):
    """האינווריאנטה שכל התיקון הזה קיים בשבילה.

    מספר ↔ מקור ידוע. ‏``None`` ↔ "לא ידוע". שני הכיוונים, בכל נקודת קצה
    שמחזירה קורסים. הצירוף האסור הוא בדיוק זה שהיה: מספר (‏0.0) בלי מקור.
    """
    data = _ok(client_with_curriculum.get(path))
    checked = 0
    for entry in _entries(data):
        # שורות תוכנית בלי קוד ("קורס כללי 1", "ספורט") אינן קורסים שאפשר
        # לבחור, ואי אפשר לפתור להן מקור לפי קוד. הן מחוץ לאינווריאנטה.
        if not str(entry.get("code") or "").strip():
            continue
        credits, source = _credits_pair(entry)
        # רשומה שאינה מדווחת נ"ז בכלל אינה יכולה לסתור את עצמה — אין מה לבדוק.
        # ‏**מקור חסר אינו פטור**: "מספר בלי מקור" הוא בדיוק הצירוף האסור,
        # ולכן הוא נבדק כאן ולא מדולג.
        if credits is _MISSING:
            continue
        checked += 1
        if credits is None:
            assert _is_unknown_source(source), (
                f"‏{entry.get('code')}: אין נ\"ז אבל המקור הוא {source!r}"
            )
        else:
            assert isinstance(credits, (int, float)), (
                f"‏{entry.get('code')}: נ\"ז אינן מספר: {credits!r}"
            )
            assert credits >= 0.0, f"‏{entry.get('code')}: נ\"ז שליליות {credits!r}"
            assert source is not None, (
                f"‏{entry.get('code')}: נ\"ז {credits!r} בלי credits_source בכלל — "
                "מספר שאיש אינו חתום עליו הוא הצירוף שהמפרט אוסר"
            )
            assert not _is_unknown_source(source), (
                f"‏{entry.get('code')}: יש נ\"ז {credits!r} אבל המקור 'לא ידוע' — "
                "זה בדיוק הסך המטעה שהמפרט אוסר"
            )
    assert checked, f"אף רשומה לא נבדקה ב-{path} — האם השדות שינו שם?"


@needs_api
def test_a_curriculum_row_without_a_code_still_shows_its_credits(client_with_curriculum):
    """"קורס כללי 1" ו"ספורט" אינם ניתנים לבחירה, אבל הנ"ז שלהם ידועות.

    שורה כזו לא צריכה להיעלם ולא להפוך למקף — היא חלק מהמניין של הסמסטר.
    """
    data = _ok(client_with_curriculum.get("/api/semester/1/courses"))
    codeless = [e for e in _entries(data) if not str(e.get("code") or "").strip()]
    if not codeless:  # pragma: no cover - התוכנית עשויה להשתנות
        pytest.skip("אין בסמסטר 1 שורות בלי קוד")
    for entry in codeless:
        credits, _source = _credits_pair(entry)
        assert isinstance(credits, (int, float)) and credits > 0, (
            f"שורה בלי קוד איבדה את הנ\"ז שלה: {entry}"
        )
        text = entry.get("credits_text")
        if isinstance(text, str) and text:
            assert text.strip() not in {"—", "-", ""}, (
                f"נ\"ז ידועות הוצגו כמקף: {entry}"
            )


# ------------------------------------------------ סדר קדימויות של נ"ז
@pytest.fixture
def client_with_stored_details(tmp_db):
    """מסד זמני עם רשומות פרטים שנבנו כדי להכריע את **סדר** ההכרעה:

    * ‏61753 — קיים בתוכנית (5.0 נ"ז ותנאי קדם משלה), ובכוונה נשמרו לו פרטים
      **שגויים**: ‏99.0 נ"ז ותנאי קדם 99999. כך הבדיקה מוכיחה שהתוכנית מנצחת
      ולא רק שהמספרים במקרה שווים.
    * ‏11001 — אינו בתוכנית; הפרטים (4.0) הם המקור היחיד לנ"ז.
    * ‏11002 — אינו בתוכנית ו**אין לו רשומה בכלל**; חייב לצאת ``None``.
    * ‏11003 — אינו בתוכנית, ויש לו רשומה שה-נ"ז שבה ``None``. זה המצב שכל
      הרשומות במסד החי נמצאות בו, והוא **אינו** זהה למצב של 11002: כאן הקוד
      עובר דרך הנפילה-לאחור לידיעון ומקבל ממנה ``None``, ולכן דווקא הוא זה
      שיחזיר ‏0.0 אם מישהו יכתוב שם ``or 0.0``.
    * ‏11005 — אינו בתוכנית, ותנאי הקדם שלו (11003) מגיעים מהידיעון בלבד.
    * ‏11063 — בתוכנית, ומצהיר במפורש על אפס תנאי קדם. נשמרת לו כאן רשומה עם
      טבלה ריקה, כדי שהמצב יהיה קבוע ולא תלוי במה שהרענון היומי הספיק למשוך.
    """
    store = store_mod.Store(str(tmp_db))
    store.save_details(
        SE_CODE, _sample_details(SE_CODE, 99.0, prereq_codes=[WRONG_PREREQ_CODE]), _stamp(0)
    )
    store.save_details(NON_SE_CODE, _sample_details(NON_SE_CODE, NON_SE_CREDITS), _stamp(0))
    store.save_details(NULL_CREDITS_CODE, _sample_details(NULL_CREDITS_CODE, None), _stamp(0))
    store.save_details(
        YEDION_PREREQ_CODE,
        _sample_details(YEDION_PREREQ_CODE, None, prereq_codes=[NULL_CREDITS_CODE]),
        _stamp(0),
    )
    store.save_details(
        CURRICULUM_ZERO_CODE,
        _sample_details(CURRICULUM_ZERO_CODE, None, prereq_codes=[]),
        _stamp(0),
    )
    assert store.load_details(NO_DETAILS_CODE) is None
    stored_null = store.load_details(NULL_CREDITS_CODE)
    assert stored_null is not None, (
        "‏11003 חייב להיות עם רשומה — בלעדיה זה שוב המקרה של 11002 ולא מקרה חדש"
    )
    assert stored_null.get("credits") is None, (
        f"ה-נ\"ז ברשומה של {NULL_CREDITS_CODE} חייבות להיות None: {stored_null.get('credits')!r}"
    )

    app = _build_app(tmp_db, CURRICULUM_PATH)
    with app.test_client() as client:
        yield client


def _courses_body(codes, **extra) -> dict:
    # fetch_missing=False במפורש — אין רשת בבדיקות האלה.
    body = {"codes": list(codes), "semester": TERM, "year": YEAR, "fetch_missing": False}
    body.update(extra)
    return body


@needs_api
@needs_store
def test_credits_resolution_prefers_the_curriculum(client_with_stored_details):
    """שלב 1 בסדר: התוכנית מנצחת — היא עשירה יותר (אשכולות, צמידות, חלופות)."""
    data = _ok(
        client_with_stored_details.post("/api/courses", json=_courses_body([SE_CODE]))
    )
    credits, source = _credits_pair(_course_entry(data, SE_CODE))
    assert credits == 5.0, (
        f"התוכנית אומרת 5.0 והפרטים אומרים 99.0 — התוכנית מנצחת. קיבלתי {credits!r}"
    )
    assert _is_curriculum_source(source), f"credits_source חייב לומר 'תוכנית': {source!r}"


@needs_api
@needs_store
def test_credits_resolution_falls_back_to_the_yedion_details(client_with_stored_details):
    """שלב 2: אין תוכנית לקורס — הידיעון עונה. זה מה שסוגר את פער ה-86%."""
    data = _ok(
        client_with_stored_details.post("/api/courses", json=_courses_body([NON_SE_CODE]))
    )
    credits, source = _credits_pair(_course_entry(data, NON_SE_CODE))
    assert credits == NON_SE_CREDITS, f"ציפיתי ל-4.0 מהפרטים, קיבלתי {credits!r}"
    assert _is_yedion_source(source), f"credits_source חייב לומר 'ידיעון': {source!r}"


@needs_api
@needs_store
def test_credits_resolution_ends_at_none_and_never_at_zero(client_with_stored_details):
    """שלב 3: אין תוכנית ואין פרטים — ``None``, והממשק יראה מקף."""
    data = _ok(
        client_with_stored_details.post("/api/courses", json=_courses_body([NO_DETAILS_CODE]))
    )
    credits, source = _credits_pair(_course_entry(data, NO_DETAILS_CODE))
    assert credits is None or credits is _MISSING, (
        f"נ\"ז לא ידועה היא None ולא 0.0 — 0.0 הוא סך מטעה. קיבלתי {credits!r}"
    )
    assert _is_unknown_source(source), f"credits_source ל'לא ידוע': {source!r}"


@needs_api
@needs_store
def test_a_stored_record_with_null_credits_is_still_unknown(client_with_stored_details):
    """המצב שכל הרשומות במסד החי נמצאות בו: **יש** רשומה, וה-נ"ז שבה ``null``.

    ‏"אין רשומה" ו"רשומה בלי נ\"ז" הם שני מסלולי קוד שונים: הראשון נעצר לפני
    הנפילה-לאחור לידיעון, השני עובר דרכה ומקבל ממנה ``None``. רק השני קורה
    בפועל, ורק בו ``or 0.0`` תמים היה מחזיר את הסך המטעה בדלת האחורית.
    """
    data = _ok(
        client_with_stored_details.get(f"/api/catalog/browse?prefix={NULL_CREDITS_CODE}")
    )
    entry = _course_entry(data, NULL_CREDITS_CODE)
    if "has_details" in entry:
        assert entry["has_details"] is True, (
            "הבדיקה הזאת שווה משהו רק אם הרשומה באמת שם — אחרת זה שוב 11002"
        )

    credits, source = _credits_pair(entry)
    assert credits is None or credits is _MISSING, (
        f"רשומה עם נ\"ז ``null`` היא 'לא ידוע', לא 0.0: {credits!r}"
    )
    assert _is_unknown_source(source), f"credits_source שגוי ללא-ידוע: {source!r}"
    text = entry.get("credits_text")
    if isinstance(text, str) and text:
        assert text.strip() not in {"0", "0.0", "0.00"}, (
            f"‏'לא ידוע' הוצג כאפס: {text!r}"
        )


@needs_api
@needs_store
def test_the_credits_total_does_not_silently_swallow_unknown_courses(
    client_with_stored_details,
):
    """סך שמתעלם מקורס לא ידוע חייב **לומר** שהוא מתעלם.

    זה הליבה של דרישה 6 במפרט: סך ששותק על מה שאינו יודע גרוע מסך שמודה בכך.
    """
    data = _ok(
        client_with_stored_details.post(
            "/api/courses", json=_courses_body([NON_SE_CODE, NO_DETAILS_CODE])
        )
    )
    total = data.get("credits_total")
    assert total is None or float(total) == pytest.approx(NON_SE_CREDITS), (
        f"הסך יכול להיות 4.0 (הידוע) או None — לא משהו שמתחזה לשלם: {total!r}"
    )
    blob = json.dumps(data, ensure_ascii=False)
    assert NO_DETAILS_CODE in blob, "הקורס שלא נספר חייב להישאר גלוי בתשובה"


# ------------------------------------------- סדר קדימויות של תנאי קדם
# ‏SPEC_MULTIFACULTY §3 מדבר על נ"ז **ותנאי קדם** באותה נשימה, ועל אותם 86%
# מהקטלוג. בלי שלוש הבדיקות האלה אפשר למחוק את הנפילה-לאחור לידיעון בתנאי
# הקדם — ובדיקת הקדם פשוט נעלמת בשקט לכל קורס שאינו הנדסת תוכנה.
@needs_api
@needs_store
def test_prereq_resolution_prefers_the_curriculum(client_with_stored_details):
    """שלב 1: התוכנית מנצחת גם בתנאי הקדם — היא מכירה חלופות והחלפות."""
    import curriculum as curriculum_mod

    entry = curriculum_mod.find_course(curriculum_mod.load_curriculum(CURRICULUM_PATH), SE_CODE)
    expected = [str(code) for code in ((entry or {}).get("prereq") or [])]
    assert expected, (
        f"‏{SE_CODE} אמור להיות בתוכנית **עם** תנאי קדם; בלי זה הבדיקה חסרת משמעות"
    )

    data = _ok(
        client_with_stored_details.post("/api/courses", json=_courses_body([SE_CODE]))
    )
    course = _course_entry(data, SE_CODE)
    prereq = [str(code) for code in (course.get("prereq") or [])]
    assert prereq == expected, (
        f"תנאי הקדם חייבים להגיע מהתוכנית ({expected}), קיבלתי {prereq}"
    )
    assert WRONG_PREREQ_CODE not in prereq, (
        f"‏{WRONG_PREREQ_CODE} נשתל בפרטים בכוונה — הופעתו כאן אומרת שהסדר התהפך"
    )
    assert _is_curriculum_source(course.get("prereq_source")), (
        f"prereq_source חייב לומר 'תוכנית': {course.get('prereq_source')!r}"
    )


@needs_api
@needs_store
def test_prereq_resolution_falls_back_to_the_yedion_details(client_with_stored_details):
    """שלב 2: אין תוכנית לקורס — טבלת תנאי הקדם של הידיעון עונה.

    זו בדיוק המחצית השנייה של פער ה-86%: בלי הנפילה-לאחור הזאת, קורס מחוץ
    להנדסת תוכנה לא מקבל בדיקת קדם בכלל — ובשקט.
    """
    data = _ok(
        client_with_stored_details.post(
            "/api/courses", json=_courses_body([YEDION_PREREQ_CODE])
        )
    )
    course = _course_entry(data, YEDION_PREREQ_CODE)
    prereq = [str(code) for code in (course.get("prereq") or [])]
    assert prereq == [NULL_CREDITS_CODE], (
        f"תנאי הקדם השמורים בידיעון הם {[NULL_CREDITS_CODE]}, קיבלתי {prereq}"
    )
    assert _is_yedion_source(course.get("prereq_source")), (
        f"prereq_source חייב לומר 'ידיעון': {course.get('prereq_source')!r}"
    )


@needs_api
@needs_store
def test_prereq_with_no_source_says_unknown_and_not_just_an_empty_list(
    client_with_stored_details,
):
    """שלב 3, וההבחנה שמקבילה ל"אפס ידוע": רשימה ריקה אינה "אין תנאי קדם".

    ‏11002 — אין תוכנית ואין פרטים: ``[]`` שפירושו **לא ידוע**.
    ‏11063 — בתוכנית, ומצהיר במפורש שאין לו תנאי קדם: ``[]`` שפירושו **אפס**.
    אילו שניהם היו יוצאים באותו מקור, "לא בדקנו" היה נראה כמו "בדקנו ואין".
    """
    unknown = _course_entry(
        _ok(
            client_with_stored_details.post(
                "/api/courses", json=_courses_body([NO_DETAILS_CODE])
            )
        ),
        NO_DETAILS_CODE,
    )
    assert [str(code) for code in (unknown.get("prereq") or [])] == []
    assert _is_unknown_source(unknown.get("prereq_source")), (
        f"בלי שום מקור, prereq_source חייב לומר 'לא ידוע': {unknown.get('prereq_source')!r}"
    )

    known = _course_entry(
        _ok(client_with_stored_details.get("/api/semester/1/courses")),
        CURRICULUM_ZERO_CODE,
    )
    assert [str(code) for code in (known.get("prereq") or [])] == []
    assert _is_curriculum_source(known.get("prereq_source")), (
        "אפס תנאי קדם שהתוכנית מצהירה עליו הוא ידיעה, לא בורות: "
        f"{known.get('prereq_source')!r}"
    )


# ------------------------------------------------------------- /api/solve
def _solve_body(codes, **extra) -> dict:
    body = {
        "codes": list(codes),
        "semester": TERM,
        "year": YEAR,
        "target_days": 4,
        "top_n": 3,
    }
    body.update(extra)
    return body


@needs_api
def test_solve_over_four_non_curriculum_courses_is_feasible(client_with_curriculum):
    """ההוכחה שהזרימה עובדת לסטודנט/ית מחוץ להנדסת תוכנה.

    ארבעת הקורסים האלה אינם ב-``curriculum.json`` בכלל. אין ספירה מקובעת כאן:
    הרענון היומי מוסיף קבוצות והמספר זז. מה שחייב להתקיים הוא ש**קיים** פתרון.
    """
    data = _ok(client_with_curriculum.post("/api/solve", json=_solve_body(NON_SE_CODES)))
    assert data.get("feasible_count", 0) > 0, (
        f"לא נמצא אף צירוף: {json.dumps(data.get('reasons'), ensure_ascii=False)}"
    )
    assert data.get("schedules"), "יש צירופים אפשריים אבל לא הוחזרה אף מערכת"
    min_days = data.get("min_days")
    assert isinstance(min_days, int) and 1 <= min_days <= 6, f"min_days שגוי: {min_days!r}"


@needs_api
def test_solve_over_four_non_curriculum_courses_covers_all_four(client_with_curriculum):
    data = _ok(client_with_curriculum.post("/api/solve", json=_solve_body(NON_SE_CODES)))
    picks = data["schedules"][0]["picks"]
    assert {str(p["code"]) for p in picks} == set(NON_SE_CODES), (
        f"המערכת חייבת לכסות את כל ארבעת הקורסים: {[p.get('code') for p in picks]}"
    )
    assert any(_hebrew(p.get("lecturer")) for p in picks), (
        "אלה נתונים אמיתיים — חייב להיות לפחות מרצה אחד בעברית"
    )


@needs_api
def test_the_returned_non_se_schedule_really_has_no_conflicts(
    client_with_curriculum, tmp_db
):
    """אימות עצמאי: בונים את הקבוצות מהמסד ובודקים חפיפה במודל עצמו.

    ‏``allow_soft_conflicts=False`` במפורש: חפיפה מכוונת (ויתור על נוכחות
    בהרצאה) היא תשובה לגיטימית של המנוע, אבל כאן בודקים את המובן המחמיר של
    ‏``Selection.is_feasible`` — כל חפיפה פוסלת.
    """
    data = _ok(
        client_with_curriculum.post(
            "/api/solve", json=_solve_body(NON_SE_CODES, allow_soft_conflicts=False)
        )
    )
    assert data.get("feasible_count", 0) > 0, "גם בלי חפיפות מכוונות חייב להיות פתרון"
    picks = data["schedules"][0]["picks"]

    store = store_mod.Store(str(tmp_db))
    groups: list[Group] = []
    for pick in picks:
        course, _meta = store.load_course(str(pick["code"]))
        assert course is not None, f"קורס {pick['code']} אינו במסד"
        # ‏(סוג, מזהה) ולא מזהה בלבד: בידיעון אותו מזהה קבוצה מופיע גם
        # בהרצאה וגם בתרגול של אותו קורס. חיפוש לפי מזהה בלבד היה מחזיר
        # את הרכיב הלא נכון — ואז "חפיפה" מדומה.
        match = [
            g
            for g in course.groups
            if g.group_id == str(pick["group_id"]) and g.kind == str(pick["kind"])
        ]
        assert match, (
            f"קבוצה {pick['group_id']} ({pick['kind']}) לא נמצאה בקורס {pick['code']}"
        )
        groups.append(match[0])

    selection = Selection(groups)
    assert selection.is_feasible(), (
        f"המערכת שהוחזרה מתנגשת: {[ (a.label(), b.label()) for a, b in selection.overlapping_pairs() ]}"
    )
    assert len(selection.days_used()) == data["schedules"][0]["days_count"]


@needs_api
def test_solve_works_with_no_curriculum_at_all(client_without_curriculum):
    """הזרימה המלאה למי שהתוכנית שלו/ה אינה ב-rec.pdf בכלל."""
    resp = client_without_curriculum.post("/api/solve", json=_solve_body(NON_SE_CODES))
    assert resp.status_code == 200, (
        f"היעדר תוכנית אינו שגיאה בשיבוץ; קיבלתי {resp.status_code}: "
        f"{resp.get_data(as_text=True)[:300]!r}"
    )
    data = _ok(resp)
    assert data.get("feasible_count", 0) > 0, "הליבה אינה תלויה בתוכנית — היא חייבת לפתור"
    assert data.get("schedules")


@needs_api
@needs_store
def test_solve_reports_real_credits_once_details_are_stored(client_with_stored_details):
    """הסיבה שכל זה נבנה: אחרי שמירת הפרטים, הסך מפסיק להיות 0.0."""
    data = _ok(
        client_with_stored_details.post("/api/solve", json=_solve_body([NON_SE_CODE]))
    )
    total = data.get("credits_total")
    assert total is not None, "יש פרטים שמורים — הסך כבר לא 'לא ידוע'"
    assert float(total) == pytest.approx(NON_SE_CREDITS), (
        f"‏11001 הוא 4.0 נ\"ז לפי הידיעון; קיבלתי {total!r}"
    )
    assert float(total) != 0.0


@needs_api
@needs_store
def test_solve_does_not_pretend_to_know_credits_it_does_not_have(
    client_with_stored_details,
):
    """הכלל המרכזי של §3, בנקודת הקצה שבה הוא הכי חשוב.

    הבדיקה נשענת על **השדות המובנים** בתשובה ולא על חיפוש מחרוזת בגוף שלה:
    ‏``json.dumps`` תמיד מכיל את שם המפתח ``"credits_unknown"``, ולכן תנאי
    כמו ``"unknown" in blob`` מתקיים בכל תשובה שהיא — גם כשסך 0.0 מוצג
    כשלם. שלושת השדות שנבדקים כאן הם בדיוק אלה שמתהפכים ברגרסיה.
    """
    data = _ok(
        client_with_stored_details.post("/api/solve", json=_solve_body([NO_DETAILS_CODE]))
    )
    total = data.get("credits_total")
    assert total is None or float(total) == 0.0, f"בלי מידע אין להמציא סך: {total!r}"
    assert data.get("credits_unknown") == 1, (
        "הקורס היחיד בבקשה אינו ידוע — התשובה חייבת לספור אותו ככזה: "
        f"credits_unknown={data.get('credits_unknown')!r}"
    )
    assert data.get("credits_complete") is False, (
        "סך שאינו יודע את הקורס היחיד שבו אינו שלם: "
        f"credits_complete={data.get('credits_complete')!r}"
    )
    text = str(data.get("credits_text") or "").strip()
    assert text not in {"", "0", "0.0", "0.00"}, (
        f"‏0.0 הוצג כסך אמיתי במקום מקף: credits_text={text!r}"
    )
    assert NO_DETAILS_CODE in json.dumps(data, ensure_ascii=False), (
        "הקורס שלא נספר חייב להישאר גלוי בתשובה"
    )


@needs_api
@needs_store
def test_solve_counts_a_null_credits_record_as_unknown_and_not_as_zero(
    client_with_stored_details,
):
    """אותו כלל, במצב שקורה בפועל: רשומה קיימת שה-נ"ז שבה ``null``."""
    data = _ok(
        client_with_stored_details.post("/api/solve", json=_solve_body([NULL_CREDITS_CODE]))
    )
    assert data.get("credits_unknown") == 1, (
        "רשומה בלי נ\"ז אינה 'נ\"ז 0' — היא קורס שלא ידוע כמה הוא שווה: "
        f"credits_unknown={data.get('credits_unknown')!r}"
    )
    assert data.get("credits_complete") is False, (
        f"credits_complete={data.get('credits_complete')!r}"
    )
    text = str(data.get("credits_text") or "").strip()
    assert text not in {"", "0", "0.0", "0.00"}, (
        f"‏0.0 הוצג כסך אמיתי במקום מקף: credits_text={text!r}"
    )


# ==========================================================================
# 9. ‏refresh.py --all — הריצה היומית חייבת לגעת גם בפרטים (מפרט §6)
#
# ‏§6 אומר שלוש אמירות מדידות: ‏--all מרענן **גם** פרטים של קורסים שהפרטים
# שלהם מיושנים, **אחרי** מעבר המערכות, באותה השהיית נימוס — והסיכום מדווח
# את שתי הספירות בנפרד. בלי המעבר הזה חלון שבעת הימים ש-``details_stale``
# ו-``save_details`` נבנו בשבילו הוא קוד שאיש אינו מריץ, והפרטים במסד
# נשארים כפי שהיו ביום שנשלפו.
#
# הכול אופליין: ה-backend של ‏refresh.py מוחלף בגב מזויף שמחזיר את הדפים
# השמורים ומקליט כל בקשה, המסד והפרופיל הם זמניים, ו-``time.sleep`` מוקלט
# במקום להירדם באמת.
# ==========================================================================
#: קוד → הדף השמור שמייצג אותו. הזוגות האלה הם אלה שהפענוח באמת מצליח עליהם.
REFRESH_PAGES = {
    "11069": "single_group.html",
    "61753": "three_groups.html",
    "61756": "four_groups.html",
}
#: הדפים השמורים האלה הם של סמסטר ב — סינון לסמסטר אחר היה מרוקן אותם.
REFRESH_TERM = "ב"
DETAILS_FRESH_CODE = "11069"    # פרטים בני 25 שעות — טריים בחלון של 7 ימים
DETAILS_STALE_CODE = "61753"    # פרטים בני 8 ימים — מיושנים
DETAILS_MISSING_CODE = "61756"  # אין לו רשומת פרטים בכלל


class FakeRefreshBackend:
    """הגב ש-``refresh.py`` מדבר איתו, בלי רשת: דפים שמורים + יומן בקשות.

    ‏refresh.py מצפה מהגב לחמש שיטות בלבד (``open``/``close``/
    ``session_lost``/``fetch_course_html``/``fetch_catalog_html``/
    ``course_url``). ``fetch_details_html`` היא מה שמעבר הפרטים יצטרך, והיא
    נחשפת גם בשם ``fetch_details`` כדי לא לקבע שם אחד מהשניים.
    """

    kind = "http"
    can_need_login = False

    def __init__(self, year_greg: str) -> None:
        self.year_gregorian = str(year_greg)
        self.year_label = refresh_mod.hebrew_year_label(year_greg)
        #: ‏[("course", code), ("details", code), …] — לפי סדר הבקשות בפועל.
        self.calls: list[tuple[str, str]] = []

    def open(self) -> str:
        return self.year_label

    def close(self) -> None:
        pass

    def session_lost(self) -> bool:
        return False

    def course_url(self, code: str) -> str:
        return (
            "https://info.braude.ac.il/yedion/fireflyweb.aspx"
            f"?prgname=S_LOOK_FOR_NOSE&arguments=-N{code}"
        )

    def fetch_course_html(self, code: str) -> str:
        self.calls.append(("course", str(code)))
        return _read(FIXTURES / REFRESH_PAGES[str(code)])

    def fetch_catalog_html(self) -> str:  # pragma: no cover - אסור שייקרא
        raise AssertionError(
            "הקטלוג נשמר טרי בבדיקה הזאת — ריצה שמושכת אותו שוב אינה מנומסת"
        )

    def fetch_details_html(self, code: str, *_args, **_kwargs) -> str:
        self.calls.append(("details", str(code)))
        return _read(DETAILS_61753)

    #: שם חלופי סביר לאותה שליפה — כדי שהבדיקה לא תכתיב איזה מהשניים ייבחר.
    fetch_details = fetch_details_html

    @property
    def course_calls(self) -> list[str]:
        return [code for kind, code in self.calls if kind == "course"]

    @property
    def details_calls(self) -> list[str]:
        return [code for kind, code in self.calls if kind == "details"]


class RefreshWorld:
    """כל מה שבדיקה צריכה כדי להריץ את ``refresh.py`` ולבדוק מה הוא עשה."""

    def __init__(self, db_root: Path, backends: list, naps: list) -> None:
        self.db_root = db_root
        self.backends = backends
        #: כל ``time.sleep`` שהריצה ביקשה, בשניות — במקום להירדם באמת.
        self.naps = naps

    def run(self, *argv: str) -> int:
        return refresh_mod.main(
            ["--all", "--max-age", "24", "--semester", REFRESH_TERM, *argv]
        )

    @property
    def backend(self) -> FakeRefreshBackend:
        assert self.backends, "refresh.py לא בנה אף גב HTTP — הריצה לא הגיעה למעבר"
        return self.backends[-1]

    def store(self) -> "store_mod.Store":
        """מופע חדש בכל קריאה — כך בדיוק קורא webapp אחרי שהג'וב סיים."""
        return store_mod.Store(str(self.db_root))

    def record(self) -> dict:
        rec = self.store().last_refresh()
        assert isinstance(rec, dict), "לא נכתבה רשומת ריצה ליומן הרענון"
        return rec


@pytest.fixture
def refresh_world(tmp_path, monkeypatch) -> "RefreshWorld":
    """מסד, פרופיל וגב מזויפים — ריצה יומית שלמה בלי רשת ובלי המתנה.

    מצב הפתיחה נבנה כך שכל שאלה של §6 ניתנת להכרעה:
      * שלושת הקורסים ישנים (100 שעות) — כולם ייכנסו למעבר המערכות;
      * הקטלוג נשמר עכשיו — אין סיבה לשלוף אותו, וניסיון כזה מתפוצץ;
      * ‏11069 פרטים בני 25 שעות (טריים), 61753 בני 8 ימים (מיושנים),
        ‏61756 בלי פרטים כלל.
    """
    if refresh_mod is None:  # pragma: no cover - נבלם קודם ב-needs_refresh_details
        pytest.skip(_REFRESH_ERROR)
    if not hasattr(store_mod, "_demo_course"):  # pragma: no cover - שינוי פנימי
        pytest.skip("אין קורס הדגמה במודול המסד")

    db_root = tmp_path / "db"
    store = store_mod.Store(str(db_root))
    store.save_catalog(
        {code: {"name": f"קורס {code}"} for code in REFRESH_PAGES}, YEAR, "2027"
    )
    stale_when = datetime.now(timezone.utc) - timedelta(hours=100)
    for code in REFRESH_PAGES:
        store.save_course(
            store_mod._demo_course(code),
            store_mod._demo_meta(store_mod.content_sha1(code), when=stale_when),
        )
    store.save_details(DETAILS_FRESH_CODE, _sample_details(DETAILS_FRESH_CODE), _stamp(25))
    store.save_details(DETAILS_STALE_CODE, _sample_details(DETAILS_STALE_CODE), _stamp(8 * DAY))
    assert store.details_stale(DETAILS_FRESH_CODE) is False
    assert store.details_stale(DETAILS_STALE_CODE) is True
    assert store.details_stale(DETAILS_MISSING_CODE) is True

    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps({"year": "2027", "semester": REFRESH_TERM, "courses": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    backends: list[FakeRefreshBackend] = []

    def _make_backend(year_greg):
        backend = FakeRefreshBackend(year_greg)
        backends.append(backend)
        return backend

    naps: list[float] = []
    # ההשהיות נמדדות ולא מבוצעות: הנימוס נבדק, הבדיקה לא נרדמת.
    monkeypatch.setattr(refresh_mod.time, "sleep", lambda seconds: naps.append(float(seconds)))
    monkeypatch.setattr(refresh_mod, "DB_ROOT", db_root)
    monkeypatch.setattr(refresh_mod, "PROFILE_PATH", profile)
    monkeypatch.setattr(refresh_mod, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(refresh_mod, "HttpBackend", _make_backend)
    return RefreshWorld(db_root, backends, naps)


@needs_refresh_details
@needs_store
def test_all_refreshes_details_only_for_the_ones_that_went_stale(refresh_world):
    """‏--all שולף פרטים למיושנים ולחסרים — ולא לטריים.

    זו בדיוק בדיקת הנימוס שחלון שבעת הימים נבנה בשבילה: שליפת פרטים בני
    יממה בכל ריצה יומית הייתה מכפילה את מספר הבקשות לשרת המכללה עבור נתונים
    שכמעט אינם זזים.
    """
    refresh_world.run()
    fetched = refresh_world.backend.details_calls

    assert DETAILS_STALE_CODE in fetched, f"פרטים בני 8 ימים חייבים להתרענן: {fetched}"
    assert DETAILS_MISSING_CODE in fetched, f"קורס בלי פרטים כלל חייב להישלף: {fetched}"
    assert DETAILS_FRESH_CODE not in fetched, (
        f"פרטים בני 25 שעות טריים — שליפתם מכפילה את עומס הבקשות לחינם: {fetched}"
    )


@needs_refresh_details
@needs_store
def test_the_details_that_were_fetched_are_stored_and_stop_being_stale(refresh_world):
    """שליפה שלא נשמרת אינה שווה כלום — הריצה הבאה הייתה שולפת שוב."""
    exit_code = refresh_world.run()
    assert exit_code in (refresh_mod.EXIT_OK, refresh_mod.EXIT_PARTIAL), (
        f"הריצה נכשלה כולה, ולא רק מעבר הפרטים: קוד יציאה {exit_code}"
    )

    store = refresh_world.store()
    assert store.load_details(DETAILS_MISSING_CODE) is not None, (
        "הפרטים נשלפו אבל לא נשמרו — הריצה הבאה תשלוף אותם שוב"
    )
    assert store.details_stale(DETAILS_STALE_CODE) is False, (
        "רשומה שרועננה עכשיו אינה יכולה להישאר מיושנת"
    )


@needs_refresh_details
@needs_store
def test_the_details_pass_runs_after_the_timetable_pass(refresh_world):
    """הסדר קבוע במפרט: קודם המערכות, אחר כך הפרטים.

    המערכות הן מה שהסטודנט/ית מרגיש/ה מיד כשמשהו זז; הפרטים משתנים לעיתים
    נדירות. ריצה שנקטעת באמצע חייבת להספיק קודם את מה שדחוף.
    """
    refresh_world.run()
    kinds = [kind for kind, _code in refresh_world.backend.calls]
    assert "course" in kinds, "לא נשלף אף קורס — אין מעבר מערכות בכלל"
    assert "details" in kinds, "לא נשלפו פרטים — אין מה לבדוק על הסדר"
    last_course = max(index for index, kind in enumerate(kinds) if kind == "course")
    first_details = min(index for index, kind in enumerate(kinds) if kind == "details")
    assert first_details > last_course, (
        f"הפרטים נשלפו לפני שמעבר המערכות הסתיים: {kinds}"
    )


@needs_refresh_details
@needs_store
def test_the_details_pass_keeps_the_same_politeness_delay(refresh_world):
    """אותה השהיה בדיוק — אין "מעבר קטן" שמותר לו לרוץ מהר."""
    refresh_world.run()
    naps = refresh_world.naps
    fetches = len(refresh_world.backend.calls)

    assert naps, "לא נמדדה אף השהיה — הבקשות יצאו רצוף"
    assert all(nap >= refresh_mod.HTTP_DELAY_S for nap in naps), (
        f"השהיה קצרה מ-{refresh_mod.HTTP_DELAY_S} שניות: {naps}"
    )
    # פער אחד בין כל שתי בקשות **בתוך** כל מעבר: (קורסים-1) + (פרטים-1).
    assert len(naps) >= fetches - 2, (
        f"‏{fetches} בקשות אבל רק {len(naps)} השהיות — מעבר אחד רץ בלי נימוס"
    )


@needs_refresh_details
@needs_store
def test_the_run_record_counts_details_separately_from_courses(refresh_world):
    """"דווחו שתי הספירות בנפרד" — אחרת "עודכנו 3" לא אומר *מה* עודכן."""
    refresh_world.run()
    record = refresh_world.record()

    details_fields = {
        key: value for key, value in record.items() if "details" in str(key).lower()
    }
    assert details_fields, (
        "רשומת הריצה מדווחת קורסים בלבד; §6 דורש ספירת פרטים נפרדת: "
        f"{sorted(record)}"
    )
    assert sorted(str(code) for code in (record.get("attempted") or [])) == sorted(
        REFRESH_PAGES
    ), (
        "ספירת הקורסים חייבת להישאר של הקורסים בלבד — שתי ספירות, לא אחת "
        f"מעורבבת: {record.get('attempted')}"
    )


# ==========================================================================
# 10. עוגני שפיות — הבדיקות עצמן לא נשענות על מה שזז
# ==========================================================================
def test_the_four_non_se_courses_really_are_outside_the_curriculum():
    """אם מישהו יוסיף אותם ל-curriculum.json, הבדיקות למעלה יאבדו משמעות."""
    import curriculum as curriculum_mod

    curr = curriculum_mod.load_curriculum(CURRICULUM_PATH)
    inside = [code for code in NON_SE_CODES if curriculum_mod.find_course(curr, code)]
    assert not inside, (
        f"‏{inside} כבר בתוכנית — יש לבחור קורסים אחרים לבדיקת 'מחוץ להנדסת תוכנה'"
    )


def test_the_four_non_se_courses_have_stored_data_for_this_term():
    """תת-קבוצה, לא שוויון: המאגר גדל כל הזמן ואסור לקבע את גודלו."""
    store = store_mod.Store(str(DB_ROOT))
    everything = store.load_all()
    missing = [code for code in NON_SE_CODES if code not in everything]
    assert not missing, f"חסרים מהמאגר: {missing}"
    for code in NON_SE_CODES:
        course = everything[code]
        assert course.groups, f"אין קבוצות ל-{code}"
        semesters = {m.semester for g in course.groups for m in g.meetings}
        assert TERM in semesters, f"‏{code} אינו נפתח בסמסטר {TERM}: {semesters}"


def test_the_saved_details_pages_are_the_ones_the_tests_describe():
    """אם הדפים השמורים הוחלפו — עדיף שהבדיקה הזו תיפול ראשונה ובבירור."""
    se = _read(DETAILS_61753)
    non_se = _read(DETAILS_11001)
    assert "S_CourseDetails" in se or "פרשיית לימוד" in se
    assert "נקודות זכות : 5.00" in se, "דף 61753 השתנה — 5.00 נ\"ז אינו שם"
    assert "שפת הוראה של הקורס" in se
    assert "תנאי קדם לנושא" in se
    assert "פרשיית לימוד" in non_se
    assert "שפת הוראה" not in non_se, "דף 11001 השתנה — הוא אמור להיות בלי שפת הוראה"


def test_this_file_never_asserts_an_exact_database_size():
    """שמירה על עצמנו: רענון קטלוג מלא רץ ברקע והמספרים זזים.

    כל טענה על גודל מאגר או קטלוג הייתה נשברת מעצמה תוך יום. הבדיקה הזו
    סורקת את הקובץ הזה ומוודאת שאיש לא החזיר לכאן מספר קסם.
    """
    source = _read(Path(__file__))
    # הצירופים נבנים בזמן ריצה, אחרת הבדיקה הייתה מוצאת את עצמה.
    needles = [f"== {number}" for number in (571, 591, 269, 2614, 493)]
    needles.append("len(" + "everything) ==")
    for forbidden in needles:
        assert forbidden not in source, (
            f"קיבוע גודל מאגר בקובץ הבדיקות: {forbidden!r} — יש לבדוק תת-קבוצה במקום"
        )


def test_the_network_guard_is_actually_armed():
    """רשת הביטחון עצמה נבדקת — אחרת היא בטחון מדומה."""
    with pytest.raises(RuntimeError):
        yedion_mod.YedionHTTP(delay_s=0.0, raw_dir=None).fetch_course("61753")
    with pytest.raises(RuntimeError):
        urllib.request.urlopen("https://info.braude.ac.il/")
