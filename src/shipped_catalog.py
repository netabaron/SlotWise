# -*- coding: utf-8 -*-
"""
הקטלוג שנשלח יחד עם הקוד — ``data/catalog/catalog.jsonl``.

למה הוא קיים
-------------
עד עכשיו כל משתמש/ת היו צריכים לגרוד את הידיעון בעצמם. מי שמשכפל את
המאגר קיבל אפליקציה שעולה ומציגה **אפס קורסים**, כי ``data/db/`` ו-
``data/raw/`` שניהם ב-.gitignore. הקטלוג הזה נבנה פעם אחת (ראי
``build_catalog.py``) ונכנס לגיט, ולכן שכפול נקי מקבל מיד את כל 572
הקורסים — בלי רשת, בלי המתנה, ובלי לגעת בשרת של המכללה.

איך הוא משתלב
--------------
הוא **שכבת בסיס מתחת** ל-``data/db``, לא במקומו:

    per-user db  (מה שהמשתמש/ת שלפו בעצמם)   ← מנצח
    ------------------------------------------
    shipped      (מה שנשלח עם הקוד)            ← ממלא את השאר

הצירוף נעשה בנקודה אחת, ``Store._load_sections_db``, ולכן ``load_course``,
``load_all`` ו-``codes`` יורשים אותו בלי שינוי.

מה הוא **לא** יודע
-------------------
הוא יודע מתי הוא נבנה, ותו לא. הוא אינו יודע — ואינו יכול לדעת — אם
הידיעון השתנה מאז. כל נוסח שמבוסס עליו חייב לדבר על **תאריך הבנייה**
ולא לרמוז על מצב הידיעון החי.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any

#: שורש הפרויקט — שתי רמות מעל הקובץ הזה (src/ -> root).
PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: תיקיית הקטלוג. ‏``SLOTWISE_CATALOG_DIR`` דורס — כך מגישים קטלוג שנבנה
#: אחרי שנבנתה התמונה, בלי לבנות אותה מחדש (‏DEPLOY.md).
#:
#: ‏הקטלוג עבר מ-``data/`` ל-``data/catalog/`` ב-2026-09-16, כשהבנייה
#: הפכה לעבודת cron: שני הקבצים הם עכשיו **הפלט** של הצינור, והם היחידים
#: תחת ``data/`` שהוא כותב. תיקייה משלהם היא מה שמאפשר ל-.gitignore
#: להבחין בין פלט שנכנס לגיט לבין ``data/raw`` ו-``data/db`` שאינם.
CATALOG_DIR = Path(
    os.environ.get("SLOTWISE_CATALOG_DIR", "").strip()
    or (PROJECT_ROOT / "data" / "catalog")
).expanduser()

CATALOG_PATH = CATALOG_DIR / "catalog.jsonl"
META_PATH = CATALOG_DIR / "catalog.meta.json"

#: מקור הרשומה, כפי שהוא נרשם ב-CourseMeta.source_url. מאפשר להבחין
#: בין "נשלח עם הקוד" ל"נשלף כאן" בלי לנחש לפי היעדר שדות.
SHIPPED_SOURCE = "shipped-catalog"

_CACHE: dict[str, Any] | None = None
_STAMP: tuple[float, float] | None = None


def _mtimes() -> tuple[float, float]:
    def m(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    return (m(CATALOG_PATH), m(META_PATH))


def load(refresh: bool = False) -> dict[str, Any]:
    """
    טוען את הקטלוג, עם מטמון שמתבטל כשהקובץ משתנה.

    הטעינה עצלה ומקוששת לפי ``mtime`` — בדיוק כמו ``strings.py``, ומאותה
    סיבה: מטמון ברמת המודול שאינו נבדק מול הדיסק שרד ריענון שלם והגיש עץ
    ישן כל חיי התהליך. זו הייתה תקלת המחרוזות הריקות.

    Returns:
        ``{"courses": {code: record}, "meta": {...}}``. חסר קובץ = ריק.
    """
    global _CACHE, _STAMP
    stamp = _mtimes()
    if _CACHE is not None and not refresh and _STAMP == stamp:
        return _CACHE

    courses: dict[str, dict] = {}
    if CATALOG_PATH.is_file():
        with io.open(CATALOG_PATH, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue  # שורה פגומה אינה מפילה את הקטלוג כולו
                code = str(rec.get("code") or "").strip()
                if code:
                    courses[code] = rec

    meta: dict[str, Any] = {}
    if META_PATH.is_file():
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        except ValueError:
            meta = {}

    _CACHE = {"courses": courses, "meta": meta}
    _STAMP = stamp
    return _CACHE


def available() -> bool:
    """האם יש קטלוג שנשלח בכלל."""
    return bool(load().get("courses"))


def built_at() -> str:
    """מתי הקטלוג נבנה, ‏ISO-8601 UTC. ריק = אין קטלוג.

    **זה כל מה שידוע.** אין כאן שום מידע על הידיעון החי.
    """
    return str((load().get("meta") or {}).get("built_at") or "")


def meta() -> dict[str, Any]:
    return dict(load().get("meta") or {})


def courses() -> dict[str, dict]:
    return dict(load().get("courses") or {})


def index() -> dict[str, dict]:
    """הקטלוג בצורת אינדקס — ``{code: {"name": ...}}`` — לחיפוש ולעיון."""
    return {
        code: {"name": rec.get("name") or "", "credits": rec.get("credits") or 0.0}
        for code, rec in (load().get("courses") or {}).items()
    }


def as_sections_entries(semester: str = "") -> dict[str, dict]:
    """
    הקטלוג בצורה ש-``Store._split_entry`` כבר יודע לקרוא.

    ``semester``: סינון בזמן **קריאה**. הקובץ נושא את כל הסמסטרים בכוונה
    (ראי ``build_catalog.py``), ולכן מי שקורא חייב לבחור. בלי הסינון
    הזה קבוצות סמסטר ב' — שאין להן מפגשים ולכן אינן מתנגשות עם דבר —
    נכנסות למרחב החיפוש ומנפחות אותו בלי לתרום פתרון אחד.

    לכל רשומה מוצמד ``meta`` סינתטי שבו ``fetched_at`` הוא **תאריך בניית
    הקטלוג**. זו לא הונאה אלא ההפך: כך ``Store.is_stale`` מודד את הגיל
    מול המספר הנכון, וקורס שנשלח עם הקוד אינו נחשב "מיושן" רק מפני
    שהמשתמש/ת מעולם לא שלפו אותו בעצמם.
    """
    stamp = built_at()
    data = load()
    info = data.get("meta") or {}
    out: dict[str, dict] = {}
    for code, rec in (data.get("courses") or {}).items():
        if semester:
            groups = [
                g for g in (rec.get("groups") or [])
                if not g.get("semester") or g.get("semester") == semester
            ]
            rec = dict(rec, groups=groups)
        out[code] = {
            "course": rec,
            "meta": {
                "fetched_at": stamp,
                "last_attempt_at": stamp,
                "year": info.get("year") or "",
                "year_gregorian": info.get("year_gregorian") or "",
                # ריק בכוונה: הקטלוג נושא את **כל** הסמסטרים, והסינון
                # נעשה בזמן קריאה. ראי build_catalog.py.
                "semester": "",
                "source_url": SHIPPED_SOURCE,
                "group_count": len(rec.get("groups") or []),
                "ok": True,
            },
        }
    return out
