# -*- coding: utf-8 -*-
"""חיפוש ה-top_n גוזם גם בשוויון — והתשובה עדיין זהה למנייה מלאה.

‏2026-10-24: עד היום ``_search_best`` גזם רק לפי ארבע הרמות הראשונות של
‏``_sort_key``. כשלאף קבוצה אין מועד (סמסטר ב' לפני שהידיעון קבע שעות), כל
העלים שווים בארבע — ובחירת ברירת המחדל של חשמל שנה ב' (5,760,000 עלים)
רצה עד ``SOLVE_DEADLINE_S``. עכשיו, כשבסלוטים שנותרו לאף מועמד אין מפגש,
החיפוש ממשיך לימים, לחורים, לאורך היום ול-``_stable_key``.

המלכודת: ‏``_stable_key`` הוא ``"|".join(sorted(...))``, ולכן ``"~10|"`` קודם
ל-``"~1|"`` — אבל במקום האחרון, בלי ``|`` אחריו, ``"~1"`` קודם ל-``"~10"``.
הבחירות כאן מעמידות מזהים כאלה זה לצד זה בשני המקומות, ומערבבות קבוצות בלי
מועד עם קבוצות עם מועד — גם בתוך אותו סלוט.

מקור האמת: מנייה מלאה (אותם סלוטים ואותו ``_pair_ok``), ניקוד ב-``score``
ומיון ב-``_sort_key``, כמו ב-``tests/test_solver_exactness.py``. משווים את
המערכות, את סדרן, את הניקוד ואת המפתח המלא של כל אחת.

מסד ריק: הקבוצות באות מהקטלוג הקפוא בלבד, בכל סמסטר שמבקשים.
"""

from __future__ import annotations

import copy
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src.web import api  # noqa: E402

sch = api.scheduler_mod
models = api.models

LECTURE, PRACTICE = "הרצאה", "תרגול"


# ==========================================================================
# הבחירות
# ==========================================================================
def _term(app, term, codes):
    with app.app_context():
        built, _problems, _metas = api._build_courses(codes, semester=term)  # noqa: SLF001
    assert [c.code for c in built] == codes, "קוד חסר בקטלוג הקפוא — הבחירה אינה מה שנבדק"
    return built


def _untimed(app, term, codes):
    built = _term(app, term, codes)
    assert not any(g.meetings for c in built for g in c.groups), "יש כאן קבוצה עם מועד"
    return built


def _last_course():
    """קורס שהקוד שלו ממוין אחרון, בלי מועדים, עם המזהים 1, 2, 10, 11.

    הסלוט שלו יושב במקום **האחרון** של ``_stable_key``, שם אין ``|`` אחרי
    האסימון. בקטלוג הקפוא ‏/1 ו-/10 יושבים רק במקומות שאחריהם בא ``|``.
    """
    groups = [
        models.Group(course_code="99999", group_id=gid, kind=PRACTICE,
                     lecturer=f"מרצה {gid}", meetings=[])
        for gid in ("2", "10", "1", "11")
    ]
    return models.Course(code="99999", name="קורס אחרון", credits=1.0, groups=groups)


def _half_stripped(app, term, code):
    """הקורס מסמסטר ``term``, כשלכל קבוצה שנייה בכל סוג נמחקו המפגשים."""
    (course,) = _term(app, term, [code])
    course = copy.deepcopy(course)
    for kind in course.kinds():
        for i, g in enumerate(course.groups_of(kind)):
            if i % 2:
                g.meetings = []
    return course


#: ‏שם → בונה רשימת קורסים. כל אחת סופית מספיק כדי שהמנייה המלאה תסיים.
SELECTIONS = {
    # כולן בלי מועד: מעבדה ‏/1–/10 באמצע המפתח.
    "untimed-lab-1-10": lambda app: _untimed(app, "ב", ["11006", "11231"]),
    # כולן בלי מועד: מעבדה ‏/1–/12, תרגול ‏/1–/5 אחרון.
    "untimed-lab-1-12": lambda app: _untimed(app, "ב", ["11006", "31616"]),
    "untimed-trio": lambda app: _untimed(app, "ב", ["11006", "11121", "31316"]),
    # המזהים 1 ו-10 במקום האחרון.
    "untimed-last-1-10": lambda app: _untimed(app, "ב", ["11006", "11121"]) + [_last_course()],
    # סלוטים עם מועד (סמסטר א') וסלוטים בלי (סמסטר ב') באותה בחירה.
    "timed-then-untimed": lambda app: (
        _term(app, "א", ["11006", "11231"]) + _untimed(app, "ב", ["11121"])
    ),
    "timed-untimed-last-1-10": lambda app: (
        _term(app, "א", ["11121"]) + _untimed(app, "ב", ["11006"]) + [_last_course()]
    ),
    # בתוך אותו סלוט: מעבדה ‏/6 של 11231 בסמסטר א' אין לה מועד.
    "mixed-inside-a-slot": lambda app: _term(app, "א", ["11231", "31316"]),
    # חצי מהקבוצות של כל סוג בלי מועד, ועוד קורס שכולו בלי מועד.
    "half-stripped": lambda app: (
        [_half_stripped(app, "א", "11001")] + _untimed(app, "ב", ["11006"])
    ),
}


