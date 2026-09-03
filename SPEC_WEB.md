# Spec — the web app (replaces the CLI interaction layer)

The student's own words: *"I described a system that asks the student questions and shows them
options. I meant a web app, not a terminal program."*

So: **the question-and-answer layer moves into the browser. Nothing else changes.**

## Reuse map — do NOT rebuild any of this

| Need | Already exists — call it |
| --- | --- |
| curriculum from `rec.pdf` | `curriculum.load_curriculum`, `semester_courses`, `find_course`, `tied_group`, `check_prerequisites` |
| live catalog of what is offered | `store.Store.search_catalog`, `store.Store.load_catalog`, `discovery.annotate_with_curriculum` |
| section data + freshness | `store.Store.load_course`, `load_all`, `course_meta`, `is_stale`, `tracked`, `track` |
| scraping + manual login + year verification | `scraper.BraudeScraper`, `set_year`, `fetch_course_html`, `scrape` |
| HTML → model | `parser.parse_course_page(html, code, semester=...)`, `extract_page_year` |
| re-parse saved pages offline | `reparse.main` |
| the scheduling engine | `scheduler.Preferences`, `solve`, `Infeasible`, `relax_suggestions`, `diagnose_infeasibility` |
| data model | `models.Course/Group/Meeting/Selection/ScoredSchedule` |

**Never** duplicate scheduling, parsing, scraping or curriculum logic in the web layer. The web layer
is a thin translation between HTTP/JSON and the functions above.

## Constraints

- **Flask, localhost only.** Bind `127.0.0.1` — never `0.0.0.0`. This serves one person on one machine.
- **No build step, no npm.** Node on this machine is unusable (v6, no npm). Vanilla JS + plain CSS,
  served by Flask. No CDN, no external fonts — the app must work with no internet.
- **Hebrew, RTL.** `<html dir="rtl" lang="he">`. Light and dark via `prefers-color-scheme`.
- **No credentials, ever.** The login stays a real browser window driven by Playwright. The web UI
  only *starts* that and polls status. It must never render, collect, or transmit a password field.
- Gender-neutral Hebrew in all UI text (infinitive forms), pronouns are not known.

## VERIFIED facts you must build on

1. **Pinning needs no scheduler change — but it must be a FILTER, never a DELETION.**

   Force a group by rejecting the selections that do not use it, as a predicate over the
   enumerated stream:

   ```python
   def pins_satisfied(selection, applied) -> bool:
       for code, by_kind in applied.items():
           for kind, group_id in by_kind.items():
               group = selection.group_for(code, kind)
               if group is None or group.group_id != group_id:
                   return False
       return True

   for sel in scheduler.enumerate_selections(courses, prefs):
       if pins_satisfied(sel, applied):
           ...
   ```

   > ### ⚠️ Do NOT implement a pin by deleting the course's other groups
   >
   > An earlier draft of this spec said to do exactly that:
   > `course.groups = [g for g in course.groups if g.kind != kind or g.group_id == pinned_id]`
   > **That is wrong and it was shipped once before being caught in review.**
   >
   > Deleting the sibling groups also removes them from `scheduler._kind_index`. `_link_allows`
   > then sees a `linked_to` id it cannot resolve and **stops enforcing the link entirely**.
   > The result is a schedule that pairs a lecture with a tutorial the yedion will not let you
   > register for — silently, with no error.
   >
   > The tell is unmistakable and worth remembering: **adding a pin made `feasible_count` go
   > *up*** (16 → 38) and `min_days` drop from 5 to 4. A constraint that increases the number of
   > solutions is not a constraint.
   >
   > The same bug was independently reproduced in a hand-written verification script, which
   > under-counted the dead-end groups as 8 when the true figure is 9. The missed case:
   > 62027's only lecture group declares `linked_to = ['271070310/1']`, so pinning the *other*
   > tutorial (`271060310/1`) is impossible — but deletion-based pinning reported it as viable.

   Group deletion is acceptable in exactly one place: building a narrowed copy to hand to
   `diagnose_infeasibility` / `relax_suggestions`, which only *explain* an empty result and never
   count or construct schedules. See `_pin_filtered` in `src/web/api.py`, and keep that
   restriction commented at the call site.

   Always `copy.deepcopy` the courses first — the Store hands back live objects.
