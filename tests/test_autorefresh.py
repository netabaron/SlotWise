# -*- coding: utf-8 -*-
"""
בדיקות לגילוי קורסים ולמסד הנתונים המתרענן — tests for src/discovery.py + src/store.py.

הבדיקות רצות **לגמרי אופליין**: אין רשת, אין דפדפן, אין Playwright, אין schtasks.
מקורות הנתונים היחידים הם:
    * tests/fixtures/real_yedion/catalog_all_courses.html — עמוד קטלוג אמיתי (1172 קורסים)
    * tests/fixtures/real_yedion/single_group.html        — עמוד קורס בודד (לא קטלוג)
    * HTML סינתטי שנבנה כאן, בדיוק לפי צורת השורות של העמוד האמיתי
    * data/curriculum.json — קובץ מקומי, נטען לקריאה בלבד

כל בדיקה של ``Store`` משתמשת ב-``tmp_path`` של pytest, כך ששום דבר כאן לא נוגע
ב-data/db האמיתי של הסטודנט/ית.

איך מריצים:
    python -m pytest tests -q

שני העקרונות שהקובץ הזה שומר עליהם (מתוך docs/SPEC_AUTOREFRESH.md):
    1. הידיעון הוא מקור האמת לגבי מה נפתח — לא curriculum.json. קורס שחוזר
       מסמסטר קודם הוא מקרה **תקין**, ולכן קוד שאינו בתוכנית הלימודים חייב
       להישאר ניתן לבחירה.
    2. הנתונים חייבים להתרענן, והמשתמש/ת חייב/ת לדעת מתי הם עודכנו לאחרונה —
       ולכן חישוב הטריות (staleness) ואיתור השינויים נבדקים כאן לעומק.

Technical notes:
    * Every file is opened with encoding="utf-8" (Windows would otherwise default
      to cp1255); sys.stdout is reconfigured defensively so a failing assertion
      that prints Hebrew does not itself blow up with UnicodeEncodeError.
    * No test depends on dict ordering, and no test reads the wall clock except
      through ``iso_ago`` — every timestamp used by an assertion is explicit.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# --------------------------------------------------------------------------
# הכנת הסביבה: להוסיף את src/ ל-sys.path בדיוק כמו ש-main.py עושה.
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURES = ROOT / "tests" / "fixtures" / "real_yedion"
CATALOG_FIXTURE = FIXTURES / "catalog_all_courses.html"
SINGLE_GROUP_FIXTURE = FIXTURES / "single_group.html"
CURRICULUM_PATH = ROOT / "data" / "curriculum.json"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):
        pass  # זרם שלא ניתן לשינוי (pytest capture / pipe) — ממשיכים בלי

# --------------------------------------------------------------------------
# שני המודולים הנבדקים נכתבים במקביל על ידי סוכנים אחרים. כל עוד הם אינם
# קיימים, הקובץ הזה מדלג בשלמותו במקום להפיל את חבילת הבדיקות הקיימת.
# ברגע ששני הקבצים נוצרים — כל הבדיקות כאן רצות באמת.
# --------------------------------------------------------------------------
_MISSING = [name for name in ("store", "discovery") if not (SRC / f"{name}.py").exists()]
if _MISSING:  # pragma: no cover - נתיב זמני בלבד
    pytest.skip(
        "src/" + ".py, src/".join(_MISSING) + ".py not written yet — "
        "these tests activate automatically once the modules exist.",
        allow_module_level=True,
    )

import discovery  # noqa: E402  (import after the sys.path surgery — intentional)
import store as store_module  # noqa: E402
from curriculum import all_course_codes, load_curriculum  # noqa: E402
from discovery import parse_catalog  # noqa: E402
from models import (  # noqa: E402
    KIND_LAB,
    KIND_LECTURE,
    KIND_TUTORIAL,
    Course,
    Group,
    Meeting,
)
from store import DEFAULT_MAX_AGE_HOURS, SCHEMA_VERSION, CourseMeta, Store  # noqa: E402

# פונקציות אופציונליות: הספק שלהן נקבע על ידי הסוכן שכותב את המודול, ולכן
# מאתרים אותן בשני המקומות הסבירים ומדלגים בבירור אם אינן קיימות.
_filter_catalog = getattr(discovery, "filter_catalog", None)
_annotate = getattr(discovery, "annotate_with_curriculum", None)
_compare_catalogs = getattr(discovery, "compare_catalogs", None) or getattr(
    store_module, "compare_catalogs", None
)

needs_compare = pytest.mark.skipif(
    _compare_catalogs is None,
    reason="compare_catalogs is not exported by discovery.py or store.py",
)
needs_filter = pytest.mark.skipif(
    _filter_catalog is None, reason="discovery.filter_catalog is not implemented"
)
needs_annotate = pytest.mark.skipif(
    _annotate is None, reason="discovery.annotate_with_curriculum is not implemented"
)


# ==========================================================================
# 0. עוזרים — helpers
# ==========================================================================
YEAR_HE = 'תשפ"ז'
YEAR_GREG = "2027"
SEMESTER = "א"
SOURCE = "https://info.braude.ac.il/yedion/fireflyweb.aspx?prgname=S_LOOK_FOR_NOSE&arguments=-N61753"

# זמנים בדקות מחצות, בדיוק כמו במודל (08:30 -> 510).
T0830, T1000, T1015, T1200, T1345 = 510, 600, 615, 720, 825


def sha1_of(text: str) -> str:
    """content_sha1 אמיתי — sha1 של ה-HTML הגולמי, מפתח זיהוי השינויים."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def iso_ago(hours: float = 0.0, seconds: float = 0.0) -> str:
    """חותמת ISO-8601 ב-UTC עם Z, המתארת נקודה בעבר ביחס לרגע הקריאה.

    כל בדיקת טריות בונה את החותמת שלה כאן ומיד אחר כך שואלת את ה-Store,
    כך שהשעון האמיתי משפיע רק במיקרו-שניות — ולכן גבול של שנייה שלמה בטוח.
    """
    moment = datetime.now(timezone.utc) - timedelta(hours=hours, seconds=seconds)
    return moment.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def mk_meta(**overrides) -> CourseMeta:
    """CourseMeta מלא עם ערכי ברירת מחדל סבירים; כל שדה ניתן לדריסה."""
    values = dict(
        fetched_at=iso_ago(),
        year=YEAR_HE,
        year_gregorian=YEAR_GREG,
        semester=SEMESTER,
        source_url=SOURCE,
        content_sha1=sha1_of("baseline"),
        group_count=1,
        warnings=[],
        ok=True,
    )
    values.update(overrides)
    return CourseMeta(**values)


def mk_meeting(day: int = 2, start: int = T1015, end: int = T1200, **kw) -> Meeting:
    kw.setdefault("room", "5203")
    kw.setdefault("building", "")
    kw.setdefault("semester", SEMESTER)
    return Meeting(day=day, start=start, end=end, **kw)


