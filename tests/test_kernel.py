import unittest
from random import Random
from unittest.mock import patch

from deck import Card
from groupchat import Channels
from mus_engine import MusEngine, Phase, LANCE_NAMES, TEAM_OF
from senas import SENAS
import agents
import apifail
import virtual_kernel as vk
from signal_bus import SignalBus
from signal_manager import (PolicyError, SignalManager, SignalPolicy,
                            SignalRule, reference_policy)
from virtual_kernel import Kernel, SeatProcess, run_hand_kernel, \
    run_match_kernel, make_procs


TWO_KINGS = [Card('rey', 'oros'), Card('tres', 'copas'),
             Card('cuatro', 'bastos'), Card('cinco', 'espadas')]


def honest_action(agent, extra=None):
    """Plays the smallest honest line at the engine until the hand closes."""
    e = agent.engine
    if e.phase == Phase.MUS_REQUEST:
        action = {"action": "no"}
    elif e.phase == Phase.DECLARE:
        lance = LANCE_NAMES[e.lance_index]
        if lance == "Pares":
            has = e._pares_value(e.hands[agent.seat])[0] > 0
        else:
            has = e.hand_points(e.hands[agent.seat], e.card_points) in e.juego_totals
        action = {"action": "tengo" if has else "no-tengo"}
    elif e.phase == Phase.ENVITE:
        action = {"action": "paso"}
    elif e.phase == Phase.ORDAGO_RESPONSE:
        action = {"action": "no-quiero"}
    else:
        raise AssertionError(f"unexpected phase {e.phase}")
    action.update(extra or {})
    return action


class ScriptSeat(agents.SeatBase):
    """LLM-parity seat: one decide() call per decision, zero retries."""
    is_llm = True

    def __init__(self, seat, team, engine, extra_fn=None):
        self.name = f"S{seat}"
        self.model = "script"
        self.seat = seat
        self.team = team
        self.engine = engine
        self.extra_fn = extra_fn
        self.deadline = None
        self.prompts = []
        self._init_state()

    def decide(self, prompt):
        self.calls += 1
        self.prompts.append(prompt)
        extra = self.extra_fn(self) if self.extra_fn else None
        return honest_action(self, extra)


def four_script_seats(engine, extra_fns=None):
    return [ScriptSeat(s, TEAM_OF[s], engine,
                       (extra_fns or {}).get(s)) for s in range(4)]


def procs_for(agents_, managers=None):
    managers = managers or {}
    return [SeatProcess(agent=a, manager=managers.get(a.seat,
                                                     SignalManager(seat=a.seat)))
            for a in agents_]


class SignalBusTests(unittest.TestCase):
    def test_pending_ttl_and_delivery(self):
        bus = SignalBus()
        e1 = bus.publish(0, 2, "elevar-las-cejas", 0.15, 5.0)
        e2 = bus.publish(0, 2, "guinar-el-ojo", 0.5, 0.4)     # dies at 0.9
        bus.publish(0, 2, "torcer-los-labios", 0.2, 5.0)
        pending = bus.pending_for(2, 1.0)
        self.assertEqual([ev.seq for ev in pending], [e1.seq, 2])  # by (t_pub, seq)
        self.assertTrue(e2.expired)
        bus.deliver(pending, 1.0)
        self.assertEqual(bus.pending_for(2, 1.0), [])
        self.assertEqual(bus.counts_for(0)["sent"], 3)

    def test_wrong_addressee_never_sees(self):
        bus = SignalBus()
        bus.publish(0, 2, "elevar-las-cejas", 0.1, 5.0)
        self.assertEqual(bus.pending_for(1, 1.0), [])

    def test_gesture_live(self):
        bus = SignalBus()
        ev = bus.publish(0, 2, "elevar-las-cejas", 0.1, 5.0)
        self.assertTrue(bus.gesture_live(0, "elevar-las-cejas", 0.5))
        bus.deliver([ev], 1.0)
        self.assertTrue(bus.gesture_live(0, "elevar-las-cejas", 1.0))
        ev2 = bus.publish(0, 2, "guinar-el-ojo", 0.1, 0.3)
        self.assertFalse(bus.gesture_live(0, "guinar-el-ojo", 1.0))


