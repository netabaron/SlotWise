"""דף התוצאה: שורה אחת מתחת לנתונים כשבחלופה הנבחרת יש קבוצה מלאה (2026-10-02).

DESIGN.md, "Results page", פריט 4: כשבחלופה הנבחרת יש לפחות קבוצה מלאה אחת —
``status_note`` שהוא בדיוק "הקורס מלא", עם מועד קבוע או בלעדיו — מופיעה מתחת
לנתונים השורה "חלק מהקבוצות במערכת הזו מלאות, ואי אפשר להירשם אליהן." היא
מתחלפת עם החלופה הנבחרת, ואינה מופיעה כשאין בחלופה קבוצה מלאה.
שני המצבים האחרים של הידיעון אינם מפעילים אותה.

**שום דבר כאן אינו תלוי ב-data/db המקומי** (DEFERRED.md): תשובות ‎/api/solve‎
מיורטות ומקבלות מצבים ידועים לכל חלופה, כי אילו קבוצות מלאות תלוי בקטלוג.
"""

from __future__ import annotations

import json
import re
import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src.web.api import create_app  # noqa: E402

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
LINE = STRINGS["app"]["schedule"]["fullGroupsLine"]
APP_JS = (ROOT / "src" / "web" / "static" / "app.js").read_text(encoding="utf-8")

#: הערך שהידיעון כותב לקבוצה מלאה — כפי שהוא מוגדר ב-app.js.
FULL = re.search(r'var FULL_STATUS = "([^"]+)";', APP_JS).group(1)
REPEATERS = "מיועד לחוזרים"
WAITLIST = "בקורס זה קיימת רשימת המתנה"

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402


def test_the_copy_is_one_plain_line_with_no_placeholder():
    assert LINE == "חלק מהקבוצות במערכת הזו מלאות, ואי אפשר להירשם אליהן."
    assert "{" not in LINE


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


def _mutate(schedules):
    """מצב ידוע לכל חלופה, בלי קשר למה שבקטלוג.

    1 — קבוצה מלאה אחת (עם מועד).   2 — אין שום מצב.
    3 — קבוצה מלאה אחת בלי מועד קבוע.   4 — רק שני המצבים האחרים.
    5 — קבוצה מלאה אחת, ובלי שום רכיב ניקוד שלילי: משפט "מה פחות טוב" לא
        נבנה, והשורה נכנסת בענף השני של buildStats — מיד אחרי השבבים.
    """
    for sch in schedules:
        for p in sch["picks"]:
            p["status_note"] = ""
    timed = [p for p in schedules[0]["picks"] if p.get("meetings")]
    timed[0]["status_note"] = FULL
    if len(schedules) > 2:
        pick = schedules[2]["picks"][0]
        pick["meetings"] = []
        pick["status_note"] = FULL
    if len(schedules) > 3:
        picks = schedules[3]["picks"]
        picks[0]["status_note"] = REPEATERS
        picks[-1]["status_note"] = WAITLIST
    if len(schedules) > 4:
        schedules[4]["picks"][0]["status_note"] = FULL
        schedules[4]["breakdown"] = {}


def _handler(route):
    response = route.fetch()
    data = response.json()
    if data.get("schedules"):
        _mutate(data["schedules"])
    route.fulfill(
        status=response.status,
        headers={"content-type": "application/json"},
        body=json.dumps(data, ensure_ascii=False),
    )


def _open(browser, server, scheme="light"):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, color_scheme=scheme)
    page = ctx.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    page.route("**/api/solve", _handler)
    page.goto(server)
    page.wait_for_timeout(2500)
    page.select_option("#select-program", "הנדסת תוכנה")
    page.select_option("#select-year", "3")
    page.select_option("#select-term", "א")
    page.wait_for_timeout(2500)
    page.click("#btn-restore-recommended")
    page.wait_for_selector("#alt-cards .alt-card", timeout=20000)
    page.wait_for_timeout(700)
    return ctx, page


@pytest.fixture(scope="module")
def page(browser, server):
    ctx, pg = _open(browser, server)
    try:
        yield pg
    finally:
        ctx.close()


def _select(page, rank):
    page.click(f'#alt-cards .alt-card[data-rank="{rank}"]')
    page.wait_for_timeout(300)


SUMMARY = """() => {
  const box = document.getElementById('schedule-summary');
  const kids = [...box.children];
  const line = box.querySelector('.fit-full');
  return {
    count: box.querySelectorAll('.fit-full').length,
    text: line ? line.textContent : null,
    index: line ? kids.indexOf(line) : -1,
    last: line ? kids[kids.length - 1] === line : false,
    classes: kids.map(k => k.className),
  };
}"""


def test_the_line_shows_under_the_stats_when_the_selected_schedule_has_a_full_group(page):
    _select(page, 1)
    got = page.evaluate(SUMMARY)
    assert got["count"] == 1, got
    assert got["text"] == LINE, got
    # מתחת לנתונים: אחרי שורת השבבים ואחרי "מה פחות טוב" — האחרונה.
    assert got["classes"] == ["stat-pills", "fit-lost", "fit-full"], got
    assert got["last"], got
    assert page.errors == [], page.errors  # type: ignore[attr-defined]


def test_the_line_follows_the_selected_alternative(page):
    _select(page, 2)
    assert page.evaluate(SUMMARY)["count"] == 0
    _select(page, 1)
    assert page.evaluate(SUMMARY)["count"] == 1
    _select(page, 2)
    assert page.evaluate(SUMMARY)["count"] == 0


def test_with_no_penalty_sentence_the_line_sits_right_under_the_pills(page):
    _select(page, 5)
    got = page.evaluate(SUMMARY)
    assert got["classes"] == ["stat-pills", "fit-full"], got
    assert got["text"] == LINE, got


def test_a_full_group_with_no_fixed_time_counts(page):
    _select(page, 3)
    got = page.evaluate(SUMMARY)
    assert got["count"] == 1 and got["text"] == LINE, got


def test_the_other_two_statuses_do_not_show_the_line(page):
    _select(page, 4)
    picks = page.evaluate(
        "() => window.slotwise.getRuntime().solve.schedules[3].picks.map(p => p.status_note)"
    )
    assert REPEATERS in picks and WAITLIST in picks, picks
    assert page.evaluate(SUMMARY)["count"] == 0


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_line_is_warn_ink_and_never_dimmed_with_opacity(browser, server, scheme):
    ctx, pg = _open(browser, server, scheme)
    try:
        _select(pg, 1)
        got = pg.evaluate(
            """() => {
              const line = document.querySelector('#schedule-summary .fit-full');
              const probe = document.createElement('span');
              probe.style.color = 'var(--warn-ink)';
              document.body.appendChild(probe);
              const want = getComputedStyle(probe).color;
              probe.remove();
              const cs = getComputedStyle(line);
              return {color: cs.color, want, opacity: cs.opacity};
            }"""
        )
        assert got["color"] == got["want"], got
        assert got["opacity"] == "1", got
    finally:
        ctx.close()
