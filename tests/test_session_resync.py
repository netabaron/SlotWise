# -*- coding: utf-8 -*-
"""
סשן שחוזר לשנה אחרת באמצע ריצה — tests for ``YedionHTTP.fetch_course_resyncing``
and for ``build_catalog.fetch_missing`` / exit code 5.

הריצה הלילית של 2026-09-25 (36080575127): הסשן נפתח ואומת על תשפ"ז, 145 דפים
חזרו תקינים, ואז — בלי שום שגיאה מהשרת — הידיעון חזר לתשפ"ו. בדיקת השנה
תפסה כל דף, אבל הלולאה ספרה כל אחד ככישלון של קורס והמשיכה על אותו סשן
עוד 74 דקות: ‏374 מתוך 571 נכשלו, ושער הכיסוי הפיל את הבנייה.

הידיעון המזויף כאן משחזר את זה: כל סשן "שוכח" את השנה אחרי מספר דפים
שנקבע מראש. הבדיקות מוודאות שלושה דברים:
  * שכחה אחת עולה פתיחה מחדש אחת וניסיון חוזר של אותו קורס — ולא יותר;
  * סשן שממשיך לשכוח עוצר את הריצה מוקדם (``SessionRevertedError``, קוד 5);
  * בדיקת השנה לא התרככה: שום דף בשנה הלא נכונה לא מוחזר, ושום דמפ כזה
    לא נשאר במקום שבו ``build_catalog`` יספור אותו כתקין.

הבדיקות משתמשות בידיעון המזויף של ``test_yedion_http.py`` (בלי לשנות אותו)
ומוסיפות לו רק את השכחה.
"""

from __future__ import annotations

import http.client
import socket
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "src", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import build_catalog as B  # noqa: E402
import yedion_http  # noqa: E402
from parser import extract_page_year  # noqa: E402
from test_yedion_http import (  # noqa: E402
    CODES,
    PREVIOUS_YEAR,
    WANT_YEAR,
    YEAR_LABELS,
    FakeOpener,
    FakeYedion,
)
from yedion_http import (  # noqa: E402
    WARMUP_CODE,
    SessionRevertedError,
    YearMismatchError,
    YedionHTTP,
)


class RevertingYedion(FakeYedion):
    """ידיעון שבו כל סשן שוכח את השנה אחרי מספר דפי קורס קבוע.

    ``lifetimes[n]`` = כמה דפי קורס הסשן ה-n (לפי סדר ה-POST) מגיש בשנה
    שנבחרה לפני שהוא חוזר לשנת ברירת המחדל. סשן שאין לו ערך ברשימה לא
    שוכח לעולם. דף החימום אינו נספר — הוא לא קורס.

    כשהסשן שוכח, השרת שוכח גם את הסשן עצמו (``session_started=False``): POST
    חוזר בלי חימום לא יתפוס, בדיוק כמו ב-GROUND_TRUTH §9.
    """

    def __init__(self, lifetimes: list[int], **kwargs) -> None:
        super().__init__(**kwargs)
        self.lifetimes = list(lifetimes)
        self.sessions = 0  # כמה POST-ים של החלפת שנה תפסו
        self.served = 0  # דפי קורס שהסשן הנוכחי הגיש
        self.served_codes: list[tuple[str, str]] = []  # (קוד, שנה לועזית)

    def change_year(self, year: str) -> str:
        page = super().change_year(year)
        if self.effective_year == year:
            self.sessions += 1
            self.served = 0
        return page

    def _lifetime(self) -> int | None:
        index = self.sessions - 1
        return self.lifetimes[index] if 0 <= index < len(self.lifetimes) else None

    def look_for_nose(self, code: str) -> str:
        if code != WARMUP_CODE:
            lifetime = self._lifetime()
            if lifetime is not None and self.served >= lifetime:
                self.effective_year = self.default_year
                self.session_started = False
            self.served += 1
            self.served_codes.append((code, self.effective_year))
        return super().look_for_nose(code)


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("בדיקה ניסתה לפתוח חיבור רשת אמיתי — אסור.")

    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", _refuse, raising=False)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", _refuse, raising=False)
    monkeypatch.setattr(time, "sleep", lambda s: None)


def _client(server: FakeYedion, raw_dir: Path, log: list[str] | None = None) -> tuple[YedionHTTP, FakeOpener]:
    opener = FakeOpener(server)
    client = YedionHTTP(
        year=WANT_YEAR, delay_s=0.25, raw_dir=str(raw_dir),
        log=(log.append if log is not None else None), opener=opener,
    )
    return client, opener


def _year_of(path: Path) -> str:
    return extract_page_year(path.read_text(encoding="utf-8"))