class PolicyTests(unittest.TestCase):
    def test_rule_validation(self):
        with self.assertRaises(PolicyError):
            SignalRule(gesture="wink-face")
        with self.assertRaises(PolicyError):
            SignalRule(gesture="guinar-el-ojo", offset=1.5)
        with self.assertRaises(PolicyError):
            SignalRule(gesture="guinar-el-ojo", ttl=0)
        with self.assertRaises(PolicyError):
            SignalRule(gesture="guinar-el-ojo", when_phase="FINALE")
        with self.assertRaises(PolicyError):
            SignalRule(gesture="guinar-el-ojo", bluff="yes")

    def test_policy_json_roundtrip_and_rejects(self):
        p = SignalPolicy(rules=(SignalRule("elevar-las-cejas", when_phase="ENVITE",
                                           offset=0.2, ttl=6.0),))
        q = SignalPolicy.from_json(p.to_json())
        self.assertEqual(q.rules, p.rules)
        with self.assertRaises(PolicyError):
            SignalPolicy.from_json({"rules": [{"gesture": "nope"}]})
        with self.assertRaises(PolicyError):
            SignalPolicy.from_json({"rules": [{"gesture": "guinar-el-ojo",
                                               "sneaky": 1}]})
        with self.assertRaises(PolicyError):
            SignalPolicy.from_json({"rules": [{"gesture": "guinar-el-ojo"}] * 17,
                                    "enabled": True})
        with self.assertRaises(PolicyError):
            SignalPolicy.from_json("not even an object")


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.engine = MusEngine(Random(3))
        self.engine.deal()
        self.engine.hands[0] = list(TWO_KINGS)

    def test_reference_fires_only_for_true_gesture_and_partner_window(self):
        mgr = SignalManager(seat=0, policy=reference_policy())
        intents = mgr.evaluate(self.engine, deciding_seat=2, t0=10.0, window=1.0)
        self.assertEqual([i.gesture for i in intents],
                         ["muerde-el-labio-inferior"])   # exactly the 2-reyes sena
        self.assertAlmostEqual(intents[0].t_pub, 10.15)
        self.assertTrue(intents[0].truthful)
        # an opponent deliberating: a sena to your partner is not for that moment
        self.assertEqual(mgr.evaluate(self.engine, deciding_seat=1, t0=11.0,
                                      window=1.0), [])

    def test_false_needs_bluff(self):
        rule = SignalRule("guinar-el-ojo", bluff=True)      # hand is not 30/31
        strict = SignalManager(seat=0, policy=SignalPolicy((rule,)),
                               allow_bluffs=False)
        loose = SignalManager(seat=0, policy=SignalPolicy((rule,)),
                              allow_bluffs=True)
        self.assertEqual(strict.evaluate(self.engine, 2, 0.0, 1.0), [])
        self.assertEqual(strict.dropped_false, 1)
        intents = loose.evaluate(self.engine, 2, 0.0, 1.0)
        self.assertEqual(len(intents), 1)
        self.assertFalse(intents[0].truthful)
        self.assertEqual(loose.bluffs, 1)

    def test_caught_gesture_not_repeated(self):
        bus = SignalBus()
        mgr = SignalManager(seat=0, policy=reference_policy())
        intents = mgr.evaluate(self.engine, 2, 0.0, 1.0, bus=bus)
        ev = bus.publish(0, 2, intents[0].gesture, intents[0].t_pub,
                         intents[0].ttl)
        bus.deliver([ev], 1.0)
        self.assertEqual(mgr.evaluate(self.engine, 2, 4.0, 1.0, bus=bus), [])


class KernelTimingTests(unittest.TestCase):
    def test_batched_delivery_respects_window(self):
        bus = SignalBus()
        bus.publish(0, 2, "elevar-las-cejas", 0.15, 5.0)   # mid-window gesture
        # the deliberating partner does NOT see it during its own window
        self.assertEqual(bus.pending_for(2, 0.1), [])
        # it is caught at the NEXT decision window start
        self.assertEqual(len(bus.pending_for(2, 1.5)), 1)


