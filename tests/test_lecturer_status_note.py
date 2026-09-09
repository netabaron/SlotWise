"""שם המרצה הוא שם, והודעת המצב יושבת בשדה משלה.

הבאג
-----
בידיעון, ההודעה "הקורס מלא" יושבת ב-``<span class="text color-red">``
משלה, **בין** שם המרצה לבין "שפת הוראה של הקורס". ‏``_visible_text``
משטח את הבלוק למחרוזת אחת, והביטוי שמחלץ את המרצה עוצר רק על "שפת
הוראה" — ולכן הוא בלע גם את ה-span האדום. התוצאה, על כל בלוק שעה
ברשת ועל הדף המודפס: ``"מר כהן אסף הקורס מלא"``.

נמדד ב-2026-09-10 מול ``data/db/sections.json`` החי: 44 ערכים מתוך 346
נשאו הודעה, ו-119 שורות קבוצה. אחרי התיקון, על כל 572 הדפים השמורים
ב-``data/raw``: אפס.

שלוש הצורות שהתגלו, ולכל אחת בדיקה כאן
---------------------------------------
1. **הודעה מסומנת שנדבקה לשם.** ``הקורס מלא``, ``בקורס זה קיימת רשימת
   המתנה``. הטיפול נשען על ה-DOM — הטקסט של ה-span האדום — ולא על
   רשימת ניסוחים, כדי שנוסח חדש יטופל מעצמו.
2. **הודעה במקום שם**, כטקסט חשוף: ``טרם נקבע``, ``מיועד לחוזרים``.
   ההתאמה היא על הערך **המלא**, ולכן היא אינה יכולה לקצר שם אמיתי.
3. **שם ריק לגמרי.** ‏``(.+?)`` לא יכול לעצור על "שפת הוראה" כשאין ולו
   תו אחד לפניו, ולכן רץ עד סוף הדף: קורס 312781 קיבל שדה מרצה שהכיל
   ``"שפת הוראה של הקורס : עברית מערכת שעות ... מדיניות הפרטיות הצהרת
   נגישות"``. ‏``(.*?)`` פותר את זה.

מה שנשמר בכוונה
----------------
‏24 ערכים בקטלוג הם **שני מרצים אמיתיים** מופרדים בפסיק, עד ארבעה
בערך אחד. פיצול נאיבי על פסיק היה הופך אותם לזבל, ולכן ההסרה על פסיק
מוציאה רק מקטע שהוא **בדיוק** אחד הביטויים שאינם שם.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import parser as parser_mod  # noqa: E402
from models import Group  # noqa: E402

_split = parser_mod._split_lecturer_status


# ==========================================================================
# 1. הפונקציה עצמה
# ==========================================================================
@pytest.mark.parametrize(
    ("value", "statuses", "name", "note"),
    [
        # 1. הודעה מסומנת שנדבקה לשם
        ("מר כהן אסף הקורס מלא", ["הקורס מלא"], "מר כהן אסף", "הקורס מלא"),
        (
            "פריטולו יבגני בקורס זה קיימת רשימת המתנה",
            ["בקורס זה קיימת רשימת המתנה"],
            "פריטולו יבגני",
            "בקורס זה קיימת רשימת המתנה",
        ),
        # ‏שפת ההוראה יושבת גם היא ב-span אדום, ולעולם אינה סיומת של השם.
        ('ד"ר סוקולובסקי איזבלה', ["אנגלית"], 'ד"ר סוקולובסקי איזבלה', ""),
        # 2. הודעה במקום שם
        ("טרם נקבע", [], "", ""),
        ("מיועד לחוזרים", [], "", "מיועד לחוזרים"),
        # הודעה מסומנת לבדה, בקבוצה בלי מרצה
        ("הקורס מלא", ["הקורס מלא"], "", "הקורס מלא"),
        # 3. שם ריק
        ("", [], "", ""),
        # שני מרצים אמיתיים — נשארים שלמים
        (
            'ד"ר גזית שמואל, מר ברק דני',
            [],
            'ד"ר גזית שמואל, מר ברק דני',
            "",
        ),
        (
            'ד"ר קלס סיון, ד"ר גזית שמואל, ד"ר יסעור קרוח לילך, פרופ\' סבאח עיסאם',
            [],
            'ד"ר קלס סיון, ד"ר גזית שמואל, ד"ר יסעור קרוח לילך, פרופ\' סבאח עיסאם',
            "",
        ),
        # מרצה אחד אמיתי ומשבצת שנייה שטרם מולאה
        ('ד"ר קליינגזינד שלום, טרם נקבע', [], 'ד"ר קליינגזינד שלום', ""),
        # שם + הודעה מסומנת + פסיק — שני המסלולים יחד
        (
            'ד"ר קליינגזינד שלום, מר עראם אשרף הקורס מלא',
            ["הקורס מלא"],
            'ד"ר קליינגזינד שלום, מר עראם אשרף',
            "הקורס מלא",
        ),
    ],
)
def test_the_name_and_the_status_are_separated(value, statuses, name, note):
    assert _split(value, statuses) == (name, note)


def test_a_status_that_is_not_a_suffix_is_left_alone():
    """חיתוך רק בקצה. הודעה שמופיעה באמצע אינה נחתכת — ואין כזאת בנתונים,
    אבל חיתוך מהאמצע היה יכול להשאיר שתי מחציות של שם מודבקות זו לזו."""
    assert _split("הקורס מלא מר כהן אסף", ["הקורס מלא"]) == (
        "הקורס מלא מר כהן אסף",
        "",
    )


def test_a_value_with_nothing_to_remove_comes_back_byte_identical():
    """‏מוטציה: בלי הבדיקה "האם באמת ירד מקטע", כל ערך עם פסיק היה נבנה
    מחדש כ-``", ".join(...)``. על הנתונים היום זה מחזיר בדיוק את אותה
    מחרוזת, ולכן שום בדיקה אחרת לא הייתה מרגישה — עד לרווח לא סטנדרטי
    סביב פסיק, שהיה מנורמל בשקט. שם מרצה אינו שדה שמנרמלים בדרך אגב."""
    value = 'ד"ר גזית שמואל ,מר ברק דני'
    assert _split(value, []) == (value, "")


def test_a_name_that_merely_contains_the_words_survives():
    """מוטציה: אילו ההתאמה הייתה ``in`` ולא ``==`` על הערך המלא, השם הזה
    היה נמחק. אין מרצה כזה בקטלוג — וזו בדיוק הסיבה לבדוק אותו כאן."""
    assert _split("מר טרם נקבעי דוד", []) == ("מר טרם נקבעי דוד", "")


def test_a_label_that_leaked_into_the_field_is_not_a_name():
    """‏שאריות של הצורה השלישית שכבר נכתבו לדיסק. ההתאמה היא על **תחילת**
    הערך, כי אחרי התווית בא ערך משתנה — "עברית", "אנגלית". אדם ששמו
    מתחיל ב"שפת הוראה" אינו קיים."""
    assert _split("שפת הוראה של הקורס : עברית", []) == ("", "")
    assert _split("שפת הוראה של הקורס : אנגלית מערכת שעות סמסטר", []) == ("", "")


def test_legacy_data_is_repaired_when_it_is_read():
    """‏הקטלוג שנשלח עם הקוד נבנה ב-2026-09-07 ונושא 134 שורות מלוכלכות.
    בנייה מחדש שלו מביאה איתה **גם** קבוצה שהידיעון הוסיף ב-08/09, וזו
    כבר החלטה אחרת (ראו ‏DEFERRED). לכן התיקון לנתונים הישנים חל בזמן
    קריאה, ב-``store._group_from_dict``, ושיבוט טרי רואה שמות נקיים
    בלי שהקטלוג ייגע.

    ‏בזמן קריאה אין ``span`` אדום, ולכן כאן דווקא כן יש רשימת ניסוחים —
    אבל רק לסיומת מדויקת, ורק אם נשאר שם אחריה.
    """
    import sys as _sys

    _sys.path.insert(0, str(ROOT / "tests"))
    from catalog_source import catalog_courses  # noqa: PLC0415

    courses = catalog_courses()
    assert len(courses) > 100, "הקטלוג ריק — אין מה לבדוק"
    dirty = [
        f"{code}/{g.group_id}: {g.lecturer!r}"
        for code, course in courses.items()
        for g in course.groups
        if any(p in g.lecturer for p in FORBIDDEN)
    ]
    assert dirty == [], "הקטלוג מחזיר שם מרצה עם הודעה: " + "; ".join(dirty[:8])
    # ‏ובלי זה היה אפשר "לנקות" פשוט על ידי ריקון השדה.
    recovered = {g.status_note for course in courses.values() for g in course.groups
                 if g.status_note}
    assert "הקורס מלא" in recovered


def test_the_status_never_lands_in_the_note_field():
    """‏``note`` נושא הערות שיוך וחובת נוכחות, ו-``api.attendance_info``
    סורק אותו בביטוי רגולרי. הודעת מצב שנכנסת לשם משנה את מה שהממשק
    אומר על נוכחות, ולכן היא בשדה נפרד."""
    g = Group(course_code="1", group_id="1", kind="הרצאה", lecturer="", meetings=[])
    assert g.note == ""
    assert g.status_note == ""
    assert "status_note" in {f for f in parser_mod._GROUP_FIELDS}


# ==========================================================================
# 2. הביטוי הרגולרי — הצורה השלישית
# ==========================================================================
def test_an_empty_lecturer_does_not_swallow_the_rest_of_the_page():
    """‏312781 החזיר שדה מרצה שהכיל את כותרות הטבלה ואת קישורי התחתית."""
    head = (
        "קורס מסוג הרצאה קבוצה : 2731300 מרצה הקורס : "
        "שפת הוראה של הקורס : עברית מערכת שעות סמסטר יום בשבוע "
        "מדיניות הפרטיות הצהרת נגישות"
    )
    m = parser_mod._GROUP_LECTURER_RE.search(head)
    assert m is not None
    assert m.group(1).strip() == ""


def test_a_real_name_still_matches():
    head = 'קורס מסוג שו"ת קבוצה : 271060310/ 1 מרצה הקורס : ד"ר סוקולובסקי איזבלה שפת הוראה של הקורס : אנגלית'
    m = parser_mod._GROUP_LECTURER_RE.search(head)
    assert m is not None
    assert m.group(1).strip() == 'ד"ר סוקולובסקי איזבלה'


# ==========================================================================
# 3. מקצה לקצה, מול HTML אמיתי מהידיעון
# ==========================================================================
RAW = ROOT / "data" / "raw"

#: ניסוחים שאסור שיופיעו בשדה המרצה, בשום עמוד.
FORBIDDEN = (
    "הקורס מלא",
    "רשימת המתנה",
    "טרם נקבע",
    "מיועד לחוזרים",
    "שפת הוראה",
    "מערכת שעות",
    "מדיניות הפרטיות",
    "הצהרת נגישות",
)


def _pages() -> list[Path]:
    if not RAW.is_dir():
        return []
    return sorted(p for p in RAW.glob("*_1.html") if p.stem.split("_")[0].isdigit())


@pytest.mark.parametrize(
    "name",
    [
        "11069_1.html",   # שם + "הקורס מלא"
        "11073_1.html",   # שם + "בקורס זה קיימת רשימת המתנה"
        "11023_1.html",   # "מיועד לחוזרים" במקום שם
        "31090_1.html",   # "טרם נקבע" במקום שם
        "312781_1.html",  # שם ריק לגמרי
    ],
)
def test_a_saved_page_yields_names_only(name):
    page = RAW / name
    if not page.exists():
        pytest.skip(f"אין {name} ב-data/raw")
    course, _warnings = parser_mod.parse_course_page(
        page.read_text(encoding="utf-8", errors="replace"), name.split("_")[0]
    )
    assert course is not None
    assert course.groups, "העמוד חייב להניב קבוצות — אחרת הבדיקה ריקה"
    for g in course.groups:
        for phrase in FORBIDDEN:
            assert phrase not in g.lecturer, (
                f"{g.course_code}/{g.group_id}: '{phrase}' בשדה המרצה — {g.lecturer!r}"
            )


def test_no_saved_page_puts_a_note_in_the_lecturer_field():
    """הבדיקה הרחבה: כל ``data/raw``. מדלגת על עצמה במכונה בלי הדפים."""
    pages = _pages()
    if len(pages) < 50:
        pytest.skip("אין מספיק דפים שמורים ב-data/raw")
    dirty: list[str] = []
    seen_status = set()
    for page in pages:
        code = page.stem.split("_")[0]
        course, _warnings = parser_mod.parse_course_page(
            page.read_text(encoding="utf-8", errors="replace"), code
        )
        if course is None:
            continue
        for g in course.groups:
            if any(p in g.lecturer for p in FORBIDDEN):
                dirty.append(f"{code}/{g.group_id}: {g.lecturer!r}")
            if g.status_note:
                seen_status.add(g.status_note)
    assert dirty == [], "שדה המרצה נושא הודעה: " + "; ".join(dirty[:12])
    # ‏ובלי זה הבדיקה הייתה עוברת גם אילו ההודעות פשוט נזרקו לפח.
    assert "הקורס מלא" in seen_status
    assert seen_status <= {
        "הקורס מלא",
        "מיועד לחוזרים",
        "בקורס זה קיימת רשימת המתנה",
    }, f"הודעת מצב בניסוח שאיש לא בדק: {seen_status}"


def test_two_real_lecturers_are_never_split():
    """‏24 ערכים בקטלוג הם שני מרצים או יותר. אף אחד מהם לא נחתך."""
    pages = _pages()
    if len(pages) < 50:
        pytest.skip("אין מספיק דפים שמורים ב-data/raw")
    multi = 0
    for page in pages:
        code = page.stem.split("_")[0]
        course, _warnings = parser_mod.parse_course_page(
            page.read_text(encoding="utf-8", errors="replace"), code
        )
        if course is None:
            continue
        for g in course.groups:
            if "," in g.lecturer:
                multi += 1
                for part in g.lecturer.split(","):
                    assert part.strip(), f"מקטע ריק ב-{g.lecturer!r}"
                    assert part.strip() not in ("טרם נקבע", "מיועד לחוזרים")
    assert multi >= 20, f"נמצאו רק {multi} ערכים עם שני מרצים — משהו כן פוצל"
