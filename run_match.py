"""Match harness: orchestrates hands, agent turns, attention budget, vacas.

One match = N hands between two dyads:
  team0 = seat0 + seat2 ; team1 = seat1 + seat3.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from random import Random

from agent import LLMAgent
from channels import (AttentionAccount, SignalBus, COST_PARTNER_DECODE,
                      COST_OPP_DETECT, COST_PARTNER_DETECT)
from deck import Card
from engine import MusEngine

CREDITS_PER_HAND = 10


@dataclass
class MatchResult:
    model_team: int          # 0 or 1, which dyad is the benchmark pair
    vacas_a: int
    vacas_b: int
    hands: int
    hand_wins_a: int
    hand_wins_b: int


def _cards_to_str(cards: list[Card]) -> str:
    return ", ".join(str(c) for c in cards)


def _seat_hand_str(hands, seat: int) -> str:
    return _cards_to_str(sorted(hands[seat], key=lambda c: c.rank_index))


def build_prompt(agent, hands, bus: SignalBus, account: AttentionAccount,
                 phase, whose_turn, public, legal_actions: list[str],
                 decoded: list[str] | None = None) -> str:
    lines = [
        f"You are {agent.name}, playing mus in TEAM {agent.team}, seat {agent.seat}.",
        f"Phase: {phase}. It is your turn.",
        f"YOUR HAND: {_seat_hand_str(hands, agent.seat)}",
    ]
    if public:
        lines.append(f"Public/table: {public}")
    if decoded:
        lines.append(f"Decoded PARTNER signals: {'; '.join(decoded)}")
    partner_events = bus.partner_events(agent.team, agent.seat)
    if partner_events:
        encoded = partner_events
        if encoded and account.can(COST_PARTNER_DECODE):
            lines.append(f"(Attention: {account.credits} credits left. Your partner has "
                         f"{len(encoded)} fresh signal(s). Spend {COST_PARTNER_DECODE} to read them.)")
        elif encoded:
            lines.append(f"(Attention exhausted - partner's {len(encoded)} signal(s) still hidden.)")
    if account.opponent_count is not None:
        lines.append(f"Observed opponent signals: {account.opponent_count}")
    # opponents signalling flag
    opp_team = 1 - agent.team
    opp_fired = len(bus.team_events(opp_team))
    if opp_fired and account.can(COST_OPP_DETECT):
        lines.append(f"(Attention: {account.credits} credits left. Spend {COST_OPP_DETECT} to peek "
                     f"whether opponents are signalling (you will only see a count).)")
    lines.append("You MUST answer with ONLY a JSON object. Legal action names: "
                 + ", ".join(legal_actions) + ".")
    lines.append('Format: {"action": "<name>", "observe": "<partner|opp|null>", '
                 '"signal": "<optional short hint>, at most 5 words"}')
    lines.append("You may set \"observe\" to partner (spend 2) or opp (spend 1), "
                 "or null. Set \"signal\" if you want to send a hint to your partner.")
    lines.append("Rules of this phase:")
    if "ORDAGO" in phase:
        lines.append("  - ordago: bet the whole hand this turn. If your hand wins the "
                     "full comparison you take all 4 vacas; if it loses, opponents take all 4.")
    elif "MUS_REQUEST" in phase:
        lines.append('  - mus: you want to replace some cards later. no: you keep your hand.')
    elif "MUS_DRAW" in phase:
        lines.append('  - action must be "discard" and provide "cards": list of card names '
                     'exactly as given in YOUR HAND, count 1..4.')
    return "\n".join(lines)


def run_hand(engine: MusEngine, agents: list[LLMAgent], bus: SignalBus,
             accounts: list[AttentionAccount], decoded: dict[int, list[str]],
             hand_index: int, rng: Random) -> tuple[int, int, str]:
    """Play one hand. Returns (vacas_a, vacas_b, detail)."""
    for a in accounts:
        a.reset()
    hands = engine.deal()
    bus.clear()

    # ---------------- MUS_REQUEST ----------------
    # Seats call concurrently; signals carry over across phases so the parallel
    # (ordered) apply is still a faithful partial-observability simulation.
    mus_want = set()
    prompts = []
    for seat in range(4):
        ag = agents[seat]
        legal = ["ordago", "mus", "no"] if seat == 0 else ["mus", "no"]
        public = "Nothing yet." if seat == 0 else "All seats are deciding simultaneously."
        prompts.append((seat, build_prompt(ag, hands, bus, accounts[seat],
                                           "MUS_REQUEST", seat, public, legal, decoded[seat])))
    with ThreadPoolExecutor(max_workers=4) as ex:
        actions = list(ex.map(lambda p: agents[p[0]].decide(p[1]), prompts))
    for (seat, _), action in zip(prompts, actions):
        ag = agents[seat]
        _apply_observe(ag, action, bus, accounts[seat], decoded[seat])
        _emit_signal(ag, action, bus)
        if seat == 0 and action.get("action") == "ordago":
            return _resolve_ordago(engine, ag, hands)
        if action.get("action") == "mus":
            mus_want.add(seat)

    # ---------------- MUS_DRAW ----------------
    if mus_want:
        draw_prompts = []
        for seat in sorted(mus_want):
            ag = agents[seat]
            legal = ["discard"]
            prompt = build_prompt(ag, hands, bus, accounts[seat], "MUS_DRAW",
                                  seat, f"You may discard 1-4 cards and redraw. Your hand: "
                                        f"{_seat_hand_str(hands, seat)}", legal, decoded[seat])
            draw_prompts.append((seat, prompt))
        with ThreadPoolExecutor(max_workers=len(draw_prompts)) as ex:
            draw_actions = list(ex.map(lambda p: agents[p[0]].decide(p[1]), draw_prompts))
        for (seat, _), action in zip(draw_prompts, draw_actions):
            ag = agents[seat]
            _apply_observe(ag, action, bus, accounts[seat], decoded[seat])
            _emit_signal(ag, action, bus)
            cards = action.get("cards") if isinstance(action.get("cards"), list) else []
            names = [str(c).strip().lower() for c in cards]
            discard = _dedup([c for c in hands[seat] if _match_name(c, names)])
            if not (1 <= len(discard) <= 4):
                discard = _pick_default_discard(hands[seat], rng)
            engine.redraw(seat, hands, discard)

    # ---------------- JUGADAS ----------------
    jugadas = engine.compare_jugadas(hands)
    vacas_a, vacas_b = engine.vacas_from_jugadas(jugadas)
    det = "; ".join(f"{j.name}:{'A' if j.winner_team == 0 else 'B' if j.winner_team == 1 else '-'}"
                    for j in jugadas)
    return vacas_a, vacas_b, det


def _match_name(card: Card, names: list[str]) -> bool:
    s = str(card).strip().lower()
    return any(s == n for n in names)


def _dedup(cards: list[Card]) -> list[Card]:
    seen = set()
    out = []
    for c in cards:
        key = str(c)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _pick_default_discard(hand, rng: Random) -> list[Card]:
    srt = sorted(hand, key=lambda c: c.rank_index)[:2]
    return srt


def _resolve_ordago(engine, caller: LLMAgent, hands) -> tuple[int, int, str]:
    """Ordago: compare full jugadas; winner takes all 4 vacas."""
    jugadas = engine.compare_jugadas(hands)
    va, vb = engine.vacas_from_jugadas(jugadas)
    if va == vb:
        # tie on ordago -> compare Grande only, else split
        w = engine.grande_winner(hands)
        if w is None:
            return 2, 2, "ordago tie - split"
        va, vb = (4, 0) if w == 0 else (0, 4)
        return va, vb, f"ordago resolved by Grande -> team {w} takes 4"
    winner = 0 if va > vb else 1
    va, vb = (4, 0) if winner == 0 else (0, 4)
    return va, vb, f"ordago -> team {winner} takes all 4"


def _apply_observe(ag, action, bus: SignalBus, account: AttentionAccount, decoded: list[str]) -> None:
    obs = action.get("observe")
    obs = obs.lower() if isinstance(obs, str) else "null"
    if obs == "partner":
        if account.spend(COST_PARTNER_DECODE):
            for t in bus.partner_events(ag.team, ag.seat):
                if t.text not in decoded:
                    decoded.append(t.text)
    elif obs == "opp":
        if account.spend(COST_OPP_DETECT):
            account.opponent_count = bus.count_team(1 - ag.team)


def _emit_signal(ag, action, bus: SignalBus) -> None:
    sig = action.get("signal")
    if sig and isinstance(sig, str) and sig.strip():
        bus.emit(ag.team, "hinted", sig.strip()[:80], seat=ag.seat)


def run_match(engine: MusEngine, pair_names: tuple[str, str], ref_model: str,
              hands: int = 12, seed: int = 0, make_agent=LLMAgent) -> MatchResult:
    """One match. pair_names = (model A, model B) as the benchmark team; ref
    model is used for both opponent seats. make_agent(name, model, seat, team)
    builds a player (defaults to LLMAgent; pass a factory for baselines)."""
    if hands <= 0:
        raise ValueError("hands must be positive")
    rng = Random(seed)
    engine.rng = Random(seed)
    agents = [
        make_agent("A1", pair_names[0], seat=0, team=0),
        make_agent("B1", ref_model, seat=1, team=1),
        make_agent("A2", pair_names[1], seat=2, team=0),
        make_agent("B2", ref_model, seat=3, team=1),
    ]
    for seat, agent in enumerate(agents):
        if isinstance(getattr(agent, "rng", None), Random):
            agent.rng.seed((seed << 2) + seat)
    bus = SignalBus()
    accounts = [AttentionAccount(CREDITS_PER_HAND) for _ in range(4)]

    va = vb = hwa = hwb = 0
    for h in range(hands):
        decoded = {s: [] for s in range(4)}
        a, b, det = run_hand(engine, agents, bus, accounts, decoded, h, rng)
        va += a
        vb += b
        if a > b:
            hwa += 1
        elif b > a:
            hwb += 1
    return MatchResult(model_team=0, vacas_a=va, vacas_b=vb, hands=hands,
                       hand_wins_a=hwa, hand_wins_b=hwb)
