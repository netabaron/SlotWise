"""שלב 9 של העיצוב מחדש, חלק ג׳: מעבר נגישות (docs/DESIGN.md, "Quality floor",
"Phase 9C decisions", הוחלט 2026-10-12 אחרי בדיקה על מאגר הבדיקות).

מה נבדק כאן
-----------
* **דירוג במקלדת** (1): בכל שורת מרצה יש כפתור דירוג; Tab מגיע אליו, Enter
  מדרג ורווח מבטל, ‏aria-pressed והשם הנגיש אומרים את הדירוג, והפוקוס נשאר
  על אותו כפתור אחרי שהרשימה נבנית מחדש.
* **טבעת הפוקוס של ראש קורס בשלב המרצים** (2) נראית: צילום של הראש בפוקוס
  שונה מצילומו בלי פוקוס, והטבעת בתוך הכפתור.
* **הסרגל התחתון לעולם אינו מכסה פקד בפוקוס** (3), ב-390.
* **הפוקוס אינו נופל לעמוד** (13): שבב בחירה, "סמנו הכל", והוספה מהחיפוש.
* **אחרי "המשך" האחרון בצר** (14) הפוקוס על כותרת התוצאה.
* **Esc ברשימת הימים** (15) סוגר את פרטי השיעור.
* **שורת המצב הנסתרת** (18, 19): ‏role=status, ‏"מעדכן…" בתחילת חישוב ו"המערכת
  עודכנה: N ימים, עד HH:MM" בסופו — של החלופה הנבחרת.
* **ניגודיות** (4, 5, 6, 8, 9), מחושבת מהצבעים שהדף צייר בפועל, בבהיר ובכהה:
  קוד ונ"ז בראש קורס, פתק הזהב, "קורס צמוד" על כל עשרת גווני הקורס, הרמז
  בשדה החיפוש, ומסגרות הפקדים.

מאגר הבדיקות (scripts/seed_dev_data.py --fixture), הנדסת תוכנה שנה 3 סמסטר א,
הקורסים המומלצים.
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

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import create_app  # noqa: E402

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
ALTS = STRINGS["app"]["alts"]
ROW = STRINGS["app"]["lecturers"]["row"]

WIDE = (1440, 900)
PHONE = (390, 844)
AA = 4.5
UI = 3.0


def fill(template: str, **kw) -> str:
    for k, v in kw.items():
        template = template.replace("{" + k + "}", str(v))
    return template


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


def _page(browser, server, size=WIDE, scheme="light"):
    ctx = browser.new_context(
        viewport={"width": size[0], "height": size[1]}, color_scheme=scheme
    )
    pg = ctx.new_page()
    pg.errors = []  # type: ignore[attr-defined]
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))  # type: ignore[attr-defined]
    pg.goto(server)
    pg.wait_for_timeout(2500)
    pg.select_option("#select-program", "הנדסת תוכנה")
    pg.select_option("#select-year", "3")
    pg.select_option("#select-term", "א")
    pg.wait_for_timeout(2500)
    pg.click("#step-year-next")
    pg.wait_for_timeout(600)
    return ctx, pg


def _recommended(pg):
    pg.click("#btn-restore-recommended")
    pg.wait_for_selector("#alt-cards .alt-card", timeout=20000)
    pg.wait_for_timeout(1500)


def _settled(pg):
    pg.wait_for_function("() => !window.slotwise.getRuntime().solveBusy", timeout=20000)
    pg.wait_for_timeout(400)


def _to_lecturers(pg):
    _recommended(pg)
    pg.click("#step-courses-next")
    pg.wait_for_timeout(800)
    pg.click("#step-days-next")
    pg.wait_for_timeout(1500)


def _active(pg):
    return pg.evaluate(
        """() => { const e = document.activeElement;
                   return e ? {id: e.id, cls: String(e.className || ''), tag: e.tagName,
                               fk: e.dataset ? e.dataset.fk || '' : ''} : null; }"""
    )


# --------------------------------------------------------------------------
# 1. דירוג במקלדת
# --------------------------------------------------------------------------
RANK_BTN = """(fk) => { const b = document.querySelector('[data-fk="' + CSS.escape(fk) + '"]');
  return b && {pressed: b.getAttribute('aria-pressed'), label: b.getAttribute('aria-label'),
               circle: b.querySelector('.rank-circle').textContent.trim(),
               focused: document.activeElement === b}; }"""


def test_a_lecturer_is_ranked_and_unranked_from_the_keyboard(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _to_lecturers(pg)
        # ‏Tab מראש הקורס הפתוח מגיע, אחרי המתגים, לכפתור דירוג.
        pg.locator(".lect-course.is-open .lect-course-head").focus()
        for _ in range(12):
            pg.keyboard.press("Tab")
            if pg.evaluate("document.activeElement.classList.contains('rank-btn')"):
                break
        reached = _active(pg)
        assert "rank-btn" in reached["cls"], reached
        fk = reached["fk"]
        before = pg.evaluate(RANK_BTN, fk)
        pg.keyboard.press("Enter")
        _settled(pg)
        ranked = pg.evaluate(RANK_BTN, fk)
        pg.keyboard.press("Space")
        _settled(pg)
        cleared = pg.evaluate(RANK_BTN, fk)
        errors = pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()
    state = ROW["rankState"]
    assert before["pressed"] == "false" and before["label"].endswith(state["none"]), before
    assert ranked["pressed"] == "true" and ranked["circle"] == "1", ranked
    assert ranked["label"].endswith(fill(state["ranked"], rank=1)), ranked
    assert ranked["focused"], "הפוקוס לא נשאר על כפתור הדירוג אחרי הבנייה מחדש"
    assert cleared["pressed"] == "false" and cleared["circle"] == "", cleared
    assert cleared["focused"], cleared
    assert errors == []


# --------------------------------------------------------------------------
# 2. הטבעת של ראש קורס בשלב המרצים נראית
# --------------------------------------------------------------------------
def test_the_lecturer_course_header_shows_its_focus_ring(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _to_lecturers(pg)
        head = pg.locator(".lect-course-head").nth(1)
        head.scroll_into_view_if_needed()
        pg.focus("#step-lecturers-next")
        off = head.screenshot()
        # ‏Shift+Tab ואז Tab: פוקוס מהמקלדת, כדי ש-:focus-visible יחול.
        head.focus()
        pg.keyboard.press("Shift+Tab")
        pg.keyboard.press("Tab")
        pg.wait_for_timeout(200)
        ring = pg.evaluate(
            """() => { const e = document.activeElement; const cs = getComputedStyle(e);
                       return {head: e.classList.contains('lect-course-head'), fv: e.matches(':focus-visible'),
                               style: cs.outlineStyle, width: parseFloat(cs.outlineWidth),
                               offset: parseFloat(cs.outlineOffset)}; }"""
        )
        on = head.screenshot()
    finally:
        ctx.close()
    assert ring["head"] and ring["fv"], ring
    assert ring["style"] != "none" and ring["width"] > 0, ring
    # ‏בתוך הכפתור: ‎.lect-course‎ חותך כל מה שמחוץ לו.
    assert ring["offset"] + ring["width"] <= 0, ring
    assert on != off, "צילום הראש בפוקוס זהה לצילומו בלי פוקוס — הטבעת אינה נראית"


# --------------------------------------------------------------------------
# 3. הסרגל התחתון אינו מכסה פקד בפוקוס
# --------------------------------------------------------------------------
COVERED = """() => { const e = document.activeElement; const r = e.getBoundingClientRect();
  const bar = document.getElementById('bottom-bar');
  const shown = bar.classList.contains('is-visible');
  const pts = [[.5, .5], [.2, .5], [.8, .5]].map(([x, y]) => {
    const t = document.elementFromPoint(r.left + r.width * x, r.top + r.height * y);
    return !!t && (t === e || e.contains(t)); });
  return {el: String(e.className || e.id), shown, visible: pts.some(Boolean), top: r.top, bottom: r.bottom}; }"""


def test_the_bottom_bar_never_covers_the_focused_control(browser, server):
    ctx, pg = _page(browser, server, size=PHONE)
    try:
        _recommended(pg)
        pg.focus("#course-search")
        seen = []
        for _ in range(16):
            pg.keyboard.press("Tab")
            pg.wait_for_timeout(150)
            seen.append(pg.evaluate(COVERED))
    finally:
        ctx.close()
    under_bar = [s for s in seen if s["shown"]]
    assert under_bar, f"הסרגל לא הוצג באף שלב — הבדיקה לא בדקה דבר: {seen}"
    hidden = [s for s in seen if not s["visible"]]
    assert not hidden, hidden


# --------------------------------------------------------------------------
# 13. הפוקוס אינו נופל לעמוד
# --------------------------------------------------------------------------
def test_restore_recommended_moves_focus_to_its_heading(browser, server):
    ctx, pg = _page(browser, server)
    try:
        pg.focus("#btn-restore-recommended")
        pg.keyboard.press("Enter")
        pg.wait_for_selector("#alt-cards .alt-card", timeout=20000)
        pg.wait_for_timeout(800)
        hidden = pg.evaluate("document.getElementById('btn-restore-recommended').hidden")
        got = _active(pg)
    finally:
        ctx.close()
    assert hidden, "‏\"סמנו הכל\" לא הסתיר את עצמו — הבדיקה לא בדקה דבר"
    assert got["id"] == "recommended-title", got


def test_an_elective_chip_keeps_focus_when_chosen(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _recommended(pg)
        pg.locator(".elective-cluster-head").first.focus()
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(600)
        pg.keyboard.press("Tab")
        chip = _active(pg)
        pg.keyboard.press("Enter")
        _settled(pg)
        after = _active(pg)
        pressed = pg.evaluate(
            "(fk) => document.querySelector('[data-fk=\"' + CSS.escape(fk) + '\"]').getAttribute('aria-pressed')",
            chip["fk"],
        )
    finally:
        ctx.close()
    assert "elective-chip" in chip["cls"] and chip["fk"], chip
    assert pressed == "true", pressed
    assert after["fk"] == chip["fk"], (chip, after)


def test_adding_a_course_from_the_search_returns_focus_to_the_field(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _recommended(pg)
        n0 = pg.evaluate("document.querySelectorAll('#course-list .course-item').length")
        pg.focus("#course-search")
        pg.keyboard.type("מבוא")
        pg.wait_for_timeout(1200)
        # ‏Tab אל התוצאה הראשונה שעוד לא נבחרה.
        pg.locator("#course-search-results li[role=option][aria-selected=false]").first.focus()
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(1500)
        n1 = pg.evaluate("document.querySelectorAll('#course-list .course-item').length")
        got = _active(pg)
    finally:
        ctx.close()
    assert n1 == n0 + 1, (n0, n1)
    assert got["id"] == "course-search", got


# --------------------------------------------------------------------------
# 14. אחרי "המשך" האחרון בצר — הפוקוס על כותרת התוצאה
# --------------------------------------------------------------------------
def test_on_a_phone_the_last_next_moves_focus_to_the_results(browser, server):
    ctx, pg = _page(browser, server, size=PHONE)
    try:
        _to_lecturers(pg)
        pg.focus("#step-lecturers-next")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(2500)
        got = _active(pg)
        top = pg.evaluate("document.getElementById('step-schedule-title').getBoundingClientRect().top")
    finally:
        ctx.close()
    assert got["id"] == "step-schedule-title", got
    assert 0 <= top < PHONE[1], top


# --------------------------------------------------------------------------
# 15. Esc ברשימת הימים
# --------------------------------------------------------------------------
def test_escape_on_a_day_list_lesson_closes_its_details(browser, server):
    ctx, pg = _page(browser, server, size=PHONE)
    try:
        _recommended(pg)
        lesson = pg.locator("#schedule-days .dl-lesson").first
        lesson.focus()
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(600)
        opened = pg.evaluate("!document.getElementById('meeting-detail').hidden")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(500)
        closed = pg.evaluate("document.getElementById('meeting-detail').hidden")
        got = _active(pg)
    finally:
        ctx.close()
    assert opened and closed, (opened, closed)
    assert "dl-lesson" in got["cls"], got


# --------------------------------------------------------------------------
# 18, 19. שורת המצב
# --------------------------------------------------------------------------
def test_the_status_line_says_updating_and_then_the_result(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _recommended(pg)
        node = pg.evaluate(
            """() => { const n = document.getElementById('results-status');
                       window.__said = [];
                       new MutationObserver(() => window.__said.push(n.textContent))
                         .observe(n, {childList: true, characterData: true, subtree: true});
                       const cs = getComputedStyle(n);
                       return {role: n.getAttribute('role'), live: n.getAttribute('aria-live'),
                               hidden: n.hidden, clipped: n.getBoundingClientRect().width <= 1}; }"""
        )
        pg.click("#step-courses-next")
        pg.wait_for_timeout(600)
        pg.click('#days-buttons [data-days="5"]')
        # ‏לא _settled: בזמן ההשהיה (150ms) עוד אין חישוב, ו-solveBusy כבר false.
        pg.wait_for_function(
            "(t) => window.__said.some(s => s.startsWith(t))",
            arg=ALTS["updatedStatus"].split("{")[0],
            timeout=20000,
        )
        pg.wait_for_timeout(300)
        said = pg.evaluate("window.__said")
        sch = pg.evaluate(
            """() => { const s = window.slotwise.getState();
                       const card = document.querySelectorAll('.alt-card')[s.activeSchedule];
                       return card.querySelector('.alt-card-facts').textContent.trim(); }"""
        )
    finally:
        ctx.close()
    assert node["role"] == "status" and not node["hidden"] and node["clipped"], node
    assert ALTS["updating"] in said, said
    assert said[-1] == fill(ALTS["updatedStatus"], facts=sch), (said, sch)


# --------------------------------------------------------------------------
# 4, 5, 6, 8, 9. ניגודיות, מהצבעים שצוירו
# --------------------------------------------------------------------------
CONTRAST = r"""() => {
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', {willReadFrequently: true});
  const rgba = c => { cx.clearRect(0,0,1,1); cx.fillStyle = '#000'; cx.fillStyle = c; cx.fillRect(0,0,1,1);
    const d = cx.getImageData(0,0,1,1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const over = (t, b) => [0,1,2].map(i => t[i] * t[3] + b[i] * (1 - t[3])).concat([1]);
  const lum = c => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); };
    return .2126 * f(c[0]) + .7152 * f(c[1]) + .0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
  const bgOf = el => { const L = []; for (let e = el; e; e = e.parentElement) {
      const c = rgba(getComputedStyle(e).backgroundColor); if (c[3] > 0) L.push(c); if (c[3] >= 1) break; }
    let bg = [255, 255, 255, 1]; for (let i = L.length - 1; i >= 0; i--) bg = over(L[i], bg); return bg; };
  const vis = e => e.getBoundingClientRect().width > 0 && !e.closest('[hidden]');
  const text = (sel, pseudo) => [...document.querySelectorAll(sel)].filter(vis).map(e => {
    const bg = bgOf(e); return ratio(over(rgba(getComputedStyle(e, pseudo || null).color), bg), bg); });
  const edge = sel => [...document.querySelectorAll(sel)].filter(vis).map(e => {
    const bg = bgOf(e.parentElement); return ratio(over(rgba(getComputedStyle(e).borderTopColor), bg), bg); });
  // ‏אסימון מול אסימון: הצבעים של כל עשרת הקורסים, גם אלה שהמערכת לא בחרה.
  const tok = name => { const p = document.createElement('span'); p.style.color = 'var(' + name + ')';
    document.body.appendChild(p); const c = rgba(getComputedStyle(p).color); p.remove(); return c; };
  return {
    meta: text('.lect-course-meta'),
    tiedOnCards: text('.course-item .tag--tied'),
    tiedOnEveryFill: [...Array(10).keys()].map(i => ratio(tok('--tie-line'), tok('--course-' + i))),
    goldOnSurface: ratio(tok('--gold-ink'), tok('--sf')),
    goldOnNote: ratio(tok('--gold-ink'), tok('--gold-bg')),
    clusterNote: text('.elective-cluster-note'),
    placeholder: text('#course-search', '::placeholder'),
    borders: edge('.input, .day-btn, #btn-print'),
  };
}"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_fixed_text_and_borders_meet_aa(browser, server, scheme):
    ctx, pg = _page(browser, server, scheme=scheme)
    try:
        _recommended(pg)
        pg.locator(".elective-cluster-head").first.click()
        pg.wait_for_timeout(600)
        courses = pg.evaluate(CONTRAST)
        pg.click("#step-courses-next")
        pg.wait_for_timeout(800)
        days = pg.evaluate(CONTRAST)
        pg.click("#step-days-next")
        pg.wait_for_timeout(1500)
        lect = pg.evaluate(CONTRAST)
    finally:
        ctx.close()
    assert lect["meta"] and min(lect["meta"]) >= AA, lect["meta"]
    assert courses["tiedOnCards"] and min(courses["tiedOnCards"]) >= AA, courses["tiedOnCards"]
    assert min(courses["tiedOnEveryFill"]) >= AA, courses["tiedOnEveryFill"]
    assert courses["goldOnSurface"] >= AA and courses["goldOnNote"] >= AA, courses
    assert courses["clusterNote"] and min(courses["clusterNote"]) >= AA, courses["clusterNote"]
    assert courses["placeholder"] and min(courses["placeholder"]) >= AA, courses["placeholder"]
    borders = courses["borders"] + days["borders"]
    assert borders and min(borders) >= UI, borders


