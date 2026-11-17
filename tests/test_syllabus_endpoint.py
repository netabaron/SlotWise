# -*- coding: utf-8 -*-
"""
‏``GET /api/syllabus/<code>`` — docs/SPEC_LINKS.md, Feature 2 (העיצוב המאושר, 2026-11-16).

השרת **אינו פונה לבראודה בזמן בקשה**: מה שידוע על קובצי הסילבוס נבדק בבנייה
הלילית (``scripts/check_syllabi.py``) ונקרא מ-``syllabi.json``. לכן כל המודול
רץ עם חסימת רשת: כל ניסיון לפתוח חיבור מפיל את הבדיקה.

נבדק:
* ‏302 ל-PDF של השנה כשהוא ``exists``, וגם כשהקוד **עוד לא נבדק** (וגם כשאין
  ‏``syllabi.json`` בכלל) — קוד שלא נבדק לעולם אינו מציג "אין סילבוס".
* ‏200 — דף הקורס כשהבדיקה מצאה ``missing``: שם, קוד, שנה, הודעה + תאריך
  הבדיקה, שורת עובדות, כפתור לידיעון, "לנסות לפתוח בכל זאת" ל-PDF של השנה,
  כפתור "שנה שעברה (תשפ"ו)" **רק** כשהוא קיים, קישור חזרה, ובלי טבלת קבוצות.
* ‏404 לקוד שאינו בקטלוג; ‏400 לקוד פגום, בלי לצטט אותו.
* אותו דבר בפרופיל המתארח (``allow_network=False``).
* ‏``src/syllabus.py`` אינו מייבא שום לקוח רשת.
"""

from __future__ import annotations

import ast
import html
import json
import re
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import syllabus as syllabus_mod  # noqa: E402
from web.api import create_app  # noqa: E402

STRINGS = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))
SAY = STRINGS["server"]["syllabus"]

#: קודים מהקטלוג הקפוא של הבדיקות (tests/fixtures/catalog).
EXISTS_CODE = "61757"
MISSING_CODE = "11001"        # חסר השנה, קיים בשנה שעברה
MISSING_NO_LAST = "11092"     # חסר השנה, ואין לשנה שעברה
UNCHECKED_CODE = "11004"      # בקטלוג, ואין עליו רשומה
NOT_IN_CATALOG = "9999999"

FIXTURE_META = json.loads(
    (ROOT / "tests" / "fixtures" / "catalog" / "catalog.meta.json").read_text(encoding="utf-8")
)
YEAR = str(FIXTURE_META["year_gregorian"])
LAST = str(int(YEAR) - 1)

SYLLABI = {
    "schema": "slotwise/syllabi",
    "version": 1,
    "updated_at": "2026-11-17T01:40:00Z",
    "years": {
        YEAR: {
            EXISTS_CODE: {"status": "exists", "checked": "2026-11-17"},
            MISSING_CODE: {"status": "missing", "checked": "2026-11-16"},
            MISSING_NO_LAST: {"status": "missing", "checked": "2026-11-15"},
        },
        LAST: {
            MISSING_CODE: {"status": "exists", "checked": "2026-11-17"},
            MISSING_NO_LAST: {"status": "missing", "checked": "2026-11-17"},
        },
    },
}


# ---------------------------------------------------------------------------
# חסימת רשת לכל המודול
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """כל ניסיון לפתוח חיבור — שקע, DNS, ‏urllib — מפיל את הבדיקה."""
    def refuse(*_args, **_kwargs):
        raise AssertionError("ניסיון לפנות לרשת מתוך /api/syllabus")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


