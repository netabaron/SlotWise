# -*- coding: utf-8 -*-
"""
בדיקות "חובת נוכחות" וחפיפות מכוונות — tests for SPEC_V2 §2.

הרעיון של הסטודנטית, ובצדק: **בהרצאות רבות אין חובת נוכחות**, במיוחד כשחוזרים
על קורס. לכן מותר להירשם ביודעין לשתי קבוצות שחופפות בזמן וללכת רק לאחת —
אם זה מה שסוגר את השבוע יום אחד מוקדם יותר. חפיפה מפסיקה להיות וטו מוחלט
והופכת ל"קשיחה" (עדיין נפסלת) או "רכה" (מותרת, נספרת ומנוקדת בקנס).

כל הבדיקות כאן רצות מול **המאגר האמיתי** ב-``data/db`` — ששת הקורסים של
סמסטר א' תשפ"ז, 27 קבוצות. זה גם מה שהופך את הקובץ הזה לרשת הביטחון של
השינוי כולו: ההעדפות של ברירת המחדל *חייבות* להחזיר בדיוק את המספרים של היום
(16 צירופים, מינימום 5 ימים). אם המספר הזה זז — השינוי שבר משהו.

איך מריצים:
    python -m pytest tests -q

מוסכמות (מ-src/models.py):
    יום   : 1=ראשון ... 6=שישי
    שעה   : דקות מחצות. 08:30 -> 510
    חפיפה : חצי-פתוחה [start, end) — 08:30-10:15 ו-10:15-12:00 *אינם* מתנגשים.

Technical note: ``data/db`` is git-ignored (it is scraped data, not source), so
the whole module skips cleanly when it is absent instead of failing a fresh
clone. On the student's machine it is there and every test runs for real.
No network, no browser, no Playwright — this file only reads local JSON.
"""

from __future__ import annotations

import copy
import inspect
import itertools
import sys
from pathlib import Path

import pytest

# --------------------------------------------------------------------------
# הכנת הסביבה: להוסיף את src/ ל-sys.path בדיוק כמו ש-main.py עושה.
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass  # זרם שלא ניתן לשינוי (pytest capture / pipe) — ממשיכים בלי

import scheduler as scheduler_mod  # noqa: E402  (import after the sys.path surgery)
from models import (  # noqa: E402
    KIND_COMBINED,
    KIND_LECTURE,
    KIND_TUTORIAL,
    Course,
    Group,
    Meeting,
    Selection,
)
from scheduler import (  # noqa: E402
    DEFAULT_WEIGHTS,
    Preferences,
    enumerate_selections,
    score,
    solve,
)
from store import Store  # noqa: E402

# --------------------------------------------------------------------------
# המאגר האמיתי. אם אינו קיים — מדלגים על הקובץ כולו, לא מפילים אותו.
# --------------------------------------------------------------------------
#: ‏המקור הוא הקטלוג שנשלח עם הקוד, לא ``data/db``. ראו tests/catalog_source.py:
#: המאגר המקומי אינו במאגר הקוד והאפליקציה הרצה כותבת אותו מחדש, ולכן כל
#: מספר שמקובע מולו זז מתחת לבדיקה. מול הקטלוג המספרים יוצאים בדיוק כפי
#: שנכתבו — 27 קבוצות — והם גם יציבים.
#: ‏הקטלוג **הקפוא**, לא ``data/catalog/``. ראו tests/conftest.py: הקטלוג
#: שנשלח הוא הפלט של הצינור הלילי, והבדיקות כאן מקבעות ערכים שנגזרים ממנו
#: (ספירת קבוצות לכל קורס). קריאה ממנו הייתה הופכת כל עדכון נתונים לכישלון
#: בדיקה. הקובץ הקפוא משתנה רק דרך scripts/update_test_fixture.py.
CATALOG = ROOT / "tests" / "fixtures" / "catalog" / "catalog.jsonl"

pytestmark = pytest.mark.skipif(
    not CATALOG.is_file(),
    reason="אין tests/fixtures/catalog/catalog.jsonl — יש להריץ scripts/update_test_fixture.py",
)

# --------------------------------------------------------------------------
# קבועי זמן וקבוצות אמיתיות — כדי שהבדיקות ייקראו כמו לוח שעות.
# --------------------------------------------------------------------------
H0830, H1030, H1130 = 510, 630, 690
WED, THU = 4, 5  # 4 = רביעי, 5 = חמישי

#: זוג החפיפה שמופיע *מילה במילה* ב-SPEC_V2 §2 כדוגמה לדיווח:
#: 61753 הרצאה קב' 271060330 (יום ד 08:30-10:30) מול 61756 תרגול קב' 271060310/3.
CLASH_A = ("61753", KIND_LECTURE, "271060330")
CLASH_B = ("61756", KIND_TUTORIAL, "271060310/3")

