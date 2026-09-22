# -*- coding: utf-8 -*-
"""‏שם קורס נבנה מעמודת השם בלבד — בדיקה של המפענח עצמו.

המקרה
------
‏``51145`` בפרק הנדסת תעשייה וניהול (‏industry.pdf, עמוד 8). השורה נשברת
לשלוש שורות ויזואליות, והשם מודפס **מעל** שורת המספרים וממשיך מתחתיה:

    y=179.6   ניהול  והערכת  סיכונים  │  11001  אלגברה
    y=187.7   51145        2  1  -  2.5  │
    y=192.2   בפרויקטים  הנדסיים        │  51723  סטטיסטיקה

העמודה השמאלית בשתי שורות השם היא "קורסי קדם". כל עוד המפענח שיטח כל
שורה למחרוזת אחת, שתי העמודות נראו זהות — ולכן השם יצא

    "ניהול והערכת סיכונים 11001 אלגברה"

במקום "ניהול והערכת סיכונים בפרויקטים הנדסיים": חצי שם, ועליו מספר קורס
של קורס אחר ומחצית שמו. ‏22 שורות ב-``data/curricula.json`` היו כאלה.

למה הבדיקה לא קוראת PDF
------------------------
פרקי השנתון **אינם במאגר** (‏git-ignored), ולכן כל בדיקה שנשענת עליהם
מדלגת על עצמה ב-CI — שם בדיוק צריך השומר לעבוד. הקואורדינטות למטה הן
המדידה האמיתית של אותה שורה, מועתקת כלשונה, ולכן זו בדיקה של הקוד ולא
של הסביבה. הבדיקה שכן קוראת את ה-PDF נמצאת בסוף הקובץ ומדלגת בנימוס.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import shnaton  # noqa: E402

INDUSTRY = ROOT / "industry.pdf"

#: השורה האמיתית, כפי שנמדדה ב-``industry.pdf`` עמוד 8.
#: ‏(x0, x1, טקסט) לכל מילה, ממוינות לפי x יורד — עברית.
ROW_51145: tuple[tuple[float, float, str], ...] = (
    (444.2, 463.1, "ניהול"),
    (414.3, 442.1, "והערכת"),
    (383.6, 412.1, "סיכונים"),
    (230.3, 252.2, "11001"),
    (200.0, 228.2, "אלגברה"),
)
ANCHOR_51145: tuple[tuple[float, float, str], ...] = (
    (482.9, 504.7, "51145"),
    (330.3, 334.7, "2"),
    (308.5, 312.8, "1"),
    (286.3, 289.5, "-"),
    (260.1, 271.3, "2.5"),
)
TAIL_51145: tuple[tuple[float, float, str], ...] = (
    (422.9, 463.1, "בפרויקטים"),
    (389.8, 420.8, "הנדסיים"),
    (230.3, 252.2, "51723"),
    (182.2, 228.1, "סטטיסטיקה"),
)

EXPECTED = "ניהול והערכת סיכונים בפרויקטים הנדסיים"


def line(y: float, words: tuple[tuple[float, float, str], ...]) -> shnaton.Line:
    return shnaton.Line(
        page=8, y=y, words=words, text="  ".join(w[2] for w in words)
    )


@pytest.fixture()
def rows() -> list[shnaton.Line]:
    return [
        line(179.6, ROW_51145),
        line(187.7, ANCHOR_51145),
        line(192.2, TAIL_51145),
    ]


def test_the_name_is_taken_from_the_name_column_only(rows):
    """הבדיקה המרכזית: השם המלא, בלי עמודת הקדם."""
    anchors, names = shnaton._bind_names(rows)
    assert list(anchors) == [1], "שורת המספרים היא העוגן, ורק היא"
    assert anchors[1].code == "51145"
    assert names[1] == EXPECTED


def test_the_name_never_carries_another_courses_code(rows):
    """הצורה של התקלה, ולא רק הערך שלה."""
    _anchors, names = shnaton._bind_names(rows)
    for code in ("11001", "51723"):
        assert code not in names[1], f"{code} הוא קדם, לא חלק מהשם"


def test_the_prereq_column_is_outside_the_name_column(rows):
    """‏מה שמגן: גבולות ב-x, ולא ניחוש על מחרוזת שטוחה."""
    anchor = shnaton._anchor_at(rows[1])
    assert anchor is not None
    # עמודת השם נמצאת בין התא המספרי הימני ביותר למספר הקורס.
    assert anchor.name_from == pytest.approx(334.7)
    assert anchor.name_to == pytest.approx(482.9)
    assert shnaton._name_words(rows[0], anchor) == ["ניהול", "והערכת", "סיכונים"]
    assert shnaton._name_words(rows[2], anchor) == ["בפרויקטים", "הנדסיים"]


def test_a_prereq_line_is_not_mistaken_for_a_course(rows):
    """שורת קדם פותחת גם היא במספר קורס — ואין בה נ"ז, ולכן אינה עוגן."""
    prereq_only = line(200.0, ((230.3, 252.2, "51723"), (182.2, 228.1, "סטטיסטיקה")))
    assert shnaton._anchor_at(prereq_only) is None


