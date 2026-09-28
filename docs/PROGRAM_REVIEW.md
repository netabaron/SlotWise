# SlotWise — Program Review Notes

Notes from a manual walkthrough of every study program (מסלול) on the site.

**Guiding principle for every item below:** a student should never need to open their official curriculum (תכנית לימודים) to use SlotWise. Anything the curriculum tells them — which semester to take electives, which courses belong to which specialization, how many credits per group — should be shown in the app itself.

**How to work through this file**
- Do not interrupt the current redesign phase from `docs/DESIGN.md`. Finish it, then start here.
- Any new UI (notes, badges, specialization pickers, explanations) must follow `docs/DESIGN.md` and the current design system — no one-off styling.
- The official curriculum is the source of truth. Verify every fix against it. Never invent numbers (credits, minimum courses, group sizes) — if a value can't be found in the curriculum, stop and ask.
- After fixing an issue in one program, check whether the same issue exists in other programs and fix it there too.
- For each item: find the root cause (scraper, parser, data file, or display logic) and fix it there, not with a hardcoded patch in the UI.
- Mark items `[x]` as they're done and add a one-line note on what was changed.
- Ask before removing any feature or making a change that affects how the solver picks courses.

---

## 1. Program naming

- [x] **Applied Mathematics is mislabeled.** The Applied Mathematics program shows as "with a specialization in Algorithmics & AI", but it is the regular Applied Mathematics program. Find where this label comes from and correct it. If the catalog genuinely contains two separate programs (regular and with the specialization), both must appear, each with its correct name.
  - *Done 2026-09-25:* the label came from the college website's program list (scraper, `programs.json`); the curriculum prints one program, "תוכנית הלימודים במתמטיקה שימושית", where AI is an elective domain. Both math curriculum files now carry `program_label`, and the API shows it; the id stays so saved selections still match. Only math differed.

## 2. Course naming

- [x] **Space between a course name and its number.** Some courses appear with the number glued to the name, e.g. `חדוא2` in Civil Engineering. Every course whose name ends with a number should have a space before it: `חדוא 2`. Apply this globally (all programs), ideally as a normalization step in the data pipeline.
  - *Done 2026-09-25:* the civil PDF extraction glued 12 numbers; `models.normalize_course_name` now runs when any curriculum file loads and when the yedion is parsed, and `civil.json` is fixed at rest. No other program had the problem.
- [x] **Truncated / abbreviated names in Biotechnology.** Year 4, Semester A shows `כתיבה מדעית ושימוש במאגרי מידע בביוט.` — the word should be written in full: `בביוטכנולוגיה`. Audit all programs for similar truncations (names ending in an abbreviation or a period) and restore the full names.
  - *Done 2026-09-25:* `biotech.json` had copied the yedion's names (cut at 40 characters) instead of the PDF's; 15 names now follow `biotech.pdf`. The student's own curriculum name now also wins in the lecturers step and timetable, and a cut-off yedion name is restored wherever any curriculum prints it in full (41711, 62015). Confirmed full names for 8 cut-off courses and the civil misspelling of 421223 are applied through `data/name_corrections.json` (2026-09-26); the other 12 are kept by decision. See `docs/PROGRAM_FINDINGS.md` §10.
- [x] **GMP course name.** A Biotechnology course is displayed as `דרישות רגולטוריות ו-GMP בביוטכ`. It should be displayed simply as `GMP`. Check the curriculum for the correct display name and use it.
  - *Done 2026-09-25:* `biotech.pdf` prints it as `GMP`, and it is now shown as `GMP` everywhere for biotech students.
- [x] **Physics 3 in Biotechnology.** Year 3, Semester B shows `פיזיקה 3ב` instead of `פיזיקה 3`. Check the curriculum and the catalog: if it's the same course, display it as `פיזיקה 3`; if they're genuinely different courses, make sure the one the curriculum requires for this program is the one shown.
  - *Done 2026-09-26:* same course (11027 in both sources); by decision all three biotech physics courses follow the yedion: `פיזיקה 1ב`, `פיזיקה 2ב`, `פיזיקה 3ב`.

## 3. Elective and general-course reminders

- [ ] **Colored "choose an elective" note.** Students can technically take electives at any pace, but the curriculum recommends specific semesters for them. In every semester where the curriculum says to take elective courses (קורסי בחירה), show a clearly visible, colored note such as "Choose an elective course" (in Hebrew in the UI). The student should learn this from SlotWise, not from their curriculum.
- [ ] **Same for general courses.** In every semester where the curriculum says to take a general course (קורס כללי), show the same kind of colored note: "Choose a general course".
- [ ] Apply both to all programs.

## 4. Specializations (מסלולי התמחות)

