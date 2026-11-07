"""Self-written memory across a vaca.

The turn feed spans one vaca. A vaca resets both scores to zero, and the
question this module makes measurable is what -- if anything -- should survive
that boundary.

Two arms, selected with VACA_MEMORY:

  off    nothing crosses. Each vaca is a fresh table, and the turn feed that
         was accumulating is cleared with the scores.
  notes  at the vaca the seat is asked to write ITSELF a short note, and that
         note is prepended to its prompts for the next vaca.

This is orthogonal to what a seat sees WITHIN a vaca, which is either the raw
turn feed (`turn_feed.py`) or the harness-written rival dossier
(`match_history.py`). The dossier is identical in form for every model, so it
measures whether a model can USE a read someone else computed; a self-written
note measures whether it can FORM one and carry it. The second is the more
interesting claim and the weaker evidence -- an improvement there could
equally be the extra context tokens -- so `off` is the control and the arms
must be run on the same seeds.

Two rules make the note safe rather than a hole in the experiment:

  PRIVATE  a note is per-seat and is NEVER shown to the partner. Partners
           cannot see each other's cards; a shared scratchpad would be an
           unlimited covert channel straight past the seña constraint, which
           is the one thing this benchmark exists to measure.
  CAPPED   truncated to VACA_NOTE_CHARS. An uncapped note lets a seat copy its
           whole hand history forward and quietly become a different
           experiment.

Every note is logged verbatim with the prompt that produced it.
"""
from __future__ import annotations

import json
import os

VACA_MEMORY = os.environ.get("VACA_MEMORY", "off").strip().lower()
VACA_NOTE_CHARS = int(os.environ.get("VACA_NOTE_CHARS", "700"))

VALID_MODES = ("off", "notes", "dossier")


def mode() -> str:
    return VACA_MEMORY if VACA_MEMORY in VALID_MODES else "off"


class NoteBook:
    """One private note per seat, replaced at each vaca."""

    def __init__(self, cap: int = VACA_NOTE_CHARS):
        self.cap = cap
        self.notes: dict[int, str] = {}
        self.history: list[dict] = []      # every note ever written, for audit

    def set(self, seat: int, text: str | None, *, vaca: int,
            raw: str | None = None) -> str | None:
        clean = (text or "").strip()
        if not clean:
            return None
        truncated = len(clean) > self.cap
        clean = clean[: self.cap]
        self.notes[seat] = clean
        self.history.append({"vaca": vaca, "seat": seat, "note": clean,
                             "truncated": truncated, "raw": raw})
        return clean

    def get(self, seat: int) -> str | None:
        return self.notes.get(seat)

    def render(self, seat: int) -> list[str]:
        note = self.get(seat)
        if not note:
            return []
        return ["YOUR NOTES TO YOURSELF (written by you at the end of the last "
                "vaca; your partner has not seen them):", note]


def reflection_prompt(agent, feed_rows: list[dict], *, vaca: int,
                      points_mine: int, points_theirs: int,
                      previous: str | None, cap: int = VACA_NOTE_CHARS) -> str:
    """Ask a seat to write its own carry-forward note. No game action here."""
    lines = [
        f"You are {agent.name}, seat {agent.seat}, team {agent.team}. "
        f"A vaca has just been decided ({points_mine} piedras to your team, "
        f"{points_theirs} to the rivals) and both scores reset to zero.",
        "",
        "This is NOT a game turn. Nothing you write here is played, spoken, or "
        "shown to anyone -- not even to your partner. It is a private note "
        "that will be given back to you during the next vaca, and it is the "
        "ONLY thing you may carry across this boundary: the turn feed is about "
        "to be cleared.",
        "",
        "Here is every turn of the vaca that just ended, as you saw it "
        "(your own turns include your private thought):",
    ]
    lines += [json.dumps(r, ensure_ascii=False, sort_keys=True)
              for r in feed_rows] or ["(no turns recorded)"]
    if previous:
        lines += ["", "Your note from the previous vaca (replace or revise it):",
                  previous]
    lines += [
        "",
        f"Write what is worth knowing about THESE TWO RIVALS and about your "
        f"own partner for the next vaca: how they bet, when they fold, whether "
        f"their table talk tracks their cards, which señas your partner seems "
        f"to be using. Be concrete and specific to the seats -- a generic mus "
        f"tip is worthless here.",
        f"Hard limit {cap} characters; anything past it is cut.",
        "",
        'Answer with ONLY a JSON object: {"notes": "<your note>"}',
    ]
    return "\n".join(lines)


def extract_note(reply) -> str | None:
    if not isinstance(reply, dict):
        return None
    for key in ("notes", "note", "memory"):
        v = reply.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None
