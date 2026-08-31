# -*- coding: utf-8 -*-
"""
‏src/web/api.py — שכבת ה-HTTP של בונה המערכת (the JSON translation layer).

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
import importlib
import json
import logging
import re
import sys
import threading
import time
from collections import deque
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

from flask import Blueprint, Flask, jsonify, request, send_from_directory  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

import curriculum as curriculum_mod  # noqa: E402
import discovery as discovery_mod  # noqa: E402
import models  # noqa: E402
import parser as parser_mod  # noqa: E402
import scheduler as scheduler_mod  # noqa: E402
import store as store_mod  # noqa: E402

LOG = logging.getLogger("schedule_builder.web")

# ---------------------------------------------------------------------------
# 1. קבועים
# ---------------------------------------------------------------------------

#: קוד קורס בבראודה — 4 עד 7 ספרות (11069 בן 5, 251961 בן 6).
CODE_RE = re.compile(r"^\d{4,7}$")

#: תקרת שורות ביומן הגרידה שנשמר בזיכרון. יומן שגדל בלי גבול הוא דליפה.
MAX_LOG_LINES = 500

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
    האם מוצע השנה) שאינם חלק מהמודל עצמו.
    """
    groups = sorted(course.groups, key=_group_sort_key)
    payload: dict[str, Any] = {
        "code": course.code,
        "name": course.name,
        "credits": float(course.credits),
        "tied_with": list(course.tied_with),
        "kinds": course.kinds(),
        "group_count": len(course.groups),
        "lecturers": course.lecturers(),
        "groups": [group_to_json(g) for g in groups],
    }
    if extra:
        payload.update(extra)
    return payload


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
                "credits": float(course.credits) if course is not None else 0.0,
                "note": group.note,
                "linked_to": list(group.linked_to),
                "meetings": [
                    meeting_to_json(m)
                    for m in sorted(group.meetings, key=lambda m: (m.day, m.start, m.end))
                ],
            }
        )

    days = sorted(sched.selection.days_used())
    # נ"ז נספרות פעם אחת לכל קורס, לא פעם אחת לכל רכיב.
    seen: set[str] = set()
    credits_total = 0.0
    for pick in picks:
        if pick["code"] not in seen:
            seen.add(pick["code"])
            credits_total += float(pick["credits"])

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
        "credits": round(credits_total, 2),
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
                "הנעיצות של כל קורס צריכות להיות מילון של {סוג רכיב: מספר קבוצה}.",
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
                "{סוג רכיב: כן/לא}.",
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

    return current_app.config["SCHEDULE_BUILDER"]


def _store() -> store_mod.Store:
    """מופע ``Store`` יחיד לכל אפליקציה. הקריאות עצמן חסרות מצב."""
    from flask import current_app

    cache = current_app.extensions.setdefault("schedule_builder", {})
    obj = cache.get("store")
    if obj is None:
        obj = store_mod.Store(str(_config()["db_root"]))
        cache["store"] = obj
    return obj


def _curriculum() -> dict:
    """תוכנית הלימודים, בקאש עם בדיקת mtime (עריכה של הקובץ נקלטת מיד)."""
    from flask import current_app

    cache = current_app.extensions.setdefault("schedule_builder", {})
    path = Path(_config()["curriculum_path"])
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        stamp = 0
    if cache.get("curriculum_stamp") != stamp or "curriculum" not in cache:
        cache["curriculum"] = curriculum_mod.load_curriculum(path)
        cache["curriculum_stamp"] = stamp
    return cache["curriculum"]


def _profile() -> dict:
    """‏data/profile.json — התשובות האמיתיות של הסטודנט/ית. חסר = ``{}``."""
    from flask import current_app

    cache = current_app.extensions.setdefault("schedule_builder", {})
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


