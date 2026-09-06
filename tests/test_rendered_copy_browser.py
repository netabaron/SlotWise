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


# ==========================================================================
# 5. קודי חדר — סדר ויזואלי, לא רק סדר לוגי
# ==========================================================================
#: משחזר את סדר התווים **על המסך** לפי מיקומם, ולא לפי textContent.
#: ‏textContent מחזיר תמיד את הסדר הלוגי, ולכן הוא עיוור בדיוק לתקלה
#: שהבדיקה הזאת נועדה לתפוס: רצף לטיני שהתהפך בתוך שורה עברית.
VISUAL_ORDER = """(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const t = el.firstChild;
  if (!t || t.nodeType !== 3) return null;
  const chars = [];
  for (let i = 0; i < t.data.length; i++) {
    const r = document.createRange();
    r.setStart(t, i); r.setEnd(t, i + 1);
    const box = r.getBoundingClientRect();
    chars.push([box.x, t.data[i]]);
  }
  chars.sort((a, b) => a[0] - b[0]);
  return { logical: t.data, visual: chars.map(c => c[1]).join('') };
}"""


def test_room_code_reformatting(fresh):
    """‏"709 L" נכנס, "L 709" יוצא.

    הידיעון שומר מספר ואז אות בניין; אף אחד בבראודה לא אומר חדר ככה,
    ולכן ההיפוך נעשה בתצוגה. הערך השמור אינו משתנה.
    """
    cases = [
        ("709 L", "L 709"),
        ("506 EF", "EF 506"),
        ("303 M", "M 303"),
        ("102 M מע'", "M 102 מע'"),
        ("205 M מע' רשתות", "M 205 מע' רשתות"),
        ("סמינר", "סמינר"),
        ("", ""),
    ]
    for raw, want in cases:
        got = fresh.evaluate("v => window.slotwise.formatRoom(v)", raw)
        assert got == want, f"{raw!r} -> {got!r}, ציפינו ל-{want!r}"


def test_room_codes_render_in_display_order(fresh):
    """‏הסדר **על המסך** שווה לערך המוצג, תו אחר תו.

    לא לערך השמור: הוא "709 L", והתצוגה היא "L 709". מה שנבדק כאן הוא
    שהרצף אינו מתהפך שוב בגלל ההקשר העברי שסביבו — ולכן המדידה היא של
    מיקומי תווים, ולא של textContent שמחזיר תמיד סדר לוגי.
    """
    _with_schedule(fresh)
    fresh.wait_for_selector("#schedule-grid .ev .code", timeout=15000)
    rows = fresh.evaluate(
        """() => {
      const out = [];
      document.querySelectorAll('.ev .code').forEach(function (el) {
        const t = el.firstChild;
        if (!t || t.nodeType !== 3) return;
        const chars = [];
        for (let i = 0; i < t.data.length; i++) {
          const r = document.createRange();
          r.setStart(t, i); r.setEnd(t, i + 1);
          chars.push([r.getBoundingClientRect().x, t.data[i]]);
        }
        chars.sort((a, b) => a[0] - b[0]);
        out.push({ shown: t.data, visual: chars.map(c => c[1]).join('') });
      });
      return out;
    }"""
    )
    assert rows, "לא נמצא אף קוד חדר ברשת"
    # רק קודים בלי עברית: תו עברי מוצג נכון מימין לשמאל, ולכן שחזור
    # משמאל-לימין שלו ייראה הפוך גם כשהכול תקין.
    latin = [r for r in rows if not any("֐" <= c <= "׿" for c in r["shown"])]
    assert latin, "אין קוד לטיני טהור לבדוק עליו"
    bad = [r for r in latin if r["visual"] != r["shown"]]
    assert bad == [], "קודים שהתהפכו: " + "; ".join(
        "%r מוצג כ-%r" % (r["shown"], r["visual"]) for r in bad
    )
    # ומה שמוצג הוא באמת הצורה ההפוכה: אות ואז מספר.
    import re as _re

    assert any(_re.match(r"^[A-Za-z]+ \d", r["shown"]) for r in latin), (
        "אף קוד לא מוצג בצורה 'אות מספר' — ההיפוך לתצוגה לא קרה"
    )


