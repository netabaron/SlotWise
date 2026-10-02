# Proposal: full groups are excluded, except in the remembered schedule

**Not implemented. Decided 2026-10-02: deferred; the measurements stay here for a future decision.**

Written 2026-10-02. Line references are to commit `95be9df`, the code at the
time of writing. It replaces the penalty proposal from earlier the same day.
**A proposal only: no code has changed.** It touches the solver, which is out of
scope unless asked. You asked for this written proposal first.

## In short

* A group the yedion marks `הקורס מלא` cannot be registered for, so it is
  **never chosen**. There is one exception: a group in the student's
  **remembered schedule**, which is the alternative they last selected. I also
  recommend keeping groups the student had already **pinned**.
* The remembered schedule is a new field in the saved state. It is sent to
  `/api/solve` as a new field, `chosen`, with the same shape as `pinned`.
* The exclusion belongs **in the engine, as a filter on candidate groups**, the
  way earliest and latest hours already work. It should not be done by deleting
  groups in `api.py`: deleting groups switches off linked-group enforcement.
  `api.py` decides which groups are excluded and which courses are left out.
* Measured on the same 16 selections, **with no remembered schedule**:
  * 8 do not change.
  * Rule 4 leaves out 4 courses, in 3 selections.
  * **4 selections become "no possible schedule" for a reason rule 4 does not
    cover.** One of them is Software Engineering semester 5. There, no component
    is entirely full, but the open groups that remain clash with each other.
* **With today's #1 remembered**, no selection becomes infeasible, no course is
  left out, and #1 stays #1 in all of them.
* **Tests:** most of the protected browser tests would fail. They open Software
  Engineering semester 5 in a fresh browser, and that selection now has no
  schedule. Landing this needs your permission to edit them (§8).
  * I ran the suite with the exclusion switched on in memory, but Claude Code
    stopped it for low memory. The first half did finish. Most of its failures
    were browser crashes caused by the memory shortage. The clean ones confirm
    the pattern: 11 tests in `test_alternatives_browser.py` time out waiting for
    the alternative cards.

## 1. The rules, as I would implement them

These are your five rules, with the details the code forces:

* **The key is (course, kind, group id).** Group ids repeat across courses, and
  even across kinds of one course. For example, 31403 has lecture 271030310/1 and
  lab 271030310/1.
* **"Full" means `status_note` is exactly `הקורס מלא`.** `מיועד לחוזרים` and
  `בקורס זה קיימת רשימת המתנה` stay allowed.
* **Allowed full groups are the remembered schedule's groups**, plus, if you
  agree (decision 3), groups the student had already pinned.
* **Rule 4 as written tests each component.** §5 shows a course it misses, and a
  variant that tests combinations instead (decision 2).

## 2. Remembering the chosen schedule (browser)

* **The field.** `state.chosen = {"<academic year>/<term>": {code: {kind: group_id}}}`.
  It is kept separately for each term, so that selecting in semester ב never
  touches what is remembered for א.
  * It goes in `defaultState()` (app.js:612-682), because `loadState` copies only
    the keys `defaultState()` has (app.js:818-821). Without that, the field is
    dropped on load. It also needs its own shape check (app.js:822-870).
  * `STORAGE_KEY` stays `braude_schedule_builder_v1`, and `STORAGE_SCHEMA` stays
    1. A different schema value discards the whole saved state (app.js:816).
  * Saved state from before the change, without the field, loads with an empty
    default. This is how the existing tests seed old state (for example
    `test_recommended_defaults_browser.py` OLD_STATE), so it keeps loading. Such
    state does trigger the one-time migration in gap 3 below, though, which means
    one extra solve.
* **One group per (course, kind) is enough.** A selection never holds two groups
  of one kind (models.py:201; scheduler.py:734-736).
* **When it is written:**
  * In `selectAlternative` (app.js:6650). Card clicks and the previous/next
    buttons both go through it (`stepAlternative`, app.js:6655).
  * In the number tabs of `compactTabs` (app.js:3652-3653). They call `setState`
    directly and skip `selectAlternative`, so they need their own write.
  * Writing must not trigger a solve.
    `test_alternatives_browser.py::test_choosing_and_sorting_do_not_ask_the_server`
    guards that for the cards and the previous/next buttons only. A new test
    must cover the number tabs.
  * A selection replaces the entries for **the courses in that alternative**.
    Entries for other courses and other terms stay.
* **Where the ids come from.** `runtime.solve.schedules[i].picks`: every pick
  carries `code`, `kind` and `group_id` (api.py:688-706).
* **What is sent.** `buildSolveBody` (app.js:2792-2824) always adds `chosen`.
  * Its content is the entry for the current academic year and term, filtered to
    the selected courses the same way pins are (`pickedFor`, app.js:2065-2072).
  * It is `{}` when nothing is remembered for this term. It is never left out,
    because leaving it out switches the exclusion off (§3).
  * Entries for courses that are not selected stay saved and dormant, as pins do
    (app.js:2605-2616).
* **After a solve.** If one of the returned schedules is exactly the remembered
  one, it becomes the active alternative. Today `activeSchedule` is only an index
  (app.js:2152-2156, 2860-2862), and nothing matches a schedule by its content.

**Three gaps in rule 1 as written** (decisions 4 and 5):

1. **The #1 shown by default is never "selected".** A student who registers from
   #1 without clicking has nothing remembered, so once those groups fill up they
   are excluded. The same applies to a course added later.

   *Recommendation:* the alternative on screen **fills in** every (course, kind)
   that has nothing remembered yet. An explicit selection replaces the entries
   for the courses in that alternative. The display never overwrites what is
   already remembered.

2. **Browsing overwrites.** Looking at #2 makes #2 the remembered schedule. The
   other alternatives stay on screen until the next solve, so the student can
   still go back to #1. After any edit or reload, though, #1's full groups that
   are not in #2 are excluded for good. That follows from rule 1, so I would
   keep it and document it.

