# Yedion ground truth — verified against a live instance

**This document supersedes SPEC.md section 4 wherever they disagree.** It was produced by
reconnaissance against a *publicly reachable* instance of the exact same product that Braude runs
(the Yedion / מידע-נט system by yedion.co.il), namely the Tel-Aviv Yaffo Academic College instance
at `https://mtamn.mta.ac.il/yedion/`. Braude's `Enter_Search` page (see `Screenshot.png`) is visually
identical panel-for-panel, so the templates are the same family.

**Caveat that must stay in the code:** the samples in `tests/fixtures/real_yedion/` are from MTA,
not Braude. The *structure* is what we rely on; institution-specific wording may differ slightly.
The parser must therefore stay tolerant, and the first real Braude login must dump raw HTML to
`data/raw/` so we can diff against these fixtures.

---

## 1. The search is a plain GET. No form-filling required.

The Enter_Search page posts a form with two hidden fields, `PRGNAME` and `ARGUMENTS`, but the same
endpoint answers **GET** requests. Verified working:

```
https://info.braude.ac.il/yedion/fireflyweb.aspx?prgname=S_LOOK_FOR_NOSE&arguments=-N61753
```

That is dramatically more robust than clicking through the WebForms UI. Use it as the primary
strategy; keep the form-filling path only as a fallback.

### The full API surface of the search page

Harvested from the `data-progname` / `data-arguments` attributes on the page's buttons:

| prgname | arguments | what it does |
| --- | --- | --- |
| `S_LOOK_FOR_NOSE` | `-N<course_code>` | **search by course code — this is the one we need** |
| `S_LOOK_FOR_NOSE_AB` | `-A<hebrew_letter>` | list all courses starting with a letter |
| `S_YFineDate` | `R1C7,R1C5,R1C6` | search by day + hours |
| `S_MASLUL` | `R1C9` | search by track (מגמה) |
| `S_EXAMS` | `R1C28,R1C29,R1C30` | exam dates |
| `S_GROUP` | `R1C20,R1C21,R1C22` | search by group |
| `S_CourseDetails` | `-N<course>,-N<sem>,-N<kind>,-N<group>,-N` | drill into one group |
| `Enter_Search` | `-A,R1C19,-AT` | apply the semester filter |
| `Enter_Search` | `-A,,-A,ChangeYear` | switch academic year |

Argument type prefixes: `-N` numeric, `-A` alphanumeric. Course codes always take `-N`.

Form control ids on the search page (confirmed twice — once on the live MTA page, once in the
`AvielMalayev/BraudeCurriculumBot` repo which drives the real Braude instance):

- `#SubjectCode` — the course-code text input (`maxlength=7`)
- `#searchButton` — the submit button (Braude bot)
- `#ChangeYear` — the academic-year `<select>`
- `#R1C19` — the semester filter `<select>`

## 2. Results are Bootstrap DIV grids, **not `<table>` elements**

This is the single most important correction. A `<table>`-based parser finds **zero** rows.
Every result page contains `<div class="row">` / `<div class="col">` and no `<table>` at all.

### Course result page shape (`S_LOOK_FOR_NOSE`)

```html
<div class="Table container fcontainer">
  <div class="row"><div class="col">
    <h2 class="TextAlignCenter"> קורס  מתמטיקה ב' שנה"ל תשפ"ז</h2>   <!-- course name + year -->
  </div></div>
  <div class="row"><div class="col">

    <!-- ===== one block PER GROUP, repeated ===== -->
    <div class="TextAlignRight">
      קורס מסוג שיעור/ציון קורס                            <!-- KIND, free text -->
      <span style="color: blue"> קבוצה : 27103001 &nbsp; </span>   <!-- GROUP ID -->
      מרצה הקורס : ד&quot;ר שפיגל הדר                        <!-- LECTURER -->
      <button data-progname="S_CourseDetails"
              data-arguments="-N271030,-N2,-N1,-N27103001,-N">פרטים נוספים</button>
    </div>
    <strong><span style="color: green">
       שיעור א' - מסלול בוקר ( קבוצות הקשורות לקורס זה : 27103002 )
    </span></strong>                                        <!-- GROUP LABEL + LINKED GROUPS -->
    <div class="card ... MasterTable"><h2 class="card-header-H2"> מערכת שעות </h2>
      <div class="Table container ncontainer WithSearch">
        <div class="row">                                   <!-- HEADER ROW -->
          <div class="col">סמסטר</div>
          <div class="col">יום בשבוע</div>
          <div class="col">שעת התחלה </div>
          <div class="col">שעת סיום</div>
          <div class="col">מרצה</div>
          <div class="col">חדר לימוד</div>
        </div>
        <div class="row">                                   <!-- one DATA ROW per MEETING -->
          <div class="col">&nbsp;ב</div>
          <div class="col">&nbsp;יום שני</div>
          <div class="col">&nbsp;14:15</div>
          <div class="col">&nbsp;15:45</div>
          <div class="col">&nbsp;ד&quot;ר שפיגל הדר</div>
          <div class="col">&nbsp;</div>
        </div>
      </div>
    </div>
    <br>
    <!-- ===== next group block ===== -->
  </div></div>
</div>
```

## 3. Field-by-field extraction rules

