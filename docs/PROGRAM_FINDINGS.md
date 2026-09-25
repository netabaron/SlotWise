# Program findings — research for `PROGRAM_REVIEW.md` sections 3, 4 and 5

Research only. Written 2026-09-25, before the UI for these sections is designed. **No code was changed
for sections 3–5.**

**Sources.** The official curriculum PDFs in the repo root are the source of truth: `civil.pdf`,
`electric.pdf`, `mecho.pdf`, `industry.pdf`, `sw.pdf`, `system.pdf`, `biotech.pdf` and
`SHANTON MATH NOV 2025 .pdf`. Every table cited below was checked against a rendered image of its page,
not only against the extracted text, because right-to-left tables come out of the text layer scrambled.
Page numbers are PDF pages counted from 1. Where the chapter prints its own page number, it is given as `[n]`.

**Conventions.**
- A number is given only when the PDF prints it, and the quote says where it comes from.
- **Not in the PDF** means we searched for it and it isn't there. Nothing below fills such a gap by guessing.
- **Inference** marks a conclusion drawn from the layout rather than stated in the PDF.

**Data status**, used in every table:
- **in repo**: the data is already in a named file and field.
- **parser**: extractable from the PDF automatically, but no parser does it yet.
- **by hand**: prose or a judgement call. It has to be entered by hand, with its citation.

---

## Summary

| Program | Specializations | Chosen / diverge | Elective rule the PDF states | Elective slots in the plan | General-course slots |
|---|---|---|---|---|---|
| Civil | 2: מבנים, ניהול הבנייה | Not stated. The tables diverge in sem. 3 (inference: after year 1) | Structures: group 1 ≥ 2 courses, group 2 ≥ 1, "עד צבירה של כ-9 נק"ז". Management: "עד צבירה של כ-14 נק"ז" | None printed. "בשנתיים האחרונות"; sem. 7–8 totals "ללא קורסי בחירה" | "ניתן לשלבם בכל סמסטר" |
| Electrical | 3: מחשבים, עיבוד אותות ותקשורת, התקנים ואלקטרו-אופטיקה | Not stated. Sem. 1–6 are common; specialization studies run "במקביל" to the sem. 7–8 design | Main ≥ 20 credits incl. ≥ 4 core (computers ≥ 6: 3 hardware + 3 software). Secondary ≥ 10 incl. ≥ 3 core, **only** for the research and final-project routes. ≤ 3 credits from the multidisciplinary strip | None printed | "ניתן לשלב קורסים אלה בכל סמסטר" |
| Mechanical | 4: תכן וייצור, מכטרוניקה, ביומכניקה, תעשייה מתקדמת | Not stated. Conditioned on 18 foundation courses; the tables diverge in sem. 5 (inference: after sem. 4) | 28.5 credits in the specialization, of which "עד צבירה של 20" from its own list. Entrepreneurship ≤ 4 credits | None printed. Lists are "לסמסטרים 5–8" | "לאורך כל תקופת הלימודים" |
| Industrial | 2: מדעי הנתונים, תכן ותפעול | "עד סוף שנה א'"; diverge in sem. 3 | DS: ≥ 4 / ≥ 2 / ≥ 1 per cluster. D&O: ≥ 7 or ≥ 8 courses by route, with per-cluster minimums and ≥ 2 from a special list. 251xxx ≤ 3 credits. Exactly 1 science & technology course | DS sem. 7; D&O sem. 7 and 8 | "לאורך כל תקופת הלימודים" |
| Software | none | — | ≥ 1 course per cluster (6 clusters). One entrepreneurship course only | sem. 7, 8 | כללי 1 + ספורט in sem. 1; כללי 2 in sem. 4; כללי 3 in sem. 6 |
| Information Systems | none | — | ≥ 1 course per cluster (3 clusters). ≥ 1 English seminar. One entrepreneurship course only | sem. 7, 8 | ספורט in sem. 1; כללי 1, 2, 3 in sem. 5, 6, 7 |
| Applied Math | none. "AI" and "algorithms" are elective **domains** | — | ≥ 3.0 credits of "בחירה מתמטיים". 201198 / 61957: one only. **No per-domain rule** | winter and spring intakes: sem. 4, 5, 6 | "לאורך כל תקופת הלימודים"; spring intake only: "מומלץ... בסמ' 1+2+3" |
| Biotechnology | none | — | none: the PDF lists mandatory courses only | none | none |

**Bugs in what the repo serves today.** Only #1 has been fixed since (2026-09-25).
1. **Fixed 2026-09-25.** `/program/electives` hard-coded the rule `"יש לקחת קורס אחד לפחות מכל אשכול."`, in `src/web/api.py` (the `cluster_rule` of the math fallback and of the chapter branch).
   - Math: the PDF never states that rule.
   - Industrial: the real rule is 4 / 2 / 1 per cluster, or 7–8 courses. "One from each" understates it.
   - Now the rule is a `cluster_rule` field in the program's curriculum file, with its source. Only Software and Information Systems have one; Industrial and Math show no rule until their real rules are entered.
