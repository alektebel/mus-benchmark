"""Partial-observability channel model with a limited attention budget.

The harness mediates perception. On each decision turn an agent is offered the
legal actions plus, if credits remain, the option to spend attention to read the
signals its partner has emitted and/or to detect whether the opponents are
signalling. Spent credits come out of a per-hand budget, so a pair that pours
attention into decoding its own signals has less left to glance at the
opponents, and vice versa.

CREDIT COSTS
  PARTNER_SIGNAL_DECODE   2  -> reveal the texts of partner signals.
  OPP_SIGNAL_DETECT       1  -> flag only: how many opponent signals have fired.
  PARTNER_SIGNAL_DETECT   1  -> flag only: one of my partner signals fired.

Signals are emitted into the bus by an agent's own action (``signal`` field of
the returned JSON). Events persist across phases and are cleared each hand.
"""
from __future__ import annotations

from dataclasses import dataclass, field

COST_PARTNER_DECODE = 2
COST_OPP_DETECT = 1
COST_PARTNER_DETECT = 1


@dataclass
class SignalEvent:
    emitter_team: int          # 0 or 1
    kind: str                  # "declared" | "hinted" | "joke" | ...
    text: str                  # encrypted-by-default content
    revealed: bool = False
    emitter_seat: int | None = None


@dataclass
class SignalBus:
    events: list[SignalEvent] = field(default_factory=list)

    def emit(self, team: int, kind: str, text: str, seat: int | None = None) -> None:
        self.events.append(SignalEvent(emitter_team=team, kind=kind, text=text, emitter_seat=seat))

    def partner_events(self, team: int, reader: int) -> list[SignalEvent]:
        return [e for e in self.team_events(team) if e.emitter_seat != reader]

    def clear(self) -> None:
        self.events.clear()

    def team_events(self, team: int) -> list[SignalEvent]:
        return [e for e in self.events if e.emitter_team == team]

    def count_team(self, team: int) -> int:
        return len(self.team_events(team))

    def decode_partner(self, team: int) -> list[str]:
        """Reveal (mutate) and return the texts of this team's signals."""
        out = []
        for e in self.team_events(team):
            if not e.revealed:
                e.revealed = True
            out.append(e.text)
        return out


class AttentionAccount:
    def __init__(self, credits: int = 10):
        if credits < 0:
            raise ValueError("credits must be nonnegative")
        self.credits = credits
        self.max = credits
        self.opponent_count: int | None = None

    def can(self, cost: int) -> bool:
        return cost >= 0 and self.credits >= cost

    def spend(self, cost: int) -> bool:
        if cost < 0 or self.credits < cost:
            return False
        self.credits -= cost
        return True

    def reset(self) -> None:
        self.credits = self.max
        self.opponent_count = None
