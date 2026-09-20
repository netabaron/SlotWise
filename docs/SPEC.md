# SlotWise — Interface Spec (authoritative)

Every module implements EXACTLY the signatures below. Do not invent alternates.
Python 3.14, Windows. Hebrew content everywhere — always open files with `encoding="utf-8"`.

Project root: `C:\Users\netab\.claude\projects\SlotWise`

```
SlotWise/
  data/curriculum.json      # already written — do not modify
  data/profile.json         # student intake answers — already written
  data/sections.json        # scraper output cache (created at runtime)
  data/raw/                 # raw HTML dumps from the yedion (created at runtime)
  src/models.py
  src/curriculum.py
  src/scraper.py
  src/parser.py
  src/scheduler.py
  src/render.py
  src/cli.py
  main.py
  tests/test_scheduler.py
  tests/fixtures/sample_sections.json
```

---

## 1. `src/models.py` — data model (pure, no I/O)

Use `@dataclass`. Days are ints: **1=ראשון, 2=שני, 3=שלישי, 4=רביעי, 5=חמישי, 6=שישי**.
Times are **minutes from midnight** (int). 08:30 → 510.

```python
DAY_NAMES_HE = {1:"ראשון",2:"שני",3:"שלישי",4:"רביעי",5:"חמישי",6:"שישי"}

# component type of a class meeting
KIND_LECTURE  = "הרצאה"
KIND_TUTORIAL = "תרגול"
KIND_LAB      = "מעבדה"
KIND_PROJECT  = "פרויקט"
KIND_OTHER    = "אחר"

@dataclass(frozen=True)
class Meeting:
    day: int                # 1..6
    start: int              # minutes from midnight
    end: int                # minutes from midnight
    room: str = ""
    building: str = ""
    def overlaps(self, other: "Meeting") -> bool: ...   # same day AND [start,end) intersect
    def duration(self) -> int: ...                      # minutes

@dataclass
class Group:
    """One registerable section (קבוצה) of one component of a course."""
    course_code: str
    group_id: str           # קבוצה number as shown in the yedion, e.g. "11"
    kind: str               # one of the KIND_* constants
    lecturer: str           # מרצה name as shown, "" if unknown
    meetings: list[Meeting]
    linked_to: list[str] = field(default_factory=list)  # group_ids that MUST be taken with this one
    note: str = ""
    def days(self) -> set[int]: ...
    def conflicts_with(self, other: "Group") -> bool: ...  # any meeting pair overlaps

@dataclass
class Course:
    code: str
    name: str
    credits: float
    groups: list[Group]
    tied_with: list[str] = field(default_factory=list)  # course codes that must be taken together
    def kinds(self) -> list[str]: ...        # distinct component kinds present, ordered
    def groups_of(self, kind: str) -> list[Group]: ...
    def lecturers(self) -> list[str]: ...    # unique, sorted, non-empty

@dataclass
class Selection:
    """One complete choice: for each course, one Group per required kind."""
    groups: list[Group]
    def all_meetings(self) -> list[Meeting]: ...
    def days_used(self) -> set[int]: ...
    def is_feasible(self) -> bool: ...       # no two groups conflict

@dataclass
class ScoredSchedule:
    selection: Selection
    score: float                 # higher = better
    breakdown: dict[str, float]  # {"lecturer":..,"days":..,"gaps":..,"compactness":..}
    days_count: int
    gap_minutes: int
    lecturer_hits: int           # how many courses got a top-ranked lecturer
    lecturer_total: int
```

## 2. `src/curriculum.py`

```python
def load_curriculum(path="data/curriculum.json") -> dict: ...
def semester_courses(curr: dict, semester: str) -> list[dict]: ...
def find_course(curr: dict, code: str) -> dict | None:
    """Search ALL semesters AND all elective clusters. Returns the course dict or None."""
def tied_group(curr: dict, code: str) -> list[str]:
    """Return the full set of course codes tied to `code` (including itself), or [code]."""
def check_prerequisites(curr: dict, code: str, passed: set[str]) -> tuple[bool, list[str]]:
    """Returns (ok, missing_codes)."""
```

## 3. `src/scraper.py` — Playwright, manual login

CRITICAL RULES:
- **NEVER** ask for, store, log, or transmit the student's username/password. The human types
  them into the real browser window. The script only waits.
