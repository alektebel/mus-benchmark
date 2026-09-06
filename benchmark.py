"""Run the benchmark: every ordered pair of the 4 participants as one team,
against a fixed reference-model opponent pair. Build a vacas win-rate matrix.

CLI:
  python benchmark.py [--hands N] [--reps R] [--out results.json]
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import time
from hashlib import sha256

from engine import MusEngine
from run_match import run_match

PARTICIPANTS = ["deepseek-v4-flash", "qwen3.8-flash", "glm5.3-flash", "gemma4"]
REF_MODEL = "qwen3.6"

MATCH_HANDS = int(os.environ.get("MATCH_HANDS", "12"))
REPS_PER_PAIR = int(os.environ.get("REPS_PER_PAIR", "3"))


def win_rate(res) -> float:
    total = res.vacas_a + res.vacas_b
    return res.vacas_a / total if total else 0.5


def run_all(hands: int, reps: int) -> dict:
    if hands <= 0 or reps <= 0:
        raise ValueError("hands and reps must be positive")
    engine = MusEngine()
    pairs = list(itertools.combinations(PARTICIPANTS, 2))
    results = {}
    for a, b in pairs:
        for order in [(a, b), (b, a)]:
            key = f"{order[0]}+{order[1]}"
            vacas = list()
            hand_wins = 0
            n = 0
            for r in range(reps):
                seed = int.from_bytes(sha256(f"{key}:{r}".encode()).digest()[:4], "big")
                res = run_match(engine, order, REF_MODEL, hands=hands, seed=seed)
                vacas.append(win_rate(res))
                hand_wins += res.hand_wins_a
                n += res.hands
                print(f"  {key} rep{r}: vacasA={res.vacas_a} vacasB={res.vacas_b} "
                      f"(win {win_rate(res):.3f})")
            results[key] = {
                "pair": order,
                "model_a": order[0],
                "model_b": order[1],
                "reps": reps,
                "hands": n,
                "hand_wins_a": hand_wins,
                "mean_win_rate": sum(vacas) / len(vacas),
                "per_rep": [round(v, 4) for v in vacas],
            }
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=MATCH_HANDS)
    ap.add_argument("--reps", type=int, default=REPS_PER_PAIR)
    ap.add_argument("--out", default="results.json")
    args = ap.parse_args()

    print(f"Participants: {PARTICIPANTS}")
    print(f"Reference opponent pair: {REF_MODEL} x2")
    print(f"hands/match={args.hands} reps/pair={args.reps}\n")
    t0 = time.time()
    results = run_all(args.hands, args.reps)
    with open(args.out, "w") as f:
        json.dump({"participants": PARTICIPANTS, "ref_model": REF_MODEL,
                   "hands": args.hands, "reps": args.reps, "results": results}, f,
                  indent=2)
    print(f"\nDone in {time.time()-t0:.1f}s -> {args.out}")


if __name__ == "__main__":
    main()
