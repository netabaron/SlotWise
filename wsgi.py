"""
wsgi.py — the hosted entry point. (WSGI entry point for gunicorn)

    gunicorn -c gunicorn.conf.py wsgi:app
    python wsgi.py                      # dev fallback, werkzeug, HOST/PORT

This is the counterpart to ``webapp.py``, not a replacement for it.
``webapp.py`` is the single-student local launcher: it binds ``127.0.0.1``,
picks a free port and opens a browser. This file is the opposite case — one
process serving many students, behind a real WSGI server — so the two differ
on exactly three points, and each one is deliberate:

1. **The network is off, explicitly.** ``create_app`` defaults
   ``allow_network=None``, which resolves to *"fetch from the yedion unless
   pytest is running"* by checking ``"pytest" in sys.modules``. That heuristic
   is right for a laptop and wrong for a server: it is an implicit default
   that silently flips to *on* in production, and an unauthenticated hosted
   process that fetches from Braude per request is the open relay
   ``HOSTING_NOTES.md`` §1 is about. Here it is pinned to ``False`` and cannot
   be turned on by configuration. A hosted instance serves the catalog it was
   built with; rebuilding it is the cron job's business (§2).

2. **Paths come from the environment.** The local app hardcodes
   ``PROJECT_ROOT / "data" / ...``; a container wants the database on a
   mounted volume.

3. **It binds ``0.0.0.0``.** ``webapp.py`` documents ``127.0.0.1`` as a hard
   rule, and for that file it still is. Binding publicly is only defensible
   here *because* of point 1 — no scrape endpoint, no network.

Environment variables — every one optional, each falling back to the same
path the local app uses. See DEPLOY.md for the full table.

    SLOTWISE_DB_ROOT                 data/db
    SLOTWISE_CURRICULUM_PATH         data/curriculum.json
    SLOTWISE_CURRICULA_DIR           data/curricula
    SLOTWISE_RAW_DIR                 data/raw
    SLOTWISE_MAX_AGE_HOURS           24.0
    SLOTWISE_DETAILS_MAX_AGE_HOURS   168.0
    SLOTWISE_CATALOG_DIR             data/catalog
    HOST                             0.0.0.0     (python wsgi.py only)
    PORT                             8000        (python wsgi.py only)

``SLOTWISE_CATALOG_DIR`` is the odd one out: it is read by
``src/shipped_catalog`` **at import time**, not passed through ``create_app``,
so it is not in ``build_settings()``. Setting it in the process environment
before startup is what works — which is what a container env var does anyway.
The directory holds ``catalog.jsonl`` and ``catalog.meta.json``, the two files
the nightly pipeline writes; see DEPLOY.md.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Hebrew on a Windows console. Guarded — pipes that cannot be reconfigured are
# fine, and under gunicorn these are already UTF-8.
# ---------------------------------------------------------------------------
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass

# ---------------------------------------------------------------------------
# Both ROOT and src/ go on sys.path: project modules import each other flat
# ("import models"), exactly as main.py and webapp.py arrange.
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
for _path in (SRC_DIR, ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

#: Defaults for `python wsgi.py`. Gunicorn takes its bind from gunicorn.conf.py.
DEFAULT_HOST = "0.0.0.0"  # noqa: S104 - hosted on purpose; see the module docstring
DEFAULT_PORT = 8000


def _env_path(name: str, default: Path) -> str:
    """A path from the environment, or the project-local default."""
    raw = str(os.environ.get(name, "") or "").strip()
    return str(Path(raw).expanduser()) if raw else str(default)


def _env_float(name: str, default: float) -> float:
    """A float from the environment.

    A malformed value raises instead of falling back. A freshness window is a
    correctness setting: ``SLOTWISE_MAX_AGE_HOURS=twentyfour`` silently
    becoming 24.0 is the kind of quiet default that makes a stale catalog look
    fresh, and this file exists to remove quiet defaults, not add one.
    """
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be a number of hours, got {raw!r}"
        ) from exc


def build_settings() -> dict[str, object]:
    """The config dict handed to ``create_app``. Pure — reads env, no I/O."""
    data = ROOT / "data"
    return {
        "db_root": _env_path("SLOTWISE_DB_ROOT", data / "db"),
        "curriculum_path": _env_path("SLOTWISE_CURRICULUM_PATH", data / "curriculum.json"),
        "curricula_dir": _env_path("SLOTWISE_CURRICULA_DIR", data / "curricula"),
        "raw_dir": _env_path("SLOTWISE_RAW_DIR", data / "raw"),
        "max_age_hours": _env_float("SLOTWISE_MAX_AGE_HOURS", 24.0),
        "details_max_age_hours": _env_float("SLOTWISE_DETAILS_MAX_AGE_HOURS", 24.0 * 7),
        # Not negotiable, and not configurable. See point 1 in the docstring.
        "allow_network": False,
    }


def build_app():
    """Builds the Flask app for hosting."""
    try:
        from src.web.api import create_app  # type: ignore[import-not-found]
    except ImportError:
        from web.api import create_app  # type: ignore[import-not-found]

    app = create_app(build_settings())

    # ---- one proxy hop, and exactly one -----------------------------------
    # Hosted, the chain is: client -> Cloudflare -> Railway's edge -> gunicorn.
    # Without this, request.remote_addr is Railway's internal proxy address on
    # every request and request.scheme is http even though the student is on
    # https — so access logs record one IP for everybody, and any rate limit
    # added later would throttle the proxy rather than an abuser.
    #
    # x_for=1 / x_proto=1, not more. Each unit of trust says "one hop I
    # control appends a value I can believe". Trusting two would let a client
    # forge the left-hand entry of X-Forwarded-For and appear as any address
    # it likes. Railway terminates and re-appends, so from gunicorn's seat
    # there is one trustworthy hop, whatever Cloudflare did upstream.
    #
    # Deliberately NOT applied in webapp.py: that binds 127.0.0.1 with no
    # proxy in front, so honouring these headers there would mean trusting
    # whatever a local process chose to send.
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0, x_prefix=0)

    # Say which catalog this process is serving, once, at startup. A wrong
    # SLOTWISE_CATALOG_DIR is otherwise completely silent: shipped_catalog
    # falls back to an empty catalog, the app starts happily, and every
    # course list is empty with no error anywhere. One line here turns that
    # into something you can see in `docker logs`.
    try:
        import shipped_catalog  # type: ignore

        stamp = shipped_catalog.built_at() or "(none)"
        count = len(shipped_catalog.courses())
        print(
            f"[slotwise] catalog: {shipped_catalog.CATALOG_PATH} "
            f"({count} courses, built {stamp})",
            flush=True,
        )
        if not count:
            print(
                "[slotwise] WARNING: the catalog is empty. Check "
                "SLOTWISE_CATALOG_DIR and that catalog.jsonl is mounted.",
                flush=True,
            )
    except Exception as exc:  # noqa: BLE001 - reporting must never break startup
        print(f"[slotwise] could not report the catalog: {exc}", flush=True)

    return app


#: What gunicorn imports: `gunicorn -c gunicorn.conf.py wsgi:app`.
#: Built at import time so preload_app=True loads the catalog once, before
#: the workers fork, and they share it copy-on-write.
app = build_app()


def main() -> int:
    """`python wsgi.py` — werkzeug on HOST:PORT. Convenience, not for prod."""
    host = str(os.environ.get("HOST", "") or "").strip() or DEFAULT_HOST
    try:
        port = int(str(os.environ.get("PORT", "") or "").strip() or DEFAULT_PORT)
    except ValueError:
        print(f"PORT must be a number — falling back to {DEFAULT_PORT}.")
        port = DEFAULT_PORT

    print(f"SlotWise (WSGI dev server) on http://{host}:{port}")
    print("Production: gunicorn -c gunicorn.conf.py wsgi:app")
    app.run(host=host, port=port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
