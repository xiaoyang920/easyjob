"""Regression coverage for tool-only auditing, continuation and RPC ID limits."""
import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['AGENT_SERVICE_KEY'] = 'offline-service-key-32-bytes-long!!'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'

import json
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.graph import main_agent as main
from app.graph.state_factory import create_initial_state
from app.models.main_tool import tool_call_adapter
from app.services import agent_events, grounding
from app.services.run_history import RunHistory, progress_snapshot
from app.services.tool_registry import tool_registry

PUBLIC_TOOLS = ('get_article_comments', 'get_user_articles', 'get_trending_topics')
RID = '11111111-1111-4111-8111-111111111111'


def tool_result(name='get_article_comments', **extra):
    return {'task_id': 'read', 'kind': 'tool', 'actor': 'main', 'status': 'succeeded',
            'tool_name': name, 'retrieval_target': None, 'result': '读者：希望补充示例。',
            'citations': [], 'article_cards': [], **extra}


class ToolOnlyAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_repair_is_reviewed_again_and_known_error_cannot_be_delivered(self):
        wrong = '所有评论都表示没有任何问题。'
        issue = {'block_index': 0, 'unit_index': 0, 'kind': 'execution_fact',
                 'verdict': 'contradicted', 'reason': '与实际评论返回不符'}
        for name in PUBLIC_TOOLS:
            for fixed_ok in (False, True):
                with self.subTest(tool=name, fixed_ok=fixed_ok):
                    state = create_initial_state(7, '总结返回的公开资料', [])
                    state['task_results'] = {'read': tool_result(name)}
                    rejected = grounding.ReviewIssues([issue], {0: ''})
                    fixed = '读者希望补充示例。' if fixed_ok else wrong
                    second = grounding.ReviewIssues([], {0: fixed}) if fixed_ok else rejected
                    auditor = AsyncMock(side_effect=[rejected, second])
                    with patch.object(grounding, 'review_text', auditor), \
                         patch.object(grounding, 'repair_text', AsyncMock(return_value=fixed)), \
                         patch.object(agent_events, 'activity', AsyncMock()):
                        text, audit = await grounding.verify_delivery(state, wrong, [])
                    self.assertEqual(auditor.await_count, 2)
                    self.assertEqual(audit['review_calls'], 2)
                    self.assertEqual(audit['status'], 'repaired' if fixed_ok else 'unverified')
                    self.assertNotIn(wrong, text)
                    if fixed_ok:
                        self.assertEqual(text, fixed)
                    self.assertEqual(auditor.await_args.args[2]['public_tool_results'][0]['tool'], name)


class PublicToolContinuationTests(unittest.IsolatedAsyncioTestCase):
    def history(self, snapshot, updated_at):
        previous = {'run_id': RID, 'status': 'failed', 'draft_article_id': None,
                    'created_at': updated_at, 'updated_at': updated_at, 'result_json': json.dumps({'progress': snapshot})}
        db = SimpleNamespace(fetch_one=AsyncMock(return_value=SimpleNamespace(_mapping=previous)),
                             fetch_all=AsyncMock(side_effect=[[], []]))
        return RunHistory(db, AsyncMock())

    async def test_recent_public_queries_survive_projection_and_explicit_main_import(self):
        results = {f'read_{i}': tool_result(name, task_id=f'read_{i}') for i, name in enumerate(PUBLIC_TOOLS)}
        snapshot = progress_snapshot({'task_results': results}, 'main_agent', 'failed')
        self.assertEqual(set(snapshot['results']), set(results))
        _, reusable = await self.history(snapshot, datetime.now(timezone.utc)).previous(11, 7, 'current')
        self.assertEqual(len(reusable), 3)
        state = create_initial_state(7, '继续总结刚才的返回', [])
        state['previous_run'] = {'reusable_results': reusable}
        imported = main.previous_results_to_import(state, list(reusable))
        self.assertEqual({r['tool_name'] for r in imported.values()}, set(PUBLIC_TOOLS))
        self.assertTrue(all(r['previous_run_id'] == RID for r in imported.values()))

    async def test_old_tool_data_is_not_reused_as_current_public_data(self):
        for name in PUBLIC_TOOLS:
            with self.subTest(tool=name):
                snapshot = progress_snapshot({'task_results': {'read': tool_result(name)}}, 'main_agent', 'failed')
                updated = datetime.now(timezone.utc) - timedelta(days=2)
                summary, reusable = await self.history(snapshot, updated).previous(11, 7, 'current')
                self.assertEqual(reusable, {})
                self.assertIn('read', summary['unavailable_tasks'])

    def test_private_failed_unknown_and_side_effect_results_are_still_excluded(self):
        bad = [tool_result(status='tool_error'), tool_result('read_draft'),
               tool_result('mcp_unknown'), tool_result(retrieval_target='editor'),
               tool_result(draft_document={'private': 'draft'}), tool_result(memory_sources=['private']),
               tool_result(draft_article_id=42)]
        snapshot = progress_snapshot({'task_results': {str(i): r for i, r in enumerate(bad)}}, 'main_agent', 'failed')
        self.assertEqual(snapshot['results'], {})

    async def test_repeated_continuation_keeps_original_tool_snapshot_age(self):
        old = tool_result(previous_run_id=RID, source_run_updated_at='2000-01-01T00:00:00Z')
        snapshot = progress_snapshot({'task_results': {'read': old}}, 'main_agent', 'failed')
        summary, reusable = await self.history(snapshot, datetime.now(timezone.utc)).previous(11, 7, 'current')
        self.assertEqual(reusable, {})
        self.assertIn('read', summary['unavailable_tasks'])


class ToolIdBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def test_all_main_blog_ids_accept_int64_max_and_reject_overflow_before_io(self):
        for name, field in [('get_article_comments', 'article_id'), ('get_user_articles', 'user_id'),
                            ('read_draft', 'article_id'), ('search_knowledge', 'article_ids')]:
            for value, accepted in [(2**63 - 1, True), (2**63, False)]:
                args = {field: [value] if field == 'article_ids' else value}
                if name == 'search_knowledge':
                    args['query'] = '读取指定文章'
                with self.subTest(tool=name, value=value):
                    payload = {'name': name, 'args': args}
                    if accepted:
                        call = tool_call_adapter.validate_python(payload)
                        main.compile_action_plan(main.MainDecision(action='call_tool', tool_call=call), 1)
                    else:
                        with self.assertRaises(ValueError):
                            tool_call_adapter.validate_python(payload)

    async def test_overflow_enters_main_format_repair_before_dispatch(self):
        bad = {'action': 'call_tool', 'tool_call': {'name': 'get_article_comments',
                                                   'args': {'article_id': 2**63}}}
        good = main.MainDecision(action='call_tool', tool_call={'name': 'get_article_comments',
                                                               'args': {'article_id': 42}})
        controller = SimpleNamespace(ainvoke=AsyncMock(side_effect=[bad, good]))
        model = SimpleNamespace(with_structured_output=Mock(return_value=controller))
        with patch.object(main, 'get_llm', return_value=model), \
             patch.object(main, 'publish_route', AsyncMock()), \
             patch.object(tool_registry, 'get_local_tool') as resolve:
            output = await main.decide_main_action(create_initial_state(7, '读取评论', []), visual={})
        self.assertEqual(controller.ainvoke.await_count, 2)
        self.assertEqual(output['main_action'], 'call_tool')
        self.assertEqual(output['decision_contract_audit']['last_outcome'], 'repaired')
        self.assertIn('article_id', controller.ainvoke.await_args.args[0][-1].content)
        resolve.assert_not_called()
