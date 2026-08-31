# Development log — Braude Schedule Builder

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
8. `linked_to` is enforced, or the tool will propose schedules that cannot be registered.
