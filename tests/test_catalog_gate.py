# -*- coding: utf-8 -*-
"""שער האיכות של הקטלוג, מול השחתה **אמיתית**.

‏tests/fixtures/poisoned_raw מכיל 103 דפי השהיה אמיתיים שהידיעון החזיר
ב-6.9.2026 ושדרסו דמפים תקינים. הם נשמרו בכוונה לפני הגרידה הנקייה: מרגע
שהיא רצה, ההשחתה הזאת נעלמת ואי אפשר יהיה לבדוק את השער מול נזק אמיתי —
רק מול חיקוי שכתבתי בעצמי, שיסכים איתי מראש.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import build_catalog as B  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "poisoned_raw"
GOOD_PAGE = "<html><body>" + ("דף אמיתי " * 300) + "</body></html>"


def _catalog(n: int) -> dict:
    return {f"9{i:04d}": {"name": f"קורס {i}"} for i in range(n)}


# ==========================================================================
# 1. הראיה עצמה: השחתה אמיתית נפסלת
# ==========================================================================
def test_the_real_poisoned_dumps_are_all_classified_bad():
    census = B.scan_raw(FIXTURE)
    assert census.intact == [], "דף השהיה נספר כתקין"
    assert len(census.throttled) == 103, f"נמצאו {len(census.throttled)} במקום 103"
    assert census.bad and len(census.bad) == 103


def test_the_gate_rejects_the_real_corruption():
    """‏103 דפים חסומים מתוך 572 — שתי בדיקות נכשלות, והקטלוג לא נכתב."""
    census = B.scan_raw(FIXTURE)
    result = B.validate({}, census, _catalog(572), None, expected_year='תשפ"ז')
    assert not result.passed
    names = " ".join(result.failures)
    assert "אין דפים חסומים" in names, "בדיקת הדפים החסומים לא נכשלה"
    assert "כיסוי" in names, "בדיקת הכיסוי לא נכשלה"


def test_a_single_poisoned_dump_is_enough_to_fail(tmp_path):
    """גם דף חסום אחד פוסל. אין סף סובלנות להשחתה."""
    one = sorted(FIXTURE.glob("*.html"))[0]
    (tmp_path / "61756_1.html").write_text(GOOD_PAGE, encoding="utf-8")
    (tmp_path / one.name).write_text(one.read_text(encoding="utf-8"), encoding="utf-8")
    census = B.scan_raw(tmp_path)
    assert len(census.throttled) == 1 and len(census.intact) == 1
    result = B.validate({"61756": {"groups": []}}, census, _catalog(1), None)
    assert not result.passed


# ==========================================================================
# 2. שאר הבדיקות — כל אחת פוסלת לבדה
# ==========================================================================
def test_a_truncated_page_is_caught(tmp_path):
    """דף שנקטע באמצע הכתיבה: גדול מספיק, אבל בלי סגירה."""
    (tmp_path / "61756_1.html").write_text(GOOD_PAGE[:2000], encoding="utf-8")
    census = B.scan_raw(tmp_path)
    assert census.truncated == ["61756"] and census.intact == []


def test_coverage_below_the_floor_fails(tmp_path):
    census = B.RawCensus(intact=["1"] * 500)
    result = B.validate({str(i): {"groups": []} for i in range(500)},
                        census, _catalog(572), None, expected_year='תשפ"ז')
    assert not result.passed and any("כיסוי" in f for f in result.failures)


def test_a_lost_course_fails_the_regression_check():
    """קורס שהיה בקטלוג הקודם ונעלם — הבדיקה שתופסת פרסר שבור.

    ‏**עודכן 2026-09-18:** האינדקס שמועבר לשער חייב להכיל את 61757. מאז
    שהשער מבחין בין נסיגה לגריעה, קוד שאינו באינדקס נחשב קורס שהמכללה
    גרעה — וזה **אינו** פוסל. כאן הכוונה היא ההפך: הידיעון עדיין מפרסם
    אותו ואנחנו לא הפקנו אותו. ראו tests/test_catalog_gate_withdrawn.py.
    """
    prev = {"counts": {"timed_meetings": 1000}, "codes": ["61756", "61757"]}
    records = {"61756": {"groups": [{"semester": "א", "meetings": [
        {"start": 510, "end": 630}] * 1000}]}}
    census = B.RawCensus(intact=["61756"])
    still_listed = {"61756": {"name": "קורס"}, "61757": {"name": "קורס"}}
    result = B.validate(records, census, still_listed, prev, expected_year='תשפ"ז')
    assert not result.passed
    assert any("נסיגה" in f and "61757" in f for f in result.failures)


def test_losing_most_meetings_fails_even_with_every_course_present():
    """כל הקורסים קיימים, אבל השעות נעלמו. זה בדיוק פרסר ששבר בשקט."""
    prev = {"counts": {"timed_meetings": 1000}, "codes": ["61756"]}
    records = {"61756": {"groups": [{"semester": "א", "meetings": [
        {"start": 510, "end": 630}] * 10}]}}
    census = B.RawCensus(intact=["61756"])
    result = B.validate(records, census, _catalog(1), prev, expected_year='תשפ"ז')
    assert not result.passed and any("נסיגה" in f for f in result.failures)


def test_a_clean_build_passes():
    """הבקרה: קלט תקין עובר את כל שש הבדיקות."""
    census = B.RawCensus(intact=[f"9{i:04d}" for i in range(572)])
    records = {f"9{i:04d}": {"groups": [{"semester": "א", "meetings": [
        {"start": 510, "end": 630}]}]} for i in range(572)}
    result = B.validate(records, census, _catalog(572), None, expected_year='תשפ"ז')
    assert result.passed, result.failures


# ==========================================================================
# 3. הכתיבה עצמה
# ==========================================================================
def test_nothing_is_written_when_the_gate_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "CATALOG_PATH", tmp_path / "catalog.jsonl")
    monkeypatch.setattr(B, "META_PATH", tmp_path / "catalog.meta.json")
    monkeypatch.setattr(B, "RAW_DIR", FIXTURE)
    monkeypatch.setattr(B, "load_catalog_index", lambda: _catalog(572))
    rc = B.main(["--check"])
    assert rc == 1
    assert not (tmp_path / "catalog.jsonl").exists(), "נכתב קטלוג למרות שהשער נכשל"


def test_the_written_catalog_is_one_course_per_line(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "CATALOG_PATH", tmp_path / "catalog.jsonl")
    monkeypatch.setattr(B, "META_PATH", tmp_path / "catalog.meta.json")
    records = {"61756": {"code": "61756", "groups": []},
               "11069": {"code": "11069", "groups": []}}
    B.write_catalog(records, {"schema": "slotwise/catalog", "counts": {}})
    lines = (tmp_path / "catalog.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    # ממוין לפי קוד, כדי שההבדל בין שתי בניות יהיה קריא
    assert [json.loads(x)["code"] for x in lines] == ["11069", "61756"]
