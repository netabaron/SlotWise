"""כל יום שיש בו שיעור נספר ביעד הימים (הוחלט 2026-10-09).

‏docs/DESIGN.md → Lecturers, "How a ranking chooses", פריט 1: גם יום שכל
השיעורים בו בלי חובת נוכחות נספר. חובת הנוכחות קובעת רק אילו שיעורים מותר
לחפוף. לכן השורה "ביום ה׳ אין שיעורים עם חובת נוכחות, ולכן הוא לא נספר ביעד
הימים." הוסרה מדף התוצאה (פריט 4), ואיתה ``skippable_days`` ב-‎/api/solve‎.
הקובץ הזה מחליף את ``test_attendance_free_day_line_browser.py``, שנמחק
באישור (2026-10-09).

הבדיקות של ה-API ושל הדפדפן רצות על מסד ה-fixture
(‏``scripts/seed_dev_data.py --fixture``), כמו ב-CI: הנדסת תוכנה, שנה ג׳,
סמסטר א׳, ששת הקורסים המומלצים. נמדד 2026-10-09: כש-61759 תרגול ו-61832
תרגול בלי חובת נוכחות, ביעד 3, חלופה 1 משתמשת ב-4 ימים, ויום ה׳ שלה כולו
שני התרגולים האלה — לפני ההחלטה הוא לא נספר (3 ימים, אפס מעל היעד); עכשיו
הוא נספר (יום אחד מעל היעד).
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import scheduler  # noqa: E402
from models import KIND_LECTURE, KIND_TUTORIAL, Course, Group, Meeting  # noqa: E402
from src.web.api import create_app  # noqa: E402

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
SCHEDULE = STRINGS["app"]["schedule"]

CODES = ["11069", "61756", "61757", "62027", "61759", "61832"]
TUTORIAL = "תרגול"
ONE = {"61832": {TUTORIAL: False}}
TWO = {"61759": {TUTORIAL: False}, "61832": {TUTORIAL: False}}
THURSDAY = 5


# --------------------------------------------------------------------------
# 1. המנוע — נתונים סינתטיים זעירים
# --------------------------------------------------------------------------
def _grp(code, gid, kind, day, start, end):
    return Group(
        course_code=code,
        group_id=gid,
        kind=kind,
        lecturer="ד\"ר איקס",
        meetings=[Meeting(day=day, start=start, end=end)],
    )


def test_a_day_of_waived_lessons_counts_toward_the_target():
    """תרגול בלי חובת נוכחות, לבד ביום ב׳ — או ביום א׳ אחרי חלון ארוך.

    לפני ההחלטה יום ב׳ לא נספר, ולכן שתי האפשרויות עמדו ביעד של יום אחד
    וזו בלי החלון ניצחה. עכשיו יום ב׳ הוא יום שני מעל היעד, וההכרעה היא
    לפי הימים: התרגול עובר ליום א׳, למרות החלון.
    """
    lecture = _grp("90001", "L", KIND_LECTURE, 1, 510, 630)
    alone = _grp("90001", "T1", KIND_TUTORIAL, 2, 510, 630)
    same_day = _grp("90001", "T2", KIND_TUTORIAL, 1, 990, 1110)
    course = Course(code="90001", name="קורס", credits=1.0, groups=[lecture, alone, same_day])
    prefs = scheduler.Preferences(
        target_days=1, attendance={"90001": {KIND_TUTORIAL: False}}
    )

    found = scheduler.solve([course], prefs, top_n=2)

    assert found[0].selection.group_for("90001", KIND_TUTORIAL).group_id == "T2"
    assert found[0].days_over_target == 0
    second = found[1]
    assert second.selection.group_for("90001", KIND_TUTORIAL).group_id == "T1"
    assert second.days_count == 2
    assert second.days_over_target == 1


def test_the_exemption_is_gone_from_the_engine():
    assert not hasattr(scheduler, "attendance_free_days")
    sel = scheduler.solve(
        [Course(code="90002", name="קורס", credits=1.0,
                groups=[_grp("90002", "L", KIND_LECTURE, 1, 510, 630)])],
        scheduler.Preferences(),
    )[0]
    assert not hasattr(sel, "skippable_days")
    assert not hasattr(sel, "effective_days")


# --------------------------------------------------------------------------
# 2. ההעתק — אין עוד שורה להסביר
# --------------------------------------------------------------------------
def test_the_line_is_gone_from_strings_json():
    for key in ("freeDayLine", "freeDaysLine", "freeDay", "freeDaysSep", "freeDaysLast"):
        assert key not in SCHEDULE, key
    blob = json.dumps(STRINGS, ensure_ascii=False)
    assert "לא נספר ביעד" not in blob
    assert "לא נספרים ביעד" not in blob


# --------------------------------------------------------------------------
# 3. ה-API, על מסד ה-fixture
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    return create_app(config={"allow_network": False}, serve_ui=False).test_client()


@pytest.mark.parametrize("attendance", [ONE, TWO], ids=["one", "two"])
@pytest.mark.parametrize("target", [3, 4])
def test_the_api_counts_every_day(client, attendance, target):
    res = client.post(
        "/api/solve",
        json={"codes": CODES, "semester": "א", "target_days": target, "attendance": attendance},
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    schedules = res.get_json()["schedules"]
    assert schedules
    for sch in schedules:
        assert "skippable_days" not in sch, sorted(sch)
        assert sch["days_over_target"] == max(0, sch["days_count"] - target), sch


# --------------------------------------------------------------------------
# 4. דף התוצאה
# --------------------------------------------------------------------------
sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright


@pytest.fixture(scope="module")
def server():
    from werkzeug.serving import make_server

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = make_server(
        "127.0.0.1", port, create_app(config={"allow_network": False}), threaded=True
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        try:
            instance = pw.chromium.launch()
        except Exception as exc:  # אין דפדפן מותקן — לא כישלון של הקוד
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            yield instance
        finally:
            instance.close()


def _with(attendance, target):
    """מוסיף לבקשה את חובת הנוכחות ואת היעד — כאילו נבחרו בשלבים עצמם."""

    def handler(route):
        body = json.loads(route.request.post_data or "{}")
        body["attendance"] = attendance
        body["target_days"] = target
        route.continue_(post_data=json.dumps(body, ensure_ascii=False))

    return handler


SUMMARY = """() => {
  const box = document.getElementById('schedule-summary');
  const days = box.querySelector('.stat-pill[data-stat="days"]');
  const lost = box.querySelector('.fit-lost');
  return {
    free: document.querySelectorAll('.fit-free-days').length,
    days: days ? days.textContent : null,
    lost: lost ? lost.textContent : null,
    text: document.body.textContent,
  };
}"""


def test_a_waived_day_reads_as_a_day_over_the_target(browser, server):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/api/solve", _with(TWO, 3))
    try:
        page.goto(server)
        page.wait_for_timeout(2500)
        page.select_option("#select-program", "הנדסת תוכנה")
        page.select_option("#select-year", "3")
        page.select_option("#select-term", "א")
        page.wait_for_timeout(2500)
        page.click("#step-year-next")
        page.click("#btn-restore-recommended")
        page.wait_for_selector("#alt-cards .alt-card", timeout=20000)
        page.wait_for_timeout(700)
        page.click('#alt-cards .alt-card[data-rank="1"]')
        page.wait_for_timeout(300)

        sch = page.evaluate("() => window.slotwise.getRuntime().solve.schedules[0]")
        got = page.evaluate(SUMMARY)
    finally:
        ctx.close()

    # יום ה׳ של חלופה 1 הוא שני התרגולים שסומנו בלי חובת נוכחות, ותו לא.
    on_thursday = {
        (p["code"], p["kind"])
        for p in sch["picks"]
        for m in p["meetings"]
        if m["day"] == THURSDAY
    }
    assert on_thursday and all(
        kind == TUTORIAL and code in TWO for code, kind in on_thursday
    ), on_thursday
    assert sch["days_count"] == 4, sch["days"]
    assert sch["days_over_target"] == 1, sch
    assert "skippable_days" not in sch

    assert got["free"] == 0, got["free"]
    assert got["days"].startswith("4 "), got["days"]
    assert got["lost"] and SCHEDULE["lost"]["days"] in got["lost"], got["lost"]
    assert "לא נספר ביעד" not in got["text"]
    assert errors == [], errors
