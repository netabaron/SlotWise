# -*- coding: utf-8 -*-
"""
‏src/web/api.py — שכבת ה-HTTP של SlotWise (the JSON translation layer).

מה הקובץ הזה כן עושה
--------------------
מתרגם בקשות HTTP לקריאות למודולים שכבר עובדים, ומחזיר JSON. זהו.

מה הקובץ הזה **לא** עושה
------------------------
לא מפענח HTML, לא מנקד מערכות, לא מחפש צירופים, לא קורא לידיעון ולא נוגע
בסיסמאות. לכל אלה כבר יש מודול, והוא נקרא — לא משוכפל:

===========================  =========================================
צורך                         מי עושה את זה בפועל
===========================  =========================================
תוכנית לימודים               ``curriculum.load_curriculum`` / ``semester_courses``
                             / ``find_course`` / ``tied_group``
קטלוג חי                     ``store.Store.search_catalog`` / ``load_catalog``
                             + ``discovery.annotate_with_curriculum``
נתוני קבוצות + טריות         ``store.Store.load_course`` / ``course_meta`` / ``freshness``
גרידה + התחברות ידנית        ``refresh.main`` (שקורא ל-``scraper.BraudeScraper``)
פענוח מחדש בלי רשת           ``reparse.main``
מנוע השיבוץ                  ``scheduler.Preferences`` / ``solve``
                             / ``enumerate_selections`` / ``diagnose_infeasibility``
                             / ``relax_suggestions``
מודל הנתונים                 ``models.Course/Group/Meeting/Selection/ScoredSchedule``
===========================  =========================================

כללי ברזל
---------
* ‏127.0.0.1 בלבד. אף פעם לא 0.0.0.0. השרת הזה משרת אדם אחד במחשב אחד.
* אין טיפול בסיסמאות. ההתחברות היא חלון דפדפן אמיתי; ה-API רק *מתחיל*
  אותו ומדווח על ההתקדמות. אין שדה סיסמה, אין קליטה, אין העברה.
* כל תשובה היא JSON. גם תקלה. אף פעם לא דף traceback של Flask.
* "אין פתרון" הוא **תשובה תקינה** ומוחזר ב-200 עם הסברים — לא 5xx.
* כל טקסט מופנה למשתמש/ת הוא עברית ניטרלית מגדרית (צורות מקור: "יש לבחור").
* כל קריאת קובץ עם ``encoding="utf-8"`` — ב-Windows ברירת המחדל היא cp1255.

מוסכמות (מ-``models.py``)
--------------------------
יום: 1=ראשון … 6=שישי. שעה: דקות מחצות (08:30 → 510). חפיפה חצי-פתוחה.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import hashlib
import importlib
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterable

# ---------------------------------------------------------------------------
# 0. נתיבים ו-sys.path
#    כל מודולי הפרויקט מייבאים זה את זה שטוח ("import models"), בדיוק כמו
#    ש-main.py מסדר. הקובץ הזה דואג לזה בעצמו כדי ש-
#    "from web.api import create_app" יעבוד גם בלי main.py.
# ---------------------------------------------------------------------------
_THIS_FILE = Path(__file__).resolve()
SRC_DIR: Path = _THIS_FILE.parents[1]
PROJECT_ROOT: Path = _THIS_FILE.parents[2]

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - צינור/מסוף שאי אפשר להגדיר מחדש, וזה בסדר
        pass

from flask import (  # noqa: E402
    Blueprint,
    Flask,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from werkzeug.exceptions import HTTPException  # noqa: E402

import curriculum as curriculum_mod  # noqa: E402
import discovery as discovery_mod  # noqa: E402
import models  # noqa: E402
import parser as parser_mod  # noqa: E402
import scheduler as scheduler_mod  # noqa: E402
import store as store_mod  # noqa: E402
import strings as strings_mod  # noqa: E402

LOG = logging.getLogger("slotwise.web")

# ---------------------------------------------------------------------------
# 1. קבועים
# ---------------------------------------------------------------------------

#: קוד קורס בבראודה — 4 עד 7 ספרות (11069 בן 5, 251961 בן 6).
CODE_RE = re.compile(r"^\d{4,7}$")

#: תקרת קבוצות שעבורה עוד שווה לחשב viability (‏~1ms לקבוצה).
MAX_VIABILITY_GROUPS = 300

#: כמה מערכות מחזירים כברירת מחדל, וכמה לכל היותר.
DEFAULT_TOP_N = 5
MAX_TOP_N = 50

#: תקרת קורסים בבקשה אחת — גדר נגד בקשה שתתקע את השרת.
MAX_CODES = 20

#: דקות ביממה.
MINUTES_IN_DAY = 24 * 60

#: הסיבה הסטנדרטית לקבוצה שמובילה למבוי סתום.
DEAD_END_REASON = "בחירה זו משאירה את המערכת בלי פתרון"

#: כמה שליפות "על-פי-דרישה" מותרות בבקשה אחת ל-/api/courses.
#: הידיעון פתוח לקריאה בלי התחברות (GROUND_TRUTH §9) — כלומר **שום דבר לא
#: מווסת אותנו חוץ מאיתנו**. תקרה + השהיה הן הנימוס שלנו כלפי שרת הקולג'.
MAX_ONDEMAND_FETCHES = 12

#: השהיה בין בקשות רשות עוקבות, בשניות.
FETCH_DELAY_S = 1.2

#: תקרת זמן לבקשת HTTP אחת.
FETCH_TIMEOUT_S = 45.0

#: חלון הטריות של **פרטי הקורס** (‏S_CourseDetails): שבעה ימים, לא יממה.
#: נ"ז, שעות ותנאי קדם משתנים אחת לשנה בערך, בעוד שהמערכת עצמה משתנה תוך כדי
#: סמסטר. חלון של 24 שעות היה מכפיל את מספר הבקשות לשרת המכללה בשביל נתון
#: שכמעט אינו זז. ‏SPEC_MULTIFACULTY §2.
DETAILS_MAX_AGE_HOURS = 24.0 * 7

#: כמה שליפות **פרטים** מותרות בבקשה אחת. תמיד רק לקורסים שנבחרו בפועל —
#: לעולם לא לכל הקטלוג.
MAX_ONDEMAND_DETAIL_FETCHES = 12

#: כמה פרטי קורס מותר לטעון קוד-קוד כשה-Store אינו חושף טעינה בבת אחת.
#: גדר נגד עמוד עיון שיקרא את אותו קובץ מאתיים פעם.
MAX_DETAILS_LOOKUPS = 64

#: עיון בקטלוג: כמה תוצאות כברירת מחדל וכמה לכל היותר.
DEFAULT_BROWSE_LIMIT = 50
MAX_BROWSE_LIMIT = 200

#: מקורות הנ"ז, לפי סדר העדיפות שב-SPEC_MULTIFACULTY §3.
CREDITS_SOURCE_CURRICULUM = "curriculum"
CREDITS_SOURCE_YEDION = "yedion"
CREDITS_SOURCE_UNKNOWN = "unknown"

#: מה שמוצג במקום נ"ז שאינן ידועות. **לעולם לא 0.0** — מכיוון ש-86% מהקטלוג
#: אינם בתוכנית הלימודים, סכום ששותק עליהם הוא שקר, וסכום שאומר "לא ידוע"
#: הוא תשובה. ‏SPEC_MULTIFACULTY §3.
CREDITS_UNKNOWN_TEXT = "—"

#: מה שאומרים פעם אחת, בפשטות, כשאין תוכנית לימודים טעונה.
CURRICULUM_MISSING_NOTE = (
    "תוכנית הלימודים של המחלקה אינה טעונה — אפשר לבחור כל קורס מהקטלוג"
)

#: כמה שניות מותר למטמון משותף (‏Cloudflare) להחזיק תשובה קריאה-בלבד.
#: ‏חמש דקות: הקטלוג משתנה פעם בלילה לכל היותר, אבל תשובה ישנה ליותר מכך
#: מתחילה לסתור את מה שהכותרת אומרת על תאריך הבנייה.
PUBLIC_CACHE_SECONDS = 300

#: נכסים סטטיים. ‏**שמות הקבצים עדיין בלי חתימה** (‏/static/app.js ולא
#: ‏/static/app.<hash>.js), אבל התבנית מוסיפה ``?v=<גיבוב תוכן>`` — ראו
#: ‏``_asset_version``. זה סוגר את החור שההערה הזאת תיארה כאן עד
#: ‏2026-09-20: פריסה החליפה את התוכן מאחורי אותה כתובת, ומבקר חוזר הריץ
#: ‏JS ישן עד תפוגת המטמון. ‏**זה לא נשאר תיאורטי** — באותו יום מחיקת
#: מפתחות נוסח הצטרפה לזה והכותרת יצאה ריקה אצל מי שכבר היה לו הקובץ.
#:
#: ‏יממה נשארת הפשרה שנבחרה. ‏``immutable`` אפשרי עכשיו מבחינה טכנית, והוא
#: לא נלקח בכוונה: זו החלטת אירוח, והיא שייכת ל-DEPLOY.md ולא לכאן.
STATIC_CACHE_SECONDS = 24 * 60 * 60

#: נקודות הקצה שמותר להגיש ממטמון משותף: ‏GET, קריאה בלבד, ותשובתן זהה לכל
#: מי ששואל. ‏**רשימת היתר ולא רשימת איסור** — ברירת המחדל היא ``no-store``,
#: כדי שנקודת קצה חדשה לא תודלף למטמון רק מפני שאיש לא חשב עליה.
#:
#: ‏``api.bootstrap`` אינו כאן בכוונה: הוא מחזיר את ``data/profile.json``,
#: והוא המועמד הסביר ביותר לצבור תוכן תלוי-משתמש בעתיד.
CACHEABLE_GET_ENDPOINTS: frozenset[str] = frozenset({
    "api.catalog_meta",
    "api.catalog_search",
    "api.catalog_browse",
    "api.semester_courses",
    "api.program_electives",
})

#: למה אין תוכנית לימודים למסלול. ‏"" = יש תוכנית.
#:
#: ‏עד כאן הממשק לא יכול היה להבחין בין "המכללה אינה מפרסמת תוכנית למסלול
#: הזה" לבין "היא כן מפרסמת, אבל לא בצורה שאפשר להציג כרשימה אחת לסמסטר".
#: שתי התשובות היו אותו ``curriculum_available: false`` ואותו נוסח כללי,
#: והסטודנט/ית נפלו לעיון בקטלוג בלי לדעת למה.
CURRICULUM_ABSENCE_NONE = ""
CURRICULUM_ABSENCE_MISSING = "no_curriculum"
CURRICULUM_ABSENCE_NOT_REPRESENTABLE = "not_representable"
#: יש תוכנית, ואפילו יותר מאחת — אבל היא נבחרת לפי מועד הכניסה, ומועד
#: הכניסה עוד לא נבחר. זו אינה היעדר תוכנית אלא שאלה פתוחה, ולכן היא
#: מקבלת ערך משלה: הנוסח מבקש לבחור מועד במקום להציע את הקטלוג.
CURRICULUM_ABSENCE_INTAKE_REQUIRED = "intake_required"

#: מסלולים שהמכללה **כן** מפרסמת להם תוכנית, אבל היא אינה ניתנת לייצוג
#: כרשימה אחת לכל סמסטר — ולכן אין כאן קובץ תוכנית, בכוונה.
#:
#: ‏**ריק כרגע.** מתמטיקה שימושית ישבה כאן עד 2026-09-21: השנתון מדפיס לה
#: את התוכנית פעמיים, אחת לכל מועד כניסה (חורף/אביב), בלי ולו סמסטר אחד
#: משותף. זה לא השתנה — מה שהשתנה הוא שאין צורך לבחור אחת מהן שרירותית:
#: ‏``intakes`` ב-``programs.json`` מציג את שתיהן ונותן לסטודנט/ית לבחור,
#: וכל מועד הוא קובץ תוכנית מלא משלו. המנגנון נשאר למקרה הבא שבו המכללה
#: אכן מפרסמת משהו שאי אפשר להציג כרשימה לסמסטר.
CURRICULUM_ABSENCE_BY_PROGRAM: dict[str, str] = {}

#: מה שאומרים כשהתוכנית טעונה אבל אין בה קורסים לסמסטר שנבחר.
CURRICULUM_EMPTY_SEMESTER_NOTE = (
    "אין קורסים לסמסטר הזה בתוכנית הלימודים — אפשר לבחור כל קורס מהקטלוג"
)

#: הערת ידיעון שמעידה על חובת נוכחות. ‏11069 כותב "חובת הנוכחות בקורס היא
#: מרגע הרישום לקורס" — לכן ה"ה" הידיעה חייבת להיות אופציונלית. "חובה לקחת
#: בצמוד לקורס זה" (61756) הוא **לא** ביטוי של נוכחות ואסור לו להיתפס כאן.
ATTENDANCE_NOTE_RE = re.compile(
    r"חוב[הת]\s*ה?נוכחות|נוכחות\s*ה?חובה|חובה\s*להשתתף|חוב[הת]\s*ה?השתתפות"
)

#: תוויות שנת לימודים (שנה א׳–ד׳) — לשלב 1 בממשק.
YEAR_LABELS: dict[int, str] = {1: "שנה א׳", 2: "שנה ב׳", 3: "שנה ג׳", 4: "שנה ד׳"}

#: תוויות סמסטר.
TERM_LABELS: dict[str, str] = {
    "א": "סמסטר א׳ (חורף)",
    "ב": "סמסטר ב׳ (אביב)",
    "קיץ": "סמסטר קיץ",
}

#: מיפוי שנה עברית → לועזית, לצורך החלפת השנה בידיעון (GROUND_TRUTH §8).
HEBREW_YEAR_TO_GREGORIAN: dict[str, str] = {
    'תשפ"ה': "2025",
    'תשפ"ו': "2026",
    'תשפ"ז': "2027",
    'תשפ"ח': "2028",
    'תשפ"ט': "2029",
}


# ---------------------------------------------------------------------------
# הגדרות מהסביבה — שכבת ברירת המחדל של ``create_app``
#
# ‏עד 2026-09-20 ישבו שתי הפונקציות האלה ב-``wsgi.py``, ולכן
# ‏``SLOTWISE_MAX_AGE_HOURS`` השפיע על התמונה המתארחת אבל לא על ‏``webapp.py``:
# ‏המפעיל המקומי קיבל את ברירות המחדל הקשיחות שהיו כאן. זה היה הבדל בין
# מקומי למתארח שאף אחד לא ביקש — הן קוראות את אותם קבצים, ולכן הן צריכות
# לקרוא גם את אותם משתנים. ‏``wsgi.py`` עדיין דורס את מה שהוא חייב לדרוס
# (‏``allow_network=False``), ודריסה מפורשת ל-``create_app`` תמיד מנצחת.
#
# ‏``SLOTWISE_CATALOG_DIR`` **אינו** כאן ולא יכול להיות: ``shipped_catalog``
# קורא אותו בזמן ייבוא, הרבה לפני ש-``create_app`` נקרא. ראו ‏DEPLOY.md.
# ---------------------------------------------------------------------------
def env_path(name: str, default: Path) -> str:
    """נתיב מהסביבה, או ברירת המחדל שבתוך הפרויקט."""
    raw = str(os.environ.get(name, "") or "").strip()
    return str(Path(raw).expanduser()) if raw else str(default)


def env_float(name: str, default: float) -> float:
    """מספר מהסביבה. **ערך פגום זורק, ולא נופל לברירת מחדל.**

    חלון טריות הוא הגדרת נכונות: ‏``SLOTWISE_MAX_AGE_HOURS=twentyfour``
    שהופך בשקט ל-24.0 הוא בדיוק סוג ברירת המחדל השקטה שגורמת לקטלוג ישן
    להיראות טרי.
    """
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number of hours, got {raw!r}") from exc


# ===========================================================================
# 2. שגיאות ה-API
# ===========================================================================
class ApiError(Exception):
    """תקלה צפויה שהמשתמש/ת אמור/ה לראות — עברית למעלה, טכני בפנים.

    ``status`` הוא קוד ה-HTTP, ``message`` העברית, ו-``detail`` ההסבר הטכני
    (אנגלית). לעולם לא נשלח traceback לדפדפן.
    """

    def __init__(self, status: int, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.status = int(status)
        self.message = str(message)
        self.detail = str(detail)


def _fail(status: int, message: str, detail: str = ""):
    """בונה תשובת שגיאה אחידה: ``{"ok": false, "error": ..., "detail": ...}``."""
    payload = {"ok": False, "error": message, "detail": detail}
    response = jsonify(payload)
    response.status_code = int(status)
    return response


def _ok(payload: dict[str, Any] | None = None, status: int = 200):
    """בונה תשובת הצלחה אחידה: ``{"ok": true, ...}``."""
    body: dict[str, Any] = {"ok": True}
    if payload:
        body.update(payload)
    response = jsonify(body)
    response.status_code = int(status)
    return response


def _endpoint(view: Callable) -> Callable:
    """עוטף handler כך שאף חריגה לא תגיע לדפדפן כדף HTML.

    ``ApiError`` → הקוד והעברית שנבחרו. ``HTTPException`` → JSON באותו קוד.
    כל השאר → 500 עם הודעה עברית כללית, ושורת לוג מלאה בצד השרת (כולל
    ה-traceback) כדי שאפשר יהיה לתקן.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except ApiError as exc:
            LOG.warning("API %s %s -> %d: %s", request.method, request.path, exc.status, exc.detail or exc.message)
            return _fail(exc.status, exc.message, exc.detail)
        except HTTPException as exc:  # 404 / 405 / 413 וכו'
            return _fail(
                exc.code or 500,
                _http_message_he(exc.code or 500),
                f"{type(exc).__name__}: {exc.description}",
            )
        except Exception as exc:  # noqa: BLE001 - רשת ביטחון אחרונה
            LOG.exception("שגיאה לא צפויה ב-%s %s", request.method, request.path)
            return _fail(
                500,
                "אירעה תקלה בלתי צפויה בשרת. הנתונים לא נפגעו — אפשר לנסות שוב, "
                "ואם זה חוזר כדאי להסתכל בחלון הטרמינל שבו רץ השרת.",
                f"{type(exc).__name__}: {exc}",
            )

    return wrapper


def _http_message_he(code: int) -> str:
    """הודעה עברית קצרה לקודי HTTP נפוצים."""
    return {
        400: "הבקשה אינה תקינה.",
        404: "הכתובת המבוקשת אינה קיימת בשרת.",
        405: "שיטת הבקשה אינה נתמכת בכתובת הזו.",
        413: "גוף הבקשה גדול מדי.",
        500: "אירעה תקלה בלתי צפויה בשרת.",
    }.get(int(code), "אירעה תקלה בשרת.")


# ===========================================================================
# 3. סריאליזציה — פונקציות טהורות, נבדקות ישירות
# ===========================================================================
def meeting_to_json(meeting: models.Meeting) -> dict[str, Any]:
    """מפגש בודד → dict. טהורה.

    כוללת גם את שדות התצוגה (אות היום, שעות כטקסט) כדי שה-JS לא יצטרך
    לשכפל את מוסכמות ה-``models``.
    """
    return {
        "day": meeting.day,
        "day_letter": models.DAY_LETTERS_HE.get(meeting.day, "?"),
        "day_name": models.DAY_NAMES_HE.get(meeting.day, ""),
        "start": meeting.start,
        "end": meeting.end,
        "start_text": models.fmt_time(meeting.start),
        "end_text": models.fmt_time(meeting.end),
        "duration": meeting.duration(),
        "room": meeting.room,
        "building": meeting.building,
        "semester": meeting.semester,
    }


def group_to_json(group: models.Group) -> dict[str, Any]:
    """קבוצה אחת → dict. טהורה."""
    meetings = sorted(group.meetings, key=lambda m: (m.day, m.start, m.end))
    return {
        "course_code": group.course_code,
        "group_id": group.group_id,
        "kind": group.kind,
        "lecturer": group.lecturer,
        "note": group.note,
        # ‏שדה נפרד מ-``note`` בכוונה — ראו ההערה ב-``models.Group``.
        "status_note": group.status_note,
        "linked_to": list(group.linked_to),
        "days": sorted(group.days()),
        "total_minutes": group.total_minutes(),
        "meetings": [meeting_to_json(m) for m in meetings],
    }


def _group_sort_key(group: models.Group) -> tuple[int, str]:
    """סדר תצוגה יציב: לפי סוג הרכיב (KIND_ORDER) ואז לפי מספר הקבוצה."""
    try:
        rank = models.KIND_ORDER.index(group.kind)
    except ValueError:
        rank = len(models.KIND_ORDER)
    return (rank, group.group_id)


