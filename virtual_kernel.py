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
import signal_bus
from signal_bus import SignalBus
from signal_manager import (SignalManager, PublishIntent, partner_of,
                            reference_policy, silent_policy, DEFAULT_TTL)
from apifail import (MatchTimeout, DegradedMatch, TurnLimitExceeded,
                     LLMCallFailure, RetryableAPIError, MATCH_TIMEOUT,
                     MAX_TURNS_PER_HAND, backoff_delay)

# Outer, decision-level retry: how many times to ride out a provider outage
# before giving up on a decision and playing the legal default.
DECISION_RETRIES = int(os.environ.get("DECISION_RETRIES", "4"))
DECISION_BACKOFF = float(os.environ.get("DECISION_BACKOFF", "20.0"))
DECISION_BACKOFF_MAX = float(os.environ.get("DECISION_BACKOFF_MAX", "300.0"))
from decision_log import (DecisionLog, build_decision, build_hand,
                          dealt_snapshot, truth_snapshot)
from match_history import MatchHistory
from turn_feed import TurnFeed
import vaca_notes

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
    intercepted: int = 0      # rival senas this seat saw over the rival's shoulder

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
                     "truthful": ev.truthful_at_pub,
                     "stolen": ev.to_seat != agent.seat} for ev in delivered],
           "prompt": io.get("prompt"), "raw": io.get("raw"),
           "action": action}
    with open(path, "a", encoding="utf8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _log_decision(stats: dict, agent, truth: dict, t: float, *, legal, action,
                  delivered=None, rejections: int = 0,
                  fallback: bool = False) -> None:
    """Record the turn: cross-hand history (public facts the table saw) and
    the ground-truth decision log, if one is attached."""
    name = action.get("action") if isinstance(action, dict) else None
    feed = stats.get("feed") if stats else None
    if feed is not None:
        feed.record(turn=stats.get("turns", 0), hand=stats.get("hand", 0),
                    seat=agent.seat, phase=truth.get("phase", ""),
                    lance=truth.get("lance"), action=action,
                    thought=(action.get("thought")
                             if isinstance(action, dict) else None))
    hist = stats.get("history") if stats else None
    if hist is not None:
        hist.record_decision(agent.seat, name, lance=truth.get("lance"),
                             facing_bet=truth.get("facing_bet", False),
                             holder_team=truth.get("holder_team"))
    log = stats.get("decision_log") if stats else None
    if log is None or not log.enabled:
        return
    read = action.get("read") if isinstance(action, dict) else None
    log.write(build_decision(
        agent, truth,
        hand=stats.get("hand", 0), turn=stats.get("turns", 0), t=t,
        legal=legal, action=action, delivered=delivered,
        rejections=rejections, fallback=fallback,
        read=read if isinstance(read, dict) else None))


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
        bus.deliver(delivered, t0, seat=proc.seat)
        stolen = [ev for ev in delivered if ev.to_seat != proc.seat]
        proc.delivered += len(delivered) - len(stolen)
        proc.intercepted += len(stolen)
        for ev in delivered:
            kind = ("INTERCEPTED" if ev.to_seat != proc.seat else "caught")
            _record_event(stats, f"[seat{proc.seat}] {kind} {ev.gesture} "
                                 f"from seat {ev.from_seat} (published t={ev.t_pub:.2f})")
    if not agent.is_llm:
        legal = engine.legal_actions(agent.seat)
        action = agent.policy.act(engine, agent.seat, legal)
        truth = truth_snapshot(engine, agent.seat)
        engine.apply(agent.seat, action)
        _log_decision(stats, agent, truth, t0, legal=legal, action=action,
                      delivered=delivered)
        kernel.now = t0 + window
        if verbose:
            print(f"  [{agent.name}/seat{agent.seat}] {action}")
        return
    stats["llm_turns"] = stats.get("llm_turns", 0) + 1
    last_error = None
    api_failed = False
    legal = engine.legal_actions(agent.seat)
    hand = list(engine.hands[agent.seat])   # truth of gestures = hand AT deliberation
    prompt = build_prompt(agent, engine, ch, legal, delivered=delivered,
                          history=stats.get("history"),
                          policy=proc.manager.policy,
                          feed=stats.get("feed"),
                          notes=stats.get("notes"))
    # Two nested retry layers, both exponential:
    #   inner  MAX_REJECT_RETRIES  -- the model returned a LEGAL-ly wrong action;
    #                                re-prompt immediately with the engine's
    #                                complaint, no point waiting.
    #   outer  DECISION_RETRIES    -- the PROVIDER failed for this whole
    #                                decision (all CALL_ATTEMPTS exhausted, or
    #                                the breaker is open). Waiting is exactly
    #                                right here: a fallback action is a poisoned
    #                                data point that counts toward DegradedMatch,
    #                                so riding out a blip is strictly better
    #                                than playing a default.
    for decision_attempt in range(DECISION_RETRIES + 1):
      for attempt in range(MAX_REJECT_RETRIES):
        retry_prompt = prompt
        if last_error:
            retry_prompt += (f"\nYour last action was REJECTED: {last_error}. "
                             f"Return a legal action.")
        try:
            action = agent.decide(retry_prompt)
        except LLMCallFailure as e:
            agent.api_errors += 1
            stats["events"].append(
                f"[{agent.name}/{agent.model}] API FAILURE "
                f"(decision attempt {decision_attempt + 1}"
                f"/{DECISION_RETRIES + 1}): {e}")
            if verbose:
                print(f"  [seat{agent.seat}] API FAILURE: {e}")
            api_failed = True
            break
        try:
            truth = truth_snapshot(engine, agent.seat)
            engine.apply(agent.seat, action)
            _emit_kernel(proc, action, ch, engine, bus, kernel, stats,
                         hand=hand)
            _dump_io(agent, t0, phase0, delivered, action)
            _log_decision(stats, agent, truth, t0, legal=legal, action=action,
                          delivered=delivered, rejections=attempt)
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
      else:
          break            # rejects exhausted, not a provider problem
      if not api_failed or decision_attempt >= DECISION_RETRIES:
          break
      api_failed = False
      delay = backoff_delay(decision_attempt, DECISION_BACKOFF,
                            DECISION_BACKOFF_MAX)
      if agent.deadline is not None:
          delay = min(delay, max(0.0, agent.deadline - time.monotonic()))
          if delay <= 0:
              break        # the match deadline will stop us anyway
      stats["events"].append(
          f"[{agent.name}] waiting {delay:.0f}s before retrying the decision")
      if verbose:
          print(f"  [seat{agent.seat}] provider down -- waiting {delay:.0f}s "
                f"before retry {decision_attempt + 2}/{DECISION_RETRIES + 1}")
      time.sleep(delay)
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
    truth = truth_snapshot(engine, agent.seat)
    engine.apply(agent.seat, action)
    _emit_kernel(proc, action, ch, engine, bus, kernel, stats, hand=hand)
    _log_decision(stats, agent, truth, t0, legal=legal, action=action,
                  delivered=delivered, rejections=MAX_REJECT_RETRIES,
                  fallback=True)
    kernel.now = t0 + window
    if verbose:
        print(f"  [seat{agent.seat}] FALLBACK -> {action}")