3. **Saved state from before the release has no field.** Its first solve would
   exclude groups the student may already be registered in. Rule 2 would protect
   nobody who built a schedule before the change.

   *Recommendation:* a one-time migration, only for saved state that has courses
   but no `chosen` field:
   * the first solve is sent **without** `chosen`, which means exclusion off (§3);
   * the alternative at the saved `activeSchedule` index is remembered;
   * the page then solves again with it.

   This rebuilds the schedule from today's catalog, which may not be exactly what
   the student saw. A fresh browser gets nothing, as rule 5 says.

   *A detail the code forces:* "no `chosen` field" has to be read from the raw
   saved JSON, before `loadState` merges it into `defaultState()` (app.js:818).
   After the merge, absent and empty look the same. The first `saveState()`
   (`setState` saves every time, app.js:898) writes the empty default, so the
   migration needs its own one-time flag. If the migration solve has no schedule
   to remember, nothing is remembered and the second solve runs with `{}`.

## 3. Server: how the ids arrive, and where the exclusion lives

### The field

* `chosen`: `{code: {kind: group_id}}`, the same shape as `pinned`.
* **Cleaning is lenient, and that has to be new code.** A malformed entry is
  ignored and never returns a 400. The value comes from localStorage, so a 400
  would lock the page on every load.
  * The comment at api.py:5242-5246 makes the same argument, but for a pin whose
    group no longer exists.
  * Pin *cleaning* is strict. `_clean_pinned` returns a 400 when the value, or one
    course's value, is not an object (api.py:1039-1056), and `clean_code` does the
    same for a bad course key (api.py:787-792). Copying it would bring the 400
    back.
* **The field's presence switches the exclusion on.** The browser always sends
  it, as `{}` when nothing is remembered. When it is absent, the server behaves as
  it does today. That covers the CLI (cli.py:2694 calls `scheduler.solve`
  directly), the protected `test_web.py` request bodies (which never send it), and
  the one-time migration solve in §2.

### api.py decides what is excluded

* Right after `_build_courses` (api.py:5157):
  `excluded = {(code, kind, gid) : status_note == "הקורס מלא"} − chosen − (pins, decision 3)`.
* Rule 4 runs there too. The left-out courses, and any courses tied to them, are
  removed from `built` before:
  * the credits (api.py:5169);
  * `attendance_info` (api.py:5198);
  * the `if not built:` early return (api.py:5201-5209). If every selected course
    is left out, that return fires with "לא נבחר אף קורס עם נתונים שמורים" and a
    "no group data" suggestion, so it needs its own wording;
  * `_validate_tied` (api.py:5222);
  * step 4 (`_count_and_min_days`, api.py:5271).
* **An ordering detail.** `prefs` is built at api.py:5133-5143, before
  `_build_courses`, but the excluded set needs the built courses. So either
  `_make_preferences` moves after `_build_courses`, or the field is added
  afterwards with `dataclasses.replace`.
* **`compute_viability`** (api.py:2679) rebuilds the courses itself. It already
  takes its codes from `built` and receives `prefs` (api.py:5248-5249,
  5302-5303), so once `prefs` carries the excluded set, it gets the set for free.
* **A new response key, `left_out`**, gives `[{code, name, reason}]`. It must not
  reuse `not_offered`: the browser merges that into "courses without group data"
  (app.js:2093-2112), which would be the wrong explanation.

### The engine applies it

* `Preferences` gets `excluded_groups: frozenset[(code, kind, gid)]`, empty by
  default. With it empty, the CLI and the engine's own tests behave exactly as
  today.
* `_unary_violations` (scheduler.py:524) adds `(CONSTRAINT_FULL, "הקבוצה מלאה")`
  for those groups. That gives the filter the same reach as the hour limits:
  * every solver path goes through `_filter_groups`;
  * so `feasible_count`, `min_days`, viability, `day_relaxations`,
    `relaxations`, the diagnosis and the solve itself all agree;
  * `dataclasses.replace` carries the field into the relaxation re-solves
    (scheduler.py:1416).

### Why not api.py alone

* **Deleting groups from `course.groups` breaks linked groups.**
  * `_link_allows` stops enforcing a link to an id it cannot find
    (scheduler.py:614-627). api.py:2437-2443 and SPEC_WEB.md:55-77 record this as
    the reason pins never delete groups.
  * Deleting a whole kind removes that component without a word
    (models.py:174-180).
* **A filter on finished selections, the way pins work (`pins_satisfied`), does
  not reach everything.** It misses `scheduler.solve` when there are no pins,
  `day_relaxations`, `relaxations` and the diagnosis. Their numbers would then
  disagree with `feasible_count`.

### Three more fixes the engine needs

1. **`relax_suggestions` tips 2–4** read `c.groups` without the filter
   (scheduler.py:1866-1906). A student with hour limits or blocked windows would
   be told to widen hours for groups that are full.
2. **Diagnosis stage 1** needs only a name for the new constraint.
   * When the causes are mixed, it prints each group's own text
     (scheduler.py:1734-1739), so "הקבוצה מלאה" reads correctly.
   * Its fallback, "אילוץ אישי חוסם את כולן" (scheduler.py:1785), is used only
     when every group of a kind fails for one constraint type. For fullness, rule
     4 leaves such a course out first.
3. **`_dead_end_reason`** (api.py:2648-2656) wraps the first violation as
   "הקבוצה נחסמת על ידי המגבלות שהוגדרו — הקבוצה מלאה" (measured). For a full
   group the reason should be "הקבוצה מלאה" on its own, even when the group also
   breaks an hour limit. `_unary_violations` lists violations meeting by meeting,
   so without a direct path the hour text could come first.

### The `_make_preferences` trap

* `_make_preferences` (api.py:1137-1155) returns a generic list of keywords that
  `Preferences` lacks. Then `solve()` turns any name on that list into
  `attendance_supported=False` and the soft-conflict note (api.py:5144-5154).
* If the field is instead added afterwards with `dataclasses.replace`, an engine
  without the field raises a TypeError, which is a 500.
* Either way, the new engine field must land in the same commit as the API change.

## 4. A remembered group id that no longer exists

