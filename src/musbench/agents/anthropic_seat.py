"""Anthropic Messages API seat (Claude).

Not OpenAI-compatible: uses `https://api.anthropic.com/v1/messages` with
`x-api-key` + `anthropic-version`. Accepts `ANTHROPIC_API_KEY` or the legacy
`ANTHROPIC_key` env name.
"""
from __future__ import annotations

import json
import os
import time

import requests

from musbench.agents.core import SeatBase, THINK_BUDGET, MAX_RESP_CAP, RESP_RETRIES, _extract_json
from musbench.live.apifail import (FatalAPIError, LLMCallFailure, MatchTimeout,
                                  call_with_retries)

ENDPOINT = os.environ.get("ANTHROPIC_API_BASE",
                          "https://api.anthropic.com/v1").rstrip("/")
API_VERSION = os.environ.get("ANTHROPIC_VERSION", "2023-06-01")
# Live table: fast + mid. Opus stays out of the default pool (cost/latency).
DEFAULT_POOL = (
    "claude-haiku-5-5",
    "claude-sonnet-5-5",
)


def anthropic_api_key() -> str:
    return (os.environ.get("ANTHROPIC_API_KEY", "").strip()
            or os.environ.get("ANTHROPIC_key", "").strip())


class AnthropicAgent(SeatBase):
    """Seat backed by Anthropic Messages (`anthropic:claude-…`)."""

    is_llm = True

    def __init__(self, name: str, model: str, seat: int, team: int):
        self.name = name
        self.model = model
        self.seat = seat
        self.team = team
        self.provider = "anthropic"
        self.deadline = None
        self.api_key = anthropic_api_key()
        if not self.api_key:
            raise FatalAPIError(
                "env var ANTHROPIC_API_KEY (or ANTHROPIC_key) not set "
                "for provider anthropic")
        self._init_state()

    def decide(self, prompt: str) -> dict:
        max_tokens = min(THINK_BUDGET, MAX_RESP_CAP)
        last_err: Exception | None = None
        for _ in range(RESP_RETRIES):
            def _call():
                timeout = float(os.environ.get("NAN_TIMEOUT", "180"))
                if self.deadline is not None:
                    remaining = self.deadline - time.monotonic()
                    if remaining <= 0:
                        raise MatchTimeout("match deadline reached before Anthropic request")
                    timeout = min(timeout, remaining)
                body = {
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "system": (
                        "You are a mus (Spanish card game) player. "
                        "Play honestly and tactically. "
                        "Answer with a single JSON object only."),
                    "messages": [{"role": "user", "content": prompt}],
                }
                # Newer Claude aliases reject `temperature`; keep it optional.
                if os.environ.get("ANTHROPIC_TEMPERATURE", "").strip():
                    body["temperature"] = float(os.environ["ANTHROPIC_TEMPERATURE"])
                return requests.post(
                    f"{ENDPOINT}/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": API_VERSION,
                        "content-type": "application/json",
                    },
                    json=body,
                    timeout=timeout)

            try:
                d = call_with_retries(
                    _call, f"anthropic:{self.model}",
                    what=f"{self.name}/{self.model}",
                    deadline=self.deadline)
            except FatalAPIError:
                self.api_errors += 1
                raise
            except Exception as e:  # noqa: BLE001
                self.api_errors += 1
                last_err = e
                break
            self.calls += 1
            u = d.get("usage") or {}
            self.tokens_in += int(u.get("input_tokens") or 0)
            self.tokens_out += int(u.get("output_tokens") or 0)
            blocks = d.get("content") or []
            parts = []
            if isinstance(blocks, list):
                for b in blocks:
                    if isinstance(b, dict) and b.get("type") == "text":
                        parts.append(b.get("text") or "")
            content = "\n".join(parts)
            if not content.strip():
                last_err = ValueError("Anthropic response has no text")
                continue
            try:
                data = json.loads(_extract_json(content))
                if isinstance(data, dict):
                    self.last_io = {"prompt": prompt, "raw": content}
                    return data
                last_err = ValueError(f"JSON is not an object: {type(data)}")
            except json.JSONDecodeError as e:
                last_err = e
                continue
        raise LLMCallFailure(
            f"{self.name}/{self.model}: no valid action JSON; last_err={last_err}")


def list_anthropic_models() -> list[str]:
    """Return `anthropic:<id>` specs when a key is set."""
    key = anthropic_api_key()
    if not key:
        return []
    try:
        r = requests.get(
            f"{ENDPOINT}/models",
            headers={"x-api-key": key, "anthropic-version": API_VERSION},
            timeout=8)
        r.raise_for_status()
        data = r.json().get("data") or []
        # Prefer the short current aliases only (haiku + sonnet).
        want = set(DEFAULT_POOL)
        ids = []
        if isinstance(data, list):
            have = {item.get("id") for item in data if isinstance(item, dict)}
            for mid in DEFAULT_POOL:
                if mid in have:
                    ids.append(f"anthropic:{mid}")
        if ids:
            return ids
        # Fall back to whatever haiku/sonnet aliases exist without dates.
        if isinstance(data, list):
            for item in data:
                mid = item.get("id") if isinstance(item, dict) else None
                if mid and ("haiku" in mid or "sonnet" in mid) and "-20" not in mid:
                    if mid in want or mid.startswith("claude-haiku-5") or mid.startswith("claude-sonnet-5"):
                        ids.append(f"anthropic:{mid}")
        if ids:
            return list(dict.fromkeys(ids))
    except Exception:  # noqa: BLE001
        pass
    return [f"anthropic:{m}" for m in DEFAULT_POOL]
