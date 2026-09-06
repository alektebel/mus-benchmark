"""Non-LLM baselines. They implement the same ``decide(prompt) -> dict`` shape as
``LLMAgent``, so they can be dropped into ``run_match(make_agent=...)`` without
touching the harness. These establish the skill floor for the benchmark.

Strategies are intentionally simple and rule-based (no API, no learning):
  - RandomAgent  : picks a uniformly random legal action; random discard.
  - HeuristicAgent: "mus" on a weak hand, keeps strong cards when drawing,
                    never risks ordago.
"""
from __future__ import annotations

import random

from deck import RANK_ORDER, RANK_POINTS


def _parse_hand(prompt: str) -> list[str]:
    for line in prompt.splitlines():
        s = line.strip()
        if s.startswith("YOUR HAND:"):
            tail = s.split("YOUR HAND:", 1)[1]
            return [x.strip().rstrip(".") for x in tail.split(",") if x.strip()]
    return []


def _parse_legal(prompt: str) -> list[str]:
    for line in prompt.splitlines():
        s = line.strip()
        if "Legal action names:" in s:
            tail = s.split("Legal action names:", 1)[1]
            return [x.strip().rstrip(".") for x in tail.split(",") if x.strip()]
    return []


def _phase(prompt: str) -> str:
    for line in prompt.splitlines():
        if "Phase:" in line:
            return line.split("Phase:", 1)[1].split(".")[0].strip()
    return ""


def _rank(card_str: str) -> str:
    """'as de oros' -> 'as'."""
    return card_str.split()[0]


class RandomAgent:
    def __init__(self, name: str, model: str = "random", seat: int = 0, team: int = 0):
        self.name = name
        self.model = model
        self.seat = seat
        self.team = team
        self.rng = random.Random()

    def decide(self, prompt: str) -> dict:
        legal = _parse_legal(prompt)
        if not legal:
            return {}
        if _phase(prompt) == "MUS_DRAW":
            hand = _parse_hand(prompt)
            n = min(len(hand), self.rng.randint(1, 4))
            return {"action": "discard", "cards": self.rng.sample(hand, n),
                    "observe": None, "signal": None}
        return {"action": self.rng.choice(legal), "observe": None, "signal": None}


class HeuristicAgent:
    def __init__(self, name: str, model: str = "heuristic", seat: int = 0, team: int = 0):
        self.name = name
        self.model = model
        self.seat = seat
        self.team = team

    def decide(self, prompt: str) -> dict:
        hand = _parse_hand(prompt)
        if not hand:
            return {}
        if _phase(prompt) == "MUS_DRAW":
            # discard the two weakest (lowest-ranked) cards, keep strong ones.
            ranked = sorted(hand, key=lambda c: RANK_ORDER.index(_rank(c)))
            return {"action": "discard", "cards": ranked[: min(2, len(ranked))],
                    "observe": None, "signal": None}
        pts = sum(RANK_POINTS.get(_rank(c), 0) for c in hand)
        # weak hand -> ask for cards; otherwise keep. Never ordago.
        if pts < 20:
            return {"action": "mus", "observe": None, "signal": None}
        return {"action": "no", "observe": None, "signal": None}
