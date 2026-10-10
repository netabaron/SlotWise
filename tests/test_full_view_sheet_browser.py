"""שלב 8 של העיצוב מחדש, חלק ג׳: "צפייה במערכת המלאה ⤢" ושורת הכותרת בטלפון
(docs/DESIGN.md, "Results page", פריט 2; הוחלט 2026-10-07, המידות 2026-10-08).

מה נבדק כאן
-----------
* **הכפתור:** מוצג ב-390x844 (מסך צר — תמיד), ב-1440x650 (צעד 4 של סדר ההתאמה,
  הרשת נגללת בתוך התיבה) ולא ב-1920x1080 (הרשת נכנסת). ‏"הדפסה" תמיד שם.
  הסמל הוא SVG, לא תו.
* **השכבה:** דיאלוג אמיתי (aria-modal, שם מכותרת "מערכת N", הפוקוס כלוא בו
  והדף שמתחתיו inert). **התאמה** (2026-10-08): השבוע כולו בחלון, בלי גלילה
  אנכית או אופקית, בשש מידות חלון; כל בלוק של החלופה שנבחרה נמצא בה, בשלוש
  שורות, בלי גלישה ובלי שורה שיוצאת מהבלוק; הגופן אינו גדול מגודל ההדפסה.
* **"הגדלה":** ‏aria-pressed, גיליון ה-A4 בגודל ההדפסה ונגלל; לחיצה נוספת
  חוזרת להתאמה, וכל פתיחה מתחילה בהתאמה.
* **סגירה:** ‏Esc וכפתור הסגירה, והפוקוס חוזר לכפתור שפתח.
* **החלופה שנבחרה:** אחרי "הבאה" השכבה מראה את המערכת החדשה — אותם שיעורים
  באותם מקומות כמו ברשת שבדף.
* **שורת הכותרת:** ב-390 שורה אחת בלי גלישה, והכפתורים בשורה שמתחתיה; ב-360
  הכותרת והדפדוף בשורה הראשונה והמיון בשנייה. הכותרת 15px, ושאר הטקסט ≥13px.
* **הדפדוף:** "1/5" על המסך, ושם נגיש מלא "מערכת 1 מתוך 5". ‏"מיון" נשאר השם
  הנגיש של ה-select גם כשהוא מוסתר.
* **הדפסה:** מהדף — עמוד A4 אחד, שלוש שורות, אותו גופן שגיליון ה-A4 של השכבה
  בחר (גודל ההדפסה); והשכבה עצמה אינה מגיעה לנייר.

מאגר הבדיקות (scripts/seed_dev_data.py --fixture), הנדסת תוכנה שנה 3 סמסטר א.
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
SHEET = STRINGS["app"]["sheet"]

PHONE = (390, 844)
SMALL_PHONE = (360, 800)
STEP4 = (1440, 650)
FITS = (1920, 1080)
#: ‏A4 לאורך בפיקסלי CSS — הרוחב שבו emulate_media("print") מתנהג כמו הנייר.
PAGE_W, PAGE_H = 794, 1123
#: ‏ששת החלונות שבהם נמדדה ההתאמה (DESIGN.md, "Results page", 2). ב-1440x900
#: וב-1920x1080 הרשת נכנסת והכפתור אינו מוצג; שם השכבה נפתחת דרכו בכוח.
FIT_SIZES = [PHONE, SMALL_PHONE, (1366, 768), STEP4, (1440, 900), FITS]


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


def _open(browser, server, size):
    ctx = browser.new_context(viewport={"width": size[0], "height": size[1]}, color_scheme="light")
    page = ctx.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    page.goto(server)
    page.wait_for_timeout(2500)
    page.select_option("#select-program", "הנדסת תוכנה")
    page.select_option("#select-year", "3")
    page.select_option("#select-term", "א")
    page.wait_for_timeout(2500)
    page.click("#step-year-next")
    page.click("#btn-restore-recommended")
    # ‏התוצאה, ולא הרשת: מתחת ל-1000px המערכת שבדף היא רשימת ימים
    # ‏(DESIGN.md, "Results page", 5; ‏2026-10-10). כשהרשת על המסך — גובה השעה.
    page.wait_for_function(
        "() => [...document.querySelectorAll('#schedule-grid .ev, #schedule-days .dl-lesson')]"
        ".some(e => e.getClientRects().length > 0)",
        timeout=20000,
    )
    page.wait_for_function(
        "() => !!document.getElementById('schedule-grid').style.getPropertyValue('--slot-h')"
        " || getComputedStyle(document.getElementById('grid-scroll')).display === 'none'",
        timeout=15000,
    )
    page.wait_for_timeout(900)
    return ctx, page


def _open_sheet(page):
    if not _shown(page, "#btn-full"):
        # ‏הכפתור מוסתר כשהשבוע נכנס במסך (צעדים 1–3). השכבה עצמה לא תלויה בזה.
        page.evaluate("() => { const b = document.getElementById('btn-full'); b.hidden = false; b.click(); }")
    else:
        page.click("#btn-full")
    page.wait_for_function("() => !document.getElementById('sheet-layer').hidden")
    page.wait_for_timeout(300)


def _shown(page, selector):
    return page.evaluate(
        """(sel) => { const e = document.querySelector(sel);
                      return !!e && !e.hidden && e.getClientRects().length > 0
                             && getComputedStyle(e).visibility !== 'hidden'; }""",
        selector,
    )


#: כל בלוק בשכבה ובדף: מפתח השיעור והמקום, השורות, וגלישה.
SHEET_STATE = """() => {
  const L = document.getElementById('sheet-layer');
  const sheet = document.getElementById('sheet');
  const box = document.getElementById('sheet-scroll');
  const blocks = sel => [...document.querySelectorAll(sel)].map(e => {
    const cs = getComputedStyle(e);
    const r = e.getBoundingClientRect();
    const top = r.top + parseFloat(cs.borderTopWidth);
    const bottom = r.bottom - parseFloat(cs.borderBottomWidth);
    const lines = [...e.querySelectorAll(':scope > .ev-line')].map(l => {
      const lr = l.getBoundingClientRect();
      return {cls: l.className.replace('ev-line', '').trim(), text: l.textContent.trim(),
              shown: getComputedStyle(l).display !== 'none' && lr.height > 0,
              inside: lr.top >= top - 0.5 && lr.bottom <= bottom + 0.5};
    });
    return {key: e.dataset.lesson + '@' + e.dataset.slot, lines,
            over: e.scrollHeight - e.clientHeight, font: parseFloat(cs.fontSize)};
  });
  const title = document.getElementById(L.getAttribute('aria-labelledby'));
  const zoom = document.getElementById('sheet-zoom');
  const font = id => parseFloat(document.getElementById(id).style.getPropertyValue('--ev-font-print')) || 13;
  return {hidden: L.hidden, role: L.getAttribute('role'), modal: L.getAttribute('aria-modal'),
          title: title ? title.textContent.trim() : null,
          vScroll: box.scrollHeight > box.clientHeight, hScroll: box.scrollWidth > box.clientWidth,
          zoomed: L.classList.contains('is-zoomed'), pressed: zoom.getAttribute('aria-pressed'),
          a4Shown: getComputedStyle(sheet).visibility === 'visible' && getComputedStyle(sheet).position !== 'fixed',
          fitShown: getComputedStyle(document.getElementById('sheet-fit')).display !== 'none',
          printFont: font('sheet-grid'), fitFont: font('sheet-fit-grid'),
          sheet: blocks('#sheet-fit-grid .ev'), a4: blocks('#sheet-grid .ev'), page: blocks('#schedule-grid .ev'),
          listShown: getComputedStyle(document.getElementById('schedule-days')).display !== 'none',
          list: [...document.querySelectorAll('#schedule-days .dl-lesson')].map(e => ({
            key: e.dataset.lesson + '@' + e.dataset.slot,
            name: e.querySelector('.dl-name').textContent.trim(),
            kind: (e.querySelector('.dl-kind') || {textContent: ''}).textContent.trim(),
            room: (e.querySelector('.ev-room') || {textContent: ''}).textContent.trim(),
            label: e.getAttribute('aria-label')})),
          active: document.activeElement ? document.activeElement.id : null,
          inert: [...document.body.children].filter(n => n !== L && n.tagName !== 'SCRIPT')
                   .every(n => n.inert),
          activeSchedule: window.slotwise.getState().activeSchedule};
}"""


def _content(blocks):
    return sorted((b["key"], tuple(ln["text"] for ln in b["lines"])) for b in blocks)


def _in_page(st):
    """המערכת שבדף: רשימת הימים מתחת ל-1000px, הרשת מעליו (2026-10-10)."""
    return st["list"] if st["listShown"] else st["page"]


def _same_as_list(sheet, items):
    """אותם שיעורים, באותם מקומות ובאותו תוכן כמו רשימת הימים שבדף: שם,
    סוג וחדר בשורות, והמרצה — שאינו שורה ברשימה — בשם הנגיש."""
    assert sorted(b["key"] for b in sheet) == sorted(i["key"] for i in items)
    by_key = {i["key"]: i for i in items}
    for b in sheet:
        item = by_key[b["key"]]
        name, when, who = (ln["text"] for ln in b["lines"])
        assert item["name"] == name, (b["key"], item, name)
        assert when.startswith(item["kind"]), (b["key"], item, when)
        assert item["room"] in who and who.split(" · ")[0] in item["label"], (b["key"], item, who)


def _assert_full_blocks(blocks, where):
    assert blocks, f"{where}: אין בלוקים"
    for b in blocks:
        names = [ln["cls"] for ln in b["lines"]]
        assert names == ["ev-name", "ev-when", "ev-who"], (where, b["key"], names)
        for ln in b["lines"]:
            assert ln["shown"] and ln["text"], (where, b["key"], ln)
            assert ln["inside"], f"{where}: שורה יוצאת מהבלוק {b['key']}: {ln}"
        assert b["over"] <= 0, f"{where}: בלוק גולש {b['key']} ב-{b['over']}px"


# ==========================================================================
# 1. הכפתור — מתי הוא מוצג
# ==========================================================================
def test_button_is_shown_on_a_phone_with_an_svg_icon_next_to_print(browser, server):
    ctx, pg = _open(browser, server, PHONE)
    try:
        assert _shown(pg, "#btn-full")
        assert _shown(pg, "#btn-print")
        got = pg.evaluate(
            """() => { const b = document.getElementById('btn-full');
                       return {text: b.textContent.trim(), svg: !!b.querySelector('svg[aria-hidden="true"]'),
                               popup: b.getAttribute('aria-haspopup')}; }"""
        )
        assert got["text"] == STRINGS["ui"]["schedule"]["btnFull"], got
        assert "⤢" not in got["text"] and got["svg"], got
        assert got["popup"] == "dialog", got
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_button_is_shown_at_step_4_and_absent_when_the_week_fits(browser, server):
    for size, want in ((STEP4, True), (FITS, False)):
        ctx, pg = _open(browser, server, size)
        try:
            fit = pg.evaluate("document.getElementById('step-schedule').dataset.fit || null")
            if want:
                assert fit == "4", (size, fit)
            else:
                assert fit in ("1", "2", "3"), (size, fit)
            assert _shown(pg, "#btn-full") is want, (size, fit)
            assert _shown(pg, "#btn-print"), size
            assert pg.errors == []  # type: ignore[attr-defined]
        finally:
            ctx.close()


# ==========================================================================
# 2. השכבה
# ==========================================================================
@pytest.mark.parametrize("size", FIT_SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_layer_fits_the_whole_week_in_the_window_with_every_block_in_full(browser, server, size):
    ctx, pg = _open(browser, server, size)
    try:
        _open_sheet(pg)
        st = pg.evaluate(SHEET_STATE)
        assert st["role"] == "dialog" and st["modal"] == "true", st
        assert st["title"] == fill(SHEET["title"], n=st["activeSchedule"] + 1), st["title"]
        assert st["inert"], "הדף שמתחת לשכבה אמור להיות inert"
        assert not st["zoomed"] and st["pressed"] == "false" and st["fitShown"] and not st["a4Shown"]
        # ‏השבוע כולו, בלי גלילה.
        assert not st["vScroll"] and not st["hScroll"], (size, st["vScroll"], st["hScroll"])
        # כל בלוק של החלופה שנבחרה, ואותו מקום — לא פחות, לא יותר.
        assert sorted(b["key"] for b in st["sheet"]) == sorted(b["key"] for b in _in_page(st))
        _assert_full_blocks(st["sheet"], f"השכבה ב-{size}")
        fonts = {b["font"] for b in st["sheet"]}
        assert fonts == {st["fitFont"]}, (fonts, st["fitFont"])
        # ‏לעולם לא גדול מגודל ההדפסה — הגופן שגיליון ה-A4 קיבל, כמו בהדפסה.
        assert 0 < st["fitFont"] <= st["printFont"] <= 13, (st["fitFont"], st["printFont"])
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_zoom_shows_the_print_size_scrolling_and_resets_on_reopen(browser, server):
    ctx, pg = _open(browser, server, STEP4)
    try:
        _open_sheet(pg)
        assert pg.get_by_role("button", name=SHEET["zoom"], exact=True).count() == 1
        pg.click("#sheet-zoom")
        pg.wait_for_timeout(400)
        st = pg.evaluate(SHEET_STATE)
        assert st["zoomed"] and st["pressed"] == "true", st
        assert st["a4Shown"] and not st["fitShown"], st
        # ‏גודל ההדפסה, ולכן גבוה מהחלון: נגלל.
        assert st["vScroll"], "בהגדלה הגיליון אמור להיגלל"
        assert {b["font"] for b in st["a4"]} == {st["printFont"]}, st["printFont"]
        _assert_full_blocks(st["a4"], "הגדלה")

        pg.click("#sheet-zoom")
        pg.wait_for_timeout(400)
        st = pg.evaluate(SHEET_STATE)
        assert not st["zoomed"] and st["pressed"] == "false" and st["fitShown"], st
        assert not st["vScroll"] and not st["hScroll"], st

        # ‏סגירה בזמן הגדלה, ופתיחה מחדש — שוב בהתאמה.
        pg.click("#sheet-zoom")
        pg.wait_for_timeout(300)
        pg.click("#sheet-close")
        pg.wait_for_timeout(300)
        _open_sheet(pg)
        st = pg.evaluate(SHEET_STATE)
        assert not st["zoomed"] and st["pressed"] == "false", st
        assert not st["vScroll"] and not st["hScroll"], st
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_focus_is_trapped_and_esc_and_close_return_it_to_the_button(browser, server):
    ctx, pg = _open(browser, server, PHONE)
    try:
        pg.focus("#btn-full")
        _open_sheet(pg)
        inside = "() => document.getElementById('sheet-layer').contains(document.activeElement)"
        assert pg.evaluate(inside)
        for _ in range(5):
            pg.keyboard.press("Tab")
            assert pg.evaluate(inside), "Tab יצא מהשכבה"
        for _ in range(5):
            pg.keyboard.press("Shift+Tab")
            assert pg.evaluate(inside), "Shift+Tab יצא מהשכבה"

        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        got = pg.evaluate(
            "() => ({hidden: document.getElementById('sheet-layer').hidden, active: document.activeElement.id,"
            " inert: [...document.body.children].some(n => n.inert)})"
        )
        assert got == {"hidden": True, "active": "btn-full", "inert": False}, got

        _open_sheet(pg)
        pg.click("#sheet-close")
        pg.wait_for_timeout(200)
        got = pg.evaluate(
            "() => ({hidden: document.getElementById('sheet-layer').hidden, active: document.activeElement.id})"
        )
        assert got == {"hidden": True, "active": "btn-full"}, got
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_esc_closes_the_layer_after_a_click_on_the_top_bar_background(browser, server):
    """לחיצה על רקע הסרגל מעבירה את הפוקוס ל-body, מחוץ לשכבה — ו-Esc עדיין סוגר."""
    ctx, pg = _open(browser, server, PHONE)
    try:
        _open_sheet(pg)
        # ‏נקודה ריקה בסרגל: בין הכותרת (מימין) לכפתורים (משמאל; "הגדלה" הקרוב).
        spot = pg.evaluate(
            """() => { const bar = document.querySelector('.sheet-bar').getBoundingClientRect();
                       const t = document.getElementById('sheet-title').getBoundingClientRect();
                       const p = document.getElementById('sheet-zoom').getBoundingClientRect();
                       return {x: (t.left + p.right) / 2, y: (bar.top + bar.bottom) / 2,
                               gap: t.left - p.right}; }"""
        )
        assert spot["gap"] > 10, spot
        pg.mouse.click(spot["x"], spot["y"])
        hit = pg.evaluate(
            "([x, y]) => document.elementFromPoint(x, y).className", [spot["x"], spot["y"]]
        )
        assert hit == "sheet-bar", hit
        assert pg.evaluate("document.activeElement === document.body"), pg.evaluate(
            "document.activeElement.id"
        )
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        got = pg.evaluate(
            "() => ({hidden: document.getElementById('sheet-layer').hidden, active: document.activeElement.id})"
        )
        assert got == {"hidden": True, "active": "btn-full"}, got
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_layer_follows_the_selected_alternative(browser, server):
    ctx, pg = _open(browser, server, PHONE)
    try:
        _open_sheet(pg)
        first = pg.evaluate(SHEET_STATE)
        pg.click("#sheet-close")
        pg.click("#alt-next")
        pg.wait_for_timeout(1200)
        _open_sheet(pg)
        second = pg.evaluate(SHEET_STATE)
        assert second["activeSchedule"] != first["activeSchedule"]
        assert second["title"] == fill(SHEET["title"], n=second["activeSchedule"] + 1)
        # ‏אותם שיעורים, באותם מקומות ובאותו תוכן כמו הרשת שבדף. החלופה הבאה
        # יכולה להיבדל רק בקבוצה (מרצה או חדר) באותה שעה, ולכן ההשוואה
        # לקודמת היא על התוכן, לא רק על המקום.
        _same_as_list(second["sheet"], second["list"])
        assert _content(second["sheet"]) != _content(first["sheet"])
        _assert_full_blocks(second["sheet"], "אחרי הבאה")
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


# ==========================================================================
# 3. שורת הכותרת בטלפון
# ==========================================================================
HEAD = """() => {
  const box = el => { const r = el.getBoundingClientRect();
                      return {l: r.left, r: r.right, t: r.top, b: r.bottom, mid: (r.top + r.bottom) / 2}; };
  const head = document.getElementById('alt-head');
  const sel = document.getElementById('alt-sort');
  const texts = [...head.querySelectorAll('*')].filter(e =>
      [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()) && e.getClientRects().length
      && !e.closest('.visually-hidden') && !e.closest('.alt-sort-label') && e.tagName !== 'OPTION');
  return {head: box(head), overflow: head.scrollWidth - head.clientWidth,
          page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          title: box(document.getElementById('alt-title')), sort: box(sel),
          nav: box(head.querySelector('.alt-nav')),
          print: box(document.getElementById('btn-print')), full: box(document.getElementById('btn-full')),
          titleFont: parseFloat(getComputedStyle(document.getElementById('alt-title')).fontSize),
          small: texts.filter(e => e.id !== 'alt-title' && parseFloat(getComputedStyle(e).fontSize) < 13)
                      .map(e => e.textContent.trim()),
          options: [...sel.options].map(o => [o.value, o.textContent])};
}"""


def _inside(item, head):
    return item["l"] >= head["l"] - 0.5 and item["r"] <= head["r"] + 0.5


def _same_line(a, b):
    return abs(a["mid"] - b["mid"]) < 8


def test_phone_header_is_one_line_at_390_with_the_buttons_below(browser, server):
    ctx, pg = _open(browser, server, PHONE)
    try:
        h = pg.evaluate(HEAD)
        assert h["overflow"] <= 0 and h["page"] <= 0, h
        for k in ("title", "sort", "nav", "print", "full"):
            assert _inside(h[k], h["head"]), (k, h[k], h["head"])
        assert _same_line(h["title"], h["sort"]) and _same_line(h["title"], h["nav"]), h
        first_bottom = max(h["title"]["b"], h["sort"]["b"], h["nav"]["b"])
        assert h["print"]["t"] >= first_bottom and h["full"]["t"] >= first_bottom, h
        assert _same_line(h["print"], h["full"]), h
        assert h["titleFont"] == 15, h["titleFont"]
        assert h["small"] == [], h["small"]
        assert h["options"] == [[k, ALTS["sort"][k]] for k in ("fit", "gaps", "finish", "days")]
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_phone_header_at_360_moves_only_the_sort_to_the_second_line(browser, server):
    ctx, pg = _open(browser, server, SMALL_PHONE)
    try:
        h = pg.evaluate(HEAD)
        assert h["overflow"] <= 0 and h["page"] <= 0, h
        for k in ("title", "sort", "nav", "print", "full"):
            assert _inside(h[k], h["head"]), (k, h[k], h["head"])
        assert _same_line(h["title"], h["nav"]), h
        first_bottom = max(h["title"]["b"], h["nav"]["b"])
        assert h["sort"]["t"] >= first_bottom, h
        assert h["print"]["t"] >= h["sort"]["b"] and h["full"]["t"] >= h["sort"]["b"], h
        assert h["titleFont"] == 15, h["titleFont"]
        assert h["small"] == [], h["small"]
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_pager_shows_1_of_5_and_keeps_its_full_accessible_name(browser, server):
    ctx, pg = _open(browser, server, PHONE)
    try:
        assert pg.text_content("#alt-pos") == fill(ALTS["position"], pos=1, total=5) == "1/5"
        assert pg.get_attribute("#alt-pos", "aria-hidden") == "true"
        name1 = fill(ALTS["positionLabel"], pos=1, total=5)
        assert "מתוך" in name1
        assert pg.get_by_role("group", name=name1, exact=True).count() == 1
        assert pg.get_attribute("#alt-pos-label", "aria-live") == "polite"
        # ‏"מיון" נשאר השם הנגיש של ה-select, גם כשהוא מוסתר על המסך.
        assert pg.get_by_role("combobox", name=ALTS["sortLabel"], exact=True).count() == 1
        assert not _shown(pg, ".alt-sort-label") or pg.evaluate(
            "document.querySelector('.alt-sort-label').getBoundingClientRect().width <= 1"
        )
        pg.click("#alt-next")
        pg.wait_for_timeout(800)
        assert pg.text_content("#alt-pos") == "2/5"
        assert pg.get_by_role("group", name=fill(ALTS["positionLabel"], pos=2, total=5), exact=True).count() == 1
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


# ==========================================================================
# 4. הדפסה
# ==========================================================================
def test_print_from_the_page_is_unchanged_and_matches_the_layer(browser, server):
    ctx, pg = _open(browser, server, (PAGE_W, PAGE_H))
    try:
        _open_sheet(pg)
        layer_font = pg.evaluate(
            "document.getElementById('sheet-grid').style.getPropertyValue('--ev-font-print')"
        )
        # ‏הדפסה בזמן שהשכבה פתוחה: השכבה אינה על הנייר, הרשת של הדף כן.
        pg.emulate_media(media="print")
        pg.wait_for_timeout(1000)
        got = pg.evaluate(
            """() => ({layer: getComputedStyle(document.getElementById('sheet-layer')).display,
                       font: document.getElementById('schedule-grid').style.getPropertyValue('--ev-font-print'),
                       body: Math.round(document.body.scrollHeight)})"""
        )
        assert got["layer"] == "none", got
        assert got["body"] <= PAGE_H, got
        assert got["font"] == layer_font and layer_font, (got, layer_font)
        pg.emulate_media(media="screen")
        pg.wait_for_timeout(600)
        pg.click("#sheet-close")
        pg.wait_for_timeout(300)

        # ‏ומהדף, בלי שהשכבה נפתחה: עמוד אחד, שלוש שורות בכל בלוק.
        pg.emulate_media(media="print")
        pg.wait_for_timeout(1000)
        st = pg.evaluate(SHEET_STATE)
        _assert_full_blocks(st["page"], "הדפסה")
        assert pg.evaluate("Math.round(document.body.scrollHeight)") <= PAGE_H
        assert pg.evaluate(
            "document.getElementById('schedule-grid').style.getPropertyValue('--ev-font-print')"
        ) == layer_font
        pg.emulate_media(media="screen")
        pg.wait_for_timeout(600)
        assert pg.evaluate(
            "document.getElementById('schedule-grid').style.getPropertyValue('--ev-font-print')"
        ) == ""
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()