2. `data/curricula.json` (built by `src/shnaton.py`) has wrong elective lists for three programs:
   - Civil: 4 "tracks" instead of 2; groups 1 and 2 merged; 51600 missing.
   - Mechanical: 4 courses missing; the shared enrichment list is filed under Industry 4.0 only.
   - Industrial: the two specializations' printings are merged; 51916 is missing; 251966 is filed in the wrong cluster; most 251xxx rows are missing.

   The cause is the same in all three. `shnaton.py` recognises only headings that start with "אשכול" or "מסלול". It misses "קבוצה N:", "קורסי העשרה לכלל ההתמחויות", "קורסי בחירה בהתמחות", "תחום X", and Electrical's bare specialization names. Electrical therefore comes out as `structure: "flat"`.
3. The PDF's placeholder rows ("קורסי בחירה", "קורס כללי N", "ספורט") are recorded inconsistently:
   - Software: `code: null` rows plus `plus: "קורסי בחירה"`.
   - Information Systems: general and sport rows only; the elective rows survive only in the semester `note`.
   - Math: the elective rows were dropped on purpose.
   - Industrial: not recorded.

---

## 1. Civil Engineering — `civil.pdf`, `data/curricula/civil.json`

### Specializations and when they're chosen

p. 2: "התוכנית כוללת, בשלב זה, שתי התמחויות מתחום ההנדסה האזרחית:"
- **תכן מבנים** (the tables call it "מסלול מבנים" / "מסלול הנדסת מבנים").
- **הנדסת ניהול הבנייה** ("מסלול ניהול הבנייה" / "מסלול להנדסת ניהול הבנייה").
- The same page: "ההתמחות אינה נרשמת על גבי תעודת התואר אלא מופיעה בגיליון הציונים".
- **Admission criteria**, also p. 2:
  - "בהתמחות תכן מבנים יינתן דגש על ההישגים במקצועות מבוא למכניקה הנדסית ותורת החוזק 1"
  - "בהתמחות הנדסת ניהול הבנייה… מבוא למכניקה הנדסית וכלכלה הנדסית"

**When:** not in the PDF. The first specialization table is "קורסי חובה בהתמחות לסמסטר 3 — מסלול מבנים" (p. 6), and Management's first courses are in semester 4. Admission rests on semester 1–2 courses. **Inference:** the choice is made after year 1 and applies from semester 3.

### Courses mandatory only in one specialization (pp. 6–11)

Each semester table also has a placeholder row "*קורסי חובה בהתמחות".

| Sem | מבנים | ניהול הבנייה |
|---|---|---|
| 3 | 421212 תורת החוזק 2 (4.0) | none (the placeholder reads "0-4") |
| 4 | 421219 מבני בטון 1 (4.0); 421316 סטטיקת מבנים 2 (3.0) | 421221 שיטות ביצוע (2.5); 421214 מבני בטון 12 (4.0) |
| 5 | 421314 מבני בטון 2 (4.0); 421315 דינמיקת מבנים (3.0) | 421222 (2.5); 421318 מיכון ותיעוש (2.5); 421319 אומדן עלויות (2.5) |
| 6 | 421326 הנדסת רעידות אדמה (2.5); 500115 מבוא לאלמנטים סופיים (2.5) | 421327 תכן מבנים ארעיים (2.0); 421328 (2.5); 421317 (2.5) |
| 7 | 421411 בטון דרוך (2.5); 421412 בניית המהנדס (3.5) | 421413 תכנון תפעולי בתחבורה (3.0) |
| **Total** | **29.0** | **24.0** |

- The totals match p. 3: "24.0–29.0 נ"ז לימודי התמחות".
- For semester 7 the PDF prints 3.0–5.5, but the Structures block adds up to 6.0. This is a source error, already noted in `civil.json`.

### Elective groups and their rules

p. 3 breakdown:
- "160 נ"ז הכוללות: 114.0 חובה / 24.0–29.0 התמחות / 9.0–14.0 נ"ז לימודי בחירה מחלקתיים / 6.0 קורסים כלליים / 1.0 מיומנות יסוד הנדסית / 1.0 ספורט"
- "לפחות 160 נ"ז (ולא יותר מ-165 נ"ז)"

**Structures** (pp. 12–14), heading "מסלול הנדסת מבנים- (עד צבירה של כ-9 נק"ז)":
- "קבוצה 1: חובה ללמוד לפחות 2 קורסים מהרשימה הבאה:" — 500110, 500111, 500112, 500113, 500114, 421418, 500116, 500117, 500118, 500119.
- "קבוצה 2: חובה ללמוד לפחות קורס אחד מהרשימה הבאה" — 421222, 421319, 421221, 421413, 421318, 500120, 421327, 421420. Most of these are Management's mandatory courses.

**Construction management** (p. 15), heading "מסלול להנדסת ניהול הבנייה- עד צבירה של כ-14 נק"ז":
- One list, with no groups: 500210\*, 500211, 500212, 500213, 500214, 500120, 500122, 421412, 421420, 421422, 500217, 500218, 421418, 51600\* (4 credits).
- p. 16: "*שימו לב כי קורסי "מבוא לכלכלה" "וניהול משאבי אנוש בבניה" - הם קורסי חובה לפי רשם המהנדסים וצריכים לקחת אותם כחובה ולא כבחירה."

