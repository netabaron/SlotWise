# -*- coding: utf-8 -*-
"""אשכולות קורסי בחירה על המסך — שלושת המסלולים, בדפדפן אמיתי.

‏``tests/test_elective_clusters.py`` בודק את הנתונים ואת נקודת הקצה. כאן
נבדק מה שרק דפדפן יודע לומר:

* קבוצות הבחירה של **הנדסת תוכנה** ושל **תעשייה וניהול** נראות בדיוק כפי
  שנראו — הן באות מפרק השנתון, והשינוי לא נגע בהן.
* **מתמטיקה שימושית** מציגה עכשיו את ארבעת התחומים שלה. המשיכה תלויה גם
  במועד הכניסה, ולכן ``fetchElectives`` חייב לשלוח אותו; בלעדיו היה חוזר
  ``available: false`` והחלק היה נשאר מוסתר.
* שורה שהשנתון מדפיס בלי מספר קורס מוצגת כמידע ו**אין לה תיבת סימון**.
  תיבה כזאת הייתה מוסיפה קוד ריק ל-``state.codes``, בשקט.
"""

from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import create_app  # noqa: E402

SOFTWARE = "הנדסת תוכנה"
INDUSTRY = "הנדסת תעשייה וניהול"
MATH = "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה"

MATH_TITLES = [
    "תחום AI",
    "תחום האלגוריתמים",
    "תחום בתורת המערכות, הבקרה ועיבוד אותות",
    "תחום אחר או מתמטיקה",
]


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
    sync_playwright = pytest.importorskip(
        "playwright.sync_api", reason="אין Playwright מותקן"
    ).sync_playwright
    with sync_playwright() as pw:
        try:
            instance = pw.chromium.launch()
        except Exception as exc:  # אין דפדפן מותקן — לא כישלון של הקוד
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture()
def page(browser, server):
    ctx = browser.new_context()
    p = ctx.new_page()
    errors: list[str] = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(server)
    p.wait_for_timeout(1500)
    p.errors = errors  # type: ignore[attr-defined]
    try:
        yield p
    finally:
        ctx.close()


def _expand(page, step_id: str) -> None:
    """שלב שנסגר מתחת לאצבע אינו נעילה — פותחים אותו וממשיכים."""
    page.evaluate(
        """(id) => {
      const s = document.getElementById(id);
      if (s && s.classList.contains('is-collapsed')) {
        const b = document.getElementById(id + '-toggle');
        if (b) b.click();
      }
    }""",
        step_id,
    )
    page.wait_for_timeout(200)


def choose(page, program: str, intake: str = "", year: str = "1") -> None:
    """בוחר זהות מלאה. מסלול עם מועדי כניסה נשאל מועד ומספר סמסטר."""
    _expand(page, "step-year")
    page.select_option("#select-program", program)
    page.wait_for_timeout(700)
    _expand(page, "step-year")
    if intake:
        page.select_option("#select-intake", intake)
        page.wait_for_timeout(700)
        _expand(page, "step-year")
        page.select_option("#select-plan-semester", "1")
    else:
        page.select_option("#select-year", year)
        _expand(page, "step-year")
        page.select_option("#select-term", "א")
    page.wait_for_timeout(2000)


def electives_on_screen(page) -> dict:
    return page.evaluate(
        """() => ({
      hidden: document.getElementById('electives').hidden,
      title: (document.getElementById('electives-title') || {}).textContent || '',
      groups: [...document.querySelectorAll('.elective-cluster-title')]
                .map(x => (x.textContent || '').trim()),
      chips: [...document.querySelectorAll('.elective-cluster')]
                .map(x => x.querySelectorAll('.elective-chip').length),
      pills: document.querySelectorAll('#electives-groups .elective-pill').length,
      checkboxes: document.querySelectorAll(
        '#electives-groups .elective-chip:not(.is-static)').length,
      noteRows: document.querySelectorAll('#electives-groups .elective-chip.is-static').length,
    })"""
    )


def test_software_engineering_looks_exactly_as_before(page):
    choose(page, SOFTWARE)
    seen = electives_on_screen(page)
    assert seen["hidden"] is False
    assert seen["groups"] == [
        "מדעים",
        "עיבוד אותות ורשתות תקשורת",
        "אלגוריתמים",
        "סמינרים",
        "הנדסת תוכנה",
        "מעבדות",
    ]
    assert seen["chips"] == [12, 10, 13, 10, 17, 13]
    assert page.errors == []


def test_industrial_engineering_looks_exactly_as_before(page):
    choose(page, INDUSTRY, year="2")
    page.select_option("#select-specialization", "מדעי הנתונים")
    page.wait_for_timeout(1500)
    seen = electives_on_screen(page)
    assert seen["hidden"] is False
    assert seen["groups"] == [
        "מערכות מידע ומדע הנתונים",
        "תכן ותפעול של מערכות ייצור ושירות",
        "ניהול",
        "המרכז לחינוך הנדסי וליזמות",
        "מדע וטכנולוגיה",
    ]


@pytest.mark.parametrize("intake", ["winter", "spring"])
def test_applied_maths_shows_its_four_domains(page, intake):
    choose(page, MATH, intake)
    seen = electives_on_screen(page)
    assert seen["hidden"] is False, "החלק נשאר מוסתר — כנראה לא נשלח מועד הכניסה"
    assert seen["title"] == "קורסי בחירה"
    assert seen["groups"] == MATH_TITLES
    # השנתון של מתמטיקה אינו קובע "קורס מכל תחום", ולכן אין גלולה.
    # שונתה באישור מפורש, 2026-09-27: הגלולה מחליפה את שורת הכלל.
    assert seen["pills"] == 0
    assert page.errors == []


def test_a_row_without_a_course_number_cannot_be_ticked(page):
    """שמונה שורות כאלה בפרק, ולכן 29 תיבות סימון מתוך 37 שורות."""
    choose(page, MATH, "winter")
    seen = electives_on_screen(page)
    assert seen["noteRows"] == 8
    assert seen["checkboxes"] == 29