def close_vaca(procs, engine, stats, vaca: int, verbose: bool = False) -> None:
    """Vaca boundary: ask each LLM seat for its carry-forward note, then clear
    the turn feed. Order matters -- the note is written FROM the feed that is
    about to be discarded, which is what makes it the only thing that crosses.
    """
    feed, notes = stats.get("feed"), stats.get("notes")
    if notes is not None:
        for proc in procs:
            agent = proc.agent
            if not agent.is_llm:
                continue
            rows = feed.view_for(agent.seat) if feed is not None else []
            team = TEAM_OF[agent.seat]
            prompt = vaca_notes.reflection_prompt(
                agent, rows, vaca=vaca,
                points_mine=(engine.points_a if team == 0 else engine.points_b),
                points_theirs=(engine.points_b if team == 0 else engine.points_a),
                previous=notes.get(agent.seat))
            try:
                reply = agent.decide(prompt)
            except (LLMCallFailure, RetryableAPIError) as e:
                _record_event(stats, f"[{agent.name}] NOTE FAILED: {e}")
                continue
            raw = (getattr(agent, "last_io", None) or {}).get("raw")
            text = vaca_notes.extract_note(reply)
            saved = notes.set(agent.seat, text, vaca=vaca, raw=raw)
            _dump_io(agent, 0.0, "VACA_NOTE", [], reply)
            _record_event(stats, f"[{agent.name}] note for vaca {vaca + 1}: "
                                 f"{len(saved or '')} chars")
            if verbose:
                print(f"  [{agent.name}] NOTE: {(saved or '(none)')[:160]}")
    if feed is not None:
        feed.reset(vaca)


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
        if stats is not None:
            stats["dealt"] = dealt_snapshot(engine)
            _record_event(stats, "DEAL " + " ".join(
                f"seat{s}:" + ",".join(str(c) for c in engine.hands[s])
                for s in range(4)))
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
    va, vb = engine.vacas_a - v_a0, engine.vacas_b - v_b0
    hist = stats.get("history") if stats else None
    if hist is not None:
        hist.close_hand(engine, stats.get("hand", 0))
    log = stats.get("decision_log") if stats else None
    if log is not None and log.enabled:
        log.write(build_hand(engine, hand=stats.get("hand", 0),
                             t=kernel.now, va_delta=va, vb_delta=vb,
                             dealt=stats.get("dealt")))
    return va, vb, engine.hand_winner


