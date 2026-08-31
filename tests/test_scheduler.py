# -*- coding: utf-8 -*-
"""
בדיקות המנוע — tests for src/scheduler.py.

הבדיקות רצות **לגמרי אופליין**: אין רשת, אין דפדפן, אין Playwright.
כל הנתונים מגיעים מ-tests/fixtures/sample_sections.json — נתונים סינתטיים
אבל ריאליסטיים עבור ששת הקורסים האמיתיים של סמסטר 5.

איך מריצים:
    python -m pytest tests -q

מוסכמות שחוזרות בכל הקובץ (ראי גם src/models.py):
    יום   : 1=ראשון ... 6=שישי
    שעה   : דקות מחצות. 08:30 -> 510
    חפיפה : חצי-פתוחה [start, end) — 08:30-10:15 ו-10:15-12:00 *אינם* מתנגשים.

Technical note: every file is opened with encoding="utf-8" (Windows would
otherwise default to cp1255), and stdout is reconfigured defensively so that a
failing assertion which prints Hebrew does not itself explode with a
UnicodeEncodeError.
"""

from __future__ import annotations

import json
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

FIXTURE_PATH = ROOT / "tests" / "fixtures" / "sample_sections.json"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass  # זרם שלא ניתן לשינוי (pytest capture / pipe) — ממשיכים בלי

from models import (  # noqa: E402  (import after the sys.path surgery — intentional)
    KIND_LAB,
    KIND_LECTURE,
    KIND_PROJECT,
    KIND_TUTORIAL,
    Course,
    Group,
    Meeting,
    Selection,
)
from scheduler import (  # noqa: E402
    Infeasible,
    Preferences,
    SearchExhausted,
    TiedCoursesError,
    diagnose_infeasibility,
    enumerate_selections,
    score,
    solve,
)

# --------------------------------------------------------------------------
# קבועי זמן — כדי שהבדיקות ייקראו כמו לוח שעות ולא כמו מספרים.
# --------------------------------------------------------------------------
T0830, T0915, T1000, T1015 = 510, 555, 600, 615
T1200, T1245, T1345, T1400 = 720, 765, 825, 840
T1430, T1545, T1600, T1630 = 870, 945, 960, 990
T1745, T1800, T1830, T2000 = 1065, 1080, 1110, 1200

FULL_DAY = (0, 24 * 60)

# שמות מרצים שמופיעים ב-fixture (מועתקים ממנו כלשונם).
LEVI = 'ד"ר לוי נטלי'
VOLKOVICH = "פרופ' וולקוביץ' זאב"
MILLER = 'ד"ר מילר אורנה'


# ==========================================================================
# טעינת ה-fixture
# ==========================================================================
def _courses_from_raw(raw: object) -> dict[str, Course]:
    """
    בונה dict[str, Course] מתוך מבנה ה-JSON, ישירות מול שמות השדות של models.

    זהו קורא הגיבוי: הוא משמש כשעדיין אין parser.load_sections, או כשהוא
    נכשל. הוא סלחני לגבי העטיפה החיצונית ({"courses": ...} / {code: ...} /
    רשימה) בדיוק כמו הקורא הפנימי שבתוך scheduler.py.
    """
    data: object = raw
    if isinstance(data, dict) and "courses" in data:
        data = data["courses"]

    if isinstance(data, dict):
        items = list(data.values())
    elif isinstance(data, list):
        items = list(data)
    else:  # pragma: no cover - צורת JSON בלתי צפויה
        raise AssertionError(f"מבנה JSON לא נתמך ב-fixture: {type(raw)!r}")

    courses: dict[str, Course] = {}
    for item in items:
        code = str(item["code"])
        groups = [
            Group(
                course_code=str(gd.get("course_code", code)),
                group_id=str(gd["group_id"]),
                kind=str(gd["kind"]),
                lecturer=str(gd.get("lecturer", "")),
                meetings=[
                    Meeting(
                        day=int(md["day"]),
                        start=int(md["start"]),
                        end=int(md["end"]),
                        room=str(md.get("room", "")),
                        building=str(md.get("building", "")),
                    )
                    for md in gd.get("meetings", [])
                ],
                linked_to=[str(x) for x in gd.get("linked_to", [])],
                note=str(gd.get("note", "")),
            )
            for gd in item.get("groups", [])
        ]
        courses[code] = Course(
            code=code,
            name=str(item.get("name", "")),
            credits=float(item.get("credits", 0.0)),
            groups=groups,
            tied_with=[str(x) for x in item.get("tied_with", [])],
        )
    return courses


def _load_via_parser() -> dict[str, Course] | None:
    """מנסה את הקורא הקנוני parser.load_sections. None אם הוא עוד לא קיים."""
    try:
        from parser import load_sections  # type: ignore[attr-defined]
    except Exception:
        return None
    try:
        loaded = load_sections(str(FIXTURE_PATH))
    except Exception:
        return None
    if isinstance(loaded, dict) and loaded:
        return loaded
    return None


