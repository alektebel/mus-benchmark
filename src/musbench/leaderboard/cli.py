"""`python -m musbench.leaderboard` -- roster, runs and the public score.

    list                      roster and how many rated matches each model has
    add ID --spec S [--name N] [--run]
                              register a model (and optionally play it now)
    schedule ID               the matches `run ID` would play (no API calls)
    run ID [--workers N]      play ID against every other roster model, every
                              seed, both seatings; append to the ledger
    score                     rate the ledger, rewrite README block + SVG + JSON
    icon SLUG                 download a LobeHub logo into benchmark/icons/
    scout [--dry-run]         scouting experiment (see leaderboard/scouting.py)
    scout-report              scouting gain per model, scout arm minus control

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
import time
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

from musbench.leaderboard import rating, render

ROOT = Path(__file__).resolve().parents[3]
HARNESS_MODULES = {"kernel": "musbench.harness.kernel_match",
                   "menu": "musbench.harness.menu"}
# MUSBENCH_CONFIG points at another roster (e.g. benchmark/models-elo2.toml)
# without touching the published one.
CONFIG = Path(os.environ.get("MUSBENCH_CONFIG") or ROOT / "benchmark" / "models.toml")
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
            "harness": bench.get("harness", "kernel"),
            "hands": int(bench.get("hands", 8)),
            "seeds": [int(s) for s in bench.get("seeds", [0, 1, 2, 3])],
            "anchor": bench.get("anchor", ""),
            "start_elo": float(bench.get("start_elo", 1000)),
            "tournament": bench.get("tournament", ""),
            "bootstrap": int(bench.get("bootstrap", 2000)),
            "models": {m["id"]: {"name": m.get("name", m["id"]),
                                 "spec": m.get("spec", m["id"]),
                                 **{k: m[k] for k in ("provider", "provider_icon",
                                                      "model_icon") if k in m}}
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
        if cfg.get("tournament") and m.get("tournament") != cfg["tournament"]:
            continue                      # a fresh tournament: everyone starts level
        out.append(m)
    return out


def schedule(cfg: dict, ledger: list[dict], model_id: str,
             vs: list[str] | None = None) -> list[tuple[str, str, int]]:
    """Mirrored round robin of `model_id` vs the rest of the roster (or only
    the opponents in `vs`), minus what the ledger already holds."""
    have = {(m["team_a"], m["team_b"], m["seed"])
            for m in rated_matches(cfg, ledger)}
    jobs = []
    for opp in cfg["models"]:
        if opp == model_id or (vs and opp not in vs):
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
    return per_team | {"protocol": cfg["protocol"], "tournament": cfg.get("tournament", ""),
                       "team_a": a, "team_b": b, "seed": seed,
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
    jobs = schedule(cfg, ledger, args.id, _vs(args))
    for a, b, s in jobs:
        print(f"  seed {s}: {a} (seats 0+2) vs {b} (seats 1+3)")
    print(f"{len(jobs)} matches x {cfg['hands']} hands")


def _vs(args) -> list[str] | None:
    v = getattr(args, "vs", None)
    return [x.strip() for x in v.split(",") if x.strip()] if v else None


def cmd_run(cfg, ledger, args):
    if args.id not in cfg["models"]:
        raise SystemExit(f"{args.id!r} is not on the roster (benchmark/models.toml)")
    jobs = schedule(cfg, ledger, args.id, _vs(args))
    if not jobs:
        print("nothing to play: the ledger already holds the full schedule")
        return
    outdir = Path(args.out or tempfile.mkdtemp(prefix=f"mus-{args.id.replace(':', '_')}-"))
    ok = run_jobs(cfg, jobs, args.workers, outdir, args.job_timeout)
    print(f"[leaderboard] {ok}/{len(jobs)} rated. "
          f"next: python -m musbench.leaderboard score")


def run_jobs(cfg, jobs, workers, outdir: Path, job_timeout: float,
             retry: bool = True) -> int:
    """Play (team_a, team_b, seed) jobs, appending each finish to the ledger."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from musbench.harness.tournament import run_job
    # subprocesses run `-m musbench.harness.*`; make src importable
    src = str(ROOT / "src")
    os.environ["PYTHONPATH"] = os.pathsep.join(
        p for p in (src, os.environ.get("PYTHONPATH")) if p)
    outdir.mkdir(parents=True, exist_ok=True)
    commit = _git_commit()
    print(f"[leaderboard] {len(jobs)} matches -> raw results in {outdir}", flush=True)
    spec = lambda mid: cfg["models"][mid]["spec"]  # noqa: E731
    module = HARNESS_MODULES[cfg["harness"]]
    if cfg["protocol"] in ("v3-menu", "v4-menu"):   # read by the subprocess
        os.environ["MENU_PROTOCOL"] = cfg["protocol"]
    ok = 0
    failed: list[tuple] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_job, (spec(a), spec(b)), cfg["hands"], s, outdir,
                          job_timeout, module): (a, b, s) for a, b, s in jobs}
        for fut in as_completed(futs):
            a, b, s = futs[fut]
            entry = fut.result()
            r = entry.get("result")
            status = entry.get("status", "failed")
            if r and r.get("hands_completed", 0) < cfg["hands"] and status in ("done", "finished"):
                status = "partial"
            if r:
                row = ledger_row(cfg, a, b, s, r, status, commit)
                row |= _save_replay(cfg, a, b, s, r, outdir, commit)
                with open(LEDGER, "a") as f:     # append as we go: crash-safe
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            ok += status in ("done", "finished")
            if status in ("provider_error", "no_answer") or str(status).startswith("failed"):
                failed.append((a, b, s))
            print(f"  seed {s} {a} vs {b}: {status}"
                  + (f" piedras {r.get('piedras_a')}-{r.get('piedras_b')}" if r else ""),
                  flush=True)
    if failed and retry:
        print(f"[leaderboard] replaying {len(failed)} provider failure(s) in 60 s", flush=True)
        time.sleep(60)
        ok += run_jobs(cfg, failed, workers, outdir / "retry", job_timeout, retry=False)
    return ok


