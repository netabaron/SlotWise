"""מזהה קבוצה ששני סוגים חולקים — ‏linked_to מגיע לסוג הנכון (2026-10-03).

הבאג (DEFERRED.md, נסגר): ‏``scheduler._kind_index`` מיפה (קורס, מזהה) לסוג
אחד, והאחרון שנכתב ניצח — מעבדה דרסה תרגול, שדרס הרצאה. בידיעון אותו מזהה
נושא לא פעם כמה רכיבים בקורס אחד (‏11232: ‏/1–/3 הם גם תרגולים וגם מעבדות),
ולכן קישור של הרצאה לתרגולים שלה נקרא כקישור למעבדות:

* מעבדה פתוחה שאינה ברשימה (‏11232 ‏/4) לא נבחרה אף פעם;
* והתרגולים לא הוגבלו כלל — הרצאה יכלה לצאת עם תרגול שאינו שלה.

מה נבדק כאן: שהמעבדה נבחרת, שהרצאה עדיין מושכת רק את התרגולים שלה, ושני
כללי ההכרעה (רמז משאר הרשימה; הסוג הקרוב אחרי הבעלים) — על נתונים
סינתטיים, ועל 11232 מהקטלוג הקפוא (לא מ-data/db המקומי).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import scheduler as S  # noqa: E402
from models import Course, Group, Meeting  # noqa: E402

L, T, M = "הרצאה", "תרגול", "מעבדה"


def g(code, gid, kind, day, links=()):
    """קבוצה ביום של הסוג שלה: סוגים שונים לעולם אינם חופפים, וקבוצות מאותו
    סוג אינן נבחרות יחד — כך שרק linked_to מכריע."""
    return Group(course_code=code, group_id=gid, kind=kind, lecturer="",
                 meetings=[Meeting(day=day, start=480, end=540)],
                 linked_to=list(links))


def course(code, groups):
    return Course(code=code, name="קורס בדיקה", credits=1.0, groups=groups, tied_with=[])


def selections(c):
    return [{grp.kind: grp.group_id for grp in sel.groups}
            for sel in S.enumerate_selections([c], S.Preferences())]


def pairs(sels, a, b):
    out = {}
    for s in sels:
        out.setdefault(s[a], set()).add(s[b])
    return out


# ---- הבאג עצמו: מבנה של 11232, בלי זמנים שמפריעים -----------------------
def _like_11232():
    """הרצאות → ‏/1–/3 (תרגולים ומעבדות חולקים אותם); תרגולים → ‏/1–/4."""
    return course("90001", [
        g("90001", "/1", L, 1, ["/1", "/2", "/3"]),
        g("90001", "/2", L, 1, ["/1", "/2", "/3"]),
        *[g("90001", f"/{i}", T, 2, ["/1", "/2", "/3", "/4"]) for i in (1, 2, 3)],
        *[g("90001", f"/{i}", M, 3) for i in (1, 2, 3, 4)],
    ])


def test_a_lab_whose_id_the_lecture_does_not_list_can_be_chosen():
    labs = {s[M] for s in selections(_like_11232())}
    assert "/4" in labs, labs  # לפני התיקון: רק /1–/3


def test_the_kind_index_keeps_every_kind_that_shares_an_id():
    index = S._kind_index([_like_11232()])
    assert index[("90001", "/1")] == frozenset({L, T, M})
    assert index[("90001", "/4")] == frozenset({M})


# ---- האכיפה נשמרת: הרצאה מושכת רק את התרגולים שלה -----------------------
def test_a_lecture_still_pulls_only_its_own_tutorials():
    c = course("90002", [
        g("90002", "A", L, 1, ["/1", "/2"]),
        g("90002", "B", L, 1, ["/3"]),
        *[g("90002", f"/{i}", T, 2) for i in (1, 2, 3)],
        *[g("90002", f"/{i}", M, 3) for i in (1, 2, 3)],
    ])
    with_tutorial = pairs(selections(c), L, T)
    # לפני התיקון ‏/1,/2,/3 נקראו כמעבדות, ו-A יצאה גם עם תרגול ‏/3.
    assert with_tutorial == {"A": {"/1", "/2"}, "B": {"/3"}}, with_tutorial


def test_a_tutorial_still_pulls_only_its_own_labs():
    """‏/1 ו-/2 הם כאן הרצאה, תרגול ומעבדה בבת אחת.

    * תרגול ‏/2 → ‏/2: מלבד התרגול עצמו המזהה הוא הרצאה ומעבדה, ואין רמז —
      הסוג הקרוב אחרי תרגול: מעבדה.
    * תרגול ‏/1 → ‏/1,/4: ‏/4 הוא מעבדה בלבד, והרמז מכריע ש-/1 היא המעבדה.
    * ההרצאות → ‏/1,/2 הן התרגולים; לפני התיקון הן נקראו כמעבדות, ומעבדה ‏/4
      נחסמה גם לתרגול ‏/1.
    """
    c = course("90006", [
        g("90006", "/1", L, 1, ["/1", "/2"]),
        g("90006", "/2", L, 1, ["/1", "/2"]),
        g("90006", "/1", T, 2, ["/1", "/4"]),
        g("90006", "/2", T, 2, ["/2"]),
        *[g("90006", f"/{i}", M, 3) for i in (1, 2, 4)],
    ])
    assert pairs(selections(c), T, M) == {"/1": {"/1", "/4"}, "/2": {"/2"}}


# ---- כללי ההכרעה --------------------------------------------------------
def test_an_ambiguous_id_takes_the_kind_the_rest_of_the_list_names():
    """‏11026: הרצאה → ‏/1 (תרגול+מעבדה), ‏/4 (מעבדה בלבד) — ‏/1 היא המעבדה."""
    c = course("90003", [
        g("90003", "X", L, 1, ["/1", "/4"]),
        *[g("90003", f"/{i}", T, 2) for i in (1, 2)],
        *[g("90003", f"/{i}", M, 3) for i in (1, 2, 4)],
    ])
    sels = selections(c)
    assert {s[M] for s in sels} == {"/1", "/4"}
    assert {s[T] for s in sels} == {"/1", "/2"}  # התרגולים אינם מוגבלים


def test_a_self_link_still_means_the_other_kind_with_my_id():
    """הרצאה ‏/1 → ‏/1, כש-/1 הוא גם מעבדה: המעבדה ‏/1 (DEVELOPMENT_LOG.md)."""
    c = course("90004", [
        g("90004", "/1", L, 1, ["/1"]),
        *[g("90004", f"/{i}", M, 3) for i in (1, 2)],
    ])
    assert {s[M] for s in selections(c)} == {"/1"}


def test_with_no_kind_after_the_owner_an_id_takes_the_nearest_before():
    """מעבדה ‏/1 → ‏/1, כש-/1 הוא גם הרצאה וגם תרגול: אין סוג אחרי מעבדה,
    ולכן הקרוב לפניה — התרגול. (הקוד הישן קרא את ‏/1 כמעבדה, כלומר כסוג של
    הבעלים עצמם, ולא אכף דבר.)"""
    c = course("90007", [
        g("90007", "/1", L, 1),
        *[g("90007", f"/{i}", T, 2) for i in (1, 2)],
        g("90007", "/1", M, 3, ["/1"]),
    ])
    assert pairs(selections(c), M, T) == {"/1": {"/1"}}


def test_unshared_ids_behave_exactly_as_before():
    c = course("90005", [
        g("90005", "10", L, 1, ["21"]),
        g("90005", "11", L, 1, ["22"]),
        *[g("90005", t, T, 2) for t in ("21", "22")],
    ])
    assert pairs(selections(c), L, T) == {"10": {"21"}, "11": {"22"}}


# ---- הנתונים האמיתיים: 11232 מהקטלוג הקפוא --------------------------------
@pytest.fixture(scope="module")
def course_11232():
    return _fixture_course("11232")


def test_11232_open_lab_4_can_be_chosen(course_11232):
    labs = {s[M] for s in selections(course_11232)}
    assert "271030210/4" in labs, sorted(labs)


def _fixture_course(code):
    from catalog_source import catalog_courses  # noqa: PLC0415

    c = catalog_courses().get(code)
    if c is None:
        pytest.skip(f"{code} אינו בקטלוג הקפוא")
    c.groups = [grp for grp in c.groups if grp.semester in ("", "א")]
    c.tied_with = []
    return c


def test_31476_each_lecture_still_takes_only_its_own_tutorial():
    """‏31476: כל הרצאה מקושרת למזהה שלה בלבד, והמזהה הוא גם תרגול וגם מעבדה.
    המזהה נקרא כתרגול — וכל הרצאה יוצאת רק עם התרגול שלה."""
    c = _fixture_course("31476")
    with_tutorial = pairs(selections(c), L, T)
    assert with_tutorial == {"271030420/1": {"271030420/1"}, "271030420/2": {"271030420/2"}}, with_tutorial