def mk_group(
    group_id: str = "6175301",
    kind: str = KIND_LECTURE,
    lecturer: str = "פרופ' וולקוביץ' זאב",
    meetings=None,
    linked_to=None,
    note: str = "",
    code: str = "61753",
) -> Group:
    return Group(
        course_code=code,
        group_id=group_id,
        kind=kind,
        lecturer=lecturer,
        meetings=list(meetings) if meetings is not None else [mk_meeting()],
        linked_to=list(linked_to) if linked_to is not None else [],
        note=note,
    )


def mk_course(code: str = "61753", groups=None, name: str = "אלגוריתמים") -> Course:
    return Course(
        code=code,
        name=name,
        credits=3.5,
        groups=list(groups) if groups is not None else [mk_group()],
        tied_with=[],
    )


def new_store(tmp_path: Path, name: str = "db") -> Store:
    """Store חדש מתחת ל-tmp_path — לעולם לא data/db האמיתי."""
    return Store(str(tmp_path / name))


def find_file(root: Path, filename: str) -> Path | None:
    """מאתר קובץ לפי שם בכל מקום מתחת ל-root (מיקום מדויק הוא פרט מימוש)."""
    matches = sorted(root.rglob(filename))
    return matches[0] if matches else None


def catalog_html(rows, *, with_button: bool = True) -> str:
    """בונה עמוד קטלוג סינתטי בדיוק בצורת העמוד האמיתי (div.row / div.col).

    ``rows`` הוא רצף של (code, name, status) — מחרוזות HTML גולמיות, כך שאפשר
    להזריק ``&quot;`` ו-``&nbsp;`` ולבדוק את הניקוי.
    """
    parts = [
        '<!DOCTYPE html><html lang="he" dir="rtl"><head><meta charset="utf-8">',
        "<title>חיפוש קורסים במערכת - רשימת נושאים</title></head><body>",
        '<div class="Table container fcontainer">',
        # שורת כותרת — col0 אינו ספרות ואין בה כפתור, ולכן חייבת להידחות.
        '<div class="row"><div class="col">קוד נושא</div><div class="col">שם נושא</div>'
        '<div class="col">סטטוס</div><div class="col">חיפוש קורס במערכת השעות</div>'
        '<div class="col">הערות</div></div>',
    ]
    for code, name, status in rows:
        if with_button:
            cell = (
                '<button type="button" class="btn btn-primary rounded g-mb-12" '
                'data-progname="S_LOOK_FOR_NOSE" data-arguments="-N'
                + str(code).strip()
                + '">חיפוש קורס במערכת השעות</button>'
            )
        else:
            cell = "&nbsp;"
        parts.append(
            '<div class="row">'
            f'<div class="col">{code}</div>'
            f'<div class="col">{name}</div>'
            f'<div class="col">{status}</div>'
            f'<div class="col">{cell}</div>'
            '<div class="col">&nbsp;</div>'
            "</div>"
        )
    parts.append("</div></body></html>")
    return "".join(parts)


def flatten_report(result) -> list[str]:
    """ממפה כל צורת-החזרה סבירה של compare_catalogs לרשימת מחרוזות.

    צורת המכולה היא פרט מימוש (רשימת תיאורים בעברית או dict של added/removed/
    renamed). מה שחייב להיבדק הוא ש**המידע** מדווח, ולכן הבדיקות מחפשות קודים
    ושמות בתוך הטקסט המשוטח.
    """
    if result is None:
        return []
    if isinstance(result, dict):
        out: list[str] = []
        for key, value in result.items():
            if isinstance(value, (list, tuple, set)):
                out.extend(f"{key}: {item}" for item in value)
            elif isinstance(value, dict):
                out.extend(f"{key}: {k} {v}" for k, v in value.items())
            elif value:
                out.append(f"{key}: {value}")
        return out
    if isinstance(result, (list, tuple, set)):
        return [str(item) for item in result]
    return [str(result)]


# --------------------------------------------------------------------------
# פיקסצ'רים — fixtures
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def catalog_page() -> str:
    return CATALOG_FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def real_catalog(catalog_page: str) -> dict:
    courses, _warnings = parse_catalog(catalog_page)
    return courses


@pytest.fixture(scope="module")
def curriculum() -> dict:
    return load_curriculum(CURRICULUM_PATH)


@pytest.fixture()
def store(tmp_path: Path) -> Store:
    return new_store(tmp_path)


# שמות שנשלפו מהקטלוג האמיתי — כולל גרשיים ופסקות, בדיוק כפי שהם בעמוד.
KNOWN_NAMES: dict[str, str] = {
    "271030": "מתמטיקה ב'",
    "651112": "סמינר מחקר - המשך",
    "211164": "פייתון לכלכלנים",
    "93567": "לילדים ונוערDBT",
}
NAMES_WITH_QUOTES: dict[str, str] = {
    "385111": '"השלישי על ארבע"',
    "93420": 'הפרעת אישיות גבולית(הא"ג)',
    "142226": 'סמינר מרחיב דעת ב"נושאים במדעי המחשב"',
}
NAMES_WITH_PARENS: dict[str, str] = {
    "93218": "Dyadic Developmental Psychotherapy (DDP)",
    "389009": "הדרכה לפרקטיקום א' (התפתחותית)",
}


# ==========================================================================
# 1. parse_catalog — הקטלוג האמיתי
# ==========================================================================
class TestParseRealCatalog:
    """העמוד האמיתי עולה בקריאה אחת (SPEC_AUTOREFRESH §"VERIFIED")."""

    def test_returns_pair_of_courses_and_warnings(self, catalog_page: str):
        result = parse_catalog(catalog_page)
        assert isinstance(result, tuple) and len(result) == 2
        courses, warnings = result
        assert isinstance(courses, dict)
        assert isinstance(warnings, list)
        assert all(isinstance(w, str) for w in warnings)

    def test_exactly_1172_courses(self, real_catalog: dict):
        # המספר אומת מול העמוד השמור — כל סטייה ממנו היא רגרסיה בפרסר.
        assert len(real_catalog) == 1172

    def test_every_code_is_four_to_seven_digits(self, real_catalog: dict):
        bad = [c for c in real_catalog if not re.fullmatch(r"\d{4,7}", c)]
        assert bad == []

    def test_every_name_is_non_empty(self, real_catalog: dict):
        empty = sorted(c for c, v in real_catalog.items() if not v.get("name", "").strip())
        assert empty == []

    def test_every_entry_has_name_and_status_keys(self, real_catalog: dict):
        missing = sorted(
            code for code, value in real_catalog.items() if not {"name", "status"} <= set(value)
        )
        assert missing == []

    def test_known_pair_math_b(self, real_catalog: dict):
        # הזוג הידוע מ-GROUND_TRUTH §"row shape".
        assert real_catalog["271030"]["name"] == "מתמטיקה ב'"

    @pytest.mark.parametrize("code,name", sorted(KNOWN_NAMES.items()))
    def test_known_names_round_trip(self, real_catalog: dict, code: str, name: str):
        assert real_catalog[code]["name"] == name

    @pytest.mark.parametrize("code,name", sorted(NAMES_WITH_QUOTES.items()))
    def test_names_with_quotes_round_trip_intact(self, real_catalog: dict, code: str, name: str):
        # &quot; חייב לעבור html.unescape ולחזור כגרש כפול אמיתי.
        got = real_catalog[code]["name"]
        assert got == name
        assert '"' in got

    @pytest.mark.parametrize("code,name", sorted(NAMES_WITH_PARENS.items()))
    def test_names_with_parentheses_round_trip_intact(
        self, real_catalog: dict, code: str, name: str
    ):
        got = real_catalog[code]["name"]
        assert got == name
        assert "(" in got and ")" in got

    def test_no_stray_nbsp_or_entities_survive_cleaning(self, real_catalog: dict):
        dirty = sorted(
            code
            for code, value in real_catalog.items()
            if " " in value["name"] or "&quot;" in value["name"] or "&amp;" in value["name"]
        )
        assert dirty == []

    def test_names_are_stripped(self, real_catalog: dict):
        unstripped = sorted(c for c, v in real_catalog.items() if v["name"] != v["name"].strip())
        assert unstripped == []

    def test_real_page_statuses_are_all_nilmad(self, real_catalog: dict):
        # בעמוד ההתייחסות נצפה סטטוס אחד בלבד: "נלמד".
        assert {v["status"] for v in real_catalog.values()} == {"נלמד"}


