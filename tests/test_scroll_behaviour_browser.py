"""שלב 8 של העיצוב, חלק ב': התנהגות הגלילה (docs/DESIGN.md, "Scroll
behaviour", פריטים 1, 3, 4, 5 ו-6).

מה נבדק כאן: הכותרת הופכת לפס דק בצר אחרי גלילה, ואומרת "שלב X מתוך Y" —
וכלום כשכל השלבים הושלמו; ברחב היא כמו שהייתה. ראש הקורס הפתוח בשלב
המרצים נדבק בזמן שהשורות שלו נגללות. הסרגל התחתון מופיע רק כשיש מערכת
והכפתור שבעמוד והתוצאה מחוץ למסך, לוקח אל התוצאה, לעולם לא מכסה תוכן,
ואינו קיים ברחב; ‏#sticky-bar ו-#grid-overlay אינם עוד. שורת הימים נעוצה
בצר. והבלוקים נוחתים פעם אחת לכל בנייה — לא בהחלפת חלופה, ומיד תחת
‏prefers-reduced-motion.

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

NARROW = (390, 844)
WIDE = (1440, 900)
#: ‏התנהגות של הרשת בפריסה הצרה. מתחת ל-1000px המערכת שבדף היא רשימת ימים
#: ‏(DESIGN.md, "Results page", 5; ‏2026-10-10), ולכן הרשת הצרה נבדקת כאן.
NARROW_GRID = (1024, 844)

#: ‏מונה קריאות ל-Element.animate, לפני שהעמוד נטען. הנחיתה מזוהה לפי
#: ‏הצורה שלה: ‎500ms‎ של ‏clip-path שמתחיל סגור.
ANIMATE_HOOK = """(() => {
  window.__anims = [];
  const orig = Element.prototype.animate;
  Element.prototype.animate = function (frames, opts) {
    const first = Array.isArray(frames) ? frames[0] || {} : {};
    window.__anims.push({
      cls: this.className || '',
      duration: opts && opts.duration,
      delay: (opts && opts.delay) || 0,
      fromOpacity: first.opacity,
      fromClip: first.clipPath,
      props: Object.keys(first),
      t: performance.now(),
    });
    return orig.apply(this, arguments);
  };
})()"""

LANDINGS = """() => (window.__anims || []).filter(
  a => String(a.cls).includes('ev') && a.duration === 500 && a.fromClip === 'inset(0 0 100% 0)')"""


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


def _page(browser, server, size=NARROW, *, reduced=True, hook=False):
    # ‏בלי תנועה כברירת מחדל: הבדיקות כאן הן על מיקום, וגלילה חלקה הייתה
    # ‏הופכת כל מדידה למרוץ מול השעון. בדיקות הנחיתה מבקשות תנועה במפורש.
    ctx = browser.new_context(
        viewport={"width": size[0], "height": size[1]},
        color_scheme="light",
        reduced_motion="reduce" if reduced else "no-preference",
    )
    pg = ctx.new_page()
    pg.errors = []  # type: ignore[attr-defined]
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))  # type: ignore[attr-defined]
    if hook:
        pg.add_init_script(ANIMATE_HOOK)
    pg.goto(server)
    pg.wait_for_timeout(3000)
    return ctx, pg


def _identity(pg):
    pg.select_option("#select-program", "הנדסת תוכנה")
    pg.select_option("#select-year", "3")
    pg.select_option("#select-term", "א")
    pg.wait_for_timeout(2500)


def _next(pg, key, wait=1200):
    pg.click(f"#step-{key}-next")
    pg.wait_for_timeout(wait)


def _with_schedule(pg):
    """מסלול וסמסטר, "המשך", הקורסים המומלצים — ושלב הקורסים פתוח."""
    _identity(pg)
    _next(pg, "year")
    pg.click("#btn-restore-recommended")
    # ‏התוצאה, ולא הרשת: מתחת ל-1000px הרשת אינה על המסך (2026-10-10).
    pg.wait_for_selector("#alt-cards .alt-card", timeout=20000)
    pg.wait_for_timeout(1000)


def _all_steps_done(pg):
    _with_schedule(pg)
    _next(pg, "courses")
    _next(pg, "days")
    _next(pg, "lecturers")


def _scroll(pg, y, wait=400):
    pg.evaluate(f"() => window.scrollTo(0, {y})")
    pg.wait_for_timeout(wait)


HEADER = """() => {
  const h = document.getElementById('app-header');
  const cs = getComputedStyle(h);
  const step = document.getElementById('header-step');
  const r = h.getBoundingClientRect();
  return {
    thin: h.classList.contains('is-thin'),
    position: cs.position,
    top: r.top, height: r.height,
    border: parseFloat(cs.borderBottomWidth),
    icon: document.querySelector('.app-header .brand-icon').getBoundingClientRect().height,
    stepShown: !step.hidden && getComputedStyle(step).display !== 'none' && step.getBoundingClientRect().height > 0,
    stepText: step.textContent,
  };
}"""

BAR = """() => {
  const b = document.getElementById('bottom-bar');
  const cs = getComputedStyle(b);
  const r = b.getBoundingClientRect();
  return {
    visible: b.classList.contains('is-visible') && cs.visibility === 'visible' && cs.display !== 'none',
    display: cs.display,
    top: r.top, bottom: r.bottom, height: r.height,
    padding: parseFloat(getComputedStyle(document.body).paddingBottom),
    facts: document.getElementById('bottom-bar-facts').textContent,
  };
}"""


def _bar(pg):
    return pg.evaluate(BAR)


def _wait_bar(pg, visible):
    pg.wait_for_function(
        "v => document.getElementById('bottom-bar').classList.contains('is-visible') === v",
        arg=visible,
        timeout=5000,
    )
    pg.wait_for_timeout(350)  # ‏ההחלקה (‎.2s‎) — מושבתת כאן, ובכל זאת


def _on_screen(pg, sel):
    return pg.evaluate(
        """s => { const r = document.querySelector(s).getBoundingClientRect();
                  return r.bottom > 0 && r.top < innerHeight; }""",
        sel,
    )


# ==========================================================================
# 1. הכותרת המתכווצת
# ==========================================================================
def test_the_header_thins_after_scrolling_on_narrow_and_counts_the_step(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _identity(pg)
        _next(pg, "year")
        _scroll(pg, 0)
        full = pg.evaluate(HEADER)
        anchor = pg.evaluate(
            "() => document.getElementById('step-courses').getBoundingClientRect().top + scrollY")
        _scroll(pg, 10)
        still = pg.evaluate(HEADER)
        _scroll(pg, 300)
        thin = pg.evaluate(HEADER)
        after = pg.evaluate(
            "() => document.getElementById('step-courses').getBoundingClientRect().top + scrollY")
        errors = pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()
    assert not full["thin"] and not full["stepShown"], full
    assert not still["thin"], f"‏10px אינם ~20px, והכותרת כבר דקה: {still}"
    assert thin["thin"], thin
    assert thin["position"] in ("fixed", "sticky") and abs(thin["top"]) < 1, thin
    assert thin["height"] < full["height"] and thin["height"] <= 56, (full, thin)
    assert thin["icon"] < full["icon"], "הלוגו לא קטן בכותרת הדקה"
    assert thin["border"] >= 1, "לכותרת הדקה אין קו תחתון"
    assert thin["stepShown"] and thin["stepText"] == "שלב 2 מתוך 4", thin
    # ‏המרווח שומר את גובה הכותרת המלא: שום דבר בעמוד אינו קופץ.
    assert abs(after - anchor) < 1, f"העמוד זז כשהכותרת התכווצה: {anchor} → {after}"
    assert errors == []


def test_the_step_count_follows_the_open_step(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _with_schedule(pg)
        _next(pg, "courses")
        _scroll(pg, 300)
        text = pg.evaluate(HEADER)["stepText"]
    finally:
        ctx.close()
    assert text == "שלב 3 מתוך 4"


def test_no_step_count_once_every_step_is_complete(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _all_steps_done(pg)
        _scroll(pg, 300)
        got = pg.evaluate(HEADER)
    finally:
        ctx.close()
    assert got["thin"], got
    assert not got["stepShown"], f"כל השלבים הושלמו, והכותרת עדיין סופרת: {got}"


def test_the_header_is_unchanged_at_1440(browser, server):
    ctx, pg = _page(browser, server, WIDE)
    try:
        _identity(pg)
        _next(pg, "year")
        _scroll(pg, 0)
        top = pg.evaluate(HEADER)
        _scroll(pg, 300)
        scrolled = pg.evaluate(HEADER)
    finally:
        ctx.close()
    assert not scrolled["thin"], scrolled
    assert scrolled["position"] == "static", scrolled
    assert scrolled["height"] == top["height"], (top, scrolled)
    # ‏נגללת עם העמוד, כמו היום.
    assert scrolled["top"] < top["top"] - 250, (top, scrolled)
    assert not scrolled["stepShown"]


# ==========================================================================
# 3. ראש הקורס הפתוח בשלב המרצים
# ==========================================================================
OPEN_BIGGEST_COURSE = """() => {
  const cards = [...document.querySelectorAll('#lecturer-courses .lect-course')]
    .filter(c => c.querySelector('.lect-course-head'));
  cards.sort((a, b) => b.querySelectorAll('tbody tr').length - a.querySelectorAll('tbody tr').length);
  const c = cards[0];
  if (!c.classList.contains('is-open')) c.querySelector('.lect-course-head').click();
  return cards.indexOf(c);
}"""

COURSE = """() => {
  const c = document.querySelector('#lecturer-courses .lect-course.is-open');
  const h = c.querySelector(':scope > .lect-course-h');
  const rows = [...c.querySelectorAll('tbody tr')];
  const hr = h.getBoundingClientRect();
  const cr = c.getBoundingClientRect();
  const mid = document.elementFromPoint(hr.left + hr.width / 2, hr.top + hr.height / 2);
  return {
    headTop: hr.top, headBottom: hr.bottom, cardTop: cr.top + scrollY, cardBottom: cr.bottom,
    cardTopOnScreen: cr.top, scrollY,
    firstRowTop: rows.length ? rows[0].getBoundingClientRect().top : null,
    firstRowAbs: rows.length ? rows[0].getBoundingClientRect().top + scrollY : null,
    lastRowBottom: rows.length ? rows[rows.length - 1].getBoundingClientRect().bottom : null,
    rows: rows.length,
    headOnTop: !!mid && h.contains(mid),
  };
}"""

#: ‏מוסיף מסך שלם של מקום בסוף העמוד. ברחב שלב המרצים הוא כמעט סוף העמוד,
#: ‏ומה שיש מתחתיו תלוי בגופנים: ב-CI (‏Linux) הגלילה המקסימלית היא 520
#: ‏והיעד 587, כך ש-‏scrollTo נחתך בשקט והשורה הראשונה נשארה 18px מתחת
#: ‏לתחתית הראש. מקומית (‏Windows) היו 541 — ועבר בהפרש של 2.75px, במקרה. הבדיקה
#: ‏היא על ה-sticky, לא על אורך העמוד, ולכן היא דואגת לעצמה למקום לגלול.
ROOM_BELOW = """() => {
  const s = document.createElement('div');
  s.id = 'test-room-below';
  s.style.blockSize = innerHeight + 'px';
  document.body.append(s);
}"""

#: ‏אמת כשהכרטיס הפתוח, השורות שלו והגלילה לא זזו חמש פריימים ברצף —
#: ‏במקום שינה קבועה ולקוות שהפריסה כבר נרגעה.
COURSE_SETTLED = """() => {
  const c = document.querySelector('#lecturer-courses .lect-course.is-open');
  const rows = c ? c.querySelectorAll('tbody tr') : [];
  if (!rows.length) return false;
  const top = el => Math.round(el.getBoundingClientRect().top * 4);
  const key = [scrollY, document.documentElement.scrollHeight, top(c),
               top(c.querySelector(':scope > .lect-course-h')), top(rows[0]),
               top(rows[rows.length - 1])].join();
  window.__courseSame = key === window.__courseKey ? (window.__courseSame || 0) + 1 : 0;
  window.__courseKey = key;
  return window.__courseSame >= 5;
}"""


def _course_settled(pg):
    pg.evaluate("() => { window.__courseKey = null; window.__courseSame = 0; }")
    pg.wait_for_function(COURSE_SETTLED, polling="raf", timeout=10000)


@pytest.mark.parametrize("size", [NARROW, WIDE], ids=["390", "1440"])
def test_the_open_course_header_stays_visible_while_its_rows_scroll(browser, server, size):
    ctx, pg = _page(browser, server, size)
    try:
        _with_schedule(pg)
        _next(pg, "courses")
        _next(pg, "days")
        pg.evaluate(OPEN_BIGGEST_COURSE)
        pg.evaluate(ROOM_BELOW)
        _course_settled(pg)
        start = pg.evaluate(COURSE)
        # ‏גוללים עד שהשורה הראשונה עוברת אל מתחת לראש המסך: אם הראש
        # ‏לא היה נדבק, הוא היה כבר מעל המסך.
        cover = 48 if size == NARROW else 0
        target = round(start["firstRowAbs"] - cover - 10)
        pg.evaluate(f"() => window.scrollTo(0, {target})")
        _course_settled(pg)
        got = pg.evaluate(COURSE)
    finally:
        ctx.close()
    assert start["rows"] >= 3, start
    # ‏אם זה נכשל, העמוד קצר מכדי לגלול אל היעד — וכל השאר היה נמדד במקום הלא נכון.
    assert abs(got["scrollY"] - target) <= 1, f"הגלילה נחתכה לפני היעד {target}: {got}"
    # ‏הכרטיס כבר יצא מעל הראש; הראש נשאר — זה ה-sticky.
    assert got["cardTopOnScreen"] < got["headTop"] - 20, got
    assert abs(got["headTop"] - cover) <= 1, f"ראש הקורס לא נדבק מתחת לכותרת: {got}"
    assert got["headOnTop"], f"ראש הקורס מוסתר מתחת למשהו: {got}"
    # ‏השורות ממשיכות להיגלל מתחתיו.
    assert got["firstRowTop"] < got["headBottom"], got
    assert got["lastRowBottom"] > got["headBottom"], got


# ==========================================================================
# 4. הסרגל התחתון
# ==========================================================================
def test_no_floating_bar_or_overlay_on_any_width(browser, server):
    for size in (NARROW, WIDE):
        ctx, pg = _page(browser, server, size)
        try:
            _with_schedule(pg)
            _scroll(pg, 600)
            gone = pg.evaluate(
                """() => ['sticky-bar', 'grid-overlay', 'btn-show-grid', 'grid-overlay-panel']
                     .filter(id => document.getElementById(id))""")
        finally:
            ctx.close()
        assert gone == [], f"{size}: {gone}"


def test_the_bottom_bar_needs_a_schedule(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _identity(pg)
        _next(pg, "year")
        _scroll(pg, 400)
        pg.wait_for_timeout(600)
        bar = _bar(pg)
    finally:
        ctx.close()
    assert not bar["visible"], f"אין מערכת, והסרגל מוצג: {bar}"
    assert bar["padding"] == 0, bar


def test_the_bottom_bar_shows_only_when_build_button_and_results_are_off_screen(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _with_schedule(pg)
        _scroll(pg, 400)
        _wait_bar(pg, True)
        assert not _on_screen(pg, "#build-row") and not _on_screen(pg, "#step-schedule")
        shown = _bar(pg)
        pg.evaluate("() => document.getElementById('build-row').scrollIntoView({block: 'center'})")
        _wait_bar(pg, False)
        by_button = _bar(pg)
        pg.evaluate("() => document.getElementById('alt-head').scrollIntoView({block: 'center'})")
        pg.wait_for_timeout(600)
        by_results = _bar(pg)
        results_seen = _on_screen(pg, "#step-schedule")
    finally:
        ctx.close()
    assert shown["visible"], shown
    # ‏"N ימים · עד HH:MM"
    assert "ימים · עד " in shown["facts"] or shown["facts"].startswith("יום אחד · עד "), shown
    assert abs(shown["bottom"] - NARROW[1]) <= 1, f"הסרגל אינו בתחתית המסך: {shown}"
    assert not by_button["visible"], by_button
    assert results_seen and not by_results["visible"], by_results


def test_the_bottom_bar_never_covers_content(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _with_schedule(pg)
        _scroll(pg, 400)
        _wait_bar(pg, True)
        shown = _bar(pg)
        pg.evaluate("() => document.getElementById('build-row').scrollIntoView({block: 'center'})")
        _wait_bar(pg, False)
        hidden = _bar(pg)
    finally:
        ctx.close()
    # ‏בזמן שהוא מוצג, לעמוד יש ריפוד תחתון בגובהו, כך שאפשר לגלול כל תוכן
    # ‏אל מעליו; כשהוא אינו מוצג — אין ריפוד.
    assert abs(shown["padding"] - shown["height"]) <= 1, shown
    assert hidden["padding"] == 0, hidden


def test_the_bottom_bar_button_builds_and_scrolls_to_the_results(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _with_schedule(pg)
        _scroll(pg, 400)
        _wait_bar(pg, True)
        same_look = pg.evaluate(
            """() => { const a = getComputedStyle(document.getElementById('btn-bottom-build'));
                       const b = getComputedStyle(document.getElementById('btn-build'));
                       return [a.backgroundColor === b.backgroundColor, a.color === b.color,
                               a.backgroundColor, a.color]; }""")
        pg.click("#btn-bottom-build")
        pg.wait_for_timeout(2500)
        top = pg.evaluate("() => document.getElementById('step-schedule').getBoundingClientRect().top")
        after = _bar(pg)
        focus = pg.evaluate("() => document.activeElement ? document.activeElement.tagName : null")
        errors = pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()
    assert same_look[0] and same_look[1], f"הכפתור שבסרגל אינו כמו זה שבעמוד: {same_look}"
    assert 0 <= top <= NARROW[1] * 0.4, f"התוצאה לא הגיעה למסך: top={top}"
    assert not after["visible"], after
    assert focus not in (None, "BODY", "HTML"), focus
    assert errors == []


def test_the_bottom_bar_does_not_exist_at_1440(browser, server):
    ctx, pg = _page(browser, server, WIDE)
    try:
        _with_schedule(pg)
        got = []
        for y in (0, 400, 1200):
            _scroll(pg, y)
            got.append(_bar(pg))
        padded = pg.evaluate("() => document.body.classList.contains('has-bottom-bar')")
    finally:
        ctx.close()
    for bar in got:
        assert bar["display"] == "none" and not bar["visible"], bar
    assert not padded


def test_the_ink_hover_token_is_mapped_in_both_dark_blocks():
    """‏‎--ink-hover‎ (‏#2a2a2e / ‏#d9d9d6) — ערך אחד לכל ערכה, ומיפוי בשני
    ‏הגושים הכהים, כמו כל טוקן אחר (CLAUDE.md, "Every colour is written
    exactly once")."""
    css = (ROOT / "src" / "web" / "static" / "style.css").read_text(encoding="utf-8")
    assert css.count("--ink-hover: #2a2a2e;") == 1
    assert css.count("--dark-ink-hover: #d9d9d6;") == 1
    assert css.count("--ink-hover: var(--dark-ink-hover);") == 2


# ==========================================================================
# 5. שורת הימים נעוצה בצר
# ==========================================================================
DAYS_ROW = """() => {
  const grid = document.getElementById('schedule-grid');
  const hd = [...grid.querySelectorAll('.hd')][1];
  const r = hd.getBoundingClientRect();
  const g = grid.getBoundingClientRect();
  const mid = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return {hdTop: r.top, hdBottom: r.bottom, gridTop: g.top, gridBottom: g.bottom,
          gridTopAbs: g.top + scrollY, onTop: !!mid && hd.contains(mid)};
}"""


def test_the_weekday_row_stays_pinned_below_the_thin_header_on_narrow(browser, server):
    ctx, pg = _page(browser, server, NARROW_GRID)
    try:
        _all_steps_done(pg)
        start = pg.evaluate(DAYS_ROW)
        _scroll(pg, start["gridTopAbs"] - 48 + 250, wait=500)
        mid = pg.evaluate(DAYS_ROW)
        cover = pg.evaluate("() => document.getElementById('app-header').getBoundingClientRect().bottom")
        _scroll(pg, start["gridTopAbs"] + 5000, wait=500)
        past = pg.evaluate(DAYS_ROW)
    finally:
        ctx.close()
    assert mid["gridTop"] < cover - 200, mid
    assert abs(mid["hdTop"] - cover) <= 2, f"שורת הימים לא נעוצה מתחת לכותרת: {mid}, cover={cover}"
    assert mid["onTop"], mid
    # ‏לעולם לא מעבר לתחתית הרשת.
    assert past["hdBottom"] <= past["gridBottom"] + 1, past


# ==========================================================================
# 6. רגע הנחיתה
# ==========================================================================
def test_blocks_land_once_per_build_and_not_on_an_alternative_switch(browser, server):
    ctx, pg = _page(browser, server, NARROW_GRID, reduced=False, hook=True)
    try:
        _with_schedule(pg)
        pg.wait_for_timeout(2500)
        first = pg.evaluate(LANDINGS)
        blocks = pg.evaluate("() => document.querySelectorAll('#schedule-grid .ev').length")
        # ‏החלפת חלופה זזה — היא אינה נוחתת.
        pg.evaluate("() => document.getElementById('alt-head').scrollIntoView({block: 'center'})")
        pg.click(".alt-card >> nth=1")
        pg.wait_for_timeout(1500)
        after_switch = pg.evaluate(LANDINGS)
        selected = pg.evaluate(
            "() => [...document.querySelectorAll('.alt-card')].findIndex(c => c.getAttribute('aria-pressed') === 'true')")
        # ‏"בנה מערכות" הוא בנייה: הבלוקים נוחתים שוב, פעם אחת.
        pg.evaluate("() => document.getElementById('build-row').scrollIntoView({block: 'center'})")
        pg.click("#btn-build")
        pg.wait_for_timeout(3500)
        after_build = pg.evaluate(LANDINGS)
        errors = pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()
    assert blocks > 0
    assert len(first) == blocks, f"נחתו {len(first)} מתוך {blocks} בלוקים"
    # ‏חשיפה בלבד: לא הזזה ולא שקיפות (tests/test_no_opacity_on_text.py).
    assert all(a["props"] == ["clipPath"] for a in first), first[:2]
    delays = sorted(a["delay"] for a in first)
    assert delays[0] == 0 and all(b - a == 70 for a, b in zip(delays, delays[1:])), delays
    assert len(after_switch) == len(first), "החלפת חלופה הפעילה את הנחיתה"
    assert selected == 1, "החלופה לא הוחלפה — הבדיקה לא בדקה דבר"
    landed_again = len(after_build) - len(first)
    assert 0 < landed_again <= blocks + 20, f"אחרי בנייה: {landed_again}"
    assert errors == []


def test_the_landing_never_moves_a_block(browser, server):
    """‏clip-path בלבד: בזמן הנחיתה המלבן של כל בלוק כבר במקומו הסופי, כך שכל
    ‏מדידה באמצע — ‏FLIP, פרטי השיעור, התאמה למסך — רואה את המקום הנכון."""
    rects = """() => [...document.querySelectorAll('#schedule-grid .ev')].map(e => {
      const r = e.getBoundingClientRect();
      return [Math.round(r.left), Math.round(r.top + scrollY), Math.round(r.width), Math.round(r.height)]; })"""
    # ‏הנחיתה נעצרת באמצע (pause) באותו פריים שבו היא נמצאה רצה, והפריסה
    # ‏מקבלת זמן להתייצב — גובה השעה נמדד אחרי הציור הראשון. אחר כך מודדים,
    # ‏מסיימים את הנחיתה ומודדים שוב: ההפרש היחיד בין שתי המדידות הוא הנחיתה.
    pause = """() => {
      const anims = [...document.querySelectorAll('#schedule-grid .ev')]
        .flatMap(b => b.getAnimations()).filter(a => a.id === 'ev-land');
      if (!anims.some(a => a.playState === 'running')) return false;
      anims.forEach(a => a.pause());
      return true; }"""
    held = """() => [...document.querySelectorAll('#schedule-grid .ev')]
      .flatMap(b => b.getAnimations()).filter(a => a.id === 'ev-land' && a.playState === 'paused').length"""
    finish = """() => [...document.querySelectorAll('#schedule-grid .ev')]
      .flatMap(b => b.getAnimations()).filter(a => a.id === 'ev-land').forEach(a => a.finish())"""
    ctx, pg = _page(browser, server, WIDE, reduced=False, hook=True)
    try:
        _identity(pg)
        _next(pg, "year")
        pg.click("#btn-restore-recommended")
        pg.wait_for_function(pause, polling="raf", timeout=20000)
        pg.wait_for_timeout(1500)
        paused = pg.evaluate(held)
        during = pg.evaluate(rects)
        pg.evaluate(finish)
        pg.wait_for_timeout(200)
        settled = pg.evaluate(rects)
    finally:
        ctx.close()
    assert paused > 0, "שום נחיתה לא נעצרה באמצע — הבדיקה לא מדדה דבר"
    assert during == settled


def test_reduced_motion_makes_the_landing_instant(browser, server):
    ctx, pg = _page(browser, server, NARROW_GRID, reduced=True, hook=True)
    try:
        _with_schedule(pg)
        pg.wait_for_timeout(300)
        landings = pg.evaluate(LANDINGS)
        shown = pg.evaluate(
            """() => [...document.querySelectorAll('#schedule-grid .ev')]
                     .every(b => getComputedStyle(b).opacity === '1'
                                 && getComputedStyle(b).clipPath === 'none')""")
    finally:
        ctx.close()
    assert landings == []
    assert shown
