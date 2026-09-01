# Spec — make the tool work for any faculty, not just Software Engineering

The student reframed the project: *"This isn't just for me — I want it usable by a student from any
faculty, so the full catalog is the right scope."*

## The audit — what still assumes Software Engineering

Measured, not guessed:

| assumption | evidence | severity |
| --- | --- | --- |
| **credits come from `curriculum.json`** | **493 of 571 catalog courses (86%) are not in it**, so they report `credits: 0.0`. Totals are meaningless for anyone outside SE. | **blocking** |
| prerequisites come from `curriculum.json` | same 86% get no prerequisite checking at all | major |
| tied courses (`tied_with`) come from `curriculum.json` | a non-SE student gets no all-or-nothing enforcement | major |
| step 2's course list is built from `curriculum.json` | a non-SE student sees an **empty** course list in the UI | **blocking** |
| `profile.json` defaults to הנדסת תוכנה / year 3 / semester 5 | wrong defaults for everyone else | minor |
| year+term → `curriculum_semester` assumes an 8-semester program | breaks for 6- or 10-semester programs | major |
| the six course codes appear in comments, `--help` examples and metavars | cosmetic only — **no logic depends on them** (verified) | cosmetic |

**What already works, verified:** the scheduling core is fully faculty-agnostic. Solving over four
pure non-SE courses (11001 אלגברה, 11002 אלגברה מ, 11003 חדו"א 1, 11005 חדו"א 2) returned
**2614 feasible combinations, min_days 4**, with real lecturers, rooms and times. The parser,
store, scheduler, viability and attendance logic never look at the curriculum.

## The fix — the yedion already has everything

`S_CourseDetails` is publicly readable like the other endpoints, and carries per course:

```
GET fireflyweb.aspx?prgname=S_CourseDetails&arguments=-N<course>,-N<sem>,-N<kind>,-N<group>,-N
```

```
פרשיית לימוד 61753 אלגוריתמים  4  2  -  -  5.0 נ"ז
נקודות זכות : 5.00     שעות סמסטריאליות : 4.00     סוג קורס : הרצאה
שפת הוראה של הקורס : עברית
מטרת הקורס היא ...                       <- description
תנאי קדם לנושא | סוג הקשר | אוכלוסייה לגביה תקף | נושא נקשר | חליפי   <- prerequisites table
```

So `curriculum.json` stops being a requirement and becomes **optional enrichment**.

### 1. `src/yedion_http.py` + `src/parser.py`

```python
# yedion_http
def details_url(code, semester_code="1", kind_code="1", group_id="0") -> str
def fetch_details(self, code: str, group_id: str = "0", kind_code: str = "1") -> str
```

```python
# parser
class CourseDetails(NamedTuple):
    code: str
    name: str
    credits: float | None          # "נקודות זכות : 5.00" -> 5.0
    hours: dict[str, float]        # {"he":4,"te":2,"ma":0,"pr":0} from the פרשיית לימוד line
    weekly_hours: float | None     # "שעות סמסטריאליות"
    language: str                  # "עברית"
    description: str
    prerequisites: list[dict]      # [{"code","name","relation","alternative"}]
    warnings: list[str]

def parse_course_details(html: str, code: str) -> CourseDetails
```

Parsing rules: the `פרשיית לימוד` line is `<code> <name> <he> <te> <ma> <pr> <credits> נ"ז` where a
missing component is `-`. Take `נקודות זכות` as authoritative for credits when both appear.
Everything optional — a missing field is `None`/empty plus a warning, never an exception.

### 2. `src/store.py`

Store details alongside sections: `data/db/details.json`, keyed by course code, with its own
`fetched_at`. **Details change far less often than timetables**, so they get their own staleness
window (default 7 days) — the daily job must not double its request count for data that rarely moves.

```python
def save_details(self, code: str, details: dict, fetched_at: str) -> None
def load_details(self, code: str) -> dict | None
def details_stale(self, code: str, max_age_hours: float = 24 * 7) -> bool
```

### 3. Credits and prerequisites become curriculum-independent

Everywhere the app currently reads credits or prerequisites from `curriculum.json`, the order becomes:

1. `curriculum.json` if the course is there (richer: elective clusters, tied courses, replacements)
2. otherwise the stored yedion details
3. otherwise `None`, and the UI shows `—` rather than a misleading `0.0`

**`0.0` must never be displayed for "unknown".** A credit total that silently omits 86% of courses
is worse than one that says it does not know.

### 4. Step 2 must work with no curriculum at all

`GET /api/semester/<sem>/courses` currently returns curriculum courses only. Add
`GET /api/catalog/browse?prefix=&q=&limit=` over the stored catalog, and have the UI fall back to it
whenever the curriculum yields nothing for the chosen program. A student whose program is not in
`rec.pdf` must still be able to find and select courses — via search and code prefix, which is how
they think about it anyway.

The UI must not present the curriculum as mandatory. When it is absent, say so once, plainly
("תוכנית הלימודים של המחלקה אינה טעונה — אפשר לבחור כל קורס מהקטלוג"), and carry on.

### 5. Program-agnostic semester handling

`curriculum_semester` is an SE-specific notion. Where the curriculum is absent:
- year+term still select which *catalog* courses to show (via the semester filter on meetings)
- no attempt to map to a curriculum semester; the field becomes optional everywhere
- `profile.example.json` gains a comment saying the curriculum is optional

### 6. `refresh.py`

`--all` additionally refreshes **details** for courses whose details are stale (7-day window),
after the timetable pass, with the same politeness delay. Report both counts separately.

## Out of scope

Visual design. Still deferred at the student's request.

## Tests (`tests/test_multifaculty.py`, do not modify existing test files)

- `parse_course_details` against a saved real details page: credits 5.0, hours he=4/te=2,
  language, a non-empty description, and at least one prerequisite row.
- A details page with no credits line yields `credits=None` plus a warning, never an exception.
- Store round-trip for details, and the 7-day staleness window.
- Credits resolution order: curriculum wins; falls back to yedion details; `None` when neither.
- **`0.0` is never returned for unknown credits** — regression guard for the misleading total.
- `/api/solve` over four non-curriculum courses returns a feasible schedule (the 11001/11002/
  11003/11005 case) and non-zero credits once details are stored.
- `/api/catalog/browse` returns catalog entries with no curriculum loaded.
- Everything offline: inject a fake fetcher, use saved pages.
