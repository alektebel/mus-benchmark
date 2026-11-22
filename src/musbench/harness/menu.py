"""Menu harness: every decision is a pick from the engine's legal moves.

This is the benchmark harness (protocol v3). It asks a seat only what a real
player decides at the table, with only what that player knows:

  * their own four cards (plus engine-computed facts: punto total, pares,
    juego -- arithmetic, not judgement),
  * the score, who is mano, and the public history of this hand (who said
    mus, how many cards each seat changed, declarations, every bet),
  * the showdown of recent hands (cards are turned over at the end),
  * a NUMBERED list of the moves the engine allows right now.

The seat answers with one number. A prohibited move cannot be expressed, so
the old failure mode -- free-form JSON actions rejected 10-66% of the time and
replaced by a default -- is gone by construction. No move is ever played for
a model: an invalid answer is asked again (MENU_ASKS times in all), and if it
never answers validly the match ends as `no_answer`, unscored. The only
automatic move is the declaration (tengo / no tengo), because the engine
accepts only the truthful one; tío Perete is a menu option like any other. There is no table talk and no señas:
this track measures card play alone.

Discards are a menu too (every subset of the hand), so no seat -- LLM or Jev --
gets the heuristic's discards for free.

CLI:
  python -m musbench.harness.menu --teams glm5.3-flash qwen3.6 --hands 8 --seed 0 --out m.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import time
from random import Random

import requests

from musbench.agents.core import (_default_legal, _make_agent, REASONING_MODE,
                                  THINK_BUDGET, TEMPERATURE)
from musbench.live.apifail import FatalAPIError, LLMCallFailure, MatchTimeout
from musbench.mus.engine import (LANCE_NAMES, TEAM_OF, MusEngine, Phase,
                                 RANK_GRANDE)
from musbench.observe.decision_log import (DecisionLog, build_decision,
                                           build_hand, dealt_snapshot,
                                           truth_snapshot)

# v3-menu: the elo-1 pilot prompt. v4-menu: same information, shorter text
# (suits dropped -- they never matter in mus -- one rules block that comes
# first so the CLI can cache it, explicit card orders per lance, discards
# deduplicated by rank, compact showdowns). Pick with MENU_PROTOCOL.
PROTOCOL = os.environ.get("MENU_PROTOCOL", "v3-menu")
if PROTOCOL not in ("v3-menu", "v4-menu"):
    raise SystemExit(f"unknown MENU_PROTOCOL {PROTOCOL!r}")
V4 = PROTOCOL == "v4-menu"
MATCH_TIMEOUT = float(os.environ.get("MATCH_TIMEOUT", "5400"))
MAX_TURNS_PER_HAND = 400
# A seat that cannot produce a valid number this often is not being measured.
MAX_INVALID_RATE = float(os.environ.get("MAX_INVALID_RATE", "0.05"))
INVALID_MIN_TURNS = 20
HISTORY_HANDS = int(os.environ.get("MENU_HISTORY_HANDS", "3"))

RULES = """\
RULES OF THIS TABLE (Spanish 40-card deck, 2 vs 2, partners sit opposite):
- Each hand is played in four lances, in order: Grande (high cards win),
  Chica (low cards win), Pares (pairs), Juego (31-40 points; if nobody has
  juego, Punto: highest total up to 30). Compare best card first, then second...
  A team plays the BETTER of its two hands. Ties go to the seat nearest the mano.
- Ranks: tres counts as rey; as and dos are different (as+dos is not a pair).
  Points: figures and tres = 10, as/dos = 1, others face value.
- Pares: par < medias (three of a kind) < duples (two pairs / four of a kind).
- Juego order: 31 > 32 > 40 > 39 > 38 > 37 > 36 > 35 > 34 > 33.
- Only seats that HAVE pares (or juego) take part in that lance's betting.
- Betting: envido = 2, y-yo = +2, reenvido = double, órdago = the whole vaca.
  quiero accepts (settled when cards are shown at the end of the hand);
  no-quiero folds you; if both rivals fold, the bettor's team takes the
  previous stake (1 if none) plus the lance.
