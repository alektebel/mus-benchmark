import unittest
from unittest.mock import patch
from random import Random

from baseline import RandomAgent, _parse_legal
from channels import AttentionAccount, SignalBus
from deck import Card
from engine import MusEngine
from groupchat import Channels, PerceptionBudget
from run_match import run_match, _apply_observe, _emit_signal, _match_name, build_prompt
from run_match_gc import GCAgent, _emit_turn


class LegacyTests(unittest.TestCase):
    def test_legal_names_exclude_sentence_punctuation(self):
        self.assertEqual(_parse_legal('Legal action names: mus, no.'), ['mus', 'no'])

    def test_seed_reproduces_threaded_random_baseline(self):
        first = run_match(MusEngine(Random(99)), ('a', 'b'), 'c', hands=20,
                          seed=42, make_agent=RandomAgent)
        second = run_match(MusEngine(Random(7)), ('a', 'b'), 'c', hands=20,
                           seed=42, make_agent=RandomAgent)
        self.assertEqual(first, second)

    def test_signal_observation_excludes_own_and_opponents_text(self):
        bus = SignalBus()
        agents = [RandomAgent(str(s), seat=s, team=s % 2) for s in range(4)]
        for agent in agents:
            _emit_signal(agent, {'signal': f'secret {agent.seat}'}, bus)
        account = AttentionAccount()
        decoded = []
        _apply_observe(agents[0], {'observe': 'partner'}, bus, account, decoded)
        self.assertEqual(decoded, ['secret 2'])
        _apply_observe(agents[0], {'observe': 'opp'}, bus, account, decoded)
        prompt = build_prompt(agents[0], MusEngine().deal(), bus, account,
                              'MUS_REQUEST', 0, '', ['mus', 'no'], decoded)
        self.assertIn('Observed opponent signals: 2', prompt)
        self.assertNotIn('secret 1', prompt)
        self.assertEqual(account.credits, 7)

    def test_invalid_observation_and_listen_types_do_not_crash(self):
        agent = GCAgent('a', 'mock', 0, 0)
        _emit_turn(agent, {'listen': ['both'], 'signal': {'to': True, 'text': 'bad'}}, Channels())
        self.assertEqual(agent.listen, 'both')
        account = AttentionAccount()
        _apply_observe(agent, {'observe': {'partner': True}}, SignalBus(), account, [])
        self.assertEqual(account.credits, 10)

    def test_card_matching_requires_full_name(self):
        card = Card('as', 'oros')
        self.assertFalse(_match_name(card, ['']))
        self.assertFalse(_match_name(card, ['as']))
        self.assertTrue(_match_name(card, ['as de oros']))

    def test_custom_budget_reset_preserves_budget_and_credit_behavior(self):
        budget = PerceptionBudget(10)
        self.assertTrue(budget.spend(20))
        self.assertEqual(budget.remaining, 0)
        budget.reset()
        self.assertEqual(budget.remaining, 10)
        with self.assertRaises(ValueError):
            budget.spend(-1)

    def test_gc_agent_rejects_non_object_json(self):
        agent = GCAgent('a', 'mock', 0, 0)
        with patch('run_match_gc.requests.post') as post, patch('run_match_gc.time.sleep'):
            post.return_value.json.return_value = {'choices': [{'message': {'content': '[]'}}]}
            self.assertEqual(agent.decide('prompt'), {})
            self.assertEqual(post.call_count, 3)

    def test_redraw_rejects_invalid_discard_without_mutating_hand(self):
        engine = MusEngine(Random(0))
        hands = engine.deal()
        before = list(hands[0])
        with self.assertRaises(ValueError):
            engine.redraw(0, hands, [hands[0][0], hands[0][0]])
        self.assertEqual(hands[0], before)
        with self.assertRaises(ValueError):
            engine.redraw(0, hands, [hands[0][0], hands[1][0]])
        self.assertEqual(hands[0], before)

    def test_invalid_match_size_is_rejected_before_agents(self):
        with self.assertRaises(ValueError):
            run_match(MusEngine(), ('a', 'b'), 'c', hands=0)


if __name__ == '__main__':
    unittest.main()
