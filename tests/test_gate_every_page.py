# -*- coding: utf-8 -*-
"""
שער 3 בודק את השנה על כל דף שפוענח, ודף שנפסל לעולם אינו "תקין".

עד 2026-09-26 שער 3 בדק מדגם: 60 הקודים הראשונים בסדר ממוין. בריצה הלילית
36080575127 הסשן חזר לתשפ"ו אחרי 145 דפים; ‏374 דפי תשפ"ו נשארו ב-data/raw,
``scan_raw`` ספר אותם כתקינים, ``build_records`` פענח אותם — והמדגם עבר, כי
60 הקודים הראשונים נשלפו כולם לפני הנסיגה. הבנייה נפלה רק על כיסוי ועל 52
קורסים שאין בתשפ"ו; לו תשפ"ו הציע את אותם קורסים, קטלוג משתי שנים היה עובר.

הבדיקות כאן:
  * קטלוג מעורב שהמדגם הישן היה מעביר — נפסל בשער החדש;
  * ``scan_raw`` עם שנה צפויה אינו סופר דף משנה אחרת כתקין;
  * דפים ב-``raw/wrong_year/`` (ו-``raw/blocked/``) אינם נספרים ואינם
    משמשים בנייה שממשיכה מאמצע: הקורסים שלהם נשלפים מחדש.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "src", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import build_catalog as B  # noqa: E402

WANT = 'תשפ"ז'
OTHER = 'תשפ"ו'

#: דף ידיעון אמיתי שמצהיר על תשפ"ז בכותרת (``שנה"ל תשפ"ז``) — פעם אחת בדיוק.
PAGE = (ROOT / "tests" / "fixtures" / "real_yedion" / "single_group.html").read_text(
    encoding="utf-8"
)
assert PAGE.count(WANT) == 1
WRONG_PAGE = PAGE.replace(WANT, OTHER)


def _old_gate_3(census: B.RawCensus, raw_dir: Path, expected_year: str) -> list[str]:
    """שער 3 כפי שהיה עד 2026-09-26, מילה במילה — כדי להראות מה הוא החמיץ."""
    wrong = []
    for code in list(census.intact)[:60]:
        hits = sorted(raw_dir.glob(f"{code}_*.html"))
        if not hits:
            continue
        if expected_year not in hits[-1].read_text(encoding="utf-8", errors="replace"):
            wrong.append(code)
    return wrong


def _gate_3(result: B.GateResult) -> tuple[bool, str]:
    (hit,) = [(ok, detail) for name, ok, detail in result.checks if name.startswith("3.")]
    return hit


def _mixed_raw(raw: Path, good: int, bad: int) -> tuple[list[str], list[str]]:
    """‏``good`` דפי תשפ"ז בקודים הנמוכים, ואחריהם ``bad`` דפי תשפ"ו — בדיוק
    הצורה של ריצה 9: מה שנשלף לפני הנסיגה ממוין ראשון."""
    raw.mkdir(parents=True, exist_ok=True)
    good_codes = [str(10000 + i) for i in range(good)]
    bad_codes = [str(30000 + i) for i in range(bad)]
    for code in good_codes:
        (raw / f"{code}_1.html").write_text(PAGE, encoding="utf-8")
    for code in bad_codes:
        (raw / f"{code}_1.html").write_text(WRONG_PAGE, encoding="utf-8")
    return good_codes, bad_codes


# ==========================================================================
# 1. הקטלוג המעורב: המדגם הישן מעביר, השער החדש פוסל
# ==========================================================================
def test_a_mixed_year_catalog_passes_the_old_sample_but_fails_the_new_gate(tmp_path):
    raw = tmp_path / "raw"
    good, bad = _mixed_raw(raw, good=145, bad=374)
    # ‏כמו לפני התיקון: scan_raw בלי שנה, ולכן כל 519 הדפים "תקינים" ומפוענחים.
    census = B.scan_raw(raw)
    assert len(census.intact) == 519
    records = {code: {"groups": []} for code in census.intact}

    assert _old_gate_3(census, raw, WANT) == [], "המדגם הישן היה אמור להחמיץ את זה"

    result = B.validate(records, census, {c: {} for c in good + bad}, None,
                        expected_year=WANT, raw_dir=raw)
    ok, detail = _gate_3(result)
    assert not ok
    assert not result.passed
    assert "374 עם שנה שגויה" in detail
    assert "נבדקו כל 519 הדפים" in detail


def test_a_single_wrong_year_page_at_the_end_fails_the_gate(tmp_path):
    """אין סף סובלנות, ואין "מחוץ למדגם"."""
    raw = tmp_path / "raw"
    good, bad = _mixed_raw(raw, good=200, bad=1)
    census = B.scan_raw(raw)
    records = {code: {"groups": []} for code in census.intact}
    ok, detail = _gate_3(B.validate(records, census, {}, None,
                                    expected_year=WANT, raw_dir=raw))
    assert not ok
    assert bad[0] in detail


def test_an_all_correct_catalog_still_passes_gate_3(tmp_path):
    raw = tmp_path / "raw"
    good, _ = _mixed_raw(raw, good=120, bad=0)
    census = B.scan_raw(raw, WANT)
    records = {code: {"groups": []} for code in census.intact}
    ok, detail = _gate_3(B.validate(records, census, {}, None,
                                    expected_year=WANT, raw_dir=raw))
    assert ok, detail
    assert "נבדקו כל 120 הדפים" in detail


def test_every_dump_of_a_parsed_course_is_checked(tmp_path):
    """‏build_records מפענח כל ``<code>_*.html`` — ולכן השער בודק את כולם."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "61756_1.html").write_text(WRONG_PAGE, encoding="utf-8")
    (raw / "61756_2.html").write_text(PAGE, encoding="utf-8")
    census = B.scan_raw(raw)
    ok, _ = _gate_3(B.validate({"61756": {"groups": []}}, census, {}, None,
                               expected_year=WANT, raw_dir=raw))
    assert not ok


