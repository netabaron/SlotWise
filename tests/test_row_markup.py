"""שורה בגריד של הידיעון מזוהה לפי ה-class ``row``, לא לפי התגית.

הבאג
-----
ב-2026-10-19 הידיעון החליף את ``<div class="row">`` ב-``<article class="row">``
גם בדף הקטלוג וגם בדף הקורס. שני הפרסרים חיפשו ``div.row`` בלבד:

* ‏``discovery.parse_catalog`` מצא 0 שורות בדף של ~576 קורסים, והבנייה
  הלילית נכשלה ב-19.10 וב-20.10 עם "הקטלוג חזר ריק".
* ‏``parser.parse_course_page`` עדיין מצא את הקבוצות (הכותרת שלהן אינה
  שורה), אבל איבד **כל** מפגש — יום, שעה, חדר — כי טבלת מערכת השעות
  בנויה משורות.

הפיקסצ'רים ב-``tests/fixtures/row_markup/`` קוצרו מהדפים החיים של
2026-10-20. קובצי ה-``div`` הם אותם קבצים בדיוק עם התגית הישנה (וה-class
‏``g-mb-12`` שהכפתור נשא אז) — כך ששני המבנים חייבים לתת אותה תוצאה.
שמות המרצים הוחלפו בשמות-מקום.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import discovery  # noqa: E402
import parser as parser_mod  # noqa: E402
import refresh  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "row_markup"
MARKUPS = ("div", "article")


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ==========================================================================
# 1. דף הקטלוג
# ==========================================================================
EXPECTED_CATALOG = {
    "41063": {"name": "כימיה אורגנית 2 - סליק", "status": "נלמד"},
    "421314": {"name": "מבני בטון 2", "status": "נלמד"},
    "421315": {"name": "דינמיקת מבנים", "status": "נלמד"},
    "61761": {"name": "כריית נתונים ומערכות לומדות", "status": "נלמד"},
}


@pytest.mark.parametrize("markup", MARKUPS)
def test_catalog_rows_parse_in_both_markups(markup):
    courses, _ = discovery.parse_catalog(_read(f"catalog_rows_{markup}.html"))
    assert courses == EXPECTED_CATALOG


@pytest.mark.parametrize("markup", MARKUPS)
def test_catalog_header_and_junk_rows_are_ignored(markup):
    courses, warnings = discovery.parse_catalog(_read(f"catalog_rows_{markup}.html"))
    # שורת הכותרת ("קוד קורס"), שורת ההערה ושורת הכותרת התחתונה אינן קודים.
    assert "קוד קורס" not in courses
    # קוד בתא הראשון בלי כפתור חיפוש — לא שורת קורס, ונרשם על כך.
    assert "12345" not in courses
    assert any("12345" in w and "S_LOOK_FOR_NOSE" in w for w in warnings)


def test_catalog_both_markups_agree():
    old, old_warnings = discovery.parse_catalog(_read("catalog_rows_div.html"))
    new, new_warnings = discovery.parse_catalog(_read("catalog_rows_article.html"))
    assert old == new
    assert old_warnings == new_warnings


# ==========================================================================
# 2. דף הקורס
# ==========================================================================
def _groups(markup: str) -> list[tuple]:
    result = parser_mod.parse_course_page(_read(f"course_{markup}.html"), "11001")
    assert result.course is not None, result.warnings
    return [
        (
            g.group_id,
            g.kind,
            g.lecturer,
            g.status_note,
            [(m.day, m.start, m.end, m.room, m.semester) for m in g.meetings],
        )
        for g in result.course.groups
    ]


EXPECTED_GROUPS = [
    ("261200111", "הרצאה", 'ד"ר מרצה א', "", [(5, 570, 740, "EM 103", "א")]),
    ("261200111/1", "הרצאה", 'ד"ר מרצה א', "הקורס מלא", [(1, 510, 690, "302 EM", "א")]),
    ("261200111/1", "תרגול", "גב' מתרגלת ב", "", [(5, 630, 740, "703 L", "א")]),
]


@pytest.mark.parametrize("markup", MARKUPS)
def test_course_groups_times_and_rooms_in_both_markups(markup):
    assert _groups(markup) == EXPECTED_GROUPS


@pytest.mark.parametrize("markup", MARKUPS)
def test_course_schedule_header_is_found(markup):
    """לפני התיקון: "לא נמצאה שורת כותרת" ו"אין מועד קבוע" על כל קבוצה."""
    result = parser_mod.parse_course_page(_read(f"course_{markup}.html"), "11001")
    assert not [w for w in result.warnings if "header row not found" in w]
    assert not [w for w in result.warnings if "no fixed time" in w]


def test_course_both_markups_agree():
    assert _groups("div") == _groups("article")


# ==========================================================================
# 3. ההודעה ביומן כשהמבנה משתנה שוב
# ==========================================================================
def _run_catalog_pass(html: str) -> dict:
    record = {"catalog": {"refreshed": False, "courses": 0, "warnings": []}}
    store = SimpleNamespace(
        save_catalog=lambda *a, **k: pytest.fail("an empty parse must not be saved"),
        load_catalog=lambda: ({}, {}),
    )
    outcome, _, _ = refresh.run_pass(
        SimpleNamespace(fetch_catalog_html=lambda: html),
        argparse.Namespace(catalog_only=True),
        record,
        None,
        store,
        discovery,
        targets=[],
        need_catalog=True,
        catalog_age=None,
        year_label='תשפ"ו',
        year_greg="2026",
        semester="",
        delay_s=0,
    )
    assert outcome == refresh.PASS_CATALOG_ONLY
    return record


def test_buttons_without_rows_report_a_structure_change(capsys):
    # המבנה הבא שאיננו מכירים: אותם כפתורים, שורות בלי class ``row``.
    html = _read("catalog_rows_article.html").replace(
        '<article class="row">', '<li class="item">'
    ).replace("</article>", "</li>")
    record = _run_catalog_pass(html)
    out = capsys.readouterr().out
    assert "the yedion page structure changed (4 course buttons, 0 parsed rows)" in out
    assert "חזר ריק" not in out
    assert record["catalog"]["warnings"][-1].startswith(
        "the yedion page structure changed (4 course buttons, 0 parsed rows)"
    )


def test_page_without_buttons_is_still_reported_empty(capsys):
    record = _run_catalog_pass('<html><body><h2>שנה"ל תשפ"ו</h2></body></html>')
    out = capsys.readouterr().out
    assert "הקטלוג חזר ריק" in out
    assert "structure changed" not in out
    assert record["catalog"]["warnings"][-1] == "empty catalog page; kept previous"
