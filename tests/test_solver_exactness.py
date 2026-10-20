# -*- coding: utf-8 -*-
"""הפותר המהיר מחזיר **בדיוק** את מה שמנייה מלאה מחזירה.

‏2026-10-20 (docs/DESIGN.md → "Solver: exact pruned search"): ‏``solve()``
גוזם ענפים שאינם יכולים לנצח את המקום ה-``top_n``, ה-viability מחפש פתרון
אחד עם הקבוצה קבועה בסלוט שלה, והספירה נעצרת במכסה. כל אחד מהשלושה
נועד לשנות **רק את המהירות**. הקובץ הזה מחזיק את ההבטחה הזו מול מקור
אמת שאינו תלוי בקוד שהשתנה: מנייה מלאה, מועתקת מהאלגוריתם כפי שהיה לפני
השינוי (``_reference_leaves``), שמנקדת כל עלה ב-``scheduler.score`` וממיינת
ב-``scheduler._sort_key`` — שתי הפונקציות שאינן משתנות.

לכל בחירה × העדפות נבדקים:
  * ‏``scheduler.solve``: אותן מערכות, באותו סדר, עם אותו ניקוד ופירוק בדיוק;
  * ‏``/api/solve``: אותן מערכות ואותו סדר, אותו ``min_days``, אותה viability
    לכל קבוצה (כולל הסיבה), וספירה שווה למנייה — או למכסה, עם דגל.

הבחירות קטנות בכוונה: מקור האמת הוא מנייה ממצה, והוא חייב לסיים.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src.web import api  # noqa: E402

sch = api.scheduler_mod  # אותו מודול שהשרת משתמש בו, לא עותק שני שלו
Selection = api.models.Selection

TERM = "א"

# ==========================================================================
# הבחירות — מהקטלוג הקפוא, סמסטר א'
# ==========================================================================
#: מעין שנה א': קורסי השירות הגדולים (6 הרצאות × 10 תרגולים), בקטן.
FIRST_YEAR_LIKE = {
    "algebra+calculus": ["11001", "11003"],
    "civil-y1-slice": ["11003", "41079", "421110"],
    "ee-y1-slice": ["11002", "31230", "31511"],
    "mech-y1-slice": ["22112", "251961", "11001"],
    "ie-y1-slice": ["11179", "51104", "61903"],
}
#: סמסטרים מאוחרים, כפי שהדף מסמן אותם.
LATER = {
    "civil-y2": ["421109", "421210", "421211", "421217", "11133"],
    "ee-y3": ["31442", "31521", "31711", "31910", "31999", "31403"],
    "sw-y3": ["11069", "61756", "61757", "62027", "61759", "61832"],
    "is-y2": ["61774", "61739", "61778", "61832", "61911"],
    "mech-y2": ["11212", "22114", "22310", "11061", "11133", "22415"],
}
SELECTIONS = {**FIRST_YEAR_LIKE, **LATER}


# ==========================================================================
# ההעדפות — כל ציר שהגיזום נוגע בו
# ==========================================================================
def _lecturers(course, kind):
    """המרצים של רכיב, בסדר הקבוצות, בלי כפילויות."""
    out = []
    for g in course.groups_of(kind):
        if g.lecturer and g.lecturer not in out:
            out.append(g.lecturer)
    return out


def _ranked_per_kind(built):
    """דירוג לכל סוג בשני הקורסים הראשונים: האחרון ברשימה ראשון, ושם שאינו מלמד."""
    ranked = {}
    for course in built[:2]:
        per = {}
        for kind in course.kinds():
            names = _lecturers(course, kind)
            if names:
                per[kind] = [names[-1], names[0], "מרצה שאינו בקטלוג"][: 2 + (len(names) == 1)]
        if per:
            ranked[course.code] = per
    return ranked


def _ranked_flat(built):
    """הצורה השטוחה הישנה ‏{קוד: [שמות]} — לקורס האחרון בבחירה."""
    course = built[-1]
    names = []
    for kind in course.kinds():
        for name in _lecturers(course, kind):
            if name not in names:
                names.append(name)
    return {course.code: list(reversed(names))[:3]} if names else {}


def _optional(built, kinds=None):
    """‏attendance=False לכל רכיב (או רק לסוגים שב-``kinds``) — כמו ברירת המחדל של הדף."""
    out = {}
    for course in built:
        for kind in course.kinds():
            if kinds is None or kind in kinds:
                out.setdefault(course.code, {})[kind] = False
    return out


#: ‏(שם, פונקציה שבונה גוף בקשה מהקורסים). כל גוף מכסה ציר אחד לפחות.
VARIANTS = [
    ("required", lambda b: {"target_days": 6}),
    ("page-default", lambda b: {"target_days": 6, "attendance": _optional(b)}),
    ("lectures-optional-target4", lambda b: {"target_days": 4,
                                             "attendance": _optional(b, {"הרצאה"})}),
    ("ranked-per-kind-target3", lambda b: {"target_days": 3, "attendance": _optional(b),
                                           "ranked": _ranked_per_kind(b)}),
    ("ranked-flat-blocked-friday", lambda b: {"target_days": 4, "ranked": _ranked_flat(b),
                                              "blocked": [{"day": 2, "start": "08:00", "end": "12:00"}],
                                              "forbid_friday": True}),
    ("window-weights-top12", lambda b: {"target_days": 5, "attendance": _optional(b),
                                        "earliest": "08:30", "latest": "20:00",
                                        "weights": {"gaps": 0.0, "compactness": 2.5,
                                                    "late_finish": 0.0},
                                        "top_n": 12}),
    ("negative-weight", lambda b: {"target_days": 6, "attendance": _optional(b),
                                   "weights": {"compactness": -1.0, "soft_conflict": 0.5}}),
    ("ranked-top1-target2", lambda b: {"target_days": 2, "ranked": _ranked_per_kind(b),
                                       "top_n": 1}),
]


# ==========================================================================
# מקור האמת — המנייה המלאה כפי שהייתה
# ==========================================================================
def _reference_leaves(courses, prefs):
    """כל בחירה שלמה ותקינה, בדיוק כמו ``enumerate_selections`` עד 2026-10-20.

    אותם סלוטים באותו סדר (``_build_slots``), אותו כלל זוגי (``_pair_ok``),
    בלי מכסת צמתים ובלי גיזום מעבר לו.
    """
    slots = sch._build_slots(courses, prefs)  # noqa: SLF001
    kind_of = sch._kind_index(courses)  # noqa: SLF001
    out, chosen = [], []

    def bt(depth):
        if depth == len(slots):
            out.append(Selection(list(chosen)))
            return
        for cand in slots[depth].candidates:
            if any(not sch._pair_ok(a, cand, kind_of, prefs) for a in chosen):  # noqa: SLF001
                continue
            chosen.append(cand)
            bt(depth + 1)
            chosen.pop()

    bt(0)
    return out


def _reference(courses, prefs, top_n):
    """‏(top_n מנוקדות וממוינות, כל העלים) — ניקוד ומיון של המנוע עצמו."""
    prefs = replace(
        prefs, preferred_lecturers=sch.rankings_by_kind(courses, prefs.preferred_lecturers)
    )
    leaves = _reference_leaves(courses, prefs)
    scored = sorted((sch.score(s, prefs) for s in leaves), key=sch._sort_key)  # noqa: SLF001
    return scored[: max(1, int(top_n))], leaves, prefs


def _picks(selection):
    return sorted((g.course_code, g.kind, g.group_id) for g in selection.groups)


def _fingerprint(sched):
    """כל מה שהסטודנט/ית רואים ממערכת אחת, כולל הניקוד המדויק."""
    return (
        _picks(sched.selection),
        sched.score,
        dict(sched.breakdown),
        sched.days_count,
        sched.gap_minutes,
        sch.days_over_target_of(sched),
        sch.soft_conflicts_of(sched),
        tuple(getattr(sched, "lecturer_key", ()) or ()),
        sched.lecturer_hits,
        sched.lecturer_total,
    )


# ==========================================================================
# התשתית
# ==========================================================================
@pytest.fixture(scope="module")
def app():
    return api.create_app({"allow_network": False}, serve_ui=False)


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


def _prefs_like_the_api(body, built):
    """אותן העדפות שהשרת בונה מאותו גוף — דרך אותם מנקים."""
    prefs, unsupported = api._make_preferences(  # noqa: SLF001
        target_days=int(body.get("target_days", 4)),
        preferred_lecturers=api._clean_ranked(body.get("ranked")),  # noqa: SLF001
        blocked_windows=api._clean_blocked(body.get("blocked")),  # noqa: SLF001
        earliest=api._as_minutes(body.get("earliest"), field="earliest", default=0),  # noqa: SLF001
        latest=api._as_minutes(body.get("latest"), field="latest",  # noqa: SLF001
                               default=api.MINUTES_IN_DAY),
        weights=api._clean_weights(body.get("weights")),  # noqa: SLF001
        forbid_friday=bool(body.get("forbid_friday", False)),
        attendance=api._clean_attendance(body.get("attendance")),  # noqa: SLF001
        allow_soft_conflicts=True,
    )
    assert not unsupported
    return prefs


CASES = [
    pytest.param(name, variant, id=f"{name}-{vname}")
    for name in SELECTIONS
    for vname, variant in VARIANTS
]


# ==========================================================================
# 1. ‏scheduler.solve — אותן מערכות, אותו סדר, אותו ניקוד
# ==========================================================================
@pytest.mark.parametrize("name,variant", CASES)
def test_solve_matches_full_enumeration(app, name, variant):
    codes = SELECTIONS[name]
    with app.app_context():
        built, _problems, _metas = api._build_courses(codes, semester=TERM)  # noqa: SLF001
    assert [c.code for c in built] == codes, "קוד חסר בקטלוג הקפוא — הבחירה אינה מה שנבדק"
    body = variant(built)
    top_n = int(body.get("top_n", 5))
    prefs = _prefs_like_the_api(body, built)

    expected, leaves, _ = _reference(built, prefs, top_n)
    if not leaves:
        with pytest.raises(sch.Infeasible):
            sch.solve(built, prefs, top_n=top_n)
        return

    got = sch.solve(built, prefs, top_n=top_n)
    assert [_fingerprint(s) for s in got] == [_fingerprint(s) for s in expected]
    assert not any(getattr(s, "truncated", False) for s in got)


# ==========================================================================
# 2. ‏/api/solve — מערכות, ימים, viability וספירה
# ==========================================================================
@pytest.mark.parametrize("name,variant", CASES)
def test_api_solve_matches_full_enumeration(app, client, name, variant):
    codes = SELECTIONS[name]
    with app.app_context():
        built, _problems, _metas = api._build_courses(codes, semester=TERM)  # noqa: SLF001
    body = variant(built)
    top_n = int(body.get("top_n", 5))
    prefs = _prefs_like_the_api(body, built)
    expected, leaves, ref_prefs = _reference(built, prefs, top_n)

    res = client.post("/api/solve", json={"codes": codes, "semester": TERM, **body})
    assert res.status_code == 200, res.get_data(as_text=True)
    data = res.get_json()

    # --- המערכות
    got = [sorted((p["code"], p["kind"], p["group_id"]) for p in s["picks"])
           for s in data["schedules"]]
    want = [_picks(s.selection) for s in expected] if leaves else []
    assert got == want
    assert [s["score"] for s in data["schedules"]] == [
        round(float(s.score), 4) for s in (expected if leaves else [])
    ]

    # --- מינימום הימים והיעד
    ref_min = min((len(s.days_used()) for s in leaves), default=None)
    assert data["min_days"] == ref_min
    assert data["target_reachable"] == (ref_min is not None and ref_min <= body["target_days"])

    # --- הספירה: מדויקת עד המכסה, ומעליה המכסה עם דגל
    cap = getattr(api, "FEASIBLE_COUNT_CAP", None)
    if cap is None or len(leaves) <= cap:
        assert data["feasible_count"] == len(leaves)
        assert not data.get("feasible_count_capped", False)
    else:
        assert data["feasible_count"] == cap
        assert data["feasible_count_capped"] is True
    assert data["counts_truncated"] is False

    # --- viability: לכל קבוצה, האם היא באחד העלים, ואותה סיבה כשלא
    assert data["viability_skipped"] is False and data["viability_truncated"] is False
    alive = {(g.course_code, g.kind, g.group_id) for s in leaves for g in s.groups}
    expected_via = {}
    for course in built:
        for g in course.groups:
            key = (course.code, g.kind, g.group_id)
            entry = ({"ok": True} if key in alive
                     else {"ok": False, "reason": api._dead_end_reason(g, ref_prefs)})  # noqa: SLF001
            expected_via.setdefault(course.code, {}).setdefault(g.kind, {})[g.group_id] = entry
    assert data["viability"] == expected_via

