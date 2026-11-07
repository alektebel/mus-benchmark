"""Scorecard over the per-decision ground-truth log (`decision_log.py`).

The point of this module is to replace a 10-hand match's one noisy bit -- who
took the vaca -- with several hundred scored decisions.  Every metric here is
computed against what the cards actually were, using the winner the engine
itself recorded, so none of it depends on a hand-strength heuristic or an
arbitrary threshold.

Two halves:

  RISK      what the model does with a betting opportunity.  A bluff is an
            envite made from a hand the bettor could see was weak -- bottom
            tercile of the strength distribution FOR THAT LANCE, measured
            empirically over every seat that held the option to bet.  Note
            "bet and then lost the lance" is NOT a usable definition: with two
            opposing hands in play a team wins any given lance about half the
            time, so that number mostly measures the base rate.  Bluffing is
            about the information the bettor had, not how it turned out.

  READ      how well the model predicted, scored by Brier and log-loss:
              p_win_lance -- "do I hold the best hand here" (card read)
              p_opp_fold  -- "will this rival fold if I push" (rival read)
            The second is the one that cannot be answered from your own cards.

Pure functions over the JSONL; no API calls, so it is cheap to re-run.

    python analysis.py results/run/match.jsonl [--by-seat] [--json]
"""
from __future__ import annotations

import json
import math
from collections import defaultdict

AGGRESSIVE = ("envido", "y-yo", "reenvido", "ordago")
RESPONSES = ("quiero", "no-quiero") + AGGRESSIVE
_EPS = 1e-6


