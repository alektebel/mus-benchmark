"""Scouting experiment: does studying a rival's past hands help beat it?

    python -m musbench.leaderboard scout --rivals 2 --seeds 2       # plays (API spend)
    python -m musbench.leaderboard scout-report                     # the gain table

For every (scouter S, rival R, seed) the experiment plays two arms on the same
deals, both seatings:

  control   S vs R with plain v4-menu prompts (shared by S-scouts-R and
            R-scouts-S, since nobody scouts in it)
  scout     S first reads up to --scout-hands of R's hands from the source
            tournament's replays (anonymous "Player X" unless --named), writes a
            report, and plays with it in every prompt. R plays plain v4.

The gain for S is its piedras-per-hand margin in the scout arm minus the
control arm, paired by rival, seed and seating. Seeds start at 1000, so no
scouted hand shares a deal with the match.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from random import Random

ARMS = ("control", "anon", "named")


def _cli():
    from musbench.leaderboard import cli
    return cli


def plan(cfg, args) -> list[dict]:
    """Every match the experiment needs, control matches deduplicated."""
    ids = [m for m in cfg["models"] if not cfg["models"][m]["spec"].startswith("typesafe:")]
    exclude = set(filter(None, (args.exclude or "").split(",")))
    scouters = [m for m in (args.scouters.split(",") if args.scouters else ids)
                if m not in exclude]
    rng = Random(args.pick_seed)
    pairs = []
    if args.pairs:
        pairs = [tuple(p.split(":vs:")) for p in args.pairs.split(",")]
    else:
        for s in scouters:
            rivals = [m for m in cfg["models"] if m != s and m not in exclude]
            rng.shuffle(rivals)
            pairs += [(s, r) for r in rivals[:args.rivals]]
    seeds = list(range(args.seed_base, args.seed_base + args.seeds))
    arm = "named" if args.named else "anon"
    jobs, seen_ctrl = [], set()
    for s, r in pairs:
        for seed in seeds:
            for a, b in ((s, r), (r, s)):
                key = (frozenset((s, r)), seed, a)
                if key not in seen_ctrl:
                    seen_ctrl.add(key)
                    jobs.append({"arm": "control", "a": a, "b": b, "seed": seed,
                                 "scouter": "", "rival": ""})
                jobs.append({"arm": arm, "a": a, "b": b, "seed": seed,
                             "scouter": s, "rival": r})
    return jobs


def _key(row) -> tuple:
    return (row.get("arm"), row["team_a"], row["team_b"], row["seed"], row.get("scouter", ""))


def cmd_scout(cfg, ledger, args):
    cli = _cli()
    tag = args.tag
    src = cli.REPLAYS / args.source
    if not any(src.glob("*.json.gz")):
        raise SystemExit(f"no replays to scout from in {src}")
    done = {_key(m) for m in ledger if str(m.get("tournament", "")).startswith(tag + "-")
            and m.get("status") == "done"}
    jobs = [j for j in plan(cfg, args)
            if (j["arm"], j["a"], j["b"], j["seed"], j["scouter"]) not in done]
    n_ctrl = sum(j["arm"] == "control" for j in jobs)
    print(f"[scout] {len(jobs)} matches to play ({n_ctrl} control, "
          f"{len(jobs) - n_ctrl} scouting) from {src}", flush=True)
    if args.dry_run:
        for j in jobs:
            print(f"  {j['arm']:7} seed {j['seed']} {j['a']} vs {j['b']}"
                  + (f"  ({j['scouter']} scouts)" if j["scouter"] else ""))
        return
    _play(cfg, jobs, args, src)


def _play(cfg, jobs, args, src, retry=True):
    cli = _cli()
    from musbench.harness.tournament import run_job
    srcpath = str(cli.ROOT / "src")
    os.environ["PYTHONPATH"] = os.pathsep.join(
        p for p in (srcpath, os.environ.get("PYTHONPATH")) if p)
    commit = cli._git_commit()
    out_root = Path(args.out or cli.ROOT / "results" / args.tag)
    spec = lambda m: cfg["models"][m]["spec"]  # noqa: E731
    failed = []

    def submit(ex, j):
        arm = j["arm"]
        outdir = out_root / arm / (j["scouter"] or "nobody")
        outdir.mkdir(parents=True, exist_ok=True)
        extra = ()
        if arm != "control":
            label = cfg["models"][j["rival"]]["name"] if arm == "named" else "Player X"
            extra = ("--scout", "A" if j["scouter"] == j["a"] else "B",
                     "--scout-rival", j["rival"], "--scout-source", str(src),
                     "--scout-hands", args.scout_hands, "--scout-label", label)
        env = {"MENU_PROTOCOL": "v4-menu" if arm == "control" else "v4-scout"}
        return ex.submit(run_job, (spec(j["a"]), spec(j["b"])), cfg["hands"], j["seed"],
                         outdir, args.job_timeout, "musbench.harness.menu", extra, env)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {submit(ex, j): j for j in jobs}
        for fut in as_completed(futs):
            j = futs[fut]
            entry = fut.result()
            r = entry.get("result")
            status = entry.get("status", "failed")
            arm_cfg = cfg | {"tournament": f"{args.tag}-{j['arm']}",
                             "protocol": "v4-menu" if j["arm"] == "control" else "v4-scout"}
            if r:
                outdir = out_root / j["arm"] / (j["scouter"] or "nobody")
                row = cli.ledger_row(arm_cfg, j["a"], j["b"], j["seed"], r, status, commit)
                row |= {"arm": j["arm"], "scouter": j["scouter"], "rival": j["rival"]}
                row |= cli._save_replay(arm_cfg, j["a"], j["b"], j["seed"], r, outdir, commit)
                with open(cli.LEDGER, "a") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if status != "done":
                failed.append(j)
            print(f"  {j['arm']:7} seed {j['seed']} {j['a']} vs {j['b']}: {status}"
                  + (f" piedras {r.get('piedras_a')}-{r.get('piedras_b')}" if r else ""),
                  flush=True)
    retryable = [j for j in failed]
    if retryable and retry:
        print(f"[scout] replaying {len(retryable)} failed match(es) in 60 s", flush=True)
        time.sleep(60)
        _play(cfg, retryable, args, src, retry=False)


# ------------------------------------------------------------- report ----
def gains(ledger, tag: str, arm: str = "anon") -> list[dict]:
    """One row per scouting match that has its control twin."""
    ctrl = {(m["team_a"], m["team_b"], m["seed"]): m for m in ledger
            if m.get("tournament") == f"{tag}-control" and m.get("status") == "done"}
    out = []
    for m in ledger:
        if m.get("tournament") != f"{tag}-{arm}" or m.get("status") != "done":
            continue
        c = ctrl.get((m["team_a"], m["team_b"], m["seed"]))
        if not c:
            continue
        s = m["scouter"]
        sign = 1 if m["team_a"] == s else -1

        def margin(x):
            return sign * (x["piedras_a"] - x["piedras_b"]) / max(x["hands"], 1)
        out.append({"scouter": s, "rival": m["rival"], "seed": m["seed"],
                    "seating": "A" if sign == 1 else "B",
                    "scout": margin(m), "control": margin(c),
                    "gain": margin(m) - margin(c)})
    return out


def _ci(xs, n_boot=2000, seed=0):
    if len(xs) < 2:
        return (float("nan"), float("nan"))
    rng = Random(seed)
    ms = sorted(sum(rng.choice(xs) for _ in xs) / len(xs) for _ in range(n_boot))
    return ms[int(0.025 * n_boot)], ms[int(0.975 * n_boot)]


def cmd_scout_report(cfg, ledger, args):
    cli = _cli()
    rows = gains(ledger, args.tag, "named" if args.named else "anon")
    if not rows:
        print(f"[scout] no paired {args.tag} matches yet")
        return
    by = {}
    for r in rows:
        by.setdefault(r["scouter"], []).append(r["gain"])
    names = {k: v["name"] for k, v in cfg["models"].items()}
    allg = [r["gain"] for r in rows]
    lo, hi = _ci(allg)
    print(f"Scouting gain, piedras/hand (scout arm minus control, same deals), "
          f"{len(rows)} paired matches:")
    print(f"  {'all scouters':28} {sum(allg)/len(allg):+6.2f}  [{lo:+.2f}, {hi:+.2f}]  n={len(allg)}")
    table = []
    for s, g in sorted(by.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        lo, hi = _ci(g)
        table.append({"scouter": s, "gain": sum(g) / len(g), "ci": [lo, hi], "n": len(g)})
        print(f"  {names.get(s, s):28} {sum(g)/len(g):+6.2f}  [{lo:+.2f}, {hi:+.2f}]  n={len(g)}")
    # skills of the scouting seats, scout arm vs control, from the replays
    from musbench.leaderboard import replay, skills
    out = {"tag": args.tag, "matches": rows, "by_scouter": table, "skills": {}}
    for arm in ("control", "named" if args.named else "anon"):
        d = cli.REPLAYS / f"{args.tag}-{arm}"
        reps = [replay.read(p) for p in sorted(d.glob("*.json.gz"))] if d.exists() else []
        out["skills"][arm] = skills.compute(reps)
    path = cli.ROOT / "benchmark" / f"scout_{args.tag}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    print(f"wrote {path.relative_to(cli.ROOT)}")


def add_parsers(sub):
    sc = sub.add_parser("scout", help="scouting experiment: study a rival, then play it")
    sc.add_argument("--tag", default="scout-1")
    sc.add_argument("--source", default="elo-2", help="replay folder to scout from")
    sc.add_argument("--scouters", help="comma-separated ids (default: every LLM)")
    sc.add_argument("--rivals", type=int, default=2, help="rivals per scouter")
    sc.add_argument("--pairs", help="explicit 'scouter:vs:rival,...'")
    sc.add_argument("--exclude", help="ids to leave out")
    sc.add_argument("--seeds", type=int, default=2)
    sc.add_argument("--seed-base", type=int, default=1000)
    sc.add_argument("--scout-hands", type=int, default=12)
    sc.add_argument("--named", action="store_true", help="name the rival (biased arm)")
    sc.add_argument("--pick-seed", type=int, default=0)
    sc.add_argument("--workers", type=int, default=4)
    sc.add_argument("--job-timeout", type=float, default=7500)
    sc.add_argument("--out")
    sc.add_argument("--dry-run", action="store_true", help="list the matches, play nothing")
    sr = sub.add_parser("scout-report", help="scouting gain per model")
    sr.add_argument("--tag", default="scout-1")
    sr.add_argument("--named", action="store_true")
    return {"scout": cmd_scout, "scout-report": cmd_scout_report}
