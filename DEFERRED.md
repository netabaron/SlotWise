# Deferred — things a phase found but did not fix

Anything noticed during the UI overhaul that belongs to a later phase, or to no
phase at all, gets written here the moment it is noticed. The point is that none
of it is rediscovered in Phase 9 as a surprise.

Format: what it is · where · which phase should own it · why it was not done now.

---

## Open

### On a tall grid the lesson details open out of view
**Where:** `#meeting-detail` in `src/web/templates/index.html` (inside `.grid-tools`,
under the timetable) and `openMeetingDetail()` in `src/web/static/app.js`.
**Owner:** Phase 7 (wide layout).
**What:** since Phase 6 (2026-10-01) the details panel sits next to the legend, under
the timetable (DESIGN.md, "Results page", 8). In today's single-column layout the
grid can be taller than the viewport, so clicking a block near the top fills a panel
that is below the fold. The block gets its course-colour outline and the panel's
content is announced (`aria-live`), but nothing on screen shows where the details went.
**Why not now:** Phase 7 puts the timetable in a sticky column, at most one viewport
tall, with the legend and the details inside it (DESIGN.md, "Layout"). That keeps the
panel in view on wide screens without any scrolling logic. Scrolling the page to the
panel on every click was considered and not done: it moves the page away from the
block the student just clicked, and the sticky column makes it unnecessary. On phones
the panel is already a bottom sheet over the page, so this applies to the wide range.

### Tests that start a server read the real `data/db` — four fail on a store written by `webapp.py`
**Where:** `tests/test_hosted_missing_groups.py` (4 of its 7 tests); more generally,
any test that calls `create_app()` without pointing `SLOTWISE_DB_ROOT` elsewhere.
**Owner:** unassigned. The file is protected (`SPEC_WEB.md:230`: do not modify existing
tests), so this is recorded, not changed.
**What:** `create_app()` reads `data/db` when it exists. `conftest.py` freezes the
catalog (`SLOTWISE_CATALOG_DIR` = `tests/fixtures/catalog`) but not the store, so a
local store silently becomes part of the test's input. Running `python webapp.py`
in local mode writes that store: it copies the shipped catalog into
`data/db/sections.json` and `details.json`.
**What fails:** with such a store, `/api/courses` returns groups for 201009 and
201015 in semester א, so `not_offered` comes back empty and these four fail:
`test_the_blanket_skip_reason_does_not_erase_the_real_one`,
`test_a_course_that_does_have_groups_is_untouched`,
`test_step_four_is_not_locked_on_courses_that_will_never_have_groups`,
`test_the_explanation_is_plain_and_mentions_no_fetching`.
**Measured 2026-09-30:**

| store | result |
|---|---|
| untouched HEAD (`116c365`), store written by `webapp.py` | 4 failed, 3 passed |
| untouched HEAD, no `data/db` | 7 passed |
| fixture store (`scripts/seed_dev_data.py --fixture`, what CI runs) | all 7 pass in the full suite |

The store here was written by a throwaway `webapp.py` run during the Phase 5 work
(`updated_at` 2026-09-30T18:35Z). Any local run of the app does the same, so a
developer who has used the app locally can see these four fail on unchanged code.
**Same trap, caught in Phase 5:** two of the new tests in
`tests/test_results_page_browser.py` first passed locally only because the test
server read the real store. One assumed schedule 1 is always labelled "ההתאמה הגבוהה
ביותר"; with the frozen catalog all five schedules tie. The other assumed 11069 lands
in a group without meetings; in the frozen catalog every semester-א group of 11069
has a meeting. Both now derive their expectations from what the server returned, and
the whole file passes with the fixture store and with no `data/db` at all.
**How to run the suite as CI does, locally:** move `data/db` aside,
`python scripts/seed_dev_data.py --fixture`, run the suite, then put the store back.
**A fix, when someone owns this:** have `conftest.py` point `SLOTWISE_DB_ROOT` at a
seeded temporary store, as it already does for the catalog. Some tests copy
`data/db` by path (`test_multifaculty.py::_copy_db`), so they would need the same.

### Grid blocks ship with lecturer names sliced in half — **closed 2026-09-30 (redesign Phase 5)**
**Closed by:** removing the cause rather than re-timing it. `fitBlocks()` and its
drop ladder are gone. Every block shows all three lines (name; type · time;
lecturer · room), and the hour height is derived from the content by
`sizeGrid()`, which runs **after** layout: in a `requestAnimationFrame` after each
render, from a `ResizeObserver` on both grid containers, when web fonts finish
loading (Heebo is wider than the fallback — the second half of the race below),
and synchronously on the print media change. Measured on the semester-5 default:
64px per hour at 1440 and at 1200, 0 blocks overflowing, 0 lines hidden, 0 lines
clipped; at 390px, 112px per hour where the old code sliced 4 lines in 2 blocks.
`test_overlap_halves_stay_readable_at_half_width` passes, and
`tests/test_results_page_browser.py` pins the rest. The history below is kept.

**Where (historical):** `fitBlocks()` in `src/web/static/app.js:6855`, called from `app.js:6071`.
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
`test_neither_physics_track_is_recommended` further down this file: both are
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

### The printed sheet is now at the bottom of its ladder — **superseded 2026-09-30 (redesign Phase 5)**
**Superseded by:** the print fit is driven by font size, not slot height and dropped
lines. The sheet is portrait A4; `fitGridToPage()` steps the print-only block font
down from 13px in 0.5px steps to a 10px floor, re-measuring the hour height from
the content at each step, and prints at 13px on two pages if even 10px does not
fit (DESIGN.md, "Results page", Print). Semester-5 default: one page at 10.5px.
**Still true, and worth knowing:** a denser semester than the default may reach the
10px floor or the two-page fallback; that has been measured on one schedule only.
Below a 13px slot the hour labels in the time column are clipped by the next cell's
background (seen in a landscape trial at 10px); portrait semester 5 prints at 17px.

**Where (historical):** `fitGridToPage()` in `src/web/static/app.js:6892`, `SLOT_H_PRINT_MIN = 12`.
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


