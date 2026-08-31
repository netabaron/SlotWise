# -*- coding: utf-8 -*-
"""
בדיקות המושך חסר-ההתחברות — tests for src/yedion_http.py (SPEC_V2 §3, GROUND_TRUTH §9).

הגילוי שמאחורי המודול הזה: **חיפוש הקורסים בידיעון אינו דורש התחברות בכלל.**
רק ``prgname=Enter_Search`` חסום מאחורי שער ה-Citrix; ``S_LOOK_FOR_NOSE`` ו-
``S_LOOK_FOR_NOSE_AB`` קריאים לכל אחד ב-HTTP רגיל. לכן הרענון היומי יכול להיות
שקט ואוטומטי לגמרי — בלי דפדפן, בלי חלון, בלי זיהוי.

יש בפרוטוקול הזה מלכודת אחת, והיא כל הסיפור של הקובץ הזה:

    **חובה לבצע GET חימום לפני ה-POST של ChangeYear.**
    בלעדיו ה-POST מחזיר 200, הכותרת אפילו מציגה תשפ"ז — וכל GET שאחריו חוזר
    בשקט כ*תשפ"ו*, בלי שום שגיאה. נצפה במו עינינו: 11069 החזיר 4 קבוצות
    (תשפ"ו) במקום 2 (תשפ"ז).

לכן שרת-הדמה שכאן לא רק מחזיר דפים: הוא **משחזר את הבאג**. שרת שמעניש חימום
חסר הוא ההוכחה האמיתית שהסדר בקוד נכון — הרבה יותר מבדיקת סדר קריאות בלבד.

**אין רשת באף בדיקה.** מזריקים opener מזויף, וגם חוסמים את שכבת הסוקטים כרשת
ביטחון. הדפים הם ה-HTML האמיתי שנשמר מהידיעון (``data/raw/*.html``, ואם הוא
חסר — ה-fixtures ב-``tests/fixtures/real_yedion/``), כך שהטענות נבדקות מול
מארקאפ אמיתי ולא מול המצאה.

איך מריצים:
    python -m pytest tests -q
"""

from __future__ import annotations

import http.client
import inspect
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from email.message import Message
from io import BytesIO
from pathlib import Path

import pytest

# --------------------------------------------------------------------------
# הכנת הסביבה: להוסיף את src/ ל-sys.path בדיוק כמו ש-main.py עושה.
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass  # זרם שלא ניתן לשינוי (pytest capture / pipe) — ממשיכים בלי

import yedion_http  # noqa: E402  (import after the sys.path surgery — intentional)
from parser import extract_page_year, parse_course_page  # noqa: E402
from yedion_http import BASE_URL, YearMismatchError, YedionHTTP  # noqa: E402

#: אימות השנה ואי-התאמת שנה הן שתי פנים של אותה תקלה (``GROUND_TRUTH`` §9),
#: והמימוש מבדיל ביניהן בשני סוגי חריגה. הבדיקות מקבלות כל אחת מהן.
YearSwitchError = getattr(yedion_http, "YearSwitchError", YearMismatchError)
YEAR_ERRORS = (YearSwitchError, YearMismatchError)

# ==========================================================================
# דפים אמיתיים
# ==========================================================================
RAW_DIR = ROOT / "data" / "raw"
FIXTURES = ROOT / "tests" / "fixtures" / "real_yedion"

#: ``data/raw`` הוא git-ignored (תוצר גריפה, לא מקור). כשהוא קיים — משתמשים
#: במארקאפ של בראודה עצמה; כשלא — ב-fixtures של MTA, מאותה משפחת תבניות.
HAVE_BRAUDE_RAW = (RAW_DIR / "11069_1.html").is_file()

CODES = ("11069", "61753", "61756", "61757", "61832", "62027")

#: מיפוי גיבוי לקוד שאין לו דמפ אמיתי — כל אחד מהם דף ידיעון מלא ואמיתי.
_FALLBACK_PAGES = {
    "11069": "single_group.html",
    "61753": "three_groups.html",
    "61756": "four_groups.html",
    "61757": "multi_group_lecture_tutorial.html",
    "61832": "three_groups.html",
    "62027": "single_group.html",
}

YEAR_LABELS = {"2027": 'תשפ"ז', "2026": 'תשפ"ו', "2025": 'תשפ"ה'}
WANT_YEAR = "2027"  # תשפ"ז — השנה שהסטודנטית צריכה
PREVIOUS_YEAR = "2026"  # תשפ"ו — מה שהאתר מציג לפני החלפת שנה


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def course_page(code: str) -> str:
    """דף קורס אמיתי עבור ``code`` (בראודה אם יש, אחרת fixture)."""
    raw = RAW_DIR / f"{code}_1.html"
    if raw.is_file():
        return _read(raw)
    return _read(FIXTURES / _FALLBACK_PAGES.get(code, "single_group.html"))


