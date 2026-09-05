# Development log — SlotWise

What was built, in what order, what broke, and how it was fixed.
Reconstructed from the session transcripts under `~/.claude/projects/` (session
`8ee53a5d-a0ab-42b3-975c-5dc672f1a4c3`, 2026-08-30 → 2026-08-31).

The recurring theme is worth stating up front: **almost every serious bug in this project came from
building against assumed markup instead of real markup.** The fixes that mattered came from
reconnaissance and from the first contact with real Braude data.

---

## Phase 1 — Intake and curriculum extraction (2026-08-30 ~11:00)

The student described the goal: build a semester timetable from real course data, choosing
preferred lecturers, targeting a number of days on campus.

**Inputs provided:** `rec.pdf` (the department chapter of the שנתון) and `Screenshot.png` (the
yedion course-search page).

Established before asking anything:
- `rec.pdf` is 14 pages of Hebrew RTL tables.
- **Problem:** `page.get_text()` scrambles RTL tables — rows interleave and columns reverse.
- **Fix:** coordinate-aware extraction with PyMuPDF — cluster words by `y`, sort each row by
  *descending* `x`. This reconstructed all 8 semesters and 74 electives correctly.

Result: `data/curriculum.json` — 8 semesters, 6 elective clusters, prerequisites, tied courses,
and the replacement-course mapping (61832→61760, 62027→61769, 62028→61762, 62018→61912).

**Intake answers:** שנה ג', סמסטר א' תשפ"ז → curriculum semester 5. Target 4 days. Balanced
priority. Courses chosen: the tied block 61756+61757+62027, plus 61832, 11069, and **61753
אלגוריתמים borrowed from semester 4**.

Noted at the time: taking 61753 instead of 61759 is correct, because 61753 is 61759's prerequisite.

## Phase 2 — Reconnaissance (the highest-value hour of the project)

`info.braude.ac.il/yedion` 302-redirects anonymous requests to `loginedu.braude.ac.il`, a **Citrix
NetScaler AAA gateway**. No API, no anonymous fetch.

Rather than guess the markup, two sources were found:
1. `AvielMalayev/BraudeCurriculumBot` on GitHub — drives the real Braude yedion, confirming the
   `#SubjectCode` and `#searchButton` control ids.
2. **A publicly reachable instance of the identical Yedion product** at
   `mtamn.mta.ac.il/yedion` (Tel-Aviv Yaffo College), serving the same `Enter_Search` page.

Against that public instance the whole protocol was reverse-engineered and *verified*, with no
Braude credentials involved:

| discovery | how it was verified |
| --- | --- |
| search is a plain `GET ?prgname=S_LOOK_FOR_NOSE&arguments=-N<code>` | fetched real course pages |
| results are **Bootstrap `div.row`/`div.col`, never `<table>`** | zero `<table>` elements in any response |
| `קבוצות הקשורות לקורס זה` links lectures to their permitted tutorials | course 271030 |
| the academic year is **session state**, set by a POST, not a URL parameter | flipping the year changed course 271030 from תשפ"ז/5 groups to תשפ"ו/15 |
| the whole catalog costs **one** request | `-Aא`, `-Aמ`, `-Aש`, `-A` all returned byte-identical 566,762-byte responses |

Written up as `GROUND_TRUTH.md`, and five real pages saved as parser fixtures.

**This changed the design twice.** The original `SPEC.md` told the parser to look for `<table>`
elements — it would have found nothing. And without the year switch the tool would have silently
returned **תשפ"ו** data, since the yedion defaults to the previous year.

## Phase 3 — First build (21 agents, orchestrated)

Interfaces were pinned first: `src/models.py` was written by hand as the shared contract, then
seven modules were built in parallel against `SPEC.md`, each with adversarial review.

Delivered: `curriculum.py`, `scraper.py`, `parser.py`, `scheduler.py`, `render.py`, `cli.py`,
`main.py`, and 77 offline tests.

