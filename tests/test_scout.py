"""Scouting: dossier contents, report injection, failure handling, pairing."""
import gzip
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from random import Random
from types import SimpleNamespace
from unittest import mock

from musbench.agents.core import StrictAgent
from musbench.harness import menu, scout
from musbench.leaderboard import scouting


def _replay(match_id, seed, team_a, team_b, why="SECRET REASON"):
    ev = [{"seat": 0, "phase": "MUS_REQUEST", "public": "mus", "thought": why},
          {"seat": 1, "phase": "MUS_REQUEST", "public": "no hay mus", "thought": why},
          {"seat": 0, "phase": "ENVITE", "public": "Grande: envido", "thought": why},
          {"seat": 1, "phase": "ENVITE", "public": "Grande: no-quiero", "thought": why}]
    hand = {"hand": 1, "mano": 0, "events": ev,
            "showdown": {"0": ["rey de oros", "rey de copas", "siete de oros", "as de oros"],
                         "1": ["cinco de oros", "cuatro de copas", "dos de oros", "as de copas"],
                         "2": ["sota de oros", "seis de copas", "seis de oros", "dos de copas"],
                         "3": ["caballo de oros", "siete de copas", "cuatro de oros", "tres de copas"]},
            "lances": {"Grande": 0, "Chica": 1}, "gain": [1, 2]}
    return {"match_id": match_id, "seed": seed, "status": "done",
            "seats": [{"seat": i, "team": "AB"[i % 2],
                       "model": team_a if i % 2 == 0 else team_b} for i in range(4)],
            "hands": [hand]}


def _write(d, rp):
    with gzip.open(Path(d) / f"{rp['match_id']}.json.gz", "wt") as f:
        json.dump(rp, f)


class DossierTest(unittest.TestCase):
    def test_public_actions_and_showdown_only(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, _replay("m1", 3, "rival", "other"))
            txt = scout.dossier("rival", d, k=5, match_seed=1000)
        self.assertNotIn("SECRET", txt)                  # reasons stay private
        self.assertIn("X1 Grande: envido", txt)          # rival = team A here
        self.assertIn("O1 Grande: no-quiero", txt)
        self.assertIn("X1 rey rey siete as", txt)        # ranks, no suits
        self.assertNotIn("oros", txt)
        self.assertIn("Grande X, Chica O", txt)
        self.assertIn("Piedras X +1, O +2", txt)
        self.assertIn("Player X", txt)
        self.assertNotIn("rival", txt.replace("Player X", ""))  # anonymous

    def test_rival_on_team_b_is_still_x(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, _replay("m1", 3, "other", "rival"))
            txt = scout.dossier("rival", d, k=5, match_seed=1000)
        self.assertIn("X1 Grande: no-quiero", txt)
        self.assertIn("Grande O, Chica X", txt)

    def test_same_seed_never_scouted(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, _replay("m1", 1000, "rival", "other"))
            with self.assertRaises(SystemExit):
                scout.dossier("rival", d, k=5, match_seed=1000)


def _decide(prompts, report='{"report": "Player X folds Grande too often; bet it."}'):
    rng = Random(0)

    def decide(self, prompt):
        prompts.append((self.seat, prompt))
        self.calls += 1
        if '{"report"' in prompt:
            return json.loads(report)
        n = int(re.search(r"<1-(\d+)>", prompt).group(1))
        return {"choice": rng.randint(1, n), "why": "x"}
    return decide