### `test_neither_physics_track_is_recommended` is load-sensitive, not deterministic
**Where:** `tests/test_recommended_defaults_browser.py`, via the `choose()` helper.
**Renamed 2026-09-09** from `..._is_marked` when the recommendation stopped
arriving ticked (`69cdabb`). The rename does not touch the timing problem below,
which is about `choose()` and applies to every test that goes through it.
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

### `test_restoring_the_recommended_list_brings_it_back` passes for the wrong reason
**Where:** `tests/test_recommended_defaults_browser.py`.
**Owner:** unassigned — test honesty, not a product bug.
**What:** it calls `uncheck(page, "61759")`, which clicks the checkbox. Since
`dc112c3` nothing arrives ticked, so that click now *ticks* 61759 rather than
unticking it. The test still passes — clicking `סמן את כל המומלצים` afterwards
produces the asserted end state either way — but it no longer exercises the path
its name describes, and it would keep passing if restore stopped clearing
`autoDropped`.
**Why it was left:** the rule for the 2026-09-09 test work was explicit — do not
touch a test in that file that still passes. The untick-and-restore path itself is
covered by `test_unchecking_a_recommended_course_sticks_across_a_reload`, which
ticks first and does genuinely untick.
**What would fix it:** tick before unticking, exactly as the five mechanical
repairs in `5c10640` do.

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

---

### A thin local course entry masks a fuller shipped one — the merge is per course, not per group
**Where:** `Store._load_sections_db` in `src/store.py:1080`, the `merged.update(courses)`
line that is the whole merge.
**Owner:** unassigned. Papered over in the data 2026-09-10; the mechanism is untouched.
**What:** the shipped catalog is the base layer and `data/db/sections.json` overrides it
**a whole course at a time**. So a local entry that carries *fewer* groups than the
shipped record does not merge with it — it replaces it, and the groups only the catalog
has disappear. Nothing warns, because the course still resolves and still has groups.
**How it surfaced:** `61776` (פיתוח יישומי אינטרנט) and `62028` (נושאים מתקדמים ב-AI)
came back `kind: "semester_mismatch"` — not offered — for a student on semester א.
The shipped catalog had 3 semester-א groups with meetings for each; the local entry
held only the semester-ב groups, which have no meetings. The local entry won, so at
semester א both courses had nothing left to schedule.
**Scope, measured rather than guessed:** swept all 572 courses through the read path at
semester א, ב and unfiltered. Exactly **2 of 572** were affected, and both are outside
the default six. No course anywhere returns zero groups. Local was never *ahead* of
shipped on any course — 570 identical, 2 behind, 0 better.
**What was done instead:** the two stale entries were deleted from `data/db/sections.json`
(572 → 570 stored; still 572 visible, the catalog supplies the rest). Both now return
3 groups / 3 meetings from `source: "shipped"`. Verified against the running server on
port 5000, not a throwaway one.
**Why the mechanism was not fixed:** making the merge group-aware changes read semantics
for all 572 courses, and this was found the night before the presentation. The data fix
is exact and reversible; the code fix is the right one and should be done when this area
is next opened. Note the merge is also why `_store_for(semester)` is currently close to a
no-op — a local entry that covers every code is never semester-filtered on read, only the
shipped layer is.
**Not to be confused with** "sections.json was emptied by a running server". It was not:
the file was 1.5 MB with 572 courses and 1,445 groups throughout. The
`Schedule_Builder_backup_20260906` copy is **smaller** — 433 courses, 1,169 groups, and
one `הקורס מלא` lecturer value that `ba8a34e` had just fixed — so restoring it would have
deleted 139 courses and reintroduced the pollution.

---

### The progress chips cannot tell "required and missing" from "left alone on purpose"
**Where:** `sectionState()` / `renderProgress()` in `src/web/static/app.js`, and
`app.progress.untouched` / `app.steps.stateDefault` in `src/strings.json`.
**Owner:** Phase 5 item 1, which already asks for a stateful mark.
**What:** the chips carry three states — untouched / chosen / conflict. Since the
recommendation stopped arriving pre-ticked, "untouched" covers two opposite things:
**מסלול** and **קורסים** are required and block a build, while **ימים** and
**מרצים** are genuinely fine left alone. One label serves both.
**What was done now:** the label said `— בברירת מחדל`, which claimed a default was
in force. For identity and courses there is no default any more, so it was a false
statement; it now reads `— לא נבחר`, which is true of all four but says nothing
about which ones matter. The hint line beneath the chips carries that instead, and
it **names the two**: `כדי לבנות מערכת: מסלול, שנה וסמסטר · קורסים`. The two names
are quoted from `ui.steps.yearTitle` and `ui.steps.coursesTitle` character for
character, which is what lets a student match the line to a chip — change either
title and this line has to change with it.
**Known limit of that line:** `hintDefault` renders whenever there is no conflict,
so it stays on screen after a schedule has been built, where it reads as a legend
rather than an instruction. The version that names only what is still missing, and
goes quiet once both are satisfied, was written up and deliberately not built the
night before the presentation — `sectionState()` already computes everything it
would need.
**Why not fixed properly:** a fourth state is a design decision with a colour and a
non-colour marker attached (Phase 7 rule 5), found the night before the
presentation. The hint line carries the information correctly in the meantime.
**Also noticed:** `app.header.refresh` is referenced by `T()` in `app.js` but does
not exist in `strings.json` — pre-existing, and it survives only because `T()` falls
back. Not touched here.

---