REPLAYS = ROOT / "benchmark" / "replays"


def _save_replay(cfg, a, b, seed, result, outdir: Path, commit: str) -> dict:
    """Write benchmark/replays/<tournament>/<match_id>.json.gz for this match."""
    from datetime import datetime, timezone
    from musbench.harness.tournament import _safe
    from musbench.leaderboard import replay
    spec = lambda mid: cfg["models"][mid]["spec"]  # noqa: E731
    dec = outdir / f"{_safe(spec(a))}__vs__{_safe(spec(b))}__seed{seed}.jsonl"
    tag = cfg.get("tournament") or cfg["protocol"]
    base = f"{tag}-{_safe(a)}-vs-{_safe(b)}-s{seed}"
    match_id, n = base, 1
    while (REPLAYS / tag / f"{match_id}.json.gz").exists():  # noqa: B007
        n += 1
        match_id = f"{base}-r{n}"          # a replay of an aborted attempt
    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
    seats = [{"seat": i, "team": "A" if i % 2 == 0 else "B",
              "model": (a if i % 2 == 0 else b),
              "spec": spec(a if i % 2 == 0 else b),
              "name": cfg["models"][a if i % 2 == 0 else b]["name"]} for i in range(4)]
    rp = replay.build(result, replay.load_decisions(dec), match_id=match_id,
                      tournament=tag, seats=seats, commit=commit,
                      finished_at=finished)
    path = replay.write(rp, REPLAYS)
    try:
        rel = str(path.relative_to(ROOT))
    except ValueError:
        rel = str(path)
    return {"match_id": match_id, "finished_at": finished, "replay": rel}


def _done_games(cfg, ledger) -> dict[tuple, set]:
    """(x, y) sorted -> seeds with BOTH seatings finished cleanly."""
    from musbench.leaderboard import elo
    out: dict[tuple, set] = {}
    for g in elo.pair_games(rated_matches(cfg, ledger)):
        out.setdefault((g["x"], g["y"]), set()).add(g["seed"])
    return out


