"""Exact state-local addressing, batch isolation and model-visible coverage."""
from copy import deepcopy
import json
import unittest
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.graph import action_runtime, main_agent
from app.graph.state_factory import create_initial_state
from app.models.main_tool import tool_call_adapter
from app.services import context_tools
from app.services.context_projection import project_results
from app.services.result_access import result_version
from test_context_management import evidence, tool_context
from test_main_tools import planned, decision


class ResultAccessTests(unittest.IsolatedAsyncioTestCase):
    async def read(self, sources, args, name='read_task_result'):
        with patch.object(context_tools, 'verify_public_evidence', AsyncMock()):
            return await context_tools.read_task_result(tool_context(name, args, sources))

    async def test_keyword_near_tail_is_read_once_from_state_without_storage(self):
        text = 'irrelevant log ' * 7000 + '\n验收口令：北斗-K7P9\n' + 'other log ' * 400
        source = evidence(text)
        original = deepcopy(source)
        with patch('app.services.checkpoint_store.LatestRunRedisSaver.aget_tuple', AsyncMock()) as redis, \
                patch.object(context_tools.db, 'fetch_all', AsyncMock()) as mysql:
            output = await self.read({'s': source}, {'source_task_id': 's', 'query': '验收口令', 'max_chars': 1000})
        payload = json.loads(output['result'])
        self.assertTrue(payload['matched'])
        self.assertIn('北斗-K7P9', payload['content'])
        self.assertGreater(payload['start_char'], 90000)
        self.assertEqual(payload['content'], text[payload['start_char']:payload['next_start_char']])
        self.assertEqual(output['result_reads'][0]['source_version'], result_version(source))
        self.assertEqual(source, original)
        redis.assert_not_awaited(); mysql.assert_not_awaited()

    async def test_keyword_is_literal_and_missing_match_cannot_be_evidence(self):
        output = await self.read({'s': evidence('plain text')}, {'source_task_id': 's', 'query': '.*'})
        self.assertFalse(json.loads(output['result'])['matched'])
        self.assertEqual(output['result_reads'], [])
        self.assertEqual(output['citations'], [])

    async def test_citation_locator_returns_only_that_canonical_source(self):
        source = {**evidence('[s:1] A\n[s:2] B'),
            'citations': [{'id': 's:1'}, {'id': 's:2'}],
            'citation_contents': {'s:1': 'SOURCE A', 's:2': 'SOURCE B'}}
        output = await self.read({'s': source}, {'source_task_id': 's', 'citation_id': 's:2'})
        self.assertEqual(json.loads(output['result'])['content'], 'SOURCE B')
        self.assertEqual(output['citations'], [{'id': 's:2'}])
        with self.assertRaises(ValueError):
            await self.read({'s': source}, {'source_task_id': 's', 'citation_id': 'foreign:1'})

    async def test_batch_shares_character_budget_and_keeps_all_requested_sources(self):
        sources = {f's{i}': evidence(str(i) * 30000) for i in range(4)}
        output = await self.read(sources, {'requests': [
            {'source_task_id': tid, 'max_chars': 24000} for tid in sources]}, 'read_task_results')
        results = json.loads(output['result'])['results']
        self.assertEqual(len(results), 4)
        self.assertLessEqual(sum(len(r['content']) for r in results), 24000)
        self.assertEqual({r['source_task_id'] for r in results}, set(sources))
        self.assertTrue(all(r['has_more'] for r in results))

    async def test_invalid_batch_item_prevents_partial_disclosure(self):
        context = tool_context('read_task_results', {'requests': [
            {'source_task_id': 'public'}, {'source_task_id': 'private'}]},
            {'public': evidence('public'), 'private': evidence('secret', 'drafts')})
        with patch.object(context_tools, 'verify_public_evidence', AsyncMock()) as verify:
            with self.assertRaises(ValueError): await context_tools.read_task_results(context)
        verify.assert_not_awaited()

    async def test_batch_cannot_hide_web_access_in_second_item(self):
        sources = {'public': evidence(), 'web': {**evidence(), 'tool_name': 'web_search',
                   'citations': [{'id': 'w:1', 'url': 'https://example.com'}]}}
        with self.assertRaises(PermissionError):
            await self.read(sources, {'requests': [{'source_task_id': 'public'},
                            {'source_task_id': 'web'}]}, 'read_task_results')

    async def test_read_alias_returns_root_text_instead_of_nested_json(self):
        sources = {'s': evidence('root body ' * 200)}
        first = await self.read(sources, {'source_task_id': 's', 'max_chars': 500})
        sources['read'] = {**first, 'kind': 'tool', 'actor': 'main', 'tool_name': 'read_task_result'}
        second = await self.read(sources, {'source_task_id': 'read', 'start_char': 500, 'max_chars': 500})
        payload = json.loads(second['result'])
        self.assertEqual(payload['source_task_id'], 's')
        self.assertEqual(payload['content'], sources['s']['result'][500:1000])
        sources['s']['result'] = 'changed root'
        with self.assertRaises(ValueError):
            await self.read(sources, {'source_task_id': 'read'})

    async def test_alias_cycle_and_private_root_are_rejected(self):
        alias = {**evidence(json.dumps({'source_task_id': 'b'})),
                 'kind': 'tool', 'tool_name': 'read_task_result'}
        with self.assertRaises(ValueError):
            await self.read({'a': alias, 'b': {**alias, 'result': json.dumps({'source_task_id': 'a'})}},
                            {'source_task_id': 'a'})
        with self.assertRaises(ValueError):
            await self.read({'a': alias, 'b': evidence('private', 'editor')}, {'source_task_id': 'a'})

    async def test_partial_overlap_is_subtracted_only_in_model_view(self):
        source = evidence('0123456789' * 4000)
        old = await self.read({'s': source}, {'source_task_id': 's', 'max_chars': 1000})
        new = await self.read({'s': source}, {'source_task_id': 's', 'start_char': 500, 'max_chars': 1000})
        values = {'old': {**old, 'tool_name': 'read_task_result'},
                  'new': {**new, 'tool_name': 'read_task_result'}}
        original = deepcopy(values)
        view = project_results(values, selective=True)
        fragment = json.loads(view['old']['result'])
        self.assertEqual(fragment['content'], source['result'][:500])
        self.assertEqual(view['old']['result_reads'][0]['end_char'], 500)
        self.assertEqual(values, original)

    async def test_batch_dispatch_retains_backend_read_metadata_in_state(self):
        state = planned(decision('read_task_results', {'requests': [
            {'source_task_id': 's', 'query': 'needle'}]}, tid='batch'))
        state['task_results'] = {'s': evidence('padding ' * 3000 + 'needle END')}
        with patch.object(context_tools, 'verify_public_evidence', AsyncMock()):
            update = await action_runtime.execute_tool_node(state)
        saved = update['task_results']['batch']
        self.assertEqual(saved['status'], 'succeeded')
        self.assertEqual(saved['result_reads'][0]['source_task_id'], 's')

    async def test_delivery_audit_cannot_use_unread_tail_of_canonical_source(self):
        from app.services.result_access import answer_source_scope
        from app.services.grounding import source_contents
        body = 'visible beginning ' * 100 + 'UNREAD_SECRET_TAIL'
        source = {**evidence(body), 'citations': [{'id': 's:1'}], 'citation_contents': {'s:1': body}}
        output = await self.read({'s': source}, {'source_task_id': 's', 'max_chars': 500})
        view = {'read': {**output, 'tool_name': 'read_task_result'}}
        state = {'task_results': {'s': source}, 'answer_source_scope': answer_source_scope(view, ['read'])}
        content = source_contents(state, [{'id': 's:1'}])[0]['content']
        self.assertEqual(content, body[:500])
        self.assertNotIn('UNREAD_SECRET_TAIL', content)

    async def test_range_in_second_citation_does_not_grant_the_first_citation(self):
        source = {**evidence('[s:1]\n' + 'A' * 2000 + '\n[s:2]\n' + 'B' * 2000),
                  'citations': [{'id': 's:1'}, {'id': 's:2'}]}
        output = await self.read({'s': source}, {'source_task_id': 's', 'start_char': 2500, 'max_chars': 500})
        self.assertEqual(output['citations'], [{'id': 's:2'}])


