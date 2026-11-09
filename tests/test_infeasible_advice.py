# -*- coding: utf-8 -*-
"""‏"אין מערכת": ההצעות מדברות עברית, אינן שולחות לשנות את יעד הימים, ואומרות
קודם כול כשקורס שנבחר אינו מהתוכנית.

המקרה (2026-11-09): הנדסת תעשייה וניהול, שנה ג' סמסטר א', "בלי חפיפות".
נבחר ‏11026 ‏פיזיקה 2ב — של ביוטכנולוגיה — במקום ‏11210 ‏פיזיקה 2 IE. ההרצאה
היחידה של ‏11026 (ראשון 13:50–15:50) חופפת להרצאה היחידה של ‏51132 (ראשון
‏11:30–14:50), ולכן אין מערכת. הקופסה אמרה:

* ‏"העלי את target_days מ-4 ל-5" — יעד הימים משנה רק את הניקוד, ולעולם אינו
  הסיבה שאין מערכת; וגם שם משתנה.
* ‏"(every group pair is blocked)", "(drop course 11026)" — אנגלית בסוף כל
  משפט. (באתר המאורח נראה גם "(combinatorial exhaustion — …)"; על הקטלוג
  הקפוא המקרה הזה נותן את סיבת הזוג, ולכן המסלול הקומבינטורי נבדק כאן
  בנפרד, על שלושה קורסים בנויים.)
* ולא אמרה שהקורס בכלל אינו בתוכנית.

‏**הקטלוג הקפוא** (``tests/fixtures/catalog``, דרך ``conftest.py``) ו-``db_root``
ריק — כמו ב-CI ובאתר המאורח. ‏``data/db`` המקומי שונה מהם (‏DEFERRED.md).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import scheduler as scheduler_mod  # noqa: E402
import strings as strings_mod  # noqa: E402
from models import KIND_LECTURE, Course, Group, Meeting  # noqa: E402
from scheduler import Preferences  # noqa: E402
from src.web import api as api_mod  # noqa: E402
from src.web.api import create_app  # noqa: E402

INDUSTRY = "הנדסת תעשייה וניהול"
#: הליבה של סמסטר 5 בתעשייה וניהול, ו-‏11026 שנבחר בטעות. שישה קורסים.
CORE = ["51132", "51159", "51213", "51429", "51724"]
REPRO = CORE + ["11026"]

LATIN = re.compile(r"[A-Za-z]")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    empty_db = tmp_path_factory.mktemp("empty_db")
    return create_app(config={"allow_network": False, "db_root": str(empty_db)})


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


def solve(client, codes, **extra):
    body = {
        "codes": codes,
        "semester": "א",
        "program": INDUSTRY,
        "target_days": 4,
        # ‏"בלי חפיפות בכלל" — מה שהממשק שולח במצב הזה.
        "allow_soft_conflicts": False,
        **extra,
    }
    resp = client.post("/api/solve", json=body)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:400]
    return resp.get_json()


@pytest.fixture(scope="module")
def repro(client):
    data = solve(client, REPRO)
    assert data["schedules"] == [], "המקרה הזה חייב להיות בלי מערכת"
    return data


def course_names(app, codes) -> list[str]:
    """השמות שהנוסח משבץ — אותם ``Course.name`` ש-/api/solve בונה."""
    with app.test_request_context():
        built, _problems, _ = api_mod._build_courses(  # noqa: SLF001
            codes, semester="א", year="", program=INDUSTRY, intake=""
        )
    return [c.name for c in built]


def without_names(text: str, names) -> str:
    for name in sorted(set(names), key=len, reverse=True):
        text = text.replace(name, "")
    return text


# ---------------------------------------------------------------- the report
def test_the_first_suggestion_is_the_swap_to_the_students_own_physics(repro):
    assert repro["swaps"], repro["suggestions"]
    swap = repro["swaps"][0]
    assert (swap["from"], swap["to"]) == ("11026", "11210"), swap
    assert repro["suggestions"][0] == swap["text"], repro["suggestions"]

    first = repro["suggestions"][0]
    assert "11026" in first and "11210" in first, first
    assert "ביוטכנולוגיה" in first, first
    assert "בתוכנית שלך" in first, first


def test_the_swap_record_carries_what_the_button_needs(repro):
    swap = repro["swaps"][0]
    assert swap["from_name"] == "פיזיקה 2ב", swap
    assert swap["to_name"] == "פיזיקה 2 IE", swap
    assert swap["to_credits"] == 4.0, swap
    # ‏"הנדסת" יורד, כמו בתווית שליד שם הקורס בחיפוש.
    assert swap["from_programs"] == ["ביוטכנולוגיה"], swap


def test_no_reason_or_suggestion_names_target_days_or_has_english(app, repro):
    names = course_names(app, REPRO + ["11210"])
    texts = list(repro["reasons"]) + list(repro["suggestions"])
    assert texts
    for text in texts:
        assert "target_days" not in text, text
        assert "יעד הימים" not in text, text
        leftover = without_names(text, names)
        assert not LATIN.search(leftover), (text, LATIN.findall(leftover))


def test_the_in_plan_course_is_not_offered_as_the_one_to_drop(repro):
    drop_51132 = strings_mod.fmt(
        "server.infeasible.tipDrop",
        code="51132", name="תכנון ותפעול תהליך האספקה בארגון",
    )
    assert drop_51132 not in repro["suggestions"], repro["suggestions"]
    assert not any(s.startswith("אפשר לוותר על 51132") for s in repro["suggestions"])
    # ‏ויתור על הקורס שמחוץ לתוכנית נשאר — כאפשרות משנית, אחרי ההחלפה.
    assert any(s.startswith("אפשר לוותר על 11026") for s in repro["suggestions"][1:])


def test_at_most_three_suggestions_and_overlaps_come_last(repro):
    suggestions = repro["suggestions"]
    assert 1 <= len(suggestions) <= 3, suggestions
    overlap = [i for i, s in enumerate(suggestions) if "חובת נוכחות" in s]
    if overlap:
        assert overlap == [len(suggestions) - 1], suggestions


def test_the_reason_still_names_the_colliding_pair(repro):
    joined = "\n".join(repro["reasons"])
    assert "51132" in joined and "11026" in joined, joined
    assert "13:50-14:50" in joined, joined


def test_the_swap_really_opens_schedules(client):
    data = solve(client, CORE + ["11210"])
    assert data["schedules"], data["reasons"]
    assert data["swaps"] == []


def test_a_target_already_chosen_is_not_offered_again(client):
    data = solve(client, REPRO + ["11210"])
    assert data["schedules"] == []
    assert data["swaps"] == [], data["swaps"]


def test_without_a_program_there_is_nothing_to_swap_to(client):
    data = solve(client, REPRO, program="")
    assert data["schedules"] == []
    assert data["swaps"] == []
    assert data["suggestions"], data
    assert len(data["suggestions"]) <= 3
    assert not any("target_days" in s or "יעד הימים" in s for s in data["suggestions"])
    # ‏בלי החלפה, ויתור על ‏51132 הוא הצעה לגיטימית.
    assert any("51132" in s for s in data["suggestions"]), data["suggestions"]


# ---------------------------------------------------------- the ordering rule
def _course(code: str, name: str) -> Course:
    return Course(code=code, name=name, credits=1.0, groups=[], tied_with=[])


@pytest.mark.parametrize(
    "blocked_with, held_back",
    [
        (["11026"], True),            # כל מה שחוסם הוא הקורס שמוחלף
        (["11026", "51213"], False),  # יש לו גם בעיה משלו מול קורס מהתוכנית
        ([], False),                  # רכיב שנמחק לבדו — לא קשור להחלפה
    ],
)
def test_dropping_an_in_plan_course_is_held_back_only_when_the_swap_solves_it(
    app, monkeypatch, blocked_with, held_back
):
    built = [
        _course("51132", "תכנון ותפעול תהליך האספקה בארגון"),
        _course("51213", "ניהול איכות סטטיסטי"),
        _course("11026", "פיזיקה 2ב"),
    ]
    drop_51132 = {
        "kind": "drop", "text": "drop-51132", "codes": ["51132"],
        "blocked_with": blocked_with, "wiped": not blocked_with,
    }
    advice = [
        {"kind": "overlap", "text": "overlap", "codes": ["51132", "11026"]},
        drop_51132,
        {"kind": "drop", "text": "drop-11026", "codes": ["11026"],
         "blocked_with": ["51132"], "wiped": False},
    ]
    monkeypatch.setattr(scheduler_mod, "relax_advice", lambda *_a, **_k: list(advice))
    with app.test_request_context():
        texts, swaps = api_mod._infeasible_advice(  # noqa: SLF001
            built, Preferences(), INDUSTRY, ""
        )
    assert [s["to"] for s in swaps] == ["11210"]
    assert texts[0] == swaps[0]["text"]
    assert ("drop-51132" not in texts) is held_back, texts
    assert "drop-11026" in texts
    assert len(texts) <= 3, texts
    # ‏החפיפה אחרונה; כשיש ארבע הצעות היא זו שנחתכת.
    if held_back:
        assert texts == [swaps[0]["text"], "drop-11026", "overlap"], texts
    else:
        assert texts == [swaps[0]["text"], "drop-51132", "drop-11026"], texts


# ------------------------------------------------------- the scheduler itself
def _group(code: str, gid: str, day: int, start: int, end: int) -> Group:
    return Group(
        course_code=code, group_id=gid, kind=KIND_LECTURE, lecturer="מרצה",
        meetings=[Meeting(day=day, start=start, end=end)], linked_to=[],
    )


def _pigeonhole() -> list[Course]:
    """שלושה קורסים, לכל אחד שתי קבוצות באותן שתי משבצות.

    כל זוג מסתדר (אחד בכל משבצת), אבל שלושה אינם נכנסים לשתי משבצות — כלומר
    אין זוג אשם, וזה בדיוק המסלול "הקומבינטורי" של האבחון.
    """
    return [
        Course(
            code=code, name=f"קורס {code}", credits=1.0, tied_with=[],
            groups=[_group(code, "1", 1, 510, 600), _group(code, "2", 1, 600, 690)],
        )
        for code in ("90001", "90002", "90003")
    ]


def test_the_combinatorial_reason_is_hebrew_and_gives_no_advice():
    courses = _pigeonhole()
    with pytest.raises(scheduler_mod.Infeasible):
        scheduler_mod.solve(courses, Preferences(), top_n=1)
    reasons = scheduler_mod.diagnose_infeasibility(courses, Preferences())
    assert reasons == [strings_mod.fmt("server.infeasible.combinatorial", n="8")], reasons
    assert not LATIN.search(reasons[0]), reasons[0]
    assert "combinatorial" not in reasons[0]


@pytest.mark.parametrize("target_days", [1, 4, 5])
def test_relax_advice_never_suggests_the_days_target(target_days):
    prefs = Preferences(target_days=target_days, forbid_friday=True, earliest=600)
    for courses in (_pigeonhole(), _pigeonhole()[:1]):
        advice = scheduler_mod.relax_advice(courses, prefs)
        texts = scheduler_mod.relax_suggestions(courses, prefs)
        assert texts == [t["text"] for t in advice]
        for tip in advice:
            assert tip["kind"] != "target_days"
            assert "target_days" not in tip["text"] and "יעד הימים" not in tip["text"]
            assert not LATIN.search(tip["text"]), tip["text"]


def test_every_infeasible_template_is_hebrew_without_latin():
    """הנוסח עצמו, לפני הצבה: אף שם משתנה ואף מילה באנגלית."""
    templates = strings_mod.get("server.infeasible", {})
    assert isinstance(templates, dict) and templates
    for key, text in templates.items():
        bare = re.sub(r"\{\w+\}", "", text)
        assert not LATIN.search(bare), (key, text)
