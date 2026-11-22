"""The public score: rating maths, roster/ledger plumbing, README render."""
import json
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from musbench.leaderboard import cli, rating, render


def _match(a, b, seed, margin, hands=8, protocol="v2", status="done"):
    return {"protocol": protocol, "team_a": a, "team_b": b, "seed": seed,
            "hands": hands, "piedras_a": 100 + margin * hands, "piedras_b": 100,
            "status": status, "llm_calls": 100, "fallbacks": 0}


def _synthetic(true, bias, seeds=range(4), noise=0.0, rng=None):
    out = []
    names = sorted(true)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            for s in seeds:
                for x, y in ((a, b), (b, a)):
                    e = rng.gauss(0, noise) if rng else 0.0
                    out.append(_match(x, y, s, true[x] - true[y] + bias + e))
    return out


class RatingTest(unittest.TestCase):
    def test_recovers_ratings_and_seat_bias(self):
        true = {"a": 3.0, "b": 0.0, "c": -1.0, "d": -2.0}   # mean 0
        f = rating.fit(_synthetic(true, bias=0.7))
        for k, v in true.items():
            self.assertAlmostEqual(f["ratings"][k], v, places=6)
        self.assertAlmostEqual(f["seat_bias"], 0.7, places=6)

    def test_anchor_pins_a_model_at_zero(self):
        true = {"a": 3.0, "b": 0.0, "c": -1.0}
        f = rating.fit(_synthetic(true, bias=0.0), anchor="c")
        self.assertAlmostEqual(f["ratings"]["c"], 0.0, places=6)
        self.assertAlmostEqual(f["ratings"]["a"], 4.0, places=6)

    def test_disconnected_graph_is_not_rated(self):
        ms = [_match("a", "b", 0, 1), _match("c", "d", 0, 1)]
        self.assertIsNone(rating.fit(ms))
        self.assertEqual(rating.rate(ms, n_boot=10)["rows"], [])

    def test_interval_covers_truth_and_best_is_found(self):
        true = {"a": 4.0, "b": 0.0, "c": -2.0}
        ms = _synthetic(true, 0.5, seeds=range(6), noise=3.0, rng=random.Random(1))
        res = rating.rate(ms, n_boot=400)
        top = res["rows"][0]
        self.assertEqual(top["model"], "a")
        self.assertGreater(top["p_best"], 0.9)
        for r in res["rows"]:
            self.assertLessEqual(r["ci_low"], r["score"])
            self.assertGreaterEqual(r["ci_high"], r["score"])

    def test_bootstrap_keeps_mirror_pairs_together(self):
        ms = _synthetic({"a": 1.0, "b": 0.0}, 0.0, seeds=range(3))
        blocks = rating._blocks(ms)
        self.assertEqual(len(blocks), 3)
        self.assertTrue(all(len(b) == 2 for b in blocks))


class LedgerTest(unittest.TestCase):
    cfg = {"protocol": "v2", "hands": 8, "seeds": [0, 1], "anchor": "",
           "bootstrap": 10,
           "models": {m: {"name": m.upper(), "spec": m} for m in ("x", "y", "z")}}

    def test_rated_matches_filters_protocol_roster_status(self):
        ledger = [_match("x", "y", 0, 1),
                  _match("x", "y", 1, 1, protocol="v1"),
                  _match("x", "gone", 0, 1),
                  _match("y", "x", 0, 1, status="degraded")]
        self.assertEqual(len(cli.rated_matches(self.cfg, ledger)), 1)

    def test_schedule_is_mirrored_and_skips_played(self):
        jobs = cli.schedule(self.cfg, [_match("x", "y", 0, 1)], "x")
        self.assertEqual(len(jobs), 2 * 2 * 2 - 1)       # 2 opps x 2 seeds x 2 seatings
        self.assertNotIn(("x", "y", 0), jobs)
        self.assertIn(("y", "x", 0), jobs)

    def test_ledger_row_splits_fallbacks_by_team(self):
        result = {"piedras_a": 30, "piedras_b": 20, "vacas_a": 1, "vacas_b": 0,
                  "hands": 8, "hands_completed": 8, "usage": {"fallbacks": 3},
                  "agents": [{"seat": 0, "is_llm": True, "calls": 10, "fallbacks": 2},
                             {"seat": 1, "is_llm": True, "calls": 9, "fallbacks": 1},
                             {"seat": 2, "is_llm": True, "calls": 11, "fallbacks": 0},
                             {"seat": 3, "is_llm": True, "calls": 8, "fallbacks": 0}]}
        row = cli.ledger_row(self.cfg, "x", "y", 0, result, "done", "abc")
        self.assertEqual((row["fallbacks_a"], row["fallbacks_b"]), (2, 1))
        self.assertEqual((row["llm_calls_a"], row["llm_calls_b"]), (21, 17))
        self.assertEqual(row["piedras_a"] - row["piedras_b"], 10)


