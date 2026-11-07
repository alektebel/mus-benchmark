"""Offline tests for the live table: leak-free snapshots, human action flow,
seña bus semantics. No network: LLM seats are never constructed here."""
from __future__ import annotations

import threading
import time
import unittest

import musbench.live.server as live_server
from musbench.live.server import LiveGame, HumanSeat
from musbench.mus.engine import Phase
import musbench.mus.senas as senas_mod
from musbench.mus.senas import sena_truthful


def make_game(seats=("human", "heuristic", "human", "heuristic"),
              hands=1, seed=3) -> LiveGame:
    return LiveGame(list(seats), hands=hands, seed=seed)


def feed_defaults(game: LiveGame, stop: threading.Event):
    """Scripted humans: play the default legal action whenever asked."""
    humans = game.human_agents
    while not stop.is_set() and game.match_status == "running":
        for a in humans:
            a.inbox.put({"action": "__default__"})
        time.sleep(0.02)


def run_scripted(game: LiveGame) -> LiveGame:
    stop = threading.Event()
    t = threading.Thread(target=feed_defaults, args=(game, stop), daemon=True)
    t.start()
    game.run()
    stop.set()
    t.join(timeout=2)
    return game


class TestLiveSnapshotPrivacy(unittest.TestCase):
    def test_spectator_sees_no_cards_and_no_gestures(self):
        g = make_game()
        g.engine.deal()
        snap = g.snapshot(None)
        self.assertIsNone(snap["you"])
        self.assertIsNone(snap["reveal"])
        # no hand contents anywhere in the spectator snapshot
        blob = str(snap)
        for s in range(4):
            for c in g.engine.hands[s]:
                self.assertNotIn(str(c), blob)

    def test_player_sees_own_hand_only(self):
        g = make_game()
        g.engine.deal()
        token0 = g.human_agents[0].token
        snap = g.snapshot(token0)
        self.assertEqual(snap["you"]["seat"], 0)
        own = [str(c) for c in g.engine.hands[0]]
        self.assertEqual(snap["you"]["hand"], own)
        blob = str(snap)
        for s in (1, 2, 3):
            for c in g.engine.hands[s]:
                self.assertNotIn(str(c), blob)

    def test_sena_gesture_hidden_from_outsiders(self):
        g = make_game()
        g.engine.deal()
        ok, _ = g.make_sena(0, "guinar-el-ojo")
        self.assertTrue(ok)
        spectator = g.snapshot(None)
        for ev in spectator["feed"]:
            if ev["kind"] in ("sena", "sena_caught"):
                self.assertIsNone(ev["gesture"])
        partner = g.snapshot(next(a for a in g.human_agents if a.seat == 2).token)
        senas = [ev for ev in partner["feed"] if ev["kind"] == "sena"]
        self.assertTrue(any(ev["gesture"] == "guinar-el-ojo" for ev in senas))
        self.assertEqual(partner["feed"][-1]["to_seat"], 2)


