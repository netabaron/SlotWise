"""‏"בלי X (הרצאה) · צריך יום לימוד נוסף [הוספת יום] ⓘ" — 2026-10-27.

מרצה בדירוג 1 שחסר כי יעד הימים קודם לו נאמר בשורה משלו, מתחת לשבבי הנתונים
ומעל "מה פחות טוב", עם כפתור שמעלה את היעד ל-``first_choices_days`` (N). כשהשורה
מוצגת, פריט המרצים יוצא משורת "מה פחות טוב" — הוא לא נאמר פעמיים. בלי N הכול
כמו קודם.

המקרה האמיתי, בקטלוג הקפוא: הנדסת תוכנה שנה ב׳ סמסטר א׳ עם המומלצים, יעד 3
ימים, ו-ד"ר דנטה-בירון אילה בדירוג 1 בהרצאה של 61911. המערכת הראשונה היא
3 ימים בלעדיה, ו-N הוא 4. הלחיצה מעלה את היעד ל-4, והראשונה החדשה כוללת אותה.

‏"2 ימים", ‏N חסר ודירוג מת נבנים בתשובת ‎/api/solve‎ מיורטת — את N האמיתי
בודקת ‏tests/test_first_choices_days.py מול חיפוש בלתי תלוי.
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
SCHED = STRINGS["app"]["schedule"]
LINE = SCHED["dayLine"]
NOTE = STRINGS["app"]["lecturers"]["note"]
DEAD = STRINGS["app"]["lecturers"]["row"]["deadLine"]
STORAGE_KEY = "braude_schedule_builder_v1"  # אין לשנותו — ראו CLAUDE.md

LECTURER = 'ד"ר דנטה-בירון אילה'
RANKED = {"61911": {"הרצאה": [LECTURER]}}
TUTOR = "מר רויטמן אריאל"  # מלמד תרגול ב-11129 בקטלוג הקפוא


def fill(template: str, **values) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


#: "ד"ר דנטה-בירון אילה (הרצאה)" — כמו שהשורה כותבת כל מרצה.
SHOWN = fill(SCHED["lostLecturer"], name=LECTURER, kind="הרצאה")


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


def _patch(**fields):
    """מוסיף/דורס שדות בתשובת ‎/api/solve‎ האמיתית. ‏dead: כל קבוצות ההרצאה של
    61911 מתות (דירוג ישן אחרי שנחסם חלון). ‏reason: ‏first_choices_reason_day
    בכל המערכות."""
    dead = fields.pop("dead", False)
    reason = fields.pop("reason", "keep")

    def handler(route):
        response = route.fetch()
        data = response.json()
        if data.get("schedules"):
            data.update(fields)
            if reason != "keep":
                for sched in data["schedules"]:
                    sched["first_choices_reason_day"] = reason
            if dead:
                lect = (data.get("viability") or {}).get("61911", {}).get("הרצאה", {})
                for gid in list(lect):
                    lect[gid] = {"ok": False, "reason": DEAD}
        route.fulfill(status=response.status, headers={"content-type": "application/json"},
                      body=json.dumps(data, ensure_ascii=False))
    return handler


def _open(browser, server, *, ranked=None, target=3, route=None, width=1440,
          reduced=False, init=None, program=("הנדסת תוכנה", "2")):
    ctx = browser.new_context(
        viewport={"width": width, "height": 1000}, color_scheme="dark",
        reduced_motion="reduce" if reduced else "no-preference",
    )
    page = ctx.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    if init:
        page.add_init_script(init)
    if route:
        page.route("**/api/solve", route)
    page.goto(server)
    page.wait_for_timeout(2000)
    page.select_option("#select-program", program[0])
    page.select_option("#select-year", program[1])
    page.select_option("#select-term", "א")
    page.wait_for_timeout(2000)
    page.click("#step-year-next")
    page.click("#btn-restore-recommended")
    page.wait_for_selector("#schedule-grid .ev", state="attached", timeout=20000)
    page.wait_for_timeout(800)
    page.evaluate(
        """(a) => { const s = JSON.parse(localStorage.getItem(a.key) || '{}');
                    s.ranked = a.ranked; s.targetDays = a.target;
                    localStorage.setItem(a.key, JSON.stringify(s)); }""",
        {"key": STORAGE_KEY, "ranked": RANKED if ranked is None else ranked, "target": target},
    )
    page.reload()
    page.wait_for_selector("#schedule-grid .ev", state="attached", timeout=20000)
    page.wait_for_timeout(2000)
    return ctx, page


def _solve(page):
    return page.evaluate("window.slotwise.getRuntime().solve")


#: מה יש בתיבת הנתונים: סדר הילדים, השורה החדשה, ופריט המרצים בשורת "מה פחות טוב".
SUMMARY = """() => {
  const box = document.getElementById('schedule-summary');
  const line = box.querySelector('.fit-day');
  const add = box.querySelector('.fit-day .day-add');
  const lost = box.querySelector('.fit-lost-item[data-penalty="lecturer"]');
  return {
    classes: [...box.children].map(k => k.className.split(' ')[0]),
    names: line ? line.querySelector('.fit-day-names').textContent : null,
    why: line && line.querySelector('.fit-day-why') ? line.querySelector('.fit-day-why').textContent : null,
    add: add && {text: add.textContent, label: add.getAttribute('aria-label'), title: add.title,
                 tag: add.tagName},
    lostLecturer: lost ? lost.textContent : null,
  };
}"""


def _summary(page):
    return page.evaluate(SUMMARY)


def _wait_target(page, n):
    page.wait_for_function(
        """(n) => window.slotwise.getState().targetDays === n
                  && !window.slotwise.getRuntime().solveBusy
                  && window.slotwise.getRuntime().solve
                  && window.slotwise.getRuntime().solve.target_days === n""",
        arg=n, timeout=20000,
    )
    page.wait_for_timeout(300)


# ==========================================================================
# 1. השורה, על הנתונים האמיתיים
# ==========================================================================
def test_the_line_names_the_lecturer_the_reason_and_the_action(browser, server):
    ctx, pg = _open(browser, server)
    try:
        s = _solve(pg)
        top = s["schedules"][0]
        assert s["first_choices_days"] == 4, s["first_choices_days"]
        assert top["days_count"] == 3 and [m["name"] for m in top["lecturer_misses"]] == [LECTURER]
        got = _summary(pg)
        label = fill(LINE["label"], N=4, names=LECTURER)
        assert got["names"] == fill(LINE["without"], names=SHOWN), got
        assert got["why"] == " · " + LINE["needsDay"], got
        assert got["add"] == {"text": LINE["add"], "label": label, "title": label, "tag": "BUTTON"}, got
        assert pg.errors == [], pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_the_line_sits_under_the_stats_and_the_lecturer_is_not_said_twice(browser, server):
    ctx, pg = _open(browser, server)
    try:
        got = _summary(pg)
        # ‏שבבי הנתונים, השורה, ההסבר (סגור), ואז "מה פחות טוב".
        assert got["classes"][:4] == ["stat-pills", "fit-day", "att-info", "fit-lost"], got["classes"]
        assert got["lostLecturer"] is None, got
        assert LECTURER not in pg.text_content("#schedule-summary .fit-lost")
    finally:
        ctx.close()


def test_the_line_is_plain_text_in_ink_with_the_reason_in_sec(browser, server):
    ctx, pg = _open(browser, server)
    try:
        style = pg.evaluate(
            """() => { const css = (s, p) => getComputedStyle(document.querySelector(s))[p];
                       const root = getComputedStyle(document.documentElement);
                       const probe = (v) => { const d = document.createElement('span');
                         d.style.color = 'var(' + v + ')'; document.body.appendChild(d);
                         const c = getComputedStyle(d).color; d.remove(); return c; };
                       return {names: css('.fit-day-names', 'color'), why: css('.fit-day-why', 'color'),
                               ink: probe('--ink'), sec: probe('--sec'),
                               bg: css('.fit-day', 'backgroundColor'),
                               border: css('.fit-day', 'borderTopStyle')}; }"""
        )
        assert style["names"] == style["ink"] and style["why"] == style["sec"], style
        assert style["bg"] == "rgba(0, 0, 0, 0)" and style["border"] == "none", style
    finally:
        ctx.close()


def test_the_info_button_opens_the_rule_in_place(browser, server):
    ctx, pg = _open(browser, server)
    try:
        info = """() => { const b = document.querySelector('.day-why-btn');
                          const p = document.getElementById('day-why');
                          return {expanded: b.getAttribute('aria-expanded'), controls: b.getAttribute('aria-controls'),
                                  label: b.getAttribute('aria-label'), hidden: p.hidden, text: p.textContent}; }"""
        closed = pg.evaluate(info)
        assert closed["expanded"] == "false" and closed["hidden"] is True, closed
        assert closed["controls"] == "day-why" and closed["label"] == LINE["infoLabel"] == "למה?", closed
        pg.click(".day-why-btn")
        opened = pg.evaluate(info)
        assert opened["expanded"] == "true" and opened["hidden"] is False, opened
        assert opened["text"] == LINE["why"], opened["text"]
        pg.click(".day-why-btn")
        assert pg.evaluate(info)["hidden"] is True
    finally:
        ctx.close()


def test_two_days_say_two_days(browser, server):
    ctx, pg = _open(browser, server, route=_patch(first_choices_days=5))
    try:
        got = _summary(pg)
        assert got["why"] == " · " + fill(LINE["needsDays"], n=2), got
        assert got["add"]["text"] == fill(LINE["addMany"], n=2), got
        assert got["add"]["label"] == fill(LINE["label"], N=5, names=LECTURER), got
        pg.click(".day-why-btn")
        assert pg.text_content("#day-why p") == LINE["why"]
    finally:
        ctx.close()


def test_a_trade_off_shows_the_line_without_a_reason(browser, server):
    """הסיבה נאמרת רק כשהיא נכונה על המרצה שחסר לבדו (השרת מחליט). בלעדיה —
    השמות, הכפתור וה-ⓘ, בלי "· צריך יום לימוד נוסף"."""
    ctx, pg = _open(browser, server, route=_patch(reason=False))
    try:
        got = _summary(pg)
        assert got["names"] == fill(LINE["without"], names=SHOWN), got
        assert got["why"] is None, got
        assert got["add"]["text"] == LINE["add"], got
        assert pg.query_selector(".fit-day .day-why-btn") is not None
        assert got["lostLecturer"] is None, got
        assert pg.text_content(".fit-day") == fill(LINE["without"], names=SHOWN) + LINE["add"] + "ⓘ"
    finally:
        ctx.close()


def test_the_electrical_trade_off_on_real_data(browser, server):
    """‏הנדסת חשמל שנה א׳: גב' זמוסטיאנו (31511 תרגול) נכנסת ב-3 ימים לבדה, אבל רק
    בלי ד"ר גולדוורד (11002 הרצאה). אין סיבה בשורה; הלחיצה מחזירה את שניהם."""
    ranked = {"11002": {"הרצאה": ['ד"ר גולדוורד אלכסנדר']}, "31511": {"תרגול": ["גב' זמוסטיאנו יאנה"]}}
    ctx, pg = _open(browser, server, ranked=ranked, program=("הנדסת חשמל ואלקטרוניקה", "1"))
    try:
        s = _solve(pg)
        top = s["schedules"][0]
        assert s["first_choices_days"] == 4 and top["days_count"] == 3, (s["first_choices_days"], top["days_count"])
        assert top["first_choices_reason_day"] is False, top
        got = _summary(pg)
        her = fill(SCHED["lostLecturer"], name="גב' זמוסטיאנו יאנה", kind="תרגול")
        assert got["names"] == fill(LINE["without"], names=her) and got["why"] is None, got
        pg.click("#schedule-summary .day-add")
        _wait_target(pg, 4)
        assert _solve(pg)["schedules"][0]["lecturer_misses"] == []
    finally:
        ctx.close()


