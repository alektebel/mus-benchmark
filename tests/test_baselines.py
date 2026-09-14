"""The reference policy, and the check that the scorecard reads it correctly."""
import os
import tempfile
import unittest
from random import Random

import analysis
from agents import _make_agent
from baselines_strict import (EpsilonHeuristicPolicy, HeuristicPolicy,
                              RandomPolicy, parse_baseline)
from decision_log import DecisionLog
from mus_engine import MusEngine, Phase, JUEGO_TOTALS, LANCE_NAMES
from virtual_kernel import run_match_kernel


def play(models, seed, hands=120):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "m.jsonl")
        with DecisionLog(p) as log:
            run_match_kernel(MusEngine(rng=Random(seed)), models, hands=hands,
                             seed=seed, decision_log=log,
                             vaca_callback=lambda *a: None)
        return analysis.load(p)


class SpecTest(unittest.TestCase):
    def test_specs_parse(self):
        self.assertEqual(parse_baseline("eps")[0], "eps:0.1:0.15")
        self.assertEqual(parse_baseline("eps:0.05")[0], "eps:0.05:0.15")
        self.assertEqual(parse_baseline("eps:0.05:0.25")[0], "eps:0.05:0.25")

    def test_model_names_are_not_mistaken_for_baselines(self):
        for spec in ("glm5.3-flash", "nan:deepseek-v4-flash", "eps:bad",
                     "eps:0.1:0.2:0.3"):
            self.assertIsNone(parse_baseline(spec))

    def test_seat_spec_survives_the_provider_split(self):
        # "eps:0.3:0.4" must not be read as provider="eps", model="0.3:0.4"
        a = _make_agent("eps:0.3:0.4", 1, 1, 0)
        self.assertFalse(a.is_llm)
        self.assertEqual(a.model, "eps:0.3:0.4")
        self.assertEqual(a.policy.epsilon, 0.3)
        self.assertEqual(a.policy.bluff_p, 0.4)

    def test_bad_parameters_are_rejected(self):
        for bad in ({"epsilon": -0.1}, {"epsilon": 1.5}, {"bluff_p": 2.0}):
            with self.assertRaises(ValueError):
                EpsilonHeuristicPolicy(**bad)


class PolicyTest(unittest.TestCase):
    def test_zero_knobs_reproduces_the_deterministic_heuristic(self):
        engine = MusEngine(rng=Random(2))
        mixed = EpsilonHeuristicPolicy(epsilon=0.0, bluff_p=0.0, seed=1)
        base = HeuristicPolicy()
        for _ in range(40):
            engine.deal()
            while engine.phase != Phase.DONE:
                seat = engine.current_seat
                legal = engine.legal_actions(seat)
                self.assertEqual(mixed.act(engine, seat, legal),
                                 base.act(engine, seat, legal))
                engine.apply(seat, base.act(engine, seat, legal))

    def test_declarations_stay_truthful_even_at_epsilon_one(self):
        """A false tengo/no-tengo is rejected by the engine, so randomising
        declarations would only manufacture rejections."""
        engine = MusEngine(rng=Random(8))
        pol = EpsilonHeuristicPolicy(epsilon=1.0, bluff_p=1.0, seed=3)
        checked = 0
        for _ in range(60):
            engine.deal()
            while engine.phase != Phase.DONE:
                seat = engine.current_seat
                a = pol.act(engine, seat, engine.legal_actions(seat))
                if engine.phase == Phase.DECLARE:
                    lance = LANCE_NAMES[engine.lance_index]
                    hand = engine.hands[seat]
                    has = (engine._pares_value(hand)[0] > 0 if lance == "Pares"
                           else engine.hand_points(hand, engine.card_points)
                           in JUEGO_TOTALS)
                    self.assertEqual(a["action"], "tengo" if has else "no-tengo")
                    checked += 1
                engine.apply(seat, a)          # engine rejects a false one
        self.assertGreater(checked, 50)

    def test_full_bluff_always_opens_from_a_weak_hand(self):
        engine = MusEngine(rng=Random(4))
        pol = EpsilonHeuristicPolicy(epsilon=0.0, bluff_p=1.0, seed=5)
        opened = 0
        for _ in range(60):
            engine.deal()
            while engine.phase != Phase.DONE:
                seat = engine.current_seat
                legal = engine.legal_actions(seat)
                a = pol.act(engine, seat, legal)
                if (engine.phase == Phase.ENVITE and engine.envite.current == 0
                        and "envido" in legal):
                    self.assertIn(a["action"], ("envido", "ordago"))
                    opened += 1
                engine.apply(seat, a)
        self.assertGreater(opened, 20)
        self.assertGreater(pol.stats["bluff_open"], 0)


