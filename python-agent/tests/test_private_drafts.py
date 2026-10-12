"""Owner-only draft reads and approved edits on the real production graph."""
import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
os.environ['AGENT_SERVICE_KEY'] = 'offline-service-key-32-bytes-long!!'

import unittest
from unittest.mock import AsyncMock, patch
import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.graph import builder, main_agent as agent, action_runtime as actions, staged_runtime as runtime
from app.graph.main_agent import MainDecision, RetrievalRequest
from app.graph.staged_plan import DraftRequest, ExecutionTask
from app.graph.state_factory import create_initial_state
from app.graph.nodes import writing_worker
from app.models.draft import DraftOutput
from app.security.capabilities import task_capabilities
from app.services import private_drafts, draft_gateway
from fakes import repository, RUN_ID
from test_main_agent import llm


class PrivateDraftTests(unittest.IsolatedAsyncioTestCase):
    def context(self, **kwargs):
        task = ExecutionTask(task_id='own', instruction='读取草稿', kind='search', actor='main',
                             retrieval_target='drafts', **kwargs)
        return runtime.task_context(create_initial_state(7, '修改我的草稿', []), task)

    def client(self, response):
        client = AsyncMock()
        client.get.return_value = response
        client.post.return_value = response
        client.__aenter__.return_value = client
        return client

    def test_private_drafts_have_separate_capability_and_no_web(self):
        ctx = self.context()
        self.assertEqual(ctx['capabilities'], ['own_draft_read'])
        for extra in ({'allow_web': True}, {'article_ids': [1, 2]}):
            with self.assertRaises(ValueError):
                RetrievalRequest(target='drafts', instruction='read', **extra)
        with self.assertRaises(ValueError):
            ExecutionTask(task_id='own', instruction='read', kind='search', actor='subagent', retrieval_target='drafts')
        with self.assertRaises(ValueError):
            ExecutionTask(task_id='write', instruction='write', kind='writing', actor='main', draft_source_task_id='own')

    async def test_full_read_keeps_images_and_uses_authenticated_owner(self):
        original = '<h1>原文</h1><img src="/uploads/a.png"><p>尾部 [9]</p>'
        response = httpx.Response(200, json={'articleId': '42', 'revisionId': '5', 'lockVersion': 3, 'state': 0, 'editable': True,
                                  'payload': {'title': '原文', 'content': original, 'contentType': 1}})
        response.request = httpx.Request('GET', 'http://test/drafts/42')
        client = self.client(response)
        with patch.object(private_drafts.httpx, 'AsyncClient', return_value=client):
            result = await private_drafts.retrieve_drafts(self.context(article_ids=[42]))
        self.assertEqual(result['draft_document']['content'], original)
        self.assertEqual(result['draft_document']['revision_id'], '5')
        self.assertEqual(result['draft_document']['lock_version'], 3)
        self.assertEqual(client.get.call_args.kwargs['headers']['X-Agent-User'], '7')
        self.assertEqual(result['citations'], [])

    async def test_denied_read_never_exposes_body_or_falls_back(self):
        for code in (403, 404):
            client = self.client(httpx.Response(code, text='private title and body'))
            with patch.object(private_drafts.httpx, 'AsyncClient', return_value=client):
                result = await private_drafts.retrieve_drafts(self.context(article_ids=[42]))
            self.assertNotIn('draft_document', result)
            self.assertNotIn('private title', result['result'])
            self.assertEqual(client.get.await_count, 1)

    async def test_service_failure_is_recoverable_and_long_draft_never_truncated(self):
        client = self.client(httpx.Response(503, text='internal exception'))
        with patch.object(private_drafts.httpx, 'AsyncClient', return_value=client), self.assertRaises(ConnectionError):
            await private_drafts.retrieve_drafts(self.context())
        response = httpx.Response(200, json={'articleId': '42', 'revisionId': '5', 'lockVersion': 3, 'state': 0, 'editable': True,
                                            'payload': {'title': '标题', 'content': '\n' * 1100}})
        response.request = httpx.Request('GET', 'http://test/drafts/42')
        with patch.object(private_drafts.httpx, 'AsyncClient', return_value=self.client(response)), \
             patch.object(private_drafts.settings, 'TASK_RESULT_MAX_CHARS', 2100):
            result = await private_drafts.retrieve_drafts(self.context(article_ids=[42]))
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertNotIn('draft_document', result)

    def test_pending_or_non_draft_dependencies_cannot_become_write_targets(self):
        task = ExecutionTask(task_id='edit', kind='writing', actor='main', instruction='修改',
                             draft_source_task_id='own', depends_on=['own'])
        for source in ({'retrieval_target': 'drafts', 'draft_document': {'editable': False}},
                       {'retrieval_target': 'knowledge', 'draft_document': {'editable': True}},
                       {'retrieval_target': 'drafts'}):
            state = create_initial_state(7, '修改', [])
            state['task_results'] = {'own': {'status': 'succeeded', 'kind': 'search', 'actor': 'main', **source}}
            with self.assertRaises(ValueError):
                runtime.task_context(state, task)

    async def test_existing_draft_manual_approval_preserves_target_and_skips_regeneration(self):
        document = {'article_id': '42', 'revision_id': '5', 'lock_version': 3, 'title': '原文', 'summary': '',
                    'content': '原文 [9]', 'content_type': 2, 'editable': True}
        result = {'status': 'succeeded', 'result': '本人草稿全文 原文 [9]', 'draft_document': document,
                  'citations': [], 'article_cards': []}
        model, control = llm([
            MainDecision(action='retrieve', retrieval=RetrievalRequest(task_id='own', target='drafts', instruction='read', article_ids=[42])),
            MainDecision(action='write_draft', draft_request=DraftRequest(task_id='edit', instruction='修改并保留图片和引用', depends_on=['own'], draft_source_task_id='own')),
        ])
        state = create_initial_state(7, '修改我的原草稿', [])
        state.update(run_id=RUN_ID, execution_token='first')
        config = {'configurable': {'thread_id': 'private-edit', 'execution_token': 'first'}, 'recursion_limit': 80}
        generated = DraftOutput(title='改写版', summary='摘要', content='改写正文 [9]')
        edited = {'title': '手动标题', 'summary': '手动摘要', 'content': '# 手动正文\n保留旧脚注 [9]\n![图片](/uploads/a.png)'}
        with patch.object(agent, 'get_llm', return_value=model), patch.object(runtime, 'run_repository', repository()), \
             patch.object(actions, 'retrieve_drafts', AsyncMock(return_value=result)), \
             patch.object(writing_worker, 'generate_draft', AsyncMock(return_value=generated)) as generate, \
             patch.object(writing_worker, 'save_approved_draft', AsyncMock(return_value=42)) as save:
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            await graph.ainvoke(state, config)
            snap = await graph.aget_state(config)
            pending = snap.tasks[0].interrupts[0].value
            self.assertEqual(pending['targetArticleId'], '42')
            save.assert_not_awaited()
            config['configurable']['execution_token'] = 'resumed'
            await graph.ainvoke(Command(resume={'action': 'approve', 'runId': RUN_ID,
                                 'draftHash': pending['draftHash'], 'editedDraft': edited}), config)
        generate.assert_awaited_once()
        self.assertEqual(control.ainvoke.await_count, 2)
        saved_state, saved_draft = save.call_args.args
        self.assertEqual(saved_draft.content, edited['content'])
        self.assertEqual(saved_state['pending_article_id'], 42)
        self.assertEqual(saved_state['target_draft']['revision_id'], '5')
        self.assertEqual(saved_state['target_draft']['lock_version'], 3)
        self.assertEqual(saved_state['approved_base_hash'], pending['draftHash'])
        self.assertNotEqual(saved_state['draft_hash'], pending['draftHash'])
        self.assertIn('<h1>手动正文</h1>', saved_state['draft_html'])
        self.assertEqual(saved_state['execution_token'], 'resumed')

    async def test_gateway_sends_both_approval_version_and_edited_content_version(self):
        draft = DraftOutput(title='手动', summary='', content='修改版')
        response = httpx.Response(200, json={'articleId': '42'}, request=httpx.Request('POST', 'http://test'))
        client = self.client(response)
        state = {'run_id': RUN_ID, 'execution_token': 'new', 'user_id': 7, 'pending_article_id': 42,
                 'draft_html': '<p>修改版</p>', 'draft_hash': 'newhash', 'approved_base_hash': 'oldhash',
                 'target_draft': {'revision_id': '5', 'lock_version': 3}}
        with patch.object(draft_gateway.httpx, 'AsyncClient', return_value=client):
            self.assertEqual(await draft_gateway.save_approved_draft(state, draft), 42)
        body = client.post.call_args.kwargs['json']
        self.assertEqual(body['expectedLockVersion'], 3)
        self.assertEqual((body['draftHash'], body['baseDraftHash'], body['expectedRevisionId']), ('newhash', 'oldhash', '5'))

    async def test_gateway_conflict_never_reloads_lock_and_retries(self):
        response = httpx.Response(409, json={'message': '草稿已变化'}, request=httpx.Request('POST', 'http://test'))
        client = self.client(response)
        state = {'run_id': RUN_ID, 'execution_token': 'new', 'user_id': 7, 'pending_article_id': 42,
                 'draft_html': '<p>旧稿</p>', 'draft_hash': 'approved',
                 'target_draft': {'revision_id': '5', 'lock_version': 3}}
        with patch.object(draft_gateway.httpx, 'AsyncClient', return_value=client):
            with self.assertRaisesRegex(draft_gateway.DraftConflict, '本次未覆盖原文'):
                await draft_gateway.save_approved_draft(state, DraftOutput(title='旧稿', summary='', content='旧稿'))
        client.post.assert_awaited_once()
        client.get.assert_not_awaited()
