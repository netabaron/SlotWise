# -*- coding: utf-8 -*-
"""
‏``plan_url`` — קישור לתוכנית הלימודים של המסלול באתר המכללה
(‏docs/SPEC_LINKS.md, פיצ'ר 1), בצד השרת.

רוב הבדיקות כאן מזריקות ערכים מזויפים דרך ``programs.load_programs`` — אותה
פונקציה ש-``_program_choices`` קורא בכל בקשה — אחרי שמחקו את ``plan_url``
האמיתי, כך שהן אינן תלויות בקובץ. בדיקה אחת, בסוף, קוראת את
``data/programs.json`` כמו שהוא: הכתובות שם אושרו ביד (2026-11-16) והן דפי
התואר של המחלקות, שכתובתם אינה תלויה בשנה.

נבדק:
* ‏``/api/bootstrap`` נושא ``plan_url`` למסלול שיש לו, ו**משמיט את המפתח**
  למסלול שאין לו — היעדר המפתח הוא מה שמסתיר את הקישור בממשק.
* ערך ריק, רווחים או כתובת שאינה http(s) נחשבים "אין".
* שני מועדי הכניסה של מתמטיקה הם רשומה אחת, ולכן קישור אחד.
* העמוד שולח את הקישור מוסתר ובלי ‏href, עם ‏target ו-rel הנכונים.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import programs as programs_mod  # noqa: E402
from web.api import create_app  # noqa: E402

SOFTWARE = "הנדסת תוכנה"
CIVIL = "הנדסה אזרחית"
MATH = "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה"
OTHER = "other"

#: כתובות מזויפות בכוונה — ‏.invalid אינו נפתר לעולם, ואיש לא יקבל אותן
#: בטעות כקישור אמיתי.
FAKE_PLAN_URLS = {
    SOFTWARE: "https://plans.example.invalid/software",
    MATH: "https://plans.example.invalid/math",
}

STRINGS = json.loads(
    (ROOT / "src" / "strings.json").read_text(encoding="utf-8")
)


def patch_plan_urls(monkeypatch, urls: dict[str, str]) -> None:
    """עוטף את ``programs.load_programs``: מוחק את ``plan_url`` האמיתי של כל
    מסלול ומציב במקומו את המזויף לפי שם המסלול — כך הבדיקות אינן תלויות
    בערכים שב-``data/programs.json``."""
    original = programs_mod.load_programs

    def load_with_plan_urls(*args, **kwargs):
        listed = original(*args, **kwargs)
        out = []
        for entry in listed:
            entry = dict(entry)
            entry.pop("plan_url", None)
            if entry.get("name") in urls:
                entry["plan_url"] = urls[entry["name"]]
            out.append(entry)
        return out

    monkeypatch.setattr(programs_mod, "load_programs", load_with_plan_urls)


@pytest.fixture()
def client():
    return create_app(config={"allow_network": False}).test_client()


def _programs(client) -> dict[str, dict]:
    res = client.get("/api/bootstrap")
    assert res.status_code == 200, res.status_code
    return {p["id"]: p for p in res.get_json()["programs"]}


def test_the_names_used_here_are_real_programs(client):
    """שם שאינו ברשימה היה הופך את כל הבדיקות כאן לריקות ומצליחות."""
    by_id = _programs(client)
    for name in (SOFTWARE, CIVIL, MATH, OTHER):
        assert name in by_id, f"{name!r} אינו ב-/api/bootstrap"


def test_bootstrap_carries_plan_url_for_a_program_that_has_one(client, monkeypatch):
    patch_plan_urls(monkeypatch, FAKE_PLAN_URLS)
    by_id = _programs(client)
    assert by_id[SOFTWARE]["plan_url"] == FAKE_PLAN_URLS[SOFTWARE]


def test_bootstrap_omits_plan_url_for_a_program_without_one(client, monkeypatch):
    patch_plan_urls(monkeypatch, FAKE_PLAN_URLS)
    by_id = _programs(client)
    assert "plan_url" not in by_id[CIVIL], by_id[CIVIL]
    # ‏"מסלול אחר" אינו מסלול, ואין לו דף באתר המכללה.
    assert "plan_url" not in by_id[OTHER], by_id[OTHER]


@pytest.mark.parametrize(
    "value", ["", "   ", None, "javascript:alert(1)", "/relative/path", "ftp://x.invalid/"]
)
def test_an_empty_or_non_http_plan_url_is_omitted(client, monkeypatch, value):
    patch_plan_urls(monkeypatch, {SOFTWARE: value})
    by_id = _programs(client)
    assert "plan_url" not in by_id[SOFTWARE], by_id[SOFTWARE]


def test_surrounding_whitespace_is_trimmed(client, monkeypatch):
    patch_plan_urls(monkeypatch, {SOFTWARE: "  https://plans.example.invalid/sw  "})
    assert _programs(client)[SOFTWARE]["plan_url"] == "https://plans.example.invalid/sw"


def test_both_math_intakes_share_one_plan_url(client, monkeypatch):
    """‏math-winter ו-math-spring הם מועדים של **רשומה אחת** ב-programs.json:
    אין רשומה נפרדת לכל מועד, ולכן גם אין שני קישורים שיכולים להתפצל."""
    patch_plan_urls(monkeypatch, FAKE_PLAN_URLS)
    by_id = _programs(client)
    math = by_id[MATH]
    assert {i["id"] for i in math["intakes"]} == {"winter", "spring"}
    assert math["plan_url"] == FAKE_PLAN_URLS[MATH]
    # ‏אף רשומה אחרת אינה "מתמטיקה" בשם אחר, עם קישור משלה.
    holders = sorted(pid for pid, p in by_id.items() if p.get("plan_url"))
    assert holders == sorted(FAKE_PLAN_URLS), holders


def test_the_page_ships_the_link_hidden_and_without_href(client):
    html = client.get("/").get_data(as_text=True)
    match = re.search(r"<a\b[^>]*\bid=\"program-plan-link\"[^>]*>", html)
    assert match, "‏#program-plan-link חסר בעמוד"
    tag = match.group(0)
    assert re.search(r"\shidden(\s|>|=)", tag), tag
    assert "href=" not in tag, f"קישור בלי מסלול חייב להיות בלי href: {tag}"
    assert 'target="_blank"' in tag, tag
    rel = re.search(r'rel="([^"]*)"', tag).group(1).split()
    assert "noopener" in rel and "noreferrer" in rel, rel
    assert STRINGS["ui"]["program"]["planLink"] in html
    assert STRINGS["ui"]["program"]["opensInNewTab"] in html


def test_every_real_program_carries_its_department_page(client):
    """הערכים האמיתיים שב-``data/programs.json`` מגיעים ל-``/api/bootstrap``
    כמו שהם: לכל מסלול דף תואר של מחלקה ב-w3.braude.ac.il/department/,
    בלי שנה בכתובת (דף שמקשר תמיד לתוכנית העדכנית, לא שנתון של שנה אחת)."""
    listed = json.loads((ROOT / "data" / "programs.json").read_text(encoding="utf-8"))
    by_id = _programs(client)
    for entry in listed["programs"]:
        plan = entry.get("plan_url")
        assert plan, f"{entry['slug']}: אין plan_url"
        assert re.fullmatch(r"https://w3\.braude\.ac\.il/department/[a-z]+/[a-z0-9-]+/", plan), plan
        assert not re.search(r"20\d\d|shnaton", plan), f"{entry['slug']}: שנה בכתובת: {plan}"
        assert by_id[entry["name"]].get("plan_url") == plan, entry["slug"]
    # שני מועדי הכניסה של מתמטיקה הם רשומה אחת, ולכן קישור אחד.
    assert sum(1 for p in by_id.values() if p.get("plan_url") == by_id[MATH]["plan_url"]) == 1
