"""Context quality/ownership regressions; all providers and storage are fake."""
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.graph.state_factory import create_initial_state
from app.graph import main_agent, action_runtime
from app.graph.staged_plan import ExecutionTask
from app.models.main_tool import tool_call_adapter, task_fields
from app.models.task_context import TaskContextPatch, update_task_context
from app.services.context_projection import project_results, context_breakdown
from app.services import context_tools, main_context
from app.services.conversation import ConversationService
from app.services.run_history import RunHistory, progress_snapshot
from app.security.capabilities import task_capabilities
from app.utils.context_budget import ContextBudgetExceeded, request_tokens
from app.utils.token_utils import count_tokens
from test_context_budget import FakeStore


def evidence(text='x ' * 2000, target='knowledge'):
    return {'status': 'succeeded', 'kind': 'search', 'actor': 'main', 'retrieval_target': target,
            'result': text, 'citations': [], 'article_cards': []}


def tool_context(name, args, results=None):
    call = tool_call_adapter.validate_python({'name': name, 'args': args})
    task = ExecutionTask(task_id='lookup', actor='main', **task_fields(call))
    return {'user_id': 7, 'conversation_id': 11, 'current_task': task.model_dump(),
            'execution_mode': 'direct', 'capabilities': sorted(task_capabilities(task)),
            'readable_task_results': results or {}}


