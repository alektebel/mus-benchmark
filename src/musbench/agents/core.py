"""Agent classes for the strict mus harness: LLM seats and offline baselines.

`SeatBase` holds the per-seat runtime counters shared by every seat. The two
subclasses differ only in how they produce an action: `StrictAgent` calls a
provider API; `BaselineSeat` plays a local policy against engine state.
"""
from __future__ import annotations

import json
import os
import time

import requests

from musbench.mus.engine import MusEngine, Phase, IllegalAction
from musbench.agents.groupchat import PerceptionBudget
from musbench.agents.baselines import (RandomPolicy, HeuristicPolicy,
                              parse_baseline)
import musbench.live.apifail as apifail
from musbench.live.apifail import (FatalAPIError, LLMCallFailure, RetryableAPIError,
                     MatchTimeout)

PROVIDERS = {
    "nan": ("https://api.nan.builders/v1", "NAN_API_KEY"),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
}
DEFAULT_PROVIDER = os.environ.get("DEFAULT_PROVIDER", "nan")
# Per-thought token ceiling. The model must reason briefly and emit only the
# action JSON, so a decision stays fast and reasoning never truncates it.
THINK_BUDGET = int(os.environ.get("THINK_BUDGET", "600"))
MAX_RESP = int(os.environ.get("MAX_RESP", str(THINK_BUDGET)))  # legacy alias
MAX_RESP_CAP = int(os.environ.get("MAX_RESP_CAP", str(THINK_BUDGET * 3)))
# Keep reasoning to a minimum: verbose chains-of-thought blow the budget and get
# truncated (finish=length), forcing slow escalation retries. "minimal" is the
# lowest accepted value that yields ~0 reasoning tokens on the nan models.
REASONING_MODE = os.environ.get("REASONING_MODE", "minimal")
TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.4"))
MAX_FALLBACK_RATE = float(os.environ.get("MAX_FALLBACK_RATE", "0.15"))
FALLBACK_MIN_TURNS = int(os.environ.get("FALLBACK_MIN_TURNS", "10"))
RESP_RETRIES = int(os.environ.get("RESP_RETRIES", "3"))  # JSON-level retries


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start:end + 1]
    return raw


class SeatBase:
    """Per-seat runtime state shared by LLM and baseline seats."""

    is_llm: bool

    def _init_state(self):
        self.budget = PerceptionBudget()
        self.listen = "both"
        self.tokens_in = self.tokens_out = self.reasoning = 0
        self.calls = self.fallbacks = self.api_errors = 0
        self.signals_read = 0        # how many señas this agent has read
        self.want_signals = False    # open the señas API next turn?
        self.invalid_signals = 0
        self.senas_log = []          # (turn, gesture, truthful) for review
        self.bluffs = 0              # false gestures sent when bluffing is allowed
        self.thoughts = []           # private one-paragraph reasoning, never broadcast
        self.rejections = 0          # illegal actions / false declarations
        self.redactions = 0          # chat messages that leaked card info
        self.verbose = False
        # Live-table preplan: strategy drafted while waiting for other seats.
        self.preplan: str | None = None
        self.preplan_key = None
        self.fast_turn = False       # smaller token budget when a plan is ready
        self.snap_turn = False       # mus/no: tiny prompt + tiny budget


