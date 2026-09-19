# -*- coding: utf-8 -*-
"""
שורת הטריות בכותרת: שורה אחת, תווית הצפה אחת, ומצב אחד לשתיהן.

‏מה שהשתנה ב-2026-09-20
------------------------
בכותרת ישבו שתי שורות שאמרו את אותו דבר:

    הקטלוג נבנה לפני 19 שעות
    הקטלוג נבנה ב-19 בספטמבר 2026 · 571 קורסים

הראשונה מ-``#freshness-text``, השנייה מ-``#catalog-built``. שתיהן דיברו
במילים של מי שבונה את הקטלוג ולא של מי שמשתמש בו, והשנייה הוסיפה דיוק
שאיש לא ביקש במקום שבו ההחלטה היא "האם לסמוך על המסך".

עכשיו יש שורה אחת — ``מעודכן מהידיעון · לפני 19 שעות`` — והפירוט
(תאריך ושעה מדויקים, מספר קורסים, וההסתייגות על הידיעון) עבר לתווית
ההצפה שלה. ‏``#catalog-built`` נמחק.

‏מה שהקובץ הזה שומר עליו
-------------------------
שלושה תנאים שקל לשבור בלי לשים לב:

1. **שורה אחת, לא שתיים.** ‏``#catalog-built`` אסור שיחזור, ולא משנה
   באיזה שם.
2. **הפירוט לא נמחק אלא עבר.** קל "לתקן" שתי שורות בכך שמוחקים אחת מהן
   עם התוכן שבה; התאריך המדויק ומספר הקורסים חייבים להיות בתווית.
3. **הגיל, הצבע והנקודה נגזרים מאותה חותמת.** שלוש תצוגות של אותו נתון
   שמחושבות בנפרד מתחילות לסתור זו את זו, וזה בדיוק הבאג שהיה כאן קודם
   (נקודה כתומה ליד טקסט שאומר "לפני חצי שעה").
"""

from __future__ import annotations

import datetime as dt
import re
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

import shipped_catalog  # noqa: E402
import strings as strings_mod  # noqa: E402
from src.web.api import create_app  # noqa: E402


# ==========================================================================
# 1. הנוסח עצמו — בלי דפדפן
# ==========================================================================
def test_the_line_and_its_title_exist_in_the_copy_file():
    """‏strings.json הוא מקור הנוסח. ‏SPEC_WEB: אין טקסט מוצג בקוד."""
    assert "{age}" in strings_mod.get("app.header.updated", "")
    assert "{when}" in strings_mod.get("app.header.updatedTitle", "")
    assert "{count}" in strings_mod.get("app.header.updatedTitle", "")
    assert "{when}" in strings_mod.get("app.header.updatedTitleNoCount", "")
    assert strings_mod.get("app.header.updatedTitleNote", "")


def test_the_old_two_line_copy_is_gone():
    """הנוסח הישן נמחק ולא רק הפסיק להיקרא.

    מחרוזת שנשארת בקובץ אחרי שהשורה שלה נמחקה היא הזמנה להחזיר אותה
    בטעות — ובמקרה הזה להחזיר איתה את השורה השנייה.
    """
    for key in (
        "app.header.builtAt",
        "app.header.builtAtMixed",
        "app.header.builtAtTitle",
        "app.header.fetched",
        "app.catalog.builtAt",
        "app.catalog.builtAtWithCount",
    ):
        assert strings_mod.get(key, "") == "", f"{key} עדיין בקובץ הנוסח"


def test_the_stale_colour_comes_from_a_token_not_a_hex():
    """‏style.css הוא מקור צבע יחיד. הכלל שמור ב-test_theme_tokens.py,
    וכאן נבדק שהשורה החדשה לא פרצה אותו."""
    css = (ROOT / "src" / "web" / "static" / "style.css").read_text(encoding="utf-8")
    rule = re.search(r"\.fresh-text\[data-state=\"stale\"\]\s*\{([^}]*)\}", css)
    assert rule, "אין כלל CSS לשורת טריות מיושנת"
    body = rule.group(1)
    assert "var(--warn-" in body, body
    assert "#" not in body, f"צבע קשיח בכלל של שורת הטריות: {body!r}"


# ==========================================================================
# 2. מה שמגיע למסך
# ==========================================================================
def _age_catalog(days: float | None):
    """מזייף את תאריך בניית הקטלוג, ומחזיר את המצב לקדמותו בסוף.

    ‏אותה זהירות כמו ב-``tests/test_phase6_states_browser.py``: מילון חדש
    ולא שינוי במקום, כי ``load()`` מחזיר את ``_CACHE`` עצמו.
    """
    before_cache = shipped_catalog._CACHE
    before_stamp = shipped_catalog._STAMP
    if days is not None:
        stamp = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        real = shipped_catalog.load()
        shipped_catalog._CACHE = {
            "courses": real.get("courses") or {},
            "meta": dict(real.get("meta") or {}, built_at=stamp),
        }
        shipped_catalog._STAMP = shipped_catalog._mtimes()
    return before_cache, before_stamp


