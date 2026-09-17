#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/seed_dev_data.py — מייצר את הקבצים המקומיים שאינם במאגר הקוד.

למה הוא קיים
-------------
‏``data/db/`` ו-``data/profile.json`` שניהם ב-.gitignore, ובצדק: הראשון
הוא תוכן של המכללה, השני הוא מידע אישי. ‏**אבל חלק מהבדיקות זקוקות להם.**
‏נמדד ב-2026-09-16 על שכפול נקי: ‏4 בדיקות נופלות ו-33 שגיאות, כולן
‏``FileNotFoundError`` —

  * ‏``tests/test_multifaculty.py::_copy_db`` מעתיק את ``data/db`` כולו
    לתיקייה זמנית, ונופל כשאין מה להעתיק.
  * ‏``tests/test_web.py`` קורא את ``data/profile.json`` לברירות המחדל.

הסקריפט הזה סוגר את הפער בלי לגעת באף בדיקה: הוא בונה מסד מינימלי
**מהקטלוג שכן נמצא במאגר**, ומעתיק את הפרופיל לדוגמה. אותו קלט בדיוק
שהאפליקציה נופלת אליו כשאין מסד מקומי, ולכן הבדיקות רואות את מה שרואה
שכפול נקי — לא נתונים שנוצרו במיוחד בשבילן.

    python scripts/seed_dev_data.py           # לא דורס קיים
    python scripts/seed_dev_data.py --force   # כן דורס

‏זה **לא** תחליף לגרידה. המסד שנוצר כאן מכיל את מה שהקטלוג מכיל, ותו לא:
אין בו ``details.json`` מלא, אין בו יומני שינויים, ואין בו היסטוריה.
לפיתוח ולבדיקות זה מספיק; לשימוש אמיתי מריצים ``refresh.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

DATA = PROJECT_ROOT / "data"
DB_DIR = DATA / "db"
PROFILE = DATA / "profile.json"
PROFILE_EXAMPLE = DATA / "profile.example.json"


