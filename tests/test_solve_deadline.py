# -*- coding: utf-8 -*-
"""מגבלת הזמן של ‏/api/solve: הטוב שנמצא, עם דגל — ולעולם לא 500.

‏2026-10-20 (docs/DESIGN.md → "Solver: exact pruned search"). חיפוש שעובר
את ``SOLVE_DEADLINE_S`` זורק ``SearchTimedOut``, שהוא ``SearchExhausted``:
כל מי שכבר טיפל בחיפוש שנקטע — ‏``solve()`` מחזיר את הטוב שנמצא עם
‏``truncated`` — מטפל גם בזה. השרת מוסיף ``timed_out``, והדף אומר זאת
במשפט אחד מ-strings.json.

הנוסח שהדף מציג נבדק ב-tests/test_solve_timeout_browser.py.

‏הסיבה שהמגבלה קיימת בכלל: מעל ‏30 שניות gunicorn הורג את ה-worker באמצע
החיפוש וכותב בעצמו ‏500 ב-HTML (נמדד, docs/SOLVER_PERFORMANCE.md §2).
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src.web import api  # noqa: E402

sch = api.scheduler_mod
TERM = "א"

#: בקטלוג הקפוא: שנה א' בהנדסת מכונות כפי שהדף מסמן אותה — 128,000 צירופים
#: כשכל הרכיבים בלי חובת נוכחות. מספיק גדול כדי שהחיפוש לא יסתיים ב-256 צמתים.
BIG = ["11001", "11003", "22112", "251961"]
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
    return built


def _all_optional(built):
    return {c.code: {k: False for k in c.kinds()} for c in built}


def _prefs(built):
    prefs, _ = api._make_preferences(  # noqa: SLF001
        target_days=6, attendance=_all_optional(built), allow_soft_conflicts=True
    )
    return prefs


# ==========================================================================
# 1. הקבוע
# ==========================================================================
def test_the_deadline_is_twenty_seconds_and_under_gunicorns_timeout():
    conf = (ROOT / "gunicorn.conf.py").read_text(encoding="utf-8")
    worker_timeout = int(re.search(r"^timeout\s*=\s*(\d+)", conf, re.M).group(1))
    assert api.SOLVE_DEADLINE_S == 20.0
    # מרווח לשלבים שאחרי החיפוש (JSON, ניקוד המובילות) ולמחשב איטי יותר.
    assert api.SOLVE_DEADLINE_S <= worker_timeout - 5, (api.SOLVE_DEADLINE_S, worker_timeout)


# ==========================================================================
# 2. המנוע: SearchTimedOut, הטוב שנמצא, ושום דבר מחוץ לבלוק
# ==========================================================================
def test_an_expired_budget_stops_the_search_with_the_best_so_far(app):
    built = _built(app, BIG)
    prefs = _prefs(built)
    with sch.time_budget(0.0):
        with pytest.warns(RuntimeWarning):
            found = sch.solve(built, prefs, top_n=5)
        assert sch.time_budget_expired() is True
    assert found, "נמצאו עלים לפני הבדיקה הראשונה של השעון — הם חייבים לחזור"
    assert all(s.truncated is True and s.timed_out is True for s in found)
    # מחוץ לבלוק אין מגבלה, והדגל אינו דולף.
    assert sch.time_budget_expired() is False


def test_no_schedule_before_the_deadline_is_infeasible_marked_timed_out(app, monkeypatch):
    built = _built(app, BIG)
    monkeypatch.setattr(sch, "_CLOCK_EVERY", 1)  # השעון נבדק כבר בצומת הראשון
    with sch.time_budget(0.0):
        with pytest.warns(RuntimeWarning):
            with pytest.raises(sch.Infeasible) as info:
                sch.solve(built, _prefs(built), top_n=5)
    assert info.value.timed_out is True and info.value.truncated is True
    assert all("הזמן" in r for r in info.value.reasons), info.value.reasons


def test_a_timed_out_search_is_a_search_exhausted():
    assert issubclass(sch.SearchTimedOut, sch.SearchExhausted)


def test_a_nested_budget_never_extends_the_outer_one(app):
    built = _built(app, BIG)
    with sch.time_budget(0.0):
        with sch.time_budget(3600.0):
            with pytest.warns(RuntimeWarning):
                found = sch.solve(built, _prefs(built), top_n=5)
            assert all(s.timed_out for s in found)
        assert sch.time_budget_expired() is True, "עצירה בבלוק הפנימי נראית גם בחיצוני"


def test_without_a_budget_nothing_is_cut(app):
    built = _built(app, SMALL)
    found = sch.solve(built, _prefs(built), top_n=5)
    assert found and not any(s.truncated or s.timed_out for s in found)


# ==========================================================================
# 3. ‏/api/solve: ‏200 תמיד, עם timed_out
# ==========================================================================
def _post(client, codes, **extra):
    return client.post(
        "/api/solve", json={"codes": list(codes), "semester": TERM, "target_days": 6, **extra}
    )


def test_a_normal_solve_says_it_was_not_cut(client):
    res = _post(client, SMALL)
    assert res.status_code == 200
    data = res.get_json()
    assert data["timed_out"] is False
    assert data["schedules"] and not any(s["truncated"] for s in data["schedules"])


def test_the_deadline_returns_the_best_so_far_with_a_flag(app, client, monkeypatch):
    monkeypatch.setattr(api, "SOLVE_DEADLINE_S", 0.0)
    built = _built(app, BIG)
    res = _post(client, BIG, attendance=_all_optional(built))
    assert res.status_code == 200, res.get_data(as_text=True)
    data = res.get_json()
    assert data["ok"] is True and data["timed_out"] is True
    assert data["schedules"], "מה שנמצא לפני העצירה חוזר"
    assert all(s["truncated"] is True for s in data["schedules"])


def test_the_deadline_before_any_schedule_is_not_called_infeasible(app, client, monkeypatch):
    """בלי אף מערכת: ‏200, ‏``timed_out``, ובלי אבחון "למה אין" — זה לא הוכח."""
    monkeypatch.setattr(api, "SOLVE_DEADLINE_S", 0.0)
    monkeypatch.setattr(sch, "_CLOCK_EVERY", 1)
    built = _built(app, BIG)
    started = time.perf_counter()
    res = _post(client, BIG, attendance=_all_optional(built))
    elapsed = time.perf_counter() - started
    assert res.status_code == 200, res.get_data(as_text=True)
    data = res.get_json()
    assert data["ok"] is True and data["timed_out"] is True
    assert data["schedules"] == []
    assert data["reasons"] == [] and "relaxations" not in data
    assert elapsed < 5, elapsed


def test_the_deadline_with_an_unreachable_day_target_is_still_200(app, client, monkeypatch):
    """הוויתורים על קורסים נמדדים אחרי המערכות — ונעצרים במגבלה כ"לא נמדד"."""
    monkeypatch.setattr(api, "SOLVE_DEADLINE_S", 0.0)
    built = _built(app, BIG)
    res = client.post("/api/solve", json={"codes": BIG, "semester": TERM, "target_days": 1,
                                         "attendance": _all_optional(built)})
    assert res.status_code == 200, res.get_data(as_text=True)
    data = res.get_json()
    assert data["timed_out"] is True
    for item in (data.get("day_relaxations") or {}).get("items", []):
        assert item["schedules"] is None or isinstance(item["schedules"], int)
