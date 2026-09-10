"""Head-to-head LLM tournament over the kernel harness (real-time senas).

Each job runs a 2v2 team match: model A occupies seats 0+2, model B seats
1+3. Both teams are LLMs, both start gesture-silent and must DECLARE signal
policies, and the engine enforces official (Fournier-aligned) mus: truthful
tengo/no-tengo, named-bet envite chains, ordago semantics, vaca = 40 piedras.
Nothing about the outcome is forced -- seeds fix the deals, the models fix
the play, and every number here traces to a saved JSON.

CLI:
  python run_tournament.py --hands 10 --workers 3 --out results/tournament
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from bench_results import is_publishable_match

# pairings as (team_a, team_b) in play order; both orientations get a match
DEFAULT_PAIRINGS = [
    ("deepseek-v4-flash", "glm5.3-flash"),
    ("glm5.3-flash", "deepseek-v4-flash"),
    ("deepseek-v4-flash", "qwen3.8-flash"),
    ("qwen3.8-flash", "deepseek-v4-flash"),
    ("glm5.3-flash", "qwen3.8-flash"),
    ("qwen3.8-flash", "glm5.3-flash"),
]


def run_job(pairing: tuple[str, str], hands: int, seed: int, outdir: Path,
            job_timeout: float) -> dict:
    a, b = pairing
    name = f"{a}__vs__{b}__seed{seed}"
    out = outdir / f"{name}.json"
    log = outdir / f"{name}.log"
    env = dict(os.environ,
               ALLOW_SENA_BLUFFS="1",
               MATCH_TIMEOUT="7200",
               NAN_TIMEOUT=os.environ.get("NAN_TIMEOUT", "75"),
               # truncated samples (finish=length) are stochastic: give each
               # decision a couple of extra resamples before falling back
               RESP_RETRIES=os.environ.get("RESP_RETRIES", "5"),
               # Abort early on cascade; post-hoc is_publishable_match still
               # marks silent finishes as degraded if the abort does not fire.
               MAX_FALLBACK_RATE=os.environ.get("MAX_FALLBACK_RATE", "0.20"),
               FALLBACK_MIN_TURNS=os.environ.get("FALLBACK_MIN_TURNS", "12"))
    cmd = [sys.executable, "-u", "run_match_kernel.py",
           "--teams", a, b, "--hands", str(hands), "--seed", str(seed),
           "--out", str(out), "--verbose"]
    t0 = time.time()
    with open(log, "w") as lf:
        try:
            p = subprocess.run(cmd, env=env, stdout=lf,
                               stderr=subprocess.STDOUT, timeout=job_timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    if not out.exists():
        return {"job": name, "team_a": a, "team_b": b, "seed": seed,
                "status": f"failed (rc={rc})", "wall": round(time.time() - t0, 1)}
    r = json.load(open(out))
    status = r.get("status", "done")
    # Post-hoc quality gate: rate-limit / circuit cascades finish as "done"
    # with almost no real LLM calls — mark them degraded so they never enter
    # the publishable leaderboard (see bench_results.is_publishable_match).
    m = match_metrics(r)
    if status in ("done", "finished") and not is_publishable_match(
            m["llm_calls"], m["fallbacks"], status):
        status = "degraded"
        r["status"] = status
        out.write_text(json.dumps(r, indent=2, ensure_ascii=False))
    return {"job": name, "team_a": a, "team_b": b, "seed": seed,
            "status": status,
            "wall": round(time.time() - t0, 1), "result": r}


def match_metrics(r: dict) -> dict:
    agents = r.get("agents", [])
    llm_calls = sum(a.get("calls", 0) for a in agents if a.get("is_llm"))
    return {
        "vacas_a": r.get("vacas_a"), "vacas_b": r.get("vacas_b"),
        "hands": r.get("hands"),
        "hand_wins": f"{r.get('hand_wins_a', 0)}-{r.get('hand_wins_b', 0)}",
        "senas_published": r.get("signals", {}).get("published", 0),
        "senas_caught": r.get("signals", {}).get("caught", 0),
        "senas_missed": r.get("signals", {}).get("missed", 0),
        "llm_calls": llm_calls,
        "fallbacks": r.get("usage", {}).get("fallbacks", 0),
        "rejections": sum(a.get("rejections", 0) for a in agents),
        "bluffs": sum(a.get("bluffs", 0) for a in agents),
        "elapsed_s": r.get("elapsed"),
    }


def write_summary(outdir: Path, entries: list[dict]) -> None:
    rows = []
    for e in entries:
        if not e.get("result"):
            rows.append({k: v for k, v in e.items() if k != "result"})
            continue
        rows.append({k: v for k, v in e.items() if k != "result"}
                    | {"metrics": match_metrics(e["result"]),
                       "policies": {a["name"]: a.get("policy")
                                    for a in e["result"]["agents"]
                                    if a.get("is_llm")}})
    (outdir / "summary.json").write_text(
        json.dumps({"entries": rows}, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairings", default=None,
                    help="comma-separated 'A vs B' pairs (default: the 3-model "
                         "round robin, both orientations)")
    ap.add_argument("--hands", type=int, default=10)
    ap.add_argument("--seeds", default="0,1,2,3,4,5")
    ap.add_argument("--workers", type=int, default=1,
                    help="parallel matches; keep at 1 unless the provider "
                         "tolerates concurrent chats (qwen caps at 5)")
    ap.add_argument("--job-timeout", type=float, default=7500)
    ap.add_argument("--out", default="results/tournament")
    args = ap.parse_args()

    if args.pairings:
        pairings = []
        for p in args.pairings.split(";"):
            a, _, b = p.strip().partition(" vs ")
            if a and b:
                pairings.append((a.strip(), b.strip()))
    else:
        pairings = list(DEFAULT_PAIRINGS)
    seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
    jobs = [(pairings[i % len(pairings)], seed)
            for i, seed in enumerate(seeds)]
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"[tournament] {len(jobs)} matches x {args.hands} hands, "
          f"workers={args.workers}", flush=True)
    entries = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_job, pairing, args.hands, seed, outdir,
                          args.job_timeout): (pairing, seed)
                for pairing, seed in jobs}
        for fut in as_completed(futs):
            pairing, seed = futs[fut]
            try:
                entry = fut.result()
            except Exception as e:
                entry = {"job": f"{pairing[0]}__vs__{pairing[1]}__seed{seed}",
                         "status": f"crash: {e}"}
            entries.append(entry)
            if entry.get("result"):
                m = match_metrics(entry["result"])
                print(f"[{time.time()-t0:.0f}s] {entry['job']}: "
                      f"vacas {m['vacas_a']}-{m['vacas_b']} "
                      f"(hands {m['hands']}, senas {m['senas_published']}/"
                      f"{m['senas_caught']} caught) wall={entry['wall']}s",
                      flush=True)
            else:
                print(f"[{time.time()-t0:.0f}s] {entry.get('job')}: "
                      f"{entry['status']} wall={entry.get('wall')}s", flush=True)
            write_summary(outdir, entries)
    ok = [e for e in entries if e.get("status") in ("done", "finished")]
    deg = [e for e in entries if e.get("status") == "degraded"]
    print(f"\n[tournament] {len(ok)}/{len(jobs)} publishable"
          f" ({len(deg)} degraded); summary -> {outdir/'summary.json'}",
          flush=True)


if __name__ == "__main__":
    main()
