#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
בונה את הקטלוג שנשלח יחד עם הקוד — ``data/catalog.jsonl``.

למה הקובץ הזה קיים
-------------------
מי שמשכפל את המאגר היום מקבל אפליקציה שעולה ומציגה **אפס קורסים**:
‏``data/db/`` ו-``data/raw/`` שניהם ב-.gitignore. כדי להתחיל הוא צריך
גרידה של כשעה וחצי מול השרת של המכללה. הקטלוג שנשלח פותר את זה — הוא
נבנה **פעם אחת** על ידי המתחזק/ת, ונכנס לגיט.

שלושה כללים שמנחים את הקובץ
----------------------------
1. **כל הסמסטרים נשמרים.** הסינון לפי סמסטר עובר לזמן קריאה. עמוד הקורס
   מחזיר ממילא את כל הסמסטרים באותה טבלה, ולכן שמירה שלהם לא עולה בקשה
   אחת נוספת — ומצילה את היום שבו בראודה תפרסם את לוח סמסטר ב'.
2. **שער איכות לפני כתיבה.** גרידה חלקית או חסומה **לא** תיכתב. הקטלוג
   הקודם עדיף על קטלוג חדש ושבור, תמיד.
3. **כתיבה אטומית.** בונים לקובץ זמני ומחליפים. ריצה שנקטעת לא משאירה
   קטלוג חצי-כתוב — הלקח מ-6.9.2026, כשריצה חסומה דרסה 171 דמפים תקינים.

הרצה
-----
    python build_catalog.py --check          # רק לבדוק את מה שיש, בלי רשת
    python build_catalog.py --year 2027      # גרידה מלאה, בקצב בטוח, ואז בנייה
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# מסוף Windows עברי הוא cp1255 ולא יודע לכתוב את רוב מה שכתוב כאן.
# בלי השורה הזאת הסקריפט קורס בדיוק ברגע שהוא מדווח על כישלון.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 - סביבה בלי reconfigure
        pass

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

RAW_DIR = PROJECT_ROOT / "data" / "raw"
DB_DIR = PROJECT_ROOT / "data" / "db"
CATALOG_PATH = PROJECT_ROOT / "data" / "catalog.jsonl"
META_PATH = PROJECT_ROOT / "data" / "catalog.meta.json"

#: מתחת לזה שום תשובה אינה דף. זהה ל-``yedion_http._MIN_REAL_PAGE_CHARS``.
MIN_REAL_PAGE_CHARS = 500

#: הסימנים של דף ההשהיה של הידיעון.
THROTTLE_MARKERS: tuple[str, ...] = (
    "השהיית גישה זמנית",
    "יותר מידי שאילתות",
    "יותר מדי שאילתות",
)

#: קצב בטוח. נמדד: הידיעון סובל כ-400 בקשות לשעת שעון, ואז חוסם עד תחילת
#: השעה הבאה. ‏9 שניות לבקשה = 400 לשעה בדיוק, בלי להתקרב לתקרה.
#: ‏refresh.py רץ ב-1.2 שניות — פי 2.5 מהמכסה — ולכן כל ריצה מלאה מתה
#: סביב בקשה 400.
PACE_SECONDS = 9.0

#: כמה מהקטלוג חייב להיות מפוענח כדי שהבנייה תיחשב שלמה.
MIN_COVERAGE = 0.98

#: כמה מהמפגשים המתוזמנים של הבנייה הקודמת חייבים לשרוד.
MIN_MEETING_RETENTION = 0.95


# ==========================================================================
# 1. סקירת הגלם — מה יש על הדיסק לפני שמפענחים משהו
# ==========================================================================
@dataclass
class RawCensus:
    """מה נמצא ב-data/raw, לפי קטגוריות."""

    intact: list[str] = field(default_factory=list)
    throttled: list[str] = field(default_factory=list)
    runt: list[str] = field(default_factory=list)
    truncated: list[str] = field(default_factory=list)

    @property
    def bad(self) -> list[str]:
        return sorted(set(self.throttled) | set(self.runt) | set(self.truncated))

    def summary(self) -> str:
        return (
            f"תקינים {len(self.intact)} | חסומים {len(self.throttled)} | "
            f"זעירים {len(self.runt)} | קטועים {len(self.truncated)}"
        )


