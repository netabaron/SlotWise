# Deferred — things a phase found but did not fix

Anything noticed during the UI overhaul that belongs to a later phase, or to no
phase at all, gets written here the moment it is noticed. The point is that none
of it is rediscovered in Phase 9 as a surprise.

Format: what it is · where · which phase should own it · why it was not done now.

---

## Open

### `רכיב` still appears in server-generated text
**Where:** `src/strings.json` → `server.pins.kindMissing`, `server.pins.groupMissing`
are fixed, but the infeasibility reasons and suggestions built in
`src/web/api.py` (around the `reasons` / `suggestions` assembly) still use the
word in places, and `api.py:2343` / `api.py:3349` use `רכיב` in its *software
module* sense, which must NOT be renamed.
**Owner:** Phase 6 (empty and error states) — that phase rewrites the
infeasibility copy wholesale, so the terminology pass lands with it.
**Why not now:** Phase 1 changed only strings that were already extracted. The
remaining ones are interleaved with logic that Phase 6 rewrites anyway, and
touching them twice would mean reviewing the same lines twice.

### Duration formatting in the score panel
**Where:** `fmtSpan()` in `src/web/static/app.js`; call sites in the score panel,
the sticky bar, the schedule tabs and the overlap heading.
**Owner:** Phase 2 (the score).
**Why not now:** Phase 1 unified the *rendered* format on `H:MM` and removed the
one call site that glued `שעות` onto a clock string. Whether the score panel
should read `2:30 שעות` or `שעתיים וחצי` is a Phase 2 decision about how the
facts panel reads, so it is settled there rather than guessed at here.

### The staleness banner and the header both offer a refresh
**Where:** `#btn-refresh` in the header, and the banner's `עדכן נתונים` action.
**Owner:** unassigned — needs a product call.
**Why not now:** the brief asks for "one refresh button" *and* specifies a button
inside the banner. Both are implemented; the banner is now rare enough that the
common screen has exactly one. Flagged so it is a decision and not an oversight.

### `KIND_ORDER` and the term codes are displayed but are not copy
**Where:** `src/web/static/app.js`, the constants block.
**Owner:** nobody, by design.
**Why:** `"הרצאה"`, `"תרגול"`, `"מעבדה"`, `"פרויקט"`, `"שו״ת"`, `"אחר"` and
`"א"` / `"ב"` / `"קיץ"` arrive from the server and are used for comparison,
sorting and as keys into the attendance and pin maps. They are shown to the user,
so a reader will reasonably ask why they are not in `strings.json`. They cannot
be, until the server sends a stable id separate from the display label. Recorded
so the question is answered once.

---

## Closed

*(nothing yet)*