class StrictAgent(SeatBase):
    """A seat backed by an OpenAI-compatible API (nan / nvidia / openrouter)."""

    is_llm = True

    def __init__(self, name: str, model: str, seat: int, team: int,
                 provider: str = "nan"):
        if provider not in PROVIDERS:
            raise FatalAPIError(f"unknown provider {provider!r} "
                                f"(supported: {list(PROVIDERS)})")
        self.name, self.model, self.seat, self.team = name, model, seat, team
        self.provider = provider
        base, key_env = PROVIDERS[provider]
        if provider == "nan":
            self.base = os.environ.get("NAN_API_BASE", base)
        elif provider == "openrouter":
            self.base = os.environ.get("OPENROUTER_API_BASE", base)
        else:
            self.base = os.environ.get("NVIDIA_API_BASE", base)
        self.deadline = None
        self.api_key = os.environ.get(key_env, "")
        if not self.api_key:
            raise FatalAPIError(f"env var {key_env} not set for provider {provider}")
        self._init_state()

    # ---------------- payload ----------------
    def _payload(self, prompt: str, max_tokens: int) -> dict:
        p = {
            "model": self.model,
            "messages": [
                {"role": "system", "content":
                    "You are a mus (Spanish card game) player. "
                    "Play honestly and tactically."},
                {"role": "user", "content": prompt},
            ],
            "temperature": TEMPERATURE,
            "max_tokens": max_tokens,
        }
        # OpenRouter / some NVIDIA routes reject unknown reasoning_effort.
        if REASONING_MODE != "omit" and self.provider == "nan":
            p["reasoning_effort"] = REASONING_MODE
        return p

    def _headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.api_key}",
             "Content-Type": "application/json"}
        if self.provider == "openrouter":
            # OpenRouter ranks apps that identify themselves; optional but polite.
            referer = os.environ.get("OPENROUTER_HTTP_REFERER",
                                     "https://diegoatencia.dev/mus/")
            title = os.environ.get("OPENROUTER_APP_TITLE", "mus-benchmark")
            if referer:
                h["HTTP-Referer"] = referer
            if title:
                h["X-Title"] = title
        return h

    # ---------------- one decision ----------------
    def _initial_max_tokens(self) -> int:
        """Floor for models that burn max_tokens on hidden reasoning.

        deepseek-v4-flash on NAN ignores a tight budget: with THINK_BUDGET=600
        and a mus-sized prompt it routinely returns finish=length, reasoning=600,
        content="" — then we retry for tens of seconds and look hung. Give it
        enough headroom on the first call so the JSON actually fits.

        When a live-table preplan is already in hand, prefer a smaller budget
        so the turn is an execution step, not a fresh strategy essay.
        """
        if self.snap_turn:
            floor = int(os.environ.get("MUS_SNAP_MAX_TOKENS", "320"))
        elif self.fast_turn:
            floor = int(os.environ.get("FAST_TURN_MAX_TOKENS", "500"))
        else:
            floor = THINK_BUDGET
        model = (self.model or "").lower()
        if "deepseek" in model and self.snap_turn:
            # Short mus prompt + modest headroom; avoid 1800-token essays.
            floor = max(floor, int(os.environ.get("DEEPSEEK_SNAP_MAX_TOKENS", "480")))
        elif "deepseek" in model and not self.fast_turn:
            floor = max(floor, int(os.environ.get("DEEPSEEK_MAX_TOKENS", "1800")))
        elif "deepseek" in model and self.fast_turn:
            # Still leave room for hidden reasoning, but not a full rethink.
            floor = max(floor, int(os.environ.get("DEEPSEEK_FAST_MAX_TOKENS", "900")))
        return min(floor, MAX_RESP_CAP)

    def decide(self, prompt: str) -> dict:
        max_tokens = self._initial_max_tokens()
        last_err: Exception | None = None
        for resp_attempt in range(RESP_RETRIES):
            def _call():
                timeout = float(os.environ.get("NAN_TIMEOUT", "180"))
                if self.deadline is not None:
                    remaining = self.deadline - time.monotonic()
                    if remaining <= 0:
                        raise MatchTimeout("match deadline reached before API request")
                    timeout = min(timeout, remaining)
                return requests.post(
                    f"{self.base}/chat/completions",
                    headers=self._headers(),
                    json=self._payload(prompt, max_tokens),
                    timeout=timeout)
            try:
                # break per MODEL, not per provider: one model's rate limit
                # used to open the circuit for every seat at the table
                d = apifail.call_with_retries(_call,
                                              f"{self.provider}:{self.model}",
                                              what=f"{self.name}/{self.model}",
                                              deadline=self.deadline)
            except FatalAPIError:
                self.api_errors += 1
                raise
            except (LLMCallFailure, RetryableAPIError) as e:
                self.api_errors += 1
                last_err = e
                break  # provider-level exhaustion; do not burn JSON retries
            self.calls += 1
            choices = d.get("choices")
            if (not isinstance(choices, list) or not choices
                    or not isinstance(choices[0], dict)):
                last_err = ValueError("API response has no valid choices")
                continue
            choice = choices[0]
            msg = choice.get("message") or {}
            if not isinstance(msg, dict) or not isinstance(msg.get("content", ""), (str, type(None))):
                last_err = ValueError("API response message content must be text")
                continue
            u = d.get("usage") or {}
            self.tokens_in += u.get("prompt_tokens") or 0
            self.tokens_out += u.get("completion_tokens") or 0
            reason_tok = (u.get("completion_tokens_details") or {}).get(
                "reasoning_tokens") or 0
            self.reasoning += reason_tok
            content = msg.get("content") or ""
            finish = choice.get("finish_reason")
            if self.verbose:
                print(f"    >>> {self.name} (seat {self.seat}, {self.model}) "
                      f"finish={finish} raw: {content[:400]!r}")
            if finish == "length" or (not content.strip()):
                # Reasoning ate the budget (common on deepseek): jump to the
                # cap instead of doubling slowly across several hung calls.
                if max_tokens < MAX_RESP_CAP:
                    max_tokens = MAX_RESP_CAP
                last_err = LLMCallFailure(
                    f"truncated (finish={finish}, reasoning={reason_tok})")
                continue   # fresh sample: reasoning length is stochastic
            try:
                data = json.loads(_extract_json(content))
                if isinstance(data, dict):
                    self.last_io = {"prompt": prompt, "raw": content}
                    return data
                last_err = ValueError(f"JSON is not an object: {type(data)}")
            except json.JSONDecodeError as e:
                last_err = e
                continue  # malformed JSON -> one more clean sample
        raise LLMCallFailure(f"{self.name}/{self.model}: no valid action JSON; "
                             f"last_err={last_err}")


