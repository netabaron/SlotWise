"""הלוגו וסט ה-favicon (docs/DESIGN.md, "Logo and favicon").

מה נשמר כאן: הקבצים מוגשים מ-static/brand, כל דף מקשר אליהם, הסימן שמוטבע
בכותרת זהה לקבצים, והסימן והסימן המילולי עוקבים אחרי הערכה הפעילה —
כולל בחירה מפורשת בבורר, לא רק מערכת ההפעלה.
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
BRAND = STATIC / "brand"
TEMPLATE = (ROOT / "src" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "style.css").read_text(encoding="utf-8")
CODE = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)

FAVICON_LINKS = [
    ('icon', "/static/brand/favicon.ico"),
    ('icon', "/static/brand/favicon.svg"),
    ('apple-touch-icon', "/static/brand/apple-touch-icon.png"),
]
BRAND_FILES = ("favicon.svg", "favicon.ico", "apple-touch-icon.png",
               "mark-light.svg", "mark-dark.svg")

WORDMARK = {
    "light": {"slot": "#0d1d3d", "wise": "#0e5a5e"},
    "dark": {"slot": "#ecebe6", "wise": "#3fb8ad"},
}


def _inner(svg: str) -> str:
    return re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1).strip()


def test_brand_files_live_under_static_and_the_drop_folder_is_gone():
    for name in BRAND_FILES:
        assert (BRAND / name).is_file(), name
    assert not (ROOT / "slotwise-logo").exists()


def test_the_head_links_the_whole_favicon_set():
    head = TEMPLATE.split("</head>")[0]
    for rel, href in FAVICON_LINKS:
        assert re.search(rf'<link rel="{rel}" href="{re.escape(href)}\?v=', head), href


@pytest.mark.parametrize("variant", ["light", "dark"])
def test_the_inlined_mark_is_the_file(variant):
    """שני עותקים של אותו ציור — הקובץ והגרסה המוטבעת — חייבים להישאר זהים."""
    group = re.search(
        rf'<g class="brand-icon-{variant}">(.*?)\n        </g>', TEMPLATE, re.S)
    assert group, f"אין גרסה {variant} מוטבעת"
    file_inner = _inner((BRAND / f"mark-{variant}.svg").read_text(encoding="utf-8"))
    assert group.group(1).strip() == file_inner


def test_wordmark_colours_are_written_once():
    assert re.search(r"--brand-slot:\s*var\(--ink\);", CODE)
    assert re.findall(r"(?<![\w-])--ink:\s*(#[0-9a-f]{6})", CODE) == ["#0d1d3d"]
    for token, value in (("--brand-wise", "#0e5a5e"),
                         ("--dark-brand-slot", "#ecebe6"),
                         ("--dark-brand-wise", "#3fb8ad")):
        hits = re.findall(rf"(?<![\w-]){re.escape(token)}:\s*(#[0-9a-f]{{6}})", CODE)
        assert hits == [value], (token, hits)
    for name in ("brand-slot", "brand-wise"):
        assert CODE.count(f"--{name}: var(--dark-{name});") == 2, name


def test_wordmark_font_is_local():
    face = re.search(r'@font-face\s*\{[^}]*"DM Serif Display"[^}]*\}', CODE)
    assert face and 'url("fonts/dm-serif-display-latin.woff2")' in face.group(0)
    assert (STATIC / "fonts" / "dm-serif-display-latin.woff2").read_bytes()[:4] == b"wOF2"
    assert "Open Font License" in (
        STATIC / "fonts" / "OFL-DMSerifDisplay.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def app_client():
    from src.web.api import create_app  # noqa: PLC0415

    return create_app(config={"allow_network": False}).test_client()


@pytest.mark.parametrize("name", BRAND_FILES)
def test_brand_files_are_served(app_client, name):
    resp = app_client.get(f"/static/brand/{name}")
    assert resp.status_code == 200
    assert resp.data == (BRAND / name).read_bytes()


# --------------------------------------------------------------------------
# בדפדפן: ארבעת מצבי הערכה
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
    "scheme,attr,mode",
    [
        ("light", None, "light"), ("dark", None, "dark"),
        ("dark", "light", "light"), ("light", "dark", "dark"),
    ],
)
def test_logo_follows_the_active_theme(server, scheme, attr, mode):
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
                    const shown = v => getComputedStyle(
                        document.querySelector('.brand-icon-' + v)).display !== 'none';
                    const t = document.querySelector('.brand-title');
                    return {
                        light: shown('light'), dark: shown('dark'),
                        slot: getComputedStyle(document.querySelector('.brand-slot')).color,
                        wise: getComputedStyle(document.querySelector('.brand-wise')).color,
                        text: t.textContent,
                        family: getComputedStyle(t).fontFamily,
                        loaded: document.fonts.check('26px "DM Serif Display"', 'SlotWise'),
                        icons: [...document.querySelectorAll('link[rel~="icon"], link[rel="apple-touch-icon"]')]
                               .map(l => l.getAttribute('href').split('?')[0]),
                    };
                }"""
            )
        finally:
            browser.close()

    assert got["light"] == (mode == "light"), got
    assert got["dark"] == (mode == "dark"), got
    assert got["slot"] == _rgb(WORDMARK[mode]["slot"]), got
    assert got["wise"] == _rgb(WORDMARK[mode]["wise"]), got
    assert got["text"] == "SlotWise"
    assert got["family"].startswith('"DM Serif Display"'), got
    assert got["loaded"], got
    assert sorted(got["icons"]) == sorted(h for _, h in FAVICON_LINKS), got
