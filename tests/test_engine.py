import importlib
import contextlib
import io
import unittest
from random import Random
from unittest.mock import patch

from musbench.agents.baselines import HeuristicPolicy, RandomPolicy
from musbench.mus.deck import Card, make_deck
from musbench.mus.engine import EnviteState, IllegalAction, MusEngine, Phase


def hand(*ranks):
    return [Card(rank, suit) for rank, suit in zip(ranks, ("oros", "copas", "espadas", "bastos"))]


class EngineRegressionTests(unittest.TestCase):
    def setUp(self):
        self.engine = MusEngine(Random(0))
        self.engine.deal()

    def test_four_kind_counts_as_two_equal_pairs(self):
        # tres counts as rey, so rey+tres+rey+tres is a duples of reyes
        four = hand("rey", "tres", "rey", "tres")
        single = hand("rey", "tres", "as", "dos")
        self.assertEqual(self.engine._pares_value(four)[0], 3)
        self.assertEqual(self.engine._pares_value(single)[0], 1)
        self.assertGreater(self.engine._pares_value(four), self.engine._pares_value(single))

    def test_as_dos_is_not_a_pair_but_as_as_is(self):
        # Fournier pares: as and dos are different ranks (only tres=rey)
        self.assertEqual(self.engine._pares_value(hand("as", "dos", "siete", "cinco"))[0], 0)
        self.assertEqual(self.engine._pares_value(hand("as", "as", "siete", "cinco"))[0], 1)
        self.assertEqual(self.engine._pares_value(hand("dos", "dos", "as", "as"))[0], 3)

    def test_pares_rank_follows_grande_order(self):
        # pares de reyes beat pares de caballos; doses beat aces
        self.assertGreater(self.engine._pares_value(hand("rey", "rey", "siete", "cinco")),
                           self.engine._pares_value(hand("caballo", "caballo", "siete", "cinco")))
        self.assertGreater(self.engine._pares_value(hand("dos", "dos", "siete", "cinco")),
                           self.engine._pares_value(hand("as", "as", "siete", "cinco")))

    def test_grande_orders_dos_over_as_and_tres_equals_rey(self):
        self.assertGreater(self.engine._grande_value([Card("dos", "oros")]),
                           self.engine._grande_value([Card("as", "oros")]))
        self.assertEqual(self.engine._grande_value(hand("tres", "cuatro", "cinco", "seis"))[0],
                         self.engine._grande_value(hand("rey", "cuatro", "cinco", "seis"))[0])

    def test_chica_orders_as_best_and_tres_before_cuatro(self):
        # for chica, as (1) beats dos (2); tres/rey (3) beats cuatro (4)
        self.assertGreater(self.engine._chica_value([Card("as", "oros")]),
                           self.engine._chica_value([Card("dos", "oros")]))
        self.assertGreater(self.engine._chica_value([Card("tres", "oros")]),
                           self.engine._chica_value([Card("cuatro", "oros")]))
        # caballo (11) is the worst chica card
        self.assertGreater(self.engine._chica_value([Card("sota", "oros")]),
                           self.engine._chica_value([Card("caballo", "oros")]))

    def test_both_false_declarations_are_rejected_without_mutation(self):
        for lance, cards in ((2, hand("rey", "tres", "as", "cuatro")),
                             (3, hand("rey", "sota", "caballo", "as"))):
            self.engine.phase = Phase.DECLARE
            self.engine.lance_index = lance
            self.engine.hands[0] = cards
            with self.assertRaises(IllegalAction):
                self.engine.apply(0, {"action": "no-tengo"})
            self.assertEqual(self.engine.declared, {})

    def test_pares_envite_skips_seats_without_pares(self):
        # Real table: only "tengo" seats play the pares envite.
        e = self.engine
        e.mano = 0
        e.current_seat = 0
        e.lance_index = 2
        e.phase = Phase.DECLARE
        e.declared = {}
        e.hands[0] = hand("rey", "rey", "as", "dos")
        e.hands[1] = hand("caballo", "caballo", "cuatro", "cinco")
        e.hands[2] = hand("as", "dos", "seis", "siete")
        e.hands[3] = hand("as", "dos", "seis", "siete")
        for s in range(4):
            has = e._pares_value(e.hands[s])[0] > 0
            e.current_seat = s
            e.apply(s, {"action": "tengo" if has else "no-tengo"})
        self.assertEqual(e.phase, Phase.ENVITE)
        self.assertEqual(e.envite.folded, {2, 3})
        self.assertEqual(e.current_seat, 0)
        self.assertIn("envido", e.legal_actions(0))
        e.current_seat = 2
        self.assertEqual(e.legal_actions(2), [])

    def test_invalid_discard_is_atomic(self):
        self.engine.phase = Phase.MUS_DRAW
        self.engine.mus_want = {0, 1, 2, 3}
        before = list(self.engine.hands[0])
        for names in ([str(before[0]), "missing"], [""], [str(before[0])] * 2):
            with self.assertRaises(IllegalAction):
                self.engine.apply(0, {"action": "discard", "cards": names})
            self.assertEqual(self.engine.hands[0], before)

    def test_draw_order_rotates_with_mano(self):
        self.engine.deal()
        for seat in (1, 2, 3, 0):
            self.engine.apply(seat, {"action": "mus"})
        for seat in (1, 2, 3, 0):
            self.assertEqual(self.engine.current_seat, seat)
            self.engine.apply(seat, {"action": "discard", "cards": [str(self.engine.hands[seat][0])]})

    def test_perete_dumps_4567_and_draws_fresh_hand(self):
        from musbench.mus.engine import is_perete
        e = self.engine
        e.hands[0] = hand("cuatro", "cinco", "seis", "siete")
        e.phase = e.phase  # MUS_REQUEST after deal
        e.current_seat = 0
        self.assertTrue(is_perete(e.hands[0]))
        self.assertIn("perete", e.legal_actions(0))
        before = {str(c) for c in e.hands[0]}
        pile_before = len(e.draw_pile)
        e.apply(0, {"action": "perete"})
        self.assertEqual(e.phase, Phase.MUS_REQUEST)
        self.assertEqual(e.current_seat, 0)
        self.assertEqual(len(e.hands[0]), 4)
        self.assertNotEqual({str(c) for c in e.hands[0]}, before)
        self.assertEqual(len(e.draw_pile), pile_before - 4)
        self.assertEqual(len(e.discard_pile), 4)
        # non-perete hands cannot shout it
        e.hands[0] = hand("rey", "as", "dos", "sota")
        self.assertNotIn("perete", e.legal_actions(0))

    def test_declined_ordago_still_requires_callers_mus_consent(self):
        # Both opposing seats must retract; one no-quiero leaves the órdago open.
        self.engine.apply(0, {"action": "ordago"})
        self.assertEqual(self.engine.phase, Phase.ORDAGO_RESPONSE)
        self.engine.apply(1, {"action": "no-quiero"})
        self.assertEqual(self.engine.phase, Phase.ORDAGO_RESPONSE)
        self.assertEqual(self.engine.current_seat, 3)
        self.engine.apply(3, {"action": "no-quiero"})
        self.assertEqual(self.engine.phase, Phase.MUS_REQUEST)
        self.assertEqual(self.engine.current_seat, 0)
        self.assertNotIn("ordago", self.engine.legal_actions(0))
        for seat in range(4):
            self.engine.apply(seat, {"action": "mus"})
        self.assertEqual(self.engine.mus_want, {0, 1, 2, 3})

    def test_ordago_needs_both_rivals_to_retract(self):
        # Lance órdago: first rival's no-quiero only folds that seat; the other
        # may still quiero. Both must retract before the lance advances.
        from musbench.mus.engine import TEAM_OF
        e = self.engine
        e.apply(0, {"action": "no"})
        self.assertEqual(e.phase, Phase.ENVITE)
        opener = e.current_seat
        e.apply(opener, {"action": "ordago"})
        self.assertEqual(e.phase, Phase.ORDAGO_RESPONSE)
        caller = e.ordago_caller
        caller_team = TEAM_OF[caller]
        grande = e.lance_index
        before_pts = (e.points_a, e.points_b)
        retracted = []
        for _ in range(4):
            if e.phase != Phase.ORDAGO_RESPONSE:
                break
            seat = e.current_seat
            self.assertNotEqual(TEAM_OF[seat], caller_team)
            e.apply(seat, {"action": "no-quiero"})
            retracted.append(seat)
            if len(retracted) == 1:
                self.assertEqual(e.phase, Phase.ORDAGO_RESPONSE)
                self.assertEqual(e.lance_index, grande)
                self.assertEqual((e.points_a, e.points_b), before_pts)
                other = e.current_seat
                self.assertNotEqual(other, seat)
                self.assertIn("quiero", e.legal_actions(other))
        self.assertEqual(len(retracted), 2)
        self.assertGreater(e.lance_index, grande)  # Grande → Chica
        self.assertNotEqual((e.points_a, e.points_b), before_pts)

    def test_second_rival_can_accept_ordago_after_partner_retracts(self):
        from musbench.mus.engine import TEAM_OF
        e = self.engine
        e.apply(0, {"action": "no"})
        opener = e.current_seat
        e.apply(opener, {"action": "ordago"})
        caller_team = TEAM_OF[e.ordago_caller]
        first = e.current_seat
        e.apply(first, {"action": "no-quiero"})
        self.assertEqual(e.phase, Phase.ORDAGO_RESPONSE)
        second = e.current_seat
        self.assertNotEqual(TEAM_OF[second], caller_team)
        e.apply(second, {"action": "quiero"})
        self.assertEqual(e.phase, Phase.DONE)

    def test_heuristic_cannot_use_partner_cards(self):
        self.engine.apply(0, {"action": "no"})
        self.engine.hands[0] = hand("cuatro", "cinco", "seis", "siete")
        policy = HeuristicPolicy()
        before = policy.act(self.engine, 0, self.engine.legal_actions(0))
        self.engine.hands[2] = hand("rey", "rey", "tres", "tres")
        self.assertEqual(policy.act(self.engine, 0, self.engine.legal_actions(0)), before)

    def test_envite_needs_both_rivals_to_decline(self):
        # One rival's no-quiero only folds that seat; the other may still
        # quiero / raise. Decline settles only after both opposing seats fold.
        from musbench.mus.engine import TEAM_OF
        e = self.engine
        e.apply(0, {"action": "no"})          # no hay mus -> Grande envite
        self.assertEqual(e.phase, Phase.ENVITE)
        opener = e.current_seat
        e.apply(opener, {"action": "envido"})
        holder = e.envite.holder
        holder_team = TEAM_OF[holder]
        before_pts = (e.points_a, e.points_b)
        rivals_folded = []
        grande = e.lance_index
        for _ in range(8):
            if e.lance_index != grande:
                break
            seat = e.current_seat
            if TEAM_OF[seat] == holder_team:
                e.apply(seat, {"action": "paso"})
                continue
            e.apply(seat, {"action": "no-quiero"})
            rivals_folded.append(seat)
            if len(rivals_folded) == 1:
                self.assertEqual(e.lance_index, grande)
                self.assertEqual((e.points_a, e.points_b), before_pts)
                other = e.current_seat
                while (e.lance_index == grande and e.phase == Phase.ENVITE
                       and TEAM_OF[other] == holder_team):
                    e.apply(other, {"action": "paso"})
                    other = e.current_seat
                if e.lance_index == grande:
                    self.assertIn("quiero", e.legal_actions(other))
        self.assertEqual(len(rivals_folded), 2)
        self.assertGreater(e.lance_index, grande)  # declined Grande -> next lance
        self.assertNotEqual((e.points_a, e.points_b), before_pts)

    def test_mus_equivalent_pair_is_kept(self):
        # rey counts as tres: the rey-tres pair is kept, the low cards tossed
        cards = hand("rey", "tres", "cuatro", "cinco")
        self.assertEqual(HeuristicPolicy._discard(self.engine, cards),
                         [str(c) for c in cards[2:]])

    def test_discard_all_four_when_no_pairs_and_no_high_cards(self):
        cards = hand("as", "dos", "cuatro", "cinco")
        self.assertEqual(HeuristicPolicy._discard(self.engine, cards),
                         [str(c) for c in cards])

    def test_seeded_self_play_terminates_and_conserves_cards(self):
        policy = RandomPolicy(2)
        for _ in range(100):
            self.engine.deal()
            for turn in range(300):
                if self.engine.phase == Phase.DONE:
                    break
                seat = self.engine.current_seat
                self.engine.apply(seat, policy.act(self.engine, seat, self.engine.legal_actions(seat)))
                cards = sum(self.engine.hands.values(), []) + self.engine.draw_pile + self.engine.discard_pile
                self.assertCountEqual(cards, make_deck())
            self.assertEqual(self.engine.phase, Phase.DONE)

    def test_complete_game_runs_offline(self):
        module = importlib.import_module("complete_game")
        with patch.object(module, "SPECS", ["random"] * 4), patch.object(module, "MAX_HANDS", 2):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                module.main(["--seed", "1", "--target", "100"])
        self.assertIn("GAME OVER after 2 hands", output.getvalue())

    def test_complete_game_import_does_not_parse_or_play(self):
        with patch("argparse.ArgumentParser.parse_args", side_effect=AssertionError("parsed at import")):
            importlib.import_module("complete_game")


