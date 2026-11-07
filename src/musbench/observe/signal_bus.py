"""Partner-directed senas with virtual-time delivery and a TTL lease.

In real mus a sena is made AT THE TABLE, usually while the partner is
deliberating -- it is not bound to the sender's turn, and a gesture nobody
catches in time is simply missed. This bus models that:

  * events are addressed to one seat (the sender's partner), never broadcast;
  * each publish carries a virtual timestamp and a TTL;
  * an event is deliverable to its addressee only while unexpired;
  * delivery is performed by the kernel at the start of the addressee's next
    decision window (batched mode), so mid-window gestures inform the
    addressee's FOLLOWING deliberation unless they expire first.
  * RIVALS WATCH: with probability INTERCEPT_PROB each opposing seat caught
    the gesture too (decided once at publish time, from the bus's seeded
    rng, so runs stay reproducible). The emitter is never told either way,
    and an interception does not change delivery to the addressee.

Truth is evaluated by the sender's manager at publish time against the hand
AS IT THEN STANDS; a draw later in the hand can make a stale-but-unexpired
sena untrue, which mirrors the real game (the sena referred to the cards you
had when you made it).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from random import Random

INTERCEPT_PROB = float(os.environ.get("MUS_INTERCEPT_PROB", "0.35"))


@dataclass
class SignalEvent:
    seq: int
    t_pub: float
    from_seat: int
    to_seat: int
    gesture: str
    ttl: float
    truthful_at_pub: bool = True
    delivered_at: float | None = None
    expired: bool = False
    intercepted_by: frozenset[int] = frozenset()
    seen_by: set[int] = field(default_factory=set)

    @property
    def expires_at(self) -> float:
        return self.t_pub + self.ttl


class SignalBus:
    """Append-only event log with virtual-time pending/expired resolution."""

    def __init__(self, rng: Random | None = None,
                 intercept_prob: float | None = None):
        self.events: list[SignalEvent] = []
        self._seq = 0
        self.rng = rng or Random()
        # default bus is interception-free; call sites opt in via the
        # MUS_INTERCEPT_PROB global so plain SignalBus() stays deterministic
        self.intercept_prob = 0.0 if intercept_prob is None else intercept_prob

    def publish(self, from_seat: int, to_seat: int, gesture: str,
                t_pub: float, ttl: float, truthful_at_pub: bool = True) -> SignalEvent:
        if ttl <= 0:
            raise ValueError(f"ttl must be positive, got {ttl}")
        stolen = frozenset()
        if self.intercept_prob > 0.0:
            # each opposing seat may have been watching; one roll per seat,
            # at publish time, from the seeded stream
            stolen = frozenset(
                s for s in range(4)
                if s % 2 != from_seat % 2
                and self.rng.random() < self.intercept_prob)
        ev = SignalEvent(self._seq, float(t_pub), from_seat, to_seat,
                         gesture, float(ttl), truthful_at_pub,
                         intercepted_by=stolen)
        self._seq += 1
        self.events.append(ev)
        return ev

    def _mark_expired(self, now: float) -> None:
        for ev in self.events:
            if ev.delivered_at is None and not ev.expired and now >= ev.expires_at:
                ev.expired = True

    def pending_for(self, seat: int, now: float) -> list[SignalEvent]:
        """Unexpired events `seat` has not seen yet -- addressed to them, or
        intercepted -- published at or before `now`, in (t_pub, seq) order."""
        self._mark_expired(now)
        due = [ev for ev in self.events
               if ((ev.to_seat == seat and ev.delivered_at is None)
                   or (seat in ev.intercepted_by and seat not in ev.seen_by))
               and not ev.expired and ev.t_pub <= now]
        due.sort(key=lambda ev: (ev.t_pub, ev.seq))
        return due

    def deliver(self, events: list[SignalEvent], now: float,
                seat: int | None = None) -> None:
        for ev in events:
            if seat is not None:
                ev.seen_by.add(seat)
            if ev.to_seat == seat or seat is None:
                ev.delivered_at = now

    def gesture_live(self, from_seat: int, gesture: str, now: float) -> bool:
        """True if this seat's gesture was already caught by the partner, or
        is still in flight unexpired -- the player should not repeat it."""
        self._mark_expired(now)
        return any(ev.from_seat == from_seat and ev.gesture == gesture
                   and (ev.delivered_at is not None or not ev.expired)
                   for ev in self.events)

    def clear(self) -> None:
        self.events.clear()
        self._seq = 0

    def counts_for(self, seat: int, now: float | None = None) -> dict:
        """Per-seat signal tally for the run report."""
        if now is not None:
            self._mark_expired(now)
        out = {"sent": 0, "delivered": 0, "expired_unseen": 0, "intercepted": 0}
        for ev in self.events:
            if ev.from_seat == seat:
                out["sent"] += 1
                if ev.intercepted_by:
                    out["intercepted"] += 1
            if ev.to_seat == seat:
                if ev.delivered_at is not None:
                    out["delivered"] += 1
                elif ev.expired:
                    out["expired_unseen"] += 1
        return out
