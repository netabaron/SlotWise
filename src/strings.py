# -*- coding: utf-8 -*-
"""
strings.py — הטוען של ``strings.json``, מקור האמת היחיד לכל נוסח בממשק.

למה זה קיים
------------
עד כאן הנוסחים היו פזורים בשלושה מקומות: מחרוזות בתוך ``app.js``, טקסט
קבוע בתוך ``templates/index.html``, והודעות שנבנות בשרת ומוצגות כמו שהן
(``format_hebrew_age``, סיבות וההצעות של "אין פתרון", אזהרות לכל קורס).
לשנות מילה אחת בממשק חייב לפעול במקום אחד, ולכן כולן יושבות עכשיו
ב-``src/strings.json``.

מי קורא מכאן
-------------
* ``src/web/api.py`` — מזרים את העץ ל-Jinja (טקסט קבוע נכנס ל-HTML כבר
  בשרת, בלי הבהוב) וגם ל-``window.STRINGS`` עבור ``static/app.js``.
* ``src/store.py`` — ``format_hebrew_age`` וחבריו.
* ``src/web/static/app.js`` — דרך ``window.STRINGS``.

הערה על תלויות: הקובץ הזה **לא** מייבא Flask. ``store.py`` נטען גם מ-
``main.py``, ``refresh.py`` ו-``reparse.py`` בלי שרת בכלל, ותלות ב-Flask
הייתה שוברת את כל המסלולים האלה.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

#: הקובץ היחיד שעורכים כדי לשנות נוסח.
STRINGS_PATH = Path(__file__).resolve().parent / "strings.json"

_CACHE: dict[str, Any] | None = None


#: הענפים שחייבים להיות שם. חסר אחד מהם — הקובץ אינו הקובץ שאנחנו חושבים.
REQUIRED_SECTIONS = ("meta", "ui", "server", "app")


def load(refresh: bool = False) -> dict[str, Any]:
    """העץ המלא. נטען פעם אחת ונשמר במטמון.

    ``refresh=True`` קורא מחדש מהדיסק — שימושי בפיתוח, כשמשנים נוסח
    ולא רוצים להפעיל את השרת מחדש.

    עץ ריק או חסר-ענפים הוא **שגיאה**, לא מצב. עמוד שכל הטקסט בו ריק
    נראה כמו עיצוב גרוע ולא כמו תקלה, וכך אפשר לשלוח אותו בלי לשים לב;
    חריגה כאן עוצרת את זה בשרת, במקום להגיע למסך.
    """
    global _CACHE
    if _CACHE is None or refresh:
        with io.open(STRINGS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or not data:
            raise RuntimeError(f"{STRINGS_PATH} ריק או אינו אובייקט JSON")
        missing = [k for k in REQUIRED_SECTIONS if not data.get(k)]
        if missing:
            raise RuntimeError(
                f"{STRINGS_PATH} חסרים בו הענפים: {', '.join(missing)}"
            )
        _CACHE = data
    return _CACHE


def mtime() -> float:
    """חותמת הזמן של קובץ הנוסח, לזיהוי מטמון מיושן בתהליך ארוך־חיים."""
    try:
        return STRINGS_PATH.stat().st_mtime
    except OSError:
        return 0.0


def get(path: str, default: str = "") -> Any:
    """שליפה לפי נתיב מנוקד, למשל ``get("header.loading")``.

    מפתח חסר מחזיר את ``default`` ולא מתפוצץ: נוסח חסר הוא באג בתצוגה,
    ולא סיבה להפיל בקשה שלמה.
    """
    node: Any = load()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def fmt(path: str, **params: Any) -> str:
    """שליפה + הצבה של פרמטרים בסוגריים מסולסלים.

    התבנית נשמרת כמשפט שלם ב-JSON (``"מרענן {count} קורסים…"``) ולא
    כשלושה שברים נפרדים, כדי שמי שעורך נוסח יראה משפט ולא פאזל.
    ההצבה מכוונת ופשוטה — לא ``str.format`` — כדי שסוגריים מסולסלים
    בטקסט עצמו לא יפילו כלום.
    """
    text = get(path, "")
    if not isinstance(text, str):
        return ""
    for key, value in params.items():
        text = text.replace("{" + key + "}", str(value))
    return text