# ==========================================================================
# 2. parse_catalog — מקרי קצה
# ==========================================================================
class TestParseCatalogEdgeCases:
    def test_unknown_status_is_kept_and_warned_about(self):
        # SPEC: "Treat any other value as 'listed but check it', keep it, and record it".
        html_page = catalog_html(
            [
                ("61753", "אלגוריתמים", "נלמד"),
                ("61754", "מבני נתונים", "טרם נקבע"),
            ]
        )
        courses, warnings = parse_catalog(html_page)

        assert "61754" in courses, "שורה עם סטטוס לא מוכר לא נזרקת בשקט"
        assert courses["61754"]["name"] == "מבני נתונים"
        assert courses["61754"]["status"] == "טרם נקבע"
        assert len(courses) == 2

        joined = " | ".join(warnings)
        assert warnings, "סטטוס לא מוכר חייב להיות מדווח כאזהרה"
        assert "61754" in joined or "טרם נקבע" in joined

    def test_known_status_alone_produces_no_status_warning(self):
        html_page = catalog_html([("61753", "אלגוריתמים", "נלמד")])
        courses, warnings = parse_catalog(html_page)
        assert list(courses) == ["61753"]
        assert not [w for w in warnings if "טרם" in w]

    def test_single_course_page_returns_empty_dict_and_warning(self):
        # עמוד קורס בודד אינו קטלוג — התוצאה הנכונה היא dict ריק, לא חריגה.
        html_page = SINGLE_GROUP_FIXTURE.read_text(encoding="utf-8")
        courses, warnings = parse_catalog(html_page)
        assert courses == {}
        assert warnings, "עמוד שאינו קטלוג חייב להסביר את עצמו באזהרה"

    def test_single_course_page_does_not_raise(self):
        html_page = SINGLE_GROUP_FIXTURE.read_text(encoding="utf-8")
        parse_catalog(html_page)  # אם זה זורק — הבדיקה נכשלת מעצמה

    def test_empty_html_returns_empty_dict_and_warning(self):
        courses, warnings = parse_catalog("")
        assert courses == {}
        assert warnings

    def test_rows_without_search_button_are_skipped(self):
        # ההגדרה: שורת קורס היא כזו שיש בה גם קוד תקין וגם כפתור S_LOOK_FOR_NOSE.
        html_page = catalog_html([("61753", "אלגוריתמים", "נלמד")], with_button=False)
        courses, _warnings = parse_catalog(html_page)
        assert courses == {}

    @pytest.mark.parametrize("code", ["123", "12345678", "6175א", ""])
    def test_codes_outside_four_to_seven_digits_are_skipped(self, code: str):
        html_page = catalog_html([(code, "לא קורס", "נלמד")])
        courses, _warnings = parse_catalog(html_page)
        assert code not in courses
        assert courses == {}

    def test_entities_and_nbsp_are_cleaned_in_synthetic_rows(self):
        html_page = catalog_html(
            [("&nbsp;61753", '&nbsp;מבוא ל&quot;מדעי המחשב&quot;&nbsp;', "&nbsp;נלמד")]
        )
        courses, _warnings = parse_catalog(html_page)
        assert courses["61753"]["name"] == 'מבוא ל"מדעי המחשב"'
        assert courses["61753"]["status"] == "נלמד"

    def test_header_row_is_not_a_course(self):
        courses, _warnings = parse_catalog(catalog_html([]))
        assert courses == {}


