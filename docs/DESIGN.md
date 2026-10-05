# SlotWise UI redesign

This document is the source of truth for the SlotWise redesign. Implement it in the phases listed at the end, one phase per commit. Where this document and the current code disagree, this document wins; where it is silent, keep the current behaviour.

## Principles

1. **All content stays; presentation changes.** Nothing a student can learn today disappears. Every piece of information appears once, in the place where it is used.
2. **Color belongs to the courses and the logo.** The interface uses a single ink color (the logo navy in light mode) on neutral surfaces. Saturated color is reserved for the course colors, each used identically in the steps and in the timetable, and for the logo (see Logo and favicon).
3. **Motion explains, it does not decorate.** Motion is used only in response to the user's action: a step or course opening and closing, a rank being assigned, timetable blocks moving between alternatives. No scroll-triggered entrances, no glow, no gradients, no ambient animation.
4. **The active step is the only loud thing.** Completed steps collapse to one summary line, upcoming steps are muted.
5. **Nothing to offer is one line.** When a feature has nothing to offer, it says so in one line instead of explaining what it checked. For example, when no single-course drop reaches the study-days target, the "מה יאפשר N ימים" panel is only "אי אפשר להגיע ל-N ימים, גם בוויתור על קורס אחד."
6. **A note is one line, for the student** (decided 2026-09-27). Every note in the interface (semester notes, cluster notes, course-card notes) is at most one line, written for the student, and carries no internal data: no field names (`track`, `note`, `code`), no raw values, no extraction or reconciliation detail, no source file names or page numbers. That material stays in the data files and, where a person needs it, in `docs/PROGRAM_REVIEW.md`.

## Tokens

### Color

Light (default):

| Token | Value | Use |
|---|---|---|
| `--bg` | `#f4f4f1` | page background |
| `--sf` | `#ffffff` | surfaces (panels, course cards) |
| `--ln` | `#ebebe6` | grid lines, row dividers |
| `--bd` | `#e3e3dd` | borders |
| `--ink` | `#0d1d3d` | primary text, active step border, primary button, selected state (the logo navy) |
| `--sec` | `#6e6e73` | secondary text |
| `--mut` | `#a3a3a8` | muted text, upcoming steps, hour labels |

Dark:

| Token | Value |
|---|---|
| `--bg` | `#0e0f11` |
| `--sf` | `#17181b` |
| `--ln` | `#222327` |
| `--bd` | `#2a2b30` |
| `--ink` | `#f2f2f0` |
| `--sec` | `#9a9aa1` |
| `--mut` | `#5d5e64` |

In dark mode, elements that use `--ink` as a background use `--sf` as their text color (the pair inverts).

**Course palette** (decided 2026-09-30; **supersedes** the earlier 8-colour palette and the "tint = `color-mix` 13%" rule). Course colors are the site's existing ten: `--course-0` … `--course-9`, each with `-bd` and `-fg` (light), and `--dark-course-*` (dark), in `style.css`. They are assigned by `buildColorMap()` in `app.js`, unchanged. Wherever this document says a course's "tint" or "course color", it means that course's `--course-N` fill and `--course-N-bd` border. No hex values are listed here: `style.css` is the single source for them (see CLAUDE.md).

The existing light/dark/system toggle stays and drives these tokens.

### Type

- Family: **Heebo** (Google Fonts), weights 400, 500, 600, 700, 800. Fallback: `system-ui, sans-serif`.
- Scale: step title 20px/800; results heading 18px/800; wordmark 26px (23px on narrow screens) in DM Serif Display, see Logo and favicon; body 13–14px/400–500; secondary 12–13px; tiny labels 11px.
- Sentence case everywhere. No all-caps labels.

### Shape and spacing

- Radius: panels 12px, course cards 10px, buttons 8–10px, timetable blocks 7px, pills 999px.
- No shadows except the segmented-control indicator (if used). Separation comes from borders and surface color.
- Base spacing unit 4px; panel padding 12–16px; gap between steps 8px.

## Logo and favicon

The SlotWise logo is a mark (a calendar with gold binder rings, a clock, a teal check and a small sparkle) followed by the wordmark "SlotWise". It is the only place outside the courses where the interface uses saturated color.

Files live in `src/web/static/brand/`:

| File | Use |
|---|---|
| `mark-light.svg` | Header mark, light mode |
| `mark-dark.svg` | Header mark, dark mode |
| `favicon.svg` | Simplified mark (calendar, gold rings, teal check) for browser tabs; switches itself to its dark variant with `prefers-color-scheme: dark` |
| `favicon.ico` | Fallback favicon, 16/32/48px, light variant |
| `apple-touch-icon.png` | 180px home-screen icon on a solid cream background |

**Favicon set.** Every page's `<head>` links all three: `favicon.ico` (`sizes="any"`), `favicon.svg` (`type="image/svg+xml"`) and `apple-touch-icon.png` (`rel="apple-touch-icon"`). The tab icon follows the OS setting, not the site's theme toggle; a favicon cannot see the page's theme.

**Header logo.** The mark (34px, 30px on narrow screens) followed by the wordmark "SlotWise" in **DM Serif Display**, 26px (23px on narrow screens), weight 400, about 1.3x the previous logo text. "Slot" and "Wise" are two colors:

| | "Slot" | "Wise" | Mark |
|---|---|---|---|
| Light | `#0d1d3d` | `#0e5a5e` | `mark-light.svg` |
| Dark | `#ecebe6` | `#3fb8ad` | `mark-dark.svg` |

The ring around the clock (`.brand-halo`) is filled with the header's background token (`--panel`) in both modes, so it separates the clock from the calendar without showing as a halo against the header; the fixed fill in the SVG files is only for using them standalone. Both mark variants are inlined in the header and CSS shows the one for the active theme, so the mark and the wordmark follow the site's theme toggle (light/dark/system), not only the OS setting. The inlined markup must stay identical to the two files. The wordmark colors are the tokens `--brand-slot` (light: `var(--ink)`) and `--brand-wise`, with dark values in `--dark-brand-*`.

Both fonts are self-hosted in `src/web/static/fonts/` with their OFL licences. The app makes no external requests, so nothing is loaded from Google Fonts.

**Brand colors.** Navy `#0d1d3d` (also the light-mode `--ink`), teal `#0e5a5e` (dark mode `#3fb8ad`), gold `#c9a45c` (dark mode `#d4b06a`), cream `#fbf8f1`.

## Layout

The layout depends on screen width. Both layouts use the same components.

**Wide screens (≥1200px): side by side.** The steps column sits at the inline start (right, RTL), about 400px wide. The timetable column takes the rest of the width. Because the schedule already rebuilds live, every change in the steps is visible immediately next to it.

The timetable column (decided 2026-10-03; supersedes "sticky below the header, at most one viewport tall, scrolling internally if needed"):

- **Sticky, exactly one viewport tall.** On wide screens the page header is not sticky: it scrolls away with the page, and the timetable column sticks to the top of the viewport. Top to bottom it holds: the header row (item 2 under Results page), the alternative previews (item 3), the stats pills and their lines (item 4), the timetable, and the legend (item 7). The header row, previews, stats and legend keep their own height; the timetable gets the rest.
- **The whole week fits the user's screen.** The timetable adapts to the screen the student actually has, at any size, and is re-fitted whenever the window size, the selected alternative or the schedule changes. When the week does not fit with every block showing all three lines, these steps are applied in this order, each only if the previous one was not enough:
  1. **Always (wide only):** Friday has no column when it has no lessons (today it is a narrow column reading "אין שיעורים"), and the day header row is one line. ראשון–חמישי always keep their columns; a free day stays visible as an empty column.
  2. **Previews become a thin strip:** each card is its name and its mini week on one row. The "N ימים, עד HH:MM" line is dropped from the cards (the stats pills show it for the selected alternative), and the differentiator label of the **selected** alternative is shown once, as one line next to "5 מערכות מובילות".
  3. **Short blocks drop whole lines:** the hour height becomes what fits, and a block too short for three lines drops line 3 (lecturer · room) first, then line 2 (lesson type · time). The course name always stays, in full. A line is dropped whole or kept whole; nothing is ever clipped mid-line. A shortened block still carries its full content in its accessible name, and clicking it shows everything in the lesson details.
  4. **Floor: the timetable scrolls.** When even the course name of some block would not fit, the timetable goes back to the content-driven hour height, with all three lines in every block, and scrolls vertically inside its own box. The weekday row stays pinned (Scroll behaviour, item 5), and the timetable opens scrolled to the first lesson.
- **Screen only.** All of the above applies to the screen. Print is computed separately and is unchanged: every block keeps all three lines on paper, at every screen size (see Print).
- **Before there is a schedule** (no courses chosen yet), the column shows an empty week (ראשון–חמישי) and one line: "בחרו קורסים, והמערכת תופיע כאן".
- The no-possible-schedule state, the soft-conflicts panel and the relax-undo line take the timetable's place in the column, as they do today.

