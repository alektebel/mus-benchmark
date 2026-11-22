#!/usr/bin/env python3
"""Render a tournament video: the Elo race, then one match replayed.

    python publish/build_replay_viewer.py --out /tmp/viewer
    (cd /tmp/viewer && python -m http.server 8899) &
    python publish/render_replay_video.py --data /tmp/viewer/data.json \\
        --url http://localhost:8899/ --match 1 --hands 3 --out mus.mp4

Every frame is one exact state of the viewer (frame mode, 1280x720) captured
with headless Chromium, so the video is deterministic: one still per Elo-race
game and one per decision, held for a duration that suits it, stitched by ffmpeg.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HOLD = {"race": 1.0, "race_end": 3.0, "deal": 1.5, "auto": 0.6, "ev": 2.2, "show": 3.5}


def chrome() -> str:
    for c in (os.environ.get("CHROME"), shutil.which("chromium"), shutil.which("google-chrome"),
              *sorted(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux*/chrome"))[-1:]):
        if c and Path(c).exists():
            return str(c)
    raise SystemExit("no Chromium found (set CHROME=/path/to/chrome)")


def shoot(args):
    exe, url, out = args
    subprocess.run([exe, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                    "--window-size=1280,720", "--virtual-time-budget=3000",
                    f"--screenshot={out}", url], capture_output=True, timeout=90)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--url", default="http://localhost:8899/")
    ap.add_argument("--match", type=int, default=0, help="index in data.json matches")
    ap.add_argument("--hands", type=int, default=0, help="only the first N hands (0 = all)")
    ap.add_argument("--hand", type=int, default=None, help="only this hand (0-based)")
    ap.add_argument("--no-race", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="mus_replay.mp4")
    a = ap.parse_args()
    D = json.loads(Path(a.data).read_text())
    plan = []                                   # (query, seconds)
    if not a.no_race:
        n = len(D["history"])
        plan += [(f"frame=1&race={k}", HOLD["race"]) for k in range(n)]
        plan.append((f"frame=1&race={n}", HOLD["race_end"]))
    m = D["matches"][a.match]
    step = 0
    for hi, h in enumerate(m["hands"]):
        if a.hands and hi >= a.hands:
            break
        keep = a.hand is None or hi == a.hand
        n = len(h["events"]) + 2               # deal + events + showdown
        if keep:
            plan.append((f"frame=1&match={a.match}&step={step}", HOLD["deal"]))
            for i, e in enumerate(h["events"], 1):
                plan.append((f"frame=1&match={a.match}&step={step + i}",
                             HOLD["auto" if e.get("auto") else "ev"]))
            plan.append((f"frame=1&match={a.match}&step={step + n - 1}", HOLD["show"]))
        step += n
    exe = chrome()
    tmp = Path(tempfile.mkdtemp(prefix="mus-frames-", dir=os.environ.get("FRAMES_DIR")))
    jobs = [(exe, f"{a.url}?{q}", str(tmp / f"{i:05d}.png")) for i, (q, _) in enumerate(plan)]
    print(f"{len(jobs)} frames -> {tmp}", flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        for i, _ in enumerate(ex.map(shoot, jobs), 1):
            if i % 25 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    lst = tmp / "frames.txt"
    with lst.open("w") as f:
        for (_, sec), (_, _, png) in zip(plan, jobs):
            f.write(f"file '{png}'\nduration {sec}\n")
        f.write(f"file '{jobs[-1][2]}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-vf", "fps=30,format=yuv420p", "-c:v", "libx264",
                    "-crf", "20", "-movflags", "+faststart", a.out], check=True)
    total = sum(s for _, s in plan)
    print(f"wrote {a.out} ({total:.0f} s, {len(plan)} frames)")


if __name__ == "__main__":
    main()