### Two alignment faults in the step-4 group tables — closed 2026-09-10
**Where:** `src/web/static/style.css` — the `direction: ltr` group at the top, and
`.th-pin, .cell-pin`.
**What was reported:** the `קבוצה` column was left-aligned while every other column,
including its own `<th>`, was right-aligned.
**Cause:** `.cell-group` is a `<td>`, and it sat in the list of tokens forced to
`direction: ltr`. The table aligns with the logical `text-align: start`, so an LTR
cell resolved `start` to **left** while the RTL cells around it resolved it to
**right**. The header was unaffected because it has no such class — which is why the
column and its own title disagreed.
**The rule it broke:** the isolation belongs on the **token**, never on the cell.
`.cell-time` already does it correctly — the day cell stays RTL and only the time
span is isolated, with a comment saying so — and `.gid` inside `.cell-group` already
carried its own `direction: ltr; unicode-bidi: isolate`. The cell-level rule was
redundant for the group id and wrong for everything else in the cell.
**Second effect, not in the report:** the same rule made `group.note` and the
`status_note` tag (`הקורס מלא`) render LTR. Both are Hebrew. Fixed by the same
deletion.
**Found while checking the rest of the table:** `.th-pin, .cell-pin` declares
`text-align: center`, but `.lect-table td` is `(0,1,1)` against its `(0,1,0)`, so the
centring never applied and the pin column was `start` like the others. Invisible
today because the column is content-width around one emoji; it would have surfaced
as soon as Phase 7 replaces that emoji with a wider SVG button. Fixed by scoping the
selector to `.lect-table`.
**Verified** by measuring, in a real browser with step 4 expanded, the distance from
each cell's right content edge to its text: 0px for `סוג`, `מרצה`, `יום ושעה`, `חדר`;
1.5px for `קבוצה`, matching its own header exactly (the side-bearing of the isolated
digit run); `נעיצה` computing `center`. `.gid` still `ltr`, the notes now `rtl`.

---

### `feasible_count` counts intentional overlaps too — the last display of it is gone, 2026-09-10
**Where:** `_count_and_min_days` in `src/web/api.py`, over
`scheduler.enumerate_selections`. Was displayed by `ui.fields.factFeasible`
(the אריח) and `app.tech.found` (פרטים טכניים); both removed.
**What it actually counts:** every complete selection the enumerator yields — one
group per (course, component kind), pruned on *hard* conflicts and `linked_to`.
With attendance required everywhere that is the count of conflict-free schedules.
**But `allow_soft_conflicts` defaults to `True`**, so the moment a student waives
attendance on one component, selections carrying a deliberate overlap are legal to
the enumerator and are counted. They are explicitly **not** `Selection.is_feasible()`
— `enumerate_selections`'s own docstring says so — and a student would not call them
options.
**Measured on the default six, semester א, target 4:**

| attendance | `feasible_count` |
|---|---|
| required everywhere (default) | **152** |
| one lecture waived | 960 |
| two lectures waived | 1368 |
| every lecture waived | 1368 |
| every lecture *and* tutorial waived | 3600 |

So the same six courses report anywhere from 152 to 3600 depending on a checkbox
that has nothing to do with how many timetables exist. A bare number under the label
`מערכות אפשריות` reads as "I have N options", and past 152 that is false.
**Correction to what this file used to imply:** an earlier session reported the
number as "the legal count, 152, not the search space" and kept the tile on that
basis. That was measured only in the default all-attendance-required case and was
wrong as a general statement. The reporter was right.
**Also removed with it:** `app.schedule.noteFound`, `noteTruncated` and `noteElapsed`
— three strings Phase 1 stopped rendering but left in `strings.json`, including
`(חישוב: {ms} מ״ש)`, the millisecond timing the brief names by hand.
**Left alone deliberately:** `app.relax.applied` (`{what} בוטל. {n} מערכות נמצאו.`)
reports the relaxation engine's own per-suggestion measured count, not
`feasible_count`. It is the one number in the app that means exactly what it says.
**If a count is ever wanted again:** it has to be the count of selections where
`is_feasible()` holds, computed separately, and labelled so the attendance waiver is
visible in the wording. Do not re-point a tile at `feasible_count`.

---

### The full-day grid view is gone — `הצג את כל השעות` removed 2026-09-10
**Where:** was `#chk-all-hours` in `index.html`, `state.allHours`, its listener, and
the `if (state.allHours) return { start: fullStart, end: fullEnd };` branch in
`gridBounds()` (`src/web/static/app.js`). Strings `app.grid.showAllHours` and
`showAllHoursTitle` deleted with it.
**Why it went:** the control did nothing on the reporter's schedules, and a control
that does nothing is worse than no control.
**It was not broken — this was checked before deleting, and the distinction matters.**
The crop works. Measured through `/api/solve` on real data, cropped vs full range:

| selection | classes run | cropped to | effect |
|---|---|---|---|
| 11069 alone | 10:30–12:20 | 10:00–13:00 | crops 9h00 |
| 61753 alone | 08:30–12:20 | 08:00–13:00 | crops 7h00 |
| 61832 alone | 09:30–15:50 | 09:00–16:30 | crops 4h30 |
| 61753 + 61832 | 08:30–15:50 | 08:00–16:30 | crops 3h30 |
| **the default six** | **08:30–19:50** | **08:00–20:00** | **nothing to crop** |

End to end in a browser, grid height with the toggle off vs on: **514px vs 1130px**
on a narrow schedule, **1130px vs 1130px** on the default six. So the wiring was
intact all the way from the checkbox to the render; the six simply fill the
08:00–20:00 window, and cropping a full window is a no-op. The reporter saw a dead
control because their timetable spans the day, not because the feature was dead.
**What this costs:** there is no longer any way to see the empty hours around a
short day. That was the toggle's whole purpose, and for a student whose classes run
10:30–12:20 the grid is now four hours tall with no way to widen it. Nobody asked
for that view, but nobody had a short day either — the default six were the only
data it was ever judged on.
**If it comes back:** the branch was one line, and `gridBounds()` still computes
`fullStart`/`fullEnd` for the clamp, so restoring it is re-adding the checkbox, the
state field, and `if (state.allHours) return { start: fullStart, end: fullEnd };`.
Do not restore it as a checkbox that looks inert on a full timetable — either label
it with what it would do (`הצג 08:00–20:00`), or hide it when the crop would change
nothing, which is the honest version of the same control.
**The clamp stays either way.** `Math.max(fullStart, …)` / `Math.min(fullEnd, …)` in
`gridBounds()` stopped a day ending 19:50 from padding out to 20:30. With the toggle
present that produced a cropped grid *taller* than the full one; without it the
clamp merely keeps the grid inside the day window, and
`test_the_grid_never_draws_past_the_day_window` now pins that directly instead of by
comparing the two modes.
**Test churn:** `test_grid_crops_and_toggle_only_ever_grows` drove the checkbox and
could not survive. Replaced in `tests/test_rendered_copy_browser.py` (a file this
repo allows editing) by the test above plus
`test_the_all_hours_toggle_is_gone`, which pins the removal so it is not
reintroduced by accident.

