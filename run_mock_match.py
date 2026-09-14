"""Full-pipeline match with a fake provider: zero API spend, complete audit.

    python run_mock_match.py --teams glm5.3-flash deepseek-v4-flash \\
        --hands 30 --seed 6 --turn-feed --memory notes --out results/mock

Everything above `requests.post` is the production path, so this validates the
prompts, the JSON contract, the engine, the señas bus and the decision log
exactly as a paid run would. What it does NOT validate is model behaviour --
the mock plays a threshold policy, so treat its scorecard as a pipeline check,
never as evidence about a model.

Writes, all under --out:
    match.json       the result
    match.jsonl      one ground-truth record per decision
    io.jsonl         every prompt and every raw completion, in order
    notes.json       every self-written vaca note, verbatim
    audit.txt        human-readable summary of the above
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from random import Random

import analysis
from decision_log import DecisionLog
from mock_provider import MockProvider
from mus_engine import MusEngine
import vaca_notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", nargs=2, default=["glm5.3-flash",
                                                 "deepseek-v4-flash"],
                    help="TEAM_A TEAM_B; A takes seats 0+2, B seats 1+3")
    ap.add_argument("--hands", type=int, default=30)
    ap.add_argument("--seed", type=int, default=6)
    ap.add_argument("--turn-feed", action="store_true",
                    help="seats see the raw JSON of every turn this vaca "
                         "instead of the harness-written rival dossier")
    ap.add_argument("--memory", choices=vaca_notes.VALID_MODES, default="off",
                    help="what crosses a vaca boundary")
    ap.add_argument("--out", default="results/mock")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    # set before virtual_kernel reads it
    os.environ["VACA_MEMORY"] = args.memory
    os.environ["KERNEL_LOG_IO"] = str(Path(args.out) / "io.jsonl")
    import importlib
    importlib.reload(vaca_notes)
    import virtual_kernel
    importlib.reload(virtual_kernel)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for stale in ("io.jsonl", "match.jsonl"):
        (out / stale).unlink(missing_ok=True)

    a, b = args.teams
    models = [a, b, a, b]
    engine = MusEngine(rng=Random(args.seed))

    print(f"MOCK match: {a} (seats 0+2) vs {b} (seats 1+3)")
    print(f"hands={args.hands} seed={args.seed} "
          f"within-vaca={'turn feed' if args.turn_feed else 'dossier'} "
          f"across-vaca={args.memory}\n")

    with MockProvider(models, engine, seed=args.seed) as mock, \
            DecisionLog(str(out / "match.jsonl")) as log:
        res = virtual_kernel.run_match_kernel(
            engine, models, hands=args.hands, seed=args.seed,
            verbose=args.verbose, decision_log=log,
            turn_feed=args.turn_feed,
            vaca_callback=lambda va, vb, ta, tb: print(
                f"  [VACA] -> {ta}-{tb}"))
        notes = _notes_of(virtual_kernel, res)

    (out / "match.json").write_text(json.dumps(res, indent=2,
                                               ensure_ascii=False))
    (out / "notes.json").write_text(json.dumps(notes, indent=2,
                                               ensure_ascii=False))

    recs = analysis.load(str(out / "match.jsonl"))
    report = _audit(res, recs, mock, notes, args)
    (out / "audit.txt").write_text(report)
    print("\n" + report)
    print(f"\nArtifacts -> {out}/  "
          f"(match.json, match.jsonl, io.jsonl, notes.json, audit.txt)")


def _notes_of(vk, res) -> list[dict]:
    return res.get("vaca_notes") or []


def _audit(res, recs, mock, notes, args) -> str:
    L = []
    L.append("=" * 72)
    L.append("AUDIT")
    L.append("=" * 72)
    L.append(f"status={res['status']} hands={res['hands_completed']}/"
             f"{res['hands']} vacas {res['vacas_a']}-{res['vacas_b']} "
             f"piedras {res['piedras_a']}-{res['piedras_b']}")
    u = res["usage"]
    L.append(f"llm calls={u['calls']} fallbacks={u['fallbacks']}/"
             f"{u['llm_turns']} llm turns  rejections="
             f"{sum(a['rejections'] for a in res['agents'])}")
    L.append(f"mock completions served={len(mock.transcript)}")
    decisions = [r for r in recs if r["kind"] == "decision"]
    L.append(f"decision records={len(decisions)} "
             f"hand records={len(recs) - len(decisions)}")
    L.append(f"self-written vaca notes={len(notes)}")
    L.append("")
    L.append(analysis.render(analysis.scorecard(recs), analysis.outcome(recs)))
    return "\n".join(L)


if __name__ == "__main__":
    main()
