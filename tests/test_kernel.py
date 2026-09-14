import time
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


class InterceptionTests(unittest.TestCase):
    """Rivals watch the table: with probability p they catch the gesture."""

    def test_prob_one_intercepts_both_opponents(self):
        bus = SignalBus(rng=Random(1), intercept_prob=1.0)
        ev = bus.publish(0, 2, "guinar-el-ojo", 0.1, 5.0)
        self.assertEqual(ev.intercepted_by, frozenset({1, 3}))
        # rivals get it in their pending queue, tagged as seen-by-intercept
        pend = bus.pending_for(1, 1.0)
        self.assertEqual([e.seq for e in pend], [ev.seq])
        bus.deliver(pend, 1.0, seat=1)
        # interception must NOT look like partner delivery
        self.assertIsNone(ev.delivered_at)
        self.assertIn(1, ev.seen_by)
        # partner delivery still works independently
        pend2 = bus.pending_for(2, 1.0)
        self.assertEqual([e.seq for e in pend2], [ev.seq])
        bus.deliver(pend2, 2.0, seat=2)
        self.assertEqual(ev.delivered_at, 2.0)
        # and the interceptor does not receive it twice
        self.assertEqual(bus.pending_for(1, 3.0), [])

    def test_prob_zero_never_intercepts(self):
        bus = SignalBus(rng=Random(1), intercept_prob=0.0)
        bus.publish(0, 2, "guinar-el-ojo", 0.1, 5.0)
        for rival in (1, 3):
            self.assertEqual(bus.pending_for(rival, 1.0), [])

    def test_interception_is_probabilistic_and_seeded(self):
        a = SignalBus(rng=Random(7), intercept_prob=0.5)
        b = SignalBus(rng=Random(7), intercept_prob=0.5)
        c = SignalBus(rng=Random(8), intercept_prob=0.5)
        for _ in range(40):
            a.publish(0, 2, "guinar-el-ojo", 0.1, 5.0)
            b.publish(0, 2, "guinar-el-ojo", 0.1, 5.0)
            c.publish(0, 2, "guinar-el-ojo", 0.1, 5.0)
        got_a = [ev.intercepted_by for ev in a.events]
        self.assertEqual(got_a, [ev.intercepted_by for ev in b.events])
        self.assertNotEqual(got_a, [ev.intercepted_by for ev in c.events])
        # at p=0.5 some events escape interception entirely
        self.assertIn(frozenset(), got_a)
        self.assertIn(len({frozenset({1}), frozenset({3}),
                           frozenset({1, 3})} & set(got_a)), (1, 2, 3))

    def test_interception_does_not_expire_partner_delivery(self):
        # a gesture intercepted by a rival but never caught by the partner
        # still counts as missed for the sender, and expires on schedule
        bus = SignalBus(rng=Random(1), intercept_prob=1.0)
        ev = bus.publish(0, 2, "guinar-el-ojo", 0.1, 0.3)
        self.assertEqual(bus.pending_for(1, 0.2), [ev])
        bus.deliver(bus.pending_for(1, 0.2), 0.2, seat=1)
        self.assertTrue(ev.expired or bus.pending_for(2, 0.5) == [])
        bus._mark_expired(0.5)
        self.assertTrue(ev.expired)
        # the partner missed it (addressee-side tally); the sender's tally
        # records that it was intercepted all the same
        self.assertEqual(bus.counts_for(2)["expired_unseen"], 1)
        self.assertEqual(bus.counts_for(0)["intercepted"], 1)

    def test_default_bus_is_interception_free(self):
        bus = SignalBus()
        bus.publish(0, 2, "guinar-el-ojo", 0.1, 5.0)
        self.assertEqual(bus.pending_for(1, 1.0), [])
        self.assertEqual(bus.counts_for(0)["intercepted"], 0)


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

    def test_rivals_intercept_senas_with_probability(self):
        engine = MusEngine(rng=Random(7))
        engine.deal()
        engine.hands[0] = list(TWO_KINGS)     # guarantees the 2-reyes sena
        ch = Channels()
        bus = SignalBus(rng=Random(7), intercept_prob=1.0)
        kernel = Kernel(rng=Random(7))
        stats = {"turns": 0, "fallbacks": 0, "events": []}
        seats = four_script_seats(engine)
        procs = procs_for(seats)
        procs[0].manager = SignalManager(seat=0, policy=reference_policy())
        run_hand_kernel(engine, procs, ch, bus, kernel, stats, deal=False)
        self.assertGreater(procs[0].manager.published, 0)
        # both rivals intercepted the gesture and their prompts say so
        self.assertGreater(procs[1].intercepted, 0)
        self.assertGreater(procs[3].intercepted, 0)
        self.assertTrue(any("seat 0 sena:" in p and "INTERCEPTED" in p
                            for p in seats[1].prompts))
        self.assertTrue(any("seat 0 sena:" in p and "INTERCEPTED" in p
                            for p in seats[3].prompts))
        # the partner's version of the same gesture is NOT marked intercepted
        self.assertTrue(any("seat 0 sena:" in p
                            and "INTERCEPTED from a rival" not in p
                            for p in seats[2].prompts))
        # the run report surfaces the interception count
        self.assertEqual(len(vk._serialize_events(bus, 1)),
                         len(bus.events))
        self.assertTrue(all("intercepted_by" in ev
                            for ev in vk._serialize_events(bus, 1)))
        # the sender's own tally distinguishes caught vs intercepted
        counts = bus.counts_for(0)
        self.assertEqual(counts["intercepted"], counts["sent"])

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