- Use a **persistent** browser context at `data/.browser_profile` so the session survives re-runs.
- Always dump the raw HTML of every page fetched into `data/raw/<code>_<n>.html` BEFORE parsing.
  The yedion's exact markup is unknown; the raw dump is what lets us fix the parser later.
- Be gentle: sequential requests, ~1.5s delay between course lookups. No parallel hammering.

```python
LOGIN_URL  = "https://login.braude.ac.il/logon/LogonPoint/tmindex.html"
SEARCH_URL = "https://info.braude.ac.il/yedion/fireflyweb.aspx?prgname=Enter_Search"

class BraudeScraper:
    def __init__(self, profile_dir="data/.browser_profile", raw_dir="data/raw",
                 headless=False, year: str | None = None): ...
    def __enter__(self) / __exit__(...)                 # context manager, closes browser
    def open_and_wait_for_login(self, timeout_s=600) -> bool:
        """Opens LOGIN_URL in a visible window, prints clear Hebrew+English instructions,
        then polls until the browser lands on an info.braude.ac.il page (or timeout).
        Returns True on success."""
    def fetch_course_html(self, code: str) -> str:
        """Navigate to SEARCH_URL, fill the 'חיפוש לפי קוד קורס' input with `code`,
        submit, return the result page HTML. Dumps to raw_dir first."""
    def scrape(self, codes: list[str]) -> dict[str, str]:
        """{code: html}. Continues past individual failures, collecting them in .errors."""
```

Selector strategy: the yedion is a legacy ASP.NET WebForms page (`fireflyweb.aspx`).
Do **not** hardcode a single brittle selector. Try, in order, and log which one worked:
1. an `<input type="text">` inside the panel whose text contains `קוד קורס`
2. `input[name*="param"]`, `input[id*="course"]`, `input[id*="Course"]`
3. the first visible text input on the page
Submit by pressing Enter, then falling back to clicking the nearest `input[type=submit]`/`button`.
If nothing matches, save the HTML, raise `ScraperSelectorError` with the dump path.

## 4. `src/parser.py` — HTML → model

```python
class ParseResult(NamedTuple):
    course: Course | None
    warnings: list[str]

def parse_course_page(html: str, code: str, fallback_name: str = "") -> ParseResult: ...
def parse_time_range(text: str) -> tuple[int, int] | None:
    """'08:30-10:00', '8:30 - 10:00', '0830-1000' -> (510, 600). None if unparseable."""
def parse_day(text: str) -> int | None:
    """'א' / 'יום א' / 'ראשון' / '1' -> 1 ... 'ו'/'שישי' -> 6."""
def classify_kind(text: str) -> str:
    """Map Hebrew words to KIND_*: הרצאה/שיעור->הרצאה, תרגיל/תרגול->תרגול,
    מעבדה/מעב'->מעבדה, פרויקט/פרוייקט->פרויקט, else אחר."""
def load_sections(path="data/sections.json") -> dict[str, Course]: ...
def save_sections(courses: dict[str, Course], path="data/sections.json") -> None: ...
```

Parsing must be **table-shape agnostic**: find all `<table>`s, score each by how many of its
header cells match {קבוצה, מרצה, יום, שעה, סוג, בניין, חדר}, take the best-scoring table,
map columns by header text, and read rows. Rows that fail to yield a day+time are skipped
with a warning, never silently dropped.

## 5. `src/scheduler.py` — the engine

