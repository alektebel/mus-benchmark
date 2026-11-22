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
import random
import re
import secrets
import threading
import time
from dataclasses import dataclass, field

import requests

import musbench.observe.trace_store as trace_store

# ---- tunables (env-overridable so Fly can change them without a redeploy) ----
DAILY_CALL_BUDGET = int(os.environ.get("MUS_DAILY_CALL_BUDGET", "4000"))
SESSION_CALL_CAP = int(os.environ.get("MUS_SESSION_CALL_CAP", "240"))
MAX_SESSIONS = int(os.environ.get("MUS_MAX_SESSIONS", "12"))
MAX_LLM_SESSIONS = int(os.environ.get("MUS_MAX_LLM_SESSIONS", "8"))
SESSION_IDLE_TTL = float(os.environ.get("MUS_SESSION_IDLE_TTL", "900"))
GAMES_PER_IP_HOUR = int(os.environ.get("MUS_GAMES_PER_IP_HOUR", "6"))
# Comma-separated IPs that skip the per-hour /api/new cap (owner / CI).
IP_ALLOWLIST = {
    ip.strip() for ip in os.environ.get("MUS_IP_ALLOWLIST", "").split(",")
    if ip.strip()
}
PUBLIC_HANDS = int(os.environ.get("MUS_PUBLIC_HANDS", "4"))
STATE_PATH = os.environ.get("MUS_BUDGET_STATE", "/tmp/mus-budget.json")
NAN_MODELS_TTL = float(os.environ.get("MUS_NAN_MODELS_TTL", "300"))
# Provider /v1/models also lists embeddings, ASR, TTS, image — keep chat seats.
_NON_CHAT = re.compile(
    r"(embedding|rerank|whisper|kokoro|tts|asr|flux|image|audio|speech|"
    r"vision|moderation|transcrib|nemotron-embed|retrieve|starcoder|"
    r"fuyu|sdxl|stable-diffusion|guard|embed|translate|riva|nvclip|"
    r"neva|vila|deplot|diffusion|reward|safety|parse|detect|calibrat|"
    r"video|kosmos|clip|omni|content-safety|synthetic|ising-calibrat|"
    r"muse-glimmer|codegemma|codellama|codestral|/code-|code-instruct|coder|"
    r"-vl-|/vl-|gemma-2b$)",
    re.I,
)
# Live NVIDIA pool (only used if MUS_ALLOW_NVIDIA=1): Kimi / Mistral / Nemotron.
_NVIDIA_OK = re.compile(r"(kimi|mistral|mixtral|nemotron)", re.I)
_OFFLINE_SEAT = re.compile(r"^(human|heuristic|random|eps:.+)$", re.I)
_FALLBACK_CHAT = [
    "nan:glm5.3-flash", "nan:deepseek-v4-flash", "nan:qwen3.6",
    "nan:qwen3.8-flash", "nan:gemma4", "nan:mimo-v2.6-flash",
]
# NVIDIA seats are too slow for the live table; opt back in with MUS_ALLOW_NVIDIA=1.
ALLOW_NVIDIA_LIVE = os.environ.get("MUS_ALLOW_NVIDIA", "0").strip().lower() \
    in ("1", "true", "yes")
# Probed live (2026-11-07): specs that answer with the keys we have.
# Catalog listings ≠ account entitlement.
_VERIFIED_LIVE = [
    "nan:glm5.3-flash", "nan:deepseek-v4-flash", "nan:gemma4",
    "nan:qwen3.6", "nan:qwen3.8-flash", "nan:mimo-v2.6-flash",
    "typesafe:jev-latest", "typesafe:jev-preview",
    "anthropic:claude-haiku-5-5", "anthropic:claude-sonnet-5-5",
]
# OpenRouter: default to :free models so the live table stays cheap.
OPENROUTER_FREE_ONLY = os.environ.get("OPENROUTER_FREE_ONLY", "1").strip().lower() \
    in ("1", "true", "yes")
# When unset, seat only the verified live set (not the raw provider catalogs).
USE_VERIFIED_LIVE_POOL = os.environ.get("MUS_USE_VERIFIED_POOL", "1").strip().lower() \
    in ("1", "true", "yes")
_models_cache: dict = {"at": 0.0, "ids": []}
_models_lock = threading.Lock()
# Specs that failed to construct or answer — never seat them again this process.
_bad_models: set[str] = set()
_bad_lock = threading.Lock()


def mark_bad_model(spec: str) -> None:
    s = str(spec).strip()
    if not s or _is_fixed_seat(s):
        return
    with _bad_lock:
        _bad_models.add(s)


