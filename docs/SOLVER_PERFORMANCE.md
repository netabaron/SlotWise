# /api/solve on first-year semesters — measurements

2026-10-20. Why first-year selections ended in HTTP 500 on the hosted site, what
the solver did, and what changed. The decision is in docs/DESIGN.md →
"Solver: exact pruned search".

**How it was measured.** All on the maintainer's machine, against the shipped
catalog (`data/catalog/catalog.jsonl`, built 2026-10-18T02:06:49Z, 574 courses),
served the way the hosted image serves it: `wsgi.app` (`mode: hosted`,
`allow_network=False`) with an **empty** `SLOTWISE_DB_ROOT`. Each case used the
Flask test client and ran in its own subprocess with a hard kill at 60 s.

"page" means the request body exactly as `app.js` `buildSolveBody()` builds it
when the student changes nothing: `target_days: 6`, no ranking,
`allow_soft_conflicts: true`, and `attendance` false for every kind whose
`from_yedion` is false (`attendanceDefault()`). In practice that is every kind.
"required" is the same body with no `attendance` at all, so every overlap is hard.

---

## 1. Before: time per `/api/solve`

### Year 1, semester א — the courses the page ticks by default

Groups are lecture/tutorial/lab/other counts that survive filtering.

| Programme | Courses (credits) | Largest components | Raw product | page | required |
|---|---|---|---|---|---|
| Civil | 6 (21.5) | 11001 6/10 · 11003 6/10 · 421208 2/2/5 | 2,592,000 | **timeout** | 5.3 s |
| Biotech | 7 (19.0) | 11001 6/10 · 11003 6/10 · 251961 9 | 2,332,800 | **timeout** | 3.8 s |
| Electrical | 5 (17.5) | 11002 4/6 · 11004 4/7 · 31230 3/5 · 31511 3/5 · 251961 9 | 1,360,800 | **timeout** | 12.1 s |
| Mechanical | 4 (13.0) | 11001 6/10 · 11003 6/10 · 251961 9 | 324,000 | **timeout** | 14.6 s |
| Industrial | 6 (16.0) | 11001 6/10 · 11003 6/10 · 51104 2/7 · 61903 2/2/5 | 54,432,000 | **timeout** | **timeout** |
| Info systems | 6 (19.0) | 11004 4/7 · 251961 9 | 8,064 | 0.90 s | 0.14 s |
| Software | 5 (16.5) | 11004 4/7 · 251961 9 | 8,064 | 0.67 s | 0.23 s |
| Math (winter) | 5 (16.0) | 11004 4/7 | 10,752 | 1.18 s | 0.20 s |
| Math (spring, sem 1 = ב) | 5 (16.0) | — | 36 | 0.07 s | 0.11 s |

"timeout" means killed at 60 s. Every later semester measured (3 and 5 of every
programme, 18 cases) took 0.07–2.5 s. The difference is not the number of
courses: biotech semester 5 has 9 courses and took 0.09 s. It is how many
groups each component offers. First-year service courses offer 6–10.

The frozen test fixture (`tests/fixtures/catalog`, built 2026-09-09) shows the
same pattern. Civil, biotech, electrical and industrial year 1 timed out (page);
mechanical took 18.1 s (page) and 3.0 s (required); industrial required took 12.0 s.

### Where the time went

One request ran the full enumeration at least three times: a count pass, one
viability probe per group, and the solve, which also scored every leaf.

| Case | count pass | viability | solve | total |
|---|---|---|---|---|
| Civil y1 page | 16.2 s / 864,000 leaves | 41.5 s / 1,829,048 (54 probes) | not reached by 60 s | >60 s |
| Electrical y1 page | 21.3 s / 1,360,800 | 35.8 s / 2,121,796 (46 probes) | not reached | >60 s |
| Mechanical y1 page | 1.5 s / 324,000 | 6.5 s / 584,643 (48 probes) | running at 60 s | >60 s |
| Industrial y1 required | 20.3 s / 599,556 | running at 60 s | — | >60 s |
| Mechanical y1 required | 0.55 s | 1.7 s | 12.3 s / 100,837 | 14.6 s |

