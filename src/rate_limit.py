"""
src/rate_limit.py — a per-IP ceiling on the server time one client may use.

Not a security wall. Its job is narrower: stop one client — a bot, a script, a
stuck browser tab — from flooding ``/api/*`` and scaling Cloud Run up by
itself. Legitimate students must never hit it. DEPLOY.md, "Rate limiting", has
the derivation of the numbers; this docstring keeps the parts the code depends
on.

**The budget is CPU seconds, not requests.** A solve costs anything from 73 ms
to the 20 s ``SOLVE_DEADLINE_S``, and a client can pick the worst selection on
purpose, so a request count would be wrong by more than an order of magnitude.
Every request under ``/api/`` is charged its own ``time.process_time()`` delta
(at least ``MIN_CHARGE_S``). Under a sync gunicorn worker that delta is exactly
the request's CPU: the worker serves one request at a time, and CPU contention
on a busy instance does not inflate it the way wall time would.

**Token bucket, per IP, per worker.** Each IP has a bucket that refills at
``cpu_per_min`` CPU seconds per minute up to ``burst_cpu``. A request is
admitted while the bucket is above zero and charged after it finishes, so the
bucket can go negative; ``Retry-After`` is the time until it is back above the
minimum charge.

**Per worker** means exactly that. The buckets live in this process's memory.
``preload_app`` builds the limiter in the gunicorn master before the fork, so
every worker starts with its own empty copy, and nothing is shared between
workers or instances. One IP can therefore get ``cpu_per_min`` from *each*
worker its requests reach: with the defaults, 25% of every worker, which is
1 vCPU of a 2-vCPU instance with 4 workers. That stays below Cloud Run's CPU
scale-out target, so one IP alone cannot drive autoscaling — it can only use
instances that other traffic has already brought up. And ``Retry-After`` is
one worker's answer: the next request may land on a worker with a full bucket.

**IPv6 is keyed on the /64**, the block one subscriber gets. Keyed on the full
address, one host could rotate through 2^64 addresses.

**Exempt networks** (``SLOTWISE_RATE_LIMIT_EXEMPT_CIDRS``) are for the campus
Wi-Fi NAT: dozens of students behind one address are indistinguishable from
one heavy client, and no per-IP budget can admit the first without admitting
the second. The address checked is ``request.remote_addr`` after ``ProxyFix``,
i.e. the one the Google Frontend appended — not anything the client sent.

**Off until a time, not off.** ``SLOTWISE_RATE_LIMIT_OFF_UNTIL`` switches the
limiter off until an ISO-8601 UTC timestamp and it comes back by itself, so a
load test that forgets to unset it leaves nothing behind. There is no bypass
header.

State is short-lived, in memory, and holds no student data — an address, a
number and two timestamps per bucket. HOSTING_NOTES.md §4.1 records this as an
approved exception to "no server-side per-user state". It is kept on
``app.extensions``, not in a module-level global (§4.5).
"""

from __future__ import annotations

import ipaddress
import math
import os
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Mapping

#: Defaults. DEPLOY.md, "Rate limiting", derives them.
DEFAULT_CPU_PER_MIN = 15.0
DEFAULT_BURST_CPU = 60.0

#: The least a request is charged, in CPU seconds. Without it a flood of cheap
#: requests would cost almost nothing against the budget; with it the budget
#: still caps them (15 CPU-s per minute / 10 ms = 1,500 requests per minute,
#: per worker).
MIN_CHARGE_S = 0.010

#: Retry-After is clamped to this range, in seconds.
RETRY_AFTER_MIN_S = 1
RETRY_AFTER_MAX_S = 60

#: Buckets kept per worker before a sweep is forced. About 200 bytes each.
MAX_ENTRIES = 20_000
#: A sweep also runs every this many checks, to drop buckets that refilled.
SWEEP_EVERY = 1_000
#: At most one log line per throttled IP per this many seconds.
LOG_EVERY_S = 60.0

#: The key used when the request has no parseable address at all.
UNKNOWN_KEY = "-"