**Not in the PDF:**
- a maximum per group, or a minimum number of credits per group
- whether "עד צבירה של כ-" is a cap or a target (it is also approximate: "כ-")
- whether the two starred courses count toward the ~14
- a minimum number of courses for Management
- whether a student may take electives from the other track's list

The review item's "a maximum of X credits per group" is therefore **not** printed for civil. The only per-group numbers are the minimum course counts: group 1 ≥ 2 and group 2 ≥ 1, for Structures only.

### Semesters that recommend electives / general courses

- No placeholder rows.
- p. 2: "בשנתיים האחרונות יינתנו גם קורסי הבחירה." The semester 7 and 8 totals (p. 11, p. 12) read "סה"כ (ללא קורסי בחירה)".
- General courses and sport, p. 3: "…לא שובצו בתוכנית המובאת כאן וניתן לשלבם בכל סמסטר".
- p. 3 also requires "שני קורסים בשפה האנגלית, לפחות אחד מהם יהיה קורס תוכן".

### Data status

| Item | Status |
|---|---|
| Track names | **in repo**: `civil.json` → `tracks` |
| Track-mandatory courses | **in repo**: `civil.json` course `track` field; the 29 / 24 totals check out |
| Elective lists | **parser**. `curricula.json` has 4 keys and is wrong: groups merged, 51600 missing, raw heading used as a key |
| Group minimums (2 / 1) and "~9" / "~14" | **by hand**: they are in headings |
| The p. 16 note (two starred courses count as mandatory) | **by hand** |
| When the choice is made | **not in the PDF** |
| Elective / general semesters | **by hand**, and prose only: "last two years", "any semester" |

---

## 2. Electrical & Electronics Engineering — `electric.pdf`, `data/curricula/electronic.json`

### Specializations and when they're chosen

p. 2: "במחלקה מוצעות שלוש התמחויות: • מחשבים (חומרה ותוכנה) • עיבוד אותות ותקשורת • התקנים ואלקטרו-אופטיקה"
- Also on p. 2: "ניתנת לסטודנטים גם אפשרות לבחור קורסים מתוך רצועת קורסים רב-תחומית."

**When: the PDF gives no semester and no deadline.** What it does establish:
- Semesters 1–6 are mandatory and common to everyone. p. 3: "111 נ"ז – קורסי חובה לפי התוכנית בסמסטרים 1–6".
- Specialization studies run alongside the design phase, which the p. 7 tables place in semesters 7–8. p. 2: "ההתנסות בתכן הנדסי מתחילה עם סיום לימוד קורסי החובה ומתבצעת במקביל ללימודי ההתמחות".
- **Inference:** the specialization matters from year 4 (semester 7). The PDF does not say whether a specialization course may be taken earlier. This is the point the review asks about, and the curriculum does not settle it. **Ask the department before designing the "required from semester X" rule.**

**The semester 7–8 design route decides how many specializations are needed.** p. 7, footnote 4: "ניתן לבחור רק באחת משלוש האפשרויות: תכן הנדסי בתעשייה/תכן הנדסי מחקרי/פרויקט גמר בתכן הנדסי… סוג התכן ההנדסי הנבחר ישפיע על מספר נ"ז בקורסי התמחות ובחירה".

| Route | Design courses | Main specialization | Secondary specialization | Other electives |
|---|---|---|---|---|
| Industry design (10 credits, the default, p. 3) | 31101 (3) → 31104 (7) | ≥ 20 credits | none | 12.0 |
| Research design (8 credits) | 31101 (3) → 31103 (5) | ≥ 20 credits | ≥ 10 credits | 4.0 |
| Final project (6 credits) | 31100 (3) → 31102 (3) | ≥ 20 credits | ≥ 10 credits | 6.0 |

Sources: pp. 7–9, §2.1–2.3. The "other electives" figures each carry "(כולל עד 3 נ"ז מהרצועה הרב-תחומית)".

### Courses mandatory only in one specialization

**None.** Each specialization has three pools, all of them electives:
- a core pool with a minimum course count
- "קורסים משותפים למספר התמחויות"
- "קורסים להתמחות זו בלבד"

The only route-specific mandatory courses are the design courses above.

| Specialization | Core pool (≥ N) | Only in this specialization |
|---|---|---|
| מחשבים (pp. 10–11) | "יש לבחור לפחות 6 קורסים (3 תוכנה 3 חומרה)". Hardware: 31215, 31226, 31500, 31551. Software: 31245, 31261, 31632, 31695 | 31270, 31570 |
| עיבוד אותות ותקשורת (pp. 11–12) | "לפחות 4 קורסים": 31245, 31251, 31361, 31471, 31476, 31561, 31651, 31724 | 31485, 31740 |
| התקנים ואלקטרואופטיקה (pp. 12–13) | "לפחות 4 קורסים": 31088, 31245, 31715, 31820, 31980, 31901, 31903, 31904, 31905 | 31802, 31982, 31902, 31985, 31906, 31907 |

**Contradiction in the PDF:** 31985 is listed as "only this specialization" under התקנים (p. 13), and also appears in the shared section of עיבוד אותות (p. 12).

### Elective rules