#: הרצאת 61753 — הרכיב שהסטודנטית מסמנת כ"בלי חובת נוכחות".
OPTIONAL_LECTURE = {"61753": {KIND_LECTURE: False}}

#: ‏83 ו-564 היו כאן עד 2026-09-10, ופעמיים באותו יום הם נפלו על נתונים
#: שהשתנו כדין — פעם כשהמאגר המקומי זז מתחת לבדיקות, ופעם כשהידיעון הוסיף
#: קבוצה שלישית ל-11069 והקטלוג נבנה מחדש. מספר צירופים אינו מה שהקובץ
#: הזה שומר עליו; הוא שומר על **הכלל**. לכן במקום מספר, כל אחת מהבדיקות
#: שקיבעה מספר משווה עכשיו את המנוע לספירה ממצה של אותו כלל — ראו
#: ``legal_combinations`` — ומספר הצירופים נגזר מהנתונים שיש.
TODAY_MIN_DAYS = 4
TODAY_COURSES = 6

#: הקורסים של הסטודנט/ית בסמסטר 5. הבדיקות כאן עוסקות *בהם*, לא בכל מה
#: שמקרה במאגר: מאז שהרענון היומי מושך את כל הקורסים שנפתחים, המאגר גדל
#: כל הזמן, וקיבוע "במאגר יש בדיוק 6 קורסים" היה הופך כל רענון לבדיקה אדומה.
STUDENT_CODES = ["11069", "61753", "61756", "61757", "61832", "62027"]

#: אחרי שמסמנים את הרצאת 61753 כלא-חובה ומאפשרים חפיפות רכות.
SOFT_MIN_DAYS = 4


def selection_key(sel) -> tuple[str, ...]:
    """זהות של מערכת: אילו קבוצות בדיוק נבחרו. סדר אינו חלק ממנה."""
    return tuple(sorted(f"{g.course_code}~{g.kind}~{g.group_id}" for g in sel.groups))


def all_combinations(courses):
    """כל צירוף של קבוצה אחת לכל (קורס, סוג רכיב) — **בלי** המנוע.

    מכפלה קרטזית פשוטה, 2400 צירופים על ששת הקורסים האלה. זו הספירה
    הבלתי-תלויה שהמספרים המקובעים היו קיצור-דרך אליה.
    """
    buckets = [
        [g for g in course.groups if g.kind == kind]
        for course in courses
        for kind in course.kinds()
    ]
    for combo in itertools.product(*buckets):
        yield Selection(groups=list(combo))


def legal_combinations(courses, prefs) -> set[tuple[str, ...]]:
    """הצירופים שהכלל מתיר, נספרים ממצה ובלי ``enumerate_selections``.

    ‏``conflict_is_hard`` הוא הכלל עצמו, והוא נבדק בנפרד בסעיף 2. מה
    שנבדק כאן הוא שהמונה **מיישם** אותו: לא גוזם צירוף חוקי ולא מחזיר
    צירוף אסור. זו הטענה שהמספר 83 עמד בשבילה, והיא נכונה גם כשהידיעון
    מוסיף קבוצה.
    """
    out: set[tuple[str, ...]] = set()
    for sel in all_combinations(courses):
        if all(
            not (a.conflicts_with(b) and conflict_is_hard(a, b, prefs))
            for a, b in itertools.combinations(sel.groups, 2)
        ):
            out.add(selection_key(sel))
    return out


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def _db_courses() -> dict[str, Course]:
    """הקורסים כפי שהם בקטלוג. module-scope — קריאה אחת לכל הקובץ.

    ‏עובר דרך אותו ``Store`` שהאפליקציה משתמשת בו, כדי שרק המקור יתחלף
    ולא נתיב הקריאה.
    """
    from catalog_source import catalog_courses  # noqa: PLC0415

    return catalog_courses()


@pytest.fixture
def courses(_db_courses: dict[str, Course]) -> list[Course]:
    """עותק עמוק ומסודר של הקורסים. deepcopy כי ה-Store מחזיר אובייקטים חיים."""
    missing = [c for c in STUDENT_CODES if c not in _db_courses]
    if missing:
        pytest.skip(f"חסרים במאגר קורסים של הסטודנט/ית: {missing}")
    return [copy.deepcopy(_db_courses[code]) for code in STUDENT_CODES]


def find_group(courses: list[Course], code: str, kind: str, group_id: str) -> Group:
    """קבוצה אמיתית אחת מהמאגר, לפי (קורס, סוג, מספר קבוצה)."""
    for course in courses:
        if course.code != code:
            continue
        for group in course.groups:
            if group.kind == kind and group.group_id == group_id:
                return group
    raise AssertionError(f"קבוצה {code}/{kind}/{group_id} לא נמצאה במאגר")


