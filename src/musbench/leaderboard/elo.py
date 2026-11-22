"""Elo for mus: one game = one mirrored pair, fitted all at once.

A *game* is two matches on the same seed with the seats swapped. Both teams
see exactly the same deals from both sides, so card luck and the seat edge
cancel; whoever scores more piedras over the pair wins the game (equal totals
are a draw). One game is one Elo result, whether it was won 170-80 or 95-94.

Ratings are a Bradley-Terry fit over every game at once (order-independent,
unlike match-by-match Elo updates), on the Elo scale (400 points = 10:1
odds), with a weak Gaussian prior so an unbeaten model gets a finite rating.
The anchor (the free heuristic) is pinned at ANCHOR_ELO, so a rating means
the same thing as models come and go. Intervals: bootstrap over games.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict

ELO = 400 / math.log(10)          # logit -> Elo points
ANCHOR_ELO = 1000.0
PRIOR_SD = 350.0                  # Elo; keeps unbeaten records finite


def pair_games(matches: list[dict]) -> list[dict]:
    """Collapse matches into mirrored games. Unpaired matches are dropped."""
    by = defaultdict(dict)
    done_at: dict[tuple, int] = {}
    for i, m in enumerate(matches):
        key = (tuple(sorted((m["team_a"], m["team_b"]))), m["seed"])
        by[key][(m["team_a"], m["team_b"])] = m
        done_at[key] = i                 # a game ends with its second match
    games = []
    for (models, seed), sides in sorted(by.items(), key=lambda kv: done_at[kv[0]]):
        x, y = models
        if len(sides) != 2 or (x, y) not in sides or (y, x) not in sides:
            continue
        m1, m2 = sides[(x, y)], sides[(y, x)]
        px = m1["piedras_a"] + m2["piedras_b"]
        py = m1["piedras_b"] + m2["piedras_a"]
        hands = m1["hands"] + m2["hands"]
        games.append({"x": x, "y": y, "seed": seed, "px": px, "py": py,
                      "hands": hands,
                      "match_ids": [m1.get("match_id"), m2.get("match_id")],
                      "finished_at": max(str(m1.get("finished_at") or ""),
                                         str(m2.get("finished_at") or "")) or None,
                      "score": 1.0 if px > py else 0.0 if px < py else 0.5})
    return games


def fit(games: list[dict], anchor: str = "heuristic",
        iters: int = 200, start: float = ANCHOR_ELO) -> dict[str, float]:
    """MAP Bradley-Terry by Newton's method on the logit scale."""
    models = sorted({g["x"] for g in games} | {g["y"] for g in games})
    if not models:
        return {}
    idx = {m: i for i, m in enumerate(models)}
    n = len(models)
    th = [0.0] * n
    lam = (ELO / PRIOR_SD) ** 2       # prior precision on the logit scale
    for _ in range(iters):
        grad = [-lam * t for t in th]
        hess = [[(lam if i == j else 0.0) for j in range(n)] for i in range(n)]
        for g in games:
            i, j = idx[g["x"]], idx[g["y"]]
            p = 1 / (1 + math.exp(th[j] - th[i]))
            r = g["score"] - p
            grad[i] += r
            grad[j] -= r
            w = p * (1 - p)
            hess[i][i] += w
            hess[j][j] += w
            hess[i][j] -= w
            hess[j][i] -= w
        step = _solve(hess, grad)
        if step is None:
            break
        th = [t + s for t, s in zip(th, step)]
        if max(abs(s) for s in step) < 1e-9:
            break
    base = th[idx[anchor]] if anchor in idx else sum(th) / n
    return {m: start + ELO * (th[idx[m]] - base) for m in models}


