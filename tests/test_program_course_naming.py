"""
שמות מסלולים ושמות קורסים — ‏docs/PROGRAM_REVIEW.md סעיפים 1 ו-2.

‏**מסלול.** אתר המכללה קורא למתמטיקה שימושית "מתמטיקה שימושית עם התמחות
ב-AI ובאלגוריתמיקה", והשם הזה נכנס ל-``programs.json`` ומשם לתיבת הבחירה.
השנתון — מקור האמת — מדפיס תוכנית אחת בשם "תוכנית הלימודים במתמטיקה
שימושית", ו-AI בה הוא תחום בחירה. יש **תוכנית אחת**, ולכן גם אפשרות אחת.
המזהה (``id``) נשאר כשהיה: בחירות שמורות בדפדפן נשענות עליו.

‏**קורסים.** שלוש תקלות, שלושה שורשים:
  * 'חדו"א2' — פרק השנתון של אזרחית מודפס עם המספר צמוד, וכך חולץ.
    ‏``models.normalize_course_name`` רץ בטעינת כל קובץ תוכנית ובפענוח
    הידיעון, והנתונים עצמם תוקנו.
  * '...בביו.' / 'דרישות רגולטוריות ו-GMP בביוטכ' / 'פיזיקה 3ב' — ‏
    ``biotech.json`` מולא משמות הידיעון, שקוטע ב-40 תווים ומקצר, במקום
    מהשמות שב-``biotech.pdf``.
  * אותו קורס נקרא בשני שמות: שלב הקורסים לקח את שם התוכנית, ושלב המרצים
    והמערכת את שם הידיעון. עכשיו ``/api/courses`` ו-``/api/solve`` מקבלים
    את המסלול, והשם שהתוכנית שלו מדפיסה גובר.
"""

from __future__ import annotations

import json
import re
import socket
import sys
import threading
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import curriculum as curriculum_mod  # noqa: E402
from models import normalize_course_name  # noqa: E402
from web.api import create_app  # noqa: E402

MATH_ID = "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה"
MATH_LABEL = "מתמטיקה שימושית"
BIO = "הנדסת ביוטכנולוגיה"
CIVIL = "הנדסה אזרחית"
CURRICULUM_FILES = sorted((ROOT / "data" / "curricula").glob("*.json")) + [
    ROOT / "data" / "curriculum.json"
]
GLUED = re.compile(r"[א-ת][\"'׳״]?\d")


@pytest.fixture(scope="module")
def client():
    return create_app(config={"allow_network": False}).test_client()


def programs(client) -> dict:
    return {p["id"]: p for p in client.get("/api/bootstrap").get_json()["programs"]}


def names_of(node) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        if isinstance(node.get("name"), str):
            out.append(node["name"])
        for value in node.values():
            out.extend(names_of(value))
    elif isinstance(node, list):
        for value in node:
            out.extend(names_of(value))
    return out


# ==========================================================================
# 1. שם המסלול
# ==========================================================================
def test_applied_maths_is_shown_by_the_name_its_curriculum_prints(client):
    entry = programs(client)[MATH_ID]
    assert entry["label"] == MATH_LABEL


def test_there_is_exactly_one_applied_maths_program(client):
    """אין "מתמטיקה שימושית" שנייה, רגילה: השנתון מדפיס תוכנית אחת."""
    maths = [p for p in programs(client).values() if "מתמטיקה" in p["label"]]
    assert len(maths) == 1


def test_no_program_label_claims_an_ai_specialisation(client):
    for entry in programs(client).values():
        assert "התמחות ב-AI" not in entry["label"], entry


def test_the_program_id_is_unchanged_so_saved_choices_still_match(client):
    assert MATH_ID in programs(client)


def test_every_other_program_keeps_its_name(client):
    for pid, entry in programs(client).items():
        if pid not in (MATH_ID, "other"):
            assert entry["label"] == pid


@pytest.mark.parametrize("intake", ["winter", "spring"])
def test_both_math_files_carry_the_label_with_its_source(intake):
    data = json.loads(
        (ROOT / "data" / "curricula" / f"math-{intake}.json").read_text(encoding="utf-8")
    )
    assert data["program"] == MATH_ID
    assert data["program_label"] == MATH_LABEL
    assert "תוכנית הלימודים במתמטיקה שימושית" in data["program_label_source"]


# ==========================================================================
# 2. מספר צמוד לשם
# ==========================================================================
@pytest.mark.parametrize(
    "raw, expected",
    [
        ('חדו"א2', 'חדו"א 2'),
        ("מבני בטון1", "מבני בטון 1"),
        ("פיזיקה1 אז'", "פיזיקה 1 אז'"),
        ("חדו\"א 2", "חדו\"א 2"),
        ("תעשייה 4.0 - המפעל החכם", "תעשייה 4.0 - המפעל החכם"),
        ("C++ מודרני", "C++ מודרני"),
        ("Web3", "Web3"),
        ('ציון "80"', 'ציון "80"'),
        ("", ""),
    ],
)
def test_normalize_course_name(raw, expected):
    assert normalize_course_name(raw) == expected


