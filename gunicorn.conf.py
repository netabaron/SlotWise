"""
gunicorn.conf.py — the hosted server's settings.

    gunicorn -c gunicorn.conf.py wsgi:app

Sized for what this app actually does. The two facts that matter:

* **POST /api/solve is CPU-bound and can take about a second.** Measured
  2026-09-15 against the real data/db: 4 courses 73 ms, 5 courses 580 ms,
  6 courses 735 ms, 8 courses 1.76 s; a worst-case 5-course pick with 60
  groups took 1.9 s. The solver is an exhaustive backtracking enumeration
  (src/scheduler.py) with no I/O at all, so it holds the GIL for its whole
  run. Sync workers, and enough of them — threads would not help.

* **The catalog is read-only and identical for every student.** Loading it
  once before the fork and sharing it copy-on-write is free; loading it per
  worker is not. Hence preload_app.
"""

from __future__ import annotations

import multiprocessing
import os

# ---------------------------------------------------------------------------
# Socket
# ---------------------------------------------------------------------------
#: Public bind. Safe here only because wsgi.py pins allow_network=False and the
#: scrape endpoints are gone — see HOSTING_NOTES.md §1.
bind = f"{os.environ.get('HOST', '0.0.0.0')}:{os.environ.get('PORT', '8000')}"  # noqa: S104

# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------
def _usable_cpus() -> int:
    """How many CPUs this process may actually use.

    `multiprocessing.cpu_count()` reports the **host's** cores, which is the
    wrong number inside a container: a 2-CPU container on a 64-core host would
    compute 129 workers and thrash. `os.sched_getaffinity` respects the
    affinity mask and is the closer answer where it exists (Linux).

    It still does not see a CFS quota (`--cpus=1.5`), so on a quota-limited
    host set WEB_CONCURRENCY explicitly — see DEPLOY.md.
    """
    getaffinity = getattr(os, "sched_getaffinity", None)
    if getaffinity is not None:
        try:
            return max(1, len(getaffinity(0)))
        except OSError:  # pragma: no cover - platform-dependent
            pass
    try:
        return max(1, multiprocessing.cpu_count())
    except NotImplementedError:  # pragma: no cover - cpu_count is reliable
        return 1


def _default_workers() -> int:
    """The usual 2*CPU+1."""
    return _usable_cpus() * 2 + 1


#: WEB_CONCURRENCY is the conventional name and what most hosts set for you.
#: Worth setting explicitly: each sync worker is a full process, and 2*CPU+1 on
#: a big host is a lot of them for an app whose hot path is one CPU-bound solve.
workers = int(os.environ.get("WEB_CONCURRENCY", "") or _default_workers())

#: Sync workers on purpose. /api/solve is pure CPU and never awaits anything,
#: so gevent/eventlet would buy nothing and would make one slow solve block
#: every other request sharing its worker.
worker_class = "sync"

# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------
#: 30 s. The measured tail for /api/solve is ~2 s, so this is roughly 15x
#: headroom — generous enough that a pathological course selection is not
#: killed mid-solve, tight enough that a wedged worker is recycled quickly.
timeout = 30

#: How long a worker gets to finish in-flight requests on reload/shutdown.
#: Comfortably above the ~2 s solve tail, so a deploy does not cut anyone off.
graceful_timeout = 10

#: Keep-alive for the proxy in front. 2 s is gunicorn's default and right for
#: a sync worker: a held-open connection is a worker that cannot serve.
keepalive = 2

# ---------------------------------------------------------------------------
# Preloading
# ---------------------------------------------------------------------------
#: Import the app once in the master, then fork. Two reasons:
#:   1. data/catalog/catalog.jsonl (572 courses, 583 KB) plus the sections DB are
#:      parsed once instead of `workers` times, and the pages are shared
#:      copy-on-write.
#:   2. A broken build fails at startup, in the master, with one clear
#:      traceback — instead of every worker crash-looping separately.
#: The usual caveat does not bite: preload is a problem for code that opens
#: sockets or file handles at import time and then forks them. This app opens
#: neither — wsgi.py pins allow_network=False, so there is no connection to
#: inherit, and the store reads files per request rather than holding handles.
preload_app = True

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")

#: Response time (%(L)s) is in the access line on purpose: /api/solve timing is
#: the number worth watching, and it is the first thing to look at if requests
#: start hitting the 30 s timeout.
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(L)ss "%(a)s"'