```
┌──────────────────────────────────────────────────────────────┐
│ [icon] SlotWise                          freshness   [theme] │
├──────────────────────────────┬───────────────────────────────┤
│ timetable (sticky)           │ ✓ מסלול   summary      שינוי  │
│  5 מערכות מובילות [sort] ‹ › │ ✓ קורסים  summary      שינוי  │
│  [prev][prev][prev][prev]    │ ┌───────────────────────────┐ │
│  stats pills                 │ │ 3 active step             │ │
│  ┌────────────────────────┐  │ │   helper, controls        │ │
│  │ א  ב  ג  ד  ה          │  │ └───────────────────────────┘ │
│  │ blocks with full info  │  │ 4 מרצים (upcoming)            │
│  └────────────────────────┘  │                               │
│  legend  |  lesson details   │                               │
└──────────────────────────────┴───────────────────────────────┘
```

On wide screens the "בנה מערכת" button, the floating bar (`#sticky-bar`) and the settings pills are not shown: the steps are on screen and the timetable is always current. The "הצג מערכת" overlay is not reachable there either (its button lives in the floating bar); if it is open when the window widens past the breakpoint, it closes. On narrow screens the floating bar and the overlay stay as they are today until Phase 8. While a solve is running, the timetable header row shows a quiet "מעדכן…" in `--mut` next to "5 מערכות מובילות" instead of the build button.

**Narrow screens (<1200px, including phones): one scrolling column.** Steps first, then the "בנה מערכת" button, then the results section (settings pills, alternatives, timetable, legend, details) below.

```
┌───────────────────────────────────────────────┐
│ [icon] SlotWise        freshness   [theme]    │  header
├───────────────────────────────────────────────┤
│ ✓ מסלול   summary                    שינוי    │  completed step (one line)
│ ✓ קורסים  summary                    שינוי    │
│ ┌───────────────────────────────────────────┐ │
│ │ 3  Step title                             │ │  active step (ink border)
│ │    one-line helper                        │ │
│ │    controls                               │ │
│ └───────────────────────────────────────────┘ │
│ 4  מרצים                                      │  upcoming step (muted)
│              [ בנה מערכת ]                    │
│ results section                               │
└───────────────────────────────────────────────┘
```

RTL throughout; English strings (footer) are marked `dir="ltr"`. If the full block content (see Results) no longer fits at the low end of the wide range, raise the breakpoint rather than drop content.

## Steps

### General step behaviour

- **Completed:** one line: check dot (ink background), step name in `--sec`, summary in 500 weight, "שינוי" link at the end. Clicking "שינוי" reopens the step.
- **Active:** full panel with a 1px `--ink` border. Number dot, title (20px/800), **one** line of helper text, then the controls. The orange summary line shown today under each title is removed while the step is open; the controls themselves show the current value.
- **Upcoming:** one muted line with an outlined number dot.
- The row of progress pills at the top of the page is removed; the stepper itself shows progress.
- Opening and closing a step animates height (`grid-template-rows: 0fr → 1fr`, 350ms, `cubic-bezier(.2,.8,.2,1)`).
- **A step is completed only when the user confirms it.** The active step ends with a "המשך" button at its bottom; a step counts as completed only after the user presses it. Valid default values alone never complete a step. The lecturers step is optional, so its "המשך" works with no rankings or pins. Live rebuild is unchanged: the schedule keeps updating on every change, regardless of step state. Implemented in Phase 8, not before.

### Program, year and semester

Keep the current controls and behaviour; apply tokens, type and the general step behaviour only, with these additions (decided 2026-09-26):

- **Specialization picker.** Appears only for programs that have specializations, and only from the semester where the curriculum diverges: Civil and Industrial from semester 3, Mechanical from semester 5, Electrical from semester 7. When shown it is required, and marked with an `--ink` border like the active control. Industrial also shows the line "את ההתמחות בוחרים עד סוף שנה א׳".
- **Electrical, from semester 7:** two pickers, "סוג תכן הנדסי" (בתעשייה / מחקרי / פרויקט גמר) and "התמחות ראשית". A third, "התמחות משנית", appears only when the design route is מחקרי or פרויקט גמר.
- **Industrial, תכן ותפעול specialization, from semester 7:** one more picker for the route: "התמחות בתעשייה" or "פרויקט גמר".
- **"Other program" option** stays, labelled "מסלול אחר" (2026-09-27; it was briefly "לא מופיע ברשימה — עבודה מהקטלוג בלבד"). Its behaviour does not change: the student works from the catalog only.

