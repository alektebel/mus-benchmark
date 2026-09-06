"""Baseline agents for the Fournier-aligned strict engine.

Policies act directly on engine state via act(engine, seat, legal) -- no API.
  RandomPolicy    : uniform over legal actions (truthful declarations).
  HeuristicPolicy : mus-aware floor -- honest declarations, named-bet envites
                    (envido / y-yo / reenvido / quiero / no-quiero / ordago).
"""
from __future__ import annotations

from collections import Counter
from random import Random

from mus_engine import (MusEngine, Phase, TEAM_OF, JUEGO_TOTALS, JUEGO_RANK,
                        LANCE_NAMES, RANK_MUS)


def _juego_total(engine, hand):
    return engine.hand_points(hand, engine.card_points)


def _hand_quality(engine, hand) -> float:
    total = _juego_total(engine, hand)
    juego_score = JUEGO_RANK.get(total, 0) / 10.0 if total in JUEGO_TOTALS else 0.0
    pares = engine._pares_value(hand)[0] / 3.0
    grande = sum(RANK_MUS[c.rank] for c in hand) / 36.0
    return 0.4 * juego_score + 0.35 * pares + 0.25 * grande


def _lance_strength(engine, lance, seat) -> float:
    # Policies have the same private-card visibility as LLM seats.
    best = engine.hands[seat]
    if lance == "Grande":
        return sum(RANK_MUS[c.rank] for c in best) / 36.0
    if lance == "Chica":
        return 1.0 - sum(RANK_MUS[c.rank] for c in best) / 36.0
    if lance == "Pares":
        p = engine._pares_value(best)
        base = {0: 0.05, 1: 0.40, 2: 0.70, 3: 0.95}[p[0]]
        return min(1.0, base + (p[1][0] / 9.0) * 0.10 if p[1] else base)
    total = engine.hand_points(best, engine.card_points)
    if total in JUEGO_TOTALS:
        return JUEGO_RANK[total] / 10.0
    return (total / 30.0) * 0.6


class RandomPolicy:
    def __init__(self, seed=None):
        self.rng = Random(seed)

    def act(self, engine, seat, legal):
        if engine.phase == Phase.DECLARE:
            lance = LANCE_NAMES[engine.lance_index]
            has = (engine._pares_value(engine.hands[seat])[0] > 0
                   if lance == "Pares"
                   else _juego_total(engine, engine.hands[seat]) in JUEGO_TOTALS)
            return {"action": "tengo" if has else "no-tengo"}
        name = self.rng.choice(legal)
        a = {"action": name}
        if name == "discard":
            hand = engine.hands[seat]
            n = self.rng.randint(1, len(hand))
            a["cards"] = [str(c) for c in self.rng.sample(hand, n)]
        return a


class HeuristicPolicy:
    ORDAGO_CALL = 0.85
    OPEN_BID = 0.40
    RAISE_HIGH = 0.75
    FOLD_MAX = 0.35
    QUIERO_MIN = 0.45
    MUS_MAX = 0.45

    def act(self, engine, seat, legal):
        hand = engine.hands[seat]
        team = TEAM_OF[seat]
        if engine.phase == Phase.MUS_REQUEST:
            q = _hand_quality(engine, hand)
            if seat == engine.mano and "ordago" in legal and q >= self.ORDAGO_CALL:
                return {"action": "ordago"}
            return {"action": "mus" if q < self.MUS_MAX else "no"}

        if engine.phase == Phase.MUS_DRAW:
            return {"action": "discard", "cards": self._discard(engine, hand)}

        if engine.phase == Phase.DECLARE:
            lance = LANCE_NAMES[engine.lance_index]
            has = (engine._pares_value(hand)[0] > 0 if lance == "Pares"
                   else _juego_total(engine, hand) in JUEGO_TOTALS)
            return {"action": "tengo" if has else "no-tengo"}

        if engine.phase == Phase.ORDAGO_RESPONSE:
            q = _hand_quality(engine, hand)
            return {"action": "quiero" if q >= self.QUIERO_MIN else "no-quiero"}

        if engine.phase == Phase.ENVITE:
            return self._envite(engine, seat, team, legal)
        return {"action": legal[0]}

    @staticmethod
    def _discard(engine, hand):
        counts = Counter(RANK_MUS[c.rank] for c in hand)
        keep = [c for c in hand if counts[RANK_MUS[c.rank]] >= 2 or RANK_MUS[c.rank] >= 7]
        keep = keep[:3]
        toss = [c for c in hand if c not in keep]
        if not toss:
            toss = sorted(hand, key=lambda c: RANK_MUS[c.rank])[:1]
        return [str(c) for c in toss]

    def _envite(self, engine, seat, team, legal):
        lance = LANCE_NAMES[engine.lance_index]
        s = _lance_strength(engine, lance, seat)
        e = engine.envite
        own = e.holder is not None and TEAM_OF[e.holder] == team

        if e.current == 0:
            if "ordago" in legal and s >= self.ORDAGO_CALL:
                return {"action": "ordago"}
            if "envido" in legal and s >= self.OPEN_BID:
                return {"action": "envido"}
            return {"action": "paso"}

        if own:
            return {"action": "paso"}          # partner handles our team's bet

        if s >= self.RAISE_HIGH and "y-yo" in legal:
            return {"action": "reenvido" if e.current >= 4 else "y-yo"}
        if s < self.FOLD_MAX and "no-quiero" in legal:
            return {"action": "no-quiero"}
        if "quiero" in legal and s >= self.QUIERO_MIN:
            return {"action": "quiero"}
        if "no-quiero" in legal:
            return {"action": "no-quiero"}
        return {"action": legal[0]}
