"""אשכולות הבחירה כשורות שנפתחות בלחיצה (docs/DESIGN.md, "Elective clusters",
2026-10-05).

מה נבדק כאן
-----------
* **כל האשכולות סגורים בכניסה,** והגוף הסגור הוא ‎hidden="until-found"‎ — לא
  מצויר, מחוץ לסדר ה-Tab ולעץ הנגישות, ונמצא ב-Ctrl+F (הוחלט 2026-10-05).
* **לחיצה פותחת** את השבבים ואת ההערות של האשכול; **פתיחה של אחר סוגרת**
  את הראשון.
* **השורה אומרת "נבחרו N"** אחרי בחירה, ו-"N קורסים" לפני; ה-✓ על הגלולה
  נשאר כמו קודם.
* **החלפת סמסטר** ו**פתיחה מחדש של השלב** סוגרות הכל.
* **מקלדת:** ‏Enter ו-Space פותחים וסוגרים; ‏aria-expanded ו-aria-controls.
* **תנועה:** ‏350ms ‏cubic-bezier(.2,.8,.2,1), ומיידית ב-prefers-reduced-motion.
* **Ctrl+F מוצא קורס באשכול סגור** (‎hidden="until-found"‎, 2026-10-05): החיפוש
  פותח את האשכול שלו וסוגר כל אחר. נבדק דרך קטע טקסט (‎#:~:text=‎), שעובר
  באותו מנגנון של הדפדפן ויורה beforematch; ‏window.find() אינו יורה אותו.
* **הסעיף קצר בהרבה:** נמדד 2026-10-05 במאגר הבדיקות, ‏1440x900 (עמודת שלבים
  של 400px): ‏2718px לפני, ‏331px כשהכל סגור, ‏701px כשהאשכול הראשון פתוח.

הבחירה: הנדסת תוכנה, שנה ג', סמסטר א' — שישה אשכולות.
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
EL = STRINGS["app"]["electives"]

HEAD = "#electives-groups .elective-cluster-head"


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


def _open(browser, server, width=1440, height=900, **ctx_opts):
    ctx = browser.new_context(
        viewport={"width": width, "height": height}, color_scheme="light", **ctx_opts
    )
    page = ctx.new_page()
    page.errors = []  # type: ignore[attr-defined]
    page.on("pageerror", lambda e: page.errors.append(str(e)))  # type: ignore[attr-defined]
    page.goto(server)
    page.wait_for_timeout(2500)
    page.select_option("#select-program", "הנדסת תוכנה")
    page.select_option("#select-year", "3")
    page.select_option("#select-term", "א")
    page.click("#step-year-next")  # "המשך" אל שלב הקורסים (Phase 8, באישור 2026-10-06)
    page.wait_for_selector(HEAD, timeout=20000)
    page.wait_for_timeout(800)
    return ctx, page


#: לכל אשכול: מפתח, האם פתוח, aria, האם הגוף נראה, השורה, וכמה שבבים נראים.
CLUSTERS = """() => [...document.querySelectorAll('#electives-groups .elective-cluster')].map(c => {
  const head = c.querySelector('.elective-cluster-head');
  const body = c.querySelector('.elective-body');
  const fold = document.getElementById(head.getAttribute('aria-controls'));
  // ‏"נראה": לא ‎hidden‎ ולא ‎inert‎, והחלק שלו שבתוך העטיפה (שגוזרת אותו) אינו ריק.
  const shown = !fold.inert && !body.hasAttribute('hidden') && fold.getBoundingClientRect().height > 1;
  const box = fold.getBoundingClientRect();
  const seen = e => { const r = e.getBoundingClientRect();
                      return shown && r.height > 0 && r.top < box.bottom - 1 && r.bottom > box.top + 1; };
  return {key: c.dataset.key, open: c.classList.contains('is-open'),
          hiddenAttr: body.getAttribute('hidden'),
          expanded: head.getAttribute('aria-expanded'), tag: head.tagName,
          controls: !!fold && fold.contains(body),
          inert: fold.inert, bodyVisible: shown,
          chipsSeen: [...c.querySelectorAll('.elective-chip')].filter(seen).length,
          chips: c.querySelectorAll('.elective-chip[data-code]').length,
          notesSeen: [...c.querySelectorAll('.elective-cluster-note')].filter(seen).map(n => n.textContent.trim()),
          notes: [...c.querySelectorAll('.elective-cluster-note')].map(n => n.textContent.trim()),
          count: c.querySelector('.elective-cluster-count').textContent.trim(),
          check: !!c.querySelector('.elective-pill-check')};
})"""


def _clusters(page):
    return page.evaluate(CLUSTERS)


def _wait_settled(page):
    page.wait_for_timeout(500)  # ‏350ms של תנועה, ועוד מרווח


def _assert_all_closed(clusters, where):
    # ‏סגור = ‎hidden="until-found"‎ על הגוף (לא מצויר, מחוץ ל-Tab ולעץ הנגישות),
    # ‏או ‎inert‎ בדפדפן בלי until-found.
    bad = [c["key"] for c in clusters if c["open"] or c["expanded"] != "false"
           or not (c["hiddenAttr"] == "until-found" or c["inert"])
           or c["bodyVisible"] or c["chipsSeen"]]
    assert clusters and not bad, f"{where}: פתוחים {bad}"


# ==========================================================================
# 1. בכניסה: הכל סגור, והשורה היא כפתור אמיתי
# ==========================================================================
def test_every_cluster_is_closed_on_entry(browser, server):
    ctx, pg = _open(browser, server)
    try:
        clusters = _clusters(pg)
        assert len(clusters) >= 2, clusters
        _assert_all_closed(clusters, "בכניסה")
        for c in clusters:
            assert c["tag"] == "BUTTON" and c["controls"], c
            # ‏"N קורסים" כשלא נבחר אף אחד.
            want = EL["countCoursesOne"] if c["chips"] == 1 else fill(EL["countCourses"], n=c["chips"])
            assert c["count"] == want, c
        # ‏הכותרת והשורות שמתחתיה אינן מתקפלות.
        assert pg.is_visible("#electives-title")
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


# ==========================================================================
# 2. לחיצה פותחת; אחר סוגר
# ==========================================================================
def test_clicking_opens_chips_and_notes_and_another_closes_it(browser, server):
    ctx, pg = _open(browser, server)
    try:
        before = _clusters(pg)
        # ‏האשכול הראשון שיש לו הערה, כדי לבדוק שגם היא נפתחת.
        first = next((c for c in before if c["notes"]), before[0])
        pg.click(f"{HEAD}[data-key='{first['key']}']")
        _wait_settled(pg)
        now = {c["key"]: c for c in _clusters(pg)}
        opened = now[first["key"]]
        assert opened["open"] and opened["expanded"] == "true", opened
        assert opened["bodyVisible"] and not opened["inert"], opened
        assert opened["chipsSeen"] == len(pg.query_selector_all(
            f"#electives-groups .elective-cluster[data-key='{first['key']}'] .elective-chip")), opened
        assert opened["notesSeen"] == opened["notes"], opened
        _assert_all_closed([c for k, c in now.items() if k != first["key"]], "אחרי פתיחה")

        second = next(c for c in before if c["key"] != first["key"])
        pg.click(f"{HEAD}[data-key='{second['key']}']")
        _wait_settled(pg)
        now = {c["key"]: c for c in _clusters(pg)}
        assert now[second["key"]]["open"] and now[second["key"]]["chipsSeen"] > 0
        _assert_all_closed([c for k, c in now.items() if k != second["key"]], "אחרי פתיחת אחר")

        # לחיצה שנייה על הפתוח סוגרת אותו.
        pg.click(f"{HEAD}[data-key='{second['key']}']")
        _wait_settled(pg)
        _assert_all_closed(_clusters(pg), "אחרי סגירה")
    finally:
        ctx.close()


# ==========================================================================
# 3. "נבחרו N" וה-✓
# ==========================================================================
def test_the_line_counts_the_selection_and_keeps_the_check(browser, server):
    ctx, pg = _open(browser, server)
    try:
        c = _clusters(pg)[0]
        assert not c["check"]
        pg.click(f"{HEAD}[data-key='{c['key']}']")
        _wait_settled(pg)
        box = f"#electives-groups .elective-cluster[data-key='{c['key']}']"
        pg.locator(box + " .elective-chip[data-code]").first.click()
        pg.wait_for_timeout(800)
        after = {x["key"]: x for x in _clusters(pg)}[c["key"]]
        assert after["count"] == fill(EL["countPicked"], n=1), after
        # ‏"לפחות קורס אחד" — ה-✓ על הגלולה, כמו קודם.
        assert after["check"], after
        assert pg.locator(box + " .elective-pill-check").inner_text() == "✓"
        # הבחירה אינה סוגרת את האשכול.
        assert after["open"] and after["bodyVisible"], after
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


# ==========================================================================
# 4. החלפת סמסטר ופתיחה מחדש של השלב סוגרות הכל
# ==========================================================================
def test_changing_semester_closes_every_cluster(browser, server):
    ctx, pg = _open(browser, server)
    try:
        key = _clusters(pg)[0]["key"]
        pg.click(f"{HEAD}[data-key='{key}']")
        _wait_settled(pg)
        assert any(c["open"] for c in _clusters(pg))
        pg.click("#step-year-toggle")  # "שינוי" על שלב 1 (Phase 8, באישור 2026-10-06)
        pg.select_option("#select-term", "ב")
        pg.wait_for_timeout(2500)
        pg.select_option("#select-term", "א")
        pg.click("#step-year-next")  # "המשך" אל שלב הקורסים (Phase 8, באישור 2026-10-06)
        pg.wait_for_selector(HEAD, timeout=20000)
        pg.wait_for_timeout(1500)
        _assert_all_closed(_clusters(pg), "אחרי החלפת סמסטר")
    finally:
        ctx.close()


def test_reopening_the_step_closes_every_cluster(browser, server):
    ctx, pg = _open(browser, server)
    try:
        key = _clusters(pg)[0]["key"]
        pg.click(f"{HEAD}[data-key='{key}']")
        _wait_settled(pg)
        # ‏השלב הפתוח נסגר רק ב"המשך"; שלב שהושלם ונפתח ב"שינוי" נסגר גם
        # ‏מהכותרת (Phase 8, באישור 2026-10-06). שלב בלי קורסים אינו מושלם,
        # ‏ולכן "סמנו הכל" לפני "המשך" (באישור 2026-10-07).
        pg.click("#btn-restore-recommended")
        pg.wait_for_timeout(600)
        pg.click("#step-courses-next")
        pg.wait_for_timeout(600)
        pg.click("#step-courses-toggle")
        pg.wait_for_timeout(600)
        pg.click("#step-courses-toggle")
        pg.wait_for_timeout(600)
        assert pg.evaluate("document.getElementById('step-courses').classList.contains('is-collapsed')")
        pg.click("#step-courses-toggle")
        pg.wait_for_timeout(600)
        assert not pg.evaluate("document.getElementById('step-courses').classList.contains('is-collapsed')")
        _assert_all_closed(_clusters(pg), "אחרי פתיחה מחדש של השלב")
    finally:
        ctx.close()


# ==========================================================================
# 5. מקלדת
# ==========================================================================
def test_enter_and_space_toggle_a_cluster(browser, server):
    ctx, pg = _open(browser, server)
    try:
        key = _clusters(pg)[0]["key"]
        head = pg.locator(f"{HEAD}[data-key='{key}']")
        head.focus()
        pg.keyboard.press("Enter")
        _wait_settled(pg)
        assert head.get_attribute("aria-expanded") == "true"
        # הפוקוס נשאר על השורה, ו-Tab הבא נכנס לשבב הראשון שבתוכה.
        assert pg.evaluate("document.activeElement.classList.contains('elective-cluster-head')")
        pg.keyboard.press("Tab")
        assert pg.evaluate(
            "!!document.activeElement.closest(\"#electives-groups .elective-cluster.is-open .elective-body\")"
        )
        head.focus()
        pg.keyboard.press("Space")
        _wait_settled(pg)
        assert head.get_attribute("aria-expanded") == "false"
        # סגור — Tab מדלג על השבבים שבתוכו.
        head.focus()
        pg.keyboard.press("Tab")
        assert not pg.evaluate(
            "!!document.activeElement.closest(\"#electives-groups .elective-cluster[data-key='" + key + "'] .elective-body\")"
        )
    finally:
        ctx.close()


# ==========================================================================
# 6. תנועה
# ==========================================================================
def _fold_transition(page):
    return page.evaluate(
        """() => { const f = document.querySelector('#electives-groups .elective-fold');
                   const cs = getComputedStyle(f);
                   return {prop: cs.transitionProperty, dur: cs.transitionDuration,
                           ease: cs.transitionTimingFunction}; }"""
    )


def test_opening_animates_height_like_the_steps(browser, server):
    ctx, pg = _open(browser, server)
    try:
        t = _fold_transition(pg)
        assert t["prop"] == "grid-template-rows" and t["dur"] == "0.35s", t
        assert re.sub(r"\s", "", t["ease"]) == "cubic-bezier(0.2,0.8,0.2,1)", t
        # באמצע התנועה הגובה בין סגור לפתוח.
        key = _clusters(pg)[0]["key"]
        fold = f"#electives-groups .elective-cluster[data-key='{key}'] .elective-fold"
        pg.click(f"{HEAD}[data-key='{key}']")
        pg.wait_for_timeout(120)
        mid = pg.evaluate(f"document.querySelector(\"{fold}\").getBoundingClientRect().height")
        _wait_settled(pg)
        end = pg.evaluate(f"document.querySelector(\"{fold}\").getBoundingClientRect().height")
        assert 0 < mid < end, (mid, end)
    finally:
        ctx.close()


def test_reduced_motion_makes_it_instant(browser, server):
    ctx, pg = _open(browser, server, reduced_motion="reduce")
    try:
        t = _fold_transition(pg)
        # ‏כלל ה-reduced-motion הכללי של הגיליון קובע ‎transition: none‎ עם משך
        # ‏זעיר (‎1e-06s‎) — מיידי, בכל אחד מהניסוחים.
        durations = [float(d.strip().rstrip("s") or 0) for d in t["dur"].split(",")]
        assert t["prop"] == "none" or max(durations) < 0.01, t
        key = _clusters(pg)[0]["key"]
        pg.click(f"{HEAD}[data-key='{key}']")
        pg.wait_for_timeout(50)
        c = {x["key"]: x for x in _clusters(pg)}[key]
        assert c["bodyVisible"] and c["chipsSeen"] > 0, c
    finally:
        ctx.close()


# ==========================================================================
# 7. הסעיף קצר בהרבה
# ==========================================================================
#: ‏2718px לפני השינוי (נמדד, 1440x900). ‏רבע מזה הוא תקרה נדיבה למצב הסגור.
BEFORE_PX = 2718


def test_the_electives_section_is_far_shorter(browser, server):
    ctx, pg = _open(browser, server)
    try:
        h = lambda: pg.evaluate("document.getElementById('electives').getBoundingClientRect().height")
        closed = h()
        assert closed <= BEFORE_PX / 4, f"{closed}px כשהכל סגור"
        # כל שורה סגורה היא שורה אחת: גובה כמו של שורת טקסט אחת או שתיים.
        rows = pg.evaluate(
            "[...document.querySelectorAll('#electives-groups .elective-cluster')].map(c => c.getBoundingClientRect().height)"
        )
        assert all(r < 80 for r in rows), rows
        pg.click(f"{HEAD} >> nth=0")
        _wait_settled(pg)
        assert closed < h() < BEFORE_PX / 2
    finally:
        ctx.close()


# ==========================================================================
# 8. ‏Ctrl+F מוצא קורס באשכול סגור — ופותח רק אותו
# ==========================================================================
def test_finding_a_course_in_a_closed_cluster_opens_only_that_cluster(browser, server):
    ctx, pg = _open(browser, server)
    try:
        clusters = _clusters(pg)
        _assert_all_closed(clusters, "בכניסה")
        assert all(c["hiddenAttr"] == "until-found" for c in clusters), clusters
        # ‏שם קורס שמופיע רק באשכול אחד, ולא באשכול הראשון — שאותו נפתח קודם.
        target = pg.evaluate(
            """() => {
              const names = new Map();
              document.querySelectorAll('#electives-groups .elective-cluster').forEach((c, i) =>
                c.querySelectorAll('.elective-chip-name').forEach(n => {
                  const t = n.textContent.trim();
                  names.set(t, (names.get(t) || []).concat([i]));
                }));
              const all = [...document.querySelectorAll('#electives-groups .elective-cluster')];
              for (const [name, where] of names) {
                if (where.length === 1 && where[0] > 0
                    && document.body.innerText.indexOf(name) === -1)
                  return {name, key: all[where[0]].dataset.key};
              }
              return null;
            }"""
        )
        assert target, "אין שם קורס שמופיע רק באשכול סגור אחד"
        first = clusters[0]["key"]
        assert first != target["key"]
        pg.click(f"{HEAD}[data-key='{first}']")
        _wait_settled(pg)
        assert {c["key"]: c for c in _clusters(pg)}[first]["open"]
        # החיפוש עצמו — באותו מסמך, בלי טעינה מחדש.
        pg.evaluate("window.__noReload = true")
        pg.evaluate("(n) => { location.hash = ':~:text=' + encodeURIComponent(n); }", target["name"])
        _wait_settled(pg)
        assert pg.evaluate("window.__noReload === true"), "החיפוש טען את הדף מחדש"
        now = {c["key"]: c for c in _clusters(pg)}
        found = now[target["key"]]
        assert found["open"] and found["expanded"] == "true" and found["bodyVisible"], found
        assert found["hiddenAttr"] is None, found
        _assert_all_closed([c for k, c in now.items() if k != target["key"]], "אחרי החיפוש")
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()