# ==========================================================================
# 2. מתי אין שורה — ואז הכול כמו קודם
# ==========================================================================
def test_no_line_on_an_alternative_whose_days_already_reach_n(browser, server):
    ctx, pg = _open(browser, server)
    try:
        s = _solve(pg)
        n = s["first_choices_days"]
        seen = []
        for rank in range(1, len(s["schedules"]) + 1):
            pg.click(f'#alt-cards [data-rank="{rank}"]')
            pg.wait_for_timeout(400)
            sch = s["schedules"][rank - 1]
            got = _summary(pg)
            should = bool(sch["lecturer_misses"]) and sch["days_count"] < n
            seen.append((rank, sch["days_count"], bool(sch["lecturer_misses"]), got["names"] is not None))
            assert (got["names"] is not None) == should, seen
            if should:
                extra = n - sch["days_count"]
                assert got["add"]["text"] == (LINE["add"] if extra == 1 else fill(LINE["addMany"], n=extra))
                assert got["lostLecturer"] is None, got
            elif sch["lecturer_misses"]:
                assert got["lostLecturer"] is not None, got  # ‏בשורת "מה פחות טוב", כמו קודם
    finally:
        ctx.close()


@pytest.mark.parametrize("n", [3, 2])
def test_no_line_when_n_is_not_above_the_days_or_the_target(browser, server, n):
    ctx, pg = _open(browser, server, route=_patch(first_choices_days=n))
    try:
        got = _summary(pg)
        assert got["names"] is None and got["add"] is None, got
        assert pg.query_selector("#day-why") is None
        assert got["lostLecturer"] == fill(SCHED["lost"]["lecturer"], names=SHOWN), got
    finally:
        ctx.close()


