"""שלב 9 של העיצוב מחדש, חלק א׳: המערכת שבדף כרשימה לפי ימים מתחת ל-1000px
(docs/DESIGN.md, "Results page", פריט 5, "Below 1000px: a list by day";
הוחלט 2026-10-08, קו ה-1000px — 2026-10-10).

מה נבדק כאן
-----------
* **מתחת ל-1000px** (390x844, ‏360x800, ‏999): הרשימה מוצגת והרשת לא. כל שיעור
  של החלופה שנבחרה מופיע פעם אחת, בשלוש שורות — שעות, שם הקורס, סוג · חדר
  (‏roomOf, כמו ברשת) — בצבע הקורס (אותו מילוי ואותו פס כמו שבב המקרא שלו).
  שורות החלון נכונות ומסתכמות ב-``gap_minutes`` של השרת. יום ריק הוא שורה
  אחת, ויום ו׳ ריק אינו מופיע. הקשה פותחת את פרטי השיעור. החלפת חלופה מחליפה
  את הרשימה, בלי תנועה ובלי נחיתה. אין גלילה אופקית של העמוד.
* **מבנה:** כותרת לכל יום, השיעורים ברשימה, וכל שיעור כפתור ששמו הנגיש כולל
  יום, שעות, קורס, סוג וחדר.
* **חפיפה** (מערכת מעובדת): שני השיעורים מסומנים, בסדר ההתחלה, והפרטים מראים
  את שניהם עם ההערה מתחת לכל שיעור שהמתג שלו כבוי.
* **מ-1000px ומעלה** (1000, ‏1440): הרשת מוצגת והרשימה לא. ב-1000 כל בלוק בשלוש
  שורות שלמות, בלי גלילה אופקית בתוך התיבה.
* **קודי חדר** ברשימה ב-360 אינם נשברים באמצע ("L 706" בשורה אחת).
* **הדפסה מ-390:** הרשת, כל הבלוקים ושלוש שורות בכל אחד; הרשימה אינה על הנייר.

מאגר הבדיקות (scripts/seed_dev_data.py --fixture), הנדסת תוכנה שנה 3 סמסטר א,
הקורסים המומלצים.
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

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import create_app  # noqa: E402

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
DL = STRINGS["app"]["dayList"]
DAY_NAMES = STRINGS["app"]["terms"]["dayNames"]
GROUP_FULL = STRINGS["app"]["grid"]["groupFull"]

PHONE = (390, 844)
SMALL_PHONE = (360, 800)
LIST_SIZES = [PHONE, SMALL_PHONE]
FRIDAY = 6

#: מונה קריאות ל-Element.animate, לפני שהעמוד נטען.
ANIMATE_HOOK = """(() => {
  window.__anims = [];
  const orig = Element.prototype.animate;
  Element.prototype.animate = function (frames, opts) {
    window.__anims.push({cls: String(this.className || ''), id: '', t: performance.now()});
    return orig.apply(this, arguments);
  };
})()"""


def fill(template: str, **kw) -> str:
    for k, v in kw.items():
        template = template.replace("{" + k + "}", str(v))
    return template


def minutes(value) -> int:
    if isinstance(value, str) and ":" in value:
        h, m = value.split(":")[:2]
        return int(h) * 60 + int(m)
    return int(round(float(value)))


def hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def gap_text(total: int) -> str:
    h, m = divmod(total, 60)
    if not h:
        key = "half" if m == 30 else "minutes"
    elif h == 1:
        key = "hour" if not m else "hourHalf" if m == 30 else "hourMinutes"
    else:
        key = "hours" if not m else "hoursHalf" if m == 30 else "hoursMinutes"
    return fill(DL["gap"][key], h=h, m=m)


# ==========================================================================
# שרת, דפדפן ודף
# ==========================================================================
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


def _open(browser, server, size, craft=None, hook=False):
    """הדף, ותשובת ‎/api/solve‎ האחרונה כפי שהדף קיבל אותה (‏pg.solve)."""
    ctx = browser.new_context(
        viewport={"width": size[0], "height": size[1]}, color_scheme="light"
    )
    pg = ctx.new_page()
    pg.errors = []  # type: ignore[attr-defined]
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))  # type: ignore[attr-defined]
    if hook:
        pg.add_init_script(ANIMATE_HOOK)

    def handler(route):
        response = route.fetch()
        data = response.json()
        schedules = data.get("schedules") or []
        if craft and schedules:
            craft(schedules)
        pg.solve = data  # type: ignore[attr-defined]
        route.fulfill(
            status=response.status,
            headers={"content-type": "application/json"},
            body=json.dumps(data, ensure_ascii=False),
        )

    pg.route("**/api/solve", handler)
    pg.goto(server)
    pg.wait_for_timeout(2500)
    pg.select_option("#select-program", "הנדסת תוכנה")
    pg.select_option("#select-year", "3")
    pg.select_option("#select-term", "א")
    pg.wait_for_timeout(2500)
    pg.click("#step-year-next")
    pg.click("#btn-restore-recommended")
    pg.wait_for_selector("#alt-cards .alt-card", timeout=20000)
    pg.wait_for_timeout(1500)
    return ctx, pg


def _active(pg):
    idx = pg.evaluate("window.slotwise.getState().activeSchedule")
    return idx, pg.solve["schedules"][idx]  # type: ignore[attr-defined]


def _meetings(pg, sch):
    """כל מפגש של המערכת, עם החדר כפי שהוא מוצג (‏formatRoom של הדף)."""
    out = []
    for p in sch.get("picks") or []:
        for m in p.get("meetings") or []:
            raw = " ".join(x for x in (str(m.get("building") or ""), str(m.get("room") or "")) if x)
            out.append({
                "code": str(p.get("code")),
                "name": p.get("name") or "",
                "kind": p.get("kind") or "",
                "group": str(p.get("group_id") or ""),
                "full": (p.get("status_note") or "") == "הקורס מלא",
                "day": int(m["day"]),
                "start": minutes(m["start"]),
                "end": minutes(m["end"]),
                "room": pg.evaluate("r => window.slotwise.formatRoom(r)", raw),
            })
    return out


def _expected_days(meets):
    """הימים כפי שהרשימה צריכה להראות אותם: יום ו׳ ריק אינו מופיע, ובכל יום
    השיעורים לפי ההתחלה, עם החלון שלפני כל שיעור (‏gap_intervals של המודל)."""
    days = []
    for d in range(1, 7):
        today = sorted((m for m in meets if m["day"] == d), key=lambda m: (m["start"], m["end"]))
        if not today and d == FRIDAY:
            continue
        rows, cursor = [], None
        for m in today:
            gap = m["start"] - cursor if cursor is not None and m["start"] > cursor else 0
            cursor = m["end"] if cursor is None else max(cursor, m["end"])
            rows.append((m, gap))
        days.append((d, rows))
    return days


LIST = """() => {
  const list = document.getElementById('schedule-days');
  return [...list.querySelectorAll(':scope > .dl-day')].map(sec => {
    const h = sec.querySelector(':scope > h4');
    const ul = sec.querySelector(':scope > ul');
    return {day: +sec.dataset.day, heading: h ? h.textContent.trim() : null, empty: sec.classList.contains('is-empty'),
      items: ul ? [...ul.querySelectorAll(':scope > li')].map(li => {
        const b = li.querySelector(':scope > button.dl-lesson');
        const lines = [...b.querySelectorAll(':scope > .dl-line')];
        const cs = getComputedStyle(b);
        const chip = document.querySelector(`#schedule-legend .legend-chip[data-code="${b.dataset.code}"]`);
        const ccs = chip ? getComputedStyle(chip) : null;
        const gap = li.querySelector(':scope > .dl-gap');
        return {gap: gap ? gap.textContent.trim() : '', code: b.dataset.code, label: b.getAttribute('aria-label'),
                lines: lines.map(l => l.className.replace('dl-line', '').trim()),
                hours: b.querySelector('.dl-hours .cell-time').textContent.trim(),
                name: lines[1] ? lines[1].textContent.trim() : '',
                where: lines[2] ? lines[2].textContent.trim() : '',
                soft: b.classList.contains('is-soft'), badge: !!b.querySelector('.ev-badge'),
                bg: cs.backgroundColor, bar: cs.borderRightColor, barW: cs.borderRightWidth,
                chipBg: ccs && ccs.backgroundColor, chipBd: ccs && ccs.borderTopColor,
                fit: lines.every(l => l.scrollWidth <= l.clientWidth + 1) && b.scrollHeight <= b.clientHeight};
      }) : []};
  });
}"""

SHOWN = """() => ({
  grid: getComputedStyle(document.getElementById('grid-scroll')).display !== 'none'
        && document.getElementById('grid-scroll').getBoundingClientRect().height > 0,
  list: getComputedStyle(document.getElementById('schedule-days')).display !== 'none'
        && document.getElementById('schedule-days').getBoundingClientRect().height > 0,
  page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
})"""


def _check_list(pg, sch):
    """הרשימה שבדף מול המערכת שהשרת החזיר."""
    meets = _meetings(pg, sch)
    want = _expected_days(meets)
    got = pg.evaluate(LIST)
    assert [g["day"] for g in got] == [d for d, _ in want], (got, want)
    total_gap = 0
    count = 0
    for (d, rows), g in zip(want, got):
        if not rows:
            assert g["empty"] and not g["items"], g
            assert g["heading"] == fill(DL["emptyDay"], day=DAY_NAMES[str(d)]), g
            continue
        assert g["heading"] == DAY_NAMES[str(d)] and not g["empty"], g
        assert len(g["items"]) == len(rows), (d, g["items"], rows)
        for (m, gap), item in zip(rows, g["items"]):
            count += 1
            total_gap += gap
            assert item["lines"] == ["dl-hours", "dl-name", "dl-where"], item
            assert item["hours"] == f"{hhmm(m['start'])}–{hhmm(m['end'])}", (item, m)
            assert item["name"] == m["name"], (item, m)
            where = " · ".join(x for x in (m["kind"], m["room"], GROUP_FULL if m["full"] else "") if x)
            assert item["where"] == where, (item, m)
            assert item["gap"] == (gap_text(gap) if gap else ""), (d, item, gap)
            assert item["fit"], f"שורה גולשת: {item}"
            # ‏צבע הקורס: אותו מילוי ואותו פס כמו שבב המקרא שלו (‎--course-N‎).
            assert item["chipBg"] and item["bg"] == item["chipBg"], item
            assert item["bar"] == item["chipBd"] and item["barW"] == "4px", item
            for part in (DAY_NAMES[str(d)], hhmm(m["start"]), hhmm(m["end"]), m["name"], m["kind"], m["room"]):
                assert part in item["label"], (part, item["label"])
    # ‏כל שיעור פעם אחת, ושורות החלון מסתכמות במה שהשרת סופר.
    assert count == len(meets)
    assert total_gap == int(sch.get("gap_minutes", 0)), (total_gap, sch.get("gap_minutes"))
    return got


# ==========================================================================
# 1. מתחת ל-1000px: הרשימה
# ==========================================================================
@pytest.mark.parametrize("size", LIST_SIZES, ids=lambda s: f"{s[0]}x{s[1]}")
def test_the_list_replaces_the_grid_and_matches_the_schedule(browser, server, size):
    ctx, pg = _open(browser, server, size)
    try:
        shown = pg.evaluate(SHOWN)
        assert shown["list"] and not shown["grid"], shown
        assert shown["page"] <= 0, f"העמוד נגלל לרוחב: {shown}"
        _, sch = _active(pg)
        got = _check_list(pg, sch)
        # ‏בחלופה הזו יום ו׳ ריק — ואינו ברשימה; ויש לפחות חלון אחד.
        assert FRIDAY not in [g["day"] for g in got]
        assert any(i["gap"] for g in got for i in g["items"]), "אין שורת חלון — הבדיקה לא בדקה חלונות"
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_room_codes_do_not_break_mid_code_in_the_list(browser, server):
    """‏"L 706" בשורה אחת גם ברשימה ב-360; רק מה שאחרי הקוד רשאי להישבר."""
    ctx, pg = _open(browser, server, SMALL_PHONE)
    try:
        got = pg.evaluate(
            """() => { const codes = [...document.querySelectorAll('#schedule-days .dl-lesson .code--id')];
                       return {count: codes.length,
                               split: codes.filter(c => c.getClientRects().length > 1).map(c => c.textContent)}; }"""
        )
    finally:
        ctx.close()
    assert got["count"] > 0, got
    assert got["split"] == [], f"קודי חדר שנשברו באמצע: {got['split']}"


def test_the_list_is_also_shown_just_below_1000(browser, server):
    ctx, pg = _open(browser, server, (999, 900))
    try:
        shown = pg.evaluate(SHOWN)
        assert shown["list"] and not shown["grid"], shown
    finally:
        ctx.close()


def test_semantics_headings_lists_and_named_buttons(browser, server):
    ctx, pg = _open(browser, server, PHONE)
    try:
        got = pg.evaluate(
            """() => [...document.querySelectorAll('#schedule-days > .dl-day')].map(sec => ({
                 head: sec.firstElementChild.tagName,
                 list: sec.querySelector(':scope > ul') ? sec.querySelector(':scope > ul').tagName : null,
                 items: [...sec.querySelectorAll('li')].map(li => [...li.children].map(c => c.tagName).join(',')),
                 buttons: [...sec.querySelectorAll('.dl-lesson')].every(b => b.tagName === 'BUTTON'
                            && b.type === 'button' && (b.getAttribute('aria-label') || '').length > 0)}))"""
        )
        assert got
        for sec in got:
            assert sec["head"] == "H4", sec
            if sec["list"]:
                assert sec["list"] == "UL" and sec["buttons"], sec
                assert all(i in ("BUTTON", "P,BUTTON") for i in sec["items"]), sec
        # ‏השם הנגיש נמצא דרך התפקיד: כפתור לכל שיעור.
        _, sch = _active(pg)
        m = sorted(_meetings(pg, sch), key=lambda m: (m["day"], m["start"]))[0]
        name = re.compile(re.escape(DAY_NAMES[str(m["day"])]) + ".*" + re.escape(m["name"]))
        assert pg.get_by_role("button", name=name).count() >= 1
    finally:
        ctx.close()


def test_tapping_a_lesson_opens_its_details(browser, server):
    ctx, pg = _open(browser, server, PHONE)
    try:
        _, sch = _active(pg)
        meets = _meetings(pg, sch)
        button = pg.locator("#schedule-days .dl-lesson").nth(2)
        code = button.get_attribute("data-code")
        button.scroll_into_view_if_needed()
        button.click()
        pg.wait_for_timeout(400)
        got = pg.evaluate(
            """() => { const d = document.getElementById('meeting-detail');
                       const b = document.querySelectorAll('#schedule-days .dl-lesson')[2];
                       return {open: !d.hidden && getComputedStyle(d).display !== 'none',
                               text: document.getElementById('meeting-detail-body').textContent,
                               current: b.getAttribute('aria-current'), selected: b.classList.contains('is-selected')}; }"""
        )
        mine = [m for m in meets if m["code"] == code]
        assert got["open"], got
        assert mine and mine[0]["name"] in got["text"] and mine[0]["group"] in got["text"], (got, mine)
        assert got["current"] == "true" and got["selected"], got
        pg.click("#btn-detail-close")
        pg.wait_for_timeout(200)
        assert pg.evaluate("document.getElementById('meeting-detail').hidden")
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_switching_alternatives_replaces_the_list_without_motion(browser, server):
    ctx, pg = _open(browser, server, PHONE, hook=True)
    try:
        first_idx, first = _active(pg)
        before = pg.evaluate(LIST)
        pg.evaluate("() => { window.__anims = []; }")
        pg.click("#alt-next")
        pg.wait_for_timeout(1200)
        idx, sch = _active(pg)
        assert idx != first_idx
        after = _check_list(pg, sch)
        assert after != before, "הרשימה לא התחלפה"
        # ‏בלי תנועה: לא בלוקים שזזים ולא נחיתה — גם לא ברשת המוסתרת.
        anims = pg.evaluate("() => window.__anims")
        assert [a for a in anims if "dl-" in a["cls"] or a["cls"].startswith("ev ")] == [], anims
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_no_landing_below_1000(browser, server):
    ctx, pg = _open(browser, server, PHONE, hook=True)
    try:
        anims = pg.evaluate("() => window.__anims")
    finally:
        ctx.close()
    assert [a for a in anims if a["cls"].startswith("ev ") or "dl-" in a["cls"]] == [], anims


# ==========================================================================
# 2. מערכות מעובדות: יום ריק, יום ו׳ עם שיעורים, חפיפה
# ==========================================================================
def _monday_to_friday(schedules):
    """כל מפגשי יום ב׳ עוברים ליום ו׳: יום ב׳ ריק, ויום ו׳ אינו ריק."""
    for sch in schedules:
        for p in sch.get("picks") or []:
            for m in p.get("meetings") or []:
                if int(m["day"]) == 2:
                    m["day"] = FRIDAY


def test_an_empty_day_is_one_line_and_a_friday_with_lessons_is_listed(browser, server):
    ctx, pg = _open(browser, server, PHONE, craft=_monday_to_friday)
    try:
        _, sch = _active(pg)
        got = _check_list(pg, sch)
        monday = [g for g in got if g["day"] == 2]
        assert monday and monday[0]["empty"], got
        assert monday[0]["heading"] == "שני · אין שיעורים"
        assert got[-1]["day"] == FRIDAY and got[-1]["items"], got
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


#: ‏הקורסים שהחפיפה המעובדת נוצרה ביניהם. לא 11069: המתג של השו"ת שלו
#: ‏דולק כברירת מחדל (Phase 12), ושאר המתגים כבויים.
OVERLAP = {}


def _overlap(schedules):
    """בחלופה הראשונה: מפגש של קורס אחד עובר לשעה של מפגש של קורס אחר."""
    sch = schedules[0]
    picks = [p for p in sch.get("picks") or [] if p.get("meetings") and str(p.get("code")) != "11069"]
    a, b = picks[0], next(p for p in picks[1:] if str(p.get("code")) != str(picks[0].get("code")))
    target = a["meetings"][0]
    moved = b["meetings"][0]
    moved["day"], moved["start"], moved["end"] = target["day"], target["start"], target["end"]
    OVERLAP.update(a=str(a["code"]), b=str(b["code"]), day=int(target["day"]))


def test_overlapping_lessons_are_marked_in_start_order_and_open_together(browser, server):
    ctx, pg = _open(browser, server, PHONE, craft=_overlap)
    try:
        _, sch = _active(pg)
        got = _check_list(pg, sch)
        day = next(g for g in got if g["day"] == OVERLAP["day"])
        soft = [i for i in day["items"] if i["soft"]]
        assert {i["code"] for i in soft} >= {OVERLAP["a"], OVERLAP["b"]}, day
        assert all(i["badge"] for i in soft), soft
        assert [i["hours"] for i in day["items"]] == sorted(i["hours"] for i in day["items"])
        b = pg.locator(f'#schedule-days .dl-lesson.is-soft[data-code="{OVERLAP["b"]}"]').first
        b.scroll_into_view_if_needed()
        b.click()
        pg.wait_for_timeout(400)
        detail = pg.evaluate(
            """() => { const body = document.getElementById('meeting-detail-body');
                       return {overlap: !!body.querySelector('.detail-overlap'),
                               items: body.querySelectorAll('.detail-item').length,
                               off: body.querySelectorAll('.detail-item .detail-att-off').length}; }"""
        )
        assert detail["overlap"] and detail["items"] >= 2, detail
        assert detail["off"] == detail["items"], f"ההערה חסרה מתחת לשיעור שהמתג שלו כבוי: {detail}"
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


# ==========================================================================
# 3. מ-1000px ומעלה: הרשת
# ==========================================================================
BLOCKS = """() => [...document.querySelectorAll('#schedule-grid .ev')].map(e => {
  const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
  const top = r.top + parseFloat(cs.borderTopWidth), bot = r.bottom - parseFloat(cs.borderBottomWidth);
  const lines = [...e.querySelectorAll(':scope > .ev-line')];
  return {key: e.dataset.lesson, n: lines.length,
          ok: lines.every(l => { const lr = l.getBoundingClientRect();
                return getComputedStyle(l).display !== 'none' && lr.height > 0 && l.textContent.trim()
                       && lr.top >= top - 0.5 && lr.bottom <= bot + 0.5; }),
          over: e.scrollHeight - e.clientHeight};
})"""


@pytest.mark.parametrize("size", [(1000, 900), (1440, 900)], ids=["1000", "1440"])
def test_the_grid_stays_from_1000_up(browser, server, size):
    ctx, pg = _open(browser, server, size)
    try:
        pg.wait_for_function(
            "() => !!document.getElementById('schedule-grid').style.getPropertyValue('--slot-h')",
            timeout=15000,
        )
        pg.wait_for_timeout(500)
        shown = pg.evaluate(SHOWN)
        assert shown["grid"] and not shown["list"], shown
        blocks = pg.evaluate(BLOCKS)
        _, sch = _active(pg)
        assert len(blocks) == len(_meetings(pg, sch))
        if size[0] == 1000:
            # ‏הרוחב שבו הקו נמתח: כל בלוק בשלוש שורות שלמות, בלי גלילה הצידה.
            for b in blocks:
                assert b["n"] == 3 and b["ok"] and b["over"] <= 0, b
            box = pg.evaluate(
                "() => { const b = document.getElementById('grid-scroll'); return b.scrollWidth - b.clientWidth; }"
            )
            assert box <= 0, f"הרשת נגללת הצידה ב-1000px: {box}"
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


# ==========================================================================
# 4. הדפסה מהטלפון: תמיד הרשת
# ==========================================================================
def test_print_from_a_phone_is_the_grid_with_every_block_in_three_lines(browser, server):
    ctx, pg = _open(browser, server, PHONE)
    try:
        _, sch = _active(pg)
        n = len(_meetings(pg, sch))
        pg.emulate_media(media="print")
        pg.wait_for_timeout(1000)
        shown = pg.evaluate(
            """() => ({grid: getComputedStyle(document.getElementById('grid-scroll')).display,
                       list: getComputedStyle(document.getElementById('schedule-days')).display})"""
        )
        blocks = pg.evaluate(BLOCKS)
        pg.emulate_media(media="screen")
        pg.wait_for_timeout(500)
        back = pg.evaluate(SHOWN)
    finally:
        ctx.close()
    assert shown["grid"] != "none" and shown["list"] == "none", shown
    assert len(blocks) == n, (len(blocks), n)
    for b in blocks:
        assert b["n"] == 3 and b["ok"] and b["over"] <= 0, b
    assert back["list"] and not back["grid"], back
