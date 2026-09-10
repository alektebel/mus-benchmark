"""Discrete-event virtual clock driving the strict mus engine.

The game stays sequential: exactly one seat deliberates at a time and gets one
API call per decision (plus the existing reject-retry budget), so the model
provider is never over-used. What the kernel adds is mus's REAL-TIME layer:

  * every decision occupies a VIRTUAL window [t0, t0+W]; W is deterministic
    (phase-scaled, optionally seeded-jittered), never measured wall clock, so
    runs remain reproducible;
  * at the START of each window every seat's SignalManager is evaluated, so
    idle partners can schedule a sena INSIDE the deliberating seat's window
    at their policy's offset;
  * delivery is BATCHED: the actor sees the senas already published at window
    start; mid-window gestures inform its NEXT deliberation, and expire if the
    partner never looks in time (TTL). Preemptive delivery (interrupting the
    in-flight decision) is the planned phase-2 mode: the timestamps, offsets
    and windows it needs already exist here.

The engine remains the sole authority on game legality; the bus cannot touch
engine state, exactly like a wink at the table cannot.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from random import Random

from mus_engine import MusEngine, Phase, IllegalAction, TEAM_OF
from groupchat import Channels
from agents import (_make_agent, _default_legal, MAX_FALLBACK_RATE,
                    FALLBACK_MIN_TURNS)
from prompt_builder import build_prompt, redact_card_talk
from match import _record_event, MAX_REJECT_RETRIES
from senas import is_valid_sena, sena_truthful
from signal_bus import SignalBus
from signal_manager import (SignalManager, PublishIntent, partner_of,
                            reference_policy, silent_policy, DEFAULT_TTL)
from apifail import (MatchTimeout, DegradedMatch, TurnLimitExceeded,
                     LLMCallFailure, MATCH_TIMEOUT, MAX_TURNS_PER_HAND)

KERNEL_WINDOW = float(os.environ.get("KERNEL_WINDOW", "1.0"))
KERNEL_WINDOW_JITTER = float(os.environ.get("KERNEL_WINDOW_JITTER", "0.0"))
# Phase-dependent deliberation time (real mus: saying "tengo" is instant,
# answering an ordago is not). Format: PHASE:mult,PHASE:mult,...
_PHASE_MULT_SPEC = os.environ.get(
    "KERNEL_WINDOW_PHASE_MULT",
    "MUS_REQUEST:1.0,MUS_DRAW:1.0,DECLARE:0.5,ENVITE:1.5,ORDAGO_RESPONSE:2.0")
ALLOW_SEÑA_BLUFFS = os.environ.get("ALLOW_SEÑA_BLUFFS", "1").strip().lower() \
    in ("1", "true", "yes")


def _phase_mults() -> dict[str, float]:
    out = {}
    for pair in _PHASE_MULT_SPEC.split(","):
        k, _, v = pair.partition(":")
        if k.strip() and v.strip():
            out[k.strip()] = float(v)
    return out


PHASE_MULTS = _phase_mults()


@dataclass
class SeatProcess:
    """One seat = one player agent (sequential decisions) + one SignalManager
    (the seat's declared seña policy)."""
    agent: object
    manager: SignalManager
    decisions: int = 0
    delivered: int = 0        # senas this seat caught at window start

    @property
    def seat(self) -> int:
        return self.agent.seat


class Kernel:
    """Virtual clock + deterministic window allocator."""

    def __init__(self, rng: Random | None = None, window: float | None = None,
                 jitter: float | None = None):
        self.rng = rng or Random()
        # read the module globals at construction so CLI/env overrides apply
        self.window = KERNEL_WINDOW if window is None else window
        self.jitter = KERNEL_WINDOW_JITTER if jitter is None else jitter
        self.now = 0.0

    def window_for(self, phase: Phase) -> float:
        w = self.window * PHASE_MULTS.get(phase.name, 1.0)
        if self.jitter > 0.0:
            w *= 1.0 + self.jitter * (2.0 * self.rng.random() - 1.0)
        return w


def _publish_intents(proc: SeatProcess, intents: list[PublishIntent],
                     bus: SignalBus, stats: dict | None = None) -> None:
    target = partner_of(proc.seat)
    for it in intents:
        bus.publish(proc.seat, target, it.gesture, it.t_pub, it.ttl,
                    truthful_at_pub=it.truthful)
        proc.manager.published += 1
        if not it.truthful:
            _record_event(stats, f"[seat{proc.seat}] SEÑA BLUFF {it.gesture} "
                                 f"@t={it.t_pub:.2f}")


def _dump_io(agent, t: float, phase: str, delivered, action: dict) -> None:
    """KERNEL_LOG_IO=<path.jsonl>: verbatim per-decision input/output record
    (prompt the model saw, raw completion, accepted action, seen gestutes)."""
    path = os.environ.get("KERNEL_LOG_IO")
    if not path:
        return
    io = getattr(agent, "last_io", None) or {}
    rec = {"t": round(t, 3), "phase": phase, "seat": agent.seat,
           "model": getattr(agent, "model", None),
           "seen": [{"from": ev.from_seat, "gesture": ev.gesture,
                     "truthful": ev.truthful_at_pub} for ev in delivered],
           "prompt": io.get("prompt"), "raw": io.get("raw"),
           "action": action}
    with open(path, "a", encoding="utf8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _emit_kernel(proc: SeatProcess, action: dict, ch: Channels,
                 engine: MusEngine, bus: SignalBus, kernel: Kernel,
                 stats: dict | None = None,
                 hand: list | None = None) -> None:
    """Accepted-action side effects: table talk, private thought, one-shot
    gesture at the current time, and (re)declaring the signal policy."""
    agent = proc.agent
    msg = action.get("message")
    if isinstance(msg, str) and msg.strip():
        original = " ".join(msg.split()[:20])[:120]
        clean = redact_card_talk(original)
        if clean != original:
            agent.redactions += 1
            _record_event(stats, f"[{agent.name}] CHAT REDACTED")
        ch.say_public(agent.seat, agent.name, clean)
    thought = action.get("thought")
    if isinstance(thought, str) and thought.strip():
        agent.thoughts.append(thought.strip())
    pol = action.get("signal_policy")
    if isinstance(pol, dict):
        if proc.manager.install_policy(pol):
            _record_event(stats, f"[{agent.name}] signal policy installed "
                                 f"({len(pol.get('rules', []))} rules)")
        else:
            _record_event(stats, f"[{agent.name}] INVALID signal policy rejected")
    sig = action.get("signal")
    if isinstance(sig, dict):
        sig = sig.get("text") or sig.get("gesture")
    if isinstance(sig, str) and sig.strip():
        gesture = sig.strip().lower()
        if not is_valid_sena(gesture):
            agent.invalid_signals += 1
            return
        truthful = sena_truthful(gesture, hand if hand is not None
                                 else engine.hands[agent.seat], engine)
        agent.senas_log.append((gesture, truthful))
        if truthful or ALLOW_SEÑA_BLUFFS:
            if not truthful:
                agent.bluffs += 1
            _publish_intents(proc, [PublishIntent(gesture, kernel.now,
                                                  DEFAULT_TTL, truthful)],
                             bus, stats)
        else:
            agent.invalid_signals += 1


def play_turn_kernel(engine: MusEngine, procs: list[SeatProcess],
                     proc: SeatProcess, ch: Channels,
                     bus: SignalBus, kernel: Kernel, stats: dict,
                     verbose: bool = False) -> None:
    agent = proc.agent
    stats["turns"] = stats.get("turns", 0) + 1
    proc.decisions += 1
    t0 = kernel.now
    window = kernel.window_for(engine.phase)
    phase0 = engine.phase.name
    # every seat's policy reacts to the deliberation about to happen
    for other in procs:
        _publish_intents(other, other.manager.evaluate(engine, proc.seat,
                                                       t0, window, bus),
                         bus, stats)
    delivered = bus.pending_for(proc.seat, t0)
    if delivered:
        bus.deliver(delivered, t0)
        proc.delivered += len(delivered)
        for ev in delivered:
            _record_event(stats, f"[seat{proc.seat}] caught {ev.gesture} "
                                 f"from seat {ev.from_seat} (published t={ev.t_pub:.2f})")
    if not agent.is_llm:
        legal = engine.legal_actions(agent.seat)
        action = agent.policy.act(engine, agent.seat, legal)
        engine.apply(agent.seat, action)
        kernel.now = t0 + window
        if verbose:
            print(f"  [{agent.name}/seat{agent.seat}] {action}")
        return
    stats["llm_turns"] = stats.get("llm_turns", 0) + 1
    last_error = None
    legal = engine.legal_actions(agent.seat)
    hand = list(engine.hands[agent.seat])   # truth of gestures = hand AT deliberation
    prompt = build_prompt(agent, engine, ch, legal, delivered=delivered)
    for attempt in range(MAX_REJECT_RETRIES):
        retry_prompt = prompt
        if last_error:
            retry_prompt += (f"\nYour last action was REJECTED: {last_error}. "
                             f"Return a legal action.")
        try:
            action = agent.decide(retry_prompt)
        except LLMCallFailure as e:
            # provider retries exhausted for this one decision: count it and
            # play on with the legal default; the fallback-rate guard below
            # still aborts a match that degrades into default-action noise
            agent.api_errors += 1
            stats["events"].append(
                f"[{agent.name}/{agent.model}] API FAILURE -> default action: {e}")
            if verbose:
                print(f"  [seat{agent.seat}] API FAILURE: {e} -> default action")
            break
        try:
            engine.apply(agent.seat, action)
            _emit_kernel(proc, action, ch, engine, bus, kernel, stats,
                         hand=hand)
            _dump_io(agent, t0, phase0, delivered, action)
            kernel.now = t0 + window
            if verbose:
                print(f"  [{agent.name}/seat{agent.seat}] {action}"
                      + (f" | caught {len(delivered)} sena(s)" if delivered else ""))
            return
        except IllegalAction as e:
            last_error = str(e)
            agent.rejections += 1
            stats["events"].append(
                f"[{agent.name}/{agent.model}] REJECTED ({engine.phase.name}): {e}")
            if verbose:
                print(f"  [seat{agent.seat}] REJECTED: {e}")
    agent.fallbacks += 1
    reason = "API failure" if agent.api_errors and last_error is None \
        else f"{MAX_REJECT_RETRIES} rejects"
    stats["events"].append(
        f"[{agent.name}] FALLBACK ({reason}): {last_error}")
    stats["fallbacks"] += 1
    if (stats["llm_turns"] >= FALLBACK_MIN_TURNS
            and stats["fallbacks"] / stats["llm_turns"] > MAX_FALLBACK_RATE):
        raise DegradedMatch(
            f"fallback rate {stats['fallbacks']}/{stats['llm_turns']} LLM turns exceeds "
            f"{MAX_FALLBACK_RATE:.0%} -- aborting (results would be noise)")
    action = _default_legal(engine, agent.seat)
    engine.apply(agent.seat, action)
    _emit_kernel(proc, action, ch, engine, bus, kernel, stats, hand=hand)
    kernel.now = t0 + window
    if verbose:
        print(f"  [seat{agent.seat}] FALLBACK -> {action}")


def reset_hand(procs: list[SeatProcess], ch: Channels, bus: SignalBus,
               stats: dict | None = None) -> None:
    # a sena that survives to hand's end undelivered was simply missed --
    # gestures, like hands, do not cross the vaca boundary
    if stats is not None:
        stats["signals_missed"] = stats.get("signals_missed", 0) + sum(
            1 for ev in bus.events if ev.delivered_at is None)
    for p in procs:
        p.agent.budget.reset()
        p.agent.signals_read = 0
        p.agent.want_signals = False
    ch.clear()
    bus.clear()


def run_hand_kernel(engine: MusEngine, procs: list[SeatProcess], ch: Channels,
                    bus: SignalBus, kernel: Kernel, stats: dict,
                    verbose: bool = False, deadline: float | None = None,
                    deal: bool = True):
    reset_hand(procs, ch, bus, stats)
    if deal:
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
        play_turn_kernel(engine, procs, procs[engine.current_seat], ch, bus,
                         kernel, stats, verbose)
        if deadline is not None and time.monotonic() >= deadline:
            raise MatchTimeout("match deadline reached during turn")
    return engine.vacas_a - v_a0, engine.vacas_b - v_b0, engine.hand_winner


def _serialize_events(bus: SignalBus, hand: int) -> list[dict]:
    return [{"hand": hand, "seq": ev.seq, "t_pub": round(ev.t_pub, 3),
             "from": ev.from_seat, "to": ev.to_seat, "gesture": ev.gesture,
             "truthful": ev.truthful_at_pub,
             "delivered_at": ev.delivered_at, "expired": ev.expired}
            for ev in bus.events]


def make_procs(agents: list, allow_bluffs: bool = ALLOW_SEÑA_BLUFFS) -> list[SeatProcess]:
    """Baseline seats get the reference seña policy (the signalling floor);
    LLM seats start silent and must DECLARE a policy to ever gesture."""
    procs = []
    for a in agents:
        policy = reference_policy() if not a.is_llm else silent_policy()
        procs.append(SeatProcess(agent=a, manager=SignalManager(
            seat=a.seat, policy=policy, allow_bluffs=allow_bluffs)))
    return procs


def run_match_kernel(engine: MusEngine, models: list, hands: int = 12,
                     seed: int = 0, verbose: bool = False,
                     vaca_callback=None, hand_callback=None) -> dict:
    if len(models) != 4 or any(not m for m in models):
        raise ValueError("exactly four non-empty model specs are required")
    if hands <= 0:
        raise ValueError("hands must be positive")
    t0 = time.monotonic()
    deadline = t0 + MATCH_TIMEOUT
    agents = [_make_agent(m, s, TEAM_OF[s], seed) for s, m in enumerate(models)]
    procs = make_procs(agents)
    ch = Channels()
    bus = SignalBus()
    kernel = Kernel(rng=Random(seed))
    for a in agents:
        a.verbose = verbose
        if a.is_llm:
            a.deadline = deadline
    stats = {"turns": 0, "fallbacks": 0, "events": [], "signal_events": []}
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
        a, b, winner = run_hand_kernel(engine, procs, ch, bus, kernel, stats,
                                       verbose, deadline=deadline)
        stats["signal_events"].extend(_serialize_events(bus, h + 1))
        va += a
        vb += b
        if verbose:
            print(f"Hand {h + 1}/{hands}: +{a} vacas A / +{b} vacas B "
                  f"(running A={va} B={vb})  clock={kernel.now:.2f}")
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
    signals = {
        "published": sum(p.manager.published for p in procs),
        "caught": sum(p.delivered for p in procs),
        "missed": stats.get("signals_missed", 0) + sum(
            1 for ev in bus.events if ev.delivered_at is None),
    }
    return {
        "vacas_a": va, "vacas_b": vb, "hand_wins_a": hwa, "hand_wins_b": hwb,
        "hands": hands, "models": list(models), "usage": usage,
        "signals": signals,
        "virtual_clock": round(kernel.now, 2),
        "agents": [{"name": a.name, "model": a.model, "seat": a.seat,
                    "is_llm": a.is_llm, "calls": a.calls,
                    "fallbacks": a.fallbacks, "api_errors": a.api_errors,
                    "rejections": a.rejections, "redactions": a.redactions,
                    "invalid_signals": a.invalid_signals,
                    "bluffs": a.bluffs,
                    "senas": a.senas_log,
                    "thoughts": a.thoughts,
                    "policy": p.manager.policy.to_json(),
                    "signals_published": p.manager.published,
                    "signals_caught": p.delivered,
                    "signal_bluffs": p.manager.bluffs,
                    "invalid_policies": p.manager.invalid_policies,
                    "tokens_in": a.tokens_in, "tokens_out": a.tokens_out,
                    "reasoning": a.reasoning} for a, p in zip(agents, procs)],
        "signal_events": stats["signal_events"],
        "events": [e for e in stats["events"]],
        "status": "done",
        "elapsed": round(time.monotonic() - t0, 1),
    }