**Caught by review:** on session expiry the scraper would have taken a full-page screenshot of the
**autofilled login page** into `data/raw/`. Fixed: nothing from a non-`info.braude.ac.il` host is
ever written to disk.

### Bugs found and fixed by hand after that build

| bug | consequence | fix |
| --- | --- | --- |
| renderer used 30-minute slots | 08:30–10:15 followed by 10:15–12:00 collided in one cell, so a **valid schedule was reported as having conflicts** | 15-minute slots, and clash detection now uses real interval overlap rather than cell collision |
| terminal grid blanked after a class's text | classes looked like they ended early | added a `└ עד HH:MM` duration marker |
| gendered Hebrew imperatives (`דרגי`, `פתחי`) | assumed the reader's gender; pronouns were never stated | neutral infinitive forms throughout |

## Phase 4 — Protocol hardening

Semester filtering and academic-year assertion were added across parser, scraper and CLI, because
a course page lists **both semesters** and the yedion defaults to the wrong year.

**Caught by review:** a failed form-submit was being cached as "course not offered", which would
then delete good cached data.

## Phase 5 — Live discovery + self-refreshing database

Prompted by the student: *"Sometimes courses from previous semesters are repeated. It's not always
exactly like the curriculum."* So `curriculum.json` stopped being a gate — the yedion became the
sole source of truth for what is offered.

Built `store.py` (atomic JSON store, staleness, change detection), `discovery.py` (one-request
catalog), `refresh.py` (scheduled job with Windows Task Scheduler integration).

**The orchestration run reported total failure — all five agents hit a session limit.** The files
had already been written; only the review phase was lost. Verification was done by hand instead,
which found:

- `save_course` did `fetched_at = meta.fetched_at or now_iso`, so an **empty** timestamp was
  back-filled to "now" while malformed-but-non-empty stayed stale. Data of unknown provenance was
  being presented as freshly fetched. Fixed to fail safe: unknown timestamp ⇒ stale.

## Phase 6 — First contact with the real yedion (2026-08-30 ~15:50 → 2026-08-31 ~03:30)

### The login that never registered

The first `refresh.py --headful` run waited the full 600 seconds and timed out **even though the
student had logged in successfully**.

Cause: the "are we in yet?" probe was gated behind `not _looks_like_login_page(url)`, and the marker
list contained `/vpn/` — which is exactly where Citrix parks you *after* a successful login. "Still
typing a password" and "logged in, sitting on the portal" were indistinguishable by URL, so the gate
never opened.

Fix: **stop guessing from the URL.** Probe every 12 seconds by actually trying to open the yedion
and seeing whether it sticks. Safe because the probe uses a throwaway tab and refuses to run while a
password field is on screen.

Also learned: **Citrix AAA cookies are session cookies and die when the browser closes.** Login and
scrape must therefore happen in one run. `--headful` already does this.

### The scrape succeeded — and the data was quietly wrong

All six courses were fetched and year-verified. But Braude runs a **newer, more accessible build**
of the yedion than the Tel-Aviv instance the parser was written against, and it broke three things:

| bug | consequence |
| --- | --- |
| every cell carries `<span class="LabelIn">סמסטר:&nbsp;</span>` | cell text read `"סמסטר: א"` instead of `"א"` — the **semester column came through empty, so the א-filter did nothing**, and room data was lost. Lecturer names were polluted with `שפת הוראה של הקורס`. |
| group ids contain a slash (`271060330/ 1`) | the linked-group parser split on `/`, shattering every id so the lecture↔tutorial constraint **matched nothing and was never enforced**; ids also collapsed together, so **61756 showed 4 groups when it has 7**, and 61757 showed 3 when it has 6 |
| `שו"ת` (שיעור ותרגיל) was an unknown component type | 11069 was labelled `אחר` |

Fixes: strip accessibility label spans before reading any cell (`_strip_label_spans`), normalise
group ids and parse linked ids as whole tokens, and add `KIND_COMBINED`.

