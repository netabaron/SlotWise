"""פרטי השיעור: שם הקורס והקוד שלו אינם נצמדים (DEFERRED.md, "The course code
runs into the course name in the lesson details", נסגר 2026-10-05).

הקוד הוא ‎<bdi dir="ltr">‎. ‏‎margin-inline-start‎ שלו נחת בקצה השמאלי — הרחוק
מהשם — ובפאנל נקרא "מבוא לבדיקות תוכנה61757", ברווח של 0px, ב-1000 וב-1440.
עכשיו הרווח יושב על השם, בצד שפונה אל הקוד.

נבדק כאן, ב-1000px (פאנל ליד המקרא) וב-1440px (פאנל במקום המקרא, פריסה רחבה):
* רווח מדוד של 4px לפחות בין התיבה של השם לתיבה של הקוד, והקוד משמאל לשם;
* כששניהם נכנסים ברוחב השורה — הם באותה שורה;
* הקוד נשאר ‎dir="ltr"‎, מושתק, 13px.

הבחירה: הנדסת תוכנה, שנה ג', סמסטר א', הקורסים המומלצים.
"""

from __future__ import annotations

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

MIN_GAP = 4


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


#: לכל שורת "קורס" בפאנל: התיבות של השם ושל הקוד, ורוחב השורה.
ROWS = """() => [...document.querySelectorAll('#meeting-detail .detail-code')].map(code => {
  const dd = code.parentElement;
  // ‏השם הוא הילד הראשון של השורה — בלי להסתמך על המחלקה שהתיקון הוסיף.
  const name = dd.firstElementChild;
  const c = code.getBoundingClientRect();
  // ‏השורה של השם שבה יושב הקוד: האחרונה, כששם ארוך נשבר.
  const lines = [...name.getClientRects()];
  const n = lines[lines.length - 1];
  // ‏הרוחב הטבעי של השם, בלי שבירה — כדי לדעת אם שניהם "נכנסים" בשורה אחת.
  name.style.whiteSpace = 'nowrap';
  const natural = name.getBoundingClientRect().width;
  name.style.whiteSpace = '';
  const cs = getComputedStyle(code);
  const probe = document.createElement('span');
  probe.style.color = 'var(--muted)';
  dd.appendChild(probe);
  const muted = getComputedStyle(probe).color;
  probe.remove();
  return {name: name.textContent, code: code.textContent,
          nameRect: {l: n.left, r: n.right, t: n.top, b: n.bottom, w: natural},
          codeRect: {l: c.left, r: c.right, t: c.top, b: c.bottom, w: c.width},
          nameLines: name.getClientRects().length, codeLines: code.getClientRects().length,
          ddWidth: dd.clientWidth, dir: code.getAttribute('dir'),
          color: cs.color, muted: muted, size: cs.fontSize,
          text: dd.textContent};
})"""


@pytest.mark.parametrize("width", [1000, 1440])
def test_the_course_name_and_its_code_do_not_touch(browser, server, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900}, color_scheme="light")
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    try:
        pg.goto(server)
        pg.wait_for_timeout(2500)
        pg.select_option("#select-program", "הנדסת תוכנה")
        pg.select_option("#select-year", "3")
        pg.select_option("#select-term", "א")
        pg.wait_for_timeout(2500)
        pg.click("#btn-restore-recommended")
        pg.wait_for_selector("#schedule-grid .ev", timeout=20000)
        pg.wait_for_timeout(1500)
        blocks = pg.locator("#schedule-grid .ev").count()
        assert blocks > 0
        checked = 0
        for i in range(blocks):
            pg.evaluate(f"document.querySelectorAll('#schedule-grid .ev')[{i}].click()")
            pg.wait_for_timeout(250)
            for row in pg.evaluate(ROWS):
                n, c = row["nameRect"], row["codeRect"]
                # ‏RTL: הקוד משמאל לשורה האחרונה של השם, כשהם באותה שורה.
                on_name_line = abs(n["t"] - c["t"]) < 1
                if on_name_line:
                    gap = n["l"] - c["r"]
                    assert gap >= MIN_GAP, f"{width}px: רווח {gap:.1f}px בין '{row['name']}' ל-{row['code']}"
                # ‏כשהשם (ברוחבו הטבעי), הרווח והקוד נכנסים ברוחב השורה — שורה אחת.
                if n["w"] + c["w"] + MIN_GAP <= row["ddWidth"]:
                    assert on_name_line and row["nameLines"] == 1, (
                        f"{width}px: '{row['name']}' ו-{row['code']} בשתי שורות למרות שנכנסים: {row}")
                assert row["codeLines"] == 1, row
                assert row["dir"] == "ltr", row
                assert row["color"] == row["muted"] and row["size"] == "13px", row
                # הרווח אינו תו בתוך הקוד.
                assert row["code"] == row["code"].strip(), row
                checked += 1
        assert checked >= blocks, f"נבדקו {checked} שורות קורס מ-{blocks} בלוקים"
        assert errors == []
    finally:
        ctx.close()
