# Spec — course discovery + auto-refreshing JSON database

Extends `SPEC.md`. `GROUND_TRUTH.md` remains authoritative for anything about the yedion's wire
protocol. Read both first.

## Why this exists

Two requirements from the student:

1. **The curriculum is a guideline, not a constraint.** Courses get repeated from earlier semesters,
   and what a student actually takes in a given term routinely differs from the PDF. The tool must
   let them build a schedule from **whatever is actually open**, including a course carried over from
   an earlier semester, and must never restrict the choice to `curriculum.json`.
   `curriculum.json` stays useful for names, credits, prerequisites and tied-course rules — it stops
   being the source of truth for *what is offered*.
2. **The section data must refresh itself.** A scraper pulls from the official info station into a
   JSON store that updates on a schedule (about once a day), so the schedule is built from current
   data rather than a one-off snapshot.

## VERIFIED: the whole catalog costs ONE request

```
GET fireflyweb.aspx?prgname=S_LOOK_FOR_NOSE_AB&arguments=-A
```

Returns **every course offered in the session's selected academic year**. The letter argument is
ignored — passing `-Aא`, `-Aמ`, `-Aש` or bare `-A` all return byte-identical responses (verified:
566,762 bytes, 1172 courses, 25 distinct first letters on the reference instance). So catalog
discovery is a single call, not one per letter.

Row shape, inside `div.Table.fcontainer`, one `div.row` per course:

```html
<div class="row">
  <div class="col">271030</div>                     <!-- code -->
  <div class="col">מתמטיקה ב'</div>                  <!-- name -->
  <div class="col">נלמד</div>                        <!-- status -->
  <div class="col"><button data-progname="S_LOOK_FOR_NOSE"
                           data-arguments="-N271030">חיפוש קורס במערכת השעות</button></div>
  <div class="col"><!$MG_AdditionalInformationSubject>&nbsp;</div>
</div>
```

Status observed: `נלמד`. Treat any other value as "listed but check it", keep it, and record it —
do not silently drop rows whose status you do not recognise.

Remember the year is **session state** (`GROUND_TRUTH.md` §8): set the year *before* the catalog call,
and stamp the catalog with the year it was fetched for.

---

## 1. `src/store.py` — the JSON database

Layout under `data/db/`:

```
data/db/
  catalog.json         every course offered, code -> {name, status}
  sections.json        detailed groups per tracked course, with per-course metadata
  tracked.json         the set of course codes we keep fresh
  refresh_log.jsonl    one JSON line per refresh run (append-only)
  changes.jsonl        one JSON line per detected change (append-only)
  snapshots/           YYYY-MM-DD-HHMM.json copies of sections.json before each overwrite
```

All files utf-8, `ensure_ascii=False`, `indent=2`, newline-terminated, sorted keys where practical
so a diff is readable.