def test_without_n_nothing_changes_from_before(browser, server):
    ctx, pg = _open(browser, server, route=_patch(first_choices_days=None))
    try:
        got = _summary(pg)
        assert got["names"] is None and got["add"] is None, got
        assert "fit-day" not in got["classes"], got["classes"]
        assert got["lostLecturer"] == fill(SCHED["lost"]["lecturer"], names=SHOWN), got
        assert "יום" not in pg.text_content("#schedule-summary .fit-lost").replace("ימי לימוד ארוכים", "")
    finally:
        ctx.close()


def test_a_dead_ranking_gets_the_line_without_a_button(browser, server):
    ctx, pg = _open(browser, server, route=_patch(first_choices_days=None, dead=True))
    try:
        got = _summary(pg)
        assert got["names"] == fill(LINE["without"], names=SHOWN), got
        assert got["why"] == " · " + DEAD, got
        assert got["add"] is None and pg.query_selector(".day-why-btn") is None, got
        assert got["lostLecturer"] is None, got
    finally:
        ctx.close()


def test_the_button_and_the_explanation_are_not_printed(browser, server):
    ctx, pg = _open(browser, server)
    try:
        pg.click(".day-why-btn")
        pg.emulate_media(media="print")
        shown = pg.evaluate(
            """() => ['.day-add-wrap', '#day-why'].map(s =>
                     getComputedStyle(document.querySelector(s)).display)"""
        )
        assert shown == ["none", "none"], shown
    finally:
        ctx.close()