def course_to_json(course: models.Course, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """קורס וכל קבוצותיו → dict. טהורה.

    ``extra`` ממוזג פנימה כמו שהוא — שם נכנסים שדות ההקשר (טריות, אזהרות,
    האם מוצע השנה) שאינם חלק מהמודל עצמו, וגם ``credits``/``credits_source``
    המוכרעים (``course_facts``) כשהקורא/ת יודע/ת יותר מהמודל.

    ‏``credits`` כאן הוא ``None`` — ולא ‏0.0 — כשאין נ"ז ידועות: ‏0.0 הוא מה
    שהפענוח מחזיר כשלא מצא את השורה, ולהציג אותו כאילו הוא נתון זו שקר קטן
    שמצטבר לסכום שגוי. ‏SPEC_MULTIFACULTY §3.
    """
    groups = sorted(course.groups, key=_group_sort_key)
    resolved, credits_src = _course_credits(course)
    payload: dict[str, Any] = {
        "code": course.code,
        "name": course.name,
        "credits": resolved,
        "credits_source": credits_src,
        "credits_text": credits_text(resolved),
        "tied_with": list(course.tied_with),
        "kinds": course.kinds(),
        "group_count": len(course.groups),
        "lecturers": course.lecturers(),
        "groups": [group_to_json(g) for g in groups],
    }
    if extra:
        payload.update(extra)
    return payload


def _course_credits(course: Any) -> tuple[float | None, str]:
    """הנ"ז המוכרעות של קורס שנבנה, ומקורן — ``(None, "unknown")`` כשאין.

    ‏``_build_courses`` תולה על הקורס את התוצאה של ``resolve_credits``; מי
    שקיבל קורס ממקום אחר (בדיקה, מודול אחר) נופל בחזרה לערך שבמודל, שם
    ‏0.0 פירושו "לא נמצא בדף".
    """
    if course is None:
        return None, CREDITS_SOURCE_UNKNOWN
    if hasattr(course, "credits_resolved"):
        value = getattr(course, "credits_resolved")
        source = str(getattr(course, "credits_source", "") or CREDITS_SOURCE_UNKNOWN)
        return (value if value is None else float(value)), source
    fallback = _known_credits(getattr(course, "credits", None))
    return fallback, (CREDITS_SOURCE_YEDION if fallback is not None else CREDITS_SOURCE_UNKNOWN)


def _course_index(courses: Any) -> dict[str, models.Course]:
    """‏{קוד: Course} מרשימה, ממילון, או מ-None."""
    if not courses:
        return {}
    if isinstance(courses, dict):
        return {str(k): v for k, v in courses.items()}
    return {c.code: c for c in courses}



# ---------------------------------------------------------------------------
# 3א. חפיפות מכוונות (soft conflicts) — הצגה בלבד
#
# ההחלטה *אם* חפיפה מותרת שייכת למנוע (``scheduler.conflict_is_hard``), ואין
# מחליטים עליה כאן מחדש. מה שנעשה כאן הוא לתרגם חפיפה שהמנוע כבר אישר לטקסט
# עברי שאפשר להראות — כי חפיפה שעוברת בשקט היא בדיוק מה שאסור לקרות:
# מוותרים כאן על נוכחות תמורת זמן, וחייבים לראות בדיוק על מה ויתרו.
# ---------------------------------------------------------------------------
def _meeting_text(meeting: models.Meeting) -> str:
    """'יום ד 08:30-10:30' — בלי חדר, לשורת ההסבר."""
    letter = models.DAY_LETTERS_HE.get(meeting.day, "?")
    return f"יום {letter} {models.fmt_time(meeting.start)}-{models.fmt_time(meeting.end)}"


def _group_text(group: models.Group) -> str:
    """הצד של החפיפה כטקסט: קוד, סוג רכיב ומספר קבוצה."""
    return f"{group.course_code} {group.kind} קב' {group.group_id}"


def _overlap_window(
    a: models.Group, b: models.Group
) -> tuple[int, int, int, models.Meeting, models.Meeting] | None:
    """החפיפה המוקדמת ביותר בין שתי קבוצות: ``(יום, התחלה, סוף, מפגש, מפגש)``."""
    best: tuple[int, int, int, models.Meeting, models.Meeting] | None = None
    for first in a.meetings:
        for second in b.meetings:
            if not first.overlaps(second):
                continue
            window = (
                first.day,
                max(first.start, second.start),
                min(first.end, second.end),
                first,
                second,
            )
            if best is None or window[:2] < best[:2]:
                best = window
    return best


def _overlapping_pairs(selection: models.Selection) -> list[tuple[models.Group, models.Group]]:
    """זוגות הקבוצות החופפות בבחירה.

    מעדיף את ``Selection.overlapping_pairs`` (מודל הנתונים), ונופל חזרה לאותה
    השוואה זוגית ש-``Selection.is_feasible`` עושה — כדי שהדיווח יעבוד גם לפני
    שהמתודה נוספה למודל, ולא ישתוק בדיוק כשיש מה לומר.
    """
    method = getattr(selection, "overlapping_pairs", None)
    if callable(method):
        try:
            return [(a, b) for a, b in (method() or [])]
        except Exception:  # noqa: BLE001 - דיווח לא מפיל תשובה
            LOG.exception("Selection.overlapping_pairs נכשל")
    groups = list(selection.groups)
    return [
        (a, b)
        for i, a in enumerate(groups)
        for b in groups[i + 1 :]
        if a.conflicts_with(b)
    ]


def _attendance_required(prefs: Any, group: models.Group) -> bool:
    """האם הרכיב הזה דורש נוכחות. חסר = **כן** (ברירת המחדל הזהירה)."""
    helper = getattr(scheduler_mod, "attendance_required", None)
    if callable(helper):
        try:
            return bool(helper(prefs, group))
        except Exception:  # noqa: BLE001
            pass
    table = getattr(prefs, "attendance", None) or {}
    try:
        return bool(table.get(group.course_code, {}).get(group.kind, True))
    except Exception:  # noqa: BLE001
        return True


def _describe_soft_conflicts(sched: models.ScoredSchedule, prefs: Any) -> list[str]:
    """שורות ההסבר של המנוע, אם הן קיימות. אחרת רשימה ריקה.

    החתימה במנוע היא ``describe_soft_conflicts(selection, prefs)``; שאר הצורות
    נשארות כרשת ביטחון בלבד. ``TypeError``/``AttributeError`` מהניסיון הראשון
    פירושם "צורה לא מתאימה" — ממשיכים לצורה הבאה במקום לוותר על הדיווח.
    """
    fn = getattr(scheduler_mod, "describe_soft_conflicts", None)
    if not callable(fn):
        return []
    for args in ((sched.selection, prefs), (sched, prefs), (sched.selection,), (sched,)):
        try:
            lines = fn(*args)
        except (TypeError, AttributeError):
            continue
        except Exception:  # noqa: BLE001 - דיווח לא מפיל תשובה
            LOG.exception("describe_soft_conflicts נכשל")
            return []
        return [str(line) for line in (lines or [])]
    return []


def _engine_count(name: str, sched: models.ScoredSchedule) -> int | None:
    """קורא מונה חפיפות מהמנוע (``soft_conflicts_of`` וחברו). ``None`` = אין."""
    fn = getattr(scheduler_mod, name, None)
    if callable(fn):
        try:
            return int(fn(sched))
        except Exception:  # noqa: BLE001
            return None
    return None


def _soft_conflict_line(
    a: models.Group, b: models.Group, window: tuple, prefs: Any
) -> str:
    """שורת הסבר עברית לחפיפה אחת — הנוסח מ-SPEC_V2 §2.

    בשימוש רק כשהמנוע לא סיפק ניסוח משלו. זו הצגה, לא לוגיקת שיבוץ.
    """
    meeting_a, meeting_b = window[3], window[4]
    waived = [g for g in (a, b) if not _attendance_required(prefs, g)]
    if waived:
        assumption = " ו-".join(f"{g.course_code} {g.kind}" for g in waived)
        tail = f"— נבחר בהנחה שאין חובת נוכחות ב-{assumption}."
    else:
        tail = "— חפיפה שאושרה במפורש בהגדרות הנוכחות."
    return (
        f"חפיפה מכוונת: {_group_text(a)} ({_meeting_text(meeting_a)})\n"
        f"מול {_group_text(b)} ({_meeting_text(meeting_b)})\n"
        f"{tail}"
    )


def soft_conflicts_to_json(
    sched: models.ScoredSchedule, prefs: Any = None
) -> dict[str, Any]:
    """סיכום החפיפות המכוונות של מערכת אחת: כמה, כמה דקות, ומה בדיוק."""
    detail: list[dict[str, Any]] = []
    minutes = 0
    for a, b in _overlapping_pairs(sched.selection):
        window = _overlap_window(a, b)
        if window is None:  # pragma: no cover - דווח כחופף בלי חפיפה בפועל
            continue
        day, start, end, meeting_a, meeting_b = window
        minutes += max(0, end - start)
        detail.append(
            {
                "day": day,
                "day_letter": models.DAY_LETTERS_HE.get(day, "?"),
                "start": start,
                "end": end,
                "start_text": models.fmt_time(start),
                "end_text": models.fmt_time(end),
                "minutes": max(0, end - start),
                "a": {
                    "code": a.course_code,
                    "kind": a.kind,
                    "group_id": a.group_id,
                    "lecturer": a.lecturer,
                    "text": _group_text(a),
                    "meeting_text": _meeting_text(meeting_a),
                    "attendance_required": _attendance_required(prefs, a),
                },
                "b": {
                    "code": b.course_code,
                    "kind": b.kind,
                    "group_id": b.group_id,
                    "lecturer": b.lecturer,
                    "text": _group_text(b),
                    "meeting_text": _meeting_text(meeting_b),
                    "attendance_required": _attendance_required(prefs, b),
                },
                "text": _soft_conflict_line(a, b, window, prefs),
            }
        )

    report = _describe_soft_conflicts(sched, prefs) if detail else []
    if detail and not report:
        # המנוע לא ניסח — לא משתיקים. מנסחים כאן, לפי SPEC_V2 §2.
        report = [item["text"] for item in detail]

    # התשובה של המנוע קודמת לספירה שלנו — הוא זה שהחליט מה נחשב חפיפה רכה.
    count = _engine_count("soft_conflicts_of", sched)
    if count is None:
        count = getattr(sched, "soft_conflicts", None)
    total_minutes = _engine_count("soft_conflict_minutes_of", sched)
    if total_minutes is None:
        total_minutes = getattr(sched, "soft_conflict_minutes", None)
    return {
        "soft_conflicts": int(count if count is not None else len(detail)),
        "soft_conflict_minutes": int(total_minutes if total_minutes is not None else minutes),
        "soft_conflict_pairs": detail,
        "soft_conflict_report": report,
    }


def schedule_to_json(
    sched: models.ScoredSchedule, courses: Any = None, prefs: Any = None
) -> dict[str, Any]:
    """מערכת מנוקדת → dict. טהורה.

    ``courses`` (רשימה או מילון של ``Course``) משמש רק כדי לצרף שם ונ"ז לכל
    בחירה; בלעדיו השדות האלה יחזרו ריקים, והמבנה נשאר זהה.

    ``prefs`` מוסיף את דיווח החפיפות המכוונות (מי ויתר על נוכחות ולמה); בלעדיו
    הספירה עדיין נכונה, רק בלי שמות הרכיבים שוויתרו.
    """
    index = _course_index(courses)
    picks: list[dict[str, Any]] = []
    for group in sorted(sched.selection.groups, key=lambda g: (g.course_code, _group_sort_key(g))):
        course = index.get(group.course_code)
        picks.append(
            {
                "code": group.course_code,
                "name": course.name if course is not None else "",
                "kind": group.kind,
                "group_id": group.group_id,
                "lecturer": group.lecturer,
                "credits": _course_credits(course)[0],
                "note": group.note,
                "linked_to": list(group.linked_to),
                "meetings": [
                    meeting_to_json(m)
                    for m in sorted(group.meetings, key=lambda m: (m.day, m.start, m.end))
                ],
            }
        )

    days = sorted(sched.selection.days_used())
    # נ"ז נספרות פעם אחת לכל קורס, לא פעם אחת לכל רכיב — ורק כשהן ידועות.
    seen: set[str] = set()
    per_course: list[Any] = []
    for pick in picks:
        if pick["code"] not in seen:
            seen.add(pick["code"])
            per_course.append(pick["credits"])
    summary = credits_summary(per_course)
    credits_total = summary["total"]

    return {
        "score": round(float(sched.score), 4),
        "days_count": int(sched.days_count),
        "days": days,
        "day_letters": [models.DAY_LETTERS_HE.get(d, "?") for d in days],
        "gap_minutes": int(sched.gap_minutes),
        "span_minutes": int(sched.selection.span_minutes()),
        "lecturer_hits": int(sched.lecturer_hits),
        "lecturer_total": int(sched.lecturer_total),
        "breakdown": {k: round(float(v), 4) for k, v in (sched.breakdown or {}).items()},
        # סכום של מה שידוע בלבד, ולצידו כמה קורסים לא נספרו ולמה.
        "credits": credits_total,
        "credits_summary": summary,
        "credits_unknown": summary["unknown"],
        "credits_complete": summary["complete"],
        "credits_text": summary["text"],
        "truncated": bool(getattr(sched, "truncated", False)),
        "summary": sched.summary(),
        "picks": picks,
        # חפיפה מכוונת חייבת להיראות. אף פעם לא בשקט.
        **soft_conflicts_to_json(sched, prefs),
    }


# ===========================================================================
# 4. קריאה ואימות של גוף הבקשה
# ===========================================================================
def _read_body(required: bool = True) -> dict[str, Any]:
    """גוף הבקשה כ-dict, או ``ApiError`` 400 עם הודעה עברית.

    * גוף ריק לגמרי — שגיאה כש-``required``, ואחרת ``{}`` (כל השדות אופציונליים).
    * גוף שאינו JSON תקין — תמיד שגיאה, גם כשלא חובה. עדיף להגיד "לא הבנתי"
      מאשר להתעלם בשקט ממה שהמשתמש/ת התכוון/ה לשלוח.
    """
    try:
        raw = request.get_data(cache=True) or b""
    except Exception as exc:  # noqa: BLE001
        raise ApiError(400, "לא ניתן לקרוא את גוף הבקשה.", f"{type(exc).__name__}: {exc}") from exc

    if not raw.strip():
        if required:
            raise ApiError(
                400,
                "לא התקבל גוף בקשה. יש לשלוח אובייקט JSON עם הפרטים.",
                "empty request body",
            )
        return {}

    data = request.get_json(silent=True, force=True)
    if data is None:
        raise ApiError(
            400,
            "גוף הבקשה אינו JSON תקין. יש לשלוח אובייקט JSON.",
            "malformed JSON body",
        )
    if not isinstance(data, dict):
        raise ApiError(
            400,
            "גוף הבקשה חייב להיות אובייקט JSON (מילון), לא רשימה או ערך בודד.",
            f"expected a JSON object, got {type(data).__name__}",
        )
    return data


def clean_code(value: Any, *, field: str = "code") -> str:
    """מאמת קוד קורס: מחרוזת של 4–7 ספרות. אחרת ``ApiError`` 400."""
    text = str(value if value is not None else "").strip()
    if not CODE_RE.match(text):
        raise ApiError(
            400,
            f"קוד קורס אינו תקין: {text or '(ריק)'}. קוד קורס הוא מספר בן 4 עד 7 ספרות.",
            f"invalid course code in {field!r}: {value!r}",
        )
    return text


def _day_relaxations_json(courses: list, prefs: Any, target_days: int) -> dict[str, Any]:
    """אילו ויתורים על קורסים יפתחו את יעד הימים.

    ‏``checked`` הם אלה שנמדדו ואינם פותחים — "בדקנו את כולם" הוא מה
    שהופך "אף ויתור בודד אינו מספיק" לדיווח ולא להתחמקות.
    """
    try:
        report = scheduler_mod.day_relaxations(courses, prefs, target_days)
    except Exception as exc:  # noqa: BLE001 - אבחון לא מפיל תשובה
        LOG.exception("day_relaxations נכשל")
        return {"items": [], "checked": [], "error": str(exc)}

    def one(o: Any) -> dict[str, Any]:
        return {
            "codes": list(o.codes),
            "names": list(o.names),
            "credits": o.credits,
            # ‏None נשאר null: חיפוש שלא הסתיים אינו מספר.
            "min_days": o.min_days,
            "schedules": o.schedules,
        }

    return {
        "items": [one(o) for o in report.helpful()],
        "checked": [one(o) for o in report.measured_useless()],
        "target": report.target,
    }


def _relaxation_json(item: Any) -> dict[str, Any]:
    """ויתור אחד, בצורה שהלקוח מרנדר ממנה משפט."""
    return {
        "kind": item.kind,
        "detail": dict(item.detail or {}),
        "apply": dict(item.apply or {}),
        # ‏None עובר כ-null ונשאר null: "לא נמדד" אינו 0, ואסור שהממשק
        # יציג מספר על חיפוש שלא הסתיים.
        "schedules": item.schedules,
        "cost": dict(item.cost or {}),
        "combines_with": dict(item.combines_with) if item.combines_with else None,
    }


def _relaxations_json(courses: list, prefs: Any) -> dict[str, Any]:
    """‏{"items": [...], "pairs_only": bool, "checked": [...]}.

    ``checked`` הם הוויתורים שנמדדו במפורש כלא-עוזרים. הם נשלחים בכוונה:
    "בדקנו כל אחד לחוד ואף אחד לא פותר" הוא מה שהופך את "שילוב של שניים
    כן" למשפט שאפשר להבין.
    """
    try:
        report = scheduler_mod.relaxations(courses, prefs)
    except Exception as exc:  # noqa: BLE001 - אבחון לא מפיל תשובה
        LOG.exception("relaxations נכשל")
        return {"items": [], "pairs_only": False, "checked": [], "error": str(exc)}
    return {
        "items": [_relaxation_json(r) for r in report.best()],
        "pairs_only": bool(report.pairs_only),
        "checked": [_relaxation_json(r) for r in report.measured_useless()],
    }


def _origin_of(meta: Any) -> str:
    """מאיפה הרשומה הגיעה: ``"shipped"`` או ``"db"``.

    ‏``shipped_catalog`` מסמן את הרשומות שלו ב-``source_url`` קבוע, ולכן
    אין צורך לנחש לפי היעדר שדות.
    """
    try:
        from shipped_catalog import SHIPPED_SOURCE  # type: ignore
    except Exception:  # noqa: BLE001
        return "db"
    return "shipped" if getattr(meta, "source_url", "") == SHIPPED_SOURCE else "db"


def _clean_codes(value: Any, *, field: str = "codes", allow_empty: bool = False) -> list[str]:
    """רשימת קודים מאומתת, בלי כפילויות, בסדר שהתקבל."""
    if value is None:
        items: list[Any] = []
    elif isinstance(value, str):
        items = [part for part in re.split(r"[,\s]+", value) if part]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise ApiError(
            400,
            "רשימת הקורסים אינה בפורמט הנכון — יש לשלוח רשימה של קודים.",
            f"{field}: expected a list of codes, got {type(value).__name__}",
        )

    if len(items) > MAX_CODES:
        raise ApiError(
            400,
            f"נשלחו יותר מדי קורסים בבקשה אחת ({len(items)}). המקסימום הוא {MAX_CODES}.",
            f"{field}: too many codes ({len(items)})",
        )

    out: list[str] = []
    for item in items:
        code = clean_code(item, field=field)
        if code not in out:
            out.append(code)
    if not out and not allow_empty:
        raise ApiError(
            400,
            "יש לבחור לפחות קורס אחד.",
            f"{field}: empty course list",
        )
    return out


def _as_int(value: Any, *, field: str, default: int | None = None,
            low: int | None = None, high: int | None = None) -> int:
    """מספר שלם מאומת, עם טווח."""
    if value is None or value == "":
        if default is None:
            raise ApiError(400, f"חסר ערך בשדה {field}.", f"{field}: missing")
        return int(default)
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ApiError(
            400, f"הערך בשדה {field} אינו מספר תקין.", f"{field}: not an int ({value!r})"
        ) from exc
    if low is not None and number < low:
        raise ApiError(
            400, f"הערך בשדה {field} קטן מהמותר ({low}).", f"{field}={number} < {low}"
        )
    if high is not None and number > high:
        raise ApiError(
            400, f"הערך בשדה {field} גדול מהמותר ({high}).", f"{field}={number} > {high}"
        )
    return number


def _as_minutes(value: Any, *, field: str, default: int) -> int:
    """שעה כדקות מחצות. מקבל 510, ‏"08:30", ‏"8:30" או ``None``."""
    if value is None or value == "":
        return int(default)
    if isinstance(value, bool):
        raise ApiError(400, f"הערך בשדה {field} אינו שעה תקינה.", f"{field}: bool")
    if isinstance(value, (int, float)):
        minutes = int(value)
    else:
        text = str(value).strip()
        match = re.match(r"^(\d{1,2})[:.](\d{2})$", text)
        if match:
            minutes = int(match.group(1)) * 60 + int(match.group(2))
        elif text.isdigit():
            minutes = int(text)
        else:
            raise ApiError(
                400,
                f"הערך בשדה {field} אינו שעה תקינה. יש לשלוח דקות מחצות (510) או HH:MM.",
                f"{field}: cannot parse {value!r}",
            )
    if not 0 <= minutes <= MINUTES_IN_DAY:
        raise ApiError(
            400,
            f"השעה בשדה {field} חורגת מהיממה.",
            f"{field}={minutes} out of range",
        )
    return minutes


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "כן"}


def _clean_blocked(value: Any) -> list[tuple[int, int, int]]:
    """‏[[יום, התחלה, סוף], ...] → רשימת שלשות מאומתת."""
    if value in (None, ""):
        return []
    if not isinstance(value, (list, tuple)):
        raise ApiError(
            400,
            "רשימת החלונות החסומים אינה בפורמט הנכון.",
            f"blocked: expected a list, got {type(value).__name__}",
        )
    windows: list[tuple[int, int, int]] = []
    for i, item in enumerate(value):
        if isinstance(item, dict):
            day, start, end = item.get("day"), item.get("start"), item.get("end")
        elif isinstance(item, (list, tuple)) and len(item) == 3:
            day, start, end = item
        else:
            raise ApiError(
                400,
                "כל חלון חסום צריך להיות [יום, שעת התחלה, שעת סיום].",
                f"blocked[{i}]: bad shape {item!r}",
            )
        day_i = _as_int(day, field=f"blocked[{i}].day", low=1, high=6)
        start_i = _as_minutes(start, field=f"blocked[{i}].start", default=0)
        end_i = _as_minutes(end, field=f"blocked[{i}].end", default=0)
        if start_i >= end_i:
            raise ApiError(
                400,
                "בחלון חסום, שעת הסיום חייבת להיות אחרי שעת ההתחלה.",
                f"blocked[{i}]: start {start_i} >= end {end_i}",
            )
        windows.append((day_i, start_i, end_i))
    return windows


def _clean_ranked(value: Any) -> dict[str, list[str]]:
    """‏{קוד: [מרצה, ...]} — דירוג המרצים לפי סדר העדפה."""
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ApiError(
            400,
            "דירוג המרצים אינו בפורמט הנכון.",
            f"ranked: expected an object, got {type(value).__name__}",
        )
    out: dict[str, list[str]] = {}
    for raw_code, names in value.items():
        code = clean_code(raw_code, field="ranked")
        if names in (None, ""):
            continue
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, (list, tuple)):
            raise ApiError(
                400,
                "דירוג המרצים של כל קורס צריך להיות רשימת שמות.",
                f"ranked[{code}]: expected a list, got {type(names).__name__}",
            )
        cleaned = [str(n).strip() for n in names if str(n).strip()]
        if cleaned:
            out[code] = cleaned
    return out


def _clean_pinned(value: Any) -> dict[str, dict[str, str]]:
    """‏{קוד: {סוג רכיב: מספר קבוצה}} — הנעיצות שהמשתמש/ת ביקש/ה."""
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ApiError(
            400,
            "רשימת הנעיצות אינה בפורמט הנכון.",
            f"pinned: expected an object, got {type(value).__name__}",
        )
    out: dict[str, dict[str, str]] = {}
    for raw_code, by_kind in value.items():
        code = clean_code(raw_code, field="pinned")
        if by_kind in (None, ""):
            continue
        if not isinstance(by_kind, dict):
            raise ApiError(
                400,
                "הנעיצות של כל קורס צריכות להיות מילון של {סוג השיעור: מספר קבוצה} — "
                "למשל {הרצאה: 271060310}.",
                f"pinned[{code}]: expected an object, got {type(by_kind).__name__}",
            )
        for raw_kind, group_id in by_kind.items():
            kind = str(raw_kind).strip()
            gid = str(group_id).strip() if group_id is not None else ""
            if not kind or not gid:
                continue  # נעיצה ריקה = "בלי נעיצה", לא שגיאה
            out.setdefault(code, {})[kind] = gid
    return out


def _clean_weights(value: Any) -> dict[str, float]:
    """משקולות הניקוד, ממוזגות מעל ברירת המחדל של המנוע."""
    weights = dict(scheduler_mod.DEFAULT_WEIGHTS)
    if value in (None, ""):
        return weights
    if not isinstance(value, dict):
        raise ApiError(
            400, "המשקולות אינן בפורמט הנכון.", f"weights: got {type(value).__name__}"
        )
    for key in weights:
        if key in value and value[key] is not None:
            try:
                weights[key] = float(value[key])
            except (TypeError, ValueError) as exc:
                raise ApiError(
                    400,
                    f"המשקל בשדה weights.{key} אינו מספר.",
                    f"weights.{key}: {value[key]!r}",
                ) from exc
    return weights


def _clean_attendance(value: Any) -> dict[str, dict[str, bool]]:
    """‏{קוד: {סוג רכיב: האם נדרשת נוכחות}} — מה שהמשתמש/ת סימנ/ה בפועל.

    מה ש**לא** נשלח פשוט חסר, ומשמעותו "נוכחות חובה" — ברירת המחדל הזהירה
    שמשאירה את ההתנהגות הקיימת בדיוק כפי שהייתה. ויתור על נוכחות הוא תמיד
    בחירה מפורשת, אף פעם לא תוצר לוואי.
    """
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ApiError(
            400,
            "הגדרות הנוכחות אינן בפורמט הנכון.",
            f"attendance: expected an object, got {type(value).__name__}",
        )
    out: dict[str, dict[str, bool]] = {}
    for raw_code, by_kind in value.items():
        code = clean_code(raw_code, field="attendance")
        if by_kind in (None, ""):
            continue
        if not isinstance(by_kind, dict):
            raise ApiError(
                400,
                "הגדרות הנוכחות של כל קורס צריכות להיות מילון של "
                "{סוג השיעור: כן/לא} — למשל {הרצאה: כן}.",
                f"attendance[{code}]: expected an object, got {type(by_kind).__name__}",
            )
        for raw_kind, flag in by_kind.items():
            kind = str(raw_kind).strip()
            if not kind:
                continue
            if isinstance(flag, (dict, list, tuple)):
                raise ApiError(
                    400,
                    f"הערך של {kind} בקורס {code} צריך להיות כן או לא.",
                    f"attendance[{code}][{kind}]: {type(flag).__name__}",
                )
            out.setdefault(code, {})[kind] = _as_bool(flag, True)
    return out


def _engine_supports(field_name: str) -> bool:
    """האם ל-``scheduler.Preferences`` יש את השדה הזה בגרסה שמותקנת בפועל."""
    try:
        return field_name in {f.name for f in dataclasses.fields(scheduler_mod.Preferences)}
    except TypeError:  # pragma: no cover - לא dataclass
        return False


def _make_preferences(**kwargs: Any) -> tuple[scheduler_mod.Preferences, list[str]]:
    """בונה ``Preferences`` ומעביר רק שדות שקיימים בו בפועל.

    ``scheduler.py`` הוא קובץ של סוכן אחר. אם ``attendance`` /
    ``allow_soft_conflicts`` עדיין לא נוספו שם, עדיף לבנות העדפות תקינות
    ולדווח ללקוח ש"התכונה אינה זמינה" מאשר להפיל את כל המסך ב-500.

    Returns:
        ``(prefs, unsupported)`` — ``unsupported`` הם השדות שהושמטו.
    """
    try:
        known = {f.name for f in dataclasses.fields(scheduler_mod.Preferences)}
    except TypeError:  # pragma: no cover - לא dataclass
        known = set(kwargs)
    unsupported = sorted(name for name in kwargs if name not in known)
    prefs = scheduler_mod.Preferences(
        **{name: val for name, val in kwargs.items() if name in known}
    )
    return prefs, unsupported


def _yedion_attendance_note(course: models.Course, kind: str) -> str:
    """הערת הידיעון שממנה משתמע שיש חובת נוכחות ברכיב הזה, אם יש כזו.

    ‏11069 כותב "חובת הנוכחות בקורס היא מרגע הרישום לקורס" — זה מקור אמיתי,
    ולכן הממשק צריך לדעת להגיד "כך כתוב בידיעון" ולא רק "ברירת מחדל".
    """
    for group in course.groups_of(kind):
        note = str(group.note or "").strip()
        if note and ATTENDANCE_NOTE_RE.search(note):
            return note
    return ""


def attendance_info(
    courses: list[models.Course], requested: dict[str, dict[str, bool]] | None = None
) -> dict[str, dict[str, dict[str, Any]]]:
    """‏{קוד: {סוג רכיב: מצב הנוכחות}} — ברירת המחדל, המקור שלה, והבחירה בפועל.

    לכל (קורס, סוג רכיב):
        ``default``   — תמיד ``True``. ויתור על נוכחות הוא בחירה, לא ברירת מחדל.
        ``from_yedion`` — האם הידיעון עצמו כותב שיש חובת נוכחות.
        ``note``      — הערת הידיעון עצמה, כדי שאפשר יהיה לצטט אותה.
        ``required``  — מה נשלח למנוע בפועל (הבחירה גוברת על ברירת המחדל).
        ``source``    — ``"user"`` / ``"yedion"`` / ``"default"``.
    """
    picked = requested or {}
    info: dict[str, dict[str, dict[str, Any]]] = {}
    for course in courses:
        for kind in course.kinds():
            note = _yedion_attendance_note(course, kind)
            from_yedion = bool(note)
            chosen = (picked.get(course.code) or {}).get(kind)
            required = True if chosen is None else bool(chosen)
            if chosen is not None:
                source = "user"
                text = (
                    "סומן ידנית כחובת נוכחות."
                    if required
                    else "סומן ידנית כרכיב ללא חובת נוכחות."
                )
            elif from_yedion:
                source = "yedion"
                text = f"הידיעון כותב שיש חובת נוכחות: {note}"
            else:
                source = "default"
                text = (
                    "ברירת מחדל: נוכחות חובה. אפשר לסמן אחרת אם ידוע שאין "
                    "חובת נוכחות ברכיב הזה."
                )
            info.setdefault(course.code, {})[kind] = {
                "kind": kind,
                "required": required,
                "default": True,
                "from_yedion": from_yedion,
                "note": note,
                "source": source,
                "text": text,
            }
    return info



# ===========================================================================
# 5. גישה למודולים הקיימים (קאש קל, בלי לוגיקה משלנו)
# ===========================================================================
def _config() -> dict[str, Any]:
    from flask import current_app

    return current_app.config["SLOTWISE"]


def _asset_version(name: str) -> str:
    """‏גיבוב קצר של תוכן קובץ סטטי, ל-``?v=`` שבתבנית.

    ‏**מה זה מתקן.** ‏``/static/app.js`` הוא כתובת קבועה בלי חתימה בשם,
    ‏והיא מוגשת עם ``max-age=86400``. ‏``index.html`` לעומת זאת הוא
    ‏``no-cache``, ו-``window.STRINGS`` מוטבע **בתוכו**. כלומר מבקר חוזר
    קיבל נוסח מהיום ו-JavaScript מאתמול, עד יממה שלמה.
    ‏ב-2026-09-20 זה הפיל את שורת הטריות לגמרי: ה-JS הישן ביקש
    ‏``app.header.builtAt``, המפתח נמחק באותו יום, ‏``T()`` מחזיר מחרוזת
    ריקה כשאין מפתח (מחוץ ל-‎?debug=1‎) — והכותרת יצאה **ריקה**, ליד נקודה
    אפורה. שוחזר בדפדפן אמיתי: ‏``missingStrings()`` החזיר בדיוק את שלושת
    המפתחות שנמחקו, ובלי שום שגיאת JavaScript.
    ‏ההערה שליד ``STATIC_CACHE_SECONDS`` תיארה את הסיכון הזה מראש; מה
    שהוסיף לו שיניים היה מחיקת מפתחות נוסח.

    ‏הגיבוב הופך את הכתובת לתלוית תוכן, ולכן פריסה חדשה **אינה יכולה**
    להיות מצומדת ל-JS ישן: הכתובת השתנתה, והדפדפן חייב למשוך. הקובץ עצמו
    עדיין ב-``/static/app.js`` — ‏``?v=`` בלבד — כדי שכל מה שמפנה לנתיב
    הזה (בדיקות, ‏DEPLOY.md, ‏curl) ימשיך לעבוד.

    ‏המטמון יושב ב-``app.extensions`` ולא במשתנה ברמת המודול, כמו
    ‏``_store()``: ‏HOSTING_NOTES.md §4 אוסר להוסיף גלובלים חדשים. הוא
    מתבטל לפי ``(mtime_ns, size)``, ולכן עריכה בזמן ששרת פיתוח רץ נקראת
    מחדש — אותה סיבה בדיוק שבגללה ``TEMPLATES_AUTO_RELOAD`` דלוק.
    """
    from flask import current_app

    folder = current_app.static_folder or ""
    if not folder:
        return "0"
    path = Path(folder) / name
    try:
        info = path.stat()
    except OSError:
        # קובץ חסר אינו מפיל את הדף. ‏404 על נכס הוא תקלה שרואים, ותווית
        # גרסה מומצאת רק הייתה מסתירה אותה.
        return "0"

    key = (info.st_mtime_ns, info.st_size)
    cache = current_app.extensions.setdefault("slotwise", {}).setdefault("asset_v", {})
    hit = cache.get(name)
    if hit is not None and hit[0] == key:
        return hit[1]
    try:
        digest = hashlib.sha1(path.read_bytes()).hexdigest()[:10]
    except OSError:  # pragma: no cover - נקרא בהצלחה שורה אחת קודם
        return "0"
    cache[name] = (key, digest)
    return digest


def _store() -> store_mod.Store:
    """מופע ``Store`` יחיד לכל אפליקציה. הקריאות עצמן חסרות מצב."""
    from flask import current_app

    cache = current_app.extensions.setdefault("slotwise", {})
    obj = cache.get("store")
    if obj is None:
        # ‏use_shipped: רק כאן. זו שכבת התצוגה, וכאן רוצים שמשתמש/ת
        # יראו קטלוג מלא גם בשכפול נקי. ‏refresh/reparse משאירים כבוי.
        #
        # ‏prefer_newer_catalog: גם הוא רק כאן, ומאותו סוג בדיוק — מדיניות
        # של מה שמוצג, לא של מה שנשמר. בלעדיו רשומה מקומית בת שבועיים
        # ממשיכה לדרוס קטלוג שנבנה אתמול, ואז ``git pull`` אינו מרענן
        # אפליקציה מקומית והכותרת מדווחת את התאריך הישן. ראו
        # ``Store._load_sections_db``.
        obj = store_mod.Store(
            str(_config()["db_root"]), use_shipped=True, prefer_newer_catalog=True
        )
        cache["store"] = obj
    return obj


