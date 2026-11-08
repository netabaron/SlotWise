"""‏"האם לאפשר חפיפה?" — שאלה אחת מתחת לתיבת החפיפות, במקום מתג חובת
נוכחות בכל קורס.

* ‏state.overlaps: ‏null (טרם נענתה) / "allow" / "none", נשמר ב-localStorage.
* מוצגת כשהמערכת שנבנתה חופפת, או כשהשאלה כבר נענתה — כדי שתמיד אפשר
  יהיה לשנות. אחרת מוסתרת.
* לפני תשובה שני הכפתורים משניים ואף אחד אינו לחוץ; אחריה הנבחר ראשי,
  עם ✓ ו-‎aria-pressed="true"‎, והשאלה נשארת.
* בטלפון: כותרת, הסבר, ושני כפתורים ברוחב שווה בשורה אחת. בפריסה הרחבה
  (‎≥1200px‎) הכול בשורה אחת — כותרת והסבר בימין, כפתורים בשמאל — כדי לא
  לקחת מהרשת יותר מהנדרש.
* ‏"לא" שולח ‏allow_soft_conflicts: false, ותיבת החפיפות נעלמת; מתגי חובת
  הנוכחות בשלב 4 מושבתים (צבע ‎--muted‎, לא opacity) והגלולה "N שיעורים
  ללא חובת נוכחות" מוסתרת. ‏"כן" שולח true.
* אינה חוסמת את "בנה מערכות", ואינה מודפסת.

הקטלוג הקפוא לא מייצר חפיפה לקורסים המומלצים של הנדסת תוכנה, ולכן הבדיקות
מזריקות ‏soft_conflicts לתשובה האמיתית של ‎/api/solve‎ — ורק כשהבקשה מרשה
חפיפות, כמו שהשרת היה עושה.
"""

from __future__ import annotations

import json
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

STORAGE_KEY = "braude_schedule_builder_v1"
FAKE_REPORT = "חפיפה מכוונת: 61759 הרצאה מול 61760 תרגול"

TITLE = "האם לאפשר חפיפה?"
EXPLAIN = "שיעור בלי חובת נוכחות יכול להיות משובץ במקביל לשיעור אחר."
YES = "כן, לאפשר חפיפה"
NO = "לא, בלי חפיפה"


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


def _inject_overlap(route):
    """התשובה האמיתית, ועם חפיפה אחת בכל מערכת — רק אם הבקשה מרשה חפיפות."""
    body = json.loads(route.request.post_data or "{}")
    response = route.fetch()
    data = response.json()
    if body.get("allow_soft_conflicts") is True:
        for sch in data.get("schedules") or []:
            sch["soft_conflicts"] = 1
            sch["soft_conflict_report"] = FAKE_REPORT
    route.fulfill(
        status=response.status,
        headers={"content-type": "application/json"},
        body=json.dumps(data, ensure_ascii=False),
    )


def _open(browser, server, inject, width=1440, scheme="light", height=900):
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
    pg = ctx.new_page()
    bodies = []
    pg.on(
        "request",
        lambda r: bodies.append(json.loads(r.post_data or "{}"))
        if r.url.endswith("/api/solve") and r.method == "POST"
        else None,
    )
    if inject:
        pg.route("**/api/solve", _inject_overlap)
    pg.goto(server)
    pg.wait_for_timeout(3500)
    pg.select_option("#select-program", "הנדסת תוכנה")
    pg.select_option("#select-year", "3")
    pg.select_option("#select-term", "א")
    pg.wait_for_timeout(2500)
    pg.click("#step-year-next")
    pg.click("#btn-restore-recommended")
    pg.wait_for_timeout(5000)
    pg.click("#step-courses-next")
    pg.click("#step-days-next")
    pg.wait_for_timeout(1500)
    _build(pg)
    pg.wait_for_timeout(3000)
    return ctx, pg, bodies