def bad_models() -> set[str]:
    with _bad_lock:
        return set(_bad_models)


def clear_bad_models() -> None:
    with _bad_lock:
        _bad_models.clear()


def agent_spec(agent) -> str:
    """Canonical `provider:model` (or baseline tag) for a live seat."""
    if not getattr(agent, "is_llm", False):
        return str(getattr(agent, "model", "heuristic"))
    provider = getattr(agent, "provider", None) or "nan"
    model = getattr(agent, "model", "")
    return f"{provider}:{model}"


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

    def __init__(self, per_hour: int = GAMES_PER_IP_HOUR,
                 allowlist: set[str] | None = None):
        self.per_hour = per_hour
        self.allowlist = set(allowlist if allowlist is not None else IP_ALLOWLIST)
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def allow(self, ip: str) -> bool:
        if ip in self.allowlist:
            return True
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

    def create(self, sid: str, hands: int = PUBLIC_HANDS,
               vaca_limit: int = 0) -> tuple[Session | None, str]:
        """Make a table for sid. Returns (session, note) or (None, reason).

        Public tables always seat real LLMs. If the daily budget is gone or
        every LLM slot is taken, refuse — never deal disguised heuristics.
        """
        with self._lock:
            self._evict_locked()
            returning = sid in self._sessions
            if not returning and len(self._sessions) >= self.max_sessions:
                return None, "full"
            if self.budget.exhausted():
                return None, "budget"
            llm_used = sum(1 for other, s in self._sessions.items()
                           if s.llm and other != sid)
            if llm_used >= self.max_llm:
                return None, "busy"

            old = self._sessions.pop(sid, None)
            if old is not None:
                self._stop(old)

            try:
                table = self._factory(llm=True, hands=hands)
                table.start_new(vaca_limit=vaca_limit)
            except Exception:  # noqa: BLE001
                return None, "offline"
            game = table.current()
            game.sid = sid
            if getattr(table, "llm_active", True) is False:
                self._stop(Session(sid=sid, table=table, llm=False))
                return None, "offline"
            sess = Session(sid=sid, table=table, llm=True,
                           calls_at_start=sum(getattr(a, "calls", 0)
                                              for a in game.agents))
            self._sessions[sid] = sess
            return sess, ""

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
                # persist whatever happened before tearing the table down
                if not getattr(game, "sid", None):
                    game.sid = sess.sid
                trace_store.persist_game(game)
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


def _is_fixed_seat(spec: str) -> bool:
    return bool(_OFFLINE_SEAT.match(str(spec).strip()))


def _provider_base_and_key(provider: str) -> tuple[str, str]:
    from musbench.agents.core import PROVIDERS
    if provider not in PROVIDERS:
        return "", ""
    base, key_env = PROVIDERS[provider]
    if provider == "nan":
        base = os.environ.get("NAN_API_BASE", base)
    elif provider == "openrouter":
        base = os.environ.get("OPENROUTER_API_BASE", base)
    elif provider == "nvidia":
        base = os.environ.get("NVIDIA_API_BASE", base)
    return base.rstrip("/"), os.environ.get(key_env, "").strip()


def _fetch_provider_model_ids(provider: str) -> list[str]:
    """GET provider /v1/models as bare ids (no provider prefix)."""
    base, key = _provider_base_and_key(provider)
    if not base or not key:
        return []
    headers = {"Authorization": f"Bearer {key}"}
    if provider == "openrouter":
        headers["HTTP-Referer"] = os.environ.get(
            "OPENROUTER_HTTP_REFERER", "https://diegoatencia.dev/mus/")
        headers["X-Title"] = os.environ.get("OPENROUTER_APP_TITLE", "mus-benchmark")
    try:
        r = requests.get(f"{base}/models", headers=headers, timeout=12)
        r.raise_for_status()
        body = r.json()
        data = body.get("data") or body.get("models") or []
    except Exception:  # noqa: BLE001 — table must open even if catalog is down
        return []
    ids = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                mid = item.get("id") or item.get("name")
            else:
                mid = str(item)
            if mid:
                ids.append(str(mid).strip())
    return ids


def _keep_chat_id(provider: str, mid: str) -> bool:
    if not mid or _NON_CHAT.search(mid):
        return False
    if provider == "openrouter" and OPENROUTER_FREE_ONLY and not mid.endswith(":free"):
        return False
    if provider == "nvidia":
        if not ALLOW_NVIDIA_LIVE:
            return False
        if not _NVIDIA_OK.search(mid):
            return False
    return True


