# -*- coding: utf-8 -*-
"""
מה שצריך להיות נכון כשהאפליקציה יושבת מאחורי ‏Cloudflare ו-Railway.

שלושה דברים שאין להם משמעות בהרצה מקומית ויש להם משמעות מלאה באירוח:

1. **מה מותר לשמור במטמון.** עד כאן כל ``/api`` קיבל ``no-store`` גורף. זה
   נכון לאפליקציה מקומית שבה המסד משתנה תוך כדי, ומבזבז לגמרי מטמון קצה
   שמשרת מאות סטודנטים את אותו קטלוג. ‏**רשימת היתר, לא רשימת איסור:**
   ברירת המחדל נשארה ``no-store``, ורק נקודות קצה קריאות-בלבד נפתחות.
2. **‏/healthz.** בדיקת הבריאות של ‏Railway. ‏200 רק אם באמת יש קטלוג —
   התקלה שהיא קיימת בשבילה היא ‏``SLOTWISE_CATALOG_DIR`` שגוי, שבו השרת
   עולה בשמחה ומגיש רשימות ריקות.
3. **‏ProxyFix.** נבדק ב-``tests/test_wsgi_proxy.py`` — הוא חי ב-``wsgi.py``
   ולא ב-``create_app``, כי ``webapp.py`` המקומי דווקא **אינו** אמור לתת
   אמון בכותרות האלה.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from web.api import create_app  # noqa: E402

SOFTWARE = "הנדסת תוכנה"

#: ‏GET, קריאה בלבד, ותשובתן זהה לכל מי ששואל.
CACHEABLE = [
    "/api/catalog/meta",
    "/api/catalog/search?q=617&limit=3",
    "/api/catalog/browse?prefix=110&limit=3",
    f"/api/semester/3/courses?program={quote(SOFTWARE)}",
    f"/api/program/electives?program={quote(SOFTWARE)}",
]


@pytest.fixture(scope="module")
def client():
    return create_app(config={"allow_network": False}).test_client()


# ==========================================================================
# 1. מה נשמר במטמון משותף
# ==========================================================================
@pytest.mark.parametrize("path", CACHEABLE)
def test_read_only_catalog_endpoints_are_publicly_cacheable(client, path):
    res = client.get(path)
    assert res.status_code == 200, path
    assert res.headers.get("Cache-Control") == "public, max-age=300", (
        f"{path}: {res.headers.get('Cache-Control')!r}"
    )


def test_solve_is_never_cached(client):
    """‏POST /api/solve תלוי בגוף הבקשה. תשובה משותפת כאן היא מערכת של מישהו אחר."""
    res = client.post("/api/solve", json={"codes": ["61753"], "semester": "א"})
    assert res.headers.get("Cache-Control") == "no-store"


def test_bootstrap_is_not_publicly_cached(client):
    """‏bootstrap מחזיר את ``data/profile.json`` ואינו ברשימת ההיתר."""
    res = client.get("/api/bootstrap")
    assert res.headers.get("Cache-Control") == "no-store", (
        "‏/api/bootstrap נפתח למטמון משותף — הוא נושא פרופיל"
    )


def test_an_unlisted_api_endpoint_defaults_to_no_store(client):
    """ברירת המחדל היא איסור. נקודת קצה חדשה אינה נדלפת רק מפני ששכחו אותה."""
    res = client.post("/api/courses", json={"codes": ["61753"], "fetch_missing": False})
    assert res.headers.get("Cache-Control") == "no-store"


def test_an_api_error_is_not_cached(client):
    """תשובת שגיאה מנקודת קצה שניתנת למטמון עדיין אסורה לשמירה.

    ‏אחרת תקלה רגעית נתקעת בקצה לחמש דקות ומוגשת לכל מי שמגיע אחריה.
    """
    res = client.get("/api/semester/99/courses?program=" + quote(SOFTWARE))
    assert res.status_code >= 400
    assert res.headers.get("Cache-Control") == "no-store", (
        f"שגיאה {res.status_code} נשמרה במטמון"
    )


def test_static_assets_are_cached_for_a_day(client):
    res = client.get("/static/app.js")
    assert res.status_code == 200
    assert res.headers.get("Cache-Control") == "public, max-age=86400"


def test_static_is_not_marked_immutable(client):
    """שמות הקבצים אינם נושאים גיבוב, ולכן ``immutable`` היה שקר.

    ‏פריסה מחליפה את התוכן מאחורי אותה כתובת בדיוק; ``immutable`` אומר
    לדפדפן לא לבדוק אפילו אחרי ‏reload.
    """
    cc = client.get("/static/app.js").headers.get("Cache-Control", "")
    assert "immutable" not in cc, cc


def test_the_page_itself_is_revalidated(client):
    """הדף חייב להיות טרי, אחרת שינוי בתבנית אינו מגיע למסך כלל."""
    assert client.get("/").headers.get("Cache-Control") == "no-cache"


# ==========================================================================
# 2. ‏/healthz
# ==========================================================================
def test_healthz_is_200_when_a_catalog_is_loaded(client):
    res = client.get("/healthz")
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["course_count"] > 0


def test_healthz_is_503_when_the_catalog_is_empty(tmp_path, monkeypatch):
    """התקלה שהבדיקה קיימת בשבילה: נתיב קטלוג שגוי או ‏volume שלא עלה.

    ‏בדיקה שמסתפקת ב"הפורט פתוח" הייתה מכריזה על פריסה כזאת כתקינה.
    """
    monkeypatch.setenv("SLOTWISE_CATALOG_DIR", str(tmp_path / "nothing-here"))
    import importlib

    import shipped_catalog

    importlib.reload(shipped_catalog)
    try:
        app = create_app(config={"allow_network": False}, db_root=tmp_path / "db")
        res = app.test_client().get("/healthz")
        assert res.status_code == 503, f"קטלוג ריק החזיר {res.status_code}"
        assert res.get_json()["ok"] is False
        assert res.get_json()["course_count"] == 0
    finally:
        # ‏להחזיר את המודול למצבו, אחרת כל בדיקה שתרוץ אחריה תראה קטלוג ריק.
        monkeypatch.undo()
        importlib.reload(shipped_catalog)


def test_healthz_says_which_catalog_it_looked_at(client):
    """‏"ריק" בלי "ריק איפה" אינו מספיק כדי לתקן פריסה."""
    assert client.get("/healthz").get_json().get("catalog", "").endswith("catalog.jsonl")


def test_healthz_is_never_cached(client):
    """בדיקת בריאות שנשמרת במטמון מדווחת על העבר."""
    assert client.get("/healthz").headers.get("Cache-Control") == "no-store"


def test_healthz_exists_without_the_ui(tmp_path):
    """פריסת ‏API בלבד עדיין צריכה בדיקת בריאות."""
    app = create_app(config={"allow_network": False}, serve_ui=False)
    assert app.test_client().get("/healthz").status_code == 200
