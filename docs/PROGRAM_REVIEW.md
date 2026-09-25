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
  - *Done 2026-09-25:* `biotech.json` had copied the yedion's names (cut at 40 characters) instead of the PDF's; 15 names now follow `biotech.pdf`. The student's own curriculum name now also wins in the lecturers step and timetable, and a cut-off yedion name is restored wherever any curriculum prints it in full (41711, 62015). The 20 yedion names with no full version in any source are tabled in `docs/PROGRAM_FINDINGS.md` §10, waiting for full names; civil's printed misspelling of 421223 is kept until confirmed.
- [x] **GMP course name.** A Biotechnology course is displayed as `דרישות רגולטוריות ו-GMP בביוטכ`. It should be displayed simply as `GMP`. Check the curriculum for the correct display name and use it.
  - *Done 2026-09-25:* `biotech.pdf` prints it as `GMP`, and it is now shown as `GMP` everywhere for biotech students.
- [x] **Physics 3 in Biotechnology.** Year 3, Semester B shows `פיזיקה 3ב` instead of `פיזיקה 3`. Check the curriculum and the catalog: if it's the same course, display it as `פיזיקה 3`; if they're genuinely different courses, make sure the one the curriculum requires for this program is the one shown.
  - *Done 2026-09-25:* same course (11027 in both sources), shown as `פיזיקה 3`; by decision, biotech Physics 1 and 2 keep the yedion's names `פיזיקה 1ב` / `פיזיקה 2ב` (not the PDF's `פיזיקה 1 ב'`).

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

### 4.3 Industrial Engineering & Management, and Mechanical Engineering
- [ ] Both are organized by specializations as well. Apply the same approach: determine from the curriculum when the specialization is chosen, require the choice at the right point, and adjust mandatory courses, elective filtering and notes accordingly.

### 4.4 General
- [ ] Check every other program for specializations that aren't handled yet, and report what you find before implementing.
- [ ] Keep the specialization picker consistent across programs (same component, same place in the flow, per `docs/DESIGN.md`).

## 5. The "other program — not relevant" option

- [ ] There's an option for "another program — not relevant". It's unclear what purpose it serves. Explain what it currently does and in which cases a student would need it. If it has no real use, propose removing it — ask before removing.
