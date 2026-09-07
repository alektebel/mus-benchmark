"""Strict multi-LLM mus harness entry point (CLI).

The harness logic lives in `agents.py` (LLM + baseline seats), `match.py`
(one turn / hand / match loop), and `prompt_builder.py` (model prompts).
This module wires them together and exposes the CLI.

CLI:
  python run_match_strict.py --models "deepseek-v4-flash,heuristic,deepseek-v4-flash,heuristic" --hands 12
"""
from __future__ import annotations

import argparse
import json
from random import Random

import requests
import apifail

from mus_engine import MusEngine
from agents import (StrictAgent, BaselineSeat, _make_agent, _default_legal,
                    MAX_RESP, REASONING_MODE)
from prompt_builder import build_prompt, _channel_block, redact_card_talk
from match import (run_match_strict, run_hand, play_turn, reset_hand_channels,
                   _emit, _record_event, _print_turn)
from apifail import (FatalAPIError, LLMCallFailure, MatchTimeout, DegradedMatch,
                     TurnLimitExceeded)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models",
                    default="deepseek-v4-flash,heuristic,deepseek-v4-flash,heuristic",
                    help="4 specs: model-name (nan), provider:model via tuple in "
                         "code, or heuristic/random for baseline seats")
    ap.add_argument("--hands", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    models = [m.strip() for m in args.models.split(",")]
    if len(models) != 4 or any(not m for m in models):
        ap.error("--models requires exactly four non-empty comma-separated specs")
    if args.hands <= 0:
        ap.error("--hands must be positive")
    print(f"Match: {' vs '.join(models)}  "
          f"(teams: {models[0]}+{models[2]} | {models[1]}+{models[3]})")
    print(f"hands={args.hands} seed={args.seed} "
          f"reasoning={REASONING_MODE} max_tokens={MAX_RESP}\n")
    res = run_match_strict(MusEngine(rng=Random(args.seed)), models, hands=args.hands,
                           seed=args.seed, verbose=args.verbose)
    print(f"\nResult: vacas {res['vacas_a']}-{res['vacas_b']}  hands={res['hands']} "
          f"status={res['status']}")
    print(f"Token usage: in={res['usage']['tokens_in']} "
          f"out={res['usage']['tokens_out']} (reasoning={res['usage']['reasoning']}) "
          f"calls={res['usage']['calls']} fallbacks={res['usage']['fallbacks']}"
          f"/{res['usage']['turns']} turns elapsed={res['elapsed']}s")
    if args.out:
        with open(args.out, "w") as f:
            json.dump(res, f, indent=2)
        print(f"Saved -> {args.out}")


if __name__ == "__main__":
    main()
