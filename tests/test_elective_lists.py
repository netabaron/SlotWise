# -*- coding: utf-8 -*-
"""רשימות בחירה לפי התמחות — ``specializations`` ו-``elective_lists``.

עד 2026-09-26 ``src/shnaton.py`` זיהה רק כותרות "אשכול X" ו"מסלול X". באזרחית
יצאו 4 "מסלולים" במקום 2, במכונות רשימת ההעשרה נרשמה תחת תעשייה 4.0 בלבד,
בתעשייה וניהול שתי ההתמחויות התמזגו, וחשמל יצא ``flat``. המודל החדש נכתב
**לצד** ``clusters``/``tracks``, שנשארים כפי שהם עד שלב הקורסים יעבור אליו.

הערכים כאן נספרו מול ``docs/PROGRAM_FINDINGS.md`` ומול תמונות העמודים.

שלושה חלקים:
1. הנתונים ב-``data/curricula.json`` — רצים בכל מקום, גם ב-CI.
2. גאומטריה סינתטית של שורות אמיתיות — גם הם רצים בכל מקום.
3. חילוץ מחדש מה-PDF — מדלג כשפרקי השנתון (git-ignored) חסרים.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import shnaton  # noqa: E402

CIVIL = "הנדסה אזרחית"
ELECTRIC = "הנדסת חשמל ואלקטרוניקה"
INDUSTRY = "הנדסת תעשייה וניהול"
MECHANICAL = "הנדסת מכונות"
SOFTWARE = "הנדסת תוכנה"
INFOSYS = "הנדסת מערכות מידע"
MATH = "מתמטיקה שימושית עם התמחות ב-AI ובאלגוריתמיקה"

DS = "מדעי הנתונים"
DO = "תכן ותפעול של מערכות ייצור ושירות"


@pytest.fixture(scope="module")
def programs() -> dict:
    return json.loads((ROOT / "data" / "curricula.json").read_text(encoding="utf-8"))["programs"]


def codes(program: dict, list_id: str) -> list[str]:
    return [c["code"] for c in program["elective_lists"][list_id]["courses"]]


def all_codes(program: dict) -> set[str]:
    return {c["code"] for body in program["elective_lists"].values() for c in body["courses"]}


# ==========================================================================
# 1. המבנה
# ==========================================================================
def test_every_reference_points_at_a_list_and_every_list_is_used(programs):
    for name, program in programs.items():
        lists = program["elective_lists"]
        refs = [ref for listed in program["specializations"].values() for ref in listed]
        assert set(refs) <= set(lists), name
        if program["specializations"]:
            assert set(refs) == set(lists), f"{name}: רשימה שאף התמחות אינה מפנה אליה"


def test_every_course_row_has_a_real_code_and_a_name(programs):
    for name, program in programs.items():
        for list_id, body in program["elective_lists"].items():
            assert body["courses"], (name, list_id)
            assert isinstance(body["page"], int)
            for course in body["courses"]:
                assert course["code"].isdigit() and len(course["code"]) in (5, 6), course
                assert course["name"].strip(), course
                if "credits" in course:
                    assert isinstance(course["credits"], (int, float)), course


def test_the_old_fields_are_untouched_until_the_courses_step():
    """‏``clusters``/``tracks`` נקראים עדיין על ידי הממשק ובדיקות נעולות."""
    data = json.loads((ROOT / "data" / "curricula.json").read_text(encoding="utf-8"))["programs"]
    assert data[ELECTRIC]["structure"] == "flat"
    assert {k: len(v) for k, v in data[INDUSTRY]["clusters"].items()} == {
        "מערכות מידע ומדע הנתונים": 13,
        DO: 16,
        "ניהול": 10,
        "מדע וטכנולוגיה": 3,
    }
    assert len(data[CIVIL]["tracks"]) == 4


# ==========================================================================
# 2. אזרחית
# ==========================================================================
def test_civil_has_two_specializations_and_structures_has_two_groups(programs):
    civil = programs[CIVIL]
    assert civil["specializations"] == {
        "מבנים": ["מבנים · קבוצה 1", "מבנים · קבוצה 2"],
        "ניהול הבנייה": ["ניהול הבנייה · קורסי בחירה"],
    }
    assert codes(civil, "מבנים · קבוצה 1") == [
        "500110", "500111", "500112", "500113", "500114",
        "421418", "500116", "500117", "500118", "500119",
    ]
    assert codes(civil, "מבנים · קבוצה 2") == [
        "421222", "421319", "421221", "421413", "421318", "500120", "421327", "421420",
    ]


def test_civil_management_includes_51600_with_its_star(programs):
    """‏51600 מודפס עם נ"ז שלם ("4"), ולכן המחלץ הישן לא זיהה אותו כשורה."""
    rows = programs[CIVIL]["elective_lists"]["ניהול הבנייה · קורסי בחירה"]["courses"]
    assert len(rows) == 14
    by_code = {c["code"]: c for c in rows}
    assert by_code["51600"]["credits"] == 4.0
    assert by_code["51600"]["footnote"] == "*"
    assert by_code["500210"]["footnote"] == "*"