- **Main specialization.** p. 8, §3.1: "יש להשלים קורסים בהיקף 20 נ"ז לפחות, מתוכם לפחות 4 קורסי ליבה בהתמחות. בהתמחות מחשבים… לפחות 6 קורסים: 3 קורסים מתחום החומרה ו-3 קורסים מתחום התוכנה."
- **Secondary specialization.** p. 8, §3.2: "יש להשלים לפחות 10 נ"ז, מתוכם יש לבחור לפחות 3 קורסי ליבה בהתמחות: בהתמחות מחשבים לפחות קורס אחד מתחום החומרה וקורס אחד מתחום התוכנה."
- **Other electives.** p. 8, §3.3: "ניתן לבחור קורסים מכל ההתמחויות… אפשר ללמוד עד 3 נ"ז מרצועת הקורסים הרב-תחומית."
  - p. 15, the strip itself: "מרצועה זו ניתן ללמוד קורסים בהיקף של עד 3 נ"ז". Its courses: 51301, 51605, 51160, 251100, 251504, 251506, 251507, 251510, 251512, 251513, 251514, 251520, 251965.
  - Further additional courses (pp. 13–14): 13069, 51914 (footnote 9: "יש לקבל אישור לרישום מיועץ ומרמ"ח"), 22784, 21461, 22486, 22864, and "פרויקט מיוחד", which has no course number and "1-2" credits.
- **Totals.** p. 3 states "32 נ"ז" for specialization plus electives. That figure fits only the default industry route; the other routes need 34 and 36 (p. 8 table).
- **Other rules:**
  - §4: courses from other departments "באישור היועץ וראש המחלקה".
  - §5: "לא בכל שנה / סמסטר יינתנו כל הקורסים".
  - p. 3: at least 160 credits, "ולא יותר מ-165".

**Not in the PDF:**
- a maximum per specialization
- a minimum course count for other electives
- whether one course can count toward both the main and the secondary specialization

### Semesters that recommend electives / general courses

- No placeholder rows in semesters 1–8.
- General courses and sport:
  - p. 3: "6 נ"ז – שלושה קורסים כלליים (אינם מוצגים בתוכנית…)"
  - note 5: "ניתן לשלב קורסים אלה בכל סמסטר"
- Specialization and elective courses are placed only by the "במקביל" sentence. Semesters 7–8 print only 3–7 credits each. **Inference:** the electives belong in year 4.

### Data status

| Item | Status |
|---|---|
| Design routes (31100–31104) | **in repo**: `electronic.json` → `tracks` plus a `track` on each design course |
| The three specialization names | missing. **parser**, or by hand: `electronic.json` warning #12 says specialization study is not included |
| Pools (core, shared, only this) | **parser**, and feasible: the section rows are stable. Watch for the "– המשך" continuation headings and the 31985 contradiction |
| Rules (20/4, 6 = 3+3, 10/3, 12/4/6, ≤ 3 from the strip) | **by hand**: prose plus a merged-cell table |
| When the specialization starts | **not in the PDF** |
| General courses: any semester | **in repo** as warning text only |

---

## 3. Mechanical Engineering — `mecho.pdf`, `data/curricula/mechines.json`

### Specializations and when they're chosen

p. 2: "…באחד מתוך ארבעה תחומי עניין: תכן וייצור, מכטרוניקה, ביומכניקה ותעשייה מתקדמת בעידן המידע."
- Condition, p. 3: "רישום להתמחות מותנה במעבר קורסי היסוד המפורטים ברשימה מטה ובמצב אקדמי תקין." A list of 18 foundation courses follows.
- p. 6: "תנאי קדם ללימוד קורסי התמחות: השלמת קורסי היסוד."
- **When:** not stated as a semester. The track tables start at semester 5 (p. 6). **Inference:** the choice is made after semester 4.

### Courses mandatory only in one specialization

p. 6: "בכל התמחות ארבעה קורסי חובה אשר אינם ניתנים לשינוי/החלפה בקורס אחר."

| Sem | תכן וייצור | מכטרוניקה | ביומכניקה | תעשייה מתקדמת |
|---|---|---|---|---|
| 5 | 22720 (3.0) | 22861 (3.5) | 22467 (3.0) | 22993 (3.5) |
| 6 | 22853 (3.5); 22267 (2.5) | 22862 (2.0); 22864 (3.0) | 22472 (3.5); 22855 (2.5) | 22998 (3.0); 22997 (2.5) |
| 7 | 22268 (2.5) | 22863 (3.0) | 22471 (2.5) | 22994 (3.0) |
| **Total** | 11.5 | 11.5 | 11.5 | 12.0 |

### Elective rules

- p. 3: "28.5 נ"ז לימודי התמחות (חובה+בחירה+העשרה)".
- p. 6: "…רשימות של קורסי בחירה בהתמחות וקורסים מתקדמים בהתמחות מהן יבחר הסטודנט קורסים עד לצבירה של 28.5 נ"ז בהתמחות שבחר."
- **Per-specialization elective lists**, pp. 9–12, each headed "קורסי בחירה בהתמחות לסמסטרים 5–8 (עד צבירה של 20 נ"ז בהתמחות)":
  - Design & manufacturing: 19 courses
  - Mechatronics: 23 courses
  - Biomechanics: 18 courses
  - Industry 4.0: 22 courses
