#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/solver_sweep.py — ‏/api/solve על כל מסלול × סמסטר × התמחות/מסלול, מול מנייה מלאה.

נכתב ל-2026-10-23 (אימות הפותר אחרי ``fbd58c4``), ונשמר כדי להריץ אותו שוב
אחרי כל שינוי בפותר. הבדיקה הקבועה היא ``tests/test_solver_all_programmes.py``
(קטלוג קפוא, תקציב צמתים); הסקריפט הזה הוא המקבילה הכבדה מול הקטלוג האמיתי.

מה הוא עושה
------------
1. **תכנון** — כל מה ש-``/api/bootstrap`` מציע: מסלול × סמסטר בלוח שלו, כל
   מועד כניסה, וכל התמחות ומסלול התמחות מהסמסטר שבו בוחרים אותם (וגם "לא
   נבחר"). לכל אחד — רשימת ההמלצה של הדף, בדיוק כמו ב-app.js (העוזרים של
   ``tests/test_solver_all_programmes.py``).
2. **פתרון** — ארבע גרסאות לכל צירוף: ‏(a) ברירת המחדל של הדף; ‏(b) כל רכיבי
   הנוכחות חובה; ‏(c) דירוג מרצים בשני הקורסים הראשונים; ‏(d) יעד של 3 ימים.
   לכל אחת: סטטוס, זמן, צמתי חיפוש (כל ``_Budget.tick()``), ``timed_out``,
   מספר מערכות, ``feasible_count_capped``.
3. **מקור אמת** — המנייה המלאה של ``tests/test_solver_exactness.py``
   (``_build_slots`` + ``_pair_ok``, ניקוד ב-``score`` ומיון ב-``_sort_key``),
   בזרימה: בלי רשימה של כל העלים, כדי שלא תאכל את הזיכרון. עד 60 שניות חישוב
   לכל גרסה; כשנגמרו — "ref >60 s" ולא השוואה. ‏c ו-d פורשים את אותם עלים כמו
   a, ולכן כש-a חרג הם מדולגים. משווים: המערכות וסדרן, הניקוד, ``min_days``,
   ``target_reachable``, הספירה (עד המכסה) וה-viability של כל קבוצה.
4. **בדיקה חיה** (מצב נפרד, ``live``) — **בקשה אחת** ל-``/api/solve`` לכל מסלול ×
   סמסטר (בלי התמחות), ב-https://slotwise.co.il, **ברצף, שנייה אחת בין בקשה
   לבקשה**, ועוד ‏``/api/bootstrap`` אחד. קריאה בלבד; בערך 66 בקשות. גופי
   הבקשות נבנים מקומית מהקטלוג, ולכן יש לוודא שתאריך הקטלוג החי (בשורה
   הראשונה של הפלט) זהה למקומי.