def _restore(saved):
    shipped_catalog._CACHE, shipped_catalog._STAMP = saved


def _read_header(days: float | None) -> dict:
    """מרים שרת, טוען את העמוד, ומחזיר את מה שהכותרת באמת מציגה."""
    saved = _age_catalog(days)
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
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/")
            page.wait_for_timeout(2000)
            got = page.evaluate(
                """() => {
                  const t = document.getElementById('freshness-text');
                  const d = document.getElementById('freshness-dot');
                  return {
                    text: t ? t.textContent.trim() : '',
                    title: t ? (t.getAttribute('title') || '') : '',
                    state: t ? (t.getAttribute('data-state') || '') : '',
                    colour: t ? getComputedStyle(t).color : '',
                    dot: d ? (d.getAttribute('data-state') || '') : '',
                    second: !!document.getElementById('catalog-built'),
                  };
                }"""
            )
            browser.close()
        return got
    finally:
        srv.shutdown()
        thread.join(timeout=5)
        _restore(saved)


@pytest.fixture(scope="module")
def fresh_header():
    """‏קטלוג "שנבנה עכשיו" — ‏**מזויף בכוונה, ולא ``None``.**

    ‏הקטלוג שהבדיקות קוראות הוא הקפוא שב-``tests/fixtures/catalog``, והוא
    ‏נבנה ב-2026-09-09 ולא יתעדכן לעולם (זה כל הרעיון — ראו
    ‏``tests/conftest.py``). כלומר הוא מיושן מול כל חלון סביר, ובדיקה
    ‏ש"לא מזייפת כלום" הייתה בודקת את מצב האזהרה פעמיים ואת המצב התקין
    ‏אף פעם.
    """
    return _read_header(0)


@pytest.fixture(scope="module")
def stale_header():
    """‏60 יום — הרבה מעבר ל-SLOTWISE_MAX_AGE_HOURS שברירת המחדל שלו 24."""
    return _read_header(60)


def test_the_header_shows_one_line_only(fresh_header):
    assert not fresh_header["second"], "‏#catalog-built חזר לעמוד"
    assert "\n" not in fresh_header["text"], fresh_header["text"]
    assert fresh_header["text"].startswith("מעודכן מהידיעון"), fresh_header["text"]


def test_the_line_carries_a_relative_age(fresh_header):
    """גיל יחסי, לא תאריך. ‏"לפני …" הוא מה שמפריד בין השורה לתווית."""
    assert "לפני" in fresh_header["text"] or "עכשיו" in fresh_header["text"], (
        fresh_header["text"]
    )


def test_the_detail_moved_into_the_title_and_was_not_deleted(fresh_header):
    """תאריך מלא עם שעה, ומספר הקורסים — שניהם בתווית ההצפה."""
    title = fresh_header["title"]
    assert "נמשכו מהידיעון" in title, title
    # ‏d.M.yyyy HH:mm — אותו סדר שבו todayLabel() כותב תאריך, ועם שעה.
    assert re.search(r"\b\d{1,2}\.\d{1,2}\.\d{4} \d{2}:\d{2}\b", title), title
    assert re.search(r"\d+ קורסים", title), title
    # ההסתייגות על הידיעון לא נעלמה עם השורה שנשאה אותה קודם.
    assert "השתנה מאז" in title, title


def test_a_fresh_catalog_is_not_marked_as_a_warning(fresh_header):
    assert fresh_header["state"] == "fresh", fresh_header
    assert fresh_header["dot"] == "fresh", fresh_header


def test_a_stale_catalog_keeps_the_same_sentence_in_warning_colour(stale_header):
    """‏**אותה שורה, צבע אחר.** מה שהשתנה הוא הגיל, לא מה שהאפליקציה
    יודעת, ולכן נוסח אחר כאן היה אומר לסטודנט/ית שמשהו אחר קרה."""
    assert stale_header["text"].startswith("מעודכן מהידיעון"), stale_header["text"]
    assert stale_header["state"] == "stale", stale_header
    assert stale_header["colour"] != "", stale_header


def test_the_dot_and_the_line_never_disagree(fresh_header, stale_header):
    """שתיהן נגזרות מאותה חותמת ומאותו סף. נקודה כתומה ליד טקסט רגוע היא
    בדיוק הבאג שהיה כאן קודם."""
    for got in (fresh_header, stale_header):
        assert got["state"] == got["dot"], got
