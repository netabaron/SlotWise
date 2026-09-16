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
their place the header shows **"הקטלוג נבנה ב-…"**, read from the new
`GET /api/catalog/meta`.

---

## Environment variables

Every variable is optional. Each falls back to the same path the local app
uses, so an instance with no configuration at all still starts.

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

### Not an environment variable: the catalog path

`data/catalog.jsonl` and `data/catalog.meta.json` are resolved by
`src/shipped_catalog.py` **relative to the project root, at import time**.
There is no override. They must live at:

```
<app>/data/catalog.jsonl
<app>/data/catalog.meta.json
```

In the Docker image that is `/app/data/`. Pointing `SLOTWISE_DB_ROOT` somewhere
else does not move them — `SLOTWISE_DB_ROOT` is the *store*, the shipped catalog
is the base layer underneath it.

Both files are committed to git, so a fresh clone or a plain `docker build`
already has 572 courses and needs no volume at all. Mount over that directory
only when you want to serve a catalog newer than the image.

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
  -v /srv/slotwise/catalog.jsonl:/app/data/catalog.jsonl:ro \
  -v /srv/slotwise/catalog.meta.json:/app/data/catalog.meta.json:ro \
  slotwise
```

Mount the two files, or mount a whole directory over `/app/data`. If you mount
the directory, it must also contain `curriculum.json`, `curricula/` and
`programs.json`, or those features go quiet — the app degrades rather than
crashing, which is exactly the failure that is easy to miss.

The image installs `requirements.txt` only. Playwright and its ~400 MB of
browser binaries are in `requirements-scraper.txt` and never enter it.
`.dockerignore` also keeps out `data/raw/` (16 MB), `data/db/` (21 MB),
`data/.browser_profile/` (29 MB of **live session cookies**),
`data/profile.json` (one student's identity), `tests/` and the shnaton PDFs.

Excluding `data/db/` is deliberate, not just a size win. `Store` lays
`data/catalog.jsonl` down as a base layer beneath the store, so an image with an
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
python build_catalog.py --year 2027
```

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

Then copy `data/catalog.jsonl` and `data/catalog.meta.json` to wherever the API
instances mount them, and restart or redeploy. Because `preload_app = True`, the
catalog is read at master startup, so a running instance will not pick up a new
file until it restarts.

`refresh.py --install-task` registers a **Windows** scheduled task and is a
local maintainer tool. On a Linux host use cron or a systemd timer.

---

## Health check and smoke test

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
not load — check that `data/catalog.jsonl` is where the app expects it.

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
