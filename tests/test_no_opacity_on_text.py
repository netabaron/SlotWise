"""‏opacity על טקסט הוא כישלון ניגודיות שאף פלטה לא מתקנת.

למה הקובץ הזה קיים
-------------------
עד 2026-09-08 שנים־עשר כללים החווירו טקסט אמיתי במכפיל שקיפות. המדידה,
מול שלוש הפלטות שנשקלו לשלב 10, נתנה 2.14–2.29:1 בטבלת ההשוואה,
2.38–2.62:1 בשורת מרצה חסומה, ו-4.13–4.92:1 על קוד חדר — כולם מתחת ל-4.5
של ‏WCAG AA, ושורות הבלוק ‏(4.98–5.42:1) מתחת לרף 7:1 שהפרויקט מצהיר
עליו בעצמו.

‏opacity פועל **אחרי** שהצבע נבחר, ולכן שום ערך טוקן אינו מציל אותו:
המכפיל מערבב את הטקסט עם מה שמאחוריו ומוריד את היחס באותה מידה בכל
פלטה. התיקון הוא ‎color: var(--muted)‎ בשקיפות מלאה — אותה נסיגה
ויזואלית, בלי המחיר.

הבדיקה כאן היא רשימת היתר: מי שמוסיף ‎opacity‎ חדש חייב להצדיק אותו כאן.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "src" / "web" / "static" / "style.css").read_text(encoding="utf-8")

#: ‏השימושים המותרים ב-opacity, וההצדקה של כל אחד.
#: ‏WCAG 1.4.3 פוטר מפורשות "רכיב ממשק לא פעיל", ושבב צבע אינו טקסט.
ALLOWED: dict[str, str] = {
    ".btn:disabled":
        "רכיב ממשק לא פעיל — פטור מפורש ב-WCAG 1.4.3",
    ".banner-close":
        "כפתור סגירה, אייקון ולא טקסט; מגיע ל-1 ב-hover",
    ".banner-close:hover":
        "מצב hover של אותו כפתור",
    ".step.is-locked":
        "שלב נעול — רכיב לא פעיל",
    ".legend-swatch--dead":
        "שבב צבע במקרא, לא טקסט; לצדו תווית מילולית",
    ".pin-btn":
        "פקד הנעיצה. שלב 7 מחליף אותו ב-SVG עם aria-label ומבטל את השאלה",
    ".pin-btn:hover:not(:disabled)":
        "מצב hover של פקד הנעיצה",
    ".pin-btn[aria-pressed=\"true\"]":
        "מצב נעוץ של פקד הנעיצה",
    ".pin-btn:disabled":
        "פקד לא פעיל",
    ".busy-bar > span":
        "אנימציה מושבתת תחת prefers-reduced-motion, לא טקסט",
}


def _rules_with_opacity() -> list[tuple[str, str]]:
    """‏[(סלקטור, ערך)] לכל כלל שמכיל opacity קטן מ-1, בלי @keyframes."""
    without_frames = re.sub(r"@keyframes[^{]*\{(?:[^{}]|\{[^{}]*\})*\}", "", CSS)
    without_comments = re.sub(r"/\*.*?\*/", "", without_frames, flags=re.S)
    found = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", without_comments):
        selector, body = match.group(1).strip(), match.group(2)
        for value in re.findall(r"(?<![-\w])opacity:\s*([^;]+);", body):
            value = value.strip()
            if value.split()[0] in ("1", "1.0"):
                continue
            for part in selector.split(","):
                part = part.strip()
                if part and not part.startswith("@"):
                    found.append((part, value))
    return found


def test_every_opacity_is_on_the_allowlist():
    offenders = [
        f"{sel} -> opacity: {val}"
        for sel, val in _rules_with_opacity()
        if sel not in ALLOWED
    ]
    assert not offenders, (
        "‏opacity חדש על טקסט. אם זה באמת רכיב לא פעיל או שבב צבע — "
        "הוסיפו אותו ל-ALLOWED עם נימוק. אחרת השתמשו ב-color: var(--muted).\n"
        + "\n".join(offenders)
    )


def test_the_twelve_repaired_rules_stay_repaired():
    """שנים־עשר הכללים ששוחררו מהמכפיל — כל אחד בשמו."""
    must_not_contain = [
        (".course-item.is-unavailable", "opacity: .55"),
        (".lect-table tbody tr.is-dead > td", "opacity: .4"),
        (".compare-table tr.same th", "opacity: .5"),
        (".hd.is-empty", "opacity: .55"),
        (".detail-code", "opacity: .6"),
        (".ev span", "opacity: .94"),
        (".ev .ev-lect", "opacity: .82"),
        (".fact-hint", "opacity: .85"),
        (".gid-prefix", "opacity: .5"),
        (".banner-more-title", "opacity: .85"),
        (".banner-more-legend", "opacity: .8"),
    ]
    back = [f"{sel} {val}" for sel, val in must_not_contain
            if re.search(rf"{re.escape(sel)}[^{{]*\{{[^}}]*{re.escape(val)}", CSS)]
    assert not back, "חזרו מכפילי שקיפות:\n" + "\n".join(back)


def test_the_print_override_that_only_undid_them_is_gone():
    """כלל שכל תפקידו היה לבטל כלל אחר נמחק יחד איתו.

    ‏ההערה בגוש ההדפסה מספרת שהכלל היה שם, ולכן משמיטים הערות לפני
    הבדיקה — אחרת התיעוד של המחיקה נחשב לכלל שלא נמחק.
    """
    code = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    assert "opacity: 1 !important" not in code
