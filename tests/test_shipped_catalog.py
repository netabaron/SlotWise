# -*- coding: utf-8 -*-
"""הקטלוג שנשלח עם הקוד — ומה שהוא מותר ואסור לטעון.

שתי טענות נבדקות כאן, והשנייה חשובה מהראשונה:

1. שכפול נקי מקבל קטלוג מלא בלי רשת.
2. ‏``Store(path)`` ממשיך לתאר את ``path`` בלבד. הצירוף הוא **בחירה** של
   שכבת התצוגה, לא התנהגות של המסד — אחרת זיהוי השינויים ב-refresh.py
   היה מוצא 572 "קורסים קיימים" שמעולם לא נכתבו אליו.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import shipped_catalog  # noqa: E402
from src.store import Store  # noqa: E402
from src.web.api import create_app  # noqa: E402


@pytest.fixture()
def empty_db(tmp_path):
    return str(tmp_path / "db")


# ==========================================================================
# 1. הקובץ עצמו
# ==========================================================================
def test_the_shipped_catalog_is_present_and_parsed():
    assert shipped_catalog.available(), "אין קטלוג שנשלח עם הקוד"
    courses = shipped_catalog.courses()
    assert len(courses) >= 500, f"רק {len(courses)} קורסים"
    assert shipped_catalog.built_at(), "אין תאריך בנייה"


def test_every_semester_is_kept_not_just_the_current_one():
    """הסינון עבר לזמן קריאה — לכן סמסטר ב' חייב להיות בקובץ."""
    semesters = {
        (g.get("semester") or "")
        for rec in shipped_catalog.courses().values()
        for g in rec.get("groups") or []
    }
    assert "א" in semesters
    assert "ב" in semesters, "סמסטר ב' סונן בכתיבה — זה בדיוק מה שתוקן"


def test_the_catalog_knows_only_when_it_was_built():
    """מה שהקטלוג יודע: תאריך בנייה. מה שאינו יודע: מצב הידיעון."""
    meta = shipped_catalog.meta()
    assert meta.get("built_at")
    for forbidden in ("yedion_checked_at", "verified_at", "up_to_date"):
        assert forbidden not in meta, (
            f"‏{forbidden} טוען ידע על הידיעון החי שאין לאפליקציה"
        )


def test_a_broken_line_does_not_destroy_the_whole_catalog(tmp_path, monkeypatch):
    good = json.dumps({"code": "61756", "name": "א", "groups": []}, ensure_ascii=False)
    path = tmp_path / "catalog.jsonl"
    path.write_text(good + "\n{ this is not json\n", encoding="utf-8")
    monkeypatch.setattr(shipped_catalog, "CATALOG_PATH", path)
    monkeypatch.setattr(shipped_catalog, "META_PATH", tmp_path / "missing.json")
    data = shipped_catalog.load(refresh=True)
    assert set(data["courses"]) == {"61756"}


# ==========================================================================
# 2. חוזה ה-Store — מסד ריק נשאר ריק
# ==========================================================================
def test_a_plain_store_on_an_empty_dir_is_empty(empty_db):
    """‏Store(path) מתאר את path. זה מה ש-refresh.py נשען עליו."""
    store = Store(empty_db)
    assert store.codes() == []
    assert store.load_all() == {}
    assert store.load_catalog() == ({}, {})


def test_the_shipped_layer_is_opt_in(empty_db):
    store = Store(empty_db, use_shipped=True)
    assert len(store.codes()) >= 500
    catalog, meta = store.load_catalog()
    assert len(catalog) >= 500
    assert meta.get("fetched_at") == shipped_catalog.built_at()


def test_user_data_wins_over_the_shipped_layer(empty_db, tmp_path):
    """מה שהמשתמש/ת שלפו דורס את מה שנשלח, קוד-אחר-קוד."""
    store = Store(empty_db, use_shipped=True)
    shipped_name = store.load_course("61756")[0].name
    db = Path(empty_db)
    db.mkdir(parents=True, exist_ok=True)
    (db / "sections.json").write_text(json.dumps({
        "schema": "braude-schedule-builder/sections-db", "version": 1,
        "courses": {"61756": {"course": {"code": "61756", "name": "שם מקומי",
                                         "credits": 1.0, "groups": []},
                              "meta": {"fetched_at": "2026-09-07T00:00:00Z"}}},
    }, ensure_ascii=False), encoding="utf-8")
    store2 = Store(empty_db, use_shipped=True)
    assert store2.load_course("61756")[0].name == "שם מקומי" != shipped_name
    assert len(store2.codes()) >= 500, "שאר הקטלוג נעלם כשנוספה רשומה אחת"


# ==========================================================================
# 3. שכפול נקי — הטענה שבגללה כל זה נעשה
# ==========================================================================
def _clone_client():
    tmp = Path(tempfile.mkdtemp(prefix="clone_"))
    return create_app(config={"allow_network": False, "db_root": str(tmp)}).test_client()


def test_a_fresh_clone_shows_the_whole_catalog_without_network():
    c = _clone_client()
    browse = c.get("/api/catalog/browse?program=%s" % "הנדסת תוכנה").get_json()
    assert browse["total"] >= 500, f"שכפול נקי מציג {browse['total']} קורסים"


def test_a_fresh_clone_can_solve_without_network():
    c = _clone_client()
    r = c.post("/api/solve", json={"codes": ["61756", "61757", "62027"],
                                   "semester": "א", "target_days": 4}).get_json()
    assert r.get("ok"), r.get("error")
    assert len(r.get("schedules") or []) > 0


def test_shipped_courses_are_reported_as_shipped_not_as_fetched():
    """הכי חשוב: ‏API שאומר "db" על נתון שנשלח עם הקוד משקר על מקורו."""
    c = _clone_client()
    r = c.post("/api/courses", json={"codes": ["61756"], "semester": "א",
                                     "fetch_missing": False}).get_json()
    course = (r.get("courses") or [])[0]
    assert course["source"] == "shipped"
    assert course["freshness"]["origin"] == "shipped"
    assert course["freshness"]["fetched_at"] == shipped_catalog.built_at()


def test_the_bootstrap_reports_the_build_date_not_a_fetch_date():
    c = _clone_client()
    db = (c.get("/api/bootstrap").get_json() or {})["db"]
    assert db["origin"] == "shipped"
    assert db["catalog_built_at"] == shipped_catalog.built_at()
