"""מקור נתונים יציב לבדיקות: הקטלוג שנשלח עם הקוד, לא המאגר המקומי.

למה הקובץ הזה קיים
-------------------
שמונה־עשרה בדיקות קיבעו מספרים מדויקים — "6 קורסים ו-27 קבוצות", גודל
מנייה, שם מרצה — מול ``data/db/sections.json``. הקובץ ההוא **אינו במאגר
הקוד** (‏gitignored), הוא חי רק על המכונה, **והאפליקציה הרצה כותבת אותו
מחדש**. ב-2026-09-09 מספר הקבוצות זז 1444 ⇐ 1445 בין שתי הרצות של אותה
סוויטה, ומספר הכישלונות עלה משתיים בבוקר לשמונה־עשרה בערב בלי שורת קוד
אחת שהשתנתה בין לבין.

‏``data/catalog.jsonl`` הוא ההפך: הוא **כן** במאגר, הוא נבנה בכוונה
ובשליטה (``build_catalog.py``, עם שש שערי איכות), והוא אותו מקור שהשרת
נופל אליו כשאין נתונים מקומיים.

**המספרים לא הוחלשו כדי לעבור.** מול הקטלוג הם יוצאים בדיוק כפי שנכתבו:
27 קבוצות בסך הכול, ו-‎{11069: 2, 61753: 4, 61756: 7, 61757: 6, 61832: 5,
62027: 3}‎ לכל קורס. הבדיקות תמיד היו צודקות; מה שזז מתחתיהן היה המאגר
המקומי. ההצמדה לקטלוג מחזירה למספרים את המשמעות שהייתה להם ומייצבת אותה.

‏הקריאה עוברת דרך ``Store`` ולא דרך פענוח משלה: אותו נתיב קוד בדיוק שדרכו
האפליקציה קוראת, ולכן הבדיקות ממשיכות לבדוק את מה שהן בדקו — ורק המקור
התחלף.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

#: הסמסטר שהבדיקות מתארות. הקטלוג נושא את כל הסמסטרים בכוונה, ולכן מי
#: שקורא חייב לבחור — בלי זה קבוצות סמסטר ב' נכנסות למרחב החיפוש.
SEMESTER = "א"

_dir: Path | None = None


def catalog_db_dir() -> Path:
    """תיקייה זמנית שבה ``sections.json`` הוא הקטלוג שנשלח עם הקוד.

    נבנית פעם אחת לכל הרצה. ‏``Store`` מקבל תיקייה, ולכן זו הדרך להאכיל
    אותו מקטלוג בלי לגעת ב-``data/db`` של המשתמש/ת.
    """
    global _dir
    if _dir is not None:
        return _dir

    import shipped_catalog  # noqa: PLC0415 — אחרי הזרקת sys.path

    entries = shipped_catalog.as_sections_entries(SEMESTER)
    if not entries:
        raise RuntimeError(
            "‏data/catalog.jsonl ריק או חסר — אי אפשר להריץ בדיקות נתונים בלעדיו"
        )
    out = Path(tempfile.mkdtemp(prefix="slotwise-catalog-"))
    (out / "sections.json").write_text(
        json.dumps(
            {"schema": "sections", "version": 1,
             "updated_at": shipped_catalog.built_at(), "courses": entries},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _dir = out
    return out


def catalog_courses() -> dict:
    """``{code: Course}`` מהקטלוג, דרך אותו ``Store`` שהאפליקציה משתמשת בו."""
    from store import Store  # noqa: PLC0415

    return Store(str(catalog_db_dir())).load_all()
