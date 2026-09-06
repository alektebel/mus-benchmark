"""LLM agent wrapper for the nan.builders OpenAI-compatible API.

Each decision turn builds a prompt (own hand, observable channel state, legal
actions, remaining credits) and asks the model for a strict JSON action:
    {"action": <name>, "signal"?: <optional text>, "observe"?: <type>}
The harness then validates against the engine's legal moves.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

import requests

BASE = os.environ.get("NAN_API_BASE", "https://api.nan.builders/v1")
API_KEY = os.environ.get("NAN_API_KEY", "")
TIMEOUT = float(os.environ.get("NAN_TIMEOUT", "60"))
MAX_REASON = 400
MAX_RESP = 600


@dataclass
class LLMAgent:
    name: str
    model: str
    seat: int = 0
    team: int = 0
    system: str = "You are a mus (Spanish card game) player. Play honestly and tactically."

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    def _payload(self, prompt: str) -> dict:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.4,
            "max_tokens": MAX_RESP,
        }

    def _call(self, prompt: str) -> str:
        r = requests.post(f"{BASE}/chat/completions", headers=self._headers(),
                          json=self._payload(prompt), timeout=TIMEOUT)
        r.raise_for_status()
        d = r.json()
        content = d["choices"][0]["message"].get("content")
        return content or ""

    def decide(self, prompt: str) -> dict:
        """Return a dict action. Retries on malformed JSON, returns {} on failure."""
        for attempt in range(3):
            try:
                raw = self._call(prompt)
                if not raw:
                    return {}
                data = json.loads(self._extract_json(raw))
                if isinstance(data, dict):
                    return data
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    print(f"[{self.name}] action parse failed: {e}")
                time.sleep(1)
        return {}

    @staticmethod
    def _extract_json(raw: str) -> str:
        """Tolerate fenced/marked-up JSON from reasoning model output."""
        raw = raw.strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            return raw[start:end + 1]
        return raw