---

### Ten fields in the `/api/bootstrap` `db` payload have no reader — settle in one pass
**Where:** `_db_snapshot()` in `src/web/api.py`.
**Owner:** one deliberate pass, **after the presentation**. Deleting fields from a
public surface during the week it is being demonstrated is not a trade worth making
for tidiness.
**What:** of the fifteen keys `_db_snapshot()` returns, ten are read by nothing —
not `app.js`, not the tests, not `refresh.py`, not the CLI:

| no reader | still read | read by |
|---|---|---|
| `codes`, `tracked`, `stale`, `failed`, `any_stale`, `age_hours`, `age_text`, `newest`, `oldest`, `max_age_hours` | `count` | `app.js` (6 sites, incl. the `bootDb` alias) |
| | `text` | `app.js` — the header's build-line fallback |
| | `origin` | `app.js` banners, one test |
| | `catalog_built_at` | `app.js` header, one test |
| | `courses` | `app.js` — the per-course metas `selectedFreshness()` runs on |

**How it was counted:** every key matched against `app.js` with comments stripped
(a field named in prose is not a read — `any_stale` appears only in the comment
warning people off it), plus `tests/*.py`, `refresh.py` and `src/cli.py`. The only
alias of the payload, `bootDb` at `app.js:2596`, reads `count` and nothing else.
**Three of the ten already carry a warning comment.** `any_stale`, `age_text` and
`newest` are the whole-database freshness fields the header used to read; the
comment above them records the bug that removed them and says not to wire the
header back. The other seven have no note.
**Why they are not all dead weight.** `stale` and `failed` are genuine per-run
information the interface simply never used, and `oldest`/`newest` are the only
place the database's span is exposed at all. The pass should decide per field
whether it is unused because nothing needs it or unused because the thing that
needed it was never built — those want opposite outcomes.
**Related:** the header stopped reading the whole-database fields on 2026-09-13;
see the commit that added `selectedFreshness()`. That change is what left most of
this block unreferenced, so the two belong together in whoever's head does the pass.

### Six Applied Maths courses are in the curriculum but not in the yedion — nothing here can fix it

**Where:** `data/curricula/math-winter.json`, `math-spring.json`. Measured
2026-09-22 against `data/catalog/catalog.jsonl` (571 courses, built 2026-09-21).

| code | name | where it is |
|---|---|---|
| `201155` | חשיבה מתמטית | curriculum only |
| `51900` | תורת ההסתברות מש | curriculum only |
| `201174` | אלגברה לינארית 2 | curriculum only |
| `201176` | מבוא לאנליזה | curriculum only |
| `201029` | אנליזה קומפלקסית | curriculum only |
| `201178` | מבוא לאופטימיזציה | curriculum only |

**Not a scraper bug, and not a `build_catalog.py` bug.** `build_catalog.py`
fetches exactly the codes in `data/db/catalog.json` — the yedion's own index of
what is taught this year, pulled fresh every night by the
`refresh.py --catalog-only` step in `.github/workflows/build-catalog.yml`. That
index holds 571 codes and the catalog holds the same 571: coverage is 100%, and
**none of the six is in the index**, under their codes or under their names. The
yedion does not publish them for תשפ"ז, so no change on this side can make them
appear. They will arrive on their own the first night the college lists them.

**What the student sees, and why that is now correct:** step 2 tags them
`לא נפתח בסמסטר`, and they are not auto-recommended. That is the honest answer.

**Separately, and not the same thing:** `201009` (אנליזה נומרית מש) and `201015`
(אלגברה מודרנית) **are** in the catalog. The curriculum places them in a
semester-א slot, but the yedion gives each of them one הרצאה and one תרגול in
semester **ב**, both with `אין מועד קבוע` — no meeting rows at all, and
`מרצה הקורס: טרם נקבע`. The semester letter is not guessed: it comes from the
`data-arguments` of the "פרטים נוספים" button (`semester_from_details_args`,
`parser.py:187`), where `-N2` means ב. So for semester א they correctly build as
`no_groups`. How that is *presented* was the bug, and it was fixed on
2026-09-22 — see `tests/test_hosted_missing_groups.py`.

---

### Fixed sleeps are most of the suite's runtime — **after the redesign; approved as a note only**
**Where:** 207 `wait_for_timeout` calls in 20 browser test files, mostly in
shared helpers (`_ready`, `_fresh`, `_open`, `_with_schedule`, `choose`, …).
**Owner:** after the UI redesign (`docs/DESIGN.md` phases). Decided 2026-09-24:
parallel runs (pytest-xdist) were done first; this was kept as a note, not started.
**Measured 2026-09-24:** a serial run takes 21:21, and the browser tests' fixed
waits add up to ~19.5 min of it. The biggest files: `test_rendered_copy_browser`
291 s, `test_lecturers_step` 133 s, `test_settings_screen` 128 s,
`test_recommended_defaults_browser` 112 s. The common helper "goto, wait 3500,
pick identity, wait 2500, recommended, wait 6000" alone costs ~12 s per test.
**What would fix it:** a small app change that exposes when the page has settled,
e.g. a `data-solve` attribute on `<html>` reading `pending` → `busy` → `idle`,
set in `scheduleSolve`/`doSolve`. `#busy-bar` alone is not enough: it is hidden
during the 150 ms debounce, so a test would read "done" too early. The helpers
would then wait on that condition instead of the clock.
**Why it matters beyond speed:** the fixed waits are timing assumptions. This is
the same fix the `test_neither_physics_track_is_recommended` entry above asks
for, and it would remove that class of load-sensitive failures.
**Estimate, not measured:** serial perhaps 5–8 min, and 2–3 min combined with
`-n`. Measure how long a solve takes on the frozen catalog before promising it.
**Why not now:** it edits many protected test files, which needs an explicit
decision per the standing rule, and it was deferred until after the redesign.

