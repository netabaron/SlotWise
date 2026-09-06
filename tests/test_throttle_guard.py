# -*- coding: utf-8 -*-
"""דף השהיה לעולם אינו נשמר מעל דמפ תקין.

ב-2026-09-06 רצה שליפה שנחסמה באמצע. הידיעון עונה 200 עם 158 תווים של
"השהיית גישה זמנית", ‏``fetch_course`` שמר אותם לפני שבדק — ‏171 מתוך 623
הדמפים ב-data/raw נדרסו. הנתונים ב-sections.json שרדו רק מפני ש-
``mark_course_failed`` משמר רשומה קודמת; הדמפים לא היה מי שישמר.

‏``fetch_details`` היה מוגן מהיום הראשון, עם הערה שמסבירה בדיוק למה.
‏``fetch_course`` לא — הבדיקה פשוט נכתבה במסלול אחד ולא הוצאה החוצה.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src import yedion_http as yh  # noqa: E402

#: הגוף האמיתי שנשמר על 171 הדמפים, אות באות.
THROTTLE_BODY = (
    "השהיית גישה זמנית: כתובת IP: 198.51.100.23<br>יותר מידי שאילתות בשעה"
    "<br>ניתן לנסות שוב החל משעה 9:00"
)
GOOD_PAGE = "<html><body>" + ("דף קורס אמיתי " * 200) + "</body></html>"


def _fetcher(tmp_path: Path):
    return yh.YedionHTTP(year="2027", raw_dir=str(tmp_path), log=lambda *a, **k: None)


# ==========================================================================
# 1. נקודת הכתיבה מסרבת
# ==========================================================================
def test_a_throttle_body_never_overwrites_an_existing_dump(tmp_path):
    """זה הנזק עצמו: דמפ תקין שנדרס בדף שגיאה."""
    existing = tmp_path / "61998_1.html"
    existing.write_text(GOOD_PAGE, encoding="utf-8")

    fetcher = _fetcher(tmp_path)
    assert fetcher.dump_html("61998", THROTTLE_BODY) is None
    assert existing.read_text(encoding="utf-8") == GOOD_PAGE, "הדמפ התקין נדרס"


def test_a_runt_body_never_overwrites_an_existing_dump(tmp_path):
    """גם בלי מילות המפתח: 158 תווים אינם דף."""
    existing = tmp_path / "61753_1.html"
    existing.write_text(GOOD_PAGE, encoding="utf-8")

    fetcher = _fetcher(tmp_path)
    assert fetcher.dump_html("61753", "<html>קצר מדי</html>") is None
    assert existing.read_text(encoding="utf-8") == GOOD_PAGE


def test_a_throttle_body_is_not_written_even_when_no_dump_exists(tmp_path):
    """אין דמפ קודם — עדיין לא כותבים. דף שגיאה אינו נתון."""
    fetcher = _fetcher(tmp_path)
    assert fetcher.dump_html("99999", THROTTLE_BODY) is None
    assert list(tmp_path.glob("99999_*.html")) == []


def test_the_refused_body_is_kept_for_inspection_out_of_the_way(tmp_path):
    """נשמר להתחקות — אבל לא במקום ש-glob של דמפים יסתכל בו."""
    fetcher = _fetcher(tmp_path)
    fetcher.dump_html("61998", THROTTLE_BODY)
    kept = list((tmp_path / "blocked").glob("61998_*.html"))
    assert len(kept) == 1, "הגוף שנדחה לא נשמר להתחקות"
    assert THROTTLE_BODY in kept[0].read_text(encoding="utf-8")
    # ‏Path.glob אינו רקורסיבי, ולכן הדמפים לא רואים אותו.
    assert list(tmp_path.glob("61998_*.html")) == []


def test_a_real_page_is_still_written(tmp_path):
    """השומר לא תופס דפים אמיתיים."""
    fetcher = _fetcher(tmp_path)
    path = fetcher.dump_html("61756", GOOD_PAGE)
    assert path is not None and path.exists()
    assert path.read_text(encoding="utf-8") == GOOD_PAGE


# ==========================================================================
# 2. השליפה מדווחת כישלון, ולא "הצלחה עם דף ריק"
# ==========================================================================
@pytest.mark.parametrize("body", [THROTTLE_BODY, "<html>זעיר</html>"])
def test_the_guard_raises_so_the_course_counts_as_failed(tmp_path, body):
    fetcher = _fetcher(tmp_path)
    with pytest.raises(yh.ThrottledError):
        fetcher._assert_not_throttled("קורס 61998", body)


def test_a_real_page_passes_the_guard(tmp_path):
    _fetcher(tmp_path)._assert_not_throttled("קורס 61756", GOOD_PAGE)


def test_fetch_course_leaves_a_good_dump_alone_when_throttled(tmp_path, monkeypatch):
    """התוצאה שחשובה: הדמפ התקין שורד שליפה חסומה.

    שתי שכבות מגינות עליו — הבדיקה ב-``fetch_course`` והסירוב ב-
    ``dump_html`` — ולכן הבדיקה הזאת עוברת גם אם אחת מהן תיפול. את הסדר
    עצמו נועל ``test_fetch_course_never_offers_a_bad_body_to_dump_html``.
    """
    fetcher = _fetcher(tmp_path)
    (tmp_path / "61998_1.html").write_text(GOOD_PAGE, encoding="utf-8")
    monkeypatch.setattr(fetcher, "_request", lambda *a, **k: THROTTLE_BODY)
    monkeypatch.setattr(fetcher, "_warn_if_no_session", lambda *a, **k: None)

    with pytest.raises(yh.ThrottledError):
        fetcher.fetch_course("61998")
    assert (tmp_path / "61998_1.html").read_text(encoding="utf-8") == GOOD_PAGE


def test_fetch_course_never_offers_a_bad_body_to_dump_html(tmp_path, monkeypatch):
    """הסדר עצמו: מאמתים, ורק אז שומרים.

    ‏dump_html מסרב לגוף חסום בכל מקרה, ולכן בדיקה על הקובץ בדיסק עוברת
    גם כשהסדר הפוך — היא בודקת את השכבה השנייה. כאן מרגלים אחרי הקריאה
    עצמה: אם ‏fetch_course בכלל הציע את הגוף הזה לשמירה, הסדר שגוי.
    """
    fetcher = _fetcher(tmp_path)
    offered: list[str] = []
    monkeypatch.setattr(fetcher, "_request", lambda *a, **k: THROTTLE_BODY)
    monkeypatch.setattr(fetcher, "_warn_if_no_session", lambda *a, **k: None)
    monkeypatch.setattr(
        fetcher, "dump_html", lambda name, html: offered.append(html) or None
    )

    with pytest.raises(yh.ThrottledError):
        fetcher.fetch_course("61998")
    assert offered == [], "גוף חסום הוצע לשמירה — האימות רץ אחרי השמירה"


# ==========================================================================
# 3. הריצה נעצרת במקום לגרור את הקטלוג כולו למטה
# ==========================================================================
def test_refresh_recognises_a_throttle_as_a_global_failure():
    import refresh as refresh_mod

    assert refresh_mod.is_throttled(yh.ThrottledError("השהיית גישה זמנית"))
    assert refresh_mod.is_throttled(RuntimeError("throttled by the yedion"))
    assert not refresh_mod.is_throttled(RuntimeError("קוד קורס ריק"))


def test_the_consecutive_failure_limit_is_small_enough_to_matter():
    import refresh as refresh_mod

    assert 1 < refresh_mod.MAX_CONSECUTIVE_FAILURES <= 10, (
        "מפסק שנפתח אחרי עשרות כישלונות אינו מפסק"
    )


# ==========================================================================
# 4. המפסק סופר בקשות שנכשלו — לא פענוחים שנכשלו
# ==========================================================================
def _fake_run(monkeypatch, outcome=None, raises=None, n=12):
    """מריץ את refresh_courses על קודים מדומים ומחזיר את ה-record."""
    import refresh as refresh_mod

    record = {"attempted": [], "refreshed": [], "failed": [], "skipped": [],
              "not_offered": []}

    def fake_one(*a, **k):
        if raises is not None:
            raise raises
        return outcome

    monkeypatch.setattr(refresh_mod, "refresh_one_course", fake_one)
    monkeypatch.setattr(refresh_mod, "mark_course_failed", lambda *a, **k: False)
    monkeypatch.setattr(refresh_mod, "curriculum_hints", lambda c: ({}, {}))
    monkeypatch.setattr(refresh_mod, "log", lambda *a, **k: None)

    backend = type("B", (), {"session_lost": lambda self: False})()
    result, reason = refresh_mod.refresh_courses(
        backend, None, None, record, [f"9000{i}" for i in range(n)], {},
        year_label="תשפ\"ז", year_greg="2027", semester="א", delay_s=0,
    )
    return result, reason, record


def test_parse_failures_do_not_stop_the_run(monkeypatch):
    """הדף הגיע ונשמר; הפרסר לא הבין אותו. זה עניין של קורס אחד.

    הריצה הראשונה אחרי התיקון נעצרה בדיוק כאן — חמישה קורסים מפקולטה
    שהפרסר לא מכיר, ו-115 קודים תקינים לא נוסו.
    """
    import refresh as refresh_mod

    bad = {"ok": False, "error": "parse returned no course", "not_offered": False,
           "group_count": 0, "warnings": []}
    result, _, record = _fake_run(monkeypatch, outcome=bad, n=12)
    assert result != refresh_mod.PASS_ABORTED, "כישלון פענוח עצר את הריצה"
    assert len(record["attempted"]) == 12, "קודים תקינים לא נוסו"
    assert record["skipped"] == []


def test_repeated_request_failures_do_stop_the_run(monkeypatch):
    """אלה כן: הבקשה עצמה נכשלת שוב ושוב — אין טעם להמשיך."""
    import refresh as refresh_mod

    result, reason, record = _fake_run(
        monkeypatch, raises=OSError("connection reset"), n=12
    )
    assert result == refresh_mod.PASS_ABORTED
    assert "consecutive" in reason
    assert len(record["attempted"]) == refresh_mod.MAX_CONSECUTIVE_FAILURES
    assert record["skipped"], "הקודים שלא נוסו לא נרשמו כדולגו"


def test_a_throttle_stops_immediately(monkeypatch):
    """חסימה היא הוראה להאט — עוצרים על הראשונה, לא אחרי חמש."""
    import refresh as refresh_mod

    result, reason, record = _fake_run(
        monkeypatch, raises=yh.ThrottledError("השהיית גישה זמנית"), n=12
    )
    assert result == refresh_mod.PASS_ABORTED
    assert "throttled" in reason
    assert len(record["attempted"]) == 1, "המשכנו לבקש אחרי שהשרת חסם"
