# -*- coding: utf-8 -*-
"""קופסת "אין מערכת" בדפדפן: קצרה, רגועה, וההחלפה בלחיצה אחת.

המקרה (2026-11-09): תעשייה וניהול, שנה ג' סמסטר א', וב-‏11026 ‏פיזיקה 2ב
(של ביוטכנולוגיה) במקום ‏11210 ‏פיזיקה 2 IE. הקופסה הייתה ארוכה, נראתה
כמו קריסה (‎✖‎ לפני כל סיבה), והציעה להעלות את יעד הימים.

עכשיו: כותרת בשורה אחת; עד שלוש הצעות, ההחלפה ראשונה ועם כפתור; הסיבות
מאחורי "פרטים", סגור. הכפתור מחליף, וההחלפה מקבלת את הודעת הביטול של
הוויתורים — ‏``toggleCourse``/``addCourse``, לא מנגנון חדש.
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

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import create_app  # noqa: E402

KEY = "braude_schedule_builder_v1"
INDUSTRY = "הנדסת תעשייה וניהול"
CORE = ["51132", "51159", "51213", "51429", "51724"]
CODES = CORE + ["11026"]


def _seed():
    return {
        "schema": 1, "studyYear": 3, "term": "א", "semester": "5",
        "codes": CODES, "known": {}, "program": INDUSTRY, "topN": 5,
        "activeSchedule": 0, "targetDays": 4, "provenanceReady": True,
        # ‏הכול ידני: אין סימון מראש, ו-``autoCodes`` נמחק בטעינה.
        "autoSemester": "5", "autoCodes": [], "manualCodes": CODES,
        "autoDropped": [], "autoTrack": "", "overlaps": "none",
    }


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    # ‏``db_root`` ריק: הקטלוג הקפוא, כמו ב-CI ובאתר המאורח.
    empty_db = tmp_path_factory.mktemp("empty_db")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    app = create_app(config={"allow_network": False, "db_root": str(empty_db)})
    srv = make_server("127.0.0.1", port, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield "http://127.0.0.1:%d/" % port
    finally:
        srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            yield b
        finally:
            b.close()


def _page(browser, server):
    ctx = browser.new_context(viewport={"width": 1100, "height": 1000})
    ctx.add_init_script(
        "localStorage.setItem('%s', %s);" % (KEY, json.dumps(json.dumps(_seed())))
    )
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.goto(server)
    page.wait_for_function(
        "() => !document.getElementById('schedule-empty').hidden", timeout=20000
    )
    return ctx, page


BOX = """() => {
  const t = e => e ? e.textContent.replace(/\\s+/g, ' ').trim() : '';
  const box = document.getElementById('schedule-empty');
  const items = [].slice.call(document.querySelectorAll('#infeasible-suggestions > li'));
  const details = document.querySelector('#infeasible-reasons details');
  const reason = document.querySelector('#infeasible-reasons details li');
  return {
    title: t(box.querySelector('.empty-title')),
    sub: !!box.querySelector('.empty-sub'),
    items: items.map(t),
    firstButton: t(items[0] && items[0].querySelector('button')),
    buttons: items.map(li => li.querySelectorAll('button').length),
    details: details ? {open: details.open, summary: t(details.querySelector('summary'))} : null,
    reasonMark: reason ? getComputedStyle(reason, '::before').content : null,
    visibleReasons: document.querySelectorAll('#infeasible-reasons > li').length,
    text: t(box),
  };
}"""


def test_the_box_is_short_calm_and_leads_with_the_swap(browser, server):
    ctx, page = _page(browser, server)
    try:
        box = page.evaluate(BOX)
        assert box["title"], box
        assert not box["sub"], "שורת המשנה הוסרה — כותרת אחת בלבד"

        assert 1 <= len(box["items"]) <= 3, box["items"]
        first = box["items"][0]
        assert "11026" in first and "11210" in first, first
        assert "ביוטכנולוגיה" in first and "בתוכנית שלך" in first, first
        assert box["firstButton"] == "להחליף", box
        # כפתור רק בשורת ההחלפה.
        assert box["buttons"][0] == 1 and sum(box["buttons"][1:]) == 0, box["buttons"]
        assert not any(s.startswith("אפשר לוותר על 51132") for s in box["items"]), box["items"]

        assert box["details"] == {"open": False, "summary": "פרטים"}, box["details"]
        assert box["visibleReasons"] == 1, box
        assert "✖" not in (box["reasonMark"] or ""), box["reasonMark"]

        assert "target_days" not in box["text"] and "יעד הימים" not in box["text"]
        for word in ("combinatorial", "drop course", "allow_soft_conflicts", "earliest"):
            assert word not in box["text"], word
        assert page.errors == []
    finally:
        ctx.close()


def test_the_box_uses_warning_colours_not_error_colours(browser, server):
    ctx, page = _page(browser, server)
    try:
        colours = page.evaluate(
            """() => {
              const probe = c => { const d = document.createElement('div');
                d.style.color = c; document.body.appendChild(d);
                const v = getComputedStyle(d).color; d.remove(); return v; };
              return {
                box: getComputedStyle(document.getElementById('schedule-empty')).borderTopColor,
                warn: probe('var(--warn-line)'),
                err: probe('var(--err-line)'),
              };
            }"""
        )
        assert colours["box"] == colours["warn"], colours
        assert colours["box"] != colours["err"], colours
    finally:
        ctx.close()


def _codes(page) -> list[str]:
    return page.evaluate(
        "() => JSON.parse(localStorage.getItem('%s')).codes" % KEY
    )


def test_the_swap_button_swaps_and_the_undo_puts_it_back(browser, server):
    ctx, page = _page(browser, server)
    try:
        page.click("#infeasible-suggestions > li:first-child button")
        page.wait_for_function(
            "() => document.getElementById('schedule-empty').hidden", timeout=20000
        )
        codes = _codes(page)
        assert "11210" in codes and "11026" not in codes, codes
        assert set(CORE) <= set(codes), codes

        undo = page.locator("#relax-undo")
        assert undo.is_visible(), "אין הודעת ביטול אחרי ההחלפה"
        notice = re.sub(r"\s+", " ", undo.inner_text())
        assert "החלפת" in notice and "11026" in notice and "11210" in notice, notice
        button = undo.locator("button")
        assert "11026" in button.inner_text(), button.inner_text()

        button.click()
        page.wait_for_function(
            "() => !document.getElementById('schedule-empty').hidden", timeout=20000
        )
        codes = _codes(page)
        assert "11026" in codes and "11210" not in codes, codes
        assert set(CORE) <= set(codes), codes
        assert page.locator("#relax-undo").is_hidden()
        assert page.errors == []
    finally:
        ctx.close()
