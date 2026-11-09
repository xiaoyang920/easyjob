"""Source-selection mistakes are rechecked before editing the author's answer."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import grounding, agent_events
from test_grounding_contract_repair import CID, OTHER, SOURCES, initial_state, response_for


def first_only(response):
    return grounding.GroundingReview(blocks=[response.blocks[0]])


class CitationRecheckTests(unittest.IsolatedAsyncioTestCase):
    async def deliver(self, original, responses, fixed=None):
        control = SimpleNamespace(ainvoke=AsyncMock(side_effect=responses))
        model = SimpleNamespace(with_structured_output=lambda *args, **kwargs: control)
        with patch.object(grounding, 'get_llm', return_value=model), \
             patch.object(grounding, 'repair_text', AsyncMock(return_value=fixed or original)) as repair, \
             patch.object(agent_events, 'activity', AsyncMock()):
            text, audit = await grounding.verify_delivery(initial_state(), original, SOURCES)
        return text, audit, control, repair

    async def test_other_source_selection_keeps_correct_original_without_content_repair(self):
        original = f'可用资料。[{CID}]\n\n可用资料。[{OTHER}]'
        initial = response_for(original)
        initial.blocks[0].claims[0].evidence_ids = response_for(original, wrong_source=True).blocks[0].claims[0].evidence_ids
        text, audit, control, repair = await self.deliver(original, [initial, first_only(response_for(original))])
        self.assertEqual(text, original)
        self.assertEqual(audit['status'], 'verified')
        self.assertEqual(audit['review_calls'], 2)
        self.assertEqual(audit['citation_recheck_calls'], 1)
        self.assertNotIn('review_format_repair_calls', audit)
        repair.assert_not_awaited()
        payload = json.loads(control.ainvoke.await_args.args[0][1].content)
        self.assertEqual(payload['kind'], 'citation_source_recheck')
        self.assertEqual([block['block_index'] for block in payload['blocks']], [0])
        self.assertEqual([source['id'] for source in payload['sources']], [CID])
        self.assertEqual({span['citation_id'] for span in payload['evidence_catalog']}, {CID})
        self.assertEqual(payload['blocks'][0]['units'][0]['allowed_evidence_ids'],
                         [span['id'] for span in payload['evidence_catalog']])
        record = audit['citation_rechecks'][0]
        self.assertEqual((record['citation_ids'], record['evidence_citation_ids']), ([CID], [OTHER]))
        self.assertEqual((record['outcome'], record['phase']), ('matched', 'review'))
        self.assertNotIn('可用资料', json.dumps(audit, ensure_ascii=False))

    async def test_original_source_rejected_then_content_repaired_and_reaudited(self):
        original, fixed = f'可用资料。[{CID}]', f'可用资料。[{OTHER}]'
        rejected = response_for(original)
        rejected.blocks[0].claims[0].verdict = 'unsupported'
        rejected.blocks[0].claims[0].evidence_ids = []
        text, audit, control, repair = await self.deliver(original,
            [response_for(original, wrong_source=True), rejected, response_for(fixed)], fixed)
        self.assertEqual(text, fixed)
        self.assertEqual(audit['status'], 'repaired')
        self.assertEqual((audit['review_calls'], audit['citation_recheck_calls'], audit['repair_calls']), (3, 1, 1))
        repair.assert_awaited_once()
        self.assertEqual(audit['citation_rechecks'][0]['outcome'], 'not_supported')

    async def test_repeated_mismatch_is_unavailable_not_false_content_and_never_auto_rebound(self):
        original = f'可用资料。[{CID}]\n\n可用资料。[{OTHER}]'
        initial = response_for(original)
        initial.blocks[0].claims[0].evidence_ids = response_for(original, wrong_source=True).blocks[0].claims[0].evidence_ids
        text, audit, control, repair = await self.deliver(original,
            [initial, first_only(response_for(original, wrong_source=True))])
        self.assertEqual(control.ainvoke.await_count, 2)
        repair.assert_not_awaited()
        self.assertEqual(audit['reason_code'], 'citation_unverified')
        self.assertEqual(audit['citation_rechecks'][0]['outcome'], 'unresolved')
        self.assertNotIn('与依据或执行记录不符', text)
        self.assertIn('引用尚未核对清楚', text)
        self.assertIn(f'可用资料。[{OTHER}]', text)
        self.assertNotIn(f'[{CID}]', text)
        self.assertEqual(audit['initial_findings'][0]['evidence_citation_ids'], [OTHER])

    async def test_recheck_timeout_retains_other_verified_units(self):
        original = f'可用资料。[{CID}]\n\n可用资料。[{OTHER}]'
        initial = response_for(original)
        initial.blocks[0].claims[0].evidence_ids = response_for(original, wrong_source=True).blocks[0].claims[0].evidence_ids
        text, audit, control, repair = await self.deliver(original, [initial, TimeoutError()])
        self.assertEqual(control.ainvoke.await_count, 2)
        repair.assert_not_awaited()
        self.assertEqual(audit['reason_code'], 'timeout')
        self.assertEqual(audit['citation_rechecks'][0]['outcome'], 'pending')
        self.assertIn(f'可用资料。[{OTHER}]', text)
        self.assertNotIn(f'[{CID}]', text)
        self.assertNotIn('与依据或执行记录不符', text)

    async def test_unknown_evidence_and_extra_units_do_not_escape_scoped_validation(self):
        original = f'可用资料。[{CID}]\n\n可用资料。[{OTHER}]'
        initial = response_for(original)
        initial.blocks[0].claims[0].evidence_ids = response_for(original, wrong_source=True).blocks[0].claims[0].evidence_ids
        unknown = first_only(response_for(original))
        unknown.blocks[0].claims[0].evidence_ids = ['invented']
        for response, detail in [(unknown, 'unknown_evidence'), (response_for(original), 'block_coverage')]:
            with self.subTest(detail=detail):
                text, audit, control, repair = await self.deliver(original, [initial, response])
                self.assertEqual(audit['failure_detail'], detail)
                self.assertEqual(control.ainvoke.await_count, 2)
                self.assertNotIn(f'[{CID}]', text)
                repair.assert_not_awaited()

    async def test_recheck_after_content_repair_preserves_corrected_answer(self):
        original, fixed = f'错误资料。[{CID}]', f'可用资料。[{CID}]'
        initial = response_for(original)
        initial.blocks[0].claims[0].verdict = 'contradicted'
        text, audit, _, repair = await self.deliver(original,
            [initial, response_for(fixed, wrong_source=True), response_for(fixed)], fixed)
        self.assertEqual(text, fixed)
        self.assertEqual(audit['status'], 'repaired')
        self.assertEqual(audit['citation_rechecks'][0]['phase'], 'review_after_repair')
        self.assertEqual(audit['review_calls'], 3)
        repair.assert_awaited_once()

    async def test_cancel_and_permission_failure_are_terminal_during_recheck(self):
        original = f'可用资料。[{CID}]'
        for error in (asyncio.CancelledError(), PermissionError('denied')):
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                await self.deliver(original, [response_for(original, wrong_source=True), error])

    def test_reference_diagnostics_are_bounded_and_do_not_copy_claims(self):
        rows = grounding.issue_locations([{'block_index': 0, 'unit_index': 1,
            'citation_ids': ['x' * 1000] * 100, 'evidence_citation_ids': [OTHER],
            'statement': 'private', 'reason': 'private', 'quotes': ['private']}])
        self.assertEqual(len(rows[0]['citation_ids']), 16)
        self.assertEqual(len(rows[0]['citation_ids'][0]), 256)
        self.assertNotIn('private', json.dumps(rows))
