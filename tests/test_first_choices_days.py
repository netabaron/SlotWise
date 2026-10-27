"""‏``first_choices_days`` (N) ו-``scheduler.min_days(fixed=)`` — 2026-10-27.

N הוא מספר הימים הקטן ביותר של מערכת שבה **כל** סוג מדורג מלמד המרצה הראשון
שלו. שבב "+יום" מעלה את היעד ל-N, והטענה שהוא נשען עליה היא שהראשונה החדשה
כוללת את כולם — מכוח הסדר (ימים מעל היעד, ואז המרצים), לא מכוח מזל. הבדיקות
כאן:

1. ‏``min_days(fixed=)`` שווה למנייה מלאה מסוננת, ובלי ``fixed`` לא השתנה דבר;
2. ‏N שווה לחיפוש בלתי תלוי, בשם המרצה ולא במזהי קבוצות;
3. הלחיצה (יעד N) מחזירה כל מרצה בדירוג 1, גם כשהראשונה החמיצה שניים;
4. ‏N חסר (``None``) בכל המקרים שבהם אין מה להציע.

הכול על הקטלוג הקפוא, ‏allow_network=False.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src.web import api  # noqa: E402

#: ‏המודול ש-api עצמו מייבא — לא ``src.scheduler``, שהוא עותק נפרד עם שעון משלו.
sch = api.scheduler_mod

TERM = "א"
#: ‏הנדסת תוכנה שנה ב׳, סמסטר א׳ — המומלצים.
SOFTWARE_S3 = ["11129", "61739", "61774", "61778", "61911"]
LECTURER = 'ד"ר דנטה-בירון אילה'
SMALL = ["11069", "61756", "61757", "62027", "61759", "61832"]


@pytest.fixture(scope="module")
def app():
    return api.create_app({"allow_network": False}, serve_ui=False)


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


def _built(app, codes):
    with app.app_context():
        built, _p, _m = api._build_courses(codes, semester=TERM)  # noqa: SLF001
    return [c for c in built if c.groups]


def _optional(built):
    return {c.code: {k: False for k in c.kinds()} for c in built}


def _prefs(built, ranked=None, target=6):
    prefs, _ = api._make_preferences(  # noqa: SLF001
        target_days=target, attendance=_optional(built), allow_soft_conflicts=True,
        preferred_lecturers=api._clean_ranked(ranked or {}),  # noqa: SLF001
    )
    prefs.preferred_lecturers = sch.rankings_by_kind(built, prefs.preferred_lecturers)
    return prefs


def _brute_min_days(built, prefs, keep):
    """המינימום על פני מנייה מלאה, רק בחירות ש-``keep(selection)`` מקבל."""
    best = None
    for sel in sch.enumerate_selections(built, prefs, limit=5_000_000):
        if keep(sel):
            days = len(sel.days_used())
            best = days if best is None else min(best, days)
    return best


def _all_first(prefs):
    """‏האם בבחירה כל סוג מדורג מלמד המרצה הראשון — לפי השם."""
    wanted = {
        (code, kind): sch._norm_name(names[0])  # noqa: SLF001
        for code, by_kind in prefs.preferred_lecturers.items()
        for kind, names in by_kind.items() if names
    }

    def keep(sel):
        for g in sel.groups:
            want = wanted.get((g.course_code, g.kind))
            if want is not None and sch._norm_name(g.lecturer) != want:  # noqa: SLF001
                return False
        return True
    return keep


def _post(client, codes, *, target, ranked, attendance):
    res = client.post("/api/solve", json={
        "codes": codes, "semester": TERM, "target_days": target,
        "ranked": ranked, "attendance": attendance,
    })
    assert res.status_code == 200
    return res.get_json()


# ==========================================================================
# 1. ‏min_days(fixed=)
# ==========================================================================
def test_without_fixed_min_days_is_the_full_enumeration(app):
    for codes in (SMALL, SOFTWARE_S3):
        built = _built(app, codes)
        prefs = _prefs(built)
        want = _brute_min_days(built, prefs, lambda s: True)
        assert sch.min_days(built, prefs) == want
        assert sch.min_days(built, prefs, fixed=None) == want
        assert sch.min_days(built, prefs, fixed={}) == want


def test_fixed_equals_a_filtered_enumeration_for_every_group(app):
    built = _built(app, SOFTWARE_S3)
    prefs = _prefs(built)
    checked = 0
    for course in built:
        for kind in course.kinds():
            for group in course.groups_of(kind):
                gid = str(group.group_id)
                want = _brute_min_days(
                    built, prefs,
                    lambda s, c=course.code, k=kind, g=gid: any(
                        x.course_code == c and x.kind == k and str(x.group_id) == g for x in s.groups),
                )
                # מזהה יחיד, ואוסף שמכיל רק אותו — אותה תשובה.
                assert sch.min_days(built, prefs, fixed={course.code: {kind: gid}}) == want, (course.code, kind, gid)
                assert sch.min_days(built, prefs, fixed={course.code: {kind: {gid}}}) == want
                checked += 1
    assert checked > 10, checked


def test_fixed_on_a_missing_slot_or_group_is_none(app):
    built = _built(app, SOFTWARE_S3)
    prefs = _prefs(built)
    assert sch.min_days(built, prefs, fixed={"61911": {"מעבדה": "1"}}) is None
    assert sch.min_days(built, prefs, fixed={"99999": {"הרצאה": "1"}}) is None
    assert sch.min_days(built, prefs, fixed={"61911": {"הרצאה": {"no-such-group"}}}) is None


# ==========================================================================
# 2. ‏N עצמו
# ==========================================================================
def _every_lecturer(built, kinds=("הרצאה", 'שו"ת', "תרגול")):
    for course in built:
        for kind in course.kinds():
            if kind not in kinds:
                continue
            names = []
            for g in course.groups_of(kind):
                if g.lecturer and g.meetings and g.lecturer not in names:
                    names.append(g.lecturer)
            if len(names) >= 2:
                for name in names:
                    yield course.code, kind, name


def test_n_equals_an_independent_search_for_every_single_ranking(app):
    built = _built(app, SOFTWARE_S3)
    seen = 0
    for code, kind, name in _every_lecturer(built):
        prefs = _prefs(built, {code: {kind: [name]}}, target=3)
        want = _brute_min_days(built, prefs, _all_first(prefs))
        assert api._first_choices_days(built, prefs) == want, (code, kind, name)  # noqa: SLF001
        seen += 1
    assert seen >= 4, seen


def test_the_known_case_needs_four_days(app):
    built = _built(app, SOFTWARE_S3)
    prefs = _prefs(built, {"61911": {"הרצאה": [LECTURER]}}, target=3)
    top = sch.solve(built, prefs, top_n=5)[0]
    assert top.days_count == 3
    assert [m["name"] for m in sch.lecturer_misses_of(top)] == [LECTURER]
    assert api._first_choices_days(built, prefs) == 4  # noqa: SLF001


def test_the_response_carries_n_and_the_tap_brings_every_first_choice_back(app, client):
    built = _built(app, SOFTWARE_S3)
    ranked = {"61911": {"הרצאה": [LECTURER]}}
    data = _post(client, SOFTWARE_S3, target=3, ranked=ranked, attendance=_optional(built))
    assert data["first_choices_days"] == 4
    assert data["schedules"][0]["lecturer_misses"], "המקרה צריך החטאה בראשונה"
    after = _post(client, SOFTWARE_S3, target=4, ranked=ranked, attendance=_optional(built))
    top = after["schedules"][0]
    assert top["lecturer_misses"] == [] and top["days_count"] == 4, top["lecturer_ranks"]
    assert after["first_choices_days"] == 4


@pytest.mark.parametrize("target", [2, 3])
def test_the_tap_is_guaranteed_for_every_pair_of_rankings(app, target):
    """הרצאה בקורס אחד ותרגול באחר, כל הזוגות: ביעד N הראשונה כוללת את שניהם —
    גם כשהראשונה החמיצה את שניהם (ואז N יכול להיות יותר מיום אחד מעליה)."""
    built = _built(app, SOFTWARE_S3)
    lectures = [x for x in _every_lecturer(built, ("הרצאה", 'שו"ת'))]
    tutorials = [x for x in _every_lecturer(built, ("תרגול",))]
    tried = misses = double = 0
    for a in lectures:
        for b in tutorials:
            if a[0] == b[0]:
                continue
            ranked = {a[0]: {a[1]: [a[2]]}, b[0]: {b[1]: [b[2]]}}
            prefs = _prefs(built, ranked, target=target)
            try:
                top = sch.solve(built, prefs, top_n=5)[0]
            except sch.Infeasible:
                continue
            tried += 1
            n = api._first_choices_days(built, prefs)  # noqa: SLF001
            assert n == _brute_min_days(built, prefs, _all_first(prefs)), (a, b)
            missed = sch.lecturer_misses_of(top)
            if not missed:
                continue
            misses += 1
            double += len(missed) == 2
            assert n is not None and n > top.days_count, (a, b, n, top.days_count)
            again = sch.solve(built, dataclasses.replace(prefs, target_days=max(n, target)), top_n=1)[0]
            assert sch.lecturer_misses_of(again) == [], (a, b, n)
            assert again.days_count == max(n, target) or again.days_count <= n, (a, b)
    assert tried and misses, (tried, misses)


# ==========================================================================
# 3. מתי אין N
# ==========================================================================
def test_n_is_none_without_a_ranking(app):
    built = _built(app, SOFTWARE_S3)
    assert api._first_choices_days(built, _prefs(built, {}, target=3)) is None  # noqa: SLF001


def test_n_is_none_when_the_first_choice_teaches_nothing_in_that_kind(app):
    built = _built(app, SOFTWARE_S3)
    prefs = _prefs(built, {"61911": {"הרצאה": ["מרצה שאינו בקטלוג"]}}, target=3)
    assert api._first_choices_days(built, prefs) is None  # noqa: SLF001


def test_n_is_none_for_a_dead_ranking(app):
    """דירוג ישן: כל קבוצות המרצה נחסמו בחלון — אין מערכת שבה הוא מלמד."""
    built = _built(app, SOFTWARE_S3)
    prefs = _prefs(built, {"61911": {"הרצאה": [LECTURER]}}, target=3)
    course = next(c for c in built if c.code == "61911")
    windows = [
        (m.day, m.start, m.end)
        for g in course.groups_of("הרצאה") if sch._norm_name(g.lecturer) == sch._norm_name(LECTURER)  # noqa: SLF001
        for m in g.meetings
    ]
    assert windows
    blocked, _ = api._make_preferences(  # noqa: SLF001
        target_days=3, attendance=_optional(built), allow_soft_conflicts=True,
        preferred_lecturers=prefs.preferred_lecturers, blocked_windows=windows,
    )
    blocked.preferred_lecturers = prefs.preferred_lecturers
    assert api._first_choices_days(built, blocked) is None  # noqa: SLF001


def test_n_is_none_when_the_deadline_has_passed(app, monkeypatch):
    built = _built(app, SOFTWARE_S3)
    prefs = _prefs(built, {"61911": {"הרצאה": [LECTURER]}}, target=3)
    monkeypatch.setattr(sch, "_CLOCK_EVERY", 1)  # השעון נבדק כבר בצומת הראשון
    # ‏מועד שכבר עבר: ב-Windows ‏time.monotonic() מתקדם בקפיצות של ~15ms,
    # ולכן ב-0.0 חיפוש קטן היה מסתיים לפני שהשעון זז.
    with sch.time_budget(-1.0):
        assert api._first_choices_days(built, prefs) is None  # noqa: SLF001
        assert sch.time_budget_expired() is True


def test_the_response_has_the_field_when_nothing_is_ranked(app, client):
    built = _built(app, SOFTWARE_S3)
    data = _post(client, SOFTWARE_S3, target=3, ranked={}, attendance=_optional(built))
    assert data["schedules"] and data["first_choices_days"] is None


# ==========================================================================
# 4. ‏first_choices_reason_day: "צריך יום לימוד נוסף" רק כשזה נכון על החסרים
# ==========================================================================
#: ‏הנדסת חשמל שנה א׳ סמסטר א׳, המומלצים, וחובת הנוכחות כמו שהדף שולח אותה.
ELECTRICAL_S1 = ["11002", "11004", "31230", "31511", "251961"]
ELECTRICAL_ATT = {
    "11002": {"הרצאה": False, "תרגול": False}, "11004": {"הרצאה": False, "תרגול": False},
    "31230": {"הרצאה": False, "תרגול": False}, "31511": {"הרצאה": False, "תרגול": False},
    "251961": {'שו"ת': False},
}
GOLDWARD = 'ד"ר גולדוורד אלכסנדר'
ZAMOSTIANO = "גב' זמוסטיאנו יאנה"
TRADE_OFF = {"11002": {"הרצאה": [GOLDWARD]}, "31511": {"תרגול": [ZAMOSTIANO]}}


def _rank1_ids(built, code, kind, name):
    course = next(c for c in built if c.code == code)
    return {str(g.group_id) for g in course.groups_of(kind)
            if sch._norm_name(g.lecturer) == sch._norm_name(name)}  # noqa: SLF001


def test_a_trade_off_gets_no_reason(app, client):
    """‏גב' זמוסטיאנו נכנסת ב-3 ימים לבדה — אבל רק בוויתור על ד"ר גולדוורד, וההרצאה
    גוברת בשוויון. "צריך יום לימוד נוסף" היה שקר עליה; ‏N=4 מחזיר את שניהם."""
    data = _post(client, ELECTRICAL_S1, target=3, ranked=TRADE_OFF, attendance=ELECTRICAL_ATT)
    assert data["first_choices_days"] == 4
    tops = data["schedules"]
    assert all([m["name"] for m in s["lecturer_misses"]] == [ZAMOSTIANO] for s in tops), tops
    assert all(s["days_count"] == 3 for s in tops)
    assert [s["first_choices_reason_day"] for s in tops] == [False] * len(tops)
    # ‏לבדה היא אכן נכנסת ב-3 ימים; עם ד"ר גולדוורד צריך 4.
    built = _built(app, ELECTRICAL_S1)
    prefs, _ = api._make_preferences(  # noqa: SLF001
        target_days=3, attendance=ELECTRICAL_ATT, allow_soft_conflicts=True,
        preferred_lecturers=api._clean_ranked(TRADE_OFF),  # noqa: SLF001
    )
    prefs.preferred_lecturers = sch.rankings_by_kind(built, prefs.preferred_lecturers)
    her = {"31511": {"תרגול": _rank1_ids(built, "31511", "תרגול", ZAMOSTIANO)}}
    both = {**her, "11002": {"הרצאה": _rank1_ids(built, "11002", "הרצאה", GOLDWARD)}}
    assert sch.min_days(built, prefs, fixed=her) == 3
    assert sch.min_days(built, prefs, fixed=both) == 4
    # ‏והכפתור עדיין נכון: ביעד 4 שניהם בפנים.
    after = _post(client, ELECTRICAL_S1, target=4, ranked=TRADE_OFF, attendance=ELECTRICAL_ATT)
    assert after["schedules"][0]["lecturer_misses"] == []


def test_a_real_extra_day_gets_the_reason(client, app):
    built = _built(app, SOFTWARE_S3)
    data = _post(client, SOFTWARE_S3, target=3, ranked={"61911": {"הרצאה": [LECTURER]}},
                 attendance=_optional(built))
    top = data["schedules"][0]
    assert top["lecturer_misses"] and top["first_choices_reason_day"] is True, top


def test_no_reason_field_value_where_no_line_is_shown(client, app):
    built = _built(app, SOFTWARE_S3)
    data = _post(client, SOFTWARE_S3, target=3, ranked={}, attendance=_optional(built))
    assert all(s["first_choices_reason_day"] is None for s in data["schedules"])


@pytest.mark.parametrize("target", [2, 3])
def test_the_reason_matches_its_definition_on_every_pair(app, target):
    """לכל זוג דירוגים ולכל מערכת שהשורה מוצגת בה: הסיבה נאמרת אם ורק אם כל
    מרצה שחסר, לבדו, צריך יותר ימים ממה שיש — וכל החסרים יחד צריכים N. נבדק
    מול מנייה מלאה, בשמות המרצים ולא במזהי קבוצות."""
    built = _built(app, SOFTWARE_S3)
    lectures = list(_every_lecturer(built, ("הרצאה", 'שו"ת')))
    tutorials = list(_every_lecturer(built, ("תרגול",)))
    shown = said = 0
    for a in lectures:
        for b in tutorials:
            if a[0] == b[0]:
                continue
            ranked = {a[0]: {a[1]: [a[2]]}, b[0]: {b[1]: [b[2]]}}
            prefs = _prefs(built, ranked, target=target)
            try:
                found = sch.solve(built, prefs, top_n=5)
            except sch.Infeasible:
                continue
            n = api._first_choices_days(built, prefs)  # noqa: SLF001
            got = api._first_choices_reasons(built, prefs, found, n, target)  # noqa: SLF001
            for s, reason in zip(found, got):
                misses = sch.lecturer_misses_of(s)
                if not misses or n is None or not (n > s.days_count and n > target):
                    assert reason is None
                    continue
                shown += 1

                def first(sel, keys):
                    for g in sel.groups:
                        for m in misses:
                            if (g.course_code, g.kind) == (m["code"], m["kind"]) and (m["code"], m["kind"]) in keys:
                                if sch._norm_name(g.lecturer) != sch._norm_name(m["name"]):  # noqa: SLF001
                                    return False
                    return True
                keys = [(m["code"], m["kind"]) for m in misses]
                alone = [_brute_min_days(built, prefs, lambda sel, k=k: first(sel, {k})) for k in keys]
                together = _brute_min_days(built, prefs, lambda sel: first(sel, set(keys)))
                want = all(d is not None and d > s.days_count for d in alone) and together is not None and together >= n
                assert reason is want, (a, b, s.days_count, n, alone, together)
                said += reason
    # ‏שני המקרים קורים: שורה עם הסיבה, ושורה בלעדיה (קרמר בהרצאה וגבינט בתרגול).
    assert 0 < said < shown, (said, shown)


def test_no_reason_when_the_deadline_has_passed(app, monkeypatch):
    built = _built(app, SOFTWARE_S3)
    prefs = _prefs(built, {"61911": {"הרצאה": [LECTURER]}}, target=3)
    found = sch.solve(built, prefs, top_n=5)
    n = api._first_choices_days(built, prefs)  # noqa: SLF001
    assert n == 4
    monkeypatch.setattr(sch, "_CLOCK_EVERY", 1)
    with sch.time_budget(-1.0):
        got = api._first_choices_reasons(built, prefs, found, n, 3)  # noqa: SLF001
    assert got == [None] * len(found), got
