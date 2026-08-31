"""
reparse.py — בונה מחדש את מסד הנתונים מתוך דפי ה-HTML השמורים, בלי רשת.

למה זה קיים
-----------
כל דף שנשלף מהידיעון נשמר גולמי ב-``data/raw/`` *לפני* שמפענחים אותו. לכן,
כשמתקנים באג בפרסר, אין שום סיבה להטריח את השרת של המכללה (ואת ההתחברות
הידנית) רק כדי לפענח מחדש את אותם נתונים בדיוק. הכלי הזה מפענח מחדש מהדיסק.

חשוב: חותמת הזמן שנשמרת היא **זמן השליפה האמיתי** — כלומר זמן השינוי של קובץ
ה-HTML — ולא "עכשיו". פענוח מחדש אינו שליפה מחדש, ואסור שהוא יגרום לנתונים
מלפני יומיים להיראות טריים.

שימוש:
    python reparse.py                # כל הקודים שבמעקב + הקטלוג
    python reparse.py --codes 61753  # קודים מסוימים
    python reparse.py --semester ב   # לסנן לסמסטר אחר
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import discovery as discovery_mod  # noqa: E402
import parser as parser_mod  # noqa: E402
import store as store_mod  # noqa: E402

RAW_DIR = ROOT / "data" / "raw"
DB_ROOT = ROOT / "data" / "db"
PROFILE = ROOT / "data" / "profile.json"


def newest_raw(code: str) -> Path | None:
    """הדמפ העדכני ביותר של הקוד הזה (``61753_3.html`` גובר על ``61753_1.html``)."""
    hits = sorted(
        RAW_DIR.glob(f"{code}_*.html"),
        key=lambda p: (int(m.group(1)) if (m := re.search(r"_(\d+)\.html$", p.name)) else 0),
    )
    return hits[-1] if hits else None


def file_stamp(path: Path) -> str:
    """זמן השינוי של הקובץ כ-ISO-8601 UTC — זמן השליפה האמיתי."""
    return (
        datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="reparse",
        description="פענוח מחדש של דפי הידיעון השמורים אל מסד הנתונים (בלי רשת)",
    )
    ap.add_argument("--codes", type=str, default=None, metavar="61753,61756")
    ap.add_argument("--semester", type=str, default=None, choices=["א", "ב", "קיץ"])
    ap.add_argument("--year", type=str, default=None)
    args = ap.parse_args(argv)

    profile = json.loads(PROFILE.read_text(encoding="utf-8")) if PROFILE.exists() else {}
    student = profile.get("student") or {}
    semester = args.semester or str(student.get("term") or "א")
    year_he = args.year or str(student.get("academic_year") or 'תשפ"ז')
    year_greg = {'תשפ"ו': "2026", 'תשפ"ז': "2027", 'תשפ"ח': "2028"}.get(year_he, "2027")

    store = store_mod.Store(str(DB_ROOT))

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        codes = store.tracked() or [c["code"] for c in (profile.get("selected_courses") or [])]

    print(f"פענוח מחדש מ-{RAW_DIR}  |  סמסטר {semester}  |  {year_he} ({year_greg})")
    print("=" * 74)

    # ---- הקטלוג -----------------------------------------------------------
    catalog_file = newest_raw("catalog")
    if catalog_file is not None:
        cat, warns = discovery_mod.parse_catalog(catalog_file.read_text(encoding="utf-8", errors="replace"))
        if cat:
            store.save_catalog(cat, year_he, year_greg)
            print(f"קטלוג: {len(cat)} קורסים נשמרו  ({len(warns)} אזהרות)")
        else:
            print(f"קטלוג: הפענוח החזיר ריק — לא נשמר. אזהרות: {warns[:2]}")
    else:
        print("קטלוג: אין דמפ שמור.")

    # ---- הקורסים ----------------------------------------------------------
    ok = failed = 0
    all_changes: list[str] = []
    for code in codes:
        path = newest_raw(code)
        if path is None:
            print(f"  {code}: אין דמפ שמור — דילוג.")
            failed += 1
            continue
        html = path.read_text(encoding="utf-8", errors="replace")
        result = parser_mod.parse_course_page(html, code, semester=semester)
        if result.course is None:
            print(f"  {code}: לא נפתח בסמסטר {semester} (או שהפענוח נכשל).")
            for w in result.warnings[:2]:
                print(f"        {w[:120]}")
            failed += 1
            continue
        meta = store_mod.CourseMeta(
            fetched_at=file_stamp(path),          # זמן השליפה האמיתי, לא עכשיו
            year=year_he,
            year_gregorian=year_greg,
            semester=semester,
            source_url=f"reparsed://{path.name}",
            content_sha1=hashlib.sha1(html.encode("utf-8", "replace")).hexdigest(),
            group_count=len(result.course.groups),
            warnings=list(result.warnings),
            ok=True,
        )
        changes = store.save_course(result.course, meta) or []
        all_changes.extend(changes)
        ok += 1
        kinds = "/".join(result.course.kinds())
        print(f"  {code}: {len(result.course.groups)} קבוצות [{kinds}] — {result.course.name}")

    print("=" * 74)
    print(f"הצליחו: {ok}  |  נכשלו/לא נפתחים: {failed}")
    if all_changes:
        print(f"\nשינויים מול מה שהיה שמור ({len(all_changes)}):")
        for ch in all_changes:
            print("  •", ch)
    return 0 if failed == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