def catalog_page() -> str:
    raw = RAW_DIR / "catalog_1.html"
    if raw.is_file():
        return _read(raw)
    return _read(FIXTURES / "catalog_all_courses.html")


SEARCH_PAGE = _read(FIXTURES / "enter_search_page.html")


def as_year(html: str, gregorian: str) -> str:
    """כותב מחדש דף שמור כך שידווח על שנה אחרת — בשתי הדרכים שהידיעון מדווח:
    התווית העברית בכותרת, וה-``<option selected>`` בבורר השנה."""
    label = YEAR_LABELS[gregorian]
    out = html.replace(YEAR_LABELS[WANT_YEAR], label)
    if gregorian != WANT_YEAR:
        out = re.sub(
            r'<option\s+selected\s+value="%s"' % WANT_YEAR,
            '<option value="%s"' % WANT_YEAR,
            out,
        )
        out = re.sub(
            r'<option\s+value="%s"' % gregorian,
            '<option selected value="%s"' % gregorian,
            out,
            count=1,
        )
    return out


# ==========================================================================
# תשתית: opener מזויף שמקליט כל קריאה
# ==========================================================================
@dataclass
class Call:
    """קריאת HTTP אחת, כפי שהוקלטה."""

    method: str
    url: str
    headers: dict[str, str]
    body: str
    timeout: object = None

    @property
    def query(self) -> dict[str, str]:
        raw = urllib.parse.urlsplit(self.url).query
        return {
            k: v[0]
            for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()
        }

    @property
    def form(self) -> dict[str, str]:
        if not self.body:
            return {}
        return {
            k: v[0]
            for k, v in urllib.parse.parse_qs(self.body, keep_blank_values=True).items()
        }

    def param(self, name: str) -> str:
        """שדה לפי שם, ללא תלות ברישיות ובלי אכפת אם הוא ב-query או בגוף."""
        wanted = name.casefold()
        for source in (self.query, self.form):
            for key, value in source.items():
                if key.casefold() == wanted:
                    return value
        return ""

    @property
    def prgname(self) -> str:
        return self.param("prgname")

    @property
    def arguments(self) -> str:
        return self.param("arguments")

    @property
    def course_code(self) -> str:
        m = re.search(r"-N(\d+)", self.arguments)
        return m.group(1) if m else ""

    def __str__(self) -> str:  # pragma: no cover - נוחות דיבוג
        return f"{self.method} {self.prgname} {self.arguments}"


class FakeResponse:
    """תשובת HTTP מזויפת — מספיק ממשק כדי להיראות כמו ``http.client.HTTPResponse``."""

    def __init__(self, html: str, url: str, status: int = 200) -> None:
        self._stream = BytesIO(html.encode("utf-8"))
        self.url = url
        self.status = status
        self.code = status
        self.reason = "OK"
        headers = Message()
        headers.add_header("Content-Type", "text/html; charset=utf-8")
        self.headers = headers
        self.msg = headers

    def read(self, amt: int | None = None) -> bytes:
        return self._stream.read() if amt is None else self._stream.read(amt)

    def readline(self, *a, **k) -> bytes:
        return self._stream.readline(*a, **k)

    def __iter__(self):
        return iter(self._stream)

    def info(self) -> Message:
        return self.headers

    def geturl(self) -> str:
        return self.url

    def getcode(self) -> int:
        return self.status

    def getheader(self, name: str, default=None):
        return self.headers.get(name, default)

    def close(self) -> None:
        self._stream.close()

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False