def _import_root_module(name: str):
    """מייבא מודול מ*שורש* הפרויקט (``refresh``/``reparse``).

    מוסיפים את השורש ל-``sys.path`` ב**סוף** — כדי ש-``src/`` ימשיך לגבור
    ולא ניצור התנגשות שמות בשוגג.
    """
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.append(root)
    return importlib.import_module(name)


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
    store = _store()
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
                        "אין נתונים שמורים לקורס הזה. יש להריץ רענון מהידיעון "
                        "כדי למשוך את הקבוצות שלו."
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
                        f"הנתונים השמורים הם לסמסטר {stored_semester}, ולא לסמסטר {semester}. "
                        f"יש להריץ רענון מהידיעון לסמסטר המבוקש."
                    ),
                    "kind": "semester_mismatch",
                    "needs_scrape": True,
                }
            )
            continue

        # ── מה שהמנוע צריך ולא נמצא בדף הידיעון ──
        tied = [other for other in curriculum_mod.tied_group(curr, code) if other != code]
        course.tied_with = tied
        if entry.get("credits") is not None:
            course.credits = float(entry["credits"])
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
                        "reason": (
                            f"בקורס {code} אין רכיב מסוג {kind}, ולכן אי אפשר "
                            f"לנעוץ בו קבוצה. הנעיצה שוחררה."
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
                        "reason": (
                            f"קבוצה {group_id} אינה קיימת עוד ברכיב {kind} של קורס "
                            f"{code} — ייתכן שהנתונים התעדכנו. הנעיצה שוחררה; "
                            f"יש לבחור קבוצה אחרת ברשימה."
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
            "שליפה ישירה מהידיעון אינה זמינה כרגע (הרכיב yedion_http חסר). "
            "אפשר להריץ רענון מלא, או לפענח מחדש את הנתונים השמורים."
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
# 7. מצב הגרידה — thread אחד בלבד, יומן חסום בזיכרון
# ===========================================================================
_scrape_lock = threading.Lock()

#: כותב אחד בלבד ל-``data/db``. ``Store._atomic_write_text`` מקנה לקובץ הזמני
#: שם לפי **מזהה התהליך** בלבד, ולכן שני כותבים באותו שרת (thread הגרידה
#: ובקשת ``/api/reparse``) מתנגשים על אותו ``<path>.<pid>.tmp`` ונופלים
#: ב-WinError 32. הנעילה נלקחת בבקשה שמתחילה את הכתיבה ומשוחררת בסופה
#: (בגרידה — ב-thread שסיים; ‏``threading.Lock`` מתיר שחרור מ-thread אחר).
_db_write_lock = threading.Lock()

#: הצינור של ה-thread הנוכחי עבור ``_thread_stdout``.
_stdout_local = threading.local()
_stdout_proxy_lock = threading.Lock()
_stdout_proxy: Any = None
_stdout_users = 0
_scrape_log: deque[str] = deque(maxlen=MAX_LOG_LINES)
_scrape_state: dict[str, Any] = {
    "running": False,
    "phase": "idle",
    "exit_code": None,
    # ‏GROUND_TRUTH §9: במסלול ברירת המחדל אין התחברות בכלל, ולכן זה תמיד
    # ‏False. השדה נשאר קיים בשביל מסלול הדפדפן (``mode == "browser"``).
    "needs_login": False,
    "mode": "http",
    "started_at": None,
    "finished_at": None,
    "error": "",
    "codes": [],
    "message": "עדיין לא בוצע רענון בהרצה הזו.",
    "dropped_lines": 0,
}
_scrape_thread: threading.Thread | None = None

#: קודי היציאה של refresh.py (מתועדים ב-epilog שלו).
_EXIT_MESSAGES: dict[int, str] = {
    0: "הרענון הסתיים בהצלחה — הנתונים מעודכנים.",
    # קוד 2 שייך אך ורק למסלול הדפדפן. במסלול ברירת המחדל אין התחברות,
    # ולכן כישלון שם מדווח כשגיאה אמיתית ולא כ"צריך להתחבר".
    2: "נדרשת התחברות לידיעון. יש להשלים את ההתחברות בחלון הדפדפן שנפתח, ואז להריץ רענון שוב.",
    3: "הרענון הסתיים חלקית — חלק מהקורסים לא נשלפו. פירוט ביומן שלמטה.",
    1: "הרענון נכשל. פירוט ביומן שלמטה.",
    130: "הרענון הופסק.",
}

#: מילות מפתח שמזהות שלב מתוך שורת היומן שהגורד/הרענון הדפיסו.
#: ‏(תת-מחרוזת, שלב, מה לעשות עם needs_login) — ``None`` = לא לגעת.
#: הסדר קובע: המחרוזות הספציפיות לפני הכלליות, אחרת "התחברות זוהתה" הייתה
#: נקראת בטעות כ"ממתינים להתחברות".
_PHASE_MARKERS: tuple[tuple[str, str, bool | None], ...] = (
    ("התחברות זוהתה", "connected", False),
    ("Login detected", "connected", False),
    ("כבר מחוברים", "connected", False),
    ("התחברות ידנית לידיעון", "login", True),
    ("נדרשת התחברות", "login", True),
    ("ממתין להתחברות", "login", True),
    ("לא בוצעה התחברות", "login", True),
    ("יש להתחבר", "login", True),
    ("בודק אם הסשן", "session", None),
    ("שנת הלימודים", "year", None),
    ("מעבר שנה", "year", None),
    ("קטלוג", "catalog", None),
    ("מביא קורס", "fetching", None),
    ("נשמר", "saving", None),
    ("סיום", "finishing", None),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _scrape_emit(line: str, *, internal: bool = False) -> None:
    """שורה אחת ליומן, עם זיהוי שלב. בטוח לקריאה מה-thread של הגרידה.

    ``internal=True`` = שורה שאנחנו כתבנו (מסגור, הסבר), ולכן **אין** להסיק
    ממנה שלב. אחרת המשפט שמסביר שאיננו נוגעים בסיסמאות היה נקרא בטעות
    כ"נדרשת התחברות" עוד לפני שהדפדפן בכלל נפתח.
    """
    text = str(line).rstrip()
    if not text:
        return
    with _scrape_lock:
        if len(_scrape_log) == _scrape_log.maxlen:
            _scrape_state["dropped_lines"] = int(_scrape_state.get("dropped_lines", 0)) + 1
        _scrape_log.append(text)
        if internal:
            return
        for marker, phase, needs_login in _PHASE_MARKERS:
            if marker in text:
                _scrape_state["phase"] = phase
                if needs_login is not None:
                    _scrape_state["needs_login"] = bool(needs_login)
                break


def _scrape_snapshot() -> dict[str, Any]:
    """תמונת מצב עקבית של הגרידה, להחזרה ב-JSON."""
    with _scrape_lock:
        snapshot = dict(_scrape_state)
        snapshot["log"] = list(_scrape_log)
    return snapshot


class _LogStream:
    """קובץ-מדומה שמפצל את מה שנכתב אליו לשורות יומן, ומשקף למסוף.

    ‏``refresh.main`` ו-``reparse.main`` מדפיסים ב-``print``; זו הדרך לקלוט
    את ההתקדמות שלהם בלי לגעת בהם.
    """

    def __init__(self, emit: Callable[[str], None], mirror: Any = None) -> None:
        self._emit = emit
        self._mirror = mirror
        self._buffer = ""

    def write(self, text: str) -> int:
        data = str(text)
        if self._mirror is not None:
            try:
                self._mirror.write(data)
            except Exception:  # noqa: BLE001 - מסוף שלא יודע עברית לא יפיל גרידה
                pass
        self._buffer += data
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit(line)
        return len(data)

    def flush(self) -> None:
        if self._buffer.strip():
            self._emit(self._buffer)
        self._buffer = ""
        if self._mirror is not None:
            try:
                self._mirror.flush()
            except Exception:  # noqa: BLE001
                pass

    def isatty(self) -> bool:
        return False


class _ThreadStdout:
    """‏מחליף את ``sys.stdout`` פעם אחת, ומנתב כל כתיבה לפי ה-thread הכותב.

    למה לא ``contextlib.redirect_stdout``: הוא גלובלי לתהליך. הגרידה רצה
    ב-thread רקע ונמשכת דקות (היא ממתינה להתחברות ידנית), והשרת רץ
    ‏``threaded=True`` — כך שכל הדפסה של כל בקשה מקבילה, של werkzeug ושל כל
    ספרייה הייתה נבלעת ליומן הגרידה. גרוע מזה: שני redirect-ים שנסגרים בסדר
    לא-מקונן (גרידה + ``/api/reparse``) משאירים את ``sys.stdout`` תקוע על
    יומן של ריצה שכבר הסתיימה — ומאותו רגע המסוף שותק לצמיתות, בדיוק כשה-API
    מפנה את הסטודנט/ית "לחלון הטרמינל שבו רץ השרת".

    כאן כל thread רושם את הצינור שלו ב-``_stdout_local``; מי שלא רשם ממשיך
    למסוף האמיתי כרגיל.
    """

    def __init__(self, base: Any) -> None:
        self.base = base

    def _target(self) -> Any:
        return getattr(_stdout_local, "sink", None) or self.base

    def write(self, text: str) -> int:
        target = self._target()
        try:
            return target.write(text)
        except Exception:  # noqa: BLE001 - מסוף סגור לא מפיל גרידה
            fallback = sys.__stdout__
            if fallback is not None and fallback is not target:
                try:
                    return fallback.write(text)
                except Exception:  # noqa: BLE001
                    pass
            return len(str(text))

    def flush(self) -> None:
        try:
            self._target().flush()
        except Exception:  # noqa: BLE001
            pass

    def isatty(self) -> bool:
        try:
            return bool(self.base.isatty())
        except Exception:  # noqa: BLE001
            return False

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)


@contextlib.contextmanager
def _thread_stdout(stream: Any):
    """מנתב את ``print`` של ה-thread הנוכחי בלבד אל ``stream``.

    ה-proxy מותקן פעם אחת ומשותף לכל ה-threads, ולכן סדר היציאה לא משנה:
    הוא מוסר רק כשהמשתמש/ת האחרון/ה סיים/ה.
    """
    global _stdout_proxy, _stdout_users
    with _stdout_proxy_lock:
        if _stdout_proxy is None or sys.stdout is not _stdout_proxy:
            _stdout_proxy = _ThreadStdout(sys.stdout)
            sys.stdout = _stdout_proxy
        proxy = _stdout_proxy
        _stdout_users += 1

    previous = getattr(_stdout_local, "sink", None)
    _stdout_local.sink = stream
    try:
        yield
    finally:
        _stdout_local.sink = previous
        with _stdout_proxy_lock:
            _stdout_users = max(0, _stdout_users - 1)
            if _stdout_users == 0 and sys.stdout is proxy:
                sys.stdout = proxy.base
                _stdout_proxy = None


def _run_root_script(
    name: str,
    argv: list[str],
    emit: Callable[[str], None],
    *,
    mirror: bool = False,
) -> int:
    """מריץ ``<name>.main(argv)`` משורש הפרויקט וקולט את הפלט שלו ליומן.

    הקליטה היא **לכל thread בנפרד** (``_thread_stdout``), כך שהדפסות של בקשות
    אחרות לא נבלעות לכאן.

    ``mirror=False`` (ברירת המחדל) = **שום שורה לא מגיעה למסך**. זו דרישה
    מפורשת: שורות הריצה שהופיעו על המסך בזמן רענון הן בדיוק מה שביקשו שלא
    יופיע. ההתקדמות נשמרת ביומן שבזיכרון ומוגשת ב-``/api/scrape/status``,
    ומה שנשבר באמת נרשם דרך ``LOG`` בצד השרת.
    """
    module = _import_root_module(name)
    stream = _LogStream(emit, mirror=sys.__stdout__ if mirror else None)
    with _thread_stdout(stream):
        try:
            return int(module.main(list(argv)))
        finally:
            stream.flush()


def _argv_has(argv: list[str], flag: str) -> bool:
    return flag in list(argv or [])


def _argv_value(argv: list[str], flag: str, default: str = "") -> str:
    """הערך שאחרי ``flag`` ב-argv, או ``flag=value``. חסר → ``default``."""
    items = [str(a) for a in (argv or [])]
    for i, item in enumerate(items):
        if item == flag and i + 1 < len(items):
            return items[i + 1]
        if item.startswith(flag + "="):
            return item.split("=", 1)[1]
    return default


def _http_scrape_runner(argv: list[str], emit: Callable[[str], None]) -> int:
    """רענון ישיר ב-HTTP בתוך התהליך — בלי דפדפן ובלי התחברות.

    מסלול גיבוי ל-``refresh.main``: אותו שולף (``yedion_http.YedionHTTP``),
    אותו פענוח ואותה שמירה, דרך ``fetch_courses_into_store``. ה-``log`` של
    השולף מוזרם ליומן שבזיכרון, ולכן שום שורה לא מגיעה למסך.

    Returns:
        ‏0 הצלחה, 3 הצלחה חלקית, 1 כישלון. **אף פעם לא 2** — אין כאן התחברות.
    """
    student = _profile().get("student") or {}
    year_gregorian = _argv_value(argv, "--year") or _gregorian_for(
        student.get("academic_year")
    )
    year_he = _hebrew_year_for(year_gregorian) or str(student.get("academic_year") or "")
    semester = _argv_value(argv, "--semester") or str(student.get("term") or "")
    codes = [c for c in re.split(r"[,\s]+", _argv_value(argv, "--codes")) if c]
    catalog_only = _argv_has(argv, "--catalog-only")
    max_age_text = _argv_value(argv, "--max-age")

    fetcher, error, injected = _make_fetcher(
        year_gregorian=year_gregorian, log=emit, delay_s=FETCH_DELAY_S
    )
    if fetcher is None:
        emit(error)
        return 1
    error = _open_fetcher_session(fetcher, year_he)
    if error:
        emit(error)
        return 1
    delay_s = 0.0 if injected else FETCH_DELAY_S

    if catalog_only:
        result = fetch_catalog_into_store(
            year_he=year_he,
            year_gregorian=year_gregorian,
            emit=emit,
            fetcher=fetcher,
        )
        return 0 if result.get("ok") else 1

    store = _store()
    if not codes:
        codes = store.tracked()
    if not codes:
        emit("אין קורסים במעקב, ולכן אין מה לרענן.")
        return 0

    # נימוס: מרעננים רק מה שבאמת התיישן (GROUND_TRUTH §9).
    if max_age_text:
        try:
            stale = store.stale_codes(codes, float(max_age_text))
        except (TypeError, ValueError):
            stale = list(codes)
        fresh = [c for c in codes if c not in stale]
        if fresh:
            emit(f"מדלגים על {len(fresh)} קורסים שהנתונים שלהם עדיין טריים.")
        codes = stale
        if not codes:
            emit("כל הנתונים טריים — אין מה לרענן.")
            return 0

    emit(f"מרענן {len(codes)} קורסים…")
    report = fetch_courses_into_store(
        codes,
        semester=semester,
        year_he=year_he,
        year_gregorian=year_gregorian,
        emit=emit,
        cap=len(codes),
        delay_s=delay_s,
        fetcher=fetcher,
    )
    fetched = list(report.get("fetched") or [])
    failed = list(report.get("failed") or [])
    changed = sum(len(v) for v in (report.get("changes") or {}).values())
    emit(f"עודכנו {len(fetched)} קורסים, {changed} שינויים.")
    if failed and not fetched:
        return 1
    return 3 if failed else 0


def _default_scrape_runner(argv: list[str], emit: Callable[[str], None]) -> int:
    """ברירת המחדל של הרענון: ``refresh.main`` — **בלי דפדפן ובלי התחברות**.

    מאז ‏GROUND_TRUTH §9 חיפוש הקורסים בידיעון פתוח לקריאה, ו-``refresh.py``
    שולף ב-HTTP ישיר אלא אם התבקש ``--browser`` במפורש. קוראים לו ולא כותבים
    כאן רענון מקביל, כי הוא זה שמנהל גם את יומן השינויים, את רשימת המעקב ואת
    דוח הריצה — ורענון "משלנו" היה מאבד את כל אלה בשקט.

    אם ``refresh`` בכלל לא ניתן לטעינה, עוברים לשליפה ישירה בתוך התהליך
    (``_http_scrape_runner``) במקום להשאיר את הסטודנט/ית בלי רענון.
    """
    try:
        return _run_root_script("refresh", argv, emit)
    except (ImportError, ModuleNotFoundError) as exc:
        if _argv_has(argv, "--browser"):
            raise
        LOG.warning("refresh.py אינו זמין (%s) — עוברים לשליפה ישירה", exc)
        emit("רכיב הרענון הראשי אינו זמין — ממשיכים בשליפה ישירה מהידיעון.")
        return _http_scrape_runner(argv, emit)


#: שם היסטורי, נשמר כדי שקוד קיים שמצביע עליו ימשיך לעבוד.
_default_refresh_runner = _default_scrape_runner


def _default_reparse_runner(argv: list[str], emit: Callable[[str], None]) -> int:
    """ברירת המחדל: ``reparse.main`` — פענוח מחדש מ-data/raw, בלי רשת."""
    return _run_root_script("reparse", argv, emit)


def _scrape_worker(
    runner: Callable[[list[str], Callable[[str], None]], int],
    argv: list[str],
    intro: Iterable[str] = (),
) -> None:
    """ה-thread של הרענון. אף פעם לא זורק — מסיים תמיד עם exit_code.

    ``intro`` הן שורות הפתיחה של היומן, והן תלויות במסלול: ברירת המחדל היא
    ‏HTTP ישיר בלי דפדפן, ורק ``--browser`` פותח חלון.
    """
    exit_code = 1
    error = ""
    try:
        _scrape_emit("מתחיל רענון מהידיעון…", internal=True)
        for line in intro:
            _scrape_emit(line, internal=True)
        exit_code = int(runner(argv, _scrape_emit))
    except Exception as exc:  # noqa: BLE001 - thread שנופל בשקט הוא הגרוע מכול
        LOG.exception("הרענון נכשל")
        error = f"{type(exc).__name__}: {exc}"
        _scrape_emit(f"תקלה: {error}", internal=True)
        exit_code = 1
    finally:
        with _scrape_lock:
            _scrape_state["running"] = False
            _scrape_state["exit_code"] = exit_code
            _scrape_state["finished_at"] = _now_iso()
            _scrape_state["error"] = error
            _scrape_state["phase"] = "done" if exit_code == 0 else "failed"
            if exit_code == 2:
                _scrape_state["needs_login"] = True
                _scrape_state["phase"] = "needs_login"
            _scrape_state["message"] = _EXIT_MESSAGES.get(
                exit_code, f"הרענון הסתיים עם קוד {exit_code}."
            )


def reset_scrape_state() -> None:
    """מאפס את מצב הגרידה. נועד לבדיקות — לא נקרא בזרימה רגילה."""
    global _scrape_thread
    with _scrape_lock:
        _scrape_log.clear()
        _scrape_state.update(
            {
                "running": False,
                "phase": "idle",
                "exit_code": None,
                "needs_login": False,
                "mode": "http",
                "started_at": None,
                "finished_at": None,
                "error": "",
                "codes": [],
                "message": "עדיין לא בוצע רענון בהרצה הזו.",
                "dropped_lines": 0,
            }
        )
    # אין thread חי — אין סיבה שהנעילה על המסד תישאר תפוסה. אם יש thread חי
    # הנעילה שייכת לו, ושחרור מכאן היה גוזל אותה ממנו.
    if _scrape_thread is None or not _scrape_thread.is_alive():
        try:
            _db_write_lock.release()
        except RuntimeError:
            pass
    _scrape_thread = None


# ===========================================================================
# 8. עזרי תצוגה
# ===========================================================================
def _semester_label(semester: str, info: dict) -> str:
    """'שנה ג׳ · סמסטר א׳ (חורף)' — התווית שהממשק מציג בשלב 1."""
    year = info.get("year")
    term = str(info.get("term") or "")
    year_text = YEAR_LABELS.get(int(year), f"שנה {year}") if isinstance(year, int) else ""
    term_text = TERM_LABELS.get(term, f"סמסטר {term}" if term else "")
    parts = [p for p in (year_text, term_text) if p]
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
        "any_stale": bool(freshness.get("stale")),
        "age_hours": freshness.get("age_hours"),
        "age_text": store_mod.format_hebrew_age(freshness.get("age_hours")),
        "text": freshness.get("text", ""),
        "newest": freshness.get("newest", ""),
        "oldest": freshness.get("oldest", ""),
        "max_age_hours": max_age,
        "courses": {code: _meta_to_json(metas.get(code), max_age) for code in codes},
    }


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
    """כל מה שהממשק צריך בפתיחה: ברירות מחדל, סמסטרים, טריות, קטלוג, גרידה."""
    curr = _curriculum()
    profile = _profile()
    student = profile.get("student") or {}
    prefs = profile.get("preferences") or {}

    semesters = []
    for key in sorted((curr.get("semesters") or {}).keys(), key=lambda k: (len(k), k)):
        try:
            info = curriculum_mod.semester_info(curr, key)
        except curriculum_mod.UnknownSemesterError:  # pragma: no cover - לא אמור לקרות
            continue
        courses = curriculum_mod.semester_courses(curr, key)
        semesters.append(
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
            }
        )

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
        "semester": str(student.get("curriculum_semester") or ""),
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
            "terms": [
                {"term": key, "label": label, "in_curriculum": key in {"א", "ב"}}
                for key, label in TERM_LABELS.items()
            ],
            "years": [{"year": y, "label": label} for y, label in sorted(YEAR_LABELS.items())],
            "summer_note": (
                "בתוכנית הלימודים אין סמסטר קיץ — אפשר לבחור קורסים מהקטלוג החי, "
                "אבל אין רשימת קורסים מומלצת לסמסטר הזה."
            ),
            "curriculum": {
                "program": curr.get("program", ""),
                "catalog": curr.get("catalog", ""),
                "degree_credits_required": curr.get("degree_credits_required"),
                "hour_legend": curr.get("hour_legend") or {},
            },
            "db": _db_snapshot(),
            "catalog": catalog_summary,
            "scrape": _scrape_snapshot(),
            "day_names": {str(k): v for k, v in models.DAY_NAMES_HE.items()},
            "day_letters": {str(k): v for k, v in models.DAY_LETTERS_HE.items()},
            "kind_order": list(models.KIND_ORDER),
            "limits": {
                "max_codes": MAX_CODES,
                "max_top_n": MAX_TOP_N,
                "max_log_lines": MAX_LOG_LINES,
                "max_ondemand_fetches": MAX_ONDEMAND_FETCHES,
                "fetch_delay_s": FETCH_DELAY_S,
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
            },
        }
    )


