"""ההתאמה מוצגת כאחוז אחד, ולא כשני מספרים שאפשר להפוך ביניהם.

למה הקובץ הזה קיים
-------------------
עד 2026-09-08 הנוסח היה ``"{score} / 100"``. בפאנל הניקוד הוא נעטף
ב-``class="ltr"`` והוצג נכון; בטבלת ההשוואה אותה מחרוזת נכנסה ל-``<td>``
רגיל, ירשה את כיוון הדף, ו**הוצגה הפוכה** — ``100 / 87``. הטבלה הזאת היא
"התוספת בעלת הערך הגבוה ביותר בכל התדריך" לפי התדריך עצמו, והמספר שהיא
קיימת כדי להשוות הוא זה שהתהפך.

**הבדיקה החשובה כאן היא ``test_the_fit_is_not_visually_reversed``.**
בדיקת ``textContent`` לא הייתה תופסת את הבאג לעולם: ‏textContent מחזיר
את הסדר הלוגי, שהוא תמיד ``87 / 100``, גם כשהעין רואה ``100 / 87``.
היפוך דו-כיווני נראה רק בגאומטריה, ולכן כאן נמדדים המלבנים של התו הראשון
ושל התו האחרון בפועל.

הבחירה באחוז אינה קוסמטית: ``%`` הוא ET, וכלל W5 של אלגוריתם
הדו-כיווניות מצרף ET צמוד ל-EN לאותו מקטע. מספר יחיד אינו יכול להתפצל
לשני מקטעים ולכן אינו יכול להתהפך — הסיבה סולקה, לא הסימפטום.
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

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
APP_JS = (ROOT / "src" / "web" / "static" / "app.js").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 1. הנוסח עצמו — מבנה, לא רק תוכן
# --------------------------------------------------------------------------
def test_the_fit_string_holds_one_number_and_no_separator():
    """שני מקטעי מספר עם נייטרלי ביניהם הם התנאי להיפוך. אסור שיחזור."""
    value = STRINGS["app"]["schedule"]["fitValue"]
    assert value == "{score}%", value
    without_placeholder = value.replace("{score}", "")
    assert not re.search(r"\d", without_placeholder), (
        f"מספר קבוע שני בנוסח ההתאמה מחזיר את תנאי ההיפוך: {value!r}")


def test_the_caveat_survives_the_change():
    """אחוז נשמע מוחלט יותר מציון, ולכן המשפט הזה חשוב עכשיו יותר."""
    title = STRINGS["app"]["schedule"]["fitTitle"]
    assert "ביחס לחמש המערכות המוצגות" in title, title
    assert "100%" in title, "הרף בהסבר חייב לשאת אותה יחידה כמו המספר"
    assert STRINGS["app"]["schedule"]["fitTied"]


def test_there_is_exactly_one_formatter():
    """כל אתר תצוגה עובר דרך fmtFit, אחרת נוסח שני יחזור בשקט."""
    assert APP_JS.count("function fmtFit(") == 1
    direct = re.findall(r'Tf\(\s*"app\.schedule\.fitValue"', APP_JS)
    assert len(direct) == 1, (
        "‏app.schedule.fitValue נקרא ישירות מחוץ ל-fmtFit — "
        f"{len(direct)} קריאות, ציפינו לאחת (זו שבתוך fmtFit)")
    assert APP_JS.count("fmtFit(") >= 3  # ההגדרה ושני אתרי התצוגה


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
        pg.wait_for_timeout(5000)
        pg.evaluate("() => { const d = document.getElementById('compare');"
                    " if (d) d.open = true; }")
        pg.wait_for_timeout(400)
        try:
            yield pg
        finally:
            browser.close()


#: מאתר את תא ההתאמה בטבלת ההשוואה — ‎<td>‎ ללא class="ltr", כלומר
#: האלמנט שבו ההיפוך באמת קרה.
COMPARE_FIT_CELL = """() => {
  const rows = [...document.querySelectorAll('.compare-table tbody tr')];
  const row = rows.find(r => (r.querySelector('th')?.textContent || '').trim() === 'התאמה');
  if (!row) return null;
  return row.querySelector('td.is-active') || row.querySelector('td');
}"""

#: מלבן התו הראשון ומלבן התו האחרון בתוך אלמנט, לפי הציור בפועל.
FIRST_LAST = """(sel) => {
  const el = sel === '@compare'
    ? (() => { const rows = [...document.querySelectorAll('.compare-table tbody tr')];
               const row = rows.find(r => (r.querySelector('th')?.textContent || '')
                                            .trim() === 'התאמה');
               return row && (row.querySelector('td.is-active') || row.querySelector('td')); })()
    : document.querySelector(sel);
  if (!el) return null;
  const node = [...el.childNodes].find(n => n.nodeType === 3 && n.textContent.trim());
  if (!node) return null;
  const text = node.textContent;
  const r = document.createRange();
  r.setStart(node, 0); r.setEnd(node, 1);
  const first = r.getBoundingClientRect();
  r.setStart(node, text.length - 1); r.setEnd(node, text.length);
  const last = r.getBoundingClientRect();
  return {text: text, firstLeft: first.left, lastLeft: last.left};
}"""


def test_the_score_panel_shows_a_percentage(page):
    text = page.text_content(".fit-value").strip()
    assert re.fullmatch(r"\d{1,3}%", text), text
    assert "/" not in text


def test_the_comparison_table_shows_the_same_percentage(page):
    """אותו מספר בשני המקומות — וגם זה נשבר פעם אחת בעבר."""
    cell = page.evaluate(
        """() => {
          const rows = [...document.querySelectorAll('.compare-table tbody tr')];
          const row = rows.find(r => (r.querySelector('th')?.textContent || '')
                                       .trim() === 'התאמה');
          if (!row) return null;
          const active = row.querySelector('td.is-active') || row.querySelector('td');
          return active ? active.textContent.trim() : null;
        }"""
    )
    assert cell, "לא נמצאה שורת ההתאמה בטבלת ההשוואה"
    assert re.fullmatch(r"\d{1,3}%", cell), cell
    assert "/" not in cell
    assert cell == page.text_content(".fit-value").strip()


@pytest.mark.parametrize(
    "where,selector",
    [
        # ‏זה האתר שנשבר. אין עליו class="ltr", ולכן הוא יורש את כיוון הדף.
        ("טבלת ההשוואה", "@compare"),
        # ‏זה האתר שלא נשבר — ‎.ltr‎ הגן עליו. נבדק כדי שההגנה לא תוסר בשקט.
        ("פאנל הניקוד", ".fit-value"),
    ],
)
def test_the_fit_is_not_visually_reversed(page, where, selector):
    """הבדיקה שהייתה תופסת את הבאג המקורי — ורק בגרסת הגאומטריה.

    ‏"87%" נצבע משמאל לימין: התו הראשון חייב לשבת שמאלה מהאחרון. עם
    הנוסח הישן ‏"87 / 100" בתוך ‎<td>‎ בעברית התו הראשון ישב **מימין**
    לאחרון, וזה בדיוק מה שנראה על המסך. ‏textContent היה מחזיר
    ‏"87 / 100" בשני המקרים ולא היה מבחין ביניהם כלל.
    """
    got = page.evaluate(FIRST_LAST, selector)
    assert got, f"לא נמצא טקסט ב{where}"
    assert got["firstLeft"] < got["lastLeft"], (
        f"ההתאמה מצוירת הפוכה ב{where}: {got['text']!r} — "
        f"התו הראשון ב-{got['firstLeft']:.1f}, האחרון ב-{got['lastLeft']:.1f}")
