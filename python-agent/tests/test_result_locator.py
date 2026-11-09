"""Paging, exact offsets, budget sharing and old saved-call compatibility."""
import json
import unittest
from unittest.mock import AsyncMock, patch

from app.graph import main_agent
from app.graph.staged_plan import ExecutionTask
from app.models.main_tool import tool_call_adapter
from app.services import context_tools
from app.services.result_access import read_selection
from app.services.result_locator import sections
from test_context_management import evidence, tool_context


class LocatorTests(unittest.IsolatedAsyncioTestCase):
    async def read(self, sources, args, name='read_task_result'):
        with patch.object(context_tools, 'verify_public_evidence', AsyncMock()):
            return await context_tools.read_task_result(tool_context(name, args, sources))

    async def test_all_ten_matches_are_reachable_and_ranges_are_exact(self):
        text = ''.join(f'needle={i} 😀中文\n' + 'filler ' * 250 for i in range(10))
        source, cursor, found = evidence(text), None, set()
        for _ in range(15):
            args = {'source_task_id': 's', 'query': 'needle', 'max_chars': 500}
            if cursor: args['cursor'] = cursor
            result = await self.read({'s': source}, args)
            payload = json.loads(result['result'])
            fragments = payload.get('fragments', [payload] if 'content' in payload else [])
            for piece in fragments:
                self.assertEqual(piece['content'], text[piece['start_char']:piece['next_start_char']])
                found.update(i for i in range(10) if f'needle={i} ' in piece['content'])
            next_cursor = payload['next_cursor']
            self.assertNotEqual(next_cursor, cursor) if next_cursor else None
            cursor = next_cursor
            if not cursor: break
        self.assertEqual(found, set(range(10)))
        self.assertIsNone(cursor)

    async def test_multiple_literal_words_and_no_match(self):
        source = evidence('中文😀\r\nalpha value\n' + 'x ' * 900 + '\n.* exact')
        result = await self.read({'s': source}, {'source_task_id': 's', 'queries': ['alpha', '.*']})
        self.assertIn('alpha', result['result']); self.assertIn('.*', result['result'])
        absent = await self.read({'s': source}, {'source_task_id': 's', 'queries': ['absent', 'missing']})
        self.assertFalse(json.loads(absent['result'])['matched'])
        self.assertEqual(absent['result_reads'], [])

    async def test_section_cursor_preserves_source_offsets_and_stops_at_next_section(self):
        text = '# First\n' + '中文😀测试\r\n' * 250 + '# Second\nsecret other section'
        source, cursor, pieces = evidence(text), None, []
        section = sections(text)[0][0]
        for _ in range(10):
            args = {'source_task_id': 's', 'section_id': section['section_id'], 'max_chars': 500}
            if cursor: args['cursor'] = cursor
            output = await self.read({'s': source}, args)
            payload = json.loads(output['result'])
            pieces.append(payload['content'])
            cursor = payload['next_cursor']
            if not cursor: break
        self.assertEqual(''.join(pieces), text[:text.index('# Second')])

    async def test_cursor_changed_source_query_and_invalid_payload_are_rejected(self):
        source = evidence(('needle ' + 'x ' * 900) * 6)
        output = await self.read({'s': source}, {'source_task_id': 's', 'query': 'needle', 'max_chars': 500})
        cursor = json.loads(output['result'])['next_cursor']
        self.assertTrue(cursor)
        for args, value in (({'query': 'other', 'cursor': cursor}, source),
                            ({'query': 'needle', 'cursor': cursor}, evidence(source['result'] + 'changed')),
                            ({'query': 'needle', 'cursor': '!!!'}, source)):
            with self.assertRaisesRegex(ValueError, '游标'):
                await self.read({'s': value}, {'source_task_id': 's', **args})

    async def test_empty_and_short_batch_items_release_their_budget(self):
        sources = {'long': evidence('abcd ' * 16000), 'none': evidence('no match'), 'short': evidence('short')}
        output = await self.read(sources, {'requests': [
            {'source_task_id': 'long', 'max_chars': 24000},
            {'source_task_id': 'none', 'query': 'missing'}, {'source_task_id': 'short'}]}, 'read_task_results')
        payloads = json.loads(output['result'])['results']
        self.assertGreater(len(payloads[0]['content']), 12000)
        self.assertLessEqual(sum(len(p.get('content', '')) for p in payloads), 24000)
        self.assertEqual(payloads[2]['content'], 'short')

    def test_markdown_index_ignores_code_and_bounds_entries(self):
        text = '# Same\nbody\n```md\n# Fake\n```\n## Child\nbody\n# Same\nend'
        outline, more = sections(text)
        self.assertEqual([item['title'] for item in outline], ['Same', 'Child', 'Same'])
        self.assertNotEqual(outline[0]['section_id'], outline[2]['section_id'])
        self.assertFalse(more)
        self.assertEqual(len(sections('# h\n' * 1000)[0]), 32)
        self.assertTrue(sections('# h\n' * 1000)[1])

    def test_old_saved_single_and_batch_defaults_preserve_fingerprints(self):
        for name, args in (('read_task_result', {'source_task_id': 's'}),
                           ('read_task_results', {'requests': [{'source_task_id': 's'}]})):
            task = tool_context(name, args)['current_task']
            expected = main_agent.task_fingerprint(ExecutionTask.model_validate(task))
            selections = task['tool_args']['requests'] if name == 'read_task_results' else [task['tool_args']]
            for selection in selections:
                for key in ('queries', 'section_id', 'cursor'):
                    selection.pop(key)
            restored = ExecutionTask.model_validate(task)
            self.assertEqual(main_agent.task_fingerprint(restored), expected)

    def test_conflicting_or_unbounded_locator_arguments_are_rejected(self):
        for extra in ({'query': 'x', 'queries': ['x']}, {'queries': ['x'] * 6},
                      {'section_id': 'h_0', 'citation_id': 's:1'}, {'cursor': 'x', 'start_char': 1},
                      {'queries': [' ']}):
            with self.assertRaises(ValueError):
                tool_call_adapter.validate_python({'name': 'read_task_result', 'args': {'source_task_id': 's', **extra}})