### A timing-sensitive lecturers test fails intermittently under 3 workers — **noted 2026-09-27, not fixed**
**Where:** `tests/test_lecturers_step.py::test_click_ranks_the_next_and_click_again_renumbers`.
**Seen:** once in four full runs on 2026-09-27 (`-n 3 --dist loadfile`):
`AssertionError: {'lect': …, 'rank': '1', 'filled': True, 'pop': False, …}`.
The rank was assigned correctly; only the `pop` check failed. Run alone it passed
twice, and it passed in the next full run.
**Why:** the check reads the rank "pop" (250 ms scale to 1.2 and back,
`docs/DESIGN.md` → Lecturers) after a fixed wait. Under three workers the
animation can finish, or not yet start, outside that window. The code under test
was not changed in that session (the courses-step cleanup).
**What would fix it:** assert the animation was triggered (a class or an
`animationstart` event) instead of sampling its state at a fixed time, or the
settled-page signal the entry above proposes.
**Why not now:** the user asked for it to be recorded, not fixed. It is a
protected test file.

## Closed

### Local `sections.json` shadows the shipped catalog with an older build's stamp — closed 2026-09-20
**Where:** `Store._load_sections_db` in `src/store.py` (`merged.update(courses)`), the
records in `data/db/sections.json` whose `meta.source_url` is `shipped-catalog`.
**Owner:** unassigned. Found 2026-09-13 while scoping the header freshness line.
**What:** the local database holds **135 entries that came from the shipped catalog**,
not from a fetch. **133 of them carry `fetched_at: 2026-09-07T14:07:54Z`** — the stamp
of the *previous* catalog build. The current catalog was built `2026-09-09T22:35:44Z`.
Because local wins the merge whole-course-at-a-time, those 133 shadow the current
shipped layer, and `_origin_of` still labels them `shipped`.
**So the header's own build date is wrong about most of the data it describes.**
`הקטלוג נבנה לפני 3 ימים` reads `catalog.meta.json`, which is true of the *file*; the
records that line is describing are from a build two days older. A date that is wrong
about its own data is the same class of problem as the fetch line that reported the
stalest record in the database as though it were the last update — which is what was
just fixed in `renderHeader()`.
**Content is fine, the stamp is not.** Checked 2026-09-10: zero polluted lecturer
values across the whole database, because `_LEGACY_STATUS_SUFFIXES` cleans the two
known suffixes at read time. So this is not the Sep 7 lecturer bug surviving in the
shadow copies — it is only the provenance stamp that is stale.
**How they got there:** not established. A refresh or reparse run that persisted the
merged view rather than only the fetched half would do it, since `save_course` writes
whatever it is handed. Worth confirming before fixing, because the fix depends on
which path wrote them.
**Why it was not fixed now:** deleting the 133 shadow entries would let the current
catalog show through and is the obvious repair — it is the same shape as the
`61776`/`62028` fix on 2026-09-10 — but it edits the student's database on a hunch
about how the rows appeared. That was fine for two courses with a measured symptom;
it is not fine for 133 without knowing the writer. Establish the path first.
**What it is not costing today:** nothing visible. The merge is per course, the
content matches, and no line in the interface reads `fetched_at` off these records
now that the header is scoped to the student's selection — and a *selected*
catalog-only course puts the header into the `mixed`/`catalog` wording, which talks
about the build date rather than claiming a fetch.

**Closed 2026-09-20 — by changing who wins the merge, not by deleting the rows.**
This entry was held because the obvious repair edits the student's database on a
hunch about which code path wrote those rows, and 133 rows is too many to do that
to without knowing. That question turned out not to need an answer: the fix was a
line higher up. `Store._load_sections_db` now takes `prefer_newer_catalog=True`
from the web layer and resolves each code **newest-first**, so a row stamped with
an older build simply loses to the catalog. Nothing in `data/db` was touched — the
135 rows are still on disk, they are just never served.

Measured on the machine that reported it, 2026-09-20:

| | |
|---|---|
| rows in `data/db/sections.json` | 572 |
| rows stamped `shipped-catalog` | 135 — **133 at `2026-09-07T14:07:54Z`**, 2 at `2026-09-09T22:35:44Z` |
| current catalog `built_at` | `2026-09-19T02:34:09Z` |
| shadow rows now superseded | **135 of 135** |
| courses served carrying the catalog's stamp | 571 of 572 |

The single exception is `51961`, which the catalog does not carry at all, so there
is nothing to supersede it with — it keeps its own `2026-09-06` fetch, which is
correct and is why `db.origin` reads `mixed` rather than `shipped`.

**The other half closed with it.** This entry's real complaint was a date that was
wrong about its own data — `הקטלוג נבנה לפני 3 ימים` describing records from a
build two days older. The header line is now `מעודכן מהידיעון · …`, and since the
merge gives every catalog-served record `fetched_at = built_at`, the date it shows
and the records it describes are the same stamp by construction.

**Still not established:** how those rows came to be written with a build stamp in
the first place. It is no longer blocking anything, and it is no longer costing
anything, but it was never answered.

---

### The shipped catalog was a build behind — closed 2026-09-10
**Where:** `data/catalog.jsonl` / `data/catalog.meta.json`, built 2026-09-07.
**Owner:** a decision waiting, not a loose end. Held back deliberately 2026-09-10.
**What happened:** the lecturer fix above needs the catalog rebuilt to carry
clean values at rest. `build_catalog.py --check` does it offline from
`data/raw`, and it worked — all six quality gates passed, 134 polluted rows went
to 0. It was **not committed**, because it also brings a data change that has
nothing to do with lecturers:

| | committed catalog (07/09) | rebuilt from today's `data/raw` |
|---|---|---|
| groups | 2166 | 2167 |
| timed meetings | 1186 | 1187 |
| 11069, semester א | 2 groups | **3** |

The third group of 11069 (`271060310/2`) is real: the yedion added it in the
2026-09-08 fetch, `data/db/sections.json` has had it since, and the app has been
showing it. Only the committed catalog predates it.

**Verified not to be caused by the parser change**, because that was the obvious
suspicion: the *old* parser on today's `data/raw` also yields 3 groups for
11069. The parser change moved lecturer strings and nothing else.

