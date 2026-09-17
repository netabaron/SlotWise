# -*- coding: utf-8 -*-
"""
הקטלוג **האמיתי** — ‏data/catalog/. הקובץ היחיד בסוויטה שנוגע בו.

למה הוא לבדו
-------------
כל שאר הבדיקות קוראות את הקטלוג הקפוא שב-``tests/fixtures/catalog``
(ראו ``tests/conftest.py``), כי הן מקבעות ערכים שנגזרים ממנו — ימים,
ספירות, שמות — ועדכון נתונים לילי היה מפיל אותן בלי שאיש נגע בקוד.

אבל אסור שהתוצאה תהיה ש**אף בדיקה אינה מסתכלת על מה שבאמת נשלח**. אם
הצינור יכתוב קטלוג ריק, קטוע, של שנה שגויה, או כזה שהמטא שלו מתאר קטלוג
אחר — הבדיקות שרצות מול הקובץ הקפוא יעברו בשמחה, והמשתמש/ת יקבלו
אפליקציה ריקה. הקובץ הזה סוגר בדיוק את הפער הזה.

הכלל שמחזיק אותו
-----------------
**רק תכונות (invariants), אף פעם לא ערכים.** "יש לפחות 400 קורסים" —
כן. "יש 572 קורסים" — לא, זה היה מחזיר בדיוק את הבעיה שהקובץ הקפוא בא
לפתור. אם בדיקה כאן נופלת אחרי בנייה לילית, משהו **באמת** שבור.

הטעינה נעשית דרך ``shipped_catalog.py`` — אותו נתיב קוד שהשרת משתמש בו —
אבל כמופע מודול נפרד, כדי לא לגעת במצב הגלובלי ש-conftest הפנה לקובץ
הקפוא.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for _path in (str(SRC), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

REAL_CATALOG_DIR = ROOT / "data" / "catalog"
REAL_CATALOG = REAL_CATALOG_DIR / "catalog.jsonl"
REAL_META = REAL_CATALOG_DIR / "catalog.meta.json"

#: רצפה שמרנית. הקטלוג האמיתי מחזיק 572 קורסים; ‏400 תופס קריסה אמיתית
#: בלי ליפול על תנודה טבעית. זהה ל-``scripts/verify_catalog.py``.
MIN_COURSES = 400

pytestmark = pytest.mark.skipif(
    not REAL_CATALOG.is_file(),
    reason="אין data/catalog/catalog.jsonl — הקטלוג שנשלח חסר",
)


@pytest.fixture(scope="module")
def real_catalog():
    """‏``shipped_catalog`` טעון מחדש, מכוון לקטלוג האמיתי.

    ‏מופע מודול **נפרד** ולא ``import shipped_catalog``: ה-conftest הפנה
    את המודול הגלובלי לקובץ הקפוא, ודריסה שלו כאן הייתה דולפת לכל שאר
    הקבצים לפי סדר ההרצה. ‏spec_from_file_location נותן אובייקט מודול
    משלנו, עם ``_CACHE`` משלו, שנעלם בסוף.
    """
    previous = os.environ.get("SLOTWISE_CATALOG_DIR")
    os.environ["SLOTWISE_CATALOG_DIR"] = str(REAL_CATALOG_DIR)
    try:
        spec = importlib.util.spec_from_file_location(
            "shipped_catalog__real", SRC / "shipped_catalog.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            os.environ.pop("SLOTWISE_CATALOG_DIR", None)
        else:
            os.environ["SLOTWISE_CATALOG_DIR"] = previous

    assert Path(module.CATALOG_PATH) == REAL_CATALOG, (
        f"הבדיקה הזאת חייבת לקרוא את הקטלוג האמיתי; קיבלה {module.CATALOG_PATH}"
    )
    return module


# ==========================================================================
# 1. הוא קיים, והוא נטען
# ==========================================================================
def test_the_shipped_catalog_loads(real_catalog):
    assert real_catalog.available(), "הקטלוג שנשלח אינו נטען"


def test_the_shipped_catalog_is_not_empty(real_catalog):
    """רצפה, לא ערך מדויק."""
    courses = real_catalog.courses()
    assert len(courses) >= MIN_COURSES, (
        f"רק {len(courses)} קורסים בקטלוג שנשלח (נדרש לפחות {MIN_COURSES})"
    )


def test_every_record_carries_the_required_fields(real_catalog):
    """‏code ו-groups בכל רשומה, ו-groups הוא רשימה.

    ‏בלי זה, קטלוג שנכתב חלקית עובר בשקט והאפליקציה נופלת בזמן ריצה.
    """
    bad: list[str] = []
    for code, rec in real_catalog.courses().items():
        if not str(code).strip():
            bad.append("(קוד ריק)")
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("groups"), list):
            bad.append(str(code))
    assert not bad, f"{len(bad)} רשומות פגומות: {', '.join(bad[:5])}"


def test_at_least_one_group_has_a_timed_meeting(real_catalog):
    """קטלוג בלי שעות אינו קטלוג — אי אפשר לבנות ממנו מערכת."""
    timed = sum(
        1
        for rec in real_catalog.courses().values()
        for g in rec.get("groups") or []
        for m in g.get("meetings") or []
        if m.get("start") is not None and m.get("end") is not None
    )
    assert timed > 0, "אין אף מפגש עם שעות בקטלוג שנשלח"


# ==========================================================================
# 2. המטא מתאר את הקטלוג שלצידו
# ==========================================================================
def test_the_meta_has_a_build_timestamp_and_a_year(real_catalog):
    meta = real_catalog.meta()
    assert str(meta.get("built_at") or "").strip(), f"אין חותמת בנייה: {meta!r}"
    assert str(meta.get("year") or "").strip(), f"אין שנה עברית: {meta!r}"
    assert str(meta.get("year_gregorian") or "").strip(), f"אין שנה לועזית: {meta!r}"


def test_the_meta_year_matches_the_pages_it_was_built_from(real_catalog):
    """השנה העברית והלועזית מתארות את אותה שנה.

    ‏שנה שגויה בשקט היא הכשל הגרוע ביותר שהכלי הזה יכול לייצר: מערכת
    אמינה-למראה של שנה אחרת. ‏GROUND_TRUTH §9.
    """
    meta = real_catalog.meta()
    gregorian = str(meta.get("year_gregorian") or "").strip()
    try:
        from yedion_http import hebrew_year_label  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - המודול אינו חובה לבדיקה הזאת
        pytest.skip("yedion_http אינו זמין")
    assert str(meta.get("year")).strip() == hebrew_year_label(gregorian), (
        f"‏{meta.get('year')!r} אינו התווית של {gregorian!r}"
    )


def test_the_meta_counts_match_the_catalog(real_catalog):
    """הכשל שאף שער בנייה אינו רואה: מטא של בנייה אחת לצד קטלוג של אחרת."""
    courses = real_catalog.courses()
    meta_counts = real_catalog.meta().get("counts") or {}
    assert int(meta_counts.get("courses") or 0) == len(courses), (
        f"המטא אומר {meta_counts.get('courses')} קורסים, בקטלוג יש {len(courses)}"
    )

    groups = sum(len(rec.get("groups") or []) for rec in courses.values())
    assert int(meta_counts.get("groups") or 0) == groups, (
        f"המטא אומר {meta_counts.get('groups')} קבוצות, בקטלוג יש {groups}"
    )


def test_the_meta_code_list_matches_the_catalog(real_catalog):
    meta_codes = {str(c) for c in (real_catalog.meta().get("codes") or [])}
    actual = set(real_catalog.courses())
    assert meta_codes == actual, (
        f"רק במטא: {len(meta_codes - actual)}; רק בקטלוג: {len(actual - meta_codes)}"
    )


def test_the_catalog_file_is_one_json_object_per_line():
    """נקרא מהדיסק ישירות — ‏shipped_catalog סלחן לשורה פגומה בכוונה.

    ‏``load()`` מדלג על שורה שאינה נפרסרת, כדי ששורה אחת לא תמחק קטלוג
    שלם בזמן ריצה. זו התנהגות נכונה לשרת ו**שגויה** לשער איכות: כאן
    רוצים לדעת שהקובץ תקין לגמרי.
    """
    bad: list[int] = []
    with REAL_CATALOG.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                bad.append(lineno)
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError:
                bad.append(lineno)
    assert not bad, f"{len(bad)} שורות פגומות, למשל בשורות {bad[:5]}"


# ==========================================================================
# 3. השומר על ההפרדה עצמה
# ==========================================================================
def test_the_frozen_fixture_exists_and_is_a_separate_file():
    """הקובץ הקפוא קיים, ואינו אותו קובץ כמו הקטלוג שנשלח.

    ‏אם מישהו יסמלן (symlink) או יעתיק את הקפוא אל מעל האמיתי, כל
    ההפרדה הזאת מתמוטטת בשקט — וכל הבדיקות עדיין יעברו.
    """
    frozen = ROOT / "tests" / "fixtures" / "catalog" / "catalog.jsonl"
    assert frozen.is_file(), "הקטלוג הקפוא חסר — ראו scripts/update_test_fixture.py"
    assert frozen.resolve() != REAL_CATALOG.resolve(), (
        "הקובץ הקפוא והקטלוג שנשלח הם אותו קובץ — ההפרדה בטלה"
    )