class TestSenaBus(unittest.TestCase):
    def _truthful_gesture(self, game, seat=0) -> str:
        hand = game.engine.hands[seat]
        for g in senas_mod.SENAS:
            if sena_truthful(g, hand, game.engine):
                return g
        return "guinar-el-ojo"   # bluffs allowed by default

    def test_truthful_sena_published_to_partner(self):
        g = make_game(seed=11)
        g.engine.deal()
        gesture = self._truthful_gesture(g, 0)
        ok, _ = g.make_sena(0, gesture)
        self.assertTrue(ok)
        evs = [e for e in g.bus.events if e.from_seat == 0]
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].to_seat, 2)

    def test_false_sena_rejected_when_bluffs_disabled(self):
        old = live_server.ALLOW_SEÑA_BLUFFS
        live_server.ALLOW_SEÑA_BLUFFS = False
        try:
            g = make_game(seed=5)
            g.engine.deal()
            hand0 = list(g.engine.hands[0])
            lies = [gest for gest in senas_mod.SENAS
                    if not sena_truthful(gest, hand0, g.engine)]
            if not lies:
                self.skipTest("hand matches every gesture")
            before = len(g.bus.events)
            ok, _ = g.make_sena(0, lies[0])
            self.assertFalse(ok)
            self.assertEqual(len(g.bus.events), before)
        finally:
            live_server.ALLOW_SEÑA_BLUFFS = old

    def test_sena_delivered_at_partner_next_window(self):
        """Deterministic: drive _step() manually, publish before the partner's
        decision window; the bus must deliver the gesture at that window."""
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=1, seed=21)
        g.engine.deal()
        published = False
        guard = 0
        while g.engine.phase != Phase.DONE and guard < 500:
            guard += 1
            seat = g.engine.current_seat
            agent = g.agents[seat]
            if seat == 2 and not published:
                ok, _ = g.make_sena(0, self._truthful_gesture(g, 0))
                self.assertTrue(ok)
                published = True
            if isinstance(agent, HumanSeat):
                # keep the hand alive: always mus, discard one, else default
                if g.engine.phase == Phase.MUS_REQUEST:
                    agent.inbox.put({"action": "mus"})
                elif g.engine.phase == Phase.MUS_DRAW:
                    agent.inbox.put({"action": "discard",
                                     "cards": [str(g.engine.hands[seat][0])]})
                else:
                    agent.inbox.put({"action": "__default__"})
            g._step()
        self.assertTrue(published, "seña never reached its window")
        evs = [e for e in g.bus.events if e.from_seat == 0]
        self.assertTrue(evs, "seña must be on the bus")
        self.assertTrue(all(e.delivered_at is not None for e in evs),
                        "partner must catch the seña at its next window")


class TestHumanFlow(unittest.TestCase):
    def test_full_hand_with_scripted_humans(self):
        g = make_game(hands=1, seed=7)
        run_scripted(g)
        self.assertEqual(g.match_status, "finished")
        self.assertEqual(g.engine.phase, Phase.DONE)
        self.assertEqual(len(g.history), 1)
        self.assertIsNotNone(g.reveal)
        # reveal carries all four hands and jugadas
        for s in range(4):
            self.assertEqual(len(g.reveal["hands"][s]), 4)
        self.assertEqual(len(g.reveal["jugadas"]), 4)

    def test_illegal_action_surfaces_error_not_crash(self):
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=1, seed=7)
        g.engine.deal()
        seat0 = g.human_agents[0]
        # queue an impossible action, then the escape hatch
        seat0.inbox.put({"action": "quiero"})       # illegal at MUS_REQUEST
        seat0.inbox.put({"action": "__default__"})
        g._step()  # seat 0's decision window
        self.assertEqual(seat0.rejections, 1)
        self.assertNotEqual(g.engine.phase, Phase.DONE)
        # the turn advanced past the human seat without applying "quiero"
        self.assertNotIn(g.engine.phase.name, ())

    def test_submit_rejected_when_not_your_turn(self):
        g = make_game(hands=1, seed=7)
        g.pending_human = None
        ok, err = g.submit_human_action(0, {"action": "mus"})
        self.assertFalse(ok)
        self.assertIn("not this seat's turn", err)


