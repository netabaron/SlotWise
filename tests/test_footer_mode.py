"""שורת התחתית לפי המצב: ‏webapp.py מקומי מול ‏wsgi.py מאורח.

המשפט המקומי אומר "שרת מקומי על 127.0.0.1 בלבד" — אמת במחשב של
הסטודנט/ית, שקר בשרת ציבורי. לכן המצב נחשף ב-‏``/api/bootstrap`` (‏``mode``)
והממשק בוחר את השורה לפיו. בדיקה אחת לכל מצב בדפדפן, ועוד בדיקות קטנות
על מה שה-API מחזיר ועל כך ש-``wsgi.app`` באמת מאורח.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import create_app  # noqa: E402

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
FOOTER = STRINGS["app"]["footer"]

HOSTED_TEXT = (
    "SlotWise · Built by Neta Baron · Your data stays in your browser · Report an issue"
)
LINKEDIN = "https://www.linkedin.com/in/neta-baron"
REPORT = "https://forms.gle/vbfne2rP9eSFuw179"


def _serve(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = make_server("127.0.0.1", port, app, threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    return srv, thread, f"http://127.0.0.1:{port}/"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        try:
            instance = pw.chromium.launch()
        except Exception as exc:  # אין דפדפן מותקן — לא כישלון של הקוד
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            yield instance
        finally:
            instance.close()


def _footer(browser, config):
    """טוען את הדף מול שרת עם ``config`` ומחזיר את השורה כפי שצוירה."""
    srv, thread, url = _serve(create_app(config=config))
    try:
        ctx = browser.new_context()
        try:
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            line = page.locator("#app-footer-line")
            line.wait_for(state="visible", timeout=15000)
            info = line.evaluate(
                """el => ({
                  text: el.textContent,
                  dir: el.getAttribute('dir'),
                  lang: el.getAttribute('lang'),
                  links: Array.from(el.querySelectorAll('a')).map(a => ({
                    text: a.textContent,
                    href: a.getAttribute('href'),
                    target: a.getAttribute('target'),
                    rel: a.getAttribute('rel'),
                  })),
                  lineCount: Math.round(
                    el.getBoundingClientRect().height /
                    parseFloat(getComputedStyle(el).lineHeight || '0')
                  ),
                  fontSize: parseFloat(getComputedStyle(el).fontSize),
                })"""
            )
            info["errors"] = errors
            return info
        finally:
            ctx.close()
    finally:
        srv.shutdown()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# 1. ‏/api/bootstrap אומר באיזה מצב השרת
# ---------------------------------------------------------------------------
def test_bootstrap_says_local_by_default():
    data = create_app({"allow_network": False}).test_client().get("/api/bootstrap").get_json()
    assert data["mode"] == "local"


def test_bootstrap_says_hosted_when_configured():
    app = create_app({"allow_network": False, "mode": "hosted"})
    data = app.test_client().get("/api/bootstrap").get_json()
    assert data["mode"] == "hosted"


def test_an_unknown_mode_reads_as_local():
    app = create_app({"allow_network": False, "mode": "Hosted "})
    data = app.test_client().get("/api/bootstrap").get_json()
    assert data["mode"] == "local"


def test_the_wsgi_app_is_hosted():
    """נקרא מההגדרות ולא בבקשה: ‏``wsgi.app`` משותף לכל התהליך, ובקשה
    ראשונה כאן נועלת אותו מפני ה-route שבודקת ‏test_wsgi_proxy מוסיפה."""
    import wsgi  # noqa: PLC0415 — ייבוא מאוחר: הוא בונה את האפליקציה

    assert wsgi.app.config["SLOTWISE"]["mode"] == "hosted"


# ---------------------------------------------------------------------------
# 2. מה שמצויר בפועל — בדיקה לכל מצב
# ---------------------------------------------------------------------------
def test_local_footer_keeps_the_hebrew_line(browser):
    info = _footer(browser, {"allow_network": False})
    assert not info["errors"], info["errors"]
    assert info["text"] == FOOTER["local"]
    assert "127.0.0.1" in info["text"]
    assert info["links"] == []
    assert info["dir"] is None and info["lang"] is None


def test_hosted_footer_has_the_public_line_and_links(browser):
    info = _footer(browser, {"allow_network": False, "mode": "hosted"})
    assert not info["errors"], info["errors"]
    assert info["text"] == HOSTED_TEXT
    assert info["dir"] == "ltr" and info["lang"] == "en"
    assert info["links"] == [
        {"text": "Neta Baron", "href": LINKEDIN, "target": "_blank", "rel": "noopener"},
        {"text": "Report an issue", "href": REPORT, "target": "_blank", "rel": "noopener"},
    ]
    # קטנה ובשורה אחת, ברוחב שולחני רגיל.
    assert info["lineCount"] == 1, info
    assert info["fontSize"] <= 12, info
