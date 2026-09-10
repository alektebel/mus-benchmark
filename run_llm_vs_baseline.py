"""LLM dyad vs baseline dyad -- the batch-1 experiment.

Design (answers "do we need 4 LLMs at once?"): NO. Mus is strictly turn-based
(only the active seat acts), so a match is inherently ONE api call at a time.
Team A = the model under test in BOTH its seats (a self-partnered dyad -- it
still can't see its partner's cards, so cooperation/signalling is exercised),
Team B = the heuristic floor. This isolates "can model X (paired with itself)
beat the baseline?" and ranks models by vacas won -- at half the cost and with
zero intra-match concurrency (the 429 storms came from parallel matches, so
matches run sequentially by default).

CLI:
  python run_llm_vs_baseline.py --models "deepseek-v4-flash,qwen3.8-flash" \
      --hands 12 --seeds 0,1,2 --out batch1.json
"""
from __future__ import annotations

import argparse
from random import Random
import json
import threading
import time

from mus_engine import MusEngine
from run_match_strict import run_match_strict, REASONING_MODE, THINK_BUDGET
from batch_runner import run_batch, write_progress as _write, PROGRESS_FILE


def run_job(job: dict, progress: dict, lock: threading.Lock) -> None:
    t0 = time.monotonic()
    partner, opponent = job["models"][1], job["opponent"]
    models = [job["models"][0], opponent, partner, opponent]
    with lock:
        job["status"] = "running"
        job["msg"] = "starting"
        _write(progress)
    def on_hand(hi, a, b, winner, va, vb):
        with lock:
            job.update(hand=hi, msg=f"hand {hi}/{job['hands']} running A={va} B={vb}")
            progress["done_hands"] += 1
            progress["running_a"] += a
            progress["running_b"] += b
            _write(progress)

    try:
        res = run_match_strict(MusEngine(Random(job["seed"])), models, hands=job["hands"],
                               seed=job["seed"], verbose=False, hand_callback=on_hand)
    except Exception as e:  # noqa: BLE001 -- loud, per-job failure
        with lock:
            job["status"] = "error"
            job["elapsed"] = round(time.monotonic() - t0, 1)
            job["msg"] = f"ERROR {type(e).__name__}: {e}"
            progress["log"].append(f"[{job['id']}] {job['msg']}")
            _write(progress)
        return
    with lock:
        job.update(status="done", vacas_llm=res["vacas_a"], vacas_base=res["vacas_b"],
                   hand_wins_llm=res["hand_wins_a"], hand_wins_base=res["hand_wins_b"],
                   usage=res["usage"], agents=res["agents"],
                   elapsed=round(time.monotonic() - t0, 1),
                   msg=f"done: LLM {res['vacas_a']}-{res['vacas_b']} baseline")
        progress["completed"] += 1
        progress["log"].append(f"[{job['id']}] {job['models'][0]} seed {job['seed']}: "
                               f"{res['vacas_a']}-{res['vacas_b']} "
                               f"(calls={res['usage']['calls']})")
        _write(progress)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True,
                    help="comma-separated model names for team A (each plays "
                         "both its seats vs the baseline dyad)")
    ap.add_argument("--pair", action="store_true",
                    help="instead: each model paired with the NEXT model in the "
                         "list as partners (exactly two; still vs baseline dyad)")
    ap.add_argument("--opponent", default="heuristic", choices=["heuristic", "random"])
    ap.add_argument("--hands", type=int, default=12)
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--workers", type=int, default=1,
                    help="parallel MATCHES; keep 1-2 to avoid provider 429s")
    ap.add_argument("--out", default="llm_vs_baseline.json")
    args = ap.parse_args()

    names = [m.strip() for m in args.models.split(",") if m.strip()]
    try:
        seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    except ValueError:
        ap.error("--seeds must contain comma-separated integers")
    if not seeds or args.hands <= 0 or args.workers <= 0:
        ap.error("provide at least one seed and positive --hands and --workers")
    if not names:
        ap.error("--models needs at least one model")
    jobs = []
    jid = 0
    if args.pair:
        if len(names) != 2:
            ap.error("--pair needs exactly 2 models")
        for s in seeds:
            jobs.append({"id": jid, "models": names, "hands": args.hands,
                         "seed": s, "opponent": args.opponent, "status": "queued",
                         "vacas_llm": None, "vacas_base": None, "elapsed": None,
                         "msg": "queued"})
            jid += 1
    else:
        for m in names:
            for s in seeds:
                jobs.append({"id": jid, "models": [m, m], "hands": args.hands,
                             "seed": s, "opponent": args.opponent,
                             "status": "queued", "vacas_llm": None,
                             "vacas_base": None, "elapsed": None, "msg": "queued"})
                jid += 1

    progress = {"status": "running", "started": time.time(), "total": len(jobs),
                "completed": 0, "done_hands": 0, "running_a": 0, "running_b": 0,
                "jobs": jobs, "log": [],
                "config": {"reasoning_mode": REASONING_MODE, "think_budget": THINK_BUDGET,
                           "opponent": args.opponent, "hands": args.hands}}
    _write(progress)
    print(f"LLM-vs-baseline: {len(jobs)} matches ({len(names)} models x {len(seeds)} seeds), "
          f"{args.workers} worker(s), opponent={args.opponent}, "
          f"reasoning={REASONING_MODE}, think_budget={THINK_BUDGET}")
    print(f"Progress -> {PROGRESS_FILE}\n")

    run_batch(jobs, args.workers, run_job, progress)
    progress["status"] = "error" if any(j["status"] == "error" for j in jobs) else "done"
    _write(progress)

    # ranking
    print("\n==== RANKING (vacas LLM vs baseline, summed over seeds) ====")
    by_model: dict[str, dict] = {}
    for j in jobs:
        if j["status"] != "done":
            print(f"  {j['models'][0]} seed {j['seed']}: {j['status']} -- {j['msg']}")
            continue
        m = by_model.setdefault(" + ".join(j["models"]) if args.pair else j["models"][0],
                                {"vacas": 0, "against": 0, "wins": 0, "matches": 0,
                                 "calls": 0, "fallbacks": 0, "tokens": 0})
        m["vacas"] += j["vacas_llm"]
        m["against"] += j["vacas_base"]
        m["wins"] += 1 if j["vacas_llm"] > j["vacas_base"] else 0
        m["matches"] += 1
        m["calls"] += j["usage"]["calls"]
        m["fallbacks"] += j["usage"]["fallbacks"]
        m["tokens"] += j["usage"]["tokens_in"] + j["usage"]["tokens_out"]
    rank = sorted(by_model.items(), key=lambda kv: kv[1]["vacas"], reverse=True)
    for i, (m, st) in enumerate(rank, 1):
        wr = st["vacas"] / max(1, st["vacas"] + st["against"])
        print(f"{i}. {m:32s} vacas {st['vacas']:3d}-{st['against']:3d} "
              f"(share {wr:.2f}) match-wins {st['wins']}/{st['matches']} "
              f"calls={st['calls']} fallbacks={st['fallbacks']} tok={st['tokens']}")

    results = [{"models": j["models"], "seed": j["seed"], "status": j["status"],
                "msg": j["msg"], "vacas_llm": j.get("vacas_llm"), "vacas_base": j.get("vacas_base"),
                "hand_wins_llm": j.get("hand_wins_llm"),
                "hand_wins_base": j.get("hand_wins_base"),
                "usage": j.get("usage"), "elapsed": j.get("elapsed")}
               for j in jobs]
    with open(args.out, "w") as f:
        json.dump({"config": progress["config"], "results": results}, f, indent=2)
    print(f"\nSaved -> {args.out}")
    if progress["status"] == "error":
        raise SystemExit(1)


if __name__ == "__main__":
    main()