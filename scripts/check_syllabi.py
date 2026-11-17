#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
בודק אילו קובצי סילבוס קיימים באתר המכללה, וכותב את התשובות ל-``data/catalog/syllabi.json``.

למה זה כאן ולא בשרת
-------------------
השרת המתארח אסור לו לפנות לבראודה בזמן בקשה (``wsgi.py`` נועל
``allow_network=False``; ‏DEPLOY.md). לכן הבדיקה רצה בבנייה הלילית, באותו קצב
מנומס של שאר הבנייה, ו-``/api/syllabus/<code>`` רק קורא את הקובץ
(``src/syllabus.py``). הכתובות והמצבים מוגדרים שם; כאן רק הבקשות.

מה נבדק (docs/GROUND_TRUTH.md §10)
----------------------------------
‏``HEAD https://info.braude.ac.il/info/<שנה>/<קוד מרופד ל-7>.pdf`` — בקשה אחת
לכל (שנה, קוד), בלי עוגיות ובלי לעקוב אחרי הפניות. ‏200 עם PDF → ``exists``;
‏404 → ``missing``; כל השאר הוא כישלון **שאינו נרשם** — התשובה הקודמת נשארת.

תקציב וסדר
----------
הבדיקה המלאה היא כ-1,150 בקשות (577 קורסים × שתי שנים) — כמעט שלוש שעות
בקצב של 9 שניות, יותר ממה שנכנס לצד הבנייה הלילית. לכן כל ריצה בודקת עד
``--budget`` בקשות, לפי הסדר:

1. השנה, קודים שעוד לא נבדקו;
2. השנה, ``missing`` — הבדיקה הישנה ביותר קודם (אלה שמשתנים: קובץ מועלה);
3. שנה שעברה, קודים שעוד לא נבדקו — התשובה שם סופית (השנה סגורה);
4. השנה, ``exists`` שנבדקו לפני יותר מ-``--recheck-days`` ימים.

הצינור הלילי מריץ ``--budget 150``; המילוי הראשון רץ פעם אחת ידנית
(``.github/workflows/check-syllabi.yml``).

הרצה
-----
    python scripts/check_syllabi.py --budget 150            # כמו בצינור הלילי
    python scripts/check_syllabi.py --budget 1200 --pace 9  # מילוי מלא

סיכום
-----
בסוף כל ריצה מודפסת טבלה — לכל שנה: נבדקו, קיים, חסר, נכשלו, ועוד לא נבדקו —
ורשימת הקודים שנכשלו. ב-GitHub Actions אותו טקסט נכתב גם ל-``$GITHUB_STEP_SUMMARY``,
כך שאפשר לקרוא אותו בדף הריצה אחרי ההרצה הידנית.

קודי יציאה
----------
0 — הסתיים (גם כשהתקציב נגמר לפני שהכול נבדק).
1 — קלט חסר: אין ``catalog.meta.json``, אין בו קודים, או שנה לא תקינה. הקובץ לא נגע.
2 — תקלה בלתי צפויה. הקובץ לא נגע.
3 — נעצר מוקדם אחרי ``--max-failures`` כישלונות רצופים. מה שנלמד עד אז **נשמר**.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - סביבה בלי reconfigure
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import syllabus as syllabus_mod  # noqa: E402

EXIT_OK = 0
EXIT_BAD_INPUT = 1
EXIT_ERROR = 2
EXIT_STOPPED_EARLY = 3

DEFAULT_DIR = PROJECT_ROOT / "data" / "catalog"
DEFAULT_BUDGET = 150
#: אותו קצב כמו הבנייה הלילית (``build_catalog.PACE_SECONDS``).
DEFAULT_PACE = 9.0
DEFAULT_TIMEOUT = 10.0
DEFAULT_RECHECK_DAYS = 30
DEFAULT_MAX_FAILURES = 5

#: כללי בכוונה — בלי כתובת או פרטי קשר.
USER_AGENT = "SlotWise-syllabus-check/1"

FAILED = "failed"


# ---------------------------------------------------------------------------
# הבקשה
# ---------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """לא עוקבים אחרי הפניות: urllib הופך ‏HEAD ל-GET בהפניה, כלומר הורדה
    של הקובץ כולו. הקובץ האמיתי עונה ‏200 ישירות, ולכן הפניה היא כישלון."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


#: ‏opener בלי ‏HTTPCookieProcessor — אין עוגיות, לא נשלחות ולא נשמרות.
_OPENER = urllib.request.build_opener(_NoRedirect())


