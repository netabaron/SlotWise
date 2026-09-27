"""
המשך למשימת השמות (docs/PROGRAM_REVIEW.md §1–2), 2026-09-25.

  * פיזיקה בביוטכנולוגיה מוצגת כפי שהידיעון קורא לה — "פיזיקה 1ב",
    "פיזיקה 2ב", "פיזיקה 3ב" (עודכן 2026-09-26: גם פיזיקה 3 כמו בידיעון).
  * איות השם של 421223 באזרחית נשאר כפי שהשנתון מדפיס אותו עד אישור.
  * כלל האשכולות "קורס אחד לפחות מכל אשכול" מוצג רק למסלול שתוכנית
    הלימודים שלו מצהירה עליו (תוכנה, מערכות מידע), ומגיע מקובץ התוכנית
    ולא מהקוד.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from web.api import create_app  # noqa: E402

BIO = "הנדסת ביוטכנולוגיה"
MATH = "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה"
RULE = "יש לקחת קורס אחד לפחות מכל אשכול."


@pytest.fixture(scope="module")
def client():
    return create_app(config={"allow_network": False}).test_client()


def electives(client, program: str, intake: str = "") -> dict:
    res = client.get(f"/api/program/electives?program={quote(program)}&intake={intake}")
    assert res.status_code == 200
    return res.get_json()


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


# --- פיזיקה בביוטכנולוגיה ------------------------------------------------
def test_biotech_physics_names(client):
    body = {"codes": ["11023", "11026", "11027"], "semester": "ב",
            "program": BIO, "fetch_missing": False}
    data = client.post("/api/courses", json=body).get_json()
    names = {r["code"]: r["name"] for r in data["courses"] + data["not_offered"]}
    assert names == {"11023": "פיזיקה 1ב", "11026": "פיזיקה 2ב", "11027": "פיזיקה 3ב"}


# --- איות באזרחית: ממתין לאישור -----------------------------------------
def test_civil_421223_keeps_its_printed_spelling_until_confirmed():
    rows = [c for s in load("data/curricula/civil.json")["semesters"].values()
            for c in s["courses"] if c.get("code") == "421223"]
    assert rows and all(r["name"] == "מבוא לאלגרומיתקה ותכנות" for r in rows)


# --- כלל האשכולות --------------------------------------------------------
@pytest.mark.parametrize("program", ["הנדסת תוכנה", "הנדסת מערכות מידע"])
def test_the_rule_is_shown_where_the_curriculum_states_it(client, program):
    data = electives(client, program)
    assert data["clusters"]
    for cluster in data["clusters"]:
        assert cluster["pills"] == [{"type": "min_courses", "n": 1, "approximate": False}]
    quotes = [r["source"]["quote"] for r in data["rules"] if r["id"].startswith("cluster-")]
    assert quotes and all("כל סטודנט חייב לקחת קורס אחד מכל אשכול" in q for q in quotes)


@pytest.mark.parametrize(
    "program, intake",
    [("הנדסת תעשייה וניהול", "&specialization=מדעי הנתונים"), (MATH, "winter"), (MATH, "spring")],
)
def test_no_generic_rule_where_the_curriculum_does_not_state_it(client, program, intake):
    data = electives(client, program, intake)
    assert data["available"] is True and data["clusters"]
    pills = {c["title"]: [p["n"] for p in c["pills"] if p["type"] == "min_courses"]
             for c in data["clusters"]}
    if program == MATH:
        assert all(v == [] for v in pills.values())
    else:
        assert pills["מערכות מידע ומדע הנתונים"] == [4]
        assert pills["תכן ותפעול של מערכות ייצור ושירות"] == [2]
        assert pills["ניהול"] == [1]


@pytest.mark.parametrize("rel", ["data/curriculum.json", "data/curricula/infosystems.json"])
def test_the_rule_lives_in_the_data_with_its_source(rel):
    data = load(rel)
    assert data["cluster_rule"] == RULE
    assert "כל סטודנט חייב לקחת קורס אחד מכל אשכול" in data["cluster_rule_source"]


def test_the_rule_is_not_hard_coded_in_the_api():
    source = (ROOT / "src" / "web" / "api.py").read_text(encoding="utf-8")
    assert RULE not in source

