# -*- coding: utf-8 -*-
"""קורא שמשמיט שדה בשקט — הצורה, לא המקרה.

ב-7.9.2026 ‏``_group_from_dict`` לא העביר את ``semester`` ל-``Group``.
זה היה בלתי מזיק כל עוד ``sections.json`` נכתב מסונן לסמסטר אחד: לא היה
מה להבחין בו. ברגע שהקטלוג שנשלח עם הקוד התחיל לשאת את **כל** הסמסטרים,
כל קבוצה חזרה בלי תג — הסינון בזמן קריאה הפך לבלתי אפשרי, ‏24 קבוצות של
סמסטר ב' (שאין להן מפגשים ולכן אינן מתנגשות עם דבר) נכנסו למרחב החיפוש,
ו-``/api/solve`` עבר מ-0.14 שניות ליותר משתי דקות.

הבדיקה כאן אינה על ``semester``. היא על **הצורה**: השוואה מכנית בין מה
שהדאטהקלאס מכריז עליו לבין מה שהקורא באמת מעביר. שדה שנוסף למודל ולא
נוסף לקורא ייתפס כאן, בלי שאיש יצטרך לזכור להסתכל.
"""

from __future__ import annotations

import ast
import dataclasses
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from src.models import Course, Group, Meeting  # noqa: E402
from src.store import CourseMeta  # noqa: E402

STORE_SRC = ROOT / "src" / "store.py"

#: קורא -> הדאטהקלאס שהוא בונה.
READERS = {
    "_meeting_from_dict": Meeting,
    "_group_from_dict": Group,
    "_course_from_dict": Course,
}


def _kwargs_passed(func_name: str, cls_name: str) -> set:
    """אילו שדות הקורא באמת מעביר לבנאי — נקרא מהקוד, לא מהזיכרון."""
    tree = ast.parse(STORE_SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            passed = set()
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == cls_name
                ):
                    passed |= {kw.arg for kw in sub.keywords if kw.arg}
            return passed
    raise AssertionError(f"לא נמצאה הפונקציה {func_name} ב-store.py")


@pytest.mark.parametrize("func_name,cls", sorted(READERS.items()))
def test_the_reader_passes_every_field_the_model_declares(func_name, cls):
    declared = {f.name for f in dataclasses.fields(cls)}
    passed = _kwargs_passed(func_name, cls.__name__)
    missing = sorted(declared - passed)
    assert not missing, (
        f"{func_name} אינו מעביר ל-{cls.__name__} את: {', '.join(missing)}. "
        "שדה שהמודל מכריז עליו והקורא משמיט חוזר תמיד כברירת מחדל, בשקט."
    )


def test_group_semester_specifically_survives_a_round_trip():
    """המקרה שקרה בפועל, ננעל בנפרד מהבדיקה המכנית."""
    from src.store import _group_from_dict

    g = _group_from_dict(
        {"group_id": "271060310/1", "kind": "הרצאה", "lecturer": "מר בדיקה",
         "semester": "ב", "meetings": []},
        "61756",
    )
    assert g.semester == "ב", "תג הסמסטר של הקבוצה אבד בקריאה"


def test_course_meta_round_trips_every_field():
    declared = [f.name for f in dataclasses.fields(CourseMeta)]
    sample = {}
    for f in dataclasses.fields(CourseMeta):
        default = f.default if f.default is not dataclasses.MISSING else None
        if isinstance(default, bool):
            sample[f.name] = not default
        elif isinstance(default, str):
            sample[f.name] = "v_" + f.name
        elif isinstance(default, int):
            sample[f.name] = 7
        else:
            sample[f.name] = ["w"]
    back = CourseMeta.from_dict(sample)
    lost = [f for f in declared if getattr(back, f) != sample[f]]
    assert not lost, f"CourseMeta.from_dict איבד: {', '.join(lost)}"
    written = back.to_dict()
    assert not [f for f in declared if f not in written], "to_dict השמיט שדות"