def _explicit_pairs(v: str) -> list[tuple[str, str]]:
    out = []
    for item in _split(v):
        a, _, b = item.partition(":vs:")
        if not b:
            raise SystemExit(f"--pairs items look like 'a:vs:b', got {item!r}")
        out.append((a.strip(), b.strip()))
    return out


def swiss_pairings(ratings: dict[str, float], played: dict[tuple, set],
                   pool: list[str], seed: int = 0) -> list[tuple[str, str]]:
    """Pair models of similar Elo, avoiding repeat pairings when possible.
    Equal ratings (e.g. round 1, everyone at the start value) are ordered at
    random so the opening pairings are not just roster order."""
    import random as _r
    rng = _r.Random(seed)
    order = sorted(pool, key=lambda m: (-ratings.get(m, 1000.0), rng.random()))
    free, pairs = list(order), []
    while len(free) > 1:
        m = free.pop(0)
        opp = min(free, key=lambda o: (len(played.get(tuple(sorted((m, o))), ())),
                                       abs(ratings.get(m, 1000) - ratings.get(o, 1000))))
        free.remove(opp)
        pairs.append((m, opp))
    return pairs


PROBE = ('Mus test. You hold rey, rey, caballo, sota (31, juego). Options: 1. mus '
         '2. no hay mus. Reply with JSON only: {"choice": <1-2>, "why": "<short>"}')


def probe(cfg, mid) -> tuple[bool, str]:
    """One tiny call: is this model's provider up and within quota right now?"""
    from musbench.agents import cli_seat
    from musbench.agents.core import _make_agent
    try:
        agent = _make_agent(cfg["models"][mid]["spec"], 0, 0, 0)
        if not getattr(agent, "is_llm", False):
            return True, "offline"
        old = cli_seat.CLI_TIMEOUT
        cli_seat.CLI_TIMEOUT = 120
        try:
            if getattr(agent, "provider", "") == "typesafe":
                from musbench.harness.menu import _jev_choose
                ok = _jev_choose(agent, PROBE, ["mus", "no hay mus"]) is not None
            else:
                ok = isinstance(agent.decide(PROBE), dict)
        finally:
            cli_seat.CLI_TIMEOUT = old
        return ok, "ok" if ok else "no valid answer"
    except Exception as e:                      # noqa: BLE001 -- report and sit out
        return False, f"{type(e).__name__}: {str(e)[-160:]}"


def available(cfg, pool: list[str]) -> list[str]:
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(pool) or 1) as ex:
        res = dict(zip(pool, ex.map(lambda m: probe(cfg, m), pool)))
    for m, (ok, why) in res.items():
        if not ok:
            print(f"[swiss] {m} sits out this round: {why}", flush=True)
    return [m for m in pool if res[m][0]]


def choose_bye(pool: list[str], games: dict[str, int], seed: int) -> str:
    """With an odd field, the model with the most games so far sits out."""
    import random as _r
    rng = _r.Random(seed)
    return max(pool, key=lambda m: (games.get(m, 0), rng.random()))


def cmd_swiss(cfg, ledger, args):
    from musbench.leaderboard import elo
    exclude = set(_split(args.exclude))
    roster = [m for m in cfg["models"] if m not in exclude]
    for rnd in range(1, args.rounds + 1):
        ledger = load_ledger()
        rated = rated_matches(cfg, ledger)
        games = elo.pair_games(rated)
        ratings = elo.fit(games, cfg["anchor"], start=cfg["start_elo"])
        ratings = {m: ratings.get(m, cfg["start_elo"]) for m in roster}
        played = _done_games(cfg, ledger)
        pool = roster if getattr(args, "no_probe", False) else available(cfg, roster)
        if len(pool) < 2:
            print("[swiss] fewer than two models available; waiting 10 minutes", flush=True)
            time.sleep(600)
            continue
        counts: dict[str, int] = {}
        for g in games:
            counts[g["x"]] = counts.get(g["x"], 0) + 1
            counts[g["y"]] = counts.get(g["y"], 0) + 1
        if len(pool) % 2:
            bye = choose_bye(pool, counts, rnd)
            print(f"[swiss] bye this round: {bye}", flush=True)
            pool = [m for m in pool if m != bye]
        pairs = (_explicit_pairs(args.pairs) if args.pairs and rnd == 1
                 else swiss_pairings(ratings, played, pool, seed=rnd))
        finished = {(m["team_a"], m["team_b"], m["seed"]) for m in rated}
        jobs = []
        for x, y in pairs:
            have = played.get(tuple(sorted((x, y))), set())
            seeds = [s for s in range(10_000) if s not in have][:args.games]
            for s in seeds:
                # a half-played game only needs its missing seating
                jobs += [j for j in ((x, y, s), (y, x, s)) if j not in finished]
        print(f"\n[swiss] round {rnd}/{args.rounds}: " + ", ".join(
            f"{x} ({ratings.get(x, 1000):.0f}) v {y} ({ratings.get(y, 1000):.0f})"
            for x, y in pairs), flush=True)
        outdir = Path(args.out) / f"round{rnd}" if args.out else Path(
            tempfile.mkdtemp(prefix="mus-swiss-"))
        run_jobs(cfg, jobs, args.workers, outdir, args.job_timeout)
        cmd_elo(cfg, load_ledger(), args)


