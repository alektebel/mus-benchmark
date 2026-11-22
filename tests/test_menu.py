"""Menu harness: every option is legal, seats only see what they may know."""
import os
import random
import re
import unittest
from random import Random
from unittest import mock

from musbench.agents.core import StrictAgent
from musbench.harness import menu
from musbench.mus.engine import MusEngine, Phase


def _fake_decide(rng, prompts, bad=0.0):
    def decide(self, prompt):
        n = int(re.search(r"<1-(\d+)>", prompt).group(1))
        prompts.append((self.seat, prompt))
        self.calls += 1
        if rng.random() < bad:
            return {"choice": "banana"}
        return {"choice": rng.randint(1, n)}
    return decide


class MenuOptionsTest(unittest.TestCase):
    def test_every_option_is_accepted_by_the_engine(self):
        """Walk many hands taking random menu options; apply never raises."""
        rng = Random(4)
        for seed in range(40):
            e = MusEngine(rng=Random(seed))
            e.deal()
            steps = 0
            while e.phase != Phase.DONE and steps < 400:
                steps += 1
                seat = e.current_seat
                auto = menu._auto(e, seat)
                if auto:
                    e.apply(seat, auto)
                    continue
                opts = menu.menu_options(e, seat)
                self.assertTrue(opts, f"no options in {e.phase}")
                e.apply(seat, rng.choice(opts)[1])
            self.assertEqual(e.phase, Phase.DONE)

    def test_discard_menu_lists_every_subset(self):
        e = MusEngine(rng=Random(0))
        e.deal()
        e.phase, e.mus_want, e.current_seat = Phase.MUS_DRAW, {0}, 0
        opts = menu.menu_options(e, 0)
        self.assertEqual(len(opts), 15)          # 2^4 - 1
        self.assertTrue(all(o[1]["action"] == "discard" for o in opts))

    def test_parse_choice(self):
        self.assertEqual(menu._parse_choice({"choice": 2}, 3), 2)
        self.assertEqual(menu._parse_choice({"choice": "3"}, 3), 3)
        self.assertIsNone(menu._parse_choice({"choice": 4}, 3))
        self.assertIsNone(menu._parse_choice({"choice": True}, 3))
        self.assertIsNone(menu._parse_choice({"pick": 1}, 3))


@mock.patch.dict(os.environ, {"NAN_API_KEY": "test"})
class MenuMatchTest(unittest.TestCase):
    def test_match_runs_and_prompts_hide_other_hands(self):
        prompts = []
        with mock.patch.object(StrictAgent, "decide",
                               _fake_decide(random.Random(0), prompts)):
            r = menu.run_menu_match(["m", "heuristic", "m", "heuristic"],
                                    hands=4, seed=2)
        self.assertEqual(r["status"], "done")
        self.assertEqual(r["hands_completed"], 4)
        self.assertEqual(r["usage"]["invalid"], 0)
        self.assertGreater(len(prompts), 0)
        for seat, p in prompts:
            # cards of the current hand appear only in YOUR CARDS / options;
            # other seats' cards only in RECENT HANDS (showdowns, public)
            current = p.split("RECENT HANDS")[0]
            mine = re.search(r"YOUR CARDS: (.+)", p).group(1).split(", ")
            for card in re.findall(r"\b(?:as|dos|tres|cuatro|cinco|seis|siete|"
                                   r"sota|caballo|rey) de \w+", current):
                self.assertIn(card, mine, f"seat {seat} saw {card}")

    def test_an_occasional_bad_answer_is_reasked_never_played_for(self):
        prompts = []
        with mock.patch.object(StrictAgent, "decide",
                               _fake_decide(random.Random(1), prompts, bad=0.2)):
            r = menu.run_menu_match(["m", "random", "m", "random"],
                                    hands=2, seed=0)
        self.assertEqual(r["status"], "done")
        self.assertEqual(r["usage"]["fallbacks"], 0)
        self.assertTrue(any("not a valid option" in p for _, p in prompts))

    def test_a_model_that_never_answers_validly_ends_the_match_unscored(self):
        with mock.patch.object(StrictAgent, "decide", lambda self, p: {"choice": "banana"}):
            r = menu.run_menu_match(["m", "random", "m", "random"], hands=2, seed=0)
        self.assertEqual(r["status"], "no_answer")
        self.assertEqual(r["usage"]["fallbacks"], 0)

    def test_perete_is_the_models_choice(self):
        from musbench.mus.deck import Card
        e = MusEngine(rng=Random(0))
        e.deal()
        e.hands[e.current_seat] = [Card("cuatro", "oros"), Card("cinco", "oros"),
                                   Card("seis", "oros"), Card("siete", "oros")]
        self.assertIsNone(menu._auto(e, e.current_seat))
        labels = [a["action"] for _, a in menu.menu_options(e, e.current_seat)]
        self.assertIn("perete", labels)

    def test_same_seed_same_deals(self):
        a = menu.run_menu_match(["heuristic"] * 4, hands=3, seed=5)
        b = menu.run_menu_match(["heuristic"] * 4, hands=3, seed=5)
        self.assertEqual((a["piedras_a"], a["piedras_b"]),
                         (b["piedras_a"], b["piedras_b"]))


if __name__ == "__main__":
    unittest.main()


@mock.patch.dict(os.environ, {"NAN_API_KEY": "test"})
class ProviderFailureTest(unittest.TestCase):
    def test_provider_failure_aborts_instead_of_scoring_a_fallback(self):
        from musbench.live.apifail import LLMCallFailure

        def boom(self, prompt):
            raise LLMCallFailure("usage limit")
        with mock.patch.object(StrictAgent, "decide", boom):
            r = menu.run_menu_match(["m", "heuristic", "m", "heuristic"],
                                    hands=2, seed=0)
        self.assertEqual(r["status"], "provider_error")
        self.assertEqual(r["usage"]["invalid"], 0)