@pytest.mark.parametrize("path", CURRICULUM_FILES, ids=lambda p: p.name)
def test_no_curriculum_file_glues_a_number_to_a_name(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    bad = [n for n in names_of(raw) if GLUED.search(n)]
    assert not bad, f"{path.name}: {bad}"


def test_loading_a_curriculum_normalises_names(tmp_path):
    """שלב הנרמול רץ בטעינה, כך שגם קובץ שיחולץ מחר מ-PDF יוצג נכון."""
    target = tmp_path / "x.json"
    target.write_text(
        json.dumps({"semesters": {"1": {"courses": [{"code": "1", "name": 'חדו"א2'}]}}}),
        encoding="utf-8",
    )
    data = curriculum_mod.load_curriculum(target)
    assert data["semesters"]["1"]["courses"][0]["name"] == 'חדו"א 2'


def test_civil_shows_calculus_2_with_a_space(client):
    data = client.get(f"/api/semester/2/courses?program={quote(CIVIL)}").get_json()
    names = {c["code"]: c["name"] for c in data["courses"]}
    assert names["11005"] == 'חדו"א 2'
    assert not [n for n in names.values() if GLUED.search(n)]


# ==========================================================================
# 3. שמות קטועים בביוטכנולוגיה
# ==========================================================================
def bio_names() -> dict[str, str]:
    data = curriculum_mod.load_curriculum(ROOT / "data" / "curricula" / "biotech.json")
    return {
        c["code"]: c["name"]
        for sem in data["semesters"].values()
        for c in sem["courses"]
        if c.get("code")
    }


def test_scientific_writing_is_written_in_full():
    assert bio_names()["41711"] == "כתיבה מדעית ושימוש במאגרי מידע בביוטכנולוגיה"


def test_gmp_is_shown_as_the_curriculum_prints_it():
    assert bio_names()["41730"] == "GMP"


def test_physics_3_is_the_same_course_and_shown_as_physics_3():
    """אותו קוד (11027) בתוכנית ובידיעון — אותו קורס. השנתון: "פיזיקה 3"."""
    assert bio_names()["11027"] == "פיזיקה 3"


@pytest.mark.parametrize("path", CURRICULUM_FILES, ids=lambda p: p.name)
def test_no_curriculum_name_ends_in_a_truncation_dot(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    bad = [n for n in names_of(raw) if n.rstrip().endswith(".")]
    assert not bad, f"{path.name}: {bad}"


def test_year_4_semester_a_lists_the_full_names(client):
    data = client.get(f"/api/semester/7/courses?program={quote(BIO)}").get_json()
    names = {c["code"]: c["name"] for c in data["courses"]}
    assert names["41711"] == "כתיבה מדעית ושימוש במאגרי מידע בביוטכנולוגיה"
    assert names["41730"] == "GMP"


# ==========================================================================
# 4. אותו שם בכל שלב
# ==========================================================================
def course_names(client, codes, **extra) -> dict[str, str]:
    body = {"codes": codes, "semester": "א", "fetch_missing": False, **extra}
    data = client.post("/api/courses", json=body).get_json()
    rows = data["courses"] + data["not_offered"]
    return {r["code"]: r.get("name") for r in rows}


def test_the_lecturers_step_uses_the_programs_own_name(client):
    names = course_names(client, ["41730", "41711", "11027"], program=BIO)
    assert names == {
        "41730": "GMP",
        "41711": "כתיבה מדעית ושימוש במאגרי מידע בביוטכנולוגיה",
        "11027": "פיזיקה 3",
    }


def test_without_a_program_the_yedion_name_stays(client):
    """קורס שאינו בתוכנית של אף מסלול שנבחר נקרא בשם הידיעון."""
    names = course_names(client, ["41730"])
    assert names["41730"] == "דרישות רגולטוריות ו-GMP בביוטכ"


def test_the_timetable_uses_the_programs_own_name(client):
    data = client.post(
        "/api/solve", json={"codes": ["41730", "41711"], "semester": "א", "program": BIO}
    ).get_json()
    picks = [p for s in data.get("schedules") or [] for p in s.get("picks", [])]
    assert picks, "אמורה להיות לפחות מערכת אחת"
    assert {p["code"]: p["name"] for p in picks} == {
        "41730": "GMP",
        "41711": "כתיבה מדעית ושימוש במאגרי מידע בביוטכנולוגיה",
    }


def test_a_cut_off_yedion_name_is_restored_when_a_curriculum_has_it(client):
    """הידיעון: '...במערכות מודר'. אשכול הבחירה של תוכנה מדפיס את השם המלא."""
    data = client.get("/api/catalog/search?q=62015").get_json()
    names = {r["code"]: r["name"] for r in data["results"]}
    assert names["62015"] == "סמינר בניתוח סיבוכיות חישוב במערכות מודרניות"


def test_a_different_curriculum_name_is_not_a_restoration(client):
    """'דרישות רגולטוריות ו-GMP בביוטכ' אינו תחילתו של 'GMP' — אין החלפה בחיפוש."""
    data = client.get("/api/catalog/search?q=41730").get_json()
    names = {r["code"]: r["name"] for r in data["results"]}
    assert names["41730"] == "דרישות רגולטוריות ו-GMP בביוטכ"


# ==========================================================================
# 5. בדפדפן: תיבת המסלול
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
def page(server):
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # אין דפדפן מותקן — לא כישלון של הקוד
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            p = browser.new_page()
            p.goto(server)
            p.wait_for_timeout(1500)
            yield p
        finally:
            browser.close()


def test_the_program_box_shows_the_curriculum_name(page):
    options = page.evaluate(
        "() => [...document.querySelectorAll('#select-program option')]"
        ".map(o => [o.value, o.textContent.trim()])"
    )
    labels = dict(options)
    assert labels[MATH_ID] == MATH_LABEL
    assert not [t for _v, t in options if "התמחות ב-AI" in t]
