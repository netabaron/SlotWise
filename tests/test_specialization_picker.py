# -*- coding: utf-8 -*-
"""
שלב 1: התמחות ומסלול (docs/DESIGN.md, "Program, year and semester").

מה נבדק
-------
* **השרת.** ‏``/api/bootstrap`` נושא לכל מסלול את בלוק ה-``specialization``
  שלו (או ``None``). ‏``/api/semester/<n>/courses`` מקבל ``specialization`` ו-
  ``route``: קורס של התמחות או מסלול **אחרים** יורד מהרשימה, קורס של הבחירה
  מסומן ``track_chosen``. **בלי הפרמטרים התשובה זהה לזו שלפניהם** — הבדיקות
  המוגנות (``test_program_curricula``, ``test_industry_curriculum``,
  ``test_recommended_defaults``) נשענות על כך.
* **הנתונים.** קורסי ההתנסות המעשית בתעשייה וניהול נושאים סמסטר ושלב,
  מצוטטים מ-``industry.pdf`` עמ' 12–13: שלב א' בסמסטר 7, שלב ב' בסמסטר 8.
* **הממשק.** התיבות מוצגות רק למסלול שיש לו אותן ורק מהסמסטר שבקובץ, הבחירה
  משנה את ההמלצה, נשמרת בין רענונים, ויורדת כשהמסלול או הסמסטר משתנים.
"""

from __future__ import annotations

import json
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

CIVIL = "הנדסה אזרחית"
IND = "הנדסת תעשייה וניהול"
EL = "הנדסת חשמל ואלקטרוניקה"
MECH = "הנדסת מכונות"
SW = "הנדסת תוכנה"
DO = "תכן ותפעול של מערכות ייצור ושירות"
DS = "מדעי הנתונים"
STORAGE_KEY = "braude_schedule_builder_v1"


@pytest.fixture(scope="module")
def client():
    return create_app(config={"allow_network": False}).test_client()


def semester(client, sem, program, **params) -> dict:
    query = urlencode({"program": program, **params})
    res = client.get(f"/api/semester/{sem}/courses?{query}")
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()


def tracked(data: dict) -> dict[str, tuple[str, bool]]:
    return {c["code"]: (c["track"], c["track_chosen"]) for c in data["courses"] if c["track"]}


# ==========================================================================
# 1. השרת
# ==========================================================================
@pytest.mark.parametrize("program,sem", [(CIVIL, "5"), (IND, "7"), (EL, "8"), (MECH, "6"), (SW, "5")])
def test_without_a_choice_the_answer_is_unchanged(client, program, sem):
    plain = semester(client, sem, program)
    empty = semester(client, sem, program, specialization="", route="")
    assert [c["code"] for c in plain["courses"]] == [c["code"] for c in empty["courses"]]
    assert not any(c["track_chosen"] for c in plain["courses"])


def test_a_specialization_drops_the_other_ones_courses(client):
    rows = tracked(semester(client, "5", CIVIL, specialization="מבנים"))
    assert rows, "קורסי מבנים נשארים"
    assert all(track == "מבנים" and mine for track, mine in rows.values()), rows
    shared = [c for c in semester(client, "5", CIVIL, specialization="מבנים")["courses"] if not c["track"]]
    assert shared, "והליבה המשותפת נשארת"


def test_a_specialization_before_its_semester_is_ignored(client):
    """מכונות בוחרים התמחות מסמסטר 5. בסמסטר 4 הבחירה אינה חלה."""
    plain = semester(client, "4", MECH)
    chosen = semester(client, "4", MECH, specialization="מכטרוניקה")
    assert [c["code"] for c in plain["courses"]] == [c["code"] for c in chosen["courses"]]


def test_an_unknown_value_is_treated_as_no_choice(client):
    plain = semester(client, "5", CIVIL)
    junk = semester(client, "5", CIVIL, specialization="לא קיימת", route="גם לא")
    assert [c["code"] for c in plain["courses"]] == [c["code"] for c in junk["courses"]]


@pytest.mark.parametrize(
    "route,sem,expected",
    [
        ("התמחות בתעשייה", "7", "51014"),
        ("התמחות בתעשייה", "8", "51020"),
        ("פרויקט גמר", "7", "51230"),
        ("פרויקט גמר", "8", "51231"),
    ],
)
def test_industrial_route_courses_arrive_by_stage(client, route, sem, expected):
    rows = tracked(semester(client, sem, IND, specialization=DO, route=route))
    route_rows = {code for code, (track, _) in rows.items() if track == route}
    assert route_rows == {expected}
    assert rows[expected][1] is True, "של הבחירה — מומלץ"
    other = {"51014", "51020", "51230", "51231"} - {expected}
    assert not other & set(rows), "המסלול האחר אינו ברשימה"