def _optional(built):
    return {c.code: {k: False for k in c.kinds()} for c in built}


def _ranked(built):
    """לכל רכיב: המרצה האחרון ברשימה קודם, ואחריו הראשון — כמו בבדיקת הדיוק."""
    out = {}
    for course in built:
        per = {}
        for kind in course.kinds():
            names = []
            for g in course.groups_of(kind):
                if g.lecturer and g.lecturer not in names:
                    names.append(g.lecturer)
            if names:
                per[kind] = [names[-1], names[0]]
        if per:
            out[course.code] = per
    return out


#: ‏(שם, גוף בקשה מהקורסים). אותה צורה כמו ``/api/solve``.
VARIANTS = [
    ("page-default", lambda b: {"target_days": 6, "attendance": _optional(b)}),
    ("required", lambda b: {"target_days": 6}),
    ("target2-top1", lambda b: {"target_days": 2, "attendance": _optional(b), "top_n": 1}),
    ("ranked-top12", lambda b: {"target_days": 4, "attendance": _optional(b),
                                "ranked": _ranked(b), "top_n": 12}),
    ("zero-weights", lambda b: {"target_days": 6, "attendance": _optional(b),
                                "weights": {"gaps": 0.0, "compactness": 0.0,
                                            "late_finish": 0.0}}),
    ("negative-weight", lambda b: {"target_days": 6, "attendance": _optional(b),
                                   "weights": {"compactness": -1.0}}),
    ("top40", lambda b: {"target_days": 3, "attendance": _optional(b), "top_n": 40}),
]


def _prefs(body):
    prefs, unsupported = api._make_preferences(  # noqa: SLF001
        target_days=int(body.get("target_days", 4)),
        preferred_lecturers=api._clean_ranked(body.get("ranked")),  # noqa: SLF001
        blocked_windows=[],
        earliest=0,
        latest=api.MINUTES_IN_DAY,
        weights=api._clean_weights(body.get("weights")),  # noqa: SLF001
        forbid_friday=False,
        attendance=api._clean_attendance(body.get("attendance")),  # noqa: SLF001
        allow_soft_conflicts=True,
    )
    assert not unsupported
    return prefs


# ==========================================================================
# מקור האמת
# ==========================================================================
def _reference(courses, prefs, top_n):
    prefs = replace(
        prefs, preferred_lecturers=sch.rankings_by_kind(courses, prefs.preferred_lecturers)
    )
    slots = sch._build_slots(courses, prefs)  # noqa: SLF001
    kind_of = sch._kind_index(courses)  # noqa: SLF001
    leaves, chosen = [], []

    def bt(depth):
        if depth == len(slots):
            leaves.append(models.Selection(list(chosen)))
            return
        for cand in slots[depth].candidates:
            if any(not sch._pair_ok(a, cand, kind_of, prefs) for a in chosen):  # noqa: SLF001
                continue
            chosen.append(cand)
            bt(depth + 1)
            chosen.pop()

    bt(0)
    scored = sorted((sch.score(s, prefs) for s in leaves), key=sch._sort_key)  # noqa: SLF001
    return scored[: max(1, int(top_n))], len(leaves)


def _fingerprint(sched):
    return (
        sorted((g.course_code, g.kind, g.group_id) for g in sched.selection.groups),
        sched.score,
        dict(sched.breakdown),
        sch._sort_key(sched),  # noqa: SLF001
    )


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    empty = tmp_path_factory.mktemp("empty-store")
    return api.create_app({"allow_network": False}, serve_ui=False, db_root=empty)