class FakeYedion:
    """ידיעון מזויף — כולל הבאג של ``GROUND_TRUTH`` §9.

    ``warm_up_required=True`` (ברירת המחדל) מחקה את ההתנהגות שנצפתה באמת:
    ה-POST של ChangeYear "תופס" רק אם כבר קיים session (כלומר בוצע GET לפניו).
    אם לא — התשובה ל-POST *מציגה* את השנה המבוקשת, אבל כל GET שאחריה חוזר
    כשנה הקודמת. בשקט. בלי שגיאה.
    """

    def __init__(
        self,
        *,
        default_year: str = PREVIOUS_YEAR,
        warm_up_required: bool = True,
        search_year: str | None = None,
        course_year: str | None = None,
        course_year_overrides: dict[str, str] | None = None,
        fail: dict[str, Exception] | None = None,
    ) -> None:
        self.default_year = default_year
        self.warm_up_required = warm_up_required
        self.search_year = search_year
        self.course_year = course_year
        self.course_year_overrides = dict(course_year_overrides or {})
        self.fail = dict(fail or {})

        self.session_started = False
        self.effective_year = default_year
        self.posted_year: str | None = None
        self.unexpected: list[Call] = []

    # -- הפרוטוקול עצמו --------------------------------------------------
    def change_year(self, year: str) -> str:
        """שלב 1: POST ChangeYear. תופס *רק* אם כבר יש session."""
        self.posted_year = year
        if self.session_started or not self.warm_up_required:
            self.effective_year = year
        return as_year(SEARCH_PAGE, self.search_year or year)

    def look_for_nose(self, code: str) -> str:
        """שלב 0/2: GET חיפוש לפי קוד קורס. גם מייצר את ה-session."""
        self.session_started = True
        year = self.course_year_overrides.get(
            code, self.course_year or self.effective_year
        )
        return as_year(course_page(code), year)

    def look_for_nose_ab(self) -> str:
        self.session_started = True
        return as_year(catalog_page(), self.course_year or self.effective_year)

    def respond(self, call: Call) -> FakeResponse:
        if call.prgname == "Enter_Search" or call.method == "POST":
            year = call.param("ChangeYear") or WANT_YEAR
            return FakeResponse(self.change_year(year), call.url)

        if call.prgname == "S_LOOK_FOR_NOSE_AB":
            return FakeResponse(self.look_for_nose_ab(), call.url)

        if call.prgname == "S_LOOK_FOR_NOSE":
            code = call.course_code
            if code in self.fail:
                raise self.fail[code]
            return FakeResponse(self.look_for_nose(code), call.url)

        self.unexpected.append(call)
        raise AssertionError(f"הידיעון המזויף קיבל בקשה לא צפויה: {call}")


class FakeOpener:
    """``urllib.request.OpenerDirector`` מזויף שמקליט הכול ולא נוגע ברשת."""

    def __init__(self, server: FakeYedion) -> None:
        self.server = server
        self.calls: list[Call] = []
        self.addheaders: list[tuple[str, str]] = []

    # החתימה זהה ל-OpenerDirector.open כדי שכל סגנון קריאה יעבוד.
    def open(self, fullurl, data=None, timeout=None, **kwargs) -> FakeResponse:
        call = self._record(fullurl, data, timeout)
        self.calls.append(call)
        return self.server.respond(call)

    def close(self) -> None:  # pragma: no cover - נדרש רק לשלמות הממשק
        pass

    @staticmethod
    def _record(fullurl, data, timeout) -> Call:
        if isinstance(fullurl, str):
            body = data.decode("utf-8") if isinstance(data, bytes) else (data or "")
            method = "POST" if data else "GET"
            return Call(method, fullurl, {}, str(body), timeout)

        payload = fullurl.data if fullurl.data is not None else data
        body = payload.decode("utf-8") if isinstance(payload, bytes) else (payload or "")
        headers = {str(k).casefold(): str(v) for k, v in fullurl.header_items()}
        return Call(fullurl.get_method(), fullurl.full_url, headers, str(body), timeout)

    # -- עזרי שאילתה -----------------------------------------------------
    def of_kind(self, prgname: str) -> list[Call]:
        return [c for c in self.calls if c.prgname == prgname]

    @property
    def gets(self) -> list[Call]:
        return [c for c in self.calls if c.method == "GET"]

    @property
    def posts(self) -> list[Call]:
        return [c for c in self.calls if c.method == "POST"]


@dataclass
class Harness:
    """כל מה שבדיקה צריכה: הלקוח, מה שהוקלט, ולאן נכתבו הדמפים."""

    client: object
    opener: FakeOpener
    server: FakeYedion
    sleeps: list[float]
    log_lines: list[str]
    raw_dir: Path

    @property
    def waits(self) -> list[float]:
        """ההשהיות שהלקוח *התכוון* לקחת (``YedionHTTP.waits``)."""
        return list(getattr(self.client, "waits", []))

    def dumped(self) -> list[Path]:
        return sorted(self.raw_dir.glob("*.html")) if self.raw_dir.is_dir() else []


# ==========================================================================
# fixtures
# ==========================================================================
@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """רשת ביטחון: גם אם מישהו יעקוף את ה-opener, לא ייפתח חיבור אמיתי."""

    def _refuse(*args, **kwargs):
        raise AssertionError(
            "בדיקה ניסתה לפתוח חיבור רשת אמיתי — אסור. יש להזריק opener מזויף."
        )

    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", _refuse, raising=False)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", _refuse, raising=False)