### Courses

- **Helper line:** "סמנו את הקורסים שתלמדו בסמסטר."
- **Search and credits:** the search field's placeholder is "הוספת קורס מהידיעון, גם מסמסטר קודם". A live credit counter ("N נ״ז") sits next to it and replaces the "סך נקודות זכות" tile.
- **Recommended courses:** the paragraph about recommended courses becomes a heading "מומלצים לסמסטר X", with "לפי תכנית הלימודים" as secondary text and a "סמנו הכל" link. The list of unchecked ("בוטלו") courses is removed; the cards already show their state.
- **Credit-total mismatch:** where the curriculum's printed credit total for the semester does not match its rows, the only line under the heading is "סך הנקודות המומלץ לסמסטר הזה שונה בין השנתון לידיעון" (2026-09-27). The explanation of each mismatch is not shown; it stays in the semester's `note` in the data file, and the full texts are recorded in `docs/PROGRAM_REVIEW.md`.
- **Course card:** checkbox, name (600) with the code in muted text, credits at the end; one line with the lesson structure and prerequisites; and an optional muted "מחליף את …" line. The "בתוכנית-סמסטר X" tag on each card is removed. A selected card gets its course color as the inline-start stripe and tint: the same color the course will have in the timetable.
- **Linked courses:** each linked card keeps today's "קורס צמוד" badge in its current color, plus one short line "נבחר יחד עם …". Selecting one still selects all of them. The long per-card sentence and the paragraph below the cards are removed.
- **Semester notes:** a gold note at the top of the step, shown only in semesters where the curriculum places an elective or general-course slot, e.g. "בסמסטר הזה מומלץ לבחור קורסי בחירה" or "בסמסטר הזה מומלץ לבחור קורס כללי (קורס כללי 2)". Colors: light text and icon `#9a7a32`, background `#faf3e3`, border `#e8d6ab`; dark `#d4b06a`, `#2a2418`, `#4a3f28`. Where the curriculum says "any semester" instead of naming one, show one quiet info line, not a gold note.
- **Specialization badge:** a recommended course that is mandatory only in the chosen specialization carries a "חובה בהתמחות X" badge, an `--ink` outline pill. It is separate from the "קורס צמוד" badge; a card can carry both.
- **Elective clusters** (decided 2026-09-27; **supersedes** the 2026-09-26 "Elective requirements" decision, under which the program's rules were listed in a box with their source and a "בסמסטר הזה: X" count, with no "met" states).
  - The requirements list is removed from the interface, and so is the subtitle "דרישות לתואר, לפי תכנית הלימודים". The heading "קורסי בחירה" stays above the clusters. `elective_rules` and `elective_lists` stay in the data unchanged; only the display changes.
  - **Each cluster is one line that opens on click** (decided 2026-10-05; supersedes "a box with its name, its minimum as a pill, and its courses as chips", which made the section up to 2718px tall in the 400px steps column for Software Engineering). The line holds the cluster's name, its minimum pill (with the ✓ as before) and, at the end, "נבחרו N" when N of its courses are selected, otherwise "N קורסים". Clicking it opens the cluster's chips and every note that belongs under it (only-one-of, composition, text rules). Only one cluster is open at a time; opening one closes the other. All clusters are closed when the step opens and whenever the program, year or semester changes. The heading "קורסי בחירה" and the lines under it are not collapsible. Same behaviour on wide and narrow screens.
  - **"At least N courses from cluster X"** rules are not written out: the cluster's minimum pill already says it. When N courses of that cluster are selected in the current semester, the pill gets a teal ✓ (`--brand-wise`): "לפחות קורס אחד" at one, "לפחות 2 קורסים" at two (decided 2026-09-27, for every minimum pill). Courses that the rule counts as one (`count_one_of`, e.g. 51535/51537) count once. The app still does not know what was taken in earlier semesters, so the ✓ means "chosen this semester", not "requirement met".
  - **A group that exists only in a rule** (Industrial, תכן ותפעול: "at least 2 from the special group", per route) is its own cluster box, "רשימת בחירה מחייבת" (renamed 2026-09-28: `industry.pdf` gives the group no name, only "לפחות שניים מקורסי הבחירה חייבים להיות מהקבוצה הבאה"), with its minimum pill ("לפחות 2 קורסים") and the same ✓. The rule's `cluster_title` asks for this.
  - **A card note from a rule** (`course_notes`): one line on that course's card, not under the cluster — e.g. 51170, "לאחוזון 80 ומעלה, באישור רמ״ח".
  - **Mandatory in the specialization, outside the semester plan** (`mandatory_in_specialization`; Civil, ניהול הבנייה: 500210, 51600): the "חובה בהתמחות X" badge appears on the course's chip in the cluster box and on its card once added.
  - **"Only one of" rules** (`mutually_exclusive`, `only_one_counts`, including "whoever took X cannot register for Y") are shown as a one-line gold note under the cluster that contains those courses, e.g. "אפשר לקחת רק אחד מ-62002 ו-62023". When the courses sit in more than one cluster, the note appears under every cluster that holds at least one of them (decided 2026-09-27 for Industrial 251966/51515 and Software 251100/251965).
  - **Which rules are shown** (principle, decided 2026-09-27): show the rules that decide which courses to pick or which of them count — composition ("of them, at least 3 hardware"), caps ("up to 4 credits of entrepreneurship"), "only one of". Do not show degree-level totals of credits or of course counts ("at least 20 credits in the main specialization", "at least 7 electives", "28.5 credits"). Each shown rule is one line.
  - **Composition** rules (a minimum over part of one cluster, e.g. Electrical, Computers: "מתוכם לפחות 3 מתחום החומרה ולפחות 3 מתחום התוכנה"; 1 + 1 for the secondary) are one line under that cluster.
  - Text rules are shown only when the data marks them `"show": true`. Approved on 2026-09-27: IS "one elective must be an English seminar" and Math "3.0 credits of mathematical electives" as one line under the heading (no list); Mechanical's 4-credit entrepreneurship cap as one line under the enrichment cluster (its list). Not shown: Electrical's and Mechanical's credit totals, Industrial's "at least 7/8 electives" and "a course cannot count in two clusters".
  - Rules that do not affect choosing courses for a semester (e.g. converting credits for social activity or reserve duty) are not shown.
  - Source citations (file name and page) are not shown. They stay in the data.
  - A program with no clusters in its data shows no clusters.

### Study days

- Buttons for each possible number of days. The selected one is filled `--ink`.
- The minimum possible value gets a small "מינימום" label under it.
- Values below the minimum are dashed and muted, **but stay selectable** (decided 2026-09-24): selecting one is the only way to see the warning and the "מה יאפשר N ימים" panel that lists which courses to drop to reach it. When selected, it is filled `--ink` like any selection.
- The explanatory sentence shown today becomes the one-line helper; nothing else repeats it.

### Lecturers

- Helper line: "לחצו על מרצים לפי סדר העדפה. הנעץ קובע קבוצה."
- "איפוס" is a small text link in the step header, not a large button.
- The legend (first preference / pinned / no-solution) is removed. The controls explain themselves: an empty dashed circle means "click to rank", a filled numbered circle is the rank, the pin icon is pinning.
- The list of sessions without mandatory attendance collapses into one pill ("N שיעורים ללא חובת נוכחות") that expands the list, followed by one short line explaining what that means.
- **Course card (accordion):** 4px course-color stripe, course name (600), code and credits in `--mut`, and at the end a live summary of the current choice: "לא דורג", "עדיפות: A ← B", or "נעוץ: A". Only one course is open at a time.
- **Inside a course:** a mandatory-attendance switch with an ⓘ that reveals the existing explanation inline. The sentence about attendance (currently repeated on every group row) appears once here, not per row.
- **Group rows:** rank circle, lecturer, type, day and time, room, pin button. Group number moves to the lesson-details view on the results page (or a tooltip here); it is not a column.
- Clicking a row assigns the next rank; clicking a ranked row removes it and renumbers. Rank assignment has a short pop (250ms scale to 1.2 and back).
- A pinned row gets the course tint as background and a filled pin in the course color.
- A group that leaves no possible schedule is dimmed, is not clickable, and carries a one-line reason under the lecturer's name ("לא משאיר מערכת אפשרית"). This replaces the pink legend color. It is dimmed **with color, not opacity** (decided 2026-09-24): text in `--mut`, the rank circle and pin faded. Opacity on text is banned by `tests/test_no_opacity_on_text.py`, which exists because faded text failed contrast.
- **A group with no meeting time** (decided 2026-10-03): when another group of the same course and kind has meetings, the solver never chooses it. Its row is shown exactly like a group that leaves no possible schedule — dimmed with color, not clickable, not rankable, not pinnable — but its one line reads "אין לקבוצה מועד קבוע" instead of "לא משאיר מערכת אפשרית". When no group of that component has meetings, its groups stay normal rows, and the course appears on the results page as before.
- "עודכן לפני X שעות" is shown once, in the header, not per course.

## Results page

Shown after "בנה מערכת", and kept up to date by the existing live rebuild. Uses the existing solve response, which already returns several ranked alternatives. **The number of alternatives stays 5**, the current `top_n`; it is not raised (decided 2026-09-30; supersedes "request enough alternatives to fill the previews").

Items 2–5 below were decided 2026-09-30 and **supersede** the earlier text of items 2–5.

1. **Settings pills:** one row of pills summarising every step (program, courses and credits, days, lecturer preferences), with "עריכת ההגדרות" at the end, which returns to the steps.
2. **Header row:** "5 מערכות מובילות", a sort select, previous/next buttons with "1 מתוך 5" between them, and a small "הדפסה" button. "נמצאו N מערכות" is **not** shown: `feasible_count` must not be displayed (see DEFERRED.md, "`feasible_count` counts intentional overlaps too").
   - Sort options: "התאמה להעדפות" (the default: the server's order), "הכי פחות חלונות", "מסיים הכי מוקדם", "הכי פחות ימים". Sorting runs in the browser only, over the 5 alternatives received; it does not call the server. Ties keep the server's order.
3. **Alternative previews:** one card per alternative (5). Each card is a miniature of the week (5 columns, blocks in course colors, no text), the line "N ימים, עד HH:MM" under it, and under that the existing differentiator label the tabs show today (e.g. "דומה למערכת 1, בהבדל של קבוצת תרגול אחת"). The selected card has an `--ink` border. Clicking a card selects that alternative. The cards **replace** the alternative tabs and the "מה ההבדל?" comparison table, which is removed.
4. **Stats pills** for the selected alternative, in this order: the existing fit ("ההתאמה הגבוהה ביותר" for the best alternative, otherwise "התאמה N%"), days on campus, finish time, total gap hours ("בלי חלונות" when zero), credits. A sixth pill, "N מתוך N מרצים מועדפים", follows credits whenever lecturer preferences exist (decided 2026-09-30); it is always visible, not only in a tooltip, because phones have no tooltips. Under the pills, one plain sentence that a student understands (decided 2026-10-01; supersedes the line "מה הוריד מההתאמה: …" in the scoring terms): "מה פחות טוב במערכת הזו: …", listing what lowered the fit, heaviest first, in the student's words — "מסתיימת מאוחר", "ימי לימוד ארוכים", "חלונות בין שיעורים", "יותר ימים ממה שביקשת", "שיעורים חופפים" — and, for preferred lecturers who are not in the schedule, "בלי המרצה שבחרת: X" ("בלי המרצים שבחרת: X, Y" for more than one). It reads the same on the top schedule. When nothing lowered the fit, the line is omitted. **Full groups** (decided 2026-10-02): when the selected alternative contains at least one full group (item 5's definition: `status_note` exactly "הקורס מלא", with or without a meeting time), one more line follows, directly under the pills when the sentence above is omitted: "חלק מהקבוצות במערכת הזו מלאות, ואי אפשר להירשם אליהן." It changes with the selected alternative and is omitted when that alternative has no full group. Full groups stay selectable; excluding them was measured and deferred (docs/PROPOSAL_FULL_GROUPS.md).
5. **Timetable:** days ראשון–חמישי as columns (RTL), hours as rows with `--ln` hairlines. Each lesson block has three lines: (1) course name, (2) lesson type · time, (3) lecturer · room. Block colors are the existing ones: `--course-N` fill, 1px `--course-N-bd` border, `--course-N-fg` text. **The hour height is set so that every block shows all three lines in full:** no line is dropped and nothing is clipped. The one exception is the wide-screen fitting order (Layout, step 3, decided 2026-10-03), where a short block may drop whole lines on screen only; nothing is ever clipped mid-line, and print is unaffected. `fitBlocks()`'s line dropping is removed (see DEFERRED.md, "Grid blocks ship with lecturer names sliced in half"). The height comes from the content, not from a fixed number. For reference, measured 2026-09-30 on Software Engineering semester 5 (the six recommended courses): 76px per hour at 1440px wide (912px for 08:00–20:00), and 112px per hour at 1200px wide. This supersedes "start from ~48px per hour". Re-measured 2026-10-03 on the same schedule, one-column layout: 64px per hour at 1440px wide. On wide screens the hour height is further limited by the screen (see Layout, "The whole week fits the user's screen"). Nothing is moved out of the block; the lesson-details panel (item 8) is an extra, not a replacement. Days with no lessons are simply empty.
   - **No fixed meeting time:** one line under the legend lists every component of the selected alternative that has no fixed meeting time (decided 2026-10-03; before, only courses with no timed component at all were listed). A course with no timed component at all reads "<name> (<type>, N נ״ז)"; a course whose other components are timed reads "<name> (<type>)", naming only its components without a time and no credits, since its timed parts are on the grid. For example: "ללא מועד קבוע: מבוא לפיזיקה אקדמית (שו"ת)".
   - **Full groups** (decided 2026-10-01; clarified 2026-10-02): a group is full when its `status_note` — the yedion's own status text, kept apart from `note` — is exactly "הקורס מלא". Its block ends line 3 with "קבוצה מלאה": "<lecturer> · <room> · קבוצה מלאה", and the content-driven hour height still fits all three lines. The no-fixed-time line carries it too: "ללא מועד קבוע: <name> (<type>, N נ״ז) · קבוצה מלאה". The other two statuses, "מיועד לחוזרים" and "בקורס זה קיימת רשימת המתנה", are information, not a reason a group is unavailable: they appear only in the lesson details (item 8), in the yedion's own words, with no short form, no mark on the block and no penalty. The lesson details show any status, whatever it says.
   - **No count line under the timetable** (decided 2026-10-01): "מוצגות 5 המערכות המובילות" is removed; the header row already says "5 מערכות מובילות".
   - **Unchanged:** the soft-conflicts panel, the "no possible schedule" state with its relaxations, and the relax-undo line stay where they are today, in place of the timetable.
