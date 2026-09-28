# -*- coding: utf-8 -*-
"""
שלב 2, הקורסים (docs/DESIGN.md, "Courses").

מה נבדק
-------
* **‏/api/program/electives** נשען על ``elective_lists``/``specializations``
  שב-``data/curricula.json`` ועל ``elective_rules`` שבקובץ התוכנית: חוקים
  שחלים על הבחירה משלב 1 בלבד, כל אחד עם מקורו, ‏``rows`` לספירה, וגלולת
  מינימום על תיבת הרשימה שהחוק מדבר עליה.
* **‏semester_notes** מ-``semester_slots``: מה התוכנית משבצת בסמסטר, ומה
  "בכל סמסטר" (רק כשאינו משובץ בו).
* **הממשק**: כותרת "מומלצים לסמסטר X", מונה נ"ז, פתק הזהב, תג "חובה
  בהתמחות", "נבחר יחד עם", ‏✓ על הגלולה שסופר את הבחירה בלבד, ושבב
  שלב 1 שסופר רק את המומלצים להתמחות שנבחרה.
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
MECH = "הנדסת מכונות"
BIO = "הנדסת ביוטכנולוגיה"
MATH = "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה"
DS = "מדעי הנתונים"
DO = "תכן ותפעול של מערכות ייצור ושירות"


@pytest.fixture(scope="module")
def client():
    return create_app(config={"allow_network": False}).test_client()


def electives(client, program, **params) -> dict:
    res = client.get("/api/program/electives?" + urlencode({"program": program, **params}))
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()


def semester(client, sem, program, **params) -> dict:
    res = client.get(f"/api/semester/{sem}/courses?" + urlencode({"program": program, **params}))
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()


def rules(data) -> dict:
    return {r["id"]: r for r in data["rules"]}


# ==========================================================================
# 1. דרישות הבחירה
# ==========================================================================
def test_software_rules_and_clusters_with_their_pills(client):
    data = electives(client, SW)
    assert data["available"] and not data["needs_specialization"]
    assert [c["title"] for c in data["clusters"]] == [
        "מדעים", "עיבוד אותות ורשתות תקשורת", "אלגוריתמים", "סמינרים", "הנדסת תוכנה", "מעבדות",
    ]
    for cluster in data["clusters"]:
        assert cluster["pills"] == [{"type": "min_courses", "n": 1, "approximate": False}]
    r = rules(data)
    assert r["cluster-0"]["source"]["pdf"] == "sw.pdf" and r["cluster-0"]["source"]["page"] == 9
    assert r["seminars-no-substitute"]["countable"] is False, "חוק מילולי — בלי ספירה"
    assert set(r["exclusive-62023-62002"]["rows"]) == {"62023", "62002"}


def test_old_clusters_field_is_gone(client):
    data = electives(client, SW)
    assert "tracks" not in data and "cluster_rule" not in data


def test_a_program_with_specializations_waits_for_the_choice(client):
    data = electives(client, CIVIL)
    assert data["needs_specialization"] and data["clusters"] == [] and data["rules"] == []


def test_civil_structures(client):
    data = electives(client, CIVIL, specialization="מבנים")
    assert [c["title"] for c in data["clusters"]] == ["קבוצה 1", "קבוצה 2"]
    assert set(rules(data)) == {"structures-group-1", "structures-group-2", "structures-credits"}
    assert rules(data)["structures-credits"]["unit"] == "credits"


def test_industrial_center_rows_count_toward_their_cluster(client):
    r = rules(electives(client, IND, specialization=DS))
    assert "251966" in r["ds-information-systems"]["rows"]
    assert "do-internship-total" not in r, "חוק של התמחות אחרת אינו חל"


def test_industrial_route_rules_need_the_route(client):
    assert "do-project-total" not in rules(electives(client, IND, specialization=DO))
    r = rules(electives(client, IND, specialization=DO, route="פרויקט גמר"))
    assert r["do-project-special-list"]["count_one_of"] == [["51535", "51537"]]


def test_electrical_secondary_and_not_counted_again(client):
    data = electives(
        client, EL, specialization="מחשבים (חומרה ותוכנה)", route="תכן הנדסי מחקרי",
        secondary="עיבוד אותות ותקשורת",
    )
    r = rules(data)
    assert "secondary-credits-1" in r and "secondary-credits-0" not in r
    assert "31215" not in r["other-research"]["rows"], "קורס של ההתמחות אינו נספר שוב"
    assert set(r["main-core-hw-0"]["rows"]) <= set(r["main-core-0"]["rows"])
    titles = [c["title"] for c in data["clusters"]]
    assert len(titles) == len(set(titles)), "עם התמחות משנית — כותרות נבדלות"


def test_mechanical_counts_the_specialization_mandatory_courses(client):
    r = rules(electives(client, MECH, specialization="מכטרוניקה"))
    assert "22861" in r["specialization-credits-1"]["rows"]


def test_maths_domains_stay_as_boxes_without_pills(client):
    data = electives(client, MATH, intake="winter")
    assert len(data["clusters"]) == 4
    assert all(c["pills"] == [] for c in data["clusters"])
    assert rules(data)["mathematical-electives"]["countable"] is False


def test_biotech_shows_nothing(client):
    assert electives(client, BIO)["available"] is False


# ==========================================================================
# 2. פתקי הסמסטר
# ==========================================================================
def test_software_semester_seven_places_electives(client):
    notes = semester(client, 7, SW)["semester_notes"]
    assert [p["kind"] for p in notes["placed"]] == ["electives"] and notes["anywhere"] == []


def test_general_course_slot_carries_its_label(client):
    notes = semester(client, 4, SW)["semester_notes"]
    assert notes["placed"] == [{"kind": "general", "label": "קורס כללי 2", "note": ""}]


def test_any_semester_is_quoted(client):
    notes = semester(client, 3, EL)["semester_notes"]
    assert notes["placed"] == []
    assert {a["kind"] for a in notes["anywhere"]} == {"general", "sport"}
    assert "בכל סמסטר" in notes["anywhere"][0]["quote"]


def test_industrial_slot_follows_the_specialization(client):
    assert semester(client, 8, IND, specialization=DS)["semester_notes"]["placed"] == []
    placed = semester(client, 8, IND, specialization=DO, route="התמחות בתעשייה")["semester_notes"]["placed"]
    assert [p["kind"] for p in placed] == ["electives"]


def test_replacement_table_reaches_the_card(client):
    rows = {c["code"]: c for c in semester(client, 5, SW)["courses"]}
    assert rows["62027"]["replaces"] == [{"code": "61769", "name": "ממשק אדם מחשב"}]


# ==========================================================================
# 3. הממשק
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


def choose(page, program, year, term="א"):
    page.select_option("#select-program", program)
    page.select_option("#select-year", str(year))
    page.select_option("#select-term", term)
    page.wait_for_timeout(1400)


def text(page, selector) -> str:
    return page.evaluate(
        "s => { const e = document.querySelector(s); return e && !e.hidden ? e.textContent.trim() : ''; }",
        selector,
    )


def test_heading_counter_and_gold_note(page):
    choose(page, SW, 4)
    assert text(page, "#recommended-title") == "מומלצים לסמסטר 7"
    assert text(page, "#btn-restore-recommended") == "סמנו הכל"
    assert text(page, "#semester-note") == "בסמסטר הזה מומלץ לבחור קורסי בחירה"
    assert text(page, "#credits-total") == "0 נ״ז"
    page.click("#btn-restore-recommended")
    page.wait_for_timeout(600)
    assert text(page, "#credits-total").endswith("נ״ז") and text(page, "#credits-total") != "0 נ״ז"
    assert page.get_attribute("#course-search", "placeholder") == "הוספת קורס מהידיעון, גם מסמסטר קודם"
    assert "בתוכנית-סמסטר" not in page.inner_text("#course-list")


def test_any_semester_is_one_quiet_line(page):
    choose(page, EL, 2)
    assert text(page, "#semester-note") == ""
    assert text(page, "#semester-info").startswith("קורסים כלליים וספורט:")


def test_linked_courses_say_with_what(page):
    choose(page, SW, 3)
    card = page.locator("#course-list .course-item:has(.course-code:text-is('61756'))")
    assert card.locator(".tag--tied").inner_text() == "קורס צמוד"
    line = card.locator(".course-tied-with").inner_text()
    assert line.startswith("נבחר יחד עם ")
    assert sorted(line.removeprefix("נבחר יחד עם ").split(", ")) == ["61757", "62027"]


def test_specialization_badge_and_step_one_count(page):
    choose(page, CIVIL, 4)
    page.select_option("#select-specialization", "מבנים")
    page.wait_for_timeout(1300)
    card = page.locator("#course-list .course-item:has(.course-code:text-is('421411'))")
    assert card.locator(".tag--spec").inner_text() == "חובה בהתמחות מבנים"
    recommended = page.evaluate(
        "() => JSON.parse(localStorage.getItem('braude_schedule_builder_v1')).autoCodes.length"
    )
    assert f"{recommended} קורסים מומלצים" in text(page, "#semester-summary")


def test_the_pill_ticks_on_the_current_selection_only(page):
    choose(page, SW, 4)
    check = "#electives-groups .elective-cluster[data-key='מדעים'] .elective-pill-check"
    assert page.locator(check).count() == 0
    page.click("#electives-groups .elective-chip[data-code='61957']")
    page.wait_for_timeout(700)
    assert page.locator(check).count() == 1
    assert page.locator("#electives-rules").count() == 0
    assert "הושלם" not in page.inner_text("#electives")