class KernelMatchTests(unittest.TestCase):
    def test_one_api_call_per_decision(self):
        engine = MusEngine(rng=Random(7))
        engine.deal()
        ch, bus = Channels(), SignalBus()
        kernel = Kernel(rng=Random(7))
        stats = {"turns": 0, "fallbacks": 0, "events": []}
        seats = four_script_seats(engine)
        procs = procs_for(seats)
        run_hand_kernel(engine, procs, ch, bus, kernel, stats, deal=False)
        self.assertEqual(engine.phase, Phase.DONE)
        total_calls = sum(a.calls for a in seats)
        self.assertEqual(total_calls, stats["turns"])          # no amplification
        self.assertEqual(total_calls, stats["llm_turns"])

    def test_partner_sena_reaches_next_prompt(self):
        engine = MusEngine(rng=Random(7))
        engine.deal()
        engine.hands[0] = list(TWO_KINGS)     # guarantees the 2-reyes sena
        ch, bus = Channels(), SignalBus()
        kernel = Kernel(rng=Random(7))
        stats = {"turns": 0, "fallbacks": 0, "events": []}
        seats = four_script_seats(engine)
        procs = procs_for(seats)
        procs[0].manager = SignalManager(seat=0, policy=reference_policy())
        run_hand_kernel(engine, procs, ch, bus, kernel, stats, deal=False)
        self.assertGreater(procs[0].manager.published, 0)
        self.assertGreater(procs[2].delivered, 0)
        self.assertTrue(any("seat 0 sena: muerde-el-labio-inferior" in p
                            for p in seats[2].prompts))
        # opponents never see partner-directed senas delivered in their prompts
        self.assertTrue(all("seat 0 sena:" not in p for p in seats[1].prompts))
        self.assertTrue(all("seat 0 sena:" not in p for p in seats[3].prompts))
        # and the bus itself never addressed one to an opponent
        self.assertEqual([ev for ev in bus.events if ev.to_seat in (1, 3)], [])

    def test_declared_policy_installs_and_invalid_rejected(self):
        engine = MusEngine(rng=Random(9))
        engine.deal()
        good = {"rules": [{"gesture": "elevar-las-cejas", "when_lance": "Grande",
                           "offset": 0.0, "ttl": 6}], "enabled": True}
        bad = {"rules": [{"gesture": "telepathy"}]}

        def first_envite_extra(seat):
            def fn(agent):
                if (agent.engine.phase == Phase.ENVITE
                        and not getattr(agent, "_policy_sent", False)):
                    agent._policy_sent = True
                    return {"signal_policy": good if seat == 1 else bad}
                return None
            return fn

        ch, bus = Channels(), SignalBus()
        kernel = Kernel(rng=Random(9))
        stats = {"turns": 0, "fallbacks": 0, "events": []}
        seats = four_script_seats(engine, {1: first_envite_extra(1),
                                           3: first_envite_extra(3)})
        procs = procs_for(seats)
        run_hand_kernel(engine, procs, ch, bus, kernel, stats, deal=False)
        self.assertEqual(len(procs[1].manager.policy.rules), 1)
        self.assertEqual(procs[3].manager.policy.rules, ())
        self.assertEqual(procs[3].manager.invalid_policies, 1)

    def test_one_shot_action_signal_is_partner_directed(self):
        engine = MusEngine(rng=Random(11))
        engine.deal()
        engine.hands[0] = list(TWO_KINGS)      # 29 pts: guinar-el-ojo is a lie
        ch, bus = Channels(), SignalBus()
        kernel = Kernel(rng=Random(11))
        stats = {"turns": 0, "fallbacks": 0, "events": []}
        hand_is_not_30 = {"action": "no", "signal": "guinar-el-ojo"}

        def first(seat_signal):
            def fn(agent):
                if agent.calls == 1:
                    return {"signal": seat_signal}
                return None
            return fn

        seats = four_script_seats(engine, {0: first("guinar-el-ojo")})
        procs = procs_for(seats)
        with patch.object(vk, "ALLOW_SEÑA_BLUFFS", True):
            run_hand_kernel(engine, procs, ch, bus, kernel, stats, deal=False)
        evs = [ev for ev in bus.events if ev.from_seat == 0]
        self.assertEqual([ev.to_seat for ev in evs], [2])
        self.assertEqual(seats[0].bluffs, 1)
        self.assertFalse(evs[0].truthful_at_pub)

        engine2 = MusEngine(rng=Random(11))
        engine2.deal()
        engine2.hands[0] = list(TWO_KINGS)
        seats2 = four_script_seats(engine2, {0: first("guinar-el-ojo")})
        procs2 = procs_for(seats2)
        stats2 = {"turns": 0, "fallbacks": 0, "events": []}
        with patch.object(vk, "ALLOW_SEÑA_BLUFFS", False):
            run_hand_kernel(engine2, procs2, Channels(), SignalBus(),
                            Kernel(rng=Random(11)), stats2, deal=False)
        self.assertEqual(seats2[0].invalid_signals, 1)
        self.assertEqual(seats2[0].bluffs, 0)

    def test_one_shot_truth_uses_deliberation_hand(self):
        # a gesture emitted by a MUS_DRAW action must be judged against the
        # hand the agent deliberated with, not the post-draw engine state
        engine = MusEngine(rng=Random(11))
        engine.deal()
        before = [Card('cuatro', 'bastos'), Card('cinco', 'espadas'),
                  Card('seis', 'oros'), Card('siete', 'copas')]  # 22 pts ciego
        engine.hands[0] = [Card('rey', 'oros'), Card('rey', 'copas'),
                           Card('tres', 'bastos'), Card('cuatro', 'espadas')]
        ch, bus = Channels(), SignalBus()
        kernel = Kernel(rng=Random(11))
        seats = four_script_seats(engine)
        proc = procs_for(seats)[0]
        action = {"action": "no", "signal": "cerrar-los-ojos"}
        vk._emit_kernel(proc, action, ch, engine, bus, kernel, hand=before)
        self.assertTrue(seats[0].senas_log[-1][1])
        vk._emit_kernel(proc, action, ch, engine, bus, kernel)
        self.assertFalse(seats[0].senas_log[-1][1])

    def test_kernel_run_is_reproducible(self):
        common = dict(hands=4, seed=7)
        r1 = run_match_kernel(MusEngine(rng=Random(7)),
                              ["heuristic", "random", "heuristic", "random"],
                              **common)
        r2 = run_match_kernel(MusEngine(rng=Random(7)),
                              ["heuristic", "random", "heuristic", "random"],
                              **common)
        for r in (r1, r2):
            r.pop("elapsed")
        self.assertEqual(r1, r2)
        self.assertGreater(r1["signals"]["published"], 0)
        self.assertEqual(r1["signals"]["published"],
                         r1["signals"]["caught"] + r1["signals"]["missed"])

    def test_make_procs_reference_floor_for_baselines(self):
        ags = [agents.BaselineSeat(f"B{i}", "heuristic", i, i % 2)
               for i in range(4)]
        procs = make_procs(ags)
        self.assertEqual(len(procs[0].manager.policy.rules), len(SENAS))


