"""דף התוצאה: שורת "ללא מועד קבוע" מונה כל רכיב בלי מועד (2026-10-03).

DESIGN.md, "Results page", 5: השורה מונה כל רכיב בחלופה הנבחרת שאין לו מועד
קבוע — לא רק קורסים שאין להם אף מפגש.

* קורס בלי אף רכיב עם מועד: "<שם> (<סוג>, N נ״ז)", כמו קודם.
* קורס שחלק מרכיביו משובצים: "<שם> (<סוג>)" — רק הרכיבים בלי המועד, ובלי
  נ"ז. עד 2026-10-03 קורס כזה לא נמנה כלל, והרכיב בלי המועד לא הופיע בשום
  מקום בדף (‏11179, 11360, 11361, 51432 בקטלוג).
* "קבוצה מלאה" נאמרת לפי הרכיבים בלי המועד בלבד.

השרת מצביע על מסד ריק — רק הקטלוג הקפוא נקרא, לא data/db המקומי.
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
GRID = STRINGS["app"]["grid"]
APP_JS = (ROOT / "src" / "web" / "static" / "app.js").read_text(encoding="utf-8")
FULL = re.search(r'var FULL_STATUS = "([^"]+)";', APP_JS).group(1)
STORAGE_KEY = "braude_schedule_builder_v1"  # אין לשנותו — ראו CLAUDE.md

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402


def fill(template: str, **values) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    db = tmp_path_factory.mktemp("empty-db")
    srv = make_server(
        "127.0.0.1", port,
        create_app(config={"allow_network": False, "db_root": str(db)}), threaded=True,
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
            b = pw.chromium.launch()
        except Exception as exc:  # אין דפדפן מותקן — לא כישלון של הקוד
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            yield b
        finally:
            b.close()


def _mutating(mutate):
    def handler(route):
        response = route.fetch()
        data = response.json()
        if data.get("schedules"):
            mutate(data["schedules"])
        route.fulfill(status=response.status, headers={"content-type": "application/json"},
                      body=json.dumps(data, ensure_ascii=False))
    return handler


def _open(browser, server, extra, mutate=None):
    """הנדסת תוכנה סמסטר 5 המומלץ ועוד extra, עד שהרשת מוכנה."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, color_scheme="light")
    pg = ctx.new_page()
    if mutate:
        pg.route("**/api/solve", _mutating(mutate))
    pg.goto(server)
    pg.wait_for_timeout(2500)
    pg.select_option("#select-program", "הנדסת תוכנה")
    pg.select_option("#select-year", "3")
    pg.select_option("#select-term", "א")
    pg.wait_for_timeout(2500)
    pg.click("#step-year-next")  # "המשך" אל שלב הקורסים (Phase 8, באישור 2026-10-06)
    pg.click("#btn-restore-recommended")
    pg.wait_for_selector("#schedule-grid .ev", timeout=20000)
    pg.evaluate(
        """(a) => { const s = JSON.parse(localStorage.getItem(a.key) || '{}');
                    s.codes = (s.codes || []).concat(a.codes);
                    localStorage.setItem(a.key, JSON.stringify(s)); }""",
        {"key": STORAGE_KEY, "codes": list(extra)},
    )
    pg.reload()
    pg.wait_for_selector("#schedule-grid .ev", timeout=20000)
    pg.wait_for_timeout(1200)
    return ctx, pg


LINE = """() => {
  const el = document.getElementById('schedule-unscheduled');
  const sch = window.slotwise.getRuntime().solve.schedules[window.slotwise.getState().activeSchedule];
  const blocks = [...document.querySelectorAll('#schedule-grid .ev')].map(e => e.dataset.code);
  return {text: el && !el.hidden ? el.textContent.trim() : '', picks: sch.picks, blocks};
}"""


def _items(text):
    head = fill(GRID["unscheduled"], list="")
    assert text.startswith(head), text
    return text[len(head):]


def test_a_partly_timed_course_lists_its_no_time_component_without_credits(browser, server):
    """‏51432 בקטלוג הקפוא: הרצאה עם מועד, ורכיב "אחר" בלי מועד."""
    ctx, pg = _open(browser, server, ["51432"])
    try:
        got = pg.evaluate(LINE)
        untimed = [p for p in got["picks"] if p["code"] == "51432" and not p["meetings"]]
        timed = [p for p in got["picks"] if p["code"] == "51432" and p["meetings"]]
        assert untimed and timed, got["picks"]
        name = untimed[0]["name"]
        want = fill(GRID["unscheduledItemNoCredits"], name=name, kind=untimed[0]["kind"])
        items = _items(got["text"])
        # הפריט עצמו מכיל ", " כשיש לו נ"ז — ולכן בדיקת מחרוזת, לא פיצול.
        assert want in items, (want, got["text"])
        assert f"{name} ({untimed[0]['kind']}, " not in items, got["text"]  # בלי נ"ז
        # ‏ההרצאה שיש לה מועד עדיין על הרשת.
        assert "51432" in got["blocks"], got["blocks"]
    finally:
        ctx.close()


def test_the_line_keeps_credits_for_a_course_with_no_timed_component(browser, server):
    """‏61998 בלי אף מפגש; ובחלופה 1 גם התרגול של 61832 בלי מועד (מיורט), עם
    מצב "מלאה" על ההרצאה שלו שיש לה מועד — ולכן בלי "קבוצה מלאה" בשורה."""
    def mutate(schedules):
        for p in schedules[0]["picks"]:
            if p["code"] == "61832" and p["kind"] == "תרגול":
                p["meetings"] = []
                p["status_note"] = ""
            elif p["code"] == "61832":
                p["status_note"] = FULL
    ctx, pg = _open(browser, server, ["61998"], mutate)
    try:
        got = pg.evaluate(LINE)
        items = _items(got["text"])
        project = next(p for p in got["picks"] if p["code"] == "61998")
        credits = fill(STRINGS["app"]["credits"]["withUnit"],
                       value=int(project["credits"]) if float(project["credits"]).is_integer() else project["credits"])
        want_project = fill(GRID["unscheduledItem"], name=project["name"], kind=project["kind"], credits=credits)
        tut = next(p for p in got["picks"] if p["code"] == "61832" and p["kind"] == "תרגול")
        want_tut = fill(GRID["unscheduledItemNoCredits"], name=tut["name"], kind="תרגול")
        assert want_project in items, (want_project, items)
        assert want_tut in items, (want_tut, items)
        assert fill(GRID["unscheduledFull"], item=want_tut, status=GRID["groupFull"]) not in items, items
    finally:
        ctx.close()


def test_a_full_group_with_no_time_in_a_partly_timed_course_is_marked(browser, server):
    def mutate(schedules):
        for p in schedules[0]["picks"]:
            if p["code"] == "61832" and p["kind"] == "תרגול":
                p["meetings"] = []
                p["status_note"] = FULL
    ctx, pg = _open(browser, server, [], mutate)
    try:
        got = pg.evaluate(LINE)
        tut = next(p for p in got["picks"] if p["code"] == "61832" and p["kind"] == "תרגול")
        item = fill(GRID["unscheduledItemNoCredits"], name=tut["name"], kind="תרגול")
        want = fill(GRID["unscheduledFull"], item=item, status=GRID["groupFull"])
        assert want in _items(got["text"]), (want, got["text"])
    finally:
        ctx.close()
