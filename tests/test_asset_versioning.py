# -*- coding: utf-8 -*-
"""
‏``?v=<גיבוב>`` על הנכסים הסטטיים — ולמה בלעדיו הכותרת יוצאת ריקה.

‏התקלה שהקובץ הזה נכתב בשבילה (2026-09-20)
-------------------------------------------
‏אחרי הפעלה מחדש של השרת ורענון, שורת הטריות בכותרת יצאה **ריקה** והנקודה
אפורה. השרת היה תקין לגמרי: ‏``/api/bootstrap`` החזיר
‏``catalog_built_at: "2026-09-19T02:34:09Z"``, ‏``/api/catalog/meta`` החזיר
‏571 קורסים, והקטלוג נטען מהנתיב הנכון.

מה שנשבר היה **הצמד** שהדפדפן הרכיב:

  * ‏``index.html`` מוגש עם ``no-cache``, ו-``window.STRINGS`` מוטבע בתוכו —
    כלומר הנוסח תמיד טרי.
  * ‏``/static/app.js`` הוא כתובת קבועה בלי חתימה בשם, עם ``max-age=86400``
    — כלומר ה-JavaScript יכול להיות בן יממה.

באותו יום נמחקו מ-``strings.json`` מפתחות שה-JS הקודם עוד ביקש
(‏``app.header.builtAt`` ואחרים). ‏``T()`` מחזיר מחרוזת **ריקה** כשאין
מפתח ומחוץ ל-‎?debug=1‎ — ולכן השורה צוירה ריקה, בלי שום שגיאת JavaScript
שתסגיר את הסיבה. שוחזר בדפדפן אמיתי מול השרת שרץ: ‏``missingStrings()``
החזיר בדיוק את שלושת המפתחות שנמחקו.

‏הכתובת תלוית-תוכן סוגרת את זה מהשורש: משתנה הקובץ ⇐ משתנה הכתובת ⇐
הדפדפן **חייב** למשוך. אי אפשר עוד להרכיב דף מהיום עם קוד מאתמול.

‏מה שנבדק כאן, ומה לא
----------------------
‏ההתאמה *בתוך העץ* בין ``strings.json`` ל-``app.js`` כבר שמורה
ב-``test_rendered_copy_browser.py::test_missing_string_registry_is_empty``.
הקובץ הזה שומר על הדבר השני, זה שאותה בדיקה לא יכולה לראות: שהדפדפן לא
יכול להחזיק את הקובץ הישן אחרי שהוא השתנה.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT / "src"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from web import api as api_mod  # noqa: E402

#: ‏?v=<hex> — עשרה תווים מ-sha1. הצורה, לא הערך.
VERSION_RE = re.compile(r"\?v=([0-9a-f]{10})\b")

#: כל נכס שהעמוד טוען, וששינוי בו חייב להגיע לדפדפן מיד.
ASSETS = ("app.js", "style.css", "theme.js")


@pytest.fixture()
def client():
    app = api_mod.create_app({"allow_network": False})
    return app, app.test_client()


def _html(client) -> str:
    res = client.get("/")
    assert res.status_code == 200, res.status_code
    return res.get_data(as_text=True)


# ==========================================================================
# 1. מה שהדף מפנה אליו
# ==========================================================================
def test_every_asset_url_carries_a_content_version(client):
    app, cl = client
    html = _html(cl)
    for name in ASSETS:
        found = re.search(re.escape(f"/static/{name}") + r"\?v=([0-9a-f]{10})\b", html)
        assert found, f"‏/static/{name} מוגש בלי ?v= — מטמון ישן יכול לשרוד פריסה"


def test_the_plain_path_is_still_in_the_page(client):
    """‏``?v=`` נוסף לנתיב ולא מחליף אותו.

    ‏``tests/test_web.py`` מחפש את המחרוזת ``/static/app.js`` גם בקובץ שעל
    הדיסק וגם בתשובה, ‏DEPLOY.md מריץ עליה ``curl``, והשרת מגיש את אותה
    נקודת קצה. נתיב מגובב בשם הקובץ היה שובר את שלושתם.
    """
    app, cl = client
    html = _html(cl)
    for name in ASSETS:
        assert f"/static/{name}" in html
    on_disk = (ROOT / "src" / "web" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    assert "/static/app.js" in on_disk


def test_every_versioned_url_actually_serves(client):
    """שאילתה אינה משנה מה מוגש — אבל עדיף לדעת את זה מבדיקה ולא מ-404."""
    app, cl = client
    html = _html(cl)
    urls = set(
        re.findall(r'(?:src|href)\s*=\s*["\'](/static/[^"\']+)', html)
    )
    assert urls, "העמוד אינו טוען אף נכס סטטי"
    for url in urls:
        assert VERSION_RE.search(url), url
        assert cl.get(url).status_code == 200, url


# ==========================================================================
# 2. הערובה עצמה: התוכן משתנה ⇐ הכתובת משתנה
# ==========================================================================
def _versions(app) -> dict[str, str]:
    with app.test_request_context("/"):
        return {name: api_mod._asset_version(name) for name in ASSETS}


def test_the_version_changes_when_the_file_changes(tmp_path):
    """‏**זו הבדיקה שכל הקובץ קיים בשבילה.**

    ‏מועתק לתיקייה זמנית ונערך שם: העץ האמיתי לא נוגע, והשינוי הוא בדיוק
    מה שפריסה עושה — אותו שם קובץ, תוכן אחר.
    """
    static = tmp_path / "static"
    static.mkdir()
    src = ROOT / "src" / "web" / "static"
    for name in ASSETS:
        shutil.copy2(src / name, static / name)

    app = api_mod.create_app({"allow_network": False})
    app.static_folder = str(static)

    before = _versions(app)
    assert all(v != "0" for v in before.values()), before

    (static / "app.js").write_text(
        (static / "app.js").read_text(encoding="utf-8") + "\n// deploy\n",
        encoding="utf-8",
    )

    after = _versions(app)
    assert after["app.js"] != before["app.js"], (
        "‏app.js השתנה והכתובת לא — דפדפן עם מטמון חם ימשיך להריץ את הישן"
    )
    # ‏שכן שלא נגעו בו אינו מקבל כתובת חדשה: אחרת כל פריסה הייתה מבטלת את
    # המטמון של כל הנכסים, וזה בדיוק מה שהגיבוב בא למנוע.
    assert after["style.css"] == before["style.css"]


def test_the_version_is_stable_while_the_file_is_not_touched(client):
    app, _cl = client
    assert _versions(app) == _versions(app)


def test_a_missing_asset_does_not_break_the_page(tmp_path):
    """קובץ חסר הוא ‏404 שרואים. תווית גרסה מומצאת רק הייתה מסתירה אותו."""
    app = api_mod.create_app({"allow_network": False})
    app.static_folder = str(tmp_path)
    with app.test_request_context("/"):
        assert api_mod._asset_version("app.js") == "0"


# ==========================================================================
# 3. סובלנות לשרת שעלה לפני השינוי הזה
# ==========================================================================
def test_the_page_still_renders_without_the_jinja_global():
    """‏תבנית נטענת מחדש בזמן ריצה, ‏api.py לא.

    ‏``TEMPLATES_AUTO_RELOAD`` אומר ששרת שעלה אתמול יגיש את ``index.html``
    של היום — אבל עם ה-``api.py`` של אתמול, שבו ``asset_v`` אינו רשום.
    ‏עם ``StrictUndefined`` זה היה ‏500 על הדף כולו, וזו תקלה גרועה יותר
    מזו שהשינוי בא לתקן. ‏``if asset_v is defined`` הופך אותה לכתובת בלי
    ‏``?v=``, כלומר להתנהגות של אתמול בדיוק.
    """
    app = api_mod.create_app({"allow_network": False})
    app.jinja_env.globals.pop("asset_v", None)
    res = app.test_client().get("/")
    assert res.status_code == 200, (
        "‏הדף נפל כש-asset_v אינו רשום — שרת ישן שמגיש תבנית חדשה יחזיר 500"
    )
    html = res.get_data(as_text=True)
    assert "/static/app.js" in html
