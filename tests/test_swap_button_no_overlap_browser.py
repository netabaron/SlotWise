# -*- coding: utf-8 -*-
"""כפתור "להחליף" לא עולה על השורה שלפניו, והחץ נשאר בגובה הטקסט (2026-11-10).

‏``.suggestion-swap .swap-apply`` היה עם ‎``margin-block: -6px``‎, כדי
שהכפתור לא יגביה את השורה. כשהמשפט נשבר — ‏390px, המקרה של
‏11026 → 11210 — השוליים השליליים משכו את הכפתור כ-‏5px אל תוך השורה
הראשונה, והוא כיסה את הטקסט.

בלי השוליים הכפתור מגביה את השורה שלו. ב-‏1100px זו השורה הראשונה, והחץ
‏‎absolute‎ (שנצמד לראש השורה) צף ‏6px מעל הטקסט; לכן החץ של שורת ההחלפה
הוא ‎inline-block‎ על קו הבסיס.

1. ‏390px: ראש הכפתור לא גבוה מתחתית שורת הטקסט שלפניו. השורות נמדדות
   מ-``Range.getClientRects()`` על ``.swap-text`` — מה שמצויר, לא ה-DOM.
2. ‏1100px: החץ באותו גובה ביחס לטקסט כמו בהצעה בלי כפתור. ל-‎::before‎ אין
   מלבן ב-DOM, ולכן נמדד הדיו שלו בצילום של ה-li, ברצועת הריפוד.
"""

from __future__ import annotations

import base64
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

KEY = "braude_schedule_builder_v1"
INDUSTRY = "הנדסת תעשייה וניהול"
CODES = ["51132", "51159", "51213", "51429", "51724", "11026"]

SWAP = "#infeasible-suggestions > li.suggestion-swap"
PLAIN = "#infeasible-suggestions > li:not(.suggestion-swap)"