def test_room_codes_are_explicitly_ltr_everywhere(fresh):
    """כל מקום שבו מופיע קוד: רשת, פאנל וטבלת המרצים."""
    _with_schedule(fresh)
    # רשת
    assert fresh.evaluate(
        "getComputedStyle(document.querySelector('.ev .code')).direction"
    ) == "ltr"
    # פאנל
    fresh.click("#schedule-grid .ev")
    fresh.wait_for_timeout(700)
    panel = fresh.evaluate(
        """() => [].slice.call(document.querySelectorAll('#meeting-detail .code'))
             .map(e => [e.getAttribute('dir'), getComputedStyle(e).direction])"""
    )
    assert panel, "אין קודים בפאנל"
    for attr, computed in panel:
        assert attr == "ltr" and computed == "ltr", f"בפאנל: dir={attr} computed={computed}"
    fresh.keyboard.press("Escape")
    fresh.wait_for_timeout(400)
    # טבלת המרצים
    for key in ("lecturers",):
        if fresh.evaluate(
            "document.getElementById('step-%s').classList.contains('is-collapsed')" % key
        ):
            fresh.click("#step-%s-toggle" % key)
            fresh.wait_for_timeout(600)
    table = fresh.evaluate(
        """() => [].slice.call(document.querySelectorAll('.lect-table .code'))
             .map(e => getComputedStyle(e).direction)"""
    )
    assert table and set(table) == {"ltr"}, f"בטבלה: {set(table)}"


def test_block_shows_name_kind_time_and_room(fresh):
    """הבלוק נושא שם, סוג, שעה וחדר — והגופן אינו יורד מ-13px.

    סוג השיעור הוא מהדברים הראשונים שמחפשים על הרשת, והצבע מציין את
    הקורס ולא את הסוג — בלי המילה אי אפשר להבחין בין הרצאה לתרגול.
    """
    _with_schedule(fresh)
    info = fresh.evaluate(
        """() => {
      const evs = [].slice.call(document.querySelectorAll('#schedule-grid .ev'));
      const vis = e => !!e && !e.hidden;
      return {
        total: evs.length,
        withName: evs.filter(e => (e.querySelector('b') || {}).textContent).length,
        withKind: evs.filter(e => vis(e.querySelector('.ev-kind'))).length,
        withRoom: evs.filter(e => vis(e.querySelector('.ev-room'))).length,
        fonts: Array.from(new Set(evs.map(e => getComputedStyle(e).fontSize))),
      };
    }"""
    )
    assert info["total"] > 0
    # שם וסוג לעולם אינם יורדים.
    assert info["withName"] == info["total"], "בלוק בלי שם קורס"
    assert info["withKind"] == info["total"], "בלוק בלי סוג שיעור"
    assert info["withRoom"] > 0, "אף בלוק לא מציג חדר"
    for f in info["fonts"]:
        assert float(f.replace("px", "")) >= 13, f"גופן קטן מ-13px בבלוק: {f}"


def test_block_shows_the_full_lecturer_name(fresh):
    """שם המרצה על הבלוק הוא השם המלא, אות באות — לא מקוצר.

    ‏"ד״ר סוקולובסקי" לבדו מוחק את מה שמבדיל בין שני מרצים באותו שם
    משפחה, וזה בדיוק מה שבוחרים לפיו. שם ארוך נשבר לשתי שורות.
    """
    _with_schedule(fresh)
    rows = fresh.evaluate(LINES, "#schedule-grid")
    shown = [r["lectText"].strip() for r in rows if r["lect"]]
    assert shown, "אף בלוק לא מציג מרצה"
    # מקור האמת: שם המרצה יושב על ה-pick, לא על המפגש הבודד.
    full = fresh.evaluate(
        """() => ((window.slotwise.getRuntime().solve.schedules || [])[0] || {picks: []})
             .picks.map(p => p.lecturer).filter(Boolean)"""
    )
    assert full, "אין שמות מרצים בנתונים"
    for name in shown:
        assert name in full, f"שם על הבלוק שאינו זהה למקור: {name!r}"


