# -*- coding: utf-8 -*-
"""
‏src/web — שכבת האינטראקציה בדפדפן (the browser interaction layer).

החבילה הזו מחליפה את שכבת השאלות-ותשובות של ה-CLI, ו**רק** אותה. כל השאר
נקרא, לא נכתב מחדש: המנוע (``scheduler``), המסד (``store``), הפרסר
(``parser``), הגורד (``scraper``) ותוכנית הלימודים (``curriculum``).

שימוש::

    from web.api import create_app
    app = create_app()
    app.run(host="127.0.0.1", port=5000)     # לוקאלי בלבד — לעולם לא 0.0.0.0

הערה על ייבוא: כל המודולים בפרויקט מייבאים זה את זה בסגנון שטוח
(``import models``), ולכן ``src/`` חייב להיות ב-``sys.path``. הקובץ
``web/api.py`` דואג לזה בעצמו בזמן הייבוא, כך ש-``from web.api import
create_app`` עובד גם בלי ``main.py``.
"""

from __future__ import annotations

__all__ = ["create_app"]

__version__ = "1.0.0"


def create_app(*args, **kwargs):
    """קיצור דרך ל-:func:`web.api.create_app` (ייבוא עצל, כדי ש-``import web``
    לא יגרור את Flask ואת כל המנוע כשלא צריך אותם)."""
    from .api import create_app as _create_app

    return _create_app(*args, **kwargs)
