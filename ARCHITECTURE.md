# ארכיטקטורה — SlotWise

צינור אחד, בכיוון אחד: דף HTML מהידיעון נכנס בצד אחד, מערכת שעות מדורגת
יוצאת בצד השני. כל שלב מוסר מבנה נתונים אחד לשלב הבא.

---

## הזרימה

```mermaid
flowchart TD
    A["הידיעון<br/>info.braude.ac.il/yedion/fireflyweb.aspx<br/>prgname=S_LOOK_FOR_NOSE"]
    B["שליפה ב-HTTP, בלי התחברות<br/>src/yedion_http.py<br/>YedionHTTP.fetch_course()"]
    C["HTML גולמי על הדיסק<br/>data/raw/61753_1.html<br/>572 דפי קורס"]
    D["פענוח<br/>src/parser.py<br/>parse_course_page()"]
    E["אובייקטים<br/>src/models.py<br/>Meeting ⊂ Group ⊂ Course"]
    F["אחסון<br/>src/store.py<br/>data/db/sections.json"]
    G["קטלוג שנשלח עם הקוד<br/>src/shipped_catalog.py<br/>data/catalog/catalog.jsonl"]
    H["פתרון וניקוד<br/>src/scheduler.py<br/>enumerate_selections() → solve()"]
    I["API<br/>src/web/api.py · POST /api/solve<br/>webapp.py · 127.0.0.1<br/>wsgi.py · gunicorn · מאורח"]
    J["דפדפן<br/>src/web/templates/index.html<br/>src/web/static/app.js"]
    R(["refresh.py — מתזמן את 2→6"])

    A -->|"GET אחד לכל קוד קורס"| B
    B -->|"נשמר לדיסק לפני כל פירסור"| C
    C -->|"טקסט HTML"| D
    D -->|"ParseResult(course, warnings)"| E
    E -->|"save_course()"| F
    G -.->|"שכבת בסיס מתחת למסד"| F
    C -.->|"build_catalog.py · עבודת cron"| G
    F -->|"list[Course]"| H
    H -->|"list[ScoredSchedule]"| I
    I -->|"JSON"| J
    R -.-> B
    R -.-> D
    R -.-> F
```

---

## שלב אחר שלב

1. **הידיעון** — מקור האמת של המכללה. **מסך חיפוש הקורסים קריא בלי התחברות**
   (`S_LOOK_FOR_NOSE`); מוסר דף HTML אחד לכל קוד קורס.
2. **שליפה · `src/yedion_http.py`** — ספריית תקן בלבד: חימום, החלפת שנה, אימות
   שהשנה נתפסה, ואז GET לכל קוד; מוסר מחרוזת HTML.
   **שומרים את הדף לפני שמפענחים אותו — כדי שאפשר יהיה לתקן באג בפרסר ולהריץ
   מחדש בלי לגעת בשרת של המכללה.**
3. **HTML גולמי · `data/raw/`** — 572 דפי קורס (ועוד דפי פרטים, קטלוג וסשן);
   מוסר טקסט לפרסר, ומאפשר לפענח הכול מחדש בלי לגעת ברשת.
4. **פענוח · `src/parser.py`** — `parse_course_page()` מוציא מהדף קבוצות, מרצים,
   ימים, שעות, בניינים וחדרים; מוסר `ParseResult` — קורס ורשימת אזהרות.
5. **אובייקטים · `src/models.py`** — `Meeting` בתוך `Group` בתוך `Course`; מוסר
   את המבנה היחיד שכל שאר הקוד מדבר בו.
6. **אחסון · `src/store.py`** — `save_course()` / `load_all()` כותבים וקוראים את
   `data/db/sections.json`; מוסר `list[Course]`.
7. **פתרון · `src/scheduler.py`** — `enumerate_selections()` מונה בבקטרקינג כל
   בחירה חוקית, `solve()` מנקד כל אחת ושומר את הטובות; מוסר `list[ScoredSchedule]`.
8. **API · `src/web/api.py`** — Flask; `POST /api/solve` מקבל קודים והעדפות
   ומחזיר JSON. שני מפעילים: `webapp.py` לשימוש מקומי (‏`127.0.0.1` בלבד),
   ו-`wsgi.py` תחת gunicorn לאירוח.
9. **דפדפן · `index.html` + `app.js`** — HTML/CSS/JS רגילים, בלי פריימוורק ובלי
   שלב בנייה; מקבל JSON ומצייר את הגריד.

---

## שלוש החלטות

**למה זה היה מקומי, ומה השתנה.** ‏המצב של הסטודנט/ית יושב ב-`localStorage`
ולא בשרת, ולכן לא היה מה לארח; ובכיוון השני `POST /api/scrape/start` היה בלי
הזדהות ובלי מגן קצב — מאורח, הוא ממסר פתוח אל השרת של המכללה. שתי הסיבות
האלה הן שקשרו את `webapp.py` ל-`127.0.0.1` בלבד.

‏**הסיבה השנייה בוטלה ב-2026-09-16:** נקודות הקצה של הגרידה החיה הוסרו,
`wsgi.py` מקבע `allow_network=False`, ובניית הקטלוג עברה לעבודת cron נפרדת.
הראשונה עדיין נכונה ועדיין רצויה — אין חשבונות ואין מצב פר-משתמש בשרת.
‏`webapp.py` נשאר מקומי בלבד; האירוח הוא דרך `wsgi.py`. ראו `HOSTING_NOTES.md`
ו-`DEPLOY.md`.

**למה הקטלוג נשלח עם הקוד.** `data/db/` ו-`data/raw/` שניהם ב-`.gitignore`, ולכן
שכפול נקי היה עולה עם אפס קורסים; `data/catalog/catalog.jsonl` נכנס לגיט,
ו-`Store._load_sections_db()` מניח אותו כשכבת בסיס שהנתונים של המשתמש/ת דורסים.
‏הוא נבנה פעם אחת ביד; מאז ‏2026-09-16 הוא הפלט של
`.github/workflows/build-catalog.yml`.

**למה מנייה ממצה ולא היוריסטיקה.** רק מי שספר את כל הצירופים יכול לומר "אין
מערכת שעונה על הדרישות", "ארבעה ימים בלתי אפשריים, המינימום הוא חמישה" ו"אלו
באמת חמש הטובות ביותר" — היוריסטיקה מחזירה מערכת אחת סבירה ואינה יכולה להוכיח
אף אחת מהשלוש.