class RenderTest(unittest.TestCase):
    def test_readme_splice_is_idempotent(self):
        res = rating.rate(_synthetic({"a": 1.0, "b": -1.0}, 0.0), n_boot=20)
        block = render.markdown(res, {"a": "Alpha"}, "v2")
        once = render.splice_readme("# title\n\nbody\n", block)
        twice = render.splice_readme(once, block)
        self.assertEqual(once, twice)
        self.assertTrue(once.startswith("# title\n\n" + render.START))
        self.assertIn("Best at mus right now: Alpha", once)

    def test_svg_has_one_row_per_model(self):
        res = rating.rate(_synthetic({"a": 1.0, "b": 0.0, "c": -1.0}, 0.0), n_boot=20)
        svg = render.svg(res, {}, "v2")
        self.assertEqual(svg.count('class="row"'), 3)
        self.assertNotIn("var(--", svg)   # rsvg/non-browser renderers


class IconTest(unittest.TestCase):
    def test_guess_provider_and_model_logos(self):
        from musbench.leaderboard import icons
        g = icons.guess("gemma4")
        self.assertEqual((g["provider"], g["provider_icon"], g["model_icon"]),
                         ("Google", "google-color", "gemma-color"))
        self.assertEqual(icons.guess("anthropic:claude-sonnet-5-5")["provider"], "Anthropic")
        self.assertEqual(icons.guess("mystery-model")["provider_icon"], "")

    def test_svg_inlines_both_logos_with_unique_ids(self):
        res = rating.rate(_synthetic({"gemma4": 1.0, "qwen3.6": 0.0}, 0.0), n_boot=20)
        svg = render.svg(res, {}, "v2")
        self.assertIn("Google", svg)
        self.assertIn("Alibaba Cloud", svg)
        self.assertEqual(svg.count('class="ico"'), 4)   # provider + model per row
        ids = __import__("re").findall(r' id="([^"]+)"', svg)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("<script", svg)

    def test_sanitize_strips_script_and_handlers(self):
        from musbench.leaderboard import icons
        bad = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
               '<script>alert(1)</script><path d="M0 0" onclick="x()"/></svg>')
        _, inner = icons._sanitize(bad, "t")
        self.assertNotIn("script", inner)
        self.assertNotIn("onclick", inner)


class OfflineRunTest(unittest.TestCase):
    """`run` end to end with free baseline seats: subprocess, ledger, score."""

    def test_run_and_score_with_baselines(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cfg_path, ledger = d / "models.toml", d / "matches.jsonl"
            cfg_path.write_text(
                '[benchmark]\nprotocol = "t"\nhands = 1\nseeds = [0]\nbootstrap = 20\n'
                '[[model]]\nid = "heuristic"\n[[model]]\nid = "random"\n')
            readme = d / "README.md"
            readme.write_text("# t\n")
            old = cli.CONFIG, cli.LEDGER, cli.ROOT, cli.REPLAYS
            cli.CONFIG, cli.LEDGER, cli.REPLAYS = cfg_path, ledger, d / "replays"
            try:
                cfg = cli.load_config(cfg_path)
                cli.cmd_run(cfg, [], SimpleNamespace(
                    id="heuristic", workers=2, job_timeout=300, out=str(d / "raw")))
                rows = cli.load_ledger(ledger)
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(r["status"] == "done" for r in rows))
                self.assertEqual({(r["team_a"], r["team_b"]) for r in rows},
                                 {("heuristic", "random"), ("random", "heuristic")})
                cli.ROOT = d
                cli.cmd_score(cfg, rows, SimpleNamespace(
                    readme="README.md", svg="lb.svg", json="lb.json"))
                out = json.loads((d / "lb.json").read_text())
                self.assertEqual(len(out["rows"]), 2)
                self.assertIn(render.START, readme.read_text())
            finally:
                cli.CONFIG, cli.LEDGER, cli.ROOT, cli.REPLAYS = old

    def test_elo_tournament_round_writes_replays_and_history(self):
        from musbench.leaderboard import replay
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "benchmark").mkdir()
            cfg_path, ledger = d / "models.toml", d / "matches.jsonl"
            cfg_path.write_text(
                '[benchmark]\nprotocol = "t"\nharness = "menu"\nhands = 2\n'
                'seeds = [0]\nanchor = ""\nstart_elo = 1500\ntournament = "tt"\n'
                'bootstrap = 20\n[[model]]\nid = "heuristic"\n[[model]]\nid = "random"\n')
            (d / "README.md").write_text("# t\n")
            old = cli.CONFIG, cli.LEDGER, cli.ROOT, cli.REPLAYS
            cli.CONFIG, cli.LEDGER, cli.REPLAYS = cfg_path, ledger, d / "replays"
            try:
                cfg = cli.load_config(cfg_path)
                cli.cmd_swiss(cfg, [], SimpleNamespace(
                    rounds=1, games=1, exclude=None, pairs=None, workers=2,
                    job_timeout=300, out=str(d / "raw"), boot=20))
                rows = cli.load_ledger(ledger)
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(r["tournament"] == "tt" for r in rows))
                rp = replay.read(d / "replays" / "tt" / (rows[0]["match_id"] + ".json.gz"))
                self.assertEqual(rp["format"], "mus-replay/1")
                self.assertEqual(len(rp["hands"]), 2)
                self.assertTrue(rp["hands"][0]["events"])
                self.assertIn("dealt", rp["hands"][0])
                cli.ROOT = d
                cli.cmd_score(cfg, rows, SimpleNamespace(
                    readme="README.md", svg="lb.svg", json="lb.json", boot=20))
                hist = (d / "benchmark" / "elo_history_tt.jsonl").read_text().splitlines()
                self.assertEqual(len(hist), 1)
                h = json.loads(hist[0])
                self.assertAlmostEqual(sum(h["elo_live"].values()) / 2, 1500, places=3)
                self.assertIn("Elo", (d / "README.md").read_text())
            finally:
                cli.CONFIG, cli.LEDGER, cli.ROOT, cli.REPLAYS = old


