# -*- coding: utf-8 -*-
"""
מגן הקצב לכל IP (‏src/rate_limit.py, ‏DEPLOY.md "Rate limiting").

התקציב הוא שניות CPU ולא בקשות, הוא לכל worker, ו-IPv6 נספר לפי /64.
הבדיקות כאן מחליפות את השעונים של המגן (``clock``, ``cpu_clock``, ``now``)
כדי שהמספרים יהיו מדויקים ולא תלויים במהירות המכונה.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import rate_limit  # noqa: E402
from rate_limit import RateLimiter  # noqa: E402

#: כתובות מתוך ‏TEST-NET (‏RFC 5737 / 3849) — לא ניתובות, לא של אף אחד.
CLIENT = "203.0.113.9"
OTHER = "198.51.100.20"
FORGED = "198.51.100.7"

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))


class Clock:
    """שעון שזז רק כשאומרים לו."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t


def limiter(**kwargs) -> tuple[RateLimiter, Clock]:
    lim = RateLimiter(**kwargs)
    clock = Clock()
    lim.clock = clock
    return lim, clock


# ==========================================================================
# 1. הדלי
# ==========================================================================
def test_a_new_address_is_admitted():
    lim, _ = limiter()
    assert lim.check(CLIENT) is None


def test_admitted_until_the_budget_is_spent_then_rejected():
    lim, _ = limiter(cpu_per_min=15, burst_cpu=60)
    lim.charge(CLIENT, 59.0)
    assert lim.check(CLIENT) is None, "נשארה שנייה אחת — עדיין בפנים"
    lim.charge(CLIENT, 2.0)
    assert lim.check(CLIENT) is not None


def test_retry_after_is_the_time_until_the_bucket_is_back():
    """‏-1 שנייה, מילוי של 0.25 לשנייה, ועוד מינימום החיוב: ‏ceil(1.01/0.25) = 5."""
    lim, _ = limiter(cpu_per_min=15, burst_cpu=60)
    lim.charge(CLIENT, 61.0)
    assert lim.check(CLIENT) == 5


def test_the_bucket_refills_with_time():
    lim, clock = limiter(cpu_per_min=15, burst_cpu=60)
    lim.charge(CLIENT, 61.0)
    assert lim.check(CLIENT) is not None
    clock.t += 5
    assert lim.check(CLIENT) is None


def test_the_bucket_never_holds_more_than_the_burst():
    lim, clock = limiter(cpu_per_min=15, burst_cpu=60)
    lim.charge(CLIENT, 0.0)
    clock.t += 24 * 3600
    lim.charge(CLIENT, 60.0)
    assert lim.check(CLIENT) is not None, "יום שלם בלי בקשות לא צובר יותר מ-60"


def test_every_request_costs_at_least_the_minimum():
    """הצפה של בקשות זולות נעצרת גם היא: ‏60 / 0.01 = כ-6000 בקשות.

    ‏לא על הגבול המדויק: 6000 חיסורים של 0.01 משאירים שארית נקודה צפה.
    """
    lim, _ = limiter(cpu_per_min=15, burst_cpu=60)
    for _ in range(5990):
        lim.charge(CLIENT, 0.0)
    assert lim.check(CLIENT) is None
    for _ in range(20):
        lim.charge(CLIENT, 0.0)
    assert lim.check(CLIENT) is not None


def test_retry_after_is_clamped():
    lim, _ = limiter(cpu_per_min=15, burst_cpu=60)
    lim.charge(CLIENT, 10_000.0)
    assert lim.check(CLIENT) == rate_limit.RETRY_AFTER_MAX_S
    fast, _ = limiter(cpu_per_min=6000, burst_cpu=1)
    fast.charge(CLIENT, 1.0)
    assert fast.check(CLIENT) == rate_limit.RETRY_AFTER_MIN_S


def test_addresses_do_not_share_a_bucket():
    lim, _ = limiter()
    lim.charge(CLIENT, 1000.0)
    assert lim.check(CLIENT) is not None
    assert lim.check(OTHER) is None


# ==========================================================================
# 2. המפתח
# ==========================================================================
def test_ipv4_is_its_own_key():
    lim, _ = limiter()
    assert lim.key_for(CLIENT) == CLIENT