@mock.patch.dict(os.environ, {"NAN_API_KEY": "test"})
@mock.patch.object(menu, "V4", True)
class ScoutMatchTest(unittest.TestCase):
    def test_report_reaches_only_the_scouting_team(self):
        prompts = []
        with mock.patch.object(StrictAgent, "decide", _decide(prompts)):
            r = menu.run_menu_match(["m", "n", "m", "n"], hands=2, seed=1000,
                                    scout={"team": 0, "dossier": "DOSSIER", "rival": "n"})
        self.assertEqual(r["status"], "done")
        self.assertIn("folds Grande", r["scout"]["report"])
        self.assertEqual(r["scout"]["dossier"], "DOSSIER")
        play = [(s, p) for s, p in prompts if '{"report"' not in p]
        self.assertTrue(any(s in (0, 2) for s, _ in play))
        for s, p in play:
            self.assertEqual("folds Grande" in p, s in (0, 2), f"seat {s}")
        first = [p for _, p in prompts if '{"report"' in p]
        self.assertEqual(len(first), 1)
        self.assertIn("DOSSIER", first[0])

    def test_no_usable_report_ends_the_match_unscored(self):
        prompts = []
        with mock.patch.object(StrictAgent, "decide", _decide(prompts, '{"report": ""}')):
            r = menu.run_menu_match(["m", "n", "m", "n"], hands=2, seed=1000,
                                    scout={"team": 1, "dossier": "D", "rival": "m"})
        self.assertEqual(r["status"], "no_answer")
        self.assertEqual(len(prompts), menu.ASKS)        # asked, re-asked, then stop

    def test_without_scout_prompts_have_no_notes(self):
        prompts = []
        with mock.patch.object(StrictAgent, "decide", _decide(prompts)):
            menu.run_menu_match(["m", "n", "m", "n"], hands=1, seed=1000)
        self.assertFalse(any("scouting notes" in p for _, p in prompts))


class PlanAndGainTest(unittest.TestCase):
    def _cfg(self):
        return {"models": {m: {"spec": m, "name": m.upper()} for m in ("a", "b", "c")}}

    def test_control_is_shared_between_both_scouting_directions(self):
        args = SimpleNamespace(scouters=None, exclude=None, pick_seed=0, named=False,
                               pairs="a:vs:b,b:vs:a", rivals=1, seed_base=1000, seeds=2)
        jobs = scouting.plan(self._cfg(), args)
        ctrl = [j for j in jobs if j["arm"] == "control"]
        anon = [j for j in jobs if j["arm"] == "anon"]
        self.assertEqual(len(ctrl), 4)        # 2 seeds x 2 seatings, once
        self.assertEqual(len(anon), 8)        # 2 scouters x 2 seeds x 2 seatings
        self.assertTrue(all(j["seed"] >= 1000 for j in jobs))

    def test_gain_is_scout_margin_minus_control_from_the_scouters_side(self):
        row = lambda t, a, b, pa, pb, **k: {"tournament": t, "team_a": a, "team_b": b,  # noqa: E731
                                           "seed": 1000, "status": "done", "hands": 8,
                                           "piedras_a": pa, "piedras_b": pb, **k}
        ledger = [row("s-control", "b", "a", 40, 0),
                  row("s-anon", "b", "a", 16, 24, arm="anon", scouter="a", rival="b")]
        g = scouting.gains(ledger, "s")
        self.assertEqual(len(g), 1)
        self.assertAlmostEqual(g[0]["control"], -5.0)   # a lost 40 over 8 hands
        self.assertAlmostEqual(g[0]["scout"], 1.0)
        self.assertAlmostEqual(g[0]["gain"], 6.0)


if __name__ == "__main__":
    unittest.main()


class ReplyParsingTest(unittest.TestCase):
    def test_a_self_correcting_reply_is_sent_back_not_guessed(self):
        from musbench.agents.cli_seat import read_reply
        raw = ('{"choice": 1, "why": "keep the pair"}\n\nWait, correction needed: '
               'option 3 is better.\n{"choice": 3, "why": "change the as"}')
        self.assertIsNone(read_reply(raw)[0])
        self.assertIsNone(read_reply("no json here")[0])

    def test_unreadable_reply_is_the_models_not_the_providers(self):
        from musbench.agents.cli_seat import CliAgent
        a = CliAgent("x", "claude-cli", "claude-haiku-5-5", 0, 0)
        done = SimpleNamespace(returncode=0, stdout=json.dumps({"result": "I fold"}), stderr="")
        with mock.patch("subprocess.run", return_value=done) as run:
            data = a.decide("prompt")
        self.assertEqual(run.call_count, 1)              # no blind CLI retries
        self.assertIsNone(menu._parse_choice(data, 3))   # so the harness re-asks
