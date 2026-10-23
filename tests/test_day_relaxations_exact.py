# -*- coding: utf-8 -*-
"""‏``day_relaxations`` המהיר אומר **בדיוק** את מה שאמרה המנייה המלאה.

‏2026-10-23: עד כאן כל יחידת ויתור נמדדה ב-``_min_days_of`` — מנייה מלאה
של כל הבחירות, שסופרת גם את המערכות. בשנה א' עם יעד שאינו אפשרי זה היה
‏770–820 אלף צמתים, ו-/api/solve נעצר במגבלת הזמן. עכשיו המינימום נמצא ב-
branch-and-bound (``min_days``, עם ``base_min`` כחסם התחלתי), והספירה הוסרה
(הממשק אינו מציג אותה עוד). השינוי אמור לגעת **רק במהירות**.

מקור האמת כאן הוא ``_reference_day_relaxations`` — העתק של הגרסה הקודמת,
מנייה מלאה, שאינו תלוי בקוד שהשתנה. לכל בחירה × העדפות × יעד נבדקים:
  * ‏``scheduler.day_relaxations``: אותן יחידות ויתור, באותו סדר, עם אותו
    מינימום ימים, אותן נ"ז ואותו ``reachable_without_dropping``;
  * ‏``/api/solve``: ‏``day_relaxations.items`` ו-``checked`` — אותם קודים, באותו
    סדר, עם אותו מינימום.

הבחירות הן אלה של ``test_solver_exactness.py`` (קטלוג קפוא, סמסטר א') —
קטנות בכוונה, כדי שהמנייה המלאה תסיים.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from src.web import api  # noqa: E402
from test_solver_exactness import SELECTIONS, TERM, _prefs_like_the_api  # noqa: E402

sch = api.scheduler_mod


# ==========================================================================
# מקור האמת — ‏day_relaxations כפי שהיה עד 2026-10-23
# ==========================================================================
def _reference_min_days_of(courses, prefs, limit):
    """‏``_min_days_of`` כפי שהיה: מנייה מלאה, ‏``None`` כשנקטעה."""
    budget = limit if limit is not None else sch._node_budget(courses, prefs)  # noqa: SLF001
    best = None
    try:
        for selection in sch.enumerate_selections(courses, prefs, limit=budget):
            days = len(selection.days_used())
            if best is None or days < best:
                best = days
    except sch.SearchExhausted:
        return None
    except Exception:  # noqa: BLE001
        return None
    return best


def _reference_day_relaxations(courses, prefs, target_days):
    """‏(‏reachable_without_dropping, ‏[(codes, names, credits, min_days)], ממוין)."""
    base_min = _reference_min_days_of(courses, prefs, None)
    if base_min is not None and base_min <= target_days:
        return True, []
    by_code = {c.code: c for c in courses}
    options = []
    for unit in sch._tied_units(courses):  # noqa: SLF001
        kept = [c for c in courses if c.code not in unit]
        if not kept:
            continue
        options.append((
            list(unit),
            [str(getattr(by_code.get(c), "name", "") or c) for c in unit],
            round(sum(float(getattr(by_code.get(c), "credits", 0) or 0) for c in unit), 1),
            _reference_min_days_of(kept, prefs, None),
        ))

    def unlocks(o):
        return o[3] is not None and o[3] <= target_days

    options.sort(key=lambda o: (not unlocks(o), o[2], o[3] if o[3] is not None else 99, o[0]))
    return False, options


# ==========================================================================
# הבקשות
# ==========================================================================
def _optional(built):
    return {c.code: {k: False for k in c.kinds()} for c in built}


#: ‏(שם, פונקציה שבונה גוף בקשה). כל אחת משנה את מרחב הבחירות אחרת.
PREFS = [
    ("required", lambda b: {}),
    ("page-default", lambda b: {"attendance": _optional(b)}),
    ("blocked-friday", lambda b: {"blocked": [{"day": 2, "start": "08:00", "end": "12:00"}],
                                  "forbid_friday": True}),
    ("window", lambda b: {"attendance": _optional(b), "earliest": "08:30", "latest": "18:00"}),
]

#: יעדים יחסית למינימום: אחד מתחתיו, הכי נמוך שאפשר, ובדיוק המינימום.
TARGETS = ["min-1", "one", "min"]


def _target(kind, base_min):
    return {"min-1": base_min - 1, "one": 1, "min": base_min}[kind]


@pytest.fixture(scope="module")
def app():
    return api.create_app({"allow_network": False}, serve_ui=False)


@pytest.fixture(scope="module")
def client(app):
    return app.test_client()


def _setup(app, name, prefs_fn):
    codes = SELECTIONS[name]
    with app.app_context():
        built, _p, _m = api._build_courses(codes, semester=TERM)  # noqa: SLF001
    assert [c.code for c in built] == codes, "קוד חסר בקטלוג הקפוא — הבחירה אינה מה שנבדק"
    extra = prefs_fn(built)
    prefs = _prefs_like_the_api({"target_days": 6, **extra}, built)
    base_min = _reference_min_days_of(built, prefs, None)
    return codes, built, extra, prefs, base_min


CASES = [
    pytest.param(name, pname, pfn, target, id=f"{name}-{pname}-{target}")
    for name in SELECTIONS
    for pname, pfn in PREFS
    for target in TARGETS
]


@pytest.mark.parametrize("name,pname,prefs_fn,target", CASES)
def test_day_relaxations_match_the_full_enumeration(app, name, pname, prefs_fn, target):
    _codes, built, _extra, prefs, base_min = _setup(app, name, prefs_fn)
    if base_min is None:
        pytest.skip("אין אף בחירה — אין יעד לדבר עליו")
    target_days = _target(target, base_min)
    want_reachable, want = _reference_day_relaxations(built, prefs, target_days)

    report = sch.day_relaxations(built, prefs, target_days)
    assert report.reachable_without_dropping is want_reachable
    got = [(o.codes, o.names, o.credits, o.min_days) for o in report.options]
    assert got == want
    # ‏base_min שהקורא מסר — כמו ש-/api/solve עושה — נותן את אותה תשובה בדיוק.
    passed = sch.day_relaxations(built, prefs, target_days, base_min=base_min)
    assert [(o.codes, o.names, o.credits, o.min_days) for o in passed.options] == want
    assert passed.reachable_without_dropping is want_reachable


@pytest.mark.parametrize("name,pname,prefs_fn", [
    pytest.param(name, pname, pfn, id=f"{name}-{pname}")
    for name in SELECTIONS for pname, pfn in PREFS
])
def test_api_day_relaxations_match_the_full_enumeration(app, client, name, pname, prefs_fn):
    codes, built, extra, prefs, base_min = _setup(app, name, prefs_fn)
    if base_min is None or base_min <= 1:
        pytest.skip("אין יעד שאינו אפשרי")
    target_days = base_min - 1
    _reachable, want = _reference_day_relaxations(built, prefs, target_days)

    res = client.post("/api/solve", json={"codes": codes, "semester": TERM,
                                         "target_days": target_days, **extra})
    assert res.status_code == 200, res.get_data(as_text=True)
    data = res.get_json()
    assert data["timed_out"] is False
    assert data["target_reachable"] is False and data["min_days"] == base_min
    rel = data["day_relaxations"]

    def unlocks(o):
        return o[3] is not None and o[3] <= target_days

    assert [(i["codes"], i["min_days"]) for i in rel["items"]] == [
        (o[0], o[3]) for o in want if unlocks(o)
    ]
    assert [(i["codes"], i["min_days"]) for i in rel["checked"]] == [
        (o[0], o[3]) for o in want if o[3] is not None and not unlocks(o)
    ]
    # הספירה הוסרה מהתשובה (2026-10-23), לא רק מהתצוגה.
    assert all("schedules" not in i for i in rel["items"] + rel["checked"])