def _solve(a, b):
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-12:
            return None
        m[c], m[piv] = m[piv], m[c]
        for r in range(n):
            if r != c and m[r][c]:
                f = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def rate(matches: list[dict], anchor: str = "heuristic", n_boot: int = 1000,
         seed: int = 0, start: float = ANCHOR_ELO) -> dict:
    games = pair_games(matches)
    point = fit(games, anchor, start=start)
    if not point:
        return {"rows": [], "games": 0, "n_boot": 0}
    rng = random.Random(seed)
    draws = defaultdict(list)
    best = defaultdict(int)
    contenders = [m for m in point if m != anchor] or list(point)
    used = 0
    for _ in range(n_boot):
        sample = [rng.choice(games) for _ in games]
        f = fit(sample, anchor, iters=60, start=start)
        if set(f) != set(point):
            continue
        used += 1
        for m, v in f.items():
            draws[m].append(v)
        best[max(contenders, key=lambda m: f[m])] += 1
    stats = defaultdict(lambda: {"games": 0, "w": 0, "l": 0, "d": 0,
                                 "pf": 0, "pa": 0, "hands": 0, "opp": set()})
    for g in games:
        for me, op, pf, pa, sc in ((g["x"], g["y"], g["px"], g["py"], g["score"]),
                                   (g["y"], g["x"], g["py"], g["px"], 1 - g["score"])):
            s = stats[me]
            s["games"] += 1
            s["w" if sc == 1 else "l" if sc == 0 else "d"] += 1
            s["pf"] += pf
            s["pa"] += pa
            s["hands"] += g["hands"]
            s["opp"].add(op)
    rows = []
    for m, v in point.items():
        d = sorted(draws[m])
        lo = d[int(0.025 * (len(d) - 1))] if d else float("nan")
        hi = d[int(0.975 * (len(d) - 1))] if d else float("nan")
        s = stats[m]
        rows.append({"model": m, "elo": v, "ci_low": lo, "ci_high": hi,
                     "p_best": best[m] / used if used else 0.0,
                     "games": s["games"], "record": f"{s['w']}-{s['l']}-{s['d']}",
                     "opponents": len(s["opp"]),
                     "per_hand": (s["pf"] - s["pa"]) / s["hands"] if s["hands"] else 0.0,
                     "anchor": m == anchor})
    rows.sort(key=lambda r: r["elo"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return {"rows": rows, "games": len(games), "n_boot": used, "anchor": anchor}


def incremental(games: list[dict], start: float = ANCHOR_ELO,
                k: float = 32.0) -> dict[str, float]:
    """Classic chess-style Elo: everyone starts at `start` and each game moves
    both ratings by K x (result - expected), in the order the games finished.
    Order-dependent, so it is the 'live' number, not the official fit."""
    r: dict[str, float] = defaultdict(lambda: start)
    for g in games:
        ex = 1 / (1 + 10 ** ((r[g["y"]] - r[g["x"]]) / 400))
        d = k * (g["score"] - ex)
        r[g["x"]] += d
        r[g["y"]] -= d
    return dict(r)


def history(games: list[dict], models: list[str], start: float = ANCHOR_ELO,
            anchor: str = "", k: float = 32.0) -> list[dict]:
    """One row per game in finishing order: the result, then every model's
    live (K-factor) Elo and the fitted Elo over all games so far."""
    live = {m: start for m in models}
    out = []
    for n, g in enumerate(games, 1):
        ex = 1 / (1 + 10 ** ((live[g["y"]] - live[g["x"]]) / 400))
        d = k * (g["score"] - ex)
        live[g["x"]] += d
        live[g["y"]] -= d
        fitted = fit(games[:n], anchor, iters=60, start=start)
        out.append({"game": n, "x": g["x"], "y": g["y"], "seed": g["seed"],
                    "piedras": [g["px"], g["py"]], "score": g["score"],
                    "match_ids": g.get("match_ids"), "finished_at": g.get("finished_at"),
                    "elo_live": {m: round(v, 1) for m, v in live.items()},
                    "elo_fit": {m: round(fitted.get(m, start), 1) for m in models}})
    return out


# -------------------------------------------------------------- power ----
def games_needed(elo_gap: float, z: float = 1.96) -> int:
    """Mirrored games between TWO models for a win rate CI to exclude 50%,
    if their true gap is `elo_gap` (normal approximation, no draws)."""
    p = 1 / (1 + 10 ** (-elo_gap / 400))
    return math.ceil(z * z * p * (1 - p) / (p - 0.5) ** 2)


def gap_resolvable(games: int, z: float = 1.96) -> float:
    """Smallest Elo gap that `games` head-to-head games can resolve."""
    lo, hi = 1.0, 2000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if games_needed(mid, z) > games:
            lo = mid
        else:
            hi = mid
    return hi
