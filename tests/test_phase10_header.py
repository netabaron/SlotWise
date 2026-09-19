"""שלב 10: הסימן בצד שמאל, בורר הערכה כאייקונים, והתחזוקה מחוץ למסך.

למה הקובץ הזה קיים
-------------------
שלושת הפריטים האלה נראים כמו סידור מחדש, ולכל אחד מהם יש תנאי שנשבר
בשקט:

* **הסימן** אמור לשבת בקצה השמאלי. ‏``order`` בלבד מזיז אותו, ושינוי
  עתידי ב-``justify-content`` או ב-``flex-direction`` היה מחזיר אותו ימינה
  בלי שאף בדיקה תבחין. לכן נמדד מיקום מצויר, לא מחלקת CSS.
* **בורר הערכה** איבד את הטקסט הנראה שלו. השם הנגיש עבר ל-``aria-label``,
  וכפתור אייקון בלי שם הוא כפתור שקורא מסך מקריא כ"לחצן". בנוסף, כלל 7.1
  אוסר לסמן מצב בצבע בלבד — הגלולה הצבועה לבדה היא בדיוק זה, ולכן
  ה-``.ico-fill`` נבדק בנפרד.
* **המשיכה מהידיעון** נשארת בתוכנה אבל יוצאת ממסך הסטודנט/ית. "עברה"
  נבדק בשני הכיוונים: שהיא אינה בכותרת, **ו**שהיא נמצאת בפרטים הטכניים —
  בדיקה של צד אחד בלבד עוברת גם אם הכפתור נמחק בטעות.
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


@pytest.fixture()
def page(browser, server):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    pg.goto(server)
    pg.wait_for_timeout(3000)
    try:
        yield pg
    finally:
        ctx.close()


# --------------------------------------------------------------------------
# 1. הסימן בצד שמאל, עם אייקון
# --------------------------------------------------------------------------
def test_the_wordmark_sits_on_the_left(page):
    """נמדד לפי הציור. מחלקת CSS אינה עדות למיקום בפריסת flex עם order."""
    box = page.evaluate(
        """() => {
          const h = document.querySelector('.app-header');
          const b = document.querySelector('.brand');
          const s = document.querySelector('.header-side');
          if (!h || !b || !s) return null;
          const hr = h.getBoundingClientRect(), br = b.getBoundingClientRect(),
                sr = s.getBoundingClientRect();
          return {headerLeft: hr.left, headerRight: hr.right,
                  brandLeft: br.left, brandRight: br.right, sideLeft: sr.left};
        }"""
    )
    assert box, "לא נמצאה הכותרת"
    assert box["brandLeft"] < box["sideLeft"], (
        f"הסימן אינו משמאל לשאר הכותרת: brand={box['brandLeft']:.0f} "
        f"side={box['sideLeft']:.0f}")
    from_left = box["brandLeft"] - box["headerLeft"]
    from_right = box["headerRight"] - box["brandRight"]
    assert from_left < from_right, (
        f"הסימן קרוב יותר לקצה הימני: {from_left:.0f}px משמאל, "
        f"{from_right:.0f}px מימין")


def test_the_wordmark_has_an_icon_beside_it(page):
    """אייקון מצויר, ומשמאל למילה — לא מימין לה."""
    got = page.evaluate(
        """() => {
          const i = document.querySelector('.brand-icon');
          const t = document.querySelector('.brand-title');
          if (!i || !t) return null;
          const ir = i.getBoundingClientRect(), tr = t.getBoundingClientRect();
          return {w: ir.width, h: ir.height, iconLeft: ir.left, titleLeft: tr.left,
                  tag: i.tagName.toLowerCase(),
                  hidden: i.getAttribute('aria-hidden')};
        }"""
    )
    assert got, "אין אייקון לצד שם המוצר"
    assert got["tag"] == "svg", got["tag"]
    assert got["w"] > 8 and got["h"] > 8, got
    assert got["iconLeft"] < got["titleLeft"], (
        "האייקון נוחת מימין לשם — היחידה חייבת להיות ltr")
    assert got["hidden"] == "true", "אייקון דקורטיבי חייב להיות מוסתר מקורא מסך"


# --------------------------------------------------------------------------
# 2. בורר הערכה כאייקונים
# --------------------------------------------------------------------------
def test_theme_buttons_have_accessible_names(page):
    """אין טקסט נראה, ולכן aria-label הוא השם היחיד שנשאר."""
    rows = page.evaluate(
        """() => [...document.querySelectorAll('.theme-btn')].map(b => ({
             choice: b.dataset.themeChoice,
             text: (b.textContent || '').trim(),
             label: (b.getAttribute('aria-label') || '').trim(),
             role: b.getAttribute('role'),
             checked: b.getAttribute('aria-checked'),
           }))"""
    )
    assert len(rows) == 3, rows
    assert {r["choice"] for r in rows} == {"system", "light", "dark"}
    for r in rows:
        assert not r["text"], f"נשאר טקסט נראה בכפתור {r['choice']}: {r['text']!r}"
        assert r["label"], f"כפתור {r['choice']} בלי שם נגיש"
        assert any("֐" <= c <= "׿" for c in r["label"]), r["label"]
        assert r["role"] == "radio"
        assert r["checked"] in ("true", "false")
    assert sum(r["checked"] == "true" for r in rows) == 1, "בדיוק אחד נבחר"


def test_theme_state_is_not_signalled_by_colour_alone(page):
    """הצורה שבתוך האייקון עוברת ממתאר למילוי. זה הסימן שאינו צבע.

    ‏גלולה צבועה לבדה נבדלת בגוון ובבהירות בלבד, וזה בדיוק מה שכלל 7.1
    פוסל. הבדיקה משווה את ‎fill‎ המחושב של הנבחר מול הלא-נבחרים.
    """
    for choice in ("light", "dark", "system"):
        page.click(f'.theme-btn[data-theme-choice="{choice}"]')
        page.wait_for_timeout(250)
        fills = page.evaluate(
            """() => [...document.querySelectorAll('.theme-btn')].map(b => {
                 const g = b.querySelector('.ico-fill');
                 return {choice: b.dataset.themeChoice,
                         checked: b.getAttribute('aria-checked') === 'true',
                         fill: g ? getComputedStyle(g).fill : null,
                         op: g ? getComputedStyle(g).fillOpacity : null};
               })"""
        )
        chosen = [f for f in fills if f["checked"]]
        others = [f for f in fills if not f["checked"]]
        assert len(chosen) == 1, fills
        assert chosen[0]["choice"] == choice, fills
        assert chosen[0]["fill"] not in (None, "none"), (
            f"הנבחר ({choice}) אינו ממולא — נשאר רק הצבע כסימן: {chosen[0]}")
        for o in others:
            assert o["fill"] == "none", (
                f"גם הלא-נבחר ({o['choice']}) ממולא — אין הבדל צורה: {o}")


# --------------------------------------------------------------------------
# 3. אין פקדי תחזוקה במסך — הם הוסרו יחד עם נקודות הקצה שמאחוריהם
# --------------------------------------------------------------------------
# ‏עד לאריזה לאירוח היו כאן שלוש בדיקות ששמרו על **מיקומו** של כפתור
# ‏"עדכן נתונים מהידיעון": שהוא עזב את הכותרת, שהוא יושב בפרטים הטכניים,
# ‏ושרק ‎?debug=1‎ חושף אותו. הכפתור עצמו נמחק עכשיו, ואיתו
# ‏``POST /api/scrape/start`` ויומן הגרידה — ‏HOSTING_NOTES.md §1 שורה 3.
# ‏לכן השאלה התהפכה: לא "איפה הוא", אלא "ודאו שהוא איננו".
def test_no_maintenance_controls_reach_the_page(page):
    """כפתור הרענון ויומן הגרידה אינם קיימים ב-DOM — לא מוסתרים, אלא אינם."""
    got = page.evaluate(
        """() => ({
          refresh: !!document.getElementById('btn-refresh'),
          summary: !!document.getElementById('refresh-summary'),
          log: !!document.getElementById('scrape-log'),
          logLines: !!document.getElementById('scrape-log-lines'),
        })"""
    )
    assert not got["refresh"], "כפתור המשיכה מהידיעון עדיין בעמוד"
    assert not got["summary"], "שורת סיכום המשיכה עדיין בעמוד"
    assert not got["log"], "יומן הגרידה עדיין בעמוד"
    assert not got["logLines"], "שורות יומן הגרידה עדיין בעמוד"


def test_the_header_says_when_the_data_was_pulled(page):
    """‏#freshness-text הוא מה שהחליף אותם, והוא בכותרת — לא מאחורי ‎?debug=1‎.

    ‏זה חיווי הטריות היחיד שיש לסטודנט/ית מאורח/ת, ולכן הוא חייב להיות
    ‏גלוי בלי לפתוח שום סעיף. ‏HOSTING_NOTES.md §3.

    ‏עד 2026-09-20 הבדיקה הזאת חיפשה ``#catalog-built`` ואת המילה "הקטלוג".
    ‏השורה ההיא נמחקה: היא הייתה שנייה מתוך שתיים שאמרו את אותו דבר,
    ‏ובניסוח של מי שבונה את הקטלוג ולא של מי שמשתמש בו. הכוונה של הבדיקה
    ‏לא השתנתה — רק המזהה והנוסח שהיא מודדת.
    """
    page.wait_for_timeout(1500)
    got = page.evaluate(
        """() => {
          const el = document.getElementById('freshness-text');
          if (!el) return {exists: false};
          return {exists: true,
                  inHeader: !!el.closest('.app-header'),
                  inTech: !!el.closest('#tech-details'),
                  text: (el.textContent || '').trim(),
                  title: el.getAttribute('title') || '',
                  second: !!document.getElementById('catalog-built')};
        }"""
    )
    assert got["exists"], "אין שורת טריות בעמוד"
    assert got["inHeader"], "שורת הטריות אינה בכותרת"
    assert not got["inTech"], "שורת הטריות נקברה בפרטים הטכניים"
    assert "מעודכן מהידיעון" in got["text"], (
        f"השורה ריקה או לא בנוסח שסוכם: {got['text']!r}"
    )
    assert not got["second"], "‏#catalog-built חזר — שוב שתי שורות על אותו דבר"
    # הפירוט לא נמחק, הוא עבר לתווית ההצפה. בלי הצד הזה אפשר "לעבור" את
    # הבדיקה בכך שפשוט מוחקים את המידע.
    assert "נמשכו מהידיעון" in got["title"], (
        f"אין תווית הצפה עם התאריך המלא: {got['title']!r}"
    )


def test_debug_opens_the_technical_section(browser, server):
    """‏?debug=1 עדיין פותח את הפרטים הטכניים — שם יושבות הספירות."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    pg = ctx.new_page()
    try:
        pg.goto(server + "?debug=1")
        pg.wait_for_timeout(3000)
        assert pg.evaluate(
            "() => document.getElementById('tech-details').open"
        ), "‏?debug=1 אינו פותח את הפרטים הטכניים"
    finally:
        ctx.close()
