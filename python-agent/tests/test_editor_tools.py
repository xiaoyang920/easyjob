from tool_fakes import retrieval_call, raw_retrieval_call
"""Editor snapshots/proposals and exact-page retrieval; no external model/API."""
import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
os.environ['AGENT_SERVICE_KEY'] = 'offline-service-key-32-bytes-long!!'

import unittest
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from app.graph import builder, main_agent, staged_runtime
from app.graph.main_agent import MainDecision, RetrievalRequest
from app.graph.staged_plan import ExecutionTask
from app.graph.state_factory import create_initial_state
from app.services.editor_tools import EditorSnapshot, EditorEdit, read_editor, build_editor_edits
from app.services.run_history import public_result, project_history
from app.services import page_reader
from app.services import grounding
from app.services.execution_facts import execution_facts

DOC = '12345678-1234-4234-8234-123456789012'
SNAP = '12345678-1234-4234-8234-123456789013'

def snapshot(**changes):
    return EditorSnapshot(document_id=DOC, snapshot_id=SNAP, title='原来的标题', content='原来的正文。', selection='正文', **changes).model_dump(mode='json')

def context(part='document'):
    state = create_initial_state(7, '修改当前文章', [])
    task = ExecutionTask(task_id='read_editor', instruction='读取当前文章', kind='search', actor='main', retrieval_target='editor', editor_part=part)
    state['editor_context'] = snapshot()
    return staged_runtime.task_context(state, task), task


class EditorContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_is_request_scoped_and_not_reusable_as_public_evidence(self):
        state, task = context()
        data = await read_editor(state)
        result = staged_runtime.task_result(state, {'worker_results': [{'worker_name': 'search', 'status': data['status'], 'result': data['result']}],
            'citations': [], 'article_cards': [], 'editor_snapshot_id': data['editor_snapshot_id'], 'editor_part': data['editor_part']})
        self.assertEqual(result['editor_snapshot_id'], SNAP)
        self.assertFalse(public_result(result))
        edit = EditorEdit(source_task_id='read_editor', target='body', replacement='更清楚的正文。')
        proposals = build_editor_edits({'editor_context': snapshot(), 'task_results': {'read_editor': result}}, [edit], ['read_editor'])
        self.assertEqual(proposals[0]['before'], '原来的正文。')
        self.assertEqual(proposals[0]['snapshotId'], SNAP)
        self.assertEqual(len(proposals[0]['id']), 64)
        with self.assertRaises(ValueError):
            build_editor_edits({'editor_context': snapshot(), 'task_results': {'read_editor': {**result, 'editor_snapshot_id': DOC}}}, [edit], ['read_editor'])
        with self.assertRaises(ValueError):
            build_editor_edits({'editor_context': snapshot(content_complete=False), 'task_results': {'read_editor': result}}, [edit], ['read_editor'])
        with self.assertRaises(ValueError):
            build_editor_edits({'editor_context': snapshot(), 'task_results': {'read_editor': result}}, [edit], [])

    async def test_selection_requires_explicit_selection_read_and_missing_selection_is_not_success(self):
        state, _ = context('selection')
        data = await read_editor(state)
        self.assertNotIn('原来的正文。', data['result'])
        source = {'status': 'succeeded', 'retrieval_target': 'editor', 'editor_snapshot_id': SNAP, 'editor_part': 'document'}
        edit = EditorEdit(source_task_id='read_editor', target='selection', replacement='新正文')
        with self.assertRaises(ValueError):
            build_editor_edits({'editor_context': snapshot(), 'task_results': {'read_editor': source}}, [edit], ['read_editor'])
        state['editor_context']['selection'] = ''
        self.assertEqual((await read_editor(state))['status'], 'insufficient_evidence')
        state['capabilities'] = []
        with self.assertRaises(PermissionError):
            await read_editor(state)

    def test_editor_cannot_grant_web_access_or_database_write(self):
        with self.assertRaises(ValidationError):
            RetrievalRequest(target='editor', instruction='read', allow_web=True)
        with self.assertRaises(ValidationError):
            ExecutionTask(task_id='bad', instruction='read', kind='search', actor='subagent', retrieval_target='editor')
        with self.assertRaises(ValidationError):
            MainDecision(action='call_tool', tool_call=retrieval_call(RetrievalRequest(target='editor', instruction='read')), editor_edits=[EditorEdit(source_task_id='x', target='title', replacement='new')])

    async def test_read_budget_does_not_silently_allow_a_truncated_rewrite(self):
        state, _ = context()
        with patch('app.config.settings.TASK_RESULT_MAX_CHARS', 100):
            data = await read_editor(state)
        self.assertEqual(data['status'], 'insufficient_evidence')
        self.assertNotIn('editor_snapshot_id', data)

    async def test_failed_content_review_removes_proposal_even_if_review_text_is_unchanged(self):
        state = create_initial_state(7, '修改当前正文', [])
        state.update(final_reply='请确认修改建议。', editor_edits=[{'after': '未经证实的新事实'}])
        with patch('app.services.grounding.verify_delivery', AsyncMock(side_effect=[('请确认修改建议。', {'status': 'not_required'}), ('未经证实的新事实', {'status': 'unverified'})])):
            result = await staged_runtime.final_gate(state)
        self.assertEqual(result['editor_edits'], [])
        self.assertIn('未通过内容核验', result['final_reply'])

    async def test_real_graph_reads_editor_then_delivers_a_proposal_without_save(self):
        decisions = [MainDecision(action='call_tool', tool_call=retrieval_call(RetrievalRequest(task_id='read_editor', target='editor', instruction='读取当前文章'))),
            MainDecision(action='answer', reply='这是待确认的标题修改建议。', answer_dependencies=['read_editor'],
                editor_edits=[EditorEdit(source_task_id='read_editor', target='title', replacement='更清楚的新标题')])]
        control = SimpleNamespace(ainvoke=AsyncMock(side_effect=decisions))
        model = SimpleNamespace(with_structured_output=Mock(return_value=control))
        state = create_initial_state(7, '帮我修改当前标题', [])
        state['editor_context'] = snapshot()
        with patch.object(main_agent, 'get_llm', return_value=model), patch.object(grounding, 'review_text', AsyncMock(return_value=[])):
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            result = await graph.ainvoke(state, {'configurable': {'thread_id': 'editor-qa'}})
        self.assertEqual(result['editor_edits'][0]['after'], '更清楚的新标题')
        self.assertFalse(result.get('draft_article_id'))
        self.assertEqual([task['action'] for task in result['action_history']], ['call_tool'])

    async def test_summary_proposal_uses_snapshot_summary_and_enforces_its_limit(self):
        source = {'status': 'succeeded', 'retrieval_target': 'editor', 'editor_snapshot_id': SNAP, 'editor_part': 'document'}
        state = {'editor_context': snapshot(summary='原摘要'), 'task_results': {'read_editor': source}}
        edit = EditorEdit(source_task_id='read_editor', target='summary', replacement='根据正文生成的新摘要。')
        proposal = build_editor_edits(state, [edit], ['read_editor'])[0]
        self.assertEqual(proposal['before'], '原摘要')
        self.assertEqual(proposal['format'], 'text')
        state['editor_context']['summary'] = ''
        self.assertEqual(build_editor_edits(state, [edit], ['read_editor'])[0]['before'], '')
        with self.assertRaises(ValueError):
            build_editor_edits(state, [edit.model_copy(update={'replacement': '摘' * 501})], ['read_editor'])
        with self.assertRaises(ValueError):
            build_editor_edits(state, [edit], [])

    async def test_real_graph_generates_summary_from_unsaved_editor_without_creating_a_draft(self):
        decisions = [MainDecision(action='call_tool', tool_call=retrieval_call(RetrievalRequest(task_id='read_editor', target='editor', instruction='读取正文写摘要'))),
            MainDecision(action='answer', reply='摘要已生成，请确认后应用。', answer_dependencies=['read_editor'],
                editor_edits=[EditorEdit(source_task_id='read_editor', target='summary', replacement='根据当前正文生成的摘要。')])]
        control = SimpleNamespace(ainvoke=AsyncMock(side_effect=decisions))
        model = SimpleNamespace(with_structured_output=Mock(return_value=control))
        state = create_initial_state(7, '你帮我写个摘要', [])
        state['editor_context'] = snapshot()
        with patch.object(main_agent, 'get_llm', return_value=model), patch.object(grounding, 'review_text', AsyncMock(return_value=[])):
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            result = await graph.ainvoke(state, {'configurable': {'thread_id': 'editor-summary-qa'}})
        self.assertEqual(result['editor_edits'][0]['target'], 'summary')
        self.assertEqual(result['editor_edits'][0]['before'], '')
        self.assertFalse(result.get('draft_article_id'))
        self.assertEqual(control.ainvoke.await_count, 2)

    async def test_summary_answer_with_conflicting_artifact_recovers_without_rereading_editor(self):
        bad = {'action': 'answer', 'artifacts': [{'task_id': 'summary', 'instruction': '生成摘要', 'result': '正文摘要'}],
               'answer_dependencies': ['read_editor'], 'user_reply': '摘要如下。'}
        with self.assertRaises(ValidationError) as caught:
            MainDecision.model_validate(bad)
        raw = {'raw': SimpleNamespace(tool_calls=[{'name': 'MainDecision', 'args': bad}]),
               'parsed': None, 'parsing_error': caught.exception}
        decisions = [MainDecision(action='call_tool', tool_call=retrieval_call(RetrievalRequest(task_id='read_editor', target='editor', instruction='读取正文写摘要'))),
            raw, MainDecision(action='answer', reply='请确认这份摘要。', answer_dependencies=['read_editor'],
                editor_edits=[EditorEdit(source_task_id='read_editor', target='summary', replacement='根据正文生成的摘要。')])]
        control = SimpleNamespace(ainvoke=AsyncMock(side_effect=decisions))
        model = SimpleNamespace(with_structured_output=Mock(return_value=control))
        state = create_initial_state(7, '你帮我写个摘要', [])
        state['editor_context'] = snapshot()
        with patch.object(main_agent, 'get_llm', return_value=model), patch.object(grounding, 'review_text', AsyncMock(return_value=[])):
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            result = await graph.ainvoke(state, {'configurable': {'thread_id': 'editor-summary-repair-qa'}})
        self.assertEqual(result['decision_contract_audit']['last_outcome'], 'repaired')
        self.assertEqual(result['editor_edits'][0]['target'], 'summary')
        self.assertEqual(len(result['action_history']), 1)
        self.assertFalse(result.get('draft_article_id'))
        self.assertIn('answer时artifacts必须=[]', control.ainvoke.await_args_list[-1].args[0][-1].content)

    def test_history_replays_proposals_only_on_their_committed_assistant_message(self):
        history = [{'role': 'assistant', 'messageId': '8', 'content': '修改建议'}]
        runs = [{'run_id': 'run', 'status': 'succeeded', 'draft_article_id': None,
                 'created_at': '2026-10-11T01:00:00Z', 'updated_at': '2026-10-11T01:00:22Z',
                 'result_json': {'editor_edits': [{'id': 'one'}], 'assistant_message_id': '8'}}]
        self.assertEqual(project_history(history, runs, {}, {})[0]['editorEdits'], [{'id': 'one'}])

    def test_auditor_receives_only_the_current_successfully_read_editor_scope(self):
        state = {'editor_context': snapshot(), 'task_results': {}}
        self.assertEqual(execution_facts(state)['editor_documents'], [])
        source = {'status': 'succeeded', 'retrieval_target': 'editor', 'editor_snapshot_id': SNAP, 'editor_part': 'selection'}
        state['task_results']['read_editor'] = source
        document = execution_facts(state)['editor_documents'][0]
        self.assertEqual(document['content'], '正文')
        self.assertFalse(document['content_complete'])
        source['editor_part'] = 'document'
        self.assertEqual(execution_facts(state)['editor_documents'][0]['content'], '原来的正文。')
        source['editor_snapshot_id'] = DOC
        self.assertEqual(execution_facts(state)['editor_documents'], [])
        source.update(editor_snapshot_id=SNAP, status='tool_error')
        self.assertEqual(execution_facts(state)['editor_documents'], [])

    async def test_summary_is_audited_against_editor_text_without_public_citations_or_placeholder(self):
        text = '本文介绍正文的内容。'
        state = create_initial_state(7, '帮我写个摘要', [])
        state['editor_context'] = snapshot(content_complete=False)
        state['task_results'] = {'read_editor': {'status': 'succeeded', 'retrieval_target': 'editor',
            'editor_snapshot_id': SNAP, 'editor_part': 'document'}}
        state['main_decision'] = {'evidence_assessment': {'adequacy': 'none'}}
        async def audit(messages, **kwargs):
            payload = json.loads(messages[-1].content)
            self.assertEqual(payload['execution_facts']['editor_documents'][0]['content'], '原来的正文。')
            self.assertEqual(payload['sources'], [])
            return grounding.GroundingReview(blocks=[grounding.BlockReview(block_index=0, claims=[
                grounding.ClaimReview(unit_index=0, kind='user_content', verdict='supported')])])
        controller = SimpleNamespace(ainvoke=AsyncMock(side_effect=audit))
        with patch.object(grounding, 'get_llm', return_value=SimpleNamespace(with_structured_output=Mock(return_value=controller))):
            result, audit_result = await grounding.verify_delivery(state, text, [])
        self.assertEqual(result, text)
        self.assertEqual(audit_result['status'], 'verified')
        self.assertEqual(controller.ainvoke.await_count, 1)
        self.assertNotIn('需要查阅', result)

    def test_editor_summary_category_cannot_bypass_missing_editor_or_external_fact_evidence(self):
        review = grounding.GroundingReview(blocks=[grounding.BlockReview(block_index=0, claims=[
            grounding.ClaimReview(unit_index=0, kind='user_content', verdict='supported')])])
        self.assertTrue(grounding.validate_review(review, ['摘要正文'], [], facts=execution_facts({})))
        review.blocks[0].claims[0].kind = 'source_fact'
        state = {'editor_context': snapshot(), 'task_results': {'read_editor': {'status': 'succeeded',
            'retrieval_target': 'editor', 'editor_snapshot_id': SNAP, 'editor_part': 'document'}}}
        with self.assertRaises(grounding.ReviewContractError):
            grounding.validate_review(review, ['外部事实'], [], facts=execution_facts(state))

    def test_plain_text_snapshot_can_generate_summary_but_cannot_replace_rich_body(self):
        source = {'status': 'succeeded', 'retrieval_target': 'editor', 'editor_snapshot_id': SNAP, 'editor_part': 'document'}
        state = {'editor_context': snapshot(body_replaceable=False), 'task_results': {'read_editor': source}}
        edit = EditorEdit(source_task_id='read_editor', target='summary', replacement='正文摘要')
        self.assertEqual(build_editor_edits(state, [edit], ['read_editor'])[0]['target'], 'summary')
        with self.assertRaises(ValueError):
            build_editor_edits(state, [edit.model_copy(update={'target': 'body'})], ['read_editor'])


