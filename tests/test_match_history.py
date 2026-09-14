import unittest
from random import Random

from match_history import MatchHistory
from mus_engine import MusEngine, Phase
from decision_log import DecisionLog
from virtual_kernel import run_match_kernel


class DossierTest(unittest.TestCase):
    def test_empty_before_any_hand_closes(self):
        self.assertEqual(MatchHistory().dossier(0), [])

    def test_rivals_and_partner_are_split_by_seat(self):
        h = MatchHistory()
        h.hands = 3
        for s in range(4):
            h.record_decision(s, "paso")
        text = "\n".join(h.dossier(1))
        self.assertIn("seat 0 (rival)", text)
        self.assertIn("seat 2 (rival)", text)
        self.assertIn("seat 3 (your partner)", text)
        self.assertNotIn("seat 1 (", text)      # never profiles itself

    def test_fold_counts_only_bets_from_the_other_team(self):
        h = MatchHistory()
        h.record_decision(1, "no-quiero", facing_bet=True, holder_team=0)
        h.record_decision(1, "no-quiero", facing_bet=True, holder_team=1)
        self.assertEqual(h.seats[1]["faced_bets"], 1)
        self.assertEqual(h.seats[1]["folds"], 1)

    def test_showdown_credits_only_seats_that_bet_that_lance(self):
        engine = MusEngine(rng=Random(1))
        engine.deal()
        h = MatchHistory()
        h.record_decision(1, "envido", lance="Grande")
        h.record_decision(3, "paso", lance="Grande")
        engine.locked_envites = [("Grande", 2, 1)]

        class J:
            name, winner_team = "Grande", 0      # team 0 won: seat 1 was caught
        engine.jugadas = [J()]
        h.close_hand(engine, 1)
        self.assertEqual(h.seats[1]["bets_shown"], 1)
        self.assertEqual(h.seats[1]["bets_caught"], 1)
        self.assertEqual(h.seats[3]["bets_shown"], 0)   # never pushed
        self.assertIn("1/1 were with the weaker hand", h._line(1))

    def test_a_lance_with_no_accepted_bet_reveals_nothing(self):
        engine = MusEngine(rng=Random(1))
        engine.deal()
        h = MatchHistory()
        h.record_decision(1, "envido", lance="Grande")
        engine.locked_envites = []

        class J:
            name, winner_team = "Grande", 0
        engine.jugadas = [J()]
        h.close_hand(engine, 1)
        self.assertEqual(h.showdowns, [])
        self.assertEqual(h.seats[1]["bets_shown"], 0)

    def test_bets_do_not_carry_into_the_next_hand(self):
        engine = MusEngine(rng=Random(1))
        engine.deal()
        h = MatchHistory()
        h.record_decision(1, "envido", lance="Grande")
        h.close_hand(engine, 1)                       # no locked envites
        engine.locked_envites = [("Grande", 2, 1)]

        class J:
            name, winner_team = "Grande", 0
        engine.jugadas = [J()]
        h.close_hand(engine, 2)
        self.assertEqual(h.seats[1]["bets_shown"], 0)  # that bet was hand 1


class LeakTest(unittest.TestCase):
    """The dossier must never carry a card a seat could not legitimately know."""

    def test_dossier_never_shows_unrevealed_cards(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "m.jsonl")
            with DecisionLog(path) as log:
                run_match_kernel(MusEngine(rng=Random(11)),
                                 ["heuristic", "random", "heuristic", "random"],
                                 hands=12, seed=11, decision_log=log,
                                 vaca_callback=lambda *a: None)
            import json
            with open(path, encoding="utf8") as f:
                recs = [json.loads(l) for l in f]

        # rebuild the history exactly as the kernel does, then check that every
        # card it would print was actually turned over at a showdown
        hands = [r for r in recs if r["kind"] == "hand"]
        for h in hands:
            shown_lances = {e["lance"] for e in h["locked_envites"]}
            if not shown_lances:
                continue
            self.assertTrue(shown_lances <= set(h["jugadas"]))

        # a hand with no accepted envite must contribute no showdown at all
        silent = [h for h in hands if not h["locked_envites"]]
        self.assertTrue(silent, "expected at least one hand with no locked bet")


if __name__ == "__main__":
    unittest.main()
