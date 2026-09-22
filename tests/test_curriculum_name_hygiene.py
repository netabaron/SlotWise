# -*- coding: utf-8 -*-
"""שם קורס אינו מכיל מספר של קורס אחר.

מה זה שומר עליו
----------------
‏``src/shnaton.py`` משחזר שורת טבלה לפי קואורדינטות: הוא מקבץ מילים לפי ``y``
וממיין לפי ``x`` יורד. בטבלאות שבהן שורה אחת נשברת לשתי שורות ויזואליות —
שם הקורס נמשך לשורה הבאה — הקיבוץ תפס את **חצי השם הראשון** ואחריו את
עמודת "קורסי קדם" של אותה שורה. התוצאה היא שם שנראה כמו שם, ובתוכו מספר
קורס וחצי שם של קורס אחר:

    "ניהול והערכת סיכונים 11001 אלגברה"   במקום   "ניהול והערכת סיכונים בפרויקטים הנדסיים"

זה לא נראה כמו תקלה על המסך, וזה מה שהפך אותו לשקט: הסטודנט/ית קוראים שם
קורס ארוך ומוזר, לא הודעת שגיאה. ‏22 שורות ב-``data/curricula.json`` היו
כאלה — אזרחית, מכונות, תעשייה, תוכנה ומערכות מידע — ותוקנו ב-2026-09-22 מול
עמודת השם שב-PDF.

מה הבדיקה עושה
---------------
סורקת **כל** שורת קורס בכל קובץ תוכנית — חובה ובחירה כאחד — ומחפשת בתוך השם
מספר בן 5–6 ספרות שהוא קוד קורס אמיתי. "אמיתי" = מופיע בקטלוג הקפוא, או
מוצהר כ-``code`` באחד מקובצי התוכנית. מספר שאינו קוד קורס (‏"חדו"א 2",
"אלגברה 1") אינו נתפס, וזו הנקודה: הבדיקה אינה אוסרת ספרות בשם.

הבדיקה היא על **הנתונים**, לא על המחלץ. ‏shnaton.py עצמו לא תוקן — תיקון שלו
ירוץ מחדש על כל הפרקים ויכתוב את כל הקובץ מחדש, וזו החלטה נפרדת. עד אז
הבדיקה כאן היא מה שיתפוס את החזרה של הארטיפקט בחילוץ הבא.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

CURRICULUM = ROOT / "data" / "curriculum.json"
CURRICULA = ROOT / "data" / "curricula.json"
CURRICULA_DIR = ROOT / "data" / "curricula"

#: מספר בן 5–6 ספרות שאינו חלק ממספר ארוך יותר.
CODE_IN_NAME = re.compile(r"(?<!\d)(\d{5,6})(?!\d)")


def _files() -> list[Path]:
    return [CURRICULUM, CURRICULA] + sorted(CURRICULA_DIR.glob("*.json"))


def _rows(path: Path):
    """‏(תיאור מקום, רשומת קורס) לכל שורת קורס בקובץ, בכל צורה שהוא נושא."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if "programs" in data:  # data/curricula.json — פרקי השנתון
        for program, chapter in data["programs"].items():
            for kind in ("clusters", "tracks"):
                for group, items in (chapter.get(kind) or {}).items():
                    for entry in items or []:
                        yield f"{path.name} · {program} · {kind} · {group}", entry
        return
    for semester, body in (data.get("semesters") or {}).items():
        for entry in body.get("courses") or []:
            yield f"{path.name} · semester {semester}", entry
    for cluster, items in (data.get("elective_clusters") or {}).items():
        for entry in items or []:
            yield f"{path.name} · cluster {cluster}", entry


@pytest.fixture(scope="module")
def known_codes() -> set[str]:
    """הקודים שנחשבים אמיתיים: הקטלוג הקפוא + כל מה שהתוכניות מצהירות."""
    import shipped_catalog

    codes = set(shipped_catalog.courses())
    for path in _files():
        for _where, entry in _rows(path):
            code = str(entry.get("code") or "").strip()
            if code:
                codes.add(code)
    return codes


def test_the_scan_has_something_to_scan():
    """שמירה על הבדיקה עצמה: נתיב שגוי היה הופך אותה לירוקה תמיד."""
    rows = [r for path in _files() for r in _rows(path)]
    assert len(rows) > 900, len(rows)
    assert len({w.split(" · ")[0] for w, _e in rows}) >= 9


def test_known_codes_are_actually_known(known_codes):
    """ובלי זה היא הייתה ירוקה גם כשהקטלוג לא נטען."""
    assert len(known_codes) > 500
    assert "61753" in known_codes


@pytest.mark.parametrize("path", _files(), ids=lambda p: p.name)
def test_no_course_name_carries_another_courses_code(path, known_codes):
    """הארטיפקט של 2026-09-22, בכל קובץ תוכנית, בשורות חובה ובחירה כאחד."""
    bad = []
    for where, entry in _rows(path):
        name = str(entry.get("name") or "")
        own = str(entry.get("code") or "").strip()
        for found in CODE_IN_NAME.findall(name):
            if found in known_codes and found != own:
                bad.append(f"{where}: {own or '(אין קוד)'} — {name!r} מכיל {found}")
    assert bad == [], "שם קורס נושא מספר של קורס אחר:\n" + "\n".join(bad)


def test_a_number_that_is_not_a_course_code_is_left_alone(known_codes):
    """הבדיקה אינה אוסרת ספרות בשם — רק קוד של קורס אחר.

    ‏"חדו"א 1 מ'" ו-"אלגברה 1 מח'" הם שמות תקינים לגמרי, והם בקבצים.
    """
    names = [
        str(e.get("name") or "")
        for path in _files()
        for _w, e in _rows(path)
    ]
    with_digits = [n for n in names if re.search(r"\d", n)]
    assert with_digits, "אין אף שם עם ספרה — הבדיקה הזאת אינה בודקת כלום"
