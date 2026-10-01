"""שלב 5 של העיצוב מחדש: דף התוצאה (docs/DESIGN.md, "Results page", 2026-09-30).

מה נבדק כאן
-----------
* **שלוש שורות בכל בלוק, ושום בלוק אינו גולש.** גובה השעה נגזר מהתוכן
  (``sizeGrid`` ב-app.js) ונמדד אחרי הפריסה. עד 2026-09-30 ``fitBlocks()``
  הוריד שורות ומדד לפני שהפריסה התייצבה, והבלוקים הגיעו עם שם מרצה חתוך
  לרוחבו (DEFERRED.md, "Grid blocks ship with lecturer names sliced in half").
* **הגובה בא מהתוכן, לא ממספר קבוע:** פיקסל אחד פחות, ובלוק גולש.
* **שבבי הנתונים בסדר של DESIGN,** והשורה "מה הוריד מההתאמה".
* **קורס בלי מועד קבוע** (61998, פרויקט מסכם שלב א') נאמר בשורה מתחת
  למקרא, ואינו שבב במקרא.

**אף בדיקה כאן אינה תלויה ב-data/db המקומי.** השרת של הבדיקות קורא את
‏``data/db`` האמיתי אם הוא קיים, ושתי בדיקות בקובץ הזה עברו בהתחלה רק בזכות
הנתונים שבו (DEFERRED.md). לכן כל ציפייה נגזרת ממה שהשרת החזיר בפועל, והקובץ
נבדק גם עם מאגר הבדיקות (seed_dev_data.py --fixture) וגם בלי data/db בכלל.
* **הדפסה:** הבחירה של סמסטר 5 נכנסת לעמוד A4 לאורך אחד, עם שלוש השורות
  בכל בלוק, וגופן הבלוקים יורד רק בהדפסה.

הבחירה: הנדסת תוכנה, שנה ג', סמסטר א' (סמסטר 5 בתוכנית), ששת הקורסים
המומלצים — אותה בחירה שבה נמדדו המספרים ב-DESIGN.md.
"""

from __future__ import annotations

import json
import math
import re
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
SCHED = STRINGS["app"]["schedule"]
GRID = STRINGS["app"]["grid"]

#: מפתח ה-localStorage של האפליקציה. **אין לשנותו** — ראו CLAUDE.md.
STORAGE_KEY = "braude_schedule_builder_v1"

#: ‏A4 לאורך, בפיקסלי CSS.
PAGE_W = round(210 * 96 / 25.4)
PAGE_H = round(297 * 96 / 25.4)

#: הסדר של DESIGN.md, "Results page", פריט 4.
PILL_ORDER = ["fit", "days", "finish", "gaps", "credits"]


def fill(template: str, **values) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


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


def _open_semester_5(browser, server, width=1440, height=1000):
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme="light")
    page = ctx.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    page.goto(server)
    page.wait_for_timeout(2500)
    page.select_option("#select-program", "הנדסת תוכנה")
    page.select_option("#select-year", "3")
    page.select_option("#select-term", "א")
    page.wait_for_timeout(2500)
    page.click("#btn-restore-recommended")
    page.wait_for_selector("#schedule-grid .ev", timeout=20000)
    _settle(page)
    return ctx, page


def _settle(page):
    """הגובה נקבע בפריים שאחרי הציור; מחכים שיהיה, ועוד רגע לגופנים."""
    page.wait_for_function(
        "() => !!document.getElementById('schedule-grid').style.getPropertyValue('--slot-h')",
        timeout=15000,
    )
    page.wait_for_timeout(600)


@pytest.fixture(scope="module")
def page(browser, server):
    """דף אחד ב-1440, לבדיקות שרק קוראות."""
    ctx, pg = _open_semester_5(browser, server)
    try:
        yield pg
    finally:
        ctx.close()


#: כל בלוק: גולש? כמה שורות? האם שורה יוצאת מתיבת התוכן, לגובה או לרוחב?
BLOCKS = """() => [...document.querySelectorAll('#schedule-grid .ev')].map(e => {
  const cs = getComputedStyle(e);
  const box = e.getBoundingClientRect();
  const top = box.top + parseFloat(cs.borderTopWidth) + parseFloat(cs.paddingTop);
  const bottom = box.bottom - parseFloat(cs.borderBottomWidth) - parseFloat(cs.paddingBottom);
  const lines = [...e.querySelectorAll(':scope > .ev-line')].map(l => {
    const r = l.getBoundingClientRect();
    return {cls: l.className, text: l.textContent.trim(),
            shown: getComputedStyle(l).display !== 'none' && !l.hidden && r.height > 0,
            inside: r.top >= top - 0.5 && r.bottom <= bottom + 0.5,
            wide: l.scrollWidth > l.clientWidth + 1};
  });
  return {name: (e.querySelector('b') || {}).textContent || '',
          overflow: e.scrollHeight - e.clientHeight,
          hiddenParts: e.querySelectorAll('[hidden]').length,
          lines: lines,
          font: parseFloat(cs.fontSize)};
})"""


