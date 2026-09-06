"""Establish the skill floor by running non-LLM baselines (no API required).

CLI: python run_baseline.py [--hands N] [--reps R]
"""
from __future__ import annotations

import argparse
from hashlib import sha256

from baseline import HeuristicAgent, RandomAgent
from engine import MusEngine
from run_match import run_match


def run_pair(a_cls, b_cls, hands: int, reps: int, tag: str) -> float:
    if hands <= 0 or reps <= 0:
        raise ValueError("hands and reps must be positive")
    engine = MusEngine()
    total_a = total_b = 0
    # a_cls occupies team 0, b_cls occupies team 1
    def factory(name, model, seat=0, team=0):
        cls = a_cls if team == 0 else b_cls
        return cls(name, model, seat, team)
    for r in range(reps):
        seed = int.from_bytes(sha256(f"{tag}:{r}".encode()).digest()[:4], "big")
        res = run_match(engine, ('A', 'A'), 'B', hands=hands, seed=seed,
                        make_agent=factory)
        total_a += res.vacas_a
        total_b += res.vacas_b
        print(f"  {tag} rep{r}: {res.vacas_a} - {res.vacas_b}")
    wr = total_a / max(1, total_a + total_b)
    print(f"{tag}: win-rate={wr:.3f}  (vacas {total_a}-{total_b} over {reps} matches)\n")
    return wr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=12)
    ap.add_argument("--reps", type=int, default=5)
    args = ap.parse_args()
    print(f"Baseline floor: hands/match={args.hands}, reps={args.reps}\n")
    run_pair(RandomAgent, RandomAgent, args.hands, args.reps, "random vs random")
    run_pair(HeuristicAgent, HeuristicAgent, args.hands, args.reps, "heuristic vs heuristic")
    run_pair(HeuristicAgent, RandomAgent, args.hands, args.reps, "heuristic vs random")
    run_pair(RandomAgent, HeuristicAgent, args.hands, args.reps, "random vs heuristic")


if __name__ == "__main__":
    main()
