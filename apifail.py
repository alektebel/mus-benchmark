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


def _sleep_backoff(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return max(0.0, retry_after) + random.uniform(0, 1)
    return min(BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.5), BACKOFF_MAX)


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
        try:
            r = fn()
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
            raise
        except RetryableAPIError as e:
            last = e
        except Exception as e:  # noqa: BLE001 -- timeouts, conn errors
            last = RetryableAPIError(f"{type(e).__name__}: {e}")
        BREAKER.record_failure(provider)
        if attempt < attempts - 1:
            delay = _sleep_backoff(attempt, retry_after)
            if deadline is not None:
                delay = min(delay, max(0.0, deadline - time.monotonic()))
            time.sleep(delay)
            check_deadline()
    raise LLMCallFailure(f"{what}: {attempts} attempts exhausted; last={last}")
