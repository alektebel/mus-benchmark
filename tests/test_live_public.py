"""Tests for the public-hosting layer (sessions, budget, rate limits).

These never touch the network: the table factory is a stub, so nothing here
spends API credits.
"""
import os
import tempfile
import time
import unittest
from unittest import mock

import musbench.live.public as live_public


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

    def test_roll_lineup_keeps_human_and_samples_pool(self):
        import random
        os.environ["MUS_MODEL_POOL"] = "alpha,beta,gamma,delta"
        try:
            live_public._models_cache["ids"] = []
            template = ["human", "glm5.3-flash", "deepseek-v4-flash", "qwen3.6"]
            a = live_public.roll_lineup(template, rng=random.Random(1))
            b = live_public.roll_lineup(template, rng=random.Random(2))
            self.assertEqual(a[0], "human")
            self.assertEqual(b[0], "human")
            self.assertEqual(len(set(a[1:])), 3)
            # bare pool ids are normalized to nan:<id>
            expect = {"nan:alpha", "nan:beta", "nan:gamma", "nan:delta"}
            self.assertTrue(set(a[1:]).issubset(expect))
            self.assertNotEqual(a[1:], b[1:])
        finally:
            os.environ.pop("MUS_MODEL_POOL", None)
            live_public._models_cache["ids"] = []

    def test_list_chat_models_filters_non_chat_and_prefixes(self):
        live_public._models_cache["ids"] = []
        live_public._models_cache["at"] = 0.0

        def fake_fetch(provider):
            if provider == "nan":
                return ["glm5.3-flash", "whisper", "qwen3-embedding",
                        "flux-2-klein", "deepseek-v4-flash", "kokoro", "gemma4"]
            if provider == "nvidia":
                return [
                    "moonshotai/kimi-k2.6",
                    "mistralai/mistral-large",
                    "nvidia/nemotron-4-340b-instruct",
                    "google/gemma-4-31b-it",
                    "meta/llama-3.1-8b-instruct",
                    "nvidia/riva-translate-4b-instruct",
                ]
            if provider == "openrouter":
                return ["meta-llama/llama-3.3-70b:free", "openai/gpt-4o"]
            return []

        with mock.patch.object(live_public, "USE_VERIFIED_LIVE_POOL", False):
            with mock.patch.object(live_public, "ALLOW_NVIDIA_LIVE", True):
                with mock.patch.object(live_public, "_fetch_provider_model_ids",
                                       side_effect=fake_fetch):
                    with mock.patch.object(live_public, "OPENROUTER_FREE_ONLY", True):
                        with mock.patch(
                                "musbench.agents.jev_seat.list_jev_models",
                                return_value=["typesafe:jev-latest"]):
                            with mock.patch(
                                    "musbench.agents.anthropic_seat.list_anthropic_models",
                                    return_value=["anthropic:claude-haiku-5-5"]):
                                got = live_public.list_chat_models(force=True)
        self.assertEqual(got, [
            "nan:glm5.3-flash", "nan:deepseek-v4-flash", "nan:gemma4",
            "nvidia:moonshotai/kimi-k2.6",
            "nvidia:mistralai/mistral-large",
            "nvidia:nvidia/nemotron-4-340b-instruct",
            "typesafe:jev-latest",
            "anthropic:claude-haiku-5-5",
        ])
        self.assertNotIn("nvidia:google/gemma-4-31b-it", got)
        self.assertNotIn("nvidia:nvidia/riva-translate-4b-instruct", got)
        self.assertNotIn("openrouter:meta-llama/llama-3.3-70b:free", got)

    def test_verified_pool_excludes_nvidia_by_default(self):
        with mock.patch.object(live_public, "USE_VERIFIED_LIVE_POOL", True):
            with mock.patch.object(live_public, "ALLOW_NVIDIA_LIVE", False):
                got = live_public.list_chat_models(force=True)
        self.assertTrue(got)
        self.assertTrue(all(not s.startswith("nvidia:") for s in got))

    def test_list_chat_models_respects_mus_model_pool_specs(self):
        os.environ["MUS_MODEL_POOL"] = (
            "nan:a,nvidia:meta/llama,openrouter:x/y:free,bare")
        try:
            with mock.patch.object(live_public, "ALLOW_NVIDIA_LIVE", True):
                got = live_public.list_chat_models(force=True)
        finally:
            os.environ.pop("MUS_MODEL_POOL", None)
        self.assertEqual(got, [
            "nan:a", "nvidia:meta/llama", "openrouter:x/y:free", "nan:bare",
        ])


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

    def test_exhausted_budget_refuses_table(self):
        reg, b = self._registry(daily=1)
        b.spend(); b.spend()                # push past the ceiling
        sess, note = reg.create("sid-x")
        self.assertIsNone(sess)
        self.assertEqual(note, "budget")

    def test_llm_slots_are_capped(self):
        reg, _ = self._registry(max_llm=2)
        self.assertTrue(reg.create("a")[0].llm)
        self.assertTrue(reg.create("b")[0].llm)
        sess, note = reg.create("c")
        self.assertIsNone(sess)
        self.assertEqual(note, "busy")

    def test_bad_models_are_skipped_by_roll(self):
        live_public.clear_bad_models()
        live_public.mark_bad_model("nan:alpha")
        os.environ["MUS_MODEL_POOL"] = "alpha,beta,gamma"
        try:
            live_public._models_cache["ids"] = []
            out = live_public.roll_lineup(
                ["human", "x", "y", "z"], rng=__import__("random").Random(0))
        finally:
            os.environ.pop("MUS_MODEL_POOL", None)
            live_public.clear_bad_models()
            live_public._models_cache["ids"] = []
        self.assertEqual(out[0], "human")
        self.assertTrue(all(s.startswith("nan:") for s in out[1:]))
        self.assertNotIn("nan:alpha", out)

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

    def test_allowlist_skips_cap(self):
        lim = live_public.IPLimiter(per_hour=1, allowlist={"9.9.9.9"})
        self.assertTrue(all(lim.allow("9.9.9.9") for _ in range(20)))
        self.assertTrue(lim.allow("8.8.8.8"))
        self.assertFalse(lim.allow("8.8.8.8"))


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
    def test_session_refuses_when_factory_cannot_seat_llms(self):
        """If models cannot be built, refuse the table — never fake LLM seats."""
        b = live_public.Budget(daily=100, path=tempfile.mktemp(suffix=".json"))

        def downgrading_factory(llm, hands):
            tbl = FakeTable(["human"] + ["heuristic"] * 3, hands)
            tbl.llm_active = False
            return tbl

        reg = live_public.SessionRegistry(downgrading_factory, b)
        sess, note = reg.create("sid")
        self.assertIsNone(sess)
        self.assertEqual(note, "offline")

    def test_factory_raise_refuses_table(self):
        b = live_public.Budget(daily=100, path=tempfile.mktemp(suffix=".json"))

        def exploding_factory(llm, hands):
            raise RuntimeError("no models")

        reg = live_public.SessionRegistry(exploding_factory, b)
        sess, note = reg.create("sid")
        self.assertIsNone(sess)
        self.assertEqual(note, "offline")
