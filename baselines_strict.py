"""Baseline agents for the Fournier-aligned strict engine.

Policies act directly on engine state via act(engine, seat, legal) -- no API.
  RandomPolicy    : uniform over legal actions (truthful declarations).
  HeuristicPolicy : mus-aware floor -- honest declarations, named-bet envites
                    (envido / y-yo / reenvido / quiero / no-quiero / ordago).
  EpsilonHeuristicPolicy : the same thresholds played as a MIXED strategy.

Why the mixed one exists: HeuristicPolicy is deterministic and only ever opens
above OPEN_BID, so it never bluffs. As a reference for a benchmark about
bluffing that makes it degenerate -- bluff_rate ~ 0, no bluff to catch, no
fold decision to read. EpsilonHeuristicPolicy bluffs at a rate you SET, which
is the only way to check that the scorecard measures what it claims to.
"""
from __future__ import annotations

import os
from bisect import bisect_left, bisect_right
from collections import Counter
from random import Random

from deck import make_deck
from mus_engine import (MusEngine, Phase, TEAM_OF, JUEGO_TOTALS, JUEGO_RANK,
                        LANCE_NAMES, RANK_GRANDE, RANK_CHICA)


def _juego_total(engine, hand):
    return engine.hand_points(hand, engine.card_points)


def _hand_quality(engine, hand) -> float:
    total = _juego_total(engine, hand)
    juego_score = JUEGO_RANK.get(total, 0) / 10.0 if total in JUEGO_TOTALS else 0.0
    pares = engine._pares_value(hand)[0] / 3.0
    grande = sum(RANK_GRANDE[c.rank] for c in hand) / 48.0
    return 0.4 * juego_score + 0.35 * pares + 0.25 * grande


_PCT_SAMPLES = int(os.environ.get("STRENGTH_SAMPLES", "6000"))
_PCT_TABLES: dict[str, list] = {}


def _percentile_tables() -> dict[str, list]:
    """For each lance, the sorted distribution of `_lance_value` over random
    hands, built once.

    Hand strength is then "what fraction of random hands this hand beats at
    this lance", using the ENGINE's own comparison. The previous ad-hoc sums
    were not comparable across lances -- a raw Grande score averaged ~0.67 and
    a raw Chica score ~0.62, so a single threshold like OPEN_BID meant a
    different thing in every lance -- and the Chica one was inverted outright.
    """
    if _PCT_TABLES:
        return _PCT_TABLES
    ref = MusEngine(rng=Random(0))
    rng = Random(12345)                       # fixed: the scale is a constant
    pools = {name: [] for name in LANCE_NAMES}
    for _ in range(_PCT_SAMPLES):
        deck = make_deck()
        rng.shuffle(deck)
        hand = deck[:4]
        for name in LANCE_NAMES:
            pools[name].append(ref._lance_value(name, hand))
    for name, vals in pools.items():
        vals.sort()
        _PCT_TABLES[name] = vals
    return _PCT_TABLES


def _lance_strength(engine, lance, seat) -> float:
    """Percentile of this seat's hand at this lance, in [0, 1].

    Policies have the same private-card visibility as LLM seats: this reads
    only `engine.hands[seat]`.
    """
    table = _percentile_tables()[lance]
    value = engine._lance_value(lance, engine.hands[seat])
    lo = bisect_left(table, value)
    hi = bisect_right(table, value)
    return (lo + hi) / (2.0 * len(table))     # mid-rank: ties sit in the middle


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
        counts = Counter(RANK_GRANDE[c.rank] for c in hand)
        keep = [c for c in hand
                if counts[RANK_GRANDE[c.rank]] >= 2 or RANK_GRANDE[c.rank] >= 7]
        keep = keep[:3]
        toss = [c for c in hand if c not in keep]
        if not toss:
            toss = sorted(hand, key=lambda c: RANK_GRANDE[c.rank])[:1]
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