- An accepted órdago in a lance is decided by that lance alone. The mano may
  also call órdago before the draw: then the team that wins more of the four
  lances takes the vaca (Grande breaks a 2-2 tie).
- Before the lances: if every seat says mus, everyone changes cards; one
  "no hay mus" ends the changing. A vaca is 40 piedras; both scores then reset.
"""


RULES_V4 = """\
MUS RULES (40-card Spanish deck; suits never matter; 2 vs 2, partners sit opposite)
- Four lances in order: Grande (high cards), Chica (low cards), Pares, Juego
  (31-40 points; if nobody has juego: Punto, highest total up to 30).
  Compare best card first, then the next. A team plays the better of its two
  hands. Ties go to the seat nearest the mano.
- tres counts as rey and as/dos stay different, in every lance.
  Grande, best to worst: rey=tres, caballo, sota, siete, seis, cinco, cuatro, dos, as.
  Chica, best to worst: as, dos, cuatro, cinco, seis, siete, sota, caballo, rey=tres.
- Points: rey, tres, caballo, sota = 10; as, dos = 1; others face value.
- Pares: par < medias (three alike) < duples (two pairs or four alike);
  within a kind, higher cards win.
- Juego: 31 > 32 > 40 > 39 > 38 > 37 > 36 > 35 > 34 > 33.
- Only seats that HAVE pares (or juego) bet in that lance.
- Bets: envido 2, y-yo +2, reenvido doubles, órdago = the whole vaca.
  quiero accepts (paid when cards are shown at the end of the hand);
  no-quiero folds. If both rivals fold, the bettor's team takes the previous
  stake (1 if none) and the lance.
- An accepted órdago in a lance is decided by that lance alone. Before the
  draw the mano may call órdago: the team that wins more of the four lances
  takes the vaca (Grande breaks a 2-2 tie).
- Mus: if all four say mus, everyone changes cards; one "no hay mus" stops
  it. A vaca is 40 piedras; both scores then reset.
"""


class ProviderError(Exception):
    """The seat's API/CLI failed after its own retries; replay the match."""


class NoAnswer(Exception):
    """The model answered, but never with a valid option; the match ends
    unscored rather than letting a rule play the move for it."""


ASKS = int(os.environ.get("MENU_ASKS", "3"))   # first ask + re-asks


# ------------------------------------------------------------ helpers ----
def _rel(seat: int, other: int) -> str:
    if other == seat:
        return "you"
    if TEAM_OF[other] == TEAM_OF[seat]:
        return f"your partner (seat {other})"
    return f"rival seat {other}"


def _cards(cards) -> str:
    srt = sorted(cards, key=lambda c: -RANK_GRANDE.get(c.rank, 0))
    if V4:                                   # suits never matter in mus
        return ", ".join(c.rank for c in srt)
    return ", ".join(str(c) for c in srt)


class PublicLog:
    """Everything the whole table saw, in order. Seats get it verbatim."""

    def __init__(self):
        self.hand: list[tuple[int, str]] = []     # (seat, text) this hand
        self.past: list[str] = []                 # showdown summaries

    def new_hand(self):
        self.hand = []

    def add(self, seat: int, text: str):
        self.hand.append((seat, text))

    def view(self, seat: int) -> list[str]:
        return [f"- {_rel(seat, s)}: {t}" for s, t in self.hand]


def _stage(engine) -> str:
    if engine.phase in (Phase.MUS_REQUEST, Phase.MUS_DRAW):
        return "mus"
    if engine.phase == Phase.ORDAGO_RESPONSE and engine.ordago_context == "mus_request":
        return "mus"
    if engine.lance_index >= 4:
        return "end"
    if (engine.lance_index == 3 and len(engine.declared) == 4
            and not any(engine.declared.values())):
        return "Punto"                      # nobody has juego
    return LANCE_NAMES[engine.lance_index]


