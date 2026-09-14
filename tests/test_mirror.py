"""Paired (duplicate-bridge) deals: the same cards, the other way round.

Comparing two models on the same deals removes most of the card luck that
makes a short mus match uninterpretable. That only works if the sequence of
deals depends on the SEED ALONE and never on how the hands happened to be
played -- which is what these tests pin down.
"""
import json
import os
import tempfile
import unittest
from random import Random

from decision_log import DecisionLog
from mus_engine import MusEngine
from virtual_kernel import run_match_kernel


def deals_for(models, seed, hands=14):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "m.jsonl")
        with DecisionLog(path) as log:
            run_match_kernel(MusEngine(rng=Random(seed)), models, hands=hands,
                             seed=seed, decision_log=log,
                             vaca_callback=lambda *a: None)
        with open(path, encoding="utf8") as f:
            recs = [json.loads(l) for l in f]
    return [r["dealt"] for r in recs if r["kind"] == "hand"]


class MirrorTest(unittest.TestCase):
    def test_deal_sequence_is_identical_under_a_seat_swap(self):
        a = deals_for(["heuristic", "random", "heuristic", "random"], 6)
        b = deals_for(["random", "heuristic", "random", "heuristic"], 6)
        self.assertEqual(len(a), len(b))
        self.assertEqual(a, b)

    def test_deal_sequence_is_identical_for_wildly_different_play(self):
        # random seats ask for mus far more often, so they churn the draw pile
        # much harder; the deals must still line up hand for hand.
        a = deals_for(["heuristic", "heuristic", "heuristic", "heuristic"], 21)
        b = deals_for(["random", "random", "random", "random"], 21)
        self.assertEqual(a, b)

    def test_different_seeds_give_different_deals(self):
        self.assertNotEqual(
            deals_for(["heuristic", "random", "heuristic", "random"], 6, 4),
            deals_for(["heuristic", "random", "heuristic", "random"], 7, 4))

    def test_draw_pile_exhaustion_does_not_desynchronise_the_deals(self):
        """The old shared generator reshuffled the discard pile through the
        same stream that dealt, so an exhausted draw pile shifted every later
        deal. Force the exhaustion and check it no longer does."""
        engine = MusEngine(rng=Random(5))
        engine.deal()
        before = [str(c) for c in engine.draw_pile]
        engine.draw_pile = []                    # force the reshuffle path
        engine.discard_pile = [c for c in before[:8]] and engine.hands[0][:]
        engine._redraw(0, engine.hands[0][:1])
        after_first = engine.deal()

        clean = MusEngine(rng=Random(5))
        clean.deal()
        self.assertEqual([str(c) for c in after_first[0]],
                         [str(c) for c in clean.deal()[0]])


if __name__ == "__main__":
    unittest.main()


class JobPairingTest(unittest.TestCase):
    PAIRS = [("a", "b"), ("b", "a")]

    def test_mirror_gives_every_pairing_every_seed(self):
        import run_tournament as rt
        jobs = rt.build_jobs(self.PAIRS, [6, 7], mirror=True)
        self.assertEqual(len(jobs), 4)
        for seed in (6, 7):
            self.assertEqual(
                sorted(p for p, s in jobs if s == seed), sorted(self.PAIRS))

    def test_default_zip_leaves_orientations_on_different_deals(self):
        import run_tournament as rt
        jobs = rt.build_jobs(self.PAIRS, [6, 7])
        self.assertEqual(jobs, [(("a", "b"), 6), (("b", "a"), 7)])

    def test_paired_rows_cancel_the_deal_out(self):
        import run_tournament as rt
        # same cards both ways; "a" nets +10 in one seating and +6 in the other
        entries = [
            {"team_a": "a", "team_b": "b", "seed": 6, "status": "done",
             "result": {"piedras_a": 40, "piedras_b": 30, "hands_completed": 10}},
            {"team_a": "b", "team_b": "a", "seed": 6, "status": "done",
             "result": {"piedras_a": 27, "piedras_b": 33, "hands_completed": 10}},
        ]
        rows = rt.paired_rows(entries)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["models"], ["a", "b"])
        self.assertEqual(rows[0]["paired_diff"], 16)
        self.assertEqual(rows[0]["per_hand"], 0.8)

    def test_a_constant_seat_bias_cancels(self):
        """Seats 0+2 carry a small positional edge (measured: ~+0.25 piedras
        per hand for a deterministic policy, and NOT caused by the shared draw
        pile -- it survives MUS_ROUNDS_MAX=0). Pairing the two orientations
        removes it by construction, which is the reason --mirror exists."""
        import run_tournament as rt
        d, bias, n = 4, 7, 10          # true edge to "a", plus a seat bias
        entries = [
            # orientation 1: "a" sits in seats 0+2 and collects the bias
            {"team_a": "a", "team_b": "b", "seed": 6, "status": "done",
             "result": {"piedras_a": 100 + d + bias, "piedras_b": 100,
                        "hands_completed": n}},
            # orientation 2: same deals, "b" now collects it
            {"team_a": "b", "team_b": "a", "seed": 6, "status": "done",
             "result": {"piedras_a": 100 + bias, "piedras_b": 100 + d,
                        "hands_completed": n}},
        ]
        row = rt.paired_rows(entries)[0]
        self.assertEqual(row["paired_diff"], 2 * d)      # bias gone
        self.assertEqual(row["per_hand"], d / n)
        # and each orientation on its own would have been wrong
        self.assertNotEqual(row["piedra_diff_seat_a"], d)
        self.assertNotEqual(row["piedra_diff_seat_b"], d)

    def test_an_unmatched_orientation_is_dropped(self):
        import run_tournament as rt
        entries = [{"team_a": "a", "team_b": "b", "seed": 6, "status": "done",
                    "result": {"piedras_a": 40, "piedras_b": 30,
                               "hands_completed": 10}}]
        self.assertEqual(rt.paired_rows(entries), [])

    def test_degraded_matches_never_enter_a_pair(self):
        import run_tournament as rt
        entries = [
            {"team_a": "a", "team_b": "b", "seed": 6, "status": "done",
             "result": {"piedras_a": 40, "piedras_b": 30, "hands_completed": 10}},
            {"team_a": "b", "team_b": "a", "seed": 6, "status": "degraded",
             "result": {"piedras_a": 27, "piedras_b": 33, "hands_completed": 10}},
        ]
        self.assertEqual(rt.paired_rows(entries), [])
