"""Real graph streaming: source-free text is live; audited text stays private."""
import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
os.environ['AGENT_SERVICE_KEY'] = 'offline-service-key-32-bytes-long!!'

import asyncio
import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from app import main
from app.graph import builder, main_agent as agent
from app.graph.state_factory import create_initial_state
from app.models.evidence_assessment import EvidenceAssessment
from app.services.answer_stream import DirectAnswerStream, can_stream_direct_answer
from fakes import repository, RUN_ID


def event(args='', name=None, rid='one', node='main_agent', allowed=True, content=''):
    return {'event': 'on_chat_model_stream', 'run_id': rid,
            'metadata': {'langgraph_node': node, 'public_answer_stream': allowed},
            'data': {'chunk': AIMessageChunk(content=content, tool_call_chunks=[
                {'name': name, 'args': args, 'index': 0, 'id': None}] if args or name else [])}}


def arguments(reply, **changes):
    return json.dumps(agent.MainDecision(action='answer', reply=reply, **changes).model_dump(), ensure_ascii=False)


class DirectStreamTests(unittest.TestCase):
    def test_eligibility_uses_backend_state_and_only_first_direct_round(self):
        state = create_initial_state(7, 'RAG是什么', [])
        self.assertTrue(can_stream_direct_answer(state))
        for key, value in [('main_round', 1), ('correction_count', 1),
                           ('task_results', {'a': {'status': 'failed'}}),
                           ('article_context', {'content': 'article'}), ('origin_article_id', 42),
                           ('delivery_review', {'phase': 'repairing'}), ('memory_write_status', 'pending')]:
            with self.subTest(key=key):
                self.assertFalse(can_stream_direct_answer({**state, key: value}))
        self.assertTrue(can_stream_direct_answer({**state, 'history_messages': [{'role': 'user', 'content': '你好'}]}))
        # An unrelated new question need not buffer merely because a prior run
        # had sources; the explicit header still forbids selecting old results.
        self.assertTrue(can_stream_direct_answer({**state, 'previous_run': {'reusable_results': {'a': {}}}}))

    def test_explicit_headers_and_backend_metadata_are_required(self):
        for args in ['{"action":"answer","reply":"private"}',
                     arguments('private', evidence_assessment=EvidenceAssessment(
                         selected_ids=[], adequacy='none', reason='缺资料')),
                     arguments('private', answer_dependencies=['source']),
                     arguments('private', reuse_previous_results=['source']),
                     arguments('private', constraint_overrides=['constraint'])]:
            with self.subTest(args=args):
                self.assertEqual(DirectAnswerStream().consume(event(args, 'MainDecision')), [])
        for e in [event(arguments('private'), 'MainDecision', allowed=False),
                  event(arguments('private'), 'MainDecision', node='draft_generate'),
                  event(arguments('private'), 'CitationRepair'), event(content='private reasoning')]:
            self.assertEqual(DirectAnswerStream().consume(e), [])

    def test_json_fragments_preserve_unicode_newlines_and_do_not_repeat_text(self):
        stream = DirectAnswerStream(min_interval=0)
        text = '中文🙂\nC:\\new\\file'
        args = arguments(text)
        cut = args.index('中文') + 2
        first = stream.consume(event(args[:cut], 'MainDecision'))
        self.assertEqual(first, [{'type': 'start', 'mode': 'direct'}, {'type': 'delta', 'seq': 0, 'content': '中文'}])
        rest = stream.consume(event(args[cut:]))
        self.assertEqual(''.join(x['content'] for x in [*first, *rest] if x['type'] == 'delta'), text)
        self.assertEqual(stream.finish(text), [{'type': 'end', 'chunks': 2}])
        self.assertEqual(stream.consume(event(arguments('replacement'), 'MainDecision', rid='retry')), [])

    def test_throttled_tail_flushes_at_model_end(self):
        stream = DirectAnswerStream(min_interval=999)
        args = arguments('first tail')
        cut = args.index('first') + len('first')
        stream.consume(event(args[:cut], 'MainDecision'))
        self.assertEqual(stream.consume(event(args[cut:])), [])
        end = {'event': 'on_chat_model_end', 'run_id': 'one',
               'metadata': {'langgraph_node': 'main_agent', 'public_answer_stream': True}}
        self.assertEqual(stream.consume(end), [{'type': 'delta', 'seq': 1, 'content': ' tail'}])
        self.assertEqual(stream.finish('first tail\nfooter'), [
            {'type': 'delta', 'seq': 2, 'content': '\nfooter'}, {'type': 'end', 'chunks': 3}])

    def test_provider_alphabetic_order_uses_wire_alias_and_keeps_state_reply_name(self):
        decision = agent.MainDecision(action='answer', reply='实时正文')
        wire = decision.model_dump(by_alias=True)
        self.assertIn('user_reply', wire)
        self.assertNotIn('reply', wire)
        self.assertEqual(sorted(wire)[-1], 'user_reply')
        self.assertEqual(agent.MainDecision.model_validate(wire).model_dump()['reply'], '实时正文')
        frames = DirectAnswerStream().consume(event(json.dumps(wire, sort_keys=True, ensure_ascii=False), 'MainDecision'))
        self.assertEqual(frames[-1]['content'], '实时正文')

    def test_unknown_references_and_false_execution_claims_are_not_streamed(self):
        for text in ['幻觉引用 [missing:1]', '文章已经保存到草稿箱', '已经记住了', '已经完成联网搜索']:
            with self.subTest(text=text):
                self.assertEqual(DirectAnswerStream().consume(event(arguments(text), 'MainDecision')), [])


class GraphDirectStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_or_superseded_executor_cannot_publish_new_text(self):
        from fastapi import HTTPException
        repo = repository()
        repo.assert_executor.side_effect = HTTPException(409, 'cancelled')
        repo.get.return_value = None
        service = SimpleNamespace(repository=repo, finish=AsyncMock())
        class Graph:
            async def astream_events(self, *args, **kwargs):
                yield event(arguments('不得发布'), 'MainDecision')
        config = {'configurable': {'run_id': RUN_ID, 'execution_token': 'old'}}
        with patch.object(main, 'run_service', service):
            frames = [f async for f in main._stream_source(Graph(), {}, 11, 7, config)]
        self.assertFalse(any('__ANSWER__:' in f or '不得发布' in f for f in frames))
        service.finish.assert_not_awaited()
        repo.assert_executor.assert_awaited_once_with(RUN_ID, 'old')

    async def collect_live(self, *, sourced=False):
        release, started, visible = asyncio.Event(), asyncio.Event(), asyncio.Event()
        text = '第一段第二段' + (' [source:1]' if sourced else '')
        decision = agent.MainDecision(action='answer', reply=text,
            **({'answer_dependencies': ['source'], 'evidence_assessment': EvidenceAssessment(
                selected_ids=['source:1'], adequacy='sufficient', reason='资料支持')} if sourced else {}))
        args = json.dumps(decision.model_dump(), ensure_ascii=False)
        cut = args.index('第一段') + len('第一段')
        model = ChatOpenAI(model='offline', api_key='offline-test')
        calls = []
        async def model_stream(self, messages, **kwargs):
            calls.append(messages)
            yield ChatGenerationChunk(message=AIMessageChunk(content='', tool_call_chunks=[
                {'name': 'MainDecision', 'args': args[:cut], 'id': 'call-1', 'index': 0}]))
            started.set()
            await release.wait()
            yield ChatGenerationChunk(message=AIMessageChunk(content='', tool_call_chunks=[
                {'name': None, 'args': args[cut:], 'id': None, 'index': 0}]))
        service = SimpleNamespace(repository=repository(), finish=AsyncMock(return_value={
            'reply': text, 'articles': [], 'citations': [], 'interrupted': None,
            'cancelled': False, 'draft_article_id': None}))
        config = {'configurable': {'thread_id': 'direct-stream-' + str(sourced), 'run_id': RUN_ID, 'execution_token': 't'}}
        state = create_initial_state(7, '解释一个概念', [])
        if sourced:
            state.update(main_round=1, task_results={'source': {'status': 'succeeded', 'kind': 'search',
                'actor': 'main', 'retrieval_target': 'knowledge', 'result': 'source text',
                'citations': [{'id': 'source:1', 'articleId': '42', 'excerpt': 'source text'}],
                'article_cards': [], 'citation_contents': {'source:1': 'source text'}}})
        review = AsyncMock(return_value=[])
        with ExitStack() as stack:
            stack.enter_context(patch.object(ChatOpenAI, '_astream', model_stream))
            stack.enter_context(patch.object(agent, 'get_llm', return_value=model))
            stack.enter_context(patch.object(main, 'run_service', service))
            stack.enter_context(patch('app.services.grounding.review_text', review))
            stack.enter_context(patch('app.graph.staged_runtime.verify_public_evidence', AsyncMock()))
            graph = builder._build_graph().compile(checkpointer=InMemorySaver())
            source = main._stream_source(graph, state, 11, 7, config)
            frames = []
            async def collect():
                async for frame in source:
                    frames.append(frame)
                    if '第一段' in frame:
                        visible.set()
            collector = asyncio.create_task(collect())
            try:
                async with asyncio.timeout(5):
                    await started.wait()
                    if not sourced:
                        await visible.wait()
                service.finish.assert_not_awaited()
                self.assertTrue(any('__AGENT_EVENT__:' in f for f in frames))
                self.assertEqual(any('第一段' in f for f in frames), not sourced)
                self.assertFalse(any('__REPLY__:' in f for f in frames))
                release.set()
                await asyncio.wait_for(collector, 5)
            finally:
                release.set()
                if not collector.done():
                    collector.cancel()
                await asyncio.gather(collector, return_exceptions=True)
                await source.aclose()
        service.finish.assert_awaited_once()
        self.assertEqual(len(calls), 1, 'streaming must not add a model call')
        self.assertEqual(review.await_count, int(sourced))
        answers = [json.loads(f.removeprefix('data:__ANSWER__:').strip()) for f in frames if f.startswith('data:__ANSWER__:')]
        self.assertEqual(sum(e['type'] == 'start' for e in answers), 1, 'settlement must not clear live text')
        self.assertEqual(''.join(e['content'] for e in answers if e['type'] == 'delta'), text)
        self.assertEqual(answers[-1], {'type': 'end', 'chunks': sum(e['type'] == 'delta' for e in answers)})
        self.assertTrue(any('__REPLY__:' in f and text in f for f in frames))
        self.assertFalse(any('__PREVIEW__:' in f for f in frames))

    async def test_plain_answer_is_visible_while_same_model_call_is_still_generating(self):
        await self.collect_live()

    async def test_sourced_answer_is_private_until_gate_and_settlement(self):
        await self.collect_live(sourced=True)
