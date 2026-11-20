"""Current documents and canonical read aliases must not force repeated reads."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.config import settings
from app.graph import main_agent
from app.graph.state_factory import create_initial_state
from app.models.evidence_assessment import EvidenceAssessment
from app.services import context_tools
from app.services.context_projection import project_results
from app.services.result_access import answer_source_scope, scoped_source_text
from test_context_management import evidence, tool_context


class CurrentDocumentTests(unittest.TestCase):
    def test_current_document_fits_inline_without_reloading_old_results(self):
        state = create_initial_state(7, '解释选中的句子', [])
        state['task_results'] = {
            'old': evidence('OLD_RESULT ' * 4000),
            'article_context': {**evidence('CURRENT_ARTICLE ' * 1200), 'source_context': True},
        }
        original = deepcopy(state)
        with patch.object(settings, 'CONTEXT_RESULT_ACCESS_ENABLED', True), \
                patch.object(settings, 'CONTEXT_TOOL_ADAPTIVE_INLINE', True), \
                patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1024):
            sent = json.loads(main_agent.build_main_messages(state, {})[1].content)['successful_tasks']
        self.assertEqual(sent['article_context']['result'], state['task_results']['article_context']['result'])
        self.assertEqual(sent['old']['content_scope'], 'index_only')
        self.assertEqual(state, original)

    def test_current_document_still_respects_total_admission_and_keeps_history(self):
        history = [{'role': 'user', 'content': 'preserved history ' * 200}]
        state = create_initial_state(7, '解释文章', history)
        state['task_results'] = {'article_context': {**evidence('body ' * 9000), 'source_context': True}}
        with patch.object(settings, 'CONTEXT_RESULT_ACCESS_ENABLED', True), \
                patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1024), \
                patch.object(settings, 'CONTEXT_TOOL_ADAPTIVE_INLINE', False):
            base = main_agent.build_main_messages(state, {})
        from app.utils.context_budget import request_tokens
        ceiling = request_tokens(base, [main_agent.MainDecision]) + 2048
        with patch.object(settings, 'CONTEXT_RESULT_ACCESS_ENABLED', True), \
                patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1024), \
                patch.object(settings, 'CONTEXT_TOOL_ADAPTIVE_INLINE', True), \
                patch.object(settings, 'CONTEXT_COMPACT_TRIGGER_TOKENS', ceiling):
            messages = main_agent.build_main_messages(state, {})
        sent = json.loads(messages[1].content)
        self.assertEqual(sent['successful_tasks']['article_context']['content_scope'], 'index_only')
        self.assertEqual(sent['history'], json.loads(base[1].content)['history'])


class LoadedAliasTests(unittest.IsolatedAsyncioTestCase):
    async def view(self):
        body = '已读取的原文说明。' * 100 + 'UNREAD_PRIVATE_TAIL' * 1800
        source = {**evidence(body), 'instruction': '读取文章',
                  'citations': [{'id': 'source:1'}], 'citation_contents': {'source:1': body}}
        with patch.object(context_tools, 'verify_public_evidence', AsyncMock()):
            read = await context_tools.read_task_result(tool_context('read_task_result',
                {'source_task_id': 'source', 'max_chars': 500}, {'source': source}))
        results = {'source': source, 'read': {**read, 'kind': 'tool', 'actor': 'main',
                   'tool_name': 'read_task_result', 'instruction': '读取相关段落'}}
        return results, project_results(results, selective=True)

    def decision(self):
        return main_agent.MainDecision(action='answer', reply='根据已读取的段落解释。[source:1]',
            answer_dependencies=['source'], evidence_assessment=EvidenceAssessment(
                selected_ids=['source:1'], adequacy='sufficient', reason='已读取相关段落'))

    async def test_canonical_source_binds_to_loaded_read_with_bounded_evidence(self):
        results, view = await self.view()
        self.assertEqual(view['source']['content_scope'], 'index_only')
        decision = self.decision()
        main_agent.validate_loaded_context(decision, view)
        self.assertEqual(decision.answer_dependencies, ['read'])
        scope = answer_source_scope(view, decision.answer_dependencies)
        self.assertFalse(scope['source:1'].get('full'))
        self.assertEqual(scoped_source_text({'task_results': results}, scope['source:1']),
                         results['source']['result'][:500])
        self.assertNotIn('UNREAD_PRIVATE_TAIL', scoped_source_text({'task_results': results}, scope['source:1']))

    async def test_hidden_stale_or_empty_reads_cannot_authorize_source(self):
        _, original = await self.view()
        for change in ({'content_scope': 'index_only'}, {'content_scope': 'shared_result'},
                       {'result': ''}, {'result_reads': []}, {'result_reads': [{
                           **original['read']['result_reads'][0], 'source_version': 'stale'}]}):
            view = deepcopy(original)
            view['read'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                main_agent.validate_loaded_context(self.decision(), view)

    async def test_loaded_alias_does_not_authorize_citation_from_another_dependency(self):
        _, view = await self.view()
        view['other'] = {**evidence('another visible text'), 'citations': [{'id': 'other:1'}]}
        decision = self.decision()
        decision.evidence_assessment.selected_ids = ['other:1']
        with self.assertRaises(ValueError):
            main_agent.validate_loaded_context(decision, view)

    async def test_answer_after_read_requires_one_model_call_and_no_new_tool(self):
        results, _ = await self.view()
        state = create_initial_state(7, '解释文章中的这句话', [])
        state.update(task_results=results, main_round=1, action_task_ids=['read'])
        control = SimpleNamespace(ainvoke=AsyncMock(return_value=self.decision()))
        model = SimpleNamespace(with_structured_output=Mock(return_value=control))
        with patch.object(main_agent, 'get_llm', return_value=model), \
                patch.object(main_agent, 'assert_run', AsyncMock()), \
                patch.object(main_agent, 'activity', AsyncMock()), \
                patch.object(main_agent, 'publish_route', AsyncMock()), \
                patch.object(settings, 'CONTEXT_RESULT_ACCESS_ENABLED', True):
            update = await main_agent.decide_main_action(state, {})
        self.assertEqual(update['main_action'], 'answer')
        self.assertEqual(update['main_decision']['answer_dependencies'], ['read'])
        self.assertEqual(control.ainvoke.await_count, 1)
        self.assertFalse(update['answer_source_scope']['source:1'].get('full'))
        self.assertNotIn('decision_contract_audit', update)


if __name__ == '__main__':
    unittest.main()