@pytest.fixture
def make_client(monkeypatch, tmp_path):
    """בונה ``YedionHTTP`` שכל בקשה שלו הולכת ל-``FakeOpener``, ושלא ישן באמת.

    שתי דרכי הזרקה, ושתיהן נבדקות:
      * ברירת המחדל — ``opener=`` (ממשק ההזרקה המתועד של המודול).
      * ``real_sleep_path=True`` — מזייפים את ``urllib.request.build_opener``
        עצמו, כך שהמודול חושב שהוא מדבר עם רשת אמיתית ולכן *באמת* קורא
        לפונקציית ההשהיה. ככה בודקים שהשעון נקרא, בלי לחכות באמת.
    """

    def _make(
        server: FakeYedion | None = None, *, real_sleep_path: bool = False, **kwargs
    ) -> Harness:
        server = server if server is not None else FakeYedion()
        opener = FakeOpener(server)
        params = inspect.signature(YedionHTTP.__init__).parameters

        # רשת ביטחון: גם אם ה-opener נבנה בעצלתיים, הוא יהיה המזויף.
        monkeypatch.setattr(
            urllib.request, "build_opener", lambda *a, **k: opener, raising=False
        )
        if not real_sleep_path and "opener" in params:
            kwargs["opener"] = opener

        # שינה מזויפת, כדי שהבדיקות לא יחכו באמת.
        sleeps: list[float] = []

        def _fake_sleep(seconds: float) -> None:
            sleeps.append(float(seconds))

        monkeypatch.setattr(time, "sleep", _fake_sleep)
        if "sleep" in params:
            kwargs.setdefault("sleep", _fake_sleep)

        log_lines: list[str] = []
        raw_dir = Path(kwargs.pop("raw_dir", tmp_path / "raw"))
        kwargs.setdefault("year", WANT_YEAR)
        kwargs.setdefault("delay_s", 0.25)
        kwargs.setdefault("log", log_lines.append)

        client = YedionHTTP(raw_dir=str(raw_dir), **kwargs)
        return Harness(client, opener, server, sleeps, log_lines, raw_dir)

    return _make


@pytest.fixture
def session(make_client):
    """לקוח שכבר ביצע ``open_session`` בהצלחה מול שרת תקין."""
    harness = make_client()
    harness.client.open_session()
    return harness


# ==========================================================================
# 1. החוזה של המודול
# ==========================================================================
def test_the_module_exposes_the_documented_contract():
    assert isinstance(BASE_URL, str)
    assert BASE_URL.startswith("https://info.braude.ac.il/yedion/fireflyweb.aspx")
    assert issubclass(YearMismatchError, Exception)
    for name in ("open_session", "fetch_course", "fetch_catalog", "scrape"):
        assert callable(getattr(YedionHTTP, name, None)), f"חסרה המתודה {name}"


def test_the_constructor_accepts_the_documented_keywords():
    params = inspect.signature(YedionHTTP.__init__).parameters
    for name in ("year", "delay_s", "timeout_s", "raw_dir", "log"):
        assert name in params, f"חסר הפרמטר {name} ב-YedionHTTP.__init__"


def test_the_module_imports_only_the_standard_library():
    """כלל ברזל מ-SPEC_V2 §3: urllib + http.cookiejar בלבד. לא requests, לא דפדפן."""
    source = _read(SRC / "yedion_http.py")
    imports = re.findall(r"^\s*(?:import|from)\s+([\w.]+)", source, re.MULTILINE)
    for banned in ("requests", "playwright", "bs4", "lxml"):
        assert not any(
            name == banned or name.startswith(banned + ".") for name in imports
        ), f"המודול מייבא {banned} — אמור להיות ספריית תקן בלבד"
    assert any(name.startswith("urllib") for name in imports)
    assert any("cookiejar" in name for name in imports)


def test_the_module_handles_no_credentials():
    """כלל ברזל: אין טיפול בסיסמאות בשום מקום. אין למה — הפרוטוקול אנונימי."""
    source = _read(SRC / "yedion_http.py")
    code_only = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert not re.search(r"\bgetpass\b", code_only)
    assert not re.search(r"\bkeyring\b", code_only)
    assert not re.search(r"password\s*=", code_only)
    assert not re.search(r"\binput\s*\(", code_only)


