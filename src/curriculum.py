"""
ניווט בתוכנית הלימודים (הידיעון) — Braude curriculum navigation.

המודול הזה יודע לקרוא את data/curriculum.json ולענות על ארבע שאלות:
    1. אילו קורסים יש בסמסטר מסוים?                 -> semester_courses
    2. איפה נמצא קוד קורס מסוים בכל התוכנית?         -> find_course
    3. אילו קורסים "צמודים" (חייבים להילקח יחד)?     -> tied_group
    4. האם עברתי את קורסי הקדם?                      -> check_prerequisites

מבנה קובץ הידיעון (למי שקורא את הקוד בפעם הראשונה):
    curr["semesters"]         -> {"1".."8": {"term": "א"/"ב", "year": 1..4,
                                             "total": {...}, "courses": [ ... ]}}
    curr["elective_clusters"] -> {"<שם אשכול>": [ ... ]}   # 6 אשכולות, 74 קורסי בחירה
    curr["replacement_courses"] -> [{"new": "61832", "old": "61760", ...}, ...]

כל "קורס" הוא dict עם השדות:
    code (str | None), name, he, te, ma, credits, prereq [list of codes]
    ולעיתים גם: cond, group, note, tied_with, replaced_by, pr

שימו לב לשתי מלכודות בנתונים:
    * יש רשומות שבהן "code": null — קורס כללי, ספורט, "קורס בחירה מאשכול".
      אסור לקרוס עליהן; פשוט מדלגים עליהן בכל חיפוש לפי קוד.
    * הקוד 251100 מופיע בשני אשכולות שונים. החיפוש מחזיר את המופע הראשון
      לפי סדר קבוע (סמסטרים 1..8 ואז האשכולות), כדי שהתוצאה תהיה יציבה.

Technical notes (English):
    * Every file open uses encoding="utf-8" — mandatory on Windows.
    * Pure functions, no globals, no I/O except load_curriculum().
    * The curriculum is tiny (122 entries), so plain linear scans are used
      instead of prebuilt indexes — clearer to read, fast enough.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# קבועים
# --------------------------------------------------------------------------

#: שורש הפרויקט — התיקייה שמעל src/. משמש לפתרון נתיבים יחסיים.
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

#: נתיב ברירת המחדל לקובץ הידיעון, יחסית לשורש הפרויקט.
DEFAULT_CURRICULUM_PATH: str = "data/curriculum.json"


class UnknownCourseError(ValueError):
    """קוד קורס שאינו קיים בתוכנית הלימודים — Raised for an unknown course code."""


class UnknownSemesterError(ValueError):
    """מספר סמסטר שאינו קיים בתוכנית הלימודים — Raised for an unknown semester key."""


# --------------------------------------------------------------------------
# עזרי־פנים (private helpers)
# --------------------------------------------------------------------------
def _norm_code(code: Any) -> str:
    """
    מנרמל קוד קורס למחרוזת נקייה.

    מקבל str / int / None ומחזיר מחרוזת. עבור None או ריק — מחזיר "".
    כך אפשר להשוות בבטחה גם רשומות שבהן "code": null.
    """
    if code is None:
        return ""
    return str(code).strip()


def _semester_keys_in_order(curr: dict) -> list[str]:
    """מפתחות הסמסטרים ממוינים מספרית ('1'..'8'), עם נפילה למיון טקסטואלי."""
    keys = list((curr.get("semesters") or {}).keys())

    def sort_key(k: str) -> tuple[int, str]:
        # סמסטרים הם "1".."8"; אם יופיע מפתח לא־מספרי הוא יידחף לסוף.
        return (int(k), "") if str(k).isdigit() else (10**6, str(k))

    return sorted(keys, key=sort_key)


def iter_all_courses(curr: dict) -> Iterator[tuple[str, dict]]:
    """
    עובר על *כל* רשומות הקורסים בתוכנית, בסדר קבוע וצפוי.

    Yields:
        (source, entry) — source הוא תווית מקור קריאה לאדם, למשל
        "semester:5" או "cluster:אלגוריתמים"; entry הוא ה-dict של הקורס.

    הסדר: סמסטר 1..8 (לפי סדר הקורסים בכל סמסטר), ואז אשכולות הבחירה
    לפי סדר הופעתם בקובץ. הסדר חשוב כי קוד אחד (251100) מופיע פעמיים,
    ואנחנו רוצים ש-find_course יחזיר תמיד את אותה רשומה.
    """
    for sem_key in _semester_keys_in_order(curr):
        body = (curr.get("semesters") or {}).get(sem_key) or {}
        for entry in body.get("courses") or []:
            yield f"semester:{sem_key}", entry

    for cluster_name, entries in (curr.get("elective_clusters") or {}).items():
        for entry in entries or []:
            yield f"cluster:{cluster_name}", entry


def _course_pairs_tied(curr: dict) -> dict[str, set[str]]:
    """
    בונה גרף "צמידות" בין קורסים מתוך שדות tied_with.

    הגרף דו־כיווני: אם 61756 מצהיר על 61757, גם ההפך נכון — גם אם
    הקובץ מצהיר רק לכיוון אחד. כך "קורסים צמודים" הם תמיד קבוצה שלמה.
    """
    graph: dict[str, set[str]] = {}
    for _source, entry in iter_all_courses(curr):
        code = _norm_code(entry.get("code"))
        if not code:
            continue  # רשומה ללא קוד (קורס כללי / ספורט) — אין לה צמידות
        for other in entry.get("tied_with") or []:
            other_code = _norm_code(other)
            if not other_code or other_code == code:
                continue
            graph.setdefault(code, set()).add(other_code)
            graph.setdefault(other_code, set()).add(code)
    return graph


def _replacement_graph(curr: dict) -> dict[str, set[str]]:
    """
    בונה גרף שקילות בין קורס ישן לקורס שהחליף אותו.

    מקורות המידע:
        * curr["replacement_courses"] — הרשימה הרשמית: {"new": ..., "old": ...}
        * שדה "replaced_by" שמופיע על רשומת קורס שבוטלה (למשל 61912 -> 62018)

    שקילות היא סימטרית: מי שעבר 61760 (הישן) נחשב כאילו עבר 61832 (החדש),
    ולהפך. זה בדיוק מה ש-check_prerequisites צריך.
    """
    graph: dict[str, set[str]] = {}

    def link(a: str, b: str) -> None:
        if not a or not b or a == b:
            return
        graph.setdefault(a, set()).add(b)
        graph.setdefault(b, set()).add(a)

    for rep in curr.get("replacement_courses") or []:
        link(_norm_code(rep.get("new")), _norm_code(rep.get("old")))

    for _source, entry in iter_all_courses(curr):
        link(_norm_code(entry.get("code")), _norm_code(entry.get("replaced_by")))

    return graph


def _connected_component(graph: dict[str, set[str]], start: str) -> set[str]:
    """
    סגור טרנזיטיבי: כל הצמתים שאפשר להגיע אליהם מ-start, כולל start עצמו.

    BFS פשוט. אם start אינו בגרף — מחזיר {start} (רפלקסיבי תמיד).
    """
    seen: set[str] = {start}
    queue: list[str] = [start]
    while queue:
        node = queue.pop()
        for neighbour in graph.get(node, ()):  # ריק אם הצומת לא קיים
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return seen


def _resolve_path(path: str | Path) -> Path:
    """
    פותר נתיב לקובץ: מוחלט -> כמו שהוא; יחסי -> מנסה מול תיקיית העבודה,
    ואם לא נמצא — מול שורש הפרויקט. כך main.py עובד מכל תיקייה.
    """
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    if candidate.exists():
        return candidate.resolve()
    return (PROJECT_ROOT / candidate).resolve()


# --------------------------------------------------------------------------
# 1. טעינת הידיעון
# --------------------------------------------------------------------------
def load_curriculum(path: str | Path = DEFAULT_CURRICULUM_PATH) -> dict:
    """
    טוען את קובץ תוכנית הלימודים ומחזיר אותו כ-dict.

    Args:
        path: נתיב לקובץ ה-JSON. יחסי לשורש הפרויקט כברירת מחדל.

    Returns:
        ה-dict המלא של הידיעון (semesters, elective_clusters, וכו').

    Raises:
        FileNotFoundError: אם הקובץ לא נמצא — עם הודעה בעברית ובאנגלית.
        ValueError: אם הקובץ אינו JSON תקין או אינו אובייקט.
    """
    resolved = _resolve_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(
            f"קובץ תוכנית הלימודים לא נמצא: {resolved} "
            f"(curriculum file not found)"
        )

    # encoding="utf-8" חובה — הקובץ מלא בעברית, וב-Windows ברירת המחדל היא cp1255.
    with open(resolved, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"קובץ תוכנית הלימודים אינו JSON תקין: {resolved} — {exc} "
                f"(invalid JSON)"
            ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"מבנה לא צפוי בקובץ תוכנית הלימודים: {resolved} "
            f"(expected a JSON object at the top level)"
        )
    return data


# --------------------------------------------------------------------------
# 2. קורסים לפי סמסטר
# --------------------------------------------------------------------------
def semester_courses(curr: dict, semester: str) -> list[dict]:
    """
    מחזיר את רשימת הקורסים של סמסטר בתוכנית הלימודים.

    Args:
        curr: הידיעון (מ-load_curriculum).
        semester: מספר הסמסטר בתוכנית כמחרוזת, "1".."8".
                  לסטודנטית שלנו — סמסטר 5 (שנה ג', סמסטר א').
                  מתקבל גם int (5) לנוחות.

    Returns:
        רשימה חדשה (עותק רדוד) של רשומות הקורסים, לפי סדר הידיעון.
        הרשימה כוללת גם רשומות עם "code": null — קורס כללי, ספורט וכו'.

    Raises:
        UnknownSemesterError: אם מספר הסמסטר אינו קיים.
    """
    key = _norm_code(semester)
    semesters = curr.get("semesters") or {}
    if key not in semesters:
        available = ", ".join(_semester_keys_in_order(curr)) or "—"
        raise UnknownSemesterError(
            f"סמסטר {semester!r} אינו קיים בתוכנית הלימודים. "
            f"סמסטרים אפשריים: {available} (unknown semester)"
        )
    # list(...) כדי שהקורא לא יוכל בטעות לשנות את הידיעון שנטען.
    return list(semesters[key].get("courses") or [])


def semester_info(curr: dict, semester: str) -> dict:
    """
    מחזיר את "הכותרת" של הסמסטר: term (א/ב), year (שנה), total (סיכומי שעות ונ"ז).

    שימושי ל-CLI בשלב 1 — לאשר מול הסטודנטית שנה/סמסטר לפני שממשיכים.
    השדה "courses" מושמט בכוונה; לקורסים יש semester_courses.

    Raises:
        UnknownSemesterError: אם מספר הסמסטר אינו קיים.
    """
    key = _norm_code(semester)
    semesters = curr.get("semesters") or {}
    if key not in semesters:
        available = ", ".join(_semester_keys_in_order(curr)) or "—"
        raise UnknownSemesterError(
            f"סמסטר {semester!r} אינו קיים בתוכנית הלימודים. "
            f"סמסטרים אפשריים: {available} (unknown semester)"
        )
    body = semesters[key]
    return {k: v for k, v in body.items() if k != "courses"}


# --------------------------------------------------------------------------
# 3. חיפוש קורס לפי קוד
# --------------------------------------------------------------------------
def find_course(curr: dict, code: str) -> dict | None:
    """
    מחפש קוד קורס בכל התוכנית: גם ב-8 הסמסטרים וגם ב-6 אשכולות הבחירה.

    זה קריטי: 61753 (אלגוריתמים) יושב בסמסטר 4, ואילו 62021, למשל,
    קיים *רק* באשכול בחירה. חיפוש שמסתכל רק על סמסטר 5 יפספס את שניהם.

    Args:
        curr: הידיעון.
        code: קוד הקורס, למשל "61756" (גם int יתקבל).

    Returns:
        ה-dict של הקורס, או None אם אין קוד כזה בתוכנית.
        רשומות עם "code": null (קורס כללי, ספורט) לעולם אינן מותאמות.
    """
    wanted = _norm_code(code)
    if not wanted:
        return None
    for _source, entry in iter_all_courses(curr):
        if _norm_code(entry.get("code")) == wanted:
            return entry
    return None


def find_course_source(curr: dict, code: str) -> str | None:
    """
    כמו find_course, אבל מחזיר *מאיפה* הקורס הגיע:
    "semester:4" או "cluster:הנדסת תוכנה". None אם לא נמצא.

    שימושי להסביר לסטודנטית "הקורס הזה שאול מסמסטר 4".
    """
    wanted = _norm_code(code)
    if not wanted:
        return None
    for source, entry in iter_all_courses(curr):
        if _norm_code(entry.get("code")) == wanted:
            return source
    return None


def all_course_codes(curr: dict) -> list[str]:
    """כל קודי הקורסים הקיימים בתוכנית, ממוינים וללא כפילויות (ללא code=null)."""
    return sorted(
        {
            _norm_code(entry.get("code"))
            for _source, entry in iter_all_courses(curr)
            if _norm_code(entry.get("code"))
        }
    )


def resolve_codes(curr: dict, codes: Iterable[str]) -> list[dict]:
    """
    ממיר רשימת קודי קורס לרשימת רשומות הידיעון שלהם — *באותו סדר*.

    זו הדלת הראשית של שאר המודולים: ה-CLI קורא ל-
        resolve_codes(curr, ["11069","61753","61756","61757","61832","62027"])
    ומקבל שש רשומות מלאות (שם, נ"ז, שעות, קדם).

    Args:
        curr: הידיעון.
        codes: איטרבל של קודים.

    Returns:
        list[dict] באורך ובסדר של codes.

    Raises:
        UnknownCourseError: אם קוד אחד או יותר אינו קיים בתוכנית.
                            ההודעה מונה את *כל* הקודים החסרים בבת אחת,
                            כדי שלא נתקן אותם אחד־אחד.
    """
    entries: list[dict] = []
    missing: list[str] = []

    for code in codes:
        entry = find_course(curr, code)
        if entry is None:
            missing.append(_norm_code(code) or repr(code))
        else:
            entries.append(entry)

    if missing:
        raise UnknownCourseError(
            f"קודי קורס שלא נמצאו בתוכנית הלימודים: {', '.join(missing)} — "
            f"יש לבדוק את הקוד מול הידיעון (unknown course code(s))"
        )
    return entries


# --------------------------------------------------------------------------
# 4. קורסים צמודים (korsim tzmudim)
# --------------------------------------------------------------------------
def tied_group(curr: dict, code: str) -> list[str]:
    """
    מחזיר את כל הקורסים ה"צמודים" לקוד הנתון, כולל הוא עצמו.

    "קורסים צמודים" בהנדסת תוכנה = חבילה של הכול־או־כלום: אי אפשר לקחת
    את 61756 בלי 61757 ובלי 62027. הפונקציה סוגרת את הקשר טרנזיטיבית
    ודו־כיוונית, כך שלא משנה באיזה קוד מהחבילה שואלים.

    Examples:
        tied_group(curr, "61756") -> ["61756", "61757", "62027"]
        tied_group(curr, "62027") -> ["61756", "61757", "62027"]
        tied_group(curr, "61832") -> ["61832"]          # קורס עצמאי

    Args:
        curr: הידיעון.
        code: קוד קורס.

    Returns:
        רשימה ממוינת של קודים. תמיד כוללת את code עצמו (רפלקסיבי),
        וגם עבור קוד שאינו קיים בתוכנית מוחזר [code] ולא שגיאה.
    """
    wanted = _norm_code(code)
    if not wanted:
        return []
    graph = _course_pairs_tied(curr)
    return sorted(_connected_component(graph, wanted))


# --------------------------------------------------------------------------
# 5. קורסי קדם ושקילויות
# --------------------------------------------------------------------------
def equivalent_codes(curr: dict, code: str) -> list[str]:
    """
    מחזיר את קבוצת הקורסים ה*שקולים* לקוד הנתון (כולל הוא עצמו), ממוינת.

    שקילות נובעת מטבלת ההחלפות של הידיעון:
        61760 (הסתברות להנדסת תוכנה)  <->  61832 (מבוא להסתברות וסטטיסטיקה)
        61769 (ממשק אדם מחשב)          <->  62027 (HCI)
        61762 (ניהול פרויקטי תוכנה)    <->  62028 (ניהול פרויקטים טכנולוגיים)
        61912 (ארכיטקטורת מערכות תוכנה)<->  62018 (מבוא לארכיטקטורה ומבנה המחשב)

    מי שכבר עברה את הישן — נחשבת כאילו עברה את החדש, ולהפך.
    """
    wanted = _norm_code(code)
    if not wanted:
        return []
    return sorted(_connected_component(_replacement_graph(curr), wanted))


def check_prerequisites(
    curr: dict, code: str, passed: set[str]
) -> tuple[bool, list[str]]:
    """
    בודק אם קורסי הקדם של קורס מסוים מולאו.

    Args:
        curr: הידיעון.
        code: קוד הקורס שרוצים לקחת.
        passed: קבוצת הקודים שהסטודנטית כבר עברה (str). גם int יתקבל.

    Returns:
        (ok, missing):
            ok      – True אם כל קורסי הקדם מולאו.
            missing – רשימת קודי הקדם החסרים, לפי סדר הידיעון, ללא כפילויות.
                      ריקה כאשר ok הוא True.

    שקילות נלקחת בחשבון: אם הקדם הוא 61832 ועברת 61760 — זה נחשב מולא
    (וכן להפך), לפי טבלת replacement_courses.

    שימו לב: יש רשומות עם שדה "cond" — תנאי חלופי שאינו קורס, למשל
    "או ציון פסיכומטרי באנגלית 134". הפונקציה לא יכולה לאמת תנאי כזה,
    ולכן הקדם ידווח כחסר; הקורא יכול לבדוק entry["cond"] ולהחליט.

    Raises:
        UnknownCourseError: אם code אינו קיים בתוכנית הלימודים.
    """
    entry = find_course(curr, code)
    if entry is None:
        shown = _norm_code(code) or repr(code)
        raise UnknownCourseError(
            f"קוד קורס לא נמצא בתוכנית הלימודים: {shown} (unknown course code)"
        )

    # 1. מנרמלים את מה שכבר נלמד, ומרחיבים לכל השקילויות.
    equivalence = _replacement_graph(curr)
    satisfied: set[str] = set()
    for done in passed or ():
        done_code = _norm_code(done)
        if done_code:
            satisfied |= _connected_component(equivalence, done_code)

    # 2. עוברים על קורסי הקדם ומסמנים את מה שחסר, בסדר שבו הם מופיעים בידיעון.
    missing: list[str] = []
    for req in entry.get("prereq") or []:
        req_code = _norm_code(req)
        if not req_code or req_code in missing:
            continue
        # הקדם מולא אם הוא עצמו — או כל קורס שקול לו — נמצא ברשימת שנלמדו.
        if _connected_component(equivalence, req_code) & satisfied:
            continue
        missing.append(req_code)

    return (not missing, missing)


# --------------------------------------------------------------------------
# בדיקת שפיות ידנית: python src/curriculum.py
# --------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import sys

    # ב-Windows הפלט הוא cp1255 כברירת מחדל ועברית תישבר. מגנים על עצמנו,
    # בתוך try/except כי יש זרמים שלא ניתן לשנות (למשל בתוך pytest).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError, OSError):
        pass

    curr = load_curriculum()
    print(f"תוכנית: {curr.get('program')} | קטלוג: {curr.get('catalog')}")
    print(f"סה\"כ קודי קורס בתוכנית: {len(all_course_codes(curr))}")

    print("\n— סמסטר 5 (שנה ג', סמסטר א') —")
    print(f"כותרת: {semester_info(curr, '5')}")
    for c in semester_courses(curr, "5"):
        print(f"  {_norm_code(c.get('code')) or '(ללא קוד)':>7}  {c.get('name')}")

    print("\n— ששת הקורסים של הסטודנטית —")
    codes = ["11069", "61753", "61756", "61757", "61832", "62027"]
    for c, entry in zip(codes, resolve_codes(curr, codes)):
        print(
            f"  {c}  {entry.get('name')}  "
            f"[{find_course_source(curr, c)}]  "
            f"צמודים: {tied_group(curr, c)}"
        )

    print("\n— בדיקת קדם לדוגמה (בהנחה שעברה את הישן 61760) —")
    ok, missing = check_prerequisites(curr, "61836", {"61911", "61760"})
    print(f"  61836: ok={ok} missing={missing}")