def _write(path: Path, payload: dict, *, force: bool) -> bool:
    if path.exists() and not force:
        print(f"  קיים, לא נגעתי: {path.relative_to(PROJECT_ROOT)}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"  נכתב: {path.relative_to(PROJECT_ROOT)}")
    return True


#: הסמסטר שהמסד נבנה עבורו. ‏**לא** "כל הסמסטרים", וזה לא עניין של טעם:
#: ‏``Store`` כותב ``sections.json`` מסונן לסמסטר (ראו ההערה ב-store.py),
#: והבדיקות מתארות סמסטר אחד — ``tests/catalog_source.py`` קובע ``"א"``.
#:
#: ‏מדוע זה חשוב יותר ממה שזה נשמע: מסד עם כל הסמסטרים נושא 2167 קבוצות
#: במקום 1179, כלומר כפליים מועמדים לכל רכיב. ‏``enumerate_selections``
#: הוא מנייה ממצה, ולכן הכפלת המועמדים מפוצצת את מרחב החיפוש — סוויטת
#: הבדיקות עברה מ-‏6 דקות ליותר מ-40 בניסיון הראשון כאן (2026-09-16),
#: וזה היה עובר את ה-timeout של ‏CI.
DEFAULT_SEMESTER = "א"


def seed_db(*, force: bool, semester: str = DEFAULT_SEMESTER) -> None:
    """בונה ``data/db`` מהקטלוג שנשלח עם הקוד."""
    import shipped_catalog  # type: ignore

    if not shipped_catalog.available():
        raise SystemExit(
            "אין קטלוג ב-data/catalog — אי אפשר לייצר מסד בלעדיו.\n"
            "(no catalog at data/catalog; nothing to seed from)"
        )

    stamp = shipped_catalog.built_at()

    # ‏sections.json — מסונן לסמסטר אחד. ראו DEFAULT_SEMESTER למה.
    entries = shipped_catalog.as_sections_entries(semester)
    if not entries:
        raise SystemExit(f"אין קורסים בקטלוג לסמסטר {semester!r}.")
    groups = sum(
        len(((v.get("course") or v).get("groups")) or []) for v in entries.values()
    )
    print(f"  (סמסטר {semester}: {len(entries)} קורסים, {groups} קבוצות)")
    _write(
        DB_DIR / "sections.json",
        {"schema": "braude-schedule-builder/sections-db", "version": 1,
         "updated_at": stamp, "courses": entries},
        force=force,
    )

    # ‏catalog.json — רשימת הקורסים שנפתחים השנה. ‏build_catalog.py קורא
    # אותה כדי לדעת מה לשלוף, ובלעדיה שער הכיסוי מחלק באפס ונכשל.
    meta = shipped_catalog.meta()
    _write(
        DB_DIR / "catalog.json",
        {"schema": "braude-schedule-builder/catalog", "version": 1,
         "meta": {"fetched_at": stamp, "year": meta.get("year", ""),
                  "year_gregorian": meta.get("year_gregorian", "")},
         "courses": {code: {"name": rec.get("name", ""), "status": ""}
                     for code, rec in shipped_catalog.courses().items()}},
        force=force,
    )

    # ‏details.json — ריק בכוונה. הקטלוג אינו נושא נ"ז ותנאי קדם, ולהמציא
    # אותם כאן היה גרוע מלהשאיר "לא ידוע": הבדיקות מבדילות בין השניים.
    _write(
        DB_DIR / "details.json",
        {"schema": "braude-schedule-builder/course-details", "version": 1,
         "courses": {}},
        force=force,
    )

    _write(
        DB_DIR / "tracked.json",
        {"schema": "braude-schedule-builder/tracked", "version": 1,
         "codes": sorted(shipped_catalog.courses())},
        force=force,
    )


#: ‏מה שסוויטת הבדיקות מקבעת לגבי ``data/profile.json``.
#: ‏``tests/test_web.py`` (שורות 109–111) מגדיר ‏TERM="א" ו-
#: ‏CURRICULUM_SEMESTER="5", ו-``test_bootstrap_carries_the_profile_defaults``
#: פותח בעוגן מפורש: ‏``assert (want_semester, want_term) == (CURRICULUM_SEMESTER, TERM)``.
#:
#: ‏כלומר הבדיקה מקבעת את הפרופיל **האישי של המתחזק/ת** — שנה ג', סמסטר 5.
#: ‏``data/profile.example.json`` הוא שנה א', סמסטר 1, ובצדק: הוא הדוגמה
#: שסטודנט/ית חדש/ה מעתיק/ה. לכן העתקה פשוטה של הדוגמה מפילה את הבדיקה,
#: וזה נכון לכל שכפול נקי שעקב אחרי ההוראה שב-.gitignore — לא רק כאן.
#: ‏אומת ‏2026-09-16: ‏('1', 'א') == ('5', 'א') נכשל.
#:
#: ‏הסקריפט כותב פרופיל שתואם לעוגן, ולא נוגע בדוגמה. ‏**אם העוגן בבדיקה
#: ישתנה, יש לעדכן כאן.**
TEST_ANCHOR = {
    "year_of_study": 3,
    "year_label": "שנה ג'",
    "term": "א",
    "curriculum_semester": "5",
}


def seed_profile(*, force: bool) -> None:
    """כותב ``data/profile.json`` מהדוגמה, מותאם לעוגן שהבדיקות מקבעות."""
    if PROFILE.exists() and not force:
        print(f"  קיים, לא נגעתי: {PROFILE.relative_to(PROJECT_ROOT)}")
        return
    if not PROFILE_EXAMPLE.is_file():
        raise SystemExit(f"אין {PROFILE_EXAMPLE} לגזור ממנו.")

    profile = json.loads(PROFILE_EXAMPLE.read_text(encoding="utf-8"))
    student = profile.setdefault("student", {})
    student.update(TEST_ANCHOR)

    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"  נכתב: {PROFILE.relative_to(PROJECT_ROOT)} "
        f"(שנה {student['year_of_study']}, סמסטר {student['curriculum_semester']} — "
        f"העוגן של הבדיקות, לא ברירת המחדל שבדוגמה)"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="מייצר data/db ו-data/profile.json לפיתוח ולבדיקות."
    )
    ap.add_argument("--force", action="store_true",
                    help="לדרוס קבצים קיימים (ברירת מחדל: לא לגעת)")
    ap.add_argument("--semester", default=DEFAULT_SEMESTER,
                    help=f"הסמסטר שהמסד נבנה עבורו (ברירת מחדל {DEFAULT_SEMESTER})")
    args = ap.parse_args(argv)

    print("מסד מינימלי מהקטלוג:")
    seed_db(force=args.force, semester=args.semester)
    print("פרופיל:")
    seed_profile(force=args.force)
    print("\nמוכן. ‏זהו מסד לפיתוח בלבד — לנתונים אמיתיים יש להריץ refresh.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
