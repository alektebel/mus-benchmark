"""Jev (TypeSafe System One) as a live/harness mus seat.

Jev is not a chat model: it answers typed questions with calibrated scores.
Each decision is one `choice` over the legal action names (parsed from the
prompt the harness already builds). Discard is delegated to HeuristicPolicy
because card-subset choice is a poor fit for a single System One question.
"""
from __future__ import annotations

import os
import re

import requests

from musbench.agents.baselines import HeuristicPolicy
from musbench.agents.core import SeatBase
from musbench.live.apifail import FatalAPIError, LLMCallFailure

ENDPOINT = os.environ.get("JEV_API_BASE", "https://api.typesafe.ai/v1").rstrip("/")
DEFAULT_MODEL = os.environ.get("JEV_MODEL", "jev-latest")
TIMEOUT = float(os.environ.get("JEV_TIMEOUT", "15"))

_LEGAL_RE = re.compile(
    r"Legal action names?:\s*(.+)$", re.I | re.M)
_HAND_RE = re.compile(
    r"YOUR HAND:\s*(.+?)(?:\s*\(punto|\n|$)", re.I)


class JevAgent(SeatBase):
    """Seat backed by TypeSafe System One (`typesafe:jev-…`)."""

    is_llm = True

    def __init__(self, name: str, model: str, seat: int, team: int):
        self.name = name
        self.model = model or DEFAULT_MODEL
        self.seat = seat
        self.team = team
        self.provider = "typesafe"
        self.deadline = None
        self.api_key = os.environ.get("JEV_TOKEN", "").strip()
        if not self.api_key:
            raise FatalAPIError("env var JEV_TOKEN not set for provider typesafe")
        self._init_state()

    def decide(self, prompt: str) -> dict:
        legal = _parse_legal(prompt)
        if not legal:
            raise LLMCallFailure(f"{self.name}/{self.model}: no legal actions in prompt")

        # Discard needs a card list; System One choice over action names is enough
        # for every other phase the live table asks an LLM about.
        if "discard" in legal and len(legal) == 1:
            cards = _parse_hand_cards(prompt)
            if not cards:
                raise LLMCallFailure(f"{self.name}/{self.model}: discard without hand")
            hand = [_card_from_name(n) for n in cards]
            toss = HeuristicPolicy._discard(None, hand)
            action = {"action": "discard", "cards": toss}
            self.calls += 1
            self.last_io = {"prompt": prompt, "raw": f"heuristic-discard:{toss}"}
            return action

        try:
            answers = self._system_one(prompt, legal)
        except (requests.RequestException, KeyError, ValueError, TypeError) as e:
            self.api_errors += 1
            raise LLMCallFailure(f"{self.name}/{self.model}: {e}") from e

        choice = answers.get("action", {}).get("choice")
        if choice not in legal:
            # fall back to highest-probability legal key if present
            probs = answers.get("action", {}).get("probabilities") or {}
            ranked = sorted(
                ((p, a) for a, p in probs.items() if a in legal),
                reverse=True)
            choice = ranked[0][1] if ranked else legal[0]
        self.calls += 1
        self.last_io = {"prompt": prompt, "raw": str(answers)}
        return {"action": choice}

    def _system_one(self, prompt: str, legal: list[str]) -> dict:
        criteria = {a: f"legal mus action `{a}`" for a in legal}
        body = {
            "model": self.model,
            "state": {
                "game": "mus",
                "legal_actions": legal,
                "prompt": prompt[:3500],
            },
            "questions": {
                "action": {
                    "type": "choice",
                    "instructions": (
                        "You are playing Spanish mus. Pick the single best "
                        "legal action for this seat given the prompt. Prefer "
                        "sound tactics over aggression; never invent an action "
                        "that is not in legal_actions."),
                    "criteria": criteria,
                },
            },
        }
        timeout = TIMEOUT
        if self.deadline is not None:
            import time
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                from musbench.live.apifail import MatchTimeout
                raise MatchTimeout("match deadline reached before Jev request")
            timeout = min(timeout, remaining)
        r = requests.post(
            f"{ENDPOINT}/systemone",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json=body,
            timeout=timeout)
        r.raise_for_status()
        data = r.json()
        u = data.get("usage") or {}
        self.tokens_in += int(u.get("input_tokens") or 0)
        self.tokens_out += int(u.get("output_tokens") or 0)
        return data.get("answers") or {}


def _parse_legal(prompt: str) -> list[str]:
    m = _LEGAL_RE.search(prompt or "")
    if not m:
        return []
    return [p.strip() for p in m.group(1).split(",") if p.strip()]


def _parse_hand_cards(prompt: str) -> list[str]:
    m = _HAND_RE.search(prompt or "")
    if not m:
        return []
    raw = m.group(1).strip()
    return [p.strip() for p in raw.split(",") if p.strip()]


def _card_from_name(name: str):
    from musbench.mus.deck import make_deck
    want = name.strip().lower()
    for c in make_deck():
        if str(c).lower() == want:
            return c
    raise ValueError(f"unknown card {name!r}")


def list_jev_models() -> list[str]:
    """Return `typesafe:<name>` specs when JEV_TOKEN is set."""
    key = os.environ.get("JEV_TOKEN", "").strip()
    if not key:
        return []
    try:
        r = requests.get(
            f"{ENDPOINT}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=8)
        r.raise_for_status()
        body = r.json()
        data = body.get("models") or body.get("data") or []
    except Exception:  # noqa: BLE001
        return [f"typesafe:{DEFAULT_MODEL}"]
    out = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                mid = item.get("name") or item.get("id")
            else:
                mid = str(item)
            if mid and str(mid).startswith("jev"):
                out.append(f"typesafe:{mid}")
    return out or [f"typesafe:{DEFAULT_MODEL}"]
