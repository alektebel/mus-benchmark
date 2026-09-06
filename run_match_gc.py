"""Single 4-model match with two metered group channels.

Each seat is a distinct model. Teams are {0,2} and {1,3}. There are two
*temporal* channels the agents can listen to:
  * a public group chat (what everyone says aloud), and
  * a signals API (private, addressed agent-to-agent messages).
Listening is metered in tokens, per participant, drained from a per-hand
perception budget (see ``groupchat.py``).

CLI:
  python run_match_gc.py --models m0,m1,m2,m3 --hands 12 [--out gc_result.json]
"""
from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from random import Random

from agent import LLMAgent
import requests

from engine import MusEngine, TEAM_OF
from groupchat import (Channels, PerceptionBudget, public_cost, signals_cost)
from run_match import _match_name, _dedup, _pick_default_discard, _resolve_ordago

BASE = os.environ.get("NAN_API_BASE", "https://api.nan.builders/v1")
API_KEY = os.environ.get("NAN_API_KEY", "")
TIMEOUT = float(os.environ.get("NAN_TIMEOUT", "180"))
MAX_RESP = 700
REASONING_EFFORT = os.environ.get("REASONING_EFFORT", "low")


class GCAgent:
    """A seat + perception budget + last listen preference, backed by the API."""

    def __init__(self, name: str, model: str, seat: int, team: int):
        self.name = name
        self.model = model
        self.seat = seat
        self.team = team
        self.budget = PerceptionBudget()
        self.listen = "both"          # channels included in the next prompt
        self.tokens_in = 0
        self.tokens_out = 0
        self.calls = 0
        self.reasoning = 0

    def _payload(self, prompt: str) -> dict:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content":
                    "You are a mus (Spanish card game) player. Play honestly and tactically."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.4,
            "max_tokens": MAX_RESP,
            "reasoning_effort": REASONING_EFFORT,
        }

    def decide(self, prompt: str) -> dict:
        """Returns the parsed action dict and records real token usage."""
        for attempt in range(3):
            try:
                r = requests.post(f"{BASE}/chat/completions",
                                  headers={"Authorization": f"Bearer {API_KEY}",
                                           "Content-Type": "application/json"},
                                  json=self._payload(prompt), timeout=TIMEOUT)
                r.raise_for_status()
                d = r.json()
                u = d.get("usage", {})
                self.tokens_in += u.get("prompt_tokens", 0)
                self.tokens_out += u.get("completion_tokens", 0)
                self.reasoning += u.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
                self.calls += 1
                content = d["choices"][0]["message"].get("content") or ""
                if content.strip():
                    action = json.loads(LLMAgent._extract_json(content))
                    if isinstance(action, dict):
                        return action
            except Exception:  # noqa: BLE001
                if attempt == 2:
                    traceback.print_exc()
                time.sleep(1)
        return {}


def _cards_in(seat: int, hands) -> str:
    return ", ".join(str(c) for c in sorted(hands[seat], key=lambda c: c.rank_index))


def _channel_block(ch: Channels, agent: GCAgent, what: str) -> tuple[str, int]:
    """Build the transcript text for a channel and its listening cost."""
    if what == "public":
        if not ch.public:
            return "(no one has spoken yet)", 0
        cost = public_cost(len(ch.public))
        lines = [f"  {msg.turn}. {msg.name} (seat {msg.seat}): \"{msg.text}\""
                 for msg in ch.public]
        return "\n".join(lines), cost
    # signals
    mine = [e for e in ch.signals if e.to_seat == agent.seat]
    if not mine:
        return "(no signals addressed to you)", 0
    cost = signals_cost(len(mine))
    lines = [f"  {e.turn}. from {e.from_seat} -> you: \"{e.text}\"" for e in mine]
    return "\n".join(lines), cost


def _access_block(view: Channels, agent: GCAgent) -> str | None:
    """What this agent can observe about others accessing its API / the channels."""
    evs = [e for e in view.accesses if e.reader != agent.seat]
    if not evs:
        return None
    lines = []
    for e in evs:
        if e.channel == "signals" and e.sender == agent.seat:
            lines.append(f"  seat {e.reader} accessed/read your signal.")
        elif e.channel == "signals":
            lines.append(f"  seat {e.reader} accessed the signals API (read a signal from seat {e.sender}).")
        else:
            lines.append(f"  seat {e.reader} is listening to the public group chat.")
    return "\n".join(lines)