def _build(pg):
    """במסך רחב התוצאה מתעדכנת לבד ו"בנה מערכות" אינו מוצג; בצר — לוחצים."""
    if pg.is_visible("#btn-build"):
        pg.click("#btn-build")


def _stored(pg):
    return pg.evaluate(f"() => JSON.parse(localStorage.getItem('{STORAGE_KEY}') || 'null')")


def _choose(pg, which):
    pg.locator("#overlap-ask").scroll_into_view_if_needed()
    pg.click("#btn-overlaps-" + which)
    pg.wait_for_timeout(4000)


VISIBLE = """id => { const n = document.getElementById(id);
  return !!n && !n.hidden && getComputedStyle(n).display !== 'none'; }"""

ASK = """() => {
  const box = document.getElementById('overlap-ask');
  const btn = id => { const b = document.getElementById(id);
    const m = b.querySelector('.overlap-check');
    const r = b.getBoundingClientRect();
    return {pressed: b.getAttribute('aria-pressed'), primary: b.classList.contains('btn-primary'),
            mark: !!m && !m.hidden && getComputedStyle(m).display !== 'none' ? m.textContent : '',
            text: b.innerText.replace(/\\s+/g, ' ').trim(), bg: getComputedStyle(b).backgroundColor,
            l: r.left, r: r.right, t: r.top, w: r.width}; };
  return {
    shown: !box.hidden && getComputedStyle(box).display !== 'none',
    title: document.getElementById('overlap-ask-title').textContent.trim(),
    sub: document.getElementById('overlap-ask-sub').textContent.trim(),
    yes: btn('btn-overlaps-allow'), no: btn('btn-overlaps-none'),
  };
}"""

SWITCHES = """() => {
  const muted = getComputedStyle(document.querySelector('.label')).color;
  return [...document.querySelectorAll('input[role="switch"]')].map(i => ({
    disabled: i.disabled,
    color: getComputedStyle(i.closest('label')).color,
    muted: muted,
  }));
}"""


# --------------------------------------------------------------------------
# מתי היא מוצגת
# --------------------------------------------------------------------------
def test_hidden_when_the_schedule_has_no_overlap_and_nothing_was_answered(browser, server):
    ctx, pg, _ = _open(browser, server, inject=False)
    try:
        got = {"soft": pg.evaluate(VISIBLE, "soft-conflicts"),
               "ask": pg.evaluate(VISIBLE, "overlap-ask")}
    finally:
        ctx.close()
    assert got == {"soft": False, "ask": False}, got


def test_an_overlap_shows_the_question_directly_below_the_overlap_box_unanswered(browser, server):
    ctx, pg, _ = _open(browser, server, inject=True)
    try:
        ask = pg.evaluate(ASK)
        place = pg.evaluate(
            """() => { const s = document.getElementById('soft-conflicts');
                const a = document.getElementById('overlap-ask');
                const g = document.getElementById('grid-scroll');
                return {next: s.nextElementSibling === a,
                        below: a.getBoundingClientRect().top >= s.getBoundingClientRect().bottom,
                        aboveGrid: a.getBoundingClientRect().bottom <= g.getBoundingClientRect().top}; }""")
        soft = pg.evaluate(VISIBLE, "soft-conflicts")
        stored = _stored(pg)["overlaps"]
    finally:
        ctx.close()
    assert soft and ask["shown"], ask
    assert place == {"next": True, "below": True, "aboveGrid": True}, place
    assert ask["title"] == TITLE and ask["sub"] == EXPLAIN, ask
    assert ask["yes"]["text"] == YES and ask["no"]["text"] == NO, ask
    for b in (ask["yes"], ask["no"]):
        assert b["pressed"] == "false" and not b["primary"] and not b["mark"], b
    assert stored is None


