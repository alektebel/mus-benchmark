"""Tests for the public-hosting layer (sessions, budget, rate limits).

These never touch the network: the table factory is a stub, so nothing here
spends API credits.
"""
import os
import tempfile
import time
import unittest

import live_public


class FakeGame:
    def __init__(self, specs, hands):
        self.specs, self.hands = specs, hands
        self.agents = []
        self.stopped = False
        self.epoch = 1

    def stop(self):
        self.stopped = True


class FakeTable:
    """Stands in for LiveTable without an engine or any threads."""

    def __init__(self, specs, hands):
        self.specs, self.hands = specs, hands
        self.game = None

    def start_new(self, **_kw):
        self.game = FakeGame(self.specs, self.hands)
        return self.game

    def current(self):
        return self.game


def factory(llm: bool, hands: int):
    return FakeTable(live_public.public_specs(
        ["human", "glm5.3-flash", "deepseek-v4-flash", "qwen3.8-flash"], llm),
        hands)


class BudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.path = self.tmp.name

    def tearDown(self):
        for p in (self.path, self.path + ".tmp"):
            try:
                os.unlink(p)
            except OSError:
                pass

    def test_spend_until_exhausted(self):
        b = live_public.Budget(daily=3, path=self.path)
        self.assertEqual(b.remaining(), 3)
        self.assertTrue(b.spend())
        self.assertTrue(b.spend())
        self.assertTrue(b.spend())          # third call is still within budget
        self.assertFalse(b.spend())         # fourth crosses the ceiling
        self.assertTrue(b.exhausted())
        self.assertEqual(b.remaining(), 0)

    def test_survives_restart(self):
        """A crash loop must not hand out a fresh day's budget each restart."""
        b = live_public.Budget(daily=10, path=self.path)
        for _ in range(4):
            b.spend()
        again = live_public.Budget(daily=10, path=self.path)
        self.assertEqual(again.status()["calls"], 4)
        self.assertEqual(again.remaining(), 6)

    def test_readonly_fs_does_not_raise(self):
        b = live_public.Budget(daily=2, path="/proc/nonexistent/nope.json")
        self.assertTrue(b.spend())          # persistence fails, table survives


class MeteringTest(unittest.TestCase):
    def test_llm_seat_is_charged(self):
        b = live_public.Budget(daily=5, path=tempfile.mktemp(suffix=".json"))

        class Seat:
            is_llm = True

            def decide(self, prompt):
                return {"action": "paso"}

        seat = live_public.budgeted_agent(Seat(), b)
        seat.decide("x")
        seat.decide("x")
        self.assertEqual(b.status()["calls"], 2)

    def test_offline_seat_is_not_charged(self):
        b = live_public.Budget(daily=5, path=tempfile.mktemp(suffix=".json"))

        class Seat:
            is_llm = False

            def decide(self, prompt):
                return {"action": "paso"}

        seat = live_public.budgeted_agent(Seat(), b)
        self.assertEqual(b.status()["calls"], 0)

    def test_public_specs_keeps_human_seat(self):
        specs = ["human", "glm5.3-flash", "deepseek-v4-flash", "qwen3.8-flash"]
        off = live_public.public_specs(specs, llm=False)
        self.assertEqual(off[0], "human")
        self.assertEqual(off[1:], ["heuristic"] * 3)
        self.assertEqual(live_public.public_specs(specs, llm=True), specs)