def build_gc_prompt(agent: GCAgent, hands, view: Channels, phase, legal: list[str],
                    public_text: str, extra: str | None = None,
                    record: Channels | None = None) -> str:
    """Build a prompt from a frozen ``view``. When the agent pays to listen it also
    records an access event into ``record`` (the live channels) so others can see
    that this agent touched their API."""
    rec = record if record is not None else view
    lines = [
        f"You are {agent.name}, playing mus in TEAM {agent.team}, seat {agent.seat}.",
        f"Phase: {phase}. It is your turn.",
        f"YOUR HAND: {_cards_in(agent.seat, hands)}",
        "",
    ]
    listen = agent.listen
    for what, label in (("public", "PUBLIC GROUP CHAT"), ("signals", "SIGNALS API")):
        take = (listen == "both") or (listen == what)
        text, cost = _channel_block(view, agent, what) if take else ("", 0)
        header = f"[{label} — cost {cost} tokens to listen; budget {agent.budget.remaining}]"
        if take:
            if agent.budget.can_afford(cost):
                agent.budget.spend(cost)
                lines.append(header)
                lines.append(text)
                if what == "public":
                    rec.add_access(agent.seat, "public", None)
                else:
                    for ev in [e for e in view.signals if e.to_seat == agent.seat]:
                        rec.add_access(agent.seat, "signals", ev.from_seat)
            else:
                lines.append(f"[{label} — budget {agent.budget.remaining} too low; channel unavailable]")
        else:
            lines.append(f"[{label} — not listening this turn]")
        lines.append("")
    ab = _access_block(view, agent)
    if ab:
        lines.append("[ACCESSES you can observe]")
        lines.append(ab)
        lines.append("")
    lines.append(f"Public/table: {public_text}")
    if extra:
        lines.append(extra)
    lines.append("You MUST answer with ONLY a JSON object. Legal action names: "
                 + ", ".join(legal) + ".")
    lines.append('Format: {"action": "<name>", "listen": "<public|signals|both|none>", '
                 '"message": "<public group-chat text, max 20 words>", '
                 '"signal": {"to": <seat>, "text": "<private text, max 10 words>"}, '
                 '"cards": [card names]}')
    lines.append('"listen" chooses which channel to consume NEXT turn (default "both").')
    lines.append("Rules of this phase:")
    if "ORDAGO" in phase:
        lines.append("  - ordago: bet the whole hand; winner takes all 4 vacas.")
    elif "MUS_REQUEST" in phase:
        lines.append('  - mus: want new cards later. no: keep hand.')
    elif "MUS_DRAW" in phase:
        lines.append('  - action must be "discard" with "cards": list of card names '
                     'exactly as in YOUR HAND, count 1..4.')
    return "\n".join(lines)


def _emit_turn(agent: GCAgent, action: dict, ch: Channels) -> None:
    msg = action.get("message")
    if msg and isinstance(msg, str) and msg.strip():
        ch.say_public(agent.seat, agent.name, msg.strip()[:120])
    sig = action.get("signal")
    if isinstance(sig, dict):
        to = sig.get("to")
        txt = sig.get("text")
        if type(to) is int and 0 <= to <= 3 and isinstance(txt, str) and txt.strip():
            ch.send_signal(agent.seat, to, txt.strip()[:80])
    new_listen = action.get("listen")
    new_listen = new_listen.lower() if isinstance(new_listen, str) else agent.listen
    if new_listen in ("public", "signals", "both", "none"):
        agent.listen = new_listen


def _prompt_for(agent, hands, ch, phase, legal, public_text, extra=None):
    return build_gc_prompt(agent, hands, ch, phase, legal, public_text, extra)


def _snapshot(ch: Channels) -> Channels:
    """A frozen copy of both channels, so simultaneous agents see the same state."""
    snap = Channels()
    snap.public = list(ch.public)
    snap.signals = list(ch.signals)
    snap.accesses = list(ch.accesses)
    return snap


