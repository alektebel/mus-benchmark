import json
import os
import tempfile
import unittest
from random import Random

import analysis
from decision_log import DecisionLog
from mus_engine import MusEngine
from virtual_kernel import run_match_kernel


def dec(hand, seat, team, action, *, lance="Grande", strength=0.5,
        would_win=None, legal=("paso", "envido", "ordago"), read=None,
        stake=0, previous=0, holder=None, holder_team=None,
        facing_bet=False, points_a=0, points_b=0):
    return {"kind": "decision", "hand": hand, "turn": 0, "t": 0.0,
            "seat": seat, "team": team, "name": f"S{seat}", "model": f"m{team}",
            "is_llm": True, "action": action, "raw_action": {"action": action},
            "legal": list(legal), "rejections": 0, "fallback": False,
            "read": read, "senas_delivered": [], "thought": None,
            "phase": "ENVITE", "lance": lance, "cards_final": True,
            "strength": strength, "would_win": would_win,
            "lance_winner_truth": (None if would_win is None
                                   else (team if would_win else 1 - team)),
            "facing_bet": facing_bet, "stake": stake, "previous": previous,
            "holder": holder, "holder_team": holder_team, "folded": [],
            "points_a": points_a, "points_b": points_b,
            "vacas_a": 0, "vacas_b": 0}


class LinkResponsesTest(unittest.TestCase):
    def test_first_opposing_action_is_the_response(self):
        recs = [
            dec(1, 0, 0, "envido"),
            dec(1, 2, 0, "paso"),                 # partner, not a response
            dec(1, 1, 1, "no-quiero", stake=2, previous=0, holder=0,
                holder_team=0, facing_bet=True),
        ]
        analysis.link_responses(recs)
        self.assertEqual(recs[0]["response"], "fold")
        self.assertEqual(recs[0]["responder_seat"], 1)
        self.assertEqual(recs[0]["fold_gain"], 1)   # deje when previous == 0

    def test_call_and_raise_are_distinguished(self):
        for act, want in (("quiero", "call"), ("reenvido", "raise")):
            recs = [dec(1, 0, 0, "envido"),
                    dec(1, 1, 1, act, stake=2, holder=0, holder_team=0,
                        facing_bet=True)]
            analysis.link_responses(recs)
            self.assertEqual(recs[0]["response"], want)

    def test_responses_do_not_cross_lances_or_hands(self):
        recs = [dec(1, 0, 0, "envido", lance="Grande"),
                dec(1, 1, 1, "no-quiero", lance="Chica", facing_bet=True),
                dec(2, 1, 1, "no-quiero", lance="Grande", facing_bet=True)]
        analysis.link_responses(recs)
        self.assertIsNone(recs[0]["response"])


class TercileTest(unittest.TestCase):
    def test_terciles_only_use_seats_that_could_bet(self):
        recs = [dec(1, 0, 0, "paso", strength=s) for s in
                (0.1, 0.2, 0.3, 0.7, 0.8, 0.9)]
        recs.append(dec(1, 0, 0, "quiero", strength=0.0, legal=("quiero",)))
        cuts = analysis.strength_terciles(recs)
        lo, hi = cuts["Grande"]
        self.assertEqual((lo, hi), (0.3, 0.8))
        self.assertEqual(analysis.strength_band(
            dec(1, 0, 0, "envido", strength=0.15), cuts), "weak")
        self.assertEqual(analysis.strength_band(
            dec(1, 0, 0, "envido", strength=0.95), cuts), "strong")

    def test_too_few_samples_yields_no_cut(self):
        recs = [dec(1, 0, 0, "paso", strength=0.5) for _ in range(3)]
        self.assertEqual(analysis.strength_terciles(recs), {})