class EpsilonHeuristicPolicy:
    """HeuristicPolicy played as a mixed strategy, with a known bluff rate.

    Two knobs, both ground truth because you chose them:

      epsilon : chance of playing a uniformly random legal action instead of
                the threshold action. Classic exploration noise; it also stops
                the policy being a pure function of the hand, so an opponent
                cannot read it perfectly even in principle.
      bluff_p : chance of betting or raising anyway from a hand the thresholds
                would pass or fold. This is the knob that creates bluffs at a
                rate the harness knows in advance.

    Declarations stay truthful in every branch -- the engine rejects a false
    tengo/no-tengo, so randomising them would just manufacture rejections.
    `self.stats` records what the policy actually chose, so a test can check
    the measured bluff rate against the configured one.
    """

    def __init__(self, epsilon: float = 0.10, bluff_p: float = 0.15,
                 seed: int | None = None):
        if not 0.0 <= epsilon <= 1.0:
            raise ValueError("epsilon must be in [0, 1]")
        if not 0.0 <= bluff_p <= 1.0:
            raise ValueError("bluff_p must be in [0, 1]")
        self.epsilon = epsilon
        self.bluff_p = bluff_p
        self.rng = Random(seed)
        self.base = HeuristicPolicy()
        # its own generator so epsilon draws stay reproducible regardless of
        # how many random actions the noise policy happens to need
        self.noise = RandomPolicy(seed)
        self.stats = Counter()

    def act(self, engine, seat, legal):
        if engine.phase == Phase.DECLARE:
            return self.base.act(engine, seat, legal)   # truth is not optional
        if self.rng.random() < self.epsilon:
            self.stats["epsilon"] += 1
            return self.noise.act(engine, seat, legal)
        if engine.phase == Phase.ENVITE:
            bluff = self._maybe_bluff(engine, seat, legal)
            if bluff is not None:
                return bluff
        self.stats["policy"] += 1
        return self.base.act(engine, seat, legal)

    def _maybe_bluff(self, engine, seat, legal) -> dict | None:
        """Push from a hand the thresholds would give up on."""
        lance = LANCE_NAMES[engine.lance_index]
        s = _lance_strength(engine, lance, seat)
        e = engine.envite
        if e.holder is not None and TEAM_OF[e.holder] == TEAM_OF[seat]:
            return None                       # our own bet; partner answers
        if self.rng.random() >= self.bluff_p:
            return None
        if e.current == 0:
            if s < self.base.OPEN_BID and "envido" in legal:
                self.stats["bluff_open"] += 1
                return {"action": "envido"}
            return None
        if s < self.base.FOLD_MAX:
            for name in ("reenvido", "y-yo"):
                if name in legal:
                    self.stats["bluff_raise"] += 1
                    return {"action": name}
            if "quiero" in legal:
                self.stats["bluff_call"] += 1   # a light call, same family
                return {"action": "quiero"}
        return None


def parse_baseline(spec: str, seed: int = 0):
    """Baseline seat specs. Returns (label, policy) or None if not a baseline.

      heuristic            deterministic thresholds (never bluffs)
      random               uniform over legal actions
      eps                  mixed thresholds, defaults epsilon=0.10 bluff_p=0.15
      eps:0.05             epsilon only
      eps:0.05:0.25        epsilon and bluff_p
    """
    if not isinstance(spec, str):
        return None
    parts = spec.strip().split(":")
    kind = parts[0].strip().lower()
    if kind == "heuristic" and len(parts) == 1:
        return "heuristic", HeuristicPolicy()
    if kind == "random" and len(parts) == 1:
        return "random", RandomPolicy(seed)
    if kind != "eps":
        return None
    try:
        epsilon = float(parts[1]) if len(parts) > 1 and parts[1] else 0.10
        bluff_p = float(parts[2]) if len(parts) > 2 and parts[2] else 0.15
    except ValueError:
        return None
    if len(parts) > 3:
        return None
    return (f"eps:{epsilon:g}:{bluff_p:g}",
            EpsilonHeuristicPolicy(epsilon, bluff_p, seed))