def run_hand_gc(engine: MusEngine, agents: list[GCAgent], ch: Channels, hand: int, rng: Random,
                 verbose: bool = False):
    for a in agents:
        a.budget.reset()
        a.listen = "both"
    ch.clear()
    hands = engine.deal()

    # ---- MUS_REQUEST: all seats reason CONCURRENTLY over a frozen snapshot.
    # In a real-time group chat you see the transcript as it was when you
    # started reasoning, not what others are typing right now.
    snap = _snapshot(ch)
    mus_want = set()
    prompts = []
    for seat in range(4):
        ag = agents[seat]
        legal = ["ordago", "mus", "no"] if seat == 0 else ["mus", "no"]
        pub = "Nothing yet." if seat == 0 else "All seats are deciding simultaneously."
        prompts.append((seat, build_gc_prompt(ag, hands, snap, "MUS_REQUEST", legal, pub, record=ch)))
    with ThreadPoolExecutor(max_workers=4) as ex:
        actions = list(ex.map(lambda p: agents[p[0]].decide(p[1]), prompts))
    for (seat, _), action in zip(prompts, actions):
        ag = agents[seat]
        _emit_turn(ag, action, ch)
        if verbose:
            _print_turn(ag, action, ch)
        if seat == 0 and action.get("action") == "ordago":
            vacas_a, vacas_b, det = _resolve_ordago(engine, ag, hands)
            return vacas_a, vacas_b, det
        if action.get("action") == "mus":
            mus_want.add(seat)

    # ---- MUS_DRAW: only the mus players, concurrently, over a fresh snapshot.
    if mus_want:
        snap = _snapshot(ch)
        draw_prompts = []
        for seat in sorted(mus_want):
            ag = agents[seat]
            extra = f"You may discard 1-4 cards and redraw. Your hand: {_cards_in(seat, hands)}"
            draw_prompts.append((seat, build_gc_prompt(ag, hands, snap, "MUS_DRAW",
                                                       ["discard"], "You may discard cards.", extra, record=ch)))
        with ThreadPoolExecutor(max_workers=len(draw_prompts)) as ex:
            draw_actions = list(ex.map(lambda p: agents[p[0]].decide(p[1]), draw_prompts))
        for (seat, _), action in zip(draw_prompts, draw_actions):
            ag = agents[seat]
            _emit_turn(ag, action, ch)
            if verbose:
                _print_turn(ag, action, ch)
            names = [str(c).strip().lower() for c in (action.get("cards") if isinstance(action.get("cards"), list) else [])]
            discard = _dedup([c for c in hands[seat] if _match_name(c, names)])
            if not (1 <= len(discard) <= 4):
                discard = _pick_default_discard(hands[seat], rng)
            engine.redraw(seat, hands, discard)

    # ---- JUGADAS ----
    jugadas = engine.compare_jugadas(hands)
    vacas_a, vacas_b = engine.vacas_from_jugadas(jugadas)
    det = "; ".join(f"{j.name}:{'A' if j.winner_team == 0 else 'B' if j.winner_team == 1 else '-'}"
                    for j in jugadas)
    return vacas_a, vacas_b, det


def _print_turn(agent: GCAgent, action: dict, ch: Channels) -> None:
    msg = action.get("message")
    if msg:
        print(f"  [{agent.name}/seat{agent.seat}] PUB: {msg}")
    sig = action.get("signal")
    if isinstance(sig, dict) and sig.get("text"):
        print(f"  [{agent.name}/seat{agent.seat}] SIG -> seat {sig.get('to')}: {sig.get('text')}")
    print(f"  ({agent.name} listen={agent.listen} budget={agent.budget.remaining})")


def run_match_gc(engine: MusEngine, models: list[str], hands: int = 12, seed: int = 0,
                 verbose: bool = False):
    if hands <= 0:
        raise ValueError("hands must be positive")
    if len(models) != 4 or any(not model.strip() for model in models):
        raise ValueError("exactly four nonempty models are required")
    rng = Random(seed)
    engine.rng = Random(seed)
    agents = [
        GCAgent("A1", models[0], seat=0, team=0),
        GCAgent("B1", models[1], seat=1, team=1),
        GCAgent("A2", models[2], seat=2, team=0),
        GCAgent("B2", models[3], seat=3, team=1),
    ]
    ch = Channels()
    va = vb = hwa = hwb = 0
    for h in range(hands):
        a, b, det = run_hand_gc(engine, agents, ch, h, rng, verbose=verbose)
        va += a; vb += b
        if a > b: hwa += 1
        elif b > a: hwb += 1
    usage = {
        "tokens_in": sum(a.tokens_in for a in agents),
        "tokens_out": sum(a.tokens_out for a in agents),
        "reasoning": sum(a.reasoning for a in agents),
        "calls": sum(a.calls for a in agents),
    }
    return {
        "vacas_a": va, "vacas_b": vb, "hand_wins_a": hwa, "hand_wins_b": hwb,
        "hands": hands, "models": models, "usage": usage,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="deepseek-v4-flash,qwen3.8-flash,glm5.3-flash,gemma4")
    ap.add_argument("--hands", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    models = [m.strip() for m in args.models.split(",")]
    if len(models) != 4 or any(not model for model in models):
        ap.error("--models requires exactly four nonempty model names")
    print(f"Match: {' vs '.join(models)}  (teams: {models[0]}+{models[2]} | {models[1]}+{models[3]})")
    print(f"hands={args.hands} seed={args.seed}\n")
    t0 = time.time()
    res = run_match_gc(MusEngine(), models, hands=args.hands, seed=args.seed, verbose=args.verbose)
    res["elapsed"] = round(time.time() - t0, 1)
    print(f"\nResult: vacas {res['vacas_a']}-{res['vacas_b']}  hands={res['hands']}")
    print(f"Token usage: in={res['usage']['tokens_in']} out={res['usage']['tokens_out']} "
          f"(reasoning={res['usage']['reasoning']}) calls={res['usage']['calls']} "
          f"elapsed={res['elapsed']}s")
    if args.out:
        with open(args.out, "w") as f:
            json.dump(res, f, indent=2)
        print(f"Saved -> {args.out}")


if __name__ == "__main__":
    main()
