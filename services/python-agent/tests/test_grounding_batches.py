"""Long reviews retain exact global coverage and one bounded audit lifetime."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import test_grounding as fixtures
from app.services import agent_events, grounding
from app.services.execution_facts import execution_facts, delivery_notices


def long_text(count=167):
    return '\n'.join(f'- 原文第{i}项。' for i in range(count))


class BatchedReviewTests(unittest.IsolatedAsyncioTestCase):
    def model(self, callback=None):
        async def invoke(messages, **kwargs):
            payload = json.loads(messages[1].content)
            if callback:
                await callback(payload)
            return {'blocks': [{'block_index': block['block_index'], 'claims': [
                {'unit_index': unit['unit_index'], 'kind': 'user_content', 'verdict': 'supported'}
                for unit in block['units']]} for block in payload['blocks']]}
        controller = SimpleNamespace(ainvoke=AsyncMock(side_effect=invoke))
        return SimpleNamespace(with_structured_output=lambda *a, **k: controller), controller

    def facts(self):
        return {**execution_facts({}), 'editor_documents': [{'content': long_text(640)}]}

    async def test_167_units_in_one_block_cover_every_unit_without_changing_text(self):
        text = long_text()
        model, controller = self.model()
        with patch.object(grounding, 'get_llm', return_value=model):
            review = await grounding.review_text(text, [], self.facts())
        self.assertFalse(review)
        self.assertEqual(review.safe_blocks, {0: text})
        self.assertEqual(review.substantive, 167)
        self.assertEqual(controller.ainvoke.await_count, 3)
        self.assertEqual(review.contract_audit['completed_batches'], 3)
        ids = [unit['unit_index'] for call in controller.ainvoke.await_args_list
               for block in json.loads(call.args[0][1].content)['blocks'] for unit in block['units']]
        self.assertEqual(sorted(ids), list(range(167)))

    async def test_many_blocks_are_reassembled_by_original_id_and_call_count_is_real(self):
        text = '\n\n'.join(long_text(6) for _ in range(36))
        model, controller = self.model()
        with patch.object(grounding, 'get_llm', return_value=model), \
             patch.object(agent_events, 'activity', AsyncMock()):
            result, audit = await grounding.verify_delivery(
                {'editor_context': {'snapshot_id': 's', 'content': text}, 'task_results': {
                    'read': {'status': 'succeeded', 'retrieval_target': 'editor', 'editor_snapshot_id': 's', 'editor_part': 'document'}}}, text, [])
        self.assertEqual(result, text)
        self.assertEqual(audit['status'], 'verified')
        self.assertEqual(audit['unit_count'], 216)
        self.assertEqual(audit['review_batches'], 2)
        self.assertEqual(audit['review_calls'], controller.ainvoke.await_count)
        self.assertNotIn('review_format_repair_calls', audit)

    async def test_late_batch_failure_keeps_only_verified_content_and_cancels_siblings(self):
        cancelled = asyncio.Event()
        async def fail(payload):
            index = payload['blocks'][0]['units'][0]['unit_index']
            if index == 80:
                await asyncio.sleep(.01)
                raise TimeoutError()
            if index == 160:
                try:
                    await asyncio.sleep(5)
                finally:
                    cancelled.set()
        model, controller = self.model(fail)
        with patch.object(grounding, 'get_llm', return_value=model):
            with self.assertRaises(TimeoutError) as raised:
                await grounding.review_text(long_text(240), [], self.facts())
        partial = raised.exception.partial_review
        self.assertIsNotNone(partial)
        self.assertEqual(partial.substantive, 0)  # A partially reviewed list stays atomic.
        self.assertEqual(partial.safe_blocks, {0: ''})
        self.assertEqual(len(partial), 160)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(raised.exception.contract_audit['model_calls'], 3)

    async def test_overall_timeout_does_not_restart_for_each_batch(self):
        active, cancelled = 0, 0
        async def slow(payload):
            nonlocal active, cancelled
            active += 1
            try:
                await asyncio.sleep(5)
            finally:
                cancelled += 1
        model, controller = self.model(slow)
        with patch.object(grounding, 'get_llm', return_value=model), \
             patch.object(grounding.settings, 'GROUNDING_TIMEOUT_SECONDS', .02):
            with self.assertRaises(TimeoutError) as raised:
                await grounding.review_text(long_text(320), [], self.facts())
        self.assertEqual(active, 2)
        self.assertEqual(cancelled, 2)
        self.assertEqual(raised.exception.contract_audit['model_calls'], 2)
        self.assertIsNone(raised.exception.partial_review)

    async def test_partial_failure_never_releases_known_bad_or_unreviewed_original(self):
        first, pending = '独立段落的特别结论。', long_text(160)
        text = first + '\n\n' + pending
        for verdict in ('supported', 'contradicted'):
            async def invoke(messages, **kwargs):
                payload = json.loads(messages[1].content)
                if payload['blocks'][0]['units'][0]['unit_index'] == 80:
                    await asyncio.sleep(.01)
                    raise TimeoutError()
                return {'blocks': [{'block_index': block['block_index'], 'claims': [
                    {'unit_index': unit['unit_index'], 'kind': 'user_content',
                     'verdict': verdict if block['block_index'] == 0 else 'supported'}
                    for unit in block['units']]} for block in payload['blocks']]}
            controller = SimpleNamespace(ainvoke=AsyncMock(side_effect=invoke))
            model = SimpleNamespace(with_structured_output=lambda *a, **k: controller)
            state = {'editor_context': {'snapshot_id': 's', 'content': text}, 'task_results': {
                'read': {'status': 'succeeded', 'retrieval_target': 'editor', 'editor_snapshot_id': 's', 'editor_part': 'document'}}}
            with self.subTest(verdict=verdict), patch.object(grounding, 'get_llm', return_value=model), \
                 patch.object(agent_events, 'activity', AsyncMock()):
                result, audit = await grounding.verify_delivery(state, text, [])
            self.assertNotEqual(audit['status'], 'verified')
            self.assertEqual(audit['completed_batches'], 1)
            self.assertNotIn(pending, result)
            self.assertEqual(first in result, verdict == 'supported')

    async def test_batched_draft_metadata_remains_in_the_original_positions(self):
        draft = json.dumps({'title': '草稿标题', 'summary': '草稿摘要', 'content': long_text()}, ensure_ascii=False)
        model, controller = self.model()
        with patch.object(grounding, 'get_llm', return_value=model):
            review = await grounding.review_text(draft, [], self.facts())
        self.assertFalse(review)
        self.assertEqual(review.safe_blocks[0], 'title: 草稿标题')
        self.assertEqual(review.safe_blocks[1], 'summary: 草稿摘要')
        self.assertEqual(review.safe_blocks[2], long_text())
        for call in controller.ainvoke.await_args_list:
            for block in json.loads(call.args[0][1].content)['blocks']:
                self.assertTrue(all(unit['metadata'] == (block['block_index'] < 2) for unit in block['units']))

    async def test_size_rejection_is_input_limit_and_records_zero_model_calls(self):
        for text in (long_text(641), '\n\n'.join('段落' for _ in range(81))):
            model, controller = self.model()
            with self.subTest(chars=len(text)), patch.object(grounding, 'get_llm', return_value=model), \
                 patch.object(agent_events, 'activity', AsyncMock()):
                state = {'article_context': {'content': '原文'}}
                result, audit = await grounding.verify_delivery(state, text, [{'id': 'article_context:1'}])
            self.assertEqual(audit['reason_code'], 'review_size_limit')
            self.assertEqual(audit['review_calls'], 0)
            self.assertIn('超出本次自动核验范围', result)
            self.assertNotIn('返回的结构', result)
            controller.ainvoke.assert_not_awaited()

    async def test_inherited_citation_and_metadata_scope_survive_batch_boundaries(self):
        text = f'**列表来源**[source:1]：\n\n{long_text(167)}'
        sources = [{'id': 'source:1', 'content': '原文'}]
        catalog = grounding.evidence_catalog(sources)
        async def invoke(messages, **kwargs):
            payload = json.loads(messages[1].content)
            return {'blocks': [{'block_index': block['block_index'], 'claims': [
                {'unit_index': unit['unit_index'], 'kind': 'source_fact', 'verdict': 'supported', 'evidence_ids': list(catalog)}
                for unit in block['units']]} for block in payload['blocks']]}
        controller = SimpleNamespace(ainvoke=AsyncMock(side_effect=invoke))
        model = SimpleNamespace(with_structured_output=lambda *a, **k: controller)
        with patch.object(grounding, 'get_llm', return_value=model):
            review = await grounding.review_text(text, sources, execution_facts({}))
        self.assertFalse(review)
        for call in controller.ainvoke.await_args_list:
            for block in json.loads(call.args[0][1].content)['blocks']:
                for unit in block['units']:
                    if block['block_index'] == 1:
                        self.assertEqual(unit['citation_ids'], ['source:1'])
        self.assertEqual(set(review.safe_blocks), {0, 1})

    def test_article_excerpt_notice_explains_scope_without_generic_target_warning(self):
        notes = delivery_notices({'article_context': {'completeness': 'excerpt'},
            'main_decision': {'evidence_assessment': {'adequacy': 'partial'}}}, [{'id': 'article_context:1'}])
        self.assertEqual(notes, ['当前文章只读取了部分正文，以上仅总结已读取内容。'])
