"""End-to-end coverage of the live table — offline, no provider API.

These drive a real LiveGame (and a tiny HTTP server) with heuristic seats so
every ship-critical path is exercised before deploy: mus → declare → envite →
órdago, perete, privacy, pool filters, and the public JSON surface.
"""
from __future__ import annotations

import json
import threading
import time
import unittest
from http.client import HTTPConnection
from unittest import mock

import musbench.live.public as live_public
import musbench.live.server as live_server
from musbench.live.server import LiveGame, LiveHTTP, LiveTable, HumanSeat
from musbench.mus.deck import Card
from musbench.mus.engine import Phase, is_perete


def _hand(*ranks, suits=("oros", "copas", "espadas", "bastos")):
    return [Card(r, s) for r, s in zip(ranks, suits)]


def _feed_defaults(game: LiveGame, stop: threading.Event):
    while not stop.is_set() and game.match_status == "running":
        for a in game.human_agents:
            a.inbox.put({"action": "__default__"})
        time.sleep(0.015)


def _run(game: LiveGame) -> LiveGame:
    stop = threading.Event()
    t = threading.Thread(target=_feed_defaults, args=(game, stop), daemon=True)
    t.start()
    game.run()
    stop.set()
    t.join(timeout=2)
    return game


class TestE2EFullVacaOffline(unittest.TestCase):
    def test_scripted_human_finishes_a_short_match(self):
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=2, seed=21)
        _run(g)
        self.assertEqual(g.match_status, "finished")
        self.assertEqual(len(g.history), 2)
        kinds = {e["kind"] for e in g.events}
        self.assertTrue({"mus", "envite", "hand_start", "hand_end"} <= kinds)


class TestE2EDeclareAndMusTempo(unittest.TestCase):
    def test_pares_declare_never_arms_llm_clock(self):
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=1, seed=3)
        g.engine.deal()
        g.engine.phase = Phase.DECLARE
        g.engine.lance_index = 2
        g.engine.declared = {}
        g.engine.current_seat = 1
        agent = g.agents[1]
        self.assertTrue(g._try_auto_declare(agent, list(g.engine.hands[1])))
        self.assertIsNone(g.thinking_seat)
        self.assertIsNone(g.turn_seat)
        self.assertIn(1, g.engine.declared)

    def test_juego_declare_is_truthful(self):
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=1, seed=4)
        g.engine.deal()
        g.engine.phase = Phase.DECLARE
        g.engine.lance_index = 3
        g.engine.declared = {}
        g.engine.current_seat = 2
        hand = _hand("rey", "caballo", "sota", "as")  # 31
        g.engine.hands[2] = hand
        self.assertTrue(g._try_auto_declare(g.agents[2], hand))
        self.assertTrue(g.engine.declared[2])

    def test_mus_snap_prompt_used_for_llm_path_shape(self):
        from musbench.agents.prompt_builder import build_mus_snap_prompt
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=1, seed=5)
        g.engine.deal()
        p = build_mus_snap_prompt(g.agents[1], g.engine, ["mus", "no"])
        self.assertLess(len(p), 1200)
        self.assertIn("farol", p.lower())
        self.assertNotIn("signal_policy", p)


class TestE2EPerete(unittest.TestCase):
    def test_perete_button_path_redraws_and_emits_event(self):
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=1, seed=8)
        g.engine.deal()
        g.engine.phase = Phase.MUS_REQUEST
        g.engine.current_seat = 0
        g.engine.hands[0] = _hand("cuatro", "cinco", "seis", "siete")
        self.assertTrue(is_perete(g.engine.hands[0]))
        self.assertIn("perete", g.engine.legal_actions(0))
        before = {str(c) for c in g.engine.hands[0]}
        g.engine.apply(0, {"action": "perete"})
        g._narrate(g.agents[0], {"action": "perete"})
        self.assertEqual(g.engine.phase, Phase.MUS_REQUEST)
        self.assertEqual(g.engine.current_seat, 0)
        self.assertNotEqual({str(c) for c in g.engine.hands[0]}, before)
        self.assertTrue(any(e["kind"] == "perete" and e.get("to_seat") == 1
                            for e in g.events))

    def test_llm_auto_perete_no_thinking(self):
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=1, seed=9)
        g.engine.deal()
        g.engine.phase = Phase.MUS_REQUEST
        g.engine.current_seat = 1
        g.engine.hands[1] = _hand("cuatro", "cinco", "seis", "siete")
        self.assertTrue(g._try_auto_perete(g.agents[1], list(g.engine.hands[1])))
        self.assertIsNone(g.thinking_seat)
        self.assertTrue(any(e["kind"] == "perete" for e in g.events))