def _assert_three_full_lines(blocks, where):
    assert blocks, f"אין בלוקים ({where})"
    bad = []
    for b in blocks:
        if b["overflow"] > 0:
            bad.append(f"{b['name']}: גולש ב-{b['overflow']}px")
        if b["hiddenParts"]:
            bad.append(f"{b['name']}: {b['hiddenParts']} חלקים מוסתרים")
        # כל מפגש בבחירה הזו יש לו מרצה או חדר, ולכן שלוש שורות.
        if len(b["lines"]) != 3:
            bad.append(f"{b['name']}: {len(b['lines'])} שורות")
        for line in b["lines"]:
            if not (line["shown"] and line["inside"] and not line["wide"] and line["text"]):
                bad.append(f"{b['name']}: {line['cls']} {line}")
    assert not bad, f"{where}: " + " | ".join(bad)


# ==========================================================================
# 1. הבלוקים: שלוש שורות, שום גלישה
# ==========================================================================
def test_every_block_shows_three_full_lines_at_1440(page):
    _assert_three_full_lines(page.evaluate(BLOCKS), "1440")


def test_the_three_lines_are_name_kind_time_and_lecturer_room(page):
    """‏(1) שם הקורס, (2) סוג · שעה, (3) מרצה · חדר."""
    rows = page.evaluate(
        """() => [...document.querySelectorAll('#schedule-grid .ev')].map(e => {
          const ls = [...e.querySelectorAll(':scope > .ev-line')];
          return {classes: ls.map(l => l.className),
                  when: ls[1] ? [!!ls[1].querySelector('.ev-kind'), !!ls[1].querySelector('.cell-time')] : [],
                  who: ls[2] ? [!!ls[2].querySelector('.ev-lect'), !!ls[2].querySelector('.ev-room')] : [],
                  timeText: (e.querySelector('.cell-time') || {}).textContent || ''};
        })"""
    )
    for r in rows:
        assert r["classes"] == ["ev-line ev-name", "ev-line ev-when", "ev-line ev-who"], r
        assert r["when"] == [True, True], r
        assert any(r["who"]), r
        assert re.fullmatch(r"\d\d:\d\d–\d\d:\d\d", r["timeText"]), r


@pytest.mark.parametrize("width", [1440, 1200])
def test_no_block_overflows(browser, server, width):
    ctx, pg = _open_semester_5(browser, server, width=width)
    try:
        blocks = pg.evaluate(BLOCKS)
        over = [(b["name"], b["overflow"]) for b in blocks if b["overflow"] > 0]
        assert blocks and not over, f"בלוקים גולשים ב-{width}px: {over}"
        _assert_three_full_lines(blocks, f"{width}px")
    finally:
        ctx.close()


def test_the_hour_height_comes_from_the_content(page):
    """פיקסל אחד פחות למשבצת, ולפחות בלוק אחד גולש. כלומר הגובה הוא הקטן
    ביותר שמכיל את התוכן — ולא מספר קבוע שבמקרה גדול מספיק."""
    got = page.evaluate(
        """() => {
          const g = document.getElementById('schedule-grid');
          const slot = parseFloat(g.style.getPropertyValue('--slot-h'));
          const evs = [...g.querySelectorAll('.ev')];
          const over = () => evs.filter(e => e.scrollHeight > e.clientHeight).length;
          const atSlot = over();
          g.style.setProperty('--slot-h', (slot - 1) + 'px');
          const below = over();
          g.style.setProperty('--slot-h', slot + 'px');
          return {slot, atSlot, below};
        }"""
    )
    assert got["atSlot"] == 0, got
    assert got["below"] > 0 or got["slot"] <= 12, (
        f"גם ב-{got['slot'] - 1}px שום בלוק אינו גולש — הגובה אינו נגזר מהתוכן: {got}"
    )


