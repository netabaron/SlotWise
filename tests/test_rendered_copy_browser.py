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


@pytest.fixture()
def fresh(browser, server):
    """טעינה נקייה: אין ‏localStorage, בדיוק כמו כניסה ראשונה."""
    ctx = browser.new_context()
    p = ctx.new_page()
    p.errors = []  # type: ignore[attr-defined]
    p.on("pageerror", lambda e: p.errors.append(str(e)))  # type: ignore[attr-defined]
    p.goto(server)
    p.wait_for_timeout(4000)
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
def test_no_missing_keys_on_first_render(fresh):
    """הציור הראשון, בלי מצב שמור — המסך שרואים בכניסה."""
    hits = scan(fresh, "first-render")
    assert hits == [], "מפתחות חסרים בציור הראשון:\n  " + "\n  ".join(hits)


def test_no_missing_keys_while_stepping_through(fresh):
    """צועדים בזרימה, וסורקים בכל שלב.

    כל שלב מצייר מצבים אחרים — רשימת קורסים, תוצאות חיפוש, טבלאות
    הקבוצות, פאנל הניקוד, הרשת, השכבה — ולכל אחד מהם נוסח משלו.
    """
    hits: list[str] = []
    hits += scan(fresh, "load")

    fresh.select_option("#select-year", "3")
    fresh.select_option("#select-term", "א")
    fresh.wait_for_timeout(2500)
    hits += scan(fresh, "year+term")

    fresh.fill("#course-search", "61753")
    fresh.wait_for_timeout(1500)
    hits += scan(fresh, "search")
    try:
        fresh.click("#course-search-results li >> nth=0")
        fresh.wait_for_timeout(2500)
        hits += scan(fresh, "course-added")
    except Exception:
        pass

    for key in ("courses", "days", "lecturers"):
        try:
            if fresh.evaluate(
                "document.getElementById('step-%s')"
                ".classList.contains('is-collapsed')" % key
            ):
                fresh.click("#step-%s-toggle" % key)
                fresh.wait_for_timeout(500)
        except Exception:
            pass
    fresh.wait_for_timeout(1200)
    hits += scan(fresh, "steps-expanded")

    try:
        fresh.click('.day-btn[data-days="3"]')
        fresh.wait_for_timeout(2000)
        hits += scan(fresh, "days-3")
    except Exception:
        pass

    try:
        fresh.evaluate("document.getElementById('tech-details').open = true")
        fresh.wait_for_timeout(400)
        hits += scan(fresh, "tech-details")
    except Exception:
        pass

    try:
        fresh.evaluate("window.scrollTo(0, 1200)")
        fresh.wait_for_timeout(600)
        fresh.click("#btn-show-grid")
        fresh.wait_for_timeout(1200)
        hits += scan(fresh, "overlay")
        fresh.keyboard.press("Escape")
        fresh.wait_for_timeout(500)
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
