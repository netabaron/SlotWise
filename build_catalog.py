#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
בונה את הקטלוג שנשלח יחד עם הקוד — ``data/catalog/catalog.jsonl``.

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
    python build_catalog.py --check          # רק לבדוק את מה שיש, בלי רשת ובלי כתיבה
    python build_catalog.py --year 2027      # גרידה מלאה, בקצב בטוח, ואז בנייה
    python build_catalog.py --year 2027 --out out/   # לתיקייה אחרת

הצינור הלילי (.github/workflows/build-catalog.yml) מריץ בדיוק את הפקודה
השנייה, ואז ``scripts/verify_catalog.py``. קודי היציאה מתועדים ב---help.
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

#: תיקיית הפלט. ‏--out דורס אותה, ואיתה את שני הנתיבים שמתחתיה.
#: ‏נשארים משתני מודול (ולא נסגרים בתוך main) כי ``tests/test_catalog_gate.py``
#: מחליף אותם ב-monkeypatch כדי לכתוב לתיקייה זמנית.
CATALOG_DIR = PROJECT_ROOT / "data" / "catalog"
CATALOG_PATH = CATALOG_DIR / "catalog.jsonl"
META_PATH = CATALOG_DIR / "catalog.meta.json"

# ---- קודי יציאה (ה-CI קורא אותם) ----------------------------------------
#: הצלחה. הקטלוג נכתב, או שלא היה מה לשנות.
EXIT_OK = 0
#: שער איכות נכשל. הפלט הקודם **לא** נגע.
EXIT_GATE_FAILED = 1
#: תקלה בלתי צפויה.
EXIT_ERROR = 2
#: הידיעון החזיר דף השהיה. לא באג — הקצב היה מהיר מדי, או שמישהו אחר
#: שלף מאותה כתובת. ריצה חוזרת מאוחר יותר היא התגובה הנכונה.
EXIT_THROTTLED = 3
#: הבקשה הופנתה אל מחוץ לידיעון, כלומר אל שער ההתחברות. זה היום שבו
#: בראודה סגרה את נקודות הקצה הציבוריות — ואז שום ריצה אוטומטית לא תעזור.
EXIT_GATED = 4
#: הסשן של הידיעון חזר לשנה אחרת, ופתיחה מחדש לא החזיקה. ‏2026-09-25 זה קרה
#: אחרי 25 דקות בריצה ששמונה קודמותיה החזיקו סשן אחד כ-97 דקות — תקלה אצל
#: השרת, לא אצלנו. ריצה חוזרת היא התגובה הנכונה.
EXIT_SESSION_REVERTED = 5

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
        gone = prev_codes - set(records)
        # ‏קורס שנעלם משתי סיבות שונות לגמרי, והשער הזה אמור לתפוס רק אחת
        # מהן. ‏**נסיגה** היא קורס שהידיעון עדיין מפרסם ואנחנו לא הצלחנו
        # להפיק — פרסר שנשבר, שליפה שנכשלה. ‏**גריעה** היא קורס שהידיעון
        # עצמו כבר אינו מפרסם, וזה אירוע רגיל לגמרי במכללה.
        #
        # ‏עד 2026-09-18 השער לא הבחין ביניהן ונפל על ``not lost``, בלי שום
        # סובלנות. הריצה הראשונה של הצינור (‏1h39m, ‏571/571 נשלפו, אפס
        # כישלונות) נפלה בגלל קורס אחד מתוך 572 — ‏51961, שהמכללה גרעה —
        # בזמן שהחצי השני של אותו שער, שימור המפגשים, עבר ב-99.7% מול רף
        # של 95%. כלומר: אחד מהשניים נכתב כטווח סבילות והשני כמספר מוחלט.
        #
        # ‏``catalog`` הוא אינדקס הקורסים **הטרי** שנשלף בתחילת הריצה, ולכן
        # הוא בדיוק מה שמבדיל: קוד שאינו בו — המכללה גרעה אותו.
        lost = sorted(gone & set(catalog)) if prev_codes else []
        withdrawn = sorted(gone - set(catalog)) if prev_codes else []
        prev_timed = int(prev.get("timed_meetings") or 0)
        retention = (counts["timed_meetings"] / prev_timed) if prev_timed else 1.0
        check(
            "4. אין נסיגה מול הקטלוג הקודם",
            not lost and retention >= MIN_MEETING_RETENTION,
            f"קורסים שנעלמו למרות שהם עדיין בקטלוג: {len(lost)}"
            + (f" ({', '.join(lost[:5])})" if lost else "")
            # ‏נאמר בקול ואינו פוסל: שינוי אמיתי אצל המכללה ראוי שיופיע
            # ביומן, ולא שייעלם בשקט רק מפני שאינו תקלה.
            + (f"; נגרעו מהקטלוג של המכללה: {len(withdrawn)} "
               f"({', '.join(withdrawn[:5])})" if withdrawn else "")
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
def write_catalog(
    records: dict[str, dict],
    meta: dict,
    catalog_path: Path | None = None,
    meta_path: Path | None = None,
) -> None:
    """כותב לקובץ זמני ומחליף. אף פעם לא משאיר קטלוג חצי-כתוב.

    ‏שני הנתיבים אופציונליים ונופלים למשתני המודול, כדי ש-monkeypatch
    עליהם (‏tests/test_catalog_gate.py) ימשיך לעבוד כמו שהוא.
    """
    catalog_path = catalog_path or CATALOG_PATH
    meta_path = meta_path or META_PATH
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = catalog_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for code in sorted(records):
            fh.write(json.dumps(records[code], ensure_ascii=False,
                                separators=(",", ":")) + "\n")
    os.replace(tmp, catalog_path)

    tmp_meta = meta_path.with_suffix(".json.tmp")
    tmp_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    os.replace(tmp_meta, meta_path)


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
def _yedion_errors():
    """‏(ThrottledError, GatedEndpointError) כטאפלים — ריקים אם המודול חסר.

    ‏מוחזרים כטאפלים ולא כמחלקות כדי שאפשר יהיה למסור אותם ל-``except``
    גם כשהמודול לא נטען: ``except ()`` פשוט אינו תופס כלום, במקום לזרוק.
    """
    try:
        import yedion_http  # type: ignore
    except Exception:  # noqa: BLE001
        return (), ()
    throttled = getattr(yedion_http, "ThrottledError", None)
    gated = getattr(yedion_http, "GatedEndpointError", None)
    return ((throttled,) if throttled else ()), ((gated,) if gated else ())


def _session_reverted_error():
    """‏(SessionRevertedError,) — ריק אם המודול חסר, מאותה סיבה כמו למעלה."""
    try:
        import yedion_http  # type: ignore
    except Exception:  # noqa: BLE001
        return ()
    reverted = getattr(yedion_http, "SessionRevertedError", None)
    return (reverted,) if reverted else ()


def fetch_missing(codes: list[str], year: str, pace: float) -> tuple[int, int]:
    """
    שולף רק את מה שחסר או פסול, בקצב ``pace`` שניות לבקשה.

    ניתן להפסקה ולהמשך: דמפ תקין קיים לא נשלף שוב, ולכן ריצה שנקטעה
    ממשיכה מאיפה שהפסיקה. ‏6.9.2026 הפיק שלוש הפסקות בשעתיים (כישלוני
    פענוח, נפילת DNS, ונקודת קצה שנתקעה), ולכן זה לא מותרות.

    **שתי תקלות אינן נספרות ככישלון של קורס בודד — הן עוצרות את הבנייה.**
    ‏``ThrottledError`` אומרת שהידיעון חסם, ומכאן כל בקשה נוספת גם תיחסם
    וגם תהיה חוסר נימוס. ‏``GatedEndpointError`` אומרת שנחתנו בשער
    ההתחברות, כלומר שנקודת הקצה הציבורית נסגרה — ושום ריצה אוטומטית לא
    תפתור זאת. שתיהן עולות למעלה ומתורגמות לקוד יציאה משלהן, כדי שה-CI
    יבדיל בין "בראודה חסמה אותנו" לבין "הפרסר נשבר".

    **דף בשנה הלא נכונה אינו כישלון של קורס — הוא כישלון של הסשן.** עד
    2026-09-25 הוא נספר כמו כל כישלון, והלולאה המשיכה על אותו סשן: אחרי
    145 דפים תקינים הידיעון חזר בשקט לתשפ"ו, ו-374 הקורסים שנותרו נכשלו
    אחד-אחד במשך 74 דקות. ‏``fetch_course_resyncing`` פותח את הסשן מחדש
    ומנסה שוב את אותו קורס; אם זה לא מחזיק הוא זורק ``SessionRevertedError``,
    וזו התקלה השלישית שעוצרת את הבנייה.
    """
    import yedion_http  # type: ignore

    throttled_exc, gated_exc = _yedion_errors()
    stop_exc = throttled_exc + gated_exc + _session_reverted_error()

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
            fetcher.fetch_course_resyncing(code)
            ok += 1
        except stop_exc as exc:
            print(f"  ({i}/{total}) {code}: {type(exc).__name__}: {exc}", flush=True)
            raise
        except Exception as exc:  # noqa: BLE001 - קורס בודד שנכשל אינו עוצר
            failed += 1
            print(f"  ({i}/{total}) {code}: {type(exc).__name__}: {exc}", flush=True)
        if i % 25 == 0:
            print(f"  ({i}/{total}) נשלפו {ok}, נכשלו {failed}", flush=True)
    if fetcher.session_reopens:
        print(f"  הסשן נפתח מחדש {fetcher.session_reopens} פעמים בריצה הזאת.",
              flush=True)
    return ok, failed


# ==========================================================================
# 6. CLI
# ==========================================================================
def _apply_out_dir(out: str) -> None:
    """מפנה את הפלט לתיקייה אחרת. משנה את משתני המודול בכוונה.

    ‏``CATALOG_PATH``/``META_PATH`` הם מה ש-``write_catalog`` נופל אליו,
    וגם מה שהבדיקות מחליפות ב-monkeypatch. שינוי שלהם כאן שומר על מקור
    אמת אחד לנתיב, במקום להשחיל אותו דרך כל קריאה.
    """
    global CATALOG_DIR, CATALOG_PATH, META_PATH
    CATALOG_DIR = Path(out).expanduser().resolve()
    CATALOG_PATH = CATALOG_DIR / "catalog.jsonl"
    META_PATH = CATALOG_DIR / "catalog.meta.json"


def build_meta(
    records: dict[str, dict],
    census: RawCensus,
    catalog: dict,
    result: GateResult,
    *,
    expected_year: str,
    year_gregorian: str,
) -> dict:
    """המטא שנכתב לצד הקטלוג, כולל סיכום שער האיכות.

    ‏``validation`` נוסף ב-2026-09-16, כשהבנייה הפכה לעבודת cron: מי
    שמסתכל על הקטלוג בגיט צריך לדעת **שהוא עבר את השערים, ומתי**, בלי
    לחפש את יומן הריצה שייצרה אותו — והיומן של ריצת cron נמחק.
    ‏scripts/verify_catalog.py קורא את הבלוק הזה ומצליב אותו מול הקטלוג.
    """
    counts = tally(records)
    return {
        "schema": "slotwise/catalog",
        "version": 1,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "year": expected_year,
        "year_gregorian": str(year_gregorian),
        "semesters": sorted({g.get("semester") or "?"
                             for r in records.values() for g in r["groups"]}),
        "counts": counts,
        "codes": sorted(records),
        "source": {"catalog_entries": len(catalog), "dumps_used": len(census.intact)},
        "validation": {
            "passed": bool(result.passed),
            "gate_count": len(result.checks),
            "gates": [
                {"name": name, "passed": bool(ok), "detail": detail}
                for name, ok, detail in result.checks
            ],
            "failures": list(result.failures),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="בונה את הקטלוג שנשלח עם הקוד.",
        epilog=(
            "קודי יציאה: 0 הצלחה · 1 שער איכות נכשל · 2 תקלה · "
            "3 הידיעון חסם · 4 נקודת הקצה נסגרה (שער התחברות) · "
            "5 הסשן חזר לשנה אחרת גם אחרי פתיחה מחדש.\n"
            "בכל קוד שאינו 0 קובצי הפלט **לא** נגעו."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--year", default="2027", help="שנה לועזית (2027 = תשפ\"ז)")
    ap.add_argument("--out", default=None, metavar="DIR",
                    help="תיקיית הפלט (ברירת מחדל: data/catalog)")
    ap.add_argument("--check", action="store_true",
                    help="רק להריץ את השער על מה שכבר על הדיסק — בלי רשת "
                         "ובלי לכתוב שום דבר")
    ap.add_argument("--pace", type=float, default=PACE_SECONDS,
                    help=f"שניות בין בקשות (ברירת מחדל {PACE_SECONDS:g})")
    args = ap.parse_args(argv)

    if args.out:
        _apply_out_dir(args.out)
    print(f"פלט: {CATALOG_PATH}")

    try:
        from yedion_http import hebrew_year_label  # type: ignore
        expected_year = hebrew_year_label(args.year)
    except Exception:  # noqa: BLE001
        expected_year = ""

    catalog = load_catalog_index()
    throttled_exc, gated_exc = _yedion_errors()
    reverted_exc = _session_reverted_error()

    if not args.check:
        census = scan_raw(RAW_DIR)
        need = sorted(set(catalog) - set(census.intact))
        if need:
            print(f"חסרים או פסולים: {len(need)} קורסים. "
                  f"בקצב {args.pace:g} שניות לבקשה זה כ-{len(need)*args.pace/60:.0f} דקות.")
            try:
                fetch_missing(need, args.year, args.pace)
            except gated_exc as exc:
                print(f"\nנקודת הקצה הציבורית נסגרה: {exc}")
                print("הקטלוג הקודם נשאר כמו שהוא. ריצה אוטומטית לא תפתור זאת.")
                return EXIT_GATED
            except throttled_exc as exc:
                print(f"\nהידיעון חסם: {exc}")
                print("הקטלוג הקודם נשאר כמו שהוא. כדאי לנסות שוב מאוחר יותר.")
                return EXIT_THROTTLED
            except reverted_exc as exc:
                print(f"\nהסשן של הידיעון לא מחזיק את השנה: {exc}")
                print("הקטלוג הקודם נשאר כמו שהוא. הדפים התקינים שכבר נשלפו "
                      "נשארים על הדיסק, וריצה חוזרת תמשיך מהם.")
                return EXIT_SESSION_REVERTED
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
        return EXIT_GATE_FAILED

    if args.check:
        # ‏--check הוא בדיקה, לא בנייה. עד 2026-09-16 הוא כן כתב כששער
        # האיכות עבר, וזה הפתיע בדיוק כפי שנשמע: ריצה שנועדה "רק להסתכל"
        # החליפה קטלוג שנמצא במאגר הקוד. עכשיו הוא קורא בלבד.
        counts = tally(records)
        print(f"\nהשער עבר. ‏--check אינו כותב; היו נכתבים "
              f"{counts['courses']} קורסים, {counts['groups']} קבוצות, "
              f"{counts['timed_meetings']} מפגשים.")
        return EXIT_OK

    meta = build_meta(records, census, catalog, result,
                      expected_year=expected_year, year_gregorian=args.year)
    write_catalog(records, meta)
    counts = meta["counts"]
    print(f"\nנכתב בהצלחה: {CATALOG_PATH}: {counts['courses']} קורסים, "
          f"{counts['groups']} קבוצות, {counts['timed_meetings']} מפגשים.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
