# Spec v2 — no-login refresh, attendance-aware scheduling, fetch-on-demand

Four issues raised by the student, in their priority order (functionality first — they explicitly
said the visual design comes **after** this, so do not spend effort on styling here).

Read `docs/GROUND_TRUTH.md` §9 first. It changes the premise of the whole scraping layer.

---

## 1. "Why do some courses say there is no data in the database?"

Not a bug, but bad UX. Only the student's six tracked courses were ever fetched, so every other
course in the semester (e.g. `61759 אוטומטים`, which *is* offered) shows `has_data: false`.

**Fix: fetch on demand.** Now that fetching needs no login (§3 below), checking a course in step 2
should fetch its groups immediately — a second or two — instead of showing "no data".

- `POST /api/courses` gains `fetch_missing: bool = true`. Any requested code with no stored data
  (or stale data) is fetched, parsed, stored, and returned in the same response.
- Return per-course `source: "db" | "fetched" | "unavailable"` and, on failure, a Hebrew reason.
- Never block the whole request on one failing course.
- Cap it: at most 12 on-demand fetches per request, 1.2 s apart. Report anything skipped.

## 2. Attendance is not always mandatory — allow deliberate overlaps

The student's point, and it is correct about how this college works: **lectures often carry no
attendance requirement**, especially when repeating a course. A student may knowingly register for
two courses that clash and simply attend one, if that yields a week that ends earlier.

So a time clash must stop being an absolute veto.

### Model

Add to `scheduler.Preferences`:

```python
attendance: dict[str, dict[str, bool]] = field(default_factory=dict)
    # {course_code: {kind: attendance_required}}. MISSING MEANS True.
    # Default stays "everything is mandatory" so existing behaviour is unchanged.
allow_soft_conflicts: bool = False
    # False = today's behaviour exactly: any overlap is rejected.
    # True  = an overlap is permitted when AT LEAST ONE side does not require attendance.
```

A clash between two groups is **hard** (still rejected) when both sides require attendance, and
**soft** (permitted, but counted and penalised) otherwise:

```python
def conflict_is_hard(a: Group, b: Group, prefs) -> bool:
    if not a.conflicts_with(b):
        return False
    if not prefs.allow_soft_conflicts:
        return True
    return attendance_required(prefs, a) and attendance_required(prefs, b)
```

`enumerate_selections` uses `conflict_is_hard` in place of the raw `conflicts_with` check.

### Scoring

`ScoredSchedule` gains `soft_conflicts: int` and `soft_conflict_minutes: int`. Add a weight
`"soft_conflict": 6.0` — a skipped lecture is a real cost, not free, so it must be penalised
enough that the solver only takes one when it genuinely buys a shorter week. Subtract
`w["soft_conflict"] * soft_conflicts`.

`Selection.is_feasible()` in `models.py` keeps its current strict meaning — do not change it.
Add a separate `Selection.overlapping_pairs()` returning the clashing `(Group, Group)` pairs so
the API and UI can *show* what overlaps.

### Reporting — non-negotiable

A schedule containing a soft conflict must say so loudly, naming both sides and the overlap, e.g.

```
חפיפה מכוונת: 61753 הרצאה קב' 271060330 (יום ד 08:30-10:30)
              מול 61756 תרגול קב' 271060310/3 (יום ד 08:30-11:30)
              — נבחר בהנחה שאין חובת נוכחות ב-61753 הרצאה.
```

Never let a soft conflict pass silently. The student is trading attendance for time and must see
exactly what they are trading.

### Seeding the defaults

The yedion sometimes states it: 11069's note is `חובת הנוכחות בקורס היא מרגע הרישום לקורס`.
When a group's `note` matches `חובת נוכחות` / `חובה להשתתף`, default that component to
**required** and mark it as coming from the yedion so the UI can say so. Otherwise default to
required as well — the student opts *out* deliberately, never by accident.

## 3. Refreshing must not require signing in to Citrix

**Verified and written up in `docs/GROUND_TRUTH.md` §9: the course search needs no login.** Only
`Enter_Search` is gated; `S_LOOK_FOR_NOSE` and `S_LOOK_FOR_NOSE_AB` are public.

### New module `src/yedion_http.py`

A login-free fetcher using only the standard library (`urllib.request` + `http.cookiejar`).

```python
BASE_URL = "https://info.braude.ac.il/yedion/fireflyweb.aspx"

class YedionHTTP:
    def __init__(self, year: str | None = None, delay_s: float = 1.2,
                 timeout_s: float = 45.0, raw_dir: str | None = "data/raw",
                 log: Callable[[str], None] | None = None): ...
    def open_session(self) -> None
        """Warm-up GET, then the ChangeYear POST, then VERIFY the year came back right.
           The warm-up is REQUIRED - see GROUND_TRUTH §9. Without it the year silently
           reverts and every page returns the previous year."""
    def fetch_course(self, code: str) -> str    # dumps raw HTML first, asserts the year
    def fetch_catalog(self) -> str
    def scrape(self, codes) -> dict[str, str]   # sequential, polite, collects .errors
```

Rules:
- Set a normal `User-Agent`.
- Keep the raw dump before parsing, exactly as the Playwright path does.
- `YearMismatchError` if a page's year is not the requested one — this is the guard that catches
  the missing-warm-up failure mode.
- Politeness matters *more* now that nothing throttles us: `delay_s` between requests, and never
  loop the catalog over the alphabet (one request returns all of it).

### Wiring

- `refresh.py` uses `YedionHTTP` **by default**. New flag `--browser` selects the old Playwright
  path (kept, unchanged, for the day the college gates these endpoints).
- The `needs_login` exit path (code 2) stops being the normal case. Keep the code and the message
  for the `--browser` path only.
- `--install-task` now genuinely means unattended: no window, no sign-in.
- `POST /api/scrape/start` uses the HTTP fetcher, so the web refresh is silent and needs no browser.

## 4. No console output on screen during a refresh

Two parts:

1. Removing the browser removes the `[scraper]` chatter entirely for the default path.
2. The remaining progress lines must go to the API's in-memory log buffer that
   `/api/scrape/status` already serves — **not** to the server's stdout. Pass an explicit `log=`
   callback into `YedionHTTP`; the module must never `print()` on its own.

The UI shows progress in the existing collapsible log panel, collapsed by default, with a one-line
summary ("מרענן 6 קורסים…" then "עודכנו 6 קורסים, 0 שינויים"). Raw lines only when expanded.

## Out of scope here

**Visual design.** The student said the interface is not attractive but asked to fix functionality
first. Do not restyle anything in this pass.

## Tests

Extend the existing files' style; do not modify existing test files.
`tests/test_yedion_http.py`, plus additions in a new `tests/test_attendance.py`:

- `YedionHTTP.open_session` performs the warm-up **before** the year POST (assert call order with a
  fake opener), and raises if the verified year does not match.
- A fetch whose page reports the wrong year raises `YearMismatchError`.
- No network in any test — inject a fake opener/transport.
- `conflict_is_hard`: both mandatory → hard; one optional and `allow_soft_conflicts=True` → soft;
  same pair with `allow_soft_conflicts=False` → hard.
- Default `Preferences` (no `attendance` given) behaves **exactly** as before — this is the
  regression guard for the existing 270 tests.
- A soft conflict appears in `ScoredSchedule.soft_conflicts` and is penalised in the score.
- With this student's real data: marking 61753 הרצאה as attendance-optional and enabling soft
  conflicts yields at least one schedule that the strict solver rejects.