# ==========================================================================
# 3. Store — שמירה וטעינה (round-trip)
# ==========================================================================
class TestStoreRoundTrip:
    def test_schema_version_is_a_positive_int(self):
        assert isinstance(SCHEMA_VERSION, int) and SCHEMA_VERSION >= 1

    def test_default_max_age_is_about_a_day(self):
        assert DEFAULT_MAX_AGE_HOURS == pytest.approx(24.0)

    def test_save_then_load_returns_equal_course(self, store: Store):
        course = mk_course(
            groups=[
                mk_group(
                    "6175301",
                    KIND_LECTURE,
                    "פרופ' וולקוביץ' זאב",
                    [mk_meeting(2, T1015, T1200), mk_meeting(4, T0830, T1000)],
                    linked_to=["6175302"],
                    note="שיעור א' - מסלול בוקר",
                ),
                mk_group("6175302", KIND_TUTORIAL, 'ד"ר גולני מתתיהו', [mk_meeting(3, T1200, T1345)]),
            ]
        )
        store.save_course(course, mk_meta(group_count=2))

        loaded, meta = store.load_course("61753")
        assert loaded == course, "הקורס חייב לחזור זהה לחלוטין"
        assert meta is not None

    def test_meeting_semester_field_survives_round_trip(self, store: Store):
        # השדה הקריטי: בלעדיו מפגשים מסמסטר ב' יזלגו למערכת של סמסטר א'.
        course = mk_course(groups=[mk_group(meetings=[mk_meeting(semester="ב")])])
        store.save_course(course, mk_meta())
        loaded, _meta = store.load_course("61753")
        assert loaded is not None
        assert loaded.groups[0].meetings[0].semester == "ב"

    def test_group_linked_to_survives_round_trip(self, store: Store):
        course = mk_course(groups=[mk_group(linked_to=["6175302", "6175303"])])
        store.save_course(course, mk_meta())
        loaded, _meta = store.load_course("61753")
        assert loaded is not None
        assert loaded.groups[0].linked_to == ["6175302", "6175303"]

    def test_empty_optional_fields_round_trip(self, store: Store):
        course = mk_course(
            groups=[
                mk_group(
                    lecturer="",
                    note="",
                    linked_to=[],
                    meetings=[mk_meeting(room="", building="", semester="")],
                )
            ]
        )
        store.save_course(course, mk_meta())
        loaded, _meta = store.load_course("61753")
        assert loaded == course

    def test_course_meta_round_trips_every_field(self, store: Store):
        meta = mk_meta(
            fetched_at="2026-08-30T07:00:00Z",
            semester="קיץ",
            content_sha1=sha1_of("page-v1"),
            group_count=7,
            warnings=["קורס 61753: אזהרה לדוגמה"],
            ok=True,
        )
        store.save_course(mk_course(), meta)

        got = store.course_meta("61753")
        assert got is not None
        assert got.fetched_at == "2026-08-30T07:00:00Z"
        assert got.year == YEAR_HE
        assert got.year_gregorian == YEAR_GREG
        assert got.semester == "קיץ"
        assert got.source_url == SOURCE
        assert got.content_sha1 == sha1_of("page-v1")
        assert got.group_count == 7
        assert list(got.warnings) == ["קורס 61753: אזהרה לדוגמה"]
        assert got.ok is True

    def test_load_missing_course_returns_none_pair(self, store: Store):
        assert store.load_course("99999") == (None, None)

    def test_course_meta_of_missing_code_is_none(self, store: Store):
        assert store.course_meta("99999") is None

    def test_load_all_returns_every_saved_course(self, store: Store):
        for code in ("61753", "61754", "61755"):
            store.save_course(mk_course(code=code, groups=[mk_group(code=code)]), mk_meta())
        loaded = store.load_all()
        assert set(loaded) == {"61753", "61754", "61755"}
        assert all(isinstance(c, Course) for c in loaded.values())

    def test_load_all_on_empty_store_is_empty(self, store: Store):
        assert store.load_all() == {}

    def test_data_survives_a_fresh_store_object(self, tmp_path: Path):
        # אותה תיקייה, מופע Store חדש — כך בדיוק פועל refresh.py מול main.py.
        course = mk_course()
        new_store(tmp_path).save_course(course, mk_meta())
        loaded, meta = new_store(tmp_path).load_course("61753")
        assert loaded == course
        assert meta is not None


# ==========================================================================
# 4. Store — טריות הנתונים (staleness)
# ==========================================================================
class TestStaleness:
    """גבולות הטריות. אסור להציג נתונים ישנים כאילו הם עדכניים."""

    def test_freshly_saved_course_is_not_stale(self, store: Store):
        store.save_course(mk_course(), mk_meta(fetched_at=iso_ago()))
        assert store.is_stale("61753", 24.0) is False

    def test_exactly_at_max_age_is_stale(self, store: Store):
        # בדיוק על הגבול: מרגע כתיבת החותמת הזמן רק מתקדם, ולכן הרשומה
        # כבר אינה צעירה מ-24 שעות — התשובה הבטוחה היא "ישן".
        store.save_course(mk_course(), mk_meta(fetched_at=iso_ago(hours=24.0)))
        assert store.is_stale("61753", 24.0) is True

    def test_one_second_under_max_age_is_fresh(self, store: Store):
        # ‏‎iso_ago‎ קוצץ לשנייה שלמה, כלומר מזיז את החותמת עד שנייה *אחורה* —
        # ‏וכאן זה אוכל את המרווח: "שנייה מתחת לגבול" היה בפועל 0 עד 1 שניות,
        # ‏ותחת עומס (‎-n 3‎, 2026-09-25) הכתיבה לדיסק גמרה אותו והבדיקה נכשלה.
        # ‏מעגלים כאן *למעלה* לשנייה השלמה הבאה, כך שהחותמת לעולם אינה ותיקה
        # מ-24 שעות פחות שנייה: המרווח הוא שנייה אמיתית. הטענה לא השתנתה.
        # (תוקן באישור מפורש.)
        moment = datetime.now(timezone.utc) - timedelta(hours=24.0, seconds=-1)
        if moment.microsecond:
            moment = moment.replace(microsecond=0) + timedelta(seconds=1)
        stamp = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
        store.save_course(mk_course(), mk_meta(fetched_at=stamp))
        assert store.is_stale("61753", 24.0) is False

    def test_one_second_over_max_age_is_stale(self, store: Store):
        store.save_course(mk_course(), mk_meta(fetched_at=iso_ago(hours=24.0, seconds=1)))
        assert store.is_stale("61753", 24.0) is True

    def test_ok_false_is_always_stale_even_when_just_fetched(self, store: Store):
        store.save_course(mk_course(), mk_meta(fetched_at=iso_ago(), ok=False))
        assert store.is_stale("61753", 24.0) is True

    def test_ok_false_is_stale_even_with_a_huge_max_age(self, store: Store):
        store.save_course(mk_course(), mk_meta(fetched_at=iso_ago(), ok=False))
        assert store.is_stale("61753", 100000.0) is True

    def test_missing_code_is_stale(self, store: Store):
        assert store.is_stale("99999", 24.0) is True

    def test_missing_code_is_stale_with_default_max_age(self, store: Store):
        assert store.is_stale("99999") is True

    @pytest.mark.parametrize("bad", ["", "not-a-timestamp", "30/08/2026", "2026-13-45T99:99:99Z"])
    def test_unparseable_fetched_at_is_stale(self, store: Store, bad: str):
        # חותמת שאי אפשר לפענח היא "לא ידוע" — ולכן נחשבת ישנה, לא טרייה.
        store.save_course(mk_course(), mk_meta(fetched_at=bad))
        assert store.is_stale("61753", 24.0) is True

    def test_stale_codes_returns_only_the_stale_ones(self, store: Store):
        store.save_course(
            mk_course(code="61753", groups=[mk_group(code="61753")]),
            mk_meta(fetched_at=iso_ago(hours=1)),
        )
        store.save_course(
            mk_course(code="61754", groups=[mk_group(code="61754")]),
            mk_meta(fetched_at=iso_ago(hours=48)),
        )
        store.save_course(
            mk_course(code="61755", groups=[mk_group(code="61755")]),
            mk_meta(fetched_at=iso_ago(hours=1), ok=False),
        )
        got = store.stale_codes(["61753", "61754", "61755", "61756"], 24.0)
        assert set(got) == {"61754", "61755", "61756"}

    def test_stale_codes_accepts_any_iterable(self, store: Store):
        store.save_course(mk_course(), mk_meta(fetched_at=iso_ago(hours=1)))
        assert set(store.stale_codes(("61753", "99999"), 24.0)) == {"99999"}


