# SlotWise — UI/UX overhaul brief

You are working on SlotWise, a local-only web app that scrapes Braude College's course
catalog (yedion) and generates possible semester timetables for a student, ranked by the
student's preferences (courses, study days, lecturers, attendance requirements).

The engine works. The interface does not. Everything below is about the **presentation
layer only**.

## Ground rules

1. **Do not change the scheduling/scoring algorithm, the scraper, or the data model.**
   If a change to the UI requires new data from the backend, expose it, but don't alter
   how schedules are generated or ranked.
2. The UI is Hebrew and RTL. Every string below that must appear in the product is given
   in Hebrew — use it verbatim. Keep `dir="rtl"` `lang="he"` on the root.
3. The audience is a student who has never seen this app before and will use it for ten
   minutes, twice a year, probably on a phone. They are not a developer and have not read
   any documentation.
4. Work in the phases below, in order. After each phase, stop, summarize what changed,
   and let me review before moving on. Commit each phase separately.
5. Before you start: read the existing templates/CSS/JS and tell me what the stack is and
   where the strings live. If strings are scattered inline, extract them into one
   strings/i18n module as part of Phase 1 — I want to be able to edit all copy in one file.
6. Preserve every existing capability. This is a re-presentation, not a feature cut.
   The only things allowed to disappear are the developer-facing diagnostics listed in
   Phase 1, which move behind a debug toggle.

---

## Phase 1 — Copy and messaging

The single biggest problem: the app talks like a developer's log file. Fix the words
before touching a single pixel.

**Principles**
- One sentence in the interface; anything longer goes behind a "מה זה?" disclosure.
- Name things by what the user does, not by how the system works.
- A message appears only if the user has to decide or act on it.
- Never show internal identifiers, timings, or counts unless the user asked for them.

**Remove from the default UI** (move all of these behind a `?debug=1` flag or a
collapsed "פרטים טכניים" section at the very bottom):
- `(חישוב: 294 מ״ש)` — runtime in ms.
- `נמצאו 2400 מערכות אפשריות` — keep only `מוצגות 5 המערכות המובילות`.
- `קטלוג: 571 · תשפ״ז 431` in the header chip.
- The `לפני 48 דקות` string next to each course. Find out what it actually refers to
  (last scrape? last catalog update for that course?) and tell me — then either delete it
  or rename it so it says what it means, e.g. `עודכן לפני 48 דקות`.
- Raw group/component IDs (`271060310/1`) as primary text. They may stay as small
  secondary metadata inside the detail panel, never in a calendar block.

**De-duplicate the header.** Right now the data-freshness status appears twice (a chip in
the toolbar and a full-width banner underneath) and `רענון מהידיעון` appears twice on the
same screen. Keep one status line and one refresh button.

**Make the staleness banner conditional.** The current banner says the data is 3 days old
and 398 courses are stale — and then says none of the user's selected courses are affected.
If nothing the user selected is affected, this is not a banner. Rules:
- No selected course affected → quiet single line in the header, no banner, no dismiss X:
  `הנתונים עודכנו לפני 3 ימים`
- One or more selected courses affected → amber banner naming them:
  `2 מהקורסים שבחרת התעדכנו בידיעון מאז החישוב האחרון: 61753, 62027. כדאי לרענן.`
  with a single button `עדכן נתונים`.

**Rename the toolbar buttons** — they currently describe the implementation:
- `רענון מהידיעון` → `עדכן נתונים מהידיעון`
- `בנייה מחדש ללא רשת` → `חשב מערכות מחדש`
- `יומן` → make it explicit what it does; if it exports, `ייצוא ליומן`.
- There must be exactly **one** visually primary button on the settings screen:
  `בנה מערכות`. Everything else is secondary/ghost.

