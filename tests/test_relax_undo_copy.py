# -*- coding: utf-8 -*-
"""נוסח הוויתור והביטול: שמות האילוצים כבר נושאים "את".

‏``app.relax.restoreName.*`` הם "את השעה המאוחרת ביותר (13:00)", "את חסימת יום
שישי" וכו' — כך הם נכנסים לכפתור "החזר {what}". שלושה משפטים קיבלו את אותו
שם וכפלו או שברו אותו (תוקן 2026-11-09):

* ‏``undoNotice`` — "ויתרת על את השעה המאוחרת ביותר (13:00)."
* ‏``undone``     — "את השעה המאוחרת ביותר (13:00) הוחזר."
* ‏``applied``    — "את השעה המאוחרת ביותר (13:00) בוטל. 12 מערכות נמצאו."
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RELAX = json.loads((ROOT / "src" / "strings.json").read_text(encoding="utf-8"))["app"]["relax"]

#: ערכים לדוגמה לכל ממלא מקום שהשמות משתמשים בו.
SAMPLE = {
    "time": "13:00", "day": "ראשון", "from": "08:30", "to": "10:00",
    "course": "11026 פיזיקה 2ב",
}


def fill(template: str, **params) -> str:
    for key, value in params.items():
        template = template.replace("{" + key + "}", str(value))
    return template


def restore_names() -> list[str]:
    return [fill(t, **SAMPLE) for t in RELAX["restoreName"].values()]


def test_every_restore_name_carries_its_own_et():
    """החוזה שהמשפטים שלמטה נשענים עליו — ושעליו נשען "החזר {what}"."""
    for name in restore_names():
        assert name.startswith("את "), name
    assert fill(RELAX["undo"], what=restore_names()[0]).startswith("החזר את "), RELAX["undo"]


@pytest.mark.parametrize("key", ["undoNotice", "undone", "applied"])
def test_the_sentences_around_a_restore_name_read_as_hebrew(key):
    names = restore_names()
    # ‏app.js מחבר כמה ויתורים ב-" ו": "את X ואת Y".
    for what in names + [names[0] + " ו" + names[1]]:
        sentence = fill(RELAX[key], what=what, n=12)
        assert "על את" not in sentence, sentence
        assert not sentence.startswith("את "), sentence
        assert sentence.count("את ") == what.count("את "), sentence
