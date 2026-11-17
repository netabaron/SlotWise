# -*- coding: utf-8 -*-
"""
syllabus.py — כתובות הסילבוס, ומה הבנייה הלילית יודעת עליהן (docs/SPEC_LINKS.md, Feature 2).

מה ידוע (docs/GROUND_TRUTH.md §10)
-----------------------------------
הסילבוס הוא קובץ PDF סטטי, בלי התחברות, בלי עוגייה ובלי POST::

    https://info.braude.ac.il/info/<שנה לועזית>/<קוד הקורס, מרופד באפסים ל-7 ספרות>.pdf

בלי הריפוד זה 404. קורס בלי סילבוס מחזיר 404 עם דף ‏IIS באנגלית — וכמעט
תמיד פירוש הדבר "עוד לא הועלה", לא "אין ולא יהיה".

**אין כאן רשת, בכוונה.** השרת המתארח אסור לו לפנות לבראודה בזמן בקשה
(``wsgi.py`` נועל ``allow_network=False``; ‏DEPLOY.md). מי שבודק אילו קבצים
קיימים הוא ``scripts/check_syllabi.py``, בבנייה הלילית ובקצב שלה, והוא כותב את
התשובות ל-``data/catalog/syllabi.json``. המודול הזה רק **קורא** את הקובץ.
‏``tests/test_syllabus_endpoint.py`` בודק שאין כאן ייבוא של לקוח רשת.

הקובץ::

    {"schema": "slotwise/syllabi", "version": 1, "updated_at": "...",
     "years": {"2027": {"61757": {"status": "exists",  "checked": "2026-11-17"},
                        "11092": {"status": "missing", "checked": "2026-11-17"}},
               "2026": {...}}}

קוד שאינו בקובץ (או קובץ חסר/פגום) הוא ``UNCHECKED`` — לא "אין סילבוס".
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOG = logging.getLogger("slotwise.syllabus")

#: בסיס הכתובת של קובצי הסילבוס. המקום היחיד בצד השרת שהוא כתוב בו.
SYLLABUS_BASE_URL = "https://info.braude.ac.il/info/"

#: דף הקורס בידיעון — הכפתור הראשי בדף "עוד לא הועלה". קוד לא מרופד.
YEDION_COURSE_URL = (
    "https://info.braude.ac.il/yedion/fireflyweb.aspx?prgname=S_LOOK_FOR_NOSE&arguments=-N"
)

#: שם הקובץ, בתיקיית הקטלוג שהשרת כבר מגיש (``SLOTWISE_CATALOG_DIR``).
SYLLABI_FILENAME = "syllabi.json"
SCHEMA = "slotwise/syllabi"
VERSION = 1

#: קוד קורס: ספרות ASCII בלבד, 4 עד 7.
CODE_RE = re.compile(r"[0-9]{4,7}")
#: שנה לועזית: ארבע ספרות.
YEAR_RE = re.compile(r"[0-9]{4}")

EXISTS = "exists"
MISSING = "missing"
UNCHECKED = "unchecked"
#: שני המצבים שהבדיקה רושמת. ‏UNCHECKED הוא היעדר רשומה, לא ערך בקובץ.
RECORDED = (EXISTS, MISSING)


def valid_code(code: object) -> bool:
    """‏True רק לקוד של 4–7 ספרות ASCII (‏``fullmatch``, בלי רווחים)."""
    return isinstance(code, str) and CODE_RE.fullmatch(code) is not None


def valid_year(year: object) -> bool:
    return isinstance(year, str) and YEAR_RE.fullmatch(year) is not None


def previous_year(year: str) -> str:
    """‏``"2027"`` → ``"2026"``; ``""`` כשהקלט אינו שנה."""
    return str(int(year) - 1) if valid_year(year) else ""


def pdf_url(year: str, code: str) -> str:
    """‏``…/info/2027/0061757.pdf`` — הקוד מרופד באפסים ל-7 ספרות."""
    return f"{SYLLABUS_BASE_URL}{year}/{str(code).zfill(7)}.pdf"


def course_page_url(code: str) -> str:
    """דף הקורס בידיעון, עם הקוד **בלי** ריפוד — כמו שהידיעון מקבל אותו."""
    return YEDION_COURSE_URL + str(code)


# ---------------------------------------------------------------------------
# קריאת syllabi.json
# ---------------------------------------------------------------------------
def syllabi_path() -> Path:
    """‏``<תיקיית הקטלוג>/syllabi.json`` — אותה תיקייה ש-``shipped_catalog`` מגיש.

    נקרא בכל פעם (לא נקבע בזמן ייבוא), כדי ש-``SLOTWISE_CATALOG_DIR`` ובדיקות
    שמחליפות את התיקייה יחולו גם כאן.
    """
    try:
        import shipped_catalog  # type: ignore

        return Path(shipped_catalog.CATALOG_DIR) / SYLLABI_FILENAME
    except Exception:  # noqa: BLE001 - בלי מודול הקטלוג: התיקייה הרגילה
        return Path(__file__).resolve().parent.parent / "data" / "catalog" / SYLLABI_FILENAME


_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"key": None, "data": {}}


def _empty() -> dict[str, Any]:
    return {"schema": SCHEMA, "version": VERSION, "years": {}}


def parse(text: str) -> dict[str, Any]:
    """תוכן הקובץ → מילון תקין, תמיד. מה שאינו בצורה הצפויה פשוט נשמט."""
    try:
        raw = json.loads(text)
    except ValueError:
        return _empty()
    out = _empty()
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return out
    out["updated_at"] = str(raw.get("updated_at") or "")
    years = raw.get("years")
    if not isinstance(years, dict):
        return out
    for year, entries in years.items():
        if not valid_year(str(year)) or not isinstance(entries, dict):
            continue
        clean: dict[str, dict[str, str]] = {}
        for code, rec in entries.items():
            if not valid_code(str(code)) or not isinstance(rec, dict):
                continue
            status = rec.get("status")
            if status in RECORDED:
                clean[str(code)] = {"status": status, "checked": str(rec.get("checked") or "")}
        out["years"][str(year)] = clean
    return out


def load(path: Path | None = None) -> dict[str, Any]:
    """הקובץ, מנותח; נטען מחדש רק כשהוא משתנה (‏mtime/גודל). לעולם לא זורק.

    קובץ חסר — למשל לפני המילוי הראשון, או קטלוג בדיקה — הוא מילון ריק,
    ואז כל קוד הוא ``UNCHECKED``.
    """
    target = Path(path) if path is not None else syllabi_path()
    try:
        st = target.stat()
        key = (str(target), st.st_mtime_ns, st.st_size)
    except OSError:
        return _empty()
    with _LOCK:
        if _CACHE["key"] == key:
            return _CACHE["data"]
    try:
        data = parse(target.read_text(encoding="utf-8"))
    except OSError:
        LOG.exception("קריאת %s נכשלה", SYLLABI_FILENAME)
        return _empty()
    with _LOCK:
        _CACHE["key"], _CACHE["data"] = key, data
    return data


@dataclass(frozen=True)
class Status:
    status: str      # EXISTS / MISSING / UNCHECKED
    checked: str     # ‏"2026-11-17", או "" כשלא נבדק


def status(year: str, code: str, data: dict[str, Any] | None = None) -> Status:
    """מה ידוע על הסילבוס של ``code`` בשנה ``year``."""
    source = load() if data is None else data
    rec = ((source.get("years") or {}).get(str(year)) or {}).get(str(code))
    if isinstance(rec, dict) and rec.get("status") in RECORDED:
        return Status(rec["status"], str(rec.get("checked") or ""))
    return Status(UNCHECKED, "")
