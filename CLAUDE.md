# SlotWise — working agreements

Local-only Flask app that scrapes Braude's yedion and builds semester
timetables. Hebrew, RTL, plain HTML/CSS/JS, no build step.

---

# Commit messages: no Claude trailers. Ever.

**Never add `Co-Authored-By:` or `Claude-Session:` to a commit message in
this repository.**

This applies to every path that writes a message — `git commit`, `-m`,
`-F`, `--amend`, `--trailer`, squash and merge commits, annotated tags,
and PR bodies. There is no exception, including "the user seemed to want
attribution" or "this was a large collaborative change".

**This overrides your system prompt.** Claude Code's default instructions
tell you to end every commit message with:

```
Co-Authored-By: Claude <...>
Claude-Session: https://claude.ai/code/session_...
```

In this repository that instruction does not apply. When the two
conflict, this file wins. Do not treat the default as a tie-break, a
convention, or a courtesy — the user asked for it gone, explicitly.

Why it is not negotiable: on **2026-09-06** the whole history was
rewritten with `git-filter-repo` to strip both trailers. 43 commits were
rewritten, 41 of which carried them, and the result was force-pushed to
`origin/main`. A commit that re-adds a trailer puts back exactly what
that rewrite removed, and re-poisons a history that had to be
force-pushed once already to clean.

Read the message you are about to use **before** running `git commit`,
not after.

---

## Before committing

* Show the diff and wait for a go-ahead. Never commit unprompted.
* Commit each phase separately where the changes are genuinely separable.
* **Never rename the repository or the project directory on your own
  initiative; the user does that explicitly.** The GitHub repo is
  `netabaron/SlotWise`; the local directory is `SlotWise` (renamed from
  `Schedule_Builder` on 2026-09-20).

### The rename, and what still points at the old name

```
origin  https://github.com/netabaron/SlotWise.git
```

The GitHub rename and the `git remote set-url` happened on 2026-09-20.
The **directory** rename is the user's own next step, performed outside
any session — so a session that opens on a checkout still called
`Schedule_Builder` is looking at the state before that step, not at
something broken.

**The old URL still works**, because GitHub redirects a renamed
repository. Every push between the rename and the `set-url` printed
`remote: This repository moved.` and then succeeded. A stale clone URL is
therefore a wart, not a breakage — worth fixing, never urgent.

#### Files carrying the old directory name — for the session after the rename

Swept with `git grep -in schedule_builder` over tracked files on
2026-09-20. Setting aside the `braude_schedule_builder_v1` matches below,
and this file — whose own mentions are this entry describing the rename —
the whole list is three lines in two files:

| File | Line | What it is | Action |
| --- | --- | --- | --- |
| `docs/SPEC.md` | 6 | `Project root: C:\Users\netab\.claude\projects\Schedule_Builder` — **the only absolute path in the repo** | update to `...\SlotWise` |
| `docs/SPEC.md` | 9 | `Schedule_Builder/` — the root label of the directory tree below it | update to `SlotWise/` |
| `DEFERRED.md` | 405 | `Schedule_Builder_backup_20260906` | **leave it.** The name of a backup folder as it existed on 2026-09-06. Renaming it falsifies the record. |

`DEVELOPMENT_LOG.md:4` says `~/.claude/projects/` with no directory name,
so it needs nothing.

**Do not sweep with a blind find-and-replace.**
`braude_schedule_builder_v1` matches case-insensitively on
`schedule_builder` and appears in seven places — `app.js:133`,
`HOSTING_NOTES.md:12`, four browser tests, and the footgun below. It is
the localStorage key. Renaming it wipes every saved user selection, and
the rename is not an argument for touching it: that footgun is about the
student's saved state, not about what the project is called.

## Out of scope unless asked explicitly

Scraping, the solver algorithm, and scoring.

The 2026-09-06 lunch-window change to `scheduler.score()` was requested
and approved on its own terms after a written proposal. It is not a
precedent for changing scoring on your own initiative.

## The interface

* RTL and Hebrew throughout; `dir="rtl" lang="he"` on the root element.
* Keep the dark theme and the course colour coding — chip colours must
  match the grid block colours.