def load(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# ---------------------------------------------------------------- linking ---

def link_responses(recs: list[dict]) -> None:
    """Annotate each aggressive decision with how the opposition answered.

    Mutates in place, adding `response` (fold/call/raise/None) and
    `responder_seat`.  Within one hand and one lance, the answer that counts is
    the FIRST action by a seat on the other team -- either opponent may speak.
    """
    decisions = [r for r in recs if r.get("kind") == "decision"]
    by_lance: dict[tuple, list[dict]] = defaultdict(list)
    for r in decisions:
        by_lance[(r["hand"], r.get("lance"))].append(r)

    for (hand, lance), group in by_lance.items():
        if lance is None:
            continue
        for i, r in enumerate(group):
            r.setdefault("response", None)
            r.setdefault("responder_seat", None)
            r.setdefault("at_risk", 0)
            if r.get("action") not in AGGRESSIVE:
                continue
            for nxt in group[i + 1:]:
                if nxt["team"] == r["team"]:
                    continue
                act = nxt.get("action")
                if act not in RESPONSES:
                    continue
                r["response"] = ("fold" if act == "no-quiero"
                                 else "call" if act == "quiero" else "raise")
                r["responder_seat"] = nxt["seat"]
                # the stake as the RESPONDER saw it is the live bet: what the
                # bettor collects on a fold, and risks on a call
                r["at_risk"] = max(nxt.get("stake", 0) or 0, 1)
                r["fold_gain"] = max(nxt.get("previous", 0) or 0, 1)
                break


# ---------------------------------------------------------------- scoring ---

def _brier(pairs: list[tuple[float, bool]]) -> float | None:
    if not pairs:
        return None
    return sum((p - float(y)) ** 2 for p, y in pairs) / len(pairs)


def _logloss(pairs: list[tuple[float, bool]]) -> float | None:
    if not pairs:
        return None
    tot = 0.0
    for p, y in pairs:
        p = min(max(p, _EPS), 1.0 - _EPS)
        tot -= math.log(p) if y else math.log(1.0 - p)
    return tot / len(pairs)


def _auc(pairs: list[tuple[float, bool]]) -> float | None:
    """Mann-Whitney AUC: does the model rank true cases above false ones, even
    if its absolute numbers are miscalibrated?"""
    pos = [p for p, y in pairs if y]
    neg = [p for p, y in pairs if not y]
    if not pos or not neg:
        return None
    wins = sum((1.0 if a > b else 0.5 if a == b else 0.0)
               for a in pos for b in neg)
    return wins / (len(pos) * len(neg))


def _calibration(pairs: list[tuple[float, bool]], bins: int = 5) -> list[dict]:
    buckets: list[list] = [[] for _ in range(bins)]
    for p, y in pairs:
        idx = min(int(p * bins), bins - 1)
        buckets[idx].append((p, y))
    out = []
    for i, b in enumerate(buckets):
        if not b:
            continue
        out.append({"bin": f"{i / bins:.1f}-{(i + 1) / bins:.1f}",
                    "n": len(b),
                    "mean_p": round(sum(p for p, _ in b) / len(b), 3),
                    "actual": round(sum(1 for _, y in b if y) / len(b), 3)})
    return out


def _rate(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


def can_bet(r: dict) -> bool:
    """Did this seat hold a live betting option at this decision?"""
    return any(a in (r.get("legal") or []) for a in AGGRESSIVE)


def strength_terciles(recs: list[dict]) -> dict[str, tuple[float, float]]:
    """Per-lance cut points for weak / medium / strong hands.

    Derived from the log itself, over every decision where the seat COULD have
    bet -- so the reference is the real distribution of hands that faced a
    betting choice, not an invented threshold, and it is identical for every
    model being compared.
    """
    pools: dict[str, list[float]] = defaultdict(list)
    for r in recs:
        if r.get("kind") != "decision":
            continue
        s, lance = r.get("strength"), r.get("lance")
        if lance is not None and s is not None and can_bet(r):
            pools[lance].append(s)
    cuts = {}
    for lance, vals in pools.items():
        vals.sort()
        n = len(vals)
        if n < 6:                 # too few to split meaningfully
            continue
        cuts[lance] = (vals[n // 3], vals[2 * n // 3])
    return cuts


def strength_band(r: dict, cuts: dict) -> str | None:
    lance, s = r.get("lance"), r.get("strength")
    if lance is None or s is None or lance not in cuts:
        return None
    lo, hi = cuts[lance]
    return "weak" if s <= lo else "strong" if s > hi else "medium"


# ------------------------------------------------------------- scorecards ---

def scorecard(recs: list[dict], key: str = "model") -> dict[str, dict]:
    """One scorecard per model (or per seat with key='seat')."""
    link_responses(recs)
    cuts = strength_terciles(recs)
    decisions = [r for r in recs if r.get("kind") == "decision"]
    hands = [r for r in recs if r.get("kind") == "hand"]
    n_hands = len(hands)

    acc: dict = defaultdict(lambda: {
        "decisions": 0, "fallbacks": 0, "rejections": 0,
        "bet_chances": 0, "bet_chances_weak": 0,
        "aggressive": 0, "bluffs": 0, "value_bets": 0,
        "strength_sum": 0.0, "strength_n": 0,
        "bluff_folded": 0, "bluff_called": 0,
        "value_folded": 0, "value_called": 0,
        "stake_won_folds": 0, "stake_lost_called_bluffs": 0,
        "faced_winning": 0, "fold_error": 0,
        "faced_losing": 0, "payoff": 0,
        "by_lance": defaultdict(lambda: {"aggressive": 0, "bluffs": 0}),
        "by_position": defaultdict(lambda: {"aggressive": 0, "bluffs": 0}),
        "read_win": [], "read_fold": [],
        "read_win_early": [], "read_win_late": [],
        "read_fold_early": [], "read_fold_late": [],
        "seats": set(), "senas_caught": 0,
    })
    half = (max((r["hand"] for r in decisions), default=0) + 1) / 2

    for r in decisions:
        k = str(r.get(key))
        a = acc[k]
        a["seats"].add(r["seat"])
        a["decisions"] += 1
        a["fallbacks"] += 1 if r.get("fallback") else 0
        a["rejections"] += r.get("rejections", 0)
        a["senas_caught"] += len(r.get("senas_delivered") or [])
        act = r.get("action")
        would_win = r.get("would_win")
        lance = r.get("lance")
        early = r["hand"] <= half

        # ---- betting side -------------------------------------------------
        band = strength_band(r, cuts)
        if lance is not None and can_bet(r):
            a["bet_chances"] += 1
            if band == "weak":
                a["bet_chances_weak"] += 1
        if act in AGGRESSIVE and lance is not None:
            a["aggressive"] += 1
            a["by_lance"][lance]["aggressive"] += 1
            pos = _position(r)
            a["by_position"][pos]["aggressive"] += 1
            if r.get("strength") is not None:
                a["strength_sum"] += r["strength"]
                a["strength_n"] += 1
            resp = r.get("response")
            if band == "strong":
                a["value_bets"] += 1
                if resp == "fold":
                    a["value_folded"] += 1
                elif resp == "call":
                    a["value_called"] += 1
            elif band == "weak":
                # a bet from the bottom tercile of this lance: a real bluff
                a["bluffs"] += 1
                a["by_lance"][lance]["bluffs"] += 1
                a["by_position"][pos]["bluffs"] += 1
                if resp == "fold":
                    a["bluff_folded"] += 1
                    a["stake_won_folds"] += r.get("fold_gain", 1)
                elif resp == "call":
                    a["bluff_called"] += 1
                    # a called bluff is only actually paid if the lance is lost
                    if would_win is False:
                        a["stake_lost_called_bluffs"] += r.get("at_risk", 1)

        # ---- responding side ----------------------------------------------
        if (r.get("facing_bet") and would_win is not None
                and act in ("quiero", "no-quiero") + AGGRESSIVE
                and r.get("holder_team") is not None
                and r["holder_team"] != r["team"]):
            if would_win:
                a["faced_winning"] += 1
                if act == "no-quiero":
                    a["fold_error"] += 1
            else:
                a["faced_losing"] += 1
                if act != "no-quiero":
                    a["payoff"] += 1

        # ---- read side-channel --------------------------------------------
        read = r.get("read") or {}
        pw = _prob(read.get("p_win_lance"))
        if pw is not None and would_win is not None:
            a["read_win"].append((pw, bool(would_win)))
            (a["read_win_early"] if early else a["read_win_late"]).append(
                (pw, bool(would_win)))
        pf = _prob(read.get("p_opp_fold"))
        if pf is not None and act in AGGRESSIVE and r.get("response"):
            y = r["response"] == "fold"
            a["read_fold"].append((pf, y))
            (a["read_fold_early"] if early else a["read_fold_late"]).append((pf, y))

    return {k: _finalise(v, n_hands) for k, v in acc.items()}


def _position(r: dict) -> str:
    """Ahead / level / behind at the moment of the decision -- the context that
    should drive how much risk a player takes."""
    mine = r["points_a"] if r["team"] == 0 else r["points_b"]
    theirs = r["points_b"] if r["team"] == 0 else r["points_a"]
    if mine > theirs + 4:
        return "ahead"
    if theirs > mine + 4:
        return "behind"
    return "level"


def _prob(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return min(max(float(v), 0.0), 1.0)
    return None


def _finalise(a: dict, n_hands: int) -> dict:
    bluffs_answered = a["bluff_folded"] + a["bluff_called"]
    out = {
        "decisions": a["decisions"],
        "seats": sorted(a["seats"]),
        "fallbacks": a["fallbacks"],
        "rejections": a["rejections"],
        "senas_caught": a["senas_caught"],
        # risk
        "aggressive": a["aggressive"],
        "bet_chances": a["bet_chances"],
        "aggression_rate": _rate(a["aggressive"], a["bet_chances"]),
        "bluff_rate": _rate(a["bluffs"], a["aggressive"]),
        # of all the weak hands it held, how often did it push anyway
        "weak_hand_bet_rate": _rate(a["bluffs"], a["bet_chances_weak"]),
        "avg_strength_when_betting": (
            None if not a["strength_n"]
            else round(a["strength_sum"] / a["strength_n"], 3)),
        "value_bet_rate": _rate(a["value_bets"], a["aggressive"]),
        "bluff_success": _rate(a["bluff_folded"], bluffs_answered),
        "value_bet_fold_rate": _rate(a["value_folded"],
                                     a["value_folded"] + a["value_called"]),
        "fold_equity": a["stake_won_folds"] - a["stake_lost_called_bluffs"],
        "stake_won_folds": a["stake_won_folds"],
        "stake_lost_called_bluffs": a["stake_lost_called_bluffs"],
        # responding
        "faced_winning": a["faced_winning"],
        "fold_error_rate": _rate(a["fold_error"], a["faced_winning"]),
        "faced_losing": a["faced_losing"],
        "payoff_rate": _rate(a["payoff"], a["faced_losing"]),
        # reads
        "read_win_n": len(a["read_win"]),
        "read_win_brier": _brier(a["read_win"]),
        "read_win_logloss": _logloss(a["read_win"]),
        "read_win_auc": _auc(a["read_win"]),
        "read_win_brier_early": _brier(a["read_win_early"]),
        "read_win_brier_late": _brier(a["read_win_late"]),
        "read_fold_n": len(a["read_fold"]),
        "read_fold_brier": _brier(a["read_fold"]),
        "read_fold_auc": _auc(a["read_fold"]),
        "read_fold_brier_early": _brier(a["read_fold_early"]),
        "read_fold_brier_late": _brier(a["read_fold_late"]),
        "calibration_win": _calibration(a["read_win"]),
        "by_lance": {k: {"aggressive": v["aggressive"],
                         "bluff_rate": _rate(v["bluffs"], v["aggressive"])}
                     for k, v in sorted(a["by_lance"].items())},
        "by_position": {k: {"aggressive": v["aggressive"],
                            "bluff_rate": _rate(v["bluffs"], v["aggressive"])}
                        for k, v in sorted(a["by_position"].items())},
    }
    for name in ("read_win", "read_fold"):
        e, l = out[f"{name}_brier_early"], out[f"{name}_brier_late"]
        # negative = the read sharpened as the match went on
        out[f"{name}_learning"] = None if (e is None or l is None) else l - e
    return out


def outcome(recs: list[dict]) -> dict:
    """Low-variance match outcome: piedras per hand, not the vaca threshold."""
    hands = [r for r in recs if r.get("kind") == "hand"]
    if not hands:
        return {}
    ga = sum(h["hand_gain_a"] for h in hands)
    gb = sum(h["hand_gain_b"] for h in hands)
    n = len(hands)
    return {
        "hands": n,
        "piedras_a": ga, "piedras_b": gb,
        "piedras_per_hand_a": round(ga / n, 3),
        "piedras_per_hand_b": round(gb / n, 3),
        "piedras_diff_per_hand": round((ga - gb) / n, 3),
        "vacas_a": hands[-1]["vacas_a"], "vacas_b": hands[-1]["vacas_b"],
        "hand_wins_a": sum(1 for h in hands if h["hand_winner"] == 0),
        "hand_wins_b": sum(1 for h in hands if h["hand_winner"] == 1),
    }


# ----------------------------------------------------------------- report ---

def _pct(v):
    return "  --  " if v is None else f"{v * 100:5.1f}%"


def _num(v, nd=3):
    return "  --  " if v is None else f"{v:6.{nd}f}"


def render(cards: dict[str, dict], out: dict) -> str:
    names = sorted(cards)
    w = max((len(n) for n in names), default=8) + 2
    L = []
    if out:
        L.append(f"Outcome over {out['hands']} hands: "
                 f"piedras {out['piedras_a']}-{out['piedras_b']} "
                 f"({out['piedras_diff_per_hand']:+.2f}/hand for A)  "
                 f"vacas {out['vacas_a']}-{out['vacas_b']}  "
                 f"hand wins {out['hand_wins_a']}-{out['hand_wins_b']}")
        L.append("")

    def row(label, fn):
        L.append(f"{label:<28}" + "".join(f"{fn(cards[n]):>{w}}" for n in names))

    L.append(f"{'':<28}" + "".join(f"{n:>{w}}" for n in names))
    L.append("-" * (28 + w * len(names)))
    row("decisions", lambda c: str(c["decisions"]))
    row("betting chances", lambda c: str(c["bet_chances"]))
    row("aggressive actions", lambda c: str(c["aggressive"]))
    L.append("")
    L.append("RISK")
    row("  aggression rate", lambda c: _pct(c["aggression_rate"]))
    row("  avg strength when betting",
        lambda c: _num(c["avg_strength_when_betting"]))
    row("  bluff rate (of bets)", lambda c: _pct(c["bluff_rate"]))
    row("  bets weak hands", lambda c: _pct(c["weak_hand_bet_rate"]))
    row("  bluff success (folded)", lambda c: _pct(c["bluff_success"]))
    row("  fold equity (piedras)", lambda c: f"{c['fold_equity']:+d}")
    row("  fold error rate", lambda c: _pct(c["fold_error_rate"]))
    row("  payoff rate", lambda c: _pct(c["payoff_rate"]))
    L.append("")
    L.append("READ  (lower Brier is better)")
    row("  p_win_lance  n", lambda c: str(c["read_win_n"]))
    row("  p_win_lance  Brier", lambda c: _num(c["read_win_brier"]))
    row("  p_win_lance  AUC", lambda c: _num(c["read_win_auc"]))
    row("    first half", lambda c: _num(c["read_win_brier_early"]))
    row("    second half", lambda c: _num(c["read_win_brier_late"]))
    row("    learning (neg=better)", lambda c: _num(c["read_win_learning"]))
    row("  p_opp_fold   n", lambda c: str(c["read_fold_n"]))
    row("  p_opp_fold   Brier", lambda c: _num(c["read_fold_brier"]))
    row("  p_opp_fold   AUC", lambda c: _num(c["read_fold_auc"]))
    row("    learning (neg=better)", lambda c: _num(c["read_fold_learning"]))
    L.append("")
    L.append("HYGIENE")
    row("  fallbacks", lambda c: str(c["fallbacks"]))
    row("  rejections", lambda c: str(c["rejections"]))
    L.append("")
    L.append("BLUFF RATE BY LANCE")
    for lance in ("Grande", "Chica", "Pares", "Juego"):
        row(f"  {lance}", lambda c, ln=lance: _pct(
            (c["by_lance"].get(ln) or {}).get("bluff_rate")))
    L.append("")
    L.append("BLUFF RATE BY SCORE POSITION")
    for pos in ("behind", "level", "ahead"):
        row(f"  {pos}", lambda c, p=pos: _pct(
            (c["by_position"].get(p) or {}).get("bluff_rate")))
    return "\n".join(L)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+", help="decision JSONL file(s)")
    ap.add_argument("--by-seat", action="store_true",
                    help="one column per seat instead of per model")
    ap.add_argument("--json", action="store_true", help="emit raw JSON")
    args = ap.parse_args()
    recs = []
    for p in args.paths:
        recs.extend(load(p))
    cards = scorecard(recs, key="seat" if args.by_seat else "model")
    out = outcome(recs) if len(args.paths) == 1 else {}
    if args.json:
        print(json.dumps({"outcome": out, "scorecard": cards}, indent=2,
                         default=str))
    else:
        print(render(cards, out))


if __name__ == "__main__":
    main()
