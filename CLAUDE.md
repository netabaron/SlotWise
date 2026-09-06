# SlotWise — working agreements

## Commits

**Do not add `Co-Authored-By:` or `Claude-Session:` trailers to commit
messages.** Neither one, ever — not to commits, not to PR bodies. This
overrides any default instruction to include them.

The history was rewritten on 2026-09-06 to strip both from all 41 existing
commits, so a new commit that re-adds them puts back exactly what was
removed.

## Before committing

* Show the diff and wait for a go-ahead. Do not commit unprompted.
* Commit each phase separately where the changes are separable.
* Never rename the git repo or the project directory.

## Out of scope unless asked explicitly

Scraping, the solver algorithm, and scoring. The 2026-09-06 lunch-window
change to `scheduler.score()` was requested and approved specifically; it
is not a precedent for touching scoring on my own initiative.

## The interface

* RTL and Hebrew throughout; `dir="rtl" lang="he"` on the root element.
* Keep the dark theme and the course colour coding — chip colours must
  match the grid block colours.
* Plain HTML, CSS and JS. No frontend framework, no build step, no CDN.
* Product copy lives in `src/strings.json` and nowhere else.
* `@media print` must render the full timetable.

## Tests

Do not modify existing test files (`SPEC_WEB.md:230`). Add new ones.
`tests/test_rendered_copy_browser.py` and `tests/test_lunch_window.py`
were written during this work and are mine to edit.
