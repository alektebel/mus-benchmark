"""Spanish 40-card deck for mus."""
from __future__ import annotations

from dataclasses import dataclass
from random import Random

PALOS = ("oros", "copas", "espadas", "bastos")

# Physical deck order, also used by the legacy engine. The strict engine
# defines its own mus-rank equivalence (rey=tres, as=dos) in RANK_MUS.
RANK_ORDER = (
    "as", "dos", "tres", "cuatro", "cinco", "seis",
    "siete", "sota", "caballo", "rey",
)

# Legacy-engine point values; the strict engine uses its own CARD_POINTS.
# as=11, tres=10, rey=4, caballo=4, sota=4, dos=2, else = 0.
RANK_POINTS = {
    "as": 11, "dos": 2, "tres": 10, "cuatro": 0, "cinco": 0,
    "seis": 0, "siete": 0, "sota": 4, "caballo": 4, "rey": 4,
}


@dataclass(frozen=True)
class Card:
    rank: str
    palo: str

    @property
    def points(self) -> int:
        return RANK_POINTS[self.rank]

    @property
    def rank_index(self) -> int:
        # Index in physical rank order; rey is highest.
        return RANK_ORDER.index(self.rank)

    def __str__(self) -> str:
        return f"{self.rank} de {self.palo}"


def make_deck() -> list[Card]:
    return [Card(rank, palo) for palo in PALOS for rank in RANK_ORDER]


def shuffle_deck(rng: Random) -> list[Card]:
    deck = make_deck()
    rng.shuffle(deck)
    return deck
