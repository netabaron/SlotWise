# Deploying SlotWise

How to run SlotWise as a hosted service: one process serving many students,
behind a real WSGI server.

This is **step 1: packaging**. It follows `HOSTING_NOTES.md` §2 (rebuild the
catalog on a cron instead of per-user scraping) and §4 (no server-side per-user
state, no new module-level globals). It does not add accounts, a database, or
cross-device sync — student state stays in `localStorage`, which is where
`HOSTING_NOTES.md` §3 argues it should stay.

For the local single-student app, nothing here applies: keep using
`python main.py`, which binds `127.0.0.1` and opens a browser.

---

## What a hosted instance does and does not do

**Does:** serve the catalog, solve timetables, render the UI.

**Does not:** fetch from the yedion. `wsgi.py` pins `allow_network=False`, and
`POST /api/scrape/start`, `GET /api/scrape/status` and `POST /api/reparse` have
been removed outright. That is deliberate and load-bearing:
`/api/scrape/start` had no authentication and no rate guard, so a hosted copy
was an open relay to Braude's server (`HOSTING_NOTES.md` §1, row 3). Rebuilding
the catalog is now a separate job — see [Rebuilding the catalog](#rebuilding-the-catalog).

The UI reflects this. The refresh button and the live scrape log are gone; in
their place the header shows one line, **"מעודכן מהידיעון · לפני 19 שעות"**,
with the exact timestamp and course count in its tooltip. It is fed by
`bootstrap.db.catalog_built_at` and `GET /api/catalog/meta`.

---

## Environment variables

Every variable is optional. Each falls back to the same path the local app
uses, so an instance with no configuration at all still starts.

The `SLOTWISE_*` rows are read by `create_app()` itself (`api.env_path` /
`api.env_float`), which means **`python main.py` honours every one of them
too**. Until 2026-09-20 they were read in `wsgi.py`, so they were a hosted-only
feature and a local run silently used the hardcoded defaults. `wsgi.py` now
passes exactly one setting of its own, `allow_network=False`, which is the one
thing that must not be configurable.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SLOTWISE_DB_ROOT` | `<app>/data/db` | The sections/catalog/details store. Read-only in practice for a hosted instance, but the directory must exist. |
| `SLOTWISE_CURRICULUM_PATH` | `<app>/data/curriculum.json` | Default study program (software engineering). |
| `SLOTWISE_CURRICULA_DIR` | `<app>/data/curricula` | One JSON per department. |
| `SLOTWISE_RAW_DIR` | `<app>/data/raw` | Raw scraped HTML. Unused when hosted — `reparse` is gone — but the setting still exists. |
| `SLOTWISE_MAX_AGE_HOURS` | `24` | Freshness window for course data. A non-numeric value raises at startup rather than silently defaulting. |
| `SLOTWISE_DETAILS_MAX_AGE_HOURS` | `168` | Freshness window for credits/prerequisites (7 days — they barely change). |
| `HOST` | `0.0.0.0` | Bind address. Used by `gunicorn.conf.py` and by `python wsgi.py`. |
| `PORT` | `8000` | Bind port, same two consumers. |
| `WEB_CONCURRENCY` | `2 × CPU + 1` | Gunicorn worker count. **Set this explicitly in a container** — see the note below. |
| `GUNICORN_LOGLEVEL` | `info` | Gunicorn log level. |

### The catalog path

The catalog lives in its own directory, and it is the nightly pipeline's only
output:

```
<app>/data/catalog/catalog.jsonl
<app>/data/catalog/catalog.meta.json
```

`SLOTWISE_CATALOG_DIR` moves it. The one wrinkle: `src/shipped_catalog.py`
reads that variable **at import time**, so it is not passed through
`create_app()` and is the one `SLOTWISE_*` name absent from the settings dict.
Setting it in the process environment before startup is what works — which is
what a container env var or a `docker run -e` does anyway. The Docker image
sets it to `/app/data/catalog` explicitly.

`SLOTWISE_DB_ROOT` is a different thing and does not move the catalog:
`SLOTWISE_DB_ROOT` is the *store*, the catalog is the base layer beneath it.

A wrong path is otherwise silent — `shipped_catalog` falls back to an empty
catalog, the app starts happily, and every course list is empty with no error.
`wsgi.py` therefore prints the resolved path and course count once at startup,
and warns when the count is zero. Check `docker logs` if courses go missing:

```
[slotwise] catalog: /app/data/catalog/catalog.jsonl (572 courses, built 2026-09-09T22:35:44Z)
```

`webapp.py` prints the same facts in its startup box, for the same reason plus
a local one: a server started days ago keeps listening on the same port, and
the browser shows what *that* process serves. Comparing the date in the box to
the date in the page header answers "which server am I looking at" without
guessing.

Both files are committed to git, so a fresh clone or a plain `docker build`
already has 572 courses and needs no volume at all. Mount over the directory
only when you want to serve a catalog newer than the image.

---

## Where the freshness date comes from

There is one source of truth: **`data/catalog/catalog.meta.json` → `built_at`**.
Everything the student sees about freshness reads it, and nothing reads
anything else.

* The header line `מעודכן מהידיעון · …` comes from
  `bootstrap.db.catalog_built_at`, which is `shipped_catalog.built_at()`. The
  same stamp drives the relative age, the exact date in the tooltip, and the
  warning colour — one value, three renderings, so they cannot disagree.
* `GET /api/catalog/meta` returns the same `built_at` — that is the whole
  point of the endpoint.

`data/db/sections.json` does **not** get a say, and this is the fix made on
2026-09-20. `Store._load_sections_db` merges the shipped catalog underneath the
local store, and the local store used to win unconditionally. A laptop that had
scraped the yedion weeks earlier therefore kept serving those records after a
`git pull` brought in a catalog built the same night, and the header reported
the old scrape date — `הנתונים עודכנו לאחרונה: 2026-09-01`. The hosted image
never showed this only because it has no `data/db` at all, so the difference
between local and hosted was a difference in *data*, not in code.

The merge rule is now **newer wins, per course code**: a local record survives
only when its `fetched_at` is at or after the catalog's `built_at`. Ties stay
local, a code the catalog does not carry stays local, and a hand-written entry
with no `meta` stays local. Everything else is served from the catalog, so
`git pull` is all it takes to refresh a local app.

It is opt-in — `Store(root, use_shipped=True, prefer_newer_catalog=True)` — and
`src/web/api.py` is the only caller that turns it on, exactly as it is the only
caller that turns on `use_shipped`. Both are display-layer policy. A plain
`Store(root, use_shipped=True)` keeps the original meaning of `use_shipped`
("the catalog fills in the rest, local always wins"), which is what
`refresh.py`'s change detection and `tests/test_shipped_catalog.py` depend on.

Because a record served from the catalog carries `fetched_at = built_at`,
`Store.freshness()`, `Store.is_stale()` and therefore `SLOTWISE_MAX_AGE_HOURS`
are all measured against the catalog build time. The separate 45-day
"catalog is old" banner is `CATALOG_STALE_DAYS` in `app.js` and is not
configurable.

### Rebuilding `data/db` from the shipped catalog

`data/db` is gitignored and is still where course *details* (credits,
prerequisites) live, which the catalog does not carry. One command rebuilds the
rest of it from whatever catalog `SLOTWISE_CATALOG_DIR` points at — by default
the one that was just pulled:

```bash
python scripts/seed_dev_data.py --force
```

`--force` is the point: without it the script leaves existing files alone and
prints `קיים, לא נגעתי`. It writes `sections.json`, `catalog.json`,
`details.json` (empty on purpose) and `tracked.json`.

Since the merge rule above, this is a convenience rather than a requirement —
the app serves the fresh catalog either way. Run it when you want `data/db` on
disk to match, or to get a clean clone into a working state. It is **not** a
substitute for `refresh.py`: the database it writes holds what the catalog
holds and nothing more.

---

## Running locally with gunicorn

```bash
python -m pip install -r requirements.txt
gunicorn -c gunicorn.conf.py wsgi:app
```

Then open <http://127.0.0.1:8000>.

**Gunicorn does not run on Windows** — it needs `fcntl`. It installs there
without complaint and then fails at startup. On Windows use either the local
app (`python main.py`) or the WSGI dev server:

```bash
python wsgi.py           # werkzeug on HOST:PORT, defaults to 0.0.0.0:8000
```

`python wsgi.py` is a convenience for checking that the hosted configuration
builds. It is a development server; do not put it in front of students.

### Why the gunicorn settings are what they are

`gunicorn.conf.py` carries the full reasoning. The short version:

- `POST /api/solve` is **CPU-bound and can take about a second** (measured
  2026-09-15: 4 courses 73 ms, 6 courses 735 ms, 8 courses 1.76 s, worst case
  1.9 s). It is exhaustive backtracking with no I/O, so it holds the GIL for
  its whole run. Hence sync workers, and enough of them.
- `preload_app = True` parses the catalog once in the master and shares it
  copy-on-write across forks, instead of once per worker.
- `timeout = 30` is ~15× the measured tail; `graceful_timeout = 10` is
  comfortably above it, so a deploy does not cut a solve off mid-flight.

The UI calls `/api/solve` on every preference change. If you see workers
saturating, debounce on the client before adding workers.

### Set `WEB_CONCURRENCY` in a container

The `2 × CPU + 1` default is computed from the CPUs this process can see.
`gunicorn.conf.py` uses `os.sched_getaffinity` where available, so an affinity
mask is respected — but **a CFS quota (`--cpus=1.5`) is invisible to it**. On a
quota-limited host the default still reads the host's core count, and a 2-CPU
container on a 64-core machine would start 129 workers.

Set it explicitly whenever the host constrains CPU:

```bash
docker run -e WEB_CONCURRENCY=5 --cpus=2 ...
```

On this development machine (22 cores) the default computes to **45 workers**,
which is far more than this app needs. Treat the formula as an upper bound, not
a recommendation.

---

## Docker

```bash
docker build -t slotwise .
docker run --rm -p 8000:8000 slotwise
```

With configuration:

```bash
docker run --rm -p 8000:8000 \
  -e WEB_CONCURRENCY=4 \
  -e SLOTWISE_MAX_AGE_HOURS=48 \
  slotwise
```

Serving a catalog built after the image was:

```bash
docker run --rm -p 8000:8000 \
  -v /srv/slotwise/catalog:/app/data/catalog:ro \
  slotwise
```

That is the whole override now that the catalog has its own directory: one
directory holding `catalog.jsonl` and `catalog.meta.json`. Mount the two files
individually if you prefer, but do **not** mount over `/app/data` itself — that
hides `curriculum.json`, `curricula/` and `programs.json`, and those features go
quiet rather than crashing, which is exactly the failure that is easy to miss.

The image installs `requirements.txt` only. Playwright and its ~400 MB of
browser binaries are in `requirements-scraper.txt` and never enter it.
`.dockerignore` also keeps out `data/raw/` (16 MB), `data/db/` (21 MB),
`data/.browser_profile/` (29 MB of **live session cookies**),
`data/profile.json` (one student's identity), `tests/` and the shnaton PDFs.

Excluding `data/db/` is deliberate, not just a size win. `Store` lays
`data/catalog/catalog.jsonl` down as a base layer beneath the store, so an image with an
empty `data/db` still serves all 572 courses — verified 2026-09-16. The
Dockerfile creates the empty directory because `Store` builds its paths at
construction time and a missing directory is a startup failure.

The container runs as the non-root user `slotwise` (uid 10001) and has a
`HEALTHCHECK` that polls `/api/catalog/meta`.

---

## Rebuilding the catalog

This is the half of hosting that replaces per-user scraping. Run it **outside**
the API image, on a schedule, and publish the result where the API reads it.

```bash
pip install -r requirements.txt -r requirements-scraper.txt   # scraper deps optional, see below
python build_catalog.py --year 2027 --out data/catalog
python scripts/verify_catalog.py --dir data/catalog --year 2027
```

`build_catalog.py --help` documents its exit codes, and CI depends on them:
**0** ok · **1** a validation gate failed · **2** unexpected error · **3** the
yedion throttled us · **4** the public endpoint is gated behind a login wall.
In every non-zero case the output files are left untouched.

`--check` runs the gates against whatever is already on disk, without network
and **without writing**. (It used to write when the gates passed, which was as
surprising as it sounds; fixed 2026-09-16.)

Facts that shape the schedule:

- The default fetch path (`src/yedion_http.py`) is **standard library only** and
  **needs no login** — `S_LOOK_FOR_NOSE` answers an anonymous GET
  (`docs/GROUND_TRUTH.md` §9, re-verified 2026-09-16). So the normal build needs
  nothing from `requirements-scraper.txt`; install it only if you want the
  `--browser` fallback.
- It is paced at **9 s/request**, so a full 572-course build takes **~86
  minutes**. The measured throttle is ~400 requests/hour. Do not parallelise it.
- The build is gated and atomic: a partial or throttled scrape is **not**
  written, and the previous catalog stays in place. A failed rebuild leaves a
  working instance serving slightly older data, which is the correct outcome.
- The academic year is session state, not a URL parameter. `open_session()`
  runs the required warm-up → `ChangeYear` → verify sequence. A bare GET
  silently returns **last year's data** — confirmed 2026-09-16.

Then copy `data/catalog/catalog.jsonl` and `data/catalog/catalog.meta.json` to
wherever the API instances mount them, and restart or redeploy. Because
`preload_app = True`, the catalog is read at master startup, so a running
instance will not pick up a new file until it restarts.

`refresh.py --install-task` registers a **Windows** scheduled task and is a
local maintainer tool. On a Linux host use cron, a systemd timer — or the
GitHub Actions pipeline below, which is what actually runs now.

---

## The nightly pipeline

`.github/workflows/build-catalog.yml` is the cron job `HOSTING_NOTES.md` §2
describes: the maintainer command with a different trigger. It reuses the paced
fetch loop, the throttle guard, all six validation gates and the atomic write
unchanged — only the trigger and the destination moved.

**Schedule: `cron: "0 23 * * *"`, enabled 2026-09-18.** 23:00 UTC is 02:00 IDT
in summer (UTC+3) and 01:00 IST in winter (UTC+2). Israel has no fixed UTC
offset and GitHub cron has no DST, so one expression cannot mean 02:00 all
year; both land in the quiet hours, which is the property that matters.

Both questions that kept it disabled are now answered:

1. **Does Braude answer a GitHub datacenter IP?** **Yes.** Runs `35262996905`
   and `35284235638` each fetched 571/571 course pages with zero failures, at
   9 s/request over ~100 minutes.
2. **Would a fresh catalog turn CI red?** **No**, not since the suite was
   decoupled from the shipped catalog. Tests read the frozen
   `tests/fixtures/catalog`; only `test_catalog_invariants.py` looks at
   `data/catalog/`, and it asserts invariants rather than pinned values.

### What the first two runs taught

Both failed, and each failure was worth having.

**Run 1** died on validation gate 4 after 1h39m. The college had withdrawn
course 51961, and the gate's course-loss half had **zero** tolerance while its
meeting-retention half allowed 5% — so one withdrawal in 572 failed the build.
The gate now separates a *regression* (a course the yedion still lists that we
failed to produce — fails) from a *withdrawal* (a course it no longer lists —
reported, does not fail).

**Run 2** passed all six gates, built a valid catalog, committed it on the
runner — and died at `git push`. The cause was not the catalog: a fresh
checkout of this repo was **already dirty**. `.gitattributes` declared
`tests/fixtures/real_yedion/*.html` as `eol=lf` while the stored blobs held
CRLF, so git rewrote them on checkout, and `git rebase` refuses to run with
unstaged changes. `--autostash` turned that into a misleading "stash apply
conflicted" at the very end of a 100-minute build.

Both are fixed: the blobs were renormalised to LF (a fresh clone is clean
again), and the commit step now runs `git checkout -- .` after committing the
two catalog files, so it no longer depends on the tree being pristine.

**What a run does:**

1. `refresh.py --catalog-only` — **one** request (`S_LOOK_FOR_NOSE_AB` returns
   the whole catalog) to build `data/db/catalog.json`, the index of which course
   codes exist this year.
2. `build_catalog.py --year 2027 --out data/catalog` — the paced fetch
   (~86 minutes), the parse, the six gates, the atomic write.
3. `scripts/verify_catalog.py` — checks the *artifact* rather than the build.
4. Commits and pushes the two files **only if they changed**; otherwise the run
   ends quietly.

The log is uploaded as an artifact on every run, pass or fail, and kept 14 days.

**Why step 1 is not optional.** `build_catalog.py` reads `data/db/catalog.json`
to learn which codes to fetch, and `data/db/` is gitignored — so on a clean CI
checkout that index is empty, every coverage ratio divides by zero, and gate 2
fails before a single page is fetched. Verified 2026-09-16. Seeding the index
from the committed catalog instead would work, but would freeze the course list
at whatever it was the day the pipeline was written, so a genuinely new course
could never appear.

**`concurrency: nightly-catalog`, `cancel-in-progress: false`.** Two builds must
never overlap against the college's server, and killing one halfway wastes an
hour of polite requests that were already served.

### Triggering a build by hand

GitHub UI: **Actions → nightly catalog build → Run workflow**. It takes `year`
(default `2027`) and `pace` (default `9`).

With the CLI:

```bash
gh workflow run build-catalog.yml -f year=2027
gh run watch
```

Do not lower `pace` to make it finish sooner. 9 s/request is 400/hour, which is
exactly the measured ceiling.

### If Braude blocks datacenter IPs

**Expect this.** GitHub-hosted runners come from well-known cloud ranges, and
nothing about the anonymous endpoint promises they are welcome. The pipeline is
built so that this failure is loud and harmless rather than silent: the build
exits non-zero **without touching the output files**, the job goes red, and the
committed catalog keeps serving.

Read the exit code in the job log:

| Code | Meaning | What to do |
| --- | --- | --- |
| 3 | The yedion returned its throttle page | Re-run later. Do **not** lower `--pace`. |
| 4 | A request landed on the login gate | The public endpoint closed. Automation cannot fix this — see below. |
| 1 | A validation gate failed | The fetch worked but the result is not trustworthy. Read the gate report in the log. |

The fallback is the same command on a machine on a normal connection:

```bash
git pull
python refresh.py --catalog-only --year 2027
python build_catalog.py --year 2027 --out data/catalog
python scripts/verify_catalog.py --dir data/catalog --year 2027

git add data/catalog/catalog.jsonl data/catalog/catalog.meta.json
git commit -m "catalog: manual build $(date -u +%F)"
git push
```

That is byte-for-byte what the workflow runs — same gates, same atomic write,
same two files — so a hand-built catalog and a CI-built one are
indistinguishable downstream. If this becomes the normal path, comment out the
`schedule:` block so the job stops failing nightly, and keep `workflow_dispatch`
for when you want to try the runner again.

If the cause is code **4**, no amount of re-running helps: the college has
closed the anonymous endpoints, and the only remaining route is the Playwright
fallback (`refresh.py --browser`), which needs a visible window and a manual
Citrix login and therefore cannot run unattended anywhere.

---

## CI

`.github/workflows/ci.yml` runs on every push and pull request.

**`test`** — Python 3.12, installs `requirements.txt` + `requirements-dev.txt`
+ `requirements-scraper.txt` and the Playwright browser, seeds the gitignored
fixtures from the **frozen** catalog, then runs the whole suite. No tests are
excluded; see [Why CI installs Playwright](#why-ci-installs-playwright).

The seed step is not optional. `data/db/` and `data/profile.json` are gitignored
— correctly; they are college content and personal data — but part of the suite
needs them. Measured on a clean checkout 2026-09-16: **4 failures and 33
errors**, all `FileNotFoundError`, from `tests/test_multifaculty.py` (which
`copytree`s `data/db`) and `tests/test_web.py` (which reads `profile.json` for
its defaults). `scripts/seed_dev_data.py` builds a minimal store from the
catalog that *is* committed:

```bash
python scripts/seed_dev_data.py          # will not overwrite existing files
python scripts/seed_dev_data.py --force
```

It is useful outside CI too — it is the fastest way to get a new clone into a
runnable state without an hour of scraping. It is **not** a substitute for real
data: `details.json` is deliberately empty, because the catalog carries no
credits or prerequisites and inventing them would be worse than "unknown".

The script writes `data/profile.json` rather than copying
`profile.example.json` verbatim, and the difference matters.
`tests/test_web.py::test_bootstrap_carries_the_profile_defaults` opens with an
explicit anchor — `assert (want_semester, want_term) == (CURRICULUM_SEMESTER,
TERM)` — pinning the profile to **year 3, semester 5**, which is the
maintainer's own profile. `profile.example.json` is year 1, semester 1, and
rightly so: it is the example a new student copies. So the setup `.gitignore`
documents ("copy the example and edit it") produces a profile that fails that
test on any machine but the maintainer's. Verified 2026-09-16: `('1', 'א') ==
('5', 'א')` fails. The seed writes the anchor values and leaves the example
alone; `TEST_ANCHOR` in the script is the single place to update if that test's
anchor ever moves.

One other detail in that script is load-bearing and easy to get wrong: it seeds
**one semester** (`א` by default), not all of them. `Store` writes
`sections.json` filtered to a semester, and the catalog carries every semester
in the same file — 2167 groups against 1179 for semester א alone. Seeding all
of them roughly doubles the candidates per component, and since
`enumerate_selections` is an exhaustive enumeration, that blows up the search
space rather than merely slowing it: the first attempt here took the suite from
~6 minutes to over 40 before it was stopped (2026-09-16), which would have
blown the CI timeout. `--semester` overrides it if you need a different one.

**`docker`** — builds the image, runs the container, waits for the `HEALTHCHECK`
to report healthy, then asserts `GET /api/catalog/meta` returns 200 *and* that
the payload carries a non-zero `course_count`. A 200 with an empty catalog would
mean the image built but shipped no data: green CI, dead app. Nothing is pushed
to any registry.

### Why CI installs Playwright

Nine test modules open with `pytest.importorskip("playwright.sync_api")` at
module level. Without the package that raises **at import time**, so the entire
module is skipped and its tests are never collected — one `s` in the output and
nothing else. The first two CI runs looked green in 32 seconds while silently
not running 36 tests, including the eight colour-token tests `CLAUDE.md` calls
load-bearing.

So the `test` job installs `requirements-scraper.txt` and runs
`playwright install --with-deps chromium`, and there is no `--ignore` list any
more. A hand-maintained list of "the browser tests" is exactly what drifted out
of date — `test_settings_screen.py`, `test_fit_percentage.py` and
`test_theme_tokens.py` were browser-driven and not on it. The browsers launch
headless (`pw.chromium.launch()` with no arguments), so no display is needed.

A **Guard against silently skipped modules** step fails the job if fewer than
`MIN_TESTS` are collected. That is the backstop for this whole class of bug:
a module that skips at import collects zero tests and says almost nothing.
Raise the floor when you add tests; lower it only when you have deliberately
deleted some.

---

## The frozen test catalog

The test suite does **not** read `data/catalog/`. It reads a frozen copy at
`tests/fixtures/catalog/`.

**The problem this solves.** Dozens of tests pin values derived from the
catalog — the optimal schedule's days, per-course group counts, a lecturer's
name. `data/catalog/` is the nightly pipeline's output. Once that pipeline
runs, any real change at the yedion turns those tests red: not because the code
broke, but because a course gained a group. Measured, not predicted: rebuilding
from the current `data/raw` gives 61753 nine groups instead of eight, which
moves the best timetable from days `[1,2,3,4]` to `[1,3,4,5]` and fails
`tests/test_web.py::test_solve_returns_schedules_with_the_full_shape`.

**How it works.** `src/shipped_catalog.py` reads `SLOTWISE_CATALOG_DIR` at
import time, and `tests/conftest.py` sets it to the fixture at module level —
before pytest imports any test module. Every test that goes through
`shipped_catalog` (which is all of them, via `tests/catalog_source.py`) gets the
frozen data. Each run prints which catalog it used in the pytest header:

```
catalog: .../tests/fixtures/catalog/catalog.jsonl (572 courses, built 2026-09-09T22:35:44Z) [frozen fixture]
```

`scripts/seed_dev_data.py --fixture` builds `data/db` from the same frozen
catalog, so the store the tests run against is frozen too. CI passes
`--fixture` and also sets `SLOTWISE_CATALOG_DIR` at job level.

**The one exception.** `tests/test_catalog_invariants.py` is the only test that
reads `data/catalog/`, and it asserts **invariants only, never values**: the
catalog loads, has at least 400 courses, every record has `code` and a `groups`
list, at least one meeting has times, the meta carries a timestamp and a year,
the meta's counts and code list match the catalog beside it, and every line is
valid JSON. Nothing there can be broken by a course gaining a group; everything
there would be broken by a truncated or mismatched build. It loads
`shipped_catalog.py` as a separate module instance so it does not disturb the
global redirect.

### Re-pinning the tests on purpose

When the pipeline brings a real change you want the tests to describe:

```bash
python scripts/update_test_fixture.py --check --diff   # what would move
python scripts/update_test_fixture.py                  # copy it in
python -m pytest -q                                    # expect failures
```

The failures are the point — read each one, update the pinned values to what
the data now says, and **commit the fixture and the test edits together**. A
commit that updates the fixture without the values leaves `main` red; one that
updates the values without the fixture is not reproducible.

`--diff` reports which courses changed group counts, which is the change that
actually moves pinned schedules — a course gaining a group shifts the optimal
timetable without changing any visible total.

Do **not** run it to make a red test green. If you did not update the fixture,
the data did not move; the code did, and the test is doing its job. The nightly
pipeline never runs this script — if it did, the whole separation would be
worthless.

---

## Health check and smoke test

`GET /healthz` is the liveness probe, and it is deliberately stricter than "the
port is open":

```bash
curl -si localhost:8000/healthz
```

```json
{"ok": true, "course_count": 572, "built_at": "2026-09-09T22:35:44Z",
 "catalog": "/app/data/catalog/catalog.jsonl"}
```

**200 only when a catalog is actually loaded; 503 otherwise.** The failure it
exists for is a wrong `SLOTWISE_CATALOG_DIR` or a volume that did not mount: the
server starts happily, every request returns 200, and every course list is
empty. A probe that only checked the port would call that deployment healthy. It
reports which path it looked at, because "empty" without "empty *where*" is not
enough to fix a deployment.

Both `railway.json` and the Dockerfile's `HEALTHCHECK` use it.

For catalog detail:

```bash
curl -s localhost:8000/api/catalog/meta
```

```json
{"ok": true, "built_at": "2026-09-09T22:35:44Z", "age_hours": 163.8,
 "age_text": "לפני 6 ימים", "course_count": 572, "year": "תשפ\"ז",
 "year_gregorian": "2027", "source": "shipped", "empty": false}
```

`source` is `"shipped"` for the catalog that ships with the code and `"db"` for
a locally fetched one. `course_count: 0` or `empty: true` means the catalog did
not load — check that `data/catalog/catalog.jsonl` is where the app expects it,
and read the `[slotwise] catalog:` line the process prints at startup.

---

## Railway + Cloudflare setup

Target: `slotwise.co.il`, served by Railway from the Dockerfile, with Cloudflare
in front. `railway.json` pins the build and the health check; everything below is
console configuration that does not live in the repo.

### 1. Railway service

Point a service at this repo. `railway.json` does the rest:

```json
{ "build":  { "builder": "DOCKERFILE", "dockerfilePath": "Dockerfile" },
  "deploy": { "healthcheckPath": "/healthz", "healthcheckTimeout": 60,
              "restartPolicyType": "ON_FAILURE", "restartPolicyMaxRetries": 5 } }
```

**Do not set `PORT`.** Railway injects it, and `gunicorn.conf.py` binds
`0.0.0.0:$PORT` — verified: with `PORT=7777` the computed bind is
`0.0.0.0:7777`. Setting it by hand is how you bind the wrong port and fail the
health check.

### 2. Environment variables to set on Railway

Everything is optional except `WEB_CONCURRENCY`, which you want explicitly
because the default is computed from CPUs the container may not actually have.

| Name | Value | Why |
| --- | --- | --- |
| `WEB_CONCURRENCY` | `4` | **Set this.** The `2 × CPU + 1` default reads the host's cores, not the container's quota — on a big host it would start dozens of workers. Raise it only if `/api/solve` queues. |
| `SLOTWISE_CATALOG_DIR` | `/app/data/catalog` | Already set in the Dockerfile; set it here only if you mount a catalog elsewhere. |
| `GUNICORN_LOGLEVEL` | `info` | `warning` if the access log is noisy. |
| `SLOTWISE_MAX_AGE_HOURS` | `24` | Default. Only change it if the catalog is deliberately stale. |
| `TZ` | `Asia/Jerusalem` | Cosmetic — makes container log timestamps readable. |

Do **not** set `HOST`, `SLOTWISE_DB_ROOT`, `SLOTWISE_CURRICULUM_PATH`,
`SLOTWISE_CURRICULA_DIR` or `SLOTWISE_RAW_DIR` unless you are mounting a volume:
the image defaults are correct, and `allow_network` is pinned `False` in
`wsgi.py` and cannot be turned on by configuration.

### 3. Cloudflare DNS

Railway gives the service a domain like `slotwise-production.up.railway.app`.
Add its target in Cloudflare's DNS tab:

| Type | Name | Target | Proxy |
| --- | --- | --- | --- |
| CNAME | `@` | `<service>.up.railway.app` | **Proxied** (orange cloud) |
| CNAME | `www` | `<service>.up.railway.app` | **Proxied** (orange cloud) |

Cloudflare flattens the CNAME at the apex, so `@` as a CNAME is fine there even
though plain DNS forbids it. Add both `slotwise.co.il` and
`www.slotwise.co.il` as custom domains on the Railway service too, or Railway
will not answer for them.

### 4. Cloudflare SSL

**SSL/TLS mode: Full (strict).** Railway serves a valid publicly-trusted
certificate on its own domain, so strict verification succeeds and there is no
reason to accept less.

- *Flexible* would make Cloudflare talk plain HTTP to Railway — the connection
  the student sees would be encrypted and the one carrying their data would not.
- *Full* without strict accepts any certificate, including one an attacker
  presents.

Also switch on **Always Use HTTPS**. `wsgi.py` trusts `X-Forwarded-Proto` from
one hop, so the app sees `https` correctly once that is on.

### 5. Caching at the edge

The app already sends the right headers:

| Response | `Cache-Control` |
| --- | --- |
| `/static/*` | `public, max-age=86400` |
| `/api/catalog/meta`, `/api/catalog/search`, `/api/catalog/browse`, `/api/semester/<n>/courses`, `/api/program/electives` | `public, max-age=300` |
| `/` | `no-cache` |
| `/api/bootstrap`, `/api/courses`, `/api/solve`, `/healthz`, any error | `no-store` |

Two things to know:

**Cloudflare does not cache `/api/*` by default.** Its default rules key on file
extension, so those `max-age=300` headers are honoured by browsers but ignored
by the edge until you add a Cache Rule — match `starts_with(http.request.uri.path, "/api/")`
and set *Eligible for cache*, respecting origin TTL. Without that rule nothing
breaks; you simply get no CDN caching.

**Static filenames are not content-hashed.** `/static/app.js` is a fixed path,
so a deploy replaces the content behind the same URL and a returning visitor can
run up to a day of stale JavaScript. `/` is `no-cache` so the page itself is
always fresh, but it references the same asset paths. Purge the Cloudflare cache
after a deploy that changes frontend assets, or accept the delay. The durable
fix is hashed filenames, which the app does not do today.

### 6. Smoke test after DNS propagates

```bash
# 1. Health, through the whole chain. Expect 200 and course_count > 0.
curl -si https://slotwise.co.il/healthz | head -20

# 2. Cloudflare is actually in front (expect a cf-ray header and server: cloudflare)
curl -sI https://slotwise.co.il/healthz | grep -iE "^(server|cf-ray|cf-cache-status)"

# 3. HTTP redirects to HTTPS (Always Use HTTPS)
curl -sI http://slotwise.co.il/ | grep -iE "^(HTTP|location)"

# 4. www resolves the same way
curl -si https://www.slotwise.co.il/healthz | head -5

# 5. The page renders and carries the freshness line
#    (#catalog-built was removed on 2026-09-20 -- one line now, not two)
curl -s https://slotwise.co.il/ | grep -c "freshness-text"

# 6. Cache headers survive the edge
curl -sI https://slotwise.co.il/api/catalog/meta | grep -i cache-control   # public, max-age=300
curl -sI https://slotwise.co.il/static/app.js    | grep -i cache-control   # public, max-age=86400

# 7. A solve really runs end to end (expect ok:true and a schedules array)
curl -s -X POST https://slotwise.co.il/api/solve      -H 'content-type: application/json'      -d '{"codes":["61753","61756"],"semester":"א","top_n":3}' | head -c 300

# 8. The removed scrape surface is still gone (expect 404 on all three)
for p in /api/scrape/start /api/scrape/status /api/reparse; do
  echo -n "$p -> "; curl -s -o /dev/null -w '%{http_code}
' "https://slotwise.co.il$p"
done
```

Then check the Railway logs for the startup line, which names the catalog the
process actually loaded:

```
[slotwise] catalog: /app/data/catalog/catalog.jsonl (572 courses, built 2026-09-09T22:35:44Z)
```

and confirm the access log shows **real client IPs** rather than one repeated
internal address — that is `ProxyFix` doing its job. If every line shows the
same address, `X-Forwarded-For` is not arriving and the trust setting needs
revisiting.

---

## Known gaps

Honest list of what this step does **not** settle.

1. **Python version.** The Dockerfile pins `python:3.12-slim`, as specified.
   The project is developed and tested on **3.14** (`docs/SPEC.md` says "Python
   3.14, Windows"; the README says 3.10+). The code is conservative — `from
   __future__ import annotations` throughout, `X | Y` unions, no 3.13+ syntax
   found — so 3.12 should be fine, **but the suite has not been run under 3.12
   here.** Do that before trusting the image in production, or move the base to
   `python:3.14-slim` to match the tested interpreter.
2. **`pymupdf` is in the API image.** It looks scraper-only and is not.
   `GET /api/program/electives` reads `data/curricula.json`, but reaches it via
   `from shnaton import load_curricula`, and `src/shnaton.py` imports `pymupdf`
   at module level. The import sits in a `try/except`, so dropping it does not
   crash — the endpoint silently returns `available: false` and the electives
   section disappears. ~20 MB for a feature that silently vanishes; the comment
   in `requirements.txt` says so at the point of decision.
3. **No per-instance rate limiting.** Nothing throttles `/api/solve`, and it is
   the expensive endpoint. Put a rate limit in the reverse proxy.
4. **No HTTPS, no reverse proxy config.** Gunicorn binds plain HTTP; terminate
   TLS in front of it.
5. **Catalog updates need a restart** (see `preload_app` above).
6. **`needs_scrape` still appears in API responses** as a per-course flag
   meaning "this course has no stored data". The name is a leftover from the
   scrape era and is now misleading, but it is load-bearing for the frontend and
   for tests, so renaming it was out of scope here.
7. **The nightly build has run twice, both times failing at a different late
   step, and both causes are fixed** (see "What the first two runs taught").
   The schedule is enabled as of 2026-09-18, so the next unattended run is the
   first genuine end-to-end test. Everything in it was exercised locally —
   the CLI, `--out`, the exit codes, the gates, `verify_catalog.py` — but the
   workflow itself has not executed on a runner even once, and a GitHub-hosted
   runner has never been pointed at the yedion. Whether Braude answers a
   datacenter IP at all is **unknown**; see
   [If Braude blocks datacenter IPs](#if-braude-blocks-datacenter-ips). Treat
   the first scheduled run as the real test, and watch it.
8. **The nightly job pushes to `main`.** It commits `data/catalog/*` as
   `github-actions[bot]` with `permissions: contents: write`. If `main` ever
   gets branch protection, this job needs an exemption or it will start failing
   at the push step, after having done a full hour of fetching.
9. **`scripts/seed_dev_data.py` is not real data.** It gives CI a store with an
   empty `details.json`, so anything depending on credits or prerequisites is
   exercised only through the "unknown" path there. The suite passes on it, but
   it is thinner than the maintainer's local `data/db`.
10. **Docker CI is unverified locally.** Docker is not installed on the
    development machine, so the `docker` job — and the image itself — has only
    ever been reasoned about, never built. The first CI run is its first real
    test.
