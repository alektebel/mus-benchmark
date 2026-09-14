#!/usr/bin/env python3
"""Export a finished match into one self-contained JSON trace for the web viewer.

Joins the three artifacts a run leaves behind:
  match.json    -- match-level totals, agents, signal_events
  match.jsonl   -- per-decision engine state + per-hand resolution
  io.jsonl      -- the prompt actually sent to each seat, and the raw reply

Usage:
  python publish/export_trace.py results/live_run --out publish/web/traces/seed6.json
"""
import argparse
import json
import os


class LineDict:
    """Prompts repeat a large static rules preamble on every turn.

    Storing each prompt as a list of indices into a shared line table shrinks
    the trace ~9x (4.2 MB -> ~0.5 MB), which matters because the viewer fetches
    the whole thing over the wire before it can animate anything.
    """

    def __init__(self):
        self.lines = []
        self._index = {}

    def encode(self, text):
        if text is None:
            return None
        out = []
        for line in text.split("\n"):
            idx = self._index.get(line)
            if idx is None:
                idx = len(self.lines)
                self._index[line] = idx
                self.lines.append(line)
            out.append(idx)
        return out


def load_jsonl(path):
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build(run_dir, slug):
    match = json.load(open(os.path.join(run_dir, "match.json")))
    events = load_jsonl(os.path.join(run_dir, "match.jsonl"))
    io_rows = load_jsonl(os.path.join(run_dir, "io.jsonl"))

    # VACA_NOTE rows are not decisions -- they are the private note a seat writes to
    # carry across a vaca boundary, and several share t=0.0, so they collide on
    # (t, seat) and would overwrite real prompts. Key on phase too and split them out.
    io_by_key = {(r["t"], r["seat"], r["phase"]): r
                 for r in io_rows if r["phase"] != "VACA_NOTE"}

    lines = LineDict()
    turns = []
    for ev in events:
        if ev.get("kind") != "decision":
            continue
        # A fallback decision has no io row: the model never returned a usable reply.
        io = io_by_key.get((ev["t"], ev["seat"], ev["phase"]), {})
        turns.append({
            "t": ev["t"],
            "hand": ev["hand"],
            "turn": ev.get("turn"),
            "seat": ev["seat"],
            "team": ev["team"],
            "name": ev["name"],
            "model": ev["model"],
            "phase": ev["phase"],
            "lance": ev.get("lance"),
            "action": ev.get("action"),
            "legal": ev.get("legal") or [],
            "thought": ev.get("thought"),
            "stake": ev.get("stake", 0),
            "previous": ev.get("previous", 0),
            "facing_bet": ev.get("facing_bet", False),
            "fallback": bool(ev.get("fallback")),
            "rejections": ev.get("rejections", 0),
            "senas_delivered": ev.get("senas_delivered") or [],
            "seen": io.get("seen") or [],
            "points_a": ev.get("points_a", 0),
            "points_b": ev.get("points_b", 0),
            "vacas_a": ev.get("vacas_a", 0),
            "vacas_b": ev.get("vacas_b", 0),
            "prompt": lines.encode(io.get("prompt")),
            "raw": io.get("raw"),
        })

    hands = []
    for ev in events:
        if ev.get("kind") != "hand":
            continue
        hands.append({
            "hand": ev["hand"],
            "t": ev["t"],
            "mano": ev.get("mano"),
            "dealt": ev.get("dealt") or {},
            "jugada_truth": ev.get("jugada_truth") or {},
            "locked_envites": ev.get("locked_envites") or [],
            "gain_a": ev.get("hand_gain_a", 0),
            "gain_b": ev.get("hand_gain_b", 0),
            "winner": ev.get("hand_winner"),
            "vacas_a": ev.get("vacas_a", 0),
            "vacas_b": ev.get("vacas_b", 0),
            "vaca_delta_a": ev.get("vaca_delta_a", 0),
            "vaca_delta_b": ev.get("vaca_delta_b", 0),
        })

    notes = [{
        "t": r["t"],
        "seat": r["seat"],
        "model": r.get("model"),
        "prompt": lines.encode(r.get("prompt")),
        "raw": r.get("raw"),
    } for r in io_rows if r["phase"] == "VACA_NOTE"]

    agents = [{
        "name": a["name"],
        "seat": a["seat"],
        "model": a["model"],
        "calls": a.get("calls", 0),
        "api_errors": a.get("api_errors", 0),
        "fallbacks": a.get("fallbacks", 0),
        "bluffs": a.get("bluffs", 0),
        "senas": a.get("senas") or [],
    } for a in match.get("agents", [])]

    return {
        "slug": slug,
        "lines": lines.lines,
        "meta": {
            "models": match.get("models"),
            "hands_requested": match.get("hands"),
            "hands_completed": match.get("hands_completed"),
            "status": match.get("status"),
            "abort_reason": match.get("abort_reason"),
            "elapsed": match.get("elapsed"),
            "virtual_clock": match.get("virtual_clock"),
            "memory_mode": match.get("memory_mode"),
            "turn_feed": match.get("turn_feed"),
        },
        "score": {
            "vacas_a": match.get("vacas_a"),
            "vacas_b": match.get("vacas_b"),
            "piedras_a": match.get("piedras_a"),
            "piedras_b": match.get("piedras_b"),
            "hand_wins_a": match.get("hand_wins_a"),
            "hand_wins_b": match.get("hand_wins_b"),
        },
        "usage": match.get("usage") or {},
        "signals": match.get("signals") or {},
        "agents": agents,
        "hands": hands,
        "turns": turns,
        "notes": notes,
        "signal_events": match.get("signal_events") or [],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--slug", default=None)
    args = ap.parse_args()

    slug = args.slug or os.path.basename(os.path.normpath(args.run_dir))
    trace = build(args.run_dir, slug)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(trace, fh, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(args.out)
    print(f"{args.out}  {size/1024:.0f} KB  "
          f"{len(trace['turns'])} turns, {len(trace['hands'])} hands, "
          f"{len(trace['signal_events'])} signals, "
          f"{len(trace['lines'])} distinct prompt lines, "
          f"{len(trace['notes'])} vaca notes, "
          f"{sum(1 for t in trace['turns'] if t['prompt'] is None)} turns with no reply")


if __name__ == "__main__":
    main()
