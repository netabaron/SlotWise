# -*- coding: utf-8 -*-
"""מתמטיקה שימושית: תוכנית לכל מועד כניסה.

הרקע
----
השנתון מדפיס למחלקה **שתי** תוכניות לימודים, אחת למתקבלים בחורף ואחת
למתקבלים באביב, ואין ולו סמסטר אחד שזהה בשתיהן. עד 2026-09-21 המסקנה
הייתה שאי אפשר להציג אותן בכלל: המסלול נשא ``curriculum_absence:
not_representable`` ונפל לעיון בקטלוג, כי רשימה שטוחה אחת הייתה נכונה
לחצי מהמחלקה ושגויה לחצי השני.

מה שהשתנה
----------
במקום לבחור אחת מהשתיים, שתיהן חולצו — ``data/curricula/math-winter.json``
ו-``math-spring.json`` — והשאלה "באיזה מועד התחלת" נשאלת בממשק. אחרי
שנבחר מועד, המסלול מתנהג **בדיוק** כמו כל מסלול עם תוכנית אחת: יש לו לוח
סמסטרים, יש לו רשימת קורסים מומלצת, והקורסים אינם מסומנים כ-``track``.

מה הקובץ הזה שומר עליו
-----------------------
1. שני הקבצים נטענים, ושניהם מסתדרים מול הסה"כ שהמסמך מדפיס.
2. אותו מספר סמסטר מציין קורסים אחרים בכל מועד — זו הסיבה שכל זה קיים.
3. התיבה מופיעה **רק** למסלול הזה. שאלה שאין לה משמעות אינה שאלה.
4. בלי מועד: "יש לבחור סמסטר התחלה", ולא "אין תוכנית".
5. עם מועד: רשימה מומלצת, בלי תווית מסלול התמחות.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from web.api import create_app  # noqa: E402

MATH = "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה"
PLAIN_PROGRAM = "הנדסת תוכנה"
CURRICULA_DIR = ROOT / "data" / "curricula"
FILES = {"winter": "math-winter.json", "spring": "math-spring.json"}
INTAKE_REQUIRED = "intake_required"
CHOOSE_INTAKE_NOTE = "יש לבחור סמסטר התחלה"


@pytest.fixture(scope="module")
def client():
    return create_app(config={"allow_network": False}).test_client()


def semester(client, sem: str, program: str, intake: str = "") -> dict:
    url = f"/api/semester/{sem}/courses?program={quote(program)}"
    if intake:
        url += f"&intake={quote(intake)}"
    res = client.get(url)
    assert res.status_code == 200, f"{program}/{intake} סמסטר {sem} החזיר {res.status_code}"
    return res.get_json()


def plan(intake: str) -> dict:
    return json.loads((CURRICULA_DIR / FILES[intake]).read_text(encoding="utf-8"))


# ==========================================================================
# 1. שני הקבצים
# ==========================================================================
@pytest.mark.parametrize("intake", sorted(FILES))
def test_both_intake_files_load_and_name_their_intake(intake):
    data = plan(intake)
    assert data["program"] == MATH, "שם המסלול חייב להיות זהה למה שב-programs.json"
    assert data["intake"] == intake, "בלי השדה הזה הקובץ אינו משויך לאף מועד"
    assert data["intake_label"], "למועד חייבת להיות תווית בעברית"
    assert sorted(data["semesters"], key=int) == ["1", "2", "3", "4", "5", "6"], (
        "התוכנית תלת-שנתית: שישה סמסטרים, לא שמונה"
    )


@pytest.mark.parametrize("intake", sorted(FILES))
def test_every_semester_reconciles_with_the_printed_total(intake):
    """הנ"ז שחילצנו שווה לסה"כ שהמסמך עצמו מדפיס, בכל אחד מהסמסטרים.

    זו הבדיקה שמגלה שורה שנקראה לסמסטר הלא נכון: טבלה שנמשכת על פני שני
    עמודים היא בדיוק המקום שבו זה קורה, ובמסמך הזה יש ארבע כאלה.
    """
    data = plan(intake)
    for key, sem in sorted(data["semesters"].items(), key=lambda kv: int(kv[0])):
        printed = sem["printed_total_credits"]
        assert printed is not None, f'סמסטר {key}: לא נקרא סה"כ מהמסמך'
        assert sem["reconciles"] is True, (
            f"סמסטר {key}: חולצו {sem['total']['credits']} נ\"ז "
            f"מול {printed} שהמסמך מדפיס"
        )


@pytest.mark.parametrize("intake", sorted(FILES))
def test_the_mandatory_credits_match_what_the_chapter_declares(intake):
    """המסמך מצהיר 96.0 נ"ז קורסי חובה. סכום כל הסמסטרים חייב להיות זה."""
    data = plan(intake)
    total = sum(s["total"]["credits"] for s in data["semesters"].values())
    assert round(total, 1) == 96.0, f"{intake}: {total} נ\"ז"