# ==========================================================================
# 3. הלחיצה, הביטול והתנועה
# ==========================================================================
def test_the_tap_raises_the_target_and_brings_the_lecturer_back(browser, server):
    ctx, pg = _open(browser, server)
    try:
        pg.click("#schedule-summary .day-add")
        _wait_target(pg, 4)
        state = pg.evaluate("window.slotwise.getState()")
        top = _solve(pg)["schedules"][0]
        assert state["targetDays"] == 4 and state["activeSchedule"] == 0, state
        assert top["lecturer_misses"] == [] and top["lecturer_hits"] == 1, top["lecturer_ranks"]
        assert top["days_count"] == 4
        got = _summary(pg)
        assert got["names"] is None and got["lostLecturer"] is None, got
        assert pg.text_content("#schedule-summary .fit-undo") == fill(LINE["undo"], old=3)
        # הביטול מחזיר את היעד הקודם, והשורה חוזרת.
        pg.click("#schedule-summary .fit-undo button")
        _wait_target(pg, 3)
        assert pg.query_selector("#schedule-summary .fit-undo") is None
        assert pg.query_selector("#schedule-summary .day-add") is not None
        assert pg.errors == [], pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_the_undo_goes_away_on_the_next_settings_change(browser, server):
    ctx, pg = _open(browser, server)
    try:
        pg.click("#schedule-summary .day-add")
        _wait_target(pg, 4)
        assert pg.query_selector("#schedule-summary .fit-undo") is not None
        # ‏שינוי שאינו היעד — "בלי יום ו׳" — הוא "השינוי הבא", והביטול נעלם.
        pg.evaluate("document.getElementById('chk-forbid-friday').click()")
        pg.wait_for_function("window.slotwise.getState().forbidFriday === true")
        pg.wait_for_function("!window.slotwise.getRuntime().solveBusy", timeout=20000)
        pg.wait_for_timeout(300)
        assert pg.query_selector("#schedule-summary .fit-undo") is None
    finally:
        ctx.close()