class ScoringTest(unittest.TestCase):
    def test_bluff_is_a_weak_hand_bet_not_a_losing_one(self):
        # eight strong-hand bets that all LOSE the lance: high loss rate, but
        # not one of them is a bluff.
        recs = [dec(h, 0, 0, "envido", strength=0.9, would_win=False)
                for h in range(1, 9)]
        recs += [dec(h, 2, 0, "paso", strength=s)
                 for h, s in enumerate([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], 1)]
        card = analysis.scorecard(recs)["m0"]
        self.assertEqual(card["bluff_rate"], 0.0)

    def test_fold_error_and_payoff_need_an_opposing_holder(self):
        recs = [
            # folds a lance we would have won -> fold error
            dec(1, 0, 0, "no-quiero", would_win=True, facing_bet=True,
                stake=2, holder=1, holder_team=1),
            # calls a lance we lose -> pays off
            dec(2, 0, 0, "quiero", would_win=False, facing_bet=True,
                stake=2, holder=1, holder_team=1),
            # our own partner holds the bet: neither
            dec(3, 0, 0, "quiero", would_win=False, facing_bet=True,
                stake=2, holder=2, holder_team=0),
        ]
        card = analysis.scorecard(recs)["m0"]
        self.assertEqual(card["faced_winning"], 1)
        self.assertEqual(card["fold_error_rate"], 1.0)
        self.assertEqual(card["faced_losing"], 1)
        self.assertEqual(card["payoff_rate"], 1.0)

    def test_brier_and_auc_on_the_read_channel(self):
        recs = [dec(1, 0, 0, "quiero", would_win=True, facing_bet=True,
                    holder=1, holder_team=1, read={"p_win_lance": 1.0}),
                dec(2, 0, 0, "quiero", would_win=False, facing_bet=True,
                    holder=1, holder_team=1, read={"p_win_lance": 0.0})]
        card = analysis.scorecard(recs)["m0"]
        self.assertEqual(card["read_win_n"], 2)
        self.assertEqual(card["read_win_brier"], 0.0)
        self.assertEqual(card["read_win_auc"], 1.0)

    def test_a_coinflip_read_scores_a_quarter(self):
        recs = [dec(h, 0, 0, "quiero", would_win=bool(h % 2), facing_bet=True,
                    holder=1, holder_team=1, read={"p_win_lance": 0.5})
                for h in range(1, 11)]
        card = analysis.scorecard(recs)["m0"]
        self.assertAlmostEqual(card["read_win_brier"], 0.25)
        # every prediction tied, so the ranking is a coin flip
        self.assertEqual(card["read_win_auc"], 0.5)

    def test_p_opp_fold_is_scored_against_the_actual_response(self):
        recs = [dec(1, 0, 0, "envido", read={"p_opp_fold": 0.9}),
                dec(1, 1, 1, "no-quiero", facing_bet=True, stake=2,
                    holder=0, holder_team=0)]
        card = analysis.scorecard(recs)["m0"]
        self.assertEqual(card["read_fold_n"], 1)
        self.assertAlmostEqual(card["read_fold_brier"], 0.01)

    def test_learning_is_late_minus_early(self):
        recs = [dec(1, 0, 0, "quiero", would_win=True, facing_bet=True,
                    holder=1, holder_team=1, read={"p_win_lance": 0.5}),
                dec(4, 0, 0, "quiero", would_win=True, facing_bet=True,
                    holder=1, holder_team=1, read={"p_win_lance": 1.0})]
        card = analysis.scorecard(recs)["m0"]
        self.assertAlmostEqual(card["read_win_brier_early"], 0.25)
        self.assertAlmostEqual(card["read_win_brier_late"], 0.0)
        self.assertAlmostEqual(card["read_win_learning"], -0.25)


class BaselineSeparationTest(unittest.TestCase):
    """The scorecard's own calibration check.

    HeuristicPolicy only opens above OPEN_BID=0.40 on its own hand strength;
    RandomPolicy picks uniformly among legal actions. If the risk metrics do
    not separate those two, the metrics are wrong -- so this is the test that
    guards the whole module.
    """

    def test_heuristic_bets_weak_hands_far_less_than_random(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "m.jsonl")
            with DecisionLog(path) as log:
                run_match_kernel(MusEngine(rng=Random(3)),
                                 ["heuristic", "random", "heuristic", "random"],
                                 hands=30, seed=3, decision_log=log,
                                 vaca_callback=lambda *a: None)
            recs = analysis.load(path)

        cards = analysis.scorecard(recs)
        heur, rand = cards["heuristic"], cards["random"]
        self.assertLess(heur["weak_hand_bet_rate"], 0.20)
        self.assertGreater(rand["weak_hand_bet_rate"], 0.45)
        self.assertLess(heur["bluff_rate"], rand["bluff_rate"])
        self.assertGreater(heur["avg_strength_when_betting"],
                           rand["avg_strength_when_betting"])
        self.assertLess(heur["aggression_rate"], rand["aggression_rate"])

        out = analysis.outcome(recs)
        self.assertEqual(out["hands"], 30)
        self.assertEqual(out["piedras_a"] > 0, True)


class OutcomeTest(unittest.TestCase):
    def test_piedras_per_hand_uses_hand_gains_not_the_reset_counters(self):
        recs = [{"kind": "hand", "hand": 1, "hand_gain_a": 30,
                 "hand_gain_b": 5, "hand_winner": 0, "points_a": 30,
                 "points_b": 5, "vacas_a": 0, "vacas_b": 0},
                {"kind": "hand", "hand": 2, "hand_gain_a": 12,
                 "hand_gain_b": 3, "hand_winner": 0, "points_a": 0,
                 "points_b": 0, "vacas_a": 1, "vacas_b": 0}]
        out = analysis.outcome(recs)
        self.assertEqual(out["piedras_a"], 42)   # survives the vaca reset
        self.assertEqual(out["piedras_b"], 8)
        self.assertEqual(out["piedras_diff_per_hand"], 17.0)
        self.assertEqual(out["vacas_a"], 1)


if __name__ == "__main__":
    unittest.main()