def test_screen_blocks_keep_the_13px_floor(page):
    fonts = page.evaluate(
        """() => [...new Set([...document.querySelectorAll('#schedule-grid .ev, #schedule-grid .ev *')]
                   .map(e => getComputedStyle(e).fontSize))]"""
    )
    assert fonts and all(float(f.replace("px", "")) >= 13 for f in fonts), fonts


def test_a_narrow_window_refits_without_dropping(browser, server):
    """שינוי רוחב אחרי הציור: ‏ResizeObserver מודד מחדש."""
    ctx, pg = _open_semester_5(browser, server, width=1440)
    try:
        before = pg.evaluate("parseFloat(document.getElementById('schedule-grid').style.getPropertyValue('--slot-h'))")
        pg.set_viewport_size({"width": 900, "height": 1000})
        pg.wait_for_timeout(800)
        after = pg.evaluate("parseFloat(document.getElementById('schedule-grid').style.getPropertyValue('--slot-h'))")
        _assert_three_full_lines(pg.evaluate(BLOCKS), "900px אחרי שינוי רוחב")
        assert after >= before, (before, after)
    finally:
        ctx.close()


def test_room_codes_do_not_break_mid_code_at_phone_width(browser, server):
    """‏"L 706" בשורה אחת גם בעמודה צרה; רק מה שאחרי הקוד רשאי להישבר."""
    ctx, pg = _open_semester_5(browser, server, width=390, height=900)
    try:
        split = pg.evaluate(
            """() => [...document.querySelectorAll('#schedule-grid .ev .code--id')]
                 .filter(c => c.getClientRects().length > 1).map(c => c.textContent)"""
        )
        count = pg.evaluate("document.querySelectorAll('#schedule-grid .ev .code--id').length")
        assert count > 0
        assert split == [], f"קודי חדר שנשברו באמצע: {split}"
        _assert_three_full_lines(pg.evaluate(BLOCKS), "390px")
    finally:
        ctx.close()


# ==========================================================================
# 2. שבבי הנתונים, ומה הוריד מההתאמה
# ==========================================================================
def test_stat_pills_are_in_design_order(page):
    order = page.evaluate(
        "[...document.querySelectorAll('#schedule-summary .stat-pill')].map(p => p.dataset.stat)"
    )
    # בלי העדפות מרצים אין שבב שישי.
    assert order == PILL_ORDER, order


def _expected_fits(scores):
    """אותו חישוב כמו fitScores() ב-app.js: ביחס לטובה מבין המוצגות."""
    best = max(scores)
    scale = max(abs(best), 1)
    # ‏Math.round של JS מעגל ‎.5‎ למעלה; round של פייתון — לזוגי.
    return [min(100, max(0, math.floor(100 * (1 - (best - v) / scale) + 0.5))) for v in scores]


def test_the_top_schedule_carries_the_label_and_the_facts(page):
    """הציפייה נגזרת מהניקוד שהשרת החזיר, ולא מהנחה על הנתונים: עם הקטלוג
    הקפוא כל חמש המערכות שקולות, ואז אין "מובילה" — השבב אומר "התאמה 100%"."""
    pills = page.evaluate(
        """() => Object.fromEntries([...document.querySelectorAll('#schedule-summary .stat-pill')]
              .map(p => [p.dataset.stat, p.textContent.trim()]))"""
    )
    fit = page.evaluate(
        """() => { const p = document.querySelector('#schedule-summary .stat-pill.fit');
                   const label = p.querySelector('.fit-label');
                   const value = p.querySelector('.fit-value');
                   return {label: label ? label.textContent : null,
                           value: value.textContent,
                           best: value.classList.contains('fit-value--best')}; }"""
    )
    runtime = page.evaluate(
        """() => ({scores: window.slotwise.getRuntime().solve.schedules.map(s => s.score),
                   active: window.slotwise.getState().activeSchedule})"""
    )
    fits = _expected_fits(runtime["scores"])
    tied = len(fits) > 1 and len(set(fits)) == 1
    mine = fits[runtime["active"]]
    if not tied and mine == max(fits):
        assert fit == {"label": None, "value": STRINGS["app"]["compare"]["bestOverall"],
                       "best": True}, (fit, fits)
    else:
        assert fit == {"label": SCHED["fitLabel"], "value": fill(SCHED["fitValue"], score=mine),
                       "best": False}, (fit, fits)
    sch = page.evaluate(
        "window.slotwise.getRuntime().solve.schedules[window.slotwise.getState().activeSchedule]"
    )
    days = sch["days_count"]
    assert pills["days"].startswith(f"{days} ") and "(" in pills["days"], pills
    if round(sch["gap_minutes"]) == 0:
        assert pills["gaps"] == SCHED["pillNoGaps"], pills
    else:
        assert pills["gaps"].startswith(SCHED["pillGaps"].split("{")[0]), pills
    assert 'נ"ז' in pills["credits"], pills