```python
@dataclass
class Preferences:
    target_days: int = 4
    preferred_lecturers: dict[str, list[str]] = field(default_factory=dict)
        # {course_code: [lecturer_name_ranked_best_first, ...]}
    blocked_windows: list[tuple[int,int,int]] = field(default_factory=list)
        # (day, start_min, end_min) the student is unavailable
    earliest: int = 0          # no class may start before this (minutes)
    latest: int = 24*60        # no class may end after this
    weights: dict[str, float] = field(default_factory=lambda: {
        "lecturer": 10.0, "days": 8.0, "gaps": 4.0, "compactness": 1.0})
    forbid_friday: bool = False

def enumerate_selections(courses: list[Course], prefs: Preferences,
                         limit: int = 200_000) -> Iterator[Selection]:
    """Backtracking over (course, kind) slots, one Group each.
    PRUNE as early as possible: reject a partial selection the moment a conflict,
    a blocked window, an earliest/latest violation, or a forbid_friday violation appears.
    Respects Group.linked_to. Raises SearchExhausted if `limit` partial nodes are exceeded."""

def score(sel: Selection, prefs: Preferences) -> ScoredSchedule: ...
    # lecturer:    per course, 1.0 for the #1 ranked lecturer, decaying by rank, 0 if unranked
    # days:        penalty = max(0, days_used - target_days)
    # gaps:        total minutes between consecutive meetings on the same day
    # compactness: rewards shorter total campus span per day
    # Final score = w.lecturer*L - w.days*D - w.gaps*(G/60) - w.compactness*(S/60)

def solve(courses: list[Course], prefs: Preferences, top_n: int = 5) -> list[ScoredSchedule]:
    """Enumerate, score, return the best `top_n`, sorted score-descending.
    If ZERO feasible selections exist, DO NOT return []. Instead call diagnose_infeasibility
    and raise Infeasible with a human-readable Hebrew+English explanation of which pair
    of courses/groups clashes."""

def diagnose_infeasibility(courses: list[Course], prefs: Preferences) -> list[str]:
    """Return concrete reasons, e.g.
    'קורס 61753 קבוצה 11 (הרצאה) מתנגש עם 61756 קבוצה 21 (תרגול) — יום ג 10:00-12:00'.
    Check pairwise course-level clashes: a course pair is IMPOSSIBLE if every group
    combination between them conflicts. Also report which constraint (earliest/latest/
    blocked/forbid_friday) eliminates all groups of a course."""
```

Correctness requirements the tests must cover:
- overlap detection is half-open `[start, end)` — a class ending 10:00 and one starting 10:00 do NOT conflict
- tied courses (61756/61757/62027) always appear together or not at all
- a course with a הרצאה and a תרגול must contribute exactly one group of EACH kind
- `linked_to` is respected in both directions
- gap minutes count only *within* a day, between consecutive meetings, never across days

## 6. `src/render.py`

```python
def render_terminal(sched: ScoredSchedule, courses: dict[str, Course]) -> str:
    """Weekly grid as aligned text. Hebrew day headers right-to-left order (א..ו)."""
def render_html(scheds: list[ScoredSchedule], courses: dict[str, Course],
                out_path: str, title: str = "מערכת שעות") -> str:
    """Self-contained RTL HTML file, one weekly grid per schedule, color per course,
    a score breakdown table, and a print stylesheet. Returns out_path.
    dir='rtl', lang='he', system font stack with Hebrew fallbacks."""
def render_lecturer_menu(course: Course) -> str:
    """Numbered list of lecturers for this course with the days/hours each one teaches,
    so the student can choose. This is what step 3 of the flow shows."""
```

## 7. `src/cli.py` + `main.py` — the interactive flow

Exact order, matching what the student asked for:
1. Load profile (`data/profile.json`). Confirm year/semester/target days.
2. Resolve the course codes for that semester from the curriculum.
3. If `data/sections.json` is missing or `--refresh` is passed → run the scraper
   (browser opens, student logs in manually), parse, save cache.
4. **For each course, print the available lecturers** (`render_lecturer_menu`) and ask the
   student to rank/choose. Accept: numbers ("1,3"), "any"/"" for no preference, "q" to quit.
5. Build `Preferences`, run `solve(...)`.
6. Print the top schedules to the terminal, write the HTML, print the file path.
7. On `Infeasible`, print the diagnosis and offer to relax: raise target_days, or drop a course.

Flags: `--refresh` (re-scrape), `--offline` (use cache/fixtures only, no browser),
`--top N`, `--days N`, `--html PATH`.

Every prompt and every error message: Hebrew first, English in parentheses.

## 8. `tests/test_scheduler.py`

pytest. Must run fully **offline** against `tests/fixtures/sample_sections.json`, which you
also write: a realistic synthetic dataset covering all 6 of this student's course codes
(11069, 61753, 61756, 61757, 61832, 62027) with 2-4 groups per component, some deliberately
conflicting, at least one `linked_to` pair, and the 61756/61757/62027 tie.
Cover: overlap edge cases (touching times), tied courses, one-per-kind, linked groups,
gap math, day counting, lecturer scoring order, infeasibility diagnosis, and a full
`solve()` end-to-end that returns a schedule using <= 4 days.