def scan_raw(raw_dir: Path) -> RawCensus:
    """מסווג כל דמפ. **לפני** הפענוח — דף חסום אינו קלט לפרסר."""
    census = RawCensus()
    for path in sorted(raw_dir.glob("*.html")):
        if not path.name[0].isdigit():
            continue  # ‏session_/catalog_ — לא דפי קורס
        code = path.name.rsplit("_", 1)[0]
        text = path.read_text(encoding="utf-8", errors="replace")
        body = text.strip()
        if any(marker in text for marker in THROTTLE_MARKERS):
            census.throttled.append(code)
        elif len(body) < MIN_REAL_PAGE_CHARS:
            census.runt.append(code)
        elif "</html>" not in body[-20:].lower():
            # דף שנקטע באמצע הכתיבה. נדיר, אבל שקט — ולכן נבדק.
            census.truncated.append(code)
        else:
            census.intact.append(code)
    return census


# ==========================================================================
# 2. בנייה — מהגלם לרשומות
# ==========================================================================
def build_records(raw_dir: Path, census: RawCensus) -> dict[str, dict]:
    """מפענח את הדמפים התקינים בלבד, **בלי סינון סמסטר**."""
    import parser as parser_mod  # type: ignore

    out: dict[str, dict] = {}
    for path in sorted(raw_dir.glob("*.html")):
        code = path.name.rsplit("_", 1)[0]
        if code not in census.intact:
            continue
        html = path.read_text(encoding="utf-8", errors="replace")
        result = parser_mod.parse_course_page(html, code, semester=None)
        course = result.course
        if course is None:
            continue
        out[code] = {
            "code": course.code,
            "name": course.name,
            "credits": course.credits,
            "groups": [
                {
                    "group_id": g.group_id,
                    "kind": g.kind,
                    "lecturer": g.lecturer,
                    "semester": g.semester,
                    "note": g.note,
                    # ‏הודעת המצב של הידיעון ("הקורס מלא"). בלי השורה הזאת
                    # היא נופלת בקטלוג, ומי שרץ על הקטלוג — כלומר כל
                    # שיבוט טרי — לא רואה אותה כלל.
                    "status_note": g.status_note,
                    "linked_to": list(g.linked_to or []),
                    "meetings": [
                        {
                            "day": m.day,
                            "start": m.start,
                            "end": m.end,
                            "room": m.room,
                            "building": m.building,
                            "semester": m.semester,
                        }
                        for m in (g.meetings or [])
                    ],
                }
                for g in course.groups
            ],
        }
    return out


def tally(records: dict[str, dict]) -> dict[str, int]:
    """ספירות שהשער נשען עליהן."""
    groups = timed = 0
    per_semester: dict[str, int] = {}
    for rec in records.values():
        for g in rec["groups"]:
            groups += 1
            sem = g.get("semester") or "?"
            per_semester[sem] = per_semester.get(sem, 0) + 1
            for m in g["meetings"]:
                if m.get("start") is not None and m.get("end") is not None:
                    timed += 1
    return {
        "courses": len(records),
        "groups": groups,
        "timed_meetings": timed,
        **{f"groups_{k}": v for k, v in sorted(per_semester.items())},
    }


# ==========================================================================
# 3. שער האיכות — שש בדיקות, וכל אחת פוסלת
# ==========================================================================
@dataclass
class GateResult:
    passed: bool
    failures: list[str]
    checks: list[tuple[str, bool, str]]

    def report(self) -> str:
        lines = []
        for name, ok, detail in self.checks:
            lines.append(f"  [{'עבר' if ok else 'נכשל'}] {name}: {detail}")
        return "\n".join(lines)