def _serialize_events(bus: SignalBus, hand: int) -> list[dict]:
    return [{"hand": hand, "seq": ev.seq, "t_pub": round(ev.t_pub, 3),
             "from": ev.from_seat, "to": ev.to_seat, "gesture": ev.gesture,
             "truthful": ev.truthful_at_pub,
             "intercepted_by": sorted(ev.intercepted_by),
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
                     vaca_callback=None, hand_callback=None,
                     decision_log: DecisionLog | None = None,
                     turn_feed: bool = False) -> dict:
    if len(models) != 4 or any(not m for m in models):
        raise ValueError("exactly four non-empty model specs are required")
    if hands <= 0:
        raise ValueError("hands must be positive")
    t0 = time.monotonic()
    deadline = t0 + MATCH_TIMEOUT
    agents = [_make_agent(m, s, TEAM_OF[s], seed) for s, m in enumerate(models)]
    procs = make_procs(agents)
    ch = Channels()
    # interception rolls draw from their own seeded stream so that turning
    # interception on/off never reshuffles the deal/jitter randomness
    bus = SignalBus(rng=Random(f"{seed}:signals"),
                    intercept_prob=signal_bus.INTERCEPT_PROB)
    kernel = Kernel(rng=Random(seed))
    for a in agents:
        a.verbose = verbose
        if a.is_llm:
            a.deadline = deadline
    # Two orthogonal axes. WITHIN a vaca a seat sees either the raw turn feed
    # (turn_feed=True) or the harness-written dossier (the default). ACROSS a
    # vaca it carries either nothing or its own note (VACA_MEMORY=notes).
    memory = vaca_notes.mode()
    stats = {"turns": 0, "fallbacks": 0, "events": [], "signal_events": [],
             "decision_log": decision_log, "hand": 0,
             "history": MatchHistory(),
             "feed": TurnFeed() if turn_feed else None,
             "notes": vaca_notes.NoteBook() if memory == "notes" else None}
    va = vb = hwa = hwb = 0
    piedras_a = piedras_b = 0     # cumulative, immune to the 40-point reset
    hand_rows: list[dict] = []

    def _report_vaca(va_, vb_, tot_a, tot_b):
        if vaca_callback:
            vaca_callback(va_, vb_, tot_a, tot_b)
        else:
            print(f"  [VACA] +{va_} A / +{vb_} B   -> total vacas A={tot_a} B={tot_b}")

    engine.vaca_callback = _report_vaca

    status = "done"
    abort_reason = None
    for h in range(hands):
        if time.monotonic() - t0 > MATCH_TIMEOUT:
            status, abort_reason = "timeout", (
                f"match exceeded {MATCH_TIMEOUT:.0f}s wall clock at hand {h + 1}")
            _record_event(stats, f"ABORT ({status}): {abort_reason}")
            break
        stats["hand"] = h + 1
        try:
            a, b, winner = run_hand_kernel(engine, procs, ch, bus, kernel,
                                           stats, verbose, deadline=deadline)
        except (DegradedMatch, MatchTimeout, TurnLimitExceeded) as e:
            # every hand before this one is real data and is already on disk;
            # surface the abort in the result rather than losing the match.
            status = {DegradedMatch: "degraded", MatchTimeout: "timeout",
                      TurnLimitExceeded: "deadlock"}[type(e)]
            abort_reason = str(e)
            stats["signal_events"].extend(_serialize_events(bus, h + 1))
            _record_event(stats, f"ABORT ({status}): {abort_reason}")
            if verbose:
                print(f"\nABORT after {h} complete hands ({status}): {e}")
            break
        stats["signal_events"].extend(_serialize_events(bus, h + 1))
        va += a
        vb += b
        # piedras are the low-variance outcome: hand_gain_* is the per-hand
        # award, unaffected by the vaca reset that zeroes BOTH counters.
        piedras_a += engine.hand_gain_a
        piedras_b += engine.hand_gain_b
        if a or b:                      # a vaca was decided in this hand
            close_vaca(procs, engine, stats, va + vb, verbose)
        hand_rows.append({"hand": h + 1, "gain_a": engine.hand_gain_a,
                          "gain_b": engine.hand_gain_b, "winner": winner,
                          "vaca_a": a, "vaca_b": b})
        if verbose:
            print(f"Hand {h + 1}/{hands}: +{a} vacas A / +{b} vacas B "
                  f"(running A={va} B={vb})  "
                  f"piedras {piedras_a}-{piedras_b}  clock={kernel.now:.2f}")
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
        "intercepted": sum(p.intercepted for p in procs),
    }
    return {
        "vacas_a": va, "vacas_b": vb, "hand_wins_a": hwa, "hand_wins_b": hwb,
        "piedras_a": piedras_a, "piedras_b": piedras_b,
        "hand_rows": hand_rows,
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
                    "signals_intercepted": p.intercepted,
                    "signal_bluffs": p.manager.bluffs,
                    "invalid_policies": p.manager.invalid_policies,
                    "tokens_in": a.tokens_in, "tokens_out": a.tokens_out,
                    "reasoning": a.reasoning} for a, p in zip(agents, procs)],
        "signal_events": stats["signal_events"],
        # every self-written note, verbatim, with the vaca that produced it
        "vaca_notes": (stats["notes"].history if stats.get("notes") else []),
        "memory_mode": memory,
        "turn_feed": bool(stats.get("feed")),
        "events": [e for e in stats["events"]],
        "status": status,
        "abort_reason": abort_reason,
        "hands_completed": len(hand_rows),
        "elapsed": round(time.monotonic() - t0, 1),
    }
