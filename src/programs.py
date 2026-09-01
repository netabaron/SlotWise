"""
src/programs.py — רשימת תוכניות הלימוד של בראודה, מהאתר הציבורי.

למה המודול הזה קיים
--------------------
עד עכשיו הממשק הכיר תוכנית לימודים אחת — הנדסת תוכנה — כי ``rec.pdf`` הוא
פרק אחד בשנתון. כל השאר קיבלו "תוכנית אחרת / לא ברשימה", שזו תשובה נכונה
אבל עלובה: הכלי לא ידע אפילו איך קוראים למסלול שלהם.

האתר הציבורי ``w3.braude.ac.il`` מפרסם את הרשימה המלאה והמוסמכת, בלי שום
התחברות. הקובץ הזה מושך אותה ושומר אותה ל-``data/programs.json``.

מה יש כאן ומה **אין**
---------------------
יש: שמות התוכניות, הכתובות שלהן, ותיאור קצר.
אין: תוכניות לימודים מלאות לכל מחלקה. בדקתי — האתר מפרסם שנתון מלא
(‏251 עמודים, כל המחלקות) אבל **הישן ביותר שבו הוא תשפ"ד 2023-24**; שנתוני
תשפ"ה/ו/ז אינם שם, ומה שמסומן שם "גרסת הדפסה" הוא לוח שנה אקדמית בלבד.
לכן מקור האמת ל"מה באמת נלמד השנה" נשאר הידיעון, שממילא מכסה את כל המחלקות.

Technical notes:
    * stdlib only (urllib + http.cookiejar), same discipline as yedion_http.
    * Never prints; progress goes to an injected log callback.
    * Every field is optional - a site redesign degrades the data, never crashes.
"""

from __future__ import annotations

import html as _html
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

__all__ = [
    "SITE",
    "PROGRAMS_INDEX",
    "Program",
    "fetch_programs",
    "parse_programs_index",
    "parse_program_page",
    "parse_tracks_text",
    "save_programs",
    "load_programs",
    "DEFAULT_PATH",
]

SITE = "https://w3.braude.ac.il"

#: הדף שמרכז את כל תוכניות התואר הראשון.
PROGRAMS_INDEX = f"{SITE}/calander-newsletter/yedion-bsc/"

DEFAULT_PATH = "data/programs.json"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ScheduleBuilder/1.0"

#: קישור לעמוד תוכנית: ‏/bsc-programs/yedionbsc-<slug>/
_PROGRAM_LINK_RE = re.compile(
    r'href="(https://w3\.braude\.ac\.il/bsc-programs/yedionbsc-[^"]+)"[^>]*>(.*?)</a>',
    re.S,
)

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPTY_RE = re.compile(r"<(script|style|nav|footer|header)[^>]*>.*?</\1>", re.S | re.I)


def _clean(text: Any) -> str:
    """מנקה טקסט HTML לשורה אחת קריאה."""
    out = _html.unescape(_TAG_RE.sub(" ", str(text or "")))
    return re.sub(r"\s+", " ", out.replace("\xa0", " ")).strip()


class Program(dict):
    """תוכנית לימודים אחת. ``dict`` בכוונה — נשמרת ל-JSON כמו שהיא."""

    @property
    def name(self) -> str:
        return str(self.get("name", ""))