class PageReaderTests(unittest.IsolatedAsyncioTestCase):
    def test_markdown_and_chinese_punctuation_keep_the_actual_url(self):
        self.assertEqual(page_reader.referenced_urls('读[文档](https://example.org/Foo_(bar))，帮我总结。'), {'https://example.org/Foo_(bar)'})

    def state(self, urls):
        task = ExecutionTask(task_id='pages', instruction='读取网页', kind='search', actor='main', retrieval_target='knowledge', allow_web=True, urls=urls)
        state = create_initial_state(7, '读一下 https://example.org/doc。', [])
        return staged_runtime.task_context(state, task)

    async def test_exact_page_enters_evidence_and_never_calls_keyword_search(self):
        with patch('app.config.settings.AGENT_WEB_SEARCH_ENABLED', True), patch.object(page_reader, 'do_fetch', AsyncMock(return_value={
            'title': '文档', 'content': '实际网页正文', 'contentScope': 'page_content', 'contentTruncated': False})) as fetch:
            result = await page_reader.read_pages(self.state(['https://example.org/doc']))
        fetch.assert_awaited_once_with('https://example.org/doc')
        self.assertEqual(result['citations'][0]['url'], 'https://example.org/doc')
        self.assertIn('实际网页正文', result['rag_context'])

    async def test_exact_urls_are_wired_into_the_shared_retriever(self):
        from app.graph.nodes import search_worker
        with patch('app.config.settings.AGENT_WEB_SEARCH_ENABLED', True), patch.object(page_reader, 'do_fetch', AsyncMock(return_value={
            'title': '文档', 'content': '正文', 'contentScope': 'page_content', 'contentTruncated': False})), patch.object(search_worker.query_rewrite_service, 'rewrite_request', AsyncMock()) as rewrite:
            result = await search_worker.retrieve_evidence(self.state(['https://example.org/doc']))
        self.assertEqual(result['status'], 'succeeded')
        rewrite.assert_not_awaited()

    async def test_denied_or_unreferenced_urls_never_reach_provider(self):
        for url in ['http://127.0.0.1/private', 'file:///etc/passwd', 'https://unmentioned.example/doc']:
            with patch('app.config.settings.AGENT_WEB_SEARCH_ENABLED', True), patch.object(page_reader, 'do_fetch', AsyncMock()) as fetch:
                with self.assertRaises(PermissionError):
                    await page_reader.read_pages(self.state([url]))
                fetch.assert_not_awaited()
        with patch('app.config.settings.AGENT_WEB_SEARCH_ENABLED', False), patch.object(page_reader, 'do_fetch', AsyncMock()) as fetch:
            with self.assertRaises(PermissionError):
                await page_reader.read_pages(self.state(['https://example.org/doc']))
            fetch.assert_not_awaited()

    async def test_failed_fetch_is_reported_and_does_not_substitute_search_results(self):
        with patch('app.config.settings.AGENT_WEB_SEARCH_ENABLED', True), patch.object(page_reader, 'do_fetch', AsyncMock(side_effect=page_reader.WebSearchError('offline'))):
            result = await page_reader.read_pages(self.state(['https://example.org/doc']))
        self.assertEqual(result['status'], 'tool_error')
        self.assertEqual(result['citations'], [])
