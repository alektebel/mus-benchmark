"""Match loop for the strict mus harness: one turn, one hand, one match."""
from __future__ import annotations

import time

from mus_engine import MusEngine, Phase, IllegalAction, TEAM_OF
from groupchat import Channels
from prompt_builder import build_prompt, redact_card_talk
from agents import _make_agent, _default_legal, MAX_FALLBACK_RATE, FALLBACK_MIN_TURNS
from senas import is_valid_sena, sena_truthful
from apifail import (FatalAPIError, LLMCallFailure, MatchTimeout, DegradedMatch,
                     TurnLimitExceeded, MATCH_TIMEOUT, MAX_TURNS_PER_HAND)


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