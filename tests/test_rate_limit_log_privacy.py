# -*- coding: utf-8 -*-
"""
שורת היומן של מגן הקצב אינה נושאת את הכתובת (‏src/web/api.py, ‏DEPLOY.md
"What the student sees").

הכתובת היא המפתח של הדלי ונשארת בזיכרון של המגן בלבד. היומן אומר שבקשה
נעצרה, באיזה נתיב ולכמה זמן — ולא של מי. גם ‏IPv6 נבדק: המפתח שלו הוא
ה-/64, וגם הוא אינו נרשם.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

#: כתובות מתוך ‏TEST-NET (‏RFC 5737 / 3849).
IPV4 = "203.0.113.77"
IPV6 = "2001:db8:5:6::9"


class Clock:
    """שעון שזז רק כשאומרים לו."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t


class CpuClock:
    """כל קריאה מוסיפה ``step`` — כל בקשה עולה בדיוק ``step`` שניות CPU."""

    def __init__(self, step: float) -> None:
        self.step = step
        self.t = 0.0

    def __call__(self) -> float:
        self.t += self.step
        return self.t


def _hosted():
    """אפליקציה מאורחת שבה בקשה אחת מרוקנת את הדלי, והזמן עומד."""
    from src.web.api import create_app  # noqa: PLC0415

    app = create_app({"allow_network": False, "mode": "hosted"})
    lim = app.extensions["slotwise_rate_limit"]
    lim.clock = Clock()
    lim.cpu_clock = CpuClock(61.0)
    return app


@pytest.mark.parametrize("addr,fragments", [
    pytest.param(IPV4, [IPV4, "203.0.113."], id="ipv4"),
    pytest.param(IPV6, [IPV6, "2001:db8:5:6", "/64"], id="ipv6"),
])
def test_the_throttle_line_does_not_name_the_address(caplog, addr, fragments):
    client = _hosted().test_client()
    env = {"REMOTE_ADDR": addr}
    assert client.get("/api/catalog/meta", environ_base=env).status_code == 200
    with caplog.at_level(logging.DEBUG):
        for _ in range(5):
            assert client.get("/api/catalog/meta", environ_base=env).status_code == 429

    lines = [r.getMessage() for r in caplog.records if "rate limit" in r.getMessage()]
    assert len(lines) == 1, f"שורה אחת בדקה לכל כתובת: {lines}"
    assert "GET /api/catalog/meta" in lines[0], lines[0]
    for fragment in fragments:
        assert fragment not in caplog.text, f"{fragment!r} ביומן: {caplog.text}"


def test_the_address_behind_the_proxy_is_not_logged_either(caplog):
    """דרך ``wsgi.build_app``: הכתובת ש-‏ProxyFix קיבל מה-Google Frontend."""
    import wsgi  # noqa: PLC0415

    app = wsgi.build_app()
    lim = app.extensions["slotwise_rate_limit"]
    lim.clock = Clock()
    lim.cpu_clock = CpuClock(61.0)
    client = app.test_client()
    headers = {"X-Forwarded-For": IPV4}
    client.post("/api/solve", json={"codes": ["11069"], "semester": "א"}, headers=headers)
    with caplog.at_level(logging.DEBUG):
        res = client.post("/api/solve", json={"codes": ["11069"], "semester": "א"}, headers=headers)
    assert res.status_code == 429
    assert "rate limit: a client was throttled on POST /api/solve" in caplog.text, caplog.text
    assert IPV4 not in caplog.text, caplog.text
