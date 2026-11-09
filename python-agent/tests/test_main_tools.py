"""Production routing and tool dispatch with fake providers; no network or live model calls."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from test_main_agent import llm, run_updates, evidence
from grounding_fakes import setUpModule, tearDownModule
from langgraph.checkpoint.memory import InMemorySaver
from fastapi import HTTPException

from app.config import settings
from app.graph import main_agent as main, action_runtime as actions, builder, staged_runtime as runtime
from app.graph.staged_plan import ExecutionTask, DraftRequest
from app.graph.state_factory import create_initial_state
from app.models.main_tool import tool_call_adapter
from app.services import main_tools, agent_events
from app.services.execution_facts import execution_facts
from app.services.tool_registry import tool_registry
from app.rpc.blog_client import ServiceError


def decision(name='get_article_comments', args=None, tid='read'):
    return main.MainDecision(action='call_tool', tool_call={'name': name, 'task_id': tid,
        'args': {'article_id': 42} if args is None else args})


def planned(choice):
    state = create_initial_state(7, '读取指定公开资料', [])
    return {**state, 'main_round': 1, 'main_action': 'call_tool', **main.validate_action(state, choice, 1)}


class ToolContractTests(unittest.TestCase):
    def test_rendered_prompt_output_fields_match_wire_schema(self):
        state = create_initial_state(7, '查看最新公开资料', [])
        prompt = main.build_main_messages(state, visual={})[0].content
        declaration = next(line for line in prompt.splitlines() if line.startswith('输出序列化顺序固定为：'))
        fields = declaration.split('：', 1)[1].split('。', 1)[0].split(' → ')
        self.assertEqual(fields, list(main.MainDecision.model_json_schema(by_alias=True)['properties']))
        self.assertEqual(fields[-1], 'user_reply')
        self.assertIn(f'前{len(fields) - 1}个控制字段', declaration)
        self.assertNotIn('retrieval.allow_web', prompt)
        self.assertNotIn('retrieval.search_query', prompt)

    def test_observed_legacy_null_field_is_still_rejected(self):
        # Correct the instructions, never silently ignore obsolete controls.
        with self.assertRaises(ValueError) as caught:
            main.MainDecision.model_validate({'action': 'answer', 'user_reply': '回答', 'retrieval': None})
        self.assertIn('extra_forbidden', str(caught.exception))

    def test_schema_has_four_actions_and_exactly_the_executable_catalog(self):
        schema = main.MainDecision.model_json_schema()
        self.assertEqual(set(schema['properties']['action']['enum']), {'call_tool', 'delegate', 'answer', 'write_draft'})
        self.assertNotIn('retrieval', schema['properties'])
        names = {item['properties']['name']['const'] for item in tool_call_adapter.json_schema()['$defs'].values()
                 if 'name' in item.get('properties', {})}
        self.assertEqual(names, {item['name'] for item in tool_registry.main_catalog()})
        self.assertEqual(len(names), 13)

    def test_conflicting_actions_unknown_tools_and_old_wire_contract_are_rejected(self):
        call = decision().tool_call
        for payload in (
            {'action': 'retrieve', 'retrieval': {'instruction': 'find'}},
            {'action': 'call_tool'},
            {'action': 'answer', 'reply': 'hello', 'tool_call': call},
            {'action': 'write_draft', 'draft_request': DraftRequest(task_id='draft', instruction='write'), 'tool_call': call},
            {'action': 'call_tool', 'tool_call': {'name': 'save_draft', 'args': {}}},
            {'action': 'call_tool', 'tool_call': {'name': 'mcp_private', 'args': {}}},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                main.MainDecision.model_validate(payload)

    def test_typed_arguments_reject_invalid_or_authority_fields(self):
        cases = [('get_article_comments', {'article_id': -1}), ('get_article_comments', {'article_id': True}),
            ('get_article_comments', {'article_id': 42, 'limit': '20'}),
            ('get_article_comments', {'article_id': 42, 'limit': 51}),
            ('get_article_comments', {'article_id': 'not-an-id'}), ('get_trending_topics', {'limit': 0}),
            ('read_memory', {'query': 'history', 'user_id': 99}), ('read_editor', {'part': 'document', 'snapshot_id': 'old'}),
            ('read_draft', {'article_id': 42, 'allow_web': True}), ('web_search', {'query': 'x' * 129}),
            ('search_knowledge', {'query': 'find', 'capabilities': ['web_search']}), ('web_search', {'query': '   '})]
        for name, args in cases:
            with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                decision(name, args)

    def test_task_cannot_change_compiled_tool_arguments_or_executor(self):
        task = main.compile_action_plan(decision(), 1).tasks[0].model_dump()
        for change in ({'tool_args': {'article_id': -1}}, {'actor': 'subagent'}, {'tool_name': 'read_memory'},
                       {'kind': 'writing'}, {'allow_web': True}, {'depends_on': ['other']}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                ExecutionTask.model_validate({**task, **change})

    def test_different_rpc_arguments_are_different_strategies_and_same_call_is_bounded(self):
        state = planned(decision())
        state['task_results'] = {'read': {'status': 'succeeded'}}
        same = main.validate_action(state, decision(tid='again'), 2)
        changed = main.validate_action(state, decision(args={'article_id': 43}, tid='other'), 2)
        self.assertTrue(same['stop_reason'])
        self.assertNotIn('stop_reason', changed)


class ExecuteToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_adapters_reuse_real_tools_with_bounded_rpc_parameters(self):
        from app.tools import get_article_comments, get_user_articles, get_trending_topics
        cases = [
            ('get_article_comments', {'article_id': 42, 'limit': 5}, get_article_comments,
             [{'nick_name': '读者', 'content': '有帮助', 'create_time': '2026-10-20'}],
             ('comments',), {'target_id': 42, 'limit': 5}),
            ('get_user_articles', {'user_id': 8, 'page': 2, 'page_size': 5}, get_user_articles,
             [{'article_id': 42, 'title': '文章', 'view_count': 1, 'like_count': 2, 'collect_count': 0, 'create_time': '2026-10-20'}],
             ('user_articles',), {'target_id': 8, 'page': 2, 'limit': 5}),
            ('get_trending_topics', {'limit': 5}, get_trending_topics,
             [{'tag_name': 'Agent', 'use_count': 3}], ('trending',), {'limit': 5}),
        ]
        for name, args, module, rows, positional, keyword in cases:
            with self.subTest(name=name), patch.object(module, 'public_read', AsyncMock(return_value=rows)) as rpc:
                result = await actions.execute_tool_node(planned(decision(name, args)))
            rpc.assert_awaited_once_with(*positional, **keyword)
            self.assertEqual(result['task_results']['read']['status'], 'succeeded')

    async def test_main_calls_comments_then_answers_without_another_tool_selection_model(self):
        model, control = llm([decision(), main.MainDecision(action='answer', reply='评论里提到了重试。', answer_dependencies=['read'])])
        tool = tool_registry.get_local_tool('get_article_comments')
        with patch.object(main, 'get_llm', return_value=model), \
             patch.object(type(tool), 'ainvoke', AsyncMock(return_value='- 读者：请解释重试 [77]')) as invoke:
            result, nodes = await run_updates(builder._build_graph().compile(checkpointer=InMemorySaver()), create_initial_state(7, '读一下文章评论', []))
        self.assertEqual(nodes, ['main_agent', 'execute_tool', 'main_agent', 'final_gate'])
        self.assertEqual(control.ainvoke.await_count, 2)
        invoke.assert_awaited_once_with({'article_id': 42, 'limit': 20})
        self.assertEqual(result['task_results']['read']['status'], 'succeeded')
        self.assertEqual(result['task_results']['read']['citations'], [])
        self.assertIn('重试', execution_facts(result)['public_tool_results'][0]['result'])

    async def test_bad_parameters_are_repaired_once_before_any_tool_runs(self):
        bad = {'action': 'call_tool', 'tool_call': {'name': 'get_article_comments', 'args': {'article_id': 'wrong'}}}
        model, control = llm([bad, decision()])
        tool = tool_registry.get_local_tool('get_article_comments')
        with patch.object(main, 'get_llm', return_value=model), patch.object(type(tool), 'ainvoke', AsyncMock()) as invoke:
            update = await main.decide_main_action(create_initial_state(7, '读评论', []), visual={})
        invoke.assert_not_awaited()
        self.assertEqual(update['main_action'], 'call_tool')
        self.assertEqual(control.ainvoke.await_count, 2)
        self.assertEqual(update['decision_contract_audit']['last_outcome'], 'repaired')
        repair = control.ainvoke.await_args.args[0][-1].content
        self.assertIn('article_id', repair)

    async def test_unknown_tool_stops_after_one_repair_with_no_execution(self):
        bad = {'action': 'call_tool', 'tool_call': {'name': 'drop_database', 'args': {}}}
        model, control = llm([bad, bad])
        with patch.object(main, 'get_llm', return_value=model), patch.object(tool_registry, 'get_local_tool') as resolve:
            update = await main.decide_main_action(create_initial_state(7, 'read', []), visual={})
        resolve.assert_not_called()
        self.assertEqual(control.ainvoke.await_count, 2)
        self.assertTrue(update['stop_reason'])

    async def test_web_tools_check_current_policy_and_constraints_before_io(self):
        for enabled, constraints in ((False, []), (True, [{'id': 'deny', 'key': 'web_search', 'content': 'deny'}])):
            with self.subTest(enabled=enabled), patch.object(settings, 'AGENT_WEB_SEARCH_ENABLED', enabled):
                state = planned(decision('web_search', {'query': 'Agent 最新资料'}))
                state['active_constraints'] = constraints
                with patch.object(main_tools, 'retrieve_evidence', AsyncMock()) as search:
                    with self.assertRaises(PermissionError):
                        await actions.execute_tool_node(state)
                search.assert_not_awaited()

    async def test_revoked_executor_and_cancellation_never_become_repairable_tool_errors(self):
        state = planned(decision())
        tool = tool_registry.get_local_tool('get_article_comments')
        for error in (HTTPException(409, 'revoked'), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__), patch.object(runtime, 'assert_run', AsyncMock(side_effect=error)), \
                 patch.object(type(tool), 'ainvoke', AsyncMock()) as invoke:
                with self.assertRaises(type(error)):
                    await actions.execute_tool_node(state)
            invoke.assert_not_awaited()

    async def test_executor_revoked_during_io_cannot_commit_the_tool_result(self):
        tool = tool_registry.get_local_tool('get_article_comments')
        with patch.object(type(tool), 'ainvoke', AsyncMock(return_value='资料')) as invoke, \
             patch.object(runtime, 'assert_run', AsyncMock(side_effect=[None, HTTPException(409, 'revoked')])):
            with self.assertRaises(HTTPException):
                await actions.execute_tool_node(planned(decision()))
        invoke.assert_awaited_once()

    async def test_outage_is_an_observation_but_permission_error_propagates(self):
        state = planned(decision())
        tool = tool_registry.get_local_tool('get_article_comments')
        with patch.object(type(tool), 'ainvoke', AsyncMock(side_effect=ServiceError(503, 'private endpoint'))):
            update = await actions.execute_tool_node(state)
        self.assertEqual(update['task_results']['read']['status'], 'tool_error')
        self.assertEqual(update['observations'][0]['tool_failures']['read']['code'], 'TOOL_UNAVAILABLE')
        self.assertNotIn('private endpoint', json.dumps(update))
        with patch.object(type(tool), 'ainvoke', AsyncMock(side_effect=ServiceError(403))):
            with self.assertRaises(PermissionError):
                await actions.execute_tool_node(state)

    async def test_old_checkpoint_retrieval_uses_same_executor_without_old_model_action(self):
        task = ExecutionTask(task_id='old', kind='search', actor='main', instruction='find', filters={})
        state = create_initial_state(7, 'find', [])
        state.update(main_round=1, main_action='retrieve', plan={'tasks': [task.model_dump()]})
        with patch.object(main_tools, 'retrieve_evidence', AsyncMock(return_value=evidence('old'))) as search:
            result = await actions.main_retrieve_node(state)
        search.assert_awaited_once()
        self.assertEqual(result['task_results']['old']['tool_name'], 'search_knowledge')

    async def test_production_graph_resumes_at_old_node_name_after_upgrade(self):
        task = ExecutionTask(task_id='old', kind='search', actor='main', instruction='find', filters={})
        state = create_initial_state(7, 'find', [])
        state.update(main_round=1, main_action='retrieve', plan={'tasks': [task.model_dump()]})
        model, control = llm([main.MainDecision(action='answer', reply='没有找到相关公开资料。')])
        graph = builder._build_graph().compile(checkpointer=InMemorySaver())
        config = {'configurable': {'thread_id': 'old-tool-checkpoint'}}
        await graph.aupdate_state(config, state, as_node='main_agent')
        self.assertEqual((await graph.aget_state(config)).next, ('main_retrieve',))
        empty = {'status': 'insufficient_evidence', 'result': '没有匹配资料', 'citations': [], 'article_cards': []}
        with patch.object(main, 'get_llm', return_value=model), \
             patch.object(main_tools, 'retrieve_evidence', AsyncMock(return_value=empty)) as search:
            result = await graph.ainvoke(None, config)
        search.assert_awaited_once()
        self.assertEqual(control.ainvoke.await_count, 1)
        self.assertEqual(result['task_results']['old']['tool_name'], 'search_knowledge')

    async def test_mcp_name_collision_does_not_replace_trusted_public_tool(self):
        tool = tool_registry.get_local_tool('get_article_comments')
        with patch.dict(tool_registry._mcp_tools, {'get_article_comments': object()}), \
             patch.object(type(tool), 'ainvoke', AsyncMock(return_value='暂无评论')) as invoke:
            result = await actions.execute_tool_node(planned(decision()))
        invoke.assert_awaited_once()
        self.assertEqual(result['task_results']['read']['status'], 'succeeded')

    async def test_public_plan_reports_actual_tool_and_preserves_full_query(self):
        query = '核实公开出处，' * 100
        state = planned(decision('search_knowledge', {'query': query}))
        with patch.object(agent_events, 'publish_event', AsyncMock()) as publish:
            await agent_events.publish_route(state, 'call_tool', state)
        plan = publish.await_args.args[0]
        self.assertEqual(plan['tasks'][0]['label'], query)

    async def test_web_search_skips_platform_rag_and_returns_normal_citations(self):
        with patch.object(settings, 'AGENT_WEB_SEARCH_ENABLED', True):
            task = main.compile_action_plan(decision('web_search', {'query': 'Agent 官方说明'}), 1).tasks[0]
            state = runtime.task_context(create_initial_state(7, '查询', []), task)
            search = main_tools.retrieve_evidence.__wrapped__ if hasattr(main_tools.retrieve_evidence, '__wrapped__') else main_tools.retrieve_evidence
            from app.graph.nodes import search_worker
            from app.services.query_rewrite import ResolvedFilters
            with patch.object(search_worker.filter_resolver_instance, 'resolve', AsyncMock(return_value=ResolvedFilters())), \
                 patch.object(search_worker.retrieval_service_instance, 'hybrid_search', AsyncMock()) as platform, \
                 patch.object(search_worker, 'do_search', AsyncMock(return_value=[{'title': '官方', 'url': 'https://example.com/agent', 'content': '公开说明'}])) as web:
                result = await search(state)
        platform.assert_not_awaited()
        web.assert_awaited_once()
        self.assertEqual(result['retrieval_report']['platform']['status'], 'not_requested')
        self.assertEqual(result['retrieval_report']['web']['status'], 'found')
        self.assertEqual(result['citations'][0]['url'], 'https://example.com/agent')