def _store_for(semester: str) -> store_mod.Store:
    """‏Store שמסנן את הקטלוג שנשלח לסמסטר מבוקש.

    מופע לכל סמסטר, ולא שדה שמשתנה על מופע משותף: השרת מטפל בבקשות
    במקביל, ומצב משותף שמשתנה לפי בקשה הוא בדיוק סוג התקלה שאי אפשר
    לשחזר. המופעים זולים ומקוששים.
    """
    from flask import current_app

    key = str(semester or "")
    if not key:
        return _store()
    cache = current_app.extensions.setdefault("slotwise", {})
    stores = cache.setdefault("stores_by_semester", {})
    obj = stores.get(key)
    if obj is None:
        obj = store_mod.Store(
            str(_config()["db_root"]),
            use_shipped=True,
            semester=key,
            prefer_newer_catalog=True,
        )
        stores[key] = obj
    return obj


def _request_cache() -> dict[str, Any]:
    """מטמון קצר-טווח שחי **רק לאורך הבקשה הנוכחית**.

    כאן יושבים דברים שמותר לקרוא פעם אחת בבקשה אבל אסור לשמור בין בקשות —
    למשל פרטי הקורסים, שמשתנים ברגע שהרענון שומר אותם. מחוץ להקשר בקשה
    (בדיקה שקוראת לפונקציה ישירות) מוחזר מילון חדש, כלומר בלי מטמון בכלל.
    """
    try:
        from flask import g

        cache = getattr(g, "_slotwise_cache", None)
        if cache is None:
            cache = {}
            g._slotwise_cache = cache  # noqa: SLF001 - זה בדיוק ייעודו של g
        return cache
    except Exception:  # noqa: BLE001 - אין הקשר בקשה: פשוט בלי מטמון
        return {}


def _norm_program(value: Any) -> str:
    """שם מסלול לשם השוואה בלבד — בלי רווחים, גרשיים ומקפים."""
    return re.sub(r"[\s\"'׳״-]", "", str(value or ""))


def _curricula() -> dict[str, dict]:
    """כל תוכניות הלימודים שיש לנו, לפי שם מסלול מנורמל.

    ‏``curriculum_path`` (הנדסת תוכנה) ועוד קובץ לכל מחלקה תחת
    ``curricula_dir``. עד שהתיקייה הזאת נוצרה הייתה כאן תוכנית אחת בלבד,
    וכל מי שאינו הנדסת תוכנה קיבל/ה קטלוג במקום רשימת סמסטר.

    ‏**קובץ חסר או פגום פשוט אינו נכנס לרשימה.** מסלול בלי תוכנית עובד מול
    הקטלוג, וזו התנהגות תקינה — ‏SPEC_MULTIFACULTY §4 — ולא תקלה.

    ‏**קובץ שנושא ``intake`` אינו נכנס לכאן בכלל.** מסלול עם מועדי כניסה
    אינו "תוכנית אחת" ואין לו ערך יחיד שאפשר להחזיר; הוא חי ב-
    ``_curricula_by_intake()``. ההפרדה היא מה ששומר על הנתיב הקיים
    (מסלול ⇐ קובץ אחד) בדיוק כפי שהיה לכל שאר המחלקות.
    """
    return _curricula_split()[0]


def _curricula_by_intake() -> dict[str, dict[str, dict]]:
    """תוכניות לפי מסלול **ולפי מועד כניסה**: ``{מסלול: {intake: תוכנית}}``.

    ‏מתמטיקה שימושית היא המקרה הראשון: השנתון מדפיס לה שתי תוכניות, אחת
    למתקבלים בחורף ואחת למתקבלים באביב, בלי ולו סמסטר אחד משותף — ומספר
    הסמסטר עצמו מציין דבר אחר בכל אחת. לכן הן שני קבצים, כל אחד עם שדה
    ``intake``, ולא קובץ אחד עם שני ענפים.
    """
    return _curricula_split()[1]


def _curricula_split() -> tuple[dict[str, dict], dict[str, dict[str, dict]]]:
    """קורא את כל קובצי התוכנית פעם אחת ומפריד אותם לשתי המפות."""
    from flask import current_app

    cache = current_app.extensions.setdefault("slotwise", {})
    cfg = _config()
    paths = [Path(cfg["curriculum_path"])]
    folder = Path(cfg.get("curricula_dir") or "")
    if folder.is_dir():
        paths.extend(sorted(folder.glob("*.json")))

    def stamp_of(path: Path) -> int:
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return 0

    stamp = tuple((str(p), stamp_of(p)) for p in paths)
    if cache.get("curricula_stamp") != stamp or "curricula" not in cache:
        loaded: dict[str, dict] = {}
        by_intake: dict[str, dict[str, dict]] = {}
        for path in paths:
            try:
                data = curriculum_mod.load_curriculum(path)
            except Exception as exc:  # noqa: BLE001 — חסר/פגום = "אין תוכנית"
                LOG.info("תוכנית לימודים שלא נטענה (%s): %s", path, exc)
                continue
            if not isinstance(data, dict) or not data:
                continue
            name = _norm_program(data.get("program") or data.get("program_en"))
            if not name:
                continue
            intake = str(data.get("intake") or "").strip()
            if intake:
                by_intake.setdefault(name, {}).setdefault(intake, data)
                continue
            # הקובץ הראשון ברשימה מנצח, כדי שתוכנית ברירת המחדל תישאר יציבה.
            if name not in loaded:
                loaded[name] = data
        cache["curricula"] = loaded
        cache["curricula_by_intake"] = by_intake
        cache["curricula_stamp"] = stamp
    return cache["curricula"], cache["curricula_by_intake"]


def _program_intakes(program: Any = None) -> list[dict]:
    """מועדי הכניסה של המסלול, מ-``programs.json``. ריק = מסלול רגיל.

    ‏הרשימה היא מקור האמת לשאלה "האם צריך לשאול על מועד כניסה", והיא
    באה מהמרשם ולא מהקבצים: מסלול שהוכרז כבעל מועדים אבל קובץ אחד שלו
    חסר צריך עדיין לשאול, ולא להתנהג כאילו יש לו תוכנית אחת.
    """
    wanted = _norm_program(program)
    if not wanted:
        return []
    # ‏``_program_choices`` שואל פעם אחת לכל מסלול, ו-``_curriculum`` שואל
    # שוב. בלי המטמון זו קריאת קובץ ופענוח ‏JSON לכל אחת מהן באותה בקשה.
    cache = _request_cache()
    table = cache.get("program_intakes")
    if table is None:
        table = {}
        try:
            from programs import load_programs

            listed = load_programs(str(PROJECT_ROOT / "data" / "programs.json"))
        except Exception:  # noqa: BLE001 — היעדר הקובץ אינו תקלה
            listed = []
        for entry in listed:
            out = []
            for item in entry.get("intakes") or []:
                if not isinstance(item, dict):
                    continue
                ident = str(item.get("id") or "").strip()
                if ident:
                    out.append({"id": ident, "label": str(item.get("label") or ident)})
            if out:
                table[_norm_program(entry.get("name"))] = out
        cache["program_intakes"] = table
    return list(table.get(wanted, []))


def _curriculum(program: Any = None, intake: Any = None) -> dict:
    """תוכנית הלימודים של המסלול המבוקש, או תוכנית ברירת המחדל בלעדיו.

    בלי ``program`` מוחזרת התוכנית שב-``curriculum_path`` — בדיוק כמו קודם,
    כדי שכל קריאה קיימת תמשיך להתנהג אותו דבר.

    ‏``intake`` נקרא **רק** למסלול שיש לו מועדי כניסה. שם הוא חובה: בלי
    מועד אין תוכנית אחת להחזיר, ו-``{}`` כאן הוא מה שגורם לממשק לבקש
    לבחור מועד במקום להציג רשימה של חצי מהמחלקה.
    """
    wanted = str(program or "").strip()
    if not wanted:
        return _default_curriculum()
    if wanted.casefold() == OTHER_PROGRAM:
        return {}
    norm = _norm_program(wanted)
    if _program_intakes(wanted):
        chosen = str(intake or "").strip()
        if not chosen:
            return {}
        return _curricula_by_intake().get(norm, {}).get(chosen, {})
    return _curricula().get(norm, {})


def _default_curriculum() -> dict:
    """תוכנית הלימודים, בקאש עם בדיקת mtime (עריכה של הקובץ נקלטת מיד).

    ‏**קובץ חסר או פגום מחזיר ``{}``, לא חריגה.** התוכנית הפכה להעשרה
    אופציונלית (‏SPEC_MULTIFACULTY §4): סטודנט/ית שהמסלול שלהם אינו ב-rec.pdf
    חייבים לעבור לעיון בקטלוג ולהמשיך לעבוד, ולא לקבל ‏500 בכל נקודת קצה.
    """
    from flask import current_app

    cache = current_app.extensions.setdefault("slotwise", {})
    path = Path(_config()["curriculum_path"])
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        stamp = 0
    if cache.get("curriculum_stamp") != stamp or "curriculum" not in cache:
        try:
            loaded = curriculum_mod.load_curriculum(path)
        except Exception as exc:  # noqa: BLE001 - חסר/פגום = "אין תוכנית", לא תקלה
            LOG.info("אין תוכנית לימודים טעונה (%s): %s", path, exc)
            loaded = {}
        cache["curriculum"] = loaded if isinstance(loaded, dict) else {}
        cache["curriculum_stamp"] = stamp
    return cache["curriculum"]


def _profile() -> dict:
    """‏data/profile.json — התשובות האמיתיות של הסטודנט/ית. חסר = ``{}``."""
    from flask import current_app

    cache = current_app.extensions.setdefault("slotwise", {})
    if "profile" not in cache:
        path = Path(_config()["profile_path"])
        data: dict = {}
        try:
            with open(path, encoding="utf-8") as fh:  # utf-8 חובה — עברית
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError) as exc:
            LOG.warning("לא ניתן לקרוא את %s: %s", path, exc)
        cache["profile"] = data
    return cache["profile"]


# ===========================================================================
# 5א. נ"ז ותנאי קדם — בלי תלות בתוכנית הלימודים  (SPEC_MULTIFACULTY §3)
#
# ‏493 מתוך 571 קורסי הקטלוג (86%) אינם ב-curriculum.json. עד כאן הם דיווחו
# ‏0.0 נ"ז, בלי תנאי קדם ובלי קורסים צמודים — כלומר הכלי עבד רק לתוכנית אחת.
# הידיעון עצמו יודע את כל זה (‏S_CourseDetails, קריא בלי התחברות), ולכן סדר
# ההכרעה **בכל מקום** הוא אחד:
#
#     1. ‏curriculum.json — העשיר ביותר (אשכולות, קורסים צמודים, חליפיים)
#     2. פרטי הידיעון השמורים (``data/db/details.json``)
#     3. ‏``None`` — ולא ‏0.0. הממשק מציג "—".
#
# ‏**0.0 לעולם אינו "לא ידוע".** סכום נ"ז ששותק על 86% מהקטלוג גרוע מסכום
# שמודה שאינו יודע, ולכן ``credits_summary`` סופר גם את מה שלא ידוע ואומר זאת.
# ===========================================================================
#: שמות אפשריים לטעינת **כל** הפרטים בקריאה אחת. ``store.py`` שייך לסוכן
#: אחר; אם אחת מהשיטות קיימת נשתמש בה, ואם לא — נטען קוד-קוד עם תקרה.
_DETAILS_BULK_METHODS: tuple[str, ...] = ("all_details", "load_all_details", "details_map")


def _details_supported() -> bool:
    """האם ה-Store שבשימוש בכלל יודע לשמור פרטי קורס."""
    store = _store()
    return callable(getattr(store, "load_details", None)) or any(
        callable(getattr(store, name, None)) for name in _DETAILS_BULK_METHODS
    )


def _details_bulk() -> dict[str, dict] | None:
    """כל פרטי הקורסים בקריאה אחת — או ``None`` אם ה-Store אינו תומך בכך.

    נשמר במטמון לאורך הבקשה בלבד: אותה בקשה לא תקרא את הקובץ פעמיים, ובקשה
    הבאה תראה מיד מה שנשמר בינתיים.
    """
    cache = _request_cache()
    if "details_bulk" in cache:
        return cache["details_bulk"]
    store = _store()
    result: dict[str, dict] | None = None
    for name in _DETAILS_BULK_METHODS:
        loader = getattr(store, name, None)
        if not callable(loader):
            continue
        try:
            raw = loader()
        except Exception:  # noqa: BLE001 - מסד פגום לא מפיל בקשה
            LOG.exception("טעינת כל פרטי הקורסים נכשלה (%s)", name)
            raw = None
        if isinstance(raw, dict):
            result = {
                str(code): dict(info)
                for code, info in raw.items()
                if isinstance(info, dict)
            }
            break
    cache["details_bulk"] = result
    return result


def _course_details(code: str) -> dict | None:
    """פרטי הידיעון השמורים לקורס אחד. ``None`` כשאין, וגם כשאין תמיכה.

    לעולם לא זורק: פרטים הם העשרה, ואפליקציה שנופלת בגללם מפסידה יותר
    ממה שהיא מרוויחה.
    """
    key = str(code or "").strip()
    if not key:
        return None
    bulk = _details_bulk()
    if bulk is not None:
        return bulk.get(key)

    cache = _request_cache()
    memo: dict[str, dict | None] = cache.setdefault("details_one", {})
    if key in memo:
        return memo[key]
    if len(memo) >= MAX_DETAILS_LOOKUPS:
        # מעבר לתקרה לא משקרים: פשוט לא יודעים, וזה מה שיוחזר.
        return None
    store = _store()
    loader = getattr(store, "load_details", None)
    value: dict | None = None
    if callable(loader):
        try:
            raw = loader(key)
        except Exception:  # noqa: BLE001
            LOG.exception("טעינת פרטי הקורס %s נכשלה", key)
            raw = None
        if isinstance(raw, dict):
            value = raw
    memo[key] = value
    return value


def _details_age_hours(details: Any) -> float | None:
    """גיל הפרטים בשעות, לפי ``fetched_at``. ``None`` כשאי אפשר לדעת.

    החותמת יכולה לשבת ברמה העליונה או תחת ``meta`` — שתי הצורות מקובלות,
    כי מבנה ``details.json`` נקבע בקובץ של סוכן אחר.
    """
    if not isinstance(details, dict):
        return None
    stamp = details.get("fetched_at")
    if not stamp and isinstance(details.get("meta"), dict):
        stamp = details["meta"].get("fetched_at")
    return store_mod.age_hours_since(stamp) if stamp else None


def _details_max_age() -> float:
    """חלון הטריות של הפרטים, לפי ההגדרות. ברירת המחדל היא שבעה ימים."""
    try:
        value = float(_config().get("details_max_age_hours") or DETAILS_MAX_AGE_HOURS)
    except Exception:  # noqa: BLE001 - מחוץ להקשר בקשה, או ערך לא מספרי
        return DETAILS_MAX_AGE_HOURS
    return value if value > 0 else DETAILS_MAX_AGE_HOURS


def _details_stale(
    code: str,
    details: Any = None,
    *,
    max_age_hours: float | None = None,
) -> bool:
    """האם שווה למשוך מחדש את פרטי הקורס — חלון של שבעה ימים.

    ``store.details_stale`` הוא מקור האמת אם הוא קיים; אחרת מחשבים מהחותמת
    השמורה. חסר לגמרי = מיושן (כלומר: שווה להביא).
    """
    key = str(code or "").strip()
    if not key:
        return False
    if max_age_hours is None:
        max_age_hours = _details_max_age()
    store = _store()
    checker = getattr(store, "details_stale", None)
    if callable(checker):
        try:
            return bool(checker(key, max_age_hours))
        except TypeError:
            with contextlib.suppress(Exception):
                return bool(checker(key, max_age_hours=max_age_hours))
        except Exception:  # noqa: BLE001
            LOG.exception("בדיקת טריות הפרטים של %s נכשלה", key)
    if details is None:
        details = _course_details(key)
    if not isinstance(details, dict) or not details:
        return True
    age = _details_age_hours(details)
    if age is None:
        return True
    return age > float(max_age_hours)


def _stated_credits(value: Any) -> float | None:
    """נ"ז שמקור **הצהיר** עליהן במפורש — כולל אפס אמיתי.

    ‏11063 (אנגלית בסיסי) הוא באמת ‏0 נ"ז בתוכנית, ו-``parse_course_details``
    מחזיר ``None`` (ולא ‏0.0) כשהוא לא ידע. לכן במקורות מוצהרים ‏0.0 הוא
    **ידיעה**, ורק ``None``/ריק הוא בורות. ההבחנה הזו היא כל ההבדל בין
    להציג ‏0 לבין להציג מקף.
    """
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _known_credits(value: Any) -> float | None:
    """נ"ז מתוך **דף המערכת** — שם ‏0.0 פירושו "לא נמצא", כלומר לא ידוע.

    ‏``parser._extract_credits`` מחזיר ‏0.0 עם אזהרה כשהשורה חסרה בדף, ולכן
    אסור להציג ‏0.0 שהגיע משם כאילו מישהו אמר אותו.
    """
    number = _stated_credits(value)
    if number is None or number <= 0:
        return None
    return number


def credits_text(value: Any) -> str:
    """נ"ז לתצוגה: ‏5.0 → "5", ‏0.0 → "0", לא ידוע (``None``) → "—"."""
    number = _stated_credits(value)
    if number is None:
        return CREDITS_UNKNOWN_TEXT
    return f"{number:g}"


def resolve_credits(
    code: str,
    *,
    entry: dict | None = None,
    details: Any = None,
    course: Any = None,
) -> tuple[float | None, str]:
    """נ"ז של קורס + **מאיפה** הן. זהו העוזר היחיד; אין העתקים.

    Args:
        code: קוד הקורס.
        entry: רשומת ``curriculum.json`` אם כבר נטענה (חוסך חיפוש).
        details: פרטי הידיעון השמורים אם כבר נטענו. ``None`` = לטעון.
        course: ``models.Course`` שנטען מהמסד. **אינו מקור נ"ז.** המספר
            שמופיע בדף המערכת נשלף משורת הערה חופשית ("טווח 72.01-96 נ\"ז",
            "‏10 נ\"ז, נוכחות חובה") ולכן הוא לא פעם טווח זכאות או תנאי
            רישום — לא נ"ז הקורס. הפרמטר נשמר כדי שהחתימה לא תישבר.

    Returns:
        ``(credits, source)`` כאשר ``source`` הוא ``"curriculum"`` /
        ``"yedion"`` / ``"unknown"``. ‏**לעולם לא מוחזר 0.0 כ"לא ידוע"**,
        וגם לא מספר שנקרע מתוך הערה חופשית בדף המערכת.
    """
    key = str(code or "").strip()
    if entry is None and key:
        entry = curriculum_mod.find_course(_curriculum(), key)
    if isinstance(entry, dict):
        # מקור מוצהר: ‏0.0 בתוכנית (אנגלית בסיסי) הוא אפס אמיתי, לא "לא ידוע".
        from_curriculum = _stated_credits(entry.get("credits"))
        if from_curriculum is not None:
            return from_curriculum, CREDITS_SOURCE_CURRICULUM

    if details is None and key:
        details = _course_details(key)
    if isinstance(details, dict):
        from_yedion = _stated_credits(details.get("credits"))
        if from_yedion is not None:
            return from_yedion, CREDITS_SOURCE_YEDION

    # אין שלב שלישי. ‏SPEC_MULTIFACULTY §3 מגדיר שני מקורות בלבד — התוכנית
    # ואז פרטי הידיעון — ואז "לא ידוע". המספר שב-``course.credits`` מגיע
    # מהערה חופשית בדף המערכת, ולכן הוא עלול להיות טווח זכאות (96 במקום 5),
    # תנאי רישום, או ‏0.25 שנחתך ל-25. להציג אותו כ"ידוע" זה בדיוק הסך
    # המטעה שהמפרט בא לחסל, רק בתחפושת.
    return None, CREDITS_SOURCE_UNKNOWN


def _details_prereq_rows(details: Any) -> list[dict[str, Any]]:
    """טבלת תנאי הקדם מתוך הפרטים השמורים, מנורמלת ובסדר הידיעון.

    כל השדות שהפענוח מוציא נשמרים — כולל ``population`` (לגבי מי התנאי תקף)
    ו-``alternative_name`` (הקורס החליפי שמספיק לעבור במקומו). בלעדיהם השורה
    אומרת "יש תנאי" ולא *איזה*, וזה ההבדל בין מידע לרעש.
    """
    rows: list[dict[str, Any]] = []
    if not isinstance(details, dict):
        return rows
    for row in details.get("prerequisites") or []:
        if not isinstance(row, dict):
            text = str(row or "").strip()
            if text:
                rows.append(
                    {
                        "code": text,
                        "name": "",
                        "relation": "",
                        "alternative": None,
                        "alternative_name": "",
                        "population": "",
                    }
                )
            continue
        rows.append(
            {
                "code": str(row.get("code") or "").strip(),
                "name": str(row.get("name") or "").strip(),
                "relation": str(row.get("relation") or ""),
                "alternative": row.get("alternative"),
                "alternative_name": str(row.get("alternative_name") or ""),
                "population": str(row.get("population") or ""),
            }
        )
    return rows


def _details_prereq_codes(details: Any) -> list[str]:
    """מזהי תנאי הקדם מתוך טבלת הפרטים, בלי כפילויות ובסדר הידיעון.

    בטבלה האמיתית (``S_CourseDetails``) **אין עמודת קוד בכלל** — עמודת
    "נושא נקשר" נותנת שם. לכן השם הוא הנפילה־לאחור, אחרת כל הטבלה נזרקת
    ואנחנו מדווחים "אין מידע" על טבלה שפענחנו במלואה.
    """
    out: list[str] = []
    for row in _details_prereq_rows(details):
        ident = row["code"] or row["name"]
        if ident and ident not in out:
            out.append(ident)
    return out


def resolve_prerequisites(
    code: str,
    *,
    entry: dict | None = None,
    details: Any = None,
) -> tuple[list[str], str, list[dict[str, Any]]]:
    """תנאי הקדם + מאיפה + הטבלה המלאה (כשהיא קיימת בפרטי הידיעון).

    אותו סדר הכרעה כמו הנ"ז: התוכנית קודם (היא מכירה קורסים חליפיים), ואז
    הידיעון. ``([], "unknown", [])`` פירושו "אין לנו מידע", לא "אין תנאי קדם".
    """
    key = str(code or "").strip()
    if entry is None and key:
        entry = curriculum_mod.find_course(_curriculum(), key)
    if details is None and key:
        details = _course_details(key)
    # הטבלה נבנית פעם אחת ומוחזרת בכל ענף: היא תיאור, לא הכרעה. גם כשהתוכנית
    # היא זו שנותנת את הקודים, הטבלה של הידיעון היא מה שמסביר *למה*.
    rows = _details_prereq_rows(details)

    if isinstance(entry, dict):
        listed = [str(p).strip() for p in (entry.get("prereq") or []) if str(p or "").strip()]
        if listed:
            return listed, CREDITS_SOURCE_CURRICULUM, rows

    # התנאי הוא על **השורות**, לא על הקודים: טבלה שכולה שמות היא עדיין מידע.
    if rows:
        return _details_prereq_codes(details), CREDITS_SOURCE_YEDION, rows

    # רשומת תוכנית שקיימת ומצהירה במפורש על אפס תנאי קדם היא ידיעה, לא בורות.
    if isinstance(entry, dict) and "prereq" in entry:
        return [], CREDITS_SOURCE_CURRICULUM, rows
    return [], CREDITS_SOURCE_UNKNOWN, rows


def course_facts(
    code: str,
    *,
    course: Any = None,
    entry: dict | None = None,
    details: Any = None,
    stale: bool | None = None,
) -> dict[str, Any]:
    """כל מה שידוע על קורס אחד **בלי תלות בתוכנית** — נקודת האמת היחידה.

    כל נקודת קצה שמציגה נ"ז, תנאי קדם או קורסים צמודים עוברת דרך כאן, כדי
    שהתשובה תהיה זהה בכל מקום — כולל ההודאה "לא ידוע".

    Args:
        code: קוד הקורס.
        course: ``models.Course`` שנטען, אם יש.
        entry: רשומת התוכנית, אם כבר נטענה.
        details: פרטי הידיעון, אם כבר נטענו.
        stale: האם הפרטים מיושנים, כשהקורא/ת כבר יודע/ת. ‏``None`` =
            "לא נבדק" — ובכוונה: בדיקת טריות קוד-קוד הייתה קוראת את קובץ
            הפרטים פעם לכל שורה בעמוד עיון, ולכן היא נעשית בבת אחת
            ב-``_details_needing_fetch`` ומועברת לכאן.

    Returns:
        מילון עם ``credits`` (‏``float | None``), ``credits_source``,
        ``credits_text``, ``prereq``, ``prereq_source``, ``prereq_detail``,
        ``tied_with``, ``in_curriculum``, ``curriculum_semester``,
        ``cluster``, ``name``, ``hours``, ``weekly_hours``, ``language``,
        ``description``, ``details_available``, ``details_stale``.
    """
    key = str(code or "").strip()
    curr = _curriculum()
    if entry is None and key:
        entry = curriculum_mod.find_course(curr, key)
    if details is None and key:
        details = _course_details(key)
    details_dict = details if isinstance(details, dict) else None

    credits, credits_source = resolve_credits(
        key, entry=entry, details=details_dict, course=course
    )
    prereq, prereq_source, prereq_rows = resolve_prerequisites(
        key, entry=entry, details=details_dict
    )

    source_label = curriculum_mod.find_course_source(curr, key) if key else None
    semester = cluster = None
    if source_label:
        if source_label.startswith("semester:"):
            semester = source_label.split(":", 1)[1]
        elif source_label.startswith("cluster:"):
            cluster = source_label.split(":", 1)[1]

    tied: list[str] = []
    if key:
        with contextlib.suppress(Exception):
            tied = [other for other in curriculum_mod.tied_group(curr, key) if other != key]

    name = ""
    for candidate in (
        (entry or {}).get("name") if isinstance(entry, dict) else "",
        (details_dict or {}).get("name") if details_dict else "",
        getattr(course, "name", ""),
    ):
        if str(candidate or "").strip():
            name = str(candidate).strip()
            break

    hours: dict[str, Any] = {}
    if isinstance(entry, dict) and any(k in entry for k in ("he", "te", "ma", "pr")):
        hours = {k: entry.get(k) for k in ("he", "te", "ma", "pr")}
    elif details_dict and isinstance(details_dict.get("hours"), dict):
        hours = dict(details_dict["hours"])

    return {
        "code": key,
        "name": name,
        "credits": credits,
        "credits_source": credits_source,
        "credits_text": credits_text(credits),
        "prereq": prereq,
        "prereq_source": prereq_source,
        "prereq_detail": prereq_rows,
        "tied_with": tied,
        "in_curriculum": isinstance(entry, dict) and bool(entry),
        "curriculum_semester": semester,
        "cluster": cluster,
        "hours": hours,
        "weekly_hours": (details_dict or {}).get("weekly_hours"),
        "language": str((details_dict or {}).get("language") or ""),
        "description": str((details_dict or {}).get("description") or ""),
        "details_available": bool(details_dict),
        "details_stale": stale,
    }


def credits_summary(values: Iterable[Any]) -> dict[str, Any]:
    """סיכום נ"ז שמודה במה שאינו ידוע.

    מחבר **רק** ערכים ידועים, וסופר בנפרד כמה קורסים אין להם נ"ז. סכום
    שמתעלם מזה בשקט הוא בדיוק מה ש-SPEC_MULTIFACULTY §3 אוסר.
    """
    total = 0.0
    known = 0
    unknown = 0
    for value in values:
        # הערכים כאן כבר עברו הכרעה: ``None`` = לא ידוע, ‏0.0 = אפס אמיתי.
        number = _stated_credits(value)
        if number is None:
            unknown += 1
        else:
            total += number
            known += 1
    rounded = round(total, 2)
    if unknown == 0:
        text = f"{rounded:g}"
    elif known == 0:
        text = CREDITS_UNKNOWN_TEXT
    else:
        text = f"{rounded:g} (ועוד {unknown} קורסים ללא נתוני נ\"ז)"
    return {
        "total": rounded,
        "known": known,
        "unknown": unknown,
        "complete": unknown == 0,
        "text": text,
    }


