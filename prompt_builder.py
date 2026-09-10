"""Prompt construction for LLM seats: channel blocks and phase rules.

Functions here turn engine state + channel state into the model prompt. They
are pure and side-effect only on the supplied agent's perception budget
(when a channel is read, the cost is charged and the read count advances).
"""
from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from mus_engine import Phase, TEAM_OF, LANCE_NAMES
from groupchat import Channels, public_cost, signals_cost
from agents import THINK_BUDGET
import senas
from senas import SENAS

# Experimental arm switch: with 0 the schema hides the "bluff" field entirely
# (the mechanics still accept a false one-shot gesture), so a lie can only be
# UNPROMPTED. With 1 the affordance is stated in the prompt.
BLUFF_AFFORDANCE = os.environ.get("KERNEL_BLUFF_AFFORDANCE", "1") != "0"

if TYPE_CHECKING:
    from agents import StrictAgent
    from mus_engine import MusEngine


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


def _delivered_block(delivered: list) -> str:
    """Kernel mode: your partner's senas are visual at the table -- you do
    NOT pay attention credits to see them; you either caught them in time or
    they were gone. The line shows WHEN each was made relative to windows."""
    if not delivered:
        return ("(you caught no partner sena before this decision -- either "
                "none was made or it faded before you looked)", 0)
    lines = [f"  seat {ev.from_seat} sena: {ev.gesture} (= {SENAS[ev.gesture][0]})"
             for ev in delivered]
    return "\n".join(lines), 0


def build_prompt(agent: StrictAgent, engine: MusEngine, ch: Channels,
                 legal: list[str], error: str | None = None,
                 delivered: list | None = None) -> str:
    kernel_mode = delivered is not None
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
    if kernel_mode:
        text, cost = _delivered_block(delivered)
        lines.append("[SEÑAS AT THE TABLE — your partner's gestures that you "
                     "caught before this decision (visual: free to see, but they "
                     "fade -- a sena made too late informs your NEXT decision).]")
    else:
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
                     'NOTE: tres counts as rey (same card for pares and '
                     'comparisons); as and dos are DIFFERENT ranks, so as+dos '
                     'is not a pair. Pares need two equal cards (rey=tres).')
    elif engine.phase == Phase.ORDAGO_RESPONSE:
        lines.append('  - "quiero": accept -> whole game decided by the hand '
                     'comparison. "no-quiero": decline -> the caller takes the '
                     'previous stake plus the jugada value, and play continues.')
    if kernel_mode:
        lines.append("SENAS (reglamentarias): fixed gestures with fixed meanings, "
                     "addressed to YOUR PARTNER only, made at the table during "
                     "ANYONE's deliberation -- including your partner's (that is "
                     "the point of a sena). Opponents do not see them.")
    else:
        lines.append("SENAS (reglamentarias): gestures are made AT THE TABLE and "
                     "are always PUBLIC -- there is no private signalling. Any seat "
                     "(including opponents) can catch a seña by attending to the "
                     "señas API. Fixed gestures with fixed meanings only:")
    lines.append(senas.vocabulary_for_prompt())
    if kernel_mode:
        lines.append("Most hands have NO seña available: then gesture nothing. "
                     "A gesture is only worth making if it can still reach your "
                     "partner in time to change a decision.")
        lines.append("SIGNAL POLICY: declare WHEN you gesture with "
                     "\"signal_policy\" -- declarative rules the table interprets "
                     "(no code). Each rule fires ONLY if its gesture is true of "
                     "your hand at that moment. Null/omitted keeps your current "
                     "policy. Schema:")
        if BLUFF_AFFORDANCE:
            lines.append('  {"rules": [{"gesture": "<one sena>", '
                         '"when_phase": "MUS_REQUEST|MUS_DRAW|DECLARE|ENVITE|ORDAGO_RESPONSE|*", '
                         '"when_lance": "Grande|Chica|Pares|Juego|*", '
                         '"when_deciding": "partner|any", '
                         '"offset": <0..0.95>, "ttl": <0..20>, "bluff": false}], '
                         '"enabled": true}')
            lines.append("  offset = where inside the deciding seat's deliberation "
                         "window you make the gesture; ttl = lifetime in decision-"
                         "window units (a full table rotation is ~4, so a gesture "
                         "meant for your partner's NEXT decision needs ttl > ~4). "
                         "Rules fire only while TRUE of your hand, unless "
                         "\"bluff\": true and this table allows sena bluffs. A "
                         "gesture your partner already caught is not repeated.")
        else:
            lines.append('  {"rules": [{"gesture": "<one sena>", '
                         '"when_phase": "MUS_REQUEST|MUS_DRAW|DECLARE|ENVITE|ORDAGO_RESPONSE|*", '
                         '"when_lance": "Grande|Chica|Pares|Juego|*", '
                         '"when_deciding": "partner|any", '
                         '"offset": <0..0.95>, "ttl": <0..20>}], '
                         '"enabled": true}')
            lines.append("  offset = where inside the deciding seat's deliberation "
                         "window you make the gesture; ttl = lifetime in decision-"
                         "window units (a full table rotation is ~4, so a gesture "
                         "meant for your partner's NEXT decision needs ttl > ~4). "
                         "Rules fire only while their gesture is true of your "
                         "hand. A gesture your partner already caught is not "
                         "repeated.")
    else:
        lines.append("Most hands have NO seña available: then omit 'signal' "
                     "entirely. Gesture only what is worth the leak -- your "
                     "opponents will see it if they pay attention.")
    lines.append(f"THINK BUDGET: keep this whole turn under {THINK_BUDGET} tokens "
                 f"-- reason briefly, then output ONLY the JSON below. Do not "
                 f"restate the rules, the hand, or your reasoning.")
    lines.append("Answer with ONLY a JSON object:")
    if kernel_mode:
        lines.append('{"action": "<name>", '
                     '"thought": "<private reasoning, ONE short paragraph, <100 words>", '
                     '"message": "<table talk, max 20 words, NO card names>", '
                     '"signal": "<one sena to make right now, or null>", '
                     '"signal_policy": <null or policy object>, '
                     '"cards": [card names]}')
    else:
        lines.append('{"action": "<name>", "read_signals": <true|false>, '
                     '"thought": "<private reasoning, ONE short paragraph, <100 words>", '
                     '"message": "<table talk, max 20 words, NO card names>", '
                     '"signal": "<one seña gesture from the list, or null>", '
                     '"cards": [card names]}')
    lines.append('INNER/OUTER SPLIT: "thought" is ONLY your private reasoning and '
                 'is never shown to other players; "message" is the only thing you '
                 'say out loud. Keep the whole turn under THINK_BUDGET tokens.')
    if not kernel_mode:
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