def test_a_page_without_a_year_heading_keeps_the_old_rule(tmp_path):
    """דף בלי ``שנה"ל`` נבדק כמו קודם: התווית חייבת להופיע בו. לא מקל."""
    raw = tmp_path / "raw"
    raw.mkdir()
    bare = "<html><body>" + ("דף אמיתי " * 300) + "</body></html>"
    (raw / "61756_1.html").write_text(bare, encoding="utf-8")
    assert B.scan_raw(raw, WANT).wrong_year == ["61756"]
    # ‏גם כשהוא בכל זאת פוענח (scan_raw בלי שנה), השער פוסל אותו.
    census = B.scan_raw(raw)
    ok, _ = _gate_3(B.validate({"61756": {"groups": []}}, census, {}, None,
                               expected_year=WANT, raw_dir=raw))
    assert not ok


def test_a_label_elsewhere_on_a_wrong_year_page_does_not_rescue_it():
    """הכלל הישן היה "התווית מופיעה איפשהו". כותרת הקורס היא מה שקובע."""
    page = WRONG_PAGE.replace("</body>", f"<p>{WANT}</p></body>")
    assert WANT in page
    assert not B.page_is_year(page, WANT)
    assert B.page_is_year(PAGE, WANT)


# ==========================================================================
# 2. scan_raw: דף משנה אחרת אינו "תקין"
# ==========================================================================
def test_scan_raw_with_a_year_sets_wrong_year_pages_apart(tmp_path):
    raw = tmp_path / "raw"
    good, bad = _mixed_raw(raw, good=3, bad=2)
    census = B.scan_raw(raw, WANT)
    assert census.intact == good
    assert census.wrong_year == bad
    assert "שנה אחרת 2" in census.summary()

    result = B.validate({c: {"groups": []} for c in census.intact}, census, {}, None,
                        expected_year=WANT, raw_dir=raw)
    ok, detail = _gate_3(result)
    assert not ok, "דף בשנה אחרת נפסל גם כשלא פוענח"
    assert bad[0] in detail


def test_scan_raw_without_a_year_is_unchanged(tmp_path):
    raw = tmp_path / "raw"
    good, bad = _mixed_raw(raw, good=2, bad=2)
    census = B.scan_raw(raw)
    assert census.intact == good + bad
    assert census.wrong_year == []


@pytest.mark.parametrize("shed", ["wrong_year", "blocked"])
def test_pages_in_the_quarantine_folders_are_never_intact(tmp_path, shed):
    raw = tmp_path / "raw"
    (raw / shed).mkdir(parents=True)
    # ‏דף תקין לגמרי, בשנה הנכונה — ועדיין: מה שבתיקיית הפסולים לא נספר.
    (raw / shed / "61756_1.html").write_text(PAGE, encoding="utf-8")
    (raw / shed / "61757_1_20260925-013252-000000.html").write_text(PAGE, encoding="utf-8")
    for year in ("", WANT):
        census = B.scan_raw(raw, year)
        assert census.intact == [] and census.wrong_year == []
    assert B.build_records(raw, B.scan_raw(raw, WANT)) == {}


# ==========================================================================
# 3. בנייה שממשיכה מאמצע שולפת מחדש את מה שנפסל
# ==========================================================================
def test_a_resumed_build_refetches_quarantined_and_wrong_year_courses(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    good, bad = _mixed_raw(raw, good=3, bad=2)          # תשפ"ו שנשאר ב-raw
    (raw / "wrong_year").mkdir()
    (raw / "wrong_year" / "40000_1_20260925-013252-000000.html").write_text(
        WRONG_PAGE, encoding="utf-8")                   # מה שהשליפה הזיזה
    index = {c: {} for c in good + bad + ["40000"]}

    out = tmp_path / "catalog"
    monkeypatch.setattr(B, "RAW_DIR", raw)
    monkeypatch.setattr(B, "CATALOG_DIR", out)
    monkeypatch.setattr(B, "CATALOG_PATH", out / "catalog.jsonl")
    monkeypatch.setattr(B, "META_PATH", out / "catalog.meta.json")
    monkeypatch.setattr(B, "load_catalog_index", lambda: index)
    asked: list[list[str]] = []
    monkeypatch.setattr(B, "fetch_missing",
                        lambda codes, year, pace: asked.append(list(codes)) or (0, 0))

    rc = B.main(["--year", "2027", "--pace", "0", "--out", str(out)])

    assert asked == [sorted(bad + ["40000"])]
    # ‏"השליפה" המזויפת לא הביאה כלום, ולכן השער נופל והקטלוג לא נכתב.
    assert rc == B.EXIT_GATE_FAILED
    assert not (out / "catalog.jsonl").exists()
