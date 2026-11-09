"""Prefetch grants no new access, and partial evidence stays partial downstream."""
from copy import deepcopy
from contextlib import ExitStack
import json
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.graph import main_agent
from app.graph.state_factory import create_initial_state
from app.services.result_access import answer_source_scope, scoped_source_text
from app.services.result_prefetch import prepare_prefetch, has_prefetch_hint
from app.services import context_tools
from test_context_management import evidence, tool_context


class PrefetchTests(unittest.IsolatedAsyncioTestCase):
    def state(self, message='从结果log_0提取“现场校验代号”，只回答代号。'):
        state = create_initial_state(7, message, [])
        body = 'ordinary ' * 14000 + '\n现场校验代号：PREFETCH-K8P2\n' + 'tail ' * 2000
        state['task_results'] = {'log_0': {**evidence(body), 'citations': [
            {'id': 'log_0:1', 'articleId': 17, 'sourceHash': 'fixture-hash', 'title': '平台日志'}],
            'citation_contents': {'log_0:1': body}}}
        return state

    async def prefetch(self, state, **config):
        with ExitStack() as stack:
            stack.enter_context(patch.object(settings, 'CONTEXT_RESULT_PREFETCH_ENABLED', True))
            stack.enter_context(patch('app.services.context_tools.verify_public_evidence', AsyncMock()))
            for name, value in config.items():
                stack.enter_context(patch.object(settings, name, value))
            return await prepare_prefetch(state, main_agent.build_main_messages(state, {}),
                [main_agent.MainDecision], fence=AsyncMock())

    async def test_explicit_source_loads_excerpt_and_keeps_original_unchanged(self):
        state = self.state()
        original = deepcopy(state)
        views, stats = await self.prefetch(state)
        self.assertEqual(stats['status'], 'hit')
        self.assertLessEqual(stats['added_tokens'], 4096)
        self.assertIn('PREFETCH-K8P2', views['log_0']['result'])
        self.assertEqual(state, original)
        messages = main_agent.build_main_messages({**state, '_result_prefetch': views}, {})
        sent = json.loads(messages[1].content)['successful_tasks']
        scope = answer_source_scope(sent, ['log_0'])
        self.assertFalse(scope['log_0:1'].get('full', False))
        self.assertNotIn('ordinary ' * 1000, scoped_source_text(state, scope['log_0:1']))

    async def test_ambiguous_no_locator_web_private_and_already_loaded_are_skipped(self):
        for message in ('继续', '找现场校验代号', '从log_0提取不存在的东西',
                        '不要读取log_0，也不要提取“现场校验代号”，只说收到。'):
            views, stats = await self.prefetch(self.state(message))
            self.assertEqual(views, {})
        for change in ({'private_context': True}, {'source_context': True}, {'tool_name': 'web_search'}, {'result': 'small source'}):
            state = self.state()
            state['task_results']['log_0'].update(change)
            views, _ = await self.prefetch(state)
            self.assertEqual(views, {})

    async def test_visible_read_already_covering_keyword_is_not_prefetched_again(self):
        state = self.state()
        views, _ = await self.prefetch(state)
        state['task_results']['already_read'] = {**views['log_0'], 'status': 'succeeded',
            'kind': 'tool', 'actor': 'main', 'tool_name': 'read_task_result'}
        repeated, stats = await self.prefetch(state)
        self.assertEqual(repeated, {})
        self.assertEqual(stats['reason'], 'no_explicit_unloaded_source')

    async def test_permission_failure_or_source_update_cannot_insert_text(self):
        state = self.state()
        with patch.object(settings, 'CONTEXT_RESULT_PREFETCH_ENABLED', True), \
                patch('app.services.context_tools.verify_public_evidence', AsyncMock(side_effect=ValueError('changed'))) as verify:
            views, stats = await prepare_prefetch(state, main_agent.build_main_messages(state, {}),
                [main_agent.MainDecision], fence=AsyncMock())
        verify.assert_awaited_once()
        self.assertEqual(views, {})
        self.assertEqual(stats['reason'], 'validation_or_lookup_failed')

    async def test_prefetch_does_not_displace_budget_or_run_again_in_later_round(self):
        state = self.state()
        self.assertTrue(has_prefetch_hint(state))
        state['action_task_ids'] = ['log_0']
        self.assertFalse(has_prefetch_hint(state))
        state['action_task_ids'] = []
        state['main_round'] = 1
        self.assertEqual((await self.prefetch(state))[0], {})
        state['main_round'] = 0
        views, stats = await self.prefetch(state, CONTEXT_COMPACT_TRIGGER_TOKENS=16000)
        self.assertEqual(views, {})
        self.assertEqual(stats['reason'], 'budget')

    async def test_main_authored_artifact_keeps_visible_source_scope(self):
        state = self.state()
        views, _ = await self.prefetch(state)
        artifact = main_agent.MainArtifact(task_id='note', instruction='整理已读取的代号',
            depends_on=['log_0'], result='代号为PREFETCH-K8P2[log_0:1]')
        output = main_agent.prepare_artifacts(state, [artifact], model_view=views)
        scope = answer_source_scope(output, ['note'])
        self.assertFalse(scope['log_0:1'].get('full', False))
        self.assertEqual(scope, output['note']['evidence_scope'])
        with patch.object(context_tools, 'verify_public_evidence', AsyncMock()):
            readback = await context_tools.read_task_result(tool_context('read_task_result',
                {'source_task_id': 'note'}, {**state['task_results'], **output}))
        inherited = answer_source_scope({'read_note': readback}, ['read_note'])
        self.assertEqual(inherited, scope)
        self.assertEqual(answer_source_scope({'left': readback, 'right': readback}, ['left', 'right']), scope)
        self.assertIn('PREFETCH-K8P2', scoped_source_text(state, inherited['log_0:1']))
        self.assertNotIn('ordinary ' * 1000, scoped_source_text(state, inherited['log_0:1']))
