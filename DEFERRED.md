# Deferred — things a phase found but did not fix

Anything noticed during the UI overhaul that belongs to a later phase, or to no
phase at all, gets written here the moment it is noticed. The point is that none
of it is rediscovered in Phase 9 as a surprise.

Format: what it is · where · which phase should own it · why it was not done now.

---

## Open

### Grid blocks ship with lecturer names sliced in half — **next up after the palette**
**Where:** `fitBlocks()` in `src/web/static/app.js:6855`, called from `app.js:6071`.
**Owner:** the first thing to fix once Phase 10's palette lands. Agreed 2026-09-08.
**What it looks like:** not an ellipsis — the glyphs are cut horizontally by the
block's own bottom edge, so the lecturer's name shows its top half and nothing
else. It reads as a rendering fault, not as truncation.
**The mechanism, measured rather than guessed:** `fitBlocks()` drops
`ev-drop-1/2/3` (room, time, lecturer) while `block.scrollHeight >
block.clientHeight`. Measured live, the short blocks report `scrollH 91` against
`clientH 83` — the test *works*, it correctly says "overflows". But
`hiddenLines` is **0**: nothing was dropped. So the function is not running
against the settled layout. It measures too early, breaks out of its loop, and
never re-runs.
**Rate, over five runs of the default semester-5 schedule:**

| width | runs that clipped | lines clipped | after a `resize` event |
|---|---|---|---|
| 1440px | 4 of 5 | 2 | 0 — always repaired |
| 390px | 5 of 5 | 4 | 0 — always repaired |

Dispatching `window.resize` fixes it every single time, which is what pins it to
ordering rather than to the drop logic. The same is true under `@media print`,
where `refitBlocks()` fires on the media change and 6 lines drop correctly.
**Pre-existing.** Present at `e6aaafb` (before any Phase 10 work). The 13px type
floor deepens each clip by about 1.9px but does not change how many lines clip.
**Probably the same root cause as** the load-sensitive
`test_neither_physics_track_is_marked` further down this file: both are
measurements taken before layout settles.
**Where to look first:** `fitBlocks(ui.grid)` at `app.js:6071` runs synchronously
inside the render path. It likely needs to run after layout — a
`requestAnimationFrame`, or a `ResizeObserver` on the grid, which would also
cover the width-change case the fixed call cannot see.

**It already fails a test, and that test is the better repro — 2026-09-08.**
`tests/test_rendered_copy_browser.py::test_overlap_halves_stay_readable_at_half_width`
fails: a half-width overlap block gives up its lecturer. Measured at 900px, on
the block the test names:

| state | space in the block | space the lines need | slack | lines dropped |
|---|---|---|---|---|
| `e6aaafb`, before any Phase 10 work | 167px | 79.4px | **+87.6px** | **4** |
| after commits 1–4 | 167px | 81.3px | **+85.8px** | **4** |
| with the Phase 10 palette applied | 167px | 81.3px | **+85.8px** | **4** |

So this is not a block that is too small. `fitBlocks()` threw away **four lines
from a block with 86px to spare**, which is a far clearer symptom than the 8px
clipping above and the same cause: it measured before the layout existed, found
what looked like an overflow, dropped everything in `DROP_ORDER`, and never ran
again. The three states are identical in behaviour — the 1.9px the type floor
added changes nothing here.

**Do not read the suite's history as this being new.** The full browser suite
passed at commits 3 and 4 and fails now, which looks like a regression and is
not: the test fails **3 of 3 in isolation at every one of the three states,
including `e6aaafb`**. The in-suite passes were the race landing the other way
when earlier tests had warmed the page. Two green runs were luck.

**Consequence for the fix:** whoever fixes `fitBlocks()` gets this test back for
free, and should check it rather than only the clipping. Until then the browser
suite is 62/63, with this the only failure.

### The printed sheet is now at the bottom of its ladder
**Where:** `fitGridToPage()` in `src/web/static/app.js:6892`, `SLOT_H_PRINT_MIN = 12`.
**Owner:** informational — no action pending, but read this before adding to a block.
**What:** the 13px type floor pushed the print fit down one rung. Measured on the
semester-5 default, 13 blocks:

| | slot height chosen | body height | fits one page |
|---|---|---|---|
| before the floor | 13px | 784px | yes |
| after the floor | **12px — the minimum** | 750px | yes (44px spare) |

