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
    assert [w[2] for w in shnaton._name_words(rows[0], anchor)] == [
        "ניהול", "והערכת", "סיכונים"
    ]
    assert [w[2] for w in shnaton._name_words(rows[2], anchor)] == [
        "בפרויקטים", "הנדסיים"
    ]


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
    # ‏"ל" ו"הנדסת" מודפסים במרווח של ‏-0.1 נקודה, כלומר מילה אחת.
    assert names[1] == "מבוא להנדסת מערכות ותעשיה 4.0 להנדסת תוכנה"
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
    # המקף נדבק לשכניו, כי ה-PDF מדפיס אותם בלי מרווח — ראו _GLUE_GAP.
    assert names[0] == "מבוא ל-ERP ומערכות ארגוניות"


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


# ==========================================================================
# חיבור מילים — מה שה-PDF פיצל, ומה שהוא באמת הפריד
# ==========================================================================
def test_a_word_split_into_two_runs_is_joined_back():
    """‏"בנושאים" מודפס כ-"ב" + "נושאים" במרווח של ‏0.10 נקודה.

    מרווח אמיתי בין מילים ב-sw.pdf הוא ‏1.8–2.5, כלומר סדר גודל שלם
    מעליו. בלי החיבור הזה השם יצא "סמינר ב נושאים נבחרים בבינה מלאכותית".
    """
    row = line(285.9, (
        (403.0, 425.0, "61779"),
        (370.4, 390.0, "סמינר"),
        (364.0, 368.4, "ב"),
        (340.2, 363.9, "נושאים"),
        (313.8, 338.1, "נבחרים"),
        (292.4, 311.7, "בבינה"),
        (257.0, 262.0, "3"),
        (240.0, 243.0, "-"),
        (222.0, 225.0, "-"),
        (200.0, 211.0, "3.0"),
    ))
    tail = line(291.3, ((357.0, 390.0, "מלאכותית"),))
    _anchors, names = shnaton._bind_names([row, tail])
    assert names[0] == "סמינר בנושאים נבחרים בבינה מלאכותית"


def test_a_real_space_between_words_is_kept():
    """החיבור אינו מוחק רווחים אמיתיים — אחרת כל שם היה נדבק לגוש אחד."""
    _anchors, names = shnaton._bind_names(
        [line(179.6, ROW_51145), line(187.7, ANCHOR_51145), line(192.2, TAIL_51145)]
    )
    assert names[1] == EXPECTED
    assert " " in names[1]


def test_words_from_two_different_lines_are_never_glued():
    """‏x חוזר לתחילת העמודה בכל שורה, ולכן "מרווח" בין שורות חסר משמעות.

    חישוב שלו נתן מספר שלילי, והוא חיבר את סוף שורת השם לתחילת השורה
    שאחריה: ‏"יישומים מעשיים באלמנטיםסופיים".
    """
    _anchors, names = shnaton._bind_names(
        [line(179.6, ROW_51145), line(187.7, ANCHOR_51145), line(192.2, TAIL_51145)]
    )
    assert "סיכוניםבפרויקטים" not in names[1]
    assert "סיכונים בפרויקטים" in names[1]


def test_a_colon_clings_to_the_word_before_it():
    """‏civil.pdf מדפיס ":" כ-run נפרד במרווח **רגיל** (‏2.4 נקודות).

    חיבור לפי מרווח אינו תופס אותו, ולכן הפיסוק מטופל בנפרד — אחרת
    ‏421222 יצא "ניהול ובקרת ביצוע : פרוייקטי בנייה".
    """
    head = line(275.3, (
        (439.2, 459.4, "ניהול"),
        (408.8, 434.2, "ובקרת"),
        (384.6, 406.3, "ביצוע"),
        (379.3, 382.2, ":"),
        (197.8, 231.3, "421221"),
        (169.8, 195.3, "שיטות"),
    ))
    anchor = line(288.2, (
        (471.0, 493.0, "421222"),
        (341.0, 346.0, "2"),
        (317.0, 321.0, "1"),
        (293.0, 296.0, "-"),
        (269.0, 272.0, "-"),
        (239.0, 250.0, "2.5"),
    ))
    tail = line(297.9, ((429.0, 455.0, "פרוייקטי"), (406.0, 427.0, "בנייה")))
    _anchors, names = shnaton._bind_names([head, anchor, tail])
    assert names[1] == "ניהול ובקרת ביצוע: פרוייקטי בנייה"
    assert "421221" not in names[1]