def test_civil_specialization_mandatory_courses_are_not_electives(programs):
    """‏29 / 24 נ"ז החובה בהתמחות (עמודים 6–11) נרשמו פעם כקורסי בחירה."""
    mandatory = {"421212", "421219", "421316", "421314", "421315", "421326", "500115",
                 "421411", "421214", "421317", "421328"}
    assert not mandatory & all_codes(programs[CIVIL])


# ==========================================================================
# 3. מכונות
# ==========================================================================
def test_mechanical_lists_have_the_printed_sizes(programs):
    mech = programs[MECHANICAL]
    sizes = {k: len(v["courses"]) for k, v in mech["elective_lists"].items()}
    assert sizes == {
        "תכן וייצור · קורסי בחירה בהתמחות": 19,
        "מכטרוניקה · קורסי בחירה בהתמחות": 23,
        "ביומכניקה · קורסי בחירה בהתמחות": 18,
        "תעשייה מתקדמת בעידן המידע · קורסי בחירה בהתמחות": 22,
        "קורסי העשרה לכלל ההתמחויות": 42,
    }


def test_the_enrichment_list_is_recorded_once_for_all_four(programs):
    mech = programs[MECHANICAL]
    assert mech["elective_lists"]["קורסי העשרה לכלל ההתמחויות"]["for_all_specializations"] is True
    assert len(mech["specializations"]) == 4
    for listed in mech["specializations"].values():
        assert listed[-1] == "קורסי העשרה לכלל ההתמחויות"


def test_mechanical_rows_printed_across_two_lines_are_found(programs):
    mech = programs[MECHANICAL]
    assert "22777" in codes(mech, "תכן וייצור · קורסי בחירה בהתמחות")
    assert "22748" in codes(mech, "מכטרוניקה · קורסי בחירה בהתמחות")
    bio = {c["code"]: c for c in mech["elective_lists"]["ביומכניקה · קורסי בחירה בהתמחות"]["courses"]}
    assert "21461" in bio
    assert "credits" not in bio["21461"], "עמוד 11 אינו מדפיס נ\"ז לשורה הזאת"


def test_mechanical_names_keep_their_own_digits(programs):
    rows = {c["code"]: c["name"] for c in programs[MECHANICAL]["elective_lists"]["קורסי העשרה לכלל ההתמחויות"]["courses"]}
    assert rows["22971"].endswith("א1")
    assert rows["22977"].endswith("ב2")


# ==========================================================================
# 4. תעשייה וניהול
# ==========================================================================
def test_industry_keeps_its_two_specializations_apart(programs):
    ind = programs[INDUSTRY]
    assert list(ind["specializations"]) == [DS, DO]
    assert len(codes(ind, f"{DS} · מערכות מידע ומדע הנתונים")) == 10
    assert len(codes(ind, f"{DO} · מערכות מידע ומדע הנתונים")) == 13
    only_do = set(codes(ind, f"{DO} · מערכות מידע ומדע הנתונים")) - set(
        codes(ind, f"{DS} · מערכות מידע ומדע הנתונים")
    )
    assert only_do == {"51027", "51030", "51535"}


def test_identical_lists_are_recorded_once(programs):
    ind = programs[INDUSTRY]
    for spec in (DS, DO):
        assert "ניהול" in ind["specializations"][spec]
        assert "מדע וטכנולוגיה" in ind["specializations"][spec]
    assert "51916" in codes(ind, "ניהול")
    assert codes(ind, "מדע וטכנולוגיה") == ["22993", "41095", "41942"]


def test_every_center_course_is_filed_under_its_printed_cluster(programs):
    ind = programs[INDUSTRY]
    for spec, size in ((DS, 13), (DO, 12)):
        rows = ind["elective_lists"][f"{spec} · המרכז לחינוך הנדסי וליזמות"]["courses"]
        assert len(rows) == size
        for row in rows:
            assert row["cluster"] in ind["specializations"][spec], row
        cluster = {r["code"]: r["cluster"] for r in rows}
        assert cluster["251966"] == f"{spec} · מערכות מידע ומדע הנתונים"
        assert cluster["251514"] == f"{spec} · {DO}"
        assert cluster["251100"] == "ניהול"