Same six lines dropped, same 11 blocks keeping room and time, nothing clipped. So
the sheet is unchanged in content — but it is now sitting on `SLOT_H_PRINT_MIN`
with no rung left. The next thing that makes a block taller paginates the sheet,
and `fitGridToPage()` deliberately stops shrinking rather than print something
too small to read. A student with a denser semester than the default may already
be there; this was measured on one schedule, not on the worst one.

### Phase 7's 14px body half is not done — only the 13px floor
**Where:** `src/web/static/style.css`, everywhere.
**Owner:** Phase 7.
**What:** the brief asks for "minimum font size 14px for body, 13px for
secondary". This commit raised all 76 sub-13px screen rules to 13px, which closes
the secondary half. It did **not** promote sentence-level text — `.step-hint`,
`.note`, `.empty-sub`, `.fit-note`, `.relax-intro`, `.progress-hint` — to 14px.
**Why not:** deciding which rules are "body" is a judgement per rule, and each
promotion costs vertical space that the print sheet no longer has (see above).
A flat floor is mechanical and verifiable; a scale is a design decision, and the
three Phase 10 directions each propose their own. Doing it now means doing it
twice.
**Consequence to be honest about:** a floor flattens hierarchy. Rules that were
12.5px and 11px are now both 13px, so the relationship between them is gone. The
scale that restores it arrives with whichever palette direction is chosen.

### `.pin-btn` sits at 45% opacity as its resting state
**Where:** `src/web/static/style.css`, `.pin-btn`.
**Owner:** Phase 7 (item 3 replaces the control outright).
**Why it survived the opacity sweep:** the sweep removed multipliers from *text*.
`.pin-btn` is a control, and its `:disabled` state at `.2` is covered by WCAG
1.4.3's exemption for inactive components — but `.45` is its **enabled** resting
state, which is not exempt. It is left alone because Phase 7 replaces the emoji
pin with an inline SVG button carrying `aria-label` and `aria-pressed`, and
re-tuning the opacity of a control that is about to be deleted is wasted work.
Recorded so it is a decision and not an oversight.
`tests/test_no_opacity_on_text.py` lists it in `ALLOWED` with this reason.

### A missing string used to be invisible
**Where:** `T()` in `app.js`, Jinja rendering in `api.py`, `strings.py:load()`.
**Owner:** closed — fixed the moment it was found, not deferred.
**What happened:** the score panel shipped with every label blank and the penalty
bars showing `compactness` / `gaps` / `soft_conflict`. Root cause on the reporter's
machine was a stale copy of the strings tree; the *reason it could ship* was that a
missing key degraded silently — to `""` at some call sites and to the key name at
others. 545 of 548 tests passed on that page.
**Root cause, confirmed:** `app.js` is a static file, so the browser always
gets the current one — but `strings.py` read `strings.json` into a module-level
`_CACHE` once per process. A `webapp.py` server started before the `app.*` branch
was written kept serving a tree of only `meta`/`ui`/`server` for its whole life.
New client, frozen server copy: every `ui.*` string rendered (Jinja, server side)
and every `app.*` lookup failed. Reproduced and fixed; the hot-reload is verified
by editing `strings.json` under a running server and seeing the change served
without a restart.
**Now:** `T()` logs a console error, collects the key in `window.slotwise
.missingStrings()`, and renders `⟦path⟧` which `markMissingStrings()` outlines in
red. Jinja runs with `StrictUndefined`. `strings.py` raises on an empty or
section-less tree and reloads when the file's mtime changes, so a long-running dev
server cannot serve yesterday's copy. `tests/test_rendered_copy_browser.py` asserts
in a real browser that no label is empty and no raw key reaches the screen.

### `רכיב` as user-facing wording — **closed 2026-09-07, and it was overstated**
**What the entry used to claim:** that the infeasibility reasons and suggestions
built in `src/web/api.py` still used `רכיב` in user-facing text, and that Phase 6
would rewrite them.
**What was actually there:** almost nothing. Every `רכיב` in `src/scheduler.py`
and nearly all in `api.py` are docstrings and comments, which are correct — it is
the right internal term. The infeasibility reasons never used it: they say
`כל קבוצות ה{kind}`, substituting the real kind name (`הרצאה`, `תרגול`).
**The two genuine ones**, both validation errors, now say `סוג השיעור` with a
worked example instead of `סוג רכיב`:
`api.py` — the `pinned` shape error, and the `attendance` shape error.
**Worth recording as a habit, not just a fix:** this entry sat open for weeks
describing a rewrite that was never needed. A deferred item should name the exact
lines it means, or it grows in the retelling.

