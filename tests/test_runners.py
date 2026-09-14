"""Offline regressions for runner entry points and API failure handling."""
import importlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from random import Random
import unittest
from unittest.mock import Mock, patch

import apifail
import run_benchmark_strict as strict
import run_llm_vs_baseline as baseline


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.breaker = patch.object(apifail, 'BREAKER', apifail.CircuitBreaker())
        self.breaker.start()
        self.addCleanup(self.breaker.stop)

    def test_permanent_unlisted_client_error_is_not_retried(self):
        call = Mock(return_value=Mock(status_code=405, text='method not allowed'))
        with self.assertRaises(apifail.FatalAPIError):
            apifail.call_with_retries(call)
        call.assert_called_once()

    def test_transient_exception_retries_and_requires_json_object(self):
        bad = Mock(status_code=200)
        bad.json.return_value = []
        good = Mock(status_code=200)
        good.json.return_value = {'ok': True}
        call = Mock(side_effect=[apifail.RetryableAPIError('busy'), bad, good])
        with patch.object(apifail.time, 'sleep'):
            self.assertEqual(apifail.call_with_retries(call, attempts=3), {'ok': True})
        self.assertEqual(call.call_count, 3)

    def test_deadline_caps_sleep_and_stops_retries(self):
        response = Mock(status_code=429, text='busy', headers={'Retry-After': '100'})
        call = Mock(return_value=response)
        with patch.object(apifail.time, 'monotonic', side_effect=[0, 0, 0, 0, 0, 1]), \
             patch.object(apifail.time, 'sleep') as sleep:
            with self.assertRaises(apifail.MatchTimeout):
                apifail.call_with_retries(call, deadline=1)
        sleep.assert_called_once_with(1)
        call.assert_called_once()

    def test_success_closes_breaker(self):
        breaker = apifail.CircuitBreaker()
        for _ in range(apifail.CB_THRESHOLD):
            breaker.record_failure('provider')
        breaker.record_success('provider')
        breaker.check('provider')


class RunnerTests(unittest.TestCase):
    def test_cli_reports_failure_in_saved_results_and_exit_status(self):
        for runner in (strict, baseline):
            with self.subTest(runner=runner.__name__), tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / 'results.json'
                argv = ['runner', '--models', 'random,random,random,random',
                        '--hands', '1', '--seeds', '0', '--out', str(output)]
                with patch('sys.argv', argv), patch.object(runner, '_write'), \
                     patch.object(runner, 'run_match_strict', side_effect=RuntimeError('broken')), \
                     patch('builtins.print'):
                    with self.assertRaises(SystemExit) as raised:
                        runner.main()
                self.assertEqual(raised.exception.code, 1)
                results = json.loads(output.read_text())['results']
                self.assertTrue(results)
                self.assertTrue(all(r['status'] == 'error' and 'broken' in r['msg'] for r in results))

    def test_diagnostic_imports_do_not_start_matches(self):
        with patch('run_match_strict.run_match_strict') as run:
            for module in ('single_test', 'error_hunt'):
                importlib.reload(importlib.import_module(module))
            run.assert_not_called()

    def test_runners_seed_engine_from_job(self):
        for runner in (strict, baseline):
            job = {'id': 0, 'models': ['random'] * 4, 'hands': 1,
                   'seed': 37, 'opponent': 'heuristic'}
            progress = {'completed': 0, 'log': []}
            with self.subTest(runner=runner.__name__), patch.object(runner, '_write'), \
                 patch.object(runner, 'run_match_strict', side_effect=RuntimeError('stop')) as match:
                runner.run_job(job, progress, threading.Lock())
            engine = match.call_args.args[0]
            self.assertEqual(engine.rng.getstate(), Random(37).getstate())

    def test_failed_job_preserves_error_and_elapsed(self):
        job = strict.generate_jobs(['random'] * 4, 1, [0])[0]
        progress = {'completed': 0}
        with patch.object(strict, '_write'), \
             patch.object(strict, 'run_match_strict', side_effect=RuntimeError('failure')):
            strict.run_job(job, progress, threading.Lock())
        self.assertEqual(job['status'], 'error')
        self.assertIn('failure', job['msg'])
        self.assertIsNotNone(job['elapsed'])
        self.assertEqual(progress['completed'], 0)

    def test_baseline_progress_updates_once_per_hand(self):
        job = {'id': 0, 'models': ['random', 'random'], 'opponent': 'heuristic',
               'hands': 2, 'seed': 0}
        progress = {'done_hands': 0, 'running_a': 0, 'running_b': 0,
                    'completed': 0, 'log': []}
        def match(engine, models, **kwargs):
            kwargs['hand_callback'](1, 1, 0, 0, 1, 0)
            kwargs['hand_callback'](2, 0, 1, 1, 1, 1)
            return {'vacas_a': 1, 'vacas_b': 1, 'hand_wins_a': 1, 'hand_wins_b': 1,
                    'usage': {'calls': 0}, 'agents': []}
        with patch.object(baseline, '_write'), patch.object(baseline, 'run_match_strict', match):
            baseline.run_job(job, progress, threading.Lock())
        self.assertEqual((progress['done_hands'], progress['running_a'], progress['running_b']), (2, 1, 1))
        self.assertEqual(job['status'], 'done')