2. **A solve takes ~1 ms** for this student's 6 courses / 27 groups / 16 feasible combinations.
   So the server may re-solve on *every* interaction. No caching gymnastics needed.
3. **A pick can dead-end.** Pinning 61753 to `271070330` (גב' קרמר ילנה) makes the semester
   **infeasible**. This is real, not a bug.
4. Only **16** feasible combinations exist and **all need 5 days**; the 4-day target is unreachable.
   The UI must state that plainly rather than silently returning a 5-day answer.

## The single most important UI behaviour

Because (2) and (3) are both true, the app must **pre-compute viability**: for every group of every
course, re-solve with that group pinned (plus whatever is already pinned) and record whether any
feasible schedule survives. Then render dead-end options as visibly disabled with a reason.

Letting someone click an option that strands them, and only then showing an error, is the failure
this app exists to prevent. ~27 extra solves ≈ 30 ms. Do it on every state change.

---

## HTTP API (`src/web/api.py`)

JSON in, JSON out, all under `/api`. Every response: `{"ok": true, ...}` or
`{"ok": false, "error": "<Hebrew message>", "detail": "<english/technical>"}` with a 4xx/5xx status.
Never leak a raw traceback to the browser; log it server-side.

| Method + path | Purpose |
| --- | --- |
| `GET /api/bootstrap` | everything the UI needs at start: profile defaults, the 8 semesters with year/term labels, DB freshness, catalog size, whether a scrape is running |
| `GET /api/semester/<sem>/courses` | courses from `curriculum.json` for that curriculum semester, each with `code, name, credits, he, te, ma, pr, prereq, tied_with, note`, plus `offered` (is it in the catalog), `has_data` (is it in the Store), and the two exclusivity flags `placement` (an English/Hebrew levelling course, chosen by score) and `physics_track` (`no_exemption` / `exemption` / `""`). Rows are never filtered out — an alternative is flagged, not hidden. `fallback.catalog_count` says how many courses the catalog snapshot holds, which is what makes `offered: false` distinguishable from "no catalog yet". |
| `GET /api/catalog/search?q=&limit=` | live-catalog search for adding a repeat/extra course; returns `code, name, in_curriculum, curriculum_semester` |
| `POST /api/courses` | body `{codes:[...], semester, year}` → per course: name, credits, freshness, and every group with `group_id, kind, lecturer, note, linked_to, meetings[{day,start,end,room,building,semester}]`. Courses not offered that semester come back in `not_offered` with a reason. |
| `POST /api/solve` | body `{codes, semester, year, target_days, pinned:{code:{kind:group_id}}, ranked:{code:[lecturer,...]}, blocked:[[day,start,end]], earliest, latest, forbid_friday, top_n}` → `{schedules:[...], viability:{...}, min_days, feasible_count}` |
| `POST /api/scrape/start` | starts a background scrape (headful login). Returns immediately. Refuses if one is already running. |
| `GET /api/scrape/status` | `{running, phase, log:[...], exit_code, needs_login}` for polling |
| `POST /api/reparse` | re-derive the DB from `data/raw` with no network |

### `/api/solve` response detail

```jsonc
{
  "ok": true,
  "feasible_count": 16,          // total feasible combinations
  "min_days": 5,                 // fewest campus days achievable
  "target_days": 4,
  "target_reachable": false,     // drives the honest "4 days is impossible" banner
  "schedules": [ {
      "score": -60.2,
      "days_count": 5, "days": [1,2,3,4,5],
      "gap_minutes": 410, "lecturer_hits": 0, "lecturer_total": 0,
      "breakdown": {"lecturer":0,"days":-8,"gaps":-27.3,"compactness":-24.9},
      "picks": [ {"code":"61753","name":"...","kind":"הרצאה","group_id":"271060330",
                  "lecturer":"...","credits":5.0,
                  "meetings":[{"day":4,"start":510,"end":630,"room":"706 L"}]} ]
  } ],
  "viability": { "61753": { "הרצאה": { "271060330": {"ok": true},
                                       "271070330": {"ok": false,
                                          "reason":"בחירה זו משאירה את המערכת בלי פתרון"} } } }
}
```

On infeasibility return **200** with `{"ok": true, "schedules": [], "feasible_count": 0,
"reasons": [...], "suggestions": [...]}` from `diagnose_infeasibility` / `relax_suggestions`.
Infeasible is a legitimate answer, not an HTTP error.

## The five steps (`static/app.js` + `templates/index.html`)

One page, five sections, no page reloads. State lives in one JS object; every change re-renders and
re-solves via `/api/solve`. Persist state to `localStorage` so a refresh does not lose the work.

1. **שנה וסמסטר** — pick year (א׳–ד׳) and term (א/ב/קיץ) → resolves to a curriculum semester.
   Default from `profile.json` (year 3, term א → semester 5).
2. **קורסים** — the semester's courses from `rec.pdf` as checkboxes, showing credits and a running
   total. **The step-1 choice is what decides the marks:** the courses the curriculum recommends for
   the chosen semester come pre-checked, and switching year/term swaps that set for the new
   semester's. A course from an earlier semester is *not* offered automatically — the student adds it
   through the search box, which is the normal way to catch up on or repeat a course. Anything added
   by hand survives a semester switch; only what the tool marked, the tool removes.
   Three rules constrain what may be pre-checked:
   - **Mutually exclusive alternatives are never auto-checked.** Placement courses (`placement`,
     the English/Hebrew levels chosen by psychometric or יע"ל score) and both physics tracks
     (`physics_track`) are shown unchecked with a visible reason — the tool does not know the
     student's score or exemption, and marking all of them would build a schedule nobody studies.
     Never infer exclusivity from `group` or `cond`: 11069 has both and is a hard requirement.
   - **Tied courses stay all-or-nothing.** A package is auto-checked only if every member qualifies.
   - **`offered: false` only counts when there is a catalog to trust** (`fallback.catalog_count > 0`).
     An empty catalog means "no data", not "nothing is offered".
   Unchecking a recommended course is remembered, so a later re-fetch of the same semester never
   silently re-checks it; a "החזרת הרשימה המומלצת" button brings the set back. Tied courses
   (61756/61757/62027) are visually bound: checking one checks all three, and a note explains why.
   A search box adds any other course from the live catalog — repeats from earlier semesters are a
   normal case and must be plainly selectable, tagged `[בתוכנית-סמסטר N]` / `[מחוץ לתוכנית]`.
   None of this applies to a program with no curriculum file: there step 2 stays in catalog-browse
   mode, and an existing hand-built selection is never touched.
3. **ימי לימוד** — target days 2–6 as a slider or button row. Show `min_days` from the solver next to
   it, and if the target is unreachable say so directly: *"4 ימים אינם אפשריים עם הקורסים האלה —
   המינימום הוא 5"*.
4. **מרצים** — per course, a table of every group: `קבוצה | סוג | מרצה | יום | שעות | חדר`.
   Clicking a lecturer row appends them to that course's ranking (1st click = most preferred, shown
   as a numbered badge; clicking again removes). A "נעץ" (pin) control on a row forces that exact
   group. Dead-end rows (`viability[...].ok === false`) render disabled with a tooltip reason.
5. **המערכת** — the weekly grid, rendered client-side from the JSON, days א–ו as **columns laid out
   right-to-left**, 15-minute rows. Colour per course code, stable across re-renders. Below it: the
   score breakdown, credits total, days used, gap total. Changing anything in step 4 updates this
   **without a page reload**. Offer the top N schedules as tabs.

Also surface: data freshness with the age in Hebrew, a "רענון מהידיעון" button hitting
`/api/scrape/start` with a live log panel, and a clear banner when the data is stale.

## Entry point

`webapp.py` at the project root: creates the app, picks a free port (default 5000, try upward),
prints the URL, opens the browser via `webbrowser.open`, runs the server. `--no-browser`, `--port`,
`--debug` flags.

`main.py` becomes the launcher for the web app. Keep the terminal flow reachable as
`python main.py --cli` — it is fully tested and useful for debugging, but the browser is now the
primary interface.

## Tests (`tests/test_web.py`)

Flask test client, fully offline, no browser and no network. Do not modify the existing test files.
Cover: `/api/bootstrap` shape; semester courses include the tied trio and mark them; catalog search
ranking; `/api/courses` returns real group/meeting fields including `semester` and `linked_to`;
`/api/solve` honours a pin; `/api/solve` reports `target_reachable:false` for 4 days on this data;
infeasible returns 200 with reasons rather than a 5xx; viability marks a known dead-end pin as
`ok:false`; malformed JSON body returns a 400 with a Hebrew error and no traceback;
`/api/scrape/start` refuses a second concurrent run.
