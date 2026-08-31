"""
main.py — נקודת ההפעלה של בונה המערכת. (launcher)

**הדפדפן הוא הממשק הראשי.** "python main.py" מפעיל אפליקציית ווב מקומית
(Flask על 127.0.0.1 בלבד) ופותח אותה בדפדפן. שם בוחרים שנה וסמסטר, קורסים,
מספר ימים ומרצים, ורואים את המערכת מתעדכנת בזמן אמת.

הרצה:
    python main.py                 # דפדפן — הממשק הראשי
    python main.py --port 5005     # פורט מפורש
    python main.py --no-browser    # להריץ שרת בלי לפתוח דפדפן
    python main.py --debug         # מצב פיתוח (הודעות שגיאה מלאות)

    python main.py --cli           # הזרימה הישנה בטרמינל (עדיין עובדת)
    python main.py --cli --offline # כל דגלי הטרמינל ממשיכים לעבוד אחרי --cli
    python main.py --cli --top 3 --days 3 --html C:\\temp\\schedule.html

הקובץ הזה בכוונה דק מאוד: כל ההיגיון נמצא ב-src/web/api.py (דפדפן) וב-src/cli.py
(טרמינל). כל מה שהוא עושה הוא (1) לוודא שאפשר להדפיס עברית, (2) להוסיף את src/
ל-sys.path כדי ש-"from models import ..." יעבוד, ו-(3) לנתב ל-webapp.main()
או ל-cli.main().

שכבת השאלות-והתשובות עברה לדפדפן; המנוע, הסקרייפר, מסד הנתונים ואימות השנה
נשארו בדיוק כפי שהיו ונקראים משם — לא נבנו מחדש.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. עברית ב-Windows: להכריח UTF-8 על הפלט.
#    Guarded — some consoles/pipes cannot be reconfigured, and that is fine.
# ---------------------------------------------------------------------------
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 2. src/ נכנס ל-sys.path — כל המודולים מייבאים זה את זה בסגנון "import models".
#    ROOT נכנס גם הוא, כדי ש-"import src.web.api" יעבוד מהדפדפן.
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
for _path in (SRC_DIR, ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

#: דגלים ששייכים רק לזרימת הטרמינל (src/cli.py). אם אחד מהם מופיע בלי --cli,
#: מסבירים ומריצים את הטרמינל במקום להיכשל על "unrecognized arguments".
CLI_ONLY_FLAGS = {
    "--refresh",
    "--offline",
    "--top",
    "--days",
    "--html",
    "--codes",
    "--semester",
    "--year",
    "--pick",
    "--track",
    "--untrack",
}


def _is_cli_flag(arg: str) -> bool:
    """האם הארגומנט הוא דגל של הטרמינל (גם בצורת --flag=value)?"""
    return arg.split("=", 1)[0] in CLI_ONLY_FLAGS


def run_cli(argv: list[str]) -> int:
    """מפעילה את הזרימה האינטראקטיבית בטרמינל, בדיוק כפי שהייתה."""
    import cli  # ייבוא אחרי תיקון sys.path (import after the path fix)

    return cli.main(argv)


def run_web(argv: list[str]) -> int:
    """מפעילה את אפליקציית הווב המקומית ומחזירה את קוד היציאה."""
    import webapp  # ייבוא אחרי תיקון sys.path

    return webapp.main(argv)


def main(argv: list[str] | None = None) -> int:
    """מנתבת בין הדפדפן (ברירת מחדל) לטרמינל (--cli). מחזירה קוד יציאה."""
    args = list(sys.argv[1:] if argv is None else argv)

    # --cli במפורש: כל השאר עובר כמו שהוא ל-src/cli.py, בלי שינוי בהתנהגות.
    if "--cli" in args:
        rest = list(args)
        rest.remove("--cli")
        return run_cli(rest)

    # דגל טרמינל בלי --cli: לא נכשלים ולא מנחשים בשקט — מודיעים ומריצים.
    leftovers = [a for a in args if _is_cli_flag(a)]
    if leftovers:
        print(
            "הדגלים "
            + " ".join(leftovers)
            + " שייכים לזרימת הטרמינל, ולכן היא זו שתרוץ."
        )
        print("(terminal-only flags detected — running the CLI flow)")
        print("להרצה מפורשת: python main.py --cli " + " ".join(args))
        print()
        return run_cli(args)

    return run_web(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # רשת ביטחון אחרונה — Ctrl+C לא יראה לסטודנט/ית traceback מפחיד.
        print()
        print("עצרת את התוכנית. להתראות! (interrupted — bye)")
        sys.exit(130)
