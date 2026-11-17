# -*- coding: utf-8 -*-
"""
‏``scripts/check_syllabi.py`` — הבדיקה הלילית של קובצי הסילבוס (SPEC_LINKS.md, Feature 2).

אף בקשה אמיתית: ``probe`` מוחלף, ‏``sleep`` מוחלף, ו-``_OPENER`` מוחלף במי
שזורק בכל בדיקה. נבדק: סדר העדיפויות, התקציב, הקצב, כישלון שאינו נרשם, עצירה
אחרי חמישה כישלונות רצופים, בדיקה חוזרת של ``exists`` אחרי 30 יום, שנה שעברה
סופית, מחיקת קודים שיצאו מהקטלוג, כתיבה אטומית, וקודי היציאה.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location("check_syllabi", ROOT / "scripts" / "check_syllabi.py")
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)

import syllabus as syllabus_mod  # noqa: E402

TODAY = dt.date(2026, 11, 17)
YEAR, LAST = "2027", "2026"


@pytest.fixture(autouse=True)
def no_real_requests(monkeypatch):
    class Refuse:
        def open(self, *_a, **_k):
            raise AssertionError("בקשה אמיתית מתוך בדיקה")

    monkeypatch.setattr(cs, "_OPENER", Refuse())


def _data(years: dict | None = None) -> dict:
    return {"schema": "slotwise/syllabi", "version": 1, "years": years or {}}


def _rec(status: str, checked: str) -> dict:
    return {"status": status, "checked": checked}


# ---------------------------------------------------------------------------
# סדר העדיפויות
# ---------------------------------------------------------------------------
def test_plan_order():
    data = _data({
        YEAR: {
            "11001": _rec("missing", "2026-11-10"),
            "11002": _rec("missing", "2026-11-01"),   # ישן יותר — קודם
            "11003": _rec("exists", "2026-10-01"),    # לפני 47 יום
            "11004": _rec("exists", "2026-11-10"),    # טרי — לא נבדק
        },
        LAST: {"11001": _rec("exists", "2026-11-01"), "11002": _rec("missing", "2026-11-01")},
    })
    codes = ["11001", "11002", "11003", "11004", "11005"]
    tasks = cs.plan(data, codes, YEAR, today=TODAY, recheck_days=30)
    assert tasks == [
        (YEAR, "11005"),                    # 1. השנה, לא נבדק
        (YEAR, "11002"), (YEAR, "11001"),   # 2. השנה, missing — הישן קודם
        (LAST, "11003"), (LAST, "11004"), (LAST, "11005"),  # 3. שנה שעברה, לא נבדק
        (YEAR, "11003"),                    # 4. השנה, exists ישן מ-30 יום
    ]


def test_last_year_is_final_once_recorded():
    data = _data({LAST: {"11001": _rec("missing", "2020-01-01")}, YEAR: {"11001": _rec("exists", TODAY.isoformat())}})
    assert cs.plan(data, ["11001"], YEAR, today=TODAY) == []


def test_exists_is_rechecked_only_after_30_days():
    fresh = _data({YEAR: {"1": _rec("exists", "2026-10-18")}, LAST: {"1": _rec("exists", "x")}})
    stale = _data({YEAR: {"1": _rec("exists", "2026-10-17")}, LAST: {"1": _rec("exists", "x")}})
    # קוד בן ספרה אחת אינו קוד תקין לשרת, אבל plan אינו מסנן — הסינון ב-main.
    assert cs.plan(fresh, ["1"], YEAR, today=TODAY) == []
    assert cs.plan(stale, ["1"], YEAR, today=TODAY) == [(YEAR, "1")]


# ---------------------------------------------------------------------------
# הריצה: תקציב, קצב, כישלונות
# ---------------------------------------------------------------------------
def test_budget_and_pace():
    data = _data()
    tasks = [(YEAR, str(11000 + i)) for i in range(10)]
    slept, asked = [], []

    def fetch(url):
        asked.append(url)
        return "exists"

    counts = cs.run(data, tasks, budget=4, pace=9.0, max_failures=5, today=TODAY,
                    fetch=fetch, sleep=slept.append, log=lambda m: None)
    assert counts["checked"] == 4 and len(asked) == 4
    assert slept == [9.0, 9.0, 9.0], "המתנה לפני כל בקשה חוץ מהראשונה"
    assert asked[0] == "https://info.braude.ac.il/info/2027/0011000.pdf"
    assert set(data["years"][YEAR]) == {"11000", "11001", "11002", "11003"}
    assert data["years"][YEAR]["11000"] == _rec("exists", "2026-11-17")


def test_a_failure_is_not_recorded_and_keeps_the_previous_answer():
    data = _data({YEAR: {"11001": _rec("missing", "2026-11-01")}})
    counts = cs.run(data, [(YEAR, "11001"), (YEAR, "11002")], budget=10, pace=0,
                    max_failures=5, today=TODAY, fetch=lambda url: "failed",
                    sleep=lambda s: None, log=lambda m: None)
    assert counts["failed"] == 2
    assert data["years"][YEAR] == {"11001": _rec("missing", "2026-11-01")}


def test_stops_after_five_failures_in_a_row():
    answers = iter(["exists", "failed", "failed", "missing", "failed", "failed",
                    "failed", "failed", "failed", "exists"])
    data = _data()
    tasks = [(YEAR, str(11000 + i)) for i in range(10)]
    counts = cs.run(data, tasks, budget=10, pace=0, max_failures=5, today=TODAY,
                    fetch=lambda url: next(answers), sleep=lambda s: None, log=lambda m: None)
    assert counts["stopped_early"] == 1
    assert counts["checked"] == 9          # הרצף נשבר ב-missing, ואז חמישה ברצף
    assert data["years"][YEAR] == {
        "11000": _rec("exists", "2026-11-17"),
        "11003": _rec("missing", "2026-11-17"),
    }


# ---------------------------------------------------------------------------
# מחיקה, כתיבה, main
# ---------------------------------------------------------------------------
def test_prune_drops_codes_that_left_the_catalog_and_old_years():
    data = _data({YEAR: {"11001": _rec("exists", "x"), "99999": _rec("exists", "x")},
                  LAST: {"99999": _rec("exists", "x")},
                  "2025": {"11001": _rec("exists", "x")}})
    dropped = cs.prune(data, ["11001"], YEAR)
    assert dropped == 1
    assert set(data["years"]) == {YEAR, LAST}
    assert set(data["years"][YEAR]) == {"11001"}
    assert set(data["years"][LAST]) == {"99999"}, "שנה שעברה סופית — לא נמחקת"


def test_render_round_trips_through_the_servers_parser():
    data = _data({YEAR: {"61757": _rec("exists", "2026-11-17"), "11092": _rec("missing", "2026-11-17")},
                  LAST: {"61757": _rec("exists", "2026-11-17")}})
    data["updated_at"] = "2026-11-17T01:00:00Z"
    text = cs.render(data)
    assert syllabus_mod.parse(text)["years"] == data["years"]
    assert text.count("\n") > 6, "שורה לכל קורס — diff קריא"


def _catalog(tmp_path: Path, codes=("11001", "11002", "11003"), year="2027") -> Path:
    d = tmp_path / "catalog"
    d.mkdir()
    (d / "catalog.meta.json").write_text(
        json.dumps({"year_gregorian": year, "codes": list(codes)}), encoding="utf-8")
    return d


def test_main_writes_atomically_and_exits_0(tmp_path, monkeypatch):
    d = _catalog(tmp_path)
    monkeypatch.setattr(cs, "probe", lambda url, timeout=0: "missing" if "0011002" in url else "exists")
    monkeypatch.setattr(cs.time, "sleep", lambda s: None)
    rc = cs.main(["--dir", str(d), "--budget", "100", "--pace", "9"])
    assert rc == cs.EXIT_OK
    out = syllabus_mod.parse((d / "syllabi.json").read_text(encoding="utf-8"))
    assert out["years"][YEAR]["11002"]["status"] == "missing"
    assert out["years"][YEAR]["11001"]["status"] == "exists"
    assert set(out["years"][LAST]) == {"11001", "11002", "11003"}
    assert not list(d.glob("*.tmp")), "קובץ זמני נשאר"


def test_main_exit_3_still_saves_what_it_learned(tmp_path, monkeypatch):
    d = _catalog(tmp_path, codes=[str(11000 + i) for i in range(8)])
    answers = iter(["exists"] + ["failed"] * 20)
    monkeypatch.setattr(cs, "probe", lambda url, timeout=0: next(answers))
    monkeypatch.setattr(cs.time, "sleep", lambda s: None)
    rc = cs.main(["--dir", str(d), "--budget", "100", "--max-failures", "5"])
    assert rc == cs.EXIT_STOPPED_EARLY
    out = syllabus_mod.parse((d / "syllabi.json").read_text(encoding="utf-8"))
    assert out["years"][YEAR] == {"11000": {"status": "exists", "checked": out["years"][YEAR]["11000"]["checked"]}}


def test_main_bad_input_exits_1_and_touches_nothing(tmp_path, monkeypatch):
    d = tmp_path / "empty"
    d.mkdir()
    monkeypatch.setattr(cs, "probe", lambda *a, **k: pytest.fail("לא אמורה לצאת בקשה"))
    assert cs.main(["--dir", str(d)]) == cs.EXIT_BAD_INPUT
    assert not (d / "syllabi.json").exists()
    (tmp_path / "x").mkdir()
    d2 = _catalog(tmp_path / "x", year="27")  # שנה לא תקינה
    assert cs.main(["--dir", str(d2)]) == cs.EXIT_BAD_INPUT
    assert not (d2 / "syllabi.json").exists()


# ---------------------------------------------------------------------------
# probe — סיווג תשובות (opener מזויף)
# ---------------------------------------------------------------------------
class _Res:
    def __init__(self, status, ctype):
        self.status = status
        self.headers = {"Content-Type": ctype}

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Opener:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []

    def open(self, req, timeout=None):
        self.requests.append((req, timeout))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


@pytest.mark.parametrize(
    "outcome, expected",
    [
        (_Res(200, "application/pdf"), "exists"),
        (_Res(200, "text/html"), "failed"),
        (_Res(204, "application/pdf"), "failed"),
        (urllib.error.HTTPError("u", 404, "nf", {}, None), "missing"),
        (urllib.error.HTTPError("u", 500, "err", {}, None), "failed"),
        (urllib.error.HTTPError("u", 302, "moved", {}, None), "failed"),
        (TimeoutError("slow"), "failed"),
        (urllib.error.URLError("dns"), "failed"),
        (ConnectionResetError("reset"), "failed"),
    ],
)
def test_probe_classification(monkeypatch, outcome, expected):
    opener = _Opener(outcome)
    monkeypatch.setattr(cs, "_OPENER", opener)
    assert cs.probe("https://info.braude.ac.il/info/2027/0061757.pdf", timeout=10) == expected
    (req, timeout), = opener.requests
    assert req.get_method() == "HEAD"
    assert timeout == 10
    assert not req.has_header("Cookie")
    assert "SlotWise" in req.get_header("User-agent")


def test_the_real_opener_has_no_cookies_and_follows_no_redirects():
    import urllib.request

    handlers = cs.urllib.request.build_opener(cs._NoRedirect()).handlers
    assert not any(isinstance(h, urllib.request.HTTPCookieProcessor) for h in handlers)
    assert any(isinstance(h, cs._NoRedirect) for h in handlers)


# ---------------------------------------------------------------------------
# הסיכום — ליומן ול-$GITHUB_STEP_SUMMARY
# ---------------------------------------------------------------------------
def test_summary_counts_per_year_and_lists_failed_codes():
    answers = {"0011001": "exists", "0011002": "missing", "0011003": "failed"}
    data = _data()
    tasks = [(YEAR, "11001"), (YEAR, "11002"), (YEAR, "11003"), (LAST, "11001"), (LAST, "11003")]

    def fetch(url):
        code = url.rsplit("/", 1)[1][:-4]
        return answers[code] if f"/{YEAR}/" in url else ("failed" if code == "0011003" else "exists")

    counts = cs.run(data, tasks, budget=10, pace=0, max_failures=5, today=TODAY,
                    fetch=fetch, sleep=lambda s: None, log=lambda m: None)
    assert counts["by_year"][YEAR] == {"checked": 3, "exists": 1, "missing": 1, "failed": 1}
    assert counts["by_year"][LAST] == {"checked": 2, "exists": 1, "missing": 0, "failed": 1}
    assert counts["failed_codes"] == [(YEAR, "11003"), (LAST, "11003")]

    text = cs.summary(counts, data, ["11001", "11002", "11003", "11004"], YEAR)
    assert f"| {YEAR} | 3 | 1 | 1 | 1 | 2 |" in text     # 11003, 11004 עוד לא נבדקו
    assert f"| {LAST} | 2 | 1 | 0 | 1 | 3 |" in text
    assert "| **total** | **5** | **2** | **1** | **2** |" in text
    assert f"- {YEAR}: 11003" in text and f"- {LAST}: 11003" in text
    assert "Stopped early" not in text


def test_summary_says_no_failures_and_reports_an_early_stop():
    clean = cs.summary({"checked": 0, "by_year": {}, "failed_codes": []}, _data(), ["11001"], YEAR)
    assert "No failures." in clean
    stopped = cs.summary({"checked": 5, "failed": 5, "stopped_early": 1, "by_year": {},
                          "failed_codes": [(YEAR, str(11000 + i)) for i in range(5)]},
                         _data(), ["11001"], YEAR, max_failures=5)
    assert "Stopped early" in stopped and "5 failures in a row" in stopped


def test_main_writes_the_summary_to_the_log_and_the_step_summary(tmp_path, monkeypatch, capsys):
    d = _catalog(tmp_path)
    step = tmp_path / "step_summary.md"
    step.write_text("earlier step\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step))
    monkeypatch.setattr(cs, "probe", lambda url, timeout=0: "failed" if "0011002" in url else "exists")
    monkeypatch.setattr(cs.time, "sleep", lambda s: None)
    assert cs.main(["--dir", str(d), "--budget", "100"]) == cs.EXIT_OK
    log = capsys.readouterr().out
    written = step.read_text(encoding="utf-8")
    assert written.startswith("earlier step\n"), "מוסיף, לא דורס"
    for text in (log, written):
        assert "### Syllabus check" in text
        assert f"| {YEAR} | 3 | 2 | 0 | 1 | 1 |" in text
        assert f"- {YEAR}: 11002" in text and f"- {LAST}: 11002" in text


def test_without_github_actions_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    cs.write_step_summary("x")  # אין יעד — ואין חריגה
    d = tmp_path / "empty"
    d.mkdir()
    step = tmp_path / "step.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step))
    assert cs.main(["--dir", str(d)]) == cs.EXIT_BAD_INPUT
    assert "Did not run" in step.read_text(encoding="utf-8")