- **Shared enrichment list**, pp. 13–14, headed "קורסי העשרה לכלל ההתמחויות לסמסטרים 5–8 (עד צבירה של 28.5 נ"ז בהתמחות)": 42 courses.
  - Directly under it: "מקורסי היזמות המופיעים מטה ניתן ללמוד עד מכסה של 4 נ"ז."
  - The PDF does not mark which courses are "יזמות". **Inference:** the 251xxx rows, going by their names.

**Not in the PDF:**
- a minimum number of elective courses
- a split between the specialization list and the enrichment list
- whether "עד צבירה של 20" is a cap or a target
- p. 6 mentions "קורסים מתקדמים בהתמחות", but no list with that heading exists

### Semesters that recommend electives / general courses

- No placeholder rows. The lists are headed "לסמסטרים 5–8".
- The semester 7 and 8 totals (p. 8, p. 9) read "סה"כ ללא קורסי בחירה".
- General courses and sport, p. 3: "…לא שובצו בתוכנית המוצעת כאן. ניתן לשלבם לאורך כל תקופת הלימודים במחלקה".

### Data status

| Item | Status |
|---|---|
| Track names and the 16 mandatory courses | **in repo**: `mechines.json`, correct |
| Foundation-course condition | **by hand** |
| Elective lists | **parser**. `curricula.json` mixes mandatory courses and electives in each key. Missing: 22720 and 22777 (design), 22748 (mechatronics), 21461 (biomechanics). The 42-course enrichment list sits only under "…– תעשייה 4.0" |
| 28.5 / 20 / entrepreneurship ≤ 4 credits | **by hand**. Which courses count as entrepreneurship needs a decision |
| Elective / general semesters | **by hand**: "5–8", "any time" |

---

## 4. Industrial Engineering & Management — `industry.pdf`, `data/curricula/industry.json`

### Specializations and when they're chosen

p. 2: "…וכוללת שתי התמחויות (ההתמחויות אינן נרשמות על גבי תעודת התואר. פתיחתן מותנית במספר הנרשמים אליהן): • מדעי הנתונים • תכן ותפעול של מערכות ייצור ושירות"
- **When**, p. 3: "יש לבחור את ההתמחות עד סוף שנה א' לכל המאוחר (מפגש הסבר עבור ההתמחויות יתקיים באמצע הסמסטר השני)."
- The PDF prints the whole plan twice: Data Science on pp. 3–9, Design & Operations on pp. 10–17. Semesters 1–2 are identical, and the two diverge from semester 3.

### Courses mandatory only in one specialization

| Sem | מדעי הנתונים only | תכן ותפעול only |
|---|---|---|
| 3 | 51031 (3.0) | 21214 (2.0), 51302 (2.5) |
| 4 | 51913 (3.0), 51302 (2.5) | 51310 (4.5), 51432 (2.5) |
| 5 | 51027 (2.5), 51525 (2.5) | 51013 (2.5), 51618 (2.5) |
| 6 | 51030 (2.5), 51535 (2.5), 51955 (2.5) | 51138 (2.0), 51525 (2.5), 51608 (2.5) |
| 7 | 51023 (4.0) | 31323 (2.0), plus practical experience part א' |
| 8 | 51024 (4) | practical experience part ב' |

- 51302 and 51525 are mandatory in both specializations, in different semesters.
- **Design & Operations practical experience** (p. 13): "יש לבחור באחת מהחלופות", and then "יש להמשיך לבחור באותה חלופה".
  - Industry internship: 51014 (5) → 51020 (5).
  - Final project: 51230 (4) → 51231 (4).
- The Data Science printing lists only 51023 / 51024, although p. 3 says every specialization includes "התמחות בתעשייה או פרויקט גמר".

### Elective rules

**Data Science** (p. 7):
- "יש לבחור לפחות 4 קורסים מאשכול מערכות מידע ומדע הנתונים"
- "יש לבחור לפחות 2 קורסים מאשכול תכן ותפעול של מערכות ייצור ושירות"
- "יש לבחור לפחות קורס אחד מאשכול ניהול"
- "יש להשלים ל-160 נ"ז לפחות"
- No total course count is printed.