@pytest.mark.parametrize("intake", sorted(FILES))
def test_no_row_is_marked_as_a_specialisation_track(intake):
    """התוכנית שטוחה: אין בה מסלולי התמחות, ולכן אף שורה אינה נושאת track.

    זה מה שמבדיל בינה לבין תעשייה וניהול, ובלעדיו הקורסים היו מוצגים
    כ"מסלול" ולא היו נבחרים אוטומטית.
    """
    data = plan(intake)
    assert data["tracks"] == []
    tagged = [
        c["code"]
        for s in data["semesters"].values()
        for c in s["courses"]
        if c.get("track")
    ]
    assert tagged == [], f"{intake}: שורות עם track: {tagged}"


# ==========================================================================
# 2. שני המועדים אינם אותה תוכנית
# ==========================================================================
def test_semester_three_is_a_different_list_in_each_intake():
    """זו כל הסיבה שהתכונה קיימת.

    בחירה שרירותית באחת התוכניות הייתה נותנת לחצי מהמחלקה רשימה של
    סמסטר אחר לגמרי — ולא רשימה חלקית, אלא רשימה שגויה.
    """
    winter = {c["code"] for c in plan("winter")["semesters"]["3"]["courses"]}
    spring = {c["code"] for c in plan("spring")["semesters"]["3"]["courses"]}
    assert winter and spring
    assert winter != spring, "סמסטר 3 חייב להיות שונה בין המועדים"


def test_no_semester_number_means_the_same_thing_in_both_intakes():
    """לא רק סמסטר 3: אין ולו מספר סמסטר אחד שמציין את אותה רשימה."""
    same = []
    for key in map(str, range(1, 7)):
        a = {c["code"] for c in plan("winter")["semesters"][key]["courses"]}
        b = {c["code"] for c in plan("spring")["semesters"][key]["courses"]}
        if a == b:
            same.append(key)
    assert same == [], f"סמסטרים זהים בשני המועדים: {same}"


def test_the_first_semester_of_each_intake_is_in_its_own_term():
    """מתקבל/ת בחורף מתחיל/ה בסמסטר א׳, ומתקבל/ת באביב בסמסטר ב׳.

    ‏זה מה שהופך את מיפוי שנה+סמסטר ⇐ מספר סמסטר לשונה בין המועדים, והוא
    הסיבה ש-``semesters_by_program_intake`` נושא לוח נפרד לכל מועד.
    """
    assert plan("winter")["semesters"]["1"]["term"] == "א"
    assert plan("spring")["semesters"]["1"]["term"] == "ב"


# ==========================================================================
# 3. השרת: בלי מועד אין תוכנית, עם מועד יש
# ==========================================================================
def test_without_an_intake_the_server_asks_for_one(client):
    data = semester(client, "3", MATH)
    assert data["curriculum_available"] is False
    assert data["courses"] == []
    assert data["curriculum_absence"] == INTAKE_REQUIRED
    assert data["note"], "חייב לומר משהו, ולא להשאיר מסך ריק"


