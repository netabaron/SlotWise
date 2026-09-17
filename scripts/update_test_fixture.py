#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/update_test_fixture.py — מעדכן את הקטלוג הקפוא של הבדיקות.

מה זה
------
מעתיק את הקטלוג שנשלח (``data/catalog/``) אל ``tests/fixtures/catalog/``,
שהוא מה שכל סוויטת הבדיקות קוראת (ראו ``tests/conftest.py``).

**זו פעולה מכוונת, ולא חלק משום זרימה אוטומטית.** הצינור הלילי לעולם
אינו מריץ אותה. אם הוא היה מריץ, כל הפרדת הקפאה הזאת הייתה חסרת ערך:
הבדיקות היו שוב רצות מול נתונים שמשתנים מתחתיהן.

מתי כן להריץ
-------------
כשמחליטים **לקבע מחדש** את הבדיקות על נתונים חדשים. בדרך כלל אחרי
שהצינור הביא שינוי אמיתי בידיעון שרוצים שהבדיקות יתארו — קורס שנפתח,
קבוצה שנוספה, שעה שזזה.

הזרימה:

    1. python scripts/update_test_fixture.py
    2. python -m pytest -q          <- חלק מהבדיקות ייפלו. זה הצפוי.
    3. לעדכן את הערכים המקובעים בבדיקות שנפלו, לפי מה שהנתונים אומרים
       עכשיו. **לקרוא כל כישלון**: הוא אומר מה בדיוק זז.
    4. לעשות commit לקובץ הקפוא **ולתיקוני הבדיקות יחד**.

שלב 4 אינו קוסמטי. ‏commit שמעדכן את הקובץ הקפוא בלי לעדכן את הערכים
משאיר את main אדום; ‏commit שמעדכן ערכים בלי את הקובץ אינו ניתן לשחזור.

מתי **לא** להריץ
-----------------
כדי "לתקן" בדיקה אדומה. אם בדיקה נפלה ולא עדכנתם את הקובץ הקפוא, הנתונים
לא זזו — הקוד זז, וזה בדיוק מה שהבדיקה נועדה לתפוס.

    python scripts/update_test_fixture.py            # מעדכן
    python scripts/update_test_fixture.py --check    # רק משווה, בלי לכתוב
    python scripts/update_test_fixture.py --diff     # מה היה משתנה

קודי יציאה: ‏0 בוצע / זהה · 1 שונה (ב---check) · 2 שגיאה.
"""

from __future__ import annotations

import argparse
import collections
import filecmp
import json
import shutil
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "data" / "catalog"
FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "catalog"

#: שני הקבצים שהצינור כותב, והיחידים שהקובץ הקפוא מחזיק. ‏seed_dev_data.py
#: גוזר מהם את ``data/db`` בזמן ריצה, ולכן אין מה להקפיא מעבר לאלה.
FILES = ("catalog.jsonl", "catalog.meta.json")


def _counts(meta_path: Path) -> dict:
    try:
        return json.loads(meta_path.read_text(encoding="utf-8")).get("counts") or {}
    except Exception:  # noqa: BLE001
        return {}


def _summary(directory: Path) -> str:
    meta = directory / "catalog.meta.json"
    if not meta.is_file():
        return "(חסר)"
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return f"(מטא פגום: {exc})"
    counts = data.get("counts") or {}
    return (
        f"נבנה {data.get('built_at', '?')} · {counts.get('courses', '?')} קורסים · "
        f"{counts.get('groups', '?')} קבוצות · {counts.get('timed_meetings', '?')} מפגשים"
    )


def _identical() -> bool:
    return all(
        (SOURCE_DIR / name).is_file()
        and (FIXTURE_DIR / name).is_file()
        and filecmp.cmp(SOURCE_DIR / name, FIXTURE_DIR / name, shallow=False)
        for name in FILES
    )


def _print_diff() -> None:
    """מה זז בין הקפוא לנשלח — ברמת הספירות ורשימת הקודים."""
    old, new = _counts(FIXTURE_DIR / "catalog.meta.json"), _counts(SOURCE_DIR / "catalog.meta.json")
    keys = sorted(set(old) | set(new))
    print("\nספירות:")
    for key in keys:
        a, b = old.get(key), new.get(key)
        mark = "  " if a == b else "->"
        print(f"  {mark} {key}: {a} -> {b}")

    def codes(path: Path) -> set[str]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {str(c) for c in (data.get("codes") or [])}
        except Exception:  # noqa: BLE001
            return set()

    a = codes(FIXTURE_DIR / "catalog.meta.json")
    b = codes(SOURCE_DIR / "catalog.meta.json")
    added, removed = sorted(b - a), sorted(a - b)
    print(f"\nקורסים שנוספו: {len(added)}" + (f" ({', '.join(added[:8])})" if added else ""))
    print(f"קורסים שנעלמו: {len(removed)}" + (f" ({', '.join(removed[:8])})" if removed else ""))

    # ‏השינוי שהכי מפיל בדיקות אינו קורס שנוסף אלא קבוצה שנוספה לקורס
    # קיים: הוא מזיז את המערכת האופטימלית בלי לשנות אף ספירה גלויה.
    def groups_by_code(path: Path) -> dict[str, int]:
        out: collections.Counter[str] = collections.Counter()
        if not path.is_file():
            return out
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[str(rec.get("code"))] = len(rec.get("groups") or [])
        return out

    ga = groups_by_code(FIXTURE_DIR / "catalog.jsonl")
    gb = groups_by_code(SOURCE_DIR / "catalog.jsonl")
    moved = sorted(c for c in set(ga) & set(gb) if ga[c] != gb[c])
    print(f"\nקורסים ששינו מספר קבוצות: {len(moved)}")
    for code in moved[:10]:
        print(f"    {code}: {ga[code]} -> {gb[code]}")
    if moved:
        print("  אלה הם שיפילו בדיקות שמקבעות ימים או ספירות.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="מעדכן את הקטלוג הקפוא של הבדיקות מהקטלוג שנשלח.",
        epilog="קודי יציאה: 0 בוצע/זהה · 1 שונה (ב---check) · 2 שגיאה.",
    )
    ap.add_argument("--check", action="store_true",
                    help="רק לבדוק אם הקפוא מפגר אחרי הנשלח, בלי לכתוב")
    ap.add_argument("--diff", action="store_true",
                    help="להראות מה היה משתנה")
    args = ap.parse_args(argv)

    missing = [name for name in FILES if not (SOURCE_DIR / name).is_file()]
    if missing:
        print(f"אין מה להעתיק — חסר ב-{SOURCE_DIR}: {', '.join(missing)}")
        return 2

    print(f"נשלח:  {SOURCE_DIR}\n       {_summary(SOURCE_DIR)}")
    print(f"קפוא:  {FIXTURE_DIR}\n       {_summary(FIXTURE_DIR)}")

    same = _identical()
    if args.diff and not same:
        _print_diff()

    if same:
        print("\nזהים — אין מה לעדכן.")
        return 0

    if args.check:
        print("\nהקובץ הקפוא **אינו** זהה לקטלוג שנשלח.")
        print("זה תקין ומכוון: הבדיקות מקובעות על הקפוא. ראו את הראש של הקובץ הזה.")
        return 1

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        shutil.copyfile(SOURCE_DIR / name, FIXTURE_DIR / name)
        print(f"  הועתק: {name}")

    print("\nהקובץ הקפוא עודכן.")
    print("עכשיו: python -m pytest -q  — וצפו לכישלונות. הם אומרים מה זז.")
    print("יש לעדכן את הערכים המקובעים ולעשות commit לשניהם יחד.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