**Why it is held:** one extra group in a shared course multiplies through the
enumeration, and 15 assertions in `test_attendance.py` and `test_web.py` fail on
it — 27 groups becomes 28, an enumeration of 83 becomes 152, 564 becomes 960.
Those are the same count-pinned tests as the entry further down, and both files
are covered by the standing rule against editing existing tests. With the
committed catalog restored, all 112 tests in those two files pass.

**So the fix ships without the rebuild:** `store._group_from_dict()` repairs the
catalog's 134 rows as it reads them, so a fresh clone sees clean names anyway.
That is a patch over stale data, not a substitute for rebuilding it.

**Two ways out, for whoever picks this up:**
1. Rebuild the catalog and update the 15 counts, saying in the message that the
   yedion added a group on 2026-09-08. Honest, and it needs the test rule lifted.
2. Do the invariants conversion the count-pinning entry already recommends, and
   then the rebuild costs nothing.

Not "leave the catalog stale": every further yedion change widens the gap, and
the read-time repair only knows the phrases seen up to 2026-09-10.

**Closed 2026-09-10, the same night.** The count-pinned tests were converted to
invariants first (entry above), which removed the only thing standing in the
way, and then the catalogue was rebuilt and committed.

`build_catalog.py --check` builds offline from `data/raw` with no network. All
six quality gates passed. What landed:

| | before (07/09) | after (10/09) |
|---|---|---|
| courses | 572 | 572 |
| groups | 2166 | **2167** |
| timed meetings | 1186 | **1187** |
| lecturer values carrying a status note | **134 rows** | 0 |
| `status_note` populated | — | 134 rows |

The extra group is 11069's `271060310/2`, which the yedion added in the
2026-09-08 fetch. It is real, `data/db/sections.json` has had it since, and the
app has been showing it — only the committed catalogue predated it.

**The read-time repair in `store._group_from_dict()` stays.** It is no longer
load-bearing for the shipped catalogue, but it still covers the 12 courses that
`reparse` skips because they have no fixed time in semester א, and any older
`data/db` on another machine. It costs a string comparison per group on read.

Order of the two commits was reversed from the way it was asked for — tests
first, then the rebuild — so that neither commit is red on its own. Committing
the rebuild first would have left one commit in history with 15 failures in it.


### Eighteen tests pinned exact counts — closed 2026-09-10
**Where:** `tests/test_attendance.py`, `tests/test_web.py`, `tests/test_yedion_http.py`
— e.g. `test_the_real_database_has_six_courses_and_27_groups`.
**Owner:** unassigned — a test-robustness question, not a product bug.
**What:** these assert exact numbers ("six courses and 27 groups", a specific
enumeration size, a named lecturer) against `data/db/sections.json`, which is
gitignored, lives only on the machine, and is **rewritten by the running app**.

Observed twice on 2026-09-09 alone. The count went 1444 → 1445 groups between two
runs of the same suite, with `updated_at` moving to `15:06:08Z` three minutes
after the server was restarted at 18:03 local. Two tests failed in the morning,
eighteen by the evening, with no code change between them — verified by reverting
`app.js` and `strings.json` to `72b00ed` and getting the identical eighteen.

**Why it matters beyond the noise:** a suite that fails for environmental reasons
teaches you to skim its output, and that is exactly how a real regression gets
waved through. It also cost real time today — the drifting data was first
misread as the identity change breaking the API layer.

**Options, for whoever picks this up:**
1. Point these tests at a committed fixture rather than `data/db/`. Most direct,
   and the shipped `data/catalog.jsonl` is already a committed, stable source.
2. Assert invariants instead of counts — "every group has a kind and a group id"
   rather than "there are 27 of them".
3. Leave them, and accept that the suite is only meaningful with the app stopped.

Option 1 or 2. Not 3: the standing advice would become "ignore those eighteen",
which is worse than no test.

**Mostly closed 2026-09-09 by `dc8c20d`, option 1.** `tests/catalog_source.py`
writes `data/catalog.jsonl` into a temp `sections.json` and reads it back through
the same `Store` the app uses, so only the source changed and not the code path.
`test_attendance.py`, `test_web.py` and `test_yedion_http.py` are converted, and
the numbers came out exactly as written — nothing was weakened to pass.

**What is still open:** `tests/test_multifaculty.py` still points `DB_ROOT` at the
live `data/db` in four places (module-level API probe, a `copytree`, and a direct
`Store(DB_ROOT)`). It has not failed on drift, so this is prevention rather than a
live problem — but it is the same exposure, and it is the last of it.

**Closed 2026-09-10, option 2 on top of option 1.** `dc8c20d` had done option 1
— point them at the committed catalogue — which stabilised the *source* while
leaving the exact numbers in place. It bought one day. They broke again the
moment the catalogue itself legitimately moved: the yedion added a third
semester-א group to 11069 on 08/09, rebuilding the catalogue picked it up, and
15 assertions went red — 27 groups to 28, an enumeration of 83 to 152, 564 to
960. The rule against editing existing tests was lifted for exactly this, on the
grounds that a test which breaks when the yedion legitimately adds a group is
pinning something it does not care about.

**What each number became.** Nothing was deleted and nothing was loosened to a
range; every assertion still fails on a real defect. The pattern is that both
sides of the comparison are derived at runtime, so legitimate data movement
moves them together.

| was | is |
|---|---|
| `sum(len(groups)) == 27` | every one of the six courses has groups, kinds, and well-formed ids |
| `{"11069": 2, "61753": 4, ...}` | the same dict, read from the catalogue through `Store` |
| `feasible_count == 83` | `== _engine_feasible_count()` — the API agrees with the engine on the same data |
| `feasible_count == 83` after `top_n=3` | equal to the unrestricted solve's own count: `top_n` caps what is returned, not what exists |
| `feasible_count == 14` after a pin | `0 < pinned < unpinned` — pinning narrows, and neither kills everything nor is ignored |
| viability `counted == 27` | equal to the number of groups the payload carries — a coverage claim |
| blocking Sunday gives `== 0` | the count drops, **and** no returned meeting falls in the blocked window |
| enumeration `== 83` / `== 564` | equal to `legal_combinations()`, an exhaustive independent count of the same rule |

