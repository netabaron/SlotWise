# Command-line reference

The browser app is the primary interface (`python main.py`). Everything below is
for the terminal flow, the scheduled refresh job, and offline re-parsing.

---

## `main.py` — launcher

With no flags, `main.py` starts the local Flask server and opens the browser.

| Flag | Meaning |
| --- | --- |
| `--port N` | Port to listen on (default 5000; climbs upward if taken) |
| `--no-browser` | Start the server without opening a browser |
| `--debug` | Development mode — full error pages |
| `--cli` | Run the original terminal flow instead of the browser |

Any terminal-only flag used without `--cli` is detected: `main.py` says so and
runs the CLI flow rather than failing on an unrecognised argument.

## `main.py --cli` — terminal flow

```bash
python main.py --cli                          # interactive: scrape, pick lecturers, solve
python main.py --cli --offline                # cache or demo data, no fetching
python main.py --cli --top 3 --days 3
python main.py --cli --codes 61756,61757,62027
python main.py --cli --semester א --year 2027
```

| Flag | Meaning |
| --- | --- |
| `--refresh` | Re-fetch from the yedion even when a cache exists |
| `--offline` | Never fetch — cache, or demo data if there is no cache |
| `--top N` | How many schedules to print (default 5) |
| `--days N` | Target days on campus (default: from the profile) |
| `--html PATH` | Where to write the standalone HTML timetable |
| `--codes ...` | Comma-separated course codes, instead of the profile's |
| `--semester א\|ב\|קיץ` | Which semester's meetings to keep |
| `--year YYYY` | Academic year, Gregorian (2027 = תשפ"ז); a Hebrew label also works |
| `--pick` | Choose courses from the live catalog (search by code, code prefix, or part of the name) |
| `--track ...` | Add codes to the auto-refresh set |
| `--untrack ...` | Remove codes from the auto-refresh set |

The curriculum is a recommendation, not a fence: courses repeat from earlier
semesters, and what actually opens is decided by the yedion alone. `--pick`
shows the live catalog and labels each hit as in-plan for the current semester,
in-plan for another semester, or outside the plan — **all three are selectable.**
`data/curriculum.json` is used only for names, credits, prerequisites and tied
courses.

## `refresh.py` — scheduled refresh

Fetches into the local JSON database under `data/db/`. The default path is a
plain HTTP fetch: no browser, no window, no sign-in.

```bash
python refresh.py                 # refresh what is stale
python refresh.py --status        # database state; makes no network request at all
python refresh.py --all           # every course offered this year, not just tracked ones
python refresh.py --codes 61753   # specific codes (also adds them to the tracked set)
python refresh.py --catalog-only  # catalog only, no group detail
python refresh.py --max-age 12    # only refresh entries older than 12 hours
python refresh.py --install-task  # register a daily Windows scheduled task
python refresh.py --uninstall-task
python refresh.py --browser --headful   # fallback path through a real browser
```

| Flag | Meaning |
| --- | --- |
| `--status` | Print freshness, last run and recent changes; no network |
| `--install-task` / `--uninstall-task` | Register / remove the daily Windows task |
| `--task-time HH:MM` | When the daily task runs (default 07:00) |
| `--all` | Refresh every offered course, not only the tracked ones |
| `--codes ...` | Refresh these codes now, and track them |
| `--catalog-only` | Catalog only, skip the per-course group pages |
| `--max-age HOURS` | Staleness threshold in hours (default 20); `0` refreshes everything |
| `--browser` | Fallback: fetch through Playwright instead of direct HTTP |
| `--headful` | Only with `--browser` — show the window so you can sign in manually |
| `--year YYYY`, `--semester א\|ב\|קיץ` | Override the profile's target |

**Exit codes** — the scheduler reads these:

| Code | Meaning |
| --- | --- |
| `0` | Refreshed, or everything was already fresh |
| `2` | Sign-in required — **`--browser` path only** |
| `3` | Partial refresh: some courses failed |
| `1` | Error |

Exit code `2` cannot occur on the default HTTP path, because that path never
signs in. On the `--browser` path, an expired session leaves existing data
untouched, marks the record stale, writes `needs_login` to the log, and prints
the real age of the data. **Stale data is never presented as current.**

### What gets written

```
data/db/catalog.json       every course offered — code, name, status
data/db/sections.json      detailed groups plus per-course metadata (fetched_at, year, semester, sha1)
data/db/details.json       per-course detail pages
data/db/tracked.json       the codes that refresh automatically
data/db/refresh_log.jsonl  one line per run
data/db/changes.jsonl      one line per detected change
data/db/snapshots/         a backup before every overwrite (last 30)
```

### Change detection

Every refresh diffs against what is stored and reports out loud:

```
61753: group 21 — lecturer changed: ד"ר לוי נטלי -> ד"ר גולני מתתיהו
61753: group 21 — time changed: Mon 10:15-12:00 -> Mon 14:00-15:45
61753: group 22 added (tutorial, מר גל תומר)
61753: group 27 cancelled (tutorial)
```

A lecturer or time changing *after* you have registered is the single most
useful thing this tool can tell you.

## `reparse.py` — re-parse without the network

Every fetched page is saved raw to `data/raw/` before it is parsed, so a parser
fix can be re-run without touching the college's server:

```bash
python reparse.py                # all tracked codes plus the catalog
python reparse.py --codes 61753
python reparse.py --semester ב   # see what the other semester holds
python reparse.py --year 2027
```

The timestamp written is the **real fetch time** (the HTML file's mtime), not
"now" — re-parsing is not re-fetching, and must not make old data look fresh.

## Test fixtures

`tests/fixtures/real_yedion/` holds real yedion pages used to test the parser.
They came from a public instance of the **same yedion software** at a different
college (Tel Aviv-Yaffo Academic College), not from Braude. The page structure
is identical, but on a first real run it is worth diffing what lands in
`data/raw/` against these fixtures to confirm the parser caught everything.
