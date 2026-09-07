"""Spanish 40-card deck for mus."""
from __future__ import annotations

from dataclasses import dataclass

PALOS = ("oros", "copas", "espadas", "bastos")

# Physical deck order, used for the strict engine's mus-rank comparisons and
# the strict engine defines its own mus-rank equivalence (rey=tres, as=dos)
# in RANK_MUS.
RANK_ORDER = (
    "as", "dos", "tres", "cuatro", "cinco", "seis",
    "siete", "sota", "caballo", "rey",
)


@dataclass(frozen=True)
class Card:
    rank: str
    palo: str

    @property
    def rank_index(self) -> int:
        # Index in physical rank order; rey is highest.
        return RANK_ORDER.index(self.rank)

    def __str__(self) -> str:
        return f"{self.rank} de {self.palo}"


def make_deck() -> list[Card]:
    return [Card(rank, palo) for palo in PALOS for rank in RANK_ORDER]
