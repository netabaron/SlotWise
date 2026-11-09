# -*- coding: utf-8 -*-
"""
שגיאת API צפויה (‏``ApiError``) נרשמת ביומן בלי מה שהבקשה הכילה.

ה-``detail`` וה-``message`` של ‏``ApiError`` מצטטים את הבקשה: קוד הקורס
הפגום, השעות, הקידומת שהוקלדה. הם נשלחים לדפדפן ששלח אותה, וזה נשאר.
ביומן (‏stderr, ‏Cloud Logging) נרשמים רק השיטה, הנתיב והסטטוס.

כל מקרה כאן בודק שני צדדים: הערך עדיין מגיע לתשובה (אחרת המקרה לא בודק
דבר), ואינו מופיע באף רשומת יומן.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from src.web.api import create_app  # noqa: E402

SECRET = "9137"

CASES = [
    pytest.param(
        "POST", "/api/solve",
        {"codes": ["61756", f"zz-audit-{SECRET}"], "semester": "א"},
        id="invalid-course-code",
    ),
    pytest.param(
        "POST", "/api/solve",
        {"codes": ["61756"], "semester": "א", "blocked": [[f"audit-{SECRET}"]]},
        id="blocked-window-shape",
    ),
    pytest.param("GET", f"/api/catalog/browse?prefix=zz{SECRET}", None, id="browse-prefix"),
]


@pytest.fixture()
def client():
    return create_app({"allow_network": False, "mode": "hosted"}).test_client()


@pytest.mark.parametrize("method,url,body", CASES)
def test_the_log_line_has_no_request_values(client, caplog, method, url, body):
    with caplog.at_level(logging.DEBUG):
        res = client.open(url, method=method, json=body)
    assert res.status_code == 400, res.get_json()
    data = res.get_json()
    assert SECRET in f"{data['error']} {data['detail']}", "המקרה לא מצטט את הבקשה — הוא לא בודק דבר"

    path = url.split("?", 1)[0]
    assert f"API {method} {path} -> 400" in caplog.text, caplog.text
    assert SECRET not in caplog.text, caplog.text


def test_hours_out_of_order_are_not_logged(client, caplog):
    """‏``earliest=… >= latest=…`` — השעות שהסטודנט/ית בחר/ה."""
    body = {"codes": ["61756"], "semester": "א", "earliest": 1137, "latest": 547}
    with caplog.at_level(logging.DEBUG):
        res = client.post("/api/solve", json=body)
    assert res.status_code == 400, res.get_json()
    assert "1137" in res.get_json()["detail"]
    assert "API POST /api/solve -> 400" in caplog.text, caplog.text
    assert "1137" not in caplog.text and "547" not in caplog.text, caplog.text
