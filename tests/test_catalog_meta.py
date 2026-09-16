# -*- coding: utf-8 -*-
"""
‏GET /api/catalog/meta — מתי נבנה הקטלוג, וכמה קורסים יש בו.

‏נקודת הקצה הזאת נולדה באריזה לאירוח (2026-09-16) והחליפה את
‏``GET /api/scrape/status``. ההחלפה אינה שינוי שם: היא שינוי של השאלה.
‏``/api/scrape/status`` ענה על *"איך הולכת הגרידה שלך"*, ולסטודנט/ית
‏מאורח/ת אין גרידה משלהם ואין יומן לצפות בו. מה שכן נוגע להם הוא
‏**"כמה ישן הקטלוג שאני מקבל"**. ‏HOSTING_NOTES.md §3 ו-§4 כלל 2.

‏הקובץ גם נועל את ההסרה עצמה: שלוש נקודות הקצה החיות — ‏scrape/start,
‏scrape/status ו-reparse — חייבות להחזיר ‏404. בלי הבדיקה הזאת, החזרה שלהן
‏בטעות (‏merge, ‏revert, העתקה מקובץ ישן) הייתה שקטה לחלוטין, והיא בדיוק
‏הדבר שאסור שיחזור: ‏``/api/scrape/start`` הוא בלי הזדהות ובלי מגן קצב,
‏כלומר מאורח הוא ממסר פתוח אל השרת של המכללה. ‏HOSTING_NOTES.md §1 שורה 3.

‏רץ לגמרי אופליין: ‏Flask test client, בלי רשת ובלי דפדפן.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for _path in (str(SRC), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

#: ‏ISO-8601 ב-UTC, בדיוק כפי ש-``_now_iso`` ו-``catalog.meta.json`` כותבים.
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@pytest.fixture(scope="module")
def client():
    """לקוח מעל הקטלוג שנשלח עם הקוד, בלי רשת.

    ‏``db_root`` מצביע על הקטלוג ולא על ``data/db`` מאותה סיבה שמתועדת
    ב-``tests/test_web.py``: ‏``data/db`` אינו במאגר הקוד והאפליקציה הרצה
    כותבת אותו מחדש, כך שבדיקה שנשענת עליו זזה מתחת לעצמה.
    """
    from catalog_source import catalog_db_dir  # noqa: PLC0415

    from web.api import create_app  # noqa: PLC0415

    app = create_app({"allow_network": False}, db_root=catalog_db_dir())
    with app.test_client() as test_client:
        yield test_client


def _ok(resp) -> dict:
    assert resp.status_code == 200, (
        f"ציפיתי ל-200; התקבל {resp.status_code} — {resp.get_data(as_text=True)[:300]!r}"
    )
    data = resp.get_json()
    assert isinstance(data, dict) and data.get("ok") is True, f"תשובה לא תקינה: {data!r}"
    return data


# ==========================================================================
# 1. נקודת הקצה החדשה
# ==========================================================================
def test_catalog_meta_reports_a_build_timestamp(client):
    """``built_at`` הוא ‏ISO-8601 ב-UTC — מה שהתווית בכותרת מתארכת לפיו."""
    data = _ok(client.get("/api/catalog/meta"))
    built_at = data.get("built_at")
    assert isinstance(built_at, str) and built_at, f"אין חותמת בנייה: {data!r}"
    assert ISO_UTC.match(built_at), f"חותמת שאינה ISO-8601 ב-UTC: {built_at!r}"


def test_catalog_meta_reports_a_plausible_course_count(client):
    """ספירה אמיתית, לא אפס.

    ‏הקטלוג שנשלח עם הקוד מחזיק 572 קורסים; הרף כאן נמוך בכוונה, כי מה
    ‏שהבדיקה שומרת עליו הוא ש**נספר משהו** — קטלוג ריק שמדווח 0 הוא בדיוק
    ‏המצב שבו התווית בכותרת משקרת בשקט.
    """
    data = _ok(client.get("/api/catalog/meta"))
    count = data.get("course_count")
    assert isinstance(count, int), f"course_count חייב להיות מספר שלם: {count!r}"
    assert count >= 100, f"ספירת קורסים לא סבירה: {count}"


def test_catalog_meta_says_where_the_timestamp_came_from(client):
    """``source`` מבדיל בין קטלוג שנשלח עם הקוד לבין שליפה מקומית."""
    data = _ok(client.get("/api/catalog/meta"))
    assert data.get("source") in {"shipped", "db"}, f"מקור לא מוכר: {data.get('source')!r}"
    assert data.get("empty") is False, "הקטלוג מדווח ריק בזמן שיש בו קורסים"


def test_catalog_meta_needs_no_network(client):
    """``allow_network=False`` — והתשובה עדיין מלאה.

    ‏זו כל הנקודה של האריזה לאירוח: הקטלוג מוגש מהדיסק, ואף בקשה אינה
    ‏נוגעת בשרת של המכללה.
    """
    data = _ok(client.get("/api/catalog/meta"))
    assert data.get("built_at"), "בלי רשת אין חותמת — סימן שהיא נשלפה ולא נקראה"


def test_catalog_meta_never_leaks_a_password(client):
    """אין שדה שנראה כמו סיסמה. אותו כלל כמו ב-``/api/bootstrap``."""
    blob = client.get("/api/catalog/meta").get_data(as_text=True).lower()
    for forbidden in ("password", "passwd", "סיסמה", "סיסמא"):
        assert forbidden not in blob, f"אסור לטפל בסיסמאות: {forbidden}"


# ==========================================================================
# 2. מה שהוסר חייב להישאר מוסר
# ==========================================================================
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/scrape/start"),
        ("get", "/api/scrape/status"),
        ("post", "/api/reparse"),
    ],
)
def test_the_live_scrape_surface_is_gone(client, method, path):
    """‏404, לא 405 ולא 500 — המסלול עצמו אינו רשום.

    ‏405 היה אומר שהמסלול קיים ורק הפועל שגוי, כלומר שההסרה לא הושלמה.
    """
    resp = getattr(client, method)(path, json={})
    assert resp.status_code == 404, (
        f"{method.upper()} {path} החזיר {resp.status_code} — נקודת הקצה חזרה"
    )


def test_bootstrap_no_longer_carries_live_scrape_state(client):
    """‏``/api/bootstrap`` לא מחזיר יותר ``scrape``.

    ‏השדה הזה היה תמונת מצב של המשתנים הגלובליים שהוסרו. השארתו הייתה
    ‏מחזירה אותם דרך הדלת האחורית. ‏HOSTING_NOTES.md §4 כלל 5.
    """
    data = _ok(client.get("/api/bootstrap"))
    assert "scrape" not in data, "‏bootstrap עדיין מחזיר מצב גרידה חי"
    limits = data.get("limits") or {}
    assert "max_log_lines" not in limits, "‏מגבלת יומן הגרידה עדיין מדווחת"