@pytest.mark.parametrize("intake", sorted(FILES))
def test_with_an_intake_the_server_answers_like_any_other_program(client, intake):
    data = semester(client, "3", MATH, intake)
    assert data["curriculum_available"] is True
    assert data["count"] > 0
    assert data["curriculum_absence"] == "", "אחרי בחירת מועד אין היעדר"
    assert data["program"] == MATH
    assert data["intake"] == intake


def test_the_two_intakes_answer_differently_over_http(client):
    winter = {c["code"] for c in semester(client, "3", MATH, "winter")["courses"]}
    spring = {c["code"] for c in semester(client, "3", MATH, "spring")["courses"]}
    assert winter != spring


def test_an_unknown_intake_is_not_silently_treated_as_a_choice(client):
    """מועד שאינו קיים אינו "בחירה" — אחרת שגיאת כתיב הייתה מחזירה רשימה
    ריקה שנראית כמו "אין קורסים בסמסטר הזה"."""
    data = semester(client, "3", MATH, "autumn")
    assert data["curriculum_available"] is False
    assert data["courses"] == []


# ==========================================================================
# 4. ‏/api/bootstrap נושא את המועדים ואת הלוחות
# ==========================================================================
def test_only_applied_maths_offers_intakes(client):
    data = client.get("/api/bootstrap").get_json()
    with_intakes = [p["id"] for p in data["programs"] if p.get("intakes")]
    assert with_intakes == [MATH], f"מסלולים עם מועדים: {with_intakes}"


def test_every_program_entry_carries_the_intakes_field(client):
    """‏חסר שם היה מתפרש בממשק כ"עוד לא נאמר" ומסתיר את התיבה בטעות."""
    data = client.get("/api/bootstrap").get_json()
    missing = [p["id"] for p in data["programs"] if p.get("intakes") is None]
    assert not missing, f"מסלולים בלי השדה: {missing}"


def test_the_intake_labels_are_hebrew(client):
    data = client.get("/api/bootstrap").get_json()
    by_id = {p["id"]: p for p in data["programs"]}
    labels = {i["id"]: i["label"] for i in by_id[MATH]["intakes"]}
    assert set(labels) == {"winter", "spring"}
    for ident, label in labels.items():
        assert any("֐" <= ch <= "׿" for ch in label), f"{ident}: {label!r} אינו בעברית"


def test_bootstrap_carries_a_semester_table_per_intake(client):
    """הממשק מחליף מועד בלי לבקש ‏bootstrap מחדש, ולכן שני הלוחות נשלחים."""
    data = client.get("/api/bootstrap").get_json()
    tables = data["semesters_by_program_intake"]
    assert MATH in tables
    assert set(tables[MATH]) == {"winter", "spring"}
    for intake, rows in tables[MATH].items():
        assert len(rows) == 6, f"{intake}: {len(rows)} סמסטרים"


def test_a_program_with_intakes_stays_out_of_the_single_plan_table(client):
    """‏``semesters_by_program`` הוא "מסלול ⇐ לוח אחד". למסלול עם מועדים אין
    לוח אחד, ולוח של מועד אחד שם היה נכון לחצי מהמחלקה."""
    data = client.get("/api/bootstrap").get_json()
    assert MATH not in data["semesters_by_program"]


def test_other_programs_are_untouched(client):
    """הנתיב הקיים — מסלול ⇐ קובץ אחד — נשאר בדיוק כפי שהיה."""
    data = client.get("/api/bootstrap").get_json()
    by_id = {p["id"]: p for p in data["programs"]}
    for name in ("הנדסת תוכנה", "הנדסת ביוטכנולוגיה", "הנדסת תעשייה וניהול"):
        assert by_id[name]["intakes"] == [], f"{name} אינו אמור לשאת מועדים"
        assert by_id[name]["has_curriculum"] is True
        assert by_id[name]["curriculum_absence"] == ""
        assert name in data["semesters_by_program"]