| Model field | Where it comes from |
| --- | --- |
| `Course.name` | `h2.TextAlignCenter`, strip the leading `קורס` and the trailing `שנה"ל תשפ"X` |
| `Group.kind` | text after `קורס מסוג` in the `div.TextAlignRight` |
| `Group.group_id` | text after `קבוצה :` inside `span[style*="color: blue"]` |
| `Group.lecturer` | text after `מרצה הקורס :` in the same `div.TextAlignRight` |
| `Group.linked_to` | ids listed after `קבוצות הקשורות לקורס זה :` in the green `<strong><span>` |
| `Group.note` | the green label text with the linked-groups clause removed (e.g. `שיעור א' - מסלול בוקר`) |
| `Meeting.day` | col 2, e.g. `יום שני` |
| `Meeting.start` | col 3, e.g. `14:15` |
| `Meeting.end` | col 4, e.g. `15:45` — **separate columns, NOT a single range string** |
| `Meeting.room` | col 6, `חדר לימוד`, often empty |
| semester of meeting | col 1 (`א` / `ב` / `קיץ`) — **filter on this** |

### Kind mapping (Yedion wording → our KIND_* constants)

| Yedion text | numeric code seen | our constant |
| --- | --- | --- |
| `שיעור/ציון קורס`, `שיעור`, `הרצאה` | 1 | `KIND_LECTURE` = הרצאה |
| `תרגיל`, `תרגול` | 7 | `KIND_TUTORIAL` = תרגול |
| `מעבדה`, `מעב'` | — | `KIND_LAB` = מעבדה |
| `פרויקט`, `פרוייקט` | — | `KIND_PROJECT` = פרויקט |
| `מפגש לימודי`, anything else | 18 | `KIND_OTHER` = אחר |

The numeric code is the 3rd argument of the `S_CourseDetails` button and is a useful cross-check,
but **the Hebrew text label is the primary signal** — codes may differ per institution.

## 4. Text-cleaning rules that are NOT optional

1. Every `div.col` value is prefixed with `&nbsp;` → strip ` ` as well as ordinary whitespace.
2. Lecturer names contain `&quot;` (`ד&quot;ר` → `ד"ר`). Use `html.unescape` on all extracted text.
3. The group label may contain a nested parenthetical; strip `( קבוצות הקשורות ... )` before using
   it as `note`.
4. Group ids are `<course_code><NN>` concatenated (course 271030 → group `27103001`). Keep the full
   string as `group_id`; do not try to shorten it.
5. Day strings are full names with a `יום` prefix (`יום שני`). Braude's own catalog uses letters
   (`יום ג`). Support both.

## 5. Distinguishing a header row from a data row

A `div.row` inside `div.Table.ncontainer` is a **header** if its first `div.col` text (after cleaning)
equals `סמסטר`. Otherwise it is a meeting. Do not rely on position — some courses have a leading
blank row.

## 6. Empty / not-offered results

Querying a code that does not exist, or is not offered in the selected year, returns a **200 page
with the right title and zero group blocks**. That is the signal for "not offered" — it is NOT an
error. Report it to the student explicitly. This is exactly how we will find out whether
**61753 אלגוריתמים is actually opened in סמסטר א' תשפ"ז**.

## 7. Fixtures saved in `tests/fixtures/real_yedion/`

| file | what it exercises |
| --- | --- |
| `enter_search_page.html` | the search form, all progname/arguments pairs, year + semester selects |
| `single_group.html` | one group, one meeting, empty room (course 93263) |
| `three_groups.html` | three groups (course 651112) |
| `four_groups.html` | four groups (course 211164) |
| `multi_group_lecture_tutorial.html` | **the important one** — course 271030 מתמטיקה ב': 2 lecture groups + 3 tutorial groups, with `קבוצות הקשורות` linking lectures to tutorials |

The parser must parse all five without warnings other than genuinely-empty optional fields.

---

## 8. Academic-year switching — VERIFIED end-to-end

Your `Screenshot.png` shows Braude defaulting to **תשפ"ו** while the year `<select>` offers
**2027 - תשפ"ז**. So the scraper *must* switch the year before scraping, or it will silently
return last year's timetable. This was verified against the live MTA instance:

**Step 1 — switch the year (POST, sets session state):**

```
POST /yedion/fireflyweb.aspx
    PRGNAME   = Enter_Search
    ARGUMENTS = -A,,-A,ChangeYear
    ChangeYear = 2026            <-- the gregorian year from the <option value="...">
```

Result: the page header flipped from `חיפוש קורסים במערכת תשפ"ז` to `חיפוש קורסים במערכת תשפ"ו`
and both year `<select>` elements came back with `2026` selected.

**Step 2 — every subsequent GET inherits that year from the session cookie:**

```
GET /yedion/fireflyweb.aspx?prgname=S_LOOK_FOR_NOSE&arguments=-N271030
```

returned `קורס מתמטיקה ב' שנה"ל תשפ"ו` with **15** groups, where the same GET before the switch
returned `שנה"ל תשפ"ז` with **5**. The year is genuinely session state, not a URL parameter.

### What this means for the scraper

1. Log in via Playwright (persistent context) — the human types the credentials.
2. Navigate to `Enter_Search`.
3. Set the year. Preferred: drive the real `#ChangeYear` select and click the `מעבר שנה` button.
   Fallback: issue the POST above through the authenticated `page.request` context.
4. **Assert** the page header now names the year you wanted. Abort loudly if it does not — a
   silently-wrong year is the worst possible failure for this tool.
5. Then `page.goto()` the plain `S_LOOK_FOR_NOSE` URL per course code.
6. **Re-verify per course page**: the `h2.TextAlignCenter` contains `שנה"ל תשפ"X`. If it does not
   match the requested year, raise rather than parse.

Neta needs **תשפ"ז = 2027** (academic year 2026/27).

### Semester filtering

Do **not** rely on the `R1C19` semester filter control. Every meeting row carries its own
`סמסטר` column (`א` / `ב` / `קיץ`), so filter client-side after parsing. That is both simpler and
verifiable, and it is how the tool will determine whether **61753 אלגוריתמים** — a curriculum
semester-4 (spring) course — is actually opened in **סמסטר א'**.