class FlakySeat(ScriptSeat):
    """LLM-parity seat whose provider fails: first `fail_times` decisions
    raise LLMCallFailure (as after exhausted retries)."""

    def __init__(self, seat, team, engine, fail_times=1,
                 error=apifail.LLMCallFailure("truncated (finish=length)")):
        super().__init__(seat, team, engine)
        self.fail_times = fail_times
        self.error = error

    def decide(self, prompt):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error
        return honest_action(self)


class ApiFailureTests(unittest.TestCase):
    def _hand(self, seats, deal=True, stats=None):
        engine = seats[0].engine
        ch, bus = Channels(), SignalBus()
        stats = stats or {"turns": 0, "fallbacks": 0, "events": []}
        run_hand_kernel(engine, procs_for(seats), ch, bus,
                        Kernel(rng=Random(7)), stats, deal=deal)
        return stats

    def test_llm_call_failure_falls_back_and_hand_completes(self):
        engine = MusEngine(rng=Random(7))
        engine.deal()
        seats = four_script_seats(engine)
        seats[1] = FlakySeat(1, TEAM_OF[1], engine, fail_times=2)
        stats = self._hand(seats, deal=False)
        self.assertEqual(engine.phase, Phase.DONE)          # play continued
        self.assertEqual(seats[1].api_errors, 2)
        self.assertGreaterEqual(stats["fallbacks"], 2)
        self.assertTrue(any("API FAILURE" in e for e in stats["events"]))
        self.assertFalse(any("API FAILURE -> default action" in e
                             for e in seats[1].prompts))    # no prompt leak

    def test_degraded_match_still_raises_when_fallbacks_dominate(self):
        engine = MusEngine(rng=Random(7))
        seats = [FlakySeat(s, TEAM_OF[s], engine, fail_times=10 ** 6)
                 for s in range(4)]
        stats = {"turns": 0, "fallbacks": 0, "events": []}
        with self.assertRaises(apifail.DegradedMatch):
            for _ in range(12):   # fresh deal per hand; guard trips by turn 10
                self._hand(seats, stats=stats)

    def test_fatal_api_error_still_aborts(self):
        engine = MusEngine(rng=Random(7))
        engine.deal()
        seats = [FlakySeat(s, TEAM_OF[s], engine, fail_times=1,
                           error=apifail.FatalAPIError("no key")) for s in range(4)]
        with self.assertRaises(apifail.FatalAPIError):
            self._hand(seats)


if __name__ == "__main__":
    unittest.main()