# ==========================================================================
# 5. חשמל
# ==========================================================================
def test_electrical_has_three_specializations_under_their_declared_names(programs):
    assert list(programs[ELECTRIC]["specializations"]) == [
        "מחשבים (חומרה ותוכנה)",
        "עיבוד אותות ותקשורת",
        "התקנים ואלקטרואופטיקה",
    ]


def test_electrical_pools(programs):
    el = programs[ELECTRIC]
    for spec, core, only in (
        ("מחשבים (חומרה ותוכנה)", 8, ["31270", "31570"]),
        ("עיבוד אותות ותקשורת", 8, ["31485", "31740"]),
        ("התקנים ואלקטרואופטיקה", 9, ["31802", "31982", "31902", "31985", "31906", "31907"]),
    ):
        assert el["specializations"][spec] == [
            f"{spec} · קורסי ליבה בהתמחות",
            f"{spec} · קורסים משותפים למספר התמחויות",
            f"{spec} · קורסים להתמחות זו בלבד",
            "מקצועות בחירה נוספים",
            "רצועה רב-תחומית",
        ]
        assert len(codes(el, f"{spec} · קורסי ליבה בהתמחות")) == core
        assert codes(el, f"{spec} · קורסים להתמחות זו בלבד") == only
        pools = [el["elective_lists"][ref].get("pool") for ref in el["specializations"][spec][:3]]
        assert pools == ["core", "shared", "only"]


def test_computers_core_courses_carry_their_area(programs):
    rows = programs[ELECTRIC]["elective_lists"]["מחשבים (חומרה ותוכנה) · קורסי ליבה בהתמחות"]["courses"]
    areas = [r["area"] for r in rows]
    assert areas.count("חומרה") == 4 and areas.count("תוכנה") == 4
    assert all("(" not in r["name"] for r in rows)


def test_the_strip_and_the_additional_courses(programs):
    el = programs[ELECTRIC]
    assert len(codes(el, "רצועה רב-תחומית")) == 13
    assert codes(el, "מקצועות בחירה נוספים") == ["13069", "51914", "22784", "21461", "22486", "22864"]


def test_the_special_project_is_a_note_not_a_course(programs):
    body = programs[ELECTRIC]["elective_lists"]["מקצועות בחירה נוספים"]
    assert body["notes"] == ['פרויקט מיוחד בהנדסת חשמל ואלקטרוניקה — 1-2 נ"ז, מודפס בלי מספר קורס.']


def test_51914_reads_nlp_forward(programs):
    rows = {c["code"]: c for c in programs[ELECTRIC]["elective_lists"]["מקצועות בחירה נוספים"]["courses"]}
    assert rows["51914"]["name"] == "NLP מבוא לעיבוד שפה טבעית"


def test_seminars_keep_their_number_and_quarter_credit(programs):
    rows = {c["code"]: c for c in programs[ELECTRIC]["elective_lists"]["מחשבים (חומרה ותוכנה) · קורסים משותפים למספר התמחויות"]["courses"]}
    assert rows["31060"]["name"] == "סמינר מחלקתי 1"
    assert rows["31060"]["credits"] == 0.25
    assert rows["31060"]["footnote"] == "6"


# ==========================================================================
# 6. תוכניות בלי התמחויות
# ==========================================================================
@pytest.mark.parametrize("program", [SOFTWARE, INFOSYS])
def test_cluster_programs_match_the_old_clusters(programs, program):
    """אותם קודים ואותם שמות — פרט ל-61994, שורה אמיתית שהמחלץ הישן פספס."""
    data = programs[program]
    assert data["specializations"] == {}
    for title, rows in data["clusters"].items():
        new = {c["code"]: c["name"] for c in data["elective_lists"][title]["courses"]}
        old = {r["code"]: r["name"] for r in rows}
        extra = set(new) - set(old)
        assert extra == ({"61994"} if (program, title) == (INFOSYS, "מדעים") else set())
        assert {k: new[k] for k in old} == old


def test_math_is_not_written_while_rows_are_unrecognised(programs):
    math = programs[MATH]
    assert math["elective_lists"] == {} and math["specializations"] == {}
    assert any("לא זוהו" in w for w in math["elective_list_warnings"])


# ==========================================================================
# 7. גאומטריה של שורות אמיתיות
# ==========================================================================
def word(x0, x1, text, block, line_no, word_no, y0=0.0, y1=11.0):
    return (x0, y0, x1, y1, text, block, line_no, word_no)