* **Nothing happens in the engine.** The exclusion is computed from groups that
  exist, so an allow-entry with no group behind it changes nothing. The course
  is solved normally from its open groups.
* **It must not go through `resolve_pins` / `dropped_pins`.** A dropped pin takes
  the early return at api.py:5247-5268, which comes back with no schedule at all.
* **The server reports it, without stopping the solve:** a new key,
  `chosen_missing: [{code, kind, group_id}]`. The browser deletes those entries
  from saved state and shows a toast, the same way it handles a dropped pin
  (`applyDroppedPins`, app.js:2653-2675). A group the student registered in that
  disappears from the yedion is worth knowing about.
* **Remembered entries for another term are never sent and never pruned.**
  `/api/courses` returns groups only for the requested term (api.py:2346, 4619);
  a different academic year only adds a warning (api.py:4681-4688).
  * Pruning the way pins are pruned (`prunePicks`, app.js:2617-2645) would delete
    א's entries for every course whose ב groups happen to be loaded.
  * The server's `chosen_missing` is safe because it is reported only for the
    term actually being solved.

## 5. Interactions

### The attendance waiver

* The waiver only softens overlaps (`conflict_is_hard`, scheduler.py:479-492) and
  lowers the score's day penalty (`attendance_free_days`, used only in `score()`,
  scheduler.py:1132-1134). The `min_days` the page shows still counts raw days
  (api.py:2563).
* Every component still gets a group (scheduler.py:734-736), so the student
  still registers for it.
* So a full group is excluded in a waived component too, and a waiver cannot
  rescue a component whose groups are all full.
* A waiver **can** rescue a clash between the open groups that remain. Measured:
  * Software Engineering semester 5: waiving 11069 שו"ת or the 61832 lecture
    gives 4 schedules.
  * Information Systems year 3: waiving the 61757 lab or the 62009 tutorial gives
    2.
  * Mechanical Engineering year 2 and Electrical Engineering year 2: no single
    waiver helps.
* The page never suggests a waiver. The browser always sends
  `allow_soft_conflicts: true`, and `_soft_conflict_opportunities` returns nothing
  in that case (scheduler.py:1954-1955). That is today's behaviour, outside this
  proposal.

### Linked groups

* **The exclusion keeps every group in place, so links stay enforced.** A
  tutorial linked only to a full lecture stays tied to it, and becomes unusable
  once that lecture is excluded. That is correct: it is for that lecture's
  students only.
