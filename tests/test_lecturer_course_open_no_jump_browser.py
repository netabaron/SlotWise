"""פתיחת קורס בשלב המרצים אינה מקפיצה את העמוד (docs/DESIGN.md, "Scroll
behaviour", פריט 3, "Opening a course glides its head below the header",
‏2026-10-16; החליף את "keeps its head in place" של 2026-10-13).

הבאג: ‏``rebuild()`` מרוקן את ‏``#lecturer-courses`` לפני שהוא בונה אותו
מחדש. כל עוד המכולה ריקה העמוד קצר מהמסך, הדפדפן מצמיד את ‏scrollY ל-0,
והוא נשאר 0 גם אחרי הבנייה. ב-1440x900: ‏605 → 0 בפריים אחד. ואחרי התיקון
של 2026-10-13: כשהקורס שנסגר מעל גבוה מ-‏scrollY, השארת הראש במקומו דרשה
‏scrollY שלילי — הראש קפץ 85–400px והעמוד נחת ב-0 (נמדד על הקטלוג האמיתי).

מה נבדק כאן: לוחצים על ראש קורס סגור ודוגמים בכל פריים —
  * אף פריים לא מזיז את הראש יותר מ-‎``MAX_STEP``‎;
  * הוא נגמר מתחת לכותרת העמוד, היכן שהוא נדבק, או במקום המוגבל כשהעמוד
    קצר מדי;
  * ‏scrollY אף פעם לא יורד ל-0 כשהיעד נמוך יותר;
  * הפוקוס נשאר על הראש, וההדבקה עובדת אחרי הגלישה.
שני מצבים: הראש באמצע המסך (קל), והראש כ-120px מעל תחתית המסך עם ‏scrollY
קטן מגובה הקורס שנסגר מעליו (המקרה האמיתי). ועוד: בלי תנועה — מיד.

רץ על מסד ה-fixture (‏``scripts/seed_dev_data.py --fixture``), כמו ב-CI.
"""

from __future__ import annotations

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

DESKTOP = (1440, 900)
#: ‏התזוזה הגדולה ביותר שמותרת לראש הקורס בין שני פריימים.
MAX_STEP = 60
#: ‏סטייה מותרת מהיעד בסוף הגלישה.
LANDING_TOLERANCE = 2
#: ‏במקרה האמיתי: ראש הקורס הבא כ-120px מעל תחתית המסך.
FROM_BOTTOM = 120

#: ‏דוגם את ראש הקורס פעם אחת בכל פריים, בתוך ‏requestAnimationFrame
#: ‏ואחרי הקולבק של הגלישה באותו פריים — כלומר את המקום שהפריים הזה מצייר.
#: ‏לא במשימה ולא ב-timeout: דגימה מ-MessageChannel פספסה בעומס פריימים
#: ‏שרצו ברצף, וב-CI ראתה שני צעדים של 45px כאילו היו אחד (‏780 → 690).
#:
#: ‏הסדר: קולבקים של ‏rAF רצים לפי סדר הרישום. הלחיצה רושמת את הגלישה,
#: ‏ומאזין ‏click על ‏window (אחרי המאזין של הכפתור) רושם את הדגימה מחדש
#: ‏אחריה. משם כל אחד נרשם מחדש מתוך הקולבק שלו, והסדר נשמר.
#:
#: ‏דוגמים עד שהגלישה נגמרה — ‏will-change הוסר אחרי שהוצב, או שהראש לא
#: ‏זז שלושה פריימים — ולכל היותר ‎ms‎. הראש נמצא מחדש בכל דגימה לפי
#: ‏data-fk: ‏``rebuild()`` מחליף את האלמנט, ואלמנט שנשמר מראש כבר אינו
#: ‏במסמך.
SAMPLER = """([fk, ms]) => {
  const find = () => document.querySelector('[data-fk="' + fk + '"]');
  const box = document.getElementById('lecturer-courses');
  window.__samples = [];
  window.__settled = false;
  const t0 = performance.now();
  let clicked = false;
  let glided = false;
  let still = 0;
  let last = null;
  let id = 0;
  const sample = () => {
    const t = performance.now() - t0;
    const head = find();
    const top = head ? head.getBoundingClientRect().top : null;
    window.__samples.push({ t, top, y: window.scrollY });
    if (clicked) {
      if (box.style.willChange === 'transform') glided = true;
      still = top !== null && last !== null && Math.abs(top - last) < 0.01 ? still + 1 : 0;
      const ended = (glided && box.style.willChange === '') || still >= 3;
      if (ended || t >= ms) {
        window.removeEventListener('click', rearm);
        window.__settled = true;
        return;
      }
    }
    last = top;
    id = requestAnimationFrame(sample);
  };
  const rearm = () => {
    clicked = true;
    cancelAnimationFrame(id);
    id = requestAnimationFrame(sample);
  };
  window.addEventListener('click', rearm);
  id = requestAnimationFrame(sample);
}"""

