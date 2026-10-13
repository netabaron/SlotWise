"""תמרור האזהרה ליד כל "קבוצה מלאה" (DESIGN.md, Tokens, Color, "Warning sign", 2026-10-13).

משולש צהוב עם "!" שחור וקו מתאר שחור, ‏aria-hidden, בחמישה מקומות — ורק לקבוצה
מלאה (‏``status_note`` בדיוק "הקורס מלא"):

1. ‏"קבוצה מלאה" בבלוק של הרשת (‎.ev-full‎), ואותו סימון ברשימה לפי יום (‎.dl-full‎).
2. שורת המצב של הקבוצה בשלב המרצים (‎.group-status‎).
3. השורה "חלק מהקבוצות במערכת הזו מלאות..." (‎.fit-full‎).
4. שורת המצב בפאנל הפרטים.
5. ‏"קבוצה מלאה" בשורת "ללא מועד קבוע".

הטקסט שליד התמרור נשאר כפי שהיה, תו בתו: התמרור אינו מוסיף טקסט.
הצבעים זהים בבהיר, בכהה ובהדפסה.

כמו ‎tests/test_results_status_browser.py‎: צד הדף נבדק בתשובות ‎/api/solve‎
מיורטות שמקבלות מצב ידוע; שלב המרצים — בקטלוג הקפוא (11061, קבוצה מלאה ולא מלאה).
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

from src.web.api import create_app  # noqa: E402

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
GRID = STRINGS["app"]["grid"]
SCHED = STRINGS["app"]["schedule"]
DETAIL = STRINGS["app"]["detail"]
APP_JS = (ROOT / "src" / "web" / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "src" / "web" / "static" / "style.css").read_text(encoding="utf-8")
STORAGE_KEY = "braude_schedule_builder_v1"  # אין לשנותו — ראו CLAUDE.md

FULL = re.search(r'var FULL_STATUS = "([^"]+)";', APP_JS).group(1)
REPEATERS = "מיועד לחוזרים"

#: קורס עם מפגשים בקורסים המומלצים (הנדסת תוכנה, שנה 3, סמסטר א').
BLOCK_CODE = "61756"
#: פרויקט בלי מועד קבוע בשום קטלוג.
NO_TIME_CODE = "61998"
#: בקטלוג הקפוא: 11061 שו"ת, קבוצה מלאה וקבוצה שאינה מלאה.
LECT_CODE, LECT_KIND = "11061", 'שו"ת'
LECT_FULL, LECT_OPEN = "271020210", "271420310"


# --------------------------------------------------------------------------
# תשתית
# --------------------------------------------------------------------------
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


def _statuses(by_code):
    """מיירט את ‎/api/solve‎: כל pick מקבל את המצב שב-by_code, ואחר — ריק."""
    def handler(route):
        response = route.fetch()
        data = response.json()
        for sch in data.get("schedules") or []:
            for p in sch["picks"]:
                p["status_note"] = by_code.get(p["code"], "")
        route.fulfill(
            status=response.status,
            headers={"content-type": "application/json"},
            body=json.dumps(data, ensure_ascii=False),
        )
    return handler


def _open(browser, server, by_code=None, extra_codes=(), width=1440, height=1426, scheme="light"):
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
    page = ctx.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    if by_code is not None:
        page.route("**/api/solve", _statuses(by_code))
    ready = "#schedule-grid .ev" if width >= 1000 else "#day-list .dl-lesson, .dl-lesson"
    page.goto(server)
    page.wait_for_timeout(2500)
    page.select_option("#select-program", "הנדסת תוכנה")
    page.select_option("#select-year", "3")
    page.select_option("#select-term", "א")
    page.wait_for_timeout(2500)
    page.click("#step-year-next")
    page.click("#btn-restore-recommended")
    page.wait_for_selector(ready, state="attached", timeout=20000)
    if extra_codes:
        page.evaluate(
            """(a) => { const s = JSON.parse(localStorage.getItem(a.key) || '{}');
                        s.codes = (s.codes || []).concat(a.codes);
                        localStorage.setItem(a.key, JSON.stringify(s)); }""",
            {"key": STORAGE_KEY, "codes": list(extra_codes)},
        )
        page.reload()
        page.wait_for_selector(ready, state="attached", timeout=20000)
    page.wait_for_timeout(900)
    return ctx, page


#: לכל אלמנט שתואם: הטקסט שלו, האם התמרור הוא הילד הראשון, ‏aria-hidden,
#: ומידות — התמרור מול הטקסט שאחריו (‏Range על צומת הטקסט).
MARKS = """(sel) => [...document.querySelectorAll(sel)].map(n => {
  const s = n.querySelector('svg.warn-sign');
  const out = {text: n.textContent, sign: !!s, signs: n.querySelectorAll('svg.warn-sign').length};
  if (!s) return out;
  const before = document.createRange();
  before.setStart(n, 0);
  before.setEndBefore(s);
  out.first = before.toString() === '';
  const join = s.parentNode;
  out.join = join.classList.contains('warn-sign-join') ? join.textContent : null;
  out.nowrap = getComputedStyle(join).whiteSpace;
  out.hidden = s.getAttribute('aria-hidden');
  out.title = !!s.querySelector('title');
  const r = s.getBoundingClientRect();
  let t = s.nextSibling;
  while (t && t.nodeType === 1 && !t.textContent) t = t.nextSibling;
  out.fs = parseFloat(getComputedStyle(n).fontSize);
  if (t && r.width) {
    const range = document.createRange();
    range.selectNodeContents(t);
    const rects = [...range.getClientRects()];
    const tr = rects[0];
    out.geo = {sL: r.left, sR: r.right, sT: r.top, sB: r.bottom, h: r.height,
               tL: tr.left, tR: tr.right, tT: tr.top, tB: tr.bottom};
  }
  return out;
})"""


def _assert_sign(m, text):
    assert m["sign"] and m["signs"] == 1, m
    assert m["first"], m  # לפני הטקסט: בצד הימני ב-RTL
    # ‏התמרור והמילה הראשונה ב-span אחד עם nowrap — לא נפרדים בשבירת שורה.
    assert m["join"] == text.split(" ")[0] and m["nowrap"] == "nowrap", m
    assert m["hidden"] == "true" and not m["title"], m
    assert m["text"] == text, m  # הטקסט נשאר תו בתו, בלי תוספת


def _assert_geometry(m):
    """בגודל הטקסט, בשורה שלו, מימין לו (RTL), עם מרווח קטן."""
    g = m.get("geo")
    assert g, m
    assert 0.8 * m["fs"] <= g["h"] <= 1.25 * m["fs"], m
    middle = (g["sT"] + g["sB"]) / 2
    assert g["tT"] <= middle <= g["tB"], m
    gap = g["sL"] - g["tR"]
    assert 1 <= gap <= 0.6 * m["fs"], (gap, m)


# --------------------------------------------------------------------------
# 1. בלוק הרשת, ורשימת הימים
# --------------------------------------------------------------------------
def test_grid_block_of_a_full_group_has_the_sign_and_others_do_not(browser, server):
    ctx, pg = _open(browser, server, by_code={BLOCK_CODE: FULL})
    try:
        blocks = pg.evaluate(
            """() => [...document.querySelectorAll('#schedule-grid .ev')].map(e => ({
                 code: e.dataset.code, signs: e.querySelectorAll('svg.warn-sign').length,
                 over: e.scrollHeight - e.clientHeight}))"""
        )
        full = [b for b in blocks if b["code"] == BLOCK_CODE]
        assert full and all(b["signs"] == 1 for b in full), blocks
        assert all(b["signs"] == 0 for b in blocks if b["code"] != BLOCK_CODE), blocks
        # ‏התמרור אינו מוסיף שורה: שלוש השורות עדיין נכנסות בכל בלוק.
        assert all(b["over"] <= 0 for b in blocks), blocks
        marks = pg.evaluate(MARKS, "#schedule-grid .ev .ev-full")
        assert marks, "אין ‎.ev-full‎ ברשת"
        for m in marks:
            _assert_sign(m, GRID["groupFull"])
            _assert_geometry(m)
        assert pg.errors == [], pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_day_list_marks_a_full_group_with_the_sign(browser, server):
    ctx, pg = _open(browser, server, by_code={BLOCK_CODE: FULL}, width=390, height=844)
    try:
        lessons = pg.evaluate(
            """() => [...document.querySelectorAll('.dl-lesson')].map(e => ({
                 code: e.dataset.code, signs: e.querySelectorAll('svg.warn-sign').length}))"""
        )
        assert any(x["code"] == BLOCK_CODE for x in lessons), lessons
        for x in lessons:
            assert x["signs"] == (1 if x["code"] == BLOCK_CODE else 0), lessons
        marks = pg.evaluate(MARKS, ".dl-lesson .dl-full")
        assert marks
        for m in marks:
            _assert_sign(m, GRID["groupFull"])
            _assert_geometry(m)
        assert pg.errors == [], pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()


# --------------------------------------------------------------------------
# 2. שלב המרצים
# --------------------------------------------------------------------------
def test_lecturer_row_of_a_full_group_has_the_sign(browser, server):
    ctx, pg = _open(browser, server, extra_codes=(LECT_CODE,))
    try:
        row = 'tr[data-fk="row-{}-{}-{}"] .group-status'.format(
            LECT_CODE, LECT_KIND.replace('"', '\\"'), "{}")
        full = pg.evaluate(MARKS, row.format(LECT_FULL))
        assert len(full) == 1, full
        _assert_sign(full[0], FULL)
        # ‏הקבוצה שאינה מלאה: אין לה תמרור (וייתכן שאין לה שורת מצב בכלל).
        assert not any(m["sign"] for m in pg.evaluate(MARKS, row.format(LECT_OPEN)))
        # ‏ובכל השלב: תמרור רק בשורת מצב שאומרת בדיוק "הקורס מלא".
        for m in pg.evaluate(MARKS, ".lect-table .group-status"):
            assert m["sign"] == (m["text"] == FULL), m
        assert pg.evaluate("document.querySelectorAll('.lect-table svg.warn-sign').length") == \
            sum(1 for m in pg.evaluate(MARKS, ".lect-table .group-status") if m["sign"])
    finally:
        ctx.close()


# --------------------------------------------------------------------------
# 3. השורה "חלק מהקבוצות במערכת הזו מלאות"
# --------------------------------------------------------------------------
def test_full_groups_line_has_the_sign(browser, server):
    ctx, pg = _open(browser, server, by_code={BLOCK_CODE: FULL})
    try:
        marks = pg.evaluate(MARKS, "#schedule-summary .fit-full")
        assert len(marks) == 1, marks
        _assert_sign(marks[0], SCHED["fullGroupsLine"])
        _assert_geometry(marks[0])
    finally:
        ctx.close()


def test_no_full_group_means_no_sign_anywhere(browser, server):
    """בלי קבוצה מלאה: אין שורה, ואין תמרור בשום מקום בדף התוצאה."""
    ctx, pg = _open(browser, server, by_code={BLOCK_CODE: REPEATERS})
    try:
        assert pg.evaluate("document.querySelectorAll('.fit-full').length") == 0
        assert pg.evaluate("document.querySelectorAll('.ev-full, .dl-full').length") == 0
        assert pg.evaluate(
            "document.querySelectorAll('#schedule-grid svg.warn-sign, #schedule-summary svg.warn-sign,"
            " #schedule-unscheduled svg.warn-sign').length") == 0
    finally:
        ctx.close()


# --------------------------------------------------------------------------
# 4. פאנל הפרטים
# --------------------------------------------------------------------------
@pytest.mark.parametrize("status,signed", [(FULL, True), (REPEATERS, False)])
def test_details_status_row_has_the_sign_only_when_full(browser, server, status, signed):
    ctx, pg = _open(browser, server, by_code={BLOCK_CODE: status})
    try:
        pg.click(f'#schedule-grid .ev[data-code="{BLOCK_CODE}"] >> nth=0')
        pg.wait_for_timeout(400)
        got = pg.evaluate(
            """() => {
              const body = document.getElementById('meeting-detail-body');
              const dts = [...body.querySelectorAll('dt')];
              const dds = [...body.querySelectorAll('dd')];
              return {dts: dts.map(e => e.textContent), all: body.querySelectorAll('svg.warn-sign').length,
                      idx: dds.map((d, i) => i)};
            }"""
        )
        i = got["dts"].index(DETAIL["status"])
        mark = pg.evaluate(MARKS, "#meeting-detail-body dd")[i]
        if signed:
            _assert_sign(mark, FULL)
            _assert_geometry(mark)
            assert got["all"] == 1, got
        else:
            assert not mark["sign"] and mark["text"] == REPEATERS, mark
            assert got["all"] == 0, got
    finally:
        ctx.close()


# --------------------------------------------------------------------------
# 5. שורת "ללא מועד קבוע"
# --------------------------------------------------------------------------
@pytest.mark.parametrize("status,signed", [(FULL, True), (REPEATERS, False)])
def test_no_fixed_time_line_has_the_sign_only_when_full(browser, server, status, signed):
    ctx, pg = _open(browser, server, by_code={NO_TIME_CODE: status}, extra_codes=(NO_TIME_CODE,))
    try:
        line = pg.evaluate(MARKS, "#schedule-unscheduled")
        assert len(line) == 1 and line[0]["text"].startswith(GRID["unscheduled"].split("{")[0]), line
        marks = pg.evaluate(MARKS, "#schedule-unscheduled .unscheduled-full")
        if signed:
            assert len(marks) == 1, marks
            _assert_sign(marks[0], GRID["groupFull"])
            _assert_geometry(marks[0])
            assert (" · " + GRID["groupFull"]) in line[0]["text"], line
        else:
            assert marks == [] and line[0]["signs"] == 0, (marks, line)
            assert GRID["groupFull"] not in line[0]["text"], line
    finally:
        ctx.close()


# --------------------------------------------------------------------------
# 6. תמרור אינו מחליף צבע: בהיר, כהה, הדפסה
# --------------------------------------------------------------------------
COLOURS = """() => { const s = document.querySelector('.fit-full svg.warn-sign');
  const tri = getComputedStyle(s.querySelector('.warn-sign-tri'));
  const mark = getComputedStyle(s.querySelector('.warn-sign-mark'));
  return {fill: tri.fill, stroke: tri.stroke, mark: mark.fill,
          opacity: [getComputedStyle(s).opacity, tri.opacity, mark.opacity, tri.fillOpacity]}; }"""


def test_the_sign_has_the_same_colours_in_light_dark_and_print(browser, server):
    seen = {}
    for scheme in ("light", "dark"):
        ctx, pg = _open(browser, server, by_code={BLOCK_CODE: FULL}, scheme=scheme)
        try:
            seen[scheme] = pg.evaluate(COLOURS)
            pg.evaluate("() => document.documentElement.setAttribute('data-theme', 'dark')")
            seen[scheme + "/attr-dark"] = pg.evaluate(COLOURS)
            pg.emulate_media(media="print")
            pg.wait_for_timeout(200)
            seen[scheme + "/print"] = pg.evaluate(COLOURS)
        finally:
            ctx.close()
    first = seen["light"]
    assert first["fill"] != first["stroke"] == first["mark"], first
    assert all(o == "1" for o in first["opacity"]), first
    for key, value in seen.items():
        assert value == first, (key, value, first)


# --------------------------------------------------------------------------
# 7. הצבעים: מוגדרים פעם אחת, וניגודיות
# --------------------------------------------------------------------------
def _hex(token: str) -> str:
    hits = re.findall(rf"{re.escape(token)}:\s*(#[0-9a-fA-F]{{6}})\s*;", CSS)
    assert len(hits) == 1, (token, hits)
    return hits[0]


def _lum(hex_colour: str) -> float:
    def ch(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _ratio(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_sign_tokens_are_defined_once_and_meet_contrast():
    fill, ink = _hex("--warn-sign-fill"), _hex("--warn-sign-ink")
    # ‏לא ממופים בשום גוש: לא ‎--dark-warn-sign-*‎ ולא ‎--print-warn-sign-*‎.
    assert "--dark-warn-sign" not in CSS and "--print-warn-sign" not in CSS
    assert _ratio(ink, fill) >= 4.5, _ratio(ink, fill)          # ה-"!" על הצהוב
    assert _ratio(ink, _hex("--bg")) >= 3, _ratio(ink, _hex("--bg"))  # קו המתאר, בהיר
    # ‏בכהה קו המתאר כהה כמו הרקע (כ-1:1), ואת הקצה נושא הצהוב מול הרקע.
    assert _ratio(fill, _hex("--dark-bg")) >= 3, _ratio(fill, _hex("--dark-bg"))