# ------------------------------------------------------- semester courses
@bp.get("/semester/<sem>/courses")
@_endpoint
def semester_courses(sem: str):
    """קורסי הסמסטר מתוך ``curriculum.json``, עם 'מוצע השנה' ו'יש נתונים'."""
    curr = _curriculum()
    try:
        entries = curriculum_mod.semester_courses(curr, sem)
        info = curriculum_mod.semester_info(curr, sem)
    except curriculum_mod.UnknownSemesterError as exc:
        raise ApiError(404, str(exc).split("(")[0].strip(), f"unknown semester {sem!r}") from exc

    catalog, _summary = _catalog_snapshot()
    offered = discovery_mod.offered_codes(catalog)
    store = _store()
    have_data = set(store.codes())

    courses: list[dict[str, Any]] = []
    credits_total = 0.0
    for entry in entries:
        raw_code = entry.get("code")
        code = str(raw_code).strip() if raw_code else ""
        credits = float(entry.get("credits") or 0.0)
        credits_total += credits

        item: dict[str, Any] = {
            "code": code or None,
            "name": entry.get("name", ""),
            "credits": credits,
            "he": entry.get("he", 0),
            "te": entry.get("te", 0),
            "ma": entry.get("ma", 0),
            "pr": entry.get("pr", 0),
            "prereq": [str(p) for p in (entry.get("prereq") or [])],
            "tied_with": [],
            "note": entry.get("note", ""),
            "cond": entry.get("cond", ""),
            "group": entry.get("group", ""),
            "curriculum_semester": str(sem),
            "selectable": bool(code),
            "offered": False,
            "has_data": False,
        }

        if code:
            item["tied_with"] = [
                other for other in curriculum_mod.tied_group(curr, code) if other != code
            ]
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

    return _ok(
        {
            "semester": str(sem),
            "info": {
                "year": info.get("year"),
                "term": info.get("term", ""),
                "label": _semester_label(str(sem), info),
                "total": info.get("total") or {},
                "plus": info.get("plus", ""),
            },
            "courses": courses,
            "credits_total": round(credits_total, 2),
            "count": len(courses),
        }
    )