if __name__ == '__main__':
    unittest.main()


class RateLimitTests(unittest.TestCase):
    """The 429 cascade that destroyed three qwen matches must not recur."""

    def test_rate_limit_does_not_open_the_breaker(self):
        apifail.BREAKER.record_success('p')
        response = Mock(status_code=429, text='max_parallel_requests',
                        headers={})
        call = Mock(return_value=response)
        with patch.object(apifail.time, 'sleep'):
            with self.assertRaises(apifail.LLMCallFailure):
                apifail.call_with_retries(call, 'p', attempts=6)
        # six 429s in a row, well past CB_THRESHOLD, and the circuit is still
        # closed -- the next decision gets a real attempt, not default noise
        apifail.BREAKER.check('p')

    def test_a_real_server_error_still_opens_the_breaker(self):
        apifail.BREAKER.record_success('q')
        response = Mock(status_code=503, text='down', headers={})
        call = Mock(return_value=response)
        with patch.object(apifail.time, 'sleep'):
            with self.assertRaises(apifail.LLMCallFailure):
                apifail.call_with_retries(call, 'q', attempts=6)
        with self.assertRaises(apifail.RetryableAPIError):
            apifail.BREAKER.check('q')

    def test_breaker_is_keyed_per_model(self):
        apifail.BREAKER.record_success('nan:a')
        for _ in range(apifail.CB_THRESHOLD):
            apifail.BREAKER.record_failure('nan:a')
        with self.assertRaises(apifail.RetryableAPIError):
            apifail.BREAKER.check('nan:a')
        apifail.BREAKER.check('nan:b')      # the other seat is unaffected


class InflightLimiterTests(unittest.TestCase):
    def test_limiter_caps_concurrent_slots(self):
        with tempfile.TemporaryDirectory() as d:
            lim = apifail.InflightLimiter(limit=2, path=d)
            a, b = lim.acquire(), lim.acquire()
            self.assertIsNotNone(a)
            self.assertIsNotNone(b)
            self.assertEqual(len(os.listdir(d)), 2)
            with self.assertRaises(apifail.MatchTimeout):
                lim.acquire(deadline=time.monotonic())   # full, already past
            lim.release(a)
            self.assertEqual(len(os.listdir(d)), 1)
            c = lim.acquire()
            self.assertIsNotNone(c)
            lim.release(b)
            lim.release(c)
            self.assertEqual(os.listdir(d), [])

    def test_zero_limit_is_a_no_op(self):
        lim = apifail.InflightLimiter(limit=0)
        self.assertIsNone(lim.acquire())
        lim.release(None)

    def test_stale_slots_from_a_killed_process_are_reclaimed(self):
        with tempfile.TemporaryDirectory() as d:
            lim = apifail.InflightLimiter(limit=1, path=d)
            dead = os.path.join(d, 'dead')
            open(dead, 'w').close()
            old = time.time() - apifail.InflightLimiter.STALE_AFTER - 1
            os.utime(dead, (old, old))
            slot = lim.acquire(deadline=time.monotonic() + 5)
            self.assertIsNotNone(slot)
            self.assertFalse(os.path.exists(dead))