#: מודד את **השורות** בתוך הבלוק, לא את הבלוק.
#:
#: זו לא קפדנות יתר. ‏.ev הוא ``display:flex; flex-direction:column``, ולכן
#: בלוק נמוך מדי דוחס את ילדיו במקום לגלוש: ‏scrollHeight שלו נשאר שווה
#: ל-clientHeight גם כשהשם והסוג נחתכים בפנים. בדיקה שמדדה את המכל עברה
#: תמיד — ולא בגלל שהכול נכנס, אלא בגלל שאין דבר שהיא יכולה לראות.
LINES = """(sel) => {
  const vis = e => !!e && !e.hidden && getComputedStyle(e).display !== 'none';
  return [].slice.call(document.querySelectorAll(sel + ' .ev')).map(e => {
    const parts = {
      name: e.querySelector('b'), kind: e.querySelector('.ev-kind'),
      time: e.querySelector('.cell-time'), room: e.querySelector('.ev-room'),
      lect: e.querySelector('.ev-lect'),
    };
    const cut = [];
    Object.keys(parts).forEach(k => {
      const el = parts[k];
      if (!vis(el)) return;
      const dh = el.scrollHeight - el.clientHeight;
      const dw = el.scrollWidth - el.clientWidth;
      if (dh > 1 || dw > 1) cut.push(k + (dh > 1 ? ' גובה+' + dh : '')
                                       + (dw > 1 ? ' רוחב+' + dw : ''));
    });
    // ‏"קיים אבל מוסתר" (ירד) שונה מ"לא קיים" (אין נתון). בלי ההבחנה
    // הזאת בלוק בלי חדר או בלי מרצה נספר כהפרת סדר.
    return {
      name: parts.name ? parts.name.textContent : '',
      kind: vis(parts.kind), time: vis(parts.time), room: vis(parts.room),
      lect: vis(parts.lect),
      hasRoom: !!parts.room, hasTime: !!parts.time, hasLect: !!parts.lect,
      lectText: parts.lect ? parts.lect.textContent : '',
      soft: e.classList.contains('is-soft'),
      dashed: getComputedStyle(e).outlineStyle === 'dashed',
      cut: cut,
    };
  });
}"""


def _overlap_on(page):
    """מכבה חובת נוכחות ברכיב אחד, ועובר ללשונית שבה יש חפיפה מכוונת.

    בלי זה בדיקות החפיפה ריקות מתוכן: המערכת שנבנית בברירת המחדל אינה
    מכילה חפיפה כלל, וכל תנאי ``if softCount`` היה עובר בלי לבדוק דבר.
    שני השלבים הם פעולות ממשק אמיתיות — מתג ולחיצה על לשונית — ולא מצב
    מוזרע.

    למה צריך גם לעבור לשונית: מרגע שהפסקת הצהריים אינה נספרת, מערכת בלי
    חפיפה כבר אינה מפסידה 2 נקודות על החור שסביב הצהריים, ולכן היא
    מנצחת את זו שקונה את החור הזה בוויתור על נוכחות. החפיפה ירדה
    למקום שלישי — קיימת, ולא נבחרת ראשונה. זה בדיוק מה שהשינוי נועד
    לעשות, ולכן הבדיקה מחפשת אותה ולא מניחה שהיא במקום הראשון.
    """
    page.uncheck('input[data-fk="att-61759-הרצאה"]', force=True)
    page.wait_for_timeout(3000)
    tabs = page.locator("#schedule-tabs .tab")
    for i in range(tabs.count()):
        if i:
            tabs.nth(i).click()
            page.wait_for_timeout(1200)
        if page.locator("#schedule-grid .ev.is-soft").count():
            return
    raise AssertionError(
        "אף אחת מהמערכות המוצגות אינה מכילה חפיפה מכוונת — "
        "הבדיקה אינה בודקת דבר, ויש למצוא הגדרה שמייצרת אחת"
    )


