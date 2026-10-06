import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
os.environ['AGENT_SERVICE_KEY'] = 'offline-service-key-32-bytes-long!!'
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from app.services.answer_preview import AnswerPreview
from app.graph import builder, main_agent as agent
from app.graph.state_factory import create_initial_state
from app import main
from fakes import repository, RUN_ID


def event(args='', name=None, rid='one', node='main_agent', content='', **metadata):
    return {'event': 'on_chat_model_stream', 'run_id': rid,
            'metadata': {'langgraph_node': node, **metadata},
            'data': {'chunk': AIMessageChunk(content=content, tool_call_chunks=[
                {'name': name, 'args': args, 'index': 0, 'id': None}] if args or name else [])}}


class PreviewTests(unittest.TestCase):
    def test_split_json_only_releases_answer_reply_and_preserves_escapes(self):
        preview = AnswerPreview(min_interval=0)
        self.assertIsNone(preview.consume(event('{"action":"ans', 'MainDecision')))
        first = preview.consume(event('wer","reply":"中文🙂'))
        self.assertEqual(first['content'], '中文🙂')
        second = preview.consume(event('\\nC:\\\\new","memory_changes":[{"secret":"hidden"}]}'))
        self.assertEqual(second['content'], '\nC:\\new')
        retry = preview.consume(event('{"action":"answer","reply":"修正后的正文"}', 'MainDecision', rid='retry'))
        self.assertEqual(retry['type'], 'replace')
        self.assertEqual(retry['content'], '修正后的正文')

    def test_routing_tools_structurization_and_reasoning_stay_private(self):
        for node, name, args in [('main_agent', 'MainDecision', '{"action":"retrieve","reply":"private"}'),
                                ('search_worker', 'MainDecision', '{"action":"answer","reply":"private"}'),
                                ('main_agent', 'CitationRepair', '{"reply":"private"}')]:
            self.assertIsNone(AnswerPreview().consume(event(args, name, node=node, content='reasoning')))
        self.assertIsNone(AnswerPreview().consume(event(content='private reasoning')))
        draft = AnswerPreview(min_interval=0)
        self.assertEqual(draft.consume(event(node='draft_generate', content='# 标题', public_preview='draft'))['type'], 'replace')
        self.assertEqual(draft.consume(event(node='draft_generate', content='正文', public_preview='draft'))['type'], 'delta')

    def test_coalescing_flushes_tail_at_model_end(self):
        preview=AnswerPreview(min_interval=10)
        self.assertEqual(preview.consume(event('{"action":"answer","reply":"开头', 'MainDecision'))['content'],'开头')
        self.assertIsNone(preview.consume(event('尾部"}')))
        self.assertEqual(preview.consume({'event':'on_chat_model_end','run_id':'one'})['content'],'尾部')


class LiveGraphPreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_structured_model_call_streams_before_completion_and_commits_after_gate(self):
        release = asyncio.Event()
        model = ChatOpenAI(model='offline', api_key='offline-test')
        async def model_stream(self, messages, **kwargs):
            yield ChatGenerationChunk(message=AIMessageChunk(content='', tool_call_chunks=[
                {'name':'MainDecision','args':'{"action":"answer","reply":"第一段', 'id':'call-1','index':0}]))
            await release.wait()
            yield ChatGenerationChunk(message=AIMessageChunk(content='', tool_call_chunks=[
                {'name':None,'args':'第二段"}', 'id':None,'index':0}]))
        service = SimpleNamespace(repository=repository(), finish=AsyncMock(return_value={
            'reply':'第一段第二段','articles':[],'citations':[],'interrupted':None,'cancelled':False,'draft_article_id':None}))
        config={'configurable':{'thread_id':'live-preview','run_id':RUN_ID,'execution_token':'t'}}
        with patch.object(ChatOpenAI,'_astream',model_stream), patch.object(agent,'get_llm',return_value=model), patch.object(main,'run_service',service):
            graph=builder._build_graph().compile(checkpointer=InMemorySaver())
            source=main._stream_source(graph,create_initial_state(7,'解释一个概念',[]),11,7,config)
            frames=[]
            try:
                async with asyncio.timeout(5):
                    while True:
                        frame=await anext(source);frames.append(frame)
                        if '__PREVIEW__:' in frame:break
                service.finish.assert_not_awaited()
                self.assertIn('第一段',frames[-1])
                self.assertNotIn('__REPLY__:', ''.join(frames))
                release.set()
                frames.extend([frame async for frame in source])
            finally:
                release.set();await source.aclose()
        service.finish.assert_awaited_once()
        previews=[json.loads(f.removeprefix('data:__PREVIEW__:').strip()) for f in frames if f.startswith('data:__PREVIEW__:')]
        self.assertEqual(''.join(p['content'] for p in previews),'第一段第二段')
        self.assertTrue(any('__REPLY__:' in f and '第一段第二段' in f for f in frames))