### The staleness banner and the header both offer a refresh
**Where:** `#btn-refresh` in the header, and the banner's `עדכן נתונים` action.
**Owner:** unassigned — needs a product call.
**Why not now:** the brief asks for "one refresh button" *and* specifies a button
inside the banner. Both are implemented; the banner is now rare enough that the
common screen has exactly one. Flagged so it is a decision and not an oversight.

### The fit score is relative to the five shown, not absolute
**Where:** `fitScores()` in `src/web/static/app.js`.
**Owner:** unassigned — needs a product call, possibly never.
**Why:** there is no absolute maximum to normalise against — `lecturer` is an
unbounded positive bonus and every other component is a penalty — so 100 can
only mean "the best of the five returned". The label says so and the tooltip
spells it out, but two different course selections can both show 100 while being
nothing alike. If an absolute scale is ever wanted, the scheduler would have to
expose a theoretical best for the chosen courses.

### The fit number is not the thing to choose on
**Where:** `fitScores()` / the `.fit` block in `src/web/static/app.js`.
**Owner:** informational — Phase 3 worked around it, no action pending.
**Why:** with five schedules inside a few points the score is honest but useless
as a decision aid. Phase 3 leads with the differentiating label and demotes the
number whenever the spread across the shown set is 5 points or less. The number
is still there, and still relative — see the entry above.

### Colour-blind distinguishability of the ten course colours — **measured 2026-09-08, and it is worse than this entry used to say**
**Where:** `--course-0..9` in `src/web/static/style.css`.
**Owner:** Phase 7 (accessibility) — and now Phase 10, because a new ramp is the
cheapest time to fix it.
**What this entry used to say:** that separability "is a palette question" to be
looked at later. That was true but it left the impression the current ramp was
merely untested. It was tested on 2026-09-08 and it fails badly.
**Measured** — dichromat simulation over the ten backgrounds, worst pair by ΔE:

| theme | worst pair | ΔE deuteranopia | ΔE protanopia |
|---|---|---|---|
| light | course-4 vs course-8 | 1.4 | **0.4** |
| light | course-5 vs course-8 | **0.6** | 5.3 |
| light | course-4 vs course-5 | **0.9** | 5.5 |
| dark | course-2 vs course-6 | 4.5 | **1.3** |
| dark | course-6 vs course-7 | **1.9** | 6.2 |

