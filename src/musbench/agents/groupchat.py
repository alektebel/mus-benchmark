"""Two temporal group channels plus a metered token budget for perception.

There are two channels an agent can listen to on each decision turn:

  * PUBLIC group chat  — a running transcript of what every seat says aloud.
  * SIGNALS API        — private, addressed agent-to-agent signal messages.

Listening is not free: each channel is metered in *tokens*, charged per
participant. The costs are abstract game-facing charges that drain a per-hand
perception budget; they are meant to model the real cost of putting a growing
transcript into the model's context (which is charged against the caller's total
token budget).

The listening cost constants can be tuned through the environment variables
``PUBLIC_COST_PER_PARTICIPANT`` and ``SIGNAL_COST_PER_SIGNAL``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# Cost to listen to the public group chat, per participant, per turn.
PUBLIC_COST_PER_PARTICIPANT = int(os.environ.get("PUBLIC_COST_PER_PARTICIPANT", "50"))
# Cost to listen to the signals API, per signal addressed to you, per turn.
SIGNAL_COST_PER_SIGNAL = int(os.environ.get("SIGNAL_COST_PER_SIGNAL", "50"))
# Per-hand perception budget (tokens) available to each agent.
PERCEPTION_BUDGET = int(os.environ.get("PERCEPTION_BUDGET", "2000"))


@dataclass
class PublicMessage:
    seat: int
    name: str
    text: str
    turn: int


@dataclass
class SignalEvent:
    from_seat: int
    to_seat: int | None   # None = table-wide gesture (broadcast)
    text: str
    turn: int


@dataclass
class AccessEvent:
    reader: int          # seat that accessed/read
    channel: str         # 'public' | 'signals'
    sender: int | None   # whose message/signal was read (None = public broadcast)
    turn: int


class Channels:
    """Sticky, temporal stores for both channels across a hand, plus an access log."""

    def __init__(self):
        self.public: list[PublicMessage] = []
        self.signals: list[SignalEvent] = []
        self.accesses: list[AccessEvent] = []

    def say_public(self, seat: int, name: str, text: str) -> None:
        self.public.append(PublicMessage(seat, name, text, len(self.public)))

    def send_signal(self, from_seat: int, to_seat: int, text: str) -> None:
        self.signals.append(SignalEvent(from_seat, to_seat, text, len(self.signals)))

    def clear(self) -> None:
        self.public.clear()
        self.signals.clear()
        self.accesses.clear()

    def add_access(self, reader: int, channel: str, sender: int | None = None) -> None:
        self.accesses.append(AccessEvent(reader, channel, sender, len(self.accesses)))




class PerceptionBudget:
    """Per-hand token budget for channel listening."""

    def __init__(self, budget: int = PERCEPTION_BUDGET):
        if budget < 0:
            raise ValueError("budget must be nonnegative")
        self.initial_budget = budget
        self.budget = budget

    @property
    def remaining(self) -> int:
        return self.budget

    def can_afford(self, cost: int) -> bool:
        return cost >= 0 and self.budget >= cost

    def spend(self, cost: int) -> bool:
        if cost < 0:
            raise ValueError("cost must be nonnegative")
        # Channels are always delivered; the budget tracks attention spend and
        # clamps at 0 (an agent that listens beyond its budget is 'on credit').
        self.budget = max(0, self.budget - cost)
        return True

    def reset(self) -> None:
        self.budget = self.initial_budget


def public_cost(num_participants: int) -> int:
    return PUBLIC_COST_PER_PARTICIPANT * num_participants


def signals_cost(num_signals: int) -> int:
    return SIGNAL_COST_PER_SIGNAL * num_signals