# ------------------------------------------------------------ the menu ----
def menu_options(engine: MusEngine, seat: int) -> list[tuple[str, dict]]:
    """(label, action) for every move the engine allows this seat now."""
    legal = engine.legal_actions(seat)
    e = engine.envite
    out: list[tuple[str, dict]] = []
    if engine.phase == Phase.MUS_DRAW:
        hand = list(engine.hands[seat])
        seen = set()
        for k in range(1, 5):
            for combo in itertools.combinations(hand, k):
                if V4:                       # same ranks = same move
                    key = tuple(sorted(c.rank for c in combo))
                    if key in seen:
                        continue
                    seen.add(key)
                keep = [c for c in hand if c not in combo]
                label = (f"change {k}: {_cards(combo)}"
                         + (f"  (keep {_cards(keep)})" if keep else "  (all four)"))
                out.append((label, {"action": "discard",
                                    "cards": [str(c) for c in combo]}))
        return out
    if engine.phase == Phase.MUS_REQUEST:      # the all-in goes last, never first
        legal = [a for a in legal if a != "ordago"] + (["ordago"] if "ordago" in legal else [])
    for a in legal:
        if engine.phase == Phase.MUS_REQUEST:
            label = {"mus": "mus -- ask to change cards",
                     "no": "no hay mus -- play these cards now",
                     "ordago": "órdago before the draw -- the whole vaca on this hand",
                     "perete": "perete -- swap your 4-5-6-7 for new cards"}[a]
        elif engine.phase == Phase.ORDAGO_RESPONSE:
            label = {"quiero": "quiero -- accept the órdago: this hand decides the vaca",
                     "no-quiero": "no-quiero -- decline the órdago"}[a]
        elif engine.phase == Phase.DECLARE:
            label = a
        else:
            cur, prev = e.current, e.previous
            label = {
                "paso": ("paso -- no bet" if cur == 0 else
                         "paso -- stop here (you drop out of this bet)"),
                "envido": "envido -- bet 2",
                "y-yo": f"y-yo -- raise to {cur + 2}",
                "reenvido": f"reenvido -- raise to {cur * 2}",
                "quiero": f"quiero -- accept the bet of {cur}",
                "no-quiero": (f"no-quiero -- fold (if your side folds, rivals "
                              f"take {prev or 1} plus the lance)"),
                "ordago": "órdago -- bet the whole vaca",
            }.get(a, a)
        out.append((label, {"action": a}))
    return out


def _situation(engine: MusEngine, seat: int) -> str:
    e = engine.envite
    if engine.phase == Phase.MUS_REQUEST:
        return "Mus round: do you want to change cards?"
    if engine.phase == Phase.MUS_DRAW:
        return "Everyone said mus. Choose which cards to change."
    if engine.phase == Phase.ORDAGO_RESPONSE:
        return (f"{_rel(seat, engine.ordago_caller).capitalize()} called ÓRDAGO "
                f"in {_stage(engine)}.")
    lance = _stage(engine)
    if e.current == 0:
        return f"Lance: {lance}. No bet yet."
    return (f"Lance: {lance}. Live bet of {e.current} by "
            f"{_rel(seat, e.holder)}.")


def build_menu_prompt(engine: MusEngine, seat: int, log: PublicLog,
                      options: list[tuple[str, dict]], hand_no: int,
                      hands: int) -> str:
    team = TEAM_OF[seat]
    hand = engine.hands[seat]
    total = engine.hand_points(hand, engine.card_points)
    pares = {0: "no pair", 1: "par", 2: "medias", 3: "duples"}[
        engine._pares_value(hand)[0]]
    juego = (f"juego {total}" if total in engine.juego_totals
             else f"no juego (punto {total})")
    mine, theirs = ((engine.points_a, engine.points_b) if team == 0
                    else (engine.points_b, engine.points_a))
    mv, tv = ((engine.vacas_a, engine.vacas_b) if team == 0
              else (engine.vacas_b, engine.vacas_a))
    if V4:
        return _build_v4(engine, seat, log, options, hand_no, hands, team,
                         hand, pares, juego, mine, theirs, mv, tv)
    lines = [
        f"You are seat {seat} in a game of mus. Your partner is seat {(seat + 2) % 4}; "
        f"seats {(seat + 1) % 4} and {(seat + 3) % 4} are your rivals. Your team is "
        f"{'A (seats 0+2)' if team == 0 else 'B (seats 1+3)'}.",
        "",
        RULES,
        f"HAND {hand_no} of {hands}. Mano (speaks first, wins ties): "
        f"{_rel(seat, engine.mano)}.",
        f"SCORE: your team {mine} piedras, rivals {theirs} (vacas {mv}-{tv}).",
        "",
        f"YOUR CARDS: {_cards(hand)}",
        f"  -> {pares}; {juego}.",
    ]
    if engine.locked_envites:
        lines.append("ACCEPTED BETS (paid at the end of the hand): " + "; ".join(
            f"{n} {s}" for n, s, _ in engine.locked_envites))
    lines += ["", "THIS HAND SO FAR:"] + (log.view(seat) or ["- (nothing yet)"])
    if log.past:
        lines += ["", "RECENT HANDS (cards shown at the end):"] + log.past[-HISTORY_HANDS:]
    lines += ["", _situation(engine, seat), "YOUR OPTIONS:"]
    lines += [f"  {i}. {label}" for i, (label, _) in enumerate(options, 1)]
    lines += ["", f'Reply with JSON only: {{"choice": <1-{len(options)}>, '
                  f'"why": "<one short sentence>"}}']
    return "\n".join(lines)