# ==========================================================================
# 2. open_session — סדר הפעולות הוא כל התיקון
# ==========================================================================
def test_open_session_warms_up_before_posting_the_year(make_client):
    """GROUND_TRUTH §9: ה-GET חייב לקדום ל-POST. זה הבאג, וזה התיקון."""
    harness = make_client()
    harness.client.open_session()

    assert len(harness.opener.calls) >= 2
    first, second = harness.opener.calls[0], harness.opener.calls[1]

    assert first.method == "GET", f"הקריאה הראשונה חייבת להיות GET, לא {first}"
    assert first.prgname == "S_LOOK_FOR_NOSE"
    assert second.method == "POST"
    assert second.prgname == "Enter_Search"

    order = [(c.method, c.prgname) for c in harness.opener.calls]
    assert order.index(("GET", "S_LOOK_FOR_NOSE")) < order.index(
        ("POST", "Enter_Search")
    )


def test_the_warm_up_carries_a_course_code(make_client):
    harness = make_client()
    harness.client.open_session()
    warm_up = harness.opener.calls[0]
    assert warm_up.arguments.startswith("-N")
    assert warm_up.course_code.isdigit()


def test_the_year_post_carries_the_documented_form_fields(make_client):
    harness = make_client()
    harness.client.open_session()
    post = harness.opener.posts[0]
    assert post.param("PRGNAME") == "Enter_Search"
    assert post.param("ARGUMENTS") == "-A,,-A,ChangeYear"
    assert post.param("ChangeYear") == WANT_YEAR


def test_the_module_knows_the_year_the_student_needs():
    """תשפ"ז = 2027. הקבוע קיים כדי שאיש לא ינחש אותו במקום אחר."""
    assert getattr(yedion_http, "DEFAULT_YEAR", WANT_YEAR) == WANT_YEAR


def test_an_explicit_year_is_the_one_that_is_posted(make_client):
    harness = make_client(year=WANT_YEAR)
    harness.client.open_session()
    assert harness.opener.posts[0].param("ChangeYear") == WANT_YEAR
    assert harness.server.effective_year == WANT_YEAR


def test_year_none_falls_back_to_the_current_academic_year(make_client):
    """``year=None`` = **כן** מחליף שנה, לשנה האקדמית הנוכחית.

    זו לא קוסמטיקה: הידיעון נפתח על השנה הקודמת, ולכן "לא ציינו שנה"
    חייב להיות "השנה הנוכחית" ולא "מה שהאתר יחליט". שתיקה כאן הייתה
    מחזירה בשקט את המערכת של אשתקד.
    """
    harness = make_client(year=None)
    harness.client.open_session()
    assert harness.opener.posts, "year=None חייב להחליף שנה, לא לדלג"
    assert harness.opener.posts[0].param("ChangeYear") == yedion_http.current_academic_year()


def test_empty_year_is_the_explicit_way_to_skip_the_switch(make_client):
    """``year=""`` = במפורש לא נוגעים בשנה. זו הדרך היחידה לדלג."""
    harness = make_client(year="")
    harness.client.open_session()
    assert harness.opener.posts == []
    assert harness.server.posted_year is None


def test_open_session_raises_when_the_year_comes_back_wrong(make_client):
    """אימות השנה אינו קישוט: שנה אחרת = עצירה רועשת, לא המשך שקט."""
    harness = make_client(FakeYedion(course_year=PREVIOUS_YEAR))
    with pytest.raises(YEAR_ERRORS):
        harness.client.open_session()
    assert harness.client.session_ready is False


def test_the_year_error_message_names_both_years(make_client):
    harness = make_client(FakeYedion(course_year=PREVIOUS_YEAR))
    with pytest.raises(YEAR_ERRORS) as excinfo:
        harness.client.open_session()
    message = str(excinfo.value)
    assert YEAR_LABELS[WANT_YEAR] in message or WANT_YEAR in message
    assert YEAR_LABELS[PREVIOUS_YEAR] in message or PREVIOUS_YEAR in message


def test_the_year_is_verified_on_a_fresh_get_not_on_the_post_reply(make_client):
    """התקלה של §9 היא "ה-POST נראה מצוין וה-GET הבא חוזר עם שנה אחרת".

    לכן שרת שמחזיר POST משכנע אבל דפי קורס של השנה הקודמת חייב להיתפס.
    """
    harness = make_client(
        FakeYedion(search_year=WANT_YEAR, course_year=PREVIOUS_YEAR)
    )
    with pytest.raises(YEAR_ERRORS):
        harness.client.open_session()
    # ה-POST באמת "הצליח": הכותרת שלו הראתה את השנה הנכונה.
    assert harness.opener.posts, "לא נשלח POST בכלל"


def test_no_course_is_fetched_when_the_year_cannot_be_confirmed(make_client):
    """מוטב לחזור בלי נתונים מאשר עם מערכת של שנה שגויה."""
    harness = make_client(FakeYedion(course_year=PREVIOUS_YEAR))
    result = harness.client.scrape(["11069", "61753"])
    assert result == {}
    assert _error_blob(harness.client)