class EloTest(unittest.TestCase):
    @staticmethod
    def _game(x, y, seed, px, py):
        return [{"protocol": "v3", "team_a": x, "team_b": y, "seed": seed,
                 "hands": 8, "piedras_a": px, "piedras_b": py, "status": "done"},
                {"protocol": "v3", "team_a": y, "team_b": x, "seed": seed,
                 "hands": 8, "piedras_a": 0, "piedras_b": 0, "status": "done"}]

    def test_pairs_collapse_to_one_game_and_unpaired_drop(self):
        from musbench.leaderboard import elo
        ms = self._game("a", "b", 0, 50, 40) + [self._game("a", "b", 1, 9, 1)[0]]
        gs = elo.pair_games(ms)
        self.assertEqual(len(gs), 1)
        self.assertEqual(gs[0]["score"], 1.0)

    def test_stronger_model_rates_higher_and_anchor_is_pinned(self):
        from musbench.leaderboard import elo
        ms = []
        for s in range(12):      # a beats h 9/12, h beats b 9/12
            ms += self._game("a", "heuristic", s, 60 if s < 9 else 30, 45)
            ms += self._game("heuristic", "b", s, 60 if s < 9 else 30, 45)
        r = elo.fit(elo.pair_games(ms))
        self.assertAlmostEqual(r["heuristic"], 1000.0)
        self.assertGreater(r["a"], 1100)
        self.assertLess(r["b"], 900)

    def test_power_table_is_monotonic(self):
        from musbench.leaderboard import elo
        self.assertGreater(elo.games_needed(100), elo.games_needed(200))
        self.assertLessEqual(elo.games_needed(elo.gap_resolvable(30)), 30)

    def test_swiss_pairs_neighbours_and_avoids_repeats(self):
        ratings = {"a": 1300, "b": 1250, "c": 1000, "d": 950}
        self.assertEqual(cli.swiss_pairings(ratings, {}, list(ratings)),
                         [("a", "b"), ("c", "d")])
        played = {("a", "b"): {0, 1, 2}}
        self.assertEqual(cli.swiss_pairings(ratings, played, list(ratings))[0],
                         ("a", "c"))


if __name__ == "__main__":
    unittest.main()


class SwissFairnessTest(unittest.TestCase):
    def test_bye_goes_to_the_model_with_most_games(self):
        self.assertEqual(cli.choose_bye(["a", "b", "c"], {"a": 3, "b": 7, "c": 1}, 0), "b")

    def test_probe_reports_missing_credentials_instead_of_raising(self):
        import os
        from unittest import mock
        cfg = {"models": {"x": {"spec": "openrouter:some/model"}}}
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            ok, why = cli.probe(cfg, "x")
        self.assertFalse(ok)
        self.assertIn("OPENROUTER_API_KEY", why)