def test_industrial_routes_only_for_design_and_operations(client):
    rows = tracked(semester(client, "7", IND, specialization=DS, route="פרויקט גמר"))
    assert not {"51014", "51230"} & set(rows)
    both = tracked(semester(client, "7", IND, specialization=DO))
    assert both["51014"] == ("התמחות בתעשייה", False)
    assert both["51230"] == ("פרויקט גמר", False), "בלי מסלול — שניהם מוצגים, אף אחד לא מומלץ"


def test_route_courses_carry_a_name_and_their_credits(client):
    data = semester(client, "7", IND, specialization=DO, route="התמחות בתעשייה")
    row = next(c for c in data["courses"] if c["code"] == "51014")
    assert row["name"], "שם מהקטלוג"
    assert row["credits"] == 5.0 and row["credits_source"] == "curriculum"


@pytest.mark.parametrize(
    "route,sem7,sem8",
    [
        ("תכן הנדסי בתעשייה", "31101", "31104"),
        ("תכן הנדסי מחקרי", "31101", "31103"),
        ("פרויקט גמר בתכן הנדסי", "31100", "31102"),
    ],
)
def test_electrical_design_route_filters_both_semesters(client, route, sem7, sem8):
    """‏31101 משותף לתעשייה ולמחקר — שורה אחת ששייכת לשני מסלולים."""
    assert {c: m for c, (_, m) in tracked(semester(client, "7", EL, route=route)).items()} == {sem7: True}
    assert {c: m for c, (_, m) in tracked(semester(client, "8", EL, route=route)).items()} == {sem8: True}


def test_bootstrap_carries_each_programs_specialization(client):
    programs = {p["id"]: p for p in client.get("/api/bootstrap").get_json()["programs"]}
    assert programs[CIVIL]["specialization"]["choose_from_semester"] == 3
    assert programs[IND]["specialization"]["choose_from_semester"] == 3
    assert programs[MECH]["specialization"]["choose_from_semester"] == 5
    assert programs[EL]["specialization"]["choose_from_semester"] == 7
    assert programs[IND]["specialization"]["deadline"] == "את ההתמחות בוחרים עד סוף שנה א׳"
    assert programs[EL]["specialization"]["secondary"]["when_route"] == [
        "תכן הנדסי מחקרי",
        "פרויקט גמר בתכן הנדסי",
    ]
    assert programs[SW]["specialization"] is None
    assert programs["other"]["specialization"] is None


def test_the_other_program_is_relabelled(client):
    programs = client.get("/api/bootstrap").get_json()["programs"]
    assert programs[-1]["id"] == "other"
    assert programs[-1]["label"] == "מסלול אחר"


# ==========================================================================
# 2. הנתונים
# ==========================================================================
def test_industrial_route_courses_are_placed_and_cited():
    doc = json.loads((ROOT / "data" / "curricula" / "industry.json").read_text(encoding="utf-8"))
    placed = {}
    for group in doc["specialization"]["routes"]:
        for option in group["options"]:
            for course in option["courses"]:
                placed[course["code"]] = (course["semester"], course["stage"])
                pages = {s["page"] for s in course["source"]}
                assert all(s["pdf"] == "industry.pdf" and s["quote"].strip() for s in course["source"])
                assert course["semester"] == 7 and pages == {12, 13} or course["semester"] == 8 and pages == {13}
    assert placed == {
        "51014": (7, "א"),
        "51020": (8, "ב"),
        "51230": (7, "א"),
        "51231": (8, "ב"),
    }


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
    p.errors = errors  # type: ignore[attr-defined]
    try:
        yield p
    finally:
        assert errors == [], f"שגיאות JavaScript: {errors}"
        ctx.close()


VIEW = """() => {
  const vis = id => { const e = document.getElementById(id); return !!e && !e.hidden && e.offsetParent !== null; };
  const saved = JSON.parse(localStorage.getItem('%s') || '{}');
  return {
    spec: vis('field-specialization'), route: vis('field-route'), secondary: vis('field-secondary'),
    deadline: vis('specialization-deadline')
      ? document.getElementById('specialization-deadline').textContent : '',
    specValue: (document.getElementById('select-specialization') || {}).value || '',
    routeLabel: (document.getElementById('label-route') || {}).textContent || '',
    rows: [...document.querySelectorAll('#course-list .course-item .course-code')].map(e => e.textContent),
    checked: [...document.querySelectorAll('#course-list .course-item')]
      .filter(e => e.querySelector('input[type=checkbox]:checked'))
      .map(e => (e.querySelector('.course-code') || {}).textContent),
    autoCodes: saved.autoCodes || [],
    saved: { specialization: saved.specialization, route: saved.route,
             secondary: saved.secondarySpecialization },
  };
}""" % STORAGE_KEY


