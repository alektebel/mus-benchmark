"""Offline end-to-end strict-harness probe; replaces only HTTP transport.

Run: python mock_match.py --out /tmp/mus-mock-results.json
The mock chooses from its prompt and own hand, never opponents' hands.
"""
import argparse
import json
from json import dumps
import re
from collections import Counter
from random import Random
from unittest.mock import patch

from deck import Card
from mus_engine import MusEngine, CARD_POINTS, RANK_MUS
import apifail
import run_match_strict as harness
import senas


class Response:
    def __init__(self, data=None, status=200):
        self.status_code = status
        self.headers = {}
        self.text = 'injected mock error' if status != 200 else ''
        self.data = data

    def json(self):
        return self.data


def choose_action(prompt):
    names = re.search(r'^YOUR HAND: (.+)$', prompt, re.M).group(1).split(', ')
    hand = [Card(*name.split(' de ')) for name in names]
    legal = re.search(r'^Legal action names: (.+)$', prompt, re.M).group(1).split(', ')
    counts = Counter(RANK_MUS[c.rank] for c in hand)
    total = sum(CARD_POINTS[c.rank] for c in hand)
    if 'no-tengo' in legal:
        has = max(counts.values()) >= 2 if 'DECLARATION ROUND for Pares' in prompt else total >= 31
        name = 'tengo' if has else 'no-tengo'
    elif 'no' in legal:
        name = 'no'
    elif 'discard' in legal:
        name = 'discard'
    elif 'paso' in legal:
        name = 'envido' if 'envido' in legal and total >= 31 else 'paso'
    else:
        name = 'quiero' if total >= 31 else 'no-quiero'
    action = {'action': name, 'read_signals': True, 'message': 'Vamos con calma.'}
    if name == 'discard':
        action['cards'] = [names[0]]
    # Pure hand predicates; this helper engine is never dealt any hidden cards.
    predicates = MusEngine(Random(0))
    available = [s for s in senas.SENAS if senas.sena_truthful(s, hand, predicates)]
    if available:
        action['signal'] = available[0]
    return action


def run_scenario(mode, hands=12, seed=7):
    requests = 0
    faults = Counter()
    observed = Counter()
    engine = MusEngine(Random(seed))
    channel_block = harness._channel_block

    def observe_channel(ch, agent, what):
        before = agent.budget.remaining
        text, cost = channel_block(ch, agent, what)
        if before == 0 and cost > 0:
            observed['channel_reads_at_zero_budget'] += 1
        if what == 'signals' and agent.want_signals and ch.signals:
            observed['signal_views'] += 1
        return text, cost

    def post(url, *, headers, json: dict, timeout):
        nonlocal requests
        requests += 1
        prompt = json['messages'][-1]['content']
        action = choose_action(prompt)
        content = dumps(action)
        finish = 'stop'
        usage = {'prompt_tokens': 100, 'completion_tokens': 20}
        if mode == 'recoverable' and requests % 17 == 1:
            faults['http_429'] += 1
            return Response(status=429)
        if mode == 'recoverable' and requests % 17 == 3:
            faults['malformed_json'] += 1
            content = '{broken'
        if mode == 'recoverable' and requests % 17 == 5:
            faults['illegal_action'] += 1
            content = '{"action":"invented-action"}'
        if mode == 'recoverable' and requests % 17 == 7:
            faults['truncated'] += 1
            finish = 'length'
            content = ''
        if mode == 'invalid_actions':
            content = '{"action":"invented-action"}'
        if mode == 'fatal_auth':
            return Response(status=401)
        if mode == 'null_usage':
            usage['prompt_tokens'] = None
        if mode == 'false_signals':
            predicates = MusEngine(Random(0))
            names = re.search(r'^YOUR HAND: (.+)$', prompt, re.M).group(1).split(', ')
            hand = [Card(*name.split(' de ')) for name in names]
            action['signal'] = next(s for s in senas.SENAS
                                    if not senas.sena_truthful(s, hand, predicates))
            action['message'] = 'Tengo rey y 39.'
            content = dumps(action)
            faults['false_signals'] += 1
        return Response({'choices': [{'message': {'content': content},
                                      'finish_reason': finish}], 'usage': usage})

    with patch.dict('os.environ', {'NAN_API_KEY': 'offline-mock-only'}), \
         patch.object(harness.requests, 'post', side_effect=post), \
         patch.object(apifail, 'BREAKER', apifail.CircuitBreaker()), \
         patch.object(apifail, '_sleep_backoff', return_value=0), \
         patch.object(harness, '_channel_block', side_effect=observe_channel):
        try:
            result = harness.run_match_strict(
                engine, ['mock-model'] * 4, hands=hands, seed=seed,
                vaca_callback=lambda *args: None)
        except Exception as error:
            result = {'status': 'error', 'error_type': type(error).__name__, 'error': str(error)}
    return {'scenario': mode, 'http_requests': requests,
            'injected': dict(faults), 'observed': dict(observed), 'result': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='/tmp/mus-mock-results.json')
    args = parser.parse_args()
    results = [run_scenario(mode) for mode in
               ('clean', 'recoverable', 'false_signals', 'invalid_actions', 'fatal_auth', 'null_usage')]
    with open(args.out, 'w') as output:
        json.dump(results, output, indent=2)
    for row in results:
        result = row['result']
        print(json.dumps({
            'scenario': row['scenario'], 'status': result['status'],
            'http_requests': row['http_requests'],
            'usage': result.get('usage'), 'injected': row['injected'],
            'observed': row['observed'],
            'invalid_signals': sum(a['invalid_signals'] for a in result.get('agents', [])),
            'rejections': sum(a['rejections'] for a in result.get('agents', [])),
            'redactions': sum(a['redactions'] for a in result.get('agents', [])),
            'error': result.get('error'),
        }))
    print(f'Full results: {args.out}')


if __name__ == '__main__':
    main()
