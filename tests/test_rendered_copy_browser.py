"""הדף באמת מציג טקסט — לא רק נטען בלי לקרוס.

למה הקובץ הזה קיים
-------------------
עמוד שבו **כל** התוויות ריקות עבר 548 בדיקות. זה לא היה מזל רע אלא פער
אמיתי בכיסוי: אף בדיקה לא הסתכלה על טקסט מצויר.

* ``test_web.py`` דורש "לפחות אות עברית אחת בעמוד" — והערת חוזה ה-DOM
  שבראש ``index.html`` מלאה עברית, ולכן התנאי מתקיים גם כשכל תווית ריקה.
* בדיקות ה-Playwright הקיימות נוגעות רק בשלב 2 — קודי קורס, תגיות
  וסימוני בחירה — וכל אלה מגיעים מנתוני השרת, לא מ-``strings.json``.

**הדף נטען כאן כמו שהוא נטען אצל משתמש/ת: בלי מצב שמור.** גרסה קודמת של
הקובץ הזה הזריעה ‏localStorage מלא, וכך בדקה מסך שכבר יש בו קורסים ומערכת
מחושבת — כלומר בדיוק לא את הציור הראשון, שבו רוב המצבים הריקים מופיעים.
אחרי הטעינה הבדיקה גם צועדת בזרימה, ובכל שלב סורקת את כל ה-DOM.
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

#: הסימן ש-T() מחזיר למפתח נוסח חסר.
OPEN_MARK = "⟦"

#: סורק את **כל** ה-DOM — לא רשימת סלקטורים — ומחזיר כל מופע של הסימן,
#: כולל בתוך title / aria-label / placeholder, שם תווית חסרה לא נראית לעין
#: אבל כן נשמעת לקורא מסך.
SCAN = """() => {
  const MARK = '\\u27E6';
  const hits = [];
  const seen = new Set();
  const push = (where, text) => {
    const key = where + '::' + text;
    if (!seen.has(key)) { seen.add(key); hits.push(key); }
  };
  document.querySelectorAll('body *').forEach(function (el) {
    if (!el.children.length) {
      const t = (el.textContent || '').trim();
      if (t.indexOf(MARK) !== -1) push('text', t);
    }
    ['title', 'aria-label', 'placeholder', 'alt'].forEach(function (attr) {
      const v = el.getAttribute && el.getAttribute(attr);
      if (v && v.indexOf(MARK) !== -1) push(attr, v);
    });
  });
  if (document.title.indexOf(MARK) !== -1) push('document.title', document.title);
  return hits;
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
            instance = pw.chromium.launch()
        except Exception as exc:  # אין דפדפן מותקן — לא כישלון של הקוד
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            yield instance
        finally:
            instance.close()


def _open(browser, url):
    ctx = browser.new_context()
    p = ctx.new_page()
    p.errors = []  # type: ignore[attr-defined]
    p.on("pageerror", lambda e: p.errors.append(str(e)))  # type: ignore[attr-defined]
    p.goto(url)
    p.wait_for_timeout(4000)
    return ctx, p


@pytest.fixture()
def fresh(browser, server):
    """טעינה נקייה, בדיוק כמו כניסה ראשונה: אין ‏localStorage ואין ?debug."""
    ctx, p = _open(browser, server)
    try:
        yield p
    finally:
        ctx.close()


@pytest.fixture()
def dev(browser, server):
    """אותה טעינה, במצב ניפוי.

    הסימן ⟦…⟧ והמסגרת האדומה קיימים **רק** ב-?debug=1: סטודנט/ית לא
    אמורים לראות שם מפתח פנימי. לכן סריקת הסימנים רצה כאן, ואילו הרישום
    ב-``missingStrings()`` נבדק גם בטעינה הרגילה.
    """
    ctx, p = _open(browser, server + "?debug=1")
    try:
        yield p
    finally:
        ctx.close()


def scan(page, stage: str) -> list[str]:
    return [stage + " | " + h for h in page.evaluate(SCAN)]


# ==========================================================================
# 1. מקור הנוסח הגיע, ובשלמותו
# ==========================================================================
def test_strings_reach_the_browser(fresh):
    assert fresh.evaluate("!window.slotwise.stringsEmpty()"), (
        "‏window.STRINGS ריק — כל הטקסט בממשק ייעלם"
    )
    branches = fresh.evaluate("Object.keys(window.STRINGS).sort()")
    for need in ("app", "meta", "server", "ui"):
        assert need in branches, f"חסר ענף {need}; יש רק {branches}"


def test_app_branch_is_whole(fresh):
    """‏הזרקה חלקית הייתה נראית בדיוק כמו התקלה שדווחה: השרת תקין, הלקוח ריק."""
    subs = fresh.evaluate("Object.keys(window.STRINGS.app).sort()")
    for need in ("grid", "header", "lecturers", "schedule", "sticky", "steps", "score"):
        assert need in subs, f"חסר app.{need}; יש רק {subs}"


# ==========================================================================
# 2. סריקת ה-DOM לאורך הזרימה
# ==========================================================================
def test_no_missing_keys_on_first_render(dev):
    """הציור הראשון, בלי מצב שמור — המסך שרואים בכניסה."""
    hits = scan(dev, "first-render")
    assert hits == [], "מפתחות חסרים בציור הראשון:\n  " + "\n  ".join(hits)


def test_no_missing_keys_while_stepping_through(dev):
    """צועדים בזרימה, וסורקים בכל שלב.

    כל שלב מצייר מצבים אחרים — רשימת קורסים, תוצאות חיפוש, טבלאות
    הקבוצות, פאנל הניקוד, הרשת, השכבה — ולכל אחד מהם נוסח משלו.
    """
    hits: list[str] = []
    hits += scan(dev, "load")

    dev.select_option("#select-year", "3")
    dev.select_option("#select-term", "א")
    dev.wait_for_timeout(2500)
    hits += scan(dev, "year+term")

    dev.fill("#course-search", "61753")
    dev.wait_for_timeout(1500)
    hits += scan(dev, "search")
    try:
        dev.click("#course-search-results li >> nth=0")
        dev.wait_for_timeout(2500)
        hits += scan(dev, "course-added")
    except Exception:
        pass

    for key in ("courses", "days", "lecturers"):
        try:
            if dev.evaluate(
                "document.getElementById('step-%s')"
                ".classList.contains('is-collapsed')" % key
            ):
                dev.click("#step-%s-toggle" % key)
                dev.wait_for_timeout(500)
        except Exception:
            pass
    dev.wait_for_timeout(1200)
    hits += scan(dev, "steps-expanded")

    try:
        dev.click('.day-btn[data-days="3"]')
        dev.wait_for_timeout(2000)
        hits += scan(dev, "days-3")
    except Exception:
        pass

    try:
        dev.evaluate("document.getElementById('tech-details').open = true")
        dev.wait_for_timeout(400)
        hits += scan(dev, "tech-details")
    except Exception:
        pass

    try:
        dev.evaluate("window.scrollTo(0, 1200)")
        dev.wait_for_timeout(600)
        dev.click("#btn-show-grid")
        dev.wait_for_timeout(1200)
        hits += scan(dev, "overlay")
        dev.keyboard.press("Escape")
        dev.wait_for_timeout(500)
    except Exception:
        pass

    assert hits == [], "מפתחות נוסח חסרים:\n  " + "\n  ".join(hits)


def test_missing_string_registry_is_empty(fresh):
    """גם מה שנרשם ולא הגיע ל-DOM — למשל נוסח שנכנס ל-title בלבד."""
    missing = fresh.evaluate("window.slotwise.missingStrings()")
    assert missing == [], "מפתחות שנרשמו כחסרים: " + ", ".join(missing)


# ==========================================================================
# 3. תוויות ריקות, ושמות מפתח באנגלית
# ==========================================================================
LABEL_SELECTORS = [
    ".btn",
    ".fact-label",
    ".panel-block-title",
    ".fit-label",
    ".penalty-label",
    ".step-name",
    ".step-hint",
    ".tab",
    ".theme-btn",
    ".label",
    ".lect-table thead th",
]


def test_no_empty_labels(fresh):
    fresh.select_option("#select-year", "3")
    fresh.select_option("#select-term", "א")
    fresh.wait_for_timeout(2500)
    for key in ("courses", "days", "lecturers"):
        try:
            if fresh.evaluate(
                "document.getElementById('step-%s')"
                ".classList.contains('is-collapsed')" % key
            ):
                fresh.click("#step-%s-toggle" % key)
                fresh.wait_for_timeout(400)
        except Exception:
            pass
    fresh.wait_for_timeout(1000)
    empty = fresh.evaluate(
        """(sels) => {
      const bad = [];
      sels.forEach(function (sel) {
        document.querySelectorAll(sel).forEach(function (el) {
          if (el.offsetParent === null) return;
          if (el.closest('[hidden]')) return;
          if (!(el.textContent || '').trim()) {
            bad.push(sel + ' :: ' + (el.id || el.className));
          }
        });
      });
      return bad;
    }""",
        LABEL_SELECTORS,
    )
    assert empty == [], "תוויות ריקות: " + "; ".join(empty)


def test_no_raw_key_names_on_screen(fresh):
    """שם מפתח פנימי כטקסט — למשל ‏compactness כתווית של פס קנס."""
    fresh.select_option("#select-year", "3")
    fresh.select_option("#select-term", "א")
    fresh.wait_for_timeout(2500)
    found = fresh.evaluate(
        """() => {
      const keys = ['compactness','gaps','soft_conflict','late_finish',
                    'lecturer','days_count','elapsed_ms','feasible_count'];
      const bad = [];
      document.querySelectorAll('body *').forEach(function (el) {
        if (el.children.length) return;
        if (el.offsetParent === null) return;
        const t = (el.textContent || '').trim();
        if (t && keys.indexOf(t) !== -1) bad.push(t);
      });
      return bad;
    }"""
    )
    assert found == [], "שמות מפתח על המסך: " + "; ".join(found)


def test_key_screens_carry_hebrew(fresh):
    """כל אזור מרכזי נושא עברית משלו, ולא נשען על הערה שבראש הקובץ."""
    fresh.select_option("#select-year", "3")
    fresh.select_option("#select-term", "א")
    fresh.wait_for_timeout(2500)
    regions = {
        "כפתורי הכותרת": ".header-actions",
        "שלב 1": "#step-year .step-head",
        "שלב 2": "#step-courses .step-head",
        "פאנל הניקוד": "#schedule-summary",
        "לשוניות": "#schedule-tabs",
        "כותרות הרשת": "#schedule-grid",
        "תחתית": ".app-footer",
    }
    missing = fresh.evaluate(
        """(cfg) => {
      const re = new RegExp('[\\\\u0590-\\\\u05FF]');
      const bad = [];
      Object.keys(cfg).forEach(function (name) {
        const el = document.querySelector(cfg[name]);
        if (!el) { bad.push(name + ' (לא נמצא)'); return; }
        if (!re.test(el.textContent || '')) bad.push(name);
      });
      return bad;
    }""",
        regions,
    )
    assert missing == [], "אזורים בלי עברית: " + ", ".join(missing)


def test_no_javascript_errors(fresh):
    assert fresh.errors == [], "שגיאות JS: " + "; ".join(fresh.errors)


# ==========================================================================
# 4. הרשת: קיצוץ, ימים ריקים, ופאנל הפרטים
# ==========================================================================
def _with_schedule(page):
    """מביא את הדף למצב שבו יש מערכת מצוירת."""
    page.select_option("#select-year", "3")
    page.select_option("#select-term", "א")
    page.wait_for_timeout(3000)
    page.wait_for_selector("#schedule-grid .ev", timeout=15000)


def test_grid_blocks_are_buttons_and_reachable(fresh):
    """הבלוקים נגישים במקלדת.

    מרגע שהם מציגים שם ושעה בלבד, הפאנל הוא המקום היחיד שבו נמצאים
    מספר הקבוצה, המרצה והחדר — ולכן דרך עכבר בלבד אליו אינה מספיקה.
    """
    _with_schedule(fresh)
    tags = fresh.evaluate(
        "[].slice.call(document.querySelectorAll('#schedule-grid .ev'))"
        ".map(e => e.tagName)"
    )
    assert tags and set(tags) == {"BUTTON"}, f"בלוקים שאינם כפתור: {set(tags)}"
    labels = fresh.evaluate(
        "[].slice.call(document.querySelectorAll('#schedule-grid .ev'))"
        ".filter(e => !e.getAttribute('aria-label')).length"
    )
    assert labels == 0, "יש בלוק בלי aria-label"


def test_detail_panel_opens_by_keyboard_and_announces(fresh):
    """‏Enter פותח, הפוקוס עובר לדיאלוג, ‏Esc סוגר ומחזיר."""
    _with_schedule(fresh)
    fresh.focus("#schedule-grid .ev")
    fresh.keyboard.press("Enter")
    fresh.wait_for_timeout(600)

    assert fresh.evaluate("!document.getElementById('meeting-detail').hidden"), (
        "הפאנל לא נפתח ב-Enter"
    )
    # הכרזה = הפוקוס עובר לדיאלוג עם שם נגיש, ולא רק שינוי ויזואלי
    assert fresh.evaluate("document.activeElement.id === 'meeting-detail'"), (
        "הפוקוס לא עבר לפאנל — קורא מסך לא יכריז שנפתח משהו"
    )
    assert fresh.evaluate(
        "document.getElementById('meeting-detail').getAttribute('role')"
    ) == "dialog"
    assert fresh.evaluate(
        "!!document.getElementById('meeting-detail').getAttribute('aria-labelledby')"
    )

    body = fresh.evaluate(
        "document.getElementById('meeting-detail-body').textContent"
    )
    for need in ("קבוצה", "מרצה", "חדר"):
        assert need in body, f"הפאנל לא מציג {need} — ואין מקום אחר שבו הוא מופיע"

    fresh.keyboard.press("Escape")
    fresh.wait_for_timeout(500)
    assert fresh.evaluate("document.getElementById('meeting-detail').hidden")
    assert fresh.evaluate(
        "document.activeElement.classList.contains('ev')"
    ), "הפוקוס לא חזר לבלוק שממנו נפתח"


def test_grid_crops_and_toggle_only_ever_grows(fresh):
    """הקיצוץ לעולם אינו גדול מהטווח המלא.

    זו הייתה תקלה אמיתית: הריפוד של חצי שעה חרג מסוף היום, ולכן הרשת
    ה"מקוצצת" יצאה גבוהה מזו של "הצג את כל השעות" — מתג שעושה את ההפך
    ממה שכתוב עליו.
    """
    _with_schedule(fresh)
    height = lambda: fresh.evaluate(
        "Math.round(document.getElementById('schedule-grid').getBoundingClientRect().height)"
    )
    cropped = height()
    fresh.check("#chk-all-hours")
    fresh.wait_for_timeout(1500)
    full = height()
    assert full >= cropped, f"'כל השעות' ({full}) קטן מהמקוצץ ({cropped})"
    fresh.uncheck("#chk-all-hours")
    fresh.wait_for_timeout(1200)
    assert height() == cropped


def test_empty_days_collapse_but_stay_labelled(fresh):
    """יום בלי שיעורים נעשה צר — ועדיין אומר שהוא ריק."""
    _with_schedule(fresh)
    info = fresh.evaluate(
        """() => {
      const heads = [].slice.call(document.querySelectorAll('#schedule-grid .hd'));
      const empty = heads.filter(h => h.classList.contains('is-empty'));
      return {
        total: heads.length,
        empty: empty.length,
        labelled: empty.filter(h => (h.textContent || '').indexOf('אין שיעורים') !== -1).length,
      };
    }"""
    )
    assert info["total"] == 7, "שבע כותרות: שעה + שישה ימים"
    if info["empty"]:
        assert info["empty"] == info["labelled"], "יום ריק בלי תווית"


def test_blocks_do_not_truncate_with_ellipsis(fresh):
    _with_schedule(fresh)
    bad = fresh.evaluate(
        """() => [].slice.call(document.querySelectorAll('#schedule-grid .ev span'))
             .filter(e => getComputedStyle(e).textOverflow === 'ellipsis').length"""
    )
    assert bad == 0, "יש טקסט שנחתך בשלוש נקודות בתוך הרשת"