if __name__ == "__main__":
    unittest.main()


class OrdagoAndTieRulesTest(unittest.TestCase):
    """Regressions found by the Fable 5.2 harness check (2026-11-22)."""

    @staticmethod
    def _hands(spec):
        from musbench.mus.deck import Card
        return {s: [Card(*c.split(" de ")) for c in cards]
                for s, cards in spec.items()}

    def test_lance_ordago_is_decided_by_that_lance_only(self):
        # Fable hand 5: seat 3 (team B) órdago at Juego with 32; seat 2
        # (team A) holds 36 and wins Grande/Chica/Pares. B must take the vaca.
        e = MusEngine(rng=Random(0))
        e.deal()
        e.hands = self._hands({
            0: ["siete de copas", "as de copas", "cinco de oros", "tres de espadas"],
            1: ["seis de oros", "cinco de copas", "seis de bastos", "siete de oros"],
            2: ["caballo de espadas", "rey de espadas", "seis de copas", "tres de bastos"],
            3: ["sota de espadas", "siete de espadas", "caballo de copas", "cinco de espadas"]})
        e.mano = 0
        e.lance_index = 3
        e.phase = Phase.ENVITE
        e.envite = EnviteState()
        e.envite.folded = {0, 1}          # only juego holders bet
        e.current_seat = 3
        e.apply(3, {"action": "ordago"})
        e.apply(e.current_seat, {"action": "quiero"})
        self.assertEqual(e.phase, Phase.DONE)
        self.assertEqual(e.vacas_b, 1)
        self.assertEqual(e.vacas_a, 0)

    def test_ties_go_to_the_side_nearest_the_mano(self):
        e = MusEngine(rng=Random(0))
        e.deal()
        same = ["rey de {}", "caballo de {}", "sota de {}", "siete de {}"]
        e.hands = self._hands({s: [c.format(p) for c in same]
                               for s, p in zip(range(4), ["oros", "copas", "espadas", "bastos"])})
        for mano, team in ((0, 0), (1, 1), (2, 0), (3, 1)):
            e.mano = mano
            self.assertEqual(e._lance_winner("Grande"), team)
            self.assertEqual(e._lance_winner("Chica"), team)

    def test_nobody_wins_pares_when_nobody_has_pares(self):
        e = MusEngine(rng=Random(0))
        e.deal()
        e.hands = self._hands({
            0: ["rey de oros", "caballo de oros", "sota de oros", "siete de oros"],
            1: ["rey de copas", "caballo de copas", "sota de copas", "seis de copas"],
            2: ["as de oros", "dos de oros", "cuatro de oros", "cinco de oros"],
            3: ["as de copas", "dos de copas", "cuatro de copas", "cinco de copas"]})
        self.assertIsNone(e._lance_winner("Pares"))