Several programs split into specializations, and the courses offered (mandatory and elective) depend on the specialization. Today the app doesn't handle this well enough, so students would have to check their curriculum. The goal is to make specialization a first-class part of the flow.

*Interim, 2026-09-25:* the generic "at least one course from each cluster" rule is now shown only where the curriculum states it (Software, Information Systems) and comes from the program's data file; Industrial and Applied Math show no rule until their real rules are added with the courses-step work.

### 4.1 Civil Engineering
- [ ] Let the student choose their specialization, and adjust the offered courses accordingly.
- [ ] Mark courses that are mandatory in the chosen specialization with a note like "Mandatory in the X specialization".
- [ ] Filter the elective courses by specialization group, and show the same explanation the curriculum gives: electives are organized in groups, there is a maximum of X credits (נ"ז) per group, and the student must take at least 2 courses. Take the exact rules and numbers from the curriculum.

### 4.2 Electrical Engineering
- [ ] Read the curriculum carefully and determine **when** the specialization is chosen — from the start of studies, or only from a specific semester.
- [ ] Based on the semester the student selects, require them to pick a specialization when it's relevant (e.g. if the specialization applies from year 4, a student entering year 4 must choose one), so the app knows which courses to offer.
- [ ] Mandatory courses and electives should both be filtered by the specialization, with notes like in Civil Engineering.

- *Decided 2026-09-26 (user):* sections 1–6 of the curriculum are common to everyone; the specialization and the design route are chosen from semester 7. The curriculum does not state this outright; it follows from its structure, and the user confirmed it. Rules:
  - **Main specialization:** ≥ 20 credits, with ≥ 4 core courses (Computers: ≥ 6 core, 3 hardware and 3 software).
  - **Secondary specialization:** ≥ 10 credits, with ≥ 3 core courses. Only for the research (מחקרי) and final-project (פרויקט גמר) routes.
  - Up to 3 credits from the multidisciplinary strip.
  - UI: see `docs/DESIGN.md` → Program, year and semester.

### 4.3 Industrial Engineering & Management, and Mechanical Engineering
- [ ] Both are organized by specializations as well. Apply the same approach: determine from the curriculum when the specialization is chosen, require the choice at the right point, and adjust mandatory courses, elective filtering and notes accordingly.

### 4.4 General
- [ ] Check every other program for specializations that aren't handled yet, and report what you find before implementing.
  - *Decided 2026-09-26 (user):* **Biotechnology** has no elective data, so no elective rules are shown for it.
- [ ] Keep the specialization picker consistent across programs (same component, same place in the flow, per `docs/DESIGN.md`).

## 5. The "other program — not relevant" option

- [ ] There's an option for "another program — not relevant". It's unclear what purpose it serves. Explain what it currently does and in which cases a student would need it. If it has no real use, propose removing it — ask before removing.
  - *Decided 2026-09-26 (user):* keep it, relabelled "לא מופיע ברשימה — עבודה מהקטלוג בלבד". See `docs/PROGRAM_FINDINGS.md` §9 for what it does.
  - *Decided 2026-09-27 (user):* relabelled "מסלול אחר". Behaviour unchanged.

## 6. Credit-total mismatches (moved out of the UI)

*Moved 2026-09-27.* Until now the courses step showed each of these explanations in full under "מומלצים לסמסטר X". Per `docs/DESIGN.md` (principle 6, and Courses → Credit-total mismatch) the interface now shows only "סך הנקודות המומלץ לסמסטר הזה שונה בין השנתון לידיעון". The texts below are the complete explanations, copied verbatim; they also remain in each semester's `note` in the data file. These are the semesters whose `reconciles` is `false`.

- **הנדסה אזרחית, סמסטר 7** (`data/curricula/civil.json`, `semesters.7.note`):
  > שורת סה"כ המודפסת היא טווח: 10-12.5 נ"ז (ליבה משותפת 7 + שורת "קורסי חובה בהתמחות" המודפסת 3.0-5.5 נ"ז). בפועל חפיפת המסלולים בסמסטר זה: מבנים 6 / ניהול הבנייה 3 נ"ז, כלומר 10–13 נ"ז. אי-התאמה: קצה הטווח העליון המודפס הוא 12.5 נ"ז אך בלוק מסלול מבנים לסמסטר זה מסתכם ב-6 נ"ז (421411 בטון דרוך 2.5 + 421412 בניית המהנדס 3.5), ולכן הסה"כ האמיתי הוא 13 נ"ז. הטעות היא במקור ולא בחילוץ: סכום חפיפת מסלול מבנים על פני סמסטרים 3-7 הוא 29.0 נ"ז בדיוק, כמודפס בעמוד "תוכניות הלימודים" ("24.0 – 29.0 נ"ז לימודי התמחות"); עם 5.5 במקום 6.0 הוא היה יוצא 28.5. הליבה המשותפת עצמה כן מסתדרת (10 − 3.0 = 12.5 − 5.5 = 7.0 נ"ז).
- **הנדסת ביוטכנולוגיה, סמסטר 6** (`data/curricula/biotech.json`, `semesters.6.note`):
  > שורת הסה"כ המודפסת היא 17.5 נ"ז, והסכום של השורות בעמודה הוא 15.5. המסמך מדפיס את 41197 (ביואינפורמטיקה ובינה מלאכותית) פעמיים באותה עמודה, והסה"כ המודפס סופר אותו פעמיים. כאן הוא נספר פעם אחת.
- **הנדסת ביוטכנולוגיה, סמסטר 8** (`data/curricula/biotech.json`, `semesters.8.note`):
  > הסה"כ המצטבר המודפס מחייב 23 נ"ז בסמסטר זה, והמסמך מונה בו קורס חובה אחד בלבד (41750, 16 נ"ז). ההפרש הוא קורסי בחירה, שהמסמך הזה — תוכנית קורסי החובה — אינו מפרט.
- **הנדסת מכונות, סמסטר 2** (`data/curricula/mechines.json`, `semesters.2.note`):
  > לא מסתדר. סכום השורות המחולצות = 22.0 נ"ז (או 19.5 בלי 22705), מול טווח מודפס 18.5-21.0 - עודף קבוע של 1.0 נ"ז בשני קצות הטווח. רוחב הטווח (2.5 נ"ז) מוסבר בדיוק על ידי 22705, אבל הפער של 1.0 נ"ז אינו מוסבר על ידי אף קבוצת חלופות בטבלה, וכל שורה בפני עצמה עקבית (נ"ז = ה + 0.5*(ת+מ)). גם ה המודפס (13-14) נמוך ב-1 מהמחושב (14-15). ההערכה: שורת הסה"כ מיושנת ביחס לשורת קורס שעודכנה - מהקובץ הזה לבדו אי אפשר להכריע איזו.
- **הנדסת מכונות, סמסטר 4** (`data/curricula/mechines.json`, `semesters.4.note`):
  > לא מסתדר. סכום השורות המחולצות = 22.0 נ"ז מול 21.0 נ"ז מודפס - עודף של 1.0 נ"ז. גם ה המחושב (16) גבוה ב-1 מהמודפס (15), בעוד ת (10) ומ (2) תואמים במדויק. כלומר לסכום המודפס חסרים בדיוק שיעור הרצאה אחד ו-1.0 נ"ז. אין בסמסטר קבוצת חלופות שיכולה להסביר זאת; כנראה סכום מיושן.
- **הנדסת מכונות, סמסטר 5** (`data/curricula/mechines.json`, `semesters.5.note`):
  > לא מסתדר. קורסי הליבה המשותפים (track ריק) = 15.0 נ"ז, וזה מה שמופיע בשדה total. קורסי החובה בהתמחות מוסיפים 3.0 נ"ז (תכן וייצור / ביומכניקה) או 3.5 נ"ז (מכטרוניקה / תעשייה מתקדמת), כלומר 18.0-18.5 נ"ז בסך הכל, מול טווח מודפס 18.5-19.5. שורת ההשמה "קורסי חובה בהתמחות" עצמה מודפסת 2.5-3.5 נ"ז בעוד טבלאות המסלולים נותנות 3.0-3.5. הגבול העליון המודפס (19.5) אינו בר-השגה באף אחד מארבעת המסלולים.
- **הנדסת מכונות, סמסטר 7** (`data/curricula/mechines.json`, `semesters.7.note`):
  > לא מסתדר. קורסי הליבה המשותפים = 9.0 נ"ז (22900 + 22921), וזה מה שמופיע בשדה total. קורסי החובה בהתמחות מוסיפים 2.5-3.0 נ"ז, כלומר 11.5-12.0 נ"ז בסך הכל, מול טווח מודפס 14.5-15. הפער הוא 3.0 נ"ז בדיוק, ושעות הסה"כ המודפסות (ה=4, ת=2-3, מ=1-3) עודפות בדיוק ב-ה=2, ת=1, מ=1 מעל המחושב. כלומר הסכום המודפס דורש קורס נוסף של 2/1/1 = 3.0 נ"ז שאינו מופיע בשום טבלה בפרק. מהקובץ הזה לבדו אי אפשר לדעת אם שורה חסרה או שהסכום מיושן.

## 7. Card and cluster notes shortened for the UI

*Done 2026-09-27, approved by the user.* Per `docs/DESIGN.md` principle 6 these notes were shortened (or emptied) in the data files. The original texts are kept here verbatim, since the notes themselves were changed at the source.

- `data/curricula/civil.json` — 11063 (סמ' 1)
  - Was: רמת האנגלית נקבעת לפי ציון פסיכומטרי/אמיר"ם באנגלית 85–99. 0 נ"ז.
  - Now: לציון באנגלית 85–99
- `data/curricula/civil.json` — 11064 (סמ' 1)
  - Was: רמת האנגלית נקבעת לפי ציון פסיכומטרי/אמיר"ם באנגלית 100–119, או לאחר סיום 11063. 0 נ"ז.
  - Now: לציון באנגלית 100–119, או אחרי 11063
- `data/curricula/civil.json` — 11061 (סמ' 4)
  - Was: רמת האנגלית נקבעת לפי ציון פסיכומטרי/אמיר"ם באנגלית 120–133, או לאחר סיום 11064.
  - Now: לציון באנגלית 120–133, או אחרי 11064
- `data/curricula/civil.json` — 421223 (סמ' 2)
  - Was: השם מודפס במקור "מבוא לאלגרומיתקה ותכנות"; במקומות אחרים בפרק נכתב "מבוא לאלגוריתמיקה ותכנות". נשמר כפי שמודפס בטבלת התוכנית.
  - Now: (removed)
- `data/curricula/civil.json` — 421214 (סמ' 4)
  - Was: השם מודפס במקור "מבני בטון12" — ככל הנראה "מבני בטון 1,2".
  - Now: (removed)
- `data/curricula/civil.json` — 421323 (סמ' 6)
  - Was: סמינר משותף לשני המסלולים ("סמינר בהנדסת ניהול הבנייה/הנדסת מבנים").
  - Now: סמינר משותף לשני המסלולים
- `data/curricula/civil.json` — 421410 (סמ' 7), 421415 (סמ' 8)
  - Was: שורת השעות מודפסת "-" בכל ארבע עמודות השעות במקור; 4.0 נ"ז.
  - Now: (removed)
- `data/curricula/civil.json` — 421412 (סמ' 7)
  - Was: 2.5+3.5=6.0 נ"ז בבלוק מסלול מבנים לסמסטר 7 — גבוה ב-0.5 נ"ז מהטווח המודפס. ראו note של הסמסטר.
  - Now: (removed)
- `data/curricula/biotech.json` — 11062 (סמ' 1), 11063 (סמ' 1), 11064 (סמ' 1), 11058 (סמ' 1)
  - Was: רמת האנגלית נקבעת לפי ציון פסיכומטרי/אמיר"ם, והסטודנט/ית נכנס/ת לשרשרת בנקודה אחת בלבד. כל ארבע הרמות מודפסות בסמסטר 1 במסמך, ולכן אף אחת מהן אינה מסומנת אוטומטית.
  - Now: (removed)
- `data/curricula/biotech.json` — 51728 (סמ' 6)
  - Was: המסמך מציין שהקורס אינו ניתן בסמסטר זה אלא בקיץ או בסמסטר ב'.
  - Now: לא ניתן בסמסטר הזה, רק בקיץ או בסמסטר ב׳
- `data/curricula/electronic.json` — 11063 (סמ' 1)
  - Was: רמת האנגלית נקבעת לפי ציון פסיכומטרי/אמיר"ם באנגלית (90-99). לשורה זו לא מודפסות נ"ז בשנתון (0).
  - Now: לציון באנגלית 90–99
- `data/curricula/electronic.json` — 251961 (סמ' 1)
  - Was: חובה ללמוד בשנה א' בסמסטר 1 או 2 (הערה 3 בשנתון). קוד הקורס הוא בן שש ספרות - 251961 - כמקובל בקורסי הלימודים הכלליים במשפחת 25xxxx.
  - Now: חובה בשנה א׳, בסמסטר 1 או 2
- `data/curricula/electronic.json` — 11064 (סמ' 2)
  - Was: נקבע לפי 11063 או ציון פסיכומטרי באנגלית 100-119. לשורה זו לא מודפסות נ"ז בשנתון (0).
  - Now: לציון באנגלית 100–119, או אחרי 11063
- `data/curricula/electronic.json` — 11057 (סמ' 3)
  - Was: נקבע לפי 11064 או ציון פסיכומטרי באנגלית 120-133. פטור מכל קורסי האנגלית לציון 134 ומעלה.
  - Now: לציון באנגלית 120–133, או אחרי 11064
- `data/curricula/electronic.json` — 31100 (סמ' 7)
  - Was: חלק א' של מסלול פרויקט גמר בתכן הנדסי. יש להירשם לשני חלקי התכן ההנדסי בסמסטרים עוקבים.
  - Now: חלק א׳ של פרויקט גמר; שני החלקים בסמסטרים עוקבים
- `data/curricula/electronic.json` — 31102 (סמ' 8)
  - Was: ניתן לבחור רק באחת משלוש אפשרויות התכן ההנדסי (3 נ"ז במסלול זה).
  - Now: אפשר לבחור רק באחת משלוש אפשרויות התכן ההנדסי
- `data/curricula/electronic.json` — 31103 (סמ' 8)
  - Was: ניתן לבחור רק באחת משלוש אפשרויות התכן ההנדסי (5 נ"ז במסלול זה).
  - Now: אפשר לבחור רק באחת משלוש אפשרויות התכן ההנדסי
- `data/curricula/electronic.json` — 31104 (סמ' 8)
  - Was: ניתן לבחור רק באחת משלוש אפשרויות התכן ההנדסי (7 נ"ז במסלול זה).
  - Now: אפשר לבחור רק באחת משלוש אפשרויות התכן ההנדסי
- `data/curricula/mechines.json` — 11063 (סמ' 1)
  - Was: ציון פסיכומטרי באנגלית 85-99. שיבוץ לפי ציון פסיכומטרי באנגלית; שרשרת האנגלית חייבת להסתיים עד תום סמסטר 4.
  - Now: לציון באנגלית 85–99
- `data/curricula/mechines.json` — 11064 (סמ' 1)
  - Was: ציון פסיכומטרי באנגלית 100-119, או אחרי 11063. מופיע גם בסמסטר 2. שיבוץ לפי ציון פסיכומטרי באנגלית; שרשרת האנגלית חייבת להסתיים עד תום סמסטר 4.
  - Now: לציון באנגלית 100–119, או אחרי 11063
- `data/curricula/mechines.json` — 11064 (סמ' 2)
  - Was: ציון פסיכומטרי באנגלית 100-119, או אחרי 11063. מופיע גם בסמסטר 1. שיבוץ לפי ציון פסיכומטרי באנגלית; שרשרת האנגלית חייבת להסתיים עד תום סמסטר 4.
  - Now: לציון באנגלית 100–119, או אחרי 11063
- `data/curricula/mechines.json` — 11179 (סמ' 1)
  - Was: ניתן פטור למי שלמד פיזיקה 5 יח"ל בציון 75 ומעלה או שעבר מכינת קדם-הנדסה. 0 נ"ז.
  - Now: פטור ל-5 יח״ל פיזיקה בציון 75+ או למכינה
- `data/curricula/mechines.json` — 22705 (סמ' 1)
  - Was: מומלץ בסמסטר 1 לבעלי פטור מ-11179 בלבד; אחרת נלמד בסמסטר 2. נלמד פעם אחת בלבד.
  - Now: בסמסטר 1 רק למי שפטור מ-11179
- `data/curricula/mechines.json` — 22705 (סמ' 2)
  - Was: מופיע גם בסמסטר 1; מי שפטור מ-11179 לומד אותו בסמסטר 1. נלמד פעם אחת בלבד.
  - Now: מי שפטור מ-11179 לומד אותו בסמסטר 1
- `data/curricula/mechines.json` — 11360 (סמ' 1), 11360 (סמ' 2)
  - Was: ציון מבחן יע"ל 100-119. שיבוץ לפי ציון מבחן יע"ל; ציון 134 ומעלה - פטור משני קורסי עלמ"א.
  - Now: לציון יע״ל 100–119
- `data/curricula/mechines.json` — 11361 (סמ' 1)
  - Was: ציון מבחן יע"ל 120-133, או אחרי עלמ"א א'. מופיע גם בסמסטר 2. שיבוץ לפי ציון מבחן יע"ל; ציון 134 ומעלה - פטור משני קורסי עלמ"א.
  - Now: לציון יע״ל 120–133, או אחרי עלמ״א א׳
- `data/curricula/mechines.json` — 11361 (סמ' 2)
  - Was: ציון מבחן יע"ל 120-133, או אחרי עלמ"א א'. שיבוץ לפי ציון מבחן יע"ל; ציון 134 ומעלה - פטור משני קורסי עלמ"א.
  - Now: לציון יע״ל 120–133, או אחרי עלמ״א א׳
- `data/curricula/mechines.json` — 11061 (סמ' 3)
  - Was: ציון פסיכומטרי באנגלית 120-133, או אחרי 11064. שיבוץ לפי ציון פסיכומטרי באנגלית; שרשרת האנגלית חייבת להסתיים עד תום סמסטר 4.
  - Now: לציון באנגלית 120–133, או אחרי 11064
- `data/curricula/infosystems.json` — 11063 (סמ' 1)
  - Was: נלמד לפי ציון פסיכומטרי באנגלית 90-99. 0 נ"ז. שרשרת קורסי האנגלית מפורטת בפרק היחידה ללימודי אנגלית; יש לסיים אותה עד סוף סמסטר 4.
  - Now: לציון באנגלית 90–99
- `data/curricula/infosystems.json` — 11064 (סמ' 1)
  - Was: נלמד לפי ציון פסיכומטרי באנגלית 100-119, או אחרי 11063 אנגלית בסיסי. 0 נ"ז.
  - Now: לציון באנגלית 100–119, או אחרי 11063
- `data/curricula/infosystems.json` — 11360 (סמ' 1)
  - Was: נדרש למי שקיבל 100-119 בבחינת יע"ל. 0 נ"ז. ציון 120-133 – מתחילים ישירות בעלמ"א ב'; ציון 134 ומעלה – פטור משניהם.
  - Now: לציון יע״ל 100–119
- `data/curricula/infosystems.json` — 251961 (סמ' 1)
  - Was: הקוד מודפס בשנתון כ-251961, שש ספרות, בניגוד לכל שאר הקודים. כך הוא מופיע גם בהערת השוליים בשנתון ("סימול קורס251961"). לא תוקן.
  - Now: (removed)
- `data/curricula/infosystems.json` — ספורט (סמ' 1)
  - Was: שורה ללא קוד קורס בתוכנית, מודפסת "ספורט 1". חובה לקחת קורס ספורט אחד במהלך הלימודים בהיקף 1.0 נ"ז.
  - Now: קורס ספורט אחד, 1 נ״ז, במהלך התואר
- `data/curricula/infosystems.json` — 11060 (סמ' 2)
  - Was: נדרש למי שסיים 11064 או בעל ציון פסיכומטרי באנגלית 120-133. מי שקיבל 134 ומעלה פטור ועובר ישירות ל-11069, ואז הסמסטר קטן ב-2.0 נ"ז. הקורס נספר בסכום המודפס ולכן נספר גם כאן.
  - Now: לציון באנגלית 120–133 או אחרי 11064; ציון 134+ פטור
- `data/curricula/infosystems.json` — 11361 (סמ' 2)
  - Was: נדרש למי שקיבל 120-133 בבחינת יע"ל, או אחרי עלמ"א א'. 0 נ"ז. שורת סה"כ של הסמסטר מודפסת במפורש "ללא עלמ"א ב'".
  - Now: לציון יע״ל 120–133, או אחרי עלמ״א א׳
- `data/curricula/infosystems.json` — 51957 (סמ' 3)
  - Was: קיים קורס חליפי של המחלקה להנדסת תעשייה וניהול: "מבוא למערכות ארגוניות", סימול 51431.
  - Now: יש קורס חלופי: 51431
- `data/curricula/infosystems.json` — 61832 (סמ' 3)
  - Was: מהווה קורס חליפי לקורס "הסתברות" סימול 51709, החל משנה"ל תשפ"ו.
  - Now: חלופי ל-51709, מתשפ״ו
- `data/curricula/infosystems.json` — 61181 (סמ' 4)
  - Was: למי שיש לו פטור מפיזיקה אקדמית. חלופה ל-61179+61180, ולא בנוסף להם.
  - Now: רק למי שפטור מפיזיקה אקדמית, במקום 61179+61180
- `data/curricula/infosystems.json` — 61836 (סמ' 5)
  - Was: מהווה קורס חליפי לקורס "סטטיסטיקה למערכות מידע", סימול 51956 כפי שמודפס בשנתון, החל משנה"ל תשפ"ו.
  - Now: חלופי ל-51956, מתשפ״ו
- `data/curricula/infosystems.json` — קורס כללי (סמ' 5)
  - Was: קורס מלימודים כלליים. סה"כ 6 נ"ז לימודים כלליים לאורך התואר, שלושה קורסים (מודפס בשנתון כ"קורס כללי 1").
  - Now: אחד משלושה קורסים כלליים (6 נ״ז בתואר)
- `data/curricula/infosystems.json` — קורס כללי (סמ' 6)
  - Was: קורס מלימודים כלליים. סה"כ 6 נ"ז לימודים כלליים לאורך התואר, שלושה קורסים (מודפס בשנתון כ"קורס כללי 2").
  - Now: אחד משלושה קורסים כלליים (6 נ״ז בתואר)
- `data/curricula/infosystems.json` — קורס כללי (סמ' 7)
  - Was: קורס מלימודים כלליים. סה"כ 6 נ"ז לימודים כלליים לאורך התואר, שלושה קורסים (מודפס בשנתון כ"קורס כללי 3").
  - Now: אחד משלושה קורסים כלליים (6 נ״ז בתואר)
- `data/curricula/infosystems.json` — 62028 (סמ' 6)
  - Was: מחליף את הקורס "ניהול פרויקטי תוכנה" סימול 61762 החל מסמסטר א' תשפ"ז, וגם כקורס קדם לפרויקט המסכם.
  - Now: מחליף את 61762 מסמסטר א׳ תשפ״ז
- `data/curricula/infosystems.json` — 61998 (סמ' 7)
  - Was: פרויקט מסכם שלב א'. 4.0 נ"ז ללא שעות מודפסות.
  - Now: פרויקט מסכם שלב א׳
- `data/curricula/infosystems.json` — 61999 (סמ' 8)
  - Was: פרויקט מסכם שלב ב'. 4.0 נ"ז ללא שעות מודפסות.
  - Now: פרויקט מסכם שלב ב׳
- `data/curriculum.json` — 61912 (סמ' 3)
  - Was: בוטל החל מסמסטר א' תשפ"ז (2027). חליפי: 62018 מבוא לארכיטקטורה ומבנה המחשב (קדם 61740, 61745)
  - Now: בוטל מסמסטר א׳ תשפ״ז; במקומו 62018
- `data/curriculum.json` — 61998 (סמ' 7)
  - Was: 61180 או 61181. 11129 בוטל כקדם לתשפ"ד ואילך.
  - Now: קדם: 61180 או 61181
- `data/curricula/industry.json` — 11063 (סמ' 1), 11064 (סמ' 1), 11059 (סמ' 2)
  - Was: רמת האנגלית נקבעת לפי ציון פסיכומטרי/אמיר"ם, והסטודנט/ית נכנס/ת לשרשרת בנקודה אחת בלבד.
  - Now: (removed)
- `data/curricula/math-spring.json` — 11360 (סמ' 1), 11361 (סמ' 1)
  - Was: עברית למטרות אקדמיות נדרשת רק לפי ציון יע"ל: 100-119 מתחיל/ה בעלמ"א א', 120-133 בעלמ"א ב', ו-134 ומעלה פטור/ה משתיהן. לכן הקורס אינו מסומן אוטומטית.
  - Now: לפי יע״ל: 100–119 עלמ״א א׳, 120–133 עלמ״א ב׳
- `data/curricula/math-winter.json` — 11360 (סמ' 1), 11361 (סמ' 1)
  - Was: עברית למטרות אקדמיות נדרשת רק לפי ציון יע"ל: 100-119 מתחיל/ה בעלמ"א א', 120-133 בעלמ"א ב', ו-134 ומעלה פטור/ה משתיהן. לכן הקורס אינו מסומן אוטומטית.
  - Now: לפי יע״ל: 100–119 עלמ״א א׳, 120–133 עלמ״א ב׳
- `data/curricula/math-spring.json` — 11063 (סמ' 1), 11064 (סמ' 1), 11059 (סמ' 2)
  - Was: רמת האנגלית נקבעת לפי ציון פסיכומטרי/אמיר"ם, והסטודנט/ית נכנס/ת לשרשרת בנקודה אחת בלבד. כל הרמות מודפסות באותו סמסטר במסמך, ולכן אף אחת מהן אינה מסומנת אוטומטית. יש לסיים את שרשרת האנגלית עד סמסטר 4.
  - Now: (removed)
- `data/curricula/math-winter.json` — 11063 (סמ' 1), 11064 (סמ' 1), 11059 (סמ' 2)
  - Was: רמת האנגלית נקבעת לפי ציון פסיכומטרי/אמיר"ם, והסטודנט/ית נכנס/ת לשרשרת בנקודה אחת בלבד. כל הרמות מודפסות באותו סמסטר במסמך, ולכן אף אחת מהן אינה מסומנת אוטומטית. יש לסיים את שרשרת האנגלית עד סמסטר 4.
  - Now: (removed)
- `data/curricula/math-spring.json` — 11179 (סמ' 1)
  - Was: סטודנטים שלמדו פיזיקה ברמה של 5 יח"ל בציון 75 ומעלה פטורים מהקורס. הקורס ניתן גם בסמסטר קיץ.
  - Now: פטור ל-5 יח״ל פיזיקה בציון 75+. ניתן גם בקיץ
- `data/curricula/math-winter.json` — 11179 (סמ' 1)
  - Was: סטודנטים שלמדו פיזיקה ברמה של 5 יח"ל בציון 75 ומעלה פטורים מהקורס. הקורס ניתן גם בסמסטר קיץ.
  - Now: פטור ל-5 יח״ל פיזיקה בציון 75+. ניתן גם בקיץ
- `data/curricula/math-winter.json` — 11121 (סמ' 2)
  - Was: המסמך מציין בהערת שוליים שבשנת תשפ"ו הקורס יהיה 2.5 נ"ז במקום 3.0.
  - Now: מתשפ״ו: 2.5 נ״ז במקום 3
- `data/curricula/math-spring.json` — elective chip "תורת המספרים ויישומים להצפנה", elective chip "תורת הגרפים", elective chip "קומבינטוריקה", elective chip "קורס בחירה של מומחה מהתעשייה", elective chip "טופולוגיה"
  - Was: קורס חדש בשנתון — טרם הוקצה לו מספר קורס.
  - Now: קורס חדש, עדיין בלי מספר קורס
- `data/curricula/math-winter.json` — elective chip "תורת המספרים ויישומים להצפנה", elective chip "תורת הגרפים", elective chip "קומבינטוריקה", elective chip "קורס בחירה של מומחה מהתעשייה", elective chip "טופולוגיה"
  - Was: קורס חדש בשנתון — טרם הוקצה לו מספר קורס.
  - Now: קורס חדש, עדיין בלי מספר קורס
- `data/curricula/math-spring.json` — elective chip "רשתות מורכבות"
  - Was: קורס חדש בשנתון — טרם הוקצה לו מספר קורס. בשנתון מסומן גם "תורת הגרפים" כמומלץ, עם סימן שאלה.
  - Now: קורס חדש, עדיין בלי מספר קורס
- `data/curricula/math-winter.json` — elective chip "רשתות מורכבות"
  - Was: קורס חדש בשנתון — טרם הוקצה לו מספר קורס. בשנתון מסומן גם "תורת הגרפים" כמומלץ, עם סימן שאלה.
  - Now: קורס חדש, עדיין בלי מספר קורס
- `data/curricula/math-spring.json` — elective chip "אפידמיולוגיה מתמטית"
  - Was: קורס חדש בשנתון — טרם הוקצה לו מספר קורס. נ"ז אינן מודפסות. הקדמים מודפסים כטקסט ועם סימן שאלה: מד"ר, מבוא לאנליזה.
  - Now: קורס חדש, עדיין בלי מספר קורס
- `data/curricula/math-winter.json` — elective chip "אפידמיולוגיה מתמטית"
  - Was: קורס חדש בשנתון — טרם הוקצה לו מספר קורס. נ"ז אינן מודפסות. הקדמים מודפסים כטקסט ועם סימן שאלה: מד"ר, מבוא לאנליזה.
  - Now: קורס חדש, עדיין בלי מספר קורס
- `data/curricula/math-spring.json` — elective chip "תהליכים אקראיים עם יישומים ל-AI"
  - Was: מחליף את "תהליכים אקראיים מש". טרם הוקצה לו מספר קורס.
  - Now: קורס חדש, עדיין בלי מספר קורס
- `data/curricula/math-winter.json` — elective chip "תהליכים אקראיים עם יישומים ל-AI"
  - Was: מחליף את "תהליכים אקראיים מש". טרם הוקצה לו מספר קורס.
  - Now: קורס חדש, עדיין בלי מספר קורס
- `data/curricula/math-winter.json`, `data/curricula/math-spring.json` — `notes` (above the elective clusters)
  - Was: הנ"ז ותנאי הקדם של קורסי הבחירה עשויים להשתנות בהתאם להחלטות המחלקה שהקורס שייך אליה, כפי שכתוב בשנתון.
  - Now: הנ״ז והקדמים עשויים להשתנות בהתאם להחלטות המחלקה
- `data/curricula/industry.json` — rules `do-internship-special-list`, `do-project-special-list`: `notes` became `course_notes` (shown on 51170's card)
  - Was: 51170 מיועד לסטודנטים באחוזון ציונים של 80% ומעלה, באישור רמ"ח בלבד.
  - Now: לאחוזון 80 ומעלה, באישור רמ״ח
- `data/name_corrections.json` — 51170 and 51156 had no name (not in the catalog, not in any elective list). Added 2026-09-27 from `industry.pdf`: 51170 "נושא אישי 1" (p. 13, also p. 14), 51156 "מבוא להנדסת מערכות שירות" (p. 14). Neither line prints credits, so they show "—".

## 8. Inconsistencies inside the curriculum PDFs

*Recorded 2026-09-28.* Places where a PDF contradicts itself. The data follows one side on purpose; nothing is missing, and nothing here is to be "fixed" without a decision.

- **Industrial, 51156 "מבוא להנדסת מערכות שירות"** (`industry.pdf`). The final-project route's list of courses from which at least two electives must come (p. 14, shown in the app as "רשימת בחירה מחייבת") marks 51156 as "(אשכול תכן ותפעול)". But 51156 does not appear in the תכן ותפעול cluster's table itself. `data/curricula.json` follows the table, so 51156 is not in that cluster box; it appears only in "רשימת בחירה מחייבת" (final-project route). Data not changed.
