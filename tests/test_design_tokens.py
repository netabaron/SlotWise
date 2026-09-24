"""שלב 1 של העיצוב מחדש: טוקני הצבע ו-Heebo (docs/DESIGN.md, "Tokens").

הערכים כאן מועתקים מטבלאות ה-DESIGN בכוונה: אם מישהו משנה צבע בגיליון,
הבדיקה הזאת צריכה להיכשל עד שה-DESIGN מתעדכן איתו.
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

STATIC = ROOT / "src" / "web" / "static"
CSS = (STATIC / "style.css").read_text(encoding="utf-8")
#: ‏בלי הערות: ההערות בגיליון מצטטות ערכים היסטוריים (‎--ink: #e6eaf1‎).
CODE = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)

LIGHT = {
    "bg": "#f4f4f1", "sf": "#ffffff", "ln": "#ebebe6", "bd": "#e3e3dd",
    "ink": "#111114", "sec": "#6e6e73", "mut": "#a3a3a8",
}
DARK = {
    "bg": "#0e0f11", "sf": "#17181b", "ln": "#222327", "bd": "#2a2b30",
    "ink": "#f2f2f0", "sec": "#9a9aa1", "mut": "#5d5e64",
}
FONT_FILES = ("heebo-hebrew.woff2", "heebo-latin.woff2")


def _value(token: str) -> str:
    hits = re.findall(rf"(?<![\w-]){re.escape(token)}\s*:\s*(#[0-9a-fA-F]{{6}})", CODE)
    assert len(hits) == 1, f"{token}: {len(hits)} הגדרות, ציפינו ל-1"
    return hits[0].lower()


@pytest.mark.parametrize("name", sorted(LIGHT))
def test_light_token_matches_design(name):
    assert _value(f"--{name}") == LIGHT[name]


@pytest.mark.parametrize("name", sorted(DARK))
def test_dark_token_matches_design(name):
    assert _value(f"--dark-{name}") == DARK[name]


@pytest.mark.parametrize(
    "block",
    [
        r'@media screen and \(prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme="light"\]\)\s*\{',
        r'@media screen \{\s*:root\[data-theme="dark"\]\s*\{',
    ],
)
def test_both_dark_blocks_map_the_design_tokens(block):
    match = re.search(block, CSS)
    assert match
    body = CSS[match.end():CSS.index("}", match.end())]
    missing = [n for n in DARK if f"--{n}: var(--dark-{n})" not in body]
    assert not missing, f"לא ממופים: {missing}"


def test_font_files_are_shipped_with_their_licence():
    for name in FONT_FILES:
        data = (STATIC / "fonts" / name).read_bytes()
        assert data[:4] == b"wOF2", f"{name} אינו woff2"
    assert "Open Font License" in (STATIC / "fonts" / "OFL.txt").read_text(encoding="utf-8")


def test_font_face_is_local_and_body_uses_heebo():
    faces = re.findall(r"@font-face\s*\{([^}]*)\}", CSS)
    assert len(faces) == len(FONT_FILES)
    for face in faces:
        assert '"Heebo"' in face
        src = re.search(r'url\("([^"]+)"\)', face).group(1)
        assert src.startswith("fonts/"), f"גופן חיצוני: {src}"
    body = re.search(r"\nbody\s*\{([^}]*)\}", CSS).group(1)
    assert re.search(r'font-family:\s*"Heebo",\s*system-ui,\s*sans-serif;', body)


@pytest.fixture(scope="module")
def app_client():
    from src.web.api import create_app  # noqa: PLC0415

    return create_app(config={"allow_network": False}).test_client()


@pytest.mark.parametrize("name", FONT_FILES)
def test_font_files_are_served(app_client, name):
    resp = app_client.get(f"/static/fonts/{name}")
    assert resp.status_code == 200
    assert resp.data[:4] == b"wOF2"


# --------------------------------------------------------------------------
# בדפדפן: הערכים שמגיעים בפועל לכל אחד משלושת מצבי הערכה, והגופן שנטען
# --------------------------------------------------------------------------
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


def _rgb(hex_: str) -> str:
    r, g, b = (int(hex_[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgb({r}, {g}, {b})"


@pytest.mark.parametrize(
    "scheme,attr,expected",
    [
        ("light", None, LIGHT), ("dark", None, DARK),
        ("dark", "light", LIGHT), ("light", "dark", DARK),
    ],
)
def test_page_uses_the_tokens_and_heebo(server, scheme, attr, expected):
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
                """async () => {
                    await document.fonts.ready;
                    const b = getComputedStyle(document.body);
                    const probe = document.createElement('button');
                    probe.className = 'btn btn-primary';
                    document.body.appendChild(probe);
                    const p = getComputedStyle(probe);
                    const out = {
                        bg: b.backgroundColor, color: b.color,
                        family: b.fontFamily,
                        primaryBg: p.backgroundColor, primaryInk: p.color,
                        buttonFamily: p.fontFamily,
                        loaded: document.fonts.check('16px Heebo', 'שלום')
                             && document.fonts.check('16px Heebo', 'Hello'),
                    };
                    probe.remove();
                    return out;
                }"""
            )
        finally:
            browser.close()

    assert got["bg"] == _rgb(expected["bg"]), got
    assert got["color"] == _rgb(expected["ink"]), got
    # ‏הכפתור הראשי הוא הדיו, והזוג מתהפך בשני המצבים.
    assert got["primaryBg"] == _rgb(expected["ink"]), got
    assert got["primaryInk"] == _rgb(expected["sf"]), got
    assert got["family"].startswith("Heebo"), got
    assert got["buttonFamily"].startswith("Heebo"), got
    assert got["loaded"], f"Heebo לא נטען: {got}"
