"""Fallback/error suite for LLM API calls: no silent failures, no infinite loops.

Design goals:
  * Classify errors: RETRYABLE (429/5xx/timeout/conn) vs FATAL (400/401/403/404).
    Fatal errors raise immediately -- retrying a bad payload is pointless.
  * Exponential backoff with jitter, honoring Retry-After on 429.
  * Circuit breaker per provider: after N consecutive failures, cool down
    instead of hammering (hammering makes 429s worse).
  * Hard watchdogs: per-call timeout, per-turn retry cap, per-hand turn cap,
    per-match wall clock. Any breach raises -- the match STOPS with a status,
    it never degrades silently into default-action noise.
"""
from __future__ import annotations

import os
from email.utils import parsedate_to_datetime
import random
import tempfile
import threading
import time


# ---------------- exceptions ----------------
class RetryableAPIError(Exception):
    """Transient failure (429, 5xx, timeout, connection). Worth retrying."""


class FatalAPIError(Exception):
    """Permanent failure (bad payload, auth, unknown model). Do NOT retry."""


class LLMCallFailure(Exception):
    """All retry attempts exhausted for one decision call."""


class MatchTimeout(Exception):
    """Match exceeded its wall-clock budget."""


class DegradedMatch(Exception):
    """Too many fallback actions -- results would be noise, abort loudly."""


class TurnLimitExceeded(Exception):
    """A hand exceeded the max-turn watchdog (engine deadlock guard)."""


RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
FATAL_STATUS = {400, 401, 403, 404, 422}

# Tunables (env-overridable).
CALL_ATTEMPTS = int(os.environ.get("CALL_ATTEMPTS", "6"))
BACKOFF_BASE = float(os.environ.get("BACKOFF_BASE", "1.5"))
BACKOFF_MAX = float(os.environ.get("BACKOFF_MAX", "30.0"))
CB_THRESHOLD = int(os.environ.get("CB_THRESHOLD", "5"))        # consecutive fails
CB_COOLDOWN = float(os.environ.get("CB_COOLDOWN", "60.0"))     # seconds
MATCH_TIMEOUT = float(os.environ.get("MATCH_TIMEOUT", "3600"))  # 1h per match
MAX_TURNS_PER_HAND = int(os.environ.get("MAX_TURNS_PER_HAND", "200"))
# Global cap on requests in flight, enforced ACROSS PROCESSES: the tournament
# runs each match as its own subprocess, so an in-process semaphore cannot see
# the other matches. 0 disables. Set it below the provider's own parallel cap.
MAX_INFLIGHT = int(os.environ.get("MAX_INFLIGHT", "0"))
INFLIGHT_DIR = os.environ.get(
    "INFLIGHT_DIR", os.path.join(tempfile.gettempdir(), "mus_bench_inflight"))
INFLIGHT_WAIT = float(os.environ.get("INFLIGHT_WAIT", "0.25"))
# A 429 means "wait", not "the provider is broken". Counting it toward the
# breaker is what turned one model's rate limit into a table-wide outage:
# every seat saw `circuit open for nan` and played default actions instead.
CB_COUNT_RATE_LIMIT = os.environ.get("CB_COUNT_RATE_LIMIT", "0") == "1"


def classify_status(status: int, body: str = "") -> Exception:
    if status not in RETRYABLE_STATUS and not 500 <= status < 600:
        return FatalAPIError(f"HTTP {status}: {body[:200]}")
    return RetryableAPIError(f"HTTP {status}: {body[:200]}")


class CircuitBreaker:
    """Per-provider breaker: open after N consecutive failures."""

    def __init__(self):
        self._lock = threading.Lock()
        self._fails: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def check(self, provider: str) -> None:
        with self._lock:
            until = self._open_until.get(provider, 0.0)
            if until > time.monotonic():
                raise RetryableAPIError(
                    f"circuit open for {provider} for another "
                    f"{until - time.monotonic():.0f}s")

    def record_success(self, provider: str) -> None:
        with self._lock:
            self._fails[provider] = 0
            self._open_until.pop(provider, None)

    def record_failure(self, provider: str) -> None:
        with self._lock:
            n = self._fails.get(provider, 0) + 1
            self._fails[provider] = n
            if n >= CB_THRESHOLD:
                self._open_until[provider] = time.monotonic() + CB_COOLDOWN


BREAKER = CircuitBreaker()


def is_rate_limit(err: Exception) -> bool:
    return isinstance(err, RetryableAPIError) and "HTTP 429" in str(err)


