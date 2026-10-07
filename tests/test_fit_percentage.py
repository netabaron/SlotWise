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
    # ‏ההגדרה ושבב ההתאמה. טבלת "מה ההבדל?", אתר התצוגה השני, הוסרה בשלב 6
    # של העיצוב (2026-10-01); ההבטחה עצמה — אין קריאה ישירה — נבדקת למעלה.
    assert APP_JS.count("fmtFit(") >= 2


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


def test_a_lower_ranked_schedule_still_shows_a_percentage(page):
    """התווית היא למובילה בלבד; כל השאר נשארות מספר."""
    total = page.evaluate(SELECT, 0)
    found = None
    for i in range(1, total):
        page.evaluate(SELECT, i)
        page.wait_for_timeout(400)
        got = page.evaluate(FIT_STATE)
        if got and not got["best"]:
            found = got
            break
    page.evaluate(SELECT, 0)
    page.wait_for_timeout(300)
    if found is None:
        pytest.skip("כל המערכות המוצגות שקולות — אין מערכת שאינה המובילה")
    assert re.fullmatch(r"\d{1,3}%", found["text"]), found["text"]
    assert "/" not in found["text"]
    assert found["ltr"], "מספר חייב להישאר מבודד ב-ltr"
    assert found["hasLabel"], "מספר בלי 'התאמה' לצדו אינו אומר מה הוא מודד"


def _select_a_numeric_schedule(page) -> bool:
    """בורר מערכת שאינה המובילה, כי רק שם ההתאמה היא מספר."""
    total = page.evaluate(SELECT, 0)
    for i in range(0, total):
        page.evaluate(SELECT, i)
        page.wait_for_timeout(400)
        got = page.evaluate(FIT_STATE)
        if got and not got["best"]:
            return True
    return False


@pytest.mark.parametrize(
    "where,selector",
    [
        # ‏עד שלב 6 נבדקה כאן גם טבלת "מה ההבדל?" — האתר שבו ההיפוך קרה. הטבלה
        # הוסרה (2026-10-01). זה האתר שנשאר: ‎.ltr‎ מגן עליו, ונבדק כדי שההגנה
        # לא תוסר בשקט.
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
    if selector == ".fit-value":
        # ‏במערכת המובילה הפאנל מציג משפט עברי, ושם ימין-לשמאל הוא הנכון.
        # הבדיקה הזאת עוסקת בסדר של מספר, ולכן בוחרים מערכת שמציגה מספר.
        if not _select_a_numeric_schedule(page):
            pytest.skip("כל המערכות שקולות — אין מספר לבדוק את סדרו")
    got = page.evaluate(FIRST_LAST, selector)
    page.evaluate(SELECT, 0)
    assert got, f"לא נמצא טקסט ב{where}"
    assert got["firstLeft"] < got["lastLeft"], (
        f"ההתאמה מצוירת הפוכה ב{where}: {got['text']!r} — "
        f"התו הראשון ב-{got['firstLeft']:.1f}, האחרון ב-{got['lastLeft']:.1f}")
