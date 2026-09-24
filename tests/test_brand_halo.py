"""הטבעת סביב השעון בסימן ממולאת ברקע הכותרת, ולא בצבע קבוע.

עד 2026-09-24 היא הייתה שמנת (בהיר) או כמעט־שחור (כהה) — צבעים שנבחרו
לקובץ כשהוא מוצג לבד — ועל רקע הכותרת זה נראה כהילה סביב השעון.
"""

from __future__ import annotations

import re
import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEMPLATE = (ROOT / "src" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "src" / "web" / "static" / "style.css").read_text(encoding="utf-8")


@pytest.mark.parametrize("variant", ["light", "dark"])
def test_each_inlined_mark_marks_its_halo(variant):
    group = re.search(
        rf'<g class="brand-icon-{variant}">(.*?)\n        </g>', TEMPLATE, re.S).group(1)
    assert len(re.findall(r'<circle class="brand-halo" [^>]*r="13"', group)) == 1


def test_halo_is_filled_with_the_header_background_token():
    header = re.search(r"\n\.app-header\s*\{([^}]*)\}", CSS).group(1)
    token = re.search(r"background:\s*(var\(--[\w-]+\))", header).group(1)
    assert re.search(rf"\.brand-icon \.brand-halo\s*\{{\s*fill:\s*{re.escape(token)};", CSS)


sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import create_app  # noqa: E402


@pytest.fixture(scope="module")
def server():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = make_server(
        "127.0.0.1", port, create_app(config={"allow_network": False}), threaded=True
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    "scheme,attr,mode",
    [
        ("light", None, "light"), ("dark", None, "dark"),
        ("dark", "light", "light"), ("light", "dark", "dark"),
    ],
)
def test_visible_halo_matches_the_header(server, scheme, attr, mode):
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            page = browser.new_page()
            page.emulate_media(color_scheme=scheme)
            page.goto(server)
            page.wait_for_timeout(1500)
            if attr:
                page.evaluate(
                    "a => document.documentElement.setAttribute('data-theme', a)", attr)
            else:
                page.evaluate(
                    "() => document.documentElement.removeAttribute('data-theme')")
            got = page.evaluate(
                """v => ({
                    halo: getComputedStyle(
                        document.querySelector('.brand-icon-' + v + ' .brand-halo')).fill,
                    header: getComputedStyle(
                        document.querySelector('.app-header')).backgroundColor,
                })""",
                mode,
            )
        finally:
            browser.close()

    assert got["halo"] == got["header"], got