def test_ipv6_is_keyed_on_the_64():
    lim, _ = limiter()
    a = lim.key_for("2001:db8:1:2::1")
    b = lim.key_for("2001:db8:1:2:ffff:ffff:ffff:ffff")
    c = lim.key_for("2001:db8:1:3::1")
    assert a == b == "2001:db8:1:2::/64"
    assert c != a


def test_ipv4_mapped_ipv6_is_the_ipv4_address():
    lim, _ = limiter()
    assert lim.key_for("::ffff:203.0.113.9") == CLIENT


def test_exempt_networks_have_no_key():
    nets = (ipaddress.ip_network("203.0.113.0/24"), ipaddress.ip_network("2001:db8:aa::/48"))
    lim, _ = limiter(exempt=nets)
    assert lim.key_for(CLIENT) is None
    assert lim.key_for("2001:db8:aa:1::5") is None
    assert lim.key_for(OTHER) == OTHER


def test_an_unparseable_address_still_gets_a_bucket():
    """לא פטור: כתובת שאינה מתפרשת היא לא סיבה לדלג על המגן."""
    lim, _ = limiter()
    assert lim.key_for(None) == rate_limit.UNKNOWN_KEY
    assert lim.key_for("not-an-ip") == rate_limit.UNKNOWN_KEY


# ==========================================================================
# 3. זיכרון ויומן
# ==========================================================================
def test_buckets_that_refilled_are_swept():
    lim, clock = limiter(cpu_per_min=15, burst_cpu=60)
    lim.charge(CLIENT, 1.0)
    lim.charge(OTHER, 1000.0)
    clock.t += 10
    lim._sweep(clock())  # noqa: SLF001 - זה בדיוק מה שנבדק
    assert len(lim) == 1, "הדלי שהתמלא נמחק, זה שבחוב נשאר"


def test_a_flood_of_addresses_is_capped():
    lim, _ = limiter(max_entries=100)
    for i in range(500):
        addr = f"10.0.{i // 256}.{i % 256}"
        lim.charge(addr, 1000.0)
        lim.check(addr)
    assert len(lim) <= 101


def test_one_log_line_per_address_per_minute():
    lim, clock = limiter()
    lim.charge(CLIENT, 1000.0)
    assert lim.should_log(CLIENT) is True
    assert lim.should_log(CLIENT) is False
    clock.t += rate_limit.LOG_EVERY_S
    assert lim.should_log(CLIENT) is True


# ==========================================================================
# 4. כבוי עד שעה
# ==========================================================================
def test_off_until_a_future_time_then_back_by_itself():
    now = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
    lim = RateLimiter(off_until=now + timedelta(hours=2))
    lim.now = lambda: now
    assert lim.active() is False
    assert lim.describe() == "off until 2026-11-01T03:00Z"
    lim.now = lambda: now + timedelta(hours=2)
    assert lim.active() is True
    assert lim.describe().startswith("on:")


# ==========================================================================
# 5. פענוח הסביבה — ערך פגום זורק
# ==========================================================================
def test_defaults_with_no_environment():
    s = rate_limit.settings_from_env({})
    assert s == {
        "rate_limit_cpu_per_min": 15.0,
        "rate_limit_burst_cpu": 60.0,
        "rate_limit_exempt_cidrs": (),
        "rate_limit_off_until": None,
    }


def test_values_are_parsed():
    s = rate_limit.settings_from_env({
        rate_limit.ENV_CPU_PER_MIN: "20",
        rate_limit.ENV_BURST_CPU: " 90.5 ",
        rate_limit.ENV_EXEMPT_CIDRS: "203.0.113.0/24, 198.51.100.7 2001:db8::/48",
        rate_limit.ENV_OFF_UNTIL: "2026-11-01T03:00Z",
    })
    assert s["rate_limit_cpu_per_min"] == 20.0
    assert s["rate_limit_burst_cpu"] == 90.5
    assert [str(n) for n in s["rate_limit_exempt_cidrs"]] == [
        "203.0.113.0/24", "198.51.100.7/32", "2001:db8::/48",
    ]
    assert s["rate_limit_off_until"] == datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("name,value", [
    (rate_limit.ENV_CPU_PER_MIN, "fifteen"),
    (rate_limit.ENV_CPU_PER_MIN, "0"),
    (rate_limit.ENV_CPU_PER_MIN, "-5"),
    (rate_limit.ENV_BURST_CPU, "nan"),
    (rate_limit.ENV_BURST_CPU, "inf"),
    (rate_limit.ENV_EXEMPT_CIDRS, "203.0.113.0/33"),
    (rate_limit.ENV_EXEMPT_CIDRS, "campus"),
    (rate_limit.ENV_OFF_UNTIL, "tomorrow"),
    (rate_limit.ENV_OFF_UNTIL, "2026-11-01T03:00"),  # בלי אזור זמן
])
def test_a_malformed_value_raises(name, value):
    with pytest.raises(ValueError, match=name):
        rate_limit.settings_from_env({name: value})


