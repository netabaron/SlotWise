"""שלב המרצים: קבוצה בלי מועד שהכלל פוסל (2026-10-03).

DESIGN.md, שלב המרצים: קבוצה בלי מפגשים, כשלקבוצה אחרת מאותו קורס ומאותו
סוג יש מפגשים, מוצגת כמו קבוצה שאינה משאירה מערכת אפשרית — עם שורה אחת,
"אין לקבוצה מועד קבוע", בצבע ולא בשקיפות, ובלי דירוג ובלי נעיצה. קבוצה בלי
מועד ברכיב שאין בו אף קבוצה עם מועד נשארת רגילה.

השרת כאן מצביע על מסד ריק, כך שרק הקטלוג הקפוא נקרא — לא data/db המקומי.
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

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
ROW = STRINGS["app"]["lecturers"]["row"]
NO_TIME = ROW["noTimeLine"]
STORAGE_KEY = "braude_schedule_builder_v1"  # אין לשנותו — ראו CLAUDE.md

LAB8 = "row-11232-מעבדה-271030210/8"      # בלי מועד; למעבדות אחרות יש מועד
LAB3 = "row-11232-מעבדה-271030210/3"      # מעבדה עם מועד
PROJECT = "row-61998-פרויקט-271060410"    # בלי מועד, ואין לרכיב קבוצה עם מועד
THESIS = "row-53110-הרצאה-273550200"     # בלי מועד, ליד הרצאה עם מועד; יש שם מרצה

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402


def test_the_copy():
    assert NO_TIME == "אין לקבוצה מועד קבוע"


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


def _page(browser, server, extra, scheme="light"):
    """הנדסת תוכנה, סמסטר 5 המומלץ, ועוד הקורסים ב-extra; כל הקורסים פתוחים."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme=scheme)
    pg = ctx.new_page()
    pg.goto(server)
    pg.wait_for_timeout(3000)
    pg.select_option("#select-program", "הנדסת תוכנה")
    pg.select_option("#select-year", "3")
    pg.select_option("#select-term", "א")
    pg.wait_for_timeout(2500)
    pg.click("#btn-restore-recommended")
    pg.wait_for_timeout(4000)
    pg.evaluate(
        """(a) => { const s = JSON.parse(localStorage.getItem(a.key) || '{}');
                    s.codes = (s.codes || []).concat(a.codes);
                    localStorage.setItem(a.key, JSON.stringify(s)); }""",
        {"key": STORAGE_KEY, "codes": list(extra)},
    )
    pg.reload()
    for code in extra:
        head = pg.locator(f'[data-fk="lect-course-{code}"]')
        head.wait_for(state="attached", timeout=20000)
        pg.wait_for_timeout(2500)
        # השלבים עשויים להיות מקופלים אחרי הטעינה; לחיצה בסקריפט, כמו _fk
        # ב-test_lecturers_step.py, פותחת את הקורס גם כשהכותרת מוסתרת.
        if head.get_attribute("aria-expanded") != "true":
            pg.evaluate(
                "fk => document.querySelector('[data-fk=\"' + fk + '\"]').click()",
                f"lect-course-{code}",
            )
            pg.wait_for_timeout(400)
    return ctx, pg


ROWINFO = """(fk) => {
  const tr = document.querySelector('[data-fk="' + fk + '"]');
  if (!tr) return null;
  const sub = tr.querySelector('.row-dead');
  const pin = tr.querySelector('.pin-btn');
  const probe = document.createElement('span');
  probe.style.color = 'var(--mut)';
  document.body.appendChild(probe);
  const mut = getComputedStyle(probe).color;
  probe.remove();
  return {
    cls: tr.className, disabled: tr.getAttribute('aria-disabled'), title: tr.getAttribute('title') || '',
    text: tr.textContent, sub: sub ? sub.textContent : null,
    subColor: sub ? getComputedStyle(sub).color : null, mut,
    opacity: [getComputedStyle(tr).opacity, sub ? getComputedStyle(sub).opacity : '1'],
    pinDisabled: pin ? pin.disabled : null, pinLabel: pin ? pin.getAttribute('aria-label') : null,
  };
}"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_a_no_time_group_the_rule_excludes_is_shown_as_unavailable(browser, server, scheme):
    ctx, pg = _page(browser, server, ["11232"], scheme)
    try:
        got = pg.evaluate(ROWINFO, LAB8)
        assert got, "השורה של מעבדה /8 לא נמצאה"
        assert "is-dead" in got["cls"].split() and got["disabled"] == "true", got
        assert got["sub"] == NO_TIME, got
        assert ROW["deadLine"] not in got["text"], got
        assert NO_TIME in got["title"] and NO_TIME in (got["pinLabel"] or ""), got
        assert got["pinDisabled"] is True, got
        # צבע, לא שקיפות.
        assert got["subColor"] == got["mut"], got
        assert got["opacity"] == ["1", "1"], got
    finally:
        ctx.close()


def test_it_cannot_be_ranked_or_pinned(browser, server):
    """הנעיצה — על מעבדה ‏/8 של 11232. הדירוג — על הרצאה 273550200 של 53110:
    בלי מועד, ליד הרצאה עם מועד, ועם שם מרצה (למעבדה ‏/8 אין שם, ושם ריק
    ממילא אינו מדורג — שם הבדיקה לא הייתה יכולה להיכשל)."""
    ctx, pg = _page(browser, server, ["11232", "53110"])
    try:
        assert pg.evaluate(ROWINFO, THESIS)["sub"] == NO_TIME
        pg.evaluate("fk => document.querySelector('[data-fk=\"' + fk + '\"]').click()", THESIS)
        pg.evaluate(
            "fk => document.querySelector('[data-fk=\"' + fk + '\"] .pin-btn').click()", LAB8
        )
        pg.wait_for_timeout(600)
        state = pg.evaluate("() => window.slotwise.getState()")
        assert not (state.get("ranked") or {}).get("53110"), state.get("ranked")
        assert not (state.get("pinned") or {}).get("11232"), state.get("pinned")
    finally:
        ctx.close()


def test_a_timed_group_of_the_same_component_does_not_carry_the_line(browser, server):
    ctx, pg = _page(browser, server, ["11232"])
    try:
        got = pg.evaluate(ROWINFO, LAB3)
        assert got and NO_TIME not in got["text"], got
    finally:
        ctx.close()


def test_a_no_time_group_with_no_timed_sibling_stays_a_normal_row(browser, server):
    ctx, pg = _page(browser, server, ["61998"])
    try:
        got = pg.evaluate(ROWINFO, PROJECT)
        assert got, "השורה של 61998 לא נמצאה"
        assert NO_TIME not in got["text"], got
        assert "is-dead" not in got["cls"].split(), got
    finally:
        ctx.close()