class BaselineSeat(SeatBase):
    """Plays directly on engine state. No prompt, no API."""

    is_llm = False

    def __init__(self, name: str, kind: str, seat: int, team: int, seed: int = 0,
                 policy=None):
        self.name, self.seat, self.team = name, seat, team
        self.model = kind
        if policy is None:
            policy = (RandomPolicy(seed + seat) if kind == "random"
                      else HeuristicPolicy())
        self.policy = policy
        self._init_state()

    def decide(self, prompt: str) -> dict:  # never called; interface parity
        raise NotImplementedError


_BASELINE_TAG = {"heuristic": "HA", "random": "RA"}


def _make_agent(spec, seat: int, team: int, seed: int = 0):
    # baselines are resolved FIRST: "eps:0.05" is a baseline spec, not a
    # provider:model pair, and the provider split would eat the parameter
    baseline = parse_baseline(spec, seed + seat) if isinstance(spec, str) else None
    if baseline is not None:
        label, policy = baseline
        tag = _BASELINE_TAG.get(label, "EA")
        return BaselineSeat(f"{tag}{seat}", label, seat, team, seed,
                            policy=policy)
    # TypeSafe Jev / Anthropic Claude are not OpenAI chat/completions.
    if isinstance(spec, str):
        s = spec.strip()
        backend = s.split(":", 1)[0]
        if backend in ("claude-cli", "codex-cli", "cursor-cli") and ":" in s:
            from musbench.agents.cli_seat import CliAgent
            return CliAgent(f"{'A' if team == 0 else 'B'}{seat}", backend,
                            s.split(":", 1)[1], seat, team)
        if s in ("jev", "jev-latest", "jev-preview") or s.startswith("typesafe:"):
            from musbench.agents.jev_seat import JevAgent, DEFAULT_MODEL
            model = s.split(":", 1)[-1] if ":" in s else s
            if model == "jev":
                model = DEFAULT_MODEL
            return JevAgent(f"{'A' if team == 0 else 'B'}{seat}", model, seat, team)
        if s.startswith("anthropic:") or s.startswith("claude"):
            from musbench.agents.anthropic_seat import AnthropicAgent
            model = s.split(":", 1)[-1] if ":" in s else s
            return AnthropicAgent(f"{'A' if team == 0 else 'B'}{seat}", model,
                                  seat, team)
    if isinstance(spec, (tuple, list)) and len(spec) == 2:
        provider, model = str(spec[0]), str(spec[1])
        if provider == "typesafe":
            from musbench.agents.jev_seat import JevAgent
            return JevAgent(f"{'A' if team == 0 else 'B'}{seat}", model, seat, team)
        if provider == "anthropic":
            from musbench.agents.anthropic_seat import AnthropicAgent
            return AnthropicAgent(f"{'A' if team == 0 else 'B'}{seat}", model,
                                  seat, team)
    elif isinstance(spec, str) and ":" in spec:
        provider, model = spec.split(":", 1)
    else:
        provider, model = DEFAULT_PROVIDER, str(spec)
    return StrictAgent(f"{'A' if team == 0 else 'B'}{seat}", model, seat, team,
                       provider)


def _default_legal(engine: MusEngine, seat: int) -> dict:
    legal = engine.legal_actions(seat)
    if not legal:
        raise IllegalAction(f"no legal actions for seat {seat} "
                            f"in phase {engine.phase.name}")
    if engine.phase == Phase.DECLARE:
        return HeuristicPolicy().act(engine, seat, legal)
    if "perete" in legal:
        return {"action": "perete"}
    action = {"action": legal[0]}
    if engine.phase == Phase.MUS_DRAW:
        action["cards"] = [str(engine.hands[seat][0])]
    return action
