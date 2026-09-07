"""הפלטה חיה במקום אחד — והבדיקות כאן הן מה שמחזיק אותה שם.

למה הקובץ הזה קיים
-------------------
עד 2026-09-08 הפלטה הוגדרה בארבעה מקומות: ``:root`` הבהיר, שני גושי כהה
זהים־בכוונה, גוש ``@media print`` שהכריז פלטה משלו, ו-``src/render.py``
שהחזיק עותק שני של עשר שלישיות צבעי הקורס — תחת שמות **אחרים**
(``--cN-bg`` מול ``--course-N``). המשמעות המעשית: ``find-and-replace`` על
``--course-`` פסח על ``render.py`` לגמרי.

זה גם ייצר באג אמיתי שנשלח למשתמשים: ``:root[data-theme="dark"]`` בדרגת
עוצמה (0,2,0) גבר על ``:root`` של גוש ההדפסה בדרגה (0,1,0), ולכן הדפסה
במצב כהה יצאה עם ``--ink: #e6eaf1`` על נייר לבן — יחס ניגודיות 1.16:1.

הבדיקות כאן שומרות על שלושת התנאים שמונעים חזרה לשם.
"""

from __future__ import annotations

import re
import socket
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

CSS_PATH = ROOT / "src" / "web" / "static" / "style.css"
CSS = CSS_PATH.read_text(encoding="utf-8")

#: הטוקנים שמשנים ערך בין בהיר לכהה. כל אחד מהם חייב להופיע כערך ממשי
#: פעם אחת בלבד — תחת ``--dark-*`` — ולהיות ממופה בשני הגושים.
THEMED = [
    "bg", "panel", "panel-2", "chip", "ink", "muted", "line", "line-strong",
    "accent", "accent-ink", "accent-soft", "focus",
    "info-bg", "info-line", "info-ink", "ok-bg", "ok-line", "ok-ink",
    "warn-bg", "warn-line", "warn-ink", "err-bg", "err-line", "err-ink",
    "pin-bg", "pin-line", "tie-line", "dead-line",
]


#: ‏שני הסלקטורים חייבים לכלול את הכלל הפנימי ולא רק את ה-‎@media‎, אחרת
#: ‏_block מחזיר פעם את גוף המדיה ופעם את גוף הכלל — והשוואה ביניהם שקרית.
DARK_BY_MEDIA = (
    r'@media screen and \(prefers-color-scheme: dark\)\s*\{'
    r'\s*:root:not\(\[data-theme="light"\]\)'
)
DARK_BY_ATTR = r'@media screen \{\s*:root\[data-theme="dark"\]'


def _block(pattern: str) -> str:
    """מחזיר את גוף הכלל הראשון שהסלקטור שלו תואם, עד הסוגר המסולסל שלו."""
    match = re.search(pattern, CSS)
    assert match, f"לא נמצא גוש שתואם ל-{pattern!r}"
    start = CSS.index("{", match.end() - 1)
    depth, i = 0, start
    while True:
        if CSS[i] == "{":
            depth += 1
        elif CSS[i] == "}":
            depth -= 1
            if depth == 0:
                return CSS[start + 1:i]
        i += 1


def _decls(body: str) -> list[str]:
    """רשימת ההצהרות בגוש, מנורמלת לרווחים — כדי להשוות תוכן ולא עיצוב."""
    out = []
    for raw in body.split(";"):
        text = re.sub(r"/\*.*?\*/", "", raw, flags=re.S).strip()
        if text.startswith("--"):
            out.append(re.sub(r"\s+", " ", text))
    return out


# --------------------------------------------------------------------------
# 1. שני גושי הכהה זהים
# --------------------------------------------------------------------------
def test_the_two_dark_blocks_are_identical():
    """‏CSS אינו יודע לצרף תנאי מדיה וסלקטור, ולכן הכפילות מכוונת.

    מה שאינו מכוון הוא שהיא תיסדק. עד עכשיו ההסכם היה הערה בקובץ.
    """
    by_media = _decls(_block(DARK_BY_MEDIA))
    by_attr = _decls(_block(DARK_BY_ATTR))
    assert by_media, "גוש הכהה לפי מערכת ההפעלה ריק"
    assert by_media == by_attr, (
        "שני גושי הכהה אינם זהים. ההפרש:\n"
        + "\n".join(sorted(set(by_media) ^ set(by_attr)))
    )


def test_dark_blocks_hold_no_colour_values():
    """הגושים ממפים בלבד. צבע שנכתב בהם הוא עותק שני שאיש לא יעדכן."""
    body = _block(DARK_BY_MEDIA)
    literals = re.findall(r":\s*(#[0-9a-fA-F]{3,8})", body)
    assert not literals, f"ערכי צבע בתוך גוש מיפוי: {literals}"


def test_every_themed_token_is_mapped_in_both_dark_blocks():
    body = _block(DARK_BY_MEDIA)
    missing = [n for n in THEMED if f"--{n}: var(--dark-{n})" not in body]
    assert not missing, f"טוקנים שלא מופו לכהה: {missing}"


