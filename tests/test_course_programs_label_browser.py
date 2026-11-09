"""שלב הקורסים: ליד כל תוצאת חיפוש — של איזה מסלול הקורס.

חיפוש "פיזיקה 2" מחזיר חמישה קורסים כמעט זהים, כל אחד של מחלקה אחרת. בלי
תווית, הדרך היחידה לדעת איזה מהם שלך הייתה לפתוח את השנתון. נבדק כאן:

* ליד השם תווית שקטה (‏--muted, ‏13px): "· תעשייה וניהול". יותר משני
  מסלולים ⇐ שניים ו-"+N", והמסלול של הסטודנט/ית ראשון. השמות המלאים ב-title.
* הקורס מהתוכנית שלך ראשון, עם התג "[בתוכנית-סמסטר N]".
* כשכמה תוצאות נושאות אותו שם ואחת מהן בתוכנית — שורה אחת מעל הרשימה:
  "בתוכנית שלך: פיזיקה 2 IE (11210)". היא **מחוץ** ל-listbox: שם מותרות רק
  אפשרויות, ובדיקות קיימות לוחצות על ה-li הראשון ומצפות לתוצאה.
* אותה תווית בשורות עיון הקטלוג.
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

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import create_app  # noqa: E402

INDUSTRY = "הנדסת תעשייה וניהול"
SOFTWARE = "הנדסת תוכנה"


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


#: ‏סמסטר א׳: בקטלוג הקפוא לסמסטר ב׳ אין עדיין מועדים, ושם נפתח חלון
#: ‏"המועדים עוד לא פורסמו" שחוסם את "המשך" (test_times_not_published_browser).
def courses_step(browser, server, program: str, term: str = "א"):
    ctx = browser.new_context(viewport={"width": 1100, "height": 900}, color_scheme="dark")
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.goto(server)
    pg.wait_for_timeout(2000)
    pg.select_option("#select-program", program)
    pg.select_option("#select-year", "1")
    pg.select_option("#select-term", term)
    pg.wait_for_timeout(2000)
    if pg.locator("#no-times-dialog[open]").count():
        pg.click("#no-times-ok")
    pg.click("#step-year-next")
    pg.wait_for_timeout(600)
    return ctx, pg


def search(pg, query: str, count: int) -> None:
    pg.fill("#course-search", query)
    pg.wait_for_function(
        "n => document.querySelectorAll('#course-search-results li[role=option]').length >= n",
        arg=count,
        timeout=15000,
    )
    pg.wait_for_timeout(300)


#: כל אפשרות ברשימה: הקוד, התווית, התג, ומה שמבדיל תווית שקטה משם.
OPTIONS = """() => [...document.querySelectorAll('#course-search-results li[role=option]')].map(li => {
  const label = li.querySelector('.course-programs');
  const name = li.querySelector('.course-name');
  const probe = document.createElement('span');
  probe.style.color = 'var(--muted)';
  li.appendChild(probe);
  const muted = getComputedStyle(probe).color;
  probe.remove();
  return {
    code: li.querySelector('.course-code').textContent,
    name: name.textContent,
    labels: li.querySelectorAll('.course-programs').length,
    label: label ? label.textContent : null,
    title: label ? label.getAttribute('title') : null,
    nextToName: !!label && name.nextElementSibling === label,
    color: label ? getComputedStyle(label).color : null,
    nameColor: getComputedStyle(name).color,
    size: label ? getComputedStyle(label).fontSize : null,
    muted: muted,
    tag: li.querySelector('.tag').textContent,
  };
})"""

HINT = """() => {
  const hint = document.getElementById('course-search-hint');
  const list = document.getElementById('course-search-results');
  return {
    text: hint.textContent,
    hidden: hint.hidden,
    insideList: list.contains(hint),
    beforeList: !!(hint.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING),
    codeDir: (hint.querySelector('bdi.code') || {getAttribute: () => null}).getAttribute('dir'),
    plainLis: list.querySelectorAll('li:not([role=option])').length,
  };
}"""


@pytest.fixture(scope="module")
def industry_physics(browser, server):
    ctx, pg = courses_step(browser, server, INDUSTRY)
    search(pg, "פיזיקה 2", 5)
    yield {"options": pg.evaluate(OPTIONS), "hint": pg.evaluate(HINT), "errors": pg.errors}
    ctx.close()


def test_each_result_names_the_program_that_owns_it(industry_physics):
    by_code = {o["code"]: o for o in industry_physics["options"]}
    expected = {
        "11026": "· ביוטכנולוגיה",
        "11210": "· תעשייה וניהול",
        "11212": "· מכונות",
        "11232": "· חשמל ואלקטרוניקה",
        "421209": "· הנדסה אזרחית",
    }
    assert {code: by_code[code]["label"] for code in expected} == expected
    assert by_code["11210"]["title"] == "בתוכנית הלימודים של: הנדסת תעשייה וניהול"
    for option in industry_physics["options"]:
        assert option["labels"] == 1, option
        assert option["nextToName"], f"התווית חייבת לשבת מיד אחרי השם: {option}"
        assert option["color"] == option["muted"] != option["nameColor"], option
        assert option["size"] == "13px", option
    assert industry_physics["errors"] == []


def test_the_students_own_course_is_first_and_tagged_in_plan(industry_physics):
    options = industry_physics["options"]
    assert options[0]["code"] == "11210", [o["code"] for o in options]
    assert options[0]["tag"] == "[בתוכנית-סמסטר 3]", options[0]
    for option in options[1:]:
        assert option["tag"] == "[מחוץ לתוכנית]", option


def test_one_line_above_the_list_names_the_students_own_course(industry_physics):
    hint = industry_physics["hint"]
    assert hint["hidden"] is False, hint
    assert hint["text"] == "בתוכנית שלך: פיזיקה 2 IE (11210)", hint
    assert hint["codeDir"] == "ltr", hint
    assert hint["beforeList"] and not hint["insideList"], hint
    # ‏ה-listbox נשאר אפשרויות בלבד — ה-li הראשון הוא תוצאה.
    assert hint["plainLis"] == 0, hint


def test_more_than_two_programs_show_two_and_a_count(browser, server):
    """‏11003 (חדו"א 1) בתוכנית של ארבעה מסלולים; המסלול שלך ראשון."""
    ctx, pg = courses_step(browser, server, INDUSTRY)
    try:
        search(pg, "11003", 1)
        option = pg.evaluate(OPTIONS)[0]
        assert option["code"] == "11003"
        assert option["label"] == "· תעשייה וניהול, הנדסה אזרחית +2", option
        assert option["title"] == (
            "בתוכנית הלימודים של: הנדסת תעשייה וניהול, הנדסה אזרחית, "
            "הנדסת ביוטכנולוגיה, הנדסת מכונות"
        ), option
        # תוצאה אחת — אין "תאומים", ולכן אין שורה מעל הרשימה.
        assert pg.evaluate(HINT)["hidden"] is True
        assert pg.errors == []
    finally:
        ctx.close()


def test_no_line_when_none_of_the_twins_is_in_your_plan(browser, server):
    """לתוכנה יש פיזיקה משלה (‏61181), ואף "פיזיקה 2" אינו שלה."""
    ctx, pg = courses_step(browser, server, SOFTWARE)
    try:
        search(pg, "פיזיקה 2", 5)
        assert pg.evaluate(HINT)["hidden"] is True
        options = pg.evaluate(OPTIONS)
        assert all(o["tag"] == "[מחוץ לתוכנית]" for o in options), options
        assert all(o["labels"] == 1 for o in options), options
        assert pg.errors == []
    finally:
        ctx.close()


BROWSE_ROWS = """() => [...document.querySelectorAll('#catalog-results .course-item')].map(item => {
  const name = item.querySelector('.course-name');
  const label = item.querySelector('.course-programs');
  return {
    code: item.querySelector('.course-code').textContent,
    label: label ? label.textContent : null,
    nextToName: !!label && name.nextElementSibling === label,
  };
})"""


def test_catalog_browse_rows_carry_the_same_label(browser, server):
    """מסלול בלי תוכנית ⇐ עיון בקטלוג. אין "בתוכנית שלך" — אין תוכנית."""
    ctx, pg = courses_step(browser, server, "other")
    try:
        assert pg.locator("#catalog-browse").is_visible()
        pg.fill("#course-search", "פיזיקה 2")
        pg.wait_for_function(
            "() => document.querySelectorAll('#catalog-results .course-item').length === 5",
            timeout=15000,
        )
        rows = {r["code"]: r for r in pg.evaluate(BROWSE_ROWS)}
        assert rows["11210"]["label"] == "· תעשייה וניהול", rows
        assert rows["421209"]["label"] == "· הנדסה אזרחית", rows
        assert all(r["nextToName"] for r in rows.values()), rows
        assert pg.locator("#catalog-browse-hint").is_hidden()
        assert pg.errors == []
    finally:
        ctx.close()


def test_catalog_browse_names_your_course_when_you_have_a_plan(browser, server):
    """תעשייה וניהול בקיץ: אין רשימת סמסטר, יש תוכנית — עיון, עם השורה."""
    ctx, pg = courses_step(browser, server, INDUSTRY, term="קיץ")
    try:
        assert pg.locator("#catalog-browse").is_visible()
        pg.fill("#course-search", "פיזיקה 2")
        pg.wait_for_function(
            "() => document.querySelectorAll('#catalog-results .course-item').length === 5",
            timeout=15000,
        )
        pg.wait_for_timeout(300)
        hint = pg.locator("#catalog-browse-hint")
        assert hint.is_visible()
        assert hint.text_content() == "בתוכנית שלך: פיזיקה 2 IE (11210)"
        assert pg.errors == []
    finally:
        ctx.close()
