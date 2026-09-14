"""Aggregate mus_bench result files for the live table's Results tab.

Pure functions over the two on-disk result formats:

  * tournament (kernel) summaries -- ``results/*/summary.json`` produced by
    ``run_tournament.py``: ``{"entries": [{job, team_a, team_b, seed, status,
    wall, metrics{...}, policies{...}}]}``.
  * strict batch outputs -- e.g. ``llm_vs_baseline.json`` from
    ``run_llm_vs_baseline.py``: ``{"config": {...}, "results": [{models,
    seed, status, vacas_llm, vacas_base, usage, elapsed}]}``.

Anything else (progress files, partial dumps) is ignored, so the directory
can be scanned aggressively while a benchmark is still running.
"""
from __future__ import annotations

import json
from pathlib import Path


# Matches that mostly fell back to default actions (rate-limit cascades,
# circuit breakers) must not enter the leaderboard. Thresholds are tuned for
# ~10-hand kernel games (~200–400 real LLM calls when healthy).
MIN_LLM_CALLS = 50
MAX_FALLBACK_RATIO = 0.15


def is_publishable_match(llm_calls: int, fallbacks: int,
                         status: str = "done") -> bool:
    """True when a finished match has enough real model play to count."""
    if status not in ("done", "finished"):
        return False
    calls = int(llm_calls or 0)
    fb = int(fallbacks or 0)
    if calls < MIN_LLM_CALLS:
        return False
    denom = calls + fb
    if denom <= 0:
        return False
    return (fb / denom) <= MAX_FALLBACK_RATIO


def _match_row(kind: str, source: str, label: str, seed, status: str,
               vacas_a, vacas_b, hands, hand_wins, senas: dict,
               false_senas: int, fallbacks: int, rejections: int,
               llm_calls: int, elapsed, piedras_a=None, piedras_b=None) -> dict:
    publishable = is_publishable_match(llm_calls, fallbacks, status)
    # Surface API-noise finishes as degraded so the UI/leaderboard can skip them
    if status in ("done", "finished") and not publishable:
        status = "degraded"
    return {"kind": kind, "source": source, "label": label, "seed": seed,
            "status": status, "vacas_a": vacas_a, "vacas_b": vacas_b,
            "hands": hands, "hand_wins": hand_wins, "senas": senas,
            "piedras_a": piedras_a, "piedras_b": piedras_b,
            # gestures false of the sender's own cards, addressed to the
            # sender's PARTNER -- deceiving a teammate, not a betting bluff
            "false_senas": false_senas, "fallbacks": fallbacks,
            "rejections": rejections, "llm_calls": llm_calls,
            "elapsed": elapsed, "publishable": publishable}


def _lb_key(model: str) -> dict:
    return {"model": model, "matches": 0, "wins": 0, "losses": 0, "ties": 0,
            "vacas_for": 0, "vacas_against": 0, "hands": 0,
            "senas_published": 0, "senas_caught": 0, "senas_missed": 0,
            "senas_intercepted": 0,
            "piedras_for": 0, "piedras_against": 0, "piedras_hands": 0,
            "false_senas": 0, "fallbacks": 0, "llm_calls": 0}


def _lb_add(lb: dict, model: str, vacas_for: int, vacas_against: int,
            hands: int, row: dict, piedras_for=None,
            piedras_against=None) -> None:
    k = lb.setdefault(model, _lb_key(model))
    k["matches"] += 1
    # matches from before piedras were recorded must not read as a 0.0 edge
    if piedras_for is not None and piedras_against is not None:
        k["piedras_for"] += piedras_for
        k["piedras_against"] += piedras_against
        k["piedras_hands"] += hands or 0
    k["vacas_for"] += vacas_for or 0
    k["vacas_against"] += vacas_against or 0
    k["hands"] += hands or 0
    k["senas_published"] += row["senas"].get("published", 0)
    k["senas_caught"] += row["senas"].get("caught", 0)
    k["senas_missed"] += row["senas"].get("missed", 0)
    k["senas_intercepted"] += row["senas"].get("intercepted", 0)
    k["false_senas"] += row["false_senas"]
    k["fallbacks"] += row["fallbacks"]
    k["llm_calls"] += row["llm_calls"]
    if vacas_for is None or vacas_against is None:
        return
    if vacas_for > vacas_against:
        k["wins"] += 1
    elif vacas_for < vacas_against:
        k["losses"] += 1
    else:
        k["ties"] += 1


