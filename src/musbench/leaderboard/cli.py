"""`python -m musbench.leaderboard` -- roster, runs and the public score.

    list                      roster and how many rated matches each model has
    add ID --spec S [--name N] [--run]
                              register a model (and optionally play it now)
    schedule ID               the matches `run ID` would play (no API calls)
    run ID [--workers N]      play ID against every other roster model, every
                              seed, both seatings; append to the ledger
    score                     rate the ledger, rewrite README block + SVG + JSON

The ledger (benchmark/matches.jsonl) is append-only and committed; it is the
single source of truth for the score. `run` only plays matches the ledger
does not already hold, so it is safe to interrupt and re-run.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

from musbench.leaderboard import rating, render

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "benchmark" / "models.toml"
LEDGER = ROOT / "benchmark" / "matches.jsonl"


# ---------------------------------------------------------------- data ----
def load_config(path: Path = CONFIG) -> dict:
    cfg = tomllib.loads(path.read_text())
    bench = cfg.get("benchmark", {})
    models = cfg.get("model", [])
    ids = [m["id"] for m in models]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise SystemExit(f"duplicate model id(s) in {path}: {sorted(dup)}")
    return {"protocol": bench.get("protocol", "v1"),
            "hands": int(bench.get("hands", 8)),
            "seeds": [int(s) for s in bench.get("seeds", [0, 1, 2, 3])],
            "anchor": bench.get("anchor", ""),
            "bootstrap": int(bench.get("bootstrap", 2000)),
            "models": {m["id"]: {"name": m.get("name", m["id"]),
                                 "spec": m.get("spec", m["id"])}
                       for m in models}}


def load_ledger(path: Path = LEDGER) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def rated_matches(cfg: dict, ledger: list[dict]) -> list[dict]:
    """Same protocol, both teams on the roster, and a clean finish."""
    roster = set(cfg["models"])
    out = []
    for m in ledger:
        if m.get("protocol") != cfg["protocol"]:
            continue
        if m["team_a"] not in roster or m["team_b"] not in roster:
            continue
        if m.get("status", "done") not in ("done", "finished"):
            continue
        out.append(m)
    return out


def schedule(cfg: dict, ledger: list[dict], model_id: str) -> list[tuple[str, str, int]]:
    """Mirrored round robin of `model_id` vs the rest of the roster, minus
    what the ledger already holds for this protocol."""
    have = {(m["team_a"], m["team_b"], m["seed"]) for m in ledger
            if m.get("protocol") == cfg["protocol"]
            and m.get("status", "done") in ("done", "finished")}
    jobs = []
    for opp in cfg["models"]:
        if opp == model_id:
            continue
        for seed in cfg["seeds"]:
            for a, b in ((model_id, opp), (opp, model_id)):
                if (a, b, seed) not in have:
                    jobs.append((a, b, seed))
    return jobs


def _git_commit() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                               cwd=ROOT, capture_output=True, text=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def ledger_row(cfg: dict, a: str, b: str, seed: int, result: dict,
               status: str, commit: str) -> dict:
    from musbench.harness.tournament import match_metrics
    m = match_metrics(result)
    side = {"a": [x for x in result.get("agents", []) if x.get("seat") in (0, 2)],
            "b": [x for x in result.get("agents", []) if x.get("seat") in (1, 3)]}
    per_team = {f"{k}_{t}": sum(x.get(k, 0) for x in side[t])
                for k in ("fallbacks",) for t in "ab"}
    per_team |= {f"llm_calls_{t}": sum(x.get("calls", 0) for x in side[t] if x.get("is_llm"))
                 for t in "ab"}
    return per_team | {"protocol": cfg["protocol"], "team_a": a, "team_b": b, "seed": seed,
            "hands": m["hands_completed"], "piedras_a": m["piedras_a"],
            "piedras_b": m["piedras_b"], "vacas_a": m["vacas_a"],
            "vacas_b": m["vacas_b"], "llm_calls": m["llm_calls"],
            "fallbacks": m["fallbacks"], "status": status, "commit": commit,
            "spec_a": cfg["models"][a]["spec"], "spec_b": cfg["models"][b]["spec"]}


# ------------------------------------------------------------ commands ----
def cmd_list(cfg, ledger, _args):
    rated = rated_matches(cfg, ledger)
    print(f"protocol {cfg['protocol']} · {cfg['hands']} hands · seeds {cfg['seeds']}")
    for mid, m in cfg["models"].items():
        n = sum(1 for r in rated if mid in (r["team_a"], r["team_b"]))
        todo = len(schedule(cfg, ledger, mid))
        print(f"  {mid:28} {m['name']:22} spec={m['spec']:28} "
              f"rated={n:3}  missing={todo}")


def cmd_add(cfg, ledger, args):
    if args.id in cfg["models"]:
        raise SystemExit(f"{args.id!r} is already on the roster")
    block = (f'\n[[model]]\nid = {json.dumps(args.id)}\n'
             f'name = {json.dumps(args.name or args.id)}\n'
             f'spec = {json.dumps(args.spec or args.id)}\n')
    with open(CONFIG, "a") as f:
        f.write(block)
    print(f"added {args.id} to {CONFIG.relative_to(ROOT)}")
    cfg = load_config()
    jobs = schedule(cfg, ledger, args.id)
    print(f"{len(jobs)} matches to play "
          f"({len(cfg['models']) - 1} opponents x {len(cfg['seeds'])} seeds x 2 seatings)")
    if args.run:
        cmd_run(cfg, ledger, args)
    else:
        print(f"next: python -m musbench.leaderboard run {args.id}")


def cmd_schedule(cfg, ledger, args):
    if args.id not in cfg["models"]:
        raise SystemExit(f"{args.id!r} is not on the roster (benchmark/models.toml)")
    jobs = schedule(cfg, ledger, args.id)
    for a, b, s in jobs:
        print(f"  seed {s}: {a} (seats 0+2) vs {b} (seats 1+3)")
    print(f"{len(jobs)} matches x {cfg['hands']} hands")


def cmd_run(cfg, ledger, args):
    from musbench.harness.tournament import run_job
    if args.id not in cfg["models"]:
        raise SystemExit(f"{args.id!r} is not on the roster (benchmark/models.toml)")
    jobs = schedule(cfg, ledger, args.id)
    if not jobs:
        print("nothing to play: the ledger already holds the full schedule")
        return
    # subprocesses run `-m musbench.harness.kernel_match`; make src importable
    src = str(ROOT / "src")
    os.environ["PYTHONPATH"] = os.pathsep.join(
        p for p in (src, os.environ.get("PYTHONPATH")) if p)
    outdir = Path(args.out or tempfile.mkdtemp(prefix=f"mus-{args.id.replace(':', '_')}-"))
    outdir.mkdir(parents=True, exist_ok=True)
    commit = _git_commit()
    print(f"[leaderboard] {len(jobs)} matches -> raw results in {outdir}")
    from concurrent.futures import ThreadPoolExecutor, as_completed
    spec = lambda mid: cfg["models"][mid]["spec"]  # noqa: E731
    ok = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_job, (spec(a), spec(b)), cfg["hands"], s, outdir,
                          args.job_timeout): (a, b, s) for a, b, s in jobs}
        for fut in as_completed(futs):
            a, b, s = futs[fut]
            entry = fut.result()
            r = entry.get("result")
            status = entry.get("status", "failed")
            if r and r.get("hands_completed", 0) < cfg["hands"] and status in ("done", "finished"):
                status = "partial"
            if r:
                row = ledger_row(cfg, a, b, s, r, status, commit)
                with open(LEDGER, "a") as f:     # append as we go: crash-safe
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            ok += status in ("done", "finished")
            print(f"  seed {s} {a} vs {b}: {status}"
                  + (f" piedras {r.get('piedras_a')}-{r.get('piedras_b')}" if r else ""),
                  flush=True)
    print(f"[leaderboard] {ok}/{len(jobs)} rated. "
          f"next: python -m musbench.leaderboard score")


def cmd_score(cfg, ledger, args):
    rated = rated_matches(cfg, ledger)
    result = rating.rate(rated, anchor=cfg["anchor"], n_boot=cfg["bootstrap"])
    names = {k: v["name"] for k, v in cfg["models"].items()}
    unrated = [names[m] for m in cfg["models"] if m not in {r["model"] for r in result["rows"]}]
    svg_path = ROOT / args.svg
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(render.svg(result, names, cfg["protocol"]))
    (ROOT / args.json).write_text(json.dumps(
        {"protocol": cfg["protocol"], "anchor": cfg["anchor"],
         "seat_bias": result["seat_bias"], "n_matches": result["n_matches"],
         "n_boot": result["n_boot"], "top_separated": result.get("top_separated"),
         "unrated": unrated,
         "rows": [dict(r, name=names.get(r["model"], r["model"])) for r in result["rows"]]},
        indent=2, ensure_ascii=False) + "\n")
    readme = ROOT / args.readme
    readme.write_text(render.splice_readme(
        readme.read_text(), render.markdown(result, names, cfg["protocol"], args.svg)))
    for r in result["rows"]:
        print(f"  {r['rank']}. {names.get(r['model'], r['model']):22} "
              f"{r['score']:+6.2f}  [{r['ci_low']:+.2f}, {r['ci_high']:+.2f}]  "
              f"P(#1)={r['p_best']:.0%}  n={r['matches']}")
    if unrated:
        print(f"  not rated yet (no {cfg['protocol']} matches): {', '.join(unrated)}")
    print(f"wrote {args.readme}, {args.svg}, {args.json}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m musbench.leaderboard",
                                 description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("add")
    p.add_argument("id")
    p.add_argument("--spec", help="harness model spec (default: the id)")
    p.add_argument("--name", help="display name (default: the id)")
    p.add_argument("--run", action="store_true", help="play the schedule now")
    for name in ("schedule", "run"):
        q = sub.add_parser(name)
        q.add_argument("id")
    for q in (p, sub.choices["run"]):
        q.add_argument("--workers", type=int, default=1)
        q.add_argument("--job-timeout", type=float, default=7500)
        q.add_argument("--out", default=None, help="raw match JSON directory")
    s = sub.add_parser("score")
    s.add_argument("--readme", default="README.md")
    s.add_argument("--svg", default="docs/leaderboard.svg")
    s.add_argument("--json", default="benchmark/leaderboard.json")
    args = ap.parse_args(argv)
    cfg, ledger = load_config(), load_ledger()
    {"list": cmd_list, "add": cmd_add, "schedule": cmd_schedule,
     "run": cmd_run, "score": cmd_score}[args.cmd](cfg, ledger, args)


if __name__ == "__main__":
    main()