# ==========================================================================
# כיוון — קטע לטיני בתוך שם עברי
# ==========================================================================
#: מילה גולמית כפי ש-PyMuPDF מחזיר אותה: ‏(x0, y0, x1, y1, טקסט, block,
#: line, word_no). ‏``_reading_order`` קורא רק את 0, 2, 4, 5, 6 ו-7.
def word(x0, x1, text, block, line_no, word_no):
    return (x0, 0.0, x1, 0.0, text, block, line_no, word_no)


#: ‏22993 ב-industry.pdf עמוד 9, כלשונו: שם עברי שבתוכו קטע לטיני.
ROW_22993 = [
    word(478.1, 502.5, "22993", 37, 0, 0),
    word(432.3, 463.2, "תעשייה", 37, 2, 0),
    word(417.4, 429.9, "4.0", 37, 2, 1),
    word(357.9, 397.4, "(Industry", 37, 3, 0),
    word(399.8, 415.0, "4.0)", 37, 3, 1),
    word(330.1, 335.0, "2", 37, 5, 0),
    word(308.2, 313.1, "3", 37, 7, 0),
    word(286.2, 289.9, "-", 37, 9, 0),
    word(259.5, 272.1, "3.5", 37, 11, 0),
]

#: ‏22837 ב-mecho.pdf עמוד 10: שם לטיני שלם, על שתי שורות ויזואליות.
LATIN_HEAD_22837 = [
    word(377.7, 418.2, "Designing", 34, 2, 0),
    word(420.5, 457.8, "Solutions", 34, 2, 1),
    word(460.0, 467.6, "to", 34, 2, 2),
]
LATIN_TAIL_22837 = [
    word(395.2, 428.2, "Surgical", 35, 0, 0),
    word(430.3, 467.6, "Problems", 35, 0, 1),
]


def test_a_latin_run_keeps_its_own_direction():
    """‏"Designing Solutions to" — ולא ההיפוך שלו."""
    got = [w[4] for w in shnaton._reading_order(LATIN_HEAD_22837)]
    assert got == ["Designing", "Solutions", "to"]
    got = [w[4] for w in shnaton._reading_order(LATIN_TAIL_22837)]
    assert got == ["Surgical", "Problems"]


def test_hebrew_and_latin_in_one_line_each_read_their_own_way():
    """‏22993: העברית מימין לשמאל, הלטינית משמאל לימין, באותה שורה."""
    got = [w[4] for w in shnaton._reading_order(ROW_22993)]
    assert got == ["22993", "תעשייה", "4.0", "(Industry", "4.0)",
                   "2", "3", "-", "3.5"]


def test_the_latin_name_comes_out_in_reading_order():
    """מקצה לקצה על השורה: השם, לא רצף המילים ההפוך."""
    row = shnaton.Line(
        page=9, y=621.8,
        words=tuple((w[0], w[2], w[4]) for w in shnaton._reading_order(ROW_22993)),
        text="",
    )
    _anchors, names = shnaton._bind_names([row])
    assert names[0] == "תעשייה 4.0 (Industry 4.0)"


def test_a_hebrew_run_is_never_reordered_by_drawing_order():
    """‏``word_no`` הוא סדר **ציור**, ולכן אינו ראיה לכיוון.

    ‏industry.pdf מצייר את הנקודתיים של "אשכול: מדע וטכנולוגיה" **לפני**
    המילה שלפניהן, ושתיהן קטע אחד שה-x שלו עולה במקרה. בלי הדרישה לאות
    לטינית הכותרת נקראה ‏": אשכול", ‏``_CLUSTER_RE`` הפסיק להתאים לה,
    ושלושה קורסים דלפו לאשכול השכן.
    """
    header = [word(471.7, 476.3, ":", 34, 0, 0), word(476.3, 505.6, "אשכול", 34, 0, 1)]
    assert [w[4] for w in shnaton._reading_order(header)] == ["אשכול", ":"]


def test_two_latin_words_are_not_glued_together():
    """המרווח נמדד בלי הנחת כיוון — אחרת ‏x עולה נתן "מרווח" שלילי."""
    joined = shnaton._join_words(
        [(w[0], w[2], w[4]) for w in shnaton._reading_order(LATIN_HEAD_22837)]
    )
    assert joined == "Designing Solutions to"


