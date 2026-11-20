import asyncio
import json
import unittest
import httpx
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.graph.main_agent import (ActionContractError, BrowserDecision, MainDecision, decide_main_action,
                                  preflight_action, validate_action)
from app.graph.state_factory import create_initial_state
from app.security.delegation import current_identity
from app.security.stream_sessions import sessions
from app.services.browser_control import BrowserControl, browser_tool, locate


IDENTITY = {'user_id': 7, 'sid': 'a' * 64, 'version': 1}
ORIGIN = 'chrome-extension://' + 'a' * 32


class VisionModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_deepseek_returns_coordinates_without_spending_budget_on_reasoning(self):
        captured = []
        def respond(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop',
                'message': {'content': '{"x": 0.4, "y": 0.5}'}}]})
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with (patch.object(settings, 'BROWSER_VISION_URL', 'https://vision.test/chat/completions'),
              patch.object(settings, 'BROWSER_VISION_MODEL', 'deepseek-flash'),
              patch('app.services.browser_control.httpx.AsyncClient', return_value=client)):
            point = await locate('data:image/jpeg;base64,AAAA', '汉族选项')
        self.assertEqual(point, {'x': .4, 'y': .5})
        self.assertEqual(captured[0]['thinking'], {'type': 'disabled'})
        self.assertEqual(captured[0]['response_format'], {'type': 'json_object'})
        self.assertEqual(captured[0]['messages'][1]['content'][1]['type'], 'image_url')

    async def test_invalid_or_truncated_coordinates_never_reach_the_browser(self):
        for content, finish in [('{"x": true, "y": 0.5}', 'stop'),
                                ('{"x": 1.2, "y": 0.5}', 'stop'),
                                ('{"x": 0.4, "y": 0.5}', 'length'),
                                ('{}', 'stop'), ('not json', 'stop')]:
            with self.subTest(content=content, finish=finish):
                def respond(request):
                    self.assertNotIn('thinking', json.loads(request.content))
                    return httpx.Response(200, json={'choices': [{'finish_reason': finish,
                        'message': {'content': content}}]})
                client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
                with (patch.object(settings, 'BROWSER_VISION_URL', 'https://vision.test/chat/completions'),
                      patch.object(settings, 'BROWSER_VISION_MODEL', 'another-vision-model'),
                      patch('app.services.browser_control.httpx.AsyncClient', return_value=client)):
                    self.assertIsNone(await locate('data:image/jpeg;base64,AAAA', '发送'))


class Socket:
    def __init__(self, origin=ORIGIN):
        self.headers = {'origin': origin}
        self.sent = asyncio.Queue()
        self.incoming = asyncio.Queue()
        self.closed = None

    async def accept(self):
        pass

    async def close(self, code):
        self.closed = code

    async def send_json(self, value):
        self.sent.put_nowait(value)

    async def receive_text(self):
        value = await self.incoming.get()
        if value is None:
            raise WebSocketDisconnect()
        return json.dumps(value)


class BrowserControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.broker = BrowserControl()
        self.identity = current_identity.set(IDENTITY)
        self.addCleanup(current_identity.reset, self.identity)

    async def test_ticket_is_single_use_and_observation_stays_in_memory(self):
        @asynccontextmanager
        async def subscribe(identity):
            self.assertEqual(identity, IDENTITY)
            yield asyncio.Event()

        with (patch.object(settings, 'BROWSER_EXTENSION_ID', 'a' * 32),
                patch.object(sessions, 'subscribe', subscribe),
                patch('app.services.browser_control.browser', self.broker),
                patch('app.graph.staged_runtime.assert_run', new_callable=AsyncMock)):
            pending = self.broker.prepare(IDENTITY, 10)
            hello = {'type': 'hello', 'version': 1, 'ticket': pending['ticket']}
            invalid = Socket('https://example.test')
            await self.broker.socket(invalid)
            self.assertEqual(invalid.closed, 1008)
            socket = Socket()
            socket.incoming.put_nowait(hello)
            connected = asyncio.create_task(self.broker.socket(socket))
            self.assertEqual((await asyncio.wait_for(socket.sent.get(), 1))['type'], 'ready')
            replay = Socket()
            replay.incoming.put_nowait(hello)
            await self.broker.socket(replay)
            self.assertEqual(replay.closed, 1008)
            with self.assertRaises(HTTPException):
                self.broker.bind(IDENTITY, pending['sessionId'], 11, 'r1')
            with self.assertRaises(HTTPException):
                self.broker.bind({**IDENTITY, 'version': 2}, pending['sessionId'], 10, 'r1')
            self.broker.bind(IDENTITY, pending['sessionId'], 10, 'r1')
            state = {'browser_session_id': pending['sessionId'], 'conversation_id': 10,
                     'user_id': 7, 'run_id': 'r1', 'current_task': {
                         'tool_name': 'browser_observe', 'tool_args': {}, 'task_id': 'read'}}
            tool = asyncio.create_task(browser_tool(state))
            command = await asyncio.wait_for(socket.sent.get(), 1)
            self.assertEqual(command['action'], {'kind': 'observe'})
            socket.incoming.put_nowait({'type': 'result', 'actionId': command['actionId'],
                                       'status': 'ok', 'snapshot': {'id': 'a', 'text': 'page-only body'}})
            result = await asyncio.wait_for(tool, 1)
            self.assertNotIn('page-only body', result['result'])
            link = self.broker.for_run(state)
            self.assertIn('page-only body', link.results['read'])
            self.assertIsNone(self.broker.for_run({**state, 'run_id': 'r2'}))
            self.assertIsNone(self.broker.for_run({**state, 'conversation_id': 11}))
            link.close()
            self.assertEqual(link.results, {})
            connected.cancel()
            await asyncio.gather(connected, return_exceptions=True)

    async def test_press_uses_session_authorization_and_reports_click(self):
        grant = self.broker.prepare(IDENTITY, 10)
        link = self.broker.owned(IDENTITY)
        link.socket = SimpleNamespace()
        self.broker.bind(IDENTITY, grant['sessionId'], 10, 'r1')
        link.snapshot = {'id': 'fresh', 'origin': 'https://example.test',
                         'buttons': [{'id': 'b0', 'label': '发送'}]}
        state = {'browser_session_id': link.id, 'conversation_id': 10, 'user_id': 7, 'run_id': 'r1',
                 'current_task': {'tool_name': 'browser_press', 'task_id': 'press',
                                  'tool_args': {'snapshotId': 'fresh', 'elementId': 'b0'}}}
        with (patch('app.services.browser_control.browser', self.broker),
              patch('app.graph.staged_runtime.assert_run', new_callable=AsyncMock),
              patch('app.services.browser_control.send_action', new_callable=AsyncMock) as send):
            send.return_value = SimpleNamespace(status='clicked', snapshot=None)
            result = await browser_tool(state)
        self.assertIn('尚未读到页面反馈', result['result'])
        self.assertEqual(result['browser_outcome'], 'clicked')
        send.assert_awaited_once_with(link, {'kind': 'press', 'snapshotId': 'fresh', 'elementId': 'b0'})

    async def test_dropdown_does_not_toggle_twice_and_refreshes_stale_option(self):
        grant = self.broker.prepare(IDENTITY, 10)
        link = self.broker.owned(IDENTITY)
        link.socket = SimpleNamespace()
        self.broker.bind(IDENTITY, grant['sessionId'], 10, 'r1')
        trigger = {'id': 'b0', 'label': '民族', 'type': 'combobox'}
        option = {'id': 'b1', 'label': '汉族', 'type': 'option'}
        link.snapshot = {'id': 'initial', 'tabId': 1, 'buttons': [trigger]}
        opened = {**link.snapshot, 'id': 'opened', 'buttons': [trigger, option]}
        refreshed = {**opened, 'id': 'refreshed', 'buttons': [trigger, {**option, 'id': 'b2'}]}
        state = {'browser_session_id': link.id, 'conversation_id': 10, 'user_id': 7, 'run_id': 'r1'}

        async def press(task_id, snapshot_id, element_id):
            return await browser_tool({**state, 'current_task': {
                'tool_name': 'browser_press', 'task_id': task_id,
                'tool_args': {'snapshotId': snapshot_id, 'elementId': element_id}}})

        with (patch('app.services.browser_control.browser', self.broker),
              patch('app.graph.staged_runtime.assert_run', new_callable=AsyncMock),
              patch('app.services.browser_control.send_action', new_callable=AsyncMock) as send):
            send.side_effect = [SimpleNamespace(status='ok', snapshot=opened),
                                SimpleNamespace(status='stale_snapshot', snapshot=refreshed),
                                SimpleNamespace(status='ok', snapshot={**opened, 'id': 'done', 'buttons': [trigger]})]
            self.assertEqual((await press('open', 'initial', 'b0'))['browser_outcome'], 'dropdown_opened')
            self.assertEqual((await press('repeat', 'opened', 'b0'))['browser_outcome'], 'dropdown_repeated')
            retry = await press('option', 'opened', 'b1')
            self.assertEqual((retry['status'], retry['browser_outcome']), ('succeeded', 'page_refreshed'))
            self.assertEqual(link.snapshot['id'], 'refreshed')
            self.assertEqual((await press('option_retry', 'refreshed', 'b2'))['browser_outcome'], 'option_clicked')
            self.assertEqual(send.await_count, 3)

    async def test_enabled_vision_captures_and_clicks_without_waiting_for_approval(self):
        grant = self.broker.prepare(IDENTITY, 10)
        link = self.broker.owned(IDENTITY)
        link.socket = SimpleNamespace()
        link.vision = True
        self.broker.bind(IDENTITY, grant['sessionId'], 10, 'r1')
        state = {'browser_session_id': link.id, 'conversation_id': 10, 'user_id': 7, 'run_id': 'r1',
                 'current_task': {'tool_name': 'browser_visual_click', 'task_id': 'click',
                                  'tool_args': {'target': '展开目录'}}}
        point = {'x': 0.4, 'y': 0.5}
        with (patch('app.services.browser_control.browser', self.broker),
              patch.object(settings, 'BROWSER_VISION_URL', 'https://example.test'),
              patch.object(settings, 'BROWSER_VISION_MODEL', 'vision'),
              patch('app.graph.staged_runtime.assert_run', new_callable=AsyncMock),
              patch('app.services.browser_control.locate', new=AsyncMock(return_value=point)),
              patch('app.services.browser_control.send_action', new_callable=AsyncMock) as send):
            send.side_effect = [SimpleNamespace(status='ok', image='data:image/jpeg;base64,AAAA', shotId='shot'),
                                SimpleNamespace(status='ok', snapshot=None)]
            result = await browser_tool(state)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual([call.args[1] for call in send.await_args_list],
                         [{'kind': 'capture'}, {'kind': 'click_at', 'shotId': 'shot', **point}])

    async def test_visual_click_keeps_new_observation_and_follows_opened_tab(self):
        for status, expected in (('ok', 'clicked'), ('opened_tab', 'opened_tab')):
            with self.subTest(status=status):
                grant = self.broker.prepare(IDENTITY, 10)
                link = self.broker.owned(IDENTITY)
                link.socket = SimpleNamespace()
                link.vision = True
                self.broker.bind(IDENTITY, grant['sessionId'], 10, 'r1')
                link.snapshot = {'id': 'old', 'tabId': 1}
                link.filled_fields = [{'elementId': 'f0', 'label': '问题', 'text': '测试'}]
                snapshot = {'id': 'new', 'tabId': 2 if status == 'opened_tab' else 1,
                            'text': '页面已显示操作结果', 'buttons': []}
                state = {'browser_session_id': link.id, 'conversation_id': 10, 'user_id': 7, 'run_id': 'r1',
                         'current_task': {'tool_name': 'browser_visual_click', 'task_id': 'visual',
                                          'tool_args': {'target': '发送'}}}
                with (patch('app.services.browser_control.browser', self.broker),
                      patch.object(settings, 'BROWSER_VISION_URL', 'https://example.test'),
                      patch.object(settings, 'BROWSER_VISION_MODEL', 'vision'),
                      patch('app.graph.staged_runtime.assert_run', new_callable=AsyncMock),
                      patch('app.services.browser_control.locate', new=AsyncMock(return_value={'x': .5, 'y': .5})),
                      patch('app.services.browser_control.send_action', new_callable=AsyncMock) as send):
                    send.side_effect = [SimpleNamespace(status='ok', image='data:image/jpeg;base64,AAAA', shotId='shot'),
                                        SimpleNamespace(status=status, snapshot=snapshot)]
                    result = await browser_tool(state)
                self.assertEqual((result['status'], result['browser_outcome']), ('succeeded', expected))
                self.assertEqual(link.snapshot, snapshot)
                self.assertEqual(json.loads(link.results['visual'])['data'], snapshot)
                self.assertEqual(link.filled_fields, [])

    async def test_expired_session_cannot_fill_or_dispatch_an_action(self):
        from app.services.agent_events import publish_task_result
        grant = self.broker.prepare(IDENTITY, 10)
        link = self.broker.owned(IDENTITY)
        link.socket = SimpleNamespace()
        self.broker.bind(IDENTITY, grant['sessionId'], 10, 'r1')
        link.snapshot = {'id': 'initial', 'origin': 'https://example.test', 'fields': [{'id': 'f0', 'label': '问题'}]}
        state = {**create_initial_state(7, '发送问题', []), 'browser_session_id': link.id,
                 'conversation_id': 10, 'run_id': 'r1', 'action_task_ids': ['fill'],
                 'current_task': {'tool_name': 'browser_fill', 'task_id': 'fill',
                                  'tool_args': {'snapshotId': 'initial', 'fields': [{'elementId': 'f0', 'text': '测试'}]}}}
        link.close()
        with (patch('app.services.browser_control.browser', self.broker),
              patch('app.graph.staged_runtime.assert_run', new_callable=AsyncMock),
              patch('app.services.browser_control.send_action', new_callable=AsyncMock) as send):
            result = await browser_tool(state)
        send.assert_not_awaited()
        self.assertEqual(result['status'], 'tool_error')
        with patch('app.services.agent_events.publish_event', new_callable=AsyncMock) as publish:
            await publish_task_result('fill', result)
        self.assertIn('授权不可用', publish.await_args.args[0]['text'])

    async def test_repeat_fill_uses_fresh_snapshot_without_a_second_write(self):
        from app.graph.main_agent import decision_context
        grant = self.broker.prepare(IDENTITY, 10)
        link = self.broker.owned(IDENTITY)
        link.socket = SimpleNamespace()
        self.broker.bind(IDENTITY, grant['sessionId'], 10, 'r1')
        link.snapshot = {'id': 'initial', 'origin': 'https://example.test', 'fields': [{'id': 'f0', 'label': '问题'}]}
        fresh = {**link.snapshot, 'id': 'fresh', 'buttons': [{'id': 'b0', 'label': '发送'}]}
        state = {**create_initial_state(7, '发送问题', []), 'browser_session_id': link.id,
                 'conversation_id': 10, 'run_id': 'r1',
                 'current_task': {'tool_name': 'browser_fill', 'task_id': 'fill',
                                  'tool_args': {'snapshotId': 'initial', 'fields': [{'elementId': 'f0', 'text': '测试'}]}}}
        with (patch('app.services.browser_control.browser', self.broker),
              patch('app.graph.staged_runtime.assert_run', new_callable=AsyncMock),
              patch('app.services.browser_control.send_action', new=AsyncMock(
                  return_value=SimpleNamespace(status='ok', snapshot=fresh))) as send):
            result = await browser_tool(state)
            state['current_task']['tool_args']['snapshotId'] = 'fresh'
            repeated = await browser_tool(state)
            context = json.loads(decision_context(state))['browser_context']
        self.assertEqual(result['browser_outcome'], 'filled')
        self.assertEqual(repeated['browser_outcome'], 'already_filled')
        self.assertEqual(context['latest_page']['buttons'], fresh['buttons'])
        self.assertEqual(context['latest_page']['snapshotId'], 'fresh')
        send.assert_awaited_once()

    async def test_page_context_cannot_trigger_other_tools(self):
        decision = MainDecision(action='call_tool', tool_call={'name': 'web_search', 'args': {'query': 'text'}})
        with self.assertRaises(ActionContractError):
            preflight_action({'browser_session_id': 'session'}, decision, 1)

    async def test_keyboard_targets_fields_and_live_observations_survive_projection(self):
        from app.graph.main_agent import decision_context
        grant = self.broker.prepare(IDENTITY, 10)
        link = self.broker.owned(IDENTITY)
        link.socket = SimpleNamespace()
        self.broker.bind(IDENTITY, grant['sessionId'], 10, 'r1')
        link.snapshot = {'id': 'filled', 'fields': [{'id': 'f0', 'label': '消息'}], 'buttons': []}
        state = {**create_initial_state(7, '发给 DeepSeek：杭州最近天气', []),
                 'browser_session_id': link.id, 'conversation_id': 10, 'run_id': 'r1',
                 'current_task': {'tool_name': 'browser_keypress', 'task_id': 'send',
                     'tool_args': {'snapshotId': 'filled', 'elementId': 'f0', 'key': 'Enter'}}}
        fresh = {'id': 'sent', 'text': '问题已收到'}
        with (patch('app.services.browser_control.browser', self.broker),
              patch('app.graph.staged_runtime.assert_run', new_callable=AsyncMock),
              patch('app.services.browser_control.send_action', new=AsyncMock(
                  return_value=SimpleNamespace(status='ok', snapshot=fresh))) as send,
              patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1),
              patch.object(settings, 'CONTEXT_RESULT_ACCESS_ENABLED', True)):
            result = await browser_tool(state)
            self.assertEqual(result['browser_outcome'], 'key_pressed')
            self.assertEqual(send.await_args.args[1]['key'], 'Enter')
            state['task_results'] = {'send': {**result, 'tool_name': 'browser_keypress', 'kind': 'tool', 'actor': 'main'}}
            context = json.loads(decision_context(state))
            self.assertIn('问题已收到', context['successful_tasks']['send']['result'])
            state['current_task']['tool_args'].update(snapshotId='sent', elementId='missing')
            denied = await browser_tool(state)
            self.assertEqual(denied['browser_outcome'], 'target_unavailable')
            send.assert_awaited_once()

    async def test_tab_discovery_is_visible_and_does_not_repeat_before_opening(self):
        from app.graph.main_agent import decision_context
        grant = self.broker.prepare(IDENTITY, 10)
        link = self.broker.owned(IDENTITY)
        link.socket = SimpleNamespace()
        link.multi_tab = True
        self.broker.bind(IDENTITY, grant['sessionId'], 10, 'r1')
        state = {**create_initial_state(7, '让 DeepSeek 查询杭州天气', []),
                 'browser_session_id': link.id, 'conversation_id': 10, 'run_id': 'r1',
                 'current_task': {'tool_name': 'browser_tabs', 'task_id': 'tabs', 'tool_args': {}}}
        tabs = [{'id': 1, 'title': 'EasyJob', 'origin': 'http://localhost:3000'}]
        page = {'id': 'new', 'tabId': 2, 'fields': [], 'buttons': []}
        with (patch('app.services.browser_control.browser', self.broker),
              patch('app.graph.staged_runtime.assert_run', new_callable=AsyncMock),
              patch('app.services.browser_control.send_action', new=AsyncMock(side_effect=[
                  SimpleNamespace(status='ok', snapshot={'tabs': tabs}),
                  SimpleNamespace(status='ok', snapshot=page),
                  SimpleNamespace(status='ok', snapshot={'tabs': []})])) as send,
              patch.object(settings, 'CONTEXT_TOOL_INLINE_TOKENS', 1)):
            self.assertIsNone(json.loads(decision_context(state))['browser_context']['latest_tabs'])
            first = await browser_tool(state)
            repeated = await browser_tool(state)
            self.assertEqual(first['browser_outcome'], 'tabs')
            self.assertEqual(repeated['browser_outcome'], 'tabs_unchanged')
            send.assert_awaited_once()
            context = json.loads(decision_context(state))['browser_context']
            self.assertEqual(context['latest_tabs'], tabs)
            self.assertIsNone(context['latest_page'])
            state['current_task'] = {'tool_name': 'browser_open', 'task_id': 'open',
                                     'tool_args': {'url': 'https://chat.deepseek.com/'}}
            await browser_tool(state)
            self.assertEqual(send.await_args.args[1], {'kind': 'open', 'url': 'https://chat.deepseek.com/'})
            self.assertEqual(json.loads(decision_context(state))['browser_context']['latest_page']['tabId'], 2)
            state['current_task'] = {'tool_name': 'browser_tabs', 'task_id': 'tabs2', 'tool_args': {}}
            await browser_tool(state)
            self.assertEqual(send.await_count, 3)
            self.assertEqual(json.loads(decision_context(state))['browser_context']['latest_tabs'], [])
        self.broker.bind(IDENTITY, grant['sessionId'], 10, 'r2')
        self.assertIsNone(link.tabs)
        link.tabs = tabs
        link.close()
        self.assertIsNone(link.tabs)

    async def test_plain_model_reply_after_observation_completes_the_turn(self):
        from langchain_core.messages import AIMessage
        grant = self.broker.prepare(IDENTITY, 10)
        link = self.broker.owned(IDENTITY)
        link.socket = SimpleNamespace()
        self.broker.bind(IDENTITY, grant['sessionId'], 10, 'r1')
        link.results['read'] = json.dumps({'source': 'browser_observation', 'data': {'text': '库存明细'}})
        state = {**create_initial_state(7, '总结当前网页', []), 'browser_session_id': link.id,
                 'conversation_id': 10, 'run_id': 'r1', 'main_round': 1, 'task_results': {
                     'read': {'status': 'succeeded', 'kind': 'tool', 'actor': 'main',
                              'tool_name': 'browser_observe', 'result': '观察完成', 'private_context': True}}}
        text = '当前页面展示库存明细。'
        structured = SimpleNamespace(ainvoke=AsyncMock(return_value={
            'raw': AIMessage(content=text), 'parsed': None, 'parsing_error': None}))
        model = SimpleNamespace(with_structured_output=lambda *a, **k: structured)
        with (patch('app.services.browser_control.browser', self.broker),
              patch('app.graph.main_agent.get_llm', return_value=model),
              patch('app.graph.main_agent.assert_run', new_callable=AsyncMock)):
            update = await decide_main_action(state, visual={})
        self.assertEqual(update['main_action'], 'answer')
        self.assertEqual(update['final_reply'], text)
        self.assertEqual(update['main_decision']['answer_dependencies'], ['read'])
        structured.ainvoke.assert_awaited_once()
        structured.ainvoke.reset_mock()
        structured.ainvoke.return_value['raw'] = AIMessage(content='')
        model.ainvoke = AsyncMock(return_value=AIMessage(content=text))
        with (patch('app.services.browser_control.browser', self.broker),
              patch('app.graph.main_agent.get_llm', return_value=model),
              patch('app.graph.main_agent.assert_run', new_callable=AsyncMock)):
            recovered = await decide_main_action(state, visual={})
        self.assertEqual(recovered['final_reply'], text)
        self.assertEqual(structured.ainvoke.await_count, 2)
        model.ainvoke.assert_awaited_once()

        structured.ainvoke.reset_mock()
        structured.ainvoke.return_value = BrowserDecision(action='answer', user_reply=text)
        model.ainvoke.reset_mock()
        with (patch('app.services.browser_control.browser', self.broker),
              patch('app.graph.main_agent.get_llm', return_value=model),
              patch('app.graph.main_agent.assert_run', new_callable=AsyncMock)):
            normalized = await decide_main_action(state, visual={})
        self.assertEqual(normalized['final_reply'], text)
        self.assertEqual(normalized['main_decision']['answer_dependencies'], ['read'])
        self.assertIsNone(normalized['main_decision']['evidence_assessment'])
        structured.ainvoke.assert_awaited_once()
        model.ainvoke.assert_not_awaited()

    async def test_form_request_retries_with_only_browser_tools(self):
        grant = self.broker.prepare(IDENTITY, 10)
        self.broker.owned(IDENTITY).socket = SimpleNamespace()
        self.broker.bind(IDENTITY, grant['sessionId'], 10, 'r1')
        state = {**create_initial_state(7, '帮我填牛客那个页面的表格，姓名张三，汉族', []),
                 'browser_session_id': grant['sessionId'], 'conversation_id': 10, 'run_id': 'r1'}
        structured = SimpleNamespace(ainvoke=AsyncMock(side_effect=[
            {'action': 'call_tool', 'tool_call': {'name': 'read_editor', 'args': {}}},
            {'action': 'call_tool', 'tool_call': {'name': 'browser_tabs', 'args': {}}},
        ]))
        model = SimpleNamespace(with_structured_output=Mock(return_value=structured))
        with (patch('app.graph.main_agent.get_llm', return_value=model),
              patch('app.graph.main_agent.assert_run', new_callable=AsyncMock),
              patch('app.services.browser_control.browser', self.broker)):
            update = await decide_main_action(state, visual={})
        model.with_structured_output.assert_called_once_with(BrowserDecision, method='function_calling', include_raw=True)
        self.assertEqual(update['plan']['tasks'][0]['tool_name'], 'browser_tabs')
        self.assertEqual(update['decision_contract_audit']['last_outcome'], 'repaired')

    async def test_scrolling_can_repeat_within_the_regular_round_budget(self):
        decision = MainDecision(action='call_tool', tool_call={'name': 'browser_scroll', 'args': {'dy': 400}})
        state = create_initial_state(7, '向下滚动两次', [])
        first = validate_action(state, decision, 1)
        second = validate_action({**state, 'action_history': first['action_history'],
                                  'task_results': {'tool_1': {'status': 'succeeded'}}}, decision, 2)
        self.assertEqual(second['action_task_ids'], ['tool_2'])

    async def test_unchanged_page_does_not_loop_on_new_snapshot_ids(self):
        grant = self.broker.prepare(IDENTITY, 10)
        link = self.broker.owned(IDENTITY)
        link.socket = SimpleNamespace()
        self.broker.bind(IDENTITY, grant['sessionId'], 10, 'r1')
        page = {'id': 'old', 'tabId': 1, 'text': '简历', 'fields': []}
        link.snapshot = page
        state = {**create_initial_state(7, '填写当前简历', []), 'browser_session_id': link.id,
                 'conversation_id': 10, 'run_id': 'r1', 'action_task_ids': ['read'],
                 'current_task': {'tool_name': 'browser_observe', 'task_id': 'read', 'tool_args': {}}}
        with (patch('app.services.browser_control.browser', self.broker),
              patch('app.graph.staged_runtime.assert_run', new_callable=AsyncMock),
              patch('app.services.browser_control.send_action', new_callable=AsyncMock) as send):
            send.side_effect = [SimpleNamespace(status='ok', snapshot={**page, 'id': key})
                                for key in ('new1', 'new2')]
            self.assertEqual((await browser_tool(state))['browser_outcome'], 'page_unchanged')
            self.assertEqual((await browser_tool(state))['browser_outcome'], 'page_unchanged')
            limited = await browser_tool(state)
            self.assertEqual(limited['browser_outcome'], 'observe_limit')
            self.assertEqual(send.await_count, 2)
            self.assertEqual(link.snapshot['id'], 'new2')
            state['task_results'] = {'read': limited}
            observe = MainDecision(action='call_tool', tool_call={'name': 'browser_observe', 'args': {}})
            scroll = MainDecision(action='call_tool', tool_call={'name': 'browser_scroll', 'args': {'dy': 400}})
            self.assertEqual(validate_action(state, observe, 4)['backend_boundary']['reason_code'],
                             'browser_observe_limit')
            self.assertEqual(validate_action(state, scroll, 4)['action_task_ids'], ['tool_4'])
            send.side_effect = [SimpleNamespace(status='ok', snapshot={**page, 'id': 'new3', 'text': '编辑简历'}),
                                SimpleNamespace(status='ok', snapshot={**page, 'id': 'new4', 'text': '姓名'})]
            state['current_task']['tool_name'] = 'browser_scroll'
            state['current_task']['tool_args'] = {'dy': 400}
            self.assertEqual((await browser_tool(state))['browser_outcome'], 'scroll')
            state['current_task']['tool_name'] = 'browser_observe'
            state['current_task']['tool_args'] = {}
            self.assertEqual((await browser_tool(state))['browser_outcome'], 'observe')

    async def test_browser_step_budget_includes_a_final_main_decision(self):
        from app.graph.main_agent import decision_context, remaining_main_rounds

        decision = MainDecision(action='call_tool', tool_call={'name': 'browser_observe', 'args': {}})
        state = create_initial_state(7, '查看网页', [])
        result = {'status': 'succeeded', 'tool_name': 'browser_observe'}
        with (patch.object(settings, 'BROWSER_MAX_STEPS', 24),
              patch.object(settings, 'MAIN_MAX_ROUNDS', 8),
              patch.object(settings, 'MAIN_MAX_TASKS', 8)):
            state.update(main_round=8, task_results={f'tool_{i}': result for i in range(1, 9)})
            self.assertEqual(remaining_main_rounds(state), 0)
            self.assertIn('任务数量上限', validate_action(state, decision, 9)['stop_reason'])

            state['browser_session_id'] = 'browser-session'
            self.assertEqual(validate_action(state, decision, 9)['action_task_ids'], ['tool_9'])

            state.update(main_round=23, task_results={f'tool_{i}': result for i in range(1, 24)})
            self.assertEqual(validate_action(state, decision, 24)['action_task_ids'], ['tool_24'])
            state['task_results']['tool_24'] = result
            state['main_round'] = 24
            self.assertEqual(remaining_main_rounds(state), 1)
            self.assertIn('任务数量上限', validate_action(state, decision, 25)['stop_reason'])
            context = json.loads(decision_context({**state, 'task_results': {}}))
            self.assertEqual(context['remaining_rounds'], 1)
            self.assertEqual(context['remaining_tasks'], 24)
            state['main_round'] = 25
            self.assertEqual(remaining_main_rounds(state), 0)
