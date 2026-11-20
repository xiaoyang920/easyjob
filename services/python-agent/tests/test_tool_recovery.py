"""Tool protocol, permissions, bounded repair and truthful failure propagation."""
import os
os.environ['DEEPSEEK_API_KEY'] = 'offline-test'
os.environ['AGENT_SERVICE_KEY'] = 'offline-service-key-32-bytes-long!!'
os.environ['LANGFUSE_TRACING_ENABLED'] = 'false'
os.environ['SERVICE_DISCOVERY_ENABLED'] = 'false'

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from app.graph import tool_executor as executor
from app.services.tool_recovery import ToolPolicy, ToolTaskError, ToolInputError, argument_issues
from app.services.tool_registry import ToolRegistry


def call(name='lookup', args=None, cid='c1'):
    return {'name': name, 'args': {} if args is None else args, 'id': cid, 'type': 'tool_call'}


def response(*calls):
    return AIMessage(content='', tool_calls=list(calls))


def reader(name='lookup', action=None, schema=None):
    calls = []
    async def read(query: str):
        calls.append(query)
        if action:
            return await action(query)
        return f'found {query}'
    kwargs = {'args_schema': schema} if schema else {}
    return StructuredTool.from_function(coroutine=read, name=name, description='Read public information.', **kwargs), calls