# ==========================================================================
# 1. שכחה אחת: פתיחה מחדש אחת, ניסיון חוזר של אותו קורס
# ==========================================================================
def test_a_mid_run_revert_reopens_the_session_and_retries_that_course(tmp_path):
    server = RevertingYedion(lifetimes=[3])
    client, opener = _client(server, tmp_path / "raw")
    client.open_session()

    pages = {code: client.fetch_course_resyncing(code) for code in CODES}

    want = YEAR_LABELS[WANT_YEAR]
    assert all(extract_page_year(html) == want for html in pages.values())
    assert client.session_reopens == 1
    # הקורס הרביעי חזר בתשפ"ו, ואז — ורק אז — אותו קורס נשלף שוב בתשפ"ז.
    fourth = CODES[3]
    assert server.served_codes[3] == (fourth, PREVIOUS_YEAR)
    assert server.served_codes[4] == (fourth, WANT_YEAR)
    assert [c for c, _ in server.served_codes] == [*CODES[:4], fourth, *CODES[4:]]


def test_the_reopen_runs_the_full_protocol_in_order(tmp_path):
    """חימום, POST, אימות — ורק אז הקורס שנכשל. לא POST לבד."""
    server = RevertingYedion(lifetimes=[1])
    client, opener = _client(server, tmp_path / "raw")
    client.open_session()
    client.fetch_course_resyncing(CODES[0])
    first = len(opener.calls)

    client.fetch_course_resyncing(CODES[1])

    tail = [(c.method, c.course_code) for c in opener.calls[first:]]
    assert tail == [
        ("GET", CODES[1]),        # חזר בשנה הלא נכונה
        ("GET", WARMUP_CODE),     # שלב 1: חימום
        ("POST", ""),             # שלב 2: החלפת שנה
        ("GET", WARMUP_CODE),     # שלב 3: אימות
        ("GET", CODES[1]),        # אותו קורס, שוב
    ]


def test_reopening_starts_from_an_empty_cookie_jar(tmp_path):
    from http.cookiejar import Cookie

    server = RevertingYedion(lifetimes=[])
    client, _ = _client(server, tmp_path / "raw")
    client.open_session()
    client.cookies.set_cookie(Cookie(
        0, "Yedion.MySession", "stale", None, False, "info.braude.ac.il", True,
        False, "/", True, True, None, False, None, None, {},
    ))
    assert len(client.cookies) == 1

    client.reopen_session()

    assert len(client.cookies) == 0
    assert client.session_ready
    assert client.session_reopens == 1


def test_a_session_that_never_reverts_is_never_reopened(tmp_path):
    """הריצות התקינות (שמונה מתוך תשע) לא אמורות לשלם שום בקשה נוספת."""
    server = RevertingYedion(lifetimes=[])
    client, opener = _client(server, tmp_path / "raw")
    client.open_session()
    before = len(opener.calls)

    for code in CODES:
        client.fetch_course_resyncing(code)

    assert client.session_reopens == 0
    assert len(opener.calls) - before == len(CODES)


# ==========================================================================
# 2. הדמפ של הדף שנדחה לא נשאר איפה ש-build_catalog יראה אותו
# ==========================================================================
def test_the_rejected_dump_is_moved_out_and_the_retry_takes_its_place(tmp_path):
    raw = tmp_path / "raw"
    server = RevertingYedion(lifetimes=[0])
    client, _ = _client(server, raw)
    client.open_session()

    client.fetch_course_resyncing("61753")

    in_raw = sorted(raw.glob("61753_*.html"))
    assert [p.name for p in in_raw] == ["61753_1.html"]
    assert _year_of(in_raw[0]) == YEAR_LABELS[WANT_YEAR]

    shed = sorted((raw / "wrong_year").glob("61753_*.html"))
    assert len(shed) == 1, "הדף שנדחה נשמר לפני הבדיקה ונשאר כראיה"
    assert _year_of(shed[0]) == YEAR_LABELS[PREVIOUS_YEAR]
    assert all(p.parent == raw for p in client.dumps if p.name.startswith("61753_"))


def test_scan_raw_never_counts_a_wrong_year_dump_as_intact(tmp_path):
    """הבור של 2026-09-25: הדמפים של תשפ"ו נספרו "תקינים" ופוענחו לקטלוג."""
    raw = tmp_path / "raw"
    server = RevertingYedion(lifetimes=[2, 0, 0])
    client, _ = _client(server, raw)
    client.open_session()

    with pytest.raises(SessionRevertedError):
        for code in CODES:
            client.fetch_course_resyncing(code)

    census = B.scan_raw(raw)
    want = YEAR_LABELS[WANT_YEAR]
    assert census.intact == sorted(CODES[:2])
    # שלושה ניסיונות נפסלו, ושלושתם נשמרו כראיה — אף אחד לא דרס אחר.
    assert len(list((raw / "wrong_year").glob(f"{CODES[2]}_*.html"))) == 3
    for code in census.intact:
        for path in raw.glob(f"{code}_*.html"):
            assert _year_of(path) == want