def test_the_fake_server_really_punishes_a_missing_warm_up():
    """שיניים לבדיקה הבאה: בלי חימום, השרת המזויף מחזיר את השנה הקודמת."""
    server = FakeYedion()
    server.change_year(WANT_YEAR)  # POST ראשון, בלי GET לפניו
    assert extract_page_year(server.look_for_nose("11069")) == YEAR_LABELS[PREVIOUS_YEAR]

    fresh = FakeYedion()
    fresh.look_for_nose("11069")  # חימום
    fresh.change_year(WANT_YEAR)
    assert extract_page_year(fresh.look_for_nose("11069")) == YEAR_LABELS[WANT_YEAR]


def test_open_session_survives_a_server_that_punishes_a_missing_warm_up(make_client):
    """הבדיקה מקצה-לקצה של §9: מול שרת שמעניש חימום חסר, הלקוח יוצא נקי."""
    harness = make_client(FakeYedion(warm_up_required=True))
    harness.client.open_session()
    assert harness.server.effective_year == WANT_YEAR
    html = harness.client.fetch_course("11069")
    assert extract_page_year(html) == YEAR_LABELS[WANT_YEAR]


def test_posting_the_year_before_the_warm_up_is_refused(make_client):
    """אם מישהו יהפוך את הסדר בעתיד — הקוד עוצר אותו, לא השרת."""
    harness = make_client()
    step_2 = getattr(harness.client, "_step_2_change_year", None)
    if step_2 is None:
        pytest.skip("אין שלב פנימי נפרד להחלפת שנה במימוש הזה")
    with pytest.raises(Exception) as excinfo:
        step_2()
    assert harness.opener.posts == [], "ה-POST נשלח למרות שלא היה חימום"
    assert "חימום" in str(excinfo.value) or "warm" in str(excinfo.value).casefold()


def test_open_session_is_idempotent(make_client):
    """קריאה שנייה לא מציפה את השרת בעוד סבב של שלוש בקשות."""
    harness = make_client()
    harness.client.open_session()
    after_first = len(harness.opener.calls)
    harness.client.open_session()
    assert len(harness.opener.calls) == after_first


def test_every_request_goes_to_the_yedion(session):
    session.client.fetch_course("61753")
    for call in session.opener.calls:
        assert call.url.startswith(BASE_URL.split("?")[0])
        assert "citrix" not in call.url.casefold()
        assert "login" not in call.url.casefold()


def test_only_the_three_public_endpoints_are_used(session):
    session.client.fetch_course("61753")
    session.client.fetch_catalog()
    used = {c.prgname for c in session.opener.calls}
    assert used <= {"S_LOOK_FOR_NOSE", "S_LOOK_FOR_NOSE_AB", "Enter_Search"}


# ==========================================================================
# 3. fetch_course
# ==========================================================================
def test_fetch_course_returns_the_page_as_the_yedion_sent_it(session):
    html = session.client.fetch_course("61753")
    assert html == course_page("61753")
    assert "S_CourseDetails" in html


def test_fetch_course_asks_for_the_right_code(session):
    session.client.fetch_course("61756")
    call = session.opener.of_kind("S_LOOK_FOR_NOSE")[-1]
    assert call.method == "GET"
    assert call.arguments == "-N61756"


def test_fetch_course_raises_year_mismatch_on_a_wrong_year_page(make_client):
    """הסשן תקין, אבל *הדף הזה* חזר משנה אחרת — לא מפרסרים אותו."""
    harness = make_client(FakeYedion(course_year_overrides={"61753": PREVIOUS_YEAR}))
    harness.client.open_session()
    with pytest.raises(YearMismatchError):
        harness.client.fetch_course("61753")


def test_fetch_course_dumps_the_raw_page_before_it_checks_the_year(make_client):
    """הכלל של scraper.dump_page נשמר: קודם שומרים לדיסק, אחר כך מפרשים."""
    harness = make_client(FakeYedion(course_year_overrides={"61832": PREVIOUS_YEAR}))
    harness.client.open_session()

    with pytest.raises(YearMismatchError):
        harness.client.fetch_course("61832")

    dumps = list(harness.raw_dir.glob("61832*.html"))
    assert dumps, "הדף לא נשמר — בכישלון פירוש נשארנו בלי ראיה על הדיסק"
    saved = _read(dumps[0])
    assert extract_page_year(saved) == YEAR_LABELS[PREVIOUS_YEAR]


def test_a_successful_fetch_is_dumped_too(session):
    session.client.fetch_course("61757")
    dumps = list(session.raw_dir.glob("61757*.html"))
    assert dumps
    assert _read(dumps[0]) == course_page("61757")