# --------------------------------------------------------- catalog search
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

    results: list[dict[str, Any]] = []
    for code, name in hits:  # סדר הדירוג של search_catalog נשמר
        info = annotated.get(code) or {}
        in_curriculum = bool(info.get("in_curriculum"))
        semester = info.get("curriculum_semester")
        cluster = info.get("cluster")
        if in_curriculum and semester:
            tag = f"[בתוכנית-סמסטר {semester}]"
        elif in_curriculum and cluster:
            tag = f"[אשכול בחירה: {cluster}]"
        elif in_curriculum:
            tag = "[בתוכנית]"
        else:
            tag = "[מחוץ לתוכנית]"
        results.append(
            {
                "code": code,
                "name": name,
                "in_curriculum": in_curriculum,
                "curriculum_semester": semester,
                "cluster": cluster,
                "credits": info.get("credits"),
                "tied_with": list(info.get("tied_with") or []),
                "prereq": list(info.get("prereq") or []),
                "has_data": code in have_data,
                "tag": tag,
            }
        )

    return _ok({"query": query, "limit": limit, "results": results, "count": len(results)})


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
    }
    wanted = _stale_or_missing(
        codes, problems, metas, year=year, max_age_hours=max_age_hours
    )
    report["requested"] = wanted
    if not wanted:
        return report

    def skip_all(reason: str) -> dict[str, Any]:
        report["skipped"] = [{"code": code, "reason": reason} for code in wanted]
        return report

    if not enabled:
        return skip_all(
            "שליפה מהידיעון לא התבקשה בבקשה הזו (fetch_missing=false). "
            "הנתונים שמוצגים הם מה ששמור במסד."
        )
    if not _network_allowed():
        return skip_all(
            "פנייה לידיעון מושבתת בהרצה הזו, ולכן לא נשלפו נתונים חדשים. "
            "אפשר להריץ רענון מהידיעון כדי להשלים אותם."
        )
    with _scrape_lock:
        if _scrape_state["running"]:
            return skip_all(
                "רענון מהידיעון רץ כרגע. הנתונים יושלמו בסיומו — אפשר לעקוב "
                "אחריו ביומן הרענון."
            )
    # כותב יחיד ל-data/db: אותה נעילה שמפרידה בין הרענון לפענוח מחדש.
    if not _db_write_lock.acquire(blocking=False):
        return skip_all(
            "פעולה אחרת כותבת כרגע לנתונים. אפשר לנסות שוב בעוד רגע."
        )
    try:
        result = fetch_courses_into_store(
            wanted,
            semester=semester,
            year_he=year,
            year_gregorian=year_gregorian,
            cap=MAX_ONDEMAND_FETCHES,
            delay_s=FETCH_DELAY_S,
        )
    finally:
        _db_write_lock.release()

    for key in ("fetched", "failed", "skipped", "changes", "not_offered", "log", "error"):
        report[key] = result.get(key, report[key])
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
    fetch_reasons: dict[str, str] = {}
    for item in list(fetch_report["failed"]) + list(fetch_report["skipped"]):
        fetch_reasons.setdefault(str(item.get("code")), str(item.get("reason") or ""))

    sources: dict[str, str] = {}
    for problem in problems:
        code = str(problem.get("code"))
        problem["source"] = "fetched" if code in fetched_ok else "unavailable"
        sources[code] = problem["source"]
        reason = fetch_reasons.get(code)
        if reason:
            # הסיבה הקונקרטית ("הידיעון לא מציג קבוצות") עדיפה על הכללית.
            problem["fetch_reason"] = reason
            problem["reason"] = reason

    payload: list[dict[str, Any]] = []
    credits_total = 0.0
    for course in built:
        sources[course.code] = "fetched" if course.code in fetched_ok else "db"
        meta = metas.get(course.code)
        warnings: list[str] = []
        if not _year_matches(year, meta):
            warnings.append(
                f"הנתונים השמורים הם לשנת {meta.year or '?'}, ולא לשנת {year}. "
                f"יש להריץ רענון מהידיעון כדי לוודא."
            )
        meta_json = _meta_to_json(meta, max_age)
        if meta_json["stale"]:
            warnings.append(
                f"הנתונים של הקורס נשלפו {meta_json['age_text']} ועשויים להיות מיושנים."
            )
        credits_total += float(course.credits)
        payload.append(
            course_to_json(
                course,
                {
                    "offered": True,
                    "source": sources.get(course.code, "db"),
                    "freshness": meta_json,
                    "warnings": warnings,
                    "curriculum_semester": (
                        curriculum_mod.find_course_source(_curriculum(), course.code) or ""
                    ).replace("semester:", ""),
                },
            )
        )

    return _ok(
        {
            "semester": semester,
            "year": year,
            "codes": codes,
            "courses": payload,
            "not_offered": problems,
            "credits_total": round(credits_total, 2),
            "count": len(payload),
            "sources": sources,
            "fetch": fetch_report,
            "fetch_missing": fetch_missing,
            # ברירות הנוכחות, כדי שהממשק יוכל להציג "כך כתוב בידיעון".
            "attendance": attendance_info(built),
        }
    )


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
    allow_soft_conflicts = _as_bool(body.get("allow_soft_conflicts"), False)
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
        "credits_total": 0.0,
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
            "יש להריץ רענון מהידיעון (הכפתור 'רענון מהידיעון') כדי למשוך את נתוני הקבוצות."
        ]
        base_common["target_message"] = ""
        return _ok(base_common)

    started = time.perf_counter()

    # ── 2. נעיצות: **מסננת על הבחירות**, לא מחיקת קבוצות. המנוע לא משתנה
    #      ומקבל את הקורסים שלמים — אחרת linked_to היה מפסיק להיאכף. ──
    applied_pins, dropped_pins = resolve_pins(built, pinned_request)
    base_common["pinned"] = applied_pins
    base_common["dropped_pins"] = dropped_pins
    base_common["credits_total"] = round(sum(float(c.credits) for c in built), 2)

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
                    "יש לבחור קבוצה אחרת ברשימה במקום הנעיצה שאינה קיימת עוד, "
                    "או לשחרר את הנעיצה כדי לראות שוב את כל האפשרויות."
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
                0,
                "יש לשחרר אחת מהקבוצות הנעוצות — נעיצה אחת יכולה לבדה למנוע כל פתרון.",
            )
        base_common["reasons"] = reasons
        base_common["suggestions"] = suggestions
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