def _seed():
    return {
        "schema": 1, "studyYear": 3, "term": "א", "semester": "5",
        "codes": CODES, "known": {}, "program": INDUSTRY, "topN": 5,
        "activeSchedule": 0, "targetDays": 4, "provenanceReady": True,
        "autoSemester": "5", "autoCodes": [], "manualCodes": CODES,
        "autoDropped": [], "autoTrack": "", "overlaps": "none",
    }


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    # ‏``db_root`` ריק: הקטלוג הקפוא, כמו ב-CI ובאתר המאורח.
    empty_db = tmp_path_factory.mktemp("empty_db")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    app = create_app(config={"allow_network": False, "db_root": str(empty_db)})
    srv = make_server("127.0.0.1", port, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield "http://127.0.0.1:%d/" % port
    finally:
        srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            yield b
        finally:
            b.close()


def _open(browser, server, width):
    ctx = browser.new_context(
        viewport={"width": width, "height": 1000}, color_scheme="light",
        device_scale_factor=2,
    )
    ctx.add_init_script(
        "localStorage.setItem('%s', %s);" % (KEY, json.dumps(json.dumps(_seed())))
    )
    page = ctx.new_page()
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.goto(server)
    page.wait_for_function(
        "() => !document.getElementById('schedule-empty').hidden", timeout=20000
    )
    return ctx, page


GEOMETRY = """() => {
  const li = document.querySelector('%s');
  if (!li) return null;
  const text = li.querySelector('.swap-text');
  const button = li.querySelector('.swap-apply');
  const range = document.createRange();
  range.selectNodeContents(text);
  // ‏מלבן לכל קטע (‏bdi, קוד, טקסט) — מאחדים לפי שורה.
  const lines = [];
  for (const r of range.getClientRects()) {
    if (!r.width) continue;
    const same = lines.find(l => Math.abs(l.top - r.top) < 2);
    if (same) same.bottom = Math.max(same.bottom, r.bottom);
    else lines.push({top: r.top, bottom: r.bottom});
  }
  lines.sort((a, b) => a.top - b.top);
  const b = button.getBoundingClientRect();
  return {
    text: li.textContent.replace(/\\s+/g, ' ').trim(),
    lines: lines,
    button: {top: b.top, bottom: b.bottom},
  };
}""" % SWAP


def test_swap_button_does_not_cover_the_line_before_it_at_phone_width(browser, server):
    ctx, page = _open(browser, server, 390)
    try:
        g = page.evaluate(GEOMETRY)
        assert g is not None, "אין שורת החלפה בקופסה"
        assert "11026" in g["text"] and "11210" in g["text"], g["text"]

        lines = g["lines"]
        # ‏בלי שבירה אין "שורה לפני", והבדיקה לא בודקת כלום.
        assert len(lines) >= 2, "המשפט לא נשבר ב-390px: %r" % lines

        button = g["button"]
        middle = (button["top"] + button["bottom"]) / 2
        last = lines[-1]
        # ‏הכפתור בא מיד אחרי המשפט: בשורה האחרונה שלו, או בשורה משלו.
        before = lines[-2] if last["top"] <= middle <= last["bottom"] else last
        assert button["top"] >= before["bottom"], (
            "ראש הכפתור (%.1f) מעל תחתית השורה שלפניו (%.1f): %r"
            % (button["top"], before["bottom"], g)
        )
        assert page.errors == []
    finally:
        ctx.close()


# ‏ראש השורה הראשונה של הטקסט, ביחס לראש ה-li: מלבן צומת הטקסט הראשון
# ‏שישירות תחת המכל (‏``.swap-text`` או ה-li). לא ``bdi.code`` — לפונט שלו
# ‏יכול להיות גובה אחר, וההשוואה היא בין שני li באותו פונט.
TEXT_TOP = """(sel) => {
  const li = document.querySelector(sel);
  if (!li) return null;
  const box = li.querySelector('.swap-text') || li;
  const node = [].slice.call(box.childNodes)
    .find(n => n.nodeType === 3 && n.textContent.trim());
  if (!node) return null;
  const range = document.createRange();
  range.selectNodeContents(node);
  const first = [].slice.call(range.getClientRects()).filter(r => r.width)
    .sort((a, b) => a.top - b.top)[0];
  const r = li.getBoundingClientRect();
  const cs = getComputedStyle(li);
  return {
    textTop: first.top - r.top,
    width: r.width,
    pad: parseFloat(cs.paddingInlineStart),
    rtl: cs.direction === 'rtl',
  };
}"""

# ‏השורות ברצועת הריפוד (שם יושב החץ) שיש בהן דיו: צבע רחוק מצבע הרקע
# ‏השכיח ברצועה. מחזיר את מרכז הדיו בפיקסלים של CSS, מראש ה-li.
ARROW_INK = """async ({src, width, pad, rtl}) => {
  const img = new Image();
  img.src = src;
  await img.decode();
  const scale = img.width / width;
  const c = document.createElement('canvas');
  c.width = img.width; c.height = img.height;
  const g = c.getContext('2d');
  g.drawImage(img, 0, 0);
  // ‏פיקסל אחד פחות בצד הטקסט, שהקצה המוחלק של האות הראשונה לא ייספר.
  const w = Math.floor(pad * scale) - 1;
  const d = g.getImageData(rtl ? img.width - w : 0, 0, w, img.height).data;
  const count = new Map();
  for (let i = 0; i < d.length; i += 4) {
    const k = d[i] + ',' + d[i + 1] + ',' + d[i + 2];
    count.set(k, (count.get(k) || 0) + 1);
  }
  const bg = [...count.entries()].sort((a, b) => b[1] - a[1])[0][0].split(',').map(Number);
  let top = -1, bottom = -1;
  for (let y = 0; y < img.height; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      const diff = Math.max(Math.abs(d[i] - bg[0]), Math.abs(d[i + 1] - bg[1]),
                            Math.abs(d[i + 2] - bg[2]));
      if (diff > 64) { if (top < 0) top = y; bottom = y; break; }
    }
  }
  if (top < 0) return null;
  return (top + bottom + 1) / 2 / scale;
}"""


def _arrow_offset(page, decoder, sel):
    """מרכז הדיו של החץ פחות ראש השורה הראשונה של הטקסט, ב-‏CSS px."""
    geo = page.evaluate(TEXT_TOP, sel)
    assert geo is not None, sel
    png = page.locator(sel).first.screenshot()
    src = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    ink = decoder.evaluate(
        ARROW_INK, {"src": src, "width": geo["width"], "pad": geo["pad"], "rtl": geo["rtl"]}
    )
    assert ink is not None, "לא נמצא חץ ברצועת הריפוד של %s" % sel
    return ink - geo["textTop"]


def test_swap_arrow_is_level_with_its_text_at_desktop_width(browser, server):
    ctx, page = _open(browser, server, 1100)
    try:
        g = page.evaluate(GEOMETRY)
        assert g is not None, "אין שורת החלפה בקופסה"
        assert "11026" in g["text"] and "11210" in g["text"], g["text"]

        # ‏המקרה שנבדק: משפט בשורה אחת, והכפתור באותה שורה — גבוה ממנה.
        assert len(g["lines"]) == 1, "המשפט נשבר ב-1100px: %r" % g["lines"]
        line, button = g["lines"][0], g["button"]
        assert button["top"] < line["top"] and button["bottom"] > line["bottom"], g
        assert page.locator(PLAIN).count() >= 1, "אין הצעה בלי כפתור להשוואה"

        # ‏הצילום מפוענח בדף ריק, לא בדף של האפליקציה.
        decoder = ctx.new_page()
        swap = _arrow_offset(page, decoder, SWAP)
        plain = _arrow_offset(page, decoder, PLAIN)
        assert abs(swap - plain) <= 1.0, (
            "החץ של שורת ההחלפה זז ‏%.1fpx ביחס לטקסט (בהצעה בלי כפתור: %.1f, כאן: %.1f)"
            % (swap - plain, plain, swap)
        )
        assert page.errors == []
    finally:
        ctx.close()