class ScorecardAgreementTest(unittest.TestCase):
    """The reference exists to calibrate the metrics: a policy whose bluff
    frequency is SET must be measured as bluffing more when it is raised."""

    def test_measured_bluffing_rises_with_the_configured_rate(self):
        rates = []
        for bp in (0.0, 0.6):
            spec = f"eps:0.05:{bp:g}"
            recs = play([spec, "heuristic", spec, "heuristic"], 12)
            card = analysis.scorecard(recs)[spec]
            rates.append(card["weak_hand_bet_rate"])
        self.assertLess(rates[0], rates[1] - 0.15)

    def test_the_deterministic_heuristic_barely_bluffs_at_all(self):
        recs = play(["heuristic", "random", "heuristic", "random"], 12)
        cards = analysis.scorecard(recs)
        self.assertLess(cards["heuristic"]["weak_hand_bet_rate"], 0.25)
        self.assertGreater(cards["random"]["weak_hand_bet_rate"], 0.45)

    def test_the_instrument_detects_a_real_skill_gap(self):
        """A positive control. If the scorecard cannot see random losing to a
        competent policy, no null result it reports is interpretable."""
        recs = play(["random", "heuristic", "random", "heuristic"], 12,
                    hands=200)
        out = analysis.outcome(recs)
        self.assertLess(out["piedras_diff_per_hand"], -1.0)
        cards = analysis.scorecard(recs)
        self.assertGreater(cards["random"]["weak_hand_bet_rate"],
                           cards["heuristic"]["weak_hand_bet_rate"] + 0.3)

    def test_strength_is_a_percentile_comparable_across_lances(self):
        """Every lance must be on the same scale, or a single threshold like
        OPEN_BID silently means something different in each one."""
        import statistics
        from random import Random as R
        from baselines_strict import _lance_strength
        from deck import make_deck
        engine = MusEngine(rng=R(0))
        rng = R(7)
        for lance in ("Grande", "Chica", "Pares", "Juego"):
            vals = []
            for _ in range(800):
                d = make_deck()
                rng.shuffle(d)
                engine.hands = {i: d[:4] for i in range(4)}
                vals.append(_lance_strength(engine, lance, 0))
            self.assertAlmostEqual(statistics.mean(vals), 0.5, delta=0.06,
                                   msg=f"{lance} is off-scale")

    def test_chica_strength_is_not_inverted(self):
        """The regression that started this: RANK_CHICA already encodes
        higher = better, so the old `1.0 - sum/44` scored a great Chica hand
        as weak and every Chica bluff was classified upside down."""
        from random import Random as R
        from baselines_strict import _lance_strength
        from deck import Card
        engine = MusEngine(rng=R(0))
        great = [Card(*c.split(" de ")) for c in
                 ("as de copas", "dos de oros", "tres de bastos",
                  "cuatro de espadas")]
        awful = [Card(*c.split(" de ")) for c in
                 ("caballo de copas", "sota de oros", "siete de bastos",
                  "seis de espadas")]
        engine.hands = {0: great, 1: awful, 2: great, 3: awful}
        self.assertGreater(_lance_strength(engine, "Chica", 0), 0.85)
        self.assertLess(_lance_strength(engine, "Chica", 1), 0.15)
        # and the engine agrees about who actually wins it
        self.assertEqual(engine._lance_winner("Chica"), 0)


if __name__ == "__main__":
    unittest.main()
