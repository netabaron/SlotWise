"""שלב 7 של העיצוב מחדש, חלק ב׳: השבוע כולו על המסך (docs/DESIGN.md, "Layout",
סדר ההתאמה, צעדים 2 ו-3; 2026-10-03).

מה נבדק כאן
-----------
* **צעד 1 מספיק → שום דבר אחר אינו חל:** אין רצועה, אין תווית בכותרת, שלוש
  שורות בכל בלוק וגובה שעה מהתוכן.
* **צעד 3:** אין גלילה פנימית, שם הקורס גלוי במלואו בכל בלוק, שורה שירדה ירדה
  כולה (display: none, לא חתוכה), שורה 3 יורדת לפני שורה 2, ואף בלוק אינו
  גולש. תוויות השעה גלויות.
* **צעד 4:** חלון נמוך מדי לשמות — גלילה פנימית ושלוש שורות בכל בלוק.
* **הרצועה הדקה והתווית האחת** מופיעות רק כשצריך, והתווית היא של הנבחרת.
* **שינוי גודל גבוה → נמוך → גבוה** מחזיר את התצוגה המלאה; החלפת חלופה מתאימה
  מחדש; ואין לולאה — אחרי שהדף נח, הרשת אינה משתנה עוד.
* **השם הנגיש** של כל בלוק נושא את כל תוכנו, כולל הסוג והמרצה, ולחיצה על
  בלוק מקוצר מציגה הכל בפאנל.
* **הדפסה** מחלון שבו המסך מקצר: שלוש שורות בכל בלוק.
* **מסך צר** — בלי שום סימן של ההתאמה.

**איזה צעד חל באיזה חלון נמדד, לא נוחש** (2026-10-05, מאגר הבדיקות, הנדסת
תוכנה סמסטר 5): ‏1920x1080, ‏1536x864 ו-1440x900 — צעד 3; ‏1440x780 ו-1366x768 —
צעד 4, כי בשעה של 37px שם הקורס "אינטראקציית אדם מחשב (HCI)" בבלוק של שעה אחת
נשבר לשתי שורות ואינו נכנס. ‏1920x1500 — צעד 1. החלונות כאן נבחרו לפי זה.
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
GRID = STRINGS["app"]["grid"]

TALL = (1920, 1500)       # צעד 1
FULL_HD = (1920, 1080)
STEP3 = [(1536, 864), (1440, 900)]
STEP4 = [(1440, 780), (1366, 768)]


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
    page.click("#step-year-next")  # "המשך" אל שלב הקורסים (Phase 8, באישור 2026-10-06)
    page.click("#btn-restore-recommended")
    page.wait_for_selector("#schedule-grid .ev", timeout=20000)
    _settle(page)
    return ctx, page


def _settle(page):
    page.wait_for_function(
        "() => !!document.getElementById('schedule-grid').style.getPropertyValue('--slot-h')",
        timeout=15000,
    )
    page.wait_for_timeout(900)


def _resize(page, size):
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.wait_for_timeout(900)


#: מצב ההתאמה, ולכל בלוק: אילו שורות מוצגות, האם שורה מוצגת חתוכה, גלישה.
STATE = """() => {
  const col = document.getElementById('step-schedule');
  const g = document.getElementById('schedule-grid');
  const box = document.getElementById('grid-scroll');
  const shown = l => !!l && getComputedStyle(l).display !== 'none';
  const blocks = [...g.querySelectorAll('.ev')].map(e => {
    const cs = getComputedStyle(e);
    const r = e.getBoundingClientRect();
    const top = r.top + parseFloat(cs.borderTopWidth) + parseFloat(cs.paddingTop);
    const bottom = r.bottom - parseFloat(cs.borderBottomWidth) - parseFloat(cs.paddingBottom);
    const line = sel => {
      const l = e.querySelector(':scope > ' + sel);
      if (!l) return null;
      const lr = l.getBoundingClientRect();
      return {shown: shown(l), height: lr.height, text: l.textContent.trim(),
              inside: lr.top >= top - 0.5 && lr.bottom <= bottom + 0.5,
              wide: l.scrollWidth > l.clientWidth + 1};
    };
    return {name: line('.ev-name'), when: line('.ev-when'), who: line('.ev-who'),
            lines: e.dataset.lines || null, label: e.getAttribute('aria-label'),
            title: e.getAttribute('title'), code: e.dataset.code,
            overflow: e.scrollHeight - e.clientHeight};
  });
  return {fit: col.dataset.fit || null, strip: col.classList.contains('is-strip'),
          slot: g.style.getPropertyValue('--slot-h'),
          innerScroll: box.scrollHeight > box.clientHeight + 1,
          label: (l => ({shown: shown(l), text: l.textContent.trim()}))(document.getElementById('alt-label')),
          facts: [...document.querySelectorAll('#alt-cards .alt-card-facts')].map(shown),
          cardLabels: [...document.querySelectorAll('#alt-cards .alt-card-label')].map(shown),
          blocks: blocks};
}"""


def _state(page):
    return page.evaluate(STATE)


def _assert_names_whole_and_lines_whole(st, where):
    bad = []
    for b in st["blocks"]:
        n = b["name"]
        if not (n and n["shown"] and n["inside"] and not n["wide"] and n["text"]):
            bad.append(f"שם: {n}")
        if b["overflow"] > 0:
            bad.append(f"{n['text']}: גולש ב-{b['overflow']}px")
        for key in ("when", "who"):
            line = b[key]
            if line is None:
                continue
            # שורה מוצגת — כולה בתוך הבלוק. שורה שירדה — ירדה כולה.
            if line["shown"] and not (line["inside"] and not line["wide"] and line["height"] > 0):
                bad.append(f"{n['text']}: {key} חתוכה {line}")
        # שורה 3 יורדת לפני שורה 2.
        if b["when"] and not b["when"]["shown"] and b["who"] and b["who"]["shown"]:
            bad.append(f"{n['text']}: שורה 2 ירדה ושורה 3 נשארה")
    assert not bad, f"{where}: " + " | ".join(bad)


def _assert_three_lines(st, where):
    bad = []
    for b in st["blocks"]:
        if b["lines"] is not None or b["overflow"] > 0:
            bad.append(f"{b['name']['text']}: lines={b['lines']} overflow={b['overflow']}")
        for key in ("name", "when", "who"):
            line = b[key]
            if line and not (line["shown"] and line["inside"] and not line["wide"]):
                bad.append(f"{b['name']['text']}: {key} {line}")
    assert not bad, f"{where}: " + " | ".join(bad)


# ==========================================================================
# 1. צעד 1: חלון גבוה — שום צעד אחר אינו חל
# ==========================================================================
def test_a_tall_window_needs_no_fitting(browser, server):
    ctx, pg = _open(browser, server, TALL)
    try:
        st = _state(pg)
        assert st["fit"] == "1", st["fit"]
        assert not st["strip"] and not st["innerScroll"]
        assert not st["label"]["shown"]
        assert all(st["facts"]) and all(st["cardLabels"]), st
        _assert_three_lines(st, "1920x1500")
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


# ==========================================================================
# 2. ‏1920x1080 וחלונות של צעד 3: השבוע נכנס בלי גלילה
# ==========================================================================
@pytest.mark.parametrize("size", [FULL_HD] + STEP3, ids=lambda s: f"{s[0]}x{s[1]}")
def test_the_week_fits_without_an_inner_scroll(browser, server, size):
    ctx, pg = _open(browser, server, size)
    try:
        st = _state(pg)
        assert st["fit"] in ("1", "2", "3"), st["fit"]
        assert not st["innerScroll"], st
        # ‏גם העמודה כולה על המסך: אין גלילה פנימית גם מכיוון אחר.
        col = pg.evaluate("document.getElementById('step-schedule').getBoundingClientRect().height")
        assert col == pytest.approx(size[1], abs=1)
        _assert_names_whole_and_lines_whole(st, f"{size}")
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


@pytest.mark.parametrize("size", STEP3, ids=lambda s: f"{s[0]}x{s[1]}")
def test_step_three_drops_whole_lines_and_keeps_hour_labels_readable(browser, server, size):
    ctx, pg = _open(browser, server, size)
    try:
        st = _state(pg)
        assert st["fit"] == "3", st["fit"]
        assert st["strip"], "צעד 3 בא אחרי צעד 2: הרצועה חייבת להיות שם"
        shortened = [b for b in st["blocks"] if b["lines"]]
        assert shortened, "צעד 3 חל אבל אף בלוק לא קוצר — אז גם צעד 2 היה מספיק"
        for b in shortened:
            assert b["lines"] in ("1", "2"), b
            assert not b["who"] or not b["who"]["shown"], b
            if b["lines"] == "1":
                assert not b["when"]["shown"], b
        # ‏תוויות השעה: הטקסט כולו גלוי, ולא מכוסה בתא שמתחתיו.
        hidden = pg.evaluate(
            """() => [...document.querySelectorAll('#schedule-grid .tl.hour')].filter(tl => {
                 const r = document.createRange(); r.selectNodeContents(tl);
                 const b = r.getBoundingClientRect();
                 const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height * 0.75);
                 return !(hit === tl || tl.contains(hit));
               }).map(tl => tl.textContent)"""
        )
        assert hidden == [], f"תוויות שעה מוסתרות: {hidden}"
    finally:
        ctx.close()


# ==========================================================================
# 3. צעד 4: חלון נמוך מדי לשמות — גלילה ושלוש שורות
# ==========================================================================
@pytest.mark.parametrize("size", STEP4, ids=lambda s: f"{s[0]}x{s[1]}")
def test_too_short_for_the_names_scrolls_with_all_three_lines(browser, server, size):
    ctx, pg = _open(browser, server, size)
    try:
        st = _state(pg)
        assert st["fit"] == "4", st["fit"]
        assert st["innerScroll"], st
        assert st["strip"], "הרצועה נשארת בצעד 4"
        _assert_three_lines(st, f"{size}")
        # ‏גובה השעה חזר להיות מהתוכן: פיקסל אחד פחות, ובלוק גולש.
        fit = pg.evaluate(
            """() => { const g = document.getElementById('schedule-grid');
                       const slot = parseFloat(g.style.getPropertyValue('--slot-h'));
                       const evs = [...g.querySelectorAll('.ev')];
                       const over = () => evs.filter(e => e.scrollHeight > e.clientHeight).length;
                       const at = over();
                       g.style.setProperty('--slot-h', (slot - 1) + 'px');
                       const below = over();
                       g.style.setProperty('--slot-h', slot + 'px');
                       return {at, below}; }"""
        )
        assert fit["at"] == 0 and fit["below"] > 0, fit
    finally:
        ctx.close()


# ==========================================================================
# 4. הרצועה והתווית — רק כשצריך, והתווית של הנבחרת
# ==========================================================================
def test_the_strip_and_the_one_label_appear_only_when_needed(browser, server):
    ctx, pg = _open(browser, server, TALL)
    try:
        assert not _state(pg)["strip"]
        _resize(pg, STEP3[0])
        st = _state(pg)
        assert st["strip"] and st["fit"] in ("2", "3", "4"), st["fit"]
        assert not any(st["facts"]) and not any(st["cardLabels"]), st
        selected = pg.evaluate(
            "document.querySelector('#alt-cards .alt-card.is-selected .alt-card-label').textContent.trim()"
        )
        assert st["label"]["shown"] and st["label"]["text"] == selected, (st["label"], selected)
        # שורה אחת, באותה שורה של הכותרת.
        geo = pg.evaluate(
            """() => { const l = document.getElementById('alt-label').getBoundingClientRect();
                       const t = document.getElementById('alt-title').getBoundingClientRect();
                       const lh = parseFloat(getComputedStyle(document.getElementById('alt-label')).lineHeight) || 20;
                       return {h: l.height, lh, dy: Math.abs((l.top + l.bottom) / 2 - (t.top + t.bottom) / 2)}; }"""
        )
        assert geo["h"] <= geo["lh"] * 1.5 and geo["dy"] < 8, geo
        # כרטיס ברצועה: שם ושבוע מוקטן בשורה אחת.
        row = pg.evaluate(
            """() => { const c = document.querySelector('#alt-cards .alt-card');
                       const n = c.querySelector('.alt-card-name').getBoundingClientRect();
                       const m = c.querySelector('.mini').getBoundingClientRect();
                       return Math.abs((n.top + n.bottom) / 2 - (m.top + m.bottom) / 2); }"""
        )
        assert row < 4, row
        # החלפת חלופה: התווית עוברת לנבחרת החדשה.
        pg.click("#alt-cards .alt-card:not(.is-selected) >> nth=0")
        pg.wait_for_timeout(1200)
        st2 = _state(pg)
        selected2 = pg.evaluate(
            "document.querySelector('#alt-cards .alt-card.is-selected .alt-card-label').textContent.trim()"
        )
        assert st2["label"]["text"] == selected2, (st2["label"], selected2)
        _assert_names_whole_and_lines_whole(st2, "אחרי החלפת חלופה")
    finally:
        ctx.close()


# ==========================================================================
# 5. שינוי גודל: גבוה → נמוך → נמוך מאוד → גבוה
# ==========================================================================
def test_resizing_tall_short_tall_restores_the_full_view(browser, server):
    ctx, pg = _open(browser, server, TALL)
    try:
        first = _state(pg)
        assert first["fit"] == "1"
        _resize(pg, STEP3[0])
        assert _state(pg)["fit"] == "3"
        _resize(pg, STEP4[1])
        assert _state(pg)["fit"] == "4"
        _resize(pg, TALL)
        back = _state(pg)
        assert back["fit"] == "1" and not back["strip"] and not back["label"]["shown"], back["fit"]
        assert back["slot"] == first["slot"], (first["slot"], back["slot"])
        assert all(back["facts"])
        _assert_three_lines(back, "חזרה ל-1920x1500")
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


def test_once_settled_the_fit_does_not_keep_changing(browser, server):
    """אין לולאה בין שני צעדים: אחרי שהדף נח, אף מאפיין של ההתאמה אינו משתנה."""
    ctx, pg = _open(browser, server, STEP3[0])
    try:
        changes = pg.evaluate(
            """() => new Promise(done => {
                 let n = 0;
                 const mo = new MutationObserver(list => { n += list.length; });
                 const g = document.getElementById('schedule-grid');
                 mo.observe(g, {attributes: true, subtree: true,
                                attributeFilter: ['style', 'data-lines', 'class']});
                 mo.observe(document.getElementById('step-schedule'),
                            {attributes: true, attributeFilter: ['data-fit', 'class']});
                 setTimeout(() => { mo.disconnect(); done(n); }, 2000);
               })"""
        )
        assert changes == 0, f"{changes} שינויים בדף שאמור לנוח"
    finally:
        ctx.close()


# ==========================================================================
# 6. מה שבלוק מקוצר אינו מראה — בשם הנגיש, ב-title ובפאנל
# ==========================================================================
def test_every_block_names_its_full_content(browser, server):
    ctx, pg = _open(browser, server, STEP3[0])
    try:
        st = _state(pg)
        picks = pg.evaluate(
            """() => { const sch = window.slotwise.getRuntime().solve
                         .schedules[window.slotwise.getState().activeSchedule];
                       return sch.picks.map(p => ({code: p.code, kind: p.kind, lecturer: p.lecturer})); }"""
        )
        by_code = {}
        for p in picks:
            by_code.setdefault(p["code"], []).append(p)
        for b in st["blocks"]:
            assert b["label"] == b["title"], b
            assert b["name"]["text"] in b["label"], b
            options = by_code[b["code"]]
            assert any(
                (not p["kind"] or p["kind"] in b["label"])
                and (not p["lecturer"] or
                     GRID["labelLecturer"].replace("{lecturer}", p["lecturer"]) in b["label"])
                for p in options
            ), (b["label"], options)
        # ‏בלוק שקוצר: לחיצה מציגה את המרצה, את הסוג ואת השעה בפאנל.
        idx = next(i for i, b in enumerate(st["blocks"]) if b["lines"])
        pg.evaluate(f"document.querySelectorAll('#schedule-grid .ev')[{idx}].click()")
        pg.wait_for_timeout(600)
        panel = pg.evaluate("document.getElementById('meeting-detail-body').textContent")
        block = st["blocks"][idx]
        assert block["name"]["text"] in panel
        assert block["who"] is None or block["who"]["text"].split(" · ")[0] in panel, (block, panel)
        assert block["when"]["text"].split(" · ")[0] in panel, (block, panel)
    finally:
        ctx.close()


# ==========================================================================
# 7. הדפסה מחלונות שבהם המסך מתאים את עצמו
# ==========================================================================
@pytest.mark.parametrize("size", [STEP4[0], STEP3[0]], ids=lambda s: f"{s[0]}x{s[1]}")
def test_print_keeps_three_lines_in_every_block(browser, server, size):
    ctx, pg = _open(browser, server, size)
    try:
        assert _state(pg)["fit"] in ("3", "4")
        pg.emulate_media(media="print")
        pg.wait_for_timeout(1000)
        st = _state(pg)
        assert st["fit"] is None and not st["strip"], (st["fit"], st["strip"])
        _assert_three_lines(st, f"הדפסה מ-{size}")
        assert not st["innerScroll"]
        pg.emulate_media(media="screen")
        pg.wait_for_timeout(900)
        assert _state(pg)["fit"] in ("3", "4")
        assert pg.errors == []  # type: ignore[attr-defined]
    finally:
        ctx.close()


# ==========================================================================
# 8. מסך צר — בלי שינוי
# ==========================================================================
def test_narrow_screens_get_none_of_the_fitting(browser, server):
    ctx, pg = _open(browser, server, (1199, 700))
    try:
        st = _state(pg)
        assert st["fit"] is None and not st["strip"] and not st["label"]["shown"], st["fit"]
        assert all(st["facts"]) and all(st["cardLabels"])
        _assert_three_lines(st, "1199x700")
    finally:
        ctx.close()