class TestE2EEnviteAndOrdago(unittest.TestCase):
    def test_envite_needs_both_rivals_to_decline(self):
        from musbench.mus.engine import TEAM_OF
        g = LiveGame(["heuristic"] * 4, hands=1, seed=0)
        e = g.engine
        e.deal()
        e.apply(0, {"action": "no"})
        self.assertEqual(e.phase, Phase.ENVITE)
        opener = e.current_seat
        e.apply(opener, {"action": "envido"})
        holder_team = TEAM_OF[e.envite.holder]
        grande = e.lance_index
        before = (e.points_a, e.points_b)
        folded = []
        for _ in range(10):
            if e.lance_index != grande:
                break
            seat = e.current_seat
            if TEAM_OF[seat] == holder_team:
                e.apply(seat, {"action": "paso"})
                continue
            e.apply(seat, {"action": "no-quiero"})
            folded.append(seat)
            if len(folded) == 1:
                self.assertEqual(e.lance_index, grande)
                self.assertEqual((e.points_a, e.points_b), before)
        self.assertEqual(len(folded), 2)
        self.assertGreater(e.lance_index, grande)

    def test_ordago_needs_both_rivals_to_retract(self):
        from musbench.mus.engine import TEAM_OF
        g = LiveGame(["heuristic"] * 4, hands=1, seed=1)
        e = g.engine
        e.deal()
        e.apply(0, {"action": "no"})
        opener = e.current_seat
        e.apply(opener, {"action": "ordago"})
        self.assertEqual(e.phase, Phase.ORDAGO_RESPONSE)
        caller_team = TEAM_OF[e.ordago_caller]
        grande = e.lance_index
        retracted = []
        for _ in range(4):
            if e.phase != Phase.ORDAGO_RESPONSE:
                break
            seat = e.current_seat
            self.assertNotEqual(TEAM_OF[seat], caller_team)
            e.apply(seat, {"action": "no-quiero"})
            retracted.append(seat)
            if len(retracted) == 1:
                self.assertEqual(e.phase, Phase.ORDAGO_RESPONSE)
        self.assertEqual(len(retracted), 2)
        self.assertGreater(e.lance_index, grande)

    def test_second_rival_can_accept_ordago(self):
        from musbench.mus.engine import TEAM_OF
        g = LiveGame(["heuristic"] * 4, hands=1, seed=2)
        e = g.engine
        e.deal()
        e.apply(0, {"action": "no"})
        e.apply(e.current_seat, {"action": "ordago"})
        first = e.current_seat
        e.apply(first, {"action": "no-quiero"})
        self.assertEqual(e.phase, Phase.ORDAGO_RESPONSE)
        second = e.current_seat
        self.assertNotEqual(TEAM_OF[second], TEAM_OF[e.ordago_caller])
        e.apply(second, {"action": "quiero"})
        self.assertEqual(e.phase, Phase.DONE)


