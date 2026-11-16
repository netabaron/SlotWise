#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/check_curricula.py — משווה את תוכניות הלימודים שלנו לשנתון שבאתר בראודה.

למה הוא קיים
-------------
קבצי ``data/curricula/*.json`` ו-``data/curriculum.json`` נבנו מפרקי שנתון
ב-PDF, והם לא מתעדכנים לבד. כשהמחלקה משנה קוד קורס, הממשק ממשיך לחפש
בקטלוג את הקוד הישן ומציג "הקורס לא נפתח". כך קרה ל"כימיה א'" בחשמל:
‏41090 בקובץ, ‏41089 בשנתון תשפ"ז ובידיעון.

החל מתשפ"ז בראודה מפרסמת את השנתון כדפי HTML, דף לכל מחלקה:
``https://w3.braude.ac.il/shnaton-26-27/bsc/<slug>/``. בכל דף כל סמסטר הוא
אקורדיון שכותרתו "סמסטר N", ובתוכו טבלה שעמודותיה "מספר הקורס", "שם
הקורס", ה/ת/מ/(פ) ו"נקודות זכות". זה מבנה שאפשר לקרוא בלי לנחש.

מה נבדק
-------
לכל קורס חובה בכל סמסטר:
    * GONE     — הקוד שלנו אינו מופיע בטבלאות הסמסטרים של השנתון.
    * NEW      — קוד בטבלת סמסטר בשנתון שאינו אצלנו.
    * SEMESTER — הקורס עבר סמסטר.
    * CREDITS  — נקודות הזכות השתנו.

הסקריפט **אינו משנה** אף קובץ. הוא מדווח, ואדם מחליט: שנתון חדש חל על
המחזור שמתחיל בו, ולא כל הבדל הוא תיקון לסטודנטים ותיקים.

בנוסף הוא בודק אם כבר פורסם השנתון של השנה **הבאה** — סימן שהגיע הזמן
לעדכן את ``--year``.

קורסי בחירה אינם נבדקים כאן עדיין: מבנה האשכולות/המסלולים שונה בין
המחלקות, וראו ``src/shnaton.py``.

שימוש
-----
    python scripts/check_curricula.py                    # מושך מהאתר
    python scripts/check_curricula.py --year 26-27
    python scripts/check_curricula.py --html-dir saved/  # קבצים שמורים, בלי רשת
    python scripts/check_curricula.py --save-html saved/ # שומר את מה שנמשך

קודי יציאה: ‏0 אין הבדלים · 1 נמצאו הבדלים · 2 תקלת משיכה או פענוח.
"""

from __future__ import annotations

import argparse
import html as _html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://w3.braude.ac.il/shnaton-{year}/bsc/{slug}/"
DEFAULT_YEAR = "26-27"
#: שניות בין בקשות. עשרה דפים בלבד, אבל זה שרת של מכללה.
DEFAULT_PACE = 3.0

#: ‏slug באתר -> קובץ התוכנית שלנו (יחסית לשורש הפרויקט).
#: מתמטיקה: הדף מציג תוכנית אחת של שישה סמסטרים, שמתאימה למחזור החורף.
#: ‏math-spring.json מוזז בסמסטר אחד ולכן אינו נבדק מול אותו דף.
PROGRAMS: dict[str, str] = {
    "bio": "data/curricula/biotech.json",
    "civil": "data/curricula/civil.json",
    "elec": "data/curricula/electronic.json",
    "ind": "data/curricula/industry.json",
    "sys": "data/curricula/infosystems.json",
    "mech": "data/curricula/mechines.json",
    "software": "data/curriculum.json",
    "math": "data/curricula/math-winter.json",
}

_CODE = re.compile(r"\d{5,6}")
_SEMESTER_TITLE = re.compile(r"סמסטר\s*(\d+)")


@dataclass(frozen=True)
class Row:
    code: str
    name: str
    #: כל הסמסטרים שבהם הקוד מופיע. בהנדסת תעשייה וניהול הדף מציג את שמונת
    #: הסמסטרים פעמיים, פעם לכל התמחות, וקורס יכול לשבת בסמסטר אחר בכל אחת.
    semesters: tuple[str, ...]
    credits: float | None


@dataclass(frozen=True)
class Diff:
    kind: str  # GONE | NEW | SEMESTER | CREDITS
    code: str
    name: str
    detail: str


def _text(fragment: str) -> str:
    """טקסט גלוי של קטע HTML, עם רווחים מכווצים."""
    no_tags = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", _html.unescape(no_tags)).strip()


def _number(cell: str) -> float | None:
    cell = cell.replace("–", "").replace("-", "").strip()
    try:
        return float(cell)
    except ValueError:
        return None


def _cells(row_html: str) -> list[str]:
    return [_text(c) for c in re.findall(r"<t[dh]\b.*?</t[dh]>", row_html, re.S)]


def _columns(header: list[str]) -> dict[str, int] | None:
    """מיקומי העמודות לפי שורת הכותרת, או None אם זו אינה טבלת קורסים."""
    cols: dict[str, int] = {}
    for i, h in enumerate(header):
        if "מספר" in h and "קורס" in h:
            cols.setdefault("code", i)
        elif "שם הקורס" in h:
            cols.setdefault("name", i)
        elif "נקודות זכות" in h or h.replace('"', "") == "נז":
            cols.setdefault("credits", i)
    # בכמה טבלאות (מכונות סמסטרים 5–6, מתמטיקה סמסטר 2) תא הכותרת של
    # מספר הקורס ריק. בכל הטבלאות הוא העמודה שלפני שם הקורס.
    if "code" not in cols and cols.get("name", 0) > 0:
        cols["code"] = cols["name"] - 1
    return cols if {"code", "name"} <= cols.keys() else None


def parse_page(page: str) -> dict[str, Row]:
    """קורסי החובה בדף שנתון, לפי קוד. נקודות הזכות והשם — מהמופע הראשון."""
    parts = re.split(
        r'<a[^>]*class="[^"]*accordion-title[^"]*"[^>]*>(.*?)</a>', page, flags=re.S
    )
    rows: dict[str, Row] = {}
    for i in range(1, len(parts), 2):
        m = _SEMESTER_TITLE.match(_text(parts[i]))
        if not m:
            continue
        semester = m.group(1)
        for table in re.findall(r"<table\b.*?</table>", parts[i + 1], re.S):
            cols = None
            for tr in re.findall(r"<tr\b.*?</tr>", table, re.S):
                cells = _cells(tr)
                if cols is None:
                    cols = _columns(cells)
                    continue
                if len(cells) <= max(cols.values()):
                    continue
                code = cells[cols["code"]]
                if not _CODE.fullmatch(code):
                    continue
                if code in rows:
                    old = rows[code]
                    if semester not in old.semesters:
                        rows[code] = Row(code, old.name, old.semesters + (semester,), old.credits)
                    continue
                credits = _number(cells[cols["credits"]]) if "credits" in cols else None
                rows[code] = Row(code, cells[cols["name"]], (semester,), credits)
    return rows


def load_ours(path: Path) -> dict[str, Row]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: dict[str, Row] = {}
    for key, sem in data.get("semesters", {}).items():
        for c in sem.get("courses", []):
            code = str(c.get("code") or "").strip()
            if code and code not in rows:
                cr = c.get("credits")
                rows[code] = Row(code, c.get("name", ""), (str(key),), None if cr is None else float(cr))
    return rows


def _sems(row: Row) -> str:
    return "/".join(row.semesters)


def compare(ours: dict[str, Row], theirs: dict[str, Row]) -> list[Diff]:
    diffs: list[Diff] = []
    for code, o in ours.items():
        t = theirs.get(code)
        if t is None:
            diffs.append(Diff("GONE", code, o.name, f"סמסטר {_sems(o)} אצלנו, לא בשנתון"))
            continue
        if not set(o.semesters) & set(t.semesters):
            diffs.append(Diff("SEMESTER", code, o.name, f"סמסטר {_sems(o)} -> {_sems(t)}"))
        if t.credits is not None and o.credits is not None and abs(t.credits - o.credits) > 1e-9:
            diffs.append(Diff("CREDITS", code, o.name, f'{o.credits:g} -> {t.credits:g} נ"ז'))
    for code, t in theirs.items():
        if code not in ours:
            cr = "" if t.credits is None else f', {t.credits:g} נ"ז'
            diffs.append(Diff("NEW", code, t.name, f"סמסטר {_sems(t)}{cr}"))
    order = {"GONE": 0, "NEW": 1, "SEMESTER": 2, "CREDITS": 3}
    return sorted(diffs, key=lambda d: (order[d.kind], d.code))


def fetch(url: str, timeout: float = 45.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "SlotWise curriculum check"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def next_year(year: str) -> str:
    """‏'26-27' -> '27-28'."""
    a, b = (int(x) for x in year.split("-"))
    return f"{a + 1:02d}-{b + 1:02d}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", default=DEFAULT_YEAR, help="שנת השנתון בכתובת, למשל 26-27")
    ap.add_argument("--html-dir", type=Path, help="קריאה מקבצים שמורים <slug>.html במקום מהרשת")
    ap.add_argument("--save-html", type=Path, help="שמירת הדפים שנמשכו לתיקייה")
    ap.add_argument("--pace", type=float, default=DEFAULT_PACE)
    ap.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    total = 0
    errors = 0
    print(f"# השוואת תוכניות לימודים מול שנתון {args.year}\n")
    for n, (slug, rel) in enumerate(PROGRAMS.items()):
        url = BASE.format(year=args.year, slug=slug)
        if args.html_dir:
            page_path = args.html_dir / f"{slug}.html"
            if not page_path.exists():
                print(f"## {slug}\nחסר קובץ {page_path}\n")
                errors += 1
                continue
            page = page_path.read_text(encoding="utf-8")
        else:
            if n:
                time.sleep(args.pace)
            status, page = fetch(url)
            if status != 200:
                print(f"## {slug}\nמשיכת {url} החזירה {status}\n")
                errors += 1
                continue
            if args.save_html:
                args.save_html.mkdir(parents=True, exist_ok=True)
                (args.save_html / f"{slug}.html").write_text(page, encoding="utf-8")

        theirs = parse_page(page)
        if not theirs:
            print(f"## {slug}\nלא נמצאו טבלאות סמסטרים ב-{url} — ייתכן שמבנה הדף השתנה.\n")
            errors += 1
            continue
        diffs = compare(load_ours(args.root / rel), theirs)
        total += len(diffs)
        print(f"## {slug} — `{rel}` ({len(diffs)} הבדלים)\n")
        print(f"מקור: {url}\n")
        for d in diffs:
            print(f"- **{d.kind}** `{d.code}` {d.name} — {d.detail}")
        print()

    if not args.html_dir:
        time.sleep(args.pace)
        upcoming = next_year(args.year)
        # כתובת שאינה קיימת מפנה (301) לדף אחר שעונה 200, ולכן "200" לבדו
        # אינו הוכחה. שנתון נחשב מפורסם רק אם דף מחלקה בו מכיל טבלאות סמסטרים.
        status, page = fetch(BASE.format(year=upcoming, slug="elec"))
        if status == 200 and parse_page(page):
            print(f"**שימו לב:** שנתון {upcoming} כבר מפורסם. הגיע הזמן להריץ עם `--year {upcoming}`.\n")
            total += 1

    if errors:
        return 2
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
