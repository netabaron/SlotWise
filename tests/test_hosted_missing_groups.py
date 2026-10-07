# -*- coding: utf-8 -*-
"""קורס בלי נתוני קבוצות, בשרת שאין לו רשת — מה נאמר עליו, ומה לא.

הרקע
-----
‏201009 ו-201015 (מתמטיקה שימושית) נמצאים בקטלוג, אבל הקבוצות שלהם הן
של סמסטר ב' ואין להן אף מפגש: הידיעון מדפיס להן "טרם נקבע" בעמודת המרצה
וטבלת שעות ריקה. סטודנט/ית שבוחרים את שניהם לסמסטר א' רואים אפוא שני
קורסים בלי קבוצות — וזו תשובה נכונה, לא תקלה.

שלוש תקלות היו בדרך שבה זה הוצג במצב המאורח (``allow_network=False``):

1. ‏``_ondemand_fetch`` קורא ל-``skip_all``, שתולה את אותו משפט אחד
   ("הנתונים מוגשים מהקטלוג… בלי פנייה לידיעון") על **כל** קוד שהתבקש.
   המשפט הזה נכתב לתוך ``reason`` של הבעיה ומחק את הסיבה האמיתית.
2. הממשק הציע "ניסיון חוזר מהידיעון" — כפתור שאין מאחוריו רשת.
3. שלב 4 היה נעול כל עוד אין ולו קורס אחד עם נתונים, ולכן מי שבחר/ה
   **רק** קורסים כאלה נשאר/ה על "ממתין לנתוני הקבוצות" לנצח.

הבדיקות כאן נועלות את שלושתן. ‏``allow_network=False`` הוא בדיוק המצב
המאורח, ו-``fetch_missing=True`` הוא מה שהממשק שולח תמיד.
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

from src.web.api import create_app  # noqa: E402

#: שני קורסים שהקטלוג מכיר, ושהקבוצות שלהם אינן של סמסטר א'.
NO_GROUPS = ["201009", "201015"]
#: קורס תקין לגמרי מאותו סמסטר — שומר מפני "תיקון" שמשתיק את כולם.
WITH_GROUPS = "11102"
YEAR = 'תשפ"ז'


@pytest.fixture()
def hosted():
    """הלקוח של השרת המאורח: קטלוג בלבד, בלי רשת."""
    return create_app({"allow_network": False}).test_client()


def courses(client, codes):
    res = client.post(
        "/api/courses",
        json={"codes": codes, "semester": "א", "year": YEAR, "fetch_missing": True},
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()


# ---------------------------------------------------------------- השרת
def test_bootstrap_says_there_is_no_fetching(hosted):
    """הממשק לומד מכאן שאין ממי לבקש משיכה חוזרת."""
    data = hosted.get("/api/bootstrap").get_json()
    assert data["features"]["fetch_on_demand"] is False


def test_the_blanket_skip_reason_does_not_erase_the_real_one(hosted):
    """הסיבה היא "אין קבוצות", לא "לא פנינו לידיעון"."""
    data = courses(hosted, NO_GROUPS + [WITH_GROUPS])
    problems = {p["code"]: p for p in data["not_offered"]}
    assert sorted(problems) == sorted(NO_GROUPS)
    for code in NO_GROUPS:
        problem = problems[code]
        assert problem["kind"] == "no_groups"
        assert "קבוצות" in problem["reason"]
        # המשפט הכללי הוא הקשר, ולא ההסבר. הוא נשאר — בשדה שלו.
        assert "בלי פנייה לידיעון" not in problem["reason"]
        assert "בלי פנייה לידיעון" in problem["fetch_reason"]


def test_a_course_that_does_have_groups_is_untouched(hosted):
    """הקורס התקין נבנה כרגיל ואינו נספר כבעיה."""
    data = courses(hosted, NO_GROUPS + [WITH_GROUPS])
    built = {c["code"] for c in data["courses"]}
    assert built == {WITH_GROUPS}
    assert data["sources"][WITH_GROUPS] != "unavailable"


def test_needs_scrape_is_false_when_the_groups_simply_are_not_there(hosted):
    """‏``needs_scrape`` הוא מה שהממשק נשען עליו כדי להציע משיכה."""
    data = courses(hosted, NO_GROUPS)
    for problem in data["not_offered"]:
        assert problem["needs_scrape"] is False


# ---------------------------------------------------------------- הממשק
from werkzeug.serving import make_server  # noqa: E402

STORAGE_KEY = "braude_schedule_builder_v1"
MATH = "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה"


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
    # ‏importorskip כאן ולא ברמת המודול: בלי Playwright מדלגים על בדיקות
    # הדפדפן בלבד, ובדיקות השרת שמעליהן ממשיכות לרוץ.
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


def _expand(page, step_id: str) -> None:
    """פותח שלב מקופל. קיפול אינו נעילה, והבדיקה מדברת על נעילה."""
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


@pytest.fixture()
def picked(browser, server):
    """דף שבו נבחרו מתמטיקה/חורף/סמסטר 3, ואז **רק** שני הקורסים חסרי הקבוצות."""
    ctx = browser.new_context()
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server)
    page.wait_for_timeout(1500)

    _expand(page, "step-year")
    page.select_option("#select-program", MATH)
    page.wait_for_timeout(700)
    _expand(page, "step-year")
    page.select_option("#select-intake", "winter")
    page.wait_for_timeout(700)
    _expand(page, "step-year")
    page.select_option("#select-plan-semester", "3")
    page.wait_for_timeout(2500)

    # הבחירה נכתבת ישירות למצב השמור: רשימת הסמסטר נבנית מהתוכנית, ושני
    # הקודים האלה אינם מומלצים לסמסטר שנבחר — בדיוק המצב שדווח.
    saved = json.loads(
        page.evaluate("() => localStorage.getItem('%s') || '{}'" % STORAGE_KEY)
    )
    saved["codes"] = list(NO_GROUPS)
    saved["manualCodes"] = list(NO_GROUPS)
    saved["autoCodes"] = []
    saved["provenanceReady"] = True
    saved["collapsed"] = {}
    page.evaluate(
        "(s) => localStorage.setItem('%s', JSON.stringify(s))" % STORAGE_KEY, saved
    )
    page.reload()
    page.wait_for_timeout(3500)
    # "המשך" על שלבים 1–3 כדי להגיע אל המרצים (Phase 8, באישור 2026-10-06)
    page.click("#step-year-next")
    page.click("#step-courses-next")
    page.click("#step-days-next")
    _expand(page, "step-lecturers")
    page.wait_for_timeout(600)
    page.errors = errors  # type: ignore[attr-defined]
    try:
        yield page
    finally:
        ctx.close()


def test_step_four_is_not_locked_on_courses_that_will_never_have_groups(picked):
    """אין למה להמתין, ולכן השלב אינו "ממתין"."""
    classes = picked.evaluate(
        "() => document.getElementById('step-lecturers').className"
    )
    assert "is-locked" not in classes
    summary = picked.evaluate(
        "() => document.getElementById('step-lecturers-state').textContent"
    )
    assert "ממתין" not in summary
    assert "אין נתוני קבוצות" in summary


def test_no_retry_button_anywhere_when_the_server_has_no_network(picked):
    """כפתור שאין מאחוריו רשת אינו מוצג — בשום שלב."""
    labels = picked.evaluate(
        "() => [...document.querySelectorAll('button')]"
        ".map(b => (b.textContent || '').trim())"
    )
    assert not [x for x in labels if "ניסיון חוזר" in x], labels


def test_the_explanation_is_plain_and_mentions_no_fetching(picked):
    """"לא נפתחו קבוצות" — ולא "לא פנינו לידיעון"."""
    text = picked.evaluate(
        "() => (document.getElementById('lecturer-courses') || {}).innerText || ''"
    )
    for code in NO_GROUPS:
        assert code in text
    assert "לא נפתח בסמסטר הזה" in text
    assert "בלי פנייה לידיעון" not in text
    assert picked.errors == []
