# -*- coding: utf-8 -*-
"""
‏browser_clock.py — שעון הדפדפן בבדיקות מקובע, ולא "היום".

הבעיה שזה פותר
---------------
הקטלוג הקפוא (``tests/fixtures/catalog``) נבנה בתאריך קבוע, אבל ``app.js``
מודד את גילו מול ``Date.now()`` של הדפדפן. ‏``CATALOG_STALE_DAYS = 45``,
ולכן מ-2026-10-24T22:35Z כל בדיקת דפדפן ראתה את באנר "הקטלוג ישן", הבאנר
דחף את העמוד למטה, וחמש בדיקות גלילה ופריסה נפלו ב-CI בלי שום שינוי בקוד.
כל סף גיל אחר ב-``app.js`` (‏24 שעות לשורת הטריות, ‏30 יום ל"חודש" בגיל
המוצג) היה עושה את אותו הדבר בתאריך אחר.

הפתרון
-------
כל הקשר דפדפן שבדיקה פותחת — ‏``browser.new_context()`` או
‏``browser.new_page()`` — מקבל שעון שמתחיל ב-``PINNED_NOW``: שבוע אחרי
‏``built_at`` של הקטלוג הקפוא. ‏``conftest.py`` מתקין את זה פעם אחת, ולכן
אף קובץ בדיקה לא צריך לזכור.

‏``set_system_time`` ולא ``set_fixed_time``: הזמן ממשיך לזרום מהנקודה
המקובעת, והטיימרים אמיתיים. ‏``app.js`` מודד הפרשי זמן ב-``Date.now()``
(למשל אנימציית הדירוג, ‏``popRank``), ושעון עומד היה משנה את ההתנהגות שלו.

‏**הנגזרת היא מהקטלוג, לא תאריך קשיח**: כש-``scripts/update_test_fixture.py``
מרענן את הקטלוג, השעון זז איתו.

בדיקה שמזייפת חותמת זמן ("קטלוג שנבנה לפני 60 יום") מחשבת אותה מ-
``PINNED_NOW`` ולא מ-``datetime.now()`` — אחרת הדפדפן והבדיקה חיים בשני
זמנים שונים. ‏``tests/test_browser_clock.py`` אוכף את שני הכללים.

השרת עצמו רץ על השעון האמיתי. ‏הקטלוג הקפוא חצה את ספי השרת (‏24 שעות,
‏שבוע לפרטים) כבר ב-2026-09, והם אינם חוזרים אחורה — לכן הם אינם משתנים
מיום ליום.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

#: ‏built_at של הקטלוג הקפוא. ‏נקרא ישירות מהקובץ ולא דרך shipped_catalog,
#: כדי שהמודול לא יקבע בעצמו את סדר הייבוא של conftest.
FIXTURE_META = Path(__file__).resolve().parent / "fixtures" / "catalog" / "catalog.meta.json"

#: כמה אחרי בניית הקטלוג הדפדפן "נמצא". ‏שבוע: מעבר ל-24 השעות של שורת
#: הטריות (כמו שהבדיקות ראו מאז 2026-09-10), מתחת ל-30 יום של "לפני חודש"
#: ומתחת ל-‏CATALOG_STALE_DAYS.
PIN_AFTER_BUILD = dt.timedelta(days=7)


def fixture_built_at() -> dt.datetime:
    stamp = json.loads(FIXTURE_META.read_text(encoding="utf-8"))["built_at"]
    return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))


#: ה"עכשיו" של כל דפדפן בבדיקות.
PINNED_NOW = fixture_built_at() + PIN_AFTER_BUILD

_installed = False
#: ‏``Browser.new_context`` המקורי, לפני העטיפה של ``install()``.
_real_new_context = None

#: ‏רצים לפני ואחרי סקריפט השעון של Playwright, בסדר שבו נוספו.
_KEEP_FRAMES = (
    "window.__realRAF = window.requestAnimationFrame;"
    " window.__realCAF = window.cancelAnimationFrame;"
)
_RESTORE_FRAMES = (
    "window.requestAnimationFrame = window.__realRAF;"
    " window.cancelAnimationFrame = window.__realCAF;"
    " delete window.__realRAF; delete window.__realCAF;"
)


def new_context_with_real_frames(browser, **kwargs):
    """הקשר עם השעון המקובע, אבל עם ``requestAnimationFrame`` של הדפדפן.

    ‏השעון של Playwright מחליף גם את ‏rAF: קריאה שלו היא טיימר על גבול של
    ‏16ms בשעון המזויף, שיורה מ-setTimeout אמיתי ולא בשלב הציור של הדפדפן.
    ‏קוד שמתקן את העמוד בכל פריים (‏``holdDuringFold`` ב-app.js) רץ אז בין
    ‏פריימים, ומעבר ‏CSS — שרץ על השעון האמיתי — מצויר פריים אחד בלי התיקון.
    ‏נמדד 2026-10-25: קפיצה של ~240px בפריים מצויר בכל הרצה עם השעון,
    ‏אפס עם ‏rAF אמיתי. ‏זה מה שהפיל לסירוגין את
    ‏``test_step_continue_no_jump_browser.py`` מאז הקיבוע.

    ‏``Date`` נשאר מקובע והטיימרים נשארים על השעון המזויף; רק ‏rAF חוזר.
    ‏לבדיקות שמודדות תנועה פריים-פריים."""
    real = _real_new_context
    if real is None:  # install() לא רץ — אין עטיפה לעקוף
        from playwright.sync_api import Browser  # noqa: PLC0415

        real = Browser.new_context
    context = real(browser, **kwargs)
    context.add_init_script(_KEEP_FRAMES)
    context.clock.set_system_time(PINNED_NOW)
    context.add_init_script(_RESTORE_FRAMES)
    return context


def install() -> None:
    """עוטף את ``Browser.new_context`` ו-``Browser.new_page`` של ה-API
    הסינכרוני. ‏הקשר שנוצר מקבל את השעון לפני שדף כלשהו נטען בו, כך שגם
    הסקריפט הראשון של העמוד רואה את ``PINNED_NOW``. ‏בלי Playwright — לא
    עושה דבר; המודולים שזקוקים לו מדלגים בעצמם."""
    global _installed, _real_new_context
    if _installed:
        return
    try:
        from playwright.sync_api import Browser  # noqa: PLC0415
    except ImportError:  # pragma: no cover - אין Playwright מותקן
        return

    real_new_context = _real_new_context = Browser.new_context
    real_new_page = Browser.new_page

    def new_context(self, *args, **kwargs):
        context = real_new_context(self, *args, **kwargs)
        context.clock.set_system_time(PINNED_NOW)
        return context

    def new_page(self, *args, **kwargs):
        page = real_new_page(self, *args, **kwargs)
        page.context.clock.set_system_time(PINNED_NOW)
        return page

    Browser.new_context = new_context
    Browser.new_page = new_page
    _installed = True