6. **Switching alternatives:** blocks are persistent elements keyed by lesson and animate `top`, `right` and `height` to their new position (550ms, `cubic-bezier(.2,.8,.2,1)`), so the student sees exactly what moved.
7. **Course legend:** color, name, credits. Hovering a legend chip greys out every other course's blocks with colour, not opacity: fill and border in neutral tokens, text in `--mut` — the same treatment as the dimmed group rows in the lecturers step. On touch screens, tapping a chip toggles the same state, and tapping again clears it. (Decided 2026-10-01; supersedes "dims all other blocks to 18% opacity", since opacity on text is banned by `tests/test_no_opacity_on_text.py`.)
8. **Lesson details:** clicking a block outlines it in its course color and shows lecturer, day and time, room and group number in a details panel next to the legend. **On wide screens** (decided 2026-10-03) the panel takes the legend's place, in the legend's height, with its fields side by side, so opening it never changes the timetable's size or moves a block; closing it brings the legend back.

Items 6 and 8 are unchanged by the 2026-09-30 decisions; item 7 was revised on 2026-10-01. The sticky bar and the "הצג מערכת" overlay are not changed in Phases 5–6. On wide screens they are decided (2026-10-03, see Layout); on narrow screens they are decided with Phase 8.

**Print** (decided 2026-09-30). The printed sheet is the timetable on portrait A4, and every block keeps all three lines: nothing is dropped or clipped on paper either. To fit the week on one page, the block font on paper scales down in 0.5px steps from 13px, with a floor of 10px, and the hour height is re-measured from the content at each step. This is the one exception to the 13px block-text floor, and it applies to print only; the screen stays at 13px. If the week does not fit even at 10px, the sheet prints at 13px on two pages. The wide-screen fitting (Layout, "The whole week fits the user's screen") never reaches paper: a block shortened on screen prints with all three lines (decided 2026-10-03). The empty-day header stays as it is. Room codes never wrap mid-code ("L 706" stays on one line). Measured on Software Engineering semester 5: one page at 10.5px.

