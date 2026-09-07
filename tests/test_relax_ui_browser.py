# -*- coding: utf-8 -*-
"""מצב "אין פתרון" בדפדפן — הוויתורים, המחיר, והביטול.

הבדיקות כאן טוענות את הדף כמו משתמש/ת, עם מצב שמור שמייצר בכוונה מערכת
בלתי פתירה. שלוש התחייבויות נבדקות מהצד של המסך:

1. מספר שמוצג הוא מספר שנמדד. חיפוש שלא הסתיים אינו מציג מספר.
2. הוויתור אומר מה הוא גובה, לא רק מה הוא פותח.
3. הביטול שם את מה שהוא מחזיר, ונעלם כשהוא כבר לא תקף.
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

KEY = "braude_schedule_builder_v1"
CODES = ["11069", "61756", "61757", "62027", "61759", "61832"]


def _seed(**kw):
    base = {
        "schema": 1, "studyYear": 3, "term": "א", "semester": "5",
        "codes": CODES, "known": {}, "program": "הנדסת תוכנה", "topN": 5,
        "activeSchedule": 0, "targetDays": 4, "provenanceReady": True,
        "autoSemester": "5", "autoCodes": CODES, "manualCodes": [],
        "autoDropped": [],
    }
    base.update(kw)
    return base


@pytest.fixture(scope="module")
def server():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = make_server("127.0.0.1", port,
                      create_app(config={"allow_network": False}), threaded=True)
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


def _page(browser, server, state):
    ctx = browser.new_context(viewport={"width": 1100, "height": 1000})
    ctx.add_init_script(
        "localStorage.setItem('%s', %s);" % (KEY, json.dumps(json.dumps(state)))
    )
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.goto(server)
    page.wait_for_timeout(6500)
    return ctx, page


# ==========================================================================
# 1. ויתור בודד שעוזר
# ==========================================================================
def test_a_single_relaxation_shows_a_measured_count_and_its_cost(browser, server):
    ctx, page = _page(browser, server, _seed(latest=780))  # 13:00
    try:
        assert not page.evaluate("document.getElementById('schedule-empty').hidden")
        assert not page.evaluate("document.getElementById('relax').hidden")
        row = page.evaluate(
            """() => {
              const r = document.querySelector('.relax-row');
              const t = e => e ? e.textContent.replace(/\\s+/g,' ').trim() : '';
              return {what: t(r.querySelector('b')),
                      opens: t(r.querySelector('.relax-opens')),
                      cost: t(r.querySelector('.relax-cost')),
                      button: t(r.querySelector('button'))};
            }"""
        )
        assert "מערכות" in row["opens"], f"אין מספר מדוד: {row['opens']!r}"
        assert row["cost"], "ויתור בלי מחיר — מוכר את הרווח ומשמיט את המחיר"
        assert row["button"], "אין כפתור החלה"
        assert page.errors == []
    finally:
        ctx.close()


# ==========================================================================
# 2. זוגות — השורה הקשה ביותר על המסך
# ==========================================================================
def test_a_pairs_only_case_is_stated_plainly_and_stacked(browser, server):
    ctx, page = _page(
        browser, server, _seed(earliest=540, latest=960, forbidFriday=True)
    )
    try:
        out = page.evaluate(
            """() => {
              const t = e => e ? e.textContent.replace(/\\s+/g,' ').trim() : '';
              return {
                title: t(document.getElementById('relax-title')),
                lines: [].slice.call(
                  document.querySelectorAll('.relax-row .relax-pair-line')).map(t),
                both: t(document.querySelector('.relax-pair-both')),
                checked: t(document.getElementById('relax-checked')),
                brace: (() => {
                  const p = document.querySelector('.relax-pair');
                  if (!p) return '';
                  const cs = getComputedStyle(p);
                  return cs.borderInlineStartWidth;
                })(),
              };
            }"""
        )
        # הכותרת אומרת את זה במפורש, ולא משאירה רשימה ריקה
        assert "שילוב של שניים" in out["title"], out["title"]
        # שתי שורות, לא משפט אחד ארוך
        assert len(out["lines"]) == 2, f"השורה אינה מוצגת בשתי שורות: {out['lines']}"
        assert out["both"], "לא נאמר שמדובר בשניהם יחד"
        # הסוגר קיים ונמתח לגובה שתי השורות
        assert out["brace"] and out["brace"] != "0px", "אין סוגר על שורת הזוג"
        # ומה שהופך את הכותרת לדיווח ולא לטענה
        assert "נבדק לחוד" in out["checked"], out["checked"]
        assert page.errors == []
    finally:
        ctx.close()


def test_the_reasons_collapse_so_the_actionable_part_is_not_squeezed(browser, server):
    ctx, page = _page(browser, server, _seed(latest=780))
    try:
        out = page.evaluate(
            """() => ({
              visible: document.querySelectorAll('#infeasible-reasons > li').length,
              hasMore: !!document.querySelector('#infeasible-reasons details'),
              openByDefault: (() => {
                const d = document.querySelector('#infeasible-reasons details');
                return d ? d.open : null;
              })(),
            })"""
        )
        assert out["hasMore"], "הסיבות לא מתקפלות"
        assert out["openByDefault"] is False, "הגילוי פתוח כברירת מחדל"
        assert out["visible"] <= 2, "יותר מסיבה אחת גלויה מחוץ לגילוי"
    finally:
        ctx.close()


# ==========================================================================
# 3. הביטול
# ==========================================================================
def test_applying_shows_an_undo_that_names_what_it_restores(browser, server):
    ctx, page = _page(browser, server, _seed(latest=780))
    try:
        page.click(".relax-row button")
        page.wait_for_timeout(3500)
        undo = page.evaluate(
            """() => {
              const n = document.getElementById('relax-undo');
              const t = e => e ? e.textContent.replace(/\\s+/g,' ').trim() : '';
              return {hidden: n.hidden, notice: t(n.querySelector('.relax-undo-text')),
                      button: t(n.querySelector('button'))};
            }"""
        )
        assert not undo["hidden"], "אין הודעת ביטול אחרי החלה"
        assert "החזר" in undo["button"], f"כפתור לא ממוקד: {undo['button']!r}"
        # "בטל" לבדו אינו אומר מה חוזר
        assert undo["button"].strip() not in ("בטל", "ביטול")
        assert "השעה המאוחרת" in undo["button"], undo["button"]
        assert page.errors == []
    finally:
        ctx.close()


def test_undo_restores_exactly_what_was_relaxed(browser, server):
    ctx, page = _page(browser, server, _seed(latest=780))
    try:
        page.click(".relax-row button")
        page.wait_for_timeout(3500)
        page.click("#relax-undo button")
        page.wait_for_timeout(3500)
        state = page.evaluate("window.slotwise.getState()")
        assert state["latest"] == 780, f"האילוץ לא הוחזר: latest={state['latest']}"
        assert page.evaluate("document.getElementById('relax-undo').hidden")
    finally:
        ctx.close()


def test_the_undo_disappears_once_the_same_constraint_is_changed_again(browser, server):
    """ביטול שמחזיר מצב שכבר אינו קיים גרוע מהיעדר ביטול."""
    ctx, page = _page(browser, server, _seed(latest=780))
    try:
        page.click(".relax-row button")
        page.wait_for_timeout(3500)
        assert not page.evaluate("document.getElementById('relax-undo').hidden")
        # המשתמש/ת משנה בעצמה את אותו אילוץ
        page.evaluate("window.slotwise.setStateForTest "
                      "? window.slotwise.setStateForTest({latest: 1200}) : null")
        page.evaluate("""() => {
          const s = JSON.parse(localStorage.getItem('%s'));
          s.latest = 1200; localStorage.setItem('%s', JSON.stringify(s));
        }""" % (KEY, KEY))
        page.reload()
        page.wait_for_timeout(6000)
        assert page.evaluate("document.getElementById('relax-undo').hidden"), (
            "הביטול שרד שינוי ידני של אותו אילוץ"
        )
    finally:
        ctx.close()
