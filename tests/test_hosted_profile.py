# -*- coding: utf-8 -*-
"""
האתר הציבורי אינו קורא את ‏``data/profile.json`` (‏src/web/api.py ``_profile``).

הקובץ הוא הבחירה האישית של מי שמריץ/ה את השרת המקומי, ו-‏``/api/bootstrap``
מחזיר אותו לכל מבקר/ת. עד 2026-11-09 רק ‏.dockerignore ו-‏.gitignore הרחיקו
אותו מהאתר; עכשיו גם הקוד. הבדיקה המקומית היא בקרה: היא מוכיחה שהקובץ
הזמני באמת מגיע ל-``_profile`` כשמותר לו.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from src.web.api import create_app  # noqa: E402

MARKER = "audit-profile-9137"


@pytest.fixture()
def profile(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({
        "student": {"program": MARKER, "year_of_study": 3, "curriculum_semester": "5"},
        "preferences": {"note": MARKER},
        "selected_courses": [{"code": "61756", "name": MARKER}],
        "total_credits": 21.5,
    }, ensure_ascii=False), encoding="utf-8")
    return path


def _bootstrap(config: dict) -> dict:
    res = create_app({"allow_network": False, **config}).test_client().get("/api/bootstrap")
    assert res.status_code == 200
    return res.get_json()


def test_local_mode_reads_the_profile(profile):
    """הבקרה: בלי זה, הבדיקה הבאה הייתה עוברת גם אילו הקובץ לא נקרא אף פעם."""
    data = _bootstrap({"profile_path": str(profile)})
    assert data["profile"]["student"]["program"] == MARKER


def test_hosted_mode_never_returns_the_profile(profile):
    data = _bootstrap({"profile_path": str(profile), "mode": "hosted"})
    assert data["mode"] == "hosted"
    assert data["profile"] == {
        "student": {}, "preferences": {}, "selected_courses": [], "total_credits": None,
    }
    assert MARKER not in json.dumps(data, ensure_ascii=False)


def test_hosted_profile_is_empty_for_every_caller(profile):
    """‏‏/api/courses ו-‏/api/solve משלימים סמסטר ושנה מ-``_profile()`` — באירוח הוא ריק."""
    app = create_app({"allow_network": False, "mode": "hosted", "profile_path": str(profile)})
    with app.test_request_context("/api/bootstrap"):
        from src.web.api import _profile  # noqa: PLC0415

        assert _profile() == {}
