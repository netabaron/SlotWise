"""הדף באמת מציג טקסט — לא רק נטען בלי לקרוס.

למה הקובץ הזה קיים
-------------------
עמוד שבו **כל** התוויות ריקות עבר 548 בדיקות. זה לא היה מזל רע אלא פער
אמיתי בכיסוי: אף בדיקה לא הסתכלה על טקסט מצויר.

* ``test_web.py`` דורש "לפחות אות עברית אחת בעמוד" — והערת חוזה ה-DOM
  שבראש ``index.html`` מלאה עברית, ולכן התנאי מתקיים גם כשכל תווית ריקה.
* בדיקות ה-Playwright הקיימות נוגעות רק בשלב 2 — קודי קורס, תגיות
  וסימוני בחירה — וכל אלה מגיעים מנתוני השרת, לא מ-``strings.json``.

מה נבדק כאן, ורק זה: שהטקסט שהמשתמש/ת רואים אינו ריק ואינו שם של מפתח.
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

#: מצב שמור, כדי שגם שלבים 4 ו-5 יצוירו ולא יישארו במצב "ממתין".
STORAGE_KEY = "braude_schedule_builder_v1"
SEED = {
    "schema": 1,
    "studyYear": 3,
    "term": "א",
    "semester": "5",
    "codes": ["11069", "61756", "61757", "62027", "61759", "61832"],
    "known": {},
    "program": "הנדסת תוכנה",
    "topN": 5,
    "activeSchedule": 0,
    "targetDays": 4,
    "provenanceReady": True,
    "autoSemester": "5",
    "autoCodes": ["11069", "61756", "61757", "62027", "61759", "61832"],
    "manualCodes": [],
    "autoDropped": [],
}


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
def page(browser, server):
    import json

    ctx = browser.new_context()
    ctx.add_init_script(
        "if (!localStorage.getItem('%s')) localStorage.setItem('%s', %s);"
        % (STORAGE_KEY, STORAGE_KEY, json.dumps(json.dumps(SEED)))
    )
    p = ctx.new_page()
    p.goto(server)
    p.wait_for_timeout(4500)
    # פורסים כל שלב מקופל, אחרת חצי מהטקסט לא מצויר בכלל
    for key in ("courses", "days", "lecturers"):
        try:
            collapsed = p.evaluate(
                "document.getElementById('step-%s')"
                ".classList.contains('is-collapsed')" % key
            )
            if collapsed:
                p.click("#step-%s-toggle" % key)
                p.wait_for_timeout(400)
        except Exception:
            pass
    p.wait_for_timeout(1200)
    try:
        yield p
    finally:
        ctx.close()


# ==========================================================================
# 1. מקור הנוסח הגיע בכלל
# ==========================================================================
def test_strings_reach_the_browser(page):
    """‏window.STRINGS מלא. ריק פירושו עמוד בלי אף מילה."""
    assert page.evaluate("!window.slotwise.stringsEmpty()"), (
        "‏window.STRINGS ריק — כל הטקסט בממשק ייעלם"
    )
    for path in ("meta", "ui", "server", "app"):
        assert page.evaluate("!!window.STRINGS[%r]" % path), f"חסר ענף {path}"


def test_no_missing_string_keys(page):
    """אף קריאה ל-T() לא נפלה לברירת מחדל."""
    missing = page.evaluate("window.slotwise.missingStrings()")
    assert missing == [], "מפתחות נוסח חסרים: " + ", ".join(missing)


# ==========================================================================
# 2. הטקסט המצויר עצמו
# ==========================================================================
#: כל מה שאמור לשאת מילים. ריק כאן = תווית שנעלמה.
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
    "#schedule-tabs .tab",
    ".lect-table thead th",
]


def test_no_empty_labels(page):
    """אין תווית ריקה במסך."""
    empty = page.evaluate(
        """(sels) => {
      const bad = [];
      sels.forEach(function (sel) {
        document.querySelectorAll(sel).forEach(function (el) {
          if (el.offsetParent === null) return;          // מוסתר — לא נבדק
          if (el.closest('[hidden]')) return;
          const t = (el.textContent || '').trim();
          if (!t) bad.push(sel + ' :: ' + (el.id || el.className));
        });
      });
      return bad;
    }""",
        LABEL_SELECTORS,
    )
    assert empty == [], "תוויות ריקות: " + "; ".join(empty)


def test_no_raw_key_names_on_screen(page):
    """אין שם מפתח פנימי על המסך.

    ‏T() מסמן מפתח חסר ב-⟦…⟧, אבל גם קריאה עם ברירת מחדל שהיא שם המפתח
    (‏compactness / gaps / soft_conflict) הייתה מגיעה למסך כטקסט.
    """
    found = page.evaluate(
        """() => {
      const keys = ['compactness','gaps','soft_conflict','late_finish',
                    'lecturer','days_count','elapsed_ms'];
      const bad = [];
      document.querySelectorAll('body *').forEach(function (el) {
        if (el.children.length) return;                  // עלים בלבד
        if (el.offsetParent === null) return;
        const t = (el.textContent || '').trim();
        if (!t) return;
        if (t.indexOf('\\u27E6') !== -1) { bad.push('missing-key ' + t); return; }
        if (keys.indexOf(t) !== -1) bad.push('raw-key ' + t);
      });
      return bad;
    }"""
    )
    assert found == [], "שמות מפתח על המסך: " + "; ".join(found)


def test_key_screens_carry_hebrew(page):
    """האזורים המרכזיים נושאים עברית בפועל.

    ‏test_web.py בודק "אות עברית אחת בעמוד", והערת חוזה ה-DOM מספקת אותה
    גם כשהממשק ריק לגמרי. כאן נבדק כל אזור בנפרד.
    """
    HEB = "[\\u0590-\\u05FF]"
    regions = {
        "כפתורי הכותרת": ".header-actions",
        "שלב 1": "#step-year .step-head",
        "שלב 2": "#step-courses .step-head",
        "פאנל הניקוד": "#schedule-summary",
        "לשוניות": "#schedule-tabs",
        "כותרות הרשת": "#schedule-grid",
        "תחתית": ".app-footer",
    }
    missing = page.evaluate(
        """(cfg) => {
      const re = new RegExp(cfg.heb);
      const bad = [];
      Object.keys(cfg.regions).forEach(function (name) {
        const el = document.querySelector(cfg.regions[name]);
        if (!el) { bad.push(name + ' (לא נמצא)'); return; }
        if (!re.test(el.textContent || '')) bad.push(name);
      });
      return bad;
    }""",
        {"heb": HEB, "regions": regions},
    )
    assert missing == [], "אזורים בלי עברית: " + ", ".join(missing)


def test_no_javascript_errors(page):
    """הדף לא זורק — כולל הבדיקה שמסמנת נוסח חסר."""
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.reload()
    page.wait_for_timeout(4000)
    assert errors == [], "שגיאות JS: " + "; ".join(errors)
