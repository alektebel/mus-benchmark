"""Self-contained replays of benchmark matches, for viewers and animation.

One gzipped JSON per match in benchmark/replays/<tournament>/, built from the
harness result and its per-decision log. Everything needed to redraw the
match is inside: who sat where, the cards dealt, every decision in order
(options offered, the choice, the one-line reason, cards changed and drawn,
the stake, the score after it), the showdown and the lance results. Ground
truth fields (`would_win`, `strength`) are included for commentary; a viewer
replaying "as the table saw it" should hide them and the other seats' cards.

Format `mus-replay/1`:
  {format, match_id, tournament, protocol, commit, seed, status, started_at,
   finished_at, seats: [{seat, team, model, spec, name}], settings,
   result: {piedras_a, piedras_b, vacas_a, vacas_b, hands_completed},
   hands: [{hand, mano, dealt{seat: cards}, events: [...], showdown{seat: cards},
            lances{lance: team}, truth{lance: team}, locked_envites, gain[a, b],
            points_after[a, b], vacas_after[a, b]}]}
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

FORMAT = "mus-replay/1"
_EVENT_KEYS = ("turn", "t", "wall", "seat", "team", "phase", "stage", "lance",
               "action", "public", "thought", "options", "menu_size", "auto",
               "fallback", "drew", "stake", "holder", "facing_bet",
               "points_after", "points_delta", "would_win", "strength")


def build(result: dict, decisions: list[dict], *, match_id: str,
          tournament: str, seats: list[dict], commit: str,
          finished_at: str) -> dict:
    hands: dict[int, dict] = {}
    for rec in decisions:
        h = rec.get("hand")
        if h is None:
            continue
        slot = hands.setdefault(h, {"hand": h, "events": []})
        if rec.get("kind") == "decision":
            ev = {k: rec.get(k) for k in _EVENT_KEYS if rec.get(k) is not None}
            raw = rec.get("raw_action") or {}
            if raw.get("cards"):
                ev["cards"] = raw["cards"]
            if "mano" not in slot and rec.get("mano") is not None:
                slot["mano"] = rec["mano"]
            if "dealt" not in slot and rec.get("hands"):
                slot.setdefault("_first_seen", rec["hands"])
            slot["events"].append(ev)
        elif rec.get("kind") == "hand":
            slot.update({
                "mano": rec.get("mano"),
                "dealt": rec.get("dealt") or slot.get("_first_seen"),
                "showdown": rec.get("hands"),
                "lances": rec.get("jugadas"),
                "truth": rec.get("jugada_truth"),
                "locked_envites": rec.get("locked_envites"),
                "gain": [rec.get("hand_gain_a"), rec.get("hand_gain_b")],
                "points_after": [rec.get("points_a"), rec.get("points_b")],
                "vacas_after": [rec.get("vacas_a"), rec.get("vacas_b")],
                "ordago_caller": rec.get("ordago_caller"),
            })
    ordered = []
    for h in sorted(hands):
        slot = hands[h]
        slot.pop("_first_seen", None)
        ordered.append(slot)
    walls = [e.get("wall") for hd in ordered for e in hd["events"] if e.get("wall")]
    return {
        "format": FORMAT, "match_id": match_id, "tournament": tournament,
        "protocol": result.get("protocol"), "commit": commit,
        "seed": result.get("seed"), "status": result.get("status"),
        "abort_reason": result.get("abort_reason"),
        "started_at": min(walls) if walls else None, "finished_at": finished_at,
        "seats": seats, "settings": result.get("settings"),
        "result": {k: result.get(k) for k in ("piedras_a", "piedras_b", "vacas_a",
                                               "vacas_b", "hands_completed", "hands")},
        "usage": result.get("usage"),
        "hands": ordered,
    }


def load_decisions(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write(replay: dict, root: Path) -> Path:
    out = root / replay["tournament"] / f"{replay['match_id']}.json.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf8") as f:
        json.dump(replay, f, ensure_ascii=False, separators=(",", ":"))
    return out


def read(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf8") as f:
        return json.load(f)