def test_a_table_header_is_not_absorbed_into_the_first_name():
    """‏"שם הקורס" יושב בדיוק בעמודת השם, ולכן חייב זיהוי משלו."""
    header = line(170.0, (
        (494.0, 504.0, "מס"),
        (491.0, 493.0, "'"),
        (464.0, 489.0, "הקורס"),
        (451.0, 462.0, "שם"),
        (423.0, 449.0, "הקורס"),
        (345.0, 350.0, "ה"),
        (321.0, 326.0, "ת"),
        (247.0, 252.0, "ז"),
    ))
    assert shnaton._is_table_header(header)
    anchors, names = shnaton._bind_names(
        [header, line(179.6, ROW_51145), line(187.7, ANCHOR_51145),
         line(192.2, TAIL_51145)]
    )
    index = next(iter(anchors))
    assert names[index] == EXPECTED


def test_a_credits_cell_inside_the_name_is_part_of_the_name():
    """‏"ותעשיה 4.0" — ‏4.0 נראה כמו תא נ"ז ואינו אחד.

    ‏62004 ב-sw.pdf עמוד 12, כלשונו. השם מודפס מעל שורת המספרים ומסתיים
    ב-"4.0"; ההבדל בינו לבין נ"ז אמיתית הוא המיקום — הוא יושב בתוך עמודת
    השם, והנ"ז יושבת באזור העמודות המספריות. בלי ההבחנה הזאת שורת השם
    כולה נפסלה כ"שורה של קורס אחר", והקורס נשאר עם "להנדסת תוכנה" בלבד.
    """
    head = line(221.0, (
        (405.6, 422.3, "מבוא"),
        (399.7, 403.6, "ל"),
        (376.8, 399.8, "הנדסת"),
        (349.1, 374.8, "מערכות"),
        (321.2, 346.9, "ותעשיה"),
        (307.9, 319.2, "4.0"),
    ))
    anchor = line(226.5, (
        (430.9, 453.7, "62004"),
        (287.2, 291.7, "2"),
        (269.2, 273.7, "1"),
        (251.5, 254.3, "-"),
        (229.3, 240.7, "2.5"),
        (200.5, 223.3, "61756"),
        (177.7, 198.4, "שיטות"),
        (148.6, 175.6, "הנדסיות"),
    ))
    tail = line(232.1, ((395.4, 422.2, "להנדסת"), (373.2, 393.4, "תוכנה")))
    anchors, names = shnaton._bind_names([head, anchor, tail])
    assert list(anchors) == [1]
    assert names[1] == "מבוא ל הנדסת מערכות ותעשיה 4.0 להנדסת תוכנה"
    assert "61756" not in names[1], "עמודת הקדם נשארת בחוץ"


def test_a_row_of_its_own_is_not_swallowed_as_a_continuation():
    """שורה שיש בה תא נ"ז **באזור המספרי** שייכת לקורס משלה.

    ‏system.pdf מדפיס "למידה עמוקה עבור ראיית מכונה 2 1 - 2.5" בשורה
    שמספר הקורס שלה נמצא במקום אחר. בלי הפסילה הזאת היא נדבקה לשמו של
    הקורס שמעליה — ‏61992 יצא "מבוא לחישה ולמידה למידה עמוקה עבור ראיית
    מכונה".
    """
    anchor = line(566.3, (
        (405.0, 427.0, "61992"),
        (372.0, 396.0, "מבוא"),
        (348.0, 370.0, "לחישה"),
        (323.0, 346.0, "ולמידה"),
        (246.0, 251.0, "3"),
        (224.0, 228.0, "-"),
        (212.0, 215.0, "-"),
        (190.0, 201.0, "3.0"),
    ))
    other = line(586.4, (
        (369.0, 393.0, "למידה"),
        (345.0, 367.0, "עמוקה"),
        (327.0, 343.0, "עבור"),
        (307.0, 325.0, "ראיית"),
        (285.0, 305.0, "מכונה"),
        (246.0, 251.0, "2"),
        (224.0, 228.0, "1"),
        (212.0, 215.0, "-"),
        (190.0, 201.0, "2.5"),
    ))
    _anchors, names = shnaton._bind_names([anchor, other])
    assert names[0] == "מבוא לחישה ולמידה"


def test_a_dash_inside_the_name_does_not_end_it():
    """‏"מבוא ל-ERP" — ‏51154 ב-industry.pdf עמוד 7, כלשונו.

    המקף שבתוך השם נראה בדיוק כמו תא עמודה ריק. אילו הוא היה קובע את
    גבול העמודה, השם היה נחתך ל"מבוא".
    """
    row = line(404.0, (
        (482.9, 504.7, "51154"),
        (444.7, 463.8, "מבוא"),
        (438.0, 442.3, "ל"),
        (434.7, 438.0, "-"),
        (416.6, 434.6, "ERP"),
        (381.2, 412.2, "ומערכות"),
        (347.5, 379.0, "ארגוניות"),
        (330.4, 334.8, "2"),
        (309.4, 312.7, "-"),
        (287.5, 291.8, "2"),
        (261.8, 273.0, "3.0"),
    ))
    _anchors, names = shnaton._bind_names([row])
    assert names[0] == "מבוא ל - ERP ומערכות ארגוניות"


# ==========================================================================
# מקצה לקצה — רק כשפרק השנתון נמצא על הדיסק
# ==========================================================================
@pytest.mark.skipif(not INDUSTRY.exists(), reason="industry.pdf חסר (git-ignored)")
def test_the_real_chapter_reads_the_same_name():
    """אותה שורה, דרך ה-PDF האמיתי ולא דרך הקואורדינטות המועתקות."""
    chapter = shnaton.parse_chapter(INDUSTRY)
    found = {
        course["code"]: course["name"]
        for group in chapter["clusters"].values()
        for course in group
    }
    assert found.get("51145") == EXPECTED
