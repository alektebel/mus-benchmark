import importlib
import contextlib
import io
import unittest
from random import Random
from unittest.mock import patch

from baselines_strict import HeuristicPolicy, RandomPolicy
from deck import Card, make_deck
from mus_engine import IllegalAction, MusEngine, Phase


def hand(*ranks):
    return [Card(rank, suit) for rank, suit in zip(ranks, ("oros", "copas", "espadas", "bastos"))]


class EngineRegressionTests(unittest.TestCase):
    def setUp(self):
        self.engine = MusEngine(Random(0))
        self.engine.deal()

    def test_four_kind_counts_as_two_equal_pairs(self):
        four = hand("rey", "tres", "rey", "tres")
        duples = hand("rey", "tres", "as", "dos")
        self.assertGreater(self.engine._pares_value(four), self.engine._pares_value(duples))

    def test_both_false_declarations_are_rejected_without_mutation(self):
        for lance, cards in ((2, hand("rey", "tres", "as", "cuatro")),
                             (3, hand("rey", "sota", "caballo", "as"))):
            self.engine.phase = Phase.DECLARE
            self.engine.lance_index = lance
            self.engine.hands[0] = cards
            with self.assertRaises(IllegalAction):
                self.engine.apply(0, {"action": "no-tengo"})
            self.assertEqual(self.engine.declared, {})

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

    def test_declined_ordago_still_requires_callers_mus_consent(self):
        self.engine.apply(0, {"action": "ordago"})
        self.engine.apply(1, {"action": "no-quiero"})
        self.assertEqual(self.engine.current_seat, 0)
        self.assertNotIn("ordago", self.engine.legal_actions(0))
        for seat in range(4):
            self.engine.apply(seat, {"action": "mus"})
        self.assertEqual(self.engine.mus_want, {0, 1, 2, 3})

    def test_heuristic_cannot_use_partner_cards(self):
        self.engine.apply(0, {"action": "no"})
        self.engine.hands[0] = hand("cuatro", "cinco", "seis", "siete")
        policy = HeuristicPolicy()
        before = policy.act(self.engine, 0, self.engine.legal_actions(0))
        self.engine.hands[2] = hand("rey", "rey", "tres", "tres")
        self.assertEqual(policy.act(self.engine, 0, self.engine.legal_actions(0)), before)

    def test_mus_equivalent_pair_is_kept(self):
        cards = hand("as", "dos", "cuatro", "cinco")
        self.assertEqual(HeuristicPolicy._discard(self.engine, cards), [str(c) for c in cards[2:]])

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
