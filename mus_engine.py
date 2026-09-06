"""Fournier-aligned mus rules engine (nhfournier.es/como-jugar/mus).

Sources: Fournier "Cómo jugar al mus" + Don Naipe señas (blog 2019).
Key rules implemented:
  - Values: rey/tres/caballo/sota=10, 4-7 natural, dos=as=1.
  - ORDER equivalence: tres ties rey (top), dos ties as (bottom) -> "8 reyes y 8 ases".
  - Pares: par < medias < duples; duples = two pairs OR four of a kind (by mus-rank).
  - Juego 31 > 32 > 40 > 39 > ... > 33; nobody has juego -> Punto (best <= 30, 1 piedra).
  - Mus: one "no hay mus" blocks ALL discards; discards may repeat ("cuantas veces
    lo deseen", capped here at MUS_ROUNDS_MAX with discard recycling).
  - Declarations: Pares and Juego lances open with a truthful "tengo"/"no-tengo"
    round; envites only start if EACH team has a declarer (Juego: if nobody has
    juego, punto envites are open; if one team only, it takes the jugada).
  - Named-bet envite: envido(2) -> y-yo(+2) -> reenvido(x2) -> ordago(all).
    "quiero" locks the stake (jugada compared at lance end).
    "no-quiero" pays the holder the PREVIOUS stake (or 1 deje if none) AND the
    jugada value unconditionally -- declining concedes the jugada (no comparison).
  - Ordago accepted = whole game (40 piedras) on the jugadas compare.
  - Vaca = 40 piedras; counters reset after each vaca; mano rotates every hand.
"""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum, auto
from random import Random

from deck import Card, make_deck

TEAM_OF = {0: 0, 1: 1, 2: 0, 3: 1}

CARD_POINTS = {
    "as": 1, "dos": 1, "tres": 10, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "sota": 10, "caballo": 10, "rey": 10,
}

# mus ordering: rey=tres (9) ... cuatro(3), dos=as (0). "8 reyes y 8 ases".
RANK_MUS = {"as": 0, "dos": 0, "tres": 9, "cuatro": 3, "cinco": 4,
            "seis": 5, "siete": 6, "sota": 7, "caballo": 8, "rey": 9}

JUEGO_TOTALS = tuple(range(31, 41))
JUEGO_RANK = {31: 10, 32: 9, 40: 8, 39: 7, 38: 6, 37: 5, 36: 4, 35: 3, 34: 2, 33: 1}

VACA_TARGET = 40
MUS_ROUNDS_MAX = int(os.environ.get("MUS_ROUNDS_MAX", "2"))
# Fournier allows envites above the game total ("el juego no se gana ni se
# pierde todavia"), but the harness caps raises so betting chains terminate.
ENVITE_MAX = int(os.environ.get("ENVITE_MAX", "40"))

LANCE_NAMES = ["Grande", "Chica", "Pares", "Juego"]
DECLARATION_LANCES = {2, 3}   # Pares and Juego open with tengo/no-tengo


class Phase(Enum):
    MUS_REQUEST = auto()
    MUS_DRAW = auto()
    DECLARE = auto()      # tengo / no-tengo round (Pares, Juego)
    ENVITE = auto()
    ORDAGO_RESPONSE = auto()
    DONE = auto()


class IllegalAction(Exception):
    pass


@dataclass
class JugadaResult:
    name: str
    winner_team: int | None


@dataclass
class EnviteState:
    current: int = 0          # pending (unmatched) stake
    previous: int = 0         # what declining costs (deje 1 if 0)
    holder: int | None = None
    folded: set[int] = field(default_factory=set)
    spoke: set[int] = field(default_factory=set)   # seats that spoke at stake 0
    locked: bool = False      # accepted ("quiero"): no retraction, settled at hand end


