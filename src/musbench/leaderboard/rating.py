"""The mus_bench score: a paired, seat-corrected piedras-per-hand rating.

Every match contributes one number, the piedras margin per hand of team A
over team B. The model behind it is linear (a Massey rating):

    margin_per_hand(A vs B) = r_A - r_B + seat_bias

fitted by least squares, each match weighted by its hand count. ``seat_bias``
absorbs the known edge of seats 0+2 (README, "Known seat bias"); with the
mirrored schedule it cancels anyway, but the term keeps an unpaired match
from leaking seating into a rating.

``r`` is defined up to a constant. It is fixed either by an anchor model
(``r_anchor = 0``) or, without one, by making the field mean 0. Read a score as
*piedras per hand won against an average opponent of this field*.

Uncertainty comes from a block bootstrap: a block is one (pairing, seed) --
both seatings of the same deals -- so a resample never splits a mirror pair.
Each resample is refitted; the 2.5/97.5 percentiles give the interval and the
share of resamples where a model comes out on top gives ``p_best``.

Pure Python, no numpy: the system is (models + 1) square, i.e. tiny.
"""
from __future__ import annotations

import random
from collections import defaultdict


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; None if singular."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            return None
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col and m[r][col]:
                f = m[r][col] / m[col][col]
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def _connected(models: list[str], matches: list[dict]) -> bool:
    adj = defaultdict(set)
    for m in matches:
        adj[m["team_a"]].add(m["team_b"])
        adj[m["team_b"]].add(m["team_a"])
    seen, stack = set(), [models[0]]
    while stack:
        x = stack.pop()
        if x not in seen:
            seen.add(x)
            stack.extend(adj[x] - seen)
    return seen >= set(models)


def fit(matches: list[dict], anchor: str = "") -> dict | None:
    """Return {"ratings": {model: r}, "seat_bias": h}, or None if the
    comparison graph is disconnected (ratings would be meaningless)."""
    models = sorted({m["team_a"] for m in matches} | {m["team_b"] for m in matches})
    if len(models) < 2 or not _connected(models, matches):
        return None
    # parameters: r_1..r_{k-1} (models[0] pinned at 0), then seat_bias
    idx = {name: i - 1 for i, name in enumerate(models)}
    k = len(models)
    ata = [[0.0] * k for _ in range(k)]
    atb = [0.0] * k
    for m in matches:
        hands = m["hands"]
        y = (m["piedras_a"] - m["piedras_b"]) / hands
        row = [0.0] * k
        if idx[m["team_a"]] >= 0:
            row[idx[m["team_a"]]] += 1.0
        if idx[m["team_b"]] >= 0:
            row[idx[m["team_b"]]] -= 1.0
        row[k - 1] = 1.0
        for i in range(k):
            if row[i]:
                atb[i] += hands * row[i] * y
                for j in range(k):
                    ata[i][j] += hands * row[i] * row[j]
    sol = _solve(ata, atb)
    if sol is None:
        return None
    raw = {name: (0.0 if idx[name] < 0 else sol[idx[name]]) for name in models}
    shift = raw[anchor] if anchor in raw else sum(raw.values()) / len(raw)
    return {"ratings": {n: v - shift for n, v in raw.items()},
            "seat_bias": sol[k - 1]}


def _blocks(matches: list[dict]) -> list[list[dict]]:
    by = defaultdict(list)
    for m in matches:
        by[(tuple(sorted((m["team_a"], m["team_b"]))), m["seed"])].append(m)
    return [by[k] for k in sorted(by)]


def _percentile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    if not xs:
        return float("nan")
    pos = q * (len(xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def rate(matches: list[dict], anchor: str = "", n_boot: int = 2000,
         seed: int = 0) -> dict:
    """Full leaderboard: point ratings, bootstrap CI, p_best, descriptives."""
    point = fit(matches, anchor)
    if point is None:
        return {"rows": [], "seat_bias": None, "n_matches": len(matches),
                "n_boot": 0, "error": "comparison graph is disconnected"}
    models = list(point["ratings"])
    blocks = _blocks(matches)
    rng = random.Random(seed)
    draws = defaultdict(list)
    best = defaultdict(int)
    used = 0
    for _ in range(n_boot):
        sample = [m for _ in blocks for m in rng.choice(blocks)]
        present = {m["team_a"] for m in sample} | {m["team_b"] for m in sample}
        if present != set(models):
            continue           # a model dropped out of this resample
        f = fit(sample, anchor)
        if f is None:
            continue
        used += 1
        for name, v in f["ratings"].items():
            draws[name].append(v)
        best[max(f["ratings"], key=f["ratings"].get)] += 1

    desc = {n: {"matches": 0, "hands": 0, "pf": 0, "pa": 0, "opp": set(),
                "calls": 0, "fallbacks": 0, "w": 0, "l": 0, "t": 0}
            for n in models}
    for m in matches:
        for me, op, pf, pa in ((m["team_a"], m["team_b"], m["piedras_a"], m["piedras_b"]),
                               (m["team_b"], m["team_a"], m["piedras_b"], m["piedras_a"])):
            d = desc[me]
            d["matches"] += 1
            d["hands"] += m["hands"]
            d["pf"] += pf
            d["pa"] += pa
            d["opp"].add(op)
            d["w" if pf > pa else "l" if pf < pa else "t"] += 1
        if "fallbacks_a" in m:      # per-team counts (ledger rows from `run`)
            for me, side in ((m["team_a"], "a"), (m["team_b"], "b")):
                desc[me]["calls"] += m.get(f"llm_calls_{side}") or 0
                desc[me]["fallbacks"] += m.get(f"fallbacks_{side}") or 0
        else:                       # legacy rows: per match, charged to both
            for me in (m["team_a"], m["team_b"]):
                desc[me]["calls"] += m.get("llm_calls") or 0
                desc[me]["fallbacks"] += m.get("fallbacks") or 0

    rows = []
    for n in models:
        d = desc[n]
        calls = d["calls"] + d["fallbacks"]
        rows.append({
            "model": n,
            "score": point["ratings"][n],
            "ci_low": _percentile(draws[n], 0.025),
            "ci_high": _percentile(draws[n], 0.975),
            "p_best": best[n] / used if used else 0.0,
            "matches": d["matches"], "hands": d["hands"],
            "opponents": len(d["opp"]),
            "record": f"{d['w']}-{d['l']}-{d['t']}",
            "raw_per_hand": (d["pf"] - d["pa"]) / d["hands"] if d["hands"] else 0.0,
            "fallback_rate": d["fallbacks"] / calls if calls else 0.0,
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    # is #1 separated from #2? (their intervals do not overlap)
    separated = (len(rows) > 1 and rows[0]["ci_low"] > rows[1]["ci_high"])
    return {"rows": rows, "seat_bias": point["seat_bias"],
            "n_matches": len(matches), "n_boot": used, "anchor": anchor,
            "top_separated": separated}
