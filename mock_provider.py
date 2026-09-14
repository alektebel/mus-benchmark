"""A fake chat-completions endpoint, so a full match runs with zero API spend.

Only `requests.post` is replaced. Everything above it is the production path:
`prompt_builder` composes the same prompt, `StrictAgent.decide` does the same
JSON extraction, retry and escalation, the engine validates the same way, and
the decision log records the same records. That is the point -- a mock that
bypassed `StrictAgent` would test nothing about the code that actually runs.

Each mock model is a policy plus a personality, so the two sides are
distinguishable in the transcript and the scorecard has something to separate:

    MODELS = {"glm5.3-flash":      tight, rarely bluffs, terse table talk
              "deepseek-v4-flash": looser, bluffs more, chattier}

Responses are deterministic given the seed, so a mock run is reproducible.
"""
from __future__ import annotations

import json
import re
from random import Random
from unittest.mock import patch

from baselines_strict import EpsilonHeuristicPolicy
from mus_engine import LANCE_NAMES, Phase

# name -> (epsilon, bluff_p, voice)
PERSONAS = {
    "glm5.3-flash": (0.05, 0.10, [
        "Paso, no me interesa este lance.",
        "Voy con cuidado aqui.",
        "Que hable mi compañero.",
        "Aguanto, nada mas."]),
    "deepseek-v4-flash": (0.10, 0.35, [
        "Subo, a ver si te atreves.",
        "Aqui hay tela que cortar.",
        "No me tiembla el pulso.",
        "Te espero con esta."]),
}
DEFAULT_PERSONA = (0.08, 0.20, ["Juego."])


class MockModel:
    """One mock model: a mixed-threshold policy that emits real action JSON."""

    def __init__(self, name: str, engine, seed: int = 0):
        self.name = name
        self.engine = engine
        eps, bluff, voice = PERSONAS.get(name, DEFAULT_PERSONA)
        self.voice = voice
        self.policy = EpsilonHeuristicPolicy(eps, bluff, seed)
        self.rng = Random(seed)
        self.calls = 0

    # --------------------------------------------------------------- reply --
    def reply(self, prompt: str) -> str:
        self.calls += 1
        if "ONLY a JSON object: {\"notes\"" in prompt:
            return json.dumps({"notes": self._note(prompt)}, ensure_ascii=False)
        return json.dumps(self._action(prompt), ensure_ascii=False)

    def _seat_from(self, prompt: str) -> int:
        m = re.search(r"seat (\d+)\.", prompt)
        return int(m.group(1)) if m else self.engine.current_seat

    def _action(self, prompt: str) -> dict:
        e = self.engine
        seat = self._seat_from(prompt)
        legal = e.legal_actions(seat)
        act = dict(self.policy.act(e, seat, legal))
        act.setdefault("thought", self._thought(e, seat, act))
        act.setdefault("message", self.rng.choice(self.voice))
        act.setdefault("signal", None)
        act.setdefault("signal_policy", None)
        # honour the read side-channel when the prompt asks for it
        if "READ (required" in prompt:
            read = {}
            if '"p_win_lance"' in prompt:
                read["p_win_lance"] = round(self._belief(e, seat), 2)
            if '"p_opp_fold"' in prompt:
                read["p_opp_fold"] = round(0.3 + 0.4 * self.rng.random(), 2)
            act["read"] = read
        return act

    def _belief(self, e, seat) -> float:
        """A noisy read of its own lance strength -- not the truth, so the
        Brier numbers in a mock run are meaningful rather than perfect."""
        from baselines_strict import _lance_strength
        if e.phase not in (Phase.ENVITE, Phase.ORDAGO_RESPONSE):
            return 0.5
        if not 0 <= e.lance_index < len(LANCE_NAMES):
            return 0.5
        s = _lance_strength(e, LANCE_NAMES[e.lance_index], seat)
        return min(0.97, max(0.03, s + self.rng.uniform(-0.18, 0.18)))

    def _thought(self, e, seat, act) -> str:
        return (f"{self.name}: phase {e.phase.name}, playing "
                f"{act.get('action')} from seat {seat}.")

    def _note(self, prompt: str) -> str:
        seen = len(re.findall(r'"turn":', prompt))
        return (f"[{self.name}] reviewed {seen} turns of the last vaca. "
                f"Rivals fold to pressure on Chica more than on Grande; "
                f"keep pushing there next vaca.")


class MockProvider:
    """Patches requests.post for the duration of a `with` block."""

    def __init__(self, models: list[str], engine, seed: int = 0):
        self.engine = engine
        self.by_name = {}
        for i, name in enumerate(dict.fromkeys(models)):
            self.by_name[name] = MockModel(name, engine, seed * 97 + i)
        self.transcript: list[dict] = []
        self._patch = None

    def _post(self, url, headers=None, json=None, timeout=None, **kw):
        body = json or {}
        name = body.get("model", "")
        prompt = body["messages"][-1]["content"]
        model = self.by_name.get(name) or MockModel(name, self.engine)
        content = model.reply(prompt)
        self.transcript.append({"model": name, "prompt": prompt,
                                "response": content})

        class _Resp:
            status_code = 200
            headers: dict = {}
            text = content

            @staticmethod
            def json():
                return {"choices": [{"message": {"content": content},
                                     "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": len(prompt) // 4,
                                  "completion_tokens": len(content) // 4,
                                  "completion_tokens_details":
                                      {"reasoning_tokens": 0}}}
        return _Resp()

    def __enter__(self):
        self._patch = patch("agents.requests.post", side_effect=self._post)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()
        self._patch = None
