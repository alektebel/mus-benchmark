#!/usr/bin/env python3
"""Bundle a tournament's replays + Elo into the static replay viewer.

    python publish/build_replay_viewer.py --out /tmp/viewer
    (cd /tmp/viewer && python -m http.server 8899)

Writes <out>/index.html (publish/replay_viewer/index.html), <out>/data.json
and <out>/icons/*.svg. data.json holds the roster, the current Elo table,
the per-game Elo history and every replay of the tournament, trimmed to the
fields the viewer animates.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from musbench.leaderboard import cli, elo, render, replay, skills  # noqa: E402

BRAND = {"Anthropic": "#d97757", "OpenAI": "#10a37f", "Cursor": "#5b6270",
         "TypeSafe": "#d9a930", "Thinking Machines": "#7c6cf0", "Google": "#4285f4",
         "DeepSeek": "#4d6bfe", "Alibaba Cloud": "#ff6a00", "Zhipu AI": "#3859ff",
         "Moonshot AI": "#16191e", "xAI": "#2b2b2b", "Mistral AI": "#fa520f",
         "Meta": "#0866ff", "MiniMax": "#e2167e", "NVIDIA": "#76b900"}
HARNESS = {"claude-cli": "Claude Code", "codex-cli": "Codex CLI", "cursor-cli": "Cursor CLI",
           "typesafe": "API", "openrouter": "API", "nan": "API", "nvidia": "API",
           "anthropic": "API"}


def harness(spec: str) -> str:
    head = spec.split(":", 1)[0] if ":" in spec else "nan"
    return HARNESS.get(head, "offline" if spec in ("heuristic", "random") else "API")

KEEP = ("seat", "phase", "stage", "lance", "action", "cards", "drew", "public",
        "thought", "stake", "auto", "points_after", "would_win", "options")


def trim(rp: dict) -> dict:
    hands = []
    for h in rp["hands"]:
        hands.append({k: h.get(k) for k in ("hand", "mano", "dealt", "showdown",
                                            "lances", "gain", "points_after",
                                            "vacas_after", "locked_envites")}
                     | {"events": [{k: e[k] for k in KEEP if e.get(k) is not None}
                                   for e in h["events"]]})
    return {k: rp.get(k) for k in ("match_id", "seed", "status", "finished_at",
                                   "seats", "result")} | {"hands": hands}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    (out / "icons").mkdir(parents=True, exist_ok=True)

    cfg = cli.load_config()
    ledger = cli.load_ledger()
    rated = cli.rated_matches(cfg, ledger)
    games = elo.pair_games(rated)
    res = elo.rate(rated, cfg["anchor"], n_boot=500, start=cfg["start_elo"])
    live = elo.incremental(games, start=cfg["start_elo"])
    hist = elo.history(games, list(cfg["models"]), start=cfg["start_elo"],
                       anchor=cfg["anchor"])

    models = {}
    for mid in cfg["models"]:
        m = render._meta(cfg["models"], mid)
        for slug in {m["provider_icon"], m["model_icon"]} - {""}:
            src = ROOT / "benchmark" / "icons" / f"{slug}.svg"
            if src.exists():
                shutil.copy(src, out / "icons" / f"{slug}.svg")
        spec = cfg["models"][mid]["spec"]
        models[mid] = {"name": m["name"], "provider": m["provider"],
                       "provider_icon": m["provider_icon"], "model_icon": m["model_icon"],
                       "spec": spec, "harness": harness(spec),
                       "color": BRAND.get(m["provider"], "#8a8f9e")}

    rated_ids = {r.get("match_id") for r in rated}
    full = []
    matches = []
    for row in ledger:
        if row.get("tournament") != cfg.get("tournament") or not row.get("replay"):
            continue
        if row.get("match_id") not in rated_ids:
            continue
        path = ROOT / row["replay"]
        if path.exists():
            rp = replay.read(path)
            full.append(rp)
            matches.append(trim(rp))
    matches.sort(key=lambda m: m.get("finished_at") or "")

    seen = {r["model"] for r in res["rows"]}
    rows = res["rows"] + [{"model": m, "elo": cfg["start_elo"], "ci_low": cfg["start_elo"],
                           "ci_high": cfg["start_elo"], "games": 0, "record": "0-0-0",
                           "per_hand": 0.0, "p_best": 0.0}
                          for m in cfg["models"] if m not in seen]
    data = {"tournament": cfg.get("tournament"), "protocol": cfg["protocol"],
            "start_elo": cfg["start_elo"], "models": models,
            "leaderboard": [dict(r, live=round(live.get(r["model"], cfg["start_elo"]), 1))
                            for r in rows],
            "history": hist, "matches": matches,
            "skills": skills.compute(full),
            "skill_defs": {k: {"name": n, "unit": u, "def": d}
                           for k, (n, u, d) in skills.SKILLS.items()},
            "updated": max((r.get("finished_at") or "" for r in rated), default="")}
    (out / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    viewer = (ROOT / "publish" / "replay_viewer" / "index.html").read_text()
    # the leaderboard is the site's page; the viewer is a second, standalone page
    (out / "replays.html").write_text(
        "<!doctype html>\n<html lang=\"en\"><head><meta name=\"viewport\" "
        "content=\"width=device-width,initial-scale=1,viewport-fit=cover\">\n"
        "<style>body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n"
        + viewer.replace('<div class="wrap">', '</head><body>\n<div class="wrap">', 1)
        + "\n</body></html>\n")
    shutil.copy(ROOT / "publish" / "leaderboard_site" / "index.html", out / "index.html")
    print(f"{len(matches)} matches, {len(hist)} games -> {out}")


if __name__ == "__main__":
    main()
