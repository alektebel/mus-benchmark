"""Per-model mus skills from replays, scored against engine ground truth.

Every decision in a replay carries `would_win` (does this seat's team win the
current lance with the cards as they are?) and `strength` (the hand's
percentile at this lance). That lets each kind of decision be marked right or
wrong after the fact, independent of how the hand turned out.

Skills (each over the model's own, non-automatic decisions):
  fold_accuracy   no-quiero when facing a bet: share of folds of a LOSING lance
  call_accuracy   quiero when facing a bet: share of calls of a WINNING lance
  bluff_rate      bets/raises made from the bottom third of hands
  bluff_success   of those bluffs, share of lances the team then took
  value_rate      bets/raises made from the top third of hands
  ordago_wins     órdagos called that the cards would have won
  lance_<L>       share of lances L (Grande, Chica, Pares, Juego) won by the team
  reads           share of reasons that read the rivals (bluff, shown strength…)
  partner         share of reasons that reason about the partner
  sec_per_move    mean wall time per decision
"""
from __future__ import annotations

import re
from collections import defaultdict

AGGRESSIVE = {"envido", "y-yo", "reenvido", "ordago"}
LANCES = ("Grande", "Chica", "Pares", "Juego")
READ_RE = re.compile(r"bluff|farol|faroleando|read|signal|suggest|shown strength|probably|"
                     r"likely (has|holds)|rival.{0,24}(has|hold|show|bet)|"
                     r"seat \d.{0,30}(bet|órdago|ordago|cut|pass)|"
                     r"(rival|contrario|oponente).{0,30}(tiene|apuesta|corta|pasa)", re.I)
PARTNER_RE = re.compile(r"partner|compañer", re.I)

SKILLS = {
    "fold_accuracy": ("Fold accuracy", "%", "of its folds gave up a lance it would have lost"),
    "call_accuracy": ("Call accuracy", "%", "of its calls were on a lance it would win"),
    "bluff_success": ("Bluff success", "%", "of bets from a weak hand still took the lance"),
    "value_rate": ("Value betting", "%", "of its bets came from a top-third hand"),
    "ordago_wins": ("Órdago judgement", "%", "of the órdagos it called had the cards to win"),
    "lance_Grande": ("Grande", "%", "of Grande lances won by its team"),
    "lance_Chica": ("Chica", "%", "of Chica lances won by its team"),
    "lance_Pares": ("Pares", "%", "of Pares lances won by its team"),
    "lance_Juego": ("Juego", "%", "of Juego/Punto lances won by its team"),
    "reads": ("Reading rivals", "%", "of its reasons read the rivals' behaviour"),
    "partner": ("Partner play", "%", "of its reasons weigh what the partner holds or does"),
}


def _ratio(num, den):
    return (num / den) if den else None


def compute(replays: list[dict]) -> dict[str, dict]:
    c = defaultdict(lambda: defaultdict(float))
    for rp in replays:
        seats = {s["seat"]: s["model"] for s in rp["seats"]}
        in_match = set(seats.values())
        for h in rp["hands"]:
            lances = h.get("lances") or {}
            for m in in_match:
                team = 0 if seats[0] == m else 1
                for L in LANCES:
                    if lances.get(L) is not None:
                        c[m][f"lance_{L}_n"] += 1
                        c[m][f"lance_{L}_w"] += lances[L] == team
            prev_t = None
            for e in h["events"]:
                t = e.get("t")
                m = seats.get(e.get("seat"))
                if m is None or e.get("auto"):
                    prev_t = t if t is not None else prev_t
                    continue
                if t is not None and prev_t is not None and t >= prev_t:
                    c[m]["sec"] += t - prev_t
                    c[m]["sec_n"] += 1
                prev_t = t if t is not None else prev_t
                a, ww, st = e.get("action"), e.get("would_win"), e.get("strength")
                c[m]["moves"] += 1
                facing = e.get("phase") == "ORDAGO_RESPONSE" or (
                    e.get("phase") == "ENVITE" and (e.get("stake") or 0) > 0)
                if facing and ww is not None:
                    if a == "no-quiero":
                        c[m]["fold_n"] += 1
                        c[m]["fold_ok"] += not ww
                    elif a == "quiero":
                        c[m]["call_n"] += 1
                        c[m]["call_ok"] += bool(ww)
                if a in AGGRESSIVE and st is not None:
                    c[m]["bets"] += 1
                    team = e["seat"] % 2
                    took = lances.get(e.get("lance")) == team
                    if st < 1 / 3:
                        c[m]["bluffs"] += 1
                        c[m]["bluff_won"] += took
                    if st >= 2 / 3:
                        c[m]["value"] += 1
                if a == "ordago" and ww is not None:
                    c[m]["ord_n"] += 1
                    c[m]["ord_ok"] += bool(ww)
                why = e.get("thought") or ""
                if why:
                    c[m]["why_n"] += 1
                    c[m]["reads"] += bool(READ_RE.search(why))
                    c[m]["partner"] += bool(PARTNER_RE.search(why))
    out = {}
    for m, x in c.items():
        r = {
            "moves": int(x["moves"]),
            "fold_accuracy": _ratio(x["fold_ok"], x["fold_n"]), "fold_n": int(x["fold_n"]),
            "call_accuracy": _ratio(x["call_ok"], x["call_n"]), "call_n": int(x["call_n"]),
            "bluff_rate": _ratio(x["bluffs"], x["bets"]),
            "bluff_success": _ratio(x["bluff_won"], x["bluffs"]), "bluff_n": int(x["bluffs"]),
            "value_rate": _ratio(x["value"], x["bets"]), "bet_n": int(x["bets"]),
            "ordago_wins": _ratio(x["ord_ok"], x["ord_n"]), "ordago_n": int(x["ord_n"]),
            "reads": _ratio(x["reads"], x["why_n"]),
            "partner": _ratio(x["partner"], x["why_n"]), "why_n": int(x["why_n"]),
            "sec_per_move": _ratio(x["sec"], x["sec_n"]),
        }
        for L in LANCES:
            r[f"lance_{L}"] = _ratio(x[f"lance_{L}_w"], x[f"lance_{L}_n"])
            r[f"lance_{L}_n"] = int(x[f"lance_{L}_n"])
        out[m] = r
    return out