def validate(
    records: dict[str, dict],
    census: RawCensus,
    catalog: dict[str, Any],
    previous_meta: dict | None,
    *,
    expected_year: str = "",
    raw_dir: Path | None = None,
) -> GateResult:
    """
    שש הבדיקות שחייבות לעבור לפני שקטלוג נכתב.

    הן לא סימטריות בכוונה: חמש מהן תופסות **שליפה** שבורה, ורק אחת —
    בדיקת אי-הנסיגה — תופסת **פענוח** שבור. זו האחרונה ששווה הכי הרבה,
    כי גרידה חסומה צועקת ופרסר שבור שותק.
    """
    checks: list[tuple[str, bool, str]] = []
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append((name, ok, detail))
        if not ok:
            failures.append(f"{name}: {detail}")

    # ---- 1. אף גוף חסום או זעיר ----------------------------------------
    bad = census.bad
    check(
        "1. אין דפים חסומים או קטועים",
        not bad,
        f"{len(bad)} דמפים פסולים ({census.summary()})"
        + (f"; לדוגמה {', '.join(bad[:5])}" if bad else ""),
    )

    # ---- 2. כיסוי ------------------------------------------------------
    expected = len(catalog) if catalog else 0
    coverage = (len(records) / expected) if expected else 0.0
    check(
        "2. כיסוי הקטלוג",
        expected > 0 and coverage >= MIN_COVERAGE,
        f"{len(records)} מתוך {expected} קורסים = {coverage:.1%} "
        f"(נדרש {MIN_COVERAGE:.0%})",
    )

    # ---- 3. שנת הלימודים על הדף ----------------------------------------
    if expected_year and raw_dir is not None:
        wrong = []
        for code in list(census.intact)[:60]:  # מדגם — הבדיקה יקרה
            hits = sorted(raw_dir.glob(f"{code}_*.html"))
            if not hits:
                continue
            if expected_year not in hits[-1].read_text(encoding="utf-8", errors="replace"):
                wrong.append(code)
        check(
            "3. שנת הלימודים על הדפים",
            not wrong,
            f"נבדק מדגם של {min(60, len(census.intact))} דפים; "
            + (f"{len(wrong)} עם שנה שגויה: {', '.join(wrong[:5])}" if wrong
               else f"כולם {expected_year}"),
        )
    else:
        check("3. שנת הלימודים על הדפים", True, "לא נבדק (לא נמסרה שנה צפויה)")

    # ---- 4. אי-נסיגה מול הבנייה הקודמת ---------------------------------
    counts = tally(records)
    if previous_meta and previous_meta.get("counts"):
        prev = previous_meta["counts"]
        prev_codes = set(previous_meta.get("codes") or [])
        lost = sorted(prev_codes - set(records)) if prev_codes else []
        prev_timed = int(prev.get("timed_meetings") or 0)
        retention = (counts["timed_meetings"] / prev_timed) if prev_timed else 1.0
        check(
            "4. אין נסיגה מול הקטלוג הקודם",
            not lost and retention >= MIN_MEETING_RETENTION,
            f"קורסים שנעלמו: {len(lost)}"
            + (f" ({', '.join(lost[:5])})" if lost else "")
            + f"; מפגשים מתוזמנים {counts['timed_meetings']} מול {prev_timed} "
              f"= {retention:.1%} (נדרש {MIN_MEETING_RETENTION:.0%})",
        )
    else:
        check("4. אין נסיגה מול הקטלוג הקודם", True, "אין קטלוג קודם — בנייה ראשונה")

    # ---- 5. רצפות שפיות -------------------------------------------------
    ok_floor = counts["timed_meetings"] > 0 and counts["groups"] >= counts["courses"]
    check(
        "5. רצפות שפיות",
        ok_floor,
        f"{counts['courses']} קורסים, {counts['groups']} קבוצות, "
        f"{counts['timed_meetings']} מפגשים מתוזמנים",
    )

    # ---- 6. מטא־נתונים מלאים --------------------------------------------
    have_meta = bool(expected_year) and counts["courses"] > 0
    check(
        "6. מטא־נתונים מלאים",
        have_meta,
        f"שנה={expected_year or '(חסר)'}, קורסים={counts['courses']}",
    )

    return GateResult(passed=not failures, failures=failures, checks=checks)


# ==========================================================================
# 4. כתיבה אטומית
# ==========================================================================
def write_catalog(records: dict[str, dict], meta: dict) -> None:
    """כותב לקובץ זמני ומחליף. אף פעם לא משאיר קטלוג חצי-כתוב."""
    tmp = CATALOG_PATH.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for code in sorted(records):
            fh.write(json.dumps(records[code], ensure_ascii=False,
                                separators=(",", ":")) + "\n")
    os.replace(tmp, CATALOG_PATH)

    tmp_meta = META_PATH.with_suffix(".json.tmp")
    tmp_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    os.replace(tmp_meta, META_PATH)


def load_previous_meta() -> dict | None:
    if not META_PATH.is_file():
        return None
    try:
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def load_catalog_index() -> dict[str, Any]:
    """‏data/db/catalog.json — רשימת הקורסים שנפתחים השנה."""
    path = DB_DIR / "catalog.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("courses") or data