#: המזהה שהממשק שולח כשהסטודנט/ית בוחר/ת "תוכנית אחרת / לא ברשימה".
OTHER_PROGRAM = "other"


def _program_choices(
    curr: dict | None = None, program: Any = None, intake: Any = None
) -> list[dict]:
    """רשימת המסלולים לבחירה בשלב 1.

    המקור הוא ``data/programs.json`` — נמשך מהאתר הציבורי של המכללה
    (``src/programs.py``), ולכן זו הרשימה **המוסמכת והעדכנית**: 8 תוכניות
    תואר ראשון. אם הקובץ חסר, נופלים חזרה לשתי אפשרויות בלבד, כדי שהממשק
    ימשיך לעבוד גם בלי משיכה מהאתר.

    ``has_curriculum`` נכון רק לתוכנית שיש לה ``curriculum.json`` — כרגע
    הנדסת תוכנה בלבד, כי ``rec.pdf`` הוא הפרק שלה. לכל השאר הכלי עובד מול
    הקטלוג המלא, שממילא מכסה את כל המחלקות.

    ``intakes`` מגיע לכל מסלול שיש לו מועדי כניסה, ועם ``has_curriculum``
    שנגזר מהמועד שנבחר — ולכן הוא ``false`` כל עוד לא נבחר מועד. הממשק
    מחליף מסלול בלי לבקש ‏bootstrap מחדש, ולכן הרשימה חייבת לשאת גם את
    המועדים וגם את הסיבה, בדיוק כפי שהיא נושאת את ``curriculum_absence``.
    """
    mine = curriculum_program(curr)
    try:
        from programs import load_programs

        listed = load_programs(str(PROJECT_ROOT / "data" / "programs.json"))
    except Exception:  # noqa: BLE001 — היעדר הקובץ אינו תקלה
        listed = []

    out: list[dict] = []
    for entry in listed:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        intakes = _program_intakes(name)
        if intakes:
            # מסלול עם מועדי כניסה: התשובה תלויה במועד שנבחר, ולכן היא
            # נגזרת מ-``intake`` ולא מעצם קיומו של קובץ.
            is_chosen = _norm_program(name) == _norm_program(program)
            picked = str(intake or "").strip() if is_chosen else ""
            has = bool(_curriculum_available(_curriculum(name, picked), name))
            absence = (
                CURRICULUM_ABSENCE_NONE
                if has
                else (
                    CURRICULUM_ABSENCE_INTAKE_REQUIRED
                    if not picked
                    else CURRICULUM_ABSENCE_MISSING
                )
            )
        else:
            # לפי המרשם, לא לפי תוכנית ברירת המחדל: לכל מחלקה שיש לה
            # קובץ תוכנית משלה מגיע "יש תוכנית", לא רק להנדסת תוכנה.
            has = _norm_program(name) in _curricula()
            # למה אין תוכנית, כשאין. הממשק מחליף מסלול בלי לבקש שוב
            # ‏/api/bootstrap, ולכן הסיבה חייבת להגיע כאן לכל מסלול.
            absence = (
                CURRICULUM_ABSENCE_NONE if has else _curriculum_absence(name, {})
            )
        out.append(
            {
                "id": name,
                "label": name,
                "has_curriculum": has,
                "curriculum_absence": absence,
                # ריק לכל מסלול רגיל, וזה מה שמסתיר את התיבה בממשק.
                "intakes": intakes,
                "url": entry.get("url", ""),
                "description": entry.get("description", ""),
                "tracks_text": entry.get("tracks_text", ""),
            }
        )
    if mine and not any(p["id"] == mine for p in out):
        out.insert(0, {"id": mine, "label": mine, "has_curriculum": True,
                       "curriculum_absence": CURRICULUM_ABSENCE_NONE,
                       "intakes": []})
    out.append(
        {
            "id": OTHER_PROGRAM,
            "label": "תוכנית אחרת / לא ברשימה",
            "has_curriculum": False,
            # ‏"לא ברשימה" אינו מסלול, ולכן אין לו סיבה להיעדר תוכנית —
            # הוא **הוא** הבחירה לעבוד מול הקטלוג.
            "curriculum_absence": CURRICULUM_ABSENCE_MISSING,
            "intakes": [],
        }
    )
    return out


def curriculum_program(curr: dict | None = None) -> str:
    """שם התוכנית ש-``curriculum.json`` מתאר, למשל ``'הנדסת תוכנה'``."""
    data = _curriculum() if curr is None else curr
    if not isinstance(data, dict):
        return ""
    return str(data.get("program") or data.get("program_en") or "").strip()


def _program_matches_curriculum(program: Any, curr: dict | None = None) -> bool:
    """האם התוכנית שהסטודנט/ית ציין/ה היא זו שיש לנו קובץ תוכנית עבורה.

    ‏rec.pdf הוא פרק **הנדסת תוכנה** בשנתון בלבד — 15% מהקטלוג. עד עכשיו
    רשימת הקורסים של שלב 2 נבנתה ממנו לכל אחד/ת, כך שסטודנט/ית ממכונות
    שבחר/ה "שנה ג' סמסטר א'" קיבל/ה **קורסי תוכנה** כאילו הם המסלול שלו/ה.
    לכן: מציגים את התוכנית רק כשהיא באמת שלו/ה, ואחרת עוברים לקטלוג.

    ערך ריק = לא נשאלו / לא ידוע -> **כן** מתאים, כדי לא לשנות התנהגות
    קיימת של קריאות שאינן מציינות תוכנית.
    """
    wanted = str(program or "").strip()
    if not wanted:
        return True
    if wanted.casefold() == OTHER_PROGRAM:
        return False
    mine = curriculum_program(curr)
    if not mine:
        return False
    norm = lambda t: re.sub(r"[\s\"'׳״-]", "", str(t))
    return norm(wanted) == norm(mine)


def _curriculum_absence(
    program: Any = None, curr: dict | None = None, intake: Any = None
) -> str:
    """למה אין תוכנית לימודים למסלול הזה. ‏"" כשיש אחת.

    ‏``not_representable`` = המכללה מפרסמת תוכנית, אבל לא בצורה שאפשר
    להציג כרשימה אחת לסמסטר. ‏``no_curriculum`` = אין תוכנית ידועה.
    ההבחנה קיימת כדי שהממשק יוכל להסביר, במקום ליפול לקטלוג בשקט.
    """
    if _curriculum_available(curr, program):
        return CURRICULUM_ABSENCE_NONE
    # לפני "אין תוכנית": אולי יש, ורק לא נאמר לאיזה מועד כניסה. זו שאלה
    # פתוחה ולא היעדר, והנוסח שלה מבקש לבחור מועד במקום להציע את הקטלוג.
    if _program_intakes(program) and not str(intake or "").strip():
        return CURRICULUM_ABSENCE_INTAKE_REQUIRED
    norm = _norm_program(program)
    if norm:
        for name, reason in CURRICULUM_ABSENCE_BY_PROGRAM.items():
            if _norm_program(name) == norm:
                return reason
    return CURRICULUM_ABSENCE_MISSING


def _curriculum_available(curr: dict | None = None, program: Any = None) -> bool:
    """האם יש בכלל תוכנית לימודים טעונה שאפשר להישען עליה.

    תוכנית ריקה אינה תקלה: סטודנט/ית שהמסלול שלהם אינו ב-rec.pdf חייבים
    להמשיך לעבוד מול הקטלוג. ‏SPEC_MULTIFACULTY §4.
    """
    data = _curriculum(program) if curr is None else curr
    if not isinstance(data, dict) or not data:
        return False
    if not _program_matches_curriculum(program, data):
        return False
    if data.get("semesters") or data.get("elective_clusters"):
        try:
            return bool(next(curriculum_mod.iter_all_courses(data), None))
        except Exception:  # noqa: BLE001
            return False
    return False


# ===========================================================================
# 6. בניית הקורסים לשיבוץ — deepcopy, tied_with, נ"ז, נעיצות
# ===========================================================================
def _norm_year(value: Any) -> str:
    """מנרמל תווית שנה להשוואה: מסיר רווחים וגרשיים ('תשפ"ז' ≡ 'תשפז')."""
    return re.sub(r"[\s\"'׳״]", "", str(value or ""))


def _year_matches(requested: Any, meta: store_mod.CourseMeta | None) -> bool:
    """האם השנה שהתבקשה היא השנה ששמורה במסד (עברית או לועזית)."""
    want = _norm_year(requested)
    if not want or meta is None:
        return True
    known = {_norm_year(meta.year), _norm_year(meta.year_gregorian)}
    known.discard("")
    return (not known) or want in known


def _assert_known_codes(codes: Iterable[str]) -> None:
    """פוסל קוד שהמערכת לא מכירה בכלל — לא בתוכנית, לא בקטלוג, לא במסד.

    ההבחנה חשובה, ושתי המשמעויות שונות לגמרי:

    * ‏61759 מוכר (הוא בתוכנית ובקטלוג) אבל עדיין לא נסרק → זו **תשובה**:
      הוא חוזר ב-``not_offered`` עם ההסבר "יש להריץ רענון".
    * ‏99999 לא מוכר בשום מקום → זו **טעות**: קורס כזה לא קיים, ובניית מערכת
      שמתעלמת ממנו בשקט הייתה משקרת על מה שנכלל בה.

    Raises:
        ApiError: 404 עם רשימת הקודים הלא מוכרים.
    """
    wanted = [c for c in codes]
    if not wanted:
        return
    curr = _curriculum()
    store_codes = set(_store().codes())
    catalog: dict[str, dict] | None = None

    unknown: list[str] = []
    for code in wanted:
        if code in store_codes or curriculum_mod.find_course(curr, code) is not None:
            continue
        if catalog is None:
            catalog, _summary = _catalog_snapshot()
        if code in catalog:
            continue
        unknown.append(code)

    if unknown:
        raise ApiError(
            404,
            "קוד/ים שאינם מוכרים למערכת: "
            + ", ".join(unknown)
            + ". הקודים האלה אינם בתוכנית הלימודים, אינם בקטלוג החי ואין להם נתונים "
            "שמורים. אפשר לחפש את הקורס בתיבת החיפוש כדי לקבל את הקוד הנכון.",
            f"unknown course codes: {unknown}",
        )


def _build_courses(
    codes: Iterable[str],
    *,
    semester: str = "",
    year: str = "",
) -> tuple[list[models.Course], list[dict[str, Any]], dict[str, store_mod.CourseMeta]]:
    """טוען קורסים מהמסד ומכין אותם למנוע.

    לכל קוד:
      1. ``Store.load_course`` — ואז **deepcopy מיד**. ה-Store מחזיר אובייקטים
         חיים; סינון קבוצות עליהם היה משנה את המסד בזיכרון לכל הבקשות הבאות.
      2. ``curriculum.tied_group`` → ``course.tied_with`` (המנוע אוכף חבילה).
      3. ``curriculum.find_course`` → נ"ז לפי התוכנית (בידיעון 11069 מופיע
         עם 0 נ"ז; התוכנית יודעת שזה 1).

    Returns:
        ``(courses, problems, metas)`` — ``problems`` הם קודים שאי אפשר לשבץ,
        כל אחד עם סיבה בעברית. הם לא שגיאה: הם מידע.
    """
    # הקטלוג שנשלח נושא את **כל** הסמסטרים, ולכן כאן — במקום היחיד שבונה
    # קורסים למנוע — בוחרים אחד. בלי זה קבוצות סמסטר ב', שאין להן מפגשים
    # ולכן אינן מתנגשות עם דבר, נכנסות למרחב החיפוש ומנפחות אותו.
    store = _store_for(semester)
    curr = _curriculum()

    courses: list[models.Course] = []
    problems: list[dict[str, Any]] = []
    metas: dict[str, store_mod.CourseMeta] = {}

    for code in codes:
        entry = curriculum_mod.find_course(curr, code) or {}
        curr_name = str(entry.get("name") or "")

        loaded, meta = store.load_course(code)
        if meta is not None:
            metas[code] = meta

        if loaded is None:
            problems.append(
                {
                    "code": code,
                    "name": curr_name,
                    "reason": (
                        "הקטלוג הנוכחי אינו מכיל את הקבוצות של הקורס הזה. "
                        "ייתכן שהן יופיעו בבנייה הבאה שלו."
                    ),
                    "kind": "missing_data",
                    "needs_scrape": True,
                }
            )
            continue

        # ── deepcopy לפני שנוגעים במשהו. ה-Store מחזיר אובייקטים חיים. ──
        course = copy.deepcopy(loaded)

        if not course.groups:
            problems.append(
                {
                    "code": code,
                    "name": course.name or curr_name,
                    "reason": "לא נמצאו קבוצות לקורס הזה — ייתכן שהוא אינו נפתח בסמסטר המבוקש.",
                    "kind": "no_groups",
                    "needs_scrape": False,
                }
            )
            continue

        stored_semester = str(getattr(meta, "semester", "") or "")
        if semester and stored_semester and stored_semester != semester:
            problems.append(
                {
                    "code": code,
                    "name": course.name or curr_name,
                    "reason": (
                        f"הנתונים שבקטלוג הם לסמסטר {stored_semester}, ולא לסמסטר {semester}."
                    ),
                    "kind": "semester_mismatch",
                    "needs_scrape": True,
                }
            )
            continue

        # ── מה שהמנוע צריך ולא נמצא בדף המערכת ──
        tied = [other for other in curriculum_mod.tied_group(curr, code) if other != code]
        course.tied_with = tied
        # נ"ז לפי סדר ההכרעה היחיד: תוכנית → פרטי הידיעון → דף המערכת.
        # ‏``course.credits`` נשאר ``float`` — כך המודל מצהיר, וכך ``render``
        # ומודולים אחרים ממשיכים לעבוד. ההכרעה המלאה (כולל "לא ידוע" ואת
        # מקורה) נתלית לצד המודל בשדה נלווה, ונקראת ב-``_course_credits``.
        resolved_credits, credits_src = resolve_credits(code, entry=entry, course=course)
        if resolved_credits is not None:
            course.credits = float(resolved_credits)
        course.credits_resolved = resolved_credits  # type: ignore[attr-defined]
        course.credits_source = credits_src  # type: ignore[attr-defined]
        if not course.name and curr_name:
            course.name = curr_name

        courses.append(course)

    return courses, problems, metas