## Scroll behaviour

No scroll-triggered entrance animations. Only these, each because it saves the user a scroll or a question. Items 1 and 4 apply to the narrow layout only; 2, 3 and 6 apply to both (on wide screens, 2 and 3 scroll the steps column). Item 5 applies to both: on wide screens, whenever the timetable scrolls inside its box (Layout, step 4 of the fitting order).

1. **Shrinking header.** After ~20px of scroll the header becomes a thin sticky bar (smaller logo and padding, bottom border) and shows "שלב X מתוך Y".
2. **Auto-scroll to the next step.** Completing a step collapses it, opens the next one and smooth-scrolls it into view below the header. "שינוי" on a completed step scrolls to that step, reopens it and briefly outlines it.
3. **Sticky course header.** In the lecturers step, the open course's header sticks below the page header while its group rows scroll.
4. **Floating build button.** While the in-page "בנה מערכת" button is off-screen, a sticky bar at the bottom of the viewport shows a one-line summary and the button; it slides away when the real button is visible (IntersectionObserver). The button is always clearly readable: filled `--ink` with `--sf` text in both modes, hover slightly lighter in light mode (`#2a2a2e`) and slightly darker in dark mode (`#d9d9d6`), visible focus ring. The same styling applies to the in-page button.
5. **Sticky weekday row.** When the timetable scrolls vertically (mainly on phones), the ראשון–חמישי header row stays pinned.
6. **One landing moment.** The first time the results page shows a schedule, the blocks land one after another (≈70ms stagger, 500ms each). This happens once per build, not when switching alternatives (which uses the move animation) and not on scroll.

