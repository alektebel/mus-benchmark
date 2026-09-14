"""Per-decision ground-truth record for mus_bench.

The engine knows every seat's cards, so at any point from DECLARE onward it can
answer the question a mus player can only guess at: *who actually wins this
lance?*  `MusEngine._lance_winner` is a pure function of the four hands and is
constant for the whole lance once the draw is over, which makes it the truth
oracle for every derived metric -- was that envite a bluff, did that fold
surrender a winning lance, was that call a pay-off.

One JSONL record per decision, flushed as it is written, so a killed run keeps
every hand it finished.  Nothing here touches gameplay: the writer is a sink.

Record kinds:
  "decision"  -- one accepted action (or fallback) by one seat
  "hand"      -- close-out for a hand: deals, truth, piedras, locked envites
"""
from __future__ import annotations

import json
import os

from mus_engine import LANCE_NAMES, Phase, TEAM_OF

# Phases where the draw is over, so the four hands are final and lance truth is
# well defined.  A pre-draw ordago is still logged, just without truth fields.
_CARDS_FINAL = (Phase.DECLARE, Phase.ENVITE, Phase.ORDAGO_RESPONSE)

AGGRESSIVE = ("envido", "y-yo", "reenvido", "ordago")


class DecisionLog:
    """Append-only JSONL sink.  A log with no path is a no-op."""

    def __init__(self, path: str | None = None):
        self.path = path
        self.records = 0
        self._fh = None
        if path:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._fh = open(path, "a", encoding="utf8")

    @property
    def enabled(self) -> bool:
        return self._fh is not None

    def write(self, rec: dict) -> None:
        if self._fh is None:
            return
        self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._fh.flush()          # a SIGKILL must not cost us the hand
        self.records += 1

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def lance_of(engine) -> str | None:
    """The lance this decision belongs to, or None outside the lance phases."""
    if engine.phase not in _CARDS_FINAL:
        return None
    if engine.phase == Phase.ORDAGO_RESPONSE and engine.ordago_context == "mus":
        return None               # pre-draw ordago: no lance, cards not final
    if not 0 <= engine.lance_index < len(LANCE_NAMES):
        return None
    return LANCE_NAMES[engine.lance_index]


def jugada_truth(engine) -> dict[str, int | None] | None:
    """Winner of every lance under the CURRENT four hands, or None pre-draw.

    Uses the engine's own comparison so the truth here can never drift from the
    truth the engine settles on.
    """
    if engine.phase not in _CARDS_FINAL:
        return None
    if engine.phase == Phase.ORDAGO_RESPONSE and engine.ordago_context == "mus":
        return None
    return {j.name: j.winner_team for j in engine.compare_jugadas()}


def facing_bet(engine) -> bool:
    """True when this seat must answer a live bet -- where a read is worth
    asking for and where fold/call correctness is measurable."""
    if engine.phase == Phase.ORDAGO_RESPONSE:
        return True
    return engine.phase == Phase.ENVITE and engine.envite.current > 0


def _strength(engine, lance, seat):
    if lance is None:
        return None
    # imported lazily: baselines_strict imports the engine, and the kernel
    # imports this module, so a module-level import would round-trip.
    from baselines_strict import _lance_strength
    try:
        return round(_lance_strength(engine, lance, seat), 4)
    except Exception:
        return None


def build_decision(agent, truth, *, hand, turn, t, legal, action,
                   delivered=None, rejections=0, fallback=False,
                   read=None) -> dict:
    """Snapshot one decision together with everything needed to score it.

    `truth` is a `truth_snapshot()` taken BEFORE `engine.apply`, because apply
    advances the phase and clears the envite the seat was actually facing.
    """
    seat = agent.seat
    team = TEAM_OF[seat]
    rec = {
        "kind": "decision",
        "hand": hand, "turn": turn, "t": round(t, 3),
        "seat": seat, "team": team,
        "name": getattr(agent, "name", None),
        "model": getattr(agent, "model", None),
        "is_llm": bool(getattr(agent, "is_llm", False)),
        "action": action.get("action") if isinstance(action, dict) else None,
        "raw_action": action if isinstance(action, dict) else None,
        "legal": list(legal or []),
        "rejections": rejections,
        "fallback": bool(fallback),
        "read": read if isinstance(read, dict) else None,
        "senas_delivered": [
            {"from": ev.from_seat, "gesture": ev.gesture,
             "truthful": ev.truthful_at_pub} for ev in (delivered or [])],
        "thought": (action.get("thought") if isinstance(action, dict) else None),
    }
    rec.update(truth or {})
    return rec


def truth_snapshot(engine, seat) -> dict:
    """The ground-truth half of a decision record, read BEFORE `engine.apply`.

    Split out because `apply` mutates phase, lance_index and the envite state,
    so everything here has to be captured while the seat still faces it.
    """
    lance = lance_of(engine)
    jt = jugada_truth(engine)
    winner = jt.get(lance) if (jt and lance) else None
    e = engine.envite
    return {
        "phase": engine.phase.name,
        "lance": lance,
        "cards_final": engine.phase in _CARDS_FINAL,
        "hands": {str(s): [str(c) for c in engine.hands.get(s, [])]
                  for s in range(4)},
        "jugada_truth": jt,
        "lance_winner_truth": winner,
        "would_win": (None if winner is None else winner == TEAM_OF[seat]),
        "strength": _strength(engine, lance, seat),
        "facing_bet": facing_bet(engine),
        "stake": e.current, "previous": e.previous, "holder": e.holder,
        "holder_team": (None if e.holder is None else TEAM_OF[e.holder]),
        "folded": sorted(e.folded),
        "locked": e.locked,
        "ordago_context": engine.ordago_context,
        "mano": engine.mano,
        "points_a": engine.points_a, "points_b": engine.points_b,
        "vacas_a": engine.vacas_a, "vacas_b": engine.vacas_b,
    }


def dealt_snapshot(engine) -> dict[str, list[str]]:
    """The hands AS DEALT, before any mus redraw.

    Paired-deal analysis compares this, never the end-of-hand hands: those
    legitimately differ between two matches on the same seed because the
    players discarded differently.
    """
    return {str(s): [str(c) for c in engine.hands.get(s, [])] for s in range(4)}


def build_hand(engine, *, hand, t, va_delta, vb_delta, dealt=None) -> dict:
    """Close-out record: what the hand actually settled on."""
    return {
        "kind": "hand",
        "hand": hand, "t": round(t, 3),
        "mano": engine.mano,
        "dealt": dealt,
        "hands": {str(s): [str(c) for c in engine.hands.get(s, [])]
                  for s in range(4)},
        "jugadas": {j.name: j.winner_team for j in engine.jugadas},
        "jugada_truth": {j.name: j.winner_team
                         for j in engine.compare_jugadas()},
        "locked_envites": [{"lance": n, "stake": s, "holder": h}
                           for n, s, h in engine.locked_envites],
        "hand_gain_a": engine.hand_gain_a, "hand_gain_b": engine.hand_gain_b,
        "hand_winner": engine.hand_winner,
        "points_a": engine.points_a, "points_b": engine.points_b,
        "vacas_a": engine.vacas_a, "vacas_b": engine.vacas_b,
        "vaca_delta_a": va_delta, "vaca_delta_b": vb_delta,
        "ordago_caller": engine.ordago_caller,
        "ordago_accepted": engine.ordago_accepted,
    }