def test_an_answered_question_stays_without_an_overlap(browser, server):
    """בלי חפיפה, אבל נענתה — מוצגת, כדי שאפשר יהיה לשנות."""
    ctx, pg, _ = _open(browser, server, inject=False)
    try:
        pg.evaluate(
            f"""() => {{ const s = JSON.parse(localStorage.getItem('{STORAGE_KEY}'));
                s.overlaps = 'allow'; localStorage.setItem('{STORAGE_KEY}', JSON.stringify(s)); }}""")
        pg.reload()
        pg.wait_for_timeout(5000)
        got = {"soft": pg.evaluate(VISIBLE, "soft-conflicts"), "ask": pg.evaluate(ASK)}
    finally:
        ctx.close()
    assert not got["soft"] and got["ask"]["shown"], got
    assert got["ask"]["yes"]["pressed"] == "true" and got["ask"]["no"]["pressed"] == "false", got


# --------------------------------------------------------------------------
# מה התשובות עושות
# --------------------------------------------------------------------------
def test_no_rebuilds_without_overlaps_disables_the_switches_and_can_be_changed_back(browser, server):
    ctx, pg, bodies = _open(browser, server, inject=True)
    try:
        before = pg.evaluate(SWITCHES)
        pill_before = pg.evaluate(VISIBLE, "attendance-off")

        _choose(pg, "none")
        no = {
            "body": bodies[-1]["allow_soft_conflicts"],
            "soft": pg.evaluate(VISIBLE, "soft-conflicts"),
            "ask": pg.evaluate(ASK),
            "stored": _stored(pg)["overlaps"],
            "switches": pg.evaluate(SWITCHES),
            "pill": pg.evaluate(VISIBLE, "attendance-off"),
            "focus": pg.evaluate("() => document.activeElement.id"),
        }

        pg.reload()
        pg.wait_for_timeout(5000)
        reloaded = {"body": bodies[-1]["allow_soft_conflicts"], "ask": pg.evaluate(ASK),
                    "switches": pg.evaluate(SWITCHES)}

        _choose(pg, "allow")
        yes = {
            "body": bodies[-1]["allow_soft_conflicts"],
            "soft": pg.evaluate(VISIBLE, "soft-conflicts"),
            "ask": pg.evaluate(ASK),
            "stored": _stored(pg)["overlaps"],
            "switches": pg.evaluate(SWITCHES),
            "pill": pg.evaluate(VISIBLE, "attendance-off"),
        }
    finally:
        ctx.close()

    assert before and not any(s["disabled"] for s in before), before
    assert pill_before, "בברירת המחדל יש רכיבים בלי חובת נוכחות"

    assert no["body"] is False and no["stored"] == "none", no
    assert not no["soft"], "אחרי 'לא' אין חפיפה להציג"
    assert no["ask"]["shown"], "השאלה נשארת, כדי שאפשר יהיה לשנות"
    assert no["ask"]["no"] == {**no["ask"]["no"], "pressed": "true", "primary": True, "mark": "✓"}, no
    assert no["ask"]["yes"]["pressed"] == "false" and not no["ask"]["yes"]["primary"], no
    assert not no["ask"]["yes"]["mark"], no
    assert no["switches"] and all(s["disabled"] for s in no["switches"]), no
    assert all(s["color"] == s["muted"] for s in no["switches"]), "מושבת נראה מושבת: ‎--muted‎"
    assert not no["pill"], "אין 'N שיעורים ללא חובת נוכחות' כשאין חפיפה"
    assert no["focus"] == "btn-overlaps-none", "הפוקוס נשאר על הכפתור שנלחץ"

    assert reloaded["body"] is False and reloaded["ask"]["shown"], reloaded
    assert reloaded["ask"]["no"]["pressed"] == "true", reloaded
    assert all(s["disabled"] for s in reloaded["switches"]), reloaded

    assert yes["body"] is True and yes["stored"] == "allow", yes
    assert yes["soft"] and yes["ask"]["shown"] and yes["pill"], yes
    assert yes["ask"]["yes"]["pressed"] == "true" and yes["ask"]["yes"]["primary"], yes
    assert yes["ask"]["yes"]["mark"] == "✓", yes
    assert yes["ask"]["no"]["pressed"] == "false" and not yes["ask"]["no"]["mark"], yes
    assert not any(s["disabled"] for s in yes["switches"]), yes


