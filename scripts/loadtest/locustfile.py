"""
locustfile.py — one simulated student = one realistic SlotWise session.

    pip install -r requirements-loadtest.txt
    locust -f scripts/loadtest/locustfile.py --host https://slotwise.co.il

Run it from the "load test" workflow (.github/workflows/loadtest.yml), at a
quiet hour. See DEPLOY.md, "Load testing", for what the numbers mean.

The journey is the request sequence src/web/static/app.js actually sends, in
the same order, read from the code on 2026-10-18:

1. ``GET /`` and the static files the page references (style.css, theme.js,
   app.js, the icons) plus the fonts style.css pulls in. There is no CDN in
   front of Cloud Run any more, so gunicorn serves these too.
2. ``GET /api/bootstrap`` (``fetchBootstrap``), then ``GET /api/catalog/meta``
   (``fetchCatalogMeta``, fired from the bootstrap handler).
3. The student picks a programme and a semester, and ``syncData`` fires:
   ``GET /api/semester/<n>/courses``, ``GET /api/program/electives``,
   ``POST /api/courses`` and ``POST /api/solve``.
4. Every change after that goes through ``syncData`` again. A course toggle
   changes the codes, so it sends ``POST /api/courses`` *and*
   ``POST /api/solve``; a preference change (days, Friday, a blocked window,
   earliest/latest) sends only ``POST /api/solve``.

The programme, semester, term and year are not invented: they come from the
server's own ``/api/bootstrap``, and the course codes from its
``/api/semester/<n>/courses`` — the same lists a student clicks in. So the
payloads stay real as the nightly catalog changes.

**Read-only.** Every request here is a GET, or a POST that only reads
(``/api/courses``, ``/api/solve``). ``/api/courses`` is sent with
``fetch_missing: false`` — the browser sends ``true``, but a hosted instance
has the network pinned off in wsgi.py anyway, so on the live site the two do
the same work; ``false`` keeps this file from ever asking a server to fetch
from the yedion if it is pointed at one that could. Nothing here calls the
catalog search/browse endpoints (they are for the "other programme" path),
and there is no scrape endpoint left to call.
"""

from __future__ import annotations

import random
import re
import time
from urllib.parse import quote, urlsplit

from locust import HttpUser, between, task

#: How many /api/solve calls one session makes, initial one included.
SOLVES_PER_SESSION = (10, 15)
#: Think time between two changes, in seconds.
THINK_SECONDS = (2.0, 5.0)
#: Server-side cap (api.MAX_CODES). A selection never goes above it.
MAX_CODES = 20

#: Fallbacks for when /api/bootstrap does not say. Winter term of תשפ"ז.
DEFAULT_TERM = "א"
DEFAULT_YEAR = 'תשפ"ז'

ASSET_RE = re.compile(r'(?:src|href)="(/static/[^"]+)"')
FONT_RE = re.compile(r'url\("?(fonts/[^")]+)"?\)')


def _q(value: str) -> str:
    return quote(value or "", safe="")