# ----------------------------------------------------------- scrape start
@bp.post("/scrape/start")
@_endpoint
def scrape_start():
    """מתחיל רענון מהידיעון ב-thread רקע. חוזר מיד; ההתקדמות ב-/api/scrape/status.

    ‏**ברירת המחדל אינה דורשת התחברות ואינה פותחת דפדפן.** חיפוש הקורסים
    בידיעון פתוח לקריאה (GROUND_TRUTH §9), ולכן הרענון רץ בשקט ברקע ואפשר
    להריץ אותו גם כמשימה יומית. ההתקדמות נכתבת ליומן שבזיכרון בלבד —
    אף שורה לא מגיעה למסך.

    ``browser: true`` בוחר את מסלול הגיבוי דרך Playwright, שבו יש חלון
    התחברות ידני. גם שם האפליקציה אינה מבקשת, אינה רואה ואינה שומרת פרטי
    התחברות — אין בה שדה כזה בכלל.
    """
    global _scrape_thread

    body = _read_body(required=False)
    student = _profile().get("student") or {}

    codes = _clean_codes(body.get("codes"), field="codes", allow_empty=True)
    if not codes:
        codes = [str(c) for c in (_profile().get("scrape_codes") or [])]
        codes = _clean_codes(codes, field="codes", allow_empty=True)
    semester = str(body.get("semester") or student.get("term") or "")
    year_he = str(body.get("year") or student.get("academic_year") or "")
    year_greg = str(body.get("year_gregorian") or "") or _gregorian_for(year_he)
    catalog_only = _as_bool(body.get("catalog_only"), False)
    max_age = body.get("max_age")
    # מסלול הדפדפן נבחר רק כשמבקשים אותו במפורש. ברירת המחדל: HTTP ישיר.
    browser = _as_bool(body.get("browser"), False)
    mode = "browser" if browser else "http"

    argv: list[str] = ["--browser", "--headful"] if browser else []
    if codes and not catalog_only:
        argv += ["--codes", ",".join(codes)]
    if catalog_only:
        argv.append("--catalog-only")
    if year_greg:
        argv += ["--year", year_greg]
    if semester:
        argv += ["--semester", semester]
    if max_age is not None and max_age != "":
        argv += ["--max-age", str(float(max_age))]

    from flask import current_app

    runner = current_app.config.get("SCRAPE_RUNNER") or _default_scrape_runner
    # ה-thread צריך את ההגדרות, את ה-Store ואת הפרופיל — כולם נקראים דרך
    # ``current_app``. לוכדים את האובייקט עכשיו ודוחפים לו הקשר שם.
    app_object = current_app._get_current_object()  # noqa: SLF001

    intro = (
        (
            "בעוד רגע ייפתח חלון דפדפן. יש להשלים בו את ההתחברות לידיעון — "
            "האפליקציה אינה מבקשת, אינה רואה ואינה שומרת פרטי התחברות.",
        )
        if browser
        else (
            "הרענון רץ ברקע בלי דפדפן ובלי הזדהות — חיפוש הקורסים בידיעון "
            "פתוח לקריאה.",
        )
    )

    with _scrape_lock:
        if _scrape_state["running"]:
            raise ApiError(
                409,
                "רענון מהידיעון כבר רץ כרגע. יש להמתין לסיומו — אפשר לעקוב אחריו "
                "בחלון היומן — ורק אז להתחיל רענון נוסף.",
                "a scrape is already running",
            )
        # כותב אחד בלבד למסד. הנעילה נלקחת כאן ומשוחררת ב-thread שיסיים.
        if not _db_write_lock.acquire(blocking=False):
            raise ApiError(
                409,
                "פענוח מחדש של הנתונים רץ כרגע. יש להמתין לסיומו ורק אז להתחיל "
                "רענון מהידיעון — שתי הפעולות כותבות לאותם קבצים.",
                "a db write (reparse) is already in progress",
            )
        _scrape_log.clear()
        _scrape_state.update(
            {
                "running": True,
                "phase": "starting",
                "exit_code": None,
                "needs_login": False,
                "mode": mode,
                "started_at": _now_iso(),
                "finished_at": None,
                "error": "",
                "codes": codes,
                "message": (
                    "הרענון התחיל. ייפתח חלון דפדפן להתחברות ידנית."
                    if browser
                    else "הרענון התחיל ורץ ברקע — בלי דפדפן ובלי התחברות."
                ),
                "dropped_lines": 0,
            }
        )

    def _guarded_worker() -> None:
        """מריץ את ה-worker ומבטיח ניקוי — תהיה אשר תהיה התנהגותו.

        הנעילה על המסד נלקחה ב-thread של הבקשה, ורק כאן היא משוחררת — פעם
        אחת בדיוק. בלי הרשת הזו, worker שנופל, נתלה או מוחלף היה משאיר את
        כפתור הרענון ואת ``/api/reparse`` נעולים עד סוף חיי התהליך.
        """
        try:
            with app_object.app_context():
                _scrape_worker(runner, argv, intro)
        finally:
            with _scrape_lock:
                if _scrape_state["running"]:
                    _scrape_state["running"] = False
                    _scrape_state["finished_at"] = _scrape_state["finished_at"] or _now_iso()
                    if _scrape_state["phase"] in ("starting", "idle"):
                        _scrape_state["phase"] = "done"
            try:
                _db_write_lock.release()
            except RuntimeError:  # pragma: no cover - כבר שוחררה
                pass

    thread = threading.Thread(
        target=_guarded_worker,
        name="schedule-builder-scrape",
        daemon=True,
    )
    _scrape_thread = thread
    try:
        thread.start()
    except BaseException:  # noqa: BLE001 - לא משאירים נעילה תלויה באוויר
        _db_write_lock.release()
        with _scrape_lock:
            _scrape_state["running"] = False
            _scrape_state["phase"] = "failed"
            _scrape_state["message"] = "לא הצלחנו להתחיל את הרענון."
        raise

    return _ok(
        {
            "started": True,
            "argv": argv,
            "codes": codes,
            "mode": mode,
            "note": (
                "ייפתח חלון דפדפן. יש להשלים בו את ההתחברות ידנית — "
                "האפליקציה אינה מבקשת ואינה שומרת פרטי התחברות."
                if browser
                else "הרענון רץ ברקע. אין צורך להתחבר ואין חלון שנפתח."
            ),
            "scrape": _scrape_snapshot(),
        },
        status=202,
    )