# ==========================================================================
# 3. סשן שממשיך לשכוח: עוצרים מוקדם
# ==========================================================================
def test_a_session_that_keeps_reverting_stops_after_the_retry_limit(tmp_path):
    server = RevertingYedion(lifetimes=[2, 0, 0, 0, 0, 0])
    client, opener = _client(server, tmp_path / "raw")
    client.open_session()
    client.fetch_course_resyncing(CODES[0])
    client.fetch_course_resyncing(CODES[1])

    with pytest.raises(SessionRevertedError) as info:
        client.fetch_course_resyncing(CODES[2])

    assert isinstance(info.value, YearMismatchError), "מי שתופס כל בעיית שנה יתפוס גם אותה"
    assert client.session_reopens == yedion_http.MAX_RESYNCS_PER_COURSE
    # ניסיון ראשון + ניסיון אחרי כל פתיחה — ולא דף אחד מעבר לזה.
    tries = [c for c, _ in server.served_codes if c == CODES[2]]
    assert len(tries) == 1 + yedion_http.MAX_RESYNCS_PER_COURSE


def test_the_run_wide_cap_stops_a_session_that_reverts_every_page(tmp_path):
    """כל סשן מחזיק דף אחד. כל קורס מצליח בניסיון השני — אבל זה לא מצב
    שממשיכים בו שעה. אחרי ``MAX_SESSION_REOPENS`` עוצרים."""
    cap = yedion_http.MAX_SESSION_REOPENS
    server = RevertingYedion(lifetimes=[1] * (cap + 5))
    client, _ = _client(server, tmp_path / "raw")
    client.open_session()
    codes = [str(70000 + i) for i in range(cap + 5)]

    fetched = []
    with pytest.raises(SessionRevertedError):
        for code in codes:
            client.fetch_course_resyncing(code)
            fetched.append(code)

    assert client.session_reopens == cap
    assert fetched == codes[: cap + 1]


def test_no_wrong_year_page_is_ever_returned(tmp_path):
    """בדיקת השנה לא התרככה: כל מה שחוזר הוא תשפ"ז, או שנזרקת חריגה."""
    server = RevertingYedion(lifetimes=[1, 2, 0, 3, 0, 0, 0])
    client, _ = _client(server, tmp_path / "raw")
    client.open_session()
    want = YEAR_LABELS[WANT_YEAR]
    for code in [str(71000 + i) for i in range(30)]:
        try:
            html = client.fetch_course_resyncing(code)
        except SessionRevertedError:
            break
        assert extract_page_year(html) == want


def test_fetch_course_itself_is_unchanged(tmp_path):
    """‏``fetch_course`` עדיין זורק על דף בשנה אחרת, בלי לנסות שוב."""
    server = RevertingYedion(lifetimes=[0])
    client, opener = _client(server, tmp_path / "raw")
    client.open_session()
    before = len(opener.calls)
    with pytest.raises(YearMismatchError) as info:
        client.fetch_course("61753")
    assert not isinstance(info.value, SessionRevertedError)
    assert len(opener.calls) - before == 1
    assert client.session_reopens == 0


# ==========================================================================
# 4. build_catalog: הלולאה הלילית
# ==========================================================================
@pytest.fixture
def nightly(monkeypatch, tmp_path):
    """‏build_catalog מול ידיעון מזויף, בלי רשת ובלי לגעת ב-data/."""
    raw = tmp_path / "raw"
    out = tmp_path / "catalog"
    monkeypatch.setattr(B, "RAW_DIR", raw)
    monkeypatch.setattr(B, "CATALOG_DIR", out)
    monkeypatch.setattr(B, "CATALOG_PATH", out / "catalog.jsonl")
    monkeypatch.setattr(B, "META_PATH", out / "catalog.meta.json")

    def _use(server: FakeYedion) -> FakeOpener:
        opener = FakeOpener(server)
        monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: opener)
        return opener

    return _use, raw, out


def test_fetch_missing_survives_a_mid_run_revert(nightly, capsys):
    use, raw, _ = nightly
    server = RevertingYedion(lifetimes=[3])
    use(server)
    codes = [str(72000 + i) for i in range(12)]

    ok, failed = B.fetch_missing(codes, WANT_YEAR, 0)

    assert (ok, failed) == (12, 0)
    assert "YearMismatchError" not in capsys.readouterr().out
    assert B.scan_raw(raw).intact == codes


def test_build_stops_early_with_exit_5_and_writes_nothing(nightly, monkeypatch, capsys):
    use, raw, out = nightly
    server = RevertingYedion(lifetimes=[3, 0, 0, 0, 0, 0, 0])
    opener = use(server)
    codes = [str(73000 + i) for i in range(40)]
    monkeypatch.setattr(B, "load_catalog_index", lambda: {c: {} for c in codes})

    rc = B.main(["--year", WANT_YEAR, "--pace", "0", "--out", str(out)])

    assert rc == B.EXIT_SESSION_REVERTED == 5
    assert not (out / "catalog.jsonl").exists()
    assert not (out / "catalog.meta.json").exists()
    course_gets = [c for c in opener.calls
                   if c.method == "GET" and c.course_code not in ("", WARMUP_CODE)]
    # 3 טובים + הרביעי: ניסיון ראשון ועוד שניים. לא ארבעים.
    assert len(course_gets) == 3 + 1 + yedion_http.MAX_RESYNCS_PER_COURSE
    assert B.scan_raw(raw).intact == codes[:3]
    assert "שער האיכות" not in capsys.readouterr().out
