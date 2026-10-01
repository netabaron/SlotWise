"""‏"בלי המרצה שבחרת" ושבב "N מתוך M מרצים מועדפים" אינם יכולים לסתור זה את זה.

עד 2026-10-02 השבב נספר בשרת (``lecturer_hits``: כל קבוצה שנבחרה, שמות מנורמלים,
והמועדף הוא הראשון בדירוג) והרשימה נבנתה בדף (רק קבוצות עם מפגשים, שמות כמו
שהם, וכל מרצה מהדירוג נחשב). בהנדסת תוכנה סמסטר 5 זה נראה כך: השבב אמר
"1 מתוך 1" והמשפט אמר "חסר: מר עידי ג'יריס" — המרצה של 11069, בקבוצת שו"ת
בלי מועד שכן הייתה במערכת.

הבדיקות כאן משחזרות את הכלל של השרת בפייתון, בנפרד מהדף, ובודקות את הדף מולו
ומול ``lecturer_total - lecturer_hits`` שהשרת החזיר.

**אף בדיקה כאן אינה תלויה ב-data/db המקומי** (DEFERRED.md): השמות נלקחים מהמערכת
שהשרת החזיר, ומקרה ה-11069 נבנה בתשובת ‎/api/solve‎ מיורטת — בקטלוג הקפוא לכל
קבוצות סמסטר א' של 11069 יש מפגש.
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

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import create_app  # noqa: E402

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
LOST = STRINGS["app"]["schedule"]["lost"]
HITS = STRINGS["app"]["schedule"]["lecturersHits"]
STORAGE_KEY = "braude_schedule_builder_v1"  # אין לשנותו — ראו CLAUDE.md


def fill(template: str, **values) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def norm(name: str) -> str:
    """‏scheduler._norm_name."""
    return " ".join((name or "").split()).casefold()


def expected_missing(schedule: dict, ranked: dict) -> list[str]:
    """הכלל של השרת, בנפרד מהדף: לכל קורס מדורג שבמערכת, המועדף הוא השם הראשון
    (אחרי strip והשמטת ריקים), והוא "חסר" אם אף קבוצה שנבחרה בקורס — כולל
    קבוצה בלי מפגשים — אינה שלו."""
    by_code: dict[str, set[str]] = {}
    for p in schedule["picks"]:
        by_code.setdefault(p["code"], set()).add(norm(p.get("lecturer", "")))
    missing = []
    for code, names in ranked.items():
        names = [str(n).strip() for n in names if str(n).strip()]
        if not names or code not in by_code:
            continue
        if norm(names[0]) not in by_code[code]:
            if names[0] not in missing:
                missing.append(names[0])
    return missing


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


def _strip_meetings(code):
    """בכל המערכות: לקבוצה של code אין מפגשים — כמו 11069 בקטלוג שבמאגר."""
    def handler(route):
        response = route.fetch()
        data = response.json()
        for sch in data.get("schedules") or []:
            for p in sch["picks"]:
                if p["code"] == code:
                    p["meetings"] = []
        route.fulfill(status=response.status, headers={"content-type": "application/json"},
                      body=json.dumps(data, ensure_ascii=False))
    return handler


def _open(browser, server, route=None):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, color_scheme="light")
    page = ctx.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    if route:
        page.route("**/api/solve", route)
    page.goto(server)
    page.wait_for_timeout(2500)
    page.select_option("#select-program", "הנדסת תוכנה")
    page.select_option("#select-year", "3")
    page.select_option("#select-term", "א")
    page.wait_for_timeout(2500)
    page.click("#btn-restore-recommended")
    page.wait_for_selector("#schedule-grid .ev", timeout=20000)
    page.wait_for_timeout(800)
    return ctx, page


def _rank(page, ranked):
    page.evaluate(
        """(a) => { const s = JSON.parse(localStorage.getItem(a.key) || '{}');
                    s.ranked = a.ranked; localStorage.setItem(a.key, JSON.stringify(s)); }""",
        {"key": STORAGE_KEY, "ranked": ranked},
    )
    page.reload()
    page.wait_for_selector("#schedule-grid .ev", timeout=20000)
    page.wait_for_timeout(1200)


SHOWN = """() => {
  const rt = window.slotwise.getRuntime();
  const sch = rt.solve.schedules[window.slotwise.getState().activeSchedule];
  const item = document.querySelector('#schedule-summary .fit-lost-item[data-penalty="lecturer"]');
  const pill = document.querySelector('#schedule-summary [data-stat="lecturers"]');
  return {schedule: sch, hits: sch.lecturer_hits, total: sch.lecturer_total,
          item: item ? item.textContent : null, pill: pill ? pill.textContent.trim() : null};
}"""


def _lecturer(page, code):
    return page.evaluate(
        """(code) => { const s = window.slotwise.getRuntime().solve.schedules[0];
                       return (s.picks.find(p => p.code === code && p.lecturer) || {}).lecturer || ''; }""",
        code,
    )


def _assert_consistent(got, ranked):
    want = expected_missing(got["schedule"], ranked)
    assert len(want) == got["total"] - got["hits"], (want, got["hits"], got["total"])
    assert got["pill"] == fill(HITS, hits=got["hits"], total=got["total"]), got["pill"]
    if not want:
        assert got["item"] is None, got["item"]
    else:
        key = "lecturer" if len(want) == 1 else "lecturers"
        assert got["item"] == fill(LOST[key], names=", ".join(want)), (got["item"], want)


def test_a_preferred_lecturer_in_a_group_without_meetings_is_not_missing(browser, server):
    """המקרה של 11069: המרצה המועדף בקבוצה בלי מועד שכן במערכת."""
    ctx, pg = _open(browser, server, route=_strip_meetings("11069"))
    try:
        name = _lecturer(pg, "11069")
        assert name, "ל-11069 אין מרצה במערכת הראשונה"
        ranked = {"11069": [name]}
        _rank(pg, ranked)
        got = pg.evaluate(SHOWN)
        pick = next(p for p in got["schedule"]["picks"] if p["code"] == "11069")
        assert pick["meetings"] == [] and pick["lecturer"] == name, pick
        assert (got["hits"], got["total"]) == (1, 1), got
        assert got["item"] is None, f"המרצה נאמר חסר למרות שקבוצתו במערכת: {got['item']}"
        _assert_consistent(got, ranked)
    finally:
        ctx.close()


def test_a_second_choice_in_the_schedule_still_leaves_the_first_missing(browser, server):
    """המועדף הוא הראשון בדירוג — כמו אצל השרת. השני במערכת אינו פגיעה."""
    ctx, pg = _open(browser, server)
    try:
        present = _lecturer(pg, "61759")
        ranked = {"61759": ["מרצה מועדף שאינו בקטלוג", present]}
        _rank(pg, ranked)
        got = pg.evaluate(SHOWN)
        assert (got["hits"], got["total"]) == (0, 1), got
        assert got["item"] == fill(LOST["lecturer"], names="מרצה מועדף שאינו בקטלוג"), got
        _assert_consistent(got, ranked)
    finally:
        ctx.close()


def test_names_are_compared_like_the_server_compares_them(browser, server):
    """רווחים מיותרים בדירוג אינם הופכים מרצה שבמערכת לחסר."""
    ctx, pg = _open(browser, server)
    try:
        present = _lecturer(pg, "61759")
        spaced = "  " + "  ".join(present.split()) + " "
        ranked = {"61759": [spaced]}
        _rank(pg, ranked)
        got = pg.evaluate(SHOWN)
        assert (got["hits"], got["total"]) == (1, 1), got
        assert got["item"] is None, got["item"]
        _assert_consistent(got, ranked)
    finally:
        ctx.close()


def test_the_pill_and_the_sentence_agree_on_every_alternative(browser, server):
    """שלושה קורסים מדורגים, תערובת של פגיעות והחטאות, בכל חמש החלופות."""
    ctx, pg = _open(browser, server, route=_strip_meetings("11069"))
    try:
        ranked = {
            "11069": [_lecturer(pg, "11069")],
            "61759": ["מרצה מועדף שאינו בקטלוג", _lecturer(pg, "61759")],
            "61757": [_lecturer(pg, "61757")],
        }
        _rank(pg, ranked)
        cards = pg.locator("#alt-cards .alt-card").count()
        assert cards == 5
        for rank in range(1, cards + 1):
            pg.click(f'#alt-cards [data-rank="{rank}"]')
            pg.wait_for_timeout(500)
            _assert_consistent(pg.evaluate(SHOWN), ranked)
        assert pg.errors == [], pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()
