# -*- coding: utf-8 -*-
"""
מגן הקצב שוכח כתובת דקות אחרי הבקשה האחרונה שלה (‏src/rate_limit.py,
‏HOSTING_NOTES.md §4.1).

דלי שהתמלא שווה לדלי שאינו קיים, ולכן הוא נמחק בניקוי. עד 2026-11-09 הניקוי
רץ רק כל ‏``SWEEP_EVERY`` (‏1,000) בדיקות, ובתנועה דלה כתובת נשארה בזיכרון
ימים. עכשיו הוא רץ גם בבדיקה הראשונה שאחרי ‏``SWEEP_INTERVAL_S`` שניות.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import rate_limit  # noqa: E402
from rate_limit import RateLimiter  # noqa: E402

#: כתובות מתוך ‏TEST-NET (‏RFC 5737).
CLIENT = "203.0.113.9"
OTHER = "198.51.100.20"


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


def limiter() -> tuple[RateLimiter, Clock]:
    lim = RateLimiter(cpu_per_min=15, burst_cpu=60)
    clock = Clock()
    lim.clock = clock
    return lim, clock


def test_the_interval_is_a_minute_and_far_below_the_check_count():
    assert rate_limit.SWEEP_INTERVAL_S == 60.0
    assert rate_limit.SWEEP_EVERY == 1_000


def test_a_refilled_bucket_is_forgotten_a_minute_later():
    lim, clock = limiter()
    lim.check(CLIENT)
    lim.charge(CLIENT, 1.0)  # מתמלא תוך 4 שניות
    assert len(lim) == 1
    clock.t += rate_limit.SWEEP_INTERVAL_S
    lim.check(OTHER)  # בדיקה אחת בלבד — רחוק מ-SWEEP_EVERY
    assert len(lim) == 0, "הכתובת נשארה בזיכרון אחרי שהדלי התמלא ועברה דקה"


def test_not_before_the_interval():
    lim, clock = limiter()
    lim.check(CLIENT)
    lim.charge(CLIENT, 1.0)
    clock.t += rate_limit.SWEEP_INTERVAL_S - 1
    lim.check(OTHER)
    assert len(lim) == 1


def test_a_bucket_still_in_debt_is_kept():
    """המגן לא שוכח את מי שעוד חייב — אחרת מחיקה הייתה עוקפת את התקרה."""
    lim, clock = limiter()
    lim.check(CLIENT)
    lim.charge(CLIENT, 1000.0)
    clock.t += rate_limit.SWEEP_INTERVAL_S
    lim.check(OTHER)
    assert len(lim) == 1
    assert lim.check(CLIENT) is not None, "הכתובת שבחוב קיבלה דלי מלא"


def test_through_the_hosted_app():
    from src.web.api import create_app  # noqa: PLC0415

    app = create_app({"allow_network": False, "mode": "hosted"})
    lim = app.extensions["slotwise_rate_limit"]
    clock = Clock()
    lim.clock = clock
    lim.cpu_clock = CpuClock(0.5)
    client = app.test_client()

    assert client.get("/api/catalog/meta", environ_base={"REMOTE_ADDR": CLIENT}).status_code == 200
    assert len(lim) == 1
    clock.t += rate_limit.SWEEP_INTERVAL_S
    assert client.get("/api/catalog/meta", environ_base={"REMOTE_ADDR": OTHER}).status_code == 200
    assert len(lim) == 1, "רק הכתובת של הבקשה האחרונה צריכה להישאר"