def _get(url: str, timeout: float = 45.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "windows-1255", "iso-8859-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def parse_programs_index(html: str) -> list[dict]:
    """מוציא את רשימת התוכניות מדף הריכוז. ``[{name, url}]``, בלי כפילויות."""
    seen: dict[str, dict] = {}
    for url, label in _PROGRAM_LINK_RE.findall(html or ""):
        name = _clean(label)
        if not name or url in seen:
            continue
        seen[url] = {"name": name, "url": url, "slug": url.rstrip("/").split("-")[-1]}
    return list(seen.values())


#: "התמחויות: א, ב ו-ג." — האתר מפרסם את ההתמחויות של כל תוכנית בפסקת הפתיחה.
#: זה מקור **עדכני ומוסמך**, בניגוד לשנתון המלא שמתפרסם שם רק עד תשפ"ד.
_TRACKS_RE = re.compile(r"התמחו(?:יות|ת)\s*(?:במסלולים הבאים|באחד משלושת התחומים)?\s*:\s*([^.]{6,200})")


#  --- למה אין כאן פיצול לרשימת התמחויות ---------------------------------
#  ניסיתי, וזה יצא **שגוי בביטחון** — הגרוע מכל.
#  בעברית ו' החיבור היא גם מפריד רשימה וגם חלק משם מורכב:
#      "התמחויות: הנדסת ביצוע וניהול הבנייה, והנדסת מבנים"
#  כאן "הנדסת ביצוע וניהול הבנייה" היא התמחות **אחת**, אבל כל פיצול על ו'
#  קורע אותה לשתיים. אותו דבר ב"תכן ותפעול של מערכות ייצור ושירות".
#  אין בטקסט שום סימון מכונה שמבדיל בין השניים, ולכן שמירת המשפט כלשונו
#  היא התשובה הנכונה: היא מדויקת, והסטודנט/ית קורא/ת אותה בשנייה.
def parse_tracks_text(text: str) -> str:
    """המשפט שהאתר כותב על ההתמחויות, כלשונו. זהו המקור המוסמך."""
    match = _TRACKS_RE.search(text or "")
    return _clean(match.group(1)) if match else ""


def parse_program_page(html: str) -> dict:
    """תיאור קצר של התוכנית מתוך עמוד התוכנית.

    האתר בנוי מ-WordPress ורוב העמוד הוא ניווט. לוקחים את הפסקה המשמעותית
    הראשונה שאחרי הכותרת, ומגבילים את האורך — זו כותרת משנה בממשק, לא מאמר.
    """
    body = _SCRIPTY_RE.sub(" ", html or "")
    match = re.search(r"<(main|article)[^>]*>(.*?)</\1>", body, re.S | re.I)
    text = _clean(match.group(2) if match else body)
    # החלק שלפני "אודות הלימודים" הוא פסקת הפתיחה; מדלגים על שאריות הניווט.
    for marker in ("אודות הלימודים", "אודות התוכנית"):
        idx = text.find(marker)
        if idx > 0:
            text = text[:idx]
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if len(p.strip()) > 60]
    # התיאור נלקח לפני הניקוי של "אודות הלימודים"; ההתמחויות מהטקסט המלא,
    # כי לפעמים הן מופיעות אחרי הכותרת הזאת.
    return {
        "description": parts[-1][:400] if parts else "",
        "tracks_text": parse_tracks_text(_clean(_SCRIPTY_RE.sub(" ", html or ""))),
    }


def fetch_programs(
    log: Callable[[str], None] | None = None, delay_s: float = 1.0
) -> list[dict]:
    """מושך את רשימת התוכניות ואת התיאורים. מחזיר ``[Program]``.

    כישלון בעמוד בודד אינו מפיל את הריצה — התוכנית תישמר בלי תיאור.
    """
    import time

    emit = log or (lambda _m: None)
    emit(f"מושך את רשימת התוכניות מ-{PROGRAMS_INDEX}")
    index_html = _get(PROGRAMS_INDEX)
    programs = parse_programs_index(index_html)
    emit(f"נמצאו {len(programs)} תוכניות תואר ראשון.")

    out: list[dict] = []
    for i, prog in enumerate(programs, start=1):
        entry = dict(prog)
        try:
            emit(f"({i}/{len(programs)}) {prog['name']}")
            entry.update(parse_program_page(_get(prog["url"])))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            entry["description"] = ""
            emit(f"אזהרה: לא ניתן לקרוא את עמוד {prog['name']} ({type(exc).__name__}).")
        out.append(Program(entry))
        if i < len(programs):
            time.sleep(delay_s)
    return out


def save_programs(programs: list[dict], path: str | Path = DEFAULT_PATH) -> str:
    """שומר ל-JSON. מחזיר את הנתיב."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "braude-schedule-builder/programs",
        "version": 1,
        "source": PROGRAMS_INDEX,
        "note": (
            "שמות התוכניות בלבד. תוכניות לימודים מלאות אינן מתפרסמות באתר "
            "לשנה הנוכחית — השנתון המלא האחרון שם הוא תשפ\"ד."
        ),
        "programs": list(programs),
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return str(target)


def load_programs(path: str | Path = DEFAULT_PATH) -> list[dict]:
    """קורא את הקובץ. חסר או פגום -> רשימה ריקה, בלי לזרוק."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    programs = data.get("programs") if isinstance(data, dict) else None
    return [p for p in (programs or []) if isinstance(p, dict) and p.get("name")]


if __name__ == "__main__":  # pragma: no cover
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    found = fetch_programs(log=lambda m: print("  " + m))
    where = save_programs(found)
    print(f"\nנשמרו {len(found)} תוכניות ל-{where}")
    for p in found:
        print(f"  {p['name'][:42]:44} {p.get('description','')[:60]}")
