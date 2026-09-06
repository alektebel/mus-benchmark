"""Strict multi-LLM mus harness on top of mus_engine.MusEngine.  v2

Changes vs v1 (the "silent fallback" version):
  * Providers: nan + nvidia ONLY (openrouter dropped per config decision).
  * max_tokens raised (1600 default) with auto-escalation when the model
    truncates (finish_reason == "length").
  * REASONING_MODE control: omit (default) | off | none | low | medium | high.
  * NO silent failures: API errors classify into retryable/fatal (apifail.py),
    fatal errors abort immediately, exhausted retries raise -- never a silent
    {} substituted by a default action.
  * Fallback budget: default legal moves are a last resort and are counted;
    if the fallback rate exceeds MAX_FALLBACK_RATE the match is aborted as
    DegradedMatch instead of writing garbage results.
  * Watchdogs: per-hand turn cap + per-match wall clock (no infinite loops).
  * Baseline seats: spec "heuristic"/"random" plays directly on engine state
    (no API) so the harness can be validated for free.

CLI:
  python run_match_strict.py --models "deepseek-v4-flash,heuristic,deepseek-v4-flash,heuristic" --hands 12
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from random import Random

import requests

from mus_engine import MusEngine, Phase, IllegalAction, TEAM_OF, LANCE_NAMES
from groupchat import Channels, PerceptionBudget, public_cost, signals_cost
import senas
from senas import SENAS, is_valid_sena, sena_truthful
from baselines_strict import RandomPolicy, HeuristicPolicy
import apifail
from apifail import (FatalAPIError, LLMCallFailure, MatchTimeout, DegradedMatch,
                     TurnLimitExceeded, MATCH_TIMEOUT, MAX_TURNS_PER_HAND)

PROVIDERS = {
    "nan": ("https://api.nan.builders/v1", "NAN_API_KEY"),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_KEY"),
}
DEFAULT_PROVIDER = os.environ.get("DEFAULT_PROVIDER", "nan")
MAX_RESP = int(os.environ.get("MAX_RESP", "1600"))
MAX_RESP_CAP = int(os.environ.get("MAX_RESP_CAP", "6144"))
REASONING_MODE = os.environ.get("REASONING_MODE", "off")  # off|omit|none|low|medium|high
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


class StrictAgent:
    """A seat backed by an OpenAI-compatible API (nan / nvidia)."""

    is_llm = True

    def __init__(self, name: str, model: str, seat: int, team: int,
                 provider: str = "nan"):
        if provider not in PROVIDERS:
            raise FatalAPIError(f"unknown provider {provider!r} "
                                f"(supported: {list(PROVIDERS)})")
        self.name, self.model, self.seat, self.team = name, model, seat, team
        self.provider = provider
        base, key_env = PROVIDERS[provider]
        self.base = os.environ.get("NAN_API_BASE", base) if provider == "nan" else base
        self.deadline = None
        self.api_key = os.environ.get(key_env, "")
        if not self.api_key:
            raise FatalAPIError(f"env var {key_env} not set for provider {provider}")
        self.budget = PerceptionBudget()
        self.listen = "both"
        self.tokens_in = self.tokens_out = self.reasoning = 0
        self.calls = self.fallbacks = self.api_errors = 0
        self.signals_read = 0        # how many señas this agent has read
        self.want_signals = False    # open the señas API next turn?
        self.invalid_signals = 0
        self.senas_log = []          # (turn, gesture, truthful) for review
        self.rejections = 0          # illegal actions / false declarations
        self.redactions = 0          # chat messages that leaked card info
        self.verbose = False

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
        if REASONING_MODE != "omit":
            p["reasoning_effort"] = REASONING_MODE
        return p

    # ---------------- one decision ----------------
    def decide(self, prompt: str) -> dict:
        max_tokens = MAX_RESP
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
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Content-Type": "application/json"},
                    json=self._payload(prompt, max_tokens),
                    timeout=timeout)
            try:
                d = apifail.call_with_retries(_call, self.provider,
                                              what=f"{self.name}/{self.model}",
                                              deadline=self.deadline)
            except FatalAPIError:
                self.api_errors += 1
                raise
            except (LLMCallFailure, apifail.RetryableAPIError) as e:
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
            self.reasoning += (u.get("completion_tokens_details") or {}).get(
                "reasoning_tokens") or 0
            content = msg.get("content") or ""
            finish = choice.get("finish_reason")
            if self.verbose:
                print(f"    >>> {self.name} (seat {self.seat}, {self.model}) "
                      f"finish={finish} raw: {content[:400]!r}")
            if finish == "length" or (not content.strip()):
                # truncated (reasoning ate the budget) -> escalate, else re-sample
                if max_tokens < MAX_RESP_CAP:
                    max_tokens = min(max_tokens * 2, MAX_RESP_CAP)
                last_err = LLMCallFailure(f"truncated (finish={finish})")
                continue   # fresh sample: reasoning length is stochastic
            try:
                data = json.loads(_extract_json(content))
                if isinstance(data, dict):
                    return data
                last_err = ValueError(f"JSON is not an object: {type(data)}")
            except json.JSONDecodeError as e:
                last_err = e
                continue  # malformed JSON -> one more clean sample
        raise LLMCallFailure(f"{self.name}/{self.model}: no valid action JSON; "
                             f"last_err={last_err}")


# ---------------- baseline seats ----------------
class BaselineSeat:
    """Plays directly on engine state. No prompt, no API."""

    is_llm = False

    def __init__(self, name: str, kind: str, seat: int, team: int, seed: int = 0):
        self.name, self.seat, self.team = name, seat, team
        self.model = kind
        self.policy = RandomPolicy(seed + seat) if kind == "random" else HeuristicPolicy()
        self.calls = self.fallbacks = self.api_errors = 0
        self.tokens_in = self.tokens_out = self.reasoning = 0
        self.signals_read = 0
        self.want_signals = False
        self.invalid_signals = 0
        self.senas_log = []
        self.rejections = 0
        self.redactions = 0
        self.budget = PerceptionBudget()
        self.listen = "both"
        self.verbose = False

    def decide(self, prompt: str) -> dict:  # never called; interface parity
        raise NotImplementedError


# ---------------- prompt building ----------------
def _cards_str(cards) -> str:
    return ", ".join(str(c) for c in sorted(cards, key=lambda c: c.rank_index))


def _channel_block(ch: Channels, agent, what: str) -> tuple[str, int]:
    if what == "public":
        if not ch.public:
            return "(no one has spoken yet)", 0
        cost = public_cost(len(ch.public))
        lines = [f"  {m.turn}. {m.name} (seat {m.seat}): \"{m.text}\""
                 for m in ch.public]
        return "\n".join(lines), cost
    # The señas API shows ALL gestures to ANY agent -- but only if the agent
    # chooses to listen (paying attention). Gestures are reglamentarias only.
    unread = len(ch.signals) - agent.signals_read
    if not ch.signals:
        return "(no gestures have been made)", 0
    if not agent.want_signals:
        return (f"{unread} unread sena(s) available. Reading costs "
                f"{signals_cost(unread)} attention tokens: set \"read_signals\": "
                f"true in your action to watch next turn."), 0
    cost = signals_cost(unread)
    agent.signals_read = len(ch.signals)
    lines = [f"  {e.turn}. seat {e.from_seat} -> "
             + (f"seat {e.to_seat}" if e.to_seat is not None else "ALL")
             + f": {e.text} (= {SENAS[e.text][0]})" for e in ch.signals]
    return "\n".join(lines) + f"\n  (paid {cost} attention tokens)", cost


def build_prompt(agent: StrictAgent, engine: MusEngine, ch: Channels,
                 legal: list[str], error: str | None = None) -> str:
    lines = [
        f"You are {agent.name}, playing mus in TEAM {agent.team}, seat {agent.seat}.",
        f"Phase: {engine.phase.name}" + (
            f", lance: {LANCE_NAMES[engine.lance_index]}"
            if engine.phase == Phase.ENVITE else ""),
        f"YOUR HAND: {_cards_str(engine.hands[agent.seat])}",
        "",
    ]
    text, cost = _channel_block(ch, agent, "public")
    agent.budget.spend(cost)
    lines.append(f"[PUBLIC GROUP CHAT — all seats hear this; attention cost {cost}; "
                 f"budget left {agent.budget.remaining}. RULE: table talk only -- "
                 f"revealing your cards verbally is forbidden; the harness "
                 f"redacts card names and juego totals. Use señas instead.]")
    lines.append(text)
    lines.append("")
    text, cost = _channel_block(ch, agent, "signals")
    agent.budget.spend(cost)
    lines.append(f"[SIGNALS API — fixed gestures only (e.g. elevar-las-cejas, "
                 f"guinar-el-ojo); anyone may read it, but only if "
                 f"YOU choose to listen]")
    lines.append(text)
    lines.append("")

    if engine.phase == Phase.ENVITE:
        e = engine.envite
        holder_s = (f"seat {e.holder} (team {TEAM_OF[e.holder]})"
                    if e.holder is not None else "none yet")
        lines.append(f"ENVITE STATE: pending stake={e.current} "
                     f"(previous={e.previous}), held by {holder_s}; "
                     f"eliminated seats: {sorted(e.folded) or 'none'}")
        lines.append("Bets: envido=2 stones; y-yo=+2; reenvido=doubles the "
                     "pending stake; quiero=accept (cards compared at lance "
                     "end); no-quiero=decline (the holder takes the previous "
                     "stake -- or 1 deje -- AND the jugada value; you concede "
                     "the jugada); ordago=all-in for the whole game.")
    if engine.phase == Phase.DECLARE:
        lance = LANCE_NAMES[engine.lance_index]
        lines.append(f"DECLARATION ROUND for {lance}: each seat truthfully says "
                     f"'tengo' or 'no-tengo' (false declarations are rejected). "
                     f"Envites only start if EACH team has a declarer.")
    if engine.phase == Phase.ORDAGO_RESPONSE:
        stake = engine.envite.previous or 1
        lines.append(f"ORDAGO from seat {engine.ordago_caller} "
                     f"(team {TEAM_OF[engine.ordago_caller]}), current stake={stake}. "
                     f"'quiero' = the WHOLE game is decided by comparing hands. "
                     f"'no-quiero' = the caller's team scores the previous stake "
                     f"({stake}), plus the jugada value for a lance ordago, "
                     f"and play continues. Declining does NOT hand "
                     f"them the game.")

    lines.append("Legal action names: " + ", ".join(legal))
    if error:
        lines.append(f"Your last action was REJECTED: {error}. "
                     f"Return a legal action.")
    lines.append("Rules of this phase:")
    if engine.phase == Phase.MUS_REQUEST:
        lines.append('  - "mus": want to replace cards (only happens if EVERYONE '
                     'says mus). "no": denies mus -> NOBODY discards, the hand is '
                     'played as dealt. The mano (first seat) may "ordago".')
    elif engine.phase == Phase.MUS_DRAW:
        lines.append('  - action "discard" with "cards": names of cards from '
                     'YOUR HAND, count 1-4.')
    elif engine.phase == Phase.ENVITE:
        lines.append('  - stake 0: "paso" | "envido" (bet 2) | "ordago". '
                     'Stake pending, opponent side: "quiero" | "no-quiero" | '
                     '"y-yo" (+2) | "reenvido" (double) | "ordago". Your own '
                     'team holds the bet: "paso" (step aside) | raise | "ordago". '
                     'NOTE: tres counts as rey, dos counts as as (8 reyes/8 ases).')
    elif engine.phase == Phase.ORDAGO_RESPONSE:
        lines.append('  - "quiero": accept -> whole game decided by the hand '
                     'comparison. "no-quiero": decline -> the caller takes the '
                     'previous stake plus the jugada value, and play continues.')
    lines.append("SENAS (reglamentarias): gestures are made AT THE TABLE and "
                 "are always PUBLIC -- there is no private signalling. Any seat "
                 "(including opponents) can catch a seña by attending to the "
                 "señas API. Fixed gestures with fixed meanings only:")
    lines.append(senas.vocabulary_for_prompt())
    lines.append("Most hands have NO seña available: then omit 'signal' "
                 "entirely. Gesture only what is worth the leak -- your "
                 "opponents will see it if they pay attention.")
    lines.append("Answer with ONLY a JSON object:")
    lines.append('{"action": "<name>", "read_signals": <true|false>, '
                 '"message": "<table talk, max 20 words, NO card names>", '
                 '"signal": "<one seña gesture from the list, or null>", '
                 '"cards": [card names]}')
    lines.append('"read_signals": true opens the signals API NEXT turn (it '
                 'costs attention per unread signal).')
    return "\n".join(lines)


CARD_TALK_RE = re.compile(
    r"\b(as|ases|dos|doses|tres|treses|cuatro|cuatros|cinco|cincos|seis|sietes?"
    r"|sota|sotas|caballo|caballos|rey|reyes|pitos|oros|copas|espadas|bastos"
    r"|3[0-9]|40)\b", re.I)


def redact_card_talk(text: str) -> str:
    """Fournier: 'No se permite decir ni ensenar las cartas.' Table talk only:
    ranks, suits and juego totals are redacted from public messages."""
    return CARD_TALK_RE.sub("[cartas]", text)


def _record_event(stats: dict | None, text: str) -> None:
    if stats is not None:
        stats.setdefault("events", []).append(text)


def _emit(agent, action: dict, ch: Channels, engine: MusEngine,
          stats: dict | None = None, hand=None) -> None:
    """Publish accepted actions; validate gestures against the decision-time hand."""
    msg = action.get("message")
    if isinstance(msg, str) and msg.strip():
        original = " ".join(msg.split()[:20])[:120]
        clean = redact_card_talk(original)
        if clean != original:
            agent.redactions += 1
            _record_event(stats, f"[{agent.name}] CHAT REDACTED")
        ch.say_public(agent.seat, agent.name, clean)
    agent.want_signals = action.get("read_signals") is True
    sig = action.get("signal")
    if isinstance(sig, dict):  # Accept older clients as well as the prompt schema.
        sig = sig.get("text") or sig.get("gesture")
    if sig is None:
        return
    if not isinstance(sig, str) or not is_valid_sena(sig):
        agent.invalid_signals += 1
        return
    gesture = sig.strip().lower()
    truthful = sena_truthful(
        gesture, engine.hands[agent.seat] if hand is None else hand, engine)
    agent.senas_log.append((gesture, truthful))
    if truthful:
        ch.send_signal(agent.seat, None, gesture)
    else:
        agent.invalid_signals += 1
        _record_event(stats, f"[{agent.name}] SEÑA FALSA rejected: {gesture}")


def _default_legal(engine: MusEngine, seat: int) -> dict:
    legal = engine.legal_actions(seat)
    if not legal:
        raise IllegalAction(f"no legal actions for seat {seat} "
                            f"in phase {engine.phase.name}")
    if engine.phase == Phase.DECLARE:
        return HeuristicPolicy().act(engine, seat, legal)
    action = {"action": legal[0]}
    if engine.phase == Phase.MUS_DRAW:
        action["cards"] = [str(engine.hands[seat][0])]
    return action


# ---------------- match loop ----------------
def play_turn(engine: MusEngine, agent, ch: Channels,
              stats: dict, verbose: bool = False) -> None:
    stats.setdefault("events", [])
    stats["turns"] = stats.get("turns", 0) + 1
    if not agent.is_llm:
        legal = engine.legal_actions(agent.seat)
        action = agent.policy.act(engine, agent.seat, legal)
        engine.apply(agent.seat, action)
        if verbose:
            print(f"  [{agent.name}/seat{agent.seat}] {action}")
        return
    stats["llm_turns"] = stats.get("llm_turns", 0) + 1
    last_error = None
    legal = engine.legal_actions(agent.seat)
    prompt = build_prompt(agent, engine, ch, legal)
    hand = list(engine.hands[agent.seat])
    for attempt in range(4):
        retry_prompt = prompt
        if last_error:
            retry_prompt += f"\nYour last action was REJECTED: {last_error}. Return a legal action."
        action = agent.decide(retry_prompt)   # raises on API failure -- loud
        try:
            engine.apply(agent.seat, action)
            _emit(agent, action, ch, engine, stats, hand=hand)
            if verbose:
                _print_turn(agent, action, ch)
            return
        except IllegalAction as e:
            last_error = str(e)
            agent.rejections += 1
            stats["events"].append(
                f"[{agent.name}/{agent.model}] REJECTED ({engine.phase.name}): {e}")
            if verbose:
                print(f"  [seat{agent.seat}] REJECTED: {e}")
    # last-resort fallback -- counted, never silent
    agent.fallbacks += 1
    stats["events"].append(f"[{agent.name}] FALLBACK after 4 rejects: {last_error}")
    stats["fallbacks"] += 1
    if (stats["llm_turns"] >= FALLBACK_MIN_TURNS
            and stats["fallbacks"] / stats["llm_turns"] > MAX_FALLBACK_RATE):
        raise DegradedMatch(
            f"fallback rate {stats['fallbacks']}/{stats['llm_turns']} LLM turns exceeds "
            f"{MAX_FALLBACK_RATE:.0%} -- aborting (results would be noise)")
    action = _default_legal(engine, agent.seat)
    engine.apply(agent.seat, action)
    _emit(agent, action, ch, engine, stats, hand=hand)
    if verbose:
        print(f"  [seat{agent.seat}] FALLBACK -> {action}")
        _print_turn(agent, action, ch)


def _print_turn(agent, action: dict, ch: Channels) -> None:
    msg = action.get("message")
    if msg:
        print(f"  [{agent.name}/seat{agent.seat}] PUB: {msg}")
    sig = action.get("signal")
    if sig:
        print(f"  [{agent.name}/seat{agent.seat}] requested SEÑA: {sig}")
    print(f"  ({agent.name} listen={agent.listen} budget={agent.budget.remaining})")


def reset_hand_channels(agents: list, ch: Channels) -> None:
    for a in agents:
        a.budget.reset()
        a.signals_read = 0
        a.want_signals = False
    ch.clear()


def run_hand(engine: MusEngine, agents: list, ch: Channels,
             stats: dict, verbose: bool = False, deadline: float | None = None):
    reset_hand_channels(agents, ch)
    engine.deal()
    v_a0, v_b0 = engine.vacas_a, engine.vacas_b
    turns = 0
    while engine.phase != Phase.DONE:
        if deadline is not None and time.monotonic() >= deadline:
            raise MatchTimeout("match deadline reached during hand")
        turns += 1
        if turns > MAX_TURNS_PER_HAND:
            raise TurnLimitExceeded(
                f"hand exceeded {MAX_TURNS_PER_HAND} turns -- engine deadlock guard")
        play_turn(engine, agents[engine.current_seat], ch, stats, verbose)
        if deadline is not None and time.monotonic() >= deadline:
            raise MatchTimeout("match deadline reached during turn")
    return engine.vacas_a - v_a0, engine.vacas_b - v_b0, engine.hand_winner


def _make_agent(spec, seat: int, team: int, seed: int = 0):
    if isinstance(spec, (tuple, list)) and len(spec) == 2:
        provider, model = str(spec[0]), str(spec[1])
    elif isinstance(spec, str) and ":" in spec:
        provider, model = spec.split(":", 1)
    else:
        provider, model = DEFAULT_PROVIDER, str(spec)
    if model in ("heuristic", "random"):
        return BaselineSeat(f"{'HA' if model == 'heuristic' else 'RA'}{seat}",
                            model, seat, team, seed)
    return StrictAgent(f"{'A' if team == 0 else 'B'}{seat}", model, seat, team,
                       provider)


def run_match_strict(engine: MusEngine, models: list, hands: int = 12, seed: int = 0,
                     verbose: bool = False, vaca_callback=None,
                     hand_callback=None) -> dict:
    if len(models) != 4 or any(not m for m in models):
        raise ValueError("exactly four non-empty model specs are required")
    if hands <= 0:
        raise ValueError("hands must be positive")
    t0 = time.monotonic()
    deadline = t0 + MATCH_TIMEOUT
    agents = [_make_agent(m, s, TEAM_OF[s], seed) for s, m in enumerate(models)]
    ch = Channels()
    for a in agents:
        a.verbose = verbose
        if a.is_llm:
            a.deadline = deadline
    stats = {"turns": 0, "fallbacks": 0, "events": []}
    va = vb = hwa = hwb = 0

    def _report_vaca(va_, vb_, tot_a, tot_b):
        if vaca_callback:
            vaca_callback(va_, vb_, tot_a, tot_b)
        else:
            print(f"  [VACA] +{va_} A / +{vb_} B   -> total vacas A={tot_a} B={tot_b}")

    engine.vaca_callback = _report_vaca

    for h in range(hands):
        if time.monotonic() - t0 > MATCH_TIMEOUT:
            raise MatchTimeout(
                f"match exceeded {MATCH_TIMEOUT:.0f}s wall clock at hand {h + 1}")
        a, b, winner = run_hand(engine, agents, ch, stats, verbose, deadline=deadline)
        va += a
        vb += b
        if verbose:
            print(f"Hand {h + 1}/{hands}: +{a} vacas A / +{b} vacas B "
                  f"(running A={va} B={vb})")
        if hand_callback:
            hand_callback(h + 1, a, b, winner, va, vb)
        if winner == 0:
            hwa += 1
        elif winner == 1:
            hwb += 1

    usage = {
        "tokens_in": sum(a.tokens_in for a in agents),
        "tokens_out": sum(a.tokens_out for a in agents),
        "reasoning": sum(a.reasoning for a in agents),
        "calls": sum(a.calls for a in agents),
        "fallbacks": stats["fallbacks"],
        "turns": stats["turns"],
        "llm_turns": stats.get("llm_turns", 0),
    }
    return {
        "vacas_a": va, "vacas_b": vb, "hand_wins_a": hwa, "hand_wins_b": hwb,
        "hands": hands, "models": list(models), "usage": usage,
        "agents": [{"name": a.name, "model": a.model, "seat": a.seat,
                    "is_llm": a.is_llm, "calls": a.calls,
                    "fallbacks": a.fallbacks, "api_errors": a.api_errors,
                    "rejections": a.rejections, "redactions": a.redactions,
                    "invalid_signals": a.invalid_signals,
                    "senas": a.senas_log,
                    "tokens_in": a.tokens_in, "tokens_out": a.tokens_out,
                    "reasoning": a.reasoning} for a in agents],
        "events": stats["events"],
        "status": "done",
        "elapsed": round(time.monotonic() - t0, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models",
                    default="deepseek-v4-flash,heuristic,deepseek-v4-flash,heuristic",
                    help="4 specs: model-name (nan), provider:model via tuple in "
                         "code, or heuristic/random for baseline seats")
    ap.add_argument("--hands", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    models = [m.strip() for m in args.models.split(",")]
    if len(models) != 4 or any(not m for m in models):
        ap.error("--models requires exactly four non-empty comma-separated specs")
    if args.hands <= 0:
        ap.error("--hands must be positive")
    print(f"Match: {' vs '.join(models)}  "
          f"(teams: {models[0]}+{models[2]} | {models[1]}+{models[3]})")
    print(f"hands={args.hands} seed={args.seed} "
          f"reasoning={REASONING_MODE} max_tokens={MAX_RESP}\n")
    res = run_match_strict(MusEngine(rng=Random(args.seed)), models, hands=args.hands,
                           seed=args.seed, verbose=args.verbose)
    print(f"\nResult: vacas {res['vacas_a']}-{res['vacas_b']}  hands={res['hands']} "
          f"status={res['status']}")
    print(f"Token usage: in={res['usage']['tokens_in']} "
          f"out={res['usage']['tokens_out']} (reasoning={res['usage']['reasoning']}) "
          f"calls={res['usage']['calls']} fallbacks={res['usage']['fallbacks']}"
          f"/{res['usage']['turns']} turns elapsed={res['elapsed']}s")
    if args.out:
        with open(args.out, "w") as f:
            json.dump(res, f, indent=2)
        print(f"Saved -> {args.out}")


if __name__ == "__main__":
    main()