class ToolRepairTests(unittest.IsolatedAsyncioTestCase):
    async def run_agent(self, outputs, tools=None, **kwargs):
        model = SimpleNamespace(ainvoke=AsyncMock(), bind_tools=lambda _: model)
        self.messages = []
        async def next_output(messages, **config):
            self.messages.append(list(messages))
            return outputs[len(self.messages) - 1]
        model.ainvoke.side_effect = next_output
        self.model = model
        policies = {t.name: ToolPolicy(True) for t in tools or []}
        with patch.object(executor, 'get_llm', return_value=model), \
             patch.object(executor, 'get_langfuse_callback', return_value=None):
            return await executor.run_tool_agent('Read only.', 'Find information.', tools,
                tool_policies=kwargs.pop('tool_policies', policies), **kwargs)

    async def test_missing_argument_returns_correlated_error_then_repairs_once(self):
        tool, invoked = reader()
        result = await self.run_agent([response(call()), response(call(args={'query': 'Java'}, cid='fix')),
                                      AIMessage(content='answer')], [tool])
        self.assertEqual(result, 'answer')
        self.assertEqual(invoked, ['Java'])
        feedback = self.messages[1][-1]
        self.assertIsInstance(feedback, ToolMessage)
        self.assertEqual((feedback.tool_call_id, feedback.status), ('c1', 'error'))
        self.assertEqual(json.loads(feedback.content)['error']['fields'][0]['field'], 'query')

    async def test_typos_offer_only_allowed_names_and_never_auto_invoke(self):
        tool, invoked = reader('search_articles')
        await self.run_agent([response(call('search_articels', {'query': 'Java'})),
            response(call('search_articles', {'query': 'Java'}, 'fix')), AIMessage(content='answer')], [tool])
        feedback = json.loads(self.messages[1][-1].content)
        self.assertEqual(feedback['error']['code'], 'UNKNOWN_TOOL')
        self.assertEqual(feedback['error']['available_tools'], ['search_articles'])
        self.assertEqual(invoked, ['Java'])

    async def test_mixed_batch_repair_reuses_success_with_new_call_id(self):
        tool, invoked = reader()
        await self.run_agent([response(call(args={'query': 'A'}, cid='good'), call(cid='bad')),
            response(call(args={'query': 'A'}, cid='cached'), call(args={'query': 'B'}, cid='fixed')),
            AIMessage(content='combined')], [tool])
        self.assertEqual(invoked, ['A', 'B'])
        tools = [m for m in self.messages[2] if isinstance(m, ToolMessage)]
        self.assertEqual([m.tool_call_id for m in tools], ['good', 'bad', 'cached', 'fixed'])
        self.assertEqual([m.status for m in tools], ['success', 'error', 'success', 'success'])

    async def test_second_invalid_call_stops_without_final_summary(self):
        tool, invoked = reader()
        with self.assertRaises(ToolTaskError) as caught:
            await self.run_agent([response(call()), response(call(args={'query': 42}, cid='again'))], [tool])
        self.assertEqual(caught.exception.report['code'], 'TOOL_REPAIR_EXHAUSTED')
        self.assertEqual(caught.exception.report['repair_attempts'], 1)
        self.assertEqual(self.model.ainvoke.await_count, 2)
        self.assertEqual(invoked, [])

    async def test_plain_answer_does_not_turn_failed_call_into_success(self):
        tool, _ = reader()
        with self.assertRaises(ToolTaskError) as caught:
            await self.run_agent([response(call()), AIMessage(content='pretend success')], [tool])
        self.assertEqual(caught.exception.report['code'], 'TOOL_REPAIR_ABANDONED')

    async def test_unrelated_tool_cannot_resolve_pending_failure(self):
        first, _ = reader()
        second, _ = reader('other')
        with self.assertRaises(ToolTaskError) as caught:
            await self.run_agent([response(call()), response(call('other', {'query': 'x'}, 'fix'))], [first, second])
        self.assertEqual(caught.exception.report['code'], 'TOOL_REPAIR_ABANDONED')

    async def test_unauthorized_batch_is_rejected_before_even_valid_call_executes(self):
        tool, invoked = reader()
        for name in ('save_article', 'web_search', 'unrecognized'):
            with self.subTest(name=name), self.assertRaises(PermissionError):
                await self.run_agent([response(call(args={'query': 'ok'}), call(name, {}, 'denied'))], [tool])
            self.assertEqual(invoked, [])
            self.assertEqual(self.model.ainvoke.await_count, 1)

    async def test_repair_cannot_switch_to_forbidden_tool(self):
        tool, invoked = reader()
        with self.assertRaises(PermissionError):
            await self.run_agent([response(call()), response(call('save_article', {}, 'fix'))], [tool])
        self.assertEqual(invoked, [])

    async def test_no_tools_hallucinated_call_is_hard_denied(self):
        with self.assertRaises(PermissionError):
            await self.run_agent([response(call())])

    async def test_missing_duplicate_or_excessive_ids_are_protocol_failures(self):
        tool, invoked = reader()
        batches = [[call(cid='')], [call(), call()], [call(cid=str(i)) for i in range(9)]]
        for batch in batches:
            with self.subTest(batch=len(batch)), self.assertRaises(ToolTaskError) as caught:
                await self.run_agent([response(*batch)], [tool])
            self.assertEqual(caught.exception.report['code'], 'TOOL_CALL_PROTOCOL')
        self.assertEqual(invoked, [])

    async def test_malformed_json_can_be_repaired_via_matching_tool_message(self):
        tool, invoked = reader()
        invalid = AIMessage(content='', invalid_tool_calls=[
            {'name': 'lookup', 'args': '{broken', 'id': 'bad-json', 'error': 'invalid'}])
        await self.run_agent([invalid, response(call(args={'query': 'ok'}, cid='fix')), AIMessage(content='answer')], [tool])
        self.assertEqual(self.messages[1][-1].tool_call_id, 'bad-json')
        self.assertEqual(invoked, ['ok'])

    async def test_tool_timeout_is_task_failure_without_model_retry(self):
        async def slow(_):
            await asyncio.Event().wait()
        tool, invoked = reader(action=slow)
        with self.assertRaises(ToolTaskError) as caught:
            await self.run_agent([response(call(args={'query': 'ok'}))], [tool], tool_timeout=.01)
        self.assertEqual(caught.exception.report['code'], 'TOOL_UNAVAILABLE')
        self.assertEqual(self.model.ainvoke.await_count, 1)
        self.assertEqual(invoked, ['ok'])

    async def test_transport_failure_is_safe_without_another_model_call(self):
        async def fail(_):
            raise httpx.ConnectError('private token and endpoint')
        tool, _ = reader(action=fail)
        with self.assertRaises(ToolTaskError) as caught:
            await self.run_agent([response(call(args={'query': 'ok'}))], [tool])
        self.assertNotIn('private', json.dumps(caught.exception.report))
        self.assertEqual(self.model.ainvoke.await_count, 1)

    async def test_permission_cancellation_conflict_and_unexpected_errors_propagate(self):
        errors = [PermissionError('deny'), HTTPException(409, 'stale'), asyncio.CancelledError(), RuntimeError('database bug')]
        for error in errors:
            async def fail(_, exc=error):
                raise exc
            tool, _ = reader(action=fail)
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                await self.run_agent([response(call(args={'query': 'ok'}))], [tool])
            self.assertEqual(self.model.ainvoke.await_count, 1)

    async def test_explicit_safe_tool_input_error_is_repairable(self):
        async def validate(query):
            if query == 'bad':
                raise ToolInputError('query', 'private rejected value')
            return 'ok'
        tool, invoked = reader(action=validate)
        await self.run_agent([response(call(args={'query': 'bad'})),
            response(call(args={'query': 'good'}, cid='fix')), AIMessage(content='answer')], [tool])
        self.assertEqual(invoked, ['bad', 'good'])
        self.assertNotIn('private', self.messages[1][-1].content)

    async def test_executor_and_capability_fences_are_rechecked_before_tools(self):
        tool, invoked = reader()
        state = {'run_id': 'fixture', 'execution_token': 'token'}
        with patch('app.graph.staged_runtime.assert_run', AsyncMock()) as fence, \
             patch.object(executor, 'require_capability', side_effect=PermissionError('revoked')) as permission:
            with self.assertRaises(PermissionError):
                await self.run_agent([response(call(args={'query': 'ok'}))], [tool], execution_state=state)
        self.assertGreaterEqual(fence.await_count, 3)
        permission.assert_called_once_with(state, 'platform_read')
        self.assertEqual(invoked, [])

    async def test_cancellation_after_model_returns_prevents_tool_execution(self):
        tool, invoked = reader()
        state = {}
        async def fence(_):
            if self.model.ainvoke.await_count:
                state['cancelled'] = True
        with patch('app.graph.staged_runtime.assert_run', side_effect=fence):
            with self.assertRaises(asyncio.CancelledError):
                await self.run_agent([response(call(args={'query': 'ok'}))], [tool], execution_state=state)
        self.assertEqual(invoked, [])

    async def test_mcp_hint_does_not_grant_readonly_execution(self):
        tool, invoked = reader()
        tool.metadata = {'readOnlyHint': True}
        with self.assertRaises(PermissionError):
            await self.run_agent([], [tool], tool_policies={})
        self.assertEqual(invoked, [])

    async def test_tool_returned_error_is_not_a_successful_result(self):
        async def reported(_):
            return ToolMessage(content='provider private failure', tool_call_id='c1', status='error')
        tool, _ = reader(action=reported)
        with self.assertRaises(ToolTaskError) as caught:
            await self.run_agent([response(call(args={'query': 'ok'}))], [tool])
        self.assertEqual(caught.exception.report['code'], 'TOOL_REPORTED_ERROR')
        self.assertNotIn('private', str(caught.exception))

    async def test_full_call_preserves_injected_call_id(self):
        from typing import Annotated
        from langchain_core.tools import tool, InjectedToolCallId
        received = []
        @tool
        async def lookup(query: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> str:
            """Read a public fixture while retaining its correlation ID."""
            received.append(tool_call_id)
            return query
        await self.run_agent([response(call(args={'query': 'ok'}, cid='correlation')),
                              AIMessage(content='answer')], [lookup])
        self.assertEqual(received, ['correlation'])

    async def test_repair_calls_preserve_parent_metrics_callback(self):
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.outputs import ChatResult, ChatGeneration
        from langchain_core.runnables import RunnableLambda
        from app.services.run_metrics import RunMetrics
        class Model(BaseChatModel):
            cursor: int = 0
            @property
            def _llm_type(self):
                return 'tool-repair-offline-fixture'
            def bind_tools(self, tools, **kwargs):
                return self
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                outputs = [response(call()), response(call(args={'query': 'ok'}, cid='fix')), AIMessage(content='answer')]
                output = outputs[self.cursor]
                self.cursor += 1
                output.usage_metadata = {'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12}
                return ChatResult(generations=[ChatGeneration(message=output)])
        tool, invoked = reader()
        meter = RunMetrics()
        async def run(_):
            return await executor.run_tool_agent('read', 'fixture', [tool], tool_policies={'lookup': ToolPolicy(True)})
        with patch.object(executor, 'get_llm', return_value=Model()), \
             patch.object(executor, 'get_langfuse_callback', return_value=None):
            self.assertEqual(await RunnableLambda(run).ainvoke({}, config={'callbacks': [meter]}), 'answer')
        snapshot = meter.snapshot()
        self.assertEqual((snapshot['llm_calls'], snapshot['input_tokens'], snapshot['output_tokens']), (3, 30, 6))
        self.assertEqual(invoked, ['ok'])


class SchemaTests(unittest.TestCase):
    def test_json_schema_tools_validate_types_required_and_unknown_fields(self):
        tool, _ = reader(schema={'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']})
        for args in ({}, {'query': 42}, {'query': 'ok', 'extra': 'secret'}):
            with self.subTest(args=args):
                issues = argument_issues(tool, args)
                self.assertTrue(issues)
                self.assertNotIn('secret', json.dumps(issues))
        self.assertEqual(argument_issues(tool, {'query': 'ok'}), [])

    def test_web_search_matches_real_128_character_limit_and_rejects_blank(self):
        tool, _ = reader('web_search')
        self.assertEqual(argument_issues(tool, {'query': '中' * 128}), [])
        self.assertTrue(argument_issues(tool, {'query': '中' * 129}))
        self.assertTrue(argument_issues(tool, {'query': '  '}))

    def test_remote_schema_references_never_trigger_network_resolution(self):
        tool, _ = reader(schema={'type': 'object', 'properties': {'query': {'$ref': 'https://example.invalid/schema'}}})
        with self.assertRaisesRegex(ValueError, '外部引用'):
            argument_issues(tool, {'query': 'x'})

    def test_mcp_shadowed_local_tool_cannot_inherit_local_permission(self):
        registry = ToolRegistry()
        shadow, _ = reader('web_search')
        self.assertIsNone(registry.policy_for(shadow))
        self.assertTrue(registry.policy_for(registry._local_tools['web_search']).read_only)