def list_chat_models(force: bool = False) -> list[str]:
    """Chat-capable `provider:model` specs across every configured provider.

    Order of preference:
      1. `MUS_MODEL_POOL` (comma-separated allow-list of specs or bare NAN ids)
      2. union of live `/v1/models` for nan + nvidia + openrouter (cached)
      3. baked-in NAN fallback list
    """
    pool_env = os.environ.get("MUS_MODEL_POOL", "").strip()
    if pool_env:
        out = []
        for s in pool_env.split(","):
            s = s.strip()
            if not s:
                continue
            known = ("nan", "nvidia", "openrouter", "typesafe", "anthropic")
            if ":" not in s or s.split(":", 1)[0] not in known:
                # bare id → default to nan for back-compat (except jev*)
                if s in ("jev", "jev-latest", "jev-preview") or s.startswith("jev"):
                    out.append(s if s.startswith("typesafe:") else f"typesafe:{s if s != 'jev' else 'jev-latest'}")
                elif s.startswith("claude"):
                    out.append(s if s.startswith("anthropic:") else f"anthropic:{s}")
                else:
                    out.append(s if s.startswith("nan:") else f"nan:{s}")
            else:
                out.append(s)
        if not ALLOW_NVIDIA_LIVE:
            out = [s for s in out if not s.startswith("nvidia:")]
        return out

    if USE_VERIFIED_LIVE_POOL:
        if ALLOW_NVIDIA_LIVE:
            return list(_VERIFIED_LIVE)
        return [s for s in _VERIFIED_LIVE if not s.startswith("nvidia:")]

    now = time.time()
    with _models_lock:
        if (not force and _models_cache["ids"]
                and now - _models_cache["at"] < NAN_MODELS_TTL):
            return list(_models_cache["ids"])

    from musbench.agents.core import PROVIDERS
    chat: list[str] = []
    # OpenAI-compatible: nan + curated nvidia (+ openrouter if keyed).
    for provider in PROVIDERS:
        if provider == "openrouter" and not os.environ.get("OPENROUTER_API_KEY", "").strip():
            continue
        for mid in _fetch_provider_model_ids(provider):
            if _keep_chat_id(provider, mid):
                chat.append(f"{provider}:{mid}")
    # TypeSafe Jev + Anthropic Claude sit outside the OpenAI-compatible map.
    try:
        from musbench.agents.jev_seat import list_jev_models
        chat.extend(list_jev_models())
    except Exception:  # noqa: BLE001
        pass
    try:
        from musbench.agents.anthropic_seat import list_anthropic_models
        chat.extend(list_anthropic_models())
    except Exception:  # noqa: BLE001
        pass
    if not chat:
        chat = list(_FALLBACK_CHAT)
    # de-dupe preserving order
    seen = set()
    uniq = []
    for s in chat:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    with _models_lock:
        _models_cache["at"] = time.time()
        _models_cache["ids"] = list(uniq)
    return list(uniq)


def list_nan_chat_models(force: bool = False) -> list[str]:
    """Back-compat alias: all chat specs (may include nvidia/openrouter)."""
    return list_chat_models(force=force)


def roll_lineup(template: list[str], rng: random.Random | None = None,
                exclude: set[str] | None = None) -> list[str]:
    """Keep human/offline seats from `template`; fill the rest from the pool.

    Prefers distinct models when the pool is large enough. `template` still
    decides *which* chairs are human (usually seat 0). Specs in `exclude` or
    the process-wide bad-model set are never seated.
    """
    rng = rng or random.SystemRandom()
    out = [str(s).strip() for s in template]
    slots = [i for i, s in enumerate(out) if not _is_fixed_seat(s)]
    if not slots:
        return out
    banned = bad_models() | set(exclude or ())
    pool = [m for m in list_chat_models() if m not in banned]
    if not pool:
        pool = [m for m in _FALLBACK_CHAT if m not in banned]
    if not pool:
        raise RuntimeError("no LLM models left to seat")
    if len(pool) >= len(slots):
        picks = rng.sample(pool, len(slots))
    else:
        picks = [rng.choice(pool) for _ in slots]
    for i, seat in enumerate(slots):
        out[seat] = picks[i]
    return out


def pick_replacement_spec(exclude: set[str] | None = None) -> str | None:
    """One fresh chat spec not in the bad/exclude sets, or None."""
    banned = bad_models() | set(exclude or ())
    pool = [m for m in list_chat_models() if m not in banned]
    if not pool:
        pool = [m for m in _FALLBACK_CHAT if m not in banned]
    if not pool:
        return None
    return random.SystemRandom().choice(pool)