def test_yes_from_unanswered_keeps_everything_and_sends_nothing_new(browser, server):
    ctx, pg, bodies = _open(browser, server, inject=True)
    try:
        sent = len(bodies)
        _choose(pg, "allow")
        got = {
            "requests": len(bodies) - sent,
            "soft": pg.evaluate(VISIBLE, "soft-conflicts"),
            "ask": pg.evaluate(ASK),
            "stored": _stored(pg)["overlaps"],
        }
    finally:
        ctx.close()
    assert got["requests"] == 0, "‏allow_soft_conflicts כבר true — אין מה לפתור מחדש"
    assert got["soft"] and got["ask"]["shown"] and got["stored"] == "allow", got
    assert got["ask"]["yes"]["pressed"] == "true" and got["ask"]["yes"]["primary"], got


# --------------------------------------------------------------------------
# איך היא נראית
# --------------------------------------------------------------------------
TOKENS = """() => {
  const probe = document.createElement('div');
  probe.style.cssText = 'color: var(--line-strong); background: var(--panel-2); '
                      + 'border-radius: var(--radius); border-color: var(--muted)';
  document.body.appendChild(probe);
  const p = getComputedStyle(probe);
  const want = {line: p.color, panel2: p.backgroundColor, radius: p.borderTopLeftRadius,
                muted: p.borderTopColor};
  probe.remove();
  const box = getComputedStyle(document.getElementById('overlap-ask'));
  const sub = getComputedStyle(document.getElementById('overlap-ask-sub'));
  const soft = getComputedStyle(document.getElementById('soft-conflicts'));
  return {want: want,
          border: [box.borderTopStyle, box.borderTopWidth, box.borderTopColor],
          bg: box.backgroundColor, radius: box.borderTopLeftRadius,
          padding: box.paddingInlineStart,
          sub: sub.color, softBg: soft.backgroundColor};
}"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_box_is_dashed_on_panel2_from_tokens(browser, server, scheme):
    ctx, pg, _ = _open(browser, server, inject=True, scheme=scheme)
    try:
        got = pg.evaluate(TOKENS)
    finally:
        ctx.close()
    w = got["want"]
    assert got["border"] == ["dashed", "2px", w["line"]], got
    assert got["bg"] == w["panel2"] and got["radius"] == w["radius"], got
    assert got["padding"] == "16px", got
    assert got["sub"] == w["muted"], "שורת ההסבר ב-‎--muted‎"
    assert got["bg"] != got["softBg"], "לא בצבע של תיבת החפיפות"


@pytest.mark.parametrize("width", [320, 375])
def test_on_a_phone_the_two_buttons_share_a_row_at_equal_width(browser, server, width):
    ctx, pg, _ = _open(browser, server, inject=True, width=width, height=800)
    try:
        ask = pg.evaluate(ASK)
        row = pg.evaluate(
            "() => document.querySelector('#overlap-ask .overlap-ask-actions').getBoundingClientRect().width")
        wide = pg.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        ctx.close()
    y, n = ask["yes"], ask["no"]
    assert ask["shown"], ask
    assert abs(y["t"] - n["t"]) <= 1, "באותה שורה"
    assert abs(y["w"] - n["w"]) <= 1, "ברוחב שווה"
    assert y["w"] + n["w"] >= row - 16, "יחד הם ממלאים את השורה"
    assert y["l"] >= n["r"] - 0.5, "‏'כן' מימין ל'לא' (RTL)"
    assert wide, "אין גלילה אופקית"


COMPACT = """() => {
  const box = document.getElementById('overlap-ask');
  const r = e => { const b = e.getBoundingClientRect();
                   return {l: b.left, r: b.right, t: b.top, b: b.bottom, mid: (b.top + b.bottom) / 2}; };
  const cs = getComputedStyle(box);
  const btn = getComputedStyle(document.getElementById('btn-overlaps-allow'));
  return {box: r(box), h: box.getBoundingClientRect().height,
          title: r(document.getElementById('overlap-ask-title')),
          sub: r(document.getElementById('overlap-ask-sub')),
          yes: r(document.getElementById('btn-overlaps-allow')),
          no: r(document.getElementById('btn-overlaps-none')),
          padBlock: cs.paddingTop, btnPad: btn.paddingTop, nowrap: btn.whiteSpace,
          grid: document.getElementById('grid-scroll').clientHeight};
}"""


def test_on_a_wide_screen_the_question_is_one_compact_row(browser, server):
    """‏1440×900: כותרת והסבר זה לצד זה בימין, הכפתורים בשמאל, שורה אחת."""
    ctx, pg, _ = _open(browser, server, inject=True, width=1440, height=900)
    try:
        g = pg.evaluate(COMPACT)
    finally:
        ctx.close()
    parts = [g["title"], g["sub"], g["yes"], g["no"]]
    # ‏שורה אחת: כל החלקים חוצים את אותו קו אופקי.
    line = g["yes"]["mid"]
    assert all(p["t"] <= line <= p["b"] for p in parts), g
    assert g["h"] <= 60, f"שורה אחת קומפקטית, לא {g['h']}px"
    assert g["padBlock"] == "8px" and g["btnPad"] == "6px" and g["nowrap"] == "nowrap", g
    # ‏RTL: הכותרת בהתחלה (ימין), ההסבר אחריה, הכפתורים בסוף (שמאל).
    assert g["title"]["l"] > g["sub"]["r"], g
    assert g["sub"]["l"] > g["yes"]["r"], g
    assert g["yes"]["l"] > g["no"]["r"], "‏'כן' לפני 'לא'"
    assert abs(g["no"]["l"] - (g["box"]["l"] + 2 + 16)) <= 1, "הכפתורים צמודים לסוף (שמאל)"


@pytest.mark.parametrize("width", [375])
def test_on_a_phone_the_box_keeps_its_stacked_layout(browser, server, width):
    ctx, pg, _ = _open(browser, server, inject=True, width=width, height=800)
    try:
        g = pg.evaluate(COMPACT)
    finally:
        ctx.close()
    assert g["padBlock"] == "14px", g
    assert g["sub"]["t"] >= g["title"]["b"] and g["yes"]["t"] >= g["sub"]["b"], g


# --------------------------------------------------------------------------
# מה היא אינה עושה
# --------------------------------------------------------------------------
def test_it_does_not_block_build(browser, server):
    ctx, pg, _ = _open(browser, server, inject=True, width=800, height=700)
    try:
        assert pg.evaluate(VISIBLE, "overlap-ask")
        pg.evaluate("() => window.scrollTo(0, 0)")
        pg.wait_for_timeout(300)
        pg.click("#btn-build")
        pg.wait_for_timeout(2500)
        got = pg.evaluate(
            """() => ({top: document.getElementById('step-schedule').getBoundingClientRect().top,
                       modal: !!document.querySelector('[aria-modal="true"]:not([hidden])'),
                       html: document.documentElement.classList.contains('has-modal')})""")
    finally:
        ctx.close()
    assert not got["modal"] and not got["html"], got
    assert abs(got["top"]) < 200, f"‏'בנה מערכות' גולל אל התוצאה: {got}"


def test_it_is_not_printed(browser, server):
    ctx, pg, _ = _open(browser, server, inject=True)
    try:
        assert pg.evaluate(VISIBLE, "overlap-ask")
        pg.emulate_media(media="print")
        pg.wait_for_timeout(300)
        shown = pg.evaluate(VISIBLE, "overlap-ask")
    finally:
        ctx.close()
    assert not shown