class ResultSelectionTests(unittest.TestCase):
    def test_old_checkpoint_range_task_accepts_absent_new_optional_fields(self):
        from app.graph.staged_plan import ExecutionTask
        from app.models.main_tool import task_fields
        call = tool_call_adapter.validate_python({'name': 'read_task_result', 'args': {'source_task_id': 's'}})
        task = ExecutionTask(task_id='read', actor='main', **task_fields(call)).model_dump()
        task['tool_args'].pop('query'); task['tool_args'].pop('citation_id')
        restored = ExecutionTask.model_validate(task)
        self.assertIsNone(restored.tool_args['query'])
        task['tool_args']['user_id'] = 999
        with self.assertRaises(ValueError): ExecutionTask.model_validate(task)

    def test_version_is_stable_across_storage_object_key_order(self):
        first = {**evidence('same'), 'citations': [{'id': 's:1', 'title': 'Title'}]}
        second = {**first, 'citations': [{'title': 'Title', 'id': 's:1'}]}
        self.assertEqual(result_version(first), result_version(second))
    def test_old_large_results_stay_indexed_even_with_spare_window(self):
        state = create_initial_state(7, '查看最近结果', [])
        state['task_results'] = {'old': evidence('old ' * 18000), 'fresh': evidence('fresh result')}
        state['action_task_ids'] = ['fresh']
        payload = json.loads(main_agent.build_main_messages(state, {})[1].content)
        self.assertEqual(payload['successful_tasks']['old']['content_scope'], 'index_only')
        self.assertEqual(payload['successful_tasks']['fresh']['result'], 'fresh result')
        self.assertIn('instruction', payload['successful_tasks']['old'])

    def test_fresh_large_result_is_not_forced_through_a_reader(self):
        state = create_initial_state(7, '总结刚取得的结果', [])
        state['task_results'] = {'fresh': evidence('fresh ' * 18000)}
        state['action_task_ids'] = ['fresh']
        payload = json.loads(main_agent.build_main_messages(state, {})[1].content)
        self.assertEqual(payload['successful_tasks']['fresh']['result'], state['task_results']['fresh']['result'])

    def test_new_fields_are_optional_but_ambiguous_or_oversized_batches_are_rejected(self):
        for args in ({'source_task_id': 's', 'query': 'a', 'citation_id': 's:1'},
                     {'source_task_id': 's', 'query': 'a', 'start_char': 1}):
            with self.assertRaises(ValueError): tool_call_adapter.validate_python({'name': 'read_task_result', 'args': args})
        with self.assertRaises(ValueError):
            tool_call_adapter.validate_python({'name': 'read_task_results', 'args': {
                'requests': [{'source_task_id': 's'}] * 5}})
