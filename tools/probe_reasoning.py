"""Probe which payload variants your providers accept, cheaply (max_tokens=8).

Finds how to DISABLE reasoning on nan/nvidia: each variant is one tiny call;
we report HTTP status + reasoning_tokens. Run before batch 1 and export the
winning mode:

    export REASONING_MODE=<mode>   # off | omit | none | low | ...

Usage: python probe_reasoning.py
"""
from __future__ import annotations

import os
import requests

PROVIDERS = {
    "nan": ("https://api.nan.builders/v1", "NAN_API_KEY",
            ["deepseek-v4-flash", "qwen3.8-flash", "glm5.3-flash", "gemma4"]),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_KEY",
               ["google/gemma-4-31b-it"]),
}
VARIANTS = ["omit", "off", "none", "minimal", "low"]


def probe(base, key, model, mode) -> None:
    p: dict = {"model": model,
               "messages": [{"role": "user", "content": 'Reply {"ok":true}'}],
               "max_tokens": 8}
    if mode != "omit":
        p["reasoning_effort"] = mode
    try:
        r = requests.post(f"{base}/chat/completions",
                          headers={"Authorization": f"Bearer {key}",
                                   "Content-Type": "application/json"},
                          json=p, timeout=60)
        if r.status_code == 200:
            d = r.json()
            rt = (d.get("usage", {}).get("completion_tokens_details") or {}).get(
                "reasoning_tokens")
            fr = (d.get("choices") or [{}])[0].get("finish_reason")
            print(f"    {mode:8s} -> 200 OK  reasoning_tokens={rt} finish={fr}")
        else:
            print(f"    {mode:8s} -> HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:  # noqa: BLE001
        print(f"    {mode:8s} -> {type(e).__name__}: {e}")


def main() -> None:
    for name, (base, key_env, models) in PROVIDERS.items():
        key = os.environ.get(key_env, "")
        print(f"\n=== {name} ({base})  key={'set' if key else 'MISSING'} ===")
        if not key:
            continue
        for m in models:
            print(f"  {m}:")
            for mode in VARIANTS:
                probe(base, key, m, mode)


if __name__ == "__main__":
    main()