# ==========================================================================
# 5. Store — זיהוי שינויים (change detection)
# ==========================================================================
class TestChangeDetection:
    """הלב של הפיצ'ר: מרצה או שעה שהשתנו חייבים להיאמר בקול, לא להיקבר בלוג."""

    LECTURE = "6175301"
    TUTORIAL = "6175302"

    def _v1(self) -> Course:
        return mk_course(
            groups=[
                mk_group(self.LECTURE, KIND_LECTURE, "פרופ' וולקוביץ' זאב", [mk_meeting(2, T1015, T1200)]),
                mk_group(self.TUTORIAL, KIND_TUTORIAL, 'ד"ר רווה אלנה', [mk_meeting(3, T0830, T1000)]),
            ]
        )

    def _save_v1(self, store: Store) -> None:
        store.save_course(self._v1(), mk_meta(content_sha1=sha1_of("page-v1"), group_count=2))

    def test_first_write_reports_no_changes(self, store: Store):
        changes = store.save_course(mk_course(), mk_meta(content_sha1=sha1_of("page-v1")))
        assert changes == []

    def test_identical_save_with_identical_sha_reports_no_changes(self, store: Store):
        self._save_v1(store)
        again = store.save_course(
            self._v1(), mk_meta(content_sha1=sha1_of("page-v1"), group_count=2)
        )
        assert again == []

    def test_identical_course_with_new_sha_still_reports_no_changes(self, store: Store):
        # ה-sha הוא רק שער זול. אם התוכן זהה — אין מה לדווח.
        self._save_v1(store)
        again = store.save_course(
            self._v1(), mk_meta(content_sha1=sha1_of("page-v1-reordered-html"), group_count=2)
        )
        assert again == []

    def test_added_group_is_detected(self, store: Store):
        self._save_v1(store)
        v2 = self._v1()
        v2.groups.append(
            mk_group("6175303", KIND_TUTORIAL, 'ד"ר רווה אלנה', [mk_meeting(5, T1200, T1345)])
        )
        changes = store.save_course(
            v2, mk_meta(content_sha1=sha1_of("page-v2-added"), group_count=3)
        )
        assert changes, "קבוצה חדשה חייבת להופיע ברשימת השינויים"
        assert "6175303" in " | ".join(changes)

    def test_removed_group_is_detected(self, store: Store):
        self._save_v1(store)
        v2 = mk_course(groups=[g for g in self._v1().groups if g.group_id != self.TUTORIAL])
        changes = store.save_course(
            v2, mk_meta(content_sha1=sha1_of("page-v2-removed"), group_count=1)
        )
        assert changes, "ביטול קבוצה חייב להופיע ברשימת השינויים"
        assert self.TUTORIAL in " | ".join(changes)

    def test_lecturer_change_is_detected_with_both_names(self, store: Store):
        self._save_v1(store)
        v2 = self._v1()
        v2.groups[0].lecturer = 'ד"ר גולני מתתיהו'
        changes = store.save_course(
            v2, mk_meta(content_sha1=sha1_of("page-v2-lecturer"), group_count=2)
        )
        joined = " | ".join(changes)
        assert changes
        assert self.LECTURE in joined
        assert "וולקוביץ'" in joined, "השם הישן חייב להופיע"
        assert "גולני" in joined, "השם החדש חייב להופיע"

    def test_meeting_time_change_is_detected(self, store: Store):
        self._save_v1(store)
        v2 = self._v1()
        v2.groups[0].meetings = [mk_meeting(2, T1200, T1345)]
        changes = store.save_course(
            v2, mk_meta(content_sha1=sha1_of("page-v2-time"), group_count=2)
        )
        joined = " | ".join(changes)
        assert changes
        assert self.LECTURE in joined
        assert "10:15" in joined, "השעה הישנה חייבת להופיע"
        assert "12:00" in joined, "השעה החדשה חייבת להופיע"

    def test_day_change_is_detected(self, store: Store):
        self._save_v1(store)
        v2 = self._v1()
        v2.groups[0].meetings = [mk_meeting(4, T1015, T1200)]  # יום ב -> יום ד
        changes = store.save_course(
            v2, mk_meta(content_sha1=sha1_of("page-v2-day"), group_count=2)
        )
        assert changes, "שינוי יום הוא בדיוק מה שהסטודנט/ית צריכ/ה לדעת"
        assert self.LECTURE in " | ".join(changes)

    def test_room_only_change_does_not_crash_and_returns_a_list(self, store: Store):
        self._save_v1(store)
        v2 = self._v1()
        v2.groups[0].meetings = [mk_meeting(2, T1015, T1200, room="8104")]
        changes = store.save_course(
            v2, mk_meta(content_sha1=sha1_of("page-v2-room"), group_count=2)
        )
        assert isinstance(changes, list)
        assert all(isinstance(c, str) for c in changes)

    def test_changes_are_reported_per_group_not_as_one_blob(self, store: Store):
        self._save_v1(store)
        v2 = self._v1()
        v2.groups[0].lecturer = 'ד"ר גולני מתתיהו'
        v2.groups.append(
            mk_group("6175303", KIND_LAB, 'ד"ר רווה אלנה', [mk_meeting(5, T1200, T1345)])
        )
        changes = store.save_course(
            v2, mk_meta(content_sha1=sha1_of("page-v2-both"), group_count=3)
        )
        assert len(changes) >= 2
        joined = " | ".join(changes)
        assert "גולני" in joined and "6175303" in joined

    def test_new_version_actually_replaces_the_old_one(self, store: Store):
        self._save_v1(store)
        v2 = self._v1()
        v2.groups[0].lecturer = 'ד"ר גולני מתתיהו'
        store.save_course(v2, mk_meta(content_sha1=sha1_of("page-v2-lecturer"), group_count=2))
        loaded, _meta = store.load_course("61753")
        assert loaded is not None
        assert loaded.groups[0].lecturer == 'ד"ר גולני מתתיהו'