def _assert_lines_intact(rows, where):
    """שם וסוג קיימים בכל בלוק, שום שורה אינה נחתכת, והסדר נשמר.

    סדר הירידה, מהמוותר ביותר: חדר, שעה, מרצה. שם הקורס וסוג השיעור
    אינם יורדים לעולם. המרצה יורד אחרון — הוא מה שבוחרים לפיו.
    """
    assert rows, f"אין בלוקים ב{where}"
    cut = [r["name"] + ": " + ", ".join(r["cut"]) for r in rows if r["cut"]]
    assert not cut, f"שורות נחתכות ב{where}: " + " | ".join(cut)
    assert all(r["name"] for r in rows), f"בלוק בלי שם קורס ב{where}"
    assert all(r["kind"] for r in rows), f"בלוק בלי סוג שיעור ב{where}"
    # השעה יורדת רק אחרי החדר, והמרצה רק אחרי השעה.
    flipped = [r["name"] for r in rows
               if r["hasTime"] and not r["time"] and r["hasRoom"] and r["room"]]
    assert not flipped, f"השעה ירדה לפני החדר ב{where}: " + "; ".join(flipped)
    flipped = [r["name"] for r in rows
               if r["hasLect"] and not r["lect"] and r["hasTime"] and r["time"]]
    assert not flipped, f"המרצה ירד לפני השעה ב{where}: " + "; ".join(flipped)


def test_no_line_in_a_block_is_ever_cut(fresh):
    """שום שורה בבלוק אינה נחתכת — לא לגובה ולא לרוחב.

    זו הבדיקה שסולם הירידה קיים בשבילה: שורה שאין לה מקום יורדת כולה,
    ואינה נקטעת באמצע. שעה חתוכה ל-"10:30–12:2" נראית שלמה, וחדר חתוך
    ‏"F 506" הוא חדר קיים אחר — ולכן חיתוך כאן גרוע מהשמטה.
    """
    _with_schedule(fresh)
    _assert_lines_intact(fresh.evaluate(LINES, "#schedule-grid"), "רוחב רגיל")


def test_narrow_window_drops_room_before_time(fresh):
    """בחלון צר יורד קודם החדר, אחר כך השעה — והשם והסוג נשארים."""
    _with_schedule(fresh)
    fresh.set_viewport_size({"width": 760, "height": 900})
    fresh.wait_for_timeout(1200)  # ‏refit רץ אחרי השהיה קצרה
    _assert_lines_intact(fresh.evaluate(LINES, "#schedule-grid"), "חלון צר")


def test_print_keeps_name_and_kind_on_every_block(fresh):
    """בהדפסה משבצת נמוכה ב-5px, והשורות יורדות בהתאם — לא נחתכות.

    ‏‎--slot-h יורד מ-22px ל-17px, ולכן בלוק שנכנס על המסך אינו נכנס על
    הנייר. הבדיקה רצה אחרי המעבר למדיית הדפסה, כי זה בדיוק הרגע שבו
    ‏fitBlocks נדרש למדוד מחדש.
    """
    _with_schedule(fresh)
    fresh.emulate_media(media="print")
    fresh.wait_for_timeout(800)
    _assert_lines_intact(fresh.evaluate(LINES, "#schedule-grid"), "הדפסה")
    hidden = fresh.evaluate(
        """() => ['#tech-details', '#steps-progress', '#build-row', '#compare']
             .filter(s => { const e = document.querySelector(s);
                            return e && getComputedStyle(e).display !== 'none'; })"""
    )
    assert hidden == [], "אמצעי מסך שדלפו אל הנייר: " + ", ".join(hidden)


