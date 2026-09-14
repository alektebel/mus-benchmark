"""The turn feed: what every seat did, as JSON, in the order it happened.

This replaces the harness-written prose summary with the raw record, so a seat
reasons about *what the other models actually did in which situation* rather
than about a statistic somebody else computed for it.

THE WHOLE RISK IS LEAKAGE. A decision JSON contains fields no opponent may
ever see -- the private `thought`, the `cards` a seat discarded, the
partner-directed `signal` and `signal_policy`. So the feed is built by an
allow-list, never by deleting fields from the raw action: a new field added to
the action schema tomorrow is invisible here by default instead of silently
becoming public. `tests/test_turn_feed.py` asserts that.

Two views of the same turn:

  OWN   the seat's own past turns, including its private `thought` -- your own
        reasoning is yours to remember.
  TABLE everyone else's turns, public fields only: seat, phase, lance, the
        action name, the spoken message, and the COUNT of cards discarded
        (at a real table you see that someone took three, not which three).

Scope is the current vaca. Piedras reset at 40 and the feed resets with them,
which is what makes "should anything survive a vaca?" a question the harness
can actually answer -- see `vaca_notes.py`.
"""
from __future__ import annotations

import json
import os

from mus_engine import TEAM_OF

TURN_FEED_MAX = int(os.environ.get("TURN_FEED_MAX", "60"))

# Allow-list. Anything not named here never reaches another seat.
PUBLIC_FIELDS = ("turn", "hand", "seat", "team", "phase", "lance",
                 "action", "message", "discarded")
OWN_EXTRA = ("thought",)


class TurnFeed:
    """Ordered public record of the turns played in the current vaca."""

    def __init__(self, limit: int = TURN_FEED_MAX):
        self.limit = limit
        self.turns: list[dict] = []
        self.vaca = 0

    # ---------------------------------------------------------- recording --
    def record(self, *, turn: int, hand: int, seat: int, phase: str,
               lance: str | None, action: dict | None,
               thought: str | None = None) -> dict:
        act = action if isinstance(action, dict) else {}
        name = act.get("action")
        msg = act.get("message")
        cards = act.get("cards")
        rec = {
            "turn": turn, "hand": hand, "seat": seat, "team": TEAM_OF[seat],
            "phase": phase, "lance": lance,
            "action": name if isinstance(name, str) else None,
            # the spoken message only; it is already redacted for card talk
            "message": msg.strip() if isinstance(msg, str) and msg.strip() else None,
            # how many cards were exchanged, never which ones
            "discarded": len(cards) if isinstance(cards, list) and cards else None,
            # private, kept out of every table view
            "_thought": thought.strip() if isinstance(thought, str) and thought.strip() else None,
        }
        self.turns.append(rec)
        if len(self.turns) > self.limit * 4:
            del self.turns[: -self.limit * 2]     # bound memory, keep a margin
        return rec

    def reset(self, vaca: int) -> None:
        """A vaca zeroes both scores; the feed goes with them."""
        self.turns.clear()
        self.vaca = vaca

    # ----------------------------------------------------------- rendering --
    @staticmethod
    def _view(rec: dict, own: bool) -> dict:
        out = {k: rec.get(k) for k in PUBLIC_FIELDS if rec.get(k) is not None}
        if own:
            for k in OWN_EXTRA:
                v = rec.get(f"_{k}")
                if v:
                    out[k] = v
        return out

    def view_for(self, seat: int) -> list[dict]:
        """The feed as one seat may see it. Own turns keep their thought."""
        recent = self.turns[-self.limit:]
        return [self._view(r, own=(r["seat"] == seat)) for r in recent]

    def render(self, seat: int) -> list[str]:
        rows = self.view_for(seat)
        if not rows:
            return []
        return ([f"TURN FEED -- every turn played so far in this vaca, oldest "
                 f"first ({len(rows)} shown). Your own turns keep your private "
                 f"\"thought\"; for every other seat you see only what the "
                 f"table saw. Reason about how THESE opponents have actually "
                 f"played."]
                + [json.dumps(r, ensure_ascii=False, sort_keys=True)
                   for r in rows])
