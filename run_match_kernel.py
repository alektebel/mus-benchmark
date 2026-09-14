"""Kernel (real-time sena) mus harness entry point (CLI).

Experimental, runs alongside the strict harness. Same turn-gated engine and
same one-call-per-decision budget, but senas live on a virtual clock: idle
partners gesture DURING a deliberation window and the addressee sees them in
its NEXT window unless the TTL expires first (batched delivery). LLM seats
start gesture-silent and must DECLARE a signal policy; baseline seats carry
the rule-based reference policy (signalling floor).

CLI:
  python run_match_kernel.py --models "heuristic,random,heuristic,random" --hands 12 --seed 7
"""
from __future__ import annotations

import argparse
import json
import os
import re
from random import Random

from mus_engine import MusEngine
from agents import THINK_BUDGET, REASONING_MODE
from decision_log import DecisionLog
from virtual_kernel import run_match_kernel, KERNEL_WINDOW, KERNEL_WINDOW_JITTER


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models",
                    help="4 specs (comma-separated): model-name (nan), "
                         "provider:model, or heuristic/random for baseline seats. "
                         "Seats: [TeamA seat0, TeamB seat1, TeamA seat2, TeamB seat3]")
    ap.add_argument("--teams", nargs=2, metavar=("TEAM_A", "TEAM_B"), default=None,
                    help="2 specs, one per team; expands to 2v2 (A seats 0+2, "
                         "B seats 1+3).")
    ap.add_argument("--hands", type=int, default=12)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--window", type=float, default=None,
                    help=f"decision window in virtual time (default {KERNEL_WINDOW})")
    ap.add_argument("--jitter", type=float, default=None,
                    help=f"relative window jitter 0..1 (default {KERNEL_WINDOW_JITTER})")
    ap.add_argument("--out", default=None)
    ap.add_argument("--decisions", default=None,
                    help="JSONL path for the per-decision ground-truth record "
                         "(defaults to --out with a .jsonl suffix)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    if args.teams is not None:
        if args.models is not None:
            ap.error("provide exactly one of --models or --teams, not both")
        a, b = (t.strip() for t in args.teams)
        if not a or not b:
            ap.error("--teams requires two non-empty model specs")
        models = [a, b, a, b]
    else:
        if args.models is None:
            ap.error("provide --models (4 specs) or --teams (2 specs)")
        models = [m.strip() for m in args.models.split(",")]
        if len(models) != 4 or any(not m for m in models):
            ap.error("--models requires exactly four non-empty comma-separated specs")
    if args.hands <= 0:
        ap.error("--hands must be positive")
    import virtual_kernel
    if args.window is not None:
        virtual_kernel.KERNEL_WINDOW = args.window
    if args.jitter is not None:
        virtual_kernel.KERNEL_WINDOW_JITTER = args.jitter
    print(f"KERNEL match: {' vs '.join(models)}  "
          f"(teams: {models[0]}+{models[2]} | {models[1]}+{models[3]})")
    print(f"hands={args.hands} seed={args.seed} window={virtual_kernel.KERNEL_WINDOW} "
          f"jitter={virtual_kernel.KERNEL_WINDOW_JITTER} "
          f"reasoning={REASONING_MODE} think_budget={THINK_BUDGET}\n")
    dec_path = args.decisions
    if dec_path is None and args.out:
        dec_path = re.sub(r"\.json$", "", args.out) + ".jsonl"

    def _save(res):
        if not args.out:
            return
        tmp = args.out + ".tmp"
        with open(tmp, "w") as f:
            json.dump(res, f, indent=2, ensure_ascii=False)
        os.replace(tmp, args.out)      # never leave a half-written result

    with DecisionLog(dec_path) as dlog:
        # a partial result is rewritten after every hand, so a SIGKILL costs at
        # most the hand in flight -- the mirror run lost 3 matches to this.
        def on_hand(h, a, b, winner, va, vb):
            _save({"status": "running", "hands_completed": h,
                   "hands": args.hands, "models": list(models),
                   "vacas_a": va, "vacas_b": vb, "seed": args.seed})

        res = run_match_kernel(MusEngine(rng=Random(args.seed)), models,
                               hands=args.hands, seed=args.seed,
                               verbose=args.verbose, hand_callback=on_hand,
                               decision_log=dlog)
        if dlog.enabled:
            print(f"Decisions -> {dec_path} ({dlog.records} records)")
    print(f"\nResult: vacas {res['vacas_a']}-{res['vacas_b']}  "
          f"piedras {res['piedras_a']}-{res['piedras_b']}  "
          f"hands={res['hands_completed']}/{res['hands']} "
          f"status={res['status']}  clock={res['virtual_clock']}")
    if res.get("abort_reason"):
        print(f"ABORTED: {res['abort_reason']}")
    s = res["signals"]
    print(f"Señas: published={s['published']} caught={s['caught']} "
          f"missed={s['missed']}")
    print(f"Token usage: in={res['usage']['tokens_in']} "
          f"out={res['usage']['tokens_out']} (reasoning={res['usage']['reasoning']}) "
          f"calls={res['usage']['calls']} fallbacks={res['usage']['fallbacks']}"
          f"/{res['usage']['turns']} turns elapsed={res['elapsed']}s")
    if args.out:
        _save(res)
        print(f"Saved -> {args.out}")


if __name__ == "__main__":
    main()
