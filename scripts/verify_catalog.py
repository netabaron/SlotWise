#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/verify_catalog.py — בודק קטלוג בנוי, בלי רשת ובלי המנוע.

למה הוא קיים בנפרד מ-``build_catalog.py``
------------------------------------------
שערי האיכות שב-``build_catalog.py`` בודקים את ה**בנייה**: הם רצים על
דמפי ה-HTML הגולמיים, ויודעים מה נשלף ומה נחסם. הקובץ הזה בודק את
ה**תוצר**: שני קבצים על הדיסק, בלי גישה ל-``data/raw`` ובלי ידע על
הריצה שייצרה אותם.

ההפרדה אינה קוסמטית. בצינור הלילי (``.github/workflows/build-catalog.yml``)
זה מה שרץ **אחרי** הבנייה ולפני ה-commit, ולכן הוא התשובה לשאלה "האם מה
שעומד להידחף ל-main הוא קטלוג שלם" — שאלה שאפשר לשאול גם על קטלוג שמישהו
בנה על המחשב שלו לפני חצי שנה, וגם על התוצר של הריצה שהרגע הסתיימה.
זהו גם מה שמגן מפני התרחיש שאף שער בנייה אינו רואה: ‏commit שעבר בהצלחה
אבל כתב מטא שאינו תואם לקטלוג שלצידו.

שימוש
-----
    python scripts/verify_catalog.py                      # data/catalog
    python scripts/verify_catalog.py --dir out --year 2027
    python scripts/verify_catalog.py --min-courses 400

קודי יציאה: ‏0 תקין · 1 נמצאה בעיה · 2 שימוש שגוי.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent

#: ברירת מחדל שמרנית. הקטלוג האמיתי מחזיק 572 קורסים; 400 תופס קריסה
#: אמיתית בלי ליפול על תנודה טבעית בין סמסטרים.
DEFAULT_MIN_COURSES = 400

#: המפתחות שהמטא **חייב** לשאת. ``validation`` נוסף ב-2026-09-16.
REQUIRED_META_KEYS = ("schema", "built_at", "year", "year_gregorian", "counts", "codes")


class Problem(Exception):
    """בעיה שמפילה את הבדיקה. ההודעה נכתבת למסך כמות שהיא."""


# ==========================================================================
# טעינה
# ==========================================================================
def load_catalog(path: Path) -> dict[str, dict]:
    """קורא ‏JSONL ומחזיר ``{code: record}``. כל שורה פגומה היא בעיה.

    ‏שורה ריקה בסוף הקובץ מותרת (כתיבה אטומית מסיימת בירידת שורה); כל
    שורה ריקה **אחרת** אינה, כי היא מסגירה כתיבה שנקטעה באמצע.
    """
    if not path.is_file():
        raise Problem(f"אין קובץ קטלוג: {path}")

    records: dict[str, dict] = {}
    duplicates: list[str] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                raise Problem(f"{path.name}: שורה ריקה בשורה {lineno}")
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                raise Problem(f"{path.name}: שורה {lineno} אינה JSON תקין — {exc}") from exc
            if not isinstance(rec, dict):
                raise Problem(f"{path.name}: שורה {lineno} אינה אובייקט")
            code = str(rec.get("code") or "").strip()
            if not code:
                raise Problem(f"{path.name}: שורה {lineno} בלי שדה code")
            if "groups" not in rec or not isinstance(rec["groups"], list):
                raise Problem(f"{path.name}: {code} בלי רשימת groups")
            if code in records:
                duplicates.append(code)
            records[code] = rec

    if duplicates:
        raise Problem(
            f"{path.name}: {len(duplicates)} קודים כפולים "
            f"({', '.join(sorted(set(duplicates))[:5])})"
        )
    return records


def load_meta(path: Path) -> dict:
    if not path.is_file():
        raise Problem(f"אין קובץ מטא: {path}")
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Problem(f"{path.name} אינו JSON תקין — {exc}") from exc
    if not isinstance(meta, dict):
        raise Problem(f"{path.name} אינו אובייקט")
    missing = [k for k in REQUIRED_META_KEYS if k not in meta]
    if missing:
        raise Problem(f"{path.name}: חסרים מפתחות — {', '.join(missing)}")
    return meta


# ==========================================================================
# ספירה
# ==========================================================================
def tally(records: dict[str, dict]) -> dict[str, int]:
    """אותה ספירה בדיוק כמו ``build_catalog.tally`` — זו הנקודה.

    ‏שוכפלה במכוון ולא יובאה: הקובץ הזה בודק את התוצר מבחוץ, וייבוא
    היה אומר שבאג בספירה מבטל את עצמו בשני הצדדים ולא היה נתפס לעולם.
    """
    groups = timed = 0
    per_semester: collections.Counter[str] = collections.Counter()
    for rec in records.values():
        for g in rec["groups"]:
            groups += 1
            per_semester[g.get("semester") or "?"] += 1
            for m in g.get("meetings") or []:
                if m.get("start") is not None and m.get("end") is not None:
                    timed += 1
    return {
        "courses": len(records),
        "groups": groups,
        "timed_meetings": timed,
        **{f"groups_{k}": v for k, v in sorted(per_semester.items())},
    }