def test_what_lowered_the_fit_is_one_line_in_order(page):
    sch = page.evaluate("window.slotwise.getRuntime().solve.schedules[0]")
    negative = sorted(
        ((k, v) for k, v in sch["breakdown"].items() if v < 0 and round(v, 1) != 0),
        key=lambda kv: kv[1],
    )
    line = page.evaluate(
        """() => { const p = document.querySelector('#schedule-summary .fit-lost');
                   return p ? {text: p.textContent,
                               keys: [...p.querySelectorAll('.fit-lost-item')].map(i => i.dataset.penalty)}
                            : null; }"""
    )
    if not negative:
        assert line is None, line
        return
    assert line, "אין שורת 'מה הוריד מההתאמה' למרות שיש קנסות"
    assert line["text"].startswith(SCHED["penaltiesLine"].split("{")[0]), line
    assert line["keys"][: len(negative)] == [k for k, _ in negative], (line, negative)
    # הפאנל הישן — פסים, אריחים וכותרת — אינו קיים עוד.
    old = page.evaluate(
        "document.querySelectorAll('.penalty, .penalties, .facts--plain, .panel-block, .fit-headline').length"
    )
    assert old == 0


def test_the_lecturer_count_is_a_visible_pill_when_preferences_exist(browser, server):
    """\u200f"N מתוך N מרצים מועדפים" גלוי תמיד כשיש העדפות — לא רק בתווית הצפה,
    שאינה קיימת בטלפון."""
    ctx, pg = _open_semester_5(browser, server)
    try:
        lecturer = pg.evaluate(
            """() => (window.slotwise.getRuntime().solve.schedules[0].picks
                       .find(p => p.code === '61759') || {}).lecturer"""
        )
        assert lecturer
        pg.evaluate(
            """(args) => { const s = JSON.parse(localStorage.getItem(args.key) || '{}');
                           s.ranked = {'61759': [args.name]};
                           localStorage.setItem(args.key, JSON.stringify(s)); }""",
            {"key": STORAGE_KEY, "name": lecturer},
        )
        pg.reload()
        pg.wait_for_selector("#schedule-grid .ev", timeout=20000)
        _settle(pg)
        order = pg.evaluate(
            "[...document.querySelectorAll('#schedule-summary .stat-pill')].map(p => p.dataset.stat)"
        )
        assert order == PILL_ORDER + ["lecturers"], order
        sch = pg.evaluate("window.slotwise.getRuntime().solve.schedules[window.slotwise.getState().activeSchedule]")
        want = fill(SCHED["lecturersHits"], hits=sch["lecturer_hits"], total=sch["lecturer_total"])
        got = pg.evaluate(
            "document.querySelector('#schedule-summary [data-stat=\"lecturers\"]').textContent.trim()"
        )
        assert got == want, (got, want)
    finally:
        ctx.close()


# ==========================================================================
# 3. שורת ההגדרות, המקרא וקורס בלי מועד
# ==========================================================================
def test_settings_pills_repeat_the_step_summaries(page):
    got = page.evaluate(
        """() => ({
          pills: [...document.querySelectorAll('#settings-pills .settings-pill')]
                   .map(p => [p.dataset.step, p.textContent.trim()]),
          edit: (document.querySelector('#settings-pills .settings-edit') || {}).textContent,
          hidden: document.getElementById('settings-pills').hidden,
          states: Object.fromEntries(['year', 'courses', 'days', 'lecturers']
                   .map(k => [k, document.getElementById('step-' + k + '-state').textContent.trim()])),
        })"""
    )
    assert not got["hidden"]
    assert [k for k, _ in got["pills"]] == ["year", "courses", "days", "lecturers"], got
    texts = dict(got["pills"])
    for key in ("courses", "days", "lecturers"):
        assert texts[key] == got["states"][key], (key, texts[key], got["states"][key])
    # שבב שלב 1 מוסיף את המסלול לפני אותו סיכום.
    assert texts["year"] == fill(SCHED["settingsProgram"], program="הנדסת תוכנה", summary=got["states"]["year"])
    assert got["edit"] == SCHED["settingsEdit"]
    assert "null" not in " ".join(texts.values())


