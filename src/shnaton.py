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

שם הקורס נבנה מעמודה, לא ממחרוזת
---------------------------------
שורת קורס נשברת לעיתים קרובות לשתיים ואף לשלוש שורות ויזואליות: חלק מהשם
מעל שורת המספרים, חלק מתחתיה. **כל** אחת מהשורות האלה נושאת גם את עמודת
"קורסי קדם" של אותו גובה, ושם יושבים מספרי קורס אחרים ושמותיהם.

לכן כל מה שנוגע בשם קורס עובד על ``Line.words`` — מילים עם ``x`` — ולא על
``Line.text``, שבו שתי העמודות נראות זהות. ``_anchor_at`` גוזר משורת
המספרים את גבולות עמודת השם, ו-``_bind_names`` אוסף רק מה שנופל בתוכם.

עד 2026-09-23 הפענוח עבד על הטקסט השטוח, ושורת המשך נשמרה כ"שם אפשרי"
שלמה — כולל עמודת הקדם. כך ``51145`` קיבל את השם "ניהול והערכת סיכונים
‏11001 אלגברה" במקום "ניהול והערכת סיכונים בפרויקטים הנדסיים": חצי שם,
ועליו מספר קורס של קורס אחר ומחצית שמו. ‏22 שורות ב-``data/curricula.json``
היו כאלה. ‏``tests/test_shnaton_row_binding.py`` נועל את זה על הגאומטריה
האמיתית של אותה שורה.