def test_create_app_refuses_to_start_with_a_malformed_value(monkeypatch):
    from src.web.api import create_app  # noqa: PLC0415

    monkeypatch.setenv(rate_limit.ENV_CPU_PER_MIN, "lots")
    with pytest.raises(ValueError, match=rate_limit.ENV_CPU_PER_MIN):
        create_app({"allow_network": False, "mode": "hosted"})


# ==========================================================================
# 6. דרך האפליקציה
# ==========================================================================
class CpuClock:
    """כל קריאה מוסיפה ``step`` — כלומר כל בקשה "עולה" בדיוק ``step``."""

    def __init__(self, step: float) -> None:
        self.step = step
        self.t = 0.0

    def __call__(self) -> float:
        self.t += self.step
        return self.t


def _hosted(config: dict | None = None, *, cost: float = 61.0):
    """אפליקציה מאורחת שבה כל בקשה עולה ``cost`` שניות CPU, והזמן עומד."""
    from src.web.api import create_app  # noqa: PLC0415

    app = create_app({"allow_network": False, "mode": "hosted", **(config or {})})
    lim = app.extensions["slotwise_rate_limit"]
    lim.clock = Clock()
    # שתי קריאות לבקשה (התחלה וסוף); ההפרש ביניהן הוא צעד אחד.
    lim.cpu_clock = CpuClock(cost)
    return app, lim


def test_the_local_app_has_no_limiter():
    from src.web.api import create_app  # noqa: PLC0415

    app = create_app({"allow_network": False})
    assert app.extensions["slotwise_rate_limit"] is None


def test_the_hosted_app_has_one_on_extensions():
    app, lim = _hosted()
    assert isinstance(lim, RateLimiter)


def test_a_spent_budget_gets_a_429_with_retry_after():
    app, _ = _hosted()
    client = app.test_client()
    first = client.get("/api/catalog/meta")
    assert first.status_code == 200
    res = client.get("/api/catalog/meta")
    assert res.status_code == 429
    data = res.get_json()
    assert data["ok"] is False
    assert data["reason"] == "rate_limited"
    assert isinstance(data["retry_after"], int) and data["retry_after"] >= 1
    assert res.headers["Retry-After"] == str(data["retry_after"])
    assert res.headers["Cache-Control"] == "no-store"
    assert data["error"] and "Error" not in data["error"]
    assert "worker" in data["detail"]


def test_post_endpoints_are_limited_too():
    app, _ = _hosted()
    client = app.test_client()
    body = {"codes": ["11069"], "semester": "א"}
    client.post("/api/courses", json=body)
    assert client.post("/api/solve", json=body).status_code == 429


def test_a_failed_request_is_still_charged():
    """‏400 על JSON פגום עלה זמן כמו כל בקשה אחרת."""
    app, _ = _hosted()
    client = app.test_client()
    bad = client.post("/api/solve", data=b"{not json", content_type="application/json")
    assert bad.status_code == 400
    assert client.get("/api/catalog/meta").status_code == 429


@pytest.mark.parametrize("path", ["/healthz", "/", "/static/app.js"])
def test_the_page_static_files_and_healthz_are_never_limited(path):
    app, _ = _hosted()
    client = app.test_client()
    client.get("/api/catalog/meta")
    assert client.get("/api/catalog/meta").status_code == 429
    for _ in range(3):
        assert client.get(path).status_code in (200, 503), path