# ==========================================================================
# 6. Store — עמידות: כשלון רענון, כתיבה אטומית, קובץ פגום
# ==========================================================================
class TestDurability:
    def test_failed_refresh_does_not_destroy_stored_course(self, store: Store):
        # SPEC: "Never destroy good data on a failed fetch."
        good = mk_course(
            groups=[
                mk_group("6175301", KIND_LECTURE, "פרופ' וולקוביץ' זאב", [mk_meeting(2, T1015, T1200)]),
                mk_group("6175302", KIND_TUTORIAL, 'ד"ר רווה אלנה', [mk_meeting(3, T0830, T1000)]),
            ]
        )
        store.save_course(good, mk_meta(content_sha1=sha1_of("page-good"), group_count=2))

        # רענון שנכשל: אין קבוצות, ok=False.
        empty = mk_course(groups=[], name="")
        store.save_course(
            empty,
            mk_meta(
                fetched_at=iso_ago(),
                content_sha1="",
                group_count=0,
                warnings=["הבקשה נכשלה"],
                ok=False,
            ),
        )

        loaded, meta = store.load_course("61753")
        assert loaded is not None, "רענון כושל לא מוחק את הקורס"
        assert len(loaded.groups) == 2, "שתי הקבוצות הקודמות חייבות לשרוד"
        assert loaded == good
        assert meta is not None and meta.ok is False
        assert store.is_stale("61753", 24.0) is True, "אחרי כשלון הנתונים מסומנים כישנים"

    def test_failed_refresh_keeps_the_course_in_load_all(self, store: Store):
        store.save_course(mk_course(), mk_meta(content_sha1=sha1_of("page-good")))
        store.save_course(mk_course(groups=[]), mk_meta(ok=False, group_count=0))
        assert "61753" in store.load_all()

    def test_failed_refresh_reports_no_phantom_changes(self, store: Store):
        store.save_course(mk_course(), mk_meta(content_sha1=sha1_of("page-good")))
        changes = store.save_course(mk_course(groups=[]), mk_meta(ok=False, group_count=0))
        assert changes == [], "כשלון רשת אינו 'בוטלו כל הקבוצות'"

    def test_atomic_write_leaves_no_tmp_file(self, tmp_path: Path):
        root = tmp_path / "db"
        store = Store(str(root))
        store.save_course(mk_course(), mk_meta())
        leftovers = sorted(p.name for p in root.rglob("*.tmp"))
        assert leftovers == []

    def test_sections_file_parses_as_json_after_save(self, tmp_path: Path):
        root = tmp_path / "db"
        store = Store(str(root))
        store.save_course(mk_course(), mk_meta())
        path = find_file(root, "sections.json")
        assert path is not None, "sections.json חייב להיווצר"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_sections_file_is_utf8_and_not_ascii_escaped(self, tmp_path: Path):
        root = tmp_path / "db"
        store = Store(str(root))
        store.save_course(mk_course(), mk_meta())
        path = find_file(root, "sections.json")
        assert path is not None
        raw = path.read_text(encoding="utf-8")
        assert "אלגוריתמים" in raw, "ensure_ascii=False — כדי שה-diff יהיה קריא"

    def test_corrupt_sections_json_does_not_raise(self, tmp_path: Path):
        root = tmp_path / "db"
        root.mkdir(parents=True, exist_ok=True)
        (root / "sections.json").write_text("{ this is not json ][", encoding="utf-8")

        store = Store(str(root))  # לא אמור לזרוק
        assert store.load_all() == {} or isinstance(store.load_all(), dict)
        assert store.load_course("61753") == (None, None)

    def test_corrupt_sections_json_is_preserved_aside(self, tmp_path: Path):
        root = tmp_path / "db"
        root.mkdir(parents=True, exist_ok=True)
        bad = "{ this is not json ]["
        (root / "sections.json").write_text(bad, encoding="utf-8")

        store = Store(str(root))
        store.load_all()

        quarantined = [p for p in root.rglob("*") if p.is_file() and "corrupt" in p.name.lower()]
        assert quarantined, "הקובץ הפגום נשמר בצד עם סימון corrupt — לא נמחק"
        assert any(p.read_text(encoding="utf-8") == bad for p in quarantined)

    def test_store_is_usable_after_a_corrupt_file(self, tmp_path: Path):
        root = tmp_path / "db"
        root.mkdir(parents=True, exist_ok=True)
        (root / "sections.json").write_text("<<<not json>>>", encoding="utf-8")

        store = Store(str(root))
        store.load_all()
        course = mk_course()
        store.save_course(course, mk_meta())
        loaded, _meta = store.load_course("61753")
        assert loaded == course

    def test_store_creates_its_root_directory(self, tmp_path: Path):
        root = tmp_path / "nested" / "db"
        store = Store(str(root))
        store.save_course(mk_course(), mk_meta())
        assert root.is_dir()

    def test_store_never_touches_the_real_data_dir(self, tmp_path: Path):
        # שמירה מזהה: כל הכתיבות נשארות מתחת ל-tmp_path.
        root = tmp_path / "db"
        store = Store(str(root))
        store.save_course(mk_course(), mk_meta())
        written = [p for p in tmp_path.rglob("*") if p.is_file()]
        assert written
        assert all(str(p).startswith(str(tmp_path)) for p in written)


# ==========================================================================
# 7. Store — הקטלוג והחיפוש
# ==========================================================================
SEARCH_CATALOG = {
    "61753": {"name": "אלגוריתמים", "status": "נלמד"},
    "617531": {"name": "מבוא לאלגוריתמים", "status": "נלמד"},
    "990001": {"name": "סדנת 61753 מתקדמת", "status": "נלמד"},
    "271030": {"name": "מתמטיקה ב'", "status": "נלמד"},
    "104031": {"name": 'מבוא למדעי המחשב ומע"ב', "status": "נלמד"},
    "115000": {"name": "תורת הגרפים", "status": "נלמד"},
}


class TestCatalogStore:
    def test_catalog_round_trip(self, store: Store):
        store.save_catalog(SEARCH_CATALOG, YEAR_HE, YEAR_GREG)
        courses, meta = store.load_catalog()
        assert courses == SEARCH_CATALOG
        assert isinstance(meta, dict) and meta

    def test_catalog_meta_records_the_year_it_was_fetched_for(self, store: Store):
        # שנה שגויה היא הכישלון הגרוע ביותר — לכן היא חייבת להישמר עם הקטלוג.
        store.save_catalog(SEARCH_CATALOG, YEAR_HE, YEAR_GREG)
        _courses, meta = store.load_catalog()
        values = {str(v) for v in meta.values()}
        assert YEAR_HE in values
        assert YEAR_GREG in values

    def test_catalog_age_is_none_before_any_save(self, store: Store):
        assert store.catalog_age_hours() is None

    def test_catalog_age_is_small_right_after_saving(self, store: Store):
        store.save_catalog(SEARCH_CATALOG, YEAR_HE, YEAR_GREG)
        age = store.catalog_age_hours()
        assert age is not None
        assert 0.0 <= age < 1.0

    def test_load_catalog_on_empty_store_is_empty(self, store: Store):
        courses, meta = store.load_catalog()
        assert courses == {}
        assert isinstance(meta, dict)

    def test_catalog_survives_a_fresh_store_object(self, tmp_path: Path):
        new_store(tmp_path).save_catalog(SEARCH_CATALOG, YEAR_HE, YEAR_GREG)
        courses, _meta = new_store(tmp_path).load_catalog()
        assert courses == SEARCH_CATALOG


