# -*- coding: utf-8 -*-
"""
‏ProxyFix: לראות את הסטודנט/ית, לא את ה-proxy.

השרשרת באירוח היא ‏client → Cloudflare → Railway → gunicorn. בלי
‏ProxyFix, ‏``request.remote_addr`` הוא הכתובת הפנימית של ‏Railway בכל בקשה,
ו-``request.scheme`` הוא ‏http אף שהסטודנט/ית על ‏https. התוצאה: יומן גישה
שבו לכולם אותה כתובת, ומגן קצב עתידי שיחנוק את ה-proxy במקום את מי שמציף.

**למה בדיוק hop אחד.** כל יחידת אמון אומרת "עוד קפיצה אחת שאני שולט/ת בה
מוסיפה ערך שאפשר להאמין לו". אמון בשתיים היה מאפשר ללקוח לזייף את הערך
השמאלי ב-``X-Forwarded-For`` ולהיראות ככל כתובת שיבחר.

**ולמה זה ב-``wsgi.py`` ולא ב-``create_app``.** ‏``webapp.py`` המקומי נקשר
ל-127.0.0.1 בלי שום proxy לפניו. מתן אמון בכותרות האלה שם פירושו להאמין
לכל תהליך מקומי שיחליט לשלוח אותן.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

#: כתובות מתוך ‏TEST-NET-3 (‏RFC 5737) — לא ניתובות, לא של אף אחד.
REAL_CLIENT = "203.0.113.9"
FORGED = "198.51.100.7"


@pytest.fixture(scope="module")
def probe():
    """‏(client, seen) — ‏seen מתעדכן בכל בקשה עם מה שהאפליקציה ראתה."""
    import wsgi  # noqa: PLC0415 — ייבוא מאוחר: הוא בונה את האפליקציה

    from flask import request  # noqa: PLC0415

    seen: dict[str, str] = {}
    app = wsgi.app

    @app.route("/__proxy_probe")
    def _probe():  # pragma: no cover - נקרא דרך הלקוח
        seen.update(ip=request.remote_addr or "", scheme=request.scheme)
        return "ok"

    return app.test_client(), seen


def test_the_hosted_app_is_wrapped_in_proxyfix():
    import wsgi  # noqa: PLC0415

    assert type(wsgi.app.wsgi_app).__name__ == "ProxyFix"


def test_the_local_launcher_is_not_wrapped():
    """‏webapp.py נקשר ל-127.0.0.1 ואין לפניו proxy — אסור לו להאמין לכותרות."""
    source = (ROOT / "webapp.py").read_text(encoding="utf-8")
    assert "ProxyFix" not in source, "‏webapp.py המקומי עטוף ב-ProxyFix"


def test_without_headers_nothing_changes(probe):
    client, seen = probe
    client.get("/__proxy_probe")
    assert seen["scheme"] == "http"


def test_one_hop_gives_the_real_client_ip(probe):
    client, seen = probe
    client.get("/__proxy_probe", headers={"X-Forwarded-For": REAL_CLIENT})
    assert seen["ip"] == REAL_CLIENT


def test_one_hop_gives_https(probe):
    """בלי זה כל הקישורים והיומנים מתארים ‏http לסטודנט/ית שגולש/ת ב-https."""
    client, seen = probe
    client.get("/__proxy_probe", headers={"X-Forwarded-Proto": "https"})
    assert seen["scheme"] == "https"


def test_a_client_cannot_forge_an_extra_hop(probe):
    """הבדיקה שמצדיקה את המספר 1.

    ‏לקוח ששולח ``X-Forwarded-For: <זיוף>, <אמיתי>`` מקווה שניקח את הערך
    השמאלי. ‏x_for=1 לוקח את הימני — זה שה-proxy שאנחנו סומכים עליו הוסיף.
    """
    client, seen = probe
    client.get("/__proxy_probe",
               headers={"X-Forwarded-For": f"{FORGED}, {REAL_CLIENT}"})
    assert seen["ip"] == REAL_CLIENT, (
        f"נלקחה כתובת מזויפת: {seen['ip']} (ציפיתי ל-{REAL_CLIENT})"
    )
    assert seen["ip"] != FORGED


def test_host_and_prefix_are_not_trusted():
    """‏x_host=0 / x_prefix=0 בכוונה.

    ‏שום דבר באפליקציה אינו בונה כתובת מוחלטת מה-host של הבקשה (אומת
    ‏2026-09-18: אין ``url_for(_external=True)``, אין ``request.host``, אין
    ``SERVER_NAME``), ולכן אין מה להרוויח מאמון ב-X-Forwarded-Host — ויש מה
    להפסיד: הרעלת מטמון דרך כותרת ‏Host מזויפת.
    """
    import wsgi  # noqa: PLC0415

    fix = wsgi.app.wsgi_app
    assert fix.x_for == 1
    assert fix.x_proto == 1
    assert fix.x_host == 0
    assert fix.x_prefix == 0


def test_nothing_builds_absolute_urls_from_the_request_host():
    """מה שמאפשר ל-x_host=0 להיות בטוח. אם זה ישתנה, הבדיקה תיפול."""
    suspects = ("_external=True", "request.host", "request.url_root",
                "request.base_url", "SERVER_NAME")
    for name in ("src/web/api.py", "src/web/static/app.js"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for suspect in suspects:
            assert suspect not in text, f"{name} משתמש ב-{suspect}"
