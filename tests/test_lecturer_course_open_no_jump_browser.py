"""פתיחת קורס בשלב המרצים אינה מקפיצה את העמוד (docs/DESIGN.md, "Scroll
behaviour", פריט 3, "Opening a course keeps its head in place", ‏2026-10-13).

הבאג: ‏``rebuild()`` מרוקן את ‏``#lecturer-courses`` לפני שהוא בונה אותו
מחדש. כל עוד המכולה ריקה העמוד קצר מהמסך, הדפדפן מצמיד את ‏scrollY ל-0,
והוא נשאר 0 גם אחרי הבנייה. ב-1440x900: ‏605 → 0 בפריים אחד.

מה נבדק כאן, ב-1440x900: ראש קורס סגור באמצע המסך, עם ‏scrollY > 0. לוחצים
עליו ודוגמים בכל פריים: ‏scrollY אף פעם לא יורד ל-0, וראש הקורס זז פחות
מ-40px ממקומו לפני הלחיצה.

רץ על מסד ה-fixture (‏``scripts/seed_dev_data.py --fixture``), כמו ב-CI.
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

DESKTOP = (1440, 900)
#: ‏התזוזה הגדולה ביותר שמותרת לראש הקורס ממקומו לפני הלחיצה.
MAX_DRIFT = 40

#: ‏דוגם את ראש הקורס בכל פריים, אחרי שהפריים צויר (‏rAF ואז ‏MessageChannel),
#: ‏במשך ‎ms‎. הראש נמצא מחדש בכל דגימה לפי ‏data-fk: ‏``rebuild()`` מחליף
#: ‏את האלמנט, ואלמנט שנשמר מראש כבר אינו במסמך.
SAMPLER = """([fk, ms]) => {
  const find = () => document.querySelector('[data-fk="' + fk + '"]');
  window.__samples = [];
  window.__settled = false;
  const t0 = performance.now();
  const ch = new MessageChannel();
  ch.port1.onmessage = () => sample();
  const tick = () => ch.port2.postMessage(0);
  const sample = () => {
    const t = performance.now() - t0;
    const head = find();
    window.__samples.push({
      t,
      top: head ? head.getBoundingClientRect().top : null,
      y: window.scrollY,
    });
    if (t >= ms) {
      window.__settled = true;
      return;
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}"""

#: ‏ראש הקורס הסגור הראשון אחרי הקורס הפתוח (או הראשון, אם אף אחד לא פתוח).
NEXT_CLOSED_HEAD = """() => {
  const heads = Array.from(
    document.querySelectorAll('#lecturer-courses button.lect-course-head')
  );
  const open = heads.findIndex((h) => h.getAttribute('aria-expanded') === 'true');
  const next = heads.slice(open + 1).find(
    (h) => h.getAttribute('aria-expanded') === 'false'
  );
  return next ? next.dataset.fk : null;
}"""


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


def _next(pg, key, wait=1500):
    pg.click(f"#step-{key}-next")
    pg.wait_for_timeout(wait)


def test_opening_the_next_course_keeps_its_head_in_place(browser, server):
    ctx = browser.new_context(
        viewport={"width": DESKTOP[0], "height": DESKTOP[1]},
        color_scheme="light",
    )
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    try:
        pg.goto(server)
        pg.wait_for_timeout(3000)

        # ‏הנדסת תוכנה, שנה 3, סמסטר א, הקורסים המומלצים, ו"המשך" עד המרצים.
        pg.select_option("#select-program", "הנדסת תוכנה")
        pg.select_option("#select-year", "3")
        pg.select_option("#select-term", "א")
        pg.wait_for_timeout(2500)
        _next(pg, "year")
        pg.click("#btn-restore-recommended")
        pg.wait_for_selector("#alt-cards .alt-card", timeout=20000)
        pg.wait_for_timeout(1000)
        _next(pg, "courses")
        _next(pg, "days")

        fk = pg.evaluate(NEXT_CLOSED_HEAD)
        assert fk, "אין בשלב המרצים קורס סגור ללחוץ עליו"
        sel = f'[data-fk="{fk}"]'

        # ‏ראש הקורס באמצע המסך, ו-scrollY > 0.
        pg.evaluate(
            """(sel) => {
              const r = document.querySelector(sel).getBoundingClientRect();
              window.scrollBy(0, r.top - window.innerHeight / 2);
            }""",
            sel,
        )
        pg.wait_for_timeout(600)
        y0 = pg.evaluate("window.scrollY")
        top0 = pg.evaluate(f"document.querySelector('{sel}').getBoundingClientRect().top")
        assert y0 > 0, f"העמוד לא נגלל לפני הלחיצה (scrollY={y0})"
        assert 0 < top0 < DESKTOP[1], f"ראש הקורס לא על המסך ({top0:.1f}px)"

        pg.evaluate(SAMPLER, [fk, 1500])
        pg.click(sel)
        pg.wait_for_function("window.__settled === true", timeout=10000)
        samples = pg.evaluate("window.__samples")

        assert len(samples) > 10, f"מעט מדי פריימים נדגמו ({len(samples)})"
        assert pg.evaluate(
            f"document.querySelector('{sel}').getAttribute('aria-expanded')"
        ) == "true", "הקורס לא נפתח"

        zero = [(s["t"], s["y"]) for s in samples if s["y"] <= 0]
        assert not zero, (
            f"העמוד קפץ לראשו (scrollY לפני הלחיצה {y0}); (t ms, scrollY): {zero[:5]}"
        )

        drift = [
            (s["t"], s["top"])
            for s in samples
            if s["top"] is None or abs(s["top"] - top0) >= MAX_DRIFT
        ]
        assert not drift, (
            f"ראש הקורס זז {MAX_DRIFT}px או יותר ממקומו ({top0:.1f}px); "
            f"(t ms, top): {drift[:5]}"
        )
        assert not errors, errors
    finally:
        ctx.close()