* **Rule 4 tests components, not combinations.** A course can have an open group
  in every component and still have no allowed combination under its links.
  * In the 16 selections this happens once: Electrical Engineering year 2,
    **11232** (פיזיקה 2 מ'). With rule 4 as written, the whole result becomes "no
    possible schedule".
  * Across semester א there are 12 such courses.
* **11 of those 12 come from an existing engine bug, not from fullness.**
  * `_kind_index` is keyed by (course, group id), and the last kind written wins
    (scheduler.py:593-599).
  * So 11232's lectures, which link to ids /1–/3, are read as linking to labs
    /1–/3, all of which are full. The open lab /4 is never allowed, today
    included.
  * Only 31421 is blocked by fullness alone: its open lecture /1 links only to
    tutorial /2, which is full.
  * This collision was not in DEFERRED.md. It is recorded there now (2026-10-02).
* **The variant (decision 2):** leave a course out when, on its own, it has
  combinations today and none with the exclusion. Measured, it leaves 11232 out,
  and Electrical Engineering year 2 gets 72 schedules. For 11232 and 31421 the line
  "כל הקבוצות מלאות" is then loose wording: an open group exists, but no open
  combination does.

### Tied courses

* Leaving out one course of a tied bundle while its partners stay raises
  `TiedCoursesError` (scheduler.py:1222-1236). The response then says the bundle
  must be taken together and returns no schedules (api.py:5221-5239). That would
  be misleading, because the student did select the whole bundle.
* So rule 4 must leave out the whole bundle. Its line for a partner cannot say
  "כל הקבוצות מלאות", because the partner's groups are not full. It needs its own
  wording, for example "לא נכנס: X – צמוד ל-Y, שכל הקבוצות שלו מלאות".
* The bundles in the default curriculum are (61179, 61180) and (61756, 61757,
  62027). None of them has an all-full component today, although 4 of the 5
  61757 lab groups are full.

### Pins

* Pins filter finished selections (api.py:2495-2504). Under the exclusion, a pin
  on a full group that is not remembered would leave no candidates, which means
  "no possible schedule".
* **Decision 3, two options:**
  * **(a) An existing pin counts as allowed, like the remembered schedule.** I
    recommend this. A pin is the student's explicit choice of that group.
    * The lecturers step already shows a pinned group as live even when it is
      dead (`dead = via.ok === false && !isPinned`, app.js:6473), so the student
      can unpin it. After that it is disabled.
    * New pins on full groups are impossible under rule 3.
  * **(b) The pin is released with a toast,** without ending the solve.
* **Viability tests each group by pinning it** (api.py:2697-2702). The allow-list
  must be built from the student's own pins, not from these trial pins. Otherwise
  every full group passes its trial and rule 3 never disables anything.
* **A pin on a group of a left-out course** stays in saved state, dormant. The
  "לא נכנס" line already explains the course. Today `resolve_pins` skips it
  without a word (api.py:2457-2460), and that stays.

### Lecturer ranking

* Ranking is by lecturer name, not by group (app.js:2052-2057).
* **A disabled row ignores clicks** (app.js:6503-6504). That blocks ranking *and
  un-ranking* from that row.
  * The same lecturer can still be ranked or un-ranked from an open row.
  * A lecturer whose groups are all full can only be removed with the clear-all
    button, which also clears every pin (app.js:3378-3380).
  * A ranking already saved stays and is sent (app.js:2807).
* **The results page covers this only partly.** "בלי המרצה שבחרת: X" checks only
  the **first** name in each course's ranking (app.js:7316-7318), and says nothing
  for a course that is left out (app.js:7315).
  * An excluded first choice is named, without the reason.
  * An excluded lower-ranked lecturer is not mentioned at all.
  * I would accept both.

## 6. The interface

### Lecturers step (rule 3)

* **Server:** a full group that is not remembered gets
  `viability = {ok:false, reason:"הקבוצה מלאה"}`.
* **Browser,** in `groupRow` (app.js:6467-6611):
  * A dead row today shows the fixed sub-line "לא משאיר מערכת אפשרית"
    (`app.lecturers.row.deadLine`), plus the yedion's status line, which for a
    full group is "הקורס מלא" (app.js:6548-6549).
  * A full row shows **"הקבוצה מלאה" instead**, once, not both lines.
  * It is disabled exactly like a dead row: `is-dead`, `aria-disabled`, the pin
    disabled, colour through `--mut` and `--bd`, and no opacity (style.css:1948-1958;
    the disabled pin at style.css:1999; guarded by `test_no_opacity_on_text.py`).
* **New string:** `app.lecturers.row.fullLine` = "הקבוצה מלאה". The blocks keep
  `app.grid.groupFull` = "קבוצה מלאה", as your rule 2 says.
* **A missing viability entry counts as ok today** (app.js:2024-2032).
  * Viability is skipped above 300 groups, and it is empty on some infeasible
    exits.
  * In those cases the browser must still disable full, non-remembered rows on
    its own. It has the status from `/api/courses` and the remembered set locally.
* **The groups of a left-out course need their own disabled state.**
  `compute_viability` sends no entries for them, and the browser would treat
  them as live (measured in §7: 61767's 5 groups and 22310's 3).
* **An infeasible result marks every group dead,** and that is today's
  behaviour. It holds on the normal "no possible schedule" path. It does not hold
  in three cases, where rows stay live:
  * the tied-bundle early return, which sends `viability: {}`;
  * selections with more than 300 groups, where viability is skipped;
  * pinned rows.

  Measured: no group stays live in Software Engineering semester 5, Information
  Systems year 3, Mechanical Engineering year 2 or Electrical Engineering year 2
  when nothing is remembered.

### Results page (rule 4)

* **The line.** One new line per left-out course, under `#schedule-unscheduled`
  (index.html:652-656): "לא נכנס: <course name> – כל הקבוצות מלאות". The string
  is `app.grid.leftOutFull`.
* **It must show in two more places:** on the "no possible schedule" page, and
  when every selected course is left out. In that last case today's text is
  "לא נבחר אף קורס עם נתונים שמורים" (api.py:5201-5209), which is wrong and needs
  its own wording.
* **The line is the only explanation on the results page.** The legend and the
  credits pill are built from picks (app.js:8166, 7889), so a left-out course
  vanishes from both without a word. The courses step still counts it
  (app.js:4947, 9248-9251).

### Blocks (rule 2)

Already built: the `.ev-full` mark and the aria suffix (app.js:8438, 8471-8473),
the line for courses with no fixed time, and the details panel.

## 7. Measurements

**Method.** I used the 16 request bodies from the penalty proposal: the exact body
the page sends after "restore recommended", semester א. Each went through the
real `/api/solve` with an empty store and the shipped catalog (nightly build
2026-09-30, `59a8cfc`), plus two in-memory patches:

* The engine's candidate filter excludes every full group that is not
  remembered.
* `_build_courses` applies rule 4, together with tied partners.

The **remembered schedule is today's #1**: the schedule a student would have
built, and registered for, before its groups filled up. Every body sends
`target_days: 6` and no hour limits, blocked windows or Friday rule.

### All 16 selections

"Combinations" is `feasible_count`, the number of valid schedules. The page shows
the best 5.

| Selection | Today: combinations · min days | No remembered schedule | Today's #1 remembered |
| --- | --- | --- | --- |
| Software Eng. year 1 | 216 · 5 | identical | identical |
| Software Eng. year 2 | 314 · 3 | 15 · 4 | 78 · 4 |
| **Software Eng. year 3 (semester 5)** | 742 · 4 | **no possible schedule** | 126 · 4 |
| Software Eng. year 4 | 36 · 3 | 1 · 2; **61767 left out** | 4 · 3 |
| Information Systems year 1 | 92 · 5 | identical | identical |
| Information Systems year 2 | 804 · 3 | 6 · 5 | 54 · 4 |
| Information Systems year 3 | 60 · 4 | **no possible schedule** | 8 · 5 |
| Biotechnology year 1 | 1,460 · 5 | identical | identical |
| Biotechnology year 2 | already none | still none; **41060 and 41411 left out** | — (nothing to remember) |
| Biotechnology year 3 | 4 · 5 | identical | identical |
| Civil Eng. year 1 | 1,400 · 4 | identical | identical |
| Industrial Eng. year 1 | 6,546 · 5 | identical | identical |
| Mechanical Eng. year 1 | 36,698 · 3 | identical | identical |
| Mechanical Eng. year 2 | 104 · 4 | **no possible schedule**; 22310 left out | 2 · 4 |
| Electrical Eng. year 1 | 34,164 · 3 | identical | identical |
| Electrical Eng. year 2 | 1,284 · 3 | **no possible schedule** (combination variant: 11232 left out, 72 · 4) | 80 · 5 |
| Electrical Eng. year 3 | 124 · 4 | 10 · 4 | 14 · 4 |

"Identical" means the same five schedules, the same number of combinations, the
same min days, the same day relaxations and the same lecturers-step state. None
of their courses has a full group that any valid schedule could use.

### Top 5, for the 8 that change

Each cell reads: schedule letter · score · full groups · days · weekly gaps ·
latest end.

* Within one selection, the same letter means the same schedule.
* In the third column, every full group is one of the remembered ones.
  Remembered groups are allowed, so other alternatives can reuse them too.
* Where a course is left out, the scores cannot be compared with today's,
  because the schedule has fewer courses.

#### Software Engineering year 2

| # | Today | No remembered schedule | Today's #1 remembered |
|---|---|---|---|
| 1 | A · −49.83 · 3 · 5d · 0:30 · 16:50 | F · −72.50 · 0 · 5d · 0:00 · 18:50 | A · −49.83 · 3 · 5d · 0:30 · 16:50 |
| 2 | B · −49.83 · 4 · 5d · 0:30 · 16:50 | G · −72.83 · 0 · 5d · 0:30 · 18:50 | D · −57.17 · 3 · 5d · 0:30 · 16:50 |
| 3 | C · −56.83 · 4 · 5d · 0:30 · 16:50 | H · −72.83 · 0 · 5d · 0:30 · 18:50 | K · −57.50 · 2 · 4d · 0:30 · 18:50 |
| 4 | D · −57.17 · 3 · 5d · 0:30 · 16:50 | I · −79.17 · 0 · 5d · 3:20 · 17:50 | L · −57.50 · 1 · 5d · 0:30 · 17:50 |
| 5 | E · −57.17 · 4 · 5d · 0:30 · 16:50 | J · −79.50 · 0 · 5d · 3:50 · 17:50 | M · −57.50 · 1 · 5d · 0:30 · 17:50 |

#### Software Engineering year 3 (semester 5)

| # | Today | No remembered schedule | Today's #1 remembered |
|---|---|---|---|
| 1 | A · −65.00 · 5 · 5d · 2:30 · 19:50 | **no possible schedule** | A · −65.00 · 5 · 5d · 2:30 · 19:50 |
| 2 | B · −65.00 · 4 · 5d · 2:30 · 19:50 | | B · −65.00 · 4 · 5d · 2:30 · 19:50 |
| 3 | C · −65.33 · 4 · 5d · 2:30 · 19:50 | | C · −65.33 · 4 · 5d · 2:30 · 19:50 |
| 4 | D · −65.33 · 5 · 5d · 2:30 · 19:50 | | E · −65.33 · 3 · 5d · 2:30 · 19:50 |
| 5 | E · −65.33 · 3 · 5d · 2:30 · 19:50 | | F · −65.50 · 5 · 4d · 2:30 · 19:50 |

#### Software Engineering year 4

| # | Today | No remembered schedule (61767 left out) | Today's #1 remembered |
|---|---|---|---|
| 1 | A · −10.00 · 2 · 3d · 0:00 · 13:50 | F · −5.17 · 0 · 2d · 0:00 · 13:50 | A · −10.00 · 2 · 3d · 0:00 · 13:50 |
| 2 | B · −10.00 · 1 · 3d · 0:00 · 13:50 | — | B · −10.00 · 1 · 3d · 0:00 · 13:50 |
| 3 | C · −10.17 · 2 · 3d · 0:00 · 13:50 | — | G · −13.83 · 2 · 3d · 0:00 · 14:50 |
| 4 | D · −10.17 · 2 · 3d · 0:00 · 13:50 | — | H · −13.83 · 1 · 3d · 0:00 · 14:50 |
| 5 | E · −13.33 · 3 · 4d · 0:00 · 14:50 | — | — |

#### Information Systems year 2

| # | Today | No remembered schedule | Today's #1 remembered |
|---|---|---|---|
| 1 | A · −42.17 · 2 · 5d · 0:30 · 16:50 | F · −64.83 · 0 · 5d · 0:30 · 18:50 | A · −42.17 · 2 · 5d · 0:30 · 16:50 |
| 2 | B · −42.50 · 3 · 4d · 0:30 · 16:50 | G · −71.50 · 0 · 5d · 3:50 · 16:50 | K · −49.50 · 1 · 5d · 0:30 · 16:50 |
| 3 | C · −42.50 · 3 · 5d · 0:30 · 16:50 | H · −79.17 · 0 · 5d · 3:20 · 18:50 | L · −50.17 · 2 · 4d · 0:30 · 18:50 |
| 4 | D · −42.50 · 2 · 5d · 0:30 · 16:50 | I · −79.50 · 0 · 5d · 3:50 · 18:50 | M · −50.17 · 2 · 5d · 0:30 · 18:50 |
| 5 | E · −42.50 · 3 · 5d · 0:30 · 16:50 | J · −79.67 · 0 · 5d · 3:50 · 18:50 | N · −50.33 · 2 · 5d · 0:30 · 18:50 |

#### Information Systems year 3

| # | Today | No remembered schedule | Today's #1 remembered |
|---|---|---|---|
| 1 | A · −62.17 · 3 · 5d · 2:30 · 19:50 | **no possible schedule** | A · −62.17 · 3 · 5d · 2:30 · 19:50 |
| 2 | B · −62.50 · 3 · 4d · 2:30 · 19:50 | | F · −77.17 · 2 · 5d · 4:50 · 19:50 |
| 3 | C · −64.00 · 3 · 5d · 2:30 · 19:50 | | G · −78.83 · 2 · 5d · 4:20 · 19:50 |
| 4 | D · −64.33 · 3 · 5d · 2:30 · 19:50 | | H · −86.83 · 3 · 5d · 7:50 · 19:50 |
| 5 | E · −67.83 · 2 · 5d · 2:30 · 19:50 | | I · −93.83 · 1 · 5d · 6:40 · 19:50 |

#### Mechanical Engineering year 2

| # | Today | No remembered schedule (22310 left out) | Today's #1 remembered |
|---|---|---|---|
| 1 | A · −106.33 · 4 · 4d · 5:30 · 19:50 | **no possible schedule** | A · −106.33 · 4 · 4d · 5:30 · 19:50 |
| 2 | B · −106.33 · 5 · 4d · 5:30 · 19:50 | | C · −106.33 · 3 · 4d · 5:30 · 19:50 |
| 3 | C · −106.33 · 3 · 4d · 5:30 · 19:50 | | — |
| 4 | D · −106.33 · 4 · 4d · 5:30 · 19:50 | | — |
| 5 | E · −106.33 · 5 · 4d · 5:30 · 19:50 | | — |

#### Electrical Engineering year 2

| # | Today | No remembered schedule | Today's #1 remembered |
|---|---|---|---|
| 1 | A · −43.67 · 2 · 5d · 0:00 · 15:50 | **no possible schedule** | A · −43.67 · 2 · 5d · 0:00 · 15:50 |
| 2 | B · −44.33 · 3 · 5d · 0:00 · 17:50 | | C · −48.67 · 2 · 5d · 1:00 · 15:50 |
| 3 | C · −48.67 · 2 · 5d · 1:00 · 15:50 | | E · −51.33 · 2 · 5d · 0:00 · 17:50 |
| 4 | D · −49.33 · 3 · 5d · 1:00 · 17:50 | | F · −51.50 · 2 · 5d · 0:30 · 15:50 |
| 5 | E · −51.33 · 2 · 5d · 0:00 · 17:50 | | G · −51.67 · 2 · 5d · 0:00 · 17:50 |

#### Electrical Engineering year 3

| # | Today | No remembered schedule | Today's #1 remembered |
|---|---|---|---|
| 1 | A · −76.50 · 2 · 5d · 3:00 · 17:50 | F · −92.83 · 0 · 5d · 4:00 · 17:50 | A · −76.50 · 2 · 5d · 3:00 · 17:50 |
| 2 | B · −80.50 · 2 · 5d · 3:00 · 18:50 | G · −93.33 · 0 · 4d · 4:30 · 17:50 | B · −80.50 · 2 · 5d · 3:00 · 18:50 |
| 3 | C · −80.67 · 2 · 5d · 3:50 · 17:50 | H · −93.33 · 0 · 5d · 4:30 · 17:50 | C · −80.67 · 2 · 5d · 3:50 · 17:50 |
| 4 | D · −80.67 · 3 · 5d · 3:50 · 17:50 | I · −96.83 · 0 · 5d · 4:00 · 18:50 | K · −84.67 · 2 · 5d · 3:50 · 18:50 |
| 5 | E · −82.83 · 1 · 5d · 2:00 · 17:50 | J · −97.33 · 0 · 4d · 4:30 · 18:50 | F · −92.83 · 0 · 5d · 4:00 · 17:50 |

### Courses left out

* **No remembered schedule: 4 courses in 3 selections.**
  * Software Engineering year 4: 61767 (אבטחת מידע וקריפטולוגיה). Its tutorials
    are all full.
  * Mechanical Engineering year 2: 22310 (מכניקת מוצקים 2). Its tutorials are all
    full.
  * Biotechnology year 2: 41060 (כימיה אורגנית 2) and 41411 (מאזן חומר ואנרגיה).
    Their tutorials are all full.
  * In Mechanical Engineering year 2 and Biotechnology year 2, leaving the course
    out does not save the selection.
* **The combination variant adds 11232** (Electrical Engineering year 2).
* **Today's #1 remembered: none.**
* No left-out course is part of a tied bundle.

### Selections that become infeasible for another reason

With no remembered schedule, **4 of 16**. Rule 4 brings none of them back. Only
Mechanical Engineering year 2 has an entirely full component (22310's
tutorials), and leaving that course out still leaves two clashes. The server's
own diagnosis names the real cause, because the exclusion is a candidate filter:

| Selection | The server's reason | Its suggestion | What restores a schedule (measured) |
| --- | --- | --- | --- |
| Software Eng. semester 5 | 11069 שו"ת × 61832 lecture: 11069's only open group (Sunday 12:50–14:50) overlaps 61832's only open lecture (Sunday 12:50–15:50) | drop 11069, or drop 61832 | dropping 11069 or 61832 (4 schedules each); waiving attendance on either (4) |
| Information Systems year 3 | 61757 lab × 62009 tutorial: every allowed pair clashes. For example, 61757's only open lab, /4, against 62009 271070310/1 on Thursday 11:30–12:20 | drop 62009; dropping 61757 means dropping its whole tied bundle | dropping 62009 (2); waiving either (2) |
| Mechanical Eng. year 2 | 11061 × 11212, and 22114 × 22415 (two clashes; 22310 is already left out) | drop 11061, or drop 11212 | no single drop or waiver |
| Electrical Eng. year 2 | inside 11232, every lecture + lab pair is blocked by `linked_to` (the `_kind_index` bug, §5) | drop 11232 | dropping 11232 (72); no waiver |

**With today's #1 remembered: none.** That holds by construction. #1 was valid
and every one of its groups stays allowed, so it is still a valid schedule, and
it was the best of a larger set.

### min days and the relaxation suggestions

**min days:**

| Selection | Today | No remembered schedule | Today's #1 remembered |
| --- | :---: | :---: | :---: |
| Software Eng. year 2 | 3 | 4 | 4 |
| Software Eng. semester 5 | 4 | — | 4 |
| Software Eng. year 4 | 3 | 2 (61767 left out) | 3 |
| Information Systems year 2 | 3 | 5 | 4 |
| Information Systems year 3 | 4 | — | 5 |
| Mechanical Eng. year 2 | 4 | — | 4 |
| Electrical Eng. year 2 | 3 | — | 5 |
| Electrical Eng. year 3 | 4 | 4 | 4 |

**Day relaxations** ("drop this course to reach N days"), measured at one day
below today's minimum:

| Selection, target | Today | No remembered schedule | Today's #1 remembered |
| --- | --- | --- | --- |
| Software Eng. semester 5, 3 days | drop אוטומטים וחישוביות (395 schedules), or the tied bundle (42) | none (no schedule at all) | the same two (42 and 24 schedules) |
| Software Eng. year 4, 2 days | drop רשתות מחשבים (→1 day), or אבטחת מידע (→2) | none needed: 2 days is reachable once 61767 is left out | the same two (2 schedules each) |
| Information Systems year 3, 3 days | three options | none | only the tied bundle (→2 days) |
| Mechanical Eng. year 2, 3 days | drop אנגלית מתקדמים ב' (148) | none | the same (2) |
| Electrical Eng. year 3, 3 days | drop מבוא לעיבוד אותות ספרתי (104), or מבוא לתקשורת (62) | only מבוא לתקשורת (5) | only מבוא לתקשורת (7) |
| Software Eng. year 2 and Information Systems year 2, 2 days | no single drop helps | no single drop helps | no single drop helps |
| Electrical Eng. year 2, 2 days | no single drop helps | none (no schedule at all) | no single drop helps |

**On the 4 infeasible results:**

* `reasons` name the real clash.
* `suggestions` are "שקלי לוותר על X" for the two clashing courses.
* `relaxations` is empty, because these bodies set no hour limits, windows or
  Friday rule.
* `day_relaxations` is not computed, because min days is null.

**Not exercised by these bodies:** `relax_suggestions` tips 2–4 count full groups
(§3), so a student with hour limits set would get suggestions based on groups
that are excluded.

### The lecturers step

Each cell counts the groups the step lists, split into disabled because full ·
disabled for another reason · live.

| Selection | Groups | Today | No remembered schedule | Today's #1 remembered |
| --- | :---: | --- | --- | --- |
| Software Eng. year 2 | 22 | 0 · 0 · 22 | 6 · 0 · 16 | 3 · 0 · 19 |
| Software Eng. semester 5 | 28 | 0 · 0 · 28 | 12 · 16 · 0 | 7 · 0 · 21 |
| Software Eng. year 4 | 12 | 0 · 0 · 12 | 4 · 0 · 3, and **61767's 5 groups have no entry** | 5 · 0 · 7 |
| Information Systems year 2 | 24 | 0 · 0 · 24 | 7 · 2 · 15 | 5 · 0 · 19 |
| Information Systems year 3 | 23 | 0 · 3 · 20 | 10 · 13 · 0 | 7 · 1 · 15 |
| Mechanical Eng. year 2 | 26 | 0 · 4 · 22 | 11 · 12 · 0, and **22310's 3 groups have no entry** | 9 · 5 · 12 |
| Electrical Eng. year 2 | 30 | 0 · 3 · 27 | 8 · 22 · 0 | 6 · 4 · 20 |
| Electrical Eng. year 3 | 25 | 0 · 0 · 25 | 8 · 1 · 16 | 6 · 1 · 18 |

* **The reason the code produces today, measured, is wrong for a full group.**
  `_dead_end_reason` gives "הקבוצה נחסמת על ידי המגבלות שהוגדרו — הקבוצה מלאה"
  ("blocked by the constraints you set"). It needs the direct "הקבוצה מלאה" (§3).
* **A left-out course gets no viability entries at all,** because
  `compute_viability` only sees the courses that are kept. The browser treats a
  missing entry as live (app.js:2024-2032). So without a fix, 61767's and
  22310's groups would look rankable and pinnable.
  * The fix: the server sends an entry for each of them, for example
    `{ok:false, reason:"כל הקבוצות מלאות"}`, or the browser disables them using
    `left_out`.
* **On an infeasible result, no group is live.** That is today's behaviour for
  any infeasible result. Here it reaches every new student of Software
  Engineering semester 5.

## 8. Tests

### What was run, and what was not

I started the full suite with the exclusion switched on in memory. The patch was
a pytest plugin outside the repo: rule 5 on every `/api/solve`, `/api/courses`
untouched. It ran with 2 workers instead of 3, because only about 1 GB of memory
was free.

**It ran on the local store, not the fixture store** (corrected 2026-10-02, after
the fact).
* I copied `data/db` aside instead of moving it, and
  `scripts/seed_dev_data.py --fixture` does not overwrite existing files without
  `--force` (seed_dev_data.py:54-56).
* So the seed changed nothing, and the run read the real local `data/db`. The
  local store was never modified.
* The conclusion below holds anyway. The 11069 × 61832 clash is the same in the
  local store, and the root cause was confirmed separately on the frozen
  fixture (the table further down).

What happened:

* The first half, 34 files, finished: **22 failed, 577 passed, 30 errors.**
* Claude Code then stopped the run because the system was critically low on
  memory. **The second half never ran.**
* Afterwards I restored `data/db`: all 23 files have hashes identical to the
  backup. I also stopped the test processes the stopped run had left behind.

The first half is **not a clean measurement:**

* **33 of the 46 tracebacks** are Chromium crashing or Playwright failing to
  start ("Target crashed", `PlaywrightContextManager … _playwright`). That is the
  memory shortage, not the code.
* **The clean signal: 11 tests in `test_alternatives_browser.py`** time out
  waiting for `#alt-cards .alt-card`. The page opens Software Engineering
  semester 5 and gets no schedule. The module's other 13 tests crashed, so they
  tell nothing either way.
* **Two assertion failures in `test_hosted_missing_groups.py`** test
  `/api/courses`, which the patch does not touch. They are the known DEFERRED.md
  item "Tests that start a server read the real `data/db`", caused by the local
  store above. They are unrelated to the exclusion.

**The root cause, confirmed with the real engine** on the frozen test fixture,
browser-free, in one process:

| Selection | Today | With the exclusion |
| --- | --- | --- |
| Software Engineering semester 5, as the browser tests open it | 742 combinations | none (the 11069 × 61832 clash) |
| `test_web.py` CODES | 152 | none; 61753 left out |
| `trio` | 45 | 2 |
| `NON_SE` | unchanged | unchanged |
| `BIO` | unchanged | unchanged |

### Protected tests that would fail

CLAUDE.md lets only `test_rendered_copy_browser.py` and `test_lunch_window.py` be
edited freely, and `test_design_tokens.py` only to follow DESIGN value changes.
Every other file below is protected. "Run" marks what the stopped run confirmed;
"reading" marks what comes from reading the test.

* **Tests that open Software Engineering semester 5 in a fresh browser and need
  it to have a schedule.** Some wait for the cards or the grid; others use fixed
  waits.
  * `test_alternatives_browser.py`, all 24. In the run, 11 timed out waiting for
    the cards and the other 13 crashed. (Reading.)
  * `test_results_page_browser.py`, the whole module, 19 tests (reading)
  * `test_results_status_browser.py`, its 12 browser tests (reading)
  * `test_missing_lecturers_browser.py`, 4 (reading)
  * `test_fit_percentage.py`: only `test_the_top_ranked_schedule_is_labelled_not_scored`
    fails. With no schedule, one of the other browser tests still passes
    (`count <= 1`), and the remaining two skip themselves. (Reading.)
  * `test_days_relax_panel.py`, 2. With no schedule there is no `min_days`, so
    the server builds no day relaxations (api.py:5284-5296), and both relax-panel
    assertions fail. (Reading.)
  * `test_study_days.py`, 3. They expect the "מינימום" tag on 4, or a 4 in the
    warning. (Reading.)
  * `test_rendered_copy_browser.py`, the tests that wait for the grid (editable)
* **`test_lecturers_step.py` (reading; these crashed in the run):**
  * `test_pinned_row_is_course_tinted_and_dead_row_is_dimmed_without_opacity[light,dark]`
    fails early. In an infeasible result every row is dead, and a dead row's pin
    ignores clicks (app.js:6602-6608). So the pin never takes, and the test fails
    at `"is-pinned" in pinned["cls"]` (:290).
    * Once the selection is feasible again, for example with a remembered
      schedule seeded, its second half meets rule 3. The dead row it means,
      271070310/1, is itself full, so it would say "הקבוצה מלאה" rather than
      "לא משאיר מערכת אפשרית".
  * The tests that rank by clicking are likely to fail too, for the same reason.
* **`test_relax_ui_browser.py`: undetermined.** It seeds old saved state (six
  codes, no `chosen`) with constraints that are infeasible on purpose, and it
  expects the "no possible schedule" page with the relax panel.
  * That is exactly the state the one-time migration (§2, gap 3) applies to, so
    its first solve runs with the exclusion off.
  * The outcome depends on details of the migration that this proposal does not
    fix yet.
* **`test_web.py` passes unchanged** if the exclusion applies only when `chosen`
  is sent (decision 6), because no test sends it. If the exclusion applied to
  every request, at least 13 of its solve tests would fail:
  * `:891` and `:1127` compare `feasible_count` with the plain engine;
  * `:903`, `:907` and `:919` expect min days 4;
  * `:926` expects schedules spread over days 1–4;
  * `:938` expects 12 picks covering all of CODES;
  * `:961` pins a full group;
  * `:976` expects more than one 61756 tutorial;
  * `:1052`, `:1068` and `:1090` cover viability;
  * `:1108` ranks a lecturer whose 61753 groups are all full.
* **`test_results_status_browser.py::test_a_solve_pick_carries_the_group_status`**
  pins a full group in a bare API request without `chosen`. It passes with the
  exclusion off when `chosen` is absent, and also with pins allowed
  (decision 3).
* **Unaffected:** the engine tests (`test_scheduler`, `test_attendance`,
  `test_relaxations`, `test_day_relaxations`, `test_lunch_window`). The new
  `Preferences` field is empty by default.
* **Saved state:** no test pins the exact set of saved-state keys, and every test
  that seeds old state uses schema 1. With the field added to `defaultState()`
  and the schema unchanged, they keep loading.

**What this means.** The proposal cannot land without editing protected browser
tests. The smallest edit per module would seed a remembered schedule into
localStorage before opening the page, which also exercises rule 2. The other
option is to switch those modules to a selection that stays feasible. Either way
it needs your permission, as CLAUDE.md requires. Confirming the full list needs a
clean run on the fixture store, with memory headroom.

### New tests (new files)

* **Engine:**
  * an excluded group is never chosen;
  * a tutorial linked only to an excluded lecture becomes unusable, so links are
    intact;
  * the default empty set changes nothing.
* **API:**
  * without `chosen`, behaviour is today's; with it, the exclusion applies;
  * a remembered full group stays allowed;
  * rule 4 fills `left_out`, together with tied partners;
  * `chosen_missing` is reported;
  * a malformed `chosen` is ignored and never returns a 400;
  * a full group's viability reason is exactly "הקבוצה מלאה";
  * the groups of a left-out course get viability entries;
  * the server says that full groups were not included on an infeasible result.
* **Browser:**
  * old saved state without the field loads;
  * selecting an alternative writes `chosen` without solving, including through
    the number tabs;
  * the shown alternative fills in what is not yet remembered;
  * the remembered schedule becomes active after a solve;
  * the full row in the lecturers step uses colour, not opacity, and cannot be
    ranked or pinned;
  * the "לא נכנס" line;
  * the one-time migration solve.

## 9. Decisions for you

1. **The 4 selections that become infeasible**, Software Engineering semester 5
   among them, for every student with nothing remembered.
   * *Recommended:* accept "no possible schedule" with the server's real reason,
     plus one added sentence saying that full groups were not included.
   * *Not recommended:* leaving out a course automatically. That would choose,
     on the student's behalf, which course to give up.
2. **Rule 4: by component (as written) or by combination.**
   * *Recommended:* by combination. It keeps fullness in one course from turning
     the whole result infeasible, which is rule 4's intent (Electrical
     Engineering year 2).
   * The line is loose for 11232 and 31421 (see §5).
   * Separately, record the `_kind_index` collision in DEFERRED.md.
3. **Pins on full groups that are not remembered.**
   * *Recommended:* allowed, like the remembered schedule.
   * The alternative: released with a toast.
4. **What counts as "selected".**
   * *Recommended:* the shown alternative fills in what is not yet remembered;
     an explicit selection replaces everything.
   * The alternative: explicit selection only, exactly as rule 1 is written.
5. **Saved state from before the release.**
   * *Recommended:* the one-time migration solve without exclusion.
   * The alternative: accept the gap.
6. **When the exclusion applies.**
   * *Recommended:* only when `chosen` is present, which the browser always
     sends.
   * The alternative: always.
7. **The engine change.** A `Preferences` field and a candidate filter count as a
   solver change. It needs your explicit go-ahead.
8. **Protected tests** (§8).

If approved, it would land as separate commits:

1. DESIGN: the lecturers-step full row and the "לא נכנס" line.
2. The engine filter and the `api.py` changes, with new tests.
3. The browser: saved state, the field sent, the rows and the line.

The full suite would run before each commit.