# ==========================================================================
# סוגריים — גלִיף מצויר מול תו לוגי
# ==========================================================================
#: ‏61966 ב-system.pdf עמוד 10, כלשונו. הסוגריים אוחסנו כבבואה: בסדר
#: הקריאה ‏")" מופיע **לפני** "(".
ROW_61966 = [
    word(416.8, 439.5, "61966", 29, 0, 0),
    word(303.2, 305.9, "(", 29, 2, 0),
    word(390.6, 410.2, "סמינר", 29, 2, 1),
    word(362.9, 388.6, "מערכות", 29, 2, 2),
    word(338.0, 360.7, "לומדות", 29, 2, 3),
    word(333.2, 335.9, ")", 29, 2, 4),
    word(306.0, 333.2, "באנגלית", 29, 2, 5),
    word(271.8, 276.3, "3", 29, 3, 0),
    word(254.5, 257.3, "-", 29, 4, 0),
    word(236.3, 239.0, "-", 29, 5, 0),
    word(214.6, 225.9, "3.0", 29, 6, 0),
]

#: הכותרת "אשכול: מדע וטכנולוגיה (עבור שתי ההתמחויות)" ב-industry.pdf
#: עמוד 9. אותם תווים בדיוק — ‏U+0028 ו-U+0029 — אבל **מקוננים כהלכה**
#: בסדר הקריאה, כלומר לוגיים כבר עכשיו.
HEADER_NESTED = [
    word(471.7, 476.3, ":", 34, 0, 0),
    word(476.3, 505.6, "אשכול", 34, 0, 1),
    word(293.8, 297.5, ")", 34, 1, 0),
    word(450.7, 469.0, "מדע", 34, 1, 1),
    word(400.6, 448.0, "וטכנולוגיה", 34, 1, 2),
    word(394.3, 398.0, "(", 34, 1, 3),
    word(374.0, 394.3, "עבור", 34, 1, 4),
    word(352.1, 371.3, "שתי", 34, 1, 5),
    word(297.4, 349.5, "ההתמחויות", 34, 1, 6),
]


def test_a_mirrored_bracket_pair_is_turned_back():
    """סוגר סוגר שמופיע ראשון בסדר הקריאה — הזוג אוחסן כבבואה."""
    got = [w[4] for w in shnaton._reading_order(ROW_61966)]
    assert got == ["61966", "סמינר", "מערכות", "לומדות",
                   "(", "באנגלית", ")", "3", "-", "-", "3.0"]


def test_the_name_of_61966_reads_forward():
    """מקצה לקצה: השם המלא, עם הסוגריים בצורתם הלוגית."""
    row = shnaton.Line(
        page=10, y=423.5,
        words=tuple((w[0], w[2], w[4]) for w in shnaton._reading_order(ROW_61966)),
        text="",
    )
    _anchors, names = shnaton._bind_names([row])
    assert names[0] == "סמינר מערכות לומדות (באנגלית)"


def test_a_properly_nested_pair_is_left_alone():
    """אותם תווים, מקוננים כהלכה — ואסור לגעת בהם.

    ‏**זה החצי שמונע כלל גורף.** היפוך של כל סוגר בכל קטע ימין-לשמאל היה
    הופך את הכותרת הזאת ל-"מדע וטכנולוגיה ) עבור ... (", ואז
    ‏``parse_chapter`` — שחותך את שם האשכול ב-"(" — היה קורא לאשכול
    ‏"מדע וטכנולוגיה ) עבור שתי ההתמחויות" במקום "מדע וטכנולוגיה".
    """
    got = [w[4] for w in shnaton._reading_order(HEADER_NESTED)]
    assert got == ["אשכול", ":", "מדע", "וטכנולוגיה",
                   "(", "עבור", "שתי", "ההתמחויות", ")"]


def test_unmirror_only_fires_on_a_closer_first_run():
    """המבחן עצמו, בלי שאר המכונה."""
    ordered = sorted(ROW_61966, key=lambda w: -w[0])
    assert [w[4] for w in shnaton._unmirror(ordered) if w[4] in "()"] == ["(", ")"]
    nested = sorted(HEADER_NESTED, key=lambda w: -w[0])
    assert shnaton._unmirror(nested) is nested, "רצף מקונן חוזר כמו שהוא"


def test_a_bracket_glued_to_a_latin_word_is_not_touched():
    """‏"(Industry" הוא חלק ממילה בקטע לטיני, ואינו סוגר בודד."""
    got = [w[4] for w in shnaton._reading_order(ROW_22993)]
    assert "(Industry" in got and "4.0)" in got