Because every page had been dumped raw to `data/raw/` **before** parsing, all of this was fixed and
re-verified with **no second login and no extra load on the college's server**. That is what
`reparse.py` is for — it re-derives the database from saved HTML and stamps the *original* fetch
time, never "now".

### One more wiring gap

`obtain_sections` in the CLI never consulted the Store — it fell through to the synthetic test
fixtures. The schedule shown looked completely real but used **invented lecturers**. Fixed: the
database is now the first source, and the UI prints where the data came from and how old it is.

## Phase 7 — What the real data actually says

Established by exhaustive enumeration, not estimation:

- **Only 16 feasible combinations exist, and every one needs 5 days (א–ה).** The 4-day target is
  unreachable with these six courses. Friday is always free.
- **9 of the 27 groups are dead ends** — picking one leaves no valid schedule at all. A third of
  them. This is why the web app pre-computes viability instead of letting a click strand the user.
  (First measured as 8. The verification script pinned a group by *deleting* its siblings, which
  also drops them from the scheduler's kind index and silently disables `linked_to` enforcement —
  the same bug the review caught in `api.py`. The missed case was 62027's tutorial `271060310/1`,
  excluded by the lecture group's link to `271070310/1`.)
- **Dropping 11069 (1 נ"ז) reaches 4 days** while keeping 18.0 of 19.0 credits. Caveat: 11069 is a
  prerequisite for פרויקט מסכם and every seminar.
- 61753 אלגוריתמים **is** open in סמסטר א' — the original open question.

## Phase 8 — Web app (in progress at the time of writing)

The student clarified that "system" always meant a browser app, not a terminal program. The
question-and-answer layer is being moved to Flask on localhost, reusing the scraper, store,
year verification and scheduler unchanged.

Verified before building: pinning a group needs **no scheduler change** (filter `course.groups`
before `solve`), and a solve takes **~1 ms**, so the server can re-solve on every interaction and
pre-compute viability for all 27 groups in about 30 ms.

Also noted: the interactive flow cannot run through a non-TTY stdin. The error message now explains
this and names the command to run in a real terminal.

---

## Phase 9 — The year+semester choice actually decides what is marked (2026-09-03)

**Problem:** step 2 marked the same six courses for everyone. The checked set was seeded once from
`/api/bootstrap` → `defaults.codes` → `data/profile.json`, which is one student's personal list and
included 61753 — a **semester 4** course. Picking a different year or term re-fetched and re-drew the
course list but never touched the selection, so a student on year 2 saw semester 3's six courses
empty and, underneath them, six checked semester-5 courses tagged "מחוץ לסמסטר הזה".

**Fix:** the recommendation for the chosen semester is what gets checked, applied in
`applyRecommendedDefaults()` from inside the `fetchSemesterCourses` response — the only moment the
new semester's list actually exists. Seeding on the year/term change itself would have marked the
*previous* semester's courses. The profile seed in `applyBootstrapDefaults` is gone; the name cache
it also fed stays, so a course added by hand still shows its real name.

Four persisted fields carry provenance, with `state.codes` still the single source of truth for
drawing: `autoSemester`, `autoCodes`, `manualCodes`, `autoDropped`. Switching semester swaps the
first set and keeps the second — the tool only ever removes what the tool added.

**What the data forced:**
- **Alternatives may not all be checked.** Three English/Hebrew placement rows in semester 1, two in
  semester 2, and both physics tracks in semester 4 (61179+61180 vs 61181). They are flagged, shown,
  and left empty with a visible reason. The flags `placement` / `physics_track` existed in
  `curriculum.json` and were being dropped by both the API row builder and `normalizeSemesterCourse`.
- **The near-miss:** keying exclusivity off `group` or `cond` looks right and is wrong. 11069
  (אנגלית טכנית) is `group: "english"` with a `cond`, and is a hard requirement — such a rule would
  have silently unchecked the one English course in semester 5. A test now pins this.
- **`offered: false` is only trustworthy with a catalog.** `offered_codes({})` is empty, so on a
  fresh install every row reads "not offered" and the recommendation would have been empty with no
  explanation. Gated on `fallback.catalog_count > 0`.

**Six bugs, none of which came from reading the code.** Three surfaced by driving the page in
headless Chromium, three more from an adversarial review of the finished diff:

1. Returning from קיץ re-ran the *adoption* path and marked the entire recommendation as
   "manually cancelled", leaving the list empty. `autoSemester === ""` cannot distinguish "never
   applied" from "cleared by summer" — that needed its own flag, `provenanceReady`.
2. **Switching program kept the previous program's plan checked** — six software courses for a civil
   engineering student. The semester number does not change when the program does, so the
   "same semester, don't touch" gate let it through. The deeper cause is older than this change:
   `syncData` keyed the semester fetch on `state.semester` alone, so a program change never
   re-requested the list with the new `?program=`. The program is now part of that signature.
3. The first browser test raced the app's own first save: writing `localStorage` after `goto` lost to
   the bootstrap chain about half the time. Seeding via `add_init_script`, before any page script
   runs, is deterministic.
4. **The `seq.semester` staleness guard had a hole.** The "no semester" early return changes the
   effective request but did not advance the counter, so a still-in-flight response for the previous
   semester passed the guard. Reproduced: pick year 2, then קיץ within ~100 ms, and the semester-3
   recommendation is applied and *saved* while the screen says summer. Before this change the same
   race only left a stale list rendered; the applier turned a display glitch into state corruption.
5. **A semester change silently destroyed pinned groups, lecturer rankings and attendance settings.**
   `prunePicks` deleted them for every code not in `state.codes`, which was safe only while a
   semester change never removed codes. Peeking at another semester and coming back lost the work
   for good. Those entries are now kept dormant and filtered at the wire (`buildSolveBody`) and in
   the counters instead — so coming back to a course brings its pins back with it.
6. **The one-time adoption swallowed the student's first choice** when the saved state belonged to no
   semester (saved on קיץ). Picking שנה ג׳/סמסטר א׳ recorded the whole semester-5 recommendation as
   "cancelled" and left an empty list — the exact opposite of the request. Adoption is now bound to
   the semester the saved state actually belonged to; a selection from any other semester is treated
   as manual and the new recommendation applies over it.

Each of 4, 5 and 6 was mutation-checked: the fix was reverted and the matching test confirmed to fail.

**Result:** 498 → 528 tests, 6 skipped, none failing. 13 of the new ones cover the server contract and
the rule; 17 drive step 2 in headless Chromium, which is the project's first coverage of `app.js` at
all — the rule, the provenance bookkeeping, the summer path and the staleness guard all live there
and had none. That absence is exactly why bugs 4-6 survived a careful reading of the diff.

---

## Phase 10 — A curriculum for every department (2026-09-04)

Step 2 recommended per-semester courses only for Software Engineering, because there was only ever
one curriculum file. The other seven programs got catalog search even where the college publishes a
full semester-by-semester plan for them.

**The audit came first, and it was worth it.** All seven שנתון chapters turn out to contain a real
required-course plan — none is elective-clusters-only — but only two (`sw`, `system`) have the flat
eight-semester shape `data/curriculum.json` assumes:

| chapter | plan | the complication |
|---|---|---|
| `sw`, `system` | 1–8 | none |
| `electric` | 1–8 | semesters 7–8 are three תכן־הנדסי routes; totals printed as `3/5/7` |
| `civil` | 1–8 | core + overlay; semesters 3–7 split by 2 tracks — **not the 4 `curricula.json` claimed** |
| `mecho` | 1–8 | semesters 5–7 split by 4 tracks; 4 of 8 semesters do not reconcile |
| `industry` | 1–8 **twice** | the whole plan once per התמחות; semesters 3–8 diverge, credit loads included |
| `math` | 1–6 **twice** | a 3-year degree, split by **winter/spring intake**, with no shared semester |

Two facts hold across all seven: **no chapter states the study year or term** next to any table —
Software Engineering's `year: 3, term: "א"` was always an inference from the semester number — and
only two state a cohort year. The `תשפ"X` tokens in the other five mean other things entirely (an
English policy date, departmental history), so `cohort_year` is `null` there and every semester now
carries `year_term_inferred: true`.

**What shipped:** one curriculum file per department under `data/curricula/`, a `_curricula()`
registry, and `_curriculum(program)` resolving by program name. Civil, Electrical, Mechanical and
Information Systems now get their own recommended list. Industrial Engineering and Applied
Mathematics deliberately do **not** — a single flat list would be wrong for half their students —
and Biotechnology has no chapter at all. All three stay on catalog search, with an explanation.

Track courses reuse the alternatives mechanism from Phase 9: non-empty `track` means shown, badged
with the track name, never auto-checked. That was the whole reason the mechanism generalised cleanly.

**Verified by arithmetic, not by eye.** Every published semester's extracted credits are checked
against the total the chapter itself prints: `electronic` and `infosystems` reconcile 8/8, `civil`
7/8, `mechines` 4/8. Semesters that do not reconcile are published with `reconciles: false` and a
Hebrew note, and step 2 shows the caveat — for `mecho` the printed totals are themselves suspect
(semester 7 demands a 3.0-credit course that appears in no table).

**A shipped data bug, found on the way:** `data/curriculum.json` recorded 61181 with `he: 3`. The
PDF says 2 — the "3" is a 6.56pt bold footnote marker sitting left of the course name, against 9.42pt
body text. One row in 56 was affected; the same trap exists in every chapter.

**Three bugs the browser found that reading did not:**
1. Switching *program* kept the previous program's plan checked, because the semester number does not
   change when the program does. Ownership is now the pair (program, semester), not the semester.
2. Electrical semester 8 auto-checks nothing (all three rows are track routes), and the explanation
   was hidden along with the empty recommendation — leaving a blank list with no reason given.
   "A plan was applied" and "some course qualified" are different conditions.
3. A program change never recomputed `state.semester`, so Biotechnology — which has no chapter —
   went on claiming "סמסטר 5 בתוכנית הלימודים" inherited from Software Engineering.

**Test fallout, legitimate:** `test_a_student_of_another_program_is_not_shown_software_courses`
asserted that Mechanical Engineering gets an empty list. It now gets its own courses, so the test
asserts what its name always claimed — that none of them are Software Engineering courses — and a
new test covers the genuinely chapter-less case.

**Known gap, stated plainly:** the four new files were extracted per-department, each needing its own
handling of totals rows, track tables and section boundaries. There is no committed shared extractor
that reproduces all four, so these JSON files are currently artifacts rather than build output.
`src/shnaton.py` still covers only the elective sections.

---

## Phase 11 — Re-baselining the solver constants (2026-09-04)

Eleven tests in `test_attendance.py` and `test_web.py` were failing. They assert solver constants
measured against a particular `data/db` vintage, and the database had gone mixed: most courses were a
day old, six had been refetched hours earlier by verification scripts that ran with the network on.

`python refresh.py` (571 tracked courses, ~29 min, HTTP path, no login) reported **partial**: 286
refreshed, 260 failed, 172 changes. Of the failures, 255 are `parse returned no course` — the normal
outcome for tracked codes the yedion does not serve a course page for — and 5 were HTTP errors. It
also **skipped the two courses that mattered most**, 61832 and 62027, because they were under the
20-hour staleness threshold; a targeted `--codes ... --max-age 0` brought all six to one vintage.

**Why the numbers moved, which is the whole point of doing this properly.** In `61832`, two lecture
groups now carry a `linked_to` entry pointing at *their own group id*:

```
271060310/1 הרצאה   now = ['271060310/1', '271060310/2', '271070210/1']
                    was = [                '271060310/2', '271070210/1']
```

That self-link is exactly what the "do not link a group to itself" filter removed in Phase 9 used to
drop, and it is correct — at Braude a lecture and its tutorial **share a group id**, so a lecture
linking to its own id means "the tutorial with that id". The parser was fixed in Phase 9, but the
stored data still held pre-fix pages; only re-fetching and re-parsing put the fix into the database.

Consequences, all one cause:

| constant | was | now |
|---|---|---|
| `FEASIBLE_COUNT` / `TODAY_FEASIBLE` | 54 | 83 |
| `SOFT_FEASIBLE` | 370 | 564 |
| pinned-tutorial count | 7 | 14 |
| `KNOWN_DEAD_ENDS` | 1 entry | **none** |

Unchanged and re-verified: `TOTAL_GROUPS` 27, `PICKS_PER_SCHEDULE` 12, `MIN_DAYS` 4,
`DAYS_USED` [1,2,3,4], and the group ids the pin test names.

The last dead end was itself an artifact. `61832 תרגול 271070210/1` looked unreachable only because
its lecture's `linked_to` was missing the self-referential id. Nine dead ends before the parser fix,
one after, none after the data caught up — so `test_only_the_one_known_dead_end_remains` became
`test_no_phantom_dead_ends_appear`, which is the direction every bug here was ever in.

Three test names still said "sixteen" while asserting 83, stale since the 16→54 re-baseline. Renamed;
a name that has to be re-read against the constant is worse than no name.

**548 passing, 6 skipped, zero failures** — the first fully green suite since the database drifted.

**The lesson, recorded because it cost real time:** verification scripts must run with
`allow_network: False` against the real `data/db`, or point at a temp copy. The committed browser
tests do; ad-hoc scratch scripts did not, and quietly moved five baselines.

---

## Things that cost time, worth remembering

- **Heredocs and Hebrew.** `bash <<'EOF'` broke on Hebrew apostrophes (`א'`). Use the file-writing
  tool for Hebrew content.
- **Backticks inside JS template literals** silently terminated a workflow script string.
- **Broad `.gitignore` globs are dangerous.** `*token*` and `*secret*` would have silently ignored
  legitimate source files like `tokenizer.py`. Replaced with precise patterns.
- **A workflow reporting failure does not mean nothing was produced.** Agents that hit a session
  limit had already written their files; only the review phase was lost.

## Invariants that must not regress

1. Nothing from a non-`info.braude.ac.il` host is ever written to disk.
2. Credentials are never requested, read, stored or logged — login is always a real browser window.
3. The academic year is asserted on every page; wrong-year data is never written to the database.
4. Meetings are filtered by semester; a blank semester is kept, never silently dropped.
5. Stale data is never presented as current.
6. Overlap is half-open `[start, end)` — touching classes do not conflict.
7. Tied courses (61756/61757/62027) are all-or-nothing.
   A tied package is auto-checked only if every member qualifies — never half of one.
8. `linked_to` is enforced, or the tool will propose schedules that cannot be registered.
9. Mutually exclusive alternatives (`placement`, `physics_track`) are shown but never auto-checked —
   and exclusivity is never inferred from `group` or `cond`.
10. The tool removes only courses the tool added. A hand-picked course survives every semester change.
11. Every path that changes the requested semester advances `seq.semester` — a guard with one hole
    is not a guard.
12. Pins, lecturer rankings and attendance settings are never destroyed by a course leaving the
    list. They go dormant and are filtered at the wire.
13. A student is shown their own department's curriculum or none at all — never another
    department's, and never a plan invented to fill a gap.
14. Year and term are inferred from the semester number, never read from a chapter, and every
    semester says so with `year_term_inferred`.
15. A semester whose credits do not match the total its own chapter prints is published with
    `reconciles: false` and a visible caveat, or not at all.
