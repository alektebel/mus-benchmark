import unittest
from random import Random
from unittest.mock import Mock, patch

from deck import Card
from groupchat import Channels, public_cost
from mus_engine import MusEngine, Phase
import run_match_strict as harness
import agents


class StrictHarnessTests(unittest.TestCase):
    def setUp(self):
        self.engine = MusEngine(Random(3))
        self.engine.deal()
        self.agent = harness.BaselineSeat('mock', 'heuristic', 0, 0)
        self.agent.is_llm = True
        self.channels = Channels()
        self.stats = {'turns': 0, 'fallbacks': 0, 'events': []}

    def test_string_signal_and_optional_stats(self):
        hand = [Card('rey', 'oros'), Card('tres', 'copas'),
                Card('cuatro', 'bastos'), Card('cinco', 'espadas')]
        harness._emit(self.agent, {'signal': 'muerde-el-labio-inferior',
                                 'message': 'Tengo rey y 39'},
                      self.channels, self.engine, hand=hand)
        self.assertEqual(len(self.channels.signals), 1)
        self.assertIsNone(self.channels.signals[0].to_seat)
        self.assertNotIn('39', self.channels.public[0].text)
        self.assertEqual(self.agent.redactions, 1)

    def test_signal_uses_hand_before_discard(self):
        for seat in range(4):
            self.engine.apply(seat, {'action': 'mus'})
        hand = [Card('rey', 'oros'), Card('tres', 'copas'),
                Card('cuatro', 'bastos'), Card('cinco', 'espadas')]
        self.engine.hands[0] = hand
        self.engine.draw_pile = [Card('seis', 'oros')]
        self.agent.decide = Mock(return_value={
            'action': 'discard', 'cards': ['rey de oros'],
            'signal': 'muerde-el-labio-inferior'})
        harness.play_turn(self.engine, self.agent, self.channels, self.stats)
        self.assertEqual(len(self.channels.signals), 1)

    def test_retry_charges_channels_once_and_counts_one_turn(self):
        self.channels.say_public(1, 'other', 'Hola')
        before = self.agent.budget.remaining
        self.agent.decide = Mock(side_effect=[{'action': 'invalid'}, {'action': 'no'}])
        harness.play_turn(self.engine, self.agent, self.channels, self.stats)
        self.assertEqual(self.stats['turns'], 1)
        self.assertEqual(self.stats['llm_turns'], 1)
        self.assertEqual(self.agent.rejections, 1)
        self.assertEqual(self.agent.budget.remaining, before - public_cost(1))

    def test_fallback_denominator_includes_successful_llm_turns(self):
        self.stats.update(turns=99, llm_turns=9)
        self.agent.decide = Mock(return_value={'action': 'invalid'})
        harness.play_turn(self.engine, self.agent, self.channels, self.stats)
        self.assertEqual(self.stats['fallbacks'], 1)
        self.assertEqual(self.stats['llm_turns'], 10)

    def test_baseline_turns_cannot_dilute_fallback_rate(self):
        self.stats.update(turns=1000, llm_turns=9, fallbacks=1)
        self.agent.decide = Mock(return_value={'action': 'invalid'})
        with self.assertRaises(harness.DegradedMatch):
            harness.play_turn(self.engine, self.agent, self.channels, self.stats)

    def test_reset_preserves_match_counters(self):
        self.agent.invalid_signals = 3
        self.agent.signals_read = 2
        harness.reset_hand_channels([self.agent], self.channels)
        self.assertEqual(self.agent.invalid_signals, 3)
        self.assertEqual(self.agent.signals_read, 0)

    def test_deadline_checked_inside_hand(self):
        agents = [harness.BaselineSeat(str(s), 'heuristic', s, s % 2)
                  for s in range(4)]
        with self.assertRaises(harness.MatchTimeout):
            harness.run_hand(self.engine, agents, self.channels, self.stats, deadline=0)

    def test_provider_cli_spec(self):
        with patch.object(agents, 'StrictAgent') as agent:
            harness._make_agent('nvidia:example/model', 0, 0)
        agent.assert_called_once_with('A0', 'example/model', 0, 0, 'nvidia')

    def test_reproducible_baseline_match_and_turn_counts(self):
        models = ['heuristic', 'random', 'heuristic', 'random']
        def run():
            return harness.run_match_strict(MusEngine(Random(12)), models,
                                            hands=20, seed=12,
                                            vaca_callback=lambda *args: None)
        a, b = run(), run()
        for key in ('vacas_a', 'vacas_b', 'hand_wins_a', 'hand_wins_b', 'usage'):
            self.assertEqual(a[key], b[key])
        self.assertGreater(a['usage']['turns'], 20)
        self.assertEqual(a['usage']['llm_turns'], 0)

    def test_declaration_fallback_is_truthful(self):
        self.engine.phase = Phase.DECLARE
        self.engine.lance_index = 2
        self.engine.hands[0] = [Card(rank, 'oros') for rank in
                                ('as', 'cuatro', 'cinco', 'seis')]
        action = harness._default_legal(self.engine, 0)
        self.assertEqual(action, {'action': 'no-tengo'})
        self.engine.apply(0, action)

    def test_mock_transport_retries_bad_response_and_returns_action(self):
        with patch.dict('os.environ', {'NAN_API_KEY': 'offline-test'}):
            agent = harness.StrictAgent('mock', 'mock-model', 0, 0)
        response = {'choices': [{'message': {'content': '{"action":"no"}'},
                                 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 12, 'completion_tokens': 5}}
        with patch.object(harness.apifail, 'call_with_retries',
                          side_effect=[{'choices': []}, response]) as call:
            self.assertEqual(agent.decide('offline'), {'action': 'no'})
        self.assertEqual(call.call_count, 2)
        self.assertEqual(agent.tokens_in, 12)

    def test_null_token_counts_do_not_discard_valid_action(self):
        with patch.dict('os.environ', {'NAN_API_KEY': 'offline-test'}):
            agent = harness.StrictAgent('mock', 'mock-model', 0, 0)
        response = {'choices': [{'message': {'content': '{"action":"no"}'},
                                 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': None, 'completion_tokens': None,
                              'completion_tokens_details': {'reasoning_tokens': None}}}
        with patch.object(harness.apifail, 'call_with_retries', return_value=response):
            self.assertEqual(agent.decide('offline'), {'action': 'no'})
        self.assertEqual((agent.tokens_in, agent.tokens_out, agent.reasoning), (0, 0, 0))

    def test_bad_match_configuration(self):
        with self.assertRaises(ValueError):
            harness.run_match_strict(self.engine, ['random'])
        with self.assertRaises(ValueError):
            harness.run_match_strict(self.engine, ['random'] * 4, hands=0)


if __name__ == '__main__':
    unittest.main()