# ==========================================================================
# הבדיקות
# ==========================================================================
def test_the_selections_hold_what_they_claim(app):
    """הבחירות באמת מעמידות 1 ו-10 זה לצד זה, ובאמת מערבבות עם/בלי מועד."""
    def tokens(built):
        return {(c.code, k): {g.group_id for g in c.groups_of(k)} for c in built for k in c.kinds()}

    lab = tokens(SELECTIONS["untimed-lab-1-10"](app))[("11231", "מעבדה")]
    assert {"271030110/1", "271030110/10"} <= lab
    last = SELECTIONS["untimed-last-1-10"](app)
    keys = sorted(f"{c.code}~{k}~" for c in last for k in c.kinds())
    assert keys[-1] == f"99999~{PRACTICE}~"
    for name in ("timed-then-untimed", "mixed-inside-a-slot", "half-stripped"):
        groups = [g for c in SELECTIONS[name](app) for g in c.groups]
        assert any(g.meetings for g in groups) and any(not g.meetings for g in groups), name
    slot_mixed = [
        c for c in SELECTIONS["mixed-inside-a-slot"](app) for k in c.kinds()
        if len({bool(g.meetings) for g in c.groups_of(k)}) == 2
    ]
    assert slot_mixed, "אין סלוט שמערבב קבוצות עם מועד ובלי"


@pytest.mark.parametrize("vname,variant", VARIANTS, ids=[v[0] for v in VARIANTS])
@pytest.mark.parametrize("name", list(SELECTIONS))
def test_solve_matches_full_enumeration(app, name, vname, variant):
    built = SELECTIONS[name](app)
    body = variant(built)
    top_n = int(body.get("top_n", 5))
    prefs = _prefs(body)

    expected, n_leaves = _reference(built, prefs, top_n)
    assert n_leaves, f"{name}: אין אף עלה — הבחירה אינה בודקת דבר"
    got = sch.solve(built, prefs, top_n=top_n)

    assert len(got) == min(top_n, n_leaves)
    assert [_fingerprint(s) for s in got] == [_fingerprint(s) for s in expected]
    assert not any(getattr(s, "truncated", False) for s in got)


def test_stable_key_order_is_the_full_key_order_not_token_order(app):
    """בכל המקומות חוץ מהאחרון ‏/10 קודם ל-/1; במקום האחרון ‏1 קודם ל-10."""
    built = SELECTIONS["untimed-last-1-10"](app)
    prefs = _prefs({"target_days": 6, "attendance": _optional(built)})
    got = sch.solve(built, prefs, top_n=4)
    last = [s.selection.group_for("99999", PRACTICE).group_id for s in got]
    assert last == ["1", "10", "11", "2"]
    lectures = {s.selection.group_for("11121", LECTURE).group_id for s in got}
    assert lectures == {"271030110/1"}, "‏'271030110/1|' קודם ל-'271030110|'"


def test_electrical_s2_top5_within_a_node_limit(app):
    """בחירת ברירת המחדל של חשמל שנה ב' — ‏``_search_best`` לבדו, בלי השעון.

    ‏5,760,000 עלים, כולם שווים עד ``_stable_key``. עד 2026-10-24 החיפוש עבר
    על כולם. הטובות ביותר כאן הן חמש הקטנות לפי המפתח, ולכן הן נבדקות
    בלי מנייה: כל השילובים אפשריים (אין ``linked_to`` שפוסל), ובכל סלוט
    האסימון הקטן כפי שהוא מושווה במקומו — ובסלוט האחרון ‏1 עד 5.
    """
    built = _untimed(app, "ב", ["11006", "11121", "11231", "31316", "31616"])
    prefs = _prefs({"target_days": 6, "attendance": _optional(built)})
    limit = 2_000
    got = sch.solve(built, prefs, top_n=5, limit=limit)
    assert not any(s.truncated for s in got), f"נקטע במכסה של {limit:,} צמתים"
    keys = [sch._stable_key(s.selection) for s in got]  # noqa: SLF001
    assert keys == sorted(keys) and len(set(keys)) == 5
    last = [s.selection.group_for("31616", PRACTICE).group_id for s in got]
    assert last == [f"271030110/{i}" for i in range(1, 6)]
    head = {k.rsplit("|", 1)[0] for k in keys}
    assert len(head) == 1, "חמש הראשונות נבדלות רק בסלוט האחרון"
    picks = got[0].selection
    assert picks.group_for("11231", "מעבדה").group_id == "271030110/10"
    assert picks.group_for("31616", "מעבדה").group_id == "271030110/10"
