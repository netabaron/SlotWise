"""קבוצה בלי מועד קבוע אינה נבחרת כשלרכיב שלה יש קבוצה עם מועד (2026-10-03).

DEFERRED.md, "Groups with no meeting time" (הוחלט 2026-10-03):

* קבוצה בלי מפגשים לעולם אינה נבחרת כשלקבוצה אחרת מאותו קורס ומאותו סוג יש
  מפגשים. בלי הכלל היא "עולה" אפס בניקוד — אין לה יום, חלון או שעת סיום —
  ולכן ניצחה תמיד (‏11232 מעבדה ‏/8, "מיועד לחוזרים").
* כשלאף קבוצה ברכיב אין מפגשים, הקבוצות נשארות והקורס נשאר.

הכלל יושב ב-``scheduler._filter_groups``, ולכן החיפוש, ה-viability והאבחון
רואים אותו יחד. הקבוצה נשארת ב-course.groups, ו-linked_to נשאר נאכף.
**שום דבר כאן אינו תלוי ב-data/db המקומי**: נתונים סינתטיים, הקטלוג הקפוא
(‏catalog_source), ושרת ‏Flask שמצביע על מסד ריק.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

import scheduler as S  # noqa: E402
from models import Course, Group, Meeting  # noqa: E402

L, T, M, P = "הרצאה", "תרגול", "מעבדה", "פרויקט"


def g(code, gid, kind, slots=(), links=()):
    return Group(course_code=code, group_id=gid, kind=kind, lecturer="",
                 meetings=[Meeting(day=d, start=s, end=e) for d, s, e in slots],
                 linked_to=list(links))


def course(code, groups):
    return Course(code=code, name="קורס בדיקה", credits=1.0, groups=groups, tied_with=[])


def chosen(courses, prefs=None):
    return [{(grp.course_code, grp.kind): grp.group_id for grp in sel.groups}
            for sel in S.enumerate_selections(courses, prefs or S.Preferences())]


# ---- הבאג: קבוצה בלי מועד מנצחת ------------------------------------------
def _lab_course():
    """הרצאה ביום א'; מעבדה ‏/1 ביום ה' בערב; מעבדה ‏/8 בלי מועד."""
    return course("90101", [
        g("90101", "/1", L, [(1, 510, 600)]),
        g("90101", "/1", M, [(5, 1070, 1190)]),
        g("90101", "/8", M),
    ])


def test_a_no_time_group_no_longer_wins_the_top_schedule():
    best = S.solve([_lab_course()], S.Preferences(target_days=1), top_n=1)[0]
    lab = best.selection.group_for("90101", M)
    # לפני התיקון: ‏/8, כי הוא אינו מוסיף יום, ערב או חלון.
    assert lab.group_id == "/1", lab.group_id


def test_a_no_time_group_is_never_chosen_when_its_component_has_a_timed_group():
    labs = {sel[("90101", M)] for sel in chosen([_lab_course()])}
    assert labs == {"/1"}, labs


def test_a_component_with_no_timed_group_keeps_its_groups_and_the_course_stays():
    c = course("90102", [
        g("90102", "/1", L, [(1, 510, 600)]),
        g("90102", "a", P),
        g("90102", "b", P),
    ])
    projects = {sel[("90102", P)] for sel in chosen([c])}
    assert projects == {"a", "b"}, projects


def test_the_rule_is_per_component_not_per_course():
    """מעבדה בלי מועד נפסלת; פרויקט בלי מועד, ברכיב בלי אף קבוצה עם מועד, נשאר."""
    c = course("90103", [
        g("90103", "/1", L, [(1, 510, 600)]),
        g("90103", "/1", M, [(2, 510, 600)]),
        g("90103", "/8", M),
        g("90103", "p", P),
    ])
    sels = chosen([c])
    assert {s[("90103", M)] for s in sels} == {"/1"}
    assert {s[("90103", P)] for s in sels} == {"p"}


def test_links_are_still_enforced():
    """הרצאה ‏A מקושרת רק לתרגול ‏/9, שאין לו מועד ולכן נפסל; ‏B בלי קישור.

    הקבוצה הנפסלת נשארת ב-course.groups, ולכן ‏/9 עדיין מוכר כתרגול, ו-A
    עדיין מחויבת אליו — כלומר A אינה נבחרת. אילו הכלל היה *מוחק* את ‏/9, הקישור
    של A היה הופך למזהה לא מוכר, שאינו נאכף, ו-A הייתה יוצאת עם ‏/1."""
    c = course("90104", [
        g("90104", "A", L, [(1, 510, 600)], ["/9"]),
        g("90104", "B", L, [(1, 600, 690)]),
        g("90104", "/1", T, [(2, 510, 600)]),
        g("90104", "/9", T),
    ])
    pairs = {(s[("90104", L)], s[("90104", T)]) for s in chosen([c])}
    assert pairs == {("B", "/1")}, pairs


def test_the_diagnosis_can_name_the_rule_when_it_empties_a_component():
    """המעבדה עם המועד נחסמת באילוץ אישי; זו שבלי מועד — בכלל. אין מערכת,
    והאבחון אומר את שתי הסיבות (הכלל נקבע מהרכיב כפי שהוא בנתונים). האבחון
    מפרט לכל היותר שלוש קבוצות, ולכן ברכיב גדול הכלל עשוי לא להיאמר בשמו."""
    prefs = S.Preferences(latest=1000)
    with pytest.raises(S.Infeasible) as exc:
        S.solve([_lab_course()], prefs, top_n=1)
    text = " ".join(exc.value.reasons)
    assert S.NO_TIME_TEXT in text, text


# ---- הנתונים האמיתיים: 11232 מהקטלוג הקפוא --------------------------------
@pytest.fixture(scope="module")
def course_11232():
    from catalog_source import catalog_courses  # noqa: PLC0415

    c = catalog_courses().get("11232")
    if c is None:
        pytest.skip("11232 אינו בקטלוג הקפוא")
    c.groups = [grp for grp in c.groups if grp.semester in ("", "א")]
    c.tied_with = []
    lab8 = next(grp for grp in c.groups if grp.kind == M and grp.group_id == "271030210/8")
    assert not lab8.meetings and any(grp.meetings for grp in c.groups if grp.kind == M)
    return c


def test_11232_lab_8_with_no_time_is_never_chosen(course_11232):
    labs = {sel[("11232", M)] for sel in chosen([course_11232])}
    assert labs and "271030210/8" not in labs, sorted(labs)


def test_the_api_marks_the_no_time_lab_as_not_viable(tmp_path):
    from src.web.api import create_app  # noqa: PLC0415

    client = create_app(config={"allow_network": False, "db_root": str(tmp_path)}).test_client()
    data = client.post("/api/solve", json={"codes": ["11232"], "semester": "א"}).get_json()
    assert data["schedules"], data.get("reasons")
    labs = {p["group_id"] for s in data["schedules"] for p in s["picks"] if p["kind"] == M}
    assert "271030210/8" not in labs, labs
    via = data["viability"]["11232"][M]["271030210/8"]
    assert via is False or via.get("ok") is False, via