* **Viability walked more than the whole tree.** It enumerated every leaf and
  discarded those without the group (`pins_satisfied`). For civil page mode,
  54 probes walked 1.83 M leaves out of 864,000.
* **In page mode almost nothing was pruned.** The only cut was `_pair_ok`
  (hard conflict or `linked_to`). With every component optional, every overlap
  is soft. Civil: of 1,238 candidate pairs, 60 overlap in time, but only 6 were
  blocked (66 when required), giving 864,000 leaves (9,284 when required).
  Mechanical: 0 of 961 blocked, the full Cartesian product of 324,000. Slot order
  is already most-constrained-first, and with nothing to cut it cannot help.
* **`top_n` did not limit the work.** `solve()` scored every leaf. Profile on
  mechanical y1 required: `score()` 64%, the periodic `_sort_key` re-sort 20%,
  the enumeration 17%. That is about 75 µs per leaf against 2–11 µs per node.

---

## 2. Before: what the student got

The chain in gunicorn 23.0.0's source:

1. `arbiter.py` `murder_workers`: a sync worker silent for `timeout` (30 s) is
   logged `WORKER TIMEOUT (pid:N)` and sent SIGABRT.
2. `workers/base.py` `handle_abort` calls `sys.exit(1)`, so `SystemExit` is
   raised inside the solver.
3. `SystemExit` is a `BaseException`, so the app's `@errorhandler(Exception)`
   never runs. Reproduced in the Flask test client: `SystemExit(1)` raised from
   the solve path escapes the app with no response. A `RuntimeError` at the same
   spot gives the app's own `500 application/json`.
4. `workers/sync.py` `except BaseException` calls `handle_error`, then
   `util.write_error`, which writes `HTTP/1.1 500 Internal Server Error`
   (`text/html`, `<h1><p>Internal Server Error</p></h1>`).
5. The page showed `app.errors.serverFault`, which said "השרת **המקומי**".

The page's `AbortController` cancels the fetch, but a sync worker cannot see
that, so each change by a first-year student cost 30 s of a worker.

In the Cloud Run logs this appears as three lines together: `WORKER TIMEOUT`,
`Error handling request /api/solve` with a traceback ending in `SystemExit: 1`,
and an access line `"POST /api/solve HTTP/1.1" 500 … 30.xs`.

---

## 3. After (same harness, same real catalog)

| Case | before | after |
|---|---|---|
| Civil y1 page | >60 s | 0.63 s |
| Biotech y1 page | >60 s | 0.40 s |
| Electrical y1 page | >60 s | 0.20 s |
| Mechanical y1 page | >60 s | 0.25 s |
| Industrial y1 page | >60 s | 1.93 s |
| Civil y1 required | 5.3 s | 0.58 s |
| Electrical y1 required | 12.1 s | 0.24 s |
| Mechanical y1 required | 14.6 s | 0.26 s |
| Industrial y1 required | >60 s | 2.32 s |
| All later semesters (18) | 0.07–2.5 s | 0.07–0.25 s |

Industrial year 1 is the slowest remaining case. Most of its time is the top-5
search (1.3–1.8 s) and, in required mode, viability (0.9 s). On the frozen
fixture every first-year case from §1 finishes in 0.35–0.99 s; that is what
`tests/test_solver_performance.py` holds, under 3 s.

None of these comes near the 20 s deadline (`SOLVE_DEADLINE_S`), which is a
safety net only.

**Exactness.** `tests/test_solver_exactness.py` compares the new solve with a
full enumeration copied from the old algorithm. It covers 10 selections × 8
preference sets: attendance on and off, per-kind and flat rankings, day targets
2–6, blocked windows, Friday, earliest/latest, custom and negative weights, and
`top_n` 1, 5 and 12. It checks the same schedules in the same order with the
same scores and breakdowns, the same minimum days, and the same viability with
its reasons. All 160 cases passed against the old solver before the change and
against the new one after.

In the scratchpad prototype that preceded it, on the 9 real-catalog cases where
the old solve finished, the top 5 was identical and viability had 0 mismatches.