def probe(url: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    """‏HEAD אחד. ``exists`` / ``missing`` / ``failed``. אינו זורק."""
    req = urllib.request.Request(
        url, method="HEAD", headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"}
    )
    try:
        with _OPENER.open(req, timeout=timeout) as res:
            code = getattr(res, "status", None) or res.getcode()
            ctype = str(res.headers.get("Content-Type") or "").lower()
    except urllib.error.HTTPError as exc:
        return syllabus_mod.MISSING if exc.code == 404 else FAILED
    except Exception:  # noqa: BLE001 - זמן קצוב, DNS, TLS, ניתוק: "לא עכשיו"
        return FAILED
    if code == 200 and "pdf" in ctype:
        return syllabus_mod.EXISTS
    return FAILED


# ---------------------------------------------------------------------------
# מה לבדוק
# ---------------------------------------------------------------------------
def _days_since(checked: str, today: _dt.date) -> int:
    try:
        return (today - _dt.date.fromisoformat(checked)).days
    except ValueError:
        return 10**6  # תאריך פגום = ישן מאוד, כלומר ייבדק


def plan(
    data: dict[str, Any],
    codes: Iterable[str],
    year: str,
    *,
    today: _dt.date,
    recheck_days: int = DEFAULT_RECHECK_DAYS,
) -> list[tuple[str, str]]:
    """כל (שנה, קוד) שצריך בדיקה, בסדר העדיפות. התקציב חותך אחר כך."""
    last = syllabus_mod.previous_year(year)
    years = data.setdefault("years", {})
    now, before = years.setdefault(year, {}), years.setdefault(last, {})
    ordered = list(dict.fromkeys(str(c) for c in codes))

    def checked(rec: dict) -> str:
        return str(rec.get("checked") or "")

    never_now = [c for c in ordered if c not in now]
    missing_now = sorted(
        (c for c in ordered if (now.get(c) or {}).get("status") == syllabus_mod.MISSING),
        key=lambda c: (checked(now[c]), c),
    )
    never_before = [c for c in ordered if c not in before]
    stale_exists = sorted(
        (
            c
            for c in ordered
            if (now.get(c) or {}).get("status") == syllabus_mod.EXISTS
            and _days_since(checked(now[c]), today) > recheck_days
        ),
        key=lambda c: (checked(now[c]), c),
    )
    return (
        [(year, c) for c in never_now]
        + [(year, c) for c in missing_now]
        + [(last, c) for c in never_before]
        + [(year, c) for c in stale_exists]
    )


def prune(data: dict[str, Any], codes: Iterable[str], year: str) -> int:
    """מוחק מהשנה הנוכחית קודים שיצאו מהקטלוג, ומשאיר רק את השנה ושנה שעברה."""
    keep_years = {year, syllabus_mod.previous_year(year)}
    years = data.setdefault("years", {})
    for y in [y for y in years if y not in keep_years]:
        del years[y]
    wanted = set(str(c) for c in codes)
    now = years.setdefault(year, {})
    gone = [c for c in now if c not in wanted]
    for c in gone:
        del now[c]
    return len(gone)


# ---------------------------------------------------------------------------
# קריאה וכתיבה
# ---------------------------------------------------------------------------
def load_meta(catalog_dir: Path) -> dict[str, Any]:
    path = catalog_dir / "catalog.meta.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_existing(path: Path) -> dict[str, Any]:
    """הקובץ הקיים, דרך אותו מנתח שהשרת משתמש בו; חסר או פגום → ריק."""
    if not path.is_file():
        return syllabus_mod.parse("")
    return syllabus_mod.parse(path.read_text(encoding="utf-8"))


def render(data: dict[str, Any]) -> str:
    """‏JSON יציב: שורה לכל קורס, כדי שה-diff הלילי בגיט יהיה קריא."""
    lines = [
        "{",
        f'  "schema": {json.dumps(syllabus_mod.SCHEMA)},',
        f'  "version": {syllabus_mod.VERSION},',
        f'  "updated_at": {json.dumps(str(data.get("updated_at") or ""))},',
        '  "years": {',
    ]
    years = data.get("years") or {}
    year_keys = sorted(years, reverse=True)
    for yi, year in enumerate(year_keys):
        entries = years[year]
        codes = sorted(entries, key=lambda c: (len(c), c))
        comma = "," if yi < len(year_keys) - 1 else ""
        if not codes:
            lines.append(f"    {json.dumps(year)}: {{}}{comma}")
            continue
        lines.append(f"    {json.dumps(year)}: {{")
        for ci, code in enumerate(codes):
            rec = entries[code]
            body = json.dumps({"status": rec["status"], "checked": rec["checked"]}, ensure_ascii=False)
            lines.append(f"      {json.dumps(code)}: {body}" + ("," if ci < len(codes) - 1 else ""))
        lines.append("    }" + comma)
    lines += ["  }", "}", ""]
    return "\n".join(lines)


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# הריצה
# ---------------------------------------------------------------------------
def run(
    data: dict[str, Any],
    tasks: list[tuple[str, str]],
    *,
    budget: int,
    pace: float,
    max_failures: int,
    today: _dt.date,
    fetch: Callable[[str], str] = probe,
    sleep: Callable[[float], None] | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """מריץ עד ``budget`` בדיקות ומעדכן את ``data`` במקום. מחזיר ספירות.

    ‏``sleep`` נקרא בזמן ריצה (``time.sleep`` כשלא הועבר) ולא כברירת מחדל של
    הפרמטר — ברירת מחדל נקבעת פעם אחת בטעינת המודול.
    """
    pause = sleep if sleep is not None else time.sleep
    counts: dict[str, Any] = {
        "checked": 0, syllabus_mod.EXISTS: 0, syllabus_mod.MISSING: 0, FAILED: 0,
        "stopped_early": 0,
        # ‏לסיכום בסוף הריצה: ספירות לכל שנה, והקודים שנכשלו (לא נרשמו).
        "by_year": {},
        "failed_codes": [],
    }
    streak = 0
    stamp = today.isoformat()
    for i, (year, code) in enumerate(tasks[: max(0, budget)]):
        if i:
            pause(pace)
        result = fetch(syllabus_mod.pdf_url(year, code))
        counts["checked"] += 1
        per_year = counts["by_year"].setdefault(
            year, {"checked": 0, syllabus_mod.EXISTS: 0, syllabus_mod.MISSING: 0, FAILED: 0})
        per_year["checked"] += 1
        if result in syllabus_mod.RECORDED:
            data["years"].setdefault(year, {})[code] = {"status": result, "checked": stamp}
            counts[result] += 1
            per_year[result] += 1
            streak = 0
        else:
            counts[FAILED] += 1
            per_year[FAILED] += 1
            counts["failed_codes"].append((year, code))
            streak += 1
            log(f"  {year}/{code}: לא נבדק (כישלון {streak} ברצף)")
            if streak >= max_failures:
                counts["stopped_early"] = 1
                log(f"  {max_failures} כישלונות ברצף — עוצרים. מה שנבדק עד כאן נשמר.")
                break
        if counts["checked"] % 25 == 0:
            log(f"  ({counts['checked']}/{min(budget, len(tasks))}) "
                f"קיים {counts[syllabus_mod.EXISTS]}, חסר {counts[syllabus_mod.MISSING]}, "
                f"כישלונות {counts[FAILED]}")
    return counts


def summary(
    counts: dict[str, Any],
    data: dict[str, Any],
    codes: list[str],
    year: str,
    *,
    max_failures: int = DEFAULT_MAX_FAILURES,
) -> str:
    """סיכום הריצה ב-Markdown — אותו טקסט ליומן ול-``$GITHUB_STEP_SUMMARY``.

    לכל שנה: כמה נבדקו בריצה הזאת, כמה נמצאו, כמה חסרים, כמה נכשלו, וכמה
    קורסים מהקטלוג עוד לא נבדקו בכלל. אחריה — רשימת הקודים שנכשלו (הם לא
    נרשמו, והריצה הבאה תנסה אותם שוב).
    """
    last = syllabus_mod.previous_year(year)
    lines = [
        "### Syllabus check",
        "",
        "| year | checked | exists | missing | failed | not yet checked |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for y in (year, last):
        c = (counts.get("by_year") or {}).get(y) or {}
        known = (data.get("years") or {}).get(y) or {}
        not_yet = sum(1 for code in codes if code not in known)
        lines.append(
            f"| {y} | {c.get('checked', 0)} | {c.get(syllabus_mod.EXISTS, 0)} | "
            f"{c.get(syllabus_mod.MISSING, 0)} | {c.get(FAILED, 0)} | {not_yet} |"
        )
    lines.append(
        f"| **total** | **{counts.get('checked', 0)}** | **{counts.get(syllabus_mod.EXISTS, 0)}** | "
        f"**{counts.get(syllabus_mod.MISSING, 0)}** | **{counts.get(FAILED, 0)}** | |"
    )
    lines.append("")
    if counts.get("stopped_early"):
        lines.append(f"**Stopped early** after {max_failures} failures in a row. "
                     "Everything checked before that was saved.")
        lines.append("")
    failed = counts.get("failed_codes") or []
    if failed:
        lines.append(f"Failed ({len(failed)}, not recorded — the next run retries them):")
        lines.append("")
        for y in (year, last):
            mine = [code for fy, code in failed if fy == y]
            if mine:
                lines.append(f"- {y}: {', '.join(mine)}")
    else:
        lines.append("No failures.")
    return "\n".join(lines) + "\n"


def write_step_summary(text: str) -> None:
    """מוסיף את ``text`` ל-``$GITHUB_STEP_SUMMARY`` כשהוא מוגדר (ב-GitHub Actions).

    מחוץ ל-Actions המשתנה אינו קיים, ואין מה לעשות. כישלון בכתיבה אינו
    מפיל את הריצה — הסיכום כבר הודפס ליומן.
    """
    target = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not target:
        return
    try:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError as exc:
        print(f"לא הצלחתי לכתוב ל-GITHUB_STEP_SUMMARY: {exc}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="בודק אילו קובצי סילבוס קיימים באתר המכללה וכותב את syllabi.json.",
        epilog="קודי יציאה: 0 הסתיים · 1 קלט חסר · 2 תקלה · 3 נעצר מוקדם (מה שנבדק נשמר).",
    )
    ap.add_argument("--dir", default=str(DEFAULT_DIR), help="תיקיית הקטלוג (ברירת מחדל: data/catalog)")
    ap.add_argument("--year", default="", help="שנה לועזית; ברירת מחדל: year_gregorian של הקטלוג")
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="מספר הבקשות המרבי בריצה")
    ap.add_argument("--pace", type=float, default=DEFAULT_PACE, help="שניות בין בקשות")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="זמן קצוב לבקשה, בשניות")
    ap.add_argument("--recheck-days", type=int, default=DEFAULT_RECHECK_DAYS,
                    help="אחרי כמה ימים בודקים שוב קובץ שנמצא")
    ap.add_argument("--max-failures", type=int, default=DEFAULT_MAX_FAILURES,
                    help="כמה כישלונות רצופים עוצרים את הריצה")
    args = ap.parse_args(argv)

    catalog_dir = Path(args.dir)
    out_path = catalog_dir / syllabus_mod.SYLLABI_FILENAME
    try:
        meta = load_meta(catalog_dir)
    except (OSError, ValueError) as exc:
        print(f"אין catalog.meta.json תקין ב-{catalog_dir}: {exc}")
        write_step_summary("### Syllabus check\n\nDid not run: no usable `catalog.meta.json`. "
                           "Nothing was checked and syllabi.json was not touched.\n")
        return EXIT_BAD_INPUT
    codes = [str(c) for c in (meta.get("codes") or []) if syllabus_mod.valid_code(str(c))]
    year = str(args.year or meta.get("year_gregorian") or "").strip()
    if not codes or not syllabus_mod.valid_year(year):
        print(f"קלט חסר: {len(codes)} קודים, שנה {year!r}. הקובץ לא נגע.")
        write_step_summary(f"### Syllabus check\n\nDid not run: {len(codes)} codes, year {year!r}. "
                           "Nothing was checked and syllabi.json was not touched.\n")
        return EXIT_BAD_INPUT

    try:
        today = _dt.datetime.now(_dt.timezone.utc).date()
        data = load_existing(out_path)
        dropped = prune(data, codes, year)
        tasks = plan(data, codes, year, today=today, recheck_days=args.recheck_days)
        last = syllabus_mod.previous_year(year)
        print(f"שנה {year} (ושנה שעברה {last}): {len(codes)} קורסים בקטלוג. "
              f"ממתינות {len(tasks)} בדיקות; בריצה הזאת עד {args.budget}, "
              f"בקצב {args.pace:g} שניות. נמחקו {dropped} קודים שיצאו מהקטלוג.")
        counts = run(data, tasks, budget=args.budget, pace=args.pace,
                     max_failures=args.max_failures, today=today,
                     fetch=lambda url: probe(url, timeout=args.timeout))
        data["updated_at"] = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        write_atomic(out_path, render(data))
    except Exception as exc:  # noqa: BLE001
        print(f"תקלה: {type(exc).__name__}: {exc}. הקובץ לא נגע.")
        write_step_summary(f"### Syllabus check\n\nFailed: `{type(exc).__name__}: {exc}`. "
                           "syllabi.json was not touched.\n")
        return EXIT_ERROR

    text = summary(counts, data, codes, year, max_failures=args.max_failures)
    print("")
    print(text)
    print(f"נכתב: {out_path}")
    write_step_summary(text)
    return EXIT_STOPPED_EARLY if counts["stopped_early"] else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
