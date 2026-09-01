"""
בדיקות לפענוח פרקי השנתון של המחלקות.

שתי אמיתות שהקובץ הזה שומר עליהן
---------------------------------
1. **מסלול אינו אשכול.** אשכול = קורס אחד מכל קבוצה; מסלול = בוחרים מסלול
   אחד ומתמחים בו. להציג מסלול בשם אשכול היה מסלף את חוקי התואר, ולכן הם
   נשמרים ומוצגים בנפרד.
2. **שנה שלא נכתבה במסמך לא תומצא.** רק שני פרקים מצהירים שנת מחזור. בכל
   השאר ``year`` הוא ``None``, והממשק כותב "שנה לא צוינה".

הבדיקות מדלגות כשה-PDF חסר: פרקי השנתון הם מסמכים של המכללה והם
git-ignored, ולכן אינם קיימים בכל עותק של המאגר.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import shnaton  # noqa: E402

SW = ROOT / "sw.pdf"
MECHO = ROOT / "mecho.pdf"
SYSTEM = ROOT / "system.pdf"
ELECTRIC = ROOT / "electric.pdf"

needs_sw = pytest.mark.skipif(not SW.exists(), reason="sw.pdf חסר (git-ignored)")


# ==========================================================================
# 1. המבנה — אשכול מול מסלול מול כלום
# ==========================================================================
@needs_sw
def test_software_chapter_yields_the_six_known_clusters():
    """‏sw.pdf הוא אמת המידה: 6 אשכולות, בדיוק כמו ב-curriculum.json."""
    chapter = shnaton.parse_chapter(SW)
    assert chapter["structure"] == shnaton.STRUCTURE_CLUSTERS
    assert len(chapter["clusters"]) == 6
    assert not chapter["tracks"], "לתוכנה אין מסלולים, רק אשכולות"
    names = {n.replace(" ", "") for n in chapter["clusters"]}
    assert "מדעים" in names
    assert "מעבדות" in names


@needs_sw
def test_the_parser_finds_courses_the_hand_transcription_missed():
    """‏62003 'פרויקט במציאות רבודה' קיים ב-PDF ואומת מול הקטלוג החי.

    הוא נעדר מ-``curriculum.json`` שנכתב ביד — כלומר הפענוח האוטומטי מדויק
    יותר מהתמלול הידני, וזו הסיבה שהוא מחליף אותו.
    """
    chapter = shnaton.parse_chapter(SW)
    codes = {c["code"] for group in chapter["clusters"].values() for c in group}
    assert "62003" in codes


@pytest.mark.skipif(not MECHO.exists(), reason="mecho.pdf חסר")
def test_mechanical_yields_tracks_not_clusters():
    chapter = shnaton.parse_chapter(MECHO)
    assert chapter["structure"] == shnaton.STRUCTURE_TRACKS
    assert chapter["tracks"], "למכונות יש מסלולי התמחות"
    assert not chapter["clusters"], "מסלול אינו אשכול — אסור לערבב"


@pytest.mark.skipif(not ELECTRIC.exists(), reason="electric.pdf חסר")
def test_electrical_has_no_grouping_at_all():
    """חשמל אינו מקבץ את קורסי הבחירה — ואז אין מה להציג, ולא ממציאים."""
    chapter = shnaton.parse_chapter(ELECTRIC)
    assert chapter["structure"] == shnaton.STRUCTURE_FLAT
    assert not chapter["clusters"]
    assert not chapter["tracks"]


# ==========================================================================
# 2. שנה — רק כשהמסמך אומר
# ==========================================================================
@needs_sw
def test_a_stated_cohort_year_is_read():
    assert shnaton.parse_chapter(SW)["year"] == 'תשפ"ה'


@pytest.mark.skipif(not SYSTEM.exists(), reason="system.pdf חסר")
def test_an_older_chapter_keeps_its_own_older_year():
    """מערכות מידע הוא תשפ"ד — ישן יותר, וחייב להיות מסומן ככזה."""
    assert shnaton.parse_chapter(SYSTEM)["year"] == 'תשפ"ד'


@pytest.mark.skipif(not ELECTRIC.exists(), reason="electric.pdf חסר")
def test_a_chapter_with_no_year_reports_none_and_warns():
    chapter = shnaton.parse_chapter(ELECTRIC)
    assert chapter["year"] is None, "לא לנחש שנה שלא נכתבה"
    assert any("שנת מחזור" in w for w in chapter["warnings"])


# ==========================================================================
# 3. גבולות — קבוצה לא בולעת את הפרק הבא
# ==========================================================================
@pytest.mark.skipif(not MECHO.exists(), reason="mecho.pdf חסר")
def test_a_group_stops_at_the_next_chapter():
    """המסלול האחרון במכונות בלע פעם את פרק "מהנדסאים להנדנסה" והגיע ל-62.

    כל מסלול חייב להישאר בגודל סביר; קבוצה שמכילה עשרות קורסים היא הסימן
    שהיא רצה מעבר לסופה.
    """
    chapter = shnaton.parse_chapter(MECHO)
    for name, courses in chapter["tracks"].items():
        assert len(courses) < 60, f"מסלול {name} בלע תוכן זר ({len(courses)} קורסים)"


# ==========================================================================
# 4. ה-API — מה מוצג ומה מוסתר
# ==========================================================================
@pytest.fixture()
def client():
    from src.web.api import create_app

    return create_app().test_client()


def _electives(client, program: str) -> dict:
    return client.get(f"/api/program/electives?program={program}").get_json()


@needs_sw
def test_api_serves_clusters_with_their_year(client):
    data = _electives(client, "הנדסת תוכנה")
    assert data["available"] is True
    assert data["structure"] == "clusters"
    assert data["year"] == 'תשפ"ה'
    assert len(data["clusters"]) == 6


@pytest.mark.skipif(not SYSTEM.exists(), reason="system.pdf חסר")
def test_api_labels_the_older_chapter_with_its_year(client):
    data = _electives(client, "הנדסת מערכות מידע")
    assert data["year"] == 'תשפ"ד'
    assert 'תשפ"ד' in data["year_text"]


@pytest.mark.skipif(not MECHO.exists(), reason="mecho.pdf חסר")
def test_api_keeps_tracks_separate_from_clusters(client):
    data = _electives(client, "הנדסת מכונות")
    assert data["available"] is True
    assert data["structure"] == "tracks"
    assert data["tracks"] and not data["clusters"]
    assert "מסלול" in data["track_rule"]


@pytest.mark.skipif(not ELECTRIC.exists(), reason="electric.pdf חסר")
def test_api_hides_the_section_when_the_chapter_has_no_grouping(client):
    data = _electives(client, "הנדסת חשמל ואלקטרוניקה")
    assert data["available"] is False
    assert data.get("reason")
    assert not data.get("clusters") and not data.get("tracks")


def test_api_hides_the_section_when_there_is_no_chapter_at_all(client):
    """לביוטכנולוגיה אין PDF — מסתירים, לא מנחשים ולא מציגים ריק."""
    data = _electives(client, "הנדסת ביוטכנולוגיה")
    assert data["available"] is False
    assert not data.get("clusters") and not data.get("tracks")


def test_api_requires_a_program(client):
    assert client.get("/api/program/electives").status_code == 400


def test_an_unknown_program_is_hidden_not_an_error(client):
    data = _electives(client, "תוכנית שלא קיימת")
    assert data["available"] is False
