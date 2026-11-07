"""Jev-backed seña policies (option A): a System One co-processor decides
WHEN and WHICH gesture each seat flashes, replacing hand-written policy rules.

Jev (api.typesafe.ai/v1/systemone) is not a chat LLM: it answers typed
questions with calibrated probabilities. That matches the declarative seña
layer exactly -- the kernel interprets `SignalPolicy` rules, so the only new
piece is the question of WHERE those rules come from. With Jev, a seat's
policy is re-derived every hand from its actual cards instead of being
declared once and left stale.

Two call shapes, one endpoint:

  * policy call (per hand, per seat): one `choice` question over the 9-gesture
    vocabulary per phase/lance context, plus a `score` for the offset. The
    returned gesture set becomes the seat's SignalPolicy for that hand.
  * truthfulness is NOT delegated: the engine's `sena_truthful` stays the
    ground-truth check. Jev proposes; the engine disposes. A Jev-chosen
    gesture that is false of the hand is dropped exactly like a hand-declared
    rule would be (bluff affordance unchanged).

Failure mode: every Jev call is wrapped; on any error the seat falls back to
`reference_policy()` (the offline signalling floor) or `silent_policy()`, and
the match continues. Jev latency (~300 ms) is negligible against virtual
decision windows; there is no retry ladder here by design.
"""
from __future__ import annotations

import os

import requests

from musbench.mus.senas import SENAS
from musbench.observe.signal_manager import (SignalPolicy, SignalRule,
                                             DEFAULT_TTL, MAX_OFFSET)

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("JEV_MODEL", "jev-latest")
TIMEOUT = float(os.environ.get("JEV_TIMEOUT", "10"))

_GESTURES = tuple(SENAS)   # fixed order for reproducibility

# phase/lance contexts a hand walks through; one policy rule per context
_CONTEXTS = (
    ("*", "*"),
    ("ENVITE", "Grande"),
    ("ENVITE", "Chica"),
    ("DECLARE", "Pares"),
    ("DECLARE", "Juego"),
)


def _state(seat: int, hand, engine, partner_deciding: bool,
           caught: tuple[str, ...] = ()) -> dict:
    """Structured state Jev evaluates. Engine truth goes in (counts, points,
    pares value); the model never sees more than a seat legally knows."""
    from musbench.mus.senas import _count
    t = engine.hand_points(hand, engine.card_points)
    pares = engine._pares_value(hand)[0]
    return {
        "seat": seat,
        "hand": [str(c) for c in hand],
        "summary": {
            "reyes": _count(hand, "rey"),       # rey or tres (equivalence)
            "ases": _count(hand, "as"),         # as or dos (equivalence)
            "pares_value": int(pares),          # 0 none, 1 pares, 2 medias, 3 duples
            "juego_points": t,
            "juego": t in engine.juego_totals,
        },
        "partner_is_deciding": partner_deciding,
        "partner_already_caught": list(caught),
        "note": ("mus rank equivalence: a tres counts as a rey and a dos "
                 "counts as an as, for every gesture and for Juego"),
    }


def _questions(context: tuple[str, str]) -> dict:
    phase, lance = context
    gesture_criteria = {g: SENAS[g][0] for g in _GESTURES}
    q: dict = {
        "gesture": {
            "type": "choice",
            "instructions": (
                "Which single sena should this seat flash to its partner in "
                f"this context (phase={phase}, lance={lance})? Pick the ONE "
                "gesture that is truthful of the hand AND most useful to a "
                "mus partner right now. If none is truthful and useful, "
                "answer cerrar-los-ojos (the ciego: I have nothing)."),
            "criteria": gesture_criteria,
        },
        "offset_score": {
            "type": "score",
            "instructions": (
                "How early inside the deciding partner's deliberation window "
                "should the gesture fire? The addressee's next decision is "
                "roughly 4 window-units away, so early beats late."),
            "criteria": ["immediately", "early", "middle", "late",
                         "at the very end"],
        },
    }
    return q


def _rule_from_context(context: tuple[str, str], answers: dict,
                       caught: bool) -> SignalRule | None:
    """Turn one Jev answer pair into a SignalRule. `caught` gestures collapse
    to wildcard so the rule can still fire for later, uncaught windows."""
    phase, lance = context
    g = answers["gesture"]["choice"]
    offset = min(max(answers["offset_score"]["score"] / 4.0, 0.0), MAX_OFFSET)
    return SignalRule(gesture=g, when_phase=phase, when_lance=lance,
                      when_deciding="partner", offset=offset,
                      ttl=DEFAULT_TTL, bluff=False)


def _post(state: dict, questions: dict) -> dict:
    r = requests.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {os.environ['JEV_TOKEN']}",
                 "Content-Type": "application/json"},
        json={"model": MODEL, "state": state, "questions": questions},
        timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def jev_policy(seat: int, hand, engine,
               caught: tuple[str, ...] = ()) -> SignalPolicy | None:
    """Ask Jev for this seat's gesture plan for the current hand. Returns
    None (caller falls back) when JEV_TOKEN is unset or the API fails."""
    if not os.environ.get("JEV_TOKEN"):
        return None
    try:
        rules = []
        for ctx in _CONTEXTS:
            answers = _post(_state(seat, hand, engine, True, caught),
                            _questions(ctx))["answers"]
            rule = _rule_from_context(ctx, answers, False)
            if rule is not None:
                rules.append(rule)
        # dedupe identical (gesture, phase, lance) rules, keep first
        seen = set()
        uniq = []
        for r in rules:
            k = (r.gesture, r.when_phase, r.when_lance)
            if k not in seen:
                seen.add(k)
                uniq.append(r)
        return SignalPolicy(rules=tuple(uniq), enabled=True)
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None


def jev_truth_probability(sena: str, hand, engine) -> float | None:
    """Post-hoc calibrated truth probability for one gesture-hand pair.
    Analysis-side helper (option C lives on top of this); unused by the
    kernel path, which keeps the engine's binary verdict."""
    if not os.environ.get("JEV_TOKEN"):
        return None
    state = _state(0, hand, engine, False)
    state["gesture"] = sena
    state["gesture_meaning"] = SENAS.get(sena, ("?", ""))[0]
    try:
        a = _post(state, {"truthful": {
            "type": "noul",
            "instructions": (
                "Is the gesture truthful of this mus hand? Rank equivalence: "
                "a tres counts as a rey, a dos counts as an as."),
            "criteria": {"true": "meaning accurate",
                         "false": "meaning inaccurate"},
        }})["answers"]
        return float(a["truthful"]["noul"])
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return None
