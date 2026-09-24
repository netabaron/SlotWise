# SlotWise UI redesign

This document is the source of truth for the SlotWise redesign. Implement it in the phases listed at the end, one phase per commit. Where this document and the current code disagree, this document wins; where it is silent, keep the current behaviour.

## Principles

1. **All content stays; presentation changes.** Nothing a student can learn today disappears. Every piece of information appears once, in the place where it is used.
2. **Color belongs to the courses and the logo.** The interface uses a single ink color (the logo navy in light mode) on neutral surfaces. Saturated color is reserved for the course colors, each used identically in the steps and in the timetable, and for the logo (see Logo and favicon).
3. **Motion explains, it does not decorate.** Motion is used only in response to the user's action: a step or course opening and closing, a rank being assigned, timetable blocks moving between alternatives. No scroll-triggered entrances, no glow, no gradients, no ambient animation.
4. **The active step is the only loud thing.** Completed steps collapse to one summary line, upcoming steps are muted.

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

### Program, year and semester / Courses

Keep the current controls and behaviour; apply tokens, type and the general step behaviour only.

### Study days

- Buttons for each possible number of days. The selected one is filled `--ink`.
- The minimum possible value gets a small "מינימום" label under it.
- Values below the minimum are dashed and muted and cannot be selected.
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
- A group that leaves no possible schedule is shown at 40% opacity, is not clickable, and carries a one-line reason under the lecturer's name ("לא משאיר מערכת אפשרית"). This replaces the pink legend color.
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
5. **Results page:** settings pills, stats pills and the new timetable styling with course colors and legend.
6. **Alternatives:** previews, sorting, previous/next, animated transitions between alternatives, lesson details.
7. **Wide layout:** side-by-side steps and sticky timetable at ≥1200px, hiding the build button, floating bar and settings pills there.
8. **Scroll behaviour** as specified, per layout.
9. **Mobile and accessibility pass** across everything above.
