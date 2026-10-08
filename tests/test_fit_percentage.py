"""ההתאמה: תווית לראשונה בסדר, ובלי מספר.

למה הקובץ הזה קיים
-------------------
עד 2026-09-08 ההתאמה הוצגה כ-``"{score} / 100"``, ובטבלת ההשוואה היא **הוצגה
הפוכה** (``100 / 87``); היא הוחלפה באחוז אחד, שאינו יכול להתהפך. הבדיקות של
האחוז — הנוסח, ההסבר, המעצב היחיד והגאומטריה — חיו כאן.

מאז 2026-10-09 **אין אחוז בכלל** (docs/DESIGN.md → Results page, פריט 4): הסדר
הוא לפי עדיפות — ימים, מרצים, חפיפות, ורק אז הניקוד — ואחוז מהניקוד היה יכול
להציב חלופה נמוכה מעל גבוהה. מה שנשאר לבדוק: הראשונה בסדר השרת נושאת את
התווית "ההתאמה הגבוהה ביותר", פעם אחת, ולשאר אין שבב התאמה.
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

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 2. מה שמצויר בפועל
# --------------------------------------------------------------------------
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
def page(server):
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        pg = browser.new_page(viewport={"width": 1440, "height": 1000})
        pg.goto(server)
        pg.wait_for_timeout(3000)
        # ‏שלב 1 הוא זהות מאז 2026-09-09: בלי מסלול, שנה וסמסטר אין מערכת,
        # ולכן אין גם ציון התאמה לבדוק.
        pg.select_option("#select-program", "הנדסת תוכנה")
        pg.select_option("#select-year", "3")
        pg.select_option("#select-term", "א")
        pg.wait_for_timeout(2500)
        pg.click("#step-year-next")  # "המשך" אל שלב הקורסים (Phase 8, באישור 2026-10-06)
        # ‏הקורסים אינם מסומנים מראש; בלי סימון אין מערכת ואין ציון התאמה.
        pg.click("#btn-restore-recommended")
        pg.wait_for_timeout(6000)
        pg.click("#step-courses-next")  # "המשך" אל ימי הלימוד (Phase 8, באישור 2026-10-06)
        # ‏ובוחרים יעד ימים. בלי יעד אין קנס על מספר הימים, חמש המערכות
        # יוצאות שקולות, והפאנל מציג ‎fitTied‎ במקום תווית המובילה — נכון
        # לגמרי, אבל אז אין כאן מה לבדוק.
        pg.click('.day-btn[data-days="4"]')
        pg.wait_for_timeout(6000)
        try:
            yield pg
        finally:
            browser.close()


BEST_LABEL = STRINGS["app"]["compare"]["bestOverall"]

#: בורר מערכת לפי אינדקס בשרת, ומחזיר כמה חלופות יש. ‏מאז שלב 6 (2026-10-01)
#: אלה הכרטיסים, וכל כרטיס נושא את מספרו הקבוע — הדירוג בשרת — ב-data-rank.
SELECT = """(i) => {
  const cards = [...document.querySelectorAll('#alt-cards .alt-card')]
    .sort((a, b) => a.dataset.rank - b.dataset.rank);
  if (cards[i]) cards[i].click();
  return cards.length;
}"""

FIT_STATE = """() => {
  const v = document.querySelector('.fit-value');
  if (!v) return null;
  return {text: v.textContent.trim(), best: v.classList.contains('fit-value--best'),
          ltr: v.classList.contains('ltr'),
          hasLabel: !!document.querySelector('.fit .fit-label')};
}"""


def test_the_top_ranked_schedule_is_labelled_not_scored(page):
    """‏fitScores() נותן 100 לטובה מבין המוצגות, ולכן היא מגדירה את הרף.

    ‏"100%" שם נשמע כמו התאמה מושלמת. התווית אומרת את אותו דבר בלי
    ההבטחה הזאת.
    """
    page.evaluate(SELECT, 0)
    page.wait_for_timeout(400)
    got = page.evaluate(FIT_STATE)
    assert got, "לא נמצא פאנל ההתאמה"
    assert got["best"], f"המערכת הראשונה עדיין מציגה מספר: {got['text']!r}"
    assert got["text"] == BEST_LABEL, got["text"]
    assert "%" not in got["text"]
    assert not got["ltr"], "‏class=ltr כופה direction: ltr על משפט עברי"
    assert not got["hasLabel"], (
        "‏'התאמה' לצד 'ההתאמה הגבוהה ביותר' קורא 'התאמה · ההתאמה הגבוהה ביותר'")


def test_the_label_is_not_shown_twice(page):
    """הכותרת המבדילה יכולה לומר בדיוק את אותו משפט. אז היא נסוגה."""
    page.evaluate(SELECT, 0)
    page.wait_for_timeout(400)
    count = page.evaluate(
        "(t) => [...document.querySelectorAll('.fit *')]"
        "        .filter(e => e.textContent.trim() === t).length", BEST_LABEL)
    assert count <= 1, f"‏{BEST_LABEL!r} מופיע {count} פעמים בפאנל אחד"


def test_a_lower_ranked_schedule_shows_no_fit_pill(page):
    """התווית היא לראשונה בלבד, ולשאר אין שבב התאמה — לא אחוז ולא תווית."""
    total = page.evaluate(SELECT, 0)
    assert total > 1, "צריך יותר ממערכת אחת כדי לבדוק את השאר"
    seen = []
    for i in range(1, total):
        page.evaluate(SELECT, i)
        page.wait_for_timeout(400)
        seen.append(page.evaluate("() => !!document.querySelector('#schedule-summary .stat-pill.fit')"))
    page.evaluate(SELECT, 0)
    page.wait_for_timeout(300)
    assert not any(seen), seen
