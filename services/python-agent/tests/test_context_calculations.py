"""Identical wire views and fresh numeric scopes under context-build reuse."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from app.config import settings
from app.graph import main_agent
from app.graph.state_factory import create_initial_state
from app.utils.context_budget import request_tokens
from app.utils.context_calculations import ContextCalculations
from app.utils.token_utils import count_tokens


class CalculationTests(unittest.TestCase):
    def state(self):
        state = create_initial_state(7, '检查资料', [{'role': 'user', 'content': '仅当前任务'}])
        state['task_results'] = {'s': {'status': 'succeeded', 'kind': 'search', 'actor': 'main',
            'retrieval_target': 'knowledge', 'instruction': '日志', 'result': 'alpha ' * 12000,
            'citations': [{'id': 's:1', 'title': '日志'}], 'citation_contents': {'s:1': 'alpha ' * 12000}}}
        state['action_task_ids'] = ['s']
        return state

    def test_cache_preserves_messages_and_budget_and_does_not_mutate_results(self):
        state = self.state()
        original = deepcopy(state)
        outputs = []
        for enabled in (False, True):
            with patch.object(settings, 'CONTEXT_BUILD_CACHE_ENABLED', enabled):
                render = main_agent.main_message_renderer(state, {})
                messages = main_agent.build_main_messages(state, {}, render=render)
                cost = request_tokens(messages, [main_agent.MainDecision])
                outputs.append(([message.model_dump() for message in messages], cost))
                render(state['history_messages'])
                if enabled:
                    self.assertEqual(render.calculations.stats['result_hashes'], 1)
                    self.assertGreater(render.calculations.stats['token_cache_hits'], 0)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(state, original)

    def test_mutated_source_and_same_id_new_run_get_fresh_view(self):
        state = self.state()
        first = main_agent.build_main_messages(state, {})
        state['run_id'] = 'different'
        state['task_results']['s']['result'] = 'changed source'
        state['task_results']['s']['citations'][0]['title'] = 'changed title'
        second = main_agent.build_main_messages(state, {})
        a, b = (json.loads(messages[1].content)['successful_tasks']['s'] for messages in (first, second))
        self.assertNotEqual(a['source_version'], b['source_version'])
        self.assertEqual(b['result'], 'changed source')
        self.assertEqual(b['citations'][0]['title'], 'changed title')

    def test_changed_text_count_cannot_reuse_old_count_and_scope_is_bounded(self):
        calculations = ContextCalculations()
        with calculations.activate():
            self.assertNotEqual(count_tokens('a'), count_tokens('a ' * 200))
            for index in range(700):
                count_tokens(str(index))
        self.assertLessEqual(len(calculations.tokens), 512)
        fresh = ContextCalculations()
        with fresh.activate():
            count_tokens('a')
        self.assertEqual(fresh.stats['token_cache_hits'], 0)