`legal_combinations()` is the interesting one. It walks the cartesian product of
one group per (course, component) — 2400 combinations here — and applies
`conflict_is_hard` directly, without `enumerate_selections`. That is precisely
what 83 and 564 were shorthand for, and it reproduces both exactly on the data
they were written against. The enumerator is where pruning bugs live, so
comparing it against an exhaustive count of the rule it claims to implement is a
stronger check than a literal, not a weaker one.

**Proved not to be a loosening**, two ways. The converted files pass against
*both* the old committed catalogue and the rebuilt one — which is the actual
claim, that they no longer pin data. And three mutations each had to fail, and
did: an enumerator that silently drops one legal combination (3 tests caught), an
API that drops a group from every course (4 caught), and a server that ignores
`blocked` entirely (1 caught — the very assertion whose `== 0` had just gone).

**Still pinned, deliberately:** `MIN_DAYS = 4`, `PICKS_PER_SCHEDULE = 12` and
`DAYS_USED`. Those are product claims someone decided — "four days is
reachable", "one component per course and kind" — not incidental counts. If a
data change moves one of them, that is worth a red test.


### The lecturer field held a note glued onto a real name — closed 2026-09-10
**Where:** `src/parser.py`, surfacing in `data/db/sections.json` →
`groups[].lecturer`, rendered on every grid block and the printed sheet.
**Owner:** parser. Raised with the owner 2026-09-09; not fixed, because the
parser is out of scope in `CLAUDE.md` without an explicit ask.
**What changed.** The entry below describes 6 of 291 lecturer values that were
*pure* notes (`טרם נקבע`, `הקורס מלא`). After the 2026-09-08 fetch:

| | 2026-09-06 | 2026-09-08 |
|---|---|---|
| distinct lecturer values | 291 | 348 |
| values containing a status note | 4 | **55** |
| of those, a note **glued onto a real name** | 0 | **51** |

Examples: `ד"ר קורנבלט קטרינה הקורס מלא`,
`ד"ר סוקולובסקי איזבלה בקורס זה קיימת רשימת המתנה`,
`ד"ר קליינגזינד שלום, טרם נקבע`.

**This is a different failure from the one below.** A pure note could be
filtered by matching the whole value against a known list. A note concatenated
onto a name cannot — the name is real and must be kept, and only the suffix
removed. The two phrases seen so far are `הקורס מלא` and
`בקורס זה קיימת רשימת המתנה`, both of which are enrolment status and belong on
the group, not in the lecturer field.

**It is visible in the product right now:** the grid block for
אנגלית טכנית יישומית renders the lecturer over three lines because the waiting
-list sentence is inside the name.

**It also breaks two tests**, and they are the reason it was found:
`test_web.py::test_solve_accepts_a_lecturer_ranking` and
`test_courses_groups_carry_kind_lecturer_and_group_id` pin
`ד"ר קליימן ילנה`, which the local database now stores as
`ד"ר קליימן ילנה הקורס מלא`. They fail on the current data and pass on the
2026-09-06 copy — the tests are correct and the data is not.

**Closed 2026-09-10.** The parser was scoped in for this specifically. Three
distinct shapes turned out to be behind it, and each needed a different answer.

**1. A status span glued to a real name.** The yedion puts `הקורס מלא` and
`בקורס זה קיימת רשימת המתנה` in their own
`<span class="text color-red">`, sitting between the name and
`שפת הוראה של הקורס` — exactly as it puts the group id in a blue span.
`_visible_text()` flattens the block to one string, so the non-greedy capture
in `_GROUP_LECTURER_RE`, which stops only at `שפת הוראה`, swallowed the span
too. The `פרטים נוספים` alternative in that regex had quietly become dead: the
yedion moved that text into a `<button>`, and `_visible_text()` strips buttons.
The fix reads the red spans off the DOM and removes one **only** where it is an
exact suffix of the captured value, so it is driven by the yedion's own markup
rather than by a list of phrases, and a new wording is handled by itself.

**2. A note written instead of a name**, as bare text with no markup at all:
`טרם נקבע` (26 rows) and `מיועד לחוזרים` (19). Nothing in the DOM distinguishes
these, so they are matched against a short list — on the **whole** value, never
a substring, which is what makes it safe. `טרם נקבע` empties the field, because
that is what it means and the UI already renders "מרצה לא ידוע"; `מיועד לחוזרים`
is kept as a status note, because who may register is real information.

**3. No name at all.** `(.+?)` needs at least one character, so it could not
stop at `שפת הוראה` when the yedion emitted `מרצה הקורס :` and nothing after
it — the capture ran to the end of the page. Course 312781 stored a lecturer of
`"שפת הוראה של הקורס : עברית מערכת שעות ... מדיניות הפרטיות הצהרת נגישות"`.
`(.*?)` fixes it. This one was not in either entry above; it was found while
fixing them.

**Where the note went.** A new `Group.status_note`, separate from `Group.note`
on purpose: `note` carries tie-group and attendance text, and
`api.attendance_info()` scans it with a regex, so a status note landing there
would change what the interface says about attendance. It is rendered as a chip
in the group table in step 4, under the group id — never on a grid block, which
Phase 10 just settled and which is already clipping.

**What was deliberately not done: splitting on the comma.** 24 catalogue values
are two or more real lecturers for one group, up to four in a single value
(`ד"ר קלס סיון, ד"ר גזית שמואל, ד"ר יסעור קרוח לילך, פרופ' סבאח עיסאם`). A
naive split would have turned all of them into rubbish. Only a segment that is
**exactly** one of the non-name phrases is dropped, which is what repairs
`ד"ר קליינגזינד שלום, טרם נקבע` without touching the other 23.

**Measured, not asserted.**

| | before | after |
|---|---|---|
| `data/raw`, all 572 saved pages | — | **0** lecturer values carrying a note |
| `data/db/sections.json` | 44 of 346 values, 119 group rows | 0 |
| shipped catalog, as `Store` returns it | **134** group rows | 0 |
| multi-lecturer values kept whole | 24 | 24 |

**The data was repaired too, not only the code**, by two different routes.