def test_the_grid_moves_and_only_a_block_without_a_before_lands(browser, server):
    """הבלוקים נשמרים לפי שיעור (קורס וסוג), כמו בהחלפת חלופה: ההרצאה של 61911
    עוברת מיום א׳ ליום ג׳ — זזה. בלוק שלא היה על הרשת לפני הלחיצה נוחת."""
    record = """
      window.__anims = []; window.__before = new Set();
      const orig = Element.prototype.animate;
      Element.prototype.animate = function (k, o) {
        const a = orig.call(this, k, o);
        const el = this;
        setTimeout(() => window.__anims.push([a.id || '', window.__before.has(el)]), 0);
        return a;
      };"""
    ctx, pg = _open(browser, server, init=record)
    try:
        pg.evaluate("""() => { window.__anims = [];
                               window.__before = new Set(document.querySelectorAll('#schedule-grid .ev')); }""")
        pg.click("#schedule-summary .day-add")
        _wait_target(pg, 4)
        anims = pg.evaluate("window.__anims")
        moves = [old for kind, old in anims if kind == "ev-move"]
        lands = [old for kind, old in anims if kind == "ev-land"]
        assert moves and all(moves), anims
        assert not any(lands), anims  # ‏נחיתה רק לבלוק חדש
        new_blocks = pg.evaluate(
            "[...document.querySelectorAll('#schedule-grid .ev')].filter(b => !window.__before.has(b)).length")
        assert len(lands) == new_blocks, (lands, new_blocks)
        # ‏הגלולה "N מתוך N" קפצה, כמו עיגול דירוג.
        assert pg.evaluate("window.slotwise.getRuntime().hitsPop !== null")
    finally:
        ctx.close()