class TestSearchCatalog:
    @pytest.fixture()
    def filled(self, store: Store) -> Store:
        store.save_catalog(SEARCH_CATALOG, YEAR_HE, YEAR_GREG)
        return store

    def test_exact_code_beats_prefix_beats_name_substring(self, filled: Store):
        results = filled.search_catalog("61753")
        codes = [code for code, _name in results]
        assert codes[:3] == ["61753", "617531", "990001"], (
            "דירוג: התאמה מדויקת לקוד, אחר כך תחילית קוד, ורק אז שם"
        )

    def test_results_are_code_name_pairs(self, filled: Store):
        results = filled.search_catalog("61753")
        assert results
        for item in results:
            assert isinstance(item, tuple) and len(item) == 2
            code, name = item
            assert isinstance(code, str) and isinstance(name, str)
        assert dict(results)["61753"] == "אלגוריתמים"

    def test_name_substring_search(self, filled: Store):
        codes = [code for code, _ in filled.search_catalog("אלגוריתמים")]
        assert set(codes) >= {"61753", "617531"}

    def test_code_prefix_search(self, filled: Store):
        codes = [code for code, _ in filled.search_catalog("6175")]
        assert set(codes) >= {"61753", "617531"}

    def test_hebrew_gershayim_variant_still_matches(self, filled: Store):
        # השם בקטלוג נכתב עם גרש כפול רגיל ("), והחיפוש עם גרשיים עבריים (״).
        results = filled.search_catalog("מע״ב")
        assert "104031" in [code for code, _ in results]

    def test_hebrew_geresh_variant_still_matches(self, filled: Store):
        # "מתמטיקה ב'" מול "מתמטיקה ב׳" (U+05F3).
        results = filled.search_catalog("מתמטיקה ב׳")
        assert "271030" in [code for code, _ in results]

    def test_plain_quote_query_matches_gershayim_name(self, store: Store):
        store.save_catalog({"104031": {"name": "מבוא למדעי המחשב ומע״ב", "status": "נלמד"}}, YEAR_HE, YEAR_GREG)
        assert "104031" in [code for code, _ in store.search_catalog('מע"ב')]

    def test_nbsp_in_query_still_matches(self, filled: Store):
        results = filled.search_catalog("תורת הגרפים")
        assert "115000" in [code for code, _ in results]

    def test_limit_is_respected(self, filled: Store):
        assert len(filled.search_catalog("מ", limit=2)) <= 2

    def test_no_match_returns_empty_list(self, filled: Store):
        assert filled.search_catalog("קורס שאינו קיים בשום מקום") == []

    def test_empty_query_does_not_raise(self, filled: Store):
        assert isinstance(filled.search_catalog(""), list)

    def test_search_on_empty_catalog_is_empty(self, store: Store):
        assert store.search_catalog("61753") == []


# ==========================================================================
# 8. Store — הקבוצה שמתרעננת (tracked set)
# ==========================================================================
class TestTrackedSet:
    def test_empty_store_tracks_nothing(self, store: Store):
        assert store.tracked() == []

    def test_track_unions_dedups_and_sorts(self, store: Store):
        store.track(["61754", "61753"])
        store.track(["61754", "61752"])
        assert store.tracked() == ["61752", "61753", "61754"]

    def test_track_is_idempotent(self, store: Store):
        store.track(["61753", "61754"])
        before = store.tracked()
        store.track(["61753", "61754"])
        assert store.tracked() == before

    def test_track_dedups_within_one_call(self, store: Store):
        store.track(["61753", "61753", "61753"])
        assert store.tracked() == ["61753"]

    def test_track_accepts_any_iterable_and_still_sorts(self, store: Store):
        store.track(("61755", "61752", "61754"))
        store.track({"61753"})
        assert store.tracked() == ["61752", "61753", "61754", "61755"]

    def test_untrack_removes_only_the_named_codes(self, store: Store):
        store.track(["61752", "61753", "61754"])
        store.untrack(["61753"])
        assert store.tracked() == ["61752", "61754"]

    def test_untrack_of_an_absent_code_is_a_no_op(self, store: Store):
        store.track(["61753"])
        store.untrack(["99999"])
        assert store.tracked() == ["61753"]

    def test_untrack_everything_leaves_an_empty_list(self, store: Store):
        store.track(["61752", "61753"])
        store.untrack(["61752", "61753"])
        assert store.tracked() == []

    def test_tracked_set_persists_across_store_objects(self, tmp_path: Path):
        new_store(tmp_path).track(["61754", "61753"])
        assert new_store(tmp_path).tracked() == ["61753", "61754"]

    def test_track_of_nothing_does_not_break(self, store: Store):
        store.track([])
        assert store.tracked() == []


# ==========================================================================
# 9. Store — לוגים וגיבויים
# ==========================================================================
class TestLogsAndSnapshots:
    def test_last_refresh_is_none_before_any_run(self, store: Store):
        assert store.last_refresh() is None

    def test_log_refresh_then_last_refresh_returns_the_latest(self, store: Store):
        store.log_refresh({"started_at": "2026-08-30T07:00:00Z", "ok": True, "refreshed": 1})
        store.log_refresh({"started_at": "2026-08-31T07:00:00Z", "ok": True, "refreshed": 4})
        last = store.last_refresh()
        assert isinstance(last, dict)
        assert last.get("refreshed") == 4

    def test_refresh_log_is_append_only_jsonl(self, tmp_path: Path):
        root = tmp_path / "db"
        store = Store(str(root))
        store.log_refresh({"n": 1})
        store.log_refresh({"n": 2})
        path = find_file(root, "refresh_log.jsonl")
        assert path is not None
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 2
        assert [json.loads(ln)["n"] for ln in lines] == [1, 2]

    def test_log_changes_writes_one_line_per_run(self, tmp_path: Path):
        root = tmp_path / "db"
        store = Store(str(root))
        store.log_changes("61753", ["61753: קבוצה 6175301 — המרצה השתנה"])
        path = find_file(root, "changes.jsonl")
        assert path is not None
        text = path.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        assert len(lines) == 1
        assert "61753" in text
        json.loads(lines[0])  # חייב להיות JSON תקין

    def test_log_changes_with_empty_list_does_not_crash(self, store: Store):
        store.log_changes("61753", [])

    def test_snapshot_is_none_when_there_is_nothing_to_copy(self, store: Store):
        assert store.snapshot() is None

    def test_snapshot_copies_sections_json(self, tmp_path: Path):
        root = tmp_path / "db"
        store = Store(str(root))
        store.save_course(mk_course(), mk_meta())
        path = store.snapshot()
        assert path is not None
        copied = Path(path)
        assert copied.is_file()
        assert "snapshots" in copied.parts
        json.loads(copied.read_text(encoding="utf-8"))


# ==========================================================================
# 10. discovery — סינון והצלבה מול תוכנית הלימודים
# ==========================================================================
OUTSIDE_CODE = "999999"  # קוד שבוודאות אינו בתוכנית הלימודים


@pytest.fixture(scope="module")
def curriculum_codes(curriculum: dict) -> list[str]:
    codes = [c for c in all_course_codes(curriculum) if c.isdigit()]
    assert codes, "curriculum.json חייב להכיל קודים — אחרת הבדיקות האלה חסרות משמעות"
    return codes


