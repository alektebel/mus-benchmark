"""Shared batch-execution scaffolding for parallel benchmark runners.

Both experiment runners (`run_benchmark_strict`, `run_llm_vs_baseline`) kick
off concurrent matches and stream status to `progress.json`. This module owns
the thread-pool so runners only supply their per-job callback, their job list
and the shared progress dict.

Writes stay owned by the caller (via its ``_write``), so progress refreshes are
patchable in tests.
"""
from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

PROGRESS_FILE = os.environ.get("PROGRESS_FILE", "progress.json")


def write_progress(progress: dict) -> None:
    tmp = PROGRESS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(progress, f, indent=2)
    os.replace(tmp, PROGRESS_FILE)


def run_batch(jobs: list[dict], workers: int, run_job,
              progress: dict) -> dict:
    """Run each job concurrently; ``run_job(job, progress, lock)`` mutates the
    shared ``progress`` dict under a lock. Returns ``progress`` when finished."""
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(run_job, job, progress, lock) for job in jobs]
        for f in as_completed(futs):
            f.result()
    return progress