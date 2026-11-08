"""‏"הגדרות נוספות" בשלב 3: שתי השעות ו"בלי יום שישי" לא עולים זה על זה.

הבאג (2026-11-08) נראה בטלפון (Safari של iOS) ולא שוחזר בכרומיום. החשד:
‏input type=time מעוצב טבעית מתעלם מהרוחב שלו וגולש מהעמודה. כדי לא
להישען עליו לבדו, עד 640px הכול בטור — שעה, שעה, ואז "בלי יום שישי" —
ושום פקד אינו עומד ליד אחר. ברחב שתי השעות זו לצד זו, בשתי עמודות שוות.

הבדיקה נועלת את הפריסה הזו בכרומיום ואת ההקשחה שעל השדות (‎appearance:
none‎, רוחב מלא, רצפת גובה); את Safari עצמו היא אינה יכולה להריץ.
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


GEOMETRY = """() => {
  document.getElementById('advanced-prefs').open = true;
  const box = id => { const r = document.getElementById(id).getBoundingClientRect();
                      return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height}; };
  const times = document.querySelector('#advanced-prefs .prefs-times');
  const cs = getComputedStyle(document.getElementById('input-earliest'));
  const order = [...document.querySelectorAll(
      '#advanced-prefs #input-earliest, #advanced-prefs #input-latest, '
    + '#advanced-prefs #chk-forbid-friday, #advanced-prefs #blocked-list')].map(e => e.id);
  return {
    earliest: box('input-earliest'), latest: box('input-latest'),
    friday: box('chk-forbid-friday'),
    fridayLabel: document.querySelector('label[for="chk-forbid-friday"]').getBoundingClientRect().toJSON(),
    earliestField: document.getElementById('input-earliest').closest('.field').getBoundingClientRect().toJSON(),
    latestField: document.getElementById('input-latest').closest('.field').getBoundingClientRect().toJSON(),
    columns: times ? getComputedStyle(times).gridTemplateColumns.split(' ').length : 0,
    timesW: times ? times.getBoundingClientRect().width : 0,
    inlineFull: (() => { const i = document.getElementById('input-earliest');
                         return Math.abs(i.getBoundingClientRect().width
                                         - i.closest('.field').getBoundingClientRect().width) <= 1; })(),
    bothInTimes: !!times && times.contains(document.getElementById('input-earliest'))
                 && times.contains(document.getElementById('input-latest'))
                 && !times.contains(document.getElementById('chk-forbid-friday')),
    appearance: cs.appearance, webkitAppearance: cs.webkitAppearance,
    minBlock: parseFloat(cs.minBlockSize), minInline: cs.minInlineSize,
    order: order,
    scrollW: document.documentElement.scrollWidth, vw: window.innerWidth,
  };
}"""


def _overlap(a, b):
    return not (a["r"] <= b["l"] or b["r"] <= a["l"] or a["b"] <= b["t"] or b["b"] <= a["t"])


def _rect(d):
    return {"l": d["left"], "r": d["right"], "t": d["top"], "b": d["bottom"]}


def _measure(browser, server, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    pg = ctx.new_page()
    try:
        pg.goto(server)
        pg.wait_for_timeout(2500)
        return pg.evaluate(GEOMETRY)
    finally:
        ctx.close()


PHONES = [320, 375, 640]
WIDE = [768, 1280, 1440]


def _no_overlaps(g):
    rects = {"earliest": g["earliest"], "latest": g["latest"], "friday": g["friday"],
             "fridayLabel": _rect(g["fridayLabel"])}
    names = list(rects)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if {a, b} == {"friday", "fridayLabel"}:
                continue
            assert not _overlap(rects[a], rects[b]), (a, b, g)
    # ‏כל שדה בתוך העמודה שלו — זו בדיוק הגלישה שנראתה בטלפון.
    for inp, field in ((g["earliest"], g["earliestField"]), (g["latest"], g["latestField"])):
        assert inp["l"] >= field["left"] - 0.5 and inp["r"] <= field["right"] + 0.5, g
    assert g["scrollW"] <= g["vw"], "אין גלילה אופקית"


@pytest.mark.parametrize("width", PHONES)
def test_on_a_phone_everything_is_one_column(browser, server, width):
    g = _measure(browser, server, width)
    _no_overlaps(g)
    assert g["bothInTimes"] and g["columns"] == 1, g
    e, la, fr = g["earliest"], g["latest"], g["friday"]
    # ‏"לא להתחיל לפני" ברוחב מלא, "לא לסיים אחרי" מתחתיו באותו רוחב.
    assert abs(e["w"] - g["timesW"]) <= 1 and abs(la["w"] - g["timesW"]) <= 1, g
    assert abs(e["l"] - la["l"]) <= 1, g
    assert la["t"] >= e["b"], "השנייה מתחת לראשונה"
    # ‏"בלי יום שישי" — בשורה משלו, מתחת לשתיהן.
    assert fr["t"] >= la["b"] and g["fridayLabel"]["top"] >= la["b"], g


@pytest.mark.parametrize("width", WIDE)
def test_on_wider_screens_the_times_sit_side_by_side(browser, server, width):
    g = _measure(browser, server, width)
    _no_overlaps(g)
    assert g["bothInTimes"] and g["columns"] == 2, g
    e, la = g["earliest"], g["latest"]
    assert abs(e["w"] - la["w"]) <= 1, "שתי עמודות שוות"
    assert abs(e["t"] - la["t"]) <= 1, "באותה שורה"


@pytest.mark.parametrize("width", [375, 1440])
def test_the_time_inputs_carry_the_ios_hardening(browser, server, width):
    g = _measure(browser, server, width)
    assert "none" in (g["appearance"], g["webkitAppearance"]), g
    assert g["minInline"] == "0px", g
    assert g["inlineFull"], "inline-size: 100%"
    # ‏ריק, ‏input type=time ב-iOS מתכווץ לגובה אפס בלי רצפה.
    assert g["minBlock"] >= 40, g
    assert g["earliest"]["h"] >= 40 and g["latest"]["h"] >= 40, g


@pytest.mark.parametrize("width", [375, 1440])
def test_ids_and_control_order_are_unchanged(browser, server, width):
    g = _measure(browser, server, width)
    assert g["order"] == ["input-earliest", "input-latest", "chk-forbid-friday", "blocked-list"]