```python
SCHEMA_VERSION = 1
DEFAULT_MAX_AGE_HOURS = 24.0

@dataclass
class CourseMeta:
    fetched_at: str        # ISO-8601 UTC, e.g. "2026-08-30T14:03:11Z"
    year: str              # 'תשפ"ז'
    year_gregorian: str    # "2027"
    semester: str          # "א" / "ב" / "קיץ" / "" (unfiltered)
    source_url: str
    content_sha1: str      # sha1 of the RAW page html — the change-detection key
    group_count: int
    warnings: list[str]
    ok: bool               # False when the fetch or parse failed; data may then be stale

class Store:
    def __init__(self, root: str = "data/db"): ...
    # --- catalog -------------------------------------------------------
    def save_catalog(self, courses: dict[str, dict], year: str, year_gregorian: str) -> None
    def load_catalog(self) -> tuple[dict[str, dict], dict]   # (courses, meta)
    def catalog_age_hours(self) -> float | None
    def search_catalog(self, query: str, limit: int = 40) -> list[tuple[str, str]]
        """Match on code prefix OR name substring. Hebrew-insensitive to nbsp/quote variants.
           Returns [(code, name)] sorted: exact code first, then code-prefix, then name matches."""
    # --- sections ------------------------------------------------------
    def save_course(self, course: Course, meta: CourseMeta) -> list[str]
        """Writes/replaces one course. Returns a list of human-readable CHANGE descriptions
           versus what was stored before (empty on first write or when unchanged)."""
    def load_course(self, code: str) -> tuple[Course | None, CourseMeta | None]
    def load_all(self) -> dict[str, Course]
    def course_meta(self, code: str) -> CourseMeta | None
    def is_stale(self, code: str, max_age_hours: float = DEFAULT_MAX_AGE_HOURS) -> bool
        """True if absent, failed (ok=False), or older than max_age_hours."""
    def stale_codes(self, codes, max_age_hours=DEFAULT_MAX_AGE_HOURS) -> list[str]
    # --- tracked set ---------------------------------------------------
    def tracked(self) -> list[str]
    def track(self, codes) -> None          # union, deduped, sorted
    def untrack(self, codes) -> None
    # --- logs ----------------------------------------------------------
    def log_refresh(self, record: dict) -> None
    def log_changes(self, code: str, changes: list[str]) -> None
    def snapshot(self) -> str | None        # copy sections.json into snapshots/, return path
    def last_refresh(self) -> dict | None
```

### Change detection — this is the point of the whole exercise

`save_course` compares against the stored version and emits Hebrew descriptions, e.g.

```
61753: נוספה קבוצה 22 (הרצאה, ד"ר רווה אלנה)
61753: קבוצה 21 — המרצה השתנה: פרופ' וולקוביץ' זאב -> ד"ר גולני מתתיהו
61753: קבוצה 24 — השעה השתנתה: יום ב 10:15-12:00 -> יום ג 12:00-13:45
61753: בוטלה קבוצה 27 (תרגול)
```

Compare on `content_sha1` first as a cheap gate; only diff structurally when it differs.
A lecturer or time change after registration is exactly what the student needs to be told about,
so these must be surfaced loudly, not buried in a log.

**Never destroy good data on a failed fetch.** If a refresh fails for a course, keep the previous
entry and only update its meta with `ok=False` and a fresh `fetched_at` attempt marker — record the
attempt separately from the successful `fetched_at` so staleness stays truthful.

## 2. `src/discovery.py` — what is actually offered

```python
CATALOG_URL = BASE_URL + "?prgname=S_LOOK_FOR_NOSE_AB&arguments=-A"

def parse_catalog(html: str) -> tuple[dict[str, dict], list[str]]
    """{code: {"name":..., "status":...}}, warnings. Shape-agnostic per GROUND_TRUTH §2:
       div.row / div.col, never <table>. html.unescape + strip U+00A0 on every cell.
       A row is a course row iff col0 is 4-7 digits and there is an S_LOOK_FOR_NOSE button."""

def filter_catalog(catalog, *, code_prefixes=None, name_contains=None,
                   only_curriculum=None) -> dict[str, dict]
    """code_prefixes: e.g. ("61","62","65") for software-engineering courses.
       only_curriculum: a curriculum dict — keep only codes that appear in it (either
       a semester course or an elective). None = no curriculum restriction (the default,
       because the student may legitimately take something outside it)."""

def annotate_with_curriculum(catalog, curr) -> dict[str, dict]
    """Adds, per code, whichever of these are known: curriculum semester it belongs to,
       credits, elective cluster, tied_with, prerequisites. Codes absent from the curriculum
       get {"in_curriculum": False} and MUST still be selectable."""
```

## 3. `refresh.py` — the scheduled job

Entry point at the project root. Exit codes matter, a scheduler reads them.

