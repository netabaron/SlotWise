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


def _document_lines(pdf_path: str | Path) -> list[Line]:
    """כל השורות של המסמך, עם הקואורדינטות שלהן.

    מקבצים מילים לפי ``y`` וממיינים כל שורה לפי ``x`` **יורד** — עברית.
    ‏``get_text()`` רגיל מערבב שורות בטבלאות עבריות ומחזיר עמודות הפוכות.
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
                ordered = sorted(bucket["w"], key=lambda w: -w[0])
                words = tuple((float(w[0]), float(w[2]), w[4]) for w in ordered)
                text = "  ".join(w[2] for w in words).strip()
                if text:
                    out.append(Line(index + 1, float(bucket["y"]), words, text))
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


def _name_words(line: Line, anchor: _Anchor) -> list[str]:
    """המילים של השורה שנופלות בתוך עמודת השם של הקורס."""
    return [w[2] for w in line.words if anchor.name_from < w[0] < anchor.name_to]


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

    names = {
        index: _tidy(" ".join(w for _y, ws in sorted(parts) for w in ws))
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