class TestFilterCatalog:
    @needs_filter
    def test_code_prefixes_keeps_only_matching_codes(self):
        catalog = {
            "61753": {"name": "אלגוריתמים", "status": "נלמד"},
            "62110": {"name": "קורס מחלקה", "status": "נלמד"},
            "271030": {"name": "מתמטיקה ב'", "status": "נלמד"},
        }
        got = _filter_catalog(catalog, code_prefixes=("61", "62"))
        assert set(got) == {"61753", "62110"}

    @needs_filter
    def test_name_contains_filter(self):
        catalog = {
            "61753": {"name": "אלגוריתמים", "status": "נלמד"},
            "271030": {"name": "מתמטיקה ב'", "status": "נלמד"},
        }
        got = _filter_catalog(catalog, name_contains="מתמטיקה")
        assert set(got) == {"271030"}

    @needs_filter
    def test_no_filters_returns_everything(self):
        catalog = {"61753": {"name": "אלגוריתמים", "status": "נלמד"}}
        assert set(_filter_catalog(catalog)) == {"61753"}

    @needs_filter
    def test_only_curriculum_none_keeps_outside_courses(self, curriculum_codes):
        # דרישה (1): ברירת המחדל אינה מגבילה לתוכנית הלימודים.
        catalog = {
            curriculum_codes[0]: {"name": "קורס מהתוכנית", "status": "נלמד"},
            OUTSIDE_CODE: {"name": "קורס מחוץ לתוכנית", "status": "נלמד"},
        }
        assert set(_filter_catalog(catalog, only_curriculum=None)) == set(catalog)

    @needs_filter
    def test_only_curriculum_restricts_when_asked_explicitly(self, curriculum, curriculum_codes):
        catalog = {
            curriculum_codes[0]: {"name": "קורס מהתוכנית", "status": "נלמד"},
            OUTSIDE_CODE: {"name": "קורס מחוץ לתוכנית", "status": "נלמד"},
        }
        got = _filter_catalog(catalog, only_curriculum=curriculum)
        assert curriculum_codes[0] in got
        assert OUTSIDE_CODE not in got


class TestAnnotateWithCurriculum:
    _CURRICULUM_KEYS = {
        "in_curriculum",
        "credits",
        "semester",
        "curriculum_semester",
        "tied_with",
        "prereq",
        "prerequisites",
        "cluster",
        "elective_cluster",
    }

    @needs_annotate
    def test_course_outside_the_curriculum_is_kept_and_marked(self, curriculum, curriculum_codes):
        # דרישה (1) במפורש: קוד שאינו בתוכנית נשאר בר-בחירה, רק מסומן.
        catalog = {
            curriculum_codes[0]: {"name": "קורס מהתוכנית", "status": "נלמד"},
            OUTSIDE_CODE: {"name": "קורס מחוץ לתוכנית", "status": "נלמד"},
        }
        got = _annotate(catalog, curriculum)
        assert OUTSIDE_CODE in got, "קורס מחוץ לתוכנית לא נזרק — הוא מקרה תקין"
        assert got[OUTSIDE_CODE].get("in_curriculum") is False
        assert got[OUTSIDE_CODE].get("name") == "קורס מחוץ לתוכנית"

    @needs_annotate
    def test_curriculum_course_gains_curriculum_information(self, curriculum, curriculum_codes):
        code = curriculum_codes[0]
        catalog = {code: {"name": "קורס מהתוכנית", "status": "נלמד"}}
        got = _annotate(catalog, curriculum)
        assert got[code].get("in_curriculum") is not False
        assert self._CURRICULUM_KEYS & set(got[code]), "חייב להתווסף לפחות נתון אחד מהתוכנית"

    @needs_annotate
    def test_annotation_never_loses_courses(self, curriculum, curriculum_codes):
        catalog = {
            curriculum_codes[0]: {"name": "א", "status": "נלמד"},
            curriculum_codes[-1]: {"name": "ב", "status": "נלמד"},
            OUTSIDE_CODE: {"name": "ג", "status": "נלמד"},
        }
        assert set(_annotate(catalog, curriculum)) == set(catalog)


# ==========================================================================
# 11. compare_catalogs — מה השתנה בין שני קטלוגים
# ==========================================================================
OLD_CATALOG = {
    "61753": {"name": "אלגוריתמים", "status": "נלמד"},
    "61754": {"name": "מבני נתונים", "status": "נלמד"},
}


class TestCompareCatalogs:
    @needs_compare
    def test_identical_catalogs_report_nothing(self):
        assert flatten_report(_compare_catalogs(OLD_CATALOG, dict(OLD_CATALOG))) == []

    @needs_compare
    def test_added_course_is_detected(self):
        new = dict(OLD_CATALOG)
        new["61755"] = {"name": "מערכות הפעלה", "status": "נלמד"}
        report = " | ".join(flatten_report(_compare_catalogs(OLD_CATALOG, new)))
        assert "61755" in report

    @needs_compare
    def test_removed_course_is_detected(self):
        new = {"61753": OLD_CATALOG["61753"]}
        report = " | ".join(flatten_report(_compare_catalogs(OLD_CATALOG, new)))
        assert "61754" in report

    @needs_compare
    def test_renamed_course_reports_both_names(self):
        new = dict(OLD_CATALOG)
        new["61754"] = {"name": "מבני נתונים ואלגוריתמים", "status": "נלמד"}
        report = " | ".join(flatten_report(_compare_catalogs(OLD_CATALOG, new)))
        assert "61754" in report
        assert "מבני נתונים ואלגוריתמים" in report

    @needs_compare
    def test_added_removed_and_renamed_together(self):
        new = {
            "61753": {"name": "אלגוריתמים ויעילות", "status": "נלמד"},  # renamed
            "61755": {"name": "מערכות הפעלה", "status": "נלמד"},  # added
        }  # 61754 removed
        report = " | ".join(flatten_report(_compare_catalogs(OLD_CATALOG, new)))
        assert "61753" in report and "61754" in report and "61755" in report

    @needs_compare
    def test_comparing_against_an_empty_old_catalog_lists_everything_as_new(self):
        report = " | ".join(flatten_report(_compare_catalogs({}, OLD_CATALOG)))
        assert "61753" in report and "61754" in report


# ==========================================================================
# 12. אינטגרציה אופליין: קטלוג אמיתי -> Store -> חיפוש
# ==========================================================================
class TestCatalogToStoreIntegration:
    def test_real_catalog_can_be_stored_and_searched(self, tmp_path: Path, real_catalog: dict):
        store = new_store(tmp_path)
        store.save_catalog(real_catalog, YEAR_HE, YEAR_GREG)

        courses, _meta = store.load_catalog()
        assert len(courses) == 1172

        hits = dict(store.search_catalog("271030"))
        assert hits.get("271030") == "מתמטיקה ב'"

    def test_a_course_outside_the_curriculum_is_still_searchable(
        self, tmp_path: Path, real_catalog: dict, curriculum: dict
    ):
        # דרישה (1) מקצה לקצה: הידיעון הוא מקור האמת למה שנפתח.
        store = new_store(tmp_path)
        store.save_catalog(real_catalog, YEAR_HE, YEAR_GREG)
        in_curr = set(all_course_codes(curriculum))
        outside = sorted(c for c in real_catalog if c not in in_curr)
        assert outside, "בקטלוג האמיתי בוודאי יש קורסים שאינם בתוכנית"
        code = outside[0]
        assert code in [c for c, _ in store.search_catalog(code)]
