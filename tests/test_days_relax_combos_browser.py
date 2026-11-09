# -*- coding: utf-8 -*-
"""‏"מה יאפשר N ימים" כשאף ויתור בודד אינו מספיק — מהצד של המסך (2026-11-09).

ארבעה מצבים, לפי הסדר:
  1. ויתור בודד מגיע — הרשימה כמו קודם (``test_days_relax_panel.py``);
  2. רק שילוב מגיע — "לוותר על A + B (סה״כ N נ״ז) ← K ימים", שורה לשילוב;
  3. גם שילוב אינו מגיע — "הכי קרוב ל-N ימים", ומה שמוריד הכי הרבה;
  4. שום דבר אינו מוריד — שורה אחת, ``app.days.relaxUnreachable``.

הנדסת תוכנה שנה ג׳ סמסטר א׳, כל מתגי הנוכחות דלוקים (כמו ב-
``test_days_relax_panel.py``): המינימום 4, ויעד 2 — שהיה שם שורה אחת — מושג
בוויתור על שני קורסים. זה נבדק מול השרת האמיתי. מצבים 3–4 ושילוב בלי נ"ז
נבדקים בתשובה שהדף מקבל ומשונה בדרך (``page.route``), כדי שהציור ייבדק בלי
תלות בקטלוג.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="אין Playwright מותקן"
).sync_playwright

from werkzeug.serving import make_server  # noqa: E402

from src.web.api import create_app  # noqa: E402

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
DAYS = STRINGS["app"]["days"]
STORAGE_KEY = "braude_schedule_builder_v1"  # אין לשנותו — ראו CLAUDE.md

#: כמו ב-``test_days_relax_panel.py``: כל מתגי חובת הנוכחות דלוקים.
ALL_ON = {
    "11069": {'שו"ת': True},
    "61756": {"הרצאה": True, "תרגול": True, "פרויקט": True},
    "61757": {"הרצאה": True, "מעבדה": True},
    "62027": {"הרצאה": True, "תרגול": True},
    "61759": {"הרצאה": True, "תרגול": True},
    "61832": {"הרצאה": True, "תרגול": True},
}


def fmt(template: str, **params) -> str:
    for key, value in params.items():
        template = template.replace("{" + key + "}", str(value))
    return template


def _num(value):
    """כמו ‏``String(num)`` ב-JS: ‏9.0 → "9", ‏3.5 → "3.5"."""
    return int(value) if float(value).is_integer() else value


def _drop(codes, names, credits, days, units=None, known=True):
    return {"codes": codes, "names": names, "credits": credits, "min_days": days,
            "units": units or [[c] for c in codes], "credits_known": known}


#: יעד → מה שהדף מקבל במקום ``day_relaxations`` האמיתי.
ROUTED = {
    3: {  # שילובים: אחד עם מחיר, אחד בלי
        "items": [], "checked": [_drop(["1"], ["אלפא"], 3, 5)], "closest": [],
        "combos": [
            _drop(["1", "2"], ["אלפא", "בטא"], 7.5, 3),
            _drop(["3", "4"], ["גמא", "דלתא"], 0.0, 3, known=False),
        ],
        "combos_complete": True, "combo_max_units": 3,
    },
    4: {  # הכי קרוב, אחרי שכל שילוב נמדד
        "items": [], "checked": [_drop(["1"], ["אלפא"], 3, 5)], "combos": [],
        "closest": [_drop(["1"], ["אלפא"], 3, 5)],
        "combos_complete": True, "combo_max_units": 3,
    },
    5: {  # הכי קרוב, כשחיפוש השילובים נקטע — "לא מצאנו" ולא "אי אפשר"
        "items": [], "checked": [_drop(["1"], ["אלפא"], 3, 5)], "combos": [],
        "closest": [_drop(["1"], ["אלפא"], 3, 5)],
        "combos_complete": False, "combo_max_units": 3,
    },
    6: {  # שום דבר אינו מוריד
        "items": [], "checked": [_drop(["1"], ["אלפא"], 3, 7)], "combos": [],
        "closest": [], "combos_complete": True, "combo_max_units": 3,
    },
}

PANEL = """() => {
  const r = document.getElementById('days-relax');
  const t = e => e.textContent.replace(/\\s+/g, ' ').trim();
  return {shown: !r.hidden,
          visible: [...r.children].filter(e => !e.hidden).map(e => e.id),
          title: t(document.getElementById('days-relax-title')),
          intro: t(document.getElementById('days-relax-intro')),
          rows: [...r.querySelectorAll('#days-relax-list > li')].map(t),
          note: t(document.getElementById('days-relax-note'))};
}"""


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


def _wait_for_target(pg, days):
    """עד שהפאנל מצויר לתשובה של היעד הזה."""
    # ‏הכותרת והפתיח בלבד: שורה של היעד הקודם יכולה לומר "יאפשר 5 ימים".
    pg.wait_for_function(
        """(d) => { const r = document.getElementById('days-relax');
                    const head = document.getElementById('days-relax-title').textContent + ' '
                               + document.getElementById('days-relax-intro').textContent;
                    return !r.hidden && head.includes(d + ' ימים'); }""",
        arg=days, timeout=30000,
    )
    pg.wait_for_timeout(300)


@pytest.fixture(scope="module")
def panels(server):
    """יעד 2 מהשרת האמיתי, ו-3..6 בתשובה שמשונה בדרך."""
    with sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Exception as exc:
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            pg = b.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))

            pg.goto(server)
            pg.wait_for_timeout(3500)
            pg.evaluate(
                """(a) => { const s = JSON.parse(localStorage.getItem(a.key) || '{}');
                            s.attendance = a.attendance; localStorage.setItem(a.key, JSON.stringify(s)); }""",
                {"key": STORAGE_KEY, "attendance": ALL_ON},
            )
            pg.reload()
            pg.wait_for_timeout(3500)
            pg.select_option("#select-program", "הנדסת תוכנה")
            pg.select_option("#select-year", "3")
            pg.select_option("#select-term", "א")
            pg.wait_for_timeout(2500)
            pg.click("#step-year-next")
            pg.click("#btn-restore-recommended")
            pg.wait_for_timeout(5000)
            pg.click("#step-courses-next")

            def solve_for(days):
                def match(response):
                    if not response.url.endswith("/api/solve"):
                        return False
                    return json.loads(response.request.post_data or "{}").get("target_days") == days
                return match

            out = {}
            with pg.expect_response(solve_for(2), timeout=30000) as got:
                pg.click('.day-btn[data-days="2"]')
            out["real"] = got.value.json()
            _wait_for_target(pg, 2)
            out[2] = pg.evaluate(PANEL)

            def reroute(route):
                body = json.loads(route.request.post_data or "{}")
                scenario = ROUTED.get(body.get("target_days"))
                response = route.fetch()
                if scenario is None:
                    route.fulfill(response=response)
                    return
                data = response.json()
                data["target_reachable"] = False
                data["day_relaxations"] = {**scenario, "target": body["target_days"]}
                route.fulfill(response=response, json=data)

            pg.route("**/api/solve", reroute)
            for d in (3, 4, 5, 6):
                pg.click(f'.day-btn[data-days="{d}"]')
                _wait_for_target(pg, d)
                out[d] = pg.evaluate(PANEL)
            out["errors"] = errors
        finally:
            b.close()
    return out


def test_the_reported_case_now_says_what_to_drop(panels):
    """יעד 2 היה כאן "אי אפשר להגיע ל-2 ימים, גם בוויתור על קורס אחד." בלבד."""
    p, data = panels[2], panels["real"]
    assert data is not None, "התשובה של יעד 2 לא נקלטה"
    rel = data["day_relaxations"]
    assert data["target_reachable"] is False and rel["items"] == [], (
        "ויתור בודד מגיע ל-2 — הבדיקה אינה בודקת את הבאג"
    )
    assert rel["combos"], "‏/api/solve אינו מציע שילוב"
    assert p["visible"] == [
        "days-relax-title", "days-relax-intro", "days-relax-list", "days-relax-note",
    ], p
    assert p["title"] == fmt(DAYS["relaxTitle"], days=2)
    assert p["intro"] == DAYS["relaxComboIntro"]
    expected = [
        fmt(DAYS["relaxCombo"], names=" + ".join(c["names"]),
            credits=_num(c["credits"]), days=c["min_days"])
        if c["credits_known"] else
        fmt(DAYS["relaxComboNoCredits"], names=" + ".join(c["names"]), days=c["min_days"])
        for c in rel["combos"]
    ]
    assert p["rows"] == expected
    assert all(row.startswith("לוותר על ") and " + " in row for row in p["rows"]), p["rows"]
    assert p["note"] == DAYS["relaxNoRequiredInfo"], "ההסתייגות על קורסי חובה נשארת"


def test_a_combination_without_credits_names_no_total(panels):
    p = panels[3]
    assert p["title"] == fmt(DAYS["relaxTitle"], days=3)
    assert p["rows"] == [
        fmt(DAYS["relaxCombo"], names="אלפא + בטא", credits=7.5, days=3),
        fmt(DAYS["relaxComboNoCredits"], names="גמא + דלתא", days=3),
    ]
    assert "סה״כ 0" not in " ".join(p["rows"])


def test_the_closest_step_has_its_own_title_and_says_it_was_exhaustive(panels):
    p = panels[4]
    assert p["visible"] == [
        "days-relax-title", "days-relax-intro", "days-relax-list", "days-relax-note",
    ], p
    assert p["title"] == fmt(DAYS["relaxClosestTitle"], days=4)
    assert p["intro"] == fmt(DAYS["relaxClosestIntro"], days=4, n=3)
    assert p["rows"] == [fmt(DAYS["relaxOption"], name="אלפא", credits=3, days=5)]
    assert p["note"] == DAYS["relaxNoRequiredInfo"]


def test_a_cut_search_does_not_claim_it_is_impossible(panels):
    p = panels[5]
    assert p["intro"] == fmt(DAYS["relaxClosestIntroPartial"], days=5)
    assert "אי אפשר" not in p["intro"], p["intro"]
    assert p["rows"] == [fmt(DAYS["relaxOption"], name="אלפא", credits=3, days=5)]


def test_nothing_lowers_it_is_still_one_line(panels):
    p = panels[6]
    assert p["shown"], p
    assert p["visible"] == ["days-relax-intro"], p
    assert p["intro"] == fmt(DAYS["relaxUnreachable"], days=6)


def test_no_page_errors(panels):
    assert panels["errors"] == []
