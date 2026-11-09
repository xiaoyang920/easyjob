"""Bounded auditor contract repair and coherent partial delivery; no live calls."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import test_grounding as fixtures
from app.graph.state_factory import create_initial_state
from app.services import grounding, agent_events
from app.services.execution_facts import execution_facts

CID = 'lookup:1'
OTHER = 'lookup:2'
SOURCES = [{'id': CID, 'content': '可用资料。'}, {'id': OTHER, 'content': '可用资料。'}]


def initial_state():
    state = create_initial_state(7, '查询最新资料', [])
    state['evidence_contents'] = {source['id']: source['content'] for source in SOURCES}
    return state


def response_for(text, *, missing=False, wrong_source=False):
    blocks = grounding.text_blocks(text)
    catalog = grounding.evidence_catalog(SOURCES)
    groups = grounding.review_units(blocks)
    response = []
    for i, group in enumerate(groups):
        claims = []
        for unit in group:
            heading = unit['text'].startswith('#')
            refs = unit['citation_ids']
            cid = OTHER if wrong_source and refs else refs[0] if refs else CID
            ids = [key for key, quote in catalog.items() if quote.citation_id == cid]
            claims.append(grounding.ClaimReview(unit_index=unit['unit_index'],
                kind='non_factual' if heading else 'source_fact',
                verdict='non_factual' if heading else 'supported',
                evidence_ids=[] if heading or missing else ids))
        response.append(grounding.BlockReview(block_index=i, claims=claims))
    return grounding.GroundingReview(blocks=response)


class AuditorContractRepairTests(unittest.IsolatedAsyncioTestCase):
    def model(self, responses):
        control = SimpleNamespace(ainvoke=AsyncMock(side_effect=responses))
        model = SimpleNamespace(with_structured_output=lambda *args, **kwargs: control)
        return model, control

    async def test_missing_evidence_is_repaired_with_exact_location_and_same_catalog(self):
        text = f'可用资料。[{CID}]'
        model, control = self.model([response_for(text, missing=True), response_for(text)])
        with patch.object(grounding, 'get_llm', return_value=model):
            review = await grounding.review_text(text, SOURCES, execution_facts({}))
        self.assertFalse(review)
        self.assertEqual(control.ainvoke.await_count, 2)
        messages = control.ainvoke.await_args.args[0]
        original = json.loads(messages[1].content)
        correction = json.loads(messages[-1].content)
        self.assertEqual(correction['errors'], [{'code': 'missing_evidence', 'block_index': 0, 'unit_index': 0}])
        self.assertEqual(correction['allowed_evidence_ids'], [item['id'] for item in original['evidence_catalog']])
        self.assertNotIn('sources', correction)
        self.assertEqual(review.contract_audit['model_calls'], 2)

    async def test_valid_review_adds_no_repair_call(self):
        text = f'可用资料。[{CID}]'
        model, control = self.model([response_for(text)])
        with patch.object(grounding, 'get_llm', return_value=model):
            review = await grounding.review_text(text, SOURCES, execution_facts({}))
        self.assertFalse(review)
        self.assertEqual(control.ainvoke.await_count, 1)

    async def test_two_missing_evidence_outputs_are_not_accepted_or_retried_forever(self):
        text = f'可用资料。[{CID}]'
        model, control = self.model([response_for(text, missing=True)] * 2)
        with patch.object(grounding, 'get_llm', return_value=model), \
             patch.object(agent_events, 'activity', AsyncMock()):
            _, audit = await grounding.verify_delivery(initial_state(), text, SOURCES)
        self.assertEqual(control.ainvoke.await_count, 2)
        self.assertEqual(audit['status'], 'verification_unavailable')
        self.assertEqual(audit['failure_detail'], 'missing_evidence')
        self.assertEqual(audit['review_calls'], 2)
        self.assertEqual(audit['review_format_repair_calls'], 1)
        self.assertEqual(audit['repair_calls'], 0)

    async def test_repaired_auditor_still_rejects_unknown_evidence(self):
        text = f'可用资料。[{CID}]'
        invalid = response_for(text)
        invalid.blocks[0].claims[0].evidence_ids = ['invented']
        model, control = self.model([response_for(text, missing=True), invalid])
        with patch.object(grounding, 'get_llm', return_value=model), \
             patch.object(agent_events, 'activity', AsyncMock()):
            _, audit = await grounding.verify_delivery(initial_state(), text, SOURCES)
        self.assertEqual(control.ainvoke.await_count, 2)
        self.assertEqual(audit['status'], 'verification_unavailable')
        self.assertEqual(audit['failure_detail'], 'unknown_evidence')

    async def test_reaudit_contract_repair_preserves_complete_candidate_and_counts_calls(self):
        original = f'## 一、最新情况\n\n可用资料。[{CID}]\n\n## 二、背景\n\n可用资料。[{CID}]'
        fixed = original.replace(f'[{CID}]', f'[{OTHER}]')
        # This test targets the content-repair path. A source-selection mismatch
        # now first receives a separate, scoped auditor recheck.
        rejected = response_for(original)
        rejected.blocks[1].claims[0].verdict = 'unsupported'
        model, control = self.model([rejected,
                                    response_for(fixed, missing=True), response_for(fixed)])
        with patch.object(grounding, 'get_llm', return_value=model), \
             patch.object(grounding, 'repair_text', AsyncMock(return_value=fixed)) as repair, \
             patch.object(agent_events, 'activity', AsyncMock()):
            text, audit = await grounding.verify_delivery(initial_state(), original, SOURCES)
        self.assertEqual(text, fixed)
        self.assertEqual(audit['status'], 'repaired')
        self.assertEqual(audit['review_calls'], 3)
        self.assertEqual(audit['review_format_repair_calls'], 1)
        self.assertEqual(audit['repair_calls'], 1)
        self.assertEqual(control.ainvoke.await_count, 3)
        repair.assert_awaited_once()

    async def test_timeout_and_permission_errors_do_not_trigger_format_retry(self):
        for error in (TimeoutError(), PermissionError('denied')):
            model, control = self.model([error])
            with self.subTest(error=type(error).__name__), \
                 patch.object(grounding, 'get_llm', return_value=model):
                with self.assertRaises(type(error)):
                    await grounding.review_text('可用资料。', SOURCES, execution_facts({}))
                self.assertEqual(control.ainvoke.await_count, 1)

    async def test_cancellation_during_format_retry_propagates(self):
        text = f'可用资料。[{CID}]'
        model, control = self.model([response_for(text, missing=True), asyncio.CancelledError()])
        with patch.object(grounding, 'get_llm', return_value=model):
            with self.assertRaises(asyncio.CancelledError):
                await grounding.review_text(text, SOURCES, execution_facts({}))
        self.assertEqual(control.ainvoke.await_count, 2)

    async def test_retry_timeout_is_reported_as_timeout_with_bounded_call_count(self):
        text = f'可用资料。[{CID}]'
        model, control = self.model([response_for(text, missing=True), TimeoutError()])
        with patch.object(grounding, 'get_llm', return_value=model), \
             patch.object(agent_events, 'activity', AsyncMock()):
            _, audit = await grounding.verify_delivery(initial_state(), text, SOURCES)
        self.assertEqual(control.ainvoke.await_count, 2)
        self.assertEqual(audit['reason_code'], 'timeout')
        self.assertEqual(audit['review_calls'], 2)
        self.assertEqual(audit['review_format_repair_calls'], 1)

    async def test_permission_failure_during_retry_is_terminal(self):
        text = f'可用资料。[{CID}]'
        model, control = self.model([response_for(text, missing=True), PermissionError('denied')])
        with patch.object(grounding, 'get_llm', return_value=model), \
             patch.object(agent_events, 'activity', AsyncMock()):
            with self.assertRaises(PermissionError):
                await grounding.verify_delivery(initial_state(), text, SOURCES)
        self.assertEqual(control.ainvoke.await_count, 2)

    async def test_genuinely_missing_support_can_return_uncertainty_instead_of_fake_evidence(self):
        text = f'可用资料。[{CID}]'
        uncertain = response_for(text, missing=True)
        claim = uncertain.blocks[0].claims[0]
        claim.verdict, claim.issue_code = 'uncertain', 'insufficient_evidence'
        claim.missing_information = 'supporting_source'
        model, control = self.model([response_for(text, missing=True), uncertain])
        with patch.object(grounding, 'get_llm', return_value=model):
            review = await grounding.review_text(text, SOURCES, execution_facts({}))
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]['verdict'], 'uncertain')
        self.assertFalse(review[0]['hard_error'])
        self.assertEqual(control.ainvoke.await_count, 2)

    async def test_normal_knowledge_still_needs_no_source_id(self):
        text = '普通概念解释。'
        response = response_for(text, missing=True)
        response.blocks[0].claims[0].kind = 'general_knowledge'
        model, control = self.model([response])
        with patch.object(grounding, 'get_llm', return_value=model):
            review = await grounding.review_text(text, SOURCES, execution_facts({}))
        self.assertFalse(review)
        self.assertEqual(control.ainvoke.await_count, 1)


class PartialStructureTests(unittest.TestCase):
    def test_removed_leading_sections_leave_no_jump_or_dangling_references(self):
        blocks = {0: '下面是全部最新情况。', 1: '## 一、更新', 2: '',
                  3: '## 二、剧场版', 4: '', 5: '## 三、背景', 6: '可用资料。',
                  7: '## 四、提醒', 8: '- 上述更新安排以官方为准。',
                  9: '## 五、其他', 10: '```text\n完整代码\n```'}
        review = grounding.ReviewIssues([], blocks, substantive=3)
        retained = grounding.retained_answer(review, execution_facts({}))
        self.assertIn('## 背景', retained)
        self.assertIn('可用资料。', retained)
        self.assertIn('```text\n完整代码\n```', retained)
        for removed in ('## 三、', '## 四、', '## 五、', '上述更新', '全部最新情况', '## 四、提醒'):
            self.assertNotIn(removed, retained)

    def test_intact_numbered_sections_are_preserved_exactly(self):
        text = '## 一、背景\n\n可靠说明。\n\n## 二、提醒\n\n上述说明仅作参考。'
        blocks = dict(enumerate(grounding.text_blocks(text)))
        review = grounding.ReviewIssues([], blocks, substantive=2)
        self.assertEqual(grounding.retained_answer(review, execution_facts({})), text)

