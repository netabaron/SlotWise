"""הדירוג הוא הפקד היחיד, ודף התוצאה הולך לפי סדר העדיפויות (2026-10-09).

‏docs/DESIGN.md → Lecturers ("Ranking is the only control", "How a ranking
chooses", "Saved pins") ו-Results page, פריט 4. נבדק כאן בדפדפן אמיתי:

* בשלב המרצים אין פקד נעיצה בכלל;
* נעיצה שנשמרה לפני השינוי הופכת לדירוג 1 של המרצה, בסוג שלה, עם טוסט אחד;
* רשימה שטוחה שנשמרה נשארת כפי שהיא עד שהקורס נערך, ואז נכתבת לפי סוג;
* עם יעד ימים שאי אפשר לעמוד בו ועם דירוג בשני סוגים, המערכות, השבבים
  והמשפט "מה פחות טוב" הולכים לפי הסדר: ימים, מרצים, חפיפות, ורק אז השאר;
* תווית ההבדל "ההתאמה הגבוהה ביותר" נקבעת לפי המקום בסדר ולא לפי ניקוד.

הנתונים הם של הנדסת תוכנה שנה ג׳ סמסטר א׳, הקורסים המומלצים.
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
STORAGE_KEY = "braude_schedule_builder_v1"  # אין לשנותו — ראו CLAUDE.md

AUTOMATA = "61759"
LECTURE, TUTORIAL = "הרצאה", "תרגול"

#: המקרה שנמדד בהצעה (2026-10-09, "case 1"): הרצאת 61832 של ד"ר יהלום ותרגול
#: ‏61756 של מר זלדנר בדירוג 1. בסדר הישן המובילה ויתרה על ההרצאה.
CASE_1 = {"61832": {LECTURE: ['ד"ר יהלום אורלי']}, "61756": {TUTORIAL: ["מר זלדנר איליה"]}}

#: אוסף כל טקסט של טוסט, גם אחרי שהטוסט נעלם.
TOAST_SPY = """
window.__toasts = [];
new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => {
  if (n.nodeType === 1 && n.classList && n.classList.contains('toast'))
    window.__toasts.push(n.textContent.trim());
}))).observe(document, {childList: true, subtree: true});
"""


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


def _open(browser, server, route=None):
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000}, color_scheme="light")
    ctx.add_init_script(TOAST_SPY)
    page = ctx.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    if route:
        page.route("**/api/solve", route)
    page.goto(server)
    page.wait_for_timeout(2500)
    page.select_option("#select-program", "הנדסת תוכנה")
    page.select_option("#select-year", "3")
    page.select_option("#select-term", "א")
    page.wait_for_timeout(2500)
    page.click("#step-year-next")
    page.click("#btn-restore-recommended")
    page.wait_for_selector("#schedule-grid .ev", timeout=20000)
    page.wait_for_timeout(800)
    return ctx, page


def _seed(page, **fields):
    """כותב שדות למצב השמור וטוען מחדש — כמו סטודנט/ית שחוזר/ת."""
    page.evaluate(
        """(a) => { const s = JSON.parse(localStorage.getItem(a.key) || '{}');
                    Object.assign(s, a.fields); localStorage.setItem(a.key, JSON.stringify(s)); }""",
        {"key": STORAGE_KEY, "fields": fields},
    )
    page.reload()
    page.wait_for_selector("#schedule-grid .ev", timeout=20000)
    page.wait_for_timeout(1500)


def _state(page):
    return page.evaluate("() => window.slotwise.getState()")


def _schedules(page):
    return page.evaluate("() => window.slotwise.getRuntime().solve.schedules")


# --------------------------------------------------------------------------
# 1. אין פקד נעיצה
# --------------------------------------------------------------------------
def test_the_lecturers_step_has_no_pin_control(browser, server):
    ctx, pg = _open(browser, server)
    try:
        got = pg.evaluate(
            """() => ({pins: document.querySelectorAll('.pin-btn, .cell-pin, .th-pin, tr.is-pinned').length,
                       heads: [...document.querySelectorAll('#lecturer-courses thead th')]
                                .map(th => th.textContent.trim()),
                       text: document.getElementById('step-lecturers').textContent})"""
        )
        assert got["pins"] == 0, got
        assert "נעיצה" not in got["heads"], got["heads"]
        assert "נעוץ" not in got["text"] and "נעיצ" not in got["text"], got["text"][:300]
        assert pg.errors == [], pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()


# --------------------------------------------------------------------------
# 2. נעיצה שמורה הופכת לדירוג 1, עם טוסט אחד
# --------------------------------------------------------------------------
def test_a_saved_pin_becomes_rank_one_with_one_toast(browser, server):
    ctx, pg = _open(browser, server)
    try:
        group = pg.evaluate(
            """(code) => { const s = window.slotwise.getRuntime().solve.schedules[0];
                           return s.picks.find(p => p.code === code && p.kind === 'הרצאה'); }""",
            AUTOMATA,
        )
        _seed(pg, pinned={AUTOMATA: {LECTURE: group["group_id"]}}, ranked={})
        state = _state(pg)
        toasts = pg.evaluate("() => window.__toasts")
        # ועוד טעינה: הנעיצה כבר נמחקה, ולכן אין טוסט שני.
        pg.reload()
        pg.wait_for_selector("#schedule-grid .ev", timeout=20000)
        pg.wait_for_timeout(1500)
        again = pg.evaluate("() => window.__toasts")
        sent = _state(pg)
    finally:
        ctx.close()
    assert state["pinned"] == {}, state["pinned"]
    assert state["ranked"][AUTOMATA] == {LECTURE: [group["lecturer"]]}, state["ranked"]
    converted = STRINGS["app"]["lecturers"]["pinsConverted"]
    assert toasts.count(converted) == 1, toasts
    assert converted not in again, again
    assert sent["ranked"][AUTOMATA] == {LECTURE: [group["lecturer"]]}


# --------------------------------------------------------------------------
# 3. רשימה שטוחה נשארת עד שהקורס נערך
# --------------------------------------------------------------------------
RANK_ROWS = """(code) => { const c = document.querySelector('[data-fk="lect-course-' + code + '"]').closest('.lect-course');
  return [...c.querySelectorAll('tbody tr')].map(tr => ({
    lect: tr.querySelector('.cell-lect > span').textContent, kind: tr.cells[2].textContent.trim(),
    rank: tr.querySelector('.rank-circle').textContent})); }"""


def test_a_saved_flat_ranking_is_read_per_kind_and_rewritten_on_edit(browser, server):
    ctx, pg = _open(browser, server)
    try:
        name = pg.evaluate(
            """(code) => window.slotwise.getRuntime().solve.schedules[0].picks
                          .find(p => p.code === code && p.kind === 'הרצאה').lecturer""",
            AUTOMATA,
        )
        _seed(pg, ranked={AUTOMATA: [name]})
        kept = _state(pg)["ranked"][AUTOMATA]
        pg.evaluate("() => document.getElementById('step-lecturers').scrollIntoView()")
        head = pg.locator(f'[data-fk="lect-course-{AUTOMATA}"]')
        if head.get_attribute("aria-expanded") != "true":
            pg.evaluate(f"() => document.querySelector('[data-fk=\"lect-course-{AUTOMATA}\"]').click()")
            pg.wait_for_timeout(400)
        rows = pg.evaluate(RANK_ROWS, AUTOMATA)
        # עריכה: מסירים את המרצה מההרצאה בלבד.
        idx = next(i for i, r in enumerate(rows) if r["lect"] == name and r["kind"] == LECTURE)
        pg.evaluate(
            """(a) => document.querySelector('[data-fk="lect-course-' + a.code + '"]').closest('.lect-course')
                       .querySelectorAll('tbody tr')[a.i].click()""",
            {"code": AUTOMATA, "i": idx},
        )
        pg.wait_for_timeout(800)
        edited = _state(pg)["ranked"].get(AUTOMATA)
    finally:
        ctx.close()
    assert kept == [name], kept
    mine = [r for r in rows if r["lect"] == name]
    assert {r["kind"] for r in mine} >= {LECTURE}, rows
    assert all(r["rank"] == "1" for r in mine), rows
    # ‏נכתב לפי סוג: ההרצאה ירדה, וכל סוג אחר שהמרצה מלמד נשאר.
    taught = {r["kind"] for r in mine} - {LECTURE}
    assert edited == ({k: [name] for k in taught} or None), edited


# --------------------------------------------------------------------------
# 4. יעד ימים, דירוג בשני סוגים — הכול לפי סדר העדיפויות
# --------------------------------------------------------------------------
def _lecturer_key(sch):
    ranks = [r["rank"] for r in sch["lecturer_ranks"]]
    lectures = [r["rank"] for r in sch["lecturer_ranks"] if r["kind"] in (LECTURE, 'שו"ת')]
    deepest = max((len(r["names"]) for r in sch["lecturer_ranks"]), default=0)
    key = []
    for level in range(1, deepest + 1):
        key += [-ranks.count(level), -lectures.count(level)]
    return key


SUMMARY = """() => {
  const pills = [...document.querySelectorAll('#schedule-summary .stat-pill')]
    .map(p => [p.dataset.stat, p.textContent.trim()]);
  const line = document.querySelector('#schedule-summary .fit-lost');
  return {pills: pills,
          items: line ? [...line.querySelectorAll('.fit-lost-item')].map(i => [i.dataset.penalty, i.textContent]) : []};
}"""


def test_with_a_days_target_the_page_follows_the_priority_order(browser, server):
    """יעד 3 ימים — מתחת למינימום של 4 — ודירוג של הרצאה ותרגול.

    בסדר הישן המובילה ויתרה על הרצאת ד"ר יהלום תמורת שלוש שעות פחות אחרי
    14:00 (נמדד 2026-10-09). עכשיו המובילה מכבדת את שני הדירוגים, ובכל חלופה
    המשפט "מה פחות טוב" נפתח ב"יותר ימים ממה שביקשת", אחריו המרצים, ורק אז
    השאר — מהכבד לקל.
    """
    ctx, pg = _open(browser, server)
    try:
        pg.click("#step-courses-next")
        pg.click('.day-btn[data-days="3"]')
        pg.wait_for_timeout(1500)
        _seed(pg, ranked=CASE_1)
        sch = _schedules(pg)
        seen = []
        for rank in range(1, len(sch) + 1):
            pg.click(f'#alt-cards [data-rank="{rank}"]')
            pg.wait_for_timeout(500)
            seen.append(pg.evaluate(SUMMARY))
        assert pg.errors == [], pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()

    assert len(sch) == 5
    # המובילה: שני הדירוגים מכובדים — בניגוד לסדר הישן.
    assert (sch[0]["lecturer_hits"], sch[0]["lecturer_total"]) == (2, 2), sch[0]["lecturer_ranks"]
    # הסדר: ימים מעל היעד, ואז המרצים.
    keys = [(s["days_over_target"], _lecturer_key(s)) for s in sch]
    assert keys == sorted(keys), keys
    assert all(s["days_over_target"] >= 1 for s in sch), [s["days_over_target"] for s in sch]
    assert any(s["lecturer_hits"] < s["lecturer_total"] for s in sch), "צריך חלופה שחסר בה מרצה"

    for i, (s, got) in enumerate(zip(sch, seen)):
        stats = [k for k, _ in got["pills"]]
        # שבב ההתאמה רק לראשונה, ובלי אחוז.
        assert ("fit" in stats) == (i == 0), (i, stats)
        assert not any("%" in text for _, text in got["pills"]), got["pills"]
        lect = dict(got["pills"])["lecturers"]
        assert lect == fill(SCHED["lecturersHits"], hits=s["lecturer_hits"], total=s["lecturer_total"])

        keys = [k for k, _ in got["items"]]
        assert keys[0] == "days", (i, keys)
        rest = keys[1:]
        if s["lecturer_misses"]:
            assert rest[0] == "lecturer", (i, keys)
            names = [fill(SCHED["lostLecturer"], name=m["name"], kind=m["kind"]) for m in s["lecturer_misses"]]
            want = fill(SCHED["lost"]["lecturer" if len(names) == 1 else "lecturers"], names=", ".join(names))
            assert got["items"][1][1] == want, got["items"]
            rest = rest[1:]
        else:
            assert "lecturer" not in rest, (i, keys)
        # ואז החפיפות (אם יש), ואז השאר מהכבד לקל.
        if "soft_conflict" in rest:
            assert rest[0] == "soft_conflict", (i, keys)
            rest = rest[1:]
        sizes = [abs(s["breakdown"][k]) for k in rest]
        assert sizes == sorted(sizes, reverse=True), (i, rest, sizes)


# --------------------------------------------------------------------------
# 5. "ההתאמה הגבוהה ביותר" היא המקום בסדר, לא ניקוד
# --------------------------------------------------------------------------
def _five_copies_lowest_first(route):
    """חמש העתקות של המערכת הראשונה — אותן עובדות בדיוק — כשלראשונה הניקוד
    הנמוך מכולן. אחוז מהניקוד היה נותן את התווית לאחרת; המקום בסדר נותן
    אותה לראשונה."""
    response = route.fetch()
    data = response.json()
    first = data["schedules"][0]
    copies = []
    for i in range(5):
        copy = json.loads(json.dumps(first))
        copy["score"] = -999.0 if i == 0 else 0.0
        copies.append(copy)
    data["schedules"] = copies
    route.fulfill(status=response.status, headers={"content-type": "application/json"},
                  body=json.dumps(data, ensure_ascii=False))


def test_the_best_label_follows_the_position_not_the_score(browser, server):
    ctx, pg = _open(browser, server, route=_five_copies_lowest_first)
    try:
        labels = pg.evaluate(
            """() => [...document.querySelectorAll('#alt-cards .alt-card')]
                 .sort((a, b) => a.dataset.rank - b.dataset.rank)
                 .map(c => c.querySelector('.alt-card-label').textContent)"""
        )
        fit = pg.evaluate(
            "() => (document.querySelector('#schedule-summary .stat-pill.fit') || {}).textContent || null"
        )
        assert pg.errors == [], pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()
    best = STRINGS["app"]["compare"]["bestOverall"]
    assert labels[0] == best, labels
    assert all(label != best for label in labels[1:]), labels
    assert fit and fit.strip() == best, fit