# --------------------------------------------------------------------------
# עזרי-חוזה: השמות שה-SPEC מגדיר, עם סובלנות לקו תחתון מוביל בלבד.
# --------------------------------------------------------------------------
def _resolve(*names: str):
    for name in names:
        fn = getattr(scheduler_mod, name, None)
        if fn is not None:
            return fn
    return None


conflict_is_hard = _resolve("conflict_is_hard", "_conflict_is_hard")
attendance_required = _resolve("attendance_required", "_attendance_required")
describe_soft_conflicts = _resolve("describe_soft_conflicts", "_describe_soft_conflicts")


def describe(selection: Selection, prefs: Preferences) -> list[str]:
    """קוראת ל-describe_soft_conflicts ומחזירה רשימת שורות טקסט.

    החתימה המדויקת אינה נקבעת ב-SPEC, ולכן מתאימים את הקריאה למספר הפרמטרים
    שהפונקציה מכריזה עליהם. התוכן — זה כן נבדק, ובחומרה.
    """
    assert describe_soft_conflicts is not None, (
        "scheduler.describe_soft_conflicts חסרה — SPEC_V2 §2 דורש דיווח מפורש "
        "על כל חפיפה מכוונת"
    )
    try:
        params = [
            p
            for p in inspect.signature(describe_soft_conflicts).parameters.values()
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
    except (TypeError, ValueError):  # pragma: no cover - built-ins only
        params = [None, None]
    out = (
        describe_soft_conflicts(selection, prefs)
        if len(params) >= 2
        else describe_soft_conflicts(selection)
    )
    if out is None:
        return []
    if isinstance(out, str):
        return [out]
    return [str(line) for line in out]


def soft_prefs(**kwargs) -> Preferences:
    """העדפות עם חפיפות רכות מופעלות והרצאת 61753 מסומנת כלא-חובה."""
    base = {
        "attendance": copy.deepcopy(OPTIONAL_LECTURE),
        "allow_soft_conflicts": True,
    }
    base.update(kwargs)
    return Preferences(**base)


# ==========================================================================
# 0. המאגר עצמו — לוודא שהבדיקות מדברות על הנתונים שאנחנו חושבים
# ==========================================================================
def test_the_six_student_courses_are_present_and_well_formed(courses):
    """הקורסים של הסטודנט/ית — לא כל מה שיש במאגר (הוא גדל עם כל רענון).

    ‏עד 2026-09-10 השורה האחרונה כאן הייתה ``== 27`` קבוצות. הידיעון הוסיף
    קבוצה שלישית ל-11069 ב-08/09, והמספר נפל — על נתון שהשתנה כדין. מה
    שהבדיקה הזאת באמת עוגנת הוא שהקובץ מדבר על הקורסים שהוא חושב, ושכל
    קבוצה שהוא יקרא ניתנת לשימוש; שני אלה אינם תלויים בכמה קבוצות יש.
    """
    assert [c.code for c in courses] == STUDENT_CODES
    assert len(courses) == TODAY_COURSES
    for course in courses:
        assert course.groups, f"{course.code} בלי אף קבוצה — אין מה לשבץ"
        assert course.kinds(), f"{course.code} בלי אף סוג רכיב"
        for group in course.groups:
            assert group.group_id, f"{course.code}: קבוצה בלי מזהה"
            assert group.kind, f"{course.code}/{group.group_id}: קבוצה בלי סוג"
            assert group.course_code == course.code


def test_the_spec_example_pair_really_overlaps_on_wednesday(courses):
    """הזוג שה-SPEC מביא כדוגמה קיים במאגר וחופף באמת: יום ד 08:30-10:30."""
    lecture = find_group(courses, *CLASH_A)
    tutorial = find_group(courses, *CLASH_B)

    assert lecture.conflicts_with(tutorial)
    assert (WED, H0830, H1030) in [(m.day, m.start, m.end) for m in lecture.meetings]
    assert (WED, H0830, H1130) in [(m.day, m.start, m.end) for m in tutorial.meetings]


def test_11069_carries_the_yedion_attendance_note(courses):
    """הידיעון עצמו מצהיר על חובת נוכחות ב-11069 — הזרע לברירת המחדל."""
    course = next(c for c in courses if c.code == "11069")
    assert course.groups, "11069 חייב להיות במאגר"
    for group in course.groups:
        assert group.kind == KIND_COMBINED
        assert "חובת" in group.note and "נוכחות" in group.note


# ==========================================================================
# 1. רגרסיה: ברירת המחדל חייבת להישאר בדיוק מה שהיא היום
# ==========================================================================
def test_default_preferences_have_no_attendance_overrides():
    prefs = Preferences()
    assert prefs.attendance == {}
    # allow_soft_conflicts הוא True כברירת מחדל, ובכל זאת ההתנהגות לא משתנה:
    # attendance ריק = "בכל הקורסים יש חובת נוכחות", ולכן כל חפיפה נשארת קשה.
    # סימון הנוכחות הוא הפקד היחיד שקובע — ראו הבדיקות שמיד אחרי.
    assert prefs.allow_soft_conflicts is True


def test_default_preferences_reproduce_the_strict_enumeration(courses):
    """**שומר הרגרסיה של כל השינוי:** ברירת המחדל היא בדיוק כל הצירופים
    שאין בהם חפיפה, לא אחד יותר ולא אחד פחות.

    ‏עד 2026-09-10 זה נכתב ``== 83``. המספר עצמו אף פעם לא היה הנקודה —
    הוא היה קיצור דרך לספירה הממצה, והוא נשבר כשהיא זזה כדין. עכשיו
    הספירה עצמה כתובה, והבדיקה שורדת כל שינוי לגיטימי בנתונים.
    """
    engine = {selection_key(s) for s in enumerate_selections(courses, Preferences())}
    assert engine, "המונה החזיר ריק — אין מה להשוות"
    assert engine == legal_combinations(courses, Preferences())


def test_default_preferences_reproduce_min_days_of_five(courses):
    selections = list(enumerate_selections(courses, Preferences()))
    assert min(len(sel.days_used()) for sel in selections) == TODAY_MIN_DAYS


def test_every_default_selection_is_strictly_conflict_free(courses):
    for sel in enumerate_selections(courses, Preferences()):
        assert sel.is_feasible()
        assert sel.overlapping_pairs() == []


def test_default_scoring_reports_no_soft_conflicts(courses):
    for sel in enumerate_selections(courses, Preferences()):
        scored = score(sel, Preferences())
        assert scored.soft_conflicts == 0
        assert scored.soft_conflict_minutes == 0


def test_solve_still_works_with_the_default_preferences(courses):
    best = solve(courses, Preferences(), top_n=3)
    assert len(best) == 3
    assert all(s.selection.is_feasible() for s in best)
    assert all(s.soft_conflicts == 0 for s in best)


def test_allowing_soft_conflicts_alone_changes_nothing(courses):
    """הדגל לבדו אינו מתיר כלום — צריך גם רכיב שסומן כלא-חובה.

    ‏"לא משנה כלום" הוא יחס בין שתי הרצות, ולא מספר. עד 2026-09-10 הוא
    נבדק כ-``== 83`` בשני הצדדים בנפרד, ולכן נשבר כשהמספר זז.
    """
    prefs = Preferences(allow_soft_conflicts=True)
    with_flag = {selection_key(s) for s in enumerate_selections(courses, prefs)}
    without = {selection_key(s) for s in enumerate_selections(courses, Preferences())}
    assert with_flag == without


def test_marking_attendance_is_enough_on_its_own(courses):
    """סימון הנוכחות לבדו מספיק — אין עוד מתג נפרד שצריך להדליק.

    זו בדיוק התקלה שהסטודנט/ית דיווח/ה עליה: סומן "אין חובת נוכחות בהרצאה
    של 61753", והמערכת המשיכה לחסום את תרגול 61756 של יום חמישי, כי מתג
    נפרד וכבוי ביטל את הסימון בשקט. שני פקדים לאותה החלטה; נשאר אחד.
    """
    prefs = Preferences(attendance=copy.deepcopy(OPTIONAL_LECTURE))
    selections = list(enumerate_selections(courses, prefs))
    keys = {selection_key(s) for s in selections}
    strict = {selection_key(s) for s in enumerate_selections(courses, Preferences())}
    # ‏עד 2026-09-10: ``== 564``. מה שהתקלה דיווחה עליו אינו מספר אלא
    # שהסימון לבדו כן פותח מערכות — ושהזוג מה-SPEC הוא אחת מהן.
    assert strict < keys, "הסימון לבדו חייב לפתוח מערכות, ולא לגרוע"
    assert keys == legal_combinations(courses, prefs)
    lecture = find_group(courses, *CLASH_A)
    tutorial = find_group(courses, *CLASH_B)
    together = [
        s for s in selections
        if lecture in s.groups and tutorial in s.groups
    ]
    assert together, (
        "הזוג שהתקלה דיווחה עליו עדיין חסום — זה בדיוק מה שהסימון אמור לפתוח"
    )
    assert min(len(sel.days_used()) for sel in selections) == SOFT_MIN_DAYS


# ==========================================================================
# 2. conflict_is_hard — הכלל עצמו
# ==========================================================================
def test_conflict_is_hard_exists():
    assert conflict_is_hard is not None, "SPEC_V2 §2 מגדיר scheduler.conflict_is_hard"


def test_both_sides_mandatory_makes_the_clash_hard(courses):
    a = find_group(courses, *CLASH_A)
    b = find_group(courses, *CLASH_B)
    prefs = Preferences(allow_soft_conflicts=True)  # דגל דלוק, אבל שניהם חובה
    assert conflict_is_hard(a, b, prefs) is True


def test_one_optional_side_with_the_flag_makes_the_clash_soft(courses):
    a = find_group(courses, *CLASH_A)
    b = find_group(courses, *CLASH_B)
    assert conflict_is_hard(a, b, soft_prefs()) is False


def test_the_same_pair_turns_soft_once_attendance_is_waived(courses):
    """אותו זוג עצמו: מספיק לוותר על חובת הנוכחות באחד הצדדים."""
    a = find_group(courses, *CLASH_A)
    b = find_group(courses, *CLASH_B)
    prefs = Preferences(attendance=copy.deepcopy(OPTIONAL_LECTURE))
    assert conflict_is_hard(a, b, prefs) is False


def test_explicitly_disabling_soft_conflicts_still_forces_hard(courses):
    """הדגל נשאר בקוד ככיבוי מפורש, גם אם אינו מוצג בממשק."""
    a = find_group(courses, *CLASH_A)
    b = find_group(courses, *CLASH_B)
    prefs = Preferences(
        attendance=copy.deepcopy(OPTIONAL_LECTURE), allow_soft_conflicts=False
    )
    assert conflict_is_hard(a, b, prefs) is True


def test_conflict_is_hard_is_symmetric(courses):
    a = find_group(courses, *CLASH_A)
    b = find_group(courses, *CLASH_B)
    for prefs in (Preferences(), Preferences(allow_soft_conflicts=True), soft_prefs()):
        assert conflict_is_hard(a, b, prefs) == conflict_is_hard(b, a, prefs)


def test_groups_that_do_not_overlap_are_never_a_conflict(courses):
    """בלי חפיפה בזמן אין מה לדבר עליו — גם כששני הצדדים סומנו כלא-חובה."""
    a = find_group(courses, "61753", KIND_LECTURE, "271060330")  # ד+ה 08:30-10:30
    b = find_group(courses, "61757", KIND_LECTURE, "271060310")  # ג 08:30-09:30
    assert not a.conflicts_with(b)
    prefs = Preferences(
        attendance={"61753": {KIND_LECTURE: False}, "61757": {KIND_LECTURE: False}},
        allow_soft_conflicts=True,
    )
    assert conflict_is_hard(a, b, prefs) is False
    assert conflict_is_hard(a, b, Preferences()) is False


def test_both_sides_optional_is_still_only_soft(courses):
    a = find_group(courses, *CLASH_A)
    b = find_group(courses, *CLASH_B)
    prefs = Preferences(
        attendance={"61753": {KIND_LECTURE: False}, "61756": {KIND_TUTORIAL: False}},
        allow_soft_conflicts=True,
    )
    assert conflict_is_hard(a, b, prefs) is False


# ==========================================================================
# 3. "חסר מהמילון = חובה" — אף פעם לא מוותרים על נוכחות בטעות
# ==========================================================================
def test_missing_course_in_the_dict_means_required(courses):
    a = find_group(courses, *CLASH_A)  # 61753 — לא מוזכר במילון
    b = find_group(courses, *CLASH_B)
    prefs = Preferences(
        attendance={"61756": {KIND_TUTORIAL: False}},  # רק הצד השני סומן
        allow_soft_conflicts=True,
    )
    # צד אחד לא-חובה => רך. אבל 61753 עצמו חייב להיחשב "חובה".
    assert conflict_is_hard(a, b, prefs) is False
    prefs_none = Preferences(attendance={}, allow_soft_conflicts=True)
    assert conflict_is_hard(a, b, prefs_none) is True


def test_missing_kind_in_the_dict_means_required(courses):
    """הקורס מוזכר, אבל סוג אחר. הרכיב שלנו נשאר חובה."""
    a = find_group(courses, *CLASH_A)
    b = find_group(courses, *CLASH_B)
    prefs = Preferences(
        attendance={"61753": {KIND_TUTORIAL: False}, "61756": {KIND_LECTURE: False}},
        allow_soft_conflicts=True,
    )
    assert conflict_is_hard(a, b, prefs) is True


def test_empty_per_course_dict_means_required(courses):
    a = find_group(courses, *CLASH_A)
    b = find_group(courses, *CLASH_B)
    prefs = Preferences(attendance={"61753": {}}, allow_soft_conflicts=True)
    assert conflict_is_hard(a, b, prefs) is True


def test_explicit_true_keeps_the_clash_hard(courses):
    a = find_group(courses, *CLASH_A)
    b = find_group(courses, *CLASH_B)
    prefs = Preferences(
        attendance={"61753": {KIND_LECTURE: True}}, allow_soft_conflicts=True
    )
    assert conflict_is_hard(a, b, prefs) is True


@pytest.mark.skipif(
    attendance_required is None,
    reason="scheduler.attendance_required אינה חשופה בשם הזה",
)
def test_attendance_required_defaults_to_true(courses):
    lecture = find_group(courses, *CLASH_A)
    assert attendance_required(Preferences(), lecture) is True
    assert attendance_required(Preferences(attendance={}), lecture) is True
    assert (
        attendance_required(
            Preferences(attendance={"61753": {KIND_LECTURE: False}}), lecture
        )
        is False
    )


# ==========================================================================
# 4. Selection — is_feasible נשארת קשיחה, overlapping_pairs היא החדשה
# ==========================================================================
def test_is_feasible_still_means_strict_no_overlap(courses):
    """models.Selection.is_feasible אינה מקבלת prefs ואינה משתנה. SPEC_V2 §2."""
    sel = Selection([find_group(courses, *CLASH_A), find_group(courses, *CLASH_B)])
    assert sel.is_feasible() is False
    assert set(inspect.signature(Selection.is_feasible).parameters) == {"self"}


def test_overlapping_pairs_finds_the_real_clash(courses):
    a = find_group(courses, *CLASH_A)
    b = find_group(courses, *CLASH_B)
    pairs = Selection([a, b]).overlapping_pairs()
    assert len(pairs) == 1
    assert {g.group_id for g in pairs[0]} == {a.group_id, b.group_id}


def test_overlapping_pairs_is_empty_for_a_clean_selection(courses):
    sel = next(iter(enumerate_selections(courses, Preferences())))
    assert sel.overlapping_pairs() == []


def test_overlapping_pairs_and_is_feasible_always_agree(courses):
    for sel in enumerate_selections(courses, soft_prefs()):
        assert sel.is_feasible() == (not sel.overlapping_pairs())


# ==========================================================================
# 5. ניקוד — חפיפה רכה עולה כסף
# ==========================================================================
def test_default_weights_include_the_soft_conflict_penalty():
    assert DEFAULT_WEIGHTS["soft_conflict"] == 6.0
    assert Preferences().weights["soft_conflict"] == 6.0


def test_a_soft_conflict_is_counted_in_the_scored_schedule(courses):
    sel = Selection([find_group(courses, *CLASH_A), find_group(courses, *CLASH_B)])
    scored = score(sel, soft_prefs())
    assert scored.soft_conflicts == 1
    assert scored.soft_conflicts == len(sel.overlapping_pairs())


def test_soft_conflict_minutes_measure_the_overlap(courses):
    """יום ד 08:30-10:30 מול 08:30-11:30 => 120 דקות חופפות."""
    sel = Selection([find_group(courses, *CLASH_A), find_group(courses, *CLASH_B)])
    assert score(sel, soft_prefs()).soft_conflict_minutes == H1030 - H0830


def test_a_soft_conflict_lowers_the_score_by_its_weight(courses):
    sel = Selection([find_group(courses, *CLASH_A), find_group(courses, *CLASH_B)])
    penalised = score(sel, soft_prefs())
    free = score(sel, soft_prefs(weights={"soft_conflict": 0.0}))
    assert penalised.soft_conflicts == 1
    assert free.score - penalised.score == pytest.approx(
        DEFAULT_WEIGHTS["soft_conflict"]
    )
    assert penalised.breakdown["soft_conflict"] == pytest.approx(-6.0)
    assert penalised.score == pytest.approx(sum(penalised.breakdown.values()))


def test_the_penalty_scales_with_the_number_of_soft_conflicts(courses):
    """שתי חפיפות עולות פי שתיים מאחת."""
    a = find_group(courses, *CLASH_A)  # ד+ה 08:30-10:30
    b = find_group(courses, *CLASH_B)  # ד 08:30-11:30
    c = find_group(courses, "61756", KIND_TUTORIAL, "271060310/2")  # ה 08:30-11:30
    sel = Selection([a, b, c])
    scored = score(sel, soft_prefs())
    assert scored.soft_conflicts == 2
    assert scored.breakdown["soft_conflict"] == pytest.approx(-12.0)


def test_a_clean_schedule_pays_no_soft_conflict_penalty(courses):
    sel = next(iter(enumerate_selections(courses, Preferences())))
    scored = score(sel, soft_prefs())
    assert scored.soft_conflicts == 0
    assert scored.breakdown.get("soft_conflict", 0.0) == pytest.approx(0.0)


# ==========================================================================
# 6. דיווח — אסור שחפיפה מכוונת תעבור בשקט
# ==========================================================================
def test_describe_soft_conflicts_names_both_groups(courses):
    a = find_group(courses, *CLASH_A)
    b = find_group(courses, *CLASH_B)
    text = "\n".join(describe(Selection([a, b]), soft_prefs()))
    assert "61753" in text and a.group_id in text
    assert "61756" in text and b.group_id in text


def test_describe_soft_conflicts_names_the_day_and_the_hours(courses):
    a = find_group(courses, *CLASH_A)
    b = find_group(courses, *CLASH_B)
    text = "\n".join(describe(Selection([a, b]), soft_prefs()))
    assert ("יום ד" in text) or ("רביעי" in text), text
    assert "08:30" in text
    assert "10:30" in text


def test_describe_soft_conflicts_mentions_the_kinds(courses):
    a = find_group(courses, *CLASH_A)
    b = find_group(courses, *CLASH_B)
    text = "\n".join(describe(Selection([a, b]), soft_prefs()))
    assert KIND_LECTURE in text
    assert KIND_TUTORIAL in text


def test_describe_soft_conflicts_is_empty_for_a_clean_selection(courses):
    sel = next(iter(enumerate_selections(courses, Preferences())))
    assert describe(sel, soft_prefs()) == []


def test_describe_soft_conflicts_reports_every_pair(courses):
    a = find_group(courses, *CLASH_A)
    b = find_group(courses, *CLASH_B)
    c = find_group(courses, "61756", KIND_TUTORIAL, "271060310/2")
    lines = describe(Selection([a, b, c]), soft_prefs())
    assert len(lines) >= 2
    joined = "\n".join(lines)
    assert b.group_id in joined and c.group_id in joined


# ==========================================================================
# 7. הרווח בפועל — למה הסטודנטית ביקשה את זה
# ==========================================================================
def test_optional_lecture_unlocks_schedules_the_strict_solver_rejects(courses):
    selections = list(enumerate_selections(courses, soft_prefs()))
    strict = list(enumerate_selections(courses, Preferences()))
    assert len(selections) > len(strict)
    rejected_by_strict = [s for s in selections if not s.is_feasible()]
    assert rejected_by_strict, "לא נמצאה אף מערכת חדשה — הפיצ'ר לא עושה כלום"


def test_waiving_attendance_opens_schedules_the_strict_solver_rejects(courses):
    """הוויתור על נוכחות פותח מערכות שהפתרון הקשיח אינו מאפשר.

    התיקון בפרסר שינה את המשמעות של הבדיקה הזאת: קודם 4 ימים היו אפשריים
    **רק** בוויתור על נוכחות, וכיום הם אפשריים גם בלעדיו. לכן מה שנבדק כאן
    אינו עוד "מי קונה את היום הרביעי", אלא הדבר שנשאר נכון — שהוויתור מוסיף
    מערכות שאי אפשר להגיע אליהן אחרת.
    """
    strict = list(enumerate_selections(courses, Preferences()))
    soft = list(enumerate_selections(courses, soft_prefs()))
    assert len(soft) > len(strict)

    overlapping = [s for s in soft if not s.is_feasible()]
    assert overlapping, "חייבות להיות מערכות שנפתחו רק בזכות הוויתור"
    assert all(s.is_feasible() for s in strict), "הפתרון הקשיח לעולם בלי חפיפות"


def test_the_strict_enumeration_is_a_subset_of_the_soft_one(courses):
    strict = {selection_key(s) for s in enumerate_selections(courses, Preferences())}
    soft = {selection_key(s) for s in enumerate_selections(courses, soft_prefs())}
    assert strict, "הפתרון הקשיח ריק — אין מה להשוות"
    # ‏תת-קבוצה **ממש**: ‏``<=`` לבדו היה עובר גם אילו הרפיה לא מוסיפה דבר.
    assert strict < soft, "הרפיה חייבת רק להוסיף פתרונות, אף פעם לא לגרוע"


def test_the_soft_enumeration_is_exactly_what_the_rule_allows(courses):
    """כל שינוי בכלל החפיפה נראה מיד — בלי לקבע מספר.

    ‏עד 2026-09-10 זה היה ``== 564``, "מספר מדויק כדי שכל שינוי ייראה
    מיד". הכוונה הייתה נכונה והמימוש היה שביר: המספר זז גם כשהכלל לא
    השתנה. ההשוואה מול ספירה ממצה של אותו כלל אומרת את אותו הדבר, ורק
    שינוי אמיתי בכלל מפיל אותה.
    """
    prefs = soft_prefs()
    engine = {selection_key(s) for s in enumerate_selections(courses, prefs)}
    assert engine == legal_combinations(courses, prefs)


def _linked_candidates(courses: list[Course], owner: Group) -> list[Group]:
    """כל הקבוצות שרשימת linked_to של ``owner`` מדברת עליהן בפועל."""
    course = next(c for c in courses if c.code == owner.course_code)
    kinds = {g.kind for g in course.groups if g.group_id in owner.linked_to}
    return [g for g in course.groups if g.kind in kinds]


def test_linked_to_is_still_enforced_when_conflicts_go_soft(courses):
    """הרפיית הנוכחות אינה מרפה את כלל הקבוצות המקושרות. SPEC_WEB מזהיר על זה."""
    for sel in enumerate_selections(courses, soft_prefs()):
        for i, a in enumerate(sel.groups):
            for b in sel.groups[i + 1 :]:
                if a.course_code != b.course_code or not a.linked_to:
                    continue
                if b.group_id in a.linked_to:
                    continue
                # מותר רק אם כלל הקישור בכלל לא חל על סוג הרכיב של b
                assert b.group_id not in {
                    g.group_id for g in _linked_candidates(courses, a)
                }, f"{a.label()} מקושרת ל-{a.linked_to} אבל נבחרה עם {b.label()}"


def test_solve_can_return_a_soft_schedule_and_flags_it(courses):
    """solve חייבת להחזיר מערכות רכות *ולסמן* אותן — לא בשקט.

    מאז 2026-10-09 הסדר הוא לפי עדיפות, וחפיפה נכנסת לחמש המובילות רק כשהיא
    קונה משהו. כאן היא לא חוסכת יום (הרצאת 61753 ממילא אינה נספרת), ולכן
    מדורג/ת מתרגל/ת שרק חפיפה מאפשרת. בלי זה הבדיקה דילגה בלי לבדוק דבר."""
    prefs = soft_prefs(
        target_days=4,
        preferred_lecturers={"61756": {"תרגול": ["מר חסאוי טירן"]}},
    )
    best = solve(courses, prefs, top_n=5)
    assert best
    soft = [s for s in best if s.soft_conflicts > 0]
    if not soft:
        pytest.skip("הניקוד העדיף מערכות נקיות — עדיין תקין, אך אין מה לבדוק כאן")
    for sched in soft:
        assert sched.selection.overlapping_pairs()
        assert describe(sched.selection, prefs)


# ==========================================================================
# 8. זריעת ברירות המחדל מהערות הידיעון (SPEC_V2 §2, "Seeding the defaults")
# ==========================================================================
def test_a_yedion_attendance_note_never_seeds_optional(courses):
    seeder = _resolve(
        "seed_attendance", "seed_attendance_from_notes", "attendance_from_notes"
    )
    if seeder is None:
        pytest.skip("פונקציית הזריעה אינה חשופה בשם מוכר")
    seeded = seeder(courses)
    assert seeded.get("11069", {}).get(KIND_COMBINED) is not False
    prefs = Preferences(attendance=seeded, allow_soft_conflicts=True)
    # ‏"הזריעה לא הפכה דבר לרשות" = אותה קבוצת מערכות בדיוק כמו בלעדיה.
    # עד 2026-09-10 נבדק כ-``== 83`` בשני הצדדים בנפרד.
    assert {selection_key(s) for s in enumerate_selections(courses, prefs)} == {
        selection_key(s) for s in enumerate_selections(courses, Preferences())
    }


# ==========================================================================
# 9. שפיות: נתונים סינתטיים קטנים, לבדוק את הכלל בלי המאגר
# ==========================================================================
def _tiny_pair() -> tuple[Group, Group]:
    a = Group(
        course_code="99001",
        group_id="A1",
        kind=KIND_LECTURE,
        lecturer="פלוני",
        meetings=[Meeting(day=THU, start=H0830, end=H1030, semester="א")],
    )
    b = Group(
        course_code="99002",
        group_id="B1",
        kind=KIND_TUTORIAL,
        lecturer="אלמוני",
        meetings=[Meeting(day=THU, start=H0830, end=H1130, semester="א")],
    )
    return a, b


def test_synthetic_pair_follows_the_same_rule():
    a, b = _tiny_pair()
    assert conflict_is_hard(a, b, Preferences()) is True
    assert conflict_is_hard(a, b, Preferences(allow_soft_conflicts=True)) is True
    relaxed = Preferences(
        attendance={"99001": {KIND_LECTURE: False}}, allow_soft_conflicts=True
    )
    assert conflict_is_hard(a, b, relaxed) is False


def test_touching_meetings_are_not_a_conflict_at_all():
    """08:30-10:30 ו-10:30-11:30 — חצי-פתוח, אין חפיפה. הכלל לא מופעל בכלל."""
    a, b = _tiny_pair()
    b.meetings = [Meeting(day=THU, start=H1030, end=H1130, semester="א")]
    assert conflict_is_hard(a, b, Preferences()) is False
    assert Selection([a, b]).overlapping_pairs() == []
    assert Selection([a, b]).is_feasible() is True
