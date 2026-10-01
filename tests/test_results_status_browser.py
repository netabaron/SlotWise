"""דף התוצאה: מצב הקבוצה, משפט "מה פחות טוב", ובלי שורת הספירה (2026-10-01/02).

DESIGN.md, "Results page", פריטים 4 ו-5:

* **קבוצה מלאה** נראית בדף התוצאה, ולא רק בשלב המרצים: בסוף השורה השלישית
  של הבלוק ("<מרצה> · <חדר> · קבוצה מלאה") ובשורת "ללא מועד קבוע". "מלאה"
  נקבע מ-``status_note`` עצמו (טקסט ה-span של הידיעון, בשדה משלו), בהשוואה
  לערך המדויק שב-app.js, ולא בחיפוש ביטויים בשם המרצה או ב-``note``
  (CLAUDE.md, ‏_visible_text).
* **שני המצבים האחרים** — "מיועד לחוזרים" ו"בקורס זה קיימת רשימת המתנה" — הם
  מידע ולא סיבה שקבוצה אינה זמינה: אין להם נוסח קצר ואין סימון על הבלוק או
  בשורת "ללא מועד קבוע". הם מופיעים רק בפאנל הפרטים, במילים של הידיעון —
  כמו כל מצב (2026-10-02).
* **"מה פחות טוב במערכת הזו: …"** במקום "מה הוריד מההתאמה: …" במונחי הניקוד.
* **בלי "מוצגות 5 המערכות המובילות"** מתחת לרשת.

**אף בדיקה כאן אינה תלויה ב-data/db המקומי** (DEFERRED.md). צד השרת נבדק עם
הקטלוג הקפוא; צד הדף — בתשובות ‎/api/solve‎ שמיורטות ומקבלות מצב ידוע, כי
אילו קבוצות מלאות תלוי בקטלוג.
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

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
SCHED = STRINGS["app"]["schedule"]
GRID = STRINGS["app"]["grid"]
APP_JS = (ROOT / "src" / "web" / "static" / "app.js").read_text(encoding="utf-8")
STORAGE_KEY = "braude_schedule_builder_v1"  # אין לשנותו — ראו CLAUDE.md

#: הערך שהידיעון כותב לקבוצה מלאה — כפי שהוא מוגדר ב-app.js.
FULL = re.search(r'var FULL_STATUS = "([^"]+)";', APP_JS).group(1)
#: שני המצבים האחרים שבקטלוג. הקוד אינו משווה אליהם; כאן הם רק קלט מיורט.
OTHER = {"repeaters": "מיועד לחוזרים", "waitlist": "בקורס זה קיימת רשימת המתנה"}
VALUE = dict(OTHER, full=FULL)

#: בקטלוג הקפוא: 11061 (אנגלית מתקדמים ב'), שתי קבוצות שו"ת בסמסטר א',
#: אחת מלאה ואחת לא — ולשתיהן מפגשים.
FULL_CODE, FULL_KIND = "11061", 'שו"ת'
FULL_GROUP, OPEN_GROUP = "271020210", "271420310"


def fill(template: str, **values) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


# ==========================================================================
# 1. השרת: ה-pick נושא את status_note
# ==========================================================================
@pytest.fixture()
def client():
    return create_app({"allow_network": False}).test_client()


@pytest.mark.parametrize("group,want", [(FULL_GROUP, FULL), (OPEN_GROUP, "")])
def test_a_solve_pick_carries_the_group_status(client, group, want):
    res = client.post(
        "/api/solve",
        json={"codes": [FULL_CODE], "semester": "א", "pinned": {FULL_CODE: {FULL_KIND: group}}},
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    picks = res.get_json()["schedules"][0]["picks"]
    pick = next(p for p in picks if p["group_id"] == group)
    assert pick["status_note"] == want, pick
    # ‏note נשאר note: המצב אינו מוזרק אליו (attendance_info סורק אותו).
    assert FULL not in (pick.get("note") or ""), pick


def test_the_full_status_in_app_js_is_one_the_catalog_uses():
    """אם הידיעון ישנה את הנוסח, ההשוואה ב-app.js תפסיק להתאים בשקט. הבדיקה
    הזו נכשלת קודם: הנוסח שב-app.js חייב להופיע כ-status_note בקטלוג שבמאגר."""
    seen = set()
    for line in (ROOT / "data" / "catalog" / "catalog.jsonl").read_text(encoding="utf-8").splitlines():
        for g in json.loads(line).get("groups", []):
            seen.add(g.get("status_note", ""))
    assert FULL in seen, sorted(seen)


# ==========================================================================
# 2. הדף
# ==========================================================================
sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402


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
    def handler(route):
        response = route.fetch()
        data = response.json()
        if data.get("schedules"):
            mutate(data["schedules"])
        route.fulfill(
            status=response.status,
            headers={"content-type": "application/json"},
            body=json.dumps(data, ensure_ascii=False),
        )
    return handler


def _statuses(by_code):
    """בכל המערכות: מנקה כל מצב, ואז נותן לכל הרכיבים של כל קוד ב-by_code את
    המצב שלו (הערך המלא של הידיעון)."""
    def mutate(schedules):
        for sch in schedules:
            for p in sch["picks"]:
                p["status_note"] = by_code.get(p["code"], "")
    return mutate


def _open(browser, server, mutate=None, extra_codes=(), ranked=None, width=1440):
    ctx = browser.new_context(viewport={"width": width, "height": 1000}, color_scheme="light")
    page = ctx.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    if mutate:
        page.route("**/api/solve", _mutating(mutate))
    page.goto(server)
    page.wait_for_timeout(2500)
    page.select_option("#select-program", "הנדסת תוכנה")
    page.select_option("#select-year", "3")
    page.select_option("#select-term", "א")
    page.wait_for_timeout(2500)
    page.click("#btn-restore-recommended")
    page.wait_for_selector("#schedule-grid .ev", timeout=20000)
    if extra_codes or ranked is not None:
        page.evaluate(
            """(a) => { const s = JSON.parse(localStorage.getItem(a.key) || '{}');
                        s.codes = (s.codes || []).concat(a.codes);
                        if (a.ranked) s.ranked = a.ranked;
                        localStorage.setItem(a.key, JSON.stringify(s)); }""",
            {"key": STORAGE_KEY, "codes": list(extra_codes), "ranked": ranked},
        )
        page.reload()
        page.wait_for_selector("#schedule-grid .ev", timeout=20000)
    page.wait_for_function(
        "() => !!document.getElementById('schedule-grid').style.getPropertyValue('--slot-h')",
        timeout=15000,
    )
    page.wait_for_timeout(700)
    return ctx, page


BLOCKS = """() => [...document.querySelectorAll('#schedule-grid .ev')].map(e => {
  const who = e.querySelector(':scope > .ev-who');
  return {code: e.dataset.code, who: who ? who.textContent : '',
          full: !!e.querySelector('.ev-who .ev-full'), label: e.getAttribute('aria-label'),
          over: e.scrollHeight - e.clientHeight};
})"""

FIT = """() => {
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


def test_only_a_full_group_is_marked_and_the_lines_still_fit(browser, server):
    """שלושה קורסים, שלושה מצבים: רק הבלוקים של הקבוצה המלאה מסתיימים ב-"קבוצה
    מלאה". "מיועד לחוזרים" ו"רשימת המתנה" אינם מסמנים את הבלוק בשום צורה —
    לא בנוסח קצר, לא בטקסט של הידיעון. שלוש השורות עדיין נכנסות."""
    by_code = {"61756": VALUE["full"], "61759": VALUE["repeaters"], "62027": VALUE["waitlist"]}
    ctx, pg = _open(browser, server, mutate=_statuses(by_code))
    try:
        rows = pg.evaluate(BLOCKS)
        status = " · " + GRID["groupFull"]
        full = [r for r in rows if r["full"]]
        assert full and {r["code"] for r in full} == {"61756"}, full
        for r in full:
            assert r["who"].endswith(status), r
            assert GRID["groupFull"] in r["label"], r
        unmarked = ["לחוזרים", "רשימת המתנה", OTHER["repeaters"], OTHER["waitlist"]]
        for r in rows:
            if not r["full"]:
                assert GRID["groupFull"] not in r["who"], r
            assert not any(word in r["who"] or word in r["label"] for word in unmarked), r
            assert r["over"] <= 0, r
        fit = pg.evaluate(FIT)
        assert fit["at"] == 0 and (fit["below"] > 0 or fit["slot"] <= 12), fit
        assert pg.errors == [], pg.errors  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_an_unknown_status_marks_nothing_but_shows_in_the_panel(browser, server):
    """מצב שהידיעון יכתוב בעתיד אינו מסמן את הבלוק — רק "מלאה" מסמן — והפאנל
    מציג אותו כפי שהידיעון כתב."""
    other = "מצב שהידיעון עוד לא כתב"
    ctx, pg = _open(browser, server, mutate=_statuses({"61757": other}))
    try:
        rows = pg.evaluate(BLOCKS)
        assert not any(r["full"] or other in r["who"] for r in rows), rows
        pg.click('#schedule-grid .ev[data-code="61757"] >> nth=0')
        pg.wait_for_timeout(400)
        text = pg.evaluate("document.getElementById('meeting-detail-body').textContent")
        assert STRINGS["app"]["detail"]["status"] in text and other in text, text
    finally:
        ctx.close()


@pytest.mark.parametrize("key", ["full", "repeaters", "waitlist"])
def test_the_details_panel_shows_every_status_in_the_yedions_words(browser, server, key):
    ctx, pg = _open(browser, server, mutate=_statuses({"61756": VALUE[key]}))
    try:
        pg.click('#schedule-grid .ev[data-code="61756"] >> nth=0')
        pg.wait_for_timeout(400)
        got = pg.evaluate(
            """() => ({hidden: document.getElementById('meeting-detail').hidden,
                       dts: [...document.querySelectorAll('#meeting-detail-body dt')].map(e => e.textContent),
                       dds: [...document.querySelectorAll('#meeting-detail-body dd')].map(e => e.textContent)})"""
        )
        assert not got["hidden"], got
        i = got["dts"].index(STRINGS["app"]["detail"]["status"])
        assert got["dds"][i] == VALUE[key], got
    finally:
        ctx.close()


@pytest.mark.parametrize("key", ["full", "repeaters", "waitlist"])
def test_the_no_fixed_time_line_says_full_and_only_full(browser, server, key):
    """‏61998 (פרויקט מסכם שלב א') אין לו מועד קבוע בשום קטלוג; כאן לקבוצתו
    מצב. רק "מלאה" נאמר בשורה; שני האחרים אינם."""
    ctx, pg = _open(browser, server, mutate=_statuses({"61998": VALUE[key]}), extra_codes=("61998",))
    try:
        got = pg.evaluate(
            """() => { const sch = window.slotwise.getRuntime().solve.schedules[window.slotwise.getState().activeSchedule];
                       const p = sch.picks.find(x => x.code === '61998');
                       return {pick: p, text: document.getElementById('schedule-unscheduled').textContent.trim()}; }"""
        )
        p = got["pick"]
        assert p and not p["meetings"] and p["status_note"] == VALUE[key], p
        credits = fill(STRINGS["app"]["credits"]["withUnit"],
                       value=int(p["credits"]) if float(p["credits"]).is_integer() else p["credits"])
        item = fill(GRID["unscheduledItem"], name=p["name"], kind=p["kind"], credits=credits)
        want = fill(GRID["unscheduledFull"], item=item, status=GRID["groupFull"]) if key == "full" else item
        # ‏השורה יכולה למנות עוד קורס בלי מועד (בקטלוג שבמאגר 11069 כזה). הפריט
        # של 61998 הוא בדיוק want — עם "קבוצה מלאה" רק כשהמצב הוא "מלאה".
        head = fill(GRID["unscheduled"], list="")
        assert got["text"].startswith(head), got["text"]
        items = got["text"][len(head):]
        assert want in items, (want, got["text"])
        if key != "full":
            for word in ("לחוזרים", "רשימת המתנה", VALUE[key], GRID["groupFull"]):
                assert word not in item and (item + " · " + word) not in items, (word, got["text"])
    finally:
        ctx.close()


# ==========================================================================
# 3. "מה פחות טוב במערכת הזו"
# ==========================================================================
def _line(page):
    return page.evaluate(
        """() => { const p = document.querySelector('#schedule-summary .fit-lost');
                   return p ? {text: p.textContent,
                               items: [...p.querySelectorAll('.fit-lost-item')].map(i => [i.dataset.penalty, i.textContent])}
                            : null; }"""
    )


def test_the_line_is_one_plain_sentence_on_the_top_schedule(browser, server):
    ctx, pg = _open(browser, server)
    try:
        assert pg.evaluate("window.slotwise.getState().activeSchedule") == 0
        line = _line(pg)
        sch = pg.evaluate("window.slotwise.getRuntime().solve.schedules[0]")
        negative = [k for k, v in sch["breakdown"].items() if v < 0 and round(v, 1) != 0]
        if not negative:
            assert line is None
            return
        head = SCHED["penaltiesLine"].split("{")[0]
        assert head == "מה פחות טוב במערכת הזו: ", head
        assert line["text"].startswith(head), line
        for key, text in line["items"]:
            assert text == SCHED["lost"][key], (key, text)
        # הנוסח הישן, במונחי הניקוד, אינו מופיע.
        for old in ("מה הוריד", "חסר:", "סיום מאוחר", "רצף שיעורים", "המתנה בין שיעורים"):
            assert old not in line["text"], (old, line["text"])
    finally:
        ctx.close()


@pytest.mark.parametrize("names", [["מרצה שאינו בקטלוג"], ["מרצה שאינו בקטלוג", "מרצה אחר שאינו בקטלוג"]])
def test_missing_preferred_lecturers_are_named(browser, server, names):
    codes = ["61757", "62027"][: len(names)]
    ranked = {code: [name] for code, name in zip(codes, names)}
    ctx, pg = _open(browser, server, ranked=ranked)
    try:
        line = _line(pg)
        key = "lecturer" if len(names) == 1 else "lecturers"
        want = fill(SCHED["lost"][key], names=", ".join(names))
        assert line and ["lecturer", want] in line["items"], (want, line)
    finally:
        ctx.close()


# ==========================================================================
# 4. בלי שורת הספירה מתחת לרשת
# ==========================================================================
def test_no_count_line_under_the_timetable(browser, server):
    ctx, pg = _open(browser, server)
    try:
        note = pg.evaluate("document.getElementById('schedule-note').textContent.trim()")
        assert note == "", note
        assert "noteShown" not in SCHED
        assert "המערכות המובילות" not in pg.evaluate("document.body.innerText").replace(
            pg.evaluate("document.getElementById('alt-title').textContent"), "")
    finally:
        ctx.close()
