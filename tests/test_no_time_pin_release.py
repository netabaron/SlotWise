"""נעיצה על קבוצה שכלל "בלי מועד קבוע" פוסל — משוחררת (2026-10-03).

קבוצה בלי מפגשים, כשלקבוצה אחרת מאותו קורס ומאותו סוג יש מפגשים, אינה נבחרת
לעולם (‏scheduler.CONSTRAINT_NO_TIME), ושלב המרצים אינו נותן לנעוץ אותה.
נעיצה כזו יכולה להגיע רק מ-localStorage שנשמר קודם. ‏``resolve_pins`` משחרר
אותה דרך ``dropped_pins`` עם ``server.pins.noTime``, והדף מוחק אותה ומודיע
בהודעה הקיימת שלו. נעיצה על קבוצה עם מועד, או על קבוצה בלי מועד ברכיב שאין
בו אף קבוצה עם מועד, נשארת.

השרת מצביע על מסד ריק — רק הקטלוג הקפוא נקרא, לא data/db המקומי.
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

from src.web.api import create_app  # noqa: E402

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
NO_TIME = STRINGS["server"]["pins"]["noTime"]
STORAGE_KEY = "braude_schedule_builder_v1"  # אין לשנותו — ראו CLAUDE.md
LAB, PROJECT = "מעבדה", "פרויקט"
LAB8, LAB3 = "271030210/8", "271030210/3"   # 11232: /8 בלי מועד, /3 עם מועד


def fill(template: str, **values) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


@pytest.fixture()
def client(tmp_path):
    return create_app(config={"allow_network": False, "db_root": str(tmp_path)}).test_client()


def _solve(client, codes, pinned):
    return client.post("/api/solve", json={"codes": codes, "semester": "א", "pinned": pinned}).get_json()


def test_a_pin_on_a_no_time_group_the_rule_excludes_is_dropped(client):
    data = _solve(client, ["11232"], {"11232": {LAB: LAB8}})
    want = fill(NO_TIME, group=LAB8, kind=LAB, code="11232")
    assert data["dropped_pins"] == [
        {"code": "11232", "kind": LAB, "group_id": LAB8, "reason": want}
    ], data["dropped_pins"]
    assert "11232" not in (data.get("pinned") or {}), data.get("pinned")
    # ‏בלי הנעיצה — יש מערכות, וכולן בלי ‏/8.
    again = _solve(client, ["11232"], {})
    assert again["schedules"] and not again["dropped_pins"]


def test_a_pin_on_a_timed_group_of_the_same_component_stays(client):
    data = _solve(client, ["11232"], {"11232": {LAB: LAB3}})
    assert not data["dropped_pins"], data["dropped_pins"]
    assert data["pinned"] == {"11232": {LAB: LAB3}}


def test_a_pin_on_a_no_time_group_with_no_timed_sibling_stays(client):
    data = _solve(client, ["61998"], {"61998": {PROJECT: "271060410"}})
    assert not data["dropped_pins"], data["dropped_pins"]
    assert data["schedules"], data.get("reasons")


# ---- הדף מוחק את הנעיצה ומודיע ------------------------------------------
sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    db = tmp_path_factory.mktemp("empty-db")
    srv = make_server(
        "127.0.0.1", port,
        create_app(config={"allow_network": False, "db_root": str(db)}), threaded=True,
    )
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


def test_the_page_clears_a_saved_pin_with_its_toast(server):
    want = fill(NO_TIME, group=LAB8, kind=LAB, code="11232")
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # אין דפדפן מותקן — לא כישלון של הקוד
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            pg = ctx.new_page()
            toasts = []
            pg.expose_function("recordToast", lambda text: toasts.append(text))
            pg.add_init_script(
                """new MutationObserver(() => {
                     const t = document.getElementById('toasts');
                     if (t && t.textContent.trim()) window.recordToast(t.textContent.trim());
                   }).observe(document, {subtree: true, childList: true, characterData: true});"""
            )
            pg.goto(server)
            pg.wait_for_timeout(2500)
            pg.select_option("#select-program", "הנדסת תוכנה")
            pg.select_option("#select-year", "3")
            pg.select_option("#select-term", "א")
            pg.wait_for_timeout(2500)
            pg.click("#btn-restore-recommended")
            pg.wait_for_timeout(4000)
            pg.evaluate(
                """(a) => { const s = JSON.parse(localStorage.getItem(a.key) || '{}');
                            s.codes = (s.codes || []).concat(['11232']);
                            s.pinned = Object.assign({}, s.pinned, {'11232': {[a.kind]: a.gid}});
                            localStorage.setItem(a.key, JSON.stringify(s)); }""",
                {"key": STORAGE_KEY, "kind": LAB, "gid": LAB8},
            )
            pg.reload()
            pg.wait_for_function(
                "() => !((window.slotwise.getState().pinned || {})['11232'])", timeout=20000
            )
            pg.wait_for_timeout(800)
            saved = json.loads(pg.evaluate(f"() => localStorage.getItem('{STORAGE_KEY}')"))
            assert "11232" not in (saved.get("pinned") or {}), saved.get("pinned")
            assert any(want in t for t in toasts), toasts
        finally:
            browser.close()
