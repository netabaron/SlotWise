"""scripts/check_curricula.py — פענוח דף שנתון והשוואה לקובץ תוכנית, בלי רשת."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_curricula", ROOT / "scripts" / "check_curricula.py")
cc = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["check_curricula"] = cc  # dataclasses מחפשים את המודול ב-sys.modules
_spec.loader.exec_module(cc)


def _accordion(title: str, header: list[str], rows: list[list[str]]) -> str:
    tr = lambda cells: "<tr>" + "".join(f"<td><strong>{c}</strong></td>" for c in cells) + "</tr>"
    body = tr(header) + "".join(tr(r) for r in rows)
    return (
        '<li class="accordion-item" data-accordion-item>'
        f'<a href="#" class="accordion-title">{title}</a>'
        f'<div class="accordion-content" data-tab-content><table><tbody>{body}</tbody></table></div></li>'
    )


HEADER = ["מספר הקורס", "שם הקורס", "ה", "ת", "מ", "נקודות זכות", "קורסי קדם וקורסים צמודים"]
# מכונות סמסטר 5: תא המספר בכותרת ריק, ויש עמודת פ.
HEADER_NO_CODE = ["", "שם הקורס", "ה", "ת", "מ", "פ", "נקודות זכות"]

PAGE = (
    "<ul class='accordion'>"
    + _accordion("סמסטר 1", HEADER, [
        ["41089", "כימיה א", "1", "1", "&#8211;", "1.5", ""],
        ["11002", "אלגברה מ", "4", "2", "&#8211;", "5.0", ""],
        ["סך הכל", "", "", "", "", "6.5", ""],
    ])
    + _accordion("סמסטר 5", HEADER_NO_CODE, [
        ["22130", "אנליזה נומרית", "2", "1", "&#8211;", "&#8211;", "2.5"],
    ])
    + _accordion("קורסי בחירה", HEADER, [["99999", "בחירה", "2", "", "", "2.0", ""]])
    # התמחות שנייה: אותו קוד בסמסטר אחר.
    + _accordion("סמסטר 2", HEADER, [["11002", "אלגברה מ", "4", "2", "&#8211;", "5.0", ""]])
    + "</ul>"
)


def test_parse_page_reads_semester_tables_only():
    rows = cc.parse_page(PAGE)
    assert set(rows) == {"41089", "11002", "22130"}  # לא "סך הכל", לא קורסי בחירה
    assert rows["41089"].credits == 1.5
    assert rows["41089"].semesters == ("1",)


def test_empty_code_header_uses_column_before_name():
    rows = cc.parse_page(PAGE)
    assert rows["22130"].semesters == ("5",)
    assert rows["22130"].credits == 2.5  # עמודת נ"ז אחרי עמודת פ


def test_code_in_two_specializations_keeps_both_semesters():
    assert cc.parse_page(PAGE)["11002"].semesters == ("1", "2")


def _ours(tmp_path: Path, courses_by_semester: dict[str, list[dict]]) -> Path:
    path = tmp_path / "c.json"
    data = {"semesters": {k: {"courses": v} for k, v in courses_by_semester.items()}}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_compare_reports_each_kind(tmp_path):
    ours = cc.load_ours(_ours(tmp_path, {
        "1": [
            {"code": "41090", "name": "כימיה א'", "credits": 2.5},   # הקוד הישן
            {"code": None, "name": "קורס כללי", "credits": 2},       # בלי קוד — מדלגים
        ],
        "2": [{"code": "11002", "name": "אלגברה מ", "credits": 5}],  # סמסטר 2 קיים בהתמחות השנייה
        "4": [{"code": "22130", "name": "אנליזה נומרית", "credits": 3}],
    }))
    diffs = {(d.kind, d.code) for d in cc.compare(ours, cc.parse_page(PAGE))}
    assert diffs == {
        ("GONE", "41090"),
        ("NEW", "41089"),
        ("SEMESTER", "22130"),
        ("CREDITS", "22130"),
    }


def test_main_offline_exit_codes(tmp_path, capsys):
    html_dir = tmp_path / "html"
    html_dir.mkdir()
    root = tmp_path / "root"
    for slug, rel in cc.PROGRAMS.items():
        (html_dir / f"{slug}.html").write_text(PAGE, encoding="utf-8")
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"semesters": {
            "1": {"courses": [{"code": "41089", "credits": 1.5}, {"code": "11002", "credits": 5}]},
            "5": {"courses": [{"code": "22130", "credits": 2.5}]},
        }}), encoding="utf-8")
    assert cc.main(["--html-dir", str(html_dir), "--root", str(root)]) == 0

    (root / cc.PROGRAMS["elec"]).write_text(json.dumps({"semesters": {
        "1": {"courses": [{"code": "41090", "credits": 2.5}]},
    }}), encoding="utf-8")
    assert cc.main(["--html-dir", str(html_dir), "--root", str(root)]) == 1
    assert "41090" in capsys.readouterr().out

    (html_dir / "elec.html").write_text("<html>redesigned</html>", encoding="utf-8")
    assert cc.main(["--html-dir", str(html_dir), "--root", str(root)]) == 2


def test_next_year():
    assert cc.next_year("26-27") == "27-28"
    assert cc.next_year("09-10") == "10-11"
