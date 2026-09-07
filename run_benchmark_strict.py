"""Parallel strict-mus benchmark runner with live progress (writes progress.json).

Each job is one match (models + hands + seed). Jobs run concurrently via a
ThreadPoolExecutor. Every vaca/hand update is written to ``progress.json`` so a
dashboard can render it in real time.

CLI:
  python run_benchmark_strict.py --models a,b,c,d --hands 12 --seeds 0,1,2,3 --workers 6
"""
from __future__ import annotations

import argparse
from random import Random
import json
import threading
import time

from mus_engine import MusEngine
from run_match_strict import run_match_strict
from batch_runner import run_batch, write_progress as _write, PROGRESS_FILE


def generate_jobs(models: list[str], hands: int, seeds: list[int]) -> list[dict]:
    return [
        {"id": i, "models": models, "hands": hands, "seed": s, "status": "queued",
         "vacas_a": None, "vacas_b": None, "hand_wins_a": None, "hand_wins_b": None,
         "elapsed": None, "hand": 0, "msg": "queued"}
        for i, s in enumerate(seeds)
    ]


def run_job(job: dict, progress: dict, lock: threading.Lock) -> None:
    t0 = time.monotonic()
    engine = MusEngine(Random(job["seed"]))

    def on_vaca(va, vb, tot_a, tot_b):
        with lock:
            progress["log"].append(
                f"[job {job['id']}] VACA: +{va} A / +{vb} B (tot A={tot_a} B={tot_b})")
            job["msg"] = f"VACA! A={tot_a} B={tot_b}"
            _write(progress)

    def on_hand(hi, a, b, winner, va, vb):
        with lock:
            job["hand"] = hi
            job["msg"] = f"hand {hi}/{job['hands']} +{a}/+{b} running A={va} B={vb}"
            progress["done_hands"] += 1
            progress["running_a"] += a
            progress["running_b"] += b
            _write(progress)

    with lock:
        job["status"] = "running"
        job["msg"] = "starting"
        _write(progress)

    try:
        res = run_match_strict(engine, job["models"], hands=job["hands"], seed=job["seed"],
                               verbose=False, vaca_callback=on_vaca, hand_callback=on_hand)
    except Exception as e:  # noqa: BLE001
        with lock:
            job["status"] = "error"
            job["elapsed"] = round(time.monotonic() - t0, 1)
            job["msg"] = f"ERROR: {e}"
            _write(progress)
        return

    with lock:
        job["status"] = "done"
        job["vacas_a"] = res["vacas_a"]
        job["vacas_b"] = res["vacas_b"]
        job["hand_wins_a"] = res["hand_wins_a"]
        job["hand_wins_b"] = res["hand_wins_b"]
        job["elapsed"] = round(time.monotonic() - t0, 1)
        job["msg"] = f"done: vacas {res['vacas_a']}-{res['vacas_b']}"
        progress["completed"] += 1
        _write(progress)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="deepseek-v4-flash,qwen3.8-flash,glm5.3-flash,gemma4")
    ap.add_argument("--hands", type=int, default=12)
    ap.add_argument("--seeds", default="0,1,2,3")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="benchmark_strict.json")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",")]
    try:
        seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    except ValueError:
        ap.error("--seeds must contain comma-separated integers")
    if not seeds or args.hands <= 0 or args.workers <= 0:
        ap.error("provide at least one seed and positive --hands and --workers")
    if len(models) != 4 or not all(models):
        ap.error("--models needs exactly four nonempty seat names")
    jobs = generate_jobs(models, args.hands, seeds)

    progress = {
        "status": "running",
        "started": time.time(),
        "total": len(jobs),
        "completed": 0,
        "done_hands": 0,
        "running_a": 0,
        "running_b": 0,
        "jobs": jobs,
        "log": [],
    }
    _write(progress)
    print(f"Benchmark: {len(jobs)} matches, {args.workers} workers, "
          f"models={models}, hands={args.hands}")
    print(f"Progress -> {PROGRESS_FILE}\n")

    run_batch(jobs, args.workers, run_job, progress)
    progress["status"] = "error" if any(j["status"] == "error" for j in jobs) else "done"
    _write(progress)
    print(f"Matches finished: {progress['status']}.")

    results = [{key: j.get(key) for key in (
        "seed", "status", "msg", "vacas_a", "vacas_b", "hand_wins_a", "hand_wins_b", "elapsed")}
        for j in jobs]
    with open(args.out, "w") as f:
        json.dump({"models": models, "hands": args.hands, "results": results}, f, indent=2)
    print(f"Saved -> {args.out}")
    if progress["status"] == "error":
        raise SystemExit(1)


if __name__ == "__main__":
    main()