#: ‏ראש הקורס הסגור הראשון אחרי הקורס הפתוח (או הראשון, אם אף אחד לא פתוח).
NEXT_CLOSED_HEAD = """() => {
  const heads = Array.from(
    document.querySelectorAll('#lecturer-courses button.lect-course-head')
  );
  const open = heads.findIndex((h) => h.getAttribute('aria-expanded') === 'true');
  const next = heads.slice(open + 1).find(
    (h) => h.getAttribute('aria-expanded') === 'false'
  );
  return next ? next.dataset.fk : null;
}"""


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


def _next(pg, key, wait=1500):
    pg.click(f"#step-{key}-next")
    pg.wait_for_timeout(wait)


def _to_lecturers(browser, server, size, reduced_motion="no-preference"):
    """הנדסת תוכנה, שנה 3, סמסטר א, הקורסים המומלצים, ו"המשך" עד המרצים."""
    ctx = browser.new_context(
        viewport={"width": size[0], "height": size[1]},
        color_scheme="light",
        reduced_motion=reduced_motion,
    )
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(server)
    pg.wait_for_timeout(3000)
    pg.select_option("#select-program", "הנדסת תוכנה")
    pg.select_option("#select-year", "3")
    pg.select_option("#select-term", "א")
    pg.wait_for_timeout(2500)
    _next(pg, "year")
    pg.click("#btn-restore-recommended")
    pg.wait_for_selector("#alt-cards .alt-card", timeout=20000)
    pg.wait_for_timeout(1000)
    _next(pg, "courses")
    _next(pg, "days")
    return ctx, pg, errors


def _place_head(pg, sel, top):
    """גולל כך שראש הקורס יעמוד ‎top‎ פיקסלים מראש המסך."""
    pg.evaluate(
        """([sel, top]) => {
          const r = document.querySelector(sel).getBoundingClientRect();
          window.scrollBy(0, r.top - top);
        }""",
        [sel, top],
    )
    pg.wait_for_timeout(600)


def _open_course_height(pg):
    return pg.evaluate(
        """() => {
          const c = document.querySelector('#lecturer-courses .lect-course.is-open');
          return c ? c.getBoundingClientRect().height : 0;
        }"""
    )


def _click_and_sample(pg, fk, ms=5000):
    pg.evaluate(SAMPLER, [fk, ms])
    pg.click(f'[data-fk="{fk}"]')
    pg.wait_for_function("window.__settled === true", timeout=10000)
    return pg.evaluate("window.__samples")


#: ‏איפה הראש נדבק (‎--sticky-top‎), כמה העמוד יכול לגלול, ומה מוזז.
GEOMETRY = """(sel) => {
  const head = document.querySelector(sel);
  return {
    top: head.getBoundingClientRect().top,
    sticky: parseFloat(getComputedStyle(head.parentNode).top),
    y: window.scrollY,
    max: document.documentElement.scrollHeight - window.innerHeight,
    focused: document.activeElement === head,
    transform: getComputedStyle(document.getElementById('lecturer-courses')).transform,
  };
}"""


def _landed(g):
    """מתחת לכותרת, היכן שהראש נדבק — או במקום המוגבל כשהעמוד קצר מדי."""
    clamped = g["y"] >= g["max"] - 1 and g["top"] > g["sticky"]
    return clamped or abs(g["top"] - g["sticky"]) <= LANDING_TOLERANCE


def _check_glide(pg, sel, top0, y0, samples):
    assert len(samples) > 10, f"מעט מדי פריימים נדגמו ({len(samples)})"
    assert pg.evaluate(
        f"document.querySelector('{sel}').getAttribute('aria-expanded')"
    ) == "true", "הקורס לא נפתח"
    g = pg.evaluate(GEOMETRY, sel)

    tops = [top0] + [s["top"] for s in samples]
    assert None not in tops, "ראש הקורס נעלם באמצע"
    steps = [
        (round(s["t"]), round(tops[i], 1), round(s["top"], 1))
        for i, s in enumerate(samples)
        if abs(s["top"] - tops[i]) > MAX_STEP
    ]
    assert not steps, (
        f"ראש הקורס זז יותר מ-{MAX_STEP}px בפריים אחד "
        f"(מ-{top0:.1f}px אל {g['top']:.1f}px); (t ms, מ-, אל): {steps[:5]}"
    )

    if g["y"] > 0:
        zero = [(round(s["t"]), s["y"]) for s in samples if s["y"] <= 0]
        assert not zero, (
            f"העמוד קפץ לראשו (scrollY לפני הלחיצה {y0}, יעד {g['y']}); "
            f"(t ms, scrollY): {zero[:5]}"
        )

    assert _landed(g), (
        f"הראש נגמר ב-{g['top']:.1f}px, לא מתחת לכותרת ({g['sticky']}px); "
        f"scrollY {g['y']} מתוך {g['max']}"
    )
    assert g["transform"] == "none", f"ההזזה לא הוסרה: {g['transform']}"
    assert g["focused"], "הפוקוס לא על ראש הקורס"

    # ‏ההדבקה עובדת אחרי הגלישה: גוללים בתוך הקורס, והראש נשאר מתחת לכותרת.
    pg.mouse.wheel(0, 200)
    pg.wait_for_timeout(400)
    stuck = pg.evaluate(GEOMETRY, sel)
    assert abs(stuck["top"] - stuck["sticky"]) <= 1, (
        f"ראש הקורס לא נדבק אחרי הגלישה ({stuck['top']:.1f}px, "
        f"נדבק ב-{stuck['sticky']}px)"
    )