class TestE2EPrivacyAndPool(unittest.TestCase):
    def test_spectator_snapshot_hides_hands(self):
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=1, seed=6)
        g.engine.deal()
        snap = g.snapshot(None)
        blob = json.dumps(snap)
        for s in range(4):
            for c in g.engine.hands[s]:
                self.assertNotIn(str(c), blob)

    def test_verified_pool_has_no_nvidia_by_default(self):
        with mock.patch.object(live_public, "USE_VERIFIED_LIVE_POOL", True):
            with mock.patch.object(live_public, "ALLOW_NVIDIA_LIVE", False):
                pool = live_public.list_chat_models(force=True)
        self.assertTrue(pool)
        self.assertTrue(all(not s.startswith("nvidia:") for s in pool))

    def test_api_failure_keeps_same_seat_model(self):
        """Regression: no mid-hand seat_swap on LLMCallFailure."""
        from musbench.live.apifail import LLMCallFailure
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=1, seed=10)
        g.engine.deal()
        g.engine.phase = Phase.ENVITE
        g.engine.current_seat = 1

        from musbench.agents.groupchat import PerceptionBudget

        class Stub:
            is_llm = True
            name = "B1"
            seat = 1
            team = 1
            model = "stub-model"
            provider = "nan"
            api_errors = 0
            fallbacks = 0
            rejections = 0
            thoughts = []
            last_io = {}
            deadline = None
            preplan = None
            preplan_key = None
            fast_turn = False
            snap_turn = False
            budget = PerceptionBudget()

            def decide(self, prompt):
                raise LLMCallFailure("silent")

        stub = Stub()
        g.agents[1] = stub
        g.specs[1] = "nan:stub-model"
        g.lineup[1] = "nan:stub-model"
        live_server.AUTO_MUS = False
        g._llm_turn(stub, list(g.engine.hands[1]))
        self.assertIs(g.agents[1], stub)
        self.assertEqual(g.specs[1], "nan:stub-model")
        self.assertFalse(any(e["kind"] == "seat_swap" for e in g.events))
        self.assertTrue(any(e["kind"] in ("api_error", "fallback")
                            for e in g.events))


class TestE2EHTTPSmoke(unittest.TestCase):
    """Spin a local non-public LiveHTTP and walk /healthz → /snapshot."""

    def setUp(self):
        live_server._public = False
        live_server._registry = None
        live_server._budget = None
        live_server._iplimit = None
        live_server._allow_origins = set()
        self.table = LiveTable(
            ["human", "heuristic", "heuristic", "heuristic"],
            hands=1, seed=42)
        self.table.start_new(hands=1, seed=42)
        live_server._table = self.table
        self.httpd = live_server.ThreadingHTTPServer(("127.0.0.1", 0), LiveHTTP)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        try:
            self.table.game.stop()
        except Exception:
            pass
        self.httpd.shutdown()
        self.httpd.server_close()
        live_server._table = None

    def _raw(self, method, path, body=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        raw = None if body is None else json.dumps(body).encode()
        hdrs = {"Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        conn.request(method, path, body=raw, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def _json(self, method, path, body=None, headers=None):
        status, data = self._raw(method, path, body=body, headers=headers)
        return status, json.loads(data.decode() or "null")

    def test_health_new_snapshot_and_human_action(self):
        status, body = self._raw("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertIn(b"ok", body.lower())
        game = self.table.current()
        token = game.human_agents[0].token
        deadline = time.time() + 3
        while time.time() < deadline and game.pending_human is None \
                and game.match_status == "running":
            time.sleep(0.02)
        status, snap = self._json(
            "GET", f"/snapshot?token={token}&reveal=none")
        self.assertEqual(status, 200)
        self.assertEqual(snap["status"], "running")
        self.assertIsNotNone(snap["you"])
        self.assertEqual(len(snap["you"]["hand"]), 4)
        if game.pending_human and game.pending_human.get("seat") == 0:
            ok, _ = game.submit_human_action(
                0, {"action": game.pending_human["legal"][0]})
            self.assertTrue(ok)


class TestE2EEngineInvariants(unittest.TestCase):
    """Lightweight property checks — not formal proofs, but ship gates."""

    def test_deal_conserves_forty_cards(self):
        from musbench.mus.deck import make_deck
        g = LiveGame(["heuristic"] * 4, hands=1, seed=99)
        for i in range(20):
            g.engine.deal()
            cards = (sum(g.engine.hands.values(), [])
                     + g.engine.draw_pile + g.engine.discard_pile)
            self.assertCountEqual(cards, make_deck(), msg=f"deal {i}")

    def test_false_pares_declare_rejected(self):
        g = LiveGame(["heuristic"] * 4, hands=1, seed=7)
        e = g.engine
        e.deal()
        e.phase = Phase.DECLARE
        e.lance_index = 2
        e.declared = {}
        e.current_seat = 0
        e.hands[0] = _hand("rey", "rey", "as", "dos")  # has pares
        from musbench.mus.engine import IllegalAction
        with self.assertRaises(IllegalAction):
            e.apply(0, {"action": "no-tengo"})
        self.assertEqual(e.declared, {})


if __name__ == "__main__":
    unittest.main()