class ContextViewTests(unittest.TestCase):
    def test_adaptive_inline_uses_spare_window_and_preserves_raw_checkpoint(self):
        state = create_initial_state(7, '读回最早的工具结果', [])
        state['task_results'] = {'old': evidence('alpha ' * 2000), 'new': evidence('beta ' * 1200)}
        state['action_task_ids'] = ['old']
        original = deepcopy(state)
        with patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1800):
            self.assertEqual(json.loads(main_agent.decision_context(state))['successful_tasks']['old']['content_scope'], 'index_only')
            messages = main_agent.build_main_messages(state, {})
        visible = json.loads(messages[1].content)['successful_tasks']
        self.assertEqual(visible['old']['result'], original['task_results']['old']['result'])
        self.assertEqual(state, original)

    def test_adaptive_inline_does_not_displace_history_or_trigger_compaction(self):
        state = create_initial_state(7, '查看资料', [{'role': 'user', 'content': 'history ' * 2000}])
        state['task_results'] = {'large': evidence('body ' * 8000)}
        with patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1024), \
                patch.object(settings, 'CONTEXT_TOOL_ADAPTIVE_INLINE', False):
            base = main_agent.main_message_renderer(state, {})(state['history_messages'])
        ceiling = request_tokens(base, [main_agent.MainDecision]) + 1500
        with patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1024), \
                patch.object(settings, 'CONTEXT_COMPACT_TRIGGER_TOKENS', ceiling):
            messages = main_agent.main_message_renderer(state, {})(state['history_messages'])
        payload = json.loads(messages[1].content)
        self.assertEqual(payload['successful_tasks']['large']['content_scope'], 'index_only')
        self.assertEqual(payload['history'], json.loads(base[1].content)['history'])
        self.assertLess(request_tokens(messages, [main_agent.MainDecision]), ceiling)

    def test_adaptive_inline_counts_previous_results_and_character_guard(self):
        state = create_initial_state(7, '继续', [])
        state['task_results'] = {'current': evidence('current ' * 3000)}
        state['previous_run'] = {'reusable_results': {'previous': evidence('previous ' * 3000)}}
        with patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1024), \
                patch.object(settings, 'CONTEXT_TOOL_ADAPTIVE_INLINE', False):
            base = main_agent.main_message_renderer(state, {})([])
        with patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1024), \
                patch.object(settings, 'MAIN_CONTEXT_MAX_CHARS', sum(len(str(m.content)) for m in base) + 20000):
            messages = main_agent.main_message_renderer(state, {})([])
        payload = json.loads(messages[1].content)
        self.assertEqual(payload['successful_tasks']['current']['content_scope'], 'index_only')
        self.assertEqual(payload['previous_run']['reusable_results']['previous']['content_scope'], 'index_only')

    def test_adaptive_inline_does_not_refill_the_just_compacted_window(self):
        state = create_initial_state(7, '查看资料', [])
        state['task_results'] = {'large': evidence('body ' * 8000)}
        state['context_compaction'] = {'status': 'compacted', 'round': 1}
        with patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1024), \
                patch.object(settings, 'CONTEXT_TOOL_ADAPTIVE_INLINE', False):
            base = main_agent.main_message_renderer(state, {})([])
        target = request_tokens(base, [main_agent.MainDecision]) + 1500
        with patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1024), \
                patch.object(settings, 'CONTEXT_COMPACT_TARGET_TOKENS', target):
            messages = main_agent.main_message_renderer(state, {})([])
        self.assertEqual(json.loads(messages[1].content)['successful_tasks']['large']['content_scope'], 'index_only')
        self.assertLess(request_tokens(messages, [main_agent.MainDecision]), target)

    def test_index_cannot_supply_citations_or_sneak_into_default_answer_dependencies(self):
        view = {'hidden': {'content_scope': 'index_only', 'citations': [{'id': 'hidden:1'}]},
                'loaded': {'citations': [{'id': 'loaded:1'}]}}
        decision = main_agent.MainDecision(action='answer', reply='解释概念')
        ids = main_agent.validate_loaded_context(decision, view)
        state = {'task_results': {tid: {'status': 'succeeded', **item} for tid, item in view.items()}}
        citations, _ = main_agent.answer_evidence(state, [], ids)
        self.assertEqual([c['id'] for c in citations], ['loaded:1'])
        decision.answer_dependencies = ['hidden']
        with self.assertRaises(ValueError): main_agent.validate_loaded_context(decision, view)
        decision.answer_dependencies = []
        from app.models.evidence_assessment import EvidenceAssessment
        decision.evidence_assessment = EvidenceAssessment(selected_ids=['hidden:1'], adequacy='sufficient',
            missing_aspects=[], conflicts=[], reason='已充分')
        with self.assertRaises(ValueError): main_agent.validate_loaded_context(decision, view)

    def test_only_identical_body_and_citation_metadata_can_share_loaded_text(self):
        items = {'old': evidence(), 'new': evidence()}
        with patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 2500):
            view = project_results(items)
        self.assertEqual(view['old']['content_scope'], 'shared_result')
        self.assertEqual(view['old']['same_as'], 'new')
        items['old']['citations'] = [{'id': 'different'}]
        with patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 2500):
            self.assertEqual(project_results(items)['old']['content_scope'], 'index_only')
    def test_large_results_reduce_prompt_but_preserve_raw_results(self):
        state = create_initial_state(7, '比较资料', [])
        state['task_results'] = {'old': evidence(), 'new': evidence('y ' * 1200)}
        original = deepcopy(state)
        with patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1800):
            view = json.loads(main_agent.decision_context(state))
        self.assertEqual(state, original)
        self.assertEqual(view['successful_tasks']['old']['content_scope'], 'index_only')
        self.assertEqual(view['successful_tasks']['new']['result'], state['task_results']['new']['result'])
        self.assertLess(count_tokens(json.dumps(view['successful_tasks'])),
                        count_tokens(json.dumps(state['task_results'])) // 2)

    def test_private_document_is_never_hidden_behind_public_reader(self):
        original = {'private': evidence('x ' * 4000, 'editor')}
        with patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1024):
            self.assertEqual(project_results(original), original)

    def test_public_facts_do_not_reinject_hidden_tool_bodies(self):
        state = create_initial_state(7, '查看评论', [])
        state['task_results'] = {'comments': {**evidence('UNIQUE_BODY' * 5000),
            'kind': 'tool', 'tool_name': 'get_article_comments'}}
        with patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1024):
            payload = main_agent.decision_context(state)
        self.assertNotIn('UNIQUE_BODY', payload)

    def test_breakdown_has_no_prompt_text_and_covers_total(self):
        messages = main_agent.build_main_messages(create_initial_state(7, 'private request', []), {})
        usage = context_breakdown(messages, [main_agent.MainDecision])
        self.assertEqual(usage['total_tokens'], request_tokens(messages, [main_agent.MainDecision]))
        self.assertTrue(all(isinstance(v, int) for v in usage.values()))

    def test_revoke_survives_serialization_and_cannot_be_faked_as_completion(self):
        state = create_initial_state(7, '标题自动缩进', [])
        state['user_message_id'] = '101'
        state['task_context'] = update_task_context(state, TaskContextPatch(
            requirements=[{'id': 'indent', 'quote': '标题自动缩进'}]))
        state = json.loads(json.dumps(state)); state['user_message'] = '自动缩进不要了，让用户自己tab'
        state['user_message_id'] = '103'
        context = update_task_context(state, TaskContextPatch(revoke_requirement_ids=['indent'],
            revocation_quote='自动缩进不要了', requirements=[{'id': 'manual', 'quote': '让用户自己tab'}]))
        self.assertEqual([r['id'] for r in context['active_requirements']], ['manual'])
        self.assertEqual(context['revoked_requirements'][0]['message_id'], '101')
        self.assertEqual(context['revoked_requirements'][0]['revoked_by']['message_id'], '103')
        self.assertEqual(context['completed_items'], [])

    def test_assistant_suggestion_and_unquoted_revocation_are_rejected(self):
        state = create_initial_state(7, '帮我看看', [])
        with self.assertRaises(ValueError):
            update_task_context(state, TaskContextPatch(requirements=[{'id': 'fake', 'quote': '用户确认删除'}]))
        with self.assertRaises(ValueError):
            update_task_context(state, TaskContextPatch(revoke_requirement_ids=['fake']))
        with self.assertRaises(ValueError):
            TaskContextPatch.model_validate({'completed_items': ['已保存']})


class ContextReadersTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_user_and_task_requirements_reach_the_delivery_auditor(self):
        from app.services import grounding
        from app.services.execution_facts import execution_facts, delivery_notices
        state = create_initial_state(7, '发布日期改成2026-11-20', [])
        state['task_context'] = {'active_requirements': [{'id': 'deadline', 'quote': '改成2026-11-20'}],
            'revoked_requirements': [{'id': 'old', 'quote': '2026-11-10'}],
            'pending_items': [{'text': '未经确认的建议'}]}
        state['main_decision'] = {'evidence_assessment': {'adequacy': 'none'}}
        facts = execution_facts(state)
        self.assertEqual(facts['user_context']['current_message'], state['user_message'])
        self.assertEqual(facts['user_context']['task_requirements']['active_requirements'], state['task_context']['active_requirements'])
        self.assertNotIn('pending_items', facts['user_context']['task_requirements'])
        response = grounding.GroundingReview(blocks=[grounding.BlockReview(block_index=0, claims=[
            grounding.ClaimReview(unit_index=0, kind='user_content', verdict='supported')])])
        accepted = grounding.validate_review(response, ['发布日期现为2026-11-20。'], [], facts=facts)
        self.assertFalse(accepted)
        self.assertTrue(grounding.validate_review(response, ['发布日期现为2026-11-20。'], [], facts=execution_facts({})))
        self.assertEqual(delivery_notices(state, []), [])
        payload = json.loads(main_agent.decision_context(state))
        self.assertNotIn('user_context', payload['execution_facts'])
        with patch.object(grounding, 'review_text', AsyncMock(return_value=accepted)) as auditor:
            reply, audit = await grounding.verify_delivery(state, '发布日期现为2026-11-20。', [])
        self.assertEqual(reply, '发布日期现为2026-11-20。')
        self.assertEqual(audit['status'], 'verified')
        self.assertEqual(auditor.call_args.args[2]['user_context'], facts['user_context'])

    async def test_user_statement_does_not_replace_required_external_source_evidence(self):
        from app.services import grounding
        from app.services.execution_facts import execution_facts, delivery_notices
        state = create_initial_state(7, '我说接口默认超时13秒', [])
        response = grounding.GroundingReview(blocks=[grounding.BlockReview(block_index=0, claims=[
            grounding.ClaimReview(unit_index=0, kind='source_fact', verdict='supported')])])
        with self.assertRaises(grounding.ReviewContractError):
            grounding.validate_review(response, ['接口默认超时13秒。'], [], facts=execution_facts(state))
        state['task_results'] = {'lookup': {'status': 'succeeded', 'retrieval_report': {'platform': {'status': 'empty'}}}}
        state['main_decision'] = {'evidence_assessment': {'adequacy': 'none'}}
        self.assertTrue(delivery_notices(state, []))

    async def test_history_reply_is_audited_against_read_original_not_public_sources(self):
        from app.services import grounding
        from app.services.execution_facts import execution_facts
        message = {'message_id': '42', 'role': 'user', 'content': '不要自动缩进', 'start_char': 0, 'has_more': False}
        state = create_initial_state(7, '之前我怎么说的', [])
        state['task_results'] = {'read': {'status': 'succeeded', 'kind': 'tool', 'actor': 'main',
            'tool_name': 'read_conversation_messages', 'private_context': True,
            'result': json.dumps({'messages': [message]}), 'citations': []}}
        review = AsyncMock(return_value=grounding.ReviewIssues([], {0: '你说过不要自动缩进。'}))
        with patch.object(grounding, 'review_text', review):
            text, audit = await grounding.verify_delivery(state, '你说过不要自动缩进。', [])
        self.assertEqual(audit['review_calls'], 1)
        self.assertEqual(review.call_args.args[2]['conversation_messages'], [message])
        self.assertEqual(text, '你说过不要自动缩进。')
        self.assertEqual(execution_facts(state)['conversation_messages'], [message])

    async def test_read_result_is_exact_slice_with_original_citations(self):
        citation = {'id': 's1', 'articleId': '42', 'sourceHash': 'hash'}
        source = {**evidence('0123456789' * 200), 'citations': [citation]}
        context = tool_context('read_task_result', {'source_task_id': 's', 'start_char': 500, 'max_chars': 500}, {'s': source})
        with patch.object(context_tools, 'verify_public_evidence', AsyncMock()) as verify:
            output = await context_tools.read_task_result(context)
        payload = json.loads(output['result'])
        self.assertEqual(payload['content'], source['result'][500:1000])
        self.assertTrue(payload['has_more']); self.assertEqual(payload['next_start_char'], 1000)
        self.assertEqual(output['citations'], [citation]); verify.assert_awaited_once_with([citation])

    async def test_private_and_unknown_results_cannot_be_read(self):
        for sources in ({}, {'s': evidence('secret', 'drafts')}, {'s': evidence('secret', 'memory')},
                        {'s': evidence('secret', 'editor')}):
            with self.assertRaises(ValueError):
                await context_tools.read_task_result(tool_context('read_task_result', {'source_task_id': 's'}, sources))

    async def test_web_snapshot_cannot_bypass_disabled_web_or_user_deny(self):
        source = {**evidence(), 'tool_name': 'web_search', 'citations': [{'id': 'w1', 'url': 'https://example.com'}]}
        with patch.object(settings, 'AGENT_WEB_SEARCH_ENABLED', False):
            context = tool_context('read_task_result', {'source_task_id': 's', 'allow_web': True}, {'s': source})
            with self.assertRaises(PermissionError): await context_tools.read_task_result(context)
        with patch.object(settings, 'AGENT_WEB_SEARCH_ENABLED', True):
            context = tool_context('read_task_result', {'source_task_id': 's', 'allow_web': True}, {'s': source})
            context['active_constraints'] = [{'id': 'deny', 'key': 'web_search', 'content': 'deny'}]
            with self.assertRaises(PermissionError): await context_tools.read_task_result(context)

    async def test_changed_source_is_not_reused(self):
        context = tool_context('read_task_result', {'source_task_id': 's'}, {'s': evidence()})
        with patch.object(context_tools, 'verify_public_evidence', AsyncMock(side_effect=ValueError('changed'))):
            with self.assertRaises(ValueError): await context_tools.read_task_result(context)

    async def test_history_reader_checks_owner_before_query(self):
        context = tool_context('read_conversation_messages', {'message_ids': [42]})
        with patch.object(context_tools.ConversationService, 'require_owner', AsyncMock(side_effect=PermissionError())), \
             patch.object(context_tools.db, 'fetch_all', AsyncMock()) as query:
            with self.assertRaises(PermissionError): await context_tools.conversation_history(context)
        query.assert_not_awaited()

    async def test_history_read_cannot_import_id_from_another_conversation(self):
        context = tool_context('read_conversation_messages', {'message_ids': [42]})
        with patch.object(context_tools.ConversationService, 'require_owner', AsyncMock()), \
             patch.object(context_tools.db, 'fetch_all', AsyncMock(return_value=[])) as query:
            with self.assertRaises(ValueError): await context_tools.conversation_history(context)
        sql, params = query.call_args.args
        self.assertIn('conversation_id=:cid', sql); self.assertEqual(params['cid'], 11)

    async def test_history_search_escapes_wildcards_and_returns_original_role(self):
        context = tool_context('search_conversation_history', {'keyword': 'a%b_', 'limit': 1})
        rows = [SimpleNamespace(_mapping={'message_id': n, 'role': 'assistant', 'content': '原话', 'total_chars': 5000}) for n in (42, 41)]
        with patch.object(context_tools.ConversationService, 'require_owner', AsyncMock()), \
             patch.object(context_tools.db, 'fetch_all', AsyncMock(return_value=rows)) as query:
            output = await context_tools.conversation_history(context)
        data = json.loads(output['result'])
        self.assertEqual(query.call_args.args[1]['keyword'], '%a\\%b\\_%')
        self.assertTrue(data['has_more']); self.assertEqual(data['next_before_message_id'], '42')
        self.assertEqual(data['messages'][0]['role'], 'assistant'); self.assertTrue(data['messages'][0]['has_more'])

    async def test_task_context_reloads_from_owned_run_after_interruption(self):
        context = {'version': 1, 'active_requirements': [{'id': 'manual', 'quote': '自己tab'}]}
        state = create_initial_state(7, '继续', []); state['task_context'] = context
        snapshot = progress_snapshot(state, 'main_agent', 'failed')
        database = SimpleNamespace(fetch_all=AsyncMock(return_value=[SimpleNamespace(_mapping={
            'result_json': json.dumps({'progress': snapshot})})]))
        history = RunHistory(database=database)
        restored = await history.task_context(11, 7, 'current')
        self.assertEqual(restored['active_requirements'], context['active_requirements'])
        sql, params = database.fetch_all.call_args.args
        self.assertIn('c.user_id=:uid', sql); self.assertEqual(params['uid'], 7)

    async def test_paging_keeps_whole_recent_turn_and_never_advances_summary_across_gap(self):
        history = [{'message_id': i, 'role': 'user' if i % 2 else 'assistant', 'content': 'x ' * 1000} for i in range(1, 21)]
        database = FakeStore(history)
        service = ConversationService.__new__(ConversationService)
        with patch('app.services.conversation.db', database), patch.object(settings, 'HISTORY_LOAD_MAX_TOKENS', 2500):
            window = await service._load_context(11)
        self.assertEqual(window[0]['kind'], 'history_notice')
        self.assertEqual(window[1]['role'], 'user'); self.assertEqual(window[-1]['message_id'], 20)
        state = create_initial_state(7, '继续', window)
        with patch.object(settings, 'CONTEXT_COMPACT_TRIGGER_TOKENS', 1024):
            _, update = await main_context.prepare_context(state, main_agent.main_message_renderer(state, {}), [main_agent.MainDecision])
        self.assertEqual(update['context_compaction']['status'], 'paged_history')
        self.assertEqual(database.updates, [])

    async def test_oversized_summary_preserves_old_summary_and_raw_history(self):
        history = [{'message_id': i, 'role': 'user' if i % 2 else 'assistant', 'content': '原话'} for i in range(1, 5)]
        database = FakeStore(history)
        service = ConversationService.__new__(ConversationService)
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content='x ' * 600)))
        with patch('app.services.conversation.db', database), patch('app.services.conversation.get_llm', return_value=model), \
             patch.object(settings, 'SUMMARY_MAX_TOKENS', 128):
            with self.assertRaises(ValueError): await service.compact_history(11, history, 2, user_id=7)
        self.assertEqual(database.updates, []); self.assertEqual(database.history, history)

    async def test_paged_compaction_advances_only_contiguous_old_prefix_not_the_gap(self):
        prefix = [{'message_id': i, 'role': 'user' if i % 2 else 'assistant', 'content': '早期要求'} for i in range(1, 8)]
        recent = [{'message_id': 101, 'role': 'user', 'content': '当前问题'},
                  {'message_id': 102, 'role': 'assistant', 'content': '当前回答'}]
        notice = {'role': 'system', 'kind': 'history_notice', 'content': '存在缺口', 'before_message_id': '101'}
        database = FakeStore(prefix)
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content='早期要求摘要')))
        service = ConversationService.__new__(ConversationService)
        service._redis = SimpleNamespace(delete=AsyncMock())
        with patch('app.services.conversation.db', database), patch('app.services.conversation.get_llm', return_value=model):
            output = await service.compact_window(11, [notice, *recent], user_id=7)
        self.assertEqual(output['status'], 'compacted')
        self.assertEqual(database.cursor, 6)
        self.assertEqual(output['history'][1], notice)
        self.assertEqual(output['history'][2:], recent)

    async def test_oversized_summary_gets_one_bounded_recompression(self):
        history = [{'message_id': i, 'role': 'user' if i % 2 else 'assistant', 'content': '原话'} for i in range(1, 5)]
        database = FakeStore(history)
        service = ConversationService.__new__(ConversationService); service._redis = SimpleNamespace(delete=AsyncMock())
        model = SimpleNamespace(ainvoke=AsyncMock(side_effect=[SimpleNamespace(content='x ' * 600),
            SimpleNamespace(content='已取消自动缩进；手动Tab；来源消息1、2。')]))
        with patch('app.services.conversation.db', database), patch('app.services.conversation.get_llm', return_value=model), \
             patch.object(settings, 'SUMMARY_MAX_TOKENS', 128):
            output = await service.compact_history(11, history, 2, user_id=7)
        self.assertEqual(output['summary_calls'], 2)
        self.assertEqual(database.cursor, 2)
        self.assertIn('已取消自动缩进', database.summary)

    async def test_read_results_dispatch_and_preserve_original_task_after_checkpoint(self):
        from test_main_tools import planned, decision
        state = planned(decision('read_task_result', {'source_task_id': 'source'}, tid='readback'))
        state['task_results'] = {'source': evidence('source body')}
        with patch.object(context_tools, 'verify_public_evidence', AsyncMock()):
            update = await action_runtime.execute_tool_node(state)
        self.assertEqual(update['task_results']['readback']['status'], 'succeeded')
        restored = json.loads(json.dumps({**state, 'task_results': {**state['task_results'], **update['task_results']}}))
        self.assertEqual(restored['task_results']['source']['result'], 'source body')
        self.assertEqual(json.loads(restored['task_results']['readback']['result'])['content'], 'source body')
        with patch.object(context_tools, 'verify_public_evidence', AsyncMock()):
            reread = await context_tools.read_task_result(tool_context('read_task_result',
                {'source_task_id': 'readback'}, restored['task_results']))
        self.assertEqual(reread['status'], 'succeeded')

    async def test_history_tool_and_derived_analysis_remain_private(self):
        from app.graph.staged_runtime import task_context, task_result
        state = create_initial_state(7, '读取历史', [])
        context = tool_context('read_conversation_messages', {'message_ids': [42]})
        task = ExecutionTask.model_validate(context['current_task'])
        local = task_context(state, task)
        self.assertTrue(local['private_context'])
        result = task_result(local, {'worker_results': [{'worker_name': 'tool', 'result': '私有原话'}]})
        self.assertTrue(result['private_context'])
        state['task_results'] = {'history': result}
        child = task_context(state, ExecutionTask(task_id='child', actor='subagent', kind='analysis',
            instruction='分析原话', depends_on=['history']))
        self.assertTrue(child['private_context'])

    async def test_private_analysis_is_not_reclassified_as_public(self):
        source = {**evidence('private analysis'), 'kind': 'analysis', 'private_context': True}
        with self.assertRaises(ValueError):
            await context_tools.read_task_result(tool_context('read_task_result', {'source_task_id': 's'}, {'s': source}))