class Student(HttpUser):
    """One student: opens the site, picks a semester, and plays with it."""

    # Between two whole sessions of the same simulated user. Short, so the
    # number of users is close to the number of students active at once.
    wait_time = between(5, 15)

    @task
    def session(self) -> None:
        self.load_page()
        boot = self.get_json("/api/bootstrap", "/api/bootstrap")
        self.get_json("/api/catalog/meta", "/api/catalog/meta")
        if boot is None:
            return

        identity = self.pick_identity(boot)
        if identity is None:
            return
        program, sem, term, year = identity
        self.think()

        sem_data = self.get_json(
            f"/api/semester/{_q(sem)}/courses?program={_q(program)}"
            "&intake=&specialization=&route=",
            "/api/semester/[n]/courses",
        )
        self.get_json(
            f"/api/program/electives?program={_q(program)}"
            "&intake=&specialization=&route=&secondary=",
            "/api/program/electives",
        )
        pool = self.usable_codes(sem_data)
        if not pool:
            return

        # What applyRecommendedDefaults ticks: the semester's offered courses.
        codes = pool[:MAX_CODES]
        prefs = {"target_days": 6, "forbid_friday": False, "blocked": []}
        self.post_courses(codes, term, year, program)
        self.post_solve(codes, term, year, program, prefs)

        for _ in range(random.randint(*SOLVES_PER_SESSION) - 1):
            self.think()
            if random.random() < 0.6 and len(pool) > 1:
                codes = self.toggle(codes, pool)
                self.post_courses(codes, term, year, program)
            else:
                self.tweak(prefs)
            self.post_solve(codes, term, year, program, prefs)

    # ------------------------------------------------------------------ page

    def load_page(self) -> None:
        with self.client.get("/", name="/", catch_response=True) as res:
            if res.status_code != 200:
                res.failure(f"HTTP {res.status_code}")
                return
            html = res.text
        for asset in dict.fromkeys(ASSET_RE.findall(html)):
            path = urlsplit(asset).path
            body = self.get_static(asset, path)
            if path.endswith("/style.css") and body:
                for font in dict.fromkeys(FONT_RE.findall(body)):
                    self.get_static(f"/static/{font}", f"/static/{font}")

    def get_static(self, url: str, name: str) -> str:
        res = self.client.get(url, name=name)
        return res.text if res.status_code == 200 and name.endswith(".css") else ""

    # ------------------------------------------------------------- identity

    @staticmethod
    def pick_identity(boot: dict) -> tuple[str, str, str, str] | None:
        """A programme with a curriculum, and a semester of the current term.

        Programmes with intakes (applied maths) and "other" need an extra step
        in the UI and fall back to catalog browsing, so they are left out.
        """
        defaults = boot.get("defaults") or {}
        term = str(defaults.get("term") or DEFAULT_TERM)
        year = str(defaults.get("academic_year") or DEFAULT_YEAR)
        by_program = boot.get("semesters_by_program") or {}
        programs = [
            str(p.get("id") or "")
            for p in boot.get("programs") or []
            if p.get("has_curriculum") and not p.get("intakes")
            and by_program.get(str(p.get("id") or ""))
        ]
        if not programs:
            return None
        program = random.choice(programs)
        rows = [
            r for r in by_program[program]
            if str(r.get("term") or "") == term and r.get("course_count")
        ]
        if not rows:
            return None
        return program, str(random.choice(rows)["semester"]), term, year

    @staticmethod
    def usable_codes(sem_data: dict | None) -> list[str]:
        courses = (sem_data or {}).get("courses") or []
        return [
            str(c["code"])
            for c in courses
            if c.get("code") and c.get("selectable") and c.get("offered")
            and c.get("has_data")
        ]

    # -------------------------------------------------------------- changes

    @staticmethod
    def toggle(codes: list[str], pool: list[str]) -> list[str]:
        """Untick one course, or tick back one that is not selected."""
        off = [c for c in pool if c not in codes]
        if off and (len(codes) <= 2 or random.random() < 0.5):
            return codes + [random.choice(off)]
        drop = random.choice(codes)
        return [c for c in codes if c != drop]

    @staticmethod
    def tweak(prefs: dict) -> None:
        """One preference change, of the kind the step-3 controls make."""
        kind = random.choice(("days", "friday", "blocked", "hours"))
        if kind == "days":
            prefs["target_days"] = random.choice((3, 4, 5, 6))
        elif kind == "friday":
            prefs["forbid_friday"] = not prefs["forbid_friday"]
        elif kind == "blocked":
            if prefs["blocked"]:
                prefs["blocked"] = []
            else:
                day = random.randint(1, 5)
                start = random.choice((8, 10, 12, 14)) * 60
                prefs["blocked"] = [[day, start, start + 120]]
        elif "earliest" in prefs:
            prefs.pop("earliest", None)
            prefs.pop("latest", None)
        else:
            prefs["earliest"] = random.choice((8, 9, 10)) * 60
            prefs["latest"] = random.choice((16, 17, 18)) * 60

    # ------------------------------------------------------------- requests

    def post_courses(self, codes, term, year, program) -> None:
        self.post_json(
            "/api/courses",
            {
                "codes": list(codes),
                "semester": term,
                "year": year,
                "program": program,
                "intake": "",
                "fetch_missing": False,  # see the module docstring
            },
        )

    def post_solve(self, codes, term, year, program, prefs) -> None:
        # buildSolveBody(), field for field.
        body = {
            "codes": list(codes),
            "semester": term,
            "year": year,
            "program": program,
            "intake": "",
            "target_days": prefs["target_days"],
            "ranked": {},
            "blocked": prefs["blocked"],
            "forbid_friday": prefs["forbid_friday"],
            "top_n": 5,
            "allow_soft_conflicts": False,
        }
        for key in ("earliest", "latest"):
            if key in prefs:
                body[key] = prefs[key]
        self.post_json("/api/solve", body)

    def get_json(self, url: str, name: str) -> dict | None:
        with self.client.get(url, name=name, catch_response=True,
                             headers={"Accept": "application/json"}) as res:
            return self._check(res)

    def post_json(self, url: str, body: dict) -> dict | None:
        with self.client.post(url, name=url, json=body, catch_response=True,
                              headers={"Accept": "application/json"}) as res:
            return self._check(res)

    @staticmethod
    def _check(res) -> dict | None:
        """The page's own rule (app.js ``request``): non-2xx or ok:false fails."""
        try:
            data = res.json()
        except ValueError:
            data = None
        if res.status_code >= 400 or not isinstance(data, dict) or data.get("ok") is False:
            detail = (data or {}).get("detail") if isinstance(data, dict) else ""
            res.failure(f"HTTP {res.status_code} {detail or ''}".strip())
            return None
        res.success()
        return data

    @staticmethod
    def think() -> None:
        # Locust monkey-patches time.sleep with gevent, so this yields.
        time.sleep(random.uniform(*THINK_SECONDS))