# --------------------------------------------------------------------------
# 11. קבוצות הרדיו: עצירת Tab אחת, והחצים עוברים ובוחרים
# --------------------------------------------------------------------------
RADIOS = """(sel) => [...document.querySelectorAll(sel)].map(b => ({
  checked: b.getAttribute('aria-checked') === 'true', tab: b.tabIndex,
  focused: document.activeElement === b}))"""


def test_arrow_keys_move_and_select_in_the_radio_groups(browser, server):
    ctx, pg = _page(browser, server)
    try:
        theme = "#theme-toggle [data-theme-choice]"
        start = pg.evaluate(RADIOS, theme)
        pg.locator(theme + "[tabindex='0']").focus()
        pg.keyboard.press("ArrowLeft")  # ‏RTL: ← הוא הבא
        pg.wait_for_timeout(200)
        left = pg.evaluate(RADIOS, theme)
        pg.keyboard.press("End")
        pg.wait_for_timeout(200)
        end = pg.evaluate(RADIOS, theme)
        pg.keyboard.press("Home")
        pg.wait_for_timeout(200)
        home = pg.evaluate(RADIOS, theme)

        _recommended(pg)
        pg.click("#step-courses-next")
        pg.wait_for_timeout(800)
        days = "#days-buttons .day-btn"
        d0 = pg.evaluate(RADIOS, days)
        pg.locator(days + "[tabindex='0']").focus()
        pg.keyboard.press("ArrowLeft")
        pg.wait_for_timeout(300)
        d1 = pg.evaluate(RADIOS, days)
        pg.keyboard.press("ArrowRight")
        pg.wait_for_timeout(300)
        d2 = pg.evaluate(RADIOS, days)
    finally:
        ctx.close()

    def stops(rs):
        return [i for i, r in enumerate(rs) if r["tab"] == 0]

    def picked(rs):
        return [i for i, r in enumerate(rs) if r["checked"]]

    assert picked(start) == [0] and stops(start) == [0], start
    assert picked(left) == [1] and left[1]["focused"] and stops(left) == [1], left
    assert picked(end) == [2] and end[2]["focused"], end
    assert picked(home) == [0] and home[0]["focused"], home
    # ‏בלי יעד עדיין: עצירת ה-Tab היא הכפתור הראשון.
    assert picked(d0) == [] and stops(d0) == [0], d0
    assert picked(d1) == [1] and d1[1]["focused"] and stops(d1) == [1], d1
    assert picked(d2) == [0] and d2[0]["focused"], d2