def tolerate_fallbacks():
    """These tests are about the retry path, not the degrade guard."""
    return patch.object(vk, "MAX_FALLBACK_RATE", 1.0)


def no_sleep():
    """Silence the decision-level backoff. These tests simulate a provider
    that is down, and the production path deliberately WAITS it out rather
    than poisoning the match with default actions -- correct in a 5-hour run,
    useless in a unit test."""
    return patch.object(vk.time, "sleep")


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

    def test_a_transient_provider_failure_is_ridden_out_not_fallen_back(self):
        """The point of the decision-level retry: a fallback is a poisoned
        data point that counts toward DegradedMatch, so a blip must be waited
        out rather than answered with a default action."""
        engine = MusEngine(rng=Random(7))
        engine.deal()
        seats = four_script_seats(engine)
        seats[1] = FlakySeat(1, TEAM_OF[1], engine, fail_times=2)
        with no_sleep() as slept:
            stats = self._hand(seats, deal=False)
        self.assertEqual(engine.phase, Phase.DONE)
        self.assertEqual(seats[1].api_errors, 2)     # both failures recorded
        self.assertEqual(stats["fallbacks"], 0)      # but none became a default
        self.assertEqual(slept.call_count, 2)        # it waited, twice
        self.assertTrue(any("API FAILURE" in e for e in stats["events"]))
        self.assertTrue(any("waiting" in e for e in stats["events"]))
        self.assertFalse(any("API FAILURE" in p for p in seats[1].prompts))

    def test_the_waits_grow_exponentially(self):
        engine = MusEngine(rng=Random(7))
        engine.deal()
        seats = four_script_seats(engine)
        seats[1] = FlakySeat(1, TEAM_OF[1], engine, fail_times=3)
        with no_sleep() as slept:
            self._hand(seats, deal=False)
        waits = [c.args[0] for c in slept.call_args_list]
        self.assertEqual(len(waits), 3)
        for earlier, later in zip(waits, waits[1:]):
            self.assertGreater(later, earlier)

    def test_a_persistent_outage_still_falls_back_eventually(self):
        engine = MusEngine(rng=Random(7))
        engine.deal()
        seats = four_script_seats(engine)
        seats[1] = FlakySeat(1, TEAM_OF[1], engine, fail_times=10 ** 6)
        with tolerate_fallbacks(), no_sleep() as slept:
            stats = self._hand(seats, deal=False)
        self.assertEqual(engine.phase, Phase.DONE)        # play continued
        self.assertGreaterEqual(stats["fallbacks"], 1)
        # one full ride-out attempted per decision, then the default
        self.assertEqual(slept.call_count,
                         vk.DECISION_RETRIES * stats["fallbacks"])

    def test_the_wait_never_outlives_the_match_deadline(self):
        engine = MusEngine(rng=Random(7))
        engine.deal()
        seats = four_script_seats(engine)
        seats[1] = FlakySeat(1, TEAM_OF[1], engine, fail_times=10 ** 6)
        seats[1].deadline = time.monotonic() - 1          # already past
        with tolerate_fallbacks(), no_sleep() as slept:
            self._hand(seats, deal=False)
        self.assertEqual(slept.call_count, 0)             # no pointless waiting

    def test_degraded_match_still_raises_when_fallbacks_dominate(self):
        engine = MusEngine(rng=Random(7))
        seats = [FlakySeat(s, TEAM_OF[s], engine, fail_times=10 ** 6)
                 for s in range(4)]
        stats = {"turns": 0, "fallbacks": 0, "events": []}
        with no_sleep(), self.assertRaises(apifail.DegradedMatch):
            for _ in range(12):   # fresh deal per hand; guard trips by turn 10
                self._hand(seats, stats=stats)

    def test_fatal_api_error_is_never_retried(self):
        """A bad payload or a missing key will fail identically forever;
        waiting on it just burns the match clock."""
        engine = MusEngine(rng=Random(7))
        engine.deal()
        seats = [FlakySeat(s, TEAM_OF[s], engine, fail_times=1,
                           error=apifail.FatalAPIError("no key")) for s in range(4)]
        with no_sleep() as slept, self.assertRaises(apifail.FatalAPIError):
            self._hand(seats)
        self.assertEqual(slept.call_count, 0)


if __name__ == "__main__":
    unittest.main()