def test_an_exempt_network_is_never_limited():
    app, _ = _hosted({"rate_limit_exempt_cidrs": (ipaddress.ip_network("203.0.113.0/24"),)})
    client = app.test_client()
    for _ in range(5):
        res = client.get("/api/catalog/meta", environ_base={"REMOTE_ADDR": CLIENT})
        assert res.status_code == 200


def test_off_until_switches_it_off_and_it_comes_back():
    now = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)
    app, lim = _hosted({"rate_limit_off_until": now + timedelta(hours=2)})
    lim.now = lambda: now
    client = app.test_client()
    for _ in range(5):
        assert client.get("/api/catalog/meta").status_code == 200
    lim.now = lambda: now + timedelta(hours=3)
    client.get("/api/catalog/meta")
    assert client.get("/api/catalog/meta").status_code == 429


def test_a_throttled_address_is_logged_once_a_minute(caplog):
    app, _ = _hosted()
    client = app.test_client()
    client.get("/api/catalog/meta")
    with caplog.at_level(logging.WARNING, logger="slotwise.web"):
        for _ in range(5):
            client.get("/api/catalog/meta")
    lines = [r for r in caplog.records if "rate limit" in r.getMessage()]
    assert len(lines) == 1, [r.getMessage() for r in lines]
    assert "127.0.0.1" in lines[0].getMessage()


# ==========================================================================
# 7. דרך wsgi.py — ‏ProxyFix קובע את הכתובת
# ==========================================================================
@pytest.fixture()
def hosted_wsgi():
    """אפליקציה חדשה דרך ``wsgi.build_app`` — בדיוק החיווט של הייצור."""
    import wsgi  # noqa: PLC0415

    app = wsgi.build_app()
    lim = app.extensions["slotwise_rate_limit"]
    lim.clock = Clock()
    lim.cpu_clock = CpuClock(61.0)
    return app


def test_the_bucket_is_the_address_proxyfix_believed(hosted_wsgi):
    """‏``זיוף, אמיתי`` נספר על האמיתי — הכתובת הימנית, זו שה-Google Frontend הוסיף."""
    client = hosted_wsgi.test_client()
    client.get("/api/catalog/meta", headers={"X-Forwarded-For": f"{FORGED}, {CLIENT}"})
    assert client.get(
        "/api/catalog/meta", headers={"X-Forwarded-For": CLIENT}
    ).status_code == 429, "הבקשה המזויפת לא נספרה על הכתובת האמיתית"
    assert client.get(
        "/api/catalog/meta", headers={"X-Forwarded-For": FORGED}
    ).status_code == 200, "הכתובת המזויפת קיבלה את החיוב"


def test_a_forged_left_entry_does_not_dodge_the_limit(hosted_wsgi):
    client = hosted_wsgi.test_client()
    client.get("/api/catalog/meta", headers={"X-Forwarded-For": CLIENT})
    res = client.get("/api/catalog/meta", headers={"X-Forwarded-For": f"{OTHER}, {CLIENT}"})
    assert res.status_code == 429


def test_wsgi_says_which_limit_it_runs(capsys):
    import wsgi  # noqa: PLC0415

    capsys.readouterr()
    wsgi.build_app()
    out = capsys.readouterr().out
    assert "[slotwise] rate limit: on: 15 CPU-s/min per IP per worker, burst 60 CPU-s, exempt none" in out


# ==========================================================================
# 8. הנוסח
# ==========================================================================
def test_the_429_server_message_is_hebrew():
    from src.web.api import _http_message_he  # noqa: PLC0415

    assert _http_message_he(429) != _http_message_he(999), "אין ל-429 נוסח משלו"


@pytest.mark.parametrize("path", [
    ("app", "errors", "rateLimited"),
    ("app", "errors", "rateLimitedManual"),
    ("app", "errors", "serverBusy"),
    ("app", "banners", "solveRateLimited"),
])
def test_the_client_copy_exists_and_leaks_nothing_technical(path):
    node = STRINGS
    for part in path:
        node = node[part]
    assert isinstance(node, str) and node.strip(), path
    for leak in ("429", "Error", "rate", "worker", "Retry-After", "undefined"):
        assert leak not in node, f"{'.'.join(path)}: {leak}"


def test_the_messages_say_the_selections_are_safe():
    errs = STRINGS["app"]["errors"]
    for key in ("rateLimited", "rateLimitedManual", "serverBusy"):
        assert "שמורות" in errs[key], key
