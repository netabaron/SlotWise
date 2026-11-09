# -*- coding: utf-8 -*-
"""
שורת הגישה של gunicorn אינה רושמת מי ביקש (‏gunicorn.conf.py, ‏DEPLOY.md §11).

‏``access_log_format`` נבדק מול רשימת היתר: שיטה, נתיב בלי query string,
סטטוס, גודל וזמן. אסורים ``%(h)s`` (כתובת ה-IP אחרי ‏ProxyFix), ‏``%(a)s``
(‏User-Agent), ‏``%(r)s`` ו-``%(q)s`` (ה-query string, שבו המסלול, ההתמחות
ומילות החיפוש), ‏``%(f)s`` (‏Referer), וכל כותרת או משתנה סביבה
(``%({...}i)s``, ‏``%({...}e)s``) — גם שדה שעוד לא נוסף.

הבדיקה האחרונה מרנדרת שורה אמיתית דרך ``gunicorn.glogging`` כשהוא מותקן
(‏CI והתמונה, לינוקס בלבד). ב-Windows הוא אינו נטען, והיא מדלגת.
"""

from __future__ import annotations

import re
import runpy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
FORMAT = runpy.run_path(str(ROOT / "gunicorn.conf.py"))["access_log_format"]

#: השדות המותרים. כל השאר אסור.
ALLOWED = {
    "m",  # שיטה
    "U",  # נתיב, בלי query string
    "s",  # סטטוס
    "b", "B",  # גודל התשובה
    "L", "T", "D", "M",  # זמן התשובה
    "t",  # תאריך
    "H",  # פרוטוקול
    "p",  # pid
}

#: בקשת GET מציאותית מהדף, מאחורי ה-Google Frontend. כתובת מ-TEST-NET.
CLIENT_IP = "203.0.113.45"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AuditStudentA"
QUERY = (
    "program=%D7%94%D7%A0%D7%93%D7%A1%D7%AA%20%D7%AA%D7%95%D7%9B%D7%A0%D7%94"
    "&intake=&specialization=&route=&q=algorithms"
)
REFERER = "https://slotwise.co.il/?from=whatsapp"


def _keys(fmt: str) -> list[str]:
    return re.findall(r"%\(([^)]*)\)", fmt)


def test_the_format_uses_only_allowed_atoms():
    used = _keys(FORMAT)
    assert used, FORMAT
    banned = [k for k in used if k not in ALLOWED]
    assert not banned, (
        f"access_log_format רושם {banned} — כתובת, דפדפן, query string או"
        f" כותרת, כלומר מי ביקש: {FORMAT!r}"
    )


def test_the_line_keeps_what_operations_need():
    """נתיב, סטטוס וזמן תשובה: בשבילם השורה קיימת (‏gunicorn.conf.py)."""
    assert {"m", "U", "s", "L"} <= set(_keys(FORMAT)), FORMAT


def test_gunicorns_own_atoms_render_no_address_agent_or_query():
    """השורה כפי ש-gunicorn 23 מרכיב אותה, מבקשה שנושאת את כל המידע הרגיש."""
    glogging = pytest.importorskip(
        "gunicorn.glogging", reason="gunicorn נטען רק בלינוקס (‏CI והתמונה)"
    )
    from gunicorn.config import Config  # noqa: PLC0415

    logger = glogging.Logger(Config())
    environ = {
        "REQUEST_METHOD": "GET",
        "RAW_URI": f"/api/semester/5/courses?{QUERY}",
        "PATH_INFO": "/api/semester/5/courses",
        "QUERY_STRING": QUERY,
        "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": CLIENT_IP,  # כפי ש-ProxyFix משאיר אותו
        "HTTP_USER_AGENT": USER_AGENT,
        "HTTP_REFERER": REFERER,
        "HTTP_X_FORWARDED_FOR": CLIENT_IP,
    }
    req = SimpleNamespace(headers=[
        ("USER-AGENT", USER_AGENT), ("REFERER", REFERER), ("X-FORWARDED-FOR", CLIENT_IP),
    ])
    resp = SimpleNamespace(status="200 OK", sent=4225, headers=[("Content-Type", "application/json")])
    atoms = logger.atoms(resp, req, environ, timedelta(microseconds=250000))
    line = FORMAT % glogging.SafeAtoms(atoms)

    for secret in (CLIENT_IP, USER_AGENT, "AuditStudentA", "program=", "algorithms", "whatsapp"):
        assert secret not in line, f"{secret!r} בשורת הגישה: {line}"
    assert "GET /api/semester/5/courses" in line, line
    assert " 200 4225 0.250000s" in line, line
