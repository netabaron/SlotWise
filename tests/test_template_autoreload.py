"""תבנית שהשתנתה על הדיסק מגיעה למסך בלי להפעיל את השרת מחדש.

למה הקובץ הזה קיים
-------------------
ב-2026-09-08 דווח ששלושה שינויים בכותרת "לא בוצעו". הם בוצעו, נבדקו
ונדחפו — אבל השרת שרץ אצל המשתמש/ת הופעל ב-2026-09-05, ו-``auto_reload``
של Jinja נגזר כברירת מחדל מ-``app.debug``. שרת רגיל מהדר את ``index.html``
פעם אחת וחי איתה עד שהוא נסגר.

מה שהפך את זה למטעה במיוחד: ``style.css`` הוא קובץ **סטטי**, שנקרא מהדיסק
בכל בקשה. אז שינויי הפלטה כן הופיעו על המסך, ושינויי התבנית לא — מה
שנראה בדיוק כמו "חלק מהשינויים בוצעו וחלק לא", ולא כמו מטמון. ``Ctrl+F5``
אינו עוזר: הדפדפן אכן מבקש את הדף מחדש, והשרת מחזיר את אותו עותק מזיכרון.

זהו אותו סוג תקלה כמו ה-``_CACHE`` של ``strings.py`` (ראו DEFERRED.md),
שנסגר שם בבדיקת mtime. כאן Jinja עושה את הבדיקה בעצמו — ברגע שהדגל דלוק.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src.web.api import create_app  # noqa: E402

TEMPLATES = ROOT / "src" / "web" / "templates"
#: שם מפורש וזמני. נמחק ב-finally, ומתחיל בקו תחתון כמו ``_probe.txt`` שכבר שם.
PROBE = TEMPLATES / "_autoreload_probe.html"


def test_a_changed_template_is_re_read_without_a_restart():
    """הבדיקה האמיתית: אותו יישום, קובץ ששונה, תוכן חדש.

    ‏mtime נדחף קדימה במפורש — שתי כתיבות באותה שנייה עלולות להיראות
    ל-Jinja כאותו קובץ, ואז הבדיקה הייתה עוברת גם עם ‎auto_reload‎ כבוי.
    """
    app = create_app(config={"allow_network": False})
    try:
        PROBE.write_text("first", encoding="utf-8")
        with app.app_context():
            assert app.jinja_env.get_template(PROBE.name).render() == "first"

        PROBE.write_text("second", encoding="utf-8")
        future = os.path.getmtime(PROBE) + 10
        os.utime(PROBE, (future, future))

        with app.app_context():
            got = app.jinja_env.get_template(PROBE.name).render()
        assert got == "second", (
            "התבנית לא נקראה מחדש — שרת שרץ ימשיך להגיש את הגרסה שהייתה "
            "בזמן ההפעלה, ושינוי בתבנית ייראה כאילו לא בוצע"
        )
    finally:
        if PROBE.exists():
            PROBE.unlink()


def test_the_flag_is_set_on_both_places_that_matter():
    """‏app.config הוא מה שמתועד; ‏jinja_env.auto_reload הוא מה שפועל.

    ‏Flask מסנכרן ביניהם, אבל רק כשהוא בונה את הסביבה. הקוד קובע את
    שניהם במפורש כדי שסדר האתחול לא יהיה חלק מההסכם.
    """
    app = create_app(config={"allow_network": False})
    assert app.config["TEMPLATES_AUTO_RELOAD"] is True
    assert app.jinja_env.auto_reload is True, (
        "‏auto_reload כבוי — זהו הדגל שקובע בפועל, ובלעדיו app.config לבדו "
        "אינו מספיק"
    )


def test_it_does_not_depend_on_debug_mode():
    """‏ברירת המחדל של Jinja נגזרת מ-app.debug, וזו בדיוק המלכודת.

    השרת של הסטודנט/ית רץ בלי ‎--debug‎, ולכן בדיקה שרצה במצב ניפוי הייתה
    עוברת בזמן שהמצב האמיתי שבור.
    """
    app = create_app(config={"allow_network": False})
    assert not app.debug, "הבדיקה חייבת לרוץ במצב שאינו ניפוי כדי להיות בעלת ערך"
    assert app.jinja_env.auto_reload is True
