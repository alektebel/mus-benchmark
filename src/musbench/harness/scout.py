"""Scouting: a seat studies its rivals' past hands, then plays them.

Before a v4-scout match, the scouting team's model reads a dossier: up to `k`
hands its rivals played in an earlier tournament, against other opponents.
Each hand shows every public action in order, then all four hands as shown
at the end, the lance winners and the piedras. The rivals' own reasons are
never shown. They were private.

The model writes a short report for itself, and the harness puts it into every
prompt of that match (see `PublicLog.scout` in menu.py). The control arm plays
the same seeds with plain v4-menu prompts, so the report is the only
difference.

Leakage guard: hands from a replay whose seed equals the match seed are
skipped, because the same seed deals the same cards. Scouting runs use seeds
>= 1000 anyway.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from random import Random

from musbench.mus.engine import RANK_GRANDE

REPORT_WORDS = 120
REPORT_MAX_CHARS = 1200


def _ranks(cards) -> str:
    rk = [c.split(" de ")[0] for c in cards]
    return " ".join(sorted(rk, key=lambda r: -RANK_GRANDE.get(r, 0)))


def _load(source) -> list[dict]:
    out = []
    for f in sorted(Path(source).glob("*.json.gz")):
        with gzip.open(f) as fh:
            rp = json.load(fh)
        if rp.get("status") == "done":
            out.append(rp)
    return out


def _hand_text(h: dict, rival_team: int, n: int) -> str:
    # X1/X2 are the scouted player's seats, O1/O2 their opponents (seat order)
    lab = {}
    xs = [s for s in range(4) if s % 2 == rival_team]
    os_ = [s for s in range(4) if s % 2 != rival_team]
    for i, s in enumerate(xs):
        lab[s] = f"X{i + 1}"
    for i, s in enumerate(os_):
        lab[s] = f"O{i + 1}"
    acts = [f"{lab[e['seat']]} {e['public']}" for e in h["events"]
            if e.get("public") and e.get("seat") in lab]
    shown = h.get("showdown") or {}
    cards = " | ".join(f"{lab[int(s)]} {_ranks(c)}" for s, c in sorted(
        shown.items(), key=lambda kv: lab[int(kv[0])]))
    lances = h.get("lances") or {}
    won = ", ".join(f"{L} {'X' if t == rival_team else 'O'}"
                    for L, t in lances.items() if t is not None)
    g = h.get("gain") or [0, 0]
    gx, go = g[rival_team] or 0, g[1 - rival_team] or 0
    return (f"Hand {n} (mano {lab.get(h.get('mano'), '?')}): " + "; ".join(acts)
            + f".\n  Shown: {cards}. Won: {won or 'nothing contested'}. "
              f"Piedras X +{gx}, O +{go}.")


def _bet_count(h: dict, rival_team: int) -> int:
    return sum(1 for e in h["events"] if e.get("seat") is not None
               and e["seat"] % 2 == rival_team and not e.get("auto")
               and e.get("phase") in ("ENVITE", "ORDAGO_RESPONSE"))


def dossier(rival: str, source, k: int = 12, match_seed: int | None = None,
            label: str = "Player X") -> str:
    """Text of up to k hands the rival played in `source` replays."""
    pool = []
    for rp in _load(source):
        if match_seed is not None and rp.get("seed") == match_seed:
            continue                              # same deal: would leak cards
        teams = {s["team"]: s["model"] for s in rp["seats"]}
        for tname, team in (("A", 0), ("B", 1)):
            if teams.get(tname) != rival:
                continue
            for h in rp["hands"]:
                if h.get("showdown"):
                    pool.append((rp["match_id"], h, team))
    if not pool:
        raise SystemExit(f"no replays of {rival!r} to scout in {source}")
    rng = Random(f"{rival}:{match_seed}")
    rng.shuffle(pool)
    # hands where the rival actually bet or answered a bet tell the most
    pool.sort(key=lambda x: -min(_bet_count(x[1], x[2]), 3))
    picked = pool[:k]
    picked.sort(key=lambda x: (x[0], x[1]["hand"]))
    body = "\n".join(_hand_text(h, team, i) for i, (_, h, team) in enumerate(picked, 1))
    return (f"{len(picked)} hands {label} played earlier against other opponents. "
            f"X1 and X2 are {label}'s two seats (both the same player); O1 and O2 "
            f"are their opponents. Each hand lists the public actions in order, then "
            f"every hand as shown at the end and who won each lance.\n{body}")


def report_prompt(dossier_text: str, label: str) -> str:
    from musbench.harness.menu import RULES_V4
    return (f"{RULES_V4}\nYou are about to play a match of mus against {label}: both "
            f"rival seats will be {label}. Study how {label} played before.\n\n"
            f"{dossier_text}\n\n"
            f"Write a scouting report for yourself, at most {REPORT_WORDS} words: how "
            f"{label} bets, bluffs, calls and folds compared with the cards it held, "
            f"and how you will exploit that. It will be in front of you on every "
            f"decision of the match.\n"
            'Reply with JSON only: {"report": "<your notes>"}')


def write_report(agent, dossier_text: str, label: str = "Player X") -> str | None:
    """The scouting team's model writes its report. None if it never gives
    a usable one (the match then ends as no_answer, like an invalid move)."""
    from musbench.harness.menu import ASKS
    if getattr(agent, "provider", "") == "typesafe" or not getattr(agent, "is_llm", False):
        raise ValueError(f"{agent.name} cannot write a scouting report")
    prompt = report_prompt(dossier_text, label)
    ask = prompt
    for _ in range(ASKS):
        data = agent.decide(ask)
        rep = data.get("report") if isinstance(data, dict) else None
        if isinstance(rep, str) and len(rep.strip()) >= 20:
            return rep.strip()[:REPORT_MAX_CHARS]
        if isinstance(data, dict) and "_error" in data:
            problem = data["_error"]
        else:
            problem = 'it has no "report" text of at least a sentence'
        ask = (prompt + f"\n\nYour previous reply could not be used: {problem}. "
               'Submit the report again as exactly one JSON object and nothing else: '
               '{"report": "..."}')
    return None