## Quality floor

- Contrast: body text AA against its surface in both modes.
- Visible keyboard focus on every interactive element; ranking, pinning, accordions and alternative cards are operable by keyboard.
- `prefers-reduced-motion`: all transitions and the rank pop become instant.
- **Mobile:** single column. The timetable scrolls horizontally inside its own container (never the page), or switches to one day at a time with day tabs if that reads better. Alternative previews scroll horizontally. Group rows collapse room into the time line.

## Existing behaviour to preserve

- **Live rebuild already exists.** Every settings change goes through `setState` → `syncData` → `scheduleSolve`, which calls `/api/solve` after `SOLVE_DEBOUNCE_MS` (150ms) and cancels the previous browser request. The build button calls `doSolve()` immediately and scrolls to the result. The redesign keeps this exactly; it only changes presentation.
- **Choosing which alternative is shown** already exists and does not re-solve (`{ solve: false }`). The new alternatives UI replaces its presentation, not its logic.
- **All existing settings stay**, including those not drawn in the mockups: no Friday, earliest and latest hour, allow soft conflicts, blocked time windows. They live in the study-days step under a collapsed "הגדרות נוספות" disclosure, closed by default, with a one-line summary of any non-default values when closed.

## Out of scope for now

- Server-side solve deadline (the server keeps computing after the browser cancels). A backend task for the load-test work, not part of this redesign.