# --------------------------------------------------------------------------
# 12. ‏ArrowDown מהחיפוש אל התוצאות
# --------------------------------------------------------------------------
SEARCH = """() => { const s = document.getElementById('course-search');
  const id = s.getAttribute('aria-activedescendant');
  const li = id ? document.getElementById(id) : null;
  return {focused: document.activeElement === s, id,
          active: li ? li.classList.contains('is-active') : null,
          taken: li ? li.getAttribute('aria-selected') === 'true' : null,
          first: (document.querySelector('#course-search-results li[role=option]') || {}).id || null}; }"""


def test_arrow_down_moves_from_the_search_into_its_results(browser, server):
    ctx, pg = _page(browser, server)
    try:
        _recommended(pg)
        n0 = pg.evaluate("document.querySelectorAll('#course-list .course-item').length")
        pg.focus("#course-search")
        pg.keyboard.type("מבוא")
        pg.wait_for_timeout(1200)
        pg.keyboard.press("ArrowDown")
        first = pg.evaluate(SEARCH)
        got = first
        for _ in range(10):  # ‏אל התוצאה הראשונה שעוד לא נבחרה
            if not got["taken"]:
                break
            pg.keyboard.press("ArrowDown")
            got = pg.evaluate(SEARCH)
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(1500)
        n1 = pg.evaluate("document.querySelectorAll('#course-list .course-item').length")
    finally:
        ctx.close()
    assert first["focused"] and first["id"] == first["first"] and first["active"], first
    assert got["focused"] and not got["taken"], got
    assert n1 == n0 + 1, (n0, n1)


