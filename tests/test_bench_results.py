"""Tests for bench_results aggregation (tournament summaries + batch files)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bench_results import aggregate_results, load_batch_results, \
    load_tournament_summary


def tournament_entry(a="glm", b="ds", seed=0, va=3, vb=1, hands=10,
                     status="done", llm_calls=90, fallbacks=2):
    e = {"job": f"{a}__vs__{b}__seed{seed}", "team_a": a, "team_b": b,
         "seed": seed, "status": status, "wall": 60.0}
    if status in ("done", "degraded"):
        e["metrics"] = {"vacas_a": va, "vacas_b": vb, "hands": hands,
                        "hand_wins": f"{va}-{vb}", "senas_published": 7,
                        "senas_caught": 4, "senas_missed": 3,
                        "llm_calls": llm_calls, "fallbacks": fallbacks,
                        "rejections": 1, "bluffs": 1, "elapsed_s": 600}
        e["policies"] = {}
    return e


def batch_file(models, seeds=(0, 1), vacas=(5, 2)):
    return {"config": {"opponent": "heuristic", "hands": 12},
            "results": [{"models": list(models), "seed": s, "status": "done",
                         "vacas_llm": vacas[0], "vacas_base": vacas[1],
                         "hand_wins_llm": 6, "hand_wins_base": 3,
                         "usage": {"calls": 50, "fallbacks": 1},
                         "elapsed": 123.4} for s in seeds]}


class TournamentTests(unittest.TestCase):
    def test_summary_rows_and_leaderboard(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "summary.json").write_text(json.dumps({"entries": [
                tournament_entry("glm", "ds", 0, 3, 1),
                tournament_entry("ds", "glm", 1, 2, 2),
            ]}))
            rows = load_tournament_summary(d / "summary.json")
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["vacas_a"], 3)
            agg = aggregate_results(td)
            lb = {k["model"]: k for k in agg["leaderboard"]}
            self.assertEqual(set(lb), {"glm", "ds"})
            self.assertEqual(lb["glm"]["vacas_for"], 5)     # 3 + 2
            self.assertEqual(lb["glm"]["vacas_against"], 3)  # 1 + 2
            self.assertEqual(lb["glm"]["matches"], 2)
            self.assertEqual(lb["glm"]["senas_published"], 14)
            # glm: W (3-1) + T (2-2); ds: L + T
            self.assertEqual((lb["glm"]["wins"], lb["glm"]["losses"],
                              lb["glm"]["ties"]), (1, 0, 1))
            self.assertEqual((lb["ds"]["wins"], lb["ds"]["losses"],
                              lb["ds"]["ties"]), (0, 1, 1))
            self.assertEqual(agg["leaderboard"][0]["model"], "glm")

    def test_degraded_noise_matches_excluded_from_leaderboard(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "summary.json").write_text(json.dumps({"entries": [
                # rate-limit cascade: lots of vacas, almost no LLM play
                tournament_entry("qwen", "glm", 5, va=6, vb=4,
                                 llm_calls=0, fallbacks=20),
                tournament_entry("glm", "ds", 0, va=1, vb=0,
                                 llm_calls=280, fallbacks=12),
            ]}))
            agg = aggregate_results(td)
            statuses = {m["label"]: m["status"] for m in agg["matches"]}
            self.assertEqual(statuses["qwen vs glm"], "degraded")
            self.assertEqual(statuses["glm vs ds"], "done")
            lb = {k["model"]: k for k in agg["leaderboard"]}
            self.assertNotIn("qwen", lb)
            self.assertEqual(lb["glm"]["vacas_for"], 1)
            self.assertEqual(lb["ds"]["vacas_against"], 1)

    def test_failed_entries_do_not_pollute_leaderboard(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "summary.json").write_text(json.dumps({"entries": [
                tournament_entry(status="failed (rc=1)"),
                tournament_entry("glm", "ds", 1),
            ]}))
            agg = aggregate_results(td)
            self.assertEqual(len(agg["matches"]), 2)
            self.assertEqual(len(agg["leaderboard"]), 2)
            self.assertTrue(all(k["matches"] == 1 for k in agg["leaderboard"]))
            failed = [m for m in agg["matches"] if m["status"] != "done"][0]
            self.assertIsNone(failed["vacas_a"])

    def test_malformed_summary_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "summary.json").write_text("{not json")
            self.assertEqual(load_tournament_summary(d / "summary.json"), [])
            self.assertEqual(aggregate_results(td)["matches"], [])


class BatchTests(unittest.TestCase):
    def test_batch_rows_and_leaderboard(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "batch1.json").write_text(json.dumps(
                batch_file(["glm"], seeds=(0, 1))))
            rows = load_batch_results(d / "batch1.json")
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["label"], "glm vs baseline")
            agg = aggregate_results(td)
            self.assertEqual(len(agg["leaderboard"]), 1)
            k = agg["leaderboard"][0]
            self.assertEqual(k["model"], "glm")
            self.assertEqual(k["matches"], 2)
            self.assertEqual(k["vacas_for"], 10)
            self.assertEqual(k["vacas_against"], 4)   # 2 per seed x 2 seeds

    def test_progress_file_shapes_are_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "progress.json").write_text(json.dumps(
                {"status": "running", "jobs": []}))
            self.assertEqual(aggregate_results(td), {
                "sources": [], "matches": [], "leaderboard": []})


if __name__ == "__main__":
    unittest.main()
