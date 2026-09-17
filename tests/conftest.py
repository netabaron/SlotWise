# -*- coding: utf-8 -*-
"""
‏conftest.py — הבדיקות קוראות קטלוג **קפוא**, לא את הקטלוג שנשלח.

הבעיה שזה פותר
---------------
עשרות בדיקות מקבעות ערכים שנגזרים מהקטלוג: ימי המערכת האופטימלית, מספר
הקבוצות לכל קורס, שם מרצה. עד כאן הן קראו את ``data/catalog/``, שהוא
**הפלט של הצינור הלילי**. מרגע שהצינור רץ, כל שינוי אמיתי בידיעון היה
מפיל אותן — לא בגלל באג בקוד, אלא בגלל שקורס קיבל קבוצה נוספת.

זה נמדד, לא נחזה: בנייה מחדש מ-``data/raw`` הנוכחי נותנת ל-61753 חמש
קבוצות בסמסטר א' במקום ארבע, וזה מזיז את המערכת האופטימלית מימים
‏[1,2,3,4] ל-[1,3,4,5] ומפיל את
``test_web.py::test_solve_returns_schedules_with_the_full_shape``.

הפתרון
-------
‏``tests/fixtures/catalog/`` הוא עותק קפוא של הקטלוג. הוא משתנה **רק**
כשמפתח/ת מריצים ``scripts/update_test_fixture.py`` בכוונה, ואז מעדכנים
איתו את הערכים המקובעים באותו commit. כך כישלון בבדיקה חוזר להיות מה
שהוא אמור להיות: שינוי בקוד, לא שינוי בנתונים.

איך זה עובד
------------
‏``src/shipped_catalog.py`` קורא את ``SLOTWISE_CATALOG_DIR`` **בזמן
ייבוא**. ‏pytest מייבא את ``conftest.py`` לפני כל מודול בדיקה, ולכן
הצבת המשתנה כאן — ברמת המודול, לא בתוך fixture — מספיקה: כשמודול
בדיקה כלשהו יגיע ל-``import shipped_catalog``, הוא כבר יצביע על
הקובץ הקפוא.

‏מי שכן צריך את הקטלוג האמיתי הוא ``tests/test_catalog_invariants.py``,
והוא טוען אותו כמודול נפרד משלו במקום לגעת במצב הגלובלי הזה.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent

#: הקטלוג הקפוא שכל הבדיקות קוראות.
FIXTURE_CATALOG_DIR = TESTS_DIR / "fixtures" / "catalog"

#: הקטלוג האמיתי — הפלט של הצינור. **אף בדיקה אינה קוראת אותו**, למעט
#: ‏test_catalog_invariants.py, שבודק רק תכונות שאינן תלויות בערך.
REAL_CATALOG_DIR = PROJECT_ROOT / "data" / "catalog"

for _path in (str(PROJECT_ROOT / "src"), str(PROJECT_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# ‏מוצב לפני כל ייבוא של shipped_catalog. **דריסה, לא setdefault**: אם
# הסביבה כבר נושאת ערך (למשל מ-docker-compose של מפתח/ת), הבדיקות עדיין
# חייבות לרוץ מול הקובץ הקפוא, אחרת הן מודדות משהו אחר לגמרי.
os.environ["SLOTWISE_CATALOG_DIR"] = str(FIXTURE_CATALOG_DIR)

# רשת ביטחון: אם משהו כבר ייבא את המודול לפני ה-conftest (הרצה ישירה של
# קובץ בדיקה, ‏plugin, ייבוא מוקדם), הצבת המשתנה לבדה מאחרת את המועד.
# ‏אז מתקנים את הנתיבים שכבר נקבעו ומרעננים את המטמון.
if "shipped_catalog" in sys.modules:  # pragma: no cover - תלוי בסדר ייבוא
    _sc = sys.modules["shipped_catalog"]
    _sc.CATALOG_DIR = FIXTURE_CATALOG_DIR
    _sc.CATALOG_PATH = FIXTURE_CATALOG_DIR / "catalog.jsonl"
    _sc.META_PATH = FIXTURE_CATALOG_DIR / "catalog.meta.json"
    try:
        _sc.load(refresh=True)
    except Exception:  # noqa: BLE001
        pass


def pytest_report_header(config) -> list[str]:
    """אומר בראש כל הרצה איזה קטלוג נקרא. שקט כאן הוא בדיוק מה שהסתיר את
    הבעיה קודם, ולכן זה מודפס תמיד ולא רק ב-verbose."""
    try:
        import shipped_catalog  # noqa: PLC0415

        count = len(shipped_catalog.courses())
        stamp = shipped_catalog.built_at() or "(none)"
        where = shipped_catalog.CATALOG_PATH
    except Exception as exc:  # noqa: BLE001
        return [f"catalog: לא ניתן לטעון ({exc})"]
    frozen = Path(where).resolve().is_relative_to(FIXTURE_CATALOG_DIR.resolve())
    return [
        f"catalog: {where} ({count} courses, built {stamp}) "
        f"[{'frozen fixture' if frozen else 'NOT the fixture'}]"
    ]