def test_opening_the_next_course_from_mid_screen_glides_below_the_header(browser, server):
    ctx, pg, errors = _to_lecturers(browser, server, DESKTOP)
    try:
        fk = pg.evaluate(NEXT_CLOSED_HEAD)
        assert fk, "אין בשלב המרצים קורס סגור ללחוץ עליו"
        sel = f'[data-fk="{fk}"]'
        _place_head(pg, sel, DESKTOP[1] / 2)
        y0 = pg.evaluate("window.scrollY")
        top0 = pg.evaluate(f"document.querySelector('{sel}').getBoundingClientRect().top")
        assert y0 > 0, f"העמוד לא נגלל לפני הלחיצה (scrollY={y0})"
        assert 0 < top0 < DESKTOP[1], f"ראש הקורס לא על המסך ({top0:.1f}px)"

        samples = _click_and_sample(pg, fk)
        _check_glide(pg, sel, top0, y0, samples)
        assert not errors, errors
    finally:
        ctx.close()


def test_opening_the_next_course_near_the_bottom_glides_without_a_jump(browser, server):
    """המקרה האמיתי: הקורס שנסגר מעל גבוה מ-‏scrollY. ב-1920x1080 אין אותו
    במסד ה-fixture: בראש העמוד הראש הבא כבר ב-797px, ואי אפשר להביא אותו
    ל-120px מעל התחתית."""
    size = DESKTOP
    ctx, pg, errors = _to_lecturers(browser, server, size)
    try:
        fk = pg.evaluate(NEXT_CLOSED_HEAD)
        assert fk, "אין בשלב המרצים קורס סגור ללחוץ עליו"
        sel = f'[data-fk="{fk}"]'
        _place_head(pg, sel, size[1] - FROM_BOTTOM)
        y0 = pg.evaluate("window.scrollY")
        top0 = pg.evaluate(f"document.querySelector('{sel}').getBoundingClientRect().top")
        closing = _open_course_height(pg)
        assert abs(top0 - (size[1] - FROM_BOTTOM)) <= 2, (
            f"ראש הקורס לא במקום ({top0:.1f}px)"
        )
        assert 0 < y0 < closing, (
            f"זה לא המקרה הקשה: scrollY {y0}, הקורס שנסגר {closing:.0f}px"
        )

        samples = _click_and_sample(pg, fk)
        _check_glide(pg, sel, top0, y0, samples)
        assert not errors, errors
    finally:
        ctx.close()


def test_reduced_motion_opens_the_next_course_instantly(browser, server):
    ctx, pg, errors = _to_lecturers(browser, server, DESKTOP, reduced_motion="reduce")
    try:
        fk = pg.evaluate(NEXT_CLOSED_HEAD)
        assert fk, "אין בשלב המרצים קורס סגור ללחוץ עליו"
        sel = f'[data-fk="{fk}"]'
        _place_head(pg, sel, DESKTOP[1] - FROM_BOTTOM)
        top0 = pg.evaluate(f"document.querySelector('{sel}').getBoundingClientRect().top")

        samples = _click_and_sample(pg, fk, ms=800)
        g = pg.evaluate(GEOMETRY, sel)
        assert _landed(g), (
            f"הראש נגמר ב-{g['top']:.1f}px, לא מתחת לכותרת ({g['sticky']}px); "
            f"scrollY {g['y']} מתוך {g['max']}"
        )
        # ‏מיד: כל פריים שבו הראש כבר זז נמצא כבר ביעד, בלי ביניים.
        between = [
            (round(s["t"]), round(s["top"], 1))
            for s in samples
            if abs(s["top"] - top0) > 0.5 and abs(s["top"] - g["top"]) > 0.5
        ]
        assert not between, f"בלי תנועה, ובכל זאת היו פריימים בדרך: {between[:5]}"
        assert g["transform"] == "none", f"הזזה בלי תנועה: {g['transform']}"
        assert g["focused"], "הפוקוס לא על ראש הקורס"
        assert not errors, errors
    finally:
        ctx.close()
