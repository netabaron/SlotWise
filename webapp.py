"""
webapp.py — מפעיל את בונה המערכת בדפדפן. (local web app launcher)

הרצה:
    python webapp.py                  # פורט 5000 (או הראשון הפנוי מעליו), פתיחת דפדפן
    python webapp.py --port 5005      # פורט מפורש
    python webapp.py --no-browser     # בלי לפתוח דפדפן
    python webapp.py --debug          # מצב פיתוח (הודעות שגיאה מלאות)

הקובץ הזה דק בכוונה, בדיוק כמו main.py: כל ההיגיון של האפליקציה נמצא
ב-src/web/api.py. כל מה שהוא עושה הוא (1) לוודא שאפשר להדפיס עברית,
(2) להוסיף את src/ ל-sys.path, (3) לבנות את האפליקציה דרך create_app(),
(4) לתפוס פורט פנוי, (5) להדפיס את הכתובת ולפתוח דפדפן, (6) להריץ.

כללי ברזל:
    • הקשבה על 127.0.0.1 בלבד — לעולם לא 0.0.0.0. השרת הזה משרת אדם אחד
      במחשב אחד, ואסור שיהיה נגיש מהרשת.
    • שום טיפול בסיסמאות כאן או בשכבת הווב. ההתחברות לידיעון נעשית בחלון
      דפדפן אמיתי של Playwright בלבד.
    • כל הודעה למשתמש: עברית קודם, אנגלית אחריה, בלשון ניטרלית.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. עברית ב-Windows: להכריח UTF-8 על הפלט.
#    Guarded — some consoles and pipes cannot be reconfigured, and that is fine.
# ---------------------------------------------------------------------------
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 2. נתיבים: גם ROOT (כדי ש-"import src.web.api" יעבוד) וגם src/
#    (כדי שהמודולים הקיימים ימשיכו לייבא זה את זה בסגנון "import store").
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
for _path in (SRC_DIR, ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

#: הכתובת היחידה שמותר להאזין עליה. (localhost only — never 0.0.0.0)
HOST = "127.0.0.1"
#: פורט ברירת המחדל, ועד כמה לטפס מעליו אם הוא תפוס.
DEFAULT_PORT = 5000
PORT_PROBE_LIMIT = 5010
#: כמה פורטים לנסות כשמבקשים פורט מפורש שאינו ברירת המחדל.
PORT_PROBE_SPAN = 10
#: אורך תור ההמתנה של השקע המאזין. (listen backlog)
LISTEN_BACKLOG = 128


# ---------------------------------------------------------------------------
# הדפסה
# ---------------------------------------------------------------------------
def print_box(title: str, lines: list[str], ch: str = "=") -> None:
    """מדפיסה תיבה פשוטה. (a plain ASCII box — safe in every console)"""
    width = 64
    print()
    print(ch * width)
    print(f"  {title}")
    print(ch * width)
    for line in lines:
        print(f"  {line}" if line else "")
    print(ch * width)
    print()


# ---------------------------------------------------------------------------
# פורטים
# ---------------------------------------------------------------------------
def bind_free_port(start: int, last: int, host: str = HOST) -> socket.socket | None:
    """תופסת את הפורט הפנוי הראשון בטווח ומחזירה שקע *מאזין*, או None.

    למה להחזיק את השקע ולא רק להחזיר מספר: אם רק בודקים שהפורט פנוי, סוגרים,
    ואז מבקשים מ-werkzeug להיצמד אליו שוב — נפתח חלון קטן שבו תוכנית אחרת
    יכולה לחטוף את הפורט. במקרה כזה werkzeug מדפיס שורה באנגלית וקורא בעצמו
    ל-sys.exit(1), כלומר ההסבר בעברית שכתוב כאן לא היה מגיע לעולם. כשמחזיקים
    את השקע ומוסרים אותו ל-werkzeug כמות שהוא, החלון הזה פשוט לא קיים.

    בכוונה בלי SO_REUSEADDR: ב-Windows הדגל הזה *מרשה* להיצמד לפורט תפוס,
    וזה בדיוק ההפך ממה שהתפיסה הזאת צריכה לעשות.
    """
    for port in range(start, last + 1):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((host, port))
            sock.listen(LISTEN_BACKLOG)
        except OSError:
            sock.close()
            continue
        return sock
    return None


def serve(app, sock: socket.socket, port: int, debug: bool = False) -> None:
    """מריצה את השרת על השקע שכבר תפוס בידינו. (serve on the socket we hold)

    בכוונה לא app.run(): app.run מבקש מ-werkzeug להיצמד לפורט מחדש, וזה מחזיר
    בדיוק את חלון החטיפה שהתיעוד של bind_free_port מתאר. make_server מקבל
    שקע מוכן דרך fd, ולכן לא נצמד לשום דבר ולא יכול ליפול על פורט תפוס.
    """
    from werkzeug.serving import make_server

    app.debug = bool(debug)
    application = app
    if debug:
        from werkzeug.debug import DebuggedApplication

        application = DebuggedApplication(app, evalex=True)

    try:
        server = make_server(HOST, port, application, threaded=True, fd=sock.fileno())
    except TypeError:
        # גרסת werkzeug שלא יודעת לקבל שקע מוכן — נסיגה להתנהגות הרגילה.
        sock.close()
        app.run(host=HOST, port=port, debug=debug, use_reloader=False)
        return

    try:
        server.serve_forever()
    finally:
        server.server_close()


def wait_and_open_browser(url: str, port: int, timeout: float = 12.0) -> None:
    """מחכה שהשרת יתחיל להאזין ואז פותחת דפדפן. (runs in a daemon thread)

    פותחים רק אחרי שהפורט באמת עונה, אחרת הדפדפן מקדים את השרת ומראה
    "לא ניתן להתחבר".
    """
    deadline = time.monotonic() + timeout
    opened = False
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, port), timeout=0.4):
                opened = True
                break
        except OSError:
            time.sleep(0.15)
    if opened:
        try:
            webbrowser.open(url)
            return
        except Exception:
            pass
    # השרת לא ענה בזמן, או שאין דפדפן ברירת מחדל — הכתובת כבר מודפסת למעלה.
    print("הדפדפן לא נפתח אוטומטית — יש לפתוח את הכתובת שלמעלה ידנית.")
    print("(could not auto-open the browser — open the URL above manually)")


# ---------------------------------------------------------------------------
# בניית האפליקציה
# ---------------------------------------------------------------------------
def load_create_app():
    """מייבאת את create_app משכבת הווב, עם הודעות ברורות אם משהו חסר.

    מחזירה את הפונקציה, או None אחרי שהדפיסה הסבר (ואז יוצאים עם 1).
    """
    # קודם Flask עצמו — זאת התקלה הנפוצה ביותר, ויש לה פתרון של שורה אחת.
    try:
        import flask  # noqa: F401
    except ImportError:
        print_box(
            "חסרה ספריית Flask  (Flask is not installed)",
            [
                "השרת המקומי זקוק ל-Flask. להתקנה:",
                "",
                "    python -m pip install flask",
                "",
                "(then run this again: python main.py)",
            ],
            ch="!",
        )
        return None

    try:
        try:
            from src.web.api import create_app  # type: ignore[import-not-found]
        except ImportError:
            from web.api import create_app  # type: ignore[import-not-found]
    except ImportError as exc:
        print_box(
            "שכבת הווב חסרה  (the web layer is missing)",
            [
                "לא נמצא הקובץ src/web/api.py עם הפונקציה create_app().",
                f"פרטים (detail): {exc}",
                "",
                "בינתיים אפשר להשתמש בזרימת הטרמינל:",
                "    python main.py --cli",
            ],
            ch="!",
        )
        return None
    except Exception as exc:
        # הקובץ קיים אבל נפל בזמן הטעינה: שגיאת תחביר, קובץ נתונים חסר,
        # שם שלא הוגדר. בלי הענף הזה מתקבל traceback באנגלית במקום הסבר.
        print_box(
            "שכבת הווב לא נטענה  (the web layer failed to load)",
            [
                "הקובץ src/web/api.py קיים, אבל נפל בזמן הטעינה:",
                "",
                f"    {type(exc).__name__}: {exc}",
                "",
                "בדרך כלל זו טעות הקלדה בקובץ הזה, או קובץ נתונים חסר.",
                "בינתיים אפשר להשתמש בזרימת הטרמינל:",
                "    python main.py --cli",
            ],
            ch="!",
        )
        return None
    return create_app


# ---------------------------------------------------------------------------
# דגלים
# ---------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    """בונה את מנתח הדגלים של המפעיל. (launcher flags)"""
    ap = argparse.ArgumentParser(
        prog="webapp",
        description="בונה המערכת בדפדפן (Braude schedule builder — local web app)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "דוגמאות (examples):\n"
            "  python main.py                 # דפדפן, פורט פנוי אוטומטית\n"
            "  python main.py --port 5005     # פורט מפורש\n"
            "  python main.py --no-browser    # בלי לפתוח דפדפן\n"
            "  python main.py --debug         # מצב פיתוח\n"
            "  python main.py --cli           # הזרימה הישנה בטרמינל\n"
        ),
    )
    ap.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"פורט להאזנה, ברירת מחדל {DEFAULT_PORT} (port; climbs upward if taken)",
    )
    ap.add_argument(
        "--no-browser",
        action="store_true",
        help="לא לפתוח דפדפן אוטומטית (do not open a browser)",
    )
    ap.add_argument(
        "--debug",
        action="store_true",
        help="מצב פיתוח — הודעות שגיאה מלאות, בלי טעינה מחדש (debug mode)",
    )
    return ap


# ---------------------------------------------------------------------------
# נקודת הכניסה
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """מפעילה את השרת המקומי. מחזירה קוד יציאה: 0 תקין, 1 שגיאה, 130 עצירה."""
    ap = build_arg_parser()
    args = ap.parse_args(argv)

    if not 1 <= args.port <= 65535:
        ap.error("--port חייב להיות בין 1 ל-65535  (--port must be 1..65535)")

    create_app = load_create_app()
    if create_app is None:
        return 1

    try:
        app = create_app()
    except Exception as exc:  # שגיאת הרכבה — להסביר, לא לזרוק traceback גולמי.
        print_box(
            "האפליקציה לא נבנתה  (create_app failed)",
            [
                f"{type(exc).__name__}: {exc}",
                "",
                "אפשר לבדוק שהתיקייה data/db קיימת, ולנסות:",
                "    python main.py --cli",
            ],
            ch="!",
        )
        return 1

    # ---- בחירת פורט --------------------------------------------------------
    requested = args.port
    last = PORT_PROBE_LIMIT if requested == DEFAULT_PORT else requested + PORT_PROBE_SPAN
    last = min(max(last, requested), 65535)
    sock = bind_free_port(requested, last)
    if sock is None:
        print_box(
            "אין פורט פנוי  (no free port)",
            [
                f"כל הפורטים בטווח {requested}-{last} תפוסים.",
                "אפשר לסגור תוכנית שמאזינה שם, או לבחור פורט אחר:",
                "    python main.py --port 5500",
            ],
            ch="!",
        )
        return 1

    port = sock.getsockname()[1]
    url = f"http://{HOST}:{port}"

    lines = [
        "בונה המערכת פועל. יש לפתוח את הכתובת הזאת בדפדפן:",
        "",
        f"    {url}",
        "",
        "(the schedule builder is running — open the URL above)",
    ]
    if port != requested:
        lines += [
            "",
            f"הערה: פורט {requested} היה תפוס, ולכן נבחר {port}.",
            f"(port {requested} was busy — using {port} instead)",
        ]
    lines += [
        "",
        "לעצירה: Ctrl+C בחלון הזה.  (press Ctrl+C here to stop)",
    ]
    print_box("בונה המערכת — דפדפן  (schedule builder — web)", lines)

    # ---- פתיחת דפדפן -------------------------------------------------------
    if not args.no_browser:
        threading.Thread(
            target=wait_and_open_browser, args=(url, port), daemon=True
        ).start()

    # ---- הרצה --------------------------------------------------------------
    #  בלי טעינה מחדש (use_reloader) בכוונה: היא מריצה את הקובץ הזה שוב,
    #  ואז תפיסת הפורט קורית פעמיים ועלולה לקפוץ לפורט אחר באמצע העבודה.
    try:
        serve(app, sock, port, debug=args.debug)
    except KeyboardInterrupt:
        print()
        print("השרת נעצר. להתראות!  (server stopped — bye)")
        return 130
    except (OSError, SystemExit) as exc:
        # הפורט כבר מוחזק, ולכן חטיפה באמצע כבר לא אפשרית — אבל אם השרת בכל
        # זאת לא עלה (חומת אש, או גרסת werkzeug אחרת שנפלה לנסיגת app.run),
        # מסבירים בעברית. SystemExit ולא רק OSError: werkzeug קורא בעצמו
        # ל-sys.exit(1) במקום לזרוק את ה-OSError הלאה.
        print_box(
            "השרת לא עלה  (the server could not start)",
            [
                f"{type(exc).__name__}: {exc}",
                "",
                "אפשר לנסות פורט אחר:",
                "    python main.py --port 5500",
            ],
            ch="!",
        )
        return 1
    finally:
        sock.close()

    print()
    print("השרת נעצר. להתראות!  (server stopped — bye)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        # רשת ביטחון אחרונה — Ctrl+C לא יראה traceback.
        print()
        print("השרת נעצר. להתראות!  (interrupted — bye)")
        sys.exit(130)