def test_the_dump_is_written_as_utf8(session):
    session.client.fetch_course("11069")
    dumps = list(session.raw_dir.glob("11069*.html"))
    assert dumps
    raw_bytes = dumps[0].read_bytes()
    assert raw_bytes.decode("utf-8")  # cp1255 would have exploded on the Hebrew
    assert "קבוצה".encode("utf-8") in raw_bytes


def test_repeated_fetches_do_not_overwrite_each_other(session):
    session.client.fetch_course("11069")
    session.client.fetch_course("11069")
    assert len(list(session.raw_dir.glob("11069*.html"))) >= 2


@pytest.mark.skipif(
    not HAVE_BRAUDE_RAW, reason="אין דמפים של בראודה ב-data/raw (git-ignored)"
)
def test_the_fetched_markup_parses_into_the_real_groups(session):
    """הטענה הכי חשובה: מה שחזר הוא באמת דף בראודה שהפרסר יודע לקרוא."""
    html = session.client.fetch_course("11069")
    result = parse_course_page(html, "11069", semester="א")
    assert len(result.course.groups) == 2
    assert result.course.name.startswith("אנגלית")


# ==========================================================================
# 4. הקטלוג — בקשה אחת, לא לולאה על האלף-בית
# ==========================================================================
def test_fetch_catalog_uses_exactly_one_request(session):
    before = len(session.opener.calls)
    session.client.fetch_catalog()
    assert len(session.opener.calls) - before == 1


def test_fetch_catalog_never_loops_over_the_alphabet(session):
    """SPEC_V2 §3: בקשה אחת מחזירה את כל הקטלוג. לולאה על אותיות היא בזבוז
    ומטרד לשרת של המכללה — ואין מה שיחסום אותנו, אז אנחנו חוסמים את עצמנו."""
    session.client.fetch_catalog()
    catalog_calls = session.opener.of_kind("S_LOOK_FOR_NOSE_AB")
    assert len(catalog_calls) == 1
    assert catalog_calls[0].arguments.strip() in ("-A", "")
    assert not re.search(r"-A\s*[א-ת]", catalog_calls[0].arguments)


def test_fetch_catalog_returns_the_catalog_and_dumps_it(session):
    html = session.client.fetch_catalog()
    assert html == catalog_page()
    assert session.raw_dir.is_dir()
    assert list(session.raw_dir.glob("catalog*.html")), "הקטלוג לא נשמר לדיסק"


# ==========================================================================
# 5. שקט — הבקשה המפורשת של הסטודנטית
# ==========================================================================
def test_the_module_never_prints(make_client, capsys):
    """"יש גם שורות קוד שמופיעות על המסך" — לא עוד. הכול הולך ל-log."""
    harness = make_client()
    harness.client.open_session()
    harness.client.fetch_course("61753")
    harness.client.fetch_catalog()
    harness.client.scrape(["11069", "62027"])

    captured = capsys.readouterr()
    assert captured.out == "", f"המודול הדפיס למסך: {captured.out!r}"
    assert captured.err == "", f"המודול כתב ל-stderr: {captured.err!r}"


def test_a_failing_fetch_is_also_silent(make_client, capsys):
    harness = make_client(FakeYedion(course_year_overrides={"61753": PREVIOUS_YEAR}))
    harness.client.open_session()
    with pytest.raises(YearMismatchError):
        harness.client.fetch_course("61753")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_progress_goes_to_the_log_callback(make_client):
    harness = make_client()
    harness.client.open_session()
    harness.client.fetch_course("61753")
    assert harness.log_lines, "לא הגיעה אף שורת התקדמות ל-callback"
    assert any("61753" in line for line in harness.log_lines)


def test_the_client_works_without_a_log_callback(make_client, capsys):
    """log=None אינו אמור להפיל — ובוודאי לא להפוך להדפסה למסך."""
    harness = make_client(log=None)
    harness.client.open_session()
    harness.client.fetch_course("11069")
    assert capsys.readouterr().out == ""


# ==========================================================================
# 6. scrape — עובר הלאה על כישלון, ולא בשקט
# ==========================================================================
def _error_blob(client) -> str:
    errors = getattr(client, "errors", None)
    assert errors is not None, "YedionHTTP חייב לחשוף .errors"
    if isinstance(errors, dict):
        return "\n".join(f"{k}: {v}" for k, v in errors.items())
    return "\n".join(str(item) for item in errors)


def test_scrape_returns_html_for_every_code(session):
    result = session.client.scrape(["11069", "61753", "62027"])
    assert set(result) == {"11069", "61753", "62027"}
    assert result["61753"] == course_page("61753")