# ==========================================================================
# הבדיקות
# ==========================================================================
def verify(directory: Path, *, year: str = "", min_courses: int = DEFAULT_MIN_COURSES) -> list[str]:
    """מריץ את כל הבדיקות ומחזיר רשימת בעיות. ריקה = תקין."""
    catalog_path = directory / "catalog.jsonl"
    meta_path = directory / "catalog.meta.json"

    records = load_catalog(catalog_path)
    meta = load_meta(meta_path)
    problems: list[str] = []

    def check(name: str, ok: bool, detail: str) -> None:
        print(f"  [{'תקין' if ok else 'בעיה'}] {name}: {detail}")
        if not ok:
            problems.append(f"{name}: {detail}")

    # ---- 1. לא ריק -------------------------------------------------------
    check(
        "1. הקטלוג אינו ריק",
        len(records) >= min_courses,
        f"{len(records)} קורסים (נדרש לפחות {min_courses})",
    )

    # ---- 2. יש תוכן אמיתי, לא רק שלדים ----------------------------------
    counts = tally(records)
    check(
        "2. יש קבוצות ומפגשים מתוזמנים",
        counts["groups"] >= counts["courses"] and counts["timed_meetings"] > 0,
        f"{counts['groups']} קבוצות, {counts['timed_meetings']} מפגשים מתוזמנים",
    )

    # ---- 3. השנה ---------------------------------------------------------
    # ‏--year הוא לועזי ("2027"); המטא נושא גם אותו וגם את התווית העברית.
    if year:
        check(
            "3. השנה תואמת למבוקש",
            str(meta.get("year_gregorian") or "").strip() == str(year).strip(),
            f"מטא={meta.get('year_gregorian')!r} מבוקש={year!r} "
            f"(תווית: {meta.get('year')!r})",
        )
    else:
        check("3. השנה תואמת למבוקש", bool(meta.get("year_gregorian")),
              f"לא נמסרה --year; המטא אומר {meta.get('year_gregorian')!r}")

    # ---- 4. הספירות שבמטא תואמות לקטלוג ---------------------------------
    # ‏זה הכשל היחיד שאף שער בנייה אינו רואה: מטא של בנייה אחת לצד קטלוג
    # של בנייה אחרת. שניהם תקינים כשלעצמם, והצירוף שקרי.
    mismatched = {
        k: (v, counts.get(k))
        for k, v in (meta.get("counts") or {}).items()
        if counts.get(k) != v
    }
    check(
        "4. הספירות שבמטא תואמות לקטלוג",
        not mismatched,
        "תואם" if not mismatched
        else "; ".join(f"{k}: מטא={a} בפועל={b}" for k, (a, b) in sorted(mismatched.items())),
    )

    # ---- 5. רשימת הקודים תואמת -------------------------------------------
    meta_codes = set(map(str, meta.get("codes") or []))
    only_meta = sorted(meta_codes - set(records))
    only_catalog = sorted(set(records) - meta_codes)
    check(
        "5. רשימת הקודים תואמת",
        not only_meta and not only_catalog,
        "תואם" if not (only_meta or only_catalog)
        else f"רק במטא: {len(only_meta)} ({', '.join(only_meta[:3])}); "
             f"רק בקטלוג: {len(only_catalog)} ({', '.join(only_catalog[:3])})",
    )

    # ---- 6. סיכום השערים -------------------------------------------------
    validation = meta.get("validation")
    if isinstance(validation, dict):
        passed = validation.get("passed") is True
        check(
            "6. הבנייה עברה את שערי האיכות",
            passed,
            "passed=true" if passed
            else f"passed={validation.get('passed')!r}; "
                 f"failures={validation.get('failures')!r}",
        )
    else:
        # ‏קטלוג מלפני 2026-09-16 אינו נושא את הבלוק. זו אינה תקינות
        # שבורה — פשוט אין מה לבדוק, ואומרים את זה במקום להניח הצלחה.
        check("6. הבנייה עברה את שערי האיכות", True,
              "אין בלוק validation במטא (קטלוג שנבנה לפני שהבלוק נוסף)")

    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="בודק שקטלוג בנוי שלם ותואם למטא שלצידו.",
        epilog="קודי יציאה: 0 תקין · 1 נמצאה בעיה · 2 שימוש שגוי.",
    )
    ap.add_argument("--dir", default=str(PROJECT_ROOT / "data" / "catalog"),
                    metavar="DIR", help="תיקיית הקטלוג (ברירת מחדל: data/catalog)")
    ap.add_argument("--year", default="", help="שנה לועזית צפויה, למשל 2027")
    ap.add_argument("--min-courses", type=int, default=DEFAULT_MIN_COURSES,
                    help=f"רצפת מספר הקורסים (ברירת מחדל {DEFAULT_MIN_COURSES})")
    args = ap.parse_args(argv)

    directory = Path(args.dir).expanduser()
    print(f"בודק קטלוג: {directory}")

    try:
        problems = verify(directory, year=args.year, min_courses=args.min_courses)
    except Problem as exc:
        print(f"\nהקטלוג פסול: {exc}")
        return 1

    if problems:
        print(f"\nנמצאו {len(problems)} בעיות — הקטלוג פסול.")
        return 1

    print("\nהקטלוג תקין.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