def test_print_shows_only_the_grid_and_one_header_line(fresh):
    """על הנייר: הרשת, ושורת כותרת אחת. שום דבר אחר.

    הרשימה שקבעה מה מוסתר בהדפסה הייתה רשימת איסור, ולכן כל אלמנט חדש
    דלף אליה בשקט — שורת ההתקדמות וכפתור הבנייה היו כל תוכנו של העמוד
    המודפס הראשון. הבדיקה סורקת מה **כן** מצויר, ולכן היא נכשלת על כל
    תוספת חדשה, ולא רק על אלה שנזכרנו לרשום.
    """
    _with_schedule(fresh)
    fresh.emulate_media(media="print")
    fresh.wait_for_timeout(900)
    painted = fresh.evaluate(
        """() => {
      const out = [];
      document.querySelectorAll('body *').forEach(e => {
        const r = e.getBoundingClientRect();
        if (r.height < 1 || r.width < 1) return;
        // מה שבתוך הרשת הוא הרשת עצמה, לא תוספת עליה
        if (e.closest('#grid-scroll') && e.id !== 'grid-scroll') return;
        if (e.id) return out.push('#' + e.id);
        out.push(e.tagName.toLowerCase() + '.' + (e.className.toString().split(' ')[0] || ''));
      });
      return Array.from(new Set(out));
    }"""
    )
    allowed = {"#steps", "#step-schedule", "div.step-body", "#grid-scroll", "#print-head"}
    extra = [x for x in painted if x not in allowed]
    assert not extra, "דלף אל הדף המודפס: " + ", ".join(extra)
    assert "#grid-scroll" in painted, "הרשת עצמה אינה על הדף"
    assert "#print-head" in painted, "שורת הכותרת אינה על הדף"

    head = fresh.evaluate("document.getElementById('print-head').textContent")
    assert "מערכת" in head and "." in head, f"שורת כותרת בלי שם ותאריך: {head!r}"


def test_print_fits_one_page(fresh):
    """המערכת נכנסת לעמוד אחד.

    רשת שנשפכת לעמוד שני נשברת באמצע שעה, ושורת כותרות הימים נשארת
    מאחור — ואי אפשר לחזור עליה: ‏thead עושה זאת בטבלה, והרשת היא
    ‏grid. לכן הגובה מוקטן עד שהיא נכנסת, במקום לנהל את השבירה.
    """
    _with_schedule(fresh)
    fresh.emulate_media(media="print")
    fresh.wait_for_timeout(900)
    page_px = round(210 * 96 / 25.4)  # ‏A4 לרוחב: 210 מ"מ גובה
    body = fresh.evaluate("Math.round(document.body.scrollHeight)")
    assert body <= page_px, f"הדף המודפס גולש: {body}px מול עמוד {page_px}px"
    _assert_lines_intact(fresh.evaluate(LINES, "#schedule-grid"), "הדפסה בעמוד אחד")


def test_deliberate_overlap_stays_two_blocks(fresh):
    """חפיפה מכוונת מוצגת כשני בלוקים, לא כאחד ממוזג.

    מיזוג הסתיר **אילו** שני קורסים מתנגשים, וזו השאלה שעומדת להכרעה.
    """
    _with_schedule(fresh)
    _overlap_on(fresh)
    rows = fresh.evaluate(LINES, "#schedule-grid")
    soft = [r for r in rows if r["soft"]]
    merged = fresh.evaluate(
        "document.querySelectorAll('#schedule-grid .ev.is-cluster').length"
    )
    assert merged == 0, "עדיין קיים בלוק ממוזג"
    assert len(soft) >= 2, "חפיפה אמורה להיות לפחות שני בלוקים"
    assert all(r["dashed"] for r in soft), "בלוק חופף בלי מסגרת מקווקוות"
    assert len({r["name"] for r in soft}) >= 2, "שני הצדדים אמורים לשאת שמות שונים"