def test_reduced_motion_makes_it_instant(browser, server):
    record = """
      window.__anims = [];
      const orig = Element.prototype.animate;
      Element.prototype.animate = function (k, o) {
        window.__anims.push(this.className); return orig.call(this, k, o); };"""
    ctx, pg = _open(browser, server, reduced=True, init=record)
    try:
        pg.evaluate("window.__anims = []")
        pg.click("#schedule-summary .day-add")
        _wait_target(pg, 4)
        assert pg.evaluate("window.__anims") == []
        dur = pg.evaluate(
            """() => { const p = document.querySelector('#schedule-summary [data-stat="lecturers"]');
                       return parseFloat(getComputedStyle(p).animationDuration); }"""
        )
        assert dur < 0.01, dur
    finally:
        ctx.close()


def test_the_button_pops_once_when_it_first_appears(browser, server):
    record = """
      window.__pops = [];
      new MutationObserver(() => {
        const b = document.querySelector('.day-add.is-pop');
        if (b && !b.__seen) { b.__seen = true; window.__pops.push(performance.now()); }
      }).observe(document, {subtree: true, childList: true});"""
    ctx, pg = _open(browser, server, init=record)
    try:
        first = pg.evaluate("window.__pops.slice()")
        assert first, "הכפתור לא קפץ כשהופיע לראשונה"
        # ‏ציורים נוספים (פתיחה וסגירה של ה-ⓘ) אינם מקפיצים שוב.
        pg.click(".day-why-btn")
        pg.click(".day-why-btn")
        pg.wait_for_timeout(300)
        later = [t for t in pg.evaluate("window.__pops") if t > first[0] + 250]
        assert later == [], later
        assert "is-pop" not in pg.get_attribute(".day-add", "class")
    finally:
        ctx.close()


# ==========================================================================
# 4. שלב המרצים: הסדר נאמר מראש
# ==========================================================================
def _note(pg):
    for sel in ("#step-courses-next", "#step-days-next"):
        if pg.is_visible(sel):
            pg.click(sel)
            pg.wait_for_timeout(500)
    return pg.text_content("#lecturers-note")


@pytest.mark.parametrize(
    "ranked,want",
    [
        ({}, NOTE["skip"]),
        (RANKED, fill(NOTE["summary"], bits=NOTE["rankedOne"])),
        ({**RANKED, "11129": {"תרגול": [TUTOR]}},
         fill(NOTE["summary"], bits=fill(NOTE["ranked"], count=2))),
    ],
    ids=["none", "one", "two"],
)
def test_the_lecturers_note_says_the_days_come_first(browser, server, ranked, want):
    ctx, pg = _open(browser, server, ranked=ranked)
    try:
        assert _note(pg) == want
    finally:
        ctx.close()


def test_the_copy_is_the_approved_copy():
    assert NOTE["rankedOne"] == "מרצה אחד מדורג"
    assert fill(NOTE["summary"], bits=NOTE["rankedOne"]) == (
        "מרצה אחד מדורג · מרצה שדורש יום נוסף ייכנס רק אם תעלו את יעד הימים."
    )
    assert NOTE["skip"] == "אפשר לדלג על השלב הזה — בלי דירוג, המערכת נבחרת לפי הימים והחלונות."
    assert fill(LINE["without"], names="X (הרצאה), Y (תרגול)") == "בלי X (הרצאה), Y (תרגול)"
    assert LINE["needsDay"] == "צריך יום לימוד נוסף"
    assert fill(LINE["needsDays"], n=2) == "צריך עוד 2 ימי לימוד"
    assert LINE["add"] == "הוספת יום" and fill(LINE["addMany"], n=2) == "הוספת 2 ימים"
    assert LINE["label"] == "להעלות את יעד הימים ל-{N} ולקבל את {names}"
    assert LINE["infoLabel"] == "למה?"
    assert LINE["why"] == "יעד הימים קודם למרצים שדירגת, ולכן מרצה שדורש יום נוסף נכנס רק אחרי שמעלים את היעד."
    assert LINE["undo"] == "חזרה ל-{old} ימים"
    # ‏אין "+" בתוויות, ולכן גם אין תו כיווניות.
    assert not any("‏" in v or "‎" in v for v in LINE.values())
