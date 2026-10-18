"""
check_thresholds.py — pass or fail a load-test run from Locust's CSV stats.

    python scripts/loadtest/check_thresholds.py loadtest-results/stats_stats.csv

Exit 0 when the run is inside the limits below, 1 when it is not (or when the
run never reached /api/solve at all, which would make a pass meaningless).
Used by .github/workflows/loadtest.yml; runnable by hand on a downloaded CSV.
"""

from __future__ import annotations

import csv
import sys

# The pass/fail line for a run. These are the maintainer's decision
# (2026-10-18), not derived from anything: change them deliberately, and say
# why in the commit.
#: 95th-percentile response time of POST /api/solve, in milliseconds.
SOLVE_P95_MAX_MS = 3000
#: Failed requests / all requests, over every endpoint together.
ERROR_RATE_MAX = 0.01

SOLVE_NAME = "/api/solve"


def main(path: str) -> int:
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    solve = next((r for r in rows if r["Name"] == SOLVE_NAME and r["Type"] == "POST"), None)
    total = next((r for r in rows if r["Name"] == "Aggregated"), None)
    if solve is None or total is None or int(solve["Request Count"]) == 0:
        print(f"::error::no {SOLVE_NAME} requests in {path}; the run did not exercise the solver.")
        return 1

    p95 = float(solve["95%"])
    requests = int(total["Request Count"])
    failures = int(total["Failure Count"])
    rate = failures / requests if requests else 1.0

    ok = True
    print(f"{SOLVE_NAME}: {solve['Request Count']} requests, p95 {p95:.0f} ms "
          f"(limit {SOLVE_P95_MAX_MS} ms)")
    if p95 > SOLVE_P95_MAX_MS:
        print(f"::error::{SOLVE_NAME} p95 {p95:.0f} ms > {SOLVE_P95_MAX_MS} ms")
        ok = False
    print(f"all endpoints: {failures}/{requests} failed = {rate:.2%} "
          f"(limit {ERROR_RATE_MAX:.0%})")
    if rate > ERROR_RATE_MAX:
        print(f"::error::error rate {rate:.2%} > {ERROR_RATE_MAX:.0%}")
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
