"""Local + Dynamo sink for live-game traces."""
from __future__ import annotations

import gzip
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import musbench.observe.trace_store as trace_store
from musbench.live.server import LiveGame


def _feed_defaults(game: LiveGame, stop: threading.Event):
    while not stop.is_set() and game.match_status == "running":
        for a in game.human_agents:
            a.inbox.put({"action": "__default__"})
        stop.wait(0.015)


class TraceStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.dir = self._tmpdir.name
        self._old_dir = os.environ.get("MUS_TRACE_DIR")
        self._old_table = os.environ.get("MUS_TRACE_TABLE")
        os.environ["MUS_TRACE_DIR"] = self.dir
        os.environ["MUS_TRACE_TABLE"] = ""  # force disk-only in unit tests
        # refresh module knobs that cache env at import
        trace_store.TABLE = ""

    def tearDown(self):
        if self._old_dir is None:
            os.environ.pop("MUS_TRACE_DIR", None)
        else:
            os.environ["MUS_TRACE_DIR"] = self._old_dir
        if self._old_table is None:
            os.environ.pop("MUS_TRACE_TABLE", None)
        else:
            os.environ["MUS_TRACE_TABLE"] = self._old_table
        trace_store.TABLE = os.environ.get("MUS_TRACE_TABLE", "mus-traces")
        self._tmpdir.cleanup()

    def test_save_writes_gzip_and_index(self):
        record = {"sid": "s1", "status": "finished", "nick": "diego",
                  "hands_played": 2, "vacas_a": 1, "vacas_b": 0,
                  "specs": ["human", "heuristic", "heuristic", "heuristic"]}
        self.assertTrue(trace_store.save_trace("s1", record))
        files = list(Path(self.dir).glob("s1-*.json.gz"))
        self.assertEqual(len(files), 1)
        loaded = json.loads(gzip.decompress(files[0].read_bytes()))
        self.assertEqual(loaded["nick"], "diego")
        self.assertEqual(loaded["status"], "finished")
        idx = (Path(self.dir) / "index.jsonl").read_text(encoding="utf8")
        self.assertIn('"sid": "s1"', idx)
        self.assertIn("diego", idx)

    def test_persist_game_mints_sid_and_is_idempotent(self):
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=1, seed=3)
        g.player_nick = "mesa"
        self.assertIsNone(g.sid)
        self.assertTrue(trace_store.persist_game(g))
        self.assertTrue(g.sid.startswith("local-"))
        self.assertTrue(g._trace_saved)
        # second call is a no-op success
        with mock.patch.object(trace_store, "save_trace") as save:
            self.assertTrue(trace_store.persist_game(g))
            save.assert_not_called()

    def test_finished_match_leaves_a_play_trace(self):
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=1, seed=11)
        g.player_nick = "jugador"
        g.sid = "e2e-trace-1"
        stop = threading.Event()
        t = threading.Thread(target=_feed_defaults, args=(g, stop), daemon=True)
        t.start()
        g.run()
        stop.set()
        t.join(timeout=2)
        self.assertEqual(g.match_status, "finished")
        self.assertGreater(len(g.play_log), 0)
        self.assertTrue(g._trace_saved)
        files = list(Path(self.dir).glob("e2e-trace-1-*.json.gz"))
        self.assertEqual(len(files), 1)
        rec = json.loads(gzip.decompress(files[0].read_bytes()))
        self.assertEqual(rec["nick"], "jugador")
        self.assertGreaterEqual(len(rec["play"]), 1)
        self.assertGreaterEqual(len(rec["history"]), 1)
        self.assertIn(rec["play"][0]["action"]["action"],
                      {"mus", "no", "perete", "discard", "tengo", "no-tengo",
                       "paso", "envido", "ordago", "quiero", "no-quiero",
                       "y-yo", "reenvido"})


if __name__ == "__main__":
    unittest.main()