def _build_v4(engine, seat, log, options, hand_no, hands, team, hand, pares,
              juego, mine, theirs, mv, tv) -> str:
    # The rules come first and never change, so the CLI can cache them.
    lines = [RULES_V4,
             f"You are seat {seat}, team {'A (seats 0+2)' if team == 0 else 'B (seats 1+3)'}. "
             f"Partner: seat {(seat + 2) % 4}. Rivals: seats {(seat + 1) % 4} and {(seat + 3) % 4}.",
             f"Hand {hand_no} of {hands}. Mano: {_rel(seat, engine.mano)}. "
             f"Score: you {mine}, rivals {theirs} (vacas {mv}-{tv}).",
             f"Your cards: {_cards(hand)} -> {pares}; {juego}."]
    if engine.locked_envites:
        lines.append("Accepted bets (paid at the end): " + "; ".join(
            f"{n} {s}" for n, s, _ in engine.locked_envites))
    lines += ["This hand so far:"] + (log.view(seat) or ["- (nothing yet)"])
    if log.past:
        lines += ["Recent hands (all cards shown at the end):"] + log.past[-HISTORY_HANDS:]
    lines += [_situation(engine, seat), "Options:"]
    lines += [f"  {i}. {label}" for i, (label, _) in enumerate(options, 1)]
    lines += [f'Reply with JSON only: {{"choice": <1-{len(options)}>, '
              f'"why": "<one short sentence>"}}']
    return "\n".join(lines)


def _public_text(engine_before_phase, action: dict, stage: str, stake: int) -> str:
    a = action["action"]
    if a == "discard":
        return f"changed {len(action['cards'])} card(s)"
    if a == "no":
        return "no hay mus"
    if engine_before_phase == Phase.DECLARE:
        return f"{stage}: {'tengo' if a == 'tengo' else 'no tengo'}"
    if stage == "mus":
        return a
    if a == "quiero" and stake:
        return f"{stage}: quiero ({stake})"
    return f"{stage}: {a}"


# ---------------------------------------------------------- choosing ----
_NUM = re.compile(r"-?\d+")


def _parse_choice(data, n: int) -> int | None:
    """1-based choice from the seat's reply, or None if it is not valid."""
    v = data.get("choice") if isinstance(data, dict) else data
    if isinstance(v, str):
        m = _NUM.search(v)
        v = int(m.group()) if m else None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = int(v)
    return v if 1 <= v <= n else None


