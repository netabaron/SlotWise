"""
src/shnaton.py — פענוח פרקי השנתון של המחלקות (‏PDF) לקבוצות קורסי בחירה.

מה זה עושה
----------
כל מחלקה בבראודה מפרסמת פרק שנתון משלה. הפרקים חולקים את **פורמט הטבלה**
(``מס' | שם הקורס | ה ת [מ] [פ] | נ"ז | קורסי קדם``) אבל **לא** את הדרך שבה
הם מארגנים את קורסי הבחירה. נמדדו שלושה מבנים שונים:

===========================  ==========================  =========================
מבנה                          מחלקות                      משמעות לתואר
===========================  ==========================  =========================
‏**אשכולות** (``אשכול X``)      תוכנה, תעשייה וניהול,        קורס אחד **מכל** אשכול
                              מערכות מידע
‏**מסלולים** (``מסלול X``)      אזרחית, מכונות              בוחרים מסלול **אחד**
‏אין קיבוץ                     חשמל, מתמטיקה שימושית        רשימת בחירה שטוחה
===========================  ==========================  =========================

ההבדל בין השניים הראשונים אינו קוסמטי: אשכול פירושו "אחד מכל קבוצה", מסלול
פירושו "בוחרים מסלול ומתמחים בו". להציג מסלול בשם אשכול היה מסלף את חוקי
התואר, ולכן הם נשמרים בשדות נפרדים.

מגבלת המקור
-----------
רק שני פרקים מציינים שנת מחזור במפורש (``עבור סטודנטים שהחלו לימודיהם
בשנה"ל ...``). באחרים אין שנה בשום מקום, ואז ``year`` הוא ``None`` — ולא
ניחוש. הצרכן חייב להציג "שנה לא צוינה" ולא להמציא תאריך.

Technical notes:
    * Coordinate-aware RTL row reconstruction. ``page.get_text()`` alone
      scrambles these tables - words interleave and columns reverse.
    * PyMuPDF only. No network, no browser.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:  # pragma: no cover - נבדק בזמן ייבוא בלבד
    import pymupdf
except ImportError:  # pragma: no cover
    import fitz as pymupdf  # type: ignore[no-redef]

__all__ = [
    "build_curricula",
    "load_curricula",
    "DEFAULT_CURRICULA_PATH",
    "extract_rows",
    "parse_chapter",
    "parse_all",
    "STRUCTURE_CLUSTERS",
    "STRUCTURE_TRACKS",
    "STRUCTURE_FLAT",
]

DEFAULT_CURRICULA_PATH = "data/curricula.json"

STRUCTURE_CLUSTERS = "clusters"
STRUCTURE_TRACKS = "tracks"
STRUCTURE_FLAT = "flat"

#: כותרת אשכול: "אשכול מדעים" / "אשכול: ניהול" (תעשייה כותבת עם נקודתיים).
_CLUSTER_RE = re.compile(r"^אשכול\s*:?\s*(.{2,60})$")

#: כותרת מסלול: "מסלול תכן וייצור".
_TRACK_RE = re.compile(r"^מסלול\s+(.{2,60})$")

#: שורת קורס מתחילה בקוד בן 5-6 ספרות.
_CODE_RE = re.compile(r"^(\d{5,6})\b")

#: נ"ז: מספר עשרוני בודד, למשל 2.5 או 3.0.
_CREDITS_RE = re.compile(r"\b(\d{1,2}\.\d)\b")

#: שם המחלקה בראש הפרק.
_DEPT_RE = re.compile(r"המחלקה\s+ל(.{3,40})")
_PROGRAM_RE = re.compile(r"הת\s*ו?\s*כנית\s+ב(.{3,50})")

#: שנת המחזור, כשהיא מוצהרת.
_COHORT_RE = re.compile(r"שהחלו\s*לימודיהם\s*בשנה\s*\"?ל\s*(תשפ\s*\"?\s*[א-ט])")

#: כותרות שפותחות **פרק חדש** ולכן סוגרות קבוצת בחירה פתוחה.
#: בלי זה הקבוצה האחרונה בכל פרק ממשיכה לבלוע עד סוף המסמך — נצפה בפועל
#: ב-mecho.pdf, שם המסלול האחרון אסף גם את קורסי מסלול "מהנדסאים להנדסה"
#: שבעמוד האחרון והגיע ל-62 קורסים.
_SECTION_END_RE = re.compile(
    r"^(מהנדסאים|הנדסאים|פטור|נספח|לימודי\s+תואר|תוכנית\s+לימודים|"
    r"תכנית\s+לימודים|קורסים\s+כלליים|לימודים\s+כלליים)"
)
# מכוון: **בלי** "סה\"כ" ו"מקרא". הם כותרות של *סוף טבלה*, לא של פרק חדש,
# ומופיעים באמצע רשימות בחירה — הוספתם קיצצה את אשכול "מדע וטכנולוגיה"
# בתעשייה וניהול מ-20 קורסים ל-3.

#: כותרות שמסמנות שהחלק של קורסי החובה נגמר ומתחילים הבחירה/ההתמחות.
_ELECTIVE_MARKERS = ("קורסיבחירה", "קורסיהבחירה", "מקצועותבחירה", "לימודיהתמחות")


def _squash(text: str) -> str:
    """מסיר את כל הרווחים — להשוואות בלבד. ‏PDF עברי מפזר רווחים בתוך מילים."""
    return re.sub(r"\s+", "", text or "")


def _tidy(text: str) -> str:
    """מכווץ רווחים כפולים לשורה קריאה אחת."""
    return re.sub(r"\s{2,}", " ", (text or "").strip())


def extract_rows(pdf_path: str | Path) -> list[tuple[int, str]]:
    """‏[(מספר עמוד, טקסט השורה)] — שחזור שורות מודע-קואורדינטות, מימין לשמאל.

    זו אותה טכניקה שבה נגזר ``data/curriculum.json``: מקבצים מילים לפי ``y``,
    וממיינים כל שורה לפי ``x`` **יורד**. ``get_text()`` רגיל מערבב שורות
    בטבלאות עבריות ומחזיר עמודות הפוכות.
    """
    doc = pymupdf.open(str(pdf_path))
    out: list[tuple[int, str]] = []
    try:
        for index, page in enumerate(doc):
            buckets: list[dict[str, Any]] = []
            for word in sorted(page.get_text("words"), key=lambda w: (round(w[1], 1), -w[0])):
                for bucket in buckets:
                    if abs(bucket["y"] - word[1]) <= 4.0:
                        bucket["w"].append(word)
                        break
                else:
                    buckets.append({"y": word[1], "w": [word]})
            for bucket in sorted(buckets, key=lambda b: b["y"]):
                ordered = sorted(bucket["w"], key=lambda w: -w[0])
                line = "  ".join(w[4] for w in ordered).strip()
                if line:
                    out.append((index + 1, line))
    finally:
        doc.close()
    return out


def _program_name(rows: list[tuple[int, str]]) -> str:
    """שם המחלקה/התוכנית מראש הפרק.

    עובדים על השורה **המרווחת** ולא על הדחוסה: ב-PDF עברי המילים מגיעות
    מופרדות ("המחלקה  ל  הנדסה  אזרחית"), ודחיסה מוחקת את הגבולות.
    """
    for _page, line in rows[:80]:
        spaced = _tidy(line.replace("  ", " "))
        match = re.search(r"המחלקה\s+ל\s*(.{3,44})", spaced) or re.search(
            r"הת\s*ו?\s*כנית\s+ב\s*(.{3,50})", spaced
        )
        if match:
            name = re.split(r"[–-]|רפורמה|\d", match.group(1))[0]
            name = _tidy(name).strip(" ,.:-–")
            if 3 <= len(name) <= 44:
                return name
    return ""


def _cohort_year(rows: list[tuple[int, str]]) -> str | None:
    """שנת המחזור, אם וכאשר הפרק מצהיר עליה. אחרת ``None`` — לא ניחוש."""
    for _page, line in rows:
        match = _COHORT_RE.search(_squash(line))
        if match:
            return re.sub(r"\s+", "", match.group(1))
    return None


def _is_course_row(line: str) -> tuple[str, str] | None:
    """‏(קוד, שם) אם השורה היא שורת קורס אמיתית, אחרת ``None``.

    דורשים גם קוד בתחילת השורה **וגם** ערך נ"ז, כדי לא לתפוס שורות של
    קורסי קדם (שגם הן מתחילות בקוד, אבל אין בהן נ"ז).
    """
    code_match = _CODE_RE.match(_tidy(line))
    if not code_match:
        return None
    tidy = _tidy(line)
    rest = tidy[code_match.end() :]
    if not _CREDITS_RE.search(rest):
        return None
    # השם הוא מה שלפני עמודת השעות הראשונה.
    name = re.split(r"\s+(?:\d+(?:\.\d)?|-)\s", rest, maxsplit=1)[0]
    name = _tidy(re.sub(r"[\s\-–]+$", "", name))
    return code_match.group(1), name


def canonical_program(name: str) -> str:
    """מיישר את שם המחלקה לשם הרשמי מאתר המכללה.

    ה-PDF שובר מילים באמצע ("הנדסת תו כנה", "מערכות מיד ע"), ולכן משווים
    בצורה דחוסה מול ``data/programs.json`` — הרשימה המוסמכת שנמשכת מהאתר.
    אין התאמה? מחזירים את מה שנקרא, בלי להמציא.
    """
    squashed = _squash(name)
    if not squashed:
        return name
    try:
        from programs import load_programs

        official = load_programs(str(Path(__file__).resolve().parent.parent / "data" / "programs.json"))
    except Exception:  # noqa: BLE001
        official = []
    for entry in official:
        title = str(entry.get("name") or "")
        if not title:
            continue
        if _squash(title) == squashed or _squash(title).startswith(squashed) or squashed.startswith(_squash(title)):
            return title
    return name


def parse_chapter(pdf_path: str | Path) -> dict:
    """מפענח פרק שנתון אחד.

    Returns:
        ``{program, source, year, structure, clusters, tracks, warnings}``
        ``clusters``/``tracks`` הם ``{שם הקבוצה: [{code, name}]}``.
    """
    path = Path(pdf_path)
    rows = extract_rows(path)
    warnings: list[str] = []

    clusters: dict[str, list[dict]] = {}
    tracks: dict[str, list[dict]] = {}
    current: list[dict] | None = None
    seen_elective_zone = False
    carry = ""  # שורת טקסט אחרונה שעשויה להיות שם של הקורס הבא

    for _page, line in rows:
        tidy = _tidy(line)
        squashed = _squash(line)

        if any(marker in squashed for marker in _ELECTIVE_MARKERS):
            seen_elective_zone = True

        cluster = _CLUSTER_RE.match(tidy)
        track = _TRACK_RE.match(tidy)
        if cluster or track:
            raw = (cluster or track).group(1)
            # מנקים סוגריים/הערות נלוות: "אשכול סמינרים *(כל הקורסים...)".
            name = _tidy(re.split(r"[(*]", raw)[0]).strip(" :-–")
            if not name or len(name) > 60:
                continue
            seen_elective_zone = True
            bucket = clusters if cluster else tracks
            current = bucket.setdefault(name, [])
            continue

        # כותרת סמסטר, או תחילת פרק חדש, מסיימות קבוצת בחירה פתוחה.
        if re.match(r"^סמסטר\s*\d", tidy) or _SECTION_END_RE.match(tidy):
            current = None
            carry = ""
            continue

        if current is None or not seen_elective_zone:
            if not _CODE_RE.match(tidy) and 4 < len(squashed) < 60:
                carry = tidy  # שם שעלול להיות שייך לשורת הקורס הבאה
            continue
        found = _is_course_row(tidy)
        if found:
            code, name = found
            if not name and carry:
                # שם הקורס נשבר לשורה הקודמת, והשורה הזאת מתחילה ישר בשעות:
                #   "מבוא להנדסת מערכות ותעשיה 4.0"
                #   "62004  2 1 - 2.5  61756 שיטות הנדסיות..."
                # בלי זה הקורס נשמר בלי שם בכלל.
                name = carry
            if not any(c["code"] == code for c in current):
                current.append({"code": code, "name": name})
            carry = ""
        elif not _CODE_RE.match(tidy) and 4 < len(squashed) < 60:
            carry = tidy
        else:
            carry = ""

    clusters = {k: v for k, v in clusters.items() if v}
    tracks = {k: v for k, v in tracks.items() if v}

    if clusters and tracks:
        warnings.append(
            "בפרק נמצאו גם אשכולות וגם מסלולים — שני המבנים נשמרו בנפרד."
        )
    structure = (
        STRUCTURE_CLUSTERS if clusters else STRUCTURE_TRACKS if tracks else STRUCTURE_FLAT
    )
    year = _cohort_year(rows)
    if year is None:
        warnings.append("הפרק אינו מציין שנת מחזור — אין להציג שנה מנוחשת.")

    return {
        "program": canonical_program(_program_name(rows)),
        "program_raw": _program_name(rows),
        "source": path.name,
        "year": year,
        "structure": structure,
        "clusters": clusters,
        "tracks": tracks,
        "warnings": warnings,
    }


def parse_all(folder: str | Path = ".", pattern: str = "*.pdf") -> dict:
    """מפענח את כל פרקי השנתון בתיקייה. ``{source: chapter}``."""
    out: dict[str, dict] = {}
    for pdf in sorted(Path(folder).glob(pattern)):
        try:
            out[pdf.name] = parse_chapter(pdf)
        except Exception as exc:  # noqa: BLE001 - פרק פגום לא מפיל את השאר
            out[pdf.name] = {
                "program": "",
                "source": pdf.name,
                "year": None,
                "structure": STRUCTURE_FLAT,
                "clusters": {},
                "tracks": {},
                "warnings": [f"פענוח נכשל: {type(exc).__name__}: {exc}"],
            }
    return out


if __name__ == "__main__":  # pragma: no cover
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    for name, chapter in parse_all(".").items():
        head = f"{name}  [{chapter['structure']}]"
        year = chapter["year"] or "שנה לא צוינה"
        print(f"\n{head}  program={chapter['program']!r}  year={year}")
        for label, groups in (("אשכול", chapter["clusters"]), ("מסלול", chapter["tracks"])):
            for group, courses in groups.items():
                print(f"   {label} {group[:40]:42} {len(courses):3} courses")


def build_curricula(
    folder: str | Path = ".", out_path: str | Path = DEFAULT_CURRICULA_PATH
) -> str:
    """מפענח את כל פרקי השנתון בתיקייה וכותב ``data/curricula.json``.

    המפתח הוא **שם התוכנית הרשמי** (מאתר המכללה), כדי שהממשק יוכל לחפש לפי
    מה שהסטודנט/ית בחר/ה בשלב 1.
    """
    chapters = parse_all(folder)
    by_program: dict[str, dict] = {}
    for chapter in chapters.values():
        name = chapter.get("program") or ""
        if not name:
            continue
        by_program[name] = {
            "program": name,
            "source": chapter["source"],
            "year": chapter["year"],
            "structure": chapter["structure"],
            "clusters": chapter["clusters"],
            "tracks": chapter["tracks"],
            "warnings": chapter["warnings"],
        }
    payload = {
        "schema": "braude-schedule-builder/curricula",
        "version": 1,
        "note": (
            "נגזר מפרקי השנתון של המחלקות. 'year' הוא שנת המחזור **רק** כשהפרק "
            "מצהיר עליה; None פירושו שהמסמך אינו מציין שנה, ואין להציג שנה מנוחשת."
        ),
        "programs": by_program,
    }
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8"
    )
    return str(target)


def load_curricula(path: str | Path = DEFAULT_CURRICULA_PATH) -> dict:
    """קורא את הקובץ. חסר או פגום -> ``{}``, בלי לזרוק."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    programs = data.get("programs") if isinstance(data, dict) else None
    return programs if isinstance(programs, dict) else {}
