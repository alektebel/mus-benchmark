"""Salvage metrics from verbose kernel job logs when the result JSON never
arrived (job killed by timeout / API abort). Parses the decision print lines
(full action dict), the '| caught N sena(s)' markers and VACA lines.

Usage: python kernel_logparse.py /tmp/kernelbench_final/*.log
"""
from __future__ import annotations

import ast
import glob
import re
import sys

DEC = re.compile(r"^\s+\[(\w+)/seat(\d)\] (\{.*\})( \| caught (\d+) sena\(s\))?$")
VACA = re.compile(r"\[VACA\]")


def parse_log(path: str) -> dict:
    decisions = 0
    caught_events = 0
    signals_emitted = 0
    policies_declared = 0
    vaca_lines = 0
    by_seat: dict[str, int] = {}
    for line in open(path, encoding="utf8", errors="replace"):
        if "[VACA]" in line:
            vaca_lines += 1
        m = DEC.match(line.rstrip())
        if not m:
            continue
        try:
            action = ast.literal_eval(m.group(3))
        except (ValueError, SyntaxError):
            continue
        if not isinstance(action, dict):
            continue
        decisions += 1
        seat = m.group(2)
        by_seat[seat] = by_seat.get(seat, 0) + 1
        if action.get("signal"):
            signals_emitted += 1
        if isinstance(action.get("signal_policy"), dict):
            policies_declared += 1
        if m.group(5):
            caught_events += int(m.group(5))
    return {"file": path, "decisions_visible": decisions,
            "caught_senas": caught_events,
            "signals_emitted": signals_emitted,
            "policies_declared": policies_declared,
            "vacas_lines": vaca_lines, "by_seat": by_seat}


if __name__ == "__main__":
    pats = sys.argv[1:] or ["/tmp/kernelbench_final/*.log"]
    for p in pats:
        for f in sorted(glob.glob(p)) if any(c in p for c in "*?[") else [p]:
            if f.endswith("run.log"):
                continue
            print(parse_log(f))
