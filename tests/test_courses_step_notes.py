# -*- coding: utf-8 -*-
"""
שלב 2 אחרי הניקוי של 2026-09-27 (docs/DESIGN.md, "Elective clusters" ועיקרון 6).

מה נבדק
-------
* **✓ על הגלולה.** גלולת "לפחות קורס אחד" של אשכול מקבלת ✓ טורקיז כשנבחר
  ממנו קורס בסמסטר הזה, ומאבדת אותו כשהבחירה מוסרת. גלולה אחרת ("לפחות 2
  קורסים") אינה מקבלת ✓.
* **פתקי "רק אחד מ-".** חוק ``mutually_exclusive``/``only_one_counts``
  מוצג כשורת זהב אחת תחת כל אשכול שמחזיק לפחות אחד מהקורסים שלו.
* **רשימת החוקים איננה**: אין ‎#electives-rules‎, אין "בסמסטר הזה", אין
  כותרת המשנה "דרישות לתואר" ואין ציטוט מקור (קובץ ועמוד).
* **"מסלול אחר"** בבורר התוכנית, ושורת אי-ההתאמה בנ"ז כשורה אחת.
* **כרטיס 31101** אינו מדבר על ערך ה-``track``.
"""

from __future__ import annotations

import socket
import sys
import threading
from pathlib import Path
from urllib.parse import urlencode

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.web.api import create_app  # noqa: E402

SW = "הנדסת תוכנה"
CIVIL = "הנדסה אזרחית"
IND = "הנדסת תעשייה וניהול"
EL = "הנדסת חשמל ואלקטרוניקה"
DS = "מדעי הנתונים"
MATH = "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה"
OTHER_LABEL = "מסלול אחר"
MISMATCH = "סך הנקודות המומלץ לסמסטר הזה שונה בין השנתון לידיעון"


# ==========================================================================
# 1. בלי דפדפן
# ==========================================================================
@pytest.fixture(scope="module")
def client():
    return create_app(config={"allow_network": False}).test_client()


def test_the_other_program_is_called_other_route(client):
    programs = client.get("/api/bootstrap").get_json()["programs"]
    other = [p for p in programs if p["id"] == "other"]
    assert len(other) == 1 and other[0]["label"] == OTHER_LABEL


def test_31101_does_not_talk_about_its_track_field(client):
    res = client.get("/api/semester/7/courses?" + urlencode({"program": EL}))
    assert res.status_code == 200
    card = next(c for c in res.get_json()["courses"] if c["code"] == "31101")
    assert "track" not in card["note"]
    assert card["note"] == "יש להירשם לשני חלקי התכן ההנדסי בסמסטרים עוקבים."