class MusEngine:
    def __init__(self, rng: Random | None = None, card_points: dict | None = None):
        self.rng = rng or Random()
        self.card_points = dict(card_points or CARD_POINTS)
        self.juego_totals = JUEGO_TOTALS
        self.reset()

    # ---------------- state ----------------
    def reset(self):
        self.hands: dict[int, list[Card]] = {}
        self.draw_pile: list[Card] = []
        self.discard_pile: list[Card] = []
        self.phase = Phase.MUS_REQUEST
        self._mano_counter = 0
        self.mano = 0
        self.current_seat = 0
        self.mus_want: set[int] = set()
        self.mus_rounds = 0
        self._mus_ordago_declined = False
        self.envite = EnviteState()
        self.declared: dict[int, bool] = {}
        self.lance_index = 0
        self.vacas_a = 0
        self.vacas_b = 0
        self.points_a = 0
        self.points_b = 0
        self.hand_gain_a = 0
        self.hand_gain_b = 0
        self.jugadas: list[JugadaResult] = []
        self.locked_envites: list[tuple[str, int, int]] = []  # (lance, stake, holder)
        self.hand_winner: int | None = None
        self.ordago_caller: int | None = None
        self.ordago_accepted: bool | None = None
        self.ordago_context: str | None = None
        self.vaca_callback = None

    def deal(self):
        self.hands = {}
        self.draw_pile = []
        self.discard_pile = []
        self.phase = Phase.MUS_REQUEST
        self.mano = self._mano_counter
        self._mano_counter = (self._mano_counter + 1) % 4
        self.current_seat = self.mano
        self.mus_want = set()
        self.mus_rounds = 0
        self._mus_ordago_declined = False
        self.envite = EnviteState()
        self.declared = {}
        self.lance_index = 0
        self.hand_gain_a = 0
        self.hand_gain_b = 0
        self.jugadas = []
        self.locked_envites = []
        self.hand_winner = None
        self.ordago_caller = None
        self.ordago_accepted = None
        self.ordago_context = None
        deck = make_deck()
        self.rng.shuffle(deck)
        self.hands = {s: deck[s * 4:(s + 1) * 4] for s in range(4)}
        self.draw_pile = deck[16:]
        return self.hands

    # ---------------- values (mus-rank aware) ----------------
    @staticmethod
    def hand_points(cards, card_points) -> int:
        return sum(card_points.get(c.rank, 0) for c in cards)

    def _grande_value(self, hand):
        return tuple(sorted((RANK_MUS[c.rank] for c in hand), reverse=True))

    def _chica_value(self, hand):
        return tuple(sorted((9 - RANK_MUS[c.rank] for c in hand), reverse=True))

    def _pares_value(self, hand):
        counts = Counter(RANK_MUS[c.rank] for c in hand)
        paired = [r for r, n in counts.items() if n >= 2]
        if any(n >= 4 for n in counts.values()):
            r = next(r for r, n in counts.items() if n >= 4)
            return (3, (r, r))                   # two equal pairs = duples
        if len(paired) >= 2:
            return (3, tuple(sorted(paired, reverse=True)))   # duples
        if len(paired) == 1:
            r = paired[0]
            return (2, (r,)) if counts[r] >= 3 else (1, (r,))
        return (0, ())

    def _juego_value(self, hand):
        total = self.hand_points(hand, self.card_points)
        if total in self.juego_totals:
            return (1, JUEGO_RANK[total])
        return (0, total)

    def _lance_value(self, name, hand):
        if name == "Grande":
            return self._grande_value(hand)
        if name == "Chica":
            return self._chica_value(hand)
        if name == "Pares":
            return self._pares_value(hand)
        return self._juego_value(hand)

    def _team_best(self, hands, team, value_fn):
        players = [hands[s] for s in range(4) if TEAM_OF[s] == team]
        return max(players, key=value_fn)

    def _lance_winner(self, name, hands=None) -> int | None:
        hands = hands or self.hands
        va = self._lance_value(name, self._team_best(hands, 0, lambda h: self._lance_value(name, h)))
        vb = self._lance_value(name, self._team_best(hands, 1, lambda h: self._lance_value(name, h)))
        if va > vb:
            return 0
        if vb > va:
            return 1
        return None

    def compare_jugadas(self, hands=None):
        hands = hands or self.hands
        return [JugadaResult(n, self._lance_winner(n, hands)) for n in LANCE_NAMES]

    def vacas_from_jugadas(self, jugadas=None):
        jugadas = jugadas or self.jugadas
        a = sum(1 for j in jugadas if j.winner_team == 0)
        b = sum(1 for j in jugadas if j.winner_team == 1)
        return a, b

    # ---------------- legal actions ----------------
    def legal_actions(self, seat: int) -> list[str]:
        if self.phase == Phase.MUS_REQUEST:
            if seat != self.current_seat:
                return []
            return (["ordago", "mus", "no"]
                    if seat == self.mano and not self._mus_ordago_declined
                    else ["mus", "no"])
        if self.phase == Phase.MUS_DRAW:
            if seat != self.current_seat or seat not in self.mus_want:
                return []
            return ["discard"]
        if self.phase == Phase.DECLARE:
            if seat != self.current_seat:
                return []
            return ["tengo", "no-tengo"]
        if self.phase == Phase.ENVITE:
            if seat != self.current_seat or seat in self.envite.folded:
                return []
            if self.envite.current == 0:
                return ["paso", "envido", "ordago"]
            can_raise = self.envite.current < ENVITE_MAX
            own = self.envite.holder is not None and \
                TEAM_OF[seat] == TEAM_OF[self.envite.holder]
            if own:
                # holder's side: may raise its own bet or pass (eliminating self)
                acts = ["paso", "ordago"]
                if can_raise:
                    acts.insert(1, "y-yo")
                    if self.envite.current >= 4:
                        acts.insert(2, "reenvido")
                return acts
            acts = ["quiero", "no-quiero", "ordago"]
            if can_raise:
                acts.insert(2, "y-yo")
                if self.envite.current >= 4:
                    acts.insert(3, "reenvido")
            return acts
        if self.phase == Phase.ORDAGO_RESPONSE:
            if seat != self.current_seat:
                return []
            return ["quiero", "no-quiero"]
        return []

    # ---------------- apply ----------------
    def apply(self, seat: int, action: dict) -> None:
        if seat != self.current_seat:
            raise IllegalAction(f"not seat {seat}'s turn (current={self.current_seat})")
        name = action.get("action")
        if name not in self.legal_actions(seat):
            raise IllegalAction(f"illegal action '{name}' in phase {self.phase.name}")
        if self.phase == Phase.MUS_REQUEST:
            self._apply_mus_request(seat, name)
        elif self.phase == Phase.MUS_DRAW:
            self._apply_draw(seat, action)
        elif self.phase == Phase.DECLARE:
            self._apply_declare(seat, name)
        elif self.phase == Phase.ENVITE:
            self._apply_envite(seat, name)
        elif self.phase == Phase.ORDAGO_RESPONSE:
            self._apply_ordago_response(seat, name)

    # ---- MUS ----
    def _apply_mus_request(self, seat, name):
        if name == "ordago":
            self.ordago_caller = seat
            self.ordago_context = "mus_request"
            self.phase = Phase.ORDAGO_RESPONSE
            self.current_seat = (seat + 1) % 4
        elif name == "mus":
            self.mus_want.add(seat)
            self._advance_request()
        elif name == "no":
            self._start_lances()          # "No hay mus": nobody discards

    def _advance_request(self):
        nxt = (self.current_seat + 1) % 4
        if nxt == self.mano:
            self._start_draw()
        else:
            self.current_seat = nxt

    def _start_draw(self):
        self.mus_rounds += 1
        self.phase = Phase.MUS_DRAW
        self.current_seat = min(self.mus_want, key=lambda s: (s - self.mano) % 4)

    def _apply_draw(self, seat, action):
        cards = action.get("cards")
        if not isinstance(cards, list):
            raise IllegalAction("discard requires a 'cards' list")
        discard = self._resolve_discard(seat, cards)
        if not (1 <= len(discard) <= 4):
            raise IllegalAction("must discard between 1 and 4 cards")
        self._redraw(seat, discard)
        self.mus_want.discard(seat)
        if self.mus_want:
            self.current_seat = min(self.mus_want, key=lambda s: (s - self.mano) % 4)
        else:
            self._after_draw()

    def _after_draw(self):
        if self.mus_rounds < MUS_ROUNDS_MAX:
            # discards may repeat: new mus round
            self.phase = Phase.MUS_REQUEST
            self._mus_ordago_declined = False
            self.mus_want = set()
            self.current_seat = self.mano
        else:
            self._start_lances()

    def _redraw(self, seat, discard):
        for d in discard:
            self.hands[seat].remove(d)
            self.discard_pile.append(d)
            if not self.draw_pile:
                self.rng.shuffle(self.discard_pile)
                self.draw_pile = self.discard_pile
                self.discard_pile = []
            self.hands[seat].append(self.draw_pile.pop())

    def _resolve_discard(self, seat, names) -> list[Card]:
        hand = self.hands[seat]
        out = []
        for n in names:
            if not isinstance(n, str) or not n.strip():
                raise IllegalAction("discard card names must be nonempty strings")
            name = n.strip().lower()
            matches = [c for c in hand if c not in out and self._match_name(c, name)]
            if not matches:
                raise IllegalAction(f"discard card not available: {n!r}")
            out.extend(matches)
        return out

    @staticmethod
    def _match_name(card: Card, name: str) -> bool:
        s = str(card).strip().lower()
        return s == name or name in s or card.rank.lower() == name

    # ---- LANCES ----
    def _start_lances(self):
        self.phase = Phase.ENVITE
        self.lance_index = 0
        self.envite = EnviteState()
        self.current_seat = self.mano
        self._begin_lance()

    def _begin_lance(self):
        """Route the new lance: Pares/Juego start with a declaration round."""
        if self.lance_index in DECLARATION_LANCES:
            self.phase = Phase.DECLARE
            self.declared = {}
        else:
            self.phase = Phase.ENVITE
        self.current_seat = self.mano

    def _apply_declare(self, seat, name):
        has = name == "tengo"
        lance = LANCE_NAMES[self.lance_index]
        truthful = (self._pares_value(self.hands[seat])[0] > 0 if lance == "Pares"
                    else self.hand_points(self.hands[seat], self.card_points) in self.juego_totals)
        if has != truthful:
            raise IllegalAction(
                f"false declaration: declare {'tengo' if truthful else 'no-tengo'} for {lance.lower()}")
        self.declared[seat] = has
        nxt = (self.current_seat + 1) % 4
        if len(self.declared) == 4:
            self._resolve_declarations()
        else:
            self.current_seat = nxt

    def _resolve_declarations(self):
        lance = LANCE_NAMES[self.lance_index]
        t0 = any(self.declared[s] for s in (0, 2))
        t1 = any(self.declared[s] for s in (1, 3))
        if t0 and t1:
            self.envite = EnviteState()
            self.phase = Phase.ENVITE
            self.current_seat = self.mano
        elif t0 or t1:
            w = 0 if t0 else 1
            self._award_lance(lance, w)          # uncontested jugada value
            self.jugadas.append(JugadaResult(lance, w))
            self._advance_lance()
        else:
            if lance == "Pares":
                self.jugadas.append(JugadaResult(lance, None))   # nothing to play
                self._advance_lance()
            else:                                # nobody has juego -> punto envites
                self.envite = EnviteState()
                self.phase = Phase.ENVITE
                self.current_seat = self.mano

    # ---- ENVITE (named bets) ----
    def _apply_envite(self, seat, name):
        e = self.envite
        if name == "paso":
            if e.current > 0:
                e.folded.add(seat)            # pass after an envite = eliminated
                nxt = self._next_unfolded(seat)
                if nxt == self.envite.holder and all(
                        TEAM_OF[s] == TEAM_OF[self.envite.holder]
                        for s in range(4) if s not in e.folded):
                    self._end_lance_envite(matched=True)
                else:
                    self.current_seat = nxt
                return
            e.spoke.add(seat)
            nxt = self._next_unfolded(seat)
            if len(e.spoke) == 4:
                self._end_lance_pass()
            else:
                self.current_seat = nxt
        elif name == "envido":
            e.previous, e.current, e.holder = 0, 2, seat
            e.spoke = set()
            self._advance_envite_seat(seat)
        elif name == "y-yo":
            e.previous, e.current = e.current, e.current + 2
            e.holder = seat
            e.spoke = set()
            self._advance_envite_seat(seat)
        elif name == "reenvido":
            e.previous, e.current = e.current, e.current * 2
            e.holder = seat
            e.spoke = set()
            self._advance_envite_seat(seat)
        elif name == "quiero":
            # Accepted: the bet is locked (no retraction). Cards are compared
            # when the hand is shown at the end of the juego parcial.
            e.locked = True
            self.locked_envites.append((LANCE_NAMES[self.lance_index],
                                        e.current, e.holder))
            self.jugadas.append(JugadaResult(LANCE_NAMES[self.lance_index], None))
            self._advance_lance()
        elif name == "no-quiero":
            self._settle_decline()
        elif name == "ordago":
            self.ordago_caller = seat
            self.ordago_context = "envite"
            self.phase = Phase.ORDAGO_RESPONSE
            self.current_seat = (seat + 1) % 4

    def _advance_envite_seat(self, seat):
        nxt = self._next_unfolded(seat)
        if nxt == self.envite.holder and self.envite.current > 0:
            # nobody accepted or declined: bet locked, settled at showdown
            e2 = self.envite
            e2.locked = True
            self.locked_envites.append((LANCE_NAMES[self.lance_index],
                                        e2.current, e2.holder))
            self.jugadas.append(JugadaResult(LANCE_NAMES[self.lance_index], None))
            self._advance_lance()
        else:
            self.current_seat = nxt

    def _next_unfolded(self, seat):
        nxt = (seat + 1) % 4
        for _ in range(4):
            if nxt not in self.envite.folded:
                return nxt
            nxt = (nxt + 1) % 4
        return nxt

    def _end_lance_pass(self):
        """All seats passed at stake 0: best jugada takes its value (en paso)."""
        name = LANCE_NAMES[self.lance_index]
        winner = self._lance_winner(name)
        if winner is not None:
            self._award_lance(name, winner)
        self.jugadas.append(JugadaResult(name, winner))
        self._advance_lance()

    def _settle_decline(self):
        """No-quiero: holder takes previous stake (or 1 deje) AND the jugada."""
        name = LANCE_NAMES[self.lance_index]
        holder_team = TEAM_OF[self.envite.holder]
        stake = self.envite.previous if self.envite.previous > 0 else 1
        self._add_points(holder_team, stake)
        self._award_lance(name, holder_team)     # jugada conceded, no comparison
        self.jugadas.append(JugadaResult(name, holder_team))
        self._advance_lance()

    def _settle_locked_envites(self):
        """Showdown: cards are seen and every locked (accepted) envite is
        collected -- the JUGADA WINNER takes the stake plus the jugada value."""
        for name, stake, holder in self.locked_envites:
            winner = self._lance_winner(name)
            if winner is not None:
                self._add_points(winner, stake)
                self._award_lance(name, winner)
            for j in self.jugadas:               # record the showdown winner
                if j.name == name and j.winner_team is None:
                    j.winner_team = winner
                    break

    def _advance_lance(self):
        self.lance_index += 1
        if self.lance_index >= len(LANCE_NAMES):
            self._settle_locked_envites()
            self._apply_vaca()
            self.phase = Phase.DONE
            self._set_hand_winner()
        else:
            self.envite = EnviteState()
            self._begin_lance()

    def _award_lance(self, name, winner_team):
        if name == "Grande":
            self._add_points(winner_team, 1)
        elif name == "Chica":
            self._add_points(winner_team, 1)
        elif name == "Pares":
            self._award_pares(winner_team)
        elif name == "Juego":
            self._award_juego(winner_team)

    def _award_pares(self, winner_team):
        for s in range(4):
            if TEAM_OF[s] != winner_team:
                continue
            p = self._pares_value(self.hands[s])
            if p[0] == 3:
                self._add_points(winner_team, 3)
            elif p[0] == 2:
                self._add_points(winner_team, 2)
            elif p[0] == 1:
                self._add_points(winner_team, 1)

    def _award_juego(self, winner_team):
        players = [s for s in range(4) if TEAM_OF[s] == winner_team]
        has_juego = any(self.hand_points(self.hands[s], self.card_points) in self.juego_totals
                        for s in players)
        if has_juego:
            for s in players:
                total = self.hand_points(self.hands[s], self.card_points)
                if total in self.juego_totals:
                    self._add_points(winner_team, 3 if total == 31 else 2)
        else:
            self._add_points(winner_team, 1)     # punto

    def _add_points(self, team, tantos):
        if team == 0:
            self.points_a += tantos
            self.hand_gain_a += tantos
        else:
            self.points_b += tantos
            self.hand_gain_b += tantos

    def _apply_vaca(self):
        va, vb = self.points_a // VACA_TARGET, self.points_b // VACA_TARGET
        self.vacas_a += va
        self.vacas_b += vb
        if va or vb:
            self.points_a = 0
            self.points_b = 0
        if self.vaca_callback and (va or vb):
            self.vaca_callback(va, vb, self.vacas_a, self.vacas_b)

    def _set_hand_winner(self):
        if self.hand_gain_a > self.hand_gain_b:
            self.hand_winner = 0
        elif self.hand_gain_b > self.hand_gain_a:
            self.hand_winner = 1
        else:
            self.hand_winner = None

    # ---- ORDAGO ----
    def _apply_ordago_response(self, seat, name):
        self.ordago_accepted = (name == "quiero")
        if name == "quiero":
            self._resolve_ordago()
        else:
            self._resolve_ordago_declined()
        self.ordago_caller = None
        self.ordago_accepted = None

    def _resolve_ordago(self):
        self._settle_locked_envites()
        self.jugadas = self.compare_jugadas()
        va, vb = self.vacas_from_jugadas(self.jugadas)
        if va == vb:
            w = self._lance_winner("Grande")
            if w is None:
                self._add_points(0, VACA_TARGET // 2)
                self._add_points(1, VACA_TARGET // 2)
            else:
                self._add_points(w, VACA_TARGET)
        else:
            self._add_points(0 if va > vb else 1, VACA_TARGET)
        self._apply_vaca()
        self.phase = Phase.DONE
        self._set_hand_winner()

    def _resolve_ordago_declined(self):
        caller = self.ordago_caller
        if self.ordago_context == "mus_request":
            # Nothing staked pre-mus: caller must still consent to discards.
            self.phase = Phase.MUS_REQUEST
            self.current_seat = caller
            self._mus_ordago_declined = True
            return
        holder_team = TEAM_OF[self.envite.holder] if self.envite.holder is not None \
            else TEAM_OF[caller]
        name = LANCE_NAMES[self.lance_index]
        stake = self.envite.previous if self.envite.previous > 0 else 1
        # the ordago caller becomes the holder of the pending stake
        self._add_points(TEAM_OF[caller], stake)
        self._award_lance(name, TEAM_OF[caller])
        self.jugadas.append(JugadaResult(name, TEAM_OF[caller]))
        self._advance_lance()
