"""שלב 3 של העיצוב מחדש: ימי לימוד (docs/DESIGN.md, "Study days").

מה נשמר כאן:
* המינימום נאמר פעם אחת — "מינימום" מתחת לכפתור שלו — ולא עוד באריח
  ובהערה שחזרו עליו.
* ערך מתחת למינימום מקווקו ומושתק, **ועדיין לחיץ** (החלטה מ-2026-09-24:
  בחירתו היא הדרך היחידה אל האזהרה ואל "מה יאפשר N ימים").
* כל ההגדרות האחרות יושבות ב"הגדרות נוספות", סגור כברירת מחדל, ושורה
  אחת בכותרת אומרת מה שונה מברירת המחדל כשהוא סגור.
"""

from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import create_app  # noqa: E402

INK = {"light": "rgb(13, 29, 61)", "dark": "rgb(242, 242, 240)"}
SEC = {"light": "rgb(110, 110, 115)", "dark": "rgb(154, 154, 161)"}


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
            b = pw.chromium.launch()
        except Exception as exc:
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            yield b
        finally:
            b.close()


def _ready(browser, server, scheme="light", width=1280):
    """זהות וקורסים — אחריהם יש פתירה, ולכן יש מינימום (4 בקטלוג הקפוא)."""
    ctx = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme)
    pg = ctx.new_page()
    pg.goto(server)
    pg.wait_for_timeout(3500)
    pg.select_option("#select-program", "הנדסת תוכנה")
    pg.select_option("#select-year", "3")
    pg.select_option("#select-term", "א")
    pg.wait_for_timeout(2500)
    pg.click("#step-year-next")  # "המשך" אל שלב הקורסים (Phase 8, באישור 2026-10-06)
    pg.click("#btn-restore-recommended")
    pg.wait_for_timeout(5000)
    pg.click("#step-courses-next")  # "המשך" אל ימי הלימוד (Phase 8, באישור 2026-10-06)
    return ctx, pg


BUTTONS = """() => [...document.querySelectorAll('#days-buttons .day-btn')].map(b => {
  const t = b.querySelector('.day-min-tag');
  const cs = getComputedStyle(b);
  return {n: +b.dataset.days, checked: b.getAttribute('aria-checked') === 'true',
          impossible: b.classList.contains('is-impossible'),
          disabled: b.disabled || b.getAttribute('aria-disabled') === 'true',
          tag: t && !t.hidden && getComputedStyle(t).display !== 'none' ? t.textContent.trim() : null,
          tagBelow: t && !t.hidden ? t.getBoundingClientRect().top >= b.getBoundingClientRect().bottom : null,
          border: cs.borderTopStyle, color: cs.color, bg: cs.backgroundColor};
})"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_minimum_is_labelled_under_its_button_and_below_it_is_dashed(browser, server, scheme):
    ctx, pg = _ready(browser, server, scheme)
    try:
        buttons = pg.evaluate(BUTTONS)
    finally:
        ctx.close()
    tagged = [b for b in buttons if b["tag"]]
    assert [b["n"] for b in tagged] == [4], buttons
    assert tagged[0]["tag"] == "מינימום" and tagged[0]["tagBelow"], tagged
    for b in buttons:
        if b["n"] < 4:
            assert b["impossible"] and b["border"] == "dashed", b
            assert b["color"] == SEC[scheme], f"מתחת למינימום: מושתק ב-‎--sec‎ ({b})"
            assert not b["disabled"], "ערך מתחת למינימום נשאר לחיץ (החלטה 2026-09-24)"
        else:
            assert not b["impossible"] and b["border"] == "solid", b


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_selected_value_is_filled_ink(browser, server, scheme):
    ctx, pg = _ready(browser, server, scheme)
    try:
        pg.click('.day-btn[data-days="5"]')
        pg.wait_for_timeout(2500)
        five = [b for b in pg.evaluate(BUTTONS) if b["n"] == 5][0]
    finally:
        ctx.close()
    assert five["checked"] and five["bg"] == INK[scheme], five


def test_a_value_below_the_minimum_still_opens_the_warning_and_the_way_out(browser, server):
    ctx, pg = _ready(browser, server)
    try:
        pg.click('.day-btn[data-days="2"]')
        pg.wait_for_timeout(4000)
        got = pg.evaluate(
            """() => ({checked: document.querySelector('.day-btn[data-days="2"]').getAttribute('aria-checked'),
                       warn: !document.getElementById('days-warning').hidden,
                       warnText: document.getElementById('days-warning').textContent,
                       relax: !document.getElementById('days-relax').hidden,
                       conflict: document.getElementById('step-days').classList.contains('is-conflict')})""")
    finally:
        ctx.close()
    assert got["checked"] == "true", got
    assert got["warn"] and "4" in got["warnText"], got
    assert got["relax"], "‏'מה יאפשר 2 ימים' חייב להישאר נגיש"
    assert got["conflict"], got


def test_nothing_repeats_the_helper_line(browser, server):
    """האריחים "יעד"/"מינימום אפשרי" וההערה "המינימום האפשרי הוא N" הוסרו."""
    ctx, pg = _ready(browser, server)
    try:
        got = pg.evaluate(
            """() => ({facts: !!document.getElementById('days-facts'),
                       hint: !!document.getElementById('days-hint'),
                       body: document.getElementById('step-days-body').innerText,
                       helper: document.querySelector('#step-days .step-hint').innerText})""")
    finally:
        ctx.close()
    assert not got["facts"] and not got["hint"], got
    assert "המינימום האפשרי הוא" not in got["body"], got["body"]
    assert "המינימום האפשרי" in got["helper"], got["helper"]


EXTRAS = """() => { const d = document.getElementById('advanced-prefs');
  const v = document.getElementById('advanced-values');
  return {open: d.open, label: d.querySelector('summary').firstChild.textContent.trim(),
          values: v.textContent.trim(), valuesShown: getComputedStyle(v).display !== 'none',
          controls: ['input-earliest', 'input-latest', 'chk-forbid-friday', 'blocked-list']
                      .filter(id => d.contains(document.getElementById(id)))}; }"""


def test_extra_settings_are_one_closed_disclosure(browser, server):
    ctx, pg = _ready(browser, server)
    try:
        before = pg.evaluate(EXTRAS)
        pg.click("#advanced-prefs > summary")
        pg.check("#chk-forbid-friday")
        pg.fill("#input-latest", "21:00")
        pg.dispatch_event("#input-latest", "change")
        pg.wait_for_timeout(2500)
        opened = pg.evaluate(EXTRAS)
        pg.click("#advanced-prefs > summary")
        pg.wait_for_timeout(300)
        closed = pg.evaluate(EXTRAS)
    finally:
        ctx.close()

    assert before["open"] is False, "סגור כברירת מחדל"
    assert before["label"] == "הגדרות נוספות", before
    assert before["values"] == "" and not before["valuesShown"], "בברירת מחדל אין מה לסכם"
    assert before["controls"] == ["input-earliest", "input-latest", "chk-forbid-friday", "blocked-list"]

    assert opened["open"] and not opened["valuesShown"], "פתוח: הפקדים עצמם אומרים את זה"
    assert closed["values"] == "בלי יום שישי · לא אחרי 21:00", closed
    assert closed["valuesShown"], closed
