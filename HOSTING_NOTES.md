# Hosting notes — what to keep cheap

Not a plan, not scheduled. Written 2026-09-07 so phases 6–9 don't quietly
make hosting expensive. Every claim below is from the code.

---

## 1. What assumes a single user

**The good news first: student state is already in the browser.** Course
selections, pins, attendance overrides, collapsed sections and theme all
live in `localStorage` under `STORAGE_KEY = "braude_schedule_builder_v1"`
(`app.js:133`, written at `:715`, read at `:724`). The server holds no
per-student state at all. That is the single most expensive thing to
retrofit, and it is already right.

What actually blocks hosting:

| # | assumption | where |
|---|---|---|
| 1 | **Localhost-only is a stated design rule, not a default** — "this server serves one person on one machine" | `webapp.py:54` (`HOST = "127.0.0.1"`), `src/web/__init__.py:13`, `api.py:32` |
| 2 | **One global scrape for the whole process**: a single log deque, a single state dict, a single thread | `api.py:3012`, `:3013`, `:3028` |
| 3 | **`/api/scrape/start` has no auth and no rate guard** — any request triggers a scrape against Braude. Hosted, that is an open relay to the college | `api.py:4703` |
| 4 | Scrape runs `refresh.py` as a **subprocess spawned from an HTTP request** | `_run_root_script`, `api.py:3352` |
| 5 | **`data/profile.json` is one student's identity** — program, year, term, selected courses — read as global app state, and its path is exposed | `api.py:1180`, `:4992` |
| 6 | One `data/db/` store per process; no per-user partition | `store.py:732-736` |
| 7 | `data/raw/` and `data/.browser_profile/` are per-machine directories | `.gitignore:9,65` |
| 8 | `tracked.json` is a single global "what to refresh" list | `store.py:735` |
| 9 | The Windows scheduled task is per-machine | Task Scheduler |

Rows 5–9 all dissolve if the catalog ships. Rows 1–4 are the real work,
and they are small: bind elsewhere, remove the scrape endpoint, delete
the globals.

## 2. Does catalog-in-repo help or hurt? — **Helps, and almost nothing is thrown away**

A server rebuilding a catalog on a cron *is* the maintainer command with
a different trigger. Reused as-is:

* the paced fetch loop (1 request / 9 s, under the measured ~400/hour)
* the throttle guard and the circuit breaker
* **all six validation gates**, including the non-regression check
* the `catalog.jsonl` + `catalog.meta.json` format — it becomes what the
  server serves
* atomic write-then-swap

Thrown away: **the destination and the trigger only** — `git commit`
becomes "write to the server's data dir", and "I run it" becomes cron.

It also removes the thing that *cannot* be hosted: per-user scraping.
Fifty students each fetching 571 pages is fifty times over a limit we
already measured being hit at ~400/hour.

**So: do the catalog work. It is the first half of the hosting work.**

## 3. Three decisions before hosting

**Credentials — measured 2026-09-07, not assumed. The answer is "none",
but the earlier wording here was wrong and worth stating precisely.**

The *site entry point* and the *course-search endpoint* behave
differently, which is why "the yedion needs a login" and "our fetch needs
no login" are both true:

| request | result |
|---|---|
| `fireflyweb.aspx` (no query) | **login page** — 21,727 bytes, `input type="password"`, "שם משתמש", "סיסמה" |
| `fireflyweb.aspx?prgname=S_LOOK_FOR_NOSE&arguments=-N61756` | **real results page** — 46,995 bytes, 12 group blocks, no password field |

Both fetched from a **fresh cookie jar with no credentials**. So the
correct claim is *"the course-search endpoint is readable without
logging in"* — **not** *"the yedion has no login"*, which is false.

`open_session()` obtains two cookies — `Yedion.MySession` (182 chars) and
`TS0188c6f2` (138 chars, the load balancer's). Both are **anonymous**:
the server issues them on first contact, nothing is sent to earn them.
They carry the academic-year selection, not an identity.

No credential is read anywhere in the codebase. The only `password` match
outside the login page itself is `src/scraper.py:951`, a Playwright check
for *whether a login form appeared* on the browser fallback.

Decision unchanged, and now on evidence: if the anonymous endpoint stays
sufficient, hosting has **no credential problem**. Keeping the
Playwright/Citrix fallback server-side would reintroduce one, and it
cannot run per-request.

**Selections — keep them in the browser.** They already are. Server-side
storage buys cross-device sync and costs accounts, a database, a privacy
posture, and a deletion story for a student's course list. Cheaper
middle: an export/import or a shareable link that encodes state in the
URL. Decide before Phase 9, because "save schedule" is in that phase and
would be the first thing tempted to write server-side.

**During a scrape — never block a request on it.** Today the UI streams
live log lines from that global state. Hosted, the rebuild is a
background job no user should see: serve the last known-good catalog
always, and let the header say when it was built. The validation gate
already guarantees a failed rebuild leaves the previous catalog in place.

## 4. What to avoid in phases 6–9

1. **No server-side per-user state.** No sessions, no server-stored
   selections. New UI reads client state, not `profile.json`.
2. **Phase 6's failure states should not assume the user can watch a
   scrape.** Design them around *"the catalog is old"*, not *"your
   refresh failed"* — a hosted user has no scrape of their own. This
   directly affects the `פרטים על התקלה` disclosure: it should show
   catalog build info, not a live scrape log.
3. **Don't promote refresh/reparse to core UI.** They are maintainer
   operations and will not exist for a hosted student.
4. **Phase 9 ICS export and "save schedule": build them client-side.** A
   per-user server endpoint that renders a file is exactly the dependency
   we are trying not to create.
5. **No new module-level mutable globals in `api.py`.** They are
   per-process, and a hosted process serves everyone at once.
6. Keep the solver pure. `scheduler.py` takes courses and preferences and
   returns schedules with no I/O — it scales to a server unchanged, and
   it is worth keeping it that way.

---

**Summary:** the browser already holds user state, the solver is already
pure, and the catalog work is the first half of hosting rather than a
detour. The remaining cost is four narrow things: the localhost rule, the
global scrape state, the unauthenticated scrape endpoint, and
`profile.json` as global identity.