**Design & Operations, industry-internship route** (p. 13): "7 קורסי בחירה לפחות"
- at least three from תכן ותפעול
- at least one from ניהול
- at least one from מערכות מידע
- "לפחות שניים מקורסי הבחירה חייבים להיות מהקבוצה הבאה": 51170 (with the condition "באחוזון ציונים של 80% ומעלה, באישור רמ"ח בלבד"), 51025, 51030, 51106, 51113, 51120, and "51535 … או 51537".

**Design & Operations, final-project route** (pp. 13–14): "8 קורסי בחירה לפחות"
- at least four from תכן ותפעול, one from ניהול and one from מערכות מידע
- at least two from the same special list, with 51156 added. 51156 is in no cluster and no credits are printed for it.

**Both specializations:**
- Exactly one science & technology course. p. 3: "קורס אחד מאשכול מדע וטכנולוגיה" (22993, 41095, 41942).
- 251xxx courses (pp. 9, 16): "ניתן גם לקחת קורסים מהמרכז לחינוך הנדסי וליזמות בסך של עד 3 נ"ז". Each 251xxx course is assigned to a cluster in an "אשכול" column.
  - Mutually exclusive pairs: 251509/251513, 251514/251965, 251507/251504, and 251966/51515 (p. 9 only).
- "לא ניתן להחשיב קורס ששייך לשני אשכולות ביותר מאשכול אחד."

**Not in the PDF:**
- a maximum per cluster (other than the 3-credit cap on 251xxx)
- minimum elective credits (only "השלמה ל-160")
- a total course count for Data Science

The cluster contents also differ between the two printings. The D&O printing adds 51027, 51030 and 51535 to מערכות מידע, and 51030 to תכן ותפעול; all four are mandatory for Data Science.

### Semesters that recommend electives / general courses

- **Data Science:** semester 7 has the row "קורסי בחירה (לפי המפורט בהמשך)" (p. 6). Semester 8 has no row, but its total reads "(ללא קורסי בחירה)".
- **Design & Operations:** semester 7 has "קורסי בחירה (לפי המפורט בהמשך)" (p. 12), and semester 8 has "קורסי בחירה" (p. 13).
- **General courses and sport** (p. 3): "(ניתן לשלב אותם/אותו לאורך כל תקופת הלימודים)". No semester is given for the science & technology course.

### Data status

| Item | Status |
|---|---|
| Specializations, divergence, per-specialization mandatory courses | **in repo**: `industry.json` → `tracks` plus a per-course `track`, correct |
| "Choose by end of year 1" | **by hand** |
| D&O practical-experience alternatives | **by hand**, as route alternatives like Electrical's design routes |
| Elective placeholder rows (DS 7; D&O 7, 8) | **parser**: the literal "קורסי בחירה (לפי המפורט בהמשך)" is detectable. Or by hand |
| Cluster rules (4/2/1; 7 or 8 courses with 3/1/1 or 4/1/1, plus 2 from the list; 251xxx ≤ 3; exclusive pairs; one cluster per course; 1 science & technology course) | **by hand** |
| Clusters per specialization | **parser**. They are merged today, and 51916, 251966 and the 251xxx rows are wrong or missing |

---

## 5. Software Engineering — `sw.pdf`, `data/curriculum.json`

- **Specializations:** none. The p. 2 list ("מדעים, אלגוריתמים, עיבוד אותות ורשתות תקשורת, הנדסת תוכנה, סמינרים ומעבדות") names the six elective clusters.
- **Rule**, p. 9 [137]: "כל סטודנט חייב לקחת קורס אחד מכל אשכול ובמידה וחסרות נקודות זכות להשלמת 160.0 נ"ז יש לקחת קורס נוסף מאחד מהאשכולות." Also "הנוכחות בקורסי הבחירה הינה חובה".
- **Other constraints:**
  - Seminars cluster (p. 11): "(כל הקורסים באשכול זה יינתנו בשפה האנגלית)", and it cannot be replaced by social activity or reserve duty.
  - Entrepreneurship (pp. 10–12): "רק קורס יזמות אחד בלבד יוכר לזכאות לתואר".
  - 62023 is closed to students who took 62002.
- **Not in the PDF:** total elective credits (only "להשלמת 160"), and any maximum or minimum credits per cluster.
- **Placeholder rows:**
  - semester 1: "קורס כללי 1" (2.0) and "ספורט" (1.0)
  - semester 4: "קורס כללי 2"
  - semester 6: "קורס כללי 3"
  - semesters 7 and 8: "קורסי בחירה", with totals printed "(ללא קורסי בחירה)"
- **Data status:**
  - Placeholders: **in repo**, correct (`code: null` rows plus `plus`).
  - Clusters: **in repo, twice, and the two copies differ.**
    - `curricula.json` has 17 codes in הנדסת תוכנה, including 62003 and 62004. This is the copy the API serves.
    - `curriculum.json` has 15 codes there, plus credits and `entrepreneurship: true` flags.
  - English seminars, one entrepreneurship course and `degree_notes`: in the repo but **not read** by any code.

## 6. Information Systems Engineering — `system.pdf`, `data/curricula/infosystems.json`

- **Specializations:** none. There are three clusters: מדעים (p. 9 [161]), הנדסת תוכנה (p. 10), and תכן, תפעול וניהול (p. 11 [163]).
- **Rule**, p. 9 [161]: "כל סטודנט חייב לקחת קורס אחד מכל אשכול. אחד מקורסי הבחירה חייב להיות סמינר בשפה האנגלית. במידה וחסרות נקודות זכות להשלמת 160.0 נקודות זכות, יש לקחת קורסים נוספים מכל אחד מהאשכולות."
- **Which courses are English seminars:** **not in the PDF.** Only 61966 is marked "באנגלית". The seminars 61967, 61968, 62005, 62015 and 65012 carry no language marker.
- **Other constraints:** one entrepreneurship course only (251100, 251965); the 62023/62002 exclusion; the English seminar cannot be swapped (p. 3).
- **Placeholder rows:**
  - semester 1: "ספורט"
  - semester 5: "קורס כללי 1"
  - semester 6: "קורס כללי 2"
  - semester 7: "קורס כללי 3" and "קורסי בחירה"
  - semester 8: "קורסי בחירה"
- **Data status:**
  - General and sport rows: **in repo** (`code: null`).
  - Elective rows: only in the semester `note` text. Adding a `plus` like Software's is **by hand**.
  - Clusters: **in repo** (`curricula.json`).
  - The English-seminar rule: **by hand**. Which courses qualify needs a decision.

## 7. Applied Mathematics — `SHANTON MATH NOV 2025 .pdf`, `data/curricula/math-winter.json`, `math-spring.json`

- **Specializations: none.**
  - "התמחות" never appears in the PDF.
  - The degree heading is "תוכנית הלימודים במתמטיקה שימושית" (p. 2).
  - AI and algorithms are two of four elective-domain headings under "קורסי בחירה": "תחום AI" (p. 7), "תחום האלגוריתמים" (p. 7), "תחום בתורת המערכות, הבקרה ועיבוד אותות" (p. 8), "תחום אחר או מתמטיקה" (pp. 8–9).
  - This is why section 1 was fixed as a label, not as a second program.
- **Rules**, p. 2: "לצורך זכאות לתואר על הסטודנט לצבור 120 נ"ז הכוללות: 96.0 נ"ז קורסי חובה / 4.0 נ"ז קורסים כלליים (שני קורסים) / 1.0 נ"ז ספורט (קורס אחד) / 1.0 נ"ז במיומנויות יסוד הנדסיות 251961 (שיילקח בשנה הראשונה) / כדי להשלים ל-120 נ"ז בקורסי בחירה, חובה על הסטודנט לקחת 3.0 נ"ז בקורסי בחירה מתמטיים"
  - Exclusion, p. 9: "מבין שני הקורסים (201198 / 61957) ניתן לקחת קורס אחד בלבד".
- **Not in the PDF:**
  - total elective credits (120 − 96 − 4 − 1 − 1 = 18 is arithmetic, not a printed number)
  - which courses count as "מתמטיים" (mapping them to "תחום אחר או מתמטיקה" would be an inference)
  - **any per-domain minimum or maximum.** The "one course from each cluster" rule the app shows today is not in this PDF.
- **Placeholder rows:**
  - Winter intake: "קורסי בחירה" in semesters 4, 5 (p. 4) and 6 (p. 5).
  - Spring intake: "קורסי בחירה" in semesters 4, 5 (p. 6) and 6 (p. 7).
  - General courses, p. 2: "קורסי לימודים כללים וספורט לא שובצו בתוכנית המובאת כאן. ניתן לשלבם לאורך כל תקופת הלימודים."
  - Spring intake only, p. 5: "* מומלץ ללמוד בסמ' 1+2+3 קורסים כלליים, ספורט ומיומנויות."
- **Data status:**
  - The four domains: **in repo**, typed by hand into `elective_clusters`.
  - The elective placeholder rows were dropped on purpose (a file warning says so). The semesters are known: **by hand**.
  - The 3.0-credit rule, the exclusion and the spring recommendation: **by hand**.

## 8. Biotechnology — `biotech.pdf`, `data/curricula/biotech.json`

- **What the PDF is:** a one-page table of mandatory courses, "תוכנית לימודים של קורסי חובה תשפ"ז 2025-26". Page 2 is a blank duplicate text layer.
- It has **no** specializations, elective lists, elective or general-course rows, or rules.
- The repo already says so in a `biotech.json` warning: "המסמך הוא תוכנית קורסי החובה בלבד ואינו מפרט קורסי בחירה."
- **Nothing for sections 3–4 can be extracted.** It needs another source, such as the department's shnaton chapter.
- **Values in the repo that the PDF does not print:**
  - `degree_credits_required: 146.5` comes from an unlabelled number.
  - The semester 8 note treats the 23 − 16 gap as electives.
  - 41750's name "סטאז'" is not in the PDF.

---

## 9. The "other program — not relevant" option (section 5)

**What it does today.** It appears as "תוכנית אחרת / לא ברשימה", id `other`. It is appended by `_program_choices()` in `src/web/api.py`.
- The program box is required. Steps 2–5 stay locked until a program, year and semester are chosen (`identityChosen()` in `app.js`).
- Choosing `other` satisfies that requirement without naming a program. The server then:
  - resolves no curriculum (`_curriculum()` returns `{}`);
  - returns no recommended list and no electives (`fetchElectives()` short-circuits on `"other"`).
- The courses step shows the no-curriculum line "תוכנית הלימודים של המחלקה לא טעונה — אפשר לבחור כל קורס מהקטלוג." and works only from catalog search and browse.
- Credits, prerequisites and the solver work as for any program.
- No course is auto-selected.

**When a student needs it.** The list is the eight B.Sc. programs on the college website, so the option is the only way in for a student who isn't in one of them:
- a double-degree student (math + engineering, p. 2 of the math chapter)
- a practical-engineer completion track ("הנדסאים מדופלמים", in the industrial and IS chapters)
- a teaching-certificate or M.Sc. student
- a visiting or non-degree student

A student in a listed program could pick it only to avoid the auto-selected recommended list. That is a weak reason, since the list can be cleared.

**Recommendation: keep it.** Without it, those students are locked out of the whole app. It deserves a clearer label and a one-line explanation, for example "לא מופיע ברשימה — עבודה מהקטלוג בלבד", decided when the UI is designed. Removing it is not proposed.

**Data status:** nothing to extract; this is app behaviour.

---

## 10. Root causes and fixes, per review item

| Item | Root cause | Layer | Fix |
|---|---|---|---|
| 1. Math label | Website program list names it "…עם התמחות ב-AI ובאלגוריתמיקה"; the curriculum prints one "מתמטיקה שימושית" | scraper / data | **Done:** `program_label` in both math files, served as `label`; id unchanged |
| 2. `חדו"א2` | Civil PDF extraction glued the numbers | data (PDF extraction) | **Done:** `normalize_course_name` when curricula load and when the yedion is parsed; `civil.json` fixed at rest |
| 2. Cut-off biotech names, GMP, Physics 3 | `biotech.json` copied yedion names (cut at 40 characters) instead of the PDF's | data | **Done:** PDF names; the curriculum name wins in `/api/courses` and `/api/solve`; cut-off names restored from any curriculum that prints them in full |
| 3. Elective / general notes | Placeholder rows are recorded inconsistently, and dropped for math and industrial | data / parser | Record a per-semester `plus` or placeholder for every program (the table above has the semesters), then design the note |
| 4. Specializations | Tracks exist for civil, mechanical and industrial. Electrical has none. Elective lists are mis-parsed; rules aren't stored | parser and data | Fix `shnaton.py` headings; per-specialization clusters; a hand-entered rules block with citations; picker per `DESIGN.md` |
| 5. "Other" option | Works as designed | UI copy | Keep; clearer label |

### Yedion names still cut off, with no full name in any source

These 20 are shown as the yedion prints them (it cuts names at 40 characters). No curriculum in the repo has a longer name for them, so the full names have to be supplied by hand. **Nothing here is guessed.**

"Program" is the curriculum that lists the course. "—" means no curriculum in the repo lists it. "Why listed" says what flagged it. Those marked *may be complete* only reach the length limit or end in a normal "א'"/"ב'", and may need no change.

| Code | Program | Current name (yedion) | Length | Why listed |
|---|---|---|---|---|
| 11375 | — | פרשיות סוערות במשפט ישראלי: השלכות תרבות | 40 | at the limit |
| 11578 | — | חינוך וטכנולוגיה בעידן המהפכה התעשייתית | 39 | at the limit; *may be complete* |
| 11871 | — | שילוב טכנולוגיות מתקדמות בהוראה ובהדרכה | 39 | at the limit; *may be complete* |
| 31032 | — | בחינת סווג-יסודות הפיזיקה-חשמל ואלקטרו' | 39 | ends in an abbreviation |
| 31033 | — | יסודות הפיזיקה - הנדסת חשמל ואלקטרוניקה | 39 | at the limit; *may be complete* |
| 41526 | הנדסת ביוטכנולוגיה | קינטיקה ותכנון ריאקטורים כימיים וביולוגי | 40 | at the limit. Biotech students see the PDF's shorter "קינטיקה ותכנון ריאקטורים" |
| 43101 | — | תקינה ופיתוח מוצרים ביוטכנולוגיים ורפוא | 39 | cut mid-word |
| 51023 | הנדסת תעשייה וניהול | פרוייקט גמר בהתמחות מדעי הנתונים שלב א' | 39 | ends in "א'"; *may be complete* |
| 51024 | הנדסת תעשייה וניהול | פרוייקט גמר בהתמחות מדעי הנתונים שלב ב' | 39 | ends in "ב'"; *may be complete* |
| 51230 | — | פרויקט גמר בהתמחות תכן ותפעול שלב א' | 36 | ends in "א'"; *may be complete* |
| 51231 | — | פרויקט גמר בהתמחות תכן ותפעול שלב ב' | 36 | ends in "ב'"; *may be complete* |
| 51742 | הנדסת חשמל ואלקטרוניקה | הסתברות ויסודות הסטטיסטיקה להנדסת אלקטרו | 40 | cut mid-word. Electrical students see the curriculum's "הסתברות ויסודות הסטטיסטיקה" |
| 51963 | — | פיתוח מערכות ארגוניות בעזרת Vibe Coding | 39 | at the limit; *may be complete* |
| 81280 | — | מבוא להוראת המקצועות העיוניים ההתנסותיים | 40 | at the limit |
| 81403 | — | התנסות מעשית בהוראת מתמטיקה והנדסה משולב | 40 | at the limit |
| 81404 | — | התנ' מעשית בהוראת מתמטיקה והנדסה משולב 2 | 40 | abbreviation "התנ'" |
| 81561 | — | נושאים מתמטיים נבחרים למורים למתמט' | 35 | ends in an abbreviation |
| 81578 | — | חינוך וטכנולוגיה בעידן המהפכה התעשייתית | 39 | at the limit; *may be complete* |
| 81671 | — | שילוב טכנולוגיות מתקדמות בהוראה ובהדרכה | 39 | at the limit; *may be complete* |
| 85405 | — | פרויקט אינדוודואלי בהוראת הנדסה ומתמטיקה | 40 | at the limit |

### Civil 421223: a printed misspelling, pending confirmation

`civil.pdf` prints "מבוא לאלגרומיתקה ותכנות". The same chapter elsewhere, and the yedion, write "מבוא לאלגוריתמיקה ותכנות". The file keeps the printed spelling until the correction is confirmed.