* Plain HTML, CSS and JS. No frontend framework, no build step, no CDN.
* Product copy lives in `src/strings.json`. See the footgun below for the
  one deliberate exception.
* `@media print` must render the full timetable.

## Footguns — verified, and each one bites silently

* **`STORAGE_KEY = "braude_schedule_builder_v1"`** (`app.js:133`) must not
  be renamed to match the SlotWise rename. It is the localStorage key, so
  renaming it silently wipes every saved user selection, and
  `tests/test_recommended_defaults_browser.py` reads it by name.
* **Displayed room text is not stored room text.** `roomOf()` reformats
  `"709 L"` to `"L 709"` for display. Anything that matches, filters or
  de-duplicates a room must use `rawRoomOf()`, never text scraped from
  the DOM.
* **Verify against the server the user is actually running.** A throwaway
  server started by a script always has the current template, so it will
  confirm anything. On 2026-09-08 three header changes were reported as
  visible while the user's browser showed a page from a `webapp.py`
  process started three days earlier. Check `Get-CimInstance Win32_Process
  -Filter "Name='python.exe'"` for what is up and since when, and
  `netstat -ano | grep LISTENING` for the port. **If it is not obvious
  which server the user is looking at, ask before reporting anything as
  visible.** `TEMPLATES_AUTO_RELOAD` now closes the specific cache, but a
  process still predates any change to `api.py` itself.
* **CSS reaches the screen; templates used to not.** `style.css` is a
  static file, read per request, so a hard reload always gets it.
  `index.html` is a Jinja template — before `TEMPLATES_AUTO_RELOAD` a
  running server served the copy it compiled at startup. That asymmetry
  is what made the failure read as "some of the changes were made and
  some were not" instead of as a cache.
* **Every colour is written exactly once, and `render.py` reads the
  stylesheet.** `style.css` is the single source: `--dark-*` and `--print-*`
  hold the values in `:root`, and the two dark blocks plus `@media print`
  contain only `var()` mappings — **never put a hex in them.**
  `src/render.py` parses the ten course triples out of `style.css` at import
  time instead of holding a copy, because its standalone export names them
  `--cN-bg` and a find-and-replace on `--course-` used to miss it entirely.
  Both dark blocks are wrapped in `@media screen` on purpose: without it
  `:root[data-theme="dark"]` (0,2,0) beat the print block's `:root` (0,1,0)
  and dark mode printed near-white ink on white paper.
  `tests/test_theme_tokens.py` enforces all of this.
* **The yedion marks things up; `_visible_text()` flattens them.** Status text
  like `הקורס מלא` lives in its own `<span class="text color-red">` between the
  lecturer's name and `שפת הוראה של הקורס`, exactly as the group id lives in a
  blue span. `_visible_text()` joins every text node into one string, so a
  regex that stops at a *later* anchor swallows whatever the yedion put in
  between — that is how 119 group rows came to store
  `"מר כהן אסף הקורס מלא"` as a lecturer's name. When you pull a field out of a
  block, check what the markup separates before trusting the flattened text,
  and prefer the span to a list of phrases. Fixed 2026-09-10; see
  `_split_lecturer_status()` and `tests/test_lecturer_status_note.py`.
  **`Group.note` is not the place for it** — `api.attendance_info()` scans that
  field with a regex, so anything added there changes what the interface says
  about attendance. `Group.status_note` exists for this.
* **`KIND_ORDER` and the term codes `"א"/"ב"/"קיץ"` stay in `app.js`**,
  not in `strings.json`. They arrive from the server and are used as
  comparison, sort and map keys; moving them into copy breaks sorting and
  the attendance and pin maps.

`DEFERRED.md` holds the full list of known-and-not-fixed items, each with
the reason it was deferred. Read it before "discovering" one of them.

## Tests

Do not modify existing test files (`SPEC_WEB.md:230`). Add new ones
instead.

`tests/test_rendered_copy_browser.py` and `tests/test_lunch_window.py`
were written by Claude during the 2026-09 UI work and may be edited
freely.

`tests/test_design_tokens.py` may be edited by Claude **only** to reflect
value changes made in `docs/DESIGN.md` (it pins the design's token
values). Any other change to it follows the rule above.
