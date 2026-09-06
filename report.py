"""Render the vacas win-rate matrix and rank the best cooperation pairs.

CLI:  python report.py [results.json]
"""
from __future__ import annotations

import json
import sys


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def build_matrix(data: dict) -> tuple[list, dict]:
    parts = data["participants"]
    # average win-rate across both seatings, for a symmetric matrix
    cells = {p: {} for p in parts}
    for key, r in data["results"].items():
        a, b = r["model_a"], r["model_b"]
        # average of the two seatings for symmetric co-op value
        other_key = f"{r['model_b']}+{r['model_a']}"
        wr = r["mean_win_rate"]
        other = data["results"].get(other_key)
        if other:
            symmetric = (wr + other["mean_win_rate"]) / 2
        else:
            symmetric = wr
        cells[a][b] = symmetric
        cells[b][a] = symmetric if a != b else 0
    for p in parts:
        cells[p][p] = 0.0
    return parts, cells


def render_md(parts, cells) -> str:
    lines = ["| Pair A \\ B | " + " | ".join(parts) + " |", "|---|" + "|".join(["---"] * len(parts)) + "|"]
    for a in parts:
        row = [f"{cells[a][b]:.3f}" if b in cells[a] else "-" for b in parts]
        lines.append(f"| {a} | " + " | ".join(row) + " |")
    return "\n".join(lines)


def rank_pairs(data: dict) -> list[dict]:
    scored = []
    for key, r in data["results"].items():
        scored.append({
            "pair": f"{r['model_a']} + {r['model_b']}",
            "a": r["model_a"], "b": r["model_b"],
            "symmetric_win_rate": round(_sym(data, r), 4),
            "seated_win_rate": round(r["mean_win_rate"], 4),
            "hand_wins": r["hand_wins_a"],
        })
    # symmetric is the cooperation metric
    scored.sort(key=lambda x: x["symmetric_win_rate"], reverse=True)
    return scored


def _sym(data, r) -> float:
    other = data["results"].get(f"{r['model_b']}+{r['model_a']}")
    if other:
        return (r["mean_win_rate"] + other["mean_win_rate"]) / 2
    return r["mean_win_rate"]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "results.json"
    data = load(path)
    parts, cells = build_matrix(data)
    print("## Vaca win-rate matrix (fraction of vacas won vs reference pair; higher = better)\n")
    print(render_md(parts, cells))
    print("\n## Ranked cooperation pairs (symmetric win rate vs reference opfor)\n")
    for i, s in enumerate(rank_pairs(data), 1):
        print(f"{i:2d}. {s['pair']:<40} win_rate={s['symmetric_win_rate']:.3f} "
              f"(hand wins={s['hand_wins']})")


if __name__ == "__main__":
    main()