def test_scrape_continues_past_a_failing_code(make_client):
    boom = urllib.error.URLError("connection reset by the college")
    harness = make_client(FakeYedion(fail={"61756": boom}))
    harness.client.open_session()

    result = harness.client.scrape(["11069", "61756", "62027"])

    assert "11069" in result and "62027" in result
    assert not result.get("61756")


def test_scrape_records_the_failing_code_in_errors(make_client):
    boom = urllib.error.URLError("connection reset by the college")
    harness = make_client(FakeYedion(fail={"61756": boom}))
    harness.client.open_session()
    harness.client.scrape(["11069", "61756", "62027"])

    blob = _error_blob(harness.client)
    assert "61756" in blob
    assert "11069" not in blob
    assert len(harness.client.errors) == 1


def test_scrape_records_a_year_mismatch_as_an_error(make_client):
    """שנה שגויה בקורס אחד לא מפילה את כל הרענון — אבל גם לא נבלעת."""
    harness = make_client(
        FakeYedion(course_year_overrides={"61832": PREVIOUS_YEAR})
    )
    harness.client.open_session()
    result = harness.client.scrape(["11069", "61832", "62027"])

    assert "11069" in result and "62027" in result
    assert "61832" in _error_blob(harness.client)


def test_scrape_is_silent_even_when_a_code_fails(make_client, capsys):
    harness = make_client(FakeYedion(fail={"61756": urllib.error.URLError("nope")}))
    harness.client.open_session()
    harness.client.scrape(["11069", "61756"])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_scrape_asks_for_each_code_exactly_once(session):
    session.client.scrape(["11069", "61753", "62027"])
    asked = [c.course_code for c in session.opener.of_kind("S_LOOK_FOR_NOSE")]
    for code in ("11069", "61753", "62027"):
        assert asked.count(code) == 1, f"{code} נמשך {asked.count(code)} פעמים"


# ==========================================================================
# 7. נימוס — אין מי שיאט אותנו, אז אנחנו מאיטים את עצמנו
# ==========================================================================
def test_a_delay_is_taken_between_requests(session):
    """אין login שמאט אותנו יותר, ולכן ההאטה היא באחריות הלקוח."""
    before = len(session.waits)
    session.client.scrape(["11069", "61753", "62027"])
    taken = session.waits[before:]
    assert len(taken) >= 2, "אין השהיה בין הבקשות — זו הצפה של שרת המכללה"
    assert all(value > 0 for value in taken)


def test_the_delay_matches_delay_s(make_client):
    harness = make_client(delay_s=0.75)
    harness.client.open_session()
    before = len(harness.waits)
    harness.client.scrape(["11069", "61753"])
    taken = harness.waits[before:]
    assert taken
    for value in taken:
        assert 0 < value <= 0.75
        assert value == pytest.approx(0.75, abs=0.3)


def test_the_delay_really_calls_the_clock(make_client):
    """"הזרקת שעון מזויף" — כשהמודול חושב שהוא מול רשת אמיתית, הוא ישן."""
    harness = make_client(delay_s=0.4, real_sleep_path=True)
    harness.client.open_session()
    assert harness.sleeps, "פונקציית ההשהיה לא נקראה כלל"
    for value in harness.sleeps:
        assert 0 < value <= 0.4


def test_a_zero_delay_means_no_waiting_at_all(make_client):
    harness = make_client(delay_s=0.0)
    harness.client.open_session()
    harness.client.scrape(["11069", "61753"])
    assert harness.waits == []
    assert harness.sleeps == []


def test_requests_carry_a_normal_user_agent(session):
    session.client.fetch_course("61753")
    default_headers = {k.casefold(): v for k, v in session.opener.addheaders}
    for call in session.opener.calls:
        agent = call.headers.get("user-agent") or default_headers.get("user-agent", "")
        assert agent, f"בקשה בלי User-Agent: {call}"
        assert "python-urllib" not in agent.casefold()


def test_requests_never_carry_credentials(session):
    session.client.fetch_course("61753")
    for call in session.opener.calls:
        assert "authorization" not in call.headers
        assert "password" not in call.body.casefold()
        assert "password" not in call.url.casefold()


def test_the_timeout_is_handed_to_the_opener(make_client):
    harness = make_client(timeout_s=12.5)
    harness.client.open_session()
    harness.client.fetch_course("11069")
    seen = [c.timeout for c in harness.opener.calls if c.timeout is not None]
    assert seen, "timeout_s לא הועבר לאף בקשה — בקשה תקועה תתלה את הרענון"
    for value in seen:
        assert value == pytest.approx(12.5)
