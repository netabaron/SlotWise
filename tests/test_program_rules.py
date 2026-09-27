# -*- coding: utf-8 -*-
"""חוקי בחירה, משבצות סמסטר והגדרות התמחות בקובצי התוכניות.

שלושה בלוקים שהוקלדו ידנית מהשנתון, עם מקור לכל ערך:
``elective_rules``, ``semester_slots`` ו-``specialization``. כל מספר כאן נלקח
מ-``docs/PROGRAM_FINDINGS.md``; סמסטר תחילת ההתמחות מ-``docs/DESIGN.md``.

החוקים מפנים לרשימות ב-``data/curricula.json`` לפי מפתח, ולכן הבדיקות כאן
מוודאות גם שכל הפניה נוחתת על רשימה ועל קוד שקיימים שם. בסוף יש מונה קטן
שמראה שהחוקים ניתנים לספירה מול בחירה נוכחית, כמו שלב הקורסים יעשה.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

CIVIL = "הנדסה אזרחית"
ELECTRIC = "הנדסת חשמל ואלקטרוניקה"
INDUSTRY = "הנדסת תעשייה וניהול"
MECHANICAL = "הנדסת מכונות"
SOFTWARE = "הנדסת תוכנה"
INFOSYS = "הנדסת מערכות מידע"

DS = "מדעי הנתונים"
DO = "תכן ותפעול של מערכות ייצור ושירות"

FILES = {
    "civil": DATA / "curricula" / "civil.json",
    "electric": DATA / "curricula" / "electronic.json",
    "mechanical": DATA / "curricula" / "mechines.json",
    "industry": DATA / "curricula" / "industry.json",
    "software": DATA / "curriculum.json",
    "infosystems": DATA / "curricula" / "infosystems.json",
    "math-winter": DATA / "curricula" / "math-winter.json",
    "math-spring": DATA / "curricula" / "math-spring.json",
    "biotech": DATA / "curricula" / "biotech.json",
}

RULE_TYPES = {
    "min_courses", "min_credits", "max_credits", "exact_courses",
    "min_total_courses", "mutually_exclusive", "only_one_counts", "text",
}
SLOT_KINDS = {"electives", "general", "sport", "skills"}
SLOT_BASES = {"placeholder_row", "list_heading", "prose", "recommendation", "not_placed", "not_stated"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def files() -> dict[str, dict]:
    return {key: _load(path) for key, path in FILES.items()}


@pytest.fixture(scope="module")
def lists() -> dict:
    return _load(DATA / "curricula.json")["programs"]


def rules(doc: dict) -> list[dict]:
    return doc["elective_rules"]["rules"]


def by_id(doc: dict) -> dict[str, dict]:
    return {r["id"]: r for r in rules(doc)}


# ==========================================================================
# 1. המבנה
# ==========================================================================
def test_every_program_file_has_all_three_blocks(files):
    for key, doc in files.items():
        for block in ("elective_rules", "semester_slots", "specialization"):
            assert block in doc, (key, block)


def test_every_rule_is_typed_and_cited(files):
    for key, doc in files.items():
        ids = [r["id"] for r in rules(doc)]
        assert len(ids) == len(set(ids)), key
        for r in rules(doc):
            assert r["type"] in RULE_TYPES, (key, r["id"])
            assert r["text"].strip(), (key, r["id"])
            source = r["source"]
            assert source["pdf"] == doc["source"] if "source" in doc else source["pdf"] == "sw.pdf"
            assert isinstance(source["page"], int) and source["page"] >= 1, (key, r["id"])
            assert source["quote"].strip(), (key, r["id"])


def test_rule_fields_match_their_type(files):
    for key, doc in files.items():
        for r in rules(doc):
            t = r["type"]
            if t in ("min_courses", "min_total_courses"):
                assert isinstance(r["min"], int) and r["min"] >= 1, (key, r["id"])
            if t == "min_credits":
                assert isinstance(r["min"], float), (key, r["id"])
            if t == "max_credits":
                assert isinstance(r["max"], float), (key, r["id"])
            if t == "exact_courses":
                assert isinstance(r["count"], int), (key, r["id"])
            if t in ("mutually_exclusive", "only_one_counts"):
                assert len(r["codes"]) >= 2 and "lists" not in r, (key, r["id"])
            if t not in ("mutually_exclusive", "only_one_counts", "text"):
                assert r.get("lists") or r.get("codes"), (key, r["id"])


def test_every_list_and_code_a_rule_names_exists(files, lists):
    for key, doc in files.items():
        if doc["elective_rules"]["lists_file"] is None:
            assert not any(r.get("lists") for r in rules(doc)), key
            continue
        assert doc["elective_rules"]["lists_file"] == "data/curricula.json"
        program = lists[doc["program"]]["elective_lists"]
        known = {c["code"] for body in program.values() for c in body["courses"]}
        for r in rules(doc):
            for name in r.get("lists", []):
                assert name in program, (key, r["id"], name)
            if "cluster_rows_from" in r:
                rows = program[r["cluster_rows_from"]]["courses"]
                assert all(row["cluster"] in program for row in rows), (key, r["id"])
            for code in r.get("codes", []):
                # 51170 and 51156 are printed only in Industrial's special list, in no cluster.
                assert code in known or code in {"51170", "51156"}, (key, r["id"], code)


def test_applies_to_names_only_real_specializations_and_routes(files):
    for key, doc in files.items():
        spec = doc["specialization"]
        options = set(spec["options"]) if spec else set()
        routes = {o["route"] for g in (spec or {}).get("routes", []) for o in g["options"]}
        for r in rules(doc):
            scope = r.get("applies_to", {})
            assert set(scope) <= {"specialization", "secondary_specialization", "route"}, (key, r["id"])
            assert set(scope.get("specialization", [])) <= options, (key, r["id"])
            assert set(scope.get("secondary_specialization", [])) <= options, (key, r["id"])
            assert set(scope.get("route", [])) <= routes, (key, r["id"])


# ==========================================================================
# 2. המספרים, מול PROGRAM_FINDINGS.md
# ==========================================================================
PINNED = [
    ("civil", "structures-group-1", "min", 2),
    ("civil", "structures-group-2", "min", 1),
    ("civil", "structures-credits", "min", 9.0),
    ("civil", "management-credits", "min", 14.0),
    ("electric", "main-credits-0", "min", 20.0),
    ("electric", "main-core-0", "min", 6),
    ("electric", "main-core-hw-0", "min", 3),
    ("electric", "main-core-sw-0", "min", 3),
    ("electric", "main-core-1", "min", 4),
    ("electric", "main-core-2", "min", 4),
    ("electric", "secondary-credits-1", "min", 10.0),
    ("electric", "secondary-core-2", "min", 3),
    ("electric", "secondary-core-hw-0", "min", 1),
    ("electric", "secondary-core-sw-0", "min", 1),
    ("electric", "other-industry", "min", 12.0),
    ("electric", "other-research", "min", 4.0),
    ("electric", "other-final", "min", 6.0),
    ("electric", "strip-cap", "max", 3.0),
    ("mechanical", "specialization-credits-0", "min", 28.5),
    ("industry", "ds-information-systems", "min", 4),
    ("industry", "ds-design-operations", "min", 2),
    ("industry", "ds-management", "min", 1),
    ("industry", "do-internship-total", "min", 7),
    ("industry", "do-internship-design-operations", "min", 3),
    ("industry", "do-project-total", "min", 8),
    ("industry", "do-project-design-operations", "min", 4),
    ("industry", "do-internship-special-list", "min", 2),
    ("industry", "do-project-special-list", "min", 2),
    ("industry", "science-technology", "count", 1),
    ("industry", "ds-center-cap", "max", 3.0),
    ("industry", "do-center-cap", "max", 3.0),
]


@pytest.mark.parametrize("key,rule_id,field,value", PINNED)
def test_pinned_numbers(files, key, rule_id, field, value):
    assert by_id(files[key])[rule_id][field] == value


def test_only_civil_targets_are_approximate(files):
    approx = {(k, r["id"]) for k, d in files.items() for r in rules(d) if r.get("approximate")}
    assert approx == {("civil", "structures-credits"), ("civil", "management-credits")}


def test_only_the_two_decided_interpretations_are_marked(files):
    marked = {(k, r["id"]) for k, d in files.items() for r in rules(d) if "interpretation" in r}
    assert marked == {
        ("industry", "do-internship-special-list"), ("industry", "do-project-special-list"),
        ("electric", "other-industry"), ("electric", "other-research"), ("electric", "other-final"),
    }


def test_rules_the_app_cannot_count_are_text_only(files):
    mech = by_id(files["mechanical"])
    assert mech["entrepreneurship-cap"]["type"] == "text"
    assert all(mech[f"specialization-list-20-{i}"]["type"] == "text" for i in range(4))
    assert by_id(files["math-winter"])["mathematical-electives"]["type"] == "text"
    assert by_id(files["infosystems"])["english-seminar"]["type"] == "text"


def test_electrical_secondary_only_for_research_and_final_project(files):
    for r in rules(files["electric"]):
        if r["id"].startswith("secondary-"):
            assert r["applies_to"]["route"] == ["תכן הנדסי מחקרי", "פרויקט גמר בתכן הנדסי"]
    spec = files["electric"]["specialization"]
    assert spec["secondary"]["when_route"] == ["תכן הנדסי מחקרי", "פרויקט גמר בתכן הנדסי"]


def test_electrical_computers_core_areas_exist(lists):
    core = lists[ELECTRIC]["elective_lists"]["מחשבים (חומרה ותוכנה) · קורסי ליבה בהתמחות"]["courses"]
    assert sorted(c["area"] for c in core) == ["חומרה"] * 4 + ["תוכנה"] * 4


def test_industrial_total_excludes_science_and_technology(files):
    for rid in ("do-internship-total", "do-project-total"):
        r = by_id(files["industry"])[rid]
        assert "מדע וטכנולוגיה" not in r["lists"]
        assert r["cluster_rows_from"] == f"{DO} · המרכז לחינוך הנדסי וליזמות"


def test_industrial_special_lists(files):
    ind = by_id(files["industry"])
    base = ["51170", "51025", "51030", "51106", "51113", "51120", "51535", "51537"]
    assert sorted(ind["do-internship-special-list"]["codes"]) == sorted(base)
    assert sorted(ind["do-project-special-list"]["codes"]) == sorted(base + ["51156"])
    for rid in ("do-internship-special-list", "do-project-special-list"):
        assert ind[rid]["count_one_of"] == [["51535", "51537"]]


def test_industrial_exclusive_pairs(files):
    pairs = {(tuple(r["codes"]), tuple(r["applies_to"]["specialization"]))
             for r in rules(files["industry"]) if r["type"] == "mutually_exclusive"}
    for pair in [("251509", "251513"), ("251514", "251965"), ("251507", "251504")]:
        assert (pair, (DS,)) in pairs and (pair, (DO,)) in pairs
    assert (("251966", "51515"), (DS,)) in pairs
    assert (("251966", "51515"), (DO,)) not in pairs


def test_software_rules(files):
    sw = by_id(files["software"])
    assert [sw[f"cluster-{i}"]["min"] for i in range(6)] == [1] * 6
    assert sw["exclusive-62019-61959"]["codes"] == ["62019", "61959"]
    assert sw["exclusive-62023-62002"]["codes"] == ["62023", "62002"]
    assert sw["entrepreneurship-one"]["codes"] == ["251100", "251965"]


def test_software_rules_use_the_list_that_matches_sw_pdf(lists):
    # sw.pdf p. 12 [140] prints 17 rows in אשכול הנדסת תוכנה, 62003 and 62004 among them.
    codes = [c["code"] for c in lists[SOFTWARE]["elective_lists"]["הנדסת תוכנה"]["courses"]]
    assert len(codes) == 17 and {"62003", "62004"} <= set(codes)


def test_math_intakes_share_rules(files):
    assert files["math-winter"]["elective_rules"] == files["math-spring"]["elective_rules"]


def test_biotech_has_no_rules(files):
    assert rules(files["biotech"]) == []
    assert files["biotech"]["specialization"] is None


# ==========================================================================
# 3. משבצות סמסטר
# ==========================================================================
def slots(doc: dict, kind: str, scope: str | None = None) -> list[int]:
    out: list[int] = []
    for s in doc["semester_slots"]:
        if s["kind"] != kind or s["basis"] == "recommendation":
            continue
        if scope and scope not in s.get("applies_to", {}).get("specialization", []):
            continue
        out += s["semesters"] or []
    return sorted(out)


def test_every_program_records_electives_general_and_sport(files):
    for key, doc in files.items():
        kinds = {s["kind"] for s in doc["semester_slots"]}
        assert {"electives", "general", "sport"} <= kinds, key
        n = len(doc["semesters"])
        for s in doc["semester_slots"]:
            assert s["kind"] in SLOT_KINDS and s["basis"] in SLOT_BASES, key
            assert s["source"]["quote"].strip(), key
            if s["any_semester"]:
                assert s["semesters"] is None, key
            if s["semesters"]:
                assert all(1 <= x <= n for x in s["semesters"]), key


EXPECTED_SLOTS = [
    ("civil", "electives", None, [5, 6, 7, 8]),
    ("mechanical", "electives", None, [5, 6, 7, 8]),
    ("electric", "electives", None, []),
    ("industry", "electives", DS, [7]),
    ("industry", "electives", DO, [7, 8]),
    ("software", "electives", None, [7, 8]),
    ("software", "general", None, [1, 4, 6]),
    ("software", "sport", None, [1]),
    ("infosystems", "electives", None, [7, 8]),
    ("infosystems", "general", None, [5, 6, 7]),
    ("infosystems", "sport", None, [1]),
    ("math-winter", "electives", None, [4, 5, 6]),
    ("math-spring", "electives", None, [4, 5, 6]),
    ("biotech", "electives", None, []),
]


@pytest.mark.parametrize("key,kind,scope,expected", EXPECTED_SLOTS)
def test_slot_semesters(files, key, kind, scope, expected):
    assert slots(files[key], kind, scope) == expected


@pytest.mark.parametrize("key", ["civil", "electric", "mechanical", "industry", "math-winter", "math-spring"])
def test_general_and_sport_any_semester(files, key):
    for kind in ("general", "sport"):
        entries = [s for s in files[key]["semester_slots"] if s["kind"] == kind and s["basis"] != "recommendation"]
        assert entries and all(s["any_semester"] for s in entries), (key, kind)


def test_civil_electives_note(files):
    (entry,) = [s for s in files["civil"]["semester_slots"] if s["kind"] == "electives"]
    assert entry["note"] == "קורסי הבחירה נלמדים בשנתיים האחרונות"
    assert entry["source"]["page"] == 2


def test_math_spring_recommendation(files):
    rec = [s for s in files["math-spring"]["semester_slots"] if s["basis"] == "recommendation"]
    assert {s["kind"] for s in rec} == {"general", "sport", "skills"}
    assert all(s["semesters"] == [1, 2, 3] for s in rec)
    assert not any(s["basis"] == "recommendation" for s in files["math-winter"]["semester_slots"])


# ==========================================================================
# 4. הגדרות התמחות
# ==========================================================================
@pytest.mark.parametrize("key,program,semester", [
    ("civil", CIVIL, 3), ("industry", INDUSTRY, 3), ("mechanical", MECHANICAL, 5), ("electric", ELECTRIC, 7),
])
def test_specialization_starts_where_design_md_says(files, lists, key, program, semester):
    spec = files[key]["specialization"]
    assert spec["choose_from_semester"] == semester
    assert spec["options"] == list(lists[program]["specializations"])


@pytest.mark.parametrize("key", ["software", "infosystems", "math-winter", "math-spring", "biotech"])
def test_programs_without_specializations(files, key):
    assert files[key]["specialization"] is None


def test_specialization_options_match_the_program_tracks(files):
    for key in ("civil", "mechanical", "industry"):
        assert files[key]["specialization"]["options"] == files[key]["tracks"]
    # Electrical's tracks are its design routes.
    (design,) = files["electric"]["specialization"]["routes"]
    assert [o["route"] for o in design["options"]] == files["electric"]["tracks"]


def test_route_pickers(files):
    (design,) = files["electric"]["specialization"]["routes"]
    assert design["from_semester"] == 7 and design["applies_to"] == {}
    assert {o["route"]: [c["code"] for c in o["courses"]] for o in design["options"]} == {
        "תכן הנדסי בתעשייה": ["31101", "31104"],
        "תכן הנדסי מחקרי": ["31101", "31103"],
        "פרויקט גמר בתכן הנדסי": ["31100", "31102"],
    }
    (practical,) = files["industry"]["specialization"]["routes"]
    assert practical["from_semester"] == 7 and practical["applies_to"] == {"specialization": [DO]}
    assert {o["route"]: [(c["code"], c["credits"]) for c in o["courses"]] for o in practical["options"]} == {
        "התמחות בתעשייה": [("51014", 5.0), ("51020", 5.0)],
        "פרויקט גמר": [("51230", 4.0), ("51231", 4.0)],
    }


def test_industrial_deadline_line(files):
    deadline = files["industry"]["specialization"]["deadline"]
    assert deadline["text"] == "את ההתמחות בוחרים עד סוף שנה א׳"
    assert deadline["source"]["page"] == 3
    for key in ("civil", "mechanical", "electric"):
        assert files[key]["specialization"]["deadline"] is None


# ==========================================================================
# 5. ניתן לספור: מונה קטן מול בחירה נוכחית
# ==========================================================================
def _rows(program: dict, rule: dict) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for name in rule.get("lists", []):
        for c in program[name]["courses"]:
            if all(c.get(k) == v for k, v in rule.get("where", {}).items()):
                rows[c["code"]] = c
    if "cluster_rows_from" in rule:
        for c in program[rule["cluster_rows_from"]]["courses"]:
            if c["cluster"] in rule.get("lists", []):
                rows[c["code"]] = c
    for code in rule.get("codes", []):
        rows.setdefault(code, {"code": code})
    return rows


def count(program: dict, rule: dict, selected: set[str]) -> float:
    rows = _rows(program, rule)
    hits = [code for code in rows if code in selected]
    for group in rule.get("count_one_of", []):
        extra = [c for c in hits if c in group][1:]
        hits = [c for c in hits if c not in extra]
    if rule["type"] in ("min_credits", "max_credits"):
        return sum(rows[c]["credits"] for c in hits)
    return len(hits)


def test_counter_special_list_counts_51535_or_51537_once(files, lists):
    program = lists[INDUSTRY]["elective_lists"]
    r = by_id(files["industry"])["do-internship-special-list"]
    assert count(program, r, {"51535", "51537"}) == 1
    assert count(program, r, {"51535", "51025"}) == 2


def test_counter_center_rows_count_toward_their_cluster(files, lists):
    program = lists[INDUSTRY]["elective_lists"]
    ind = by_id(files["industry"])
    # 251966's "אשכול" column prints מערכות מידע ומדע הנתונים.
    assert count(program, ind["ds-information-systems"], {"251966"}) == 1
    assert count(program, ind["ds-management"], {"251100", "251102"}) == 2
    assert count(program, ind["ds-center-cap"], {"251100", "251102"}) == 5.0


def test_counter_computers_hardware_area(files, lists):
    program = lists[ELECTRIC]["elective_lists"]
    r = by_id(files["electric"])["main-core-hw-0"]
    assert count(program, r, {"31215", "31226", "31245"}) == 2