class RegistryTest(unittest.TestCase):
    def _registry(self, **kw):
        b = live_public.Budget(daily=kw.pop("daily", 100),
                               path=tempfile.mktemp(suffix=".json"))
        return live_public.SessionRegistry(factory, b, **kw), b

    def test_sessions_are_independent(self):
        reg, _ = self._registry()
        a, _ = reg.create("sid-a")
        c, _ = reg.create("sid-c")
        self.assertIsNot(a.table, c.table)
        self.assertIsNot(a.table.current(), c.table.current())

    def test_restart_only_stops_own_game(self):
        reg, _ = self._registry()
        a, _ = reg.create("sid-a")
        c, _ = reg.create("sid-c")
        first_game_of_c = c.table.current()
        reg.create("sid-a")                 # A restarts
        self.assertFalse(first_game_of_c.stopped,
                         "one visitor restarting stopped another's game")

    def test_exhausted_budget_degrades_to_offline(self):
        reg, b = self._registry(daily=1)
        b.spend(); b.spend()                # push past the ceiling
        sess, note = reg.create("sid-x")
        self.assertEqual(note, "budget")
        self.assertFalse(sess.llm)
        self.assertEqual(sess.table.specs[1:], ["heuristic"] * 3)

    def test_llm_slots_are_capped(self):
        reg, _ = self._registry(max_llm=2)
        self.assertTrue(reg.create("a")[0].llm)
        self.assertTrue(reg.create("b")[0].llm)
        sess, note = reg.create("c")
        self.assertEqual(note, "busy")
        self.assertFalse(sess.llm, "third concurrent game still used models")

    def test_full_table_refuses(self):
        reg, _ = self._registry(max_sessions=2)
        reg.create("a")
        reg.create("b")
        sess, note = reg.create("c")
        self.assertIsNone(sess)
        self.assertEqual(note, "full")

    def test_idle_sessions_are_reaped(self):
        reg, _ = self._registry(idle_ttl=0.01)
        sess, _ = reg.create("old")
        game = sess.table.current()
        time.sleep(0.05)
        reg.create("new")                   # create() evicts first
        self.assertIsNone(reg.get("old"))
        self.assertTrue(game.stopped, "idle game left its engine running")

    def test_drop_stops_game(self):
        reg, _ = self._registry()
        sess, _ = reg.create("a")
        game = sess.table.current()
        reg.drop("a")
        self.assertIsNone(reg.get("a"))
        self.assertTrue(game.stopped)


class IPLimiterTest(unittest.TestCase):
    def test_allows_then_blocks(self):
        lim = live_public.IPLimiter(per_hour=3)
        self.assertTrue(all(lim.allow("1.2.3.4") for _ in range(3)))
        self.assertFalse(lim.allow("1.2.3.4"))

    def test_addresses_are_independent(self):
        lim = live_public.IPLimiter(per_hour=1)
        self.assertTrue(lim.allow("1.1.1.1"))
        self.assertFalse(lim.allow("1.1.1.1"))
        self.assertTrue(lim.allow("2.2.2.2"))


if __name__ == "__main__":
    unittest.main()


class ReturningPlayerTest(unittest.TestCase):
    def test_full_table_still_serves_its_own_players(self):
        """A seated player pressing 'Nueva partida' must not be told 'full'."""
        b = live_public.Budget(daily=100, path=tempfile.mktemp(suffix=".json"))
        reg = live_public.SessionRegistry(factory, b, max_sessions=2)
        reg.create("a")
        reg.create("b")
        self.assertIsNone(reg.create("c")[0])        # stranger refused
        sess, note = reg.create("a")                 # regular comes back
        self.assertIsNotNone(sess, "an existing player was refused their own slot")
        self.assertNotEqual(note, "full")

    def test_active_player_is_never_evicted_for_a_newcomer(self):
        b = live_public.Budget(daily=100, path=tempfile.mktemp(suffix=".json"))
        reg = live_public.SessionRegistry(factory, b, max_sessions=1,
                                          idle_ttl=3600)
        sess, _ = reg.create("incumbent")
        game = sess.table.current()
        refused, note = reg.create("newcomer")
        self.assertIsNone(refused)
        self.assertEqual(note, "full")
        self.assertFalse(game.stopped, "active game was killed to seat a newcomer")
        self.assertIsNotNone(reg.get("incumbent"))


class OfflineFallbackTest(unittest.TestCase):
    def test_session_reports_offline_when_factory_downgrades(self):
        """No API key -> the table deals heuristic seats and says so.

        The factory (in live_server) flips `llm_active` when the model seats
        cannot be built. The session must report what was actually dealt,
        otherwise the UI tells the visitor they are facing models when they
        are not.
        """
        b = live_public.Budget(daily=100, path=tempfile.mktemp(suffix=".json"))

        def downgrading_factory(llm, hands):
            tbl = FakeTable(["human"] + ["heuristic"] * 3, hands)
            tbl.llm_active = False          # as if StrictAgent construction failed
            return tbl

        reg = live_public.SessionRegistry(downgrading_factory, b)
        sess, note = reg.create("sid")
        self.assertFalse(sess.llm, "session claimed models it never dealt")
        self.assertEqual(note, "offline")

    def test_budget_note_survives_downgrade(self):
        b = live_public.Budget(daily=1, path=tempfile.mktemp(suffix=".json"))
        b.spend(); b.spend()

        def downgrading_factory(llm, hands):
            tbl = FakeTable(["human"] + ["heuristic"] * 3, hands)
            tbl.llm_active = False
            return tbl

        reg = live_public.SessionRegistry(downgrading_factory, b)
        _, note = reg.create("sid")
        self.assertEqual(note, "budget", "budget reason was overwritten")
