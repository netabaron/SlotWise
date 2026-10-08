"""דף התוצאה: שורה אחת מתחת לנתונים כשבחלופה הנבחרת יש יום בלי חובת נוכחות (2026-10-08).

DESIGN.md, "Results page", פריט 4: יום שכל השיעורים בו בלי חובת נוכחות אינו
נספר ביעד הימים (``scheduler.attendance_free_days()``), ולכן מערכת של 5 ימים
יכולה לעמוד ביעד של 4. מיד מתחת לשבבים מופיעה השורה "ביום ה׳ אין שיעורים עם
חובת נוכחות, ולכן הוא לא נספר ביעד הימים." (ברבים: "בימים ב׳ ו-ה׳ …"). שבב
הימים ממשיך לספור כל יום שבמערכת. השורה מתחלפת עם החלופה הנבחרת, ואינה
מופיעה כשאין יום כזה.

רץ על מסד ה-fixture (‏``scripts/seed_dev_data.py --fixture``), כמו ב-CI:
הנדסת תוכנה, שנה ג׳, סמסטר א׳, ששת הקורסים המומלצים. נמדד 2026-10-08:

* ‏61832 תרגול בלי חובת נוכחות — חלופות 1–2 משתמשות בימים א–ה (5), ויום ה׳
  כולו בלי חובת נוכחות: 4 ימים בפועל, יעד 4, ‏min_days 4. חלופות 3–5
  משתמשות ב-4 ימים בלי יום כזה.
* ‏61759 תרגול ו-61832 תרגול בלי חובת נוכחות — חלופה 1: ימים ב׳ ו-ה׳;
  חלופה 4: רק ה׳.
* בלי שום שינוי בחובת הנוכחות — אין יום כזה באף חלופה.

ההגדרה של חובת הנוכחות מוזרקת לגוף הבקשה אל ‎/api/solve‎; התשובה עצמה היא
של השרת, ולא נוגעים בה.
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

from src.web.api import create_app  # noqa: E402

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))["app"]["schedule"]
ONE_DAY = "ביום ה׳ אין שיעורים עם חובת נוכחות, ולכן הוא לא נספר ביעד הימים."
TWO_DAYS = "בימים ב׳ ו-ה׳ אין שיעורים עם חובת נוכחות, ולכן הם לא נספרים ביעד הימים."

TUTORIAL = "תרגול"
ONE = {"61832": {TUTORIAL: False}}
TWO = {"61759": {TUTORIAL: False}, "61832": {TUTORIAL: False}}

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402


def test_the_copy_lives_in_strings_json():
    assert STRINGS["freeDayLine"].replace("{day}", "ה׳") == ONE_DAY
    days = "ב׳" + STRINGS["freeDaysLast"] + "ה׳"
    assert STRINGS["freeDaysLine"].replace("{days}", days) == TWO_DAYS
    assert STRINGS["freeDay"].replace("{day}", "ה") == "ה׳"


@pytest.fixture(scope="module")
def server():
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


def _with_attendance(attendance):
    """מוסיף לבקשה את ההגדרה — כאילו הסטודנט/ית כיבו את המתג בשלב המרצים."""

    def handler(route):
        body = json.loads(route.request.post_data or "{}")
        if attendance:
            body["attendance"] = attendance
        route.continue_(post_data=json.dumps(body, ensure_ascii=False))

    return handler


def _open(browser, server, attendance):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = ctx.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    page.route("**/api/solve", _with_attendance(attendance))
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
    return ctx, page


def _select(page, rank):
    page.click(f'#alt-cards .alt-card[data-rank="{rank}"]')
    page.wait_for_timeout(300)


SUMMARY = """() => {
  const box = document.getElementById('schedule-summary');
  const kids = [...box.children];
  const line = box.querySelector('.fit-free-days');
  const days = box.querySelector('.stat-pill[data-stat="days"]');
  return {
    count: box.querySelectorAll('.fit-free-days').length,
    text: line ? line.textContent : null,
    index: line ? kids.indexOf(line) : -1,
    pills: kids.findIndex(k => k.classList.contains('stat-pills')),
    days: days ? days.textContent : null,
  };
}"""


@pytest.fixture(scope="module")
def one_day(browser, server):
    ctx, pg = _open(browser, server, ONE)
    try:
        yield pg
    finally:
        ctx.close()


def test_the_line_names_the_day_directly_under_the_pills(one_day):
    _select(one_day, 1)
    sch = one_day.evaluate("() => window.slotwise.getRuntime().solve.schedules[0]")
    assert sch["days"] == [1, 2, 3, 4, 5], sch["days"]
    assert sch["skippable_days"] == [5], sch.get("skippable_days")
    got = one_day.evaluate(SUMMARY)
    assert got["count"] == 1, got
    assert got["text"] == ONE_DAY, got
    assert got["index"] == got["pills"] + 1, got
    # שבב הימים ממשיך לספור כל יום שבמערכת, כולל ה׳.
    assert got["days"].startswith("5 "), got
    assert one_day.errors == [], one_day.errors  # type: ignore[attr-defined]


def test_the_line_follows_the_selected_alternative(one_day):
    _select(one_day, 3)
    sch = one_day.evaluate("() => window.slotwise.getRuntime().solve.schedules[2]")
    assert sch["skippable_days"] == [], sch
    assert one_day.evaluate(SUMMARY)["count"] == 0
    _select(one_day, 1)
    assert one_day.evaluate(SUMMARY)["text"] == ONE_DAY
    _select(one_day, 5)
    assert one_day.evaluate(SUMMARY)["count"] == 0


def test_several_days_read_as_one_line(browser, server):
    ctx, pg = _open(browser, server, TWO)
    try:
        _select(pg, 1)
        got = pg.evaluate(SUMMARY)
        assert got["count"] == 1 and got["text"] == TWO_DAYS, got
        _select(pg, 4)
        assert pg.evaluate(SUMMARY)["text"] == ONE_DAY
    finally:
        ctx.close()


def test_no_line_when_every_day_has_mandatory_attendance(browser, server):
    ctx, pg = _open(browser, server, None)
    try:
        schedules = pg.evaluate("() => window.slotwise.getRuntime().solve.schedules")
        assert schedules and all(s["skippable_days"] == [] for s in schedules), schedules
        for rank in range(1, len(schedules) + 1):
            _select(pg, rank)
            assert pg.evaluate(SUMMARY)["count"] == 0, rank
    finally:
        ctx.close()