## Implementation phases

Each phase is its own commit, keeps all existing tests green, adds tests where behaviour changes, and is checked in the browser in both modes and at phone width before moving on.

1. **Tokens and type.** Introduce the color tokens for both modes and Heebo. No layout changes.
2. **Stepper.** General step behaviour: completed/active/upcoming states, remove the progress pills and the per-step summary line while open, animated open/close.
3. **Study days** step as specified.
4. **Lecturers** step as specified.
   - **Courses step** as specified under Steps → Courses. Now includes specializations (the pickers under Program, year and semester, the specialization badge, the semester notes and the elective requirements). *Research done; to be built after its data work (specialization, elective-rule and semester-slot data in the program files).* Listed after Phase 4 without a number of its own, so that the phase numbers referenced elsewhere (e.g. "Phase 8") stay valid.
5. **Results page** (updated 2026-09-30): settings pills (item 1, narrow screens only), three-line blocks, content-driven hour height with no dropped lines, the fit pill and the "מה הוריד מההתאמה" line, stats pills, legend, the no-fixed-time line.
6. **Alternatives** (updated 2026-09-30): 5 preview cards with the differentiator label, the 4 sort options, previous/next, removal of the tabs and the "מה ההבדל?" comparison table, the move animation, lesson details.
7. **Wide layout** (updated 2026-10-03): side-by-side steps and the one-viewport sticky timetable column at ≥1200px, with the four-step fitting order, the lesson details in the legend's place, the empty-week state and "מעדכן…"; hiding the build button, floating bar, "הצג מערכת" overlay and settings pills there. Print stays all three lines at every screen size, with a test that proves it from a window where the screen shortens blocks.
8. **Scroll behaviour** as specified, per layout.
9. **Mobile and accessibility pass** across everything above.
   - Decide how timetable blocks show all three lines at phone width (e.g. horizontal scroll with a minimum column width, or one day at a time with day tabs). Nothing is dropped or clipped. (decided 2026-09-30)