# ==========================================================================
# 5. שליפה בקצב בטוח
# ==========================================================================
def fetch_missing(codes: list[str], year: str, pace: float) -> tuple[int, int]:
    """
    שולף רק את מה שחסר או פסול, בקצב ``pace`` שניות לבקשה.

    ניתן להפסקה ולהמשך: דמפ תקין קיים לא נשלף שוב, ולכן ריצה שנקטעה
    ממשיכה מאיפה שהפסיקה. ‏6.9.2026 הפיק שלוש הפסקות בשעתיים (כישלוני
    פענוח, נפילת DNS, ונקודת קצה שנתקעה), ולכן זה לא מותרות.
    """
    import yedion_http  # type: ignore

    fetcher = yedion_http.YedionHTTP(
        year=year, delay_s=pace, raw_dir=str(RAW_DIR),
        log=lambda m: print(f"  [fetch] {m}", flush=True),
    )
    fetcher.open_session()
    ok = failed = 0
    total = len(codes)
    # אין כאן time.sleep: ``YedionHTTP`` כבר ממתין ``delay_s`` לפני **כל**
    # בקשה (yedion_http.py:839). השהיה נוספת כאן הייתה מכפילה את הקצב
    # ל-18 שניות לבקשה, כלומר שלוש שעות במקום שעה וחצי.
    for i, code in enumerate(codes, start=1):
        try:
            fetcher.fetch_course(code)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ({i}/{total}) {code}: {type(exc).__name__}: {exc}", flush=True)
            if isinstance(exc, getattr(yedion_http, "ThrottledError", ())):
                print("  הידיעון חסם — עוצר כאן.", flush=True)
                break
        if i % 25 == 0:
            print(f"  ({i}/{total}) נשלפו {ok}, נכשלו {failed}", flush=True)
    return ok, failed


# ==========================================================================
# 6. CLI
# ==========================================================================
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="בונה את הקטלוג שנשלח עם הקוד.")
    ap.add_argument("--year", default="2027", help="שנה לועזית (2027 = תשפ\"ז)")
    ap.add_argument("--check", action="store_true",
                    help="רק להריץ את השער על מה שכבר על הדיסק, בלי רשת")
    ap.add_argument("--pace", type=float, default=PACE_SECONDS,
                    help=f"שניות בין בקשות (ברירת מחדל {PACE_SECONDS:g})")
    args = ap.parse_args(argv)

    try:
        from yedion_http import hebrew_year_label  # type: ignore
        expected_year = hebrew_year_label(args.year)
    except Exception:  # noqa: BLE001
        expected_year = ""

    catalog = load_catalog_index()

    if not args.check:
        census = scan_raw(RAW_DIR)
        need = sorted(set(catalog) - set(census.intact))
        if need:
            print(f"חסרים או פסולים: {len(need)} קורסים. "
                  f"בקצב {args.pace:g} שניות לבקשה זה כ-{len(need)*args.pace/60:.0f} דקות.")
            fetch_missing(need, args.year, args.pace)
        else:
            print("כל הקטלוג כבר על הדיסק ותקין — לא נדרשת שליפה.")

    census = scan_raw(RAW_DIR)
    print(f"\nגלם: {census.summary()}")
    records = build_records(RAW_DIR, census)
    print(f"פוענחו: {len(records)} קורסים")

    result = validate(records, census, catalog, load_previous_meta(),
                      expected_year=expected_year, raw_dir=RAW_DIR)
    print("\nשער האיכות:")
    print(result.report())

    if not result.passed:
        print(f"\nנכשל — הקטלוג **לא** נכתב. {len(result.failures)} בדיקות נכשלו.")
        print("הקטלוג הקודם נשאר כמו שהוא — עדיף על קטלוג חדש ושבור.")
        return 1

    counts = tally(records)
    meta = {
        "schema": "slotwise/catalog",
        "version": 1,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "year": expected_year,
        "year_gregorian": str(args.year),
        "semesters": sorted({g.get("semester") or "?"
                             for r in records.values() for g in r["groups"]}),
        "counts": counts,
        "codes": sorted(records),
        "source": {"catalog_entries": len(catalog), "dumps_used": len(census.intact)},
    }
    write_catalog(records, meta)
    print(f"\nנכתב בהצלחה: {CATALOG_PATH.name}: {counts['courses']} קורסים, "
          f"{counts['groups']} קבוצות, {counts['timed_meetings']} מפגשים.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