def test_overlap_halves_stay_readable_at_half_width(fresh):
    """שני החצאים מציגים שם, סוג ומרצה — בלי חיתוך.

    זו הסיבה שהחצאים נפסלו בפעם הקודמת: הטקסט נקטע. הוא נקטע מפני
    שהבלוק נשא גם מרצה וגם מספר קבוצה; מספר הקבוצה עבר לפאנל.

    החדר **כן** רשאי לרדת כאן — הוא הראשון בסולם, והוא קוד קצר שאפשר
    לשלוף מהפאנל. מה שאסור לרדת הוא השם, הסוג והמרצה: לפי המרצה בוחרים.
    """
    _with_schedule(fresh)
    _overlap_on(fresh)
    fresh.set_viewport_size({"width": 900, "height": 900})
    fresh.wait_for_timeout(1200)
    rows = fresh.evaluate(LINES, "#schedule-grid")
    _assert_lines_intact(rows, "חצי רוחב")
    soft = [r for r in rows if r["soft"]]
    assert len(soft) >= 2
    for r in soft:
        assert r["kind"], f"חצי בלוק בלי סוג שיעור: {r['name']}"
        if r["hasLect"]:
            assert r["lect"], f"חצי בלוק ויתר על המרצה: {r['name']}"


# ==========================================================================
# 6. מצב הסעיפים — ✓ שאומר משהו
# ==========================================================================
def test_section_marks_are_stateful(fresh):
    """‏○ בברירת מחדל, ‏✓ אחרי בחירה, ‏! כשיש קונפליקט.

    ‏✓ ירוק שמופיע על כל סעיף מהרגע הראשון אינו נושא מידע.
    """
    marks = lambda: fresh.evaluate(
        """() => [].slice.call(document.querySelectorAll('.progress-chip'))
             .map(e => e.className.replace('progress-chip ', ''))"""
    )
    assert set(marks()) == {"is-default"}, "בטעינה נקייה הכול אמור להיות ברירת מחדל"

    fresh.select_option("#select-year", "3")
    fresh.select_option("#select-term", "א")
    fresh.wait_for_timeout(3000)
    assert marks()[0] == "is-chosen", "אחרי בחירת שנה וסמסטר הסעיף אמור להיות 'נבחר'"

    fresh.click('.day-btn[data-days="2"]')
    fresh.wait_for_timeout(2500)
    assert "is-conflict" in marks(), "יעד ימים בלתי אפשרי אמור להופיע כקונפליקט"
    assert fresh.evaluate(
        "document.getElementById('step-days').classList.contains('is-conflict')"
    )


def test_progress_row_is_not_numbered(fresh):
    """שורת מצב, לא רצף ממוספר.

    הסעיפים נפתחים בכל סדר; מספור היה מבטיח רצף שאינו קיים.
    """
    chips = fresh.evaluate(
        """() => [].slice.call(document.querySelectorAll('.progress-chip'))
             .map(e => e.textContent.trim())"""
    )
    assert len(chips) == 4
    import re as _re

    for c in chips:
        assert not _re.match(r"^\s*[1-9]\s*[.·]", c), f"שבב ממוספר: {c!r}"


def test_semester_line_is_not_duplicated(fresh):
    """‏השנה והסמסטר נאמרים פעם אחת."""
    fresh.select_option("#select-year", "3")
    fresh.select_option("#select-term", "א")
    fresh.wait_for_timeout(3000)
    state = fresh.evaluate(
        "(document.getElementById('step-year-state')||{}).textContent || ''"
    )
    chip = fresh.evaluate(
        "(document.getElementById('semester-summary')||{}).textContent || ''"
    )
    assert "שנה" in state, "שורת המצב אמורה לשאת את השנה"
    assert "שנה" not in chip, f"השבב חוזר על השנה: {chip!r}"
    assert "בתוכנית" in chip, "השבב אמור לשאת את התרגום לסמסטר בתוכנית"
    assert "בתוכנית" not in state, f"שורת המצב חוזרת על הסמסטר בתוכנית: {state!r}"
