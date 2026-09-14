"""Public-hosting layer for the live mus table.

`live_server.py` was written for one person on one laptop: a single global
`LiveTable`, one game, no spend ceiling. Putting that on the open internet
breaks in three ways, and this module fixes exactly those three:

  1. One shared game -- any visitor pressing "Nueva partida" would stop
     everyone else's match. `SessionRegistry` gives each browser its own table.
  2. Unbounded spend -- every visitor turn costs real API credits. `Budget`
     caps calls per day, per session and per IP, and survives restarts.
  3. Unbounded memory -- abandoned games keep engine threads alive forever.
     The registry reaps idle sessions.

When the budget runs dry the table does not break: new games are dealt with
offline heuristic seats instead of models, and the UI says so. Nothing here
is imported by the local single-player path, so `play.sh` is unaffected.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field

# ---- tunables (env-overridable so Fly can change them without a redeploy) ----
DAILY_CALL_BUDGET = int(os.environ.get("MUS_DAILY_CALL_BUDGET", "4000"))
SESSION_CALL_CAP = int(os.environ.get("MUS_SESSION_CALL_CAP", "240"))
MAX_SESSIONS = int(os.environ.get("MUS_MAX_SESSIONS", "12"))
MAX_LLM_SESSIONS = int(os.environ.get("MUS_MAX_LLM_SESSIONS", "4"))
SESSION_IDLE_TTL = float(os.environ.get("MUS_SESSION_IDLE_TTL", "900"))
GAMES_PER_IP_HOUR = int(os.environ.get("MUS_GAMES_PER_IP_HOUR", "6"))
PUBLIC_HANDS = int(os.environ.get("MUS_PUBLIC_HANDS", "4"))
STATE_PATH = os.environ.get("MUS_BUDGET_STATE", "/tmp/mus-budget.json")


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


class Budget:
    """Thread-safe daily spend ceiling, persisted so a restart cannot reset it.

    Fly restarts containers freely; an in-memory counter would hand out a fresh
    day's budget on every crash loop, which is precisely when you least want it.
    """

    def __init__(self, daily: int = DAILY_CALL_BUDGET, path: str = STATE_PATH):
        self.daily = daily
        self.path = path
        self._lock = threading.Lock()
        self._day = _today()
        self._calls = 0
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path) as fh:
                data = json.load(fh)
            if data.get("day") == self._day:
                self._calls = int(data.get("calls", 0))
        except (OSError, ValueError, TypeError):
            pass

    def _save_locked(self) -> None:
        try:
            tmp = f"{self.path}.tmp"
            with open(tmp, "w") as fh:
                json.dump({"day": self._day, "calls": self._calls}, fh)
            os.replace(tmp, self.path)
        except OSError:
            pass  # a read-only fs must not take the table down

    def _rollover_locked(self) -> None:
        today = _today()
        if today != self._day:
            self._day, self._calls = today, 0

    def spend(self, n: int = 1) -> bool:
        """Record n calls. False once the ceiling is crossed."""
        with self._lock:
            self._rollover_locked()
            self._calls += n
            self._save_locked()
            return self._calls <= self.daily

    def exhausted(self) -> bool:
        with self._lock:
            self._rollover_locked()
            return self._calls >= self.daily

    def remaining(self) -> int:
        with self._lock:
            self._rollover_locked()
            return max(0, self.daily - self._calls)

    def status(self) -> dict:
        with self._lock:
            self._rollover_locked()
            return {"day": self._day, "calls": self._calls,
                    "daily": self.daily,
                    "remaining": max(0, self.daily - self._calls),
                    "exhausted": self._calls >= self.daily}


class IPLimiter:
    """Sliding-hour cap on how many games one address may start."""

    def __init__(self, per_hour: int = GAMES_PER_IP_HOUR):
        self.per_hour = per_hour
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def allow(self, ip: str) -> bool:
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits.get(ip, []) if now - t < 3600]
            if len(hits) >= self.per_hour:
                self._hits[ip] = hits
                return False
            hits.append(now)
            self._hits[ip] = hits
            if len(self._hits) > 4096:          # crude bound on the map itself
                for k in [k for k, v in self._hits.items()
                          if not any(now - t < 3600 for t in v)]:
                    self._hits.pop(k, None)
            return True


@dataclass
class Session:
    sid: str
    table: object                    # LiveTable, injected to avoid a cycle
    created: float = field(default_factory=time.time)
    touched: float = field(default_factory=time.time)
    llm: bool = True
    calls_at_start: int = 0

    def calls_used(self) -> int:
        game = self.table.current()
        if game is None:
            return 0
        used = sum(getattr(a, "calls", 0) for a in game.agents)
        return max(0, used - self.calls_at_start)


class SessionRegistry:
    """One `LiveTable` per browser, with eviction and concurrency ceilings."""

    def __init__(self, table_factory, budget: Budget,
                 max_sessions: int = MAX_SESSIONS,
                 max_llm: int = MAX_LLM_SESSIONS,
                 idle_ttl: float = SESSION_IDLE_TTL):
        self._factory = table_factory
        self.budget = budget
        self.max_sessions = max_sessions
        self.max_llm = max_llm
        self.idle_ttl = idle_ttl
        self._lock = threading.RLock()
        self._sessions: dict[str, Session] = {}
        self._reaper = threading.Thread(target=self._reap_loop, daemon=True)
        self._reaper.start()

    # ---------------- lifecycle ----------------
    def new_sid(self) -> str:
        return secrets.token_urlsafe(18)

    def get(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        with self._lock:
            s = self._sessions.get(sid)
            if s is not None:
                s.touched = time.time()
            return s

    def llm_sessions(self) -> int:
        with self._lock:
            return sum(1 for s in self._sessions.values() if s.llm)

    def create(self, sid: str, hands: int = PUBLIC_HANDS) -> tuple[Session | None, str]:
        """Make a table for sid. Returns (session, reason-if-degraded-or-refused)."""
        with self._lock:
            self._evict_locked()
            returning = sid in self._sessions
            if not returning and len(self._sessions) >= self.max_sessions:
                return None, "full"
            # Models only when there is budget AND a free LLM slot; otherwise
            # deal the hand with offline policies rather than refusing to play.
            llm = True
            note = ""
            if self.budget.exhausted():
                llm, note = False, "budget"
            elif sum(1 for s in self._sessions.values() if s.llm) >= self.max_llm:
                llm, note = False, "busy"

            old = self._sessions.pop(sid, None)
            if old is not None:
                self._stop(old)

            table = self._factory(llm=llm, hands=hands)
            table.start_new()
            game = table.current()
            # the factory downgrades to offline seats if the models cannot be
            # built at all (no API key); trust what it actually dealt
            if getattr(table, "llm_active", llm) is False and llm:
                llm, note = False, note or "offline"
            sess = Session(sid=sid, table=table, llm=llm,
                           calls_at_start=sum(getattr(a, "calls", 0)
                                              for a in game.agents))
            self._sessions[sid] = sess
            return sess, note

    def drop(self, sid: str) -> None:
        with self._lock:
            s = self._sessions.pop(sid, None)
        if s is not None:
            self._stop(s)

    # ---------------- internals ----------------
    @staticmethod
    def _stop(sess: Session) -> None:
        try:
            game = sess.table.current()
            if game is not None:
                game.stop()
        except Exception:  # noqa: BLE001 -- teardown must never raise
            pass

    def _evict_locked(self) -> None:
        """Reap only genuinely idle sessions.

        Deliberately never evicts an active player to make room for a new one:
        a newcomer is told the table is full instead. Killing someone's game
        mid-hand to seat a stranger is worse than making the stranger wait.
        """
        now = time.time()
        dead = [sid for sid, s in self._sessions.items()
                if now - s.touched > self.idle_ttl]
        for sid in dead:
            s = self._sessions.pop(sid, None)
            if s is not None:
                self._stop(s)

    def _reap_loop(self) -> None:
        while True:
            time.sleep(60)
            try:
                with self._lock:
                    self._evict_locked()
            except Exception:  # noqa: BLE001 -- the reaper must never die
                pass

    def status(self) -> dict:
        with self._lock:
            return {"sessions": len(self._sessions),
                    "llm_sessions": sum(1 for s in self._sessions.values() if s.llm),
                    "max_sessions": self.max_sessions,
                    "max_llm_sessions": self.max_llm}


# ---------------------------------------------------------------- metering --
def budgeted_agent(agent, budget: Budget):
    """Charge `budget` for every model call this seat makes.

    Wrapping the instance rather than subclassing keeps `agents._make_agent`
    as the single place that knows how to build a seat: whatever it returns
    (StrictAgent today) is metered without this module duplicating that logic.
    Offline seats have no `decide` worth charging and are returned untouched.
    """
    if not getattr(agent, "is_llm", False):
        return agent
    inner = agent.decide

    def decide(prompt: str):
        budget.spend(1)
        return inner(prompt)

    agent.decide = decide
    return agent


def public_specs(specs, llm: bool):
    """The seat line-up to deal with: real models, or offline stand-ins.

    Seat 0 stays human either way; only the three opponents change. This is
    what makes a budget-exhausted table still playable instead of a 503.
    """
    if llm:
        return list(specs)
    return [s if str(s).strip().lower() == "human" else "heuristic"
            for s in specs]
