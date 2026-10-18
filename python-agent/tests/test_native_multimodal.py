"""Native image delivery, ownership and budgeting; no external model calls."""
import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['AGENT_SERVICE_KEY'] = 'offline-service-key-32-bytes-long!!'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'

import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from PIL import Image
from langchain_core.messages import HumanMessage
from sqlalchemy import create_engine, text
from databases.backends.common.records import Row as DatabaseRow

from app.config import settings, get_llm
from app.graph.main_agent import MainDecision, build_main_messages
from app.graph.state_factory import create_initial_state
from app.services import multimodal as mm
from app.services.conversation import ConversationService
from app.services.run_service import RunService
from app.utils.context_budget import (ContextBudgetExceeded, ensure_request_budget,
    history_as_data, message_tokens)
from fakes import repository


def image_parts(messages):
    return [part for message in messages if isinstance(message.content, list)
            for part in message.content if part.get('type') == 'image_url']


class NativeImageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.setting = patch.object(settings, 'FILE_UPLOAD_PATH', str(self.root))
        self.setting.start()
        self.addCleanup(self.setting.stop)
        self.path = self.image('chart.bin')  # Actual bytes, not extension, determine MIME.

    def image(self, name, uid=7, fmt='PNG'):
        path = f'ai-chat/{uid}/{name}'
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (48, 32), (255, 0, 0)).save(target, format=fmt)
        return path

    def state(self, text='解释图片', paths=None, history=None):
        state = create_initial_state(7, text, history or [])
        state['user_image_paths'] = [self.path] if paths is None else paths
        return state

    def test_question_and_original_image_reach_main_without_a_caption(self):
        state = self.state()
        parts = build_main_messages(state)[-1].content
        self.assertEqual(parts[0], {'type': 'text', 'text': '解释图片'})
        image = parts[-1]['image_url']
        self.assertEqual(image['detail'], 'original')
        prefix, encoded = image['url'].split(',', 1)
        self.assertEqual(prefix, 'data:image/png;base64')
        self.assertEqual(base64.b64decode(encoded), (self.root / self.path).read_bytes())
        self.assertNotIn('base64', json.dumps(state))
        self.assertEqual(state['memory_source_message'], '解释图片')

    def test_image_only_has_an_explicit_question_and_text_turn_stays_plain(self):
        self.assertIn('上传的图片', build_main_messages(self.state(''))[-1].content[0]['text'])
        state = self.state('普通问题', paths=[])
        self.assertEqual(build_main_messages(state)[-1].content, '普通问题')
        self.assertEqual(create_initial_state(7, '下一轮', [])['user_image_paths'], [])

    def test_main_knows_web_is_text_search_and_receives_actual_server_switch(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled), patch.object(settings, 'AGENT_WEB_SEARCH_ENABLED', enabled):
                context = json.loads(build_main_messages(self.state())[1].content)
            self.assertEqual(context['retrieval_policy']['web_search_enabled'], enabled)
            self.assertEqual(context['retrieval_policy']['web_search_mode'], 'text_query')
            self.assertFalse(context['retrieval_policy']['reverse_image_search'])

    def test_recent_history_is_bounded_by_occurrences_even_for_repeated_files(self):
        history = [{'message_id': i, 'role': 'user', 'content': f'问题{i}', 'image_paths': [self.path]}
                   for i in range(8)]
        state = self.state(history=history)
        messages = build_main_messages(state)
        self.assertEqual(len(image_parts(messages)), 5)  # 4 history + 1 current.
        payload = json.loads(messages[1].content)
        self.assertEqual([m['attached_image_count'] for m in payload['history']], [0]*4+[1]*4)
        self.assertNotIn('ai-chat/', messages[1].content)
        self.assertNotIn('base64', messages[1].content)
        self.assertIn('不能', payload['history'][0]['image_notice'])

    def test_current_image_has_priority_over_history_transport_budget(self):
        history = [{'message_id': 1, 'role': 'user', 'content': '旧问题', 'image_paths': [self.path]*4}]
        state = self.state(history=history)
        part = mm.image_part(self.path, 7)
        size = len(part['image_url']['url'])
        with patch.object(mm, 'MAX_INLINE_BYTES', size * 3 // 2 + 1):
            messages = build_main_messages(state)
        self.assertLessEqual(sum(len(p['image_url']['url']) for p in image_parts(messages)), size*2+2)
        self.assertEqual(messages[-1].content[-1], part)

    def test_missing_history_is_explicit_and_is_not_invented(self):
        missing = 'ai-chat/7/missing.png'
        state = self.state(paths=[], history=[{'role':'user','content':'图上呢','image_paths':[missing]}])
        messages = build_main_messages(state)
        self.assertEqual(image_parts(messages), [])
        self.assertIn('不能推测', json.dumps([m.content for m in messages], ensure_ascii=False))
        self.assertEqual(json.loads(messages[1].content)['history'][0]['attached_image_count'], 0)

    def test_current_invalid_foreign_traversal_and_unsupported_images_fail(self):
        foreign = self.image('private.png', uid=8)
        text = self.root / 'ai-chat/7/fake.png'
        text.write_text('not an image', encoding='utf-8')
        bmp = self.image('bitmap.bmp', fmt='BMP')
        for path in [foreign, '../secret.png', 'ai-chat/7/../8/private.png',
                     'ai-chat/7/missing.png', 'ai-chat/7/fake.png', bmp]:
            with self.subTest(path=path), self.assertRaises(HTTPException):
                mm.validate_current_images([path], 7)
        with self.assertRaises(HTTPException):
            mm.validate_current_images([self.path]*5, 7)
        with patch.object(mm, 'MAX_IMAGE_BYTES', 10), self.assertRaises(HTTPException):
            mm.validate_current_images([self.path], 7)
        with patch.object(mm, 'MAX_INLINE_BYTES', 10), self.assertRaises(HTTPException):
            mm.validate_current_images([self.path], 7)

    def test_supported_formats_are_sent_with_actual_mime(self):
        for fmt, mime in mm.FORMATS.items():
            with self.subTest(fmt=fmt):
                part = mm.image_part(self.image(f'format-{fmt}.data', fmt=fmt), 7)
                self.assertTrue(part['image_url']['url'].startswith(f'data:{mime};base64,'))

    def test_base64_does_not_inflate_text_token_or_character_budgets(self):
        def message(size):
            return HumanMessage(content=[{'type':'text','text':'看图'},
                {'type':'image_url','image_url':{'url':'data:image/png;base64,'+'A'*size}}])
        self.assertEqual(message_tokens(message(100)), message_tokens(message(4_000_000)))
        self.assertGreaterEqual(message_tokens(message(100)), mm.IMAGE_TOKEN_BUDGET)
        with patch.object(settings, 'MAIN_CONTEXT_MAX_CHARS', 300):
            ensure_request_budget([message(4_000_000)])
            with self.assertRaises(ContextBudgetExceeded):
                ensure_request_budget([HumanMessage(content='x'*400)])

    def test_text_only_helpers_disclose_missing_visuals_without_sending_file_paths(self):
        encoded = history_as_data([{'role':'user','content':'这张图','image_paths':[self.path]}])
        item = json.loads(encoded)['history'][0]
        self.assertEqual(item['image_count'], 1)
        self.assertNotIn('ai-chat/', encoded)
        self.assertIn('不能猜测', item['image_notice'])

    async def test_history_loader_preserves_owned_references_from_storage(self):
        # Use an actual SQLAlchemy Row as databases' MySQL adapter does, not a
        # dict stand-in that silently supplies unsupported methods like get().
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        with engine.connect() as connection:
            def adapter_row(mid, role, content):
                result = connection.execute(text('SELECT :mid AS message_id, :role AS role, :content AS content, :images AS image_paths'),
                    {'mid':mid,'role':role,'content':content,'images':json.dumps([self.path])})
                values = tuple(result.first())
                metadata = result._metadata
                # Same Row adapter construction as databases.backends.mysql.
                return DatabaseRow(metadata, metadata._processors, metadata._keymap, values)
            user = adapter_row(1, 'user', '看图')
            assistant = adapter_row(2, 'assistant', '答复')
        with self.assertRaises(AttributeError):
            user.get('image_paths')
        database = SimpleNamespace(fetch_one=AsyncMock(return_value=None), fetch_all=AsyncMock(return_value=[
            SimpleNamespace(_mapping=user), SimpleNamespace(_mapping=assistant)]))
        with patch('app.services.conversation.db', database):
            service = ConversationService()
            history = await service._load_context(11)
        self.assertEqual(history[0]['image_paths'], [self.path])
        self.assertNotIn('image_paths', history[1])
        self.assertIn('image_paths', database.fetch_all.call_args.args[0])
        self.assertIn('full:v4', service._llm_cache_key(11))

    async def test_compaction_records_an_upload_without_claiming_to_see_the_image(self):
        history = [{'role':'user','content':'解释图片','image_paths':[self.path]},
                   {'role':'assistant','content':'之前的回答'}, {'role':'user','content':'继续'}]
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content='用户上传过一张图片，要求解释。')))
        with patch('app.services.conversation.get_llm', return_value=model):
            result = await ConversationService().compact_history(None, history, 2)
        prompt = model.ainvoke.call_args.args[0][0].content
        self.assertIn('用户上传了1张图片', prompt)
        self.assertIn('本摘要未载入原图', prompt)
        self.assertNotIn(self.path, prompt)
        self.assertEqual(result['history'][-1], history[-1])

    async def test_run_records_raw_question_and_refs_and_never_calls_a_caption_model(self):
        conv = SimpleNamespace(resolve_origin=AsyncMock(return_value=None),
            get_context_for_llm=AsyncMock(return_value=[]), add_message=AsyncMock(return_value=123))
        service = RunService(conv, SimpleNamespace(load_context=AsyncMock(return_value={})),
            repository(), history=SimpleNamespace(previous=AsyncMock(return_value=({}, {}))))
        request = SimpleNamespace(conversation_id=11, request_id='native-image', user_id=7,
            origin_article_id=None, message='解释图片', image_paths=[self.path])
        with patch('app.config.get_llm') as model:
            _, _, state = await service.prepare_chat(request, None)
        model.assert_not_called()
        self.assertEqual(state['user_message'], '解释图片')
        self.assertEqual(state['memory_source_message'], '解释图片')
        self.assertEqual(state['user_image_paths'], [self.path])
        self.assertEqual(conv.add_message.call_args.kwargs['image_paths'], [self.path])
        self.assertNotIn('base64', json.dumps(state))

    async def test_real_sdk_serializes_native_parts_and_structured_tool_together(self):
        captured = []
        def respond(request):
            captured.append(json.loads(request.content))
            decision = MainDecision(action='answer', reply='图片是红色的。')
            return httpx.Response(200, json={'id':'offline','object':'chat.completion','created':1,
                'model':'deepseek-flash','choices':[{'index':0,'finish_reason':'tool_calls','message':{
                    'role':'assistant','content':None,'tool_calls':[{'id':'call_1','type':'function',
                        'function':{'name':'MainDecision','arguments':decision.model_dump_json(by_alias=True)}}]}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch.object(settings, 'DEEPSEEK_API_KEY', 'offline-test'), \
                 patch.object(settings, 'DEEPSEEK_BASE_URL', 'https://offline.test/v1'):
                model = get_llm(http_async_client=client, max_retries=0)
                result = await model.with_structured_output(MainDecision, method='function_calling').ainvoke(
                    build_main_messages(self.state()))
        self.assertEqual(result.reply, '图片是红色的。')
        self.assertEqual(captured[0]['model'], 'deepseek-flash')
        self.assertEqual(captured[0]['messages'][-1]['content'][-1]['type'], 'image_url')
        self.assertEqual(captured[0]['tools'][0]['function']['name'], 'MainDecision')
        self.assertEqual(captured[0]['thinking'], {'type':'disabled'})


if __name__ == '__main__':
    unittest.main()