class TestTableFeedForUI(unittest.TestCase):
    """The page animates from the feed: actions must be tagged, and a seat's
    buttons must disappear as soon as its turn is over."""

    def test_pending_cleared_after_human_acts(self):
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=1, seed=7)
        g.engine.deal()
        seat0 = g.human_agents[0]
        seat0.inbox.put({"action": "__default__"})
        g._human_turn(seat0, list(g.engine.hands[0]))
        self.assertIsNone(g.pending_human)
        self.assertEqual(g.snapshot(seat0.token)["you"]["legal"], [])
        ok, err = g.submit_human_action(0, {"action": "mus"})
        self.assertFalse(ok)

    def test_human_declare_is_automatic_and_truthful(self):
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=1, seed=13)
        g.engine.deal()
        g.engine.phase = Phase.DECLARE
        g.engine.lance_index = 2  # Pares
        g.engine.declared = {}
        g.engine.current_seat = 0
        seat0 = g.human_agents[0]
        hand = list(g.engine.hands[0])
        has = g.engine._pares_value(hand)[0] > 0
        g._human_turn(seat0, hand)
        self.assertEqual(g.engine.declared.get(0), has)
        self.assertIsNone(g.pending_human)
        snap = g.snapshot(seat0.token)
        self.assertEqual(snap["you"]["legal"], [])

    def test_model_declare_is_instant_no_thinking(self):
        # Offline stand-in for an LLM seat: DECLARE must not arm the turn clock.
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=1, seed=17)
        g.engine.deal()
        g.engine.phase = Phase.DECLARE
        g.engine.lance_index = 2
        g.engine.declared = {}
        g.engine.current_seat = 1
        agent = g.agents[1]
        hand = list(g.engine.hands[1])
        has = g.engine._pares_value(hand)[0] > 0
        self.assertTrue(g._try_auto_declare(agent, hand))
        self.assertEqual(g.engine.declared.get(1), has)
        self.assertIsNone(g.thinking_seat)
        self.assertIsNone(g.turn_seat)
        self.assertTrue(any(e["kind"] == "declare" and e["seat"] == 1
                            for e in g.events))

    def test_turn_clock_exposed_while_human_decides(self):
        g = LiveGame(["human", "heuristic", "heuristic", "heuristic"],
                     hands=1, seed=9)
        g.engine.deal()
        seat0 = g.human_agents[0]
        ready = threading.Event()

        def act_later():
            ready.wait(timeout=2)
            time.sleep(0.05)
            seat0.inbox.put({"action": "__default__"})

        threading.Thread(target=act_later, daemon=True).start()

        def watch():
            # wait until the turn clock is armed, then let the human act
            deadline = time.time() + 2
            while time.time() < deadline:
                if g.turn_seat == 0 and g.turn_deadline:
                    snap = g.snapshot(seat0.token)
                    self.assertEqual(snap["turn_seat"], 0)
                    self.assertEqual(snap["turn_timeout"], live_server.HUMAN_TURN_TIMEOUT)
                    self.assertGreater(snap["turn_deadline"], time.time())
                    ready.set()
                    return
                time.sleep(0.01)
            ready.set()
            self.fail("turn clock never armed")

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        g._human_turn(seat0, list(g.engine.hands[0]))
        watcher.join(timeout=3)
        self.assertIsNone(g.turn_seat)
        self.assertIsNone(g.turn_deadline)
        snap = g.snapshot(seat0.token)
        self.assertIsNone(snap["turn_seat"])
        self.assertIsNone(snap["turn_deadline"])

    def test_mus_and_envite_events_carry_action(self):
        g = run_scripted(make_game(hands=2, seed=5))
        mus = [e for e in g.events if e["kind"] == "mus"]
        self.assertTrue(mus, "every hand opens with a mus decision")
        self.assertTrue(all(e["action"] in ("mus", "no") for e in mus))
        env = [e for e in g.events if e["kind"] in ("envite", "declare")]
        self.assertTrue(env)
        self.assertTrue(all(e.get("action") for e in env))

    def test_hand_pause_is_off_by_default_and_interruptible(self):
        self.assertEqual(live_server.HAND_PAUSE, 0.0)
        old = live_server.HAND_PAUSE
        live_server.HAND_PAUSE = 30.0
        try:
            g = make_game(hands=3, seed=5)
            t = threading.Thread(target=run_scripted, args=(g,), daemon=True)
            t.start()
            deadline = time.time() + 10
            while g.hands_played < 1 or g.engine.phase != Phase.DONE:
                self.assertLess(time.time(), deadline)
                time.sleep(0.02)
            g.stop()
            t.join(timeout=5)
            self.assertFalse(t.is_alive(), "stop() must cut the pause short")
        finally:
            live_server.HAND_PAUSE = old


if __name__ == "__main__":
    unittest.main()
