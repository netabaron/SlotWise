"""שלב 6 של העיצוב מחדש: החלופות (docs/DESIGN.md, "Results page", 2, 3, 6, 7, 8).

מה נבדק כאן
-----------
* **כרטיסים:** חמישה, אחד לכל חלופה, ועל כל אחד המספר הקבוע שלה — הדירוג
  בשרת — כדי ש"דומה למערכת 1" יישאר נכון אחרי מיון. הנבחר במסגרת ‎--ink‎.
* **מיון:** ארבעה סדרים, בדפדפן בלבד, ושוויון שומר על סדר השרת. מיון חוזר
  שומר על אותה חלופה בחורה, והמיון אינו נשמר.
* **הקודמת/הבאה** הולכות לפי הסדר הממוין, ו-"N מתוך 5" איתן.
* **הלשוניות וטבלת "מה ההבדל?" הוסרו.**
* **תנועה:** הבלוקים נשמרים לפי מפתח שיעור וזזים למקומם החדש (550ms);
  ‏prefers-reduced-motion — בלי תנועה. גובה השעה מהתוכן נשמר אחרי כל החלפה.
  בחירת חלופה אינה פונה לשרת.
* **פרטי שיעור** בפאנל ליד המקרא, ומקרא שמאפיר את שאר הקורסים — בצבע, לא
  ב-opacity, בריחוף ובהקשה.

**אף בדיקה כאן אינה תלויה ב-data/db המקומי** (DEFERRED.md, "Tests that start a
server read the real data/db"). כל ציפייה נגזרת ממה שהשרת החזיר בפועל. בדיקות
המיון אינן סומכות על הנתונים בכלל: עם ששת הקורסים המומלצים כל חמש החלופות
שקולות בכל מפתח מיון, ולכן התשובה של ‎/api/solve‎ מיורטת וחמש החלופות מקבלות
ערכים ידועים — כולל שוויונות מכוונים.
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
ALTS = STRINGS["app"]["alts"]
STORAGE_KEY = "braude_schedule_builder_v1"  # אין לשנותו — ראו CLAUDE.md

#: ערכים ידועים לחמש החלופות, לפי סדר השרת. בכל אחד יש שוויון מכוון.
CRAFT_GAPS = [120, 60, 60, 0, 30]
CRAFT_DAYS = [5, 4, 5, 3, 4]
#: נוסף לשעת הסיום של כל חלופה (לשיעור האחרון שלה).
CRAFT_FINISH_DELTA = [0, 60, 0, 120, 60]


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


def _mutating(mutate):
    """‏route handler: התשובה האמיתית של ‎/api/solve‎, אחרי mutate(schedules)."""
    def handler(route):
        response = route.fetch()
        data = response.json()
        schedules = data.get("schedules") or []
        if len(schedules) == 5:
            mutate(schedules)
        route.fulfill(
            status=response.status,
            headers={"content-type": "application/json"},
            body=json.dumps(data, ensure_ascii=False),
        )
    return handler


def _craft_sort(schedules):
    """החלונות, הימים ושעת הסיום — ערכים ידועים, עם שוויון מכוון בכל אחד."""
    for i, sch in enumerate(schedules):
        sch["gap_minutes"] = CRAFT_GAPS[i]
        sch["days_count"] = CRAFT_DAYS[i]
        meetings = [m for p in sch.get("picks", []) for m in p.get("meetings") or []]
        if meetings:
            last = max(meetings, key=lambda m: m["end"])
            last["end"] = last["end"] + CRAFT_FINISH_DELTA[i]


#: שם מרצה ארוך בבלוק הקצר ביותר של חלופה 2: התוכן שלה צריך יותר גובה לשעה.
LONG_LECTURER = "ד\"ר " + "שם-ארוך-מאוד " * 8


def _craft_taller_second(schedules):
    sch = schedules[1]
    picks = [p for p in sch["picks"] if p.get("meetings")]
    shortest = min(picks, key=lambda p: min(m["end"] - m["start"] for m in p["meetings"]))
    shortest["lecturer"] = LONG_LECTURER


def _craft_one_meeting_moves(schedules):
    """חלופה 2 = חלופה 1, חוץ ממפגש **אחד** של שיעור שנפגש פעמיים בשבוע, שעובר
    ליום פנוי באותה שעה. רק הבלוק הזה אמור לזוז."""
    import copy
    first = schedules[0]
    second = copy.deepcopy(first)
    pick = next(p for p in second["picks"] if len(p.get("meetings") or []) >= 2)
    ordered = sorted(pick["meetings"], key=lambda m: (m["day"], m["start"]))
    # ‏המפגש המוקדם עובר אל **אחרי** השני: כך שיוך לפי סדר בלבד היה מזיז את
    # שני הבלוקים, והבדיקה מבחינה בין השיוך לפי יום ושעה לבין שיוך לפי סדר.
    moved, other = ordered[0], ordered[1]
    busy = [(m["day"], m["start"], m["end"]) for p in second["picks"] for m in p.get("meetings") or []]
    length = moved["end"] - moved["start"]
    # חלון פנוי באותו אורך, ביום ובשעה אחרים — בלי לחפוף לאף מפגש.
    for day in (1, 2, 3, 4, 5):
        for start in range(8 * 60 + 30, 20 * 60 - length + 1, 30):
            later = (day, start) > (other["day"], other["start"])
            free = all(not (d == day and s < start + length and start < e) for d, s, e in busy)
            if free and later:
                moved["day"], moved["start"], moved["end"] = day, start, start + length
                break
        else:
            continue
        break
    second["_moved"] = [pick["code"], pick["kind"]]
    schedules[1] = second


def _open(browser, server, width=1440, height=1000, craft=None, **ctx_opts):
    ctx = browser.new_context(
        viewport={"width": width, "height": height}, color_scheme="light", **ctx_opts
    )
    page = ctx.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    page.solves = []  # type: ignore[attr-defined]
    page.on("request", lambda r: page.solves.append(r.url)  # type: ignore[attr-defined]
            if r.method == "POST" and r.url.endswith("/api/solve") else None)
    if craft:
        page.route("**/api/solve", _mutating(craft))
    page.goto(server)
    page.wait_for_timeout(2500)
    page.select_option("#select-program", "הנדסת תוכנה")
    page.select_option("#select-year", "3")
    page.select_option("#select-term", "א")
    page.wait_for_timeout(2500)
    page.click("#btn-restore-recommended")
    page.wait_for_selector("#alt-cards .alt-card", timeout=20000)
    page.wait_for_function(
        "() => !!document.getElementById('schedule-grid').style.getPropertyValue('--slot-h')",
        timeout=15000,
    )
    page.wait_for_timeout(800)
    return ctx, page


@pytest.fixture(scope="module")
def page(browser, server):
    """הנתונים כמו שהשרת מחזיר אותם, ב-1440. לבדיקות שאינן ממיינות."""
    ctx, pg = _open(browser, server)
    try:
        yield pg
    finally:
        ctx.close()


@pytest.fixture()
def crafted(browser, server):
    """חמש חלופות עם ערכים ידועים — לבדיקות המיון."""
    ctx, pg = _open(browser, server, craft=_craft_sort)
    try:
        # הערכים באמת הגיעו לדף — אחרת כל בדיקות המיון היו ריקות.
        gaps = pg.evaluate("window.slotwise.getRuntime().solve.schedules.map(s => s.gap_minutes)")
        assert gaps == CRAFT_GAPS, gaps
        yield pg
    finally:
        ctx.close()


STATE = """() => ({
  ranks: [...document.querySelectorAll('#alt-cards .alt-card')].map(c => +c.dataset.rank),
  selected: [...document.querySelectorAll('#alt-cards .alt-card.is-selected')].map(c => +c.dataset.rank),
  pressed: [...document.querySelectorAll('#alt-cards .alt-card[aria-pressed="true"]')].map(c => +c.dataset.rank),
  active: window.slotwise.getState().activeSchedule,
  pos: document.getElementById('alt-pos').textContent,
  prev: document.getElementById('alt-prev').disabled,
  next: document.getElementById('alt-next').disabled,
  sort: document.getElementById('alt-sort').value,
})"""


def _expected(page, key):
    """הסדר הצפוי (מספרי חלופות, 1..5), מחושב מהנתונים שהדף קיבל."""
    values = page.evaluate(
        """(key) => window.slotwise.getRuntime().solve.schedules.map(s => {
             if (key === 'gaps') return s.gap_minutes;
             if (key === 'days') return s.days_count;
             let last = null;
             s.picks.forEach(p => (p.meetings || []).forEach(m => {
               if (last === null || m.end > last) last = m.end; }));
             return last === null ? Infinity : last;
           })""",
        key,
    )
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    return [i + 1 for i in order], values


def _sort(page, key):
    page.select_option("#alt-sort", key)
    page.wait_for_timeout(300)
    return page.evaluate(STATE)


# ==========================================================================
# 1. כרטיסים ושורת הכותרת
# ==========================================================================
def test_one_card_per_alternative_with_its_fixed_number(page):
    got = page.evaluate(
        """() => ({
          n: window.slotwise.getRuntime().solve.schedules.length,
          cards: [...document.querySelectorAll('#alt-cards .alt-card')].map(c => ({
            rank: +c.dataset.rank, name: c.querySelector('.alt-card-name').textContent,
            facts: c.querySelector('.alt-card-facts').textContent,
            label: c.querySelector('.alt-card-label').textContent,
            minis: c.querySelectorAll('.mini .mini-ev').length,
            cols: c.querySelectorAll('.mini .mini-day').length,
            text: [...c.querySelectorAll('.mini *')].some(e => e.textContent.trim()),
            tag: c.tagName})),
        })"""
    )
    assert got["n"] == 5 and len(got["cards"]) == 5, got
    assert [c["rank"] for c in got["cards"]] == [1, 2, 3, 4, 5]
    for c in got["cards"]:
        assert c["tag"] == "BUTTON", c
        assert c["name"] == fill(ALTS["cardName"], n=c["rank"]), c
        assert re.fullmatch(r"(\d+ ימים|יום אחד), עד \d\d:\d\d", c["facts"]), c
        assert c["label"], c
        assert c["minis"] > 0 and c["cols"] in (5, 6) and not c["text"], c


def test_the_selected_card_has_an_ink_border(page):
    got = page.evaluate(
        """() => { const c = document.querySelector('#alt-cards .alt-card.is-selected');
                   const ink = getComputedStyle(document.documentElement).getPropertyValue('--ink').trim();
                   const probe = document.createElement('span'); probe.style.color = ink;
                   document.body.appendChild(probe); const inkRgb = getComputedStyle(probe).color; probe.remove();
                   return {rank: +c.dataset.rank, border: getComputedStyle(c).borderTopColor, ink: inkRgb,
                           pressed: c.getAttribute('aria-pressed')}; }"""
    )
    assert got["rank"] == 1 and got["pressed"] == "true", got
    assert got["border"] == got["ink"], got


def test_the_header_row(page):
    got = page.evaluate(
        """() => ({title: document.getElementById('alt-title').textContent,
                   pos: document.getElementById('alt-pos').textContent,
                   print: !!document.querySelector('#alt-head #btn-print'),
                   options: [...document.querySelectorAll('#alt-sort option')].map(o => [o.value, o.textContent]),
                   sort: document.getElementById('alt-sort').value})"""
    )
    assert got["title"] == fill(ALTS["title"], n=5)
    assert got["pos"] == fill(ALTS["position"], pos=1, total=5)
    assert got["print"], "כפתור ההדפסה אמור לשבת בשורת הכותרת"
    assert got["options"] == [[k, ALTS["sort"][k]] for k in ("fit", "gaps", "finish", "days")]
    assert got["sort"] == "fit"


def test_the_tabs_and_the_comparison_table_are_gone(page):
    got = page.evaluate(
        """() => ['#schedule-tabs', '#compare', '.compare-table', '.tab', '#compare-body']
                  .filter(sel => document.querySelector(sel))"""
    )
    assert got == [], got
    assert "title" not in STRINGS["app"]["compare"] and "tableLabel" not in STRINGS["app"]["compare"]
    # התווית המבדילה עדיין משמשת את שורת ההדפסה.
    head = page.evaluate("document.getElementById('print-head').textContent")
    label = page.evaluate("document.querySelector('#alt-cards .alt-card.is-selected .alt-card-label').textContent")
    assert label in head, (head, label)


def test_cards_are_keyboard_operable(browser, server):
    ctx, pg = _open(browser, server)
    try:
        pg.focus('#alt-cards [data-rank="2"]')
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(500)
        assert pg.evaluate(STATE)["active"] == 1
        pg.focus('#alt-cards [data-rank="4"]')
        pg.keyboard.press(" ")
        pg.wait_for_timeout(500)
        assert pg.evaluate(STATE)["active"] == 3
    finally:
        ctx.close()


def test_the_cards_scroll_inside_their_own_row_on_a_phone(browser, server):
    ctx, pg = _open(browser, server, width=390, height=900)
    try:
        got = pg.evaluate(
            """() => { const r = document.getElementById('alt-cards');
                       return {own: r.scrollWidth > r.clientWidth, ox: getComputedStyle(r).overflowX,
                               page: document.documentElement.scrollWidth, vw: window.innerWidth}; }"""
        )
        assert got["own"] and got["ox"] == "auto", got
        assert got["page"] <= got["vw"], f"העמוד עצמו נגלל לרוחב: {got}"
    finally:
        ctx.close()


# ==========================================================================
# 2. מיון, הקודמת/הבאה
# ==========================================================================
@pytest.mark.parametrize("key", ["fit", "gaps", "finish", "days"])
def test_each_sort_order(crafted, key):
    """‏"fit" הוא סדר השרת; השאר עולים לפי הערך, ושוויון — לפי סדר השרת."""
    want, values = ([1, 2, 3, 4, 5], None) if key == "fit" else _expected(crafted, key)
    # קודם ממיינים לסדר אחר — כך גם "fit" נבדק כחזרה לסדר השרת, לא כמצב ההתחלה.
    _sort(crafted, "days" if key != "days" else "gaps")
    got = _sort(crafted, key)
    assert got["ranks"] == want, (key, values, got)


def test_ties_keep_the_server_order(crafted):
    """בכל מפתח יש שוויון מכוון; בתוך שוויון הסדר הוא סדר השרת."""
    for key in ("gaps", "finish", "days"):
        want, values = _expected(crafted, key)
        tied = [r for r in range(1, 6) if values.count(values[r - 1]) > 1]
        assert tied, f"אין שוויון ב-{key} — הבדיקה אינה בודקת דבר: {values}"
        got = _sort(crafted, key)["ranks"]
        for v in set(values[r - 1] for r in tied):
            group = [r for r in got if values[r - 1] == v]
            assert group == sorted(group), (key, v, got)


def test_resorting_keeps_the_same_alternative_selected(crafted):
    crafted.click('#alt-cards [data-rank="3"]')
    crafted.wait_for_timeout(500)
    for key in ("gaps", "finish", "days", "fit"):
        got = _sort(crafted, key)
        assert got["active"] == 2 and got["selected"] == [3] and got["pressed"] == [3], (key, got)
        pos = got["ranks"].index(3) + 1
        assert got["pos"] == fill(ALTS["position"], pos=pos, total=5), (key, got)


def test_prev_and_next_follow_the_sorted_order(crafted):
    want, _ = _expected(crafted, "days")
    _sort(crafted, "days")
    crafted.click(f'#alt-cards [data-rank="{want[0]}"]')
    crafted.wait_for_timeout(500)
    seen = []
    for step in range(5):
        st = crafted.evaluate(STATE)
        seen.append(st["active"] + 1)
        assert st["pos"] == fill(ALTS["position"], pos=step + 1, total=5), st
        assert st["prev"] == (step == 0) and st["next"] == (step == 4), st
        if step < 4:
            crafted.click("#alt-next")
            crafted.wait_for_timeout(450)
    assert seen == want, (seen, want)
    crafted.click("#alt-prev")
    crafted.wait_for_timeout(450)
    assert crafted.evaluate(STATE)["active"] + 1 == want[3]


def test_choosing_and_sorting_do_not_ask_the_server(crafted):
    before = len(crafted.solves)
    crafted.click('#alt-cards [data-rank="2"]')
    crafted.wait_for_timeout(400)
    _sort(crafted, "gaps")
    crafted.click("#alt-next")
    crafted.wait_for_timeout(400)
    assert len(crafted.solves) == before, crafted.solves


def test_the_sort_is_not_saved(crafted):
    _sort(crafted, "gaps")
    saved = crafted.evaluate("(k) => localStorage.getItem(k) || ''", STORAGE_KEY)
    assert "gaps" not in saved
    crafted.reload()
    crafted.wait_for_selector("#alt-cards .alt-card", timeout=20000)
    crafted.wait_for_timeout(600)
    got = crafted.evaluate(STATE)
    assert got["sort"] == "fit" and got["ranks"] == [1, 2, 3, 4, 5], got


# ==========================================================================
# 3. החלפת חלופה: בלוקים שנשמרים וזזים
# ==========================================================================
SWITCH = """async (rank) => {
  const before = new Set(document.querySelectorAll('#schedule-grid .ev'));
  document.querySelector('#alt-cards [data-rank="' + rank + '"]').click();
  await new Promise(r => setTimeout(r, 60));
  const anims = document.getAnimations().filter(a => a.id === 'ev-move');
  const evs = [...document.querySelectorAll('#schedule-grid .ev')];
  return {reused: evs.filter(e => before.has(e)).length, total: evs.length, was: before.size,
          moved: anims.map(a => a.effect.target.dataset.base),
          anims: anims.map(a => ({d: a.effect.getTiming().duration, e: a.effect.getTiming().easing}))};
}"""

#: ‏כשאין תנועה רצה: הגובה מהתוכן, ושום בלוק אינו גולש.
SETTLED = """() => ({moving: document.getAnimations().filter(a => a.id === 'ev-move').length,
                    slot: parseFloat(document.getElementById('schedule-grid').style.getPropertyValue('--slot-h'))})"""

OVERFLOW = """() => {
  const g = document.getElementById('schedule-grid');
  const slot = parseFloat(g.style.getPropertyValue('--slot-h'));
  const evs = [...g.querySelectorAll('.ev')];
  const over = () => evs.filter(e => e.scrollHeight > e.clientHeight).length;
  const at = over();
  g.style.setProperty('--slot-h', (slot - 1) + 'px');
  const below = over();
  g.style.setProperty('--slot-h', slot + 'px');
  return {slot, at, below};
}"""


def _first_differing_rank(page):
    """חלופה שבה לפחות שיעור אחד ביום או בשעה אחרים מאשר בחלופה 1. קבוצה
    אחרת באותה שעה (חדר אחר) אינה זזה ברשת, ולכן אינה נחשבת."""
    return page.evaluate(
        """() => { const s = window.slotwise.getRuntime().solve.schedules;
                   const key = sch => JSON.stringify(sch.picks.map(p => [p.code, p.kind,
                     (p.meetings || []).map(m => [m.day, m.start, m.end])]));
                   for (let i = 1; i < s.length; i++) if (key(s[i]) !== key(s[0])) return i + 1;
                   return 0; }"""
    )


def test_switching_moves_the_same_blocks_and_keeps_the_hour_height(browser, server):
    ctx, pg = _open(browser, server)
    try:
        rank = _first_differing_rank(pg)
        assert rank, "כל החלופות זהות — אין מה להזיז"
        got = pg.evaluate(SWITCH, rank)
        assert got["reused"] == min(got["total"], got["was"]), got
        assert got["anims"], f"שום בלוק לא זז במעבר לחלופה {rank}: {got}"
        assert all(a["d"] == 550 and a["e"] == "cubic-bezier(0.2, 0.8, 0.2, 1)" for a in got["anims"]), got
        pg.wait_for_timeout(900)
        fit = pg.evaluate(OVERFLOW)
        assert fit["at"] == 0, fit
        assert fit["below"] > 0 or fit["slot"] <= 12, fit
        assert pg.errors == [], pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_reduced_motion_makes_the_switch_instant(browser, server):
    ctx, pg = _open(browser, server, reduced_motion="reduce")
    try:
        rank = _first_differing_rank(pg)
        assert rank
        got = pg.evaluate(SWITCH, rank)
        assert got["reused"] == min(got["total"], got["was"]), got
        assert got["anims"] == [], got
    finally:
        ctx.close()


def test_the_hour_height_follows_the_alternative_after_the_move_lands(browser, server):
    """‏חלופה 2 צריכה יותר גובה לשעה (שם מרצה ארוך בבלוק הקצר ביותר). אחרי
    ההחלפה — כשהתנועה נחתה — הגובה הוא של חלופה 2, וכשחוזרים — של חלופה 1.

    ‏זו הבדיקה שהייתה תופסת את הבאג שבדיקת ההחלפה הרגילה פספסה: עם הנתונים
    האמיתיים לכל החלופות אותו גובה, ולכן מדידה באמצע התנועה (מהגובה הישן)
    נראתה נכונה במקרה."""
    ctx, pg = _open(browser, server, craft=_craft_taller_second)
    try:
        first = pg.evaluate(SETTLED)["slot"]
        pg.click('#alt-cards [data-rank="2"]')
        pg.wait_for_timeout(1200)
        second = pg.evaluate(SETTLED)
        fit = pg.evaluate(OVERFLOW)
        assert second["moving"] == 0, second
        assert second["slot"] > first, (first, second)
        assert fit["at"] == 0 and fit["below"] > 0, fit
        pg.click('#alt-cards [data-rank="1"]')
        pg.wait_for_timeout(1200)
        back = pg.evaluate(SETTLED)
        fit = pg.evaluate(OVERFLOW)
        assert back["slot"] == first, (first, back)
        assert fit["at"] == 0 and (fit["below"] > 0 or fit["slot"] <= 12), fit
    finally:
        ctx.close()


def test_a_second_switch_mid_move_lands_cleanly(browser, server):
    """שתי החלפות בתוך 550ms: התנועה הראשונה נעצרת, והכול נוחת במקום ובגובה."""
    ctx, pg = _open(browser, server, craft=_craft_taller_second)
    try:
        pg.click('#alt-cards [data-rank="2"]')
        pg.wait_for_timeout(120)
        pg.click('#alt-cards [data-rank="3"]')
        pg.wait_for_timeout(1300)
        st = pg.evaluate(SETTLED)
        fit = pg.evaluate(OVERFLOW)
        assert st["moving"] == 0, st
        assert fit["at"] == 0 and (fit["below"] > 0 or fit["slot"] <= 12), fit
        # ושום בלוק לא נשאר עם גודל או מיקום של אנימציה.
        stuck = pg.evaluate(
            """() => [...document.querySelectorAll('#schedule-grid .ev')]
                 .filter(e => e.style.transform || e.style.width || e.style.height).length"""
        )
        assert stuck == 0
        assert pg.errors == [], pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_only_the_meeting_that_moved_animates(browser, server):
    """שיעור שנפגש פעמיים בשבוע ושרק אחד ממפגשיו עבר: רק הבלוק הזה זז."""
    ctx, pg = _open(browser, server, craft=_craft_one_meeting_moves)
    try:
        moved = pg.evaluate("window.slotwise.getRuntime().solve.schedules[1]._moved")
        assert moved, "חלופה 2 אמורה להיות חלופה 1 עם מפגש אחד שזז"
        got = pg.evaluate(SWITCH, 2)
        assert got["moved"] == ["|".join(moved)], got
    finally:
        ctx.close()


# ==========================================================================
# 4. פרטי שיעור, ליד המקרא
# ==========================================================================
def test_the_details_panel_shows_the_lesson_next_to_the_legend(browser, server):
    ctx, pg = _open(browser, server)
    try:
        pg.focus("#schedule-grid .ev")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(500)
        got = pg.evaluate(
            """() => {
              const panel = document.getElementById('meeting-detail');
              const block = document.querySelector('#schedule-grid .ev.is-selected');
              const lesson = block && block.dataset.lesson;
              const [code, kind] = (lesson || '||').split('|');
              const sch = window.slotwise.getRuntime().solve.schedules[window.slotwise.getState().activeSchedule];
              const pick = sch.picks.find(p => p.code === code && p.kind === kind);
              const cs = block && getComputedStyle(block);
              return {hidden: panel.hidden, role: panel.getAttribute('role'),
                      live: document.getElementById('meeting-detail-body').getAttribute('aria-live'),
                      nextToLegend: panel.parentElement.classList.contains('grid-tools'),
                      text: panel.textContent, pick: pick,
                      selected: document.querySelectorAll('#schedule-grid .ev.is-selected').length,
                      focusOnBlock: document.activeElement === block,
                      outline: cs && cs.outlineStyle, outlineColor: cs && cs.outlineColor,
                      bd: cs && cs.getPropertyValue('--ev-bd').trim()};
            }"""
        )
        assert not got["hidden"] and got["role"] is None and got["live"] == "polite", got
        assert got["nextToLegend"], "הפאנל אמור לשבת ליד המקרא"
        assert got["selected"] == 1 and got["focusOnBlock"], got
        # גם מי שאינו רואה את הקו יודע איזה בלוק הפאנל מתאר.
        current = pg.evaluate(
            "[...document.querySelectorAll('#schedule-grid .ev[aria-current=\"true\"]')]"
            ".map(e => e.classList.contains('is-selected'))"
        )
        assert current == [True], current
        pick = got["pick"]
        for need in (pick["lecturer"], pick["group_id"]):
            assert need in got["text"], (need, got["text"][:200])
        meeting = pick["meetings"][0]
        assert re.search(r"\d\d:\d\d–\d\d:\d\d", got["text"]), got["text"][:200]
        room = pg.evaluate("(r) => window.slotwise.formatRoom(r)", " ".join(
            x for x in (meeting.get("building"), meeting.get("room")) if x))
        if room:
            assert room in got["text"], (room, got["text"][:200])
        # קו מתאר בצבע הקורס — אותו צבע כמו מסגרת הבלוק. כל עוד הבלוק בפוקוס
        # מקלדת, טבעת הפוקוס גוברת עליו (בכוונה); לכן בודקים אחרי שהפוקוס עבר.
        pg.evaluate("document.activeElement.blur()")
        pg.wait_for_timeout(100)
        cs = pg.evaluate(
            """() => { const b = document.querySelector('#schedule-grid .ev.is-selected');
                       const c = getComputedStyle(b);
                       return {outline: c.outlineStyle, outlineColor: c.outlineColor}; }"""
        )
        got.update(cs)
        probe = pg.evaluate(
            """(hex) => { const p = document.createElement('span'); p.style.color = hex;
                          document.body.appendChild(p); const c = getComputedStyle(p).color; p.remove(); return c; }""",
            got["bd"],
        )
        assert got["outline"] == "solid" and got["outlineColor"] == probe, got
        # ‏Esc מנקה, והפוקוס נשאר על הבלוק.
        pg.focus("#schedule-grid .ev.is-selected")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        after = pg.evaluate(
            """() => ({hidden: document.getElementById('meeting-detail').hidden,
                       selected: document.querySelectorAll('#schedule-grid .ev.is-selected').length,
                       onBlock: document.activeElement.classList.contains('ev')})"""
        )
        assert after == {"hidden": True, "selected": 0, "onBlock": True}, after
        assert pg.evaluate("document.querySelectorAll('#schedule-grid .ev[aria-current]').length") == 0
    finally:
        ctx.close()


# ==========================================================================
# 5. המקרא מאפיר את שאר הקורסים — בצבע, לא ב-opacity
# ==========================================================================
GREY = """() => {
  const evs = [...document.querySelectorAll('#schedule-grid .ev')];
  const root = getComputedStyle(document.documentElement);
  const probe = v => { const p = document.createElement('span'); p.style.color = v;
                       document.body.appendChild(p); const c = getComputedStyle(p).color; p.remove(); return c; };
  return {
    rows: evs.map(e => { const cs = getComputedStyle(e);
      return {code: e.dataset.code, muted: e.classList.contains('is-muted'), opacity: cs.opacity,
              color: cs.color, bg: cs.backgroundColor, border: cs.borderTopColor,
              innerOpacity: [...e.querySelectorAll('*')].map(x => getComputedStyle(x).opacity)
                               .filter(o => o !== '1')}; }),
    mut: probe(root.getPropertyValue('--mut').trim()),
    chip: probe(root.getPropertyValue('--chip').trim()),
    bd: probe(root.getPropertyValue('--bd').trim()),
  };
}"""


def _assert_greyed(got, code):
    muted = [r for r in got["rows"] if r["muted"]]
    kept = [r for r in got["rows"] if not r["muted"]]
    assert muted and kept, got
    assert all(r["code"] == code for r in kept), (code, kept)
    assert all(r["code"] != code for r in muted), (code, muted)
    for r in got["rows"]:
        assert r["opacity"] == "1" and r["innerOpacity"] == [], r
    for r in muted:
        assert (r["color"], r["bg"], r["border"]) == (got["mut"], got["chip"], got["bd"]), r


def test_hovering_a_legend_chip_greys_the_other_courses(page):
    chip = page.locator("#schedule-legend button.legend-chip").first
    code = chip.get_attribute("data-code")
    chip.hover()
    page.wait_for_timeout(300)
    _assert_greyed(page.evaluate(GREY), code)
    page.mouse.move(2, 2)
    page.wait_for_timeout(300)
    assert not any(r["muted"] for r in page.evaluate(GREY)["rows"])


def test_tapping_a_legend_chip_toggles_the_greying(browser, server):
    ctx, pg = _open(browser, server, has_touch=True)
    try:
        chip = pg.locator("#schedule-legend button.legend-chip").nth(1)
        code = chip.get_attribute("data-code")
        chip.tap()
        pg.wait_for_timeout(300)
        _assert_greyed(pg.evaluate(GREY), code)
        assert chip.get_attribute("aria-pressed") == "true"
        chip.tap()
        pg.wait_for_timeout(300)
        assert not any(r["muted"] for r in pg.evaluate(GREY)["rows"])
        assert chip.get_attribute("aria-pressed") == "false"
    finally:
        ctx.close()


def test_greying_and_selection_stay_off_the_printed_sheet(browser, server):
    """שבב נעוץ ופאנל פתוח, ואז הדפסה: על הנייר כל קורס בצבעו, ובלי קו בחירה."""
    ctx, pg = _open(browser, server, width=794, height=1123)
    try:
        pg.locator("#schedule-legend button.legend-chip").first.click()
        pg.click("#schedule-grid .ev >> nth=2")
        pg.wait_for_timeout(400)
        assert pg.evaluate("document.querySelectorAll('#schedule-grid .ev.is-muted').length") > 0
        pg.emulate_media(media="print")
        pg.wait_for_timeout(900)
        got = pg.evaluate(
            """() => [...document.querySelectorAll('#schedule-grid .ev')].map(e => {
                 const cs = getComputedStyle(e);
                 const p = document.createElement('span'); p.style.color = cs.getPropertyValue('--ev-bg').trim();
                 document.body.appendChild(p); const want = getComputedStyle(p).color; p.remove();
                 return {muted: e.classList.contains('is-muted'), selected: e.classList.contains('is-selected'),
                         soft: e.classList.contains('is-soft'),
                         bg: cs.backgroundColor, want: want, outline: cs.outlineStyle}; })"""
        )
        assert any(r["muted"] for r in got) and any(r["selected"] for r in got), got
        for r in got:
            assert r["bg"] == r["want"], r
            if not r["soft"]:
                assert r["outline"] == "none", r
        body = pg.evaluate("Math.round(document.body.scrollHeight)")
        assert body <= round(297 * 96 / 25.4), body
    finally:
        ctx.close()
