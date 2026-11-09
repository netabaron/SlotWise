# -*- coding: utf-8 -*-
"""‏``api.base_course_name`` ו-``baseCourseName`` ב-app.js חייבים לומר אותו דבר.

החיפוש בממשק אומר "בתוכנית שלך: פיזיקה 2 IE (11210)" לפי הכלל ב-JS, ו-
‏``/api/solve`` מציע "להחליף" לפי העותק בפייתון (2026-11-09). אם השניים
נפרדים, המסך יגיד דבר אחד בשלב הקורסים ודבר אחר בקופסת "אין מערכת".

הפונקציות נשלפות **מתוך app.js עצמו** ומורצות ב-Chromium — לא עותק שלהן
בבדיקה, שהיה יכול להישאר מאחור בדיוק כמו העותק שהבדיקה שומרת עליו.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from src.web.api import base_course_name  # noqa: E402

APP_JS = ROOT / "src" / "web" / "static" / "app.js"

#: חמש הגרסאות של פיזיקה 2, בשמות שהקטלוג נותן להן.
PHYSICS_2 = {
    "11026": "פיזיקה 2ב",
    "11210": "פיזיקה 2 IE",
    "11212": "פיזיקה 2 מכ'",
    "11232": "פיזיקה 2 מ'",
    "421209": "פיזיקה 2 אז'",
}

#: המקרים שהכלל מבחין ביניהם, כדי שהשוואה לא תעבור רק על הדרך הקלה.
EDGES = [
    "פרויקט גמר שלב א'",          # ‏"א'" הוא חלק מהשם
    "פרויקט גמר שלב ב׳",           # גרש עברי
    "מבוא למחשבים IE",              # תג מחלקה בלי מספר
    "סטטיסטיקה ל'",                 # תג מחלקה עברי
    "חדו\"א 1 מורחב",
    "חדו״א  2",                      # גרשיים עבריים ורווח כפול
    "  אנגלית   מתקדמים ב'  ",
    "מעבדה במיב\"םׁ(CIMׂ)",
    "IE",
    "",
]


def _js_function(source: str, name: str) -> str:
    """גוף פונקציה ברמה העליונה של ה-IIFE (הזחה של שני רווחים)."""
    match = re.search(
        r"^  function %s\(.*?^  \}$" % re.escape(name), source, re.S | re.M
    )
    assert match, f"{name} לא נמצאה ב-app.js"
    return match.group(0)


@pytest.fixture(scope="module")
def js_base_names():
    source = APP_JS.read_text(encoding="utf-8")
    body = _js_function(source, "txt") + "\n" + _js_function(source, "baseCourseName")
    names = list(PHYSICS_2.values()) + EDGES
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            out = page.evaluate(
                "(names) => { %s\n return names.map(baseCourseName); }" % body,
                names,
            )
        finally:
            browser.close()
    return dict(zip(names, out))


@pytest.mark.parametrize("code", sorted(PHYSICS_2))
def test_every_physics_2_has_the_same_base_name_in_both(js_base_names, code):
    name = PHYSICS_2[code]
    assert base_course_name(name) == js_base_names[name] == "פיזיקה 2", (
        code, base_course_name(name), js_base_names[name]
    )


@pytest.mark.parametrize("name", EDGES)
def test_the_edge_cases_agree(js_base_names, name):
    assert base_course_name(name) == js_base_names[name], (
        name, base_course_name(name), js_base_names[name]
    )