def cmd_elo(cfg, ledger, args):
    from musbench.leaderboard import elo
    rated = rated_matches(cfg, ledger)
    res = elo.rate(rated, cfg["anchor"], n_boot=getattr(args, "boot", 500) or 500,
                   start=cfg["start_elo"])
    live = elo.incremental(elo.pair_games(rated), start=cfg["start_elo"])
    names = {k: v["name"] for k, v in cfg["models"].items()}
    print(f"Elo over {res['games']} mirrored games (everyone starts at "
          f"{cfg['start_elo']:.0f}; {cfg['anchor'] or 'field mean'} pinned there):")
    print(f"  {'':28} {'fit':>6}  {'95% CI':>14}  {'live':>5}")
    seen = {r["model"] for r in res["rows"]}
    for m in cfg["models"]:
        if m not in seen:                 # no games yet: still at the start
            res["rows"].append({"rank": len(res["rows"]) + 1, "model": m,
                                "elo": cfg["start_elo"], "ci_low": cfg["start_elo"],
                                "ci_high": cfg["start_elo"], "games": 0,
                                "record": "0-0-0", "per_hand": 0.0, "p_best": 0.0})
    for r in res["rows"]:
        print(f"  {r['rank']:2}. {names.get(r['model'], r['model']):24} "
              f"{r['elo']:6.0f}  [{r['ci_low']:5.0f}, {r['ci_high']:5.0f}]  "
              f"{live.get(r['model'], cfg['start_elo']):5.0f}  "
              f"games {r['games']:3}  W-L-D {r['record']:8}  "
              f"{r['per_hand']:+5.2f} piedras/hand  P(#1) {r['p_best']:.0%}", flush=True)


def _split(v) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def cmd_score(cfg, ledger, args):
    if cfg.get("tournament"):
        return score_elo(cfg, ledger, args)
    rated = rated_matches(cfg, ledger)
    result = rating.rate(rated, anchor=cfg["anchor"], n_boot=cfg["bootstrap"])
    meta = {k: render._meta(cfg["models"], k) for k in cfg["models"]}
    names = {k: v["name"] for k, v in meta.items()}
    unrated = [names[m] for m in cfg["models"] if m not in {r["model"] for r in result["rows"]}]
    svg_path = ROOT / args.svg
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(render.svg(result, meta, cfg["protocol"]))
    (ROOT / args.json).write_text(json.dumps(
        {"protocol": cfg["protocol"], "anchor": cfg["anchor"],
         "seat_bias": result["seat_bias"], "n_matches": result["n_matches"],
         "n_boot": result["n_boot"], "top_separated": result.get("top_separated"),
         "unrated": unrated,
         "rows": [dict(r, **{k: meta.get(r["model"], {}).get(k) for k in
                            ("name", "provider", "provider_icon", "model_icon")})
                  for r in result["rows"]]},
        indent=2, ensure_ascii=False) + "\n")
    readme = ROOT / args.readme
    readme.write_text(render.splice_readme(
        readme.read_text(), render.markdown(result, meta, cfg["protocol"], args.svg)))
    for r in result["rows"]:
        print(f"  {r['rank']}. {names.get(r['model'], r['model']):22} "
              f"{r['score']:+6.2f}  [{r['ci_low']:+.2f}, {r['ci_high']:+.2f}]  "
              f"P(#1)={r['p_best']:.0%}  n={r['matches']}")
    if unrated:
        print(f"  not rated yet (no {cfg['protocol']} matches): {', '.join(unrated)}")
    print(f"wrote {args.readme}, {args.svg}, {args.json}")