@pytest.fixture()
def syllabi_file(tmp_path, monkeypatch):
    path = tmp_path / "syllabi.json"
    path.write_text(json.dumps(SYLLABI, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(syllabus_mod, "syllabi_path", lambda: path)
    return path


@pytest.fixture(params=["local", "hosted"])
def client(request):
    config = {"allow_network": False}
    if request.param == "hosted":
        config["mode"] = "hosted"
    return create_app(config).test_client()


def _text(res) -> str:
    body = res.get_data(as_text=True)
    inner = body.split("<body>", 1)[-1]
    return html.unescape(" ".join(re.sub(r"<[^>]+>", " ", inner).split()))


def _links(res) -> dict[str, str]:
    """טקסט הקישור → ‏href, מתוך <main>."""
    body = res.get_data(as_text=True)
    return {
        html.unescape(" ".join(re.sub(r"<[^>]+>", " ", text).split())): html.unescape(href)
        for href, text in re.findall(r'<a [^>]*href="([^"]*)"[^>]*>(.*?)</a>', body, re.S)
    }


# ---------------------------------------------------------------------------
# הפניות
# ---------------------------------------------------------------------------
def test_an_existing_syllabus_redirects_to_this_years_pdf(client, syllabi_file):
    res = client.get(f"/api/syllabus/{EXISTS_CODE}")
    assert res.status_code == 302
    assert res.headers["Location"] == f"https://info.braude.ac.il/info/{YEAR}/00{EXISTS_CODE}.pdf"
    assert "no-store" in res.headers.get("Cache-Control", "")


def test_a_code_never_checked_redirects_and_never_says_no_syllabus(client, syllabi_file):
    res = client.get(f"/api/syllabus/{UNCHECKED_CODE}")
    assert res.status_code == 302
    assert res.headers["Location"] == syllabus_mod.pdf_url(YEAR, UNCHECKED_CODE)


def test_without_syllabi_json_every_catalog_code_redirects(client, tmp_path, monkeypatch):
    monkeypatch.setattr(syllabus_mod, "syllabi_path", lambda: tmp_path / "absent.json")
    for code in (EXISTS_CODE, MISSING_CODE, UNCHECKED_CODE):
        res = client.get(f"/api/syllabus/{code}")
        assert res.status_code == 302, code
        assert res.headers["Location"] == syllabus_mod.pdf_url(YEAR, code)


def test_a_corrupt_syllabi_json_is_treated_as_unchecked(client, tmp_path, monkeypatch):
    bad = tmp_path / "syllabi.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(syllabus_mod, "syllabi_path", lambda: bad)
    res = client.get(f"/api/syllabus/{MISSING_CODE}")
    assert res.status_code == 302


def test_the_pdf_year_follows_the_catalog_not_a_constant(client, syllabi_file, monkeypatch):
    import web.api as api

    monkeypatch.setattr(api, "_shipped_meta", lambda: {"year_gregorian": "2031", "year": 'תשצ"א'})
    res = client.get(f"/api/syllabus/{UNCHECKED_CODE}")
    assert res.status_code == 302
    assert "/info/2031/" in res.headers["Location"]


# ---------------------------------------------------------------------------
# דף הקורס — missing
# ---------------------------------------------------------------------------
def test_missing_shows_the_course_page(client, syllabi_file):
    res = client.get(f"/api/syllabus/{MISSING_CODE}")
    assert res.status_code == 200
    assert res.headers["Content-Type"].startswith("text/html")
    text = _text(res)
    assert MISSING_CODE in text
    assert FIXTURE_META["year"] in text
    assert SAY["missingNotice"] in text
    assert "נבדק לאחרונה: 16.11.2026" in text
    body = res.get_data(as_text=True)
    assert 'dir="rtl"' in body and 'lang="he"' in body
    assert "<h1" in body
    assert "<table" not in body, "בלי טבלת קבוצות"


def test_the_course_page_has_the_name_and_a_facts_row(client, syllabi_file):
    res = client.get(f"/api/syllabus/{MISSING_CODE}")
    body = res.get_data(as_text=True)
    h1 = html.unescape(re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S).group(1)).strip()
    assert h1 and h1 != MISSING_CODE, "הכותרת היא שם הקורס"
    facts = [html.unescape(f) for f in re.findall(r"<li>(.*?)</li>", body)]
    assert facts, "שורת העובדות ריקה"
    assert any("סמסטר" in f for f in facts), facts
    assert any(k in " ".join(facts) for k in ("הרצאה", "תרגול", "מעבדה")), facts


def test_the_course_page_buttons(client, syllabi_file):
    res = client.get(f"/api/syllabus/{MISSING_CODE}")
    links = _links(res)
    assert links[SAY["yedionLink"]] == syllabus_mod.course_page_url(MISSING_CODE)
    assert links[SAY["tryAnyway"]] == syllabus_mod.pdf_url(YEAR, MISSING_CODE)
    last_label = SAY["lastYear"].replace("{year}", 'תשפ"ו' if LAST == "2026" else LAST)
    assert links[last_label] == syllabus_mod.pdf_url(LAST, MISSING_CODE)
    assert links[SAY["backToApp"]] == "/"
    body = res.get_data(as_text=True)
    # הכפתור הראשי הוא הידיעון.
    assert re.search(r'class="btn btn-primary"[^>]*href="[^"]*S_LOOK_FOR_NOSE', body)


def test_last_years_button_only_when_last_years_pdf_exists(client, syllabi_file):
    res = client.get(f"/api/syllabus/{MISSING_NO_LAST}")
    assert res.status_code == 200
    labels = " ".join(_links(res))
    assert "שנה שעברה" not in labels
    assert SAY["tryAnyway"] in labels


def test_the_page_follows_the_apps_theme(client, syllabi_file):
    body = client.get(f"/api/syllabus/{MISSING_CODE}").get_data(as_text=True)
    head = body.split("</head>", 1)[0]
    assert re.search(r'<script src="/static/theme\.js\?v=[^"]*"></script>', head)
    assert "/static/style.css" in head
    assert "<!--" not in body, "הערות מפתחים אינן נשלחות לדפדפן"


# ---------------------------------------------------------------------------
# 404 / 400
# ---------------------------------------------------------------------------
def test_a_code_not_in_the_catalog_is_a_friendly_404(client, syllabi_file):
    res = client.get(f"/api/syllabus/{NOT_IN_CATALOG}")
    assert res.status_code == 404
    text = _text(res)
    assert SAY["notFoundHeading"] in text
    assert NOT_IN_CATALOG in text
    links = _links(res)
    assert links[SAY["yedionLink"]] == syllabus_mod.course_page_url(NOT_IN_CATALOG)
    assert links[SAY["backToApp"]] == "/"


@pytest.mark.parametrize(
    "code", ["abc", "123", "12345678", "6175x", "-6175", "61757 ", "６１７５７"]
)
def test_a_bad_code_is_400_and_never_echoed(client, syllabi_file, code):
    res = client.get("/api/syllabus/" + code)
    assert res.status_code == 400
    text = _text(res)
    assert SAY["invalidHeading"] in text
    assert code.strip() not in text


# ---------------------------------------------------------------------------
# בלי רשת — גם בקוד
# ---------------------------------------------------------------------------
NETWORK_MODULES = {"urllib", "urllib.request", "http", "http.client", "socket",
                   "requests", "httpx", "aiohttp", "yedion_http"}


def test_syllabus_module_imports_no_network_client():
    tree = ast.parse((ROOT / "src" / "syllabus.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not imported & NETWORK_MODULES, imported & NETWORK_MODULES


def test_status_reads_the_file_and_defaults_to_unchecked(syllabi_file):
    assert syllabus_mod.status(YEAR, EXISTS_CODE).status == syllabus_mod.EXISTS
    assert syllabus_mod.status(YEAR, MISSING_CODE) == syllabus_mod.Status("missing", "2026-11-16")
    assert syllabus_mod.status(YEAR, UNCHECKED_CODE).status == syllabus_mod.UNCHECKED
    assert syllabus_mod.status("1999", EXISTS_CODE).status == syllabus_mod.UNCHECKED


def test_parse_drops_what_it_does_not_understand():
    parsed = syllabus_mod.parse(json.dumps({
        "schema": "slotwise/syllabi",
        "years": {"2027": {"61757": {"status": "exists", "checked": "x"},
                           "bad": {"status": "exists"},
                           "11001": {"status": "maybe"}},
                  "20x7": {"61757": {"status": "exists"}}},
    }))
    assert parsed["years"] == {"2027": {"61757": {"status": "exists", "checked": "x"}}}
    assert syllabus_mod.parse('{"schema": "other"}')["years"] == {}