def _jev_choose(agent, prompt: str, labels: list[str]) -> int | None:
    """Jev (TypeSafe System One) answers a typed `choice` over the labels."""
    from musbench.agents import jev_seat
    keys = [f"o{i}" for i in range(1, len(labels) + 1)]
    body = {"model": agent.model,
            "state": {"game": "mus", "prompt": prompt[:6000]},
            "questions": {"action": {
                "type": "choice",
                "instructions": "You are playing Spanish mus. Pick the single "
                                "best option for this seat.",
                "criteria": dict(zip(keys, labels))}}}
    data, last = None, None
    for attempt in range(4):
        if attempt:
            time.sleep(5 * attempt)              # ride out DNS / network blips
        try:
            r = requests.post(f"{jev_seat.ENDPOINT}/systemone",
                              headers={"Authorization": f"Bearer {agent.api_key}",
                                       "Content-Type": "application/json"},
                              json=body, timeout=jev_seat.TIMEOUT)
            r.raise_for_status()
            data = r.json()
            break
        except (requests.RequestException, ValueError) as e:
            last = e
    if data is None:
        raise LLMCallFailure(f"jev: {last}") from last
    u = data.get("usage") or {}
    agent.tokens_in += int(u.get("input_tokens") or 0)
    agent.tokens_out += int(u.get("output_tokens") or 0)
    agent.calls += 1
    ans = (data.get("answers") or {}).get("action") or {}
    agent.last_io = {"prompt": prompt, "raw": json.dumps(ans)[:2000]}
    choice = ans.get("choice")
    return keys.index(choice) + 1 if choice in keys else None


def choose(agent, prompt: str, options: list) -> tuple[int | None, str]:
    """Ask the seat; one re-ask on an invalid number. Returns (choice, why)."""
    n = len(options)
    is_jev = getattr(agent, "provider", "") == "typesafe"
    ask = prompt
    raw = ""
    for attempt in range(ASKS):
        if is_jev:
            c = _jev_choose(agent, ask, [label for label, _ in options])
            raw = (getattr(agent, "last_io", None) or {}).get("raw", "")
        else:
            data = agent.decide(ask)      # JSON object; retries live inside
            why = data.get("why") if isinstance(data, dict) else None
            raw = str(why)[:400] if why else ""
            c = _parse_choice(data, n)
        if c is not None:
            return c, raw
        ask = prompt + f"\n\nThat was not a valid option. Reply with JSON only: " \
                       f'{{"choice": <a number from 1 to {n}>, "why": "..."}}'
    return None, raw


# ------------------------------------------------------------- match ----
def _auto(engine: MusEngine, seat: int) -> dict | None:
    """The one move nobody decides: the declaration (tengo / no tengo). The
    engine accepts only the truthful one, so there is no choice to make.
    Everything else, tío Perete included, is the seat's own decision."""
    if engine.phase == Phase.DECLARE:
        return _default_legal(engine, seat)
    return None


