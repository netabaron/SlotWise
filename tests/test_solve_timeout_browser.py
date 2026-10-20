# -*- coding: utf-8 -*-
"""מה הדף אומר כש-/api/solve נעצר במגבלת הזמן, וכשהשרת המתארח נכשל.

‏2026-10-20 (docs/DESIGN.md → "Solver: exact pruned search"):
  * ‏``timed_out: true`` ⇐ באנר אחד, ‏``app.banners.solveTimeout``, גם כשנמצאו
    מערכות וגם כשלא. בלי מערכות — **לא** "אין מערכת אפשרית": זה לא הוכח.
  * ‏500 ב-HTML — מה ש-gunicorn כותב כשהוא הורג worker — ⇐ ‏``serverFault``,
    שאינו אומר עוד "השרת המקומי".
  * תקלת רשת באתר המתארח ⇐ ‏``networkHosted``, בלי "להריץ אותו שוב".

התשובות של השרת מיורטות ומקבלות מצב ידוע; השרת עצמו הוא האמיתי.
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

KEY = "braude_schedule_builder_v1"  # אין לשנותו — ראו CLAUDE.md
CODES = ["11069", "61756", "61757", "62027", "61759", "61832"]
STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
TIMEOUT_TEXT = STRINGS["app"]["banners"]["solveTimeout"]
EMPTY_TITLE = STRINGS["ui"]["schedule"]["emptyTitle"]
ERRORS = STRINGS["app"]["errors"]


# ==========================================================================
# 1. הנוסח — בלי דפדפן
# ==========================================================================
def test_the_timeout_message_lives_in_strings_json():
    text = STRINGS["app"]["banners"]["solveTimeout"]
    assert text and "ייתכן" in text and "אפשר" in text
    assert "500" not in text and "Error" not in text


def test_the_server_fault_copy_no_longer_says_local():
    assert "המקומי" not in ERRORS["serverFault"]
    assert "המקומי" not in ERRORS["networkHosted"]
    assert "שמורות" in ERRORS["networkHosted"] and "אפשר" in ERRORS["networkHosted"]
    # ‏"פרטים טכניים" מוצגים רק עם ‎?debug=1‎ — הפניה אליהם הייתה למקום שאינו קיים.
    assert "פרטים טכניים" not in ERRORS["serverFault"]


# ==========================================================================
# 2. הדף
# ==========================================================================
sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import create_app  # noqa: E402


def _state():
    return {
        "schema": 1, "studyYear": 3, "term": "א", "semester": "5",
        "codes": CODES, "known": {}, "program": "הנדסת תוכנה", "topN": 5,
        "activeSchedule": 0, "targetDays": 4, "provenanceReady": True,
        "autoSemester": "5", "autoCodes": CODES, "manualCodes": [],
        "autoDropped": [],
    }


@pytest.fixture(scope="module")
def server():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = make_server("127.0.0.1", port, create_app(config={"allow_network": False}),
                      threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d/" % port
    finally:
        srv.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            yield b
        finally:
            b.close()


def _timed_out(drop_schedules):
    """תשובת ‏/api/solve אמיתית, מסומנת כאילו נעצרה במגבלה."""
    def handler(route):
        response = route.fetch()
        data = response.json()
        data["timed_out"] = True
        for sch in data.get("schedules") or []:
            sch["truncated"] = True
        if drop_schedules:
            data["schedules"] = []
            data["feasible_count"] = 0
            data["reasons"] = []
        route.fulfill(status=200, headers={"content-type": "application/json"},
                      body=json.dumps(data, ensure_ascii=False))
    return handler


def _gunicorn_500(route):
    """בדיוק מה ש-gunicorn 23 כותב אחרי WORKER TIMEOUT (util.write_error)."""
    body = ("<html>\n  <head>\n    <title>Internal Server Error</title>\n  </head>\n"
            "  <body>\n    <h1><p>Internal Server Error</p></h1>\n    \n  </body>\n</html>\n")
    route.fulfill(status=500, headers={"content-type": "text/html"}, body=body)


def _hosted_bootstrap(route):
    response = route.fetch()
    data = response.json()
    data["mode"] = "hosted"
    route.fulfill(status=200, headers={"content-type": "application/json"},
                  body=json.dumps(data, ensure_ascii=False))


def _open(browser, server, routes):
    ctx = browser.new_context(viewport={"width": 1100, "height": 900})
    ctx.add_init_script(
        "localStorage.setItem('%s', %s);" % (KEY, json.dumps(json.dumps(_state())))
    )
    page = ctx.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    for pattern, handler in routes:
        page.route(pattern, handler)
    page.goto(server)
    page.wait_for_timeout(6500)
    return ctx, page


def _banners(page):
    return page.evaluate(
        """() => [].slice.call(document.querySelectorAll('#banners .banner')).map(b => ({
            kind: b.className.replace('banner banner--',''),
            text: (b.querySelector('.banner-text')||{}).textContent || '',
        }))"""
    )


def test_a_timed_out_solve_shows_one_message_and_keeps_the_schedules(browser, server):
    ctx, page = _open(browser, server, [("**/api/solve", _timed_out(drop_schedules=False))])
    try:
        mine = [b for b in _banners(page) if b["text"] == TIMEOUT_TEXT]
        assert len(mine) == 1, _banners(page)
        assert mine[0]["kind"] == "warn"
        assert page.locator("#schedule-grid .ev").count() > 0, "המערכות שנמצאו נשארות על המסך"
        assert page.errors == []
    finally:
        ctx.close()


def test_a_timed_out_solve_without_schedules_is_not_called_impossible(browser, server):
    ctx, page = _open(browser, server, [("**/api/solve", _timed_out(drop_schedules=True))])
    try:
        assert [b for b in _banners(page) if b["text"] == TIMEOUT_TEXT], _banners(page)
        assert page.locator("#schedule-empty").is_hidden(), "אין מערכת — לא הוכח"
        status = page.locator("#results-status").text_content() or ""
        assert EMPTY_TITLE not in status, status
        assert page.errors == []
    finally:
        ctx.close()


def test_gunicorns_html_500_reads_as_a_server_fault_not_a_local_one(browser, server):
    ctx, page = _open(browser, server, [("**/api/solve", _gunicorn_500)])
    try:
        texts = [b["text"] for b in _banners(page)]
        want = ERRORS["serverFault"].replace("{status}", "500")
        assert any(want in t for t in texts), texts
        assert not any("המקומי" in t for t in texts), texts
    finally:
        ctx.close()


def test_a_network_failure_on_the_hosted_site_does_not_say_run_it_again(browser, server):
    ctx, page = _open(browser, server, [
        ("**/api/bootstrap", _hosted_bootstrap),
        ("**/api/solve", lambda route: route.abort("connectionrefused")),
    ])
    try:
        texts = [b["text"] for b in _banners(page)]
        assert any(ERRORS["networkHosted"] in t for t in texts), texts
        assert not any(ERRORS["network"] in t for t in texts), texts
    finally:
        ctx.close()
