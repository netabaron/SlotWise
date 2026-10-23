# -*- coding: utf-8 -*-
"""כל מסלול × שנה × סמסטר נפתר, בבחירה שהדף ממליץ עליה, בכמות עבודה קבועה.

‏``test_solver_performance.py`` מחזיק את שנה א' סמסטר א' של חמישה מסלולים.
הקובץ הזה מחזיק את **כל** מה ש-``/api/bootstrap`` מציע: כל מסלול שיש לו
תוכנית, כל סמסטר בלוח שלו, ולמתמטיקה שימושית — כל מועד כניסה. לכל אחד:
‏``/api/solve`` עם רשימת ההמלצה של הסמסטר וברירת המחדל של הדף לנוכחות,
והתשובה חייבת להיות ‏200, בלי ``timed_out``, ובתוך תקציב צמתים.

‏**הבחירה היא זו שהדף ממליץ עליה**, מחושבת כאן בדיוק כמו ב-app.js:
‏``recommendedCodes()`` (חלופות הדדיות וקורסים שאינם נפתחים בחוץ, חבילות
צמודות נשפטות יחד) ואחריה ``capRecommended()`` (חיתוך ל-``max_codes``
בחבילות שלמות). מאז שהדף מציג את ההמלצה בלי לסמן אותה זו הבחירה של
לחיצה אחת על "סימון הרשימה", ולא מה שמסומן בטעינה — אותה הגדרה שבה
‏``test_solver_performance.py`` משתמש. נוכחות: ``False`` לכל רכיב שהידיעון
אינו מחייב בו (``attendanceBody()``), כמו בדף.

‏**מה נמדד — ולמה לא שעון.** כמו ב-``test_solver_performance.py``: מספר
צמתי החיפוש של הבקשה כולה (כל ``_Budget.tick()``), שהוא דטרמיניסטי — אותו
קוד ואותו קטלוג קפוא נותנים אותו מספר בכל מכונה. אין כאן שום סף זמן.

‏התקציבים הם המספרים שנמדדו ב-2026-10-23 ועוד כ-10%, מעוגלים כלפי מעלה
לאלף. שינוי מכוון באלגוריתם, בקטלוג הקפוא או בתוכניות הלימודים מעדכן אותם
כאן, באותו commit. סמסטר שמסלול נוסף או ירד ממנו נתפס ב-
``test_the_cases_are_exactly_what_the_bootstrap_offers``.

‏מה שנכשל היום מסומן ‏xfail קפדני ולא מושמט: סמסטר אחד שהחיפוש עצמו נעצר בו
(``KNOWN_TIMEOUT``), ושתי בחירות שיעד ימים בלתי אפשרי עוצר בהן את הצעות הוויתור
(``KNOWN_RELAXATION_TIMEOUT``). תיקון בפותר הופך כל אחד מהם לכישלון, ואז
מודדים, מוסיפים תקציב ומסירים את הסימון.

‏**מסד ריק, לא המסד המקומי.** האפליקציה כאן רצה מול תיקיית מסד ריקה, כמו
התמונה המתארחת (‏Dockerfile יוצר ``data/db`` ריק). המסד שה-CI זורע
(‏``seed_dev_data.py --fixture``) מחזיק סמסטר א' בלבד, ורשומה מקומית שמכסה
קוד אינה מסוננת לסמסטר בקריאה (DEFERRED.md, ‏``_store_for``) — ולכן מולו
בקשה לסמסטר ב' נענית מקבוצות סמסטר א'. נמדד: ‏electrical-s2 מול המסד
הזרוע — 35 קבוצות, כולן סמסטר א'; מול מסד ריק — 52 קבוצות, כולן סמסטר ב'.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src.web import api  # noqa: E402

sch = api.scheduler_mod

#: ‏שם קצר ויציב לכל מסלול, למזהי הבדיקות ולמפתחות התקציב.
SLUGS = {
    "הנדסה אזרחית": "civil",
    "הנדסת ביוטכנולוגיה": "biotech",
    "הנדסת חשמל ואלקטרוניקה": "electrical",
    "הנדסת מכונות": "mechanical",
    "הנדסת מערכות מידע": "infosystems",
    "הנדסת תוכנה": "software",
    "הנדסת תעשייה וניהול": "industrial",
    "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה": "math",
}

#: ‏``TIED_FALLBACK`` ב-app.js.
TIED_FALLBACK = [["61756", "61757", "62027"]]


# ==========================================================================
# מה הדף עושה — מועתק מ-app.js, בלי שיקול דעת משלו
# ==========================================================================
def _txt(value) -> str:
    return "" if value is None else str(value).strip()


def offered_cases(bootstrap: dict) -> list[dict]:
    """כל מסלול × סמסטר בלוח שלו, כפי שהדף בונה אותם מ-``/api/bootstrap``.

    ‏מסלול בלי לוח (``other``) אינו כאן: אין לו רשימת המלצה, ולכן אין לדף
    מה לשלוח. כך גם קיץ — אין לו שורה באף לוח.
    """
    out = []
    for row in bootstrap["programs"]:
        program = _txt(row.get("id"))
        intakes = [_txt(i.get("id")) for i in row.get("intakes") or []]
        if intakes:
            boards = bootstrap.get("semesters_by_program_intake", {}).get(program, {})
            plans = [(intake, boards.get(intake) or []) for intake in intakes]
        else:
            plans = [("", bootstrap.get("semesters_by_program", {}).get(program) or [])]
        for intake, rows in plans:
            for sem in rows:
                slug = SLUGS.get(program, program)
                out.append({
                    "id": f"{slug}-{intake + '-' if intake else ''}s{sem['semester']}",
                    "program": program,
                    "intake": intake,
                    "semester": _txt(sem["semester"]),
                    "year": sem.get("year"),
                    "term": _txt(sem.get("term")),
                    "spec": row.get("specialization"),
                })
    return out


def semester_list(client, case: dict, specialization: str = "", route: str = "") -> dict:
    """‏``fetchSemesterCourses()``: ‏GET ‏/api/semester/<n>/courses."""
    res = client.get(
        f"/api/semester/{case['semester']}/courses",
        query_string={"program": case["program"], "intake": case["intake"],
                      "specialization": specialization, "route": route},
    )
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()


def recommended_codes(data: dict, max_codes: int) -> list[str]:
    """‏``recommendedCodes()`` ואחריו ``capRecommended(…, [])``."""
    recs = [
        {
            "code": _txt(r.get("code")),
            "tied_with": [_txt(c) for c in r.get("tied_with") or []],
            "placement": r.get("placement") is True,
            "physics_track": _txt(r.get("physics_track")),
            "track": _txt(r.get("track")),
            "track_chosen": r.get("track_chosen") is True,
            "offered": r.get("offered") is not False,
        }
        for r in data.get("courses") or []
    ]
    recs = [r for r in recs if r["code"]]
    by_code: dict[str, dict] = {}
    for r in recs:
        by_code.setdefault(r["code"], r)
    catalog_count = (data.get("fallback") or {}).get("catalog_count")
    offered_known = catalog_count is not None and catalog_count > 0
    families = [[r["code"], *r["tied_with"]] for r in recs if r["tied_with"]]
    families += [list(f) for f in TIED_FALLBACK]

    def tied_group(code):
        group = {code}
        changed, guard = True, 0
        while changed and guard < 12:
            changed, guard = False, guard + 1
            for family in families:
                if any(x in group for x in family):
                    for x in family:
                        if x and x not in group:
                            group.add(x)
                            changed = True
        return group

    def recommendable(rec):
        if not rec or not rec["code"]:
            return False
        if rec["placement"] or rec["physics_track"]:
            return False
        if rec["track"] and not rec["track_chosen"]:
            return False
        if offered_known and rec["offered"] is False:
            return False
        return True

    decided: dict[str, bool] = {}
    for r in recs:
        code = r["code"]
        if code in decided:
            continue
        family = [c for c in tied_group(code) if c in by_code]
        if code not in family:
            family.append(code)
        ok = all(recommendable(by_code.get(c)) for c in family)
        for c in family:
            decided[c] = ok
    rec_codes = list(dict.fromkeys(r["code"] for r in recs if decided.get(r["code"]) is True))

    kept = list(rec_codes)
    while max_codes > 0 and kept and len(set(kept)) > max_codes:
        family = tied_group(kept[-1])
        before = len(kept)
        kept = [c for c in kept if c not in family]
        if len(kept) == before:
            break
    return kept


def page_attendance(attendance_info: dict) -> dict:
    """‏``attendanceBody()`` בלי בחירה שמורה: ‏False לכל רכיב שהידיעון אינו מחייב."""
    return {
        code: {kind: False for kind, rec in kinds.items() if not rec.get("from_yedion")}
        for code, kinds in (attendance_info or {}).items()
        if any(not rec.get("from_yedion") for rec in kinds.values())
    }


def courses_request(client, case: dict, codes: list[str], year: str = "") -> dict:
    """‏``fetchCourses()``: ‏POST ‏/api/courses, בלי שליפה מהידיעון."""
    res = client.post("/api/courses", json={
        "codes": codes, "semester": case["term"], "year": year,
        "program": case["program"], "intake": case["intake"], "fetch_missing": False,
    })
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()


def solve_body(case: dict, codes: list[str], attendance: dict, year: str = "", **extra) -> dict:
    """‏``buildSolveBody()`` עם מצב ברירת המחדל של הדף (‏``defaultState()``)."""
    body = {
        "codes": codes, "semester": case["term"], "year": year,
        "program": case["program"], "intake": case["intake"],
        "target_days": 6, "ranked": {}, "blocked": [], "forbid_friday": False,
        "top_n": 5, "allow_soft_conflicts": True,
    }
    if attendance:
        body["attendance"] = attendance
    body.update(extra)
    return body


def count_nodes(monkeypatch):
    """סופר כל צומת חיפוש — כל ``_Budget.tick()`` — בכל השלבים של הבקשה."""
    counter = {"n": 0}
    tick = sch._Budget.tick  # noqa: SLF001

    def counting(self):
        counter["n"] += 1
        return tick(self)

    monkeypatch.setattr(sch._Budget, "tick", counting)  # noqa: SLF001
    return counter


# ==========================================================================
# התקציבים
# ==========================================================================
#: ‏סמסטר שהבקשה שלו מגיעה היום למגבלת הזמן. ראו ``KNOWN_TIMEOUT``.
TIMES_OUT = "times out"

#: ‏למה ``TIMES_OUT``. ‏xfail קפדני: תיקון בפותר הופך אותו לכישלון, ואז
#: מודדים ומחליפים בתקציב.
KNOWN_TIMEOUT = (
    "‏2026-10-23: לקבוצות סמסטר ב' של חמשת הקורסים אין עדיין מועד, וכל הרכיבים "
    "אינם חובה — כל העלים שווים בארבע הרמות הראשונות של ``_sort_key`` (ימים מעל "
    "היעד, מרצים, חפיפות, ניקוד), החיפוש אינו גוזם, ו-/api/solve נעצר ב-"
    "``SOLVE_DEADLINE_S`` עם מערכות ``truncated``. כך גם ב-slotwise.co.il."
)

#: ‏מזהה → ‏(נמדד ב-2026-10-23, תקציב). התקציב ≈ נמדד × 1.1, מעוגל כלפי מעלה
#: לאלף. ‏``None`` = לרשימת ההמלצה של הסמסטר הזה אין אף קורס שהדף מסמן,
#: ולכן אין מה לפתור. ‏``(0, 0)`` = לקורס היחיד אין קבוצות בקטלוג הקפוא,
#: והתשובה חוזרת לפני כל חיפוש.
NODES: dict[str, tuple[int, int] | str | None] = {
    "civil-s1": (23_292, 26_000),
    "civil-s2": (1_604, 2_000),
    "civil-s3": (1_003, 2_000),
    "civil-s4": (2_680, 3_000),
    "civil-s5": (546, 1_000),
    "civil-s6": (278, 1_000),
    "civil-s7": (24, 1_000),
    "civil-s8": (4, 1_000),
    "biotech-s1": (17_599, 20_000),
    "biotech-s2": (16_904, 19_000),
    "biotech-s3": (439, 1_000),
    "biotech-s4": (458, 1_000),
    "biotech-s5": (342, 1_000),
    "biotech-s6": (214, 1_000),
    "biotech-s7": (175, 1_000),
    "biotech-s8": (4, 1_000),
    "electrical-s1": (23_131, 26_000),
    "electrical-s2": TIMES_OUT,
    "electrical-s3": (24_640, 28_000),
    "electrical-s4": (13_837, 16_000),
    "electrical-s5": (4_225, 5_000),
    "electrical-s6": (653, 1_000),
    "electrical-s7": None,
    "electrical-s8": None,
    "mechanical-s1": (19_415, 22_000),
    "mechanical-s2": (29_306, 33_000),
    "mechanical-s3": (997, 2_000),
    "mechanical-s4": (376, 1_000),
    "mechanical-s5": (437, 1_000),
    "mechanical-s6": (614, 1_000),
    "mechanical-s7": (10, 1_000),
    "mechanical-s8": (0, 0),
    "infosystems-s1": (9_383, 11_000),
    "infosystems-s2": (1_790, 2_000),
    "infosystems-s3": (6_971, 8_000),
    "infosystems-s4": (9_762, 11_000),
    "infosystems-s5": (641, 1_000),
    "infosystems-s6": (331, 1_000),
    "infosystems-s7": (204, 1_000),
    "infosystems-s8": (0, 0),
    "software-s1": (10_691, 12_000),
    "software-s2": (979, 2_000),
    "software-s3": (2_634, 3_000),
    "software-s4": (9_762, 11_000),
    "software-s5": (5_494, 7_000),
    "software-s6": (6_727, 8_000),
    "software-s7": (204, 1_000),
    "software-s8": (0, 0),
    "industrial-s1": (43_159, 48_000),
    "industrial-s2": (16_904, 19_000),
    "industrial-s3": (212, 1_000),
    "industrial-s4": (726, 1_000),
    "industrial-s5": (204, 1_000),
    "industrial-s6": (87, 1_000),
    "industrial-s7": (24, 1_000),
    "industrial-s8": None,
    "math-winter-s1": (8_202, 10_000),
    "math-winter-s2": (455, 1_000),
    "math-winter-s3": (154, 1_000),
    "math-winter-s4": (202, 1_000),
    "math-winter-s5": (64, 1_000),
    "math-winter-s6": (46, 1_000),
    "math-spring-s1": (218, 1_000),
    "math-spring-s2": (446, 1_000),
    "math-spring-s3": (100, 1_000),
    "math-spring-s4": (24, 1_000),
    "math-spring-s5": (98, 1_000),
    "math-spring-s6": (48, 1_000),
}

CASES = [
    pytest.param(case_id, marks=pytest.mark.xfail(reason=KNOWN_TIMEOUT, strict=True))
    if expected == TIMES_OUT else case_id
    for case_id, expected in NODES.items()
]

#: ‏יעד ימים שאינו אפשרי. נמדד ב-2026-10-23: המינימום של שתי הבחירות האלה הוא
#: ‏4, המערכות עצמן מוכנות בפחות משנייה, ו-``_day_relaxations_json`` לבדו רץ
#: עד ``SOLVE_DEADLINE_S`` — ‏19.6 ו-19.2 שניות כאן, ‏770–820 אלף צמתים בקטלוג
#: האמיתי.
KNOWN_RELAXATION_TIMEOUT = (
    "‏2026-10-23: יעד של 3 ימים כשהמינימום הוא 4 — ``_day_relaxations_json`` "
    "(איזה קורס להוריד כדי להגיע ליעד) מחפש עד ``SOLVE_DEADLINE_S``, ו-/api/solve "
    "חוזר עם ``timed_out`` אף שחמש המערכות מוכנות ושלמות."
)
UNREACHABLE_TARGET = ["biotech-s1", "industrial-s1"]


# ==========================================================================
# התשתית
# ==========================================================================
@pytest.fixture(scope="module")
def app(tmp_path_factory):
    # מסד ריק — ראו למעלה למה לא המסד המקומי או הזרוע.
    empty = tmp_path_factory.mktemp("empty-store")
    return api.create_app({"allow_network": False}, serve_ui=False, db_root=empty)


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


@pytest.fixture(scope="module")
def bootstrap(client):
    res = client.get("/api/bootstrap")
    assert res.status_code == 200
    return res.get_json()


@pytest.fixture()
def nodes(monkeypatch):
    return count_nodes(monkeypatch)


def test_the_cases_are_exactly_what_the_bootstrap_offers(bootstrap):
    cases = offered_cases(bootstrap)
    unknown = sorted({c["program"] for c in cases} - set(SLUGS))
    assert not unknown, f"מסלול חדש בלי שם קצר ב-SLUGS: {unknown}"
    assert [c["id"] for c in cases] == list(NODES), (
        "הלוחות ב-/api/bootstrap השתנו — יש למדוד מחדש ולעדכן את NODES"
    )


def _solve_page_default(client, bootstrap, nodes, case_id, **extra):
    """‏(הבחירה, התשובה, צמתי החיפוש) לבחירה שהדף ממליץ עליה בסמסטר הזה."""
    case = next(c for c in offered_cases(bootstrap) if c["id"] == case_id)
    codes = recommended_codes(semester_list(client, case), bootstrap["limits"]["max_codes"])
    if not codes:
        return codes, None, 0
    year = bootstrap["defaults"].get("academic_year", "")
    info = courses_request(client, case, codes, year)["attendance"]
    body = solve_body(case, codes, page_attendance(info), year, **extra)
    nodes["n"] = 0
    res = client.post("/api/solve", json=body)
    assert res.status_code == 200, res.get_data(as_text=True)
    return codes, res.get_json(), nodes["n"]


@pytest.mark.parametrize("case_id", CASES)
def test_the_page_default_solves_within_its_node_budget(client, bootstrap, nodes, case_id):
    codes, data, visited = _solve_page_default(client, bootstrap, nodes, case_id)
    expected = NODES[case_id]
    if expected is None:
        assert codes == [], f"{case_id}: יש עכשיו המלצה ({codes}) — יש למדוד ולהוסיף תקציב"
        return
    assert codes, f"{case_id}: רשימת ההמלצה התרוקנה"
    # בלי השדה רק כשאף קורס לא נבנה — התשובה חוזרת לפני כל חיפוש.
    assert data.get("timed_out", False) is False, f"{case_id}: הגיע למגבלת הזמן — כלומר לא נפתר"
    measured, budget = expected
    assert visited <= budget, (
        f"{case_id}: {visited:,} צמתים, מעל התקציב {budget:,} (נמדד {measured:,} ב-2026-10-23)"
    )


@pytest.mark.parametrize("case_id", [
    pytest.param(case_id, marks=pytest.mark.xfail(reason=KNOWN_RELAXATION_TIMEOUT, strict=True))
    for case_id in UNREACHABLE_TARGET
])
def test_an_unreachable_day_target_answers_within_the_deadline(client, bootstrap, nodes, case_id):
    """יעד 3 ימים לבחירה שהמינימום שלה 4: התשובה חייבת לחזור בלי ``timed_out``."""
    codes, data, _visited = _solve_page_default(client, bootstrap, nodes, case_id, target_days=3)
    assert codes, f"{case_id}: רשימת ההמלצה התרוקנה"
    assert data["min_days"] is not None and data["min_days"] > 3, (
        f"{case_id}: המינימום הוא {data['min_days']} — היעד אפשרי, והבדיקה אינה בודקת את מה שהיא מתיימרת"
    )
    assert data["timed_out"] is False, f"{case_id}: הגיע למגבלת הזמן — כלומר לא נפתר"