# ---------------------------------------------------------- scrape status
@bp.get("/scrape/status")
@_endpoint
def scrape_status():
    """מצב הרענון לתשאול (polling): running, phase, log, exit_code, needs_login."""
    snapshot = _scrape_snapshot()
    snapshot["ok"] = True
    response = jsonify(snapshot)
    response.status_code = 200
    return response


# ---------------------------------------------------------------- reparse
@bp.post("/reparse")
@_endpoint
def reparse():
    """בונה מחדש את המסד מ-``data/raw`` — בלי רשת, בלי דפדפן, בלי התחברות."""
    body = _read_body(required=False)
    student = _profile().get("student") or {}

    codes = _clean_codes(body.get("codes"), field="codes", allow_empty=True)
    semester = str(body.get("semester") or "")
    year = str(body.get("year") or "")

    argv: list[str] = []
    if codes:
        argv += ["--codes", ",".join(codes)]
    if semester:
        if semester not in {"א", "ב", "קיץ"}:
            raise ApiError(
                400,
                "סמסטר לא תקין. הערכים האפשריים הם א, ב או קיץ.",
                f"semester={semester!r}",
            )
        argv += ["--semester", semester]
    if year:
        argv += ["--year", year]

    from flask import current_app

    runner = current_app.config.get("REPARSE_RUNNER") or _default_reparse_runner

    lines: list[str] = []

    def emit(line: str) -> None:
        if len(lines) < MAX_LOG_LINES:
            lines.append(str(line).rstrip())

    # ── כותב אחד בלבד ל-data/db ──
    # גם הרענון וגם הפענוח מחדש שומרים דרך ``Store.save_course``, ושם הקובץ
    # הזמני נגזר ממזהה **התהליך** — כך ששני כותבים בתוך אותו שרת מתנגשים על
    # אותו ``<path>.<pid>.tmp``. בלי המשמר הזה קליק על "פענוח מחדש" בזמן
    # שחלון ההתחברות פתוח היה יכול להפיל את השמירה של הגרידה באמצע.
    with _scrape_lock:
        if _scrape_state["running"]:
            raise ApiError(
                409,
                "רענון מהידיעון רץ כרגע. יש להמתין לסיומו ורק אז להריץ פענוח "
                "מחדש — שתי הפעולות כותבות לאותם קבצים.",
                "a scrape is running",
            )
    if not _db_write_lock.acquire(blocking=False):
        raise ApiError(
            409,
            "פעולה שכותבת לנתונים כבר רצה כרגע. יש להמתין לסיומה ורק אז לנסות שוב.",
            "a db write is already in progress",
        )

    started = time.perf_counter()
    try:
        exit_code = int(runner(argv, emit))
    except Exception as exc:  # noqa: BLE001
        LOG.exception("reparse נכשל")
        raise ApiError(
            500,
            "הפענוח מחדש נכשל. הנתונים הקיימים לא נמחקו.",
            f"{type(exc).__name__}: {exc}",
        ) from exc
    finally:
        _db_write_lock.release()

    message = {
        0: "הפענוח מחדש הסתיים בהצלחה.",
        3: "הפענוח מחדש הסתיים חלקית — חלק מהקורסים אינם שמורים או אינם נפתחים בסמסטר הזה.",
    }.get(exit_code, f"הפענוח מחדש הסתיים עם קוד {exit_code}.")

    # הקאש של הקורסים נקרא מהדיסק בכל פעם, אבל התוכנית והפרופיל בקאש —
    # אחרי reparse נכון להחזיר תמונת מסד עדכנית.
    return _ok(
        {
            "exit_code": exit_code,
            "message": message,
            "log": lines,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "db": _db_snapshot(),
            "argv": argv,
            "student_semester": student.get("term", ""),
        }
    )


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
            (‏``None`` = אוטומטי: אין רשת בתוך בדיקות), ``scrape_runner``,
            ``reparse_runner``, ``course_fetcher`` (הזרקות לבדיקות — כדי שלא
            ייפתח דפדפן ושלא תיפתח פנייה אמיתית לידיעון).
        db_root: קיצור דרך ל-``config["db_root"]``, כדי שאפשר יהיה להריץ
            את האפליקציה מול עותק זמני של המסד בלי לגעת באמיתי.
        serve_ui: האם להגיש גם את ``templates/index.html`` ואת ``static/``.
            ``False`` = ‏API בלבד.

    Returns:
        ``Flask`` מוכן. ההרצה עצמה (וה-host 127.0.0.1) היא באחריות ``webapp.py``.
    """
    settings: dict[str, Any] = {
        "db_root": str(PROJECT_ROOT / "data" / "db"),
        "curriculum_path": str(PROJECT_ROOT / "data" / "curriculum.json"),
        "profile_path": str(PROJECT_ROOT / "data" / "profile.json"),
        "raw_dir": str(PROJECT_ROOT / "data" / "raw"),
        "browser_profile_dir": str(PROJECT_ROOT / "data" / ".browser_profile"),
        "max_age_hours": float(store_mod.DEFAULT_MAX_AGE_HOURS),
        # ‏None = אוטומטי: פנייה לידיעון מותרת, אבל לא בתוך הרצת בדיקות.
        "allow_network": None,
    }
    overrides = dict(config or {})
    scrape_runner = overrides.pop("scrape_runner", None)
    reparse_runner = overrides.pop("reparse_runner", None)
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
    app.config["SCHEDULE_BUILDER"] = settings
    app.config["SCRAPE_RUNNER"] = scrape_runner
    app.config["REPARSE_RUNNER"] = reparse_runner
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
    def _no_store(response):
        # מצב המסד והגרידה משתנים תוך כדי — קאש של הדפדפן רק היה משקר.
        if request.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    if serve_ui:

        @app.get("/")
        def index():
            """הדף היחיד. מוגש כקובץ סטטי — בלי Jinja, כדי ש-JS עם { } ישרוד."""
            if (templates_dir / "index.html").is_file():
                return send_from_directory(str(templates_dir), "index.html")
            return (
                "<!doctype html><html dir=\"rtl\" lang=\"he\"><meta charset=\"utf-8\">"
                "<title>בונה המערכת</title>"
                "<body style=\"font-family:system-ui;padding:2rem\">"
                "<h1>השרת עובד</h1>"
                "<p>ה-API זמין תחת <code>/api</code>, אבל הקובץ "
                "<code>templates/index.html</code> עדיין לא קיים.</p>"
                "</body></html>",
                200,
                {"Content-Type": "text/html; charset=utf-8"},
            )

    return app


# ===========================================================================
# 11. בדיקת עשן: python src/web/api.py
# ===========================================================================
def _smoke_test() -> int:  # pragma: no cover - כלי דיבוג ידני
    """מריץ את כל נקודות הקצה מול המסד האמיתי, בלי רשת ובלי דפדפן."""
    app = create_app()
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
