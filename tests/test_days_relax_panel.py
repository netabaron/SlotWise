"""‏"מה יאפשר N ימים" — קצר (docs/DESIGN.md, עיקרון 5).

כשאין ויתור בודד שמגיע ליעד: שורה אחת, וזהו — בלי רשימת מה שנבדק ובלי
ההסתייגות על קורסי חובה. כשיש: הרשימה, וההסתייגות פעם אחת, במשפט אחד.

בקטלוג הקפוא, הנדסת תוכנה שנה ג׳ סמסטר א׳ עם כל המומלצים: המינימום 4,
יעד 2 אינו מושג בשום ויתור בודד, ויעד 3 מושג בשני ויתורים.
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


STORAGE_KEY = "braude_schedule_builder_v1"  # אין לשנותו — ראו CLAUDE.md

#: ‏כל מתגי חובת הנוכחות דלוקים, כמו שהיו לפני 2026-10-10. מאז המתג כבוי בכל
#: ‏רכיב שהידיעון אינו מחייב בו נוכחות (docs/DESIGN.md, "The switch starts off"),
#: ‏וחפיפות מגיעות ל-2 ימים בוויתור על 61759 — כלומר הפאנל של יעד 2 כבר אינו
#: ‏"אין ויתור". עם המתגים דלוקים שני הפאנלים בודקים את מה שבדקו קודם.
ALL_ON = {
    "11069": {'שו"ת': True},
    "61756": {"הרצאה": True, "תרגול": True, "פרויקט": True},
    "61757": {"הרצאה": True, "מעבדה": True},
    "62027": {"הרצאה": True, "תרגול": True},
    "61759": {"הרצאה": True, "תרגול": True},
    "61832": {"הרצאה": True, "תרגול": True},
}


PANEL = """() => {
  const r = document.getElementById('days-relax');
  const vis = e => !e.hidden && getComputedStyle(e).display !== 'none';
  return {shown: vis(r),
          visible: [...r.children].filter(vis).map(e => e.id),
          text: r.innerText.trim(),
          items: r.querySelectorAll('#days-relax-list > li').length};
}"""


@pytest.fixture(scope="module")
def panels(server):
    """שני היעדים באותו דף: ‏2 (אין ויתור) ו-3 (יש)."""
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Exception as exc:
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            pg = b.new_page()
            pg.goto(server)
            pg.wait_for_timeout(3500)
            pg.evaluate(
                """(a) => { const s = JSON.parse(localStorage.getItem(a.key) || '{}');
                            s.attendance = a.attendance; localStorage.setItem(a.key, JSON.stringify(s)); }""",
                {"key": STORAGE_KEY, "attendance": ALL_ON},
            )
            pg.reload()
            pg.wait_for_timeout(3500)
            pg.select_option("#select-program", "הנדסת תוכנה")
            pg.select_option("#select-year", "3")
            pg.select_option("#select-term", "א")
            pg.wait_for_timeout(2500)
            pg.click("#step-year-next")  # "המשך" אל שלב הקורסים (Phase 8, באישור 2026-10-06)
            pg.click("#btn-restore-recommended")
            pg.wait_for_timeout(5000)
            pg.click("#step-courses-next")  # "המשך" אל ימי הלימוד (Phase 8, באישור 2026-10-06)
            out = {}
            for d in (2, 3):
                pg.click(f'.day-btn[data-days="{d}"]')
                pg.wait_for_timeout(4000)
                out[d] = pg.evaluate(PANEL)
        finally:
            b.close()
    return out


def test_nothing_reaches_it_is_one_line(panels):
    p = panels[2]
    assert p["shown"], p
    assert p["visible"] == ["days-relax-intro"], f"רק השורה האחת: {p}"
    assert p["text"] == "אי אפשר להגיע ל-2 ימים, גם בוויתור על קורס אחד.", p["text"]
    assert "נבדקו" not in p["text"] and "חובה" not in p["text"], p["text"]


def test_a_drop_that_reaches_it_is_listed_with_one_note(panels):
    p = panels[3]
    assert p["shown"], p
    assert p["visible"] == ["days-relax-title", "days-relax-list", "days-relax-note"], p
    assert p["items"] >= 1, p
    assert "נבדקו ולא הספיקו" not in p["text"], "רשימת מה שנבדק ולא הספיק הוסרה"
    assert "בדקנו כל קורס בנפרד" not in p["text"], p["text"]
    note_lines = [line for line in p["text"].splitlines() if "חובה" in line]
    assert note_lines == ["לא בדקנו אילו מהקורסים חובה לתואר שלך."], note_lines
