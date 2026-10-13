""""המשך" בטלפון אינו מקפיץ את העמוד (docs/DESIGN.md, "Scroll behaviour",
פריט 2, "No jump while the step above folds", ‏2026-10-13).

הבאג: בתחתית שלב הקורסים או המרצים, השלב שנסגר מתקפל **מעל** המסך. בלי
פיצוי, ראש השלב הבא קופץ בפריים אחד מאות פיקסלים למעלה (433 → ‎-236‎),
ורק אחרי ~450ms הגלילה החלקה מחזירה אותו מתחת לכותרת.

מה נבדק כאן, ב-390x844: ראש השלב הבא נדגם בכל פריים מהלחיצה ועד שהוא
נח. הוא אף פעם לא זז יותר מ-120px בפריים אחד, אף פעם לא עובר את מקומו
הסופי, ונח מתחת לכותרת הדביקה. תחת ‏prefers-reduced-motion אין תנועה בכלל,
ולכן שם הדרישה היא מהלך אחד: ראש השלב משתנה בפריים אחד לכל היותר, ישר
למקומו.

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

PHONE = (390, 844)
#: ‏התנועה הגדולה ביותר שמותרת לראש השלב בין שני פריימים.
MAX_FRAME_JUMP = 120
#: ‏סובלנות של מדידה (עיגול תת-פיקסלי) לבדיקת "לא עובר את מקומו".
EPS = 1.5

#: ‏מתחיל לדגום את ראש ‎sel‎ בכל פריים, עד שהוא נח: לפחות ‎minMs‎ מהתחלה,
#: ‏ואז 30 פריימים ברצף בלי תזוזה (או ‎maxMs‎ לכל היותר).
#: ‏הדגימה היא **אחרי** שהפריים צויר (‏rAF ואז ‏MessageChannel), כלומר מה
#: ‏שנראה על המסך: קריאה בתוך ה-rAF עצמו רצה לפני קריאות ה-rAF של העמוד
#: ‏באותו פריים, ורואה מיקום שאף פעם לא מגיע למסך.
SAMPLER = """([sel, minMs, maxMs]) => {
  const el = document.querySelector(sel);
  window.__samples = [];
  window.__settled = false;
  const t0 = performance.now();
  let still = 0;
  let last = null;
  const ch = new MessageChannel();
  ch.port1.onmessage = () => sample();
  const tick = () => ch.port2.postMessage(0);
  const sample = () => {
    const t = performance.now() - t0;
    const top = el.getBoundingClientRect().top;
    window.__samples.push({ t, top, y: window.scrollY });
    if (last !== null && Math.abs(top - last) < 0.5) still += 1; else still = 0;
    last = top;
    if ((t >= minMs && still >= 30) || t >= maxMs) {
      window.__settled = true;
      return;
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
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


def _page(browser, server, *, reduced):
    ctx = browser.new_context(
        viewport={"width": PHONE[0], "height": PHONE[1]},
        color_scheme="light",
        reduced_motion="reduce" if reduced else "no-preference",
        has_touch=True,
    )
    pg = ctx.new_page()
    pg.errors = []  # type: ignore[attr-defined]
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))  # type: ignore[attr-defined]
    pg.goto(server)
    pg.wait_for_timeout(3000)
    return ctx, pg


def _next(pg, key, wait=1500):
    pg.click(f"#step-{key}-next")
    pg.wait_for_timeout(wait)


def _to_courses(pg):
    """הנדסת תוכנה, שנה 3, סמסטר א, "המשך", הקורסים המומלצים."""
    pg.select_option("#select-program", "הנדסת תוכנה")
    pg.select_option("#select-year", "3")
    pg.select_option("#select-term", "א")
    pg.wait_for_timeout(2500)
    _next(pg, "year")
    pg.click("#btn-restore-recommended")
    pg.wait_for_selector("#alt-cards .alt-card", timeout=20000)
    pg.wait_for_timeout(1000)


def _tap_and_sample(pg, button, target):
    """גולל את "המשך" אל המסך כמו אגודל, ולוחץ עליו תוך דגימה בכל פריים."""
    pg.locator(button).scroll_into_view_if_needed()
    pg.wait_for_timeout(600)
    pg.evaluate(SAMPLER, [target, 1800, 6000])
    pg.tap(button)
    pg.wait_for_function("window.__settled === true", timeout=10000)
    samples = pg.evaluate("window.__samples")
    header_bottom = pg.evaluate(
        "document.getElementById('app-header').getBoundingClientRect().bottom"
    )
    return samples, header_bottom


def _assert_no_jump(samples, header_bottom, label, *, reduced):
    tops = [s["top"] for s in samples]
    assert len(tops) > 10, f"{label}: מעט מדי פריימים נדגמו ({len(tops)})"
    start, final = tops[0], tops[-1]

    if reduced:
        moves = [
            (samples[i]["t"], tops[i - 1], tops[i])
            for i in range(1, len(tops))
            if abs(tops[i] - tops[i - 1]) >= 0.5
        ]
        assert len(moves) <= 1, (
            f"{label}: בלי תנועה ראש השלב צריך להגיע במהלך אחד, וזז ב-{len(moves)} "
            f"פריימים (t ms, לפני, אחרי): {moves[:5]}"
        )

    jumps = [] if reduced else [
        (samples[i]["t"], tops[i - 1], tops[i])
        for i in range(1, len(tops))
        if abs(tops[i] - tops[i - 1]) > MAX_FRAME_JUMP
    ]
    assert not jumps, (
        f"{label}: ראש השלב קפץ יותר מ-{MAX_FRAME_JUMP}px בפריים אחד "
        f"(t ms, לפני, אחרי): {jumps[:5]}"
    )

    if start >= final:
        past = [(s["t"], s["top"]) for s in samples if s["top"] < final - EPS]
    else:
        past = [(s["t"], s["top"]) for s in samples if s["top"] > final + EPS]
    assert not past, (
        f"{label}: ראש השלב עבר את מקומו הסופי ({final:.1f}px) "
        f"וחזר אליו (t ms, top): {past[:5]}"
    )

    assert final >= header_bottom - EPS, (
        f"{label}: ראש השלב ({final:.1f}px) נח מתחת לכותרת? "
        f"תחתית הכותרת {header_bottom:.1f}px"
    )
    assert final <= header_bottom + PHONE[1] * 0.4, (
        f"{label}: ראש השלב ({final:.1f}px) לא הגיע לחלק העליון של המסך"
    )


@pytest.mark.parametrize("reduced", [False, True], ids=["motion", "reduced-motion"])
def test_courses_next_brings_days_without_a_jump(browser, server, reduced):
    ctx, pg = _page(browser, server, reduced=reduced)
    try:
        _to_courses(pg)
        samples, header_bottom = _tap_and_sample(pg, "#step-courses-next", "#step-days")
        _assert_no_jump(samples, header_bottom, "קורסים → ימים", reduced=reduced)
        assert not pg.errors, pg.errors
    finally:
        ctx.close()


@pytest.mark.parametrize("reduced", [False, True], ids=["motion", "reduced-motion"])
def test_lecturers_next_brings_the_results_without_a_jump(browser, server, reduced):
    ctx, pg = _page(browser, server, reduced=reduced)
    try:
        _to_courses(pg)
        _next(pg, "courses")
        _next(pg, "days")
        samples, header_bottom = _tap_and_sample(
            pg, "#step-lecturers-next", "#step-schedule"
        )
        _assert_no_jump(samples, header_bottom, "מרצים → תוצאה", reduced=reduced)
        assert not pg.errors, pg.errors
    finally:
        ctx.close()