class InflightLimiter:
    """Cross-process cap on concurrent requests, as lock files in a directory.

    A directory entry per in-flight call is crude but it is the one mechanism
    that works when the matches are separate subprocesses (`run_tournament`
    spawns them) and it degrades safely: if anything goes wrong we let the call
    through rather than stalling a 5-hour run. Stale slots from a killed
    process are reclaimed by age.
    """

    STALE_AFTER = 300.0

    def __init__(self, limit: int = 0, path: str | None = None):
        self.limit = limit
        self.path = path or INFLIGHT_DIR

    def _reap(self) -> int:
        now = time.time()
        live = 0
        try:
            for name in os.listdir(self.path):
                fp = os.path.join(self.path, name)
                try:
                    if now - os.path.getmtime(fp) > self.STALE_AFTER:
                        os.unlink(fp)
                    else:
                        live += 1
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            return 0
        return live

    def acquire(self, deadline: float | None = None) -> str | None:
        if self.limit <= 0:
            return None
        try:
            os.makedirs(self.path, exist_ok=True)
            token = f"{os.getpid()}-{threading.get_ident()}-{random.random():.9f}"
            fp = os.path.join(self.path, token)
            while True:
                if self._reap() < self.limit:
                    # O_EXCL so two processes cannot claim the same slot
                    fd = os.open(fp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.close(fd)
                    return fp
                if deadline is not None and time.monotonic() >= deadline:
                    raise MatchTimeout("waiting for a request slot")
                time.sleep(INFLIGHT_WAIT * (1.0 + random.random()))
        except MatchTimeout:
            raise
        except OSError:
            return None      # never let bookkeeping block the run

    def release(self, token: str | None) -> None:
        if not token:
            return
        try:
            os.unlink(token)
        except OSError:
            pass


LIMITER = InflightLimiter(MAX_INFLIGHT)


def backoff_delay(attempt: int, base: float = BACKOFF_BASE,
                  cap: float = BACKOFF_MAX) -> float:
    """Exponential backoff with EQUAL JITTER: half the delay is deterministic,
    half is random.

    The old form added only uniform(0, 0.5) to a fully deterministic delay, so
    several workers that hit a 429 in the same second retried in the same
    second, and kept doing so -- the thundering herd that makes a rate limit
    worse. Equal jitter keeps the exponential growth while decorrelating the
    retries, and never collapses to ~0 the way full jitter can.
    """
    ceiling = min(base * (2.0 ** max(0, attempt)), cap)
    return ceiling / 2.0 + random.uniform(0.0, ceiling / 2.0)


def _sleep_backoff(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        # honour the server's own number, jittered so callers do not resync
        return max(0.0, retry_after) + random.uniform(0, 1)
    return backoff_delay(attempt)


def call_with_retries(fn, provider: str = "nan", attempts: int = CALL_ATTEMPTS,
                      what: str = "call", deadline: float | None = None) -> dict:
    """fn() -> requests.Response. Returns parsed json dict on success.

    Raises FatalAPIError / LLMCallFailure -- never returns a silent sentinel.
    """
    if attempts < 1:
        raise ValueError("attempts must be positive")

    def check_deadline():
        if deadline is not None and time.monotonic() >= deadline:
            raise MatchTimeout(f"{what}: match deadline exceeded")

    check_deadline()
    BREAKER.check(provider)
    last: Exception | None = None
    retry_after: float | None = None
    for attempt in range(attempts):
        check_deadline()
        retry_after = None
        slot = None
        try:
            slot = LIMITER.acquire(deadline)
            r = fn()
            LIMITER.release(slot)
            slot = None
            check_deadline()
            if r.status_code == 200:
                data = r.json()
                if not isinstance(data, dict):
                    raise RetryableAPIError("API response must be a JSON object")
                BREAKER.record_success(provider)
                return data
            body = ""
            try:
                body = r.text
            except Exception:  # noqa: BLE001
                pass
            err = classify_status(r.status_code, body)
            if isinstance(err, FatalAPIError):
                raise err  # never retry a bad payload / auth error
            last = err
            ra = r.headers.get("Retry-After")
            try:
                retry_after = float(ra) if ra else None
            except (TypeError, ValueError):
                try:
                    retry_after = max(0.0, parsedate_to_datetime(ra).timestamp() - time.time())
                except (TypeError, ValueError, OverflowError):
                    retry_after = None
        except (FatalAPIError, MatchTimeout):
            LIMITER.release(slot)
            raise
        except RetryableAPIError as e:
            last = e
        except Exception as e:  # noqa: BLE001 -- timeouts, conn errors
            last = RetryableAPIError(f"{type(e).__name__}: {e}")
        finally:
            LIMITER.release(slot)
        # A rate limit is backpressure, not an outage: backing off is the right
        # response, opening the breaker is not.
        if CB_COUNT_RATE_LIMIT or not is_rate_limit(last):
            BREAKER.record_failure(provider)
        if attempt < attempts - 1:
            delay = _sleep_backoff(attempt, retry_after)
            if deadline is not None:
                delay = min(delay, max(0.0, deadline - time.monotonic()))
            time.sleep(delay)
            check_deadline()
    raise LLMCallFailure(f"{what}: {attempts} attempts exhausted; last={last}")