def _rounded(row: dict) -> dict:
    """Short, platform-stable floats: last-digit noise differs across Python
    versions and would make the committed JSON flap in CI."""
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()}


def _tournament_replays(cfg, ledger) -> list[dict]:
    """Full replays of this tournament's rated matches, for the skill panels."""
    from musbench.leaderboard import replay
    ids = {m.get("match_id") for m in rated_matches(cfg, ledger)}
    out = []
    for row in ledger:
        if row.get("match_id") in ids and row.get("replay"):
            path = ROOT / row["replay"]
            if path.exists():
                out.append(replay.read(path))
    return out


def score_elo(cfg, ledger, args):
    """Elo leaderboard: README block, SVG, JSON, and the per-game history."""
    from musbench.leaderboard import elo
    rated = rated_matches(cfg, ledger)
    games = elo.pair_games(rated)
    res = elo.rate(rated, cfg["anchor"], n_boot=min(cfg["bootstrap"], 1000),
                   start=cfg["start_elo"])
    live = elo.incremental(games, start=cfg["start_elo"])
    meta = {k: render._meta(cfg["models"], k) for k in cfg["models"]}
    tag = cfg["tournament"]
    from musbench.leaderboard import board, skills as skills_mod
    sk = skills_mod.compute(_tournament_replays(cfg, ledger))
    svg_path = ROOT / args.svg
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    rel = Path(args.svg).parent
    paths = {"overall": args.svg, "speed": str(rel / "speed.svg"),
             "heatmap": str(rel / "heatmap.svg"), "skills": str(rel / "skills.svg"),
             "fastest": str(rel / "fastest.svg"), "banner": str(rel / "banner.svg")}
    specs = {k: v["spec"] for k, v in cfg["models"].items()}
    updated = max((m.get("finished_at") or "" for m in rated), default="")[:10]
    if res["rows"]:
        lead = res["rows"][0]
        (ROOT / paths["banner"]).write_text(
            board.banner_svg(meta[lead["model"]]["name"], lead["elo"], res["games"]))
    (ROOT / paths["fastest"]).write_text(board.fastest_svg(res["rows"], meta, sk, specs))
    svg_path.write_text(board.overall_svg(res["rows"], meta, cfg["start_elo"], tag))
    (ROOT / paths["speed"]).write_text(board.speed_svg(res["rows"], meta, sk))
    (ROOT / paths["heatmap"]).write_text(board.heatmap_svg(sk, meta, skills_mod.SKILLS))
    (ROOT / paths["skills"]).write_text(board.skills_svg(sk, meta, skills_mod.SKILLS))
    hist = elo.history(games, list(cfg["models"]), start=cfg["start_elo"],
                       anchor=cfg["anchor"])
    hist_path = ROOT / "benchmark" / f"elo_history_{tag}.jsonl"
    hist_path.write_text("".join(json.dumps(h, ensure_ascii=False) + "\n" for h in hist))
    (ROOT / args.json).write_text(json.dumps(
        {"tournament": tag, "protocol": cfg["protocol"], "start_elo": cfg["start_elo"],
         "games": res["games"], "n_boot": res["n_boot"],
         "rows": [dict(_rounded(r), live=round(live.get(r["model"], cfg["start_elo"]), 1),
                       **{k: meta[r["model"]].get(k) for k in
                          ("name", "provider", "provider_icon", "model_icon")})
                  for r in res["rows"]]}, indent=2, ensure_ascii=False) + "\n")
    readme = ROOT / args.readme
    readme.write_text(render.splice_readme(
        readme.read_text(), board.markdown(res, live, meta, sk, cfg, paths,
                                           render.START, render.END, updated=updated)))
    cmd_elo(cfg, ledger, args)
    print(f"wrote {args.readme}, {args.svg}, {args.json}, {hist_path.relative_to(ROOT)}")


