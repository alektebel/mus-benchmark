"""Full mus engine, 2v2, with vacas scoring.

4 seats: seat index 0..3. Teams are partners sitting opposite.
  Team A = seats {0, 2};  Team B = seats {1, 3}.

Game flow per hand:
  DEAL          - 4 cards to each seat.
  MUS_REQUEST   - seats in order declare "mus" (want cards) or "no".
                  On the first seat of a hand they may instead throw
                  "ordago", which resolves the whole hand immediately
                  when accepted (full jugada comparison).
  MUS_DRAW      - each seat that declared "mus" discards 1-4 cards and
                  redraws (chosen by the agent).
  JUGADAS       - Grande, Chica, Pares, Juego are compared between teams.

Vacas scoring: each jugada won by a team awards 1 vaca. <=>4 per hand.
  - On an accepted ordago the winner takes all 4 vacas, loser 0.
  - A drawn jugada awards 0 to both.
Team with more total vacas across the match wins.

The engine is deterministic given an RNG; the harness drives all
decision points, so the engine never calls an LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from random import Random

from deck import Card, make_deck, RANK_POINTS, RANK_ORDER

TEAM_OF = {0: 0, 1: 1, 2: 0, 3: 1}
PARTNER = {0: 2, 1: 3, 2: 0, 3: 1}


class Phase(Enum):
    MUS_REQUEST = auto()
    MUS_DRAW = auto()
    JUGADAS = auto()
    DONE = auto()


@dataclass
class JugadaResult:
    name: str
    winner_team: int | None  # 0, 1, or None (draw)


@dataclass
class HandResult:
    vacas_a: int
    vacas_b: int
    jugadas: list[JugadaResult] = field(default_factory=list)
    ordago_caller: int | None = None
    ordago_accepted: bool = False
    hand_winner: int | None = None  # team with more vacas


class MusEngine:
    def __init__(self, rng: Random | None = None):
        self.rng = rng or Random()

    # ---------------- card utilities ----------------
    @staticmethod
    def rank_min(rank: str) -> int:
        """Ordinal for Grande/Chica."""
        return RANK_ORDER.index(rank)

    @staticmethod
    def hand_points(cards: list[Card]) -> int:
        return sum(c.points for c in cards)

    # ---------------- per-player jugada values ----------------
    # Real mus is 2v2: each player holds 4 cards and every jugada is judged on a
    # single player's hand. A team's value for a jugada is the best of its two
    # players' values. Here "higher value = better" for every jugada.
    @staticmethod
    def _grande_value(hand: list[Card]) -> tuple:
        return tuple(sorted((c.rank_index for c in hand), reverse=True))

    @staticmethod
    def _chica_value(hand: list[Card]) -> tuple:
        # The lowest card wins Chica, so invert ranks to keep "higher = better".
        return tuple(sorted((9 - c.rank_index for c in hand), reverse=True))

    @staticmethod
    def _pares_value(hand: list[Card]) -> tuple:
        from collections import Counter
        counts = Counter(c.rank for c in hand)
        pair_ranks = sorted(
            [r for r, n in counts.items() if n >= 2],
            key=lambda r: RANK_ORDER.index(r), reverse=True,
        )
        if len(pair_ranks) >= 2:
            # Duples (two pairs) outrank medias and pares.
            return (3, tuple(RANK_ORDER.index(r) for r in pair_ranks))
        if len(pair_ranks) == 1:
            r = pair_ranks[0]
            if counts[r] >= 3:
                # Medias (three/four of a kind) outrank a single pair.
                return (2, (RANK_ORDER.index(r),))
            return (1, (RANK_ORDER.index(r),))
        return (0, ())

    # Juego ranking: 31 < 32 < 33 < 34 < 35 < 36 < 37 < 40.
    JUEGO_TOTALS = (31, 32, 33, 34, 35, 36, 37, 40)

    @classmethod
    def _juego_value(cls, hand: list[Card]) -> tuple:
        total = cls.hand_points(hand)
        if total in cls.JUEGO_TOTALS:
            return (1, total)          # juego (valid total)
        if total > 40:
            return (1, 40)             # totals above 40 rank as the highest juego
        return (0, total)              # punto (no juego)

    @classmethod
    def is_juego(cls, cards: list[Card]) -> bool:
        return cls._juego_value(cards)[0] == 1

    # ---------------- team comparison ----------------
    @staticmethod
    def _team_best(hands: dict[int, list[Card]], team: int, value_fn) -> list[Card]:
        players = [hands[s] for s in range(4) if TEAM_OF[s] == team]
        return max(players, key=value_fn)

    def compare_jugadas(self, hands: dict[int, list[Card]]) -> list[JugadaResult]:
        """hands maps seat -> 4-card hand. Each jugada compares the best of each
        team's two players."""
        specs = [
            ("Grande", self._grande_value),
            ("Chica", self._chica_value),
            ("Pares", self._pares_value),
            ("Juego", self._juego_value),
        ]
        results = []
        for name, value_fn in specs:
            va = value_fn(self._team_best(hands, 0, value_fn))
            vb = value_fn(self._team_best(hands, 1, value_fn))
            if va > vb:
                w = 0
            elif vb > va:
                w = 1
            else:
                w = None
            results.append(JugadaResult(name, w))
        return results

    def grande_winner(self, hands: dict[int, list[Card]]) -> int | None:
        va = self._grande_value(self._team_best(hands, 0, self._grande_value))
        vb = self._grande_value(self._team_best(hands, 1, self._grande_value))
        if va > vb:
            return 0
        if vb > va:
            return 1
        return None

    def vacas_from_jugadas(self, jugadas: list[JugadaResult]) -> tuple[int, int]:
        a = sum(1 for j in jugadas if j.winner_team == 0)
        b = sum(1 for j in jugadas if j.winner_team == 1)
        return a, b

    # ---------------- hand state ----------------
    def deal(self) -> dict[int, list[Card]]:
        deck = make_deck()
        self.rng.shuffle(deck)
        hands = {s: deck[s * 4:(s + 1) * 4] for s in range(4)}
        self._draw_pile = deck[16:]
        return hands

    def redraw(self, seat: int, hands: dict[int, list[Card]], discard: list[Card]) -> None:
        if seat not in hands:
            raise ValueError("unknown seat")
        if not 1 <= len(discard) <= 4 or len(set(discard)) != len(discard):
            raise ValueError("discard must contain 1 to 4 distinct cards")
        if any(card not in hands[seat] for card in discard):
            raise ValueError("discard cards must belong to the player")
        if len(getattr(self, "_draw_pile", [])) < len(discard):
            raise ValueError("not enough cards in draw pile")
        for d in discard:
            hands[seat].remove(d)
            card = self._draw_pile.pop()
            hands[seat].append(card)