def resolve_pins(
    courses: list[models.Course], pinned: dict[str, dict[str, str]]
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    """‏מאמת נעיצות מול הקורסים שנטענו — ומחזיר אותן. **בלי לגעת בקורסים.**

    ‏SPEC_WEB מציע לנעוץ בעזרת ``course.groups = [g for g in ... ]``, אבל מחיקה
    כזו מוציאה את הקבוצות האחיות גם מהאינדקס ‏(קורס, קבוצה) → סוג שהמנוע בונה
    ב-``scheduler._kind_index``. מזהה ש-``linked_to`` מצביע עליו הופך אז
    ל"לא מוכר", ו-``scheduler._link_allows`` מפסיק לאכוף אותו — כלומר נעיצה
    הייתה **מכבה בשקט** את אילוצי הקישור ומחזירה מערכות שאי אפשר להירשם אליהן.
    לכן הנעיצה כאן היא *מסננת על הבחירות* (``pins_satisfied``), והקורסים
    מגיעים למנוע שלמים.

    Returns:
        ``(applied, dropped)``. ``dropped`` הן נעיצות שאי אפשר לכבד — קבוצה
        שאינה קיימת עוד (נתונים שהתעדכנו, או ‏localStorage ישן), כל אחת עם
        סיבה בעברית. הן **אינן** נבלעות בשקט: הקורא/ת חייב/ת להחזיר אותן
        ללקוח, אחרת נוצר בדיוק השקט שהאפליקציה נועדה למנוע.
    """
    by_code = {c.code: c for c in courses}
    applied: dict[str, dict[str, str]] = {}
    dropped: list[dict[str, str]] = []

    for code, by_kind in (pinned or {}).items():
        course = by_code.get(code)
        if course is None:
            # קורס שלא נבחר (או שאין לו נתונים) — הנעיצה פשוט לא רלוונטית.
            continue
        for kind, group_id in by_kind.items():
            candidates = course.groups_of(kind)
            if not candidates:
                dropped.append(
                    {
                        "code": code,
                        "kind": kind,
                        "group_id": group_id,
                        "reason": strings_mod.fmt(
                            "server.pins.kindMissing", code=code, kind=kind
                        ),
                    }
                )
                continue
            if not any(g.group_id == group_id for g in candidates):
                dropped.append(
                    {
                        "code": code,
                        "kind": kind,
                        "group_id": group_id,
                        "reason": strings_mod.fmt(
                            "server.pins.groupMissing",
                            group=group_id,
                            kind=kind,
                            code=code,
                        ),
                    }
                )
                continue
            applied.setdefault(code, {})[kind] = group_id

    return applied, dropped


def pins_satisfied(
    selection: models.Selection, applied: dict[str, dict[str, str]]
) -> bool:
    """האם הבחירה מכבדת את כל הנעיצות. **זו** הנעיצה בפועל — מסננת, לא מחיקה."""
    for code, by_kind in (applied or {}).items():
        for kind, group_id in by_kind.items():
            group = selection.group_for(code, kind)
            if group is None or group.group_id != group_id:
                return False
    return True


def _pin_filtered(
    courses: list[models.Course], applied: dict[str, dict[str, str]]
) -> list[models.Course]:
    """עותק מסונן לפי הנעיצות — **לאבחון בלבד**, אף פעם לא לספירה או לפתרון.

    ``diagnose_infeasibility``/``relax_suggestions`` מסבירות למה אין פתרון,
    ולשם כך הן צריכות לראות את המרחב המצומצם. הן לא סופרות ולא בונות מערכות,
    ולכן עיוות ה-linked_to שהמחיקה גורמת אינו נוגע באף מספר שמוחזר ללקוח.
    """
    if not applied:
        return courses
    trimmed = copy.deepcopy(courses)
    for course in trimmed:
        for kind, group_id in (applied.get(course.code) or {}).items():
            course.groups = [
                g for g in course.groups if g.kind != kind or g.group_id == group_id
            ]
    return trimmed



def _node_budget(courses: list[models.Course], prefs: scheduler_mod.Preferences) -> int:
    """מכסת הצמתים שהמנוע עצמו היה בוחר. נפילה חיננית אם הפרטים ישתנו."""
    try:
        return int(scheduler_mod._node_budget(courses, prefs))  # noqa: SLF001
    except Exception:  # noqa: BLE001
        return int(getattr(scheduler_mod, "DEFAULT_NODE_LIMIT", 200_000))


def _count_and_min_days(
    courses: list[models.Course],
    prefs: scheduler_mod.Preferences,
    pins: dict[str, dict[str, str]] | None = None,
) -> tuple[int, int | None, bool]:
    """מעבר **אחד** על ``enumerate_selections``: כמה צירופים, ומה מינימום הימים.

    זה מה שמאפשר לממשק לומר את האמת — "4 ימים אינם אפשריים, המינימום הוא 5" —
    במקום להחזיר בשקט מערכת בת 5 ימים ולתת לחשוב שזה מה שביקשו.

    ``pins`` מסננות את **הזרם** (``pins_satisfied``), לא את הקורסים: מחיקת
    קבוצות הייתה מכבה את אילוצי ה-linked_to ומנפחת את הספירה (ראי
    ``resolve_pins``).

    Returns:
        ``(feasible_count, min_days, truncated)``. ``min_days`` הוא ``None``
        כשאין אף צירוף.
    """
    count = 0
    min_days: int | None = None
    truncated = False
    budget = _node_budget(courses, prefs)
    try:
        for selection in scheduler_mod.enumerate_selections(courses, prefs, limit=budget):
            if pins and not pins_satisfied(selection, pins):
                continue
            count += 1
            days = len(selection.days_used())
            if min_days is None or days < min_days:
                min_days = days
    except scheduler_mod.SearchExhausted:
        truncated = True
    return count, min_days, truncated


def _has_solution(
    courses: list[models.Course],
    prefs: scheduler_mod.Preferences,
    pins: dict[str, dict[str, str]] | None = None,
) -> tuple[bool, bool]:
    """האם קיים ולו צירוף אחד שמכבד את הנעיצות. עוצר בראשון שנמצא.

    Returns:
        ``(has_solution, truncated)``.
    """
    budget = _node_budget(courses, prefs)
    try:
        for selection in scheduler_mod.enumerate_selections(courses, prefs, limit=budget):
            if pins and not pins_satisfied(selection, pins):
                continue
            return True, False
        return False, False
    except scheduler_mod.SearchExhausted:
        # לא הוכח שאין — רק שלא הספקנו. לא נטען שזה מבוי סתום.
        return True, True


def _schedule_sort_key(sched: models.ScoredSchedule) -> tuple:
    """סדר הדירוג של המנוע עצמו. נפילה חיננית אם העוזר הפרטי ישתנה."""
    try:
        return tuple(scheduler_mod._sort_key(sched))  # noqa: SLF001
    except Exception:  # noqa: BLE001
        return (-float(sched.score), int(sched.days_count), int(sched.gap_minutes))


def _top_schedules(
    courses: list[models.Course],
    prefs: scheduler_mod.Preferences,
    top_n: int,
    pins: dict[str, dict[str, str]] | None = None,
) -> list[models.ScoredSchedule]:
    """‏``top_n`` המערכות הטובות ביותר **שמכבדות את הנעיצות**.

    בלי נעיצות זה בדיוק ``scheduler.solve``. עם נעיצות זו אותה מנייה ואותו
    ``scheduler.score`` ואותו סדר — רק עם מסננת על הבחירות, כי הקורסים
    חייבים להגיע למנוע שלמים (ראי ``resolve_pins``).

    Raises:
        scheduler.Infeasible: אין אף מערכת שמכבדת את הנעיצות.
    """
    if not pins:
        return scheduler_mod.solve(courses, prefs, top_n=top_n)

    keep = max(1, int(top_n))
    prune_at = max(200, keep * 20)
    budget = _node_budget(courses, prefs)
    kept: list[models.ScoredSchedule] = []
    hit_limit = False
    try:
        for selection in scheduler_mod.enumerate_selections(courses, prefs, limit=budget):
            if not pins_satisfied(selection, pins):
                continue
            kept.append(scheduler_mod.score(selection, prefs))
            if len(kept) >= prune_at:
                kept.sort(key=_schedule_sort_key)
                del kept[keep:]
    except scheduler_mod.SearchExhausted:
        hit_limit = True

    if not kept:
        raise scheduler_mod.Infeasible(
            scheduler_mod.diagnose_infeasibility(_pin_filtered(courses, pins), prefs)
        )

    kept.sort(key=_schedule_sort_key)
    best = kept[:keep]
    for sched in best:
        sched.truncated = hit_limit  # type: ignore[attr-defined]
    return best



def _dead_end_reason(group: models.Group, prefs: scheduler_mod.Preferences) -> str:
    """למה הקבוצה הזו מובילה למבוי סתום — קונקרטי כשאפשר."""
    try:
        problems = scheduler_mod._unary_violations(group, prefs)  # noqa: SLF001
    except Exception:  # noqa: BLE001
        problems = []
    if problems:
        return f"הקבוצה נחסמת על ידי המגבלות שהוגדרו — {problems[0][1]}"
    return DEAD_END_REASON


def compute_viability(
    codes: Iterable[str],
    pinned: dict[str, dict[str, str]],
    prefs: scheduler_mod.Preferences,
    *,
    semester: str = "",
    year: str = "",
) -> tuple[dict[str, dict[str, dict[str, dict[str, Any]]]], bool, bool]:
    """‏**ההתנהגות החשובה ביותר באפליקציה.**

    לכל קבוצה של כל קורס נבחר: לפתור מחדש כשהקבוצה הזו נעוצה **בנוסף**
    לנעיצות הקיימות, ולרשום אם נשאר פתרון. ‏~27 פתרונות × ~1ms ≈ 40ms.

    בלי זה, אפשר ללחוץ על אפשרות שמשאירה את הסמסטר בלי פתרון ולגלות את זה
    רק אחר כך — וזה בדיוק הכישלון שהאפליקציה הזו נועדה למנוע.

    Returns:
        ``(viability, truncated, skipped)`` — המפתחות: ``[code][kind][group_id]``,
        והערך ``{"ok": True}`` או ``{"ok": False, "reason": "<עברית>"}``.
    """
    base, _problems, _metas = _build_courses(codes, semester=semester, year=year)
    if not base:
        return {}, False, False

    total_groups = sum(len(c.groups) for c in base)
    if total_groups > MAX_VIABILITY_GROUPS:
        LOG.warning("דילוג על חישוב viability: %d קבוצות (מעל %d)", total_groups, MAX_VIABILITY_GROUPS)
        return {}, False, True

    viability: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    truncated = False

    # הנעיצות הקיימות מאומתות פעם אחת. נעיצה שכבר אינה תקפה פשוט אינה
    # משתתפת — הקורא/ת (``solve``) הוא זה שמדווח עליה ללקוח.
    base_pins, _dropped = resolve_pins(base, pinned or {})

    for course in base:
        for group in course.groups:
            # ‏``base`` אינו משתנה יותר (הנעיצה היא מסננת), ולכן אין צורך
            # לטעון עותק חדש מהמסד לכל קבוצה.
            trial_pins = {c: dict(k) for c, k in base_pins.items()}
            trial_pins.setdefault(course.code, {})[group.kind] = group.group_id

            alive, hit_limit = _has_solution(base, prefs, trial_pins)
            truncated = truncated or hit_limit
            entry: dict[str, Any] = (
                {"ok": True} if alive else {"ok": False, "reason": _dead_end_reason(group, prefs)}
            )
            viability.setdefault(course.code, {}).setdefault(group.kind, {})[group.group_id] = entry

    return viability, truncated, False


# ===========================================================================
# 6א. שליפה על-פי-דרישה — ידיעון בלי התחברות (GROUND_TRUTH §9)
#
# הידיעון עונה על ``S_LOOK_FOR_NOSE`` בלי שום הזדהות, ולכן קורס שאין לו
# נתונים אינו חייב להישאר "אין נתונים במסד" עד הרענון הבא — אפשר להביא אותו
# עכשיו. השליפה עצמה שייכת ל-``yedion_http.YedionHTTP``, הפענוח ל-``parser``
# והשמירה ל-``store``; כאן רק מחברים ביניהם ומתרגמים תקלות לעברית.
#
# נימוס: שום דבר לא מווסת אותנו יותר, ולכן אנחנו מווסתים את עצמנו —
# ``MAX_ONDEMAND_FETCHES`` לבקשה, ``FETCH_DELAY_S`` בין בקשות, ומביאים רק את
# מה שחסר או מיושן.
# ===========================================================================
def _network_allowed() -> bool:
    """האם מותר לפנות לרשת מתוך בקשת HTTP.

    ההגדרה ``allow_network`` גוברת בשני הכיוונים. ברירת המחדל האוטומטית היא
    **לא לפנות לרשת בתוך הרצת בדיקות**: חבילת הבדיקות רצה מול ``data/db``
    האמיתי, ושליפה אמיתית באמצע בדיקה הייתה כותבת לתוכו קורס שאיש לא ביקש —
    ומשנה את המסד שהבדיקות עצמן מתארות.
    """
    flag = _config().get("allow_network")
    if flag is not None:
        return bool(flag)
    return "pytest" not in sys.modules


def _yedion_module():
    """‏``src/yedion_http.py`` — בייבוא עצל. ``None`` אם הוא לא זמין.

    עצל בכוונה: המודול נכתב בקובץ נפרד, והאפליקציה חייבת לעלות (ולהגיש את כל
    שאר נקודות הקצה) גם אם הוא חסר או שבור.
    """
    try:
        return importlib.import_module("yedion_http")
    except Exception as exc:  # noqa: BLE001
        LOG.warning("yedion_http אינו זמין: %s: %s", type(exc).__name__, exc)
        return None


class _Pacer:
    """שומר מרווח מזערי בין בקשות רשת עוקבות.

    מודד את הזמן שכבר עבר מאז הבקשה הקודמת, ולכן אם השולף כבר השהה בעצמו —
    לא מוסיפים השהיה שנייה מיותרת.
    """

    def __init__(self, min_gap: float = FETCH_DELAY_S) -> None:
        self.min_gap = max(0.0, float(min_gap))
        self._last: float | None = None

    def wait(self) -> None:
        now = time.monotonic()
        if self._last is not None and self.min_gap > 0:
            remaining = self.min_gap - (now - self._last)
            if remaining > 0:
                time.sleep(remaining)
        self._last = time.monotonic()


def _course_meta(**values: Any) -> store_mod.CourseMeta:
    """בונה ``store.CourseMeta`` ומעביר רק שדות שהוא באמת מכריז עליהם.

    ``store.py`` שייך לסוכן אחר; שדה שיתווסף או ייעלם שם לא צריך להפיל שליפה.
    """
    try:
        known = {f.name for f in dataclasses.fields(store_mod.CourseMeta)}
    except TypeError:  # pragma: no cover - לא dataclass
        known = set(values)
    return store_mod.CourseMeta(**{k: v for k, v in values.items() if k in known})


def _course_url(fetcher: Any, code: str) -> str:
    """הכתובת שממנה נשלף הקורס — למטא-דאטה בלבד. ריק אם אי אפשר לדעת."""
    for owner in (fetcher, _yedion_module()):
        helper = getattr(owner, "course_url", None)
        if callable(helper):
            try:
                return str(helper(code))
            except Exception:  # noqa: BLE001
                continue
    return ""


def _construct(factory: Callable, attempts: list[dict[str, Any]]) -> Any:
    """מנסה לבנות אובייקט עם כמה צורות של ארגומנטים, מהמפורטת לפשוטה.

    החתימה של ``YedionHTTP`` (ושל שולף מוזרק בבדיקה) נקבעת בקובץ אחר, ולכן
    עדיף לנסות ולוותר בהדרגה מאשר להניח חתימה אחת ולהיכשל ב-500.
    """
    last: Exception | None = None
    for kwargs in attempts:
        try:
            return factory(**kwargs)
        except TypeError as exc:
            last = exc
            continue
    if last is not None:
        raise last
    return factory()


def _make_fetcher(
    *, year_gregorian: str = "", log: Callable[[str], None] | None = None,
    delay_s: float = FETCH_DELAY_S,
) -> tuple[Any, str, bool]:
    """מחזיר ``(שולף, שגיאה בעברית, האם הוזרק)``. השגיאה והשולף לעולם לא יחד.

    נקודת ההזרקה ``course_fetcher`` (בהגדרות המפעל) גוברת — כך אפשר לבדוק את
    כל הזרימה בלי רשת. אחרת נבנה ``yedion_http.YedionHTTP``: בלי דפדפן, בלי
    התחברות, ובלי שום נגיעה בפרטי הזדהות — אין כאלה במסלול הזה בכלל.
    """
    from flask import current_app

    raw_dir = str(_config().get("raw_dir") or "")
    injected = current_app.config.get("COURSE_FETCHER")
    if injected is not None:
        if hasattr(injected, "fetch_course"):
            return injected, "", True
        if callable(injected):
            try:
                obj = _construct(
                    injected,
                    [
                        {
                            "year": year_gregorian,
                            "delay_s": delay_s,
                            "timeout_s": FETCH_TIMEOUT_S,
                            "raw_dir": raw_dir,
                            "log": log,
                        },
                        {"year": year_gregorian, "log": log},
                        {"log": log},
                        {},
                    ],
                )
            except Exception as exc:  # noqa: BLE001
                LOG.exception("בניית השולף המוזרק נכשלה")
                return None, f"לא ניתן להפעיל את שולף הנתונים ({type(exc).__name__}).", True
            if hasattr(obj, "fetch_course"):
                return obj, "", True
        return None, "שולף הנתונים שהוגדר אינו תומך בשליפת קורס.", True

    module = _yedion_module()
    cls = getattr(module, "YedionHTTP", None) if module is not None else None
    if cls is None:
        return None, (
            "שליפה ישירה מהידיעון אינה זמינה (הרכיב yedion_http חסר). "
            "הנתונים מוגשים מהקטלוג כפי שנבנה."
        ), False
    try:
        obj = _construct(
            cls,
            [
                {
                    "year": year_gregorian,
                    "delay_s": delay_s,
                    "timeout_s": FETCH_TIMEOUT_S,
                    "raw_dir": raw_dir,
                    "log": log,
                },
                {"year": year_gregorian, "delay_s": delay_s, "log": log},
                {"year": year_gregorian, "log": log},
                {},
            ],
        )
    except Exception as exc:  # noqa: BLE001
        LOG.exception("בניית YedionHTTP נכשלה")
        return None, f"לא ניתן להפעיל את שולף הידיעון ({type(exc).__name__}).", False
    return obj, "", False


def _open_fetcher_session(fetcher: Any, year_he: str) -> str:
    """פותח סשן מול הידיעון. מחזיר שגיאה בעברית, או מחרוזת ריקה.

    ‏GROUND_TRUTH §9: ה-GET לחימום חייב לקדום את ה-POST של החלפת השנה, אחרת
    השנה חוזרת בשקט לשנה הקודמת. האכיפה עצמה היא בתוך ``open_session``; כאן
    רק מתרגמים כישלון לעברית — כולל את מקרה השנה השגויה, שהוא בדיוק הכשל
    שהבדיקה הזו נועדה לתפוס.
    """
    opener = getattr(fetcher, "open_session", None)
    if not callable(opener):
        return ""
    try:
        opener()
    except Exception as exc:  # noqa: BLE001
        LOG.exception("open_session נכשל")
        name = type(exc).__name__
        if "Year" in name:
            return (
                f"הידיעון החזיר שנת לימודים שאינה {year_he or 'המבוקשת'}. "
                "השליפה נעצרה כדי שלא ייכנסו נתונים של שנה אחרת."
            )
        return f"לא ניתן להתחבר לידיעון ({name}). כדאי לבדוק את חיבור האינטרנט ולנסות שוב."
    return ""


def _page_year_mismatch(html: str, year_he: str) -> str:
    """בודק שהדף עצמו מצהיר על השנה המבוקשת. מחזיר הסבר, או מחרוזת ריקה.

    זו הבדיקה שתופסת את הכשל של "חימום שנשכח": ‏200 תקין, נתונים מלאים, שנה
    שגויה, אפס שגיאות. עדיף לוותר על הקורס מאשר לשמור נתון של שנה אחרת.
    """
    if not year_he:
        return ""
    try:
        found = parser_mod.extract_page_year(html)
    except Exception:  # noqa: BLE001 - אין תווית, אין סתירה
        return ""
    if not found or _norm_year(found) == _norm_year(year_he):
        return ""
    return (
        f"הדף שהתקבל מהידיעון הוא לשנת {found} ולא לשנת {year_he}. "
        "הנתונים לא נשמרו כדי שלא תיכנס שנה שגויה."
    )


def fetch_courses_into_store(
    codes: Iterable[str],
    *,
    semester: str,
    year_he: str,
    year_gregorian: str,
    emit: Callable[[str], None] | None = None,
    cap: int = MAX_ONDEMAND_FETCHES,
    delay_s: float = FETCH_DELAY_S,
    fetcher: Any = None,
) -> dict[str, Any]:
    """שולף קורסים מהידיעון, מפענח, ושומר. **לעולם לא זורק על כישלון של קורס.**

    זו המנוע המשותף לשני המסלולים: השליפה על-פי-דרישה של ``/api/courses``
    והרענון של ``/api/scrape/start``. שניהם צריכים בדיוק את אותו דבר — שולף
    אחד, נימוס אחד, ותרגום תקלות אחיד לעברית.

    Returns:
        מילון דוח: ``fetched`` / ``failed`` / ``skipped`` / ``changes`` /
        ``log`` / ``error``. קורס אחד שנכשל לא מפיל את השאר, ולא את הבקשה.
    """
    lines: list[str] = []

    def say(text: str) -> None:
        lines.append(str(text))
        if emit is not None:
            try:
                emit(str(text))
            except Exception:  # noqa: BLE001 - יומן לא מפיל שליפה
                LOG.exception("כתיבה ליומן נכשלה")

    wanted = [str(c) for c in codes]
    report: dict[str, Any] = {
        "requested": list(wanted),
        "fetched": [],
        "failed": [],
        "skipped": [],
        "changes": {},
        "not_offered": [],
        "log": lines,
        "error": "",
        "cap": int(cap),
        "delay_s": float(delay_s),
    }
    if not wanted:
        return report

    head, tail = wanted[: max(0, int(cap))], wanted[max(0, int(cap)) :]
    for code in tail:
        report["skipped"].append(
            {
                "code": code,
                "reason": (
                    f"בבקשה אחת נשלפים עד {cap} קורסים כדי לא להעמיס על שרת המכללה. "
                    f"הקורס {code} יישלף בפעם הבאה."
                ),
            }
        )
    if not head:
        return report

    owned = fetcher is None
    injected = False
    if owned:
        fetcher, error, injected = _make_fetcher(
            year_gregorian=year_gregorian, log=say, delay_s=delay_s
        )
        if fetcher is None:
            report["error"] = error
            for code in head:
                report["failed"].append({"code": code, "reason": error})
            say(error)
            return report
        error = _open_fetcher_session(fetcher, year_he)
        if error:
            report["error"] = error
            for code in head:
                report["failed"].append({"code": code, "reason": error})
            say(error)
            return report

    store = _store()
    curr = _curriculum()
    # שולף מוזרק (בדיקה/הרחבה) לא נוגע ברשת, ולכן אין את מי לכבד בהשהיה.
    # שולף שהתקבל מבחוץ — הקורא/ת קבע/ה את הקצב ואנחנו מכבדים את הקביעה.
    pacer = _Pacer(0.0 if injected else delay_s)

    for code in head:
        entry = curriculum_mod.find_course(curr, code) or {}
        fallback_name = str(entry.get("name") or "")
        fallback_credits = entry.get("credits")

        pacer.wait()
        say(f"מביא קורס {code} מהידיעון…")
        try:
            html = fetcher.fetch_course(code)
        except Exception as exc:  # noqa: BLE001 - קורס אחד לא מפיל את השאר
            # תקלת רשת/קורס חסר היא מצב צפוי, לא קריסה: שורת אזהרה בצד השרת
            # והסבר בעברית ללקוח — בלי traceback שנשפך למסך.
            LOG.warning("שליפת %s נכשלה: %s: %s", code, type(exc).__name__, exc)
            name = type(exc).__name__
            reason = (
                f"הידיעון החזיר שנה שגויה עבור {code}."
                if "Year" in name
                else f"לא ניתן היה לשלוף את הקורס {code} מהידיעון ({name})."
            )
            report["failed"].append({"code": code, "reason": reason})
            say(f"שגיאה בקורס {code}: {reason}")
            continue

        mismatch = _page_year_mismatch(html, year_he)
        if mismatch:
            report["failed"].append({"code": code, "reason": mismatch})
            say(f"שגיאה בקורס {code}: {mismatch}")
            continue

        try:
            parsed = parser_mod.parse_course_page(
                html, code, fallback_name=fallback_name, semester=semester or None
            )
        except Exception as exc:  # noqa: BLE001
            LOG.exception("פענוח %s נכשל", code)
            reason = f"לא ניתן היה לפענח את דף הקורס {code} ({type(exc).__name__})."
            report["failed"].append({"code": code, "reason": reason})
            say(f"שגיאה בקורס {code}: {reason}")
            continue

        course = parsed.course
        warnings = [str(w) for w in (parsed.warnings or [])]
        if course is None:
            # GROUND_TRUTH §6: דף תקין בלי קבוצות הוא תשובה ("לא נפתח"), לא תקלה.
            reason = (
                f"הידיעון לא מציג קבוצות לקורס {code} בסמסטר "
                f"{semester or '?'} בשנת {year_he or '?'} — ייתכן שהוא אינו נפתח."
            )
            report["not_offered"].append({"code": code, "reason": reason})
            report["failed"].append({"code": code, "reason": reason})
            say(reason)
            continue

        if not getattr(course, "credits", 0) and fallback_credits:
            course.credits = float(fallback_credits)

        group_count = len(course.groups or [])
        stamp = _now_iso()
        meta = _course_meta(
            fetched_at=stamp,
            attempted_at=stamp,
            last_attempt_at=stamp,
            year=year_he,
            year_gregorian=year_gregorian,
            semester=semester,
            source_url=_course_url(fetcher, code),
            content_sha1=store_mod.content_sha1(html),
            group_count=group_count,
            warnings=warnings,
            ok=True,
        )
        try:
            changes = store.save_course(course, meta) or []
        except Exception as exc:  # noqa: BLE001
            LOG.exception("שמירת %s נכשלה", code)
            reason = f"לא ניתן היה לשמור את הקורס {code} ({type(exc).__name__})."
            report["failed"].append({"code": code, "reason": reason})
            say(f"שגיאה בקורס {code}: {reason}")
            continue

        report["fetched"].append(code)
        report["changes"][code] = [str(c) for c in changes]
        if group_count == 0:
            report["not_offered"].append(
                {
                    "code": code,
                    "reason": (
                        f"הידיעון לא מציג אף קבוצה לקורס {code} בסמסטר "
                        f"{semester or '?'} — ייתכן שהוא אינו נפתח."
                    ),
                }
            )
        say(f"נשמר {code}: {group_count} קבוצות, {len(changes)} שינויים.")

    return report


def fetch_catalog_into_store(
    *,
    year_he: str,
    year_gregorian: str,
    emit: Callable[[str], None] | None = None,
    fetcher: Any = None,
) -> dict[str, Any]:
    """מביא את הקטלוג המלא בבקשה **אחת** ושומר אותו.

    ‏GROUND_TRUTH §9: ``S_LOOK_FOR_NOSE_AB`` מחזיר את כל הקטלוג בבת אחת. אין
    לולאה על האלפבית — זו הייתה 22 בקשות במקום אחת.
    """

    def say(text: str) -> None:
        if emit is not None:
            try:
                emit(str(text))
            except Exception:  # noqa: BLE001
                LOG.exception("כתיבה ליומן נכשלה")

    report: dict[str, Any] = {"ok": False, "count": 0, "error": "", "warnings": []}
    if fetcher is None:
        fetcher, error, _injected = _make_fetcher(year_gregorian=year_gregorian, log=say)
        if fetcher is None:
            report["error"] = error
            say(error)
            return report
        error = _open_fetcher_session(fetcher, year_he)
        if error:
            report["error"] = error
            say(error)
            return report

    grabber = getattr(fetcher, "fetch_catalog", None)
    if not callable(grabber):
        report["error"] = "שליפת הקטלוג אינה נתמכת בשולף הנוכחי."
        say(report["error"])
        return report

    say("מביא את קטלוג הקורסים המלא…")
    try:
        html = grabber()
        catalog, warnings = discovery_mod.parse_catalog(html)
    except Exception as exc:  # noqa: BLE001
        LOG.exception("שליפת הקטלוג נכשלה")
        report["error"] = f"לא ניתן היה להביא את הקטלוג ({type(exc).__name__})."
        say(report["error"])
        return report

    if not catalog:
        report["error"] = "הקטלוג שהתקבל ריק — הנתונים הקיימים נשמרו כמו שהם."
        say(report["error"])
        return report

    try:
        _store().save_catalog(catalog, year_he, year_gregorian)
    except Exception as exc:  # noqa: BLE001
        LOG.exception("שמירת הקטלוג נכשלה")
        report["error"] = f"לא ניתן היה לשמור את הקטלוג ({type(exc).__name__})."
        say(report["error"])
        return report

    report.update({"ok": True, "count": len(catalog), "warnings": [str(w) for w in warnings]})
    say(f"קטלוג: נשמרו {len(catalog)} קורסים.")
    return report


def _details_to_dict(parsed: Any) -> dict[str, Any]:
    """‏``parser.CourseDetails`` → ‏dict, בלי להניח שהוא NamedTuple דווקא."""
    if isinstance(parsed, dict):
        return dict(parsed)
    as_dict = getattr(parsed, "_asdict", None)
    if callable(as_dict):
        with contextlib.suppress(Exception):
            return dict(as_dict())
    if dataclasses.is_dataclass(parsed) and not isinstance(parsed, type):
        with contextlib.suppress(Exception):
            return dataclasses.asdict(parsed)
    fields = (
        "code", "name", "credits", "hours", "weekly_hours",
        "language", "description", "prerequisites", "warnings",
    )
    return {name: getattr(parsed, name) for name in fields if hasattr(parsed, name)}


def _details_payload_is_empty(payload: Any) -> bool:
    """האם הפענוח לא למד **כלום** — דף שגיאה, או קוד שהידיעון אינו מגיש.

    ‏GROUND_TRUTH §6: הידיעון עונה ‏200 גם לקוד שאין לו, עם דף בלי תוכן, וגם
    דף שגיאת ‏ASP.NET חוזר כ-200. ``parse_course_details`` מפענח אותם בלי
    לזרוק (וזה נכון), אבל שמירת התוצאה כהצלחה עם חותמת טרייה מקפיאה את
    הקורס לשבעה ימים: ``details_stale`` מחזיר ‏False, ``has_details`` מחזיר
    ‏True, ואין ניסיון חוזר גם אחרי שהידיעון התאושש.

    ‏0.0 נ"ז או שם ריק כשלעצמם אינם "ריק" — רק היעדר *כל* השדות.
    """
    if not isinstance(payload, dict):
        return True
    for key in ("name", "language", "description"):
        if str(payload.get(key) or "").strip():
            return False
    for key in ("credits", "weekly_hours"):
        if payload.get(key) is not None:
            return False
    if payload.get("hours"):
        return False
    if payload.get("prerequisites"):
        return False
    return True


def _fetch_details_page(fetcher: Any, code: str) -> str:
    """מביא את עמוד ``S_CourseDetails`` — עם סלחנות לחתימות שונות.

    ‏``yedion_http`` נכתב בקובץ של סוכן אחר; חתימה שהתרחבה או הצטמצמה לא
    צריכה להפיל שליפה שכל כולה העשרה.
    """
    grabber = getattr(fetcher, "fetch_details", None)
    if not callable(grabber):
        raise AttributeError("fetch_details")
    for args, kwargs in (
        ((code,), {}),
        ((code,), {"group_id": "0"}),
        ((code,), {"group_id": "0", "kind_code": "1"}),
    ):
        try:
            return str(grabber(*args, **kwargs))
        except TypeError:
            continue
    return str(grabber(code))


def fetch_details_into_store(
    codes: Iterable[str],
    *,
    year_he: str = "",
    year_gregorian: str = "",
    emit: Callable[[str], None] | None = None,
    cap: int = MAX_ONDEMAND_DETAIL_FETCHES,
    delay_s: float = FETCH_DELAY_S,
    fetcher: Any = None,
) -> dict[str, Any]:
    """מביא **פרטי קורס** (‏S_CourseDetails) ושומר אותם. לעולם לא זורק.

    זה מה שהופך את הכלי לרב-מחלקתי: נ"ז, פירוט שעות ותנאי קדם לקורס שאינו
    ב-``curriculum.json`` בכלל. הדף פתוח לקריאה בלי התחברות בדיוק כמו דף
    המערכת (‏GROUND_TRUTH §9).

    נימוס: רק לקורסים שנמסרו (כלומר: שנבחרו בפועל), תקרה לבקשה, השהיה בין
    בקשות, וחלון טריות של שבעה ימים — פרטים כמעט אינם משתנים.

    Returns:
        ``{"supported", "requested", "fetched", "failed", "skipped", "log",
        "error", "cap", "delay_s", "max_age_hours"}``.
    """
    lines: list[str] = []

    def say(text: str) -> None:
        lines.append(str(text))
        if emit is not None:
            try:
                emit(str(text))
            except Exception:  # noqa: BLE001
                LOG.exception("כתיבה ליומן נכשלה")

    wanted = [str(c).strip() for c in codes if str(c or "").strip()]
    report: dict[str, Any] = {
        "supported": True,
        "requested": list(wanted),
        "fetched": [],
        "failed": [],
        "skipped": [],
        "log": lines,
        "error": "",
        "cap": int(cap),
        "delay_s": float(delay_s),
        "max_age_hours": DETAILS_MAX_AGE_HOURS,
    }
    if not wanted:
        return report

    store = _store()
    parse = getattr(parser_mod, "parse_course_details", None)
    saver = getattr(store, "save_details", None)
    if not callable(parse) or not callable(saver):
        report["supported"] = False
        report["error"] = (
            "פענוח או שמירה של פרטי קורס אינם זמינים בגרסה הזו — "
            "הנתונים המוצגים הם מה שכבר שמור."
        )
        report["skipped"] = [{"code": c, "reason": report["error"]} for c in wanted]
        return report

    head, tail = wanted[: max(0, int(cap))], wanted[max(0, int(cap)) :]
    for code in tail:
        report["skipped"].append(
            {
                "code": code,
                "reason": (
                    f"בבקשה אחת נשלפים פרטים של עד {cap} קורסים. "
                    f"הפרטים של {code} יושלמו בפעם הבאה."
                ),
            }
        )
    if not head:
        return report

    owned = fetcher is None
    injected = False
    if owned:
        fetcher, error, injected = _make_fetcher(
            year_gregorian=year_gregorian, log=say, delay_s=delay_s
        )
        if fetcher is None:
            report["error"] = error
            report["skipped"] += [{"code": c, "reason": error} for c in head]
            say(error)
            return report
        error = _open_fetcher_session(fetcher, year_he)
        if error:
            report["error"] = error
            report["skipped"] += [{"code": c, "reason": error} for c in head]
            say(error)
            return report

    if not callable(getattr(fetcher, "fetch_details", None)):
        report["supported"] = False
        report["error"] = (
            "שליפת פרטי קורס אינה נתמכת בשולף הנוכחי — הנתונים המוצגים הם "
            "מה שכבר שמור."
        )
        report["skipped"] += [{"code": c, "reason": report["error"]} for c in head]
        return report

    pacer = _Pacer(0.0 if injected else delay_s)
    for code in head:
        pacer.wait()
        say(f"מביא את פרטי הקורס {code} מהידיעון…")
        try:
            html = _fetch_details_page(fetcher, code)
        except Exception as exc:  # noqa: BLE001 - קורס אחד לא מפיל את השאר
            LOG.warning("שליפת פרטי %s נכשלה: %s: %s", code, type(exc).__name__, exc)
            reason = f"לא ניתן היה לשלוף את פרטי הקורס {code} ({type(exc).__name__})."
            report["failed"].append({"code": code, "reason": reason})
            say(reason)
            continue

        try:
            parsed = parse(html, code)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("פענוח פרטי %s נכשל", code)
            reason = f"לא ניתן היה לפענח את דף הפרטים של {code} ({type(exc).__name__})."
            report["failed"].append({"code": code, "reason": reason})
            say(reason)
            continue

        payload = _details_to_dict(parsed)
        if _details_payload_is_empty(payload):
            # לא שומרים. רשומה ריקה עם חותמת טרייה היא שקר שמחזיק שבוע:
            # היא משתיקה כל ניסיון חוזר ומדווחת ``has_details: true`` על
            # רשומה שאין בה דבר. ``mark_details_failed`` משאיר את מה שהיה
            # שמור, רושם את הסיבה, והרשומה נשארת מיושנת — כלומר תיבדק שוב.
            reason = (
                f"דף הפרטים של {code} חזר ריק (ייתכן שהידיעון אינו מגיש את "
                f"הקוד הזה, או שהוגשה שגיאה). לא נשמר — ייבדק שוב בפעם הבאה."
            )
            marker = getattr(store, "mark_details_failed", None)
            if callable(marker):
                try:
                    marker(code, "דף הפרטים חזר ריק")
                except Exception:  # noqa: BLE001 - סימון כישלון לא מפיל שליפה
                    LOG.exception("סימון כישלון פרטים ל-%s נכשל", code)
            report["failed"].append({"code": code, "reason": reason})
            say(reason)
            continue

        stamp = _now_iso()
        payload.setdefault("code", code)
        # החותמת נשמרת במטא של הרשומה (הארגומנט השלישי) ולא בתוך הפרטים —
        # ``load_details`` מחזיר בדיוק את מה שנשמר, ואסור ללכלך אותו.
        try:
            saver(code, payload, stamp)
        except TypeError:
            try:
                saver(code, payload, fetched_at=stamp)
            except Exception as exc:  # noqa: BLE001
                LOG.exception("שמירת פרטי %s נכשלה", code)
                reason = f"לא ניתן היה לשמור את פרטי הקורס {code} ({type(exc).__name__})."
                report["failed"].append({"code": code, "reason": reason})
                say(reason)
                continue
        except Exception as exc:  # noqa: BLE001
            LOG.exception("שמירת פרטי %s נכשלה", code)
            reason = f"לא ניתן היה לשמור את פרטי הקורס {code} ({type(exc).__name__})."
            report["failed"].append({"code": code, "reason": reason})
            say(reason)
            continue

        report["fetched"].append(code)
        got = credits_text(payload.get("credits"))
        say(f"נשמרו פרטי {code}: {got} נ\"ז.")

    return report


def _details_needing_fetch(
    codes: Iterable[str],
    *,
    max_age_hours: float | None = None,
) -> list[str]:
    """אילו מהקודים חסרים פרטים או שהפרטים שלהם ישנים מ-7 ימים.

    זה הגלגל שמונע הכפלת בקשות: בדרך המהירה (הפרטים טריים) הרשימה ריקה,
    ואז אפילו לא נבנה שולף ולא נפתח סשן.
    """
    if not _details_supported():
        return []
    wanted: list[str] = []
    for raw in codes:
        code = str(raw or "").strip()
        if code and code not in wanted:
            wanted.append(code)
    if not wanted:
        return []
    window = _details_max_age() if max_age_hours is None else float(max_age_hours)

    # ‏``stale_details_codes`` קורא את הקובץ פעם אחת לכל הרשימה במקום פעם לכל
    # קוד — עדיף בהרבה כשנבחרו עשרים קורסים.
    bulk = getattr(_store(), "stale_details_codes", None)
    if callable(bulk):
        try:
            return [str(c) for c in bulk(wanted, window)]
        except Exception:  # noqa: BLE001 - נופלים בחזרה לבדיקה קוד-קוד
            LOG.exception("בדיקת טריות הפרטים בבת אחת נכשלה")
    return [code for code in wanted if _details_stale(code, max_age_hours=window)]


def _details_fetch_supported() -> bool:
    """האם בכלל יש מי שיודע לשלוף פרטים — **בלי לבנות שולף ובלי רשת**.

    זו הבדיקה שמונעת את הנזק הגדול: בלי לוודא מראש, כל בקשה ל-``/api/courses``
    הייתה פותחת סשן מול הידיעון רק כדי לגלות ששליפת פרטים לא ממומשת — כלומר
    מוסיפה שניות למסלול המהיר ובקשה מיותרת לשרת המכללה, בכל פעם מחדש.
    """
    if not callable(getattr(parser_mod, "parse_course_details", None)):
        return False
    if not callable(getattr(_store(), "save_details", None)):
        return False
    from flask import current_app

    injected = current_app.config.get("COURSE_FETCHER")
    if injected is not None:
        if hasattr(injected, "fetch_course"):          # מופע מוכן
            return callable(getattr(injected, "fetch_details", None))
        return True                                    # מפעל — נדע רק אחרי הבנייה
    module = _yedion_module()
    cls = getattr(module, "YedionHTTP", None) if module is not None else None
    return callable(getattr(cls, "fetch_details", None))


def _stale_or_missing(
    codes: Iterable[str],
    problems: list[dict[str, Any]],
    metas: dict[str, store_mod.CourseMeta],
    *,
    year: str,
    max_age_hours: float,
) -> list[str]:
    """אילו מהקודים שווה להביא עכשיו: חסרים, מיושנים, או משנה/סמסטר אחרים.

    זהו גם כלל הנימוס מ-GROUND_TRUTH §9 — מביאים רק מה שבאמת חסר או ישן,
    ולא מרעננים בכל לחיצה את מה שכבר טרי.
    """
    blocked = {
        p["code"]
        for p in problems
        if p.get("kind") in {"missing_data", "semester_mismatch", "no_groups"}
    }
    out: list[str] = []
    for code in codes:
        meta = metas.get(code)
        if code in blocked or meta is None:
            out.append(code)
            continue
        if meta.is_stale(max_age_hours) or not _year_matches(year, meta):
            out.append(code)
    return out



# ===========================================================================
# 7. כותב יחיד ל-data/db, וחותמת זמן
#
# ‏עד לאריזה לאירוח ישבה כאן כל מכונת הגרידה החיה: ``_scrape_state``,
# ‏``_scrape_log``, ``_scrape_thread``, ומעטפת ה-stdout שקלטה את הפלט של
# ‏``refresh.main`` / ``reparse.main`` ליומן שבזיכרון. כולם הוסרו יחד עם
# ‏``POST /api/scrape/start``, ``GET /api/scrape/status`` ו-``POST /api/reparse``.
#
# ‏למה: אלה משתנים גלובליים ברמת המודול, כלומר אחד לכל *תהליך* — ותהליך
# ‏מאורח משרת את כולם בבת אחת. גרידה אחת הייתה מדווחת על עצמה לכל
# ‏הסטודנטים; ``/api/scrape/start`` היה ממסר פתוח, בלי הזדהות ובלי מגבלת
# ‏קצב, אל השרת של המכללה; והריצה עצמה קרתה **בתוך** תהליך ה-web ולא
# ‏בתת-תהליך. ‏HOSTING_NOTES.md §1 שורות 2–4, ו-§4 כלל 5 ("אין משתנים
# ‏גלובליים חדשים ב-api.py — הם פר-תהליך, ותהליך מאורח משרת את כולם").
#
# ‏בניית הקטלוג היא עכשיו עבודת cron נפרדת (``build_catalog.py`` /
# ‏``refresh.py``), והממשק מציג **מתי הקטלוג נבנה** דרך
# ‏``GET /api/catalog/meta`` במקום יומן חי. ‏HOSTING_NOTES.md §3 ו-§4 כלל 2.
#
# ‏מה שנשאר כאן הוא מה ש**אינו** שייך לגרידה ועדיין משרת את השליפה
# ‏על-פי-דרישה (סעיף 6א).
# ===========================================================================
#: כותב אחד בלבד ל-``data/db``. ``Store._atomic_write_text`` מקנה לקובץ הזמני
#: שם לפי **מזהה התהליך** בלבד, ולכן שני כותבים באותו תהליך מתנגשים על אותו
#: ``<path>.<pid>.tmp`` ונופלים ב-WinError 32. הנעילה נלקחת בבקשה שמתחילה את
#: הכתיבה ומשוחררת בסופה.
_db_write_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ===========================================================================
# 8. עזרי תצוגה
# ===========================================================================
def _semester_label(semester: str, info: dict) -> str:
    """'שנה ג׳ · סמסטר א׳ (חורף)' — התווית שהממשק מציג בשלב 1.

    ‏**בלי שנה התווית נפתחת במספר הסמסטר**: 'סמסטר 4 · סמסטר א׳ (חורף)'.
    תוכנית שנבחרת לפי מועד כניסה אינה שומרת שנת לימודים — למתקבל/ת באביב
    אין סמסטר א' בשנה א', כך שללוח שנה×סמסטר יש משבצת ריקה ומספר השנה הוא
    ניחוש. מה שידוע הוא מספר הסמסטר, והוא מה שהתווית אומרת.
    """
    year = info.get("year")
    term = str(info.get("term") or "")
    year_text = YEAR_LABELS.get(int(year), f"שנה {year}") if isinstance(year, int) else ""
    term_text = TERM_LABELS.get(term, f"סמסטר {term}" if term else "")
    lead = year_text or f"סמסטר {semester}"
    parts = [p for p in (lead, term_text) if p]
    return " · ".join(parts) or f"סמסטר {semester}"


def _gregorian_for(year_he: Any) -> str:
    """'תשפ"ז' → '2027'. לא ידוע → מחרוזת ריקה."""
    return HEBREW_YEAR_TO_GREGORIAN.get(str(year_he or "").strip(), "")


def _hebrew_year_for(gregorian: Any) -> str:
    """'2027' → 'תשפ"ז'. לא ידוע → מחרוזת ריקה.

    מחושב מהמפה שכבר קיימת כאן ולא דרך ``scraper`` — הוא מייבא את Playwright
    בזמן טעינה, ובמסלול הזה אין דפדפן בכלל.
    """
    want = str(gregorian or "").strip()
    for label, greg in HEBREW_YEAR_TO_GREGORIAN.items():
        if greg == want:
            return label
    return ""


def _year_pair(value: Any, fallback: Any = "") -> tuple[str, str]:
    """מקבל שנה בכל אחת משתי הצורות ומחזיר ``(תווית עברית, שנה לועזית)``.

    הלקוח שולח לפעמים ``"2027"`` ולפעמים ``'תשפ"ז'`` — שתיהן לגיטימיות.
    בלי הנרמול הזה, ``year="2027"`` נקרא כתווית עברית לא מוכרת, ``year_gregorian``
    יוצא ריק, **החלפת השנה כלל לא מתבצעת**, והידיעון מחזיר בשקט את השנה
    הקודמת. זה בדיוק הכשל של GROUND_TRUTH §9, רק שהפעם מקורו כאן ולא ברשת.
    """
    raw = str(value or "").strip() or str(fallback or "").strip()
    if not raw:
        return "", ""
    if raw.isdigit() and len(raw) == 4:            # לועזית -> עברית
        return _hebrew_year_for(raw) or "", raw
    return raw, _gregorian_for(raw) or ""          # עברית -> לועזית


def _meta_to_json(meta: store_mod.CourseMeta | None, max_age_hours: float) -> dict[str, Any]:
    """טריות של קורס אחד, בשפה שהממשק יכול להציג ישירות."""
    if meta is None:
        return {
            "known": False,
            "origin": "",
            "fetched_at": "",
            "age_hours": None,
            "age_text": "אין נתונים",
            "freshness_text": "אין נתונים",
            "stale": True,
            "ok": False,
            "semester": "",
            "year": "",
            "group_count": 0,
            "warnings": [],
            "last_error": "",
        }
    age = meta.age_hours()
    return {
        "known": True,
        # ‏"shipped" = הגיע עם הקוד; "db" = נשלף על המכשיר הזה. הלקוח
        # חייב את ההבחנה: רק לשני האחרונים יש חותמת שליפה של המשתמש/ת,
        # ולקטלוג שנשלח יש רק תאריך **בנייה**.
        "origin": _origin_of(meta),
        "fetched_at": meta.fetched_at,
        "age_hours": age,
        "age_text": store_mod.format_hebrew_age(age),
        "freshness_text": meta.freshness_text(),
        "stale": meta.is_stale(max_age_hours),
        "ok": bool(meta.ok),
        "semester": meta.semester,
        "year": meta.year,
        "year_gregorian": meta.year_gregorian,
        "group_count": int(meta.group_count),
        "warnings": list(meta.warnings),
        "last_error": meta.last_error,
    }


def _db_snapshot() -> dict[str, Any]:
    """מצב המסד: מה יש, כמה טרי, ומה דורש רענון."""
    store = _store()
    max_age = float(_config()["max_age_hours"])
    codes = store.codes()
    metas = store.all_meta()
    freshness = store.freshness(max_age_hours=max_age)
    return {
        "codes": codes,
        "count": len(codes),
        "tracked": store.tracked(),
        "stale": list(freshness.get("stale") or []),
        "failed": list(freshness.get("failed") or []),
        # ------------------------------------------------------------------
        # ‏טריות על **כל המסד**. ‏``any_stale``, ‏``age_text`` ו-``newest``
        # אינם נקראים עוד בכותרת, וזו לא הזנחה אלא תיקון של באג.
        #
        # ‏``Store.freshness`` מחשב על כל 572 הרשומות: ‏``age_text`` הוא הגיל
        # של ה**ישנה ביותר** מביניהן, ו-``any_stale`` נכון כשולו אחת מהן
        # מיושנת — ‏566 מתוך 572, כלומר תמיד. הכותרת הציגה את שניהם, ולכן
        # אמרה "הנתונים עודכנו לפני 11 ימים" ליד נקודה כתומה קבועה, בזמן
        # שששת הקורסים שנבחרו נשלפו באותו בוקר. הרשומה הישנה ביותר במסד
        # אינה תשובה לשאלה "כמה עדכני מה שאני רואה".
        #
        # ‏``selectedFreshness()`` ב-``app.js`` מחשב את אותו הדבר מעל
        # ``courses`` שלמטה, מוגבל לקורסים שנבחרו. **אין לחבר את הכותרת
        # חזרה לשדות האלה** — זה מחזיר את הבאג במלואו.
        #
        # הם נשארים כי הם תיאור נכון של המסד, ו-``/api/bootstrap`` הוא
        # ממשק ציבורי. שימו לב שכרגע **אף אחד אינו קורא אותם**: ‏refresh.py
        # מחשב גיל משלו מ-``fetched_at`` ואינו נוגע ב-API, וה-CLI קורא
        # ל-Store ישירות. מחיקתם היא החלטה נפרדת.
        # ------------------------------------------------------------------
        "any_stale": bool(freshness.get("stale")),
        "age_hours": freshness.get("age_hours"),
        "age_text": store_mod.format_hebrew_age(freshness.get("age_hours")),
        "text": freshness.get("text", ""),
        "newest": freshness.get("newest", ""),
        "oldest": freshness.get("oldest", ""),
        "max_age_hours": max_age,
        # מאיפה הנתונים. ‏"shipped" = הכול הגיע עם התוכנה ואיש לא שלף
        # כאן דבר; אז הכותרת מדברת על **תאריך בניית הקטלוג**, שהוא
        # היחיד שידוע. ‏built_at ריק כשאין קטלוג שנשלח.
        #
        # ‏מאז מיזוג "החדש מנצח" (ראו ``Store._load_sections_db``) כל קוד
        # שהקטלוג נושא מקבל ``fetched_at = built_at``, ולכן אחרי
        # ‏``git pull`` ‏``oldest``/``text`` שלמעלה נגזרים מהקטלוג. מה
        # שנשאר מחוץ לזה הוא קוד שהקטלוג **אינו** נושא — קורס שנשלף ידנית,
        # או קורס שהוסר מהקטלוג — ואז ``origin`` הוא "mixed" ו-``oldest``
        # הוא באמת חותמת מקומית ישנה. זה נכון, והכותרת יודעת מה לעשות עם
        # זה: ``selectedFreshness()`` שואלת רק על הקורסים שנבחרו.
        #
        # ‏מקור האמת לטריות הוא ``catalog.meta.json``, ושתי התוויות
        # שהממשק מציג — ‏"הקטלוג נבנה" מכאן, ו-``/api/catalog/meta`` —
        # קוראות אותו, ולכן אינן יכולות לסתור זו את זו.
        "origin": _db_origin(metas),
        "catalog_built_at": _shipped_built_at(),
        "courses": {code: _meta_to_json(metas.get(code), max_age) for code in codes},
    }


def _shipped_built_at() -> str:
    try:
        import shipped_catalog  # type: ignore
    except Exception:  # noqa: BLE001
        return ""
    return shipped_catalog.built_at()


def _shipped_catalog_path() -> str:
    """היכן ‏shipped_catalog מחפש. ‏מוחזר ב-/healthz כי נתיב שגוי הוא
    בדיוק התקלה שהבדיקה הזאת נועדה לתפוס, ובלי זה היא אומרת "ריק" בלי לומר
    "ריק *איפה*"."""
    try:
        import shipped_catalog  # type: ignore
    except Exception:  # noqa: BLE001
        return ""
    return str(getattr(shipped_catalog, "CATALOG_PATH", ""))


def _shipped_meta() -> dict[str, Any]:
    """‏data/catalog/catalog.meta.json כמות שהוא, או ``{}``.

    ‏זה המקור ל-``/api/catalog/meta``: הקובץ שהצינור הלילי כותב, ולא
    ספירה שנגזרת מהמסד. ההבדל חשוב כשהשניים אינם מסכימים — למשל כשמישהו
    שלף קורס בודד למסד המקומי — ואז מה שהכותרת צריכה לומר הוא מתי נבנה
    **הקטלוג**, לא כמה שורות יש במסד.
    """
    try:
        import shipped_catalog  # type: ignore
    except Exception:  # noqa: BLE001
        return {}
    try:
        return shipped_catalog.meta() or {}
    except Exception:  # noqa: BLE001
        LOG.exception("קריאת catalog.meta.json נכשלה")
        return {}


def _db_origin(metas: dict) -> str:
    """‏"shipped" אם אף רשומה לא נשלפה על המכשיר הזה, אחרת "mixed"/"db"."""
    kinds = {_origin_of(m) for m in metas.values()} or {"db"}
    if kinds == {"shipped"}:
        return "shipped"
    return "mixed" if "shipped" in kinds else "db"


def _catalog_snapshot() -> tuple[dict[str, dict], dict[str, Any]]:
    """הקטלוג החי + סיכום קצר עליו."""
    store = _store()
    catalog, meta = store.load_catalog()
    age = store_mod.age_hours_since(meta.get("fetched_at")) if meta else None
    summary = {
        "count": len(catalog),
        "year": meta.get("year", ""),
        "year_gregorian": meta.get("year_gregorian", ""),
        "fetched_at": meta.get("fetched_at", ""),
        "age_hours": age,
        "age_text": store_mod.format_hebrew_age(age),
        "empty": not catalog,
    }
    return catalog, summary


# ===========================================================================
# 9. ה-Blueprint
# ===========================================================================
bp = Blueprint("api", __name__, url_prefix="/api")


# ---------------------------------------------------------------- bootstrap
@bp.get("/bootstrap")
@_endpoint
def bootstrap():
    """כל מה שהממשק צריך בפתיחה: ברירות מחדל, סמסטרים, טריות, קטלוג, גרידה.

    ‏``curriculum_available`` (וגם ``curriculum.available``) אומר מיד, בצביעה
    הראשונה, אם יש בכלל תוכנית לימודים טעונה. בלעדיו הממשק היה מציג רשימת
    קורסים ריקה לסטודנט/ית שהמסלול שלהם אינו ב-rec.pdf, ורק אחר כך מגלה
    שצריך לעבור לעיון בקטלוג — הבהוב שגם מבלבל וגם נראה כמו תקלה.
    ‏SPEC_MULTIFACULTY §4.
    """
    curr = _curriculum()
    profile = _profile()
    student = profile.get("student") or {}
    prefs = profile.get("preferences") or {}
    # מועד הכניסה של הסטודנט/ית, למסלול שיש לו מועדים. הוא חלק מהזהות
    # בדיוק כמו שנה וסמסטר, ולכן הוא נקרא מהפרופיל ולא מפרמטר.
    my_program = str(student.get("program") or "")
    my_intake = str(student.get("intake") or "")
    has_curriculum = _curriculum_available(curr)

    def semester_rows(source: dict) -> list[dict]:
        rows = []
        for key in sorted((source.get("semesters") or {}).keys(), key=lambda k: (len(k), k)):
            try:
                info = curriculum_mod.semester_info(source, key)
            except curriculum_mod.UnknownSemesterError:  # pragma: no cover
                continue
            courses = curriculum_mod.semester_courses(source, key)
            rows.append(
                {
                    "semester": key,
                    "year": info.get("year"),
                    "term": info.get("term", ""),
                    "year_label": YEAR_LABELS.get(info.get("year"), ""),
                    "term_label": TERM_LABELS.get(str(info.get("term") or ""), ""),
                    "label": _semester_label(key, info),
                    "total": info.get("total") or {},
                    "plus": info.get("plus", ""),
                    "course_count": len(courses),
                    # השנה והסמסטר אינם כתובים באף פרק שנתון — הם נגזרים
                    # ממספר הסמסטר. הדגל הזה קיים כדי שלא נציג נגזרת כעובדה.
                    "year_term_inferred": bool(info.get("year_term_inferred")),
                }
            )
        return rows

    semesters = semester_rows(curr)
    # מיפוי שנה+סמסטר -> מספר סמסטר נעשה בדפדפן לפני כל משיכה, ולכן הוא
    # חייב להכיר את כל המסלולים מראש. מתמטיקה שימושית, למשל, היא תוכנית
    # תלת-שנתית בת שישה סמסטרים, ולוח של שמונה היה שגוי עבורה.
    semesters_by_program = {
        str(data.get("program") or ""): semester_rows(data)
        for data in _curricula().values()
        if data.get("program")
    }
    # מסלול עם מועדי כניסה אינו נכנס למפה שלמעלה: אין לו לוח סמסטרים אחד.
    # ‏הממשק מחליף מועד בלי לבקש ‏bootstrap מחדש, ולכן **שני** הלוחות
    # נשלחים כאן ומי שנבחר נקרא בדפדפן.
    semesters_by_program_intake = {
        str(next(iter(plans.values())).get("program") or ""): {
            intake_id: semester_rows(data) for intake_id, data in plans.items()
        }
        for plans in _curricula_by_intake().values()
        if plans
    }

    selected = [
        str(item.get("code"))
        for item in (profile.get("selected_courses") or [])
        if item.get("code")
    ]

    year_he = str(student.get("academic_year") or "")
    catalog, catalog_summary = _catalog_snapshot()

    defaults = {
        "year_of_study": student.get("year_of_study"),
        "year_label": student.get("year_label", ""),
        "term": student.get("term", ""),
        "term_label": student.get("term_label", ""),
        "semester": str(
            student.get("semester_number") or student.get("curriculum_semester") or ""
        ),
        # שני אלה הם הזהות של מי שלומד/ת בתוכנית שנבחרת לפי מועד כניסה:
        # מועד + מספר סמסטר, בלי שנה ובלי סמסטר קלנדרי. הסמסטר הקלנדרי
        # נגזר מהם ואינו נשמר, כדי שלא יוכל לסתור אותם.
        "intake": my_intake,
        "semester_number": str(student.get("semester_number") or ""),
        "academic_year": year_he,
        "academic_year_gregorian": _gregorian_for(year_he) or str(
            student.get("academic_year_gregorian") or ""
        ),
        "codes": selected,
        "target_days": prefs.get("target_days", scheduler_mod.Preferences().target_days),
        "earliest": prefs.get("earliest"),
        "latest": prefs.get("latest"),
        "forbid_friday": bool(prefs.get("forbid_friday", False)),
        "weights": dict(prefs.get("weights") or scheduler_mod.DEFAULT_WEIGHTS),
        "top_n": DEFAULT_TOP_N,
        "allow_soft_conflicts": bool(prefs.get("allow_soft_conflicts", False)),
        "attendance": dict(prefs.get("attendance") or {}),
        "fetch_missing": True,
    }

    return _ok(
        {
            "profile": {
                "student": student,
                "preferences": prefs,
                "selected_courses": profile.get("selected_courses") or [],
                "total_credits": profile.get("total_credits"),
            },
            "defaults": defaults,
            "semesters": semesters,
            "semesters_by_program": semesters_by_program,
            "semesters_by_program_intake": semesters_by_program_intake,
            "terms": [
                {"term": key, "label": label, "in_curriculum": key in {"א", "ב"}}
                for key, label in TERM_LABELS.items()
            ],
            "years": [{"year": y, "label": label} for y, label in sorted(YEAR_LABELS.items())],
            "summer_note": (
                "בתוכנית הלימודים אין סמסטר קיץ — אפשר לבחור קורסים מהקטלוג החי, "
                "אבל אין רשימת קורסים מומלצת לסמסטר הזה."
            ),
            # שני השדות האלה נמצאים גם ברמה העליונה בכוונה: הממשק בודק אותם
            # לפני שהוא מצייר את שלב 2, ולא צריך לחפור בשביל זה.
            "curriculum_available": has_curriculum,
            "curriculum_absence": _curriculum_absence(my_program, curr, my_intake),
            # מה התוכנית הטעונה מכסה, ומה אפשר לבחור. יש לנו קובץ תוכנית
            # אחד בלבד (הנדסת תוכנה); כל השאר עובדים מול הקטלוג, שהוא ממילא
            # מלא ומכסה את כל המחלקות.
            "curriculum_program": curriculum_program(curr),
            "programs": _program_choices(curr, my_program, my_intake),
            "program": str(curr.get("program", "") or ""),
            "curriculum": {
                "available": has_curriculum,
                "program": curr.get("program", ""),
                "program_en": curr.get("program_en", ""),
                "catalog": curr.get("catalog", ""),
                "degree_credits_required": curr.get("degree_credits_required"),
                "hour_legend": curr.get("hour_legend") or {},
                "course_count": len(curriculum_mod.all_course_codes(curr)) if has_curriculum else 0,
                "semester_count": len(curr.get("semesters") or {}),
                "note": "" if has_curriculum else CURRICULUM_MISSING_NOTE,
            },
            "db": _db_snapshot(),
            "catalog": catalog_summary,
            "day_names": {str(k): v for k, v in models.DAY_NAMES_HE.items()},
            "day_letters": {str(k): v for k, v in models.DAY_LETTERS_HE.items()},
            "kind_order": list(models.KIND_ORDER),
            "limits": {
                "max_codes": MAX_CODES,
                "max_top_n": MAX_TOP_N,
                "max_ondemand_fetches": MAX_ONDEMAND_FETCHES,
                "max_ondemand_detail_fetches": MAX_ONDEMAND_DETAIL_FETCHES,
                "fetch_delay_s": FETCH_DELAY_S,
                "browse_limit_default": DEFAULT_BROWSE_LIMIT,
                "browse_limit_max": MAX_BROWSE_LIMIT,
                "details_max_age_hours": DETAILS_MAX_AGE_HOURS,
            },
            "features": {
                # קורס בלי נתונים כבר לא חייב להישאר כזה — הוא נשלף בלחיצה.
                "fetch_on_demand": _network_allowed(),
                "fetch_missing_default": True,
                # חפיפה מכוונת: תלוי במנוע השיבוץ שמותקן בפועל.
                "soft_conflicts": _engine_supports("allow_soft_conflicts"),
                "attendance": _engine_supports("attendance"),
                # ‏GROUND_TRUTH §9: הרענון הרגיל אינו דורש התחברות.
                "refresh_needs_login": False,
                "refresh_mode": "http",
                # תוכנית הלימודים היא העשרה, לא תנאי: בלעדיה עוברים לעיון
                # בקטלוג (‏/api/catalog/browse) והכול ממשיך לעבוד.
                "curriculum_optional": True,
                "catalog_browse": True,
                "course_details": _details_supported(),
            },
        }
    )


# ------------------------------------------------------- semester courses
@bp.get("/semester/<sem>/courses")
@_endpoint
def semester_courses(sem: str):
    """קורסי הסמסטר מתוך ``curriculum.json``, עם 'מוצע השנה' ו'יש נתונים'.

    ‏**חוסר בתוכנית אינו שגיאה.** סמסטר שהתוכנית לא מספקת לו קורסים —
    בין אם אין תוכנית טעונה בכלל ובין אם היא ריקה לסמסטר הזה — מחזיר ‏200
    עם רשימה ריקה, ``curriculum_available: false`` והערה בעברית. הממשק
    נשען בדיוק על הדגל הזה כדי לעבור לעיון בקטלוג (‏/api/catalog/browse),
    ולכן ‏4xx כאן היה הופך "אין לי תוכנית" ל"הכלי לא עובד".
    ‏SPEC_MULTIFACULTY §4.

    קוד סמסטר שאינו קיים בתוכנית *טעונה* נשאר ‏404 — זו טעות בבקשה, לא
    היעדר תוכנית.
    """
    # התוכנית של המסלול שנבחר, לא תוכנית ברירת המחדל: בלי זה סטודנט/ית מכל
    # מחלקה אחרת היה/תה מקבל/ת כאן קורסי הנדסת תוכנה כאילו הם המסלול שלו/ה.
    program = request.args.get("program", "")
    # מועד הכניסה נקרא רק למסלול שיש לו מועדים. בלעדיו אין תוכנית אחת
    # להחזיר, והתשובה היא "צריך לבחור מועד" ולא "אין תוכנית".
    intake = request.args.get("intake", "")
    curr = _curriculum(program, intake)
    has_curriculum = _curriculum_available(curr, program)
    info: dict[str, Any] = {}
    entries: list[dict[str, Any]] = []
    if has_curriculum:
        try:
            entries = curriculum_mod.semester_courses(curr, sem)
            info = curriculum_mod.semester_info(curr, sem)
        except curriculum_mod.UnknownSemesterError as exc:
            raise ApiError(
                404, str(exc).split("(")[0].strip(), f"unknown semester {sem!r}"
            ) from exc

    catalog, catalog_summary = _catalog_snapshot()
    offered = discovery_mod.offered_codes(catalog)
    store = _store()
    have_data = set(store.codes())

    courses: list[dict[str, Any]] = []
    credit_values: list[Any] = []
    for entry in entries:
        raw_code = entry.get("code")
        code = str(raw_code).strip() if raw_code else ""
        facts = course_facts(code, entry=entry) if code else None
        credits = facts["credits"] if facts else _known_credits(entry.get("credits"))
        credit_values.append(credits)

        item: dict[str, Any] = {
            "code": code or None,
            "name": entry.get("name", ""),
            # ‏None ולא ‏0.0 — הממשק מצייר "—" ולא מספר שאיש לא אמר.
            "credits": credits,
            "credits_source": facts["credits_source"] if facts else CREDITS_SOURCE_UNKNOWN,
            "credits_text": credits_text(credits),
            "he": entry.get("he", 0),
            "te": entry.get("te", 0),
            "ma": entry.get("ma", 0),
            "pr": entry.get("pr", 0),
            "prereq": [str(p) for p in (entry.get("prereq") or [])],
            "prereq_source": facts["prereq_source"] if facts else CREDITS_SOURCE_UNKNOWN,
            "tied_with": [],
            "note": entry.get("note", ""),
            "cond": entry.get("cond", ""),
            "group": entry.get("group", ""),
            # ‏חלופות הדדיות בתוכנית. שתי השורות האלה קיימות כדי שהממשק יידע
            # אילו קורסים *אסור* לסמן אוטומטית: קורס השמה נקבע לפי ציון
            # פסיכומטרי/יע"ל, ומסלול הפיזיקה נקבע לפי פטור. סימון כולם יחד
            # היה מרכיב מערכת שאיש לא אמור ללמוד.
            # ‏אזהרה: אין להסיק חלופיות מ-``group`` או מ-``cond``. ‏11069
            # (אנגלית טכנית) הוא ``group: "english"`` עם ``cond``, והוא קורס
            # חובה גמור — כלל שנשען עליהם היה מבטל אותו בטעות.
            "placement": bool(entry.get("placement", False)),
            "physics_track": str(entry.get("physics_track") or ""),
            # מסלול התמחות. מחלקות אחדות מפצלות חלק מהסמסטרים לפי מסלול,
            # והכלי אינו יודע באיזה מסלול הסטודנט/ית — באזרחית הוא בכלל
            # נקבע לפי ציונים. ריק = קורס ליבה משותף לכולם.
            "track": str(entry.get("track") or ""),
            "curriculum_semester": str(sem),
            "in_curriculum": True,
            "selectable": bool(code),
            "offered": False,
            "has_data": False,
        }

        if code:
            item["prereq"] = list(facts["prereq"]) if facts else item["prereq"]
            item["tied_with"] = list(facts["tied_with"]) if facts else []
            item["offered"] = code in offered
            item["has_data"] = code in have_data
            item["catalog_name"] = str((catalog.get(code) or {}).get("name", ""))
            if item["tied_with"] and not item["note"]:
                item["note"] = (
                    "קורס צמוד — חובה לקחת אותו יחד עם "
                    + ", ".join(item["tied_with"])
                    + " באותו סמסטר."
                )
            if not item["offered"]:
                item["unselectable_reason"] = ""  # מוצע/לא-מוצע אינו חוסם בחירה
        else:
            item["unselectable_reason"] = (
                "אין לקורס הזה קוד קבוע בתוכנית (קורס כללי / ספורט) — "
                "יש לבחור אותו ישירות בידיעון."
            )

        courses.append(item)

    summary = credits_summary(credit_values)
    if not has_curriculum:
        note = CURRICULUM_MISSING_NOTE
    elif not courses:
        note = CURRICULUM_EMPTY_SEMESTER_NOTE
    else:
        note = ""

    return _ok(
        {
            "semester": str(sem),
            "info": {
                "year": info.get("year"),
                "term": info.get("term", ""),
                "label": _semester_label(str(sem), info) if info else f"סמסטר {sem}",
                "total": info.get("total") or {},
                "plus": info.get("plus", ""),
                # השנה והסמסטר אינם כתובים באף פרק שנתון — הם נגזרים ממספר
                # הסמסטר, וזה מה שהדגל אומר. אין להציג נגזרת כעובדה.
                "year_term_inferred": bool(info.get("year_term_inferred")),
                # האם הנ"ז שחילצנו שווה לסה"כ שהשנתון עצמו מדפיס. ‏False
                # אינו "תקלה" אלא "אל תסמכו על הרשימה הזאת בלי לבדוק" —
                # ולפעמים המסמך עצמו הוא שאינו מסתדר.
                "reconciles": info.get("reconciles"),
                "semester_note": str(info.get("note") or ""),
                "printed_total_credits": info.get("printed_total_credits"),
            },
            # אזהרות ברמת התוכנית כולה, מקובץ התוכנית של המחלקה.
            "program_warnings": [str(w) for w in (curr.get("warnings") or [])],
            "cohort_year": str(curr.get("cohort_year") or ""),
            "courses": courses,
            "credits_total": summary["total"],
            "credits_summary": summary,
            "credits_unknown": summary["unknown"],
            "count": len(courses),
            # הדגל שהממשק נשען עליו כדי לעבור לעיון בקטלוג. ריק = אין על מה
            # להישען כאן, ולא "משהו נשבר".
            "curriculum_available": bool(courses),
            "curriculum_loaded": has_curriculum,
            "curriculum_absence": _curriculum_absence(program, curr, intake),
            "program": str(curr.get("program", "") or ""),
            "intake": str(curr.get("intake", "") or ""),
            "note": note,
            "fallback": {
                "endpoint": "/api/catalog/browse",
                "catalog_count": catalog_summary.get("count", 0),
            },
        }
    )


# --------------------------------------------------------- catalog search
def _catalog_tag(in_curriculum: bool, semester: Any, cluster: Any) -> str:
    """התווית הקצרה שמופיעה ליד תוצאת חיפוש/עיון."""
    if in_curriculum and semester:
        return f"[בתוכנית-סמסטר {semester}]"
    if in_curriculum and cluster:
        return f"[אשכול בחירה: {cluster}]"
    if in_curriculum:
        return "[בתוכנית]"
    return "[מחוץ לתוכנית]"


def _catalog_entry_json(
    code: str,
    name: str,
    *,
    info: dict[str, Any] | None = None,
    have_data: set[str] | None = None,
    offered: set[str] | None = None,
    details: Any = None,
) -> dict[str, Any]:
    """שורת קטלוג אחת, זהה בחיפוש ובעיון — כולל נ"ז כנות ומקורן."""
    info = info or {}
    facts = course_facts(code, details=details)
    in_curriculum = bool(info.get("in_curriculum", facts["in_curriculum"]))
    semester = info.get("curriculum_semester", facts["curriculum_semester"])
    cluster = info.get("cluster", facts["cluster"])
    return {
        "code": code,
        "name": name or facts["name"],
        "in_curriculum": in_curriculum,
        "curriculum_semester": semester,
        "cluster": cluster,
        # ‏None כשלא ידוע. אף פעם לא 0.0.
        "credits": facts["credits"],
        "credits_source": facts["credits_source"],
        "credits_text": facts["credits_text"],
        "tied_with": list(info.get("tied_with") or facts["tied_with"]),
        "prereq": list(info.get("prereq") or facts["prereq"]),
        "prereq_source": facts["prereq_source"],
        "language": facts["language"],
        "has_details": facts["details_available"],
        "has_data": code in (have_data or set()),
        "offered": (code in offered) if offered is not None else None,
        "tag": _catalog_tag(in_curriculum, semester, cluster),
    }


@bp.get("/catalog/search")
@_endpoint
def catalog_search():
    """חיפוש בקטלוג החי — כך מוסיפים קורס חוזר או קורס מחוץ לתוכנית."""
    query = str(request.args.get("q", "") or "").strip()
    limit = _as_int(request.args.get("limit"), field="limit", default=20, low=1, high=200)

    store = _store()
    hits = store.search_catalog(query, limit=limit)
    if not hits:
        return _ok({"query": query, "limit": limit, "results": [], "count": 0})

    curr = _curriculum()
    have_data = set(store.codes())
    raw = {code: {"name": name} for code, name in hits}
    annotated = discovery_mod.annotate_with_curriculum(raw, curr)

    results = [
        _catalog_entry_json(code, name, info=annotated.get(code) or {}, have_data=have_data)
        for code, name in hits  # סדר הדירוג של search_catalog נשמר
    ]

    return _ok({"query": query, "limit": limit, "results": results, "count": len(results)})


# --------------------------------------------------------- catalog browse
def _norm_browse(text: Any) -> str:
    """נרמול להשוואה: רווח קשיח, גרש/גרשיים עבריים ומרכאות מסולסלות.

    בלי זה חיפוש ``מתמטיקה ב'`` לא היה מוצא קורס שנכתב בידיעון עם ``ב׳`` —
    בדיוק כמו ב-``store.search_catalog``.
    """
    value = str(text or "").replace(" ", " ")
    for src, dst in (("׳", "'"), ("״", '"'), ("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"')):
        value = value.replace(src, dst)
    return re.sub(r"\s+", " ", value).strip().lower()


def _browse_sort_key(code: str) -> tuple[int, int, str]:
    """מיון לפי קוד: מספרי כשאפשר, אחרת אלפביתי — תמיד יציב."""
    text = str(code or "")
    if text.isdigit():
        return (0, int(text), text)
    return (1, 0, text)


@bp.get("/catalog/browse")
@_endpoint
def catalog_browse():
    """עיון בקטלוג המלא — הדרך של מי שהתוכנית שלהם אינה ב-rec.pdf.

    ‏SPEC_MULTIFACULTY §4: ‏86% מהקטלוג אינם ב-``curriculum.json``, ולכן שלב
    ‏2 חייב מקור שני. שלושה אופנים, כולם אופציונליים ומצטברים:

    * ``prefix`` — קידומת קוד (‏"110" → 11001, 11002 …). כך סטודנטים חושבים:
      טווח קודים הוא בפועל שם המחלקה.
    * ``q`` — תת-מחרוזת בשם (עברית) או בקוד.
    * ``limit`` + ``offset`` — דפדוף, עם תקרה קשיחה של ‏200 שורות לבקשה.

    בלי שני הראשונים מוחזר ראש הקטלוג לפי קוד — עיון הוא בדיוק המצב שבו
    עוד אין מה להקליד.
    """
    prefix = str(request.args.get("prefix", "") or "").strip()
    if prefix and not prefix.isdigit():
        raise ApiError(
            400,
            "קידומת קוד חייבת להיות ספרות בלבד (למשל 110 או 617).",
            f"bad prefix {prefix!r}",
        )
    if len(prefix) > 7:
        raise ApiError(
            400, "קידומת קוד ארוכה מדי — קוד קורס הוא עד 7 ספרות.", f"long prefix {prefix!r}"
        )

    query = str(request.args.get("q", "") or "").strip()
    limit = _as_int(
        request.args.get("limit"),
        field="limit",
        default=DEFAULT_BROWSE_LIMIT,
        low=1,
        high=MAX_BROWSE_LIMIT,
    )
    offset = _as_int(request.args.get("offset"), field="offset", default=0, low=0, high=100000)

    catalog, catalog_summary = _catalog_snapshot()
    store = _store()
    curr = _curriculum()
    needle = _norm_browse(query)
    needle_nospace = needle.replace(" ", "")

    matched: list[tuple[str, str]] = []
    for raw_code, raw_info in catalog.items():
        code = str(raw_code).strip()
        if not code:
            continue
        name = str(raw_info.get("name", "")) if isinstance(raw_info, dict) else str(raw_info or "")
        if prefix and not code.startswith(prefix):
            continue
        if needle:
            code_n = _norm_browse(code)
            if needle not in _norm_browse(name) and not code_n.startswith(needle_nospace):
                continue
        matched.append((code, name))

    matched.sort(key=lambda pair: _browse_sort_key(pair[0]))
    total = len(matched)
    page = matched[offset : offset + limit]

    have_data = set(store.codes())
    offered = discovery_mod.offered_codes(catalog)
    annotated = discovery_mod.annotate_with_curriculum(
        {code: {"name": name} for code, name in page}, curr
    )
    results = [
        _catalog_entry_json(
            code,
            name,
            info=annotated.get(code) or {},
            have_data=have_data,
            offered=offered,
        )
        for code, name in page
    ]

    if not catalog:
        note = (
            "הקטלוג אינו טעון, ולכן רשימת הקורסים המלאה אינה זמינה כרגע."
        )
    elif not results:
        note = "לא נמצאו קורסים שמתאימים לחיפוש הזה בקטלוג."
    elif not _curriculum_available(curr):
        note = CURRICULUM_MISSING_NOTE
    else:
        note = ""

    return _ok(
        {
            "prefix": prefix,
            "query": query,
            "limit": limit,
            "offset": offset,
            "results": results,
            "count": len(results),
            "total": total,
            "has_more": offset + len(results) < total,
            "next_offset": (offset + len(results)) if offset + len(results) < total else None,
            "curriculum_available": _curriculum_available(curr),
            "note": note,
            "catalog": catalog_summary,
        }
    )


# ---------------------------------------------------------------- courses
def _ondemand_fetch(
    codes: list[str],
    problems: list[dict[str, Any]],
    metas: dict[str, store_mod.CourseMeta],
    *,
    semester: str,
    year: str,
    year_gregorian: str,
    enabled: bool,
    max_age_hours: float,
) -> dict[str, Any]:
    """מביא עכשיו את מה שחסר או מיושן — או מסביר בעברית למה לא.

    זו התשובה לשאלה "למה יש קורסים שכתוב עליהם שאין נתונים במסד?": מאז
    ‏GROUND_TRUTH §9 השליפה אינה דורשת התחברות, ולכן "אין נתונים" הפסיק להיות
    גזר דין. כל מה שכאן הוא **שמירות**: מכסה, השהיה, כותב יחיד, ובלי רשת
    כשאסור. כישלון של קורס אחד אף פעם לא מפיל את הבקשה.

    בנוסף למערכת עצמה נשלפים כאן גם **פרטי הקורס** (נ"ז, שעות, תנאי קדם)
    כשהם חסרים או ישנים משבעה ימים — ורק לקורסים שנבחרו בפועל, אף פעם לא
    לכל הקטלוג. בדרך המקובלת (פרטים טריים) לא נשלחת אף בקשה נוספת, ולכן
    המסלול המהיר נשאר מהיר. ‏SPEC_MULTIFACULTY §3+§5.
    """
    report: dict[str, Any] = {
        "enabled": bool(enabled),
        "requested": [],
        "fetched": [],
        "failed": [],
        "skipped": [],
        "changes": {},
        "not_offered": [],
        "log": [],
        "error": "",
        "cap": MAX_ONDEMAND_FETCHES,
        "delay_s": FETCH_DELAY_S,
        "details": {
            "enabled": bool(enabled),
            "supported": _details_fetch_supported(),
            "requested": [],
            "fetched": [],
            "failed": [],
            "skipped": [],
            "log": [],
            "error": "",
            "cap": MAX_ONDEMAND_DETAIL_FETCHES,
            "delay_s": FETCH_DELAY_S,
            "max_age_hours": DETAILS_MAX_AGE_HOURS,
        },
    }
    wanted = _stale_or_missing(
        codes, problems, metas, year=year, max_age_hours=max_age_hours
    )
    # פרטים נשלפים רק לקורסים שנבחרו, ורק כשהם באמת ישנים (7 ימים) — וגם
    # רק אם יש בכלל מי שיודע לשלוף אותם, אחרת פותחים סשן לחינם בכל בקשה.
    details_wanted = (
        _details_needing_fetch(codes) if report["details"]["supported"] else []
    )
    report["requested"] = wanted
    report["details"]["requested"] = details_wanted
    if not wanted and not details_wanted:
        return report

    def skip_all(reason: str) -> dict[str, Any]:
        report["skipped"] = [{"code": code, "reason": reason} for code in wanted]
        report["details"]["skipped"] = [
            {"code": code, "reason": reason} for code in details_wanted
        ]
        return report

    if not enabled:
        return skip_all(
            "שליפה מהידיעון לא התבקשה בבקשה הזו (fetch_missing=false). "
            "הנתונים שמוצגים הם מה ששמור במסד."
        )
    if not _network_allowed():
        return skip_all(
            "הנתונים מוגשים מהקטלוג כפי שנבנה, בלי פנייה לידיעון."
        )
    # כותב יחיד ל-data/db — ראו ‏_db_write_lock.
    if not _db_write_lock.acquire(blocking=False):
        return skip_all(
            "פעולה אחרת כותבת כרגע לנתונים. אפשר לנסות שוב בעוד רגע."
        )
    try:
        result: dict[str, Any] = {}
        if wanted:
            result = fetch_courses_into_store(
                wanted,
                semester=semester,
                year_he=year,
                year_gregorian=year_gregorian,
                cap=MAX_ONDEMAND_FETCHES,
                delay_s=FETCH_DELAY_S,
            )
        details_result: dict[str, Any] = {}
        if details_wanted:
            details_result = fetch_details_into_store(
                details_wanted,
                year_he=year,
                year_gregorian=year_gregorian,
                cap=MAX_ONDEMAND_DETAIL_FETCHES,
                delay_s=FETCH_DELAY_S,
            )
    finally:
        _db_write_lock.release()

    for key in ("fetched", "failed", "skipped", "changes", "not_offered", "log", "error"):
        report[key] = result.get(key, report[key])
    for key in ("supported", "fetched", "failed", "skipped", "log", "error"):
        if key in details_result:
            report["details"][key] = details_result[key]
    if details_result.get("fetched"):
        # הפרטים שנשמרו זה עתה חייבים להיקרא מחדש באותה בקשה, אחרת התשובה
        # תציג "—" עבור נ"ז שכבר יושבות במסד.
        _request_cache().pop("details_bulk", None)
        _request_cache().pop("details_one", None)
    return report


@bp.post("/courses")
@_endpoint
def courses():
    """נתוני הקבוצות המלאים לקורסים שנבחרו, כולל טריות וקורסים שאינם נפתחים.

    ``fetch_missing`` (ברירת מחדל ``true``): קוד שאין לו נתונים שמורים, או
    שהנתונים שלו מיושנים, נשלף מהידיעון עכשיו — בלי התחברות — נשמר, ומוחזר
    באותה תשובה. לכל קורס מוחזר ``source``: ``"db"`` / ``"fetched"`` /
    ``"unavailable"``, ולכישלון תמיד יש סיבה בעברית.
    """
    body = _read_body(required=True)
    codes = _clean_codes(body.get("codes"), field="codes")
    _assert_known_codes(codes)
    profile_student = _profile().get("student") or {}
    semester = str(body.get("semester") or profile_student.get("term") or "")
    year, year_gregorian = _year_pair(
        body.get("year"), profile_student.get("academic_year")
    )
    if body.get("year_gregorian"):
        year_gregorian = str(body["year_gregorian"]).strip()
    fetch_missing = _as_bool(body.get("fetch_missing"), True)
    max_age = float(_config()["max_age_hours"])

    built, problems, metas = _build_courses(codes, semester=semester, year=year)

    fetch_report = _ondemand_fetch(
        codes,
        problems,
        metas,
        semester=semester,
        year=year,
        year_gregorian=year_gregorian,
        enabled=fetch_missing,
        max_age_hours=max_age,
    )
    if fetch_report["fetched"]:
        # נטענים מחדש מהמסד כדי שכל הקורסים ייבנו בדיוק באותו מסלול אחד.
        built, problems, metas = _build_courses(codes, semester=semester, year=year)

    fetched_ok = set(fetch_report["fetched"])
    # שתי מפות ולא אחת. ``failed`` הוא כישלון של הקוד הזה ("הידיעון לא מציג
    # קבוצות"), ולכן הוא **מסביר** את הבעיה ועדיף על הנוסח הכללי של
    # ``_build_courses``. ``skipped`` אינו הסבר בכלל: כשאין רשת
    # (``allow_network=False`` — המצב המאורח) ``skip_all`` תולה את אותו
    # משפט אחד על כל קוד שהתבקש, וכשהוא נכתב לתוך ``reason`` הוא **מחק** את
    # הסיבה האמיתית. כך קורס שפשוט לא נפתח בסמסטר הזה הוצג כאילו הבעיה היא
    # שלא פנינו לידיעון — ועם כפתור "ניסיון חוזר" שאין מאחוריו רשת.
    failed_reasons: dict[str, str] = {}
    for item in fetch_report["failed"]:
        failed_reasons.setdefault(str(item.get("code")), str(item.get("reason") or ""))
    skipped_reasons: dict[str, str] = {}
    for item in fetch_report["skipped"]:
        skipped_reasons.setdefault(str(item.get("code")), str(item.get("reason") or ""))

    sources: dict[str, str] = {}
    for problem in problems:
        code = str(problem.get("code"))
        problem["source"] = "fetched" if code in fetched_ok else "unavailable"
        sources[code] = problem["source"]
        # ``fetch_reason`` נשאר לשקיפות בשני המקרים; ``reason`` מוחלף רק
        # כשבאמת ניסינו והקורס נכשל.
        failure = failed_reasons.get(code)
        context = failure or skipped_reasons.get(code)
        if context:
            problem["fetch_reason"] = context
        if failure:
            problem["reason"] = failure

    payload: list[dict[str, Any]] = []
    credit_values: list[Any] = []
    # קריאה אחת לכל הרשימה, לא אחת לכל קורס — אחרי השליפה, כדי שמה שנשלף
    # עכשיו כבר ייחשב טרי.
    stale_details = set(_details_needing_fetch(codes))
    for course in built:
        meta = metas.get(course.code)
        # שלושה מקורות: נשלף עכשיו / נשלף כאן בעבר / הגיע עם הקוד.
        # אחרי ``meta``, לא לפניו — אחרת נקרא כאן ה-meta של הקורס הקודם.
        sources[course.code] = (
            "fetched" if course.code in fetched_ok else _origin_of(meta)
        )
        warnings: list[str] = []
        if not _year_matches(year, meta):
            warnings.append(
                strings_mod.fmt(
                    "server.course.yearMismatch",
                    stored=meta.year or "?",
                    wanted=year,
                )
            )
        meta_json = _meta_to_json(meta, max_age)
        if meta_json["stale"]:
            warnings.append(
                strings_mod.fmt(
                    "server.course.staleWarning", age=meta_json["age_text"]
                )
            )
        facts = course_facts(
            course.code, course=course, stale=course.code in stale_details
        )
        credit_values.append(facts["credits"])
        if facts["credits"] is None:
            warnings.append(
                "נקודות הזכות של הקורס אינן ידועות — הוא אינו בתוכנית הלימודים "
                "ופרטיו טרם נשלפו מהידיעון."
            )
        payload.append(
            course_to_json(
                course,
                {
                    "offered": True,
                    # שלושה מקורות, לא שניים: "fetched" — נשלף עכשיו;
                    # "db" — המשתמש/ת שלפו קודם; "shipped" — הגיע עם הקוד.
                    # ההבחנה אינה קוסמטית: רק ל-"db" ול-"fetched" יש
                    # חותמת שליפה אמיתית, ועליה נשען כל נוסח הטריות.
                    "source": sources.get(course.code, _origin_of(meta)),
                    "freshness": meta_json,
                    "warnings": warnings,
                    # נ"ז ותנאי קדם לפי סדר ההכרעה היחיד — עם המקור, כדי
                    # שהממשק יוכל לומר את האמת ולא לנחש.
                    "credits": facts["credits"],
                    "credits_source": facts["credits_source"],
                    "credits_text": facts["credits_text"],
                    "prereq": facts["prereq"],
                    "prereq_source": facts["prereq_source"],
                    "prereq_detail": facts["prereq_detail"],
                    "in_curriculum": facts["in_curriculum"],
                    "cluster": facts["cluster"],
                    "hours": facts["hours"],
                    "weekly_hours": facts["weekly_hours"],
                    "language": facts["language"],
                    "has_details": facts["details_available"],
                    "details_stale": facts["details_stale"],
                    "curriculum_semester": (
                        curriculum_mod.find_course_source(_curriculum(), course.code) or ""
                    ).replace("semester:", ""),
                },
            )
        )

    # קורסים שלא נבנו (אין נתונים שמורים, אין קבוצות, סמסטר אחר) חייבים
    # להיספר גם הם: 251100 ו-41942 שוות ‏3 נ"ז כל אחת בתוכנית, ובלי השורה
    # הזו בחירה בשתיהן הייתה מחזירה ‏"0" עם ``complete: true`` — בדיוק הסך
    # השקט ש-SPEC_MULTIFACULTY §3 אוסר, רק הפוך: אפס במקום מקף.
    for problem in problems:
        credit_values.append(course_facts(str(problem.get("code") or ""))["credits"])

    summary = credits_summary(credit_values)
    return _ok(
        {
            "semester": semester,
            "year": year,
            "codes": codes,
            "courses": payload,
            "not_offered": problems,
            # סכום של הידוע בלבד; ``credits_summary`` אומר כמה לא ידוע.
            "credits_total": summary["total"],
            "credits_summary": summary,
            "credits_unknown": summary["unknown"],
            "credits_complete": summary["complete"],
            "credits_text": summary["text"],
            "curriculum_available": _curriculum_available(),
            "count": len(payload),
            "sources": sources,
            "fetch": fetch_report,
            "fetch_missing": fetch_missing,
            # ברירות הנוכחות, כדי שהממשק יוכל להציג "כך כתוב בידיעון".
            "attendance": attendance_info(built),
        }
    )


# ------------------------------------------------ electives (clusters/tracks)
@bp.get("/program/electives")
@_endpoint
def program_electives():
    """קבוצות קורסי הבחירה של תוכנית לימודים, מפרק השנתון שלה.

    שלושה מבנים אפשריים, והם **אינם** שקולים:
      ``clusters`` — אשכולות: קורס אחד **מכל** אשכול (תוכנה, תעשייה, מערכות מידע)
      ``tracks``   — מסלולי התמחות: בוחרים מסלול **אחד** (אזרחית, מכונות)
      ``flat``     — אין קיבוץ בפרק (חשמל, מתמטיקה) -> אין מה להציג

    ``year`` הוא שנת המחזור **רק** כשהפרק מצהיר עליה. ``None`` = המסמך לא
    ציין שנה, והממשק חייב לכתוב "שנה לא צוינה" ולא להמציא.
    ``available: false`` = אין פרק לתוכנית הזאת, או שאין בו קיבוץ — ואז
    הממשק **מסתיר** את החלק הזה לגמרי במקום להראות רשימה ריקה או מנוחשת.
    """
    program = str(request.args.get("program", "")).strip()
    if not program:
        raise ApiError(400, "חסר שם תוכנית.", "program is required")

    try:
        from shnaton import load_curricula

        all_programs = load_curricula(str(PROJECT_ROOT / "data" / "curricula.json"))
    except Exception:  # noqa: BLE001 - היעדר הקובץ אינו תקלה
        all_programs = {}

    def norm(text: Any) -> str:
        return re.sub(r"[\s\"'׳״-]", "", str(text or ""))

    chapter = all_programs.get(program)
    if chapter is None:
        for name, entry in all_programs.items():
            if norm(name) == norm(program):
                chapter = entry
                break

    if not chapter:
        return {
            "ok": True,
            "program": program,
            "available": False,
            "reason": "אין פרק שנתון לתוכנית הזאת.",
        }

    clusters = chapter.get("clusters") or {}
    tracks = chapter.get("tracks") or {}
    if not clusters and not tracks:
        return {
            "ok": True,
            "program": chapter.get("program", program),
            "available": False,
            "structure": chapter.get("structure", "flat"),
            "reason": "פרק השנתון של התוכנית אינו מקבץ את קורסי הבחירה.",
        }

    year = chapter.get("year")
    return {
        "ok": True,
        "program": chapter.get("program", program),
        "available": True,
        "structure": chapter.get("structure"),
        "year": year,
        "year_text": year or "שנה לא צוינה במסמך",
        "source": chapter.get("source", ""),
        "clusters": clusters,
        "tracks": tracks,
        "cluster_rule": "יש לקחת קורס אחד לפחות מכל אשכול." if clusters else "",
        "track_rule": "יש לבחור מסלול התמחות אחד ולהתמחות בו." if tracks else "",
        "warnings": chapter.get("warnings", []),
    }


# ------------------------------------------------------------------ solve
@bp.post("/solve")
@_endpoint
def solve():
    """הלב: פותר, סופר, ומחשב viability לכל קבוצה של כל קורס נבחר.

    ‏``attendance`` (‏{קוד: {סוג רכיב: האם נדרשת נוכחות}}) ו-
    ``allow_soft_conflicts`` מאפשרים חפיפה מכוונת: בבראודה הרצאה רבות אינן
    מחייבות נוכחות, ובמיוחד בקורס חוזר — ואז שווה לפעמים להירשם לשתי קבוצות
    שמתנגשות, ללכת לאחת, ולסיים את השבוע מוקדם יותר. חסר = "נוכחות חובה",
    כלומר בלי לשלוח כלום ההתנהגות זהה לחלוטין לקודמת.

    ‏**חישוב ה-viability משתמש באותן העדפות בדיוק**, ולכן קבוצה שאפשרית רק
    בזכות חפיפה מכוונת מסומנת כאפשרית כשהחפיפות מאושרות — ורק אז.
    """
    body = _read_body(required=True)
    codes = _clean_codes(body.get("codes"), field="codes")
    # קוד שאינו קיים בשום מקום נפסל כאן, לפני הכול: מערכת שנבנתה בלי קורס
    # שביקשו — בלי לומר מילה — היא בדיוק סוג השקט שהאפליקציה נועדה למנוע.
    _assert_known_codes(codes)
    profile_student = _profile().get("student") or {}
    semester = str(body.get("semester") or profile_student.get("term") or "")
    year = str(body.get("year") or profile_student.get("academic_year") or "")

    target_days = _as_int(body.get("target_days"), field="target_days", default=4, low=1, high=6)
    top_n = _as_int(body.get("top_n"), field="top_n", default=DEFAULT_TOP_N, low=1, high=MAX_TOP_N)
    earliest = _as_minutes(body.get("earliest"), field="earliest", default=0)
    latest = _as_minutes(body.get("latest"), field="latest", default=MINUTES_IN_DAY)
    if earliest >= latest:
        raise ApiError(
            400,
            "השעה המאוחרת ביותר חייבת להיות אחרי השעה המוקדמת ביותר.",
            f"earliest={earliest} >= latest={latest}",
        )

    pinned_request = _clean_pinned(body.get("pinned"))
    attendance_request = _clean_attendance(body.get("attendance"))
    # ברירת מחדל True: הסימון של חובת הנוכחות הוא הפקד היחיד שקובע.
    allow_soft_conflicts = _as_bool(body.get("allow_soft_conflicts"), True)
    prefs, unsupported_prefs = _make_preferences(
        target_days=target_days,
        preferred_lecturers=_clean_ranked(body.get("ranked")),
        blocked_windows=_clean_blocked(body.get("blocked")),
        earliest=earliest,
        latest=latest,
        weights=_clean_weights(body.get("weights")),
        forbid_friday=_as_bool(body.get("forbid_friday"), False),
        attendance=attendance_request,
        allow_soft_conflicts=allow_soft_conflicts,
    )
    attendance_supported = not unsupported_prefs
    attendance_note = ""
    if unsupported_prefs:
        # לא משתיקים: אם המנוע עוד לא מכיר את החפיפות המכוונות, עדיף לומר את
        # זה מפורשות מאשר להחזיר מערכת שנראית כאילו ההגדרה נלקחה בחשבון.
        LOG.warning("scheduler.Preferences אינו תומך ב: %s", ", ".join(unsupported_prefs))
        attendance_note = (
            "מנוע השיבוץ בגרסה הזו עדיין אינו תומך בחפיפות מכוונות, ולכן כל "
            "התנגשות בזמן נחשבה חוסמת."
        )
        allow_soft_conflicts = False

    # ── 1. הקורסים: deepcopy, tied_with, נ"ז ──
    built, problems, _metas = _build_courses(codes, semester=semester, year=year)
    # רק נ"ז ידועות נסכמות, וכמה לא ידועות נאמר במפורש (SPEC_MULTIFACULTY §3).
    # נספרים **כל** הקודים שנבחרו, גם אלה שאין להם נתונים שמורים: אחרת בחירה
    # שכולה קורסים בלי מערכת שמורה חוזרת כ-"0" עם ``complete: true``, כלומר
    # אפס שמתחזה לתשובה שלמה. הסכום אינו תלוי בנעיצות, ולכן הוא נחשב כאן —
    # לפני היציאה המוקדמת, שאחרת הייתה מחזירה אפס קשיח.
    solve_credits = credits_summary(
        [course_facts(c.code, course=c)["credits"] for c in built]
        + [course_facts(str(p.get("code") or ""))["credits"] for p in problems]
    )
    base_common: dict[str, Any] = {
        "codes": codes,
        "semester": semester,
        "year": year,
        "target_days": target_days,
        "not_offered": problems,
        "schedules": [],
        "viability": {},
        "feasible_count": 0,
        "min_days": None,
        "target_reachable": False,
        "reasons": [],
        "suggestions": [],
        "credits_total": solve_credits["total"],
        "credits_summary": solve_credits,
        "credits_unknown": solve_credits["unknown"],
        "credits_complete": solve_credits["complete"],
        "credits_text": solve_credits["text"],
        "curriculum_available": _curriculum_available(),
        "elapsed_ms": 0,
        "allow_soft_conflicts": bool(allow_soft_conflicts),
        "attendance_supported": bool(attendance_supported),
        "attendance_note": attendance_note,
        # לכל (קורס, סוג רכיב): ברירת המחדל, האם היא מגיעה מהערת הידיעון,
        # ומה נבחר בפועל.
        "attendance": attendance_info(built, attendance_request),
    }

    if not built:
        base_common["reasons"] = [
            p["reason"] for p in problems
        ] or ["לא נבחר אף קורס עם נתונים שמורים."]
        base_common["suggestions"] = [
            "לקורסים שנבחרו אין נתוני קבוצות בקטלוג הנוכחי."
        ]
        base_common["target_message"] = ""
        return _ok(base_common)

    started = time.perf_counter()

    # ── 2. נעיצות: **מסננת על הבחירות**, לא מחיקת קבוצות. המנוע לא משתנה
    #      ומקבל את הקורסים שלמים — אחרת linked_to היה מפסיק להיאכף. ──
    applied_pins, dropped_pins = resolve_pins(built, pinned_request)
    base_common["pinned"] = applied_pins
    base_common["dropped_pins"] = dropped_pins

    # ── 3. חבילת קורסים צמודים — נבדק *לפני* הספירה, אחרת התשובה סותרת את
    #      עצמה ("יש 12 צירופים" לצד "אין אף מערכת"). זו תשובה, לא תקלה.
    try:
        scheduler_mod._validate_tied(built)  # noqa: SLF001
    except AttributeError:  # pragma: no cover - העוזר הפרטי נעלם; ייתפס ב-solve
        pass
    except scheduler_mod.TiedCoursesError as exc:
        base_common.update(
            {
                "reasons": [str(exc)],
                "suggestions": [
                    "יש לסמן את כל הקורסים בחבילה הצמודה, או להוריד את כולם יחד: "
                    + ", ".join([exc.course_code, *exc.partners]),
                ],
                "tied_block": [exc.course_code, *exc.partners],
                "tied_missing": list(exc.missing),
                "target_message": "",
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return _ok(base_common)

    # ── 3.5 נעיצה שאי אפשר לכבד: קבוצה שכבר אינה קיימת בנתונים ──
    #      זו לא שגיאת HTTP. הממשק שומר את הנעיצות ב-localStorage ומשחזר
    #      אותן בכל טעינה, ולכן 400 היה נועל את שלב 5 לתמיד ו"לרענן את
    #      הדף" לא היה עוזר. במקום זה: 200 שאומר **במפורש** איזו נעיצה
    #      שוחררה (``dropped_pins``), כדי שהממשק ימחק אותה מהאחסון —
    #      ובלי להעמיד פנים שנבנתה מערכת שמכבדת אותה.
    if dropped_pins:
        viability, via_truncated, via_skipped = compute_viability(
            [c.code for c in built], applied_pins, prefs, semester=semester, year=year
        )
        base_common.update(
            {
                "viability": viability,
                "viability_truncated": via_truncated,
                "viability_skipped": via_skipped,
                "feasible_count": 0,
                "min_days": None,
                "target_reachable": False,
                "target_message": "",
                "schedules": [],
                "reasons": [d["reason"] for d in dropped_pins],
                "suggestions": [
                    strings_mod.get("server.infeasible.pinSuggestion", "")
                ],
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return _ok(base_common)

    # ── 4. מעבר אחד למניית הצירופים ומינימום הימים ──
    feasible_count, min_days, counts_truncated = _count_and_min_days(
        built, prefs, applied_pins
    )
    target_reachable = bool(min_days is not None and min_days <= target_days)

    base_common.update(
        {
            "feasible_count": feasible_count,
            "min_days": min_days,
            "target_reachable": target_reachable,
            "counts_truncated": counts_truncated,
        }
    )
    if min_days is None:
        base_common["target_message"] = ""
    elif target_reachable:
        base_common["target_message"] = f"אפשר לסגור את השבוע ב-{min_days} ימים."
    else:
        base_common["target_message"] = (
            f"{target_days} ימים אינם אפשריים עם הקורסים האלה — המינימום הוא {min_days}"
        )
        # לא רק לקרוא לקיר בשמו. איזה ויתור על קורס יפתח את היעד —
        # נמדד, עם המחיר בנקודות זכות, ומסודר מהזול לנזק.
        base_common["day_relaxations"] = _day_relaxations_json(
            built, prefs, target_days
        )

    # ── 5. viability — לכל קבוצה, האם היא משאירה פתרון ──
    #      **אותן ``prefs`` בדיוק** שהפתרון עצמו רץ איתן. אחרת קבוצה שאפשרית
    #      רק בזכות חפיפה מכוונת הייתה מסומנת כמבוי סתום ולהפך — כלומר
    #      הממשק היה חוסם בדיוק את האפשרות שהתכונה הזו נועדה לפתוח.
    viability, via_truncated, via_skipped = compute_viability(
        [c.code for c in built], applied_pins, prefs, semester=semester, year=year
    )
    base_common["viability"] = viability
    base_common["viability_truncated"] = via_truncated
    base_common["viability_skipped"] = via_skipped

    # ── 6. המערכות עצמן ──
    if feasible_count == 0:
        # אין פתרון — זו תשובה, לא שגיאה. 200 עם הסבר ועם צעדים מעשיים.
        # לאבחון בלבד — שם מותר לצמצם את המרחב לפי הנעיצות (ראי _pin_filtered).
        diag = _pin_filtered(built, applied_pins)
        try:
            reasons = scheduler_mod.diagnose_infeasibility(diag, prefs)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("diagnose_infeasibility נכשל")
            reasons = [f"לא ניתן לאבחן את הסיבה ({type(exc).__name__})."]
        try:
            suggestions = scheduler_mod.relax_suggestions(diag, prefs)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("relax_suggestions נכשל")
            suggestions = []
        if applied_pins:
            suggestions.insert(
                0, strings_mod.get("server.infeasible.releasePin", "")
            )
        base_common["reasons"] = reasons
        base_common["suggestions"] = suggestions
        # ויתורים **נמדדים**: לכל אילוץ שהוגדר בפועל, כמה מערכות ייפתחו אם
        # נרפה אותו, ומה זה גובה. הפותר רץ במילישניות, ולכן אין שום סיבה
        # להציע ויתור בלי לבדוק אם הוא בכלל עוזר.
        base_common["relaxations"] = _relaxations_json(diag, prefs)
        base_common["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return _ok(base_common)

    try:
        found = _top_schedules(built, prefs, top_n, applied_pins)
    except scheduler_mod.TiedCoursesError as exc:  # pragma: no cover - נתפס כבר בשלב 3
        base_common.update(
            {
                "reasons": [str(exc)],
                "suggestions": [
                    "יש לסמן את כל הקורסים בחבילה הצמודה, או להוריד את כולם יחד."
                ],
                "tied_block": [exc.course_code, *exc.partners],
                "tied_missing": list(exc.missing),
                "feasible_count": 0,
                "min_days": None,
                "target_reachable": False,
                "target_message": "",
                "schedules": [],
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        return _ok(base_common)
    except scheduler_mod.Infeasible as exc:  # pragma: no cover - נתפס כבר בשלב 3
        base_common["reasons"] = list(exc.reasons)
        base_common["suggestions"] = scheduler_mod.relax_suggestions(
            _pin_filtered(built, applied_pins), prefs
        )
        base_common["feasible_count"] = 0
        base_common["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return _ok(base_common)

    base_common["schedules"] = [schedule_to_json(s, built, prefs) for s in found]
    base_common["top_n"] = top_n
    if not target_reachable:
        base_common["suggestions"] = [
            f"אפשר להעלות את יעד הימים ל-{min_days} — זו העדפה רכה בלבד, "
            f"והיא רק משפיעה על הניקוד."
        ]
    base_common["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    return _ok(base_common)


# ------------------------------------------------------------ catalog meta
@bp.get("/catalog/meta")
@_endpoint
def catalog_meta():
    """מתי נבנה הקטלוג וכמה קורסים יש בו — במקום יומן הגרידה החי.

    ‏זו נקודת הקצה שהחליפה את ``/api/scrape/status``, וההבדל אינו טכני בלבד:
    ‏סטודנט/ית מאורח/ת אינם מריצים גרידה משלהם ואין להם יומן לצפות בו. השאלה
    ‏שהממשק צריך לענות עליה היא **"מתי נבנה הקטלוג"**, לא "איך הולך הרענון
    ‏שלך". ‏HOSTING_NOTES.md §4 כלל 2.

    ``built_at`` הוא ‏ISO-8601 ב-UTC, או ``""`` כשאין קטלוג כלל.
    ``source``: ``"shipped"`` = תאריך הבנייה של הקטלוג שנשלח עם הקוד;
    ``"db"`` = חותמת השליפה של קטלוג מקומי; ``""`` = אין קטלוג.
    """
    meta = _shipped_meta()
    _catalog, summary = _catalog_snapshot()

    built_at = str(meta.get("built_at") or "") or str(summary.get("fetched_at") or "")
    age = store_mod.age_hours_since(built_at) if built_at else None
    counts = meta.get("counts") if isinstance(meta.get("counts"), dict) else {}
    course_count = int(counts.get("courses") or 0) or int(summary.get("count") or 0)

    payload: dict[str, Any] = {
        "built_at": built_at,
        "age_hours": age,
        "age_text": store_mod.format_hebrew_age(age),
        "course_count": course_count,
        "year": meta.get("year") or summary.get("year", ""),
        "year_gregorian": meta.get("year_gregorian") or summary.get("year_gregorian", ""),
        "source": "shipped" if meta.get("built_at") else ("db" if built_at else ""),
        "empty": course_count == 0,
    }

    # ‏סיכום שערי האיכות של הבנייה שייצרה את הקטלוג. ‏הצינור הלילי כותב
    # אותו (‏build_catalog.build_meta), ו-scripts/verify_catalog.py מצליב
    # אותו. נחשף כאן כדי שאפשר יהיה לשאול מכונה שרצה **האם הקטלוג שהיא
    # מגישה עבר את השערים** — בלי גישה ליומן של ריצת ה-cron שנמחק.
    # ‏נשלחים רק הדגלים והמונים, לא רשימת השערים המלאה: היא ארוכה, היא
    # בעברית, והממשק אינו מציג אותה.
    validation = meta.get("validation")
    if isinstance(validation, dict):
        payload["validation"] = {
            "passed": validation.get("passed") is True,
            "gate_count": int(validation.get("gate_count") or 0),
            "failure_count": len(validation.get("failures") or []),
        }

    return _ok(payload)


# ===========================================================================
# 10. המפעל (application factory)
# ===========================================================================
def create_app(
    config: dict[str, Any] | None = None,
    *,
    db_root: str | Path | None = None,
    serve_ui: bool = True,
) -> Flask:
    """בונה את אפליקציית Flask.

    Args:
        config: דריסות לנתיבים ולהגדרות. מפתחות מוכרים: ``db_root``,
            ``curriculum_path``, ``profile_path``, ``raw_dir``,
            ``browser_profile_dir``, ``max_age_hours``, ``allow_network``
            (‏``None`` = אוטומטי: אין רשת בתוך בדיקות), ``course_fetcher``
            (הזרקה לבדיקות — כדי שלא תיפתח פנייה אמיתית לידיעון).
        db_root: קיצור דרך ל-``config["db_root"]``, כדי שאפשר יהיה להריץ
            את האפליקציה מול עותק זמני של המסד בלי לגעת באמיתי.
        serve_ui: האם להגיש גם את ``templates/index.html`` ואת ``static/``.
            ``False`` = ‏API בלבד.

    Returns:
        ``Flask`` מוכן. ההרצה עצמה (וה-host 127.0.0.1) היא באחריות ``webapp.py``.
    """
    data = PROJECT_ROOT / "data"
    settings: dict[str, Any] = {
        "db_root": env_path("SLOTWISE_DB_ROOT", data / "db"),
        "curriculum_path": env_path("SLOTWISE_CURRICULUM_PATH", data / "curriculum.json"),
        # תוכנית לימודים אחת לכל מחלקה. ‏curriculum_path נשאר תוכנית
        # ברירת המחדל (הנדסת תוכנה) כדי לא לשנות התנהגות קיימת.
        "curricula_dir": env_path("SLOTWISE_CURRICULA_DIR", data / "curricula"),
        # ‏לא מהסביבה: ‏DEPLOY.md אינו מתעד משתנה כזה, והתמונה המתארחת
        # אינה נושאת פרופיל אישי בכלל.
        "profile_path": str(data / "profile.json"),
        "raw_dir": env_path("SLOTWISE_RAW_DIR", data / "raw"),
        "browser_profile_dir": str(data / ".browser_profile"),
        "max_age_hours": env_float(
            "SLOTWISE_MAX_AGE_HOURS", store_mod.DEFAULT_MAX_AGE_HOURS
        ),
        # פרטי קורס (נ"ז, שעות, תנאי קדם) מקבלים חלון טריות משלהם — שבעה
        # ימים, לא יממה. הם כמעט אינם משתנים, והכפלת הבקשות בשבילם היא
        # חוסר נימוס כלפי שרת המכללה. ‏SPEC_MULTIFACULTY §2.
        "details_max_age_hours": env_float(
            "SLOTWISE_DETAILS_MAX_AGE_HOURS", DETAILS_MAX_AGE_HOURS
        ),
        # ‏None = אוטומטי: פנייה לידיעון מותרת, אבל לא בתוך הרצת בדיקות.
        "allow_network": None,
    }
    overrides = dict(config or {})
    course_fetcher = overrides.pop("course_fetcher", None)
    settings.update({k: v for k, v in overrides.items() if k in settings})
    if db_root is not None:
        settings["db_root"] = str(db_root)

    # התבניות והנכסים יושבים ליד המודול הזה (src/web/), לא בשורש הפרויקט.
    # כשהנתיב הצביע על שורש הפרויקט, Flask לא מצא את index.html והגיש דף חלופי
    # זעיר במקום הממשק האמיתי — השרת "עבד" אבל הראה עמוד ריק.
    # The UI lives next to this module, not at the project root.
    web_dir = Path(__file__).resolve().parent
    templates_dir = web_dir / "templates"
    static_dir = web_dir / "static"

    app = Flask(
        __name__,
        template_folder=str(templates_dir),
        static_folder=str(static_dir),
        static_url_path="/static",
    )
    # ‏StrictUndefined: ‏{{ S.ui.missing }} יזרוק במקום לרנדר מחרוזת ריקה.
    # בלי זה מפתח שגוי בתבנית יוצא ככפתור ריק — שנראה כמו עיצוב, לא כמו
    # באג, וזה בדיוק המצב שאפשר לשלוח בלי לשים לב.
    from jinja2 import StrictUndefined

    app.jinja_env.undefined = StrictUndefined

    # ‏‎{{ asset_v('app.js') }}‎ בתבנית. ראו ‏_asset_version: בלי זה דף
    # חדש יכול להיות מצומד ל-JavaScript ישן מהמטמון למשך יממה.
    app.jinja_env.globals["asset_v"] = _asset_version

    # ‏התבנית נקראת מחדש כשהקובץ משתנה, גם בלי ‎--debug‎.
    #
    # ‏auto_reload של Jinja נגזר כברירת מחדל מ-‎app.debug‎, כלומר שרת רגיל
    # מהדר את ‎index.html‎ פעם אחת וחי איתה עד שהוא נסגר. זה נראה בדיוק כמו
    # שינוי שלא בוצע: ‎style.css‎ הוא קובץ סטטי ונקרא מהדיסק בכל בקשה, ולכן
    # שינויי CSS כן מגיעים למסך — בעוד שינויי תבנית לא. ‏Ctrl+F5 אינו עוזר,
    # כי הדפדפן אמנם מבקש את הדף מחדש והשרת מחזיר את אותו עותק מזיכרון.
    #
    # ‏ב-2026-09-08 שרת שהופעל ב-2026-09-05 הגיש כותרת ישנה שלושה ימים,
    # כולל כפתור שנמחק מהמאגר לפני כן. אותו סוג תקלה בדיוק כמו ‎_CACHE‎ של
    # ‎strings.py‎ — ראו DEFERRED.md — ושם הוא כבר נסגר בבדיקת mtime. כאן
    # ‏Jinja עושה את אותה בדיקה בעצמו ברגע שהדגל דלוק.
    #
    # ‏המחיר הוא ‎stat()‎ אחד לכל רינדור של תבנית. זו אפליקציה מקומית לחמישה
    # משתמשים לכל היותר, והמחיר הזה זניח מול יום עבודה שהולך על "שיניתי
    # ולא קרה כלום".
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True

    app.config["SLOTWISE"] = settings
    app.config["COURSE_FETCHER"] = course_fetcher
    app.config["JSON_SORT_KEYS"] = False

    # עברית קריאה ב-JSON (ולא עב...). לא חובה, אבל עוזר בדיבוג.
    try:
        app.json.ensure_ascii = False  # type: ignore[attr-defined]
        app.json.sort_keys = False  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - גרסת Flask ישנה יותר
        pass

    app.register_blueprint(bp)

    # ---- רשת ביטחון ברמת האפליקציה: אף פעם לא דף HTML של traceback ----
    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException):  # pragma: no cover - נבדק דרך המסלולים
        if request.path.startswith("/api"):
            return _fail(
                exc.code or 500,
                _http_message_he(exc.code or 500),
                f"{type(exc).__name__}: {exc.description}",
            )
        return exc

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception):
        LOG.exception("שגיאה לא צפויה ב-%s %s", request.method, request.path)
        return _fail(
            500,
            "אירעה תקלה בלתי צפויה בשרת. הנתונים לא נפגעו.",
            f"{type(exc).__name__}: {exc}",
        )

    @app.after_request
    def _cache_control(response):
        """מה מותר לשמור במטמון, ולכמה זמן.

        ‏עד לפריסה מאחורי ‏Cloudflare היה כאן ``no-store`` גורף על כל
        ‏``/api``. זה היה נכון לאפליקציה מקומית שבה המסד משתנה תוך כדי, והוא
        מבזבז לגמרי מטמון קצה שמשרת מאות סטודנטים את אותו קטלוג בדיוק.

        ‏ברירת המחדל נשארה ``no-store``. רק מה שברשימת ההיתר נפתח.
        """
        endpoint = request.endpoint or ""

        if endpoint == "static":
            response.headers["Cache-Control"] = (
                f"public, max-age={STATIC_CACHE_SECONDS}"
            )
            return response

        if request.path.startswith("/api"):
            cacheable = (
                request.method == "GET"
                and endpoint in CACHEABLE_GET_ENDPOINTS
                and response.status_code == 200
            )
            response.headers["Cache-Control"] = (
                f"public, max-age={PUBLIC_CACHE_SECONDS}" if cacheable else "no-store"
            )
            return response

        # ‏הדף עצמו: תמיד לאמת מחדש. שמות הנכסים אינם נושאים גיבוב, ולכן דף
        # ‏ישן מהמטמון היה מצביע על אותן כתובות בדיוק — אבל לפחות הוא עצמו
        # לא יהיה ישן, וזה מה שקובע מתי משתמש רואה שינוי בתבנית.
        if endpoint == "index":
            response.headers["Cache-Control"] = "no-cache"
        elif endpoint == "healthz":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    def healthz():
        """בדיקת בריאות ל-Railway: ‏200 רק אם באמת יש מה להגיש.

        ‏**לא "השרת עונה" אלא "השרת עונה עם קטלוג".** התקלה שהבדיקה הזאת
        קיימת בשבילה היא ‏SLOTWISE_CATALOG_DIR שגוי או ‏volume שלא עלה: השרת
        עולה בשמחה, כל בקשה מחזירה ‏200, וכל רשימת קורסים ריקה. בדיקה שבודקת
        רק שהפורט פתוח הייתה מכריזה על פריסה כזאת כתקינה.

        ‏רשום מחוץ ל-``serve_ui`` כדי שיעבוד גם בפריסת ‏API בלבד.
        """
        try:
            meta = _shipped_meta()
            counts = meta.get("counts") if isinstance(meta.get("counts"), dict) else {}
            count = int(counts.get("courses") or 0)
            if not count:
                _catalog, summary = _catalog_snapshot()
                count = int(summary.get("count") or 0)
            built_at = str(meta.get("built_at") or "")
        except Exception as exc:  # noqa: BLE001 - בדיקת בריאות לא מפילה את עצמה
            LOG.exception("בדיקת הבריאות נכשלה")
            return jsonify({"ok": False, "course_count": 0,
                            "error": f"{type(exc).__name__}: {exc}"}), 503

        healthy = count > 0
        return jsonify({
            "ok": healthy,
            "course_count": count,
            "built_at": built_at,
            "catalog": str(_shipped_catalog_path()),
        }), (200 if healthy else 503)

    if serve_ui:
        _strings_stamp: dict[str, float] = {}

        @app.get("/")
        def index():
            """הדף היחיד, מוגש דרך Jinja.

            עד כאן הוא הוגש כקובץ סטטי, מחשש ש-JavaScript מוטבע עם ``{ }``
            יתנגש ב-Jinja. הקובץ מצהיר שאין בו קוד מוטבע ואין בו אף רצף
            ``{{`` / ``{%`` / ``{#``, ולכן החשש אינו רלוונטי — ו-Jinja הוא
            מה שמאפשר לטקסט הקבוע להגיע מ-``strings.json`` כבר בשרת,
            בלי הבהוב של כותרות ריקות.

            **אם מוסיפים אי־פעם סקריפט מוטבע לעמוד — יש לעטוף אותו
            ב-``{% raw %}``**, אחרת Jinja ינסה לפרש אותו.
            """
            # ‏טוענים מחדש אם קובץ הנוסח השתנה מאז. ``strings.py`` מחזיק
            # מטמון לכל חיי התהליך, ובשרת פיתוח שרץ שעות זה אומר שעריכת
            # נוסח — או הוספת strings.json מלכתחילה — לא מגיעה למסך, והדף
            # יוצא עם טקסט ריק בלי שום רמז לסיבה.
            stamp = strings_mod.mtime()
            S = strings_mod.load(refresh=stamp != _strings_stamp.get("mtime"))
            _strings_stamp["mtime"] = stamp
            if (templates_dir / "index.html").is_file():
                return render_template("index.html", S=S)
            ui = S.get("ui", {}).get("fallbackPage", {})
            body = str(ui.get("body", "")).replace(
                "{api}", "<code>/api</code>"
            ).replace("{file}", "<code>templates/index.html</code>")
            return (
                "<!doctype html><html dir=\"rtl\" lang=\"he\"><meta charset=\"utf-8\">"
                f"<title>{ui.get('title', '')}</title>"
                "<body style=\"font-family:system-ui;padding:2rem\">"
                f"<h1>{ui.get('heading', '')}</h1>"
                f"<p>{body}</p>"
                "</body></html>",
                200,
                {"Content-Type": "text/html; charset=utf-8"},
            )

    return app


# ===========================================================================
# 11. בדיקת עשן: python src/web/api.py
# ===========================================================================
def _smoke_test() -> int:  # pragma: no cover - כלי דיבוג ידני
    """מריץ את כל נקודות הקצה מול המסד האמיתי, בלי רשת ובלי דפדפן.

    ‏``allow_network=False`` הוא מה שהופך את ההבטחה הזו לאמת: מאז שהשליפה
    על-פי-דרישה מביאה גם *פרטי* קורס, כלי דיבוג ידני היה יכול לפנות לידיעון
    עשרות פעמים רק כדי להדפיס וי.
    """
    app = create_app({"allow_network": False})
    client = app.test_client()
    checks: list[tuple[str, bool, str]] = []

    def check(label: str, condition: bool, note: str = "") -> None:
        checks.append((label, bool(condition), note))
        mark = "✓" if condition else "✗"
        print(f"  {mark} {label}{(' — ' + note) if note else ''}")

    print("בדיקת עשן ל-src/web/api.py")
    print("=" * 74)

    res = client.get("/api/bootstrap")
    data = res.get_json()
    check("bootstrap", res.status_code == 200 and data.get("ok"), f"{len(data.get('semesters', []))} סמסטרים")

    res = client.get("/api/semester/5/courses")
    data = res.get_json()
    tied = [c for c in data.get("courses", []) if c.get("tied_with")]
    check("semester/5/courses", res.status_code == 200 and len(tied) >= 3, f"{len(tied)} קורסים צמודים")

    res = client.get("/api/catalog/search?q=617&limit=5")
    data = res.get_json()
    check("catalog/search", res.status_code == 200 and data.get("count", 0) > 0, f"{data.get('count')} תוצאות")

    res = client.get("/api/catalog/browse?prefix=110&limit=5")
    data = res.get_json()
    zeros = [c for c in data.get("results", []) if c.get("credits") == 0.0]
    check(
        "catalog/browse",
        res.status_code == 200 and data.get("count", 0) > 0 and not zeros,
        f"{data.get('count')}/{data.get('total')} תוצאות, בלי אף 0.0 מזויף",
    )

    codes = ["11069", "61753", "61756", "61757", "61832", "62027"]
    res = client.post("/api/courses", json={"codes": codes, "semester": "א"})
    data = res.get_json()
    groups = sum(c["group_count"] for c in data.get("courses", []))
    check("courses", res.status_code == 200 and groups == 27, f"{groups} קבוצות")

    res = client.post("/api/solve", json={"codes": codes, "semester": "א", "target_days": 4})
    data = res.get_json()
    check(
        "solve",
        res.status_code == 200 and data.get("feasible_count") == 16 and data.get("min_days") == 5,
        f"{data.get('feasible_count')} צירופים, מינימום {data.get('min_days')} ימים, {data.get('elapsed_ms')}ms",
    )
    check("target_reachable=False עבור 4 ימים", data.get("target_reachable") is False, data.get("target_message", ""))
    dead = ((data.get("viability") or {}).get("61753") or {}).get("הרצאה", {}).get("271070330", {})
    check("viability מסמן מבוי סתום", dead.get("ok") is False, dead.get("reason", ""))

    res = client.post("/api/solve", json={"codes": codes, "semester": "א", "pinned": {"61753": {"הרצאה": "271070330"}}})
    data = res.get_json()
    check(
        "נעיצה למבוי סתום -> 200 עם הסבר",
        res.status_code == 200 and data.get("ok") and data.get("feasible_count") == 0 and data.get("reasons"),
        f"{len(data.get('reasons', []))} סיבות, {len(data.get('suggestions', []))} הצעות",
    )

    res = client.post("/api/solve", data=b"{not json", content_type="application/json")
    data = res.get_json()
    check("JSON פגום -> 400 בעברית", res.status_code == 400 and data.get("ok") is False, data.get("error", ""))

    print("=" * 74)
    failed = [label for label, okay, _ in checks if not okay]
    print(f"עברו {len(checks) - len(failed)}/{len(checks)}")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_smoke_test())