מגבלת המקור
-----------
רק שני פרקים מציינים שנת מחזור במפורש (``עבור סטודנטים שהחלו לימודיהם
בשנה"ל ...``). באחרים אין שנה בשום מקום, ואז ``year`` הוא ``None`` — ולא
ניחוש. הצרכן חייב להציג "שנה לא צוינה" ולא להמציא תאריך.

Technical notes:
    * Coordinate-aware RTL row reconstruction. ``page.get_text()`` alone
      scrambles these tables - words interleave and columns reverse.
    * A course name is cut by x-bounds, never by a regex over flattened
      text: the name column and the prerequisite column look identical
      once the line is a single string.
    * Latin text inside a Hebrew name still reads reversed ("to Solutions
      Designing"), because the join is right-to-left for the whole line.
      Pre-existing, and untouched here.
    * PyMuPDF only. No network, no browser.
"""

from __future__ import annotations

import bisect
import difflib
import json
import re
from pathlib import Path
from typing import Any, NamedTuple

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


#: מילה אחת בשורה: ``(x0, x1, טקסט)``. ‏x גדל שמאלה, כלומר בעברית העמודה
#: הימנית ביותר (מספר הקורס) היא זו עם ה-x **הגדול** ביותר.
Word = tuple[float, float, str]


class Line(NamedTuple):
    """שורה ויזואלית אחת, עם הגאומטריה שלה שמורה.

    ‏``text`` הוא בדיוק מה ש-``extract_rows`` החזיר תמיד — כל העמודות
    משורשרות לשורה אחת. הוא נוח לזיהוי כותרות, והוא **הרסני** לשמות:
    שם קורס ועמודת "קורסי קדם" נראים בו זהים. ``words`` הוא מה שמאפשר
    להבדיל, ולכן כל מה שנוגע בשם קורס עובד עליו ולא על ``text``.
    """

    page: int
    y: float
    words: tuple[Word, ...]
    text: str
    #: גובה כל מילה, באותו סדר כמו ``words``. משמש רק את ``parse_electives``
    #: כדי לזהות סימני הערת שוליים בכתב עילי; ריק בשורות שנבנו ביד.
    heights: tuple[float, ...] = ()


def _reading_order(words: list[Any]) -> list[Any]:
    """מילים של שורה ויזואלית אחת, בסדר הקריאה שלהן.

    ‏**מיון לפי x יורד נכון לעברית ושקרי לכל דבר אחר.** קטע לטיני בתוך שם
    עברי נכתב משמאל לימין, ולכן מיון ימין-לשמאל מהפך אותו: ‏22837 יצא
    ‏"to Solutions Designing Problems Surgical" במקום "Designing Solutions
    to Surgical Problems", ו-22993 יצא "תעשייה 4.0 4.0) (Industry" במקום
    ‏"תעשייה 4.0 (Industry 4.0)".

    ‏PyMuPDF מקבץ מילים ל-``(block, line)``, וזה בדיוק הגבול של קטע בעל
    כיוון אחד. **אבל ``word_no`` הוא סדר הציור ולא סדר הקריאה**, ולכן אי
    אפשר לסמוך עליו לבדו: ב-industry.pdf הכותרת "אשכול: תכן ותפעול" היא
    קטע אחד שבו הנקודתיים מצוירות **לפני** המילה שלפניה, ומיון לפי
    ‏``word_no`` הפך אותה ל-": אשכול תכן ותפעול" — שאינה מתאימה יותר
    ל-``_CLUSTER_RE``, ושישה-עשר קורסים דלפו לאשכול השכן.

    המבחן הוא הגאומטריה עצמה, ועוד תנאי: קטע שה-x שלו **עולה** לאורך
    ‏``word_no`` **ושיש בו אות לטינית** הוא קטע שנכתב משמאל לימין, ושם סדר
    הציור הוא סדר הקריאה. בכל מקרה אחר חוזרים למיון ימין-לשמאל, כלומר
    להתנהגות שהייתה כאן מאז ומתמיד.

    האות הלטינית אינה קישוט. הכותרת "אשכול: מדע וטכנולוגיה" היא קטע של
    שתי מילים — נקודתיים ואז "אשכול" — שה-x שלו עולה במקרה, ובלי התנאי
    הזה הוא נקרא ‏": אשכול" ושלושה קורסים דלפו לאשכול השכן.
    """
    runs: dict[tuple[int, int], list[Any]] = {}
    for word in words:
        runs.setdefault((word[5], word[6]), []).append(word)

    ordered_runs: list[list[Any]] = []
    for run in runs.values():
        drawn = sorted(run, key=lambda w: w[7])
        ascending = all(a[0] < b[0] for a, b in zip(drawn, drawn[1:]))
        latin = any(_LATIN_RE.search(w[4]) for w in drawn)
        if ascending and latin:
            ordered_runs.append(drawn)
        else:
            ordered_runs.append(_unmirror(sorted(run, key=lambda w: -w[0])))

    ordered_runs.sort(key=lambda run: -max(w[2] for w in run))
    return [word for run in _latin_fragments_forward(ordered_runs) for word in run]


def _latin_only(run: list[Any]) -> bool:
    return all(_LATIN_RE.search(w[4]) and not _HEBREW_RE.search(w[4]) for w in run)


def _latin_fragments_forward(runs: list[list[Any]]) -> list[list[Any]]:
    """קטעים לטיניים **נוגעים** זה בזה נקראים משמאל לימין.

    ‏electric.pdf עמוד 13 מצייר את "NLP" של ‏51914 כשני קטעים: ‏"LP" ואז
    ‏"N" משמאלו, צמוד. מיון הקטעים מימין לשמאל שם את "LP" ראשון, והשם יצא
    ‏"LPN מבוא לעיבוד שפה טבעית". קטעים לטיניים עם רווח ביניהם אינם נוגעים
    ונשארים כפי שהיו.
    """
    out: list[list[Any]] = []
    group: list[list[Any]] = []
    for run in runs:
        touching = (
            group
            and _latin_only(run)
            and min(w[0] for w in group[-1]) - max(w[2] for w in run) < _GLUE_GAP
        )
        if touching:
            group.append(run)
            continue
        out.extend(reversed(group))
        group = [run] if _latin_only(run) else []
        if not group:
            out.append(run)
    out.extend(reversed(group))
    return out


def _unmirror(run: list[Any]) -> list[Any]:
    """מחזיר סוגריים שאוחסנו כגלִיף מצויר לצורתם הלוגית.

    ‏**לא פתרון דו-כיווניות.** המבחן הוא מקומי ובדיד: אם הסוגר הראשון
    שנפגש בסדר הקריאה הוא סוגר **סוגר**, הזוג אינו מקונן ולכן מה שאוחסן
    הוא הבבואה. אז — ורק אז — מחליפים כל סוגר בודד בקטע הזה.

    שני הפרקים מוכיחים למה זה חייב להיות מבחן ולא כלל גורף:

    * ‏system.pdf, שורת ‏61966: בסדר הקריאה ‏")" מופיע לפני "(", כלומר
      מצויר. בלי התיקון: "סמינר מערכות לומדות )באנגלית(".
    * ‏industry.pdf, הכותרת "אשכול: מדע וטכנולוגיה (עבור שתי ההתמחויות)":
      בסדר הקריאה ‏"(" לפני ")", כלומר לוגי כבר עכשיו. היפוך גורף היה
      שובר אותה, ואיתה את שם האשכול שנגזר ממנה.

    מוחלפים רק תווים שהם סוגר **בודד**. ‏"(Industry" הוא חלק ממילה, והוא
    ממילא בקטע לטיני שאינו עובר כאן.
    """
    brackets = [word[4] for word in run if word[4] in _MIRROR]
    if not brackets or brackets[0] not in _CLOSERS:
        return run
    return [
        (word[:4] + (_MIRROR[word[4]],) + tuple(word[5:]))
        if word[4] in _MIRROR
        else word
        for word in run
    ]


def _document_lines(pdf_path: str | Path) -> list[Line]:
    """כל השורות של המסמך, עם הקואורדינטות שלהן.

    מקבצים מילים לפי ``y``, ובתוך כל שורה מסדרים לפי סדר הקריאה — ראו
    ‏``_reading_order``. ‏``get_text()`` רגיל מערבב שורות בטבלאות עבריות
    ומחזיר עמודות הפוכות, ולכן השחזור נעשה כאן ולא על ידו.
    """
    doc = pymupdf.open(str(pdf_path))
    out: list[Line] = []
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
                ordered = _reading_order(bucket["w"])
                words = tuple((float(w[0]), float(w[2]), w[4]) for w in ordered)
                heights = tuple(float(w[3]) - float(w[1]) for w in ordered)
                text = "  ".join(w[2] for w in words).strip()
                if text:
                    out.append(Line(index + 1, float(bucket["y"]), words, text, heights))
    finally:
        doc.close()
    return out


def extract_rows(pdf_path: str | Path) -> list[tuple[int, str]]:
    """‏[(מספר עמוד, טקסט השורה)] — שחזור שורות מודע-קואורדינטות, מימין לשמאל.

    נשאר כפי שהיה עבור מי שקורא טקסט בלבד (זיהוי שם המחלקה, שנת המחזור,
    והבדיקות). מי שצריך **עמודה** מסוימת חייב את ``_document_lines``.
    """
    return [(line.page, line.text) for line in _document_lines(pdf_path)]


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


#: תא בעמודה מספרית: שעות (‏ה/ת/מ/פ), נ"ז, או מקף שמציין עמודה ריקה.
#: ‏**עד ארבע ספרות בכוונה** — מספר קורס הוא בן 5–6, ולכן עמודת "קורסי קדם"
#: לעולם אינה נספרת כאן, וגבול עמודת השם אינו נמשך שמאלה עד אליה.
_COLUMN_CELL_RE = re.compile(r"^(?:\d{1,4}(?:\.\d+)?|[-–—])$")

#: נ"ז כפי שהיא מודפסת בתא משלה: ‏"2.5", "4.0".
_CREDITS_CELL_RE = re.compile(r"^\d{1,2}\.\d$")


class _Anchor(NamedTuple):
    """שורת הפתיחה של קורס, ועמודת השם שנגזרת ממנה.

    ‏``name_from``/``name_to`` הם גבולות עמודת השם ב-x: מימין מספר הקורס,
    ומשמאל התא המספרי הימני ביותר. **זה כל התיקון.** קודם לכן השם נחתך
    מתוך שורת טקסט שטוחה, ושורת המשך שנשמרה כ"שם אפשרי" הכילה את עמודת
    "קורסי קדם" של אותה שורה — ולכן שם כמו "ניהול והערכת סיכונים" יצא
    ‏"ניהול והערכת סיכונים 11001 אלגברה". טווח ב-x אינו יכול לבלוע עמודה
    שכנה, כי עמודה שכנה היא בדיוק מה שנמצא מחוץ לטווח.
    """

    index: int
    code: str
    name_from: float
    name_to: float


def _numeric_block_edge(words: tuple[Word, ...]) -> float | None:
    """הקצה הימני של גוש העמודות המספריות, או ``None`` אם אין כזה.

    ‏**הגוש הוא הרצף האחרון שיש בו תא נ"ז**, ולא פשוט התא המספרי הימני
    ביותר. שני מקרים אמיתיים מחייבים את זה, והם מושכים לכיוונים הפוכים:

    * ‏"מבוא ל-ERP ומערכות ארגוניות" — המקף שבתוך השם הוא תא מספרי לכל
      דבר לפי הצורה. אילו הוא היה קובע את הגבול, השם היה נחתך ל"מבוא".
    * ‏"טכנולוגיות מתקדמות בעידן תעשייה 4.0" — ‏4.0 שבתוך השם **נראה**
      בדיוק כמו תא נ"ז. אילו הוא היה קובע, היה נופל סוף השם.

    שני הרצפים האלה יושבים מימין לגוש האמיתי, ולכן "האחרון שיש בו נ"ז"
    מדלג על שניהם.
    """
    runs: list[list[Word]] = []
    open_run = False
    for word in words:
        if _COLUMN_CELL_RE.match(word[2]):
            if not open_run:
                runs.append([])
                open_run = True
            runs[-1].append(word)
        else:
            open_run = False
    blocks = [r for r in runs if any(_CREDITS_CELL_RE.match(w[2]) for w in r)]
    if not blocks:
        return None
    return blocks[-1][0][1]


def _anchor_at(line: Line) -> _Anchor | None:
    """‏``_Anchor`` אם השורה פותחת קורס, אחרת ``None``.

    שלושה תנאים, וכולם נחוצים: המילה הימנית ביותר היא מספר קורס; יש
    משמאלה גוש עמודות מספריות; ויש בו נ"ז. התנאי השלישי הוא מה שמפריד
    שורת קורס משורת "קורסי קדם", שגם היא פותחת במספר קורס.
    """
    if not line.words:
        return None
    x0, _x1, token = line.words[0]
    if not re.fullmatch(r"\d{5,6}", token):
        return None
    edge = _numeric_block_edge(tuple(w for w in line.words[1:] if w[1] < x0))
    if edge is None:
        return None
    return _Anchor(-1, token, edge, x0)


def _name_words(line: Line, anchor: _Anchor) -> list[Word]:
    """המילים של השורה שנופלות בתוך עמודת השם של הקורס."""
    return [w for w in line.words if anchor.name_from < w[0] < anchor.name_to]


#: מתחת למרווח הזה שתי "מילים" הן מילה אחת ש-PyMuPDF פיצל לשני runs.
#: נמדד ב-sw.pdf: מרווח אמיתי בין מילים הוא ‏1.8–2.5 נקודות, והפיצול
#: הפנימי של "בנושאים" ל-"ב" ו-"נושאים" הוא ‏0.10.
_GLUE_GAP = 1.0

#: אות לטינית — הסימן שקטע נכתב משמאל לימין.
_LATIN_RE = re.compile(r"[A-Za-z]")
#: אות עברית — קטע שיש בו אחת אינו "לטיני בלבד".
_HEBREW_RE = re.compile(r"[\u0590-\u05FF]")

#: סוגריים והבבואה שלהם. ‏Unicode מגדיר לתווים האלה "mirroring": בהקשר
#: ימין-לשמאל הם **מצוירים** הפוך מכפי שהם מאוחסנים, ויש מחוללי PDF
#: שמאחסנים את הגלִיף המצויר במקום את התו הלוגי.
_MIRROR = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{"}
_CLOSERS = frozenset(")]}")

#: פיסוק שנדבק למילה שלפניו. בפרק אזרחית ‏":" מודפס כ-run נפרד במרווח
#: רגיל, ולכן חיבור לפי מרווח אינו תופס אותו.
_CLINGING = frozenset(":,;.")


def _join_words(words: list[Word]) -> str:
    """מחבר מילים לשם, עם רווח רק היכן שה-PDF באמת שם אחד."""
    out: list[str] = []
    for index, word in enumerate(words):
        if not out:
            out.append(word[2])
            continue
        previous = words[index - 1]
        # מרחק בין שתי תיבות, בלי להניח כיוון: בקטע עברי ‏x יורד ובקטע
        # לטיני הוא עולה, והחיסור הישן החזיר מספר שלילי בלטינית — כלומר
        # "מרווח אפס" — והדביק את ‏"Designing" ל-"Solutions".
        gap = max(previous[0], word[0]) - min(previous[1], word[1])
        glued = gap < _GLUE_GAP or word[2] in _CLINGING
        if glued:
            out[-1] += word[2]
        else:
            out.append(word[2])
    return _tidy(" ".join(out))


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


#: אוצר המילים של שורת הכותרת בטבלה. שורה שכל מילותיה מכאן היא כותרת
#: עמודות ולא קורס — והיא יושבת בדיוק בעמודת השם, ולכן בלי הזיהוי הזה
#: ‏"שם הקורס" נדבק לשם של הקורס הראשון שמתחתיה.
_HEADER_WORDS = frozenset(
    """מס מספר ' " שם הקורס קורס ה ת מ פ נ ז נ"ז קורסי קדם קדמים
       וקורסים צמודים הרצאה תרגול מעבדה פרויקט""".split()
)

#: המרחק האנכי המרבי בין שורת המשך לשורה שכבר שייכת לקורס. נמדד על חמשת
#: הפרקים: בתוך שורת קורס המרווח הוא ‏4.5–12.9 נקודות, ובין שורת קורס
#: לפסקת הערה שמתחת לטבלה הוא גדול בהרבה. ‏15 עובר את הראשון ולא את השני.
_MAX_CONTINUATION_GAP = 15.0

#: כמה שורות שם קורס יכול להימשך **כלפי מטה**. ‏2 מותיר מרווח לשם ארוך
#: בלי לפתוח את הדלת לפסקה שלמה.
_MAX_CONTINUATION_LINES = 2

#: וכמה **כלפי מעלה** — אחת בדיוק. נמדד על חמשת הפרקים: שם שמודפס מעל
#: שורת המספרים תופס שורה אחת, תמיד. ‏2 כאן בלע סימן הערת שוליים
#: (‏"1" בכתב עילי) ששייך לשורה שמעליה ויושב במקרה בתוך עמודת השם —
#: ‏251100 ב-sw.pdf יצא "1 פרויקט בינתחומי במערכות בריאות ושיקום".
_MAX_PREFIX_LINES = 1


def _is_table_header(line: Line) -> bool:
    """שורת כותרת של טבלה — ‏"מס' | שם הקורס | ה ת מ פ | נ"ז | קורסי קדם"."""
    words = [w[2] for w in line.words]
    return bool(words) and all(w in _HEADER_WORDS for w in words)


def _is_header_line(text: str) -> bool:
    """כותרת — אשכול, מסלול, סמסטר, או פתיחת פרק. לא שייכת לשום קורס."""
    tidy = _tidy(text)
    return bool(
        _CLUSTER_RE.match(tidy)
        or _TRACK_RE.match(tidy)
        or _SECTION_END_RE.match(tidy)
        or re.match(r"^סמסטר\s*\d", tidy)
    )


def _may_continue(line: Line) -> bool:
    """האם השורה יכולה בכלל להיות המשך של שם קורס.

    ‏שורת כותרת של טבלה אינה יכולה — ראו ``_is_table_header``. הפסילה
    השנייה, "שורה שיש בה נ"ז שייכת לקורס משלה", **אינה** כאן אלא
    ב-``_claims``: היא תלויה בעמודות של העוגן, כי ‏4.0 שבתוך השם
    ‏"תעשייה 4.0" נראה בדיוק כמו תא נ"ז ואינו אחד.
    """
    return not (_is_header_line(line.text) or _is_table_header(line))


def _claims(line: Line, anchor: _Anchor) -> list[str] | None:
    """המילים שהשורה תורמת לשם הקורס, או ``None`` אם אינה שייכת לו.

    ‏תא נ"ז **בתוך אזור העמודות המספריות** אומר שהשורה היא שורת קורס
    בפני עצמה, גם כשמספר הקורס שלה מודפס בשורה אחרת — ‏system.pdf עושה
    בדיוק את זה. תא נ"ז בתוך עמודת השם הוא חלק מהשם, ולא סימן לכלום.
    """
    if any(_CREDITS_CELL_RE.match(w[2]) and w[0] < anchor.name_from for w in line.words):
        return None
    got = _name_words(line, anchor)
    return got or None


def _bind_names(lines: list[Line]) -> tuple[dict[int, _Anchor], dict[int, str]]:
    """מחבר לכל שורת קורס את שמה המלא, לפי עמודות.

    שורת קורס בשנתון נשברת לעיתים קרובות לשתיים ואף לשלוש שורות ויזואליות.
    ‏**כל** אחת מהן נושאת גם את עמודת "קורסי קדם" של אותו גובה, ושם יושבים
    מספרי קורס אחרים — ולכן שורת המשך נתרמת רק דרך עמודת השם של העוגן.

    ‏**הכיוון נקבע לפי העוגן, לא לפי המרחק.** שורה שיושבת בין שני קורסים
    קרובה לפעמים דווקא לזה שאינו שלה: ב-industry.pdf השורה "ההון" — הסיפא
    של "ניתוח דו"חות כספיים ושוק ההון" — רחוקה ‏14.6 נקודות מהקורס שלה
    ו-11.9 מהבא אחריו. לכן:

    * עוגן ש**אין** בשורתו אף מילה בעמודת השם לוקח קודם את השורה שמעליו:
      שם הקורס הודפס מעל שורת המספרים, וזו האפשרות היחידה שיש לו.
    * אחר כך כל עוגן אוסף כלפי מטה, עד לעוגן הבא או עד לשורה שכבר נתפסה.
    """
    anchors: dict[int, _Anchor] = {}
    for index, line in enumerate(lines):
        found = _anchor_at(line)
        if found is not None:
            anchors[index] = found._replace(index=index)

    pieces: dict[int, list[tuple[float, list[str]]]] = {}
    for index in anchors:
        own = _name_words(lines[index], anchors[index])
        pieces[index] = [(lines[index].y, own)] if own else []
    taken: set[int] = set()

    def reachable(anchor_index: int, j: int) -> bool:
        if j < 0 or j >= len(lines) or j in anchors or j in taken:
            return False
        if lines[j].page != lines[anchor_index].page:
            return False
        if abs(lines[anchor_index].y - lines[j].y) > _MAX_CONTINUATION_GAP:
            return False
        return _may_continue(lines[j])

    # ── שלב 1: עוגן בלי שם משלו תופס את השורה שמעליו ──
    for index in sorted(anchors):
        if pieces[index]:
            continue
        for step in range(1, _MAX_PREFIX_LINES + 1):
            j = index - step
            if not reachable(index, j):
                break
            got = _claims(lines[j], anchors[index])
            if got is None:
                break
            pieces[index].insert(0, (lines[j].y, got))
            taken.add(j)

    # ── שלב 2: כל עוגן אוסף כלפי מטה ──
    for index in sorted(anchors):
        for step in range(1, _MAX_CONTINUATION_LINES + 1):
            j = index + step
            if not reachable(index, j):
                break
            got = _claims(lines[j], anchors[index])
            if got is None:
                break
            pieces[index].append((lines[j].y, got))
            taken.add(j)

    # ‏**החיבור נעשה בתוך שורה בלבד.** המרווח בין המילה האחרונה של שורה
    # אחת לראשונה של הבאה אינו מרווח כלל — ‏x חוזר לתחילת העמודה — ולכן
    # חישוב שלו נתן "מרווח" שלילי וחיבר "באלמנטים" ל"סופיים".
    names = {
        index: _tidy(" ".join(_join_words(ws) for _y, ws in sorted(parts) if ws))
        for index, parts in pieces.items()
    }
    return anchors, names


def parse_chapter(pdf_path: str | Path) -> dict:
    """מפענח פרק שנתון אחד.

    Returns:
        ``{program, source, year, structure, clusters, tracks, warnings}``
        ``clusters``/``tracks`` הם ``{שם הקבוצה: [{code, name}]}``.
    """
    path = Path(pdf_path)
    lines = _document_lines(path)
    rows = [(line.page, line.text) for line in lines]
    warnings: list[str] = []

    anchors, names = _bind_names(lines)

    clusters: dict[str, list[dict]] = {}
    tracks: dict[str, list[dict]] = {}
    current: list[dict] | None = None
    seen_elective_zone = False

    for index, line in enumerate(lines):
        tidy = _tidy(line.text)
        squashed = _squash(line.text)

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
            continue

        if current is None or not seen_elective_zone or index not in anchors:
            continue

        code = anchors[index].code
        if not any(c["code"] == code for c in current):
            current.append({"code": code, "name": names.get(index, "")})

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


# ==========================================================================
# רשימות בחירה לפי התמחות — ``parse_electives``
# ==========================================================================
#
# ‏``parse_chapter`` מכיר רק כותרות "אשכול X" ו"מסלול X", ולכן (נמדד
# 2026-09-26 מול ``docs/PROGRAM_FINDINGS.md``): באזרחית יצאו 4 "מסלולים"
# במקום 2 וקבוצות 1 ו-2 התמזגו; במכונות רשימת ההעשרה המשותפת נרשמה תחת
# תעשייה 4.0 בלבד; בתעשייה וניהול שתי ההדפסות התמזגו; וחשמל יצא ``flat``.
#
# ‏``clusters``/``tracks`` נשארים כפי שהם — הממשק הנוכחי ובדיקות נעולות
# קוראים אותם. המודל הזה נכתב **לצידם**, בשדות ``specializations`` ו-
# ``elective_lists``:
#
# * ‏``elective_lists`` — ‏``{מזהה: {title, page, courses, ...}}``. רשימה
#   שכמה התמחויות חולקות נרשמת **פעם אחת**.
# * ‏``specializations`` — ‏``{שם התמחות: [מזהי רשימות]}``. ריק בתוכנית
#   בלי התמחויות, ואז כל הרשימות חלות על כולם.
#
# החילוץ מזהה גם שורות שהמחלץ הישן מפספס. כל אחת נמדדה על שורה אמיתית:
#
# * ‏נ"ז שלם ("2", "4") או בשתי ספרות אחרי הנקודה ("0.25") — ‏51600,
#   ‏51916, שורות ‏251xxx, סמינרים ‏31060–31062.
# * מספר קורס שמודפס בשורה ויזואלית אחרת מהעמודות המספריות, או בלי נ"ז
#   כלל — ‏22777, ‏22748, ‏21461, ‏31905–31907.
# * סימן הערת שוליים בכתב עילי (‏"1", "6", "7", "9") — נראה כמו תא
#   מספרי והזיז את גבול עמודת השם. מזוהה לפי גובה המילה.

#: נ"ז בתא משלו, רחב מ-``_CREDITS_CELL_RE``: גם ‏"0.25".
_WIDE_CREDITS_RE = re.compile(r"^\d{1,2}\.\d{1,2}$")
#: נ"ז שלם — נחשב נ"ז רק כתא האחרון בגוש של ארבעה תאים לפחות.
_INT_CELL_RE = re.compile(r"^\d{1,2}$")
_CODE_RE = re.compile(r"^\d{5,6}$")

#: מילה נמוכה מזה ביחס לחציון השורה היא כתב עילי. נמדד: ‏7.0 מול ‏11.0
#: בחשמל, ‏11.2 מול ‏13.3 בתוכנה.
_SUPERSCRIPT_RATIO = 0.9
#: תא מספרי שמתחיל ימינה מזה, ביחס לקצה כותרת "ה" של הטבלה, הוא חלק מהשם.
_FIRST_CELL_SLACK = 12.0
#: מספר קורס שמתחיל שמאלה מזה נמצא בעמודת "קורסי קדם", לא בעמודת מספר הקורס.
#: נמדד על כל הפרקים: עמודת הקדם מסתיימת לפני ‏320, עמודת מספר הקורס מתחילה אחרי ‏400.
_CODE_COLUMN_MIN_X = 380.0
#: כמה רחוק ב-x מספר קורס יכול להיות מעמודת מספרי הקורס של העמוד.
_CODE_COLUMN_TOLERANCE = 4.0
#: המרחק האנכי המרבי בין שורת קורס "תלושה" לשורות שנושאות את שמה.
_BAND = 16.0

#: תחום/חומרה/תוכנה בסוף שם קורס ליבה בחשמל: "מיקרו-מעבדים (חומרה(".
_AREA_RE = re.compile(r"\s*[()]\s*(חומרה|תוכנה)\s*[()]\s*$")

#: הדפסה שלמה של התוכנית להתמחות אחת (תעשייה וניהול): "התמחות במדעי הנתונים :".
_SPEC_PRINTING_RE = re.compile(r"^התמחות\s+ב(.{3,60}?)\s*:$")
_GROUP_RE = re.compile(r"^קבוצה\s*(\d+)")
_DOMAIN_RE = re.compile(r"^תחום\s+(.{2,60})$")

#: כותרות שסוגרות רשימה פתוחה (בנוסף לסמסטר ולפתיחת פרק).
_LIST_END_PREFIXES = (
    "קורסיחובה",
    "הערות",
    "סטודנטיםמצטיינים",
    "חלופותלהתנסות",
)

#: מאגרי חשמל: כותרת -> ‏(שם הרשימה, pool).
_POOLS = (
    ("קורסיליבהבהתמחות", "קורסי ליבה בהתמחות", "core"),
    ("קורסיםמשותפיםלמספרהתמחויות", "קורסים משותפים למספר התמחויות", "shared"),
    ("קורסיםלהתמחותזובלבד", "קורסים להתמחות זו בלבד", "only"),
    ("קורסיםבהתמחותזובלבד", "קורסים להתמחות זו בלבד", "only"),
)
#: רשימות שחלות על כל ההתמחויות: כותרת -> שם הרשימה.
_FOR_ALL = (
    ("קורסיהעשרהלכללההתמחויות", "קורסי העשרה לכלל ההתמחויות"),
    ("מקצועותבחירהנוספים", "מקצועות בחירה נוספים"),
    ("רצועהרב", "רצועה רב-תחומית"),
)
_CENTER_PREFIX = "במסגרתקורסיהבחירהניתןגםלקחתקורסיםמהמרכז"
_CENTER_TITLE = "המרכז לחינוך הנדסי וליזמות"


def _strip_superscripts(line: Line) -> tuple[Line, list[str]]:
    """השורה בלי סימני הערות שוליים, ורשימת הסימנים שהוסרו."""
    if not line.heights or len(line.heights) != len(line.words):
        return line, []
    body = sorted(line.heights)[len(line.heights) // 2]
    keep: list[tuple[Word, float]] = []
    marks: list[str] = []
    for index, (word, height) in enumerate(zip(line.words, line.heights)):
        small = height < body * _SUPERSCRIPT_RATIO and re.fullmatch(r"\d{1,2}|\*", word[2])
        # ספרה שדבוקה למילה שלפניה ("משלכם1") היא סימן הערה גם כשגובהה רגיל.
        # **אחרי מילה של שלוש אותיות לפחות**: ‏"א1" ו-"ב2" במכונות (‏22971–
        # ‏22977) הם חלק מהשם, והם באותו גובה בדיוק.
        before = line.words[index - 1] if index else None
        glued = (
            before is not None
            and re.fullmatch(r"\d{1,2}", word[2])
            and len(re.sub(r"[\d.\-–—]", "", before[2])) >= 3
            and max(before[0], word[0]) - min(before[1], word[1]) < _GLUE_GAP
        )
        if small or glued:
            marks.append(word[2])
        else:
            keep.append((word, height))
    if not marks:
        return line, []
    words = tuple(w for w, _h in keep)
    return (
        line._replace(
            words=words,
            heights=tuple(h for _w, h in keep),
            text="  ".join(w[2] for w in words),
        ),
        marks,
    )


def _first_cell_edge(line: Line) -> float | None:
    """הקצה השמאלי-ימני של כותרת "ה" — העמודה המספרית הראשונה. ``None`` = לא כותרת.

    תא מספרי שמתחיל ימינה ממנה הוא חלק מהשם: בלי זה ‏"1" שבסוף "סמינר
    מחלקתי 1" (‏31060) נספר כתא ונחתך מהשם. **ספירת עמודות אינה עובדת
    כאן** — הכותרת של מערכות מידע מדפיסה "ה ת מ נ"ז" מעל חמישה תאים.
    """
    texts = [w[2] for w in line.words]
    if "ה" not in texts or "ת" not in texts:
        return None
    if not {"קדם", "הקורס", "קורס"} & set(texts):
        return None
    return next(w[1] for w in line.words if w[2] == "ה")


def _wide_block(words: tuple[Word, ...], first_cell: float | None) -> tuple[float, float | None] | None:
    """‏(קצה ימני של גוש העמודות, נ"ז) — כמו ``_numeric_block_edge``, ברוחב.

    ‏``first_cell`` הוא קצה כותרת "ה" באותו עמוד (‏``_first_cell_edge``);
    תא שמתחיל ימינה ממנו אינו תא.
    """
    runs: list[list[Word]] = []
    open_run = False
    for word in words:
        beyond = first_cell is not None and word[0] > first_cell + _FIRST_CELL_SLACK
        if _COLUMN_CELL_RE.match(word[2]) and not beyond:
            if not open_run:
                runs.append([])
                open_run = True
            runs[-1].append(word)
        else:
            open_run = False
    blocks = [
        r
        for r in runs
        if any(_WIDE_CREDITS_RE.match(w[2]) for w in r)
        or (len(r) >= 4 and _INT_CELL_RE.match(r[-1][2]))
    ]
    if not blocks:
        return None
    block = blocks[-1]
    last = block[-1][2]
    credits = float(last) if (_WIDE_CREDITS_RE.match(last) or _INT_CELL_RE.match(last)) else None
    return block[0][1], credits


def _bind_rows(lines: list[Line]) -> dict[int, dict]:
    """כל שורות הקורס במסמך, ברוחב המלא. ‏``{אינדקס שורה: {code, name, credits, marks}}``.

    שלושה שלבים:

    1. עוגנים רגילים, ב-``_wide_block``.
    2. עוגנים "תלושים": מספר קורס בעמודת מספרי הקורס של העמוד, בלי עמודות
       מספריות בשורתו. הם נכנסים ל-``anchors`` **לפני** איסוף השמות, כך
       ששורת ‏22748 כבר אינה נבלעת כהמשך של ‏22874 שמעליה.
    3. שם לעוגן תלוש: עמודת השם של כל שורה פנויה ברצועה של ``_BAND``
       נקודות, שהעוגן הקרוב אליה ביותר הוא הוא.
    """
    marks: dict[int, list[str]] = {}
    clean: list[Line] = []
    for index, line in enumerate(lines):
        stripped, found = _strip_superscripts(line)
        clean.append(stripped)
        if found:
            marks[index] = found

    # קצה "ה" של הכותרת האחרונה. טבלה שנמשכת לעמוד הבא אינה חוזרת תמיד על
    # הכותרת (‏mecho.pdf עמוד 14), ולכן הכותרת נשארת בתוקף עד הבאה אחריה.
    # ‏``same_page`` — רק כותרת מאותו עמוד. היא לבדה מזיזה את תחילת עמודת
    # השם: כותרת מעמוד 10 של מערכות מידע קטעה את "מכונה" מ-62002 בעמוד 11.
    edge_now: float | None = None
    edge_page = 0
    at_line: list[float | None] = []
    same_page: list[float | None] = []
    for line in clean:
        edge = _first_cell_edge(line)
        if edge is not None:
            edge_now, edge_page = edge, line.page
        at_line.append(edge_now)
        same_page.append(edge_now if edge_page == line.page else None)

    anchors: dict[int, _Anchor] = {}
    credits: dict[int, float | None] = {}
    for index, line in enumerate(clean):
        columns = at_line[index]
        if _first_cell_edge(line) is not None:
            continue
        if not line.words or not _CODE_RE.match(line.words[0][2]):
            continue
        x0 = line.words[0][0]
        got = _wide_block(tuple(w for w in line.words[1:] if w[1] < x0), columns)
        if got is not None:
            # שורה שתא "ה" שלה מודפס בשורה ויזואלית אחרת (‏51025 בהדפסת תכן
            # ותפעול) מתחילה שמאלה מעמודת "ה" — ואז הגבול הוא הכותרת.
            header = same_page[index]
            start = got[0] if header is None else max(got[0], header + 2.0)
            anchors[index] = _Anchor(index, line.words[0][2], start, x0)
            credits[index] = got[1]

    # ── עמודת מספרי הקורס, ועמודת השם, לכל עמוד ──
    code_x: dict[int, list[float]] = {}
    name_from: dict[int, list[float]] = {}
    for index, anchor in anchors.items():
        code_x.setdefault(clean[index].page, []).append(anchor.name_to)
        name_from.setdefault(clean[index].page, []).append(anchor.name_from)

    loose: set[int] = set()
    for index, line in enumerate(clean):
        if index in anchors or not line.words or not _CODE_RE.match(line.words[0][2]):
            continue
        x0 = line.words[0][0]
        if not any(abs(x0 - x) <= _CODE_COLUMN_TOLERANCE for x in code_x.get(line.page, [])):
            continue
        edges = sorted(name_from[line.page])
        start = edges[len(edges) // 2]
        if same_page[index] is not None:
            # תא "ה" של השורה עצמה יכול לשבת בשורה ויזואלית אחרת.
            start = max(start, same_page[index] + 2.0)
        anchors[index] = _Anchor(index, line.words[0][2], start, x0)
        loose.add(index)

    names = _collect_names(clean, anchors, skip=loose)

    # ── שמות ונ"ז לעוגנים התלושים ──
    taken = set(anchors)
    for index in anchors:
        taken.update(names.get(("lines", index), ()))
    by_page: dict[int, list[int]] = {}
    for index in anchors:
        by_page.setdefault(clean[index].page, []).append(index)
    parts: dict[int, list[tuple[float, list[Word]]]] = {
        i: [(clean[i].y, _name_words(clean[i], anchors[i]))] for i in loose
    }
    for j, line in enumerate(clean):
        if j in taken or not _may_continue(line):
            continue
        near = [
            (abs(clean[i].y - line.y), i)
            for i in by_page.get(line.page, [])
            if abs(clean[i].y - line.y) <= _BAND
        ]
        if not near:
            continue
        _dist, owner = min(near)
        if owner not in loose:
            continue
        got = _name_words(line, anchors[owner])
        if got:
            parts[owner].append((line.y, got))
        if credits.get(owner) is None:
            block = _wide_block(
                tuple(w for w in line.words if w[1] < anchors[owner].name_from), at_line[j]
            )
            if block is not None:
                credits[owner] = block[1]

    # ── שורת שם שהמעבר הרגיל לא הגיע אליה, מעל או מתחת לעוגן רגיל:
    #    ‏251512 ("מבוא לניהול" מעל השורה), ‏51030 בהדפסת תכן ותפעול ("שירות"
    #    מתחת, אחרי שורת קדם ריקה בעמודת השם). רק שורה שאף עוגן לא לקח, עד
    #    ‏12 נקודות, ורק כשהמילה הראשונה שלה פותחת באותו קצה כמו השם —
    #    כותרת מתחילה בשוליים ואינה עוברת את זה. ──
    extra_above: dict[int, list[Word]] = {}
    extra_below: dict[int, list[Word]] = {}
    for index, anchor in anchors.items():
        if index in loose:
            continue
        own = _name_words(clean[index], anchor)
        if not own:
            continue
        for direction, found in ((-1, extra_above), (1, extra_below)):
            j = index + direction
            while 0 <= j < len(clean) and j not in anchors:
                other = clean[j]
                if other.page != clean[index].page or abs(clean[index].y - other.y) > 12.0:
                    break
                got = _name_words(other, anchor)
                if not got:
                    j += direction
                    continue
                if (
                    j not in taken
                    and _may_continue(other)
                    and other.words[0] == got[0]
                    and abs(got[0][1] - own[0][1]) <= 3.0
                    and not any(_CREDITS_CELL_RE.match(w[2]) for w in other.words)
                ):
                    found[index] = got
                    taken.add(j)
                break

    # ── מילה לטינית על קו בסיס משלה, בתוך שם עברי (‏51154: "מבוא ל-ERP") ──
    latin_inside: dict[int, list[Word]] = {}
    for j, line in enumerate(clean):
        if j in taken or j in anchors or not line.words:
            continue
        for index in (j - 1, j + 1):
            if index not in anchors or abs(clean[index].y - line.y) > 6.0:
                continue
            got = _name_words(line, anchors[index])
            if not got or not all(
                _LATIN_RE.search(w[2]) and not _HEBREW_RE.search(w[2]) for w in got
            ):
                continue
            own = _name_words(clean[index], anchors[index])
            lo, hi = min(w[0] for w in got), max(w[1] for w in got)
            gaps = [
                (a, b) for a, b in zip(own, own[1:]) if b[1] <= lo + 1 and hi <= a[0] + 1
            ]
            if gaps:
                latin_inside[index] = got
                taken.add(j)
                break

    rows: dict[int, dict] = {}
    for index, anchor in anchors.items():
        if index in latin_inside:
            own = _name_words(clean[index], anchor) + latin_inside[index]
            names[index] = _join_words(sorted(own, key=lambda w: -w[0]))
            # שם שנמשך לשורות נוספות — לא קרה בשורות שנמדדו, ואז פשוט נופלים לשם הרגיל.
        if index in extra_above:
            names[index] = _tidy(_join_words(extra_above[index]) + " " + names[index])
        if index in extra_below:
            names[index] = _tidy(names[index] + " " + _join_words(extra_below[index]))
        if index in loose:
            name = _tidy(" ".join(_join_words(ws) for _y, ws in sorted(parts[index]) if ws))
        else:
            name = names[index]
        rows[index] = {
            "code": anchor.code,
            "name": name,
            "credits": credits.get(index),
            "marks": marks.get(index, []),
            "loose": index in loose,
            "bounds": (anchor.name_from, anchor.name_to),
        }
    return rows


def _collect_names(
    lines: list[Line], anchors: dict[int, _Anchor], skip: set[int] = frozenset()  # type: ignore[assignment]
) -> dict:
    """שני שלבי האיסוף של ``_bind_names`` על עוגנים נתונים.

    עוגן שב-``skip`` אינו אוסף — אבל הוא עדיין חוסם: שורה שלו לא תיבלע
    בשם של העוגן שמעליו. מחזיר ``{אינדקס: שם}`` וגם, תחת
    ``("lines", אינדקס)``, את השורות שכל עוגן לקח.
    """
    pieces: dict[int, list[tuple[float, list[Word]]]] = {}
    for index in anchors:
        if index in skip:
            continue
        own = _name_words(lines[index], anchors[index])
        pieces[index] = [(lines[index].y, own)] if own else []
    taken: dict[int, int] = {}

    def reachable(anchor_index: int, j: int) -> bool:
        if j < 0 or j >= len(lines) or j in anchors or j in taken:
            return False
        if lines[j].page != lines[anchor_index].page:
            return False
        if abs(lines[anchor_index].y - lines[j].y) > _MAX_CONTINUATION_GAP:
            return False
        return _may_continue(lines[j])

    for index in sorted(pieces):
        if pieces[index]:
            continue
        for step in range(1, _MAX_PREFIX_LINES + 1):
            j = index - step
            if not reachable(index, j):
                break
            got = _claims(lines[j], anchors[index])
            if got is None:
                break
            pieces[index].insert(0, (lines[j].y, got))
            taken[j] = index

    for index in sorted(pieces):
        for step in range(1, _MAX_CONTINUATION_LINES + 1):
            j = index + step
            if not reachable(index, j):
                break
            got = _claims(lines[j], anchors[index])
            if got is None:
                break
            pieces[index].append((lines[j].y, got))
            taken[j] = index

    out: dict = {
        index: _tidy(" ".join(_join_words(ws) for _y, ws in sorted(parts) if ws))
        for index, parts in pieces.items()
    }
    for j, index in taken.items():
        out.setdefault(("lines", index), []).append(j)
    return out


def _balance_parens(name: str) -> str:
    """סוגריים שהשנתון הדפיס בבבואה: ‏"(EMC(" -> "(EMC)", ‏"זימקס )(" -> "(זימקס)"."""
    name = re.sub(r"(\S+)\s*\)\(\s*$", r"(\1)", name)
    if name.count("(") == 2 and ")" not in name:
        cut = name.rfind("(")
        name = name[:cut] + ")" + name[cut + 1 :]
    elif name.count(")") == 2 and "(" not in name:
        cut = name.find(")")
        name = name[:cut] + "(" + name[cut + 1 :]
    name = re.sub(r"\(\s+", "(", name)
    return re.sub(r"\s+\)", ")", name)


def _course_entry(row: dict) -> dict:
    """רשומת קורס לרשימת בחירה: ‏code, name, ולפי הצורך credits, area, footnote."""
    name = row["name"]
    entry: dict[str, Any] = {"code": row["code"]}
    area = _AREA_RE.search(name)
    if area:
        entry["area"] = area.group(1)
        name = name[: area.start()]
    footnote = list(row["marks"])
    if name.rstrip().endswith("*"):
        footnote.append("*")
        name = name.rstrip()[:-1]
    entry["name"] = _tidy(_balance_parens(_tidy(name)))
    if row["credits"] is not None:
        entry["credits"] = row["credits"]
    if footnote:
        entry["footnote"] = " ".join(dict.fromkeys(footnote))
    if area:  # סדר מפתחות קבוע: code, name, credits, area, footnote
        entry["area"] = entry.pop("area")
    return entry


#: נ"ז כטווח, בתא משלו: ‏"1-2".
_RANGE_CELL_RE = re.compile(r"^\d+(?:\.\d+)?-\d+(?:\.\d+)?$")


def _codeless_note(lines: list[Line], index: int, rows: dict[int, dict]) -> str:
    """הערה לשורה בלי מספר קורס: השם מעמודת השם, והטווח של הנ"ז.

    עמודת השם נלקחת משורת הקורס הקרובה באותו עמוד; השם מודפס לעיתים מעל
    ומתחת לשורת הטווח, ולכן נאספות גם השורות שבטווח ‏8 נקודות.
    """
    line = lines[index]
    near = [
        (abs(lines[i].y - line.y), row["bounds"])
        for i, row in rows.items()
        if lines[i].page == line.page
    ]
    if not near:
        return ""
    name_from, name_to = min(near)[1]
    words: list[tuple[float, list[Word]]] = []
    for j in range(max(0, index - 3), min(len(lines), index + 4)):
        other = lines[j]
        if j in rows or other.page != line.page or abs(other.y - line.y) > 8.0:
            continue
        clean, _marks = _strip_superscripts(other)
        got = [w for w in clean.words if name_from < w[0] < name_to]
        if got:
            words.append((other.y, got))
    name = _tidy(" ".join(_join_words(ws) for _y, ws in sorted(words)))
    span = next(w[2] for w in line.words if _RANGE_CELL_RE.match(w[2]))
    return f'{name} — {span} נ"ז, מודפס בלי מספר קורס.' if name else ""


def _canonical_spec(printed: str, known: tuple[str, ...], declared: tuple[str, ...] = ()) -> str:
    """שם ההתמחות.

    1. כפי שקובץ התוכנית של המסלול קורא לה (‏``known``), אם יש התאמה אחת.
    2. אחרת הכותרת כפי שהודפסה — **אלא** אם היא שגיאת כתיב של שם שהפרק
       עצמו מצהיר עליו (‏``declared``, ‏``_declared_specializations``):
       הכותרת בחשמל עמוד 11 היא "עיבוד אות ותקשורת", ועמוד 2 וסעיף ב
       מדפיסים "עיבוד אותות ותקשורת". הבדל של רווח או מקף בלבד אינו שגיאה
       — "התקנים ואלקטרואופטיקה" נשארת כפי שהודפסה.
    """
    printed = _tidy(_balance_parens(_tidy(printed))).strip(" :-–")
    squashed = _squash(printed)
    hits = [name for name in known if _squash(name) and _squash(name) in squashed]
    if len(hits) == 1:
        return hits[0]

    def bare(text: str) -> str:
        return re.sub(r"[-–()]", "", _squash(text))

    if any(bare(name) == bare(printed) for name in declared):
        return printed
    close = [
        name for name in declared
        if difflib.SequenceMatcher(None, bare(name), bare(printed)).ratio() >= 0.9
    ]
    return close[0] if len(close) == 1 else printed


def _declared_specializations(lines: list[Line]) -> tuple[str, ...]:
    """שמות ההתמחויות מהרשימה שבפתיחת הפרק: שורת "…התמחויות:" ואחריה תבליטים."""
    for index, line in enumerate(lines):
        squashed = _squash(line.text)
        if not (squashed.endswith(":") and "התמחויות" in squashed):
            continue
        names: list[str] = []
        for following in lines[index + 1 : index + 8]:
            text = _tidy(following.text)
            if not text.startswith("•"):
                break
            name = _tidy(_balance_parens(text.lstrip("• ")))
            names.append(re.sub(r"\s*-\s*", "-", name))
        if names:
            return tuple(names)
    return ()


def parse_electives(pdf_path: str | Path, track_names: tuple[str, ...] = ()) -> dict:
    """רשימות הבחירה של פרק שנתון, לפי התמחות.

    Args:
        track_names: שמות ההתמחויות כפי שקובץ התוכנית של המסלול קורא להן
            (‏``tracks``). כותרת שמכילה בדיוק אחד מהם מקבלת את השם הזה —
            ‏"מסלול הנדסת מבנים" היא "מבנים".

    Returns:
        ``{specializations, elective_lists, warnings}``. ראו את ההסבר מעל
        ``_WIDE_CREDITS_RE``.
    """
    lines = _document_lines(Path(pdf_path))
    rows = _bind_rows(lines)
    declared = _declared_specializations(lines)
    warnings: list[str] = []

    specs: list[str] = []
    lists: dict[tuple[str | None, str], dict] = {}
    spec: str | None = None
    current: dict | None = None
    zone = False
    pending_title = "קורסי בחירה"
    frags: list[tuple[int, float, str]] = []
    unbound: list[str] = []

    def open_list(owner: str | None, title: str, page: int, **extra: Any) -> dict:
        key = (owner, title)
        if key in lists:
            # אותה כותרת פעם שנייה: המשך, או הדפסה חוזרת (תעשייה מדפיסה את
            # "מדע וטכנולוגיה" בשתי ההדפסות). ההדפסה החוזרת נבדקת בסוף.
            again = dict(lists[key], courses=[], again=True)
            lists[(owner, title, len(lists))] = again  # type: ignore[index]
            return again
        lists[key] = {"owner": owner, "title": title, "page": page, "courses": [], **extra}
        return lists[key]

    def use_spec(name: str) -> str:
        if name not in specs:
            specs.append(name)
        return name

    previous = ""
    #: השורה האחרונה שאינה שורת קורס ואינה כותרת טבלה. בחשמל שם ההתמחות
    #: מודפס מעל הטבלה, ו"קורסי ליבה בהתמחות" היא שורה בתוכה.
    previous_heading = ""
    cluster_edge: float | None = None
    for index, line in enumerate(lines):
        tidy = _tidy(line.text)
        squashed = _squash(line.text)
        texts = [w[2] for w in line.words]

        # עמודת "אשכול" בטבלת המרכז לחינוך הנדסי: כל קורס משויך בה לאשכול.
        if "אשכול" in texts and "ה" in texts and "ת" in texts:
            cluster_edge = next(w[1] for w in line.words if w[2] == "אשכול")
            previous = tidy
            continue
        if current is not None and current.get("center") and cluster_edge is not None:
            frags.extend(
                (line.page, line.y, w)
                for w in line.words
                if w[1] <= cluster_edge + 6 and not _CODE_RE.match(w[2])
            )

        if (
            index not in rows
            and current is not None
            and zone
            and line.words
            and _CODE_RE.match(line.words[0][2])
            and line.words[0][0] > _CODE_COLUMN_MIN_X
        ):
            unbound.append(f"{line.words[0][2]} (עמוד {line.page})")

        # שורה בלי מספר קורס, עם נ"ז כטווח ("1-2"): ‏"פרויקט מיוחד" בחשמל.
        # אין לה קוד, ולכן אינה קורס ברשימה — היא נרשמת כהערה של הרשימה.
        if current is not None and zone and index not in rows and any(
            _RANGE_CELL_RE.match(w[2]) for w in line.words
        ):
            note = _codeless_note(lines, index, rows)
            if note:
                current.setdefault("notes", []).append(note)

        if index in rows:
            if current is not None and zone:
                row = rows[index]
                if not any(c["code"] == row["code"] for c in current["courses"]):
                    current["courses"].append(dict(_course_entry(row), _y=(line.page, line.y)))
            previous = tidy
            continue

        # ‏"מחשבים (חומרה ותוכנה) – המשך": אותה התמחות ואותו מאגר, בעמוד הבא.
        if "–המשך" in squashed or "-המשך" in squashed:
            previous = tidy
            continue

        printing = _SPEC_PRINTING_RE.match(tidy)
        if printing:
            spec = use_spec(_canonical_spec(printing.group(1), track_names, declared))
            current, zone = None, False
        elif re.match(r"^סמסטר\s*\d", tidy) or re.match(r"^סמסטר\d", squashed) or _SECTION_END_RE.match(tidy):
            current, zone = None, False
        elif squashed.startswith(_LIST_END_PREFIXES) or "קורסיםמקבילים" in squashed[:20]:
            current = None
            if squashed.startswith("קורסיחובה"):
                zone = False
        elif squashed.startswith("קורסיבחירהבהתמחות"):
            zone, current, pending_title = True, None, "קורסי בחירה בהתמחות"
        elif squashed in ("קורסיבחירה",) or squashed.startswith("קורסיבחירהלפיאשכולות"):
            zone, current = True, None
        elif any(squashed.startswith(p) for p, _t, _k in _POOLS):
            _p, title, pool = next(x for x in _POOLS if squashed.startswith(x[0]))
            if pool == "core":
                spec = use_spec(_canonical_spec(previous_heading, track_names, declared))
            zone = True
            current = open_list(spec, title, line.page, pool=pool)
        elif any(squashed.startswith(p) for p, _t in _FOR_ALL):
            title = next(t for p, t in _FOR_ALL if squashed.startswith(p))
            zone = True
            current = open_list(None, title, line.page, for_all=True)
        elif squashed.startswith(_CENTER_PREFIX):
            zone = True
            current = open_list(spec, _CENTER_TITLE, line.page, center=True)
        elif _CLUSTER_RE.match(tidy):
            raw = _CLUSTER_RE.match(tidy).group(1)
            title = _tidy(re.split(r"[(*]", raw)[0]).strip(" :-–")
            zone = True
            if "עבורשתיההתמחויות" in squashed:
                current = open_list(None, title, line.page, for_all=True)
            else:
                current = open_list(spec, title, line.page)
        elif _GROUP_RE.match(tidy) and zone:
            title = f"קבוצה {_GROUP_RE.match(tidy).group(1)}"
            current = open_list(spec, title, line.page)
        elif _DOMAIN_RE.match(tidy) and zone:
            current = open_list(None, tidy, line.page)
        elif _TRACK_RE.match(tidy):
            if "עדצבירה" in squashed:
                zone = True
                pending_title = "קורסי בחירה"
            if zone:
                raw = re.split(r"[(]|-\s*\(|-\s*עד\s+צבירה|–", _TRACK_RE.match(tidy).group(1))[0]
                spec = use_spec(_canonical_spec(raw, track_names, declared))
                current = open_list(spec, pending_title, line.page)
        previous = tidy
        if not (_first_cell_edge(line) is not None or _is_table_header(line)):
            previous_heading = tidy

    if unbound:
        # רשימה שידוע שחסרות בה שורות אינה נכתבת בכלל: חצי רשימה נראית
        # שלמה בממשק, ורשימה חסרה נראית חסרה.
        return {
            "specializations": {},
            "elective_lists": {},
            "warnings": [
                "שורות קורס ברשימות הבחירה לא זוהו, ולכן הרשימות לא נכתבו: "
                + ", ".join(unbound)
            ],
        }
    return _assemble(specs, lists, frags, warnings)


def _assemble(
    specs: list[str],
    lists: dict,
    frags: list[tuple[int, float, Word]],
    warnings: list[str],
) -> dict:
    """מאחד הדפסות חוזרות, רושם רשימה משותפת פעם אחת, ומשייך לאשכולות."""
    # ── הדפסה חוזרת של אותה רשימה (אותו בעלים, אותה כותרת) ──
    merged: dict[tuple[str | None, str], dict] = {}
    for key, entry in lists.items():
        base = (entry["owner"], entry["title"])
        if not entry.get("again"):
            merged[base] = entry
            continue
        first = merged[base]
        codes = [c["code"] for c in first["courses"]]
        more = [c["code"] for c in entry["courses"]]
        if not codes or not more:
            first["courses"].extend(c for c in entry["courses"] if c["code"] not in codes)
        elif codes != more:
            warnings.append(
                f"'{entry['title']}' מודפסת פעמיים ברשימות שונות; נשמרה ההדפסה הראשונה "
                f"(עמוד {first['page']}). בשנייה בלבד: {sorted(set(more) - set(codes))}; "
                f"בראשונה בלבד: {sorted(set(codes) - set(more))}."
            )
    merged = {k: v for k, v in merged.items() if v["courses"]}

    # ── שיוך שורות המרכז לחינוך הנדסי לאשכול, לפי עמודת "אשכול" ──
    for (owner, _title), entry in merged.items():
        if not entry.get("center"):
            continue
        clusters = [
            e["title"] for (o, _t), e in merged.items()
            if (o == owner or e.get("for_all")) and not e.get("center") and not e.get("pool")
        ]
        at: dict[str, list[tuple[float, Word]]] = {}
        for course in entry["courses"]:
            at[course["code"]] = []
        for page, y, word in frags:
            near = [
                (abs(y - c["_y"][1]), c["code"])
                for c in entry["courses"]
                if c["_y"][0] == page and abs(y - c["_y"][1]) <= _BAND
            ]
            if near:
                at[min(near)[1]].append((y, word))
        for course in entry["courses"]:
            parts = sorted(at[course["code"]], key=lambda p: (p[0], -p[1][0]))
            text = _squash(" ".join(w[2] for _y, w in parts))
            hits = [t for t in clusters if text and (_squash(t).startswith(text) or text.startswith(_squash(t)))]
            if len(hits) == 1:
                course["cluster"] = hits[0]
            else:
                warnings.append(f"{course['code']}: עמודת האשכול לא זוהתה ('{text}').")

    # ── רשימה זהה בכמה התמחויות נרשמת פעם אחת ──
    def signature(entry: dict) -> tuple:
        return (entry["title"], tuple(c["code"] for c in entry["courses"]))

    owners_of: dict[tuple, list[str | None]] = {}
    for (owner, _t), entry in merged.items():
        owners_of.setdefault(signature(entry), []).append(owner)

    out_lists: dict[str, dict] = {}
    ids: dict[tuple[str | None, str], str] = {}
    for (owner, title), entry in merged.items():
        shared = owner is None or len(owners_of[signature(entry)]) > 1
        list_id = title if shared else f"{owner} · {title}"
        ids[(owner, title)] = list_id
        if list_id in out_lists:
            continue
        body: dict[str, Any] = {"title": title, "page": entry["page"]}
        if entry.get("pool"):
            body["pool"] = entry["pool"]
        if owner is None and entry.get("for_all"):
            body["for_all_specializations"] = True
        body["courses"] = entry["courses"]
        if entry.get("notes"):
            body["notes"] = entry["notes"]
        out_lists[list_id] = body

    # שם אשכול -> מזהה הרשימה שלו באותה התמחות.
    for (owner, _t), entry in merged.items():
        if not entry.get("center"):
            continue
        for course in entry["courses"]:
            if "cluster" in course:
                course["cluster"] = ids.get((owner, course["cluster"]), ids.get((None, course["cluster"])))
    for body in out_lists.values():
        for course in body["courses"]:
            course.pop("_y", None)

    for_all = [ids[k] for k, e in merged.items() if k[0] is None and e.get("for_all")]
    specializations: dict[str, list[str]] = {}
    for spec in specs:
        own = [ids[k] for k in merged if k[0] == spec]
        refs = list(dict.fromkeys(own + for_all))
        if own:
            specializations[spec] = refs
    return {
        "specializations": specializations,
        "elective_lists": out_lists,
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
    track_names = _track_names_by_source()
    by_program: dict[str, dict] = {}
    for chapter in chapters.values():
        name = chapter.get("program") or ""
        if not name:
            continue
        electives = parse_electives(
            Path(folder) / chapter["source"], track_names.get(chapter["source"], ())
        )
        by_program[name] = {
            "program": name,
            "source": chapter["source"],
            "year": chapter["year"],
            "structure": chapter["structure"],
            "clusters": chapter["clusters"],
            "tracks": chapter["tracks"],
            "warnings": chapter["warnings"],
            "specializations": electives["specializations"],
            "elective_lists": electives["elective_lists"],
            "elective_list_warnings": electives["warnings"],
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


def _track_names_by_source(
    folder: str | Path = Path(__file__).resolve().parent.parent / "data" / "curricula",
) -> dict[str, tuple[str, ...]]:
    """‏``{קובץ PDF: שמות ההתמחויות}`` מקובצי התוכנית של המסלולים (‏``tracks``)."""
    out: dict[str, tuple[str, ...]] = {}
    for path in sorted(Path(folder).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tracks = data.get("tracks") if isinstance(data, dict) else None
        if data.get("source") and isinstance(tracks, list):
            out.setdefault(str(data["source"]), tuple(str(t) for t in tracks))
    return out


def load_curricula(path: str | Path = DEFAULT_CURRICULA_PATH) -> dict:
    """קורא את הקובץ. חסר או פגום -> ``{}``, בלי לזרוק."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    programs = data.get("programs") if isinstance(data, dict) else None
    if not isinstance(programs, dict):
        return {}
    try:  # אותו שלב נרמול שמים לכל קובצי התוכנית (``curriculum.load_curriculum``).
        from curriculum import normalize_names
    except ImportError:  # pragma: no cover
        from src.curriculum import normalize_names  # type: ignore[no-redef]
    return normalize_names(programs)
