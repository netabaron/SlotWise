# -*- coding: utf-8 -*-
"""
דף הקורס של ``/api/syllabus/<code>`` בדפדפן אמיתי (docs/SPEC_LINKS.md, Feature 2).

הדף נפתח בלשונית חדשה, מחוץ לאפליקציה — ובכל זאת הוא חייב לעקוב אחרי הערכה
שנבחרה **באפליקציה** (``localStorage["slotwise_theme"]``, אותו מקור), ולא רק
אחרי מערכת ההפעלה. נבדק:

* מערכת בהירה + "כהה" שמור באפליקציה → הדף כהה; והפוך.
* בלי בחירה שמורה — הדף עוקב אחרי מערכת ההפעלה.
* ‏RTL; ‏Tab מגיע לכפתור הידיעון, לכפתור של שנה שעברה, ל"לנסות לפתוח בכל זאת"
  ולקישור החזרה, בסדר הזה, ולכל אחד טבעת פוקוס גלויה.

השרת רץ בתוך התהליך עם ``syllabi.json`` זמני; אף בקשה לא יוצאת לבראודה
(‏``context.route`` עונה במקומה, וממילא הדף אינו טוען ממנה דבר).
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _path in (str(ROOT / "src"), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

import syllabus as syllabus_mod  # noqa: E402
from web.api import create_app  # noqa: E402

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
SAY = STRINGS["server"]["syllabus"]
META = json.loads(
    (ROOT / "tests" / "fixtures" / "catalog" / "catalog.meta.json").read_text(encoding="utf-8")
)
YEAR = str(META["year_gregorian"])
LAST = str(int(YEAR) - 1)
CODE = "11001"  # בקטלוג הקפוא; חסר השנה, קיים בשנה שעברה

THEME_KEY = "slotwise_theme"


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    path = tmp_path_factory.mktemp("syllabi") / "syllabi.json"
    path.write_text(json.dumps({
        "schema": "slotwise/syllabi", "version": 1, "updated_at": "2026-11-17T01:00:00Z",
        "years": {YEAR: {CODE: {"status": "missing", "checked": "2026-11-16"}},
                  LAST: {CODE: {"status": "exists", "checked": "2026-11-16"}}},
    }), encoding="utf-8")
    patch = pytest.MonkeyPatch()
    patch.setattr(syllabus_mod, "syllabi_path", lambda: path)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = make_server("127.0.0.1", port, create_app(config={"allow_network": False}), threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/api/syllabus/{CODE}"
    finally:
        srv.shutdown()
        thread.join(timeout=5)
        patch.undo()


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


def _open(browser, url, *, os_scheme: str, saved: str | None):
    ctx = browser.new_context(viewport={"width": 900, "height": 800}, color_scheme=os_scheme)
    ctx.route("https://info.braude.ac.il/**", lambda route: route.abort())
    if saved is not None:
        ctx.add_init_script(f"try {{ localStorage.setItem('{THEME_KEY}', '{saved}'); }} catch (e) {{}}")
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda exc: pg.errors.append(str(exc)))
    res = pg.goto(url, wait_until="load")
    assert res is not None and res.status == 200, res and res.status
    return ctx, pg


def _look(pg) -> dict:
    return pg.evaluate("""() => ({
        theme: document.documentElement.getAttribute('data-theme'),
        dir: document.documentElement.getAttribute('dir'),
        bg: getComputedStyle(document.body).backgroundColor,
        ink: getComputedStyle(document.querySelector('h1')).color,
    })""")


def _luminance(rgb: str) -> float:
    r, g, b = [int(x) for x in rgb[rgb.index("(") + 1:rgb.index(")")].split(",")[:3]]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_saved_dark_wins_over_a_light_os(browser, server):
    ctx, pg = _open(browser, server, os_scheme="light", saved="dark")
    try:
        look = _look(pg)
    finally:
        ctx.close()
    assert look["theme"] == "dark"
    assert _luminance(look["bg"]) < 80, look
    assert _luminance(look["ink"]) > _luminance(look["bg"]), look


def test_saved_light_wins_over_a_dark_os(browser, server):
    ctx, pg = _open(browser, server, os_scheme="dark", saved="light")
    try:
        look = _look(pg)
    finally:
        ctx.close()
    assert look["theme"] == "light"
    assert _luminance(look["bg"]) > 180, look


@pytest.mark.parametrize("os_scheme", ["light", "dark"])
def test_without_a_saved_choice_it_follows_the_os(browser, server, os_scheme):
    ctx, pg = _open(browser, server, os_scheme=os_scheme, saved=None)
    try:
        look = _look(pg)
        errors = list(pg.errors)
    finally:
        ctx.close()
    assert look["theme"] is None
    assert (_luminance(look["bg"]) < 80) == (os_scheme == "dark"), look
    assert look["dir"] == "rtl"
    assert errors == []


def test_keyboard_reaches_every_action_with_a_visible_ring(browser, server):
    ctx, pg = _open(browser, server, os_scheme="light", saved=None)
    try:
        seen = []
        for _ in range(6):
            pg.keyboard.press("Tab")
            seen.append(pg.evaluate("""() => {
                const a = document.activeElement;
                const s = getComputedStyle(a);
                return {text: a.textContent.trim(), tag: a.tagName,
                        outline: s.outlineStyle, width: parseFloat(s.outlineWidth)};
            }"""))
    finally:
        ctx.close()
    texts = [s["text"] for s in seen if s["tag"] == "A"]
    last_label = SAY["lastYear"].replace("{year}", 'תשפ"ו' if LAST == "2026" else LAST)
    wanted = [SAY["yedionLink"], last_label, SAY["tryAnyway"], SAY["backToApp"]]
    assert texts[:4] == wanted, texts
    for s in seen[:4]:
        assert s["outline"] != "none" and s["width"] >= 2, s