def cmd_backfill(cfg, ledger, args):
    """Write replays for this tournament's ledger rows that lack one, from
    the raw harness output in --dir (match JSON + decision JSONL)."""
    from musbench.harness.tournament import _safe
    raw = Path(args.dir)
    changed = 0
    for row in ledger:
        if row.get("replay") or row.get("tournament") != cfg.get("tournament"):
            continue
        a, b, seed = row["team_a"], row["team_b"], row["seed"]
        if a not in cfg["models"] or b not in cfg["models"]:
            continue
        name = f"{_safe(row.get('spec_a') or cfg['models'][a]['spec'])}__vs__" \
               f"{_safe(row.get('spec_b') or cfg['models'][b]['spec'])}__seed{seed}"
        hits = list(raw.rglob(name + ".json"))
        if not hits:
            print(f"  no raw files for {name}")
            continue
        result = json.loads(hits[0].read_text())
        row |= _save_replay(cfg, a, b, seed, result, hits[0].parent,
                            row.get("commit", "unknown"))
        changed += 1
        print(f"  {row['match_id']} -> {row['replay']}")
    if changed:
        LEDGER.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ledger))
    print(f"backfilled {changed} replay(s)")


def cmd_icon(cfg, ledger, args):
    from musbench.leaderboard import icons
    print(f"saved {icons.fetch(args.slug).relative_to(ROOT)}")


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
        q.add_argument("--vs", help="only these opponents (comma-separated ids)")
    for q in (p, sub.choices["run"]):
        q.add_argument("--workers", type=int, default=1)
        q.add_argument("--job-timeout", type=float, default=7500)
        q.add_argument("--out", default=None, help="raw match JSON directory")
    sw = sub.add_parser("swiss", help="Swiss rounds: pair models of similar Elo")
    sw.add_argument("--rounds", type=int, default=1)
    sw.add_argument("--games", type=int, default=2,
                    help="mirrored games (2 matches each) per pairing per round")
    sw.add_argument("--exclude", help="roster ids to sit out (comma-separated)")
    sw.add_argument("--pairs", help="round-1 pairings, e.g. 'a:vs:b,c:vs:d'")
    sw.add_argument("--no-probe", action="store_true",
                    help="skip the per-round availability check")
    sw.add_argument("--workers", type=int, default=4)
    sw.add_argument("--job-timeout", type=float, default=7500)
    sw.add_argument("--out", default=None)
    e = sub.add_parser("elo", help="print the Elo table")
    e.add_argument("--boot", type=int, default=500)
    sub.add_parser("check", help="probe every roster model once (credentials, quota)")
    bf = sub.add_parser("backfill", help="write missing replays from raw harness output")
    bf.add_argument("dir")
    i = sub.add_parser("icon", help="download a LobeHub logo, e.g. perplexity-color")
    i.add_argument("slug")
    s = sub.add_parser("score")
    s.add_argument("--readme", default="README.md")
    s.add_argument("--svg", default="docs/leaderboard.svg")
    s.add_argument("--json", default="benchmark/leaderboard.json")
    from musbench.leaderboard import scouting
    scout_cmds = scouting.add_parsers(sub)
    args = ap.parse_args(argv)
    cfg, ledger = load_config(), load_ledger()
    if args.cmd in scout_cmds:
        return scout_cmds[args.cmd](cfg, ledger, args)
    {"list": cmd_list, "add": cmd_add, "schedule": cmd_schedule,
     "run": cmd_run, "score": cmd_score, "icon": cmd_icon,
     "swiss": cmd_swiss, "elo": cmd_elo, "backfill": cmd_backfill,
     "check": lambda cfg, ledger, args: print("available:", available(cfg, list(cfg["models"])))}[args.cmd](cfg, ledger, args)


if __name__ == "__main__":
    main()