ENV_CPU_PER_MIN = "SLOTWISE_RATE_LIMIT_CPU_PER_MIN"
ENV_BURST_CPU = "SLOTWISE_RATE_LIMIT_BURST_CPU"
ENV_EXEMPT_CIDRS = "SLOTWISE_RATE_LIMIT_EXEMPT_CIDRS"
ENV_OFF_UNTIL = "SLOTWISE_RATE_LIMIT_OFF_UNTIL"

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


# ---------------------------------------------------------------------------
# Parsing. A malformed value raises at startup instead of falling back to a
# default: a limit that is silently not the one configured is worse than a
# revision that refuses to start (Cloud Run keeps the old one serving).
# ---------------------------------------------------------------------------
def parse_positive(name: str, raw: str | None, default: float) -> float:
    """A positive number of CPU seconds, or ``default`` when unset."""
    text = str(raw or "").strip()
    if not text:
        return float(default)
    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number of CPU seconds, got {text!r}") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive number of CPU seconds, got {text!r}")
    return value


def parse_cidrs(name: str, raw: str | None) -> tuple[Network, ...]:
    """Comma- or space-separated networks. A bare address is its own /32 or /128."""
    text = str(raw or "").replace(",", " ")
    nets = []
    for item in text.split():
        try:
            nets.append(ipaddress.ip_network(item, strict=False))
        except ValueError as exc:
            raise ValueError(f"{name}: {item!r} is not an address or CIDR") from exc
    return tuple(nets)