Six pairs collapse in each theme. A ΔE under about 2 is not "hard to tell apart",
it is the same colour. For a red-green colour-blind student roughly a third of the
pairwise comparisons carry no information at all.
**What Phase 4's mitigation does and does not cover:** every block states its
*kind* in words, so הרצאה vs תרגול is safe. **Which course a block belongs to is
still signalled by fill colour alone** — the block shows the course name, so a
single block is readable, but scanning the grid for "all my algorithms classes",
which is what the colour is for, is not.
**Why it cannot be fixed one hue at a time:** verified, not assumed. Dichromats
have essentially only lightness left, so moving one fill to separate it from its
neighbour re-collides it with another. Every single-hue repair tested during the
Phase 10 direction work *lowered* the worst-pair floor. The ramp is a joint
optimisation: no course colour is ever changed alone, and every change re-runs the
full simulation.
**Where it stands:** all three Phase 10 candidate ramps raise the floor
substantially (worst pair ΔE 4.5–6.9 against today's 0.4), which is a 5–15×
improvement but still not full separation — ten categories cannot be made
unambiguous for a dichromat by fill alone. That is why the 1px per-course border
is load-bearing in every direction.

### Displayed room text no longer equals the stored room text
**Where:** `formatRoom()` / `roomOf()` vs `rawRoomOf()` in `src/web/static/app.js`.
**Owner:** standing constraint — read this before matching a room anywhere.
**What:** the yedion stores `"709 L"` — number then building letter. Nobody at
Braude says a room that way, so the interface reverses it for display: `roomOf()`
returns `"L 709"`, `"M 102 מע'"`, `"EF 506"`.

**Consequence, and the reason this entry exists:** rendered room text and stored
room text are now different strings. Anything that ever compares, searches,
filters, groups or de-duplicates a room **must use `rawRoomOf()`** — the stored
form — never the text on screen or `textContent` scraped from the DOM. Only
display goes through `roomOf()`.

The reversal is display-only and deliberate: it was measured, not assumed. Without
bidi isolation `"709 L"` renders visually as `L 709` by accident, which is the same
string the reformatting now produces on purpose — so isolation plus reformatting
are both required, and removing either one is caught by
`tests/test_rendered_copy_browser.py`.

### Middle-dot meta strings are still used on more than one line per card
**Where:** course cards in step 2, the lecturer panel header, the sticky bar.
**Owner:** unassigned — partially addressed in Phase 5.
**Why not finished:** Phase 5 removed the worst case (the year/term/semester line
said the same thing twice, one line apart) and trimmed the step state to a single
dot. The remaining ones — `3 נ"ז · 6 קבוצות · עודכן לפני 48 דקות` on a course
panel — each carry three genuinely different facts, and splitting them into rows
costs vertical space that Phase 8 will be fighting for on a phone. Worth revisiting
with the mobile layout rather than guessing at it now.

### `KIND_ORDER` and the term codes are displayed but are not copy
**Where:** `src/web/static/app.js`, the constants block.
**Owner:** nobody, by design.
**Why:** `"הרצאה"`, `"תרגול"`, `"מעבדה"`, `"פרויקט"`, `"שו״ת"`, `"אחר"` and
`"א"` / `"ב"` / `"קיץ"` arrive from the server and are used for comparison,
sorting and as keys into the attendance and pin maps. They are shown to the user,
so a reader will reasonably ask why they are not in `strings.json`. They cannot
be, until the server sends a stable id separate from the display label. Recorded
so the question is answered once.


### `test_neither_physics_track_is_marked` is load-sensitive, not deterministic
**Where:** `tests/test_recommended_defaults_browser.py`, via the `choose()` helper.
**Owner:** unassigned — a test-robustness question, not a product bug.
**What happened:** it failed once in a full-suite run on 2026-09-07 and has not
reproduced since. Chased properly before being written off:

| check | result |
|---|---|
| full suite, first run | 1 failed |
| that module alone | 20 passed |
| that module + `test_phase6_states_browser` | 28 passed |
| same two, with a suspected fixture bug deliberately restored | 28 passed |
| orphaned Playwright browsers | none — the 26 chromium processes were the user's own Chrome/Edge |
| full suite, second run | **665 passed, 0 failed** |

**Why it is believed to be timing:** `choose()` changes year and semester, which
triggers a course fetch, a solve and a re-render, then waits a fixed
`wait_for_timeout(1200)` before snapshotting. On a busy machine that margin can
lapse and `snap()` reads a half-updated page. The failing run took 8m32s against
a usual ~6m40s, which is consistent with contention.
**Two hypotheses that were tested and are wrong**, recorded so nobody re-tests
them: the `_age_catalog` helper in the Phase 6 tests mutating `shipped_catalog`'s
module cache (restoring the bug did not reproduce the failure), and orphaned
browser processes from killed background runs (there were none).
**What would fix it:** replace the fixed sleep with a wait on an observable
condition — the semester's course list having rendered — rather than on the
clock. That means editing an existing test file, which the standing rule forbids
without an explicit decision.

### Phase 10 — visual identity, and getting maintainer controls off the student's screen
**Where:** `src/web/static/style.css` (tokens), `src/web/templates/index.html`
(header, theme switch, `פרטים טכניים`), `src/web/static/app.js`.
**Owner:** Phase 10 — runs **after Phase 6 closes and before Phases 7-9**, which
wait until after the presentation. Logged 2026-09-07.
**What it covers:**
1. **A real visual identity.** The palette is unattractive and the screen is
   defaults rather than decisions. Two or three directions to be **proposed with
   a rationale and chosen by the owner** — not picked unilaterally. Whatever wins
   must pass the Phase 7 contrast checks in both themes.
2. **Logo to the left of the header.** "SlotWise" reads as English, so in RTL it
   belongs on the left. An icon joins the wordmark.
3. **Theme switch as icons** — sun / moon / monitor, each with an accessible
   label and a current state that is visible by more than colour.
4. **Maintainer controls move into `פרטים טכניים`.**
   `עבד מחדש את הנתונים השמורים` goes behind `?debug=1` with the reparse button.
   `עדכן נתונים מהידיעון` **stays but moves there too** — it now refreshes only
   the student's selected courses, which is the only way to check whether a
   specific course changed since the catalog was built. Real functionality, wrong
   prominence.
**Note this explicitly overrides** the brief's original "do not redesign the
visual identity from scratch", which was written when behaviour mattered more
than appearance. The brief has been amended.

### `עדכן נתונים מהידיעון` must disappear entirely if this is ever hosted
**Where:** the button, `/api/scrape/start`, `/api/scrape/status`.
**Owner:** whoever does the hosting work — see `HOSTING_NOTES.md` row 3.
**Why:** a hosted student has no scrape of their own, and the endpoint has no auth
or rate guard, so exposing it publicly makes the app an open relay to Braude's
server. Phase 10 moves the button into `פרטים טכניים`; hosting removes it.
**The functionality does not vanish, it changes owner:** the catalog rebuild
becomes a server cron running `build_catalog.py`, which is the same paced fetch
and the same six validation gates with a different trigger.

### No course can be marked "required for my degree" — Phase 6 follow-up
**Where:** course selection in step 2; consumed by `scheduler.day_relaxations()`
and the "מה יאפשר N ימים" list in step 3.
**Owner:** Phase 6 follow-up, deliberately deferred so Phase 6 could close.
**What is missing:** there is no way for a student to mark a course as
non-negotiable. Checked before building the day-target relaxations: the only
`required` field in the codebase (`src/web/api.py:1086`) is per-component
*attendance*, unrelated. The closest thing is `tied_with`, and that is the
yedion's rule that certain courses form one package — not the student's choice.
**Why it matters:** the day-target list will cheerfully suggest dropping a course
someone must pass this semester to graduate, ranked first if it happens to be
cheap in credits. The ordering is honest about credit cost and says nothing about
necessity, because it cannot.
**Mitigation shipped in the meantime:** the list carries a one-line caveat —
`app.days.relaxNoRequiredInfo` — stating that the system does not know which
courses are required for the degree and checked study days only. That makes the
gap visible instead of letting the ranking sound more authoritative than it is.
**Where it should live:** next to the course chips in step 2, as a per-course
toggle, so `day_relaxations()` can exclude marked courses from the candidate
units entirely rather than ranking them low. Note that a required course inside a
tied package makes the whole package non-droppable.

### `runtime.reparseBusy` is dead state that is permanently `false`
**Where:** `src/web/static/app.js` — initialised at the `runtime` block, read at
four sites (`anyBusy()`, the scrape summary line, the header phase line, and the
disable check that survived).
**Owner:** unassigned — a tidy-up, not a bug.
**What:** the reparse button was removed on 2026-09-07 and `startReparse()` with
it, so nothing ever sets the flag true. Four branches now cannot fire.
**Why not removed:** the reads live inside the busy/phase logic that the *scrape*
path still uses. Deleting them means editing shared state machinery for no
user-visible gain, and this change had already grown large. Worth doing next time
that code is opened for another reason — dead state that is always false is
exactly what misleads a reader who assumes it can be true.

### `/api/reparse` reads `data/raw`, which a fresh clone does not have
**Where:** `src/web/api.py` (`/api/reparse`), `reparse.py`, and
`tests/test_web.py` §6ב which covers the endpoint.
**Owner:** a decision waiting, not a loose end.
**What:** reparse rebuilds the database from the raw HTML in `data/raw/`. That
directory is gitignored, so on a fresh clone the endpoint operates on an empty
directory and always will. The button is gone; the endpoint remains and is
tested.
**The three options, for when this is decided:**
1. **Make it a maintainer CLI only.** `reparse.py` already is one, and
   `build_catalog.py` does the same job better — it reparses *and* validates.
   Removing the HTTP endpoint means editing `tests/test_web.py`, which the
   standing rule forbids, so it needs an explicit decision to lift that.
2. **Repoint it at the shipped catalog.** "Reparse" becomes "reload
   `data/catalog.jsonl`", which is meaningful on any machine and costs no
   network. Closest to what a user would expect the words to mean.
3. **Leave it.** It is harmless: it returns an honest "nothing to reparse" on a
   clone. The cost is an endpoint whose name promises something it cannot do.
**Recommendation:** option 2 when Phase 9 or hosting work touches this area.
Option 1 is cleaner but pays a test-file edit for an endpoint nobody calls.

### The lecturer field in the yedion sometimes holds a note, not a name
**Where:** `data/db/sections.json` → `groups[].lecturer`, now rendered in full on
every grid block and on the printed sheet.
**Owner:** unassigned — a parser question, not a display one.
**What:** 6 of 291 distinct lecturer values are not names: `טרם נקבע`,
`מיועד לחוזרים`, `הקורס מלא`, `שפת הוראה של הקורס : עברית`, plus two untitled
names. The block now shows the value verbatim, so
`שפת הוראה של הקורס : עברית` wraps across two lines of a timetable block as
though it were a person.
**Got slightly worse, deliberately:** an earlier version abbreviated to title +
surname, which happened to cap junk at two words. Showing the full name is the
right call for the 285 real names — abbreviating deletes exactly what separates
two lecturers with the same surname — and it removes that accidental cap for the
6 bad ones. The fix belongs in `src/parser.py`, which should not be putting a
group note in the lecturer field at all, rather than in a display-layer guess
about which strings are people.

---

## Closed

### The fit score rendered backwards in the comparison table — closed 2026-09-08
`app.schedule.fitValue` was `"{score} / 100"`. That is two number runs with a
bidi-neutral separator between them, so in an RTL paragraph the neutrals resolve
to right-to-left and the runs are ordered right-to-left: the cell drew
**`100 / 87`**. The score panel escaped it because `app.js` gives that element
`class="fit-value ltr"`; the comparison table built the same string into a plain
`<td>` and inherited the page direction. The table is the brief's
"highest-value addition in the whole brief", and the number it exists to compare
was the one reversed.

**Fixed by removing the cause, not the symptom.** The fit is now a single
percentage — `87%`. `%` is an ET, and rule W5 of the bidi algorithm folds an ET
adjacent to an EN into the same run, so one number cannot split into two runs
and cannot reorder. One string in `strings.json`, one formatter (`fmtFit()` in
`app.js`), both render sites through it. The caveat in `fitTitle` is unchanged
apart from its unit — a percentage reads more absolute than a score does, so
"relative to the five shown" matters more now, not less.

**The test that matters is `test_the_fit_is_not_visually_reversed`**, and it is
worth understanding why. `textContent` returns the *logical* order, which is
`87 / 100` whether or not the glyphs are reversed — so no text assertion could
ever have caught this, and none did. The test measures the painted rectangle of
the first character against the last one via a `Range`. Mutation-tested: with
`"{score} / 100"` put back, it reports the first character 20.4px to the *right*
of the last and fails. The same test against `.fit-value` passes even with the
bug restored, which is the proof that `.ltr` was masking it there.

**Habit worth keeping:** a composite `number separator number` string is a bidi
hazard in any RTL interface. Prefer a form that cannot be reordered over a form
that has to be wrapped, because the wrapper is what someone forgets.

### The palette lived in four places — closed 2026-09-08
Not three, as first reported. `:root` (light), two hand-duplicated dark blocks,
`@media print` re-declaring its own, and `src/render.py` holding a second copy of
the ten course triples under **different names** (`--cN-bg`, not `--course-N`) —
so a find-and-replace on `--course-` missed the standalone export entirely.

**Now:** every colour is written once. `--dark-*` and `--print-*` hold the values
in `:root`; the two dark blocks and the print block contain only `var()` mappings
and no hex at all. `render.py` parses the ramp out of `style.css` at import and
raises if a token is missing, rather than carrying its own copy.

**The structural move that did most of the work:** both dark blocks are now
wrapped in `@media screen`. Dark is a property of a screen, not of paper, so the
dark palette can no longer reach the print sheet by any path — which means the
print block does not need to override the ten course colours at all.

**It was hiding a real bug, shipped.** `:root[data-theme="dark"]` has specificity
(0,2,0); the print block's `:root` has (0,1,0). The print block therefore lost.
Printing in dark mode kept `--ink: #e6eaf1` while `body` was forced to white —
**near-white text on white paper, 1.16:1.** It applied to an explicit dark choice
*and* to "system" on a dark OS, so the only users who printed correctly were those
on a light theme. For a schedule app used at night during registration week, that
is most of the wrong half. Caught by specificity arithmetic, reproduced in a
browser, fixed by the `@media screen` wrapping.

**Guarded by `tests/test_theme_tokens.py`** (13 tests): the two dark blocks are
compared declaration-by-declaration, both are asserted to contain no hex, every
themed token is asserted to be mapped in both, each source token is asserted to be
defined exactly once, `render.py`'s ramp is asserted equal to the stylesheet's, and
printing is asserted black-on-white in all four theme states. Both guards were
mutation-tested — re-forking one hex and removing the `@media screen` wrapper each
produced a failure.

**Verified behaviour-preserving:** every resolved custom property and the computed
styles of fifteen painted elements were snapshotted in five modes before and after.
Zero differences, other than the print-in-dark fix, which is the point.

### Twelve opacity multipliers on real text — closed 2026-09-08
`opacity` runs *after* the colour is chosen, so it blends text with whatever is
behind it and no token value rescues it. Measured against the current light
palette, on `--panel`:

| | before | after |
|---|---|---|
| comparison table, identical row | 3.17 : 1 | 7.23 : 1 |
| lecturer row, dead end | 2.42 : 1 | 7.23 : 1 |
| unavailable course | 3.66 : 1 | 7.23 : 1 |
| room code in the detail panel | 4.26 : 1 | 7.23 : 1 |
| lecturer line inside a grid block | 6.84 : 1 | 11.28 : 1 |

All twelve now use `color: var(--muted)` at full opacity — the same visual
recession, without the cost. The `@media print` rule that set
`opacity: 1 !important` on three block lines was deleted with them: its entire job
was to undo a screen decision that no longer exists.

What deliberately stayed, each with its reason in `ALLOWED` in
`tests/test_no_opacity_on_text.py`: `.btn:disabled`, `.step.is-locked`,
`.banner-close`, `.pin-btn` (WCAG 1.4.3 exempts inactive components — but see the
open entry, its *enabled* state is not exempt), `.legend-swatch--dead` (a colour
chip, not text), and the reduced-motion busy bar (an animation).

### The printed sheet — closed
The print stylesheet now describes what **is** printed instead of listing what
is not: `body > *:not(.steps)`, then `.steps > *:not(#step-schedule)`, then
`#step-schedule > .step-body > *:not(#grid-scroll):not(#print-head)`. A denylist
had leaked the progress row and the build button onto printed page 1 twice; a
list of what survives cannot forget a new element, and a browser test asserts the
painted set rather than a handful of named ids.

The sheet is the grid plus one header line — schedule name and date. Everything
else (score, tabs, facts tiles, penalty breakdown, course chips, legend, overlap
warning) is decision support; once the decision is made, you print the schedule,
not the reasoning.

One page, not two. Repeating the day headers across a page break was the original
ask and it has no CSS answer: `<thead>` repeats in a table, the timetable is a
CSS grid, and `position: fixed` is not repainted on later pages in Chrome. So the
break is avoided rather than managed — `fitGridToPage()` steps `--slot-h` down
from 17px until the body fits 210mm, flooring at 12px. Measured on the semester-5
default: 13px, one page, and 2 of 13 blocks give up their room and time line while
every block keeps its name and kind. Below 12px it stops shrinking and lets the
sheet paginate, because a single page too small to read is not an improvement on
two readable ones. `@page` margin is 0 with the margin moved to body padding —
that is also what suppresses the browser's own URL/date footer, which no CSS can
switch off directly.


### Duration formatting in the score panel — closed in Phase 2
Every duration now goes through `fmtDuration()`, which renders `3:00 שעות` —
one format, with a unit, in the facts panel, the schedule tabs, the sticky bar
and the overlap heading. `fmtSpan()` survives only as its internal `H:MM` half.
Chose `H:MM שעות` over `שעתיים וחצי` because the same helper has to render
`0:45` and `12:30`, and a worded form needs a special case per magnitude.