**Collapse the attendance explainer.** The paragraph that currently begins
`כברירת מחדל לכל רכיב יש חובת נוכחות…` and then lists course codes inside running prose
must become:
- Visible line: `לכל שיעור מסומנת חובת נוכחות. ביטול הסימון מאפשר לשבץ שיעור אחר במקביל — על חשבון הנוכחות.`
- A `מה זה?` disclosure containing the longer explanation.
- The list of components without attendance becomes a **list**, not prose — one row per
  item, course name + component type, not a comma-separated string of codes.

**Rewrite the overlap warning.** Current version is a yellow paragraph. Replace with a
heading + one line per overlap:
- Heading: `חפיפה מכוונת אחת (2:00 שעות)`
- Row: `61753 אלגוריתמים (הרצאה) מול 61756 שיטות הנדסיות (תרגול) · יום ד׳ 08:30–10:30 · אפשרי כי סימנת שאין חובת נוכחות באלגוריתמים`
- Use course **names** first, codes second.

**Terminology pass** — replace throughout:
| Current | Replace with |
|---|---|
| `חורים` | `זמן המתנה` |
| `רכיב` | `שיעור` (or `מפגש`) |
| `צפיפות` | `רצף שיעורים` — and make the direction explicit (see Phase 2) |
| `סיום מאוחר` | `שעת סיום` |
| `נעיצה` | keep, but add a one-time tooltip: `נעיצה מחייבת את המערכת לכלול דווקא את הקבוצה הזו` |

**Consistency**: one format for durations everywhere. Pick `2:30 שעות` or `שעתיים וחצי`
and use it in the header, the score panel and the warnings — not a different one in each.

---

## Phase 2 — The score

Currently: `ניקוד -49.2` with the label `גבוה = טוב יותר`, broken into `חפיפות מכוונות -6`,
`סיום מאוחר -30.7`, `צפיפות -26.5`, `מרצים מועדפים 3/4`, `נ״ז 19`, `חורים 2:30`, `ימים 5`.
A negative number that is "better when higher" is unreadable, and the panel mixes penalty
scores with plain facts as if they were the same kind of thing.

1. **Normalize the headline score to 0–100** across the returned set (best schedule in the
   result set = 100). Label it `התאמה` and show it as `87 / 100`. Keep the raw internal
   score available in debug mode only.
2. **Split the panel in two.**
   - *Facts about this schedule*: `ימים`, `נ״ז`, `שעת סיום`, `זמן המתנה` — neutral styling.
   - *What lowered the score*: penalty components, shown as small horizontal bars with
     human labels, e.g. `סיום מאוחר — הגורם המשפיע ביותר`. Never show a bare negative float.
3. **Say what each penalty means on hover/tap**, one sentence each:
   `סיום מאוחר: כמה מאוחר מסתיימים הימים, ביחס לשאר האפשרויות.`
4. `מרצים מועדפים 3/4` should say which one is missing:
   `3 מתוך 4 מרצים מועדפים · חסר: מר חסאווי טירן`.

---

## Phase 3 — Choosing between schedules

Current tabs read `מערכת 1 · 5 ימים · חורים 2:30`, `מערכת 2 · 5 ימים · חורים 2:30`,
`מערכת 3 · 5 ימים · חורים 2:30` — indistinguishable. The user cannot make a choice.

1. **Compute a differentiating label per schedule** and put it in the tab, e.g.
   `הכי מעט המתנה`, `מסתיימת הכי מוקדם`, `4 ימי לימוד`, `כל המרצים המועדפים`.
   If two schedules genuinely have the same profile, say so rather than faking a
   difference: `דומה למערכת 1, בהבדל של קבוצת תרגול אחת`.
2. **Add a "מה ההבדל?" comparison view** — a small table of the 5 schedules × the facts
   from Phase 2, so the differences are visible at a glance. This is the highest-value
   addition in the whole brief.
3. **The bare numbered circles `5 4 3 2 1` in the sticky header have no label.** Prefix
   them with `מערכת:` or replace them with the labeled tabs. A user cannot guess what
   those circles are.
