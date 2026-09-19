# -*- coding: utf-8 -*-
"""
‏מי מנצח במיזוג — המסד המקומי או הקטלוג שנשלח — ומה זה עושה לתווית הטריות.

‏הבאג שהקובץ הזה נכתב בשבילו (2026-09-20)
------------------------------------------
‏``Store._load_sections_db`` מיזג את הקטלוג מתחת ל-``data/db`` והמסד המקומי
ניצח **תמיד**. אפליקציה מקומית שמשכה ``git pull`` עם קטלוג שנבנה באותו לילה
המשיכה להגיש ‏572 רשומות שנשלפו שבועות קודם, והכותרת דיווחה את התאריך הישן:
‏"הנתונים עודכנו לאחרונה: 2026-09-01 (לפני 18 ימים)". התמונה המתארחת לא סבלה
מזה רק מפני שאין בה ``data/db`` כלל.

‏הכלל החדש: **החדש מנצח, קוד-אחר-קוד**, ושוויון נשאר אצל המקומי. התוצאה
הנגזרת — וזו החשובה — היא ש-``fetched_at`` של רשומה שהגיעה מהקטלוג הוא תאריך
**הבנייה**, ולכן ``freshness``, ``is_stale`` ו-``SLOTWISE_MAX_AGE_HOURS``
נמדדים מול הקטלוג.

‏**הוא מותנה ב-``prefer_newer_catalog=True``, ורק שכבת הווב מדליקה אותו.**
‏``Store(root, use_shipped=True)`` לבדו ממשיך להתנהג בדיוק כפי שהתנהג — זו
המשמעות המקורית של ``use_shipped`` ("הקטלוג ממלא את השאר"), וזה מה
ש-``tests/test_shipped_catalog.py::test_user_data_wins_over_the_shipped_layer``
מקבע. ‏``test_the_default_precedence_is_unchanged`` כאן שומר על אותו גבול
מהצד הזה.

‏הקטלוג כאן הוא הקפוא שב-``tests/fixtures/catalog`` — ‏``conftest.py`` מציב
את ``SLOTWISE_CATALOG_DIR`` לפני כל ייבוא.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT / "src"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import shipped_catalog  # noqa: E402
import store as store_mod  # noqa: E402


# ---------------------------------------------------------------------------
# עזרים
# ---------------------------------------------------------------------------
def _built_at() -> str:
    stamp = shipped_catalog.built_at()
    assert stamp, "‏הקטלוג הקפוא חייב לשאת built_at — ראו tests/conftest.py"
    return stamp


def _some_shipped_code() -> str:
    codes = sorted(shipped_catalog.courses())
    assert codes, "‏הקטלוג הקפוא ריק"
    return codes[0]


def _shift(stamp: str, **delta) -> str:
    """חותמת ‏ISO-8601 ב-UTC, מוזזת. אותה צורה בדיוק שהמסד כותב."""
    base = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (base + timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_db(root: Path, entries: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "sections.json").write_text(
        json.dumps(
            {
                "schema": "braude-schedule-builder/sections-db",
                "version": 1,
                "updated_at": "",
                "courses": entries,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _local_entry(code: str, fetched_at: str, *, lecturer: str = "מרצה מקומי") -> dict:
    """רשומה מקומית מזוהה: מרצה שאינו קיים בקטלוג, כדי שאפשר יהיה לראות
    בעין איזו משתי הרשומות שרדה את המיזוג."""
    return {
        "course": {
            "code": code,
            "name": "קורס מקומי",
            "groups": [
                {
                    "group": "10",
                    "kind": "הרצאה",
                    "lecturer": lecturer,
                    "semester": "א",
                    "meetings": [
                        {"day": 1, "start": 600, "end": 660, "room": "100"}
                    ],
                }
            ],
        },
        "meta": {
            "fetched_at": fetched_at,
            "last_attempt_at": fetched_at,
            "source_url": "https://info.braude.ac.il/yedion/local",
            "group_count": 1,
            "ok": True,
        },
    }


# ---------------------------------------------------------------------------
# 1. ‏_entry_beats — הכלל עצמו, בלי מסד
# ---------------------------------------------------------------------------
def test_a_newer_local_stamp_beats_the_catalog():
    built = "2026-09-19T02:34:09Z"
    entry = {"course": {}, "meta": {"fetched_at": "2026-09-20T00:00:00Z"}}
    assert store_mod._entry_beats(entry, built) is True


def test_an_older_local_stamp_loses_to_the_catalog():
    built = "2026-09-19T02:34:09Z"
    entry = {"course": {}, "meta": {"fetched_at": "2026-09-01T17:09:41Z"}}
    assert store_mod._entry_beats(entry, built) is False


def test_an_equal_stamp_stays_local():
    """שוויון נשאר אצל המקומי — הקטלוג מנצח רק כשהוא חדש ממש.

    ‏זה לא עניין של טעם: ``tests/catalog_source.py`` בונה מסד שבו
    ‏``fetched_at`` הוא בדיוק ``built_at``, והוא **מסונן לסמסטר א'**. אילו
    הקטלוג היה מנצח בשוויון, כל בדיקה שמקבעת מספר קבוצות הייתה מקבלת פתאום
    את כל הסמסטרים.
    """
    built = "2026-09-19T02:34:09Z"
    entry = {"course": {}, "meta": {"fetched_at": built}}
    assert store_mod._entry_beats(entry, built) is True


def test_a_meta_without_a_stamp_loses():
    """שליפה שמעולם לא הצליחה מפסידה לקטלוג. נתון ידוע עדיף על כישלון."""
    entry = {"course": {}, "meta": {"fetched_at": "", "ok": False}}
    assert store_mod._entry_beats(entry, "2026-09-19T02:34:09Z") is False


def test_a_hand_written_entry_without_meta_wins():
    """הצורה שנכתבת ביד אין לה חותמת להשוות, ומי שכתב אותה התכוון שתיקרא."""
    entry = {"code": "61753", "name": "קורס", "groups": []}
    assert store_mod._entry_beats(entry, "2026-09-19T02:34:09Z") is True


# ---------------------------------------------------------------------------
# 2. המיזוג עצמו, דרך ‏Store
# ---------------------------------------------------------------------------
def test_a_stale_local_record_is_replaced_by_the_catalog(tmp_path):
    code = _some_shipped_code()
    built = _built_at()
    _write_db(tmp_path, {code: _local_entry(code, _shift(built, days=-30))})

    store = store_mod.Store(str(tmp_path), use_shipped=True, prefer_newer_catalog=True)
    meta = store.all_meta()[code]

    assert meta.source_url == shipped_catalog.SHIPPED_SOURCE
    assert meta.fetched_at == built
    course, _ = store.load_course(code)
    assert course is not None
    assert all(g.lecturer != "מרצה מקומי" for g in course.groups)


def test_a_fresher_local_record_survives_the_catalog(tmp_path):
    code = _some_shipped_code()
    built = _built_at()
    newer = _shift(built, days=+1)
    _write_db(tmp_path, {code: _local_entry(code, newer)})

    store = store_mod.Store(str(tmp_path), use_shipped=True, prefer_newer_catalog=True)
    meta = store.all_meta()[code]

    assert meta.source_url != shipped_catalog.SHIPPED_SOURCE
    assert meta.fetched_at == newer
    course, _ = store.load_course(code)
    assert course is not None
    assert any(g.lecturer == "מרצה מקומי" for g in course.groups)


def test_a_code_the_catalog_does_not_carry_survives_however_old(tmp_path):
    """קורס שנשלף ידנית ואינו בקטלוג אינו נמחק בגלל גיל. אין במה להחליף אותו."""
    code = "99999"
    assert code not in shipped_catalog.courses()
    old = _shift(_built_at(), days=-400)
    _write_db(tmp_path, {code: _local_entry(code, old)})

    store = store_mod.Store(str(tmp_path), use_shipped=True, prefer_newer_catalog=True)
    meta = store.all_meta()[code]

    assert meta.fetched_at == old
    assert meta.source_url != shipped_catalog.SHIPPED_SOURCE


def test_the_default_precedence_is_unchanged(tmp_path):
    """‏בלי ``prefer_newer_catalog`` המסד המקומי מנצח, גם כשהוא ישן מהקטלוג.

    ‏זה הגבול של השינוי כולו. ‏``use_shipped`` פירושו "הקטלוג ממלא את השאר",
    ‏ו-``tests/test_shipped_catalog.py`` מקבע את זה; העדפת החדש היא מדיניות
    תצוגה נפרדת שמופעלת במפורש. כל קורא אחר של ``Store`` — וגם קריאה עתידית
    שתישכח — מקבל את ההתנהגות הישנה.
    """
    code = _some_shipped_code()
    old = _shift(_built_at(), days=-30)
    _write_db(tmp_path, {code: _local_entry(code, old)})

    store = store_mod.Store(str(tmp_path), use_shipped=True)
    meta = store.all_meta()[code]

    assert meta.fetched_at == old
    assert meta.source_url != shipped_catalog.SHIPPED_SOURCE


def test_the_web_layer_turns_the_new_precedence_on(tmp_path):
    """‏שכבת הווב היא המקום היחיד שמדליק אותה — ושם זה חייב להיות דלוק,
    אחרת ``git pull`` שוב אינו מרענן אפליקציה מקומית."""
    from web import api as api_mod

    app = api_mod.create_app({"allow_network": False, "db_root": str(tmp_path)})
    with app.app_context():
        assert api_mod._store().prefer_newer_catalog is True
        assert api_mod._store_for("א").prefer_newer_catalog is True


def test_without_use_shipped_the_local_record_is_untouched(tmp_path):
    """‏refresh.py ו-reparse.py קוראים עם ``use_shipped=False``. זיהוי השינויים
    שלהם חייב לראות את המסד כמות שהוא, גם כשהוא ישן מהקטלוג."""
    code = _some_shipped_code()
    old = _shift(_built_at(), days=-30)
    _write_db(tmp_path, {code: _local_entry(code, old)})

    store = store_mod.Store(str(tmp_path), use_shipped=False)

    assert store.codes() == [code]
    assert store.all_meta()[code].fetched_at == old


# ---------------------------------------------------------------------------
# 3. מה שנגזר מזה: התווית והסף
# ---------------------------------------------------------------------------
def test_freshness_reports_the_catalog_build_time(tmp_path):
    """‏כשכל הקורסים מגיעים מהקטלוג, ``oldest`` הוא תאריך הבנייה — ולא חותמת
    ישנה שנשארה ב-``data/db``. זו בדיוק התווית שהראתה 2026-09-01."""
    built = _built_at()
    codes = sorted(shipped_catalog.courses())[:5]
    _write_db(
        tmp_path,
        {c: _local_entry(c, _shift(built, days=-(i + 3))) for i, c in enumerate(codes)},
    )

    store = store_mod.Store(str(tmp_path), use_shipped=True, prefer_newer_catalog=True)
    report = store.freshness()

    assert report["oldest"] == built
    assert report["newest"] == built


def test_the_stale_window_is_measured_against_the_catalog(tmp_path):
    """‏SLOTWISE_MAX_AGE_HOURS נמדד מול הקטלוג: אותו מסד בדיוק, שני חלונות,
    והגבול נופל על גיל **הקטלוג** ולא על גיל הרשומה המקומית."""
    built = _built_at()
    code = _some_shipped_code()
    _write_db(tmp_path, {code: _local_entry(code, _shift(built, days=-30))})

    store = store_mod.Store(str(tmp_path), use_shipped=True, prefer_newer_catalog=True)
    age = store_mod.age_hours_since(built)
    assert age is not None

    assert store.is_stale(code, age + 1.0) is False
    assert store.is_stale(code, max(age - 1.0, 0.0)) is True


# ---------------------------------------------------------------------------
# 4. ההגדרות מהסביבה — אותו קוד למקומי ולמתארח
# ---------------------------------------------------------------------------
def test_create_app_reads_the_freshness_window_from_the_environment(monkeypatch):
    """‏עד 2026-09-20 המשתנה הזה עבד רק דרך ``wsgi.py``, ולכן ``webapp.py``
    התעלם ממנו. שניהם קוראים ל-``create_app``, ולכן די לבדוק אותו."""
    from web import api as api_mod

    monkeypatch.setenv("SLOTWISE_MAX_AGE_HOURS", "72")
    app = api_mod.create_app()
    assert app.config["SLOTWISE"]["max_age_hours"] == 72.0


def test_an_explicit_override_still_beats_the_environment(monkeypatch):
    from web import api as api_mod

    monkeypatch.setenv("SLOTWISE_MAX_AGE_HOURS", "72")
    app = api_mod.create_app({"max_age_hours": 5.0})
    assert app.config["SLOTWISE"]["max_age_hours"] == 5.0


def test_a_malformed_freshness_window_raises_instead_of_defaulting(monkeypatch):
    """ברירת מחדל שקטה כאן גורמת לקטלוג ישן להיראות טרי. ‏DEPLOY.md מבטיח זריקה."""
    from web import api as api_mod

    monkeypatch.setenv("SLOTWISE_MAX_AGE_HOURS", "twentyfour")
    with pytest.raises(ValueError):
        api_mod.create_app()


def test_the_db_root_comes_from_the_environment(monkeypatch, tmp_path):
    from web import api as api_mod

    monkeypatch.setenv("SLOTWISE_DB_ROOT", str(tmp_path))
    app = api_mod.create_app()
    assert app.config["SLOTWISE"]["db_root"] == str(tmp_path)


def test_wsgi_pins_only_the_network_switch():
    """‏``wsgi.py`` אינו קורא עוד את הסביבה בעצמו — אחרת היו שני מקומות
    שקוראים את אותם משתנים, וזה בדיוק סוג ההיסט שהאיחוד בא למנוע."""
    import wsgi

    assert wsgi.build_settings() == {"allow_network": False}


# ---------------------------------------------------------------------------
# 5. המפעיל המקומי אומר איזה קטלוג הוא מגיש
# ---------------------------------------------------------------------------
def test_the_local_launcher_names_the_catalog_it_serves():
    """שרת שהופעל לפני ימים ממשיך להאזין על אותו פורט. בלי השורה הזאת אין
    דרך להשוות את מה שהדפדפן מראה למה שהתהליך הזה באמת טען."""
    import webapp

    lines = webapp.catalog_lines()
    joined = "\n".join(lines)

    assert str(shipped_catalog.CATALOG_PATH) in joined
    assert _built_at() in joined
    assert str(len(shipped_catalog.courses())) in joined