def test_the_edit_link_returns_to_the_first_step(browser, server):
    ctx, pg = _open_semester_5(browser, server)
    try:
        pg.click("#settings-pills .settings-edit")
        pg.wait_for_timeout(500)
        got = pg.evaluate(
            """() => ({top: document.getElementById('step-year').getBoundingClientRect().top,
                       focus: document.activeElement && document.activeElement.id})"""
        )
        assert abs(got["top"]) < 120, got
        assert got["focus"] == "step-year-toggle", got
    finally:
        ctx.close()


#: פרויקט מסכם שלב א' בהנדסת תוכנה: בסמסטר א' יש לו קבוצה אחת, בלי אף מפגש —
#: בקטלוג הקפוא של הבדיקות ובקטלוג שבמאגר כאחד. לכן הוא נשאר בלי מועד קבוע
#: **בכל** בחירה של הפותר, ולא רק כשהפותר בוחר קבוצה מסוימת. ‏11069, שהיה
#: הדוגמה הראשונה, אינו כזה: בקטלוג הקפוא לכל קבוצות סמסטר א' שלו יש מפגש.
NO_TIME_CODE = "61998"

#: הקורסים שאין להם אף מפגש במערכת הפעילה, בסדר ה-picks — אותו כלל כמו
#: unscheduledCourses() ב-app.js — וכל מה שצריך כדי לבנות את השורה.
UNSCHEDULED = """() => {
  const rt = window.slotwise.getRuntime();
  const sch = rt.solve.schedules[window.slotwise.getState().activeSchedule];
  const by = {}, order = [];
  sch.picks.forEach(p => {
    if (!by[p.code]) { by[p.code] = {code: p.code, name: p.name, kinds: [], credits: null, timed: false};
                       order.push(p.code); }
    const r = by[p.code];
    if ((p.meetings || []).length) r.timed = true;
    if (p.kind && r.kinds.indexOf(p.kind) === -1) r.kinds.push(p.kind);
    if (r.credits === null && p.credits !== null && p.credits !== undefined && p.credits !== ''
        && Number(p.credits) >= 0) r.credits = Number(p.credits);
  });
  const line = document.getElementById('schedule-unscheduled');
  return {list: order.map(c => by[c]).filter(r => !r.timed),
          hidden: line.hidden, text: line.textContent.trim(),
          chips: [...document.querySelectorAll('#schedule-legend .legend-chip')]
                   .map(c => c.dataset.code).filter(Boolean),
          // ‏מול המקרא עצמו, לא מול ‎.grid-tools‎: מאז שלב 6 השורה יושבת בתוכו,
          // וצאצא תמיד "אחרי" ההורה שלו — הבדיקה הייתה עוברת תמיד.
          afterLegend: !!(document.getElementById('schedule-legend').compareDocumentPosition(line)
                          & Node.DOCUMENT_POSITION_FOLLOWING)};
}"""


def _fmt_number(value):
    """‏fmtNumber() של app.js: ‏19 ולא 19.0, ו-2.5 נשאר 2.5."""
    rounded = math.floor(value * 10 + 0.5) / 10
    return str(int(rounded)) if float(rounded).is_integer() else str(rounded)


def _unscheduled_line(items):
    parts = []
    for r in items:
        kind = ", ".join(r["kinds"])
        if r["credits"] is None:
            parts.append(fill(GRID["unscheduledItemNoCredits"], name=r["name"], kind=kind))
        else:
            credits = fill(STRINGS["app"]["credits"]["withUnit"], value=_fmt_number(r["credits"]))
            parts.append(fill(GRID["unscheduledItem"], name=r["name"], kind=kind, credits=credits))
    return fill(GRID["unscheduled"], list=", ".join(parts))


