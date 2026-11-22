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


@mock.patch.dict(os.environ, {"NAN_API_KEY": "test"})
class DeclarationsAreAutomaticTest(unittest.TestCase):
    def test_models_never_decide_whether_they_have_pares_or_juego(self):
        prompts = []
        with mock.patch.object(StrictAgent, "decide",
                               _fake_decide(random.Random(7), prompts)):
            r = menu.run_menu_match(["m", "heuristic", "m", "heuristic"],
                                    hands=6, seed=11)
        self.assertEqual(r["status"], "done")
        for _, p in prompts:
            opts = p.split("YOUR OPTIONS:")[1]
            self.assertNotIn("tengo", opts)
            self.assertNotIn("Declarations", p.split("YOUR OPTIONS:")[0][-200:])


class V4PromptTest(unittest.TestCase):
    """v4-menu: same information as v3, shorter text, rules first."""

    def setUp(self):
        p = mock.patch.object(menu, "V4", True)
        p.start()
        self.addCleanup(p.stop)

    def test_prompt_starts_with_rules_and_drops_suits(self):
        e = MusEngine(rng=Random(0))
        e.deal()
        seat = e.current_seat
        prompt = menu.build_menu_prompt(e, seat, menu.PublicLog(),
                                        menu.menu_options(e, seat), 1, 8)
        self.assertTrue(prompt.startswith(menu.RULES_V4))
        self.assertIn("Chica, best to worst: as, dos, cuatro", prompt)
        self.assertIn("la real (31 made of three sietes and a sota)", prompt)
        body = prompt[len(menu.RULES_V4):]
        for palo in ("oros", "copas", "espadas", "bastos"):
            self.assertNotIn(palo, body)
        self.assertRegex(body, r'"choice": <1-\d+>')

    def test_discards_with_repeated_ranks_are_listed_once(self):
        from musbench.mus.deck import Card
        e = MusEngine(rng=Random(0))
        e.deal()
        e.hands[0] = [Card("rey", "oros"), Card("rey", "copas"),
                      Card("cinco", "oros"), Card("as", "bastos")]
        e.phase, e.mus_want, e.current_seat = Phase.MUS_DRAW, {0}, 0
        opts = menu.menu_options(e, 0)
        labels = [o[0] for o in opts]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertEqual(len(opts), 11)          # rank multisets of 1-4 cards
        for _, action in opts:                   # every one is still legal
            e2 = MusEngine(rng=Random(0))
            e2.deal()
            e2.hands[0] = list(e.hands[0])
            e2.phase, e2.mus_want, e2.current_seat = Phase.MUS_DRAW, {0}, 0
            e2.apply(0, action)


class EffortSuffixTest(unittest.TestCase):
    def test_effort_reaches_each_cli(self):
        from musbench.agents.cli_seat import CliAgent
        from pathlib import Path
        a = CliAgent("x", "claude-cli", "claude-opus-5-5@low", 0, 0)
        cmd = a._cmd(Path("o"))
        self.assertEqual(a.model, "claude-opus-5-5")
        self.assertEqual(cmd[cmd.index("--effort") + 1], "low")
        c = CliAgent("x", "codex-cli", "gpt-6-sol@high", 0, 0)
        self.assertIn('model_reasoning_effort="high"', c._cmd(Path("o")))
        self.assertNotIn("--effort", CliAgent("x", "claude-cli", "claude-haiku-5-5", 0, 0)._cmd(Path("o")))

    def test_unknown_effort_is_rejected(self):
        from musbench.agents.cli_seat import CliAgent
        with self.assertRaises(ValueError):
            CliAgent("x", "claude-cli", "claude-opus-5-5@turbo", 0, 0)
        with self.assertRaises(ValueError):
            CliAgent("x", "cursor-cli", "composer-2.5@high", 0, 0)


class LaRealInMatchTest(unittest.TestCase):
    def test_v4_matches_play_with_la_real_and_v3_without(self):
        seen = {}
        orig = menu.MusEngine

        def spy(*a, **k):
            e = orig(*a, **k)
            seen["engine"] = e
            return e
        for v4 in (True, False):
            with mock.patch.object(menu, "V4", v4), \
                 mock.patch.object(menu, "MusEngine", spy), \
                 mock.patch.object(StrictAgent, "decide", _fake_decide(Random(1), [])):
                menu.run_menu_match(["m", "random", "m", "random"], hands=1, seed=0)
            self.assertIs(seen["engine"].la_real, v4)
