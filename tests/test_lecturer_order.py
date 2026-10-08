"""סדר העדיפויות של המנוע: ימים, מרצים, חפיפות, ורק אז הניקוד.

‏docs/DESIGN.md → Lecturers, "How a ranking chooses" (הוחלט 2026-10-09):

    1. פחות ימים מעל יעד הימים;
    2. דירוג המרצים — יותר רכיבים בדירוג 1, ובשוויון יותר הרצאות; אחר כך
       דירוג 2, וכן הלאה. כל סוג רכיב מדורג בנפרד;
    3. פחות חפיפות מכוונות — חפיפה נוגעת תמיד בשיעור שסומן כלא-מחייב-נוכחות,
       ולכן מותר לה לחסוך יום או לכבד מרצה מדורג/ת;
    4. ורק אז חלונות, סיום מאוחר ואורך היום, משוקללים זה מול זה.

אין נקודות שנסחרות בין הרמות. הבדיקות כאן בנויות מנתונים סינתטיים זעירים, כדי
שכל אחת תבודד רמה אחת מול הבאה בתור — ובסוף, ה-API: שתי צורות הדירוג, השדות
החדשים, ו-``pinned`` שאינו נקרא עוד.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from models import KIND_LECTURE, KIND_TUTORIAL, Course, Group, Meeting  # noqa: E402
from scheduler import (  # noqa: E402
    Preferences,
    describe_soft_conflicts,
    rankings_by_kind,
    solve,
)

#: שעות, בדקות מחצות.
H0830, H1030, H1230, H1430, H1630, H1830 = 510, 630, 750, 870, 990, 1110

X, Y, Z, P, T, U = "ד\"ר איקס", "ד\"ר וואי", "ד\"ר זד", "ד\"ר פי", "מר טי", "גב' יו"


def grp(code, gid, kind, lecturer, *slots):
    return Group(
        course_code=code,
        group_id=gid,
        kind=kind,
        lecturer=lecturer,
        meetings=[Meeting(day=d, start=s, end=e) for d, s, e in slots],
    )


def course(code, *groups):
    return Course(code=code, name=f"קורס {code}", credits=1.0, groups=list(groups))


def lecturer_of(sched, code, kind):
    return sched.selection.group_for(code, kind).lecturer


def best(courses, **prefs):
    return solve(courses, Preferences(**prefs), top_n=5)[0]


# --------------------------------------------------------------------------
# 1. דירוג 1 אינו נמכר תמורת חלונות או סיום מאוחר
# --------------------------------------------------------------------------
def test_rank_one_is_never_given_up_for_gaps_or_a_late_finish():
    """‏X מאוחר ומשאיר חור של שש שעות; Y צמוד ומוקדם. אותו יום — אז X."""
    courses = [
        course("90001",
               grp("90001", "1", KIND_LECTURE, X, (1, H1630, H1830)),
               grp("90001", "2", KIND_LECTURE, Y, (1, H1030, H1230))),
        course("90002", grp("90002", "1", KIND_LECTURE, P, (1, H0830, H1030))),
    ]
    ranked = {"90001": {KIND_LECTURE: [X]}}
    found = solve(courses, Preferences(target_days=6, preferred_lecturers=ranked), top_n=2)
    assert lecturer_of(found[0], "90001", KIND_LECTURE) == X
    # והיא אכן ויתרה על נקודות: למערכת של Y ניקוד טוב יותר.
    assert found[1].score > found[0].score
    assert found[0].gap_minutes > found[1].gap_minutes


# --------------------------------------------------------------------------
# 2. ...אבל יום שלם קודם לו
# --------------------------------------------------------------------------
def _day_courses():
    return [
        course("90001",
               grp("90001", "1", KIND_LECTURE, X, (2, H0830, H1030)),
               grp("90001", "2", KIND_LECTURE, Z, (1, H1430, H1630)),
               grp("90001", "3", KIND_LECTURE, Y, (1, H1030, H1230))),
        course("90002", grp("90002", "1", KIND_LECTURE, P, (1, H0830, H1030))),
    ]


def test_rank_one_is_given_up_for_a_day():
    """‏X פותח יום שני; יעד של יום אחד — ולכן לא X."""
    ranked = {"90001": {KIND_LECTURE: [X]}}
    one_day = best(_day_courses(), target_days=1, preferred_lecturers=ranked)
    assert lecturer_of(one_day, "90001", KIND_LECTURE) != X
    assert one_day.days_over_target == 0
    # כשהיום השני בתוך היעד, X נבחר.
    two_days = best(_day_courses(), target_days=2, preferred_lecturers=ranked)
    assert lecturer_of(two_days, "90001", KIND_LECTURE) == X


def test_when_rank_one_costs_a_day_rank_two_is_next():
    """‏X עולה יום, Z (דירוג 2) לא — אז Z, ולא Y שאינו ברשימה."""
    ranked = {"90001": {KIND_LECTURE: [X, Z]}}
    found = best(_day_courses(), target_days=1, preferred_lecturers=ranked)
    assert lecturer_of(found, "90001", KIND_LECTURE) == Z
    assert [r["rank"] for r in found.lecturer_ranks] == [2]


def test_an_unreachable_target_still_honours_ranks_within_the_fewest_days():
    """יעד 1 כששני ימים הם המינימום: הדירוג מכובד בתוך המערכות בנות יומיים."""
    courses = [
        course("90001",
               grp("90001", "1", KIND_LECTURE, X, (2, H1430, H1630)),
               grp("90001", "2", KIND_LECTURE, Y, (2, H0830, H1030))),
        course("90002", grp("90002", "1", KIND_LECTURE, P, (1, H0830, H1030))),
    ]
    found = best(courses, target_days=1, preferred_lecturers={"90001": {KIND_LECTURE: [X]}})
    assert found.days_over_target == 1
    assert lecturer_of(found, "90001", KIND_LECTURE) == X


# --------------------------------------------------------------------------
# 3. כמה רכיבים מדורגים: יותר בדירוג 1, ובשוויון — הרצאות
# --------------------------------------------------------------------------
def test_on_a_tie_in_rank_one_count_the_lecture_wins():
    """ההרצאה המועדפת והתרגול המועדף חופפים; אחד מהם בלבד — ההרצאה."""
    courses = [
        course("90001",
               grp("90001", "1", KIND_LECTURE, X, (1, H1030, H1230)),
               grp("90001", "2", KIND_LECTURE, Y, (3, H1030, H1230))),
        course("90003",
               grp("90003", "1", KIND_TUTORIAL, T, (1, H1030, H1230)),
               grp("90003", "2", KIND_TUTORIAL, U, (4, H1030, H1230))),
    ]
    ranked = {"90001": {KIND_LECTURE: [X]}, "90003": {KIND_TUTORIAL: [T]}}
    found = best(courses, target_days=6, preferred_lecturers=ranked)
    assert lecturer_of(found, "90001", KIND_LECTURE) == X
    assert lecturer_of(found, "90003", KIND_TUTORIAL) == U
    assert (found.lecturer_hits, found.lecturer_total) == (1, 2)


def test_more_rank_ones_beat_a_lecture():
    """שני תרגולים בדירוג 1 גוברים על הרצאה אחת בדירוג 1."""
    courses = [
        course("90001",
               grp("90001", "1", KIND_LECTURE, X, (1, H1030, H1430)),
               grp("90001", "2", KIND_LECTURE, Y, (3, H1030, H1230))),
        course("90003",
               grp("90003", "1", KIND_TUTORIAL, T, (1, H1030, H1230)),
               grp("90003", "2", KIND_TUTORIAL, U, (4, H1030, H1230))),
        course("90004",
               grp("90004", "1", KIND_TUTORIAL, T, (1, H1230, H1430)),
               grp("90004", "2", KIND_TUTORIAL, U, (5, H1030, H1230))),
    ]
    # ‏X (א׳ 10:30–14:30) חופף לשני ה-T — או X לבדו, או שני ה-T.
    ranked = {
        "90001": {KIND_LECTURE: [X]},
        "90003": {KIND_TUTORIAL: [T]},
        "90004": {KIND_TUTORIAL: [T]},
    }
    found = best(courses, target_days=6, preferred_lecturers=ranked)
    assert lecturer_of(found, "90003", KIND_TUTORIAL) == T
    assert lecturer_of(found, "90004", KIND_TUTORIAL) == T
    assert lecturer_of(found, "90001", KIND_LECTURE) == Y
    assert found.lecturer_hits == 2


# --------------------------------------------------------------------------
# 4. חפיפות: אחרי המרצים, לפני הניקוד
# --------------------------------------------------------------------------
def _overlap_courses():
    # ‏90007 מחייב נוכחות ביום א׳, כך שיום א׳ הוא יום קמפוס גם בלי P — שהרי
    # יום שכולו שיעורים בלי חובת נוכחות אינו נספר ביעד.
    return [
        course("90007", grp("90007", "1", KIND_LECTURE, Z, (1, H0830, H1030))),
        course("90001",
               grp("90001", "1", KIND_LECTURE, X, (1, H1030, H1230)),
               grp("90001", "2", KIND_LECTURE, Y, (3, H1030, H1230))),
        course("90002", grp("90002", "1", KIND_LECTURE, P, (1, H1030, H1230))),
    ]


def _overlap_prefs(**extra):
    return dict(
        allow_soft_conflicts=True,
        attendance={"90002": {KIND_LECTURE: False}},
        **extra,
    )


def test_an_overlap_may_be_used_to_honour_a_ranked_lecturer():
    found = best(
        _overlap_courses(),
        **_overlap_prefs(target_days=6, preferred_lecturers={"90001": {KIND_LECTURE: [X]}}),
    )
    assert lecturer_of(found, "90001", KIND_LECTURE) == X
    assert found.soft_conflicts == 1


def test_without_a_reason_no_overlap_is_taken():
    found = best(_overlap_courses(), **_overlap_prefs(target_days=6))
    assert lecturer_of(found, "90001", KIND_LECTURE) == Y
    assert found.soft_conflicts == 0


def test_an_overlap_may_save_a_day():
    prefs = _overlap_prefs(target_days=1)
    found = best(_overlap_courses(), **prefs)
    assert lecturer_of(found, "90001", KIND_LECTURE) == X
    assert found.days_over_target == 0
    # והחפיפה מסומנת ומדווחת — לא בשקט (SPEC_V2 §2).
    assert found.soft_conflicts == 1
    assert found.selection.overlapping_pairs()
    assert describe_soft_conflicts(found.selection, Preferences(**prefs))


def test_an_overlap_does_not_beat_a_ranked_lecturer():
    """דירוג 1 בלי חפיפה קודם לחפיפה — הרמות אינן נסחרות."""
    found = best(
        _overlap_courses(),
        **_overlap_prefs(target_days=6, preferred_lecturers={"90001": {KIND_LECTURE: [Y]}}),
    )
    assert lecturer_of(found, "90001", KIND_LECTURE) == Y
    assert found.soft_conflicts == 0


# --------------------------------------------------------------------------
# 5. לכל סוג בנפרד; רשימה שטוחה חלה רק על הסוגים שמרציה מלמדים
# --------------------------------------------------------------------------
def _two_kind_course():
    return course(
        "90005",
        grp("90005", "1", KIND_LECTURE, X, (1, H0830, H1030)),
        grp("90005", "2", KIND_LECTURE, Y, (2, H0830, H1030)),
        grp("90005", "1/1", KIND_TUTORIAL, X, (1, H1030, H1230)),
        grp("90005", "1/2", KIND_TUTORIAL, T, (2, H1030, H1230)),
    )


def test_counting_is_per_ranked_kind():
    c = [_two_kind_course()]
    by_kind = best(c, target_days=6, preferred_lecturers={"90005": {KIND_LECTURE: [X]}})
    assert (by_kind.lecturer_hits, by_kind.lecturer_total) == (1, 1)
    both = best(
        c, target_days=6,
        preferred_lecturers={"90005": {KIND_LECTURE: [Y], KIND_TUTORIAL: [X]}},
    )
    assert (both.lecturer_hits, both.lecturer_total) == (2, 2)
    assert lecturer_of(both, "90005", KIND_LECTURE) == Y
    assert lecturer_of(both, "90005", KIND_TUTORIAL) == X


def test_a_flat_list_applies_only_to_the_kinds_its_lecturers_teach():
    c = [_two_kind_course()]
    assert rankings_by_kind(c, {"90005": [X]}) == {
        "90005": {KIND_LECTURE: [X], KIND_TUTORIAL: [X]}
    }
    assert rankings_by_kind(c, {"90005": [T, Y]}) == {
        "90005": {KIND_LECTURE: [Y], KIND_TUTORIAL: [T]}
    }
    assert rankings_by_kind(c, {"90005": ["מרצה שאינו מלמד"]}) == {}
    # מילון לפי סוג נשאר כפי שהוא, גם עם שם שאינו מלמד — הוא ייאמר "חסר".
    assert rankings_by_kind(c, {"90005": {KIND_TUTORIAL: ["  מרצה שאינו מלמד "]}}) == {
        "90005": {KIND_TUTORIAL: ["מרצה שאינו מלמד"]}
    }
    found = best(c, target_days=6, preferred_lecturers={"90005": [X]})
    assert (found.lecturer_hits, found.lecturer_total) == (2, 2)


def test_the_days_level_comes_before_the_lecturer_level_in_the_key():
    from scheduler import _sort_key

    found = solve(_day_courses(), Preferences(
        target_days=1, preferred_lecturers={"90001": {KIND_LECTURE: [X]}}), top_n=3)
    keys = [_sort_key(s) for s in found]
    assert keys == sorted(keys)
    assert [s.days_over_target for s in found] == sorted(s.days_over_target for s in found)


# --------------------------------------------------------------------------
# 6. ה-API: שתי הצורות, השדות החדשים, ובלי נעיצות
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    from src.web.api import create_app

    return create_app({"allow_network": False}).test_client()


CODES = ["11069", "61756", "61757", "62027", "61759", "61832"]


def _solve(client, **body):
    res = client.post("/api/solve", json={"codes": CODES, "semester": "א", **body})
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json()


def test_the_api_returns_the_priority_fields(client):
    data = _solve(client, target_days=4)
    for sch in data["schedules"]:
        assert isinstance(sch["days_over_target"], int)
        assert sch["lecturer_ranks"] == [] and sch["lecturer_misses"] == []
        assert "lecturer" not in sch["breakdown"] and "days" not in sch["breakdown"]


def test_the_api_accepts_a_ranking_per_kind_and_a_flat_one(client):
    from src.web import api

    first = _solve(client)["schedules"][0]
    name = next(p["lecturer"] for p in first["picks"]
                if p["code"] == "61759" and p["kind"] == KIND_LECTURE)

    per_kind = _solve(client, ranked={"61759": {KIND_LECTURE: [name]}})["schedules"][0]
    assert (per_kind["lecturer_hits"], per_kind["lecturer_total"]) == (1, 1)
    assert per_kind["lecturer_ranks"][0]["kind"] == KIND_LECTURE

    with create_app_context():
        built, _, _ = api._build_courses(["61759"], semester="א")
    teaches = {g.kind for g in built[0].groups if g.lecturer == name}
    flat = _solve(client, ranked={"61759": [name]})["schedules"][0]
    assert flat["lecturer_total"] == len(teaches)
    assert {r["kind"] for r in flat["lecturer_ranks"]} == teaches


def create_app_context():
    from src.web.api import create_app

    return create_app({"allow_network": False}).app_context()


def test_the_api_names_a_missing_rank_one_with_its_kind(client):
    sch = _solve(client, ranked={"61759": {KIND_LECTURE: ["מרצה שאינו בקטלוג"]}})["schedules"][0]
    assert sch["lecturer_misses"] == [
        {"code": "61759", "kind": KIND_LECTURE, "name": "מרצה שאינו בקטלוג"}
    ]
    assert (sch["lecturer_hits"], sch["lecturer_total"]) == (0, 1)


def test_the_api_ignores_pinned(client):
    """‏``pinned`` מבקשה ישנה אינו נקרא: אין סינון, אין "שוחררה", ואין שדות נעיצה."""
    loose = _solve(client)
    pinned = _solve(client, pinned={"61759": {KIND_LECTURE: "no-such-group"}})
    assert pinned["feasible_count"] == loose["feasible_count"] > 0
    assert "pinned" not in pinned and "dropped_pins" not in pinned
    assert [s["picks"] for s in pinned["schedules"]] == [s["picks"] for s in loose["schedules"]]


def test_a_malformed_per_kind_ranking_is_a_clean_400(client):
    res = client.post(
        "/api/solve",
        json={"codes": CODES, "semester": "א", "ranked": {"61759": {KIND_LECTURE: 5}}},
    )
    assert res.status_code == 400
    body = res.get_json()
    assert body["ok"] is False and body.get("error")