```
python refresh.py                 # one refresh pass, headless, using the saved session
python refresh.py --headful       # show the browser so a human can log in
python refresh.py --status        # print DB freshness, last run, tracked codes; no network
python refresh.py --codes A,B     # refresh just these (also adds them to tracked)
python refresh.py --catalog-only  # refresh only the catalog, skip section details
python refresh.py --install-task  # register a Windows Scheduled Task
python refresh.py --uninstall-task
python refresh.py --max-age 12    # only refresh what is older than N hours
```

Exit codes: `0` refreshed (or already fresh), `2` **session expired, needs login**, `3` partial
failure (some courses failed), `1` unexpected error.

Flow:
1. Load `profile.json` for the target year/semester; load `Store`.
2. Open the persistent Playwright context **headless**. Navigate to the search page.
3. If redirected to the auth gate → do NOT attempt to log in, do NOT dump the page.
   Write status `needs_login`, log it, print a clear bilingual instruction to run
   `python refresh.py --headful` (or `python main.py`) and sign in once, then exit **2**.
4. Set the academic year and assert it (`GROUND_TRUTH` §8). On mismatch, abort — never write
   wrong-year data into the DB.
5. Fetch and store the catalog.
6. For each tracked code that is stale, fetch + parse + `store.save_course`, 1.5s apart.
7. Write a `refresh_log` record: started/finished, counts, changes, failures, exit reason.
8. Print a short human summary, and every detected change in full.

### Windows Task Scheduler

`--install-task` shells out to `schtasks`, creating a daily task. Quote every path.

```
schtasks /Create /TN "BraudeScheduleRefresh" /SC DAILY /ST 07:00 /F ^
  /TR "\"<pythonw.exe>\" \"<abs path to refresh.py>\""
```

Use `pythonw.exe` when present so no console window flashes daily. Print the exact command before
running it, and print how to inspect/remove the task afterwards. `--uninstall-task` runs
`schtasks /Delete /TN "BraudeScheduleRefresh" /F`.

### The honest limitation — state it in the code and to the user

The yedion sits behind a Citrix NetScaler gateway. A saved browser profile keeps the session alive
for a while, but it **will** expire, and re-authentication is interactive by design. Since this tool
will never store credentials, a daily job cannot be guaranteed unattended forever.

Correct behaviour, which must be implemented and not glossed over:
- try the saved session headlessly;
- on expiry, keep the existing data, mark it stale, exit 2, and tell the student plainly that the
  data is from `<date>` and needs a fresh sign-in;
- **never** present stale data as current.

## 4. CLI changes (`src/cli.py`)

- New flag `--pick`: interactive course chooser driven by `Store.search_catalog`. Type a code, part
  of a name, or a code prefix; shows matches with an indicator for whether the course is in the
  student's curriculum semester, elsewhere in the curriculum, or outside it entirely. All three are
  selectable — a repeat from an earlier semester is a first-class case, not an error.
- New flag `--track`/`--untrack` to manage the auto-refreshed set.
- Read sections from `Store` first; fall back to `data/sections.json`, then to fixtures.
- Print data freshness prominently: `הנתונים עודכנו לאחרונה: 2026-08-30 07:00 (לפני 3 שעות)`.
  If anything selected is stale or `ok=False`, warn in a box before building the schedule.
- When a chosen course is not in the student's curriculum semester, note it as **information**
  ("קורס זה משויך לסמסטר 4 בתוכנית — נלקח כהשלמה") and continue. Never block.

## 5. Tests

Extend `tests/`, all offline:
- `parse_catalog` against a real saved catalog page fixture; assert the course count and that codes
  and names round-trip, including names containing quotes and parentheses.
- `Store`: save/load round-trip, staleness boundaries (exactly at max_age, just over, just under),
  `ok=False` counting as stale, tracked-set union/dedup.
- Change detection: added group, removed group, lecturer change, time change, no-change → empty list.
- Failed refresh must not destroy the previously stored course.
- `search_catalog` ranking: exact code beats prefix beats name substring.