def test_touching_latin_fragments_read_left_to_right():
    """‏51914, electric.pdf עמוד 13: ‏"LP" ואז "N" משמאלו, צמודים."""
    row = [
        word(471.9, 497.1, "51914", 12, 0, 0),
        word(450.9, 460.3, "LP", 12, 2, 0),
        word(444.6, 451.0, "N", 12, 3, 0),
        word(424.1, 442.3, "מבוא", 12, 5, 0),
    ]
    ordered = shnaton._reading_order(row)
    assert shnaton._join_words([(w[0], w[2], w[4]) for w in ordered]) == "51914 NLP מבוא"


def test_separate_latin_words_are_not_reordered():
    row = [word(300.0, 330.0, "High", 1, 0, 0), word(260.0, 290.0, "speed", 1, 1, 0)]
    assert [w[4] for w in shnaton._reading_order(row)] == ["High", "speed"]


def _line(words, heights=None):
    words = tuple(words)
    return shnaton.Line(1, 0.0, words, "  ".join(w[2] for w in words),
                        tuple(heights) if heights else tuple(11.0 for _ in words))


def test_a_small_digit_is_a_footnote():
    """‏31904: "מבוא ללייזרים" ואחריו "7" בכתב עילי (‏7.0 מול ‏11.0)."""
    line = _line(
        [(473, 498, "31904"), (446, 464, "מבוא"), (415, 444, "ללייזרים"), (412, 415, "7"),
         (334, 339, "2"), (311, 316, "1"), (287, 290, "-"), (256, 268, "2.5")],
        [11, 11, 11, 7, 11, 11, 11, 11],
    )
    clean, marks = shnaton._strip_superscripts(line)
    assert marks == ["7"]
    assert "7" not in [w[2] for w in clean.words]


def test_a_digit_glued_to_a_word_is_a_footnote_but_not_after_a_single_letter():
    glued = _line([(290, 315, "משלכם"), (286, 290, "1")])
    assert shnaton._strip_superscripts(glued)[1] == ["1"]
    label = _line([(377, 382, "א"), (373, 377, "1")])
    assert shnaton._strip_superscripts(label)[1] == []


def test_whole_and_two_decimal_credits_close_a_row():
    whole = ((345, 350, "3"), (330, 335, "2"), (310, 312, "-"), (290, 292, "-"), (270, 275, "4"))
    assert shnaton._wide_block(whole, None) == (350, 4.0)
    quarter = ((335, 338, "-"), (312, 315, "-"), (287, 290, "-"), (253, 271, "0.25"))
    assert shnaton._wide_block(quarter, None)[1] == 0.25


def test_a_number_right_of_the_first_column_belongs_to_the_name():
    """‏"סמינר מחלקתי 1": ה-"1" יושב ימינה מכותרת "ה" (‏340), ולכן אינו תא."""
    cells = ((404, 409, "1"), (335, 338, "-"), (312, 315, "-"), (287, 290, "-"), (253, 271, "0.25"))
    assert shnaton._wide_block(cells, 340.0)[0] == 338


def test_a_misspelt_heading_takes_the_declared_name():
    declared = ("מחשבים (חומרה ותוכנה)", "עיבוד אותות ותקשורת", "התקנים ואלקטרו-אופטיקה")
    assert shnaton._canonical_spec("עיבוד אות ותקשורת", (), declared) == "עיבוד אותות ותקשורת"
    # רווח או מקף בלבד אינם שגיאה: הכותרת נשארת כפי שהודפסה.
    assert shnaton._canonical_spec("התקנים ואלקטרואופטיקה", (), declared) == "התקנים ואלקטרואופטיקה"


def test_a_track_name_from_the_program_file_wins():
    assert shnaton._canonical_spec("הנדסת מבנים-", ("מבנים", "ניהול הבנייה")) == "מבנים"


# ==========================================================================
# 8. חילוץ מחדש
# ==========================================================================
PDFS = [ROOT / name for name in ("civil.pdf", "electric.pdf", "industry.pdf", "mecho.pdf")]


@pytest.mark.skipif(not all(p.exists() for p in PDFS), reason="פרקי השנתון חסרים (git-ignored)")
def test_the_committed_lists_are_what_the_parser_produces(tmp_path, programs):
    out = tmp_path / "curricula.json"
    shnaton.build_curricula(ROOT, out)
    fresh = json.loads(out.read_text(encoding="utf-8"))["programs"]
    for name, program in programs.items():
        for key in ("specializations", "elective_lists", "elective_list_warnings"):
            assert fresh[name][key] == program[key], (name, key)
