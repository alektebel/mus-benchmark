"""Reference scorecard: what the risk metrics look like for known policies.

Every number in `analysis.py` is a bare number until you know what a bad one
and a good one look like. These runs cost no API credits, so the reference can
be regenerated whenever the harness changes:

    python reference_card.py --hands 300

`eps:E:B` is HeuristicPolicy played as a mixed strategy -- E is the chance of a
random legal action, B the chance of pushing from a hand the thresholds would
give up on. Its bluff frequency is SET, so it is also the check that the
scorecard measures what it claims to.
"""
from __future__ import annotations

import argparse
import os
import tempfile
from random import Random

import analysis
from decision_log import DecisionLog
from mus_engine import MusEngine
from virtual_kernel import run_match_kernel

# each row: the policy under test, seated against the deterministic floor
ROWS = ["random", "eps:0.1:0.6", "eps:0.1:0.3", "eps:0.05:0", "heuristic"]
OPPONENT = "heuristic"


def measure(spec: str, hands: int, seed: int) -> tuple[dict, dict]:
    models = [spec, OPPONENT, spec, OPPONENT]
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "ref.jsonl")
        with DecisionLog(path) as log:
            run_match_kernel(MusEngine(rng=Random(seed)), models, hands=hands,
                             seed=seed, decision_log=log,
                             vaca_callback=lambda *a: None)
        recs = analysis.load(path)
    cards = analysis.scorecard(recs)
    key = spec if spec in cards else next(iter(cards))
    return cards[key], analysis.outcome(recs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hands", type=int, default=300)
    ap.add_argument("--seed", type=int, default=12)
    args = ap.parse_args()

    print(f"Reference policies vs {OPPONENT}, {args.hands} hands, "
          f"seed {args.seed}. No API calls.\n")
    hdr = (f"{'policy':<16}{'aggr':>7}{'str@bet':>9}{'weakbet':>9}"
           f"{'bluff':>8}{'bl.succ':>9}{'folderr':>9}{'payoff':>8}{'pd/hand':>9}")
    print(hdr)
    print("-" * len(hdr))
    for spec in ROWS:
        c, o = measure(spec, args.hands, args.seed)

        def pc(v):
            return "   --" if v is None else f"{v * 100:5.1f}"
        print(f"{spec:<16}{pc(c['aggression_rate']):>7}"
              f"{(c['avg_strength_when_betting'] or 0):9.3f}"
              f"{pc(c['weak_hand_bet_rate']):>9}"
              f"{pc(c['bluff_rate']):>8}"
              f"{pc(c['bluff_success']):>9}"
              f"{pc(c['fold_error_rate']):>9}"
              f"{pc(c['payoff_rate']):>8}"
              f"{o['piedras_diff_per_hand']:+9.2f}")
    print("\naggr=aggression rate  str@bet=mean hand strength when betting")
    print("weakbet=share of weak hands it bets  bluff=share of its bets "
          "that are bluffs")
    print("folderr=folded a lance it would have won  payoff=called one it lost")
    print("pd/hand=piedras per hand vs the floor")


if __name__ == "__main__":
    main()
