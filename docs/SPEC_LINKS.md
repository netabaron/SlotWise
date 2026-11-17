# SPEC — Study-program links and per-course syllabus PDFs

Status: **implemented.** Feature 1 in `362709e` (2026-11-16), Feature 2 in
`04eaaf7` (2026-11-17), both on `main`. The commit messages carry the full
detail; this file records what was decided and built.

---

## Feature 1 — Link to the program's study plan on the college site

* **`plan_url` is the department's B.Sc page**, not the plan itself. From
  תשפ"ז the plan is an HTML yearbook page under `shnaton-26-27/bsc/<x>/`,
  whose address changes every year; the department page has no year in its
  address and links to the current plan. All eight were checked by hand. The
  old `url` values (`bsc-programs/yedionbsc-*`) return 404 and are kept as
  they were.
* `_program_choices()` sends `plan_url` only when it is an http(s) URL.
* Under the program select: a small **blue-tinted button** (`.plan-link`,
  the existing `--info-*` tokens, not filled, so it does not compete with
  "המשך"), with a document icon and a new-tab icon. Shown only when the chosen
  program has a `plan_url` — never a dead link. Both math intakes share it.
  32 px hit area, focus ring, not printed.
* Copy: `ui.program.planLink`, `ui.program.opensInNewTab`.
* Tests: `test_program_plan_link.py`, `test_program_plan_link_browser.py`.

---

## Feature 2 — "סילבוס" button that opens the course's syllabus PDF

Syllabi are static PDFs at
`https://info.braude.ac.il/info/<year>/<code zero-padded to 7>.pdf`, with no
login, cookie or POST. How this was found and verified:
**`docs/GROUND_TRUTH.md` §10.**

### No request at click time

The server never fetches from Braude while answering a request. Which PDFs
exist is learned ahead of time and shipped as `data/catalog/syllabi.json`,
filled by `scripts/check_syllabi.py` (one HEAD per year and code, this year
and last), run from:

* the nightly `build-catalog.yml` — a "Check syllabi" step with a budget of
  150 checks per run;
* `check-syllabi.yml` — manual, for the first full pass and refills after a
  year rollover. Commits only `syllabi.json`.

`src/syllabus.py` has no network code; it reads `syllabi.json` and builds
URLs.

### `GET /api/syllabus/<code>`

| Case | Response |
| --- | --- |
| not 4–7 digits | 400 page (does not echo the input) |
| not in the catalog | 404 page with a link to the yedion |
| this year `exists`, or never checked (or no `syllabi.json`) | 302 to this year's PDF |
| this year `missing` | 200 course page |

A code that was never checked never says "no syllabus".

The course page shows the name, code and year, "not uploaded yet" with the
date of the last check, the course facts, a primary button to the yedion
course page, a **"לנסות לפתוח בכל זאת"** link to this year's PDF, and a
**"הסילבוס של שנה שעברה (תשפ"ו)"** button only when last year's PDF exists.
It follows the theme chosen in the app.

### The button

On every course card in both lists: a document icon plus the word "סילבוס",
in the top-left (RTL end) corner, `<a target="_blank" rel="noopener
noreferrer">`, title and aria-label "סילבוס הקורס {name} (PDF, נפתח בלשונית
חדשה)". 32 px hit area, focus ring, not printed; a click does not select the
card. Every URL comes from `syllabusUrl(code)`.

Copy: `server.syllabus.*`, `app.courses.syllabus`, `app.courses.syllabusTitle`.

Tests: `test_syllabus_endpoint.py`, `test_check_syllabi.py`,
`test_syllabus_catalog_urls.py`, `test_syllabus_page_browser.py`,
`test_syllabus_button_browser.py`.

---

## Out of scope

* Showing the syllabus text inside SlotWise.
* Storing syllabus PDFs in the repo or on the server.
* Any change to the timetable scrape, solver or scoring.