def parse_off_until(name: str, raw: str | None) -> datetime | None:
    """An ISO-8601 timestamp **with** a zone (``Z`` or ``+00:00``), or ``None``."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        # fromisoformat accepts a trailing "Z" from Python 3.11; the image is 3.12.
        when = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be an ISO-8601 UTC time such as 2026-11-01T03:00Z, got {text!r}"
        ) from exc
    if when.tzinfo is None:
        raise ValueError(
            f"{name} must say its zone (end it in Z for UTC), got {text!r}"
        )
    return when.astimezone(timezone.utc)


def settings_from_env(environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """The four ``SLOTWISE_RATE_LIMIT_*`` variables, parsed. Raises on bad values."""
    env = os.environ if environ is None else environ
    return {
        "rate_limit_cpu_per_min": parse_positive(
            ENV_CPU_PER_MIN, env.get(ENV_CPU_PER_MIN), DEFAULT_CPU_PER_MIN
        ),
        "rate_limit_burst_cpu": parse_positive(
            ENV_BURST_CPU, env.get(ENV_BURST_CPU), DEFAULT_BURST_CPU
        ),
        "rate_limit_exempt_cidrs": parse_cidrs(ENV_EXEMPT_CIDRS, env.get(ENV_EXEMPT_CIDRS)),
        "rate_limit_off_until": parse_off_until(ENV_OFF_UNTIL, env.get(ENV_OFF_UNTIL)),
    }


# ---------------------------------------------------------------------------
# The limiter
# ---------------------------------------------------------------------------
class RateLimiter:
    """Token buckets of CPU seconds, keyed by client address. One per process.

    ``clock`` (monotonic seconds), ``cpu_clock`` (this process's CPU seconds)
    and ``now`` (aware UTC datetime) are attributes so tests can replace them.
    """

    def __init__(
        self,
        *,
        cpu_per_min: float = DEFAULT_CPU_PER_MIN,
        burst_cpu: float = DEFAULT_BURST_CPU,
        exempt: tuple[Network, ...] = (),
        off_until: datetime | None = None,
        max_entries: int = MAX_ENTRIES,
    ) -> None:
        self.cpu_per_min = float(cpu_per_min)
        self.burst_cpu = float(burst_cpu)
        self.exempt = tuple(exempt)
        self.off_until = off_until
        self.max_entries = int(max_entries)
        self.clock: Callable[[], float] = time.monotonic
        self.cpu_clock: Callable[[], float] = time.process_time
        self.now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
        # key -> [tokens, last refill (clock), last log line (clock)]
        self._buckets: dict[str, list[float]] = {}
        self._checks = 0
        # Gunicorn's sync workers never run two requests at once, but
        # `python wsgi.py` (werkzeug, threaded) does.
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Mapping[str, object]) -> "RateLimiter":
        return cls(
            cpu_per_min=float(settings["rate_limit_cpu_per_min"]),  # type: ignore[arg-type]
            burst_cpu=float(settings["rate_limit_burst_cpu"]),  # type: ignore[arg-type]
            exempt=tuple(settings["rate_limit_exempt_cidrs"]),  # type: ignore[arg-type]
            off_until=settings["rate_limit_off_until"],  # type: ignore[arg-type]
        )

    # ---- what is limited -------------------------------------------------
    @property
    def refill_per_s(self) -> float:
        return self.cpu_per_min / 60.0

    def active(self) -> bool:
        """False while ``off_until`` is in the future."""
        return self.off_until is None or self.now() >= self.off_until

    def key_for(self, addr: str | None) -> str | None:
        """The bucket key for an address, or ``None`` when it is exempt."""
        try:
            ip = ipaddress.ip_address(str(addr or "").strip())
        except ValueError:
            return UNKNOWN_KEY
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if any(ip.version == net.version and ip in net for net in self.exempt):
            return None
        if isinstance(ip, ipaddress.IPv6Address):
            return str(ipaddress.IPv6Network((ip, 64), strict=False))
        return str(ip)

    # ---- the bucket ------------------------------------------------------
    def _refilled(self, entry: list[float], now: float) -> float:
        elapsed = max(0.0, now - entry[1])
        return min(self.burst_cpu, entry[0] + elapsed * self.refill_per_s)

    def check(self, key: str) -> int | None:
        """``None`` to admit the request, or the ``Retry-After`` seconds to reject it."""
        with self._lock:
            now = self.clock()
            self._checks += 1
            if self._checks % SWEEP_EVERY == 0 or len(self._buckets) > self.max_entries:
                self._sweep(now)
            entry = self._buckets.get(key)
            if entry is None:
                return None
            tokens = self._refilled(entry, now)
            entry[0], entry[1] = tokens, now
            if tokens > 0:
                return None
            deficit = MIN_CHARGE_S - tokens
            wait = math.ceil(deficit / self.refill_per_s)
            return max(RETRY_AFTER_MIN_S, min(RETRY_AFTER_MAX_S, wait))

    def charge(self, key: str, cpu_seconds: float) -> None:
        """Debit what a finished request cost, never less than ``MIN_CHARGE_S``."""
        cost = max(MIN_CHARGE_S, float(cpu_seconds))
        with self._lock:
            now = self.clock()
            entry = self._buckets.get(key)
            if entry is None:
                entry = self._buckets[key] = [self.burst_cpu, now, -math.inf]
            tokens = self._refilled(entry, now)
            entry[0], entry[1] = tokens - cost, now

    def should_log(self, key: str) -> bool:
        """True at most once per ``LOG_EVERY_S`` per key, so a flood is one line a minute."""
        with self._lock:
            entry = self._buckets.get(key)
            if entry is None:
                return False
            now = self.clock()
            if now - entry[2] < LOG_EVERY_S:
                return False
            entry[2] = now
            return True

    def _sweep(self, now: float) -> None:
        """Drop buckets that have refilled — a full bucket is the same as none.

        If that still leaves more than ``max_entries`` (a flood from many
        addresses), drop the least recently used until half the cap is left.
        """
        full = [k for k, e in self._buckets.items() if self._refilled(e, now) >= self.burst_cpu]
        for k in full:
            del self._buckets[k]
        if len(self._buckets) > self.max_entries:
            oldest = sorted(self._buckets, key=lambda k: self._buckets[k][1])
            for k in oldest[: len(self._buckets) - self.max_entries // 2]:
                del self._buckets[k]

    def __len__(self) -> int:
        return len(self._buckets)

    def describe(self) -> str:
        """One line for the startup log."""
        if self.off_until is not None and not self.active():
            stamp = self.off_until.strftime("%Y-%m-%dT%H:%MZ")
            return f"off until {stamp}"
        nets = ",".join(str(n) for n in self.exempt) or "none"
        return (
            f"on: {self.cpu_per_min:g} CPU-s/min per IP per worker, "
            f"burst {self.burst_cpu:g} CPU-s, exempt {nets}"
        )