# --------------------------------------------------------------------------
# 2. הפלטה מוגדרת פעם אחת
# --------------------------------------------------------------------------
@pytest.mark.parametrize("prefix", ["dark", "print"])
def test_source_tokens_are_defined_exactly_once(prefix: str):
    """‏--dark-bg (וכו') מוגדר פעם אחת בלבד בכל הגיליון."""
    duplicated = []
    for name in THEMED:
        token = f"--{prefix}-{name}"
        hits = re.findall(rf"(?<![\w-]){re.escape(token)}\s*:\s*[^;]+;", CSS)
        if prefix == "print" and not hits:
            continue  # ‏הנייר דורס רק חלק מהטוקנים, וזה בסדר
        if len(hits) != 1:
            duplicated.append(f"{token}: {len(hits)} הגדרות")
    assert not duplicated, "\n".join(duplicated)


def test_course_ramp_is_defined_exactly_once_per_theme():
    for i in range(10):
        for suffix in ("", "-bd", "-fg"):
            for token in (f"--course-{i}{suffix}", f"--dark-course-{i}{suffix}"):
                hits = re.findall(
                    rf"(?<![\w-]){re.escape(token)}\s*:\s*#[0-9a-fA-F]{{6}}", CSS)
                assert len(hits) == 1, f"{token}: {len(hits)} הגדרות, ציפינו ל-1"


def test_print_block_declares_no_colour_of_its_own():
    """גוש ההדפסה ממפה מ-‎--print-*‎; צבע שנכתב בו הוא פלטה רביעית."""
    body = _block(r"@media print")
    root = _block(r"@media print\s*\{[\s\S]*?:root")
    literals = re.findall(r":\s*(#[0-9a-fA-F]{3,8})", root)
    assert not literals, f"ערכי צבע בגוש ההדפסה: {literals}"
    assert "--print-bg" in body


# --------------------------------------------------------------------------
# 3. ‏render.py קורא מהגיליון, ולא מחזיק עותק
# --------------------------------------------------------------------------
def test_render_palette_is_read_from_the_stylesheet():
    import render  # noqa: PLC0415  — הייבוא הוא חלק מהבדיקה

    assert len(render.PALETTE) == 10
    for i, entry in enumerate(render.PALETTE):
        for mode, prefix in (("light", "--course-"), ("dark", "--dark-course-")):
            expected = tuple(
                re.search(
                    rf"(?<![\w-]){re.escape(prefix + str(i) + suffix)}\s*:\s*(#[0-9a-fA-F]{{6}})",
                    CSS,
                ).group(1).lower()
                for suffix in ("", "-bd", "-fg")
            )
            assert entry[mode] == expected, f"course-{i} {mode}"


def test_render_py_holds_no_literal_course_colour():
    """אין שלישיות צבע כתובות בקוד — אחרת חזרנו לשני מקורות."""
    source = (ROOT / "src" / "render.py").read_text(encoding="utf-8")
    body = source.split("def _load_palette")[0]
    hexes = re.findall(r"#[0-9a-fA-F]{6}", body)
    assert not hexes, f"צבעים כתובים בקוד ב-render.py: {hexes}"


# --------------------------------------------------------------------------
# 4. הרגרסיה עצמה: הדפסה במצב כהה
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


@pytest.mark.parametrize(
    "scheme,attr",
    [("light", "light"), ("dark", "dark"), ("dark", None), ("light", None)],
)
def test_print_is_black_on_white_in_every_theme(server, scheme, attr):
    """הדף המודפס לבן־ושחור, ולא משנה באיזו ערכה המסך היה.

    זו הבדיקה שהייתה תופסת את הבאג: לפני התיקון, ‏scheme="dark"‎ החזיר
    ‏rgb(230, 234, 241)‎ — טקסט כמעט־לבן על נייר לבן.
    """
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:
            pytest.skip(f"אין דפדפן ל-Playwright: {exc}")
        try:
            page = browser.new_page()
            page.emulate_media(color_scheme=scheme)
            page.goto(server)
            page.wait_for_timeout(2500)
            if attr:
                page.evaluate(
                    "a => document.documentElement.setAttribute('data-theme', a)", attr)
            else:
                page.evaluate(
                    "() => document.documentElement.removeAttribute('data-theme')")
            page.emulate_media(media="print")
            page.wait_for_timeout(200)
            got = page.evaluate(
                "() => {"
                " const r = getComputedStyle(document.documentElement);"
                " const b = getComputedStyle(document.body);"
                " return {ink: r.getPropertyValue('--ink').trim(),"
                "         bg: r.getPropertyValue('--bg').trim(),"
                "         bodyColor: b.color};"
                "}"
            )
        finally:
            browser.close()

    assert got["ink"] == "#000000", f"דיו לא שחור בהדפסה: {got}"
    assert got["bg"] == "#ffffff", f"רקע לא לבן בהדפסה: {got}"
    assert got["bodyColor"] == "rgb(0, 0, 0)", got