4. The sticky header currently repeats `ימים 5 · מסיים 19:50 · חורים 2:30`, which also
   appears in the score panel below. Keep it in one place — the sticky header should carry
   the schedule selector and the primary action, not duplicated stats.

---

## Phase 4 — The calendar grid

This is where students will spend their time, and it's currently the least readable part.

1. **Reduce text per block.** Default block content: **course name + time range**, plus a
   small type indicator (הרצאה / תרגול / מעבדה / שו״ת / פרויקט). Lecturer, room, group
   number and notes move to a detail panel opened on click (side panel on desktop, bottom
   sheet on mobile).
2. **Never truncate with an ellipsis.** Blocks currently show `הרצאה · קבו…` and
   `חפיפה מכוונ…`. If it doesn't fit, it doesn't belong in the block.
3. **Crop the grid to the active hours.** The grid runs 08:00–20:00 even when the first
   class is at 10:30, leaving huge empty regions. Start at the earliest class minus 30 min,
   end at the latest plus 30 min. Add a toggle `הצג את כל השעות`.
4. **Hide or dim empty days.** יום ו׳ is completely empty in every generated schedule but
   takes a full column. Collapse empty days to a narrow dimmed strip labeled `אין שיעורים`.
5. **Overlaps.** Two half-width unreadable columns is the wrong treatment. Render the
   overlap as a single block with a badge `חפיפה` in the corner, expandable to show both.
   Whatever visual you use for the intentional-overlap marker (currently a dashed orange
   border) must appear in a legend.
6. **Put the course color legend adjacent to the grid**, not floating above the score panel
   far from it. Colors must be stable for the same course across all 5 schedules.
7. **Don't rely on color alone** to distinguish lecture/tutorial/lab — add a text or icon
   marker, and make sure the palette is distinguishable for color-blind users.
8. **Fix bidi on codes.** Room and building codes are Latin inside Hebrew text
   (`L 706`, `EF 506 מע׳`, `M 303`) and can reorder unpredictably. Wrap every such token in
   `<bdi>` or a `dir="ltr"` span. Same for time ranges — verify `08:30–10:30` renders in
   that order in every browser, and use `&#8211;` deliberately.

---

## Phase 5 — Structure and hierarchy of the settings screen

1. The settings sections (`מסלול, שנה וסמסטר`, `קורסים`, `ימי לימוד`, `מרצים`) all carry a
   green ✓ at all times, so the checkmark carries no information. Make it stateful:
   - grey outline = not touched yet (defaults in use)
   - green ✓ = the user made a choice
   - amber ! = a conflict or an impossible constraint
2. **Give the flow a sense of order.** Turn the accordion into a numbered flow —
   `1 מסלול · 2 קורסים · 3 ימים · 4 מרצים · 5 תוצאה` — with a persistent primary
   `בנה מערכות` button. Right now a first-time user doesn't know how many steps there are
   or when they're done. (Only number these if you present them as an actual sequence; if
   you keep the accordion, then at minimum add a progress line at the top.)
3. Every collapsed section must show its own summary — `קורסים` already does
   (`6 קורסים · 19 נ״ז`). Do the same for the others.
4. Remove the redundant summary chip under the מסלול selects: the line
   `שנה ג׳ · סמסטר א · סמסטר 5 בתוכנית` and the chip
   `שנה ג׳ · סמסטר א · סמסטר 5 בתוכנית הלימודים · 6 קורסים מומלצים` say nearly the same
   thing twice. Keep one.
5. Selects are currently full-width and of inconsistent widths. Size inputs to their
   content class, align them on a grid.
6. Reduce the middle-dot meta strings (`A · B · C`). They're used for every line in the app
   and they flatten hierarchy. Use them for at most one line per card.

---

## Phase 6 — Empty and error states (highest-value missing feature)