# --------------------------------------------------------------------------
# 17, 20, 21. שם לאזור הטבלה, השלב הנוכחי, ורמת הכותרת
# --------------------------------------------------------------------------
def test_the_step_marks_regions_and_headings(browser, server):
    current = """() => [...document.querySelectorAll('.step-toggle')]
      .filter(t => t.getAttribute('aria-current') === 'step').map(t => t.id)"""
    ctx, pg = _page(browser, server)
    try:
        at_courses = pg.evaluate(current)
        _recommended(pg)
        pg.click("#step-courses-next")
        pg.wait_for_timeout(800)
        at_days = pg.evaluate(current)
        pg.click('#days-buttons [data-days="2"]')
        pg.wait_for_selector("#days-relax:not([hidden])", timeout=20000)
        relax = pg.evaluate(
            """() => { const h = document.getElementById('days-relax-title');
                       return {tag: h.tagName, text: h.textContent.trim()}; }"""
        )
        pg.click('#days-buttons [data-days="4"]')
        _settled(pg)
        pg.click("#step-days-next")
        pg.wait_for_timeout(1500)
        at_lecturers = pg.evaluate(current)
        regions = pg.evaluate(
            """() => [...document.querySelectorAll('.lect-course')].map(c => {
                 const w = c.querySelector('.lect-table-wrap');
                 return {title: c.querySelector('.lect-course-title').textContent.trim(),
                         role: w && w.getAttribute('role'), label: w && w.getAttribute('aria-label')}; })"""
        )
    finally:
        ctx.close()
    assert at_courses == ["step-courses-toggle"], at_courses
    assert at_days == ["step-days-toggle"], at_days
    assert at_lecturers == ["step-lecturers-toggle"], at_lecturers
    assert relax["tag"] == "H3" and relax["text"], relax
    label = STRINGS["app"]["lecturers"]["table"]["regionLabel"]
    assert regions, regions
    for r in regions:
        assert r["role"] == "region" and r["label"] == fill(label, course=r["title"]), r