def test_the_not_representable_mechanism_is_still_there():
    """אין לו כרגע אף מסלול, וזו בדיוק הסיבה לבדוק אותו.

    ‏המנגנון נשאר למקרה הבא. בלי הבדיקה הזאת הוא היה נמחק בפעם הבאה
    שמישהו מנקה קוד שנראה לא בשימוש.
    """
    from web import api

    assert api.CURRICULUM_ABSENCE_NOT_REPRESENTABLE == "not_representable"
    assert isinstance(api.CURRICULUM_ABSENCE_BY_PROGRAM, dict)


# ==========================================================================
# 5. בדפדפן: התיבה, הנוסח, וההמלצה
# ==========================================================================
sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402


@pytest.fixture(scope="module")
def server():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = make_server("127.0.0.1", port,
                      create_app(config={"allow_network": False}), threaded=True)
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


@pytest.fixture()
def page(browser, server):
    ctx = browser.new_context(viewport={"width": 1200, "height": 1000})
    p = ctx.new_page()
    p.goto(server)
    p.wait_for_timeout(1500)
    try:
        yield p
    finally:
        ctx.close()


def intake_visible(page) -> bool:
    return page.evaluate(
        "() => { const f = document.getElementById('field-intake');"
        " return !!f && !f.hidden; }"
    )


def year_note(page) -> str:
    return page.evaluate(
        "() => (document.getElementById('year-note') || {}).textContent || ''"
    )


def listed_codes(page) -> list:
    return page.evaluate(
        "() => [...document.querySelectorAll('#course-list .course-code')]"
        ".map(e => e.textContent.trim())"
    )


def test_the_intake_box_is_hidden_until_a_program_with_intakes_is_chosen(page):
    assert not intake_visible(page), "לפני בחירת מסלול אין למה לשאול"
    page.select_option("#select-program", PLAIN_PROGRAM)
    page.wait_for_timeout(800)
    assert not intake_visible(page), f"{PLAIN_PROGRAM} אינו אמור לקבל את התיבה"


def test_the_intake_box_appears_for_applied_maths(page):
    page.select_option("#select-program", MATH)
    page.wait_for_timeout(800)
    assert intake_visible(page), "מתמטיקה שימושית חייבת לקבל את התיבה"
    values = page.eval_on_selector_all(
        "#select-intake option", "els => els.map(e => e.value).filter(Boolean)"
    )
    assert sorted(values) == ["spring", "winter"]


def test_switching_back_to_a_plain_program_hides_the_box_again(page):
    page.select_option("#select-program", MATH)
    page.wait_for_timeout(600)
    assert intake_visible(page)
    page.select_option("#select-program", PLAIN_PROGRAM)
    page.wait_for_timeout(800)
    assert not intake_visible(page)


def test_without_an_intake_the_page_asks_for_one(page):
    page.select_option("#select-program", MATH)
    page.select_option("#select-year", "2")
    page.select_option("#select-term", "א")
    page.wait_for_timeout(1500)
    assert CHOOSE_INTAKE_NOTE in year_note(page), (
        f"‏#year-note היה {year_note(page)!r}"
    )


def test_choosing_an_intake_produces_a_recommended_list(page):
    page.select_option("#select-program", MATH)
    page.select_option("#select-year", "2")
    page.select_option("#select-term", "א")
    page.select_option("#select-intake", "winter")
    page.wait_for_timeout(2000)
    assert CHOOSE_INTAKE_NOTE not in year_note(page), "אחרי בחירה אין מה לבקש"
    codes = listed_codes(page)
    assert codes, "חורף, שנה ב׳ סמסטר א׳ = סמסטר 3, ויש בו קורסים"
    assert "61739" in codes, f"קורס מסמסטר 3 של מועד חורף חסר: {codes}"


def test_the_two_intakes_show_different_lists_in_the_browser(page):
    page.select_option("#select-program", MATH)
    page.select_option("#select-year", "2")
    page.select_option("#select-term", "א")
    page.select_option("#select-intake", "winter")
    page.wait_for_timeout(2000)
    winter = set(listed_codes(page))
    page.select_option("#select-intake", "spring")
    page.wait_for_timeout(2000)
    spring = set(listed_codes(page))
    assert winter and spring
    assert winter != spring, "החלפת מועד חייבת להחליף את הרשימה"