def view(page) -> dict:
    return page.evaluate(VIEW)


def choose(page, program: str, year: int, term: str = "א") -> dict:
    page.select_option("#select-program", program)
    page.select_option("#select-year", str(year))
    page.select_option("#select-term", term)
    page.wait_for_timeout(1300)
    return view(page)


def pick(page, selector: str, value: str) -> dict:
    page.select_option(selector, value)
    page.wait_for_timeout(1100)
    return view(page)


def test_no_pickers_for_a_program_without_specializations(page):
    v = choose(page, SW, 3)
    assert not (v["spec"] or v["route"] or v["secondary"])


def test_civil_picker_appears_from_semester_three_only(page):
    assert not choose(page, CIVIL, 1)["spec"], "סמסטר 1 — עוד אין התמחות"
    v = choose(page, CIVIL, 2)
    assert v["spec"] and not v["route"] and not v["deadline"]
    assert "421212" in v["rows"] and "421212" not in v["autoCodes"], "בלי בחירה — כמו היום"
    v = pick(page, "#select-specialization", "מבנים")
    assert "421212" in v["autoCodes"], "קורס מבנים מומלץ אחרי הבחירה"


def test_civil_other_specialization_is_no_longer_recommended(page):
    choose(page, CIVIL, 3)
    v = pick(page, "#select-specialization", "ניהול הבנייה")
    assert not {"421314", "421315"} & set(v["rows"]), "קורסי מבנים אינם ברשימה"
    assert {"421222", "421318", "421319"} <= set(v["autoCodes"])


def test_industrial_shows_the_deadline_and_the_route_for_design_and_operations(page):
    v = choose(page, IND, 4)
    assert v["spec"] and not v["route"]
    assert v["deadline"] == "את ההתמחות בוחרים עד סוף שנה א׳"
    assert not pick(page, "#select-specialization", DS)["route"], "מדעי הנתונים — בלי מסלול"
    v = pick(page, "#select-specialization", DO)
    assert v["route"] and v["routeLabel"] == "התנסות מעשית"
    v = pick(page, "#select-route", "פרויקט גמר")
    assert "51230" in v["autoCodes"] and "51014" not in v["rows"]


def test_electrical_secondary_only_for_research_and_final_project(page):
    v = choose(page, EL, 4)
    assert v["route"] and v["spec"] and not v["secondary"]
    assert v["routeLabel"] == "סוג תכן הנדסי"
    assert not pick(page, "#select-route", "תכן הנדסי בתעשייה")["secondary"]
    v = pick(page, "#select-route", "תכן הנדסי מחקרי")
    assert v["secondary"]
    assert v["rows"] == ["31101"] and v["autoCodes"] == ["31101"]


def test_the_choice_survives_a_reload(page):
    choose(page, IND, 4)
    pick(page, "#select-specialization", DO)
    pick(page, "#select-route", "התמחות בתעשייה")
    page.reload()
    page.wait_for_timeout(1800)
    v = view(page)
    assert v["saved"]["specialization"] == DO and v["saved"]["route"] == "התמחות בתעשייה"
    assert v["specValue"] == DO
    assert "51014" in v["rows"] and "51230" not in v["rows"]


def test_the_choice_is_cleared_when_it_no_longer_applies(page):
    choose(page, CIVIL, 3)
    pick(page, "#select-specialization", "מבנים")
    page.select_option("#select-year", "1")
    page.wait_for_timeout(1000)
    assert view(page)["saved"]["specialization"] == "", "סמסטר 1 — ההתמחות יורדת"

    choose(page, CIVIL, 3)
    pick(page, "#select-specialization", "מבנים")
    page.select_option("#select-program", MECH)
    page.wait_for_timeout(1000)
    assert view(page)["saved"]["specialization"] == "", "מסלול אחר — ההתמחות יורדת"


def test_ticked_core_courses_survive_choosing_a_specialization(page):
    choose(page, CIVIL, 3)
    page.click("#btn-restore-recommended")
    page.wait_for_timeout(1000)
    before = set(view(page)["checked"])
    assert before
    v = pick(page, "#select-specialization", "מבנים")
    assert before <= set(v["checked"]), "קורסי הליבה שסומנו נשארים מסומנים"
