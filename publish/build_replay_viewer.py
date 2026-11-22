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

from musbench.leaderboard.board import harness  # noqa: E402
from musbench.leaderboard.icons import BRAND  # noqa: E402

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
    ap.add_argument("--standalone", action="store_true",
                    help="wrap index.html in a full HTML document (for static hosting; "
                         "artifact publishing adds its own wrapper)")
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

    # a public page lists only models that have played
    seen = {r["model"] for r in res["rows"]}
    rows = res["rows"]
    models = {k: v for k, v in models.items() if k in seen}
    for h in hist:
        h["elo_live"] = {k: v for k, v in h["elo_live"].items() if k in seen}
        h["elo_fit"] = {k: v for k, v in h["elo_fit"].items() if k in seen}
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
    page = (ROOT / "publish" / "leaderboard_site" / "index.html").read_text()
    if args.standalone:
        page = ("<!doctype html>\n<html lang=\"en\"><head><meta name=\"viewport\" "
                "content=\"width=device-width,initial-scale=1,viewport-fit=cover\">\n"
                "<style>body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n"
                + page.replace('<div class="banner">', '</head><body>\n<div class="banner">', 1)
                + "\n</body></html>\n")
    (out / "index.html").write_text(page)
    print(f"{len(matches)} matches, {len(hist)} games -> {out}")


if __name__ == "__main__":
    main()
