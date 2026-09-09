# -*- coding: utf-8 -*-
"""
בדיקות שכבת האינטרנט — tests for the local Flask app (src/web/api.py + webapp.py).

הבדיקות רצות **לגמרי אופליין**: אין רשת, אין דפדפן, אין Playwright, אין scraping אמיתי.
המקורות היחידים הם:
    * data/db          — מסד הנתונים האמיתי של הסטודנט/ית (נקרא בלבד)
    * data/curriculum.json, data/profile.json — קבצים מקומיים, קריאה בלבד
    * Flask test client — בלי לפתוח פורט, בלי להאזין לרשת

כל בדיקה שעלולה *לשנות* משהו (התחלת סריקה) מקבלת עותק זמני של המסד ב-tmp_path,
וכל קריאה לסורק מוחלפת ב-stub שחוסם — כך ששום חלון דפדפן לא נפתח אף פעם.
בנוסף יש fixture אוטומטי שמחליף את ``sync_playwright`` בפונקציה שזורקת שגיאה,
כרשת ביטחון אחרונה.

עובדות אמיתיות שהבדיקות נשענות עליהן (נמדדו, לא נוחשו) — סמסטר א', תשפ"ז:
    6 קורסים · 27 קבוצות · 12 רכיבים בבחירה שלמה · 16 צירופים אפשריים · מינימום 5 ימים
    נעיצת 61753 הרצאה 271060330 → תקין ; נעיצת 271070330 → אין פתרון כלל

איך מריצים:
    python -m pytest tests -q

Technical notes:
    * Every file is opened with encoding="utf-8" (Windows would otherwise default
      to cp1255); sys.stdout is reconfigured defensively so a failing assertion
      that prints Hebrew does not itself blow up with UnicodeEncodeError.
    * The web module is written in parallel by another agent, so the app is
      located through a small discovery helper (factory name + optional keyword
      arguments are probed, never assumed). The *HTTP contract* from SPEC_WEB.md
      is asserted strictly — only the plumbing is flexible.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

# --------------------------------------------------------------------------
# הכנת הסביבה: src/ ושורש הפרויקט נכנסים ל-sys.path, בדיוק כמו ש-main.py עושה.
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for _path in (str(SRC), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass  # זרם שלא ניתן לשינוי (pytest capture / pipe) — ממשיכים בלי

DB_ROOT = ROOT / "data" / "db"
CURRICULUM_PATH = ROOT / "data" / "curriculum.json"
PROFILE_PATH = ROOT / "data" / "profile.json"
WEB_DIR = SRC / "web"
API_PATH = WEB_DIR / "api.py"
WEBAPP_PATH = ROOT / "webapp.py"

#: מקומות אפשריים לתבנית העמוד — הסוכן שכותב את ה-UI בוחר אחד מהם.
INDEX_CANDIDATES = (
    ROOT / "templates" / "index.html",
    WEB_DIR / "templates" / "index.html",
    SRC / "templates" / "index.html",
)

pytest.importorskip("flask", reason="Flask נדרש לשכבת האינטרנט (flask is required for the web layer)")

# --------------------------------------------------------------------------
# שכבת האינטרנט נכתבת במקביל על ידי סוכן אחר. כל עוד אין קובץ בכלל, הקובץ הזה
# מדלג בשלמותו במקום להפיל את חבילת הבדיקות הקיימת. ברגע שהקובץ נוצר — אם הוא
# לא נטען, זו שגיאה רועשת ולא דילוג.
# --------------------------------------------------------------------------
if not API_PATH.exists():  # pragma: no cover - נתיב זמני בלבד
    pytest.skip(
        "שכבת האינטרנט עדיין לא נכתבה (src/web/api.py missing) — "
        "הבדיקות האלה ירוצו ברגע שהקובץ ייווצר.",
        allow_module_level=True,
    )

# --------------------------------------------------------------------------
# עובדות אמיתיות מהמסד — כל הבדיקות מתייחסות אליהן.
# --------------------------------------------------------------------------
CODES = ["11069", "61753", "61756", "61757", "61832", "62027"]
TIED_TRIO = {"61756", "61757", "62027"}
TOTAL_GROUPS = 27
PICKS_PER_SCHEDULE = 12  # רכיב אחד לכל (קורס, סוג): 1+2+3+2+2+2
# ‏עודכן ב-2026-09-04 אחרי ריענון מלא: ראו ההערה ב-tests/test_attendance.py.
# תיקון הקבוצות המקושרות נכנס לנתונים רק בריענון, ופתח צירופים שהיו חסומים.
FEASIBLE_COUNT = 83
MIN_DAYS = 4
DAYS_USED = [1, 2, 3, 4]

TERM = "א"
YEAR = 'תשפ"ז'
CURRICULUM_SEMESTER = "5"

LECTURE = "הרצאה"
TUTORIAL = "תרגול"
LAB = "מעבדה"
PROJECT = "פרויקט"
COMBINED = 'שו"ת'

ALGO = "61753"
GOOD_PIN = "271060330"  # ד"ר קליימן ילנה — נשארת אפשרית
# ‏271070330 נראתה פעם כמבוי סתום, אבל זה היה **באג שלנו**: מסנן
# "אל תקשר קבוצה לעצמה" מחק קישור לגיטימי, כי בבראודה הרצאה ותרגול של אותה
# קבוצה חולקים מזהה. אחרי התיקון אין אף מבוי סתום בנתונים האמיתיים, ולכן
# בדיקות ה-viability עברו לנתונים סינתטיים שבנויים במפורש עם מבוי סתום.
VIABLE_PIN = "271070330"
GOOD_PIN_LECTURER = 'ד"ר קליימן ילנה'

HEBREW_RE = re.compile(r"[֐-׿]")


def _hebrew(text: object) -> bool:
    """האם יש בטקסט אות עברית אחת לפחות."""
    return bool(HEBREW_RE.search(str(text or "")))


# ==========================================================================
# איתור האפליקציה — flexible plumbing, strict contract
# ==========================================================================
_FACTORY_NAMES = (
    "create_app",
    "make_app",
    "build_app",
    "create_application",
    "app_factory",
    "get_app",
)
_DB_KWARGS = (
    "db_root",
    "db_dir",
    "db_path",
    "store_root",
    "store_dir",
    "store_path",
    "data_dir",
    "data_root",
    "db",
)
_IMPORT_ERRORS: list[str] = []


def _try_import(name: str):
    try:
        return importlib.import_module(name)
    except Exception as exc:  # pragma: no cover - נרשם ומדווח בהודעת השגיאה
        _IMPORT_ERRORS.append(f"{name}: {exc!r}")
        return None


def _load_from_file(path: Path, mod_name: str):
    if not path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location(mod_name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception as exc:  # pragma: no cover - נרשם ומדווח בהודעת השגיאה
        _IMPORT_ERRORS.append(f"{path.name}: {exc!r}")
        sys.modules.pop(mod_name, None)
        return None


def _api_modules() -> list[object]:
    """כל המודולים שעשויים להחזיק את הפונקציות של שכבת האינטרנט."""
    mods = []
    for name in ("web.api", "web", "webapp"):
        mod = sys.modules.get(name)
        if mod is not None and mod not in mods:
            mods.append(mod)
    if API_MODULE is not None and API_MODULE not in mods:
        mods.append(API_MODULE)
    return mods


def _discover_api_module():
    module = None
    if (WEB_DIR / "__init__.py").exists():
        module = _try_import("web.api")
    if module is None and WEBAPP_PATH.exists():
        module = _try_import("webapp")
    if module is None:
        module = _load_from_file(API_PATH, "_braude_web_api")
    return module


API_MODULE = _discover_api_module()
if API_MODULE is None:  # pragma: no cover - כשל טעינה אמיתי צריך להיות רועש
    raise ImportError(
        "לא הצלחתי לטעון את שכבת האינטרנט (could not import the web layer). "
        + " | ".join(_IMPORT_ERRORS)
    )


def _find_factory():
    """מאתרת את הפונקציה שבונה את אפליקציית Flask, בכל אחד מהמודולים."""
    for mod in _api_modules() + [API_MODULE]:
        for name in _FACTORY_NAMES:
            candidate = getattr(mod, name, None)
            if callable(candidate):
                return candidate
    return None


def _factory_params() -> dict:
    factory = _find_factory()
    if factory is None:
        return {}
    try:
        return dict(inspect.signature(factory).parameters)
    except (TypeError, ValueError):  # pragma: no cover
        return {}


def _factory_supports_overrides() -> bool:
    params = _factory_params()
    return "config" in params or any(name in params for name in _DB_KWARGS)


def _make_app(db_root: object = None, hooks: dict | None = None):
    """בונה אפליקציית Flask.

    אם המפעל מקבל הגדרות — מעבירים לו מסד נתונים זמני ונקודות הזרקה, כדי ששום
    בדיקה לא תיגע במסד האמיתי ושום סורק אמיתי לא ירוץ. אם לא — בונים כרגיל.
    """
    factory = _find_factory()
    if factory is None:
        existing = None
        for mod in _api_modules() + [API_MODULE]:
            existing = getattr(mod, "app", None)
            if existing is not None and hasattr(existing, "test_client"):
                break
            existing = None
        assert existing is not None, (
            "לא נמצאה פונקציה שבונה את האפליקציה (no create_app/app found in the web layer)"
        )
        return existing

    params = _factory_params()
    overrides: dict[str, object] = {}
    if db_root is not None:
        overrides["db_root"] = str(db_root)
    overrides.update(hooks or {})

    app = None
    if overrides:
        if "config" in params:
            try:
                app = factory(config=dict(overrides))
            except TypeError:  # pragma: no cover - חתימה אחרת מהצפוי
                app = None
        else:
            kwargs = {}
            if db_root is not None:
                for name in _DB_KWARGS:
                    if name in params:
                        kwargs[name] = str(db_root)
                        break
            if kwargs:
                try:
                    app = factory(**kwargs)
                except TypeError:  # pragma: no cover
                    app = None
    if app is None:
        app = factory()

    assert hasattr(app, "test_client"), (
        f"{getattr(factory, '__name__', factory)} לא החזירה אפליקציית Flask "
        "(the app factory did not return a Flask app)"
    )
    return app


# ==========================================================================
# עוזרים לקריאת תשובות
# ==========================================================================
def _payload(resp) -> dict:
    """גוף התשובה כ-dict, עם הודעת שגיאה קריאה אם זה לא JSON."""
    body = resp.get_data(as_text=True)
    data = resp.get_json(silent=True)
    assert isinstance(data, dict), (
        f"ציפיתי לאובייקט JSON; קיבלתי status={resp.status_code} body={body[:300]!r}"
    )
    return data


def _ok(resp) -> dict:
    assert resp.status_code == 200, (
        f"ציפיתי ל-200; קיבלתי {resp.status_code} — {resp.get_data(as_text=True)[:300]!r}"
    )
    data = _payload(resp)
    assert data.get("ok") is True, f"ok אינו True: {json.dumps(data, ensure_ascii=False)[:300]}"
    return data


def _client_error(resp, allowed=(400,)) -> dict:
    assert resp.status_code in allowed, (
        f"ציפיתי לאחד מ-{allowed}; קיבלתי {resp.status_code} — "
        f"{resp.get_data(as_text=True)[:300]!r}"
    )
    data = _payload(resp)
    assert data.get("ok") is False, "תשובת שגיאה חייבת לכלול ok:false"
    assert _hebrew(data.get("error")), (
        f"הודעת השגיאה חייבת להיות בעברית: {data.get('error')!r}"
    )
    _assert_no_traceback(resp)
    return data


def _assert_clean_response(resp) -> dict:
    """התשובה חוקית לפי החוזה: 200 עם ok:true, או 4xx עם ok:false והודעה בעברית.

    5xx, traceback או גוף שאינו JSON — כישלון.
    """
    assert resp.status_code < 500, (
        f"קלט של המשתמש לא יכול להפיל את השרת: {resp.status_code} — "
        f"{resp.get_data(as_text=True)[:300]!r}"
    )
    _assert_no_traceback(resp)
    data = _payload(resp)
    if resp.status_code == 200:
        assert data.get("ok") is True
    else:
        assert data.get("ok") is False
        assert _hebrew(data.get("error")), f"הודעת שגיאה בעברית חסרה: {data}"
    return data


def _assert_no_traceback(resp) -> None:
    """שום traceback לא דולף לדפדפן."""
    body = resp.get_data(as_text=True)
    for marker in (
        "Traceback (most recent call last)",
        'File "',
        ".py\", line",
        "werkzeug.exceptions",
        "<!DOCTYPE HTML PUBLIC",
    ):
        assert marker not in body, f"דלף פרט פנימי לתשובה: {marker!r}"


def _pick_list(data: dict, *keys: str) -> list:
    """שולפת את הרשימה מהתשובה — לפי מפתח מועדף, ואם אין, הרשימה הראשונה."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    for key, value in data.items():
        if key in {"reasons", "suggestions", "warnings", "log"}:
            continue
        if isinstance(value, list) and (not value or isinstance(value[0], dict)):
            return value
    raise AssertionError(
        f"לא נמצאה רשימה בתשובה תחת {keys}: {json.dumps(data, ensure_ascii=False)[:300]}"
    )