בידוד
------
כל פתרון וכל מקור אמת רצים **בתהליך משלהם**, אחד אחרי השני: ‏60 שניות לפתרון
ו-100 לתהליך של מקור האמת (‏60 חישוב + טעינה), ומעל 1.5 GB זיכרון התהליך
נהרג. לפני כל תהליך הסקריפט מחכה לפחות ל-900 MB פנויים. האפליקציה רצה מול
תיקיית מסד **ריקה** (``<OUTDIR>/empty-store``), כמו התמונה המתארחת: ‏``data/db``
אינו נקרא ואינו נכתב (ראו בדיקת הקבע למה זה משנה בסמסטר ב'), ו-
``allow_network=False``.

    py -I scripts/solver_sweep.py run  data/catalog OUTDIR     # הכול; ניתן לחידוש
    py -I scripts/solver_sweep.py live OUTDIR/cases.json OUTDIR/live.jsonl
    py -I scripts/solver_sweep.py live OUTDIR/cases.json OUTDIR/live.jsonl --dry

‏OUTDIR מקבל ``cases.json`` (התכנון), ``results.jsonl`` (שורה לכל פתרון, כולל
‏``ref``), ``work/`` (התשובות המלאות) ו-``workers.log``. הרצה שנקטעה ממשיכה
מאיפה שעצרה. ‏``SOLVER_SWEEP_NO_REF=1`` מדלג על מקור האמת.

**כמה זמן:** נמדד 2026-10-23 — ‏132 צירופים × 4 = ‏528 פתרונות, ‏~31 דקות
(‏~12 פתרון, ~17 מקור אמת, שהוא בעיקר שמונה חריגות של 60 שניות). הבדיקה החיה:
כ-2 דקות.

קריאת התוצאות
--------------
* ‏**בחירה שאף קורס בה לא נבנה** (לכל הקודים אין קבוצות — כולם ב-
  ``not_offered``) מופיעה כאי-התאמה של "עלה אחד": ‏``/api/solve`` חוזר לפני כל
  חיפוש, ומקור האמת, שבדיקת הדיוק לעולם אינה מזינה בבחירה ריקה, סופר בחירה
  ריקה אחת כעלה. אין זו אי-התאמה של הפותר; ב-2026-10-23 היו 88 כאלה, כולן
  בסמסטר 8.
* ‏``timed_out`` עם ``any_truncated`` = המערכות עצמן נקטעו. ‏``timed_out`` בלי
  ``any_truncated`` = המערכות שלמות, ושלב מאוחר יותר (viability, הצעות ויתור)
  נעצר.
"""

from __future__ import annotations

import bisect
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOLVE_KILL_S = 60.0
REF_COMPUTE_S = 60.0
REF_KILL_S = 100.0
RSS_KILL_MB = 1500
MIN_FREE_MB = 900
VARIANTS = ["a_default", "b_all_required", "c_ranked", "d_target3"]
LIVE_BASE = "https://slotwise.co.il"
LIVE_GAP_S = 1.0

#: ‏תיקיית המסד הריקה. הדרייבר קובע אותה לכל התהליכים; תהליך שהורץ ידנית
#: מקבל תיקייה זמנית חדשה.
EMPTY_DB_ENV = "SOLVER_SWEEP_EMPTY_DB"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass


def _setup(catalog_dir: str):
    db = os.environ.get(EMPTY_DB_ENV) or tempfile.mkdtemp(prefix="solver-sweep-store-")
    os.environ["SLOTWISE_CATALOG_DIR"] = str(Path(catalog_dir).resolve())
    os.environ["SLOTWISE_DB_ROOT"] = str(db)
    for p in (str(ROOT / "tests"), str(ROOT / "src"), str(ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from src.web import api  # noqa: PLC0415 — אחרי הצבת הסביבה
    import test_solver_all_programmes as page  # noqa: PLC0415

    app = api.create_app({"allow_network": False}, serve_ui=False)
    return api, page, app, app.test_client()


# ==========================================================================
# 1. תכנון
# ==========================================================================
def _lecturers(course, kind):
    out = []
    for g in course.groups_of(kind):
        if g.lecturer and g.lecturer not in out:
            out.append(g.lecturer)
    return out


def plan(catalog_dir, out_path):
    api, page, app, client = _setup(catalog_dir)
    boot = client.get("/api/bootstrap").get_json()
    year = boot["defaults"].get("academic_year", "")
    max_codes = boot["limits"]["max_codes"]
    cases = []
    skipped = []
    for base in page.offered_cases(boot):
        n = int(base["semester"])
        spec = base["spec"]
        tracks = [("", "")]
        # ‏specializationShown() / routeGroup() ב-app.js.
        if spec and n >= int(spec.get("choose_from_semester") or 0):
            tracks = []
            for sp in [""] + list(spec["options"]):
                group = None
                for g in spec.get("routes") or []:
                    wanted = (g.get("applies_to") or {}).get("specialization") or []
                    if n < int(g.get("from_semester") or 0):
                        continue
                    if wanted and sp not in wanted:
                        continue
                    group = g
                    break
                routes = [""] + list(group["options"]) if group else [""]
                tracks += [(sp, r) for r in routes]
        for sp, route in tracks:
            case = dict(base, specialization=sp, route=route, year_he=year)
            case.pop("spec", None)
            case["id"] = base["id"] + (f"|{sp}" if sp else "") + (f"|{route}" if route else "")
            data = page.semester_list(client, base, sp, route)
            codes = page.recommended_codes(data, max_codes)
            case["codes"] = codes
            if not codes:
                skipped.append(case)
                continue
            info = page.courses_request(client, base, codes, year)["attendance"]
            case["att_default"] = page.page_attendance(info)
            case["att_all"] = {c: {k: True for k in kinds} for c, kinds in info.items()}
            with app.app_context():
                built, _p, _m = api._build_courses(codes, semester=base["term"], year=year,  # noqa: SLF001
                                                   program=base["program"], intake=base["intake"])
            # ‏(c): שני הקורסים הראשונים שיש להם מרצים, לכל סוג — האחרון ואז הראשון.
            ranked = {}
            for course in built:
                if len(ranked) == 2:
                    break
                per = {}
                for kind in course.kinds():
                    names = _lecturers(course, kind)
                    if names:
                        per[kind] = list(dict.fromkeys([names[-1], names[0]]))
                if per:
                    ranked[course.code] = per
            case["ranked"] = ranked
            case["n_groups"] = sum(len(c.groups) for c in built)
            cases.append(case)
    Path(out_path).write_text(json.dumps({"cases": cases, "skipped": skipped},
                                         ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(cases)} cases, {len(skipped)} with no recommended selection")


def body_for(page, case, variant):
    year = case["year_he"]
    if variant == "a_default":
        return page.solve_body(case, case["codes"], case["att_default"], year)
    if variant == "b_all_required":
        return page.solve_body(case, case["codes"], case["att_all"], year)
    if variant == "c_ranked":
        return page.solve_body(case, case["codes"], case["att_default"], year,
                               ranked=case["ranked"])
    if variant == "d_target3":
        return page.solve_body(case, case["codes"], case["att_default"], year, target_days=3)
    raise ValueError(variant)


# ==========================================================================
# 2. פתרון
# ==========================================================================
def solve(catalog_dir, cases_path, idx, variant, out_path):
    api, page, app, client = _setup(catalog_dir)
    case = json.loads(Path(cases_path).read_text(encoding="utf-8"))["cases"][int(idx)]
    body = body_for(page, case, variant)
    # חימום, כמו בדף לפני כל פתרון: ‏/api/courses.
    page.courses_request(client, case, case["codes"], case["year_he"])
    sch = api.scheduler_mod
    counter = {"n": 0}
    tick = sch._Budget.tick  # noqa: SLF001

    def counting(self):
        counter["n"] += 1
        return tick(self)

    sch._Budget.tick = counting  # noqa: SLF001
    t0 = time.perf_counter()
    res = client.post("/api/solve", json=body)
    elapsed = time.perf_counter() - t0
    data = res.get_json(silent=True) or {}
    out = {
        "status": res.status_code, "time_s": round(elapsed, 3), "nodes": counter["n"],
        "timed_out": data.get("timed_out"),
        "n_schedules": len(data.get("schedules") or []),
        "feasible_count": data.get("feasible_count"),
        "feasible_count_capped": data.get("feasible_count_capped"),
        "counts_truncated": data.get("counts_truncated"),
        "viability_skipped": data.get("viability_skipped"),
        "viability_truncated": data.get("viability_truncated"),
        "any_truncated": any(s.get("truncated") for s in data.get("schedules") or []),
        "min_days": data.get("min_days"),
        "target_reachable": data.get("target_reachable"),
        "tied_block": data.get("tied_block"),
        "not_offered": [p.get("code") for p in data.get("not_offered") or []],
        "picks": [sorted([p["code"], p["kind"], p["group_id"]] for p in s["picks"])
                  for s in data.get("schedules") or []],
        "scores": [s["score"] for s in data.get("schedules") or []],
        "viability": data.get("viability"),
        "error": None if res.status_code == 200 else res.get_data(as_text=True)[:500],
    }
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


# ==========================================================================
# 3. מקור אמת — המנייה המלאה של בדיקת הדיוק, בזרימה
# ==========================================================================
class RefTimeout(Exception):
    pass


def reference(catalog_dir, cases_path, idx, variant, solve_path, out_path):
    api, page, app, client = _setup(catalog_dir)
    import test_solver_exactness as ex  # noqa: PLC0415

    sch = api.scheduler_mod
    Selection = api.models.Selection
    case = json.loads(Path(cases_path).read_text(encoding="utf-8"))["cases"][int(idx)]
    got = json.loads(Path(solve_path).read_text(encoding="utf-8"))
    body = body_for(page, case, variant)
    top_n = int(body.get("top_n", 5))
    with app.app_context():
        built, _p, _m = api._build_courses(case["codes"], semester=case["term"],  # noqa: SLF001
                                           year=case["year_he"], program=case["program"],
                                           intake=case["intake"])
    prefs = ex._prefs_like_the_api(body, built)  # noqa: SLF001
    out = {"compared": False, "mismatches": []}

    if got.get("tied_block"):
        try:
            sch._validate_tied(built)  # noqa: SLF001
            out["mismatches"].append("API reported a tied block; reference validates fine")
        except sch.TiedCoursesError:
            pass
        out.update(compared=True, ref_time_s=0.0, ref_leaves=0, note="tied block")
        Path(out_path).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return

    ref_prefs = replace(prefs, preferred_lecturers=sch.rankings_by_kind(built, prefs.preferred_lecturers))
    slots = sch._build_slots(built, ref_prefs)  # noqa: SLF001
    kind_of = sch._kind_index(built)  # noqa: SLF001
    deadline = time.monotonic() + REF_COMPUTE_S
    state = {"leaves": 0, "min_days": None, "seq": 0, "nodes": 0}
    alive = set()
    # ‏(מפתח מיון, מספר סידורי, מערכת), ממוין — שקול למיון יציב של כל העלים
    # ולקיחת top_n הראשונים, כמו ``_reference``.
    top = []
    chosen = []
    t0 = time.perf_counter()

    def leaf():
        sel = Selection(list(chosen))
        state["leaves"] += 1
        d = len(sel.days_used())
        if state["min_days"] is None or d < state["min_days"]:
            state["min_days"] = d
        for g in sel.groups:
            alive.add((g.course_code, g.kind, g.group_id))
        sc = sch.score(sel, ref_prefs)
        item = (sch._sort_key(sc), state["seq"], sc)  # noqa: SLF001
        state["seq"] += 1
        if len(top) < top_n or item[:2] < top[-1][:2]:
            bisect.insort(top, item, key=lambda t: t[:2])
            del top[top_n:]

    def bt(depth):
        state["nodes"] += 1
        if not state["nodes"] % 2000 and time.monotonic() > deadline:
            raise RefTimeout
        if depth == len(slots):
            leaf()
            return
        for cand in slots[depth].candidates:
            if any(not sch._pair_ok(a, cand, kind_of, ref_prefs) for a in chosen):  # noqa: SLF001
                continue
            chosen.append(cand)
            bt(depth + 1)
            chosen.pop()

    sys.setrecursionlimit(10000)
    try:
        bt(0)
    except RefTimeout:
        out.update(ref_timeout=True, ref_time_s=round(time.perf_counter() - t0, 2),
                   ref_leaves_so_far=state["leaves"])
        Path(out_path).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return
    out["ref_time_s"] = round(time.perf_counter() - t0, 2)
    out["ref_leaves"] = state["leaves"]
    out["ref_nodes"] = state["nodes"]
    mm = out["mismatches"]
    leaves_n = state["leaves"]
    expected = [t[2] for t in top] if leaves_n else []

    want_picks = [ex._picks(s.selection) for s in expected]  # noqa: SLF001
    got_picks = [[tuple(p) for p in s] for s in got["picks"]]
    if got_picks != want_picks:
        first = next((i for i, (a, b) in enumerate(zip(got_picks, want_picks)) if a != b),
                     min(len(got_picks), len(want_picks)))
        mm.append(f"schedules differ (API {len(got_picks)}, ref {len(want_picks)}; first diff at #{first + 1})")
    want_scores = [round(float(s.score), 4) for s in expected]
    if got["scores"] != want_scores:
        mm.append(f"scores differ: API {got['scores']} ref {want_scores}")
    if got["min_days"] != state["min_days"]:
        mm.append(f"min_days API {got['min_days']} ref {state['min_days']}")
    want_reach = state["min_days"] is not None and state["min_days"] <= body["target_days"]
    if got["target_reachable"] != want_reach:
        mm.append(f"target_reachable API {got['target_reachable']} ref {want_reach}")
    cap = api.FEASIBLE_COUNT_CAP
    if leaves_n <= cap:
        if got["feasible_count"] != leaves_n or got["feasible_count_capped"]:
            mm.append(f"feasible_count API {got['feasible_count']}/{got['feasible_count_capped']} ref {leaves_n}")
    elif got["feasible_count"] != cap or got["feasible_count_capped"] is not True:
        mm.append(f"feasible_count API {got['feasible_count']}/{got['feasible_count_capped']} ref {leaves_n} (> cap)")
    if got["counts_truncated"]:
        mm.append("counts_truncated true")
    if got["viability_skipped"] or got["viability_truncated"]:
        mm.append(f"viability skipped={got['viability_skipped']} truncated={got['viability_truncated']}")
    else:
        expected_via = {}
        for course in built:
            for g in course.groups:
                key = (course.code, g.kind, g.group_id)
                entry = ({"ok": True} if key in alive
                         else {"ok": False, "reason": api._dead_end_reason(g, ref_prefs)})  # noqa: SLF001
                expected_via.setdefault(course.code, {}).setdefault(g.kind, {})[g.group_id] = entry
        if got["viability"] != expected_via:
            diffs = []
            for code, kinds in expected_via.items():
                for kind, groups in kinds.items():
                    for gid, entry in groups.items():
                        have = ((got["viability"] or {}).get(code) or {}).get(kind, {}).get(gid)
                        if have != entry:
                            diffs.append(f"{code}/{kind}/{gid}: API {have} ref {entry}")
            mm.append(f"viability differs on {len(diffs)} groups: {diffs[:5]}")
    out["compared"] = True
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


# ==========================================================================
# הדרייבר — תהליך אחד בכל פעם
# ==========================================================================
def _run_child(args, kill_s, log):
    import psutil  # noqa: PLC0415

    # מחכים למרווח זיכרון במקום להתחיל בתוך מצוקה.
    for _ in range(60):
        if psutil.virtual_memory().available > MIN_FREE_MB * 2**20:
            break
        time.sleep(2)
    t0 = time.perf_counter()
    proc = subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), *args],
                            stdout=log, stderr=log)
    ps = psutil.Process(proc.pid)
    peak = 0
    reason = None
    while proc.poll() is None:
        try:
            peak = max(peak, ps.memory_info().rss)
        except psutil.Error:
            pass
        if time.perf_counter() - t0 > kill_s:
            reason = f"killed after {kill_s:.0f} s"
        elif peak > RSS_KILL_MB * 2**20:
            reason = f"killed at {peak / 2**20:.0f} MB"
        if reason:
            proc.kill()
            proc.wait()
            break
        time.sleep(0.1)
    return {"rc": proc.returncode, "wall_s": round(time.perf_counter() - t0, 2),
            "peak_mb": round(peak / 2**20), "killed": reason}


def run(catalog_dir, outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    work = outdir / "work"
    work.mkdir(exist_ok=True)
    empty = outdir / "empty-store"
    empty.mkdir(exist_ok=True)
    os.environ[EMPTY_DB_ENV] = str(empty.resolve())
    cases_path = outdir / "cases.json"
    log = open(outdir / "workers.log", "a", encoding="utf-8")
    if not cases_path.exists():
        r = _run_child(["plan", catalog_dir, str(cases_path)], 900, log)
        if r["rc"] != 0:
            raise SystemExit(f"plan failed: {r}")
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    results_path = outdir / "results.jsonl"
    done = set()
    ref_a = {}
    if results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            done.add((rec["id"], rec["variant"]))
            if rec["variant"] == "a_default":
                ref_a[rec["id"]] = rec.get("ref") or {}
    run_ref = os.environ.get("SOLVER_SWEEP_NO_REF") != "1"
    with open(results_path, "a", encoding="utf-8") as res_f:
        for idx, case in enumerate(cases):
            for variant in VARIANTS:
                if (case["id"], variant) in done:
                    continue
                tag = f"{idx:03d}_{variant}"
                solve_out = work / f"{tag}.solve.json"
                ref_out = work / f"{tag}.ref.json"
                rec = {"id": case["id"], "variant": variant, "idx": idx,
                       "n_codes": len(case["codes"]), "n_groups": case.get("n_groups")}
                print(f"[{idx + 1}/{len(cases)}] {case['id']} {variant}", flush=True)
                r = _run_child(["solve", catalog_dir, str(cases_path), str(idx), variant,
                                str(solve_out)], SOLVE_KILL_S, log)
                rec["solve_proc"] = r
                if r["rc"] == 0 and solve_out.exists():
                    s = json.loads(solve_out.read_text(encoding="utf-8"))
                    rec.update({k: v for k, v in s.items() if k not in ("picks", "viability")})
                    a_timeout = ((ref_a.get(case["id"]) or {}).get("ref_timeout")
                                 and variant in ("c_ranked", "d_target3"))
                    if a_timeout:
                        rec["ref"] = {"compared": False, "mismatches": [],
                                      "skipped": "same leaf set as a_default, whose reference timed out"}
                    elif run_ref and s["status"] == 200:
                        r2 = _run_child(["ref", catalog_dir, str(cases_path), str(idx), variant,
                                         str(solve_out), str(ref_out)], REF_KILL_S, log)
                        rec["ref_proc"] = r2
                        if r2["rc"] == 0 and ref_out.exists():
                            rec["ref"] = json.loads(ref_out.read_text(encoding="utf-8"))
                if variant == "a_default":
                    ref_a[case["id"]] = rec.get("ref") or {}
                res_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                res_f.flush()


# ==========================================================================
# 4. הבדיקה החיה — ברצף, שנייה בין בקשה לבקשה
# ==========================================================================
def _live_call(method, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        LIVE_BASE + path, data=data, method=method,
        headers={"User-Agent": "SlotWise-verification/1 (owner, read-only, sequential)",
                 "Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, time.perf_counter() - t0, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, time.perf_counter() - t0, {"error": e.read()[:300].decode("utf-8", "replace")}
    except Exception as e:  # noqa: BLE001
        return None, time.perf_counter() - t0, {"error": repr(e)}


def live(cases_path, out_path, *flags):
    cases = json.loads(Path(cases_path).read_text(encoding="utf-8"))["cases"]
    # מסלול × סמסטר כפי שהדף שולח אותם: בלי התמחות ובלי מסלול התמחות.
    plain = [c for c in cases if not c["specialization"] and not c["route"]]
    print(f"{len(plain)} solves + 1 bootstrap")
    if "--dry" in flags:
        return
    with open(out_path, "w", encoding="utf-8") as out:
        st, t, boot = _live_call("GET", "/api/bootstrap")
        cat = (boot or {}).get("catalog") or {}
        out.write(json.dumps({"bootstrap": st, "time_s": round(t, 3), "catalog": cat,
                              "mode": boot.get("mode")}, ensure_ascii=False) + "\n")
        print("bootstrap", st, round(t, 2), cat.get("fetched_at"), boot.get("mode"))
        for c in plain:
            time.sleep(LIVE_GAP_S)
            body = {"codes": c["codes"], "semester": c["term"], "year": c["year_he"],
                    "program": c["program"], "intake": c["intake"], "target_days": 6,
                    "ranked": {}, "blocked": [], "forbid_friday": False, "top_n": 5,
                    "allow_soft_conflicts": True}
            if c["att_default"]:
                body["attendance"] = c["att_default"]
            st, t, d = _live_call("POST", "/api/solve", body)
            rec = {"id": c["id"], "status": st, "time_s": round(t, 3),
                   "timed_out": d.get("timed_out"), "n_schedules": len(d.get("schedules") or []),
                   "feasible_count": d.get("feasible_count"),
                   "feasible_count_capped": d.get("feasible_count_capped"),
                   "elapsed_ms": d.get("elapsed_ms"), "error": d.get("error")}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            print(rec["id"], st, rec["time_s"], rec["timed_out"], rec["n_schedules"], flush=True)


if __name__ == "__main__":
    mode, *rest = sys.argv[1:]
    {"run": run, "plan": plan, "solve": solve, "ref": reference, "live": live}[mode](*rest)