# ==========================================================================
# 2. בדפדפן
# ==========================================================================
playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def server():
    from werkzeug.serving import make_server  # noqa: PLC0415

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = make_server("127.0.0.1", port, create_app(config={"allow_network": False}), threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as pw:
        try:
            instance = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
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
    p.wait_for_timeout(1200)
    try:
        yield p
    finally:
        assert errors == [], f"שגיאות JavaScript: {errors}"
        ctx.close()


def choose(page, program, year, term="א", specialization=""):
    page.select_option("#select-program", program)
    page.select_option("#select-year", str(year))
    page.select_option("#select-term", term)
    page.wait_for_timeout(1400)
    if specialization:
        page.select_option("#select-specialization", specialization)
        page.wait_for_timeout(1300)


def cluster(key: str) -> str:
    return f"#electives-groups .elective-cluster[data-key='{key}']"


def notes_under(page, key: str) -> list[str]:
    return [t.strip() for t in page.locator(cluster(key) + " .elective-cluster-note").all_inner_texts()]


# --------------------------------------------------------------- ✓ על הגלולה
def test_the_check_follows_the_selection(page):
    choose(page, SW, 4)
    pill = cluster("אלגוריתמים") + " .elective-pill"
    assert page.locator(pill).inner_text().strip() == "לפחות קורס אחד"
    assert page.locator(pill + " .elective-pill-check").count() == 0

    chip = page.locator(cluster("אלגוריתמים") + " .elective-chip[data-code]").first
    code = chip.get_attribute("data-code")
    page.click(cluster("אלגוריתמים") + " .elective-cluster-head")  # פתיחת האשכול לפני שימוש בשבב (באישור, 2026-10-05)
    chip.click()
    page.wait_for_timeout(700)
    assert page.locator(pill + " .elective-pill-check").count() == 1
    assert page.locator(pill + " .elective-pill-check").inner_text() == "✓"
    # רק האשכול שממנו נבחר — לא האחרים.
    assert page.locator(cluster("מעבדות") + " .elective-pill-check").count() == 0

    page.click(f"{cluster('אלגוריתמים')} .elective-chip[data-code='{code}']")
    page.wait_for_timeout(700)
    assert page.locator(pill + " .elective-pill-check").count() == 0


def test_the_check_is_teal(page):
    choose(page, SW, 4)
    page.click(cluster("מדעים") + " .elective-cluster-head")  # פתיחת האשכול לפני שימוש בשבב (באישור, 2026-10-05)
    page.locator(cluster("מדעים") + " .elective-chip[data-code]").first.click()
    page.wait_for_timeout(700)
    colours = page.evaluate(
        """() => {
      const check = document.querySelector("#electives-groups .elective-pill-check");
      const probe = document.createElement("span");
      probe.style.color = "var(--brand-wise)";
      document.body.appendChild(probe);
      const want = getComputedStyle(probe).color;
      probe.remove();
      return { got: getComputedStyle(check).color, want };
    }"""
    )
    assert colours["got"] == colours["want"]


def test_a_minimum_of_two_ticks_at_two(page):
    choose(page, CIVIL, 4, specialization="מבנים")
    two = cluster("מבנים · קבוצה 1")
    assert page.locator(two + " .elective-pill").inner_text().strip() == "לפחות 2 קורסים"
    page.click(two + " .elective-cluster-head")  # פתיחת האשכול לפני שימוש בשבב (באישור, 2026-10-05)
    page.locator(two + " .elective-chip[data-code]").nth(0).click()
    page.wait_for_timeout(700)
    assert page.locator(two + " .elective-pill-check").count() == 0, "אחד מתוך 2 — עוד אין ✓"
    page.locator(two + " .elective-chip[data-code]").nth(1).click()
    page.wait_for_timeout(700)
    assert page.locator(two + " .elective-pill-check").count() == 1


# ------------------------------------------------------- פתקי "רק אחד מ-"
def test_only_one_of_notes_sit_under_their_cluster(page):
    choose(page, SW, 4)
    page.click(cluster("מדעים") + " .elective-cluster-head")  # פתיחת האשכול לפני קריאת ההערות שלו (באישור, 2026-10-05)
    assert notes_under(page, "מדעים") == ["אפשר לקחת רק אחד מ-62002 ו-62023"]
    page.click(cluster("אלגוריתמים") + " .elective-cluster-head")  # פתיחת האשכול לפני קריאת ההערות שלו (באישור, 2026-10-05)
    assert notes_under(page, "אלגוריתמים") == ["אפשר לקחת רק אחד מ-61959 ו-62019"]
    page.click(cluster("מעבדות") + " .elective-cluster-head")  # פתיחת האשכול לפני קריאת ההערות שלו (באישור, 2026-10-05)
    assert notes_under(page, "מעבדות") == []


def test_a_rule_across_clusters_shows_under_each_of_them(page):
    # ‏251100 יושב גם ב"עיבוד אותות" וגם ב"הנדסת תוכנה"; ‏251965 רק בשני.
    choose(page, SW, 4)
    line = "אפשר לקחת רק אחד מ-251100 ו-251965"
    page.click(cluster("הנדסת תוכנה") + " .elective-cluster-head")  # פתיחת האשכול לפני קריאת ההערות שלו (באישור, 2026-10-05)
    assert line in notes_under(page, "הנדסת תוכנה")
    page.click(cluster("עיבוד אותות ורשתות תקשורת") + " .elective-cluster-head")  # פתיחת האשכול לפני קריאת ההערות שלו (באישור, 2026-10-05)
    assert line in notes_under(page, "עיבוד אותות ורשתות תקשורת")


def test_industrial_251966_and_51515_under_both_clusters(page):
    choose(page, IND, 2, specialization=DS)
    line = "אפשר לקחת רק אחד מ-51515 ו-251966"
    page.click(cluster(f"{DS} · המרכז לחינוך הנדסי וליזמות") + " .elective-cluster-head")  # פתיחת האשכול לפני קריאת ההערות שלו (באישור, 2026-10-05)
    assert line in notes_under(page, f"{DS} · המרכז לחינוך הנדסי וליזמות")
    page.click(cluster(f"{DS} · מערכות מידע ומדע הנתונים") + " .elective-cluster-head")  # פתיחת האשכול לפני קריאת ההערות שלו (באישור, 2026-10-05)
    assert line in notes_under(page, f"{DS} · מערכות מידע ומדע הנתונים")


def test_a_note_is_one_line(page):
    choose(page, SW, 4)
    heights = page.evaluate(
        """() => [...document.querySelectorAll('.elective-cluster-note')].map(n => {
      const lh = parseFloat(getComputedStyle(n).lineHeight) || parseFloat(getComputedStyle(n).fontSize) * 1.6;
      return n.getBoundingClientRect().height / lh;
    })"""
    )
    assert heights and all(h < 1.5 for h in heights), heights


# ------------------------------------------------------ מה שאינו מוצג עוד
def test_the_requirements_list_is_gone(page):
    choose(page, SW, 4)
    shown = page.inner_text("#electives")
    assert page.locator("#electives-rules").count() == 0
    assert page.locator(".electives-sub").count() == 0
    assert "דרישות לתואר" not in shown
    assert "בסמסטר הזה:" not in shown
    assert ".pdf" not in shown and "עמ׳" not in shown
    assert page.inner_text("#electives-title").strip() == "קורסי בחירה"


def test_the_other_route_label_in_the_picker(page):
    labels = page.locator("#select-program option").all_inner_texts()
    assert OTHER_LABEL in [t.strip() for t in labels]
    assert not any("עבודה מהקטלוג" in t for t in labels)


def test_the_credit_mismatch_is_one_line(page):
    choose(page, CIVIL, 4)
    note = page.evaluate(
        "() => { const e = document.getElementById('recommended-note'); return e && !e.hidden ? e.textContent.trim() : ''; }"
    )
    assert note == MISMATCH


# ------------------------------------------------------------- חוקי הרכב
COMPUTERS = "מחשבים (חומרה ותוכנה)"


def test_composition_is_one_line_under_the_core_cluster(page):
    choose(page, EL, 4, specialization=COMPUTERS)
    core = f"{COMPUTERS} · קורסי ליבה בהתמחות"
    page.click(cluster(core) + " .elective-cluster-head")  # פתיחת האשכול לפני קריאת ההערות שלו (באישור, 2026-10-05)
    assert notes_under(page, core) == ["מתוכם לפחות 3 מתחום החומרה ולפחות 3 מתחום התוכנה"]
    shown = page.inner_text("#electives")
    assert "לפחות 20 נ״ז" not in shown, "סך נ״ז ברמת התואר אינו מוצג"


def test_short_semester_lines(page):
    choose(page, CIVIL, 2)
    info = page.evaluate(
        "() => { const e = document.getElementById('semester-info'); return e && !e.hidden ? e.textContent.trim() : ''; }"
    )
    assert info == "קורסים כלליים וספורט: אפשר לשלב בכל סמסטר"
    needs = page.evaluate(
        "() => { const e = document.getElementById('electives-needs-spec'); return e && !e.hidden ? e.textContent.trim() : ''; }"
    )
    assert needs == "קורסי הבחירה יופיעו אחרי בחירת התמחות בשלב 1"
    choose(page, CIVIL, 3, "א", specialization="מבנים")
    gold = page.evaluate(
        "() => { const e = document.getElementById('semester-note'); return e && !e.hidden ? e.textContent.trim() : ''; }"
    )
    assert gold == "בסמסטר הזה מומלץ לבחור קורסי בחירה"


# ------------------------------------------- חובה בהתמחות, מחוץ לסמסטרים
MGMT = "ניהול הבנייה"


def test_mandatory_in_specialization_on_chips_and_cards(page):
    choose(page, CIVIL, 3, specialization=MGMT)
    box = cluster(f"{MGMT} · קורסי בחירה")
    page.click(box + " .elective-cluster-head")  # פתיחת האשכול לפני שימוש בשבב (באישור, 2026-10-05)
    for code in ("500210", "51600"):
        chip = page.locator(f"{box} .elective-chip[data-code='{code}']")
        assert chip.locator(".tag--spec").inner_text() == f"חובה בהתמחות {MGMT}"
    others = page.locator(f"{box} .elective-chip[data-code] .tag--spec").count()
    assert others == 2, "רק שני הקורסים המסומנים בשנתון"
    page.click(f"{box} .elective-chip[data-code='51600']")
    page.wait_for_timeout(800)
    card = page.locator("#course-list .course-item:has(.course-code:text-is('51600'))")
    assert card.locator(".tag--spec").inner_text() == f"חובה בהתמחות {MGMT}"


# ------------------------------------- רשימת הבחירה המחייבת בתעשייה
DO = "תכן ותפעול של מערכות ייצור ושירות"
SPECIAL = "רשימת בחירה מחייבת"


def choose_do(page, route):
    choose(page, IND, 4, specialization=DO)
    page.select_option("#select-route", route)
    page.wait_for_timeout(1300)


def test_the_special_group_is_a_cluster_with_its_pill(page):
    choose_do(page, "התמחות בתעשייה")
    box = cluster(SPECIAL)
    codes = [c.get_attribute("data-code") for c in page.locator(box + " .elective-chip[data-code]").all()]
    assert codes == ["51170", "51025", "51030", "51106", "51113", "51120", "51535", "51537"]
    assert page.locator(box + " .elective-pill").inner_text().strip() == "לפחות 2 קורסים"


def test_the_special_group_counts_51535_and_51537_as_one(page):
    choose_do(page, "פרויקט גמר")
    box = cluster(SPECIAL)
    assert page.locator(box + " .elective-chip[data-code='51156']").count() == 1
    check = box + " .elective-pill-check"
    page.click(box + " .elective-cluster-head")  # פתיחת האשכול לפני שימוש בשבב (באישור, 2026-10-05)
    page.click(box + " .elective-chip[data-code='51535']")
    page.click(box + " .elective-chip[data-code='51537']")
    page.wait_for_timeout(800)
    assert page.locator(check).count() == 0, "51535 ו-51537 נספרים כאחד"
    page.click(box + " .elective-chip[data-code='51025']")
    page.wait_for_timeout(800)
    assert page.locator(check).count() == 1


def test_51170_note_is_on_its_card_not_the_cluster(page):
    choose_do(page, "התמחות בתעשייה")
    assert notes_under(page, SPECIAL) == []
    page.click(cluster(SPECIAL) + " .elective-cluster-head")  # פתיחת האשכול לפני שימוש בשבב (באישור, 2026-10-05)
    page.click(cluster(SPECIAL) + " .elective-chip[data-code='51170']")
    page.wait_for_timeout(800)
    card = page.locator("#course-list .course-item:has(.course-code:text-is('51170'))")
    metas = [t.strip() for t in card.locator(".course-meta").all_inner_texts()]
    assert "לאחוזון 80 ומעלה, באישור רמ״ח" in metas


# ------------------------------------------------ חוקים מילוליים מסומנים
def head_notes(page) -> list[str]:
    return [t.strip() for t in page.locator("#electives-head-notes .elective-cluster-note").all_inner_texts()]


def test_is_english_seminar_under_the_heading(page):
    choose(page, "הנדסת מערכות מידע", 4)
    assert head_notes(page) == ["אחד מקורסי הבחירה חייב להיות סמינר בשפה האנגלית."]
    assert "מילואים" not in page.inner_text("#electives")


def test_mechanical_entrepreneurship_cap_under_its_cluster(page):
    choose(page, "הנדסת מכונות", 3, specialization="תכן וייצור")
    page.click(cluster("קורסי העשרה לכלל ההתמחויות") + " .elective-cluster-head")  # פתיחת האשכול לפני קריאת ההערות שלו (באישור, 2026-10-05)
    assert notes_under(page, "קורסי העשרה לכלל ההתמחויות") == [
        "מקורסי היזמות ברשימת ההעשרה ניתן ללמוד עד 4 נ״ז."
    ]
    shown = page.inner_text("#electives")
    assert "28.5" not in shown and "עד צבירה של 20" not in shown
    assert head_notes(page) == []


@pytest.mark.parametrize("intake", ["winter", "spring"])
def test_math_shows_its_mathematical_electives_rule(client, intake):
    data = client.get(
        "/api/program/electives?" + urlencode({"program": MATH, "intake": intake})
    ).get_json()
    shown = [r["text"] for r in data["rules"] if r["show"]]
    assert shown == ["חובה לקחת 3.0 נ״ז בקורסי בחירה מתמטיים."]


# ------------------------------------ שמות מ-industry.pdf (name_corrections)
@pytest.mark.parametrize("code, name", [("51170", "נושא אישי 1"), ("51156", "מבוא להנדסת מערכות שירות")])
def test_names_outside_the_catalog_on_chips_and_cards(page, code, name):
    choose_do(page, "פרויקט גמר")
    page.click(cluster(SPECIAL) + " .elective-cluster-head")  # פתיחת האשכול לפני שימוש בשבב (באישור, 2026-10-05)
    chip = page.locator(f"{cluster(SPECIAL)} .elective-chip[data-code='{code}']")
    assert chip.locator(".elective-chip-name").inner_text().strip() == name
    chip.click()
    page.wait_for_timeout(800)
    card = page.locator(f"#course-list .course-item:has(.course-code:text-is('{code}'))")
    assert card.locator(".course-name").inner_text().strip() == name