1. **Zero results.** There is currently no design for "no schedule satisfies these
   constraints", which is the single most likely frustrating moment. Build it, and make it
   *actionable* by testing which single constraint, if relaxed, unlocks the most results:
   > `לא נמצאה מערכת שעונה על כל הדרישות.`
   > `אם תוותרי על יום ו׳ פנוי — יימצאו 12 מערכות.`
   > `אם תוותרי על מר גיריס באנגלית טכנית — יימצאו 3 מערכות.`
   Each suggestion is a button that applies the relaxation and recomputes.
2. **Scrape failure / offline.** Say what still works: `לא הצלחנו להתחבר לידיעון. אפשר להמשיך עם הנתונים מ-2 בספטמבר.`
3. **Loading.** Generation takes real time — show progress with a cancel option, not a
   frozen screen.
4. Errors state what happened and what to do. No apologies, no vagueness.

---

## Phase 7 — Accessibility

1. The lecturer-section legend uses color-only squares (green = `קבוצה נעוצה`,
   red = `בחירה שמשאירה בלי פתרון`). Add an icon or text label to each.
2. Audit contrast in the dark theme. Muted grey secondary text (group IDs, timestamps,
   helper lines) is likely under 4.5:1 on the near-black background. Fix all body text to
   ≥ 4.5:1 and large text to ≥ 3:1. Check the light theme too.
3. The 📌 pin is an emoji used as a control: it renders inconsistently across platforms and
   has no accessible name. Replace with an inline SVG icon button with
   `aria-label="נעץ קבוצה זו"` / `aria-pressed`.
4. Minimum font size 14px for body, 13px for secondary. There is a lot of 11–12px text.
5. Full keyboard support: visible focus rings, tab order that follows the visual order in
   RTL, Enter/Space on every clickable table row, Escape closes panels.
6. Semantic markup: the group tables should be real `<table>` with `<th scope="col">`;
   the schedule tabs should be a real tablist with `aria-selected`; the accordion sections
   need `aria-expanded`.
7. Respect `prefers-reduced-motion`.
8. Announce recomputation with an `aria-live="polite"` region — currently the schedule
   silently changes under the user when a preference is toggled.

---

## Phase 8 — Mobile

Currently unusable on a phone: a 6-column × 12-hour grid plus dense tables.

1. Below ~700px, replace the weekly grid with a **single-day agenda**: a sticky day
   selector (`א ב ג ד ה ו`, with a dot marking days that have classes) and a vertical list
   of that day's classes.
2. Settings sections become full-width stacked form controls; tables become stacked cards.
3. The schedule selector becomes a horizontally scrollable row of labeled chips.
4. Tap targets ≥ 44px. The pin control in particular is currently far too small.
5. Test at 360px, 390px and 430px widths.

---

## Phase 9 — Actions on a chosen schedule

Currently the only action is `הדפסה`.
1. `ייצוא ליומן (ICS)` — one event series per component, with room and lecturer in the
   description.
2. `שמור מערכת` — keep a chosen schedule so it survives a recompute, marked `שמורה`.
3. `העתק סיכום` — plain-text summary for pasting into WhatsApp.
4. Fix print CSS: the printed page must show the grid, the course list, and nothing else —
   no toolbar, no debug strings, black-on-white regardless of the active theme.

---

## Acceptance checklist

Before you tell me a phase is done, verify:
- [ ] No string in the default UI contains a millisecond timing, a raw internal ID as
      primary text, or an internal term (`רכיב`, `קטלוג`, `מסד`).
- [ ] No message appears twice on the same screen.
- [ ] Every number shown to the user has a unit and a direction (is higher better?).
- [ ] No text is truncated with `…` inside the calendar grid.
- [ ] Every color-coded meaning also has a non-color indicator.
- [ ] Exactly one primary button is visible per screen.
- [ ] The app is usable start-to-finish with keyboard only.
- [ ] The app is usable at 390px width.
- [ ] There is a designed state for: loading, zero results, scrape failure, stale data.
- [ ] Both dark and light themes pass contrast checks.

## Out of scope

Do not redesign the visual identity from scratch, do not introduce a UI framework or a
component library, do not add animations beyond what communicates a state change, and do
not change any Hebrew string I specified above.
