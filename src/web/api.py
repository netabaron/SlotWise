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


def schedule_to_json(
    sched: models.ScoredSchedule, courses: Any = None
) -> dict[str, Any]:
    """מערכת מנוקדת → dict. טהורה.

    ``courses`` (רשימה או מילון של ``Course``) משמש רק כדי לצרף שם ונ"ז לכל
    בחירה; בלעדיו השדות האלה יחזרו ריקים, והמבנה נשאר זהה.
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
    "needs_login": False,
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


def _run_root_script(name: str, argv: list[str], emit: Callable[[str], None]) -> int:
    """מריץ ``<name>.main(argv)`` משורש הפרויקט וקולט את הפלט שלו ליומן.

    הקליטה היא **לכל thread בנפרד** (``_thread_stdout``), ומשוקפת תמיד
    ל-``sys.__stdout__`` כדי שהמסוף ימשיך לעבוד.
    """
    module = _import_root_module(name)
    stream = _LogStream(emit, mirror=sys.__stdout__)
    with _thread_stdout(stream):
        try:
            return int(module.main(list(argv)))
        finally:
            stream.flush()


def _default_refresh_runner(argv: list[str], emit: Callable[[str], None]) -> int:
    """ברירת המחדל: ``refresh.main`` — שקורא ל-``scraper.BraudeScraper``.

    הגורד הקיים הוא זה שאוכף שאין כתיבה לדיסק של דף שאינו מ-info.braude.ac.il
    ושאין נגיעה בסיסמאות. לכן קוראים לו, ולא כותבים גרידה חדשה כאן.
    """
    return _run_root_script("refresh", argv, emit)


def _default_reparse_runner(argv: list[str], emit: Callable[[str], None]) -> int:
    """ברירת המחדל: ``reparse.main`` — פענוח מחדש מ-data/raw, בלי רשת."""
    return _run_root_script("reparse", argv, emit)


def _scrape_worker(runner: Callable[[list[str], Callable[[str], None]], int], argv: list[str]) -> None:
    """ה-thread של הרענון. אף פעם לא זורק — מסיים תמיד עם exit_code."""
    exit_code = 1
    error = ""
    try:
        _scrape_emit("מתחיל רענון מהידיעון…", internal=True)
        _scrape_emit(
            "בעוד רגע ייפתח חלון דפדפן. כל ההזדהות מתבצעת בחלון הזה בלבד — "
            "האפליקציה אינה מבקשת, אינה רואה ואינה שומרת פרטי התחברות.",
            internal=True,
        )
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
@bp.post("/courses")
@_endpoint
def courses():
    """נתוני הקבוצות המלאים לקורסים שנבחרו, כולל טריות וקורסים שאינם נפתחים."""
    body = _read_body(required=True)
    codes = _clean_codes(body.get("codes"), field="codes")
    _assert_known_codes(codes)
    profile_student = _profile().get("student") or {}
    semester = str(body.get("semester") or profile_student.get("term") or "")
    year = str(body.get("year") or profile_student.get("academic_year") or "")

    built, problems, metas = _build_courses(codes, semester=semester, year=year)
    max_age = float(_config()["max_age_hours"])

    payload: list[dict[str, Any]] = []
    credits_total = 0.0
    for course in built:
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
        }
    )


# ------------------------------------------------------------------ solve
@bp.post("/solve")
@_endpoint
def solve():
    """הלב: פותר, סופר, ומחשב viability לכל קבוצה של כל קורס נבחר."""
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
    prefs = scheduler_mod.Preferences(
        target_days=target_days,
        preferred_lecturers=_clean_ranked(body.get("ranked")),
        blocked_windows=_clean_blocked(body.get("blocked")),
        earliest=earliest,
        latest=latest,
        weights=_clean_weights(body.get("weights")),
        forbid_friday=_as_bool(body.get("forbid_friday"), False),
    )

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

    base_common["schedules"] = [schedule_to_json(s, built) for s in found]
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

    ההתחברות מתבצעת בחלון דפדפן אמיתי שנפתח על המסך. האפליקציה לא מבקשת,
    לא רואה ולא שומרת פרטי התחברות — ואין בה שדה כזה בכלל.
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

    argv: list[str] = ["--headful"]
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

    runner = current_app.config.get("SCRAPE_RUNNER") or _default_refresh_runner

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
                "started_at": _now_iso(),
                "finished_at": None,
                "error": "",
                "codes": codes,
                "message": "הרענון התחיל. ייפתח חלון דפדפן להתחברות ידנית.",
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
            _scrape_worker(runner, argv)
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
            "note": (
                "ייפתח חלון דפדפן. יש להשלים בו את ההתחברות ידנית — "
                "האפליקציה אינה מבקשת ואינה שומרת פרטי התחברות."
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
            ``browser_profile_dir``, ``max_age_hours``, ``scrape_runner``,
            ``reparse_runner`` (הזרקה לבדיקות — כדי שלא ייפתח דפדפן).
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
    }
    overrides = dict(config or {})
    scrape_runner = overrides.pop("scrape_runner", None)
    reparse_runner = overrides.pop("reparse_runner", None)
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