def _tournament_entry_metrics(entry: dict) -> dict | None:
    """Metrics for one summary entry; derives them from the full result if
    the compact metrics block is missing (older summaries)."""
    m = entry.get("metrics")
    if m is not None:
        return m
    r = entry.get("result")
    if not isinstance(r, dict):
        return None
    return {
        "vacas_a": r.get("vacas_a"), "vacas_b": r.get("vacas_b"),
        "hands": r.get("hands"),
        "hand_wins": f"{r.get('hand_wins_a', 0)}-{r.get('hand_wins_b', 0)}",
        "senas_published": r.get("signals", {}).get("published", 0),
        "senas_caught": r.get("signals", {}).get("caught", 0),
        "senas_missed": r.get("signals", {}).get("missed", 0),
        "senas_intercepted": r.get("signals", {}).get("intercepted", 0),
        "llm_calls": sum(a.get("calls", 0) for a in r.get("agents", [])
                         if a.get("is_llm")),
        "fallbacks": r.get("usage", {}).get("fallbacks", 0),
        "rejections": sum(a.get("rejections", 0) for a in r.get("agents", [])),
        "false_senas_to_partner": sum(a.get("bluffs", 0)
                                      for a in r.get("agents", [])),
        "piedras_a": r.get("piedras_a"), "piedras_b": r.get("piedras_b"),
        "elapsed_s": r.get("elapsed"),
        "policies": {a["name"]: a.get("policy") for a in r.get("agents", [])
                     if a.get("is_llm")},
    }


def load_tournament_summary(path: Path) -> list[dict]:
    """Rows for every completed match in a run_tournament summary.json."""
    try:
        data = json.loads(path.read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return []
    rows = []
    for e in data["entries"]:
        m = _tournament_entry_metrics(e)
        if m is None:
            rows.append(_match_row(
                "tournament", str(path),
                f"{e.get('team_a')} vs {e.get('team_b')}",
                e.get("seed"), e.get("status", "failed"),
                None, None, None, None, {}, 0, 0, 0, 0, e.get("wall")))
            continue
        senas = {"published": m.get("senas_published", 0),
                 "caught": m.get("senas_caught", 0),
                 "missed": m.get("senas_missed", 0),
                 "intercepted": m.get("senas_intercepted", 0)}
        rows.append(_match_row(
            "tournament", str(path),
            f"{e.get('team_a')} vs {e.get('team_b')}",
            e.get("seed"), e.get("status", "done"),
            m.get("vacas_a"), m.get("vacas_b"), m.get("hands"),
            m.get("hand_wins"), senas,
            # older summaries spelled this "bluffs"
            m.get("false_senas_to_partner", m.get("bluffs", 0)),
            m.get("fallbacks", 0), m.get("rejections", 0),
            m.get("llm_calls", 0), m.get("elapsed_s"),
            m.get("piedras_a"), m.get("piedras_b")))
    return rows


def load_batch_results(path: Path) -> list[dict]:
    """Rows for a strict batch output file ({config, results})."""
    try:
        data = json.loads(path.read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        return []
    rows = []
    for j in data["results"]:
        models = j.get("models") or []
        if not models:
            continue
        partner = models[1] if len(models) > 1 else None
        label = (" + ".join(models) + " vs baseline"
                 if partner else f"{models[0]} vs baseline")
        u = j.get("usage") or {}
        rows.append(_match_row(
            "batch", str(path), label, j.get("seed"), j.get("status", "?"),
            j.get("vacas_llm"), j.get("vacas_base"), None,
            (f"{j.get('hand_wins_llm', 0)}-{j.get('hand_wins_base', 0)}"
             if j.get("hand_wins_llm") is not None else None),
            {}, 0, u.get("fallbacks", 0), 0, u.get("calls", 0),
            j.get("elapsed")))
    return rows


def _classify_and_load(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("entries"), list):          # tournament summary
        return load_tournament_summary(path)
    if isinstance(data.get("results"), list) and "config" in data \
            and isinstance(data["config"], dict):      # strict batch output
        return load_batch_results(path)
    return []                                          # progress/dump file


def aggregate_results(results_dir: str | Path = "results") -> dict:
    """Scan a results directory and return {sources, matches, leaderboard}.

    The leaderboard credits both tournament teams with their own vacas;
    batch rows credit the LLM side (models joined) vs the baseline floor.
    """
    root = Path(results_dir)
    matches: list[dict] = []
    sources = []
    if root.is_dir():
        for p in sorted(root.rglob("*.json")):
            rows = _classify_and_load(p)
            if rows:
                sources.append(str(p))
                matches.extend(rows)

    lb: dict[str, dict] = {}
    for row in matches:
        if not row.get("publishable"):
            continue
        if row["kind"] == "tournament":
            team_a, team_b = row["label"].split(" vs ", 1)
            _lb_add(lb, team_a, row["vacas_a"], row["vacas_b"],
                    row["hands"], row, row["piedras_a"], row["piedras_b"])
            _lb_add(lb, team_b, row["vacas_b"], row["vacas_a"],
                    row["hands"], row, row["piedras_b"], row["piedras_a"])
        elif row["kind"] == "batch" and row["label"].endswith(" vs baseline"):
            side = row["label"][: -len(" vs baseline")]
            _lb_add(lb, side, row["vacas_a"], row["vacas_b"],
                    row["hands"], row, row["piedras_a"], row["piedras_b"])
    for k in lb.values():
        k["piedras_per_hand"] = (
            round((k["piedras_for"] - k["piedras_against"])
                  / k["piedras_hands"], 3) if k["piedras_hands"] else None)
    leaderboard = sorted(
        lb.values(),
        key=lambda k: (k["piedras_per_hand"] is not None,
                       k["piedras_per_hand"] or 0.0,
                       k["vacas_for"] - k["vacas_against"]), reverse=True)
    return {"sources": sources, "matches": matches,
            "leaderboard": leaderboard}
