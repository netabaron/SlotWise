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

Course palette, assigned to courses in selection order and kept stable for the session:
`#5b5bd6` indigo, `#0e9f8e` teal, `#d98b06` amber, `#e5484d` red, `#8e4ec6` violet, `#2f8fd8` blue, `#c2571a` rust, `#3f8f3f` green.
A course's tint is `color-mix(in srgb, <course> 13%, var(--sf))`, which works in both modes.

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

**Wide screens (≥1200px): side by side.** The steps column sits at the inline start (right, RTL), about 400px wide. The timetable column takes the rest of the width and is `position: sticky` below the header, at most one viewport tall, scrolling internally if needed. Because the schedule already rebuilds live, every change in the steps is visible immediately next to it.

```
┌──────────────────────────────────────────────────────────────┐
│ [icon] SlotWise                          freshness   [theme] │
├──────────────────────────────┬───────────────────────────────┤
│ timetable (sticky)           │ ✓ מסלול   summary      שינוי  │
│  N מערכות  [sort]  ‹ ›       │ ✓ קורסים  summary      שינוי  │
│  [prev][prev][prev][prev]    │ ┌───────────────────────────┐ │
│  stats pills                 │ │ 3 active step             │ │
│  ┌────────────────────────┐  │ │   helper, controls        │ │
│  │ א  ב  ג  ד  ה          │  │ └───────────────────────────┘ │
│  │ blocks with full info  │  │ 4 מרצים (upcoming)            │
│  └────────────────────────┘  │                               │
│  legend  |  lesson details   │                               │
└──────────────────────────────┴───────────────────────────────┘
```

On wide screens the "בנה מערכת" button, the floating build bar and the settings pills are not shown: the steps are on screen and the timetable is always current. While a solve is running, the timetable header shows a quiet "מעדכן…" state instead.

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
  - Each cluster is a box with its name, its minimum as a pill, and its courses as chips.
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
- "עודכן לפני X שעות" is shown once, in the header, not per course.

## Results page

Shown after "בנה מערכת", and kept up to date by the existing live rebuild. Uses the existing solve response, which already returns several ranked alternatives. Request enough alternatives to fill the previews (default 5; the server allows up to 50).

1. **Settings pills:** one row of pills summarising every step (program, courses and credits, days, lecturer preferences), with "עריכת ההגדרות" at the end, which returns to the steps.
2. **Header row:** "נמצאו N מערכות", a sort select, and previous/next buttons.
   - Sort options: "הכי פחות חלונות", "מסיים הכי מוקדם", "הכי פחות ימים". Sorting runs in the browser over the alternatives already received; it does not call the server.
3. **Alternative previews:** a row of small cards, one per alternative, each a miniature of the week (5 columns, blocks in course colors, no text) with "N ימים, עד HH:00" under it. The selected card has an `--ink` border. Clicking a card selects that alternative.
4. **Stats pills** for the selected alternative: days on campus, finish time, total gap hours ("בלי חלונות" when zero).
5. **Timetable:** days ראשון–חמישי as columns (RTL), hours as rows with `--ln` hairlines. Each lesson is a block with a 3px course-color stripe on the inline-start edge and the course tint as background. **Every block shows all of its information inside the block, as the current site does:** course name (600), lesson type, lecturer, room and time, in `--ink`/`--sec`. The hour-row height is chosen so that a one-hour lesson fits all of these lines on desktop (start from ~48px per hour and adjust to the real content). Nothing is moved out of the block; the lesson-details panel (item 8) is an extra, not a replacement. On narrow screens text may wrap or truncate with an ellipsis, with the full text available on tap. Days with no lessons are simply empty.
6. **Switching alternatives:** blocks are persistent elements keyed by lesson and animate `top`, `right` and `height` to their new position (550ms, `cubic-bezier(.2,.8,.2,1)`), so the student sees exactly what moved.
7. **Course legend:** color, name, credits. Hovering a course dims all other blocks to 18% opacity.
8. **Lesson details:** clicking a block outlines it in its course color and shows lecturer, day and time, room and group number in a details panel next to the legend.

## Scroll behaviour

No scroll-triggered entrance animations. Only these, each because it saves the user a scroll or a question. Items 1, 4 and 5 apply to the narrow layout only; 2, 3 and 6 apply to both (on wide screens, 2 and 3 scroll the steps column).

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
5. **Results page:** settings pills, stats pills and the new timetable styling with course colors and legend.
6. **Alternatives:** previews, sorting, previous/next, animated transitions between alternatives, lesson details.
7. **Wide layout:** side-by-side steps and sticky timetable at ≥1200px, hiding the build button, floating bar and settings pills there.
8. **Scroll behaviour** as specified, per layout.
9. **Mobile and accessibility pass** across everything above.
