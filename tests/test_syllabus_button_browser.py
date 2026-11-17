"""כפתור "סילבוס" על כל כרטיס קורס (docs/SPEC_LINKS.md, Feature 2).

נבדק כאן, בשתי הרשימות — "הקורסים שלי" (‏#course-list) ועיון הקטלוג
‏(#catalog-results):

* בכל כרטיס קישור אחד בדיוק; ה-href שלו נושא את קוד הקורס, ‏target=_blank,
  ‏rel עם noopener; המילה "סילבוס" גלויה; ה-title וה-aria-label נושאים את
  שם הקורס; גובה לחיצה של 32px לפחות; והוא בפינה העליונה-שמאלית (סוף ב-RTL).
* לחיצה עליו — בעכבר או ב-Enter — פותחת לשונית חדשה ואינה משנה את הבחירה:
  ‏``localStorage["braude_schedule_builder_v1"]`` זהה לפני ואחרי, ותיבת
  הסימון והמחלקות של הכרטיס לא זזו.
* הוא אינו מודפס.

הקישור הולך ל-``/api/syllabus/<code>`` של השרת שלנו (‏src/syllabus.py), שמפנה
ל-PDF באתר המכללה. השרת עצמו אינו פונה לרשת (הוא רק קורא את
``syllabi.json``; ‏tests/test_syllabus_endpoint.py). הלשונית החדשה לא יוצאת
לרשת: כל בקשה ל-``/api/syllabus/`` ול-info.braude.ac.il נענית כאן בעמוד ריק
(``context.route``), והחלון הקופץ נסגר.
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

#: ‏בשמו המילולי, בכוונה — זה המפתח שהמצב השמור של הסטודנטים יושב בו.
STORAGE_KEY = "braude_schedule_builder_v1"

INDUSTRY = "הנדסת תעשייה וניהול"
YEDION = "https://info.braude.ac.il/**"
SYLLABUS_ROUTE = "**/api/syllabus/**"

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
WORD = STRINGS["app"]["courses"]["syllabus"]
assert WORD == "סילבוס"


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


def courses_step(browser, server, program: str, term: str = "א", scheme: str = "dark"):
    ctx = browser.new_context(viewport={"width": 1100, "height": 900}, color_scheme=scheme)
    # ‏הלשונית החדשה אינה יוצאת לידיעון, וגם לא ל-PDF שהשרת היה מפנה אליו.
    stub = lambda route: route.fulfill(  # noqa: E731
        status=200, content_type="text/html", body="<p>stub</p>"
    )
    ctx.route(YEDION, stub)
    ctx.route(SYLLABUS_ROUTE, stub)
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
    pg.wait_for_timeout(800)
    return ctx, pg


def browse(pg, query: str, count: int) -> None:
    pg.fill("#course-search", query)
    pg.wait_for_function(
        "n => document.querySelectorAll('#catalog-results .course-item').length === n",
        arg=count,
        timeout=15000,
    )
    pg.wait_for_timeout(300)


#: ‏כל כרטיס ברשימה: הקוד, השם, וכל קישור שבו.
CARDS = """sel => [...document.querySelectorAll(sel + ' .course-item')].map(card => {
  const links = [...card.querySelectorAll('a')];
  const a = card.querySelector('a.course-syllabus');
  const cr = card.getBoundingClientRect();
  const ar = a ? a.getBoundingClientRect() : null;
  return {
    code: card.querySelector('.course-code').textContent,
    name: card.querySelector('.course-name').textContent,
    links: links.length,
    syllabusLinks: links.filter(l => l.textContent.includes('סילבוס')).length,
    href: a ? a.href : null,
    target: a ? a.getAttribute('target') : null,
    rel: a ? a.getAttribute('rel') : null,
    text: a ? a.innerText : null,
    title: a ? a.getAttribute('title') : null,
    aria: a ? a.getAttribute('aria-label') : null,
    height: ar ? ar.height : 0,
    fromLeft: ar ? ar.left - cr.left : null,
    fromTop: ar ? ar.top - cr.top : null,
    fromRight: ar ? cr.right - ar.right : null,
  };
})"""


def check_cards(cards: list[dict]) -> None:
    assert cards, "אין כרטיסים לבדוק"
    for card in cards:
        assert card["links"] == 1, card
        assert card["syllabusLinks"] == 1, card
        assert card["code"] in card["href"], card
        assert card["target"] == "_blank", card
        assert "noopener" in card["rel"].split(), card
        assert WORD in card["text"], card
        assert card["name"] and card["name"] in card["title"], card
        assert card["name"] in card["aria"], card
        assert card["height"] >= 32, card
        # ‏הפינה העליונה בצד הסוף — שמאל ב-RTL — ולא ליד שם הקורס.
        assert card["fromLeft"] < card["fromRight"], card
        assert card["fromLeft"] <= 20 and card["fromTop"] <= 12, card


def saved(pg) -> str | None:
    return pg.evaluate("k => localStorage.getItem(k)", STORAGE_KEY)


CARD_STATE = """code => {
  const card = [...document.querySelectorAll('.course-item')]
    .find(c => c.querySelector('.course-code').textContent === code);
  return { cls: card.className, checked: card.querySelector('input[type=checkbox]').checked };
}"""


def click_without_side_effects(pg, list_sel: str, code: str, keyboard: bool = False) -> None:
    link = pg.locator(
        f"{list_sel} .course-item:has(.course-code:text-is('{code}')) a.course-syllabus"
    )
    pg.wait_for_timeout(600)
    before = saved(pg)
    state_before = pg.evaluate(CARD_STATE, code)
    with pg.context.expect_page() as popup_info:
        if keyboard:
            link.focus()
            pg.keyboard.press("Enter")
        else:
            link.click()
    popup = popup_info.value
    try:
        popup.wait_for_load_state()
        assert code in popup.url, popup.url
        assert f"/api/syllabus/{code}" in popup.url, popup.url
    finally:
        popup.close()
    pg.wait_for_timeout(800)
    assert saved(pg) == before, "לחיצה על סילבוס שינתה את הבחירה השמורה"
    assert pg.evaluate(CARD_STATE, code) == state_before, "לחיצה על סילבוס שינתה את הכרטיס"


# ==========================================================================
# 1. "הקורסים שלי"
# ==========================================================================
@pytest.fixture(scope="module")
def industry(browser, server):
    ctx, pg = courses_step(browser, server, INDUSTRY)
    pg.wait_for_function(
        "() => document.querySelectorAll('#course-list .course-item').length > 0", timeout=15000
    )
    yield pg
    ctx.close()


def test_every_card_in_my_courses_has_one_syllabus_link(industry):
    check_cards(industry.evaluate(CARDS, "#course-list"))
    assert industry.errors == []


def test_the_link_is_the_one_helper_with_the_code_encoded(industry, server):
    cards = industry.evaluate(
        """() => [...document.querySelectorAll('#course-list .course-item')].map(c => ({
          code: c.querySelector('.course-code').textContent,
          href: c.querySelector('a.course-syllabus').href,
          raw: c.querySelector('a.course-syllabus').getAttribute('href'),
        }))"""
    )
    assert cards
    for card in cards:
        # ‏אותו שרת, ‏/api/syllabus/<code> — לא ישר למכללה.
        assert card["href"] == f"{server}api/syllabus/{card['code']}", card
        assert card["raw"] == f"/api/syllabus/{card['code']}", card


def test_clicking_on_a_selected_and_an_unselected_card_changes_nothing(industry):
    states = industry.evaluate(
        """() => [...document.querySelectorAll('#course-list .course-item')].map(c => ({
          code: c.querySelector('.course-code').textContent,
          checked: c.querySelector('input[type=checkbox]').checked,
          disabled: c.querySelector('input[type=checkbox]').disabled,
        }))"""
    )
    pick = next(s for s in states if not s["disabled"])
    picked = pick["code"]
    box = f"#course-list .course-item:has(.course-code:text-is('{picked}')) input"
    # ‏כרטיס מסומן — דרך תיבת הסימון, לא דרך הסילבוס.
    if not pick["checked"]:
        industry.click(box)
        industry.wait_for_timeout(800)
    assert industry.evaluate(CARD_STATE, picked)["checked"] is True
    assert saved(industry) is not None, "אין מצב שמור להשוות אליו"
    assert picked in json.loads(saved(industry))["codes"]
    click_without_side_effects(industry, "#course-list", picked)

    # ‏ואותו כרטיס כשאינו מסומן.
    industry.click(box)
    industry.wait_for_timeout(800)
    assert industry.evaluate(CARD_STATE, picked)["checked"] is False
    click_without_side_effects(industry, "#course-list", picked)
    click_without_side_effects(industry, "#course-list", picked, keyboard=True)
    assert industry.errors == []


def test_the_link_is_not_printed(industry):
    industry.emulate_media(media="print")
    try:
        shown = industry.evaluate(
            """() => [...document.querySelectorAll('a.course-syllabus')]
              .filter(a => getComputedStyle(a).display !== 'none').length"""
        )
    finally:
        industry.emulate_media(media="screen")
    assert shown == 0


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_visible_in_both_themes_with_a_focus_ring(browser, server, scheme):
    ctx, pg = courses_step(browser, server, INDUSTRY, scheme=scheme)
    try:
        pg.wait_for_function(
            "() => document.querySelectorAll('#course-list a.course-syllabus').length > 0",
            timeout=15000,
        )
        pg.locator("#course-list a.course-syllabus").first.focus()
        pg.keyboard.press("Shift+Tab")
        pg.keyboard.press("Tab")
        look = pg.evaluate(
            """() => {
              const a = document.activeElement;
              const s = getComputedStyle(a);
              const card = getComputedStyle(a.closest('.course-item'));
              return { cls: a.className, color: s.color, bg: card.backgroundColor,
                       outline: s.outlineStyle, width: s.outlineWidth };
            }"""
        )
        assert look["cls"] == "course-syllabus", look
        assert look["color"] != look["bg"], look
        assert look["outline"] == "solid" and look["width"] == "2px", look
        assert pg.errors == []
    finally:
        ctx.close()


# ==========================================================================
# 2. עיון הקטלוג
# ==========================================================================
def test_every_catalog_row_has_one_syllabus_link_and_clicking_adds_nothing(browser, server):
    ctx, pg = courses_step(browser, server, "other")
    try:
        assert pg.locator("#catalog-browse").is_visible()
        browse(pg, "פיזיקה 2", 5)
        check_cards(pg.evaluate(CARDS, "#catalog-results"))
        code = pg.evaluate(
            "() => document.querySelector('#catalog-results .course-item .course-code').textContent"
        )
        assert pg.evaluate(CARD_STATE, code)["checked"] is False
        click_without_side_effects(pg, "#catalog-results", code)
        codes = json.loads(saved(pg) or "{}").get("codes", [])
        assert code not in codes, codes
        assert pg.errors == []
    finally:
        ctx.close()


def test_catalog_rows_with_a_plan_carry_it_too(browser, server):
    """תעשייה וניהול בקיץ: עיון בקטלוג עם תוכנית — אותו כרטיס, אותו קישור."""
    ctx, pg = courses_step(browser, server, INDUSTRY, term="קיץ")
    try:
        assert pg.locator("#catalog-browse").is_visible()
        browse(pg, "פיזיקה 2", 5)
        check_cards(pg.evaluate(CARDS, "#catalog-results"))
        assert pg.errors == []
    finally:
        ctx.close()