@pytest.fixture(scope="session")
def raw_fixture() -> dict:
    """ה-JSON הגולמי. שים לב ל-encoding='utf-8' — חובה על Windows."""
    with open(FIXTURE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def courses(raw_fixture: dict) -> dict[str, Course]:
    """{קוד קורס: Course} — מועדף דרך parser, ובגיבוי דרך הקורא המקומי."""
    return _load_via_parser() or _courses_from_raw(raw_fixture)


@pytest.fixture(scope="session")
def course_list(courses: dict[str, Course]) -> list[Course]:
    """רשימת הקורסים בסדר קבוע לפי קוד — לעולם לא מסתמכים על סדר של dict."""
    return [courses[code] for code in sorted(courses)]


@pytest.fixture(scope="session")
def all_selections(course_list: list[Course]) -> list[Selection]:
    """כל הבחירות התקינות תחת ההעדפות הבסיסיות (מחושב פעם אחת לכל הריצה)."""
    return list(enumerate_selections(course_list, Preferences(target_days=4)))


# --------------------------------------------------------------------------
# עזרים לבניית נתונים סינתטיים זעירים בתוך הבדיקות עצמן
# --------------------------------------------------------------------------
def mk_group(
    code: str,
    gid: str,
    kind: str,
    lecturer: str,
    slots: list[tuple[int, int, int]],
    linked_to: list[str] | None = None,
) -> Group:
    """קבוצה קטנה לבדיקה. slots הוא [(יום, התחלה, סוף), ...]."""
    return Group(
        course_code=code,
        group_id=gid,
        kind=kind,
        lecturer=lecturer,
        meetings=[Meeting(day=d, start=s, end=e) for d, s, e in slots],
        linked_to=list(linked_to or []),
    )


def mk_course(code: str, groups: list[Group], name: str = "קורס בדיקה") -> Course:
    """קורס זעיר לבדיקה, בלי צמידויות."""
    return Course(code=code, name=name, credits=1.0, groups=groups, tied_with=[])


def weights(lecturer=0.0, days=0.0, gaps=0.0, compactness=0.0) -> dict[str, float]:
    """מילון משקולות מלא — תמיד כל ארבעת המפתחות, כדי לבודד רכיב אחד."""
    return {
        "lecturer": float(lecturer),
        "days": float(days),
        "gaps": float(gaps),
        "compactness": float(compactness),
    }


def group_of(courses: dict[str, Course], code: str, gid: str) -> Group:
    """שולפת קבוצה לפי (קוד קורס, מספר קבוצה). נכשלת בבירור אם אינה קיימת."""
    for g in courses[code].groups:
        if g.group_id == gid:
            return g
    raise AssertionError(f"קבוצה {gid} לא נמצאה בקורס {code}")


def ids_of(sel: Selection) -> set[tuple[str, str]]:
    """{(קוד קורס, מספר קבוצה)} — ייצוג יציב שאינו תלוי בסדר."""
    return {(g.course_code, g.group_id) for g in sel.groups}


def reasons_of(exc: BaseException) -> list[str]:
    """ההסברים שנשמרו על החריגה, עם נפילה להודעה עצמה."""
    found = list(getattr(exc, "reasons", []) or [])
    return found or ([str(exc)] if str(exc).strip() else [])


# ==========================================================================
# 1. ה-fixture עצמו — שהנתונים שעליהם נשענות כל שאר הבדיקות באמת תקינים
# ==========================================================================
EXPECTED_CODES = {"11069", "61753", "61756", "61757", "61832", "62027"}
TIED_BLOCK = {"61756", "61757", "62027"}


def test_fixture_contains_the_six_real_course_codes(courses):
    """ה-fixture מכסה בדיוק את ששת הקורסים של סמסטר 5."""
    assert set(courses) == EXPECTED_CODES


def test_fixture_names_and_credits_match_the_curriculum(courses):
    """שמות הקורסים בעברית ונקודות הזכות — כפי שהם בידיעון."""
    expected = {
        "11069": ("אנגלית טכנית יישומית – תוכנה", 1.0),
        "61753": ("אלגוריתמים", 5.0),
        "61756": ("שיטות הנדסיות לפיתוח מערכות תוכנה", 5.0),
        "61757": ("מבוא לבדיקות תוכנה", 2.0),
        "61832": ("מבוא להסתברות וסטטיסטיקה", 4.0),
        "62027": ("אינטראקציית אדם מחשב (HCI)", 2.0),
    }
    for code, (name, credits) in expected.items():
        assert courses[code].name == name
        assert courses[code].credits == pytest.approx(credits)


def test_fixture_declares_the_tied_block_symmetrically(courses):
    """קורסים צמודים: כל אחד מהשלושה מצהיר על שני האחרים, בלי לכלול את עצמו."""
    for code in sorted(TIED_BLOCK):
        assert set(courses[code].tied_with) == TIED_BLOCK - {code}, code
    for code in sorted(EXPECTED_CODES - TIED_BLOCK):
        assert courses[code].tied_with == []


def test_fixture_has_between_two_and_four_groups_per_component(courses):
    """לכל (קורס, סוג רכיב) יש 2-4 קבוצות — אחרת אין בכלל מה לבחור ביניהן."""
    for code in sorted(courses):
        course = courses[code]
        assert course.kinds(), f"{code} בלי אף רכיב"
        for kind in course.kinds():
            n = len(course.groups_of(kind))
            assert 2 <= n <= 4, f"{code} {kind}: {n} קבוצות"


def test_fixture_component_structure_matches_the_real_courses(courses):
    """מבנה הרכיבים: 61756 = הרצאה+תרגול+פרויקט, 61757 = הרצאה+מעבדה, וכו'."""
    expected = {
        "11069": {KIND_TUTORIAL},
        "61753": {KIND_LECTURE, KIND_TUTORIAL},
        "61756": {KIND_LECTURE, KIND_TUTORIAL, KIND_PROJECT},
        "61757": {KIND_LECTURE, KIND_LAB},
        "61832": {KIND_LECTURE, KIND_TUTORIAL},
        "62027": {KIND_LECTURE},
    }
    for code, kinds in expected.items():
        assert set(courses[code].kinds()) == kinds, code


def test_fixture_linked_to_points_at_a_real_group_in_the_same_course(courses):
    """כל מזהה ב-linked_to חייב להתקיים באותו קורס, אחרת האילוץ בלתי אפשרי."""
    linked_found = 0
    for code in sorted(courses):
        available = {g.group_id for g in courses[code].groups}
        for g in courses[code].groups:
            for target in g.linked_to:
                linked_found += 1
                assert target in available, f"{code}/{g.group_id} -> {target}"
                assert target != g.group_id
    assert linked_found >= 2, "ה-fixture חייב להכיל לפחות זוג linked_to אחד"


def test_fixture_algorithms_lecture_is_split_over_two_days(courses):
    """61753: ההרצאה בת 4 ש\"ש ומפוצלת לשני מפגשים בשני ימים שונים."""
    for g in courses["61753"].groups_of(KIND_LECTURE):
        assert len(g.meetings) == 2, g.group_id
        assert len(g.days()) == 2, g.group_id


@pytest.mark.parametrize("code", sorted(EXPECTED_CODES))
def test_fixture_meetings_are_well_formed(courses, code):
    """כל מפגש: יום 1-6, שעת סיום אחרי שעת התחלה, ובתוך יממה."""
    for g in courses[code].groups:
        assert g.meetings, f"{code}/{g.group_id} בלי מפגשים"
        assert g.lecturer.strip(), f"{code}/{g.group_id} בלי מרצה"
        for m in g.meetings:
            assert 1 <= m.day <= 6
            assert 0 <= m.start < m.end <= 24 * 60
            assert m.duration() > 0


def test_fixture_loads_through_parser_load_sections_unmodified(raw_fixture):
    """
    דרישת SPEC: הקובץ חייב להיטען דרך parser.load_sections כמו שהוא.
    אם parser.py עדיין לא נכתב — מדלגים במקום להיכשל.
    """
    loaded = _load_via_parser()
    if loaded is None:
        pytest.skip("parser.load_sections עדיין לא זמין (parser.py not ready yet)")
    assert set(loaded) == EXPECTED_CODES
    for code, course in loaded.items():
        assert isinstance(course, Course)
        assert len(course.groups) == len(raw_fixture[code]["groups"])


# ==========================================================================
# 2. Meeting.overlaps — חפיפה חצי-פתוחה [start, end)
# ==========================================================================
def test_touching_boundaries_do_not_overlap():
    """שיעור שנגמר ב-10:00 ואחד שמתחיל ב-10:00 — לא מתנגשים. זה הלב של [start, end)."""
    ends_at_ten = Meeting(day=2, start=T0830, end=T1000)
    starts_at_ten = Meeting(day=2, start=T1000, end=T1200)
    assert ends_at_ten.overlaps(starts_at_ten) is False
    assert starts_at_ten.overlaps(ends_at_ten) is False


def test_one_minute_overlap_does_conflict():
    """דקה אחת של חפיפה היא כבר התנגשות."""
    a = Meeting(day=2, start=T0830, end=T1000 + 1)  # מסתיים ב-10:01
    b = Meeting(day=2, start=T1000, end=T1200)
    assert a.overlaps(b) is True
    assert b.overlaps(a) is True


def test_meetings_on_different_days_never_overlap():
    """אותן שעות בדיוק, ימים שונים — אין התנגשות."""
    a = Meeting(day=1, start=T1015, end=T1200)
    b = Meeting(day=3, start=T1015, end=T1200)
    assert a.overlaps(b) is False
    assert b.overlaps(a) is False


def test_contained_meeting_overlaps_and_duration_is_correct():
    """מפגש שכולו בתוך מפגש אחר — חפיפה מלאה. וגם: duration בדקות."""
    outer = Meeting(day=4, start=T0830, end=T1400)
    inner = Meeting(day=4, start=T1015, end=T1200)
    assert outer.overlaps(inner) is True
    assert inner.overlaps(outer) is True
    assert inner.duration() == T1200 - T1015 == 105
    assert Meeting(day=1, start=T1200, end=T1200).duration() == 0


def test_group_conflicts_with_uses_the_same_half_open_rule():
    """Group.conflicts_with עובר על כל זוגות המפגשים — עם אותו כלל בדיוק."""
    a = mk_group("90001", "1", KIND_LECTURE, "א", [(1, T0830, T1015), (3, T0830, T1015)])
    touching = mk_group("90002", "1", KIND_TUTORIAL, "ב", [(3, T1015, T1200)])
    clashing = mk_group("90003", "1", KIND_TUTORIAL, "ג", [(3, T1015 - 1, T1200)])
    assert a.conflicts_with(touching) is False
    assert touching.conflicts_with(a) is False
    assert a.conflicts_with(clashing) is True
    assert clashing.conflicts_with(a) is True


def test_the_optimal_fixture_pair_is_touching_not_clashing(courses):
    """
    בדיקה על נתוני אמת: ההרצאה 08:30-10:15 והתרגול 10:15-12:00 של 61753
    נוגעים זה בזה ביום ב' — ולכן מותרים יחד. זה מה שמאפשר מערכת צפופה.
    """
    lecture = group_of(courses, "61753", "21")  # ימים ב' ו-ד', 08:30-10:15
    tutorial = group_of(courses, "61753", "24")  # יום ב', 10:15-12:00
    assert lecture.conflicts_with(tutorial) is False


# ==========================================================================
# 3. חישוב חורים (gap_minutes) ואורך יום (span)
# ==========================================================================
def test_gap_minutes_counts_the_hole_between_two_meetings_on_one_day():
    """08:30-10:15 ואז 12:00-13:45 באותו יום => חור של 105 דקות."""
    sel = Selection(
        [
            mk_group("90010", "1", KIND_LECTURE, "א", [(1, T0830, T1015)]),
            mk_group("90011", "1", KIND_TUTORIAL, "ב", [(1, T1200, T1345)]),
        ]
    )
    assert sel.gap_minutes() == T1200 - T1015 == 105


def test_gap_minutes_is_zero_across_different_days():
    """אותם שני מפגשים בדיוק, אבל בימים שונים — אפס חורים. חורים נספרים רק בתוך יום."""
    sel = Selection(
        [
            mk_group("90012", "1", KIND_LECTURE, "א", [(1, T0830, T1015)]),
            mk_group("90013", "1", KIND_TUTORIAL, "ב", [(3, T1200, T1345)]),
        ]
    )
    assert sel.gap_minutes() == 0
    assert sel.days_used() == {1, 3}


def test_gap_minutes_is_never_negative_for_overlapping_meetings():
    """מפגשים חופפים לא מייצרים 'חור שלילי'."""
    sel = Selection(
        [
            mk_group("90014", "1", KIND_LECTURE, "א", [(2, T0830, T1200)]),
            mk_group("90015", "1", KIND_TUTORIAL, "ב", [(2, T1015, T1400)]),
        ]
    )
    assert sel.gap_minutes() == 0


def test_gap_minutes_is_never_negative_for_a_contained_meeting():
    """
    מפגש קצר שבלוע בתוך מפגש ארוך, ואחריו מפגש מאוחר:
    רק החור האמיתי (14:00->16:00) נספר, והבלוע לא מזיז את המונה אחורה.
    """
    sel = Selection(
        [
            mk_group("90016", "1", KIND_LECTURE, "א", [(2, T0830, T1400)]),
            mk_group("90017", "1", KIND_TUTORIAL, "ב", [(2, T1015, T1200)]),
            mk_group("90018", "1", KIND_LAB, "ג", [(2, T1600, T1745)]),
        ]
    )
    assert sel.gap_minutes() == T1600 - T1400 == 120


def test_gap_minutes_is_zero_for_a_perfectly_contiguous_day():
    """שרשרת נוגעת 08:30-10:15-12:00-14:30 — אפס חורים."""
    sel = Selection(
        [
            mk_group("90019", "1", KIND_LECTURE, "א", [(4, T0830, T1015)]),
            mk_group("90020", "1", KIND_TUTORIAL, "ב", [(4, T1015, T1200)]),
            mk_group("90021", "1", KIND_PROJECT, "ג", [(4, T1200, T1430)]),
        ]
    )
    assert sel.gap_minutes() == 0
    assert sel.span_minutes() == T1430 - T0830


def test_score_reports_the_same_gap_minutes_as_the_model():
    """ScoredSchedule.gap_minutes אינו חישוב חדש — הוא בדיוק Selection.gap_minutes()."""
    sel = Selection(
        [
            mk_group("90022", "1", KIND_LECTURE, "א", [(1, T0830, T1015)]),
            mk_group("90023", "1", KIND_TUTORIAL, "ב", [(1, T1200, T1345)]),
            mk_group("90024", "1", KIND_LAB, "ג", [(5, T1600, T1745)]),
        ]
    )
    sched = score(sel, Preferences(target_days=4))
    assert sched.gap_minutes == sel.gap_minutes() == 105
    assert sched.days_count == len(sel.days_used()) == 2


# ==========================================================================
# 4. enumerate_selections — מבנה כל פתרון
# ==========================================================================
def test_enumeration_finds_at_least_one_valid_selection(all_selections):
    """שפיות: ה-fixture בנוי כך שיש פתרונות."""
    assert len(all_selections) > 0


def test_every_selection_has_exactly_one_group_per_course_and_kind(
    all_selections, course_list
):
    """
    הדרישה המרכזית: קורס עם הרצאה ותרגול תורם בדיוק קבוצה אחת מכל סוג —
    לא שתיים מאותו סוג, ולא אפס.
    """
    required = {(c.code, kind) for c in course_list for kind in c.kinds()}
    assert len(required) == 11  # 1+2+3+2+2+1 רכיבים

    for sel in all_selections:
        seen: dict[tuple[str, str], int] = {}
        for g in sel.groups:
            key = (g.course_code, g.kind)
            seen[key] = seen.get(key, 0) + 1
        assert set(seen) == required
        assert all(count == 1 for count in seen.values()), seen
        assert len(sel.groups) == len(required)


def test_every_enumerated_selection_is_conflict_free(all_selections):
    """שום בחירה שהמנוע מחזיר לא מכילה שתי קבוצות חופפות."""
    for sel in all_selections:
        assert sel.is_feasible(), sorted(ids_of(sel))


def test_enumerated_selections_are_distinct(all_selections):
    """אין כפילויות — כל בחירה מופיעה פעם אחת בלבד."""
    keys = [tuple(sorted(ids_of(sel))) for sel in all_selections]
    assert len(keys) == len(set(keys))


def test_enumerate_respects_latest(course_list):
    """latest=18:00 מוחק את 61832 קבוצה 53 (מסתיימת 18:30) — ורק אותה."""
    prefs = Preferences(target_days=4, latest=T1800)
    sels = list(enumerate_selections(course_list, prefs))
    assert sels, "האילוץ latest=18:00 לא אמור לחסום את המערכת לגמרי"
    for sel in sels:
        assert ("61832", "53") not in ids_of(sel)
        for m in sel.all_meetings():
            assert m.end <= T1800


def test_enumerate_respects_earliest():
    """
    earliest חוסם קבוצות שמתחילות מוקדם מדי. נבדק על נתונים סינתטיים
    כדי שהאילוץ יהיה חד ובלי תופעות לוואי.
    """
    early = mk_group("90030", "11", KIND_LECTURE, "א", [(1, T0830, T1015)])
    late = mk_group("90030", "12", KIND_LECTURE, "ב", [(1, T1200, T1345)])
    other = mk_group("90031", "21", KIND_TUTORIAL, "ג", [(2, T1400, T1545)])

    prefs = Preferences(target_days=6, earliest=T1015)
    sels = list(
        enumerate_selections(
            [mk_course("90030", [early, late]), mk_course("90031", [other])], prefs
        )
    )
    assert len(sels) == 1
    assert ids_of(sels[0]) == {("90030", "12"), ("90031", "21")}
    for m in sels[0].all_meetings():
        assert m.start >= T1015


def test_enumerate_respects_blocked_windows(course_list):
    """חלון חסום ביום א' 12:00-14:00 מוחק כל קבוצה שחופפת לו."""
    day, w_start, w_end = 1, T1200, T1400
    prefs = Preferences(target_days=4, blocked_windows=[(day, w_start, w_end)])
    sels = list(enumerate_selections(course_list, prefs))
    assert sels, "חסימת חלון אחד לא אמורה להפיל את כל המערכת"

    for sel in sels:
        for m in sel.all_meetings():
            if m.day == day:
                assert not (m.start < w_end and w_start < m.end), str(m)
        # שתי הקבוצות שנופלות מהחלון: 61832/51 (12:00-14:30) ו-61753/23 (12:00-13:45)
        assert ("61832", "51") not in ids_of(sel)
        assert ("61753", "23") not in ids_of(sel)

    # --- הצד החיובי: מה שרק *נוגע* בגבול החלון חייב לשרוד -----------------
    # החפיפה מול חלון חסום היא חצי-פתוחה בדיוק כמו בין שני מפגשים, ולכן
    # בלי הבדיקות האלה באג של [start, end] סגור היה מוחק קבוצות תקינות בשקט.
    reachable = set().union(*(ids_of(sel) for sel in sels))
    # 61832 קב' 54 — יום א' 10:15-12:00: נגמרת בדיוק כשהחלון נפתח.
    assert ("61832", "54") in reachable, "קבוצה שנגמרת בתחילת החלון נמחקה בטעות"
    # 61757 קב' 44 — יום א' 14:00-15:45: מתחילה בדיוק כשהחלון נסגר.
    assert ("61757", "44") in reachable, "קבוצה שמתחילה בסוף החלון נמחקה בטעות"
    # ...ולכן גם ההרצאה הצמודה אליה (linked_to) לא נגררת החוצה.
    assert ("61757", "42") in reachable

    # מספר הפתרונות מקובע: כל שינוי בסמנטיקת החלון החסום נעשה מיד גלוי.
    # (חפיפה סגורה במקום חצי-פתוחה מפילה את המספר הזה מ-292 ל-76.)
    assert len(sels) == 292


def test_enumerate_respects_forbid_friday(course_list):
    """forbid_friday מוחק את קבוצת יום שישי (11069/14) וכל פתרון שמשתמש בה."""
    free = list(enumerate_selections(course_list, Preferences(target_days=4)))
    no_friday = list(
        enumerate_selections(course_list, Preferences(target_days=4, forbid_friday=True))
    )
    assert no_friday, "בלי יום שישי עדיין חייבת להיות מערכת"
    assert len(no_friday) < len(free), "ל-forbid_friday חייבת להיות השפעה על ה-fixture"
    for sel in no_friday:
        assert 6 not in sel.days_used()
        assert ("11069", "14") not in ids_of(sel)


def test_search_exhausted_when_the_node_limit_is_tiny(course_list):
    """
    limit הוא בלם בטיחות: מכסת צמתים חלקיים. מכסה של צומת אחד חייבת
    לעצור חיפוש שיש בו 11 סלוטים.
    """
    with pytest.raises(SearchExhausted):
        list(enumerate_selections(course_list, Preferences(target_days=4), limit=1))


# ==========================================================================
# 5. linked_to — קבוצות צמודות בתוך אותו קורס, בשני הכיוונים
# ==========================================================================
def test_linked_pair_is_all_or_nothing_in_both_directions(all_selections, courses):
    """
    61753: הרצאה 23 ותרגול 26 מצהירות זו על זו. בכל פתרון — או ששתיהן בפנים,
    או ששתיהן בחוץ. אף פעם לא אחת מהן לבד.
    """
    assert group_of(courses, "61753", "23").linked_to == ["26"]
    assert group_of(courses, "61753", "26").linked_to == ["23"]

    together = 0
    for sel in all_selections:
        ids = ids_of(sel)
        has_lecture = ("61753", "23") in ids
        has_tutorial = ("61753", "26") in ids
        assert has_lecture == has_tutorial, sorted(ids)
        together += int(has_lecture)
    assert together > 0, "צריך להיות לפחות פתרון אחד שמשתמש בזוג הצמוד"


def test_linked_declared_on_one_side_only_is_still_enforced_symmetrically(
    all_selections, courses
):
    """
    61757: המעבדות מצהירות על ההרצאה שלהן, ההרצאות לא מצהירות כלום.
    האכיפה חייבת להיות סימטרית — מעבדה 43 <-> הרצאה 41, מעבדה 44 <-> הרצאה 42.
    בפרט: הרצאה 41 לעולם לא תופיע יחד עם מעבדה 44.
    """
    assert group_of(courses, "61757", "43").linked_to == ["41"]
    assert group_of(courses, "61757", "44").linked_to == ["42"]
    assert group_of(courses, "61757", "41").linked_to == []
    assert group_of(courses, "61757", "42").linked_to == []

    seen_43 = seen_44 = 0
    for sel in all_selections:
        ids = ids_of(sel)
        assert (("61757", "43") in ids) == (("61757", "41") in ids), sorted(ids)
        assert (("61757", "44") in ids) == (("61757", "42") in ids), sorted(ids)
        seen_43 += int(("61757", "43") in ids)
        seen_44 += int(("61757", "44") in ids)
    assert seen_43 > 0 and seen_44 > 0


def test_linked_to_is_satisfied_within_the_same_course(all_selections):
    """
    כלל linked_to חל רק בתוך אותו קורס: אם קבוצה שנבחרה מצהירה linked_to,
    היעד חייב להיבחר גם הוא — ומאותו קורס, לא מקורס זר עם אותו מספר.
    """
    for sel in all_selections:
        by_course: dict[str, set[str]] = {}
        for g in sel.groups:
            by_course.setdefault(g.course_code, set()).add(g.group_id)
        for g in sel.groups:
            if not g.linked_to:
                continue
            assert by_course[g.course_code] & set(g.linked_to), g.label()


# ==========================================================================
# 6. קורסים צמודים (korsim tzmudim) — 61756 / 61757 / 62027
# ==========================================================================
def test_tied_courses_appear_together_in_every_schedule(all_selections):
    """שלושת הקורסים הצמודים תמיד נוכחים יחד — חבילה בלתי נפרדת."""
    for sel in all_selections:
        present = sel.course_codes() & TIED_BLOCK
        assert present in (TIED_BLOCK, set()), sorted(present)
        assert present == TIED_BLOCK  # ב-fixture המלא הם תמיד בפנים


def test_solve_raises_when_a_tied_course_is_missing(courses):
    """אם 62027 נשמט מהרשימה החבילה שבורה — solve זורקת, ולא מחזירה []."""
    broken = [courses[c] for c in sorted(EXPECTED_CODES - {"62027"})]
    with pytest.raises((TiedCoursesError, Infeasible, ValueError)) as excinfo:
        solve(broken, Preferences(target_days=4), top_n=3)
    assert "62027" in str(excinfo.value)


@pytest.mark.parametrize("dropped", sorted(TIED_BLOCK))
def test_solve_raises_for_each_missing_partner_of_the_tied_block(courses, dropped):
    """אותו כלל בדיוק לכל אחד משלושת הקורסים הצמודים."""
    broken = [courses[c] for c in sorted(EXPECTED_CODES - {dropped})]
    with pytest.raises((TiedCoursesError, Infeasible, ValueError)):
        solve(broken, Preferences(target_days=4), top_n=1)


def test_a_tied_course_on_its_own_is_rejected(courses):
    """61756 לבדו, בלי שותפיו — שבירת חבילה, ולכן חריגה."""
    with pytest.raises((TiedCoursesError, Infeasible, ValueError)):
        solve([courses["61756"]], Preferences(target_days=4), top_n=1)


# ==========================================================================
# 7. ניקוד מרצים
# ==========================================================================
#: אותו זמן בדיוק לכל קבוצות הבדיקה — כדי לבודד את רכיב המרצה משאר הרכיבים.
SLOT = [(1, T1015, T1200)]


def _lecturer_prefs() -> Preferences:
    """משקולות שבהן רק רכיב המרצה חי. כל השאר אפס."""
    return Preferences(
        target_days=6,
        preferred_lecturers={"90040": [LEVI, MILLER]},
        weights=weights(lecturer=10.0),
    )


def test_rank_zero_lecturer_scores_higher_than_rank_one():
    """המרצה המועדפת (דירוג 0) שווה יותר מהשנייה (דירוג 1), ושתיהן חיוביות."""
    prefs = _lecturer_prefs()
    best = score(Selection([mk_group("90040", "11", KIND_LECTURE, LEVI, SLOT)]), prefs)
    second = score(Selection([mk_group("90040", "12", KIND_LECTURE, MILLER, SLOT)]), prefs)

    assert best.breakdown["lecturer"] > second.breakdown["lecturer"] > 0.0
    assert best.score > second.score
    assert best.breakdown["lecturer"] == pytest.approx(10.0)  # 10.0 * 1/(0+1)
    assert second.breakdown["lecturer"] == pytest.approx(5.0)  # 10.0 * 1/(1+1)


def test_unranked_lecturer_scores_zero():
    """מרצה שאינה ברשימת ההעדפות שווה 0 — לא שלילי, ולא חצי נקודה."""
    prefs = _lecturer_prefs()
    unranked = score(
        Selection([mk_group("90040", "13", KIND_LECTURE, VOLKOVICH, SLOT)]), prefs
    )
    assert unranked.breakdown["lecturer"] == pytest.approx(0.0)
    assert unranked.score == pytest.approx(0.0)
    assert unranked.lecturer_hits == 0


def test_lecturer_hits_counts_only_rank_zero():
    """lecturer_hits סופר אך ורק פגיעות במרצה המועדפת ביותר (דירוג 0)."""
    prefs = _lecturer_prefs()
    hit = score(Selection([mk_group("90040", "11", KIND_LECTURE, LEVI, SLOT)]), prefs)
    near_miss = score(
        Selection([mk_group("90040", "12", KIND_LECTURE, MILLER, SLOT)]), prefs
    )
    miss = score(
        Selection([mk_group("90040", "13", KIND_LECTURE, VOLKOVICH, SLOT)]), prefs
    )

    assert hit.lecturer_hits == 1
    assert near_miss.lecturer_hits == 0  # דירוג 1 מזכה בניקוד, אבל אינו "פגיעה"
    assert miss.lecturer_hits == 0
    for sched in (hit, near_miss, miss):
        assert sched.lecturer_total >= sched.lecturer_hits
        assert sched.lecturer_total == 1  # קורס מדורג אחד


def test_lecturer_ranking_ignores_courses_that_are_not_scheduled():
    """דירוג לקורס שאינו במערכת אינו מנפח ואינו מדלל את היחס hits/total."""
    prefs = Preferences(
        target_days=6,
        preferred_lecturers={"90040": [LEVI], "99999": [MILLER]},
        weights=weights(lecturer=10.0),
    )
    sched = score(Selection([mk_group("90040", "11", KIND_LECTURE, LEVI, SLOT)]), prefs)
    assert sched.lecturer_hits == 1
    assert sched.lecturer_total == 1


def test_lecturer_preference_steers_the_winning_schedule(course_list):
    """
    על נתוני אמת: כשרק המרצים נחשבים, המערכת המנצחת בוחרת את הקבוצות
    של המרצות המועדפות — 62027 עם ד"ר לוי, ו-61832 עם פרופ' וולקוביץ'.
    """
    prefs = Preferences(
        target_days=6,
        preferred_lecturers={"62027": [LEVI], "61832": [VOLKOVICH]},
        weights=weights(lecturer=10.0),
    )
    best = solve(course_list, prefs, top_n=1)[0]

    assert [g.lecturer for g in best.selection.groups if g.course_code == "62027"] == [LEVI]
    assert any(
        g.lecturer == VOLKOVICH for g in best.selection.groups if g.course_code == "61832"
    )
    assert best.lecturer_hits == 2
    assert best.lecturer_total == 2
    assert best.score == pytest.approx(20.0)


# ==========================================================================
# 8. קנס הימים — רק מעל היעד, אף פעם לא בונוס מתחתיו
# ==========================================================================
def _days_only_prefs(target: int = 4) -> Preferences:
    """משקולות שבהן רק ספירת הימים חיה."""
    return Preferences(target_days=target, weights=weights(days=8.0))


def _selection_over_n_days(n: int) -> Selection:
    """בחירה סינתטית שפרושה על n ימים — מפגש אחד ביום, בלי חורים בתוך יום."""
    return Selection(
        [
            mk_group(f"905{d:02d}", "1", KIND_LECTURE, "א", [(d, T0830, T1015)])
            for d in range(1, n + 1)
        ]
    )


@pytest.mark.parametrize("n_days", [1, 2, 3, 4])
def test_target_days_penalty_is_zero_at_or_below_target(n_days):
    """יעד 4 ימים: 1, 2, 3 או 4 ימים — קנס אפס. אין 'פרס' על פחות ימים."""
    sched = score(_selection_over_n_days(n_days), _days_only_prefs(4))
    assert sched.days_count == n_days
    assert sched.breakdown["days"] == pytest.approx(0.0)
    assert sched.score == pytest.approx(0.0)


def test_fewer_days_than_target_gives_no_bonus():
    """2 ימים ו-4 ימים מקבלים בדיוק אותו ניקוד — הקנס חד-כיווני."""
    prefs = _days_only_prefs(4)
    two = score(_selection_over_n_days(2), prefs)
    four = score(_selection_over_n_days(4), prefs)
    assert two.score == pytest.approx(four.score)
    assert two.breakdown["days"] == pytest.approx(four.breakdown["days"])


@pytest.mark.parametrize("n_days, expected", [(5, -8.0), (6, -16.0)])
def test_target_days_penalty_grows_only_above_the_target(n_days, expected):
    """מעל היעד הקנס לינארי: 8 נקודות לכל יום עודף."""
    sched = score(_selection_over_n_days(n_days), _days_only_prefs(4))
    assert sched.days_count == n_days
    assert sched.breakdown["days"] == pytest.approx(expected)
    assert sched.score == pytest.approx(expected)


def test_days_count_matches_days_used_for_a_split_lecture(courses):
    """הרצאה מפוצלת לשני ימים תורמת שני ימים לספירה."""
    lecture = group_of(courses, "61753", "21")  # ימים ב' ו-ד'
    sched = score(Selection([lecture]), Preferences(target_days=4))
    assert sched.days_count == 2
    assert sched.selection.days_used() == {2, 4}


def test_score_breakdown_has_exactly_the_four_components():
    """breakdown הוא חוזה: ארבעה מפתחות, וסכומם הוא הניקוד הסופי."""
    sched = score(_selection_over_n_days(5), Preferences(target_days=4))
    assert set(sched.breakdown) == {"lecturer", "days", "gaps", "compactness"}
    assert sched.score == pytest.approx(sum(sched.breakdown.values()))
    assert sched.breakdown["days"] <= 0.0
    assert sched.breakdown["gaps"] <= 0.0
    assert sched.breakdown["compactness"] <= 0.0


# ==========================================================================
# 8ב. חורים ודחיסות — שני הרכיבים הנותרים של הנוסחה, בערכים מספריים
#
# הבדיקות בסעיף 8 מאפסות את המשקולות האלה כדי לבודד רכיבים אחרים; כאן
# המשקולות דולקות, והערכים נבדקים במספרים — אחרת אפשר להחליף כל אחד
# משני הרכיבים ב-0.0 ואף בדיקה לא תרגיש.
# ==========================================================================
def _gappy_day() -> Selection:
    """יום א' עם חור של 1:45 באמצע: 08:30-10:15 ואז 12:00-13:45."""
    return Selection(
        [
            mk_group("90600", "1", KIND_LECTURE, "א", [(1, T0830, T1015)]),
            mk_group("90601", "2", KIND_TUTORIAL, "ב", [(1, T1200, T1345)]),
        ]
    )


def _tight_day() -> Selection:
    """אותן שתי שעתיים וחצי בדיוק, אבל צמודות: 08:30-10:15 ואז 10:15-12:00."""
    return Selection(
        [
            mk_group("90600", "1", KIND_LECTURE, "א", [(1, T0830, T1015)]),
            mk_group("90601", "2", KIND_TUTORIAL, "ב", [(1, T1015, T1200)]),
        ]
    )


def _short_day() -> Selection:
    """שיעור בודד: אותו יום, חצי מהזמן על הקמפוס, ובלי חורים גם כן."""
    return Selection([mk_group("90600", "1", KIND_LECTURE, "א", [(1, T0830, T1015)])])


def test_gaps_and_compactness_have_exact_numeric_values():
    """
    הנוסחה מ-SPEC סעיף 5: gaps = -w*(G/60) ו-compactness = -w*(S/60).
    G ו-S נמדדים בדקות והמשקולות מדברות בשעות — ולכן חלוקת ה-60 היא חלק
    מהחוזה, לא קישוט. משקולות ברירת המחדל: gaps=4.0, compactness=1.0.
    """
    sel = _gappy_day()
    assert sel.gap_minutes() == 105  # 10:15 -> 12:00
    assert sel.span_minutes() == 315  # 08:30 -> 13:45

    sched = score(sel, Preferences(target_days=6))  # יום אחד => אין קנס ימים
    assert sched.gap_minutes == 105
    assert sched.breakdown["lecturer"] == pytest.approx(0.0)
    assert sched.breakdown["days"] == pytest.approx(0.0)
    assert sched.breakdown["gaps"] == pytest.approx(-7.0)  # -4.0 * 105/60
    assert sched.breakdown["compactness"] == pytest.approx(-5.25)  # -1.0 * 315/60
    assert sched.score == pytest.approx(-12.25)


def test_gap_weight_alone_prefers_the_contiguous_day():
    """
    רק משקל החורים חי. לשתי המערכות אותן דקות לימוד בדיוק — ההבדל היחיד
    הוא החור, ולכן היום הרצוף חייב לקבל אפס והיום המחורר קנס.
    """
    prefs = Preferences(target_days=6, weights=weights(gaps=4.0))
    gappy = score(_gappy_day(), prefs)
    tight = score(_tight_day(), prefs)

    assert sum(m.duration() for m in _gappy_day().all_meetings()) == sum(
        m.duration() for m in _tight_day().all_meetings()
    )
    # אפס מדויק: אילו רכיב החורים היה מחושב מ-span הוא היה נותן כאן -14.0.
    assert tight.score == pytest.approx(0.0)
    assert gappy.score == pytest.approx(-7.0)  # -4.0 * 105/60
    assert gappy.score < tight.score


def test_compactness_measures_the_span_of_the_day_not_the_gaps():
    """
    רק משקל הדחיסות חי, ולשתי המערכות אפס חורים. אילו compactness היה
    מחושב מ-gap_minutes שתיהן היו מקבלות אותו ניקוד; ההבדל כאן הוא אך ורק
    אורך היום על הקמפוס (span) — 3:30 מול 1:45.
    """
    prefs = Preferences(target_days=6, weights=weights(compactness=1.0))
    long_day = score(_tight_day(), prefs)
    short_day = score(_short_day(), prefs)

    assert _tight_day().gap_minutes() == 0
    assert _short_day().gap_minutes() == 0
    assert _tight_day().span_minutes() == 210
    assert _short_day().span_minutes() == 105

    assert long_day.score == pytest.approx(-3.5)  # -1.0 * 210/60
    assert short_day.score == pytest.approx(-1.75)  # -1.0 * 105/60
    assert long_day.score < short_day.score


# ==========================================================================
# 9. אי-אפשרות — Infeasible, ולא רשימה ריקה
# ==========================================================================
def test_infeasible_is_raised_with_reasons_when_earliest_is_20_00(course_list):
    """
    'אף שיעור לפני 20:00' מוחק כל קבוצה ב-fixture. solve חייבת לזרוק Infeasible
    עם הסברים — ולא להחזיר [] בשקט.
    """
    prefs = Preferences(target_days=4, earliest=T2000)
    with pytest.raises(Infeasible) as excinfo:
        solve(course_list, prefs, top_n=5)

    reasons = reasons_of(excinfo.value)
    assert reasons, "Infeasible חייבת לשאת הסבר"
    assert all(isinstance(r, str) and r.strip() for r in reasons)
    joined = "\n".join(reasons)
    assert "20:00" in joined
    assert any(code in joined for code in EXPECTED_CODES)


def test_diagnose_reports_the_constraint_that_wiped_out_a_component(course_list):
    """האבחון מזהה את האילוץ עצמו (earliest) ולא רק אומר 'אין פתרון'."""
    reasons = diagnose_infeasibility(
        course_list, Preferences(target_days=4, earliest=T2000)
    )
    assert reasons
    joined = "\n".join(reasons)
    for code in sorted(EXPECTED_CODES):
        assert code in joined, f"האבחון לא הזכיר את {code}"
    assert "20:00" in joined
    assert "לפני" in joined, joined  # הניסוח של earliest


def test_diagnose_blames_latest_and_not_earliest(course_list):
    """
    latest=10:00 מוחק רכיבים שלמים. האבחון חייב לנקוב בשעה *ובאילוץ הנכון*:
    ניסוח של 'אחרי' (latest), ולא של 'לפני' (earliest) — שהוא אילוץ אחר לגמרי.
    """
    reasons = diagnose_infeasibility(course_list, Preferences(target_days=4, latest=T1000))
    assert reasons
    joined = "\n".join(reasons)
    assert "10:00" in joined, joined
    assert "אחרי" in joined, joined
    assert "לפני" not in joined, joined
    assert "61832" in joined, joined


def test_diagnose_blames_forbid_friday_when_a_whole_component_is_on_friday():
    """
    ב-fixture אין רכיב שכל קבוצותיו בשישי, ולכן בונים אחד: קורס ששתי
    ההרצאות שלו ביום ו'. עם forbid_friday האבחון חייב להאשים את יום שישי
    בשמו, ולא להסתפק ב'אין פתרון'.
    """
    friday_only = mk_course(
        "90700",
        [
            mk_group("90700", "1", KIND_LECTURE, LEVI, [(6, T0830, T1015)]),
            mk_group("90700", "2", KIND_LECTURE, MILLER, [(6, T1200, T1345)]),
        ],
    )
    reasons = diagnose_infeasibility(
        [friday_only], Preferences(target_days=4, forbid_friday=True)
    )
    assert reasons
    joined = "\n".join(reasons)
    assert "90700" in joined, joined
    assert "שישי" in joined, joined
    assert "נאסרו" in joined, joined


def test_diagnose_names_an_actual_conflicting_pair(course_list, courses):
    """
    חלון 10:15-12:00 בלבד משאיר את 61753 קבוצה 22 מול 61832 קבוצה 54 —
    שתיהן ביום ראשון 10:15-12:00. האבחון חייב לנקוב בזוג הזה בשמו.
    """
    prefs = Preferences(target_days=4, earliest=T1015, latest=T1200)

    lecture = group_of(courses, "61753", "22")
    tutorial = group_of(courses, "61832", "54")
    assert lecture.conflicts_with(tutorial), "הבדיקה מניחה שהזוג הזה באמת מתנגש"

    reasons = diagnose_infeasibility(course_list, prefs)
    assert reasons
    named = [r for r in reasons if "61753" in r and "61832" in r]
    assert named, "\n".join(reasons)
    assert any("22" in r and "54" in r for r in named), "\n".join(named)
    assert any("10:15" in r for r in named), "\n".join(named)

    with pytest.raises(Infeasible):
        solve(course_list, prefs, top_n=3)


@pytest.mark.parametrize(
    "prefs, must_explain",
    [
        (Preferences(target_days=4), False),
        (Preferences(target_days=4, earliest=T2000), True),
        (Preferences(target_days=4, forbid_friday=True, latest=T1200), True),
    ],
)
def test_diagnose_never_raises_and_always_returns_strings(course_list, prefs, must_explain):
    """
    diagnose_infeasibility היא פונקציית הסבר — היא לא זורקת, גם כשהכל תקין.
    וכשבאמת אין פתרון היא חייבת לומר משהו קונקרטי: רשימה ריקה אינה אבחון,
    ולכן בדיקת טיפוסים לבדה (שעוברת גם על []) לא מספיקה כאן.
    """
    reasons = diagnose_infeasibility(course_list, prefs)
    assert isinstance(reasons, list)
    assert all(isinstance(r, str) and r.strip() for r in reasons)

    if must_explain:
        assert reasons, "אין פתרון תחת ההעדפות האלה — האבחון חייב סיבה אחת לפחות"
        joined = "\n".join(reasons)
        assert any(code in joined for code in EXPECTED_CODES), joined


def test_diagnose_flags_a_course_with_no_groups_at_all(courses):
    """
    61753 מושאל מסמסטר 4 ועלול פשוט לא להיפתח. קורס בלי קבוצות חייב לקבל
    הסבר מפורש — לא כישלון סתום.
    """
    empty = Course(code="61753", name="אלגוריתמים", credits=5.0, groups=[], tied_with=[])
    subset = [empty, courses["61832"]]
    assert any("61753" in r for r in diagnose_infeasibility(subset, Preferences()))

    with pytest.raises(Infeasible):
        solve(subset, Preferences(target_days=4), top_n=1)


def test_a_two_day_week_is_impossible_for_this_fixture(all_selections, course_list):
    """
    ה-fixture בנוי בכוונה כך שאין פתרון של יומיים: ההרצאה של 61753 תמיד
    פרושה על שני ימים, ואף זוג ימים לא מכיל גם את 11069 וגם את ההרצאה
    של 61756. נבדק גם מבנית (על כל הפתרונות) וגם דרך solve.
    """
    assert min(len(sel.days_used()) for sel in all_selections) > 2

    # חסימת כל הימים חוץ מב' ו-ד' => אין מערכת בכלל.
    prefs = Preferences(
        target_days=2, blocked_windows=[(d, *FULL_DAY) for d in (1, 3, 5, 6)]
    )
    with pytest.raises(Infeasible) as excinfo:
        solve(course_list, prefs, top_n=3)
    reasons = reasons_of(excinfo.value)
    assert reasons

    # ...וההסבר חייב להאשים את החלונות החסומים בשמם. 62027 הוא המקרה הנקי:
    # שתי ההרצאות שלו נופלות מהחסימה, ולכן הרכיב כולו נמחק.
    blamed = [r for r in reasons if "62027" in r]
    assert blamed, "\n".join(reasons)
    assert any("חסומ" in r for r in blamed), "\n".join(blamed)
    assert any("ראשון" in r for r in blamed), "\n".join(blamed)


# ==========================================================================
# 10. solve — מקצה לקצה
# ==========================================================================
def test_solve_end_to_end_returns_a_schedule_of_four_days_or_fewer(course_list):
    """
    הבדיקה הגדולה: ההעדפות האמיתיות של הסטודנטית (יעד 4 ימים, משקולות
    מאוזנות) מחזירות מערכת חוקית שמשתמשת ב-4 ימים לכל היותר.
    """
    prefs = Preferences(
        target_days=4,
        weights={"lecturer": 10.0, "days": 8.0, "gaps": 4.0, "compactness": 1.0},
    )
    results = solve(course_list, prefs, top_n=5)

    assert results, "solve חייבת להחזיר לפחות מערכת אחת"
    assert len(results) <= 5

    best = results[0]
    assert best.days_count <= 4
    assert best.selection.is_feasible()
    assert len(best.selection.groups) == 11
    assert best.selection.course_codes() == EXPECTED_CODES
    assert best.days_count == len(best.selection.days_used())
    assert best.gap_minutes == best.selection.gap_minutes()
    assert best.breakdown["days"] == pytest.approx(0.0)  # 4 ימים = בדיוק היעד


def test_solve_returns_results_sorted_by_score_descending(course_list):
    """התוצאות ממוינות מהטובה לפחות טובה, ואף אחת לא חורגת מהמבנה הנדרש."""
    results = solve(course_list, Preferences(target_days=4), top_n=5)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    for r in results:
        assert r.score == pytest.approx(sum(r.breakdown.values()))
        assert r.selection.is_feasible()
        assert r.selection.course_codes() == EXPECTED_CODES


def test_solve_top_n_is_honoured(course_list):
    """top_n שולט על אורך הרשימה, וההתחלה זהה לרשימה ארוכה יותר."""
    prefs = Preferences(target_days=4)
    one = solve(course_list, prefs, top_n=1)
    three = solve(course_list, prefs, top_n=3)
    assert len(one) == 1
    assert len(three) == 3
    assert one[0].score == pytest.approx(three[0].score)
    assert ids_of(one[0].selection) == ids_of(three[0].selection)


def test_solve_is_deterministic_regardless_of_input_order(course_list):
    """
    אותה קלט -> אותה תוצאה, גם אם סדר הקורסים ברשימה מתהפך.
    (זו הסיבה שאף בדיקה בקובץ הזה לא נשענת על סדר של dict.)
    """
    prefs = Preferences(target_days=4)
    first = solve(course_list, prefs, top_n=3)
    second = solve(list(reversed(course_list)), prefs, top_n=3)
    assert [r.score for r in first] == pytest.approx([r.score for r in second])
    assert ids_of(first[0].selection) == ids_of(second[0].selection)


def test_the_best_schedule_is_the_tight_zero_gap_four_day_week(course_list):
    """
    ה-fixture תוכנן כך שקיימת מערכת אידיאלית: 4 ימים (א'-ד'), אפס חורים,
    שרשראות נוגעות 08:30-10:15-12:00. זו חייבת להיות המנצחת.
    """
    best = solve(course_list, Preferences(target_days=4), top_n=1)[0]
    assert best.days_count == 4
    assert best.gap_minutes == 0
    assert best.selection.days_used() == {1, 2, 3, 4}
    # אפס חורים => אורך היום הכולל שווה בדיוק לסך דקות הלימוד.
    total_teaching = sum(m.duration() for m in best.selection.all_meetings())
    assert best.selection.span_minutes() == total_teaching


def test_solve_still_works_when_friday_is_forbidden(course_list):
    """ההעדפה forbid_friday לא שוברת את הפתרון — היא רק מצמצמת אותו."""
    best = solve(course_list, Preferences(target_days=4, forbid_friday=True), top_n=1)[0]
    assert 6 not in best.selection.days_used()
    assert best.days_count <= 4