`reparse.py` rebuilt the 76 affected courses from `data/raw` with no network:
572 courses and 1445 groups before and after, none lost, and the only fields
that moved were `lecturer` (108) and `status_note` (213).

The other route is a **read-time** repair in `store._group_from_dict()`, and it
covers two cases the reparse cannot. 12 courses have no fixed time in
semester א, so `parse_course_page(..., semester="א")` returns `None` and
`reparse` skips them entirely. And `data/catalog.jsonl` — committed, and what a
fresh clone reads — was a build behind on the night this landed, so it was
repaired on read too; it has since been rebuilt (see the entry above), and the
read path stays as a floor under any older copy.
Reading has no HTML and therefore no red span, so this path uses a two-item
phrase list (`_LEGACY_STATUS_SUFFIXES`) plus a prefix check for labels that
leaked into the field. It removes an **exact suffix only**, and only when a name
remains after it, so it cannot shorten a real one. The parser itself stays
DOM-driven; the list exists for bytes already on disk.

**Tests:** `tests/test_lecturer_status_note.py`, 24 of them, including every
shape above, the 24 multi-lecturer values, and three mutations that each had to
fail: `(.+?)` restored, the suffix removal disabled, and the comma guard
loosened.

**A caution recorded with it.** Diagnosing this, the same investigation first
reported that the database had been emptied and that an empty local overlay was
masking the shipped catalog. Both were wrong, and both came from guessing a
JSON shape instead of reading it: groups live at
`courses[<code>].course.groups`, not `courses[<code>].groups`, and the
`semester` field of `POST /api/courses` is the **term** (`"א"`), not the
program-semester number. Read the schema before reporting data loss — the
restore that was nearly performed would have replaced 572 courses with 433.

### The lecturer field sometimes held a note, not a name — closed 2026-09-10 with the entry above
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


### A running server served a three-day-old template — closed 2026-09-08
Three Phase 10 header changes were reported as visible and were not. The code
was right and committed; the server was from 2026-09-05. Jinja's `auto_reload`
defaults to `app.debug`, so `create_app()` compiled `index.html` once and served
that copy for the life of the process — including a button deleted from the repo
before this session began.

**What made it read as "the work was not done" rather than as a cache:**
`style.css` is a static file, read from disk per request, so the palette and the
`order: 1` wordmark move *did* appear. `index.html` is a template, so the icon,
the theme buttons and the moved scrape control did not. Half the change landing
looks nothing like staleness. `Ctrl+F5` cannot help — the browser refetches and
the server hands back the same compiled copy.

Measured at the time: the file on disk had 4 occurrences of
`brand-icon`/`theme-ico`; `http://127.0.0.1:5000/` served **0**, plus
`כהה</button>` and `עבד מחדש את הנתונים השמורים`. The same URL served the
current `style.css`, `--dark-accent-soft: #3e3e3e` and all.

**Now:** `api.py` sets `TEMPLATES_AUTO_RELOAD` and `jinja_env.auto_reload`
explicitly, so it no longer rides on `app.debug` — the student's server runs
without `--debug`, which is exactly the case the default got wrong. Cost is one
`stat()` per template render, on a local app for at most five people.

**This is the third instance of one pattern in this repo,** and worth naming as
such: `strings.py`'s module-level `_CACHE` (closed with an mtime check), the
shipped-catalog module cache, and now Jinja's template cache. A long-running
local dev server plus any process-lifetime cache equals "I changed it and
nothing happened". `tests/test_template_autoreload.py` closes this one
behaviourally — same app object, file changed on disk with mtime pushed
forward, new content asserted — and was mutation-tested by deleting the two
lines, which fails all three of its tests.

**The habit this should leave behind** is in `CLAUDE.md`: verify against the
server the user is actually running. A throwaway server started by a script
always has the current template and will confirm anything asked of it.

### Phase 10 — closed 2026-09-08, all four items
1. **The visual identity.** Four directions were proposed against the brief's
   constraints, each adversarially reviewed, and every claimed contrast ratio
   re-computed rather than taken on trust. Three were shown; **Paper & Ink** was
   chosen, with its dark theme's warm brown page rejected and replaced by a
   neutral lifted charcoal derived from the same luminance ladder. See the two
   commits for the measurements.
2. **The wordmark moved left, with an icon.** `order: 1` rather than reordering
   the DOM, so the product name stays first for a screen reader and first in the
   Tab order while only its painted position changes. The icon is an inline SVG
   of a timetable with one filled slot — not an emoji, which renders differently
   per platform and carries no colour.
3. **The theme switch is three icons** — moon, sun, monitor — with the accessible
   name in `aria-label`, since there is no visible text left to name them. The
   selected state is marked twice: the accent pill, **and** the shape inside the
   icon filling in. A coloured pill on its own distinguishes by hue and lightness
   only, which is what rule 7.1 forbids.
4. **`עדכן נתונים מהידיעון` moved into `פרטים טכניים`.** It stays in the product
   because it is the only way to check whether one course changed since the
   catalog was built; it is not a student's action, so it is not in the header.
   `עבד מחדש את הנתונים השמורים` needed no move — that button and
   `startReparse()` were already deleted on 2026-09-07 (see the dead-state entry
   above), so only its string survives in `strings.json`.

**Guarded by `tests/test_phase10_header.py`** (7 tests). Two of them are worth
knowing about, because the obvious version of each would pass while broken:
the wordmark's position is measured from the **painted rectangle**, since a
class name proves nothing in a flex row driven by `order`; and the theme state
compares the computed `fill` of the selected icon against the unselected ones,
because asserting "the selected one has the accent background" is asserting
exactly the colour-only signal the rule forbids. Both were mutation-tested —
removing `order: 1` and removing the `.ico-fill` rule each produce a failure.

**Two existing tests were updated, not worked around.** `.theme-btn` left
`LABEL_SELECTORS` in `test_rendered_copy_browser.py` because those buttons no
longer have visible text; their name is now asserted on `aria-label` instead.
And `test_key_screens_carry_hebrew` watched `.header-actions` for Hebrew, which
is the element that moved — it now watches `#freshness`, which is what is
actually left in the header.

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