def _by_code(data: dict, *keys: str) -> dict[str, dict]:
    """קורסים לפי קוד — עובד גם אם התשובה היא רשימה וגם אם היא מילון."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict):
            return {str(k): v for k, v in value.items() if isinstance(v, dict)}
        if isinstance(value, list):
            return {str(c.get("code")): c for c in value if isinstance(c, dict)}
    items = _pick_list(data, *keys)
    return {str(c.get("code")): c for c in items if isinstance(c, dict)}


def _viability_node(data: dict, code: str, kind: str, group_id: str) -> dict:
    """קריאת viability בלי להניח אם יש שכבת 'סוג רכיב' באמצע."""
    viability = data.get("viability")
    assert isinstance(viability, dict), "התשובה חייבת לכלול viability"
    per_course = viability.get(code)
    assert isinstance(per_course, dict), f"אין viability לקורס {code}: {list(viability)[:8]}"
    node = per_course.get(kind, per_course)
    assert isinstance(node, dict), f"מבנה viability לא צפוי עבור {code}/{kind}"
    entry = node.get(group_id)
    assert isinstance(entry, dict), (
        f"אין viability לקבוצה {group_id} של {code}/{kind}: {list(node)[:8]}"
    )
    return entry


def _solve_body(**overrides) -> dict:
    body: dict[str, object] = {
        "codes": list(CODES),
        "semester": TERM,
        "year": YEAR,
        "target_days": 4,
        "top_n": 5,
    }
    body.update(overrides)
    return body


def _courses_body(codes=None, **extra) -> dict:
    # fetch_missing=False במפורש: ברירת המחדל בשרת היא True, ובלי הכיבוי הזה
    # הבדיקות היו מושכות מהאתר האמיתי של המכללה. אין רשת בבדיקות.
    body = {"codes": list(codes or CODES), "semester": TERM, "year": YEAR,
            "fetch_missing": False}
    body.update(extra)
    return body


# ==========================================================================
# רשת ביטחון: אף בדיקה לא תפתח דפדפן, לעולם.
# ==========================================================================
@pytest.fixture(autouse=True)
def _never_touch_the_network(monkeypatch):
    """רשת ביטחון שנייה: אף בדיקה לא פונה לאתר המכללה.

    מאז ש-fetch_missing הוא True כברירת מחדל, בקשה תמימה אחת יכולה לצאת
    לרשת. עדיף להתפוצץ בבדיקה מאשר להטריח את שרת המכללה.
    """
    import yedion_http

    def _refuse(*_a, **_k):  # pragma: no cover - נקרא רק אם משהו השתבש
        raise RuntimeError("no network in tests")

    monkeypatch.setattr(yedion_http.YedionHTTP, "open_session", _refuse, raising=False)
    monkeypatch.setattr(yedion_http.YedionHTTP, "fetch_course", _refuse, raising=False)
    monkeypatch.setattr(yedion_http.YedionHTTP, "fetch_catalog", _refuse, raising=False)


@pytest.fixture(autouse=True)
def _never_open_a_browser(monkeypatch):
    """מחליף את sync_playwright בכל מקום שהוא מיובא אליו."""

    def _refuse(*_args, **_kwargs):  # pragma: no cover - נקרא רק אם משהו השתבש
        raise RuntimeError("no browser in tests")

    try:
        import playwright.sync_api as pw_api

        monkeypatch.setattr(pw_api, "sync_playwright", _refuse, raising=False)
    except Exception:  # pragma: no cover - playwright לא מותקן
        pass
    try:
        import scraper as scraper_mod

        monkeypatch.setattr(scraper_mod, "sync_playwright", _refuse, raising=False)
    except Exception:  # pragma: no cover
        pass
    try:
        import webbrowser

        monkeypatch.setattr(webbrowser, "open", lambda *a, **k: False)
        monkeypatch.setattr(webbrowser, "open_new", lambda *a, **k: False, raising=False)
    except Exception:  # pragma: no cover
        pass
    yield


@pytest.fixture(scope="module")
def app():
    """אפליקציה אחת לכל הקובץ, מעל הקטלוג שנשלח עם הקוד.

    ‏db_root מצביע על הקטלוג ולא על ``data/db``: המאגר המקומי אינו במאגר
    הקוד, והאפליקציה הרצה כותבת אותו מחדש — ב-2026-09-09 מספר הקבוצות זז
    מתחת לבדיקות האלה בזמן שהן רצו. מול הקטלוג המספרים כאן יוצאים בדיוק
    כפי שנכתבו (27 קבוצות, ואותו פירוק לכל קורס) והם יציבים. ראו
    ``tests/catalog_source.py``.

    ‏cwd נשאר בשורש: נתיבים יחסיים אחרים (תוכנית לימודים, פרופיל) עדיין
    נקראים משם.
    """
    from catalog_source import catalog_db_dir  # noqa: PLC0415

    previous = os.getcwd()
    os.chdir(ROOT)
    try:
        yield _make_app(db_root=catalog_db_dir())
    finally:
        os.chdir(previous)


@pytest.fixture
def client(app):
    with app.test_client() as test_client:
        yield test_client


# ==========================================================================
# 0. עוגן: המסד האמיתי הוא באמת מה שהבדיקות מניחות
# ==========================================================================
def test_the_catalog_is_the_one_the_tests_assume():
    """אם מקור הנתונים השתנה — עדיף שהבדיקה הזו תיפול ראשונה, ובבירור.

    ‏שומרת על הקטלוג ולא על ``data/db``, כי מאז 2026-09-09 זה המקור שכל
    הקובץ הזה קורא. ההבדל אינו טכני: ``data/db`` נכתב מחדש בכל רענון,
    ולכן קנרית שמצביעה עליו מצייצת על כל שינוי בידיעון ולא על שינוי אצלנו.
    ``data/catalog.jsonl`` נמצא במאגר הקוד, ולכן נפילה כאן פירושה שמישהו
    בנה אותו מחדש — וזה בדיוק מה שכדאי לדעת עליו.
    """
    from catalog_source import catalog_courses  # noqa: PLC0415

    everything = catalog_courses()
    # תת-קבוצה ולא שוויון: הקטלוג נושא את כל המחלקות, ומה שחייב להתקיים
    # הוא שהקורסים של הסטודנט/ית שבבדיקות נמצאים בו.
    missing = [c for c in CODES if c not in everything]
    assert not missing, f"חסרים מהמאגר: {missing}"
    courses = {c: everything[c] for c in CODES}
    assert sum(len(c.groups) for c in courses.values()) == TOTAL_GROUPS
    semesters = {m.semester for c in courses.values() for g in c.groups for m in g.meetings}
    assert semesters == {TERM}


# ==========================================================================
# 1. /api/bootstrap
# ==========================================================================
def test_bootstrap_returns_ok(client):
    data = _ok(client.get("/api/bootstrap"))
    assert isinstance(data, dict) and data


def test_bootstrap_lists_the_eight_semesters_with_year_and_term(client):
    expected = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))["semesters"]
    data = _ok(client.get("/api/bootstrap"))
    semesters = _pick_list(data, "semesters", "semester_list", "curriculum_semesters")
    assert len(semesters) == len(expected) == 8, (
        f"ציפיתי ל-{len(expected)} סמסטרים מתוך curriculum.json, קיבלתי {len(semesters)}"
    )
    blob = json.dumps(semesters, ensure_ascii=False)
    for entry in semesters:
        assert isinstance(entry, dict)
        keys = {k.lower() for k in entry}
        assert any("year" in k or "שנה" in k for k in keys), f"אין שדה שנה: {entry}"
        assert any("term" in k or "sem" in k for k in keys), f"אין שדה סמסטר: {entry}"
    assert TERM in blob and "ב" in blob


def test_bootstrap_carries_the_profile_defaults(client):
    """ברירת המחדל באה מ-profile.json: שנה ג', סמסטר א' — כלומר סמסטר 5 בתוכנית."""
    student = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))["student"]
    want_semester = str(student["curriculum_semester"])
    want_term = str(student["term"])
    assert (want_semester, want_term) == (CURRICULUM_SEMESTER, TERM)  # שמירה על העוגן

    data = _ok(client.get("/api/bootstrap"))
    defaults = None
    for key in ("profile", "defaults", "student", "preferences"):
        if isinstance(data.get(key), dict) and data[key]:
            defaults = data[key]
            break
    blob = json.dumps(defaults if defaults is not None else data, ensure_ascii=False)
    assert (
        re.search(rf'"(curriculum_)?semester"\s*:\s*"?{want_semester}"?', blob)
        or f'"{want_semester}"' in blob
    ), f"ברירת המחדל צריכה להיות סמסטר {want_semester}: {blob[:400]}"
    assert want_term in blob, f"ברירת המחדל היא סמסטר {want_term}': {blob[:400]}"


def test_bootstrap_reports_freshness_and_catalog_size(client):
    data = _ok(client.get("/api/bootstrap"))
    blob = json.dumps(data, ensure_ascii=False)
    assert re.search(r"fresh|age|updated|stale|עודכנ", blob), "אין מידע על טריות הנתונים"
    numbers = re.findall(r'"(?:catalog_size|catalog_count|count)"\s*:\s*(\d+)', blob)
    sizes = [int(n) for n in numbers]
    nested = data.get("catalog")
    if isinstance(nested, dict):
        for key in ("size", "count", "courses"):
            value = nested.get(key)
            if isinstance(value, int):
                sizes.append(value)
    assert any(size >= 100 for size in sizes), (
        f"גודל הקטלוג האמיתי הוא 571 קורסים; לא נמצא מספר סביר: {blob[:400]}"
    )


def test_bootstrap_says_no_scrape_is_running_and_never_mentions_a_password(client):
    data = _ok(client.get("/api/bootstrap"))
    blob = json.dumps(data, ensure_ascii=False)
    assert re.search(r'"[a-z_]*running"\s*:\s*(true|false)', blob), (
        f"צריך לדעת אם סריקה רצה כרגע: {blob[:400]}"
    )
    for forbidden in ("password", "passwd", "סיסמה", "סיסמא"):
        assert forbidden not in blob.lower(), f"אסור לטפל בסיסמאות: {forbidden}"


# ==========================================================================
# 2. /api/semester/<sem>/courses
# ==========================================================================
def test_semester_courses_contains_the_tied_trio(client):
    data = _ok(client.get(f"/api/semester/{CURRICULUM_SEMESTER}/courses"))
    courses = _by_code(data, "courses", "items", "results")
    for code in sorted(TIED_TRIO):
        assert code in courses, f"קורס {code} חסר בסמסטר {CURRICULUM_SEMESTER}: {sorted(courses)}"


def test_semester_courses_marks_the_trio_as_tied_to_each_other(client):
    data = _ok(client.get(f"/api/semester/{CURRICULUM_SEMESTER}/courses"))
    courses = _by_code(data, "courses", "items", "results")
    for code in sorted(TIED_TRIO):
        entry = courses[code]
        tied = entry.get("tied_with")
        assert isinstance(tied, list) and tied, f"{code} חייב להיות מסומן כצמוד: {entry}"
        assert set(tied) == TIED_TRIO - {code}, f"קשירה שגויה ל-{code}: {tied}"


def test_semester_courses_carries_the_curriculum_fields(client):
    data = _ok(client.get(f"/api/semester/{CURRICULUM_SEMESTER}/courses"))
    courses = _by_code(data, "courses", "items", "results")
    entry = courses["61756"]
    for field in ("code", "name", "credits"):
        assert field in entry, f"שדה {field} חסר: {entry}"
    assert entry["credits"] == 5.0
    assert _hebrew(entry["name"])
    for field in ("he", "te", "ma", "pr"):
        assert field in entry, f"שדות השעות חסרים ({field}): {entry}"
    assert isinstance(entry.get("prereq"), list)
    assert "11060" in entry["prereq"]


def _a_code_with_no_data() -> str | None:
    """קוד קורס שקיים בתוכנית אבל אין לו נתונים במאגר, או ``None``.

    נבחר דינמית ולא מקובע: פעם זה היה 61759, ואז הרענון היומי משך גם אותו
    והבדיקה נשברה. הרענון מושך היום את כל הקורסים שנפתחים, ולכן ייתכן
    לגמרי שאין אף קוד כזה — ואז אין מה לבדוק וצריך לדלג.
    """
    import curriculum as curriculum_mod
    import store as store_mod

    stored = set(store_mod.Store(str(DB_ROOT)).load_all())
    curr = curriculum_mod.load_curriculum(str(CURRICULUM_PATH))
    for entry in curriculum_mod.semester_courses(curr, CURRICULUM_SEMESTER):
        code = entry.get("code")
        if code and code not in stored:
            return code
    return None


def test_semester_courses_flags_offered_and_has_data(client):
    data = _ok(client.get(f"/api/semester/{CURRICULUM_SEMESTER}/courses"))
    courses = _by_code(data, "courses", "items", "results")
    assert courses["61756"].get("has_data") is True, "61756 נמצא במסד — has_data חייב להיות true"
    assert courses["61756"].get("offered") is True, "61756 מופיע בקטלוג — offered חייב להיות true"
    # has_data חייב להיות בוליאני אמיתי לכל קורס — זה מה שהממשק נשען עליו.
    assert all(isinstance(c.get("has_data"), bool) for c in courses.values())
    empty = _a_code_with_no_data()
    if empty and empty in courses:
        assert courses[empty].get("has_data") is False


def test_semester_courses_rejects_an_unknown_semester(client):
    resp = client.get("/api/semester/99/courses")
    _client_error(resp, allowed=(400, 404))


# ==========================================================================
# 3. /api/catalog/search
# ==========================================================================
def test_catalog_search_ranks_an_exact_code_first(client):
    data = _ok(client.get("/api/catalog/search?q=61753&limit=10"))
    results = _pick_list(data, "results", "courses", "items", "matches")
    assert results, "חיפוש קוד מדויק חייב להחזיר תוצאה"
    assert str(results[0].get("code")) == ALGO, f"הקוד המדויק חייב להיות ראשון: {results[:3]}"
    assert _hebrew(results[0].get("name"))


def test_catalog_search_matches_a_hebrew_name_substring(client):
    data = _ok(client.get("/api/catalog/search?q=%D7%94%D7%A1%D7%AA%D7%91%D7%A8%D7%95%D7%AA&limit=20"))
    codes = [str(r.get("code")) for r in _pick_list(data, "results", "courses", "items", "matches")]
    assert "61832" in codes, f'חיפוש "הסתברות" חייב למצוא את 61832: {codes}'


def test_catalog_search_finds_the_algorithms_course_by_name(client):
    data = _ok(client.get("/api/catalog/search", query_string={"q": "אלגוריתמים", "limit": 20}))
    results = _pick_list(data, "results", "courses", "items", "matches")
    codes = [str(r.get("code")) for r in results]
    assert ALGO in codes
    assert codes[0] == ALGO, f"התאמה מלאה לשם חייבת לעלות לראש: {codes[:4]}"


def test_catalog_search_marks_courses_inside_and_outside_the_curriculum(client):
    inside = _ok(client.get("/api/catalog/search", query_string={"q": "61753", "limit": 5}))
    entry = _pick_list(inside, "results", "courses", "items", "matches")[0]
    assert entry.get("in_curriculum") is True
    assert str(entry.get("curriculum_semester")) == "4", (
        f"61753 שייך לסמסטר 4 בתוכנית: {entry}"
    )

    outside = _ok(client.get("/api/catalog/search", query_string={"q": "הסתברות", "limit": 20}))
    by_code = {str(r.get("code")): r for r in _pick_list(outside, "results", "courses", "items")}
    assert "51709" in by_code, f"ציפיתי למצוא גם קורס מחוץ לתוכנית: {sorted(by_code)}"
    assert by_code["51709"].get("in_curriculum") is False


def test_catalog_search_respects_the_limit(client):
    data = _ok(client.get("/api/catalog/search", query_string={"q": "אלגוריתמים", "limit": 3}))
    results = _pick_list(data, "results", "courses", "items", "matches")
    assert 0 < len(results) <= 3


def test_catalog_search_with_an_empty_query_does_not_crash(client):
    resp = client.get("/api/catalog/search?q=&limit=10")
    assert resp.status_code in (200, 400), resp.status_code
    _assert_no_traceback(resp)
    if resp.status_code == 200:
        assert _pick_list(_payload(resp), "results", "courses", "items", "matches") == []


# ==========================================================================
# 4. /api/courses
# ==========================================================================
@pytest.fixture(scope="module")
def courses_payload(app):
    with app.test_client() as test_client:
        resp = test_client.post("/api/courses", json=_courses_body())
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    data = resp.get_json(silent=True)
    assert isinstance(data, dict) and data.get("ok") is True
    return data


def test_courses_returns_all_six_courses(courses_payload):
    courses = _by_code(courses_payload, "courses", "items", "results")
    assert sorted(courses) == CODES


def test_courses_returns_twenty_seven_groups_in_total(courses_payload):
    courses = _by_code(courses_payload, "courses", "items", "results")
    total = sum(len(c.get("groups") or []) for c in courses.values())
    assert total == TOTAL_GROUPS, f"ציפיתי ל-27 קבוצות, קיבלתי {total}"


def test_courses_group_counts_match_the_real_data(courses_payload):
    courses = _by_code(courses_payload, "courses", "items", "results")
    expected = {"11069": 2, "61753": 4, "61756": 7, "61757": 6, "61832": 5, "62027": 3}
    actual = {code: len(courses[code].get("groups") or []) for code in expected}
    assert actual == expected


def test_courses_every_meeting_has_day_start_end_and_semester(courses_payload):
    courses = _by_code(courses_payload, "courses", "items", "results")
    meetings = 0
    for code, course in courses.items():
        for group in course.get("groups") or []:
            for meeting in group.get("meetings") or []:
                meetings += 1
                for field in ("day", "start", "end", "semester"):
                    assert field in meeting, f"{code}/{group.get('group_id')}: חסר {field}"
                assert 1 <= meeting["day"] <= 6
                assert 0 <= meeting["start"] < meeting["end"] <= 24 * 60
                assert meeting["semester"] == TERM, (
                    f"מפגש מסמסטר {meeting['semester']!r} זלג פנימה — חייב להיות א'"
                )
    assert meetings > 0


def test_courses_groups_carry_kind_lecturer_and_group_id(courses_payload):
    courses = _by_code(courses_payload, "courses", "items", "results")
    kinds_by_course = {
        code: {g.get("kind") for g in course.get("groups") or []}
        for code, course in courses.items()
    }
    assert kinds_by_course["11069"] == {COMBINED}
    assert kinds_by_course[ALGO] == {LECTURE, TUTORIAL}
    assert kinds_by_course["61756"] == {LECTURE, TUTORIAL, PROJECT}
    assert kinds_by_course["61757"] == {LECTURE, LAB}
    lecture = next(g for g in courses[ALGO]["groups"] if g["group_id"] == GOOD_PIN)
    assert lecture["kind"] == LECTURE
    assert lecture["lecturer"] == GOOD_PIN_LECTURER


def test_courses_linked_to_survives_for_the_algorithms_lectures(courses_payload):
    courses = _by_code(courses_payload, "courses", "items", "results")
    lectures = [g for g in courses[ALGO]["groups"] if g.get("kind") == LECTURE]
    assert {g["group_id"] for g in lectures} == {GOOD_PIN, VIABLE_PIN}
    for group in lectures:
        linked = group.get("linked_to")
        assert isinstance(linked, list) and linked, f"linked_to אבד בדרך: {group}"
        # לא שוויון מדויק: רשימת הקבוצות הצמודות היא נתון של המכללה והיא משתנה.
        # ב-2026-09-01 נוספה שם 271060330/2 — תרגול שטרם פורסם לו מועד, בדיוק
        # כמו קבוצות סמסטר ב' שראינו קודם. מה שחייב להתקיים הוא שכל התרגולים
        # שכן קיימים בדף מופיעים ברשימה.
        assert {f"{GOOD_PIN}/1", f"{VIABLE_PIN}/1"} <= set(linked)
        assert all(str(lid).startswith((GOOD_PIN, VIABLE_PIN)) for lid in linked)


def test_courses_reports_a_code_that_has_no_data_without_crashing(client):
    empty = _a_code_with_no_data()
    if empty is None:
        pytest.skip("כל קורסי הסמסטר כבר במאגר — אין קוד בלי נתונים לבדוק")
    resp = client.post("/api/courses", json=_courses_body(codes=["61756", empty]))
    assert resp.status_code in (200, 400), resp.get_data(as_text=True)[:300]
    _assert_no_traceback(resp)
    if resp.status_code == 400:
        _client_error(resp)
        return
    data = _payload(resp)
    not_offered = data.get("not_offered")
    assert not_offered, "קורס בלי נתונים חייב לחזור ב-not_offered"
    blob = json.dumps(not_offered, ensure_ascii=False)
    assert empty in blob
    assert _hebrew(blob), "חייבת להיות סיבה בעברית"


def test_courses_rejects_a_malformed_json_body(client):
    resp = client.post(
        "/api/courses", data="{ this is not json".encode("utf-8"), content_type="application/json"
    )
    _client_error(resp)


def test_courses_rejects_an_unknown_course_code(client):
    resp = client.post("/api/courses", json=_courses_body(codes=["99999"]))
    assert resp.status_code < 500, "קוד לא מוכר הוא טעות משתמש, לא קריסת שרת"
    _assert_no_traceback(resp)
    if resp.status_code == 200:
        blob = json.dumps(_payload(resp).get("not_offered"), ensure_ascii=False)
        assert "99999" in blob
    else:
        _client_error(resp, allowed=(400, 404))


# ==========================================================================
# 5. /api/solve
# ==========================================================================
@pytest.fixture(scope="module")
def solve_payload(app):
    with app.test_client() as test_client:
        resp = test_client.post("/api/solve", json=_solve_body())
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    data = resp.get_json(silent=True)
    assert isinstance(data, dict) and data.get("ok") is True
    return data


def test_solve_finds_every_feasible_combination(solve_payload):
    assert solve_payload.get("feasible_count") == FEASIBLE_COUNT


def test_solve_reports_five_as_the_minimum_number_of_days(solve_payload):
    assert solve_payload.get("min_days") == MIN_DAYS


def test_solve_says_four_days_is_reachable(solve_payload):
    """‏4 ימים **כן** אפשריים — וזה תיקון של טעות קודמת, לא שינוי דרישה.

    כל עוד מסנן ה"אל תקשר קבוצה לעצמה" מחק קישורים לגיטימיים, נראה היה
    שהמינימום הוא 5. אחרי תיקון הפרסר המינימום הוא 4, בלי שום ויתור על
    חובת נוכחות.
    """
    assert solve_payload.get("target_days") == 4
    assert solve_payload.get("target_reachable") is True
    assert solve_payload.get("min_days") == 4


def test_solve_says_five_days_is_reachable(client):
    """יעד רחב מהמינימום תמיד בר-השגה."""
    data = _ok(client.post("/api/solve", json=_solve_body(target_days=5)))
    assert data.get("target_reachable") is True
    assert data.get("min_days") == MIN_DAYS


def test_solve_returns_schedules_with_the_full_shape(solve_payload):
    schedules = _pick_list(solve_payload, "schedules")
    assert schedules, "חייבות לחזור מערכות"
    best = schedules[0]
    for field in ("score", "days_count", "days", "gap_minutes", "breakdown", "picks"):
        assert field in best, f"שדה {field} חסר במערכת: {sorted(best)}"
    assert best["days_count"] == MIN_DAYS
    assert sorted(best["days"]) == DAYS_USED
    assert set(best["breakdown"]) >= {"lecturer", "days", "gaps", "compactness"}
    assert isinstance(best["gap_minutes"], int) and best["gap_minutes"] >= 0


def test_solve_picks_cover_every_course_component(solve_payload):
    best = _pick_list(solve_payload, "schedules")[0]
    picks = best["picks"]
    assert len(picks) == PICKS_PER_SCHEDULE, f"ציפיתי ל-12 רכיבים, קיבלתי {len(picks)}"
    assert {p["code"] for p in picks} == set(CODES)
    for pick in picks:
        for field in ("code", "kind", "group_id", "meetings"):
            assert field in pick, f"שדה {field} חסר בבחירה: {pick}"
        assert pick["meetings"], f"בחירה בלי מפגשים: {pick}"
        for meeting in pick["meetings"]:
            assert {"day", "start", "end"} <= set(meeting)


def test_solve_respects_top_n(client):
    data = _ok(client.post("/api/solve", json=_solve_body(top_n=3)))
    assert len(_pick_list(data, "schedules")) <= 3
    assert data.get("feasible_count") == FEASIBLE_COUNT, "top_n לא משנה את מספר האפשרויות"


def test_solve_honours_a_pin(client):
    body = _solve_body(pinned={ALGO: {LECTURE: GOOD_PIN}}, top_n=10)
    data = _ok(client.post("/api/solve", json=body))
    schedules = _pick_list(data, "schedules")
    assert schedules, "נעיצה חוקית חייבת להשאיר פתרונות"
    for schedule in schedules:
        chosen = [
            p for p in schedule["picks"] if p["code"] == ALGO and p["kind"] == LECTURE
        ]
        assert len(chosen) == 1
        assert chosen[0]["group_id"] == GOOD_PIN, (
            f"הנעיצה לא כובדה: {chosen[0]['group_id']}"
        )


def test_solve_pin_narrows_the_result_set_to_the_pinned_group(client):
    """נעיצה אמיתית: בלי נעיצה שתי הקבוצות מופיעות, ואיתה — רק אחת."""
    loose = _ok(client.post("/api/solve", json=_solve_body(top_n=10)))
    loose_ids = {
        pick["group_id"]
        for schedule in _pick_list(loose, "schedules")
        for pick in schedule["picks"]
        if pick["code"] == "61756" and pick["kind"] == TUTORIAL
    }
    assert len(loose_ids) > 1, f"הנתונים אמורים לאפשר יותר מתרגול אחד ל-61756: {loose_ids}"

    body = _solve_body(pinned={"61756": {TUTORIAL: "271060310/1"}}, top_n=10)
    data = _ok(client.post("/api/solve", json=body))
    schedules = _pick_list(data, "schedules")
    assert schedules
    for schedule in schedules:
        chosen = [p for p in schedule["picks"] if p["code"] == "61756" and p["kind"] == TUTORIAL]
        assert [p["group_id"] for p in chosen] == ["271060310/1"], (
            f"הנעיצה לא כובדה: {chosen}"
        )
    assert data.get("feasible_count") == 14, (
        f"נעיצת תרגול 271060310/1 משאירה 14 צירופים; קיבלתי {data.get('feasible_count')}"
    )


def test_solve_with_no_possible_schedule_returns_200_with_reasons(client):
    """חוסר פתרון הוא תשובה, לא שגיאה.

    האילוץ נבנה כאן במפורש (אין שיעור לפני 20:00) ולא נשען על "קבוצה
    שמובילה למבוי סתום" בנתונים האמיתיים: אחרי תיקון הפרסר אין בהם אף
    מבוי סתום, ובדיקה שנשענת על תכונה מקרית של הנתונים נשברת בכל רענון.
    """
    body = _solve_body(earliest=20 * 60)
    resp = client.post("/api/solve", json=body)
    assert resp.status_code == 200, (
        "חוסר פתרון הוא תשובה לגיטימית, לא שגיאת HTTP — "
        f"קיבלתי {resp.status_code}"
    )
    data = _ok(resp)
    assert data.get("feasible_count") == 0
    assert _pick_list(data, "schedules") == []
    reasons = data.get("reasons")
    assert isinstance(reasons, list) and reasons, "חייב להיות הסבר למה אין פתרון"
    assert any(_hebrew(r) for r in reasons)
    _assert_no_traceback(resp)


def test_solve_marks_a_group_not_viable_when_a_constraint_kills_it(client):
    """‏viability מסמן קבוצה כחסומה כשאילוץ באמת חוסם אותה.

    ‏271070330 נחשבה פעם למבוי סתום. זה היה באג בפרסר, לא תכונה של
    הנתונים — ולכן האילוץ כאן נוצר במפורש.
    """
    data = _ok(client.post("/api/solve", json=_solve_body(earliest=13 * 60)))
    viability = data.get("viability") or {}
    flags = [
        entry.get("ok")
        for kinds in viability.values()
        for groups in kinds.values()
        for entry in groups.values()
    ]
    assert flags, "viability חייב להיות מחושב"
    assert any(flag is False for flag in flags), (
        "עם 'אין שיעור לפני 13:00' חייבות להיות קבוצות חסומות"
    )


def test_solve_marks_the_good_group_as_viable(solve_payload):
    entry = _viability_node(solve_payload, ALGO, LECTURE, GOOD_PIN)
    assert entry.get("ok") is True


#: המבוי הסתום היחיד שנותר בנתונים האמיתיים אחרי תיקון הפרסר.
#: ‏61832 תרגול 271070210/1 מותר רק עם הרצאת יהלום (א 12:50-15:50), והשילוב
#: הזה אינו ניתן להשלמה. תשעת ה"מבויים" שדווחו קודם היו כולם תוצר של מסנן
#: שמחק קישורים לגיטימיים — זה האמיתי היחיד.
#: ‏ריק, ובכוונה. עד 2026-09-04 ישב כאן ("61832", "תרגול", "271070210/1"),
#: והוא היה שריד לנתונים שנפרסרו לפני תיקון הקבוצות המקושרות: הרצאת
#: ‏271060310/1 לא הצביעה על המזהה של עצמה, ולכן התרגול ההוא נראה בלתי-שביר.
#: אחרי ריענון מלא מהידיעון, עם הפרסר המתוקן, אין אף מבוי סתום.
KNOWN_DEAD_ENDS: set[tuple[str, str, str]] = set()


def test_no_phantom_dead_ends_appear(solve_payload):
    """אין מבויים סתומים, וגם לא אמורים לצוץ כאלה.

    ההיסטוריה כאן שווה זכירה: לפני תיקון הפרסר היו תשעה מבויים, וכולם היו
    שקריים. אחריו נשאר אחד, שנראה אמיתי — ואחרי ריענון מלא מהידיעון עם
    הפרסר המתוקן התברר שגם הוא היה שריד: הרצאת 271060310/1 של 61832 לא
    הצביעה על המזהה של עצמה, ובבראודה הרצאה ותרגול חולקים מזהה קבוצה.

    הבדיקה שומרת עכשיו על כיוון אחד בלבד — שלא יצוצו מבויים מדומים — וזה
    הכיוון שכל התקלות כאן היו בו ממילא.
    """
    viability = solve_payload["viability"]
    dead = {
        (code, kind, gid)
        for code, kinds in viability.items()
        for kind, groups in kinds.items()
        for gid, entry in groups.items()
        if entry.get("ok") is False
    }
    assert dead == KNOWN_DEAD_ENDS, f"מבויים סתומים בלתי צפויים: {dead ^ KNOWN_DEAD_ENDS}"


def test_solve_computes_viability_for_every_group(solve_payload):
    viability = solve_payload["viability"]
    assert set(viability) == set(CODES), f"חסרים קורסים ב-viability: {sorted(viability)}"
    counted = 0
    for per_course in viability.values():
        for value in per_course.values():
            assert isinstance(value, dict)
            if value and all(isinstance(v, dict) for v in value.values()):
                counted += len(value)
            else:  # מבנה שטוח: {group_id: {...}}
                counted += 1
    assert counted == TOTAL_GROUPS, f"ציפיתי ל-27 בדיקות היתכנות, קיבלתי {counted}"


def test_solve_accepts_a_lecturer_ranking(client):
    body = _solve_body(ranked={ALGO: [GOOD_PIN_LECTURER]}, top_n=3)
    data = _ok(client.post("/api/solve", json=body))
    schedules = _pick_list(data, "schedules")
    assert schedules
    assert schedules[0].get("lecturer_total", 0) >= 1
    assert schedules[0].get("lecturer_hits", 0) >= 1


def test_solve_hard_constraint_that_kills_everything_returns_200(client):
    """earliest=20:00 פוסל הכול — עדיין 200 עם הסבר, לא 500."""
    resp = client.post("/api/solve", json=_solve_body(earliest=1200))
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    data = _ok(resp)
    assert data.get("feasible_count") == 0
    assert _pick_list(data, "schedules") == []
    assert data.get("reasons"), "חייב להיות הסבר"


def test_solve_accepts_blocked_windows_and_forbid_friday(client):
    body = _solve_body(blocked=[[6, 0, 1440]], forbid_friday=True, top_n=2)
    resp = client.post("/api/solve", json=body)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    data = _ok(resp)
    # אין שיעורים ביום שישי בנתונים האמיתיים — החסימה לא אמורה לשנות כלום.
    assert data.get("feasible_count") == FEASIBLE_COUNT

    # ...אבל חסימה שכן פוגעת חייבת להשפיע: כל 16 הצירופים משתמשים ביום ראשון,
    # ולכן חסימת יום ראשון חייבת לאפס אותם. בלי הבדיקה הזאת שרת שמתעלם
    # לגמרי מ-blocked היה עובר את הבדיקה הזאת בירוק.
    real = client.post("/api/solve", json=_solve_body(blocked=[[1, 0, 1440]], top_n=2))
    assert real.status_code == 200, real.get_data(as_text=True)[:300]
    blocked_data = _ok(real)
    assert blocked_data.get("feasible_count") == 0, (
        "חסימת יום ראשון כולו חייבת לפסול את כל הצירופים — נראה ש-blocked לא נלקח בחשבון"
    )
    assert _pick_list(blocked_data, "schedules") == []
    reasons = blocked_data.get("reasons")
    assert reasons, "כשאין פתרון חייב להגיע הסבר"
    assert _hebrew(json.dumps(reasons, ensure_ascii=False)), (
        f"ההסבר חייב להיות בעברית: {reasons}"
    )


def test_solve_rejects_a_malformed_json_body(client):
    resp = client.post(
        "/api/solve", data='{"codes": [', content_type="application/json"
    )
    data = _client_error(resp)
    assert "traceback" not in json.dumps(data, ensure_ascii=False).lower()


def test_solve_rejects_an_unknown_course_code(client):
    """קוד לא מוכר נדחה בבירור — או 400, או 200 שאומר במפורש שאין לו נתונים.

    מה שאסור: 5xx, traceback, או מערכת שמתעלמת מהקורס בשקט.
    """
    resp = client.post("/api/solve", json=_solve_body(codes=["61756", "99999"]))
    data = _assert_clean_response(resp)
    if resp.status_code != 200:
        assert resp.status_code in (400, 404, 422)
        return
    blob = json.dumps(data.get("not_offered"), ensure_ascii=False)
    assert "99999" in blob, f"קוד לא מוכר חייב להיות מדווח: {json.dumps(data, ensure_ascii=False)[:300]}"
    assert _hebrew(blob), "חייבת להיות סיבה בעברית"
    assert _pick_list(data, "schedules") == [], "אסור להחזיר מערכת שמתעלמת מהקורס"


def test_solve_does_not_silently_ignore_a_pin_to_a_group_that_does_not_exist(client):
    resp = client.post(
        "/api/solve", json=_solve_body(pinned={ALGO: {LECTURE: "no-such-group"}})
    )
    data = _assert_clean_response(resp)
    if resp.status_code == 200:
        assert data.get("feasible_count") == 0, (
            "נעיצה לקבוצה לא קיימת לא יכולה להחזיר מערכות כאילו כלום"
        )
    else:
        assert resp.status_code in (400, 404, 422)


@pytest.mark.parametrize(
    "label,body",
    [
        ("codes אינו רשימה", {"codes": "61756", "semester": TERM}),
        ("target_days אינו מספר", {"codes": ["61756"], "target_days": "מחר"}),
        ("pinned אינו אובייקט", {"codes": ["61756"], "pinned": "x"}),
        ("blocked בצורה שגויה", {"codes": ["61756"], "blocked": [["x"]]}),
        ("ranked אינו אובייקט", {"codes": ["61756"], "ranked": [1, 2]}),
        ("top_n שלילי", {"codes": ["61756"], "top_n": -3}),
        ("גוף ריק לגמרי", {}),
    ],
)
def test_solve_survives_garbage_input(client, label, body):
    """קלט משובש הוא טעות משתמש — תשובה נקייה, לעולם לא 500 ולא traceback."""
    _assert_clean_response(client.post("/api/solve", json=body))


def test_solve_with_no_codes_does_not_crash(client):
    resp = client.post("/api/solve", json=_solve_body(codes=[]))
    assert resp.status_code in (200, 400, 422), resp.status_code
    _assert_no_traceback(resp)


def test_solve_is_fast_enough_to_run_on_every_interaction(client):
    started = time.perf_counter()
    _ok(client.post("/api/solve", json=_solve_body(top_n=5)))
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0, f"פתרון + היתכנות ארכו {elapsed:.2f} שניות — איטי מדי לממשק חי"


# ==========================================================================
# 6. /api/scrape — בלי דפדפן, לעולם
# ==========================================================================
_RELEASE: dict[str, object] = {"event": None}


def _wait_for_release(timeout: float = 30.0) -> None:
    event = _RELEASE.get("event")
    if isinstance(event, threading.Event):
        event.wait(timeout)


class _StubScraper:
    """תחליף ל-BraudeScraper: לא נוגע ברשת, וחוסם עד שהבדיקה משחררת."""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        def _method(*args, **kwargs):
            _wait_for_release()
            if "html" in name:
                return "<html></html>"
            return None

        return _method


def _blocking_worker(*args, **kwargs):
    _wait_for_release()
    return 0


class _StubStream:
    def readline(self):
        _wait_for_release()
        return ""

    def read(self, *args):
        _wait_for_release()
        return ""

    def __iter__(self):
        _wait_for_release()
        return iter(())

    def close(self):
        return None


class _StubPopen:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.returncode = None
        self.pid = -1
        self.stdout = _StubStream()
        self.stderr = _StubStream()
        self.stdin = None

    def poll(self):
        event = _RELEASE.get("event")
        if isinstance(event, threading.Event) and event.is_set():
            self.returncode = 0
        return self.returncode

    def wait(self, timeout=None):
        _wait_for_release()
        self.returncode = 0
        return 0

    def communicate(self, *args, **kwargs):
        _wait_for_release()
        self.returncode = 0
        return ("", "")

    def terminate(self):
        self.returncode = -1

    kill = terminate


_WORKER_NAMES = {
    "BraudeScraper",
    "run_scrape",
    "_run_scrape",
    "do_scrape",
    "_do_scrape",
    "scrape_worker",
    "_scrape_worker",
    "scrape_job",
    "_scrape_job",
    "scrape_task",
    "_scrape_task",
    "scrape_once",
    "_scrape_once",
    "run_scraper",
    "_run_scraper",
    "background_scrape",
    "_background_scrape",
    "perform_scrape",
    "_perform_scrape",
    "run_refresh",
    "_run_refresh",
}
_WORKER_HINT = re.compile(r"(worker|job|task|thread|background|perform|execute|once)")


@pytest.fixture
def scrape_stub(monkeypatch, app):
    """מחליף כל מה שיכול באמת לסרוק, ומחזיר את האירוע שמשחרר את הסריקה."""
    release = threading.Event()
    _RELEASE["event"] = release

    try:
        import scraper as scraper_mod

        monkeypatch.setattr(scraper_mod, "BraudeScraper", _StubScraper, raising=False)
        monkeypatch.setattr(scraper_mod, "main", _blocking_worker, raising=False)
    except Exception:  # pragma: no cover
        pass
    try:
        import refresh as refresh_mod

        for name in ("main", "cmd_refresh", "run_refresh", "scrape_courses"):
            if hasattr(refresh_mod, name):
                monkeypatch.setattr(refresh_mod, name, _blocking_worker)
    except Exception:  # pragma: no cover
        pass

    monkeypatch.setattr(subprocess, "Popen", _StubPopen)
    monkeypatch.setattr(subprocess, "run", _blocking_worker)

    view_functions = list(getattr(app, "view_functions", {}).values())
    for module in _api_modules():
        for name, obj in list(vars(module).items()):
            if not callable(obj):
                continue
            if any(obj is view for view in view_functions):
                continue
            lowered = name.lower()
            replacement = None
            if name in _WORKER_NAMES:
                replacement = _StubScraper if name == "BraudeScraper" else _blocking_worker
            elif (
                inspect.isfunction(obj)
                and ("scrape" in lowered or "refresh" in lowered)
                and _WORKER_HINT.search(lowered)
                and not re.search(r"(status|state|log|phase|payload|json|render)", lowered)
            ):
                replacement = _blocking_worker
            if replacement is not None:
                monkeypatch.setattr(module, name, replacement, raising=False)

    try:
        yield release
    finally:
        release.set()
        _RELEASE["event"] = None
        time.sleep(0.05)  # לתת ל-thread החסום להתעורר ולסיים


@pytest.fixture
def scrape_client(tmp_path, app):
    """לקוח שמצביע על עותק זמני של המסד — כדי ששום סריקה לא תיגע במסד האמיתי.

    אם המפעל מציע נקודת הזרקה לסורק (``scrape_runner``) — מזריקים לתוכה תחליף
    חוסם. גם ככה אין דפדפן, אבל ככה גם אין ספק.
    """
    target = app
    if _factory_supports_overrides():
        tmp_db = tmp_path / "db"
        shutil.copytree(DB_ROOT, tmp_db)
        hooks = {"scrape_runner": _blocking_worker, "reparse_runner": _blocking_worker}
        target = _make_app(db_root=tmp_db, hooks=hooks)
    with target.test_client() as test_client:
        try:
            yield test_client
        finally:
            # אחרי שהבדיקה שחררה את הסורק — להמתין שהמצב יתנקה, כדי שלא יישאר
            # thread חי אחרי סוף הבדיקה.
            deadline = time.time() + 5.0
            while time.time() < deadline:
                status = test_client.get("/api/scrape/status").get_json(silent=True)
                if not isinstance(status, dict) or not status.get("running"):
                    break
                time.sleep(0.05)


def test_scrape_status_is_pollable_and_has_no_credentials(client):
    data = _ok(client.get("/api/scrape/status"))
    assert isinstance(data.get("running"), bool)
    assert isinstance(data.get("log"), list)
    assert "phase" in data
    blob = json.dumps(data, ensure_ascii=False).lower()
    for forbidden in ("password", "passwd", "סיסמה"):
        assert forbidden not in blob


def test_scrape_start_refuses_a_second_concurrent_run(scrape_client, scrape_stub):
    first = scrape_client.post("/api/scrape/start", json={})
    assert first.status_code in (200, 202), first.get_data(as_text=True)[:300]
    assert _payload(first).get("ok") is True

    running = False
    deadline = time.time() + 5.0
    while time.time() < deadline:
        status = _payload(scrape_client.get("/api/scrape/status"))
        if status.get("running"):
            running = True
            break
        time.sleep(0.02)
    assert running, "אחרי start הסטטוס חייב לדווח שסריקה רצה"

    second = scrape_client.post("/api/scrape/start", json={})
    assert second.status_code in (400, 409, 423, 429), (
        f"סריקה שנייה חייבת להידחות; קיבלתי {second.status_code}"
    )
    data = _payload(second)
    assert data.get("ok") is False
    assert _hebrew(data.get("error")), f"הודעת הסירוב חייבת להיות בעברית: {data}"
    _assert_no_traceback(second)


def test_scrape_start_never_accepts_a_password(scrape_client, scrape_stub):
    resp = scrape_client.post("/api/scrape/start", json={"password": "hunter2"})
    assert resp.status_code < 500
    blob = resp.get_data(as_text=True)
    assert "hunter2" not in blob, "אסור להחזיר שום דבר שנשלח כסיסמה"


# ==========================================================================
# 6ב. /api/reparse — בנייה מחדש מ-data/raw, בלי רשת ובלי דפדפן
# ==========================================================================
def _reparse_recorder(calls: list):
    """runner מזויף לפענוח מחדש: רושם את ה-argv, כותב שורת לוג ומחזיר 0.

    הרישום הוא ההוכחה ששום פענוח אמיתי לא רץ על המסד של הסטודנט/ית.
    """

    def _runner(*args, **kwargs):
        argv = kwargs.get("argv")
        emit = kwargs.get("emit")
        for arg in args:
            if argv is None and isinstance(arg, (list, tuple)):
                argv = list(arg)
            elif emit is None and callable(arg):
                emit = arg
        calls.append(list(argv or []))
        if callable(emit):
            emit("פענוח מדומה — בדיקה בלבד")
        return 0

    return _runner


@pytest.fixture
def reparse_client(tmp_path):
    """לקוח עם מסד זמני ועם runner מוזרק — כדי ששום reparse אמיתי לא ירוץ."""
    if not _factory_supports_overrides():
        pytest.skip(
            "למפעל אין נקודת הזרקה ל-reparse — לא מריצים פענוח אמיתי על המסד האמיתי"
        )
    calls: list[list[str]] = []
    tmp_db = tmp_path / "db"
    shutil.copytree(DB_ROOT, tmp_db)
    app = _make_app(db_root=tmp_db, hooks={"reparse_runner": _reparse_recorder(calls)})
    with app.test_client() as test_client:
        yield test_client, calls


def test_reparse_rebuilds_the_db_without_network(reparse_client):
    """POST /api/reparse מחזיר 200 עם תוצאה בעברית — ומכבד את נקודת ההזרקה."""
    test_client, calls = reparse_client
    data = _ok(test_client.post("/api/reparse", json={"semester": TERM}))

    assert data.get("exit_code") == 0, f"ציפיתי לקוד יציאה 0: {data.get('exit_code')!r}"
    assert _hebrew(data.get("message")), f"ההודעה חייבת להיות בעברית: {data.get('message')!r}"
    assert isinstance(data.get("log"), list), "חייב לחזור יומן (log) כרשימה"
    assert isinstance(data.get("db"), dict), "חייבת לחזור תמונת מסד מעודכנת"

    assert len(calls) == 1, f"ה-runner המוזרק חייב להיקרא בדיוק פעם אחת: {calls}"
    assert calls[0] == ["--semester", TERM], (
        f"argv לא צפוי — ייתכן שרץ פענוח אמיתי במקום המוזרק: {calls[0]}"
    )


def test_reparse_rejects_an_invalid_semester(reparse_client):
    """סמסטר לא חוקי נדחה ב-400 בעברית — ובלי להריץ שום דבר."""
    test_client, calls = reparse_client
    _client_error(test_client.post("/api/reparse", json={"semester": "ז"}))
    assert not calls, f"סמסטר לא תקין חייב להיפסל לפני הרצת הפענוח: {calls}"


# ==========================================================================
# 7. הדף עצמו — RTL, בלי סיסמאות, בלי אינטרנט
# ==========================================================================
def _index_on_disk() -> Path | None:
    for candidate in INDEX_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _served_index(client) -> str:
    """ה-HTML ש-``GET /`` מחזיר בפועל — אחרי אימות שזה **העמוד האמיתי**.

    בלי האימות הזה כל בדיקות הממשק היו יכולות לרוץ מול עמוד-חלופה זעיר
    ("השרת עובד") ולהיות ירוקות בזמן שהממשק האמיתי כלל אינו מגיע לדפדפן.
    """
    disk = _index_on_disk()
    assert disk is not None, "אין index.html על הדיסק"
    on_disk = disk.read_text(encoding="utf-8")

    resp = client.get("/")
    assert resp.status_code == 200, resp.status_code
    html = resp.get_data(as_text=True)

    for marker in ("/static/style.css", "/static/app.js"):
        assert marker in on_disk, f"{disk} חייב להפנות ל-{marker}"
        assert marker in html, (
            f"‏GET / לא מגיש את {disk} — חסר {marker} "
            f"({len(html)} תווים בתשובה מול {len(on_disk)} בקובץ). "
            "כנראה נתיב תבניות/סטטיים שגוי במפעל האפליקציה."
        )
    assert len(html) >= len(on_disk) // 2, (
        f"‏GET / החזיר {len(html)} תווים בלבד במקום את {disk} ({len(on_disk)} תווים)"
    )
    return html


def test_index_page_is_hebrew_rtl(client):
    if _index_on_disk() is None:
        pytest.skip("templates/index.html עדיין לא נכתב על ידי סוכן הממשק")
    html = _served_index(client)
    assert 'dir="rtl"' in html
    assert 'lang="he"' in html
    assert _hebrew(html)


def test_index_page_has_no_password_field_and_no_internet(client):
    if _index_on_disk() is None:
        pytest.skip("templates/index.html עדיין לא נכתב על ידי סוכן הממשק")
    html = _served_index(client)
    lowered = html.lower()
    for marker in ('type="password"', "type='password'", "type=password"):
        assert marker not in lowered, "אסור לאסוף סיסמאות בממשק"
    external = [
        url
        for url in re.findall(r'(?:src|href)\s*=\s*["\']([^"\']+)', html)
        if url.startswith(("http://", "https://", "//"))
    ]
    assert not external, f"האפליקציה חייבת לעבוד בלי אינטרנט; נמצאו מקורות חיצוניים: {external}"


def test_local_assets_referenced_by_the_page_are_served(client):
    """כל קובץ סטטי שהעמוד מבקש חייב להיות זמין מקומית — בלי 404 ובלי CDN."""
    if _index_on_disk() is None:
        pytest.skip("templates/index.html עדיין לא נכתב על ידי סוכן הממשק")
    html = _served_index(client)
    links = [
        url
        for url in re.findall(r'(?:src|href)\s*=\s*["\']([^"\']+)', html)
        if url.startswith("/static/")
    ]
    assert links, "העמוד חייב לטעון קבצים מ-/static (גיליון סגנון וקוד JS)"
    for url in links:
        resp = client.get(url)
        assert resp.status_code == 200, f"הקובץ {url} אינו מוגש (קיבלתי {resp.status_code})"

    # במפורש, גם אם ההפניות בעמוד ישתנו: שני הקבצים האלה חייבים להיות מוגשים.
    for url in ("/static/app.js", "/static/style.css"):
        resp = client.get(url)
        assert resp.status_code == 200, (
            f"{url} אינו מוגש (קיבלתי {resp.status_code}) — הממשק לא ייטען בדפדפן"
        )


def test_the_launcher_listens_on_localhost_only():
    """webapp.py חייב להאזין ל-127.0.0.1 בלבד — אף פעם לא 0.0.0.0."""
    if not WEBAPP_PATH.exists():
        pytest.skip("webapp.py עדיין לא נכתב")
    source = WEBAPP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    bad = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "0.0.0.0" in node.value
        and id(node) not in docstrings
    ]
    assert not bad, f"אסור להאזין על 0.0.0.0: {bad}"
    assert "127.0.0.1" in source, "כתובת ההאזנה חייבת להיות 127.0.0.1"


def test_unknown_api_path_is_a_clean_404(client):
    resp = client.get("/api/no-such-endpoint")
    assert resp.status_code == 404
    _assert_no_traceback(resp)
    data = resp.get_json(silent=True)
    if isinstance(data, dict):
        assert data.get("ok") is False
        assert _hebrew(data.get("error"))
