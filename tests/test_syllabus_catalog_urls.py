# -*- coding: utf-8 -*-
"""
כתובת סילבוס תקינה לכל קורס בקטלוג **האמיתי** שנשלח (``data/catalog``) —
docs/SPEC_LINKS.md, Feature 2; docs/GROUND_TRUTH.md §10.

הקטלוג הקפוא של הבדיקות (``tests/fixtures/catalog``) אינו מה שהשרת מגיש. כאן
נקראים הקבצים שהבנייה הלילית כותבת, ולכל קוד בהם נבדק ש-``syllabus.pdf_url``
בונה בדיוק::

    https://info.braude.ac.il/info/<year_gregorian של הקטלוג>/<הקוד מרופד ל-7 ספרות>.pdf

וגם שהקוד עצמו עובר את ``valid_code`` — אחרת ``/api/syllabus/<code>`` היה מחזיר
לו 400, והכפתור על הכרטיס היה מוביל לדף "קוד לא תקין".

בלי רשת: כל ניסיון לפתוח חיבור מפיל את הבדיקה.
"""

from __future__ import annotations

import json
import re
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import syllabus as syllabus_mod  # noqa: E402

#: הקטלוג שנשלח — בכוונה לא ``SLOTWISE_CATALOG_DIR``, ש-conftest מפנה לקטלוג הקפוא.
CATALOG_DIR = ROOT / "data" / "catalog"

URL_RE = re.compile(r"https://info\.braude\.ac\.il/info/(?P<year>[0-9]{4})/(?P<code>[0-9]{7})\.pdf")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("ניסיון לפנות לרשת מבדיקה שאמורה לרוץ בלי רשת")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def _meta() -> dict:
    return json.loads((CATALOG_DIR / "catalog.meta.json").read_text(encoding="utf-8"))


def _catalog_codes() -> list[str]:
    """כל קוד בקטלוג: מרשומות ``catalog.jsonl`` ומרשימת ``codes`` שבמטא."""
    codes: list[str] = []
    with (CATALOG_DIR / "catalog.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                codes.append(str(json.loads(line)["code"]))
    codes += [str(c) for c in _meta().get("codes") or []]
    return sorted(set(codes))


def test_the_shipped_catalog_has_a_gregorian_year_and_courses():
    year = str(_meta().get("year_gregorian") or "")
    assert syllabus_mod.valid_year(year), f"year_gregorian לא תקין: {year!r}"
    assert len(_catalog_codes()) >= 100, "הקטלוג שנשלח ריק או כמעט ריק"


def test_every_catalog_code_gets_a_valid_syllabus_url():
    year = str(_meta()["year_gregorian"])
    bad: list[str] = []
    for code in _catalog_codes():
        if not syllabus_mod.valid_code(code):
            bad.append(f"{code}: אינו קוד של 4–7 ספרות — /api/syllabus היה מחזיר 400")
            continue
        url = syllabus_mod.pdf_url(year, code)
        m = URL_RE.fullmatch(url)
        if m is None:
            bad.append(f"{code}: {url} אינו בתבנית")
            continue
        if m["year"] != year:
            bad.append(f"{code}: שנה {m['year']} ולא {year}")
        if m["code"] != code.zfill(7) or len(m["code"]) != 7 or int(m["code"]) != int(code):
            bad.append(f"{code}: {m['code']} אינו הקוד מרופד בדיוק ל-7 ספרות")
    assert not bad, f"{len(bad)} קודים:\n" + "\n".join(bad[:20])


def test_the_meta_codes_and_the_records_agree():
    """אם השניים נפרדים, אחד מהם מכיל קוד שלבדיקה הלילית אין כתובת בשבילו."""
    meta_codes = {str(c) for c in _meta().get("codes") or []}
    record_codes = set()
    with (CATALOG_DIR / "catalog.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                record_codes.add(str(json.loads(line)["code"]))
    assert meta_codes == record_codes, (
        f"רק במטא: {sorted(meta_codes - record_codes)[:10]}, "
        f"רק ברשומות: {sorted(record_codes - meta_codes)[:10]}"
    )
