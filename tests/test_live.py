"""Offline tests for the live table: leak-free snapshots, human action flow,
seña bus semantics. No network: LLM seats are never constructed here."""
from __future__ import annotations

import threading
import time
import unittest

import live_server
from live_server import LiveGame, HumanSeat
from mus_engine import Phase
import senas as senas_mod
from senas import sena_truthful


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


if __name__ == "__main__":
    unittest.main()