def run_menu_match(models: list, hands: int = 8, seed: int = 0,
                   verbose: bool = False, decision_log: DecisionLog | None = None,
                   hand_callback=None) -> dict:
    if len(models) != 4:
        raise ValueError("exactly four model specs are required")
    t0 = time.monotonic()
    deadline = t0 + MATCH_TIMEOUT
    engine = MusEngine(rng=Random(seed))
    agents = [_make_agent(m, s, TEAM_OF[s], seed) for s, m in enumerate(models)]
    for a in agents:
        a.invalid = 0
        a.decisions = 0
        a.latency = 0.0
        if a.is_llm:
            a.deadline = deadline
    log = PublicLog()
    stats = {"turns": 0, "llm_turns": 0, "fallbacks": 0, "invalid": 0}
    piedras_a = piedras_b = hwa = hwb = 0
    status, abort_reason, done = "done", None, 0
    va0 = vb0 = 0
    hand_rows = []
    try:
        for h in range(1, hands + 1):
            engine.deal()
            dealt = dealt_snapshot(engine)
            log.new_hand()
            va0, vb0 = engine.vacas_a, engine.vacas_b
            turns = 0
            while engine.phase != Phase.DONE:
                if time.monotonic() > deadline:
                    raise MatchTimeout(f"match deadline exceeded at hand {h}")
                turns += 1
                if turns > MAX_TURNS_PER_HAND:
                    raise RuntimeError("turn limit exceeded (engine deadlock guard)")
                seat = engine.current_seat
                agent = agents[seat]
                phase, stage, stake = engine.phase, _stage(engine), engine.envite.current
                legal = engine.legal_actions(seat)
                truth = truth_snapshot(engine, seat)
                stats["turns"] += 1
                fallback = False
                n_options = 0
                action = _auto(engine, seat)
                auto = action is not None
                if action is None and not agent.is_llm:
                    action = agent.policy.act(engine, seat, legal)
                if action is None:
                    options = menu_options(engine, seat)
                    n_options = len(options)
                    if len(options) == 1:
                        auto = True
                        action = options[0][1]
                    else:
                        stats["llm_turns"] += 1
                        agent.decisions += 1
                        prompt = build_menu_prompt(engine, seat, log, options, h, hands)
                        t1 = time.monotonic()
                        try:
                            c, why = choose(agent, prompt, options)
                        except LLMCallFailure as e:
                            # The provider failed (quota, outage), not the
                            # model: never score a fallback move as its play.
                            agent.api_errors += 1
                            raise ProviderError(str(e)) from e
                        agent.latency += time.monotonic() - t1
                        agent.last_why = why if c is not None else None
                        if c is None:
                            # Never play a move for the model: no valid answer
                            # after every re-ask ends the match (not scored).
                            agent.invalid += 1
                            stats["invalid"] += 1
                            raise NoAnswer(f"{agent.name}/{agent.model}: no valid choice "
                                           f"after {ASKS} asks ({engine.phase.name})")
                        action = options[c - 1][1]
                before = [str(c) for c in engine.hands[seat]]
                ga, gb = engine.points_a, engine.points_b
                engine.apply(seat, action)      # menu actions are legal by construction
                public = _public_text(phase, action, stage, stake)
                log.add(seat, public)
                if decision_log is not None:
                    rec = build_decision(
                        agent, truth, hand=h, turn=stats["turns"], t=time.monotonic() - t0,
                        legal=legal, action=action, fallback=fallback)
                    rec["auto"] = auto            # declaration / perete / forced
                    rec["thought"] = None if auto else getattr(agent, "last_why", None)
                    if agent.is_llm and not auto:
                        rec["options"] = [label for label, _ in options]
                    rec["menu_size"] = n_options
                    # replay fields: what the table saw, cards drawn, score move
                    rec["public"] = public
                    rec["stage"] = stage
                    rec["wall"] = time.time()
                    after = [str(c) for c in engine.hands.get(seat, [])]
                    if action.get("action") in ("discard", "perete"):
                        rec["drew"] = [c for c in after if c not in before]
                    rec["points_after"] = [engine.points_a, engine.points_b]
                    rec["points_delta"] = [engine.points_a - ga, engine.points_b - gb]
                    decision_log.write(rec)
                if verbose:
                    print(f"  h{h} seat{seat} {agent.model:>18}: {action}")
            piedras_a += engine.hand_gain_a
            piedras_b += engine.hand_gain_b
            hwa += engine.hand_winner == 0
            hwb += engine.hand_winner == 1
            shown = "; ".join(f"seat {s}: {_cards(engine.hands[s])}" for s in range(4))
            won = ", ".join(f"{j.name}->{'A(0+2)' if j.winner_team == 0 else 'B(1+3)' if j.winner_team == 1 else '-'}"
                            for j in engine.jugadas)
            if V4:
                shown = " | ".join(f"s{s} {' '.join(c.rank for c in sorted(engine.hands[s], key=lambda c: -RANK_GRANDE.get(c.rank, 0)))}"
                                   for s in range(4))
                won = ", ".join(f"{j.name} {'A' if j.winner_team == 0 else 'B' if j.winner_team == 1 else '-'}"
                                for j in engine.jugadas)
                log.past.append(f"- h{h}: {shown}. Won: {won}. "
                                f"+{engine.hand_gain_a} A / +{engine.hand_gain_b} B.")
            else:
                log.past.append(f"- hand {h}: {shown}. Lances: {won}. "
                                f"Piedras +{engine.hand_gain_a} seats 0+2 / "
                                f"+{engine.hand_gain_b} seats 1+3.")
            hand_rows.append({"hand": h, "gain_a": engine.hand_gain_a,
                              "gain_b": engine.hand_gain_b,
                              "winner": engine.hand_winner})
            if decision_log is not None:
                decision_log.write(build_hand(
                    engine, hand=h, t=time.monotonic() - t0,
                    va_delta=engine.vacas_a - va0, vb_delta=engine.vacas_b - vb0,
                    dealt=dealt))
            done = h
            if verbose:
                print(f"hand {h}: piedras {piedras_a}-{piedras_b} "
                      f"vacas {engine.vacas_a}-{engine.vacas_b}")
            if hand_callback:
                hand_callback(h, piedras_a, piedras_b)
    except MatchTimeout as e:
        status, abort_reason = "timeout", str(e)
    except ProviderError as e:
        status, abort_reason = "provider_error", str(e)[:500]
    except NoAnswer as e:
        status, abort_reason = "no_answer", str(e)[:500]
    except (RuntimeError, FatalAPIError) as e:
        status, abort_reason = "degraded", str(e)

    llm = [a for a in agents if a.is_llm]
    return {
        "protocol": PROTOCOL, "status": status, "abort_reason": abort_reason,
        "models": list(models), "seed": seed,
        "hands": hands, "hands_completed": done,
        "piedras_a": piedras_a, "piedras_b": piedras_b,
        "vacas_a": engine.vacas_a, "vacas_b": engine.vacas_b,
        "hand_wins_a": hwa, "hand_wins_b": hwb, "hand_rows": hand_rows,
        "settings": {"reasoning": REASONING_MODE, "think_budget": THINK_BUDGET,
                     "temperature": TEMPERATURE, "history_hands": HISTORY_HANDS},
        "usage": {"calls": sum(a.calls for a in agents),
                  "tokens_in": sum(a.tokens_in for a in agents),
                  "tokens_out": sum(a.tokens_out for a in agents),
                  "fallbacks": stats["fallbacks"], "invalid": stats["invalid"],
                  "turns": stats["turns"], "llm_turns": stats["llm_turns"]},
        "signals": {},
        "agents": [{"name": a.name, "model": a.model, "seat": a.seat,
                    "is_llm": a.is_llm, "calls": a.calls,
                    "decisions": a.decisions, "invalid": a.invalid,
                    "fallbacks": a.fallbacks, "api_errors": a.api_errors,
                    "rejections": 0, "tokens_in": a.tokens_in,
                    "tokens_out": a.tokens_out,
                    "latency_s": round(a.latency, 1),
                    "cost_usd": round(getattr(a, "cost_usd", 0.0), 4)} for a in agents],
        "elapsed": round(time.monotonic() - t0, 1),
        "llm_seats": len(llm),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--teams", nargs=2, metavar=("TEAM_A", "TEAM_B"))
    ap.add_argument("--models", help="4 comma-separated specs (seat 0..3)")
    ap.add_argument("--hands", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    if bool(args.teams) == bool(args.models):
        ap.error("give exactly one of --teams or --models")
    models = ([args.teams[0], args.teams[1], args.teams[0], args.teams[1]]
              if args.teams else [m.strip() for m in args.models.split(",")])
    dec_path = re.sub(r"\.json$", "", args.out) + ".jsonl" if args.out else None
    if dec_path and os.path.exists(dec_path):
        os.remove(dec_path)                # a re-run must not append to an old log
    with DecisionLog(dec_path) as dlog:
        def save(res):
            if args.out:
                tmp = args.out + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(res, f, indent=2, ensure_ascii=False)
                os.replace(tmp, args.out)
        res = run_menu_match(models, hands=args.hands, seed=args.seed,
                             verbose=args.verbose, decision_log=dlog,
                             hand_callback=lambda h, a, b: save(
                                 {"status": "running", "hands_completed": h,
                                  "piedras_a": a, "piedras_b": b,
                                  "models": models, "seed": args.seed}))
    save(res)
    print(f"{res['status']}: piedras {res['piedras_a']}-{res['piedras_b']} "
          f"vacas {res['vacas_a']}-{res['vacas_b']} hands {res['hands_completed']}/"
          f"{res['hands']} calls {res['usage']['calls']} invalid "
          f"{res['usage']['invalid']}/{res['usage']['llm_turns']} "
          f"elapsed {res['elapsed']}s")
    if res["abort_reason"]:
        print("ABORT:", res["abort_reason"])


if __name__ == "__main__":
    main()