def test_a_course_with_no_fixed_time_gets_its_own_line(browser, server):
    """קורס בלי מועד קבוע אין לו בלוק, ולכן גם לא שבב במקרא — הוא נאמר בשורה
    אחת מתחת למקרא: "ללא מועד קבוע: <שם> (<סוג>, N נ"ז)"."""
    ctx, pg = _open_semester_5(browser, server)
    try:
        pg.evaluate(
            """(args) => { const s = JSON.parse(localStorage.getItem(args.key) || '{}');
                           s.codes = (s.codes || []).concat([args.code]);
                           localStorage.setItem(args.key, JSON.stringify(s)); }""",
            {"key": STORAGE_KEY, "code": NO_TIME_CODE},
        )
        pg.reload()
        pg.wait_for_selector("#schedule-grid .ev", timeout=20000)
        _settle(pg)
        got = pg.evaluate(UNSCHEDULED)
        codes = [r["code"] for r in got["list"]]
        assert NO_TIME_CODE in codes, f"{NO_TIME_CODE} אמור להיות בלי מועד קבוע: {got['list']}"
        assert not got["hidden"], "השורה מוסתרת למרות שיש קורס בלי מועד קבוע"
        assert got["text"] == _unscheduled_line(got["list"]), got
        assert not set(codes) & set(got["chips"]), (codes, got["chips"])
        assert got["afterLegend"], "השורה אמורה לשבת מתחת למקרא"
    finally:
        ctx.close()


def test_the_no_fixed_time_line_matches_the_schedule(page):
    """בלי קורס כזה השורה מוסתרת; עם קורס כזה — היא בדיוק שלו. נגזר מהמערכת
    שהשרת החזיר, כך שהבדיקה אינה תלויה בקטלוג או במאגר המקומי."""
    got = page.evaluate(UNSCHEDULED)
    if not got["list"]:
        assert got["hidden"] and got["text"] == "", got
    else:
        assert not got["hidden"] and got["text"] == _unscheduled_line(got["list"]), got


def test_the_legend_sits_under_the_grid_and_names_credits(page):
    got = page.evaluate(
        """() => {
          const grid = document.getElementById('grid-scroll');
          const legend = document.getElementById('schedule-legend');
          return {below: !!(grid.compareDocumentPosition(legend) & Node.DOCUMENT_POSITION_FOLLOWING),
                  chips: [...legend.querySelectorAll('.legend-chip[data-code]')].map(c => c.textContent)};
        }"""
    )
    assert got["below"], "המקרא אמור לשבת מתחת לרשת"
    assert got["chips"] and all('נ"ז' in c for c in got["chips"]), got["chips"]


# ==========================================================================
# 4. הדפסה — A4 לאורך, עמוד אחד
# ==========================================================================
def test_semester_5_prints_on_one_portrait_page_with_three_lines_in_every_block(
    browser, server, tmp_path
):
    ctx, pg = _open_semester_5(browser, server, width=PAGE_W, height=PAGE_H)
    try:
        pg.emulate_media(media="print")
        pg.wait_for_timeout(1000)
        body = pg.evaluate("Math.round(document.body.scrollHeight)")
        assert body <= PAGE_H, f"הדף המודפס גולש: {body}px מול עמוד {PAGE_H}px"
        blocks = pg.evaluate(BLOCKS)
        _assert_three_full_lines(blocks, "הדפסה לאורך")
        # הגופן יורד רק בהדפסה, ולא מתחת ל-10px.
        fonts = {b["font"] for b in blocks}
        assert len(fonts) == 1 and 10 <= fonts.pop() <= 13, fonts
        split = pg.evaluate(
            """() => [...document.querySelectorAll('#schedule-grid .ev .code--id')]
                 .filter(c => c.getClientRects().length > 1).map(c => c.textContent)"""
        )
        assert split == [], f"קודי חדר שנשברו באמצע בהדפסה: {split}"
        # והעמוד האמיתי: PDF, ולא רק מדידה.
        pdf = tmp_path / "print.pdf"
        pg.pdf(path=str(pdf), prefer_css_page_size=True, print_background=True)
        pages = len(re.findall(rb"/Type\s*/Page(?!s)", pdf.read_bytes()))
        assert pages == 1, f"ה-PDF יצא {pages} עמודים"
        assert pg.errors == [], pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_leaving_print_restores_the_screen_font(browser, server):
    ctx, pg = _open_semester_5(browser, server, width=PAGE_W, height=PAGE_H)
    try:
        pg.emulate_media(media="print")
        pg.wait_for_timeout(800)
        pg.emulate_media(media="screen")
        pg.wait_for_timeout(800)
        got = pg.evaluate(
            """() => ({var: document.getElementById('schedule-grid').style.getPropertyValue('--ev-font-print'),
                       font: getComputedStyle(document.querySelector('#schedule-grid .ev')).fontSize})"""
        )
        assert got == {"var": "", "font": "13px"}, got
    finally:
        ctx.close()
