"""Declarative sena policies, interpreted by the kernel. Each seat owns one.

A seat *declares* when it will gesture (rule objects or JSON); it never ships
executable code. The kernel evaluates the rules against the seat's own hand
and the live engine view at the start of every decision window, so policies
stay inspectable, diffable and seed-stable.

Semantics faithful to the reglamento:
  * only the fixed `SENAS` vocabulary is permitted (a sena means exactly the
    hand-shape in `senas.py`, nothing custom);
  * a rule fires only when the gesture is TRUE of the sender's hand at
    publish time -- unless bluffs are allowed, in which case false gestures
    count against the sender's credibility like the public variant;
  * `when_deciding: "partner"` reflects the point of a sena: it informs the
    partner's DELIBERATION, so a gesture is addressed to the partner and
    timed inside (or just before) the partner's window.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from mus_engine import Phase, LANCE_NAMES
from senas import SENAS, sena_truthful

WILDCARD = "*"
PHASE_NAMES = {p.name for p in Phase} | {"*"}
LANCE_OR_WILDCARD = set(LANCE_NAMES) | {"*"}
DECIDING_TARGETS = {"partner", "any"}

DEFAULT_OFFSET = float(os.environ.get("SENA_DEFAULT_OFFSET", "0.15"))
# Units are virtual decision-windows. The addressee's NEXT decision arrives
# roughly one full table rotation (~4 windows) later, so a sena meant to be
# caught must outlive that gap.
DEFAULT_TTL = float(os.environ.get("SENA_DEFAULT_TTL", "5.0"))
MAX_OFFSET = 0.95          # gestures land strictly inside the window
MAX_TTL = 20.0             # windows are unit-scale; longer crosses hands


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class SignalRule:
    gesture: str
    when_phase: str = WILDCARD
    when_lance: str = WILDCARD
    when_deciding: str = "partner"   # partner | any
    offset: float = DEFAULT_OFFSET   # fraction of the deciding window
    ttl: float = DEFAULT_TTL
    bluff: bool = False              # fire even when the gesture is false

    def __post_init__(self):
        g = str(self.gesture).strip().lower()
        if g not in SENAS:
            raise PolicyError(f"not a reglamentaria sena: {self.gesture!r}")
        if self.when_phase not in PHASE_NAMES:
            raise PolicyError(f"unknown phase {self.when_phase!r}")
        if self.when_lance not in LANCE_OR_WILDCARD:
            raise PolicyError(f"unknown lance {self.when_lance!r}")
        if self.when_deciding not in DECIDING_TARGETS:
            raise PolicyError(f"when_deciding must be one of {sorted(DECIDING_TARGETS)}")
        if not (0.0 <= self.offset <= MAX_OFFSET):
            raise PolicyError(f"offset must be in [0, {MAX_OFFSET}], got {self.offset}")
        if not (0.0 < self.ttl <= MAX_TTL):
            raise PolicyError(f"ttl must be in (0, {MAX_TTL}], got {self.ttl}")
        if not isinstance(self.bluff, bool):
            raise PolicyError("'bluff' must be a boolean")
        object.__setattr__(self, "gesture", g)


@dataclass
class SignalPolicy:
    rules: tuple[SignalRule, ...] = ()
    enabled: bool = True

    @classmethod
    def from_json(cls, obj) -> "SignalPolicy":
        if not isinstance(obj, dict):
            raise PolicyError("policy must be a JSON object")
        raw_rules = obj.get("rules")
        if not isinstance(raw_rules, list):
            raise PolicyError("policy needs a 'rules' list")
        if len(raw_rules) > 16:
            raise PolicyError("policy exceeds 16 rules")
        rules = []
        for r in raw_rules:
            if not isinstance(r, dict):
                raise PolicyError("each rule must be a JSON object")
            unknown = set(r) - {"gesture", "when_phase", "when_lance",
                                 "when_deciding", "offset", "ttl", "bluff"}
            if unknown:
                raise PolicyError(f"unknown rule fields: {sorted(unknown)}")
            try:
                rules.append(SignalRule(
                    gesture=r["gesture"],
                    when_phase=r.get("when_phase", WILDCARD),
                    when_lance=r.get("when_lance", WILDCARD),
                    when_deciding=r.get("when_deciding", "partner"),
                    offset=float(r.get("offset", DEFAULT_OFFSET)),
                    ttl=float(r.get("ttl", DEFAULT_TTL)),
                    bluff=r.get("bluff", False)))
            except (KeyError, TypeError, ValueError) as e:
                raise PolicyError(f"bad rule: {e}") from e
        enabled = obj.get("enabled", True)
        if not isinstance(enabled, bool):
            raise PolicyError("'enabled' must be a boolean")
        return cls(rules=tuple(rules), enabled=enabled)

    def to_json(self) -> dict:
        return {"enabled": self.enabled,
                "rules": [{"gesture": r.gesture, "when_phase": r.when_phase,
                           "when_lance": r.when_lance,
                           "when_deciding": r.when_deciding,
                           "offset": r.offset, "ttl": r.ttl,
                           "bluff": r.bluff}
                          for r in self.rules]}


def reference_policy() -> SignalPolicy:
    """Offline floor: gesture whenever a reglamentaria sena is true of the
    hand and the partner is about to deliberate."""
    return SignalPolicy(rules=tuple(SignalRule(g) for g in SENAS))


def silent_policy() -> SignalPolicy:
    return SignalPolicy(rules=())


def partner_of(seat: int) -> int:
    return (seat + 2) % 4


@dataclass
class PublishIntent:
    gesture: str
    t_pub: float
    ttl: float
    truthful: bool


@dataclass
class SignalManager:
    """Per-seat seña actor: owns the policy, counts bluffs and rejected
    policy installs. Evaluated by the kernel once per decision window."""
    seat: int
    policy: SignalPolicy = field(default_factory=silent_policy)
    allow_bluffs: bool = False
    published: int = 0
    bluffs: int = 0
    invalid_policies: int = 0
    dropped_false: int = 0

    def install_policy(self, obj) -> bool:
        try:
            self.policy = SignalPolicy.from_json(obj)
            return True
        except PolicyError:
            self.invalid_policies += 1
            return False

    def evaluate(self, engine, deciding_seat: int, t0: float,
                 window: float, bus=None) -> list[PublishIntent]:
        """Return gestures this seat makes given that `deciding_seat` is
        about to spend `window` virtual time deliberating."""
        if not self.policy.enabled or not self.policy.rules:
            return []
        hand = engine.hands.get(self.seat)
        if not hand:
            return []
        partner = partner_of(self.seat)
        phase_name = engine.phase.name
        lance = (LANCE_NAMES[engine.lance_index]
                 if phase_name in ("ENVITE", "DECLARE") else None)
        intents = []
        for rule in self.policy.rules:
            if rule.when_phase != WILDCARD and rule.when_phase != phase_name:
                continue
            if rule.when_lance != WILDCARD:
                if lance is None or rule.when_lance != lance:
                    continue
            if rule.when_deciding == "partner" and deciding_seat != partner:
                continue
            truthful = sena_truthful(rule.gesture, hand, engine)
            if not truthful:
                if not (rule.bluff and self.allow_bluffs):
                    self.dropped_false += 1
                    continue
                self.bluffs += 1
            if bus is not None and bus.gesture_live(self.seat, rule.gesture, t0):
                continue    # partner already caught it, or it is still in flight
            intents.append(PublishIntent(rule.gesture, t0 + rule.offset * window,
                                         rule.ttl, truthful))
        return intents
